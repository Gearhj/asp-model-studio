"""Date-atomic state and matchup components for the Phase 7B5 study.

The module has no filesystem or model-fitting authority.  A caller supplies a
governed in-memory frame and Direct Gold probabilities with an explicit
per-row chronological training cutoff.  State for a score date ``D`` is built
only from outcomes whose ``game_date < D``.  The complete date is appended in
one operation after it has been scored, so plate appearances on the same date
can never affect one another.

Player archetypes are fitted once from the initial training slice and are
never refitted while a validation or holdout block advances.  Expectation-
adjusted residual history can enter the engine only through
``ChronologicalDirectLedger``; raw probability matrices are not accepted by
the public fit or score APIs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from ..sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    require_frozen_class_order,
    validate_probability_matrix,
)
from .recent_state_components import (
    ComponentEstimate,
    SoftArchetypeModel,
    _fit_soft_archetypes,
    fixed_log_opinion_pool,
)
from .walk_forward_ensemble import (
    CLUSTER_MATCHUP,
    DECAY_180_DAY_STATE,
    DECAY_365_DAY_STATE,
    DIRECT_GOLD,
    RECENT_14_DAY_STATE,
    RECENT_42_DAY_STATE,
    RECENT_RESIDUAL_FORM,
    ROLLING_365_DAY_STATE,
    ROLLING_730_DAY_STATE,
    SHRUNK_EXACT_BVP,
    WALK_FORWARD_COMPONENT_ORDER,
)


SCHEMA_VERSION = "MLB_GOLD_WALK_FORWARD_STATE_V1"
RESIDUAL_EXPECTATION_SOURCE = "CALLER_PROVIDED_CHRONOLOGICAL_OOF_DIRECT_LEDGER"
RANDOM_SEED = 20_260_826

_DAY_NANOS = 86_400_000_000_000
_EPSILON = 1.0e-12
_CLASS_COUNT = len(PA_CLASS_ORDER)


class WalkForwardStateError(RuntimeError):
    """Raised when a row, probability, or temporal state contract differs."""


@dataclass(frozen=True)
class WalkForwardStateConfig:
    """Fixed state constants; none is a tuning grid."""

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
    rolling_365_prior_strength: float = 24.0
    rolling_730_prior_strength: float = 24.0
    decay_prior_strength: float = 24.0
    cluster_matchup_prior_strength: float = 30.0
    exact_bvp_prior_strength: float = 50.0
    residual_14_prior_strength: float = 30.0
    residual_42_prior_strength: float = 45.0
    batter_archetypes: int = 6
    pitcher_archetypes: int = 6
    random_seed: int = RANDOM_SEED
    kmeans_n_init: int = 20

    def validate(self) -> "WalkForwardStateConfig":
        require_frozen_class_order(self.class_order)
        columns = (
            self.date_column,
            self.outcome_column,
            self.batter_column,
            self.pitcher_column,
            self.row_id_column,
        )
        if not all(isinstance(value, str) and value.strip() for value in columns):
            raise ValueError("walk-forward column names must be non-empty strings")
        strengths = (
            self.league_uniform_prior_strength,
            self.long_term_role_prior_strength,
            self.recent_14_prior_strength,
            self.recent_42_prior_strength,
            self.rolling_365_prior_strength,
            self.rolling_730_prior_strength,
            self.decay_prior_strength,
            self.cluster_matchup_prior_strength,
            self.residual_14_prior_strength,
            self.residual_42_prior_strength,
        )
        if not all(math.isfinite(value) and value > 0.0 for value in strengths):
            raise ValueError(
                "walk-forward shrinkage strengths must be finite and positive"
            )
        if self.exact_bvp_prior_strength != 50.0:
            raise ValueError(
                "exact batter-versus-pitcher prior strength is fixed at 50 PA"
            )
        if self.batter_archetypes != 6 or self.pitcher_archetypes != 6:
            raise ValueError("walk-forward archetypes are fixed at six per role")
        if self.kmeans_n_init < 1:
            raise ValueError("kmeans_n_init must be positive")
        if isinstance(self.random_seed, bool) or not isinstance(self.random_seed, int):
            raise TypeError("random_seed must be an integer")
        return self


def _calendar_days(values: Sequence[Any], *, label: str) -> pd.DatetimeIndex:
    try:
        days = pd.DatetimeIndex(pd.to_datetime(list(values), errors="raise"))
    except Exception as exc:  # pragma: no cover - pandas supplies the detail
        raise WalkForwardStateError(f"{label} contains an invalid date") from exc
    if days.empty or days.hasnans:
        raise WalkForwardStateError(f"{label} must be non-empty and complete")
    if days.tz is not None:
        raise WalkForwardStateError(f"{label} must be timezone-naive calendar days")
    if not days.normalize().equals(days):
        raise WalkForwardStateError(f"{label} must contain normalized calendar days")
    if np.any(days.year >= 2025):
        raise WalkForwardStateError(f"{label} contains prohibited 2025-or-later data")
    return days


@dataclass(frozen=True)
class ChronologicalDirectLedger:
    """Direct probabilities plus the last training date used for every row.

    The ledger contains prediction provenance, not labels.  Alignment is by
    immutable row identity rather than by positional coincidence.
    """

    row_ids: tuple[str, ...]
    probabilities: np.ndarray
    training_end_days: tuple[str, ...]
    availability: np.ndarray | None = None

    def __post_init__(self) -> None:
        row_ids = tuple(str(value) for value in self.row_ids)
        if not row_ids or any(not value.strip() for value in row_ids):
            raise ValueError("Direct ledger row identities must be non-empty strings")
        if len(set(row_ids)) != len(row_ids):
            raise ValueError("Direct ledger row identities must be unique")
        probabilities = validate_probability_matrix(
            np.asarray(self.probabilities)
        ).copy()
        if probabilities.shape[0] != len(row_ids):
            raise ValueError("Direct ledger probabilities are not row-aligned")
        raw_cutoffs = tuple(self.training_end_days)
        if len(raw_cutoffs) != len(row_ids):
            raise ValueError("Direct ledger training cutoffs are not row-aligned")
        cutoffs = _calendar_days(raw_cutoffs, label="Direct ledger training cutoffs")
        if self.availability is None:
            availability = np.ones(len(row_ids), dtype=np.bool_)
        else:
            availability = np.asarray(self.availability)
            if (
                availability.dtype.kind != "b"
                or availability.ndim != 1
                or availability.shape[0] != len(row_ids)
            ):
                raise TypeError(
                    "Direct ledger availability must be a row-aligned boolean vector"
                )
            availability = availability.astype(np.bool_, copy=True)
        probabilities.setflags(write=False)
        availability.setflags(write=False)
        object.__setattr__(self, "row_ids", row_ids)
        object.__setattr__(self, "probabilities", probabilities)
        object.__setattr__(
            self,
            "training_end_days",
            tuple(day.strftime("%Y-%m-%d") for day in cutoffs),
        )
        object.__setattr__(self, "availability", availability)

    @classmethod
    def aligned(
        cls,
        frame: pd.DataFrame,
        probabilities: Any,
        training_end_days: Sequence[Any] | Any,
        *,
        row_id_column: str = "plate_appearance_id",
        availability: Any | None = None,
    ) -> "ChronologicalDirectLedger":
        """Construct a ledger from arrays already aligned to ``frame``."""

        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise TypeError("Direct ledger frame must be a non-empty pandas DataFrame")
        if row_id_column not in frame:
            raise WalkForwardStateError(
                f"Direct ledger frame is missing {row_id_column!r}"
            )
        rows = len(frame)
        if isinstance(training_end_days, (str, pd.Timestamp, np.datetime64)):
            cutoffs = (training_end_days,) * rows
        else:
            cutoffs = tuple(training_end_days)
        return cls(
            row_ids=tuple(frame[row_id_column].astype(str).tolist()),
            probabilities=np.asarray(probabilities),
            training_end_days=cutoffs,
            availability=availability,
        )

    def subset(self, row_ids: Sequence[Any]) -> "ChronologicalDirectLedger":
        """Return the requested identities in caller order, rejecting omissions."""

        requested = tuple(str(value) for value in row_ids)
        if not requested or len(set(requested)) != len(requested):
            raise WalkForwardStateError(
                "requested Direct ledger identities are empty or duplicate"
            )
        lookup = {row_id: index for index, row_id in enumerate(self.row_ids)}
        missing = [row_id for row_id in requested if row_id not in lookup]
        if missing:
            raise WalkForwardStateError(
                f"Direct ledger is missing {len(missing)} required row identities"
            )
        positions = np.asarray([lookup[row_id] for row_id in requested], dtype=np.int64)
        return ChronologicalDirectLedger(
            row_ids=requested,
            probabilities=self.probabilities[positions],
            training_end_days=tuple(
                self.training_end_days[index] for index in positions
            ),
            availability=np.asarray(self.availability)[positions],
        )


def _coerce_mask(mask: Any | None, rows: int) -> np.ndarray:
    if mask is None:
        return np.ones(rows, dtype=np.bool_)
    values = np.asarray(mask)
    if values.dtype.kind != "b" or values.ndim != 1 or values.shape[0] != rows:
        raise TypeError("training_mask must be a boolean vector aligned to the frame")
    if not values.any():
        raise ValueError("training_mask selects no rows")
    return values.astype(np.bool_, copy=True)


def _prepare_frame(
    frame: pd.DataFrame,
    config: WalkForwardStateConfig,
    *,
    label: str,
    require_outcome: bool,
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise TypeError(f"{label} must be a non-empty pandas DataFrame")
    columns = [
        config.date_column,
        config.batter_column,
        config.pitcher_column,
        config.row_id_column,
    ]
    if require_outcome:
        columns.append(config.outcome_column)
    missing = [name for name in columns if name not in frame]
    if missing:
        raise WalkForwardStateError(f"{label} columns missing: {sorted(missing)}")
    result = frame[columns].copy()
    row_ids = result[config.row_id_column]
    if row_ids.isna().any():
        raise WalkForwardStateError(f"{label} contains null row identities")
    row_ids = row_ids.astype(str).str.strip()
    if row_ids.eq("").any() or row_ids.duplicated().any():
        raise WalkForwardStateError(f"{label} row identities are blank or duplicated")
    result[config.row_id_column] = row_ids
    for column in (config.batter_column, config.pitcher_column):
        if result[column].isna().any():
            raise WalkForwardStateError(f"{label} {column} contains missing identity")
        entities = result[column].astype(str).str.strip()
        if entities.eq("").any():
            raise WalkForwardStateError(f"{label} {column} contains blank identity")
        result[column] = entities
    dates = _calendar_days(result[config.date_column].tolist(), label=f"{label} dates")
    result[config.date_column] = dates
    result["_day"] = (dates.astype("int64") // _DAY_NANOS).astype(np.int64)
    if require_outcome:
        result["_label"] = encode_labels(
            result[config.outcome_column].astype(str).to_numpy()
        )
    return result


def _aligned_ledger(
    ledger: ChronologicalDirectLedger,
    prepared: pd.DataFrame,
    config: WalkForwardStateConfig,
    *,
    exact: bool,
    require_available: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not isinstance(ledger, ChronologicalDirectLedger):
        raise TypeError("Direct expectations must be a ChronologicalDirectLedger")
    row_ids = tuple(prepared[config.row_id_column].astype(str).tolist())
    if exact and set(ledger.row_ids) != set(row_ids):
        missing = len(set(row_ids) - set(ledger.row_ids))
        extra = len(set(ledger.row_ids) - set(row_ids))
        raise WalkForwardStateError(
            f"Direct ledger identity inventory differs (missing={missing}, extra={extra})"
        )
    lookup = {row_id: index for index, row_id in enumerate(ledger.row_ids)}
    missing_ids = [row_id for row_id in row_ids if row_id not in lookup]
    if missing_ids:
        raise WalkForwardStateError(
            f"Direct ledger is missing {len(missing_ids)} required row identities"
        )
    if row_ids == ledger.row_ids:
        probabilities = ledger.probabilities
        raw_cutoffs = ledger.training_end_days
        availability = np.asarray(ledger.availability, dtype=np.bool_)
    else:
        positions = np.asarray([lookup[row_id] for row_id in row_ids], dtype=np.int64)
        probabilities = ledger.probabilities[positions]
        raw_cutoffs = tuple(ledger.training_end_days[index] for index in positions)
        availability = np.asarray(ledger.availability, dtype=np.bool_)[positions]
    cutoffs = _calendar_days(
        raw_cutoffs, label="aligned Direct ledger training cutoffs"
    )
    target_days = pd.DatetimeIndex(prepared[config.date_column])
    if np.any(cutoffs >= target_days):
        raise WalkForwardStateError(
            "Direct expectation training cutoff must be strictly earlier than its score row"
        )
    cutoff_ints = (cutoffs.astype("int64") // _DAY_NANOS).astype(np.int64)
    if require_available and not availability.all():
        raise WalkForwardStateError(
            "Direct probabilities are unavailable for one or more score rows"
        )
    return probabilities, cutoff_ints, availability


@dataclass
class _EntityHistory:
    days: np.ndarray
    labels: np.ndarray
    residuals: np.ndarray
    residual_available: np.ndarray


@dataclass
class _PairHistory:
    days: np.ndarray
    labels: np.ndarray


@dataclass(frozen=True)
class _RawState:
    weighted_class_count: np.ndarray
    observation_count: np.ndarray
    total_weight: np.ndarray
    effective_sample_size: np.ndarray
    missing_history: np.ndarray
    days_since_prior_appearance: np.ndarray


@dataclass(frozen=True)
class _RoleStateSet:
    all_history: _RawState
    windows: Mapping[int, _RawState]
    decays: Mapping[int, _RawState]
    residual_sums: Mapping[int, np.ndarray]
    residual_counts: Mapping[int, np.ndarray]


def _build_histories(
    prepared: pd.DataFrame,
    direct: np.ndarray,
    direct_available: np.ndarray,
    config: WalkForwardStateConfig,
) -> tuple[
    dict[str, _EntityHistory],
    dict[str, _EntityHistory],
    dict[tuple[str, str], _PairHistory],
]:
    labels = prepared["_label"].to_numpy(dtype=np.int64)
    one_hot = np.eye(_CLASS_COUNT, dtype=np.float64)[labels]
    residuals = one_hot - direct

    def entities(column: str) -> dict[str, _EntityHistory]:
        result: dict[str, _EntityHistory] = {}
        for raw_entity, raw_positions in prepared.groupby(
            column, sort=True
        ).indices.items():
            positions = np.asarray(raw_positions, dtype=np.int64)
            days = prepared.iloc[positions]["_day"].to_numpy(dtype=np.int64)
            order = np.argsort(days, kind="mergesort")
            selected = positions[order]
            result[str(raw_entity)] = _EntityHistory(
                days=days[order].copy(),
                labels=labels[selected].copy(),
                residuals=residuals[selected].copy(),
                residual_available=direct_available[selected].copy(),
            )
        return result

    pairs: dict[tuple[str, str], _PairHistory] = {}
    grouped = prepared.groupby(
        [config.batter_column, config.pitcher_column], sort=True
    ).indices
    for raw_pair, raw_positions in grouped.items():
        positions = np.asarray(raw_positions, dtype=np.int64)
        days = prepared.iloc[positions]["_day"].to_numpy(dtype=np.int64)
        order = np.argsort(days, kind="mergesort")
        pairs[(str(raw_pair[0]), str(raw_pair[1]))] = _PairHistory(
            days=days[order].copy(), labels=labels[positions[order]].copy()
        )
    return entities(config.batter_column), entities(config.pitcher_column), pairs


def _empty_raw(rows: int) -> _RawState:
    return _RawState(
        weighted_class_count=np.zeros((rows, _CLASS_COUNT), dtype=np.float64),
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
) -> _RawState:
    return _RawState(
        weighted_class_count=class_count,
        observation_count=observation_count,
        total_weight=total_weight,
        effective_sample_size=np.minimum(effective, observation_count),
        missing_history=observation_count <= 0.0,
        days_since_prior_appearance=days_since,
    )


def _score_role(
    history: Mapping[str, _EntityHistory],
    target_entities: np.ndarray,
    target_day: int,
) -> _RoleStateSet:
    rows = len(target_entities)
    long_count = np.zeros((rows, _CLASS_COUNT), dtype=np.float64)
    long_n = np.zeros(rows, dtype=np.float64)
    days_since = np.full(rows, np.nan, dtype=np.float64)
    window_count = {
        window: np.zeros((rows, _CLASS_COUNT), dtype=np.float64)
        for window in (14, 42, 365, 730)
    }
    window_n = {window: np.zeros(rows, dtype=np.float64) for window in window_count}
    residual_sum = {
        window: np.zeros((rows, _CLASS_COUNT), dtype=np.float64) for window in (14, 42)
    }
    residual_count = {window: np.zeros(rows, dtype=np.float64) for window in (14, 42)}
    decay_count = {
        half_life: np.zeros((rows, _CLASS_COUNT), dtype=np.float64)
        for half_life in (180, 365)
    }
    decay_weight = {
        half_life: np.zeros(rows, dtype=np.float64) for half_life in decay_count
    }
    decay_ess = {
        half_life: np.zeros(rows, dtype=np.float64) for half_life in decay_count
    }

    positions_by_entity: dict[str, list[int]] = {}
    for position, entity in enumerate(target_entities):
        positions_by_entity.setdefault(str(entity), []).append(position)
    for entity, raw_positions in positions_by_entity.items():
        series = history.get(entity)
        if series is None:
            continue
        end = int(np.searchsorted(series.days, target_day, side="left"))
        if end != len(series.days):
            raise WalkForwardStateError(
                "same-day or future entity history reached scoring"
            )
        if end == 0:
            continue
        positions = np.asarray(raw_positions, dtype=np.int64)
        labels = series.labels[:end]
        prior_days = series.days[:end]
        long_count[positions] = np.bincount(labels, minlength=_CLASS_COUNT)
        long_n[positions] = float(end)
        elapsed = float(target_day - prior_days[-1])
        if elapsed < 1.0:
            raise WalkForwardStateError(
                "state history is not strictly prior to score date"
            )
        days_since[positions] = elapsed

        for window in (14, 42, 365, 730):
            start = int(np.searchsorted(prior_days, target_day - window, side="left"))
            sample_labels = labels[start:]
            count = float(sample_labels.size)
            window_count[window][positions] = np.bincount(
                sample_labels, minlength=_CLASS_COUNT
            )
            window_n[window][positions] = count
            if window in residual_sum:
                available = series.residual_available[start:end]
                residual_sum[window][positions] = series.residuals[start:end][
                    available
                ].sum(axis=0)
                residual_count[window][positions] = float(available.sum())

        ages = target_day - prior_days
        for half_life in (180, 365):
            weights = np.power(0.5, ages / float(half_life))
            total = float(weights.sum())
            square = float(np.dot(weights, weights))
            decay_count[half_life][positions] = np.bincount(
                labels, weights=weights, minlength=_CLASS_COUNT
            )
            decay_weight[half_life][positions] = total
            decay_ess[half_life][positions] = (
                total * total / square if square > 0.0 else 0.0
            )

    long_raw = _raw_state(long_count, long_n, long_n, long_n, days_since)
    windows = {
        window: _raw_state(
            window_count[window],
            window_n[window],
            window_n[window],
            window_n[window],
            days_since,
        )
        for window in (14, 42, 365, 730)
    }
    decays = {
        half_life: _raw_state(
            decay_count[half_life],
            long_n,
            decay_weight[half_life],
            decay_ess[half_life],
            days_since,
        )
        for half_life in (180, 365)
    }
    return _RoleStateSet(
        all_history=long_raw,
        windows=windows,
        decays=decays,
        residual_sums=residual_sum,
        residual_counts=residual_count,
    )


def _normalize_rows(values: Any) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float64)
    if matrix.ndim != 2 or matrix.shape[1] != _CLASS_COUNT or matrix.shape[0] == 0:
        raise ValueError("probability values must be a non-empty governed-order matrix")
    if not np.isfinite(matrix).all() or np.any(matrix < 0.0):
        raise ValueError("probability values must be finite and nonnegative")
    totals = matrix.sum(axis=1)
    if np.any(totals <= 0.0):
        raise ValueError("probability rows must carry positive mass")
    return validate_probability_matrix(matrix / totals[:, None])


def _shrink(raw: _RawState, prior: np.ndarray, strength: float) -> np.ndarray:
    if prior.ndim == 1:
        prior = np.broadcast_to(prior, raw.weighted_class_count.shape)
    return _normalize_rows(
        (raw.weighted_class_count + strength * prior)
        / (raw.total_weight[:, None] + strength)
    )


def _entropy(probabilities: np.ndarray) -> np.ndarray:
    return -np.sum(
        probabilities * np.log(np.clip(probabilities, _EPSILON, 1.0)), axis=1
    )


def _total_variation(probabilities: np.ndarray, reference: np.ndarray) -> np.ndarray:
    return 0.5 * np.sum(np.abs(probabilities - reference), axis=1)


def _role_diagnostics(
    batter_probability: np.ndarray,
    pitcher_probability: np.ndarray,
    batter: _RawState,
    pitcher: _RawState,
) -> dict[str, np.ndarray]:
    return {
        "batter_probabilities": batter_probability,
        "pitcher_probabilities": pitcher_probability,
        "batter_observation_count": batter.observation_count,
        "pitcher_observation_count": pitcher.observation_count,
        "batter_effective_sample_size": batter.effective_sample_size,
        "pitcher_effective_sample_size": pitcher.effective_sample_size,
        "batter_missing_history": batter.missing_history,
        "pitcher_missing_history": pitcher.missing_history,
        "batter_days_since_prior_appearance": batter.days_since_prior_appearance,
        "pitcher_days_since_prior_appearance": pitcher.days_since_prior_appearance,
    }


def _component(
    name: str,
    probabilities: np.ndarray,
    batter_probability: np.ndarray,
    pitcher_probability: np.ndarray,
    batter: _RawState,
    pitcher: _RawState,
    reference: np.ndarray,
) -> ComponentEstimate:
    count = batter.observation_count + pitcher.observation_count
    effective = batter.effective_sample_size + pitcher.effective_sample_size
    return ComponentEstimate(
        name=name,
        probabilities=probabilities,
        observation_count=count,
        effective_sample_size=np.minimum(effective, count),
        missing_history=batter.missing_history | pitcher.missing_history,
        days_since_prior_appearance=np.maximum(
            batter.days_since_prior_appearance,
            pitcher.days_since_prior_appearance,
        ),
        entropy=_entropy(probabilities),
        deviation_from_long_term=_total_variation(probabilities, reference),
        role_diagnostics=_role_diagnostics(
            batter_probability, pitcher_probability, batter, pitcher
        ),
    )


@dataclass(frozen=True)
class WalkForwardDayBundle:
    row_ids: tuple[str, ...]
    class_order: tuple[str, ...]
    components: Mapping[str, ComponentEstimate]
    score_day: str
    history_end_day_before_score: str
    residual_expectation_source: str = RESIDUAL_EXPECTATION_SOURCE

    def __post_init__(self) -> None:
        require_frozen_class_order(self.class_order)
        if tuple(self.components) != WALK_FORWARD_COMPONENT_ORDER:
            raise ValueError(
                "day component mapping differs from the fixed ten-component order"
            )
        if not self.row_ids or len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("day bundle row identities must be non-empty and unique")
        if any(component.name != name for name, component in self.components.items()):
            raise ValueError("day component names and mapping keys differ")
        if any(
            component.probabilities.shape[0] != len(self.row_ids)
            for component in self.components.values()
        ):
            raise ValueError("day components are not row-aligned")
        if pd.Timestamp(self.history_end_day_before_score) >= pd.Timestamp(
            self.score_day
        ):
            raise ValueError("day bundle history is not strictly prior")
        if self.residual_expectation_source != RESIDUAL_EXPECTATION_SOURCE:
            raise ValueError("day residual expectation source differs")

    @property
    def probability_matrices(self) -> dict[str, np.ndarray]:
        return {
            name: component.probabilities for name, component in self.components.items()
        }

    @property
    def reliability(self) -> dict[str, dict[str, np.ndarray]]:
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
            if name != DIRECT_GOLD
        }


@dataclass(frozen=True)
class WalkForwardBlockBundle:
    row_ids: tuple[str, ...]
    class_order: tuple[str, ...]
    components: Mapping[str, ComponentEstimate]
    daily_bundles: tuple[WalkForwardDayBundle, ...]
    score_start_day: str
    score_end_day: str
    initial_history_end_day: str
    final_history_end_day: str
    input_rows: int
    scored_rows: int
    advanced_rows: int
    residual_expectation_source: str = RESIDUAL_EXPECTATION_SOURCE

    def __post_init__(self) -> None:
        require_frozen_class_order(self.class_order)
        if tuple(self.components) != WALK_FORWARD_COMPONENT_ORDER:
            raise ValueError(
                "block component mapping differs from the fixed ten-component order"
            )
        if self.input_rows <= 0 or not (
            self.input_rows
            == self.scored_rows
            == self.advanced_rows
            == len(self.row_ids)
        ):
            raise ValueError("walk-forward block did not reconcile every input row")
        if len(set(self.row_ids)) != len(self.row_ids):
            raise ValueError("walk-forward block row identities are duplicated")
        if sum(len(bundle.row_ids) for bundle in self.daily_bundles) != self.input_rows:
            raise ValueError("daily walk-forward rows do not reconcile to the block")
        if pd.Timestamp(self.initial_history_end_day) >= pd.Timestamp(
            self.score_start_day
        ):
            raise ValueError(
                "block history is not strictly prior to its first score date"
            )
        if self.score_end_day != self.final_history_end_day:
            raise ValueError("block final score date was not advanced into history")

    @property
    def probability_matrices(self) -> dict[str, np.ndarray]:
        return {
            name: component.probabilities for name, component in self.components.items()
        }

    @property
    def reliability(self) -> dict[str, dict[str, np.ndarray]]:
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
            if name != DIRECT_GOLD
        }

    @property
    def reconciliation(self) -> dict[str, Any]:
        return {
            "inputRows": self.input_rows,
            "scoredRows": self.scored_rows,
            "advancedRows": self.advanced_rows,
            "scoreDates": len(self.daily_bundles),
            "rowIdsUnique": len(set(self.row_ids)) == len(self.row_ids),
            "noRowsDropped": self.input_rows == self.scored_rows == self.advanced_rows,
        }


@dataclass(frozen=True)
class _PendingDay:
    day: int
    row_ids: tuple[str, ...]
    direct_probabilities: np.ndarray
    bundle: WalkForwardDayBundle


class WalkForwardStateEngine:
    """Mutable daily history with immutable training-only archetypes."""

    def __init__(
        self,
        *,
        config: WalkForwardStateConfig,
        training_rows: int,
        training_start_day: int,
        training_end_day: int,
        league_probabilities: np.ndarray,
        batter_archetypes: SoftArchetypeModel,
        pitcher_archetypes: SoftArchetypeModel,
        batter_history: dict[str, _EntityHistory],
        pitcher_history: dict[str, _EntityHistory],
        pair_history: dict[tuple[str, str], _PairHistory],
        cluster_class_count: np.ndarray,
        cluster_count: np.ndarray,
        cluster_weight_square: np.ndarray,
        known_row_ids: set[str],
    ) -> None:
        self.config = config.validate()
        self.class_order = PA_CLASS_ORDER
        self.training_rows = int(training_rows)
        self.training_start_day = _day_string(training_start_day)
        self.archetype_fit_end_day = _day_string(training_end_day)
        self.league_probabilities = validate_probability_matrix(
            np.asarray(league_probabilities)[None, :]
        )[0]
        self.batter_archetypes = batter_archetypes
        self.pitcher_archetypes = pitcher_archetypes
        self._batter_history = batter_history
        self._pitcher_history = pitcher_history
        self._pair_history = pair_history
        self._cluster_class_count = np.asarray(cluster_class_count, dtype=np.float64)
        self._cluster_count = np.asarray(cluster_count, dtype=np.float64)
        self._cluster_weight_square = np.asarray(
            cluster_weight_square, dtype=np.float64
        )
        self._known_row_ids = set(known_row_ids)
        self._history_end_day = int(training_end_day)
        self._history_rows = int(training_rows)
        self._pending: _PendingDay | None = None

    @property
    def history_end_day(self) -> str:
        return _day_string(self._history_end_day)

    @property
    def history_rows(self) -> int:
        return self._history_rows

    @property
    def has_pending_day(self) -> bool:
        return self._pending is not None

    def _cluster_component(
        self,
        batter_ids: np.ndarray,
        pitcher_ids: np.ndarray,
        batter_long: _RawState,
        pitcher_long: _RawState,
        reference: np.ndarray,
    ) -> ComponentEstimate:
        batter_membership = self.batter_archetypes.memberships_for(batter_ids)
        pitcher_membership = self.pitcher_archetypes.memberships_for(pitcher_ids)
        strength = self.config.cluster_matchup_prior_strength
        cell_probabilities = _normalize_rows(
            (
                self._cluster_class_count
                + strength * self.league_probabilities[None, None, :]
            ).reshape(-1, _CLASS_COUNT)
            / (self._cluster_count.reshape(-1, 1) + strength)
        ).reshape(6, 6, _CLASS_COUNT)
        probabilities = _normalize_rows(
            np.einsum(
                "ni,nj,ijk->nk",
                batter_membership,
                pitcher_membership,
                cell_probabilities,
                optimize=True,
            )
        )
        pair_weight = batter_membership[:, :, None] * pitcher_membership[:, None, :]
        count = np.sum(pair_weight * self._cluster_count[None, :, :], axis=(1, 2))
        cell_effective = np.divide(
            self._cluster_count * self._cluster_count,
            self._cluster_weight_square,
            out=np.zeros_like(self._cluster_count),
            where=self._cluster_weight_square > 0.0,
        )
        cell_effective = np.minimum(cell_effective, self._cluster_count)
        effective = np.minimum(
            np.sum(pair_weight * cell_effective[None, :, :], axis=(1, 2)), count
        )
        batter_known = np.isin(
            batter_ids, np.asarray(self.batter_archetypes.player_ids, dtype=object)
        )
        pitcher_known = np.isin(
            pitcher_ids, np.asarray(self.pitcher_archetypes.player_ids, dtype=object)
        )
        missing = ~(batter_known & pitcher_known)
        days = np.where(
            missing,
            np.nan,
            np.maximum(
                batter_long.days_since_prior_appearance,
                pitcher_long.days_since_prior_appearance,
            ),
        )
        return ComponentEstimate(
            name=CLUSTER_MATCHUP,
            probabilities=probabilities,
            observation_count=count,
            effective_sample_size=effective,
            missing_history=missing,
            days_since_prior_appearance=days,
            entropy=_entropy(probabilities),
            deviation_from_long_term=_total_variation(probabilities, reference),
            role_diagnostics={
                "batter_memberships": batter_membership,
                "pitcher_memberships": pitcher_membership,
                "batter_missing_history": ~batter_known,
                "pitcher_missing_history": ~pitcher_known,
            },
        )

    def _bvp_component(
        self,
        batter_ids: np.ndarray,
        pitcher_ids: np.ndarray,
        target_day: int,
        cluster: ComponentEstimate,
        reference: np.ndarray,
    ) -> ComponentEstimate:
        rows = len(batter_ids)
        class_count = np.zeros((rows, _CLASS_COUNT), dtype=np.float64)
        count = np.zeros(rows, dtype=np.float64)
        days_since = np.full(rows, np.nan, dtype=np.float64)
        positions_by_pair: dict[tuple[str, str], list[int]] = {}
        for position, pair in enumerate(zip(batter_ids, pitcher_ids)):
            positions_by_pair.setdefault((str(pair[0]), str(pair[1])), []).append(
                position
            )
        for pair, raw_positions in positions_by_pair.items():
            history = self._pair_history.get(pair)
            if history is None:
                continue
            end = int(np.searchsorted(history.days, target_day, side="left"))
            if end != len(history.days):
                raise WalkForwardStateError(
                    "same-day or future BvP history reached scoring"
                )
            positions = np.asarray(raw_positions, dtype=np.int64)
            class_count[positions] = np.bincount(
                history.labels[:end], minlength=_CLASS_COUNT
            )
            count[positions] = float(end)
            days_since[positions] = target_day - history.days[end - 1]
        strength = self.config.exact_bvp_prior_strength
        probabilities = _normalize_rows(
            (class_count + strength * cluster.probabilities)
            / (count[:, None] + strength)
        )
        return ComponentEstimate(
            name=SHRUNK_EXACT_BVP,
            probabilities=probabilities,
            observation_count=count,
            effective_sample_size=count.copy(),
            missing_history=count <= 0.0,
            days_since_prior_appearance=days_since,
            entropy=_entropy(probabilities),
            deviation_from_long_term=_total_variation(probabilities, reference),
            role_diagnostics={
                "cluster_prior_probabilities": cluster.probabilities,
                "exact_pair_weight": count / (count + strength),
            },
        )

    def _residual_component(
        self,
        direct: np.ndarray,
        batter: _RoleStateSet,
        pitcher: _RoleStateSet,
        reference: np.ndarray,
    ) -> ComponentEstimate:
        config = self.config

        def correction(role: _RoleStateSet, window: int, strength: float) -> np.ndarray:
            return role.residual_sums[window] / (
                role.residual_counts[window][:, None] + strength
            )

        batter14 = correction(batter, 14, config.residual_14_prior_strength)
        pitcher14 = correction(pitcher, 14, config.residual_14_prior_strength)
        batter42 = correction(batter, 42, config.residual_42_prior_strength)
        pitcher42 = correction(pitcher, 42, config.residual_42_prior_strength)
        batter_correction = (batter14 + batter42) / 2.0
        pitcher_correction = (pitcher14 + pitcher42) / 2.0
        total_correction = (batter_correction + pitcher_correction) / 2.0
        log_mass = np.log(np.clip(direct, _EPSILON, 1.0)) + total_correction
        log_mass -= np.max(log_mass, axis=1, keepdims=True)
        probabilities = _normalize_rows(np.exp(log_mass))
        count = batter.residual_counts[42] + pitcher.residual_counts[42]
        missing = (batter.residual_counts[42] <= 0.0) | (
            pitcher.residual_counts[42] <= 0.0
        )
        rows = len(direct)
        return ComponentEstimate(
            name=RECENT_RESIDUAL_FORM,
            probabilities=probabilities,
            observation_count=count,
            effective_sample_size=count.copy(),
            missing_history=missing,
            days_since_prior_appearance=np.maximum(
                batter.all_history.days_since_prior_appearance,
                pitcher.all_history.days_since_prior_appearance,
            ),
            entropy=_entropy(probabilities),
            deviation_from_long_term=_total_variation(probabilities, reference),
            role_diagnostics={
                "batter_14_residual": batter14,
                "pitcher_14_residual": pitcher14,
                "batter_42_residual": batter42,
                "pitcher_42_residual": pitcher42,
                "batter_residual_observation_count": batter.residual_counts[42],
                "pitcher_residual_observation_count": pitcher.residual_counts[42],
                "chronological_oof_expectation_verified": np.ones(rows, dtype=np.bool_),
            },
        )

    def score_day(
        self,
        day_frame: pd.DataFrame,
        direct_ledger: ChronologicalDirectLedger,
    ) -> WalkForwardDayBundle:
        """Score one complete date without mutating history."""

        prepared = _prepare_frame(
            day_frame,
            self.config,
            label="walk-forward score day",
            require_outcome=False,
        )
        unique_days = np.unique(prepared["_day"].to_numpy(dtype=np.int64))
        if unique_days.size != 1:
            raise WalkForwardStateError(
                "score_day requires exactly one complete calendar date"
            )
        target_day = int(unique_days[0])
        if target_day <= self._history_end_day:
            raise WalkForwardStateError(
                "score date is not strictly later than current history"
            )
        row_ids = tuple(prepared[self.config.row_id_column].astype(str).tolist())
        if set(row_ids) & self._known_row_ids:
            raise WalkForwardStateError(
                "score rows already exist in walk-forward history"
            )
        direct, _, direct_available = _aligned_ledger(
            direct_ledger,
            prepared,
            self.config,
            exact=True,
            require_available=True,
        )

        if self._pending is not None:
            if (
                self._pending.day == target_day
                and self._pending.row_ids == row_ids
                and np.array_equal(self._pending.direct_probabilities, direct)
            ):
                return self._pending.bundle
            raise WalkForwardStateError(
                "a different score day is pending atomic advancement"
            )

        batter_ids = prepared[self.config.batter_column].to_numpy(dtype=object)
        pitcher_ids = prepared[self.config.pitcher_column].to_numpy(dtype=object)
        batter = _score_role(self._batter_history, batter_ids, target_day)
        pitcher = _score_role(self._pitcher_history, pitcher_ids, target_day)

        batter_long = _shrink(
            batter.all_history,
            self.league_probabilities,
            self.config.long_term_role_prior_strength,
        )
        pitcher_long = _shrink(
            pitcher.all_history,
            self.league_probabilities,
            self.config.long_term_role_prior_strength,
        )
        batter365 = _shrink(
            batter.windows[365],
            self.league_probabilities,
            self.config.rolling_365_prior_strength,
        )
        pitcher365 = _shrink(
            pitcher.windows[365],
            self.league_probabilities,
            self.config.rolling_365_prior_strength,
        )
        rolling365 = fixed_log_opinion_pool(
            batter365, pitcher365, self.league_probabilities
        )

        components: dict[str, ComponentEstimate] = {}
        rows = len(prepared)
        components[DIRECT_GOLD] = ComponentEstimate(
            name=DIRECT_GOLD,
            probabilities=direct,
            observation_count=np.zeros(rows, dtype=np.float64),
            effective_sample_size=np.zeros(rows, dtype=np.float64),
            missing_history=np.zeros(rows, dtype=np.bool_),
            days_since_prior_appearance=np.full(rows, np.nan, dtype=np.float64),
            entropy=_entropy(direct),
            deviation_from_long_term=_total_variation(direct, rolling365),
        )

        for name, batter_raw, pitcher_raw, prior_batter, prior_pitcher, strength in (
            (
                RECENT_14_DAY_STATE,
                batter.windows[14],
                pitcher.windows[14],
                batter365,
                pitcher365,
                self.config.recent_14_prior_strength,
            ),
            (
                RECENT_42_DAY_STATE,
                batter.windows[42],
                pitcher.windows[42],
                batter365,
                pitcher365,
                self.config.recent_42_prior_strength,
            ),
            (
                ROLLING_365_DAY_STATE,
                batter.windows[365],
                pitcher.windows[365],
                self.league_probabilities,
                self.league_probabilities,
                self.config.rolling_365_prior_strength,
            ),
            (
                ROLLING_730_DAY_STATE,
                batter.windows[730],
                pitcher.windows[730],
                self.league_probabilities,
                self.league_probabilities,
                self.config.rolling_730_prior_strength,
            ),
            (
                DECAY_180_DAY_STATE,
                batter.decays[180],
                pitcher.decays[180],
                batter_long,
                pitcher_long,
                self.config.decay_prior_strength,
            ),
            (
                DECAY_365_DAY_STATE,
                batter.decays[365],
                pitcher.decays[365],
                batter_long,
                pitcher_long,
                self.config.decay_prior_strength,
            ),
        ):
            batter_probability = _shrink(batter_raw, prior_batter, strength)
            pitcher_probability = _shrink(pitcher_raw, prior_pitcher, strength)
            combined = fixed_log_opinion_pool(
                batter_probability, pitcher_probability, self.league_probabilities
            )
            components[name] = _component(
                name,
                combined,
                batter_probability,
                pitcher_probability,
                batter_raw,
                pitcher_raw,
                rolling365,
            )

        cluster = self._cluster_component(
            batter_ids,
            pitcher_ids,
            batter.all_history,
            pitcher.all_history,
            rolling365,
        )
        components[CLUSTER_MATCHUP] = cluster
        components[SHRUNK_EXACT_BVP] = self._bvp_component(
            batter_ids, pitcher_ids, target_day, cluster, rolling365
        )
        components[RECENT_RESIDUAL_FORM] = self._residual_component(
            direct, batter, pitcher, rolling365
        )
        if tuple(components) != WALK_FORWARD_COMPONENT_ORDER:
            raise WalkForwardStateError(
                "walk-forward component construction order drifted"
            )
        bundle = WalkForwardDayBundle(
            row_ids=row_ids,
            class_order=PA_CLASS_ORDER,
            components=components,
            score_day=_day_string(target_day),
            history_end_day_before_score=self.history_end_day,
        )
        self._pending = _PendingDay(
            day=target_day,
            row_ids=row_ids,
            direct_probabilities=direct.copy(),
            bundle=bundle,
        )
        return bundle

    def advance_day(self, day_frame: pd.DataFrame) -> None:
        """Atomically append the complete previously scored date."""

        if self._pending is None:
            raise WalkForwardStateError(
                "advance_day requires a previously scored pending date"
            )
        prepared = _prepare_frame(
            day_frame,
            self.config,
            label="walk-forward advance day",
            require_outcome=True,
        )
        days = np.unique(prepared["_day"].to_numpy(dtype=np.int64))
        row_ids = tuple(prepared[self.config.row_id_column].astype(str).tolist())
        if days.size != 1 or int(days[0]) != self._pending.day:
            raise WalkForwardStateError(
                "advanced date differs from the pending score date"
            )
        if row_ids != self._pending.row_ids:
            raise WalkForwardStateError(
                "advanced row identities/order differ from pending score rows"
            )
        labels = prepared["_label"].to_numpy(dtype=np.int64)
        one_hot = np.eye(_CLASS_COUNT, dtype=np.float64)[labels]
        residuals = one_hot - self._pending.direct_probabilities
        target_day = self._pending.day

        _append_entity_histories(
            self._batter_history,
            prepared[self.config.batter_column].to_numpy(dtype=object),
            target_day,
            labels,
            residuals,
            np.ones(len(prepared), dtype=np.bool_),
        )
        _append_entity_histories(
            self._pitcher_history,
            prepared[self.config.pitcher_column].to_numpy(dtype=object),
            target_day,
            labels,
            residuals,
            np.ones(len(prepared), dtype=np.bool_),
        )
        _append_pair_histories(
            self._pair_history,
            prepared[self.config.batter_column].to_numpy(dtype=object),
            prepared[self.config.pitcher_column].to_numpy(dtype=object),
            target_day,
            labels,
        )
        batter_membership = self.batter_archetypes.memberships_for(
            prepared[self.config.batter_column].to_numpy(dtype=object)
        )
        pitcher_membership = self.pitcher_archetypes.memberships_for(
            prepared[self.config.pitcher_column].to_numpy(dtype=object)
        )
        _accumulate_clusters(
            self._cluster_class_count,
            self._cluster_count,
            self._cluster_weight_square,
            batter_membership,
            pitcher_membership,
            labels,
        )
        self._known_row_ids.update(row_ids)
        self._history_rows += len(prepared)
        self._history_end_day = target_day
        self._pending = None


def _day_string(day: int) -> str:
    return pd.Timestamp(int(day) * _DAY_NANOS).strftime("%Y-%m-%d")


def _append_entity_histories(
    history: dict[str, _EntityHistory],
    entities: np.ndarray,
    day: int,
    labels: np.ndarray,
    residuals: np.ndarray,
    residual_available: np.ndarray,
) -> None:
    positions_by_entity: dict[str, list[int]] = {}
    for position, entity in enumerate(entities):
        positions_by_entity.setdefault(str(entity), []).append(position)
    for entity, raw_positions in positions_by_entity.items():
        positions = np.asarray(raw_positions, dtype=np.int64)
        new_days = np.full(len(positions), day, dtype=np.int64)
        existing = history.get(entity)
        if existing is None:
            history[entity] = _EntityHistory(
                days=new_days,
                labels=labels[positions].copy(),
                residuals=residuals[positions].copy(),
                residual_available=residual_available[positions].copy(),
            )
            continue
        if int(existing.days[-1]) >= day:
            raise WalkForwardStateError(
                "entity history append is not strictly chronological"
            )
        existing.days = np.concatenate([existing.days, new_days])
        existing.labels = np.concatenate([existing.labels, labels[positions]])
        existing.residuals = np.concatenate(
            [existing.residuals, residuals[positions]], axis=0
        )
        existing.residual_available = np.concatenate(
            [existing.residual_available, residual_available[positions]]
        )


def _append_pair_histories(
    history: dict[tuple[str, str], _PairHistory],
    batters: np.ndarray,
    pitchers: np.ndarray,
    day: int,
    labels: np.ndarray,
) -> None:
    positions_by_pair: dict[tuple[str, str], list[int]] = {}
    for position, pair in enumerate(zip(batters, pitchers)):
        positions_by_pair.setdefault((str(pair[0]), str(pair[1])), []).append(position)
    for pair, raw_positions in positions_by_pair.items():
        positions = np.asarray(raw_positions, dtype=np.int64)
        new_days = np.full(len(positions), day, dtype=np.int64)
        existing = history.get(pair)
        if existing is None:
            history[pair] = _PairHistory(new_days, labels[positions].copy())
            continue
        if int(existing.days[-1]) >= day:
            raise WalkForwardStateError(
                "BvP history append is not strictly chronological"
            )
        existing.days = np.concatenate([existing.days, new_days])
        existing.labels = np.concatenate([existing.labels, labels[positions]])


def _accumulate_clusters(
    class_count: np.ndarray,
    total_count: np.ndarray,
    weight_square: np.ndarray,
    batter_membership: np.ndarray,
    pitcher_membership: np.ndarray,
    labels: np.ndarray,
) -> None:
    total_count += batter_membership.T @ pitcher_membership
    weight_square += (batter_membership * batter_membership).T @ (
        pitcher_membership * pitcher_membership
    )
    for class_index in range(_CLASS_COUNT):
        selected = labels == class_index
        if selected.any():
            class_count[:, :, class_index] += (
                batter_membership[selected].T @ pitcher_membership[selected]
            )


def _initial_cluster_counts(
    prepared: pd.DataFrame,
    batter_archetypes: SoftArchetypeModel,
    pitcher_archetypes: SoftArchetypeModel,
    config: WalkForwardStateConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    class_count = np.zeros((6, 6, _CLASS_COUNT), dtype=np.float64)
    count = np.zeros((6, 6), dtype=np.float64)
    square = np.zeros((6, 6), dtype=np.float64)
    labels = prepared["_label"].to_numpy(dtype=np.int64)
    chunk_size = 50_000
    for start in range(0, len(prepared), chunk_size):
        stop = min(start + chunk_size, len(prepared))
        batter = batter_archetypes.memberships_for(
            prepared.iloc[start:stop][config.batter_column].to_numpy(dtype=object)
        )
        pitcher = pitcher_archetypes.memberships_for(
            prepared.iloc[start:stop][config.pitcher_column].to_numpy(dtype=object)
        )
        _accumulate_clusters(
            class_count, count, square, batter, pitcher, labels[start:stop]
        )
    return class_count, count, square


def fit_walk_forward_state(
    frame: pd.DataFrame,
    direct_ledger: ChronologicalDirectLedger,
    *,
    training_mask: Any | None = None,
    config: WalkForwardStateConfig | None = None,
) -> WalkForwardStateEngine:
    """Fit fixed priors/archetypes and initialize strictly chronological state."""

    active = (config or WalkForwardStateConfig()).validate()
    if not isinstance(direct_ledger, ChronologicalDirectLedger):
        raise TypeError("direct_ledger must be a ChronologicalDirectLedger")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise TypeError(
            "walk-forward training frame must be a non-empty pandas DataFrame"
        )
    if active.date_column not in frame:
        raise WalkForwardStateError(
            f"walk-forward training frame columns missing: {[active.date_column]}"
        )
    # Reject a prohibited year anywhere in the supplied population, including
    # rows outside a caller mask.  A mask is selection authority, not license
    # to carry future data through this module.
    _calendar_days(
        frame[active.date_column].tolist(),
        label="walk-forward supplied population dates",
    )
    selected = _coerce_mask(training_mask, len(frame))
    selected_frame = frame.loc[selected].reset_index(drop=True)
    prepared = _prepare_frame(
        selected_frame,
        active,
        label="walk-forward training frame",
        require_outcome=True,
    )
    selected_ids = tuple(prepared[active.row_id_column].astype(str).tolist())
    direct, _, direct_available = _aligned_ledger(
        direct_ledger,
        prepared,
        active,
        exact=training_mask is None,
    )
    labels = prepared["_label"].to_numpy(dtype=np.int64)
    class_counts = np.bincount(labels, minlength=_CLASS_COUNT).astype(np.float64)
    uniform = np.full(_CLASS_COUNT, 1.0 / _CLASS_COUNT, dtype=np.float64)
    league = (class_counts + active.league_uniform_prior_strength * uniform) / (
        class_counts.sum() + active.league_uniform_prior_strength
    )
    league = validate_probability_matrix(league[None, :])[0]
    batter_history, pitcher_history, pair_history = _build_histories(
        prepared, direct, direct_available, active
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
    cluster_class, cluster_count, cluster_square = _initial_cluster_counts(
        prepared, batter_archetypes, pitcher_archetypes, active
    )
    days = prepared["_day"].to_numpy(dtype=np.int64)
    return WalkForwardStateEngine(
        config=active,
        training_rows=len(prepared),
        training_start_day=int(days.min()),
        training_end_day=int(days.max()),
        league_probabilities=league,
        batter_archetypes=batter_archetypes,
        pitcher_archetypes=pitcher_archetypes,
        batter_history=batter_history,
        pitcher_history=pitcher_history,
        pair_history=pair_history,
        cluster_class_count=cluster_class,
        cluster_count=cluster_count,
        cluster_weight_square=cluster_square,
        known_row_ids=set(selected_ids),
    )


def _concatenate_components(
    daily: Sequence[WalkForwardDayBundle],
    output_row_ids: tuple[str, ...],
) -> dict[str, ComponentEstimate]:
    chronological_ids = tuple(row_id for bundle in daily for row_id in bundle.row_ids)
    lookup = {row_id: position for position, row_id in enumerate(chronological_ids)}
    if len(lookup) != len(chronological_ids) or set(lookup) != set(output_row_ids):
        raise WalkForwardStateError(
            "daily component identities do not reconcile to output rows"
        )
    order = np.asarray([lookup[row_id] for row_id in output_row_ids], dtype=np.int64)
    result: dict[str, ComponentEstimate] = {}
    for name in WALK_FORWARD_COMPONENT_ORDER:
        components = [bundle.components[name] for bundle in daily]

        def joined(attribute: str) -> np.ndarray:
            return np.concatenate(
                [np.asarray(getattr(component, attribute)) for component in components],
                axis=0,
            )[order]

        diagnostic_keys = tuple(components[0].role_diagnostics)
        if any(
            tuple(component.role_diagnostics) != diagnostic_keys
            for component in components
        ):
            raise WalkForwardStateError(
                f"{name} role diagnostics drifted across score dates"
            )
        diagnostics = {
            key: np.concatenate(
                [
                    np.asarray(component.role_diagnostics[key])
                    for component in components
                ],
                axis=0,
            )[order]
            for key in diagnostic_keys
        }
        result[name] = ComponentEstimate(
            name=name,
            probabilities=joined("probabilities"),
            observation_count=joined("observation_count"),
            effective_sample_size=joined("effective_sample_size"),
            missing_history=joined("missing_history"),
            days_since_prior_appearance=joined("days_since_prior_appearance"),
            entropy=joined("entropy"),
            deviation_from_long_term=joined("deviation_from_long_term"),
            role_diagnostics=diagnostics,
        )
    return result


def score_walk_forward_block(
    engine: WalkForwardStateEngine,
    target_frame: pd.DataFrame,
    direct_ledger: ChronologicalDirectLedger,
) -> WalkForwardBlockBundle:
    """Score and date-atomically advance every row in a target block."""

    if not isinstance(engine, WalkForwardStateEngine):
        raise TypeError("engine must be a fitted WalkForwardStateEngine")
    if engine.has_pending_day:
        raise WalkForwardStateError("engine has an unresolved pending score date")
    prepared = _prepare_frame(
        target_frame,
        engine.config,
        label="walk-forward target block",
        require_outcome=True,
    )
    _aligned_ledger(
        direct_ledger,
        prepared,
        engine.config,
        exact=True,
        require_available=True,
    )
    target_days = prepared["_day"].to_numpy(dtype=np.int64)
    if int(target_days.min()) <= engine._history_end_day:
        raise WalkForwardStateError("target block overlaps or precedes current history")
    row_ids = tuple(prepared[engine.config.row_id_column].astype(str).tolist())
    if set(row_ids) & engine._known_row_ids:
        raise WalkForwardStateError("target block contains rows already in history")
    initial_history_end = engine.history_end_day
    initial_history_rows = engine.history_rows
    daily_bundles: list[WalkForwardDayBundle] = []
    for day in np.unique(target_days):
        positions = np.flatnonzero(target_days == day)
        raw_day = target_frame.iloc[positions].copy()
        day_ids = tuple(prepared.iloc[positions][engine.config.row_id_column].tolist())
        day_ledger = direct_ledger.subset(day_ids)
        bundle = engine.score_day(raw_day, day_ledger)
        daily_bundles.append(bundle)
        engine.advance_day(raw_day)
    components = _concatenate_components(daily_bundles, row_ids)
    return WalkForwardBlockBundle(
        row_ids=row_ids,
        class_order=PA_CLASS_ORDER,
        components=components,
        daily_bundles=tuple(daily_bundles),
        score_start_day=_day_string(int(target_days.min())),
        score_end_day=_day_string(int(target_days.max())),
        initial_history_end_day=initial_history_end,
        final_history_end_day=engine.history_end_day,
        input_rows=len(target_frame),
        scored_rows=sum(len(bundle.row_ids) for bundle in daily_bundles),
        advanced_rows=engine.history_rows - initial_history_rows,
    )


__all__ = [
    "ChronologicalDirectLedger",
    "CLUSTER_MATCHUP",
    "DECAY_180_DAY_STATE",
    "DECAY_365_DAY_STATE",
    "DIRECT_GOLD",
    "RANDOM_SEED",
    "RECENT_14_DAY_STATE",
    "RECENT_42_DAY_STATE",
    "RECENT_RESIDUAL_FORM",
    "RESIDUAL_EXPECTATION_SOURCE",
    "ROLLING_365_DAY_STATE",
    "ROLLING_730_DAY_STATE",
    "SCHEMA_VERSION",
    "SHRUNK_EXACT_BVP",
    "WALK_FORWARD_COMPONENT_ORDER",
    "WalkForwardBlockBundle",
    "WalkForwardDayBundle",
    "WalkForwardStateConfig",
    "WalkForwardStateEngine",
    "WalkForwardStateError",
    "fit_walk_forward_state",
    "score_walk_forward_block",
]
