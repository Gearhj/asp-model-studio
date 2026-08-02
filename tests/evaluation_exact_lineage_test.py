from __future__ import annotations

from pathlib import Path
import copy
import hashlib
import inspect
import json
import sys
import uuid

import pandas as pd
import pytest
from fastapi import HTTPException


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.dataset_store import DATASTORE
from server.core.result_store import RESULTS, ResultStore
from server.core.session_checkpoint import _apply_results, _encode_results
from server.evaluation.eval_service import EVAL
from server.evaluation import eval_router
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.training.candidate_contract import canonical_contract_hash


ALGORITHM_ID = "logreg"
LINEAGE = {
    "project_id": "project-eval-1",
    "dataset_id": "dataset-eval-1",
    "dataset_version_id": "dataset-version-eval-1",
    "candidate_id": "candidate-eval-opaque-1",
    "training_job_id": "training-job-eval-1",
    "training_run_id": "training-run-eval-1",
    "feature_manifest_version": "manifest-eval-1",
    "validation_design_id": "validation-design-eval-1",
    "validation_design_version": "validation-design-version-eval-1",
    "split_id": "split-eval-1",
    "target": "bad_flag",
    "problem_type": "classification",
    "candidate_decision_id": "decision-eval-1",
}


class CandidateArtifact:
    classes_ = [0, 1]

    def predict_proba(self, frame):
        import numpy as np

        scores = np.linspace(0.15, 0.85, len(frame))
        return np.column_stack([1.0 - scores, scores])

    def predict(self, frame):
        import numpy as np

        return np.linspace(12.0, 38.0, len(frame))


@pytest.fixture(autouse=True)
def isolated_governance_database():
    temporary_root = Path(".tmp")
    temporary_root.mkdir(parents=True, exist_ok=True)
    database_path = temporary_root / (
        f"evaluation-governance-{uuid.uuid4().hex}.db"
    )
    database = Database(database_path)
    database.initialize()
    previous = EVAL._persistence_service
    EVAL._persistence_service = PersistenceService(database)
    try:
        yield EVAL._persistence_service
    finally:
        EVAL._persistence_service = previous
        for suffix in ("", "-wal", "-shm"):
            Path(str(database_path) + suffix).unlink(missing_ok=True)


def seed_durable_decision(candidate_contract: dict, decision: dict) -> None:
    metric = candidate_contract["selection_metric"]
    snapshot = [
        {
            "rank": 1,
            "candidate_id": candidate_contract["candidate_id"],
            "candidate_contract_hash": candidate_contract["contract_hash"],
            "selection_metric": copy.deepcopy(metric),
        }
    ]
    ranking_snapshot_hash = canonical_contract_hash(snapshot)
    decision["selection_ranking_snapshot_hash"] = ranking_snapshot_hash
    threshold = candidate_contract["threshold_configuration"]
    decision_record = {
            "candidate_decision_id": decision["decision_id"],
            "decision_status": "locked",
            "project_id": candidate_contract["project_id"],
            "dataset_id": candidate_contract["dataset_id"],
            "dataset_version_id": candidate_contract["dataset_version_id"],
            "feature_manifest_id": candidate_contract["feature_manifest_id"],
            "feature_manifest_hash": candidate_contract[
                "feature_manifest_hash"
            ],
            "treatment_manifest_id": candidate_contract[
                "treatment_manifest_id"
            ],
            "treatment_manifest_hash": candidate_contract[
                "treatment_manifest_hash"
            ],
            "materialization_id": candidate_contract["materialization_id"],
            "validation_design_id": candidate_contract[
                "validation_design_id"
            ],
            "validation_design_version_id": candidate_contract[
                "validation_design_version"
            ],
            "split_id": candidate_contract["split_id"],
            "final_holdout_partition_id": candidate_contract[
                "final_holdout_partition_id"
            ],
            "training_job_id": candidate_contract["training_job_id"],
            "training_run_id": candidate_contract["training_run_id"],
            "candidate_id": candidate_contract["candidate_id"],
            "selected_candidate_contract_hash": candidate_contract[
                "contract_hash"
            ],
            "selection_metric_name": metric["selection_metric_name"],
            "selection_metric_value": metric["selection_metric_value"],
            "selection_metric_source": metric["selection_metric_source"],
            "selection_metric_created_at": metric["created_at"],
            "selection_partition_id": metric["selection_partition_id"],
            "fold_definition_id": metric["fold_definition_id"],
            "fold_count": metric["fold_count"],
            "fold_values_json": metric["fold_values"],
            "selection_metric_mean": metric["mean"],
            "selection_metric_std": metric["standard_deviation"],
            "out_of_fold_prediction_artifact_id": metric[
                "out_of_fold_prediction_artifact_id"
            ],
            "threshold_source": metric["threshold_source"],
            "locked_threshold": threshold["locked_threshold"],
            "threshold_locked_at": threshold["threshold_locked_at"],
            "threshold_policy_hash": threshold[
                "threshold_policy_hash"
            ],
            "calibration_source": metric["calibration_source"],
            "ranking_snapshot_json": snapshot,
            "ranking_snapshot_hash": ranking_snapshot_hash,
            "selection_rationale": "Selected from governed OOF evidence.",
            "selection_locked_at": decision["selection_locked_at"],
            "actor": "evaluation-test",
            "selection_integrity_status": "verified",
            "selection_integrity_reason": (
                "Selection used governed training-only validation evidence."
            ),
            "holdout_isolation_status": "verified",
            "holdout_isolation_reason": (
                "The final holdout remained sealed until this lock."
            ),
            "integrity_classified_by": "evaluation-test",
            "created_at": metric["created_at"],
    }
    decision_record["decision_contract_hash"] = canonical_contract_hash(
        decision_record
    )
    EVAL._governance_repository().insert_selection_decision_if_absent(
        decision_record
    )


