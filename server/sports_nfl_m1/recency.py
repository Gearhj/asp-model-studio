"""Declared NFL M1 training-history strategies and deterministic weights."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np

from .contracts import NflM1IntegrityError


class RecencyStrategy(str, Enum):
    ALL_AVAILABLE_HISTORY = "ALL_AVAILABLE_HISTORY"
    MOST_RECENT_8_SEASONS = "MOST_RECENT_8_SEASONS"
    MOST_RECENT_5_SEASONS = "MOST_RECENT_5_SEASONS"
    MOST_RECENT_3_SEASONS = "MOST_RECENT_3_SEASONS"
    EXPONENTIAL_SEASON_DECAY_HALF_LIFE_1 = "EXPONENTIAL_SEASON_DECAY_HALF_LIFE_1"
    EXPONENTIAL_SEASON_DECAY_HALF_LIFE_2 = "EXPONENTIAL_SEASON_DECAY_HALF_LIFE_2"


RECENCY_STRATEGIES: tuple[RecencyStrategy, ...] = tuple(RecencyStrategy)
_WINDOW_SEASONS = {
    RecencyStrategy.MOST_RECENT_8_SEASONS: 8,
    RecencyStrategy.MOST_RECENT_5_SEASONS: 5,
    RecencyStrategy.MOST_RECENT_3_SEASONS: 3,
}
_HALF_LIVES = {
    RecencyStrategy.EXPONENTIAL_SEASON_DECAY_HALF_LIFE_1: 1.0,
    RecencyStrategy.EXPONENTIAL_SEASON_DECAY_HALF_LIFE_2: 2.0,
}


@dataclass(frozen=True)
class RecencyWeights:
    strategy: RecencyStrategy
    validation_season: int
    eligible_mask: np.ndarray
    sample_weights: np.ndarray
    earliest_included_season: int
    latest_included_season: int

    @property
    def row_count(self) -> int:
        return int(self.eligible_mask.sum())

    def state(self) -> dict[str, object]:
        included = self.sample_weights[self.eligible_mask]
        return {
            "strategy": self.strategy.value,
            "validationSeason": self.validation_season,
            "rowCount": self.row_count,
            "earliestIncludedSeason": self.earliest_included_season,
            "latestIncludedSeason": self.latest_included_season,
            "minimumPositiveWeight": float(included.min()),
            "maximumWeight": float(included.max()),
            "meanPositiveWeight": float(included.mean()),
            "normalization": "POSITIVE_TRAINING_WEIGHTS_MEAN_ONE",
        }


def recency_weights(
    seasons: np.ndarray,
    validation_season: int,
    strategy: RecencyStrategy | str,
) -> RecencyWeights:
    """Return the pre-validation mask and fold-local recency sample weights.

    ``validation_season`` is the temporal cutoff: rows from that season or any
    later season always receive zero weight.  Exponential distance is measured
    from the last authorized season, not from the maximum value in the input.
    Positive weights are normalized to mean one for estimator stability.
    """

    try:
        selected = RecencyStrategy(strategy)
    except ValueError as exc:
        raise NflM1IntegrityError(f"unknown recency strategy: {strategy}") from exc
    values = np.asarray(seasons)
    if values.ndim != 1 or values.size == 0:
        raise NflM1IntegrityError("seasons must be a non-empty one-dimensional array")
    if values.dtype.kind not in "iu":
        try:
            numeric = values.astype(np.int64)
        except (TypeError, ValueError) as exc:
            raise NflM1IntegrityError("seasons must contain integer values") from exc
        if not np.array_equal(values, numeric):
            raise NflM1IntegrityError("seasons must contain integer values")
        values = numeric
    else:
        values = values.astype(np.int64, copy=False)
    cutoff = int(validation_season)
    eligible = values < cutoff
    if selected in _WINDOW_SEASONS:
        eligible &= values >= cutoff - _WINDOW_SEASONS[selected]
    if not np.any(eligible):
        raise NflM1IntegrityError(
            f"recency strategy {selected.value} has no rows before season {cutoff}"
        )
    weights = np.zeros(values.size, dtype=np.float64)
    if selected in _HALF_LIVES:
        age = (cutoff - 1) - values[eligible]
        weights[eligible] = np.power(0.5, age / _HALF_LIVES[selected])
    else:
        weights[eligible] = 1.0
    weights[eligible] /= float(weights[eligible].mean())
    if not np.isfinite(weights).all() or np.any(weights < 0.0):
        raise NflM1IntegrityError("recency weighting produced invalid weights")
    included_seasons = values[eligible]
    return RecencyWeights(
        strategy=selected,
        validation_season=cutoff,
        eligible_mask=eligible,
        sample_weights=weights,
        earliest_included_season=int(included_seasons.min()),
        latest_included_season=int(included_seasons.max()),
    )


__all__ = ["RECENCY_STRATEGIES", "RecencyStrategy", "RecencyWeights", "recency_weights"]
