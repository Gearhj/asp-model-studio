from __future__ import annotations

import asyncio
from copy import deepcopy
import inspect
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import HTTPException, UploadFile

from server.core.result_store import ResultStore
from server.evaluation import eval_router, eval_service
from server.preprocessing.execution_contract import (
    canonical_preprocessing_hash,
    default_no_treatment_contract,
)
from server.scoring_runs import scoring_run_service


PROJECT_ID = "project-exact"
MODEL_ID = "model-exact"
MODEL_VERSION_ID = "mv-exact"
DATASET_ID = "dataset-exact"
DATASET_VERSION_ID = "dataset-version-exact"
TARGET = "outcome"
CANDIDATE_ID = "candidate-exact"
CANDIDATE_DECISION_ID = "decision-exact"
ANALYSIS_PARTITION_ID = "analysis-partition-exact"
TRAINING_POPULATION_ID = "development-population-exact"
HOLDOUT_POPULATION_ID = "final-holdout-exact"


def governed_candidate_contract() -> dict:
    preprocessing_policy = default_no_treatment_contract(
        identity={
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": DATASET_VERSION_ID,
            "analysis_partition_id": ANALYSIS_PARTITION_ID,
            "analysis_partition_revision": 1,
        },
        feature_names=["feature"],
        source="exact_registry_scoring_fixture",
    )
    return {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
        "analysis_partition_id": ANALYSIS_PARTITION_ID,
        "analysis_partition_revision": 1,
        "candidate_id": CANDIDATE_ID,
        "algorithm_id": "fixed-classifier",
        "problem_type": "classification",
        "target_name": TARGET,
        "positive_class": "yes",
        "selected_original_features": ["feature"],
        "selected_engineered_features": [],
        "training_population_id": TRAINING_POPULATION_ID,
        "training_population_rows": 2,
        "final_holdout_partition_id": HOLDOUT_POPULATION_ID,
        "final_holdout_population_rows": 2,
        "preprocessing_contract_version": 2,
        "preprocessing_policy_id": preprocessing_policy[
            "preprocessing_policy_id"
        ],
        "preprocessing_policy_revision": preprocessing_policy[
            "preprocessing_policy_revision"
        ],
        "preprocessing_policy_hash": preprocessing_policy[
            "preprocessing_policy_hash"
        ],
        "preprocessing_policy": preprocessing_policy,
        "threshold_configuration": {
            "locked_threshold": 0.7,
            "threshold_source": "development_oof",
        },
    }


def final_preprocessing_artifact(candidate_contract: dict) -> dict:
    artifact = {
        "preprocessing_contract_version": 2,
        "artifact_kind": "final_development_fitted_preprocessing",
        "artifact_checksum": "fixture-final-fit-exact",
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION_ID,
        "analysis_partition_id": ANALYSIS_PARTITION_ID,
        "analysis_partition_revision": 1,
        "preprocessing_policy_id": candidate_contract[
            "preprocessing_policy_id"
        ],
        "preprocessing_policy_revision": candidate_contract[
            "preprocessing_policy_revision"
        ],
        "preprocessing_policy_hash": candidate_contract[
            "preprocessing_policy_hash"
        ],
        "candidate_decision_id": CANDIDATE_DECISION_ID,
        "candidate_id": CANDIDATE_ID,
        "fit_scope": "final_development",
        "fit_population_id": TRAINING_POPULATION_ID,
        "fit_population_count": 2,
        "fit_population_rows": 2,
        "fit_excluded_true_null_cells": 0,
        "fit_excluded_special_value_cells": 0,
        "application_scope": "external_scoring_fixed_application",
        "application_population_id": HOLDOUT_POPULATION_ID,
        "application_population_rows": 2,
        "outlier_fitted_recipe": {"features": {}},
        "missing_fitted_recipe": {"features": {}},
        "encoding_scaling_parameters": {"status": "not_requested"},
        "encoding_scaling_fitted": False,
        "feature_names": ["feature"],
        "policy_scope": "governed_recipe",
        "final_holdout_target_accessed": False,
        "final_holdout_parameter_influence": False,
        "final_holdout_used_for_selection": False,
        "final_holdout_transformed_or_materialized_prelock": False,
        "final_holdout_opened_for_final_reporting": True,
        "validation_fold_parameter_influence": False,
        "refit_during_application": False,
    }
    artifact["final_artifact_checksum"] = canonical_preprocessing_hash(
        {
            key: value
            for key, value in artifact.items()
            if key not in {"fitted_at", "final_artifact_checksum"}
        }
    )
    return artifact


