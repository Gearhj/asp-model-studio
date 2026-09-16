import json

import numpy as np
import pandas as pd
import pytest

from server.sports_nfl.gold import GAME_FEATURES, ROLLING_METRICS
from server.sports_nfl_m1.semantic_features import make_history_features, SemanticTreatment
from server.sports_nfl_m1.semantic_lab import immutable_json, SemanticForecastArtifact


def fixture_frames():
    games, team, passers = [], [], []
    for i in range(16):
        day = pd.Timestamp("2019-09-01") + pd.Timedelta(days=7 * i)
        # Last two events share a date: updates must remain atomic.
        if i == 15:
            day -= pd.Timedelta(days=7)
        record = {name: 0 for name in GAME_FEATURES}
        record.update(canonical_game_id=f"G{i}", season=2019, week=i+1, game_date=day,
                      canonical_home_team_id="A", canonical_away_team_id="B",
                      home_points=24., away_points=20., roof="outdoors", surface="grass", game_type="REG")
        games.append(record)
        for side in ("A", "B"):
            row = {name: (.4 if name.endswith("rate") else .1 if "epa" in name else 24.) for name in ROLLING_METRICS}
            row.update(canonical_game_id=f"G{i}", season=2019, game_date=day, team_id=side)
            team.append(row)
            passers.append(dict(canonical_game_id=f"G{i}", season=2019, game_date=day, team_id=side, player_id=f"P{side}", attempts=30., epa_sum=3., epa_sumsq=90.))
    return pd.DataFrame(games), pd.DataFrame(team), pd.DataFrame(passers)


def test_zero_exposure_is_prior_not_zero_or_median_and_names_align():
    games, team, qb = fixture_frames()
    history = make_history_features(games, team, qb)
    treatment = SemanticTreatment("C1").fit(history, team, qb)
    values, counts = treatment.transform(history.head(1))
    lookup = dict(zip(treatment.names, values[0]))
    assert lookup["home_offensive_epa_per_play_season_to_date"] == pytest.approx(.1)
    assert lookup["home_offensive_epa_per_play_season_to_date__effective_games"] == 0
    assert lookup["home_offensive_epa_per_play_season_to_date__posterior_sd"] > 0
    assert "roof==outdoors" not in lookup
    assert counts["prior_only_cells"] == 176
    assert len(treatment.names) == values.shape[1] == len(set(treatment.names))
    assert treatment.state()["genericMedianBranch"] is False


def test_history_is_strict_prior_date_and_never_target_starter():
    games, team, qb = fixture_frames()
    history = make_history_features(games, team, qb)
    a = history.loc[history.canonical_game_id.eq("G14")].iloc[0]
    b = history.loc[history.canonical_game_id.eq("G15")].iloc[0]
    assert a["home_points_for_season_to_date__n"] == b["home_points_for_season_to_date__n"]
    assert a["home__lagged_passer_mixture"] == b["home__lagged_passer_mixture"]
    assert json.loads(history.iloc[0]["home__lagged_passer_mixture"]) == []
    assert pd.Timestamp(a["home__last_passer_date"]) < a.game_date


def test_broken_exposure_fails_and_c2_is_real_extra_input():
    games, team, qb = fixture_frames()
    history = make_history_features(games, team, qb)
    c1 = SemanticTreatment("C1").fit(history, team, qb)
    c2 = SemanticTreatment("C2").fit(history, team, qb)
    assert len(c2.names) == len(c1.names) + 12
    values, _ = c2.transform(history)
    assert np.isfinite(values).all()
    broken = history.head(1).copy()
    broken["home_prior_games"] = np.nan
    with pytest.raises(ValueError, match="INVALID_OBSERVED_EXPOSURE"):
        c2.transform(broken)
    unresolved = history.head(1).copy()
    unresolved["home_red_zone_td_play_rate_season_to_date__unknown_games"] = 1
    transformed, counts = c2.transform(unresolved)
    assert np.isnan(transformed[0, list(c2.names).index("home_red_zone_td_play_rate_season_to_date")])
    assert counts["unresolved_native_missing_cells"] == 1
