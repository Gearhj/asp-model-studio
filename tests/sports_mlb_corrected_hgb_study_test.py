from __future__ import annotations

import copy
import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast import mlb_corrected_hgb_study as study
from server.sports_current_statcast import mlb_core_challenger_tuning as previous
from server.sports_current_statcast.stage3_model_laboratory import GOLD_CLASS_ORDER, _metrics


def _oof(rows: int = 24, correct_probability: float = 0.35) -> pd.DataFrame:
    labels = np.arange(rows, dtype=np.int64) % len(GOLD_CLASS_ORDER)
    values = np.full((rows, len(GOLD_CLASS_ORDER)), (1.0 - correct_probability) / 7)
    values[np.arange(rows), labels] = correct_probability
    frame = pd.DataFrame({"canonicalPaId": [f"pa-{i}" for i in range(rows)],
                          "canonicalGameId": ["g0"] * 3 + ["g1"] * 9 + ["g2"] * (rows - 12),
                          "foldNumber": np.ones(rows, dtype=np.int64), "observedClassIndex": labels})
    for index, name in enumerate(GOLD_CLASS_ORDER):
        frame[f"probability_{name}"] = values[:, index]
    return frame


def _eligibility() -> tuple[dict, dict]:
    feature_set = {"featureSetId": "successor", "checksum": "f" * 64,
                   "transformationContracts": {"rowEligibilityPolicy": {"policyChecksum": "p" * 64}}}
    body = {"schemaVersion": "MLB_CORRECTED_ROW_ELIGIBILITY_V1", "status": "APPLIED_EXPLICIT_OUTCOME_INDEPENDENT_QUARANTINE",
            "policyChecksum": "p" * 64, "featureSetId": "successor", "featureSetChecksum": "f" * 64,
            "sourceRows": 683662, "eligibleRows": 683660, "heldRows": 2, "sourceRowIdentityChecksum": "s" * 64,
            "targetValuesRead": 0, "finalOotPayloadRowsRead": 0, "sourceRowsDeleted": 0, "valuesImputed": 0, "statesRelabeledAsColdStart": 0,
            "heldObservations": [
                {"canonicalPaId": "train-only", "canonicalGameId": "old", "gameDate": "2023-04-01", "reason": "V1_KNOWN_ZERO_PRIOR_PA_UNSUPPORTED_HISTORY_STATE"},
                {"canonicalPaId": "pa-5", "canonicalGameId": "g1", "gameDate": "2024-04-01", "reason": "V1_KNOWN_ZERO_PRIOR_PA_UNSUPPORTED_HISTORY_STATE"}]}
    return {**body, "eligibilityChecksum": study.content_sha(body)}, feature_set


def _folds() -> list[dict]:
    return [{"foldNumber": 1, "trainStart": "2023-03-30", "trainEnd": "2023-10-01", "trainRows": 100, "trainGames": 10,
             "validationStart": "2024-03-20", "validationEnd": "2024-07-06", "validationRows": 24, "validationGames": 3}]


def test_exact_one_configuration_plan_and_terminal_resume_no_reenqueue():
    config = {"max_iter": 500, "learning_rate": 0.03}
    experiment = study.exact_experiment("successor", {"hyperparameters": config}, 20260906)
    assert experiment["compactGrid"] == [config]
    plan = {"checksum": "plan", "batchName": study.BATCH_NAME, "totalConfigurations": 1, "totalFits": 5, "foldCount": 5,
            "finalOotLocked": True, "finalOotTargetAccessed": False,
            "experiments": [{"algorithmId": "histogram_gradient_boosting", "seed": 20260906, "featureUniverseId": "successor", "tuning": {"configurations": [config]}}]}
    study.validate_single_plan(plan, hyperparameters=config, seed=20260906, feature_set_id="successor")
    for status in ("RUNNING", "COMPLETE", "FAILED", "CANCELLED_PARTIAL"):
        job = {"jobId": "already-existing", "status": status, "plan": plan}
        assert study.matching_job([job], {"plan": plan}) is job
    assert study.matching_job([], {"plan": plan}) is None
    with pytest.raises(RuntimeError, match="Multiple"):
        study.matching_job([job, copy.deepcopy(job)], {"plan": plan})
    with pytest.raises(RuntimeError, match="different plan"):
        study.matching_job([job], {"plan": {"checksum": "changed"}})
    for field, value in (("totalFits", 10), ("totalConfigurations", 2), ("finalOotLocked", False)):
        invalid = {**plan, field: value}
        with pytest.raises(RuntimeError, match="exactly"):
            study.validate_single_plan(invalid, hyperparameters=config, seed=20260906, feature_set_id="successor")


