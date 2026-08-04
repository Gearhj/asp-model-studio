"""Fail-closed documentation and legacy target-authority boundaries."""
from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from fastapi import HTTPException

from server.analysis_partition import service as service_module
from server.analysis_partition.service import AnalysisPartitionService
from server.analysis_partition.types import (
    ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
    ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED,
    AnalysisPartitionDocumentationRequest,
    AnalysisPartitionError,
)
from server.analytics.analysis_scope import workspace_fingerprint
from server.eda.analytical_contract import (
    EDAAnalyticalContractError,
    resolve_development_partition,
)
from server.eda.workspace_service import EDAWorkspaceService
from server.eda.workspace_types import EDAWorkspaceRequest


partition_router = importlib.import_module("server.analysis_partition.router")


def _legacy_record(*, ambiguous: bool = False) -> dict:
    assignments = {
        "development_positions": [0, 1, 2, 3],
        "holdout_positions": [4, 5],
    }
    frame = pd.DataFrame(index=range(6))
    record = {
        "analysis_partition_id": "partition-doc-gate-r1",
        "revision": 1,
        "project_id": "project-doc-gate",
        "dataset_id": "dataset-doc-gate",
        "dataset_version_id": "version-doc-gate",
        "target_contract_id": "target-contract-doc-gate",
        "target_column": "bad_flag",
        "positive_value_json": 1,
        "negative_value_json": None if ambiguous else 0,
        "predictor_authorization_id": "predictor-auth-doc-gate",
        "problem_type": "classification",
        "partition_method": "deterministic_random",
        "selection_rationale": "",
        "preview_fingerprint": "",
        "sufficiency_json": {},
        "development_partition_id": "development-doc-gate-r1",
        "sealed_holdout_partition_id": "holdout-doc-gate-r1",
        "development_share": 4 / 6,
        "holdout_share": 2 / 6,
        "random_seed": 42,
        "stratification_policy": "target",
        "stratification_field": "bad_flag",
        "population_count": 6,
        "development_count": 4,
        "holdout_count": 2,
        "event_counts_json": {},
        "row_assignments_json": assignments,
        "population_fingerprint": service_module._structural_fingerprint(frame),
        "status": "current",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
        "evidence_status": "pending",
        "mdd_status": "pending",
    }
    record["assignment_hash"] = service_module._stable_hash(
        service_module._assignment_payload(record)
    )
    record["artifact_hash"] = service_module._stable_hash(
        service_module._artifact_payload(record)
    )
    return record


def test_direct_eda_resolver_cannot_bypass_pending_partition_documentation() -> None:
    pending = AnalysisPartitionError(
        ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
        "Exact Analysis Partition documentation is pending.",
    )
    current = Mock(side_effect=pending)
    materialize = Mock()
    store = SimpleNamespace(
        meta={"target_contract_id": "target-contract-doc-gate"}
    )
    with (
        patch.object(service_module.analysis_partition_service, "current", current),
        patch.object(
            service_module.analysis_partition_service,
            "materialize_development",
            materialize,
        ),
    ):
        with pytest.raises(EDAAnalyticalContractError) as captured:
            resolve_development_partition(
                store=store,
                identity={
                    "project_id": "project-doc-gate",
                    "dataset_id": "dataset-doc-gate",
                    "dataset_version_id": "version-doc-gate",
                },
                target="bad_flag",
                authorized_predictors=["feature_a"],
                predictor_manifest_id="predictor-auth-doc-gate",
            )

    assert captured.value.code == ANALYSIS_PARTITION_DOCUMENTATION_PENDING
    assert current.call_args.kwargs["require_documentation_ready"] is True
    materialize.assert_not_called()


def test_pending_documentation_overview_is_target_free_structural_only() -> None:
    workspace = EDAWorkspaceService()
    frame = pd.DataFrame(
        {
            "feature_a": [1.0, 2.0, 3.0],
            "feature_b": [3.0, 2.0, 1.0],
            "bad_flag": [0, 1, 1],
        }
    )
    authorization = {
        "manifest_version": "predictor-auth-doc-gate",
        "authorized_predictors": ["feature_a", "feature_b"],
        "target_source_fields": [],
        "target_source_excluded": [],
    }
    request = EDAWorkspaceRequest(
        project_id="project-doc-gate", target="bad_flag"
    )
    blocked = EDAAnalyticalContractError(
        "Exact Analysis Partition documentation is pending.",
        code=ANALYSIS_PARTITION_DOCUMENTATION_PENDING,
    )
    with (
        patch.object(
            workspace,
            "_dataset",
            return_value=(
                frame,
                "bad_flag",
                frame["bad_flag"],
                "unavailable",
                None,
                authorization,
            ),
        ),
        patch.object(workspace, "_governed_contract", side_effect=blocked),
        patch("server.eda.workspace_service.upsert_evidence") as evidence_write,
    ):
        result = workspace._cached("overview", request, workspace._overview)

    assert result["partial"] is True
    assert result["governed_readiness"]["code"] == (
        ANALYSIS_PARTITION_DOCUMENTATION_PENDING
    )
    assert result["governed_readiness"]["target_directed_available"] is False
    assert "target_profile" not in result
    assert result["headline"]["predictors"] == 2
    assert "bad_flag" not in (
        result["available_fields"]["numeric"]
        + result["available_fields"]["categorical"]
    )
    assert result["workspace_compatibility_scope"]["datasetFingerprint"] == (
        workspace_fingerprint(frame, "bad_flag", {})
    )
    assert not workspace._cache
    assert not workspace._contract_cache
    evidence_write.assert_not_called()


