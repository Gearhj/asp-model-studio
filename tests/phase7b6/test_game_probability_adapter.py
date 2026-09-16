"""Synthetic tests for the pure Phase 7B6 pregame probability-card adapter."""

from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from server.sports_gold.contracts import GOLD_FEATURES
from server.sports_gold.game_probability_adapter import (
    E10,
    TEMPLATE_COLUMNS,
    GameProbabilityAdapterError,
    build_pregame_probability_adapter,
)
from server.sports_gold.models import FittedFixedModel
from server.sports_gold.walk_forward_ensemble import (
    DIRECT_GOLD,
    RECENT_RESIDUAL_FORM,
    RELIABILITY_FIELDS,
    ROLLING_365_DAY_STATE,
    STACKER_LOG_EPSILON,
    WALK_FORWARD_COMPONENT_ORDER,
    WALK_FORWARD_EMPIRICAL_COMPONENTS,
    FittedWalkForwardStacker,
    build_walk_forward_stacker_features,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5.whole_game_monte_carlo import SimulatedPAStateBatch


ROWS = 18
CLASSES = len(PA_CLASS_ORDER)


class _CapturingPreprocessor:
    def __init__(self) -> None:
        self.last_values: dict[str, np.ndarray] | None = None

    def transform(self, feature_values, row_mask):
        self.last_values = {
            name: np.asarray(values).copy() for name, values in feature_values.items()
        }
        return np.column_stack(
            (
                feature_values["context_top_bottom"],
                feature_values["batter_prior_pa_count"],
            )
        ).astype(np.float64)


class _DirectEstimator:
    classes_ = np.arange(CLASSES, dtype=np.int64)

    def predict_proba(self, matrix):
        logits = np.tile(np.linspace(-0.5, 0.5, CLASSES), (len(matrix), 1))
        logits[:, 0] += matrix[:, 0] * 0.15
        logits[:, 1] += matrix[:, 1] * 0.001
        logits -= logits.max(axis=1, keepdims=True)
        values = np.exp(logits)
        return values / values.sum(axis=1, keepdims=True)


class _CapturingScaler:
    def __init__(self) -> None:
        self.last_features: np.ndarray | None = None

    def transform(self, features):
        self.last_features = np.asarray(features).copy()
        return features


class _E10Estimator:
    classes_ = np.arange(CLASSES, dtype=np.int64)

    def predict_proba(self, features):
        logits = np.array(features[:, :CLASSES], dtype=np.float64, copy=True)
        logits -= logits.max(axis=1, keepdims=True)
        values = np.exp(logits)
        return values / values.sum(axis=1, keepdims=True)


def _probabilities(offset: float) -> np.ndarray:
    raw = np.arange(1, CLASSES + 1, dtype=np.float64)[None, :] + offset
    row_offsets = np.arange(ROWS, dtype=np.float64)[:, None] * 0.01
    values = raw + row_offsets
    return values / values.sum(axis=1, keepdims=True)


def _components() -> dict[str, np.ndarray]:
    return {
        component: _probabilities(float(index + 1))
        for index, component in enumerate(WALK_FORWARD_COMPONENT_ORDER)
    }


def _reliability() -> dict[str, dict[str, np.ndarray]]:
    result: dict[str, dict[str, np.ndarray]] = {}
    for index, component in enumerate(WALK_FORWARD_EMPIRICAL_COMPONENTS):
        result[component] = {
            "observationCount": np.full(ROWS, 100.0 + index),
            "effectiveSampleSize": np.full(ROWS, 80.0 + index),
            "missingHistoryFlag": np.zeros(ROWS),
            "daysSincePriorAppearance": np.full(ROWS, 2.0 + index),
            "entropy": np.full(ROWS, 0.25 + index * 0.01),
            "deviationFromLongTerm": np.full(ROWS, 0.05 + index * 0.01),
        }
    return result


def _template(*, context_marker: object = 999) -> pd.DataFrame:
    data: dict[str, object] = {
        "plate_appearance_id": [f"pa-{index}" for index in range(ROWS)],
        "game_id": ["game-1"] * ROWS,
        "batting_side": ["AWAY"] * 9 + ["HOME"] * 9,
        "batting_order_slot": list(range(1, 10)) * 2,
        "batterCanonicalPlayerId": [f"batter-{index}" for index in range(ROWS)],
        "pitcherCanonicalPlayerId": ["home-starter"] * 9
        + ["away-starter"] * 9,
    }
    for index, feature in enumerate(GOLD_FEATURES):
        data[feature] = np.full(ROWS, float(index + 1))
    for feature in (
        "context_inning",
        "context_top_bottom",
        "context_outs_before",
        "context_base_mask_before",
        "context_batting_score_diff_before",
    ):
        data[feature] = [context_marker] * ROWS
    return pd.DataFrame(data, columns=TEMPLATE_COLUMNS)


def _artifacts(components, reliability):
    preprocessor = _CapturingPreprocessor()
    direct = FittedFixedModel(
        model_id="fold-direct48",
        estimator=_DirectEstimator(),
        preprocessor=preprocessor,
        feature_names=tuple(GOLD_FEATURES),
        effective_config={"frozen": True},
    )
    _, names = build_walk_forward_stacker_features(components, reliability)
    scaler = _CapturingScaler()
    e10 = FittedWalkForwardStacker(
        scaler=scaler,
        estimator=_E10Estimator(),
        feature_names=names,
    )
    return direct, e10, preprocessor, scaler


def _build(*, frame=None, row_ids=None, components=None, reliability=None):
    frame = _template() if frame is None else frame
    components = _components() if components is None else components
    reliability = _reliability() if reliability is None else reliability
    # Keep fitted-artifact construction independent of the deliberately malformed adapter
    # inputs used by fail-closed tests.
    direct, e10, preprocessor, scaler = _artifacts(_components(), _reliability())
    adapter = build_pregame_probability_adapter(
        frame,
        stored_row_ids=(
            frame["plate_appearance_id"].tolist() if row_ids is None else row_ids
        ),
        stored_components=components,
        stored_reliability=reliability,
        direct_model=direct,
        e10_stacker=e10,
    )
    return adapter, preprocessor, scaler, components, reliability


def _state(is_top, ordinals):
    top = np.asarray(is_top, dtype=bool)
    ordinal = np.asarray(ordinals, dtype=np.int64)
    rows = len(top)
    zeros = np.zeros(rows, dtype=np.int64)
    return SimulatedPAStateBatch(
        inning=np.full(rows, 7, dtype=np.int64),
        is_top=top,
        outs_before=np.full(rows, 2, dtype=np.int64),
        base_mask_before=np.full(rows, 7, dtype=np.int64),
        away_score_before=np.full(rows, 5, dtype=np.int64),
        home_score_before=np.full(rows, 4, dtype=np.int64),
        batting_score_diff_before=np.full(rows, 1, dtype=np.int64),
        batting_team_pa_ordinal=ordinal,
        active=np.ones(rows, dtype=bool),
    )


def test_builds_frozen_cards_from_canonical_context_only():
    adapter, preprocessor, _, _, _ = _build(frame=_template(context_marker="unused"))

    assert adapter.away_direct.shape == (9, 8)
    assert adapter.home_direct.shape == (9, 8)
    assert adapter.away_e10.shape == (9, 8)
    assert adapter.home_e10.shape == (9, 8)
    for cards in (
        adapter.away_direct,
        adapter.home_direct,
        adapter.away_e10,
        adapter.home_e10,
    ):
        assert not cards.flags.writeable
        assert np.allclose(cards.sum(axis=1), 1.0)
        with pytest.raises(ValueError):
            cards[0, 0] = 0.0

    seen = preprocessor.last_values
    assert seen is not None
    assert np.array_equal(seen["context_inning"], np.ones(ROWS))
    assert np.array_equal(
        seen["context_top_bottom"], np.array([0] * 9 + [1] * 9)
    )
    assert np.array_equal(seen["context_outs_before"], np.zeros(ROWS))
    assert np.array_equal(seen["context_base_mask_before"], np.zeros(ROWS))
    assert np.array_equal(
        seen["context_batting_score_diff_before"], np.zeros(ROWS)
    )


def test_source_context_changes_cannot_change_cards_and_targets_are_rejected():
    first, *_ = _build(frame=_template(context_marker="not-read-a"))
    second, *_ = _build(frame=_template(context_marker={"not": "read-b"}))

    assert np.array_equal(first.away_direct, second.away_direct)
    assert np.array_equal(first.home_e10, second.home_e10)

    for prohibited in ("outcome", "label", "actualRelieverId", "substitutionEvent"):
        frame = _template()
        frame[prohibited] = "forbidden"
        with pytest.raises(GameProbabilityAdapterError, match="prohibited"):
            _build(frame=frame)


def test_residual_is_log_ratio_rebased_and_reliability_is_recomputed():
    adapter, _, scaler, components, reliability = _build()
    assert adapter.away_e10.shape == (9, 8)
    features = scaler.last_features
    assert features is not None

    canonical_direct = np.vstack((adapter.away_direct, adapter.home_direct))
    stored_direct = components[DIRECT_GOLD]
    stored_residual = components[RECENT_RESIDUAL_FORM]
    correction = np.log(np.clip(stored_residual, STACKER_LOG_EPSILON, 1.0)) - np.log(
        np.clip(stored_direct, STACKER_LOG_EPSILON, 1.0)
    )
    logits = np.log(np.clip(canonical_direct, STACKER_LOG_EPSILON, 1.0)) + correction
    logits -= logits.max(axis=1, keepdims=True)
    expected_residual = np.exp(logits)
    expected_residual /= expected_residual.sum(axis=1, keepdims=True)
    expected_entropy = -np.sum(
        expected_residual
        * np.log(np.clip(expected_residual, STACKER_LOG_EPSILON, 1.0)),
        axis=1,
    )
    expected_deviation = 0.5 * np.sum(
        np.abs(expected_residual - components[ROLLING_365_DAY_STATE]), axis=1
    )

    _, feature_names = build_walk_forward_stacker_features(components, reliability)
    for class_index, class_name in enumerate(PA_CLASS_ORDER):
        column = feature_names.index(
            f"{RECENT_RESIDUAL_FORM}__log_probability__{class_name}"
        )
        assert np.allclose(
            features[:, column],
            np.log(np.clip(expected_residual[:, class_index], STACKER_LOG_EPSILON, 1.0)),
        )
    entropy_column = feature_names.index(f"{RECENT_RESIDUAL_FORM}__entropy")
    deviation_column = feature_names.index(
        f"{RECENT_RESIDUAL_FORM}__deviation_from_long_term"
    )
    observation_column = feature_names.index(
        f"{RECENT_RESIDUAL_FORM}__observation_count"
    )
    assert np.allclose(features[:, entropy_column], expected_entropy)
    assert np.allclose(features[:, deviation_column], expected_deviation)
    assert np.array_equal(
        features[:, observation_column],
        reliability[RECENT_RESIDUAL_FORM]["observationCount"],
    )


def test_provider_cycles_starting_order_and_holds_announced_starter():
    adapter, *_ = _build()
    direct = adapter.provider(DIRECT_GOLD)
    e10 = adapter.provider(E10)
    state = _state(
        [True, True, True, False, False, False],
        [0, 8, 9, 0, 9, 17],
    )

    assert np.array_equal(
        direct(state),
        np.vstack(
            (
                adapter.away_direct[0],
                adapter.away_direct[8],
                adapter.away_direct[0],
                adapter.home_direct[0],
                adapter.home_direct[0],
                adapter.home_direct[8],
            )
        ),
    )
    assert np.array_equal(e10(state)[0], adapter.away_e10[0])
    record = e10.record()
    assert record["battingOrderPolicy"] == "STARTING_LINEUP_CYCLED"
    assert record["pitcherPolicy"] == "ANNOUNCED_STARTER_HELD_CONSTANT"
    assert record["awayAnnouncedStarterId"] == "away-starter"
    assert record["homeAnnouncedStarterId"] == "home-starter"
    assert record["substitutionsUsed"] is False
    assert record["actualRelieversUsed"] is False


@pytest.mark.parametrize("failure", ["side", "slot", "row_id", "starter"])
def test_template_order_and_id_faults_fail_closed(failure):
    frame = _template()
    row_ids = frame["plate_appearance_id"].tolist()
    if failure == "side":
        frame.loc[0, "batting_side"] = "HOME"
    elif failure == "slot":
        frame.loc[0, "batting_order_slot"] = 2
    elif failure == "row_id":
        row_ids[0] = "different"
    else:
        frame.loc[1, "pitcherCanonicalPlayerId"] = "actual-reliever"

    with pytest.raises(GameProbabilityAdapterError):
        _build(frame=frame, row_ids=row_ids)


@pytest.mark.parametrize("failure", ["order", "shape", "probability", "reliability"])
def test_stored_prediction_contract_faults_fail_closed(failure):
    components = _components()
    reliability = _reliability()
    if failure == "order":
        components = dict(reversed(tuple(components.items())))
    elif failure == "shape":
        components[DIRECT_GOLD] = components[DIRECT_GOLD][:-1]
    elif failure == "probability":
        components[DIRECT_GOLD] = components[DIRECT_GOLD].copy()
        components[DIRECT_GOLD][0, 0] = -1.0
    else:
        reliability = deepcopy(reliability)
        reliability[RECENT_RESIDUAL_FORM]["entropy"] = np.zeros(17)

    with pytest.raises(GameProbabilityAdapterError):
        _build(components=components, reliability=reliability)


def test_adapter_evidence_records_pregame_policy_and_limitation():
    adapter, *_ = _build()
    record = adapter.record()
    assert record["battingOrderPolicy"] == "STARTING_LINEUP_CYCLED"
    assert record["pitcherPolicy"] == "ANNOUNCED_STARTER_HELD_CONSTANT"
    assert record["targetOutcomeColumnsAccepted"] is False
    assert record["targetContextValuesRead"] is False
    assert "DO_NOT_MODEL_SUBSTITUTIONS_RELIEVERS" in record["researchLimitation"]


def test_provider_rejects_invalid_candidate_and_negative_ordinal():
    adapter, *_ = _build()
    with pytest.raises(GameProbabilityAdapterError, match="candidate"):
        adapter.provider("OTHER")
    provider = adapter.provider(DIRECT_GOLD)
    with pytest.raises(GameProbabilityAdapterError, match="nonnegative"):
        provider(_state([True], [-1]))
