from __future__ import annotations

import json
import shutil
import uuid
from datetime import date
from pathlib import Path

import pytest

from server.sports_gold import nfl_shadow_exchange as X
from server.sports_nfl_m1 import current_shadow as C
from server.sports_nfl_m1 import prospective_shadow as P


SOURCE_EXCHANGE = Path(r"C:\Users\james\asp-model-exchange")
SLATE = date(2026, 9, 9)


def _isolated_slate_exchange(tmp_path: Path) -> tuple[Path, dict, dict]:
    source_locator_path = SOURCE_EXCHANGE / X.BUNDLE_OBJECT_FAMILY / X.NFL_2026_RESEARCH_SHADOW_INDEX_NAME
    source_locator = json.loads(source_locator_path.read_text(encoding="utf-8"))
    selected_sha = None
    selected_bundle = None
    for digest in source_locator["currentBundleSha256s"]:
        path = SOURCE_EXCHANGE / X.BUNDLE_OBJECT_FAMILY / "sha256" / digest / "bundle.json"
        candidate = json.loads(path.read_text(encoding="utf-8"))
        if candidate["slateDate"] == SLATE.isoformat():
            selected_sha = digest
            selected_bundle = candidate
            break
    assert selected_sha is not None and selected_bundle is not None
    exchange = (tmp_path / "exchange").resolve()
    exchange.mkdir(parents=True)
    source_dir = SOURCE_EXCHANGE / X.BUNDLE_OBJECT_FAMILY / "sha256" / selected_sha
    target_dir = exchange / X.BUNDLE_OBJECT_FAMILY / "sha256" / selected_sha
    target_dir.parent.mkdir(parents=True)
    shutil.copytree(source_dir, target_dir)
    X.write_nfl_2026_research_shadow_locator(
        exchange,
        current_bundle_sha256s=[selected_sha],
        historical_bundle_sha256s=[],
        feature_contract_sha256=source_locator["featureContractSha256"],
        updated_at_utc=selected_bundle["generatedAtUtc"],
    )
    current = max(
        selected_bundle["forecasts"],
        key=lambda item: ({"EARLY": 1, "CURRENT": 2, "FINAL_PREGAME": 3}[item["snapshotType"]], item["snapshotVersion"]),
    )
    expected = {
        "eventId": current["eventId"],
        "homeTeamId": current["homeTeam"]["teamId"],
        "awayTeamId": current["awayTeam"]["teamId"],
        "scheduledStartUtc": current["scheduledStartUtc"].replace(".000000Z", "Z"),
    }
    return exchange, current, expected


def test_bounded_slate_selection_is_exact_and_fail_closed() -> None:
    targets = [
        {"game_date": "2026-09-10", "id": "second"},
        {"game_date": "2026-09-09", "id": "first"},
        {"game_date": "2026-09-13", "id": "third"},
    ]
    assert [item["id"] for item in P._select_slate_targets(targets, slate_date=None, next_slate_only=True)] == ["first"]
    assert [item["id"] for item in P._select_slate_targets(targets, slate_date=SLATE, next_slate_only=False)] == ["first"]
    with pytest.raises(P.NflProspectiveShadowError, match="mutually exclusive"):
        P._select_slate_targets(targets, slate_date=SLATE, next_slate_only=True)


def test_current_slate_handoff_is_content_addressed_complete_and_idempotent() -> None:
    root = (Path(".runtime") / "nfl-current-shadow-tests" / uuid.uuid4().hex).resolve()
    try:
        exchange, current, expected = _isolated_slate_exchange(root)
        output = root / "handoff"
        runtime = P.load_foundation_runtime()
        refresh = {
            "status": "ACTIVE",
            "selectedSlateDates": [SLATE.isoformat()],
            "completedAtUtc": current["availableAsOfUtc"],
            "sourceEvidenceAsOfUtc": runtime.schedule_as_of_utc,
            "sourceFoundationManifestSha256": runtime.paths.foundation_manifest_sha256,
            "priorSourceFoundationManifestSha256s": [runtime.paths.foundation_manifest_sha256],
            "sourceFoundationChangedSincePreviousSnapshot": False,
            "forecastsCreated": 0,
            "unchangedEvidenceForecastsReused": 1,
        }
        first = C.publish_current_slate_handoff(
            SLATE,
            output_root=output,
            exchange_root=exchange,
            expected_events=[expected],
            refresh_evidence=refresh,
        )
        second = C.publish_current_slate_handoff(
            SLATE,
            output_root=output,
            exchange_root=exchange,
            expected_events=[expected],
            refresh_evidence=refresh,
        )
        assert first["created"] is True
        assert second["created"] is False
        assert first["handoffSha256"] == second["handoffSha256"]
        assert first["eventCount"] == first["forecastCount"] == 1
        assert first["skipCount"] == 0
        assert first["importAllowed"] is True
        assert first["status"] == "RESEARCH_SHADOW"
        assert first["promotionStatus"] == "NOT_PROMOTED"
        assert first["wageringAuthority"] is False
        assert first["executionAllowedInAISP"] is False
        assert first["schemaVersion"] == "ASP_NFL_M1_CURRENT_SLATE_HANDOFF_V2"
        assert first["sourceFreshness"]["forecastDisposition"] == "UNCHANGED_SOURCE_EVIDENCE_FORECAST_REUSED"
        assert first["sourceFreshness"]["newForecastCountThisRun"] == 0
        assert first["sourceFreshness"]["publicationTimestampRepresentsSourceRefresh"] is False
        assert {item["name"] for item in first["files"]} == {
            "bundle.json", "consumer-import-fixture.json", "VALIDATION.md"
        }
        forecast = first["forecasts"][0]
        assert forecast["forecastId"] == current["forecastId"]
        assert forecast["expectedMarginHomeMinusAway"] == pytest.approx(
            current["expectedHomeScore"] - current["expectedAwayScore"]
        )
        assert forecast["expectedTotal"] == pytest.approx(
            current["expectedHomeScore"] + current["expectedAwayScore"]
        )
        assert C.verify_current_slate_handoff(Path(first["handoffPath"])) == {
            key: value for key, value in first.items() if key not in {"handoffSha256", "handoffPath", "created"}
        }
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_current_slate_handoff_records_explicit_missing_forecast_skip() -> None:
    root = (Path(".runtime") / "nfl-current-shadow-tests" / uuid.uuid4().hex).resolve()
    try:
        exchange, _, expected = _isolated_slate_exchange(root)
        missing = {
            "eventId": "2026_01_MISSING",
            "homeTeamId": "MISSING_HOME",
            "awayTeamId": "MISSING_AWAY",
            "scheduledStartUtc": "2026-09-10T03:00:00Z",
        }
        record = C.build_current_slate_handoff(
            SLATE,
            exchange_root=exchange,
            expected_events=[expected, missing],
        )
        assert record["eventCount"] == 2
        assert record["forecastCount"] == 1
        assert record["skipCount"] == 1
        assert record["importAllowed"] is False
        assert record["skips"] == [{**missing, "reason": "NO_VERIFIED_CURRENT_FORECAST"}]
    finally:
        if root.exists():
            shutil.rmtree(root)
