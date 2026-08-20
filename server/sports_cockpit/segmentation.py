"""Exploratory player segmentation workbench (batter/pitcher archetypes).

This is research-only: it never mutates the PA model and creates no per-player boosts. It fits
K-means / diagnostics on the *development* population of prior-state player characteristics, offers
a PCA view, cluster profiles, temporal cluster stability, and an interpretable 3×3 grid designer.
Player counts are small (~600–700 per role per season), so clustering is fast and bounded.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

import itertools

from sklearn.cluster import DBSCAN, KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler

from . import engine as E
from .engine import CockpitError, load_frame

BATTER_CLUSTER_FEATURES = ("batter_log1p_pa", "batter_avg", "batter_obp", "batter_slg", "batter_so_per_pa", "batter_bb_hbp_per_pa", "batter_hr_per_pa")
PITCHER_CLUSTER_FEATURES = ("pitcher_log1p_bfp", "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp", "pitcher_bb_per_bfp", "pitcher_hr_per_bfp", "pitcher_gs_per_g")


def default_features(population: str) -> tuple[str, ...]:
    return BATTER_CLUSTER_FEATURES if population == "BATTERS" else PITCHER_CLUSTER_FEATURES


def _player_table(population: str, features: Sequence[str], season: int) -> pd.DataFrame:
    """One row per player for `season`, prior-state features + PA/BF weight (vectorized)."""
    frame = load_frame()
    if population == "BATTERS":
        uuid_col, missing_col = "batter_canonical_player_uuid", "batter_prior_missing"
    else:
        uuid_col, missing_col = "pitcher_canonical_player_uuid", "pitcher_prior_missing"
    m = frame["season"].to_numpy() == season
    sub = frame.loc[m, [uuid_col, missing_col, *features]].copy()
    weight = sub.groupby(uuid_col).size().rename("weight")
    agg = sub.groupby(uuid_col)[list(features) + [missing_col]].first()
    agg = agg.join(weight)
    agg = agg[agg[missing_col] < 0.5]                 # players with a real prior only
    agg = agg.dropna(subset=list(features))
    return agg.reset_index()


def population_summary(population: str, season: int = E.DEV_SEASON) -> dict[str, Any]:
    feats = default_features(population)
    tbl = _player_table(population, feats, season)
    return {
        "population": population,
        "season": season,
        "players": int(len(tbl)),
        "candidateFeatures": list(feats),
        "paWeightTotal": int(tbl["weight"].sum()) if len(tbl) else 0,
    }


SEG_SCORE_WEIGHTS = {"normSilhouette": 0.35, "invNormDaviesBouldin": 0.25, "temporalStability": 0.20, "sizeBalance": 0.10, "usableClusterFraction": 0.10}


def run_kmeans(population: str, features: Sequence[str], k_min: int = 2, k_max: int = 10, season: int = E.DEV_SEASON, seed: int = 20260819) -> dict[str, Any]:
    feats = list(features) if features else list(default_features(population))
    tbl = _player_table(population, feats, season)
    if len(tbl) < (k_max + 2):
        raise CockpitError("not enough players for the requested cluster range")
    scaler = StandardScaler().fit(tbl[feats].to_numpy(dtype=np.float64))
    X = scaler.transform(tbl[feats].to_numpy(dtype=np.float64))
    weight = tbl["weight"].to_numpy(dtype=np.float64)
    uuid_col = "batter_canonical_player_uuid" if population == "BATTERS" else "pitcher_canonical_player_uuid"
    # 2024 projection for per-K temporal stability (development-fitted scaler + centroids; descriptive).
    t24 = _player_table(population, feats, E.VAL_SEASON)
    X24 = scaler.transform(t24[feats].to_numpy(dtype=np.float64)) if len(t24) else None
    tiny_floor = max(5, int(0.03 * len(tbl)))
    results = []
    for k in range(max(2, k_min), min(k_max, 15) + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X)
        labels = km.labels_
        sizes = np.bincount(labels, minlength=k)
        pa_prev = np.array([weight[labels == c].sum() for c in range(k)]) / weight.sum()
        stability = None
        if X24 is not None and len(t24):
            a23 = dict(zip(tbl[uuid_col], labels))
            a24 = dict(zip(t24[uuid_col], km.predict(X24)))
            common = [u for u in a23 if u in a24]
            stability = float(sum(1 for u in common if a23[u] == a24[u]) / len(common)) if common else None
        results.append({
            "k": k,
            "silhouette": float(silhouette_score(X, labels)),
            "daviesBouldin": float(davies_bouldin_score(X, labels)),
            "calinskiHarabasz": float(calinski_harabasz_score(X, labels)),
            "clusterSizes": sizes.tolist(),
            "paWeightedPrevalence": pa_prev.tolist(),
            "inertia": float(km.inertia_),
            "minClusterShare": float(sizes.min() / sizes.sum()),
            "sizeBalance": float(sizes.min() / sizes.max()),
            "tinyCluster": bool(sizes.min() < tiny_floor),
            "temporalStability": stability,
            "usableClusterFraction": float(int((sizes >= tiny_floor).sum()) / k),
        })
    # Transparent exploratory-segmentation score (documented composite — NOT proof of predictive value).
    sils = [r["silhouette"] for r in results]
    dbs = [r["daviesBouldin"] for r in results]

    def _norm(vals: list[float], x: float) -> float:
        lo, hi = min(vals), max(vals)
        return (x - lo) / (hi - lo) if hi > lo else 0.5

    for r in results:
        n_sil = _norm(sils, r["silhouette"])
        inv_db = 1.0 - _norm(dbs, r["daviesBouldin"])
        stab = r["temporalStability"] if r["temporalStability"] is not None else 0.5
        comps = {"normSilhouette": round(n_sil, 3), "invNormDaviesBouldin": round(inv_db, 3),
                 "temporalStability": round(stab, 3), "sizeBalance": round(r["sizeBalance"], 3),
                 "usableClusterFraction": round(r["usableClusterFraction"], 3)}
        r["scoreComponents"] = comps
        r["explorScore"] = round(sum(SEG_SCORE_WEIGHTS[k] * comps[k] for k in SEG_SCORE_WEIGHTS), 3)
    rec = max(results, key=lambda r: r["explorScore"])
    rationale = (
        f"highest exploratory score ({rec['explorScore']:.2f}): silhouette {rec['silhouette']:.3f}, "
        f"Davies-Bouldin {rec['daviesBouldin']:.2f}"
        + (f", membership {rec['temporalStability']*100:.0f}% stable 2023→2024" if rec['temporalStability'] is not None else "")
        + (", no critically small clusters" if not rec["tinyCluster"] else ", but watch a small cluster")
    )
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "population": population, "season": season, "features": feats, "players": int(len(tbl)),
        "results": results,
        "recommendedK": rec["k"],
        "recommendationRationale": rationale,
        "scoreWeights": SEG_SCORE_WEIGHTS,
        "note": "Exploratory structural quality only. The composite score measures cluster structure, NOT predictive usefulness — that requires a downstream challenger test.",
    }


def run_dbscan(
    population: str,
    features: Sequence[str],
    eps: float | None = None,
    min_samples: int | None = None,
    season: int = E.DEV_SEASON,
    seed: int = 20260819,
) -> dict[str, Any]:
    """Density-based segmentation. Finds dense archetype cores and leaves genuine outliers as NOISE
    (never forced into an archetype). Development-fitted; exploratory only. Provides a k-distance curve
    and a suggested eps (the standard 'elbow' heuristic) so parameters are principled, not arbitrary."""
    feats = list(features) if features else list(default_features(population))
    tbl = _player_table(population, feats, season)
    if len(tbl) < 10:
        raise CockpitError("not enough players for density segmentation")
    X = StandardScaler().fit_transform(tbl[feats].to_numpy(dtype=np.float64))
    ms = int(min_samples) if min_samples else max(5, X.shape[1] + 1)  # heuristic: dimensionality + 1
    # k-distance curve (k = min_samples): the eps 'knee' is where the sorted k-distance rises sharply.
    nn = NearestNeighbors(n_neighbors=ms).fit(X)
    dist, _ = nn.kneighbors(X)
    kd = np.sort(dist[:, ms - 1])
    suggested_eps = round(float(np.percentile(kd, 90)), 3)
    used_eps = round(float(eps), 3) if eps else suggested_eps
    labels = DBSCAN(eps=used_eps, min_samples=ms).fit(X).labels_
    weight = tbl["weight"].to_numpy(dtype=np.float64)
    raw = tbl[feats].to_numpy(dtype=np.float64)
    uniq = [c for c in sorted(set(labels)) if c != -1]
    clusters = []
    for c in uniq:
        sel = labels == c
        clusters.append({
            "cluster": int(c), "players": int(sel.sum()),
            "paShare": float(weight[sel].sum() / weight.sum()) if weight.sum() else 0.0,
            "centroid": {f: float(raw[sel, j].mean()) for j, f in enumerate(feats)},
        })
    noise = int((labels == -1).sum())
    # Recommendation state — DBSCAN answers a DIFFERENT question than K-means (density/outliers), so
    # it is never ranked against K-means on silhouette.
    noise_pct = noise / len(tbl)
    assigned = len(tbl) - noise
    biggest_share = float(max((int((labels == c).sum()) for c in uniq), default=0) / assigned) if assigned else 0.0
    if noise_pct > 0.5:
        rec, rec_label = "EXCESSIVE_NOISE", "Excessive noise — most players are unassigned; raise eps or lower min-samples."
    elif len(uniq) <= 1:
        rec, rec_label = "MOSTLY_ONE_CLUSTER_PLUS_OUTLIERS", "Mostly one dense cluster plus outliers — lower eps to split archetypes."
    elif len(uniq) >= 6:
        rec, rec_label = "FRAGMENTED_UNSTABLE", "Fragmented into many small clusters — raise eps or min-samples."
    elif biggest_share > 0.85:
        rec, rec_label = "ONE_GIANT_CLUSTER", "One giant cluster dominates — lower eps for finer structure."
    else:
        rec, rec_label = "PLAUSIBLE_DENSITY_STRUCTURE", "Plausible density structure — multiple cores with a modest outlier set."
    pca = PCA(n_components=2, random_state=seed)
    coords = pca.fit_transform(X)
    n = min(len(tbl), 800)
    idx = np.linspace(0, len(tbl) - 1, n).astype(int)
    points = [{"x": float(coords[i, 0]), "y": float(coords[i, 1]), "cluster": int(labels[i])} for i in idx]
    m = min(len(kd), 200)
    kidx = np.linspace(0, len(kd) - 1, m).astype(int)
    k_distance = [{"rank": int(r), "dist": float(kd[j])} for r, j in enumerate(kidx)]
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "population": population, "season": season, "features": feats, "players": int(len(tbl)),
        "eps": used_eps, "minSamples": ms, "suggestedEps": suggested_eps,
        "nClusters": len(uniq), "noise": noise, "noisePct": float(noise_pct),
        "biggestClusterShare": biggest_share,
        "recommendation": rec, "recommendationLabel": rec_label,
        "clusters": clusters, "points": points, "kDistance": k_distance,
        "note": "Exploratory density clustering. Noise points are genuinely unassigned outliers — never forced into an archetype. DBSCAN answers a different question than K-means (density/outliers, not archetype count) and is not compared on silhouette.",
    }


def grid_guidance(population: str, season: int = E.DEV_SEASON, top: int = 6) -> dict[str, Any]:
    """Rank candidate X/Y grid dimensions from the REAL development data (not baseball opinion). Prefers
    evenly-populated, non-redundant pairs so the 3×3 archetype grid is interpretable and well-covered."""
    feats = list(default_features(population))
    tbl = _player_table(population, feats, season)
    if len(tbl) < 18:
        raise CockpitError("not enough players for grid guidance")
    sparse_floor = max(3, len(tbl) // 30)
    uuid_col = "batter_canonical_player_uuid" if population == "BATTERS" else "pitcher_canonical_player_uuid"
    t24 = _player_table(population, feats, E.VAL_SEASON)
    weights = {"cellBalance": 0.35, "nonRedundancy": 0.30, "temporalStability": 0.20, "coverage": 0.15}

    def tercile_cuts(series: np.ndarray) -> np.ndarray:
        return np.quantile(series, [1 / 3, 2 / 3])

    suggestions = []
    for x, y in itertools.combinations(feats, 2):
        vx = tbl[x].to_numpy(dtype=np.float64)
        vy = tbl[y].to_numpy(dtype=np.float64)
        r = abs(float(np.corrcoef(vx, vy)[0, 1])) if vx.std() and vy.std() else 0.0
        cx, cy = tercile_cuts(vx), tercile_cuts(vy)
        gx, gy = np.digitize(vx, cx), np.digitize(vy, cy)
        counts = np.array([int(((gx == ix) & (gy == iy)).sum()) for iy in range(3) for ix in range(3)])
        p = counts / counts.sum()
        entropy = float(-(p[p > 0] * np.log(p[p > 0])).sum())
        balance = round(entropy / np.log(9), 3)
        min_cell = int(counts.min())
        coverage = round(float((counts > 0).sum() / 9.0), 3)
        # temporal stability: apply the 2023 cut points to 2024 players; same-cell fraction for common ids.
        stability = None
        if len(t24):
            cell23 = dict(zip(tbl[uuid_col], gx * 3 + gy))
            g24x, g24y = np.digitize(t24[x].to_numpy(dtype=np.float64), cx), np.digitize(t24[y].to_numpy(dtype=np.float64), cy)
            cell24 = dict(zip(t24[uuid_col], g24x * 3 + g24y))
            common = [u for u in cell23 if u in cell24]
            stability = round(float(sum(1 for u in common if cell23[u] == cell24[u]) / len(common)), 3) if common else None
        stab_v = stability if stability is not None else 0.5
        quality = round(weights["cellBalance"] * balance + weights["nonRedundancy"] * (1 - r) + weights["temporalStability"] * stab_v + weights["coverage"] * coverage, 3)
        suggestions.append({
            "dimX": x, "dimY": y, "absCorr": round(r, 3), "cellBalance": balance, "coverage": coverage,
            "temporalStability": stability, "minCell": min_cell, "sparse": min_cell < sparse_floor,
            "gridQualityScore": quality,
            "components": {"cellBalance": balance, "nonRedundancy": round(1 - r, 3), "temporalStability": stab_v, "coverage": coverage},
        })
    suggestions.sort(key=lambda d: -d["gridQualityScore"])
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "population": population, "season": season, "players": int(len(tbl)),
        "sparseFloor": sparse_floor, "scoreWeights": weights, "suggestions": suggestions[:top],
        "note": "Grid Quality Score = 0.35·cell-balance + 0.30·non-redundancy + 0.20·year-over-year stability + 0.15·coverage (all from real development data). Target-separation across cells is a descriptive component computed at the modeling-matrix level and is not folded into this structural score.",
    }


def pca_scatter(population: str, features: Sequence[str], k: int, season: int = E.DEV_SEASON, seed: int = 20260819) -> dict[str, Any]:
    feats = list(features) if features else list(default_features(population))
    tbl = _player_table(population, feats, season)
    X = StandardScaler().fit_transform(tbl[feats].to_numpy(dtype=np.float64))
    labels = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)
    pca = PCA(n_components=2, random_state=seed)
    coords = pca.fit_transform(X)
    # bounded scatter payload (<= 800 points)
    n = min(len(tbl), 800)
    idx = np.linspace(0, len(tbl) - 1, n).astype(int)
    points = [{"x": float(coords[i, 0]), "y": float(coords[i, 1]), "cluster": int(labels[i])} for i in idx]
    # cluster profiles + auto-labels from the strongest standardized differences (not LLM-invented).
    raw = tbl[feats].to_numpy(dtype=np.float64)
    overall_mean = raw.mean(axis=0)
    overall_std = raw.std(axis=0) + 1e-9
    short = lambda f: f.replace("batter_", "").replace("pitcher_", "").replace("_per_pa", "").replace("_per_bfp", "")
    profiles = []
    for c in range(k):
        sel = labels == c
        diffs = sorted(((f, float((raw[sel, j].mean() - overall_mean[j]) / overall_std[j]), j) for j, f in enumerate(feats)), key=lambda x: -abs(x[1]))
        top = diffs[:2]
        auto_label = " / ".join(f"{'Higher' if d > 0 else 'Lower'} {short(f)}" for f, d, _ in top) if top else f"Cluster {c}"
        distinguishing = [{"feature": f, "clusterMean": float(raw[sel, j].mean()), "overallMean": float(overall_mean[j]), "stdDiff": round(d, 2)} for f, d, j in diffs[:4]]
        profiles.append({
            "cluster": c, "players": int(sel.sum()),
            "centroid": {f: float(raw[sel, j].mean()) for j, f in enumerate(feats)},
            "autoLabel": auto_label, "distinguishing": distinguishing,
        })
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "population": population, "k": k, "features": feats,
        "explainedVariance": [float(v) for v in pca.explained_variance_ratio_],
        "points": points,
        "profiles": profiles,
    }


def cluster_stability(population: str, features: Sequence[str], k: int, seed: int = 20260819) -> dict[str, Any]:
    """Compare cluster assignments 2023 vs 2024 for players present in both (centroid-matched)."""
    feats = list(features) if features else list(default_features(population))
    t23 = _player_table(population, feats, E.DEV_SEASON)
    t24 = _player_table(population, feats, E.VAL_SEASON)
    uuid_col = "batter_canonical_player_uuid" if population == "BATTERS" else "pitcher_canonical_player_uuid"
    scaler = StandardScaler().fit(t23[feats].to_numpy(dtype=np.float64))
    km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(scaler.transform(t23[feats].to_numpy(dtype=np.float64)))
    a23 = dict(zip(t23[uuid_col], km.labels_))
    a24 = dict(zip(t24[uuid_col], km.predict(scaler.transform(t24[feats].to_numpy(dtype=np.float64)))))
    common = [u for u in a23 if u in a24]
    same = sum(1 for u in common if a23[u] == a24[u])
    return {
        "population": population, "k": k, "commonPlayers": len(common),
        "sameClusterPct": float(same / len(common)) if common else None,
        "note": "Assignment reproduced by projecting 2024 players onto 2023-fitted centroids (development-fitted scaler/centroids).",
    }


def grid_3x3(population: str, dim_x: str, dim_y: str, season: int = E.DEV_SEASON, method: str = "tercile") -> dict[str, Any]:
    """Interpretable 3×3 grid on two chosen derived dimensions, development-fitted boundaries."""
    feats = default_features(population)
    if dim_x not in feats or dim_y not in feats:
        raise CockpitError("grid dimensions must be player cluster features")
    tbl = _player_table(population, feats, season)
    def cut(series):
        qs = np.quantile(series, [1 / 3, 2 / 3])
        return np.digitize(series, qs)  # 0,1,2
    gx = cut(tbl[dim_x].to_numpy(dtype=np.float64))
    gy = cut(tbl[dim_y].to_numpy(dtype=np.float64))
    weight = tbl["weight"].to_numpy(dtype=np.float64)
    labels = ["LOW", "MED", "HIGH"]
    cells = []
    for iy in range(3):
        for ix in range(3):
            sel = (gx == ix) & (gy == iy)
            cells.append({
                "x": labels[ix], "y": labels[iy], "players": int(sel.sum()),
                "paShare": float(weight[sel].sum() / weight.sum()) if weight.sum() else 0.0,
                "centroidX": float(tbl[dim_x].to_numpy()[sel].mean()) if sel.any() else None,
                "centroidY": float(tbl[dim_y].to_numpy()[sel].mean()) if sel.any() else None,
            })
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "population": population, "dimX": dim_x, "dimY": dim_y, "season": season, "method": method,
        "boundaryScope": "DEVELOPMENT_ONLY", "cells": cells, "players": int(len(tbl)),
    }
