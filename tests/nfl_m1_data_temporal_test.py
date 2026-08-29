from __future__ import annotations

from datetime import date
from pathlib import Path
import shutil
import uuid

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.sports_nfl_m1.data_authority import (
    DEFAULT_NFL_STAGING_ROOT,
    FoundationPaths,
    NflM1DataError,
    assess_feature_tiers,
    audit_game_population,
    audit_market_coverage,
    load_eligible_games,
    resolve_nfl_m1_authority,
)
from server.sports_nfl_m1.temporal import build_temporal_design


@pytest.fixture
def m1_tmp_path() -> Path:
    """Avoid a machine-global pytest temp root that may be ACL-governed."""

    path = Path(".tmp") / f"nfl-m1-data-temporal-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _write(path: Path, rows: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)
    return path


def _game(game_id: str, season: int, *, day: int = 1) -> dict[str, object]:
    return {
        "canonical_game_id": game_id,
        "season": season,
        "game_type": "REG",
        "game_date": date(season, 9, day),
        "canonical_home_team_id": "HOME",
        "canonical_away_team_id": "AWAY",
        "home_points": 24.0,
        "away_points": 20.0,
        "home_win": 1,
        "tie_game": 0,
        "score_differential": 4.0,
        "total_points": 44.0,
        "overtime": 0,
        "game_state": "FINAL",
        "governed_population": "REGULAR_SEASON",
        "season_to_date_feature": 0.1,
        "home_points_for_last_4": 22.0,
        "home_prior_season_games": 16.0,
        "home_short_week": 0,
        "roof": "outdoors",
    }


def _paths(tmp_path: Path) -> FoundationPaths:
    game_rows = [_game("2019_01_AWAY_HOME", 2019), _game("2020_01_AWAY_HOME", 2020)]
    schedule_rows = [
        {
            "game_id": row["canonical_game_id"],
            "season": row["season"],
            "game_type": row["game_type"],
            "gameday": str(row["game_date"]),
            "home_team": row["canonical_home_team_id"],
            "away_team": row["canonical_away_team_id"],
            "home_score": row["home_points"],
            "away_score": row["away_points"],
        }
        for row in game_rows
    ]
    schedule_rows.append(
        {
            "game_id": "2021_01_AWAY_HOME",
            "season": 2021,
            "game_type": "REG",
            "gameday": "2021-09-01",
            "home_team": "HOME",
            "away_team": "AWAY",
            "home_score": None,
            "away_score": None,
        }
    )
    market_rows = [
        {
            "canonical_game_id": game_rows[0]["canonical_game_id"],
            "season": 2019,
            "home_moneyline": -120.0,
            "away_moneyline": 110.0,
            "spread_line": -2.5,
            "home_spread_price": -110.0,
            "away_spread_price": -110.0,
            "total_line": 44.5,
            "over_price": -105.0,
            "under_price": -115.0,
            "timing_semantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN",
            "core_predictor_eligible": False,
        },
        {
            "canonical_game_id": game_rows[1]["canonical_game_id"],
            "season": 2020,
            "home_moneyline": None,
            "away_moneyline": None,
            "spread_line": -1.0,
            "home_spread_price": None,
            "away_spread_price": None,
            "total_line": 42.0,
            "over_price": None,
            "under_price": None,
            "timing_semantics": "MARKET_SNAPSHOT_TIMING_UNPROVEN",
            "core_predictor_eligible": False,
        },
    ]
    game_path = _write(tmp_path / "game.parquet", game_rows)
    schedule_path = _write(tmp_path / "schedule.parquet", schedule_rows)
    market_path = _write(tmp_path / "market.parquet", market_rows)
    play_path = _write(tmp_path / "play.parquet", [{"canonical_game_id": "g", "canonical_play_id": 1}])
    return FoundationPaths(
        foundation_root=tmp_path,
        dataset_id="asp.nfl.test",
        dataset_version_id="asp.nfl.test:sha256:" + "a" * 64,
        foundation_manifest_sha256="a" * 64,
        game_gold_id="gold-table:gold_nfl_game_pregame_v1",
        game_manifest_sha256="b" * 64,
        game_path=game_path,
        game_row_count=len(game_rows),
        game_ordered_predictors=(
            "season_to_date_feature", "home_points_for_last_4",
            "home_prior_season_games", "home_short_week", "roof",
        ),
        play_gold_id="gold-table:gold_nfl_play_state_v1",
        play_manifest_sha256="c" * 64,
        play_path=play_path,
        play_row_count=1,
        schedule_manifest_sha256="d" * 64,
        schedule_path=schedule_path,
        schedule_row_count=len(schedule_rows),
        market_manifest_sha256="e" * 64,
        market_path=market_path,
        market_row_count=len(market_rows),
        feature_families={
            "QUARTERBACK": ("expected_starting_quarterback_id",),
            "ROSTER_AND_USAGE": ("prior_snap_share",),
            "ADVANCED_TRACKING_AND_PARTICIPATION": ("prior_motion_rate",),
            "RECENT_CHARTING": ("prior_screen_rate",),
        },
    )


