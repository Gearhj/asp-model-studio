"""Synthetic safety/recipe tests; no retained historical or current-year access."""
import numpy as np
import pandas as pd
import pytest

from scripts.freeze_cfb_strength_candidate_v1 import (
    baseline, exclusive_json, fit_candidate, fixed_recipe, freeze, prepare_frames,
)


def frames():
    rng = np.random.default_rng(14)
    seasons = np.repeat(np.arange(2014, 2026), 50)
    n = len(seasons)
    rows = pd.DataFrame({"game_id": np.arange(n), "season": seasons, "week": np.tile(np.arange(1, 11), n // 10),
                         "home_id": 1, "away_id": 2, "neutral_site": False, "primary": True, "is_final": True})
    rows["scheduled_at"] = pd.to_datetime(rows.season.astype(str) + "-09-01", utc=True) + pd.to_timedelta(np.arange(n) % 50, unit="D")
    rows["home_score"] = rng.integers(10, 50, n)
    rows["away_score"] = rng.integers(10, 50, n)
    rows["home_margin"], rows["total_points"] = rows.home_score - rows.away_score, rows.home_score + rows.away_score
    rows["home_win"] = (rows.home_score > rows.away_score).astype(int)
    features = rows.copy()
    for key in baseline.FEATURE_COLUMNS:
        if key not in features:
            features[key] = rng.normal(size=n)
    features["research_origin"] = features.scheduled_at.dt.floor("D")
    features["feature_max_source_game_date"] = features.research_origin - pd.Timedelta(days=7)
    sidecar = pd.DataFrame({"game_id": rows.game_id, "origin": features.research_origin,
                            "history_latest_kickoff": features.research_origin - pd.Timedelta(days=3),
                            "strength_pred_margin": rng.normal(size=n), "strength_pred_total": rng.normal(50, 5, n)})
    oof = rows.loc[rows.season.ge(2016)].copy()
    oof["arm"], oof["trainingThroughSeason"] = "B", oof.season - 1
    oof["lambda_prior"] = np.where(oof.season.le(2018), 12.0, 4.0)
    oof["pred_home"], oof["pred_away"] = rng.normal(28, 2, len(oof)), rng.normal(25, 2, len(oof))
    oof["pred_margin"], oof["pred_total"] = oof.pred_home - oof.pred_away, oof.pred_home + oof.pred_away
    return features, sidecar, oof, rows


def test_fits_fixed_37_features_preserving_actual_oof_donors():
    train, donors, history, columns = prepare_frames(*frames())
    fitted = fit_candidate(train, donors, history, columns, {}, [])
    assert len(columns) == 37 and len(fitted["historicalPrimary"]) == 600
    assert fitted["models"]["margin"].named_steps["model"].alpha == 100
    assert fitted["models"]["total"].named_steps["imputer"].strategy == "median"
    assert fitted["calibrator"].C == 1 and len(fitted["residualDonors"]) == 500
    assert set(fitted["residualDonors"].lambda_prior) == {4.0, 12.0}
    np.testing.assert_array_equal(fitted["residualDonors"].homeResidual, donors.home_score - donors.pred_home)
    assert fixed_recipe()["lambdaPrior"] == 4 and fixed_recipe()["drawCount"] == 10000


@pytest.mark.parametrize("failure", ["future", "same_season_oof", "reversed_identity", "missing_strength", "recent_history"])
def test_invalid_final_fit_inputs_fail_closed(failure):
    features, sidecar, oof, history = frames()
    if failure == "future": features.loc[0, "season"] = 2026
    elif failure == "same_season_oof": oof["trainingThroughSeason"] = oof.season
    elif failure == "reversed_identity": oof.iloc[0, oof.columns.get_loc("home_id")] = 2
    elif failure == "missing_strength": sidecar.loc[0, "strength_pred_total"] = np.nan
    else: sidecar.loc[0, "history_latest_kickoff"] = sidecar.loc[0, "origin"] - pd.Timedelta(hours=1)
    with pytest.raises(ValueError):
        prepare_frames(features, sidecar, oof, history)


def test_existing_fit_marker_prevents_even_loading_inputs(tmp_path):
    exclusive_json(tmp_path / "FINAL_FIT_STARTED.json", {"synthetic": True})
    with pytest.raises(FileExistsError, match="refitting"):
        freeze(tmp_path, study=tmp_path / "not_a_study")


def test_original_study_cannot_be_an_output(tmp_path):
    with pytest.raises(ValueError, match="immutable"):
        freeze(tmp_path / "nested", study=tmp_path)


def test_exclusive_receipt_cannot_be_overwritten(tmp_path):
    path = tmp_path / "receipt.json"
    exclusive_json(path, {"first": True})
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        exclusive_json(path, {"first": False})
    assert path.read_bytes() == before
