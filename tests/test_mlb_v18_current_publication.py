"""Unpublished incomplete-input fixtures only: no model or simulation execution."""
from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from server.sports_current_statcast import mlb_v18_current_publication as publication


def test_incomplete_raw246_skip_reuses_evidence_without_starting_engine(tmp_path, monkeypatch):
    contract = publication.load_contract()  # Accepted schema metadata, not training rows.
    columns = contract["rawFeatureColumns"]
    assert len(columns) == 246
    attempts = []

    def forbidden_engine(*args, **kwargs):
        attempts.append("engine")
        raise AssertionError("Incomplete evidence must never load or execute a model")

    monkeypatch.setattr(publication, "CurrentV18Engine", forbidden_engine)
    game_id = "SYNTHETIC_INCOMPLETE_SNAPSHOT_ONLY_NOT_A_FORECAST"
    snapshot = {
        "capturedAt": "2099-04-01T10:00:00+00:00",
        "game": {"game_id": game_id, "starts_at": "2099-04-01T18:00:00+00:00", "status": "SCHEDULED"},
        "sides": [],
        "sourceEvidence": {
            "sourceIdentity": "SYNTHETIC_TEST_ONLY",
            "observedAt": "2099-04-01T09:00:00+00:00",
            "ingestedAt": "2099-04-01T09:01:00+00:00",
            "availableAsOf": "2099-04-01T09:01:00+00:00",
        },
    }
    composition = {
        "rows": [{column: None for column in columns}],
        "snapshotCapturedAt": snapshot["capturedAt"],
        "canSimulate": False,
        "coverage": {"supportedFields": 0, "requiredFields": 246},
        "blockers": [{"reason": "SYNTHETIC_REQUIRED_SOURCE_EVIDENCE_MISSING"}],
    }

    def publish(source, composed):
        return publication.publish_slate(
            {"capturedAt": source["capturedAt"], "snapshots": [source]},
            [composed], output_root=tmp_path,
        )

    first = publish(snapshot, composition)
    first_game = first["games"][0]
    assert first_game["status"] == "SKIPPED"
    assert first_game["unchangedEvidenceReused"] is False
    record = first_game["featureSnapshot"]
    original_bytes = Path(record["path"]).read_bytes()
    assert hashlib.sha256(original_bytes).hexdigest() == record["sha256"]
    assert len(original_bytes) == record["bytes"]
    saved = json.loads(original_bytes)
    assert saved["rawFeatureOrder"] == columns
    assert set(saved["composition"]["rows"][0]) == set(columns)
    assert all(value is None for value in saved["composition"]["rows"][0].values())

    polled, polled_composition = deepcopy(snapshot), deepcopy(composition)
    polled["capturedAt"] = "2099-04-01T10:30:00+00:00"
    polled["queryReceipts"] = [{"generatedAt": polled["capturedAt"]}]
    polled_composition["snapshotCapturedAt"] = polled["capturedAt"]
    second = publish(polled, polled_composition)
    assert second["games"][0]["unchangedEvidenceReused"] is True
    assert second["games"][0]["featureSnapshot"] == record
    assert Path(record["path"]).read_bytes() == original_bytes
    assert saved["capturedAt"] == snapshot["capturedAt"]
    for report in (first, second):
        assert report["newForecastCount"] == report["validForecastCount"] == report["failedGameCount"] == 0
        assert report["skippedGameCount"] == 1
        assert report["handoff"] is None
        assert report["fits"] == report["aispWrites"] == report["finalOotPayloadReads"] == 0

    # Genuine source clocks remain material, unlike poll clocks; retain both objects.
    refreshed = deepcopy(polled)
    refreshed["sourceEvidence"]["observedAt"] = "2099-04-01T09:15:00+00:00"
    refreshed["sourceEvidence"]["availableAsOf"] = "2099-04-01T09:16:00+00:00"
    refreshed["sourceEvidence"]["ingestedAt"] = "2099-04-01T09:16:00+00:00"
    third = publication.publish_composed_game(refreshed, polled_composition, output_root=tmp_path)
    assert third["status"] == "SKIPPED"
    assert third["featureSnapshot"]["sha256"] != record["sha256"]
    assert Path(record["path"]).read_bytes() == original_bytes

    no_explicit_blocker = {**polled_composition, "blockers": []}
    unattested = publication.publish_composed_game(refreshed, no_explicit_blocker, output_root=tmp_path)
    assert unattested["status"] == "SKIPPED"
    assert unattested["blockers"] == [{"reason": "COMPLETE_SIMULATION_MATCHUP_EVIDENCE_NOT_ATTESTED"}]

    missing_column = deepcopy(composition)
    missing_column["rows"][0].pop(columns[-1])
    with pytest.raises(ValueError, match="CURRENT_SNAPSHOT_MUST_RETAIN_ALL_246_RAW_FIELDS"):
        publication.publish_composed_game(snapshot, missing_column, output_root=tmp_path)
    assert attempts == []
    assert not (tmp_path / "numerical-keys").exists()


