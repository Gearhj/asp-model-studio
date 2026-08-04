from __future__ import annotations

from copy import deepcopy
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest

from server.analysis_partition import service as partition_service_module
from server.analysis_partition.service import AnalysisPartitionService
from server.training import training_job_service as job_module
from server.training import training_preflight_service as preflight_module
from server.training.training_job_service import TrainingJobService
from server.training.training_preflight_service import (
    TRAINING_TARGET_SEMANTICS_CONTRADICTORY,
    TrainingTargetSemanticsError,
)
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
            "analysis_partition_id": "analysis-partition-1",
            "analysis_partition_revision": 3,
            "feature_manifest_hash": "feature-manifest-hash-1",
            "status": "approved",
            "target": "bad_flag",
            "target_contract_id": "source-target-contract-1",
            "problem_type": "classification",
            "event_value": 1,
            "non_event_value": 0,
            "target_definition": {
                "target": "bad_flag",
                "target_contract_id": "source-target-contract-1",
                "problem_type": "classification",
                "positive_value": 1,
                "negative_value": 0,
                "authority_source": "sealed_analysis_partition",
            },
            "development_dataset": {
                "dataset_id": IDENTITY["dataset_id"],
                "dataset_version_id": IDENTITY["dataset_version_id"],
            },
        }
        return {
            **IDENTITY,
            "split_status": "current",
            "analysis_partition": {
                **IDENTITY,
                "analysis_partition_id": "analysis-partition-1",
                "revision": 3,
                "target": "bad_flag",
                "target_contract_id": "source-target-contract-1",
                "problem_type": "classification",
                "problem_type_status": "verified",
                "positive_value": 1,
                "negative_value": 0,
                "evidence_status": "recorded",
                "evidence_ref": "analysis-partition-evidence-1",
                "mdd_status": "recorded",
                "mdd_ref": "analysis-partition-mdd-1",
            },
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
                "analysis_partition_id": "analysis-partition-1",
                "analysis_partition_revision": 3,
                "target": "bad_flag",
                "target_contract_id": "source-target-contract-1",
                "problem_type": "classification",
                "event_value": 1,
                "non_event_value": 0,
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


def _native_partition_record() -> dict[str, object]:
    record: dict[str, object] = {
        **IDENTITY,
        "analysis_partition_id": "analysis-partition-1",
        "revision": 3,
        "target_contract_id": "source-target-contract-1",
        "target_column": "bad_flag",
        "positive_value_json": 1,
        "negative_value_json": 0,
        "predictor_authorization_id": "predictor-auth-native-1",
        "problem_type": "classification",
        "partition_method": "deterministic_random",
        "selection_rationale": "",
        "preview_fingerprint": "native-preview-fingerprint-1",
        "sufficiency_json": {},
        "development_partition_id": "development-population-1",
        "sealed_holdout_partition_id": "final-holdout-1",
        "development_share": 0.8,
        "holdout_share": 0.2,
        "random_seed": 42,
        "stratification_policy": "target",
        "stratification_field": "bad_flag",
        "population_count": 10,
        "development_count": 8,
        "holdout_count": 2,
        "event_counts_json": {},
        "row_assignments_json": {
            "development_positions": list(range(8)),
            "holdout_positions": [8, 9],
        },
        "population_fingerprint": "native-population-fingerprint-1",
        "status": "current",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
        "created_by": "native-owner",
        "evidence_status": "recorded",
        "evidence_ref": "native-evidence-1",
        "mdd_status": "recorded",
        "mdd_ref": "native-mdd-1",
    }
    record["assignment_hash"] = partition_service_module._stable_hash(
        partition_service_module._assignment_payload(record)
    )
    record["artifact_hash"] = partition_service_module._stable_hash(
        partition_service_module._artifact_payload(record)
    )
    return record


def _native_partition_service(
    documentation_readiness: dict[str, object] | None = None,
) -> tuple[AnalysisPartitionService, Mock, dict[str, object]]:
    record = _native_partition_record()
    repository = Mock()
    repository.get_current.return_value = record
    repository.documentation_readiness.return_value = (
        documentation_readiness
        if documentation_readiness is not None
        else {
            "ready": True,
            "flags_ready": True,
            "evidence_ready": True,
            "mdd_ready": True,
            "evidence_ref": record["evidence_ref"],
            "mdd_ref": record["mdd_ref"],
        }
    )
    return AnalysisPartitionService(repository), repository, record


@pytest.fixture(autouse=True)
def native_partition_authority(monkeypatch):
    service, repository, record = _native_partition_service()
    monkeypatch.setattr(
        preflight_module, "analysis_partition_service", service
    )
    return SimpleNamespace(
        service=service,
        repository=repository,
        record=record,
    )


def _legacy_partition_record(
    *,
    positive_value=1,
    negative_value=0,
    problem_type: str = "regression",
) -> dict[str, object]:
    """Build an integrity-valid v1 row whose migration type is not authority."""

    record: dict[str, object] = {
        **IDENTITY,
        "analysis_partition_id": "analysis-partition-legacy-1",
        "revision": 1,
        "target_contract_id": "source-target-contract-1",
        "target_column": "bad_flag",
        "positive_value_json": positive_value,
        "negative_value_json": negative_value,
        "predictor_authorization_id": "predictor-auth-legacy-1",
        "problem_type": problem_type,
        "partition_method": "deterministic_random",
        "selection_rationale": "",
        "preview_fingerprint": "",
        "sufficiency_json": {},
        "development_partition_id": "development-legacy-1",
        "sealed_holdout_partition_id": "holdout-legacy-1",
        "development_share": 0.8,
        "holdout_share": 0.2,
        "random_seed": 42,
        "stratification_policy": "target",
        "stratification_field": "bad_flag",
        "population_count": 10,
        "development_count": 8,
        "holdout_count": 2,
        "event_counts_json": {},
        "row_assignments_json": {
            "development_positions": list(range(8)),
            "holdout_positions": [8, 9],
        },
        "population_fingerprint": "legacy-population-fingerprint-1",
        "status": "current",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
        "created_by": "legacy-owner",
        "evidence_status": "recorded",
        "evidence_ref": "legacy-evidence-1",
        "mdd_status": "recorded",
        "mdd_ref": "legacy-mdd-1",
    }
    record["assignment_hash"] = partition_service_module._stable_hash(
        partition_service_module._assignment_payload(record)
    )
    record["artifact_hash"] = partition_service_module._stable_hash(
        partition_service_module._artifact_payload(record)
    )
    return record


def _legacy_store_and_service(
    record: dict[str, object],
) -> tuple[IsolatedStore, AnalysisPartitionService, Mock]:
    store = IsolatedStore()
    preserve_corrupted_artifact = record.get("artifact_hash") == "corrupted"
    holdout = pd.DataFrame(
        {
            "feature_a": [8.0, 9.0],
            "feature_b": [-1.0, -2.0],
        },
        index=[8, 9],
    )
    full_features = pd.concat([store.X_train, holdout])
    full_target = pd.concat(
        [store.y_train, pd.Series([0, 1], index=[8, 9], name="bad_flag")]
    )
    store.raw_df = full_features.copy()
    store.raw_df["bad_flag"] = full_target
    store.processed_df = store.raw_df.copy()
    store.meta["selected_columns"] = ["feature_a", "feature_b"]
    record["population_fingerprint"] = (
        partition_service_module._structural_fingerprint(store.raw_df)
    )
    record["assignment_hash"] = partition_service_module._stable_hash(
        partition_service_module._assignment_payload(record)
    )
    record["artifact_hash"] = partition_service_module._stable_hash(
        partition_service_module._artifact_payload(record)
    )
    if preserve_corrupted_artifact:
        record["artifact_hash"] = "corrupted"
    safe_partition = AnalysisPartitionService.safe_record(record)
    store.meta["analysis_partition"] = safe_partition
    split_record = store.meta["split_record"]
    validation_design = split_record["validation_design"]
    lineage = {
        "analysis_partition_id": record["analysis_partition_id"],
        "analysis_partition_revision": record["revision"],
        "development_partition_id": record["development_partition_id"],
        "sealed_holdout_partition_id": record[
            "sealed_holdout_partition_id"
        ],
        "training_population_id": record["development_partition_id"],
        "selection_partition_id": record["development_partition_id"],
        "holdout_population_id": record["sealed_holdout_partition_id"],
        "final_holdout_partition_id": record[
            "sealed_holdout_partition_id"
        ],
    }
    split_record.update(lineage)
    validation_design.update(lineage)
    validation_design["target_definition"] = {
        "target": "bad_flag",
        "target_contract_id": "source-target-contract-1",
        "problem_type": "classification",
        "positive_value": 1,
        "negative_value": 0,
        "authority_source": "verified_legacy_analysis_partition",
        "compatibility_status": "verified_legacy_v1",
        "lineage_contract": "analysis_partition_v1",
    }
    split_record["target_authority"] = {
        "source": "verified_legacy_analysis_partition",
        "compatibility_status": "verified_legacy_v1",
        "lineage_contract": "analysis_partition_v1",
        "target_membership_fingerprint_status": "legacy_not_recorded",
    }
    repository = Mock()
    repository.get_current.return_value = record
    repository.documentation_readiness.return_value = {
        "ready": True,
        "flags_ready": True,
        "evidence_ready": True,
        "mdd_ready": True,
        "evidence_ref": record["evidence_ref"],
        "mdd_ref": record["mdd_ref"],
    }
    return store, AnalysisPartitionService(repository), repository


def _run_legacy_preflight(
    store: IsolatedStore,
    service: AnalysisPartitionService,
) -> dict[str, object]:
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
        patch.object(
            preflight_module, "analysis_partition_service", service
        ),
    ):
        return preflight_module.training_preflight(request())


