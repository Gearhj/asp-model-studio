"""Separate reduced NBA point/Elo forecast path; no joint simulator or intake.

Actual future schedule and current-history capture evidence are mandatory.
Target features are a direct state snapshot: no invented target final is added.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .authority import RESEARCH_FLAGS, reference, verified_bytes
from .historical_features import _normalize, _mean, _shrink
from .recent_features import FEATURE_COLUMNS, _moments, _mix, _std, recent_feature_contract
from .models import FittedPointModel
from .rest_support import FittedRestPointModel, feature_contract as rest_feature_contract


SCHEMA = "NBA_GEN1_REDUCED_POINT_ELO_FORECAST_V1"
TARGET_KEYS = {"game_id", "source_game_id", "season_end", "game_date", "home_team_id", "away_team_id",
               "home_team_code", "away_team_code", "season_type", "status", "neutral_site",
               "scheduled_tipoff_utc", "source_revision"}


class PointForecastUnavailable(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise PointForecastUnavailable(message)


def _utc(value):
    stamp = pd.Timestamp(value)
    _require(not pd.isna(stamp) and stamp.tzinfo is not None, "Actual timezone-bearing clock required")
    return stamp.tz_convert("UTC")


def _now():
    return pd.Timestamp(datetime.now(timezone.utc))


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _json(bound):
    result = json.loads(verified_bytes(bound))
    _require(isinstance(result, dict), "Bound JSON object required")
    return result


def _same(a, b):
    return a["sha256"] == b["sha256"] and a["bytes"] == b["bytes"]


def _target(target):
    _require(isinstance(target, dict) and set(target) == TARGET_KEYS, "Exact identity-only target fields required; outcomes forbidden")
    _require(target["status"] == "SCHEDULED" and target["season_type"] == "REGULAR" and target["neutral_site"] is False,
             "Only real scheduled, oriented nonneutral regular-season targets are supported")
    _require(isinstance(target["season_end"], int) and not isinstance(target["season_end"], bool), "Integer season end year required")
    for field in ("game_id", "source_game_id", "home_team_id", "away_team_id", "home_team_code", "away_team_code", "source_revision"):
        _require(target[field] is not None and bool(str(target[field]).strip()), f"Missing target {field}")
    _require(target["home_team_id"] != target["away_team_id"], "Target teams must differ")
    day = date.fromisoformat(target["game_date"])
    _require(day.isoformat() == target["game_date"] and day.year in (target["season_end"] - 1, target["season_end"]), "Source game date/season mismatch")
    tipoff = _utc(target["scheduled_tipoff_utc"])
    _require(tipoff.tz_convert("America/New_York").date() == day, "Target game_date must match governed Eastern-calendar date")
    return day, tipoff


def build_target_features(history: pd.DataFrame, target: dict, context_events=()):
    """Snapshot the existing 78-field state using only earlier-date real finals.

    The caller separately binds pre-cutoff acquisition and current membership.
    This function excludes target/same-date/later rows before score validation.
    """
    day, _ = _target(target)
    metadata = history[["game_id", "game_date"]]
    selected = history[metadata.game_id.ne(target["game_id"]) & metadata.game_date.lt(target["game_date"])].copy()
    rows = _normalize(selected)
    season, ordinal = target["season_end"], day.toordinal()
    _require(all(row["season_end"] <= season for row in rows), "Future season entered target history")
    ratings, team_seasons, team_dates = defaultdict(lambda: 1500.0), defaultdict(list), defaultdict(list)
    league_season_points, league_season_counts = defaultdict(float), defaultdict(int)
    league_moments, all_moments = defaultdict(list), []
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["game_date"]].append(row)
    count, home_sum, away_sum, oriented_count, oriented_home, oriented_away = 0, 0.0, 0.0, 0, 0.0, 0.0
    previous_season, digest = None, hashlib.sha256()
    for _, games in grouped.items():
        current_season = games[0]["season_end"]
        if previous_season is not None and previous_season != current_season:
            for team in ratings:
                ratings[team] = 1500.0 + (ratings[team] - 1500.0) * (2 / 3) ** (current_season - previous_season)
        previous_season = current_season
        deltas = defaultdict(float)
        for row in games:
            home, away = row["home_team_id"], row["away_team_id"]
            probability = 1 / (1 + 10 ** (-(ratings[home] - ratings[away] + (0 if row["neutral_site"] else 65)) / 400))
            delta = 20 * (int(row["home_score"] > row["away_score"]) - probability)
            deltas[home] += delta
            deltas[away] -= delta
            for side, other in (("home", "away"), ("away", "home")):
                score, against = row[f"{side}_score"], row[f"{other}_score"]
                team_seasons[(row[f"{side}_team_id"], current_season)].append((score, against))
                team_dates[row[f"{side}_team_id"]].append(row["date_ordinal"])
                league_season_points[current_season] += score
                league_season_counts[current_season] += 1
                moment = np.array([score, against, score - against, score + against], dtype=float)
                league_moments[current_season].append(moment)
                all_moments.append(moment)
            home_sum += row["home_score"]
            away_sum += row["away_score"]
            count += 1
            if not row["neutral_site"]:
                oriented_home += row["home_score"]
                oriented_away += row["away_score"]
                oriented_count += 1
            ident = {name: row[name] for name in ("game_id", "game_date", "season_end", "home_team_id", "away_team_id", "neutral_site", "orientation")}
            digest.update(json.dumps(ident, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        for team, delta in deltas.items():
            ratings[team] += delta
    if previous_season is not None and previous_season != season:
        for team in ratings:
            ratings[team] = 1500.0 + (ratings[team] - 1500.0) * (2 / 3) ** (season - previous_season)
    calendar_dates = {team: dates.copy() for team, dates in team_dates.items()}
    context_ids = set()
    for event in context_events:
        _require(event.get("classification") == "NBA_CUP_FINAL_DATE_ONLY", "Only declared Cup date-only calendar context supported")
        _require(not {"home_score", "away_score", "score1", "score2"}.intersection(event), "Context must never contain outcomes")
        _require(event["game_id"] not in context_ids and event["game_id"] not in set(selected.game_id), "Duplicate calendar-context identity")
        context_ids.add(event["game_id"])
        _require(len(event["team_ids"]) == 2 and len(set(event["team_ids"])) == 2, "Two distinct context teams required")
        if event["game_date"] < target["game_date"]:
            for team in event["team_ids"]:
                calendar_dates.setdefault(team, []).append(date.fromisoformat(event["game_date"]).toordinal())
    for team in calendar_dates:
        calendar_dates[team].sort()
    row = {**target, "season": season - 1, "orientation": "SOURCE_HOME_AWAY", "target_eligible": True,
           "evidence_class": "C_GENUINE_FUTURE_CAPTURE_REQUIRES_BOUND_RECEIPTS",
           "home_court": 1.0, "league_history_games": count,
           "history_latest_game_date": max(grouped, default=None), "history_identity_sha256": digest.hexdigest()}
    row["league_mean_home_score"] = oriented_home / oriented_count if oriented_count else float("nan")
    row["league_mean_away_score"] = oriented_away / oriented_count if oriented_count else float("nan")
    row["league_mean_total"] = row["league_mean_home_score"] + row["league_mean_away_score"]
    row["league_mean_home_margin"] = row["league_mean_home_score"] - row["league_mean_away_score"]
    league_prior = (home_sum + away_sum) / (2 * count) if count else float("nan")
    if league_season_counts[season - 1]:
        league_prior = league_season_points[season - 1] / league_season_counts[season - 1]
    ln, lm, ls = _moments(league_moments[season - 1] or all_moments)
    for side in ("home", "away"):
        team = target[f"{side}_team_id"]
        current, previous = team_seasons[(team, season)], team_seasons[(team, season - 1)]
        rolling = current[-20:]
        pf = _shrink(_mean([x[0] for x in previous]), len(previous), league_prior)
        pa = _shrink(_mean([x[1] for x in previous]), len(previous), league_prior)
        rf, ra = _mean([x[0] for x in rolling]), _mean([x[1] for x in rolling])
        dates = calendar_dates.get(team, [])
        gap = ordinal - dates[-1] if dates else None
        values = dict(elo=ratings[team], points_for=_shrink(rf, len(rolling), pf), points_allowed=_shrink(ra, len(rolling), pa),
                      rolling_points_for=rf, rolling_points_allowed=ra, prior_points_for=pf, prior_points_allowed=pa,
                      rest_days=max(0, gap - 1) if gap is not None else float("nan"), rest_known=int(gap is not None),
                      back_to_back=int(gap == 1), season_games_played=len(current), prior_season_games=len(previous),
                      rolling_games=len(rolling), current_season_weight=len(rolling) / (len(rolling) + 10),
                      history_supported=int(len(current) + len(previous) >= 5), early_season=int(len(current) < 10))
        for window in (3, 7, 14):
            values[f"games_last_{window}_days"] = len(dates) - bisect_left(dates, ordinal - window)
        vectors = lambda pairs: [np.array([a, b, a - b, a + b], dtype=float) for a, b in pairs]
        n, mean, second = _moments(vectors(rolling))
        pn, pm, ps = _moments(vectors(previous))
        pm, ps = _mix(pn, pm, ps, lm, ls)
        mm, ms = _mix(n, mean, second, pm, ps)
        raw_std, mixed_std = _std(mean, second, n >= 2), _std(mm, ms, max(n, pn, ln) >= 2)
        values.update(rolling_margin=mean[2], rolling_total=mean[3], margin=mm[2], total=mm[3],
                      variability_supported=int(max(n, pn) >= 2), prior_fallback_available=int(ln > 0))
        for i, name in enumerate(("points_for", "points_allowed", "margin", "total")):
            values[f"rolling_{name}_std"] = raw_std[i]
            values[f"{name}_std"] = mixed_std[i]
        row.update({f"{side}_{name}": value for name, value in values.items()})
    row["elo_home_win_probability"] = 1 / (1 + 10 ** (-(row["home_elo"] - row["away_elo"] + 65) / 400))
    for name in ("elo", "points_for", "points_allowed", "rest_days", "games_last_7_days"):
        row[f"difference_{name}"] = row[f"home_{name}"] - row[f"away_{name}"]
    frame = pd.DataFrame([row])
    _require(set(FEATURE_COLUMNS) <= set(frame), "Incomplete reduced feature snapshot")
    return frame, {"schema": "nba-gen1-reduced-future-feature-audit-v1", "rawFeatureContract": recent_feature_contract(),
                   "historyGames": len(rows), "historyLatestGameDate": row["history_latest_game_date"],
                   "excludedTargetSameDateOrLaterRows": len(history) - len(selected),
                   "dummyTargetFinalsUsed": False, "contextEvents": len(context_ids),
                   "calendarSemantics": "Eastern source date; all same-date outcomes excluded; rest describes admitted games/context only"}


def build_point_forecast(current_receipt_ref, schedule_ref, coverage_ref, cutoff_utc):
    """Build one honest future point/Elo object; never acquire, simulate or publish."""
    start, cutoff = _now(), _utc(cutoff_utc)
    current, schedule, coverage = _json(current_receipt_ref), _json(schedule_ref), _json(coverage_ref)
    _require(current.get("configurationIdentity") == "NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1", "Current receipt must identify the separate point/Elo combination")
    _require(schedule.get("schema") == "NBA_GEN1_REDUCED_SCHEDULE_EVIDENCE_V1", "Authentic reduced schedule evidence is missing")
    _require(schedule.get("dataClassification") == "REAL_UNSCRAMBLED_GAMES" and schedule.get("reviewedBy"), "Fixture or unreviewed schedule is unavailable")
    target = schedule["target"]
    _, tipoff = _target(target)
    _require(_utc(schedule["capturedAtUtc"]) <= cutoff <= start < tipoff, "Schedule capture/cutoff/creation must precede original tipoff")
    verified_bytes(schedule["sourceObject"])
    _require(schedule.get("rightsEvidence"), "Applicable schedule retrieval/retention/derived-use evidence required")
    for bound in schedule["rightsEvidence"]:
        verified_bytes(bound)
    _require(coverage.get("schema") == "NBA_GEN1_REDUCED_CURRENT_HISTORY_V1" and coverage.get("reviewedBy"), "Named current-history coverage receipt required")
    _require(coverage.get("currentResearchReceiptSha256") == current_receipt_ref["sha256"] and coverage.get("targetGameId") == target["game_id"], "History coverage is not bound to this model/target")
    _require(_utc(coverage["sourceCutoffUtc"]) == cutoff == _utc(coverage["completeThroughUtc"]), "Current membership must be certified through exact forecast cutoff")
    _require(coverage.get("regularSeasonMembershipComplete") is True and coverage.get("missingGameIds") == [], "Missing intervening regular games remain unsupported")
    _require(set(coverage.get("teamIds", [])) == {target["home_team_id"], target["away_team_id"]}, "Both mapped teams require coverage")
    _require(coverage.get("identityReconciled") is True and coverage.get("evidence"), "Source/canonical identities and membership evidence required")
    for bound in coverage["evidence"]:
        verified_bytes(bound)
    history_refs = current["history"]
    _require(_same(coverage["historyPopulation"], history_refs["games"]) and _same(coverage["contextMetadata"], history_refs["contextMetadata"]), "Current-history bytes differ")
    captures = coverage.get("sourceCaptures", [])
    _require(captures and coverage.get("allHistoryRowsCoveredBySourceCaptures") is True, "Every history source requires actual pre-cutoff capture lineage")
    for capture in captures:
        _require(_utc(capture["capturedAtUtc"]) <= cutoff, "History source was captured after cutoff")
        verified_bytes(capture["sourceObject"])
        _require(capture.get("rightsEvidence"), "History source applicable-use evidence required")
        for bound in capture["rightsEvidence"]:
            verified_bytes(bound)
    acquisition = _json(history_refs["acquisition"])
    _require(_utc(acquisition["acquiredAtUtc"]) <= cutoff, "Current acquired history postdates cutoff")
    point_bound, elo_bound = current["models"]["ridge_a100_rest"], current["models"]["elo"]
    for bound in (point_bound, elo_bound):
        _require(bound.get("numericalModules"), "Fitted numerical-code bindings required")
        for module in bound["numericalModules"].values():
            verified_bytes(module)
        _require(bound["trainingLastDate"] < target["game_date"] and target["game_id"] not in bound["trainingGameIds"], "Training must precede and exclude target")
    point = joblib.load(io.BytesIO(verified_bytes(point_bound["artifact"])))
    elo = joblib.load(io.BytesIO(verified_bytes(elo_bound["artifact"])))
    _require(isinstance(point, FittedRestPointModel) and isinstance(elo, FittedPointModel) and elo.family == "elo", "Exact ordinary-rest Ridge and independent Elo artifacts required")
    _require(point.training_identity_sha256 == point_bound["trainingIdentitySha256"] and elo.training_identity_sha256 == elo_bound["trainingIdentitySha256"], "Fitted training identity mismatch")
    _require(point.feature_contract == rest_feature_contract() and point.rest_support == point_bound["restSupport"], "Fitted feature/rest-support contract mismatch")
    history = pd.read_parquet(io.BytesIO(verified_bytes(history_refs["games"])))
    contexts = _json(history_refs["contextMetadata"])
    _require(isinstance(contexts.get("contextOnlyEvents"), list), "Explicit retained calendar-context list required")
    events = contexts["contextOnlyEvents"]
    features, audit = build_target_features(history, target, events)
    _require(bool(features.iloc[0].home_history_supported) and bool(features.iloc[0].away_history_supported), "Both teams require five current/prior-season games")
    scores = point.predict(features)[0]
    _require(np.isfinite(scores).all() and (scores > 0).all(), "Nonpositive/nonfinite point expectation is unsupported; no clipping")
    p_home = float(features.iloc[0].elo_home_win_probability)
    feature_values = {name: float(features.iloc[0][name]) if pd.notna(features.iloc[0][name]) else None for name in FEATURE_COLUMNS}
    completed = _now()
    _require(completed < tipoff, "Forecast finished after original tipoff")
    rest_audit = point.support_audit(features).replace({np.nan: None}).to_dict("records")[0]
    result = {"schema": SCHEMA, "engine": "NBA_GEN1_REDUCED_POINT_WITH_SEPARATE_ELO", "configurationIdentity": current["configurationIdentity"],
              "pointConfigurationIdentity": point.screen_version,
              "game": target, "evidenceClass": "C_GENUINE_PRE_CUTOFF_FORECAST_WITH_CATEGORY_A_TRAINING", "sourceCutoffUtc": cutoff.isoformat(),
              "createdAtUtc": completed.isoformat(), "exportedAtUtc": None, "publishedAtUtc": None,
              "pointExpectations": {"home": float(scores[0]), "away": float(scores[1]), "homeMargin": float(scores[0] - scores[1]), "total": float(scores.sum()), "units": "points including overtime"},
              "winnerProbabilities": {"home": p_home, "away": 1 - p_home, "tie": 0.0, "units": "fractions 0 to 1", "method": "UNCHANGED_CHRONOLOGICAL_ELO_1500_K20_HOME65_SCALE400_SEASON_REGRESSION_TWO_THIRDS"},
              "channelSemantics": "Score means come from ordinary-rest Ridge; win probabilities from separate chronological Elo. They are not derived from one joint population and must not be advertised as a simulated distribution.",
              "distributions": {"status": "UNAVAILABLE", "drawCount": 0, "home": None, "away": None, "total": None, "margin": None, "intervals": None},
              "inputFeatureValues": feature_values, "inputFeatureValuesSha256": _hash(feature_values), "featureAudit": audit, "restSupportAudit": rest_audit,
              "bindings": {"currentResearchReceipt": current_receipt_ref, "schedule": schedule_ref, "historyCoverage": coverage_ref,
                           "pointModelAndPreprocessor": point_bound["artifact"], "eloBenchmarkArtifact": elo_bound["artifact"],
                           "pointTrainingIdentitySha256": point.training_identity_sha256, "featureContractSha256": point.feature_contract_sha256,
                           "historyPopulation": history_refs["games"], "contextMetadata": history_refs["contextMetadata"],
                           "forecastExecutable": reference(Path(__file__))},
              "limitations": ["Historical training was reconstructed from finalized records; original revision vintages are unknown", "No player/lineup/box/possession inputs", "No joint score distribution, overtime adjustment, prediction intervals or simulated tail evidence", "Source captures do not retroactively certify historical pregame information"],
              "authority": dict(RESEARCH_FLAGS)}
    result["forecastId"] = "nba-point:" + _hash({"game": target, "configuration": point.training_identity_sha256, "featureHash": result["inputFeatureValuesSha256"], "cutoff": cutoff.isoformat(), "created": completed.isoformat()})
    return result


def export_point_forecast(forecast, output_directory):
    """Write a new local checksummed research export; no exchange/AISP write."""
    now = _now()
    _require(now < _utc(forecast["game"]["scheduled_tipoff_utc"]), "Export deadline expired")
    exported = dict(forecast, exportedAtUtc=now.isoformat())
    raw = (json.dumps(exported, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    directory = Path(output_directory).resolve() / "sha256" / digest
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "forecast.json"
    path.write_bytes(raw)
    index = {"schema": "NBA_GEN1_REDUCED_POINT_EXPORT_INDEX_V1", "createdAtUtc": _now().isoformat(), "forecast": reference(path), "published": False, "consumerConfirmed": False, "authority": dict(RESEARCH_FLAGS)}
    index_path = directory / "index.json"
    index_path.write_text(json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return reference(index_path)
