from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.persistence.db import Database, json_dumps
from server.sports_datasets.registry import SportsDatasetRegistry
from server.sports_nfl import canonical as nfl_canonical
from server.sports_nfl import pipeline as nfl_pipeline
from server.sports_nfl.gold import (
    FEATURE_ERA_CONTRACTS,
    FEATURE_FAMILY_CATALOG,
    GAME_FEATURES,
    MARKET_FIELDS,
    PLAY_STATE_FEATURES,
    ROLLING_METRICS,
    materialize_gold,
)
from server.sports_nfl.publication import (
    NflPublicationError,
    parquet_evidence,
    publish_parquet_object,
    verify_parquet_object,
)
from server.sports_nfl.registry import NFL_DATASET_ID, register_nfl_foundation


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _canonical_source_paths(
    root: Path,
    *,
    schedules: list[dict[str, object]],
    plays: list[dict[str, object]],
    players: list[dict[str, object]],
) -> dict[str, list[Path]]:
    paths = {
        "schedules": _write_parquet(root / "schedules.parquet", schedules),
        "play_by_play": _write_parquet(root / "pbp.parquet", plays),
        "players": _write_parquet(root / "players.parquet", players),
    }
    for family in (
        "teams",
        "weekly_player_stats",
        "weekly_team_stats",
        "rosters",
        "weekly_rosters",
    ):
        paths[family] = _write_parquet(root / f"{family}.parquet", [{"placeholder": 1}])
    return {family: [path] for family, path in paths.items()}


def _schedule_row(game_id: str, game_date: date, **changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game_id,
        "season": 2024,
        "game_type": "REG",
        "week": 1,
        "gameday": game_date,
        "weekday": "Sunday",
        "gametime": "13:00",
        "away_team": "BBB",
        "home_team": "AAA",
        "away_score": 7.0,
        "home_score": 10.0,
        "location": "Home",
        "overtime": 0,
        "old_game_id": None,
        "gsis": game_id,
        "nfl_detail_id": None,
        "pfr": None,
        "pff": None,
        "espn": None,
        "ftn": None,
        "roof": "outdoors",
        "surface": "grass",
        "temp": 70.0,
        "wind": 5.0,
        "stadium_id": "VENUE-1",
        "stadium": "Test Stadium",
        "div_game": 1,
        "home_qb_id": "QB-A",
        "away_qb_id": "QB-B",
        "away_moneyline": 120.0,
        "home_moneyline": -130.0,
        "spread_line": -2.5,
        "away_spread_odds": -110.0,
        "home_spread_odds": -110.0,
        "total_line": 43.5,
        "over_odds": -105.0,
        "under_odds": -115.0,
    }
    row.update(changes)
    return row


def _play_row(game_id: str, play_id: int, game_date: date, **changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "game_id": game_id,
        "play_id": play_id,
        "season": 2024,
        "season_type": "REG",
        "week": 1,
        "game_date": game_date,
        "posteam": "AAA",
        "defteam": "BBB",
        "qtr": 1,
        "down": 1,
        "ydstogo": 10.0,
        "yardline_100": 75.0,
        "game_seconds_remaining": 3500.0,
        "score_differential": 0.0,
        "posteam_score": 0.0,
        "defteam_score": 0.0,
        "play_type": "run",
        "yards_gained": 4.0,
        "first_down": 0,
        "touchdown": 0,
        "interception": 0,
        "fumble_lost": 0,
        "sack": 0,
        "penalty": 0,
        "success": 1,
        "epa": 0.1,
        "ep": 1.0,
        "wp": 0.5,
        "home_wp": 0.5,
        "passer_player_id": None,
        "rusher_player_id": "00-RUSH",
        "receiver_player_id": None,
        "fixed_drive": 1,
        "drive": 1,
        "drive_play_count": 1,
        "drive_yards_penalized": 0.0,
        "fixed_drive_result": "Punt",
        "order_sequence": play_id,
        "desc": "Synthetic governed play",
    }
    row.update(changes)
    return row


def _player_row(gsis_id: str | None, display_name: str) -> dict[str, object]:
    return {
        "gsis_id": gsis_id,
        "display_name": display_name,
        "first_name": display_name.split()[0],
        "last_name": display_name.split()[-1],
        "position_group": "QB",
        "position": "QB",
        "birth_date": None,
        "height": 74,
        "weight": 220,
        "college_name": "Test University",
        "esb_id": None,
        "nfl_id": None,
        "pfr_id": None,
        "pff_id": None,
        "otc_id": None,
        "espn_id": None,
        "smart_id": None,
        "rookie_season": 2020,
        "last_season": 2026,
        "latest_team": "AAA",
        "status": "ACT",
    }


