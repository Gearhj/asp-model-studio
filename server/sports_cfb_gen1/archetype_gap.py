"""Bounded Development-only CFB archetype and uncertainty research.

This module never reads 2026 evidence and has no exchange/consumer side effects.
The production point model and final-score transformation are reused unchanged.
"""
from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.cluster import KMeans
from sklearn.impute import SimpleImputer
from sklearn.metrics import adjusted_rand_score, roc_auc_score, silhouette_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .pipeline import SIMULATION_COUNT, score_distribution, simulate_paired_residuals

VERSION = "CFB_ARCHETYPE_AND_EXTENDED_GAP_CHALLENGER_V1"
MODEL = "ridge_alpha100"
SEED = 260915
TEAM_VARIABLES = [
    "points_for_season", "points_allowed_season", "total_yards_season",
    "yards_allowed_season", "turnovers_season", "takeaways_season",
    "elo", "prior_margin_shrunk",
]
K_VALUES = (2, 3, 4)
MIN_PAIR = 200
MIN_PAIR_SEASONS = 3
MIN_TEAM_IDS = 20
SHRINKAGE_GAMES = 200
BIAS_BLEND = 0.5
MIN_GAP = 150
MIN_GAP_SEASONS = 2
MAX_MARGIN_SCALE = 1.5


def eligible_donors(predictions: pd.DataFrame, target: pd.Series) -> pd.DataFrame:
    """Conservative season-complete donor gate; no invented completion times."""
    selected = predictions[(predictions.season < int(target.season)) & (predictions.season <= 2025)].copy()
    if len(selected) and not (selected.scheduled_at < target.scheduled_at).all():
        raise ValueError("donor chronology reaches target kickoff")
    if int(target.season) > 2025:
        raise ValueError("this study has no 2026 forecast authority")
    return selected


def weak_support(frame: pd.DataFrame) -> np.ndarray:
    return (
        (frame.home_current_season_games < 2) | (frame.away_current_season_games < 2)
        | frame.home_long_gap.astype(bool) | frame.away_long_gap.astype(bool)
    ).to_numpy()


def team_states(frame: pd.DataFrame, side: str) -> pd.DataFrame:
    cols = [f"elo_{side}" if name == "elo" else f"{side}_{name}" for name in TEAM_VARIABLES]
    result = frame[cols].copy()
    result.columns = TEAM_VARIABLES
    return result.reset_index(drop=True)


def raw_residuals(frame: pd.DataFrame) -> np.ndarray:
    return frame[["home_score", "away_score"]].to_numpy(float) - frame[
        [f"{MODEL}_pred_home", f"{MODEL}_pred_away"]
    ].to_numpy(float)


def draw_hash(draws: pd.DataFrame) -> str:
    return hashlib.sha256(draws[["home_score", "away_score"]].to_numpy(dtype="<i2").tobytes()).hexdigest()


def _fit_kmeans(x: pd.DataFrame, k: int, seed: int) -> Pipeline:
    estimator = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("scale", StandardScaler()),
        ("cluster", KMeans(n_clusters=k, n_init=10, random_state=seed)),
    ])
    with threadpool_limits(limits=1):
        estimator.fit(x)
    return estimator