def exact_version(**overrides):
    candidate_contract = governed_candidate_contract()
    final_artifact = final_preprocessing_artifact(candidate_contract)
    version = {
        "modelId": MODEL_ID,
        "modelVersionId": MODEL_VERSION_ID,
        "versionNumber": 3,
        "projectId": PROJECT_ID,
        "datasetId": DATASET_ID,
        "datasetVersionId": DATASET_VERSION_ID,
        "targetName": TARGET,
        "featureManifestVersion": "",
        "algorithm": "fixed-classifier",
        "publicationStatus": "finalized",
        "lineageStatus": "verified",
        "lockedThreshold": 0.7,
        "thresholdSource": "development_oof",
        "interpretationSummary": {"selectedFeatures": ["feature"]},
        "lineage": {
            "projectId": PROJECT_ID,
            "datasetId": DATASET_ID,
            "datasetVersionId": DATASET_VERSION_ID,
            "target": TARGET,
            "positiveClass": "yes",
            "candidateContract": candidate_contract,
        },
        "modelContract": {
            "candidateDecisionId": CANDIDATE_DECISION_ID,
            "candidateContract": candidate_contract,
            "finalPreprocessingArtifact": final_artifact,
            "preprocessingContractVersion": 2,
            "preprocessingPolicyId": candidate_contract[
                "preprocessing_policy_id"
            ],
            "preprocessingPolicyRevision": candidate_contract[
                "preprocessing_policy_revision"
            ],
            "preprocessingPolicyHash": candidate_contract[
                "preprocessing_policy_hash"
            ],
            "finalPreprocessingArtifactChecksum": final_artifact[
                "final_artifact_checksum"
            ],
            "preprocessingFitScope": final_artifact["fit_scope"],
            "preprocessingFitPopulationId": final_artifact[
                "fit_population_id"
            ],
            "preprocessingFitPopulationRows": final_artifact[
                "fit_population_rows"
            ],
        },
    }
    version.update(overrides)
    return version


class FixedClassifier:
    classes_ = np.asarray(["no", "yes"])

    def __init__(self):
        self.preprocessing_artifact_ = final_preprocessing_artifact(
            governed_candidate_contract()
        )

    def predict_proba(self, frame):
        probability = np.asarray(frame["feature"], dtype=float)
        return np.column_stack([1.0 - probability, probability])


class DecisionClassifier:
    classes_ = np.asarray(["no", "yes"])

    def decision_function(self, frame):
        return np.asarray(frame["feature"], dtype=float)


class PositiveClassFirstClassifier:
    classes_ = np.asarray(["yes", "no"])

    def predict_proba(self, frame):
        positive_probability = np.asarray(frame["feature"], dtype=float)
        return np.column_stack(
            [positive_probability, 1.0 - positive_probability]
        )


class PositiveClassFirstDecisionClassifier:
    classes_ = np.asarray(["yes", "no"])

    def decision_function(self, frame):
        # Positive raw values favor sklearn's classes_[1] ("no").
        return np.asarray(frame["feature"], dtype=float)