def test_unchanged_handoff_does_not_create_another_publication_version(tmp_path, monkeypatch):
    # Packaging-only synthetic references: no real game forecast or model run.
    rows = [{"gameId": "SYNTHETIC_HANDOFF_ONLY", "objectSha256": "1"*64,
             "relativePath": "synthetic-not-importable", "forecastFile": "forecast.json",
             "manifestFile": "manifest.json", "capturedAt": "2099-04-01T10:00:00Z",
             "scheduledStart": "2099-04-01T18:00:00Z"}]
    first = publication.current_handoff(tmp_path, date(2099, 4, 1), rows)
    def forbidden_writer(*args, **kwargs):
        raise AssertionError("Unchanged forecast state must reuse its original handoff")
    monkeypatch.setattr(publication.daily, "_write_handoff", forbidden_writer)
    second = publication.current_handoff(tmp_path, date(2099, 4, 1), deepcopy(rows))
    assert first == second
    assert publication.reference(first["path"])["sha256"] == first["sha256"]
    assert len(list((tmp_path/"handoffs/sha256").glob("*/aisp-handoff.json"))) == 1


def _synthetic_complete_inputs(game_id):
    """Packaging and identity fixture only; no provider/model is instantiated."""
    clock = "2099-04-01T09:00:00+00:00"
    snapshot = {"capturedAt": "2099-04-01T10:00:00+00:00", "contentSha256": "0"*64,
                "game": {"game_id": game_id, "starts_at": "2099-04-01T18:00:00+00:00",
                         "scheduled_innings": 9, "status": "SCHEDULED"}, "sides": []}
    for side in ("AWAY", "HOME"):
        authority = {"observedAt": clock, "availableAsOf": clock, "ingestedAt": clock,
                     "source": "SYNTHETIC_PACKAGING_FIXTURE"}
        snapshot["sides"].append({"side": side, "team": {"uuid": side},
            "starter": {**authority, "mlbamId": side+"-pitcher"},
            "lineupAuthority": {**authority, "status": "CONFIRMED"},
            "lineup": [{"mlbam": side+str(slot), "batting_order": slot} for slot in range(1, 10)]})
    columns = publication.load_contract()["rawFeatureColumns"]
    rows = []
    for side in ("AWAY", "HOME"):
        for slot in range(1, 10):
            row = {column: 0.0 for column in columns}
            row.update(canonicalGameId=game_id, canonicalPaId=f"SYNTHETIC:{side}:{slot}",
                       game_date="2099-04-01", batterCanonicalPlayerId=f"{side}:{slot}",
                       pitcherCanonicalPlayerId="HOME:P" if side == "AWAY" else "AWAY:P")
            rows.append(row)
    return snapshot, {"rows": rows, "providerInputs": {"awayBatters": rows[:9], "homeBatters": rows[9:],
        "awayStarter": rows[9], "homeStarter": rows[0], "awayBullpen": [rows[9]], "homeBullpen": [rows[0]]},
        "canSimulate": True, "blockers": [], "coverage": {"rawInputCount": 246, "worstRawSupportedCount": 246},
        "sourceCutoff": snapshot["capturedAt"], "venueTimezone": "America/New_York"}


