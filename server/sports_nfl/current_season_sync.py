"""Locked, model-free orchestration for the NFL current-season foundation.

The acquisition/canonical/Gold/registry pipeline owns evidence publication.
This module only decides whether that existing pipeline needs to run, records
bounded operational health, and proves the resulting source/foundation
authority before declaring success.  Source probes inspect GitHub release
metadata; they do not download an asset.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from server.sports_cockpit.interprocess_lock import interprocess_lock
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes

from .bronze_acquisition import (
    NflBronzeError,
    ReleaseCache,
    discover_release_asset,
    verify_nflverse_bronze,
)
from .pipeline import NflFoundationConfig, build_nfl_foundation
from .publication import verify_foundation
from .registry import NFL_DATASET_ID
from .source_contracts import (
    MANDATORY_FAMILIES,
    NFLVERSE_SOURCE_FAMILIES,
    SourceFamilyContract,
    source_families_for_manifest,
    source_contract_for_partition,
)


LATEST_COMPLETED = "latest-completed"
LOCK_BUSY_EXIT = 75
REPORT_CONTRACT = "ASP_NFL_CURRENT_SEASON_SYNC_REPORT_V1"
SOURCE_SNAPSHOT_CONTRACT = "ASP_NFL_SOURCE_METADATA_SNAPSHOT_V1"

NIGHTLY = "nightly"
THURSDAY_CORRECTION = "thursday-correction"
SCHEDULE_REFRESH = "schedule-refresh"
CATCH_UP = "catch-up"
SYNC_MODES = (NIGHTLY, THURSDAY_CORRECTION, SCHEDULE_REFRESH, CATCH_UP)


class NflCurrentSeasonSyncError(RuntimeError):
    """A current-season orchestration invariant failed."""


@dataclass(frozen=True)
class NflCurrentSeasonSyncConfig:
    foundation: NflFoundationConfig = field(default_factory=NflFoundationConfig)
    through: str = LATEST_COMPLETED
    mode: str = NIGHTLY
    report_root: Path = Path(r".runtime\asp-model-studio\nfl-current-season-sync")
    lock_path: Path = Path(r".runtime\asp-model-studio\locks\nfl-current-season-sync.lock")

    def __post_init__(self) -> None:
        if self.mode not in SYNC_MODES:
            raise ValueError(f"mode must be one of: {', '.join(SYNC_MODES)}")
        through = str(self.through).strip()
        if not through:
            raise ValueError("through must be latest-completed or YYYY-MM-DD")
        if through != LATEST_COMPLETED:
            try:
                date.fromisoformat(through)
            except ValueError as exc:
                raise ValueError("through must be latest-completed or YYYY-MM-DD") from exc
        if not self.foundation.seasons:
            raise ValueError("foundation seasons must not be empty")

    @property
    def current_season(self) -> int:
        return max(int(value) for value in self.foundation.seasons)


InspectAuthority = Callable[[NflCurrentSeasonSyncConfig], dict[str, Any]]
ProbeSources = Callable[[NflCurrentSeasonSyncConfig], dict[str, Any]]
BuildFoundation = Callable[[NflFoundationConfig], dict[str, Any]]
VerifyPrior = Callable[[NflCurrentSeasonSyncConfig, Mapping[str, Any]], bool]


@dataclass(frozen=True)
class NflCurrentSeasonSyncDependencies:
    inspect_authority: InspectAuthority
    probe_sources: ProbeSources
    build_foundation: BuildFoundation
    verify_prior: VerifyPrior
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    try:
        with temporary.open("wb") as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _record_attempt(config: NflCurrentSeasonSyncConfig, report: Mapping[str, Any]) -> None:
    root = Path(config.report_root)
    _atomic_json(root / "latest-attempt.json", report)
    if report.get("status") in {"COMPLETE", "NO_OP"}:
        _atomic_json(root / "latest-success.json", report)


def _clock_text(clock: Callable[[], datetime]) -> str:
    observed = clock()
    if observed.tzinfo is None:
        raise NflCurrentSeasonSyncError("sync clock must be timezone-aware")
    return observed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _allowed_family_ids(config: NflCurrentSeasonSyncConfig) -> tuple[str, ...]:
    allowed = (
        tuple(NFLVERSE_SOURCE_FAMILIES)
        if config.foundation.include_optional
        else tuple(MANDATORY_FAMILIES)
    )
    if config.mode == SCHEDULE_REFRESH:
        selected = {"schedules"}
    elif config.mode == THURSDAY_CORRECTION:
        selected = {
            "schedules",
            "play_by_play",
            "weekly_player_stats",
            "weekly_team_stats",
        }
    else:
        selected = set(allowed)
    return tuple(value for value in allowed if value in selected)


def _available_seasons(
    config: NflCurrentSeasonSyncConfig,
    contract: SourceFamilyContract,
) -> tuple[int, ...]:
    requested = tuple(sorted(set(int(value) for value in config.foundation.seasons)))
    candidates = requested if config.mode == CATCH_UP else (config.current_season,)
    available = tuple(
        season
        for season in candidates
        if not (
            contract.available_start_season is not None
            and season < contract.available_start_season
        )
        and not (
            contract.available_end_season is not None
            and season > contract.available_end_season
        )
    )
    if contract.season_scoped:
        return available
    # Combined all-season releases are probed using the latest configured
    # season inside their declared availability window, matching acquisition.
    if available:
        return (available[-1],)
    eligible = tuple(
        season
        for season in requested
        if (contract.available_start_season is None or season >= contract.available_start_season)
        and (contract.available_end_season is None or season <= contract.available_end_season)
    )
    return (eligible[-1],) if eligible else ()


def _source_scope(config: NflCurrentSeasonSyncConfig, families=NFLVERSE_SOURCE_FAMILIES) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for family_id in _allowed_family_ids(config):
        contract = families[family_id]
        result.append(
            {
                "familyId": family_id,
                "releaseTag": contract.release_tag,
                "contractVersion": contract.contract_version,
                "seasonScoped": contract.season_scoped,
                "availableStartSeason": contract.available_start_season,
                "availableEndSeason": contract.available_end_season,
                "selectedSeasons": list(_available_seasons(config, contract)),
            }
        )
    return result


def _asset_record(
    contract: SourceFamilyContract,
    season: int,
    asset: Any | None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "familyId": contract.family_id,
        "season": season if contract.season_scoped else None,
        "releaseTag": contract.release_tag,
        "contractVersion": contract.contract_version,
    }
    if asset is None:
        return {**record, "status": "RELEASE_ASSET_ABSENT"}
    return {
        **record,
        "status": "COMPLETE",
        "releasePublishedAt": asset.release_published_at,
        "assetId": asset.asset_id,
        "assetUpdatedAt": asset.asset_updated_at,
        "sourceDigest": asset.source_digest,
        "assetName": asset.name,
        "sourceUrl": asset.source_url,
        "byteCount": asset.byte_count,
    }


def _partition_record(
    contract: SourceFamilyContract,
    season: int,
    partition: Mapping[str, Any] | None,
    *,
    missing_reason: str | None,
) -> dict[str, Any]:
    if partition is None:
        if contract.mandatory or missing_reason is None:
            raise NflCurrentSeasonSyncError(
                f"verified Bronze lacks an outcome for {contract.family_id}/{season}"
            )
        return {**_asset_record(contract, season, None), "status": missing_reason}
    return {
        "familyId": contract.family_id,
        "season": season if contract.season_scoped else None,
        "releaseTag": partition.get("releaseTag"),
        "contractVersion": partition.get("sourceContractVersion"),
        "status": partition.get("status"),
        "releasePublishedAt": partition.get("releasePublishedAt"),
        "assetId": partition.get("assetId"),
        "assetUpdatedAt": partition.get("assetUpdatedAt"),
        "sourceDigest": partition.get("sourceDigest"),
        "assetName": partition.get("assetName"),
        "sourceUrl": partition.get("sourceUrl"),
        "byteCount": partition.get("byteCount"),
    }


def _snapshot(
    config: NflCurrentSeasonSyncConfig,
    records: list[dict[str, Any]],
    families=NFLVERSE_SOURCE_FAMILIES,
) -> dict[str, Any]:
    body = {
        "contract": SOURCE_SNAPSHOT_CONTRACT,
        "currentSeason": config.current_season,
        "includeOptional": config.foundation.include_optional,
        "scope": _source_scope(config, families),
        "assets": sorted(
            records,
            key=lambda item: (str(item["familyId"]), int(item.get("season") or 0)),
        ),
    }
    return {
        **body,
        "sourceSnapshotIdentity": sha256_bytes(canonical_json_bytes(body)),
    }


def _default_probe_sources(config: NflCurrentSeasonSyncConfig) -> dict[str, Any]:
    cache: ReleaseCache = {}
    records: list[dict[str, Any]] = []
    for family_id in _allowed_family_ids(config):
        contract = NFLVERSE_SOURCE_FAMILIES[family_id]
        for season in _available_seasons(config, contract):
            partition_contract = source_contract_for_partition(
                NFLVERSE_SOURCE_FAMILIES, family_id, season if contract.season_scoped else None)
            try:
                asset = discover_release_asset(
                    partition_contract,
                    season,
                    release_cache=cache,
                )
            except (NflBronzeError, OSError, ValueError):
                if contract.mandatory:
                    raise
                records.append({
                    **_asset_record(partition_contract, season, None),
                    # Keep the metadata probe's failure vocabulary identical
                    # to the governed Bronze outcome emitted by acquisition.
                    # Otherwise a repeated optional discovery outage can never
                    # reconcile to NO_OP even when authority is unchanged.
                    "status": "SOURCE_DISCOVERY_FAILURE",
                })
                continue
            records.append(_asset_record(partition_contract, season, asset))
    return _snapshot(config, records)


def _snapshot_from_bronze(
    config: NflCurrentSeasonSyncConfig,
    bronze: Mapping[str, Any],
) -> dict[str, Any]:
    families = source_families_for_manifest(bronze)
    requested = set(str(value) for value in bronze.get("requestedFamilies") or [])
    expected_requested = set(
        NFLVERSE_SOURCE_FAMILIES
        if config.foundation.include_optional
        else MANDATORY_FAMILIES
    )
    if requested != expected_requested:
        raise NflCurrentSeasonSyncError(
            "verified Bronze family scope differs from the sync configuration"
        )
    configured_seasons = sorted(set(int(value) for value in config.foundation.seasons))
    if list(bronze.get("seasons") or []) != configured_seasons:
        raise NflCurrentSeasonSyncError(
            "verified Bronze season scope differs from the sync configuration"
        )
    partitions = {
        (str(item.get("familyId")), item.get("season")): item
        for item in bronze.get("partitions") or []
        if isinstance(item, Mapping)
    }
    missing = {
        (str(item.get("familyId")), item.get("season")): str(item.get("reason"))
        for item in bronze.get("optionalMissing") or []
        if isinstance(item, Mapping)
    }
    records: list[dict[str, Any]] = []
    for family_id in _allowed_family_ids(config):
        if family_id not in requested:
            raise NflCurrentSeasonSyncError(
                f"verified Bronze did not request source family {family_id}"
            )
        contract = families[family_id]
        for season in _available_seasons(config, contract):
            key = (family_id, season if contract.season_scoped else None)
            records.append(
                _partition_record(
                    contract,
                    season,
                    partitions.get(key),
                    missing_reason=missing.get(key),
                )
            )
    return _snapshot(config, records, families)


def _registration_for_manifest(database_path: Path, manifest_sha: str) -> dict[str, Any] | None:
    path = Path(database_path).resolve()
    if not path.is_file():
        return None
    uri = f"file:{path.as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT registration_id, dataset_id, dataset_version_id,
                   manifest_sha, validation_status, active
            FROM sports_dataset_registrations
            WHERE dataset_id = ? AND manifest_sha = ?
            """,
            (NFL_DATASET_ID, manifest_sha),
        ).fetchall()
    finally:
        connection.close()
    if len(rows) != 1:
        return None
    return dict(rows[0])