class ExactRegistryResolutionTests(unittest.TestCase):
    def test_router_loads_only_the_requested_verified_version(self):
        artifact = FixedClassifier()
        user = {"userId": "owner"}
        with (
            patch.object(eval_router.REGISTRY, "get_version", return_value=exact_version()) as get_version,
            patch.object(eval_router.REGISTRY, "load_version_artifact", return_value=artifact) as load_artifact,
        ):
            resolved_artifact, metadata = eval_router._resolve_exact_scoring_version(
                user,
                project_id=PROJECT_ID,
                model_version_id=MODEL_VERSION_ID,
                dataset_id=DATASET_ID,
                dataset_version_id=DATASET_VERSION_ID,
                target=TARGET,
            )

        self.assertIs(resolved_artifact, artifact)
        get_version.assert_called_once_with(user, MODEL_VERSION_ID)
        load_artifact.assert_called_once_with(
            user,
            MODEL_VERSION_ID,
            expected_project_id=PROJECT_ID,
        )
        self.assertEqual(metadata["modelVersionId"], MODEL_VERSION_ID)
        self.assertEqual(metadata["datasetId"], DATASET_ID)
        self.assertEqual(metadata["datasetVersionId"], DATASET_VERSION_ID)
        self.assertEqual(metadata["target"], TARGET)
        self.assertEqual(metadata["features"], ["feature"])
        self.assertEqual(metadata["lockedThreshold"], 0.7)
        self.assertEqual(metadata["positiveClass"], "yes")
        self.assertEqual(metadata["problemType"], "classification")
        self.assertIs(metadata["candidateContract"], metadata["candidate_contract"])

    def test_cross_project_and_dataset_version_mismatches_fail_before_artifact_load(self):
        cases = (
            ({"projectId": "other-project"}, {}),
            ({"datasetVersionId": "other-version"}, {}),
            ({}, {"target": "other-target"}),
        )
        for version_overrides, request_overrides in cases:
            with self.subTest(version_overrides=version_overrides, request_overrides=request_overrides):
                with (
                    patch.object(
                        eval_router.REGISTRY,
                        "get_version",
                        return_value=exact_version(**version_overrides),
                    ),
                    patch.object(eval_router.REGISTRY, "load_version_artifact") as load_artifact,
                ):
                    with self.assertRaises(HTTPException) as raised:
                        eval_router._resolve_exact_scoring_version(
                            {"userId": "owner"},
                            project_id=PROJECT_ID,
                            model_version_id=MODEL_VERSION_ID,
                            dataset_id=DATASET_ID,
                            dataset_version_id=DATASET_VERSION_ID,
                            target=request_overrides.get("target", TARGET),
                        )
                self.assertEqual(raised.exception.status_code, 409)
                load_artifact.assert_not_called()

    def test_public_score_routes_require_exact_identity_and_have_no_model_selector(self):
        for endpoint in (eval_router.score_upload, eval_router.score_development_split):
            parameters = inspect.signature(endpoint).parameters
            self.assertNotIn("model", parameters)
            for field in (
                "project_id",
                "model_version_id",
                "dataset_id",
                "dataset_version_id",
                "target",
            ):
                self.assertIn(field, parameters)


class ExactArtifactScoringTests(unittest.TestCase):
    def test_positive_class_selects_the_estimator_class_column_not_column_one(self):
        scores = eval_service.EvaluationService()._predict_score(
            PositiveClassFirstClassifier(),
            pd.DataFrame({"feature": [0.2, 0.9]}),
            positive_class="yes",
        )
        np.testing.assert_allclose(scores, np.asarray([0.2, 0.9]))
        decision_scores = eval_service.EvaluationService()._predict_score(
            PositiveClassFirstDecisionClassifier(),
            pd.DataFrame({"feature": [-2.0, 2.0]}),
            positive_class="yes",
        )
        self.assertGreater(decision_scores[0], decision_scores[1])

    def test_decision_function_score_is_invariant_to_other_batch_rows(self):
        service = eval_service.EvaluationService()
        model = DecisionClassifier()
        score_alone = service._predict_score(
            model,
            pd.DataFrame({"feature": [0.25]}),
            positive_class="yes",
        )[0]
        score_in_batch = service._predict_score(
            model,
            pd.DataFrame({"feature": [-100.0, 0.25, 100.0]}),
            positive_class="yes",
        )[1]
        self.assertAlmostEqual(float(score_alone), float(score_in_batch), places=12)

    def test_scoring_survives_cleared_results_without_final_or_latest_fallback(self):
        service = eval_service.EvaluationService()
        service._resolve_scoring_model = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("volatile model resolution must not run")
        )
        empty_results = ResultStore()
        metadata = {
            "modelId": MODEL_ID,
            "modelVersionId": MODEL_VERSION_ID,
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": DATASET_VERSION_ID,
            "target": TARGET,
            "problem_type": "classification",
            "features": ["feature"],
            "locked_threshold": 0.7,
            "positive_class": "yes",
            "candidate_contract": governed_candidate_contract(),
            "candidate_decision_id": CANDIDATE_DECISION_ID,
            "final_preprocessing_artifact": final_preprocessing_artifact(
                governed_candidate_contract()
            ),
        }
        frame = pd.DataFrame(
            {"feature": [0.6, 0.8], TARGET: ["no", "yes"]}
        )

        with patch.object(eval_service, "RESULTS", empty_results):
            result = service.score_dataset(
                frame,
                dataset_type="external",
                model_artifact=FixedClassifier(),
                model_metadata=metadata,
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["model"]["modelVersionId"], MODEL_VERSION_ID)
        self.assertEqual(result["target_column"], TARGET)
        self.assertEqual(
            [row["prediction"] for row in result["scored_rows"]],
            [0, 1],
        )
        self.assertEqual(
            result["scoring_diagnostics"]["classification_threshold"], 0.7
        )

    def test_completed_score_persistence_failure_never_returns_success(self):
        upload = UploadFile(
            filename="external.csv",
            file=io.BytesIO(b"feature,outcome\n0.8,yes\n"),
        )
        metadata = {
            "modelId": MODEL_ID,
            "modelVersionId": MODEL_VERSION_ID,
            "modelVersion": 3,
            "projectId": PROJECT_ID,
            "datasetId": DATASET_ID,
            "datasetVersionId": DATASET_VERSION_ID,
            "target": TARGET,
            "problemType": "classification",
            "featureManifestVersion": "manifest-exact",
        }
        successful_result = {
            "ok": True,
            "rows": 1,
            "model": metadata,
            "scored_rows": [],
            "scored_columns": [],
        }
        with (
            patch.object(eval_router, "authorize_modeling_scope"),
            patch.object(
                eval_router,
                "_resolve_exact_scoring_version",
                return_value=(FixedClassifier(), metadata),
            ),
            patch.object(eval_router.EVAL, "score_dataset", return_value=successful_result),
            patch.object(eval_router, "create_scoring_run", return_value=None),
        ):
            with self.assertRaises(HTTPException) as raised:
                asyncio.run(
                    eval_router.score_upload(
                        file=upload,
                        project_id=PROJECT_ID,
                        model_version_id=MODEL_VERSION_ID,
                        dataset_id=DATASET_ID,
                        dataset_version_id=DATASET_VERSION_ID,
                        target=TARGET,
                        dataset_type="test",
                        correction_method="none",
                        original_prior=None,
                        model_prior=None,
                        user={"userId": "owner"},
                    )
                )
        self.assertEqual(raised.exception.status_code, 503)