def seed_exact_candidate(
    *,
    kind: str = "supervised",
    champion_eligible: bool = True,
    frozen_threshold: float | None = None,
    problem_type: str = "classification",
) -> dict[str, str]:
    DATASTORE.reset_all()
    RESULTS.clear_model_artifacts()
    RESULTS.evaluation_packages = {}
    RESULTS.holdout_evaluations = {}
    RESULTS.selection_integrity_records = {}
    X_train = pd.DataFrame({"income": [10.0, 20.0, 30.0, 40.0], "util": [0.1, 0.2, 0.3, 0.4]})
    X_test = pd.DataFrame({"income": [15.0, 25.0, 35.0, 45.0], "util": [0.15, 0.25, 0.35, 0.45]})
    y_train = pd.Series([0, 0, 1, 1], name=LINEAGE["target"])
    y_test = pd.Series([0, 1, 0, 1], name=LINEAGE["target"])
    DATASTORE.set_raw(pd.concat([X_train, X_test], ignore_index=True))
    DATASTORE.set_target(LINEAGE["target"])
    DATASTORE.set_splits(X_train, X_test, y_train, y_test)
    DATASTORE.meta.update(
        {
            "project_id": LINEAGE["project_id"],
            "dataset_id": LINEAGE["dataset_id"],
            "dataset_version_id": LINEAGE["dataset_version_id"],
            "dataset_identity_status": "current",
            "split_status": "current",
            "feature_manifest": {
                "manifest_hash": LINEAGE["feature_manifest_version"],
                "confirmation_status": "confirmed",
                "materialization_status": "current",
            },
            "split_record": {
                "project_id": LINEAGE["project_id"],
                "dataset_id": LINEAGE["dataset_id"],
                "dataset_version_id": LINEAGE["dataset_version_id"],
                "feature_manifest_version": LINEAGE["feature_manifest_version"],
                "split_id": LINEAGE["split_id"],
                "training_population_id": "population-train-eval-1",
                "holdout_population_id": "population-holdout-eval-1",
                "validation_design": {
                    "validation_design_id": LINEAGE["validation_design_id"],
                    "design_version": LINEAGE["validation_design_version"],
                    "status": "approved",
                    "development_dataset": {
                        "dataset_id": LINEAGE["dataset_id"],
                        "dataset_version_id": LINEAGE["dataset_version_id"],
                    },
                },
            },
        }
    )
    threshold_source = (
        "not_applicable"
        if problem_type == "regression"
        else (
            "cross_validation"
            if frozen_threshold is not None
            else "platform_governed_default_0_5"
        )
    )
    locked_threshold = (
        None
        if problem_type == "regression"
        else (0.5 if frozen_threshold is None else frozen_threshold)
    )
    threshold_policy = {
        "locked_threshold": locked_threshold,
        "threshold_source": threshold_source,
        "threshold_locked_at": "2026-07-31T00:00:00Z",
        "selection_threshold_tuned": False,
    }
    threshold_policy_hash = canonical_contract_hash(threshold_policy)
    candidate_contract = {
        "project_id": LINEAGE["project_id"],
        "dataset_id": LINEAGE["dataset_id"],
        "dataset_version_id": LINEAGE["dataset_version_id"],
        "training_dataset_id": LINEAGE["dataset_id"],
        "training_dataset_version_id": LINEAGE["dataset_version_id"],
        "target": LINEAGE["target"],
        "target_name": LINEAGE["target"],
        "problem_type": problem_type,
        "target_definition": {
            "target_name": LINEAGE["target"],
            "problem_type": problem_type,
            "positive_class": 1,
            "negative_class": 0,
        },
        "target_contract_id": "target-contract-eval-1",
        "positive_class": 1,
        "predictor_manifest_id": "predictor-manifest-eval-1",
        "predictor_manifest_hash": "predictor-hash-eval-1",
        "treatment_manifest_id": "treatment-manifest-eval-1",
        "treatment_manifest_hash": "treatment-hash-eval-1",
        "materialization_id": "materialization-eval-1",
        "feature_manifest_id": "feature-manifest-eval-1",
        "feature_manifest_hash": LINEAGE["feature_manifest_version"],
        "feature_manifest_version": LINEAGE["feature_manifest_version"],
        "validation_design_id": LINEAGE["validation_design_id"],
        "validation_design_version": LINEAGE["validation_design_version"],
        "split_id": LINEAGE["split_id"],
        "training_job_id": LINEAGE["training_job_id"],
        "training_run_id": LINEAGE["training_run_id"],
        "candidate_id": LINEAGE["candidate_id"],
        "algorithm_id": ALGORITHM_ID,
        "algorithm_class": "sklearn.linear_model.LogisticRegression",
        "algorithm_version": "1.0",
        "hyperparameter_manifest": {},
        "calibration_configuration": {},
        "ranking_metric": "rmse" if problem_type == "regression" else "roc_auc",
        "training_population_id": "population-train-eval-1",
        "selection_partition_id": "population-train-eval-1",
        "holdout_population_id": "population-holdout-eval-1",
        "final_holdout_partition_id": "population-holdout-eval-1",
        "fold_definition_id": "fold-definition-eval-1",
        "final_holdout_status": "sealed",
        "selection_resampling_status": "not_applied",
        "selection_metric": {
            "selection_metric_name": (
                "rmse" if problem_type == "regression" else "roc_auc"
            ),
            "selection_metric_value": (
                1.0 if problem_type == "regression" else 0.88
            ),
            "selection_metric_source": "out_of_fold",
            "selection_partition_id": "population-train-eval-1",
            "fold_definition_id": "fold-definition-eval-1",
            "fold_count": 2,
            "fold_values": (
                [0.9, 1.1] if problem_type == "regression" else [0.86, 0.90]
            ),
            "mean": 1.0 if problem_type == "regression" else 0.88,
            "standard_deviation": (
                0.1 if problem_type == "regression" else 0.02
            ),
            "out_of_fold_prediction_artifact_id": "oof-eval-1",
            "threshold_source": threshold_source,
            "calibration_source": "fold_local_training_only",
            "created_at": "2026-07-31T00:00:00Z",
        },
        "selection_integrity_status": "verified",
        "holdout_isolation_status": "verified",
        "positive_class_index": 1,
        "class_encoding": {
            "class_labels": [0, 1],
            "positive_class_index": 1,
            "positive_class_label": 1,
            "fit_partition": "training_only",
        },
        "threshold_configuration": {
            **threshold_policy,
            "threshold_policy_hash": threshold_policy_hash,
        },
        "candidate_state": "complete",
        "champion_eligible": champion_eligible,
        "created_by": "evaluation-test",
        "created_at": "2026-07-31T00:00:00Z",
        "runtime_environment": {
            "python_version": "test",
            "platform": "test",
            "package_versions": {},
            "code_version": "test",
        },
        "worker_configuration": {
            "requested_workers": 1,
            "honored_workers": 1,
            "execution_mode": "test",
        },
        "random_seed": 42,
        "training_contract_hash": "training-contract-hash-eval-1",
    }
    candidate_contract["contract_hash"] = canonical_contract_hash(candidate_contract)
    candidate = {
        "key": ALGORITHM_ID,
        "candidate_id": LINEAGE["candidate_id"],
        "candidate_contract": candidate_contract,
        "name": "Logistic Regression",
        "kind": kind,
        "champion_eligible": champion_eligible,
        "target_usage": "supervised" if kind != "anomaly" else "none",
        "auc": 0.91,
        "selection_metric": copy.deepcopy(candidate_contract["selection_metric"]),
        "selection_integrity_status": "verified",
        "holdout_isolation_status": "verified",
    }
    raw_result = {"task": problem_type, "metric_class": "selection"}
    RESULTS.set_last_summary(
        {
            **{
                field: value
                for field, value in LINEAGE.items()
                if field not in {"candidate_id", "problem_type"}
            },
            "problem_type": problem_type,
            "ranked": [candidate],
            "raw": {ALGORITHM_ID: raw_result},
        }
    )
    RESULTS.set_model_artifacts(
        {ALGORITHM_ID: CandidateArtifact()},
        {
            ALGORITHM_ID: {
                **LINEAGE,
                "problem_type": problem_type,
                "model_key": ALGORITHM_ID,
                "candidate_contract": candidate_contract,
                "trained_feature_names": list(X_train.columns),
            }
        },
    )
    DATASTORE.meta["model_selection_decision"] = {
        **{field: value for field, value in LINEAGE.items() if field != "candidate_decision_id"},
        "decision_id": LINEAGE["candidate_decision_id"],
        "selected_candidate_id": LINEAGE["candidate_id"],
        "status": "locked",
        "selection_metric": copy.deepcopy(candidate_contract["selection_metric"]),
        "selection_integrity_status": "verified",
        "holdout_isolation_status": "verified",
        "selection_ranking_snapshot_hash": "ranking-snapshot-eval-1",
        "selection_locked_at": "2026-07-31T00:01:00Z",
        "threshold_locked_at": "2026-07-31T00:00:00Z",
        "locked_threshold": locked_threshold,
        "threshold_source": threshold_source,
        "threshold_policy_hash": threshold_policy_hash,
        "actor": {"user_id": "evaluation-test"},
    }
    seed_durable_decision(
        candidate_contract,
        DATASTORE.meta["model_selection_decision"],
    )
    return {**LINEAGE, "problem_type": problem_type}