def _default_inspect_authority(config: NflCurrentSeasonSyncConfig) -> dict[str, Any]:
    bronze_current = config.foundation.bronze_root / "current.json"
    foundation_current = config.foundation.foundation_root / "current.json"
    if not bronze_current.is_file() or not foundation_current.is_file():
        return {"status": "MISSING"}
    try:
        bronze = verify_nflverse_bronze(config.foundation.bronze_root)
        bronze_sha = sha256_bytes(canonical_json_bytes(bronze))
        foundation = verify_foundation(config.foundation.foundation_root)
        manifest = foundation["manifest"]
        if manifest.get("sourceManifestSha256") != bronze_sha:
            raise NflCurrentSeasonSyncError(
                "current foundation is not bound to current verified Bronze"
            )
        governance = manifest.get("governance") or {}
        if (
            governance.get("modelFitOccurred") is not False
            or governance.get("modelScoringOccurred") is not False
            or governance.get("promotionEligible") is not False
        ):
            raise NflCurrentSeasonSyncError(
                "current foundation is not model-free research authority"
            )
        registration = _registration_for_manifest(
            config.foundation.database_path,
            foundation["manifestSha256"],
        )
        if registration is None:
            raise NflCurrentSeasonSyncError(
                "current foundation lacks one matching warehouse registration"
            )
        if (
            registration.get("validation_status") != "VALID"
            or registration.get("active") not in {0, False}
            or registration.get("dataset_version_id") != foundation["datasetVersionId"]
        ):
            raise NflCurrentSeasonSyncError(
                "current warehouse registration state differs"
            )
        source = _snapshot_from_bronze(config, bronze)
        coverage = dict(manifest.get("coverage") or {})
        return {
            "status": "VERIFIED",
            "sourceSnapshotIdentity": source["sourceSnapshotIdentity"],
            "sourceAssets": source["assets"],
            "bronzeManifestSha256": bronze_sha,
            "foundationManifestSha256": foundation["manifestSha256"],
            "datasetVersionId": foundation["datasetVersionId"],
            "registrationIdentity": registration["registration_id"],
            "currentSeasonScheduledGames": coverage.get("currentSeasonScheduledGames"),
            "currentSeasonCompletedGames": coverage.get("currentSeasonCompletedGames"),
            "maximumDate": coverage.get("maximumDate"),
            "modelsFitted": 0,
        }
    except Exception as exc:
        return {
            "status": "INVALID",
            "errorType": type(exc).__name__,
            "error": str(exc)[:500],
        }