def test_authoritative_preflight_is_consistent_and_never_opens_holdout(
    native_partition_authority,
) -> None:
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
    assert result["problem_type"] == "classification"
    assert result["event_value"] == 1
    assert result["non_event_value"] == 0
    assert result["target_contract"]["source_target_contract_id"] == (
        "source-target-contract-1"
    )
    assert result["target_authority_hash"] == result[
        "target_semantics_authority"
    ]["target_authority_hash"]
    assert result["selected_algorithm_ids"] == ["logreg"]
    assert result["selected_algorithm_versions"]["logreg"]
    assert result["estimated_fits"] == 2
    assert result["final_holdout_sealed"] is True
    assert result["final_holdout_access"] == "contract_metadata_only"
    assert result["selection_evidence_source"] == (
        "development_population_cross_validation"
    )
    native_partition_authority.repository.get_current.assert_called_once_with(
        IDENTITY["project_id"]
    )
    readiness_call = (
        native_partition_authority.repository.documentation_readiness.call_args
    )
    assert readiness_call is not None
    assert readiness_call.args[0]["analysis_partition_id"] == (
        "analysis-partition-1"
    )


@pytest.mark.parametrize(
    "documentation_readiness",
    [
        {
            "ready": False,
            "flags_ready": True,
            "evidence_ready": False,
            "mdd_ready": False,
            "evidence_ref": "native-evidence-1",
            "mdd_ref": "native-mdd-1",
        },
        {
            "ready": False,
            "flags_ready": True,
            "evidence_ready": True,
            "mdd_ready": False,
            "mdd_content_ready": False,
            "evidence_ref": "native-evidence-1",
            "mdd_ref": "native-mdd-1",
        },
    ],
    ids=["missing-sidecars", "corrupt-mdd-content"],
)
def test_native_v2_cached_recorded_flags_cannot_bypass_durable_documentation(
    documentation_readiness: dict[str, object],
) -> None:
    store = IsolatedStore()
    assert store.meta["analysis_partition"]["evidence_status"] == "recorded"
    assert store.meta["analysis_partition"]["mdd_status"] == "recorded"
    service, repository, _record = _native_partition_service(
        documentation_readiness
    )

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
        patch.object(
            preflight_module, "analysis_partition_service", service
        ),
    ):
        result = preflight_module.training_preflight(request())

    assert result["ready"] is False
    detail = next(
        item
        for item in result["blocking_details"]
        if "durable_analysis_partition" in item.get("mismatches", {})
    )
    assert detail["code"] == "training_target_authority_unavailable"
    assert detail["mismatches"]["durable_analysis_partition"]["code"] == (
        "analysis_partition_documentation_pending"
    )
    repository.get_current.assert_called_once_with(IDENTITY["project_id"])
    repository.documentation_readiness.assert_called_once()