def test_changed_coverage_matches_observations_not_outer_join_dtypes():
    before = _oof()
    after = _oof(correct_probability=0.4).drop(index=5).reset_index(drop=True)
    matched, coverage, columns = study.paired_frames(after, before)
    assert coverage["baselineOnlyRows"] == 1 and coverage["correctedOnlyRows"] == 0
    assert coverage["matchingRows"] == 23 and coverage["coverageChanged"]
    result = study.paired_metrics(matched, columns)
    assert result["correctedMinusBaseline"]["multiclassLogLoss"] < 0


@pytest.mark.parametrize("column,value", [("observedClassIndex", 7), ("foldNumber", 2), ("canonicalGameId", "altered")])
def test_changed_identity_is_not_treated_as_coverage(column, value):
    before = _oof()
    after = before.copy()
    after.loc[0, column] = value
    with pytest.raises(RuntimeError, match=f"disagree on {column}"):
        study.paired_frames(after, before)


def test_duplicates_and_probability_column_order_fail_closed():
    before = _oof()
    with pytest.raises(RuntimeError, match="duplicate"):
        study.paired_frames(pd.concat([before, before.iloc[:1]]), before)
    columns = list(before.columns)
    columns[-1], columns[-2] = columns[-2], columns[-1]
    with pytest.raises(RuntimeError, match="class order"):
        study.paired_frames(before[columns], before)


def test_frozen_exclusion_ledger_authenticates_pre_outcome_counts():
    evidence, feature_set = _eligibility()
    study.validate_eligibility_receipt(evidence, feature_set)
    populations = study.model_fold_populations(_folds(), evidence)
    assert populations[0]["trainRows"] == 99 and populations[0]["validationRows"] == 23
    assert populations[0]["registeredTrainRows"] == 100
    bad = copy.deepcopy(evidence)
    bad["targetValuesRead"] = 1
    bad["eligibilityChecksum"] = study.content_sha({key: value for key, value in bad.items() if key != "eligibilityChecksum"})
    with pytest.raises(RuntimeError, match="authenticate"):
        study.validate_eligibility_receipt(bad, feature_set)


def test_only_predeclared_oof_exclusions_are_permitted():
    evidence, _ = _eligibility()
    frozen = {"rowEligibility": evidence, "folds": _folds()}
    before = _oof()
    after = before.drop(index=5)
    result = study.verify_coverage_ledger(before, after, frozen)
    assert result["quarantinedOofRows"] == 1 and result["quarantinedDevelopmentRows"] == 2
    for invalid in (before, before.drop(index=[5, 6]), before.drop(index=6)):
        with pytest.raises(RuntimeError, match="coverage differs"):
            study.verify_coverage_ledger(before, invalid, frozen)


def test_exact_established_metrics_and_absent_class_subgroups():
    frame = _oof()
    columns = [column for column in frame if column.startswith("probability_")]
    probabilities = study._probabilities(frame, columns)
    labels = frame["observedClassIndex"].to_numpy(dtype=np.int64)
    actual = study.metrics_allow_absent_classes(probabilities, labels)
    for key, value in _metrics(probabilities, labels).items():
        assert actual[key] == value
    subset = study.metrics_allow_absent_classes(probabilities[:2], labels[:2])
    assert subset["macroOvrRocAuc"] is None
    assert len(subset["classCalibration"]) == 8
    assert subset["multiclassLogLoss"] == pytest.approx(-np.log(0.35))
    empty = study.metrics_allow_absent_classes(probabilities[:0], labels[:0])
    assert empty["observations"] == 0 and empty["multiclassLogLoss"] is None


