"""Development-only NFL multi-model and feature-treatment laboratory.

The runner never reads the sealed 2025 outcome population.  Every model,
feature selector, treatment, residual adapter, and calibrator is fitted within
the relevant chronological training authority.  Results are research-only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import matplotlib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.neural_network import MLPRegressor
from threadpoolctl import threadpool_limits

from server.audit_assurance.canonical import canonical_json_bytes

from .contracts import RANDOM_SEED, NflM1IntegrityError
from .data_authority import DEFAULT_NFL_STAGING_ROOT, resolve_nfl_m1_authority
from .distributions import PairedResidualAuthority, make_common_random_numbers, simulate_joint_scores


matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


MATRIX_PATH = Path(__file__).with_name("nfl_overnight_matrix_v1.json")
DEFAULT_EXTERNAL_ROOT = DEFAULT_NFL_STAGING_ROOT / "overnight-model-laboratory-v1"
DEFAULT_OUTPUT_ROOT = Path("outputs") / "nfl-overnight-model-laboratory-v1"
RUN_CONTRACT = "ASP_NFL_OVERNIGHT_MODEL_LAB_RUN_V1"
RESULT_CONTRACT = "ASP_NFL_OVERNIGHT_MODEL_LAB_RESULT_V1"
CATEGORICAL = ("game_type", "roof", "surface")
IDENTITY = (
    "canonical_game_id", "season", "game_date", "week", "game_type",
    "home_points", "away_points", "tie_game",
)
UTC = timezone.utc


class NflOvernightLabError(RuntimeError):
    """A leakage, authority, or persistence invariant failed."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> str:
    payload = canonical_json_bytes(dict(value))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _sha_bytes(payload)


def _atomic_parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        frame.to_parquet(temporary, index=False, compression="zstd")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _sha_file(path)


def _matrix() -> tuple[dict[str, Any], str]:
    payload = MATRIX_PATH.read_bytes()
    value = json.loads(payload)
    if value.get("contract") != "ASP_NFL_OVERNIGHT_EXPERIMENT_MATRIX_V1":
        raise NflOvernightLabError("experiment matrix contract differs")
    if value.get("declaredBeforeCandidateOutcomeInspection") is not True:
        raise NflOvernightLabError("experiment matrix was not prospectively declared")
    return value, _sha_bytes(payload)


@dataclass(frozen=True)
class LabConfig:
    foundation_root: Path = DEFAULT_NFL_STAGING_ROOT / "foundation-v1"
    external_root: Path = DEFAULT_EXTERNAL_ROOT
    output_root: Path = DEFAULT_OUTPUT_ROOT
    draws: int = 2_000
    tuning_draws: int = 1_000
    bootstrap_resamples: int = 1_000
    seed: int = RANDOM_SEED
    max_threads: int = 2


def _load_development(config: LabConfig) -> tuple[Any, pd.DataFrame, tuple[str, ...]]:
    authority = resolve_nfl_m1_authority(config.foundation_root, deep_verify=True)
    features = tuple(authority.game_ordered_predictors)
    columns = list(dict.fromkeys((*IDENTITY, *features)))
    # This physical predicate is the sealed-population boundary.  No 2025
    # identity, feature, or outcome column is read by this study.
    frame = pd.read_parquet(
        authority.game_path,
        columns=columns,
        filters=[("season", "<", 2025)],
        engine="pyarrow",
    )
    frame["game_date"] = pd.to_datetime(frame["game_date"], errors="raise")
    frame = frame.sort_values(["game_date", "canonical_game_id"], kind="stable").reset_index(drop=True)
    if frame.empty or int(frame["season"].max()) != 2024 or int(frame["season"].min()) != 1999:
        raise NflOvernightLabError("development population boundary differs")
    if frame["canonical_game_id"].astype(str).duplicated().any():
        raise NflOvernightLabError("development game identities are not unique")
    if len(features) != 197 or any(name not in frame.columns for name in features):
        raise NflOvernightLabError("registered 197-input contract differs")
    if not np.isfinite(frame[["home_points", "away_points"]].to_numpy(float)).all():
        raise NflOvernightLabError("development score truth is incomplete")
    return authority, frame, features


def _folds(frame: pd.DataFrame) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for position, season in enumerate((2020, 2021, 2022, 2023, 2024), start=1):
        train = frame.index[frame["season"] < season].to_numpy()
        validation = frame.index[frame["season"] == season].to_numpy()
        if train.size == 0 or validation.size == 0:
            raise NflOvernightLabError(f"fold {position} is empty")
        if frame.loc[train, "game_date"].max() >= frame.loc[validation, "game_date"].min():
            raise NflOvernightLabError(f"fold {position} is not chronological")
        ids = set(frame.loc[validation, "canonical_game_id"].astype(str))
        if ids & seen:
            raise NflOvernightLabError("validation identities overlap")
        seen |= ids
        result.append({
            "foldId": f"FOLD_{position}",
            "trainIndex": train,
            "validationIndex": validation,
            "trainStart": frame.loc[train, "game_date"].min().date().isoformat(),
            "trainEnd": frame.loc[train, "game_date"].max().date().isoformat(),
            "validationStart": frame.loc[validation, "game_date"].min().date().isoformat(),
            "validationEnd": frame.loc[validation, "game_date"].max().date().isoformat(),
            "trainRows": int(train.size),
            "validationRows": int(validation.size),
            "validationSeason": season,
        })
    return result