def test_verified_legacy_v1_authority_is_accepted_and_hash_freezes_source() -> None:
    record = _legacy_partition_record()
    store, service, repository = _legacy_store_and_service(record)

    result = _run_legacy_preflight(store, service)

    assert result["ready"] is True
    authority = result["target_semantics_authority"]
    assert authority["problem_type"] == "classification"
    assert authority["event_value"] == 1
    assert authority["non_event_value"] == 0
    assert (
        authority["partition_authority_source"]
        == "verified_legacy_analysis_partition"
    )
    assert authority["compatibility_status"] == "verified_legacy_v1"
    assert authority["lineage_contract"] == "analysis_partition_v1"
    assert authority["assignment_hash"] == record["assignment_hash"]
    frozen = dict(authority)
    frozen_hash = frozen.pop("target_authority_hash")
    assert frozen_hash == preflight_module.canonical_contract_hash(frozen)
    spoofed = {**frozen, "partition_authority_source": "mutable_metadata"}
    assert preflight_module.canonical_contract_hash(spoofed) != frozen_hash
    assert result["target_authority_hash"] == frozen_hash
    assert repository.get_current.call_count == 2
    repository.get_current.assert_called_with(IDENTITY["project_id"])


def test_verified_legacy_v1_pending_documentation_blocks_preflight() -> None:
    record = _legacy_partition_record()
    record.update(
        {
            "evidence_status": "pending",
            "evidence_ref": "",
            "mdd_status": "pending",
            "mdd_ref": "",
        }
    )
    store, service, repository = _legacy_store_and_service(record)
    store.meta["analysis_partition"].update(
        {
            "evidence_status": "pending",
            "evidence_ref": "",
            "mdd_status": "pending",
            "mdd_ref": "",
        }
    )
    repository.documentation_readiness.return_value = {
        "ready": False,
        "flags_ready": False,
        "evidence_ready": False,
        "mdd_ready": False,
        "evidence_ref": None,
        "mdd_ref": None,
    }

    result = _run_legacy_preflight(store, service)

    assert result["ready"] is False
    assert any(
        detail.get("mismatches", {})
        .get("durable_analysis_partition", {})
        .get("code")
        == "analysis_partition_documentation_pending"
        for detail in result["blocking_details"]
    )


