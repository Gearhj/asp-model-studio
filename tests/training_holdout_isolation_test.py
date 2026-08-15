from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.model_selection import StratifiedKFold


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.training import trainer  # noqa: E402
from server.analysis_partition.service import AnalysisPartitionService  # noqa: E402
from server.analysis_partition.types import AnalysisPartitionError  # noqa: E402
from server.preprocessing.execution_contract import (  # noqa: E402
    default_no_treatment_contract,
    extract_final_preprocessing_artifact,
    validate_final_preprocessing_artifact,
)
from server.training.candidate_contract import (  # noqa: E402
    assert_candidate_contract_intact,
    build_candidate_contract,
    classify_selection_integrity,
    complete_training_contract,
)
from server.training.training_job_service import TrainingJobService  # noqa: E402


FIXED_TIME = "2026-07-31T12:00:00+00:00"


def _preprocessing_policy() -> dict[str, object]:
    return default_no_treatment_contract(
        identity={
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
            "analysis_partition_id": "partition-1",
            "analysis_partition_revision": 1,
        },
        feature_names=["first", "second"],
    )


def _development_population() -> tuple[pd.DataFrame, pd.Series, list[tuple[list[int], list[int]]]]:
    rng = np.random.default_rng(42)
    rows = 72
    first = rng.normal(size=rows)
    second = rng.normal(size=rows)
    target = (first + 0.3 * second + rng.normal(scale=0.5, size=rows) > 0).astype(int)
    frame = pd.DataFrame(
        {"first": first, "second": second},
        index=np.arange(1000, 1000 + rows),
    )
    series = pd.Series(target, name="event", index=frame.index)
    folds = [
        (train.tolist(), validation.tolist())
        for train, validation in StratifiedKFold(
            n_splits=3, shuffle=True, random_state=19
        ).split(frame, series)
    ]
    return frame, series, folds


def _train(**overrides):
    frame, target, folds = _development_population()
    kwargs = {
        "X_train": frame,
        "y_train": target,
        "requested_models": ["logreg"],
        "cv_folds": 3,
        "cv_splits": folds,
        "primary_metric": "pr_auc",
        "positive_class": 1,
        "selection_partition_id": "population-train-1",
        "fold_definition_id": "fold-definition-1",
        "selection_created_at": FIXED_TIME,
        "balancing_status": "not_applied",
        "preprocessing_recipe": _preprocessing_policy(),
    }
    kwargs.update(overrides)
    return trainer.train_models(**kwargs)


def _training_contract():
    return complete_training_contract(
        {
            "project_id": "project-1",
            "dataset_id": "dataset-1",
            "dataset_version_id": "version-1",
            "target": "event",
            "problem_type": "classification",
            "event_value": 1,
            "non_event_value": 0,
            "feature_manifest_version": "feature-hash-1",
            "selected_original_features": ["first", "second"],
            "selected_engineered_features": [],
            "preprocessing_policy": _preprocessing_policy(),
            "analysis_partition_id": "partition-1",
            "analysis_partition_revision": 1,
            "split_id": "split-1",
            "validation_design_id": "design-1",
            "validation_design_version": "design-version-1",
            "training_population_id": "population-train-1",
            "training_population_rows": 72,
            "selection_partition_id": "population-train-1",
            "holdout_population_id": "population-holdout-1",
            "final_holdout_partition_id": "population-holdout-1",
            "final_holdout_population_rows": 18,
            "fold_definition_id": "fold-definition-1",
            "final_holdout_status": "sealed",
            "holdout_isolation_status": "verified",
            "selection_resampling_status": "not_applied",
            "random_seed": 42,
            "calibration_configuration": {"requested": False},
            "runtime_environment": {"requested_workers": 1, "honored_workers": 1},
        },
        feature_manifest={
            "manifest_id": "feature-manifest-1",
            "manifest_hash": "feature-hash-1",
        },
        store_meta={"preprocessing_policy": _preprocessing_policy()},
        training_job_id="train-job-1",
        training_run_id="train-run-1",
        created_by="user-1",
        created_at=FIXED_TIME,
        primary_metric="pr_auc",
    )