def _engineered(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    result = frame.copy()
    definitions: list[dict[str, Any]] = []
    roots = (
        "points_for", "points_against", "offensive_epa_per_play",
        "defensive_epa_per_play", "pass_epa_per_play", "rush_epa_per_play",
        "success_rate", "defensive_success_rate", "turnover_rate", "sack_rate",
        "penalty_rate", "seconds_per_play",
    )
    for root in roots:
        for window in ("last_4", "last_16"):
            home, away = f"home_{root}_{window}", f"away_{root}_{window}"
            if home in result and away in result:
                name = f"engineered_{root}_{window}_home_minus_away"
                result[name] = pd.to_numeric(result[home], errors="coerce") - pd.to_numeric(result[away], errors="coerce")
                definitions.append({"feature": name, "method": "HOME_MINUS_AWAY", "inputs": [home, away]})
        home4, home16 = f"home_{root}_last_4", f"home_{root}_last_16"
        away4, away16 = f"away_{root}_last_4", f"away_{root}_last_16"
        for side, short, long in (("home", home4, home16), ("away", away4, away16)):
            if short in result and long in result:
                name = f"engineered_{side}_{root}_short_minus_long"
                result[name] = pd.to_numeric(result[short], errors="coerce") - pd.to_numeric(result[long], errors="coerce")
                definitions.append({"feature": name, "method": "LAST_4_MINUS_LAST_16", "inputs": [short, long]})
        hs, as_ = f"home_{root}_season_to_date", f"away_{root}_season_to_date"
        hl, al = f"home_{root}_last_16", f"away_{root}_last_16"
        if all(name in result for name in (hs, as_, hl, al)):
            for side, current, long, count in (
                ("home", hs, hl, "home_prior_season_games"),
                ("away", as_, al, "away_prior_season_games"),
            ):
                n = pd.to_numeric(result[count], errors="coerce").fillna(0.0).clip(lower=0.0)
                weight = n / (n + 4.0)
                current_values = pd.to_numeric(result[current], errors="coerce")
                long_values = pd.to_numeric(result[long], errors="coerce")
                name = f"engineered_{side}_{root}_reliability_blend"
                result[name] = weight * current_values + (1.0 - weight) * long_values
                definitions.append({
                    "feature": name,
                    "method": "N_OVER_N_PLUS_4_SEASON_TO_DATE_PLUS_LAST_16",
                    "inputs": [current, long, count],
                })
    result["engineered_rest_days_home_minus_away"] = (
        pd.to_numeric(result["home_days_since_previous_game"], errors="coerce")
        - pd.to_numeric(result["away_days_since_previous_game"], errors="coerce")
    )
    definitions.append({
        "feature": "engineered_rest_days_home_minus_away",
        "method": "HOME_MINUS_AWAY",
        "inputs": ["home_days_since_previous_game", "away_days_since_previous_game"],
    })
    return result, definitions


def _f1_features(train: pd.DataFrame, baseline: Sequence[str]) -> tuple[tuple[str, ...], dict[str, Any]]:
    categoricals = [name for name in baseline if name in CATEGORICAL]
    numerics = [name for name in baseline if name not in CATEGORICAL]
    forced = [
        name for name in numerics
        if name in {"season", "week", "game_month", "game_weekday", "neutral_site", "division_game"}
        or "days_since_previous_game" in name
        or "prior_games" in name
        or "prior_season_games" in name
        or "source_era_missing" in name
    ]
    eligible = [name for name in numerics if float(train[name].isna().mean()) <= 0.40 or name in forced]
    numeric = train[eligible].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.fillna(numeric.median()).fillna(0.0)
    nonconstant = [name for name in eligible if numeric[name].nunique(dropna=False) > 1 or name in forced]
    kept: list[str] = []
    removed_redundant: list[str] = []
    for name in nonconstant:
        if name in forced:
            kept.append(name)
            continue
        if kept:
            correlations = numeric[kept].corrwith(numeric[name]).abs()
            if bool((correlations > 0.985).any()):
                removed_redundant.append(name)
                continue
        kept.append(name)
    associations = {}
    for name in kept:
        values = numeric[name]
        scores = []
        for target in ("home_points", "away_points"):
            correlation = values.corr(pd.to_numeric(train[target], errors="coerce"))
            scores.append(0.0 if pd.isna(correlation) else abs(float(correlation)))
        associations[name] = float(np.mean(scores))
    selected = list(dict.fromkeys([*forced, *sorted(kept, key=lambda name: (-associations[name], name))[:60]]))
    names = tuple([name for name in baseline if name in selected or name in categoricals])
    return names, {
        "fitScope": "TRAINING_ROWS_OF_THIS_FOLD_ONLY",
        "missingnessMaximum": 0.40,
        "redundancyAbsoluteCorrelationMaximum": 0.985,
        "boundedAssociationMaximumFeatures": 60,
        "forcedColdStartAndContext": forced,
        "removedForMissingness": sorted(set(numerics) - set(eligible)),
        "removedForRedundancy": removed_redundant,
        "selectedFeatures": list(names),
        "targetAssociation": {name: associations[name] for name in selected if name in associations},
    }


@dataclass
class FoldTreatment:
    feature_names: tuple[str, ...]
    treatment: str
    family: str
    medians: dict[str, float] = field(default_factory=dict)
    clips: dict[str, tuple[float, float]] = field(default_factory=dict)
    log1p_features: tuple[str, ...] = ()
    centers: dict[str, float] = field(default_factory=dict)
    scales: dict[str, float] = field(default_factory=dict)
    categories: dict[str, tuple[str, ...]] = field(default_factory=dict)
    missing_indicators: tuple[str, ...] = ()
    expanded_names: tuple[str, ...] = ()

    @classmethod
    def fit(cls, frame: pd.DataFrame, feature_names: Sequence[str], treatment: str, family: str) -> "FoldTreatment":
        names = tuple(feature_names)
        if treatment not in {"T0", "T1", "T2"}:
            raise NflOvernightLabError("unknown treatment")
        fitted = cls(names, treatment, family)
        numeric_names = [name for name in names if name not in CATEGORICAL]
        indicators = []
        logs = []
        expanded = []
        scale_values = family in {"RIDGE", "MLP"} or treatment == "T0"
        robust = treatment in {"T1", "T2"}
        for name in numeric_names:
            values = pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
            finite = values[np.isfinite(values)]
            median = float(np.median(finite)) if finite.size else 0.0
            fitted.medians[name] = median
            if np.isnan(values).any():
                indicators.append(name)
            imputed = np.where(np.isfinite(values), values, median)
            unique = np.unique(imputed)
            binary = unique.size <= 2 and set(unique.tolist()).issubset({0.0, 1.0})
            if treatment in {"T1", "T2"} and not binary and finite.size >= 20:
                lower, upper = np.quantile(finite, [0.01, 0.99])
                if np.isfinite(lower) and np.isfinite(upper) and lower < upper:
                    fitted.clips[name] = (float(lower), float(upper))
                    imputed = np.clip(imputed, lower, upper)
            if treatment == "T2" and not binary and np.min(imputed) >= 0.0:
                skew = float(pd.Series(imputed).skew())
                if np.isfinite(skew) and abs(skew) > 1.0:
                    logs.append(name)
                    imputed = np.log1p(imputed)
            if scale_values:
                if robust:
                    center = float(np.median(imputed))
                    q1, q3 = np.quantile(imputed, [0.25, 0.75])
                    scale = float(q3 - q1) or 1.0
                else:
                    center = float(np.mean(imputed))
                    scale = float(np.std(imputed, ddof=0)) or 1.0
            else:
                center, scale = 0.0, 1.0
            fitted.centers[name], fitted.scales[name] = center, scale
            expanded.append(name)
        for name in names:
            if name in CATEGORICAL:
                values = frame[name].astype("string").fillna("SOURCE_OR_HISTORY_MISSING")
                levels = tuple(sorted(set(str(value) for value in values)))
                fitted.categories[name] = levels
                expanded.extend(f"{name}={value}" for value in levels)
        expanded.extend(f"{name}__missing" for name in indicators)
        fitted.log1p_features = tuple(logs)
        fitted.missing_indicators = tuple(indicators)
        fitted.expanded_names = tuple(expanded)
        fitted.transform(frame)
        return fitted

    def transform(self, frame: pd.DataFrame) -> np.ndarray:
        columns: list[np.ndarray] = []
        missing_arrays: list[np.ndarray] = []
        for name in self.feature_names:
            if name in CATEGORICAL:
                values = frame[name].astype("string").fillna("SOURCE_OR_HISTORY_MISSING").astype(str).to_numpy()
                for level in self.categories[name]:
                    columns.append((values == level).astype(float)[:, None])
                continue
            values = pd.to_numeric(frame[name], errors="coerce").to_numpy(float)
            missing = ~np.isfinite(values)
            if name in self.missing_indicators:
                missing_arrays.append(missing.astype(float)[:, None])
            values = np.where(np.isfinite(values), values, self.medians[name])
            if name in self.clips:
                values = np.clip(values, *self.clips[name])
            if name in self.log1p_features:
                values = np.log1p(np.maximum(values, 0.0))
            values = (values - self.centers[name]) / self.scales[name]
            columns.append(values[:, None])
        columns.extend(missing_arrays)
        matrix = np.concatenate(columns, axis=1).astype(np.float64, copy=False)
        if matrix.shape != (len(frame), len(self.expanded_names)) or not np.isfinite(matrix).all():
            raise NflOvernightLabError("fold treatment produced invalid matrix")
        return np.ascontiguousarray(matrix)

    def state(self) -> dict[str, Any]:
        return {
            "treatment": self.treatment,
            "family": self.family,
            "featureNames": list(self.feature_names),
            "fitScope": "TRAINING_ROWS_OF_THIS_FOLD_ONLY",
            "numericImputation": "MEDIAN_WITH_MISSING_INDICATOR",
            "medians": self.medians,
            "clipMethod": "TRAINING_1ST_99TH_PERCENTILE_NONBINARY" if self.treatment != "T0" else "NONE",
            "clips": {name: list(value) for name, value in self.clips.items()},
            "skewMethod": "LOG1P_NONNEGATIVE_ABS_SKEW_GT_1" if self.treatment == "T2" else "NONE",
            "log1pFeatures": list(self.log1p_features),
            "scaling": (
                "ROBUST_MEDIAN_IQR" if self.treatment != "T0" and self.family in {"RIDGE", "MLP"}
                else "STANDARD_MEAN_SD" if self.treatment == "T0"
                else "NONE_TREE_INVARIANT"
            ),
            "centers": self.centers,
            "scales": self.scales,
            "categoricalValues": {name: list(values) for name, values in self.categories.items()},
            "expandedFeatureNames": list(self.expanded_names),
        }


def _estimator(family: str, parameters: Mapping[str, Any], seed: int) -> Any:
    values = dict(parameters)
    if family == "RIDGE":
        return Ridge(alpha=float(values["alpha"]))
    if family == "EXTRA_TREES":
        return ExtraTreesRegressor(
            **values, criterion="squared_error", bootstrap=False,
            n_jobs=2, random_state=seed,
        )
    if family == "HIST_GRADIENT_BOOSTING":
        return HistGradientBoostingRegressor(
            **values, loss="squared_error", early_stopping=False, random_state=seed,
        )
    if family == "XGBOOST":
        try:
            from xgboost import XGBRegressor
        except ImportError as exc:
            raise NflOvernightLabError("XGBoost dependency is unavailable") from exc
        return XGBRegressor(
            **values, objective="reg:squarederror", tree_method="hist",
            n_jobs=2, random_state=seed, verbosity=0,
        )
    if family == "MLP":
        values["hidden_layer_sizes"] = tuple(values["hidden_layer_sizes"])
        return MLPRegressor(
            **values, early_stopping=True, validation_fraction=0.15,
            n_iter_no_change=20, random_state=seed,
        )
    raise NflOvernightLabError(f"unsupported family: {family}")


@dataclass
class FittedScorePipeline:
    pipeline_id: str
    family: str
    parameters: Mapping[str, Any]
    feature_variant: str
    treatment_id: str
    feature_names: tuple[str, ...]
    feature_definitions: list[dict[str, Any]]
    selection_state: Mapping[str, Any] | None
    transformer: FoldTreatment
    home_model: Any
    away_model: Any
    seed: int

    def predict(self, frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, int]:
        expanded, _ = _engineered(frame) if self.feature_variant == "F2" else (frame, [])
        matrix = self.transformer.transform(expanded)
        raw_home = np.asarray(self.home_model.predict(matrix), dtype=float)
        raw_away = np.asarray(self.away_model.predict(matrix), dtype=float)
        negative = int((raw_home < 0.0).sum() + (raw_away < 0.0).sum())
        return np.maximum(raw_home, 0.0), np.maximum(raw_away, 0.0), negative

    def state(self) -> dict[str, Any]:
        return {
            "pipelineId": self.pipeline_id,
            "family": self.family,
            "parameters": dict(self.parameters),
            "featureVariant": self.feature_variant,
            "treatment": self.treatment_id,
            "featureNames": list(self.feature_names),
            "featureDefinitions": self.feature_definitions,
            "selectionState": self.selection_state,
            "transformer": self.transformer.state(),
            "seedHome": self.seed,
            "seedAway": self.seed + 1,
            "status": "RESEARCH_SHADOW",
            "promotionStatus": "NOT_PROMOTED",
            "deploymentEligible": False,
        }


def _fit_pipeline(
    pipeline: Mapping[str, Any],
    parameters: Mapping[str, Any],
    train: pd.DataFrame,
    baseline_features: Sequence[str],
    *,
    seed: int,
) -> FittedScorePipeline:
    variant = str(pipeline["features"])
    feature_definitions: list[dict[str, Any]] = []
    selection_state = None
    prepared = train
    if variant == "F1":
        feature_names, selection_state = _f1_features(train, baseline_features)
    elif variant == "F2":
        prepared, feature_definitions = _engineered(train)
        feature_names = tuple([*baseline_features, *(item["feature"] for item in feature_definitions)])
    else:
        feature_names = tuple(baseline_features)
    transformer = FoldTreatment.fit(prepared, feature_names, str(pipeline["treatment"]), str(pipeline["family"]))
    matrix = transformer.transform(prepared)
    home = _estimator(str(pipeline["family"]), parameters, seed)
    away = _estimator(str(pipeline["family"]), parameters, seed + 1)
    home.fit(matrix, train["home_points"].to_numpy(float))
    away.fit(matrix, train["away_points"].to_numpy(float))
    return FittedScorePipeline(
        pipeline_id=str(pipeline["id"]), family=str(pipeline["family"]),
        parameters=dict(parameters), feature_variant=variant,
        treatment_id=str(pipeline["treatment"]), feature_names=feature_names,
        feature_definitions=feature_definitions, selection_state=selection_state,
        transformer=transformer, home_model=home, away_model=away, seed=seed,
    )


def _outcome_class(frame: pd.DataFrame) -> np.ndarray:
    home = frame["home_points"].to_numpy(float)
    away = frame["away_points"].to_numpy(float)
    return np.where(home > away, 2, np.where(home < away, 0, 1)).astype(np.int8)


def _probabilities(simulation: Any) -> np.ndarray:
    margin = simulation.home - simulation.away
    values = np.column_stack((
        np.mean(margin < 0, axis=1),
        np.mean(margin == 0, axis=1),
        np.mean(margin > 0, axis=1),
    )).astype(float)
    values = np.maximum(values, 1e-12)
    return values / values.sum(axis=1, keepdims=True)


def _loss_vector(probabilities: np.ndarray, truth: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(probabilities, dtype=float), 1e-12, 1.0)
    clipped /= clipped.sum(axis=1, keepdims=True)
    return -np.log(clipped[np.arange(len(truth)), np.asarray(truth, dtype=int)])


def _ece_home(probabilities: np.ndarray, truth: np.ndarray, bins: int = 10) -> float:
    forecast = probabilities[:, 2]
    actual = (truth == 2).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    result = 0.0
    for position in range(bins):
        mask = (forecast >= edges[position]) & (
            forecast <= edges[position + 1] if position == bins - 1 else forecast < edges[position + 1]
        )
        if mask.any():
            result += float(mask.mean()) * abs(float(forecast[mask].mean() - actual[mask].mean()))
    return result


def _metrics(ledger: pd.DataFrame, *, probability_prefix: str = "raw") -> dict[str, float | int]:
    probability = ledger[[
        f"{probability_prefix}_away_probability",
        f"{probability_prefix}_tie_probability",
        f"{probability_prefix}_home_probability",
    ]].to_numpy(float)
    truth = ledger["outcome_class"].to_numpy(int)
    actual_home = ledger["actual_home_points"].to_numpy(float)
    actual_away = ledger["actual_away_points"].to_numpy(float)
    predicted_home = ledger["predicted_home_points"].to_numpy(float)
    predicted_away = ledger["predicted_away_points"].to_numpy(float)
    return {
        "games": int(len(ledger)),
        "multiclassLogLoss": float(_loss_vector(probability, truth).mean()),
        "multiclassBrier": float(np.mean(np.sum((probability - np.eye(3)[truth]) ** 2, axis=1))),
        "homeWinEce": _ece_home(probability, truth),
        "homeScoreMae": float(np.mean(np.abs(predicted_home - actual_home))),
        "awayScoreMae": float(np.mean(np.abs(predicted_away - actual_away))),
        "homeScoreRmse": float(np.sqrt(np.mean((predicted_home - actual_home) ** 2))),
        "awayScoreRmse": float(np.sqrt(np.mean((predicted_away - actual_away) ** 2))),
        "marginMae": float(np.mean(np.abs(
            (predicted_home - predicted_away) - (actual_home - actual_away)
        ))),
        "totalMae": float(np.mean(np.abs(
            (predicted_home + predicted_away) - (actual_home + actual_away)
        ))),
    }


def _fit_and_score(
    pipeline: Mapping[str, Any],
    parameters: Mapping[str, Any],
    train: pd.DataFrame,
    validation: pd.DataFrame,
    baseline_features: Sequence[str],
    *,
    seed: int,
    draws: int,
    common_random_numbers: Any | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], FittedScorePipeline]:
    calibration_season = int(train["season"].max())
    residual_train = train.loc[train["season"] < calibration_season].copy()
    residual_validation = train.loc[train["season"] == calibration_season].copy()
    if residual_train.empty or residual_validation.empty:
        raise NflOvernightLabError("training-only residual split is empty")
    started = time.perf_counter()
    residual_model = _fit_pipeline(
        pipeline, parameters, residual_train, baseline_features, seed=seed + 10_000
    )
    residual_home, residual_away, residual_negative = residual_model.predict(residual_validation)
    residual_authority = PairedResidualAuthority.fit(
        actual_home=residual_validation["home_points"].to_numpy(float),
        actual_away=residual_validation["away_points"].to_numpy(float),
        predicted_home=residual_home,
        predicted_away=residual_away,
        row_ids=residual_validation["canonical_game_id"].astype(str).tolist(),
        row_dates=residual_validation["game_date"].tolist(),
        training_end=residual_validation["game_date"].max(),
    )
    fitted = _fit_pipeline(pipeline, parameters, train, baseline_features, seed=seed)
    fit_seconds = time.perf_counter() - started
    scoring_started = time.perf_counter()
    predicted_home, predicted_away, validation_negative = fitted.predict(validation)
    randoms = common_random_numbers or make_common_random_numbers(
        n_games=len(validation), draws=draws, seed=seed + 20_000
    )
    simulation = simulate_joint_scores(
        predicted_home_mean=predicted_home,
        predicted_away_mean=predicted_away,
        residual_authority=residual_authority,
        draws=draws,
        seed=seed + 20_000,
        common_random_numbers=randoms,
    )
    probability = _probabilities(simulation)
    ledger = pd.DataFrame({
        "canonical_game_id": validation["canonical_game_id"].astype(str).to_numpy(),
        "season": validation["season"].astype(int).to_numpy(),
        "week": validation["week"].astype(str).to_numpy(),
        "game_date": validation["game_date"].dt.strftime("%Y-%m-%d").to_numpy(),
        "actual_home_points": validation["home_points"].to_numpy(float),
        "actual_away_points": validation["away_points"].to_numpy(float),
        "outcome_class": _outcome_class(validation),
        "predicted_home_points": predicted_home,
        "predicted_away_points": predicted_away,
        "raw_away_probability": probability[:, 0],
        "raw_tie_probability": probability[:, 1],
        "raw_home_probability": probability[:, 2],
    })
    diagnostics = {
        "fitSeconds": fit_seconds,
        "scoreSeconds": time.perf_counter() - scoring_started,
        "residualCalibrationSeason": calibration_season,
        "residualRows": residual_authority.row_count,
        "residualAuthoritySha256": residual_authority.sha256,
        "residualCorrelation": residual_authority.residual_correlation,
        "negativeMeanPredictionsClamped": residual_negative + validation_negative,
        "treatmentState": fitted.transformer.state(),
        "selectedFeatures": list(fitted.feature_names),
    }
    return ledger, diagnostics, fitted


