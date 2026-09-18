"""Governed SportsDataverse/hoopR NBA team-box population and features.

This module is deliberately source-local and has no network or publication
interface.  The supplied acquisition receipt binds the private raw objects.
Historical rows are finalized-record reconstruction: date ordering prevents
target leakage, but does not certify the original source publication vintage.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

import numpy as np
import pandas as pd


ALIAS_TO_GEN1 = {
    "BKN": "BRK", "CHA": "CHO", "GS": "GSW", "NO": "NOP",
    "NY": "NYK", "PHX": "PHO", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS",
}
NBA_TEAM_CODES = frozenset({
    "ATL", "BOS", "BRK", "CHI", "CHO", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
})
REQUIRED_BOX = {
    "game_id", "season", "season_type", "game_date", "team_id",
    "team_home_away", "team_score", "opponent_team_id", "opponent_team_score",
    "field_goals_made", "field_goals_attempted", "three_point_field_goals_made",
    "three_point_field_goals_attempted", "free_throws_made", "free_throws_attempted",
    "offensive_rebounds", "defensive_rebounds", "total_rebounds", "turnovers",
    "team_abbreviation", "opponent_team_abbreviation",
}
REQUIRED_SCHEDULE = {
    "game_id", "season", "season_type", "game_date", "status_period",
    "status_type_completed", "home_id", "away_id", "home_score", "away_score",
}
BOX_METRICS = (
    "possessions", "pace48", "off_rating", "def_rating", "efg", "opp_efg",
    "tov_rate", "opp_tov_rate", "oreb_rate", "opp_oreb_rate", "ft_rate",
    "opp_ft_rate", "three_attempt_rate", "opp_three_attempt_rate",
    "three_accuracy", "opp_three_accuracy",
)
SUMMARY_FORMS = ("shrunk", "rolling10", "ewm")
PRIOR_WEIGHT = 10.0
EWM_ALPHA = 0.15


class TeamBoxIntegrityError(ValueError):
    """The retained source cannot support the governed population."""


def _hash_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _line_score_values(raw: Any) -> list[int]:
    if raw is None or (isinstance(raw, float) and np.isnan(raw)):
        return []
    return [int(round(float(value))) for value in
            re.findall(r"['\"]value['\"]\s*:\s*(-?\d+(?:\.\d+)?)", str(raw))]


def _safe_divide(numerator, denominator):
    numerator, denominator = np.asarray(numerator, float), np.asarray(denominator, float)
    return np.divide(numerator, denominator, out=np.full_like(numerator, np.nan), where=denominator > 0)


@dataclass(frozen=True)
class GovernedPopulation:
    team_rows: pd.DataFrame
    games: pd.DataFrame
    overtime_periods: pd.DataFrame
    audit: dict[str, Any]


def load_governed_population(receipt_path: str | Path, *,
                             excluded_integrity_game_ids: tuple[str, ...] = ()) -> GovernedPopulation:
    """Verify retained bytes and build regular/playoff oriented team-game rows."""
    receipt_path = Path(receipt_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("provider") != "SportsDataverse/hoopR-nba-data" or receipt.get("license") != "CC BY 4.0":
        raise TeamBoxIntegrityError("Unexpected source or license binding")
    if receipt.get("nbaComRequests") != 0 or receipt.get("costUsd") != 0:
        raise TeamBoxIntegrityError("Source receipt violates the authorized source/cost boundary")
    requests = receipt.get("requests", [])
    if len(requests) != 16 or sum(item.get("kind") == "team_box" for item in requests) != 8 \
            or sum(item.get("kind") == "schedule" for item in requests) != 8:
        raise TeamBoxIntegrityError("Expected eight team-box and eight schedule objects")

    boxes, schedules, object_rows = [], [], []
    for item in requests:
        path = Path(item["path"])
        physical = _hash_file(path)
        if physical != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise TeamBoxIntegrityError(f"Raw-object integrity mismatch: {path.name}")
        frame = pd.read_parquet(path)
        required = REQUIRED_BOX if item["kind"] == "team_box" else REQUIRED_SCHEDULE
        missing = sorted(required.difference(frame.columns))
        if missing:
            raise TeamBoxIntegrityError(f"{path.name} missing required fields {missing}")
        frame = frame.copy()
        frame["source_object_sha256"] = physical
        frame["source_retrieved_at_utc"] = item["retrievedAtUtc"]
        frame["source_season_end"] = int(item["seasonEndYear"])
        (boxes if item["kind"] == "team_box" else schedules).append(frame)
        object_rows.append({"kind": item["kind"], "seasonEndYear": int(item["seasonEndYear"]),
                            "sha256": physical, "bytes": int(item["bytes"]),
                            "schemaFingerprint": item["schemaFingerprint"],
                            "rows": int(len(frame))})

    box = pd.concat(boxes, ignore_index=True)
    schedule = pd.concat(schedules, ignore_index=True)
    box["game_id"] = box.game_id.astype(str)
    schedule["game_id"] = schedule.game_id.astype(str)
    box["game_date"] = pd.to_datetime(box.game_date).dt.date.astype(str)
    schedule["game_date"] = pd.to_datetime(schedule.game_date).dt.date.astype(str)

    duplicate_team_keys = int(box.duplicated(["game_id", "team_id"], keep=False).sum())
    if duplicate_team_keys:
        raise TeamBoxIntegrityError("Duplicate team-game identities")
    counts = box.groupby("game_id").size()
    invalid_grain = counts[counts != 2]
    if len(invalid_grain):
        raise TeamBoxIntegrityError("A retained box game does not have exactly two team rows")
    if box[list(REQUIRED_BOX - {"game_id", "season", "season_type", "game_date", "team_home_away",
                                "team_abbreviation", "opponent_team_abbreviation"})].isna().any().any():
        raise TeamBoxIntegrityError("Required box components contain missing values")

    paired = box[["game_id", "team_id", "team_score"]].rename(
        columns={"team_id": "opponent_team_id_check", "team_score": "opponent_score_check"})
    joined = box.merge(paired, left_on=["game_id", "opponent_team_id"],
                       right_on=["game_id", "opponent_team_id_check"], how="left", validate="many_to_one")
    orphan_joins = int(joined.opponent_team_id_check.isna().sum())
    opponent_score_failures = int((joined.opponent_team_score != joined.opponent_score_check).sum())
    if orphan_joins or opponent_score_failures:
        raise TeamBoxIntegrityError("Opponent joins or opponent scores do not reconcile")

    formula_failure_mask = (box.team_score !=
        2 * box.field_goals_made + box.three_point_field_goals_made + box.free_throws_made)
    formula_failure_ids = sorted(box.loc[formula_failure_mask, "game_id"].astype(str).unique())
    declared_exclusions = sorted(set(str(value) for value in excluded_integrity_game_ids))
    if formula_failure_ids != declared_exclusions:
        raise TeamBoxIntegrityError(
            "Traditional box score formula failures must exactly equal the predeclared integrity quarantine")
    score_formula_failures = int(formula_failure_mask.sum())
    if declared_exclusions:
        box = box[~box.game_id.isin(declared_exclusions)].copy()
        joined = joined[~joined.game_id.isin(declared_exclusions)].copy()
        counts = box.groupby("game_id").size()
        home = box[box.team_home_away.astype(str).str.lower().eq("home")]
        away = box[box.team_home_away.astype(str).str.lower().eq("away")]
    normalized_team = box.team_abbreviation.replace(ALIAS_TO_GEN1)
    normalized_opponent = box.opponent_team_abbreviation.replace(ALIAS_TO_GEN1)
    nonfranchise_game_ids = sorted(box.loc[
        ~normalized_team.isin(NBA_TEAM_CODES) | ~normalized_opponent.isin(NBA_TEAM_CODES), "game_id"
    ].astype(str).unique())
    if nonfranchise_game_ids:
        box = box[~box.game_id.isin(nonfranchise_game_ids)].copy()
        joined = joined[~joined.game_id.isin(nonfranchise_game_ids)].copy()
        counts = box.groupby("game_id").size()
    home = box[box.team_home_away.astype(str).str.lower().eq("home")]
    away = box[box.team_home_away.astype(str).str.lower().eq("away")]
    if len(home) != len(counts) or len(away) != len(counts):
        raise TeamBoxIntegrityError("Participant orientation is incomplete")

    schedule_completed = schedule[schedule.status_type_completed.fillna(False).astype(bool)].copy()
    schedule_completed = schedule_completed.drop_duplicates("game_id", keep="last")
    merged = box.merge(schedule_completed, on="game_id", how="left", suffixes=("", "_schedule"),
                       validate="many_to_one")
    orphan_schedule = int(merged.status_type_completed.isna().sum())
    if orphan_schedule:
        raise TeamBoxIntegrityError("Completed box rows lack matching completed schedule identities")
    if (merged.game_date != merged.game_date_schedule).any():
        raise TeamBoxIntegrityError("Box and schedule game dates disagree")
    if ((merged.season != merged.season_schedule) | (merged.season_type != merged.season_type_schedule)).any():
        raise TeamBoxIntegrityError("Box and schedule season identities disagree")
    if (merged.status_period < 4).any():
        raise TeamBoxIntegrityError("A completed admitted NBA box has fewer than four periods")
    merged["overtime_periods"] = (merged.status_period.astype(int) - 4).clip(lower=0)
    merged["team_minutes_derived"] = 240 + 25 * merged.overtime_periods
    merged["minutes_provenance"] = "DERIVED_FROM_COMPLETED_SCHEDULE_STATUS_PERIOD"
    merged["component_rebounds"] = merged.offensive_rebounds + merged.defensive_rebounds
    merged["team_rebound_difference"] = merged.total_rebounds - merged.component_rebounds

    # Two-row game possession estimate. OREB/DREB are used directly; the
    # source-defined total_rebounds field is preserved and never substituted.
    merged["team_possession_component"] = (
        merged.field_goals_attempted + 0.44 * merged.free_throws_attempted
        - merged.offensive_rebounds + merged.turnovers)
    merged["possessions"] = merged.groupby("game_id").team_possession_component.transform("mean")
    merged["pace48"] = merged.possessions * 48.0 / (merged.team_minutes_derived / 5.0)
    merged["off_rating"] = 100 * _safe_divide(merged.team_score, merged.possessions)
    merged["def_rating"] = 100 * _safe_divide(merged.opponent_team_score, merged.possessions)
    merged["efg"] = _safe_divide(merged.field_goals_made + 0.5 * merged.three_point_field_goals_made,
                                  merged.field_goals_attempted)
    denominator = merged.field_goals_attempted + 0.44 * merged.free_throws_attempted + merged.turnovers
    merged["tov_rate"] = _safe_divide(merged.turnovers, denominator)
    opponent = merged[["game_id", "team_id", "defensive_rebounds", "efg", "tov_rate",
                       "offensive_rebounds", "field_goals_attempted", "free_throws_attempted",
                       "three_point_field_goals_attempted", "three_point_field_goals_made"]].rename(columns={
        "team_id": "opponent_team_id_metric", "defensive_rebounds": "opponent_dreb",
        "efg": "opp_efg", "tov_rate": "opp_tov_rate", "offensive_rebounds": "opp_oreb",
        "field_goals_attempted": "opp_fga", "free_throws_attempted": "opp_fta",
        "three_point_field_goals_attempted": "opp_3pa", "three_point_field_goals_made": "opp_3pm"})
    merged = merged.merge(opponent, left_on=["game_id", "opponent_team_id"],
                          right_on=["game_id", "opponent_team_id_metric"], validate="many_to_one")
    merged["oreb_rate"] = _safe_divide(merged.offensive_rebounds,
                                        merged.offensive_rebounds + merged.opponent_dreb)
    merged["opp_oreb_rate"] = _safe_divide(merged.opp_oreb, merged.opp_oreb + merged.defensive_rebounds)
    merged["ft_rate"] = _safe_divide(merged.free_throws_attempted, merged.field_goals_attempted)
    merged["opp_ft_rate"] = _safe_divide(merged.opp_fta, merged.opp_fga)
    merged["three_attempt_rate"] = _safe_divide(merged.three_point_field_goals_attempted,
                                                 merged.field_goals_attempted)
    merged["opp_three_attempt_rate"] = _safe_divide(merged.opp_3pa, merged.opp_fga)
    merged["three_accuracy"] = _safe_divide(merged.three_point_field_goals_made,
                                             merged.three_point_field_goals_attempted)
    merged["opp_three_accuracy"] = _safe_divide(merged.opp_3pm, merged.opp_3pa)

    # Extract each observed overtime period as one oriented complete pair.
    periods = []
    for row in schedule_completed.loc[schedule_completed.status_period > 4].itertuples():
        if not hasattr(row, "home_linescores") or not hasattr(row, "away_linescores"):
            continue
        hvals, avals = _line_score_values(row.home_linescores), _line_score_values(row.away_linescores)
        expected = int(row.status_period)
        if len(hvals) < expected or len(avals) < expected:
            continue
        for period in range(4, expected):
            periods.append({"game_id": str(row.game_id), "game_date": str(row.game_date),
                            "season_end": int(row.season), "period": period + 1,
                            "home_points": int(hvals[period]), "away_points": int(avals[period])})
    overtime = pd.DataFrame(periods)

    game_home = merged[merged.team_home_away.astype(str).str.lower().eq("home")].copy()
    game_home["home_team_code"] = game_home.team_abbreviation.replace(ALIAS_TO_GEN1)
    game_home["away_team_code"] = game_home.opponent_team_abbreviation.replace(ALIAS_TO_GEN1)
    game_home["home_score"] = game_home.team_score.astype(int)
    game_home["away_score"] = game_home.opponent_team_score.astype(int)
    game_home["role"] = np.select([game_home.season_type.eq(2), game_home.season_type.eq(3)],
                                   ["REGULAR_SEASON", "PLAYOFFS"], default="OTHER_EXCLUDED")
    identity_fields = game_home[["game_id", "game_date", "season", "season_type", "team_id",
                                 "opponent_team_id", "home_score", "away_score", "status_period",
                                 "source_object_sha256"]].sort_values("game_id").to_dict("records")
    rebound_diff = merged.team_rebound_difference.astype(float)
    schema_by_year = {}
    for item in object_rows:
        schema_by_year.setdefault(str(item["seasonEndYear"]), {})[item["kind"]] = item["schemaFingerprint"]
    audit = {
        "schemaVersion": "nba-gen2-team-box-population-audit-v1",
        "sourceReceiptPhysicalSha256": _hash_file(receipt_path),
        "sourceContentIdentitySha256": receipt["contentIdentitySha256"],
        "objects": object_rows,
        "schemaBySeason": schema_by_year,
        "teamRows": int(len(merged)), "games": int(len(game_home)),
        "regularSeasonGames": int(game_home.season_type.eq(2).sum()),
        "playoffGames": int(game_home.season_type.eq(3).sum()),
        "otherExcludedGames": int((~game_home.season_type.isin([2, 3])).sum()),
        "duplicateTeamGameKeys": duplicate_team_keys, "orphanOpponentJoins": orphan_joins,
        "opponentScoreFailures": opponent_score_failures, "scoreFormulaFailures": score_formula_failures,
        "integrityQuarantineGameIds": declared_exclusions,
        "integrityQuarantineRule": "Preserve raw bytes; exclude complete game before any feature-history update; never infer component stats from final score.",
        "nonFranchiseExhibitionGameIds": nonfranchise_game_ids,
        "nonFranchiseExhibitionRule": "Exclude non-NBA team codes before regular-season modeling even when source season_type is 2.",
        "orphanScheduleRows": orphan_schedule,
        "overtimeGames": int(game_home.overtime_periods.gt(0).sum()),
        "derivedMinutesRows": int(merged.team_minutes_derived.notna().sum()),
        "overtimePeriodEvidenceRows": int(len(overtime)),
        "totalReboundIdentity": {
            "definition": "source-defined total_rebounds preserved separately; no equality requirement",
            "componentDefinition": "offensive_rebounds + defensive_rebounds",
            "equalRows": int(rebound_diff.eq(0).sum()),
            "differentRows": int(rebound_diff.ne(0).sum()),
            "minimumDifference": float(rebound_diff.min()),
            "medianDifference": float(rebound_diff.median()),
            "maximumDifference": float(rebound_diff.max()),
            "seasonsWithDifferences": sorted(int(v) for v in merged.loc[rebound_diff.ne(0), "season"].unique()),
            "featureUse": "OREB and DREB directly; total_rebounds excluded from four-factor features",
        },
        "populationIdentitySha256": _canonical_hash(identity_fields),
        "evidenceClass": "CATEGORY_A_RECONSTRUCTED_HISTORICAL_EVIDENCE",
        "historicalVintageCertified": False,
    }
    return GovernedPopulation(merged, game_home, overtime, audit)


def build_pregame_box_features(population: GovernedPopulation) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Emit target features before updating any result on the same date."""
    rows = population.team_rows[population.team_rows.season_type.eq(2)].copy()
    rows["team_code"] = rows.team_abbreviation.replace(ALIAS_TO_GEN1)
    rows = rows.sort_values(["game_date", "game_id", "team_home_away"])
    histories: dict[str, list[dict[str, Any]]] = defaultdict(list)
    league_by_season: dict[int, list[np.ndarray]] = defaultdict(list)
    output = []

    for day, day_rows in rows.groupby("game_date", sort=True):
        # All targets for this date are emitted before any date outcome update.
        for row in day_rows.itertuples():
            team, season = str(row.team_code), int(row.season)
            prior = histories[team]
            current = [item for item in prior if item["season"] == season]
            previous = [item for item in prior if item["season"] == season - 1]
            league_prior = league_by_season.get(season - 1, [])
            fallback = np.mean(league_prior, axis=0) if league_prior else np.full(len(BOX_METRICS), np.nan)
            prior_mean = np.mean([item["values"] for item in previous], axis=0) if previous else fallback
            current_values = np.asarray([item["values"] for item in current], dtype=float)
            current_mean = current_values.mean(axis=0) if len(current_values) else np.full(len(BOX_METRICS), np.nan)
            if np.isfinite(prior_mean).all():
                shrunk = ((len(current_values) * current_mean + PRIOR_WEIGHT * prior_mean)
                          / (len(current_values) + PRIOR_WEIGHT)) if len(current_values) else prior_mean
            else:
                shrunk = current_mean
            rolling = current_values[-10:].mean(axis=0) if len(current_values) else prior_mean
            if len(current_values):
                weights = (1 - EWM_ALPHA) ** np.arange(len(current_values) - 1, -1, -1)
                ewm = np.average(current_values, axis=0, weights=weights)
            else:
                ewm = prior_mean
            record = {"box_game_id": str(row.game_id), "game_date": str(day), "season_end": season,
                      "team_code": team, "team_id_box": str(row.team_id),
                      "team_history_games": len(current_values), "prior_season_games": len(previous),
                      "feature_history_latest_date": max((item["date"] for item in prior), default=None)}
            for metric, values in zip(BOX_METRICS, zip(shrunk, rolling, ewm)):
                for form, value in zip(SUMMARY_FORMS, values):
                    record[f"{metric}_{form}"] = float(value) if np.isfinite(value) else np.nan
            output.append(record)
        for row in day_rows.itertuples():
            values = np.asarray([getattr(row, metric) for metric in BOX_METRICS], dtype=float)
            item = {"season": int(row.season), "date": str(day), "values": values}
            histories[str(row.team_code)].append(item)
            league_by_season[int(row.season)].append(values)

    team_features = pd.DataFrame(output)
    home = population.games[population.games.season_type.eq(2)][[
        "game_id", "game_date", "season", "home_team_code", "away_team_code",
        "home_score", "away_score", "status_period", "overtime_periods"]].copy()
    home = home.rename(columns={"game_id": "box_game_id", "season": "season_end"})
    home_features = team_features.rename(columns={
        col: f"home_box_{col}" for col in team_features.columns
        if col not in ("box_game_id", "game_date", "season_end", "team_code")})
    away_features = team_features.rename(columns={
        col: f"away_box_{col}" for col in team_features.columns
        if col not in ("box_game_id", "game_date", "season_end", "team_code")})
    games = home.merge(home_features, left_on=["box_game_id", "game_date", "season_end", "home_team_code"],
                       right_on=["box_game_id", "game_date", "season_end", "team_code"], validate="one_to_one")
    games = games.drop(columns="team_code")
    games = games.merge(away_features, left_on=["box_game_id", "game_date", "season_end", "away_team_code"],
                        right_on=["box_game_id", "game_date", "season_end", "team_code"], validate="one_to_one")
    games = games.drop(columns="team_code")
    for metric in BOX_METRICS:
        for form in SUMMARY_FORMS:
            games[f"difference_box_{metric}_{form}"] = (
                games[f"home_box_{metric}_{form}"] - games[f"away_box_{metric}_{form}"])
    feature_columns = [column for column in games if (column.startswith("home_box_")
                       or column.startswith("away_box_") or column.startswith("difference_box_"))
                       and not column.endswith(("team_id_box", "feature_history_latest_date"))]
    feature_columns = [c for c in feature_columns if c not in
                       ("home_box_team_history_games", "home_box_prior_season_games",
                        "away_box_team_history_games", "away_box_prior_season_games")]
    feature_columns += ["home_box_team_history_games", "home_box_prior_season_games",
                        "away_box_team_history_games", "away_box_prior_season_games"]
    audit = {
        "schemaVersion": "nba-gen2-pregame-box-features-v1",
        "chronology": "game_date strictly earlier than target; all same-date targets emitted before updates",
        "sameDateOutcomesConsumed": False,
        "featureColumns": feature_columns,
        "featureColumnCount": len(feature_columns),
        "gameRows": int(len(games)),
        "earliestDate": str(games.game_date.min()), "latestDate": str(games.game_date.max()),
        "targetLeakageChecks": {
            "latestHistoryBeforeTarget": bool(((games.home_box_feature_history_latest_date.isna()) |
                (games.home_box_feature_history_latest_date < games.game_date)).all() and
                ((games.away_box_feature_history_latest_date.isna()) |
                (games.away_box_feature_history_latest_date < games.game_date)).all()),
        },
    }
    audit["featureContractSha256"] = _canonical_hash({
        "metrics": BOX_METRICS, "forms": SUMMARY_FORMS, "priorWeight": PRIOR_WEIGHT,
        "ewmAlpha": EWM_ALPHA, "columns": feature_columns, "chronology": audit["chronology"]})
    return games, audit