def test_bootstrap_exact_previous_method_and_pooled_pa_weighting(monkeypatch):
    before = _oof()
    after = _oof(correct_probability=0.4)
    # Make the effect nonconstant across games with unequal PA counts.
    after.loc[:2, [column for column in after if column.startswith("probability_")]] = before.loc[:2, [column for column in before if column.startswith("probability_")]]
    matched, _, columns = study.paired_frames(after, before)
    result = study.game_clustered_difference(matched, columns, replicates=200, seed=20260907)
    monkeypatch.setattr(previous, "read_oof", lambda attempt: after if attempt["id"] == "corrected" else before)
    established = previous.paired_game_cluster_bootstrap({"id": "corrected"}, {"id": "baseline"}, replicates=200, seed=20260907)
    for key in ("estimate", "standardError", "confidenceInterval", "rowCount", "gameClusterCount"):
        assert result[key] == pytest.approx(established[key])
    comparison = study.paired_metrics(matched, columns)
    assert result["estimate"] == pytest.approx(comparison["correctedMinusBaseline"]["multiclassLogLoss"], abs=1e-12)
    per_game_average = (0 + 2 * (-np.log(0.4) + np.log(0.35))) / 3
    assert not np.isclose(result["estimate"], per_game_average)


def test_probability_invalid_values_are_rejected():
    frame = _oof()
    columns = [column for column in frame if column.startswith("probability_")]
    for value in (np.nan, np.inf, -0.1, 1.1):
        invalid = frame.copy()
        invalid.loc[0, columns[0]] = value
        with pytest.raises(RuntimeError, match="probability rows are invalid"):
            study._probabilities(invalid, columns)


def test_runner_freezes_registered_split_and_exact_preflight_eligibility(monkeypatch):
    from scripts import run_mlb_corrected_hgb as runner
    from server.sports_datasets.consumer import canonical_json_bytes

    evidence, feature_set = _eligibility()
    feature_set.update({"featureSetKey": study.FEATURE_SET_KEY, "orderedFeatures": [f"model_{i}" for i in range(273)]})
    feature_set["transformationContracts"].update({"semanticTreatmentVersion": "MLB_SEMANTIC_TREATMENT_V1", "sourceOrderedFeatures": [f"source_{i}" for i in range(218)]})
    config = {"max_iter": 500, "learning_rate": 0.03}
    resources = {"nativeWorkers": 4, "exclusiveCandidate": True}
    baseline = {"hyperparameters": config, "folds": _folds(), "meanOofLogLoss": study.BASELINE_LOG_LOSS, "evaluationEvidence": {}, "experimentId": "selected", "featureSetChecksum": "b" * 64, "orderedFeatures": list(feature_set["transformationContracts"]["sourceOrderedFeatures"]), "executionResources": resources}
    resolved = SimpleNamespace(feature_sets=[feature_set], authority_key="authority",
                               treatment_specification={"status": "ADOPTED", "specificationVersion": 15, "specificationId": "v15", "checksum": "t" * 64},
                               split={"contractId": "same-dates-newbinding", "checksum": "c" * 64, "contract": {"folds": _folds()}, "development": {"rows": 683662}, "finalOot": {"rows": 14067, "locked": True}})
    baseline_run = {"identity": {"targetOrder": list(GOLD_CLASS_ORDER)}, "plan": {"experiments": [{"experimentId": "selected", "executionResources": resources}], "parallelism": {"effectiveCandidateWorkers": 2}}}
    monkeypatch.setattr(runner, "baseline_authority", lambda: (baseline_run, baseline, 20260906))
    monkeypatch.setattr(runner, "resolve_model_lab_authority", lambda *args: resolved)
    plan = {"checksum": "planned", "totalConfigurations": 1, "totalFits": 5, "foldCount": 5, "finalOotLocked": True, "finalOotTargetAccessed": False,
            "parallelism": {"effectiveCandidateWorkers": 1},
            "experiments": [{"algorithmId": "histogram_gradient_boosting", "seed": 20260906, "featureUniverseId": "successor", "tuning": {"configurations": [config]}, "executionResources": resources}]}
    monkeypatch.setattr(runner, "plan_model_development_queue", lambda *args, **kwargs: plan)
    receipt = SimpleNamespace(read_bytes=lambda: canonical_json_bytes(evidence), resolve=lambda: Path("C:/synthetic-eligibility.json"))
    payload, frozen = runner.validated_study(object(), receipt)
    assert payload["experiments"][0]["compactGrid"] == [config]
    assert frozen["rowEligibility"] == evidence
    assert frozen["modelFoldPopulations"][0]["validationRows"] == 23
    assert frozen["sourceFeatureOrderMatchesBaselineExactly"]
    assert frozen["executionResourceComparison"]["baseline"]["nativeWorkers"] == 4
    assert frozen["executionResourceComparison"]["baselineBatchParallelism"] != frozen["executionResourceComparison"]["correctedBatchParallelism"]
    assert frozen["studyChecksum"] == study.content_sha({key: value for key, value in frozen.items() if key != "studyChecksum"})
    monkeypatch.setattr(runner, "plan_model_development_queue", lambda *args, **kwargs: pytest.fail("An invalid source order reached planning"))
    feature_set["transformationContracts"]["sourceOrderedFeatures"][:2] = list(reversed(feature_set["transformationContracts"]["sourceOrderedFeatures"][:2]))
    with pytest.raises(RuntimeError, match="source feature identity/order"):
        runner.validated_study(object(), receipt)


