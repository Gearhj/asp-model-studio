"""Verified, read-only compatibility for pre-product Analysis Partitions."""
from __future__ import annotations

from copy import deepcopy
from unittest.mock import Mock

import pandas as pd
import pytest
from fastapi import HTTPException

from server.analysis_partition import service as service_module
from server.analysis_partition.service import AnalysisPartitionService
from server.analysis_partition.types import (
    ANALYSIS_PARTITION_CONTRADICTORY,
    ANALYSIS_PARTITION_INTEGRITY_FAILED,
    ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED,
    AnalysisPartitionError,
)
from server.core.dataset_store import DatasetStore
from server.splitting import split_router


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "feature_a": [10, 11, 12, 13, 14, 15],
            "feature_b": [20, 21, 22, 23, 24, 25],
            "bad_flag": [0, 1, 0, 1, 0, 1],
        },
        index=[f"row-{position}" for position in range(6)],
    )


def _store(frame: pd.DataFrame) -> DatasetStore:
    store = DatasetStore()
    store.raw_df = frame
    store.processed_df = frame
    store.target = "bad_flag"
    store.meta["selected_columns"] = ["feature_a", "feature_b"]
    return store


def _sealed_record(
    frame: pd.DataFrame,
    *,
    native_v2: bool = False,
    positive_value=1,
    negative_value=0,
    stratification_policy: str = "target",
    problem_type: str = "classification",
    include_target_fingerprints: bool | None = None,
) -> dict:
    development = [0, 2, 3, 5]
    holdout = [1, 4]
    include_fingerprints = (
        native_v2
        if include_target_fingerprints is None
        else include_target_fingerprints
    )
    assignments = {
        "development_positions": development,
        "holdout_positions": holdout,
    }
    if include_fingerprints:
        assignments.update(
            {
                "development_target_fingerprint": (
                    service_module._target_membership_fingerprint(
                        frame, "bad_flag", development
                    )
                ),
                "holdout_target_fingerprint": (
                    service_module._target_membership_fingerprint(
                        frame, "bad_flag", holdout
                    )
                ),
            }
        )
    record = {
        "analysis_partition_id": "analysis-partition-legacy-r1",
        "revision": 1,
        "project_id": "project-legacy",
        "dataset_id": "dataset-legacy",
        "dataset_version_id": "version-legacy",
        "target_contract_id": "target-contract-legacy",
        "target_column": "bad_flag",
        "positive_value_json": positive_value,
        "negative_value_json": negative_value,
        "predictor_authorization_id": "predictor-auth-legacy",
        # A migrated v1 row may have a default that is not evidence. Tests set
        # this independently from the original v1 target mapping deliberately.
        "problem_type": problem_type,
        "partition_method": "deterministic_random",
        "selection_rationale": "",
        "preview_fingerprint": "native-preview" if native_v2 else "",
        "sufficiency_json": {"overall_status": "ready"} if native_v2 else {},
        "development_partition_id": "development-legacy-r1",
        "sealed_holdout_partition_id": "holdout-legacy-r1",
        "development_share": 4 / 6,
        "holdout_share": 2 / 6,
        "random_seed": 42,
        "stratification_policy": stratification_policy,
        "stratification_field": (
            "bad_flag" if stratification_policy == "target" else ""
        ),
        "population_count": 6,
        "development_count": 4,
        "holdout_count": 2,
        "event_counts_json": {},
        "row_assignments_json": assignments,
        "population_fingerprint": service_module._structural_fingerprint(frame),
        "status": "current",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
        "created_by": "legacy-owner",
    }
    record["assignment_hash"] = service_module._stable_hash(
        service_module._assignment_payload(record)
    )
    record["artifact_hash"] = service_module._stable_hash(
        service_module._artifact_payload(record)
    )
    return record


def _payload(**updates) -> split_router.SplitConfigPayload:
    values = {
        "project_id": "project-legacy",
        "dataset_id": "dataset-legacy",
        "dataset_version_id": "version-legacy",
        "test_size": 2 / 6,
        "random_seed": 42,
        "stratify": True,
    }
    values.update(updates)
    return split_router.SplitConfigPayload(**values)


class _GuardedILoc:
    def __init__(self, indexer, owner: "_HoldoutGuardFrame") -> None:
        self._indexer = indexer
        self._owner = owner

    def __getitem__(self, key):
        row_key = key[0] if isinstance(key, tuple) else key
        if isinstance(row_key, (list, tuple, pd.Index)):
            selected = {int(position) for position in row_key}
            self._owner.position_reads.append(selected)
            if selected.intersection(self._owner.forbidden_positions):
                raise AssertionError("development materialization accessed holdout rows")
        return self._indexer[key]


class _HoldoutGuardFrame(pd.DataFrame):
    _metadata = ["forbidden_positions", "position_reads"]

    @property
    def _constructor(self):
        return _HoldoutGuardFrame

    @property
    def iloc(self):
        return _GuardedILoc(super().iloc, self)


