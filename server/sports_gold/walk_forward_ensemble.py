"""Bounded walk-forward ensemble primitives for Phase 7B5.

This module has no filesystem or data-source access.  It receives governed,
row-aligned frames and probability arrays from its caller, freezes the final
2024 holdout before fitting, constructs five date-atomic expanding folds, and
provides daily-update-compatible scoring contracts.  No API accepts 2025 or
2026 dates and no object can register or promote a model.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.exceptions import ConvergenceWarning

from ..sports_modeling.metrics import (
    PA_CLASS_ORDER,
    encode_labels,
    validate_probability_matrix,
)
from .recent_state_ensemble import (
    FittedConvexBlend,
    compact_game_bootstrap,
    compact_multiclass_metrics,
    component_disagreement,
    fit_convex_blend,
)


SCHEMA_VERSION = "MLB_GOLD_WALK_FORWARD_ENSEMBLE_PRIMITIVES_V1"
HOLDOUT_ACTIVE_DATE_COUNT = 14
FOLD_COUNT = 5
STACKER_RANDOM_SEED = 20_260_826
STACKER_LOG_EPSILON = 1e-12

DIRECT_GOLD = "DIRECT_GOLD"
RECENT_14_DAY_STATE = "RECENT_14_DAY_STATE"
RECENT_42_DAY_STATE = "RECENT_42_DAY_STATE"
ROLLING_365_DAY_STATE = "ROLLING_365_DAY_STATE"
ROLLING_730_DAY_STATE = "ROLLING_730_DAY_STATE"
DECAY_180_DAY_STATE = "DECAY_180_DAY_STATE"
DECAY_365_DAY_STATE = "DECAY_365_DAY_STATE"
CLUSTER_MATCHUP = "CLUSTER_MATCHUP"
SHRUNK_EXACT_BVP = "SHRUNK_EXACT_BVP"
RECENT_RESIDUAL_FORM = "RECENT_RESIDUAL_FORM"

WALK_FORWARD_COMPONENT_ORDER: tuple[str, ...] = (
    DIRECT_GOLD,
    RECENT_14_DAY_STATE,
    RECENT_42_DAY_STATE,
    ROLLING_365_DAY_STATE,
    ROLLING_730_DAY_STATE,
    DECAY_180_DAY_STATE,
    DECAY_365_DAY_STATE,
    CLUSTER_MATCHUP,
    SHRUNK_EXACT_BVP,
    RECENT_RESIDUAL_FORM,
)
WALK_FORWARD_EMPIRICAL_COMPONENTS: tuple[str, ...] = WALK_FORWARD_COMPONENT_ORDER[1:]

FIXED_WALK_FORWARD_ENSEMBLES: Mapping[str, tuple[str, ...]] = {
    "E1": (DIRECT_GOLD, RECENT_14_DAY_STATE),
    "E2": (DIRECT_GOLD, RECENT_14_DAY_STATE, RECENT_42_DAY_STATE),
    "E3": (DIRECT_GOLD, ROLLING_365_DAY_STATE, ROLLING_730_DAY_STATE),
    "E4": (DIRECT_GOLD, DECAY_180_DAY_STATE, DECAY_365_DAY_STATE),
    "E5": (DIRECT_GOLD, CLUSTER_MATCHUP),
}
WALK_FORWARD_ENSEMBLE_IDS: tuple[str, ...] = (
    "E1",
    "E2",
    "E3",
    "E4",
    "E5",
    "E9",
    "E10",
)
COMPARISON_CANDIDATE_IDS: tuple[str, ...] = (
    "CLASS_FREQUENCY_NULL",
    "MATCHED_BASE",
    DIRECT_GOLD,
    *WALK_FORWARD_ENSEMBLE_IDS,
)

RELIABILITY_FIELDS: tuple[str, ...] = (
    "observationCount",
    "effectiveSampleSize",
    "missingHistoryFlag",
    "daysSincePriorAppearance",
    "entropy",
    "deviationFromLongTerm",
)
_RELIABILITY_SUFFIX: Mapping[str, str] = {
    "observationCount": "observation_count",
    "effectiveSampleSize": "effective_sample_size",
    "missingHistoryFlag": "missing_history",
    "daysSincePriorAppearance": "days_since_prior_appearance",
    "entropy": "entropy",
    "deviationFromLongTerm": "deviation_from_long_term",
}

STACKER_CONFIG: Mapping[str, Any] = {
    "estimator": "sklearn.linear_model.LogisticRegression",
    "C": 0.1,
    "penalty": "l2",
    "solver": "lbfgs",
    "maxIter": 5_000,
    "tol": 1e-6,
    "fitIntercept": True,
    "randomState": STACKER_RANDOM_SEED,
    "preprocessing": "StandardScaler",
    "featureContract": "MLB_GOLD_WALK_FORWARD_RELIABILITY_FEATURES_V1",
    "selectionCriterion": "DEVELOPMENT_WALK_FORWARD_OOF_LOG_LOSS_ONLY",
}


class WalkForwardEnsembleError(RuntimeError):
    """Raised when a temporal, row, probability, or fitted contract differs."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def _canonical_dates(values: Any, *, label: str = "game dates") -> pd.DatetimeIndex:
    source = values
    if isinstance(values, pd.DataFrame):
        if "game_date" not in values.columns:
            raise ValueError("date frame must contain game_date")
        source = values["game_date"]
    raw = np.asarray(source)
    if raw.ndim != 1 or raw.size == 0:
        raise ValueError(f"{label} must be a non-empty one-dimensional sequence")
    parsed = pd.DatetimeIndex(
        pd.to_datetime(raw, format="%Y-%m-%d", errors="raise")
    ).normalize()
    if parsed.hasnans:
        raise ValueError(f"{label} must not contain missing values")
    years = set(parsed.year.tolist())
    if not years.issubset({2021, 2022, 2023, 2024}):
        raise WalkForwardEnsembleError(
            f"{label} contains a season outside authorized 2021--2024: {sorted(years)}"
        )
    return parsed