def test_structural_workspace_fingerprint_excludes_target_values() -> None:
    frame = pd.DataFrame(
        {
            "feature_a": [1.0, 2.0, 3.0, 4.0],
            "feature_b": [4.0, 3.0, 2.0, 1.0],
            "bad_flag": [0, 0, 1, 1],
        }
    )
    source = {"kind": "dataset_library", "filename": "governed.csv"}
    baseline = workspace_fingerprint(frame, "bad_flag", source)

    target_changed = frame.copy(deep=True)
    target_changed["bad_flag"] = [1, 1, 0, 0]
    assert workspace_fingerprint(target_changed, "bad_flag", source) == baseline

    predictor_changed = frame.copy(deep=True)
    predictor_changed.loc[0, "feature_a"] = 999.0
    assert workspace_fingerprint(predictor_changed, "bad_flag", source) != baseline

    renamed_target = frame.rename(columns={"bad_flag": "outcome"})
    assert workspace_fingerprint(renamed_target, "outcome", source) != baseline


def test_development_target_fingerprint_uses_exact_materialized_values_only() -> None:
    baseline = pd.Series([0, 1, 0, 1], name="bad_flag")
    same = baseline.copy(deep=True)
    changed = pd.Series([1, 1, 0, 1], name="bad_flag")

    baseline_fingerprint = (
        EDAWorkspaceService._development_target_fingerprint(baseline)
    )
    assert (
        EDAWorkspaceService._development_target_fingerprint(same)
        == baseline_fingerprint
    )
    assert (
        EDAWorkspaceService._development_target_fingerprint(changed)
        != baseline_fingerprint
    )


def test_ambiguous_v1_cannot_be_reported_current_or_documented() -> None:
    record = _legacy_record(ambiguous=True)
    repository = Mock()
    repository.get_current.return_value = record
    service = AnalysisPartitionService(repository)
    store = SimpleNamespace(meta={})
    authority = {
        "target": "bad_flag",
        "target_contract_id": "target-contract-doc-gate",
        "predictor_authorization_id": "predictor-auth-doc-gate",
    }
    with (
        patch.object(partition_router, "analysis_partition_service", service),
        patch.object(
            partition_router,
            "_authoritative_partition_request",
            return_value=(store, authority, {}),
        ),
    ):
        with pytest.raises(HTTPException) as status_error:
            partition_router.analysis_partition_status(
                project_id=record["project_id"],
                dataset_id=record["dataset_id"],
                dataset_version_id=record["dataset_version_id"],
                target=record["target_column"],
                target_contract_id=record["target_contract_id"],
                predictor_authorization_id=record[
                    "predictor_authorization_id"
                ],
                user={"userId": "doc-gate-owner"},
            )
    assert status_error.value.status_code == 409
    assert status_error.value.detail["code"] == (
        ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED
    )
    assert "analysis_partition" not in store.meta

    request = AnalysisPartitionDocumentationRequest(
        project_id=record["project_id"],
        dataset_id=record["dataset_id"],
        dataset_version_id=record["dataset_version_id"],
        target=record["target_column"],
        target_contract_id=record["target_contract_id"],
        predictor_authorization_id=record["predictor_authorization_id"],
        analysis_partition_id=record["analysis_partition_id"],
        revision=record["revision"],
    )
    evidence = Mock()
    mdd = Mock()
    with (
        patch.object(partition_router, "analysis_partition_service", service),
        patch.object(
            partition_router,
            "_authorize_partition_documentation_retry",
            return_value=(store, record),
        ),
        patch.object(partition_router, "_record_partition_evidence", evidence),
        patch.object(partition_router, "_record_partition_mdd", mdd),
    ):
        with pytest.raises(HTTPException) as retry_error:
            partition_router.complete_analysis_partition_documentation(
                request, user={"userId": "doc-gate-owner"}
            )
    assert retry_error.value.status_code == 409
    assert retry_error.value.detail["code"] == (
        ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED
    )
    evidence.assert_not_called()
    mdd.assert_not_called()
