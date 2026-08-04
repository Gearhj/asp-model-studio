"""Focused proof that Validation Design reuses sealed pre-EDA membership."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import HTTPException

from server.splitting import split_router
from server.splitting.split_service import split_service
from server.core.dataset_store import DatasetStore
from server.core.result_store import ResultStore


def _population() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "feature": [float(value) for value in range(12)],
            "companion": [float(value % 3) for value in range(12)],
            "account_group": [f"group-{value // 2}" for value in range(12)],
            "bad_flag": [0, 1] * 6,
        },
        index=[f"row-{value}" for value in range(12)],
    )


def _sealed_membership(frame: pd.DataFrame):
    development_positions = [0, 1, 4, 5, 8, 9, 10, 11]
    holdout_positions = [2, 3, 6, 7]
    selected = ["feature", "companion"]
    return (
        frame.iloc[development_positions].loc[:, selected],
        frame.iloc[holdout_positions].loc[:, selected],
        frame.iloc[development_positions].loc[:, "bad_flag"],
        frame.iloc[holdout_positions].loc[:, "bad_flag"],
    )


def _config(**updates):
    config = {
        "split_strategy": "hybrid",
        "test_size": 0.2,
        "random_seed": 42,
        "problem_type": "classification",
        "event_value": 1,
        "stratify": True,
        "fold_method": "stratified_k_fold",
        "fold_count": 2,
        "repeats": 1,
        "shuffle": True,
        "balance_method": "none",
    }
    config.update(updates)
    return config


def test_validation_design_never_calls_outer_train_test_split_for_sealed_membership():
    frame = _population()
    development_X, holdout_X, development_y, holdout_y = _sealed_membership(frame)

    with patch(
        "server.splitting.split_service.train_test_split",
        side_effect=AssertionError("outer membership must not be redrawn"),
    ):
        result = split_service.make_validation_split(
            frame,
            "bad_flag",
            ["feature", "companion"],
            _config(),
            prepartitioned_development=development_X,
            prepartitioned_holdout=holdout_X,
            prepartitioned_development_target=development_y,
            prepartitioned_holdout_target=holdout_y,
        )

    assert result.training_index == development_y.index.tolist()
    assert result.validation_index == holdout_y.index.tolist()
    assert result.X_train.index.tolist() == development_X.index.tolist()
    assert result.X_test.index.tolist() == holdout_X.index.tolist()
    assert result.evaluation_population_role == "untouched_holdout"


def test_cross_validation_positions_are_owned_only_by_development_population():
    frame = _population()
    development_X, holdout_X, development_y, holdout_y = _sealed_membership(frame)
    result = split_service.make_validation_split(
        frame,
        "bad_flag",
        ["feature", "companion"],
        _config(),
        prepartitioned_development=development_X,
        prepartitioned_holdout=holdout_X,
        prepartitioned_development_target=development_y,
        prepartitioned_holdout_target=holdout_y,
    )

    for fold in result.fold_architecture["execution_splits"]:
        positions = fold["train_positions"] + fold["validation_positions"]
        assert positions
        assert min(positions) >= 0
        assert max(positions) < len(development_X)
    assert result.X_test.index.tolist() == holdout_X.index.tolist()


def test_holdout_targets_do_not_influence_design_policy_or_fold_local_balancing():
    frame = _population()
    development_X, holdout_X, development_y, holdout_y = _sealed_membership(frame)
    config = _config(
        balance_method="oversample",
        fold_local_preprocessing="fit_transform_per_fold",
    )
    baseline = split_service.make_validation_split(
        frame,
        "bad_flag",
        ["feature", "companion"],
        config,
        prepartitioned_development=development_X,
        prepartitioned_holdout=holdout_X,
        prepartitioned_development_target=development_y,
        prepartitioned_holdout_target=holdout_y,
    )
    altered_holdout = pd.Series(
        [1] * len(holdout_y),
        index=holdout_y.index,
        name=holdout_y.name,
    )
    altered = split_service.make_validation_split(
        frame,
        "bad_flag",
        ["feature", "companion"],
        config,
        prepartitioned_development=development_X,
        prepartitioned_holdout=holdout_X,
        prepartitioned_development_target=development_y,
        prepartitioned_holdout_target=altered_holdout,
    )

    assert baseline.training_index == altered.training_index
    assert baseline.validation_index == altered.validation_index
    assert baseline.fold_architecture == altered.fold_architecture
    assert baseline.original_train_distribution == altered.original_train_distribution
    assert baseline.applied_train_distribution == altered.applied_train_distribution
    assert baseline.test_distribution == altered.test_distribution == {
        "rows": len(holdout_y),
        "status": "sealed",
        "target_statistics_withheld": True,
    }
    assert baseline.X_train.index.tolist() == development_X.index.tolist()
    assert baseline.synthetic_rows_added == baseline.rows_removed == 0
    assert (
        baseline.balancing_application_status
        == "planned_fold_local_training_only"
    )


def test_fold_constraint_field_can_remain_outside_the_model_feature_set():
    frame = _population()
    development_positions = [0, 1, 4, 5, 8, 9, 10, 11]
    holdout_positions = [2, 3, 6, 7]
    constraint_fields = ["feature", "companion", "account_group"]
    result = split_service.make_validation_split(
        frame,
        "bad_flag",
        ["feature", "companion"],
        _config(
            fold_method="group_k_fold",
            group_field="account_group",
        ),
        prepartitioned_development=frame.iloc[development_positions].loc[
            :, constraint_fields
        ],
        prepartitioned_holdout=frame.iloc[holdout_positions].loc[
            :, constraint_fields
        ],
        prepartitioned_development_target=frame.iloc[
            development_positions
        ]["bad_flag"],
        prepartitioned_holdout_target=frame.iloc[holdout_positions][
            "bad_flag"
        ],
    )
    assert "account_group" not in result.X_train.columns
    assert result.fold_architecture["method"] == "group_k_fold"
    assert all(
        fold["validation_groups"]
        for fold in result.fold_architecture["folds"]
    )


def test_partial_prepartition_is_rejected_instead_of_falling_back_to_redraw():
    frame = _population()
    development_X, _, development_y, _ = _sealed_membership(frame)
    with pytest.raises(ValueError, match="must be supplied together"):
        split_service.make_validation_split(
            frame,
            "bad_flag",
            ["feature", "companion"],
            _config(),
            prepartitioned_development=development_X,
            prepartitioned_development_target=development_y,
        )


def test_validation_controls_must_equal_the_immutable_partition_contract():
    partition = {
        "analysis_partition_id": "analysis-partition-exact-r1",
        "revision": 1,
        "holdout_share": 0.2,
        "random_seed": 42,
        "stratification_policy": "target",
        "development_partition_id": "development-exact-r1",
        "sealed_holdout_partition_id": "holdout-exact-r1",
    }
    exact = split_router.SplitConfigPayload(
        project_id="project-exact",
        test_size=0.2,
        random_seed=42,
        stratify=True,
    )
    assert split_router._immutable_partition_mismatch(exact, partition) is None

    contradictory = exact.model_copy(
        update={"test_size": 0.3, "random_seed": 7, "stratify": False}
    )
    mismatch = split_router._immutable_partition_mismatch(
        contradictory,
        partition,
    )
    assert mismatch == {
        "holdout_share": {"requested": 0.3, "sealed": 0.2},
        "random_seed": {"requested": 7, "sealed": 42},
        "stratification": {"requested": False, "sealed": True},
    }


def test_validation_request_identity_is_stable_and_partition_revision_sensitive():
    identity = {
        "project_id": "project-exact",
        "dataset_id": "dataset-exact",
        "dataset_version_id": "version-exact",
    }
    partition = {
        "analysis_partition_id": "analysis-partition-exact-r1",
        "revision": 1,
        "development_partition_id": "development-exact-r1",
        "sealed_holdout_partition_id": "holdout-exact-r1",
    }
    kwargs = {
        "config": _config(),
        "selected_features": ["feature", "companion"],
        "identity": identity,
        "feature_manifest_version": "feature-manifest-exact",
        "partition": partition,
    }
    first = split_router._validation_request_hash(**kwargs)
    assert split_router._validation_request_hash(**kwargs) == first
    assert split_router._validation_request_hash(
        **{**kwargs, "partition": {**partition, "revision": 2}}
    ) != first


def test_repeated_identical_config_reuses_design_without_rematerializing_membership():
    frame = _population()
    development_X, holdout_X, development_y, holdout_y = _sealed_membership(frame)
    identity = {
        "project_id": "project-exact",
        "dataset_id": "dataset-exact",
        "dataset_version_id": "version-exact",
    }
    partition = {
        **identity,
        "analysis_partition_id": "analysis-partition-exact-r1",
        "revision": 1,
        "target_contract_id": "target-contract-exact",
        "target_column": "bad_flag",
        "positive_value_json": 1,
        "negative_value_json": 0,
        "predictor_authorization_id": "predictor-authorization-exact",
        "problem_type": "classification",
        "preview_fingerprint": "preview-fingerprint-exact",
        "development_partition_id": "development-exact-r1",
        "sealed_holdout_partition_id": "holdout-exact-r1",
        "development_share": 0.8,
        "holdout_share": 0.2,
        "random_seed": 42,
        "stratification_policy": "target",
        "stratification_field": "bad_flag",
        "final_holdout_status": "sealed",
        "holdout_isolation_status": "verified",
        "status": "current",
    }
    store = DatasetStore()
    store.set_raw(frame)
    store.set_target("bad_flag")
    store.meta.update(
        {
            **identity,
            "dataset_version": identity["dataset_version_id"],
            "dataset_identity_status": "current",
            "target_contract_id": "target-contract-exact",
            "predictor_authorization_id": "predictor-authorization-exact",
            "selected_columns": ["feature", "companion"],
            "feature_manifest": {
                **identity,
                "dataset_version": identity["dataset_version_id"],
                "manifest_hash": "feature-manifest-exact",
                "manifest_version": "feature-manifest-exact",
                "validation_status": "passed",
                "materialization_status": "current",
                "materialized_manifest_hash": "feature-manifest-exact",
                "confirmation_status": "confirmed",
                "confirmed_manifest_hash": "feature-manifest-exact",
                "features": [
                    {
                        "feature_name": name,
                        "selected": True,
                        "eligibility_status": "eligible",
                        "origin": "original",
                    }
                    for name in ("feature", "companion")
                ],
            },
        }
    )
    results = ResultStore()
    payload = split_router.SplitConfigPayload(
        project_id=identity["project_id"],
        split_strategy="hybrid",
        test_size=0.2,
        random_seed=42,
        stratify=True,
        problem_type="classification",
        event_value=1,
        selected_features=["feature", "companion"],
        feature_manifest_version="feature-manifest-exact",
        dataset_id=identity["dataset_id"],
        dataset_version_id=identity["dataset_version_id"],
        development_dataset_id=identity["dataset_id"],
        development_dataset_version_id=identity["dataset_version_id"],
        fold_method="stratified_k_fold",
        fold_count=2,
        fold_local_preprocessing="fit_transform_per_fold",
        balance_method="oversample",
        holdout_protection_confirmed=True,
        cv_design_approved=True,
        approval_note="Exact pre-EDA membership reuse.",
    )

    def assert_identity(*_args, **_kwargs):
        return dict(identity)

    populations = (development_X, holdout_X, development_y, holdout_y)
    with (
        patch.object(split_router, "DATASTORE", store),
        patch.object(split_router, "RESULTS", results),
        patch.object(split_router, "authorize_modeling_scope"),
        patch.object(split_router, "assert_expected_active_identity", side_effect=assert_identity),
        patch.object(split_router, "active_dataset_identity", return_value=dict(identity)),
        patch.object(split_router, "_current_analysis_partition", return_value=partition),
        patch.object(
            split_router.analysis_partition_service,
            "materialize_validation",
            return_value=populations,
        ) as materialize,
        patch.object(split_router, "audit_event"),
        patch.object(split_router, "schedule_checkpoint_save"),
        patch.object(
            split_router.split_service,
            "make_validation_split",
            wraps=split_router.split_service.make_validation_split,
        ) as make_split,
    ):
        first = split_router.balancing_split_config(
            payload,
            user={"userId": "user-exact", "displayName": "User"},
        )
        revision_after_first = store.data_revision
        second = split_router.balancing_split_config(
            payload,
            user={"userId": "user-exact", "displayName": "User"},
        )
        with pytest.raises(HTTPException) as contradictory:
            split_router.balancing_split_config(
                payload.model_copy(update={"event_value": 0}),
                user={"userId": "user-exact", "displayName": "User"},
            )

    assert first["split_id"] == second["split_id"]
    assert first["validation_design_id"] == second["validation_design_id"]
    assert store.data_revision == revision_after_first
    assert make_split.call_count == 1
    assert materialize.call_count == 1
    assert contradictory.value.status_code == 409
    assert contradictory.value.detail["code"] == (
        split_router.ANALYSIS_PARTITION_CONTRADICTORY
    )
    assert store.X_train.index.tolist() == development_X.index.tolist()
    assert store.X_test.index.tolist() == holdout_X.index.tolist()
    assert first["balancing_policy"]["method"] == "oversample"
    assert (
        first["balancing_policy"]["fold_local_resampling_status"]
        == "planned_fold_local_training_only"
    )
    assert first["balancing_policy"]["global_rows_changed"] == 0
    assert first["validation_design"]["fold_local_preprocessing"] == (
        "fit_transform_per_fold"
    )
    assert first["problem_type"] == "classification"
    assert first["event_value"] == 1
    assert first["negative_value"] == 0
    assert first["non_event_value"] == 0
    assert first["target_contract_id"] == "target-contract-exact"
    assert first["validation_design"]["target_definition"] == {
        "target": "bad_flag",
        "target_contract_id": "target-contract-exact",
        "problem_type": "classification",
        "positive_value": 1,
        "negative_value": 0,
        "authority_source": "sealed_analysis_partition",
    }
    assert first["distributions"]["holdout_untouched"] == {
        "rows": len(holdout_y),
        "status": "sealed",
        "target_statistics_withheld": True,
    }
    assert "full_dataset" not in first["distributions"]