def _pipeline_dir(run_root: Path, pipeline_id: str) -> Path:
    return run_root / "pipelines" / pipeline_id.lower()


def _screen_pipeline(
    pipeline: Mapping[str, Any],
    parameters: Mapping[str, Any],
    development: pd.DataFrame,
    folds: Sequence[Mapping[str, Any]],
    features: Sequence[str],
    run_root: Path,
    *,
    seed: int,
    draws: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    pipeline_id = str(pipeline["id"])
    root = _pipeline_dir(run_root, pipeline_id)
    fold_ledgers: list[pd.DataFrame] = []
    fold_receipts: list[dict[str, Any]] = []
    started = datetime.now(UTC).isoformat()
    for number, fold in enumerate(folds):
        train = development.iloc[np.asarray(fold["trainIndex"], dtype=int)].copy()
        validation = development.iloc[np.asarray(fold["validationIndex"], dtype=int)].copy()
        randoms = make_common_random_numbers(
            n_games=len(validation), draws=draws, seed=seed + number * 100
        )
        ledger, diagnostics, _ = _fit_and_score(
            pipeline, parameters, train, validation, features,
            seed=seed + number * 100, draws=draws, common_random_numbers=randoms,
        )
        ledger.insert(0, "fold_id", str(fold["foldId"]))
        ledger.insert(0, "pipeline_id", pipeline_id)
        ledger_path = root / "folds" / str(fold["foldId"]).lower() / "predictions.parquet"
        ledger_sha = _atomic_parquet(ledger_path, ledger)
        receipt = {
            "foldId": fold["foldId"],
            "trainStart": fold["trainStart"], "trainEnd": fold["trainEnd"],
            "validationStart": fold["validationStart"], "validationEnd": fold["validationEnd"],
            "trainRows": fold["trainRows"], "validationRows": fold["validationRows"],
            "parameters": dict(parameters), "metrics": _metrics(ledger),
            "predictionsPath": str(ledger_path.resolve()), "predictionsSha256": ledger_sha,
            **diagnostics,
        }
        _atomic_json(ledger_path.with_name("receipt.json"), receipt)
        fold_ledgers.append(ledger)
        fold_receipts.append(receipt)
    combined = pd.concat(fold_ledgers, ignore_index=True)
    combined_path = root / "oof_predictions.parquet"
    combined_sha = _atomic_parquet(combined_path, combined)
    summary = {
        "contract": "ASP_NFL_OVERNIGHT_PIPELINE_RESULT_V1",
        "pipelineId": pipeline_id, "family": pipeline["family"],
        "featureVariant": pipeline["features"], "treatment": pipeline["treatment"],
        "reference": bool(pipeline.get("reference", False)),
        "parameters": dict(parameters), "status": "COMPLETED",
        "startedAt": started, "completedAt": datetime.now(UTC).isoformat(),
        "metrics": _metrics(combined), "folds": fold_receipts,
        "oofPredictionsPath": str(combined_path.resolve()), "oofPredictionsSha256": combined_sha,
        "finalOotAccessed": False, "promotionStatus": "NOT_PROMOTED",
    }
    summary["receiptSha256"] = _atomic_json(root / "result.json", summary)
    return combined, summary


def _select_tuning_candidates(results: Sequence[Mapping[str, Any]]) -> list[str]:
    eligible = sorted(
        (item for item in results if item.get("status") == "COMPLETED" and not item.get("reference")),
        key=lambda item: (float(item["metrics"]["multiclassLogLoss"]), str(item["pipelineId"])),
    )
    selected: list[str] = []
    families: set[str] = set()
    for item in eligible:
        if str(item["family"]) in families:
            continue
        selected.append(str(item["pipelineId"]))
        families.add(str(item["family"]))
        if len(selected) == 2:
            break
    return selected


def _tune_pipeline(
    pipeline: Mapping[str, Any],
    grid: Sequence[Mapping[str, Any]],
    development: pd.DataFrame,
    folds: Sequence[Mapping[str, Any]],
    features: Sequence[str],
    run_root: Path,
    *,
    seed: int,
    draws: int,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    tuned_id = f"{pipeline['id']}_TUNED"
    tuned_pipeline = {**pipeline, "id": tuned_id, "reference": False}
    selected_by_fold: list[dict[str, Any]] = []
    ledgers: list[pd.DataFrame] = []
    for number, fold in enumerate(folds):
        outer_train = development.iloc[np.asarray(fold["trainIndex"], dtype=int)].copy()
        outer_validation = development.iloc[np.asarray(fold["validationIndex"], dtype=int)].copy()
        inner_season = int(outer_train["season"].max())
        inner_train = outer_train.loc[outer_train["season"] < inner_season].copy()
        inner_validation = outer_train.loc[outer_train["season"] == inner_season].copy()
        trials: list[dict[str, Any]] = []
        inner_randoms = make_common_random_numbers(
            n_games=len(inner_validation), draws=draws, seed=seed + number * 100 + 50
        )
        for grid_number, parameters in enumerate(grid):
            ledger, _, _ = _fit_and_score(
                pipeline, parameters, inner_train, inner_validation, features,
                seed=seed + number * 100 + grid_number,
                draws=draws, common_random_numbers=inner_randoms,
            )
            trials.append({"parameters": dict(parameters), "metrics": _metrics(ledger)})
        trials.sort(key=lambda item: float(item["metrics"]["multiclassLogLoss"]))
        selected = trials[0]
        outer_randoms = make_common_random_numbers(
            n_games=len(outer_validation), draws=draws, seed=seed + number * 100
        )
        ledger, diagnostics, _ = _fit_and_score(
            tuned_pipeline, selected["parameters"], outer_train, outer_validation, features,
            seed=seed + number * 100, draws=draws, common_random_numbers=outer_randoms,
        )
        ledger.insert(0, "fold_id", str(fold["foldId"]))
        ledger.insert(0, "pipeline_id", tuned_id)
        ledgers.append(ledger)
        selected_by_fold.append({
            "foldId": fold["foldId"], "innerValidationSeason": inner_season,
            "trials": trials, "selectedParameters": selected["parameters"],
            "outerMetrics": _metrics(ledger), **diagnostics,
        })
        fold_path = _pipeline_dir(run_root, tuned_id) / "folds" / str(fold["foldId"]).lower() / "predictions.parquet"
        _atomic_parquet(fold_path, ledger)
        _atomic_json(fold_path.with_name("receipt.json"), selected_by_fold[-1])
    combined = pd.concat(ledgers, ignore_index=True)
    path = _pipeline_dir(run_root, tuned_id) / "oof_predictions.parquet"
    digest = _atomic_parquet(path, combined)
    summary = {
        "contract": "ASP_NFL_OVERNIGHT_TUNED_RESULT_V1", "pipelineId": tuned_id,
        "sourcePipelineId": pipeline["id"], "family": pipeline["family"],
        "featureVariant": pipeline["features"], "treatment": pipeline["treatment"],
        "status": "COMPLETED", "metrics": _metrics(combined), "folds": selected_by_fold,
        "oofPredictionsPath": str(path.resolve()), "oofPredictionsSha256": digest,
        "finalOotAccessed": False, "promotionStatus": "NOT_PROMOTED",
    }
    summary["receiptSha256"] = _atomic_json(_pipeline_dir(run_root, tuned_id) / "result.json", summary)
    return combined, summary


def _chronological_calibration(ledger: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    result = ledger.copy()
    raw_columns = ["raw_away_probability", "raw_tie_probability", "raw_home_probability"]
    for name in ("away", "tie", "home"):
        result[f"calibrated_{name}_probability"] = result[f"raw_{name}_probability"]
    receipts: list[dict[str, Any]] = []
    seasons = sorted(result["season"].astype(int).unique())
    for season in seasons:
        train = result.loc[result["season"] < season]
        score_index = result.index[result["season"] == season]
        if train.empty or train["outcome_class"].nunique() < 3:
            receipts.append({"season": season, "status": "RAW_INSUFFICIENT_EARLIER_OOF"})
            continue
        x_train = np.log(np.clip(train[raw_columns].to_numpy(float), 1e-12, 1.0))
        model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=2_000, random_state=731001)
        model.fit(x_train, train["outcome_class"].to_numpy(int))
        predicted = model.predict_proba(np.log(np.clip(result.loc[score_index, raw_columns].to_numpy(float), 1e-12, 1.0)))
        aligned = np.zeros((len(score_index), 3), dtype=float)
        aligned[:, model.classes_.astype(int)] = predicted
        result.loc[score_index, [
            "calibrated_away_probability", "calibrated_tie_probability", "calibrated_home_probability"
        ]] = aligned
        receipts.append({"season": season, "status": "CALIBRATED", "trainingGames": int(len(train)),
                         "trainingSeasons": sorted(train["season"].astype(int).unique().tolist())})
    comparison = {
        "method": "CHRONOLOGICAL_MULTINOMIAL_LOGIT_ON_LOG_PROBABILITIES",
        "raw": _metrics(result, probability_prefix="raw"),
        "calibrated": _metrics(result, probability_prefix="calibrated"),
        "folds": receipts,
    }
    comparison["selected"] = (
        "REGULARIZED_CALIBRATED" if comparison["calibrated"]["multiclassLogLoss"] < comparison["raw"]["multiclassLogLoss"]
        else "RAW"
    )
    return result, comparison


def _paired_block_uncertainty(
    candidate: pd.DataFrame, reference: pd.DataFrame, *, resamples: int, seed: int
) -> dict[str, Any]:
    keys = ["canonical_game_id", "season", "week"]
    merged = candidate.merge(reference, on=keys, suffixes=("_candidate", "_reference"), validate="one_to_one")
    candidate_probability = merged[[
        "raw_away_probability_candidate", "raw_tie_probability_candidate", "raw_home_probability_candidate"
    ]].to_numpy(float)
    reference_probability = merged[[
        "raw_away_probability_reference", "raw_tie_probability_reference", "raw_home_probability_reference"
    ]].to_numpy(float)
    truth = merged["outcome_class_candidate"].to_numpy(int)
    delta = _loss_vector(candidate_probability, truth) - _loss_vector(reference_probability, truth)
    blocks = (merged["season"].astype(str) + ":" + merged["week"].astype(str)).to_numpy()
    unique = np.unique(blocks)
    rng = np.random.default_rng(seed)
    values = np.empty(resamples, dtype=float)
    for position in range(resamples):
        sampled = rng.choice(unique, size=len(unique), replace=True)
        indices = np.concatenate([np.flatnonzero(blocks == block) for block in sampled])
        values[position] = float(delta[indices].mean())
    return {
        "games": int(len(merged)), "temporalBlocks": int(len(unique)),
        "candidateMinusM1LogLoss": float(delta.mean()),
        "clusterBootstrap95Ci": [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))],
        "resamples": int(resamples), "cluster": "SEASON_WEEK",
    }


