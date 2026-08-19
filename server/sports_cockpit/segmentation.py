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

from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score
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


def run_kmeans(population: str, features: Sequence[str], k_min: int = 2, k_max: int = 10, season: int = E.DEV_SEASON, seed: int = 20260819) -> dict[str, Any]:
    feats = list(features) if features else list(default_features(population))
    tbl = _player_table(population, feats, season)
    if len(tbl) < (k_max + 2):
        raise CockpitError("not enough players for the requested cluster range")
    X = StandardScaler().fit_transform(tbl[feats].to_numpy(dtype=np.float64))
    weight = tbl["weight"].to_numpy(dtype=np.float64)
    results = []
    for k in range(max(2, k_min), min(k_max, 15) + 1):
        km = KMeans(n_clusters=k, n_init=10, random_state=seed).fit(X)
        labels = km.labels_
        sizes = np.bincount(labels, minlength=k)
        pa_prev = np.array([weight[labels == c].sum() for c in range(k)]) / weight.sum()
        results.append({
            "k": k,
            "silhouette": float(silhouette_score(X, labels)),
            "daviesBouldin": float(davies_bouldin_score(X, labels)),
            "calinskiHarabasz": float(calinski_harabasz_score(X, labels)),
            "clusterSizes": sizes.tolist(),
            "paWeightedPrevalence": pa_prev.tolist(),
            "inertia": float(km.inertia_),
        })
    # recommendation: best silhouette, tie-broken by lower Davies-Bouldin
    rec = max(results, key=lambda r: (round(r["silhouette"], 4), -r["daviesBouldin"]))
    return {
        "schemaVersion": E.COCKPIT_SCHEMA_VERSION,
        "population": population, "season": season, "features": feats, "players": int(len(tbl)),
        "results": results,
        "recommendedK": rec["k"],
        "recommendationRationale": f"highest silhouette ({rec['silhouette']:.3f}) with competitive Davies-Bouldin ({rec['daviesBouldin']:.2f})",
        "note": "Exploratory only — a lower validation-metric cluster count is not automatically 'best'; predictive value must be tested via a controlled ablation.",
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
    # cluster profiles (mean of raw features per cluster)
    raw = tbl[feats].to_numpy(dtype=np.float64)
    profiles = []
    for c in range(k):
        sel = labels == c
        profiles.append({"cluster": c, "players": int(sel.sum()), "centroid": {f: float(raw[sel, j].mean()) for j, f in enumerate(feats)}})
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
