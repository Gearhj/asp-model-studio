"""Pure pregame probability-card adapter for Phase 7B6 whole-game simulation.

The adapter consumes exactly eighteen already-authorized starting-matchup template rows and
their aligned Phase 7B5 prediction evidence.  It performs no I/O, fitting, participant lookup,
or outcome access.  Current-game context is replaced with one canonical pregame state before
Direct scoring; the resulting nine-card batting orders remain fixed throughout simulation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
import pandas as pd

from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix
from server.sports_phase5.whole_game_monte_carlo import (
    PAProbabilityProvider,
    SimulatedPAStateBatch,
)

from .contracts import GOLD_FEATURES
from .models import FittedFixedModel
from .walk_forward_ensemble import (
    DIRECT_GOLD,
    RECENT_RESIDUAL_FORM,
    RELIABILITY_FIELDS,
    ROLLING_365_DAY_STATE,
    STACKER_LOG_EPSILON,
    WALK_FORWARD_COMPONENT_ORDER,
    WALK_FORWARD_EMPIRICAL_COMPONENTS,
    FittedWalkForwardStacker,
)


SCHEMA_VERSION = "MLB_GOLD_PREGAME_PROBABILITY_ADAPTER_V1"
E10 = "E10"
TEMPLATE_ROWS = 18
LINEUP_SIZE = 9

TEMPLATE_ID_COLUMNS: tuple[str, ...] = (
    "plate_appearance_id",
    "game_id",
    "batting_side",
    "batting_order_slot",
    "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId",
)
TEMPLATE_COLUMNS: tuple[str, ...] = (*TEMPLATE_ID_COLUMNS, *GOLD_FEATURES)
CANONICAL_CONTEXT: Mapping[str, int] = {
    "context_inning": 1,
    "context_outs_before": 0,
    "context_base_mask_before": 0,
    "context_batting_score_diff_before": 0,
}
_SIDE_ORDER: tuple[str, ...] = ("AWAY",) * LINEUP_SIZE + ("HOME",) * LINEUP_SIZE
_SLOT_ORDER = np.tile(np.arange(1, LINEUP_SIZE + 1, dtype=np.int64), 2)


class GameProbabilityAdapterError(ValueError):
    """Raised when a pregame template or aligned prediction authority differs."""


def _exact_strings(values: Any, *, label: str, rows: int) -> tuple[str, ...]:
    raw = np.asarray(values, dtype=object)
    if raw.ndim != 1 or raw.size != rows:
        raise GameProbabilityAdapterError(f"{label} must contain exactly {rows} ordered rows")
    result: list[str] = []
    for value in raw.tolist():
        if (
            not isinstance(value, str)
            or not value
            or value.strip() != value
        ):
            raise GameProbabilityAdapterError(
                f"{label} must contain non-empty whitespace-normalized strings"
            )
        result.append(value)
    return tuple(result)


def _frozen_matrix(values: Any) -> np.ndarray:
    """Return an immutable-buffer float64 matrix."""

    contiguous = np.ascontiguousarray(values, dtype=np.float64)
    return np.frombuffer(contiguous.tobytes(), dtype=np.float64).reshape(contiguous.shape)


def _frozen_vector(values: Any) -> np.ndarray:
    contiguous = np.ascontiguousarray(values, dtype=np.float64)
    return np.frombuffer(contiguous.tobytes(), dtype=np.float64)


def _validate_template(
    template_rows: pd.DataFrame, stored_row_ids: Any
) -> tuple[pd.DataFrame, tuple[str, ...], str, tuple[str, ...], tuple[str, ...], str, str]:
    if not isinstance(template_rows, pd.DataFrame):
        raise TypeError("template_rows must be a pandas DataFrame")
    if tuple(template_rows.columns) != TEMPLATE_COLUMNS:
        raise GameProbabilityAdapterError(
            "template columns must be exactly the six pregame identities followed by "
            "the governed 48 Gold features; target/outcome/actual-participant columns "
            "are prohibited"
        )
    if len(template_rows) != TEMPLATE_ROWS:
        raise GameProbabilityAdapterError("template must contain exactly 18 ordered rows")

    row_ids = _exact_strings(
        template_rows["plate_appearance_id"].to_numpy(copy=False),
        label="template row IDs",
        rows=TEMPLATE_ROWS,
    )
    authority_row_ids = _exact_strings(
        stored_row_ids, label="stored prediction row IDs", rows=TEMPLATE_ROWS
    )
    if row_ids != authority_row_ids or len(set(row_ids)) != TEMPLATE_ROWS:
        raise GameProbabilityAdapterError(
            "template row IDs must uniquely equal stored prediction row IDs in exact order"
        )

    game_ids = _exact_strings(
        template_rows["game_id"].to_numpy(copy=False),
        label="game IDs",
        rows=TEMPLATE_ROWS,
    )
    if len(set(game_ids)) != 1:
        raise GameProbabilityAdapterError("all starting-matchup rows must identify one game")

    sides = _exact_strings(
        template_rows["batting_side"].to_numpy(copy=False),
        label="batting sides",
        rows=TEMPLATE_ROWS,
    )
    if sides != _SIDE_ORDER:
        raise GameProbabilityAdapterError(
            "template order must be AWAY slots 1-9 followed by HOME slots 1-9"
        )

    slots = template_rows["batting_order_slot"]
    if (
        pd.api.types.is_bool_dtype(slots.dtype)
        or not pd.api.types.is_numeric_dtype(slots.dtype)
    ):
        raise GameProbabilityAdapterError("batting_order_slot must be numeric")
    slot_values = slots.to_numpy(dtype=np.float64, copy=False)
    if not np.isfinite(slot_values).all() or not np.array_equal(
        slot_values, _SLOT_ORDER.astype(np.float64)
    ):
        raise GameProbabilityAdapterError(
            "batting_order_slot must be exactly 1-9 for AWAY then 1-9 for HOME"
        )

    batter_ids = _exact_strings(
        template_rows["batterCanonicalPlayerId"].to_numpy(copy=False),
        label="batter IDs",
        rows=TEMPLATE_ROWS,
    )
    if len(set(batter_ids[:LINEUP_SIZE])) != LINEUP_SIZE or len(
        set(batter_ids[LINEUP_SIZE:])
    ) != LINEUP_SIZE:
        raise GameProbabilityAdapterError(
            "each starting lineup must contain nine unique batter IDs"
        )

    pitcher_ids = _exact_strings(
        template_rows["pitcherCanonicalPlayerId"].to_numpy(copy=False),
        label="announced starter IDs",
        rows=TEMPLATE_ROWS,
    )
    home_starters = set(pitcher_ids[:LINEUP_SIZE])
    away_starters = set(pitcher_ids[LINEUP_SIZE:])
    if len(home_starters) != 1 or len(away_starters) != 1:
        raise GameProbabilityAdapterError(
            "each batting side must face one announced starter across all nine rows"
        )

    return (
        template_rows.copy(deep=True),
        row_ids,
        game_ids[0],
        batter_ids[:LINEUP_SIZE],
        batter_ids[LINEUP_SIZE:],
        next(iter(away_starters)),
        next(iter(home_starters)),
    )


def _validated_components(probabilities: Mapping[str, Any]) -> dict[str, np.ndarray]:
    if not isinstance(probabilities, Mapping) or tuple(probabilities) != (
        WALK_FORWARD_COMPONENT_ORDER
    ):
        raise GameProbabilityAdapterError(
            "stored components must preserve the exact Phase 7B5 component order"
        )
    result: dict[str, np.ndarray] = {}
    for component in WALK_FORWARD_COMPONENT_ORDER:
        try:
            matrix = validate_probability_matrix(
                probabilities[component], class_order=PA_CLASS_ORDER
            )
        except (TypeError, ValueError) as exc:
            raise GameProbabilityAdapterError(
                f"stored component probabilities are invalid for {component}"
            ) from exc
        if matrix.shape != (TEMPLATE_ROWS, len(PA_CLASS_ORDER)):
            raise GameProbabilityAdapterError(
                f"stored component {component} must contain exactly 18 aligned rows"
            )
        result[component] = _frozen_matrix(matrix)
    return result


def _copy_reliability(
    reliability_inputs: pd.DataFrame | Mapping[str, Any],
) -> dict[str, dict[str, np.ndarray]]:
    flat_order = tuple(
        f"{component}__{field}"
        for component in WALK_FORWARD_EMPIRICAL_COMPONENTS
        for field in RELIABILITY_FIELDS
    )
    if isinstance(reliability_inputs, pd.DataFrame):
        if len(reliability_inputs) != TEMPLATE_ROWS or tuple(
            reliability_inputs.columns
        ) != flat_order:
            raise GameProbabilityAdapterError(
                "stored reliability DataFrame differs from the exact aligned contract"
            )
        source: Mapping[str, Any] = {
            component: {
                field: reliability_inputs[f"{component}__{field}"].to_numpy(
                    copy=False
                )
                for field in RELIABILITY_FIELDS
            }
            for component in WALK_FORWARD_EMPIRICAL_COMPONENTS
        }
    elif isinstance(reliability_inputs, Mapping) and tuple(
        reliability_inputs
    ) == WALK_FORWARD_EMPIRICAL_COMPONENTS:
        source = reliability_inputs
    elif isinstance(reliability_inputs, Mapping) and tuple(
        reliability_inputs
    ) == flat_order:
        source = {
            component: {
                field: reliability_inputs[f"{component}__{field}"]
                for field in RELIABILITY_FIELDS
            }
            for component in WALK_FORWARD_EMPIRICAL_COMPONENTS
        }
    else:
        raise GameProbabilityAdapterError(
            "stored reliability inputs differ from the exact Phase 7B5 order"
        )

    copied: dict[str, dict[str, np.ndarray]] = {}
    for component in WALK_FORWARD_EMPIRICAL_COMPONENTS:
        fields = source[component]
        if not isinstance(fields, Mapping) or tuple(fields) != RELIABILITY_FIELDS:
            raise GameProbabilityAdapterError(
                f"stored reliability fields differ for {component}"
            )
        copied[component] = {}
        for field in RELIABILITY_FIELDS:
            raw = np.asarray(fields[field])
            if raw.dtype.kind not in "fiub" or raw.shape != (TEMPLATE_ROWS,):
                raise GameProbabilityAdapterError(
                    f"stored reliability field is not an aligned numeric vector: "
                    f"{component}__{field}"
                )
            values = np.asarray(raw, dtype=np.float64)
            if np.isinf(values).any() or (
                field != "daysSincePriorAppearance" and np.isnan(values).any()
            ):
                raise GameProbabilityAdapterError(
                    f"stored reliability field contains invalid values: "
                    f"{component}__{field}"
                )
            copied[component][field] = values.copy()
    return copied


def _rebase_residual(
    canonical_direct: np.ndarray,
    stored_direct: np.ndarray,
    stored_residual: np.ndarray,
) -> np.ndarray:
    log_correction = np.log(
        np.clip(stored_residual, STACKER_LOG_EPSILON, 1.0)
    ) - np.log(np.clip(stored_direct, STACKER_LOG_EPSILON, 1.0))
    logits = np.log(
        np.clip(canonical_direct, STACKER_LOG_EPSILON, 1.0)
    ) + log_correction
    logits -= logits.max(axis=1, keepdims=True)
    rebased = np.exp(logits)
    rebased /= rebased.sum(axis=1, keepdims=True)
    return validate_probability_matrix(rebased, class_order=PA_CLASS_ORDER)


@dataclass(frozen=True)
class StartingLineupProbabilityProvider(PAProbabilityProvider):
    """Static candidate cards cycling the announced starting lineups forever."""

    candidate_id: str
    away_cards: np.ndarray
    home_cards: np.ndarray
    away_batter_ids: tuple[str, ...]
    home_batter_ids: tuple[str, ...]
    away_announced_starter_id: str
    home_announced_starter_id: str

    def __call__(self, state: SimulatedPAStateBatch, /) -> np.ndarray:
        if not isinstance(state, SimulatedPAStateBatch):
            raise GameProbabilityAdapterError(
                "provider state must be SimulatedPAStateBatch"
            )
        arrays = (
            state.inning,
            state.is_top,
            state.outs_before,
            state.base_mask_before,
            state.away_score_before,
            state.home_score_before,
            state.batting_score_diff_before,
            state.batting_team_pa_ordinal,
            state.active,
        )
        if not arrays or arrays[0].ndim != 1 or any(
            values.shape != arrays[0].shape for values in arrays
        ):
            raise GameProbabilityAdapterError(
                "simulated provider state arrays must be one-dimensional and aligned"
            )
        if state.is_top.dtype != np.bool_ or state.active.dtype != np.bool_:
            raise GameProbabilityAdapterError(
                "simulated side and active state must be boolean"
            )
        ordinals = np.asarray(state.batting_team_pa_ordinal)
        if ordinals.dtype.kind not in "iu" or np.any(ordinals < 0):
            raise GameProbabilityAdapterError(
                "batting-team PA ordinals must be nonnegative integers"
            )
        slots = ordinals.astype(np.int64, copy=False) % LINEUP_SIZE
        probabilities = np.where(
            state.is_top[:, None], self.away_cards[slots], self.home_cards[slots]
        )
        validated = validate_probability_matrix(
            probabilities, class_order=PA_CLASS_ORDER
        )
        validated.setflags(write=False)
        return validated

    def record(self) -> dict[str, Any]:
        return {
            "candidateId": self.candidate_id,
            "battingOrderPolicy": "STARTING_LINEUP_CYCLED",
            "pitcherPolicy": "ANNOUNCED_STARTER_HELD_CONSTANT",
            "awayAnnouncedStarterId": self.away_announced_starter_id,
            "homeAnnouncedStarterId": self.home_announced_starter_id,
            "substitutionsUsed": False,
            "actualRelieversUsed": False,
        }


@dataclass(frozen=True)
class PregameProbabilityAdapter:
    """Frozen Direct/E10 starting-order cards and their pregame-only evidence."""

    game_id: str
    row_ids: tuple[str, ...]
    away_batter_ids: tuple[str, ...]
    home_batter_ids: tuple[str, ...]
    away_announced_starter_id: str
    home_announced_starter_id: str
    away_direct: np.ndarray
    home_direct: np.ndarray
    away_e10: np.ndarray
    home_e10: np.ndarray

    @property
    def class_order(self) -> tuple[str, ...]:
        return tuple(PA_CLASS_ORDER)

    def provider(self, candidate: str) -> StartingLineupProbabilityProvider:
        if candidate == DIRECT_GOLD:
            away, home = self.away_direct, self.home_direct
        elif candidate == E10:
            away, home = self.away_e10, self.home_e10
        else:
            raise GameProbabilityAdapterError(
                f"candidate must be {DIRECT_GOLD!r} or {E10!r}"
            )
        return StartingLineupProbabilityProvider(
            candidate_id=candidate,
            away_cards=away,
            home_cards=home,
            away_batter_ids=self.away_batter_ids,
            home_batter_ids=self.home_batter_ids,
            away_announced_starter_id=self.away_announced_starter_id,
            home_announced_starter_id=self.home_announced_starter_id,
        )

    def record(self) -> dict[str, Any]:
        return {
            "schemaVersion": SCHEMA_VERSION,
            "gameId": self.game_id,
            "templateRowCount": TEMPLATE_ROWS,
            "rowIds": list(self.row_ids),
            "classOrder": list(PA_CLASS_ORDER),
            "cardShapePerSide": [LINEUP_SIZE, len(PA_CLASS_ORDER)],
            "canonicalPregameContext": {
                **dict(CANONICAL_CONTEXT),
                "awayContextTopBottom": 0,
                "homeContextTopBottom": 1,
            },
            "battingOrderPolicy": "STARTING_LINEUP_CYCLED",
            "pitcherPolicy": "ANNOUNCED_STARTER_HELD_CONSTANT",
            "substitutionsUsed": False,
            "actualRelieversUsed": False,
            "targetOutcomeColumnsAccepted": False,
            "targetContextValuesRead": False,
            "residualRebase": (
                "STORED_LOG_RESIDUAL_OVER_DIRECT_CORRECTION_APPLIED_TO_"
                "CANONICAL_PREGAME_DIRECT"
            ),
            "researchLimitation": (
                "STATIC_CANONICAL_PREGAME_CARDS_CYCLE_STARTERS_ONLY_AND_DO_NOT_"
                "MODEL_SUBSTITUTIONS_RELIEVERS_FATIGUE_OR_TIMES_THROUGH_ORDER"
            ),
        }


def build_pregame_probability_adapter(
    template_rows: pd.DataFrame,
    *,
    stored_row_ids: Any,
    stored_components: Mapping[str, Any],
    stored_reliability: pd.DataFrame | Mapping[str, Any],
    direct_model: FittedFixedModel,
    e10_stacker: FittedWalkForwardStacker,
) -> PregameProbabilityAdapter:
    """Build frozen Direct/E10 cards from exact aligned pregame template evidence."""

    if not isinstance(direct_model, FittedFixedModel):
        raise TypeError("direct_model must be FittedFixedModel")
    if direct_model.feature_names != tuple(GOLD_FEATURES) or direct_model.preprocessor is None:
        raise GameProbabilityAdapterError(
            "Direct model must carry the exact fitted 48-feature Gold contract"
        )
    if not isinstance(e10_stacker, FittedWalkForwardStacker):
        raise TypeError("e10_stacker must be FittedWalkForwardStacker")

    (
        canonical,
        row_ids,
        game_id,
        away_batters,
        home_batters,
        away_starter,
        home_starter,
    ) = _validate_template(template_rows, stored_row_ids)
    components = _validated_components(stored_components)
    reliability = _copy_reliability(stored_reliability)

    # The source values of all five current-game context fields are deliberately never
    # inspected.  Canonical replacement happens before the fitted Direct model is invoked.
    for column, value in CANONICAL_CONTEXT.items():
        canonical[column] = value
    canonical["context_top_bottom"] = np.concatenate(
        (
            np.zeros(LINEUP_SIZE, dtype=np.int64),
            np.ones(LINEUP_SIZE, dtype=np.int64),
        )
    )
    try:
        canonical_direct = validate_probability_matrix(
            direct_model.predict_proba(canonical), class_order=PA_CLASS_ORDER
        )
    except (TypeError, ValueError) as exc:
        raise GameProbabilityAdapterError(
            "canonical pregame Direct scoring failed"
        ) from exc
    if canonical_direct.shape != (TEMPLATE_ROWS, len(PA_CLASS_ORDER)):
        raise GameProbabilityAdapterError(
            "canonical pregame Direct scoring must return exactly 18 rows"
        )

    rebased_residual = _rebase_residual(
        canonical_direct,
        components[DIRECT_GOLD],
        components[RECENT_RESIDUAL_FORM],
    )
    canonical_components = dict(components)
    canonical_components[DIRECT_GOLD] = _frozen_matrix(canonical_direct)
    canonical_components[RECENT_RESIDUAL_FORM] = _frozen_matrix(rebased_residual)

    residual_reliability = reliability[RECENT_RESIDUAL_FORM]
    residual_reliability["entropy"] = -np.sum(
        rebased_residual
        * np.log(np.clip(rebased_residual, STACKER_LOG_EPSILON, 1.0)),
        axis=1,
    )
    residual_reliability["deviationFromLongTerm"] = 0.5 * np.sum(
        np.abs(rebased_residual - canonical_components[ROLLING_365_DAY_STATE]),
        axis=1,
    )
    frozen_reliability: dict[str, dict[str, np.ndarray]] = {
        component: {
            field: _frozen_vector(values)
            for field, values in fields.items()
        }
        for component, fields in reliability.items()
    }

    try:
        e10_probabilities = validate_probability_matrix(
            e10_stacker.predict_proba(canonical_components, frozen_reliability),
            class_order=PA_CLASS_ORDER,
        )
    except (TypeError, ValueError, RuntimeError) as exc:
        raise GameProbabilityAdapterError("canonical pregame E10 scoring failed") from exc
    if e10_probabilities.shape != (TEMPLATE_ROWS, len(PA_CLASS_ORDER)):
        raise GameProbabilityAdapterError(
            "canonical pregame E10 scoring must return exactly 18 rows"
        )

    return PregameProbabilityAdapter(
        game_id=game_id,
        row_ids=row_ids,
        away_batter_ids=away_batters,
        home_batter_ids=home_batters,
        away_announced_starter_id=away_starter,
        home_announced_starter_id=home_starter,
        away_direct=_frozen_matrix(canonical_direct[:LINEUP_SIZE]),
        home_direct=_frozen_matrix(canonical_direct[LINEUP_SIZE:]),
        away_e10=_frozen_matrix(e10_probabilities[:LINEUP_SIZE]),
        home_e10=_frozen_matrix(e10_probabilities[LINEUP_SIZE:]),
    )


__all__ = [
    "CANONICAL_CONTEXT",
    "E10",
    "GameProbabilityAdapterError",
    "LINEUP_SIZE",
    "PregameProbabilityAdapter",
    "SCHEMA_VERSION",
    "StartingLineupProbabilityProvider",
    "TEMPLATE_COLUMNS",
    "TEMPLATE_ID_COLUMNS",
    "TEMPLATE_ROWS",
    "build_pregame_probability_adapter",
]
