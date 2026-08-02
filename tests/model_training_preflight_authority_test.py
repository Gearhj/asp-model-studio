from __future__ import annotations

from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from server.training import training_job_service as job_module
from server.training import training_preflight_service as preflight_module
from server.training.training_job_service import TrainingJobService
from server.training.training_job_types import (
    TrainingJobRequest,
    TrainingPortfolioRequest,
)


IDENTITY = {
    "project_id": "project-preflight-test",
    "dataset_id": "dataset-preflight-test",
    "dataset_version_id": "version-preflight-test",
}


class DummyClassifier:
    pass


class DummyAnomaly:
    pass


class IsolatedStore:
    def __init__(self) -> None:
        self.state_lock = RLock()
        self.data_revision = 11
        self.target = "bad_flag"
        self.X_train = pd.DataFrame(
            {
                "feature_a": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
                "feature_b": [7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0, 0.0],
            }
        )
        self.y_train = pd.Series(
            [0, 1, 0, 1, 0, 1, 0, 1], name="bad_flag"
        )
        self.meta = self._meta()

    @property
    def X_test(self):  # pragma: no cover - accessed only on regression
        raise AssertionError("Preflight must not open the final holdout.")

    @property
    def y_test(self):  # pragma: no cover - accessed only on regression
        raise AssertionError("Preflight must not open the final holdout.")

    def _meta(self):
        validation_design = {
            **IDENTITY,
            "validation_design_id": "validation-design-1",
            "design_version": "validation-design-version-1",
            "feature_manifest_hash": "feature-manifest-hash-1",
            "status": "approved",
            "development_dataset": {
                "dataset_id": IDENTITY["dataset_id"],
                "dataset_version_id": IDENTITY["dataset_version_id"],
            },
        }
        return {
            **IDENTITY,
            "split_status": "current",
            "feature_manifest": {
                **IDENTITY,
                "manifest_id": "feature-manifest-1",
                "manifest_hash": "feature-manifest-hash-1",
                "features": [
                    {
                        "feature_name": "feature_a",
                        "selected": True,
                        "eligibility_status": "eligible",
                        "origin": "original",
                    },
                    {
                        "feature_name": "feature_b",
                        "selected": True,
                        "eligibility_status": "eligible",
                        "origin": "original",
                    },
                ],
                "pipeline_steps": [],
            },
            "split_record": {
                **IDENTITY,
                "split_id": "split-1",
                "feature_manifest_version": "feature-manifest-hash-1",
                "training_population_id": "development-population-1",
                "selection_partition_id": "development-population-1",
                "holdout_population_id": "final-holdout-1",
                "final_holdout_partition_id": "final-holdout-1",
                "fold_definition_id": "fold-definition-1",
                "final_holdout_status": "sealed",
                "holdout_isolation_status": "verified",
                "validation_design": validation_design,
                "cv_design": {
                    "method": "stratified_kfold",
                    "fold_count": 2,
                },
                "cv_execution_splits": [
                    {
                        "train_positions": [0, 1, 2, 3],
                        "validation_positions": [4, 5, 6, 7],
                    },
                    {
                        "train_positions": [4, 5, 6, 7],
                        "validation_positions": [0, 1, 2, 3],
                    },
                ],
                "completion_gates": {},
                "balancing_policy": {
                    "selection_resampling_status": "not_applied"
                },
                # Only a split-time count is exposed. No holdout frame or
                # target array is available to this test store.
                "distributions": {"holdout_untouched": {"rows": 2}},
                "n_test": 2,
            },
        }


class IsolatedDataStoreProxy:
    def __init__(self, store: IsolatedStore) -> None:
        self.store = store

    def current(self):
        return self.store

    @property
    def meta(self):
        return self.store.meta

    @property
    def target(self):
        return self.store.target


def request(**overrides) -> TrainingJobRequest:
    values = {
        **IDENTITY,
        "models": ["logreg"],
        "k_folds": 2,
        "max_parallel": 1,
        "target": "bad_flag",
        "problem_type": "classification",
        "event_value": 1,
        "non_event_value": 0,
        "feature_manifest_version": "feature-manifest-hash-1",
        "split_id": "split-1",
        "validation_design_id": "validation-design-1",
        "validation_design_version": "validation-design-version-1",
        "primary_metric": "roc_auc",
    }
    values.update(overrides)
    return TrainingJobRequest(**values)