def assert_lineage_rejected(payload: dict, phrase: str) -> None:
    assert payload["ok"] is False
    assert payload["lineage_error"] is True
    assert phrase in payload["error"].lower()


def complete_evaluation_package(context: dict[str, str]) -> dict:
    command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        context=context,
    )
    package = EVAL.bind_evaluation_package(
        context["candidate_id"],
        context,
        command,
        "command_center",
        actor_user_id="evaluation-test",
    )
    assert package["ok"] is True
    assert package["evaluation_package"]["status"] == "complete"
    durable_package = EVAL._governance_repository().get_evaluation_package(
        package["evaluation_package_id"]
    )
    assert durable_package is not None
    assert durable_package["package_status"] == "complete"
    assert durable_package["package_integrity_status"] == "verified"
    assert durable_package["package_payload_json"] == package[
        "evaluation_package"
    ]
    durable_exposure = EVAL._governance_repository().get_holdout_exposure(
        durable_package["holdout_exposure_id"]
    )
    assert durable_exposure is not None
    assert durable_exposure["final_holdout_status"] == "evaluated"
    assert durable_exposure["evaluation_package_id"] == package[
        "evaluation_package_id"
    ]
    candidate_contract = RESULTS.get_last_summary()["ranked"][0]["candidate_contract"]
    governed = package["evaluation_package"]["governed_candidate_contract"]
    assert governed["target_contract_id"] == candidate_contract["target_contract_id"]
    assert governed["target_definition"] == candidate_contract["target_definition"]
    assert governed["feature_manifest_id"] == candidate_contract["feature_manifest_id"]
    assert governed["feature_manifest_hash"] == candidate_contract["feature_manifest_hash"]
    assert package["governed_candidate_contract"] == governed
    return package


def test_evaluation_does_not_report_completion_when_durable_package_write_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = seed_exact_candidate()
    command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        context=context,
    )
    repository = EVAL._governance_repository()
    monkeypatch.setattr(
        repository,
        "insert_evaluation_package_if_absent",
        lambda record, **kwargs: (_ for _ in ()).throw(
            RuntimeError("write failed")
        ),
    )

    response = EVAL.bind_evaluation_package(
        context["candidate_id"],
        context,
        command,
        "command_center",
        actor_user_id="evaluation-test",
    )

    assert response["ok"] is False
    assert "authoritative governance registry" in response["error"]
    assert RESULTS.evaluation_packages == {}
    volatile_exposure = RESULTS.get_holdout_evaluation(context["candidate_id"])
    assert volatile_exposure is not None
    exposure = repository.get_holdout_exposure(
        volatile_exposure["holdout_exposure_id"]
    )
    assert exposure is not None
    assert exposure["final_holdout_status"] == "opened"