def _default_verify_prior(
    config: NflCurrentSeasonSyncConfig,
    prior: Mapping[str, Any],
) -> bool:
    try:
        bronze_sha = str(prior.get("bronzeManifestSha256") or "")
        foundation_sha = str(prior.get("foundationManifestSha256") or "")
        if not bronze_sha or not foundation_sha:
            return False
        bronze = verify_nflverse_bronze(config.foundation.bronze_root, bronze_sha)
        if sha256_bytes(canonical_json_bytes(bronze)) != bronze_sha:
            return False
        foundation = verify_foundation(config.foundation.foundation_root, foundation_sha)
        if foundation["manifest"].get("sourceManifestSha256") != bronze_sha:
            return False
        registration = _registration_for_manifest(
            config.foundation.database_path,
            foundation_sha,
        )
        return bool(
            registration
            and registration.get("registration_id") == prior.get("registrationIdentity")
            and registration.get("validation_status") == "VALID"
            and registration.get("active") in {0, False}
        )
    except Exception:
        return False


def default_dependencies() -> NflCurrentSeasonSyncDependencies:
    return NflCurrentSeasonSyncDependencies(
        inspect_authority=_default_inspect_authority,
        probe_sources=_default_probe_sources,
        build_foundation=build_nfl_foundation,
        verify_prior=_default_verify_prior,
    )


