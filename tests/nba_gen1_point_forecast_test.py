"""Synthetic mechanics only; these fixtures are never real NBA forecasts."""
from copy import deepcopy
from pathlib import Path
import json

import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_nba_gen1.authority import reference
from server.sports_nba_gen1.recent_features import FEATURE_COLUMNS, build_recent_features
from server.sports_nba_gen1.point_forecast import build_target_features, build_point_forecast, PointForecastUnavailable
from server.sports_nba_gen1.rest_support import fit_rest_model, feature_contract
from server.sports_nba_gen1.models import fit_model


def game(gid, day, *, home="A", away="B", hs=110, aws=100, season=2024, neutral=False):
    return dict(game_id=gid, game_date=day, season_end=season, home_team_id=home, away_team_id=away,
                home_team_code=home, away_team_code=away, home_score=hs, away_score=aws,
                neutral_site=neutral, orientation="PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM" if neutral else "SOURCE_HOME_AWAY")


def target(row):
    return {key: row[key] for key in ("game_id", "game_date", "season_end", "home_team_id", "away_team_id", "home_team_code", "away_team_code", "neutral_site")} | {
        "source_game_id": row["game_id"], "season_type": "REGULAR", "status": "SCHEDULED", "source_revision": "test-r1",
        "scheduled_tipoff_utc": row["game_date"] + "T22:00:00Z"}


@pytest.mark.parametrize("new_season", [False, True])
def test_all_78_features_match_frozen_builder_without_target_outcomes(new_season):
    history = [game(f"old{i}", f"2023-04-{i + 1:02}", hs=100+i, aws=90, season=2023, neutral=i == 0) for i in range(5)]
    history += [game(f"g{i}", f"2023-10-{i + 1:02}", hs=101+i, aws=90+i%3) for i in range(22)]
    wanted = game("wanted", "2024-10-01" if new_season else "2023-10-25", season=2025 if new_season else 2024)
    source = pd.DataFrame(history + [wanted])
    contexts = [{"game_id": "cup", "game_date": "2023-10-24", "season_end": 2024,
                 "team_ids": ["A", "C"], "classification": "NBA_CUP_FINAL_DATE_ONLY"}]
    original, _ = build_recent_features(source, contexts)
    reproduced, audit = build_target_features(pd.DataFrame(history), target(wanted), contexts)
    expected = original[original.game_id.eq("wanted")].iloc[0][list(FEATURE_COLUMNS)].to_numpy(float)
    actual = reproduced.iloc[0][list(FEATURE_COLUMNS)].to_numpy(float)
    np.testing.assert_array_equal(actual, expected)
    assert "home_score" not in reproduced and "away_score" not in reproduced
    assert not audit["dummyTargetFinalsUsed"]


def test_same_day_target_and_future_labels_never_enter_snapshot():
    old = game("old", "2023-10-01")
    wanted = game("target", "2023-10-03")
    leaked = game("target", "2023-10-03", hs="DO_NOT_READ", aws="DO_NOT_READ")
    same = game("same", "2023-10-03", home="A", away="C", hs="DO_NOT_READ", aws="DO_NOT_READ")
    later = game("future", "2023-10-05", hs="DO_NOT_READ", aws="DO_NOT_READ")
    first, _ = build_target_features(pd.DataFrame([old]), target(wanted))
    second, audit = build_target_features(pd.DataFrame([old, leaked, same, later]), target(wanted))
    pd.testing.assert_frame_equal(first, second)
    assert audit["excludedTargetSameDateOrLaterRows"] == 3


@pytest.mark.parametrize("changed", [{"home_score": 110}, {"neutral_site": True}, {"status": "FINAL"}, {"scheduled_tipoff_utc": "2023-10-03T00:30:00Z"}])
def test_invalid_target_is_not_repaired(changed):
    wanted = target(game("target", "2023-10-03"))
    wanted.update(changed)
    with pytest.raises(PointForecastUnavailable):
        build_target_features(pd.DataFrame([game("old", "2023-10-01")]), wanted)


