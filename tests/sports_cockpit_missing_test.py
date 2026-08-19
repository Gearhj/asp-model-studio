"""Phase 6E.3 — missing-value analysis backend behaviour (cockpit step 05).

Proves the payload is non-empty and real, fill statistics are fold-local on development (2023) only,
method selection changes the fill, indicators apply only to continuous features with missing values,
per-season rates are descriptive (never fitted), and before/after imputation histograms share bins.
No model training is exercised.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import modeling as M

_HAS_VIEW = True
try:
    E._feature_view_path()
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


def _feat(r, name):
    return next(x for x in r["features"] if x["feature"] == name)


def test_payload_is_non_empty_and_development_scoped():
    r = M.missing_summary({"globalMethod": "median"})
    assert r["scope"] == "FOLD_LOCAL_DEVELOPMENT_2023"
    assert r["totalObservations"] == int((E.load_frame()["season"] == 2023).sum())
    assert r["featuresAnalyzed"] == 22
    assert r["continuousFeatures"] == 17 and r["categoricalFeatures"] == 5
    assert r["featuresWithMissing"] == 15  # all prior batter/pitcher rate/volume features
    assert r["totalMissing"] > 0 and len(r["features"]) == 22


def test_missing_counts_are_default_sorted_descending():
    r = M.missing_summary({"globalMethod": "median"})
    missing = [f["missing"] for f in r["features"]]
    assert missing == sorted(missing, reverse=True)
    # the most-affected feature is a pitcher prior (13.33% missing)
    assert r["features"][0]["feature"].startswith("pitcher_")


def test_method_change_changes_fill_value():
    med = _feat(M.missing_summary({"globalMethod": "median"}), "batter_avg")["fillValue"]
    mean = _feat(M.missing_summary({"globalMethod": "mean"}), "batter_avg")["fillValue"]
    const = _feat(M.missing_summary({"globalMethod": "constant"}), "batter_avg")["fillValue"]
    assert med != mean
    assert const == 0.0
    assert med is not None and mean is not None


def test_fill_statistics_are_fold_local_development_only():
    frame = E.load_frame()
    dev = frame.loc[frame["season"] == 2023, "batter_avg"].to_numpy()
    dev = dev[np.isfinite(dev)]
    # median (fold-local) matches the development-only median, not the all-seasons median
    med = _feat(M.missing_summary({"globalMethod": "median"}), "batter_avg")["fillValue"]
    assert abs(med - float(np.median(dev))) < 1e-9
    allv = frame["batter_avg"].to_numpy()
    allv = allv[np.isfinite(allv)]
    assert abs(float(np.median(allv)) - med) > 1e-12  # 2024/2025 excluded from fitting
    # mean matches development mean
    mean = _feat(M.missing_summary({"globalMethod": "mean"}), "batter_avg")["fillValue"]
    assert abs(mean - float(dev.mean())) < 1e-9


def test_most_frequent_is_development_mode():
    import pandas as pd
    frame = E.load_frame()
    dev = frame.loc[frame["season"] == 2023, "batter_avg"].to_numpy()
    dev = dev[np.isfinite(dev)]
    mf = _feat(M.missing_summary({"globalMethod": "most_frequent"}), "batter_avg")["fillValue"]
    assert abs(mf - float(pd.Series(dev).mode().iloc[0])) < 1e-9


def test_by_season_is_descriptive_and_not_used_for_fitting():
    r = M.missing_summary({"globalMethod": "median"})
    era = _feat(r, "pitcher_era9")
    assert set(era["bySeason"].keys()) == {"2023", "2024", "2025"}
    # 2024/2025 rates differ from 2023, yet the fill uses the 2023 development statistic only
    assert era["bySeason"]["2024"] != era["bySeason"]["2023"]
    frame = E.load_frame()
    dev = frame.loc[frame["season"] == 2023, "pitcher_era9"].to_numpy()
    dev = dev[np.isfinite(dev)]
    assert abs(era["fillValue"] - float(np.median(dev))) < 1e-9


def test_none_resolves_to_median_fallback():
    f = _feat(M.missing_summary({"globalMethod": "none"}), "batter_avg")
    assert f["resolvedMethod"] == "none_median_fallback"
    frame = E.load_frame()
    dev = frame.loc[frame["season"] == 2023, "batter_avg"].to_numpy()
    dev = dev[np.isfinite(dev)]
    assert abs(f["fillValue"] - float(np.median(dev))) < 1e-9  # complete matrix required


def test_indicator_applies_only_to_continuous_with_missing():
    r = M.missing_summary({"globalMethod": "median", "addIndicator": True})
    assert _feat(r, "batter_avg")["indicator"] is True          # continuous + missing
    assert _feat(r, "context_outs_before")["indicator"] is False  # categorical, no missing
    assert _feat(r, "batter_prior_missing")["indicator"] is False  # binary indicator, no missing
    off = M.missing_summary({"globalMethod": "median", "addIndicator": False})
    assert _feat(off, "batter_avg")["indicator"] is False


def test_before_after_histograms_share_bins_and_add_imputed_mass():
    r = M.missing_summary({"globalMethod": "median"})
    f = _feat(r, "batter_avg")
    assert f["beforeHistogram"] and f["afterHistogram"]
    assert [b["lo"] for b in f["beforeHistogram"]] == [b["lo"] for b in f["afterHistogram"]]
    before = sum(b["count"] for b in f["beforeHistogram"])
    after = sum(b["count"] for b in f["afterHistogram"])
    assert after - before == f["missing"]  # the imputed mass is added as a spike


def test_categorical_features_have_no_missing_or_histogram():
    r = M.missing_summary({"globalMethod": "median"})
    cat = _feat(r, "context_outs_before")
    assert cat["missing"] == 0 and cat["beforeHistogram"] is None


def test_per_feature_override_uses_existing_backend():
    r = M.missing_summary({"globalMethod": "median", "overrides": {"batter_avg": {"method": "constant"}}})
    assert _feat(r, "batter_avg")["fillValue"] == 0.0            # overridden feature
    assert _feat(r, "pitcher_era9")["resolvedMethod"] == "median"  # global still applies