def identity_resolver(*_args, **_kwargs):
    return dict(IDENTITY)


def persistence_service():
    return SimpleNamespace(
        holdout_governance=SimpleNamespace(
            get_holdout_exposure_for_partition=lambda **_kwargs: None
        )
    )


def model_catalog():
    return {
        "logreg": {
            "label": "Logistic Regression",
            "task": "classification",
            "factory": DummyClassifier,
        },
        "iforest": {
            "label": "Isolation Forest",
            "task": "classification",
            "kind": "anomaly",
            "champion_eligible": False,
            "factory": DummyAnomaly,
        },
    }


def test_authoritative_preflight_is_consistent_and_never_opens_holdout() -> None:
    store = IsolatedStore()
    with (
        patch.object(
            preflight_module, "DATASTORE", IsolatedDataStoreProxy(store)
        ),
        patch.object(
            preflight_module,
            "assert_expected_active_identity",
            side_effect=identity_resolver,
        ),
        patch.object(
            preflight_module,
            "get_persistence_service",
            side_effect=persistence_service,
        ),
        patch.object(preflight_module, "MODEL_CATALOG", model_catalog()),
    ):
        result = preflight_module.training_preflight(request())

    assert result["ready"] is True
    assert result["readiness_status"] == "ready"
    assert result["backend_status"] == "ready"
    assert all(check["passed"] for check in result["checks"])
    assert result["preflight_id"].startswith("training-preflight-")
    assert len(result["state_hash"]) == 64
    assert result["project_id"] == IDENTITY["project_id"]
    assert result["dataset_id"] == IDENTITY["dataset_id"]
    assert result["dataset_version_id"] == IDENTITY["dataset_version_id"]
    assert result["feature_manifest_id"] == "feature-manifest-1"
    assert result["validation_design_id"] == "validation-design-1"
    assert result["split_id"] == "split-1"
    assert result["selected_algorithm_ids"] == ["logreg"]
    assert result["selected_algorithm_versions"]["logreg"]
    assert result["estimated_fits"] == 2
    assert result["final_holdout_sealed"] is True
    assert result["final_holdout_access"] == "contract_metadata_only"
    assert result["selection_evidence_source"] == (
        "development_population_cross_validation"
    )


def test_calibration_fit_count_includes_supported_algorithms_only() -> None:
    store = IsolatedStore()
    with (
        patch.object(
            preflight_module, "DATASTORE", IsolatedDataStoreProxy(store)
        ),
        patch.object(
            preflight_module,
            "assert_expected_active_identity",
            side_effect=identity_resolver,
        ),
        patch.object(
            preflight_module,
            "get_persistence_service",
            side_effect=persistence_service,
        ),
        patch.object(preflight_module, "MODEL_CATALOG", model_catalog()),
    ):
        result = preflight_module.training_preflight(
            request(models=["logreg", "iforest"], calibrate=True)
        )

    assert result["ready"] is False
    assert result["base_fit_count"] == 4
    assert result["calibration_fit_count"] == 2
    assert result["calibration_supported_algorithm_ids"] == ["logreg"]
    assert result["estimated_fits"] == 6


def test_anomaly_algorithm_is_explicitly_diagnostic_only() -> None:
    store = IsolatedStore()
    with (
        patch.object(
            preflight_module, "DATASTORE", IsolatedDataStoreProxy(store)
        ),
        patch.object(
            preflight_module,
            "assert_expected_active_identity",
            side_effect=identity_resolver,
        ),
        patch.object(
            preflight_module,
            "get_persistence_service",
            side_effect=persistence_service,
        ),
        patch.object(preflight_module, "MODEL_CATALOG", model_catalog()),
    ):
        result = preflight_module.training_preflight(
            request(models=["iforest"])
        )

    details = result["selected_algorithm_details"]["iforest"]
    assert details["candidate_role"] == "diagnostic_only"
    assert details["champion_eligible"] is False