def _spec(paths: dict[str, list[Path]], table_name: str) -> dict[str, object]:
    return next(item for item in nfl_canonical._specs(paths) if item["name"] == table_name)


def test_grouped_optional_sources_materialize_with_exact_family_identity_and_lineage(
    tmp_path: Path,
) -> None:
    paths: dict[str, list[Path]] = {}
    for family, metric in (
        ("ngs_passing", "attempts"),
        ("ngs_receiving", "targets"),
        ("ngs_rushing", "rush_attempts"),
    ):
        paths[family] = [
            _write_parquet(
                tmp_path / f"{family}.parquet",
                [
                    {
                        "season": 2025,
                        "week": 1,
                        "player_gsis_id": "00-0000001",
                        metric: 10,
                    }
                ],
            )
        ]
    for family in (
        "pfr_advanced_passing",
        "pfr_advanced_rushing",
        "pfr_advanced_receiving",
        "pfr_advanced_defense",
    ):
        paths[family] = [
            _write_parquet(
                tmp_path / f"{family}.parquet",
                [
                    {
                        "season": 2025,
                        "week": 1,
                        "pfr_player_id": "Player00",
                        "team": "AAA",
                    }
                ],
            )
        ]

    specs = {str(item["name"]): item for item in nfl_canonical._optional_specs(paths)}
    ngs = specs["fact_nfl_nextgen_player_week"]
    pfr = specs["fact_nfl_pfr_advanced"]
    assert ngs["families"] == ("ngs_passing", "ngs_receiving", "ngs_rushing")
    assert pfr["families"] == (
        "pfr_advanced_passing",
        "pfr_advanced_rushing",
        "pfr_advanced_receiving",
        "pfr_advanced_defense",
    )

    connection = duckdb.connect(database=":memory:")
    try:
        ngs_rows = connection.execute(str(ngs["query"])).fetchall()
        ngs_names = [item[0] for item in connection.description]
        assert len(ngs_rows) == 3
        source_index = ngs_names.index("source_family")
        assert {row[source_index] for row in ngs_rows} == set(ngs["families"])

        pfr_rows = connection.execute(str(pfr["query"])).fetchall()
        pfr_names = [item[0] for item in connection.description]
        assert len(pfr_rows) == 4
        source_index = pfr_names.index("source_family")
        assert {row[source_index] for row in pfr_rows} == set(pfr["families"])
    finally:
        connection.close()

    manifest = {
        "partitions": [
            {
                "familyId": family,
                "season": 2025,
                "assetName": f"{family}.parquet",
                "fileSha256": family.ljust(64, "0")[:64],
                "sourceContractVersion": "NFLVERSE_SOURCE_FAMILY_V1",
                "releaseTag": family,
                "releasePublishedAt": "2026-01-01T00:00:00Z",
                "status": "COMPLETE",
            }
            for family in (*ngs["families"], *pfr["families"])
        ]
    }
    assert {item["familyId"] for item in nfl_canonical._lineage(manifest, ngs["families"])} == set(
        ngs["families"]
    )
    assert {item["familyId"] for item in nfl_canonical._lineage(manifest, pfr["families"])} == set(
        pfr["families"]
    )


def test_optional_coverage_does_not_invent_absent_season_columns(tmp_path: Path) -> None:
    (tmp_path / "objects").mkdir()
    paths = {
        "participation": [
            _write_parquet(
                tmp_path / "participation.parquet",
                [{"nflverse_game_id": "2025_01_BBB_AAA", "play_id": 1}],
            )
        ],
        "depth_charts": [
            _write_parquet(
                tmp_path / "objects" / "depth.parquet",
                [
                    {
                        "dt": date(2026, 8, 1),
                        "team": "AAA",
                        "gsis_id": "00-0000001",
                        "pos_id": "P",
                        "pos_rank": 1,
                    },
                    {
                        "dt": date(2026, 8, 1),
                        "team": "AAA",
                        "gsis_id": "00-0000001",
                        "pos_id": "P",
                        "pos_rank": 1,
                    },
                ],
            )
        ],
        "trades": [_write_parquet(tmp_path / "trades.parquet", [{"trade_id": "T1"}])],
        "contracts": [
            _write_parquet(tmp_path / "contracts.parquet", [{"contract_id": "C1"}])
        ],
    }
    specs = {str(item["name"]): item for item in nfl_canonical._optional_specs(paths)}
    assert specs["fact_nfl_participation"]["season"] is None
    assert specs["snapshot_nfl_depth_chart"]["season"] is None
    assert specs["snapshot_nfl_depth_chart"]["identity"] == ("source_record_sha256",)
    assert specs["snapshot_nfl_depth_chart"]["required"] == ("gsis_id",)
    assert specs["fact_nfl_trade"]["season"] is None
    assert specs["fact_nfl_contract"]["season"] is None

    connection = duckdb.connect(database=":memory:")
    try:
        for table_name, spec in specs.items():
            output = tmp_path / f"{table_name}.parquet"
            nfl_canonical._copy_query(connection, str(spec["query"]), output)
            coverage = nfl_canonical._coverage(
                connection,
                output,
                season_field=spec.get("season", "season"),
                date_field=spec.get("date"),
            )
            assert "seasons" not in coverage
            if table_name == "snapshot_nfl_depth_chart":
                assert coverage == {
                    "minimumDate": "2026-08-01",
                    "maximumDate": "2026-08-01",
                }
                assert connection.execute(
                    f"SELECT count(DISTINCT source_record_sha256), "
                    f"count(DISTINCT source_row_number) FROM read_parquet('{output.as_posix()}')"
                ).fetchone() == (2, 2)
    finally:
        connection.close()


