import numpy as np
import pandas as pd

from server.sports_current_statcast.mlb_diamond_twin_screen import (
    POSITION_GROUPS,
    apply_identity_effects,
    fit_identity_effects,
    lineup_shifts,
)
from server.sports_current_statcast.mlb_v19_structural_defense import (
    BIP_INDICES,
    UNCHANGED_INDICES,
)
from scripts.run_mlb_diamond_twin_screen import add_carry_forward, pa_loss_differences


def synthetic_lineups():
    good = ["c1", "1b1", "2b1", "3b1", "ss-good", "lf1", "cf1", "rf1"]
    poor = ["c2", "1b2", "2b2", "3b2", "ss-poor", "lf2", "cf2", "rf2"]
    return np.asarray([good, poor] * 80, dtype=object)


def test_identity_fit_detects_opposite_lineup_residuals_and_centers_positions():
    lineups = synthetic_lineups()
    baseline = np.full(len(lineups), 0.30)
    observed = np.asarray(([0, 1] * 40) + ([0, 1] * 40), dtype=float)
    model = fit_identity_effects(baseline, observed, lineups, penalty=2.0)
    shifts = lineup_shifts(model, lineups)
    assert model.optimizer_success
    assert shifts[0] < 0 < shifts[1]
    assert np.isclose(shifts[::2].mean() + shifts[1::2].mean(), 0.0, atol=1e-8)


def test_unknown_players_are_zero_and_position_ablation_is_bounded():
    lineups = synthetic_lineups()
    model = fit_identity_effects(np.full(len(lineups), 0.3), np.asarray([0, 1] * 80), lineups, penalty=2.0)
    unknown = np.asarray([[f"unknown-{position}" for position in range(2, 10)]], dtype=object)
    assert lineup_shifts(model, unknown)[0] == 0.0
    full = lineup_shifts(model, lineups[:2], maximum_absolute_shift=0.01)
    infield = lineup_shifts(model, lineups[:2], included_positions=POSITION_GROUPS["INFIELD"])
    assert np.max(np.abs(full)) <= 0.01
    assert not np.array_equal(full, infield)


def test_probability_adjustment_preserves_v18_contract():
    baseline = np.asarray([[0.20, 0.08, 0.04, 0.18, 0.06, 0.01, 0.41, 0.02]])
    candidate = apply_identity_effects(baseline, [0.1])
    assert np.array_equal(candidate[:, UNCHANGED_INDICES], baseline[:, UNCHANGED_INDICES])
    assert np.allclose(candidate[:, BIP_INDICES].sum(axis=1), baseline[:, BIP_INDICES].sum(axis=1))
    assert np.allclose(candidate.sum(axis=1), 1.0)


def test_carry_forward_uses_only_a_strictly_earlier_calendar_date():
    players = {f"player_{position}": [f"old-{position}", f"same-{position}", f"next-{position}"] for position in range(2, 10)}
    rows = pd.DataFrame({
        "canonicalGameId": ["g1", "g2", "g3"],
        "homeAway": ["home", "away", "home"],
        "canonicalTeamId": ["team", "team", "team"],
        "gameDate": pd.to_datetime(["2024-05-01", "2024-05-01", "2024-05-02"]),
        "availabilityDate": pd.to_datetime(["2024-05-01", "2024-05-01", "2024-05-02"]),
        "completeStartingDefense": [True, True, True],
        **players,
    })
    carried = add_carry_forward(rows)
    assert not carried.loc[carried["canonicalGameId"].isin(["g1", "g2"]), "completeCarryDefense"].any()
    next_game = carried.loc[carried["canonicalGameId"] == "g3"].iloc[0]
    assert next_game["carry_player_6"] in {"old-6", "same-6"}


def test_non_bip_rows_do_not_enter_conditional_bip_loss_difference():
    baseline = np.asarray([[0.25, 0.10, 0.05, 0.18, 0.06, 0.01, 0.33, 0.02]])
    candidate = baseline.copy()
    candidate[0, 3] += 0.02
    candidate[0, 6] -= 0.02
    differences = pa_loss_differences(np.asarray([0]), baseline, candidate)
    assert differences[0, 0] == 0.0
    assert differences[0, 1] == 0.0
    assert differences[0, 4] == 0.0
