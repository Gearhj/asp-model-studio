"""Research-only, partially pooled CFB scoring strength.

The caller owns completion-aware admission and supplies only eligible results at
the prediction origin. This module does not open data, infer availability, fit a
distribution, or interact with a publisher.

For each score, ``score = mu + offense + opponent_defense_allowed + venue_sign*h``.
Positive defense_allowed means conceding more points. Team effects are solved
jointly using a Gaussian MAP objective with unit per-score observation precision.
The prior mean is 2/3 of the preceding season's already-pooled posterior; it is
not shrunk a second time by support. A team absent in the immediately preceding
season has zero prior mean/support, even if it appeared in an older season.

Globals use only earlier complete seasons in the supplied history. They are
pooled score/venue least squares regularized toward 28 and 1.5 with fixed 20 and
40 observation-equivalent precisions. They are identical in the adjusted and
unadjusted ablations. The unadjusted ablation instead estimates separate pooled
own-scoring and own-conceding residual means; prediction uses the same additive
equation. Neither mode clips predictions.
"""

from __future__ import annotations

import math
import hashlib
from collections import OrderedDict
from threading import RLock
from typing import Any

import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.linalg import spsolve
from threadpoolctl import threadpool_limits


SCHEMA = "CFB_OPPONENT_STRENGTH_RESEARCH_V1"
PRIOR_DECAY = 2.0 / 3.0
DYNAMIC_SUPPORT_SCALE = 4.0
DEFAULT_MU = 28.0
DEFAULT_VENUE = 1.5
MU_PRIOR_PRECISION = 20.0
VENUE_PRIOR_PRECISION = 40.0
HISTORY_COLUMNS = ("season", "home_id", "away_id", "home_score", "away_score", "neutral_site")
_PRIOR_CACHE: OrderedDict[tuple, dict[str, dict]] = OrderedDict()
_PRIOR_CACHE_LOCK = RLock()
_PRIOR_CACHE_LIMIT = 128


def clear_strength_cache() -> None:
    """Clear the optional in-process prior-season optimization; no fitted files."""
    with _PRIOR_CACHE_LOCK:
        _PRIOR_CACHE.clear()


def _team_key(value: Any) -> str:
    if value is None or pd.isna(value) or isinstance(value, (bool, np.bool_)):
        raise ValueError("Team identity must be non-null and non-boolean")
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(float(value)):
            raise ValueError("Team identity must be finite")
        return str(int(value)) if float(value).is_integer() else str(value)
    result = str(value).strip()
    if not result:
        raise ValueError("Team identity must be nonempty")
    return result


def _neutral(values: pd.Series) -> np.ndarray:
    # Reject ambiguous strings (bool('False') is True) and missing venue metadata.
    if values.isna().any() or not values.map(lambda v: isinstance(v, (bool, np.bool_, int, np.integer)) and v in (0, 1)).all():
        raise ValueError("neutral_site must contain explicit booleans or integer 0/1")
    return values.to_numpy(dtype=bool)