def _authority_summary(authority: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "status",
        "sourceSnapshotIdentity",
        "bronzeManifestSha256",
        "foundationManifestSha256",
        "datasetVersionId",
        "registrationIdentity",
        "currentSeasonScheduledGames",
        "currentSeasonCompletedGames",
        "maximumDate",
    )
    return {key: authority.get(key) for key in keys if key in authority}


def _source_summary(source: Mapping[str, Any]) -> dict[str, Any]:
    assets = source.get("assets") or []
    return {
        "sourceSnapshotIdentity": source.get("sourceSnapshotIdentity"),
        "familyCount": len(source.get("scope") or []),
        "assetCount": sum(1 for item in assets if item.get("status") == "COMPLETE"),
        "absentOptionalCount": sum(
            1 for item in assets if item.get("status") == "RELEASE_ASSET_ABSENT"
        ),
        "failedOptionalCount": sum(
            1
            for item in assets
            if item.get("status")
            in {
                "SOURCE_PROBE_FAILURE",
                "SOURCE_DISCOVERY_FAILURE",
                "DOWNLOAD_FAILURE",
                "SCHEMA_INSPECTION_FAILURE",
            }
        ),
        "families": sorted({str(item.get("familyId")) for item in assets}),
    }


def _changed_families(
    before: Mapping[str, Any],
    source: Mapping[str, Any],
) -> list[str]:
    old = {
        (str(item.get("familyId")), item.get("season")): item
        for item in before.get("sourceAssets") or []
    }
    new = {
        (str(item.get("familyId")), item.get("season")): item
        for item in source.get("assets") or []
    }
    return sorted(
        {key[0] for key in set(old) | set(new) if old.get(key) != new.get(key)}
    )


