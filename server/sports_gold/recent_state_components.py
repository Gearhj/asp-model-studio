"""Strictly-prior plate-appearance state components for Phase 7B4.

The public workflow is deliberately split into ``fit_state_authority`` and
``score_state_components``.  The first function receives only a caller-
supplied training slice.  The second rejects a target block unless every
training day is strictly earlier than every target day.  Consequently a
current-day plate appearance can never enter its own state, and a rolling
validation caller cannot accidentally update state inside a validation block.

All probability vectors use the governed :data:`PA_CLASS_ORDER`.  No function
reads files, opens a data source, consults wall-clock time, or treats 2024 as a
selection period.  Fold-safe Direct Gold probabilities are supplied by the
caller because they are needed to construct expectation-adjusted residuals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

from server.sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    require_frozen_class_order,
    validate_probability_matrix,
)


SCHEMA_VERSION = "MLB_GOLD_RECENT_STATE_COMPONENTS_V1"
RANDOM_SEED = 20_260_824

DIRECT_MODEL = "DIRECT_MODEL"
LONG_TERM_STATE = "LONG_TERM_STATE"
RECENT_14_DAY_STATE = "RECENT_14_DAY_STATE"
RECENT_42_DAY_STATE = "RECENT_42_DAY_STATE"
DECAY_180_DAY_STATE = "DECAY_180_DAY_STATE"
DECAY_365_DAY_STATE = "DECAY_365_DAY_STATE"
CLUSTER_MATCHUP = "CLUSTER_MATCHUP"
SHRUNK_EXACT_BVP = "SHRUNK_EXACT_BVP"
RECENT_RESIDUAL_FORM = "RECENT_RESIDUAL_FORM"

COMPONENT_ORDER: tuple[str, ...] = (
    DIRECT_MODEL,
    LONG_TERM_STATE,
    RECENT_14_DAY_STATE,
    RECENT_42_DAY_STATE,
    DECAY_180_DAY_STATE,
    DECAY_365_DAY_STATE,
    CLUSTER_MATCHUP,
    SHRUNK_EXACT_BVP,
    RECENT_RESIDUAL_FORM,
)
EMPIRICAL_COMPONENT_ORDER: tuple[str, ...] = COMPONENT_ORDER[1:]

_EPSILON = 1.0e-12
_DAY_NANOS = 86_400_000_000_000


class RecentStateComponentError(RuntimeError):
    """Raised when a state input or temporal invariant is not trustworthy."""


@dataclass(frozen=True)
class StateComponentConfig:
    """Fixed, intentionally small shrinkage and archetype configuration.

    These are study constants, not a tuning grid.  In particular the exact
    batter-versus-pitcher prior strength is fixed at the requested 50 PA.
    """

    class_order: tuple[str, ...] = PA_CLASS_ORDER
    date_column: str = "game_date"
    outcome_column: str = "outcome"
    batter_column: str = "batterCanonicalPlayerId"
    pitcher_column: str = "pitcherCanonicalPlayerId"
    row_id_column: str = "plate_appearance_id"
    league_uniform_prior_strength: float = 8.0
    long_term_role_prior_strength: float = 24.0
    recent_14_prior_strength: float = 30.0
    recent_42_prior_strength: float = 45.0
    decay_prior_strength: float = 24.0
    cluster_matchup_prior_strength: float = 30.0
    exact_bvp_prior_strength: float = 50.0
    residual_14_prior_strength: float = 30.0
    residual_42_prior_strength: float = 45.0
    batter_archetypes: int = 6
    pitcher_archetypes: int = 6
    random_seed: int = RANDOM_SEED
    kmeans_n_init: int = 20

    def validate(self) -> "StateComponentConfig":
        require_frozen_class_order(self.class_order)
        if not all(
            isinstance(value, str) and value.strip()
            for value in (
                self.date_column,
                self.outcome_column,
                self.batter_column,
                self.pitcher_column,
                self.row_id_column,
            )
        ):
            raise ValueError("state component column names must be non-empty strings")
        strengths = (
            self.league_uniform_prior_strength,
            self.long_term_role_prior_strength,
            self.recent_14_prior_strength,
            self.recent_42_prior_strength,
            self.decay_prior_strength,
            self.cluster_matchup_prior_strength,
            self.residual_14_prior_strength,
            self.residual_42_prior_strength,
        )
        if not all(math.isfinite(value) and value > 0.0 for value in strengths):
            raise ValueError("all state shrinkage strengths must be finite and positive")
        if self.exact_bvp_prior_strength != 50.0:
            raise ValueError("exact batter-versus-pitcher prior strength is fixed at 50 PA")
        if self.batter_archetypes != 6 or self.pitcher_archetypes != 6:
            raise ValueError("Phase 7B4 fixes exactly six batter and six pitcher archetypes")
        if self.kmeans_n_init < 1:
            raise ValueError("kmeans_n_init must be positive")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise TypeError("random_seed must be an integer")
        return self


@dataclass(frozen=True)
class ComponentEstimate:
    """One governed-order probability component and its reliability signals.

    ``role_diagnostics`` may contain aligned batter/pitcher probability and
    reliability arrays.  The top-level fields always describe the component
    probability actually offered to an ensemble or stacker.
    """

    name: str
    probabilities: np.ndarray
    observation_count: np.ndarray
    effective_sample_size: np.ndarray
    missing_history: np.ndarray
    days_since_prior_appearance: np.ndarray
    entropy: np.ndarray
    deviation_from_long_term: np.ndarray
    role_diagnostics: Mapping[str, np.ndarray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        probabilities = validate_probability_matrix(self.probabilities)
        rows = probabilities.shape[0]
        numeric = {
            "observation_count": self.observation_count,
            "effective_sample_size": self.effective_sample_size,
            "days_since_prior_appearance": self.days_since_prior_appearance,
            "entropy": self.entropy,
            "deviation_from_long_term": self.deviation_from_long_term,
        }
        for label, raw in numeric.items():
            values = np.asarray(raw)
            if values.ndim != 1 or values.shape[0] != rows:
                raise ValueError(f"{self.name} {label} is not row-aligned")
            if label == "days_since_prior_appearance":
                if np.any(np.isfinite(values) & (values < 1.0)):
                    raise ValueError(f"{self.name} includes same-day or future history")
            elif not np.isfinite(values).all() or np.any(values < 0.0):
                raise ValueError(f"{self.name} {label} must be finite and nonnegative")
        flags = np.asarray(self.missing_history)
        if flags.dtype.kind != "b" or flags.ndim != 1 or flags.shape[0] != rows:
            raise ValueError(f"{self.name} missing_history must be an aligned boolean vector")
        if np.any(np.asarray(self.effective_sample_size) > np.asarray(self.observation_count) + 1e-8):
            raise ValueError(f"{self.name} effective sample size exceeds observation count")
        if np.any(np.asarray(self.deviation_from_long_term) > 1.0 + 1e-10):
            raise ValueError(f"{self.name} deviation from long term exceeds total variation bounds")
        for label, raw in self.role_diagnostics.items():
            values = np.asarray(raw)
            if values.ndim not in (1, 2) or values.shape[0] != rows:
                raise ValueError(f"{self.name} role diagnostic {label!r} is not row-aligned")
        object.__setattr__(self, "probabilities", probabilities)


@dataclass(frozen=True)
class StateComponentBundle:
    """Aligned Phase 7B4 components for one validation/score block."""

    row_ids: tuple[str, ...]
    class_order: tuple[str, ...]
    components: Mapping[str, ComponentEstimate]
    training_end_day: str
    target_start_day: str
    target_end_day: str

    def __post_init__(self) -> None:
        require_frozen_class_order(self.class_order)
        if tuple(self.components) != COMPONENT_ORDER:
            raise ValueError("component mapping must preserve the fixed Phase 7B4 order")
        if any(key != component.name for key, component in self.components.items()):
            raise ValueError("component mapping keys and component names differ")
        rows = len(self.row_ids)
        if rows == 0 or len(set(self.row_ids)) != rows:
            raise ValueError("component bundle row identities must be non-empty and unique")
        if any(component.probabilities.shape[0] != rows for component in self.components.values()):
            raise ValueError("component bundle rows are not aligned")

    @property
    def reliability(self) -> dict[str, dict[str, np.ndarray]]:
        """Return the exact nested reliability contract used by ensembles."""

        return {
            name: {
                "observationCount": component.observation_count,
                "effectiveSampleSize": component.effective_sample_size,
                "missingHistoryFlag": component.missing_history,
                "daysSincePriorAppearance": component.days_since_prior_appearance,
                "entropy": component.entropy,
                "deviationFromLongTerm": component.deviation_from_long_term,
            }
            for name, component in self.components.items()
            if name != DIRECT_MODEL
        }

    @property
    def probability_matrices(self) -> dict[str, np.ndarray]:
        """Return the exact component-to-probability mapping expected by ensembles."""

        return {name: component.probabilities for name, component in self.components.items()}

    @property
    def batter_only_probabilities(self) -> dict[str, np.ndarray]:
        """Return aligned batter-only diagnostics where a component has them."""

        return {
            name: component.role_diagnostics["batter_probabilities"]
            for name, component in self.components.items()
            if "batter_probabilities" in component.role_diagnostics
        }

    @property
    def pitcher_only_probabilities(self) -> dict[str, np.ndarray]:
        """Return aligned pitcher-only diagnostics where a component has them."""

        return {
            name: component.role_diagnostics["pitcher_probabilities"]
            for name, component in self.components.items()
            if "pitcher_probabilities" in component.role_diagnostics
        }


@dataclass(frozen=True)
class SoftArchetypeModel:
    """Deterministic soft player memberships in canonical centroid order."""

    role: str
    player_ids: tuple[str, ...]
    player_memberships: np.ndarray
    centroids: np.ndarray
    player_observation_counts: np.ndarray
    default_membership: np.ndarray
    distance_temperature: float

    def __post_init__(self) -> None:
        if self.role not in {"batter", "pitcher"}:
            raise ValueError("archetype role must be batter or pitcher")
        rows = len(self.player_ids)
        if rows < 6 or len(set(self.player_ids)) != rows:
            raise ValueError("archetype player identities must be unique and sufficiently populated")
        memberships = np.asarray(self.player_memberships, dtype=np.float64)
        if memberships.shape != (rows, 6) or not np.isfinite(memberships).all() or np.any(memberships < 0.0):
            raise ValueError("player archetype memberships are invalid")
        if not np.allclose(memberships.sum(axis=1), 1.0, rtol=0.0, atol=1.0e-10):
            raise ValueError("player archetype memberships do not sum to one")
        centroids = validate_probability_matrix(self.centroids)
        if centroids.shape != (6, len(PA_CLASS_ORDER)):
            raise ValueError("archetype centroid architecture differs from six by eight")
        counts = np.asarray(self.player_observation_counts, dtype=np.float64)
        if counts.shape != (rows,) or not np.isfinite(counts).all() or np.any(counts <= 0.0):
            raise ValueError("archetype player observation counts are invalid")
        default = np.asarray(self.default_membership, dtype=np.float64)
        if (
            default.shape != (6,)
            or not np.isfinite(default).all()
            or np.any(default < 0.0)
            or not np.isclose(default.sum(), 1.0, rtol=0.0, atol=1.0e-10)
        ):
            raise ValueError("default archetype membership is invalid")
        if not math.isfinite(self.distance_temperature) or self.distance_temperature <= 0.0:
            raise ValueError("archetype distance temperature must be finite and positive")
        object.__setattr__(self, "centroids", centroids)

    def memberships_for(self, player_ids: Sequence[Any]) -> np.ndarray:
        """Return fitted memberships, or the training-population mixture if unseen."""

        lookup = {player_id: index for index, player_id in enumerate(self.player_ids)}
        result = np.empty((len(player_ids), self.centroids.shape[0]), dtype=np.float64)
        for row, raw in enumerate(player_ids):
            index = lookup.get(str(raw))
            result[row] = self.default_membership if index is None else self.player_memberships[index]
        totals = result.sum(axis=1)
        if not np.isfinite(result).all() or np.any(result < 0.0) or np.any(totals <= 0.0):
            raise RecentStateComponentError(f"{self.role} archetype memberships are invalid")
        return result / totals[:, None]


@dataclass(frozen=True)
class _HistorySeries:
    days: np.ndarray
    labels: np.ndarray
    residuals: np.ndarray


@dataclass(frozen=True)
class _PairSeries:
    days: np.ndarray
    labels: np.ndarray


@dataclass(frozen=True)
class StateAuthority:
    """A frozen, training-only authority used to score later target blocks."""

    config: StateComponentConfig
    class_order: tuple[str, ...]
    training_rows: int
    training_start_day: str
    training_end_day: str
    league_probabilities: np.ndarray
    batter_archetypes: SoftArchetypeModel
    pitcher_archetypes: SoftArchetypeModel
    cluster_matchup_probabilities: np.ndarray
    cluster_matchup_count: np.ndarray
    cluster_matchup_effective_sample_size: np.ndarray
    _batter_history: Mapping[str, _HistorySeries] = field(repr=False)
    _pitcher_history: Mapping[str, _HistorySeries] = field(repr=False)
    _pair_history: Mapping[tuple[str, str], _PairSeries] = field(repr=False)

    def __post_init__(self) -> None:
        self.config.validate()
        require_frozen_class_order(self.class_order)
        if self.training_rows <= 0 or not self._batter_history or not self._pitcher_history:
            raise ValueError("state authority has no training history")
        start = pd.Timestamp(self.training_start_day)
        end = pd.Timestamp(self.training_end_day)
        if start > end or end.year >= 2025:
            raise ValueError("state authority training dates are invalid")
        league = validate_probability_matrix(np.asarray(self.league_probabilities)[None, :])[0]
        expected_shape = (6, 6, len(PA_CLASS_ORDER))
        matchup = np.asarray(self.cluster_matchup_probabilities, dtype=np.float64)
        if matchup.shape != expected_shape:
            raise ValueError("cluster matchup probability architecture differs")
        validate_probability_matrix(matchup.reshape(-1, len(PA_CLASS_ORDER)))
        count = np.asarray(self.cluster_matchup_count, dtype=np.float64)
        effective = np.asarray(self.cluster_matchup_effective_sample_size, dtype=np.float64)
        if (
            count.shape != (6, 6)
            or effective.shape != (6, 6)
            or not np.isfinite(count).all()
            or not np.isfinite(effective).all()
            or np.any(count < 0.0)
            or np.any(effective < 0.0)
            or np.any(effective > count + 1.0e-8)
        ):
            raise ValueError("cluster matchup reliability arrays are invalid")
        object.__setattr__(self, "league_probabilities", league)


@dataclass(frozen=True)
class _RawRoleState:
    weighted_class_count: np.ndarray
    observation_count: np.ndarray
    total_weight: np.ndarray
    effective_sample_size: np.ndarray
    missing_history: np.ndarray
    days_since_prior_appearance: np.ndarray


@dataclass(frozen=True)
class _RoleStates:
    long_term: _RawRoleState
    recent_14: _RawRoleState
    recent_42: _RawRoleState
    decay_180: _RawRoleState
    decay_365: _RawRoleState
    residual_14_sum: np.ndarray
    residual_42_sum: np.ndarray


def _normalize_rows(values: Any) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] != len(PA_CLASS_ORDER):
        raise ValueError("probability values must be a non-empty governed-order matrix")
    if not np.isfinite(matrix).all() or np.any(matrix < 0.0):
        raise ValueError("probability values must be finite and nonnegative")
    totals = matrix.sum(axis=1)
    if np.any(totals <= 0.0):
        raise ValueError("probability rows must have positive mass")
    return validate_probability_matrix(matrix / totals[:, None])


def _entropy(probabilities: np.ndarray) -> np.ndarray:
    values = np.clip(probabilities, _EPSILON, 1.0)
    return -np.sum(probabilities * np.log(values), axis=1)


def _total_variation(probabilities: np.ndarray, reference: np.ndarray) -> np.ndarray:
    if probabilities.shape != reference.shape:
        raise ValueError("deviation inputs are not aligned")
    return 0.5 * np.sum(np.abs(probabilities - reference), axis=1)


def fixed_log_opinion_pool(
    batter_probabilities: Any,
    pitcher_allowed_probabilities: Any,
    league_probabilities: Any,
) -> np.ndarray:
    """Combine batter and pitcher distributions via the fixed benchmark.

    The unnormalized mass is ``batter * pitcher_allowed / league``.  Clipping
    is restricted to numerical protection against log zero; the output is
    then normalized exactly once.
    """

    batter = validate_probability_matrix(batter_probabilities)
    pitcher = validate_probability_matrix(pitcher_allowed_probabilities)
    if batter.shape != pitcher.shape:
        raise ValueError("batter and pitcher probability matrices are not aligned")
    league = np.asarray(league_probabilities, dtype=np.float64)
    if league.ndim == 1:
        if league.shape != (len(PA_CLASS_ORDER),):
            raise ValueError("league probabilities have the wrong class order")
        league = np.broadcast_to(league, batter.shape)
    if league.shape != batter.shape or not np.isfinite(league).all() or np.any(league <= 0.0):
        raise ValueError("league probabilities must be aligned, finite, and positive")
    log_mass = (
        np.log(np.clip(batter, _EPSILON, 1.0))
        + np.log(np.clip(pitcher, _EPSILON, 1.0))
        - np.log(np.clip(league, _EPSILON, 1.0))
    )
    log_mass -= np.max(log_mass, axis=1, keepdims=True)
    return _normalize_rows(np.exp(log_mass))


def _coerce_mask(mask: Any | None, rows: int, *, label: str) -> np.ndarray:
    if mask is None:
        return np.ones(rows, dtype=np.bool_)
    values = np.asarray(mask)
    if values.dtype.kind != "b" or values.ndim != 1 or values.shape[0] != rows:
        raise TypeError(f"{label} must be a boolean vector aligned to the frame")
    if not values.any():
        raise ValueError(f"{label} selects no rows")
    return values.astype(np.bool_, copy=True)


def _prepare_frame(
    frame: pd.DataFrame,
    config: StateComponentConfig,
    *,
    label: str,
    require_outcome: bool = True,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise TypeError(f"{label} must be a non-empty pandas DataFrame")
    required = {
        config.date_column,
        config.batter_column,
        config.pitcher_column,
        config.row_id_column,
    }
    if require_outcome:
        required.add(config.outcome_column)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise RecentStateComponentError(f"{label} columns missing: {missing}")
    result = frame[list(required)].copy()
    if result[config.row_id_column].isna().any() or result[config.row_id_column].duplicated().any():
        raise RecentStateComponentError(f"{label} row identities are null or duplicated")
    for entity_column in (config.batter_column, config.pitcher_column):
        if result[entity_column].isna().any():
            raise RecentStateComponentError(f"{label} {entity_column} contains missing identity")
        values = result[entity_column].astype(str).str.strip()
        if values.eq("").any():
            raise RecentStateComponentError(f"{label} {entity_column} contains blank identity")
        result[entity_column] = values
    dates = pd.to_datetime(result[config.date_column], errors="raise")
    if dates.isna().any() or not dates.dt.normalize().equals(dates):
        raise RecentStateComponentError(f"{label} dates must be complete calendar days")
    if (dates.dt.year >= 2025).any():
        raise RecentStateComponentError(f"{label} contains prohibited 2025-or-later data")
    result[config.date_column] = dates
    result["_day"] = (dates.astype("int64") // _DAY_NANOS).astype(np.int64)
    if require_outcome:
        result["_label"] = encode_labels(result[config.outcome_column].astype(str).to_numpy())
    result[config.row_id_column] = result[config.row_id_column].astype(str)
    return result


def _history_index(
    frame: pd.DataFrame,
    direct_probabilities: np.ndarray,
    *,
    entity_column: str,
    config: StateComponentConfig,
) -> dict[str, _HistorySeries]:
    labels = frame["_label"].to_numpy(dtype=np.int64)
    one_hot = np.eye(len(PA_CLASS_ORDER), dtype=np.float64)[labels]
    residuals = one_hot - direct_probabilities
    result: dict[str, _HistorySeries] = {}
    grouped = frame.groupby(entity_column, sort=True, dropna=False).indices
    for raw_entity, raw_positions in grouped.items():
        positions = np.asarray(raw_positions, dtype=np.int64)
        order = np.argsort(frame.iloc[positions]["_day"].to_numpy(dtype=np.int64), kind="mergesort")
        positions = positions[order]
        result[str(raw_entity)] = _HistorySeries(
            days=frame.iloc[positions]["_day"].to_numpy(dtype=np.int64),
            labels=labels[positions].copy(),
            residuals=residuals[positions].copy(),
        )
    return result


def _pair_index(frame: pd.DataFrame, config: StateComponentConfig) -> dict[tuple[str, str], _PairSeries]:
    labels = frame["_label"].to_numpy(dtype=np.int64)
    result: dict[tuple[str, str], _PairSeries] = {}
    grouped = frame.groupby([config.batter_column, config.pitcher_column], sort=True, dropna=False).indices
    for raw_pair, raw_positions in grouped.items():
        positions = np.asarray(raw_positions, dtype=np.int64)
        days = frame.iloc[positions]["_day"].to_numpy(dtype=np.int64)
        order = np.argsort(days, kind="mergesort")
        result[(str(raw_pair[0]), str(raw_pair[1]))] = _PairSeries(
            days=days[order].copy(), labels=labels[positions[order]].copy()
        )
    return result


def _fit_soft_archetypes(
    history: Mapping[str, _HistorySeries],
    league: np.ndarray,
    *,
    role: str,
    archetype_count: int,
    prior_strength: float,
    seed: int,
    n_init: int,
) -> SoftArchetypeModel:
    player_ids = tuple(sorted(history))
    if len(player_ids) < archetype_count:
        raise RecentStateComponentError(
            f"{role} training history has {len(player_ids)} players; "
            f"{archetype_count} archetypes require at least that many"
        )
    counts = np.asarray([history[player_id].labels.size for player_id in player_ids], dtype=np.float64)
    class_counts = np.vstack(
        [np.bincount(history[player_id].labels, minlength=len(PA_CLASS_ORDER)) for player_id in player_ids]
    ).astype(np.float64)
    features = (class_counts + prior_strength * league[None, :]) / (counts[:, None] + prior_strength)
    estimator = KMeans(
        n_clusters=archetype_count,
        init="k-means++",
        n_init=n_init,
        max_iter=300,
        tol=1.0e-6,
        random_state=seed,
        algorithm="lloyd",
    )
    estimator.fit(features, sample_weight=np.sqrt(counts))
    centroids = _normalize_rows(np.clip(estimator.cluster_centers_, 0.0, None))
    canonical_order = np.lexsort(tuple(centroids[:, index] for index in range(len(PA_CLASS_ORDER) - 1, -1, -1)))
    centroids = centroids[canonical_order]
    squared_distance = np.sum((features[:, None, :] - centroids[None, :, :]) ** 2, axis=2)
    positive = squared_distance[squared_distance > 1.0e-15]
    temperature = float(np.median(positive)) if positive.size else 1.0
    temperature = max(temperature, 1.0e-6)
    logits = -squared_distance / temperature
    logits -= np.max(logits, axis=1, keepdims=True)
    memberships = np.exp(logits)
    memberships /= memberships.sum(axis=1, keepdims=True)
    population = np.sum(memberships * counts[:, None], axis=0)
    default = population / population.sum()
    return SoftArchetypeModel(
        role=role,
        player_ids=player_ids,
        player_memberships=memberships,
        centroids=centroids,
        player_observation_counts=counts,
        default_membership=default,
        distance_temperature=temperature,
    )


def _fit_cluster_matchups(
    frame: pd.DataFrame,
    batter_model: SoftArchetypeModel,
    pitcher_model: SoftArchetypeModel,
    league: np.ndarray,
    config: StateComponentConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    batter_membership = batter_model.memberships_for(frame[config.batter_column].astype(str).tolist())
    pitcher_membership = pitcher_model.memberships_for(frame[config.pitcher_column].astype(str).tolist())
    labels = frame["_label"].to_numpy(dtype=np.int64)
    shape = (config.batter_archetypes, config.pitcher_archetypes, len(PA_CLASS_ORDER))
    weighted_class_count = np.zeros(shape, dtype=np.float64)
    for class_index in range(len(PA_CLASS_ORDER)):
        selected = labels == class_index
        weighted_class_count[:, :, class_index] = (
            batter_membership[selected].T @ pitcher_membership[selected]
        )
    total_weight_squared = (
        (batter_membership * batter_membership).T
        @ (pitcher_membership * pitcher_membership)
    )
    count = weighted_class_count.sum(axis=2)
    effective = np.divide(
        count * count,
        total_weight_squared,
        out=np.zeros_like(count),
        where=total_weight_squared > 0.0,
    )
    probabilities = (
        weighted_class_count + config.cluster_matchup_prior_strength * league[None, None, :]
    ) / (count[:, :, None] + config.cluster_matchup_prior_strength)
    flat = _normalize_rows(probabilities.reshape(-1, len(PA_CLASS_ORDER)))
    return flat.reshape(shape), count, np.minimum(effective, count)


def fit_state_authority(
    frame: pd.DataFrame,
    fold_safe_direct_probabilities: Any,
    *,
    training_mask: Any | None = None,
    config: StateComponentConfig | None = None,
) -> StateAuthority:
    """Fit all state priors and archetypes on a supplied training slice only.

    ``fold_safe_direct_probabilities`` must be aligned to ``frame`` and must
    already satisfy the caller's OOF provenance rule.  This module cannot and
    does not refit the Direct Gold model implicitly.
    """

    active = (config or StateComponentConfig()).validate()
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise TypeError("state training frame must be a non-empty pandas DataFrame")
    selected = _coerce_mask(training_mask, len(frame), label="training_mask")
    raw_direct = np.asarray(fold_safe_direct_probabilities)
    if raw_direct.ndim != 2 or raw_direct.shape[0] != len(frame):
        raise ValueError("training Direct probabilities are not aligned to the frame")
    prepared = _prepare_frame(
        frame.loc[selected].reset_index(drop=True),
        active,
        label="state training frame",
        require_outcome=True,
    )
    direct = validate_probability_matrix(raw_direct[selected])
    labels = prepared["_label"].to_numpy(dtype=np.int64)
    class_count = np.bincount(labels, minlength=len(PA_CLASS_ORDER)).astype(np.float64)
    uniform = np.full(len(PA_CLASS_ORDER), 1.0 / len(PA_CLASS_ORDER), dtype=np.float64)
    league = (
        class_count + active.league_uniform_prior_strength * uniform
    ) / (class_count.sum() + active.league_uniform_prior_strength)
    league = validate_probability_matrix(league[None, :])[0]
    batter_history = _history_index(
        prepared, direct, entity_column=active.batter_column, config=active
    )
    pitcher_history = _history_index(
        prepared, direct, entity_column=active.pitcher_column, config=active
    )
    batter_archetypes = _fit_soft_archetypes(
        batter_history,
        league,
        role="batter",
        archetype_count=active.batter_archetypes,
        prior_strength=active.long_term_role_prior_strength,
        seed=active.random_seed,
        n_init=active.kmeans_n_init,
    )
    pitcher_archetypes = _fit_soft_archetypes(
        pitcher_history,
        league,
        role="pitcher",
        archetype_count=active.pitcher_archetypes,
        prior_strength=active.long_term_role_prior_strength,
        seed=active.random_seed + 1,
        n_init=active.kmeans_n_init,
    )
    matchup_probabilities, matchup_count, matchup_effective = _fit_cluster_matchups(
        prepared, batter_archetypes, pitcher_archetypes, league, active
    )
    dates = prepared[active.date_column]
    return StateAuthority(
        config=active,
        class_order=PA_CLASS_ORDER,
        training_rows=len(prepared),
        training_start_day=dates.min().strftime("%Y-%m-%d"),
        training_end_day=dates.max().strftime("%Y-%m-%d"),
        league_probabilities=league,
        batter_archetypes=batter_archetypes,
        pitcher_archetypes=pitcher_archetypes,
        cluster_matchup_probabilities=matchup_probabilities,
        cluster_matchup_count=matchup_count,
        cluster_matchup_effective_sample_size=matchup_effective,
        _batter_history=batter_history,
        _pitcher_history=pitcher_history,
        _pair_history=_pair_index(prepared, active),
    )


def _empty_raw(rows: int) -> _RawRoleState:
    return _RawRoleState(
        weighted_class_count=np.zeros((rows, len(PA_CLASS_ORDER)), dtype=np.float64),
        observation_count=np.zeros(rows, dtype=np.float64),
        total_weight=np.zeros(rows, dtype=np.float64),
        effective_sample_size=np.zeros(rows, dtype=np.float64),
        missing_history=np.ones(rows, dtype=np.bool_),
        days_since_prior_appearance=np.full(rows, np.nan, dtype=np.float64),
    )


def _raw_state(
    class_count: np.ndarray,
    observation_count: np.ndarray,
    total_weight: np.ndarray,
    effective: np.ndarray,
    days_since: np.ndarray,
) -> _RawRoleState:
    return _RawRoleState(
        weighted_class_count=class_count,
        observation_count=observation_count,
        total_weight=total_weight,
        effective_sample_size=np.minimum(effective, observation_count),
        missing_history=observation_count <= 0.0,
        days_since_prior_appearance=days_since,
    )


def _calculate_role_states(
    history: Mapping[str, _HistorySeries],
    target_entities: np.ndarray,
    target_days: np.ndarray,
) -> _RoleStates:
    rows = target_days.size
    class_count = len(PA_CLASS_ORDER)
    long_classes = np.zeros((rows, class_count), dtype=np.float64)
    count14 = np.zeros((rows, class_count), dtype=np.float64)
    count42 = np.zeros((rows, class_count), dtype=np.float64)
    decay180 = np.zeros((rows, class_count), dtype=np.float64)
    decay365 = np.zeros((rows, class_count), dtype=np.float64)
    residual14 = np.zeros((rows, class_count), dtype=np.float64)
    residual42 = np.zeros((rows, class_count), dtype=np.float64)
    long_n = np.zeros(rows, dtype=np.float64)
    n14 = np.zeros(rows, dtype=np.float64)
    n42 = np.zeros(rows, dtype=np.float64)
    weight180 = np.zeros(rows, dtype=np.float64)
    weight365 = np.zeros(rows, dtype=np.float64)
    ess180 = np.zeros(rows, dtype=np.float64)
    ess365 = np.zeros(rows, dtype=np.float64)
    days_since = np.full(rows, np.nan, dtype=np.float64)

    positions_by_entity: dict[str, list[int]] = {}
    for position, entity in enumerate(target_entities):
        positions_by_entity.setdefault(str(entity), []).append(position)

    identity = np.eye(class_count, dtype=np.float64)
    for entity, raw_positions in positions_by_entity.items():
        series = history.get(entity)
        if series is None:
            continue
        positions = np.asarray(raw_positions, dtype=np.int64)
        unique_days, inverse = np.unique(target_days[positions], return_inverse=True)
        one_hot = identity[series.labels]
        prefix_count = np.vstack([np.zeros((1, class_count)), np.cumsum(one_hot, axis=0)])
        prefix_residual = np.vstack(
            [np.zeros((1, class_count)), np.cumsum(series.residuals, axis=0)]
        )
        reference_day = int(series.days[-1])
        decay_summaries: dict[float, tuple[np.ndarray, float, float]] = {}
        for half_life in (180.0, 365.0):
            reference_weights = np.power(0.5, (reference_day - series.days) / half_life)
            decay_summaries[half_life] = (
                np.bincount(
                    series.labels,
                    weights=reference_weights,
                    minlength=class_count,
                ),
                float(reference_weights.sum()),
                float(np.dot(reference_weights, reference_weights)),
            )
        for date_index, target_day in enumerate(unique_days):
            selected_positions = positions[inverse == date_index]
            end = int(np.searchsorted(series.days, target_day, side="left"))
            if end <= 0:
                continue
            prior_days = series.days[:end]
            long_value = prefix_count[end]
            long_classes[selected_positions] = long_value
            long_n[selected_positions] = float(end)
            age = float(target_day - prior_days[-1])
            if age < 1.0:
                raise RecentStateComponentError("current-day history escaped the strict cutoff")
            days_since[selected_positions] = age

            for window, count_target, n_target, residual_target in (
                (14, count14, n14, residual14),
                (42, count42, n42, residual42),
            ):
                start = int(np.searchsorted(series.days, target_day - window, side="left"))
                sample = end - start
                count_target[selected_positions] = prefix_count[end] - prefix_count[start]
                residual_target[selected_positions] = prefix_residual[end] - prefix_residual[start]
                n_target[selected_positions] = float(sample)

            for half_life, class_target, weight_target, ess_target in (
                (180.0, decay180, weight180, ess180),
                (365.0, decay365, weight365, ess365),
            ):
                reference_classes, reference_total, reference_square = decay_summaries[half_life]
                scale = float(np.power(0.5, (target_day - reference_day) / half_life))
                total = reference_total * scale
                square = reference_square * scale * scale
                class_target[selected_positions] = reference_classes * scale
                weight_target[selected_positions] = total
                ess_target[selected_positions] = (total * total / square) if square > 0.0 else 0.0

    long = _raw_state(long_classes, long_n, long_n, long_n, days_since)
    recent14 = _raw_state(count14, n14, n14, n14, days_since)
    recent42 = _raw_state(count42, n42, n42, n42, days_since)
    decay180_state = _raw_state(decay180, long_n, weight180, ess180, days_since)
    decay365_state = _raw_state(decay365, long_n, weight365, ess365, days_since)
    return _RoleStates(
        long_term=long,
        recent_14=recent14,
        recent_42=recent42,
        decay_180=decay180_state,
        decay_365=decay365_state,
        residual_14_sum=residual14,
        residual_42_sum=residual42,
    )


def _shrink(raw: _RawRoleState, prior: np.ndarray, strength: float) -> np.ndarray:
    if prior.ndim == 1:
        prior = np.broadcast_to(prior, raw.weighted_class_count.shape)
    denominator = raw.total_weight[:, None] + strength
    return _normalize_rows((raw.weighted_class_count + strength * prior) / denominator)


def _combined_reliability(
    batter: _RawRoleState,
    pitcher: _RawRoleState,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    count = batter.observation_count + pitcher.observation_count
    effective = batter.effective_sample_size + pitcher.effective_sample_size
    missing = batter.missing_history | pitcher.missing_history
    days = np.maximum(
        batter.days_since_prior_appearance,
        pitcher.days_since_prior_appearance,
    )
    return count, effective, missing, days


def _role_diagnostics(
    batter_probabilities: np.ndarray,
    pitcher_probabilities: np.ndarray,
    batter: _RawRoleState,
    pitcher: _RawRoleState,
) -> dict[str, np.ndarray]:
    return {
        "batter_probabilities": batter_probabilities,
        "pitcher_probabilities": pitcher_probabilities,
        "batter_observation_count": batter.observation_count,
        "pitcher_observation_count": pitcher.observation_count,
        "batter_effective_sample_size": batter.effective_sample_size,
        "pitcher_effective_sample_size": pitcher.effective_sample_size,
        "batter_missing_history": batter.missing_history,
        "pitcher_missing_history": pitcher.missing_history,
        "batter_days_since_prior_appearance": batter.days_since_prior_appearance,
        "pitcher_days_since_prior_appearance": pitcher.days_since_prior_appearance,
        "batter_entropy": _entropy(batter_probabilities),
        "pitcher_entropy": _entropy(pitcher_probabilities),
    }


def _component(
    name: str,
    probabilities: np.ndarray,
    batter_probabilities: np.ndarray,
    pitcher_probabilities: np.ndarray,
    batter_raw: _RawRoleState,
    pitcher_raw: _RawRoleState,
    long_reference: np.ndarray,
) -> ComponentEstimate:
    count, effective, missing, days = _combined_reliability(batter_raw, pitcher_raw)
    return ComponentEstimate(
        name=name,
        probabilities=probabilities,
        observation_count=count,
        effective_sample_size=effective,
        missing_history=missing,
        days_since_prior_appearance=days,
        entropy=_entropy(probabilities),
        deviation_from_long_term=_total_variation(probabilities, long_reference),
        role_diagnostics=_role_diagnostics(
            batter_probabilities, pitcher_probabilities, batter_raw, pitcher_raw
        ),
    )


def _score_cluster_matchup(
    authority: StateAuthority,
    batter_ids: np.ndarray,
    pitcher_ids: np.ndarray,
    batter_long: _RawRoleState,
    pitcher_long: _RawRoleState,
    long_reference: np.ndarray,
) -> ComponentEstimate:
    batter_membership = authority.batter_archetypes.memberships_for(batter_ids)
    pitcher_membership = authority.pitcher_archetypes.memberships_for(pitcher_ids)
    probabilities = np.einsum(
        "ni,nj,ijk->nk",
        batter_membership,
        pitcher_membership,
        authority.cluster_matchup_probabilities,
        optimize=True,
    )
    probabilities = _normalize_rows(probabilities)
    pair_weight = batter_membership[:, :, None] * pitcher_membership[:, None, :]
    count = np.sum(pair_weight * authority.cluster_matchup_count[None, :, :], axis=(1, 2))
    effective = np.sum(
        pair_weight * authority.cluster_matchup_effective_sample_size[None, :, :], axis=(1, 2)
    )
    effective = np.minimum(effective, count)
    batter_known = np.isin(batter_ids, np.asarray(authority.batter_archetypes.player_ids, dtype=object))
    pitcher_known = np.isin(pitcher_ids, np.asarray(authority.pitcher_archetypes.player_ids, dtype=object))
    missing = ~(batter_known & pitcher_known)
    days = np.where(
        missing,
        np.nan,
        np.maximum(
            batter_long.days_since_prior_appearance,
            pitcher_long.days_since_prior_appearance,
        ),
    )
    batter_probabilities = _normalize_rows(batter_membership @ authority.batter_archetypes.centroids)
    pitcher_probabilities = _normalize_rows(pitcher_membership @ authority.pitcher_archetypes.centroids)
    return ComponentEstimate(
        name=CLUSTER_MATCHUP,
        probabilities=probabilities,
        observation_count=count,
        effective_sample_size=effective,
        missing_history=missing,
        days_since_prior_appearance=days,
        entropy=_entropy(probabilities),
        deviation_from_long_term=_total_variation(probabilities, long_reference),
        role_diagnostics={
            "batter_probabilities": batter_probabilities,
            "pitcher_probabilities": pitcher_probabilities,
            "batter_memberships": batter_membership,
            "pitcher_memberships": pitcher_membership,
            "batter_missing_history": ~batter_known,
            "pitcher_missing_history": ~pitcher_known,
        },
    )


def _score_exact_bvp(
    authority: StateAuthority,
    batter_ids: np.ndarray,
    pitcher_ids: np.ndarray,
    target_days: np.ndarray,
    cluster: ComponentEstimate,
    long_reference: np.ndarray,
) -> ComponentEstimate:
    rows = target_days.size
    class_count = np.zeros((rows, len(PA_CLASS_ORDER)), dtype=np.float64)
    count = np.zeros(rows, dtype=np.float64)
    days_since = np.full(rows, np.nan, dtype=np.float64)
    positions_by_pair: dict[tuple[str, str], list[int]] = {}
    for row, (batter, pitcher) in enumerate(zip(batter_ids, pitcher_ids)):
        positions_by_pair.setdefault((str(batter), str(pitcher)), []).append(row)
    for pair, raw_positions in positions_by_pair.items():
        series = authority._pair_history.get(pair)
        if series is None:
            continue
        positions = np.asarray(raw_positions, dtype=np.int64)
        if np.any(series.days[-1] >= target_days[positions]):
            raise RecentStateComponentError("exact BvP history is not strictly prior")
        pair_count = np.bincount(series.labels, minlength=len(PA_CLASS_ORDER))
        class_count[positions] = pair_count
        count[positions] = float(series.labels.size)
        days_since[positions] = target_days[positions] - series.days[-1]
    strength = authority.config.exact_bvp_prior_strength
    probabilities = _normalize_rows(
        (class_count + strength * cluster.probabilities) / (count[:, None] + strength)
    )
    return ComponentEstimate(
        name=SHRUNK_EXACT_BVP,
        probabilities=probabilities,
        observation_count=count,
        effective_sample_size=count.copy(),
        missing_history=count <= 0.0,
        days_since_prior_appearance=days_since,
        entropy=_entropy(probabilities),
        deviation_from_long_term=_total_variation(probabilities, long_reference),
        role_diagnostics={
            "cluster_prior_probabilities": cluster.probabilities,
            "exact_pair_weight": count / (count + strength),
        },
    )


def _residual_correction(
    residual_sum: np.ndarray,
    raw: _RawRoleState,
    strength: float,
) -> np.ndarray:
    denominator = raw.observation_count + strength
    return residual_sum / denominator[:, None]


def _score_residual_form(
    direct: np.ndarray,
    batter_states: _RoleStates,
    pitcher_states: _RoleStates,
    long_reference: np.ndarray,
    config: StateComponentConfig,
) -> ComponentEstimate:
    batter_14 = _residual_correction(
        batter_states.residual_14_sum,
        batter_states.recent_14,
        config.residual_14_prior_strength,
    )
    pitcher_14 = _residual_correction(
        pitcher_states.residual_14_sum,
        pitcher_states.recent_14,
        config.residual_14_prior_strength,
    )
    batter_42 = _residual_correction(
        batter_states.residual_42_sum,
        batter_states.recent_42,
        config.residual_42_prior_strength,
    )
    pitcher_42 = _residual_correction(
        pitcher_states.residual_42_sum,
        pitcher_states.recent_42,
        config.residual_42_prior_strength,
    )
    batter_correction = (batter_14 + batter_42) / 2.0
    pitcher_correction = (pitcher_14 + pitcher_42) / 2.0
    corrections = (batter_correction + pitcher_correction) / 2.0
    # Exponentiation applies the expectation-adjusted residual in log-mass
    # space.  It preserves positivity without allowing a broad clipping rule.
    log_mass = np.log(np.clip(direct, _EPSILON, 1.0)) + corrections
    log_mass -= np.max(log_mass, axis=1, keepdims=True)
    probabilities = _normalize_rows(np.exp(log_mass))
    batter_log_mass = np.log(np.clip(direct, _EPSILON, 1.0)) + batter_correction
    batter_log_mass -= np.max(batter_log_mass, axis=1, keepdims=True)
    batter_probabilities = _normalize_rows(np.exp(batter_log_mass))
    pitcher_log_mass = np.log(np.clip(direct, _EPSILON, 1.0)) + pitcher_correction
    pitcher_log_mass -= np.max(pitcher_log_mass, axis=1, keepdims=True)
    pitcher_probabilities = _normalize_rows(np.exp(pitcher_log_mass))
    # The 14-day observations are a subset of the 42-day observations.  Count
    # the union once rather than inflating reliability by double-counting it.
    count = (
        batter_states.recent_42.observation_count
        + pitcher_states.recent_42.observation_count
    )
    effective = count.copy()
    missing = (
        batter_states.recent_42.missing_history
        | pitcher_states.recent_42.missing_history
    )
    days = np.maximum(
        batter_states.long_term.days_since_prior_appearance,
        pitcher_states.long_term.days_since_prior_appearance,
    )
    return ComponentEstimate(
        name=RECENT_RESIDUAL_FORM,
        probabilities=probabilities,
        observation_count=count,
        effective_sample_size=effective,
        missing_history=missing,
        days_since_prior_appearance=days,
        entropy=_entropy(probabilities),
        deviation_from_long_term=_total_variation(probabilities, long_reference),
        role_diagnostics={
            "batter_probabilities": batter_probabilities,
            "pitcher_probabilities": pitcher_probabilities,
            "batter_14_residual": batter_14,
            "pitcher_14_residual": pitcher_14,
            "batter_42_residual": batter_42,
            "pitcher_42_residual": pitcher_42,
        },
    )


def score_state_components(
    authority: StateAuthority,
    target_frame: pd.DataFrame,
    direct_probabilities: Any,
    *,
    target_mask: Any | None = None,
) -> StateComponentBundle:
    """Score all fixed components on a target block later than the authority.

    The strict block boundary is intentional: state is frozen before the first
    target day, matching the six rolling-origin Phase 7B4 development blocks.
    """

    if not isinstance(authority, StateAuthority):
        raise TypeError("authority must be a fitted StateAuthority")
    config = authority.config.validate()
    if not isinstance(target_frame, pd.DataFrame) or target_frame.empty:
        raise TypeError("state target frame must be a non-empty pandas DataFrame")
    selected = _coerce_mask(target_mask, len(target_frame), label="target_mask")
    raw_direct = np.asarray(direct_probabilities)
    if raw_direct.ndim != 2 or raw_direct.shape[0] != len(target_frame):
        raise ValueError("target Direct probabilities are not aligned to the frame")
    prepared = _prepare_frame(
        target_frame.loc[selected].reset_index(drop=True),
        config,
        label="state target frame",
        require_outcome=False,
    )
    direct = validate_probability_matrix(raw_direct[selected])
    training_end = pd.Timestamp(authority.training_end_day)
    target_start = prepared[config.date_column].min()
    if training_end >= target_start:
        raise RecentStateComponentError(
            "state authority is not strictly earlier than the complete target block"
        )
    batter_ids = prepared[config.batter_column].astype(str).to_numpy(dtype=object)
    pitcher_ids = prepared[config.pitcher_column].astype(str).to_numpy(dtype=object)
    target_days = prepared["_day"].to_numpy(dtype=np.int64)
    batter_states = _calculate_role_states(authority._batter_history, batter_ids, target_days)
    pitcher_states = _calculate_role_states(authority._pitcher_history, pitcher_ids, target_days)

    batter_long = _shrink(
        batter_states.long_term,
        authority.league_probabilities,
        config.long_term_role_prior_strength,
    )
    pitcher_long = _shrink(
        pitcher_states.long_term,
        authority.league_probabilities,
        config.long_term_role_prior_strength,
    )
    long_combined = fixed_log_opinion_pool(
        batter_long, pitcher_long, authority.league_probabilities
    )

    components: dict[str, ComponentEstimate] = {}
    rows = len(prepared)
    components[DIRECT_MODEL] = ComponentEstimate(
        name=DIRECT_MODEL,
        probabilities=direct,
        observation_count=np.zeros(rows, dtype=np.float64),
        effective_sample_size=np.zeros(rows, dtype=np.float64),
        missing_history=np.zeros(rows, dtype=np.bool_),
        days_since_prior_appearance=np.full(rows, np.nan, dtype=np.float64),
        entropy=_entropy(direct),
        deviation_from_long_term=_total_variation(direct, long_combined),
    )
    components[LONG_TERM_STATE] = _component(
        LONG_TERM_STATE,
        long_combined,
        batter_long,
        pitcher_long,
        batter_states.long_term,
        pitcher_states.long_term,
        long_combined,
    )

    for name, batter_raw, pitcher_raw, strength in (
        (
            RECENT_14_DAY_STATE,
            batter_states.recent_14,
            pitcher_states.recent_14,
            config.recent_14_prior_strength,
        ),
        (
            RECENT_42_DAY_STATE,
            batter_states.recent_42,
            pitcher_states.recent_42,
            config.recent_42_prior_strength,
        ),
        (
            DECAY_180_DAY_STATE,
            batter_states.decay_180,
            pitcher_states.decay_180,
            config.decay_prior_strength,
        ),
        (
            DECAY_365_DAY_STATE,
            batter_states.decay_365,
            pitcher_states.decay_365,
            config.decay_prior_strength,
        ),
    ):
        batter_probability = _shrink(batter_raw, batter_long, strength)
        pitcher_probability = _shrink(pitcher_raw, pitcher_long, strength)
        combined = fixed_log_opinion_pool(
            batter_probability, pitcher_probability, authority.league_probabilities
        )
        components[name] = _component(
            name,
            combined,
            batter_probability,
            pitcher_probability,
            batter_raw,
            pitcher_raw,
            long_combined,
        )

    cluster = _score_cluster_matchup(
        authority,
        batter_ids,
        pitcher_ids,
        batter_states.long_term,
        pitcher_states.long_term,
        long_combined,
    )
    components[CLUSTER_MATCHUP] = cluster
    components[SHRUNK_EXACT_BVP] = _score_exact_bvp(
        authority, batter_ids, pitcher_ids, target_days, cluster, long_combined
    )
    components[RECENT_RESIDUAL_FORM] = _score_residual_form(
        direct, batter_states, pitcher_states, long_combined, config
    )
    if tuple(components) != COMPONENT_ORDER:
        raise RecentStateComponentError("component construction order drifted")
    return StateComponentBundle(
        row_ids=tuple(prepared[config.row_id_column].astype(str).tolist()),
        class_order=PA_CLASS_ORDER,
        components=components,
        training_end_day=authority.training_end_day,
        target_start_day=target_start.strftime("%Y-%m-%d"),
        target_end_day=prepared[config.date_column].max().strftime("%Y-%m-%d"),
    )


def build_fold_state_components(
    frame: pd.DataFrame,
    fold_safe_direct_probabilities: Any,
    *,
    training_mask: Any,
    validation_mask: Any,
    config: StateComponentConfig | None = None,
) -> tuple[StateAuthority, StateComponentBundle]:
    """Convenience wrapper for one externally defined rolling-origin fold."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise TypeError("frame must be a non-empty pandas DataFrame")
    direct = np.asarray(fold_safe_direct_probabilities)
    if direct.ndim != 2 or direct.shape[0] != len(frame):
        raise ValueError("Direct probabilities are not aligned to the fold frame")
    train = _coerce_mask(training_mask, len(frame), label="training_mask")
    validation = _coerce_mask(validation_mask, len(frame), label="validation_mask")
    if np.any(train & validation):
        raise RecentStateComponentError("rolling training and validation masks overlap")
    authority = fit_state_authority(
        frame,
        direct,
        training_mask=train,
        config=config,
    )
    bundle = score_state_components(
        authority,
        frame,
        direct,
        target_mask=validation,
    )
    return authority, bundle