def test_source_coverage_uses_governed_partition_season_when_rows_lack_season() -> None:
    coverage = nfl_pipeline._source_coverage(
        {
            "requestedFamilies": ["depth_charts"],
            "partitions": [
                {
                    "familyId": "depth_charts",
                    "season": 2025,
                    "rowCount": 2,
                    "byteCount": 100,
                    "releaseTag": "depth_charts_2025",
                    "assetUpdatedAt": "2026-01-01T00:00:00Z",
                    "physicalSchemaSha256": "a" * 64,
                    "license": {"id": "CC-BY-4.0"},
                    "coverage": {},
                },
                {
                    "familyId": "depth_charts",
                    "season": 2026,
                    "rowCount": 0,
                    "byteCount": 10,
                    "releaseTag": "depth_charts_2026",
                    "assetUpdatedAt": "2026-08-01T00:00:00Z",
                    "physicalSchemaSha256": "b" * 64,
                    "license": {"id": "CC-BY-4.0"},
                    "coverage": {},
                },
            ],
            "optionalMissing": [],
        }
    )[0]
    assert coverage["seasons"] == [2025, 2026]
    assert coverage["rowsBySeason"] == [
        {"season": 2025, "rowCount": 2},
        {"season": 2026, "rowCount": 0},
    ]


def test_roster_multistate_rows_keep_exact_deterministic_source_identity(tmp_path: Path) -> None:
    paths = _canonical_source_paths(
        tmp_path,
        schedules=[_schedule_row("2024_01_BBB_AAA", date(2024, 9, 1))],
        plays=[_play_row("2024_01_BBB_AAA", 1, date(2024, 9, 1))],
        players=[_player_row("00-0000001", "Exact Player")],
    )
    paths["rosters"] = [_write_parquet(tmp_path / "rosters-multistate.parquet", [
        {"season": 2024, "team": "AAA", "gsis_id": "00-0000001", "status": "ACT"},
        {"season": 2024, "team": "AAA", "gsis_id": "00-0000001", "status": "RES"},
    ])]
    paths["weekly_rosters"] = [_write_parquet(tmp_path / "weekly-rosters-multistate.parquet", [
        {"season": 2024, "week": 1, "team": "AAA", "gsis_id": "00-0000001", "status": "ACT"},
        {"season": 2024, "week": 1, "team": "AAA", "gsis_id": "00-0000001", "status": "RES"},
    ])]
    connection = duckdb.connect(database=":memory:")
    try:
        for table_name in ("snapshot_nfl_seasonal_roster", "snapshot_nfl_weekly_roster"):
            spec = _spec(paths, table_name)
            output = tmp_path / f"{table_name}.parquet"
            nfl_canonical._copy_query(connection, str(spec["query"]), output)
            quality = nfl_canonical._quality_for(
                connection,
                output,
                identity=spec["identity"],
                required=spec["required"],
            )
            assert spec["identity"] == ("source_record_sha256",)
            assert quality["rowCount"] == 2
            assert quality["duplicateIdentityRows"] == 0
            assert quality["missingIdentityRows"] == 0
            assert connection.execute(
                f"SELECT count(DISTINCT source_record_sha256) FROM read_parquet('{output.as_posix()}')"
            ).fetchone()[0] == 2
    finally:
        connection.close()