def _mandatory_source_records_match(
    source: Mapping[str, Any],
    authority: Mapping[str, Any],
) -> bool:
    """Allow an optional enrichment failure without weakening core identity."""

    probed = sorted(
        (
            dict(item)
        for item in source.get("assets") or []
        if str(item.get("familyId")) in MANDATORY_FAMILIES
        ),
        key=lambda item: (str(item.get("familyId")), int(item.get("season") or 0)),
    )
    published = sorted(
        (
            dict(item)
        for item in authority.get("sourceAssets") or []
        if str(item.get("familyId")) in MANDATORY_FAMILIES
        ),
        key=lambda item: (str(item.get("familyId")), int(item.get("season") or 0)),
    )
    return bool(probed) and canonical_json_bytes(probed) == canonical_json_bytes(published)


def _model_counts(build: Mapping[str, Any]) -> dict[str, int]:
    counts = {
        "modelsFitted": int(build.get("modelsFitted") or 0),
        "modelsScored": int(build.get("modelsScored") or 0),
        "modelsPromoted": int(build.get("modelsPromoted") or 0),
    }
    if any(counts.values()):
        raise NflCurrentSeasonSyncError(
            "NFL current-season sync encountered model execution or promotion"
        )
    return counts


def _base_report(
    config: NflCurrentSeasonSyncConfig,
    attempted_at: str,
) -> dict[str, Any]:
    return {
        "contract": REPORT_CONTRACT,
        "status": "FAILED",
        "attemptedAtUtc": attempted_at,
        "mode": config.mode,
        "requestedThrough": config.through,
        "currentSeason": config.current_season,
        "modelsFitted": 0,
        "modelsScored": 0,
        "modelsPromoted": 0,
    }


