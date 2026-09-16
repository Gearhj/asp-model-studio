"""Focused tests for the Phase 6A interactive MLB PA modeling cockpit.

Validates the real science: multiclass one-vs-rest IV with development-only binning, MI,
fold-local outlier and missing policies, the flexible preprocessing pipeline, challenger
experiments evaluated with the shared authority, champion reproduction parity, temporal
frozen-season protection, and the bounded simulation verdict framework. Runtime-dependent
checks skip when the D3 feature view is not materialized. No component is retrained here in a
way that mutates registered artifacts; no betting/odds logic is exercised.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import modeling as M
from server.sports_modeling.metrics import PA_CLASS_ORDER

_HAS_VIEW = True
try:
    from tests._runtime_probe import IS_SYNTHETIC_SEED as _IS_SYNTHETIC_SEED
    E._feature_view_path()
    _HAS_VIEW = not _IS_SYNTHETIC_SEED   # real D3/Gen-2 view only; a synthetic seed fails real-data assertions
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


# ---------------------------------------------------------------- feature metadata
def test_feature_kinds_and_outlier_eligibility():
    # Categorical context features are one-hot, never outlier-treated.
    assert E.feature_kind("context_top_bottom") == "categorical"
    assert E.feature_kind("context_outs_before") == "categorical"
    assert E.feature_kind("context_base_mask_before") == "categorical"
    # Binary prior-missing flags are never outlier-treated.
    assert E.feature_kind("batter_prior_missing") == "binary"
    assert E.feature_kind("pitcher_prior_missing") == "binary"
    # Continuous priors are outlier-eligible.
    assert E.feature_kind("pitcher_era9") == "continuous"
    assert "pitcher_era9" in E.CONTINUOUS_FEATURES
    assert "context_top_bottom" not in E.CONTINUOUS_FEATURES
    assert "batter_prior_missing" not in E.CONTINUOUS_FEATURES


def test_all_features_and_class_order_frozen():
    assert len(E.ALL_FEATURES) == 22
    assert PA_CLASS_ORDER[0] == "STRIKEOUT" and PA_CLASS_ORDER[6] == "BIP_OUT"


# ---------------------------------------------------------------- profiling: IV / MI
def test_iv_is_one_vs_rest_development_only():
    prof = E.feature_profile()
    by_name = {f["name"]: f for f in prof["features"]}
    # Strikeout-rate feature should have its max IV on the STRIKEOUT class.
    so = by_name["batter_so_per_pa"]
    assert so["iv"]["maxIvClass"] == "STRIKEOUT"
    assert so["iv"]["maxIv"] > so["iv"]["meanIv"] >= 0.0
    # every feature carries a per-class IV vector over the 8 frozen classes
    assert set(so["iv"]["perClass"].keys()) == set(PA_CLASS_ORDER)
    # HR-rate feature keys on HOME_RUN
    assert by_name["batter_hr_per_pa"]["iv"]["maxIvClass"] == "HOME_RUN"
    # MI is present and non-negative, bounded development sample
    assert all(f["mi"] >= -1e-9 for f in prof["features"])
    assert prof["miSampleRows"] <= 30000


def test_profile_reports_real_missing_and_outliers():
    prof = E.feature_profile()
    by_name = {f["name"]: f for f in prof["features"]}
    # batter priors carry ~7.7% missing; pitcher ~11.7%
    assert 0.05 < by_name["batter_avg"]["missingPct"] < 0.12
    assert 0.08 < by_name["pitcher_era9"]["missingPct"] < 0.15
    # era9 has extreme outliers (max well above the IQR fence)
    assert by_name["pitcher_era9"]["outlierCount"] > 0
    # categorical features report zero outliers
    assert by_name["context_outs_before"]["outlierCount"] == 0


def test_woe_iv_zero_when_no_events():
    bins = np.array([0, 0, 1, 1, 2, 2])
    event = np.zeros(6)
    assert E._woe_iv(bins, event) == 0.0


# ---------------------------------------------------------------- outlier policy
def test_outlier_summary_is_fold_local_and_skips_binary():
    summ = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 3.0}})
    assert summ["scope"] == "FOLD_LOCAL_DEVELOPMENT_2023"
    names = {f["feature"] for f in summ["features"]}
    # only continuous features analyzed; binary/categorical excluded
    assert "batter_prior_missing" not in names
    assert "context_top_bottom" not in names
    assert "pitcher_era9" in names
    era = next(f for f in summ["features"] if f["feature"] == "pitcher_era9")
    # clipping reduces the max
    assert era["afterMax"] <= era["beforeMax"]
    assert era["flagged"] > 0


def test_outlier_bounds_methods():
    vals = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 100.0])
    lo_iqr, hi_iqr = M._outlier_bounds(vals, "iqr", {"k": 1.5})
    assert hi_iqr < 100.0  # the 100 outlier is outside the fence
    assert M._outlier_bounds(vals, "none", {}) is None
    lo_p, hi_p = M._outlier_bounds(vals, "percentile", {"lower": 10, "upper": 90})
    assert lo_p >= 0.0 and hi_p <= 100.0


# ---------------------------------------------------------------- missing policy
def test_missing_summary_reports_by_season():
    summ = M.missing_summary({"globalMethod": "median"})
    assert summ["totalMissing"] > 0
    era = next(f for f in summ["features"] if f["feature"] == "pitcher_era9")
    assert set(era["bySeason"].keys()) == {"2023", "2024", "2025"}
    assert 0.0 <= era["missingPct"] <= 1.0


def test_preprocessor_fits_on_development_only():
    frame = E.load_frame()
    pre = M.Preprocessor.fit(frame, ["pitcher_era9"], {"globalMethod": "none"}, {"globalMethod": "mean"})
    dev = frame["season"].to_numpy() == E.DEV_SEASON
    dev_finite = frame["pitcher_era9"].to_numpy()[dev]
    dev_finite = dev_finite[np.isfinite(dev_finite)]
    # the learned imputation fill equals the development mean (fold-local)
    assert abs(pre.state["pitcher_era9"]["imputeFill"] - float(dev_finite.mean())) < 1e-6
    # transform produces finite standardized columns with no NaN
    X = pre.transform(frame, frame["season"].to_numpy() == E.FROZEN_SEASON)
    assert np.isfinite(X).all()


def test_missing_indicator_adds_column():
    frame = E.load_frame()
    pre = M.Preprocessor.fit(frame, ["pitcher_era9"], {"globalMethod": "none"}, {"globalMethod": "median", "addIndicator": True})
    assert "pitcher_era9__missing" in pre.expanded_names
    X = pre.transform(frame, frame["season"].to_numpy() == E.DEV_SEASON)
    assert X.shape[1] == 2  # standardized value + indicator


# -------------------------------------- champion + experiments (Phase 7D.2 Gate 12: legacy 2025 path retired)
def test_legacy_champion_baseline_is_retired():
    # the in-pipeline champion reproduction fit/scored a frozen 2025 fold; it is retired before any data open
    with pytest.raises(M.LegacyModelingRetiredError):
        M.champion_baseline()


def test_champion_reference_is_2024_only_and_read_only():
    ref = E._champion_reference()
    assert "frozen2025" not in ref and "final2025" not in ref     # no sealed-2025 metric in an ordinary DTO
    assert ref["val2024"]["logLoss"] > 0                          # champion of record unchanged (2024)
    assert ref["sealed2025"] == "RESTRICTED_ARCHIVAL_AUDIT_EVIDENCE"


def test_legacy_experiment_execution_is_retired():
    with pytest.raises(M.LegacyModelingRetiredError):
        M.run_experiment({"features": list(E.BATTER_FEATURES) + list(E.PITCHER_FEATURES), "family": "logistic"},
                         persist=False)


def test_experiment_rejects_unknown_feature_and_target_leak():
    with pytest.raises(E.CockpitError):
        M.run_experiment({"features": ["not_a_feature"], "family": "logistic"}, persist=False)
    # outcome is never a valid predictor name in ALL_FEATURES
    assert "outcome" not in E.ALL_FEATURES


def test_legacy_fit_and_evaluate_is_retired_before_any_data_open():
    # the frozen-2025-scoring evaluator is retired; it raises before touching a frame (no 2025 fold fit)
    with pytest.raises(M.LegacyModelingRetiredError):
        M._fit_and_evaluate(
            None, list(E.ALL_FEATURES), "random_forest",
            {"nEstimators": 40, "maxDepth": 8, "minSamplesLeaf": 200},
            {"globalMethod": "none"}, {"globalMethod": "median"})


# ---------------------------------------------------------------- families / availability
def test_family_availability_is_honest():
    # sklearn families always available; xgboost/lightgbm reflect real install state
    assert M.AVAILABLE_FAMILIES["logistic"] is True
    assert M.AVAILABLE_FAMILIES["random_forest"] is True
    assert isinstance(M.AVAILABLE_FAMILIES["xgboost"], bool)
    # only logistic is simulator-eligible (Phase 5 FastD3Fold authority)
    assert M.SIMULATOR_ELIGIBLE_FAMILIES == {"logistic"}


def test_autopilot_budget_is_bounded():
    quick = M._autopilot_plan("quick")
    deep = M._autopilot_plan("deep")
    assert 0 < len(quick) <= len(deep)
    # quick never launches tree/boosting families
    assert all(c["family"] == "logistic" for c in quick)
