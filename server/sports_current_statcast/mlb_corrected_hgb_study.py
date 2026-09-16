"""Frozen design and matched-OOF analysis for one corrected HGB configuration."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, log_loss

from ..sports_datasets.consumer import canonical_json_bytes
from .stage3_model_laboratory import GOLD_CLASS_ORDER, _ece, _metrics, _runtime_root

PROJECT_ID = "asp-mtlozhdx"
ACTOR_USER_ID = "user_20e0f4e20ec9434c"
FEATURE_SET_KEY = "MLB_CORE_CHALLENGER_CORRECTED_V1"
BATCH_NAME = "MLB corrected treatment bounded HGB comparison"
STUDY_SCHEMA = "MLB_CORRECTED_TREATMENT_HGB_STUDY_V1"
RESULT_SCHEMA = "MLB_CORRECTED_TREATMENT_HGB_COMPARISON_V1"
BASELINE_RUN_SHA = "c9ffcc867a73eac6c287309f34889390dedf8484244c3bf5c2ed20dacecaf635"
BASELINE_CANDIDATE_ID = "stage3-candidate-acfd57993d1844db95b81512c9a78a29"
BASELINE_CANDIDATE_SHA = "561e3493f950d26b1f8c17b2cc783af1f349452745c01104ec72aaab76bf9e9e"
BASELINE_LOG_LOSS = 1.4745426774960453
BOOTSTRAP_REPLICATES = 2000
BOOTSTRAP_SEED = 20260907
FOLD_FIELDS = ("foldNumber", "trainStart", "trainEnd", "trainRows", "trainGames", "validationStart", "validationEnd", "validationRows", "validationGames")
SUBGROUPS = (
    {"name": "BATTER_TRUE_COLD_START", "anyIndicatorEqualsOne": ["batter_prior_missing"]},
    {"name": "PITCHER_TRUE_COLD_START", "anyIndicatorEqualsOne": ["pitcher_prior_missing"]},
    {"name": "EITHER_PLAYER_TRUE_COLD_START", "anyIndicatorEqualsOne": ["batter_prior_missing", "pitcher_prior_missing"]},
    {"name": "BATTING_NO_PRIOR_GAME", "anyIndicatorEqualsOne": ["batting_previous_game_missing"]},
    {"name": "FIELDING_NO_PRIOR_GAME", "anyIndicatorEqualsOne": ["fielding_previous_game_missing"]},
    {"name": "EITHER_TEAM_NO_PRIOR_GAME", "anyIndicatorEqualsOne": ["batting_previous_game_missing", "fielding_previous_game_missing"]},
)


def probe_threading_infrastructure(*, pool_factory: Any = None) -> dict[str, Any]:
    """Check Windows/thread-pool IPC before enqueue; no estimator or data.

    sklearn's HGB binning uses joblib's threading backend, whose stdlib
    ThreadPool initializes a multiprocessing SimpleQueue/Windows named pipe.
    Testing that primitive directly avoids spending an authorized model fit
    to discover an execution-context permission failure.
    """
    if pool_factory is None:
        from multiprocessing.pool import ThreadPool
        pool_factory = ThreadPool
    synthetic = [-2, -1, 0, 1, 2]
    try:
        with pool_factory(processes=4) as pool:
            result = pool.map(abs, synthetic)
        if result != [2, 1, 0, 1, 2]:
            raise RuntimeError("Synthetic threading primitive returned unexpected values.")
    except Exception as exc:
        raise RuntimeError("HGB_THREADING_INFRASTRUCTURE_UNAVAILABLE_BEFORE_SUBMISSION: " + str(exc)) from exc
    return {"status": "PASS", "probe": "STDLIB_THREADPOOL_FOUR_WORKERS_SYNTHETIC_ABS_ONLY", "nativeWorkers": 4,
            "syntheticInputs": len(synthetic), "estimatorFits": 0, "sportsDataRows": 0, "finalOotRows": 0,
            "scope": "EXECUTION_CONTEXT_THREADPOOL_AND_IPC_PRIMITIVE_NOT_MODEL_VALIDATION"}


def content_sha(payload: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def read_immutable_json(path: Path, expected: str) -> dict[str, Any]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if hashlib.sha256(raw).hexdigest() != expected or content_sha(payload) != expected:
        raise RuntimeError(f"Immutable JSON receipt checksum mismatch: {path}")
    return payload


def baseline_authority() -> tuple[dict[str, Any], dict[str, Any], int]:
    run = read_immutable_json(_runtime_root() / "objects" / "sha256" / f"{BASELINE_RUN_SHA}.json", BASELINE_RUN_SHA)
    attempt = read_immutable_json(_runtime_root() / "candidate-attempts" / "objects" / "sha256" / f"{BASELINE_CANDIDATE_SHA}.json", BASELINE_CANDIDATE_SHA)
    candidates = [row for row in run["candidates"] if row["candidateId"] == BASELINE_CANDIDATE_ID]
    if len(candidates) != 1:
        raise RuntimeError("The exact selected baseline HGB candidate is absent.")
    candidate = candidates[0]
    if (candidate != attempt["candidate"] or candidate["status"] != "COMPLETE"
            or candidate["modelFamily"] != "histogram_gradient_boosting"
            or candidate["meanOofLogLoss"] != BASELINE_LOG_LOSS or candidate["foldsCompleted"] != 5):
        raise RuntimeError("Baseline candidate identity, completed folds, or immutable benchmark does not reconcile.")
    experiments = [row for row in run["plan"]["experiments"] if row["experimentId"] == candidate["experimentId"]]
    if len(experiments) != 1:
        raise RuntimeError("The baseline candidate does not resolve to one immutable experiment seed.")
    experiment = experiments[0]
    if experiment["tuning"]["configurations"][candidate["configurationIndex"] - 1] != candidate["hyperparameters"]:
        raise RuntimeError("The baseline configuration differs between plan and candidate receipt.")
    return run, candidate, int(experiment["seed"])


def fold_population(folds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in FOLD_FIELDS} for row in folds]


def validate_eligibility_receipt(evidence: Mapping[str, Any], feature_set: Mapping[str, Any]) -> None:
    """Authenticate pre-fit metadata, never reopen the source population."""
    policy = (feature_set.get("transformationContracts") or {}).get("rowEligibilityPolicy") or {}
    body = {key: value for key, value in evidence.items() if key != "eligibilityChecksum"}
    held = evidence.get("heldObservations") or []
    forbidden_counters = ("targetValuesRead", "finalOotPayloadRowsRead", "sourceRowsDeleted", "valuesImputed", "statesRelabeledAsColdStart")
    if (content_sha(body) != evidence.get("eligibilityChecksum")
            or evidence.get("schemaVersion") != "MLB_CORRECTED_ROW_ELIGIBILITY_V1"
            or evidence.get("status") != "APPLIED_EXPLICIT_OUTCOME_INDEPENDENT_QUARANTINE"
            or evidence.get("policyChecksum") != policy.get("policyChecksum")
            or evidence.get("featureSetId") != feature_set.get("featureSetId")
            or evidence.get("featureSetChecksum") != feature_set.get("checksum")
            or evidence.get("sourceRows") != 683662
            or evidence.get("heldRows") != len(held)
            or evidence.get("eligibleRows") != 683662 - len(held)
            or any(evidence.get(key) != 0 for key in forbidden_counters)
            or len(str(evidence.get("sourceRowIdentityChecksum") or "")) != 64):
        raise RuntimeError("Pre-fit eligibility evidence does not authenticate the registered outcome-independent policy/population.")
    keys = [row.get("canonicalPaId") for row in held]
    if len(set(keys)) != len(keys) or any(not key for key in keys):
        raise RuntimeError("The exclusion ledger lacks unique observation identity.")
    for row in held:
        if (row.get("reason") != "V1_KNOWN_ZERO_PRIOR_PA_UNSUPPORTED_HISTORY_STATE"
                or not row.get("canonicalGameId")
                or not "2023-03-30" <= str(row.get("gameDate") or "") <= "2026-08-13"):
            raise RuntimeError("An exclusion is outside the exact approved reason or Development interval.")


def model_fold_populations(folds: list[dict[str, Any]], evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    dates = [row["gameDate"] for row in evidence["heldObservations"]]
    results = []
    for fold in fold_population(folds):
        held_train = sum(fold["trainStart"] <= date <= fold["trainEnd"] for date in dates)
        held_validation = sum(fold["validationStart"] <= date <= fold["validationEnd"] for date in dates)
        results.append({**fold, "registeredTrainRows": fold["trainRows"], "registeredValidationRows": fold["validationRows"],
                        "registeredTrainGames": fold["trainGames"], "registeredValidationGames": fold["validationGames"],
                        "gameCountSemantics": "TRAIN_GAMES_AND_VALIDATION_GAMES_ARE_REGISTERED_COUNTS_MODEL_GAME_COUNTS_VERIFIED_AFTER_EXECUTION",
                        "trainRows": fold["trainRows"] - held_train, "validationRows": fold["validationRows"] - held_validation,
                        "quarantinedTrainRows": held_train, "quarantinedValidationRows": held_validation})
    return results


def verify_coverage_ledger(baseline: pd.DataFrame, corrected: pd.DataFrame, study: Mapping[str, Any]) -> dict[str, Any]:
    """Missing OOF identity must equal the frozen pre-outcome quarantine."""
    held = study["rowEligibility"]["heldObservations"]
    folds = study["folds"]
    expected = {row["canonicalPaId"]: row for row in held if any(fold["validationStart"] <= row["gameDate"] <= fold["validationEnd"] for fold in folds)}
    before = set(baseline["canonicalPaId"])
    after = set(corrected["canonicalPaId"])
    if after - before or before - after != set(expected):
        raise RuntimeError("Changed OOF coverage differs from the exact frozen outcome-independent exclusion ledger.")
    indexed = baseline.set_index("canonicalPaId", verify_integrity=True)
    for key, row in expected.items():
        original = indexed.loc[key]
        fold = next(item for item in folds if item["validationStart"] <= row["gameDate"] <= item["validationEnd"])
        if original["canonicalGameId"] != row["canonicalGameId"] or int(original["foldNumber"]) != fold["foldNumber"]:
            raise RuntimeError("Quarantined observation game/fold does not match baseline OOF identity.")
    return {"status": "EXACT_FROZEN_OUTCOME_INDEPENDENT_LEDGER_MATCH", "eligibilityChecksum": study["rowEligibility"]["eligibilityChecksum"],
            "registeredDevelopmentRows": study["rowEligibility"]["sourceRows"], "eligibleDevelopmentRows": study["rowEligibility"]["eligibleRows"],
            "quarantinedDevelopmentRows": len(held), "quarantinedOofRows": len(expected),
            "quarantinedOofObservations": [expected[key] for key in sorted(expected)], "targetValuesReadForEligibility": 0}


def exact_experiment(feature_set_id: str, baseline: Mapping[str, Any], seed: int) -> dict[str, Any]:
    return {
        "algorithmId": "histogram_gradient_boosting", "featureUniverseId": feature_set_id,
        "seed": seed, "tuningMode": "GRID", "gridPreset": "COMPACT",
        "compactGrid": [dict(baseline["hyperparameters"])],
    }


def execution_resource_comparison(baseline_run: Mapping[str, Any], baseline: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    baseline_resources = baseline.get("executionResources")
    baseline_experiment = next(item for item in baseline_run["plan"]["experiments"] if item["experimentId"] == baseline["experimentId"])
    corrected_resources = plan["experiments"][0].get("executionResources")
    if (not isinstance(baseline_resources, dict) or not isinstance(corrected_resources, dict)
            or baseline_experiment.get("executionResources") != baseline_resources
            or not isinstance(baseline_resources.get("nativeWorkers"), int)
            or baseline_resources["nativeWorkers"] < 1):
        raise RuntimeError("The exact baseline and current per-estimator execution resources are not authenticated.")
    if corrected_resources.get("nativeWorkers") != baseline_resources["nativeWorkers"]:
        raise RuntimeError("Corrected HGB native workers differ from the immutable baseline; resolve this execution-resource drift before fitting.")
    differences = {key: {"baseline": baseline_resources.get(key), "corrected": corrected_resources.get(key)}
                   for key in sorted(set(baseline_resources) | set(corrected_resources)) if baseline_resources.get(key) != corrected_resources.get(key)}
    return {"baseline": dict(baseline_resources), "corrected": dict(corrected_resources), "perEstimatorNativeWorkersPreserved": True,
            "resourceMetadataDifferences": differences, "baselineBatchParallelism": dict(baseline_run["plan"].get("parallelism") or {}),
            "correctedBatchParallelism": dict(plan.get("parallelism") or {}),
            "batchSchedulingNote": "ONE_CORRECTED_CANDIDATE_ONLY_BASELINE_WAS_A_MULTI_CONFIGURATION_BATCH_NO_CLAIM_OF_IDENTICAL_BATCH_PARALLELISM"}


def validate_single_plan(plan: Mapping[str, Any], *, hyperparameters: Mapping[str, Any], seed: int, feature_set_id: str) -> None:
    experiments = plan.get("experiments") or []
    if (plan.get("totalConfigurations") != 1 or plan.get("totalFits") != 5 or plan.get("foldCount") != 5
            or plan.get("finalOotLocked") is not True or plan.get("finalOotTargetAccessed") is not False
            or len(experiments) != 1 or experiments[0].get("algorithmId") != "histogram_gradient_boosting"
            or experiments[0].get("seed") != seed
            or experiments[0].get("featureUniverseId") != feature_set_id
            or experiments[0].get("tuning", {}).get("configurations") != [dict(hyperparameters)]):
        raise RuntimeError("Bounded study requires exactly the selected HGB configuration with its existing seed across five folds.")


def matching_job(jobs: list[dict[str, Any]], study: Mapping[str, Any]) -> dict[str, Any] | None:
    matches = [job for job in jobs if (job.get("plan") or {}).get("batchName") == BATCH_NAME]
    if len(matches) > 1:
        raise RuntimeError("Multiple bounded-study jobs exist; no additional enqueue is permitted.")
    if not matches:
        return None
    job = matches[0]
    if (job.get("plan") or {}).get("checksum") != study["plan"]["checksum"]:
        raise RuntimeError("A bounded-study job already exists under a different plan; no new fits are authorized.")
    return job


def paired_frames(corrected: pd.DataFrame, baseline: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    identity = ["canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex"]
    probability_columns = [name for name in corrected if name.startswith("probability_")]
    if probability_columns != [name for name in baseline if name.startswith("probability_")] or probability_columns != [f"probability_{name}" for name in GOLD_CLASS_ORDER]:
        raise RuntimeError("Baseline and corrected OOF probability class order differ.")
    for label, frame in (("corrected", corrected), ("baseline", baseline)):
        if frame["canonicalPaId"].duplicated().any() or frame[identity].isna().any().any():
            raise RuntimeError(f"The {label} OOF artifact has duplicate or incomplete observation identity.")
    # Match by observation identity first and reject changed game/fold/target,
    # rather than treating changed labels as innocuous coverage differences.
    joined = corrected.merge(baseline, on="canonicalPaId", how="outer", validate="one_to_one", indicator=True, suffixes=("_corrected", "_baseline"))
    both = joined["_merge"].eq("both")
    for column in identity[1:]:
        if not (joined.loc[both, f"{column}_corrected"].to_numpy() == joined.loc[both, f"{column}_baseline"].to_numpy()).all():
            raise RuntimeError(f"Matching OOF rows disagree on {column}.")
    matched = joined.loc[both].copy()
    if matched.empty:
        raise RuntimeError("No matching OOF observations exist.")
    for column in identity[1:]:
        matched[column] = matched[f"{column}_corrected"]
    coverage = {
        "baselineOriginalRows": len(baseline), "correctedOriginalRows": len(corrected), "matchingRows": len(matched),
        "baselineOnlyRows": int(joined["_merge"].eq("right_only").sum()), "correctedOnlyRows": int(joined["_merge"].eq("left_only").sum()),
        "matchedGames": int(matched["canonicalGameId"].nunique()),
        "coverageChanged": len(matched) != len(baseline) or len(matched) != len(corrected),
    }
    return matched, coverage, probability_columns


def _probabilities(frame: pd.DataFrame, columns: list[str], suffix: str = "") -> np.ndarray:
    values = frame[[column + suffix for column in columns]].to_numpy(dtype=np.float64)
    if not np.isfinite(values).all() or np.any(values < 0) or np.any(values > 1) or not np.allclose(values.sum(axis=1), 1.0, rtol=0.0, atol=1e-8):
        raise RuntimeError("OOF probability rows are invalid.")
    return values


def metrics_allow_absent_classes(probabilities: np.ndarray, labels: np.ndarray) -> dict[str, Any]:
    """Use exact established metrics; undefined subgroup AUC remains null."""
    if len(labels) == 0:
        return {"status": "NO_MATCHING_OBSERVATIONS", "observations": 0, "multiclassLogLoss": None, "summedBrier": None, "macroOvrRocAuc": None, "ece": None}
    if len(np.unique(labels)) == len(GOLD_CLASS_ORDER):
        return {"status": "COMPLETE", "observations": len(labels), **_metrics(probabilities, labels)}
    # _metrics uses sklearn's fixed-eight-class macro AUC, which is undefined
    # if one class is absent. Keep identical other definitions and never
    # substitute a different AUC estimand silently.
    from sklearn.metrics import roc_auc_score
    truth = np.eye(len(GOLD_CLASS_ORDER))[labels]
    predicted = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = predicted == labels
    bands = []
    for lower in np.linspace(0.0, 1.0, 10, endpoint=False):
        upper = lower + 0.1
        selected = (confidence >= lower) & (confidence <= upper if np.isclose(upper, 1.0) else confidence < upper)
        bands.append({"lowerBound": float(lower), "upperBound": float(upper), "observations": int(selected.sum()), "meanConfidence": float(confidence[selected].mean()) if selected.any() else None, "observedAccuracy": float(correct[selected].mean()) if selected.any() else None, "absoluteCalibrationGap": float(abs(confidence[selected].mean() - correct[selected].mean())) if selected.any() else None})
    classes = []
    for index, name in enumerate(GOLD_CLASS_ORDER):
        observed = truth[:, index]
        score = probabilities[:, index]
        support = int(observed.sum())
        classes.append({"class": name, "support": support, "observedRate": float(observed.mean()), "meanPredictedProbability": float(score.mean()), "absoluteCalibrationError": float(abs(score.mean() - observed.mean())), "oneVsRestBrier": float(np.mean((score-observed)**2)), "oneVsRestRocAuc": float(roc_auc_score(observed, score)) if 0 < support < len(labels) else None})
    return {"status": "COMPLETE_WITH_UNDEFINED_MACRO_AUC", "observations": len(labels), "multiclassLogLoss": float(log_loss(labels, probabilities, labels=list(range(len(GOLD_CLASS_ORDER))))), "summedBrier": float(np.mean(np.sum((probabilities-truth)**2, axis=1))), "ece": _ece(probabilities, labels), "accuracy": float(np.mean(predicted == labels)), "macroF1": float(f1_score(labels, predicted, labels=list(range(len(GOLD_CLASS_ORDER))), average="macro", zero_division=0)), "macroOvrRocAuc": None, "macroAucUnavailableReason": "ONE_OR_MORE_OF_FIXED_EIGHT_CLASSES_ABSENT", "reliabilityBands": bands, "classCalibration": classes, "rareClass": min(classes, key=lambda row: row["support"])}


def paired_metrics(matched: pd.DataFrame, columns: list[str]) -> dict[str, Any]:
    labels = matched["observedClassIndex"].to_numpy(dtype=np.int64)
    before = metrics_allow_absent_classes(_probabilities(matched, columns, "_baseline"), labels)
    after = metrics_allow_absent_classes(_probabilities(matched, columns, "_corrected"), labels)
    difference = {name: float(after[name] - before[name]) if after.get(name) is not None and before.get(name) is not None else None for name in ("multiclassLogLoss", "summedBrier", "macroOvrRocAuc", "ece")}
    return {"baseline": before, "corrected": after, "correctedMinusBaseline": difference}


def game_clustered_difference(matched: pd.DataFrame, columns: list[str], *, replicates: int = BOOTSTRAP_REPLICATES, seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Existing game-resampling method, operating on verified matching rows.

Each sampled game contributes its PA-loss sum and PA count; the ratio yields
the same observation-weighted estimand as pooled OOF log loss.
"""
    if replicates < 200 or matched.empty:
        raise ValueError("A nonempty matched population and at least 200 replicates are required.")
    labels = matched["observedClassIndex"].to_numpy(dtype=np.int64)
    before = _probabilities(matched, columns, "_baseline")
    after = _probabilities(matched, columns, "_corrected")
    row_index = np.arange(len(labels))
    epsilon = np.finfo(np.float64).eps
    difference = -np.log(np.clip(after[row_index, labels], epsilon, 1.0)) + np.log(np.clip(before[row_index, labels], epsilon, 1.0))
    grouped = pd.DataFrame({"game": matched["canonicalGameId"].astype(str).to_numpy(), "difference": difference}).groupby("game", sort=True)["difference"].agg(["sum", "count"])
    sums = grouped["sum"].to_numpy(dtype=float)
    counts = grouped["count"].to_numpy(dtype=np.int64)
    rng = np.random.default_rng(seed)
    draws = np.empty(replicates)
    for start in range(0, replicates, 100):
        stop = min(start+100, replicates)
        indices = rng.integers(0, len(grouped), size=(stop-start, len(grouped)))
        draws[start:stop] = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
    lower, upper = np.quantile(draws, [0.025, 0.975])
    return {"method": "PAIRED_NONPARAMETRIC_BOOTSTRAP_CLUSTERED_BY_CANONICAL_GAME_ID", "estimand": "CORRECTED_MINUS_V14_OBSERVATION_WEIGHTED_MULTICLASS_LOG_LOSS", "weighting": "SUM_PA_LOSSES_DIV_SUM_PA_COUNTS_WITHIN_RESAMPLED_GAMES", "rowCount": len(matched), "gameClusterCount": len(grouped), "replicates": replicates, "seed": seed, "estimate": float(difference.mean()), "standardError": float(np.std(draws, ddof=1)), "confidenceLevel": 0.95, "confidenceInterval": {"lower": float(lower), "upper": float(upper)}, "probabilityCorrectedLowerLoss": float(np.mean(draws < 0)), "finalOotTargetAccessed": False}
