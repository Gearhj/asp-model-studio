from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from server.sports_gold import binary_hierarchical as B
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


def test_batter_retired_contract_is_exact_and_other_reach_is_not_retired() -> None:
    contract = B.target_contract()
    assert contract["classOrder"] == list(PA_CLASS_ORDER)
    assert contract["outClasses"] == ["STRIKEOUT", "BIP_OUT"]
    assert contract["notOutClasses"] == [
        "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "OTHER_REACH"
    ]
    assert contract["otherReachSemantics"]["batterRetired"] is False
    assert contract["otherReachSemantics"]["retrosheetTerminalTokens"] == ["roe", "fc"]


def test_collapsed_probability_uses_only_exact_out_columns() -> None:
    matrix = np.asarray(
        [
            [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.09, 0.16],
            [0.20, 0.10, 0.05, 0.15, 0.10, 0.05, 0.25, 0.10],
        ],
        dtype=np.float64,
    )
    matrix = validate_probability_matrix(matrix)
    collapsed = B.collapsed_out_probability(matrix)
    assert np.array_equal(collapsed, np.asarray([0.19, 0.45]))
    labels = B.binary_labels(np.asarray(["STRIKEOUT", "OTHER_REACH", "BIP_OUT"]))
    assert np.array_equal(labels, np.asarray([1, 0, 1], dtype=np.int8))


def test_reconstruction_preserves_group_ratios_and_probability_contract() -> None:
    direct = validate_probability_matrix(
        np.asarray(
            [
                [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.09, 0.16],
                [0.20, 0.10, 0.05, 0.15, 0.10, 0.05, 0.25, 0.10],
            ],
            dtype=np.float64,
        )
    )
    rebuilt, proof = B.reconstruct_eight_class_probabilities(direct, [0.40, 0.30])
    assert np.allclose(rebuilt.sum(axis=1), 1.0, rtol=0.0, atol=1e-12)
    assert np.allclose(rebuilt[:, [0, 6]].sum(axis=1), [0.40, 0.30])
    assert proof["maxWithinGroupRatioDifference"] <= 2e-15
    assert proof["classOrder"] == list(PA_CLASS_ORDER)


def test_reconstruction_accepts_exact_binary_endpoint_probabilities() -> None:
    direct = validate_probability_matrix(
        np.asarray(
            [
                [0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.09, 0.16],
                [0.20, 0.10, 0.05, 0.15, 0.10, 0.05, 0.25, 0.10],
            ],
            dtype=np.float64,
        )
    )
    rebuilt, proof = B.reconstruct_eight_class_probabilities(direct, [0.0, 1.0])
    assert np.all(rebuilt[0, [0, 6]] == 0.0)
    assert np.all(rebuilt[1, [1, 2, 3, 4, 5, 7]] == 0.0)
    assert proof["zeroOutMassRows"] == 1
    assert proof["zeroNotOutMassRows"] == 1
    assert math.isfinite(proof["maxWithinGroupRatioDifference"])


def test_binary_metrics_match_hand_calculation() -> None:
    labels = np.asarray([0, 0, 1, 1], dtype=np.int8)
    probabilities = np.asarray([0.1, 0.2, 0.8, 0.9], dtype=np.float64)
    metrics = B.evaluate_binary(labels, probabilities)
    expected_log_loss = -0.5 * (math.log(0.9) + math.log(0.8))
    assert metrics["binaryLogLoss"] == pytest.approx(expected_log_loss)
    assert metrics["brierScore"] == pytest.approx(0.025)
    assert metrics["ece"] == pytest.approx(0.15)
    assert metrics["rocAuc"] == 1.0
    assert metrics["prAuc"] == 1.0
    assert metrics["accuracy"] == 1.0


def test_dedicated_binary_fit_uses_supplied_development_and_validation_masks() -> None:
    values = np.linspace(-2.0, 2.0, 80)
    frame = pd.DataFrame({"numeric_feature": values})
    development = np.zeros(80, dtype=np.bool_)
    development[:56] = True
    validation = ~development
    labels = (np.arange(80) % 2).astype(np.int8)
    record, artifact, probabilities = B._fit_binary_candidate(
        model_id="fixture_binary_logistic",
        label="Fixture binary Logistic",
        frame=frame,
        development_mask=development,
        validation_mask=validation,
        labels=labels,
        feature_names=("numeric_feature",),
        config={"fixture": True},
        estimator_factory=B._logistic_factory,
    )
    assert record["status"] == "SUCCESS"
    assert record["developmentRows"] == 56
    assert record["validationRows"] == 24
    assert artifact is not None
    assert probabilities is not None and probabilities.shape == (24,)