def test_estimator_native_workers_are_preserved_and_other_differences_are_explicit():
    resources = {"nativeWorkers": 4, "exclusiveCandidate": True, "schedulingPolicy": "existing"}
    baseline = {"experimentId": "selected", "executionResources": resources}
    run = {"plan": {"experiments": [{"experimentId": "selected", "executionResources": resources}], "parallelism": {"effectiveCandidateWorkers": 2}}}
    plan = {"experiments": [{"executionResources": {**resources, "schedulingPolicy": "current"}}], "parallelism": {"effectiveCandidateWorkers": 1}}
    comparison = study.execution_resource_comparison(run, baseline, plan)
    assert comparison["perEstimatorNativeWorkersPreserved"]
    assert comparison["resourceMetadataDifferences"] == {"schedulingPolicy": {"baseline": "existing", "corrected": "current"}}
    plan["experiments"][0]["executionResources"]["nativeWorkers"] = 1
    with pytest.raises(RuntimeError, match="native workers differ"):
        study.execution_resource_comparison(run, baseline, plan)


def test_finalizer_sums_validation_rows_but_not_schema_width(monkeypatch):
    from scripts import finalize_mlb_corrected_hgb as finalizer
    from server.sports_current_statcast import stage3_corrected_preprocessing_artifacts as artifacts

    runtime = Path("C:/synthetic-local-research")
    monkeypatch.setattr(finalizer.lab, "_runtime_root", lambda: runtime)
    monkeypatch.setattr(artifacts, "_file_digest", lambda path: "m" * 64)
    source = b"# exact source bytes\r\n"
    implementation = {"schemaVersion": "MLB_LOCAL_RESEARCH_IMPLEMENTATION_SNAPSHOT_V1", "files": {"synthetic.py": {"sha256": hashlib.sha256(source).hexdigest(), "sourceBytesBase64": base64.b64encode(source).decode("ascii")}}}
    payloads = {}
    folds = []
    for number in (1, 2):
        payloads[str(number)] = {"fold": {"foldNumber": number}, "validationRowsUsedForParameters": 0, "finalOotRowsUsedForParameters": 0,
            "prior": {"fitRows": 100, "validationRowsUsedForFit": 0, "fittedTreatmentChecksum": "prior"},
            "semantic": {"trainingRows": 100, "validationRowsFit": 0, "fittedChecksum": "semantic"},
            "implementationSnapshot": {"sha256": "implementation"}, "trainingBranchCounts": {},
            "validationBranchCounts": {"features": {"context": {"changedRows": 3}}},
            "priorExecution": {"validation": {"features": [{"feature": "batter_so_per_pa", "wave": 1, "rows": 23, "historyStateCounts": {"ESTABLISHED_HISTORY": 23}, "priorLevelCounts": {}, "preservedRawRows": 23, "rawValueDifferentFromPosteriorRows": 20, "trueColdRawMissingRetainedRows": 0, "requiredDerivedOutputColumnsAdded": 5}]}}}
        reload = {"status": "PERSISTED_AND_RELOADED_WITHOUT_REFITTING", "refitsDuringReload": 0, "finalOotRowsRead": 0, "transformedValidationSha256": "same", "reloadedTransformedValidationSha256": "same", "validationRows": 23, "probabilityMaximumAbsoluteDifference": 0.0,
                  "model": {"sha256": "m" * 64, "relativePath": "objects/research-model/sha256/" + "m" * 64 + ".joblib"}}
        folds.append({"foldNumber": number, "registeredTrainRows": 100, "trainRows": 99, "validationRows": 23,
                      "preprocessing": {"fittedArtifact": {"sha256": str(number)}, "localResearchArtifact": reload}})
    monkeypatch.setattr(finalizer, "_artifact_payload", lambda reference: implementation if reference["sha256"] == "implementation" else payloads[reference["sha256"]])
    result = finalizer._branch_summary(folds)
    assert result["semantic"]["context"]["changedRows"] == 6
    assert result["priors"]["batter_so_per_pa"]["preservedRawRows"] == 46
    assert result["priors"]["batter_so_per_pa"]["requiredDerivedOutputColumnsAdded"] == 5
    assert result["reloadVerifiedFoldCount"] == 2
    assert result["semanticChangedRowsMeaning"] == "RAW_SOURCE_TO_SUCCESSOR_TRANSFORM_ONLY_NOT_V14_MODEL_INPUT_COMPARISON"
    assert "featuresWithNoObservedInputChange" not in result


