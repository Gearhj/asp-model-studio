"""Pure Development diagnostics for paired, eight-class MLB study forecasts.

No files, estimators, providers or publications are loaded here. Calibration
regressions diagnose supplied predictions only; their coefficients never alter
forecasts. Resampling aggregates paired PA contributions before drawing groups.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit

from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix

EPSILON = np.finfo(np.float64).eps
WEEK_BLOCK_LENGTH = 4
MINIMUM_CALENDAR_WEEKS = 8


def _validated(y: Any, p: Any) -> tuple[np.ndarray, np.ndarray]:
    probabilities = validate_probability_matrix(p)
    labels = np.asarray(y)
    if labels.ndim != 1 or len(labels) != len(probabilities):
        raise ValueError("Labels must be one-dimensional and aligned with probability rows.")
    if labels.dtype.kind in "OUS":
        mapping = {name: index for index, name in enumerate(PA_CLASS_ORDER)}
        try:
            labels = np.array([mapping[value] for value in labels], dtype=np.int64)
        except (KeyError, TypeError) as exc:
            raise ValueError("Labels must use the exact registered eight-class order or integer indices.") from exc
    if (labels.dtype.kind not in "fiu" or not np.isfinite(labels).all()
            or np.any(labels != labels.astype(np.int64)) or np.any(labels < 0) or np.any(labels >= len(PA_CLASS_ORDER))):
        raise ValueError("Labels must be valid integer indices in the registered eight-class order.")
    return labels.astype(np.int64), probabilities


def _contributions(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, np.ndarray]:
    true_probability = probabilities[np.arange(len(labels)), labels]
    residual = -probabilities.copy()
    residual[np.arange(len(labels)), labels] += 1.0
    return {
        "logLoss": -np.log(np.clip(true_probability, EPSILON, 1.0)),
        "brier": np.square(residual).sum(axis=1),
        "entropy": -(probabilities * np.log(np.clip(probabilities, EPSILON, 1.0))).sum(axis=1),
        "trueClassProbability": true_probability,
        "maximumProbability": probabilities.max(axis=1),
        "predictedClass": probabilities.argmax(axis=1),
        "calibrationResidual": residual,
    }


def metric_contributions(y: Any, p: Any) -> dict[str, np.ndarray]:
    """Return aligned row contributions; Brier is summed, not class-averaged."""
    return _contributions(*_validated(y, p))


def _calibration_diagnostic(observed: np.ndarray, probability: np.ndarray) -> dict[str, Any]:
    result = {"scope": "EVALUATION_DIAGNOSTIC_ONLY_NOT_FORECAST_CALIBRATOR",
              "definition": "logit Pr(class observed) = intercept + slope * logit(supplied probability)",
              "intercept": None, "slope": None, "regularization": "NONE", "probabilityClipEpsilon": EPSILON}
    if observed.min() == observed.max():
        return {**result, "status": "UNDEFINED_SINGLE_OUTCOME"}
    logits = np.log(np.clip(probability, EPSILON, 1.0 - EPSILON)) - np.log1p(-np.clip(probability, EPSILON, 1.0 - EPSILON))
    if np.ptp(logits) < 1e-10:
        return {**result, "status": "UNDEFINED_CONSTANT_PREDICTION"}
    positive, negative = logits[observed == 1], logits[observed == 0]
    if positive.min() >= negative.max() or positive.max() <= negative.min():
        return {**result, "status": "UNDEFINED_SEPARATION_OR_SINGULAR_INFORMATION"}
    # Centering/scaling improves numerical conditioning, not forecast treatment.
    center, scale = float(logits.mean()), float(logits.std())
    coordinate = (logits - center) / scale

    def objective(parameters):
        eta = parameters[0] + parameters[1] * coordinate
        residual = expit(eta) - observed
        return (float(np.mean(np.logaddexp(0.0, eta) - observed * eta)),
                np.array([residual.mean(), np.mean(residual * coordinate)]))

    prevalence = observed.mean()
    fitted = minimize(objective, [float(np.log(prevalence / (1.0 - prevalence))), 0.0],
                      jac=True, method="BFGS", options={"gtol": 1e-7, "maxiter": 150})
    if not fitted.success or not np.isfinite(fitted.x).all():
        return {**result, "status": "NOT_CONVERGED", "reason": str(fitted.message)}
    eta = fitted.x[0] + fitted.x[1] * coordinate
    weight = expit(eta) * expit(-eta)
    hessian = np.array([[weight.mean(), np.mean(weight * coordinate)],
                        [np.mean(weight * coordinate), np.mean(weight * coordinate * coordinate)]])
    # Complete/quasi separation cannot supply a finite, reliable diagnostic slope.
    if np.linalg.eigvalsh(hessian).min() < 1e-9:
        return {**result, "status": "UNDEFINED_SEPARATION_OR_SINGULAR_INFORMATION"}
    slope = float(fitted.x[1] / scale)
    return {**result, "status": "ESTIMATED", "intercept": float(fitted.x[0] - slope * center),
            "slope": slope, "iterations": int(fitted.nit)}


def predictive_metrics(y: Any, p: Any) -> dict[str, Any]:
    """Summarize supplied forecasts without fitting or modifying a predictor."""
    labels, probabilities = _validated(y, p)
    contributions = _contributions(labels, probabilities)
    classes = []
    for index, name in enumerate(PA_CLASS_ORDER):
        observed = (labels == index).astype(np.float64)
        predicted = probabilities[:, index]
        bin_number = np.minimum((predicted * 10).astype(int), 9)
        counts = np.bincount(bin_number, minlength=10)
        expected = np.bincount(bin_number, weights=predicted, minlength=10)
        actual = np.bincount(bin_number, weights=observed, minlength=10)
        reliability = [{"bin": number, "lowerInclusive": number / 10, "upper": (number + 1) / 10,
                        "upperInclusive": number == 9, "observations": int(counts[number]),
                        "meanProbability": float(expected[number] / counts[number]) if counts[number] else None,
                        "observedRate": float(actual[number] / counts[number]) if counts[number] else None}
                       for number in range(10)]
        classes.append({"className": name, "classIndex": index, "observations": len(labels),
                        "observedCount": int(observed.sum()), "observedRate": float(observed.mean()),
                        "predictedRate": float(predicted.mean()), "rateBias": float(predicted.mean() - observed.mean()),
                        "oneVsRestBrier": float(np.square(predicted - observed).mean()),
                        "meanTrueClassLogLoss": float(contributions["logLoss"][labels == index].mean()) if observed.sum() else None,
                        "probabilityStd": float(predicted.std()),
                        "calibration": _calibration_diagnostic(observed, predicted), "reliability": reliability})
    return {"observations": len(labels), "classOrder": list(PA_CLASS_ORDER),
            "logLoss": float(contributions["logLoss"].mean()), "brier": float(contributions["brier"].mean()),
            "brierDefinition": "SUMMED_EIGHT_CLASS_SQUARED_PROBABILITY_ERROR",
            "entropy": float(contributions["entropy"].mean()), "entropyUnits": "NATS",
            "meanMaximumProbability": float(contributions["maximumProbability"].mean()),
            "perClass": classes, "rareClassDefinition": "DESCRIPTIVE_OBSERVED_RATE_BELOW_0.02_NOT_MODEL_SELECTION",
            "rareClass": [row for row in classes if row["observedRate"] < 0.02]}


def _group_statistics(keys: Any, deltas: np.ndarray) -> np.ndarray:
    codes, names = pd.factorize(keys, sort=False)
    if np.any(codes < 0):
        raise ValueError("Missing keys must be explicitly excluded before group aggregation.")
    return np.column_stack([np.bincount(codes, minlength=len(names)),
                            np.bincount(codes, weights=deltas[:, 0], minlength=len(names)),
                            np.bincount(codes, weights=deltas[:, 1], minlength=len(names))])


def _intervals(draws: np.ndarray, estimate: np.ndarray) -> dict[str, Any]:
    return {name: {"estimate": float(estimate[index]), "lower": float(np.quantile(draws[:, index], 0.025)),
                   "upper": float(np.quantile(draws[:, index], 0.975)), "confidenceLevel": 0.95,
                   "intervalType": "PERCENTILE"} for index, name in enumerate(("logLoss", "brier"))}


def _cluster_bootstrap(keys: Any, deltas: np.ndarray, rng: np.random.Generator, replicates: int) -> dict[str, Any]:
    stats = _group_statistics(keys, deltas)
    if len(stats) < 2:
        return {"status": "INSUFFICIENT_CLUSTERS", "clusters": len(stats), "observations": len(deltas)}
    estimates = []
    for start in range(0, replicates, 32):
        draw = rng.integers(0, len(stats), size=(min(32, replicates - start), len(stats)))
        sums = stats[draw].sum(axis=1)
        estimates.append(sums[:, 1:] / sums[:, [0]])
    return {"status": "AVAILABLE", "clusters": len(stats), "observations": len(deltas), "replicates": replicates,
            "estimand": "PA_WEIGHTED_CANDIDATE_MINUS_BASELINE", "intervals": _intervals(np.vstack(estimates), deltas.mean(axis=0)),
            "limitedClusterWarning": "FEWER_THAN_20_CLUSTERS_INTERVAL_UNSTABLE" if len(stats) < 20 else None}


def _week_bootstrap(dates: pd.Series, deltas: np.ndarray, rng: np.random.Generator, replicates: int) -> dict[str, Any]:
    week_start = dates - pd.to_timedelta(dates.dt.dayofweek, unit="D")
    week_codes = ((week_start - week_start.min()).dt.days // 7).to_numpy()
    calendar_weeks = int(week_codes.max() + 1)
    observed_weeks = int(np.unique(week_codes).size)
    result = {"method": "NONCIRCULAR_MOVING_BLOCK_BOOTSTRAP_OF_FOUR_CONSECUTIVE_CALENDAR_WEEKS",
              "calendarWeeks": calendar_weeks, "observedWeeks": observed_weeks,
              "blockLengthWeeks": WEEK_BLOCK_LENGTH, "minimumCalendarWeeks": MINIMUM_CALENDAR_WEEKS,
              "minimumObservedWeeks": MINIMUM_CALENDAR_WEEKS,
              "nonoverlappingFullBlocks": calendar_weeks // WEEK_BLOCK_LENGTH,
              "observedNonoverlappingBlocks": int(np.unique(week_codes // WEEK_BLOCK_LENGTH).size),
              "calendarStart": week_start.min().date().isoformat(), "calendarEnd": week_start.max().date().isoformat(),
              "observations": len(deltas), "emptyWeeksRetained": True}
    if calendar_weeks < MINIMUM_CALENDAR_WEEKS or observed_weeks < MINIMUM_CALENDAR_WEEKS:
        return {**result, "status": "INSUFFICIENT_TEMPORAL_BLOCKS", "intervals": None}
    stats = np.column_stack([np.bincount(week_codes, minlength=calendar_weeks),
                             np.bincount(week_codes, weights=deltas[:, 0], minlength=calendar_weeks),
                             np.bincount(week_codes, weights=deltas[:, 1], minlength=calendar_weeks)])
    draws = []
    blocks_per_draw = int(np.ceil(calendar_weeks / WEEK_BLOCK_LENGTH))
    for start in range(0, replicates, 32):
        starts = rng.integers(0, calendar_weeks - WEEK_BLOCK_LENGTH + 1,
                             size=(min(32, replicates - start), blocks_per_draw))
        selected = (starts[:, :, None] + np.arange(WEEK_BLOCK_LENGTH)[None, None, :]).reshape(len(starts), -1)[:, :calendar_weeks]
        sums = stats[selected].sum(axis=1)
        valid = sums[:, 0] > 0
        draws.append(sums[valid, 1:] / sums[valid, 0][:, None])
    sampled = np.vstack(draws)
    if not len(sampled):
        return {**result, "status": "INSUFFICIENT_OBSERVED_BLOCKS", "intervals": None}
    return {**result, "status": "AVAILABLE", "requestedReplicates": replicates, "validReplicates": len(sampled),
            "emptyReplicatesExcluded": replicates - len(sampled),
            "estimand": "PA_WEIGHTED_CANDIDATE_MINUS_BASELINE", "intervals": _intervals(sampled, deltas.mean(axis=0)),
            "limitedBlockWarning": "FEWER_THAN_FIVE_NONOVERLAPPING_FULL_BLOCKS" if calendar_weeks // WEEK_BLOCK_LENGTH < 5 else None}


def paired_uncertainty(frame: pd.DataFrame, y: Any, base: Any, candidate: Any, *,
                       seed: int = 20260910, replicates: int = 1000) -> dict[str, Any]:
    """Separate dependence sensitivities, not a joint-dependence-valid interval.

    Rows must already be exact-ID matched. Games stay atomic in game/week
    resamples; four-week blocks preserve all rows in sampled calendar blocks.
