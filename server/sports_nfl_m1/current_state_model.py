"""Bounded, fold-local NFL current-state models with coherent final-score laws.

This is reconstructed Development evidence, not an archived historical vintage.
Retentions are chosen on one inner chronological season using the dynamic model.
Every residual bank is made from that inner holdout, never in-sample fit errors.
No target-game starter/context or generic median/mode input replacement is used.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits

from server.sports_nfl.gold import ROLLING_METRICS
from .distributions import PairedResidualAuthority, make_common_random_numbers

CONTRACT = "NFL_CURRENT_STATE_SCORE_SYSTEM_V2"
EVIDENCE_CLASS = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
RETENTIONS = (0.35, 0.65, 0.85)
MODEL_IDS = ("DYNAMIC", "HIERARCHICAL", "RESIDUAL")
SEED = 739031
RESIDUAL_BOUND_POINTS = 6.0
NATIVE_WORKERS = 2
HGB_PARAMETERS = dict(max_iter=80, max_leaf_nodes=7, min_samples_leaf=80,
                      learning_rate=0.03, l2_regularization=15.0, max_bins=63,
                      early_stopping=False, random_state=SEED)
RATE_NAMES = tuple(f"{side}_{metric}_season_to_date"
                   for side in ("home", "away") for metric in ROLLING_METRICS)
EXTRA_NAMES = tuple(f"{side}_{name}" for side in ("home", "away") for name in (
    "qb_epa_mean", "qb_posterior_sd", "qb_effective_exposure", "prior_season_gap",
    "prior_games", "current_games", "missing_season_uncertainty"))
INPUT_NAMES = (*RATE_NAMES, *EXTRA_NAMES)


def _feature_api():
    from .current_state_features import build_treatment_states, fit_league_prior
    return build_treatment_states, fit_league_prior


def _emit(callback, event: str, **values):
    if callback is not None:
        callback({"event": event, "contract": CONTRACT, **values})


def _guard_source(frame: pd.DataFrame, label: str):
    if "season" not in frame:
        raise ValueError(f"MISSING_SEASON_PARTITION_IDENTITY:{label}")
    if (pd.to_numeric(frame.season, errors="raise") == 2025).any():
        raise ValueError(f"SEALED_2025_NOT_PERMITTED:{label}")


def _actual(frame: pd.DataFrame) -> np.ndarray:
    result = frame[["home_points", "away_points"]].to_numpy(float)
    if not np.isfinite(result).all() or (result < 0).any():
        raise ValueError("INVALID_COMPLETED_TRAINING_SCORE")
    return result


def _state_values(states: pd.DataFrame) -> np.ndarray:
    missing = set(INPUT_NAMES) - set(states.columns)
    if missing:
        raise ValueError(f"MISSING_TREATMENT_STATE_COLUMNS:{sorted(missing)}")
    x = states[list(INPUT_NAMES)].to_numpy(float)
    if np.isinf(x).any():
        raise ValueError("INFINITE_TREATMENT_STATE")
    return x


def _dynamic(states: pd.DataFrame, home_advantage: float) -> np.ndarray:
    home = 0.5 * (states.home_points_for_season_to_date.to_numpy(float)
                  + states.away_points_against_season_to_date.to_numpy(float))
    away = 0.5 * (states.away_points_for_season_to_date.to_numpy(float)
                  + states.home_points_against_season_to_date.to_numpy(float))
    result = np.column_stack((home + home_advantage / 2, away - home_advantage / 2))
    if not np.isfinite(result).all():
        raise ValueError("ABSTAIN_UNAVAILABLE_SCORING_STATE")
    return np.maximum(result, 0.0)


def _uncertainty(states: pd.DataFrame) -> np.ndarray:
    """Score-mean uncertainty plus explicit missing-season inflation.

    The dimensionless missing-season term supplied by the feature authority is
    converted using the observed scoring posterior SD, not invented outcomes.
    This is a predeclared conservative approximation, not calibrated coverage.
    """
    values = []
    for side, opponent in (("home", "away"), ("away", "home")):
        columns = [f"{side}_points_for_season_to_date__posterior_sd",
                   f"{opponent}_points_against_season_to_date__posterior_sd"]
        sd = states[columns].to_numpy(float)
        if not np.isfinite(sd).all() or (sd < 0).any():
            raise ValueError("ABSTAIN_UNAVAILABLE_SCORING_UNCERTAINTY")
        base = np.square(sd).sum(axis=1) / 4.0
        gap = states[[f"{side}_missing_season_uncertainty",
                      f"{opponent}_missing_season_uncertainty"]].to_numpy(float)
        if not np.isfinite(gap).all() or (gap < 0).any():
            raise ValueError("INVALID_MISSING_SEASON_UNCERTAINTY")
        x = _state_values(states)
        unknown_fraction = np.isnan(x).mean(axis=1)
        values.append(base * (1.0 + np.square(gap).mean(axis=1))
                      + unknown_fraction * np.maximum(base, 1.0))
    return np.column_stack(values)


@dataclass
class _MeanComponents:
    home_advantage: float
    centers: np.ndarray
    scales: np.ndarray
    supported_columns: np.ndarray
    ridge: Any
    residual_models: list[Any]

    def _linear(self, x):
        # A missing source contributes no *incremental standardized effect*.
        # Its raw input stays NaN, gets an explicit indicator, and inflates
        # uncertainty. This is exclusion, not a fabricated observed rate.
        finite = np.isfinite(x)
        deviation = np.zeros_like(x)
        np.subtract(x, self.centers, out=deviation, where=finite)
        deviation /= self.scales
        return np.column_stack((deviation[:, self.supported_columns],
                                (~finite)[:, self.supported_columns].astype(float)))

    def predict(self, states):
        x = _state_values(states)
        dynamic = _dynamic(states, self.home_advantage)
        hierarchical = np.maximum(dynamic + self.ridge.predict(self._linear(x)), 0.0)
        # HGB preserves native NaN; its only target is the structured residual.
        residual_x = np.column_stack((x, dynamic, hierarchical))
        with threadpool_limits(limits=NATIVE_WORKERS):
            correction = np.column_stack([model.predict(residual_x)
                                           for model in self.residual_models])
        correction = np.clip(correction, -RESIDUAL_BOUND_POINTS, RESIDUAL_BOUND_POINTS)
        return {"DYNAMIC": dynamic, "HIERARCHICAL": hierarchical,
                "RESIDUAL": np.maximum(hierarchical + correction, 0.0)}


def _fit_components(states, callback, stage):
    truth = _actual(states)
    home_advantage = float(np.mean(truth[:, 0] - truth[:, 1]))
    dynamic = _dynamic(states, home_advantage)
    x = _state_values(states)
    finite = np.isfinite(x)
    counts = finite.sum(axis=0)
    centers = np.divide(np.where(finite, x, 0).sum(axis=0), counts,
                        out=np.zeros(x.shape[1]), where=counts > 0)
    variance = np.divide(np.where(finite, x - centers, 0).__pow__(2).sum(axis=0), counts,
                         out=np.zeros(x.shape[1]), where=counts > 0)
    scales = np.sqrt(np.maximum(variance, 1e-12))
    core = _MeanComponents(home_advantage, centers, scales, counts > 0,
                           Ridge(alpha=40.0), [])
    _emit(callback, "SCALER_FIT", stage=stage, rows=len(states), scope="OBSERVED_TRAINING_VALUES_ONLY")
    _emit(callback, "ESTIMATOR_FIT_START", stage=stage, component="HIERARCHICAL", target="JOINT_HOME_AWAY")
    with threadpool_limits(limits=NATIVE_WORKERS):
        core.ridge.fit(core._linear(x), truth - dynamic)
    _emit(callback, "ESTIMATOR_FIT_COMPLETE", stage=stage, component="HIERARCHICAL", target="JOINT_HOME_AWAY")
    hierarchical = np.maximum(dynamic + core.ridge.predict(core._linear(x)), 0.0)
    residual_x = np.column_stack((x, dynamic, hierarchical))
    for target, label in enumerate(("HOME", "AWAY")):
        model = HistGradientBoostingRegressor(**HGB_PARAMETERS)
        _emit(callback, "ESTIMATOR_FIT_START", stage=stage, component="RESIDUAL", target=label)
        with threadpool_limits(limits=NATIVE_WORKERS):
            model.fit(residual_x, truth[:, target] - hierarchical[:, target])
        _emit(callback, "ESTIMATOR_FIT_COMPLETE", stage=stage, component="RESIDUAL", target=label)
        core.residual_models.append(model)
    return core


@dataclass
class CurrentStateSystem:
    lag_hours: int
    decay: float
    league_prior: dict
    core: _MeanComponents
    residual_banks: dict[str, PairedResidualAuthority]
    reference_uncertainty: np.ndarray
    metadata: dict = field(default_factory=dict)

    def predict(self, events: pd.DataFrame, team: pd.DataFrame, qb: pd.DataFrame,
                *, draws: int = 1000, seed: int = SEED) -> dict:
        for label, frame in (("events", events), ("team", team), ("qb", qb)):
            _guard_source(frame, label)
        if pd.to_datetime(events.game_date).min() <= pd.Timestamp(self.metadata["trainingEnd"]):
            raise ValueError("FORECAST_NOT_AFTER_MODEL_TRAINING_CUTOFF")
        if int(draws) < 1:
            raise ValueError("DRAW_COUNT_MUST_BE_POSITIVE")
        build, _ = _feature_api()
        states = build(events, team, qb, lag_hours=self.lag_hours,
                       decay=self.decay, league_prior=self.league_prior)
        if states.canonical_game_id.tolist() != events.canonical_game_id.tolist():
            raise ValueError("TREATMENT_EVENT_ORDER_CHANGED")
        predictions = self.core.predict(states)
        uncertainty = _uncertainty(states)
        randoms = make_common_random_numbers(n_games=len(events), draws=draws, seed=seed)
        branch_counts = self._coverage(states)
        result = {"_states": states, "_coverage": branch_counts}
        for name, means in predictions.items():
            bank = self.residual_banks[name]
            # Preserve paired residual dependence. Scale only by the ratio of
            # current uncertainty to inner-holdout uncertainty already in bank.
            residual_variance = np.var(np.column_stack((bank.home, bank.away)), axis=0)
            aleatoric = np.maximum(residual_variance - self.reference_uncertainty, 1.0)
            scale = np.sqrt((aleatoric + uncertainty) /
                            (aleatoric + self.reference_uncertainty))
            index = np.minimum((randoms.residual_uniform * bank.row_count).astype(int), bank.row_count - 1)
            home_latent = np.maximum(0, means[:, 0, None] + scale[:, 0, None] * bank.home[index])
            away_latent = np.maximum(0, means[:, 1, None] + scale[:, 1, None] * bank.away[index])
            home = (np.floor(home_latent) + (randoms.home_round_uniform < home_latent % 1)).astype(np.int32)
            away = (np.floor(away_latent) + (randoms.away_round_uniform < away_latent % 1)).astype(np.int32)
            probabilities = np.column_stack(((away > home).mean(axis=1), (away == home).mean(axis=1), (home > away).mean(axis=1)))
            result[name] = {"scoreMeans": means, "homeDraws": home, "awayDraws": away,
                            "probabilityAwayTieHome": probabilities,
                            "distributionScoreMeans": np.column_stack((home.mean(axis=1), away.mean(axis=1))),
                            "stateUncertainty": np.sqrt(uncertainty), "residualScale": scale,
                            "branchCounts": branch_counts, "features": list(INPUT_NAMES),
                            "residualAuthoritySha256": bank.sha256,
                            "evidenceClass": self.metadata["evidenceClass"],
                            "rowEvidenceClasses": states.evidence_class.tolist()}
        return result

    @staticmethod
    def _coverage(states):
        result = {"games": len(states), "semanticInputs": len(RATE_NAMES),
                  "genericMedianFallbacks": 0, "genericModeFallbacks": 0,
                  "priorOnlyCells": 0, "currentEvidenceCells": 0,
                  "sourceUnknownCells": 0, "excludedUnavailableIncrementalCells": 0}
        for name in RATE_NAMES:
            exposure = states[f"{name}__current_exposure"].to_numpy(float)
            unknown = states[f"{name}__source_unknown"].to_numpy(float)
            result["priorOnlyCells"] += int(((exposure == 0) & (unknown == 0)).sum())
            result["currentEvidenceCells"] += int((exposure > 0).sum())
            result["sourceUnknownCells"] += int((unknown > 0).sum())
        result["excludedUnavailableIncrementalCells"] = int(np.isnan(_state_values(states)).sum())
        return result

    def state(self):
        return {**self.metadata, "contract": CONTRACT, "lagHours": self.lag_hours,
                "selectedRetention": self.decay, "leaguePrior": self.league_prior,
                "inputNames": list(INPUT_NAMES), "semanticInputs": len(RATE_NAMES),
                "selectedInputCount": len(INPUT_NAMES),
                "ridgeExpandedColumns": int(self.core.supported_columns.sum()) * 2,
                "hgbExpandedColumns": len(INPUT_NAMES) + 4,
                "observedTrainingCenters": self.core.centers.tolist(),
                "observedTrainingScales": self.core.scales.tolist(),
                "excludedAllMissingTrainingColumns": [name for name, valid in zip(INPUT_NAMES, self.core.supported_columns) if not valid],
                "referenceScoreMeanVariance": self.reference_uncertainty.tolist(),
                "residualAuthorities": {name: {"sha256": bank.sha256, "rows": bank.row_count,
                    "trainingStart": bank.training_start, "trainingEnd": bank.training_end,
                    "rowIds": list(bank.row_ids)} for name, bank in self.residual_banks.items()},
                "genericMedianFallbacks": 0, "genericModeFallbacks": 0,
                "sourceUnknownRule": "OMIT_UNAVAILABLE_INCREMENTAL_LINEAR_EFFECT_WITH_INDICATOR; HGB_NATIVE_NAN; WIDEN_UNCERTAINTY",
                "uncertaintyRule": "SCORE_POSTERIOR_VARIANCE_PLUS_DIMENSIONLESS_MISSING_SEASON_INFLATION; RELATIVE_TO_INNER_BANK",
                "uncertaintyIsCalibrated": False, "actualTargetStarterKnown": False,
                "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
                "wageringAuthority": False, "executionAllowedInAISP": False}


def fit_current_state_system(train_games: pd.DataFrame, team: pd.DataFrame,
                             qb: pd.DataFrame, *, lag_hours: int = 48,
                             receipt_callback: Callable | None = None) -> CurrentStateSystem:
    """Fit one predeclared system; never invoke until the run declaration exists."""
    for label, frame in (("training", train_games), ("team", team), ("qb", qb)):
        _guard_source(frame, label)
    if lag_hours not in (48, 72):
        raise ValueError("UNREGISTERED_AVAILABILITY_LAG")
    if train_games.canonical_game_id.duplicated().any():
        raise ValueError("DUPLICATE_TRAINING_GAME")
    if int(train_games.season.max()) >= 2025:
        raise ValueError("DEVELOPMENT_TRAINING_MUST_END_BY_2024")
    inner_season = int(train_games.season.max())
    inner_train = train_games.loc[train_games.season < inner_season].copy()
    inner_valid = train_games.loc[train_games.season == inner_season].copy()
    if len(inner_train) < 10 or len(inner_valid) < 2:
        raise ValueError("INSUFFICIENT_CHRONOLOGICAL_INNER_AUTHORITY")
    build, fit_prior = _feature_api()
    _emit(receipt_callback, "PRIOR_PARAMETER_FIT_START", stage="INNER")
    inner_prior = fit_prior(inner_train, team, qb, lag_hours=lag_hours)
    _emit(receipt_callback, "PRIOR_PARAMETER_FIT_COMPLETE", stage="INNER")
    selection = []
    truth = _actual(inner_valid)
    hfa = float(np.mean(_actual(inner_train)[:, 0] - _actual(inner_train)[:, 1]))
    for decay in RETENTIONS:
        _emit(receipt_callback, "DECAY_EVALUATION_START", retention=decay, season=inner_season)
        states = build(inner_valid, team, qb, lag_hours=lag_hours, decay=decay, league_prior=inner_prior)
        error = float(np.mean(np.square(truth - _dynamic(states, hfa))))
        selection.append({"retention": decay, "innerScoreMSE": error, "season": inner_season})
        _emit(receipt_callback, "DECAY_EVALUATION_COMPLETE", **selection[-1])
    decay = min(selection, key=lambda item: (item["innerScoreMSE"], item["retention"]))["retention"]
    inner_states = build(inner_train, team, qb, lag_hours=lag_hours, decay=decay, league_prior=inner_prior)
    validation_states = build(inner_valid, team, qb, lag_hours=lag_hours, decay=decay, league_prior=inner_prior)
    inner_core = _fit_components(inner_states, receipt_callback, "INNER")
    inner_predictions = inner_core.predict(validation_states)
    banks = {}
    for name, means in inner_predictions.items():
        _emit(receipt_callback, "RESIDUAL_AUTHORITY_FIT_START", component=name, rows=len(inner_valid))
        banks[name] = PairedResidualAuthority.fit(actual_home=truth[:, 0], actual_away=truth[:, 1],
            predicted_home=means[:, 0], predicted_away=means[:, 1],
            row_ids=inner_valid.canonical_game_id.astype(str).tolist(),
            row_dates=pd.to_datetime(inner_valid.game_date).dt.strftime("%Y-%m-%d").tolist(),
            training_end=str(pd.Timestamp(inner_valid.game_date.max()).date()))
        _emit(receipt_callback, "RESIDUAL_AUTHORITY_FIT_COMPLETE", component=name, rows=len(inner_valid), sha256=banks[name].sha256)
    _emit(receipt_callback, "PRIOR_PARAMETER_FIT_START", stage="FULL_TRAINING")
    prior = fit_prior(train_games, team, qb, lag_hours=lag_hours)
    _emit(receipt_callback, "PRIOR_PARAMETER_FIT_COMPLETE", stage="FULL_TRAINING")
    full_states = build(train_games, team, qb, lag_hours=lag_hours, decay=decay, league_prior=prior)
    core = _fit_components(full_states, receipt_callback, "FULL_TRAINING")
    return CurrentStateSystem(lag_hours, decay, prior, core, banks,
        _uncertainty(validation_states).mean(axis=0), {
            "evidenceClass": EVIDENCE_CLASS, "trainingEnd": str(pd.Timestamp(train_games.game_date.max()).date()),
            "trainingRows": len(train_games), "innerTrainingRows": len(inner_train),
            "innerValidationRows": len(inner_valid), "innerValidationSeason": inner_season,
            "decaySelection": selection, "decayObjective": "INNER_CHRONOLOGICAL_DYNAMIC_FINAL_SCORE_MSE",
            "ridgeAlpha": 40.0, "hgbParameters": HGB_PARAMETERS,
            "residualBoundPoints": RESIDUAL_BOUND_POINTS, "nativeWorkers": NATIVE_WORKERS,
            "actualEstimatorFitStarts": 6, "actualEstimatorFitCompletions": 6,
            "decayEvaluations": 3, "priorParameterFits": 2, "scalerFits": 2,
            "pairedResidualAuthorityFits": 3, "calibratorFits": 0,
            "residualBankScope": "LAST_TRAINING_SEASON_CHRONOLOGICAL_INNER_HOLDOUT; NOT_IN_SAMPLE",
            "lateHistoricalCorrectionsPossible": True,
            "originalHistoricalPublicationVintageEstablished": False})
