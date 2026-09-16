"""Concrete provider/data bindings for the model-free nightly Statcast sync."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import pyarrow.csv as pacsv

from server.persistence.db import Database, json_loads
from server.sports_current_statcast.contextual_gold import (
    CONTEXT_GOLD_DATASET_ID,
    build_contextual_gold,
    verify_contextual_gold,
)
from server.sports_current_statcast.gold import build_current_gold, verify_current_gold
from server.sports_current_statcast.pipeline import build_current_silver, verify_current_silver
from server.sports_datasets.current_statcast import (
    CURRENT_STATCAST_DATASET_ID,
    CurrentStatcastDatasetRegistry,
    build_current_statcast_warehouse_manifest,
)
from tools.bronze_acquisition.acquire import SOURCE_TERMS
from tools.bronze_acquisition.download import http_download, sha256_file
from tools.bronze_acquisition.manifest import BronzeManifest, inspect_csv, utc_now
from tools.bronze_acquisition.schedule_authority import (
    COMPLETED_DETAILED_STATES,
    acquire_schedule_authority,
    nightly_schedule_url,
    parse_schedule_payload,
)
from tools.bronze_acquisition.safety import (
    assert_nightly_current_statcast_date_allowed,
    contained_path,
)
from tools.bronze_acquisition.sources import (
    STATCAST_ROW_CAP,
    nightly_current_statcast_partitions,
)

from .incremental import CurrentStatcastSyncConfig, CurrentStatcastSyncDependencies, LATEST_COMPLETED


class CurrentStatcastSyncRuntimeError(RuntimeError):
    """A concrete acquisition/publication invariant failed closed."""


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentStatcastSyncRuntimeError(f"invalid JSON authority: {path}") from exc
    if not isinstance(payload, dict):
        raise CurrentStatcastSyncRuntimeError(f"JSON authority is not an object: {path}")
    return payload


def _locator(root: Path) -> dict[str, Any]:
    return _json(Path(root) / "current.json")


def _optional_locator(root: Path) -> dict[str, Any]:
    path = Path(root) / "current.json"
    return _json(path) if path.is_file() else {}


def _current_manifest(root: Path) -> tuple[str, dict[str, Any]]:
    locator = _locator(root)
    manifest_sha = str(locator.get("manifestSha256") or locator.get("currentManifestSha256") or "")
    path = Path(root) / "publications" / "sha256" / manifest_sha / "manifest.json"
    if not path.is_file() or sha256_file(path) != manifest_sha:
        raise CurrentStatcastSyncRuntimeError(f"current publication is not content-addressed: {root}")
    return manifest_sha, _json(path)


def _current_registration(config: CurrentStatcastSyncConfig) -> dict[str, Any] | None:
    database = Database(config.database_path)
    database.initialize()
    with database.connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM sports_dataset_registrations
            WHERE dataset_id = ? AND validation_status = 'VALID'
            ORDER BY registered_at DESC, registration_id DESC LIMIT 1
            """,
            (CURRENT_STATCAST_DATASET_ID,),
        ).fetchone()
    if row is None:
        return None
    record = dict(row)
    record["metadata_json"] = json_loads(record.get("metadata_json"), {})
    return record


def _coverage_snapshot(config: CurrentStatcastSyncConfig) -> dict[str, Any]:
    silver_sha, silver = _current_manifest(config.current_silver_root)
    gold_sha, gold = _current_manifest(config.current_gold_root)
    contextual_locator = _optional_locator(config.contextual_gold_root)
    contextual_sha = str(
        contextual_locator.get("manifestSha256")
        or contextual_locator.get("currentManifestSha256")
        or ""
    )
    registration = _current_registration(config)
    partitions = list(silver.get("partitions") or [])
    return {
        "earliestDate": (silver.get("dateCoverage") or {}).get("earliestDate"),
        "latestDate": (silver.get("dateCoverage") or {}).get("latestDate"),
        "silverPartitionCount": len(partitions),
        "completeEmptyPartitionCount": sum(
            str(item.get("sourceStatus")) == "COMPLETE_EMPTY" for item in partitions
        ),
        "sourcePitchRows": int((silver.get("counts") or {}).get("sourcePitchRows") or 0),
        "acceptedPitchRows": int((silver.get("counts") or {}).get("acceptedPitchRows") or 0),
        "acceptedPlateAppearances": int(
            (silver.get("counts") or {}).get("acceptedPlateAppearances") or 0
        ),
        "rejectedPlateAppearances": int(
            (silver.get("counts") or {}).get("rejectedPlateAppearances") or 0
        ),
        "rejectReasons": dict(silver.get("rejectReasonCounts") or {}),
        "goldRows": int(gold.get("rowCount") or 0),
        "goldFeatureCount": int(gold.get("featureCount") or 0),
        "silverManifestSha256": silver_sha,
        "goldManifestSha256": gold_sha,
        "contextualGoldManifestSha256": contextual_sha or None,
        "registrationId": registration.get("registration_id") if registration else None,
    }


