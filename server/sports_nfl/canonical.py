"""Canonical NFL Silver table materialization from verified nflverse Bronze.

The module is intentionally data-only.  It imports no estimator, calibration,
scoring, or promotion code.  Every SQL projection either preserves a source
field or applies an explicit deterministic identity/target transformation.
"""
from __future__ import annotations

import json
import math
import shutil
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb

from .bronze_acquisition import verify_nflverse_bronze
from .publication import publish_parquet_object


SILVER_CONTRACT = "ASP_NFL_CANONICAL_SILVER_V1"


class NflCanonicalError(RuntimeError):
    """Verified Bronze cannot be reconciled into canonical NFL tables."""


def _sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''").replace("\\", "/") + "'"


def _read_parquet(paths: Sequence[Path], *, include_filename: bool = False) -> str:
    if not paths:
        raise NflCanonicalError("canonical table has no source partitions")
    values = ",".join(_sql_string(path) for path in paths)
    filename_option = ", filename=true" if include_filename else ""
    return f"read_parquet([{values}], union_by_name=true{filename_option})"


def _source_object_identity(path: Path) -> str:
    """Return the staging-root-independent immutable Bronze object identity."""

    parts = Path(path).parts
    try:
        object_index = next(index for index, part in enumerate(parts) if part.lower() == "objects")
    except StopIteration as exc:
        raise NflCanonicalError("Bronze source path lacks its governed objects identity") from exc
    return Path(*parts[object_index:]).as_posix()


def _partition_paths(root: Path, manifest: Mapping[str, Any]) -> dict[str, list[Path]]:
    grouped: dict[str, list[Path]] = defaultdict(list)
    for item in manifest.get("partitions") or []:
        if item.get("status") != "COMPLETE":
            continue
        path = (Path(root) / str(item["relativePath"])).resolve()
        try:
            path.relative_to(Path(root).resolve())
        except ValueError as exc:
            raise NflCanonicalError("Bronze partition escapes its root") from exc
        grouped[str(item["familyId"])].append(path)
    return {family: sorted(paths, key=lambda value: value.as_posix()) for family, paths in grouped.items()}


def _lineage(manifest: Mapping[str, Any], family_ids: Sequence[str]) -> list[dict[str, Any]]:
    allowed = set(family_ids)
    result = []
    for item in manifest.get("partitions") or []:
        if item.get("familyId") not in allowed or item.get("status") != "COMPLETE":
            continue
        result.append(
            {
                "familyId": item["familyId"],
                "season": item.get("season"),
                "assetName": item["assetName"],
                "fileSha256": item["fileSha256"],
                "sourceContractVersion": item["sourceContractVersion"],
                "releaseTag": item["releaseTag"],
                "releasePublishedAt": item["releasePublishedAt"],
            }
        )
    return sorted(result, key=lambda value: (value["familyId"], value.get("season") or -1, value["assetName"]))


