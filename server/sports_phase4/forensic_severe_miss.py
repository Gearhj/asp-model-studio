"""Phase 4F severe-miss forensic primitives (analysis only -- fits no production model).

Given governed A/B/C out-of-sample probabilities on the frozen 549,479-PA population,
these functions quantify how concentrated model error is, whether the worst individual
misses follow identifiable structure, and which governed segments over-index in the tail.

Hard rules encoded here:
  * The official population is never trimmed. Tail-sensitivity numbers are computed on a
    copy and always carry an explicit ``diagnosticOnly`` label.
  * Individual log loss uses the governed probability floor (``per_row_log_loss``); no new
    clipping rule is introduced.
  * The diagnostic severe-miss classifier may only receive pre-prediction predictors; the
    outcome, the loss, and retrospective role/position are never predictors.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_modeling.metrics import (
    PA_CLASS_ORDER,
    per_row_brier_score,
    per_row_log_loss,
)

FORENSIC_CONTRACT_NAME = "MLB_PA_SEVERE_MISS_FORENSIC_STUDY_V1"
FORENSIC_SCHEMA_VERSION = "MLB_PA_SEVERE_MISS_FORENSIC_STUDY_V1"

# Percentile grid for individual-loss distributions.
LOSS_PERCENTILES: tuple[float, ...] = (
    0.0, 1.0, 5.0, 10.0, 25.0, 50.0, 75.0, 90.0, 95.0, 97.5, 99.0, 99.5, 99.9, 100.0,
)
# Worst-fraction grid for Pareto concentration (fraction of rows).
PARETO_FRACTIONS: tuple[float, ...] = (0.001, 0.0025, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20, 0.25, 0.50)
# Severe-miss worst-loss percentile definitions.
SEVERE_LOSS_PERCENTILES: tuple[float, ...] = (0.1, 0.5, 1.0, 2.0, 5.0)
# Severe-miss true-class-probability thresholds.
SEVERE_PROB_THRESHOLDS: tuple[float, ...] = (0.005, 0.01, 0.02, 0.05, 0.10)
# Tail-sensitivity removal fractions (DIAGNOSTIC ONLY -- never a production claim).
TAIL_SENSITIVITY_FRACTIONS: tuple[float, ...] = (0.001, 0.005, 0.01, 0.05)
MIN_SEGMENT_ROWS = 500


def individual_log_loss(encoded: np.ndarray, probs: np.ndarray) -> np.ndarray:
    return per_row_log_loss(encoded, probs)


def individual_brier(encoded: np.ndarray, probs: np.ndarray) -> np.ndarray:
    return per_row_brier_score(encoded, probs)


def _skewness(values: np.ndarray) -> float:
    v = np.asarray(values, dtype=np.float64)
    mean = v.mean()
    std = v.std(ddof=0)
    if std <= 0.0:
        return 0.0
    return float(((v - mean) ** 3).mean() / (std ** 3))


def distribution_summary(values: np.ndarray) -> dict[str, Any]:
    v = np.asarray(values, dtype=np.float64)
    pct = {f"p{str(p).replace('.', '_')}": float(np.percentile(v, p)) for p in LOSS_PERCENTILES}
    return {
        "count": int(v.size),
        "mean": float(v.mean()),
        "std": float(v.std(ddof=0)),
        "skewness": _skewness(v),
        "percentiles": pct,
    }


def pareto_concentration(losses: np.ndarray) -> dict[str, Any]:
    """Fraction of total loss contributed by the worst-x fraction of rows."""

    v = np.sort(np.asarray(losses, dtype=np.float64))[::-1]  # worst first
    total = float(v.sum())
    n = v.size
    rows = []
    cumulative = np.cumsum(v)
    for frac in PARETO_FRACTIONS:
        k = max(1, int(round(frac * n)))
        share = float(cumulative[k - 1] / total) if total > 0 else 0.0
        rows.append({"worstFraction": frac, "rowCount": k, "lossShare": share})
    return {"totalLoss": total, "rowCount": n, "rows": rows}


def severe_masks(
    loss: np.ndarray,
    prob_true: np.ndarray,
    *,
    baseline_loss: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Return every severe-miss definition as boolean masks over the population."""

    masks: dict[str, np.ndarray] = {}
    for p in SEVERE_LOSS_PERCENTILES:
        threshold = np.percentile(loss, 100.0 - p)
        masks[f"worst_{p}pct"] = loss >= threshold
    for t in SEVERE_PROB_THRESHOLDS:
        masks[f"prob_below_{t}"] = prob_true < t
    if baseline_loss is not None:
        excess = loss - baseline_loss
        for delta in (0.25, 0.50, 1.00):
            masks[f"worse_than_A_by_{delta}"] = excess >= delta
            masks[f"better_than_A_by_{delta}"] = excess <= -delta
    return masks