def test_verified_legacy_v1_tampered_training_arrays_fail_membership() -> None:
    record = _legacy_partition_record()
    store, service, _repository = _legacy_store_and_service(record)
    store.X_train.loc[0, "feature_a"] = 9999.0

    result = _run_legacy_preflight(store, service)

    assert result["ready"] is False
    assert any(
        "development_feature_values" in detail.get("mismatches", {})
        for detail in result["blocking_details"]
    )


def test_ambiguous_checksum_valid_legacy_partition_fails_closed() -> None:
    record = _legacy_partition_record(
        positive_value=None,
        negative_value=None,
    )
    store, service, _repository = _legacy_store_and_service(record)
    split_record = store.meta["split_record"]
    validation_design = split_record["validation_design"]
    split_record.update(
        {
            "problem_type": "regression",
            "event_value": None,
            "non_event_value": None,
        }
    )
    validation_design.update(
        {
            "problem_type": "regression",
            "event_value": None,
            "non_event_value": None,
        }
    )
    validation_design["target_definition"].update(
        {
            "problem_type": "regression",
            "positive_value": None,
            "negative_value": None,
        }
    )

    result = _run_legacy_preflight(store, service)

    assert result["ready"] is False
    detail = result["blocking_details"][0]
    assert detail["code"] == "training_target_authority_unavailable"
    assert detail["mismatches"]["durable_analysis_partition"]["code"] == (
        "analysis_partition_target_authority_unverified"
    )


