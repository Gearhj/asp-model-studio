"""Additive score/date features for the recent Category-A NBA research screen.

These empirical score moments are not possessions, efficiencies or calibrated
forecast distributions. The existing historical feature implementation remains
unchanged. All new target rows precede every outcome update on the same date.
"""
from __future__ import annotations

from collections import defaultdict
from bisect import bisect_left
from copy import deepcopy
from datetime import date
import hashlib
import json

import numpy as np
import pandas as pd

from .historical_features import (
    EVIDENCE_CLASS,
    FEATURE_COLUMNS as HISTORICAL_FEATURE_COLUMNS,
    build_historical_features,
    historical_feature_contract,
)


WINDOW = 20
PRIOR_WEIGHT = 10
_MOMENT_NAMES = ("points_for", "points_allowed", "margin", "total")
ADDED_TEAM_FEATURES = (
    "rolling_margin", "rolling_total", "rolling_points_for_std",
    "rolling_points_allowed_std", "rolling_margin_std", "rolling_total_std",
    "margin", "total", "points_for_std", "points_allowed_std", "margin_std",
    "total_std", "variability_supported", "prior_fallback_available",
)
FEATURE_COLUMNS = HISTORICAL_FEATURE_COLUMNS + tuple(
    f"{side}_{field}" for side in ("home", "away") for field in ADDED_TEAM_FEATURES
)


def recent_feature_contract() -> dict:
    """Return the fixed, independently identified reduced feature declaration."""
    contract = {
        "schema": "nba-gen1-recent-score-date-features-v1",
        "evidenceClass": EVIDENCE_CLASS,
        "parentFeatureContract": historical_feature_contract(),
        "rollingWindowGames": WINDOW,
        "priorPseudoGames": PRIOR_WEIGHT,
        "chronology": "Only game_date < target date; emit all date targets before any outcome update. No observed historical publication time is inferred.",
        "units": "Full-game points including overtime; margin is team points minus opponent points; total is their sum.",
        "rollingMoments": "Last 20 earlier-date current-season team games. Means require one observation; raw population standard deviations (ddof=0) require at least two. Missing values remain NaN.",
        "priorMoments": "Immediately prior-season team first and second score moments shrunk by 10 pseudo-games to that season's earlier-date league team-exposure moments. If prior-season league history is absent, use all earlier-date league team exposures. If team prior is absent, use that league fallback. Neither future seasons nor future dates enter the prior.",
        "currentMoments": "Current rolling first and second moments are shrunk by 10 pseudo-games to prior moments. Standard deviation is sqrt(max(0, shrunk second moment minus squared shrunk mean)). No-history values remain NaN; variance is unavailable when fewer than two genuine supporting exposures exist across current/prior/fallback inputs.",
        "leagueDenominator": "Two team exposures per earlier game, including neutral games. Total appears for each team; margins have opposite signs. This is a team-history prior, not independent additional assessment observations.",
        "counts": "Parent fields retain rolling_games, season_games_played and prior_season_games for each side. variability_supported=1 when rolling or prior team history has at least two games. prior_fallback_available=1 when earlier league moments exist; it does not certify team-level support.",
        "neutralGames": "Preserve parent history-only focal axes and target_eligible=False; score moments use each team's own points and opponent points symmetrically.",
        "sameDayAmbiguity": "Preserve parent sameDayTeamAmbiguities; game-ID order within earlier tied dates is deterministic storage order, not a claimed within-day clock.",
        "dateOnlyContext": "Optional declared NBA_CUP_FINAL_DATE_ONLY events contribute only actual recorded dates to rest/rest_known/back_to_back and 3/7/14-day schedule counts (plus corresponding home-away differences). Their outcomes never enter Elo, score moments, team support counts, fitting or assessment. Same-day dates remain excluded. Historical availability is still unverified.",
        "unavailable": deepcopy(historical_feature_contract()["unavailable"]),
        "addedNumericFeatures": [f"{side}_{field}" for side in ("home", "away") for field in ADDED_TEAM_FEATURES],
        "numericFeatures": list(FEATURE_COLUMNS),
        "fittedTransforms": "None in feature construction; all imputers/scalers/estimators must be fitted only within the caller's earlier-game training fold.",
        "prospectiveEligible": False,
    }
    raw = json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    contract["sha256"] = hashlib.sha256(raw).hexdigest()
    return contract


