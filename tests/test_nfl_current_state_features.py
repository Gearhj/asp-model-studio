import pickle

import numpy as np
import pandas as pd
import pytest

from server.sports_nfl.gold import ROLLING_METRICS
from server.sports_nfl_m1.current_state_features import (
    EVIDENCE_CLASS, FORMER_MEDIAN_FIELDS, _attach_timing, aggregate_pbp_partition,
    build_treatment_states, completion_upper_bound, fit_league_prior,
    qb_player_prior, treatment_inventory,
)


def fixture():
    games, rows, qbs = [], [], []
    for i, (season, day, week, score) in enumerate([(2022, "2022-09-01", 1, 20.), (2023, "2023-09-01", 1, 40.),
                                                  (2023, "2023-09-05", 2, 90.), (2023, "2023-09-08", 2, 100.)]):
        games.append(dict(canonical_game_id=f"G{i}", game_date=pd.Timestamp(day), season=season, week=week,
                          game_type="REG", canonical_home_team_id="A", canonical_away_team_id="B",
                          home_points=score, away_points=score - 3))
        for team, opponent in (("A", "B"), ("B", "A")):
            for metric in ROLLING_METRICS:
                value = .5 if metric.endswith("_rate") else (score if metric.startswith("points_") else .2)
                n = 1. if metric.startswith("points_") else 10.
                rows.append(dict(canonical_game_id=f"G{i}", game_date=pd.Timestamp(day), season=season, week=week,
                                 team_id=team, opponent_team_id=opponent, metric=metric, numerator=value*n, denominator=n,
                                 sumsq=(value*value+.1)*n, allowed_numerator=value*n, allowed_denominator=n,
                                 allowed_sumsq=(value*value+.1)*n, evidence_class=EVIDENCE_CLASS))
            qbs.append(dict(canonical_game_id=f"G{i}", game_date=pd.Timestamp(day), season=season, week=week,
                            team_id=team, player_id=f"P{team}", attempts=10., epa_sum=2., epa_sumsq=10., evidence_class=EVIDENCE_CLASS))
    return _attach_timing(pd.DataFrame(games)), pd.DataFrame(rows), pd.DataFrame(qbs)


def test_actual_opportunity_denominators_missing_flags_and_final_ot_scores():
    raw = []
    for i, team in enumerate(["A", "A", "A", "B"]):
        raw.append(dict(season=2023, game_id="G", game_date="2023-09-01", week=1, season_type="REG",
                        home_team="A", away_team="B", home_score=31., away_score=28., posteam=team, defteam="B" if team == "A" else "A",
                        play_type="pass", play_id=i, game_seconds_remaining=100.-i*10, epa=[1., -1., np.nan, .5][i],
                        success=[1., 0., np.nan, 1.][i], yards_gained=25. if i == 0 else 5., down=3,
                        third_down_converted=1. if i == 0 else 0., fourth_down_converted=0., yardline_100=40., touchdown=0.,
                        interception=0., fumble_lost=0., qb_dropback=1., sack=0., penalty=0., passer_player_id=f"P{team}"))
    games, team, qb = aggregate_pbp_partition(pd.DataFrame(raw), expected_season=2023)
    own = team.loc[team.team_id.eq("A")].set_index("metric")
    assert own.loc["pass_epa_per_play", "denominator"] == 2
    assert own.loc["pass_epa_per_play", "numerator"] == 0
    assert own.loc["success_rate", "denominator"] == 2
    assert own.loc["success_rate", "numerator"] == 1
    assert own.loc["rush_epa_per_play", "denominator"] == 0
    assert pd.isna(own.loc["rush_epa_per_play", "value"])
    assert games.iloc[0].home_points == 31
    assert len(team) == 44 and qb.loc[qb.team_id.eq("A"), "attempts"].iloc[0] == 2
    with pytest.raises(ValueError):
        aggregate_pbp_partition(pd.DataFrame(raw).assign(season=2025), expected_season=2025)