def test_checksum_invalid_legacy_partition_fails_closed() -> None:
    record = _legacy_partition_record()
    record["artifact_hash"] = "corrupted"
    store, service, _repository = _legacy_store_and_service(record)

    result = _run_legacy_preflight(store, service)

    assert result["ready"] is False
    detail = result["blocking_details"][0]
    assert detail["code"] == "training_target_authority_unavailable"
    assert detail["mismatches"]["durable_analysis_partition"]["code"] == (
        "analysis_partition_integrity_failed"
    )


def test_mutable_legacy_semantics_cannot_spoof_durable_target_authority() -> None:
    record = _legacy_partition_record()
    store, service, _repository = _legacy_store_and_service(record)
    split_record = store.meta["split_record"]
    validation_design = split_record["validation_design"]
    split_record.update({"event_value": 0, "non_event_value": 1})
    validation_design.update({"event_value": 0, "non_event_value": 1})
    validation_design["target_definition"].update(
        {"positive_value": 0, "negative_value": 1}
    )
    store.meta["analysis_partition"].update(
        {"positive_value": 0, "negative_value": 1}
    )

    result = _run_legacy_preflight(store, service)

    assert result["ready"] is False
    detail = result["blocking_details"][0]
    assert detail["code"] == "training_target_authority_unavailable"
    mismatches = detail["mismatches"]
    assert "analysis_partition.positive_value" in mismatches
    assert "analysis_partition.negative_value" in mismatches
    assert "durable_target_authority.event_value" in mismatches
    assert "durable_target_authority.non_event_value" in mismatches


@pytest.mark.parametrize(
    ("overrides", "mismatch_fields"),
    [
        ({"problem_type": "regression"}, {"problem_type"}),
        (
            {"event_value": 0, "non_event_value": 1},
            {"event_value", "non_event_value"},
        ),
    ],
)
def test_client_cannot_spoof_or_invert_governed_target_semantics(
    overrides: dict[str, object], mismatch_fields: set[str]
) -> None:
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
        result = preflight_module.training_preflight(request(**overrides))

    assert result["ready"] is False
    assert result["problem_type"] == "classification"
    assert result["event_value"] == 1
    assert result["non_event_value"] == 0
    detail = result["blocking_details"][0]
    assert detail["code"] == TRAINING_TARGET_SEMANTICS_CONTRADICTORY
    assert set(detail["mismatches"]) == mismatch_fields
    for field in mismatch_fields:
        assert "requested" in detail["mismatches"][field]
        assert "authoritative" in detail["mismatches"][field]

    service = TrainingJobService()
    with patch.object(service, "preflight", return_value=result):
        with pytest.raises(TrainingTargetSemanticsError) as rejected:
            service.create(request(**overrides), owner_user_id="isolated-user")
    assert rejected.value.detail["code"] == (
        TRAINING_TARGET_SEMANTICS_CONTRADICTORY
    )
    assert set(rejected.value.detail["mismatches"]) == mismatch_fields


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
    target_authority = {
        "target": "bad_flag",
        "source_target_contract_id": "source-target-contract-1",
        "problem_type": "classification",
        "event_value": 1,
        "non_event_value": 0,
        "authority_source": (
            "approved_validation_design_bound_to_sealed_analysis_partition"
        ),
        "analysis_partition_id": "analysis-partition-1",
        "analysis_partition_revision": 3,
        "validation_design_id": "validation-design-1",
        "validation_design_version": "validation-design-version-1",
    }
    target_authority["target_authority_hash"] = (
        preflight_module.canonical_contract_hash(target_authority)
    )
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
        "target_semantics_authority": target_authority,
        "target_authority_hash": target_authority[
            "target_authority_hash"
        ],
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