def test_evaluation_retry_recovers_after_atomic_completion_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = seed_exact_candidate()
    command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        context=context,
    )
    repository = EVAL._governance_repository()
    original_complete = repository.complete_evaluation_package
    monkeypatch.setattr(
        repository,
        "complete_evaluation_package",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("atomic completion failed")
        ),
    )

    first = EVAL.bind_evaluation_package(
        context["candidate_id"],
        context,
        command,
        "command_center",
        actor_user_id="evaluation-test",
    )

    assert first["ok"] is False
    with repository.database.connection() as connection:
        rows = connection.execute(
            "SELECT evaluation_package_id FROM evaluation_packages"
        ).fetchall()
    assert rows == []
    volatile_exposure = RESULTS.get_holdout_evaluation(context["candidate_id"])
    assert volatile_exposure is not None
    exposure_id = volatile_exposure["holdout_exposure_id"]
    assert repository.get_holdout_exposure(exposure_id)[
        "final_holdout_status"
    ] == "opened"

    monkeypatch.setattr(
        repository,
        "complete_evaluation_package",
        original_complete,
    )
    retry = EVAL.bind_evaluation_package(
        context["candidate_id"],
        context,
        command,
        "command_center",
        actor_user_id="evaluation-test",
    )

    assert retry["ok"] is True
    package_id = retry["evaluation_package_id"]
    durable_package = repository.get_evaluation_package(package_id)
    assert durable_package is not None
    assert repository.get_holdout_exposure(exposure_id)[
        "final_holdout_status"
    ] == "evaluated"


def test_completed_evaluation_package_recovers_from_exact_durable_payload() -> None:
    context = seed_exact_candidate()
    completed = complete_evaluation_package(context)
    package_id = completed["evaluation_package_id"]
    candidate_contract = copy.deepcopy(
        RESULTS.get_last_summary()["ranked"][0]["candidate_contract"]
    )

    RESULTS.evaluation_packages.clear()

    recovered, error = EVAL._completed_evaluation_package(
        context,
        package_id,
        candidate_contract=candidate_contract,
    )

    assert error == ""
    assert recovered == completed["evaluation_package"]
    assert RESULTS.get_evaluation_package(package_id) == recovered


def seed_exact_regression_candidate() -> dict[str, str]:
    return seed_exact_candidate(problem_type="regression")


def test_exact_evaluation_and_interpretation_artifacts_share_lineage() -> None:
    context = seed_exact_candidate()
    curves = EVAL.get_curves(context["candidate_id"], context)
    package = EVAL.bind_evaluation_package(context["candidate_id"], context, curves, "curves")
    completed = complete_evaluation_package(context)
    interpretation = EVAL.bind_interpretation_artifact(
        context["candidate_id"],
        context,
        {"ok": True, "rows": []},
        "feature_importance",
        completed["evaluation_package_id"],
    )
    assert package["ok"] is True
    assert package["lineage"] == context
    assert package["evaluation_package"]["evaluation_population"] == "governed_holdout"
    assert interpretation["lineage"] == context
    assert completed["evaluation_package_id"] != package["evaluation_package_id"]
    assert interpretation["evaluation_package_id"] == completed["evaluation_package_id"]
    assert interpretation["interpretation_artifact_id"].startswith("interpretation-")


def test_registry_handoff_is_exact_and_delegated() -> None:
    context = seed_exact_candidate()
    blocked = EVAL.registry_promotion_handoff(
        context["candidate_id"],
        context,
        {"name": "Logistic Regression", "metrics": {"auc": 0.91}},
        "evalpkg-does-not-exist",
    )
    assert blocked["ready"] is False
    assert "absent from the authoritative governance registry" in blocked[
        "error"
    ].lower()
    completed = complete_evaluation_package(context)
    handoff = EVAL.registry_promotion_handoff(
        context["candidate_id"],
        context,
        {"name": "Logistic Regression", "metrics": {"auc": 0.91}},
        completed["evaluation_package_id"],
    )
    assert handoff["ready"] is True
    assert handoff["registry_persistence"] == "delegated"
    assert handoff["exact_version_contract"] == context
    assert handoff["evaluation_package_id"].startswith("evalpkg-")
    assert handoff["evaluation_summary"]["status"] == "complete"
    assert handoff["evaluation_summary"]["actor_user_id"] == "evaluation-test"
    assert handoff["evaluation_summary"]["threshold"]["confusion"]
    assert handoff["evaluation_summary"]["calibration"]
    assert handoff["evaluation_summary"]["lift"]["deciles"]
    assert handoff["idempotency_key"].startswith("promotion-")
    assert handoff["consume_response_fields"] == ["modelVersion", "promotion"]


def test_regression_candidate_completes_exact_holdout_package_and_can_promote() -> None:
    context = seed_exact_regression_candidate()
    command = EVAL.get_evaluation_command_center(
        context["candidate_id"], context=context
    )
    assert command["ok"] is True
    assert command["problem_type"] == "regression"
    assert command["stability"]["test_metrics"]["rmse"] is not None
    assert command["stability"]["test_metrics"]["mae"] is not None
    assert command["stability"]["test_metrics"]["r2"] is not None
    assert command["holdout_prediction_digest"]
    assert "threshold" not in command
    package = EVAL.bind_evaluation_package(
        context["candidate_id"],
        context,
        command,
        "command_center",
        actor_user_id="evaluation-test",
    )
    assert package["ok"] is True, package
    assert package["evaluation_package"]["status"] == "complete"
    handoff = EVAL.registry_promotion_handoff(
        context["candidate_id"],
        context,
        {"name": "Regression Candidate"},
        package["evaluation_package_id"],
    )
    assert handoff["ready"] is True
    assert handoff["evaluation_summary"]["metrics"]["rmse"] is not None
    assert handoff["evaluation_summary"]["threshold"] == {}


def test_idempotent_same_run_summary_persistence_preserves_completed_package() -> None:
    context = seed_exact_candidate()
    completed = complete_evaluation_package(context)
    summary = RESULTS.get_last_summary()
    RESULTS.set_last_summary(summary)
    handoff = EVAL.registry_promotion_handoff(
        context["candidate_id"],
        context,
        {"name": "Logistic Regression"},
        completed["evaluation_package_id"],
    )
    assert handoff["ready"] is True
    assert RESULTS.get_evaluation_package(completed["evaluation_package_id"]) is not None


