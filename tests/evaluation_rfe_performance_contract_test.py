from __future__ import annotations

from pathlib import Path
import sys
import time

import numpy as np
import pandas as pd
import pytest


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.core.dataset_store import DATASTORE
from server.evaluation.eval_service import EvaluationService


def test_classification_rfe_uses_one_fit_per_feature_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The browser's 30-second RFE budget must not hide quadratic refits."""

    rng = np.random.default_rng(20260808)
    feature_names = [f"feature_{index:02d}" for index in range(14)]
    train_values = rng.normal(size=(1_200, len(feature_names)))
    X_train = pd.DataFrame(train_values, columns=feature_names)
    signal = (
        1.4 * X_train["feature_00"]
        - 1.0 * X_train["feature_01"]
        + 0.7 * X_train["feature_02"]
        + rng.normal(scale=0.8, size=len(X_train))
    )
    y_train = pd.Series((signal > float(signal.median())).astype(int), name="target")

    # Deliberately unrelated final-holdout values. The production method must
    # derive its own internal validation slice exclusively from X_train/y_train.
    X_holdout = pd.DataFrame(
        rng.normal(loc=100.0, scale=20.0, size=(160, len(feature_names))),
        columns=feature_names,
    )
    y_holdout = pd.Series([index % 2 for index in range(len(X_holdout))], name="target")

    service = EvaluationService()
    monkeypatch.setattr(service, "_artifact_context_mismatch", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "_is_regression_problem", lambda: False)

    fit_calls = 0
    original_fit = service._score_and_rank_feature_subset

    def counted_fit(*args, **kwargs):
        nonlocal fit_calls
        fit_calls += 1
        return original_fit(*args, **kwargs)

    monkeypatch.setattr(service, "_score_and_rank_feature_subset", counted_fit)

    DATASTORE.reset_all()
    DATASTORE.set_splits(X_train, X_holdout, y_train, y_holdout)
    started = time.perf_counter()
    try:
        result = service.rfe(
            "candidate-rfe-performance",
            keep=8,
            context={"problem_type": "classification"},
        )
    finally:
        DATASTORE.reset_all()
    elapsed = time.perf_counter() - started

    assert result["ok"] is True, result
    assert result["selection_population"] == "training_internal_validation"
    assert result["holdout_used"] is False
    assert result["rfe_search_strategy"] == "coefficient_guided_backward_elimination"
    assert result["rfe_screening_fit_count"] == 0
    assert result["rfe_path_fit_count"] == len(feature_names)
    assert result["rfe_fit_count"] == len(feature_names)
    assert result["rfe_fit_count_bound"] == len(feature_names)
    assert fit_calls == len(feature_names)
    assert len(result["curve"]) == len(feature_names)
    assert {row["feature_count"] for row in result["curve"]} == set(
        range(1, len(feature_names) + 1)
    )
    assert len(result["rows"]) == len(feature_names)
    assert elapsed < 30.0