def test_canonical_game_and_play_identity_are_exact_and_duplicates_are_detected(tmp_path: Path) -> None:
    paths = _canonical_source_paths(
        tmp_path,
        schedules=[
            _schedule_row("2024_01_BBB_AAA", date(2024, 9, 1)),
            _schedule_row("2024_02_BBB_AAA", date(2024, 9, 8), week=2),
        ],
        plays=[
            _play_row("2024_01_BBB_AAA", 10, date(2024, 9, 1)),
            _play_row("2024_01_BBB_AAA", 11, date(2024, 9, 1)),
        ],
        players=[_player_row("00-0000001", "Exact Player")],
    )
    connection = duckdb.connect(database=":memory:")
    try:
        game_spec = _spec(paths, "dim_nfl_game")
        play_spec = _spec(paths, "fact_nfl_play")
        game_path = tmp_path / "dim-game.parquet"
        play_path = tmp_path / "fact-play.parquet"
        nfl_canonical._copy_query(connection, str(game_spec["query"]), game_path)
        nfl_canonical._copy_query(connection, str(play_spec["query"]), play_path)

        game_quality = nfl_canonical._quality_for(
            connection, game_path, identity=("canonical_game_id",)
        )
        play_quality = nfl_canonical._quality_for(
            connection, play_path, identity=("canonical_game_id", "canonical_play_id")
        )
        assert game_quality["duplicateIdentityRows"] == 0
        assert play_quality["duplicateIdentityRows"] == 0

        game_ids = {
            row[0]
            for row in connection.execute(
                f"SELECT canonical_game_id FROM read_parquet('{game_path.as_posix()}')"
            ).fetchall()
        }
        play_game_ids = {
            row[0]
            for row in connection.execute(
                f"SELECT DISTINCT canonical_game_id FROM read_parquet('{play_path.as_posix()}')"
            ).fetchall()
        }
        assert play_game_ids <= game_ids
        assert play_game_ids == {"2024_01_BBB_AAA"}

        duplicated_play_path = _write_parquet(
            tmp_path / "duplicated-plays.parquet",
            [_play_row("2024_01_BBB_AAA", 10, date(2024, 9, 1))] * 2,
        )
        duplicate_paths = {**paths, "play_by_play": [duplicated_play_path]}
        duplicate_output = tmp_path / "duplicate-fact-play.parquet"
        nfl_canonical._copy_query(
            connection, str(_spec(duplicate_paths, "fact_nfl_play")["query"]), duplicate_output
        )
        assert nfl_canonical._quality_for(
            connection,
            duplicate_output,
            identity=("canonical_game_id", "canonical_play_id"),
        )["duplicateIdentityRows"] == 1
    finally:
        connection.close()


def test_player_identity_is_source_id_only_and_never_name_matched(tmp_path: Path) -> None:
    paths = _canonical_source_paths(
        tmp_path,
        schedules=[_schedule_row("2024_01_BBB_AAA", date(2024, 9, 1))],
        plays=[_play_row("2024_01_BBB_AAA", 1, date(2024, 9, 1))],
        players=[
            _player_row("00-0000001", "Same Name"),
            _player_row(None, "Same Name"),
        ],
    )
    connection = duckdb.connect(database=":memory:")
    try:
        output = tmp_path / "dim-player.parquet"
        nfl_canonical._copy_query(
            connection, str(_spec(paths, "dim_nfl_player")["query"]), output
        )
        records = pq.read_table(output).to_pylist()
        assert [record["canonical_player_id"] for record in records] == ["00-0000001", None]
        assert records[0]["display_name"] == records[1]["display_name"] == "Same Name"
        quality = nfl_canonical._quality_for(
            connection, output, identity=("canonical_player_id",)
        )
        assert quality["missingIdentityRows"] == 1
    finally:
        connection.close()


def _team_game_row(
    game_id: str,
    game_date: date,
    *,
    team: str,
    opponent: str,
    is_home: bool,
    points_for: float,
    points_against: float,
    week: int,
) -> dict[str, object]:
    row: dict[str, object] = {
        "canonical_game_id": game_id,
        "season": 2024,
        "game_type": "REG",
        "week": week,
        "game_date": game_date,
        "team_id": team,
        "source_team_id": team,
        "opponent_team_id": opponent,
        "source_opponent_team_id": opponent,
        "is_home": is_home,
        "completed": True,
    }
    for metric in ROLLING_METRICS:
        row[metric] = 1.0
    row["points_for"] = points_for
    row["points_against"] = points_against
    return row


