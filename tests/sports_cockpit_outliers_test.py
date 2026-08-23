"""Phase 6E.2 — outlier analysis backend behaviour (cockpit step 04).

Proves the reactive per-method calculation is real, fold-local on development (2023) only, method
selection changes counts and thresholds, Winsorize exposes true percentile bounds, None leaves the
distribution unchanged, and before/after histograms share bins. No model training is exercised.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import modeling as M

_HAS_VIEW = True
try:
    from tests._runtime_probe import IS_SYNTHETIC_SEED as _IS_SYNTHETIC_SEED
    E._feature_view_path()
    _HAS_VIEW = not _IS_SYNTHETIC_SEED   # real D3/Gen-2 view only; a synthetic seed fails real-data assertions
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


def _bounds(r, name):
    return next(x for x in r["features"] if x["feature"] == name)["bounds"]


def test_analyzed_features_are_continuous_only():
    r = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 1.5}})
    assert r["featuresAnalyzed"] == 17
    names = {f["feature"] for f in r["features"]}
    assert "context_base_mask_before" not in names   # categorical — never capped
    assert "batter_prior_missing" not in names       # binary indicator — never capped
    assert "batter_obp" in names


def test_default_sort_is_outlier_count_descending():
    r = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 1.5}})
    flagged = [f["flagged"] for f in r["features"]]
    assert flagged == sorted(flagged, reverse=True)


def test_method_change_changes_counts_and_thresholds():
    iqr3 = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 3.0}})
    z3 = M.outlier_summary({"globalMethod": "zscore", "params": {"k": 3.0}})
    win = M.outlier_summary({"globalMethod": "percentile", "params": {"lower": 1.0, "upper": 99.0}})
    # counts differ across methods (real, distinct calculations)
    assert iqr3["totalFlagged"] != z3["totalFlagged"]
    assert iqr3["totalFlagged"] != win["totalFlagged"]
    # thresholds differ per method for the same feature
    assert _bounds(iqr3, "batter_obp") != _bounds(z3, "batter_obp")
    assert _bounds(iqr3, "batter_obp") != _bounds(win, "batter_obp")


def test_iqr_multiplier_changes_the_result():
    k15 = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 1.5}})
    k30 = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 3.0}})
    assert k15["totalFlagged"] > k30["totalFlagged"]  # a wider fence flags fewer
    assert _bounds(k15, "batter_obp") != _bounds(k30, "batter_obp")


def test_thresholds_are_fold_local_development_2023_only():
    frame = E.load_frame()
    dev = frame.loc[frame["season"] == 2023, "batter_obp"].to_numpy()
    dev = dev[np.isfinite(dev)]
    q1, q3 = np.percentile(dev, [25, 75])
    iqr = q3 - q1
    exp_lo, exp_hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    r = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 1.5}})
    b = _bounds(r, "batter_obp")
    assert abs(b["lower"] - exp_lo) < 1e-9 and abs(b["upper"] - exp_hi) < 1e-9
    assert r["scope"] == "FOLD_LOCAL_DEVELOPMENT_2023"
    assert r["totalObservations"] == int((frame["season"] == 2023).sum())
    # bounds computed over ALL seasons would differ -> proves 2024/2025 are excluded from fitting
    allv = frame["batter_obp"].to_numpy()
    allv = allv[np.isfinite(allv)]
    aq1, aq3 = np.percentile(allv, [25, 75])
    aiqr = aq3 - aq1
    assert abs((aq1 - 1.5 * aiqr) - exp_lo) > 1e-9 or abs((aq3 + 1.5 * aiqr) - exp_hi) > 1e-9


def test_winsorize_exposes_actual_percentile_bounds():
    frame = E.load_frame()
    dev = frame.loc[frame["season"] == 2023, "batter_obp"].to_numpy()
    dev = dev[np.isfinite(dev)]
    r = M.outlier_summary({"globalMethod": "percentile", "params": {"lower": 1.0, "upper": 99.0}})
    b = _bounds(r, "batter_obp")
    assert abs(b["lower"] - float(np.percentile(dev, 1.0))) < 1e-9
    assert abs(b["upper"] - float(np.percentile(dev, 99.0))) < 1e-9


def test_none_leaves_distribution_unchanged():
    r = M.outlier_summary({"globalMethod": "none"})
    assert r["totalFlagged"] == 0
    f = r["features"][0]
    assert f["bounds"] is None and f["method"] == "none"
    assert f["beforeHistogram"] == f["afterHistogram"]  # untreated -> identical


def test_before_after_histograms_share_bins():
    r = M.outlier_summary({"globalMethod": "iqr", "params": {"k": 1.5}})
    f = next(x for x in r["features"] if x["flagged"] > 0)
    assert [b["lo"] for b in f["beforeHistogram"]] == [b["lo"] for b in f["afterHistogram"]]
    assert [b["hi"] for b in f["beforeHistogram"]] == [b["hi"] for b in f["afterHistogram"]]
    # after treatment caps values, so the boundary bins gain mass -> distributions are not identical
    assert f["beforeHistogram"] != f["afterHistogram"]


def test_per_feature_override_uses_existing_backend():
    # global IQR, but batter_obp overridden to None -> only that feature is untreated.
    r = M.outlier_summary({
        "globalMethod": "iqr", "params": {"k": 1.5},
        "overrides": {"batter_obp": {"method": "none"}},
    })
    obp = next(x for x in r["features"] if x["feature"] == "batter_obp")
    assert obp["bounds"] is None and obp["flagged"] == 0
    other = next(x for x in r["features"] if x["feature"] == "batter_log1p_pa")
    assert other["bounds"] is not None  # global policy still applies elsewhere
