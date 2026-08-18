"""Hermetic unit tests for the Phase 5B empirical base-out transition model.

Covers legality (conservation + forward/hold + no-pass), the deterministic HOME_RUN rule,
forced walk advancement, strikeout ordinary/exceptional handling, single/double/triple and
BIP_OUT multi-out transitions, OTHER_REACH, every base/out state, inning-ending strands,
runner-identity application without duplication/loss, distribution validity, the fallback
hierarchy, temporal fitting, reproducible RNG, and safe JSON round-tripping. No betting logic.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_phase5 import base_out_transition as bt

FIRST, SECOND, THIRD = 1, 2, 4


def _row(outcome, ob, bb, oa, ba, runs):
    return {"pa_outcome": outcome, "outs_before": ob, "base_mask_before": bb,
            "outs_after": ob + oa, "base_mask_after": ba, "runs_scored": runs}


# ---- legality ----
def test_home_run_is_deterministic_for_all_states():
    for outs in range(3):
        for base in range(8):
            t = bt.home_run_transition(outs, base)
            assert t == (0, 0, bt.popcount(base) + 1)
            assert bt.is_legal(outs, base, t)


def test_conservation_and_hold_are_legal():
    assert bt.is_legal(0, SECOND, (0, FIRST | SECOND, 0))       # walk: batter 1st, runner holds 2nd
    assert bt.is_legal(0, SECOND, (0, FIRST, 1))                # single: runner 2nd scores, batter 1st
    assert bt.is_legal(1, FIRST, (2, 0, 0))                     # double play, inning continues
    assert bt.is_legal(2, FIRST | SECOND, (1, 0, 0))            # third out strands two runners


def test_illegal_transitions_rejected():
    assert not bt.is_legal(0, 0, (0, FIRST | SECOND, 0))        # a runner appears from nowhere
    assert not bt.is_legal(2, 0, (2, 0, 0))                     # outs exceed 3
    assert not bt.is_legal(0, 0, (0, 0, 2))                     # runs with nobody on base + batter=1 max


def test_forward_assignment_flexibility_and_impossible_rejection():
    # A runner on second scoring while the batter triples to third is legal (no passing).
    assert bt.is_legal(0, SECOND, (0, THIRD, 1))
    # But a transition that leaves more players on base than entered is impossible.
    assert not bt.is_legal(0, SECOND, (0, FIRST | SECOND | THIRD, 0))  # 2 -> 3 on base, none out/scored


def test_enumerate_legal_only_returns_legal():
    for outs in range(3):
        for base in range(8):
            for t in bt.enumerate_legal_transitions(outs, base):
                assert bt.is_legal(outs, base, t)


# ---- model fit / distribution ----
def _fitted():
    records = []
    # SINGLE, runner on second: 70% score, 30% hold at third
    records += [_row("SINGLE", 0, SECOND, 0, FIRST, 1)] * 70
    records += [_row("SINGLE", 0, SECOND, 0, FIRST | THIRD, 0)] * 30
    # BIP_OUT, runner on first, 0 outs: ordinary out vs double play
    records += [_row("BIP_OUT", 0, FIRST, 1, FIRST, 0)] * 60
    records += [_row("BIP_OUT", 0, FIRST, 2, 0, 0)] * 40
    # WALK, bases loaded: forced run
    records += [_row("WALK_HBP_CI", 1, FIRST | SECOND | THIRD, 0, FIRST | SECOND | THIRD, 1)] * 50
    # STRIKEOUT ordinary
    records += [_row("STRIKEOUT", 0, 0, 1, 0, 0)] * 100
    return bt.fit(records, seasons=(2021, 2022, 2023))


def test_distribution_sums_to_one_and_is_legal():
    model = _fitted()
    for outcome in bt.PA_CLASSES:
        for outs in range(3):
            for base in range(8):
                d = model.distribution(outcome, outs, base)
                bt.validate_distribution(d, outs, base)


def test_empirical_probabilities_reflect_counts():
    model = _fitted()
    d = model.distribution("SINGLE", 0, SECOND)
    top = d["transitions"][0]
    # the 70% (runner scores, batter to first) transition should dominate
    assert (top["outsAdded"], top["baseMaskAfter"], top["runs"]) == (0, FIRST, 1)
    assert top["probability"] > 0.6


def test_unseen_but_legal_gets_positive_smoothed_mass():
    model = _fitted()
    d = model.distribution("SINGLE", 0, SECOND)
    # a legal-but-unobserved transition (e.g., runner out) still receives small positive mass
    probs = [t["probability"] for t in d["transitions"]]
    assert all(p > 0 for p in probs)
    assert abs(sum(probs) - 1.0) < 1e-9


def test_home_run_distribution_is_point_mass():
    model = _fitted()
    d = model.distribution("HOME_RUN", 1, FIRST | THIRD)
    assert d["fallbackLevel"] == "DETERMINISTIC_HOME_RUN"
    winners = [t for t in d["transitions"] if t["probability"] > 0]
    assert len(winners) == 1 and winners[0]["runs"] == 3


def test_bip_out_multi_out_transition_present():
    model = _fitted()
    d = model.distribution("BIP_OUT", 0, FIRST)
    dp = [t for t in d["transitions"] if t["outsAdded"] == 2]
    assert dp and dp[0]["probability"] > 0.2  # double play observed


def test_forced_walk_bases_loaded_scores_run():
    model = _fitted()
    d = model.distribution("WALK_HBP_CI", 1, FIRST | SECOND | THIRD)
    top = d["transitions"][0]
    assert top["runs"] == 1 and top["baseMaskAfter"] == (FIRST | SECOND | THIRD)


def test_fallback_hierarchy_uses_legal_prior_for_unseen_cell():
    model = _fitted()
    d = model.distribution("TRIPLE", 2, FIRST | SECOND | THIRD)  # never observed
    assert d["fallbackLevel"] in ("L1_OUTCOME_OUTS", "L2_OUTCOME", "L3_LEGAL_PRIOR")
    bt.validate_distribution(d, 2, FIRST | SECOND | THIRD)


# ---- runner identity ----
def test_apply_transition_no_duplicate_or_loss():
    # runner on second scores, batter to first
    out = bt.apply_transition_to_runners(SECOND, {2: "R2"}, "BAT", (0, FIRST, 1))
    assert out["afterRunners"] == {1: "BAT"} and out["scored"] == ["R2"]
    ids = list(out["afterRunners"].values()) + out["scored"] + out["stranded"]
    assert len(ids) == len(set(ids))


def test_apply_transition_strands_on_inning_end():
    out = bt.apply_transition_to_runners(FIRST | SECOND, {1: "R1", 2: "R2"}, "BAT", (1, 0, 0))
    # third out: batter out, two runners stranded, none score
    total = len(out["afterRunners"]) + len(out["scored"]) + len(out["stranded"]) + out["outsAdded"]
    assert total == 3


def test_apply_covers_every_enumerated_legal_transition():
    # any legal transition must be assignable to identities (no lost runners)
    for base in range(8):
        for outs in range(3):
            ids = {b: f"r{b}" for b in (1, 2, 3) if base & (1 << (b - 1))}
            for t in bt.enumerate_legal_transitions(outs, base):
                bt.apply_transition_to_runners(base, ids, "BAT", t)  # must not raise


# ---- reproducibility & sampling ----
def test_sampling_is_reproducible_and_legal():
    model = _fitted()
    a = model.sample("SINGLE", 0, SECOND, np.random.default_rng(5))
    b = model.sample("SINGLE", 0, SECOND, np.random.default_rng(5))
    assert a == b
    assert bt.is_legal(0, SECOND, a)


def test_different_seed_can_produce_alternative_legal_path():
    model = _fitted()
    draws = {tuple(model.sample("SINGLE", 0, SECOND, np.random.default_rng(s))) for s in range(50)}
    assert len(draws) >= 2  # a stochastic cell yields more than one legal outcome


# ---- temporal / serialization ----
def test_temporal_seasons_recorded_and_2025_excluded_by_construction():
    model = _fitted()
    assert model.seasons == (2021, 2022, 2023)
    assert 2025 not in model.seasons  # policy is fit on development seasons only


def test_json_round_trip_is_data_only():
    model = _fitted()
    payload = model.to_dict()
    text = __import__("json").dumps(payload)  # must be JSON-serializable (no pickle)
    restored = bt.TransitionModel.from_dict(__import__("json").loads(text))
    d1 = model.distribution("SINGLE", 0, SECOND)
    d2 = restored.distribution("SINGLE", 0, SECOND)
    assert d1["transitions"][0] == d2["transitions"][0]


def test_unknown_outcome_rejected():
    model = _fitted()
    with pytest.raises(bt.TransitionModelError):
        model.distribution("NONSENSE", 0, 0)


def test_illegal_mass_rejected_by_validator():
    bad = {"transitions": [{"outsAdded": 0, "baseMaskAfter": 3, "runs": 0, "probability": 1.0}]}
    with pytest.raises(bt.TransitionModelError):
        bt.validate_distribution(bad, 0, 0)  # (0,3,0) from empty bases is illegal