def test_model_input_change_reporting_does_not_confuse_unchanged_raw_null_with_v14():
    from scripts import finalize_mlb_corrected_hgb as finalizer

    semantic = {
        "context": {"rows": 40, "changedRows": 0, "nativeMissingRows": 12},
        "travel_product": {"rows": 40, "changedRows": 0, "nativeMissingRows": 12, "recomputedRows": 40},
        "structural": {"rows": 40, "changedRows": 12, "semanticZeroRows": 12},
        "exposure": {"rows": 40, "changedRows": 0, "semanticZeroRows": 5},
        "repeat_count": {"rows": 40, "changedRows": 8, "booleanDomainRepairRows": 8, "deterministicRecomputedRows": 40},
        "complete_product": {"rows": 40, "changedRows": 0, "recomputedRows": 40},
        **{f"future_{index}": {"rows": 40, "changedRows": 0, "futureMissingRejectedRows": 0, "sourceUnavailableRows": 0, "invalidRows": 0} for index in range(15)},
    }
    kinds = {"context": "NO_PRIOR_CONTEXT", "travel_product": "TRAVEL_INTERACTION", "structural": "STRUCTURAL_ZERO",
             "exposure": "COLD_EXPOSURE", "repeat_count": "REPEAT_OPPONENT_BOOLEAN", "complete_product": "DETERMINISTIC_INTERACTION",
             **{f"future_{index}": "REQUIRED_COMPLETE" for index in range(15)}}
    path = {"steps": ["RETAIN_RAW"], "numericMissingTreatment": "TRAINING_FOLD_MEDIAN"}
    paths = {name: [dict(path)] for name in semantic}
    paths["repeat_count"] = [{"steps": ["BINARY_PASSTHROUGH"], "numericMissingTreatment": "TRAINING_FOLD_MEDIAN"}]
    priors = {f"prior_{index}": {"wave": 1, "rows": 40, "preservedRawRows": 35, "rawValueDifferentFromPosteriorRows": 30,
                                 "trueColdRawMissingRetainedRows": 5, "requiredDerivedOutputColumnsAdded": 5} for index in range(11)}
    result = finalizer._v14_input_change_summary(semantic, priors, kinds, paths)
    context = result["features"]["context"]
    assert context["rawToSuccessorChangedRows"] == 0
    assert context["confirmedV14RepresentationDifferentRows"] == 12
    assert context["confirmedV14ValueDifferentRows"] is None
    assert context["historicalImputationValuesRecovered"] is False
    assert result["features"]["travel_product"]["confirmedV14RepresentationDifferentRows"] == 12
    for name in ("structural", "exposure"):
        assert result["features"][name]["confirmedV14ValueDifferentRows"] is None
        assert "HISTORICAL_VALUE_EQUALITY_UNRESOLVED" in result["features"][name]["comparisonStatus"]
    assert result["features"]["repeat_count"]["confirmedV14ValueDifferentRows"] == 8
    assert result["deterministicExecution"]["complete_product"] == {"recomputedRows": 40, "rawToSuccessorChangedRows": 0}
    assert result["features"]["complete_product"]["confirmedV14ValueDifferentRows"] == 0
    assert result["additionalWave1Schema"] == {"sourceFeatures": 11, "requiredColumnsAddedBeforeOneHot": 55,
                                               "observationsReceivingAddedSchema": 40, "addedChannelObservationCells": 2200}
    assert result["wave1Representation"]["prior_0"]["rawVsSuccessorPosteriorDifferentRows"] == 30
    assert result["wave1Representation"]["prior_0"]["confirmedHistoricalV14NumericalDifferenceRows"] is None
    assert result["futureMissingGuardFeatureCount"] == 15
    assert result["futureMissingRejectedFeatureRowActivations"] == 0
    assert "context" in result["featuresWithProvenV14RepresentationOrValueChanges"]
    assert "structural" not in result["featuresWithProvenV14RepresentationOrValueChanges"]


