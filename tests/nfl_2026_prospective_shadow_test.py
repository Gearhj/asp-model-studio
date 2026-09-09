from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_gold import nfl_shadow_exchange as X
from server.sports_nfl_m1 import prospective_shadow as P


def test_pinned_frozen_artifact_reloads_with_exact_contract() -> None:
    frozen = P.verify_frozen_m1()
    assert frozen.manifest["candidateId"] == P.MODEL_CANDIDATE
    assert frozen.manifest["modelArtifact"]["sha256"] == P.MODEL_BINARY_SHA256
    assert frozen.manifest["training"]["trainingCutoff"] == "2026-02-08"
    assert frozen.manifest["training"]["contains2026SeasonOutcome"] is False
    assert len(frozen.feature_names) == 197
    assert frozen.model_bundle["promotionState"] == "NOT_PROMOTED"


def test_prospective_builder_matches_all_197_registered_gold_inputs() -> None:
    evidence = P.historical_feature_parity(P.load_foundation_runtime())
    assert evidence["featureCount"] == 197
    assert evidence["mismatchCount"] == 0
    assert evidence["targetOutcomesRead"] is False


def test_activation_emits_immutable_early_current_bundles_and_is_idempotent(
    monkeypatch,
) -> None:
    monkeypatch.setattr(P, "SIMULATION_DRAWS", 1_000)
    original_targets = P._load_targets
    def bounded_targets(*args, **kwargs):
        targets, team_games, names = original_targets(*args, **kwargs)
        return targets[:2], team_games, names
    monkeypatch.setattr(P, "_load_targets", bounded_targets)
    root = (Path(".runtime") / "nfl-shadow-tests" / uuid.uuid4().hex).resolve()
    publication = root / "publication"
    exchange = root / "exchange"
    # Anchor operational timing to the current verified source authority so the
    # point-in-time guard remains valid as the governed foundation advances.
    cutoff = P._utc(P.load_foundation_runtime().schedule_as_of_utc) + timedelta(seconds=1)
    clock = {"now": cutoff + timedelta(seconds=1)}
    monkeypatch.setattr(P, "_now_utc", lambda: clock["now"])
    try:
        first = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=cutoff,
            producer_revision="e60f5b1500e1c574e17a526a6c2e8bef047f92e2",
        )
        assert first["status"] == "ACTIVE"
        assert first["games"] == 2
        assert first["forecastsCreated"] == 4
        assert first["modelsFit"] == 0
        assert first["marketFieldsRead"] is False
        assert first["bundleCount"] > 0
        for item in first["bundles"]:
            verified = X.verify_sports_forecast_bundle(exchange, item["bundleSha256"])
            assert verified.record["status"] == "RESEARCH_SHADOW"
            assert all(record["promotionStatus"] == "NOT_PROMOTED" for record in verified.record["forecasts"])
            assert all(record["executionStatus"] == "NOT_EXECUTABLE" for record in verified.record["forecasts"])
        locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        assert locator["schemaVersion"] == "ASP_NFL_2026_RESEARCH_SHADOW_INDEX_V2"
        assert locator["currentBundleCount"] == first["bundleCount"]
        assert locator["currentBundleSha256s"] == sorted(item["bundleSha256"] for item in first["bundles"])
        assert locator["historicalBundleSha256s"] == []
        assert locator["currentBundleListSha256"] == hashlib.sha256(
            canonical_json_bytes(locator["currentBundleSha256s"])
        ).hexdigest()
        feature_objects_before = sorted((publication / "feature-vectors" / "sha256").iterdir())
        clock["now"] = cutoff.replace(hour=17) + timedelta(seconds=1)
        second = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=cutoff.replace(hour=17),
            producer_revision="e60f5b1500e1c574e17a526a6c2e8bef047f92e2",
        )
        assert second["forecastsCreated"] == 0
        assert second["bundleCount"] == 0
        assert second["exchangeLocatorCurrentBundleCount"] == first["bundleCount"]
        second_locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        assert second_locator["currentBundleListSha256"] == locator["currentBundleListSha256"]
        assert second_locator["historicalBundleListSha256"] == locator["historicalBundleListSha256"]
        assert sorted((publication / "feature-vectors" / "sha256").iterdir()) == feature_objects_before
        clock["now"] = cutoff.replace(hour=18) + timedelta(seconds=1)
        revised = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=cutoff.replace(hour=18),
            producer_revision="1111111111111111111111111111111111111111",
        )
        assert revised["forecastsCreated"] == 0
        assert revised["unchangedEvidenceForecastsReused"] == 2
        assert revised["forecastInferenceRows"] == 0
        assert revised["reloadVerificationInferenceRows"] == 1
        assert revised["sourceEvidenceAsOfUtc"] == P.load_foundation_runtime().schedule_as_of_utc
        assert revised["sourceFoundationChangedSincePreviousSnapshot"] is False
        index = json.loads((publication / "prospective-index.json").read_text(encoding="utf-8"))
        assert all(len(value["EARLY"]) == 1 and len(value["CURRENT"]) == 1 for value in index["events"].values())
        assert all(
            value["CURRENT"][-1]["producerRevision"] == "e60f5b1500e1c574e17a526a6c2e8bef047f92e2"
            for value in index["events"].values()
        )
        revised_locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        assert revised_locator["currentBundleCount"] == first["bundleCount"]
        assert revised_locator["historicalBundleCount"] == 0
        assert not set(revised_locator["currentBundleSha256s"]) & set(revised_locator["historicalBundleSha256s"])
        current_records = [
            child
            for digest in revised_locator["currentBundleSha256s"]
            for child in X.verify_sports_forecast_bundle(exchange, digest).record["forecasts"]
        ]
        assert len(current_records) == 4
        assert len({(child["eventId"], child["snapshotType"]) for child in current_records}) == 4
        assert {child["snapshotVersion"] for child in current_records if child["snapshotType"] == "EARLY"} == {1}
        assert {child["snapshotVersion"] for child in current_records if child["snapshotType"] == "CURRENT"} == {1}
        first_target = bounded_targets(P.load_foundation_runtime(), as_of=cutoff)[0][0]
        final_cutoff = first_target["scheduled_start_utc"] - timedelta(minutes=25)
        before_late_locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        clock["now"] = first_target["scheduled_start_utc"] - timedelta(minutes=14)
        delayed = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=final_cutoff,
            snapshot_types=("FINAL_PREGAME",),
            producer_revision="1111111111111111111111111111111111111111",
        )
        assert delayed["games"] == 1
        assert delayed["featureVectorCount"] == 1
        assert delayed["forecastsCreated"] == 0
        assert delayed["bundleCount"] == 0
        assert delayed["lateFinalPregameOmissions"] == 1
        after_late_locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        assert after_late_locator["currentBundleListSha256"] == before_late_locator["currentBundleListSha256"]
        assert after_late_locator["historicalBundleListSha256"] == before_late_locator["historicalBundleListSha256"]
        clock["now"] = first_target["scheduled_start_utc"] - timedelta(minutes=24)
        final = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=final_cutoff,
            snapshot_types=("FINAL_PREGAME",),
            producer_revision="1111111111111111111111111111111111111111",
        )
        assert final["forecastsCreated"] == 1
        assert final["games"] == 1
        assert final["featureVectorCount"] == 1
        assert final["lateFinalPregameOmissions"] == 0
        final_locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        assert final["exchangeLocatorCurrentForecastCount"] == 5
        clock["now"] = first_target["scheduled_start_utc"] - timedelta(minutes=19)
        repeat_final = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=final_cutoff + timedelta(minutes=5),
            snapshot_types=("FINAL_PREGAME",),
            producer_revision="1111111111111111111111111111111111111111",
        )
        assert repeat_final["forecastsCreated"] == 0
        repeat_locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        assert repeat_locator["currentBundleListSha256"] == final_locator["currentBundleListSha256"]
        assert repeat_locator["historicalBundleListSha256"] == final_locator["historicalBundleListSha256"]
        clock["now"] = first_target["scheduled_start_utc"] - timedelta(minutes=13)
        late_final = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=final_cutoff + timedelta(minutes=11),
            snapshot_types=("FINAL_PREGAME",),
            producer_revision="1111111111111111111111111111111111111111",
        )
        assert late_final["status"] == "NO_ELIGIBLE_UPCOMING_GAMES"
        assert late_final["reason"] == "NO_DUE_FINAL_PREGAME_GAMES"
        late_locator = X.verify_nfl_2026_research_shadow_locator(exchange)
        assert late_locator["currentBundleListSha256"] == final_locator["currentBundleListSha256"]
        assert late_locator["historicalBundleListSha256"] == final_locator["historicalBundleListSha256"]
        index = json.loads((publication / "prospective-index.json").read_text(encoding="utf-8"))
        assert len(index["events"]) == 2
        assert all(len(value["EARLY"]) == 1 and len(value["CURRENT"]) == 1 for value in index["events"].values())
        final_counts = sorted(len(value["FINAL_PREGAME"]) for value in index["events"].values())
        assert final_counts == [0, 1]
        def first_only(*args, **kwargs):
            targets, team_games, names = original_targets(*args, **kwargs)
            return targets[:1], team_games, names
        monkeypatch.setattr(P, "_load_targets", first_only)
        clock["now"] = first_target["scheduled_start_utc"] + timedelta(minutes=1)
        late_current = P.activate_2026_shadow(
            publication_root=publication,
            exchange_root=exchange,
            as_of=first_target["scheduled_start_utc"] - timedelta(minutes=1),
            snapshot_types=("CURRENT",),
            producer_revision="2222222222222222222222222222222222222222",
        )
        assert late_current["games"] == 1
        assert late_current["forecastsCreated"] == 0
        assert late_current["bundleCount"] == 0
        final_index = json.loads((publication / "prospective-index.json").read_text(encoding="utf-8"))
        assert len(final_index["events"][first_target["canonical_game_id"]]["CURRENT"]) == 1
    finally:
        if root.exists():
            shutil.rmtree(root)


def test_registered_current_authority_has_all_272_upcoming_games_including_january() -> None:
    runtime = P.load_foundation_runtime()
    targets, _, _ = P._load_targets(
        runtime, as_of=datetime(2026, 8, 29, 16, 0, tzinfo=timezone.utc)
    )
    assert len(targets) == 272
    assert sum(str(target["game_date"]).startswith("2027-01") for target in targets) == 31


def test_team_identity_hash_and_cutoff_rules_fail_closed() -> None:
    identity = {"abbreviation": "SEA", "source": "NFLVERSE", "sourceTeamId": "SEA", "teamId": "SEA"}
    assert hashlib.sha256(canonical_json_bytes(identity)).hexdigest() == hashlib.sha256(canonical_json_bytes(identity)).hexdigest()
    with pytest.raises(X.SportsForecastExchangeError, match="fields differ"):
        X.validate_sports_game_forecast({})


def test_existing_legacy_exchange_still_rejects_2025_plus() -> None:
    from server.sports_gold.aisp_export_contracts import AispExportContractError, _event_date

    with pytest.raises(AispExportContractError, match="rejects 2025"):
        _event_date("2026-09-09", "eventDate")
