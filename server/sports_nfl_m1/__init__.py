"""Provider-free, research-only NFL M1 modeling primitives."""

from .baselines import EloTeamStrengthBaseline, LeagueHomePrior, RollingScoringMarginBaseline
from .contracts import (
    EXTRA_TREES_SCORE_GRID,
    HGB_SCORE_GRID,
    M1_SCHEMA_VERSION,
    NflM1IntegrityError,
    RANDOM_SEED,
    RIDGE_SCORE_GRID,
    SCORE_MODEL_GRID,
    WIN_LOGISTIC_C_GRID,
    XGBOOST_SCORE_CONFIG,
    ScoreModelConfig,
    assert_no_market_predictors,
    assert_valid_model_predictors,
    require_research_only,
    research_only_metadata,
)
from .models import IndependentHomeAwayScoreModel, RegularizedHomeWinModel, xgboost_capability
from .prediction import GamePredictions
from .preprocessing import DEFAULT_CATEGORICAL_FEATURES, FoldLocalPreprocessor
from .recency import RECENCY_STRATEGIES, RecencyStrategy, RecencyWeights, recency_weights


__all__ = [
    "DEFAULT_CATEGORICAL_FEATURES",
    "EXTRA_TREES_SCORE_GRID",
    "EloTeamStrengthBaseline",
    "FoldLocalPreprocessor",
    "GamePredictions",
    "HGB_SCORE_GRID",
    "IndependentHomeAwayScoreModel",
    "LeagueHomePrior",
    "M1_SCHEMA_VERSION",
    "NflM1IntegrityError",
    "RANDOM_SEED",
    "RECENCY_STRATEGIES",
    "RIDGE_SCORE_GRID",
    "RecencyStrategy",
    "RecencyWeights",
    "RegularizedHomeWinModel",
    "RollingScoringMarginBaseline",
    "SCORE_MODEL_GRID",
    "ScoreModelConfig",
    "WIN_LOGISTIC_C_GRID",
    "XGBOOST_SCORE_CONFIG",
    "assert_no_market_predictors",
    "assert_valid_model_predictors",
    "recency_weights",
    "require_research_only",
    "research_only_metadata",
    "xgboost_capability",
]