def _gold_silver_inputs(root: Path) -> dict[str, dict[str, object]]:
    game_rows: list[dict[str, object]] = []
    team_game_rows: list[dict[str, object]] = []
    schedule_rows: list[dict[str, object]] = []
    definitions = (
        ("2024_01_BBB_AAA", date(2024, 9, 1), 1, 10.0, 7.0),
        ("2024_02A_BBB_AAA", date(2024, 9, 8), 2, 100.0, 3.0),
        ("2024_02B_BBB_AAA", date(2024, 9, 8), 2, 200.0, 4.0),
        ("2024_03_BBB_AAA", date(2024, 9, 15), 3, 999.0, 2.0),
    )
    for game_id, game_date, week, home_points, away_points in definitions:
        game_rows.append(
            {
                "canonical_game_id": game_id,
                "season": 2024,
                "game_type": "REG",
                "week": week,
                "game_date": game_date,
                "canonical_home_team_id": "AAA",
                "canonical_away_team_id": "BBB",
                "location": "Home",
                "roof": "outdoors",
                "surface": "grass",
                "home_points": home_points,
                "away_points": away_points,
                "overtime": 0,
                "game_state": "FINAL",
            }
        )
        team_game_rows.extend(
            [
                _team_game_row(
                    game_id,
                    game_date,
                    team="AAA",
                    opponent="BBB",
                    is_home=True,
                    points_for=home_points,
                    points_against=away_points,
                    week=week,
                ),
                _team_game_row(
                    game_id,
                    game_date,
                    team="BBB",
                    opponent="AAA",
                    is_home=False,
                    points_for=away_points,
                    points_against=home_points,
                    week=week,
                ),
            ]
        )
        schedule_rows.append(
            _schedule_row(
                game_id,
                game_date,
                week=week,
                home_score=home_points,
                away_score=away_points,
            )
        )

    paths = {
        "fact_nfl_team_game": _write_parquet(root / "team-game.parquet", team_game_rows),
        "dim_nfl_game": _write_parquet(root / "games.parquet", game_rows),
        "snapshot_nfl_schedule": _write_parquet(root / "schedule.parquet", schedule_rows),
        "fact_nfl_play": _write_parquet(
            root / "plays.parquet",
            [
                {
                    "canonical_game_id": "2024_01_BBB_AAA",
                    "canonical_play_id": 1,
                    "game_date": date(2024, 9, 1),
                    "season": 2024,
                    "week": 1,
                    "game_type": "REG",
                    "quarter": 1,
                    "down": 1,
                    "distance": 10.0,
                    "yard_line_100": 75.0,
                    "game_seconds_remaining": 3500.0,
                    "score_differential": 0.0,
                    "possession_score": 0.0,
                    "defense_score": 0.0,
                    "possession_team_id": "AAA",
                    "defensive_team_id": "BBB",
                    "play_type": "run",
                    "yards_gained": 4.0,
                    "first_down": 0,
                    "touchdown": 0,
                    "turnover": 0,
                    "sack": 0,
                    "penalty": 0,
                    "expected_points": 1.0,
                    "epa": 0.1,
                    "possession_win_probability": 0.5,
                    "home_win_probability": 0.5,
                }
            ],
        ),
    }
    return {
        name: {
            "path": path,
            "manifest": {"manifestSha256": f"{index:x}" * 64},
        }
        for index, (name, path) in enumerate(paths.items(), start=1)
    }


def _materialized_gold(root: Path) -> dict[str, object]:
    inputs = _gold_silver_inputs(root / "silver-fixtures")
    return materialize_gold(root / "publication", inputs)


def test_gold_history_is_strictly_prior_date_and_market_evidence_is_separate(tmp_path: Path) -> None:
    gold = _materialized_gold(tmp_path)
    game_object = gold["byName"]["gold_nfl_game_pregame_v1"]
    rows = {
        row["canonical_game_id"]: row
        for row in pq.read_table(game_object["path"]).to_pylist()
    }

    # Both games on 2024-09-08 must see only 2024-09-01.  Neither the
    # target-game outcome, the other same-day game, nor the future 999-point
    # game may enter their rolling features.
    for game_id in ("2024_02A_BBB_AAA", "2024_02B_BBB_AAA"):
        assert rows[game_id]["home_prior_games"] == 1
        assert rows[game_id]["home_points_for_season_to_date"] == pytest.approx(10.0)
        assert rows[game_id]["home_days_since_previous_game"] == 7
        assert rows[game_id]["source_cutoff_contract"] == "PRIOR_COMPLETED_GAME_DATE_STRICTLY_BEFORE_TARGET"

    assert rows["2024_01_BBB_AAA"]["home_prior_games"] == 0
    assert rows["2024_01_BBB_AAA"]["home_points_for_season_to_date"] is None
    assert rows["2024_03_BBB_AAA"]["home_prior_games"] == 3

    schema_names = set(pq.read_schema(game_object["path"]).names)
    assert schema_names.isdisjoint(MARKET_FIELDS)
    assert all(row["market_fields_used"] is False for row in rows.values())
    contract = game_object["manifest"]["tableContract"]
    assert contract["orderedPredictors"] == list(GAME_FEATURES)
    assert "MARKET_LINES" in contract["excludedPredictorFamilies"]
    assert contract["historyRule"] == "COMPLETED_GAME_DATE_LT_TARGET_GAME_DATE"

    play_object = gold["byName"]["gold_nfl_play_state_v1"]
    assert play_object["manifest"]["tableContract"]["orderedPredictors"] == list(PLAY_STATE_FEATURES)
    play = pq.read_table(play_object["path"]).to_pylist()[0]
    assert play["source_cutoff_contract"] == "PLAY_START_STATE"
    assert play["future_play_state_used"] is False
    assert play["market_fields_used"] is False