def test_completed_evaluation_package_survives_scoped_checkpoint_round_trip() -> None:
    context = seed_exact_candidate()
    completed = complete_evaluation_package(context)
    restored = ResultStore()
    _apply_results(restored, _encode_results(RESULTS.current()))
    package = restored.get_evaluation_package(completed["evaluation_package_id"])
    assert package is not None
    assert package["status"] == "complete"
    assert package["candidate_id"] == context["candidate_id"]
    assert package["training_run_id"] == context["training_run_id"]


def test_completed_evaluation_package_retry_is_byte_stable() -> None:
    context = seed_exact_candidate()
    command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        threshold=0.42,
        review_capacity=0.18,
        context=context,
    )
    first = EVAL.bind_evaluation_package(
        context["candidate_id"],
        context,
        command,
        "command_center",
        actor_user_id="evaluation-test",
    )
    first_snapshot = copy.deepcopy(first["evaluation_package"])
    retry = EVAL.bind_evaluation_package(
        context["candidate_id"],
        context,
        copy.deepcopy(command),
        "command_center",
        actor_user_id="evaluation-test",
    )
    assert retry["evaluation_package_id"] == first["evaluation_package_id"]
    assert retry["evaluation_package"] == first_snapshot
    assert RESULTS.get_evaluation_package(first["evaluation_package_id"]) == first_snapshot


def test_completed_evaluation_route_fails_closed_when_checkpoint_flush_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = seed_exact_candidate()
    command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        context=context,
    )
    monkeypatch.setattr(eval_router, "flush_checkpoint", lambda: False)

    with pytest.raises(HTTPException) as failure:
        eval_router._evaluation_response(
            context["candidate_id"],
            context,
            command,
            "command_center",
            "evaluation-test",
        )
    assert failure.value.status_code == 503
    assert "durably checkpointed" in str(failure.value.detail)
    assert RESULTS.evaluation_packages == {}


def test_evaluation_package_rejects_feature_or_target_contract_substitution() -> None:
    context = seed_exact_candidate()
    completed = complete_evaluation_package(context)
    package_id = completed["evaluation_package_id"]
    tampered = RESULTS.get_evaluation_package(package_id)
    tampered["governed_candidate_contract"]["feature_manifest_id"] = "feature-other"
    RESULTS.set_evaluation_package(package_id, tampered)

    bound = EVAL.bind_interpretation_artifact(
        context["candidate_id"],
        context,
        {"ok": True},
        "model_details",
        package_id,
    )
    assert bound["ok"] is False
    assert bound["lineage_error"] is True
    assert "conflicts with its immutable durable payload" in bound[
        "error"
    ].lower()


def test_threshold_configuration_cannot_change_after_holdout_evaluation() -> None:
    context = seed_exact_candidate()
    first_command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        threshold=0.35,
        review_capacity=0.10,
        context=context,
    )
    first = EVAL.bind_evaluation_package(
        context["candidate_id"], context, first_command, "command_center"
    )
    first_snapshot = copy.deepcopy(first["evaluation_package"])
    first_handoff = EVAL.registry_promotion_handoff(
        context["candidate_id"],
        context,
        {"name": "Candidate"},
        first["evaluation_package_id"],
    )

    second_command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        threshold=0.72,
        review_capacity=0.25,
        context=context,
    )
    second = EVAL.bind_evaluation_package(
        context["candidate_id"], context, second_command, "command_center"
    )
    assert second["ok"] is False
    assert second["lineage_error"] is True
    assert "another evaluation package" in second["error"].lower()
    assert first_handoff["ready"] is True
    assert RESULTS.get_evaluation_package(first["evaluation_package_id"]) == first_snapshot
    assert first_snapshot["evaluation_configuration"] == {
        "problem_type": "classification",
        "threshold": 0.35,
        "review_capacity": 0.10,
        "threshold_source": "user_supplied_reporting_value",
        "final_holdout_role": "reporting_only",
    }


def test_final_holdout_changes_cannot_change_threshold_recommendations() -> None:
    context = seed_exact_candidate()
    first = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        threshold=0.42,
        review_capacity=0.10,
        context=context,
    )
    summary = RESULTS.get_last_summary()
    summary["raw"][ALGORITHM_ID]["y_true"] = [1, 1, 0, 0]
    summary["raw"][ALGORITHM_ID]["y_score"] = [0.02, 0.12, 0.88, 0.98]
    second = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        threshold=0.42,
        review_capacity=0.10,
        context=context,
    )

    assert first["holdout_prediction_digest"] == second["holdout_prediction_digest"]
    assert first["threshold"]["confusion"] == second["threshold"]["confusion"]
    assert first["presets"] == second["presets"] == {"current_governed": 0.5}
    assert first["threshold_policy"] == second["threshold_policy"]
    assert first["threshold_policy"]["final_holdout_role"] == "reporting_only"
    assert first["threshold_policy"]["recommendations_derived_from_final_holdout"] is False
    for forbidden in ("maximize_f1", "target_recall", "target_precision", "review_capacity"):
        assert forbidden not in first["presets"]


def test_explicit_frozen_validation_threshold_is_used_without_holdout_optimization() -> None:
    context = seed_exact_candidate(frozen_threshold=0.37)

    command = EVAL.get_evaluation_command_center(
        context["candidate_id"],
        context=context,
    )
    assert command["threshold"]["threshold"] == 0.37
    assert command["presets"] == {"current_governed": 0.37}
    assert command["threshold_policy"]["active_source"] == "cross_validation"
    assert command["threshold_policy"]["recommendations_derived_from_final_holdout"] is False


def test_routes_select_only_by_opaque_candidate_context() -> None:
    lineage_parameters = inspect.signature(eval_router._lineage_context).parameters
    assert "candidate_id" in lineage_parameters
    assert "training_job_id" in lineage_parameters
    assert "training_run_id" in lineage_parameters
    for route_handler in (
        eval_router.get_curves,
        eval_router.get_feature_importance,
        eval_router.get_rfe,
    ):
        assert "model" not in inspect.signature(route_handler).parameters
    assert "evaluation_package_id" in inspect.signature(
        eval_router._interpretation_context
    ).parameters
    assert "model_version_id" in inspect.signature(
        eval_router._interpretation_context
    ).parameters


