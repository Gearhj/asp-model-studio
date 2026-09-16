from __future__ import annotations

import numpy as np
import pandas as pd

from server.sports_cfb_gen1.current import (
    cfbd_2026_games,
    simulate_uncertainty_challenger,
    totals_probabilities,
)


def _population() -> pd.DataFrame:
    rows = []
    for i in range(600):
        rows.append({
            "game_id": i + 1,
            "scheduled_at": pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=i),
            "home_score": 28 + i % 11,
            "away_score": 20 + i % 7,
            "ridge_alpha100_pred_home": 30.0,
            "ridge_alpha100_pred_away": 24.0,
            "home_current_season_games": 0,
            "away_current_season_games": 1,
            "home_long_gap": 0,
            "away_long_gap": 0,
        })
    return pd.DataFrame(rows)


def test_cfbd_adapter_preserves_orientation_and_box_fields() -> None:
    games = [{
        "id": 9, "season": 2026, "week": 1, "seasonType": "regular",
        "startDate": "2026-09-01T00:00:00Z", "completed": True,
        "homeId": 1, "awayId": 2, "homeTeam": "Home", "awayTeam": "Away",
        "homeClassification": "fbs", "awayClassification": "fbs",
        "homePoints": 31, "awayPoints": 17, "homeLineScores": [7, 7, 7, 10],
        "awayLineScores": [3, 7, 0, 7], "neutralSite": False, "conferenceGame": True,
    }]
    team_games = [{"id": 9, "teams": [
        {"teamId": 1, "stats": [{"category": "totalYards", "stat": "410"}, {"category": "turnovers", "stat": "1"}]},
        {"teamId": 2, "stats": [{"category": "totalYards", "stat": "299"}, {"category": "turnovers", "stat": "2"}]},
    ]}]
    row = cfbd_2026_games(games, team_games).iloc[0]
    assert (row.home_id, row.away_id, row.home_score, row.away_score) == (1, 2, 31.0, 17.0)
    assert row.home_total_yards == 410.0 and row.away_turnovers == 2.0
    assert row.primary and row.period_reconciles


def test_ordinary_challenger_returns_exact_baseline() -> None:
    donors = _population()
    target = pd.Series({
        "game_id": 1000, "scheduled_at": pd.Timestamp("2022-01-01", tz="UTC"),
        "ridge_alpha100_pred_home": 30.0, "ridge_alpha100_pred_away": 24.0,
        "home_current_season_games": 3, "away_current_season_games": 2,
        "home_long_gap": 0, "away_long_gap": 0,
    })
    baseline, candidate, accounting = simulate_uncertainty_challenger(
        target, donors, "ridge_alpha100", draw_count=200
    )
    pd.testing.assert_frame_equal(baseline, candidate)
    assert accounting["disposition"] == "EXACT_BASELINE_ORDINARY"


def test_supported_challenger_centers_pairs_and_totals_reconcile() -> None:
    donors = _population()
    target = pd.Series({
        "game_id": 1001, "scheduled_at": pd.Timestamp("2022-01-01", tz="UTC"),
        "ridge_alpha100_pred_home": 30.0, "ridge_alpha100_pred_away": 24.0,
        "home_current_season_games": 1, "away_current_season_games": 2,
        "home_long_gap": 0, "away_long_gap": 0,
    })
    _, candidate, accounting = simulate_uncertainty_challenger(
        target, donors, "ridge_alpha100", draw_count=200
    )
    assert accounting["applied"] and accounting["candidateDonorCount"] == 600
    assert abs(accounting["centeredHomeResidualMean"]) < 1e-12
    assert abs(accounting["centeredAwayResidualMean"]) < 1e-12
    assert (candidate.total == candidate.home_score + candidate.away_score).all()
    assert not (candidate.home_score == candidate.away_score).any()
    probabilities = totals_probabilities(candidate, 54.0)
    assert abs(probabilities["over"] + probabilities["push"] + probabilities["under"] - 1.0) < 1e-12
    half = totals_probabilities(candidate, 54.5)
    assert half["push"] == 0.0