def test_portfolio_change_invalidates_only_algorithm_checks() -> None:
    store = IsolatedStore()
    proxy = IsolatedDataStoreProxy(store)
    service = TrainingJobService()
    first = {
        **IDENTITY,
        "preflight_id": "preflight-one",
        "state_hash": "state-one",
        "feature_manifest_id": "feature-manifest-1",
        "feature_manifest_version": "feature-manifest-hash-1",
        "validation_design_id": "validation-design-1",
        "validation_design_version": "validation-design-version-1",
        "split_id": "split-1",
        "canonical_data_revision": 11,
        "selected_algorithm_ids": ["logreg"],
    }
    second = {
        **deepcopy(first),
        "preflight_id": "preflight-two",
        "state_hash": "state-two",
        "selected_algorithm_ids": ["logreg", "iforest"],
    }
    with (
        patch.object(job_module, "DATASTORE", proxy),
        patch.object(job_module, "schedule_checkpoint_save"),
        patch.object(
            job_module,
            "training_preflight",
            side_effect=[deepcopy(first), deepcopy(second)],
        ),
    ):
        service.preflight(request())
        current = service.preflight(request(models=["logreg", "iforest"]))

    assert current["invalidated_preflight_id"] == "preflight-one"
    assert current["invalidation_scope"] == "algorithm_dependent_checks"


def test_feature_manifest_change_invalidates_complete_preflight() -> None:
    store = IsolatedStore()
    proxy = IsolatedDataStoreProxy(store)
    service = TrainingJobService()
    first = {
        **IDENTITY,
        "preflight_id": "preflight-one",
        "state_hash": "state-one",
        "feature_manifest_id": "feature-manifest-1",
        "feature_manifest_version": "feature-manifest-hash-1",
        "validation_design_id": "validation-design-1",
        "validation_design_version": "validation-design-version-1",
        "split_id": "split-1",
        "canonical_data_revision": 11,
        "selected_algorithm_ids": ["logreg"],
    }
    second = {
        **deepcopy(first),
        "preflight_id": "preflight-two",
        "state_hash": "state-two",
        "feature_manifest_id": "feature-manifest-2",
        "feature_manifest_version": "feature-manifest-hash-2",
    }
    with (
        patch.object(job_module, "DATASTORE", proxy),
        patch.object(job_module, "schedule_checkpoint_save"),
        patch.object(
            job_module,
            "training_preflight",
            side_effect=[deepcopy(first), deepcopy(second)],
        ),
    ):
        service.preflight(request())
        current = service.preflight(request())

    assert current["invalidation_scope"] == "complete_preflight"


def test_portfolio_persistence_is_exact_revisioned_and_idempotent() -> None:
    store = IsolatedStore()
    proxy = IsolatedDataStoreProxy(store)
    service = TrainingJobService()
    first_request = TrainingPortfolioRequest(
        **IDENTITY,
        selected_algorithm_ids=["logreg"],
        candidate_strategy="custom_portfolio",
    )
    second_request = TrainingPortfolioRequest(
        **IDENTITY,
        selected_algorithm_ids=["logreg", "iforest"],
        candidate_strategy="custom_portfolio",
        expected_selection_revision=1,
    )
    store.meta["training_preflight"] = {
        **IDENTITY,
        "selected_algorithm_ids": ["logreg"],
        "stale": False,
    }
    with (
        patch.object(job_module, "DATASTORE", proxy),
        patch.object(
            job_module,
            "assert_expected_active_identity",
            side_effect=identity_resolver,
        ),
        patch.object(job_module, "MODEL_CATALOG", model_catalog()),
        patch.object(job_module, "schedule_checkpoint_save"),
    ):
        first = service.save_portfolio(first_request, persisted_by="user-1")
        replay = service.save_portfolio(
            first_request, persisted_by="user-1"
        )
        second = service.save_portfolio(second_request, persisted_by="user-1")
        recovered = service.get_portfolio(**IDENTITY)

    assert first["selection_revision"] == 1
    assert replay["selection_revision"] == 1
    assert second["selection_revision"] == 2
    assert recovered["selected_algorithm_ids"] == ["logreg", "iforest"]
    assert store.meta["training_preflight"]["stale"] is True
    assert store.meta["training_preflight"]["invalidation_scope"] == (
        "algorithm_dependent_checks"
    )


class NoStartThread:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def start(self):
        return None


