from __future__ import annotations

import json
import os
import tempfile
import time
import uuid
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Isolate this suite's checkpoint writes from the real dev backend's file.
# The checkpoint is a full-snapshot, last-writer-wins file (see
# server/core/session_checkpoint.py): without this, the service calls below
# (feature materialization, evaluation) schedule checkpoint saves that would
# CLOBBER the live backend's .runtime/workflow_checkpoint.json from this
# separate process, silently dropping the backend's resident scopes from disk.
os.environ.setdefault(
    "ATLAS_CHECKPOINT_PATH",
    str(Path(tempfile.gettempdir()) / f"atlas_repair_test_checkpoint_{uuid.uuid4().hex[:8]}.json"),
)

from server.core.dataset_store import DATASTORE
from server.eda.eda_service import eda_service
from server.eda.workspace_service import eda_workspace_service
from server.eda.workspace_types import EDAWorkspaceRequest
import server.eda.workspace_service as eda_workspace_module
from server.evaluation.eval_service import EVAL
from server.preprocessing.feature_profile_service import profile_features
from server.preprocessing.missing_router import MissingApplyRequest, MissingRule, apply_missing_values, missing_summary
from server.preprocessing.outlier_router import OutlierApplyRequest, OutlierSummaryRequest, apply_outlier_treatments, outliers_summary
from server.preprocessing.quality_profile_service import profile_active_dataset
import server.preprocessing.feature_profile_service as feature_profile_module
import server.preprocessing.missing_router as missing_router_module
import server.preprocessing.outlier_router as outlier_router_module
import server.preprocessing.quality_profile_service as quality_profile_module

REPAIR_TEST_PROJECT_ID = "repair-test-project"
REPAIR_TEST_OWNER_USER_ID = "repair-test-owner"


def _skip_modeling_scope_authorization(user, project_id, permission):
    """Stand-in for authorize_modeling_scope (server/core/modeling_scope.py),
    installed for the duration of this script only.

    This script calls outlier_router.py/missing_router.py's handler
    functions directly as plain Python calls (not through FastAPI/HTTP), to
    exercise their business logic and DATASTORE bookkeeping quickly without
    a real session or persisted project. Since Stage 2B
    (ATLAS_MODELING_STATE_ISOLATION_PLAN.md), those handlers open with a
    real SharingService-backed authorize_modeling_scope(...) call, which
    requires a genuine authenticated session and a genuine persisted
    project -- neither of which this direct-call script has ever set up (it
    manipulates DATASTORE directly instead, matching how it already treats
    TRAINING_JOBS/RESULTS). Swapped in the same way this file already
    monkeypatches job_module.train_models below, and restored afterward.

    Stage 3 (RESULTS project-scoping) extended this same authorize_modeling_
    scope gate to trainer_router.py's get_last_train(), which this script
    also calls directly -- the same stand-in is reused there too.
    """
    return project_id
from server.splitting.split_service import split_service
from server.training.training_job_service import TRAINING_JOBS
from server.training.training_job_types import TrainingJobRequest
from server.training.training_preflight_service import training_preflight
from server.training.trainer_router import get_last_train
import server.training.training_job_service as job_module
import server.training.training_preflight_service as training_preflight_module
import server.training.trainer_router as trainer_router_module


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


def canonical_identity() -> dict[str, str]:
    return {
        "project_id": REPAIR_TEST_PROJECT_ID,
        "dataset_id": "ds-repair-test",
        "dataset_version_id": "repair-test-v2",
    }


def resolve_test_identity(
    project_id: str,
    *,
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
    **_kwargs,
) -> dict[str, str]:
    identity = canonical_identity()
    assert str(project_id) == identity["project_id"]
    assert not expected_dataset_id or expected_dataset_id == identity["dataset_id"]
    supplied_version = expected_dataset_version_id or legacy_dataset_version
    assert (
        not supplied_version
        or supplied_version == identity["dataset_version_id"]
    )
    return identity


def validate_test_checkpoint(
    store,
    *,
    owner_user_id: str = "",
    project_id: str = "",
):
    identity = canonical_identity()
    if project_id and project_id != identity["project_id"]:
        return False, "The test project identity changed.", None
    if any(
        str(store.meta.get(key) or "") != value
        for key, value in identity.items()
    ):
        return False, "The test dataset identity changed.", None
    return True, "", identity