def over_index(mask: np.ndarray, encoded: np.ndarray) -> dict[str, Any]:
    """Per-class population share, severe share, and severe/population over-index ratio."""

    n = encoded.size
    severe_n = int(mask.sum())
    rows = []
    for k, class_name in enumerate(PA_CLASS_ORDER):
        pop_share = float((encoded == k).mean())
        severe_share = float((encoded[mask] == k).mean()) if severe_n else 0.0
        rows.append(
            {
                "class": class_name,
                "populationShare": pop_share,
                "severeShare": severe_share,
                "overIndex": (severe_share / pop_share) if pop_share > 0 else None,
                "severeCount": int((encoded[mask] == k).sum()),
            }
        )
    return {"severeRowCount": severe_n, "rows": rows}


def confusion_pairs(encoded: np.ndarray, probs: np.ndarray, mask: np.ndarray, loss: np.ndarray) -> dict[str, Any]:
    """Ranked actual->predicted confusion pairs within a severe-miss population."""

    idx = np.where(mask)[0]
    if idx.size == 0:
        return {"severeRowCount": 0, "totalPopulationLoss": float(loss.sum()), "pairs": []}
    sub_probs = probs[idx]
    sub_encoded = encoded[idx]
    predicted = sub_probs.argmax(axis=1)
    severe_total = float(loss[idx].sum())
    pop_total = float(loss.sum())
    pairs: dict[tuple[int, int], dict[str, Any]] = {}
    for row_i in range(idx.size):
        key = (int(sub_encoded[row_i]), int(predicted[row_i]))
        entry = pairs.setdefault(key, {"count": 0, "lossSum": 0.0})
        entry["count"] += 1
        entry["lossSum"] += float(loss[idx[row_i]])
    ranked = []
    for (actual, pred), entry in pairs.items():
        ranked.append(
            {
                "actual": PA_CLASS_ORDER[actual],
                "predicted": PA_CLASS_ORDER[pred],
                "isCorrectArgmax": actual == pred,
                "count": entry["count"],
                "meanLoss": entry["lossSum"] / entry["count"],
                "shareOfSevereMisses": entry["count"] / idx.size,
                "shareOfSevereLoss": entry["lossSum"] / severe_total if severe_total else 0.0,
                "shareOfTotalLoss": entry["lossSum"] / pop_total if pop_total else 0.0,
            }
        )
    ranked.sort(key=lambda r: r["count"], reverse=True)
    return {"severeRowCount": int(idx.size), "totalPopulationLoss": pop_total, "pairs": ranked}