def test_gold_maps_actual_schedule_postseason_codes_to_postseason(tmp_path: Path) -> None:
    inputs = _gold_silver_inputs(tmp_path / "silver-fixtures")
    target_game = "2024_01_BBB_AAA"
    for table_name in (
        "fact_nfl_team_game",
        "dim_nfl_game",
        "snapshot_nfl_schedule",
    ):
        path = Path(inputs[table_name]["path"])
        rows = pq.read_table(path).to_pylist()
        for row in rows:
            identity = row.get("canonical_game_id", row.get("game_id"))
            if identity == target_game:
                row["game_type"] = "WC"
        _write_parquet(path, rows)

    gold = materialize_gold(tmp_path / "publication", inputs)
    rows = {
        row["canonical_game_id"]: row
        for row in pq.read_table(
            gold["byName"]["gold_nfl_game_pregame_v1"]["path"]
        ).to_pylist()
    }
    assert rows[target_game]["governed_population"] == "POSTSEASON"


def test_feature_era_contracts_are_explicit_and_not_zero_fill_contracts() -> None:
    assert FEATURE_ERA_CONTRACTS["LONG_HISTORY_CORE"]["availableFromSeason"] == 1999
    assert FEATURE_ERA_CONTRACTS["LONG_HISTORY_CORE"]["missingIndicator"] == "SOURCE_NOT_AVAILABLE_FOR_ERA"
    assert FEATURE_ERA_CONTRACTS["LONG_HISTORY_CORE"]["materializationState"] == "MATERIALIZED_IN_CORE_GAME_GOLD"
    assert FEATURE_ERA_CONTRACTS["ROSTER_AND_USAGE"]["weeklyRosterFromSeason"] == 2002
    assert FEATURE_ERA_CONTRACTS["ROSTER_AND_USAGE"]["snapCountsFromSeason"] == 2012
    assert FEATURE_ERA_CONTRACTS["ADVANCED_TRACKING_AND_PARTICIPATION"]["participationFromSeason"] == 2016
    assert FEATURE_ERA_CONTRACTS["ADVANCED_TRACKING_AND_PARTICIPATION"]["ngsFromSeason"] == 2016
    assert FEATURE_ERA_CONTRACTS["RECENT_CHARTING"]["ftnFromSeason"] == 2022
    assert FEATURE_ERA_CONTRACTS["PFR_ADVANCED"]["availableFromSeason"] == 2018
    assert FEATURE_ERA_CONTRACTS["CURRENT_SEASON"]["completedGameEvidenceExpectedBeforeKickoff"] is False
    assert FEATURE_FAMILY_CATALOG["LONG_HISTORY_CORE"] == GAME_FEATURES
    assert set(MARKET_FIELDS).isdisjoint(GAME_FEATURES)


def test_gold_publication_verifies_and_manifest_tamper_fails_closed(tmp_path: Path) -> None:
    gold = _materialized_gold(tmp_path)
    game_object = gold["byName"]["gold_nfl_game_pregame_v1"]
    manifest_sha = game_object["manifest"]["manifestSha256"]
    verified = verify_parquet_object(tmp_path / "publication", manifest_sha)
    assert verified["manifest"]["layer"] == "GOLD"
    assert verified["manifest"]["governance"] == {
        "status": "RESEARCH_ONLY",
        "rightsBoundary": "LOCAL_PRIVATE_RESEARCH",
        "modelFitOccurred": False,
        "modelScoringOccurred": False,
        "promotionEligible": False,
    }

    manifest_path = Path(verified["manifestPath"])
    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    tampered["quality"]["rowCount"] += 1
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(NflPublicationError, match="manifest address differs"):
        verify_parquet_object(tmp_path / "publication", manifest_sha)


