"""Immutable seven-day NFL M1 research-shadow publication handoff."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pyarrow.parquet as pq

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_nfl.bronze_acquisition import verify_nflverse_bronze
from server.sports_nfl.pipeline import NflFoundationConfig
from server.sports_nfl.publication import verify_foundation

from .current_shadow import verify_current_slate_handoff
from .prospective_shadow import DEFAULT_NFL_STAGING_ROOT, load_foundation_runtime


ROLLING_HANDOFF_CONTRACT = "ASP_NFL_M1_ROLLING_SHADOW_HANDOFF_V1"
DEFAULT_ROLLING_HANDOFF_ROOT = Path("outputs") / "nfl-week1-incremental-publication-v1"
class NflRollingPublicationError(RuntimeError):
    """A rolling research-shadow publication invariant failed."""


def _latest_source_assets(staging_root: Path) -> list[dict[str, Any]]:
    bronze_root = Path(staging_root) / "bronze-v1"
    bronze = verify_nflverse_bronze(bronze_root)
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for item in bronze["partitions"]:
        grouped.setdefault(str(item["familyId"]), []).append(item)
    assets: list[dict[str, Any]] = []
    for family_id, records in sorted(grouped.items()):
        current = [item for item in records if item.get("season") == 2026]
        combined = [item for item in records if item.get("season") is None]
        candidates = current or combined
        if not candidates:
            maximum = max(int(item["season"]) for item in records if item.get("season") is not None)
            candidates = [item for item in records if item.get("season") == maximum]
        for item in sorted(candidates, key=lambda value: (str(value.get("assetName")), str(value.get("relativePath")))):
            local_path = bronze_root / str(item["relativePath"])
            assets.append({
                "familyId": family_id,
                "season": item.get("season"),
                "releaseTag": item.get("releaseTag"),
                "releasePublishedAt": item.get("releasePublishedAt"),
                "assetUpdatedAt": item.get("assetUpdatedAt"),
                "retrievedAtUtc": item.get("retrievedAt"),
                "sourceUrl": item.get("sourceUrl"),
                "localPath": str(local_path.resolve()),
                "fileSha256": item.get("fileSha256"),
                "sourceDigest": item.get("sourceDigest"),
                "byteCount": item.get("byteCount"),
                "rowCount": item.get("rowCount"),
                "license": item.get("license"),
                "status": item.get("status"),
            })
    return assets


def _latest_completed_game_date(runtime: Any) -> str | None:
    rows = pq.read_table(
        runtime.objects["fact_nfl_team_game"]["path"],
        columns=["season", "game_date", "completed"],
    ).to_pandas()
    dates = pd.to_datetime(rows.loc[rows["season"].eq(2026) & rows["completed"].eq(True), "game_date"])
    return None if dates.empty else dates.max().date().isoformat()


def build_rolling_handoff(
    activation: Mapping[str, Any],
    slate_handoffs: Sequence[Mapping[str, Any]],
    *,
    staging_root: Path = DEFAULT_NFL_STAGING_ROOT,
    sync_report_path: Path = Path(".runtime") / "asp-model-studio" / "nfl-current-season-sync" / "latest-success.json",
) -> dict[str, Any]:
    if activation.get("status") != "ACTIVE" or activation.get("selectionMode") != "ROLLING_WINDOW":
        raise NflRollingPublicationError("rolling activation evidence differs")
    runtime = load_foundation_runtime(Path(staging_root) / "foundation-v1")
    verified_foundation = verify_foundation(Path(staging_root) / "foundation-v1", runtime.paths.foundation_manifest_sha256)
    dates = list(activation.get("selectedSlateDates") or [])
    handoffs = []
    for value in slate_handoffs:
        record = verify_current_slate_handoff(Path(value["handoffPath"]))
        if record["slateDate"] not in dates:
            raise NflRollingPublicationError("slate handoff falls outside rolling selection")
        handoffs.append({
            "slateDate": record["slateDate"],
            "handoffPath": str(Path(value["handoffPath"]).resolve()),
            "handoffSha256": value["handoffSha256"],
            "eventCount": record["eventCount"],
            "forecastCount": record["forecastCount"],
            "skipCount": record["skipCount"],
            "sourceBundleSha256": record["source"]["sourceBundleSha256"],
        })
    if sorted(item["slateDate"] for item in handoffs) != sorted(dates):
        raise NflRollingPublicationError("rolling slate handoff accounting differs")
    sync_path = Path(sync_report_path).resolve()
    sync_payload = sync_path.read_bytes()
    sync_report = json.loads(sync_payload)
    manifest = verified_foundation["manifest"]
    return {
        "schemaVersion": ROLLING_HANDOFF_CONTRACT,
        "sport": "NFL",
        "season": 2026,
        "windowDays": activation.get("rollingWindowDays"),
        "forecastCutoffUtc": activation["forecastCutoffUtc"],
        "publicationCompletedAtUtc": activation["completedAtUtc"],
        "status": "RESEARCH_SHADOW",
        "promotionStatus": "NOT_PROMOTED",
        "wageringAuthority": False,
        "executionAllowedInAISP": False,
        "source": {
            "provider": "nflverse-data",
            "providerRepository": "https://github.com/nflverse/nflverse-data",
            "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256,
            "sourceDatasetVersionId": runtime.paths.dataset_version_id,
            "sourceEvidenceAsOfUtc": runtime.schedule_as_of_utc,
            "latestCompleted2026GameDate": _latest_completed_game_date(runtime),
            "scheduled2026GameCount": manifest["coverage"]["currentSeasonScheduledGames"],
            "completed2026GameCount": manifest["coverage"]["currentSeasonCompletedGames"],
            "sourceFamilies": manifest["coverage"]["sourceFamilies"],
            "assets": _latest_source_assets(Path(staging_root)),
            "rights": manifest["rights"],
            "syncReport": {
                "path": str(sync_path),
                "sha256": hashlib.sha256(sync_payload).hexdigest(),
                "byteCount": len(sync_payload),
                "status": sync_report.get("status"),
                "sourceChanged": sync_report.get("sourceChanged"),
                "changedFamilies": sync_report.get("changedFamilies"),
            },
        },
        "model": {
            "modelManifestSha256": activation["modelManifestSha256"],
            "modelBinarySha256": activation["modelBinarySha256"],
            "modelsFit": activation["modelsFit"],
            "modelsPromoted": activation["modelsPromoted"],
        },
        "eventCount": sum(item["eventCount"] for item in handoffs),
        "forecastCount": sum(item["forecastCount"] for item in handoffs),
        "skipCount": sum(item["skipCount"] for item in handoffs),
        "newForecastCount": activation["forecastsCreated"],
        "unchangedForecastCount": activation["unchangedEvidenceForecastsReused"],
        "forecastInferenceRows": activation["forecastInferenceRows"],
        "completed2026GameIdsEligibleByFoundationCutoff": activation["completed2026GameIdsEligibleByFoundationCutoff"],
        "eventPlan": activation["eventPlan"],
        "alreadyStartedEvents": activation["alreadyStartedEvents"],
        "slateHandoffs": sorted(handoffs, key=lambda item: item["slateDate"]),
        "controls": {
            "targetOutcomeFieldsRead": False,
            "marketFieldsRead": False,
            "providerCallsDuringForecastPublication": 0,
            "sealedOotAccessed": False,
        },
    }


def verify_rolling_handoff(path: Path) -> Mapping[str, Any]:
    path = Path(path).resolve()
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if path.name != "handoff.json" or path.parent.name != digest:
        raise NflRollingPublicationError("rolling handoff content address differs")
    record = json.loads(payload)
    if payload != canonical_json_bytes(record):
        raise NflRollingPublicationError("rolling handoff is not canonical JSON")
    if (
        record.get("schemaVersion") != ROLLING_HANDOFF_CONTRACT
        or record.get("status") != "RESEARCH_SHADOW"
        or record.get("promotionStatus") != "NOT_PROMOTED"
        or record.get("wageringAuthority") is not False
        or record.get("executionAllowedInAISP") is not False
    ):
        raise NflRollingPublicationError("rolling research-shadow controls differ")
    if record.get("eventCount") != record.get("forecastCount", 0) + record.get("skipCount", 0):
        raise NflRollingPublicationError("rolling event accounting differs")
    for item in record.get("slateHandoffs", []):
        if item["handoffSha256"] != hashlib.sha256(Path(item["handoffPath"]).read_bytes()).hexdigest():
            raise NflRollingPublicationError("rolling child handoff checksum differs")
        verify_current_slate_handoff(Path(item["handoffPath"]))
    return record


def publish_rolling_handoff(
    activation: Mapping[str, Any],
    slate_handoffs: Sequence[Mapping[str, Any]],
    *,
    output_root: Path = DEFAULT_ROLLING_HANDOFF_ROOT,
    staging_root: Path = DEFAULT_NFL_STAGING_ROOT,
) -> dict[str, Any]:
    record = build_rolling_handoff(activation, slate_handoffs, staging_root=staging_root)
    payload = canonical_json_bytes(record)
    digest = hashlib.sha256(payload).hexdigest()
    parent = Path(output_root).resolve() / "sha256"
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / digest
    if not final.exists():
        staging = parent / f".staging-{uuid.uuid4().hex}"
        staging.mkdir(parents=False, exist_ok=False)
        try:
            with (staging / "handoff.json").open("xb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(staging, final)
            except OSError:
                if not final.exists():
                    raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
    path = final / "handoff.json"
    verified = verify_rolling_handoff(path)
    return {"handoffPath": str(path), "handoffSha256": digest, **dict(verified)}


__all__ = [
    "DEFAULT_ROLLING_HANDOFF_ROOT",
    "NflRollingPublicationError",
    "build_rolling_handoff",
    "publish_rolling_handoff",
    "verify_rolling_handoff",
]
