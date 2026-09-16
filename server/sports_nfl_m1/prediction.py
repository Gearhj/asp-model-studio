"""Shared validated prediction containers for NFL M1 research candidates."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .contracts import NflM1IntegrityError


@dataclass(frozen=True)
class GamePredictions:
    expected_home_points: np.ndarray
    expected_away_points: np.ndarray
    home_win_probability: np.ndarray

    def validated(self) -> "GamePredictions":
        home = np.asarray(self.expected_home_points, dtype=np.float64)
        away = np.asarray(self.expected_away_points, dtype=np.float64)
        probability = np.asarray(self.home_win_probability, dtype=np.float64)
        if home.ndim != 1 or away.ndim != 1 or probability.ndim != 1:
            raise NflM1IntegrityError("game predictions must be one-dimensional")
        if not (home.size == away.size == probability.size) or home.size == 0:
            raise NflM1IntegrityError("game prediction arrays must have equal nonzero length")
        if not np.isfinite(home).all() or not np.isfinite(away).all() or not np.isfinite(probability).all():
            raise NflM1IntegrityError("game predictions must be finite")
        if np.any(home < 0.0) or np.any(away < 0.0):
            raise NflM1IntegrityError("expected scores cannot be negative")
        if np.any(probability <= 0.0) or np.any(probability >= 1.0):
            raise NflM1IntegrityError("home-win probabilities must remain strictly inside (0, 1)")
        return GamePredictions(home, away, probability)

    @property
    def row_count(self) -> int:
        return int(np.asarray(self.expected_home_points).size)


__all__ = ["GamePredictions"]