def resolve_result_context_identity(
    project_id: str,
    *,
    expected_dataset_id: str = "",
    expected_dataset_version_id: str = "",
    legacy_dataset_version: str = "",
    **_kwargs,
) -> dict[str, str]:
    identity = canonical_identity()
    identity["project_id"] = str(project_id)
    assert not expected_dataset_id or expected_dataset_id == identity["dataset_id"]
    supplied_version = expected_dataset_version_id or legacy_dataset_version
    assert (
        not supplied_version
        or supplied_version == identity["dataset_version_id"]
    )
    return identity


def configure_manifest(frame: pd.DataFrame) -> None:
    DATASTORE.reset_all()
    DATASTORE.set_raw(frame)
    DATASTORE.set_target("target")
    DATASTORE.meta.update(canonical_identity())
    DATASTORE.meta["selected_columns"] = ["amount", "velocity", "amount_velocity"]
    DATASTORE.meta["dataset_version"] = "repair-test-v2"
    DATASTORE.meta["source"] = {"kind": "dataset_library", "datasetId": "ds-repair-test"}
    DATASTORE.meta["feature_manifest"] = {
        **canonical_identity(),
        "manifest_version": "fm-repair-test-v2",
        "manifest_hash": "fm-repair-test-v2",
        "dataset_version": "repair-test-v2",
        "validation_status": "passed",
        "materialization_status": "current",
        "materialized_manifest_hash": "fm-repair-test-v2",
        "confirmation_status": "confirmed",
        "confirmed_manifest_hash": "fm-repair-test-v2",
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
    validation_design = {
        **canonical_identity(),
        "validation_design_id": "validation-design-repair-test-v2",
        "design_version": "validation-design-version-repair-test-v2",
        "feature_manifest_hash": "fm-repair-test-v2",
        "status": "approved",
        "development_dataset": {
            "dataset_id": "ds-repair-test",
            "dataset_version_id": "repair-test-v2",
        },
    }
    DATASTORE.meta["split_record"] = {
        **canonical_identity(),
        "split_id": "split-repair-test-v2",
        "dataset_version": "repair-test-v2",
        "feature_manifest_version": "fm-repair-test-v2",
        "selected_features": ["amount", "velocity", "amount_velocity"],
        "config": config,
        "validation_design": validation_design,
        "completion_gates": {},
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
        dataset_version_id="repair-test-v2",
        dataset_version="repair-test-v2",
        feature_manifest_version="fm-repair-test-v2",
        split_id="split-repair-test-v2",
        validation_design_id="validation-design-repair-test-v2",
        validation_design_version="validation-design-version-repair-test-v2",
        project_id="repair-test-project",
        dataset_id="ds-repair-test",
        non_event_value=0,
        user="repair.tester@atlas.local",
    )


def wait_for_job(job_id: str, timeout: float = 30.0):
    deadline = time.time() + timeout
    observed = set()
    while time.time() < deadline:
        job = TRAINING_JOBS.get(job_id, owner_user_id=REPAIR_TEST_OWNER_USER_ID, project_id=REPAIR_TEST_PROJECT_ID)
        assert job is not None
        observed.add(job["overall_status"])
        for history in job.get("per_model_history", {}).values():
            observed.update(item["state"] for item in history)
        if job["overall_status"] in {"complete", "failed", "cancelled", "interrupted"}:
            return job, observed
        time.sleep(0.05)
    raise AssertionError(f"Training job {job_id} did not reach a terminal state.")


def main() -> None:
    original_outlier_authz = outlier_router_module.authorize_modeling_scope
    original_missing_authz = missing_router_module.authorize_modeling_scope
    original_trainer_authz = trainer_router_module.authorize_modeling_scope
    original_eda_identity = (
        eda_workspace_module.assert_expected_active_identity
    )
    original_outlier_identity = (
        outlier_router_module.assert_expected_active_identity
    )
    original_missing_identity = (
        missing_router_module.assert_expected_active_identity
    )
    original_preflight_identity = (
        training_preflight_module.assert_expected_active_identity
    )
    original_checkpoint_identity = job_module.validate_checkpoint_identity
    original_quality_identity = (
        quality_profile_module.assert_expected_active_identity
    )
    original_feature_profile_identity = (
        feature_profile_module.assert_expected_active_identity
    )
    original_trainer_identity = (
        trainer_router_module.assert_expected_active_identity
    )
    outlier_router_module.authorize_modeling_scope = _skip_modeling_scope_authorization
    missing_router_module.authorize_modeling_scope = _skip_modeling_scope_authorization
    trainer_router_module.authorize_modeling_scope = _skip_modeling_scope_authorization
    outlier_router_module.assert_expected_active_identity = (
        resolve_test_identity
    )
    missing_router_module.assert_expected_active_identity = (
        resolve_test_identity
    )
    training_preflight_module.assert_expected_active_identity = resolve_test_identity
    job_module.validate_checkpoint_identity = validate_test_checkpoint
    quality_profile_module.assert_expected_active_identity = (
        resolve_test_identity
    )
    feature_profile_module.assert_expected_active_identity = (
        resolve_test_identity
    )
    trainer_router_module.assert_expected_active_identity = (
        resolve_result_context_identity
    )
    eda_workspace_module.assert_expected_active_identity = (
        resolve_test_identity
    )
    try:
        frame = build_frame()

        preprocessing_frame = frame.copy()
        preprocessing_frame.loc[0, "amount"] = 10000.0
        preprocessing_frame.loc[0:11, "velocity"] = None
        configure_manifest(preprocessing_frame)
        outlier_profile = outliers_summary(
            OutlierSummaryRequest(project_id=REPAIR_TEST_PROJECT_ID, target="target", event_value=1, problem_type="classification"),
            user={},
        )
        assert outlier_profile["scope"] == "full_dataset"
        assert outlier_profile["row_count"] == len(preprocessing_frame)
        amount_profile = next(row for row in outlier_profile["features"] if row["feature"] == "amount")
        assert amount_profile["methods"]["IQR_1_5"]["outlier_count"] >= 1
        assert amount_profile["signal_metric"] is not None
        assert len(amount_profile["rendered_sample"]) <= 600
        json.dumps(outlier_profile, allow_nan=False)
        outlier_application = apply_outlier_treatments(
            OutlierApplyRequest(
                project_id=REPAIR_TEST_PROJECT_ID,
                target="target",
                event_value=1,
                problem_type="classification",
                global_method="IQR_1_5",
                config={"amount": "USE_GLOBAL", "velocity": "NONE", "amount_velocity": "NONE"},
            ),
            user={},
        )
        assert outlier_application["scope"] == "full_dataset"
        assert outlier_application["application"]["changed_values"] >= 1
        assert DATASTORE.meta["processed_stage"] == "outliers"

        missing_profile = missing_summary(
            project_id=REPAIR_TEST_PROJECT_ID,
            event_value=1,
            problem_type="classification",
            expected_dataset_id="ds-repair-test",
            expected_dataset_version_id="repair-test-v2",
            dataset_id=None,
            dataset_version_id=None,
            dataset_version=None,
            user={},
        )
        assert missing_profile["scope"] == "full_dataset"
        assert missing_profile["rows"] == len(preprocessing_frame)
        assert missing_profile["stats"]["velocity"]["missing"] == 12
        assert missing_profile["source_stage"] == "outlier_treated"
        json.dumps(missing_profile, allow_nan=False)
        missing_application = apply_missing_values(
            MissingApplyRequest(
                project_id=REPAIR_TEST_PROJECT_ID,
                event_value=1,
                problem_type="classification",
                config={"velocity": MissingRule(strategy="Median")},
            ),
            user={},
        )
        assert missing_application["scope"] == "full_dataset"
        assert missing_application["application"]["missing_before"] == 12
        assert missing_application["application"]["missing_after"] == 0
        assert missing_application["application"]["treatments"][0]["feature"] == "velocity"
        assert DATASTORE.meta["processed_stage"] == "missing_values"

        configure_manifest(frame)
        _run_remaining_checks(frame, outlier_profile, missing_profile)
    finally:
        outlier_router_module.authorize_modeling_scope = original_outlier_authz
        missing_router_module.authorize_modeling_scope = original_missing_authz
        trainer_router_module.authorize_modeling_scope = original_trainer_authz
        eda_workspace_module.assert_expected_active_identity = (
            original_eda_identity
        )
        outlier_router_module.assert_expected_active_identity = (
            original_outlier_identity
        )
        missing_router_module.assert_expected_active_identity = (
            original_missing_identity
        )
        training_preflight_module.assert_expected_active_identity = (
            original_preflight_identity
        )
        job_module.validate_checkpoint_identity = original_checkpoint_identity
        quality_profile_module.assert_expected_active_identity = (
            original_quality_identity
        )
        feature_profile_module.assert_expected_active_identity = (
            original_feature_profile_identity
        )
        trainer_router_module.assert_expected_active_identity = (
            original_trainer_identity
        )


def _run_remaining_checks(frame: pd.DataFrame, outlier_profile: dict, missing_profile: dict) -> None:

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
        EDAWorkspaceRequest(project_id=REPAIR_TEST_PROJECT_ID, target="target", event_value=1, problem_type="classification", histogram_bins=10),
    )
    forty_bin_profile = eda_workspace_service.section(
        "predictors",
        EDAWorkspaceRequest(project_id=REPAIR_TEST_PROJECT_ID, target="target", event_value=1, problem_type="classification", histogram_bins=40),
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
        TRAINING_JOBS.create(request(), owner_user_id=REPAIR_TEST_OWNER_USER_ID)
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
    created = TRAINING_JOBS.create(request(), owner_user_id=REPAIR_TEST_OWNER_USER_ID)
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
        user={},
    )
    assert contextual_last["summary"]["project_id"] == "repair-test-project"
    mismatched_last = get_last_train(
        project_id="another-project",
        dataset_version="repair-test-v2",
        target="target",
        problem_type="classification",
        user={},
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

    selected_final = EVAL.save_selected_model_as_final("dtree", context=interpretation_context)
    assert selected_final["ok"] is True, selected_final
    assert selected_final["metadata"]["feature_manifest_version"] == "fm-repair-test-v2"
    assert selected_final["metadata"]["split_id"] == "split-repair-test-v2"
    assert selected_final["metadata"]["training_job_id"] == job["job_id"]

    rfe = EVAL.rfe("logreg", keep=2, context=interpretation_context)
    assert rfe["ok"] is True, rfe
    assert len(rfe["rows"]) == 3
    assert rfe["selected_count"] == 2
    assert rfe["curve"]
    # Stage B.5 regression: save_rfe_model must reject a save whose context (dataset_version,
    # target, problem_type, project_id) does not match the trained artifact's own recorded
    # metadata -- this is the backend half of the guardrail that a stale frontend snapshot of
    # dataset_version/target (fixed in Step09_Interpretation.tsx's interpretationContextQuery)
    # must not be able to bypass. A save that slips a mismatched context through here would
    # silently corrupt final-model identity; Scoring's own readiness check depends on this
    # metadata being trustworthy.
    mismatched_save = EVAL.save_rfe_model(
        "dtree", keep=2,
        context={**interpretation_context, "dataset_version": "wrong-version"},
    )
    assert mismatched_save["ok"] is False, mismatched_save
    assert "dataset version" in mismatched_save["error"].lower()

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

    # P0 lifecycle regression: an upstream feature-contract change must make
    # an otherwise resident final artifact unavailable. It must not silently
    # remain scoreable merely because the in-memory fitted object still exists.
    DATASTORE.meta["feature_manifest"]["manifest_version"] = "fm-repair-test-stale"
    stale_status = EVAL.final_model_status()
    assert stale_status["artifact_present"] is True
    assert stale_status["ready"] is False
    assert stale_status["stale"] is True
    assert "feature manifest" in stale_status["blocker"].lower()
    stale_scoring = EVAL.score_development_split(dataset_type="train", model_name="final")
    assert stale_scoring["ok"] is False
    assert stale_scoring["stale_model"] is True
    assert "feature manifest" in stale_scoring["error"].lower()
    DATASTORE.meta["feature_manifest"]["manifest_version"] = "fm-repair-test-v2"
    assert EVAL.final_model_status()["ready"] is True

    diagnostic_created = TRAINING_JOBS.create(request(["gnb", "iso"]), owner_user_id=REPAIR_TEST_OWNER_USER_ID)
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
        partial_created = TRAINING_JOBS.create(request(), owner_user_id=REPAIR_TEST_OWNER_USER_ID)
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
        cancel_created = TRAINING_JOBS.create(request(["logreg", "dtree"]), owner_user_id=REPAIR_TEST_OWNER_USER_ID)
        cancelled = TRAINING_JOBS.cancel(cancel_created["job_id"], owner_user_id=REPAIR_TEST_OWNER_USER_ID, project_id=REPAIR_TEST_PROJECT_ID)
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