def _failed_report(
    base: Mapping[str, Any],
    *,
    stage: str,
    exc: Exception,
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report = {
        **base,
        "status": "FAILED",
        "failedStage": stage,
        "errorType": type(exc).__name__,
        "error": str(exc)[:500],
    }
    if before is not None:
        report["priorAuthority"] = _authority_summary(before)
    if after is not None:
        report["resultAuthority"] = _authority_summary(after)
        report["warehouseAdvanced"] = (
            bool(
                after.get("registrationIdentity")
                and after.get("registrationIdentity") != before.get("registrationIdentity")
            )
            if before is not None and after.get("status") == "VERIFIED"
            else None
        )
    return report


def _locked_sync(
    config: NflCurrentSeasonSyncConfig,
    deps: NflCurrentSeasonSyncDependencies,
) -> dict[str, Any]:
    attempted_at = _clock_text(deps.clock)
    base = _base_report(config, attempted_at)
    try:
        before = deps.inspect_authority(config)
    except Exception as exc:
        report = _failed_report(base, stage="AUTHORITY_INSPECTION", exc=exc)
        _record_attempt(config, report)
        return report
    try:
        source = deps.probe_sources(config)
        source_identity = str(source.get("sourceSnapshotIdentity") or "")
        if len(source_identity) != 64:
            raise NflCurrentSeasonSyncError("source probe lacks a SHA-256 identity")
    except Exception as exc:
        report = _failed_report(
            base,
            stage="SOURCE_PROBE",
            exc=exc,
            before=before,
        )
        _record_attempt(config, report)
        return report

    changed_families = _changed_families(before, source)
    if (
        before.get("status") == "VERIFIED"
        and before.get("sourceSnapshotIdentity") == source_identity
    ):
        report = {
            **base,
            "status": "NO_OP",
            "sourceChanged": False,
            "changedFamilies": [],
            "sourceProbe": _source_summary(source),
            "priorAuthority": _authority_summary(before),
            "resultAuthority": _authority_summary(before),
            "warehouseAdvanced": False,
        }
        _record_attempt(config, report)
        return report

    try:
        build = deps.build_foundation(config.foundation)
        if build.get("status") != "COMPLETE":
            raise NflCurrentSeasonSyncError("NFL foundation pipeline did not complete")
        counts = _model_counts(build)
        after = deps.inspect_authority(config)
        if after.get("status") != "VERIFIED":
            raise NflCurrentSeasonSyncError(
                "rebuilt NFL foundation authority did not independently verify"
            )
        optional_gap_only = (
            after.get("sourceSnapshotIdentity") != source_identity
            and _mandatory_source_records_match(source, after)
        )
        if after.get("sourceSnapshotIdentity") != source_identity and not optional_gap_only:
            raise NflCurrentSeasonSyncError(
                "rebuilt NFL foundation does not bind the probed source snapshot"
            )
        authority_advanced = (
            after.get("foundationManifestSha256")
            != before.get("foundationManifestSha256")
        )
        if before.get("status") == "VERIFIED":
            if not authority_advanced and not optional_gap_only:
                raise NflCurrentSeasonSyncError(
                    "changed NFL source did not create a new immutable foundation version"
                )
            if not deps.verify_prior(config, before):
                raise NflCurrentSeasonSyncError(
                    "prior NFL source/foundation/registration authority no longer verifies"
                )
        report = {
            **base,
            **counts,
            "status": "COMPLETE" if authority_advanced else "NO_OP",
            "sourceChanged": authority_advanced,
            "changedFamilies": changed_families,
            "sourceProbe": _source_summary(source),
            "priorAuthority": _authority_summary(before),
            "resultAuthority": _authority_summary(after),
            "warehouseAdvanced": (
                after.get("registrationIdentity") != before.get("registrationIdentity")
            ),
            "historicalAuthorityPreserved": (
                True if before.get("status") == "VERIFIED" else None
            ),
            "optionalSourceGapAccepted": optional_gap_only,
            "optionalProbeIncomplete": optional_gap_only and not authority_advanced,
        }
        _record_attempt(config, report)
        return report
    except Exception as exc:
        try:
            after = deps.inspect_authority(config)
        except Exception:
            after = {"status": "INVALID"}
        # The existing pipeline registers transactionally.  If it raised only
        # after completing its own final operational-report write, independently
        # verified source/foundation/registration authority is still the durable
        # result.  Recover that narrow case instead of falsely calling an
        # already-committed warehouse version a failed advancement.  A returned
        # but invalid build report (including any model execution) is never
        # recoverable here.
        build_never_returned = "build" not in locals()
        try:
            prior_preserved = (
                before.get("status") != "VERIFIED"
                or deps.verify_prior(config, before)
            )
        except Exception:
            prior_preserved = False
        if (
            build_never_returned
            and after.get("status") == "VERIFIED"
            and (
                after.get("sourceSnapshotIdentity") == source_identity
                or _mandatory_source_records_match(source, after)
            )
            and prior_preserved
        ):
            recovered_advanced = (
                after.get("foundationManifestSha256")
                != before.get("foundationManifestSha256")
            )
            report = {
                **base,
                "status": "COMPLETE" if recovered_advanced else "NO_OP",
                "sourceChanged": recovered_advanced,
                "changedFamilies": changed_families,
                "sourceProbe": _source_summary(source),
                "priorAuthority": _authority_summary(before),
                "resultAuthority": _authority_summary(after),
                "warehouseAdvanced": (
                    after.get("registrationIdentity")
                    != before.get("registrationIdentity")
                ),
                "historicalAuthorityPreserved": (
                    True if before.get("status") == "VERIFIED" else None
                ),
                "recoveredAfterPipelineException": True,
                "optionalProbeIncomplete": not recovered_advanced,
                "pipelineWarningType": type(exc).__name__,
                "pipelineWarning": str(exc)[:500],
            }
            _record_attempt(config, report)
            return report
        report = _failed_report(
            base,
            stage="FOUNDATION_BUILD",
            exc=exc,
            before=before,
            after=after,
        )
        report.update(
            {
                "sourceChanged": before.get("sourceSnapshotIdentity") != source_identity,
                "changedFamilies": changed_families,
                "sourceProbe": _source_summary(source),
            }
        )
        if "build" in locals() and isinstance(build, Mapping):
            for key in ("modelsFitted", "modelsScored", "modelsPromoted"):
                report[key] = int(build.get(key) or 0)
        _record_attempt(config, report)
        return report


def sync_nfl_current_season(
    config: NflCurrentSeasonSyncConfig = NflCurrentSeasonSyncConfig(),
    *,
    dependencies: NflCurrentSeasonSyncDependencies | None = None,
) -> dict[str, Any]:
    """Run one nonblocking, locked current-season sync attempt."""

    deps = dependencies or default_dependencies()
    with interprocess_lock(
        config.lock_path,
        blocking=False,
        stale_after=12 * 60 * 60,
    ):
        return _locked_sync(config, deps)


__all__ = [
    "CATCH_UP",
    "LATEST_COMPLETED",
    "LOCK_BUSY_EXIT",
    "NIGHTLY",
    "NflCurrentSeasonSyncConfig",
    "NflCurrentSeasonSyncDependencies",
    "NflCurrentSeasonSyncError",
    "SCHEDULE_REFRESH",
    "SYNC_MODES",
    "THURSDAY_CORRECTION",
    "sync_nfl_current_season",
]
