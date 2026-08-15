from __future__ import annotations

from threading import Event
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.model_selection import StratifiedKFold

from server.training import trainer as trainer_module
from server.training import training_job_service as job_module
from server.preprocessing.execution_contract import default_no_treatment_contract
from server.training.trainer import train_models
from server.training.training_job_service import (
    TrainingJobService,
    _governed_validation_execution_policy,
)
from server.training.training_job_types import TrainingJobRequest


def _development_data() -> tuple[pd.DataFrame, pd.Series, list[tuple[list[int], list[int]]]]:
    frame = pd.DataFrame(
        {
            "numeric": np.arange(40, dtype=float),
            "category": ["a", "b", "c", "a", "b"] * 8,
        }
    )
    target = pd.Series(([0] * 4 + [1]) * 8, name="bad_flag")
    folds = [
        (train.tolist(), validation.tolist())
        for train, validation in StratifiedKFold(
            n_splits=4,
            shuffle=True,
            random_state=17,
        ).split(frame, target)
    ]
    return frame, target, folds


def _policy(**changes: object) -> dict[str, object]:
    result: dict[str, object] = {
        "source": "approved_validation_design",
        "fold_local_preprocessing": "fit_transform_per_fold",
        "balancing_method": "none",
        "minority_share": 0.4,
        "class_weight_policy": "none",
        "random_seed": 19,
    }
    result.update(changes)
    return result


def _preprocessing_recipe() -> dict[str, object]:
    return default_no_treatment_contract(
        feature_names=["numeric", "category"]
    )


