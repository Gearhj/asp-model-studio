from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.metrics import precision_recall_fscore_support


PA_CLASS_ORDER: tuple[str, ...] = (
    "STRIKEOUT",
    "WALK_HBP_CI",
    "HOME_RUN",
    "SINGLE",
    "DOUBLE",
    "TRIPLE",
    "BIP_OUT",
    "OTHER_REACH",
)

METRICS_SCHEMA_VERSION = "MLB_PA_METRICS_V1"
DEFAULT_CALIBRATION_BINS = 10
PROBABILITY_SUM_TOLERANCE = 1e-10
PROBABILITY_EPSILON = np.finfo(np.float64).eps


def require_frozen_class_order(class_order: Sequence[str]) -> tuple[str, ...]:
    """Reject any probability-vector order other than the immutable MLB order."""

    observed = tuple(class_order)
    if observed != PA_CLASS_ORDER:
        raise ValueError(
            "class_order must exactly match the frozen MLB plate-appearance order"
        )
    return observed


def validate_probability_matrix(
    probabilities: Any,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
) -> np.ndarray:
    """Return a validated float64 probability matrix without renormalizing it."""

    order = require_frozen_class_order(class_order)
    raw = np.asarray(probabilities)
    if raw.dtype.kind not in "fiu":
        raise TypeError("probabilities must contain numeric values")
    values = np.array(raw, dtype=np.float64, order="C", copy=True)
    if values.ndim != 2:
        raise ValueError("probabilities must be a two-dimensional matrix")
    if values.shape[0] == 0:
        raise ValueError("probabilities must contain at least one row")
    if values.shape[1] != len(order):
        raise ValueError(
            f"probabilities must have exactly {len(order)} columns in frozen class order"
        )
    if not np.isfinite(values).all():
        raise ValueError("probabilities must contain only finite values")
    if np.any(values < 0.0) or np.any(values > 1.0):
        raise ValueError("probabilities must remain within [0, 1]")
    row_sums = values.sum(axis=1)
    if not np.allclose(
        row_sums,
        np.ones(values.shape[0], dtype=np.float64),
        rtol=0.0,
        atol=PROBABILITY_SUM_TOLERANCE,
    ):
        raise ValueError("every probability row must sum to one within tolerance")
    return values


def encode_labels(
    labels: Any,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
) -> np.ndarray:
    """Encode frozen-order string labels or validate integer class indices."""

    order = require_frozen_class_order(class_order)
    raw = np.asarray(labels)
    if raw.ndim != 1:
        raise ValueError("labels must be one-dimensional")
    if raw.size == 0:
        raise ValueError("labels must contain at least one row")

    items = raw.tolist()
    if all(isinstance(value, (str, np.str_)) for value in items):
        index = {name: position for position, name in enumerate(order)}
        unknown = sorted({str(value) for value in items if str(value) not in index})
        if unknown:
            raise ValueError(f"labels contain unknown classes: {unknown}")
        return np.asarray([index[str(value)] for value in items], dtype=np.int64)

    if all(
        isinstance(value, (int, np.integer))
        and not isinstance(value, (bool, np.bool_))
        for value in items
    ):
        encoded = np.asarray(items, dtype=np.int64)
        if np.any(encoded < 0) or np.any(encoded >= len(order)):
            raise ValueError("integer labels must be valid frozen-order class indices")
        return encoded

    raise TypeError("labels must be uniformly strings or non-boolean integer indices")


def validate_evaluation_inputs(
    labels: Any,
    probabilities: Any,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
) -> tuple[np.ndarray, np.ndarray]:
    encoded = encode_labels(labels, class_order=class_order)
    matrix = validate_probability_matrix(probabilities, class_order=class_order)
    if encoded.shape[0] != matrix.shape[0]:
        raise ValueError("labels and probabilities must contain the same number of rows")
    return encoded, matrix


def per_row_log_loss(
    labels: Any,
    probabilities: Any,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
) -> np.ndarray:
    encoded, matrix = validate_evaluation_inputs(
        labels, probabilities, class_order=class_order
    )
    selected = matrix[np.arange(encoded.size), encoded]
    return -np.log(np.clip(selected, PROBABILITY_EPSILON, 1.0))