def write_json(root, name, value):
    path = root / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return reference(path)


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    # Test-only synthetic artifacts. Nothing from this fixture is exported.
    games = pd.DataFrame([game(f"g{i}", f"2023-10-{i + 1:02}", hs=100+i, aws=90+i%3) for i in range(12)])
    features, _ = build_recent_features(games)
    point = fit_rest_model(features, features)
    elo = fit_model("elo", {}, features, features)
    models = {}
    module = reference(Path(__file__).resolve())
    for name, model in (("ridge_a100_rest", point), ("elo", elo)):
        path = tmp_path / (name + ".joblib")
        joblib.dump(model, path)
        models[name] = {"artifact": reference(path), "trainingIdentitySha256": model.training_identity_sha256,
                        "trainingLastDate": "2023-10-12", "trainingGameIds": list(model.training_game_ids), "numericalModules": {"synthetic_test": module}}
    models["ridge_a100_rest"]["restSupport"] = point.rest_support
    history_path = tmp_path / "games.parquet"
    games.to_parquet(history_path)
    history_ref = reference(history_path)
    context_ref = write_json(tmp_path, "context.json", {"contextOnlyEvents": []})
    acquisition = write_json(tmp_path, "acquisition.json", {"acquiredAtUtc": "2023-10-13T10:00:00Z"})
    rights = write_json(tmp_path, "test-only-rights.json", {"syntheticFixtureForCalculationTestingOnly": True})
    current = {"configurationIdentity": "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1", "models": models,
               "history": {"games": history_ref, "contextMetadata": context_ref, "acquisition": acquisition}}
    current_ref = write_json(tmp_path, "current.json", current)
    wanted = target(game("wanted", "2023-10-15"))
    schedule = {"schema": "NBA_GEN1_REDUCED_SCHEDULE_EVIDENCE_V1", "dataClassification": "REAL_UNSCRAMBLED_GAMES",
                "reviewedBy": "SYNTHETIC_TEST_ONLY", "target": wanted, "capturedAtUtc": "2023-10-13T11:00:00Z", "sourceObject": rights, "rightsEvidence": [rights]}
    schedule_ref = write_json(tmp_path, "schedule.json", schedule)
    cutoff = "2023-10-14T12:00:00Z"
    coverage = {"schema": "NBA_GEN1_REDUCED_CURRENT_HISTORY_V1", "reviewedBy": "SYNTHETIC_TEST_ONLY",
                "currentResearchReceiptSha256": current_ref["sha256"], "targetGameId": "wanted", "sourceCutoffUtc": cutoff,
                "completeThroughUtc": cutoff, "regularSeasonMembershipComplete": True, "missingGameIds": [], "teamIds": ["A", "B"],
                "identityReconciled": True, "evidence": [rights], "historyPopulation": history_ref, "contextMetadata": context_ref,
                "allHistoryRowsCoveredBySourceCaptures": True, "sourceCaptures": [{"capturedAtUtc": "2023-10-13T10:00:00Z", "sourceObject": rights, "rightsEvidence": [rights]}]}
    coverage_ref = write_json(tmp_path, "coverage.json", coverage)
    monkeypatch.setattr("server.sports_nba_gen1.point_forecast._now", lambda: pd.Timestamp("2023-10-14T13:00:00Z"))
    return tmp_path, current_ref, schedule_ref, coverage_ref, cutoff, schedule, coverage


def test_real_path_calculation_binding_and_separate_channels_with_test_artifacts(bundle):
    _, current, schedule, coverage, cutoff, _, _ = bundle
    forecast = build_point_forecast(current, schedule, coverage, cutoff)
    scores, probabilities = forecast["pointExpectations"], forecast["winnerProbabilities"]
    assert scores["home"] + scores["away"] == scores["total"]
    assert scores["home"] - scores["away"] == scores["homeMargin"]
    assert probabilities["home"] + probabilities["away"] == 1 and probabilities["tie"] == 0
    assert forecast["distributions"]["drawCount"] == 0 and forecast["distributions"]["total"] is None
    assert forecast["publishedAtUtc"] is None and forecast["exportedAtUtc"] is None
    assert len(forecast["inputFeatureValues"]) == 78
    assert not forecast["authority"]["productionAuthority"]


@pytest.mark.parametrize("case", ["fixture", "late_capture", "missing_history", "wrong_binding", "expired"])
def test_missing_or_ineligible_real_evidence_fails_closed(bundle, monkeypatch, case):
    root, current, schedule_ref, coverage_ref, cutoff, schedule, coverage = bundle
    if case == "fixture":
        schedule["dataClassification"] = "FIXTURE"
    elif case == "late_capture":
        schedule["capturedAtUtc"] = "2023-10-14T12:00:01Z"
    elif case == "missing_history":
        coverage["missingGameIds"] = ["missing"]
    elif case == "wrong_binding":
        coverage["currentResearchReceiptSha256"] = "0" * 64
    else:
        monkeypatch.setattr("server.sports_nba_gen1.point_forecast._now", lambda: pd.Timestamp("2023-10-15T22:00:00Z"))
    schedule_ref = write_json(root, "schedule-mutated.json", schedule)
    coverage_ref = write_json(root, "coverage-mutated.json", coverage)
    with pytest.raises(PointForecastUnavailable):
        build_point_forecast(current, schedule_ref, coverage_ref, cutoff)