def test_durable_publication_uses_exact_candidate_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    context = seed_exact_candidate()
    completed = complete_evaluation_package(context)
    context["evaluation_package_id"] = completed["evaluation_package_id"]
    saved = EVAL.save_selected_model_as_final(
        context["candidate_id"],
        context=context,
        evaluation_package_id=completed["evaluation_package_id"],
    )
    assert saved["ok"] is True
    exact_candidate_artifact = saved["_fitted_object"]
    interleaved_other_candidate_artifact = CandidateArtifact()
    RESULTS.set_final_model(
        interleaved_other_candidate_artifact,
        {"source_candidate_id": "candidate-interleaved-b"},
    )
    captured: dict = {}

    def fake_create_model_version(*args, **kwargs):
        captured.update(kwargs)
        return {
            "model": {"modelId": "model-eval-1"},
            "modelVersion": {
                "modelVersionId": "model-version-eval-1",
                "projectId": context["project_id"],
                "datasetId": context["dataset_id"],
                "datasetVersionId": context["dataset_version_id"],
                "candidateId": context["candidate_id"],
                "trainingRunId": context["training_run_id"],
                "featureManifestVersion": context["feature_manifest_version"],
                "evaluationPackageId": EVAL.registry_promotion_handoff(
                    context["candidate_id"],
                    context,
                    saved["metadata"],
                    completed["evaluation_package_id"],
                )["evaluation_package_id"],
                "candidateDecisionId": context["candidate_decision_id"],
            },
            "promotion": {
                "status": "finalized",
                "artifactVerified": True,
                "lineageStatus": "verified",
                "checksum": "checksum-eval-1",
            },
        }

    monkeypatch.setattr(eval_router.REGISTRY, "create_model_version", fake_create_model_version)
    published = eval_router._publish_final_version(
        {"userId": "evaluation-test"}, context, saved
    )
    assert published["modelVersion"]["modelVersionId"] == "model-version-eval-1"
    assert published["metadata"]["model_version_id"] == "model-version-eval-1"
    assert captured["candidate_contract"]["candidate_id"] == context["candidate_id"]
    assert captured["algorithm"] == ALGORITHM_ID
    assert captured["training_run_id"] == context["training_run_id"]
    assert captured["training_timestamp"] == captured["candidate_contract"]["created_at"]
    assert captured["fitted_object"] is exact_candidate_artifact
    assert captured["fitted_object"] is not interleaved_other_candidate_artifact
    assert captured["model_name"] == (
        f"ATLAS::{context['dataset_id']}::{context['dataset_version_id']}::{context['target']}"
    )


