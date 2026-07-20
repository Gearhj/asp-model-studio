from __future__ import annotations

import json
import time
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.dataset_store import DATASTORE
from server.eda.eda_service import eda_service
from server.eda.workspace_service import eda_workspace_service
from server.eda.workspace_types import EDAWorkspaceRequest
from server.evaluation.eval_service import EVAL
from server.preprocessing.feature_profile_service import profile_features
from server.preprocessing.missing_router import MissingApplyRequest, MissingRule, apply_missing_values, missing_summary
from server.preprocessing.outlier_router import OutlierApplyRequest, OutlierSummaryRequest, apply_outlier_treatments, outliers_summary
from server.preprocessing.quality_profile_service import profile_active_dataset
from server.splitting.split_service import split_service
from server.training.training_job_service import TRAINING_JOBS
from server.training.training_job_types import TrainingJobRequest
from server.training.training_preflight_service import training_preflight
from server.training.trainer_router import get_last_train
import server.training.training_job_service as job_module


def build_frame(rows: int = 360) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "account_id": [f"account-{index // 2}" for index in range(rows)],
            "amount": [float(index % 37) for index in range(rows)],
            "velocity": [float((index * 7) % 19) for index in range(rows)],
            "amount_velocity": [float(index % 37) * float((index * 7) % 19) for index in range(rows)],
            "numeric_not_a_date": [100 + index for index in range(rows)],
            "target": [1 if index % 9 == 0 else 0 for index in range(rows)],
            "split_indicator": ["development" if index < rows * 0.8 else "holdout" for index in range(rows)],
        }
    )


def configure_manifest(frame: pd.DataFrame) -> None:
    DATASTORE.reset_all()
    DATASTORE.set_raw(frame)
    DATASTORE.set_target("target")
    DATASTORE.meta["selected_columns"] = ["amount", "velocity", "amount_velocity"]
    DATASTORE.meta["dataset_version"] = "repair-test-v2"
    DATASTORE.meta["source"] = {"kind": "dataset_library", "datasetId": "ds-repair-test"}
    DATASTORE.meta["feature_manifest"] = {
        "manifest_version": "fm-repair-test-v2",
        "dataset_version": "repair-test-v2",
        "features": [
            {"feature_name": "amount", "origin": "original", "selected": True, "eligibility_status": "eligible"},
            {"feature_name": "velocity", "origin": "original", "selected": True, "eligibility_status": "eligible"},
            {"feature_name": "amount_velocity", "origin": "interaction", "selected": True, "eligibility_status": "eligible", "materialization_status": "materialized"},
        ],
        "pipeline_steps": [],
        "split_status": "not_created",
    }
    DATASTORE.meta["split_status"] = "not_created"


def create_governed_split(frame: pd.DataFrame) -> None:
    config = {
        "split_strategy": "holdout",
        "test_size": 0.2,
        "random_seed": 42,
        "stratify": True,
        "balance_method": "none",
        "minority_share": 0.5,
        "problem_type": "classification",
        "event_value": 1,
    }
    result = split_service.make_dev_split(frame, "target", ["amount", "velocity", "amount_velocity"], config)
    DATASTORE.set_splits(result.X_train, result.X_test, result.y_train, result.y_test)
    DATASTORE.meta["split_status"] = "current"
    DATASTORE.meta["split_record"] = {
        "split_id": "split-repair-test-v2",
        "dataset_version": "repair-test-v2",
        "feature_manifest_version": "fm-repair-test-v2",
        "selected_features": ["amount", "velocity", "amount_velocity"],
        "config": config,
    }


def request(models: list[str] | None = None) -> TrainingJobRequest:
    return TrainingJobRequest(
        models=models or ["logreg", "dtree"],
        k_folds=3,
        max_parallel=2,
        calibrate=True,
        target="target",
        event_value=1,
        problem_type="classification",
        dataset_version="repair-test-v2",
        feature_manifest_version="fm-repair-test-v2",
        split_id="split-repair-test-v2",
        project_id="repair-test-project",
        dataset_id="ds-repair-test",
        non_event_value=0,
        user="repair.tester@atlas.local",
    )


