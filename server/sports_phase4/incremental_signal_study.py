"""Phase 4E controlled E1/E2 incremental-signal study (feature ablation only).

This module isolates the *feature value* of the governed E1 pitch-sequence process
family and the E2 batter x pitcher process-interaction family on top of the frozen
D3 dynamic-state PA model. It trains three branches under an identical population,
identical fold-local preprocessing, and the identical fixed D3 regularization
(``C=0.05`` multinomial l2 logistic, lbfgs) so that the ONLY difference between the
branches is the feature set:

    A = D3                         (context + batter_b + pitcher_b cumulative state)
    B = D3 + E1                    (+ 48 numeric pitch-sequence process features)
    C = D3 + E1 + E2               (+ 25 numeric process-interaction features)

It performs NO grid search, NO hyperparameter tuning, NO algorithm tournament, NO
label-based feature selection, NO calibration search, and NO archetype/E6 work.
Every learned transform (imputation, standardization) is fit only on the training
fold. 2025 is never used for selection -- there is nothing to select (fixed policy).

All estimation reuses the governed primitives (``_fit_logistic``, ``evaluate_multiclass``,
``game_cluster_bootstrap``) so the branches inherit D3's exact model contract; Branch A
reproduces the frozen D3 log loss (2024=1.476588, 2025=1.474100) as a correctness anchor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from server.sports_modeling.bootstrap import game_cluster_bootstrap
from server.sports_modeling.feature_contract import CONTEXT_FEATURES
from server.sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    evaluate_multiclass,
    per_row_log_loss,
)
from server.sports_modeling.training import (
    DEFAULT_MAX_ITER,
    TrainingArrays,
    TrainingIntegrityError,
    _fit_logistic,
)
from server.sports_phase4.dynamic_contract import STATE_VALUE_COLUMNS

STUDY_CONTRACT_NAME = "MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_V1"
STUDY_SCHEMA_VERSION = "MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_V1"
FIXED_C = 0.05
FOLD_2024_ID = "ablation-train-2023-validate-2024"
FOLD_2025_ID = "ablation-train-through-2024-validate-2025"
BOOTSTRAP_RESAMPLES = 500
BOOTSTRAP_SEED = 20_260_817
CATASTROPHIC_THRESHOLDS: tuple[float, ...] = (0.005, 0.01, 0.02, 0.05)

# Frozen D3 authority log loss -- Branch A must reproduce these exactly.
D3_FROZEN_LOGLOSS: Mapping[int, float] = {2024: 1.476588, 2025: 1.474100}
ANCHOR_TOLERANCE = 5e-6

# Transparent practical-significance thresholds on RELATIVE improvement of a loss.
PRACTICAL_BANDS: tuple[tuple[str, float], ...] = (
    ("NEGLIGIBLE", 0.001),   # < 0.1%
    ("SMALL", 0.005),        # 0.1% - 0.5%
    ("MEANINGFUL", 0.02),    # 0.5% - 2%
    ("LARGE", float("inf")),  # > 2%
)

# Bootstrap probability at/above which a same-direction gain is treated as decisive.
DECISIVE_BOOTSTRAP_PROBABILITY = 0.975

BATTER_B_FEATURES: tuple[str, ...] = tuple(f"batter_b_{name}" for name in STATE_VALUE_COLUMNS)
PITCHER_B_FEATURES: tuple[str, ...] = tuple(f"pitcher_b_{name}" for name in STATE_VALUE_COLUMNS)
D3_FEATURES: tuple[str, ...] = tuple(CONTEXT_FEATURES) + BATTER_B_FEATURES + PITCHER_B_FEATURES


class IncrementalStudyError(RuntimeError):
    """Raised when the feature-ablation study cannot prove its frozen, comparable inputs."""


@dataclass(frozen=True)
class BranchFolds:
    branch_id: str
    feature_names: tuple[str, ...]
    probabilities: dict[int, np.ndarray]
    metrics: dict[int, dict[str, Any]]
    n_iter: dict[int, int]
    runtime_seconds: float


def branch_feature_names(
    branch_id: str,
    e1_features: Sequence[str],
    e2_features: Sequence[str],
) -> tuple[str, ...]:
    """Exact, order-stable feature composition for A/B/C. No label-based selection."""

    if branch_id == "A":
        return tuple(D3_FEATURES)
    if branch_id == "B":
        return tuple(D3_FEATURES) + tuple(e1_features)
    if branch_id == "C":
        return tuple(D3_FEATURES) + tuple(e1_features) + tuple(e2_features)
    raise IncrementalStudyError(f"unknown branch id: {branch_id}")


def _fold_masks(seasons: np.ndarray) -> dict[str, np.ndarray]:
    masks = {season: seasons == season for season in (2023, 2024, 2025)}
    if any(not np.any(mask) for mask in masks.values()):
        raise IncrementalStudyError("all three frozen seasons must contain rows")
    return {
        "2023": masks[2023],
        "2024": masks[2024],
        "2025": masks[2025],
        "train_2024": masks[2023],
        "train_2025": masks[2023] | masks[2024],
    }


def train_branch(
    arrays: TrainingArrays,
    branch_id: str,
    feature_names: Sequence[str],
    *,
    c_value: float = FIXED_C,
    max_iter: int = DEFAULT_MAX_ITER,
    progress: Any | None = None,
) -> BranchFolds:
    """Fit the two rolling-origin folds for one branch under the fixed D3 policy."""

    import time

    features = tuple(feature_names)
    if len(set(features)) != len(features):
        raise IncrementalStudyError(f"branch {branch_id} has duplicate feature columns")
    masks = _fold_masks(arrays.seasons)
    probabilities: dict[int, np.ndarray] = {}
    metrics: dict[int, dict[str, Any]] = {}
    n_iter: dict[int, int] = {}
    started = time.perf_counter()
    for season, train_key in ((2024, "train_2024"), (2025, "train_2025")):
        if progress is not None:
            progress(
                "FITTING_ABLATION_BRANCH",
                {"branch": branch_id, "validationSeason": season, "features": len(features), "C": c_value},
            )
        try:
            model, iterations, _ = _fit_logistic(
                arrays, features, masks[train_key], c_value=c_value, max_iter=max_iter
            )
        except TrainingIntegrityError as exc:
            raise IncrementalStudyError(f"branch {branch_id} fold {season}: {exc}") from exc
        probs = model.predict_proba(arrays.feature_values, masks[str(season)])
        probabilities[season] = probs
        metrics[season] = evaluate_multiclass(arrays.labels[masks[str(season)]], probs)
        n_iter[season] = iterations
    return BranchFolds(
        branch_id=branch_id,
        feature_names=features,
        probabilities=probabilities,
        metrics=metrics,
        n_iter=n_iter,
        runtime_seconds=round(time.perf_counter() - started, 3),
    )


def verify_branch_a_anchor(branch_a: BranchFolds) -> dict[str, Any]:
    """Confirm Branch A reproduces the frozen D3 log loss within tolerance."""

    checks = {}
    reproduced = True
    for season in (2024, 2025):
        observed = float(branch_a.metrics[season]["logLoss"])
        expected = D3_FROZEN_LOGLOSS[season]
        ok = abs(observed - expected) <= ANCHOR_TOLERANCE
        reproduced = reproduced and ok
        checks[str(season)] = {
            "observedLogLoss": observed,
            "frozenLogLoss": expected,
            "absoluteDifference": abs(observed - expected),
            "reproduced": ok,
        }
    return {
        "tolerance": ANCHOR_TOLERANCE,
        "reproducedBothFolds": reproduced,
        "perSeason": checks,
    }


def _practical_band(relative_improvement: float) -> str:
    if relative_improvement <= 0.0:
        return "NONE_OR_WORSE"
    magnitude = relative_improvement
    for name, upper in PRACTICAL_BANDS:
        if magnitude < upper:
            return name
    return "LARGE"


def incremental_table(
    branches: Mapping[str, BranchFolds],
    labels_by_season: Mapping[int, np.ndarray],
) -> dict[str, Any]:
    """Direct A/B/C log-loss and Brier comparison with signed deltas + relative gains."""

    rows: list[dict[str, Any]] = []
    for season in (2024, 2025):
        a = branches["A"].metrics[season]
        b = branches["B"].metrics[season]
        c = branches["C"].metrics[season]
        entry = {
            "validationSeason": season,
            "logLoss": {"A": a["logLoss"], "B": b["logLoss"], "C": c["logLoss"]},
            "brierScore": {"A": a["brierScore"], "B": b["brierScore"], "C": c["brierScore"]},
            "topLabelEce": {"A": a["topLabelEce"], "B": b["topLabelEce"], "C": c["topLabelEce"]},
            "featureCount": {
                "A": len(branches["A"].feature_names),
                "B": len(branches["B"].feature_names),
                "C": len(branches["C"].feature_names),
            },
            "deltas": {
                "B_minus_A": {
                    "logLoss": b["logLoss"] - a["logLoss"],
                    "brier": b["brierScore"] - a["brierScore"],
                    "relativeLogLoss": (a["logLoss"] - b["logLoss"]) / a["logLoss"],
                    "relativeBrier": (a["brierScore"] - b["brierScore"]) / a["brierScore"],
                },
                "C_minus_B": {
                    "logLoss": c["logLoss"] - b["logLoss"],
                    "brier": c["brierScore"] - b["brierScore"],
                    "relativeLogLoss": (b["logLoss"] - c["logLoss"]) / b["logLoss"],
                    "relativeBrier": (b["brierScore"] - c["brierScore"]) / b["brierScore"],
                },
                "C_minus_A": {
                    "logLoss": c["logLoss"] - a["logLoss"],
                    "brier": c["brierScore"] - a["brierScore"],
                    "relativeLogLoss": (a["logLoss"] - c["logLoss"]) / a["logLoss"],
                    "relativeBrier": (a["brierScore"] - c["brierScore"]) / a["brierScore"],
                },
            },
        }
        entry["practicalBands"] = {
            "B_minus_A_logLoss": _practical_band(entry["deltas"]["B_minus_A"]["relativeLogLoss"]),
            "C_minus_B_logLoss": _practical_band(entry["deltas"]["C_minus_B"]["relativeLogLoss"]),
            "C_minus_A_logLoss": _practical_band(entry["deltas"]["C_minus_A"]["relativeLogLoss"]),
        }
        rows.append(entry)
    return {
        "differenceConvention": "NEGATIVE_LOGLOSS_OR_BRIER_DELTA_MEANS_IMPROVEMENT",
        "relativeConvention": "POSITIVE_RELATIVE_MEANS_IMPROVEMENT",
        "practicalBandDefinition": {name: upper for name, upper in PRACTICAL_BANDS},
        "rows": rows,
    }


def classwise_table(
    branches: Mapping[str, BranchFolds],
    labels_by_season: Mapping[int, np.ndarray],
) -> dict[str, Any]:
    """Per-class observed/predicted/loss/calibration for A/B/C x 2024/2025."""

    rows: list[dict[str, Any]] = []
    for season in (2024, 2025):
        labels = labels_by_season[season]
        encoded = encode_labels(labels)
        for class_index, class_name in enumerate(PA_CLASS_ORDER):
            class_mask = encoded == class_index
            observed_count = int(class_mask.sum())
            observed_rate = float(class_mask.mean())
            per_branch: dict[str, Any] = {}
            for branch_id in ("A", "B", "C"):
                metrics = branches[branch_id].metrics[season]
                probs = branches[branch_id].probabilities[season]
                # class-conditional log loss = mean -log(p_true) over rows whose true class = k.
                if observed_count:
                    cond_ll = float(
                        per_row_log_loss(encoded[class_mask], probs[class_mask]).mean()
                    )
                else:
                    cond_ll = None
                per_branch[branch_id] = {
                    "meanPredictedProbability": float(probs[:, class_index].mean()),
                    "classConditionalLogLoss": cond_ll,
                    "classwiseBrier": metrics["classwiseBrier"][class_name],
                    "classwiseEce": metrics["classwiseEce"][class_name],
                    "recall": metrics["perClass"][class_name]["recall"],
                    "precision": metrics["perClass"][class_name]["precision"],
                    "f1": metrics["perClass"][class_name]["f1"],
                }
            rows.append(
                {
                    "validationSeason": season,
                    "class": class_name,
                    "observedCount": observed_count,
                    "observedRate": observed_rate,
                    "branches": per_branch,
                    "classConditionalLogLossDelta": {
                        "B_minus_A": (
                            per_branch["B"]["classConditionalLogLoss"]
                            - per_branch["A"]["classConditionalLogLoss"]
                            if observed_count
                            else None
                        ),
                        "C_minus_B": (
                            per_branch["C"]["classConditionalLogLoss"]
                            - per_branch["B"]["classConditionalLogLoss"]
                            if observed_count
                            else None
                        ),
                    },
                }
            )
    return {"classOrder": list(PA_CLASS_ORDER), "rows": rows}


def focused_class_analysis(
    class_name: str,
    branches: Mapping[str, BranchFolds],
    labels_by_season: Mapping[int, np.ndarray],
) -> dict[str, Any]:
    """Dedicated A/B/C comparison for a single outcome class (e.g. STRIKEOUT)."""

    class_index = PA_CLASS_ORDER.index(class_name)
    seasons: dict[str, Any] = {}
    for season in (2024, 2025):
        labels = labels_by_season[season]
        encoded = encode_labels(labels)
        class_mask = encoded == class_index
        observed_rate = float(class_mask.mean())
        branch_rows: dict[str, Any] = {}
        for branch_id in ("A", "B", "C"):
            probs = branches[branch_id].probabilities[season]
            metrics = branches[branch_id].metrics[season]
            cond_probs = probs[class_mask, class_index]
            branch_rows[branch_id] = {
                "meanPredictedProbability": float(probs[:, class_index].mean()),
                "meanPredictedProbabilityOnTrueRows": (
                    float(cond_probs.mean()) if class_mask.any() else None
                ),
                "classConditionalLogLoss": (
                    float(per_row_log_loss(encoded[class_mask], probs[class_mask]).mean())
                    if class_mask.any()
                    else None
                ),
                "classwiseBrier": metrics["classwiseBrier"][class_name],
                "classwiseEce": metrics["classwiseEce"][class_name],
                "recall": metrics["perClass"][class_name]["recall"],
                "precision": metrics["perClass"][class_name]["precision"],
                # catastrophic underprediction of the class on rows where it occurred.
                "trueRowsBelow2pct": (
                    int((cond_probs < 0.02).sum()) if class_mask.any() else 0
                ),
            }
        seasons[str(season)] = {
            "observedRate": observed_rate,
            "branches": branch_rows,
            "classConditionalLogLossDelta": {
                "B_minus_A": branch_rows["B"]["classConditionalLogLoss"]
                - branch_rows["A"]["classConditionalLogLoss"],
                "C_minus_B": branch_rows["C"]["classConditionalLogLoss"]
                - branch_rows["B"]["classConditionalLogLoss"],
                "C_minus_A": branch_rows["C"]["classConditionalLogLoss"]
                - branch_rows["A"]["classConditionalLogLoss"],
            },
        }
    return {"class": class_name, "seasons": seasons}


def catastrophic_analysis(
    branches: Mapping[str, BranchFolds],
    labels_by_season: Mapping[int, np.ndarray],
) -> dict[str, Any]:
    """Rows whose realized outcome received a tiny probability, by branch/season."""

    rows: list[dict[str, Any]] = []
    for season in (2024, 2025):
        labels = labels_by_season[season]
        encoded = encode_labels(labels)
        for branch_id in ("A", "B", "C"):
            probs = branches[branch_id].probabilities[season]
            true_prob = probs[np.arange(encoded.size), encoded]
            row_ll = per_row_log_loss(encoded, probs)
            total_ll = float(row_ll.sum())
            thresholds = []
            for threshold in CATASTROPHIC_THRESHOLDS:
                hit = true_prob < threshold
                count = int(hit.sum())
                class_counts = {
                    PA_CLASS_ORDER[k]: int(((encoded == k) & hit).sum())
                    for k in range(len(PA_CLASS_ORDER))
                }
                thresholds.append(
                    {
                        "threshold": threshold,
                        "count": count,
                        "rowShare": count / encoded.size,
                        "logLossShare": (float(row_ll[hit].sum()) / total_ll) if total_ll else 0.0,
                        "classComposition": class_counts,
                    }
                )
            rows.append({"validationSeason": season, "branch": branch_id, "thresholds": thresholds})
    return {"thresholds": list(CATASTROPHIC_THRESHOLDS), "rows": rows}


def bootstrap_comparisons(
    branches: Mapping[str, BranchFolds],
    labels_by_season: Mapping[int, np.ndarray],
    game_ids_by_season: Mapping[int, np.ndarray],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
    progress: Any | None = None,
) -> list[dict[str, Any]]:
    """Whole-game cluster bootstrap for B-A, C-B, C-A on log loss + Brier."""

    comparisons = (("B", "A"), ("C", "B"), ("C", "A"))
    out: list[dict[str, Any]] = []
    for season in (2024, 2025):
        labels = labels_by_season[season]
        game_ids = game_ids_by_season[season]
        for selected, comparator in comparisons:
            if progress is not None:
                progress(
                    "GAME_CLUSTER_BOOTSTRAP",
                    {"validationSeason": season, "selected": selected, "comparator": comparator, "resamples": n_resamples},
                )
            evidence = game_cluster_bootstrap(
                labels,
                branches[selected].probabilities[season],
                branches[comparator].probabilities[season],
                game_ids,
                n_resamples=n_resamples,
                seed=seed,
            )
            out.append(
                {
                    "validationSeason": season,
                    "selected": selected,
                    "comparator": comparator,
                    "clusterUnit": "game_id",
                    "resamples": n_resamples,
                    "seed": seed,
                    "logLoss": {
                        "pointEstimate": evidence["logLossDifference"]["pointEstimate"],
                        "ci95": evidence["logLossDifference"]["percentileInterval"],
                        "probabilitySelectedBetter": evidence["logLossDifference"]["probabilitySelectedBetter"],
                    },
                    "brier": {
                        "pointEstimate": evidence["brierScoreDifference"]["pointEstimate"],
                        "ci95": evidence["brierScoreDifference"]["percentileInterval"],
                        "probabilitySelectedBetter": evidence["brierScoreDifference"]["probabilitySelectedBetter"],
                    },
                }
            )
    return out


def _temporal_flag(delta_2024: float, delta_2025: float) -> str:
    # delta = new relative improvement (positive means better).
    improves_2024 = delta_2024 > 0.0
    improves_2025 = delta_2025 > 0.0
    if improves_2024 and improves_2025:
        return "IMPROVES_BOTH_YEARS"
    if improves_2024 and not improves_2025:
        return "IMPROVES_2024_ONLY"
    if improves_2025 and not improves_2024:
        return "IMPROVES_2025_ONLY"
    return "WORSE"


def _bootstrap_lookup(bootstrap: Sequence[Mapping[str, Any]], selected: str, comparator: str, season: int) -> Mapping[str, Any]:
    for row in bootstrap:
        if row["selected"] == selected and row["comparator"] == comparator and row["validationSeason"] == season:
            return row
    raise IncrementalStudyError(f"bootstrap row missing for {selected}-{comparator} {season}")


def decide_feature_value(
    incremental: Mapping[str, Any],
    bootstrap: Sequence[Mapping[str, Any]],
    strikeout: Mapping[str, Any],
) -> dict[str, Any]:
    """Assign the frozen E1 and E2 verdict enums from all evidence dimensions."""

    def rel(season: int, comparison: str) -> float:
        for row in incremental["rows"]:
            if row["validationSeason"] == season:
                return row["deltas"][comparison]["relativeLogLoss"]
        raise IncrementalStudyError("incremental row missing")

    # ---- E1 (B vs A) ----
    e1_rel = {season: rel(season, "B_minus_A") for season in (2024, 2025)}
    e1_flag = _temporal_flag(e1_rel[2024], e1_rel[2025])
    e1_boot = {season: _bootstrap_lookup(bootstrap, "B", "A", season)["logLoss"]["probabilitySelectedBetter"] for season in (2024, 2025)}
    e1_bands = {season: _practical_band(max(e1_rel[season], 0.0)) for season in (2024, 2025)}
    e1_decisive = all(e1_boot[s] >= DECISIVE_BOOTSTRAP_PROBABILITY for s in (2024, 2025))
    e1_meaningful = all(e1_bands[s] in ("SMALL", "MEANINGFUL", "LARGE") for s in (2024, 2025))
    if e1_flag == "WORSE":
        e1_decision = "E1_PREDICTIVE_VALUE_NEGATIVE"
    elif e1_flag == "IMPROVES_BOTH_YEARS" and e1_decisive and e1_meaningful:
        e1_decision = "E1_PREDICTIVE_VALUE_CONFIRMED"
    elif e1_flag == "IMPROVES_BOTH_YEARS" and e1_decisive:
        e1_decision = "E1_PREDICTIVE_VALUE_MARGINAL"
    else:
        e1_decision = "E1_PREDICTIVE_VALUE_NOT_CONFIRMED"

    # ---- E2 (C vs B) ----
    e2_rel = {season: rel(season, "C_minus_B") for season in (2024, 2025)}
    e2_flag = _temporal_flag(e2_rel[2024], e2_rel[2025])
    e2_boot = {season: _bootstrap_lookup(bootstrap, "C", "B", season)["logLoss"]["probabilitySelectedBetter"] for season in (2024, 2025)}
    e2_bands = {season: _practical_band(max(e2_rel[season], 0.0)) for season in (2024, 2025)}
    e2_decisive = all(e2_boot[s] >= DECISIVE_BOOTSTRAP_PROBABILITY for s in (2024, 2025))
    e2_meaningful = all(e2_bands[s] in ("SMALL", "MEANINGFUL", "LARGE") for s in (2024, 2025))
    if e2_flag == "WORSE":
        e2_decision = "E2_INCREMENTAL_VALUE_NEGATIVE"
    elif e2_flag == "IMPROVES_BOTH_YEARS" and e2_decisive and e2_meaningful:
        e2_decision = "E2_INCREMENTAL_VALUE_CONFIRMED"
    elif e2_flag == "IMPROVES_BOTH_YEARS" and e2_decisive:
        e2_decision = "E2_INCREMENTAL_VALUE_MARGINAL"
    else:
        e2_decision = "E2_INCREMENTAL_VALUE_NOT_CONFIRMED"

    # Whether the improvement is STRIKEOUT-concentrated (class-conditional log loss).
    so_improved_both = all(
        strikeout["seasons"][str(s)]["classConditionalLogLossDelta"]["B_minus_A"] < 0.0
        for s in (2024, 2025)
    )

    return {
        "e1": {
            "decision": e1_decision,
            "temporalFlag": e1_flag,
            "relativeLogLossGain": {str(s): e1_rel[s] for s in (2024, 2025)},
            "bootstrapProbabilityBetter": {str(s): e1_boot[s] for s in (2024, 2025)},
            "practicalBand": {str(s): e1_bands[s] for s in (2024, 2025)},
        },
        "e2": {
            "decision": e2_decision,
            "temporalFlag": e2_flag,
            "relativeLogLossGain": {str(s): e2_rel[s] for s in (2024, 2025)},
            "bootstrapProbabilityBetter": {str(s): e2_boot[s] for s in (2024, 2025)},
            "practicalBand": {str(s): e2_bands[s] for s in (2024, 2025)},
        },
        "strikeoutConcentration": {
            "e1ImprovesStrikeoutBothYears": so_improved_both,
        },
        "decisiveBootstrapProbability": DECISIVE_BOOTSTRAP_PROBABILITY,
    }


def next_step_path(decision: Mapping[str, Any]) -> dict[str, Any]:
    """Choose exactly one recommended next path from the frozen decision tree."""

    e1 = decision["e1"]["decision"]
    e2 = decision["e2"]["decision"]
    e1_helps = e1 in ("E1_PREDICTIVE_VALUE_CONFIRMED", "E1_PREDICTIVE_VALUE_MARGINAL")
    e2_helps = e2 in ("E2_INCREMENTAL_VALUE_CONFIRMED", "E2_INCREMENTAL_VALUE_MARGINAL")
    strikeout_only = (
        decision["strikeoutConcentration"]["e1ImprovesStrikeoutBothYears"]
        and not e1_helps
    )
    if e1_helps and e2_helps:
        path = "PATH_1"
        summary = "E6 handedness/platoon, then archetypes, then algorithm tournament."
    elif e1_helps and not e2_helps:
        path = "PATH_2"
        summary = "E6, then nonlinear algorithm tournament; do not expand manual E2 aggressively."
    elif strikeout_only:
        path = "PATH_4"
        summary = "Retain E1/E2 for K-related component modeling; consider multitask/specialized outcome architecture; do not assume universal PA benefit."
    else:
        path = "PATH_3"
        summary = "Stop expanding free pitch-sequence engineering; prioritize E6 and/or a premium-data trial; do not build E1 V2 without a specific failure hypothesis."
    return {
        "recommendedPath": path,
        "summary": summary,
        "e6ShouldProceed": path in ("PATH_1", "PATH_2", "PATH_3"),
        "archetypesShouldProceed": path == "PATH_1",
        "algorithmTournamentShouldProceed": path in ("PATH_1", "PATH_2"),
        "premiumDataPriorityRaised": path in ("PATH_3", "PATH_4"),
    }


__all__ = [
    "STUDY_CONTRACT_NAME",
    "STUDY_SCHEMA_VERSION",
    "FIXED_C",
    "D3_FEATURES",
    "BATTER_B_FEATURES",
    "PITCHER_B_FEATURES",
    "BranchFolds",
    "IncrementalStudyError",
    "branch_feature_names",
    "train_branch",
    "verify_branch_a_anchor",
    "incremental_table",
    "classwise_table",
    "focused_class_analysis",
    "catastrophic_analysis",
    "bootstrap_comparisons",
    "decide_feature_value",
    "next_step_path",
]
