"""Focused tests for the Phase 4E E1/E2 incremental-signal feature-ablation study.

These exercise the frozen invariants (branch composition, population alignment, fixed
C=0.05, class order, no-E2-without-E1, no target leakage, fold masks, whole-game
bootstrap, decision-state logic) on small synthetic inputs -- no full 549k run required.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_modeling.metrics import PA_CLASS_ORDER, encode_labels
from server.sports_modeling.training import TrainingArrays
from server.sports_phase4 import incremental_signal_study as study


def _synthetic_arrays(seed: int = 7) -> tuple[TrainingArrays, list[str], list[str]]:
    rng = np.random.default_rng(seed)
    per_season = 200
    seasons = np.repeat([2023, 2024, 2025], per_season).astype(np.int64)
    n = seasons.size
    # ensure every class appears in every season
    labels = np.empty(n, dtype=object)
    for s_index in range(3):
        block = slice(s_index * per_season, (s_index + 1) * per_season)
        base = np.array(list(PA_CLASS_ORDER) * (per_season // len(PA_CLASS_ORDER) + 1), dtype=object)[:per_season]
        labels[block] = rng.permutation(base)
    e1_features = ["e1_a", "e1_b"]
    e2_features = ["e2_a"]
    feature_values = {}
    for name in study.D3_FEATURES + tuple(e1_features) + tuple(e2_features):
        feature_values[name] = rng.normal(size=n)
    # give categorical context features valid domains
    feature_values["context_top_bottom"] = rng.integers(0, 2, size=n).astype(np.float64)
    feature_values["context_outs_before"] = rng.integers(0, 3, size=n).astype(np.float64)
    feature_values["context_base_mask_before"] = rng.integers(0, 8, size=n).astype(np.float64)
    game_ids = np.array([f"g{(i // 4) % 60}" for i in range(n)], dtype=object)
    arrays = TrainingArrays(
        feature_values=feature_values,
        labels=labels,
        encoded_labels=encode_labels(labels),
        seasons=seasons,
        game_dates=np.array([f"2023-01-{(i % 27) + 1:02d}" for i in range(n)], dtype=object),
        game_ids=game_ids,
        plate_appearance_ids=np.array([f"pa{i}" for i in range(n)], dtype=object),
    )
    return arrays, e1_features, e2_features


def test_fixed_c_is_the_frozen_d3_regularization():
    assert study.FIXED_C == 0.05


def test_branch_feature_composition_is_nested_a_subset_b_subset_c():
    e1 = ["e1_a", "e1_b"]
    e2 = ["e2_a"]
    a = study.branch_feature_names("A", e1, e2)
    b = study.branch_feature_names("B", e1, e2)
    c = study.branch_feature_names("C", e1, e2)
    assert a == study.D3_FEATURES
    assert b == tuple(a) + tuple(e1)
    assert c == tuple(b) + tuple(e2)
    # no E2 without E1: every E1 feature present in C, E2 only appears after E1
    assert set(e1).issubset(set(c))
    assert set(e2).issubset(set(c))
    assert set(e2).isdisjoint(set(b))


def test_branch_features_never_include_the_target_or_identity():
    e1 = ["e1_a"]
    e2 = ["e2_a"]
    for branch in ("A", "B", "C"):
        names = study.branch_feature_names(branch, e1, e2)
        assert "outcome" not in names
        assert "plate_appearance_id" not in names
        assert "game_id" not in names
        assert len(set(names)) == len(names)


def test_unknown_branch_rejected():
    with pytest.raises(study.IncrementalStudyError):
        study.branch_feature_names("D", [], [])


def test_train_branch_uses_rolling_origin_folds_and_fixed_c():
    arrays, e1, e2 = _synthetic_arrays()
    names = study.branch_feature_names("B", e1, e2)
    folds = study.train_branch(arrays, "B", names, max_iter=5000)
    # two rolling-origin folds only
    assert set(folds.probabilities) == {2024, 2025}
    # probabilities are proper distributions over the frozen class order
    for season in (2024, 2025):
        probs = folds.probabilities[season]
        assert probs.shape[1] == len(PA_CLASS_ORDER)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-9)
        assert folds.metrics[season]["classOrder"] == list(PA_CLASS_ORDER)


def test_population_alignment_identical_rows_across_branches():
    arrays, e1, e2 = _synthetic_arrays()
    branches = {
        b: study.train_branch(arrays, b, study.branch_feature_names(b, e1, e2), max_iter=5000)
        for b in ("A", "B", "C")
    }
    labels_by_season = {s: arrays.labels[arrays.seasons == s] for s in (2024, 2025)}
    # every branch evaluates the same number of rows per season (same population)
    for season in (2024, 2025):
        counts = {b: branches[b].probabilities[season].shape[0] for b in ("A", "B", "C")}
        assert len(set(counts.values())) == 1
        assert counts["A"] == int((arrays.seasons == season).sum())
    table = study.incremental_table(branches, labels_by_season)
    assert {r["validationSeason"] for r in table["rows"]} == {2024, 2025}


def test_bootstrap_uses_whole_game_clusters():
    arrays, e1, e2 = _synthetic_arrays()
    branches = {
        b: study.train_branch(arrays, b, study.branch_feature_names(b, e1, e2), max_iter=5000)
        for b in ("A", "B", "C")
    }
    labels_by_season = {s: arrays.labels[arrays.seasons == s] for s in (2024, 2025)}
    game_ids_by_season = {s: arrays.game_ids[arrays.seasons == s] for s in (2024, 2025)}
    boot = study.bootstrap_comparisons(branches, labels_by_season, game_ids_by_season, n_resamples=25)
    assert {(r["selected"], r["comparator"]) for r in boot} == {("B", "A"), ("C", "B"), ("C", "A")}
    for row in boot:
        assert row["clusterUnit"] == "game_id"
        assert 0.0 <= row["logLoss"]["probabilitySelectedBetter"] <= 1.0


def _incremental_stub(rel_ba, rel_cb):
    def row(season, ba, cb):
        return {
            "validationSeason": season,
            "deltas": {
                "B_minus_A": {"relativeLogLoss": ba},
                "C_minus_B": {"relativeLogLoss": cb},
                "C_minus_A": {"relativeLogLoss": ba + cb},
            },
        }
    return {"rows": [row(2024, rel_ba[2024], rel_cb[2024]), row(2025, rel_ba[2025], rel_cb[2025])]}


def _bootstrap_stub(p_ba, p_cb):
    out = []
    for season in (2024, 2025):
        out.append({"validationSeason": season, "selected": "B", "comparator": "A",
                    "logLoss": {"probabilitySelectedBetter": p_ba[season]}})
        out.append({"validationSeason": season, "selected": "C", "comparator": "B",
                    "logLoss": {"probabilitySelectedBetter": p_cb[season]}})
    return out


def _strikeout_stub(ba_delta_2024=-0.01, ba_delta_2025=-0.01):
    return {"seasons": {
        "2024": {"classConditionalLogLossDelta": {"B_minus_A": ba_delta_2024}},
        "2025": {"classConditionalLogLossDelta": {"B_minus_A": ba_delta_2025}},
    }}


# ---------------- Gate 10/25: decide_feature_value is RETIRED (it used sealed 2025 in selection) ----------
def test_decide_feature_value_is_retired_for_ordinary_research():
    """Ordinary invocation fails closed (before any 2025 open) and points to the 2024-only replacement."""
    inc = _incremental_stub({2024: 0.01, 2025: 0.012}, {2024: 0.006, 2025: 0.007})
    boot = _bootstrap_stub({2024: 0.99, 2025: 0.99}, {2024: 0.99, 2025: 0.99})
    with pytest.raises(study.IncrementalStudyError) as exc:
        study.decide_feature_value(inc, boot, _strikeout_stub())
    assert "run_feature_family_ablation" in str(exc.value)


@pytest.mark.parametrize("cap", [None, "SEALED_TARGET_DATA_READ", "RESEARCH_OBJECT_READ", "1", "true"])
def test_no_environment_capability_re_enables_2025_selection(monkeypatch, cap):
    """No user-settable environment string re-enables the retired sealed-2025 selection path."""
    if cap is None:
        monkeypatch.delenv("ASP_ARCHIVAL_AUDIT_CAPABILITY", raising=False)
    else:
        monkeypatch.setenv("ASP_ARCHIVAL_AUDIT_CAPABILITY", cap)
    inc = _incremental_stub({2024: 0.01, 2025: 0.012}, {2024: 0.006, 2025: 0.007})
    boot = _bootstrap_stub({2024: 0.99, 2025: 0.99}, {2024: 0.99, 2025: 0.99})
    with pytest.raises(study.IncrementalStudyError):
        study.decide_feature_value(inc, boot, _strikeout_stub())


def test_no_selfgrant_capability_string_in_module_source():
    """The module must not read a user-settable capability env var as sealed authorization."""
    import inspect
    assert "ASP_ARCHIVAL_AUDIT_CAPABILITY" not in inspect.getsource(study)


def test_archival_decision_impl_is_private_and_not_exported():
    assert "decide_feature_value" in study.__all__
    assert "_decide_feature_value_impl" not in study.__all__
    assert hasattr(study, "_decide_feature_value_impl")


# The pure decision-tree math is retained (archival impl) and covered on SYNTHETIC stubs only — no real
# sealed 2025 data is ever read, and the public ordinary entry stays retired (above). This preserves the
# decision-tree regression signal without restoring 2025-in-selection behavior.
def test_archival_impl_confirmed_when_both_years_decisive_and_meaningful():
    inc = _incremental_stub({2024: 0.01, 2025: 0.012}, {2024: 0.006, 2025: 0.007})
    boot = _bootstrap_stub({2024: 0.99, 2025: 0.99}, {2024: 0.99, 2025: 0.99})
    decision = study._decide_feature_value_impl(inc, boot, _strikeout_stub())
    assert decision["e1"]["decision"] == "E1_PREDICTIVE_VALUE_CONFIRMED"
    assert decision["e2"]["decision"] == "E2_INCREMENTAL_VALUE_CONFIRMED"
    path = study.next_step_path(decision)
    assert path["recommendedPath"] == "PATH_1"
    assert path["archetypesShouldProceed"] is True


def test_archival_impl_negative_when_worse_both_years():
    inc = _incremental_stub({2024: -0.01, 2025: -0.02}, {2024: -0.001, 2025: -0.002})
    boot = _bootstrap_stub({2024: 0.01, 2025: 0.02}, {2024: 0.3, 2025: 0.3})
    decision = study._decide_feature_value_impl(inc, boot, _strikeout_stub(0.01, 0.01))
    assert decision["e1"]["decision"] == "E1_PREDICTIVE_VALUE_NEGATIVE"
    assert decision["e2"]["decision"] == "E2_INCREMENTAL_VALUE_NEGATIVE"


def test_archival_impl_marginal_when_decisive_but_below_small_band():
    inc = _incremental_stub({2024: 0.0005, 2025: 0.0006}, {2024: 0.0002, 2025: 0.0003})
    boot = _bootstrap_stub({2024: 0.99, 2025: 0.99}, {2024: 0.99, 2025: 0.99})
    decision = study._decide_feature_value_impl(inc, boot, _strikeout_stub())
    assert decision["e1"]["decision"] == "E1_PREDICTIVE_VALUE_MARGINAL"
    assert study.next_step_path(decision)["recommendedPath"] == "PATH_1"


def test_archival_impl_path_2_when_e1_helps_but_e2_not_confirmed():
    inc = _incremental_stub({2024: 0.01, 2025: 0.012}, {2024: 0.0, 2025: -0.001})
    boot = _bootstrap_stub({2024: 0.99, 2025: 0.99}, {2024: 0.4, 2025: 0.4})
    decision = study._decide_feature_value_impl(inc, boot, _strikeout_stub())
    assert decision["e1"]["decision"] == "E1_PREDICTIVE_VALUE_CONFIRMED"
    assert decision["e2"]["decision"] in ("E2_INCREMENTAL_VALUE_NOT_CONFIRMED", "E2_INCREMENTAL_VALUE_NEGATIVE")
    path = study.next_step_path(decision)
    assert path["recommendedPath"] == "PATH_2"
    assert path["algorithmTournamentShouldProceed"] is True


def test_archival_impl_path_4_when_only_strikeout_improves():
    inc = _incremental_stub({2024: 0.01, 2025: -0.005}, {2024: -0.001, 2025: -0.001})
    boot = _bootstrap_stub({2024: 0.99, 2025: 0.2}, {2024: 0.3, 2025: 0.3})
    decision = study._decide_feature_value_impl(inc, boot, _strikeout_stub(-0.02, -0.02))
    assert decision["e1"]["decision"] == "E1_PREDICTIVE_VALUE_NOT_CONFIRMED"
    assert study.next_step_path(decision)["recommendedPath"] == "PATH_4"


def test_research_only_constants_do_not_imply_promotion():
    assert study.STUDY_CONTRACT_NAME == "MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_V1"
    assert study.D3_FEATURES[:5] == (
        "context_inning", "context_top_bottom", "context_outs_before",
        "context_base_mask_before", "context_batting_score_diff_before",
    )