class _SyntheticClock(datetime):
    current = datetime(2099, 4, 1, 11, tzinfo=timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.current


class _SyntheticPackagingEngine:
    def __init__(self):
        self.calls = []

    def forecast(self, snapshot, composition, feature_snapshot):
        self.calls.append(snapshot["game"]["game_id"])
        forecast = {"gameId": snapshot["game"]["game_id"], "capturedAt": snapshot["capturedAt"],
            "forecastCreatedAt": _SyntheticClock.current.isoformat(), "scheduledStart": snapshot["game"]["starts_at"],
            "sourceCutoff": snapshot["capturedAt"], "parentAuthority": {
                "bundleSha256": publication.daily.PARENT_BUNDLE_SHA256,
                "paModelSha256": publication.daily.PA_MODEL_SHA256,
                "transitionModelSha256": publication.daily.TRANSITION_MODEL_SHA256},
            "simulation": {"count": 5000, "seed": publication.daily.MASTER_SEED, "illegalStateCount": 0,
                           "nonterminationCount": 0, "deterministicReplay": True},
            "probabilities": {"homeWin": 0.5, "awayWin": 0.5},
            "expectations": {"homeRuns": 4, "awayRuns": 4, "totalRuns": 8, "homeMinusAwayRuns": 0},
            "distributions": {}, **publication.RESEARCH}
        return {"forecast": forecast, "evidence": snapshot,
            "executionInputs": {"rawTemplates": composition["rows"], "providerInputs": composition["providerInputs"],
                "featureSnapshot": feature_snapshot, "modelIdentity": {
                    "treatmentManifestSha256": publication.daily.TREATMENT_MANIFEST_SHA256}},
            "representativePath": {"gameId": forecast["gameId"], "events": [{"syntheticPackagingOnly": True}]}}


def test_numerical_identity_reuses_legacy_and_only_versions_changed_game(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "datetime", _SyntheticClock)
    _SyntheticClock.current = datetime(2099, 4, 1, 11, tzinfo=timezone.utc)
    engine = _SyntheticPackagingEngine()
    source, composed = _synthetic_complete_inputs("SYNTHETIC_GAME_A")
    other_source, other_composed = _synthetic_complete_inputs("SYNTHETIC_GAME_B")
    # Seed exactly the old index format, retaining its original immutable object.
    feature, _ = publication.write_object(tmp_path, "feature-snapshot.json", {"composition": composed})
    payload = engine.forecast(source, composed, feature)
    old = publication.daily._publish_game(tmp_path, source, payload)
    legacy_key = "e"*64
    publication.daily.write_json(tmp_path / "numerical-keys" / f"{legacy_key}.json", old)
    original_bytes = (tmp_path / old["relativePath"] / "forecast.json").read_bytes()
    second = publication.publish_composed_game(other_source, other_composed, output_root=tmp_path, engine=engine)
    polled, polled_composed = deepcopy(source), deepcopy(composed)
    polled["producerRevision"] = "different-code-and-location"
    polled["capturedAt"] = "2099-04-01T10:30:00+00:00"
    polled_composed["sourceCutoff"] = polled["capturedAt"]
    for row in polled_composed["providerInputs"]["awayBatters"]:
        row["producerRevision"] = "v-next"
        row["artifactPath"] = "C:/new-deployment/same-inputs"
        row["retrievedAt"] = polled["capturedAt"]
        row["pitcher_whip"] = 0  # Numerically identical to 0.0.
    # raw rows remain the exact registered schema even if provider rows carry metadata.
    polled_composed["rows"] = deepcopy(composed["rows"])
    reused = publication.publish_composed_game(polled, polled_composed, output_root=tmp_path, engine=engine)
    assert reused["status"] == "UNCHANGED_NUMERICAL_FORECAST_REUSED"
    assert reused["objectSha256"] == old["objectSha256"]
    assert reused["publicationKey"] == old["publicationKey"]
    assert reused["forecastCreatedAt"] == payload["forecast"]["forecastCreatedAt"]
    assert (tmp_path / old["relativePath"] / "forecast.json").read_bytes() == original_bytes
    assert (tmp_path / "numerical-keys" / f"{legacy_key}.json").exists()
    changed = deepcopy(polled_composed)
    changed["providerInputs"]["homeBullpen"][0]["pitcher_whip"] = 1.25
    version = publication.publish_composed_game(polled, changed, output_root=tmp_path, engine=engine)
    assert version["objectSha256"] != old["objectSha256"]
    # Simulate a process stopping after object commit but before index commit.
    (tmp_path / "numerical-keys-v2" / f"{second['numericalInputSha256']}.json").unlink()
    unchanged = publication.publish_composed_game(other_source, other_composed, output_root=tmp_path, engine=engine)
    assert unchanged["objectSha256"] == second["objectSha256"]
    assert engine.calls == ["SYNTHETIC_GAME_A", "SYNTHETIC_GAME_B", "SYNTHETIC_GAME_A"]
    shortened = deepcopy(other_source)
    shortened["game"]["scheduled_innings"] = 7
    assert publication.numerical_input_identity(shortened, other_composed) != unchanged["numericalInputSha256"]


def test_reuse_validates_source_clocks_and_new_forecasts_obey_actual_cutoff(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "datetime", _SyntheticClock)
    _SyntheticClock.current = datetime(2099, 4, 1, 11, tzinfo=timezone.utc)
    source, composed = _synthetic_complete_inputs("SYNTHETIC_CUTOFF")
    engine = _SyntheticPackagingEngine()
    first = publication.publish_composed_game(source, composed, output_root=tmp_path, engine=engine)
    invalid = deepcopy(source)
    invalid["sides"][0]["starter"]["ingestedAt"] = "2099-04-01T10:01:00+00:00"
    with pytest.raises(ValueError, match="CURRENT_PARTICIPANT_INGESTED_AFTER_CUTOFF"):
        publication.publish_composed_game(invalid, composed, output_root=tmp_path, engine=engine)
    invalid_composition = deepcopy(composed)
    invalid_composition["sourceEvidence"] = {"availableAsOf": "2099-04-01T10:01:00+00:00"}
    with pytest.raises(ValueError, match="CURRENT_COMPOSITION_SOURCE_CLOCK_INVALID"):
        publication.publish_composed_game(source, invalid_composition, output_root=tmp_path, engine=engine)
    invalid_composition = deepcopy(composed)
    invalid_composition["fieldReports"] = [{"battingSide": "AWAY", "battingOrder": 1,
        "batterMlbamId": "UNEXPECTED_PLAYER", "pitcherMlbamId": "HOME-pitcher"}]
    with pytest.raises(ValueError, match="CURRENT_COMPOSITION_PARTICIPANT_BINDING_MISMATCH"):
        publication.publish_composed_game(source, invalid_composition, output_root=tmp_path, engine=engine)
    # The operational runner retains cutoff detail as a mapping, with a distinct
    # scalar event cutoff; eligible original evidence remains reusable.
    with_details = deepcopy(composed)
    with_details["sourceCutoff"] = {"snapshotCapturedAt": source["capturedAt"],
        "evidenceAvailableAt": "2099-04-01T09:00:00+00:00", "playerHistoryCompleteThrough": "2099-03-31"}
    assert publication.publish_composed_game(source, with_details, output_root=tmp_path, engine=engine)["objectSha256"] == first["objectSha256"]
    changed = deepcopy(composed)
    changed["rows"][0]["pitcher_whip"] = 2.0
    _SyntheticClock.current = datetime(2099, 4, 1, 17, 56, tzinfo=timezone.utc)
    with pytest.raises(publication.daily.DailySlateError, match="five minutes"):
        publication.publish_composed_game(source, changed, output_root=tmp_path, engine=engine)
    _SyntheticClock.current = datetime(2099, 4, 1, 18, tzinfo=timezone.utc)
    # Reading a legitimately pregame original is allowed; new inference is not.
    reuse = publication.publish_composed_game(source, composed, output_root=tmp_path, engine=engine)
    assert reuse["forecastCreatedAt"] == first["forecastCreatedAt"]
    with pytest.raises(publication.daily.DailySlateError, match="first pitch"):
        publication.publish_composed_game(source, changed, output_root=tmp_path, engine=engine)
    assert len(engine.calls) == 1


def test_complete_handoff_binds_original_clocks_children_and_skip_accounting(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "datetime", _SyntheticClock)
    _SyntheticClock.current = datetime(2099, 4, 1, 11, tzinfo=timezone.utc)
    source, composed = _synthetic_complete_inputs("SYNTHETIC_HANDOFF_GAME")
    engine = _SyntheticPackagingEngine()
    monkeypatch.setattr(publication, "CurrentV18Engine", lambda: engine)
    collection = {"capturedAt": source["capturedAt"], "snapshots": [source]}
    first = publication.publish_slate(collection, [composed], output_root=tmp_path)
    assert first["failedGameCount"] == 0
    handoff = json.loads(Path(first["handoff"]["path"]).read_text(encoding="utf-8"))
    row = handoff["forecasts"][0]
    assert row["importIdentity"] == first["games"][0]["objectSha256"]
    assert row["forecastCreatedAt"] == "2099-04-01T11:00:00+00:00"
    assert row["sourceRetrievalTimestamps"]["snapshotRetrievedAt"] == source["capturedAt"]
    assert row["evidenceCutoff"] == source["capturedAt"]
    assert len(row["childBindings"]) == 4
    assert row["status"] == "RESEARCH_SHADOW"
    assert handoff["gameAccounting"] == [{"gameId": source["game"]["game_id"], "status": "PUBLISHED",
                                          "objectSha256": row["objectSha256"]}]
    body = {key: value for key, value in handoff.items() if key not in {"handoffId", "handoffSha256"}}
    assert publication.daily.sha_json(body) == first["handoff"]["logicalHandoffSha256"]
    def forbidden_engine():
        raise AssertionError("Unchanged run must not load the model")
    monkeypatch.setattr(publication, "CurrentV18Engine", forbidden_engine)
    second = publication.publish_slate(collection, [composed], output_root=tmp_path)
    assert second["newForecastCount"] == 0
    assert second["handoff"] == first["handoff"]
    forecasts = publication.daily.collect_slate_forecasts(tmp_path, date(2099, 4, 1))
    skipped = {"gameId": "SYNTHETIC_SKIPPED", "status": "SKIPPED", "blockers": [{"reason": "NO_LINEUP"}]}
    with_skip = publication.current_handoff(tmp_path, date(2099, 4, 1), forecasts, games=first["games"]+[skipped])
    assert with_skip["sha256"] != first["handoff"]["sha256"]
    assert json.loads(Path(with_skip["path"]).read_text())["gameAccounting"][1]["blockers"] == [{"reason": "NO_LINEUP"}]


def test_deployment_junction_can_reuse_canonical_handoff_and_write_receipt(tmp_path):
    import os
    from scripts.build_mlb_v18_deployment import ensure_junction
    if os.name != "nt":
        pytest.skip("Windows deployment junction regression")
    target, alias = tmp_path / "output", tmp_path / "shared-output"
    target.mkdir()
    ensure_junction(alias, target)
    games = [{"gameId": "SYNTHETIC_PENDING", "status": "SKIPPED", "reason": "NO_LINEUP"}]
    handoff = publication.current_handoff(target, date(2099, 4, 1), [], games=games)
    assert publication.current_handoff(alias, date(2099, 4, 1), [], games=games) == handoff
    receipt = publication.current_import_receipt(alias, date(2099, 4, 1), [], games, handoff)
    assert Path(receipt["path"]).is_relative_to(target)


def test_exact_player_window_cache_reuses_original_bits_and_invalidates_on_source_proof_change(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "datetime", _SyntheticClock)
    _SyntheticClock.current = datetime(2099, 4, 1, 11, tzinfo=timezone.utc)
    source, composed = _synthetic_complete_inputs("SYNTHETIC_EXACT_PLAYER_WINDOW")
    staff = deepcopy(composed["rows"][0])
    staff.update(pitcherCanonicalPlayerId="SYNTHETIC_STAFF", canonicalPaId="SYNTHETIC_STAFF_PA",
                 pitcher_prior_bf_count=500, pitcher_last250_bf_count=250,
                 pitcher_last250_fastball_velocity_sum=100.1)
    composed["providerInputs"]["homeBullpen"] = [staff]
    history = {"observedAt": "2099-04-01T09:00:00+00:00", "availableAsOf": "2099-04-01T09:00:00+00:00",
        "ingestedAt": "2099-04-01T09:00:00+00:00", "completeThrough": "2099-03-31",
        "contiguousRequestedDatesComplete": True, "missingDates": [],
        "windowSelectionProof": {"identity": {key: "a"*64 for key in (
            "historySourceIdentity", "baseExposureIdentity", "sourceImplementationSha256", "exposureImplementationSha256")},
            "rows": [{"playerId": "SYNTHETIC_STAFF", "role": "pitcher", "acceptedCumulativeExposure": 500,
                "window": 250, "selectedPaCount": 250, "orderedPaIdsSha256": "b"*64,
                "selection": "EXACT_ACCEPTED_GOLD_ORDER_LAST_N_FROM_FULL_ACCEPTED_2019_TO_CURRENT_SOURCE_UNIVERSE"}]}}
    composed["sourceEvidence"] = {"history": history, "player": {
        "calculation": "ACCEPTED_GOLD_PRIOR_WINDOW_FEATURES_UNCHANGED", "rows": [
        {"canonicalPaId": "SYNTHETIC_STAFF_PA", "playerId": "SYNTHETIC_STAFF", "role": "pitcher",
         "windowSupported": True, "cumulativeExposureSupported": True}]}}
    feature, _ = publication.write_object(tmp_path, "feature-snapshot.json", {**source, "composition": composed})
    engine = _SyntheticPackagingEngine()
    original = publication.daily._publish_game(tmp_path, source, engine.forecast(source, composed, feature))
    recomputed = deepcopy(composed)
    recomputed["providerInputs"]["homeBullpen"][0]["pitcher_last250_fastball_velocity_sum"] = 100.10000000000001
    recomputed["providerInputs"]["homeBullpen"][0]["batter_avg"] = 0.321  # Annual values remain current.
    repaired = publication.reuse_player_window_vectors(source, recomputed, output_root=tmp_path)
    assert repaired["providerInputs"]["homeBullpen"][0]["pitcher_last250_fastball_velocity_sum"] == 100.1
    assert repaired["providerInputs"]["homeBullpen"][0]["batter_avg"] == 0.321
    binding = repaired["playerWindowVectorCache"][0]
    assert binding["originalPublicationAnchor"]["originalForecastObjectSha256"] == original["objectSha256"]
    assert binding["roundingApplied"] is False
    assert publication.reuse_player_window_vectors(source, recomputed, output_root=tmp_path) == repaired
    producer_only = deepcopy(recomputed)
    producer_only["sourceEvidence"]["history"]["windowSelectionProof"]["identity"]["sourceImplementationSha256"] = "d"*64
    again = publication.reuse_player_window_vectors(source, producer_only, output_root=tmp_path)
    assert again["providerInputs"]["homeBullpen"][0]["pitcher_last250_fastball_velocity_sum"] == 100.1
    assert again["playerWindowVectorCache"] == repaired["playerWindowVectorCache"]
    changed_source = deepcopy(recomputed)
    changed_source["sourceEvidence"]["history"]["windowSelectionProof"]["rows"][0]["orderedPaIdsSha256"] = "c"*64
    changed_source.update(canSimulate=False, blockers=[{"reason": "SYNTHETIC_OTHER_DEPENDENCY_MISSING"}])
    skipped = publication.publish_composed_game(source, changed_source, output_root=tmp_path, engine=engine)
    assert skipped["status"] == "SKIPPED"
    retained = json.loads(Path(skipped["featureSnapshot"]["path"]).read_text())["composition"]
    assert retained["providerInputs"]["homeBullpen"][0]["pitcher_last250_fastball_velocity_sum"] == 100.10000000000001
    assert retained["playerWindowVectorCache"][0]["exactSourceWindowIdentity"] != binding["exactSourceWindowIdentity"]
    assert retained["playerWindowVectorCache"][0]["vectorSnapshot"]
    assert len(engine.calls) == 1