def _final_fit_and_reload(
    pipeline: Mapping[str, Any], parameters: Mapping[str, Any], development: pd.DataFrame,
    features: Sequence[str], root: Path, *, seed: int,
) -> dict[str, Any]:
    fitted = _fit_pipeline(pipeline, parameters, development, features, seed=seed)
    artifact = root / "fitted" / f"{str(pipeline['id']).lower()}.joblib"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact.with_name(f".{artifact.name}.{uuid.uuid4().hex}.tmp")
    joblib.dump(fitted, temporary)
    os.replace(temporary, artifact)
    fixture = development.tail(min(16, len(development))).copy()
    expected = fitted.predict(fixture)[:2]
    reloaded = joblib.load(artifact)
    actual = reloaded.predict(fixture)[:2]
    mismatch = max(float(np.max(np.abs(expected[0] - actual[0]))), float(np.max(np.abs(expected[1] - actual[1]))))
    if mismatch != 0.0:
        raise NflOvernightLabError(f"fitted artifact reload mismatch: {mismatch}")
    return {
        "path": str(artifact.resolve()), "sha256": _sha_file(artifact), "bytes": artifact.stat().st_size,
        "trainingRows": int(len(development)), "trainingStart": development["game_date"].min().date().isoformat(),
        "trainingEnd": development["game_date"].max().date().isoformat(),
        "maximumTrainingSeason": int(development["season"].max()), "reloadMaximumAbsoluteMismatch": mismatch,
        "state": fitted.state(),
    }


