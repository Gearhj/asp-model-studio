from __future__ import annotations

import pandas as pd
import pytest

from server.sports_nfl_m1.schedule_adjusted_effects import (
    EffectConfig,
    build_game_effect_features,
    fit_unit_effects,
)


def source_frame() -> pd.DataFrame:
    rows = []
    games = [
        ("2021_01_A_B", 2021, 1, "2021-09-01", "A", "B", True, 0.30, 0.10),
        ("2021_01_A_B", 2021, 1, "2021-09-01", "B", "A", False, -0.20, -0.05),
        ("2021_02_A_C", 2021, 2, "2021-09-08", "A", "C", False, 0.20, None),
        ("2021_02_A_C", 2021, 2, "2021-09-08", "C", "A", True, -0.10, 0.15),
        ("2022_01_B_C", 2022, 1, "2022-09-01", "B", "C", True, -0.05, 0.00),
        ("2022_01_B_C", 2022, 1, "2022-09-01", "C", "B", False, 0.05, 0.20),
    ]
    for game, season, week, date, team, opponent, home, passing, rushing in games:
        rows.append({
            "canonical_game_id": game, "season": season, "week": week,
            "game_date": date, "team_id": team, "opponent_team_id": opponent,
            "is_home": home, "pass_epa_per_play": passing,
            "rush_epa_per_play": rushing,
        })
    return pd.DataFrame(rows)


def test_target_or_future_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="future"):
        fit_unit_effects(
            source_frame(), unit="pass", target_season=2022,
            origin_date=pd.Timestamp("2022-09-01", tz="UTC"),
            config=EffectConfig(10.0, 0.5),
        )


def test_missing_unit_stays_missing_and_support_is_explicit() -> None:
    frame = source_frame()
    fit = fit_unit_effects(
        frame, unit="rush", target_season=2023,
        origin_date=pd.Timestamp("2023-09-01", tz="UTC"),
        config=EffectConfig(10.0, 0.5),
    )
    # A has one missing rush observation; it is excluded, never changed to zero.
    assert fit.weighted_support["A"] == pytest.approx(0.25)
    assert fit.team_support("NEW")["current"] == 0
    assert fit.team_support("NEW")["status"] == "LEAGUE_SHRUNK_NO_CURRENT_SEASON_EVIDENCE"
    assert fit.coefficient("offense", "NEW") == 0.0


def test_orientation_and_deterministic_replay() -> None:
    frame = source_frame()
    cfg = EffectConfig(10.0, 0.75)
    first_pass = fit_unit_effects(frame, unit="pass", target_season=2023,
                                  origin_date=pd.Timestamp("2023-09-01", tz="UTC"), config=cfg)
    first_rush = fit_unit_effects(frame, unit="rush", target_season=2023,
                                  origin_date=pd.Timestamp("2023-09-01", tz="UTC"), config=cfg)
    second_pass = fit_unit_effects(frame.sample(frac=1.0, random_state=3), unit="pass", target_season=2023,
                                   origin_date=pd.Timestamp("2023-09-01", tz="UTC"), config=cfg)
    values = build_game_effect_features("A", "B", 2023, first_pass, first_rush)
    reversed_values = build_game_effect_features("B", "A", 2023, first_pass, first_rush)
    assert first_pass.training_population_sha256 == second_pass.training_population_sha256
    assert first_pass.predict("A", "B", is_home=True, season=2023) == pytest.approx(
        second_pass.predict("A", "B", is_home=True, season=2023), abs=1e-12
    )
    assert values["home_pass_offense_effect"] == pytest.approx(first_pass.coefficient("offense", "A"))
    assert values["away_pass_defense_effect"] == pytest.approx(first_pass.coefficient("defense", "B"))
    assert values["pass_matchup_difference"] != reversed_values["pass_matchup_difference"]


def test_decay_changes_weighted_support_and_shrinkage_is_monotone() -> None:
    frame = source_frame()
    low = fit_unit_effects(frame, unit="pass", target_season=2023,
                           origin_date=pd.Timestamp("2023-09-01", tz="UTC"),
                           config=EffectConfig(10.0, 0.5))
    high = fit_unit_effects(frame, unit="pass", target_season=2023,
                            origin_date=pd.Timestamp("2023-09-01", tz="UTC"),
                            config=EffectConfig(10.0, 0.75))
    assert low.weighted_support["A"] < high.weighted_support["A"]
    assert low.team_support("A")["shrinkageWeight"] == 0.0
    assert low.team_support("A")["uncertaintyProxy"] < 1.0