def test_missing_historic_path_never_becomes_a_proven_v14_input_difference():
    from scripts import finalize_mlb_corrected_hgb as finalizer

    semantic = {"context": {"rows": 40, "changedRows": 0, "nativeMissingRows": 12}}
    result = finalizer._v14_input_change_summary(semantic, {}, {"context": "NO_PRIOR_CONTEXT"}, {})
    assert result["features"]["context"]["confirmedV14RepresentationDifferentRows"] is None
    assert result["featuresWithProvenV14RepresentationOrValueChanges"] == []


def test_threading_permission_probe_uses_no_estimator_and_fails_before_submission():
    calls = []

    class SyntheticPool:
        def __init__(self, *, processes):
            calls.append(processes)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def map(self, function, values):
            assert function is abs and values == [-2, -1, 0, 1, 2]
            return [function(value) for value in values]

    result = study.probe_threading_infrastructure(pool_factory=SyntheticPool)
    assert calls == [4]
    assert result["estimatorFits"] == 0 and result["sportsDataRows"] == 0
    def denied(**kwargs):
        raise PermissionError("[WinError 5] Access is denied")
    with pytest.raises(RuntimeError, match="HGB_THREADING_INFRASTRUCTURE_UNAVAILABLE_BEFORE_SUBMISSION"):
        study.probe_threading_infrastructure(pool_factory=denied)


