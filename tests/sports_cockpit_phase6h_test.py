"""Phase 6H — overnight scientist-acceptance guarantees, codified as bounded fast tests.

These assert the scientific invariants that the (much larger) overnight campaign exercises at scale:
model-family availability, config-hash identity + preprocessing propagation, fold-local dev-only
preprocessing, frozen-2025 never in any training fold, engineered-feature materialization/validation,
segmentation decision formulae, autopilot bounded + validation-only selection, and multiclass metric
integrity. Heavy families (RF/XGB/LGBM/MLP/SVM) are asserted available but not trained here to keep
the suite fast; the campaign trains them.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import modeling as M
from server.sports_cockpit import segmentation as SEG
from server.sports_cockpit import features_builder as FB
from server.sports_cockpit.engine import CockpitError
from server.sports_modeling.metrics import encode_labels, PA_CLASS_ORDER

_HAS_VIEW = True
try:
    E._feature_view_path()
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")

LOG = {"features": list(M.ALL_FEATURES), "family": "logistic", "hyperparameters": {"C": 1.0, "maxIter": 2000}}


# ---------------- model families ----------------
def test_all_eight_model_families_registered_and_boosters_installed():
    for fam in ("logistic", "random_forest", "extra_trees", "hist_gradient_boosting", "mlp", "xgboost", "lightgbm", "svm"):
        assert fam in M.AVAILABLE_FAMILIES
    assert M.AVAILABLE_FAMILIES["xgboost"] and M.AVAILABLE_FAMILIES["lightgbm"]
    assert M.SIMULATOR_ELIGIBLE_FAMILIES == {"logistic"}  # only the multinomial-logit authority feeds the simulator


# ---------------- config identity + preprocessing propagation ----------------
def test_distinct_configs_legacy_execution_is_retired():
    # Phase 7D.2 Gate 12 — legacy in-process experiment execution (which evaluated a frozen 2025 fold) is
    # retired before any data open; distinct-config training runs through the canonical gen3_authority path.
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_experiment({**LOG, "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "median"}}, persist=False)


def test_preprocessor_is_fold_local_and_frozen_transform_never_mutates_state():
    frame = E.load_frame()
    pre = M.Preprocessor.fit(frame, ["pitcher_era9"], {"globalMethod": "iqr", "params": {"k": 1.5}}, {"globalMethod": "median"})
    dev = frame.loc[frame["season"] == E.DEV_SEASON, "pitcher_era9"].to_numpy()
    dev = dev[np.isfinite(dev)]
    assert abs(pre.state["pitcher_era9"]["imputeFill"] - float(np.median(dev))) < 1e-6   # dev-only fill
    import json
    before = json.dumps(pre.state, sort_keys=True, default=str)
    Xf = pre.transform(frame, frame["season"].to_numpy() == E.FROZEN_SEASON)
    assert json.dumps(pre.state, sort_keys=True, default=str) == before                  # frozen never re-fits
    assert np.isfinite(Xf).all()


# ---------------- temporal integrity ----------------
def _training_seasons(fold):
    tr = fold.get("training", {})
    seasons = list(tr.get("seasons", []))
    if tr.get("season") is not None:
        seasons.append(tr["season"])
    return seasons


def test_frozen_2025_is_never_a_training_fold_in_any_policy():
    for policy in ("SEASON_HOLDOUT", "ROLLING_ORIGIN", "EXPANDING_WINDOW", "DATE_HOLDOUT", "RANDOM"):
        p = E.temporal_split_preview(policy)
        for fold in p.get("folds", []):
            assert 2025 not in _training_seasons(fold), f"{policy} leaks 2025 into training"
            val = fold.get("validation", {})
            if val.get("season") == 2025:
                assert val.get("role") == "FROZEN_EVAL_ONLY"
    assert E.temporal_split_preview("RANDOM")["researchOnly"] is True


def test_date_holdout_partitions_only_development_2023():
    for d in ("2023-05-01", "2023-07-01", "2023-09-01"):
        f = E.temporal_split_preview("DATE_HOLDOUT", d)["folds"][0]
        assert f["training"]["rows"] + f["validation"]["rows"] == 184104
        assert f["training"]["rows"] > 0 and f["validation"]["rows"] > 0


# ---------------- feature engineering ----------------
def test_every_engineered_kind_materializes_and_profiles():
    frame = E.load_frame()
    specs = [
        {"name": "e_arith", "kind": "arithmetic", "inputs": ["batter_obp", "batter_slg"], "params": {"op": "add"}},
        {"name": "e_ratio", "kind": "ratio", "inputs": ["batter_so_per_pa", "batter_bb_hbp_per_pa"]},
        {"name": "e_inter", "kind": "interaction", "inputs": ["batter_slg", "batter_hr_per_pa"]},
        {"name": "e_log", "kind": "log", "inputs": ["batter_log1p_pa"]},
        {"name": "e_pow", "kind": "power", "inputs": ["batter_slg"], "params": {"exponent": 2.0}},
        {"name": "e_bin", "kind": "bin", "inputs": ["pitcher_era9"], "params": {"bins": 5}},
        {"name": "e_ind", "kind": "indicator", "inputs": ["batter_hr_per_pa"], "params": {"threshold": 0.03}},
        {"name": "e_cal", "kind": "calendar", "params": {"subkind": "month"}},
    ]
    dev_mask = frame["season"].to_numpy() == E.DEV_SEASON
    for s in specs:
        col = FB.materialize(frame, s, dev_mask)
        assert col.shape[0] == len(frame)
        p = FB.profile_engineered(s)
        assert "maxIv" in p["iv"] and "mi" in p and "histogram" in p
    # arithmetic add equals its inputs' sum
    add = FB.materialize(frame, specs[0], dev_mask)
    assert np.allclose(add, frame["batter_obp"].to_numpy() + frame["batter_slg"].to_numpy(), equal_nan=True)
    # indicator is binary
    assert set(np.unique(FB.materialize(frame, specs[6], dev_mask))).issubset({0.0, 1.0})


def test_feature_builder_rejects_invalid_specs():
    frame = E.load_frame()
    with pytest.raises(CockpitError):
        FB.materialize(frame, {"kind": "ratio", "inputs": ["batter_obp"]})          # needs 2 inputs
    with pytest.raises(CockpitError):
        FB.materialize(frame, {"kind": "log", "inputs": ["not_a_column"]})           # unknown input
    with pytest.raises(CockpitError):
        FB.apply_engineered(frame, [{"name": "batter_obp", "kind": "log", "inputs": ["batter_slg"]}])  # name collision
    with pytest.raises(CockpitError):
        M.run_experiment({"features": ["not_a_feature"], "family": "logistic"}, persist=False)  # unknown feature
    with pytest.raises(CockpitError):
        M.run_experiment({"features": list(M.ALL_FEATURES), "family": "banana"}, persist=False)  # unknown family


def test_legacy_ablation_execution_is_retired():
    # Phase 7D.2 Gate 12 — the legacy in-process ablation (frozen-2025 scoring) is retired; the canonical
    # 2024-only feature-family ablation is gen3_authority.run_feature_family_ablation.
    base = {**LOG, "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "median"}}
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_ablation({"baseConfig": base, "addEngineered": [
            {"name": "e_ratio", "kind": "ratio", "inputs": ["batter_so_per_pa", "batter_bb_hbp_per_pa"]}]})


def test_date_holdout_rejects_invalid_or_out_of_window_dates():
    # Phase 6H defect: an invalid boundary date previously returned a degenerate fold (val rows == 0)
    # instead of failing clearly. It must now raise for non-dates and dates outside the 2023 dev window.
    for bad in ("not-a-date", "2024-07-01", "2022-01-01"):
        with pytest.raises(CockpitError):
            E.temporal_split_preview("DATE_HOLDOUT", bad)
    f = E.temporal_split_preview("DATE_HOLDOUT", "2023-07-01")["folds"][0]
    assert f["training"]["rows"] > 0 and f["validation"]["rows"] > 0


# ---------------- segmentation guidance formulae ----------------
def test_kmeans_recommendedK_equals_documented_argmax_score():
    k = SEG.run_kmeans("BATTERS", [], 2, 8)
    assert abs(sum(k["scoreWeights"].values()) - 1.0) < 1e-9
    assert k["recommendedK"] == max(k["results"], key=lambda r: r["explorScore"])["k"]
    for r in k["results"]:
        recomputed = sum(k["scoreWeights"][c] * r["scoreComponents"][c] for c in k["scoreWeights"])
        assert abs(r["explorScore"] - round(recomputed, 3)) < 1e-6


def test_dbscan_noise_is_cluster_minus_one_and_has_recommendation():
    d = SEG.run_dbscan("PITCHERS", [], None, None)
    labels = {pt["cluster"] for pt in d["points"]}
    assert d["noise"] == 0 or -1 in labels                      # noise never forced into an archetype
    assert d["recommendation"] in {"PLAUSIBLE_DENSITY_STRUCTURE", "MOSTLY_ONE_CLUSTER_PLUS_OUTLIERS",
                                   "FRAGMENTED_UNSTABLE", "ONE_GIANT_CLUSTER", "EXCESSIVE_NOISE"}


def test_grid_quality_score_matches_formula_and_is_ranked():
    g = SEG.grid_guidance("BATTERS")
    scores = [s["gridQualityScore"] for s in g["suggestions"]]
    assert scores == sorted(scores, reverse=True)
    top = g["suggestions"][0]
    recomputed = sum(g["scoreWeights"][c] * top["components"][c] for c in g["scoreWeights"])
    assert abs(top["gridQualityScore"] - round(recomputed, 3)) < 1e-6


# ---------------- autopilot ----------------
def test_legacy_autopilot_is_retired():
    # Phase 7D.2 Gate 12 — the legacy in-process autopilot is retired; the canonical bounded suite is
    # gen3_authority.run_authorized_suite (2024-only validation; 2025 sealed).
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_autopilot({"features": list(M.ALL_FEATURES)}, budget="quick", persist=False)


# ---------------- metrics integrity ----------------
def test_legacy_fit_and_evaluate_is_retired():
    # Phase 7D.2 Gate 12 — the frozen-2025-scoring evaluator is retired; the canonical run path recomputes
    # 2024 validation probabilities independently from the immutable evidence bundle (gen3_authority).
    with pytest.raises(M.LegacyModelingRetiredError):
        M._fit_and_evaluate(E.load_frame(), list(M.ALL_FEATURES), "logistic", {"C": 1.0, "maxIter": 2000},
                            {"globalMethod": "none"}, {"globalMethod": "median"})


def test_target_and_identifier_columns_are_never_predictors():
    assert "outcome" not in M.ALL_FEATURES
    for ident in ("game_id", "batter_id", "pitcher_id", "game_pk", "player_id"):
        assert ident not in M.ALL_FEATURES
