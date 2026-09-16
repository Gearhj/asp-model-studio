"""Frozen research contracts for the NFL M1 modeling benchmark.

This package is deliberately disconnected from the product model registry.  It
may fit research candidates, but it cannot promote or deploy them.  Historical
market fields are evaluation evidence and are rejected from predictor lists.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from ..sports_nfl.gold import MARKET_FIELDS


M1_SCHEMA_VERSION = "ASP_NFL_M1_MODELING_PRIMITIVES_V1"
RANDOM_SEED = 731_001


class NflM1IntegrityError(RuntimeError):
    """Raised when a candidate would violate the frozen M1 research design."""


_MARKET_EXACT_NAMES = frozenset(
    {
        *(name.lower() for name in MARKET_FIELDS),
        "moneyline",
        "home_moneyline_probability",
        "away_moneyline_probability",
        "market_probability",
        "market_implied_probability",
        "no_vig_probability",
        "sportsbook_probability",
        "opening_line",
        "closing_line",
        "consensus_line",
    }
)
_MARKET_NAME_FRAGMENTS = (
    "moneyline",
    "sportsbook",
    "market_implied",
    "no_vig",
    "closing_price",
    "opening_price",
    "market_probability",
    "market_line",
    "american_odds",
    "decimal_odds",
)
_TARGET_EXACT_NAMES = frozenset(
    {
        "home_points",
        "away_points",
        "home_win",
        "tie_game",
        "score_differential",
        "total_points",
        "overtime",
        "game_state",
    }
)


def assert_no_market_predictors(feature_names: Iterable[str]) -> tuple[str, ...]:
    """Freeze a predictor order after rejecting market-derived inputs.

    The check intentionally targets named market evidence rather than broad
    words such as ``total`` or ``spread``; legitimate football predictors like
    historical scoring totals must remain usable.
    """

    names = tuple(str(name) for name in feature_names)
    if not names:
        raise NflM1IntegrityError("an M1 candidate must declare at least one predictor")
    if len(names) != len(set(names)):
        raise NflM1IntegrityError("M1 predictor names must be unique and ordered")
    forbidden = sorted(
        name
        for name in names
        if name.lower() in _MARKET_EXACT_NAMES
        or any(fragment in name.lower() for fragment in _MARKET_NAME_FRAGMENTS)
    )
    if forbidden:
        raise NflM1IntegrityError(
            f"sportsbook/market evidence cannot be an M1 predictor: {forbidden}"
        )
    return names


def assert_valid_model_predictors(feature_names: Iterable[str]) -> tuple[str, ...]:
    """Reject target-game truth and timing-unproven research fields too."""

    names = assert_no_market_predictors(feature_names)
    forbidden = sorted(
        name
        for name in names
        if name.lower() in _TARGET_EXACT_NAMES
        or name.lower().endswith("_timing_unproven")
        or name.lower().startswith("target_game_")
    )
    if forbidden:
        raise NflM1IntegrityError(
            f"target-game or timing-unproven fields cannot be M1 predictors: {forbidden}"
        )
    return names


@dataclass(frozen=True)
class ScoreModelConfig:
    """One declared member of the deliberately small M1 score-model grid."""

    family: str
    candidate_id: str
    parameters: Mapping[str, Any]

    def state(self) -> dict[str, Any]:
        return asdict(self)


WIN_LOGISTIC_C_GRID: tuple[float, ...] = (0.1, 1.0, 10.0)
RIDGE_SCORE_GRID: tuple[ScoreModelConfig, ...] = (
    ScoreModelConfig("RIDGE", "ridge-alpha-10", {"alpha": 10.0}),
    ScoreModelConfig("RIDGE", "ridge-alpha-100", {"alpha": 100.0}),
)
HGB_SCORE_GRID: tuple[ScoreModelConfig, ...] = (
    ScoreModelConfig(
        "HIST_GRADIENT_BOOSTING",
        "hgb-leaves-15",
        {
            "learning_rate": 0.05,
            "max_iter": 120,
            "max_leaf_nodes": 15,
            "min_samples_leaf": 20,
            "l2_regularization": 1.0,
        },
    ),
    ScoreModelConfig(
        "HIST_GRADIENT_BOOSTING",
        "hgb-leaves-31",
        {
            "learning_rate": 0.05,
            "max_iter": 120,
            "max_leaf_nodes": 31,
            "min_samples_leaf": 20,
            "l2_regularization": 1.0,
        },
    ),
)
EXTRA_TREES_SCORE_GRID: tuple[ScoreModelConfig, ...] = (
    ScoreModelConfig(
        "EXTRA_TREES",
        "extra-trees-leaf-3",
        {
            "n_estimators": 160,
            "max_features": 0.7,
            "min_samples_leaf": 3,
        },
    ),
    ScoreModelConfig(
        "EXTRA_TREES",
        "extra-trees-leaf-7",
        {
            "n_estimators": 160,
            "max_features": 0.7,
            "min_samples_leaf": 7,
        },
    ),
)
SCORE_MODEL_GRID = RIDGE_SCORE_GRID + HGB_SCORE_GRID + EXTRA_TREES_SCORE_GRID
XGBOOST_SCORE_CONFIG = ScoreModelConfig(
    "XGBOOST",
    "xgboost-fixed-research-challenger",
    {
        "n_estimators": 200,
        "max_depth": 3,
        "learning_rate": 0.03,
        "min_child_weight": 5.0,
        "subsample": 0.9,
        "colsample_bytree": 0.8,
        "reg_lambda": 5.0,
    },
)


def research_only_metadata(candidate_id: str) -> dict[str, Any]:
    """Return immutable disposition fields for an M1 fitted artifact."""

    if not candidate_id:
        raise NflM1IntegrityError("candidate_id is required")
    return {
        "schemaVersion": M1_SCHEMA_VERSION,
        "candidateId": candidate_id,
        "status": "RESEARCH_SHADOW",
        "promotionState": "NOT_PROMOTED",
        "deploymentEligible": False,
        "marketPredictorsUsed": False,
    }


def require_research_only(metadata: Mapping[str, Any]) -> None:
    """Fail closed if code attempts to relabel an M1 result as promoted."""

    expected = research_only_metadata(str(metadata.get("candidateId", "")))
    for name in ("status", "promotionState", "deploymentEligible", "marketPredictorsUsed"):
        if metadata.get(name) != expected[name]:
            raise NflM1IntegrityError(f"M1 artifact disposition is invalid: {name}")


__all__ = [
    "EXTRA_TREES_SCORE_GRID",
    "HGB_SCORE_GRID",
    "M1_SCHEMA_VERSION",
    "NflM1IntegrityError",
    "RANDOM_SEED",
    "RIDGE_SCORE_GRID",
    "SCORE_MODEL_GRID",
    "ScoreModelConfig",
    "WIN_LOGISTIC_C_GRID",
    "XGBOOST_SCORE_CONFIG",
    "assert_no_market_predictors",
    "assert_valid_model_predictors",
    "require_research_only",
    "research_only_metadata",
]
