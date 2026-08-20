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
def test_distinct_configs_yield_distinct_ids_and_indicators_expand_matrix():
    a = M.run_experiment({**LOG, "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "median"}}, persist=False)
    b = M.run_experiment({**LOG, "outlierPolicy": {"globalMethod": "iqr", "params": {"k": 1.5}},
                          "missingPolicy": {"globalMethod": "median", "addIndicator": True}}, persist=False)
    assert a["experimentId"] != b["experimentId"]                       # config-hash identity
    assert b["expandedFeatureCount"] > a["expandedFeatureCount"]        # missing indicators reach the estimator
    for r in (a, b):
        assert r["leakageGuards"]["frozenSeasonExcludedFromFitting"] is True
        assert r["leakageGuards"]["foldLocalPreprocessing"] is True
        assert r["leakageGuards"]["targetColumnNeverAFeature"] is True
        assert r["metrics"]["val2024"]["rowCount"] == 182449            # evaluated on 2024
        assert r["metrics"]["frozen2025"]["rowCount"] == 182926         # frozen evaluated (not fit)


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


def test_ablation_is_a_controlled_base_vs_engineered_comparison():
    base = {**LOG, "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "median"}}
    a = M.run_ablation({"baseConfig": base, "addEngineered": [
        {"name": "e_ratio", "kind": "ratio", "inputs": ["batter_so_per_pa", "batter_bb_hbp_per_pa"]}]})
    assert a["challenger"]["features"] == a["control"]["features"] + 1
    assert a["verdict"] in {"VALUE_CONFIRMED", "VALUE_MARGINAL", "NEGATIVE_VALUE", "NO_MATERIAL_VALUE"}


def test_ablation_uses_engineered_feature_from_specs_only_and_dedupes_names():
    # Phase 6H defect: passing addEngineered (specs) without addFeatures (names) previously left the
    # engineered column materialized-but-unused (challenger == control, delta 0). It must now be selected.
    base = {**LOG, "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "median"}}
    spec = {"name": "e_inter", "kind": "interaction", "inputs": ["batter_slg", "batter_hr_per_pa"]}
    spec_only = M.run_ablation({"baseConfig": base, "addEngineered": [spec]})
    assert spec_only["challenger"]["features"] == spec_only["control"]["features"] + 1
    # frontend passes BOTH addFeatures (names) and addEngineered (specs) — must not double-count
    both = M.run_ablation({"baseConfig": base, "addFeatures": [spec["name"]], "addEngineered": [spec]})
    assert both["challenger"]["features"] == both["control"]["features"] + 1


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
def test_autopilot_quick_is_bounded_and_selects_on_validation_only():
    ap = M.run_autopilot({"features": list(M.ALL_FEATURES)}, budget="quick", persist=False)
    assert ap["candidateCount"] == 2 and ap["budget"] == "quick"            # bounded plan
    assert ap["best"] is not None
    assert any("2024 validation only" in lim for lim in ap["limitations"])   # frozen never selects
    ok = [c for c in ap["candidates"] if c["status"] == "COMPLETED"]
    assert ap["best"]["val2024"]["logLoss"] == min(c["val2024"]["logLoss"] for c in ok)


# ---------------- metrics integrity ----------------
def test_probabilities_sum_to_one_over_eight_classes_and_metrics_reproduce():
    frame = E.load_frame()
    res = M._fit_and_evaluate(frame, list(M.ALL_FEATURES), "logistic", {"C": 1.0, "maxIter": 2000},
                              {"globalMethod": "none"}, {"globalMethod": "median"})
    val_mask = frame["season"].to_numpy() == E.VAL_SEASON
    proba = M._predict_proba_aligned(res["_estimator"], res["_preprocessor"].transform(frame, val_mask))
    assert proba.shape[1] == 8 == len(PA_CLASS_ORDER)
    assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-6)
    enc = encode_labels(frame.loc[val_mask, "outcome"].to_numpy())
    ind_ll = float(np.mean(-np.log(np.clip(proba[np.arange(len(enc)), enc], 1e-15, 1))))
    assert abs(res["val2024"]["logLoss"] - ind_ll) < 1e-4                     # engine log loss reproduces
    assert abs(res["val2024"]["top1Accuracy"] - float((proba.argmax(1) == enc).mean())) < 1e-6


def test_target_and_identifier_columns_are_never_predictors():
    assert "outcome" not in M.ALL_FEATURES
    for ident in ("game_id", "batter_id", "pitcher_id", "game_pk", "player_id"):
        assert ident not in M.ALL_FEATURES