def test_training_boundaries_have_no_final_holdout_arguments() -> None:
    for callable_object in (
        trainer.train_models,
        trainer._train_classification_model,
        trainer._train_regression_model,
        trainer._train_anomaly_model,
        TrainingJobService._run,
        TrainingJobService._train_one,
        TrainingJobService._finalize,
    ):
        parameters = set(inspect.signature(callable_object).parameters)
        assert "X_test" not in parameters
        assert "y_test" not in parameters


def test_oof_selection_is_deterministic_and_contains_no_holdout_payload() -> None:
    first = _train()
    second = _train()
    assert first["ok"] and second["ok"]
    first_row = first["summary"]["ranked"][0]
    second_row = second["summary"]["ranked"][0]
    assert first_row["selection_metric"] == second_row["selection_metric"]
    assert first_row["selection_metric"]["selection_metric_name"] == "pr_auc"
    assert first_row["selection_metric"]["selection_metric_source"] == "out_of_fold"
    assert first_row["selection_metric"]["threshold_source"] == "platform_governed_default_0_5"
    assert first_row["selection_integrity_status"] == "verified"
    assert first_row["holdout_isolation_status"] == "verified"
    raw = first["summary"]["raw"]["logreg"]
    assert "y_true" not in raw and "y_score" not in raw
    assert len(raw["oof_y_true"]) == len(raw["oof_y_score"])


def test_preprocessing_is_fitted_inside_each_governed_fold() -> None:
    fit_indices: list[tuple[int, ...]] = []

    class RecordingTransformer(BaseEstimator, TransformerMixin):
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fit(self, X, y=None):
            fit_indices.append(tuple(int(value) for value in X.index))
            self.preprocessing_artifact_ = {
                "artifact_checksum": f"mock-{len(fit_indices)}"
            }
            return self

        def transform(self, X):
            return np.asarray(X, dtype=float)

        def fitted_artifact(self, **kwargs):
            return {**self.preprocessing_artifact_, **kwargs}

    frame, target, folds = _development_population()
    with patch.object(
        trainer,
        "_make_preprocessor",
        side_effect=lambda *_args, **kwargs: RecordingTransformer(**kwargs),
    ):
        result = _train(X_train=frame, y_train=target, cv_splits=folds)
    assert result["ok"]
    # Governed CV owns one fit per fold.  The extra whole-Development fit is a
    # pre-lock diagnostic candidate, never the final reporting artifact.
    assert len(fit_indices) == len(folds) + 1
    for observed, (train_positions, _) in zip(fit_indices[:-1], folds):
        assert observed == tuple(int(value) for value in frame.iloc[train_positions].index)
    assert fit_indices[-1] == tuple(int(value) for value in frame.index)