def _validated_history(history: pd.DataFrame, target_season: int) -> pd.DataFrame:
    missing = set(HISTORY_COLUMNS) - set(history.columns)
    if missing:
        raise ValueError(f"Missing history columns: {sorted(missing)}")
    frame = history.loc[:, list(HISTORY_COLUMNS)].copy()
    seasons = pd.to_numeric(frame["season"], errors="raise")
    if seasons.isna().any() or not np.isfinite(seasons.to_numpy(dtype=float)).all() or not (seasons == np.floor(seasons)).all():
        raise ValueError("Season values must be finite integers")
    frame["season"] = seasons.astype(int)
    if (frame["season"] > target_season).any():
        raise ValueError("History includes a season beyond target_season")
    for column in ("home_id", "away_id"):
        frame[column] = frame[column].map(_team_key)
    if (frame["home_id"] == frame["away_id"]).any():
        raise ValueError("A team cannot play itself")
    for column in ("home_score", "away_score"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
        if not np.isfinite(frame[column]).all() or (frame[column] < 0).any():
            raise ValueError("History scores must be finite and nonnegative")
    frame["neutral_site"] = _neutral(frame["neutral_site"])
    # A stable canonical row order makes an artifact independent of input order.
    return frame.sort_values(list(HISTORY_COLUMNS), kind="stable").reset_index(drop=True)


def _global_parameters(history: pd.DataFrame) -> tuple[float, float]:
    if history.empty:
        return DEFAULT_MU, DEFAULT_VENUE
    home = history["home_score"].to_numpy(dtype=float)
    away = history["away_score"].to_numpy(dtype=float)
    nonneutral = ~history["neutral_site"].to_numpy(dtype=bool)
    mu = (home.sum() + away.sum() + MU_PRIOR_PRECISION * DEFAULT_MU) / (2 * len(history) + MU_PRIOR_PRECISION)
    venue = ((home[nonneutral] - away[nonneutral]).sum() + VENUE_PRIOR_PRECISION * DEFAULT_VENUE) / (2 * nonneutral.sum() + VENUE_PRIOR_PRECISION)
    return float(mu), float(venue)


def _fit_season(current: pd.DataFrame, prior: dict[str, dict], mu: float, venue: float,
                lambda_prior: float, dynamic: bool, opponent_adjusted: bool) -> dict[str, dict]:
    current_ids = set(current["home_id"]) | set(current["away_id"])
    team_ids = sorted(current_ids | set(prior))
    if not team_ids:
        return {}
    positions = {key: i for i, key in enumerate(team_ids)}
    count = len(team_ids)
    home = current["home_id"].map(positions).to_numpy(dtype=int)
    away = current["away_id"].map(positions).to_numpy(dtype=int)
    support = np.bincount(np.concatenate([home, away]), minlength=count)
    precision = lambda_prior / (1.0 + support / DYNAMIC_SUPPORT_SCALE) if dynamic else np.full(count, lambda_prior)
    prior_offense = np.array([PRIOR_DECAY * prior.get(key, {}).get("offense", 0.0) for key in team_ids])
    prior_defense = np.array([PRIOR_DECAY * prior.get(key, {}).get("defense_allowed", 0.0) for key in team_ids])
    venue_sign = (~current["neutral_site"].to_numpy(dtype=bool)).astype(float)
    home_residual = current["home_score"].to_numpy(dtype=float) - mu - venue_sign * venue
    away_residual = current["away_score"].to_numpy(dtype=float) - mu + venue_sign * venue
    if opponent_adjusted and len(current):
        observations = 2 * len(current)
        rows = np.repeat(np.arange(observations), 2)
        own = np.concatenate([home, away])
        opponent = np.concatenate([away, home])
        columns = np.column_stack([own, count + opponent]).reshape(-1)
        design = sparse.coo_matrix((np.ones(len(rows)), (rows, columns)), shape=(observations, 2 * count)).tocsc()
        all_precision = np.concatenate([precision, precision])
        all_prior = np.concatenate([prior_offense, prior_defense])
        lhs = design.T @ design + sparse.diags(all_precision, format="csc")
        rhs = design.T @ np.concatenate([home_residual, away_residual]) + all_precision * all_prior
        # Sparse direct solves avoid a large dense fit and stay within one BLAS thread.
        with threadpool_limits(limits=1):
            effects = np.asarray(spsolve(lhs, rhs))
        offense, defense = effects[:count], effects[count:]
    elif opponent_adjusted:
        offense, defense = prior_offense, prior_defense
    else:
        scoring = np.bincount(home, weights=home_residual, minlength=count) + np.bincount(away, weights=away_residual, minlength=count)
        conceding = np.bincount(away, weights=home_residual, minlength=count) + np.bincount(home, weights=away_residual, minlength=count)
        offense = (scoring + precision * prior_offense) / (support + precision)
        defense = (conceding + precision * prior_defense) / (support + precision)
    return {
        key: {
            "offense": float(offense[i]), "defense_allowed": float(defense[i]),
            "current_support": int(support[i]),
            "prior_support": int(prior.get(key, {}).get("current_support", 0)),
            "prior_offense_mean": float(prior_offense[i]),
            "prior_defense_allowed_mean": float(prior_defense[i]),
            "effective_prior_precision": float(precision[i]),
            # This is diagonal precision share, not a posterior causal attribution.
            "prior_weight": float(precision[i] / (support[i] + precision[i])),
        }
        for i, key in enumerate(team_ids)
    }


def fit_strength(history: pd.DataFrame, target_season: int, lambda_prior: float,
                 dynamic: bool, opponent_adjusted: bool = True) -> dict:
    """Fit recursively from supplied permitted history; return a JSON-safe artifact.

    ``current_support`` counts eligible team games in ``target_season``. Earlier
    seasons are treated as complete *within the caller's admitted population*;
    there is no assertion of historical source availability. ``prior_weight`` is
    lambda_eff/(lambda_eff+n), a diagonal precision diagnostic for the coupled
    fit, not the full multivariate influence of previous-season observations.
    """
    if isinstance(target_season, bool) or not isinstance(target_season, (int, np.integer)):
        raise ValueError("target_season must be an integer")
    if not math.isfinite(float(lambda_prior)) or lambda_prior <= 0:
        raise ValueError("lambda_prior must be positive and finite")
    if not isinstance(dynamic, (bool, np.bool_)) or not isinstance(opponent_adjusted, (bool, np.bool_)):
        raise ValueError("dynamic and opponent_adjusted must be booleans")
    target_season, lambda_prior = int(target_season), float(lambda_prior)
    frame = _validated_history(history, target_season)
    first_season = int(frame["season"].min()) if len(frame) else target_season
    prior: dict[str, dict] = {}
    summaries = []
    teams: dict[str, dict] = {}
    # Cache only complete prior-season fits, never an origin's current-season fit.
    # Keys cover all canonical earlier/current rows and every estimator setting.
    # Cached maps stay private: public artifacts always contain a newly fit map.
    # This cache is an optimization, not a retained-data provenance certificate.
    row_hashes = pd.util.hash_pandas_object(frame, index=False).to_numpy(dtype="<u8")
    for season in range(first_season, target_season + 1):
        earlier = frame.loc[frame["season"] < season]
        current = frame.loc[frame["season"] == season]
        cache_key = (SCHEMA, season, lambda_prior, bool(dynamic), bool(opponent_adjusted),
                     hashlib.sha256(row_hashes[:len(earlier) + len(current)].tobytes()).hexdigest())
        with _PRIOR_CACHE_LOCK:
            cached = _PRIOR_CACHE.get(cache_key) if season < target_season else None
            if cached is not None:
                _PRIOR_CACHE.move_to_end(cache_key)
        if cached is not None:
            teams = cached
        else:
            mu, venue = _global_parameters(earlier)
            teams = _fit_season(current, prior, mu, venue, lambda_prior, bool(dynamic), bool(opponent_adjusted))
            if season < target_season:
                with _PRIOR_CACHE_LOCK:
                    _PRIOR_CACHE[cache_key] = teams
                    _PRIOR_CACHE.move_to_end(cache_key)
                    while len(_PRIOR_CACHE) > _PRIOR_CACHE_LIMIT:
                        _PRIOR_CACHE.popitem(last=False)
        summaries.append({"season": season, "games": len(current), "active_teams": sum(row["current_support"] > 0 for row in teams.values()), "global_fit_games": len(earlier)})
        # Only teams observed in this exact year can seed next year's prior.
        prior = {key: row for key, row in teams.items() if row["current_support"] > 0}
    return {
        "schema": SCHEMA, "classification": "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY",
        "target_season": target_season, "lambda_prior": lambda_prior,
        "dynamic": bool(dynamic), "opponent_adjusted": bool(opponent_adjusted),
        "prior_decay": PRIOR_DECAY, "dynamic_support_scale": DYNAMIC_SUPPORT_SCALE,
        "mu": mu, "venue": venue,
        "global_prior": {"mu": DEFAULT_MU, "venue": DEFAULT_VENUE, "mu_precision": MU_PRIOR_PRECISION, "venue_precision": VENUE_PRIOR_PRECISION},
        "global_fit_games": int((frame["season"] < target_season).sum()),
        "fit_games": len(frame), "current_fit_games": int((frame["season"] == target_season).sum()),
        "train_season_max": int(frame["season"].max()) if len(frame) else None,
        "prior_weight_definition": "lambda_effective / (lambda_effective + current_team_games); diagonal precision share only",
        "season_fit_summary": summaries, "teams": teams,
    }


def predict_strength(artifact: dict, targets: pd.DataFrame) -> pd.DataFrame:
    """Predict means and support diagnostics without inspecting target outcomes.

    Unknown teams have zero effects/prior support/current support. Inputs are
    never mutated. The returned frame has the same index and row order as targets.
    """
    if artifact.get("schema") != SCHEMA:
        raise ValueError("Unsupported strength artifact")
    if not {"home_id", "away_id", "neutral_site"}.issubset(targets.columns):
        raise ValueError("Targets require home_id, away_id and neutral_site")
    if "season" in targets and not (targets["season"] == artifact["target_season"]).all():
        raise ValueError("Target seasons must match the fitted target_season")
    home_keys, away_keys = targets["home_id"].map(_team_key), targets["away_id"].map(_team_key)
    if (home_keys == away_keys).any():
        raise ValueError("A team cannot play itself")
    neutral = _neutral(targets["neutral_site"])
    unseen = {"offense": 0.0, "defense_allowed": 0.0, "current_support": 0, "prior_support": 0,
              "effective_prior_precision": artifact["lambda_prior"], "prior_weight": 1.0}
    result = pd.DataFrame(index=targets.index)
    for side, keys in (("home", home_keys), ("away", away_keys)):
        rows = [artifact["teams"].get(key, unseen) for key in keys]
        for field in ("offense", "defense_allowed", "current_support", "prior_support", "effective_prior_precision", "prior_weight"):
            result[f"{side}_{field}"] = [row[field] for row in rows]
    advantage = (~neutral).astype(float) * artifact["venue"]
    result["strength_pred_home"] = artifact["mu"] + result["home_offense"] + result["away_defense_allowed"] + advantage
    result["strength_pred_away"] = artifact["mu"] + result["away_offense"] + result["home_defense_allowed"] - advantage
    result["strength_pred_margin"] = result["strength_pred_home"] - result["strength_pred_away"]
    result["strength_pred_total"] = result["strength_pred_home"] + result["strength_pred_away"]
    return result