def test_verified_v1_exact_partition_reuses_assignments_without_new_revision():
    frame = _frame()
    record = _sealed_record(
        frame,
        native_v2=False,
        # Deliberately contradict the 0025-style field: v1 semantics must be
        # recovered from original labels, never from this migration value.
        problem_type="regression",
    )
    original = deepcopy(record)
    repository = Mock()
    repository.get_current.return_value = record
    service = AnalysisPartitionService(repository)

    current = service.current(
        "project-legacy",
        "dataset-legacy",
        "version-legacy",
        target="bad_flag",
        target_contract_id="target-contract-legacy",
        predictor_authorization_id="predictor-auth-legacy",
    )
    authority = split_router._partition_target_authority(_payload(), current)
    safe = split_router._safe_partition_with_target_authority(
        service.safe_record(current), authority
    )
    X_dev, X_holdout, y_dev, y_holdout = service.materialize_validation(
        _store(frame), current, ["feature_a", "feature_b"]
    )

    assert authority["problem_type"] == "classification"
    assert authority["source"] == "verified_legacy_analysis_partition"
    assert authority["compatibility_status"] == "verified_legacy_v1"
    assert authority["target_membership_fingerprint_status"] == "legacy_not_recorded"
    assert safe["problem_type_status"] == "verified_legacy"
    assert safe["compatibility_status"] == "verified_legacy_v1"
    assert X_dev.index.tolist() == ["row-0", "row-2", "row-3", "row-5"]
    assert X_holdout.index.tolist() == ["row-1", "row-4"]
    assert y_dev.index.tolist() == X_dev.index.tolist()
    assert y_holdout.index.tolist() == X_holdout.index.tolist()
    assert current["revision"] == 1
    assert record == original
    repository.create_or_reuse.assert_not_called()
    repository.reset.assert_not_called()


def test_v1_development_materialization_never_indexes_holdout_positions():
    base = _frame()
    record = _sealed_record(base, native_v2=False)
    guarded = _HoldoutGuardFrame(base.copy())
    guarded.forbidden_positions = {1, 4}
    guarded.position_reads = []
    # If any compatibility implementation hashes the full target or holdout,
    # the guarded iloc indexer raises. Only development positions may be read.
    X_dev, y_dev = AnalysisPartitionService().materialize_development(
        _store(guarded), record, ["feature_a", "feature_b"]
    )

    assert len(X_dev) == 4
    assert y_dev.tolist() == [0, 0, 1, 1]
    assert guarded.position_reads
    assert all(not positions.intersection({1, 4}) for positions in guarded.position_reads)
    assert (
        y_dev.attrs["analysis_partition_compatibility"]["compatibility_status"]
        == "verified_legacy_v1"
    )


def test_verified_v1_regression_ignores_migration_problem_type_default():
    frame = _frame()
    record = _sealed_record(
        frame,
        native_v2=False,
        positive_value=None,
        negative_value=None,
        stratification_policy="none",
        problem_type="classification",
    )

    authority = AnalysisPartitionService.target_authority_compatibility(record)

    assert authority["problem_type"] == "regression"
    assert authority["event_value"] is None
    assert authority["non_event_value"] is None
    assert authority["compatibility_status"] == "verified_legacy_v1"


@pytest.mark.parametrize(
    "record",
    [
        lambda frame: _sealed_record(
            frame, native_v2=False, positive_value=1, negative_value=None
        ),
        lambda frame: _sealed_record(
            frame, native_v2=False, positive_value=1, negative_value=1
        ),
        lambda frame: _sealed_record(
            frame,
            native_v2=False,
            positive_value=None,
            negative_value=None,
            stratification_policy="target",
        ),
    ],
)
def test_ambiguous_but_checksum_valid_v1_target_contract_fails_closed(record):
    with pytest.raises(AnalysisPartitionError) as caught:
        AnalysisPartitionService.target_authority_compatibility(record(_frame()))

    assert caught.value.code == ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED
    assert caught.value.status_code == 409
    assert "legacy" in caught.value.message.lower()


def test_corrupted_v1_artifact_fails_integrity_before_compatibility():
    record = _sealed_record(_frame(), native_v2=False)
    record["artifact_hash"] = "corrupted"

    with pytest.raises(AnalysisPartitionError) as caught:
        AnalysisPartitionService.target_authority_compatibility(record)

    assert caught.value.code == ANALYSIS_PARTITION_INTEGRITY_FAILED
    assert caught.value.status_code == 409


def test_verified_legacy_authority_rejects_contradictory_client_claim():
    record = _sealed_record(_frame(), native_v2=False)

    with pytest.raises(HTTPException) as caught:
        split_router._partition_target_authority(
            _payload(problem_type="regression"), record
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == ANALYSIS_PARTITION_CONTRADICTORY
    assert "problem_type" in caught.value.detail["mismatches"]


def test_native_v2_missing_target_fingerprints_remains_strict():
    frame = _frame()
    record = _sealed_record(
        frame,
        native_v2=True,
        include_target_fingerprints=False,
    )

    with pytest.raises(AnalysisPartitionError) as development_error:
        AnalysisPartitionService().materialize_development(
            _store(frame), record, ["feature_a", "feature_b"]
        )
    with pytest.raises(AnalysisPartitionError) as validation_error:
        AnalysisPartitionService().materialize_validation(
            _store(frame), record, ["feature_a", "feature_b"]
        )

    assert development_error.value.code == ANALYSIS_PARTITION_INTEGRITY_FAILED
    assert validation_error.value.code == ANALYSIS_PARTITION_INTEGRITY_FAILED


def test_native_v2_target_authority_response_contract_is_unchanged():
    record = _sealed_record(_frame(), native_v2=True)

    authority = split_router._sealed_partition_target_authority(record)

    assert authority == {
        "target_contract_id": "target-contract-legacy",
        "target": "bad_flag",
        "problem_type": "classification",
        "event_value": 1,
        "non_event_value": 0,
        "source": "sealed_analysis_partition",
    }