def test_population_accounting_is_explicit_and_reconciled(m1_tmp_path: Path) -> None:
    paths = _paths(m1_tmp_path)
    audit = audit_game_population(paths)
    assert audit.source_schedule_rows == 3
    assert audit.gold_rows == audit.eligible_gold_rows == 2
    assert audit.gold_exclusions == {}
    assert audit.source_exclusions == {"NO_FINAL_SCORE_TRUTH": 1}
    assert audit.eligible_source_not_in_gold == ()
    assert audit.gold_not_in_eligible_source == ()
    assert audit.complete_eligible_seasons == (2019, 2020)
    assert [row["canonical_game_id"] for row in load_eligible_games(paths)] == [
        "2019_01_AWAY_HOME", "2020_01_AWAY_HOME"
    ]


def test_market_is_joined_only_for_evaluation_and_timing_stays_unproven(m1_tmp_path: Path) -> None:
    paths = _paths(m1_tmp_path)
    coverage = audit_market_coverage(paths, load_eligible_games(paths))
    assert coverage.eligible_games == coverage.joined_market_rows == 2
    assert coverage.complete_two_sided_moneylines == 1
    assert coverage.complete_two_sided_spreads == 1
    assert coverage.complete_two_sided_totals == 1
    assert coverage.timing_semantics == ("MARKET_SNAPSHOT_TIMING_UNPROVEN",)
    assert coverage.core_predictor_eligible_rows == 0


def test_feature_tiers_do_not_upgrade_source_tables_or_timing_unproven_fields(m1_tmp_path: Path) -> None:
    tiers = {item.tier: item for item in assess_feature_tiers(_paths(m1_tmp_path))}
    assert tiers["LONG_HISTORY_CORE"].status == "MATERIALIZED"
    assert tiers["CORE_PLUS_RECENT_FORM"].status == "PARTIAL_NOT_DISTINCT"
    assert "home_points_for_last_4" in tiers["CORE_PLUS_RECENT_FORM"].usable_columns
    assert tiers["CORE_PLUS_QUARTERBACK"].status == "NOT_POINT_IN_TIME_MATERIALIZABLE"
    assert tiers["CORE_PLUS_ROSTER_USAGE"].status == "SOURCE_TABLE_ONLY"
    assert tiers["RECENT_RICH"].status == "SOURCE_TABLE_ONLY"
    assert tiers["HIERARCHICAL_LONG_PLUS_RICH"].status == "DEPENDENCY_NOT_MATERIALIZED"


def _temporal_rows() -> list[dict[str, object]]:
    return [
        _game(f"{season}_{day:02d}_AWAY_HOME", season, day=day)
        for season in range(2018, 2026)
        for day in (1, 8)
    ]