def test_locked_candidate_gets_distinct_final_development_fit_and_fixed_holdout_application() -> None:
    frame, target, _folds = _development_population()
    trained = _train()
    assert trained["ok"] is True
    row = trained["summary"]["ranked"][0]
    contract = build_candidate_contract(
        _training_contract(),
        algorithm_id="logreg",
        candidate_metrics=row,
        artifact=trained["summary"]["_artifacts"]["logreg"],
        created_at="2026-07-31T12:05:00+00:00",
    )
    row = {
        **row,
        "candidate_id": contract["candidate_id"],
        "training_job_id": contract["training_job_id"],
        "training_run_id": contract["training_run_id"],
        "candidate_contract": contract,
    }
    holdout = pd.DataFrame(
        {"first": [10_000.0, -10_000.0], "second": [3.0, -3.0]}
    )
    final_model, final_record = trainer.fit_final_development_candidate(
        candidate_artifact=trained["summary"]["_artifacts"]["logreg"],
        candidate_row=row,
        X_development=frame,
        y_development=target,
        preprocessing_recipe=_preprocessing_policy(),
        fit_population_id="population-train-1",
        application_population_id="population-holdout-1",
        application_population_rows=18,
        actor="user-1",
        candidate_decision_id="decision-1",
    )
    validated = validate_final_preprocessing_artifact(
        final_record,
        contract,
        candidate_decision_id="decision-1",
    )
    assert validated["fit_scope"] == "final_development"
    assert validated["fit_population_rows"] == len(frame)
    assert validated["application_population_rows"] == 18
    assert validated["final_holdout_parameter_influence"] is False
    embedded = extract_final_preprocessing_artifact(final_model)
    assert embedded == validated

    checksum = validated["final_artifact_checksum"]
    preprocessor = final_model.named_steps["preprocess"]
    _ = preprocessor.transform(holdout)
    assert preprocessor.preprocessing_artifact_["final_artifact_checksum"] == checksum
    assert preprocessor.last_application_["refit_during_application"] is False

    holdout_population = pd.DataFrame(
        {
            "first": np.linspace(-50_000.0, 50_000.0, 18),
            "second": np.linspace(8_000.0, -8_000.0, 18),
            "event": [0, 1] * 9,
        },
        index=np.arange(2000, 2018),
    )
    governed_full = pd.concat(
        [frame.assign(event=target), holdout_population], axis=0
    )
    record = {
        "analysis_partition_id": "partition-1",
        "revision": 1,
        "project_id": "project-1",
        "dataset_id": "dataset-1",
        "dataset_version_id": "version-1",
        "target": "event",
        "row_assignments_json": {
            "holdout_positions": list(range(len(frame), len(governed_full))),
            "holdout_target_fingerprint": "sealed-target-membership",
        },
    }
    boundary = AnalysisPartitionService()
    with (
        patch.object(
            boundary,
            "target_authority_compatibility",
            return_value={"lineage_contract": "analysis_partition_v2"},
        ),
        patch.object(
            boundary,
            "_validate_frame_structure",
            return_value=(governed_full, "event"),
        ),
        patch(
            "server.analysis_partition.service._authorized_predictors",
            return_value=["first", "second"],
        ),
        patch(
            "server.analysis_partition.service._target_membership_fingerprint",
            return_value="sealed-target-membership",
        ),
    ):
        with pytest.raises(AnalysisPartitionError):
            boundary.materialize_final_holdout(
                object(),
                record,
                ["first", "second"],
                candidate_decision_id="",
                final_preprocessing_artifact=validated,
            )
        opened_X, opened_y = boundary.materialize_final_holdout(
            object(),
            record,
            ["first", "second"],
            candidate_decision_id="decision-1",
            final_preprocessing_artifact=validated,
        )

    assert len(opened_X) == 18
    assert len(opened_y) == 18
    before_parameters = preprocessor.preprocessing_artifact_[
        "encoding_scaling_parameters"
    ]
    _ = preprocessor.transform(opened_X)
    assert (
        preprocessor.preprocessing_artifact_["encoding_scaling_parameters"]
        == before_parameters
    )
    assert preprocessor.last_application_["refit_during_application"] is False
    assert validated["final_holdout_parameter_influence"] is False


def test_candidate_contract_hashes_selection_and_encoding_provenance() -> None:
    result = _train()
    row = result["summary"]["ranked"][0]
    contract = build_candidate_contract(
        _training_contract(),
        algorithm_id="logreg",
        candidate_metrics=row,
        artifact=result["summary"]["_artifacts"]["logreg"],
        created_at="2026-07-31T12:05:00+00:00",
    )
    assert_candidate_contract_intact(contract)
    assert contract["selection_metric"] == row["selection_metric"]
    assert contract["class_encoding"]["class_labels"] == ["0", "1"]
    assert contract["class_encoding"]["positive_class_index"] == 1
    assert contract["threshold_configuration"]["selection_threshold_tuned"] is False


def test_calibration_provenance_is_fold_local_and_never_holdout_derived() -> None:
    result = _train(calibrate=True)
    assert result["ok"]
    metric = result["summary"]["ranked"][0]["selection_metric"]
    assert metric["calibration_source"] == "fold_local_training_cross_validation"
    assert "holdout" not in metric["calibration_source"]


def test_legacy_and_contaminated_selection_records_remain_classified() -> None:
    assert classify_selection_integrity({"candidate_id": "legacy"}) == "legacy_unresolved"
    assert (
        classify_selection_integrity(
            {
                "selection_metric": {
                    "selection_metric_source": "final_holdout",
                    "selection_partition_id": "holdout-1",
                    "fold_definition_id": "none",
                },
                "selection_integrity_status": "invalid_final_holdout_ranking",
                "holdout_isolation_status": "invalid",
            }
        )
        == "invalid_final_holdout_ranking"
    )
