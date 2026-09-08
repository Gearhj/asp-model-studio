"""Bounded next-slate handoff for the frozen NFL M1 research shadow.

The handoff does not fit or execute a model.  It selects the effective forecast
from an already-published, strictly verified exchange bundle and binds the
three-file AISP import object with byte counts and SHA-256 checksums.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_gold.nfl_shadow_exchange import (
    BUNDLE_OBJECT_FAMILY,
    PublishedSportsForecastBundle,
    verify_nfl_2026_research_shadow_locator,
    verify_sports_forecast_bundle,
)

from .prospective_shadow import (
    ARTIFACT_ROOT,
    DEFAULT_EXCHANGE_ROOT,
    DEFAULT_NFL_STAGING_ROOT,
    DEFAULT_PUBLICATION_ROOT,
    FOUNDATION_MANIFEST_SHA256,
    MODEL_BINARY_SHA256,
    MODEL_CANDIDATE,
    MODEL_MANIFEST_SHA256,
    TRAINING_CUTOFF,
    _load_targets,
    load_foundation_runtime,
    verify_activation_reload_fixture,
    verify_frozen_m1,
)


HANDOFF_SCHEMA_VERSION = "ASP_NFL_M1_CURRENT_SLATE_HANDOFF_V1"
DEFAULT_HANDOFF_ROOT = Path("outputs") / "nfl-existing-track-current-shadow-v1"
UTC = timezone.utc


class NflCurrentShadowError(RuntimeError):
    """The bounded current-slate handoff failed closed."""


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NflCurrentShadowError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


def _sha_file(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "name": path.name,
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "byteCount": len(payload),
    }


def _expected_events(
    slate_date: date,
    *,
    as_of: datetime,
    foundation_root: Path,
) -> list[dict[str, Any]]:
    runtime = load_foundation_runtime(foundation_root)
    targets, _, _ = _load_targets(runtime, as_of=as_of)
    return [
        {
            "eventId": str(target["canonical_game_id"]),
            "homeTeamId": str(target["canonical_home_team_id"]),
            "awayTeamId": str(target["canonical_away_team_id"]),
            "scheduledStartUtc": target["scheduled_start_utc"].astimezone(UTC).isoformat().replace("+00:00", "Z"),
        }
        for target in targets
        if str(target["game_date"]) == slate_date.isoformat()
    ]


def _bundle_for_slate(exchange_root: Path, slate_date: date) -> tuple[Mapping[str, Any], PublishedSportsForecastBundle]:
    locator = verify_nfl_2026_research_shadow_locator(exchange_root)
    matches: list[str] = []
    for digest in locator["currentBundleSha256s"]:
        path = exchange_root / BUNDLE_OBJECT_FAMILY / "sha256" / digest / "bundle.json"
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NflCurrentShadowError("current locator names an unreadable bundle") from exc
        if raw.get("slateDate") == slate_date.isoformat():
            matches.append(digest)
    if len(matches) != 1:
        raise NflCurrentShadowError(
            f"expected exactly one current bundle for {slate_date.isoformat()}, observed {len(matches)}"
        )
    return locator, verify_sports_forecast_bundle(exchange_root, matches[0])


def _effective_forecasts(bundle: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    priority = {"EARLY": 1, "CURRENT": 2, "FINAL_PREGAME": 3}
    selected: dict[str, Mapping[str, Any]] = {}
    for forecast in bundle["forecasts"]:
        event_id = str(forecast["eventId"])
        candidate = (
            priority[str(forecast["snapshotType"])],
            int(forecast["snapshotVersion"]),
            _utc(str(forecast["availableAsOfUtc"])),
        )
        current = selected.get(event_id)
        if current is None:
            selected[event_id] = forecast
            continue
        current_key = (
            priority[str(current["snapshotType"])],
            int(current["snapshotVersion"]),
            _utc(str(current["availableAsOfUtc"])),
        )
        if candidate > current_key:
            selected[event_id] = forecast
    return selected


def _forecast_summary(forecast: Mapping[str, Any]) -> dict[str, Any]:
    expected_home = float(forecast["expectedHomeScore"])
    expected_away = float(forecast["expectedAwayScore"])
    return {
        "forecastId": forecast["forecastId"],
        "eventId": forecast["eventId"],
        "sourceEventId": forecast["sourceEventId"],
        "homeTeamId": forecast["homeTeam"]["teamId"],
        "awayTeamId": forecast["awayTeam"]["teamId"],
        "kickoffUtc": forecast["scheduledStartUtc"],
        "forecastCreatedUtc": forecast["availableAsOfUtc"],
        "forecastCutoffUtc": forecast["forecastCutoffUtc"],
        "evidenceCutoffUtc": forecast["sourceCutoffUtc"],
        "snapshotType": forecast["snapshotType"],
        "snapshotVersion": forecast["snapshotVersion"],
        "modelId": forecast["engine"]["engineId"],
        "modelVersion": forecast["engine"]["engineVersion"],
        "modelManifestSha256": forecast["engine"]["modelManifestSha256"],
        "modelBinarySha256": forecast["engine"]["modelBinarySha256"],
        "trainingCutoff": forecast["engine"]["trainingCutoff"],
        "homeWinProbability": forecast["homeWinProbability"],
        "awayWinProbability": forecast["awayWinProbability"],
        "tieProbability": forecast["tieProbability"],
        "expectedHomeScore": expected_home,
        "expectedAwayScore": expected_away,
        "expectedMarginHomeMinusAway": expected_home - expected_away,
        "expectedTotal": expected_home + expected_away,
        "readiness": forecast["readiness"],
        "supportedOutputs": [
            "HOME_AWAY_TIE_PROBABILITIES",
            "EXPECTED_HOME_AND_AWAY_SCORE",
            "EXPECTED_MARGIN",
            "EXPECTED_TOTAL",
            "JOINT_SCORE_DISTRIBUTION",
            "SPREAD_AND_TOTAL_PROJECTIONS",
        ],
    }


def build_current_slate_handoff(
    slate_date: date,
    *,
    exchange_root: Path = DEFAULT_EXCHANGE_ROOT,
    foundation_root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1",
    artifact_root: Path = ARTIFACT_ROOT,
    publication_root: Path = DEFAULT_PUBLICATION_ROOT,
    expected_events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one deterministic next-slate handoff from verified authority."""

    exchange_root = Path(exchange_root).resolve()
    frozen = verify_frozen_m1(
        artifact_root=artifact_root,
        foundation_root=foundation_root,
        publication_root=publication_root,
    )
    index_path = Path(publication_root) / "prospective-index.json"
    if not index_path.is_file():
        raise NflCurrentShadowError("prospective activation index is absent")
    try:
        activation_index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NflCurrentShadowError("prospective activation index is unreadable") from exc
    fixture_sha = activation_index.get("reloadFixtureSha256")
    if not isinstance(fixture_sha, str):
        raise NflCurrentShadowError("prospective activation reload fixture is absent")
    verify_activation_reload_fixture(Path(publication_root), fixture_sha, frozen)
    locator, published = _bundle_for_slate(exchange_root, slate_date)
    bundle = published.record
    publication_time = _utc(str(bundle["generatedAtUtc"]))
    expected = list(expected_events) if expected_events is not None else _expected_events(
        slate_date,
        as_of=publication_time,
        foundation_root=foundation_root,
    )
    if not expected:
        raise NflCurrentShadowError("verified foundation has no upcoming event on the requested slate")
    if len({str(item["eventId"]) for item in expected}) != len(expected):
        raise NflCurrentShadowError("expected slate contains duplicate event identities")

    effective = _effective_forecasts(bundle)
    expected_ids = {str(item["eventId"]) for item in expected}
    if set(effective) - expected_ids:
        raise NflCurrentShadowError("current bundle contains an event outside the verified slate")

    summaries: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    for event in sorted(expected, key=lambda item: (str(item["scheduledStartUtc"]), str(item["eventId"]))):
        event_id = str(event["eventId"])
        forecast = effective.get(event_id)
        if forecast is None:
            skips.append({**dict(event), "reason": "NO_VERIFIED_CURRENT_FORECAST"})
            continue
        if (
            forecast["homeTeam"]["teamId"] != event["homeTeamId"]
            or forecast["awayTeam"]["teamId"] != event["awayTeamId"]
            or _utc(forecast["scheduledStartUtc"]) != _utc(str(event["scheduledStartUtc"]))
        ):
            skips.append({**dict(event), "reason": "EVENT_OR_TEAM_IDENTITY_MISMATCH"})
            continue
        summary = _forecast_summary(forecast)
        if not (
            _utc(summary["evidenceCutoffUtc"])
            <= _utc(summary["forecastCutoffUtc"])
            <= _utc(summary["forecastCreatedUtc"])
            < _utc(summary["kickoffUtc"])
        ):
            skips.append({**dict(event), "reason": "PREGAME_CUTOFF_ORDER_INVALID"})
            continue
        summaries.append(summary)

    object_dir = published.bundle_path.parent
    files = [_sha_file(object_dir / name) for name in ("bundle.json", "consumer-import-fixture.json", "VALIDATION.md")]
    import_allowed = not skips and len(summaries) == len(expected)
    first = summaries[0] if summaries else None
    return {
        "schemaVersion": HANDOFF_SCHEMA_VERSION,
        "sport": "NFL",
        "league": "NFL",
        "season": 2026,
        "slateDate": slate_date.isoformat(),
        "publicationTimestampUtc": bundle["generatedAtUtc"],
        "status": "RESEARCH_SHADOW",
        "promotionStatus": "NOT_PROMOTED",
        "wageringAuthority": False,
        "executionAllowedInAISP": False,
        "importAllowed": import_allowed,
        "model": {
            "modelId": None if first is None else first["modelId"],
            "modelVersion": None if first is None else first["modelVersion"],
            "candidateId": MODEL_CANDIDATE,
            "modelManifestSha256": MODEL_MANIFEST_SHA256,
            "modelBinarySha256": MODEL_BINARY_SHA256,
            "trainingCutoff": TRAINING_CUTOFF,
            "trainingFoundationManifestSha256": FOUNDATION_MANIFEST_SHA256,
        },
        "source": {
            "locatorPath": str((exchange_root / BUNDLE_OBJECT_FAMILY / "nfl-2026-research-shadow-index.json").resolve()),
            "locatorCurrentBundleListSha256": locator["currentBundleListSha256"],
            "sourceBundleSha256": published.bundle_sha256,
            "sourceBundleLogicalUri": f"asp-model-exchange://{BUNDLE_OBJECT_FAMILY}/sha256/{published.bundle_sha256}/bundle.json",
            "sourceBundleDirectory": str(object_dir.resolve()),
            "sourceBundleForecastCount": len(bundle["forecasts"]),
        },
        "eventCount": len(expected),
        "forecastCount": len(summaries),
        "skipCount": len(skips),
        "forecasts": summaries,
        "skips": skips,
        "files": files,
        "executionEvidence": {
            "frozenEstimatorReloaded": True,
            "deterministicReloadFixtureReproduced": True,
            "modelFits": 0,
            "providerCalls": 0,
            "marketFieldsRead": False,
            "sealedOotAccessed": False,
        },
    }