def _moments(values: list[np.ndarray]) -> tuple[int, np.ndarray, np.ndarray]:
    if not values:
        return 0, np.full(4, np.nan), np.full(4, np.nan)
    array = np.asarray(values, dtype=float)
    return len(array), array.mean(axis=0), np.square(array).mean(axis=0)


def _mix(count: int, mean: np.ndarray, second: np.ndarray,
         prior_mean: np.ndarray, prior_second: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if not np.isfinite(prior_mean).all():
        return mean, second
    if not count:
        return prior_mean, prior_second
    return ((count * mean + PRIOR_WEIGHT * prior_mean) / (count + PRIOR_WEIGHT),
            (count * second + PRIOR_WEIGHT * prior_second) / (count + PRIOR_WEIGHT))


def _std(mean: np.ndarray, second: np.ndarray, available: bool) -> np.ndarray:
    return np.sqrt(np.maximum(0, second - np.square(mean))) if available else np.full(4, np.nan)


def _calendar_context(features: pd.DataFrame, context_events) -> dict:
    """Apply declared date-only calendar evidence without using its outcomes."""
    events, seen = [], set(features.game_id) if len(features) else set()
    allowed_fields = {"game_id", "game_date", "season_end", "team_ids", "classification", "source_row_numbers"}
    for raw in context_events:
        if not isinstance(raw, dict) or set(raw).difference(allowed_fields):
            raise ValueError("Calendar context must contain only declared identity/date metadata, never outcomes")
        if raw.get("classification") != "NBA_CUP_FINAL_DATE_ONLY":
            raise ValueError("Only explicitly declared cup-final date context is supported")
        gid, day, season, teams = raw.get("game_id"), raw.get("game_date"), raw.get("season_end"), raw.get("team_ids")
        if not isinstance(gid, str) or not gid or gid in seen:
            raise ValueError("Context identities must be unique and disjoint from scored game identities")
        if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
            raise ValueError("Context date must be exact YYYY-MM-DD with no manufactured time")
        if isinstance(season, bool) or not isinstance(season, int) or int(day[:4]) not in (season - 1, season):
            raise ValueError("Context date must belong to its integer season end year")
        if (not isinstance(teams, list) or len(teams) != 2 or teams[0] == teams[1]
                or any(not isinstance(team, str) or not team for team in teams)):
            raise ValueError("Context requires two distinct canonical team identities")
        seen.add(gid)
        events.append({"game_id": gid, "game_date": day, "season_end": season,
                       "team_ids": sorted(teams), "classification": raw["classification"]})
    events.sort(key=lambda item: (item["game_date"], item["game_id"]))
    dates = defaultdict(list)
    for row in features.to_dict("records"):
        ordinal = date.fromisoformat(row["game_date"]).toordinal()
        for side in ("home", "away"):
            dates[row[f"{side}_team_id"]].append(ordinal)
    for event in events:
        for team in event["team_ids"]:
            dates[team].append(date.fromisoformat(event["game_date"]).toordinal())
    for team in dates:
        dates[team].sort()
    changed_targets = []
    for index, row in features.iterrows():
        ordinal = date.fromisoformat(row.game_date).toordinal()
        changed = False
        for side in ("home", "away"):
            team_dates = dates[row[f"{side}_team_id"]]
            upper = bisect_left(team_dates, ordinal)
            gap = ordinal - team_dates[upper - 1] if upper else None
            values = {"rest_days": max(0, gap - 1) if gap is not None else float("nan"),
                      "rest_known": int(gap is not None), "back_to_back": int(gap == 1)}
            for window in (3, 7, 14):
                values[f"games_last_{window}_days"] = upper - bisect_left(team_dates, ordinal - window)
            for name, value in values.items():
                column = f"{side}_{name}"
                old = features.at[index, column]
                if not (old == value or (pd.isna(old) and pd.isna(value))):
                    changed = True
                features.at[index, column] = value
        for name in ("rest_days", "games_last_7_days"):
            features.at[index, f"difference_{name}"] = features.at[index, f"home_{name}"] - features.at[index, f"away_{name}"]
        if changed:
            changed_targets.append(row.game_id)
    raw = json.dumps(events, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"events": events, "identitySha256": hashlib.sha256(raw).hexdigest(),
            "changedTargetGameIds": changed_targets, "outcomesConsumed": False,
            "scope": "Date-only rest/schedule context; no Elo, score, support-count or model-target updates"}


def build_recent_features(normalized_games_df: pd.DataFrame, context_events=()) -> tuple[pd.DataFrame, dict]:
    """Augment the unchanged historical frame using only admitted score history.

    Input identity/orientation, neutral policy and date ambiguity validation are
    delegated to the existing builder. Source rating columns are never consumed.
    Caller owns source admission, actual capture lineage and protected roles.
    """
    features, parent_audit = build_historical_features(normalized_games_df)
    team_seasons, league_seasons = defaultdict(list), defaultdict(list)
    league_all: list[np.ndarray] = []
    additions = {}
    for _, targets in features.groupby("game_date", sort=True) if len(features) else []:
        season = int(targets.iloc[0].season_end)
        league_prior = league_seasons[season - 1] or league_all
        league_n, league_mean, league_second = _moments(league_prior)
        for target in targets.to_dict("records"):
            added = {}
            for side in ("home", "away"):
                team = target[f"{side}_team_id"]
                rolling = team_seasons[(team, season)][-WINDOW:]
                previous = team_seasons[(team, season - 1)]
                n, mean, second = _moments(rolling)
                pn, prior_mean, prior_second = _moments(previous)
                prior_mean, prior_second = _mix(pn, prior_mean, prior_second, league_mean, league_second)
                mixed_mean, mixed_second = _mix(n, mean, second, prior_mean, prior_second)
                raw_std = _std(mean, second, n >= 2)
                mixed_std = _std(mixed_mean, mixed_second, max(n, pn, league_n) >= 2)
                values = {"rolling_margin": mean[2], "rolling_total": mean[3],
                          "margin": mixed_mean[2], "total": mixed_mean[3],
                          "variability_supported": int(max(n, pn) >= 2),
                          "prior_fallback_available": int(league_n > 0)}
                for index, name in enumerate(_MOMENT_NAMES):
                    values[f"rolling_{name}_std"] = raw_std[index]
                    values[f"{name}_std"] = mixed_std[index]
                added.update({f"{side}_{name}": values[name] for name in ADDED_TEAM_FEATURES})
            additions[target["game_id"]] = added
        # No target or same-date result is visible until every date row exists.
        for target in targets.to_dict("records"):
            for side, other in (("home", "away"), ("away", "home")):
                score, opponent = target[f"{side}_score"], target[f"{other}_score"]
                values = np.array([score, opponent, score - opponent, score + opponent], dtype=float)
                team_seasons[(target[f"{side}_team_id"], season)].append(values)
                league_seasons[season].append(values)
                league_all.append(values)
    new_columns = [name for name in FEATURE_COLUMNS if name not in HISTORICAL_FEATURE_COLUMNS]
    if len(features):
        added_frame = pd.DataFrame([additions[gid] for gid in features.game_id], index=features.index)
        features = pd.concat((features, added_frame.loc[:, new_columns]), axis=1)
    else:
        for name in new_columns:
            features[name] = pd.Series(dtype=float)
    context_audit = _calendar_context(features, context_events)
    seasons = sorted(int(value) for value in features.season_end.unique()) if len(features) else []
    audit = {
        **deepcopy(parent_audit),
        "schema": "nba-gen1-recent-score-date-feature-audit-v1",
        "parentFeatureAudit": parent_audit,
        "featureContract": recent_feature_contract(),
        "observedSeasonEndYears": seasons,
        "missingSeasonEndYearsWithinRange": sorted(set(range(seasons[0], seasons[-1] + 1)).difference(seasons)) if seasons else [],
        "numericFeatureCount": len(FEATURE_COLUMNS),
        "dateOnlyCalendarContext": context_audit,
        "addedFeatureMissingCounts": {name: int(features[name].isna().sum()) for name in new_columns},
    }
    return features, audit
