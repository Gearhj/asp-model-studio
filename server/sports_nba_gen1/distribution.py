"""NBA Gen 1 oriented paired-residual distributions and proper scores.

This module has no source, model-fitting, or publication interface. The caller
must certify that residuals are chronological out-of-fold errors from eligible
earlier games and that overtime evidence consists of eligible, earlier observed
overtime-period points. Both matrices always have columns HOME, AWAY. Metadata,
acquisition clocks and source restrictions belong to the calling data contract;
an unannotated numerical matrix cannot certify its own history.

The residual bank is centered once by its two pooled column means. Each draw
samples one complete oriented pair. Scores are floored at zero and stochastically
rounded. A tied draw receives a complete empirical overtime-period points pair,
repeating only while tied. This is an explicit empirical tie-resolution rule for
the final-score residual model, not a possession-level overtime model. Because
the residual donors already represent full games, its incremental effects must
be reported; no claim that the pre-resolution population is regulation scoring
is made. No tied draws are discarded or given an invented coin-flip winner.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Sequence

import numpy as np

from server.sports_nfl_m1.metrics import empirical_crps as _established_crps
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import (
    joint_energy_score as _established_joint_energy,
)


ENGINE = "NBA_GEN1_PAIRED_RESIDUAL_V1"
PROBABILITY_UNITS = "fraction_0_to_1"
LOG_LOSS_FLOOR = 1e-12
INTERVAL_LEVELS = (0.5, 0.8, 0.9)
TAIL_QUANTILES = (0.005, 0.01, 0.05, 0.5, 0.95, 0.99, 0.995)


class DistributionUnsupported(ValueError):
    """No eligible numerical population can be returned under the frozen rule."""


def game_seed(game_identity: str, configuration_identity: str, master_seed: int) -> int:
    """Stable SHA-256-derived 64-bit seed, independent of Python hash/order.

    Canonical UTF-8 JSON is [engine, game identity, configuration identity,
    master seed]; use the first eight digest bytes as an unsigned big-endian
    integer. The caller must use stable canonical game and configuration IDs.
    """
    if not game_identity or not configuration_identity:
        raise DistributionUnsupported("Stable game and configuration identities required")
    seed = _nonnegative_integer(master_seed, "master_seed")
    payload = json.dumps([ENGINE, str(game_identity), str(configuration_identity), seed],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _nonnegative_integer(value: Any, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < 0:
        raise DistributionUnsupported(f"{name} must be a nonnegative integer")
    return int(value)


def _pairs(values: Any, name: str, minimum_rows: int, *, integer: bool = False) -> np.ndarray:
    try:
        pairs = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise DistributionUnsupported(f"{name} must be a finite HOME, AWAY matrix") from exc
    if (pairs.ndim != 2 or pairs.shape[1] != 2 or len(pairs) < minimum_rows
            or not np.isfinite(pairs).all()):
        raise DistributionUnsupported(f"{name} requires at least {minimum_rows} finite HOME, AWAY pairs")
    if integer and ((pairs < 0).any() or (pairs != np.floor(pairs)).any()):
        raise DistributionUnsupported(f"{name} must contain nonnegative integer period points")
    return pairs


def simulate(predicted_home: float, predicted_away: float, residuals: Any, seed: int,
             draws: int = 10_000, overtime_evidence: Any = None, *,
             max_overtime_periods: int = 32) -> dict[str, Any]:
    """Return paired final scores; source eligibility must be enforced upstream.

    Residual columns are actual minus predicted HOME, AWAY points. Overtime
    columns are observed HOME, AWAY points within one complete overtime period,
    including tied intermediate periods. All returned score vectors share draw
    index. The entire call fails if evidence is absent or any draw remains tied
    at the safeguard; it never filters draws or manufactures a winner.
    """
    draw_count = _nonnegative_integer(draws, "draws")
    period_limit = _nonnegative_integer(max_overtime_periods, "max_overtime_periods")
    seed = _nonnegative_integer(seed, "seed")
    if draw_count < 2 or period_limit < 1:
        raise DistributionUnsupported("At least two draws and one allowed overtime period required")
    point = np.asarray([predicted_home, predicted_away], dtype=np.float64)
    if not np.isfinite(point).all() or (point < 0).any():
        raise DistributionUnsupported("Expected HOME, AWAY scores must be finite and nonnegative")
    bank = _pairs(residuals, "chronological residuals", 2)
    if overtime_evidence is None:
        raise DistributionUnsupported("Eligible earlier overtime-period HOME, AWAY evidence is required")
    overtime = _pairs(overtime_evidence, "overtime evidence", 1, integer=True)
    if not (overtime[:, 0] != overtime[:, 1]).any():
        raise DistributionUnsupported("Overtime evidence contains no observed resolving period")

    # Independent deterministic streams prevent OT/rounding draws from changing
    # which complete residual pair was sampled for another simulation index.
    children = np.random.SeedSequence(seed).spawn(3)
    pair_rng, round_rng, overtime_rng = [np.random.default_rng(child) for child in children]
    indices = pair_rng.integers(0, len(bank), size=draw_count)
    pooled_center = bank.mean(axis=0)
    latent = point + (bank - pooled_center)[indices]
    nonnegative = np.maximum(latent, 0.0)
    maximum_increment = overtime.max(axis=0) * period_limit
    safe_maximum = np.iinfo(np.int64).max // 4
    if (nonnegative.max(axis=0) + maximum_increment > safe_maximum).any():
        raise DistributionUnsupported("Integer score range would be exceeded")
    base = np.floor(nonnegative)
    scores = (base + (round_rng.random((draw_count, 2)) < nonnegative - base)).astype(np.int64)
    before = scores.copy()
    period_counts = np.zeros(draw_count, dtype=np.int64)
    raw_ties = before[:, 0] == before[:, 1]
    period_usage = np.zeros(len(overtime), dtype=np.int64)
    for _ in range(period_limit):
        tied_indices = np.flatnonzero(scores[:, 0] == scores[:, 1])
        if not len(tied_indices):
            break
        sampled_periods = overtime_rng.integers(0, len(overtime), size=len(tied_indices))
        scores[tied_indices] += overtime[sampled_periods].astype(np.int64)
        period_counts[tied_indices] += 1
        period_usage += np.bincount(sampled_periods, minlength=len(overtime))
    unresolved = int(np.sum(scores[:, 0] == scores[:, 1]))
    if unresolved:
        raise DistributionUnsupported(
            f"{unresolved}/{draw_count} draws remain tied after {period_limit} overtime periods; "
            "entire forecast unsupported, no draws discarded")

    home, away = scores[:, 0].copy(), scores[:, 1].copy()
    before_home_win = float(np.mean(before[:, 0] > before[:, 1]))
    after_home_win = float(np.mean(home > away))
    before_mean = before.mean(axis=0)
    after_mean = scores.mean(axis=0)
    return {
        "home_runs": home, "away_runs": away, "total_runs": home + away,
        "margin": home - away, "residual_indices": indices,
        "overtime_period_counts": period_counts,
        "diagnostics": {
            "engine": ENGINE, "scoreUnits": "points", "pairedColumns": ["HOME", "AWAY"],
            "drawCount": draw_count, "seed": seed,
            "rng": "numpy.Generator.PCG64; SeedSequence children 0=pair,1=round,2=overtime",
            "residualDonorCount": len(bank), "residualPooledColumnMeans": pooled_center.tolist(),
            "residualCentering": "subtract each pooled column mean once; preserve complete oriented pairs",
            "overtimeEvidencePeriodCount": len(overtime),
            "overtimeRule": "append sampled complete empirical HOME,AWAY overtime period until untied",
            "overtimeInterpretation": "tie resolution of full-game residual draws; pre-resolution is not regulation",
            "overtimePeriodSafeguard": period_limit, "rawTieCount": int(raw_ties.sum()),
            "rawTieFraction": float(raw_ties.mean()), "finalTieCount": 0,
            "overtimePeriodsAppended": int(period_counts.sum()),
            "maximumOvertimePeriodsAppended": int(period_counts.max()),
            "overtimePeriodCountFrequencies": frequency_table(period_counts),
            "overtimeDonorPeriodUseCounts": period_usage.tolist(),
            "pointExpectedHomeAway": point.tolist(), "latentSampleMeanHomeAway": latent.mean(axis=0).tolist(),
            "nonnegativeFloorCountHomeAway": (latent < 0).sum(axis=0).astype(int).tolist(),
            "beforeOvertimeMeanHomeAway": before_mean.tolist(),
            "afterOvertimeMeanHomeAway": after_mean.tolist(),
            "overtimeMeanChangeHomeAway": (after_mean - before_mean).tolist(),
            "beforeOvertimeHomeWinProbability": before_home_win,
            "afterOvertimeHomeWinProbability": after_home_win,
            "overtimeHomeWinProbabilityChange": after_home_win - before_home_win,
            "probabilityUnits": PROBABILITY_UNITS,
            "sourceEligibility": "MUST_BE_CERTIFIED_BY_CALLER_BEFORE_SIMULATION",
        },
    }


def _vector(values: Any, name: str, *, integer: bool = False, nonnegative: bool = False) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or len(array) < 2 or not np.isfinite(array).all():
        raise DistributionUnsupported(f"{name} requires at least two finite draws")
    if (integer and (array != np.floor(array)).any()) or (nonnegative and (array < 0).any()):
        raise DistributionUnsupported(f"{name} contains invalid score values")
    return array


def _final_population(home: Any, away: Any) -> tuple[np.ndarray, np.ndarray]:
    h = _vector(home, "home", integer=True, nonnegative=True)
    a = _vector(away, "away", integer=True, nonnegative=True)
    if len(h) != len(a) or (h == a).any():
        raise DistributionUnsupported("Final NBA population must contain aligned, untied HOME, AWAY pairs")
    return h, a


def frequency_table(values: Any) -> list[dict[str, int | float]]:
    """Full integer support, no trimming; denominator is the original draw count."""
    array = _vector(values, "frequency values", integer=True)
    support, counts = np.unique(array.astype(np.int64), return_counts=True)
    return [{"value": int(value), "count": int(count), "probability": float(count / len(array))}
            for value, count in zip(support, counts)]


def empirical_crps(values: Any, observation: float) -> float:
    """Validate NBA inputs and call the established pure empirical CRPS scorer."""
    population = _vector(values, "CRPS values")
    if not np.isfinite(observation):
        raise DistributionUnsupported("CRPS observation must be finite")
    return _established_crps(population, observation)


def joint_energy_score(home: Any, away: Any, observed: Sequence[float]) -> float:
    """Exact Euclidean empirical V-statistic, retaining joint dependence.

    Delegates only pure numerical math to the established joint scorer. This
    imports no data or model and invokes no MLB/NFL task or outcome query.
    """
    h, a = _final_population(home, away)
    observation = np.asarray(observed, dtype=np.float64)
    if observation.shape != (2,) or not np.isfinite(observation).all():
        raise DistributionUnsupported("Energy observation must be finite HOME, AWAY points")
    return _established_joint_energy(h, a, observation)


def _marginal(values: np.ndarray, observed: float | None = None) -> dict[str, Any]:
    mean = float(values.mean())
    intervals = {}
    for level in INTERVAL_LEVELS:
        lower, upper = np.quantile(values, [(1 - level) / 2, (1 + level) / 2], method="inverted_cdf")
        intervals[str(level)] = {"lower": int(lower), "upper": int(upper), "width": int(upper - lower)}
        if observed is not None:
            intervals[str(level)]["covered"] = bool(lower <= observed <= upper)
    result = {
        "mean": mean, "monteCarloStandardError": float(values.std(ddof=1) / np.sqrt(len(values))),
        "centralPredictionIntervals": intervals,
        "quantiles": {str(q): int(np.quantile(values, q, method="inverted_cdf")) for q in TAIL_QUANTILES},
        "minimum": int(values.min()), "maximum": int(values.max()),
    }
    if observed is not None:
        result.update(observed=float(observed), signedError=mean - observed,
                      absoluteError=abs(mean - observed), squaredError=(mean - observed)**2,
                      crps=empirical_crps(values, observed),
                      probabilityBelowObservation=float(np.mean(values < observed)),
                      probabilityAtObservation=float(np.mean(values == observed)),
                      probabilityAboveObservation=float(np.mean(values > observed)))
    return result


def summarize(home_runs: Any, away_runs: Any, *, include_distributions: bool = True) -> dict[str, Any]:
    """Forecast contract fields derived exclusively from the original joint draws."""
    h, a = _final_population(home_runs, away_runs)
    p_home = float(np.mean(h > a))
    marginals = {name: _marginal(values) for name, values in
                 (("home", h), ("away", a), ("total", h + a), ("margin", h - a))}
    result = {
        "drawCount": len(h), "probabilityUnits": PROBABILITY_UNITS, "scoreUnits": "points",
        "homeWinProbability": p_home, "awayWinProbability": 1 - p_home, "tieProbability": 0.0,
        "homeWinMonteCarloStandardError": float(np.sqrt(p_home * (1 - p_home) / len(h))),
        "expectedHomeScore": float(h.mean()), "expectedAwayScore": float(a.mean()),
        "expectedTotal": float((h + a).mean()), "expectedHomeMargin": float((h - a).mean()),
        "marginals": marginals,
        "monteCarloInterpretation": "simulation sampling precision, not predictive uncertainty or independent games",
    }
    if include_distributions:
        result["distributions"] = {name: frequency_table(values) for name, values in
                                   (("home", h), ("away", a), ("total", h + a), ("margin", h - a))}
    return result


def score_forecast(home_runs: Any, away_runs: Any, actual_home: int, actual_away: int) -> dict[str, Any]:
    """Score one observed game; across-game aggregation is the assessment unit."""
    h, a = _final_population(home_runs, away_runs)
    oh = _nonnegative_integer(actual_home, "actual_home")
    oa = _nonnegative_integer(actual_away, "actual_away")
    if oh == oa:
        raise DistributionUnsupported("A governed FINAL NBA game cannot have a tied score")
    p_home = float(np.mean(h > a))
    truth = int(oh > oa)
    truth_probability = p_home if truth else 1 - p_home
    marginals = {name: _marginal(values, observation) for name, values, observation in
                 (("home", h, oh), ("away", a, oa), ("total", h + a, oh + oa), ("margin", h - a, oh - oa))}
    return {
        "assessmentUnit": "one_observed_game", "drawCount": len(h),
        "actualHome": oh, "actualAway": oa, "actualHomeWin": truth,
        "homeWinProbability": p_home, "awayWinProbability": 1 - p_home, "tieProbability": 0.0,
        "probabilityUnits": PROBABILITY_UNITS,
        "winnerLogLoss": float(-np.log(max(truth_probability, LOG_LOSS_FLOOR))),
        "logLossFloor": LOG_LOSS_FLOOR, "binaryBrier": float((p_home - truth)**2),
        "brierDefinition": "(P(HOME_WIN) - 1[HOME_WIN])^2; final NBA tie probability is zero",
        "jointEnergyScore": joint_energy_score(h, a, [oh, oa]),
        "marginals": marginals,
        "meanTeamScoreAbsoluteError": (marginals["home"]["absoluteError"] + marginals["away"]["absoluteError"]) / 2,
        "winnerPick": "HOME" if p_home > 0.5 else "AWAY" if p_home < 0.5 else "NO_UNIQUE_PICK",
        "correctWinnerPick": bool((p_home > 0.5) == bool(truth)) if p_home != 0.5 else None,
    }