def _minimal_verified_foundation(root: Path) -> dict[str, object]:
    objects = []
    for index, (table_name, layer) in enumerate(
        (
            ("dim_nfl_game", "SILVER"),
            ("fact_nfl_play", "SILVER"),
            ("gold_nfl_game_pregame_v1", "GOLD"),
            ("gold_nfl_play_state_v1", "GOLD"),
        ),
        start=1,
    ):
        source = _write_parquet(root / "sources" / f"{table_name}.parquet", [{"row_id": index}])
        evidence = parquet_evidence(source)
        objects.append(
            {
                "path": source,
                "manifest": {
                    "layer": layer,
                    "tableName": table_name,
                    "manifestSha256": f"{index:x}" * 64,
                    **evidence,
                    "tableContract": {
                        "contract": f"{table_name.upper()}_V1",
                        "modelFitOccurred": False,
                    },
                    "coverage": {
                        "minimumSeason": 1999,
                        "maximumSeason": 2026,
                        "minimumDate": "1999-09-01",
                        "maximumDate": "2026-09-10",
                    },
                    "quality": {"duplicateIdentityRows": 0},
                    "governance": {
                        "status": "RESEARCH_ONLY",
                        "modelFitOccurred": False,
                    },
                },
            }
        )
    manifest_sha = "e" * 64
    rights = [
        {
            "rightsControlId": "nflverse-test",
            "displayName": "nflverse test evidence",
            "sourceName": "nflverse",
            "status": "LOCAL_PRIVATE_RESEARCH",
            "allowedUses": ["LOCAL_PRIVATE_RESEARCH"],
            "prohibitedUses": ["PUBLIC_REDISTRIBUTION"],
            "attribution": "nflverse",
            "controls": {"readOnly": True},
            "metadata": {"licenseId": "CC-BY-4.0"},
        }
    ]
    limitations = [
        {
            "limitationId": "TEST-RESEARCH-ONLY",
            "scope": "MODELING",
            "description": "Synthetic foundation is read-only test evidence.",
        }
    ]
    manifest = {
        "datasetId": NFL_DATASET_ID,
        "datasetVersionId": f"{NFL_DATASET_ID}:sha256:{manifest_sha}",
        "manifestSha256": manifest_sha,
        "sourceManifestSha256": "b" * 64,
        "publishedAt": "2026-08-29T12:00:00+00:00",
        "objects": [item["manifest"] for item in objects],
        "coverage": {
            "seasons": [1999, 2026],
            "minimumDate": "1999-09-01",
            "maximumDate": "2026-09-10",
            "currentSeasonScheduledGames": 272,
            "sourceFamilies": [{"familyId": "play_by_play", "status": "COMPLETE"}],
        },
        "quality": {"duplicateGameIdentities": 0, "duplicatePlayIdentities": 0},
        "featureFamilies": {"LONG_HISTORY_CORE": ["season", "week"]},
        "limitations": limitations,
        "rights": rights,
        "governance": {
            "status": "RESEARCH_ONLY",
            "rightsBoundary": "LOCAL_PRIVATE_RESEARCH",
            "workspaceActivationEligible": False,
            "compatibleWorkflowIds": ["nfl-forecasting"],
            "modelFitOccurred": False,
            "modelScoringOccurred": False,
            "promotionEligible": False,
        },
    }
    return {
        "manifest": manifest,
        "objects": objects,
        "manifestSha256": manifest_sha,
        "datasetVersionId": manifest["datasetVersionId"],
    }