def _boolean_mask(values: Any, *, rows: int, label: str) -> np.ndarray:
    raw = np.asarray(values)
    if raw.dtype.kind != "b" or raw.ndim != 1 or raw.size != rows:
        raise ValueError(f"{label} must be a row-aligned boolean vector")
    return raw.astype(bool, copy=True)


@dataclass(frozen=True)
class FrozenHoldout:
    """The final fourteen active 2024 dates, frozen before any fitting."""

    start_date: str
    end_date: str
    active_dates: tuple[str, ...]
    row_count: int
    game_count: int

    def __post_init__(self) -> None:
        if len(self.active_dates) != HOLDOUT_ACTIVE_DATE_COUNT:
            raise ValueError("holdout must contain exactly fourteen active dates")
        parsed = pd.DatetimeIndex(pd.to_datetime(self.active_dates, format="%Y-%m-%d"))
        if not parsed.is_monotonic_increasing or parsed.has_duplicates:
            raise ValueError("holdout active dates must be unique and increasing")
        if not np.all(parsed.year == 2024):
            raise ValueError("holdout active dates must all be in 2024")
        if (
            self.start_date != self.active_dates[0]
            or self.end_date != self.active_dates[-1]
        ):
            raise ValueError("holdout boundaries differ from its active dates")
        if self.row_count <= 0 or self.game_count <= 0:
            raise ValueError("holdout row and game counts must be positive")

    def mask(self, game_dates: Any) -> np.ndarray:
        dates = _canonical_dates(game_dates)
        result = np.isin(
            dates.to_numpy(dtype="datetime64[D]"),
            np.asarray(self.active_dates, dtype="datetime64[D]"),
        )
        result.setflags(write=False)
        return result

    @property
    def start(self) -> str:
        return self.start_date

    @property
    def end(self) -> str:
        return self.end_date

    @property
    def rows(self) -> int:
        return self.row_count

    @property
    def games(self) -> int:
        return self.game_count

    def record(self) -> dict[str, Any]:
        return {
            "schemaVersion": "MLB_GOLD_FINAL_14_ACTIVE_DATE_HOLDOUT_V1",
            "selectionRule": "FINAL_14_CALENDAR_DATES_CONTAINING_GOLD_PA_IN_2024",
            "startDate": self.start_date,
            "endDate": self.end_date,
            "activeDateCount": len(self.active_dates),
            "activeDates": list(self.active_dates),
            "rowCount": self.row_count,
            "gameCount": self.game_count,
            "frozenBeforeFit": True,
            "uses2025Or2026": False,
        }


