"""Chronological ridge two-way pass/rush team effects for NFL research.

The module is pure with respect to storage and networks. Callers must supply
prior-only team-game rows and a target origin. Missing unit observations are
excluded rather than replaced with zero.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge


REQUIRED_SOURCE_COLUMNS = (
    "canonical_game_id", "season", "week", "game_date", "team_id",
    "opponent_team_id", "is_home",
)
UNIT_RESPONSES = {"pass": "pass_epa_per_play", "rush": "rush_epa_per_play"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _feature_dict(team: str, opponent: str, season: int, is_home: bool) -> dict[str, float]:
    return {
        f"offense={team}": 1.0,
        f"defense={opponent}": 1.0,
        f"season={int(season)}": 1.0,
        "offense_is_home": float(bool(is_home)),
    }


@dataclass(frozen=True)
class EffectConfig:
    ridge_alpha: float
    season_decay: float
    support_prior_games: float = 8.0

    def __post_init__(self) -> None:
        if self.ridge_alpha <= 0 or not 0 < self.season_decay <= 1 or self.support_prior_games <= 0:
            raise ValueError("invalid schedule-adjusted effect configuration")

    @property
    def identity(self) -> str:
        payload = {
            "family": "RIDGE_TWO_WAY_TEAM_EFFECTS_V1",
            "ridgeAlpha": self.ridge_alpha,
            "seasonDecay": self.season_decay,
            "supportPriorGames": self.support_prior_games,
        }
        return "nfl-team-effects:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


@dataclass
class FittedUnitEffects:
    unit: str
    response: str
    target_season: int
    config: EffectConfig
    vectorizer: DictVectorizer
    model: Ridge
    current_support: Mapping[str, int]
    weighted_support: Mapping[str, float]
    latest_source_game_date: str
    latest_source_game_id: str
    training_population_sha256: str
    residual_scale: float

    def coefficient(self, namespace: str, team: str) -> float:
        name = f"{namespace}={team}"
        position = self.vectorizer.vocabulary_.get(name)
        return 0.0 if position is None else float(self.model.coef_[position])

    @property
    def home_effect(self) -> float:
        position = self.vectorizer.vocabulary_.get("offense_is_home")
        return 0.0 if position is None else float(self.model.coef_[position])

    def environment(self, season: int) -> float:
        position = self.vectorizer.vocabulary_.get(f"season={int(season)}")
        return float(self.model.intercept_) + (0.0 if position is None else float(self.model.coef_[position]))

    def predict(self, team: str, opponent: str, *, is_home: bool, season: int) -> float:
        matrix = self.vectorizer.transform([_feature_dict(team, opponent, season, is_home)])
        return float(self.model.predict(matrix)[0])

    def team_support(self, team: str) -> dict[str, float | int | str]:
        current = int(self.current_support.get(team, 0))
        weighted = float(self.weighted_support.get(team, 0.0))
        return {
            "current": current,
            "weighted": weighted,
            "shrinkageWeight": current / (current + self.config.support_prior_games),
            "uncertaintyProxy": 1.0 / math.sqrt(weighted + 1.0),
            "status": "OBSERVED_CURRENT_SEASON" if current else "LEAGUE_SHRUNK_NO_CURRENT_SEASON_EVIDENCE",
        }


def fit_unit_effects(
    source: pd.DataFrame,
    *,
    unit: str,
    target_season: int,
    origin_date: pd.Timestamp,
    config: EffectConfig,
) -> FittedUnitEffects:
    """Fit one unit using source rows already eligible before the origin."""
    if unit not in UNIT_RESPONSES:
        raise ValueError(f"unsupported unit: {unit}")
    response = UNIT_RESPONSES[unit]
    missing = sorted(set(REQUIRED_SOURCE_COLUMNS + (response,)) - set(source.columns))
    if missing:
        raise ValueError(f"source missing columns: {missing}")
    z = source.copy()
    z["game_date"] = pd.to_datetime(z["game_date"], utc=True, errors="raise")
    origin = pd.Timestamp(origin_date)
    if origin.tzinfo is None:
        origin = origin.tz_localize("UTC")
    else:
        origin = origin.tz_convert("UTC")
    if not z.empty and not z["game_date"].lt(origin).all():
        raise ValueError("source contains a target-date or future game")
    z[response] = pd.to_numeric(z[response], errors="coerce")
    z = z[z[response].notna()].sort_values(["game_date", "canonical_game_id", "team_id"]).reset_index(drop=True)
    if z.empty:
        raise ValueError(f"no eligible {unit} observations")
    if (z["season"].astype(int) > int(target_season)).any():
        raise ValueError("source contains a later season")
    rows = [
        _feature_dict(str(r.team_id), str(r.opponent_team_id), int(r.season), bool(r.is_home))
        for r in z.itertuples(index=False)
    ]
    vectorizer = DictVectorizer(sparse=True, sort=True)
    matrix = vectorizer.fit_transform(rows)
    weights = np.power(config.season_decay, int(target_season) - z["season"].to_numpy(int))
    model = Ridge(alpha=config.ridge_alpha, fit_intercept=True, solver="lsqr", tol=1e-10)
    y = z[response].to_numpy(float)
    model.fit(matrix, y, sample_weight=weights)
    fitted = np.asarray(model.predict(matrix), dtype=float)
    current = z["season"].astype(int).eq(int(target_season))
    current_support = z[current].groupby("team_id", observed=True).size().astype(int).to_dict()
    weighted_support = pd.Series(weights, index=z.index).groupby(z["team_id"], observed=True).sum().to_dict()
    population_rows = [
        [str(r.canonical_game_id), int(r.season), int(r.week), str(r.team_id),
         str(r.opponent_team_id), bool(r.is_home), float(getattr(r, response))]
        for r in z.itertuples(index=False)
    ]
    population = {
        "unit": unit,
        "targetSeason": int(target_season),
        "origin": origin.isoformat(),
        "config": config.identity,
        "rows": population_rows,
    }
    latest = z.iloc[-1]
    return FittedUnitEffects(
        unit=unit,
        response=response,
        target_season=int(target_season),
        config=config,
        vectorizer=vectorizer,
        model=model,
        current_support=current_support,
        weighted_support=weighted_support,
        latest_source_game_date=str(latest["game_date"].isoformat()),
        latest_source_game_id=str(latest["canonical_game_id"]),
        training_population_sha256=hashlib.sha256(_canonical_bytes(population)).hexdigest(),
        residual_scale=float(np.sqrt(np.average((y - fitted) ** 2, weights=weights))),
    )


def build_game_effect_features(
    home_team: str,
    away_team: str,
    season: int,
    pass_fit: FittedUnitEffects,
    rush_fit: FittedUnitEffects,
) -> dict[str, Any]:
    if pass_fit.target_season != int(season) or rush_fit.target_season != int(season):
        raise ValueError("fit target season does not match game season")
    out: dict[str, Any] = {}
    for unit, fitted in (("pass", pass_fit), ("rush", rush_fit)):
        home_off = fitted.coefficient("offense", home_team)
        away_def = fitted.coefficient("defense", away_team)
        away_off = fitted.coefficient("offense", away_team)
        home_def = fitted.coefficient("defense", home_team)
        environment = fitted.environment(season)
        home_matchup = fitted.predict(home_team, away_team, is_home=True, season=season)
        away_matchup = fitted.predict(away_team, home_team, is_home=False, season=season)
        out.update({
            f"home_{unit}_offense_effect": home_off,
            f"away_{unit}_defense_effect": away_def,
            f"away_{unit}_offense_effect": away_off,
            f"home_{unit}_defense_effect": home_def,
            f"{unit}_season_environment": environment,
            f"{unit}_home_venue_effect": fitted.home_effect,
            f"home_{unit}_matchup_estimate": home_matchup,
            f"away_{unit}_matchup_estimate": away_matchup,
            f"home_{unit}_matchup_advantage": home_matchup - environment,
            f"away_{unit}_matchup_advantage": away_matchup - environment,
            f"{unit}_matchup_difference": home_matchup - away_matchup,
            f"{unit}_residual_scale": fitted.residual_scale,
            f"{unit}_latest_source_game_date": fitted.latest_source_game_date,
            f"{unit}_latest_source_game_id": fitted.latest_source_game_id,
            f"{unit}_training_population_sha256": fitted.training_population_sha256,
        })
        for side, team in (("home", home_team), ("away", away_team)):
            support = fitted.team_support(team)
            out[f"{side}_{unit}_current_support"] = support["current"]
            out[f"{side}_{unit}_weighted_support"] = support["weighted"]
            out[f"{side}_{unit}_shrinkage_weight"] = support["shrinkageWeight"]
            out[f"{side}_{unit}_uncertainty_proxy"] = support["uncertaintyProxy"]
            out[f"{side}_{unit}_support_status"] = support["status"]
    out["estimator_configuration_id"] = pass_fit.config.identity
    return out


PASS_PREDICTORS = tuple(
    name for name in (
        "home_pass_offense_effect", "away_pass_defense_effect",
        "away_pass_offense_effect", "home_pass_defense_effect",
        "pass_season_environment", "pass_home_venue_effect",
        "home_pass_matchup_estimate", "away_pass_matchup_estimate",
        "home_pass_matchup_advantage", "away_pass_matchup_advantage",
        "pass_matchup_difference", "pass_residual_scale",
        "home_pass_current_support", "away_pass_current_support",
        "home_pass_weighted_support", "away_pass_weighted_support",
        "home_pass_shrinkage_weight", "away_pass_shrinkage_weight",
        "home_pass_uncertainty_proxy", "away_pass_uncertainty_proxy",
    )
)
RUSH_PREDICTORS = tuple(name.replace("pass", "rush") for name in PASS_PREDICTORS)
