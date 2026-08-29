"""Transparent chronological baselines for the NFL M1 benchmark."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
import pandas as pd
from scipy.special import ndtr

from .contracts import M1_SCHEMA_VERSION, NflM1IntegrityError, research_only_metadata
from .prediction import GamePredictions


GAME_COLUMNS = (
    "game_date",
    "canonical_home_team_id",
    "canonical_away_team_id",
    "home_points",
    "away_points",
)


def _validated_games(frame: pd.DataFrame, *, require_truth: bool) -> pd.DataFrame:
    required = GAME_COLUMNS if require_truth else GAME_COLUMNS[:3]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise NflM1IntegrityError(f"baseline frame is missing columns: {missing}")
    if frame.empty:
        raise NflM1IntegrityError("baseline frame cannot be empty")
    work = frame.copy()
    try:
        work["m1_model_date"] = pd.to_datetime(work["game_date"], errors="raise").dt.normalize()
    except (TypeError, ValueError) as exc:
        raise NflM1IntegrityError("game_date contains invalid values") from exc
    if work["m1_model_date"].isna().any():
        raise NflM1IntegrityError("game_date cannot be missing")
    for name in ("canonical_home_team_id", "canonical_away_team_id"):
        if work[name].isna().any() or (work[name].astype(str).str.strip() == "").any():
            raise NflM1IntegrityError(f"team identity cannot be missing: {name}")
    if require_truth:
        for name in ("home_points", "away_points"):
            values = pd.to_numeric(work[name], errors="coerce")
            if values.isna().any() or (values < 0).any():
                raise NflM1IntegrityError(f"score truth is invalid: {name}")
            work[name] = values.astype(np.float64)
    work["m1_row_position"] = np.arange(len(work), dtype=np.int64)
    return work.sort_values(["m1_model_date", "m1_row_position"], kind="stable")


def _date_groups(frame: pd.DataFrame) -> Iterable[pd.DataFrame]:
    return (group for _, group in frame.groupby("m1_model_date", sort=True))


@dataclass
class LeagueHomePrior:
    expected_home_points: float | None = None
    expected_away_points: float | None = None
    home_win_probability: float | None = None

    def fit(self, home_points: Any, away_points: Any) -> "LeagueHomePrior":
        home = np.asarray(home_points, dtype=np.float64)
        away = np.asarray(away_points, dtype=np.float64)
        if home.ndim != 1 or away.shape != home.shape or home.size == 0:
            raise NflM1IntegrityError("league prior requires paired score arrays")
        if not np.isfinite(home).all() or not np.isfinite(away).all() or np.any(home < 0) or np.any(away < 0):
            raise NflM1IntegrityError("league-prior score truth is invalid")
        self.expected_home_points = float(home.mean())
        self.expected_away_points = float(away.mean())
        outcomes = (home > away).astype(np.float64)
        # Jeffreys smoothing prevents exact zero/one probabilities in tiny folds.
        self.home_win_probability = float((outcomes.sum() + 0.5) / (home.size + 1.0))
        return self

    def predict(self, row_count: int) -> GamePredictions:
        if self.expected_home_points is None or self.expected_away_points is None or self.home_win_probability is None:
            raise NflM1IntegrityError("league prior has not been fitted")
        if row_count <= 0:
            raise NflM1IntegrityError("row_count must be positive")
        return GamePredictions(
            np.full(row_count, self.expected_home_points),
            np.full(row_count, self.expected_away_points),
            np.full(row_count, self.home_win_probability),
        ).validated()

    def state(self) -> dict[str, Any]:
        state = research_only_metadata("league-home-team-prior")
        state.update(
            {
                "schemaVersion": M1_SCHEMA_VERSION,
                "expectedHomePoints": self.expected_home_points,
                "expectedAwayPoints": self.expected_away_points,
                "homeWinProbability": self.home_win_probability,
            }
        )
        return state


@dataclass
class RollingScoringMarginBaseline:
    window_games: int = 8
    _history: dict[str, deque[tuple[float, float]]] = field(init=False, default_factory=dict)
    _league_home: float | None = field(init=False, default=None)
    _league_away: float | None = field(init=False, default=None)
    _margin_scale: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.window_games < 1:
            raise NflM1IntegrityError("rolling baseline window must be positive")

    def _new_history(self) -> defaultdict[str, deque[tuple[float, float]]]:
        return defaultdict(lambda: deque(maxlen=self.window_games))

    def fit(self, games: pd.DataFrame) -> "RollingScoringMarginBaseline":
        work = _validated_games(games, require_truth=True)
        self._league_home = float(work["home_points"].mean())
        self._league_away = float(work["away_points"].mean())
        scale = float(np.std(work["home_points"] - work["away_points"], ddof=0))
        self._margin_scale = max(scale, 1.0)
        histories = self._new_history()
        for group in _date_groups(work):
            self._update_group(histories, group)
        self._history = dict(histories)
        return self

    @staticmethod
    def _team_means(history: deque[tuple[float, float]] | None) -> tuple[float | None, float | None]:
        if not history:
            return None, None
        values = np.asarray(history, dtype=np.float64)
        return float(values[:, 0].mean()), float(values[:, 1].mean())

    @staticmethod
    def _update_group(
        histories: defaultdict[str, deque[tuple[float, float]]],
        group: pd.DataFrame,
    ) -> None:
        # Called only after every forecast for this date has been produced.
        for row in group.itertuples(index=False):
            home = str(row.canonical_home_team_id)
            away = str(row.canonical_away_team_id)
            home_points = float(row.home_points)
            away_points = float(row.away_points)
            histories[home].append((home_points, away_points))
            histories[away].append((away_points, home_points))

    def predict(self, games: pd.DataFrame, *, update_with_truth: bool = False) -> GamePredictions:
        if self._league_home is None or self._league_away is None or self._margin_scale is None:
            raise NflM1IntegrityError("rolling baseline has not been fitted")
        work = _validated_games(games, require_truth=update_with_truth)
        histories = self._new_history()
        for team, history in self._history.items():
            histories[team].extend(history)
        home_output = np.empty(len(work), dtype=np.float64)
        away_output = np.empty(len(work), dtype=np.float64)
        probability_output = np.empty(len(work), dtype=np.float64)
        for group in _date_groups(work):
            for row in group.itertuples(index=False):
                home = str(row.canonical_home_team_id)
                away = str(row.canonical_away_team_id)
                home_for, home_against = self._team_means(histories.get(home))
                away_for, away_against = self._team_means(histories.get(away))
                expected_home = float(np.mean([value for value in (self._league_home, home_for, away_against) if value is not None]))
                expected_away = float(np.mean([value for value in (self._league_away, away_for, home_against) if value is not None]))
                position = int(row.m1_row_position)
                home_output[position] = max(expected_home, 0.0)
                away_output[position] = max(expected_away, 0.0)
                probability_output[position] = float(np.clip(ndtr((expected_home - expected_away) / self._margin_scale), 1e-6, 1.0 - 1e-6))
            if update_with_truth:
                self._update_group(histories, group)
        return GamePredictions(home_output, away_output, probability_output).validated()

    def state(self) -> dict[str, Any]:
        state = research_only_metadata(f"rolling-scoring-margin-{self.window_games}")
        state.update(
            {
                "schemaVersion": M1_SCHEMA_VERSION,
                "windowGames": self.window_games,
                "sameDateUpdateRule": "DATE_ATOMIC_PREDICT_ALL_THEN_UPDATE",
                "leagueHomePoints": self._league_home,
                "leagueAwayPoints": self._league_away,
                "marginScale": self._margin_scale,
            }
        )
        return state


@dataclass
class EloTeamStrengthBaseline:
    k_factor: float = 20.0
    home_advantage_elo: float = 55.0
    elo_per_score_point: float = 25.0
    initial_rating: float = 1500.0
    _ratings: dict[str, float] = field(init=False, default_factory=dict)
    _mean_total_points: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if self.k_factor <= 0 or self.elo_per_score_point <= 0:
            raise NflM1IntegrityError("Elo parameters must be positive")

    def _rating(self, ratings: dict[str, float], team: str) -> float:
        return float(ratings.get(team, self.initial_rating))

    def _home_probability(self, home_rating: float, away_rating: float) -> float:
        difference = home_rating + self.home_advantage_elo - away_rating
        return float(1.0 / (1.0 + 10.0 ** (-difference / 400.0)))

    def _update_group(self, ratings: dict[str, float], group: pd.DataFrame) -> None:
        changes: defaultdict[str, float] = defaultdict(float)
        for row in group.itertuples(index=False):
            home = str(row.canonical_home_team_id)
            away = str(row.canonical_away_team_id)
            probability = self._home_probability(self._rating(ratings, home), self._rating(ratings, away))
            result = 1.0 if row.home_points > row.away_points else 0.0 if row.home_points < row.away_points else 0.5
            delta = self.k_factor * (result - probability)
            changes[home] += delta
            changes[away] -= delta
        for team, delta in changes.items():
            ratings[team] = self._rating(ratings, team) + delta

    def fit(self, games: pd.DataFrame) -> "EloTeamStrengthBaseline":
        work = _validated_games(games, require_truth=True)
        self._mean_total_points = float((work["home_points"] + work["away_points"]).mean())
        ratings: dict[str, float] = {}
        for group in _date_groups(work):
            self._update_group(ratings, group)
        self._ratings = ratings
        return self

    def predict(self, games: pd.DataFrame, *, update_with_truth: bool = False) -> GamePredictions:
        if self._mean_total_points is None:
            raise NflM1IntegrityError("Elo baseline has not been fitted")
        work = _validated_games(games, require_truth=update_with_truth)
        ratings = dict(self._ratings)
        home_output = np.empty(len(work), dtype=np.float64)
        away_output = np.empty(len(work), dtype=np.float64)
        probability_output = np.empty(len(work), dtype=np.float64)
        for group in _date_groups(work):
            for row in group.itertuples(index=False):
                home_rating = self._rating(ratings, str(row.canonical_home_team_id))
                away_rating = self._rating(ratings, str(row.canonical_away_team_id))
                rating_difference = home_rating + self.home_advantage_elo - away_rating
                expected_margin = rating_difference / self.elo_per_score_point
                expected_home = max((self._mean_total_points + expected_margin) / 2.0, 0.0)
                expected_away = max((self._mean_total_points - expected_margin) / 2.0, 0.0)
                position = int(row.m1_row_position)
                home_output[position] = expected_home
                away_output[position] = expected_away
                probability_output[position] = float(np.clip(self._home_probability(home_rating, away_rating), 1e-6, 1.0 - 1e-6))
            if update_with_truth:
                self._update_group(ratings, group)
        return GamePredictions(home_output, away_output, probability_output).validated()

    def state(self) -> dict[str, Any]:
        state = research_only_metadata("elo-team-strength-baseline")
        state.update(
            {
                "schemaVersion": M1_SCHEMA_VERSION,
                "kFactor": self.k_factor,
                "homeAdvantageElo": self.home_advantage_elo,
                "eloPerScorePoint": self.elo_per_score_point,
                "initialRating": self.initial_rating,
                "sameDateUpdateRule": "DATE_ATOMIC_PREDICT_ALL_THEN_UPDATE",
                "teamCount": len(self._ratings),
                "meanTotalPoints": self._mean_total_points,
            }
        )
        return state


__all__ = [
    "EloTeamStrengthBaseline",
    "GAME_COLUMNS",
    "LeagueHomePrior",
    "RollingScoringMarginBaseline",
]
