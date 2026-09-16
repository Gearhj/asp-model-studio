"""Reduced Category-A NBA features from finalized historical game records.

This is deliberately separate from the strict pre-tipoff feature builder. Dates
establish a conservative ordering of recorded games, not when their facts were
published. Admission rights, source lineage and population roles belong to the
caller. This module never certifies historical information availability.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from copy import deepcopy
from datetime import date
import hashlib
import json
import math

import numpy as np
import pandas as pd


EVIDENCE_CLASS = "A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION"
TEAM_FEATURES = (
    "elo", "points_for", "points_allowed", "rolling_points_for", "rolling_points_allowed",
    "prior_points_for", "prior_points_allowed", "rest_days", "rest_known", "back_to_back",
    "games_last_3_days", "games_last_7_days", "games_last_14_days", "season_games_played",
    "prior_season_games", "rolling_games", "current_season_weight", "history_supported", "early_season",
)
FEATURE_COLUMNS = tuple(f"{side}_{field}" for side in ("home", "away") for field in TEAM_FEATURES) + (
    "home_court", "elo_home_win_probability", "league_history_games", "league_mean_home_score",
    "league_mean_away_score", "league_mean_total", "league_mean_home_margin",
) + tuple(f"difference_{field}" for field in ("elo", "points_for", "points_allowed", "rest_days", "games_last_7_days"))

_CONTRACT = {
    "schema": "nba-gen1-historical-reduced-features-v1",
    "evidenceClass": EVIDENCE_CLASS,
    "scope": "Caller-admitted NBA regular-season finalized full-game records including overtime",
    "chronology": "For target date D, use only game_date < D. Emit every target on D before applying any outcome on D. No historical publication time is inferred.",
    "targetExclusion": "One row per stable game identity; the target and all same-day/later games are excluded from its features.",
    "season": "season_end is converted to season start year by subtracting one; source date remains a date without manufactured time or timezone.",
    "sourceAvailability": "Historical source release, acquisition-before-target and revision availability are unverified. Reconstructed inputs are Category A, never B or C.",
    "rolling": "Arithmetic mean of last 20 earlier-date games in current season; points include overtime and are NOT possession-normalized efficiencies.",
    "prior": "Immediately preceding season team scoring/allowance mean shrunk by 10 pseudo-games to that season's earlier-date league team-score mean; absent prior season uses all earlier-date league team-score mean. No league data means NaN.",
    "current": "Current-season rolling mean shrunk by 10 pseudo-games to prior rating, weight n/(n+10), with n capped at 20. Separate counts retain all current and prior season games.",
    "league": "Simple cumulative earlier-date full-game home/away score means; no constant invented for absent history.",
    "elo": {"initial": 1500.0, "k": 20.0, "homeAdvantage": 65.0, "scale": 400.0,
            "seasonRegression": "1500 + (rating-1500)*(2/3)^number_of_elapsed_seasons",
            "update": "Rebuilt from game wins using day-start ratings, full-game overtime win counts as win. Same-day update deltas are summed; source Elo/forecasts are ignored."},
    "rest": "Calendar days between prior recorded game date and target date minus one, minimum zero. Missing prior date yields NaN and rest_known=0.",
    "backToBack": "Prior recorded game is exactly one calendar date earlier; zero with rest_known=0 if unavailable.",
    "density": "Counts of prior recorded games in inclusive date windows [D-3,D), [D-7,D), [D-14,D).",
    "support": "history_supported=1 iff earlier-date current plus immediately prior season games >=5; early_season=1 iff current-season games <10.",
    "homeCourt": "Normal games use source home orientation. Neutral games use publisher focal SIDE1/SIDE2 axes, are ineligible model targets, and remain history with zero Elo home advantage. Home/away league score means exclude neutral axes.",
    "unavailable": ["scheduled_tipoff", "historical_schedule_vintages", "source_release_vintages", "revision_availability",
                    "possessions", "pace", "offensive_efficiency", "defensive_efficiency", "opponent_adjusted_efficiency",
                    "effective_field_goal_percentage", "turnover_rate", "offensive_rebound_rate", "free_throw_rate",
                    "overtime_period_scores", "injuries", "lineups", "expected_starters", "player_strength", "travel", "referees", "market_odds"],
    "numericFeatures": list(FEATURE_COLUMNS),
}


def historical_feature_contract() -> dict:
    result = deepcopy(_CONTRACT)
    raw = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    result["sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def _normalize(games: pd.DataFrame) -> list[dict]:
    required = {"game_id", "season_end", "game_date", "home_team_id", "away_team_id",
                "home_team_code", "away_team_code", "home_score", "away_score"}
    if not isinstance(games, pd.DataFrame) or not required.issubset(games.columns):
        raise ValueError(f"Missing normalized historical fields: {sorted(required.difference(getattr(games, 'columns', [])))}")
    rows, seen = [], set()
    for raw in games.to_dict("records"):
        row = {key: raw[key] for key in required}
        neutral = raw.get("neutral_site", False)
        if not isinstance(neutral, (bool, np.bool_)):
            raise ValueError("neutral_site must be a boolean, never an inferred missing value")
        row["neutral_site"] = bool(neutral)
        expected_orientation = "PUBLISHER_FOCAL_AXIS_NO_HOME_CLAIM" if neutral else "SOURCE_HOME_AWAY"
        if raw.get("orientation", expected_orientation) != expected_orientation:
            raise ValueError("Source orientation must explicitly match neutral-site status")
        row["orientation"] = expected_orientation
        for field in ("game_id", "home_team_id", "away_team_id", "home_team_code", "away_team_code"):
            if pd.isna(row[field]) or not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"{field} must be a nonempty normalized string")
        if row["home_team_id"] == row["away_team_id"]:
            raise ValueError("Home/away identities must differ")
        if row["game_id"] in seen:
            raise ValueError("Duplicate game identity; reconcile identity/date/orientation upstream")
        seen.add(row["game_id"])
        if not isinstance(row["season_end"], (int, np.integer)) or row["season_end"] < 1947:
            raise ValueError("season_end must be an integer NBA season end year")
        row["season_end"] = int(row["season_end"])
        if not isinstance(row["game_date"], str):
            raise ValueError("game_date must be an exact YYYY-MM-DD date; no inferred tipoff")
        try:
            parsed = date.fromisoformat(row["game_date"])
        except ValueError as exc:
            raise ValueError("game_date must be an exact YYYY-MM-DD date") from exc
        if parsed.isoformat() != row["game_date"]:
            raise ValueError("game_date must be an exact YYYY-MM-DD date")
        if parsed.year not in (row["season_end"] - 1, row["season_end"]):
            raise ValueError("Game date is outside its source season years")
        row["date_ordinal"] = parsed.toordinal()
        for side in ("home", "away"):
            value = row[f"{side}_score"]
            if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
                raise ValueError("Final scores must be nonnegative integer counts")
            if not math.isfinite(value) or value < 0 or float(value) != int(value):
                raise ValueError("Final scores must be nonnegative integer counts")
            row[f"{side}_score"] = int(value)
        if row["home_score"] == row["away_score"]:
            raise ValueError("A finalized NBA game cannot be tied")
        rows.append(row)
    rows.sort(key=lambda r: (r["game_date"], r["game_id"]))
    if any(a["season_end"] > b["season_end"] for a, b in zip(rows, rows[1:])):
        raise ValueError("Season/date chronology overlaps; resolve ambiguity before feature construction")
    return rows


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else float("nan")


def _shrink(value: float, count: int, prior: float) -> float:
    if not math.isfinite(prior):
        return value
    if not count or not math.isfinite(value):
        return prior
    return (count * value + 10 * prior) / (count + 10)


def build_historical_features(normalized_games_df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Build one reconstructed feature/label row per admitted finalized game.

    Extra source columns are ignored, particularly supplied Elo values and
    forecasts. This function cannot be used as a prospective forecast runner.
    """
    rows = _normalize(normalized_games_df)
    ratings = defaultdict(lambda: 1500.0)
    team_seasons, team_dates = defaultdict(list), defaultdict(list)
    league_season_points, league_season_counts = defaultdict(float), defaultdict(int)
    output, day_groups = [], defaultdict(list)
    for row in rows:
        day_groups[row["game_date"]].append(row)
    league_count, league_home, league_away, last_season = 0, 0.0, 0.0, None
    oriented_count, oriented_home, oriented_away = 0, 0.0, 0.0
    history_digest = hashlib.sha256()
    latest_date, same_day_repeated_team_dates = None, []
    for day, targets in day_groups.items():
        season = targets[0]["season_end"]
        if any(r["season_end"] != season for r in targets):
            raise ValueError("Different seasons occur on one date; no arbitrary ordering is permitted")
        if last_season is not None and season != last_season:
            factor = (2.0 / 3.0) ** (season - last_season)
            for team in ratings:
                ratings[team] = 1500.0 + (ratings[team] - 1500.0) * factor
        last_season = season
        used_teams = [r[f"{s}_team_id"] for r in targets for s in ("home", "away")]
        repeated = sorted({team for team in used_teams if used_teams.count(team) > 1})
        if repeated:
            same_day_repeated_team_dates.append({"gameDate": day, "teams": repeated})
        for target in targets:
            row = {key: value for key, value in target.items() if key != "date_ordinal"}
            row.update(season=season - 1, evidence_class=EVIDENCE_CLASS,
                       history_latest_game_date=latest_date, history_identity_sha256=history_digest.hexdigest(),
                       league_history_games=league_count, home_court=float(not target["neutral_site"]),
                       target_eligible=not target["neutral_site"])
            row["league_mean_home_score"] = oriented_home / oriented_count if oriented_count else float("nan")
            row["league_mean_away_score"] = oriented_away / oriented_count if oriented_count else float("nan")
            row["league_mean_total"] = row["league_mean_home_score"] + row["league_mean_away_score"]
            row["league_mean_home_margin"] = row["league_mean_home_score"] - row["league_mean_away_score"]
            league_prior = ((league_home + league_away) / (2 * league_count)) if league_count else float("nan")
            if league_season_counts[season - 1]:
                league_prior = league_season_points[season - 1] / league_season_counts[season - 1]
            for side in ("home", "away"):
                team = target[f"{side}_team_id"]
                current, previous = team_seasons[(team, season)], team_seasons[(team, season - 1)]
                rolling = current[-20:]
                prior_for = _shrink(_mean([x[0] for x in previous]), len(previous), league_prior)
                prior_against = _shrink(_mean([x[1] for x in previous]), len(previous), league_prior)
                rolling_for, rolling_against = _mean([x[0] for x in rolling]), _mean([x[1] for x in rolling])
                dates = team_dates[team]
                gap = target["date_ordinal"] - dates[-1] if dates else None
                values = dict(elo=ratings[team], points_for=_shrink(rolling_for, len(rolling), prior_for),
                              points_allowed=_shrink(rolling_against, len(rolling), prior_against),
                              rolling_points_for=rolling_for, rolling_points_allowed=rolling_against,
                              prior_points_for=prior_for, prior_points_allowed=prior_against,
                              rest_days=max(0, gap - 1) if gap is not None else float("nan"),
                              rest_known=int(gap is not None), back_to_back=int(gap == 1),
                              season_games_played=len(current), prior_season_games=len(previous), rolling_games=len(rolling),
                              current_season_weight=len(rolling) / (len(rolling) + 10),
                              history_supported=int(len(current) + len(previous) >= 5), early_season=int(len(current) < 10))
                for window in (3, 7, 14):
                    values[f"games_last_{window}_days"] = len(dates) - bisect_left(dates, target["date_ordinal"] - window)
                row.update({f"{side}_{name}": value for name, value in values.items()})
            home_advantage = 0 if target["neutral_site"] else 65
            row["elo_home_win_probability"] = 1 / (1 + 10 ** (-(row["home_elo"] - row["away_elo"] + home_advantage) / 400))
            for name in ("elo", "points_for", "points_allowed", "rest_days", "games_last_7_days"):
                row[f"difference_{name}"] = row[f"home_{name}"] - row[f"away_{name}"]
            output.append(row)
        # Apply outcomes only after every target on this date has been emitted.
        deltas = defaultdict(float)
        for target in targets:
            home, away = target["home_team_id"], target["away_team_id"]
            home_advantage = 0 if target["neutral_site"] else 65
            probability = 1 / (1 + 10 ** (-(ratings[home] - ratings[away] + home_advantage) / 400))
            delta = 20 * (int(target["home_score"] > target["away_score"]) - probability)
            deltas[home] += delta
            deltas[away] -= delta
            for side, other in (("home", "away"), ("away", "home")):
                team_seasons[(target[f"{side}_team_id"], season)].append((target[f"{side}_score"], target[f"{other}_score"]))
                team_dates[target[f"{side}_team_id"]].append(target["date_ordinal"])
                league_season_points[season] += target[f"{side}_score"]
                league_season_counts[season] += 1
            league_home += target["home_score"]
            league_away += target["away_score"]
            league_count += 1
            if not target["neutral_site"]:
                oriented_home += target["home_score"]
                oriented_away += target["away_score"]
                oriented_count += 1
            identity = {key: target[key] for key in ("game_id", "game_date", "season_end", "home_team_id", "away_team_id", "neutral_site", "orientation")}
            history_digest.update(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        for team, delta in deltas.items():
            ratings[team] += delta
        latest_date = day
    features = pd.DataFrame(output)
    audit = {
        "schema": "nba-gen1-historical-reduced-feature-audit-v1", "evidenceClass": EVIDENCE_CLASS,
        "featureContract": historical_feature_contract(), "games": len(rows), "dates": len(day_groups),
        "populationIdentitySha256": history_digest.hexdigest(), "sameDayTeamAmbiguities": same_day_repeated_team_dates,
        "sourceColumnsConsumed": sorted({"game_id", "season_end", "game_date", "home_team_id", "away_team_id", "home_team_code", "away_team_code", "home_score", "away_score", "neutral_site", "orientation"}),
        "neutralHistoryGames": sum(r["neutral_site"] for r in rows),
        "neutralTargetPolicy": "History only; publisher focal axis is not actual home orientation. No home/away fitting or assessment of these targets.",
        "certifiedHistoricalAvailability": False, "prospectiveEligible": False,
        "actualAcquisitionClock": "Must be retained by the caller in its source receipt; not replaced by synthetic game-relative timestamps.",
        "sameDayRule": "All target features emitted before any same-day result is applied; no assumed within-day order.",
        "unsupportedTargetGames": int((~((features.home_history_supported == 1) & (features.away_history_supported == 1))).sum()) if len(features) else 0,
        "unsupportedFeatures": list(_CONTRACT["unavailable"]),
    }
    return features, audit