def test_rfe_analysis_is_independent_of_final_holdout_and_cannot_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = seed_exact_candidate()
    X_train = pd.DataFrame(
        {
            "income": [float(index * 10) for index in range(1, 21)],
            "util": [float((index * 7) % 13) / 13.0 for index in range(1, 21)],
        }
    )
    y_train = pd.Series([index % 2 for index in range(20)], name=context["target"])
    X_test = pd.DataFrame({"income": [5.0, 15.0, 25.0, 35.0], "util": [0.1, 0.2, 0.3, 0.4]})
    y_test = pd.Series([0, 1, 0, 1], name=context["target"])
    DATASTORE.set_splits(X_train, X_test, y_train, y_test)

    first = EVAL.rfe(context["candidate_id"], keep=1, context=context)
    assert first["ok"] is True
    assert first["selection_population"] == "training_internal_validation"
    assert first["holdout_used"] is False

    changed_holdout = pd.DataFrame(
        {"income": [10_000.0, -10_000.0, 50_000.0, -50_000.0], "util": [99.0, -99.0, 50.0, -50.0]}
    )
    changed_y = pd.Series([1, 1, 0, 0], name=context["target"])
    DATASTORE.set_splits(X_train, changed_holdout, y_train, changed_y)
    second = EVAL.rfe(context["candidate_id"], keep=1, context=context)
    assert second["ok"] is True
    assert second["rows"] == first["rows"]
    assert second["curve"] == first["curve"]
    assert second["best_auc"] == first["best_auc"]

    completed = complete_evaluation_package(context)
    publication_called = False

    def forbidden_publication(*args, **kwargs):
        nonlocal publication_called
        publication_called = True
        raise AssertionError("RFE attempted durable publication")

    monkeypatch.setattr(eval_router, "authorize_modeling_scope", lambda *args, **kwargs: context["project_id"])
    monkeypatch.setattr(eval_router, "audit_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(eval_router.REGISTRY, "create_model_version", forbidden_publication)
    response = eval_router.save_rfe_final_model(
        {**context, "evaluation_package_id": completed["evaluation_package_id"], "keep": 1},
        user={"userId": "evaluation-test"},
    )
    body = json.loads(response.body)
    assert response.status_code == 409
    assert "analysis" in body["error"].lower()
    assert body["correlation_id"].startswith("promotion-")
    assert publication_called is False


def test_interpretation_recovers_only_explicit_exact_registered_artifact_after_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = seed_exact_candidate()
    completed = complete_evaluation_package(context)
    evaluation_package_id = completed["evaluation_package_id"]
    durable_evaluation_package = copy.deepcopy(completed["evaluation_package"])
    candidate_contract = copy.deepcopy(
        RESULTS.get_last_summary()["ranked"][0]["candidate_contract"]
    )
    model_version_id = "model-version-restart-1"
    registered_artifact = CandidateArtifact()
    version = {
        "modelVersionId": model_version_id,
        "publicationStatus": "finalized",
        "lineageStatus": "verified",
        "projectId": context["project_id"],
        "datasetId": context["dataset_id"],
        "datasetVersionId": context["dataset_version_id"],
        "candidateId": context["candidate_id"],
        "trainingRunId": context["training_run_id"],
        "featureManifestVersion": context["feature_manifest_version"],
        "validationDesignId": context["validation_design_id"],
        "splitId": context["split_id"],
        "targetName": context["target"],
        "evaluationPackageId": evaluation_package_id,
        "candidateDecisionId": context["candidate_decision_id"],
        "candidateContractHash": candidate_contract["contract_hash"],
        "candidateContract": candidate_contract,
        "evaluationSummary": durable_evaluation_package,
        "modelContract": {
            "modelVersionId": model_version_id,
            "projectId": context["project_id"],
            "trainingDatasetId": context["dataset_id"],
            "trainingDatasetVersionId": context["dataset_version_id"],
            "candidateId": context["candidate_id"],
            "trainingJobId": context["training_job_id"],
            "trainingRunId": context["training_run_id"],
            "featureManifestHash": context["feature_manifest_version"],
            "validationDesignId": context["validation_design_id"],
            "validationDesignVersion": context["validation_design_version"],
            "splitId": context["split_id"],
            "evaluationPackageId": evaluation_package_id,
            "candidateDecisionId": context["candidate_decision_id"],
            "candidateContractHash": candidate_contract["contract_hash"],
            "candidateContract": candidate_contract,
        },
        "lineage": {
            "trainingJobId": context["training_job_id"],
            "validationDesignVersion": context["validation_design_version"],
            "problemType": context["problem_type"],
            "evaluationPackageId": evaluation_package_id,
            "candidateDecisionId": context["candidate_decision_id"],
            "candidateContractHash": candidate_contract["contract_hash"],
            "candidateContract": candidate_contract,
        },
    }
    calls: list[tuple] = []
    monkeypatch.setattr(eval_router, "authorize_modeling_scope", lambda *args, **kwargs: context["project_id"])
    monkeypatch.setattr(
        eval_router.REGISTRY,
        "get_version",
        lambda user, version_id: calls.append(("version", version_id)) or version,
    )
    monkeypatch.setattr(
        eval_router.REGISTRY,
        "load_version_artifact",
        lambda user, version_id, expected_project_id=None: calls.append(
            ("artifact", version_id, expected_project_id)
        ) or registered_artifact,
    )
    RESULTS.clear_model_artifacts()
    RESULTS.evaluation_packages = {}
    RESULTS.holdout_evaluations = {}
    assert RESULTS.get_last_summary() is None
    assert RESULTS.evaluation_packages == {}
    assert RESULTS.get_model_artifacts() == {}
    prepared = eval_router._prepare_interpretation_context(
        {"userId": "evaluation-test"},
        {
            **context,
            "evaluation_package_id": evaluation_package_id,
            "model_version_id": model_version_id,
        },
    )
    response = eval_router.get_model_details(
        context=prepared,
        user={"userId": "evaluation-test"},
    )
    assert response["ok"] is True
    assert response["kind"] == "generic"
    assert response["evaluation_package_id"] == evaluation_package_id
    assert calls == [
        ("version", model_version_id),
        ("artifact", model_version_id, context["project_id"]),
    ]

    missing_version = EVAL.model_details(
        context["candidate_id"],
        {**context, "evaluation_package_id": evaluation_package_id},
    )
    assert missing_version["ok"] is False
    assert "training run is unavailable" in missing_version["error"].lower()

    monkeypatch.setattr(
        eval_router.REGISTRY,
        "get_version",
        lambda user, version_id: {**version, "modelVersionId": "model-version-wrong"},
    )
    with pytest.raises(HTTPException) as wrong_version:
        eval_router._prepare_interpretation_context(
            {"userId": "evaluation-test"},
            {
                **context,
                "evaluation_package_id": evaluation_package_id,
                "model_version_id": model_version_id,
            },
        )
    assert wrong_version.value.status_code == 409


def test_promotion_failure_returns_safe_correlation_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = seed_exact_candidate()
    events: list[dict] = []
    monkeypatch.setattr(eval_router, "authorize_modeling_scope", lambda *args, **kwargs: context["project_id"])

    def capture_audit(action, resource_type, resource_id, outcome, **kwargs):
        events.append(
            {
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                **kwargs,
            }
        )

    monkeypatch.setattr(eval_router, "audit_event", capture_audit)
    response = eval_router.save_selected_final_model(
        {**context, "evaluation_package_id": "evalpkg-does-not-exist"},
        user={"userId": "evaluation-test"},
    )
    body = json.loads(response.body)
    assert response.status_code == 409
    assert body["ok"] is False
    assert body["error"]
    assert body["correlation_id"].startswith("promotion-")
    assert events[-1]["action"] == "model.promotion.failed"
    assert events[-1]["outcome"] == "failure"
    assert events[-1]["metadata"]["correlationId"] == body["correlation_id"]
    assert events[-1]["metadata"]["errorClass"] == "HTTPException"


def test_promotion_success_audits_exact_safe_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = seed_exact_candidate()
    completed = complete_evaluation_package(context)
    request = {**context, "evaluation_package_id": completed["evaluation_package_id"]}
    events: list[dict] = []
    monkeypatch.setattr(eval_router, "authorize_modeling_scope", lambda *args, **kwargs: context["project_id"])
    monkeypatch.setattr(eval_router, "schedule_checkpoint_save", lambda: None)
    monkeypatch.setattr(
        eval_router,
        "audit_event",
        lambda action, resource_type, resource_id, outcome, **kwargs: events.append(
            {
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "outcome": outcome,
                **kwargs,
            }
        ),
    )
    monkeypatch.setattr(
        eval_router,
        "_publish_final_version",
        lambda user, exact_context, result: {
            "ok": True,
            "metadata": result["metadata"],
            "model": {"modelId": "model-audit-1"},
            "modelVersion": {
                "modelVersionId": "model-version-audit-1",
                "previousChampionVersionId": "model-version-previous-1",
            },
            "promotion": {"status": "finalized", "checksum": "checksum-audit-1"},
        },
    )
    response = eval_router.save_selected_final_model(
        request,
        user={"userId": "evaluation-test"},
    )
    assert response["ok"] is True
    assert response["correlation_id"].startswith("promotion-")
    event = events[-1]
    assert event["action"] == "model.promotion.succeeded"
    assert event["outcome"] == "success"
    assert event["metadata"]["candidateId"] == context["candidate_id"]
    assert event["metadata"]["evaluationPackageId"] == completed["evaluation_package_id"]
    assert event["metadata"]["modelVersionId"] == "model-version-audit-1"
    assert event["metadata"]["previousChampionVersionId"] == "model-version-previous-1"
    assert event["metadata"]["checksum"] == "checksum-audit-1"


def test_final_status_resolves_only_the_durable_exact_context(monkeypatch: pytest.MonkeyPatch) -> None:
    context = seed_exact_candidate()
    calls: list[dict] = []

    monkeypatch.setattr(eval_router, "authorize_modeling_scope", lambda *args, **kwargs: context["project_id"])

    def fake_resolve(user, **kwargs):
        calls.append(kwargs)
        return {
            "status": "ready",
            "modelId": "model-eval-1",
            "modelVersionId": "model-version-eval-1",
            "publicationStatus": "finalized",
            "lineageStatus": "verified",
            "artifactVerified": True,
            "checksum": "checksum-eval-1",
            "artifactFormat": "joblib",
            "modelVersion": {
                "modelVersionId": "model-version-eval-1",
                "projectId": context["project_id"],
                "datasetId": context["dataset_id"],
                "datasetVersionId": context["dataset_version_id"],
                "targetName": context["target"],
                "candidateId": context["candidate_id"],
                "trainingRunId": context["training_run_id"],
                "featureManifestVersion": context["feature_manifest_version"],
                "validationDesignId": context["validation_design_id"],
                "splitId": context["split_id"],
                "lineage": {
                    "validationDesignVersion": context["validation_design_version"],
                },
            },
        }

    monkeypatch.setattr(
        eval_router.REGISTRY,
        "resolve_current_version_by_exact_context",
        fake_resolve,
    )
    status = eval_router.get_final_model_status(
        project_id=context["project_id"],
        dataset_id=context["dataset_id"],
        dataset_version_id=context["dataset_version_id"],
        target=context["target"],
        user={"userId": "evaluation-test"},
    )
    assert status["ready"] is True
    metadata = status["metadata"]
    assert metadata["model_version_id"] == "model-version-eval-1"
    assert metadata["candidate_id"] == context["candidate_id"]
    assert metadata["training_run_id"] == context["training_run_id"]
    assert metadata["feature_manifest_version"] == context["feature_manifest_version"]
    assert metadata["validation_design_id"] == context["validation_design_id"]
    assert metadata["split_id"] == context["split_id"]
    assert metadata["promotion_status"] == "finalized"
    assert metadata["designation"] == "champion"
    assert metadata["artifact_verification_status"] == "verified"
    assert calls == [
        {
            "project_id": context["project_id"],
            "dataset_id": context["dataset_id"],
            "dataset_version_id": context["dataset_version_id"],
            "target_name": context["target"],
        }
    ]
    assert "model_version_id" not in inspect.signature(eval_router.get_final_model_status).parameters


def test_export_loads_only_the_exact_registered_version(monkeypatch: pytest.MonkeyPatch) -> None:
    context = seed_exact_candidate()
    calls: list[tuple] = []
    artifact = CandidateArtifact()
    monkeypatch.setattr(eval_router, "authorize_modeling_scope", lambda *args, **kwargs: context["project_id"])
    monkeypatch.setattr(
        eval_router.REGISTRY,
        "load_version_artifact",
        lambda user, version_id, expected_project_id=None: calls.append(
            ("load", version_id, expected_project_id)
        ) or artifact,
    )
    monkeypatch.setattr(
        eval_router.REGISTRY,
        "get_version",
        lambda user, version_id: calls.append(("version", version_id)) or {
            "modelVersionId": version_id,
            "projectId": context["project_id"],
        },
    )
    monkeypatch.setattr(
        EVAL,
        "export_model_bundle",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("volatile export fallback used")),
    )
    response = eval_router.export_model(
        project_id=context["project_id"],
        model_version_id="model-version-eval-1",
        format="json",
        user={"userId": "evaluation-test"},
    )
    payload = json.loads(response.body)
    assert payload["modelVersion"]["modelVersionId"] == "model-version-eval-1"
    assert calls == [
        ("load", "model-version-eval-1", context["project_id"]),
        ("version", "model-version-eval-1"),
    ]


