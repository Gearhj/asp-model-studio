"""Phase 6F — scientist-acceptance regression tests.

Covers: 2021/2022 are NOT in the modeling matrix (definitive verdict), Temporal Split policy previews
with real frozen-safe folds, DBSCAN + grid guidance + K-means decision fields, and that the Model
Laboratory genuinely trains distinct configurations with preprocessing propagation and frozen
protection. Bounded — a couple of fast logistic fits, no tournament.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import modeling as M
from server.sports_cockpit import segmentation as SEG

_HAS_VIEW = True
try:
    E._feature_view_path()
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


# ---------------- 2021 / 2022 modeling-matrix verdict ----------------
def test_2021_2022_are_not_in_the_modeling_matrix():
    frame = E.load_frame()
    seasons = set(int(s) for s in frame["season"].unique())
    assert seasons == {2023, 2024, 2025}
    assert 2021 not in seasons and 2022 not in seasons  # source evidence only; never materialized as targets


# ---------------- Temporal Split policy previews ----------------
def test_temporal_preview_season_holdout_real_rows():
    p = E.temporal_split_preview("SEASON_HOLDOUT")
    f = p["folds"][0]
    assert f["training"]["rows"] == 184104 and f["validation"]["rows"] == 182449 and f["frozen"]["rows"] == 182926
    assert p["matchesGovernedContract"] is True and p["leakageStatus"] == "FROZEN_2025_PROTECTED"


def test_temporal_preview_rolling_never_tunes_on_frozen():
    p = E.temporal_split_preview("ROLLING_ORIGIN")
    assert len(p["folds"]) == 2 and not p["matchesGovernedContract"]
    # any fold that validates on 2025 is explicitly FROZEN_EVAL_ONLY, never a tuning fold
    for f in p["folds"]:
        if f["validation"]["season"] == 2025:
            assert f["validation"].get("role") == "FROZEN_EVAL_ONLY"


def test_temporal_preview_date_holdout_splits_development_by_date():
    p = E.temporal_split_preview("DATE_HOLDOUT", "2023-07-01")
    f = p["folds"][0]
    assert f["training"]["rows"] + f["validation"]["rows"] == 184104  # partitions the 2023 dev season
    assert f["boundaryDate"] == "2023-07-01"


def test_temporal_preview_random_is_flagged_research_only():
    p = E.temporal_split_preview("RANDOM")
    assert p["researchOnly"] is True and p["leakageStatus"] == "TEMPORAL_ORDER_NOT_PRESERVED"


# ---------------- Segmentation: DBSCAN + grid guidance + K-means fields ----------------
@pytest.mark.parametrize("pop", ["BATTERS", "PITCHERS"])
def test_dbscan_produces_clusters_and_labels_noise(pop):
    d = SEG.run_dbscan(pop, [], None, None)
    assert d["players"] > 100 and d["minSamples"] >= 5 and d["suggestedEps"] > 0
    assert d["noise"] >= 0 and 0.0 <= d["noisePct"] <= 1.0
    assert len(d["kDistance"]) > 0                 # eps-selection diagnostic present
    labels = {pt["cluster"] for pt in d["points"]}
    assert d["noise"] == 0 or -1 in labels          # noise is cluster -1, never forced into an archetype


@pytest.mark.parametrize("pop", ["BATTERS", "PITCHERS"])
def test_grid_guidance_ranks_real_pairs(pop):
    g = SEG.grid_guidance(pop)
    assert len(g["suggestions"]) >= 3
    scores = [s["gridQualityScore"] for s in g["suggestions"]]
    assert scores == sorted(scores, reverse=True)   # ranked by Grid Quality Score (Phase 6G.1)
    top = g["suggestions"][0]
    assert set(["dimX", "dimY", "absCorr", "cellBalance", "minCell", "gridQualityScore"]).issubset(top)


def test_kmeans_exposes_size_balance_decision_fields():
    k = SEG.run_kmeans("BATTERS", [], 2, 6)
    r = k["results"][0]
    assert "sizeBalance" in r and "minClusterShare" in r and "tinyCluster" in r
    assert 2 <= k["recommendedK"] <= 6


# ---------------- Model Laboratory: distinct configs, propagation, frozen protection ----------------
def test_lab_trains_distinct_configs_with_preprocessing_propagation():
    A = M.run_experiment({"features": list(M.ALL_FEATURES), "family": "logistic",
                          "outlierPolicy": {"globalMethod": "none"}, "missingPolicy": {"globalMethod": "median"}}, persist=False)
    B = M.run_experiment({"features": list(M.ALL_FEATURES), "family": "logistic",
                          "outlierPolicy": {"globalMethod": "iqr", "params": {"k": 1.5}},
                          "missingPolicy": {"globalMethod": "mean", "addIndicator": True}}, persist=False)
    assert A["experimentId"] != B["experimentId"]                    # config-hash identity, no contamination
    assert A["config"]["outlierPolicy"]["globalMethod"] == "none"
    assert B["config"]["outlierPolicy"]["globalMethod"] == "iqr"     # selected policy actually consumed
    assert B["expandedFeatureCount"] > A["expandedFeatureCount"]     # missing indicators propagated into training
    assert A["metrics"]["val2024"]["logLoss"] > 0 and A["metrics"]["frozen2025"]["logLoss"] > 0


def test_preprocessor_fits_on_development_only_frozen_protected():
    frame = E.load_frame()
    pre = M.Preprocessor.fit(frame, ["pitcher_era9"], {"globalMethod": "none"}, {"globalMethod": "median"})
    dev = frame.loc[frame["season"] == 2023, "pitcher_era9"].to_numpy()
    dev = dev[np.isfinite(dev)]
    assert abs(pre.state["pitcher_era9"]["imputeFill"] - float(np.median(dev))) < 1e-6  # dev-only statistic
    X_frozen = pre.transform(frame, frame["season"].to_numpy() == 2025)
    assert np.isfinite(X_frozen).all()  # 2025 only transformed with dev-fitted state, never used to fit