def per_row_brier_score(
    labels: Any,
    probabilities: Any,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
) -> np.ndarray:
    """Return summed multiclass Brier loss for each row (no class-count division)."""

    encoded, matrix = validate_evaluation_inputs(
        labels, probabilities, class_order=class_order
    )
    observed = np.zeros_like(matrix)
    observed[np.arange(encoded.size), encoded] = 1.0
    return np.square(matrix - observed).sum(axis=1)


def _validate_bin_count(n_bins: int) -> int:
    if not isinstance(n_bins, (int, np.integer)) or isinstance(n_bins, (bool, np.bool_)):
        raise TypeError("n_bins must be an integer")
    if int(n_bins) < 2 or int(n_bins) > 1_000:
        raise ValueError("n_bins must be between 2 and 1000")
    return int(n_bins)


def _bin_indices(values: np.ndarray, n_bins: int) -> np.ndarray:
    # Equal-width bins are [i/B, (i+1)/B), except the final bin includes 1.0.
    return np.minimum(np.floor(values * n_bins).astype(np.int64), n_bins - 1)


def _bin_record(bin_index: int, n_bins: int, count: int) -> dict[str, Any]:
    return {
        "binIndex": bin_index,
        "lowerBound": bin_index / n_bins,
        "upperBound": (bin_index + 1) / n_bins,
        "upperBoundInclusive": bin_index == n_bins - 1,
        "count": int(count),
    }


def _class_reliability(
    probabilities: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int,
) -> tuple[list[dict[str, Any]], float]:
    indices = _bin_indices(probabilities, n_bins)
    rows: list[dict[str, Any]] = []
    weighted_gap = 0.0
    total = probabilities.size
    for bin_index in range(n_bins):
        mask = indices == bin_index
        count = int(mask.sum())
        item = _bin_record(bin_index, n_bins, count)
        if count:
            mean_probability = float(probabilities[mask].mean())
            realized_frequency = float(outcomes[mask].mean())
            gap = realized_frequency - mean_probability
            item.update(
                {
                    "meanProbability": mean_probability,
                    "realizedFrequency": realized_frequency,
                    "gap": gap,
                    "absoluteGap": abs(gap),
                }
            )
            weighted_gap += count * abs(gap)
        else:
            item.update(
                {
                    "meanProbability": None,
                    "realizedFrequency": None,
                    "gap": None,
                    "absoluteGap": None,
                }
            )
        rows.append(item)
    return rows, weighted_gap / total


def _top_label_reliability(
    confidence: np.ndarray,
    correct: np.ndarray,
    n_bins: int,
) -> tuple[list[dict[str, Any]], float]:
    indices = _bin_indices(confidence, n_bins)
    rows: list[dict[str, Any]] = []
    weighted_gap = 0.0
    total = confidence.size
    for bin_index in range(n_bins):
        mask = indices == bin_index
        count = int(mask.sum())
        item = _bin_record(bin_index, n_bins, count)
        if count:
            mean_confidence = float(confidence[mask].mean())
            accuracy = float(correct[mask].mean())
            gap = accuracy - mean_confidence
            item.update(
                {
                    "meanConfidence": mean_confidence,
                    "accuracy": accuracy,
                    "gap": gap,
                    "absoluteGap": abs(gap),
                }
            )
            weighted_gap += count * abs(gap)
        else:
            item.update(
                {
                    "meanConfidence": None,
                    "accuracy": None,
                    "gap": None,
                    "absoluteGap": None,
                }
            )
        rows.append(item)
    return rows, weighted_gap / total


def _probability_histogram(values: np.ndarray, n_bins: int) -> list[dict[str, Any]]:
    indices = _bin_indices(values, n_bins)
    total = values.size
    rows: list[dict[str, Any]] = []
    for bin_index in range(n_bins):
        count = int(np.count_nonzero(indices == bin_index))
        item = _bin_record(bin_index, n_bins, count)
        item["populationShare"] = count / total
        rows.append(item)
    return rows


