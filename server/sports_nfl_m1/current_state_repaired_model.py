"""Isolated mean-role repair; predecessor classes and artifacts stay untouched.

Only chronological training/inner-holdout evidence may fit this module. Current
uncertainty summaries never enter either mean estimator. Finite populations
preserve the declared conditional score means under dispersion perturbations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import nnls
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits

from . import current_state_model as predecessor_module
from .distributions import PairedResidualAuthority, make_common_random_numbers
from .labs_simulation import file_record, immutable_json

CONTRACT = "NFL_CURRENT_STATE_MEAN_ROLE_REPAIR_V2_1"
REPAIR_AUTHORITY = "UNCERTAINTY_ONLY_MEAN_EXCLUSION_AND_INNER_DROPOUT_VARIANCE_V1"
EVIDENCE_CLASS = predecessor_module.EVIDENCE_CLASS
RATE_NAMES = predecessor_module.RATE_NAMES
INPUT_NAMES = predecessor_module.INPUT_NAMES  # Evidence inventory remains all58.
UNCERTAINTY_ONLY_NAMES = tuple(f"{side}_{name}" for side in ("home", "away")
    for name in ("qb_posterior_sd", "prior_season_gap", "missing_season_uncertainty"))
MEAN_INPUT_NAMES = tuple(name for name in INPUT_NAMES if name not in UNCERTAINTY_ONLY_NAMES)
VARIANCE_INPUT_NAMES = ("intercept", "score_posterior_variance", "qb_posterior_variance", "missing_age_count")
MODEL_IDS = predecessor_module.MODEL_IDS
SEED = predecessor_module.SEED
NATIVE_WORKERS = predecessor_module.NATIVE_WORKERS
HGB_PARAMETERS = dict(predecessor_module.HGB_PARAMETERS)
RESIDUAL_BOUND_POINTS = predecessor_module.RESIDUAL_BOUND_POINTS


def _feature_api():
    from .current_state_features import build_treatment_states, fit_league_prior
    return build_treatment_states, fit_league_prior


def _emit(callback, event, **values):
    if callback:
        callback({"event": event, "contract": CONTRACT, **values})


def _mean_values(states):
    missing = set(MEAN_INPUT_NAMES) - set(states.columns)
    if missing:
        raise ValueError(f"MISSING_MEAN_STATE_COLUMNS:{sorted(missing)}")
    x = states[list(MEAN_INPUT_NAMES)].to_numpy(float)
    if np.isinf(x).any():
        raise ValueError("INFINITE_MEAN_TREATMENT_STATE")
    return x


def mean_preserving_scores(raw_scores, target_means):
    """Nonnegative monotone row projection and exact-sum balanced rounding.

    Target sum is nearest-even round(draw_count * conditional mean). Projection
    is the unique Euclidean simplex projection, not a learned mean correction.
    Stable largest-fraction rounding preserves this sum deterministically.
    """
    raw = np.asarray(raw_scores, dtype=float)
    means = np.asarray(target_means, dtype=float)
    if raw.ndim != 2 or means.shape != (raw.shape[0],) or raw.shape[1] < 1:
        raise ValueError("MEAN_PRESERVING_SCORE_SHAPE_DIFFERS")
    if not np.isfinite(raw).all() or not np.isfinite(means).all() or (means < 0).any():
        raise ValueError("INVALID_MEAN_PRESERVING_SCORE_VALUES")
    scores = np.zeros(raw.shape, dtype=np.int32)
    count = raw.shape[1]
    for i, (row, mean) in enumerate(zip(raw, means)):
        target = int(np.rint(mean * count))
        if target == 0:
            continue
        descending = np.sort(row)[::-1]
        offsets = (np.cumsum(descending) - target) / np.arange(1, count + 1)
        supported = np.flatnonzero(descending > offsets)
        if not len(supported):
            raise ValueError("NO_POSITIVE_SCORE_PROJECTION_SUPPORT")
        projected = np.maximum(row - offsets[supported[-1]], 0.0)
        floor = np.floor(projected).astype(np.int64)
        remainder = target - int(floor.sum())
        if remainder < 0 or remainder > count:
            raise ValueError("BALANCED_ROUNDING_RESIDUAL_OUTSIDE_SUPPORT")
        if remainder:
            order = np.argsort(-(projected - floor), kind="stable")
            floor[order[:remainder]] += 1
        if floor.max() > np.iinfo(np.int32).max or int(floor.sum()) != target:
            raise ValueError("BALANCED_INTEGER_SCORE_SUM_DIFFERS")
        scores[i] = floor
    return scores


def uncertainty_design(states):
    """Side-symmetric nonnegative variance predictors, never mean inputs.

    Age and missing-season count denote the same missing-history mechanism;
    taking their maximum avoids fitting two collinear representations. The
    opposite team's scoring defense affects the relevant score uncertainty.
    QB posterior variances are averaged across the matchup without asserting
    known current starters. No 1+gap-squared inflation is used.
    """
    result = []
    gaps = states[[f"{side}_missing_season_uncertainty" for side in ("home", "away")]].to_numpy(float)
    ages = states[[f"{side}_prior_season_gap" for side in ("home", "away")]].to_numpy(float)
    qb_sd = states[[f"{side}_qb_posterior_sd" for side in ("home", "away")]].to_numpy(float)
    if any(not np.isfinite(x).all() or (x < 0).any() for x in (gaps, ages, qb_sd)):
        raise ValueError("ABSTAIN_UNAVAILABLE_UNCERTAINTY_STATE")
    age_gap = np.maximum(gaps, np.maximum(ages - 1., 0.)).mean(axis=1)
    for side, opponent in (("home", "away"), ("away", "home")):
        sd = states[[f"{side}_points_for_season_to_date__posterior_sd",
                     f"{opponent}_points_against_season_to_date__posterior_sd"]].to_numpy(float)
        if not np.isfinite(sd).all() or (sd < 0).any():
            raise ValueError("ABSTAIN_UNAVAILABLE_SCORING_UNCERTAINTY")
        result.append(np.column_stack((np.ones(len(states)), np.square(sd).sum(axis=1) / 4.,
                                       np.square(qb_sd).mean(axis=1), age_gap)))
    return np.stack(result, axis=1)


@dataclass
class RepairedMeanComponents:
    home_advantage: float
    centers: np.ndarray
    scales: np.ndarray
    supported_columns: np.ndarray
    ridge: Any
    residual_models: list[Any]

    def _linear(self, x):
        finite = np.isfinite(x)
        deviation = np.zeros_like(x)
        np.subtract(x, self.centers, out=deviation, where=finite)
        deviation /= self.scales
        return np.column_stack((deviation[:, self.supported_columns], (~finite)[:, self.supported_columns]))

    def predict(self, states):
        x = _mean_values(states)
        dynamic = predecessor_module._dynamic(states, self.home_advantage)
        hierarchical = np.maximum(dynamic + self.ridge.predict(self._linear(x)), 0.)
        hgb_x = np.column_stack((x, dynamic, hierarchical))
        with threadpool_limits(limits=NATIVE_WORKERS):
            corrections = np.column_stack([model.predict(hgb_x) for model in self.residual_models])
        corrections = np.clip(corrections, -RESIDUAL_BOUND_POINTS, RESIDUAL_BOUND_POINTS)
        return {"DYNAMIC": dynamic, "HIERARCHICAL": hierarchical,
                "RESIDUAL": np.maximum(hierarchical + corrections, 0.)}


def _fit_means(states, home_advantage, callback, stage):
    truth = predecessor_module._actual(states)
    dynamic = predecessor_module._dynamic(states, home_advantage)
    x = _mean_values(states)
    finite = np.isfinite(x)
    counts = finite.sum(axis=0)
    centers = np.divide(np.where(finite, x, 0.).sum(axis=0), counts, out=np.zeros(x.shape[1]), where=counts > 0)
    variance = np.divide(np.where(finite, x-centers, 0.).__pow__(2).sum(axis=0), counts,
                         out=np.zeros(x.shape[1]), where=counts > 0)
    core = RepairedMeanComponents(home_advantage, centers, np.sqrt(np.maximum(variance, 1e-12)), counts > 0,
                                  Ridge(alpha=40.), [])
    _emit(callback, "SCALER_FIT", stage=stage, rows=len(states), inputCount=len(MEAN_INPUT_NAMES))
    _emit(callback, "ESTIMATOR_FIT_START", stage=stage, component="HIERARCHICAL", target="JOINT_HOME_AWAY")
    with threadpool_limits(limits=NATIVE_WORKERS):
        core.ridge.fit(core._linear(x), truth-dynamic)
    _emit(callback, "ESTIMATOR_FIT_COMPLETE", stage=stage, component="HIERARCHICAL", target="JOINT_HOME_AWAY")
    hierarchical = np.maximum(dynamic + core.ridge.predict(core._linear(x)), 0.)
    hgb_x = np.column_stack((x, dynamic, hierarchical))
    for side, label in enumerate(("HOME", "AWAY")):
        estimator = HistGradientBoostingRegressor(**HGB_PARAMETERS)
        _emit(callback, "ESTIMATOR_FIT_START", stage=stage, component="RESIDUAL", target=label)
        with threadpool_limits(limits=NATIVE_WORKERS):
            estimator.fit(hgb_x, truth[:, side]-hierarchical[:, side])
        _emit(callback, "ESTIMATOR_FIT_COMPLETE", stage=stage, component="RESIDUAL", target=label)
        core.residual_models.append(estimator)
    return core


@dataclass
class FittedVarianceLaw:
    coefficients: np.ndarray
    metadata: dict

    def predict(self, states):
        variance = uncertainty_design(states) @ self.coefficients
        if not np.isfinite(variance).all() or (variance < 0).any():
            raise ValueError("INVALID_FITTED_VARIANCE")
        return variance

    @classmethod
    def fit(cls, normal_states, dropout_states, normal_errors, dropout_errors, *, callback, component):
        x_normal, x_dropout = uncertainty_design(normal_states), uncertainty_design(dropout_states)
        x = np.concatenate((x_normal.reshape(-1, 4), x_dropout.reshape(-1, 4)))
        target = np.concatenate((np.square(normal_errors).reshape(-1), np.square(dropout_errors).reshape(-1)))
        # The two reconstructions of each real inner-holdout game share equal
        # case weight. They are not claimed to be independent observations.
        weights = np.full(len(target), .5)
        scales = np.sqrt(np.average(np.square(x), axis=0, weights=weights))
        supported = scales > 0
        normalized = np.divide(x, scales, out=np.zeros_like(x), where=scales > 0)
        full_rank = int(np.linalg.matrix_rank(normalized[:, supported]))
        without_gap = supported.copy()
        without_gap[3] = False
        gap_identifiable = bool(supported[3] and full_rank > np.linalg.matrix_rank(normalized[:, without_gap]))
        if not gap_identifiable:
            # Observing a gap does not identify a separate gap coefficient when
            # its column is collinear with the other variance predictors.
            supported[3] = False
        coefficients = np.zeros(4)
        _emit(callback, "UNCERTAINTY_FIT_START", component=component, method="SYMMETRIC_NONNEGATIVE_LEAST_SQUARES")
        scaled, objective = nnls(x[:, supported] / scales[supported] * np.sqrt(weights[:, None]),
                                 target * np.sqrt(weights))
        coefficients[supported] = scaled / scales[supported]
        metadata = {"inputNames": list(VARIANCE_INPUT_NAMES), "coefficients": coefficients.tolist(),
            "normalGames": len(normal_states), "dropoutCases": len(dropout_states), "caseWeight": .5,
            "independentGameCount": len(normal_states), "pooledHomeAway": True,
            "fitObjective": "INNER_CHRONOLOGICAL_SQUARED_SCORE_ERROR_NONNEGATIVE_REGRESSION",
            "weightedResidualNorm": float(objective), "inputScales": scales.tolist(),
            "supportMax": x.max(axis=0).tolist(), "supportMin": x.min(axis=0).tolist(),
            "gapPositiveCases": int((x[:, 3] > 0).sum()), "gapIdentifiable": gap_identifiable,
            "varianceDesignRank": full_rank,
            "gapDisposition": "IDENTIFIED_NONNEGATIVE_COEFFICIENT" if gap_identifiable else "NOT_INDEPENDENTLY_IDENTIFIED_EXPLICIT_GAP_TERM_EXCLUDED",
            "noConfidenceIntervalOrCoverageCalibrationClaim": True}
        _emit(callback, "UNCERTAINTY_FIT_COMPLETE", component=component, **metadata)
        return cls(coefficients, metadata)


@dataclass
class RepairedCurrentStateSystem:
    lag_hours: int
    decay: float
    league_prior: dict
    core: RepairedMeanComponents
    residual_banks: dict
    variance_laws: dict[str, FittedVarianceLaw]
    metadata: dict = field(default_factory=dict)

    def predict(self, events, team, qb, *, draws=1000, seed=SEED):
        for label, frame in (("events", events), ("team", team), ("qb", qb)):
            predecessor_module._guard_source(frame, label)
        if pd.to_datetime(events.game_date).min() <= pd.Timestamp(self.metadata["trainingEnd"]):
            raise ValueError("FORECAST_NOT_AFTER_MODEL_TRAINING_CUTOFF")
        build, _ = _feature_api()
        states = build(events, team, qb, lag_hours=self.lag_hours, decay=self.decay, league_prior=self.league_prior)
        if states.canonical_game_id.tolist() != events.canonical_game_id.tolist():
            raise ValueError("TREATMENT_EVENT_ORDER_CHANGED")
        return self.predict_states(states, draws=draws, seed=seed)

    def predict_states(self, states, *, draws=1000, seed=SEED):
        """Internal frozen-state reconstruction path; caller owns cutoff proof."""
        if int(draws) < 1:
            raise ValueError("DRAW_COUNT_MUST_BE_POSITIVE")
        means = self.core.predict(states)
        randoms = make_common_random_numbers(n_games=len(states), draws=draws, seed=seed)
        coverage = self._coverage(states)
        result = {"_states": states, "_coverage": coverage}
        for name in MODEL_IDS:
            bank, law = self.residual_banks[name], self.variance_laws[name]
            variance = law.predict(states)
            bank_variance = np.var(np.column_stack((bank.home, bank.away)), axis=0)
            if (bank_variance <= 0).any():
                raise ValueError("DEGENERATE_PAIRED_RESIDUAL_AUTHORITY")
            scale = np.sqrt(variance / bank_variance)
            index = np.minimum((randoms.residual_uniform * bank.row_count).astype(int), bank.row_count-1)
            raw_home = means[name][:, 0, None] + scale[:, 0, None] * bank.home[index]
            raw_away = means[name][:, 1, None] + scale[:, 1, None] * bank.away[index]
            home = mean_preserving_scores(raw_home, means[name][:, 0])
            away = mean_preserving_scores(raw_away, means[name][:, 1])
            result[name] = {"scoreMeans": means[name], "homeDraws": home, "awayDraws": away,
                "distributionScoreMeans": np.column_stack((home.mean(axis=1), away.mean(axis=1))),
                "probabilityAwayTieHome": np.column_stack(((away > home).mean(axis=1), (away == home).mean(axis=1), (home > away).mean(axis=1))),
                "stateUncertainty": np.sqrt(variance), "stateUncertaintyMeaning": "FITTED_TOTAL_RESIDUAL_SCORE_SD_NOT_PARAMETER_POSTERIOR_SD",
                "fittedLatentResidualVariance": variance, "actualPopulationVariance": np.column_stack((home.var(axis=1), away.var(axis=1))),
                "residualScale": scale, "branchCounts": coverage, "features": list(MEAN_INPUT_NAMES),
                "residualAuthoritySha256": bank.sha256, "repairAuthority": REPAIR_AUTHORITY,
                "finitePopulationMeanRule": "NEAREST_EVEN_INTEGER_TOTAL_EXACT_SUM_NONNEGATIVE_PROJECTION_BALANCED_ROUNDING",
                "evidenceClass": EVIDENCE_CLASS, "rowEvidenceClasses": states.evidence_class.tolist()}
        return result

    @staticmethod
    def _coverage(states):
        result = predecessor_module.CurrentStateSystem._coverage(states)
        result.update(meanInputCount=len(MEAN_INPUT_NAMES), uncertaintyOnlyInputsExcludedFromMean=6)
        return result

    def state(self):
        return {**self.metadata, "contract": CONTRACT, "repairAuthority": REPAIR_AUTHORITY,
            "lagHours": self.lag_hours, "selectedRetention": self.decay, "leaguePrior": self.league_prior,
            "inputNames": list(INPUT_NAMES), "meanInputNames": list(MEAN_INPUT_NAMES),
            "uncertaintyOnlyNames": list(UNCERTAINTY_ONLY_NAMES), "selectedInputCount": len(MEAN_INPUT_NAMES),
            "semanticInputs": len(RATE_NAMES), "ridgeExpandedColumns": int(self.core.supported_columns.sum())*2,
            "hgbExpandedColumns": len(MEAN_INPUT_NAMES)+4,
            "observedTrainingCenters": self.core.centers.tolist(), "observedTrainingScales": self.core.scales.tolist(),
            "varianceLaws": {name: law.metadata for name, law in self.variance_laws.items()},
            "residualAuthorities": {name: {"sha256": bank.sha256, "rows": bank.row_count,
                "rowIds": list(bank.row_ids), "trainingEnd": bank.training_end} for name, bank in self.residual_banks.items()},
            "meanRoleJustification": "44 semantic estimates encode ability; QB EPA mixture is ability, effective passer exposure and prior/current game counts are measured experience/support states. Posterior SD and age/missing-season summaries are excluded from both mean designs.",
            "uncertaintyRule": "INNER_HOLDOUT_REGULAR_PLUS_PREVIOUS_SEASON_OBSERVATION_DROPOUT_NONNEGATIVE_VARIANCE_REGRESSION",
            "uncertaintyIsCalibrated": False, "genericMedianFallbacks": 0, "genericModeFallbacks": 0,
            "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False,
            "executionAllowedInAISP": False}


def fit_repaired_current_state_system(train_games, team, qb, *, predecessor, predecessor_ref=None,
                                     lag_hours=48, receipt_callback: Callable | None = None, artifact_dir=None):
    """Six fixed mean fits and three variance fits; no retention/prior search."""
    if artifact_dir is not None:
        folder = Path(artifact_dir)
        if folder.exists() and any(folder.iterdir()):
            raise ValueError("REPAIR_RECONSTRUCTION_DIRECTORY_MUST_BE_NEW")
    for label, frame in (("training", train_games), ("team", team), ("qb", qb)):
        predecessor_module._guard_source(frame, label)
    if train_games.empty or train_games.canonical_game_id.duplicated().any() or int(train_games.season.max()) >= 2025:
        raise ValueError("INVALID_REPAIR_DEVELOPMENT_TRAINING")
    if lag_hours not in (48, 72) or lag_hours != predecessor.lag_hours:
        raise ValueError("PREDECESSOR_AVAILABILITY_LAG_DIFFERS")
    if set(train_games.canonical_game_id.astype(str)) != set(predecessor.league_prior["training_ids"]):
        raise ValueError("PREDECESSOR_TRAINING_POPULATION_DIFFERS")
    if predecessor_ref is not None and file_record(Path(predecessor_ref["path"])) != predecessor_ref:
        raise ValueError("PREDECESSOR_MODEL_CHECKSUM_DIFFERS")
    inner_season = int(train_games.season.max())
    inner_train, inner_valid = train_games.loc[train_games.season < inner_season].copy(), train_games.loc[train_games.season == inner_season].copy()
    if len(inner_train) < 10 or len(inner_valid) < 2:
        raise ValueError("INSUFFICIENT_CHRONOLOGICAL_INNER_AUTHORITY")
    build, fit_prior = _feature_api()
    _emit(receipt_callback, "PRIOR_PARAMETER_RECONSTRUCTION_START", stage="INNER", reason="PREDECESSOR_INNER_PRIOR_NOT_SERIALIZED")
    inner_prior = fit_prior(inner_train, team, qb, lag_hours=lag_hours)
    _emit(receipt_callback, "PRIOR_PARAMETER_RECONSTRUCTION_COMPLETE", stage="INNER")
    decay = predecessor.decay
    inner_states = build(inner_train, team, qb, lag_hours=lag_hours, decay=decay, league_prior=inner_prior)
    normal_states = build(inner_valid, team, qb, lag_hours=lag_hours, decay=decay, league_prior=inner_prior)
    dropped_season = inner_season-1
    dropped_team, dropped_qb = team.loc[team.season.ne(dropped_season)], qb.loc[qb.season.ne(dropped_season)]
    dropout_states = build(inner_valid, dropped_team, dropped_qb, lag_hours=lag_hours, decay=decay, league_prior=inner_prior)
    inner_truth = predecessor_module._actual(inner_train)
    inner_hfa = float(np.mean(inner_truth[:, 0]-inner_truth[:, 1]))
    inner_core = _fit_means(inner_states, inner_hfa, receipt_callback, "INNER")
    normal_means, dropout_means = inner_core.predict(normal_states), inner_core.predict(dropout_states)
    truth = predecessor_module._actual(inner_valid)
    banks, laws = {}, {}
    for name in MODEL_IDS:
        _emit(receipt_callback, "RESIDUAL_AUTHORITY_FIT_START", component=name, rows=len(inner_valid))
        banks[name] = PairedResidualAuthority.fit(actual_home=truth[:, 0], actual_away=truth[:, 1],
            predicted_home=normal_means[name][:, 0], predicted_away=normal_means[name][:, 1],
            row_ids=inner_valid.canonical_game_id.astype(str).tolist(), row_dates=pd.to_datetime(inner_valid.game_date).dt.strftime("%Y-%m-%d").tolist(),
            training_end=str(pd.Timestamp(inner_valid.game_date.max()).date()))
        _emit(receipt_callback, "RESIDUAL_AUTHORITY_FIT_COMPLETE", component=name, sha256=banks[name].sha256)
        laws[name] = FittedVarianceLaw.fit(normal_states, dropout_states, truth-normal_means[name], truth-dropout_means[name],
                                         callback=receipt_callback, component=name)
    prior = predecessor.league_prior
    full_states = build(train_games, team, qb, lag_hours=lag_hours, decay=decay, league_prior=prior)
    hfa = predecessor.core.home_advantage
    core = _fit_means(full_states, hfa, receipt_callback, "FULL_TRAINING")
    reconstruction_artifacts = []
    if artifact_dir is not None:
        folder = Path(artifact_dir)
        folder.mkdir(parents=True, exist_ok=True)
        if any(folder.iterdir()):
            raise ValueError("REPAIR_RECONSTRUCTION_DIRECTORY_MUST_BE_NEW")
        for name, states in (("inner-training", inner_states), ("inner-validation", normal_states),
                             ("inner-dropout", dropout_states), ("full-training", full_states)):
            path = folder/f"{name}-states.parquet"
            states.to_parquet(path, index=False)
            reconstruction_artifacts.append(file_record(path))
        path = folder/"inner-core.joblib"
        joblib.dump(inner_core, path, compress=3)
        reconstruction_artifacts.append(file_record(path))
        reconstruction_artifacts.append(immutable_json(folder/"inner-prior.json", inner_prior))
        reconstruction_artifacts.append(immutable_json(folder/"inner-means.json", {
            "evidenceClass": EVIDENCE_CLASS, "rowIds": inner_valid.canonical_game_id.tolist(),
            "normal": {name: means.tolist() for name, means in normal_means.items()},
            "dropout": {name: means.tolist() for name, means in dropout_means.items()}}))
    return RepairedCurrentStateSystem(lag_hours, decay, prior, core, banks, laws, {
        "evidenceClass": EVIDENCE_CLASS, "repairAuthority": REPAIR_AUTHORITY, "predecessor": predecessor_ref,
        "trainingEnd": str(pd.Timestamp(train_games.game_date.max()).date()), "trainingRows": len(train_games),
        "innerTrainingRows": len(inner_train), "innerValidationRows": len(inner_valid), "innerValidationSeason": inner_season,
        "frozenRetentionReused": decay, "frozenFullLeaguePriorReused": True, "frozenDynamicHomeAdvantageReused": hfa,
        "dropout": {"removedObservationSeason": dropped_season, "innerValidationSeason": inner_season,
            "droppedTeamRows": int(team.season.eq(dropped_season).sum()), "droppedQbRows": int(qb.season.eq(dropped_season).sum()),
            "scope": "PREVIOUS_SEASON_OBSERVATIONS_ONLY; INNER_PRIOR_PARAMETERS_FROZEN; CURRENT_WEEK_CUTOFF_UNCHANGED",
            "notIndependentAdditionalGames": True},
        "actualEstimatorFitStarts": 6, "actualEstimatorFitCompletions": 6, "uncertaintyFits": 3,
        "decayEvaluations": 0, "priorParameterReconstructions": 1, "priorParameterFits": 1,
        "scalerFits": 2, "pairedResidualAuthorityFits": 3, "calibratorFits": 0,
        "ridgeAlpha": 40., "hgbParameters": HGB_PARAMETERS, "residualBoundPoints": RESIDUAL_BOUND_POINTS,
        "nativeWorkers": NATIVE_WORKERS, "reconstructionArtifacts": reconstruction_artifacts,
        "sealed2025Read": False, "lateHistoricalCorrectionsPossible": True,
        "originalHistoricalPublicationVintageEstablished": False})
