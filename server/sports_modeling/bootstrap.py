from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from .metrics import (
    PA_CLASS_ORDER,
    per_row_brier_score,
    per_row_log_loss,
    require_frozen_class_order,
    validate_evaluation_inputs,
)


BOOTSTRAP_SCHEMA_VERSION = "MLB_PA_GAME_CLUSTER_BOOTSTRAP_V1"
DEFAULT_BOOTSTRAP_RESAMPLES = 500
DEFAULT_BOOTSTRAP_SEED = 20_260_817
DEFAULT_CONFIDENCE_LEVEL = 0.95


def _validate_positive_integer(value: Any, *, label: str) -> int:
    if not isinstance(value, (int, np.integer)) or isinstance(value, (bool, np.bool_)):
        raise TypeError(f"{label} must be a positive integer")
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return parsed


def _validate_seed(value: Any) -> int:
    if not isinstance(value, (int, np.integer)) or isinstance(value, (bool, np.bool_)):
        raise TypeError("seed must be a non-negative integer")
    parsed = int(value)
    if parsed < 0 or parsed > np.iinfo(np.uint64).max:
        raise ValueError("seed must fit NumPy's unsigned 64-bit range")
    return parsed


def _validate_game_ids(game_ids: Any, row_count: int) -> tuple[np.ndarray, list[str]]:
    values = np.asarray(game_ids, dtype=object)
    if values.ndim != 1 or values.shape[0] != row_count:
        raise ValueError("game_ids must be one-dimensional and row-aligned")
    items = values.tolist()
    if not all(isinstance(value, str) and value.strip() for value in items):
        raise TypeError("game_ids must contain non-empty strings")

    # Canonical ordering makes a seeded result invariant to source row order.
    ordered_unique = sorted(set(items))
    if len(ordered_unique) < 2:
        raise ValueError("game-cluster bootstrap requires at least two unique games")
    return np.asarray(items, dtype=object), ordered_unique


def _interval_summary(
    point_estimate: float,
    replicates: np.ndarray,
    confidence_level: float,
) -> dict[str, Any]:
    alpha = 1.0 - confidence_level
    lower, upper = np.percentile(
        replicates,
        [100.0 * alpha / 2.0, 100.0 * (1.0 - alpha / 2.0)],
        method="linear",
    )
    return {
        "pointEstimate": float(point_estimate),
        "bootstrapMean": float(replicates.mean()),
        "bootstrapStandardError": float(replicates.std(ddof=1)),
        "percentileInterval": {
            "confidenceLevel": confidence_level,
            "lower": float(lower),
            "upper": float(upper),
        },
        "probabilitySelectedBetter": float(np.mean(replicates < 0.0)),
        "replicateDifferences": replicates.tolist(),
    }


def game_cluster_bootstrap(
    labels: Any,
    selected_probabilities: Any,
    comparator_probabilities: Any,
    game_ids: Any,
    *,
    class_order: Sequence[str] = PA_CLASS_ORDER,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    confidence_level: float = DEFAULT_CONFIDENCE_LEVEL,
) -> dict[str, Any]:
    """
    Bootstrap selected-minus-comparator metric differences by resampling whole
    game identities with replacement. Rows are never independently sampled.
    """

    order = require_frozen_class_order(class_order)
    encoded, selected = validate_evaluation_inputs(
        labels, selected_probabilities, class_order=order
    )
    comparator = validate_evaluation_inputs(
        encoded, comparator_probabilities, class_order=order
    )[1]
    if selected.shape != comparator.shape:
        raise ValueError("selected and comparator probabilities must have equal shape")

    resample_count = _validate_positive_integer(n_resamples, label="n_resamples")
    if resample_count < 2:
        raise ValueError("n_resamples must be at least two for interval estimation")
    parsed_seed = _validate_seed(seed)
    if not isinstance(confidence_level, (int, float)) or isinstance(
        confidence_level, bool
    ):
        raise TypeError("confidence_level must be a finite number in (0, 1)")
    parsed_confidence = float(confidence_level)
    if not math.isfinite(parsed_confidence) or not 0.0 < parsed_confidence < 1.0:
        raise ValueError("confidence_level must be a finite number in (0, 1)")

    aligned_games, unique_games = _validate_game_ids(game_ids, encoded.size)
    game_index = {game_id: index for index, game_id in enumerate(unique_games)}
    cluster_indices = np.asarray(
        [game_index[str(game_id)] for game_id in aligned_games], dtype=np.int64
    )
    cluster_count = len(unique_games)

    selected_log = per_row_log_loss(encoded, selected, class_order=order)
    comparator_log = per_row_log_loss(encoded, comparator, class_order=order)
    selected_brier = per_row_brier_score(encoded, selected, class_order=order)
    comparator_brier = per_row_brier_score(encoded, comparator, class_order=order)
    log_difference = selected_log - comparator_log
    brier_difference = selected_brier - comparator_brier

    cluster_log_values: list[list[float]] = [[] for _ in range(cluster_count)]
    cluster_brier_values: list[list[float]] = [[] for _ in range(cluster_count)]
    for index, log_value, brier_value in zip(
        cluster_indices, log_difference, brier_difference, strict=True
    ):
        cluster_log_values[int(index)].append(float(log_value))
        cluster_brier_values[int(index)].append(float(brier_value))
    cluster_rows = np.asarray(
        [len(values) for values in cluster_log_values], dtype=np.float64
    )
    # Sort within each cluster before accurate summation so row permutations do
    # not alter content-addressed bootstrap evidence through float addition order.
    cluster_log_sums = np.asarray(
        [
            math.fsum(sorted(values))
            for values in cluster_log_values
        ],
        dtype=np.float64,
    )
    cluster_brier_sums = np.asarray(
        [
            math.fsum(sorted(values))
            for values in cluster_brier_values
        ],
        dtype=np.float64,
    )

    rng = np.random.default_rng(parsed_seed)
    log_replicates = np.empty(resample_count, dtype=np.float64)
    brier_replicates = np.empty(resample_count, dtype=np.float64)
    for replicate in range(resample_count):
        drawn = rng.integers(0, cluster_count, size=cluster_count)
        sampled_rows = cluster_rows[drawn].sum()
        log_replicates[replicate] = cluster_log_sums[drawn].sum() / sampled_rows
        brier_replicates[replicate] = (
            cluster_brier_sums[drawn].sum() / sampled_rows
        )

    return {
        "schemaVersion": BOOTSTRAP_SCHEMA_VERSION,
        "classOrder": list(order),
        "differenceConvention": "SELECTED_MINUS_COMPARATOR_NEGATIVE_FAVORS_SELECTED",
        "resamplingUnit": "game_id",
        "resamplingMethod": "EQUAL_PROBABILITY_CLUSTERS_WITH_REPLACEMENT",
        "rowsSampledIndependently": False,
        "rowCount": int(encoded.size),
        "clusterCount": cluster_count,
        "clusterDrawsPerReplicate": cluster_count,
        "resampleCount": resample_count,
        "seed": parsed_seed,
        "confidenceLevel": parsed_confidence,
        "logLossDifference": _interval_summary(
            math.fsum(sorted(log_difference.tolist())) / encoded.size,
            log_replicates,
            parsed_confidence,
        ),
        "brierScoreDifference": _interval_summary(
            math.fsum(sorted(brier_difference.tolist())) / encoded.size,
            brier_replicates,
            parsed_confidence,
        ),
    }


__all__ = [
    "BOOTSTRAP_SCHEMA_VERSION",
    "DEFAULT_BOOTSTRAP_RESAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_CONFIDENCE_LEVEL",
    "game_cluster_bootstrap",
]