def ready_preflight() -> dict:
    return {
        "ok": True,
        "ready": True,
        "blocking_errors": [],
        **IDENTITY,
        "preflight_id": "training-preflight-idempotent",
        "state_hash": "a" * 64,
        "dataset_version": IDENTITY["dataset_version_id"],
        "feature_manifest_version": "feature-manifest-hash-1",
        "selected_original_features": ["feature_a", "feature_b"],
        "engineered_features": [],
        "split_id": "split-1",
        "training_population_id": "development-population-1",
        "selection_partition_id": "development-population-1",
        "holdout_population_id": "final-holdout-1",
        "final_holdout_partition_id": "final-holdout-1",
        "fold_definition_id": "fold-definition-1",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
        "selection_resampling_status": "not_applied",
        "validation_design_id": "validation-design-1",
        "validation_design_version": "validation-design-version-1",
        "validation_design": {},
        "cv_design": {"method": "stratified_kfold", "fold_count": 2},
        "fold_architecture": {},
        "evaluation_population_role": "final_holdout_evaluation_only",
        "test_reference": None,
        "oot_reference": None,
        "problem_type": "classification",
        "target": "bad_flag",
        "event_value": 1,
        "non_event_value": 0,
        "calibration_compatibility": {"logreg": {"compatible": True}},
        "cross_validation_compatibility": {"effective_folds": 2},
        "recommended_parallelism": 1,
        "estimated_fits": 2,
        "large_run": {"required": False},
    }


def test_job_creation_is_idempotent_and_returns_active_identity() -> None:
    store = IsolatedStore()
    proxy = IsolatedDataStoreProxy(store)
    service = TrainingJobService()
    fake_results = SimpleNamespace(current=lambda: SimpleNamespace())
    job_request = request(idempotency_key="one-user-action")
    service.preflight = lambda _request: deepcopy(ready_preflight())

    with (
        patch.object(job_module, "DATASTORE", proxy),
        patch.object(job_module, "RESULTS", fake_results),
        patch.object(
            job_module,
            "assert_expected_active_identity",
            side_effect=identity_resolver,
        ),
        patch.object(job_module, "MODEL_CATALOG", model_catalog()),
        patch.object(
            job_module.TRAINER,
            "_get_training_partition",
            return_value=(store.X_train.copy(), store.y_train.copy(), []),
        ),
        patch.object(job_module, "Thread", NoStartThread),
        patch.object(job_module, "schedule_checkpoint_save"),
        patch.object(service, "_scope_matches_job", return_value=(True, "")),
    ):
        first = service.create(job_request, owner_user_id="user-1")
        second = service.create(job_request, owner_user_id="user-1")

    assert first["training_job_id"] == first["job_id"]
    assert second["job_id"] == first["job_id"]
    assert second["training_run_id"] == first["training_run_id"]
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True
    assert len(service._jobs) == 1
    assert service.active("user-1", IDENTITY["project_id"])[0][
        "job_id"
    ] == first["job_id"]


def test_large_run_requires_acknowledgement_and_creates_no_job() -> None:
    store = IsolatedStore()
    proxy = IsolatedDataStoreProxy(store)
    service = TrainingJobService()
    large = ready_preflight()
    large["estimated_fits"] = 200
    large["large_run"] = {
        "required": True,
        "acknowledgement_required": True,
    }
    service.preflight = lambda _request: deepcopy(large)
    with (
        patch.object(job_module, "DATASTORE", proxy),
        patch.object(job_module, "RESULTS", SimpleNamespace(current=lambda: None)),
    ):
        with pytest.raises(ValueError, match="large job"):
            service.create(request(), owner_user_id="user-1")
    assert service._jobs == {}


def test_stale_or_failed_preflight_never_creates_job() -> None:
    store = IsolatedStore()
    proxy = IsolatedDataStoreProxy(store)
    service = TrainingJobService()
    blocked = ready_preflight()
    blocked.update(
        {
            "ready": False,
            "blocking_errors": ["Validation Design is stale."],
        }
    )
    service.preflight = lambda _request: deepcopy(blocked)
    with (
        patch.object(job_module, "DATASTORE", proxy),
        patch.object(job_module, "RESULTS", SimpleNamespace(current=lambda: None)),
    ):
        with pytest.raises(ValueError, match="preflight blocked"):
            service.create(request(), owner_user_id="user-1")
    assert service._jobs == {}

    current = ready_preflight()
    service.preflight = lambda _request: deepcopy(current)
    with (
        patch.object(job_module, "DATASTORE", proxy),
        patch.object(job_module, "RESULTS", SimpleNamespace(current=lambda: None)),
    ):
        with pytest.raises(ValueError, match="preflight is stale"):
            service.create(
                request(expected_preflight_id="old-preflight"),
                owner_user_id="user-1",
            )
    assert service._jobs == {}
