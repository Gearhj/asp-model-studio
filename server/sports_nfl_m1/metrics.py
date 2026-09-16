"""Proper probability, point, and empirical-distribution metrics for NFL M1."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from scipy.optimize import minimize

from .distributions import ScoreDistributionError, SimulatedScores


EPSILON = 1e-12


def _vector(values: Sequence[Any] | np.ndarray, *, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0 or not np.isfinite(array).all():
        raise ScoreDistributionError(f"{label} must be a finite non-empty vector")
    return array


def _aligned(*arrays: np.ndarray) -> None:
    if len({array.size for array in arrays}) != 1:
        raise ScoreDistributionError("metric inputs must have identical row counts")


def calibration_table(
    truth: Sequence[int] | np.ndarray,
    probability: Sequence[float] | np.ndarray,
    *,
    bins: int = 10,
) -> list[dict[str, Any]]:
    """Return fixed-width reliability bins including empty-bin provenance."""

    y = _vector(truth, label="truth")
    p = _vector(probability, label="probability")
    _aligned(y, p)
    if not np.isin(y, (0.0, 1.0)).all() or np.any((p < 0.0) | (p > 1.0)):
        raise ScoreDistributionError("calibration requires binary truth and [0,1] probabilities")
    if bins <= 0:
        raise ScoreDistributionError("bins must be positive")
    # p == 1 belongs to the final bin.
    bin_index = np.minimum((p * bins).astype(int), bins - 1)
    rows: list[dict[str, Any]] = []
    for index in range(bins):
        mask = bin_index == index
        count = int(mask.sum())
        rows.append(
            {
                "bin": index,
                "lower": index / bins,
                "upper": (index + 1) / bins,
                "count": count,
                "meanProbability": float(p[mask].mean()) if count else None,
                "eventRate": float(y[mask].mean()) if count else None,
            }
        )
    return rows


def expected_calibration_error(
    truth: Sequence[int] | np.ndarray,
    probability: Sequence[float] | np.ndarray,
    *,
    bins: int = 10,
) -> float:
    table = calibration_table(truth, probability, bins=bins)
    total = sum(row["count"] for row in table)
    return float(
        sum(
            row["count"]
            * abs(float(row["meanProbability"]) - float(row["eventRate"]))
            for row in table
            if row["count"]
        )
        / total
    )


def calibration_intercept_slope(
    truth: Sequence[int] | np.ndarray,
    probability: Sequence[float] | np.ndarray,
) -> dict[str, Any]:
    """Fit ``logit(y) = intercept + slope * logit(p)`` without regularization."""

    y = _vector(truth, label="truth")
    p = _vector(probability, label="probability")
    _aligned(y, p)
    if not np.isin(y, (0.0, 1.0)).all() or np.any((p < 0.0) | (p > 1.0)):
        raise ScoreDistributionError("calibration requires binary truth and [0,1] probabilities")
    if np.unique(y).size != 2:
        return {
            "intercept": None,
            "slope": None,
            "status": "UNAVAILABLE_SINGLE_CLASS",
        }
    clipped = np.clip(p, EPSILON, 1.0 - EPSILON)
    logit = np.log(clipped / (1.0 - clipped))

    def objective(parameters: np.ndarray) -> float:
        linear = parameters[0] + parameters[1] * logit
        # Stable binary cross entropy from logits.
        return float(np.sum(np.logaddexp(0.0, linear) - y * linear))

    fitted = minimize(objective, np.asarray([0.0, 1.0]), method="BFGS")
    if not fitted.success or not np.isfinite(fitted.x).all():
        return {"intercept": None, "slope": None, "status": "OPTIMIZATION_FAILED"}
    return {
        "intercept": float(fitted.x[0]),
        "slope": float(fitted.x[1]),
        "status": "COMPLETE",
    }


def binary_probability_metrics(
    truth: Sequence[int] | np.ndarray,
    probability: Sequence[float] | np.ndarray,
    *,
    bins: int = 10,
) -> dict[str, Any]:
    y = _vector(truth, label="truth")
    p = _vector(probability, label="probability")
    _aligned(y, p)
    if not np.isin(y, (0.0, 1.0)).all() or np.any((p < 0.0) | (p > 1.0)):
        raise ScoreDistributionError("binary metrics require binary truth and [0,1] probabilities")
    clipped = np.clip(p, EPSILON, 1.0 - EPSILON)
    losses = -(y * np.log(clipped) + (1.0 - y) * np.log(1.0 - clipped))
    calibration = calibration_intercept_slope(y, p)
    return {
        "rows": int(y.size),
        "logLoss": float(losses.mean()),
        "brierScore": float(np.mean((p - y) ** 2)),
        "ece": expected_calibration_error(y, p, bins=bins),
        "calibrationIntercept": calibration["intercept"],
        "calibrationSlope": calibration["slope"],
        "calibrationStatus": calibration["status"],
        "accuracy": float(np.mean((p >= 0.5) == y)),
    }


def score_point_metrics(
    *,
    actual_home: Sequence[float] | np.ndarray,
    actual_away: Sequence[float] | np.ndarray,
    predicted_home: Sequence[float] | np.ndarray,
    predicted_away: Sequence[float] | np.ndarray,
) -> dict[str, float | int]:
    ah = _vector(actual_home, label="actual_home")
    aa = _vector(actual_away, label="actual_away")
    ph = _vector(predicted_home, label="predicted_home")
    pa = _vector(predicted_away, label="predicted_away")
    _aligned(ah, aa, ph, pa)
    if any(np.any(values < 0.0) for values in (ah, aa, ph, pa)):
        raise ScoreDistributionError("actual and predicted scores must be nonnegative")
    home_error = ph - ah
    away_error = pa - aa
    differential_error = (ph - pa) - (ah - aa)
    total_error = (ph + pa) - (ah + aa)
    return {
        "rows": int(ah.size),
        "homePointsMae": float(np.mean(np.abs(home_error))),
        "awayPointsMae": float(np.mean(np.abs(away_error))),
        "meanTeamPointsMae": float(
            (np.mean(np.abs(home_error)) + np.mean(np.abs(away_error))) / 2.0
        ),
        "scoreDifferentialMae": float(np.mean(np.abs(differential_error))),
        "totalPointsMae": float(np.mean(np.abs(total_error))),
        "homePointsRmse": float(np.sqrt(np.mean(home_error**2))),
        "awayPointsRmse": float(np.sqrt(np.mean(away_error**2))),
        "scoreDifferentialRmse": float(np.sqrt(np.mean(differential_error**2))),
        "totalPointsRmse": float(np.sqrt(np.mean(total_error**2))),
    }


def empirical_crps(samples: Sequence[float] | np.ndarray, actual: float) -> float:
    """Compute CRPS from empirical samples in O(n log n), without pair expansion."""

    values = _vector(samples, label="samples")
    ordered = np.sort(values)
    count = ordered.size
    term_one = float(np.mean(np.abs(ordered - float(actual))))
    ranks = np.arange(1, count + 1, dtype=np.float64)
    expected_pair_distance = float(
        (2.0 / (count * count)) * np.sum((2.0 * ranks - count - 1.0) * ordered)
    )
    return term_one - 0.5 * expected_pair_distance


def quantile_calibration_table(
    samples: Sequence[Sequence[float]] | np.ndarray,
    actual: Sequence[float] | np.ndarray,
    *,
    quantiles: Sequence[float] = (0.1, 0.25, 0.5, 0.75, 0.9),
) -> list[dict[str, float]]:
    """Compare nominal quantiles with observed whole-game score coverage."""

    matrix = np.asarray(samples, dtype=np.float64)
    truth = _vector(actual, label="actual")
    if matrix.ndim != 2 or matrix.shape[0] != truth.size or not np.isfinite(matrix).all():
        raise ScoreDistributionError("sample matrix must align with actual rows")
    requested = np.asarray(tuple(quantiles), dtype=np.float64)
    if (
        requested.ndim != 1
        or requested.size == 0
        or not np.all(np.diff(requested) > 0.0)
        or np.any((requested <= 0.0) | (requested >= 1.0))
    ):
        raise ScoreDistributionError("quantiles must be unique, increasing, and inside (0,1)")
    predicted = np.quantile(matrix, requested, axis=1)
    return [
        {
            "nominalQuantile": float(quantile),
            "observedAtOrBelow": float(np.mean(truth <= predicted[index])),
            "absoluteCalibrationError": float(
                abs(np.mean(truth <= predicted[index]) - quantile)
            ),
        }
        for index, quantile in enumerate(requested)
    ]


def _joint_negative_log_likelihood(
    home_samples: np.ndarray,
    away_samples: np.ndarray,
    actual_home: int,
    actual_away: int,
    *,
    alpha: float,
) -> float:
    if alpha <= 0.0:
        raise ScoreDistributionError("joint likelihood smoothing alpha must be positive")
    match_count = int(
        np.sum((home_samples == int(actual_home)) & (away_samples == int(actual_away)))
    )
    max_home = max(int(home_samples.max()), int(actual_home))
    max_away = max(int(away_samples.max()), int(actual_away))
    support_size = (max_home + 1) * (max_away + 1)
    probability = (match_count + alpha) / (home_samples.size + alpha * support_size)
    return float(-np.log(probability))


def distribution_metrics(
    simulation: SimulatedScores,
    *,
    actual_home: Sequence[int] | np.ndarray,
    actual_away: Sequence[int] | np.ndarray,
    interval: tuple[float, float] = (0.05, 0.95),
    joint_smoothing_alpha: float = 0.5,
    calibration_bins: int = 10,
) -> dict[str, Any]:
    """Evaluate one aligned empirical joint distribution per game."""

    ah = _vector(actual_home, label="actual_home")
    aa = _vector(actual_away, label="actual_away")
    if ah.size != simulation.n_games or aa.size != simulation.n_games:
        raise ScoreDistributionError("actual scores must align with simulated games")
    if np.any(ah < 0.0) or np.any(aa < 0.0):
        raise ScoreDistributionError("actual scores must be nonnegative")
    lower, upper = interval
    if not 0.0 < lower < upper < 1.0:
        raise ScoreDistributionError("interval quantiles must satisfy 0 < lower < upper < 1")

    home = simulation.home.astype(np.float64)
    away = simulation.away.astype(np.float64)
    margin = home - away
    total = home + away
    actual_margin = ah - aa
    actual_total = ah + aa
    p_home = np.mean(margin > 0.0, axis=1)
    # Ties are explicitly not transformed into a hidden half-win.  Historical tied
    # finals remain non-home-wins for this binary event definition.
    probability = binary_probability_metrics(
        (actual_margin > 0.0).astype(int), p_home, bins=calibration_bins
    )
    point = score_point_metrics(
        actual_home=ah,
        actual_away=aa,
        predicted_home=home.mean(axis=1),
        predicted_away=away.mean(axis=1),
    )
    home_bounds = np.quantile(home, [lower, upper], axis=1)
    away_bounds = np.quantile(away, [lower, upper], axis=1)
    margin_bounds = np.quantile(margin, [lower, upper], axis=1)
    total_bounds = np.quantile(total, [lower, upper], axis=1)
    cover = lambda bounds, actual: float(
        np.mean((actual >= bounds[0]) & (actual <= bounds[1]))
    )
    joint_nll = [
        _joint_negative_log_likelihood(
            home[index],
            away[index],
            int(ah[index]),
            int(aa[index]),
            alpha=joint_smoothing_alpha,
        )
        for index in range(simulation.n_games)
    ]
    quantile_calibration = {
        "homePoints": quantile_calibration_table(home, ah),
        "awayPoints": quantile_calibration_table(away, aa),
        "scoreDifferential": quantile_calibration_table(margin, actual_margin),
        "totalPoints": quantile_calibration_table(total, actual_total),
    }
    return {
        "rows": simulation.n_games,
        "drawsPerGame": simulation.draws,
        "probability": probability,
        "score": point,
        "jointScoreNegativeLogLikelihood": float(np.mean(joint_nll)),
        "jointScoreNegativeLogLikelihoodByGame": joint_nll,
        "crps": {
            "homePoints": float(
                np.mean(
                    [empirical_crps(home[index], ah[index]) for index in range(ah.size)]
                )
            ),
            "awayPoints": float(
                np.mean(
                    [empirical_crps(away[index], aa[index]) for index in range(aa.size)]
                )
            ),
            "scoreDifferential": float(
                np.mean(
                    [
                        empirical_crps(margin[index], actual_margin[index])
                        for index in range(ah.size)
                    ]
                )
            ),
            "totalPoints": float(
                np.mean(
                    [empirical_crps(total[index], actual_total[index]) for index in range(ah.size)]
                )
            ),
        },
        "quantileCalibration": quantile_calibration,
        "meanAbsoluteQuantileCalibrationError": {
            name: float(np.mean([row["absoluteCalibrationError"] for row in table]))
            for name, table in quantile_calibration.items()
        },
        "interval": {
            "lowerQuantile": lower,
            "upperQuantile": upper,
            "nominalCoverage": upper - lower,
            "homePointsCoverage": cover(home_bounds, ah),
            "awayPointsCoverage": cover(away_bounds, aa),
            "scoreDifferentialCoverage": cover(margin_bounds, actual_margin),
            "totalPointsCoverage": cover(total_bounds, actual_total),
        },
    }


def line_event_metrics(
    simulation: SimulatedScores,
    *,
    actual_home: Sequence[int] | np.ndarray,
    actual_away: Sequence[int] | np.ndarray,
    home_spread: Sequence[float] | np.ndarray,
    total_line: Sequence[float] | np.ndarray,
    calibration_bins: int = 10,
) -> dict[str, Any]:
    """Evaluate cover/over calibration, excluding actual pushes transparently."""

    ah = _vector(actual_home, label="actual_home")
    aa = _vector(actual_away, label="actual_away")
    spread = _vector(home_spread, label="home_spread")
    line = _vector(total_line, label="total_line")
    _aligned(ah, aa, spread, line)
    if ah.size != simulation.n_games:
        raise ScoreDistributionError("line rows must align with simulated games")
    simulated_margin = simulation.home - simulation.away
    simulated_total = simulation.home + simulation.away
    simulated_adjusted_margin = simulated_margin + spread[:, None]
    simulated_adjusted_total = simulated_total - line[:, None]
    cover_count = np.sum(simulated_adjusted_margin > 0.0, axis=1)
    spread_nonpush_count = np.sum(simulated_adjusted_margin != 0.0, axis=1)
    over_count = np.sum(simulated_adjusted_total > 0.0, axis=1)
    total_nonpush_count = np.sum(simulated_adjusted_total != 0.0, axis=1)
    # Evaluation excludes an actual push, so use the matching conditional modeled
    # event rather than silently treating simulated pushes as losses.
    p_cover = np.divide(
        cover_count,
        spread_nonpush_count,
        out=np.full(simulation.n_games, 0.5),
        where=spread_nonpush_count > 0,
    )
    p_over = np.divide(
        over_count,
        total_nonpush_count,
        out=np.full(simulation.n_games, 0.5),
        where=total_nonpush_count > 0,
    )
    actual_adjusted_margin = ah - aa + spread
    actual_adjusted_total = ah + aa - line
    spread_nonpush = actual_adjusted_margin != 0.0
    total_nonpush = actual_adjusted_total != 0.0
    return {
        "homeCover": {
            "eligibleRows": int(spread_nonpush.sum()),
            "pushRows": int((~spread_nonpush).sum()),
            "meanPredictedPushProbability": float(
                np.mean(simulated_adjusted_margin == 0.0)
            ),
            "metrics": binary_probability_metrics(
                (actual_adjusted_margin[spread_nonpush] > 0.0).astype(int),
                p_cover[spread_nonpush],
                bins=calibration_bins,
            )
            if spread_nonpush.any()
            else None,
        },
        "over": {
            "eligibleRows": int(total_nonpush.sum()),
            "pushRows": int((~total_nonpush).sum()),
            "meanPredictedPushProbability": float(
                np.mean(simulated_adjusted_total == 0.0)
            ),
            "metrics": binary_probability_metrics(
                (actual_adjusted_total[total_nonpush] > 0.0).astype(int),
                p_over[total_nonpush],
                bins=calibration_bins,
            )
            if total_nonpush.any()
            else None,
        },
    }


def paired_whole_game_bootstrap(
    candidate_metric_by_game: Sequence[float] | np.ndarray,
    baseline_metric_by_game: Sequence[float] | np.ndarray,
    *,
    resamples: int = 2_000,
    confidence: float = 0.95,
    seed: int = 20260829,
) -> dict[str, Any]:
    """Paired percentile CI for mean candidate-minus-baseline game metric.

    The same game indices are drawn for both methods on every replicate.  For loss
    metrics, a negative difference favors the candidate.
    """

    candidate = _vector(candidate_metric_by_game, label="candidate_metric_by_game")
    baseline = _vector(baseline_metric_by_game, label="baseline_metric_by_game")
    _aligned(candidate, baseline)
    if resamples < 2 or not 0.0 < confidence < 1.0:
        raise ScoreDistributionError("invalid bootstrap configuration")
    difference = candidate - baseline
    rng = np.random.default_rng(int(seed))
    means = np.empty(int(resamples), dtype=np.float64)
    # Chunking avoids allocating resamples x games for long ledgers.
    for index in range(int(resamples)):
        sampled = rng.integers(0, difference.size, size=difference.size)
        means[index] = float(np.mean(difference[sampled]))
    tail = (1.0 - confidence) / 2.0
    return {
        "games": int(difference.size),
        "resamples": int(resamples),
        "seed": int(seed),
        "confidence": float(confidence),
        "pointEstimate": float(difference.mean()),
        "standardError": float(means.std(ddof=1)),
        "lower": float(np.quantile(means, tail)),
        "upper": float(np.quantile(means, 1.0 - tail)),
        "differenceDirection": "CANDIDATE_MINUS_BASELINE",
    }