def evaluate_multiclass(
    labels: Any,
    probabilities: Any,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
    n_bins: int = DEFAULT_CALIBRATION_BINS,
) -> dict[str, Any]:
    """Compute deterministic frozen-order discrimination and calibration evidence."""

    order = require_frozen_class_order(class_order)
    bins = _validate_bin_count(n_bins)
    encoded, matrix = validate_evaluation_inputs(
        labels, probabilities, class_order=order
    )
    row_count, class_count = matrix.shape
    class_indices = np.arange(class_count, dtype=np.int64)
    observed = np.zeros_like(matrix)
    observed[np.arange(row_count), encoded] = 1.0
    predicted = matrix.argmax(axis=1)
    confidence = matrix[np.arange(row_count), predicted]
    correct = predicted == encoded

    precision, recall, f1, support = precision_recall_fscore_support(
        encoded,
        predicted,
        labels=class_indices,
        average=None,
        zero_division=0,
    )
    active_support = support > 0
    balanced_accuracy = (
        float(recall[active_support].mean()) if np.any(active_support) else 0.0
    )
    weighted_f1 = float(np.average(f1, weights=support)) if support.sum() else 0.0

    confusion = np.zeros((class_count, class_count), dtype=np.int64)
    np.add.at(confusion, (encoded, predicted), 1)

    classwise_brier_values = np.square(matrix - observed).mean(axis=0)
    classwise_reliability: dict[str, list[dict[str, Any]]] = {}
    classwise_ece: dict[str, float] = {}
    probability_histograms: dict[str, list[dict[str, Any]]] = {}
    for index, class_name in enumerate(order):
        reliability, ece = _class_reliability(
            matrix[:, index], observed[:, index], bins
        )
        classwise_reliability[class_name] = reliability
        classwise_ece[class_name] = float(ece)
        probability_histograms[class_name] = _probability_histogram(
            matrix[:, index], bins
        )

    top_label_reliability, top_label_ece = _top_label_reliability(
        confidence, correct, bins
    )
    realized_prevalence = observed.mean(axis=0)
    predicted_prevalence = matrix.mean(axis=0)
    argmax_prevalence = np.bincount(predicted, minlength=class_count) / row_count

    per_class = {
        class_name: {
            "precision": float(precision[index]),
            "recall": float(recall[index]),
            "f1": float(f1[index]),
            "support": int(support[index]),
        }
        for index, class_name in enumerate(order)
    }

    return {
        "schemaVersion": METRICS_SCHEMA_VERSION,
        "classOrder": list(order),
        "rowCount": int(row_count),
        "binCount": bins,
        "binningRule": "FIXED_EQUAL_WIDTH_LEFT_CLOSED_FINAL_RIGHT_CLOSED",
        "logLoss": float(per_row_log_loss(encoded, matrix, class_order=order).mean()),
        "brierScore": float(
            per_row_brier_score(encoded, matrix, class_order=order).mean()
        ),
        "brierDefinition": "MEAN_SUMMED_ONE_VS_ALL_SQUARED_ERROR",
        "classwiseBrier": {
            class_name: float(classwise_brier_values[index])
            for index, class_name in enumerate(order)
        },
        "topLabelEce": float(top_label_ece),
        "classwiseEce": classwise_ece,
        "top1Accuracy": float(correct.mean()),
        "balancedAccuracy": balanced_accuracy,
        "macroF1": float(f1.mean()),
        "weightedF1": weighted_f1,
        "perClass": per_class,
        "confusionMatrix": confusion.tolist(),
        "confusionMatrixAxes": {"rows": "realized", "columns": "predicted"},
        "realizedPrevalence": {
            class_name: float(realized_prevalence[index])
            for index, class_name in enumerate(order)
        },
        "predictedPrevalence": {
            class_name: float(predicted_prevalence[index])
            for index, class_name in enumerate(order)
        },
        "argmaxPrevalence": {
            class_name: float(argmax_prevalence[index])
            for index, class_name in enumerate(order)
        },
        "topLabelReliability": top_label_reliability,
        "classwiseReliability": classwise_reliability,
        "probabilityHistograms": probability_histograms,
    }


__all__ = [
    "DEFAULT_CALIBRATION_BINS",
    "METRICS_SCHEMA_VERSION",
    "PA_CLASS_ORDER",
    "PROBABILITY_EPSILON",
    "PROBABILITY_SUM_TOLERANCE",
    "encode_labels",
    "evaluate_multiclass",
    "per_row_brier_score",
    "per_row_log_loss",
    "require_frozen_class_order",
    "validate_evaluation_inputs",
    "validate_probability_matrix",
]