def _assign(estimator: Pipeline, mapping: dict[int, int], x: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    # The study runner owns the single-thread context. Re-enumerating Windows
    # libraries for each one-row assignment is costly and changes no arithmetic.
    raw = estimator.predict(x)
    distance = estimator.transform(x).min(axis=1)
    return np.array([mapping[int(label)] for label in raw]), distance


def fit_cluster(train: pd.DataFrame, k: int, target_season: int, bootstrap_reps: int = 10) -> dict[str, Any]:
    if train.empty or (train.season >= min(target_season, 2023)).any():
        raise ValueError("cluster fitting requires strictly earlier Development seasons")
    ordinary = train.loc[~weak_support(train)].reset_index(drop=True)
    states = pd.concat([team_states(ordinary, "home"), team_states(ordinary, "away")], ignore_index=True)
    meta = pd.concat([
        ordinary[["game_id", "season", "scheduled_at", f"{side}_id", f"{side}_conference_name"]].rename(
            columns={f"{side}_id": "team_id", f"{side}_conference_name": "conference"}
        ) for side in ("home", "away")
    ], ignore_index=True)
    estimator = _fit_kmeans(states, k, SEED + k + target_season)
    original_centers = estimator.named_steps["scale"].inverse_transform(estimator.named_steps["cluster"].cluster_centers_)
    order = np.argsort(original_centers[:, TEAM_VARIABLES.index("elo")], kind="stable")
    mapping = {int(old): int(new) for new, old in enumerate(order)}
    labels, distances = _assign(estimator, mapping, states)
    limit = float(np.quantile(distances, .99))
    # Block resampling refits the imputer/scaler as well as the clusters.
    blocks = meta.scheduled_at.dt.strftime("%G-W%V").to_numpy()
    block_ids = np.unique(blocks)
    rng = np.random.default_rng(SEED + k + target_season)
    stability = []
    for rep in range(bootstrap_reps):
        sampled = rng.choice(block_ids, len(block_ids), replace=True)
        indices = np.concatenate([np.flatnonzero(blocks == b) for b in sampled])
        alternative = _fit_kmeans(states.iloc[indices], k, SEED + 100 + rep)
        with threadpool_limits(limits=1):
            alt_labels = alternative.predict(states)
        stability.append(float(adjusted_rand_score(labels, alt_labels)))
    profiles = []
    for label in range(k):
        subset = meta.loc[labels == label]
        means = states.loc[labels == label].mean()
        profiles.append({
            "cluster": label, "teamAppearances": len(subset), "distinctTeams": int(subset.team_id.nunique()),
            "bySeason": {str(s): int(n) for s, n in subset.season.value_counts().sort_index().items()},
            "byConference": {str(s): int(n) for s, n in subset.conference.fillna("UNKNOWN").value_counts().items()},
            "largestTeamFraction": float(subset.team_id.value_counts(normalize=True).max()),
            "largestConferenceFraction": float(subset.conference.fillna("UNKNOWN").value_counts(normalize=True).max()),
            "variableMeans": means.to_dict(), "centerOriginalUnits": dict(zip(TEAM_VARIABLES, original_centers[order[label]])),
        })
    sil_x = estimator[:-1].transform(states)
    quality = {
        "bootstrapRepetitions": bootstrap_reps, "bootstrapBlock": "ISO_CALENDAR_WEEK",
        "bootstrapAdjustedRand": stability, "meanBootstrapAdjustedRand": float(np.mean(stability)),
        "silhouette": float(silhouette_score(sil_x, labels, sample_size=min(2000, len(states)), random_state=SEED)),
        "distance99": limit, "profiles": profiles,
    }
    quality["supported"] = bool(
        np.mean(stability) >= .60
        and all(p["teamAppearances"] >= 300 and p["distinctTeams"] >= MIN_TEAM_IDS
                and p["largestTeamFraction"] <= .08 and p["largestConferenceFraction"] <= .65 for p in profiles)
    )
    h, hd = _assign(estimator, mapping, team_states(ordinary, "home"))
    a, ad = _assign(estimator, mapping, team_states(ordinary, "away"))
    pairs = {}
    for hc in range(k):
        for ac in range(k):
            mask = (h == hc) & (a == ac) & (hd <= limit) & (ad <= limit)
            part = ordinary.loc[mask]
            residuals = raw_residuals(part)
            count = len(part)
            support = count >= MIN_PAIR and part.season.nunique() >= MIN_PAIR_SEASONS
            support = support and part.home_id.nunique() >= MIN_TEAM_IDS and part.away_id.nunique() >= MIN_TEAM_IDS
            delta = BIAS_BLEND * count / (count + SHRINKAGE_GAMES) * residuals.mean(axis=0) if count else np.zeros(2)
            pairs[f"A{ac}_H{hc}"] = {
                "games": count, "seasons": sorted(map(int, part.season.unique())),
                "homeTeams": int(part.home_id.nunique()), "awayTeams": int(part.away_id.nunique()),
                "supported": bool(support and quality["supported"]), "deltaHome": float(delta[0]), "deltaAway": float(delta[1]),
            }
    return {
        "estimator": estimator, "mapping": mapping, "k": k, "targetSeason": target_season,
        "trainingThroughSeason": int(train.season.max()), "trainingLatestKickoff": train.scheduled_at.max().isoformat(),
        "trainingGameIds": train.game_id.astype(int).tolist(), "quality": quality, "pairs": pairs,
    }


def cluster_effect(artifact: dict[str, Any], target: pd.Series) -> dict[str, Any]:
    if pd.Timestamp(artifact["trainingLatestKickoff"]) >= target.scheduled_at:
        raise ValueError("cluster artifact reaches target kickoff")
    if artifact["trainingThroughSeason"] > 2022:
        raise ValueError("later-period outcomes entered the cluster")
    one = target.to_frame().T
    h, hd = _assign(artifact["estimator"], artifact["mapping"], team_states(one, "home"))
    a, ad = _assign(artifact["estimator"], artifact["mapping"], team_states(one, "away"))
    key = f"A{a[0]}_H{h[0]}"
    pair = artifact["pairs"][key]
    eligible = bool(not weak_support(one)[0] and max(hd[0], ad[0]) <= artifact["quality"]["distance99"] and pair["supported"])
    return {
        "homeCluster": int(h[0]), "awayCluster": int(a[0]), "matchup": key,
        "applied": eligible, "pairGames": pair["games"],
        "deltaHome": pair["deltaHome"] if eligible else 0.0,
        "deltaAway": pair["deltaAway"] if eligible else 0.0,
        "fallback": None if eligible else "EXACT_BASELINE_SUPPORT_OR_DISTANCE_GATE",
    }


def fit_gap(train: pd.DataFrame, target_season: int) -> dict[str, Any]:
    if train.empty or (train.season >= min(target_season, 2023)).any():
        raise ValueError("gap estimation requires strictly earlier Development")
    residual = raw_residuals(train)
    margin = residual[:, 0] - residual[:, 1]
    target = weak_support(train)
    n = int(target.sum())
    global_variance = float(np.var(margin, ddof=1))
    target_variance = float(np.var(margin[target], ddof=1))
    pooled = (n * target_variance + SHRINKAGE_GAMES * global_variance) / (n + SHRINKAGE_GAMES)
    scale = float(np.clip(np.sqrt(pooled / global_variance), 1, MAX_MARGIN_SCALE))
    supported = n >= MIN_GAP and train.loc[target, "season"].nunique() >= MIN_GAP_SEASONS
    return {
        "trainingThroughSeason": int(train.season.max()), "trainingLatestKickoff": train.scheduled_at.max().isoformat(),
        "trainingGameIds": train.game_id.astype(int).tolist(), "targetedGames": n,
        "targetedSeasons": sorted(map(int, train.loc[target, "season"].unique())),
        "globalMarginResidualVariance": global_variance, "targetMarginResidualVariance": target_variance,
        "targetMarginResidualMean": float(margin[target].mean()), "globalMarginResidualMean": float(margin.mean()),
        "marginScale": scale if supported else 1.0, "supported": bool(supported),
    }


def candidate_draws(target: pd.Series, donors: pd.DataFrame, baseline: pd.DataFrame,
                    *, cluster: dict[str, Any] | None = None, gap: dict[str, Any] | None = None,
                    draw_count: int = SIMULATION_COUNT) -> tuple[pd.DataFrame, dict[str, Any]]:
    if len(donors) and (donors.season >= target.season).any():
        raise ValueError("candidate requires completed prior-season donors")
    effective = target.copy()
    info: dict[str, Any] = {"applied": False, "deltaHome": 0.0, "deltaAway": 0.0, "marginScale": 1.0}
    selected_donors = donors
    if cluster is not None:
        info.update(cluster_effect(cluster, target))
        effective[f"{MODEL}_pred_home"] += info["deltaHome"]
        effective[f"{MODEL}_pred_away"] += info["deltaAway"]
    if gap is not None:
        if pd.Timestamp(gap["trainingLatestKickoff"]) >= target.scheduled_at or gap["trainingThroughSeason"] > 2022:
            raise ValueError("gap artifact reaches target or later-period outcomes")
        if weak_support(target.to_frame().T)[0] and gap["supported"] and gap["marginScale"] > 1:
            residuals = raw_residuals(donors)
            margin = residuals[:, 0] - residuals[:, 1]
            correction = (gap["marginScale"] - 1) * (margin - margin.mean())
            selected_donors = donors.copy()
            selected_donors[f"{MODEL}_pred_home"] -= correction / 2
            selected_donors[f"{MODEL}_pred_away"] += correction / 2
            info.update(applied=True, marginScale=gap["marginScale"], rawMeanMarginShift=float(correction.mean()))
    if not info["applied"]:
        info["fallback"] = "EXACT_CHRONOLOGY_ELIGIBLE_BASELINE"
        return baseline.copy(), info
    result, accounting = simulate_paired_residuals(effective, selected_donors, MODEL, draw_count=draw_count,
                                                 low_total_threshold=34, high_total_threshold=80)
    info["transformation"] = accounting
    return result, info


def measure(draws: pd.DataFrame, row: pd.Series, delta_home: float = 0, delta_away: float = 0) -> dict[str, Any]:
    out = score_distribution(draws, row, 34, 80)
    pred_home = float(row[f"{MODEL}_pred_home"]) + delta_home
    pred_away = float(row[f"{MODEL}_pred_away"]) + delta_away
    for key, pred, obs in (
        ("home", pred_home, row.home_score), ("away", pred_away, row.away_score),
        ("margin", pred_home-pred_away, row.home_margin), ("total", pred_home+pred_away, row.total_points),
    ):
        out[f"{key}PointPrediction"] = pred
        out[f"{key}Error"] = float(pred-obs)
        out[f"{key}AbsoluteError"] = abs(float(pred-obs))
    favorite_home = float(row.elo_home_win_probability) >= .5
    out["predictedUpsetProbability"] = float((draws.home_margin < 0).mean() if favorite_home else (draws.home_margin > 0).mean())
    out["observedUpset"] = int((row.home_win == 0) if favorite_home else (row.home_win == 1))
    out["predictedLargeMarginProbability"] = float((draws.home_margin.abs() >= 28).mean())
    out["observedLargeMargin"] = int(abs(row.home_margin) >= 28)
    out["finalHomeMean"] = float(draws.home_score.mean())
    out["finalAwayMean"] = float(draws.away_score.mean())
    out["drawCount"] = len(draws)
    out["drawSha256"] = draw_hash(draws)
    out["correctWinner"] = int((out["jointHomeWinProbability"] >= .5) == bool(row.home_win))
    return out


def probability_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    p = np.clip(np.asarray(p, float), 1e-12, 1-1e-12)
    y = np.asarray(y, float)
    bins = []
    indices = np.minimum((p * 10).astype(int), 9)
    for i in range(10):
        m = indices == i
        if m.any():
            bins.append({"lower": i/10, "upper": (i+1)/10, "games": int(m.sum()),
                         "meanProbability": float(p[m].mean()), "observedRate": float(y[m].mean())})
    result = {
        "logLoss": float(np.mean(-y*np.log(p)-(1-y)*np.log(1-p))),
        "brier": float(np.mean((p-y)**2)), "brierConvention": "MEAN_SINGLE_BINARY_HOME_INDICATOR_SQUARED_ERROR",
        "accuracy": float(np.mean((p>=.5)==y)),
        "auc": float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None,
        "reliability": bins,
        "ece": float(sum(b["games"]*abs(b["meanProbability"]-b["observedRate"]) for b in bins)/len(y)),
        "calibrationIntercept": None, "calibrationSlope": None,
    }
    if len(y) >= 100 and len(np.unique(y)) == 2:
        x = np.log(p/(1-p))
        def objective(beta: np.ndarray) -> float:
            z = beta[0] + beta[1]*x
            return float(np.mean(np.logaddexp(0, z)-y*z))
        fitted = minimize(objective, np.array([0., 1.]), method="BFGS")
        if fitted.success:
            result.update(calibrationIntercept=float(fitted.x[0]), calibrationSlope=float(fitted.x[1]))
    return result


def aggregate(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {"games": 0, "status": "UNAVAILABLE"}
    out: dict[str, Any] = {"games": len(rows), "appliedGames": int(rows.applied.sum())}
    out["winner"] = probability_metrics(rows.home_win.to_numpy(), rows.jointHomeWinProbability.to_numpy())
    for metric in ["jointEnergyScore", "marginCrps", "totalCrps", "homeCrps", "awayCrps"]:
        out[metric] = float(rows[metric].mean())
    out["points"] = {}
    out["intervals"] = {}
    for key in ("home", "away", "margin", "total"):
        out["points"][key] = {"mae": float(rows[f"{key}AbsoluteError"].mean()), "signedBias": float(rows[f"{key}Error"].mean()),
                              "absoluteErrorQ50Q80Q90Q95": np.quantile(rows[f"{key}AbsoluteError"], [.5,.8,.9,.95]).tolist()}
        out["intervals"][key] = {str(level): {"coverage": float(rows[f"{key}Coverage{level}"].mean()),
                                            "width": float(rows[f"{key}Width{level}"].mean())} for level in (50,80,90)}
    out["tails"] = {}
    for key, pred, actual in (
        ("lowTotal_le34", "predictedLowTotalProbability", "observedLowTotal"),
        ("highTotal_ge80", "predictedHighTotalProbability", "observedHighTotal"),
        ("upsetOfPregameEloFavorite", "predictedUpsetProbability", "observedUpset"),
        ("absoluteMargin_ge28", "predictedLargeMarginProbability", "observedLargeMargin"),
    ):
        out["tails"][key] = {"predictedRate": float(rows[pred].mean()), "observedRate": float(rows[actual].mean()),
                            "brier": float(((rows[pred]-rows[actual])**2).mean()), "positiveEvents": int(rows[actual].sum()),
                            "adequateForInterpretation": len(rows)>=200 and rows[actual].sum()>=20}
    if "rawHomeMean" in rows:
        denominator = float(rows.drawCount.sum())
        out["supportTransformation"] = {
            "negativeHomeFractionBeforeFloor": float(rows.rawNegativeHomeCount.sum()/denominator),
            "negativeAwayFractionBeforeFloor": float(rows.rawNegativeAwayCount.sum()/denominator),
            "initialTieFraction": float(rows.initialRoundedTieCount.sum()/denominator),
            "meanHomeShiftRawToFinal": float((rows.finalHomeMean-rows.rawHomeMean).mean()),
            "meanAwayShiftRawToFinal": float((rows.finalAwayMean-rows.rawAwayMean).mean()),
            "lowTotalProbabilityShiftRawToFinal": float((rows.predictedLowTotalProbability-rows.rawLowTotalProbability).mean()),
            "highTotalProbabilityShiftRawToFinal": float((rows.predictedHighTotalProbability-rows.rawHighTotalProbability).mean()),
        }
    return out


PAIRED_METRICS = ["jointEnergyScore", "jointWinnerLogLoss", "jointBinaryBrier", "marginCrps", "totalCrps",
                  "marginCoverage90", "marginWidth90", "marginAbsoluteError", "totalAbsoluteError"]


def paired_differences(base: pd.DataFrame, candidate: pd.DataFrame, repetitions: int = 2000) -> dict[str, Any]:
    b = base.set_index("game_id").sort_index()
    c = candidate.set_index("game_id").sort_index()
    if not b.index.equals(c.index):
        raise ValueError("paired assessment games differ")
    if not len(b):
        return {"games": 0}
    delta = c[PAIRED_METRICS].to_numpy(float)-b[PAIRED_METRICS].to_numpy(float)
    blocks = b.scheduled_at.dt.strftime("%G-W%V")
    keys = sorted(blocks.unique())
    sums = np.array([delta[blocks.eq(k)].sum(axis=0) for k in keys])
    counts = np.array([blocks.eq(k).sum() for k in keys])
    rng = np.random.default_rng(SEED)
    picks = rng.integers(0, len(keys), (repetitions, len(keys)))
    boot = sums[picks].sum(axis=1)/counts[picks].sum(axis=1)[:,None]
    out = {"games": len(b), "calendarBlocks": len(keys), "bootstrapRepetitions": repetitions, "seed": SEED,
           "direction": "CANDIDATE_MINUS_BASELINE; NEGATIVE_FAVORS_CANDIDATE_FOR_LOSSES_ONLY",
           "interpretation": "EXPLORATORY_GAME_BLOCK_UNCERTAINTY_NOT_SIMULATION_MCSE"}
    for j, metric in enumerate(PAIRED_METRICS):
        out[metric] = {"estimate": float(delta[:,j].mean()), "interval95": np.quantile(boot[:,j], [.025,.975]).tolist()}
    return out