def _published_source_shas(config: CurrentStatcastSyncConfig) -> dict[str, str]:
    _sha, silver = _current_manifest(config.current_silver_root)
    return {
        str(receipt.get("partitionDate")): str((receipt.get("request") or {}).get("sourcePartitionSha256") or "")
        for receipt in (silver.get("partitions") or [])
    }


def _bronze_source_shas(config: CurrentStatcastSyncConfig) -> dict[str, str]:
    manifest = BronzeManifest(Path(config.current_bronze_root))
    result: dict[str, str] = {}
    for item in manifest.partitions:
        if item.get("source") != "statcast" or item.get("scope") != "regular":
            continue
        day = str((item.get("query") or {}).get("date") or "")
        source_sha = str(item.get("fileSha256") or "")
        if day and source_sha:
            result[day] = source_sha
    return result


def _persisted_completed_games_by_date(root: Path) -> dict[str, set[int]]:
    path = Path(root) / "manifests" / "mlb-stats-api-schedule-authority.json"
    manifest = _json(path)
    result: dict[str, set[int]] = {}
    for raw in manifest.get("completedGames") or []:
        if not isinstance(raw, Mapping):
            raise CurrentStatcastSyncRuntimeError(
                "persisted schedule authority contains a non-object completed game"
            )
        day = str(raw.get("gameDate") or "")
        try:
            game_pk = int(raw["gamePk"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CurrentStatcastSyncRuntimeError(
                "persisted schedule authority contains an invalid completed game identity"
            ) from exc
        result.setdefault(day, set()).add(game_pk)
    return result


def _schedule_membership_mismatches(
    probe_by_date: Mapping[str, list[int]],
    persisted_by_date: Mapping[str, set[int]],
    *,
    dates: list[str],
) -> dict[str, dict[str, list[int]]]:
    mismatches: dict[str, dict[str, list[int]]] = {}
    for day in sorted(set(dates)):
        probe = {int(value) for value in (probe_by_date.get(day) or [])}
        persisted = {int(value) for value in (persisted_by_date.get(day) or set())}
        if probe != persisted:
            mismatches[day] = {
                "missingFromProbe": sorted(persisted - probe),
                "unexpectedInProbe": sorted(probe - persisted),
            }
    return mismatches


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        with temporary.open("wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _recover_pending_commit(config: CurrentStatcastSyncConfig) -> None:
    """Finish a verified pointer swap interrupted after registry commit."""

    journal = Path(config.report_root) / "commit-journal.json"
    if not journal.is_file():
        return
    payload = _json(journal)
    registration_id = str(payload.get("registration") or "")
    database = Database(config.database_path)
    database.initialize()
    with database.connection() as connection:
        registered = connection.execute(
            "SELECT 1 FROM sports_dataset_registrations WHERE registration_id = ?",
            (registration_id,),
        ).fetchone()
    if registered is None:
        # No mutable authority advanced.  Immutable candidates may be reused by
        # the ordinary retry, whose Bronze-vs-Silver comparison forces it past
        # the no-op path.
        journal.unlink(missing_ok=True)
        return
    silver_new = str((payload.get("silver") or [None, None])[1] or "")
    gold_new = str((payload.get("gold") or [None, None])[1] or "")
    contextual_pair = payload.get("contextualGold")
    contextual_new = ""
    silver_verified = verify_current_silver(config.current_silver_root, silver_new)
    gold_verified = verify_current_gold(config.current_gold_root, gold_new)
    if contextual_pair is not None:
        if not isinstance(contextual_pair, list) or len(contextual_pair) != 2:
            raise CurrentStatcastSyncRuntimeError(
                "pending contextual Gold journal identity is invalid"
            )
        contextual_new = str(contextual_pair[1] or "")
        contextual_verified = verify_contextual_gold(
            config.contextual_gold_root,
            contextual_new,
            current_gold_root=config.current_gold_root,
        )
        if contextual_verified.get("sourceGoldManifestSha256") != gold_new:
            raise CurrentStatcastSyncRuntimeError(
                "pending contextual Gold publication is not bound to pending Gold"
            )
    _atomic_locator(
        config.current_silver_root,
        CURRENT_STATCAST_DATASET_ID,
        silver_new,
        Path(str(silver_verified["manifestPath"])),
    )
    gold_path = Path(config.current_gold_root) / "publications" / "sha256" / gold_new / "manifest.json"
    _atomic_locator(
        config.current_gold_root,
        "gold-table:gold_mlb_current_pa_v1",
        gold_new,
        gold_path,
    )
    if contextual_new:
        contextual_path = (
            Path(config.contextual_gold_root)
            / "publications"
            / "sha256"
            / contextual_new
            / "manifest.json"
        )
        _atomic_locator(
            config.contextual_gold_root,
            CONTEXT_GOLD_DATASET_ID,
            contextual_new,
            contextual_path,
        )
    journal.unlink(missing_ok=True)


def _date_range(start: date, end: date) -> list[str]:
    result: list[str] = []
    cursor = start
    while cursor <= end:
        result.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return result


def _probe_schedule(config: CurrentStatcastSyncConfig) -> dict[str, Any]:
    _recover_pending_commit(config)
    current = _coverage_snapshot(config)
    prior_text = str(current.get("latestDate") or "")
    prior = date.fromisoformat(prior_text)
    today = datetime.now(ZoneInfo("America/New_York")).date()
    last_allowed = today - timedelta(days=1)
    requested_raw = str(config.through)
    if requested_raw == LATEST_COMPLETED:
        requested = last_allowed
    else:
        assert_nightly_current_statcast_date_allowed(requested_raw)
        requested = date.fromisoformat(requested_raw)
        if requested >= today:
            raise CurrentStatcastSyncRuntimeError(
                f"same-day or future evidence is prohibited: {requested.isoformat()}"
            )
        if requested < prior:
            raise CurrentStatcastSyncRuntimeError(
                "explicit through date cannot precede current registered coverage: "
                f"requested={requested.isoformat()} current={prior.isoformat()}"
            )
    probe_end = min(requested, last_allowed)
    published_source_shas = _published_source_shas(config)
    bronze_source_shas = _bronze_source_shas(config)
    pending_bronze_dates = sorted(
        day
        for day in set(published_source_shas).union(bronze_source_shas)
        if "2026-03-01" <= day <= probe_end.isoformat()
        and published_source_shas.get(day) != bronze_source_shas.get(day)
    )
    probe_start = min(prior + timedelta(days=1), probe_end)
    probe_start = min(probe_start, prior - timedelta(days=max(14, config.correction_lookback * 4)))
    if pending_bronze_dates:
        probe_start = min(probe_start, date.fromisoformat(pending_bronze_dates[0]))
    probe_start = max(probe_start, date(2026, 3, 1))

    candidate_root = Path(config.current_bronze_root) / ".nightly-probes"
    candidate = candidate_root / f"schedule-{uuid.uuid4().hex}.json"
    try:
        http_download(nightly_schedule_url(probe_start.isoformat(), probe_end.isoformat()), candidate)
        parsed = parse_schedule_payload(
            candidate.read_bytes(),
            start_date=probe_start.isoformat(),
            end_date=probe_end.isoformat(),
            nightly=True,
        )
    finally:
        candidate.unlink(missing_ok=True)

    all_records = list(parsed["completedGames"]) + list(parsed["excludedGames"])
    records_by_date: dict[str, list[dict[str, Any]]] = {}
    for record in all_records:
        records_by_date.setdefault(str(record["gameDate"]), []).append(record)
    fully_completed = [
        day
        for day in _date_range(probe_start, probe_end)
        if not records_by_date.get(day)
        or all(
            str(item["detailedState"]) in COMPLETED_DETAILED_STATES
            for item in records_by_date[day]
        )
    ]
    completed_game_dates = sorted(
        {str(item["gameDate"]) for item in parsed["completedGames"]}
    )
    latest_final = completed_game_dates[-1] if completed_game_dates else None
    if requested_raw == LATEST_COMPLETED:
        resolved = max(prior, date.fromisoformat(latest_final) if latest_final else prior)
    else:
        resolved = requested
        if resolved > prior and resolved.isoformat() not in fully_completed:
            raise CurrentStatcastSyncRuntimeError(
                f"requested through date is not fully completed in MLB authority: {resolved.isoformat()}"
            )

    completed_by_date: dict[str, list[int]] = {}
    for day in _date_range(probe_start, resolved):
        completed_by_date[day] = sorted(
            int(item["gamePk"])
            for item in parsed["completedGames"]
            if str(item["gameDate"]) == day
        )
    already_covered_dates = [
        day for day in completed_by_date if day <= prior.isoformat()
    ]
    schedule_mismatches = _schedule_membership_mismatches(
        completed_by_date,
        _persisted_completed_games_by_date(config.current_bronze_root),
        dates=already_covered_dates,
    )
    if schedule_mismatches:
        first_day = sorted(schedule_mismatches)[0]
        mismatch = schedule_mismatches[first_day]
        raise CurrentStatcastSyncRuntimeError(
            "completed-game membership differs from persisted schedule authority for "
            f"{first_day}: missingFromProbe={mismatch['missingFromProbe']} "
            f"unexpectedInProbe={mismatch['unexpectedInProbe']}"
        )
    registration = _current_registration(config)
    return {
        "requestedThroughDate": resolved.isoformat(),
        "priorRegisteredThroughDate": prior.isoformat(),
        "latestMlbFinalDate": latest_final,
        "completedGamesByDate": completed_by_date,
        "correctionEligibleDates": [day for day in fully_completed if day <= resolved.isoformat()],
        "currentSilverPublicationIdentity": current["silverManifestSha256"],
        "currentGoldPublicationIdentity": current["goldManifestSha256"],
        "currentContextualGoldPublicationIdentity": current.get(
            "contextualGoldManifestSha256"
        ),
        "currentWarehouseRegistrationIdentity": (
            registration.get("registration_id") if registration else None
        ),
        "currentCoverage": current,
        "publishedSourceShaByDate": published_source_shas,
        "pendingBronzeDates": pending_bronze_dates,
    }


def _candidate_record(part: Any, candidate: Path, receipt: Mapping[str, Any]) -> tuple[dict[str, Any], set[int]]:
    inspection = inspect_csv(candidate, natural_keys=part.natural_keys, date_col=part.date_col)
    row_count = int(inspection.get("rowCount") or 0)
    status = "COMPLETE_EMPTY" if row_count == 0 else "COMPLETE"
    if row_count >= STATCAST_ROW_CAP:
        raise CurrentStatcastSyncRuntimeError(
            f"Statcast partition hit the truncation cap: {part.partition_id} rows={row_count}"
        )
    if row_count and (
        inspection.get("minDate") != part.query["date"]
        or inspection.get("maxDate") != part.query["date"]
    ):
        raise CurrentStatcastSyncRuntimeError(
            f"Statcast partition returned a different date: {part.partition_id}"
        )
    game_pks: set[int] = set()
    if row_count:
        table = pacsv.read_csv(candidate)
        if "game_pk" not in table.column_names:
            raise CurrentStatcastSyncRuntimeError(f"Statcast partition lacks game_pk: {part.partition_id}")
        for raw in table["game_pk"].to_pylist():
            try:
                game_pks.add(int(float(raw)))
            except (TypeError, ValueError):
                continue
    record = {
        "partitionId": part.partition_id,
        "source": "statcast",
        "scope": part.scope,
        "sourceUrlDomain": part.url.split("/")[2],
        "year": part.year,
        "query": part.query,
        "retrievalUtc": utc_now(),
        "toolVersion": "1.2-nightly",
        "httpStatus": int(receipt.get("status") or 200),
        "attempts": int(receipt.get("attempts") or 0),
        "reused": bool(receipt.get("reused")),
        "rawFilename": part.filename,
        "fileSizeBytes": candidate.stat().st_size,
        "fileSha256": sha256_file(candidate),
        "license": SOURCE_TERMS["statcast"]["classification"],
        "status": status,
        **inspection,
    }
    return record, game_pks


def _existing_records(root: Path) -> tuple[BronzeManifest, dict[str, dict[str, Any]]]:
    manifest = BronzeManifest(root)
    return manifest, {str(item.get("partitionId")): dict(item) for item in manifest.partitions}


def _schedule_latest_end(root: Path) -> date | None:
    path = Path(root) / "manifests" / "mlb-stats-api-schedule-authority.json"
    if not path.is_file():
        return None
    snapshots = list((_json(path).get("snapshots") or []))
    ends = [date.fromisoformat(str(item["endDate"])) for item in snapshots]
    return max(ends) if ends else None


def _sync_bronze(
    config: CurrentStatcastSyncConfig,
    probe: dict[str, Any],
    inspect_dates: list[str],
) -> dict[str, Any]:
    root = Path(config.current_bronze_root).resolve()
    manifest, existing = _existing_records(root)
    candidate_root = root / ".nightly-candidates" / uuid.uuid4().hex
    candidate_root.mkdir(parents=True, exist_ok=False)
    prepared: list[tuple[Any, Path, dict[str, Any], set[int], dict[str, Any] | None]] = []
    failures: list[str] = []
    represented = 0
    expected_total = 0
    try:
        for day in inspect_dates:
            part = nightly_current_statcast_partitions(day, day)[0]
            candidate = candidate_root / part.filename
            try:
                receipt = http_download(part.url, candidate)
                record, game_pks = _candidate_record(part, candidate, receipt)
                expected = set(int(value) for value in probe["completedGamesByDate"].get(day, []))
                expected_total += len(expected)
                represented += len(game_pks.intersection(expected))
                if game_pks != expected:
                    raise CurrentStatcastSyncRuntimeError(
                        f"Statcast/schedule game reconciliation failed for {day}: "
                        f"missing={sorted(expected - game_pks)} unexpected={sorted(game_pks - expected)}"
                    )
                prepared.append((part, candidate, record, game_pks, existing.get(part.partition_id)))
            except Exception:
                failures.append(day)

        current_ids = {
            "currentSilverPublicationIdentity": probe.get("currentSilverPublicationIdentity"),
            "currentGoldPublicationIdentity": probe.get("currentGoldPublicationIdentity"),
            "currentContextualGoldPublicationIdentity": probe.get(
                "currentContextualGoldPublicationIdentity"
            ),
            "currentWarehouseRegistrationIdentity": probe.get("currentWarehouseRegistrationIdentity"),
            "currentCoverage": dict(probe.get("currentCoverage") or {}),
        }
        if failures:
            return {
                "status": "FAILED",
                "datesAdded": [],
                "datesCorrected": [],
                "datesUnchanged": [],
                "failedDates": sorted(failures),
                "completeEmptyDates": [],
                "expectedFinalGames": expected_total,
                "representedGames": represented,
                "missingGames": max(expected_total - represented, 1),
                "sourcePitches": 0,
                "acceptedPitches": 0,
                "acceptedPlateAppearances": 0,
                "rejectedPlateAppearances": 0,
                "rejectReasons": {},
                "duplicateCount": 0,
                "unresolvedCount": 0,
                **current_ids,
            }

        added: list[str] = []
        corrected: list[str] = []
        unchanged: list[str] = []
        changed_records: list[dict[str, Any]] = []
        for part, candidate, record, _game_pks, prior in prepared:
            day = str(part.query["date"])
            if prior is not None and manifest.has_valid(part.partition_id) and prior.get("fileSha256") == record["fileSha256"]:
                published_sha = str((probe.get("publishedSourceShaByDate") or {}).get(day) or "")
                if day > str(probe.get("priorRegisteredThroughDate") or ""):
                    added.append(day)
                elif published_sha and published_sha != str(record["fileSha256"]):
                    corrected.append(day)
                else:
                    unchanged.append(day)
                continue
            object_path = contained_path(
                root,
                "objects",
                "statcast",
                "sha256",
                f"{record['fileSha256']}.csv",
            )
            object_path.parent.mkdir(parents=True, exist_ok=True)
            if object_path.exists():
                if sha256_file(object_path) != record["fileSha256"]:
                    raise CurrentStatcastSyncRuntimeError("Bronze content-address conflict")
            else:
                os.replace(candidate, object_path)
            record["relativePath"] = object_path.relative_to(root).as_posix()
            if prior is None:
                added.append(day)
            else:
                corrected.append(day)
                history = list(prior.get("historicalVersions") or [])
                history.append(
                    {
                        "fileSha256": prior.get("fileSha256"),
                        "relativePath": prior.get("relativePath"),
                        "retrievalUtc": prior.get("retrievalUtc"),
                        "rowCount": prior.get("rowCount"),
                        "status": prior.get("status"),
                    }
                )
                record["historicalVersions"] = history
            changed_records.append(record)

        # A prior interrupted attempt or a separately acquired governed Bronze
        # partition can already contain the exact bytes that Silver has not yet
        # published.  In that case ``changed_records`` is empty but the logical
        # delta is still an addition/correction, and the non-overlapping schedule
        # authority must advance before downstream normalization can resume.
        if added or corrected:
            requested = date.fromisoformat(str(probe["requestedThroughDate"]))
            schedule_end = _schedule_latest_end(root)
            if schedule_end is None or requested > schedule_end:
                schedule_start = (schedule_end + timedelta(days=1)) if schedule_end else requested
                acquire_schedule_authority(
                    root,
                    start_date=schedule_start.isoformat(),
                    end_date=requested.isoformat(),
                    nightly=True,
                )
        if changed_records:
            for record in changed_records:
                manifest.upsert(record)
            manifest_sha = manifest.write()
        else:
            manifest_path = root / "manifests" / "bronze-manifest.json"
            manifest_sha = sha256_file(manifest_path)

        selected = [
            dict(item)
            for item in manifest.partitions
            if item.get("source") == "statcast"
            and item.get("scope") == "regular"
            and str((item.get("query") or {}).get("date") or "")
            <= str(probe["requestedThroughDate"])
        ]
        return {
            "status": "COMPLETE",
            "datesAdded": sorted(added),
            "datesCorrected": sorted(corrected),
            "datesUnchanged": sorted(unchanged),
            "failedDates": [],
            "completeEmptyDates": sorted(
                str((item.get("query") or {}).get("date"))
                for item in selected
                if item.get("status") == "COMPLETE_EMPTY"
            ),
            "expectedFinalGames": expected_total,
            "representedGames": represented,
            "missingGames": 0,
            "sourcePitches": sum(int(item.get("rowCount") or 0) for item in selected),
            "acceptedPitches": int((probe.get("currentCoverage") or {}).get("acceptedPitchRows") or 0),
            "acceptedPlateAppearances": int(
                (probe.get("currentCoverage") or {}).get("acceptedPlateAppearances") or 0
            ),
            "rejectedPlateAppearances": int(
                (probe.get("currentCoverage") or {}).get("rejectedPlateAppearances") or 0
            ),
            "rejectReasons": dict((probe.get("currentCoverage") or {}).get("rejectReasons") or {}),
            "duplicateCount": sum(int(item.get("naturalKeyDuplicateCount") or 0) for item in selected),
            "unresolvedCount": 0,
            "revisedPartitionCount": sum(
                bool(item.get("historicalVersions")) for item in selected
            ),
            "bronzeManifestSha256": manifest_sha,
            **current_ids,
        }
    finally:
        shutil.rmtree(candidate_root, ignore_errors=True)


def _sync_silver(
    config: CurrentStatcastSyncConfig,
    bronze_delta: dict[str, Any],
    probe: dict[str, Any],
) -> dict[str, Any]:
    prior = str(_locator(config.current_silver_root).get("manifestSha256") or "")
    built = build_current_silver(
        legacy_bronze_root=config.legacy_bronze_root,
        current_bronze_root=config.current_bronze_root,
        existing_silver_root=config.existing_silver_root,
        output_root=config.current_silver_root,
        through_date=str(probe["requestedThroughDate"]),
        publish_current=False,
        prior_manifest_sha256=prior,
    )
    verified = verify_current_silver(config.current_silver_root, str(built["manifestSha256"]))
    return {
        "status": "COMPLETE",
        "publicationIdentity": str(built["manifestSha256"]),
        "priorPublicationIdentity": prior,
        "publicationPath": str(built["manifestPath"]),
        "normalizedDates": list(built.get("normalizedDates") or []),
        "reusedDates": list(built.get("reusedDates") or []),
        "manifest": built,
        "verification": verified,
        "bronze": bronze_delta,
    }


def _sync_gold(
    config: CurrentStatcastSyncConfig,
    silver_delta: dict[str, Any],
    affected_target_dates: list[str],
) -> dict[str, Any]:
    prior = str(_locator(config.current_gold_root).get("manifestSha256") or "")
    through = str((silver_delta.get("manifest") or {}).get("dateCoverage", {}).get("latestDate") or "")
    built = build_current_gold(
        current_silver_root=config.current_silver_root,
        existing_silver_root=config.existing_silver_root,
        existing_gold_root=config.existing_gold_root,
        exchange_root=config.exchange_root,
        output_root=config.current_gold_root,
        current_silver_manifest_sha256=str(silver_delta["publicationIdentity"]),
        evidence_end=through,
        recompute_dates=affected_target_dates,
        prior_manifest_sha256=prior,
        publish_current=False,
    )
    verified = verify_current_gold(config.current_gold_root, str(built["manifestSha256"]))
    contextual_prior_locator = _optional_locator(config.contextual_gold_root)
    contextual_prior = str(
        contextual_prior_locator.get("manifestSha256")
        or contextual_prior_locator.get("currentManifestSha256")
        or ""
    )
    contextual_built = build_contextual_gold(
        current_gold_root=config.current_gold_root,
        output_root=config.contextual_gold_root,
        current_gold_manifest_sha256=str(built["manifestSha256"]),
        recompute_dates=affected_target_dates,
        prior_manifest_sha256=contextual_prior or None,
        publish_current=False,
    )
    contextual_verification = {
        "datasetId": CONTEXT_GOLD_DATASET_ID,
        "manifestSha256": str(contextual_built["manifestSha256"]),
        "sourceGoldManifestSha256": str(
            (contextual_built.get("sourceGold") or {}).get("manifestSha256") or ""
        ),
        "rowCount": int(contextual_built["rowCount"]),
        "modelsFitted": int(contextual_built["modelsFitted"]),
        "modelsScored": int(contextual_built["modelsScored"]),
        "modelsCalibrated": int(contextual_built["modelsCalibrated"]),
        "modelPromoted": contextual_built["modelPromoted"],
        "verified": True,
    }
    if (
        contextual_verification["sourceGoldManifestSha256"]
        != str(built["manifestSha256"])
        or contextual_verification["modelsFitted"] != 0
        or contextual_verification["modelsScored"] != 0
        or contextual_verification["modelsCalibrated"] != 0
        or contextual_verification["modelPromoted"] is not False
    ):
        raise CurrentStatcastSyncRuntimeError(
            "contextual Gold candidate is not model-free and bound to current Gold"
        )
    return {
        "status": "COMPLETE",
        "publicationIdentity": str(built["manifestSha256"]),
        "priorPublicationIdentity": prior,
        "publicationPath": str(built["manifestPath"]),
        "recomputedDates": affected_target_dates,
        "featureCount": int(built["featureCount"]),
        "rowCount": int(built["rowCount"]),
        "modelsFitted": int(built["modelsFitted"]),
        "manifest": built,
        "verification": verified,
        "contextualPublication": {
            "status": "COMPLETE",
            "datasetId": CONTEXT_GOLD_DATASET_ID,
            "publicationIdentity": str(contextual_built["manifestSha256"]),
            "priorPublicationIdentity": contextual_prior or None,
            "publicationPath": str(contextual_built["manifestPath"]),
            "recomputedDates": list(
                contextual_built.get("recomputedTargetDates") or affected_target_dates
            ),
            "featureCount": int(contextual_built["totalFeatureCount"]),
            "rowCount": int(contextual_built["rowCount"]),
            "modelsFitted": int(contextual_built["modelsFitted"]),
            "modelsScored": int(contextual_built["modelsScored"]),
            "modelsCalibrated": int(contextual_built["modelsCalibrated"]),
            "modelPromoted": contextual_built["modelPromoted"],
            "manifest": contextual_built,
            "verification": contextual_verification,
        },
    }


def _historical_pa_descriptors(config: CurrentStatcastSyncConfig) -> list[dict[str, Any]]:
    from scripts.build_current_statcast_extension import _historical_pa_descriptors as resolve

    return resolve(package_root=config.package_root, existing_silver_root=config.existing_silver_root)


def _atomic_locator(root: Path, dataset_id: str, new_sha: str, manifest_path: Path) -> None:
    root = Path(root).resolve()
    old = _optional_locator(root)
    old_sha = str(old.get("manifestSha256") or old.get("currentManifestSha256") or "")
    history = list(old.get("historicalManifestSha256s") or [])
    if old_sha and old_sha != new_sha and old_sha not in history:
        history.append(old_sha)
    payload = {
        "datasetId": dataset_id,
        "manifestSha256": new_sha,
        "currentManifestSha256": new_sha,
        "historicalManifestSha256s": history,
        "manifestRelativePath": Path(manifest_path).resolve().relative_to(root).as_posix(),
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    target = root / "current.json"
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(body)
    os.replace(temporary, target)


def _sync_warehouse(
    config: CurrentStatcastSyncConfig,
    silver_delta: dict[str, Any],
    gold_delta: dict[str, Any],
    status: dict[str, Any],
) -> dict[str, Any]:
    silver_manifest = dict(silver_delta["manifest"])
    contextual = gold_delta.get("contextualPublication")
    if contextual is not None:
        contextual_verification = (
            contextual.get("verification") if isinstance(contextual, Mapping) else None
        )
        if (
            not isinstance(contextual, Mapping)
            or contextual.get("status") != "COMPLETE"
            or int(contextual.get("modelsFitted") or 0) != 0
            or int(contextual.get("modelsScored") or 0) != 0
            or int(contextual.get("modelsCalibrated") or 0) != 0
            or contextual.get("modelPromoted") is not False
            or not isinstance(contextual_verification, Mapping)
            or str(contextual_verification.get("sourceGoldManifestSha256") or "")
            != str(gold_delta["publicationIdentity"])
        ):
            raise CurrentStatcastSyncRuntimeError(
                "contextual Gold candidate failed the warehouse transaction boundary"
            )
    sync_health = {
        "status": "COMPLETE",
        "latestFullyCompletedDate": (silver_manifest.get("dateCoverage") or {}).get("latestDate"),
        "sourcePitchRows": int((silver_manifest.get("counts") or {}).get("sourcePitchRows") or 0),
        "acceptedPitchRows": int((silver_manifest.get("counts") or {}).get("acceptedPitchRows") or 0),
        "acceptedPlateAppearances": int(
            (silver_manifest.get("counts") or {}).get("acceptedPlateAppearances") or 0
        ),
        "rejectedPlateAppearances": int(
            (silver_manifest.get("counts") or {}).get("rejectedPlateAppearances") or 0
        ),
        "rejectReasons": dict(silver_manifest.get("rejectReasonCounts") or {}),
        "silverPartitionCount": len(silver_manifest.get("partitions") or []),
        "completeEmptyPartitionCount": sum(
            str(item.get("sourceStatus")) == "COMPLETE_EMPTY"
            for item in (silver_manifest.get("partitions") or [])
        ),
        "revisedPartitionCount": int(
            (silver_delta.get("bronze") or {}).get("revisedPartitionCount") or 0
        ),
        "goldRows": int(gold_delta["rowCount"]),
        "goldFeatureCount": int(gold_delta["featureCount"]),
        "datesAdded": list(status.get("datesAdded") or []),
        "datesCorrected": list(status.get("datesCorrected") or []),
        "modelFits": 0,
    }
    validated = build_current_statcast_warehouse_manifest(
        config.package_root,
        Path(str(silver_delta["publicationPath"])),
        extra_partitions=_historical_pa_descriptors(config),
        include_current_receipts=True,
        current_silver_root=config.current_silver_root,
        limitations=(
            {
                "description": "This registration exposes exact PA evidence and authorized temporal coverage; no model was fitted, scored, selected, or promoted.",
                "limitationId": "CURRENT_STATCAST_PA_EVIDENCE_NO_FIT",
                "scope": "MODELING",
            },
            {
                "description": "Statcast source rights permit bounded local research; commercial use and raw redistribution require separate review.",
                "limitationId": "CURRENT_STATCAST_RIGHTS_REVIEW_REQUIRED",
                "scope": "RIGHTS",
            },
        ),
        sync_health=sync_health,
        gold_publication={
            "datasetId": "gold-table:gold_mlb_current_pa_v1",
            "manifestSha256": gold_delta["publicationIdentity"],
            "rowCount": gold_delta["rowCount"],
            "featureCount": gold_delta["featureCount"],
        },
    )
    journal = Path(config.report_root) / "commit-journal.json"
    journal.parent.mkdir(parents=True, exist_ok=True)
    expected_registration_id = CurrentStatcastDatasetRegistry._registration_id(
        str(validated.manifest["manifestSha256"])
    )
    journal_payload: dict[str, Any] = {
        "silver": [silver_delta["priorPublicationIdentity"], silver_delta["publicationIdentity"]],
        "gold": [gold_delta["priorPublicationIdentity"], gold_delta["publicationIdentity"]],
        "registration": expected_registration_id,
    }
    if isinstance(contextual, Mapping):
        journal_payload["contextualGold"] = [
            contextual.get("priorPublicationIdentity"),
            contextual["publicationIdentity"],
        ]
    _write_json_atomic(journal, journal_payload)
    database = Database(config.database_path)
    database.initialize()
    registration = CurrentStatcastDatasetRegistry(database).register(
        validated, user_id=config.registered_by
    )
    _atomic_locator(
        config.current_silver_root,
        CURRENT_STATCAST_DATASET_ID,
        str(silver_delta["publicationIdentity"]),
        Path(str(silver_delta["publicationPath"])),
    )
    _atomic_locator(
        config.current_gold_root,
        "gold-table:gold_mlb_current_pa_v1",
        str(gold_delta["publicationIdentity"]),
        Path(str(gold_delta["publicationPath"])),
    )
    if isinstance(contextual, Mapping):
        _atomic_locator(
            config.contextual_gold_root,
            CONTEXT_GOLD_DATASET_ID,
            str(contextual["publicationIdentity"]),
            Path(str(contextual["publicationPath"])),
        )
    journal.unlink(missing_ok=True)
    metadata = registration.get("metadata_json") or {}
    return {
        "status": "COMPLETE",
        "registrationIdentity": registration["registration_id"],
        "priorRegistrationIdentity": metadata.get("supersedesRegistrationId"),
        "historicalRegistrationIdentities": list(metadata.get("historicalRegistrationIds") or []),
        "coverage": {
            "earliestDate": (silver_manifest.get("dateCoverage") or {}).get("earliestDate"),
            "latestDate": (silver_manifest.get("dateCoverage") or {}).get("latestDate"),
            "partitionCount": len(silver_manifest.get("partitions") or []),
            "completeEmptyPartitionCount": sync_health["completeEmptyPartitionCount"],
            "sourcePitchRows": sync_health["sourcePitchRows"],
            "acceptedPitchRows": sync_health["acceptedPitchRows"],
            "acceptedPlateAppearances": sync_health["acceptedPlateAppearances"],
            "rejectedPlateAppearances": sync_health["rejectedPlateAppearances"],
            "rejectReasons": sync_health["rejectReasons"],
            "goldRows": sync_health["goldRows"],
            "goldFeatureCount": sync_health["goldFeatureCount"],
        },
    }


def concrete_dependencies() -> CurrentStatcastSyncDependencies:
    return CurrentStatcastSyncDependencies(
        discover_completed=_probe_schedule,
        sync_bronze=_sync_bronze,
        sync_silver=_sync_silver,
        sync_gold=_sync_gold,
        sync_warehouse=_sync_warehouse,
        clock=lambda: datetime.now(timezone.utc),
    )


__all__ = ["CurrentStatcastSyncRuntimeError", "concrete_dependencies"]