def test_embargo_boundary_week_atomicity_and_season_start_hide_current_games():
    games, team, qb = fixture()
    prior = fit_league_prior(games.iloc[:1], team, qb)
    result48 = build_treatment_states(games.iloc[[2, 3]], team, qb, lag_hours=48, decay=.65, league_prior=prior)
    result72 = build_treatment_states(games.iloc[[2, 3]], team, qb, lag_hours=72, decay=.65, league_prior=prior)
    name = "home_points_for_season_to_date"
    assert result48[name].iloc[0] > result72[name].iloc[0]
    assert result48[name].iloc[0] == result48[name].iloc[1]
    assert result48.home_current_games.tolist() == [1, 1]
    week1 = build_treatment_states(games.iloc[[1]], team, qb, league_prior=prior)
    assert week1.home_current_games.iloc[0] == 0
    changed = team.copy()
    changed.loc[changed.canonical_game_id.isin(["G2", "G3"]), "numerator"] = 1e8
    repeated = build_treatment_states(games.iloc[[2, 3]], changed, qb, league_prior=prior)
    np.testing.assert_equal(result48[list(FORMER_MEDIAN_FIELDS)].to_numpy(), repeated[list(FORMER_MEDIAN_FIELDS)].to_numpy())
    boundary = games.iloc[[2]].copy()
    boundary["forecast_cutoff_utc"] = completion_upper_bound("2023-09-01") + pd.Timedelta(hours=48)
    exact = build_treatment_states(boundary, team, qb, lag_hours=48, league_prior=prior)
    assert exact.home_current_games.iloc[0] == 0  # strictly before, not <=


def test_fold_prior_ids_are_bound_and_no_evidence_is_native_unavailable():
    games, team, qb = fixture()
    prior = fit_league_prior(games.iloc[:1], team, qb)
    poisoned = team.copy()
    poisoned.loc[poisoned.canonical_game_id.ne("G0"), "numerator"] = 1e12
    assert prior == fit_league_prior(games.iloc[:1], poisoned, qb)
    empty = build_treatment_states(games.iloc[:1], team, qb, league_prior=prior)
    assert empty[list(FORMER_MEDIAN_FIELDS)].isna().all().all()
    assert empty.generic_median_mode_fallback_count.iloc[0] == 0
    with pytest.raises(ValueError):
        build_treatment_states(games, pd.concat([team, team.assign(season=2025)]), qb)
    with pytest.raises(ValueError):
        build_treatment_states(games, team, qb, lag_hours=24)


def test_current_missing_season_uncertainty_rate_support_and_player_priors():
    games, team, qb = fixture()
    prior = fit_league_prior(games, team, qb)
    current = games.iloc[[0]].assign(canonical_game_id="CURRENT", game_date=pd.Timestamp("2026-09-10"), season=2026, week=1,
                                    forecast_cutoff_utc=pd.Timestamp("2026-09-09T12:00:00Z"), home_points=None, away_points=None)
    result = build_treatment_states(current, team, qb, decay=.65, league_prior=prior)
    assert result.home_prior_season_gap.iloc[0] == 3
    assert result.home_missing_season_uncertainty.iloc[0] == 2
    assert result.home_current_games.iloc[0] == 0
    rate_names = [name for name in FORMER_MEDIAN_FIELDS if "_rate_" in name]
    assert result[rate_names].ge(0).all().all() and result[rate_names].le(1).all().all()
    low = qb_player_prior(qb, "UNSEEN", cutoff_utc="2026-09-09T12:00:00Z", season=2026, decay=.65, league_prior=prior)
    assert low["effectiveExposure"] == 0 and low["mean"] == pytest.approx(.2)
    known = qb_player_prior(qb, "PA", cutoff_utc="2026-09-09T12:00:00Z", season=2026, decay=.65, league_prior=prior)
    assert known["effectiveExposure"] > 0 and known["posteriorSd"] < low["posteriorSd"]


def test_inventory_evidence_class_reload_and_input_order():
    games, team, qb = fixture()
    prior = fit_league_prior(games.iloc[:1], team, qb)
    targets = games.iloc[[3, 2]].copy()
    result = build_treatment_states(targets, team, qb, league_prior=prior)
    assert result.canonical_game_id.tolist() == ["G3", "G2"]
    assert result.evidence_class.eq(EVIDENCE_CLASS).all()
    assert len(treatment_inventory()) == len(set(FORMER_MEDIAN_FIELDS)) == 44
    assert all(not item["genericMedianOrModeFallback"] for item in treatment_inventory())
    restored = pickle.loads(pickle.dumps(result))
    pd.testing.assert_frame_equal(result, restored)
    reference = build_treatment_states(targets, team, qb, league_prior=prior, _vectorized=False)
    pd.testing.assert_frame_equal(result, reference, check_exact=False, atol=1e-12, rtol=1e-12)
    repeated = build_treatment_states(targets.assign(home_points=999), team, qb, league_prior=prior)
    assert repeated.home_points.eq(999).all()
    pd.testing.assert_frame_equal(result.drop(columns="home_points"), repeated.drop(columns="home_points"), check_exact=True)
    modified = team.copy()
    modified.loc[modified.canonical_game_id.eq("G0") & modified.metric.eq("points_for"), "numerator"] += 10
    changed = build_treatment_states(targets, modified, qb, league_prior=prior)
    assert not changed.home_points_for_season_to_date.equals(result.home_points_for_season_to_date)