def segment_metrics(
    segment_values: np.ndarray,
    loss: np.ndarray,
    encoded: np.ndarray,
    severe_mask: np.ndarray,
    *,
    min_rows: int = MIN_SEGMENT_ROWS,
    branch_losses: Mapping[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Per-segment log loss, severe-miss rate, class mix, over-index. Small segments pooled."""

    n = encoded.size
    pop_severe_rate = float(severe_mask.mean())
    values = np.asarray(segment_values, dtype=object)
    unique = [v for v in sorted(set(values.tolist()), key=lambda x: str(x))]
    rows = []
    small_rows = np.zeros(n, dtype=bool)
    for value in unique:
        seg = values == value
        count = int(seg.sum())
        if count < min_rows:
            small_rows |= seg
            continue
        rows.append(_segment_row(str(value), seg, loss, encoded, severe_mask, pop_severe_rate, branch_losses))
    if small_rows.any():
        rows.append(_segment_row(f"__POOLED_LT_{min_rows}__", small_rows, loss, encoded, severe_mask, pop_severe_rate, branch_losses))
    rows.sort(key=lambda r: r["logLoss"], reverse=True)
    return {"populationSevereRate": pop_severe_rate, "minRows": min_rows, "segments": rows}


def _segment_row(label, seg, loss, encoded, severe_mask, pop_severe_rate, branch_losses):
    count = int(seg.sum())
    class_mix = {PA_CLASS_ORDER[k]: float((encoded[seg] == k).mean()) for k in range(len(PA_CLASS_ORDER))}
    row = {
        "segment": label,
        "rows": count,
        "rowShare": count / encoded.size,
        "logLoss": float(loss[seg].mean()),
        "severeRate": float(severe_mask[seg].mean()),
        "severeOverIndex": (float(severe_mask[seg].mean()) / pop_severe_rate) if pop_severe_rate > 0 else None,
        "classMix": class_mix,
    }
    if branch_losses is not None:
        row["branchLogLoss"] = {b: float(bl[seg].mean()) for b, bl in branch_losses.items()}
    return row


def probability_resolution(encoded, probs, mask):
    """Overconfident-wrong vs reasonable-uncertainty split for severe rows."""

    prob_true = probs[np.arange(encoded.size), encoded]
    max_prob = probs.max(axis=1)
    entropy = -np.sum(np.where(probs > 0, probs * np.log(np.clip(probs, 1e-12, 1.0)), 0.0), axis=1)
    margin = max_prob - prob_true

    def block(sel):
        if not sel.any():
            return None
        return {
            "rows": int(sel.sum()),
            "meanProbTrue": float(prob_true[sel].mean()),
            "meanMaxProb": float(max_prob[sel].mean()),
            "meanEntropy": float(entropy[sel].mean()),
            "meanMargin": float(margin[sel].mean()),
            # overconfident-wrong: model gave a confident winner far from the truth
            "overconfidentWrongShare": float(((max_prob[sel] >= 0.5) & (prob_true[sel] < 0.1)).mean()),
        }

    return {"severe": block(mask), "ordinary": block(~mask)}


def tail_sensitivity(loss: np.ndarray) -> dict[str, Any]:
    """DIAGNOSTIC ONLY: aggregate log loss after removing the worst-x fraction of rows.

    This never alters the official metric and is not a production performance claim; it
    only quantifies how much the extreme tail influences the aggregate.
    """

    v = np.sort(np.asarray(loss, dtype=np.float64))[::-1]
    n = v.size
    full = float(v.mean())
    rows = []
    for frac in TAIL_SENSITIVITY_FRACTIONS:
        k = int(round(frac * n))
        kept = v[k:]
        rows.append(
            {
                "removedWorstFraction": frac,
                "removedRows": k,
                "aggregateLogLossOnRemainder": float(kept.mean()) if kept.size else None,
            }
        )
    return {
        "diagnosticOnly": True,
        "notAProductionPerformanceClaim": True,
        "officialAggregateLogLoss": full,
        "rows": rows,
    }


def ood_scores(train_matrix: np.ndarray, eval_matrix: np.ndarray) -> np.ndarray:
    """Target-free standardized Mahalanobis distance of eval rows to the training centroid."""

    x = np.asarray(train_matrix, dtype=np.float64)
    mean = x.mean(axis=0)
    cov = np.cov(x, rowvar=False)
    cov = cov + np.eye(cov.shape[0]) * 1e-6
    inv = np.linalg.pinv(cov)
    delta = np.asarray(eval_matrix, dtype=np.float64) - mean
    return np.sqrt(np.einsum("ij,jk,ik->i", delta, inv, delta))


def ood_band_severe_rate(ood: np.ndarray, severe_mask: np.ndarray, *, n_bands: int = 10) -> dict[str, Any]:
    order = np.argsort(ood)
    bands = np.array_split(order, n_bands)
    rows = []
    pop_rate = float(severe_mask.mean())
    for i, band in enumerate(bands):
        rows.append(
            {
                "oodDecile": i + 1,
                "rows": int(band.size),
                "meanOodScore": float(ood[band].mean()),
                "severeRate": float(severe_mask[band].mean()),
                "severeOverIndex": (float(severe_mask[band].mean()) / pop_rate) if pop_rate > 0 else None,
            }
        )
    return {"populationSevereRate": pop_rate, "bands": rows}


def severe_miss_classifier(
    x_dev: np.ndarray,
    y_dev: np.ndarray,
    x_val: np.ndarray,
    y_val: np.ndarray,
    feature_names: Sequence[str],
) -> dict[str, Any]:
    """Diagnostic: can pre-prediction metadata predict a D3 worst-5% severe miss?

    Fit on the development fold, evaluate out-of-time. Predictors are pre-prediction only
    (the caller guarantees no outcome/loss/future/retrospective columns). Not deployed.
    """

    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import average_precision_score, roc_auc_score
    from sklearn.preprocessing import StandardScaler

    scaler = StandardScaler().fit(x_dev)
    xd = scaler.transform(x_dev)
    xv = scaler.transform(x_val)
    model = LogisticRegression(C=1.0, penalty="l2", solver="lbfgs", max_iter=2000, class_weight="balanced")
    model.fit(xd, y_dev)
    p_val = model.predict_proba(xv)[:, 1]
    auc = float(roc_auc_score(y_val, p_val))
    pr_auc = float(average_precision_score(y_val, p_val))
    coefs = sorted(
        ({"feature": feature_names[i], "coefficient": float(model.coef_[0][i])} for i in range(len(feature_names))),
        key=lambda r: abs(r["coefficient"]),
        reverse=True,
    )
    return {
        "target": "D3_WORST_5PCT_INDIVIDUAL_LOG_LOSS",
        "fitFold": "2024_development",
        "evalFold": "2025_out_of_time",
        "predictorsArePrePredictionOnly": True,
        "rocAuc": auc,
        "prAuc": pr_auc,
        "baseRatePrValidation": float(np.mean(y_val)),
        "topCoefficients": coefs[:15],
        "notDeployed": True,
    }


def randomness_verdict(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Classify severe-miss structure from the aggregated forensic evidence."""

    reasons: list[str] = []
    categories: list[str] = []
    auc = evidence.get("classifierAuc")
    if auc is not None and auc >= 0.60:
        categories.append("STRUCTURED_BUT_CURRENTLY_UNMODELED")
        reasons.append(f"pre-prediction severe-miss classifier AUC={auc:.3f} (>0.60) => structured/detectable")
    elif auc is not None and auc >= 0.55:
        categories.append("MIXED")
        reasons.append(f"classifier AUC={auc:.3f} (0.55-0.60) => weak but non-random structure")
    else:
        categories.append("RANDOM_OR_IRREDUCIBLE")
        reasons.append(f"classifier AUC={auc} (<0.55) => severe misses barely detectable pre-outcome")
    if evidence.get("lowHistoryOverIndex", 1.0) and evidence["lowHistoryOverIndex"] >= 1.3:
        categories.append("LOW_HISTORY_RELATED")
        reasons.append(f"low-history batter/pitcher over-index={evidence['lowHistoryOverIndex']:.2f}")
    if evidence.get("roleOverIndex", 1.0) and evidence["roleOverIndex"] >= 1.3:
        categories.append("ROLE_OR_POSITION_RELATED")
        reasons.append(f"role/position over-index={evidence['roleOverIndex']:.2f}")
    if evidence.get("earlySeasonOverIndex", 1.0) and evidence["earlySeasonOverIndex"] >= 1.15:
        categories.append("TEMPORALLY_RELATED")
        reasons.append(f"early-season over-index={evidence['earlySeasonOverIndex']:.2f}")
    if evidence.get("outcomeConcentrated"):
        reasons.append("severe misses over-index strongly on specific outcome classes")
    primary = categories[0]
    return {"primaryCategory": primary, "allCategories": sorted(set(categories)), "reasons": reasons}


def priority_row(name: str, impact: int, repeatability: int, detectability: int, ease: int, betting: int, availability: int, correction: str) -> dict[str, Any]:
    for score in (impact, repeatability, detectability, ease, betting, availability):
        if not 1 <= score <= 5:
            raise ValueError("priority scores must be 1-5")
    return {
        "pattern": name,
        "impactOnTotalLoss": impact,
        "repeatabilityAcrossYears": repeatability,
        "prePredictionDetectability": detectability,
        "easeOfCorrection": ease,
        "bettingRelevance": betting,
        "dataAvailability": availability,
        "totalScore": impact + repeatability + detectability + ease + betting + availability,
        "proposedCorrection": correction,
    }


__all__ = [
    "FORENSIC_CONTRACT_NAME",
    "FORENSIC_SCHEMA_VERSION",
    "MIN_SEGMENT_ROWS",
    "individual_log_loss",
    "individual_brier",
    "distribution_summary",
    "pareto_concentration",
    "severe_masks",
    "over_index",
    "confusion_pairs",
    "segment_metrics",
    "probability_resolution",
    "tail_sensitivity",
    "ood_scores",
    "ood_band_severe_rate",
    "severe_miss_classifier",
    "randomness_verdict",
    "priority_row",
]