def test_incomplete_finalizer_preserves_original_baseline_without_inventing_five_fit_calls(monkeypatch):
    from scripts import finalize_mlb_corrected_hgb as finalizer

    probabilities = study._probabilities(_oof(), [f"probability_{name}" for name in GOLD_CLASS_ORDER])
    metrics = study.metrics_allow_absent_classes(probabilities, np.arange(24, dtype=np.int64) % 8)
    baseline = {"evaluationEvidence": {"rowCount": 24, "reloadableArtifactRelativePath": "not-read.parquet"},
                "meanOofLogLoss": metrics["multiclassLogLoss"], "summedBrier": metrics["summedBrier"], "macroOvrRocAuc": metrics["macroOvrRocAuc"],
                "ece": metrics["ece"], "classCalibration": metrics["classCalibration"], "reliabilityBands": metrics["reliabilityBands"],
                "folds": [{"foldNumber": 1, "validationRows": 24, "metrics": metrics}]}
    monkeypatch.setattr(finalizer, "baseline_authority", lambda: ({"identity": {"targetOrder": list(GOLD_CLASS_ORDER)}}, baseline, 20260906))
    monkeypatch.setattr(finalizer, "read_oof", lambda *args, **kwargs: pytest.fail("Incomplete study read an OOF payload"))
    monkeypatch.setattr(finalizer.lab, "_fold_frame", lambda *args, **kwargs: pytest.fail("Incomplete study read Development feature payload"))
    monkeypatch.setattr(finalizer, "_branch_summary", lambda *args, **kwargs: pytest.fail("Incomplete study replayed fitted artifacts"))
    candidate = {"candidateId": "failed", "status": "FAILED", "foldsCompleted": 0, "folds": [], "errorReason": "[WinError 5] Access is denied"}
    terminal = {"status": "PARTIAL", "plan": {"checksum": "frozen-plan"}, "identity": {"targetOrder": list(GOLD_CLASS_ORDER)},
                "population": {"finalOotLocked": True, "finalOotTargetAccessed": False, "finalOotScored": False}, "finalOotAccessed": False, "finalOotTargetsMaterialized": False,
                "candidates": [candidate], "candidateAttemptReceipts": [{"candidateId": "failed", "candidateReceiptSha256": "attempt"}],
                "runtimeMs": 111735, "failures": [{"reason": "[WinError 5] Access is denied", "failedFits": 5}]}
    attempt = {"candidate": candidate, "jobId": "job", "planChecksum": "frozen-plan", "finalOotTargetAccessed": False}
    monkeypatch.setattr(finalizer, "read_immutable_json", lambda path, checksum: terminal if checksum == "run" else attempt)
    frozen = {"studyChecksum": "frozen", "authority": {"treatmentVersion": 18}, "plan": {"checksum": "frozen-plan"}, "targetOrder": list(GOLD_CLASS_ORDER),
              "development": {"rows": 683662}, "rowEligibility": {"eligibleRows": 683606, "heldRows": 56}, "modelFoldPopulations": [{"validationRows": 501539}],
              "foldSeeds": [], "executionResourceComparison": {}}
    job = {"jobId": "job", "status": "PARTIAL", "artifacts": {"runReceiptSha256": "run"},
           "progress": {"completedFits": 0, "completedConfigurations": 0, "failedConfigurations": 1, "failedFits": 5}}
    result = finalizer._incomplete_result(frozen, job)
    accounting = result["executionAccounting"]
    assert accounting["completedFitMilestones"] == 0 and accounting["completedFoldReceipts"] == 0
    assert accounting["failedConfigurations"] == 1 and accounting["scheduledFitSlotsMarkedFailed"] == 5
    assert accounting["actualEstimatorFitCallsStarted"] is None
    assert result["correctedComparison"]["correctedMetrics"] is None
    assert result["correctedComparison"]["pairedGameClusteredConfidenceInterval"] is None
    assert result["correctedComparison"]["subgroupResults"] is None
    assert result["finalizerActivity"]["ooFPredictionPayloadsRead"] == 0
    assert len(result["baseline"]["originalPopulationMetrics"]["classCalibration"]) == 8
    assert len(result["immutableArtifactReferences"]) == 2
    markdown = finalizer._report_markdown(result)
    assert "not evidence of that many actual estimator.fit calls" in markdown
    assert "Actual fit starts are unknown" in markdown
    assert "Corrected log loss/Brier/AUC/calibration" in markdown
