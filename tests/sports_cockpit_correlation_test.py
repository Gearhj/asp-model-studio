"""Phase 6E.5 — Data Profile EDA backend aggregates.

Proves the correlation screen is development-2023 fold-local, bounded to the continuous predictors,
surfaces real strong pairs, and that the profile exposes an IV screening threshold. No training.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_cockpit import engine as E

_HAS_VIEW = True
try:
    E._feature_view_path()
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


def test_correlation_is_fold_local_and_bounded():
    c = E.correlation_summary()
    assert c["scope"] == "FOLD_LOCAL_DEVELOPMENT_2023"
    assert len(c["features"]) == 17 and list(c["features"]) == list(E.CONTINUOUS_FEATURES)
    assert len(c["matrix"]) == 17 and all(len(row) == 17 for row in c["matrix"])
    assert c["matrix"][0][0] == 1.0  # self-correlation on the diagonal
    assert c["threshold"] == E.CORRELATION_STRONG_THRESHOLD


def test_correlation_computed_on_development_only():
    frame = E.load_frame()
    dev = frame.loc[frame["season"] == 2023]
    r_dev = float(dev["batter_avg"].corr(dev["batter_obp"]))
    c = E.correlation_summary()
    i = c["features"].index("batter_avg")
    j = c["features"].index("batter_obp")
    assert abs(c["matrix"][i][j] - round(r_dev, 4)) < 1e-6
    # all-seasons correlation differs -> proves 2024/2025 are excluded
    allr = float(frame["batter_avg"].corr(frame["batter_obp"]))
    assert abs(round(allr, 4) - c["matrix"][i][j]) > 1e-9


def test_strong_pairs_are_real():
    c = E.correlation_summary()
    pairs = {(p["a"], p["b"]) for p in c["strongPairs"]}
    assert ("batter_avg", "batter_obp") in pairs
    assert ("pitcher_era9", "pitcher_whip") in pairs
    assert c["strongPairCount"] == len(c["strongPairs"]) >= 2
    for p in c["strongPairs"]:
        assert abs(p["r"]) >= c["threshold"]
    # per-feature strongest correlate is populated
    assert c["strongest"]["batter_obp"]["feature"] == "batter_avg"


def test_profile_exposes_iv_screening_threshold():
    p = E.feature_profile()
    assert p["ivScreeningThreshold"] == E.IV_SCREENING_THRESHOLD == 0.1
    assert p["ivWeakThreshold"] == E.IV_WEAK_THRESHOLD == 0.02
    # exactly one predictor clears the notable IV bar in this governed data (context_base_mask_before)
    high = [f["name"] for f in p["features"] if f["iv"]["maxIv"] >= p["ivScreeningThreshold"]]
    assert high == ["context_base_mask_before"]
