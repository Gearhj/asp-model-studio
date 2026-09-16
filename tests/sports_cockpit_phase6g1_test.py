"""Phase 6G.1 — data authority, 2021/2022 metadata, multiclass OVR IV, segmentation guidance."""

from __future__ import annotations

import pytest

from server.sports_cockpit import engine as E
from server.sports_cockpit import segmentation as SEG

_HAS_VIEW = True
try:
    from tests._runtime_probe import IS_SYNTHETIC_SEED as _IS_SYNTHETIC_SEED
    E._feature_view_path()
    _HAS_VIEW = not _IS_SYNTHETIC_SEED   # real D3/Gen-2 view only; a synthetic seed fails real-data assertions
except Exception:
    _HAS_VIEW = False

pytestmark = pytest.mark.skipif(not _HAS_VIEW, reason="D3 feature view not materialized")


def test_source_evidence_carries_real_games_batters_pitchers_including_prior_years():
    per = {r["season"]: r for r in E.population_payload()["sourceEvidence"]["perSeason"]}
    # 2021/2022 counts are DERIVED and present — never "—"
    assert per[2021]["games"] == 2429 and per[2021]["batters"] == 1049 and per[2021]["pitchers"] == 909
    assert per[2022]["games"] == 2430 and per[2022]["batters"] == 693
    # 2021 has more distinct batters (NL pitchers batted pre-universal-DH)
    assert per[2021]["batters"] > per[2022]["batters"] > per[2023]["batters"]
    for s in (2021, 2022, 2023, 2024, 2025):
        assert per[s]["games"] and per[s]["batters"] and per[s]["pitchers"]


def test_profile_exposes_per_class_ovr_iv():
    p = E.feature_profile()
    f = next(x for x in p["features"] if x["name"] == "batter_so_per_pa")
    iv = f["iv"]
    assert "perClass" in iv and len(iv["perClass"]) == 8       # class-specific OVR IV
    assert iv["maxIv"] == max(iv["perClass"].values())          # max OVR IV is the max per-class
    assert iv["maxIvClass"] in iv["perClass"]
    # mean OVR IV is the mean of the per-class values
    assert abs(iv["meanIv"] - sum(iv["perClass"].values()) / 8) < 1e-9


def test_kmeans_exploratory_score_is_transparent_composite():
    k = SEG.run_kmeans("BATTERS", [], 2, 6)
    assert set(k["scoreWeights"]) == {"normSilhouette", "invNormDaviesBouldin", "temporalStability", "sizeBalance", "usableClusterFraction"}
    assert abs(sum(k["scoreWeights"].values()) - 1.0) < 1e-9
    for r in k["results"]:
        assert "explorScore" in r and "scoreComponents" in r
        # score equals the documented weighted sum of its components
        recomputed = sum(k["scoreWeights"][c] * r["scoreComponents"][c] for c in k["scoreWeights"])
        assert abs(r["explorScore"] - round(recomputed, 3)) < 1e-6
        assert "temporalStability" in r
    # recommended K maximizes the composite
    assert k["recommendedK"] == max(k["results"], key=lambda r: r["explorScore"])["k"]


def test_cluster_profiles_have_data_derived_labels():
    p = SEG.pca_scatter("BATTERS", [], 2)
    for prof in p["profiles"]:
        assert prof["autoLabel"] and ("Higher" in prof["autoLabel"] or "Lower" in prof["autoLabel"])
        assert len(prof["distinguishing"]) >= 2
        top = prof["distinguishing"][0]
        assert set(["feature", "clusterMean", "overallMean", "stdDiff"]).issubset(top)


def test_dbscan_has_a_recommendation_state():
    d = SEG.run_dbscan("BATTERS", [], None, None)
    assert d["recommendation"] in {"PLAUSIBLE_DENSITY_STRUCTURE", "MOSTLY_ONE_CLUSTER_PLUS_OUTLIERS", "FRAGMENTED_UNSTABLE", "ONE_GIANT_CLUSTER", "EXCESSIVE_NOISE"}
    assert d["recommendationLabel"]
    assert "biggestClusterShare" in d


def test_grid_quality_score_is_transparent():
    g = SEG.grid_guidance("BATTERS")
    assert set(g["scoreWeights"]) == {"cellBalance", "nonRedundancy", "temporalStability", "coverage"}
    scores = [s["gridQualityScore"] for s in g["suggestions"]]
    assert scores == sorted(scores, reverse=True)
    top = g["suggestions"][0]
    assert set(["dimX", "dimY", "gridQualityScore", "components", "coverage", "temporalStability"]).issubset(top)
    assert 0.0 <= top["coverage"] <= 1.0