def verify_current_slate_handoff(path: Path) -> Mapping[str, Any]:
    """Verify the handoff address, inventory, disposition, and source bytes."""

    path = Path(path).resolve()
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if path.name != "handoff.json" or path.parent.name != digest:
        raise NflCurrentShadowError("handoff content address differs")
    try:
        record = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise NflCurrentShadowError("handoff JSON is invalid") from exc
    if payload != canonical_json_bytes(record):
        raise NflCurrentShadowError("handoff is not canonical JSON")
    if (
        record.get("schemaVersion") != HANDOFF_SCHEMA_VERSION
        or record.get("status") != "RESEARCH_SHADOW"
        or record.get("promotionStatus") != "NOT_PROMOTED"
        or record.get("wageringAuthority") is not False
        or record.get("executionAllowedInAISP") is not False
    ):
        raise NflCurrentShadowError("handoff research-shadow disposition differs")
    if record.get("eventCount") != record.get("forecastCount", 0) + record.get("skipCount", 0):
        raise NflCurrentShadowError("handoff event accounting differs")
    if record.get("importAllowed") != (record.get("skipCount") == 0):
        raise NflCurrentShadowError("handoff import authority differs")
    files = record.get("files")
    if not isinstance(files, list) or {item.get("name") for item in files} != {
        "bundle.json", "consumer-import-fixture.json", "VALIDATION.md"
    }:
        raise NflCurrentShadowError("handoff file inventory differs")
    for item in files:
        observed = _sha_file(Path(item["path"]))
        if observed != item:
            raise NflCurrentShadowError(f"handoff source file differs: {item.get('name')}")
    bundle_file = next(item for item in files if item["name"] == "bundle.json")
    if bundle_file["sha256"] != record["source"]["sourceBundleSha256"]:
        raise NflCurrentShadowError("handoff source bundle digest differs")
    for forecast in record.get("forecasts", []):
        if not math.isclose(
            forecast["homeWinProbability"] + forecast["awayWinProbability"] + forecast["tieProbability"],
            1.0,
            abs_tol=1e-9,
        ):
            raise NflCurrentShadowError("handoff win probabilities do not reconcile")
        if not (
            _utc(forecast["evidenceCutoffUtc"])
            <= _utc(forecast["forecastCutoffUtc"])
            <= _utc(forecast["forecastCreatedUtc"])
            < _utc(forecast["kickoffUtc"])
        ):
            raise NflCurrentShadowError("handoff forecast is not point-in-time pregame")
    return record