class ExactScoringRunLineageTests(unittest.TestCase):
    def setUp(self):
        self.saved_records = []
        repository = SimpleNamespace(upsert=self._save)
        self.persistence = SimpleNamespace(scoring_runs=repository)
        self.context = {
            "source": "csv_upload",
            "datasetIdentity": "external.csv",
            "projectId": PROJECT_ID,
            "datasetId": DATASET_ID,
            "datasetVersionId": DATASET_VERSION_ID,
            "target": TARGET,
            "modelId": MODEL_ID,
            "modelVersion": 3,
            "modelVersionId": MODEL_VERSION_ID,
            "featureManifestVersion": "manifest-exact",
            "problemType": "classification",
        }

    def _save(self, record):
        self.saved_records.append(record)
        return record

    def test_completed_and_failed_runs_store_the_same_exact_version_context(self):
        completed_result = {
            "ok": True,
            "task": "classification",
            "rows": 1,
            "scored_rows": [{"feature": 0.8, "prediction": 1}],
            "model": {
                "modelId": MODEL_ID,
                "modelVersionId": MODEL_VERSION_ID,
                "problemType": "classification",
                "target": TARGET,
            },
        }
        with (
            patch.object(scoring_run_service, "authorize_modeling_scope"),
            patch.object(
                scoring_run_service,
                "get_persistence_service",
                return_value=self.persistence,
            ),
            patch.object(
                scoring_run_service,
                "write_scoring_run_parquet",
                return_value={"path": "scoring/exact.parquet", "checksum": "sha256:exact"},
            ),
            patch.object(scoring_run_service, "_record_evidence"),
        ):
            completed = scoring_run_service.create_scoring_run(
                {"userId": "owner"},
                PROJECT_ID,
                "test",
                completed_result,
                self.context,
            )
            failed = scoring_run_service.create_failed_scoring_run(
                {"userId": "owner"},
                PROJECT_ID,
                "oot",
                "missing feature",
                self.context,
            )

        self.assertEqual(completed["modelVersionId"], MODEL_VERSION_ID)
        self.assertEqual(failed["modelVersionId"], MODEL_VERSION_ID)
        for record in self.saved_records:
            self.assertEqual(record["project_id"], PROJECT_ID)
            self.assertEqual(record["model_id"], MODEL_ID)
            self.assertEqual(record["model_version_id"], MODEL_VERSION_ID)
            self.assertEqual(record["dataset_id"], DATASET_ID)
            self.assertEqual(record["dataset_version_id"], DATASET_VERSION_ID)
            self.assertEqual(record["target"], TARGET)
            self.assertEqual(record["lineage_json"]["modelSource"], "REGISTRY.model_version")


if __name__ == "__main__":
    unittest.main()
