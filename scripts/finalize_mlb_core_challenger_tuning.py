"""Freeze the completed compact tuning decision without selecting a champion."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
os.environ.setdefault("ATLAS_SECURITY_ROOT", str(RUNTIME_ROOT / "security"))
os.environ.setdefault(
    "ATLAS_SECURITY_DB_PATH", str(RUNTIME_ROOT / "security" / "asp_model_studio_security.db")
)

from server.persistence.db import Database, now_iso
from server.sports_current_statcast.mlb_core_challenger_tuning import (
    FIRST_SCREEN_BENCHMARKS,
    NULL_BASELINE,
    PROJECT_ID,
    TUNING_BATCH_NAME,
    TUNING_SCHEMA_VERSION,
    exact_grids,
    paired_game_cluster_bootstrap,
    read_oof,
    runtime_estimate,
)
from server.sports_current_statcast.stage3_candidate_evaluation import (
    _persist_object,
    candidate_specification_fingerprint,
)
from server.sports_current_statcast.stage3_model_laboratory import (
    RUN_RECEIPT_SCHEMA_VERSION_V2,
    _read_runs,
    resolve_model_lab_authority,
)
from server.sports_current_statcast.stage3_model_jobs import list_model_development_jobs


DATABASE_PATH = RUNTIME_ROOT / "persistence" / "asp_model_studio.db"
STATIC_DECISION_PATH = REPOSITORY_ROOT / Path(
    "server/sports_current_statcast/mlb_core_challenger_tuning_decision_v1.json"
)
PRACTICAL_LOG_LOSS_THRESHOLD = 0.0001


def _complexity_score(candidate: Mapping[str, Any]) -> float:
    parameters = candidate.get("hyperparameters") or {}
    if candidate.get("modelFamily") == "histogram_gradient_boosting":
        return float(parameters["max_iter"]) * float(parameters["max_leaf_nodes"])
    depth = parameters.get("max_depth")
    depth_factor = 64.0 if depth is None else float(depth)
    feature_factor = 1.0 if parameters.get("max_features") == "sqrt" else 2.0
    return float(parameters["n_estimators"]) * depth_factor * feature_factor


def _candidate_summary(
    run: Mapping[str, Any],
    candidate: Mapping[str, Any],
    candidate_receipts: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    folds = candidate.get("folds") or []
    return {
        "candidateId": candidate.get("candidateId"),
        "candidateFingerprint": candidate_specification_fingerprint(run, candidate),
        "candidateReceiptSha256": (candidate_receipts or {}).get(
            str(candidate.get("candidateId") or "")
        ),
        "immutableModelRunReceiptSha256": run.get("runReceiptSha256"),
        "modelFamily": candidate.get("modelFamily"),
        "hyperparameters": candidate.get("hyperparameters"),
        "meanOofLogLoss": candidate.get("meanOofLogLoss"),
        "worstFoldLogLoss": (candidate.get("foldStability") or {}).get("maximumFoldLogLoss"),
        "foldStandardDeviation": (candidate.get("foldStability") or {}).get("logLossStdDev"),
        "summedBrier": candidate.get("summedBrier"),
        "ece": candidate.get("ece"),
        "macroOvrRocAuc": candidate.get("macroOvrRocAuc"),
        "classMetrics": candidate.get("classCalibration") or [],
        "folds": [
            {
                "foldNumber": fold.get("foldNumber"),
                "trainStart": fold.get("trainStart"),
                "trainEnd": fold.get("trainEnd"),
                "validationStart": fold.get("validationStart"),
                "validationEnd": fold.get("validationEnd"),
                "trainRows": fold.get("trainRows"),
                "validationRows": fold.get("validationRows"),
                "multiclassLogLoss": (fold.get("metrics") or {}).get("multiclassLogLoss"),
                "summedBrier": (fold.get("metrics") or {}).get("summedBrier"),
                "ece": (fold.get("metrics") or {}).get("ece"),
                "macroOvrRocAuc": (fold.get("metrics") or {}).get("macroOvrRocAuc"),
                "runtimeMs": fold.get("runtimeMs"),
                "probabilityReconciliation": fold.get("probabilityReconciliation"),
            }
            for fold in folds
        ],
        "modelComplexity": candidate.get("modelComplexity"),
        "complexityScore": _complexity_score(candidate),
        "runtimeMs": candidate.get("runtimeMs"),
        "memoryEvidence": candidate.get("memoryEvidence"),
        "probabilityReconciliation": candidate.get("probabilityReconciliation"),
        "oofArtifact": candidate.get("evaluationEvidence"),
        "foldLocalPreprocessingVerified": all(
            (fold.get("preprocessing") or {}).get("validationRowsUsedForParameters") == 0
            and (fold.get("preprocessing") or {}).get("finalOotRowsUsedForParameters") == 0
            for fold in folds
        ),
    }


def _select_family(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        candidates,
        key=lambda item: (
            float(item["meanOofLogLoss"]),
            float((item.get("foldStability") or {}).get("maximumFoldLogLoss") or np.inf),
            float((item.get("foldStability") or {}).get("logLossStdDev") or np.inf),
            _complexity_score(item),
        ),
    )
    best_loss = float(ranked[0]["meanOofLogLoss"])
    practically_tied = [
        item
        for item in ranked
        if float(item["meanOofLogLoss"]) - best_loss <= PRACTICAL_LOG_LOSS_THRESHOLD
    ]
    return min(
        practically_tied,
        key=lambda item: (
            _complexity_score(item),
            float(item["runtimeMs"]),
            float(item["meanOofLogLoss"]),
        ),
    )


def _probability_diversity(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    left_frame = read_oof(left)
    right_frame = read_oof(right)
    identity = ["canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex"]
    merged = left_frame.merge(
        right_frame,
        on=identity,
        how="inner",
        validate="one_to_one",
        suffixes=("_left", "_right"),
    )
    probability_columns = [name for name in left_frame.columns if name.startswith("probability_")]
    left_values = np.column_stack(
        [merged[f"{name}_left"].to_numpy(dtype=float) for name in probability_columns]
    )
    right_values = np.column_stack(
        [merged[f"{name}_right"].to_numpy(dtype=float) for name in probability_columns]
    )
    return {
        "rowCount": int(len(merged)),
        "meanAbsoluteProbabilityDifference": float(np.mean(np.abs(left_values - right_values))),
        "meanTotalVariationDistance": float(np.mean(np.abs(left_values - right_values).sum(axis=1) / 2.0)),
        "predictedClassDisagreementRate": float(
            np.mean(left_values.argmax(axis=1) != right_values.argmax(axis=1))
        ),
        "finalOotTargetAccessed": False,
    }


def _refit_baseline_candidate(
    candidates: list[dict[str, Any]], family: str
) -> dict[str, Any]:
    expected = exact_grids()[family][1 if family == "histogram_gradient_boosting" else 0]
    matching = [
        item
        for item in candidates
        if item.get("hyperparameters") == expected
    ]
    if len(matching) != 1:
        raise RuntimeError(f"The tuning run lacks one exact re-fitted {family} benchmark.")
    return matching[0]


def _immutable_first_screen_candidate(
    runs: list[dict[str, Any]], family: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected = FIRST_SCREEN_BENCHMARKS[family]["candidateFingerprint"]
    matches = [
        (run, dict(candidate))
        for run in runs
        for candidate in run.get("candidates") or []
        if candidate.get("status") == "COMPLETE"
        and candidate.get("modelFamily") == family
        and candidate_specification_fingerprint(run, candidate) == expected
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one exact immutable {family} first-screen candidate; found {len(matches)}."
        )
    return matches[0]

def main() -> None:
    database = Database(DATABASE_PATH)
    resolved = resolve_model_lab_authority(database, PROJECT_ID)
    all_runs = [dict(item) for item in _read_runs(PROJECT_ID, resolved)]
    tuning_runs = [
        dict(item)
        for item in all_runs
        if item.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION_V2
        and (item.get("plan") or {}).get("batchName") == TUNING_BATCH_NAME
    ]
    complete_runs = [
        item
        for item in tuning_runs
        if item.get("status") == "COMPLETE"
        and len(item.get("candidates") or []) == 5
        and all(
            candidate.get("status") == "COMPLETE"
            for candidate in item.get("candidates") or []
        )
    ]
    if len(complete_runs) != 1:
        raise RuntimeError(
            "Expected exactly one complete compact tuning run; "
            f"found {len(complete_runs)} among {len(tuning_runs)} terminal attempts."
        )
    run = complete_runs[0]
    jobs = list_model_development_jobs(database, PROJECT_ID)["jobs"]
    jobs_by_model_run = {
        str((item.get("artifacts") or {}).get("runId") or ""): item
        for item in jobs
        if (item.get("artifacts") or {}).get("runId")
    }
    model_job = jobs_by_model_run.get(str(run.get("runId") or ""))
    if model_job is None:
        raise RuntimeError("The complete tuning run does not resolve to its project job ledger.")
    model_job_id = model_job.get("jobId")
    job_candidate_receipts = {
        str(item.get("candidateId") or ""): str(item.get("candidateReceiptSha256") or "")
        for item in (model_job.get("artifacts") or {}).get("completedCandidateReceipts") or []
        if item.get("candidateId") and item.get("candidateReceiptSha256")
    }
    candidate_receipts = {
        str(item.get("candidateId") or ""): str(item.get("candidateReceiptSha256") or "")
        for item in run.get("candidateAttemptReceipts") or []
        if item.get("candidateId") and item.get("candidateReceiptSha256")
    }
    if candidate_receipts != job_candidate_receipts:
        raise RuntimeError("The model run and project job disagree on candidate receipt identities.")
    prior_attempts = [
        {
            "modelRunId": item.get("runId"),
            "modelRunReceiptSha256": item.get("runReceiptSha256"),
            "status": item.get("status"),
            "completedFits": sum(
                int(candidate.get("foldsCompleted") or 0)
                for candidate in item.get("candidates") or []
            ),
            "failureReasons": sorted(
                {
                    str(candidate.get("errorReason"))
                    for candidate in item.get("candidates") or []
                    if candidate.get("errorReason")
                }
            ),
            "modelJobId": (
                jobs_by_model_run.get(str(item.get("runId") or "")) or {}
            ).get("jobId"),
            "usedForSelection": False,
        }
        for item in tuning_runs
        if item.get("runReceiptSha256") != run.get("runReceiptSha256")
    ]
    run_population = run.get("population") or {}
    if (
        run.get("status") != "COMPLETE"
        or run_population.get("finalOotLocked") is not True
        or run_population.get("finalOotTargetAccessed") is not False
        or run_population.get("finalOotScored") is not False
        or run.get("finalOotAccessed") is not False
        or run.get("finalOotTargetsMaterialized") is not False
    ):
        raise RuntimeError("The compact tuning run is incomplete or violated Final OOT authority.")
    candidates = [dict(item) for item in run.get("candidates") or []]
    if len(candidates) != 5 or any(item.get("status") != "COMPLETE" for item in candidates):
        raise RuntimeError("The official tuning comparison requires five complete configurations.")
    if set(candidate_receipts) != {
        str(item.get("candidateId") or "") for item in candidates
    } or any(len(receipt) != 64 for receipt in candidate_receipts.values()):
        raise RuntimeError("The five tuning candidates do not reconcile to immutable job receipts.")
    by_family = {
        family: [item for item in candidates if item.get("modelFamily") == family]
        for family in ("histogram_gradient_boosting", "random_forest")
    }
    if len(by_family["histogram_gradient_boosting"]) != 3 or len(by_family["random_forest"]) != 2:
        raise RuntimeError("The terminal tuning run does not reconcile to the frozen 3+2 grid.")
    best = {family: _select_family(items) for family, items in by_family.items()}
    refit_baselines = {
        family: _refit_baseline_candidate(items, family)
        for family, items in by_family.items()
    }
    immutable_first_screen = {
        family: _immutable_first_screen_candidate(all_runs, family)
        for family in by_family
    }
    summaries = {
        family: _candidate_summary(run, candidate, candidate_receipts)
        for family, candidate in best.items()
    }
    refit_baseline_summaries = {
        family: _candidate_summary(run, candidate, candidate_receipts)
        for family, candidate in refit_baselines.items()
    }
    first_screen_summaries = {
        family: _candidate_summary(source_run, candidate)
        for family, (source_run, candidate) in immutable_first_screen.items()
    }
    family_uncertainty = {
        family: paired_game_cluster_bootstrap(best[family], refit_baselines[family])
        for family in best
    }
    cross_uncertainty = paired_game_cluster_bootstrap(
        best["histogram_gradient_boosting"], best["random_forest"]
    )
    diversity = _probability_diversity(
        best["histogram_gradient_boosting"], best["random_forest"]
    )
    class_auc_wins = {
        family: 0 for family in best
    }
    hgb_classes = {
        item["class"]: item.get("oneVsRestRocAuc")
        for item in summaries["histogram_gradient_boosting"]["classMetrics"]
    }
    rf_classes = {
        item["class"]: item.get("oneVsRestRocAuc")
        for item in summaries["random_forest"]["classMetrics"]
    }
    for class_name in hgb_classes:
        if hgb_classes[class_name] is None or rf_classes.get(class_name) is None:
            continue
        winner = (
            "histogram_gradient_boosting"
            if float(hgb_classes[class_name]) >= float(rf_classes[class_name])
            else "random_forest"
        )
        class_auc_wins[winner] += 1
    overall = min(best, key=lambda family: float(best[family]["meanOofLogLoss"]))
    decisions: dict[str, str] = {overall: "ADVANCE_TO_REFINEMENT"}
    other = next(family for family in best if family != overall)
    other_gain = float(first_screen_summaries[other]["meanOofLogLoss"]) - float(
        best[other]["meanOofLogLoss"]
    )
    other_stability_gain = float(
        first_screen_summaries[other]["foldStandardDeviation"]
    ) - float(summaries[other]["foldStandardDeviation"])
    diversity_supported = (
        diversity["predictedClassDisagreementRate"] >= 0.01
        or diversity["meanTotalVariationDistance"] >= 0.01
        or class_auc_wins[other] >= 1
        or other_stability_gain >= 0.00025
    )
    decisions[other] = (
        "RETAIN_AS_DIVERSITY_CHALLENGER"
        if other_gain >= PRACTICAL_LOG_LOSS_THRESHOLD and diversity_supported
        else "NO_TUNING_GAIN"
    )
    family_rows = {}
    for family in best:
        tuned = summaries[family]
        baseline = first_screen_summaries[family]
        null_gain = float(NULL_BASELINE["meanOofLogLoss"]) - float(tuned["meanOofLogLoss"])
        family_rows[family] = {
            "firstScreen": baseline,
            "sameRunFirstScreenRefit": refit_baseline_summaries[family],
            "bestTuned": tuned,
            "absoluteImprovementOverFirstScreen": float(baseline["meanOofLogLoss"]) - float(tuned["meanOofLogLoss"]),
            "absoluteImprovementOverNull": null_gain,
            "relativeImprovementOverNull": null_gain / float(NULL_BASELINE["meanOofLogLoss"]),
            "gameClusteredTuningGainUncertainty": family_uncertainty[family],
            "gameClusteredTuningGainComparator": (
                "SAME_RUN_EXACT_FIRST_SCREEN_HYPERPARAMETER_REFIT"
            ),
            "allConfigurations": [
                _candidate_summary(run, item, candidate_receipts)
                for item in sorted(
                    by_family[family], key=lambda row: float(row["meanOofLogLoss"])
                )
            ],
            "classRocAucWinsVersusOtherFamily": class_auc_wins[family],
            "advancementStatus": decisions[family],
        }
    plan = run.get("plan") or {}
    body = {
        "schemaVersion": TUNING_SCHEMA_VERSION,
        "createdAt": now_iso(),
        "projectId": PROJECT_ID,
        "authority": {
            "authorityKey": resolved.authority_key,
            "treatmentSpecificationId": (resolved.treatment_specification or {}).get("specificationId"),
            "treatmentVersion": (resolved.treatment_specification or {}).get("specificationVersion"),
            "featureSetId": resolved.feature_sets[0].get("featureSetId"),
            "featureSetChecksum": resolved.feature_sets[0].get("checksum"),
            "featureCount": len(resolved.feature_sets[0].get("orderedFeatures") or []),
            "splitContractId": resolved.split.get("contractId"),
            "splitChecksum": resolved.split.get("checksum"),
            "developmentRows": resolved.split["development"]["rows"],
            "finalOotRows": resolved.split["finalOot"]["rows"],
        },
        "design": {
            "grids": exact_grids(),
            "runtimeEstimate": runtime_estimate(),
            "selectionMetric": "MEAN_FIVE_FOLD_OOF_MULTICLASS_LOG_LOSS",
            "practicalIndifferenceThreshold": PRACTICAL_LOG_LOSS_THRESHOLD,
            "preprocessingAuthority": "FIT_INSIDE_EACH_REGISTERED_TRAINING_FOLD_ONLY",
            "earlyStopping": "DISABLED_NO_RANDOM_INTERNAL_VALIDATION_SPLIT",
            "classWeighting": "NONE_NOT_SCIENTIFICALLY_AUTHORIZED",
        },
        "execution": {
            "modelJobId": model_job_id,
            "modelRunId": run.get("runId"),
            "modelRunReceiptSha256": run.get("runReceiptSha256"),
            "modelPlanId": plan.get("planId"),
            "modelPlanChecksum": plan.get("checksum"),
            "status": run.get("status"),
            "configurationCount": len(candidates),
            "foldFits": sum(int(item.get("foldsCompleted") or 0) for item in candidates),
            "runtimeMs": run.get("runtimeMs"),
            "priorInfrastructureAttempts": prior_attempts,
            "finalOotCounters": {
                "locked": run_population.get("finalOotLocked"),
                "targetAccessed": run_population.get("finalOotTargetAccessed"),
                "scored": run_population.get("finalOotScored"),
                "accessed": run.get("finalOotAccessed"),
                "targetsMaterialized": run.get("finalOotTargetsMaterialized"),
            },
        },
        "nullBaseline": NULL_BASELINE,
        "families": family_rows,
        "crossFamilyComparison": {
            "left": "histogram_gradient_boosting",
            "right": "random_forest",
            "gameClusteredLogLossDifference": cross_uncertainty,
            "probabilityDiversity": diversity,
            "classRocAucWins": class_auc_wins,
            "practicallyMaterial": abs(float(cross_uncertainty["estimate"])) >= PRACTICAL_LOG_LOSS_THRESHOLD,
            "withinEstimatedUncertainty": (
                float(cross_uncertainty["confidenceInterval"]["lower"]) <= 0.0
                <= float(cross_uncertainty["confidenceInterval"]["upper"])
            ),
        },
        "repairBacklog": [
            {
                "modelFamily": "multinomial_logistic",
                "status": "REQUIRES_REPAIR",
                "reason": "Five first-screen convergence warnings at max_iter=1000; excluded from tuning scope.",
            },
            {
                "modelFamily": "sgd_classifier",
                "status": "REQUIRES_REPAIR",
                "reason": "First-screen probability reconciliation failed in all five folds; excluded from tuning scope.",
            },
        ],
        "governance": {
            "championSelected": False,
            "promotionStatus": "NOT_PROMOTED",
            "exportStatus": "NOT_EXPORTED",
            "deploymentStatus": "NOT_DEPLOYED",
            "merged": False,
            "finalOotLocked": True,
            "finalOotTargetAccessed": False,
            "finalOotPredictionsAccessed": False,
            "finalOotDistributionsAccessed": False,
            "finalOotMetricsAccessed": False,
            "nextStep": "STOP_AFTER_TUNING_DECISION",
        },
    }
    decision = _persist_object("tuning-decisions", body)
    STATIC_DECISION_PATH.write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "event": "TUNING_DECISION_FROZEN",
                "receiptSha256": decision["receiptSha256"],
                "modelJobId": model_job_id,
                "modelRunId": run.get("runId"),
                "familyStatuses": {
                    family: row["advancementStatus"] for family, row in family_rows.items()
                },
                "path": str(STATIC_DECISION_PATH),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
