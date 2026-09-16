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
from datetime import date, datetime, timedelta, timezone
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


HANDOFF_SCHEMA_VERSION = "ASP_NFL_M1_CURRENT_SLATE_HANDOFF_V2"
REFRESH_SELECTION_SCHEMA = "ASP_NFL_M1_REFRESH_SELECTION_SCOPE_V1"
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


def _refresh_expected_events(
    slate_date: date, refresh: Mapping[str, Any], runtime: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Bind a refreshed selection to its activation clock, not bundle age."""
    if refresh.get("status") != "ACTIVE":
        raise NflCurrentShadowError("refresh evidence is not an active publication check")
    dates = refresh.get("selectedSlateDates")
    plan = refresh.get("eventPlan")
    if (not isinstance(dates, list) or not dates or dates != sorted(set(dates))
            or slate_date.isoformat() not in dates
            or not isinstance(plan, list) or not plan):
        raise NflCurrentShadowError("refresh selection requires exact slate dates and event plan")
    if (refresh.get("sourceFoundationManifestSha256") != runtime.paths.foundation_manifest_sha256
            or refresh.get("sourceEvidenceAsOfUtc") != runtime.schedule_as_of_utc):
        raise NflCurrentShadowError("refresh evidence source authority differs")
    try:
        cutoff = _utc(str(refresh["forecastCutoffUtc"]))
        completed = _utc(str(refresh["completedAtUtc"]))
    except (KeyError, ValueError) as exc:
        raise NflCurrentShadowError("refresh selection clocks are absent or invalid") from exc
    if not _utc(runtime.schedule_as_of_utc) <= cutoff <= completed:
        raise NflCurrentShadowError("refresh selection cutoff order differs")
    mode = refresh.get("selectionMode")
    if mode not in {"ROLLING_WINDOW", "EXACT_SLATE", "NEXT_SLATE_ONLY", "ALL_UPCOMING"}:
        raise NflCurrentShadowError("refresh selection mode differs")
    days = refresh.get("rollingWindowDays")
    if mode == "ROLLING_WINDOW" and (not isinstance(days, int) or isinstance(days, bool) or days < 1):
        raise NflCurrentShadowError("refresh rolling window is invalid")
    targets, _, _ = _load_targets(runtime, as_of=cutoff)
    foundation = {str(target["canonical_game_id"]): target for target in targets}
    ids = [str(item.get("eventId") or "") for item in plan if isinstance(item, Mapping)]
    if len(ids) != len(plan) or not all(ids) or len(ids) != len(set(ids)):
        raise NflCurrentShadowError("refresh event plan contains invalid or duplicate identities")
    rolling_ids = None
    if mode == "ROLLING_WINDOW":
        boundary = cutoff + timedelta(days=days)
        rolling_ids = sorted(str(target["canonical_game_id"]) for target in targets
                             if cutoff < target["scheduled_start_utc"].astimezone(UTC) <= boundary)
        if sorted(ids) != rolling_ids:
            raise NflCurrentShadowError("refresh event plan differs from complete eligible rolling Foundation cohort")
    selected = []
    for entry in plan:
        event_id = str(entry["eventId"])
        target = foundation.get(event_id)
        if target is None:
            raise NflCurrentShadowError("refresh event plan is outside eligible Foundation identities")
        kickoff = target["scheduled_start_utc"].astimezone(UTC)
        if (_utc(str(entry["scheduledStartUtc"])) != kickoff or kickoff <= cutoff
                or (mode == "ROLLING_WINDOW" and kickoff > cutoff + timedelta(days=days))):
            raise NflCurrentShadowError("refresh event plan kickoff is outside its declared boundary")
        if str(target["game_date"]) not in dates:
            raise NflCurrentShadowError("refresh event plan slate differs from Foundation")
        selected.append({
            "eventId": event_id, "homeTeamId": str(target["canonical_home_team_id"]),
            "awayTeamId": str(target["canonical_away_team_id"]),
            "scheduledStartUtc": kickoff.isoformat().replace("+00:00", "Z"),
            "slateDate": str(target["game_date"]),
        })
    if sorted({event["slateDate"] for event in selected}) != dates:
        raise NflCurrentShadowError("refresh selected slate dates do not reconcile with event plan")
    expected = [{key: value for key, value in event.items() if key != "slateDate"}
                for event in selected if event["slateDate"] == slate_date.isoformat()]
    scope = {
        "schemaVersion": REFRESH_SELECTION_SCHEMA,
        "activationEvidence": dict(refresh),
        "activationEvidenceSha256": hashlib.sha256(canonical_json_bytes(refresh)).hexdigest(),
        "foundationEvents": sorted(selected, key=lambda item: item["eventId"]),
        "selectedEventIds": sorted(event["eventId"] for event in expected),
        "eligibleRollingFoundationEventIds": rolling_ids,
        "sourceBundlePreservedComplete": True,
        "selectionMeaning": "Exact activation eventPlan members on this slate; older or outside-window source children remain in the complete immutable bundle.",
    }
    return expected, scope


def _outside_selected_events(bundle: Mapping[str, Any], selected_ids: set[str]) -> list[dict[str, Any]]:
    effective = _effective_forecasts(bundle)
    return [{
        "eventId": event_id, "scheduledStartUtc": effective[event_id]["scheduledStartUtc"],
        "effectiveForecastId": effective[event_id]["forecastId"],
        "retainedForecastIds": sorted(str(row["forecastId"]) for row in bundle["forecasts"]
                                      if str(row["eventId"]) == event_id),
        "reason": "RETAINED_SOURCE_EVENT_OUTSIDE_ACTIVATION_SELECTION",
    } for event_id in sorted(set(effective) - selected_ids)]


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
    refresh_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one deterministic next-slate handoff from verified authority."""

    exchange_root = Path(exchange_root).resolve()
    frozen = verify_frozen_m1(
        artifact_root=artifact_root,
        foundation_root=foundation_root,
        publication_root=publication_root,
    )
    runtime = load_foundation_runtime(foundation_root)
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
    selection_scope = None
    if refresh_evidence is not None:
        expected, selection_scope = _refresh_expected_events(slate_date, refresh_evidence, runtime)
        if expected_events is not None:
            def identity(item):
                return (str(item["eventId"]), str(item["homeTeamId"]), str(item["awayTeamId"]),
                        _utc(str(item["scheduledStartUtc"])))
            if sorted(identity(item) for item in expected_events) != sorted(identity(item) for item in expected):
                raise NflCurrentShadowError("explicit expected events differ from verified activation selection")
    else:
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
    if selection_scope is None and set(effective) - expected_ids:
        raise NflCurrentShadowError("current bundle contains an event outside the verified slate")
    if selection_scope is not None:
        selection_scope["outsideSelectedSourceEvents"] = _outside_selected_events(bundle, expected_ids)
        selection_scope["selectedSourceForecastCount"] = sum(
            str(row["eventId"]) in expected_ids for row in bundle["forecasts"])
        selection_scope["outsideSelectedSourceForecastCount"] = sum(
            str(row["eventId"]) not in expected_ids for row in bundle["forecasts"])

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
            if selection_scope is not None:
                raise NflCurrentShadowError("selected activation forecast event or team identity mismatch")
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

    evidence_cutoffs = {str(item["evidenceCutoffUtc"]) for item in summaries}
    if any(_utc(value) > _utc(runtime.schedule_as_of_utc) for value in evidence_cutoffs):
        raise NflCurrentShadowError("effective forecast claims evidence newer than current local source authority")
    if refresh_evidence is None:
        if evidence_cutoffs and evidence_cutoffs != {runtime.schedule_as_of_utc}:
            raise NflCurrentShadowError("effective forecast does not match current local source evidence")
        checked_at = publication_time
        forecasts_created_this_run: int | None = None
        unchanged_reused: int | None = None
        source_changed: bool | None = None
        prior_source_manifests: list[str] = []
        disposition = "SOURCE_STATE_AT_FORECAST_PUBLICATION"
    else:
        if refresh_evidence.get("status") != "ACTIVE":
            raise NflCurrentShadowError("refresh evidence is not an active publication check")
        if slate_date.isoformat() not in (refresh_evidence.get("selectedSlateDates") or []):
            raise NflCurrentShadowError("refresh evidence slate differs")
        if (
            refresh_evidence.get("sourceFoundationManifestSha256")
            != runtime.paths.foundation_manifest_sha256
            or refresh_evidence.get("sourceEvidenceAsOfUtc") != runtime.schedule_as_of_utc
        ):
            raise NflCurrentShadowError("refresh evidence source authority differs")
        checked_at = _utc(str(refresh_evidence["completedAtUtc"]))
        forecasts_created_this_run = int(refresh_evidence.get("forecastsCreated", 0))
        unchanged_reused = int(refresh_evidence.get("unchangedEvidenceForecastsReused", 0))
        source_changed = refresh_evidence.get("sourceFoundationChangedSincePreviousSnapshot")
        if source_changed not in {True, False, None}:
            raise NflCurrentShadowError("refresh evidence source-change state differs")
        prior_source_manifests = sorted(
            str(value) for value in refresh_evidence.get("priorSourceFoundationManifestSha256s", [])
        )
        disposition = (
            "NEW_FORECAST_VERSION_PUBLISHED"
            if forecasts_created_this_run
            else "UNCHANGED_SOURCE_EVIDENCE_FORECAST_REUSED"
        )
    if checked_at < _utc(runtime.schedule_as_of_utc):
        raise NflCurrentShadowError("freshness check predates current local source evidence")
    if summaries and checked_at >= min(_utc(item["kickoffUtc"]) for item in summaries):
        raise NflCurrentShadowError("current-slate handoff freshness check occurred after kickoff")

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
            "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256,
            "sourceEvidenceAsOfUtc": runtime.schedule_as_of_utc,
        },
        "sourceFreshness": {
            "checkedAtUtc": checked_at.isoformat().replace("+00:00", "Z"),
            "evidenceAsOfUtc": runtime.schedule_as_of_utc,
            "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256,
            "sourceDatasetVersionId": runtime.paths.dataset_version_id,
            "effectiveForecastEvidenceCutoffsUtc": sorted(evidence_cutoffs),
            "priorSourceFoundationManifestSha256s": prior_source_manifests,
            "sourceFoundationChangedSincePreviousSnapshot": source_changed,
            "newForecastCountThisRun": forecasts_created_this_run,
            "unchangedEvidenceForecastsReused": unchanged_reused,
            "forecastDisposition": disposition,
            "publicationTimestampRepresentsSourceRefresh": False,
        },
        "eventCount": len(expected),
        "forecastCount": len(summaries),
        "skipCount": len(skips),
        "forecasts": summaries,
        "skips": skips,
        "files": files,
        **({"selectionScope": selection_scope} if selection_scope is not None else {}),
        "executionEvidence": {
            "frozenEstimatorReloaded": True,
            "deterministicReloadFixtureReproduced": True,
            "modelFits": 0,
            "providerCalls": 0,
            "marketFieldsRead": False,
            "sealedOotAccessed": False,
        },
    }