def publish_current_slate_handoff(
    slate_date: date,
    *,
    output_root: Path = DEFAULT_HANDOFF_ROOT,
    exchange_root: Path = DEFAULT_EXCHANGE_ROOT,
    foundation_root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1",
    artifact_root: Path = ARTIFACT_ROOT,
    publication_root: Path = DEFAULT_PUBLICATION_ROOT,
    expected_events: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write and reload one immutable content-addressed handoff."""

    record = build_current_slate_handoff(
        slate_date,
        exchange_root=exchange_root,
        foundation_root=foundation_root,
        artifact_root=artifact_root,
        publication_root=publication_root,
        expected_events=expected_events,
    )
    payload = canonical_json_bytes(record)
    digest = hashlib.sha256(payload).hexdigest()
    root = Path(output_root).resolve()
    parent = root / "sha256"
    parent.mkdir(parents=True, exist_ok=True)
    final = parent / digest
    if final.exists():
        path = final / "handoff.json"
        verified = verify_current_slate_handoff(path)
        return {"handoffSha256": digest, "handoffPath": str(path), "created": False, **dict(verified)}
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
    verified = verify_current_slate_handoff(path)
    return {"handoffSha256": digest, "handoffPath": str(path), "created": True, **dict(verified)}


__all__ = [
    "DEFAULT_HANDOFF_ROOT",
    "HANDOFF_SCHEMA_VERSION",
    "NflCurrentShadowError",
    "build_current_slate_handoff",
    "publish_current_slate_handoff",
    "verify_current_slate_handoff",
]
