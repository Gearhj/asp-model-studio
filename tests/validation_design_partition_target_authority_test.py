"""Fail-closed Validation Design target-authority contract tests."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.analysis_partition.types import (
    ANALYSIS_PARTITION_CONTRADICTORY,
    ANALYSIS_PARTITION_INTEGRITY_FAILED,
    ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED,
)
from server.splitting import split_router


def _partition(**updates):
    record = {
        "analysis_partition_id": "analysis-partition-authority-r3",
        "revision": 3,
        "project_id": "project-authority",
        "dataset_id": "dataset-authority",
        "dataset_version_id": "version-authority",
        "target_contract_id": "target-contract-authority",
        "target_column": "bad_flag",
        "positive_value_json": 1,
        "negative_value_json": 0,
        "predictor_authorization_id": "predictor-authority",
        "problem_type": "classification",
        "partition_method": "deterministic_random",
        "preview_fingerprint": "preview-authority",
        "development_partition_id": "development-authority-r3",
        "sealed_holdout_partition_id": "holdout-authority-r3",
        "development_share": 0.8,
        "holdout_share": 0.2,
        "random_seed": 42,
        "stratification_policy": "target",
        "stratification_field": "bad_flag",
        "status": "current",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
    }
    record.update(updates)
    return record


def _payload(**updates):
    values = {
        "project_id": "project-authority",
        "dataset_id": "dataset-authority",
        "dataset_version_id": "version-authority",
        "test_size": 0.2,
        "random_seed": 42,
        "stratify": True,
    }
    values.update(updates)
    return split_router.SplitConfigPayload(**values)


def test_omitted_client_semantics_rebind_to_exact_sealed_classification_contract():
    authority = split_router._partition_target_authority(
        _payload(),
        _partition(),
    )

    assert authority == {
        "target_contract_id": "target-contract-authority",
        "target": "bad_flag",
        "problem_type": "classification",
        "event_value": 1,
        "non_event_value": 0,
        "source": "sealed_analysis_partition",
    }


def test_omitted_defaults_do_not_turn_a_sealed_regression_partition_into_classification():
    authority = split_router._partition_target_authority(
        _payload(),
        _partition(
            target_column="loss",
            problem_type="regression",
            positive_value_json=None,
            negative_value_json=None,
            stratification_policy="none",
            stratification_field="",
        ),
    )

    assert authority["problem_type"] == "regression"
    assert authority["event_value"] is None
    assert authority["non_event_value"] is None


@pytest.mark.parametrize(
    ("claims", "mismatch_field"),
    [
        ({"problem_type": "regression"}, "problem_type"),
        ({"event_value": 0}, "event_value"),
        ({"negative_value": 1}, "negative_value"),
        ({"non_event_value": 1}, "non_event_value"),
    ],
)
def test_contradictory_client_target_claims_are_rejected(claims, mismatch_field):
    with pytest.raises(HTTPException) as caught:
        split_router._partition_target_authority(
            _payload(**claims),
            _partition(),
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == ANALYSIS_PARTITION_CONTRADICTORY
    assert mismatch_field in caught.value.detail["mismatches"]
    assert caught.value.detail["identifiers"] == {
        "analysis_partition_id": "analysis-partition-authority-r3",
        "analysis_partition_revision": 3,
        "target_contract_id": "target-contract-authority",
    }


def test_minimal_unverifiable_legacy_partition_fails_closed_without_inference():
    legacy = _partition(preview_fingerprint="", problem_type="classification")

    with pytest.raises(HTTPException) as caught:
        split_router._partition_target_authority(
            _payload(problem_type="classification", event_value=1),
            legacy,
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == ANALYSIS_PARTITION_INTEGRITY_FAILED
    assert "checksum" in caught.value.detail["message"].lower()
    assert "do not use" in caught.value.detail["recovery"].lower()


@pytest.mark.parametrize(
    "partition",
    [
        _partition(target_contract_id=""),
        _partition(positive_value_json=None),
        _partition(negative_value_json=1),
        _partition(
            problem_type="regression",
            positive_value_json=1,
            negative_value_json=0,
        ),
    ],
)
def test_incomplete_or_internally_inconsistent_native_target_contract_is_rejected(
    partition,
):
    with pytest.raises(HTTPException) as caught:
        split_router._sealed_partition_target_authority(partition)

    assert caught.value.status_code == 409
    assert (
        caught.value.detail["code"]
        == ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED
    )