Player and team resamples are separate one-way sensitivities, not independent
confirmatory tests or simultaneous corrections for every dependence source.
"""
    labels, baseline = _validated(y, base)
    candidate_labels, candidate_probability = _validated(y, candidate)
    if len(frame) != len(labels) or not np.array_equal(labels, candidate_labels):
        raise ValueError("Paired predictions and identity frame must align exactly.")
    if replicates < 20:
        raise ValueError("At least 20 replicates are required for percentile diagnostics.")
    for name in ("canonicalGameId", "game_date"):
        if name not in frame or frame[name].isna().any() or frame[name].astype(str).str.strip().eq("").any():
            raise ValueError(f"Complete {name} identities are required; rows cannot be silently dropped.")
    dates = pd.to_datetime(frame["game_date"].reset_index(drop=True), utc=True, errors="raise").dt.tz_localize(None).dt.normalize()
    if dates.isna().any():
        raise ValueError("Every paired game requires a valid calendar date.")
    if pd.DataFrame({"game": frame["canonicalGameId"].to_numpy(), "date": dates}).groupby("game", sort=False)["date"].nunique().gt(1).any():
        raise ValueError("One canonical game maps to conflicting calendar dates.")
    b = _contributions(labels, baseline)
    c = _contributions(labels, candidate_probability)
    deltas = np.column_stack([c["logLoss"] - b["logLoss"], c["brier"] - b["brier"]])
    streams = [np.random.default_rng(stream) for stream in np.random.SeedSequence(seed).spawn(6)]
    sensitivities = {}
    for number, name in enumerate(("batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "battingTeamId", "fieldingTeamId")):
        if name not in frame:
            sensitivities[name] = {"status": "UNAVAILABLE_IDENTITY_FIELD", "observations": None, "excludedObservations": len(frame)}
            continue
        eligible = (frame[name].notna() & frame[name].astype(str).str.strip().ne("")).to_numpy()
        if not eligible.any():
            sensitivities[name] = {"status": "UNAVAILABLE_IDENTITY_VALUES", "observations": None, "excludedObservations": len(frame)}
            continue
        sensitivity = _cluster_bootstrap(frame.loc[eligible, name].to_numpy(), deltas[eligible], streams[number + 2], replicates)
        sensitivities[name] = {**sensitivity, "excludedObservations": int((~eligible).sum()),
                               "coverageFraction": float(eligible.mean()), "method": "SEPARATE_ONE_WAY_IDENTITY_CLUSTER_SENSITIVITY"}
    return {"observations": len(frame), "games": int(frame["canonicalGameId"].nunique()), "dates": int(dates.nunique()),
            "startDate": dates.min().date().isoformat(), "endDate": dates.max().date().isoformat(),
            "seed": seed, "replicates": replicates, "direction": "CANDIDATE_MINUS_BASELINE_NEGATIVE_IS_LOWER_ERROR",
            "estimate": {"logLoss": float(deltas[:, 0].mean()), "brier": float(deltas[:, 1].mean())},
            "gameClusterBootstrap": _cluster_bootstrap(frame["canonicalGameId"].to_numpy(), deltas, streams[0], replicates),
            "calendarWeekBlockBootstrap": _week_bootstrap(dates, deltas, streams[1], replicates),
            "repeatedIdentitySensitivity": sensitivities,
            "limitations": ["Game clustering alone does not account for cross-game date, player or team dependence.",
                            "Four-week moving blocks preserve local temporal dependence, not all long-lived player/team dependence.",
                            "Separate batter, pitcher and team-role intervals are sensitivities, not one joint-dependence guarantee.",
                            "Team roles are clustered separately; no cross-role franchise-dependence guarantee is claimed.",
                            "Percentile intervals are descriptive Development uncertainty, not independent promotion authority."]}