def _insert_active_mlb(database: Database) -> None:
    now = "2026-08-29T11:00:00+00:00"
    with database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO sports_dataset_registrations (
              registration_id, dataset_id, dataset_version_id, manifest_id, manifest_sha,
              package_id, sport, league, evidence_cutoff, published_at, logical_package_root,
              validation_status, registered_at, last_validated_at, registered_by, rights_status,
              limitation_count, active, totals_json, seasons_json, evidence_coverage_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, 'Baseball', 'MLB', '2026-08-27', ?, ?, 'VALID', ?, ?,
                      'test-admin', 'LOCAL_PRIVATE_RESEARCH', 0, 1, ?, ?, ?, ?)
            """,
            (
                "active-mlb",
                "asp.mlb.test",
                "asp.mlb.test:version:1",
                "asp-mlb-test-manifest",
                "c" * 64,
                "asp-mlb-test-package",
                now,
                "mlb-test://active",
                now,
                now,
                json_dumps({"rows": 1}, {}),
                json_dumps([{"season": 2026}], []),
                json_dumps({"minimumDate": "2026-01-01", "maximumDate": "2026-08-27"}, {}),
                json_dumps({"workspaceActivationEligible": True}, {}),
            ),
        )


def test_registry_is_inactive_read_only_preserves_mlb_and_rejects_activation(tmp_path: Path) -> None:
    database = Database(tmp_path / "warehouse.db")
    database.initialize()
    _insert_active_mlb(database)
    verified = _minimal_verified_foundation(tmp_path / "foundation")

    first = register_nfl_foundation(
        database,
        verified,
        user_id="test-admin",
        logical_root=f"nfl-foundation://sha256/{verified['manifestSha256']}",
    )
    second = register_nfl_foundation(
        database,
        verified,
        user_id="test-admin",
        logical_root=f"nfl-foundation://sha256/{verified['manifestSha256']}",
    )
    assert first["registrationDisposition"] == "CREATED"
    assert second["registrationDisposition"] == "REUSED"
    assert first["active"] is False
    assert first["modelingProjectCreated"] is False
    assert first["modelsFitted"] == 0

    registry = SportsDatasetRegistry(database)
    active_before = registry.get_active()
    assert active_before is not None
    assert active_before["registration_id"] == "active-mlb"
    nfl_registration = registry.get(first["registrationId"])
    assert nfl_registration is not None
    assert nfl_registration["active"] in (0, False)
    assert nfl_registration["metadata_json"]["workspaceActivationEligible"] is False
    public = registry.public_dataset(nfl_registration)
    assert public["league"] == "NFL"
    assert public["workspaceActivationEligible"] is False
    assert public["modelFitOccurred"] is False
    assert public["modelingStatus"] == "NOT_CONNECTED"

    assert registry.activate(first["registrationId"]) is None
    assert registry.get_active()["registration_id"] == "active-mlb"
    with database.connection() as connection:
        assert connection.execute(
            "SELECT count(*) FROM sports_research_projects WHERE registration_id = ?",
            (first["registrationId"],),
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT count(*) FROM sports_dataset_registrations WHERE league = 'NFL' AND active = 1"
        ).fetchone()[0] == 0


def test_new_foundation_version_can_reuse_immutable_objects_without_replacing_history(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "warehouse.db")
    database.initialize()
    _insert_active_mlb(database)
    first_verified = _minimal_verified_foundation(tmp_path / "foundation")
    second_verified = deepcopy(first_verified)
    second_manifest_sha = "f" * 64
    second_verified["manifestSha256"] = second_manifest_sha
    second_verified["datasetVersionId"] = (
        f"{NFL_DATASET_ID}:sha256:{second_manifest_sha}"
    )
    second_verified["manifest"]["manifestSha256"] = second_manifest_sha
    second_verified["manifest"]["datasetVersionId"] = second_verified[
        "datasetVersionId"
    ]
    second_verified["manifest"]["publishedAt"] = "2026-08-30T12:00:00+00:00"

    first = register_nfl_foundation(
        database,
        first_verified,
        user_id="test-admin",
        logical_root=(
            f"nfl-foundation://sha256/{first_verified['manifestSha256']}"
        ),
    )
    second = register_nfl_foundation(
        database,
        second_verified,
        user_id="test-admin",
        logical_root=f"nfl-foundation://sha256/{second_manifest_sha}",
    )

    assert first["registrationId"] != second["registrationId"]
    with database.connection() as connection:
        registrations = connection.execute(
            """
            SELECT registration_id, active
            FROM sports_dataset_registrations
            WHERE dataset_id = ?
            ORDER BY registered_at, registration_id
            """,
            (NFL_DATASET_ID,),
        ).fetchall()
        assert len(registrations) == 2
        assert all(row["active"] == 0 for row in registrations)

        first_rows = connection.execute(
            """
            SELECT partition_id, family, logical_uri, governance_checksum
            FROM sports_dataset_partitions
            WHERE registration_id = ?
            ORDER BY family
            """,
            (first["registrationId"],),
        ).fetchall()
        second_rows = connection.execute(
            """
            SELECT partition_id, family, logical_uri, governance_checksum
            FROM sports_dataset_partitions
            WHERE registration_id = ?
            ORDER BY family
            """,
            (second["registrationId"],),
        ).fetchall()

    assert len(first_rows) == len(second_rows) == 4
    assert {row["partition_id"] for row in first_rows}.isdisjoint(
        {row["partition_id"] for row in second_rows}
    )
    assert all(
        row["partition_id"].startswith(f"{first['registrationId']}:")
        for row in first_rows
    )
    assert all(
        row["partition_id"].startswith(f"{second['registrationId']}:")
        for row in second_rows
    )
    assert [row["family"] for row in first_rows] == [
        row["family"] for row in second_rows
    ]
    assert [row["governance_checksum"] for row in first_rows] == [
        row["governance_checksum"] for row in second_rows
    ]
    assert all(first_verified["manifestSha256"] in row["logical_uri"] for row in first_rows)
    assert all(second_manifest_sha in row["logical_uri"] for row in second_rows)
    assert SportsDatasetRegistry(database).get_active()["registration_id"] == "active-mlb"


def test_nfl_namespace_contains_no_estimator_or_fit_execution() -> None:
    namespace = Path(__file__).resolve().parents[1] / "server" / "sports_nfl"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(namespace.glob("*.py"))
    ).lower()
    for forbidden in ("import sklearn", "from sklearn", "import xgboost", "from xgboost", ".fit("):
        assert forbidden not in source
