"""Focused synthetic checks; these are not Development fitted evidence."""
import io

import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_nfl_m1 import current_state_model as model


def _games(seasons):
    records = []
    for season in seasons:
        for week in range(1, 17):
            records.append({"canonical_game_id": f"{season}_{week:02d}_A_B",
                            "game_date": pd.Timestamp(f"{season}-09-01") + pd.Timedelta(days=week * 7),
                            "season": season, "week": week,
                            "home_points": 17 + (week * 7 + season) % 24,
                            "away_points": 10 + (week * 3 + season) % 27})
    return pd.DataFrame(records)


def _states(games, team, qb, *, lag_hours, decay, league_prior):
    states = games.copy()
    states["evidence_class"] = model.EVIDENCE_CLASS
    data = {}
    for index, name in enumerate(model.RATE_NAMES):
        points = "points_for" in name or "points_against" in name
        data[name] = 22.0 + np.sin(states.week.to_numpy() + index) * decay if points else np.full(len(states), 0.2 + index / 1000)
        data[name + "__posterior_sd"] = np.full(len(states), 4.0 if points else 0.1)
        data[name + "__effective_exposure"] = states.week.to_numpy() * 3.0
        data[name + "__current_exposure"] = states.week.to_numpy() - 1.0
        data[name + "__source_unknown"] = np.zeros(len(states))
    for name in model.EXTRA_NAMES:
        data[name] = np.ones(len(states))
        if name.endswith("missing_season_uncertainty"):
            data[name] = np.maximum(0, states.season.to_numpy() - 2020)
    return pd.concat([states.reset_index(drop=True), pd.DataFrame(data)], axis=1)


@pytest.fixture
def fitted(monkeypatch):
    monkeypatch.setattr(model, "_feature_api", lambda: (
        _states, lambda games, team, qb, **kwargs: {"training_ids": games.canonical_game_id.tolist()}))
    games = _games([2017, 2018, 2019])
    empty_history = pd.DataFrame({"season": [2017]})
    events = []
    system = model.fit_current_state_system(games, empty_history, empty_history,
                                           receipt_callback=events.append)
    return system, empty_history, events


def test_chronological_residual_authority_and_deterministic_reload(fitted):
    system, history, events = fitted
    assert sum(event["event"] == "ESTIMATOR_FIT_START" for event in events) == 6
    assert sum(event["event"] == "ESTIMATOR_FIT_COMPLETE" for event in events) == 6
    assert sum(event["event"] == "DECAY_EVALUATION_COMPLETE" for event in events) == 3
    assert system.decay in model.RETENTIONS
    for bank in system.residual_banks.values():
        assert bank.row_count == 16
        assert all(name.startswith("2019_") for name in bank.row_ids)
    target = _games([2020]).head(3)
    expected = system.predict(target, history, history, draws=300, seed=817)
    stream = io.BytesIO()
    joblib.dump(system, stream)
    stream.seek(0)
    reloaded = joblib.load(stream)
    actual = reloaded.predict(target, history, history, draws=300, seed=817)
    for candidate in model.MODEL_IDS:
        np.testing.assert_array_equal(actual[candidate]["homeDraws"], expected[candidate]["homeDraws"])
        np.testing.assert_array_equal(actual[candidate]["awayDraws"], expected[candidate]["awayDraws"])
        np.testing.assert_allclose(actual[candidate]["probabilityAwayTieHome"].sum(axis=1), 1, rtol=0, atol=1e-15)
        assert actual[candidate]["homeDraws"].dtype == np.int32
        assert np.all(actual[candidate]["homeDraws"] >= 0)


def test_unknown_source_stays_missing_and_gap_widens_uncertainty(fitted):
    system, history, _ = fitted
    target = _games([2020]).head(2)
    states = _states(target, history, history, lag_hours=48, decay=system.decay, league_prior={})
    before = model._uncertainty(states)
    unknown = "home_pass_epa_per_play_season_to_date"
    states.loc[0, unknown] = np.nan
    states.loc[0, unknown + "__source_unknown"] = 1
    states.loc[0, "home_missing_season_uncertainty"] = 1
    after = model._uncertainty(states)
    predictions = system.core.predict(states)
    assert np.isnan(states.loc[0, unknown])
    assert after[0, 0] > before[0, 0]
    assert all(np.isfinite(value).all() for value in predictions.values())
    coverage = system._coverage(states)
    assert coverage["sourceUnknownCells"] == 1
    assert coverage["genericMedianFallbacks"] == coverage["genericModeFallbacks"] == 0


def test_residual_correction_is_bounded(fitted):
    system, history, _ = fitted
    class ExtremeResidual:
        def predict(self, values):
            return np.full(len(values), 1000000.0)
    system.core.residual_models = [ExtremeResidual(), ExtremeResidual()]
    states = _states(_games([2020]).head(2), history, history, lag_hours=48,
                     decay=system.decay, league_prior={})
    predictions = system.core.predict(states)
    np.testing.assert_allclose(predictions["RESIDUAL"] - predictions["HIERARCHICAL"],
                               model.RESIDUAL_BOUND_POINTS)


def test_sealed_partition_and_nonprospective_prediction_fail_closed(fitted):
    system, history, _ = fitted
    with pytest.raises(ValueError, match="SEALED_2025_NOT_PERMITTED"):
        system.predict(_games([2025]), history, history)
    with pytest.raises(ValueError, match="FORECAST_NOT_AFTER_MODEL_TRAINING_CUTOFF"):
        system.predict(_games([2019]), history, history)
    with pytest.raises(ValueError, match="SEALED_2025_NOT_PERMITTED"):
        model.fit_current_state_system(_games([2018, 2019]), pd.DataFrame({"season": [2025]}), history)
