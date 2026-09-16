"""Point-in-time NFL Gold feature authorities.

The two tables in this module are deterministic feature/target publications;
they never instantiate an estimator.  Pregame history is conservative:
only completed games on a strictly earlier calendar date may contribute to a
target game.  Market lines and timing-unproven weather/starter fields remain
separate from the core feature contract.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from .publication import publish_parquet_object


GAME_GOLD_ID = "gold-table:gold_nfl_game_pregame_v1"
PLAY_GOLD_ID = "gold-table:gold_nfl_play_state_v1"
GAME_GOLD_CONTRACT = "ASP_NFL_GAME_PREGAME_GOLD_V1"
PLAY_GOLD_CONTRACT = "ASP_NFL_PLAY_STATE_GOLD_V1"

ROLLING_METRICS = (
    "points_for",
    "points_against",
    "offensive_epa_per_play",
    "pass_epa_per_play",
    "rush_epa_per_play",
    "defensive_epa_per_play",
    "defensive_pass_epa_per_play",
    "defensive_rush_epa_per_play",
    "success_rate",
    "defensive_success_rate",
    "explosive_pass_rate",
    "explosive_rush_rate",
    "defensive_explosive_pass_allowed_rate",
    "defensive_explosive_rush_allowed_rate",
    "early_down_success_rate",
    "third_down_conversion_rate",
    "fourth_down_conversion_rate",
    "red_zone_td_play_rate",
    "turnover_rate",
    "sack_rate",
    "penalty_rate",
    "seconds_per_play",
)

GAME_CONTEXT_FEATURES = (
    "season",
    "week",
    "game_type",
    "game_month",
    "game_weekday",
    "neutral_site",
    "division_game",
    "roof",
    "surface",
    "home_days_since_previous_game",
    "away_days_since_previous_game",
    "home_short_week",
    "away_short_week",
    "home_bye_or_long_rest",
    "away_bye_or_long_rest",
    "home_prior_games",
    "away_prior_games",
    "home_prior_season_games",
    "away_prior_season_games",
    "home_source_era_missing",
    "away_source_era_missing",
)

GAME_ROLLING_FEATURES = tuple(
    f"{side}_{metric}_{window}"
    for side in ("home", "away")
    for metric in ROLLING_METRICS
    for window in ("season_to_date", "last_4", "last_8", "last_16")
)
GAME_FEATURES = GAME_CONTEXT_FEATURES + GAME_ROLLING_FEATURES

PLAY_STATE_FEATURES = (
    "season",
    "week",
    "game_type",
    "quarter",
    "down",
    "distance",
    "yard_line_100",
    "game_seconds_remaining",
    "score_differential",
    "possession_score",
    "defense_score",
    "possession_team_id",
    "defensive_team_id",
)

GAME_TARGETS = (
    "home_points",
    "away_points",
    "home_win",
    "tie_game",
    "score_differential",
    "total_points",
    "overtime",
    "game_state",
)
PLAY_TARGETS = (
    "play_type",
    "yards_gained",
    "first_down",
    "touchdown",
    "turnover",
    "sack",
    "penalty",
    "expected_points",
    "epa",
    "possession_win_probability",
    "home_win_probability",
)
MARKET_FIELDS = (
    "away_moneyline", "home_moneyline", "spread_line", "away_spread_price",
    "home_spread_price", "total_line", "over_price", "under_price",
)


FEATURE_FAMILY_CATALOG: Mapping[str, tuple[str, ...]] = {
    "LONG_HISTORY_CORE": GAME_FEATURES,
    "CORE_TEAM_STRENGTH_CANDIDATES": (
        "rolling_offensive_epa_per_play", "rolling_defensive_epa_per_play",
        "rolling_pass_epa_per_play", "rolling_rush_epa_per_play",
        "rolling_success_rate", "rolling_explosive_play_rate",
        "rolling_early_down_efficiency", "rolling_third_down_performance",
        "rolling_fourth_down_performance", "rolling_red_zone_performance",
        "rolling_goal_to_go_performance", "rolling_turnover_rate",
        "rolling_sack_rate", "rolling_penalty_rate", "rolling_drive_efficiency",
        "rolling_starting_field_position", "rolling_points_per_drive",
        "rolling_pace_seconds_per_play", "rolling_special_teams_performance",
        "season_to_date_state", "previous_4_game_state", "previous_8_game_state",
        "previous_16_game_state", "exponentially_weighted_recent_state",
    ),
    "QUARTERBACK": (
        "expected_starting_quarterback_id", "prior_passing_epa", "prior_cpoe",
        "prior_qb_sack_rate", "prior_scramble_rate", "prior_air_yards",
        "prior_pressure_performance", "prior_qb_starts", "recent_qb_usage",
        "starting_quarterback_change", "quarterback_cold_start",
    ),
    "ROSTER_AND_USAGE": (
        "prior_snap_share", "prior_target_share", "prior_rush_share",
        "offensive_line_continuity", "skill_position_continuity",
        "defensive_unit_continuity", "depth_chart_rank_prior_snapshot",
        "roster_addition_count", "roster_departure_count", "roster_change_count",
        "prior_personnel_usage", "prior_formation_usage",
    ),
    "REST_TRAVEL_AND_CALENDAR": (
        "rest_days", "short_week", "bye_week", "consecutive_road_games",
        "travel_distance_miles", "time_zone_change_hours",
        "time_zone_change_direction", "local_kickoff_time",
        "body_clock_mismatch_hours", "is_thursday", "is_monday",
        "is_sunday_night", "is_holiday", "division_game",
        "conference_game", "rematch", "recent_opponent",
    ),
    "VENUE_AND_WEATHER": (
        "home_away_neutral", "stadium", "roof", "surface", "temperature_f",
        "wind_mph", "precipitation", "weather_description", "altitude_feet",
    ),
    "ADVANCED_TRACKING_AND_PARTICIPATION": (
        "prior_motion_rate", "prior_play_action_rate", "prior_rpo_rate",
        "prior_screen_rate", "prior_no_huddle_rate", "prior_formation_usage",
        "prior_personnel_usage", "prior_pressure_rate", "prior_blitz_rate",
        "prior_pass_rusher_count", "prior_man_coverage_rate",
        "prior_zone_coverage_rate", "prior_route_usage", "prior_time_to_throw",
        "prior_ngs_expected_metric", "prior_ngs_above_expected_metric",
    ),
    "RECENT_CHARTING": (
        "prior_screen_rate", "prior_no_huddle_rate", "prior_qb_fault_sack_rate",
        "prior_interception_worthy_rate", "prior_catchable_ball_rate",
    ),
    "CURRENT_SEASON": (
        "current_schedule_available", "current_roster_snapshot_available",
        "current_depth_snapshot_available", "current_completed_game_evidence_available",
    ),
    "PLAY_STATE": PLAY_STATE_FEATURES,
    "MARKET_BENCHMARK_SEPARATE": MARKET_FIELDS,
}


FEATURE_ERA_CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    "LONG_HISTORY_CORE": {
        "availableFromSeason": 1999,
        "materializationState": "MATERIALIZED_IN_CORE_GAME_GOLD",
        "missingIndicator": "SOURCE_NOT_AVAILABLE_FOR_ERA",
    },
    "CORE_TEAM_STRENGTH_CANDIDATES": {
        "availableFromSeason": 1999,
        "materializationState": "PARTIALLY_MATERIALIZED_REVIEWABLE_CANDIDATES",
        "sourceCutoff": "STRICT_PRIOR_COMPLETED_GAME_DATE",
    },
    "QUARTERBACK": {
        "materializationState": "CANDIDATE_NOT_CORE_PREDICTOR",
        "reason": "TARGET_GAME_STARTER_OBSERVATION_TIME_UNPROVEN",
    },
    "ROSTER_AND_USAGE": {
        "weeklyRosterFromSeason": 2002,
        "snapCountsFromSeason": 2012,
        "materializationState": "CANDIDATE_REQUIRES_PREGAME_SNAPSHOT_CUTOFF",
    },
    "REST_TRAVEL_AND_CALENDAR": {
        "materializationState": "PARTIAL_REST_AND_CALENDAR_ONLY",
        "unavailableFields": "TRAVEL_DISTANCE_TIME_ZONE_BODY_CLOCK_WITHOUT_GOVERNED_VENUE_COORDINATES",
    },
    "VENUE_AND_WEATHER": {
        "materializationState": "ROOF_SURFACE_PRESENT_WEATHER_TIMING_UNPROVEN",
        "corePredictorEligible": False,
    },
    "ADVANCED_TRACKING_AND_PARTICIPATION": {
        "participationFromSeason": 2016,
        "ngsFromSeason": 2016,
        "materializationState": "RECENT_ERA_CANDIDATE_NOT_FORCED_INTO_CORE_GOLD",
    },
    "RECENT_CHARTING": {
        "ftnFromSeason": 2022,
        "materializationState": "RECENT_ERA_CANDIDATE_NOT_FORCED_INTO_CORE_GOLD",
    },
    "PFR_ADVANCED": {
        "availableFromSeason": 2018,
        "materializationState": "OPTIONAL_LOCAL_PRIVATE_RESEARCH",
    },
    "CURRENT_SEASON": {
        "season": 2026,
        "materializationState": "SCHEDULE_ROSTER_DEPTH_ONLY_UNTIL_COMPLETED_GAMES_EXIST",
        "completedGameEvidenceExpectedBeforeKickoff": False,
    },
    "MARKET_BENCHMARK_SEPARATE": {
        "materializationState": "SEPARATE_NON_PREDICTOR_TABLE",
        "timingSemantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN",
        "corePredictorEligible": False,
    },
}


class NflGoldError(RuntimeError):
    """Canonical Silver cannot produce the governed NFL Gold authorities."""


def _sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''").replace("\\", "/") + "'"


def _copy(connection: duckdb.DuckDBPyConnection, query: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"COPY ({query}) TO {_sql_string(path)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )


def _object(silver_by_name: Mapping[str, Mapping[str, Any]], name: str) -> Mapping[str, Any]:
    item = silver_by_name.get(name)
    if not item:
        raise NflGoldError(f"required canonical Silver table is missing: {name}")
    return item


def _window_columns() -> str:
    expressions = []
    frames = {
        "season_to_date": "PARTITION BY team_id, season ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING",
        "last_4": "PARTITION BY team_id ORDER BY game_date ROWS BETWEEN 4 PRECEDING AND 1 PRECEDING",
        "last_8": "PARTITION BY team_id ORDER BY game_date ROWS BETWEEN 8 PRECEDING AND 1 PRECEDING",
        "last_16": "PARTITION BY team_id ORDER BY game_date ROWS BETWEEN 16 PRECEDING AND 1 PRECEDING",
    }
    for metric in ROLLING_METRICS:
        for label, frame in frames.items():
            expressions.append(f"avg({metric}) OVER ({frame}) {metric}_{label}")
    return ",\n".join(expressions)


def _selected_side(side: str) -> str:
    values = [
        f"{side}.days_since_previous_game {side}_days_since_previous_game",
        f"cast({side}.days_since_previous_game < 6 as integer) {side}_short_week",
        f"cast({side}.days_since_previous_game >= 10 as integer) {side}_bye_or_long_rest",
        f"{side}.prior_games {side}_prior_games",
        f"{side}.prior_season_games {side}_prior_season_games",
        f"cast({side}.prior_games = 0 as integer) {side}_source_era_missing",
    ]
    values.extend(
        f"{side}.{metric}_{window} {side}_{metric}_{window}"
        for metric in ROLLING_METRICS
        for window in ("season_to_date", "last_4", "last_8", "last_16")
    )
    return ",\n".join(values)


def _game_query(team_game: Path, games: Path, raw_schedule: Path) -> str:
    daily_metrics = ",\n".join(f"avg({metric}) {metric}" for metric in ROLLING_METRICS)
    return f"""
      WITH completed_team_game AS (
        SELECT * FROM read_parquet({_sql_string(team_game)}) WHERE completed = true
      ), team_date AS (
        SELECT team_id, season, game_date, count(*) games_on_date,
          {daily_metrics}
        FROM completed_team_game
        GROUP BY team_id, season, game_date
      ), history_date AS (
        SELECT *,
          datediff('day', lag(game_date) OVER (PARTITION BY team_id ORDER BY game_date), game_date)
            days_since_previous_game,
          coalesce(sum(games_on_date) OVER (PARTITION BY team_id ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) prior_games,
          coalesce(sum(games_on_date) OVER (PARTITION BY team_id, season ORDER BY game_date ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) prior_season_games,
          {_window_columns()}
        FROM team_date
      ), history AS (
        SELECT c.*, h.* EXCLUDE (team_id, season, game_date)
        FROM completed_team_game c JOIN history_date h USING (team_id, season, game_date)
      ), games AS (
        SELECT * FROM read_parquet({_sql_string(games)})
        WHERE game_state = 'FINAL'
      )
      SELECT
        g.canonical_game_id, g.season, g.game_type, g.week, g.game_date,
        month(g.game_date) game_month, dayofweek(g.game_date) game_weekday,
        g.canonical_home_team_id, g.canonical_away_team_id,
        cast(g.location = 'Neutral' as integer) neutral_site,
        cast(s.div_game as integer) division_game,
        g.roof, g.surface,
        {_selected_side('home')},
        {_selected_side('away')},
        g.home_points, g.away_points,
        cast(g.home_points > g.away_points as integer) home_win,
        cast(g.home_points = g.away_points as integer) tie_game,
        g.home_points - g.away_points score_differential,
        g.home_points + g.away_points total_points,
        g.overtime, g.game_state,
        CASE WHEN g.game_type = 'PRE' THEN 'PRESEASON_SEPARATE'
             WHEN g.game_type IN ('POST', 'WC', 'DIV', 'CON', 'SB') THEN 'POSTSEASON'
             ELSE 'REGULAR_SEASON' END governed_population,
        'PRIOR_COMPLETED_GAME_DATE_STRICTLY_BEFORE_TARGET' source_cutoff_contract,
        false market_fields_used,
        false target_game_participation_used,
        cast(s.temp as double) research_only_temperature_timing_unproven,
        cast(s.wind as double) research_only_wind_timing_unproven,
        cast(s.home_qb_id as varchar) research_only_home_qb_timing_unproven,
        cast(s.away_qb_id as varchar) research_only_away_qb_timing_unproven
      FROM games g
      JOIN history home
        ON home.canonical_game_id = g.canonical_game_id AND home.is_home = true
      JOIN history away
        ON away.canonical_game_id = g.canonical_game_id AND away.is_home = false
      JOIN read_parquet({_sql_string(raw_schedule)}) s
        ON s.game_id = g.canonical_game_id
    """


def _play_query(play: Path) -> str:
    features = ", ".join(PLAY_STATE_FEATURES)
    targets = ", ".join(PLAY_TARGETS)
    return f"""
      SELECT canonical_game_id, canonical_play_id, game_date,
        {features}, {targets},
        'PLAY_START_STATE' source_cutoff_contract,
        false market_fields_used,
        false future_play_state_used
      FROM read_parquet({_sql_string(play)})
      WHERE canonical_game_id IS NOT NULL AND canonical_play_id IS NOT NULL
        AND play_type IS NOT NULL
        AND play_type NOT IN ('no_play', 'qb_kneel', 'qb_spike')
    """


def materialize_gold(
    publication_root: Path,
    silver_by_name: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Publish the game-pregame and play-state Gold authorities."""

    team_game = Path(_object(silver_by_name, "fact_nfl_team_game")["path"])
    games = Path(_object(silver_by_name, "dim_nfl_game")["path"])
    raw_schedule = Path(_object(silver_by_name, "snapshot_nfl_schedule")["path"])
    plays = Path(_object(silver_by_name, "fact_nfl_play")["path"])
    root = Path(publication_root).resolve()
    work = root / ".build" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect(database=":memory:")
    try:
        connection.execute("SET threads = 4")
        connection.execute("SET preserve_insertion_order = false")
        game_path = work / "gold_nfl_game_pregame_v1.parquet"
        play_path = work / "gold_nfl_play_state_v1.parquet"
        _copy(connection, _game_query(team_game, games, raw_schedule), game_path)
        _copy(connection, _play_query(plays), play_path)

        game_rows = int(connection.execute(f"SELECT count(*) FROM read_parquet({_sql_string(game_path)})").fetchone()[0])
        play_rows = int(connection.execute(f"SELECT count(*) FROM read_parquet({_sql_string(play_path)})").fetchone()[0])
        if game_rows == 0 or play_rows == 0:
            raise NflGoldError("Gold materialization produced an empty mandatory table")
        game_duplicates = int(connection.execute(
            f"SELECT count(*) FROM (SELECT canonical_game_id FROM read_parquet({_sql_string(game_path)}) GROUP BY canonical_game_id HAVING count(*) > 1)"
        ).fetchone()[0])
        play_duplicates = int(connection.execute(
            f"SELECT count(*) FROM (SELECT canonical_game_id, canonical_play_id FROM read_parquet({_sql_string(play_path)}) GROUP BY ALL HAVING count(*) > 1)"
        ).fetchone()[0])
        if game_duplicates or play_duplicates:
            raise NflGoldError(f"Gold identities are duplicated: games={game_duplicates}, plays={play_duplicates}")
        source_play_rows = int(connection.execute(f"SELECT count(*) FROM read_parquet({_sql_string(plays)})").fetchone()[0])
        excluded_play_rows = source_play_rows - play_rows
        game_dates = connection.execute(
            f"SELECT min(game_date), max(game_date), min(season), max(season) FROM read_parquet({_sql_string(game_path)})"
        ).fetchone()
        play_dates = connection.execute(
            f"SELECT min(game_date), max(game_date), min(season), max(season) FROM read_parquet({_sql_string(play_path)})"
        ).fetchone()
        game_object = publish_parquet_object(
            root, game_path, layer="GOLD", table_name="gold_nfl_game_pregame_v1",
            source_lineage=[
                {"tableName": "fact_nfl_team_game", "manifestSha256": _object(silver_by_name, "fact_nfl_team_game")["manifest"]["manifestSha256"]},
                {"tableName": "dim_nfl_game", "manifestSha256": _object(silver_by_name, "dim_nfl_game")["manifest"]["manifestSha256"]},
                {"tableName": "snapshot_nfl_schedule", "manifestSha256": _object(silver_by_name, "snapshot_nfl_schedule")["manifest"]["manifestSha256"]},
            ],
            contract={
                "contract": GAME_GOLD_CONTRACT,
                "datasetId": GAME_GOLD_ID,
                "identityFields": ["canonical_game_id"],
                "orderedPredictors": list(GAME_FEATURES),
                "targets": list(GAME_TARGETS),
                "excludedPredictorFamilies": ["MARKET_LINES", "TARGET_GAME_PARTICIPATION", "TIMING_UNPROVEN_WEATHER", "TIMING_UNPROVEN_STARTER"],
                "historyRule": "COMPLETED_GAME_DATE_LT_TARGET_GAME_DATE",
            },
            coverage={
                "minimumDate": game_dates[0].isoformat(), "maximumDate": game_dates[1].isoformat(),
                "minimumSeason": int(game_dates[2]), "maximumSeason": int(game_dates[3]),
            },
            quality={"rowCount": game_rows, "duplicateGameIdentities": game_duplicates},
        )
        play_object = publish_parquet_object(
            root, play_path, layer="GOLD", table_name="gold_nfl_play_state_v1",
            source_lineage=[
                {"tableName": "fact_nfl_play", "manifestSha256": _object(silver_by_name, "fact_nfl_play")["manifest"]["manifestSha256"]}
            ],
            contract={
                "contract": PLAY_GOLD_CONTRACT,
                "datasetId": PLAY_GOLD_ID,
                "identityFields": ["canonical_game_id", "canonical_play_id"],
                "orderedPredictors": list(PLAY_STATE_FEATURES),
                "targets": list(PLAY_TARGETS),
                "historyRule": "STATE_AT_PLAY_START_ONLY",
            },
            coverage={
                "minimumDate": play_dates[0].isoformat(), "maximumDate": play_dates[1].isoformat(),
                "minimumSeason": int(play_dates[2]), "maximumSeason": int(play_dates[3]),
            },
            quality={
                "rowCount": play_rows,
                "sourceRows": source_play_rows,
                "excludedRows": excluded_play_rows,
                "exclusionReasons": {
                    "MISSING_GAME_OR_PLAY_ID_OR_PLAY_TYPE_OR_NONCOMPETITIVE_PLAY": excluded_play_rows
                },
                "duplicatePlayIdentities": play_duplicates,
            },
        )
    finally:
        connection.close()
        if work.exists():
            shutil.rmtree(work)
    return {
        "status": "COMPLETE", "objects": [game_object, play_object],
        "byName": {"gold_nfl_game_pregame_v1": game_object, "gold_nfl_play_state_v1": play_object},
        "featureFamilies": FEATURE_FAMILY_CATALOG, "featureEraContracts": FEATURE_ERA_CONTRACTS,
        "modelsFitted": 0, "modelsScored": 0, "modelsPromoted": 0,
    }


__all__ = [
    "FEATURE_ERA_CONTRACTS", "FEATURE_FAMILY_CATALOG", "GAME_FEATURES",
    "GAME_GOLD_ID", "GAME_TARGETS", "MARKET_FIELDS", "NflGoldError",
    "PLAY_GOLD_ID", "PLAY_STATE_FEATURES", "PLAY_TARGETS", "materialize_gold",
]
