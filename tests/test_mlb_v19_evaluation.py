"""Narrow protections for pregame routing and prior-fold-only discovery."""
import numpy as np
import pandas as pd

from server.sports_current_statcast.mlb_v19_evaluation import (
    discover_persistent_regimes, regime_masks,
)


def test_regimes_ignore_outcomes_and_realized_game_state():
    frame = pd.DataFrame({
        "game_day_of_season": [1, 40, 80], "batter_prior_missing": [1, 0, np.nan],
        "pitcher_prior_missing": [0, 1, 0], "batter_last100_pa_count": [0, 20, 100],
        "pitcher_last250_bf_count": [250, 0, 10], "observedClassIndex": [1, 2, 3],
        "context_outs_before": [0, 1, 2], "context_inning": [1, 5, 9],
        "context_base_mask_before": [0, 4, 7], "context_batting_score_diff_before": [-4, 0, 2],
    })
    original, registry = regime_masks(frame)
    changed = frame.copy()
    for name in ("observedClassIndex", "context_outs_before", "context_inning",
                 "context_base_mask_before", "context_batting_score_diff_before"):
        changed[name] = 999
    actual, _ = regime_masks(changed)
    assert all(np.array_equal(original[name], actual[name]) for name in original)
    assert original["BATTER_LOW_ROLLING_EXPOSURE"].tolist() == [False, True, False]
    assert original["BATTER_NO_ROLLING_OBSERVATIONS"].tolist() == [True, False, False]
    assert next(row for row in registry if row["name"] == "BULLPEN_FATIGUE")["availability"] == "UNSUPPORTED_HISTORICAL_REGIME"


def test_specialist_discovery_never_inspects_current_or_future_fold_labels():
    rows = []
    for fold in (1, 2):
        for index in range(4800):
            rows.append({"canonicalPaId": f"pa-{fold}-{index}",
                         "canonicalGameId": f"game-{fold}-{index // 24}",
                         "game_date": f"2024-{3 + fold * 3 + (index // 24) % 3:02d}-01",
                         "foldNumber": fold, "observedClassIndex": 0 if index < 2400 else 6,
                         "batter_prior_missing": int(index < 2400),
                         "homeTeamId": f"team-{(index // 24) % 15}",
                         "awayTeamId": f"team-{15 + (index // 24) % 15}"})
    past = pd.DataFrame(rows)
    probabilities = np.full((len(past), 8), 1 / 8)
    original = discover_persistent_regimes(past, probabilities, before_fold=3)
    assert original["selected"] == ["BATTER_ANNUAL_PRIOR_MISSING"]
    future = past.iloc[[0]].copy()
    future["foldNumber"] = 3
    future["observedClassIndex"] = 999
    future["canonicalPaId"] = "future-unread-pa"
    future["game_date"] = "2026-08-20"  # Sentinel only; no real sealed data.
    combined = pd.concat([past, future], ignore_index=True)
    actual = discover_persistent_regimes(combined, np.vstack([probabilities, np.full((1, 8), np.nan)]), before_fold=3)
    assert actual == original
    assert discover_persistent_regimes(past, probabilities, before_fold=2)["selected"] == []