def freeze_final_holdout(
    frame: pd.DataFrame,
    *,
    date_column: str = "game_date",
    game_id_column: str = "canonicalGameId",
) -> tuple[FrozenHoldout, np.ndarray]:
    """Freeze the final fourteen distinct 2024 dates that contain Gold rows."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("frame must be a non-empty pandas DataFrame")
    missing = sorted({date_column, game_id_column} - set(frame.columns))
    if missing:
        raise ValueError(f"holdout frame is missing columns: {missing}")
    dates = _canonical_dates(frame[date_column], label=date_column)
    active_2024 = np.unique(dates[dates.year == 2024].to_numpy(dtype="datetime64[D]"))
    if active_2024.size < HOLDOUT_ACTIVE_DATE_COUNT:
        raise WalkForwardEnsembleError(
            "2024 contains fewer than fourteen active Gold PA dates"
        )
    selected = active_2024[-HOLDOUT_ACTIVE_DATE_COUNT:]
    mask = np.isin(dates.to_numpy(dtype="datetime64[D]"), selected)
    if int(mask.sum()) <= 0:
        raise WalkForwardEnsembleError("frozen holdout is empty")
    raw_games = frame.loc[mask, game_id_column]
    if raw_games.isna().any():
        raise ValueError("holdout game identities must not be missing")
    games = raw_games.astype(str)
    if games.str.strip().eq("").any():
        raise ValueError("holdout game identities must be non-empty")
    active_dates = tuple(pd.Timestamp(value).strftime("%Y-%m-%d") for value in selected)
    holdout = FrozenHoldout(
        start_date=active_dates[0],
        end_date=active_dates[-1],
        active_dates=active_dates,
        row_count=int(mask.sum()),
        game_count=int(games.nunique()),
    )
    if not np.array_equal(mask, holdout.mask(frame[date_column])):
        raise WalkForwardEnsembleError("frozen holdout mask is not reproducible")
    mask.setflags(write=False)
    return holdout, mask


@dataclass(frozen=True)
class WalkForwardFold:
    """One expanding, date-atomic, approximately equal-PA validation fold."""

    fold_id: str
    train_end: str
    validation_start: str
    validation_end: str
    validation_active_dates: tuple[str, ...]
    training_rows: int
    validation_rows: int
    target_validation_rows: float

    def record(self) -> dict[str, Any]:
        return {
            "foldId": self.fold_id,
            "trainingRule": "game_date < validationStart",
            "trainEnd": self.train_end,
            "trainingRows": self.training_rows,
            "validationStart": self.validation_start,
            "validationEnd": self.validation_end,
            "validationActiveDateCount": len(self.validation_active_dates),
            "validationRows": self.validation_rows,
            "targetValidationRows": float(self.target_validation_rows),
            "absoluteRowDeviationFromTarget": float(
                abs(self.validation_rows - self.target_validation_rows)
            ),
            "dateAtomic": True,
            "randomSplit": False,
            "currentDayInHistory": False,
            "earlierValidationDaysUpdateLaterDays": True,
        }


def _optimal_equal_pa_boundaries(counts: np.ndarray, blocks: int) -> tuple[int, ...]:
    """Globally minimize maximum PA deviation, then squared deviation.

    Boundaries are whole active dates.  Integer-scaled deviations avoid any
    platform-sensitive floating comparison.  A final lexicographic endpoint
    tie-break makes the optimum unique and reproducible.
    """

    if counts.ndim != 1 or counts.size < blocks or np.any(counts <= 0):
        raise ValueError("date counts must be positive and contain at least five dates")
    date_count = int(counts.size)
    prefix = np.concatenate(
        (np.asarray([0], dtype=np.int64), np.cumsum(counts, dtype=np.int64))
    )
    total = int(prefix[-1])
    # State value: (maximum scaled absolute deviation, scaled SSE, endpoints).
    previous: dict[int, tuple[int, int, tuple[int, ...]]] = {0: (0, 0, ())}
    for block_number in range(1, blocks + 1):
        current: dict[int, tuple[int, int, tuple[int, ...]]] = {}
        minimum_end = block_number
        maximum_end = date_count - (blocks - block_number)
        for end in range(minimum_end, maximum_end + 1):
            best: tuple[int, int, tuple[int, ...]] | None = None
            for start in range(block_number - 1, end):
                prior = previous.get(start)
                if prior is None:
                    continue
                segment_rows = int(prefix[end] - prefix[start])
                scaled_deviation = abs(segment_rows * blocks - total)
                candidate = (
                    max(prior[0], scaled_deviation),
                    prior[1] + scaled_deviation * scaled_deviation,
                    (*prior[2], end),
                )
                if best is None or candidate < best:
                    best = candidate
            if best is not None:
                current[end] = best
        previous = current
    optimum = previous.get(date_count)
    if optimum is None or len(optimum[2]) != blocks:
        raise WalkForwardEnsembleError("equal-PA fold optimization failed")
    # Stored endpoints are exclusive; split() needs inclusive end indices.
    return tuple(endpoint - 1 for endpoint in optimum[2][:-1])


def five_equal_pa_walk_forward_folds(
    frame: pd.DataFrame,
    holdout: FrozenHoldout,
    *,
    date_column: str = "game_date",
) -> list[tuple[WalkForwardFold, np.ndarray, np.ndarray]]:
    """Split 2022 through pre-holdout dates into five whole-date PA quintiles."""

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError("frame must be a non-empty pandas DataFrame")
    if date_column not in frame.columns:
        raise ValueError(f"walk-forward frame is missing {date_column}")
    dates = _canonical_dates(frame[date_column], label=date_column)
    holdout_start = pd.Timestamp(holdout.start_date)
    eligible = (dates >= pd.Timestamp("2022-01-01")) & (dates < holdout_start)
    if not eligible.any():
        raise WalkForwardEnsembleError("walk-forward validation universe is empty")
    active_dates, counts = np.unique(
        dates[eligible].to_numpy(dtype="datetime64[D]"), return_counts=True
    )
    boundaries = _optimal_equal_pa_boundaries(counts, FOLD_COUNT)
    date_blocks = np.split(active_dates, [index + 1 for index in boundaries])
    if len(date_blocks) != FOLD_COUNT or any(block.size == 0 for block in date_blocks):
        raise WalkForwardEnsembleError("walk-forward date partition is malformed")

    output: list[tuple[WalkForwardFold, np.ndarray, np.ndarray]] = []
    covered = np.zeros(len(frame), dtype=bool)
    target_rows = int(eligible.sum()) / FOLD_COUNT
    date_values = dates.to_numpy(dtype="datetime64[D]")
    for number, block in enumerate(date_blocks, start=1):
        validation = np.isin(date_values, block) & eligible
        validation_start = pd.Timestamp(block[0])
        training = dates < validation_start
        if not training.any() or not validation.any() or np.any(training & validation):
            raise WalkForwardEnsembleError(f"FOLD_{number} is empty or overlaps")
        if dates[training].max() >= dates[validation].min():
            raise WalkForwardEnsembleError(
                f"FOLD_{number} training is not strictly earlier than validation"
            )
        if covered[validation].any():
            raise WalkForwardEnsembleError("walk-forward validation folds overlap")
        covered |= validation
        block_dates = tuple(pd.Timestamp(value).strftime("%Y-%m-%d") for value in block)
        fold = WalkForwardFold(
            fold_id=f"FOLD_{number}",
            train_end=dates[training].max().strftime("%Y-%m-%d"),
            validation_start=block_dates[0],
            validation_end=block_dates[-1],
            validation_active_dates=block_dates,
            training_rows=int(training.sum()),
            validation_rows=int(validation.sum()),
            target_validation_rows=float(target_rows),
        )
        training.setflags(write=False)
        validation.setflags(write=False)
        output.append((fold, training, validation))
    if not np.array_equal(covered, np.asarray(eligible, dtype=bool)):
        raise WalkForwardEnsembleError(
            "five folds do not cover exactly 2022 through pre-holdout rows"
        )
    return output


@dataclass(frozen=True)
class DailyScoreDay:
    score_date: str
    history_rows: int
    score_rows: int

    @property
    def day(self) -> str:
        return self.score_date

    def record(self) -> dict[str, Any]:
        return {
            "scoreDate": self.score_date,
            "historyRule": "game_date < scoreDate",
            "historyRows": self.history_rows,
            "scoreRows": self.score_rows,
            "currentDayExcluded": True,
        }


def daily_walk_forward_masks(
    game_dates: Any,
    score_mask: Any,
    *,
    history_eligible_mask: Any | None = None,
) -> list[tuple[DailyScoreDay, np.ndarray, np.ndarray]]:
    """Return strictly-prior history and current-date score masks per active day.

    Earlier dates in the score period are included in the history of later
    dates, which is the required daily D-1 update behavior.
    """

    dates = _canonical_dates(game_dates)
    rows = len(dates)
    scoring = _boolean_mask(score_mask, rows=rows, label="score_mask")
    if not scoring.any():
        raise ValueError("score_mask must select at least one row")
    history_eligible = (
        np.ones(rows, dtype=bool)
        if history_eligible_mask is None
        else _boolean_mask(
            history_eligible_mask, rows=rows, label="history_eligible_mask"
        )
    )
    score_dates = np.unique(dates[scoring].to_numpy(dtype="datetime64[D]"))
    output: list[tuple[DailyScoreDay, np.ndarray, np.ndarray]] = []
    covered = np.zeros(rows, dtype=bool)
    for raw_day in score_dates:
        day = pd.Timestamp(raw_day)
        history = history_eligible & np.asarray(dates < day, dtype=bool)
        current = scoring & np.asarray(dates == day, dtype=bool)
        if not current.any() or np.any(history & current):
            raise WalkForwardEnsembleError(
                "daily score masks are empty or overlap history"
            )
        if history.any() and dates[history].max() >= day:
            raise WalkForwardEnsembleError(
                "daily history includes current or future rows"
            )
        covered |= current
        record = DailyScoreDay(
            score_date=day.strftime("%Y-%m-%d"),
            history_rows=int(history.sum()),
            score_rows=int(current.sum()),
        )
        history.setflags(write=False)
        current.setflags(write=False)
        output.append((record, history, current))
    if not np.array_equal(covered, scoring):
        raise WalkForwardEnsembleError("daily masks do not reconcile to the score mask")
    return output


def _validated_components(
    probabilities: Mapping[str, Any],
    *,
    required: Sequence[str] = WALK_FORWARD_COMPONENT_ORDER,
) -> dict[str, np.ndarray]:
    if not isinstance(probabilities, Mapping):
        raise TypeError("component probabilities must be a mapping")
    order = tuple(required)
    if tuple(probabilities) != order:
        raise ValueError(
            "component mapping must preserve the exact walk-forward component order"
        )
    matrices = {
        name: validate_probability_matrix(
            probabilities[name], class_order=PA_CLASS_ORDER
        )
        for name in order
    }
    if len({matrix.shape[0] for matrix in matrices.values()}) != 1:
        raise ValueError("component probability matrices are not row-aligned")
    return matrices


def fixed_walk_forward_ensemble_definitions() -> dict[str, dict[str, Any]]:
    return {
        ensemble_id: {
            "ensembleId": ensemble_id,
            "method": "FIXED_EQUAL_WEIGHT_PROBABILITY_AVERAGE",
            "memberIds": list(members),
            "weights": {member: 1.0 / len(members) for member in members},
            "fitted": False,
        }
        for ensemble_id, members in FIXED_WALK_FORWARD_ENSEMBLES.items()
    }


def build_fixed_walk_forward_ensembles(
    component_probabilities: Mapping[str, Any],
) -> dict[str, np.ndarray]:
    """Build exactly the five fixed equal-weight walk-forward ensembles."""

    matrices = _validated_components(component_probabilities)
    output: dict[str, np.ndarray] = {}
    for ensemble_id, members in FIXED_WALK_FORWARD_ENSEMBLES.items():
        result = np.mean(
            np.stack([matrices[name] for name in members], axis=0),
            axis=0,
            dtype=np.float64,
        )
        result = validate_probability_matrix(result, class_order=PA_CLASS_ORDER)
        result.setflags(write=False)
        output[ensemble_id] = result
    return output


def _validate_oof_dates(
    oof_dates: Any, *, rows: int, holdout: FrozenHoldout
) -> pd.DatetimeIndex:
    dates = _canonical_dates(oof_dates, label="OOF dates")
    if len(dates) != rows:
        raise ValueError("OOF dates are not row-aligned")
    if dates.min() < pd.Timestamp("2022-01-01"):
        raise WalkForwardEnsembleError("OOF fitting includes a pre-2022 validation row")
    if dates.max() >= pd.Timestamp(holdout.start_date):
        raise WalkForwardEnsembleError("OOF fitting includes a frozen-holdout row")
    return dates


@dataclass(frozen=True)
class FittedWalkForwardConvexBlend:
    """E9 wrapper carrying the exact pre-holdout walk-forward fit authority."""

    delegate: FittedConvexBlend

    @property
    def component_ids(self) -> tuple[str, ...]:
        return self.delegate.component_ids

    @property
    def weights(self) -> tuple[float, ...]:
        return self.delegate.weights

    @property
    def optimizer_record(self) -> Mapping[str, Any]:
        return self.delegate.optimizer_record

    def predict_proba(self, probabilities: Mapping[str, Any]) -> np.ndarray:
        return self.delegate.predict_proba(probabilities)

    def record(self) -> dict[str, Any]:
        return {
            "ensembleId": "E9",
            "label": "OOF_OPTIMIZED_CONVEX_BLEND",
            "method": "STATIC_NONNEGATIVE_CONVEX_PROBABILITY_BLEND",
            "memberIds": list(self.component_ids),
            "weights": {
                component: float(weight)
                for component, weight in zip(
                    self.component_ids, self.weights, strict=True
                )
            },
            "weightSum": float(math.fsum(self.weights)),
            "fitPopulation": "PRE_HOLDOUT_WALK_FORWARD_OOF_ONLY",
            "selectionCriterion": "PRE_HOLDOUT_WALK_FORWARD_OOF_LOG_LOSS_ONLY",
            "weightsFrozenBeforeHoldout": True,
            "usesHoldoutForFit": False,
            "optimizer": _json_safe(self.optimizer_record),
        }


def fit_walk_forward_convex_blend(
    labels: Any,
    oof_component_probabilities: Mapping[str, Any],
    oof_dates: Any,
    holdout: FrozenHoldout,
) -> FittedWalkForwardConvexBlend:
    """Fit E9 on pre-holdout walk-forward OOF predictions only."""

    matrices = _validated_components(oof_component_probabilities)
    rows = next(iter(matrices.values())).shape[0]
    _validate_oof_dates(oof_dates, rows=rows, holdout=holdout)
    return FittedWalkForwardConvexBlend(
        delegate=fit_convex_blend(
            labels,
            matrices,
            component_order=WALK_FORWARD_COMPONENT_ORDER,
        )
    )


def _one_dimensional_feature(
    values: Any,
    *,
    rows: int,
    label: str,
    allow_missing: bool = False,
) -> np.ndarray:
    raw = np.asarray(values)
    if raw.dtype.kind not in "fiub" or raw.ndim != 1 or raw.size != rows:
        raise ValueError(f"{label} must be a numeric row-aligned vector")
    result = np.asarray(raw, dtype=np.float64)
    if allow_missing:
        if np.isinf(result).any():
            raise ValueError(f"{label} must not contain infinity")
        result = np.nan_to_num(result, nan=0.0)
    elif not np.isfinite(result).all():
        raise ValueError(f"{label} must contain only finite values")
    return result


def _canonical_reliability(
    reliability_inputs: pd.DataFrame | Mapping[str, Any],
    *,
    rows: int,
) -> dict[str, dict[str, np.ndarray]]:
    expected_flat = {
        f"{component}__{field}"
        for component in WALK_FORWARD_EMPIRICAL_COMPONENTS
        for field in RELIABILITY_FIELDS
    }
    if isinstance(reliability_inputs, pd.DataFrame):
        if (
            len(reliability_inputs) != rows
            or set(reliability_inputs.columns) != expected_flat
        ):
            raise ValueError("reliability DataFrame differs from the fixed contract")
        source: Mapping[str, Any] = {
            component: {
                field: reliability_inputs[f"{component}__{field}"].to_numpy(copy=False)
                for field in RELIABILITY_FIELDS
            }
            for component in WALK_FORWARD_EMPIRICAL_COMPONENTS
        }
    elif isinstance(reliability_inputs, Mapping) and set(reliability_inputs) == set(
        WALK_FORWARD_EMPIRICAL_COMPONENTS
    ):
        source = reliability_inputs
    elif (
        isinstance(reliability_inputs, Mapping)
        and set(reliability_inputs) == expected_flat
    ):
        source = {
            component: {
                field: reliability_inputs[f"{component}__{field}"]
                for field in RELIABILITY_FIELDS
            }
            for component in WALK_FORWARD_EMPIRICAL_COMPONENTS
        }
    else:
        raise ValueError("reliability inputs differ from the fixed component contract")

    output: dict[str, dict[str, np.ndarray]] = {}
    for component in WALK_FORWARD_EMPIRICAL_COMPONENTS:
        fields = source[component]
        if not isinstance(fields, Mapping) or set(fields) != set(RELIABILITY_FIELDS):
            raise ValueError(f"reliability fields differ for {component}")
        output[component] = {
            field: _one_dimensional_feature(
                fields[field],
                rows=rows,
                label=f"{component}__{field}",
                allow_missing=field == "daysSincePriorAppearance",
            )
            for field in RELIABILITY_FIELDS
        }
        observed = output[component]["observationCount"]
        effective = output[component]["effectiveSampleSize"]
        missing = output[component]["missingHistoryFlag"]
        days = output[component]["daysSincePriorAppearance"]
        entropy = output[component]["entropy"]
        deviation = output[component]["deviationFromLongTerm"]
        if (
            np.any(observed < 0.0)
            or np.any(effective < 0.0)
            or np.any(effective > observed + 1e-8)
        ):
            raise ValueError(f"reliability counts are invalid for {component}")
        if not np.isin(missing, [0.0, 1.0]).all():
            raise ValueError(f"missing-history flags are invalid for {component}")
        if (
            np.any(days < 0.0)
            or np.any(entropy < 0.0)
            or np.any(deviation < 0.0)
            or np.any(deviation > 1.0 + 1e-10)
        ):
            raise ValueError(f"reliability diagnostics are invalid for {component}")
    return output


def build_walk_forward_stacker_features(
    component_probabilities: Mapping[str, Any],
    reliability_inputs: pd.DataFrame | Mapping[str, Any],
) -> tuple[np.ndarray, tuple[str, ...]]:
    """Build the one fixed 167-column E10 reliability feature contract."""

    matrices = _validated_components(component_probabilities)
    rows = matrices[DIRECT_GOLD].shape[0]
    reliability = _canonical_reliability(reliability_inputs, rows=rows)
    blocks: list[np.ndarray] = []
    names: list[str] = []
    for component in WALK_FORWARD_COMPONENT_ORDER:
        blocks.append(np.log(np.clip(matrices[component], STACKER_LOG_EPSILON, 1.0)))
        names.extend(
            f"{component}__log_probability__{class_name}"
            for class_name in PA_CLASS_ORDER
        )
        if component != DIRECT_GOLD:
            for field in RELIABILITY_FIELDS:
                blocks.append(reliability[component][field][:, None])
                names.append(f"{component}__{_RELIABILITY_SUFFIX[field]}")
            blocks.append(
                component_disagreement(matrices[component], matrices[DIRECT_GOLD])[
                    :, None
                ]
            )
            names.append(f"{component}__direct_total_variation_disagreement")

    long_term = matrices[ROLLING_365_DAY_STATE]
    for recent in (
        RECENT_14_DAY_STATE,
        RECENT_42_DAY_STATE,
        RECENT_RESIDUAL_FORM,
    ):
        blocks.append(matrices[recent] - long_term)
        names.extend(
            f"{recent}__minus_rolling_365__{class_name}"
            for class_name in PA_CLASS_ORDER
        )
    result = np.concatenate(blocks, axis=1)
    if result.shape != (rows, 167) or len(names) != 167:
        raise WalkForwardEnsembleError("walk-forward stacker feature shape differs")
    if not np.isfinite(result).all() or len(set(names)) != len(names):
        raise WalkForwardEnsembleError("walk-forward stacker features are invalid")
    result.setflags(write=False)
    return result, tuple(names)


@dataclass
class FittedWalkForwardStacker:
    scaler: StandardScaler
    estimator: LogisticRegression
    feature_names: tuple[str, ...]

    def predict_proba(
        self,
        component_probabilities: Mapping[str, Any],
        reliability_inputs: pd.DataFrame | Mapping[str, Any],
    ) -> np.ndarray:
        features, names = build_walk_forward_stacker_features(
            component_probabilities, reliability_inputs
        )
        if names != self.feature_names:
            raise WalkForwardEnsembleError(
                "E10 score feature contract differs from fit"
            )
        transformed = self.scaler.transform(features)
        probabilities = self.estimator.predict_proba(transformed)
        if not np.array_equal(
            np.asarray(self.estimator.classes_, dtype=np.int64),
            np.arange(len(PA_CLASS_ORDER), dtype=np.int64),
        ):
            raise WalkForwardEnsembleError("E10 fitted class order differs")
        result = validate_probability_matrix(probabilities, class_order=PA_CLASS_ORDER)
        result.setflags(write=False)
        return result

    def coefficient_importance(self) -> dict[str, Any]:
        coefficients = np.mean(np.abs(self.estimator.coef_), axis=0)
        grouped = {component: 0.0 for component in WALK_FORWARD_COMPONENT_ORDER}
        other = 0.0
        for feature, value in zip(self.feature_names, coefficients, strict=True):
            matched = [
                component
                for component in WALK_FORWARD_COMPONENT_ORDER
                if component in feature
            ]
            if matched:
                for component in matched:
                    grouped[component] += float(value) / len(matched)
            else:
                other += float(value)
        denominator = math.fsum(grouped.values()) + other
        return {
            "definition": "NORMALIZED_MEAN_ABSOLUTE_MULTINOMIAL_COEFFICIENT_MAGNITUDE",
            "notProbabilityWeights": True,
            "componentImportance": {
                component: float(value / denominator) if denominator else 0.0
                for component, value in grouped.items()
            },
            "otherFeatureImportance": (
                float(other / denominator) if denominator else 0.0
            ),
        }

    def record(self) -> dict[str, Any]:
        return {
            "ensembleId": "E10",
            "label": "RELIABILITY_GATED_ENSEMBLE",
            "method": "REGULARIZED_MULTINOMIAL_LOGISTIC_STACKER",
            "configuration": dict(STACKER_CONFIG),
            "featureCount": len(self.feature_names),
            "featureNames": list(self.feature_names),
            "fitPopulation": "PRE_HOLDOUT_WALK_FORWARD_OOF_ONLY",
            "coefficientsFrozenBeforeHoldout": True,
            "usesHoldoutForFit": False,
            "coefficientImportance": self.coefficient_importance(),
        }


def fit_walk_forward_stacker(
    labels: Any,
    oof_component_probabilities: Mapping[str, Any],
    oof_reliability_inputs: pd.DataFrame | Mapping[str, Any],
    oof_dates: Any,
    holdout: FrozenHoldout,
) -> FittedWalkForwardStacker:
    """Fit and freeze E10 on pre-holdout walk-forward OOF predictions only."""

    encoded = encode_labels(labels, class_order=PA_CLASS_ORDER)
    features, feature_names = build_walk_forward_stacker_features(
        oof_component_probabilities, oof_reliability_inputs
    )
    if len(encoded) != len(features):
        raise ValueError("OOF labels and E10 features are not row-aligned")
    _validate_oof_dates(oof_dates, rows=len(encoded), holdout=holdout)
    if not np.array_equal(np.unique(encoded), np.arange(len(PA_CLASS_ORDER))):
        raise WalkForwardEnsembleError("E10 OOF labels lack a governed class")
    scaler = StandardScaler(copy=True, with_mean=True, with_std=True)
    transformed = scaler.fit_transform(features)
    estimator = LogisticRegression(
        C=float(STACKER_CONFIG["C"]),
        penalty=str(STACKER_CONFIG["penalty"]),
        solver=str(STACKER_CONFIG["solver"]),
        max_iter=int(STACKER_CONFIG["maxIter"]),
        tol=float(STACKER_CONFIG["tol"]),
        fit_intercept=bool(STACKER_CONFIG["fitIntercept"]),
        random_state=int(STACKER_CONFIG["randomState"]),
    )
    with warnings.catch_warnings(record=True) as observed_warnings:
        warnings.simplefilter("always", ConvergenceWarning)
        estimator.fit(transformed, encoded)
    convergence_warnings = [
        item
        for item in observed_warnings
        if issubclass(item.category, ConvergenceWarning)
    ]
    if convergence_warnings:
        raise WalkForwardEnsembleError(
            "E10 emitted a convergence warning under the fixed config"
        )
    if np.any(np.asarray(estimator.n_iter_) >= int(STACKER_CONFIG["maxIter"])):
        raise WalkForwardEnsembleError("E10 failed to converge under the fixed config")
    if not np.array_equal(
        np.asarray(estimator.classes_, dtype=np.int64),
        np.arange(len(PA_CLASS_ORDER), dtype=np.int64),
    ):
        raise WalkForwardEnsembleError("E10 fitted class order differs")
    artifact = FittedWalkForwardStacker(
        scaler=scaler,
        estimator=estimator,
        feature_names=feature_names,
    )
    artifact.predict_proba(oof_component_probabilities, oof_reliability_inputs)
    return artifact


def class_frequency_null_probabilities(
    training_labels: Any,
    score_rows: int,
) -> np.ndarray:
    """Fit the exact class-frequency null and repeat it for a score block."""

    encoded = encode_labels(training_labels, class_order=PA_CLASS_ORDER)
    if not isinstance(score_rows, (int, np.integer)) or isinstance(score_rows, bool):
        raise TypeError("score_rows must be a positive integer")
    if int(score_rows) <= 0:
        raise ValueError("score_rows must be a positive integer")
    counts = np.bincount(encoded, minlength=len(PA_CLASS_ORDER)).astype(np.float64)
    probabilities = counts / counts.sum()
    result = np.repeat(probabilities[None, :], int(score_rows), axis=0)
    result = validate_probability_matrix(result, class_order=PA_CLASS_ORDER)
    result.setflags(write=False)
    return result


def _coverage(
    rows: int,
    coverage_mask: Any | None,
    effective_sample_size: Any | None,
) -> dict[str, Any]:
    mask = (
        np.ones(rows, dtype=bool)
        if coverage_mask is None
        else _boolean_mask(coverage_mask, rows=rows, label="coverage mask")
    )
    if effective_sample_size is None:
        values = np.asarray([], dtype=np.float64)
    else:
        effective = _one_dimensional_feature(
            effective_sample_size, rows=rows, label="effective sample size"
        )
        if np.any(effective < 0.0):
            raise ValueError("effective sample size must be nonnegative")
        values = effective[mask]
    return {
        "coveredRows": int(mask.sum()),
        "coverage": float(mask.mean()),
        "effectiveSampleSizeMean": float(values.mean()) if values.size else None,
        "effectiveSampleSizeMedian": float(np.median(values)) if values.size else None,
    }


def evaluate_walk_forward_candidates(
    labels: Any,
    candidate_probabilities: Mapping[str, Any],
    *,
    coverage_masks: Mapping[str, Any] | None = None,
    effective_sample_sizes: Mapping[str, Any] | None = None,
    require_complete_inventory: bool = True,
) -> list[dict[str, Any]]:
    """Evaluate null, matched Base, Direct Gold, and the seven ensembles."""

    if not isinstance(candidate_probabilities, Mapping):
        raise TypeError("candidate probabilities must be a mapping")
    if (
        require_complete_inventory
        and tuple(candidate_probabilities) != COMPARISON_CANDIDATE_IDS
    ):
        raise ValueError(
            "candidate mapping differs from the fixed comparison inventory"
        )
    encoded = encode_labels(labels, class_order=PA_CLASS_ORDER)
    records: list[dict[str, Any]] = []
    for candidate_id, raw in candidate_probabilities.items():
        matrix = validate_probability_matrix(raw, class_order=PA_CLASS_ORDER)
        if len(matrix) != len(encoded):
            raise ValueError(f"{candidate_id} is not row-aligned")
        records.append(
            {
                "candidateId": candidate_id,
                "status": "SUCCESS",
                "evaluationPopulation": "WALK_FORWARD_OR_FROZEN_HOLDOUT",
                "metrics": compact_multiclass_metrics(encoded, matrix),
                **_coverage(
                    len(encoded),
                    (coverage_masks or {}).get(candidate_id),
                    (effective_sample_sizes or {}).get(candidate_id),
                ),
            }
        )
    return sorted(records, key=lambda row: float(row["metrics"]["logLoss"]))


def select_oof_winner(
    leaderboard: Sequence[Mapping[str, Any]],
    *,
    eligible_ids: Sequence[str],
) -> dict[str, Any]:
    """Select strictly by pre-holdout walk-forward OOF log loss."""

    eligible = set(eligible_ids)
    rows = [
        (index, row)
        for index, row in enumerate(leaderboard)
        if row.get("candidateId") in eligible and row.get("status") == "SUCCESS"
    ]
    if not rows:
        raise WalkForwardEnsembleError("OOF leaderboard has no eligible candidate")
    index, winner = min(
        rows,
        key=lambda item: (float(item[1]["metrics"]["logLoss"]), item[0]),
    )
    del index
    result = _json_safe(winner)
    result["selectedBy"] = "MINIMUM_PRE_HOLDOUT_WALK_FORWARD_OOF_LOG_LOSS_ONLY"
    result["holdoutUsedForSelection"] = False
    return result


def daily_metric_records(
    labels: Any,
    game_dates: Any,
    candidate_probabilities: Mapping[str, Any],
    *,
    direct_id: str = DIRECT_GOLD,
) -> list[dict[str, Any]]:
    """Return daily metrics and daily-minus-Direct log-loss differences."""

    encoded = encode_labels(labels, class_order=PA_CLASS_ORDER)
    dates = _canonical_dates(game_dates)
    if len(dates) != len(encoded):
        raise ValueError("daily metric dates and labels are not row-aligned")
    matrices = {
        candidate_id: validate_probability_matrix(raw, class_order=PA_CLASS_ORDER)
        for candidate_id, raw in candidate_probabilities.items()
    }
    if direct_id not in matrices or any(
        len(matrix) != len(encoded) for matrix in matrices.values()
    ):
        raise ValueError(
            "daily metric probabilities are missing Direct or not row-aligned"
        )
    records: list[dict[str, Any]] = []
    for raw_day in np.unique(dates.to_numpy(dtype="datetime64[D]")):
        day = pd.Timestamp(raw_day)
        mask = np.asarray(dates == day, dtype=bool)
        direct_metrics = compact_multiclass_metrics(
            encoded[mask], matrices[direct_id][mask]
        )
        for candidate_id, matrix in matrices.items():
            metrics = compact_multiclass_metrics(encoded[mask], matrix[mask])
            records.append(
                {
                    "scoreDate": day.strftime("%Y-%m-%d"),
                    "candidateId": candidate_id,
                    "metrics": metrics,
                    "logLossDifferenceVsDirect": float(
                        metrics["logLoss"] - direct_metrics["logLoss"]
                    ),
                }
            )
    return records


@dataclass
class DailyPredictionAccumulator:
    """Fail-closed collector ensuring every eligible row is scored exactly once."""

    row_count: int
    candidate_ids: tuple[str, ...]
    _matrices: dict[str, np.ndarray] = field(init=False, repr=False)
    _covered: np.ndarray = field(init=False, repr=False)
    _last_day: pd.Timestamp | None = field(default=None, init=False, repr=False)
    _daily_records: list[dict[str, Any]] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        if self.row_count <= 0:
            raise ValueError("row_count must be positive")
        if not self.candidate_ids or len(set(self.candidate_ids)) != len(
            self.candidate_ids
        ):
            raise ValueError("candidate_ids must be non-empty and unique")
        self._matrices = {
            candidate_id: np.full(
                (self.row_count, len(PA_CLASS_ORDER)), np.nan, dtype=np.float64
            )
            for candidate_id in self.candidate_ids
        }
        self._covered = np.zeros(self.row_count, dtype=bool)

    def add_day(
        self,
        score_date: str,
        positions: Any,
        predictions: Mapping[str, Any],
    ) -> None:
        day = pd.Timestamp(score_date).normalize()
        if day.year not in {2021, 2022, 2023, 2024}:
            raise WalkForwardEnsembleError("daily accumulator rejects post-2024 dates")
        if self._last_day is not None and day <= self._last_day:
            raise WalkForwardEnsembleError(
                "daily predictions must be added chronologically"
            )
        raw_positions = np.asarray(positions)
        if (
            raw_positions.dtype.kind not in "iu"
            or raw_positions.ndim != 1
            or raw_positions.size == 0
        ):
            raise ValueError("positions must be a non-empty integer vector")
        aligned = raw_positions.astype(np.int64, copy=False)
        if (
            np.any(aligned < 0)
            or np.any(aligned >= self.row_count)
            or len(set(aligned.tolist())) != aligned.size
        ):
            raise ValueError("positions are out of bounds or duplicated")
        if self._covered[aligned].any():
            raise WalkForwardEnsembleError("a prediction row was scored more than once")
        if tuple(predictions) != self.candidate_ids:
            raise ValueError("daily prediction mapping differs from candidate_ids")
        validated: dict[str, np.ndarray] = {}
        for candidate_id in self.candidate_ids:
            matrix = validate_probability_matrix(
                predictions[candidate_id], class_order=PA_CLASS_ORDER
            )
            if len(matrix) != len(aligned):
                raise ValueError(
                    f"daily {candidate_id} predictions are not row-aligned"
                )
            validated[candidate_id] = matrix
        # Commit only after every candidate for the day validates.
        for candidate_id, matrix in validated.items():
            self._matrices[candidate_id][aligned] = matrix
        self._covered[aligned] = True
        self._last_day = day
        self._daily_records.append(
            {
                "scoreDate": day.strftime("%Y-%m-%d"),
                "rowCount": int(aligned.size),
                "candidateCount": len(self.candidate_ids),
            }
        )

    def finalize(
        self, expected_mask: Any
    ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
        expected = _boolean_mask(
            expected_mask, rows=self.row_count, label="expected_mask"
        )
        if not np.array_equal(self._covered, expected):
            missing = int(np.count_nonzero(expected & ~self._covered))
            unexpected = int(np.count_nonzero(self._covered & ~expected))
            raise WalkForwardEnsembleError(
                f"daily prediction coverage differs: missing={missing}, unexpected={unexpected}"
            )
        output: dict[str, np.ndarray] = {}
        for candidate_id, matrix in self._matrices.items():
            selected = validate_probability_matrix(
                matrix[expected], class_order=PA_CLASS_ORDER
            )
            selected.setflags(write=False)
            output[candidate_id] = selected
        return output, {
            "schemaVersion": "MLB_GOLD_DAILY_PREDICTION_RECONCILIATION_V1",
            "eligibleRows": int(expected.sum()),
            "scoredRows": int(self._covered.sum()),
            "candidateIds": list(self.candidate_ids),
            "dailyRecords": list(self._daily_records),
            "missingRows": 0,
            "unexpectedRows": 0,
            "duplicateRows": 0,
            "complete": True,
        }


__all__ = [
    "CLUSTER_MATCHUP",
    "COMPARISON_CANDIDATE_IDS",
    "DECAY_180_DAY_STATE",
    "DECAY_365_DAY_STATE",
    "DIRECT_GOLD",
    "DailyPredictionAccumulator",
    "DailyScoreDay",
    "FIXED_WALK_FORWARD_ENSEMBLES",
    "FOLD_COUNT",
    "FittedWalkForwardConvexBlend",
    "FittedWalkForwardStacker",
    "FrozenHoldout",
    "HOLDOUT_ACTIVE_DATE_COUNT",
    "RECENT_14_DAY_STATE",
    "RECENT_42_DAY_STATE",
    "RECENT_RESIDUAL_FORM",
    "RELIABILITY_FIELDS",
    "ROLLING_365_DAY_STATE",
    "ROLLING_730_DAY_STATE",
    "SCHEMA_VERSION",
    "SHRUNK_EXACT_BVP",
    "STACKER_CONFIG",
    "WALK_FORWARD_COMPONENT_ORDER",
    "WALK_FORWARD_EMPIRICAL_COMPONENTS",
    "WALK_FORWARD_ENSEMBLE_IDS",
    "WalkForwardEnsembleError",
    "WalkForwardFold",
    "build_fixed_walk_forward_ensembles",
    "build_walk_forward_stacker_features",
    "class_frequency_null_probabilities",
    "compact_game_bootstrap",
    "daily_metric_records",
    "daily_walk_forward_masks",
    "evaluate_walk_forward_candidates",
    "fit_walk_forward_convex_blend",
    "fit_walk_forward_stacker",
    "five_equal_pa_walk_forward_folds",
    "fixed_walk_forward_ensemble_definitions",
    "freeze_final_holdout",
    "select_oof_winner",
]