def _copy_query(connection: duckdb.DuckDBPyConnection, query: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection.execute(
        f"COPY ({query}) TO {_sql_string(destination)} "
        "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
    )


def _scalar(connection: duckdb.DuckDBPyConnection, query: str) -> Any:
    return connection.execute(query).fetchone()[0]


def _quality_for(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    identity: Sequence[str],
    required: Sequence[str] = (),
) -> dict[str, Any]:
    source = f"read_parquet({_sql_string(path)})"
    rows = int(_scalar(connection, f"SELECT count(*) FROM {source}"))
    duplicate = 0
    missing_identity = 0
    if identity:
        keys = ",".join(f'"{item}"' for item in identity)
        duplicate = int(
            _scalar(
                connection,
                f"SELECT coalesce(sum(n - 1), 0) FROM (SELECT count(*) n FROM {source} GROUP BY {keys} HAVING count(*) > 1)",
            )
        )
        predicate = " OR ".join(f'"{item}" IS NULL OR trim(cast("{item}" AS VARCHAR)) = \'\'' for item in identity)
        missing_identity = int(_scalar(connection, f"SELECT count(*) FROM {source} WHERE {predicate}"))
    missing_required = {}
    for field in required:
        missing_required[field] = int(
            _scalar(
                connection,
                f'SELECT count(*) FROM {source} WHERE "{field}" IS NULL',
            )
        )
    return {
        "rowCount": rows,
        "duplicateIdentityRows": duplicate,
        "missingIdentityRows": missing_identity,
        "missingRequiredValues": missing_required,
    }


def _coverage(
    connection: duckdb.DuckDBPyConnection,
    path: Path,
    *,
    season_field: str | None = "season",
    date_field: str | None = None,
) -> dict[str, Any]:
    source = f"read_parquet({_sql_string(path)})"
    result: dict[str, Any] = {}
    if season_field:
        values = connection.execute(
            f'SELECT DISTINCT cast("{season_field}" AS INTEGER) season FROM {source} '
            f'WHERE "{season_field}" IS NOT NULL ORDER BY season'
        ).fetchall()
        result["seasons"] = [int(row[0]) for row in values]
    if date_field:
        minimum, maximum = connection.execute(
            f'SELECT min(cast("{date_field}" AS DATE)), max(cast("{date_field}" AS DATE)) FROM {source}'
        ).fetchone()
        result["minimumDate"] = minimum.isoformat() if minimum else None
        result["maximumDate"] = maximum.isoformat() if maximum else None
    return result


def _passthrough_query(paths: Sequence[Path]) -> str:
    return f"SELECT * FROM {_read_parquet(paths)}"


def _canonical_team(field: str) -> str:
    return (
        f"CASE cast({field} as varchar) "
        "WHEN 'OAK' THEN 'LV' WHEN 'SD' THEN 'LAC' "
        "WHEN 'STL' THEN 'LAR' WHEN 'LA' THEN 'LAR' "
        f"ELSE cast({field} as varchar) END"
    )


def _specs(paths: Mapping[str, Sequence[Path]]) -> list[dict[str, Any]]:
    schedules = _read_parquet(paths["schedules"])
    teams = _read_parquet(paths["teams"])
    players = _read_parquet(paths["players"])
    pbp = _read_parquet(paths["play_by_play"])
    player_stats = _read_parquet(paths["weekly_player_stats"])
    team_stats = _read_parquet(paths["weekly_team_stats"])
    rosters = _read_parquet(paths["rosters"])
    weekly_rosters = _read_parquet(paths["weekly_rosters"])
    play_columns = f"""
      cast(game_id as varchar) canonical_game_id,
      cast(play_id as bigint) canonical_play_id,
      cast(season as integer) season,
      cast(season_type as varchar) game_type,
      cast(week as integer) AS "week",
      cast(game_date as date) game_date,
      {_canonical_team('posteam')} possession_team_id,
      cast(posteam as varchar) source_possession_team_id,
      {_canonical_team('defteam')} defensive_team_id,
      cast(defteam as varchar) source_defensive_team_id,
      cast(qtr as integer) AS "quarter",
      cast(down as integer) AS "down",
      cast(ydstogo as double) distance,
      cast(yardline_100 as double) yard_line_100,
      cast(game_seconds_remaining as double) game_seconds_remaining,
      cast(score_differential as double) score_differential,
      cast(posteam_score as double) possession_score,
      cast(defteam_score as double) defense_score,
      cast(play_type as varchar) play_type,
      cast(yards_gained as double) yards_gained,
      cast(coalesce(first_down, 0) as integer) first_down,
      cast(coalesce(touchdown, 0) as integer) touchdown,
      cast(greatest(coalesce(interception, 0), coalesce(fumble_lost, 0)) as integer) turnover,
      cast(coalesce(sack, 0) as integer) sack,
      cast(coalesce(penalty, 0) as integer) penalty,
      cast(coalesce(success, 0) as integer) success,
      cast(epa as double) epa,
      cast(ep as double) expected_points,
      cast(wp as double) possession_win_probability,
      cast(home_wp as double) home_win_probability,
      cast(passer_player_id as varchar) passer_player_id,
      cast(rusher_player_id as varchar) rusher_player_id,
      cast(receiver_player_id as varchar) receiver_player_id,
      cast(fixed_drive as bigint) canonical_drive_id,
      cast(drive as bigint) source_drive_id,
      cast(drive_play_count as integer) source_drive_play_count,
      cast(drive_yards_penalized as double) source_drive_yards_penalized,
      cast(fixed_drive_result as varchar) source_drive_result,
      cast(order_sequence as bigint) source_order_sequence,
      cast("desc" as varchar) source_description
    """
    team_game_query = f"""
      WITH schedule_team AS (
        SELECT game_id canonical_game_id, cast(season as integer) season,
          game_type, cast(week as integer) AS "week", cast(gameday as date) game_date,
          {_canonical_team('home_team')} team_id, cast(home_team as varchar) source_team_id,
          {_canonical_team('away_team')} opponent_team_id, cast(away_team as varchar) source_opponent_team_id,
          true is_home,
          cast(home_score as double) points_for, cast(away_score as double) points_against,
          CASE WHEN home_score IS NULL OR away_score IS NULL THEN false ELSE true END completed
        FROM {schedules}
        UNION ALL
        SELECT game_id, cast(season as integer), game_type, cast(week as integer), cast(gameday as date),
          {_canonical_team('away_team')}, cast(away_team as varchar),
          {_canonical_team('home_team')}, cast(home_team as varchar),
          false, cast(away_score as double), cast(home_score as double),
          CASE WHEN home_score IS NULL OR away_score IS NULL THEN false ELSE true END
        FROM {schedules}
      ), play_ordered AS (
        SELECT *, game_seconds_remaining - lead(game_seconds_remaining) OVER
          (PARTITION BY game_id ORDER BY order_sequence) elapsed_seconds
        FROM {pbp}
      ), play_team AS (
        SELECT game_id canonical_game_id, {_canonical_team('posteam')} team_id,
          count(*) FILTER (WHERE play_type IS NOT NULL) plays,
          avg(epa) FILTER (WHERE play_type IN ('pass','run')) offensive_epa_per_play,
          avg(epa) FILTER (WHERE play_type = 'pass') pass_epa_per_play,
          avg(epa) FILTER (WHERE play_type = 'run') rush_epa_per_play,
          avg(cast(success as double)) FILTER (WHERE play_type IN ('pass','run')) success_rate,
          avg(cast(yards_gained >= 20 as double)) FILTER (WHERE play_type = 'pass') explosive_pass_rate,
          avg(cast(yards_gained >= 10 as double)) FILTER (WHERE play_type = 'run') explosive_rush_rate,
          avg(cast(success as double)) FILTER (WHERE down IN (1,2) AND play_type IN ('pass','run')) early_down_success_rate,
          avg(cast(third_down_converted as double)) FILTER (WHERE down = 3) third_down_conversion_rate,
          avg(cast(fourth_down_converted as double)) FILTER (WHERE down = 4) fourth_down_conversion_rate,
          avg(cast(touchdown as double)) FILTER (WHERE yardline_100 <= 20 AND play_type IN ('pass','run')) red_zone_td_play_rate,
          avg(cast(greatest(coalesce(interception,0),coalesce(fumble_lost,0)) as double)) turnover_rate,
          avg(cast(sack as double)) FILTER (WHERE qb_dropback = 1) sack_rate,
          avg(cast(penalty as double)) penalty_rate,
          avg(elapsed_seconds) FILTER (WHERE play_type IN ('pass','run') AND elapsed_seconds BETWEEN 0 AND 120) seconds_per_play
        FROM play_ordered
        WHERE posteam IS NOT NULL
        GROUP BY game_id, {_canonical_team('posteam')}
      )
      SELECT s.*, p.plays, p.offensive_epa_per_play, p.pass_epa_per_play,
        p.rush_epa_per_play, p.success_rate, p.explosive_pass_rate,
        p.explosive_rush_rate, p.early_down_success_rate,
        p.third_down_conversion_rate, p.fourth_down_conversion_rate,
        p.red_zone_td_play_rate, p.turnover_rate, p.sack_rate, p.penalty_rate,
        p.seconds_per_play, d.offensive_epa_per_play defensive_epa_per_play,
        d.pass_epa_per_play defensive_pass_epa_per_play,
        d.rush_epa_per_play defensive_rush_epa_per_play,
        d.success_rate defensive_success_rate,
        d.explosive_pass_rate defensive_explosive_pass_allowed_rate,
        d.explosive_rush_rate defensive_explosive_rush_allowed_rate
      FROM schedule_team s
      LEFT JOIN play_team p USING (canonical_game_id, team_id)
      LEFT JOIN play_team d ON d.canonical_game_id = s.canonical_game_id
        AND d.team_id = s.opponent_team_id
    """
    return [
        {
            "name": "dim_nfl_team", "families": ("teams",),
            "query": f"""SELECT {_canonical_team('team_abbr')} canonical_team_id,
              cast(team_abbr as varchar) source_team_abbr, team_name, team_nick, team_conf conference,
              team_division division, cast(team_id as varchar) source_team_id
              FROM {teams}""",
            "identity": ("source_team_abbr",), "required": ("canonical_team_id", "source_team_abbr"),
            "season": None,
        },
        {
            "name": "dim_nfl_player", "families": ("players",),
            "query": f"""SELECT gsis_id canonical_player_id, display_name, first_name, last_name,
              position_group, position, birth_date, height, weight, college_name,
              esb_id, nfl_id, pfr_id, pff_id, otc_id, espn_id, smart_id,
              rookie_season, last_season, latest_team, status
              FROM {players}""",
            "identity": ("canonical_player_id",), "required": (),
            "season": None,
        },
        {
            "name": "dim_nfl_game", "families": ("schedules",),
            "query": f"""SELECT game_id canonical_game_id, cast(season as integer) season,
              game_type, cast(week as integer) AS "week", cast(gameday as date) game_date,
              weekday, gametime,
              {_canonical_team('away_team')} canonical_away_team_id,
              cast(away_team as varchar) source_away_team_id,
              {_canonical_team('home_team')} canonical_home_team_id,
              cast(home_team as varchar) source_home_team_id,
              cast(away_score as double) away_points,
              cast(home_score as double) home_points, location, cast(overtime as integer) overtime,
              old_game_id, gsis gsis_game_id, nfl_detail_id, pfr pfr_game_id,
              pff pff_game_id, espn espn_game_id, ftn ftn_game_id,
              roof, surface, cast(temp as double) temperature_f,
              cast(wind as double) wind_mph, stadium_id canonical_venue_id, stadium,
              CASE WHEN home_score IS NULL OR away_score IS NULL THEN 'SCHEDULED'
                   ELSE 'FINAL' END game_state
              FROM {schedules}""",
            "identity": ("canonical_game_id",), "required": ("canonical_game_id", "season", "game_date"),
            "date": "game_date",
        },
        {
            "name": "dim_nfl_venue", "families": ("schedules",),
            "query": f"""SELECT stadium_id canonical_venue_id, any_value(stadium) venue_name,
              any_value(roof) roof, any_value(surface) surface
              FROM {schedules} WHERE stadium_id IS NOT NULL GROUP BY stadium_id""",
            "identity": ("canonical_venue_id",), "required": ("canonical_venue_id",), "season": None,
        },
        {
            "name": "dim_nfl_season_week", "families": ("schedules",),
            "query": f"""SELECT cast(season as integer) season, game_type,
              cast(week as integer) AS "week", min(cast(gameday as date)) minimum_game_date,
              max(cast(gameday as date)) maximum_game_date, count(*) scheduled_games,
              count(*) FILTER (WHERE home_score IS NOT NULL AND away_score IS NOT NULL) completed_games
              FROM {schedules} GROUP BY season, game_type, week""",
            "identity": ("season", "game_type", "week"), "required": (), "date": "minimum_game_date",
        },
        {
            "name": "fact_nfl_play", "families": ("play_by_play",),
            "query": f"SELECT {play_columns} FROM {pbp}",
            "identity": ("canonical_game_id", "canonical_play_id"),
            "required": ("canonical_game_id", "canonical_play_id", "season"), "date": "game_date",
        },
        {
            "name": "fact_nfl_drive", "families": ("play_by_play",),
            "query": f"""SELECT game_id canonical_game_id, cast(season as integer) season,
              cast(season_type as varchar) game_type, cast(week as integer) AS "week",
              cast(game_date as date) game_date, cast(fixed_drive as bigint) canonical_drive_id,
              any_value(posteam) possession_team_id, any_value(defteam) defensive_team_id,
              min(order_sequence) first_order_sequence, max(order_sequence) last_order_sequence,
              count(*) plays, max(drive_play_count) source_drive_play_count,
              max(ydsnet) drive_yards, max(drive_first_downs) first_downs,
              max(cast(drive_ended_with_score as integer)) ended_with_score,
              any_value(fixed_drive_result) drive_result,
              max(cast(touchdown as integer)) touchdown,
              max(cast(field_goal_result = 'made' as integer)) field_goal,
              max(cast(greatest(coalesce(interception,0),coalesce(fumble_lost,0)) as integer)) turnover,
              max(cast(punt_attempt as integer)) punt,
              max(cast(fourth_down_failed as integer)) turnover_on_downs
              FROM {pbp} WHERE fixed_drive IS NOT NULL
              GROUP BY game_id, season, season_type, week, game_date, fixed_drive""",
            "identity": ("canonical_game_id", "canonical_drive_id"),
            "required": ("canonical_game_id", "canonical_drive_id"), "date": "game_date",
        },
        {
            "name": "fact_nfl_team_game", "families": ("schedules", "play_by_play", "weekly_team_stats"),
            "query": team_game_query,
            "identity": ("canonical_game_id", "team_id"),
            "required": ("canonical_game_id", "team_id", "season", "game_date"), "date": "game_date",
        },
        {
            "name": "fact_nfl_player_game", "families": ("weekly_player_stats",),
            "query": f"SELECT * FROM {player_stats}",
            "identity": ("game_id", "player_id", "team"), "required": ("season", "week"),
        },
        {
            "name": "fact_nfl_player_week", "families": ("weekly_player_stats",),
            "query": f"SELECT * FROM {player_stats}",
            "identity": ("season", "week", "player_id", "team"), "required": ("season", "week"),
        },
        {
            "name": "fact_nfl_team_week", "families": ("weekly_team_stats",),
            "query": f"SELECT * FROM {team_stats}",
            "identity": ("season", "week", "team"), "required": ("season", "week", "team"),
        },
        {
            "name": "snapshot_nfl_weekly_roster", "families": ("weekly_rosters",),
            # Weekly sources can legitimately emit multiple status records for
            # one player/team/week.  Bind the complete source row rather than
            # collapsing those point-in-time states or inventing a name match.
            "query": f"SELECT *, sha256(to_json(source_row)) source_record_sha256 FROM {weekly_rosters} source_row",
            "identity": ("source_record_sha256",), "required": ("season", "team"),
        },
        {
            "name": "snapshot_nfl_seasonal_roster", "families": ("rosters",),
            # Older seasonal files contain governed multi-state records and
            # many pre-GSIS rows.  Preserve each exact row with a deterministic
            # content identity; GSIS remains a nullable linkage, never a name.
            "query": f"SELECT *, sha256(to_json(source_row)) source_record_sha256 FROM {rosters} source_row",
            "identity": ("source_record_sha256",), "required": ("season", "team"),
        },
        {
            "name": "snapshot_nfl_schedule", "families": ("schedules",),
            "query": f"SELECT * FROM {schedules}",
            "identity": ("game_id",), "required": ("game_id", "season", "gameday"), "date": "gameday",
        },
        {
            "name": "snapshot_nfl_market_line", "families": ("schedules",),
            "query": f"""SELECT game_id canonical_game_id, cast(season as integer) season,
              game_type, cast(week as integer) AS "week", cast(gameday as date) game_date,
              cast(away_moneyline as double) away_moneyline,
              cast(home_moneyline as double) home_moneyline,
              cast(spread_line as double) spread_line,
              cast(away_spread_odds as double) away_spread_price,
              cast(home_spread_odds as double) home_spread_price,
              cast(total_line as double) total_line,
              cast(over_odds as double) over_price, cast(under_odds as double) under_price,
              'MARKET_SNAPSHOT_TIMING_UNPROVEN' timing_semantics,
              false core_predictor_eligible
              FROM {schedules}
              WHERE away_moneyline IS NOT NULL OR home_moneyline IS NOT NULL
                OR spread_line IS NOT NULL OR total_line IS NOT NULL""",
            "identity": ("canonical_game_id",), "required": ("canonical_game_id",), "date": "game_date",
        },
    ]


OPTIONAL_TABLES: Mapping[str, Mapping[str, Any]] = {
    "fact_nfl_snap_count": {
        "families": ("snap_counts",),
        "identity": ("game_id", "pfr_player_id", "team"),
    },
    "fact_nfl_participation": {
        "families": ("participation",),
        "identity": ("nflverse_game_id", "play_id"),
        "season": None,
    },
    "fact_nfl_nextgen_player_week": {
        "families": ("ngs_passing", "ngs_receiving", "ngs_rushing"),
        "identity": ("source_family", "season", "week", "player_gsis_id"),
    },
    "fact_nfl_ftn_play_charting": {
        "families": ("ftn_charting",),
        "identity": ("nflverse_game_id", "nflverse_play_id"),
    },
    "snapshot_nfl_depth_chart": {
        "families": ("depth_charts",),
        # A player may legitimately hold more than one depth-chart slot at the
        # same timestamp (for example P/holder or PR/KR).  pos_id is the
        # source's slot identity; GSIS remains a separately reported player
        # linkage and is never replaced by a name match.
        "identity": ("source_record_sha256",),
        "required": ("gsis_id",),
        "season": None,
        "date": "dt",
        "sourceRecordIdentity": True,
    },
    "snapshot_nfl_injury_report": {
        "families": ("injuries",),
        "identity": ("season", "week", "team", "gsis_id"),
    },
    "dim_nfl_official": {
        "families": ("officials",),
        "identity": ("game_id", "official_id", "position"),
    },
    "fact_nfl_pfr_advanced": {
        "families": (
            "pfr_advanced_passing",
            "pfr_advanced_rushing",
            "pfr_advanced_receiving",
            "pfr_advanced_defense",
        ),
        "identity": ("source_family", "season", "week", "pfr_player_id", "team"),
    },
    "dim_nfl_draft_pick": {
        "families": ("draft_picks",), "identity": ("season", "pick"),
    },
    "dim_nfl_combine": {
        "families": ("combine",), "identity": ("season", "player_name"),
    },
    "fact_nfl_trade": {
        "families": ("trades",), "identity": (), "season": None,
    },
    "fact_nfl_contract": {
        "families": ("contracts",), "identity": (), "season": None,
    },
}


def _optional_specs(paths: Mapping[str, Sequence[Path]]) -> list[dict[str, Any]]:
    """Bind optional tables to their exact acquired source-family partitions."""

    result: list[dict[str, Any]] = []
    for table_name, contract in OPTIONAL_TABLES.items():
        configured_families = tuple(str(value) for value in contract["families"])
        available_families = tuple(
            family for family in configured_families if paths.get(family)
        )
        if not available_families:
            continue
        if len(configured_families) == 1:
            if contract.get("sourceRecordIdentity") is True:
                query = " UNION ALL BY NAME ".join(
                    "SELECT * EXCLUDE(file_row_number), "
                    f"{_sql_string(_source_object_identity(path))} source_partition_id, "
                    "file_row_number source_row_number, "
                    "sha256(to_json(struct_pack("
                    f"source_partition_id := {_sql_string(_source_object_identity(path))}, "
                    "source_row_number := file_row_number))) source_record_sha256 "
                    f"FROM read_parquet({_sql_string(path)}, union_by_name=true, file_row_number=true) source_row"
                    for path in paths[available_families[0]]
                )
            else:
                query = f"SELECT * FROM {_read_parquet(paths[available_families[0]])}"
        else:
            # These grouped families have partially different schemas and may
            # contain the same player/week.  Preserve the exact source family
            # as an identity component rather than collapsing or overwriting
            # one discipline with another.
            query = " UNION ALL BY NAME ".join(
                f"SELECT {_sql_string(family)} source_family, * "
                f"FROM {_read_parquet(paths[family])}"
                for family in available_families
            )
        result.append(
            {
                "name": table_name,
                "families": available_families,
                "query": query,
                "identity": tuple(str(value) for value in contract["identity"]),
                "required": tuple(str(value) for value in contract.get("required", ())),
                "season": contract.get("season", "season"),
                "date": contract.get("date"),
            }
        )
    return result


def materialize_canonical_silver(
    bronze_root: Path,
    silver_root: Path,
    *,
    bronze_manifest_sha: str | None = None,
) -> dict[str, Any]:
    """Build and verify canonical Silver objects from exact Bronze bytes."""

    verified = verify_nflverse_bronze(Path(bronze_root), bronze_manifest_sha)
    manifest = verified.get("manifest", verified)
    paths = _partition_paths(Path(bronze_root), manifest)
    mandatory = {
        "play_by_play", "schedules", "teams", "players", "rosters",
        "weekly_rosters", "weekly_player_stats", "weekly_team_stats",
    }
    missing = sorted(mandatory - set(paths))
    if missing:
        raise NflCanonicalError(f"mandatory Bronze families missing: {missing}")

    root = Path(silver_root).resolve()
    work = root / ".build" / uuid.uuid4().hex
    work.mkdir(parents=True, exist_ok=False)
    connection = duckdb.connect(database=":memory:")
    objects = []
    try:
        connection.execute("SET threads = 4")
        connection.execute("SET preserve_insertion_order = false")
        for spec in _specs(paths):
            destination = work / f"{spec['name']}.parquet"
            _copy_query(connection, spec["query"], destination)
            quality = _quality_for(
                connection, destination, identity=spec["identity"], required=spec.get("required", ())
            )
            coverage = _coverage(
                connection, destination, season_field=spec.get("season", "season"), date_field=spec.get("date")
            )
            objects.append(
                publish_parquet_object(
                    root, destination, layer="SILVER", table_name=spec["name"],
                    source_lineage=_lineage(manifest, spec["families"]),
                    contract={
                        "contract": SILVER_CONTRACT,
                        "identityFields": list(spec["identity"]),
                        "sourceFamilies": list(spec["families"]),
                        "targetSemantics": "SOURCE_DIRECT_OR_EXPLICIT_DETERMINISTIC_TRANSFORMATION",
                    },
                    coverage=coverage, quality=quality,
                )
            )

        for spec in _optional_specs(paths):
            table_name = str(spec["name"])
            families = tuple(str(value) for value in spec["families"])
            identity = tuple(str(value) for value in spec["identity"])
            required = tuple(str(value) for value in spec.get("required", ()))
            destination = work / f"{table_name}.parquet"
            _copy_query(connection, str(spec["query"]), destination)
            quality = _quality_for(
                connection, destination, identity=identity, required=required
            )
            coverage = _coverage(
                connection,
                destination,
                season_field=spec.get("season", "season"),
                date_field=spec.get("date"),
            )
            objects.append(
                publish_parquet_object(
                    root, destination, layer="SILVER", table_name=table_name,
                    source_lineage=_lineage(manifest, families),
                    contract={
                        "contract": SILVER_CONTRACT,
                        "identityFields": list(identity),
                        "sourceFamilies": list(families),
                        "optionalEnrichment": True,
                    },
                    coverage=coverage, quality=quality,
                )
            )
    finally:
        connection.close()
        if work.exists():
            shutil.rmtree(work)

    by_name = {item["manifest"]["tableName"]: item for item in objects}
    required_tables = {
        "dim_nfl_team", "dim_nfl_player", "dim_nfl_game", "dim_nfl_venue",
        "dim_nfl_season_week", "fact_nfl_play", "fact_nfl_drive",
        "fact_nfl_team_game", "fact_nfl_player_game", "fact_nfl_player_week",
        "fact_nfl_team_week", "snapshot_nfl_weekly_roster",
        "snapshot_nfl_seasonal_roster", "snapshot_nfl_schedule",
        "snapshot_nfl_market_line",
    }
    absent = sorted(required_tables - set(by_name))
    if absent:
        raise NflCanonicalError(f"canonical Silver tables missing: {absent}")
    return {"status": "COMPLETE", "objects": objects, "byName": by_name, "modelsFitted": 0}


__all__ = ["NflCanonicalError", "SILVER_CONTRACT", "materialize_canonical_silver"]
