"""Focused synthetic repair checks; no Development fitted evidence."""
import io
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from server.sports_nfl_m1 import current_state_repaired_model as model


def _games(seasons):
    return pd.DataFrame([{"canonical_game_id": f"{year}_{week:02d}_A_B", "season": year, "week": week,
        "game_date": pd.Timestamp(f"{year}-09-01") + pd.Timedelta(days=week*7),
        "home_points": 17 + (week*7+year) % 24, "away_points": 10+(week*3+year) % 27}
        for year in seasons for week in range(1, 17)])


def _states(games, team, qb, *, lag_hours, decay, league_prior):
    data = {}
    week = games.week.to_numpy(float)
    gap = np.array([max(0, year-int(team.loc[team.season < year, "season"].max())-1)
                    if (team.season < year).any() else 0 for year in games.season])
    for i, name in enumerate(model.RATE_NAMES):
        scoring = "points_for" in name or "points_against" in name
        data[name] = (22. if scoring else .2) + np.sin(week+i)*decay*(1 if scoring else .02)
        for suffix, values in (("__posterior_sd", (4.+gap if scoring else np.full(len(games), .1))),
            ("__effective_exposure", week*3), ("__current_exposure", week-1), ("__source_unknown", np.zeros(len(games)))):
            data[name+suffix] = values
    for side in ("home", "away"):
        data[f"{side}_qb_epa_mean"] = np.sin(week)/10
        data[f"{side}_qb_effective_exposure"] = week*10
        data[f"{side}_qb_posterior_sd"] = .1*(1+gap)+week*.001
        data[f"{side}_prior_games"] = week+30
        data[f"{side}_current_games"] = week-1
        data[f"{side}_prior_season_gap"] = gap+1
        data[f"{side}_missing_season_uncertainty"] = gap
    states = pd.concat([games.reset_index(drop=True), pd.DataFrame(data)], axis=1)
    states["evidence_class"] = model.EVIDENCE_CLASS
    return states


@pytest.fixture
def fitted(monkeypatch):
    monkeypatch.setattr(model, "_feature_api", lambda: (_states,
        lambda games, team, qb, **kwargs: {"training_ids": games.canonical_game_id.tolist()}))
    games = _games([2017, 2018, 2019])
    history = pd.DataFrame({"season": [2016, 2017, 2018, 2019]})
    predecessor = SimpleNamespace(lag_hours=48, decay=.65,
        league_prior={"training_ids": games.canonical_game_id.tolist()}, core=SimpleNamespace(home_advantage=2.))
    events = []
    fitted = model.fit_repaired_current_state_system(games, history, history,
        predecessor=predecessor, receipt_callback=events.append)
    return fitted, history, events


def test_all_uncertainty_roles_excluded_from_both_means_and_finite_population_mean(fitted):
    system, history, _ = fitted
    assert len(model.INPUT_NAMES) == 58 and len(model.MEAN_INPUT_NAMES) == 52
    assert len(model.UNCERTAINTY_ONLY_NAMES) == 6
    assert set(model.MEAN_INPUT_NAMES).isdisjoint(model.UNCERTAINTY_ONLY_NAMES)
    states = _states(_games([2020]).head(3), history, history, lag_hours=48, decay=.65, league_prior={})
    changed = states.copy()
    for name in model.UNCERTAINTY_ONLY_NAMES:
        changed[name] = changed[name]*100 + 17
    for name in changed:
        if name.endswith("__posterior_sd"):
            changed[name] *= 40
    first, second = system.predict_states(states, draws=500), system.predict_states(changed, draws=500)
    for name in model.MODEL_IDS:
        np.testing.assert_array_equal(first[name]["scoreMeans"], second[name]["scoreMeans"])
        np.testing.assert_array_equal(first[name]["distributionScoreMeans"], second[name]["distributionScoreMeans"])
        for side, index in (("home", 0), ("away", 1)):
            expected = np.rint(first[name]["scoreMeans"][:, index]*500).astype(int)
            np.testing.assert_array_equal(second[name][f"{side}Draws"].sum(axis=1), expected)
            assert (second[name][f"{side}Draws"] >= 0).all()
    assert system.core.ridge.n_features_in_ == 104
    assert all(estimator.n_features_in_ == 56 for estimator in system.core.residual_models)