def _charts(leaderboard: pd.DataFrame, ledgers: Mapping[str, pd.DataFrame], winner: str, root: Path) -> list[dict[str, Any]]:
    chart_root = root / "charts"
    chart_root.mkdir(parents=True, exist_ok=True)
    selected = leaderboard.sort_values("multiclassLogLoss").head(12).iloc[::-1]
    figure, axis = plt.subplots(figsize=(10, 6))
    axis.barh(selected["pipelineId"], selected["multiclassLogLoss"], color="#315f72")
    axis.set_xlabel("Development multiclass log loss (lower is better)")
    figure.tight_layout()
    paths: list[Path] = [chart_root / "leaderboard.png"]
    figure.savefig(paths[-1], dpi=150)
    plt.close(figure)

    winner_ledger = ledgers[winner]
    figure, axis = plt.subplots(figsize=(6, 6))
    probability = winner_ledger["raw_home_probability"].to_numpy(float)
    truth = (winner_ledger["outcome_class"].to_numpy(int) == 2).astype(float)
    groups = pd.qcut(probability, q=min(10, len(np.unique(probability))), duplicates="drop")
    calibration = pd.DataFrame({"p": probability, "y": truth, "bin": groups}).groupby("bin", observed=True).mean()
    axis.plot(calibration["p"], calibration["y"], marker="o")
    axis.plot([0, 1], [0, 1], linestyle="--", color="gray")
    axis.set(xlabel="Mean forecast home-win probability", ylabel="Observed home-win rate", title=winner)
    figure.tight_layout()
    paths.append(chart_root / "winner_calibration.png")
    figure.savefig(paths[-1], dpi=150)
    plt.close(figure)
    return [{"path": str(path.resolve()), "sha256": _sha_file(path), "bytes": path.stat().st_size} for path in paths]


