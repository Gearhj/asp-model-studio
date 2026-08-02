from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.model_selection import StratifiedKFold


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.training import trainer  # noqa: E402
from server.training.candidate_contract import (  # noqa: E402
    assert_candidate_contract_intact,
    build_candidate_contract,
    classify_selection_integrity,
    complete_training_contract,
)
from server.training.training_job_service import TrainingJobService  # noqa: E402


FIXED_TIME = "2026-07-31T12:00:00+00:00"


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
            "preprocessing_pipeline": [],
            "split_id": "split-1",
            "validation_design_id": "design-1",
            "validation_design_version": "design-version-1",
            "training_population_id": "population-train-1",
            "selection_partition_id": "population-train-1",
            "holdout_population_id": "population-holdout-1",
            "final_holdout_partition_id": "population-holdout-1",
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
        store_meta={},
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
        def fit(self, X, y=None):
            fit_indices.append(tuple(int(value) for value in X.index))
            return self

        def transform(self, X):
            return np.asarray(X, dtype=float)

    frame, target, folds = _development_population()
    with patch.object(trainer, "_make_preprocessor", return_value=RecordingTransformer()):
        result = _train(X_train=frame, y_train=target, cv_splits=folds)
    assert result["ok"]
    assert len(fit_indices) == len(folds) + 1
    for observed, (train_positions, _) in zip(fit_indices[:-1], folds):
        assert observed == tuple(int(value) for value in frame.iloc[train_positions].index)
    assert fit_indices[-1] == tuple(int(value) for value in frame.index)


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