def test_symmetric_fitted_variance_law_supported_dropout_gap_and_roles():
    history = pd.DataFrame({"season": [2017, 2018]})
    normal = _states(_games([2019]).head(12), history, history, lag_hours=48, decay=.65, league_prior={})
    dropout = normal.copy()
    for side in ("home", "away"):
        dropout[f"{side}_missing_season_uncertainty"] = 1
        dropout[f"{side}_prior_season_gap"] = 2
    true_beta = np.array([4., .5, 10., 25.])
    law = model.FittedVarianceLaw.fit(normal, dropout,
        np.sqrt(model.uncertainty_design(normal) @ true_beta),
        np.sqrt(model.uncertainty_design(dropout) @ true_beta), callback=None, component="FIXTURE")
    assert law.metadata["gapIdentifiable"] and (law.coefficients >= 0).all()
    assert np.all(law.predict(dropout) > law.predict(normal))
    swapped = dropout.rename(columns={name: ("away_"+name[5:] if name.startswith("home_") else
        "home_"+name[5:] if name.startswith("away_") else name) for name in dropout})
    np.testing.assert_allclose(law.predict(swapped), law.predict(dropout)[:, ::-1], rtol=0, atol=1e-12)
    collinear = dropout.copy()
    for column in collinear:
        if column.endswith("__posterior_sd") and ("points_for" in column or "points_against" in column):
            collinear[column] = 8.
    unsupported = model.FittedVarianceLaw.fit(normal, collinear,
        np.sqrt(model.uncertainty_design(normal) @ true_beta),
        np.sqrt(model.uncertainty_design(collinear) @ true_beta), callback=None, component="FIXTURE")
    assert not unsupported.metadata["gapIdentifiable"]
    assert unsupported.coefficients[3] == 0


def test_chronological_fixed_fit_accounting_reconstruction_and_reload(fitted):
    system, history, events = fitted
    assert sum(row["event"] == "ESTIMATOR_FIT_START" for row in events) == 6
    assert sum(row["event"] == "ESTIMATOR_FIT_COMPLETE" for row in events) == 6
    assert sum(row["event"] == "UNCERTAINTY_FIT_COMPLETE" for row in events) == 3
    assert not any(row["event"].startswith("DECAY_") for row in events)
    assert system.decay == .65 and system.core.home_advantage == 2.
    assert all(all(identity.startswith("2019_") for identity in bank.row_ids) for bank in system.residual_banks.values())
    states = _states(_games([2020]).head(3), history, history, lag_hours=48, decay=.65, league_prior={})
    expected = system.predict_states(states, draws=500)
    rebuilt = system.predict(_games([2020]).head(3), history, history, draws=500)
    stream = io.BytesIO()
    joblib.dump(system, stream)
    stream.seek(0)
    restored = joblib.load(stream).predict_states(states, draws=500)
    for name in model.MODEL_IDS:
        np.testing.assert_array_equal(expected[name]["homeDraws"], rebuilt[name]["homeDraws"])
        np.testing.assert_array_equal(expected[name]["awayDraws"], restored[name]["awayDraws"])
        np.testing.assert_allclose(expected[name]["probabilityAwayTieHome"].sum(axis=1), 1, atol=1e-15)
    assert system.state()["repairAuthority"] == model.REPAIR_AUTHORITY


def test_sealed_cutoff_guards_and_nonnegative_exact_balanced_projection(fitted):
    system, history, _ = fitted
    with pytest.raises(ValueError, match="SEALED_2025"):
        system.predict(_games([2025]), history, history)
    with pytest.raises(ValueError, match="FORECAST_NOT_AFTER"):
        system.predict(_games([2019]), history, history)
    raw = np.array([[-100., -10., 50., 90.], [-1., 0., 1., 2.]])
    means = np.array([.375, 0.])
    projected = model.mean_preserving_scores(raw, means)
    np.testing.assert_array_equal(projected.sum(axis=1), np.rint(means*4))
    assert (projected >= 0).all() and projected.dtype == np.int32
    assert np.all(np.diff(projected[0]) >= 0)
    with pytest.raises(ValueError, match="INVALID_MEAN"):
        model.mean_preserving_scores(raw, [-1., 0.])