def _market_timing_disposition(authority: Any) -> dict[str, Any]:
    market_path = getattr(authority, "market_path", None)
    if market_path is None or not Path(market_path).exists():
        return {"status": "UNAVAILABLE", "reason": "NO_REGISTERED_MARKET_TABLE"}
    schema = pq.read_schema(market_path)
    names = set(schema.names)
    timing = sorted(names & {"observed_at", "captured_at", "snapshot_at", "evidence_cutoff_at"})
    if not timing:
        return {
            "status": "EXCLUDED_TIMING_UNPROVEN", "reason": "REGISTERED_MARKET_TABLE_HAS_NO_QUOTE_OBSERVATION_TIMESTAMP",
            "path": str(Path(market_path).resolve()), "sha256": _sha_file(Path(market_path)),
        }
    return {
        "status": "AVAILABLE_FOR_REPORTING_ONLY_NOT_USED_AS_PREDICTOR",
        "timingColumns": timing, "path": str(Path(market_path).resolve()), "sha256": _sha_file(Path(market_path)),
    }


def run_overnight_lab(config: LabConfig = LabConfig()) -> dict[str, Any]:
    matrix, matrix_sha = _matrix()
    if config.max_threads > 2 or int(matrix["maximumEstimatorThreads"]) > 2:
        raise NflOvernightLabError("thread authority exceeds two")
    authority, development, features = _load_development(config)
    folds = _folds(development)
    foundation_sha = str(authority.foundation_manifest_sha256)
    run_id = f"matrix-{matrix_sha[:12]}-foundation-{foundation_sha[:12]}"
    run_root = config.external_root / "runs" / run_id
    declaration = {
        "contract": RUN_CONTRACT, "runId": run_id, "matrixPath": str(MATRIX_PATH.resolve()),
        "matrixSha256": matrix_sha, "foundationBundleSha256": foundation_sha,
        "developmentRows": int(len(development)), "developmentSeasons": [1999, 2024],
        "finalOotSeason": 2025, "finalOotAccessed": False, "registeredInputs": len(features),
        "folds": [{key: value for key, value in fold.items() if key not in {"trainIndex", "validationIndex"}} for fold in folds],
        "startedAt": datetime.now(UTC).isoformat(), "status": "RUNNING",
    }
    _atomic_json(run_root / "run_declaration.json", declaration)
    ledgers: dict[str, pd.DataFrame] = {}
    results: list[dict[str, Any]] = []
    with threadpool_limits(limits=config.max_threads):
        for position, pipeline in enumerate(matrix["pipelines"]):
            pipeline_id = str(pipeline["id"])
            existing = _pipeline_dir(run_root, pipeline_id) / "result.json"
            try:
                if existing.exists():
                    result = json.loads(existing.read_text(encoding="utf-8"))
                    ledger = pd.read_parquet(result["oofPredictionsPath"])
                else:
                    parameters = matrix["screeningModels"][pipeline["family"]]
                    ledger, result = _screen_pipeline(
                        pipeline, parameters, development, folds, features, run_root,
                        seed=config.seed + position * 1_000, draws=config.draws,
                    )
                ledgers[pipeline_id] = ledger
                results.append(result)
            except Exception as exc:
                failure = {
                    "pipelineId": pipeline_id, "family": pipeline["family"], "status": "FAILED",
                    "errorType": type(exc).__name__, "error": str(exc), "failedAt": datetime.now(UTC).isoformat(),
                }
                _atomic_json(_pipeline_dir(run_root, pipeline_id) / "failure.json", failure)
                results.append(failure)
        tuning_ids = _select_tuning_candidates(results)
        for position, source_id in enumerate(tuning_ids):
            pipeline = next(item for item in matrix["pipelines"] if item["id"] == source_id)
            tuned_id = f"{source_id}_TUNED"
            existing = _pipeline_dir(run_root, tuned_id) / "result.json"
            try:
                if existing.exists():
                    result = json.loads(existing.read_text(encoding="utf-8"))
                    ledger = pd.read_parquet(result["oofPredictionsPath"])
                else:
                    ledger, result = _tune_pipeline(
                        pipeline, matrix["tuning"]["grids"][pipeline["family"]],
                        development, folds, features, run_root,
                        seed=config.seed + 100_000 + position * 10_000, draws=config.tuning_draws,
                    )
                ledgers[tuned_id] = ledger
                results.append(result)
            except Exception as exc:
                failure = {"pipelineId": tuned_id, "family": pipeline["family"], "status": "FAILED",
                           "errorType": type(exc).__name__, "error": str(exc), "failedAt": datetime.now(UTC).isoformat()}
                _atomic_json(_pipeline_dir(run_root, tuned_id) / "failure.json", failure)
                results.append(failure)

    completed = [item for item in results if item.get("status") == "COMPLETED"]
    if not completed:
        raise NflOvernightLabError("no pipeline completed")
    leaderboard = pd.DataFrame([
        {"pipelineId": item["pipelineId"], "family": item["family"],
         "featureVariant": item.get("featureVariant"), "treatment": item.get("treatment"),
         **item["metrics"]} for item in completed
    ]).sort_values(["multiclassLogLoss", "pipelineId"], kind="stable").reset_index(drop=True)
    winner_id = str(leaderboard.iloc[0]["pipelineId"])
    calibrated, calibration = _chronological_calibration(ledgers[winner_id])
    calibration_path = run_root / "analysis" / "winner_calibrated_oof.parquet"
    calibration_sha = _atomic_parquet(calibration_path, calibrated)
    reference_id = "M1_RECIPE_FOLD_REFIT"
    uncertainty = (
        _paired_block_uncertainty(ledgers[winner_id], ledgers[reference_id],
                                  resamples=config.bootstrap_resamples, seed=config.seed + 500_000)
        if reference_id in ledgers else {"status": "UNAVAILABLE_REFERENCE_FAILED"}
    )
    winner_result = next(item for item in completed if item["pipelineId"] == winner_id)
    source_id = str(winner_result.get("sourcePipelineId", winner_id.removesuffix("_TUNED")))
    source_pipeline = next(item for item in matrix["pipelines"] if item["id"] == source_id)
    if winner_result.get("folds") and "selectedParameters" in winner_result["folds"][-1]:
        final_parameters = winner_result["folds"][-1]["selectedParameters"]
    else:
        final_parameters = winner_result["parameters"]
    final_pipeline = {**source_pipeline, "id": winner_id}
    final_artifact = _final_fit_and_reload(
        final_pipeline, final_parameters, development, features, run_root, seed=config.seed + 900_000
    )
    charts = _charts(leaderboard, ledgers, winner_id, run_root)
    leaderboard_path = run_root / "analysis" / "leaderboard.csv"
    leaderboard_path.parent.mkdir(parents=True, exist_ok=True)
    leaderboard.to_csv(leaderboard_path, index=False)
    market = _market_timing_disposition(authority)
    analysis = {
        "contract": RESULT_CONTRACT, "runId": run_id, "matrixSha256": matrix_sha,
        "foundationBundleSha256": foundation_sha, "developmentRows": int(len(development)),
        "developmentMaximumSeason": 2024, "finalOotSeason": 2025, "finalOotAccessed": False,
        "screeningScheduled": len(matrix["pipelines"]),
        "screeningCompleted": sum(1 for item in results[:len(matrix["pipelines"])] if item.get("status") == "COMPLETED"),
        "tuningSelected": tuning_ids, "pipelines": results, "leaderboard": leaderboard.to_dict("records"),
        "developmentSelectedPipeline": winner_id, "calibration": calibration,
        "calibratedOofPath": str(calibration_path.resolve()), "calibratedOofSha256": calibration_sha,
        "pairedUncertaintyVersusM1": uncertainty, "marketBenchmark": market,
        "fittedDevelopmentArtifact": final_artifact, "charts": charts,
        "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
        "wageringAuthority": False, "executionAllowedInAisp": False,
        "completedAt": datetime.now(UTC).isoformat(),
    }
    analysis_sha = _atomic_json(run_root / "analysis" / "result.json", analysis)
    manifest = {
        "contract": "ASP_NFL_OVERNIGHT_MODEL_LAB_MANIFEST_V1", "runId": run_id,
        "analysisPath": str((run_root / "analysis" / "result.json").resolve()), "analysisSha256": analysis_sha,
        "matrixSha256": matrix_sha, "foundationBundleSha256": foundation_sha,
        "files": [], "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
        "wageringAuthority": False, "executionAllowedInAisp": False,
    }
    for path in sorted(item for item in run_root.rglob("*") if item.is_file() and item.name != "manifest.json"):
        manifest["files"].append({"path": str(path.resolve()), "sha256": _sha_file(path), "bytes": path.stat().st_size})
    manifest_sha = _atomic_json(run_root / "manifest.json", manifest)
    immutable = config.output_root / "sha256" / manifest_sha
    immutable.mkdir(parents=True, exist_ok=True)
    summary = {
        "contract": "ASP_NFL_OVERNIGHT_MODEL_LAB_HANDOFF_V1", "runId": run_id,
        "externalManifestPath": str((run_root / "manifest.json").resolve()), "externalManifestSha256": manifest_sha,
        "analysisSha256": analysis_sha, "matrixSha256": matrix_sha,
        "developmentSelectedPipeline": winner_id, "leaderboard": leaderboard.to_dict("records"),
        "finalOotAccessed": False, "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
        "wageringAuthority": False, "executionAllowedInAisp": False,
    }
    handoff_sha = _atomic_json(immutable / "handoff.json", summary)
    _atomic_json(config.output_root / "current.json", {
        "contract": "ASP_NFL_OVERNIGHT_MODEL_LAB_CURRENT_V1", "handoffPath": str((immutable / "handoff.json").resolve()),
        "handoffSha256": handoff_sha, "manifestSha256": manifest_sha,
    })
    declaration.update({"status": "COMPLETED", "completedAt": datetime.now(UTC).isoformat(),
                        "manifestSha256": manifest_sha, "handoffSha256": handoff_sha})
    _atomic_json(run_root / "run_declaration.json", declaration)
    return {**analysis, "manifestSha256": manifest_sha, "handoffPath": str((immutable / "handoff.json").resolve()),
            "handoffSha256": handoff_sha}