def _verify_refresh_scope(record: Mapping[str, Any], bundle: Mapping[str, Any]) -> None:
    """Verify additive refresh accounting without reopening historical sources."""
    scope = record["selectionScope"]
    activation = scope.get("activationEvidence") or {}
    source = record["source"]
    if (scope.get("schemaVersion") != REFRESH_SELECTION_SCHEMA
            or scope.get("sourceBundlePreservedComplete") is not True
            or hashlib.sha256(canonical_json_bytes(activation)).hexdigest() != scope.get("activationEvidenceSha256")
            or activation.get("status") != "ACTIVE"
            or activation.get("sourceFoundationManifestSha256") != source["sourceFoundationManifestSha256"]
            or activation.get("sourceEvidenceAsOfUtc") != source["sourceEvidenceAsOfUtc"]):
        raise NflCurrentShadowError("handoff activation selection binding differs")
    plan = activation.get("eventPlan") or []
    events = scope.get("foundationEvents") or []
    plan_ids = [str(item["eventId"]) for item in plan]
    event_ids = [str(item["eventId"]) for item in events]
    if (not events or len(plan_ids) != len(set(plan_ids))
            or len(event_ids) != len(set(event_ids)) or set(plan_ids) != set(event_ids)
            or sorted({event["slateDate"] for event in events}) != activation.get("selectedSlateDates")):
        raise NflCurrentShadowError("handoff activation event accounting differs")
    cutoff = _utc(activation["forecastCutoffUtc"])
    completed = _utc(activation["completedAtUtc"])
    if not _utc(source["sourceEvidenceAsOfUtc"]) <= cutoff <= completed:
        raise NflCurrentShadowError("handoff activation selection clocks differ")
    if completed != _utc(record["sourceFreshness"]["checkedAtUtc"]):
        raise NflCurrentShadowError("handoff freshness is not the bound activation check")
    mode = activation.get("selectionMode")
    days = activation.get("rollingWindowDays")
    if (mode not in {"ROLLING_WINDOW", "EXACT_SLATE", "NEXT_SLATE_ONLY", "ALL_UPCOMING"}
            or (mode == "ROLLING_WINDOW" and (not isinstance(days, int) or isinstance(days, bool) or days < 1))):
        raise NflCurrentShadowError("handoff activation selection mode differs")
    if mode == "ROLLING_WINDOW" and scope.get("eligibleRollingFoundationEventIds") != sorted(plan_ids):
        raise NflCurrentShadowError("handoff activation omits or expands the eligible rolling Foundation cohort")
    planned = {str(item["eventId"]): item for item in plan}
    for event in events:
        start = _utc(event["scheduledStartUtc"])
        if (start != _utc(planned[event["eventId"]]["scheduledStartUtc"]) or start <= cutoff
                or (mode == "ROLLING_WINDOW" and start > cutoff + timedelta(days=days))):
            raise NflCurrentShadowError("handoff event exceeds activation cutoff or window")
    selected = {str(event["eventId"]): event for event in events if event["slateDate"] == record["slateDate"]}
    summaries = {str(item["eventId"]): item for item in record["forecasts"]}
    skips = {str(item["eventId"]): item for item in record["skips"]}
    if (not selected or sorted(selected) != scope.get("selectedEventIds")
            or set(summaries) & set(skips) or set(summaries) | set(skips) != set(selected)
            or len(summaries) != record["forecastCount"] or len(skips) != record["skipCount"]):
        raise NflCurrentShadowError("handoff selected event accounting differs")
    effective = _effective_forecasts(bundle)
    for event_id, summary in summaries.items():
        forecast = effective.get(event_id)
        event = selected[event_id]
        if (forecast is None or summary != _forecast_summary(forecast)
                or summary["homeTeamId"] != event["homeTeamId"]
                or summary["awayTeamId"] != event["awayTeamId"]
                or _utc(summary["kickoffUtc"]) != _utc(event["scheduledStartUtc"])
                or completed >= _utc(summary["kickoffUtc"])):
            raise NflCurrentShadowError("handoff selected forecast differs from original source or deadline")
    if (scope.get("outsideSelectedSourceEvents") != _outside_selected_events(bundle, set(selected))
            or source["sourceBundleForecastCount"] != len(bundle["forecasts"])
            or scope.get("selectedSourceForecastCount") != sum(str(row["eventId"]) in selected for row in bundle["forecasts"])
            or scope.get("outsideSelectedSourceForecastCount") != sum(str(row["eventId"]) not in selected for row in bundle["forecasts"])):
        raise NflCurrentShadowError("handoff retained outside-selection source accounting differs")


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
    freshness = record.get("sourceFreshness") or {}
    if (
        freshness.get("publicationTimestampRepresentsSourceRefresh") is not False
        or freshness.get("sourceFoundationManifestSha256")
        != record.get("source", {}).get("sourceFoundationManifestSha256")
        or freshness.get("evidenceAsOfUtc")
        != record.get("source", {}).get("sourceEvidenceAsOfUtc")
    ):
        raise NflCurrentShadowError("handoff source-freshness declaration differs")
    if freshness.get("forecastDisposition") == "UNCHANGED_SOURCE_EVIDENCE_FORECAST_REUSED":
        if freshness.get("newForecastCountThisRun") != 0:
            raise NflCurrentShadowError("unchanged evidence created a numerical forecast version")
    current_evidence = _utc(str(freshness.get("evidenceAsOfUtc")))
    if any(
        _utc(str(value)) > current_evidence
        for value in freshness.get("effectiveForecastEvidenceCutoffsUtc", [])
    ):
        raise NflCurrentShadowError("effective forecast evidence exceeds checked source authority")
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
    if "selectionScope" in record:
        _verify_refresh_scope(record, json.loads(Path(bundle_file["path"]).read_bytes()))
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
    refresh_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Write and reload one immutable content-addressed handoff."""

    record = build_current_slate_handoff(
        slate_date,
        exchange_root=exchange_root,
        foundation_root=foundation_root,
        artifact_root=artifact_root,
        publication_root=publication_root,
        expected_events=expected_events,
        refresh_evidence=refresh_evidence,
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
