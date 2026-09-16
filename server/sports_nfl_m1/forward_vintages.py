"""Forward-only local NFL source archival; never synchronizes or fits a model.

Only registered, physically season-scoped 2026 source objects are opened. A
mixed-season schedule is not read: an optional existing 2026 forecast handoff
provides a separately labeled, partial schedule-only projection instead.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pyarrow.parquet as pq

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_cockpit.interprocess_lock import interprocess_lock
from server.sports_nfl_m1.labs_simulation import file_record, immutable_json

REPO = Path(__file__).resolve().parents[2]
OUTPUTS_ROOT = REPO / "outputs"
DEFAULT_OUTPUT = OUTPUTS_ROOT / "nfl-forward-vintages-v1"
DEFAULT_BRONZE = Path(r"C:\Users\james\asp-data-staging\nfl\bronze-v1")
DEFAULT_SCHEDULE_HANDOFF = OUTPUTS_ROOT / "nfl-week1-incremental-publication-v1/sha256/fb8b91b3cfcb473a5564db5ac3c3438a54b60f16223c3f6fe7399e3d0dda2653/handoff.json"
FAMILIES = ("schedules", "rosters", "weekly_rosters", "depth_charts", "injuries", "practice_reports",
            "participation", "play_by_play", "weekly_player_stats", "weekly_team_stats",
            "ngs_passing", "ngs_rushing", "ngs_receiving", "weather_forecasts")
AUTHORITY = {"evidenceClass": "OBSERVED_AS_OF", "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
             "wageringAuthority": False, "executionAllowedInAISP": False}


class ForwardVintageError(ValueError):
    pass


def _time(value: str | datetime) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ForwardVintageError("a timezone-aware timestamp is required")
    return result.astimezone(timezone.utc)


def _text(value: str | datetime) -> str:
    return _time(value).isoformat().replace("+00:00", "Z")


def _verified_json(path: Path, sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    ref = file_record(path)
    if sha and ref["sha256"] != sha:
        raise ForwardVintageError(f"metadata checksum differs: {path}")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ForwardVintageError("expected a metadata object")
    return value, ref


def _put(root: Path, filename: str, body: dict[str, Any]) -> dict[str, Any]:
    sha = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return immutable_json(root / "sha256" / sha / filename, body)


def _pointer(path: Path, body: dict[str, Any]) -> None:
    raw = canonical_json_bytes(body)
    if path.exists() and path.read_bytes() == raw:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def schedule_events_from_handoff(path: Path = DEFAULT_SCHEDULE_HANDOFF) -> dict[str, Any]:
    """Read only existing 2026 handoffs, never the mixed source or model binary.

    Returned rows contain no score, probability, outcome, lineup or market data.
    Caller must still enforce its live pre-kickoff cutoff before forecasting.
    """
    path = Path(path).resolve()
    aggregate, aggregate_ref = _verified_json(path, path.parent.name)
    if aggregate.get("season") != 2026 or aggregate.get("executionAllowedInAISP") is not False:
        raise ForwardVintageError("only the existing 2026 research handoff is supported")
    slates = aggregate.get("slateHandoffs") or []
    if not slates:
        raise ForwardVintageError("aggregate must reference its immutable 2026 slate handoffs")
    rows: dict[str, dict[str, Any]] = {}
    parents = [aggregate_ref]
    root = path.parents[2]
    for item in slates:
        child = Path(item["handoffPath"]).resolve()
        if not child.is_relative_to(root):
            raise ForwardVintageError("slate handoff escapes the aggregate publication root")
        body, ref = _verified_json(child, item["handoffSha256"])
        if body.get("season") != 2026 or body.get("executionAllowedInAISP") is not False:
            raise ForwardVintageError("slate is not 2026 research evidence")
        parents.append(ref)
        for forecast in body.get("forecasts", []):
            event = str(forecast["eventId"])
            pieces = event.split("_")
            if len(pieces) != 4 or pieces[0] != "2026":
                raise ForwardVintageError("non-2026 or ambiguous canonical event identity")
            home, away = str(forecast["homeTeamId"]), str(forecast["awayTeamId"])
            # Preserve canonical handoff IDs; nflverse uses LA in source event IDs.
            source_teams = ["LAR" if team == "LA" else team for team in pieces[2:]]
            if home == away or source_teams != [away, home]:
                raise ForwardVintageError("canonical event and home/away identities disagree")
            if forecast["sourceEventId"] != f"nflverse:{event}":
                raise ForwardVintageError("source and canonical event identities disagree")
            row = {"eventId": event, "sourceEventId": forecast["sourceEventId"], "season": 2026,
                   "week": int(pieces[1]), "homeTeamId": home, "awayTeamId": away,
                   "kickoffUtc": _text(forecast["kickoffUtc"]),
                   "evidenceClass": "OBSERVED_AS_OF",
                   "derivation": "DERIVED_FROM_PRECOMPUTED_FORECAST_SCHEDULE_PROJECTION",
                   "sourceForecastId": forecast["forecastId"], "sourceHandoffSha256": ref["sha256"],
                   "sourceForecastCreatedUtc": forecast["forecastCreatedUtc"],
                   "sourceForecastEvidenceCutoffUtc": forecast["evidenceCutoffUtc"]}
            if event in rows and rows[event] != row:
                raise ForwardVintageError("conflicting schedule versions require explicit reconciliation")
            rows[event] = row
    if len(rows) != int(aggregate["eventCount"]):
        raise ForwardVintageError("schedule projection event count differs from aggregate")
    schedule_sources = [{key: value.get(key) for key in ("familyId", "fileSha256", "byteCount", "sourceUrl", "license",
                                                        "retrievedAtUtc", "assetUpdatedAt", "releasePublishedAt")}
                        for value in aggregate.get("source", {}).get("assets", []) if value.get("familyId") == "schedules"]
    return {"schemaVersion": "NFL_2026_DERIVED_SCHEDULE_PROJECTION_V1", **AUTHORITY,
            "derivation": "DERIVED_FROM_PRECOMPUTED_FORECAST_SCHEDULE_PROJECTION", "season": 2026,
            "eventCount": len(rows), "fullSeasonCoverage": False, "sourceHandoffs": parents,
            "sourceScheduleMetadataOnly": schedule_sources,
            "events": sorted(rows.values(), key=lambda row: (row["kickoffUtc"], row["eventId"])),
            "limitations": ["Partial published-event schedule, not a refreshed authoritative league schedule.",
                            "Source schedule metadata is preserved without opening its mixed-season payload.",
                            "Original forecast dates are lineage, not a backdated observation time for this new projection."]}


def _scope_reason(partition: dict[str, Any]) -> str | None:
    if partition.get("season") != 2026 or "season=2026" not in Path(partition.get("relativePath", "")).parts:
        return "MIXED_OR_OTHER_SEASON_SOURCE_NOT_OPENED_REQUIRES_PHYSICAL_2026_PARTITION"
    if set(partition.get("coverage", {}).get("seasons", [])) - {2026}:
        return "REGISTERED_COVERAGE_INCLUDES_OTHER_SEASONS_SOURCE_NOT_OPENED"
    if partition.get("status") != "COMPLETE":
        return "SOURCE_REGISTRATION_NOT_COMPLETE"
    if not partition.get("license") or not partition.get("sourceContractVersion"):
        return "SOURCE_USE_OR_CONTRACT_AUTHORITY_UNAVAILABLE"
    return None


def _partition_payload(bronze: Path, partition: dict[str, Any], observed: datetime) -> tuple[bytes, dict[str, Any]]:
    reason = _scope_reason(partition)
    if reason:
        raise ForwardVintageError(reason)
    path = (bronze / partition["relativePath"]).resolve()
    if not path.is_relative_to(bronze.resolve()) or path.suffix != ".parquet":
        raise ForwardVintageError("registered source path is outside the approved parquet root")
    for field in ("retrievedAt", "assetUpdatedAt", "releasePublishedAt"):
        value = partition.get(field)
        if value is not None and _time(value) > observed:
            raise ForwardVintageError(f"source {field} occurs after the actual archive clock")
    if not partition.get("retrievedAt"):
        raise ForwardVintageError("original source retrieval timestamp is unavailable")
    parquet = pq.ParquetFile(path)
    if "season" in parquet.schema_arrow.names:
        index = parquet.schema_arrow.names.index("season")
        for group in range(parquet.metadata.num_row_groups):
            stats = parquet.metadata.row_group(group).column(index).statistics
            if stats is None or not stats.has_min_max or stats.min != 2026 or stats.max != 2026 or stats.null_count:
                raise ForwardVintageError("parquet season statistics do not prove an exclusively 2026 payload")
    raw = path.read_bytes()
    if len(raw) != partition["byteCount"] or hashlib.sha256(raw).hexdigest() != partition["fileSha256"]:
        raise ForwardVintageError("registered source checksum or byte count differs")
    metadata = {"sourceIdentity": {key: partition.get(key) for key in ("familyId", "season", "sourceUrl", "assetId", "assetName", "sourceContractVersion")},
                "sourceFile": {"path": str(path), "sha256": partition["fileSha256"], "byteCount": len(raw)},
                "sourceRetrievedAtUtc": _text(partition["retrievedAt"]),
                "assetUpdatedAtUtc": _text(partition["assetUpdatedAt"]) if partition.get("assetUpdatedAt") else None,
                "releasePublishedAtUtc": _text(partition["releasePublishedAt"]) if partition.get("releasePublishedAt") else None,
                "effectiveAt": partition.get("effectiveAt"),
                "effectiveTimeStatus": "SOURCE_DECLARED" if partition.get("effectiveAt") else "NOT_DECLARED_ROW_FIELDS_RETAINED_WITHOUT_INVENTED_TIMESTAMP",
                "rowEffectiveTimeColumns": [name for name in parquet.schema_arrow.names if name in ("dt", "gameday", "game_date", "week", "season")],
                "rowCount": parquet.metadata.num_rows, "sourceRights": partition["license"],
                "scopeProof": "REGISTERED_PHYSICAL_2026_PARTITION_AND_SEASON_FOOTER_WHEN_PRESENT"}
    return raw, metadata


def _snapshot(root: Path, family: str, raw: bytes, suffix: str, metadata: dict[str, Any], observed: datetime,
              previous: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    identity = hashlib.sha256(canonical_json_bytes(metadata)).hexdigest()
    previous_ref = (previous.get("vintage") or previous.get("lastKnownVintage")) if previous else None
    if previous and previous.get("sourceVersionIdentity") == identity:
        prior, _ = _verified_json(Path(previous_ref["path"]), previous_ref["sha256"])
        if file_record(Path(prior["payload"]["path"])) != prior["payload"]:
            raise ForwardVintageError("previous archived payload checksum differs")
        restored = {"status": "AVAILABLE", "familyId": family, "sourceVersionIdentity": identity,
                    "vintage": previous_ref, "observedAtUtc": prior["observedAtUtc"], "rowCount": prior["rowCount"]}
        return restored, restored != previous
    payload_sha = hashlib.sha256(raw).hexdigest()
    payload_path = root / "objects/sha256" / payload_sha / f"snapshot{suffix}"
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    if payload_path.exists():
        if payload_path.read_bytes() != raw:
            raise ForwardVintageError("content-addressed payload was modified")
    else:
        with payload_path.open("xb") as stream:
            stream.write(raw)
    body = {"schemaVersion": "NFL_FORWARD_SOURCE_VINTAGE_V1", **AUTHORITY, "familyId": family, "season": 2026,
            "sourceVersionIdentity": identity, "observedAtUtc": _text(observed), "earliestPermittedForecastCutoffUtc": _text(observed),
            "observationMeaning": "FIRST_ARCHIVE_OBSERVATION_OF_THIS_VERSION_NOT_BACKDATED_TO_SOURCE_RETRIEVAL",
            "payload": file_record(payload_path), **metadata, "previousFamilyVintage": previous_ref,
            "changeClassification": "FIRST_CAPTURE" if not previous_ref else "CONTENT_CHANGED_OR_SOURCE_METADATA_CORRECTED",
            "rowEvidenceClass": "OBSERVED_AS_OF_INHERITED_FROM_THIS_ENVELOPE",
            "rowAvailabilityRule": "Rows are eligible no earlier than observedAtUtc, independently of older row effective dates; explicit future effective dates remain future-effective.",
            "lateHistoricalCorrections": "Exact pre-capture correction lineage is unknown; this chain preserves only changes observed from this capture onward."}
    ref = _put(root / "vintages" / family, "vintage.json", body)
    return {"status": "AVAILABLE", "familyId": family, "sourceVersionIdentity": identity, "vintage": ref,
            "observedAtUtc": body["observedAtUtc"], "rowCount": metadata["rowCount"]}, True


def capture_forward_vintages(*, bronze_root: Path = DEFAULT_BRONZE, output_root: Path = DEFAULT_OUTPUT,
                            schedule_handoff: Path | None = DEFAULT_SCHEDULE_HANDOFF,
                            clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict[str, Any]:
    output_root = Path(output_root).resolve()
    if not output_root.is_relative_to(OUTPUTS_ROOT.resolve()) or output_root == OUTPUTS_ROOT.resolve():
        raise ForwardVintageError("archive output must be a dedicated Model Studio outputs subdirectory")
    with interprocess_lock(output_root / "capture.lock", blocking=False):
        observed = _time(clock())
        current_path = output_root / "CURRENT.json"
        prior = json.loads(current_path.read_bytes()) if current_path.exists() else {}
        heads = dict(prior.get("families", {}))
        pointer = json.loads((Path(bronze_root) / "current.json").read_bytes())
        manifest_path = (Path(bronze_root) / pointer["manifestRelativePath"]).resolve()
        if not manifest_path.is_relative_to(Path(bronze_root).resolve()):
            raise ForwardVintageError("source manifest escapes the approved metadata root")
        manifest, manifest_ref = _verified_json(manifest_path, pointer["manifestSha256"])
        statuses: dict[str, Any] = {}
        changed: list[str] = []
        payload_seasons_read: set[int] = set()
        for family in FAMILIES:
            all_sources = [row for row in manifest["partitions"] if row.get("familyId") == family]
            candidates = [row for row in all_sources if _scope_reason(row) is None]
            if len(candidates) > 1:
                raise ForwardVintageError(f"multiple current source objects require explicit authority for {family}")
            if candidates:
                raw, metadata = _partition_payload(Path(bronze_root), candidates[0], observed)
                payload_seasons_read.add(2026)
                statuses[family], advanced = _snapshot(output_root, family, raw, ".parquet", metadata, observed, heads.get(family))
            elif family == "schedules" and schedule_handoff is not None and Path(schedule_handoff).is_file():
                projection = schedule_events_from_handoff(schedule_handoff)
                # Parent publication times are validated as lineage, never used
                # to backdate this new forward archive's actual observation.
                for row in projection["events"]:
                    if _time(row["sourceForecastCreatedUtc"]) > observed:
                        raise ForwardVintageError("schedule parent forecast postdates archive clock")
                raw = canonical_json_bytes(projection)
                payload_seasons_read.add(2026)
                metadata = {"sourceIdentity": {"familyId": "schedules", "season": 2026, "derivation": projection["derivation"]},
                            "sourceHandoffs": projection["sourceHandoffs"], "sourceScheduleMetadataOnly": projection["sourceScheduleMetadataOnly"],
                            "sourceFile": {"sha256": hashlib.sha256(raw).hexdigest(), "byteCount": len(raw)},
                            "sourceRetrievedAtUtc": None, "assetUpdatedAtUtc": None, "releasePublishedAtUtc": None, "effectiveAt": None,
                            "effectiveTimeStatus": "PER_EVENT_KICKOFF_NOT_SOURCE_RELEASE", "rowCount": projection["eventCount"],
                            "fullSeasonCoverage": False, "sourceRights": [row.get("license") for row in projection["sourceScheduleMetadataOnly"]],
                            "limitations": projection["limitations"]}
                statuses[family], advanced = _snapshot(output_root, family, raw, ".json", metadata, observed, heads.get(family))
            else:
                statuses[family] = {"status": "UNAVAILABLE", "familyId": family,
                                    "reason": "NO_AUTHORIZED_PHYSICAL_2026_PARTITION" if not all_sources else "MIXED_OR_OTHER_SEASON_SOURCE_NOT_OPENED",
                                    "sourceDispositionReasons": sorted({_scope_reason(row) for row in all_sources}),
                                    "requiredInput": "Existing authorized 2026-only partition with source identity, original retrieval/release/effective metadata, rights and checksum. No provider is called by this job."}
                previous = heads.get(family, {})
                previous_ref = previous.get("vintage") or previous.get("lastKnownVintage")
                if previous_ref:
                    statuses[family].update({"lastKnownVintage": previous_ref,
                                             "sourceVersionIdentity": previous["sourceVersionIdentity"]})
                advanced = statuses[family] != heads.get(family)
            if advanced:
                changed.append(family)
        if not changed and prior:
            return {"status": "NO_OP", "evidenceClass": "OBSERVED_AS_OF", "changedFamilies": [],
                    "manifest": prior["manifest"], "families": statuses, "providerCalls": 0, "sealed2025PayloadRead": False}
        receipt = {"schemaVersion": "NFL_FORWARD_VINTAGE_ARCHIVE_MANIFEST_V1", **AUTHORITY,
                   "archiveObservedAtUtc": _text(observed), "season": 2026, "families": statuses,
                   "changedFamilies": changed, "sourceRegistrationMetadata": manifest_ref, "previousArchiveManifest": prior.get("manifest"),
                   "availableFamilies": sum(row["status"] == "AVAILABLE" for row in statuses.values()),
                   "unavailableFamilies": sum(row["status"] == "UNAVAILABLE" for row in statuses.values()),
                   "providerCalls": 0, "sourcePayloadSeasonsRead": sorted(payload_seasons_read), "sealed2025PayloadRead": False,
                   "modelFits": 0, "aispWrites": 0,
                   "historicalUse": "Does not establish any 2018–2024 original publication vintage. Eligibility begins at each version's actual forward observedAtUtc."}
        ref = _put(output_root / "manifests", "manifest.json", receipt)
        _pointer(current_path, {"schemaVersion": "NFL_FORWARD_VINTAGE_CURRENT_V1", **AUTHORITY, "manifest": ref, "families": statuses})
        return {"status": "CAPTURED", "manifest": ref, "families": statuses, "changedFamilies": changed,
                "providerCalls": 0, "sealed2025PayloadRead": False}


def select_vintage(output_root: Path, family: str, cutoff: str | datetime) -> dict[str, Any] | None:
    """Select the latest actually archived version at a future evaluation cutoff."""
    if family not in FAMILIES:
        raise ForwardVintageError("unknown source family")
    current = json.loads((Path(output_root) / "CURRENT.json").read_bytes())
    head = current.get("families", {}).get(family, {})
    ref = head.get("vintage") or head.get("lastKnownVintage")
    seen: set[str] = set()
    while ref:
        if ref["sha256"] in seen:
            raise ForwardVintageError("correction lineage cycle")
        seen.add(ref["sha256"])
        vintage, _ = _verified_json(Path(ref["path"]), ref["sha256"])
        if _time(vintage["observedAtUtc"]) <= _time(cutoff):
            if file_record(Path(vintage["payload"]["path"])) != vintage["payload"]:
                raise ForwardVintageError("selected vintage payload checksum differs")
            return vintage
        ref = vintage.get("previousFamilyVintage")
    return None