def test_five_expanding_folds_are_chronological_date_atomic_and_oot_isolated() -> None:
    design = build_temporal_design(
        _temporal_rows(), complete_seasons=tuple(range(2018, 2026))
    )
    assert [fold.train_count for fold in design.folds] == [4, 6, 8, 10, 12]
    assert [fold.validation_count for fold in design.folds] == [2, 2, 2, 2, 2]
    assert [fold.validation_season for fold in design.folds] == [2020, 2021, 2022, 2023, 2024]
    assert design.oof_game_count == 10
    assert design.final_oot_season == 2025
    assert design.final_oot_count == 2
    assert design.final_oot_start_date == date(2025, 9, 1)
    assert design.final_oot_end_date == date(2025, 9, 8)
    assert set(design.oof_game_ids).isdisjoint(design.final_oot_game_ids)
    assert design.date_atomic is True


def test_incomplete_requested_oot_falls_back_before_any_fit() -> None:
    rows = _temporal_rows() + [_game("2026_01_AWAY_HOME", 2026)]
    design = build_temporal_design(
        rows,
        requested_oot_season=2026,
        complete_seasons=tuple(range(2018, 2026)),
    )
    assert design.final_oot_season == 2025
    assert design.prospective_seasons == (2026,)


def test_cross_role_date_or_duplicate_identity_fails_closed() -> None:
    rows = _temporal_rows()
    duplicate = dict(rows[-1])
    duplicate["season"] = 2026
    duplicate["game_date"] = rows[-1]["game_date"]
    with pytest.raises(NflM1DataError, match="duplicate identities"):
        build_temporal_design(rows + [duplicate])

    crossing = dict(rows[-1])
    crossing["canonical_game_id"] = "2026_UNIQUE"
    crossing["season"] = 2026
    with pytest.raises(NflM1DataError, match="crosses temporal season roles"):
        build_temporal_design(rows + [crossing], complete_seasons=tuple(range(2018, 2027)))


@pytest.mark.skipif(
    not (DEFAULT_NFL_STAGING_ROOT / "foundation-v1" / "current.json").is_file(),
    reason="local registered NFL Foundation is not present",
)
def test_completed_registered_foundation_has_exact_m1_population_and_splits() -> None:
    paths = resolve_nfl_m1_authority(deep_verify=False)
    assert paths.dataset_version_id == (
        "asp.nfl.gold-data-foundation.v1:sha256:"
        "f3e142f05bf9f503168b256db4e05d83c373e94425e1c3147d0817fdf37f3bbb"
    )
    assert paths.game_manifest_sha256 == "c13393c738f7629f4f7ff812069fa5cb29402e9bf08690e8d63586dacf9cd295"
    assert paths.play_manifest_sha256 == "3bfbe3ea89d3c29f19ac1a194fdef71582806a8e4cbf843aa150fb5db2a4e841"
    assert paths.game_row_count == 7_276
    assert paths.play_row_count == 1_109_384
    assert len(paths.game_ordered_predictors) == 197

    audit = audit_game_population(paths)
    assert audit.eligible_gold_rows == 7_276
    assert audit.source_schedule_rows == 7_548
    assert audit.source_exclusions == {"NO_FINAL_SCORE_TRUTH": 272}
    assert audit.complete_eligible_seasons == tuple(range(1999, 2026))
    rows = load_eligible_games(paths)
    design = build_temporal_design(rows, complete_seasons=audit.complete_eligible_seasons)
    assert [fold.train_count for fold in design.folds] == [5583, 5852, 6137, 6421, 6706]
    assert [fold.validation_count for fold in design.folds] == [269, 285, 284, 285, 285]
    assert design.final_oot_season == 2025
    assert design.final_oot_count == 285
    assert (design.final_oot_start_date, design.final_oot_end_date) == (
        date(2025, 9, 4), date(2026, 2, 8)
    )

    market = audit_market_coverage(paths, rows)
    assert market.joined_market_rows == 7_276
    assert market.complete_two_sided_moneylines == 5_295
    assert market.complete_two_sided_spreads == 5_295
    assert market.complete_two_sided_totals == 5_292
    assert market.timing_semantics == ("MARKET_SNAPSHOT_TIMING_UNPROVEN",)
    assert market.core_predictor_eligible_rows == 0