def wait_for_job(job_id: str, timeout: float = 30.0):
    deadline = time.time() + timeout
    observed = set()
    while time.time() < deadline:
        job = TRAINING_JOBS.get(job_id)
        assert job is not None
        observed.add(job["overall_status"])
        for history in job.get("per_model_history", {}).values():
            observed.update(item["state"] for item in history)
        if job["overall_status"] in {"complete", "failed", "cancelled", "interrupted"}:
            return job, observed
        time.sleep(0.05)
    raise AssertionError(f"Training job {job_id} did not reach a terminal state.")


def main() -> None:
    frame = build_frame()

    preprocessing_frame = frame.copy()
    preprocessing_frame.loc[0, "amount"] = 10000.0
    preprocessing_frame.loc[0:11, "velocity"] = None
    configure_manifest(preprocessing_frame)
    outlier_profile = outliers_summary(OutlierSummaryRequest(target="target", event_value=1, problem_type="classification"))
    assert outlier_profile["scope"] == "full_dataset"
    assert outlier_profile["row_count"] == len(preprocessing_frame)
    amount_profile = next(row for row in outlier_profile["features"] if row["feature"] == "amount")
    assert amount_profile["methods"]["IQR_1_5"]["outlier_count"] >= 1
    assert amount_profile["signal_metric"] is not None
    assert len(amount_profile["rendered_sample"]) <= 600
    json.dumps(outlier_profile, allow_nan=False)
    outlier_application = apply_outlier_treatments(OutlierApplyRequest(
        target="target",
        event_value=1,
        problem_type="classification",
        global_method="IQR_1_5",
        config={"amount": "USE_GLOBAL", "velocity": "NONE", "amount_velocity": "NONE"},
    ))
    assert outlier_application["scope"] == "full_dataset"
    assert outlier_application["application"]["changed_values"] >= 1
    assert DATASTORE.meta["processed_stage"] == "outliers"

    missing_profile = missing_summary(event_value=1, problem_type="classification")
    assert missing_profile["scope"] == "full_dataset"
    assert missing_profile["rows"] == len(preprocessing_frame)
    assert missing_profile["stats"]["velocity"]["missing"] == 12
    assert missing_profile["source_stage"] == "outlier_treated"
    json.dumps(missing_profile, allow_nan=False)
    missing_application = apply_missing_values(MissingApplyRequest(
        event_value=1,
        problem_type="classification",
        config={"velocity": MissingRule(strategy="Median")},
    ))
    assert missing_application["scope"] == "full_dataset"
    assert missing_application["application"]["missing_before"] == 12
    assert missing_application["application"]["missing_after"] == 0
    assert missing_application["application"]["treatments"][0]["feature"] == "velocity"
    assert DATASTORE.meta["processed_stage"] == "missing_values"

    configure_manifest(frame)

    quality = profile_active_dataset("target", 1)
    assert quality["profileScope"] == "full_dataset"
    assert quality["profiledRowCount"] == len(frame)
    assert quality["dateRanges"] == [], "Plain numeric columns must never be parsed as dates."
    classification = profile_features("target", 1, "classification")
    rows = {row["predictor"]: row for row in classification["features"]}
    assert rows["amount"]["iv"] is not None
    assert rows["target"]["eligibilityStatus"] == "excluded"
    assert rows["split_indicator"]["eligibilityStatus"] == "excluded"

    ten_bin_profile = eda_workspace_service.section(
        "predictors",
        EDAWorkspaceRequest(target="target", event_value=1, problem_type="classification", histogram_bins=10),
    )
    forty_bin_profile = eda_workspace_service.section(
        "predictors",
        EDAWorkspaceRequest(target="target", event_value=1, problem_type="classification", histogram_bins=40),
    )
    ten_bin_amount = next(row for row in ten_bin_profile["numeric"] if row["feature"] == "amount")
    forty_bin_amount = next(row for row in forty_bin_profile["numeric"] if row["feature"] == "amount")
    assert ten_bin_profile["requested_histogram_bins"] == 10
    assert forty_bin_profile["requested_histogram_bins"] == 40
    assert ten_bin_amount["histogram_bin_count"] == 10
    assert forty_bin_amount["histogram_bin_count"] == 40
    assert ten_bin_amount["histogram"] != forty_bin_amount["histogram"]
    histogram_frame = frame.copy()
    histogram_frame.loc[0, "amount"] = float("inf")
    dedicated_histogram = eda_service.histogram(histogram_frame, "amount", bins=30)
    assert dedicated_histogram["ok"] is True
    assert dedicated_histogram["returned_bins"] == 30
    assert len(dedicated_histogram["edges"]) == 31
    assert dedicated_histogram["row_count"] == len(frame) - 1

    missing_split = training_preflight(request())
    assert missing_split["ready"] is False
    assert any("validation split" in error.lower() for error in missing_split["blocking_errors"])
    try:
        TRAINING_JOBS.create(request())
        raise AssertionError("Job creation must fail when the explicit split is missing.")
    except ValueError as exc:
        assert "preflight blocked" in str(exc).lower()

    create_governed_split(frame)
    ready = training_preflight(request())
    assert ready["ready"] is True, ready
    assert ready["dataset_id"] == "ds-repair-test"
    assert ready["non_event_value"] == 0
    assert ready["duration_ms"] >= 0
    assert ready["engineered_features"] == ["amount_velocity"]
    assert ready["selected_features"] == ["amount", "velocity", "amount_velocity"]
    assert ready["split_id"] == "split-repair-test-v2"

    started = time.perf_counter()
    created = TRAINING_JOBS.create(request())
    assert time.perf_counter() - started < 2.0, "Job creation must return before model fitting finishes."
    assert created["status"] == "queued"
    assert created["creation_duration_ms"] >= 0
    job, transitions = wait_for_job(created["job_id"])
    assert job["overall_status"] == "complete", job
    assert job["completed_count"] == 2
    assert job["trained_feature_names"] == ["amount", "velocity", "amount_velocity"]
    assert job["summary"]["trained_feature_names"] == ["amount", "velocity", "amount_velocity"]
    assert job["summary"]["feature_manifest_version"] == "fm-repair-test-v2"
    assert job["summary"]["split_id"] == "split-repair-test-v2"
    assert job["summary"]["dataset_id"] == "ds-repair-test"
    assert job["summary"]["non_event_value"] == 0
    assert job["summary"]["contract"]["user"] == "repair.tester@atlas.local"
    assert job["max_parallel_honored"] <= 2
    assert {"queued", "preparing", "running", "complete"}.issubset(transitions)
    assert job["partial_results"]
    assert job["partial_results"][0]["candidate_status"].startswith("Candidate")

    contextual_last = get_last_train(
        project_id="repair-test-project",
        dataset_version="repair-test-v2",
        target="target",
        problem_type="classification",
    )
    assert contextual_last["summary"]["project_id"] == "repair-test-project"
    mismatched_last = get_last_train(
        project_id="another-project",
        dataset_version="repair-test-v2",
        target="target",
        problem_type="classification",
    )
    assert mismatched_last["summary"] is None
    assert "current project" in mismatched_last["context_error"].lower()

    interpretation_context = {
        "project_id": "repair-test-project",
        "dataset_version": "repair-test-v2",
        "target": "target",
        "problem_type": "classification",
    }
    importance = EVAL.feature_importance("logreg", interpretation_context)
    assert importance["ok"] is True, importance
    assert importance["rows"], importance
    assert {row["feature"] for row in importance["rows"]}.issubset({"amount", "velocity", "amount_velocity"})
    assert importance["method"] != "unavailable"

    mismatched_importance = EVAL.feature_importance(
        "logreg",
        {**interpretation_context, "dataset_version": "wrong-version"},
    )
    assert mismatched_importance["ok"] is False
    assert "dataset version" in mismatched_importance["error"].lower()

    pdp = EVAL.pdp("logreg", "amount", interpretation_context)
    sensitivity = EVAL.sensitivity("logreg", "amount", interpretation_context)
    shap = EVAL.shap_summary("logreg", interpretation_context)
    assert pdp["ok"] is True and len(pdp["rows"]) >= 5, pdp
    assert sensitivity["ok"] is True and len(sensitivity["rows"]) == 5, sensitivity
    assert shap["ok"] is True and shap["rows"], shap

    rfe = EVAL.rfe("logreg", keep=2, context=interpretation_context)
    assert rfe["ok"] is True, rfe
    assert len(rfe["rows"]) == 3
    assert rfe["selected_count"] == 2
    assert rfe["curve"]
    saved_final = EVAL.save_rfe_model("dtree", keep=2, context=interpretation_context)
    assert saved_final["ok"] is True, saved_final
    assert saved_final["metadata"]["source_model"] == "dtree"
    assert saved_final["metadata"]["source_estimator_class"] == "DecisionTreeClassifier"
    assert "Decision Tree" in saved_final["metadata"]["name"]
    assert saved_final["metadata"]["project_id"] == "repair-test-project"
    assert saved_final["metadata"]["dataset_version"] == "repair-test-v2"
    final_status = EVAL.final_model_status()
    assert final_status["ready"] is True
    assert final_status["metadata"]["feature_count"] == 2
    train_scoring = EVAL.score_development_split(dataset_type="train", model_name="final")
    assert train_scoring["ok"] is True, train_scoring
    assert train_scoring["rows"] == len(DATASTORE.X_train)
    assert train_scoring["model"]["source_model"] == "dtree"
    assert train_scoring["scoring_diagnostics"]["model_feature_count"] == 2
    assert train_scoring["scoring_diagnostics"]["matched_feature_count"] == 2
    assert train_scoring["scoring_diagnostics"]["constant_prediction"] is False

    diagnostic_created = TRAINING_JOBS.create(request(["gnb", "iso"]))
    diagnostic_job, _ = wait_for_job(diagnostic_created["job_id"])
    assert diagnostic_job["overall_status"] == "complete", diagnostic_job
    diagnostic_results = {row["key"]: row for row in diagnostic_job["partial_results"]}
    assert diagnostic_results["gnb"]["champion_eligible"] is True
    assert diagnostic_results["iso"]["kind"] == "anomaly"
    assert diagnostic_results["iso"]["champion_eligible"] is False
    assert diagnostic_results["iso"]["candidate_champion"] is False
    assert "fit without the target" in diagnostic_results["iso"]["target_usage"]

    original_train_models = job_module.train_models

    def fail_one_model(*args, **kwargs):
        requested = kwargs.get("requested_models") or []
        if requested == ["dtree"]:
            return {"ok": False, "error": "intentional isolated fit failure", "summary": {"problem_type": "classification", "ranked": [], "raw": {}, "failed": [{"key": "dtree", "name": "Decision Tree", "error": "intentional isolated fit failure"}]}}
        return original_train_models(*args, **kwargs)

    job_module.train_models = fail_one_model
    try:
        partial_created = TRAINING_JOBS.create(request())
        partial_job, _ = wait_for_job(partial_created["job_id"])
        assert partial_job["overall_status"] == "complete"
        assert partial_job["completed_count"] == 1
        assert len(partial_job["failed_models"]) == 1
        assert partial_job["failed_models"][0]["key"] == "dtree"
        assert partial_job["partial_results"][0]["key"] == "logreg"
        assert "Decision Tree failed" in partial_job["failed_models"][0]["error"]
    finally:
        job_module.train_models = original_train_models

    def slow_model(*args, **kwargs):
        time.sleep(0.15)
        return original_train_models(*args, **kwargs)

    job_module.train_models = slow_model
    try:
        cancel_created = TRAINING_JOBS.create(request(["logreg", "dtree"]))
        cancelled = TRAINING_JOBS.cancel(cancel_created["job_id"])
        assert cancelled and cancelled["cancellation_requested"] is True
        cancelled_job, _ = wait_for_job(cancel_created["job_id"])
        assert cancelled_job["overall_status"] == "cancelled"
    finally:
        job_module.train_models = original_train_models

    DATASTORE.y_test = pd.Series([0] * len(DATASTORE.y_test), name="target")
    one_class = training_preflight(request())
    assert one_class["ready"] is False
    assert any("holdout target" in error.lower() for error in one_class["blocking_errors"])

    print({
        "quality_rows": quality["profiledRowCount"],
        "outlier_scope_rows": outlier_profile["row_count"],
        "missing_scope_rows": missing_profile["rows"],
        "preflight_ready": ready["ready"],
        "job_status": job["overall_status"],
        "trained_features": job["trained_feature_names"],
        "histogram_bins": [ten_bin_amount["histogram_bin_count"], forty_bin_amount["histogram_bin_count"]],
        "importance_rows": len(importance["rows"]),
        "pdp_rows": len(pdp["rows"]),
        "rfe_rows": len(rfe["rows"]),
        "final_model_ready": final_status["ready"],
        "scored_train_rows": train_scoring["rows"],
        "targetless_diagnostic_not_champion": True,
        "partial_failure_isolated": True,
        "cancel_status": cancelled_job["overall_status"],
    })


if __name__ == "__main__":
    main()