def _train(
    *,
    policy: dict[str, object],
    model_params: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    frame, target, folds = _development_data()
    return train_models(
        X_train=frame,
        y_train=target,
        requested_models=["logreg"],
        cv_splits=folds,
        primary_metric="roc_auc",
        positive_class=1,
        selection_partition_id="development-only",
        fold_definition_id="governed-folds-v1",
        model_params=model_params,
        validation_policy=policy,
        preprocessing_recipe=_preprocessing_recipe(),
    )


def test_fold_local_preprocessing_fits_each_training_fold_and_never_a_holdout() -> None:
    observed_fit_values: list[set[float]] = []

    class SpyPreprocessor(BaseEstimator, TransformerMixin):
        def __init__(self, **kwargs: object):
            self.kwargs = kwargs

        def fit(self, X: pd.DataFrame, y: object = None):
            observed_fit_values.append(set(pd.to_numeric(X["numeric"])))
            self.preprocessing_artifact_ = {
                "artifact_checksum": f"mock-{len(observed_fit_values)}"
            }
            return self

        def transform(self, X: pd.DataFrame) -> np.ndarray:
            return pd.to_numeric(X["numeric"]).to_numpy(dtype=float).reshape(-1, 1)

        def fitted_artifact(self, **kwargs: object) -> dict[str, object]:
            return {**self.preprocessing_artifact_, **kwargs}

    development, _target, folds = _development_data()
    holdout_sentinel = 999_999.0
    with patch.object(
        trainer_module,
        "_make_preprocessor",
        side_effect=lambda *_args, **kwargs: SpyPreprocessor(**kwargs),
    ):
        result = _train(policy=_policy())

    assert result["ok"] is True
    # Four governed fold fits plus one final development-only fit.
    assert len(observed_fit_values) == 5
    for (train_positions, _), observed in zip(folds, observed_fit_values[:4]):
        assert observed == set(development.iloc[train_positions]["numeric"])
        assert holdout_sentinel not in observed
    assert observed_fit_values[-1] == set(development["numeric"])
    assert holdout_sentinel not in observed_fit_values[-1]


@pytest.mark.parametrize("method", ["undersample", "oversample", "smote"])
def test_each_fold_local_resampling_method_changes_training_rows_only(
    method: str,
) -> None:
    result = _train(
        policy=_policy(
            balancing_method=method,
            class_weight_policy="balanced",
        )
    )

    assert result["ok"] is True
    execution = result["summary"]["ranked"][0]["validation_policy_execution"]
    assert execution["balancing_method"] == method
    assert execution["class_weight_policy"] == "balanced"
    assert execution["final_holdout_access"] == "none"
    assert len(execution["folds"]) == 4
    for fold in execution["folds"]:
        if method == "undersample":
            assert fold["resampling"]["output_rows"] < fold["resampling"]["input_rows"]
            assert fold["resampling"]["rows_removed"] > 0
        else:
            assert fold["resampling"]["output_rows"] > fold["resampling"]["input_rows"]
            assert fold["resampling"]["synthetic_rows_added"] > 0
        assert fold["validation_rows_resampled"] is False
        assert fold["resampling"]["validation_rows_resampled"] is False
        assert fold["resampling"]["final_holdout_access"] == "none"


def test_governed_class_weight_overrides_browser_model_parameter() -> None:
    balanced = _train(
        policy=_policy(class_weight_policy="balanced"),
        model_params={"logreg": {"class_weight": None}},
    )
    balanced_model = balanced["summary"]["_artifacts"]["logreg"]
    assert balanced_model.named_steps["model"].class_weight == "balanced"
    balanced_execution = balanced["summary"]["ranked"][0][
        "validation_policy_execution"
    ]
    assert all(
        fold["class_weights"]["execution"] == "estimator_class_weight"
        for fold in balanced_execution["folds"]
    )

    unweighted = _train(
        policy=_policy(class_weight_policy="none"),
        model_params={"logreg": {"class_weight": "balanced"}},
    )
    unweighted_model = unweighted["summary"]["_artifacts"]["logreg"]
    assert unweighted_model.named_steps["model"].class_weight is None


def test_model_native_policy_executes_governed_recipe_without_encoding_or_scaling() -> None:
    frame, target, folds = _development_data()
    numeric_frame = frame[["numeric"]]
    observed: list[dict[str, object]] = []

    class NativeSpy(BaseEstimator, TransformerMixin):
        def __init__(self, **kwargs: object):
            self.kwargs = kwargs

        def fit(self, X: pd.DataFrame, y: object = None):
            observed.append(dict(self.kwargs))
            self.preprocessing_artifact_ = {
                "artifact_checksum": f"native-{len(observed)}"
            }
            return self

        def transform(self, X: pd.DataFrame) -> pd.DataFrame:
            return X.copy()

        def fitted_artifact(self, **kwargs: object) -> dict[str, object]:
            return {**self.preprocessing_artifact_, **kwargs}

    with patch.object(
        trainer_module,
        "_make_preprocessor",
        side_effect=lambda *_args, **kwargs: NativeSpy(**kwargs),
    ):
        result = train_models(
            X_train=numeric_frame,
            y_train=target,
            requested_models=["logreg"],
            cv_splits=folds,
            primary_metric="roc_auc",
            positive_class=1,
            selection_partition_id="development-only",
            fold_definition_id="governed-folds-v1",
            validation_policy=_policy(
                fold_local_preprocessing="model_native_per_fold"
            ),
            preprocessing_recipe=default_no_treatment_contract(
                feature_names=["numeric"]
            ),
        )

    assert result["ok"] is True
    execution = result["summary"]["ranked"][0]["validation_policy_execution"]
    assert all(
        fold["preprocessing_execution"] == "governed_recipe_model_native_matrix"
        for fold in execution["folds"]
    )
    assert len(observed) == len(folds) + 1
    assert all(item.get("encode_and_scale") is False for item in observed)
    assert execution["final_holdout_access"] == "none"


def test_job_worker_passes_only_approved_validation_design_policy() -> None:
    service = TrainingJobService()
    job_id = "isolated-policy-job"
    captured: dict[str, object] = {}
    service._jobs[job_id] = {
        "preflight": {
            "cross_validation_compatibility": {"effective_folds": 2},
            "calibration_compatibility": {"logreg": {"compatible": True}},
        },
        "selection_partition_id": "development-only",
        "fold_definition_id": "folds-v1",
        "selection_resampling_status": "not_applied",
        "event_value": 1,
        "_cv_execution_splits": [([0, 1], [2, 3]), ([2, 3], [0, 1])],
        "_validation_execution_policy": _policy(
            balancing_method="undersample",
            class_weight_policy="balanced",
            random_seed=73,
        ),
    }
    service._cancel_events[job_id] = Event()
    request = TrainingJobRequest(
        project_id="isolated-project",
        models=["logreg"],
        k_folds=2,
        # Adversarial/stale browser claim: the worker must ignore this and use
        # the frozen governed job authority above.
        event_value=0,
        random_seed=999,
        model_params={"logreg": {"class_weight": None}},
    )

    def capture_train_models(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"ok": True, "summary": {"ranked": []}}

    with patch.object(service, "_transition_model"), patch.object(
        job_module, "train_models", side_effect=capture_train_models
    ):
        service._train_one(
            job_id,
            "logreg",
            request,
            pd.DataFrame({"x": [0.0, 1.0, 2.0, 3.0]}),
            pd.Series([0, 1, 0, 1]),
        )

    assert captured["validation_policy"] == service._jobs[job_id][
        "_validation_execution_policy"
    ]
    assert captured["validation_policy"]["random_seed"] == 73
    assert captured["validation_policy"]["balancing_method"] == "undersample"
    assert captured["validation_policy"]["class_weight_policy"] == "balanced"
    assert captured["positive_class"] == 1
    assert captured["X_train"].shape[0] == 4
    assert "X_test" not in captured and "y_test" not in captured


def test_policy_snapshot_rejects_contradictory_or_global_resampling() -> None:
    base = {
        "validation_design_id": "design-v1",
        "validation_design_version": "version-v1",
        "fold_definition_id": "folds-v1",
        "validation_design": {
            "fold_local_preprocessing": "fit_transform_per_fold"
        },
        "cv_design": {
            "fold_local_preprocessing": "model_native_per_fold",
            "random_seed": 23,
        },
        "balancing_configuration": {
            "method": "none",
            "class_weight_policy": "none",
            "selection_resampling_status": "not_applied",
        },
    }
    with pytest.raises(ValueError, match="contradictory"):
        _governed_validation_execution_policy(base)

    globally_resampled = {
        **base,
        "cv_design": {
            "fold_local_preprocessing": "fit_transform_per_fold",
            "random_seed": 23,
        },
        "balancing_configuration": {
            "method": "oversample",
            "minority_share": 0.4,
            "class_weight_policy": "none",
            "fold_local_resampling_status": "planned_fold_local_training_only",
            "selection_resampling_status": "applied",
        },
    }
    with pytest.raises(ValueError, match="population-level"):
        _governed_validation_execution_policy(globally_resampled)