def reliability_feature_matrix(
    bundle: StateComponentBundle,
    *,
    component_names: Sequence[str] = COMPONENT_ORDER,
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Build the fixed reliability-gated stacker inputs from a component bundle.

    Features contain component log probabilities; every empirical reliability
    field; Direct-versus-component disagreement; and classwise recent-minus-
    long-term differences.  No target labels are consumed.
    """

    requested = tuple(component_names)
    unknown = sorted(set(requested) - set(COMPONENT_ORDER))
    if unknown or len(set(requested)) != len(requested):
        raise ValueError(f"invalid or duplicate component names: {unknown}")
    rows = len(bundle.row_ids)
    columns: list[np.ndarray] = []
    names: list[str] = []
    direct = bundle.components[DIRECT_MODEL].probabilities
    for name in requested:
        component = bundle.components[name]
        log_probabilities = np.log(np.clip(component.probabilities, _EPSILON, 1.0))
        columns.append(log_probabilities)
        names.extend(f"{name}__log_probability__{class_name}" for class_name in PA_CLASS_ORDER)
        if name != DIRECT_MODEL:
            scalar_values = (
                ("observation_count", component.observation_count),
                ("effective_sample_size", component.effective_sample_size),
                ("missing_history", component.missing_history.astype(np.float64)),
                ("days_since_prior_appearance", np.nan_to_num(
                    component.days_since_prior_appearance, nan=0.0
                )),
                ("entropy", component.entropy),
                ("deviation_from_long_term", component.deviation_from_long_term),
                (
                    "direct_total_variation_disagreement",
                    _total_variation(component.probabilities, direct),
                ),
            )
            for suffix, values in scalar_values:
                columns.append(np.asarray(values, dtype=np.float64)[:, None])
                names.append(f"{name}__{suffix}")
    long_probabilities = bundle.components[LONG_TERM_STATE].probabilities
    for recent_name in (RECENT_14_DAY_STATE, RECENT_42_DAY_STATE, RECENT_RESIDUAL_FORM):
        difference = bundle.components[recent_name].probabilities - long_probabilities
        columns.append(difference)
        names.extend(
            f"{recent_name}__minus_long_term__{class_name}" for class_name in PA_CLASS_ORDER
        )
    matrix = np.concatenate(columns, axis=1)
    if matrix.shape != (rows, len(names)) or not np.isfinite(matrix).all():
        raise RecentStateComponentError("reliability feature matrix is invalid")
    return matrix, tuple(names)


__all__ = [
    "CLUSTER_MATCHUP",
    "COMPONENT_ORDER",
    "ComponentEstimate",
    "DECAY_180_DAY_STATE",
    "DECAY_365_DAY_STATE",
    "DIRECT_MODEL",
    "EMPIRICAL_COMPONENT_ORDER",
    "LONG_TERM_STATE",
    "RECENT_14_DAY_STATE",
    "RECENT_42_DAY_STATE",
    "RECENT_RESIDUAL_FORM",
    "RANDOM_SEED",
    "RecentStateComponentError",
    "SCHEMA_VERSION",
    "SHRUNK_EXACT_BVP",
    "SoftArchetypeModel",
    "StateAuthority",
    "StateComponentBundle",
    "StateComponentConfig",
    "build_fold_state_components",
    "fit_state_authority",
    "fixed_log_opinion_pool",
    "reliability_feature_matrix",
    "score_state_components",
]
