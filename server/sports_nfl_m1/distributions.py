"""Deterministic, correlated NFL score-distribution simulation.

The simulator deliberately has a small scientific surface.  A caller first freezes a
paired empirical residual authority using *training-only* games.  Predicted home and
away means are then shifted by residual pairs sampled with common random numbers and
stochastically rounded to non-negative integer scores.  Keeping each residual pair
together preserves the empirical home/away dependence rather than assuming independent
team scores.

Sportsbook fields are neither accepted nor referenced by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Sequence

import numpy as np


SIMULATION_CONTRACT_VERSION = "NFL_M1_EMPIRICAL_CORRELATED_RESIDUAL_V1"


class ScoreDistributionError(ValueError):
    """Raised when score-distribution authority or output is invalid."""


def _vector(values: Sequence[Any] | np.ndarray, *, label: str) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or array.size == 0:
        raise ScoreDistributionError(f"{label} must be a non-empty one-dimensional array")
    if not np.isfinite(array).all():
        raise ScoreDistributionError(f"{label} contains a non-finite value")
    return array


def _day(value: str | date | datetime | np.datetime64) -> np.datetime64:
    try:
        return np.datetime64(value, "D")
    except (TypeError, ValueError) as exc:
        raise ScoreDistributionError(f"invalid authority date: {value!r}") from exc


def _readonly(array: np.ndarray) -> np.ndarray:
    array = np.ascontiguousarray(array)
    array.setflags(write=False)
    return array


@dataclass(frozen=True)
class PairedResidualAuthority:
    """Immutable paired residual bank fitted strictly through ``training_end``."""

    home: np.ndarray
    away: np.ndarray
    row_ids: tuple[str, ...]
    training_start: str
    training_end: str
    residual_correlation: float
    sha256: str
    contract_version: str = SIMULATION_CONTRACT_VERSION

    @property
    def row_count(self) -> int:
        return int(self.home.size)

    @classmethod
    def fit(
        cls,
        *,
        actual_home: Sequence[float] | np.ndarray,
        actual_away: Sequence[float] | np.ndarray,
        predicted_home: Sequence[float] | np.ndarray,
        predicted_away: Sequence[float] | np.ndarray,
        row_ids: Sequence[str],
        row_dates: Sequence[str | date | datetime | np.datetime64],
        training_end: str | date | datetime | np.datetime64,
    ) -> "PairedResidualAuthority":
        """Freeze paired, zero-mean residuals and their exact training lineage.

        Dates after ``training_end`` fail closed.  This makes it impossible to
        accidentally describe a residual authority containing validation/OOT truth as
        training-only evidence.
        """

        ah = _vector(actual_home, label="actual_home")
        aa = _vector(actual_away, label="actual_away")
        ph = _vector(predicted_home, label="predicted_home")
        pa = _vector(predicted_away, label="predicted_away")
        count = ah.size
        if count < 2 or any(array.size != count for array in (aa, ph, pa)):
            raise ScoreDistributionError("paired residual authority needs at least two aligned games")
        if np.any(ah < 0.0) or np.any(aa < 0.0):
            raise ScoreDistributionError("training score truth must be nonnegative")
        if np.any(ph < 0.0) or np.any(pa < 0.0):
            raise ScoreDistributionError("training score predictions must be nonnegative")
        ids = tuple(str(item) for item in row_ids)
        if len(ids) != count or len(set(ids)) != count or any(not item for item in ids):
            raise ScoreDistributionError("row_ids must be non-empty, aligned, and unique")
        if len(row_dates) != count:
            raise ScoreDistributionError("row_dates must align with residual rows")
        days = np.asarray([_day(item) for item in row_dates], dtype="datetime64[D]")
        cutoff = _day(training_end)
        if np.isnat(days).any() or np.isnat(cutoff):
            raise ScoreDistributionError("authority dates may not be NaT")
        if np.any(days > cutoff):
            raise ScoreDistributionError("residual authority includes truth after training_end")

        home = ah - ph
        away = aa - pa
        # Training-only centering prevents a systematic residual offset from being counted
        # twice when it has already been learned by the score-mean estimator.
        home = _readonly(home - float(np.mean(home)))
        away = _readonly(away - float(np.mean(away)))
        correlation = float(np.corrcoef(home, away)[0, 1])
        if not np.isfinite(correlation):
            correlation = 0.0
        start = str(days.min())
        end = str(cutoff)
        identity = {
            "contractVersion": SIMULATION_CONTRACT_VERSION,
            "trainingStart": start,
            "trainingEnd": end,
            "rows": [
                {
                    "rowId": row_id,
                    "date": str(row_day),
                    "homeResidual": format(float(home_value), ".17g"),
                    "awayResidual": format(float(away_value), ".17g"),
                }
                for row_id, row_day, home_value, away_value in zip(
                    ids, days, home, away, strict=True
                )
            ],
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return cls(
            home=home,
            away=away,
            row_ids=ids,
            training_start=start,
            training_end=end,
            residual_correlation=correlation,
            sha256=digest,
        )


@dataclass(frozen=True)
class CommonRandomNumbers:
    """Candidate-independent uniforms used for fair simulation comparisons."""

    residual_uniform: np.ndarray
    home_round_uniform: np.ndarray
    away_round_uniform: np.ndarray
    seed: int

    @property
    def shape(self) -> tuple[int, int]:
        return tuple(int(value) for value in self.residual_uniform.shape)


def make_common_random_numbers(
    *, n_games: int,
    draws: int,
    seed: int,
) -> CommonRandomNumbers:
    if n_games <= 0 or draws <= 0:
        raise ScoreDistributionError("n_games and draws must be positive")
    rng = np.random.default_rng(int(seed))
    return CommonRandomNumbers(
        residual_uniform=_readonly(rng.random((n_games, draws))),
        home_round_uniform=_readonly(rng.random((n_games, draws))),
        away_round_uniform=_readonly(rng.random((n_games, draws))),
        seed=int(seed),
    )


@dataclass(frozen=True)
class SimulatedScores:
    """Aligned integer score draws, one row per game."""

    home: np.ndarray
    away: np.ndarray
    predicted_home_mean: np.ndarray
    predicted_away_mean: np.ndarray
    residual_authority_sha256: str
    seed: int
    contract_version: str = SIMULATION_CONTRACT_VERSION

    @property
    def n_games(self) -> int:
        return int(self.home.shape[0])

    @property
    def draws(self) -> int:
        return int(self.home.shape[1])

    def joint_pmf(self, game_index: int) -> dict[tuple[int, int], float]:
        """Return the exact empirical joint PMF for one simulated game."""

        if game_index < 0 or game_index >= self.n_games:
            raise IndexError(game_index)
        pairs = np.column_stack((self.home[game_index], self.away[game_index]))
        values, counts = np.unique(pairs, axis=0, return_counts=True)
        return {
            (int(home), int(away)): float(count / self.draws)
            for (home, away), count in zip(values, counts, strict=True)
        }


def simulate_joint_scores(
    *,
    predicted_home_mean: Sequence[float] | np.ndarray,
    predicted_away_mean: Sequence[float] | np.ndarray,
    residual_authority: PairedResidualAuthority,
    draws: int = 10_000,
    seed: int = 20260829,
    common_random_numbers: CommonRandomNumbers | None = None,
) -> SimulatedScores:
    """Draw coherent correlated home/away final scores.

    Passing the same ``CommonRandomNumbers`` to multiple candidates ensures each is
    compared on the same empirical residual indices and stochastic-rounding uniforms.
    """

    home_mean = _vector(predicted_home_mean, label="predicted_home_mean")
    away_mean = _vector(predicted_away_mean, label="predicted_away_mean")
    if home_mean.size != away_mean.size:
        raise ScoreDistributionError("predicted home/away means must align")
    if np.any(home_mean < 0.0) or np.any(away_mean < 0.0):
        raise ScoreDistributionError("predicted score means must be nonnegative")
    randoms = common_random_numbers or make_common_random_numbers(
        n_games=home_mean.size, draws=int(draws), seed=int(seed)
    )
    if randoms.shape != (home_mean.size, int(draws)):
        raise ScoreDistributionError("common random number dimensions do not match request")
    for label, values in (
        ("residual_uniform", randoms.residual_uniform),
        ("home_round_uniform", randoms.home_round_uniform),
        ("away_round_uniform", randoms.away_round_uniform),
    ):
        if values.shape != randoms.shape or not np.isfinite(values).all():
            raise ScoreDistributionError(f"{label} dimensions or values are invalid")
        if np.any((values < 0.0) | (values >= 1.0)):
            raise ScoreDistributionError(f"{label} values must be in [0,1)")
    if (
        residual_authority.home.ndim != 1
        or residual_authority.away.shape != residual_authority.home.shape
        or residual_authority.row_count < 2
        or not np.isfinite(residual_authority.home).all()
        or not np.isfinite(residual_authority.away).all()
    ):
        raise ScoreDistributionError("paired residual authority is invalid")

    residual_index = np.minimum(
        (randoms.residual_uniform * residual_authority.row_count).astype(np.int64),
        residual_authority.row_count - 1,
    )
    latent_home = np.maximum(
        0.0, home_mean[:, None] + residual_authority.home[residual_index]
    )
    latent_away = np.maximum(
        0.0, away_mean[:, None] + residual_authority.away[residual_index]
    )
    # Unbiased integerization for nonnegative latent points.
    home_floor = np.floor(latent_home)
    away_floor = np.floor(latent_away)
    home = home_floor + (randoms.home_round_uniform < (latent_home - home_floor))
    away = away_floor + (randoms.away_round_uniform < (latent_away - away_floor))
    integer_limit = np.iinfo(np.int32).max
    if np.any(home > integer_limit) or np.any(away > integer_limit):
        raise ScoreDistributionError("simulated score exceeds supported integer range")
    result = SimulatedScores(
        home=_readonly(home.astype(np.int32)),
        away=_readonly(away.astype(np.int32)),
        predicted_home_mean=_readonly(home_mean),
        predicted_away_mean=_readonly(away_mean),
        residual_authority_sha256=residual_authority.sha256,
        seed=randoms.seed,
    )
    reconcile_score_simulation(result)
    return result


def reconcile_score_simulation(simulation: SimulatedScores) -> dict[str, Any]:
    """Fail closed unless every implicit joint PMF is a valid probability measure."""

    home = np.asarray(simulation.home)
    away = np.asarray(simulation.away)
    if home.ndim != 2 or away.shape != home.shape or home.size == 0:
        raise ScoreDistributionError("home/away simulation matrices must be aligned and non-empty")
    if not np.isfinite(home).all() or not np.isfinite(away).all():
        raise ScoreDistributionError("simulated scores contain non-finite values")
    if np.any(home < 0) or np.any(away < 0):
        raise ScoreDistributionError("simulated scores contain negative values")
    if np.any(home != np.floor(home)) or np.any(away != np.floor(away)):
        raise ScoreDistributionError("simulated scores must be integral")
    mass = np.asarray(
        [sum(simulation.joint_pmf(index).values()) for index in range(simulation.n_games)]
    )
    if not np.allclose(mass, 1.0, rtol=0.0, atol=1e-12):
        raise ScoreDistributionError("a joint score distribution does not sum to one")
    return {
        "games": simulation.n_games,
        "drawsPerGame": simulation.draws,
        "finite": True,
        "nonnegative": True,
        "integral": True,
        "minimumJointMass": float(mass.min()),
        "maximumJointMass": float(mass.max()),
        "residualAuthoritySha256": simulation.residual_authority_sha256,
        "seed": simulation.seed,
    }


def summarize_game_distribution(
    simulation: SimulatedScores,
    game_index: int,
    *,
    home_spread: float | None = None,
    total_line: float | None = None,
    top_scores: int = 5,
) -> dict[str, Any]:
    """Summarize win, margin, total, interval, and optional market-line events."""

    home = simulation.home[game_index].astype(np.float64)
    away = simulation.away[game_index].astype(np.float64)
    margin = home - away
    total = home + away
    pmf = simulation.joint_pmf(game_index)
    likely = sorted(pmf.items(), key=lambda item: (-item[1], item[0]))[: max(1, top_scores)]
    result: dict[str, Any] = {
        "expectedHomePoints": float(home.mean()),
        "expectedAwayPoints": float(away.mean()),
        "homeWinProbability": float(np.mean(margin > 0.0)),
        "awayWinProbability": float(np.mean(margin < 0.0)),
        "tieProbability": float(np.mean(margin == 0.0)),
        "expectedScoreDifferential": float(margin.mean()),
        "expectedTotalPoints": float(total.mean()),
        "scoreDifferentialInterval90": [
            float(np.quantile(margin, 0.05)),
            float(np.quantile(margin, 0.95)),
        ],
        "totalPointsInterval90": [
            float(np.quantile(total, 0.05)),
            float(np.quantile(total, 0.95)),
        ],
        "mostLikelyFinalScores": [
            {"home": pair[0], "away": pair[1], "probability": probability}
            for pair, probability in likely
        ],
        # These are final-score simulations.  Overtime incidence is not separately
        # identified, so it is left explicitly unsupported instead of fabricated.
        "overtimeProbability": None,
        "overtimeProbabilityStatus": "NOT_SUPPORTED_BY_FINAL_SCORE_RESIDUAL_MODEL",
    }
    if home_spread is not None:
        adjusted = margin + float(home_spread)
        result["homeSpread"] = float(home_spread)
        result["homeCoverProbability"] = float(np.mean(adjusted > 0.0))
        result["awayCoverProbability"] = float(np.mean(adjusted < 0.0))
        result["spreadPushProbability"] = float(np.mean(adjusted == 0.0))
    if total_line is not None:
        adjusted_total = total - float(total_line)
        result["totalLine"] = float(total_line)
        result["overProbability"] = float(np.mean(adjusted_total > 0.0))
        result["underProbability"] = float(np.mean(adjusted_total < 0.0))
        result["totalPushProbability"] = float(np.mean(adjusted_total == 0.0))
    return result