@pytest.mark.parametrize(
    ("field", "wrong_value", "phrase"),
    [
        ("project_id", "project-cross", "project_id"),
        ("dataset_version_id", "version-cross", "dataset_version_id"),
        ("target", "other_target", "target"),
        ("split_id", "split-cross", "split_id"),
        ("feature_manifest_version", "manifest-cross", "feature_manifest_version"),
        ("validation_design_id", "design-cross", "validation_design_id"),
        ("training_job_id", "training-cross", "training_job_id"),
        ("training_run_id", "run-cross", "training_run_id"),
    ],
)
def test_cross_lineage_requests_are_rejected(field: str, wrong_value: str, phrase: str) -> None:
    context = seed_exact_candidate()
    context[field] = wrong_value
    assert_lineage_rejected(EVAL.get_curves(LINEAGE["candidate_id"], context), phrase)


def test_missing_exact_context_is_rejected() -> None:
    context = seed_exact_candidate()
    context.pop("dataset_id")
    assert_lineage_rejected(EVAL.get_curves(LINEAGE["candidate_id"], context), "dataset_id")


def test_algorithm_key_cannot_select_an_opaque_candidate() -> None:
    context = seed_exact_candidate()
    assert_lineage_rejected(EVAL.get_curves(ALGORITHM_ID, context), "candidate_id")


def test_stale_split_is_rejected() -> None:
    context = seed_exact_candidate()
    DATASTORE.meta["split_status"] = "stale"
    assert_lineage_rejected(EVAL.get_curves(LINEAGE["candidate_id"], context), "split is stale")


def test_unsupported_candidate_is_rejected() -> None:
    context = seed_exact_candidate(kind="anomaly", champion_eligible=False)
    assert_lineage_rejected(EVAL.get_curves(LINEAGE["candidate_id"], context), "unsupported")


def test_artifact_cross_version_is_rejected() -> None:
    context = seed_exact_candidate()
    RESULTS.model_artifact_metadata[ALGORITHM_ID]["dataset_version_id"] = "version-cross"
    assert_lineage_rejected(EVAL.get_curves(LINEAGE["candidate_id"], context), "candidate artifact")
