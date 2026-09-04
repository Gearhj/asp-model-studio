from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from server.persistence.db import Database, json_dumps
from server.sports_current_statcast import sufficient_stats as stats
from server.sports_current_statcast.pipeline import CurrentStatcastPipelineError
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_gold.contracts import GOLD_FEATURES
from server.sports_gold.features import (
    aggregate_pitch_history,
    build_advanced_features_with_sufficient_statistics,
    prepare_pa_history,
)
from scripts import build_current_sufficient_stats as sufficient_stats_cli


def _annual_metrics(*, batting: bool, multiplier: int) -> str:
    values = (
        {
            "AB": 100 * multiplier,
            "H": 30 * multiplier,
            "2B": 6 * multiplier,
            "3B": 1 * multiplier,
            "HR": 4 * multiplier,
            "BB": 10 * multiplier,
            "HBP": 2 * multiplier,
            "SF": 3 * multiplier,
            "SH": 1 * multiplier,
            "SO": 20 * multiplier,
        }
        if batting
        else {
            "IPouts": 150 * multiplier,
            "H": 40 * multiplier,
            "BB": 12 * multiplier,
            "HBP": 2 * multiplier,
            "BFP": 200 * multiplier,
            "G": 20 * multiplier,
            "GS": 8 * multiplier,
        }
    )
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def _annual_prior_table(*, include_same_season: bool) -> pa.Table:
    rows: list[dict[str, Any]] = []
    for source_season in ((2022, 2023) if include_same_season else (2022,)):
        multiplier = source_season - 2020
        for player, domain, batting in (
            ("uuid-b", "BATTING", True),
            ("uuid-p", "PITCHING", False),
        ):
            rows.append(
                {
                    "canonical_player_id": player,
                    "identity_resolution_status": "EXACT",
                    "season": source_season,
                    "domain": domain,
                    "eligible_from_season": source_season + 1,
                    "same_season_predictor_eligible": False,
                    "metrics_json": _annual_metrics(
                        batting=batting, multiplier=multiplier
                    ),
                }
            )
    return pa.Table.from_pylist(rows)


def _gold_upstream() -> dict[str, Any]:
    return {
        "existingGoldV1": {
            "datasetVersionId": "gold-v1",
            "logicalContentSha256": "1" * 64,
            "reusedSeasons": [2023, 2024],
        },
        "existingSilverPa": {"manifestSha256": "2" * 64},
        "existingSilverPitch": {"manifestSha256": "3" * 64},
        "currentSilverManifestSha256": "4" * 64,
        "playerIdentity": {"registrationSha256": "5" * 64},
        "playerPrior": {"datasetManifestSha256": "6" * 64},
    }


def _valid_payload_frame() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pa_id, role in (("pa-development", "DEVELOPMENT_SELECTION"), ("pa-oot", "FINAL_OOT")):
        row: dict[str, Any] = {
            "canonicalPaId": pa_id,
            "game_date": (
                date(2026, 8, 13) if role == "DEVELOPMENT_SELECTION" else None
            ),
            "season": 2026 if role == "DEVELOPMENT_SELECTION" else None,
            "datasetRole": role,
            "materialization_status": (
                stats.DEVELOPMENT_MATERIALIZED
                if role == "DEVELOPMENT_SELECTION"
                else stats.UNMATERIALIZED
            ),
            "materialization_reason": (
                None if role == "DEVELOPMENT_SELECTION" else stats.FINAL_OOT_SEALED
            ),
        }
        row.update({name: 0 if role == "DEVELOPMENT_SELECTION" else None for name in stats.INTEGER_COUNT_COLUMNS})
        row.update({name: 2026 if role == "DEVELOPMENT_SELECTION" else None for name in stats.ELIGIBLE_SEASON_COLUMNS})
        row.update({name: 0.0 if role == "DEVELOPMENT_SELECTION" else None for name in stats.FLOAT_COLUMNS})
        rows.append(row)
    return pd.DataFrame(rows)


def test_wave1_companion_contract_has_exact_physical_types() -> None:
    assert stats.CURRENT_SUFFICIENT_STATS_CONTRACT == (
        "MLB_CURRENT_STATCAST_SUFFICIENT_STATS_V1"
    )
    assert stats.CURRENT_SUFFICIENT_STATS_DATASET_ID == (
        "gold-table:gold_mlb_current_pa_sufficient_stats_v1"
    )
    assert stats.FINAL_OOT_SEALED == "FINAL_OOT_SEALED"
    assert "pitcher_last250_other_or_unclassified_pitch_count" in (
        stats.SUFFICIENT_STATISTIC_COLUMNS
    )
    schema = stats.sufficient_statistics_schema()
    assert schema.field("pitcher_last250_pitch_count").type == pa.int64()
    assert schema.field("game_date").nullable is True
    assert schema.field("season").nullable is True
    assert schema.field("pitcher_last250_fastball_velocity_sum").type == pa.float64()
    assert schema.field("pitcher_last250_fastball_velocity_sumsq").type == pa.float64()


def test_pitch_aggregation_preserves_full_composition_moments_and_cutoff() -> None:
    pitches = pa.table(
        {
            "canonicalPaId": ["pa-1"] * 6,
            "gameDate": ["2026-08-13"] * 5 + ["2026-08-14"],
            "pitchType": ["FF", "SL", "CH", None, "FA", "FF"],
            "releaseSpeed": [95.5, 85.0, 87.0, 82.0, float("nan"), 120.0],
            "pitchResultType": [
                "swinging_strike",
                "foul",
                "ball",
                "called_strike",
                "hit_into_play",
                "swinging_strike",
            ],
        }
    )

    row = aggregate_pitch_history(
        pitches, maximum_game_date="2026-08-13"
    ).to_dict("records")[0]

    assert row["pitch_count"] == 5
    assert row["fastball_count"] == 2
    assert row["breaking_count"] == 1
    assert row["offspeed_count"] == 1
    assert row["other_or_unclassified_pitch_count"] == 1
    assert (
        row["fastball_count"]
        + row["breaking_count"]
        + row["offspeed_count"]
        + row["other_or_unclassified_pitch_count"]
        == row["pitch_count"]
    )
    assert row["fastball_velocity_count"] == 1
    assert row["fastball_velocity_sum"] == pytest.approx(95.5)
    assert row["fastball_velocity_sumsq"] == pytest.approx(95.5**2)


def _history_inputs(rows: list[tuple[str, str]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    pa_rows: list[dict[str, Any]] = []
    pitch_rows: list[dict[str, Any]] = []
    for index, (pa_id, game_date) in enumerate(rows, start=1):
        season = int(game_date[:4])
        pa_rows.append(
            {
                "canonicalPaId": pa_id,
                "canonicalGameId": f"game-{pa_id}",
                "mlbamGamePk": season * 1000 + index,
                "atBatNumber": index,
                "batterCanonicalPlayerId": "b-shared",
                "pitcherCanonicalPlayerId": "p-shared",
                "season": season,
                "gameDate": game_date,
                "stand": "R",
                "pThrows": "R",
                "paEvent": "strikeout" if pa_id == "source-shifted" else "single",
            }
        )
        is_shifted_source = pa_id == "source-shifted"
        pitch_rows.append(
            {
                "canonicalPaId": pa_id,
                "pitch_count": 2 if is_shifted_source else 1,
                "swing_count": 2 if is_shifted_source else 1,
                "whiff_count": 1 if is_shifted_source else 0,
                "contact_count": 1,
                "fastball_count": 1,
                "breaking_count": 0,
                "offspeed_count": 0,
                "other_or_unclassified_pitch_count": 1 if is_shifted_source else 0,
                "fastball_velocity_sum": 97.25 if is_shifted_source else 90.0,
                "fastball_velocity_sumsq": (
                    97.25**2 if is_shifted_source else 90.0**2
                ),
                "fastball_velocity_count": 1,
            }
        )
    return pd.DataFrame(pa_rows), pd.DataFrame(pitch_rows)


def _prepared_history(rows: list[tuple[str, str]]) -> pd.DataFrame:
    pa_rows, pitch_rows = _history_inputs(rows)
    seasons = sorted({int(game_date[:4]) for _pa_id, game_date in rows})
    return prepare_pa_history(pa_rows, pitch_rows, allowed_seasons=seasons)


def test_shifted_source_pa_changes_only_causally_exposed_rolling_window() -> None:
    original_rows = [
        ("target-before", "2025-01-01"),
        ("target-between", "2025-01-03"),
        ("source-shifted", "2025-01-04"),
        ("target-after", "2025-01-05"),
    ]
    shifted_rows = [
        (pa_id, "2025-01-02" if pa_id == "source-shifted" else game_date)
        for pa_id, game_date in original_rows
    ]
    matched = pd.DataFrame(
        {
            "canonicalPaId": [
                "target-before",
                "target-between",
                "target-after",
            ]
        }
    )

    original_rates, original_stats = build_advanced_features_with_sufficient_statistics(
        _prepared_history(original_rows), matched
    )
    shifted_rates, shifted_stats = build_advanced_features_with_sufficient_statistics(
        _prepared_history(shifted_rows), matched
    )

    stats_changed = ~np.isclose(
        original_stats.to_numpy(dtype=np.float64),
        shifted_stats.to_numpy(dtype=np.float64),
        equal_nan=True,
    ).all(axis=1)
    rates_changed = ~np.isclose(
        original_rates.to_numpy(dtype=np.float64),
        shifted_rates.to_numpy(dtype=np.float64),
        equal_nan=True,
    ).all(axis=1)
    assert stats_changed.tolist() == [False, True, False]
    assert rates_changed.tolist() == [False, True, False]


def _development_companion_bytes(
    pa_rows: pd.DataFrame,
    rolling: pd.DataFrame,
) -> bytes:
    by_id = pa_rows.set_index("canonicalPaId")
    payload = pd.DataFrame(
        {
            "canonicalPaId": rolling.index.map(lambda index: pa_rows.iloc[index]["canonicalPaId"]),
            "game_date": rolling.index.map(
                lambda index: date.fromisoformat(pa_rows.iloc[index]["gameDate"])
            ),
            "season": rolling.index.map(lambda index: int(pa_rows.iloc[index]["season"])),
            "datasetRole": "DEVELOPMENT_SELECTION",
            "materialization_status": stats.DEVELOPMENT_MATERIALIZED,
            "materialization_reason": None,
        },
        index=rolling.index,
    )
    assert by_id.index.is_unique
    for column in stats.INTEGER_COUNT_COLUMNS:
        payload[column] = 0
    for column in stats.ELIGIBLE_SEASON_COLUMNS:
        payload[column] = payload["season"]
    for column in stats.FLOAT_COLUMNS:
        payload[column] = 0.0
    for column in rolling.columns:
        payload[column] = rolling[column]
    return stats._parquet_bytes(stats._validate_payload_frame(payload))


def test_future_season_append_leaves_2023_2025_companion_bytes_identical() -> None:
    base_rows = [
        ("target-2023", "2023-04-01"),
        ("target-2024", "2024-04-01"),
        ("target-2025", "2025-04-01"),
    ]
    future_rows = [*base_rows, ("source-shifted", "2026-04-01")]
    matched = pd.DataFrame(
        {"canonicalPaId": ["target-2023", "target-2024", "target-2025"]}
    )
    base_pa, base_pitch = _history_inputs(base_rows)
    future_pa, future_pitch = _history_inputs(future_rows)
    base_history = prepare_pa_history(
        base_pa, base_pitch, allowed_seasons=(2023, 2024, 2025)
    )
    future_history = prepare_pa_history(
        future_pa, future_pitch, allowed_seasons=(2023, 2024, 2025, 2026)
    )

    base_rates, base_stats = build_advanced_features_with_sufficient_statistics(
        base_history, matched
    )
    future_rates, future_stats = build_advanced_features_with_sufficient_statistics(
        future_history, matched
    )

    pd.testing.assert_frame_equal(base_rates, future_rates)
    pd.testing.assert_frame_equal(base_stats, future_stats)
    assert _development_companion_bytes(base_pa, base_stats) == (
        _development_companion_bytes(base_pa, future_stats)
    )


def test_annual_components_use_latest_eligible_prior_and_preserve_rookie_nulls() -> None:
    development = pd.DataFrame(
        [
            {
                "canonicalPaId": "pa-established",
                "season": 2023,
                "batterCanonicalPlayerId": "b-1",
                "pitcherCanonicalPlayerId": "p-1",
            },
            {
                "canonicalPaId": "pa-rookie",
                "season": 2023,
                "batterCanonicalPlayerId": "b-rookie",
                "pitcherCanonicalPlayerId": "p-rookie",
            },
        ]
    )
    identities = {
        "b-1": "uuid-b",
        "p-1": "uuid-p",
        "b-rookie": "uuid-b-rookie",
        "p-rookie": "uuid-p-rookie",
    }
    without_same_season = stats._annual_sufficient_statistics(
        development,
        canonical_to_chadwick=identities,
        player_priors=_annual_prior_table(include_same_season=False),
    )
    with_same_season = stats._annual_sufficient_statistics(
        development,
        canonical_to_chadwick=identities,
        player_priors=_annual_prior_table(include_same_season=True),
    )

    pd.testing.assert_frame_equal(without_same_season, with_same_season)
    established = with_same_season.iloc[0]
    assert established["batter_prior_ab"] == 200
    assert established["pitcher_prior_ipouts"] == 300
    assert established["batter_prior_eligible_from_season"] == 2023
    assert established["pitcher_prior_eligible_from_season"] == 2023
    rookie = with_same_season.iloc[1]
    annual_count_columns = [
        name
        for name, _metric in (*stats.ANNUAL_BATTING_FIELDS, *stats.ANNUAL_PITCHING_FIELDS)
    ]
    assert rookie[annual_count_columns].isna().all()
    assert rookie[list(stats.ELIGIBLE_SEASON_COLUMNS)].isna().all()
    missingness_frame = development.assign(
        batter_prior_missing=[0.0, 1.0],
        pitcher_prior_missing=[0.0, 1.0],
    )
    stats._assert_annual_missingness_parity(missingness_frame, with_same_season)
    with pytest.raises(CurrentStatcastPipelineError, match="differs from Gold missingness"):
        stats._assert_annual_missingness_parity(
            missingness_frame.assign(batter_prior_missing=[0.0, 0.0]),
            with_same_season,
        )


def test_final_oot_payload_is_null_and_physical_schema_is_exact() -> None:
    validated = stats._validate_payload_frame(_valid_payload_frame())
    oot = validated.loc[validated["datasetRole"].eq("FINAL_OOT")]
    assert oot[list(stats.SUFFICIENT_STATISTIC_COLUMNS)].isna().all(axis=None)
    assert oot[["game_date", "season"]].isna().all(axis=None)
    allowed = {
        "canonicalPaId",
        "datasetRole",
        "materialization_status",
        "materialization_reason",
    }
    assert set(oot.columns[oot.notna().any(axis=0)]) == allowed
    assert all(str(validated[name].dtype) == "Int64" for name in stats.INTEGER_COUNT_COLUMNS)
    assert all(str(validated[name].dtype) == "Float64" for name in stats.FLOAT_COLUMNS)

    first = stats._parquet_bytes(validated)
    second = stats._parquet_bytes(validated)
    assert first == second
    table = pq.read_table(pa.BufferReader(first))
    assert table.schema.remove_metadata() == stats.sufficient_statistics_schema()

    leaked = _valid_payload_frame()
    leaked.loc[leaked["datasetRole"].eq("FINAL_OOT"), stats.INTEGER_COUNT_COLUMNS[0]] = 1
    with pytest.raises(CurrentStatcastPipelineError, match="FINAL_OOT row carries fields"):
        stats._validate_payload_frame(leaked)

    broken = _valid_payload_frame()
    broken.loc[broken["datasetRole"].eq("DEVELOPMENT_SELECTION"), "pitcher_last250_pitch_count"] = 1
    with pytest.raises(CurrentStatcastPipelineError, match="pitch-composition invariant"):
        stats._validate_payload_frame(broken)


def test_all_gold_declared_upstreams_must_match_exactly() -> None:
    upstream = _gold_upstream()
    gold_manifest = {"sourceAuthorities": upstream}
    silver = {
        "existingSilverPa": upstream["existingSilverPa"],
        "existingSilverPitch": upstream["existingSilverPitch"],
        "currentSilverManifestSha256": upstream["currentSilverManifestSha256"],
    }
    bound = stats._bind_gold_upstream_authorities(
        gold_manifest,
        silver_authority=silver,
        identity_authority=upstream["playerIdentity"],
        prior_authority=upstream["playerPrior"],
    )
    assert bound["verifiedExact"] is True
    assert bound["authorities"] == upstream
    assert bound["sha256"] == sha256_bytes(canonical_json_bytes(upstream))

    with pytest.raises(CurrentStatcastPipelineError, match="currentSilverManifestSha256"):
        stats._bind_gold_upstream_authorities(
            gold_manifest,
            silver_authority={**silver, "currentSilverManifestSha256": "7" * 64},
            identity_authority=upstream["playerIdentity"],
            prior_authority=upstream["playerPrior"],
        )


def test_gold_authentication_uses_only_keys_and_development_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values: dict[str, list[Any]] = {
        "canonicalPaId": ["pa-development", "pa-oot"],
        "game_date": [date(2023, 3, 30), date(2026, 8, 14)],
        "season": [2023, 2026],
        "datasetRole": ["DEVELOPMENT_SELECTION", "FINAL_OOT"],
        "batterCanonicalPlayerId": ["b-1", "b-2"],
        "pitcherCanonicalPlayerId": ["p-1", "p-2"],
        "outcome": ["DO_NOT_READ", "SEALED_DO_NOT_READ"],
    }
    for name in stats._GOLD_DEVELOPMENT_COLUMNS:
        if name not in values:
            values[name] = [0.0, 999.0]
    table = pa.table(values)
    object_dir = tmp_path / "objects" / "sha256"
    object_dir.mkdir(parents=True)
    object_path = object_dir / "gold.parquet"
    pq.write_table(table, object_path)
    object_sha = sha256_bytes(object_path.read_bytes())
    manifest = {
        "datasetId": stats.CURRENT_GOLD_DATASET_ID,
        "featureNames": list(GOLD_FEATURES),
        "featureCount": 48,
        "rowCount": 2,
        "dateCoverage": {"earliestDate": "2023-03-30", "latestDate": "2026-08-14"},
        "sourceAuthorities": _gold_upstream(),
        "partitions": [
            {
                "season": 2026,
                "relativePath": object_path.relative_to(tmp_path).as_posix(),
                "sha256": object_sha,
                "rowCount": 2,
                "minimumDate": "2023-03-30",
                "maximumDate": "2026-08-14",
            }
        ],
    }
    manifest_bytes = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(manifest_bytes)
    manifest_path = tmp_path / "publications" / "sha256" / manifest_sha / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_bytes(manifest_bytes)
    locator = {
        "datasetId": stats.CURRENT_GOLD_DATASET_ID,
        "manifestSha256": manifest_sha,
        "manifestRelativePath": manifest_path.relative_to(tmp_path).as_posix(),
    }
    (tmp_path / "current.json").write_text(json.dumps(locator), encoding="utf-8")

    original_read_table = pq.read_table
    projections: list[tuple[str, ...]] = []

    def recording_read_table(*args: Any, **kwargs: Any) -> pa.Table:
        columns = kwargs.get("columns")
        if columns is not None:
            projections.append(tuple(columns))
        return original_read_table(*args, **kwargs)

    monkeypatch.setattr(stats.pq, "read_table", recording_read_table)
    _, loaded_sha, keys, development, _ = stats._load_gold_without_target(
        tmp_path, manifest_sha
    )

    assert loaded_sha == manifest_sha
    assert len(keys) == 2 and len(development) == 1
    assert projections == [stats.GOLD_KEY_COLUMNS, stats._GOLD_DEVELOPMENT_COLUMNS]
    assert all("outcome" not in projection for projection in projections)
    assert "game_date" not in projections[0] and "season" not in projections[0]
    assert "outcome" not in keys and "outcome" not in development

    bad_locator = {**locator, "manifestSha256": "a" * 64}
    (tmp_path / "current.json").write_text(json.dumps(bad_locator), encoding="utf-8")
    with pytest.raises(CurrentStatcastPipelineError, match="authenticated current locator"):
        stats._load_gold_without_target(tmp_path, manifest_sha)


def test_deterministic_publication_keeps_oot_unmaterialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upstream = _gold_upstream()
    gold_manifest = {
        "datasetId": stats.CURRENT_GOLD_DATASET_ID,
        "featureCount": 48,
        "sourceAuthorities": upstream,
    }
    source_identity = _valid_payload_frame()[
        list(stats.COMPANION_IDENTITY_COLUMNS)
    ].copy()
    source_identity.loc[
        source_identity["datasetRole"].eq("FINAL_OOT"), "game_date"
    ] = date(2026, 8, 14)
    source_identity.loc[
        source_identity["datasetRole"].eq("FINAL_OOT"), "season"
    ] = 2026
    keys = source_identity[list(stats.GOLD_KEY_COLUMNS)].copy()
    development = source_identity.loc[
        source_identity["datasetRole"].eq("DEVELOPMENT_SELECTION")
    ].copy()
    development["batterCanonicalPlayerId"] = "b-1"
    development["pitcherCanonicalPlayerId"] = "p-1"
    development["batter_prior_missing"] = 0.0
    development["pitcher_prior_missing"] = 0.0
    payload = _valid_payload_frame().loc[
        lambda frame: frame["datasetRole"].eq("DEVELOPMENT_SELECTION"),
        list(stats.SUFFICIENT_STATISTIC_COLUMNS),
    ].reset_index(drop=True)
    silver = {
        "currentSilverManifestSha256": upstream["currentSilverManifestSha256"],
        "existingSilverPa": upstream["existingSilverPa"],
        "existingSilverPitch": upstream["existingSilverPitch"],
        "developmentPaRowsRead": 1,
        "maximumPaHistoryDateRead": "2026-08-13",
        "finalOotPaRowsRead": 0,
        "finalOotPitchRowsRead": 0,
    }
    monkeypatch.setattr(
        stats,
        "_load_gold_without_target",
        lambda *_args, **_kwargs: (
            gold_manifest,
            "9" * 64,
            keys,
            development,
            {"currentSha256": "c" * 64, "manifestSha256": "9" * 64, "partitionSha256": {}},
        ),
    )
    monkeypatch.setattr(
        stats,
        "_load_development_history",
        lambda **_kwargs: (pd.DataFrame(), silver),
    )
    monkeypatch.setattr(
        stats,
        "build_advanced_features_with_sufficient_statistics",
        lambda *_args, **_kwargs: (
            pd.DataFrame(index=[0]),
            payload[list(stats.ROLLING_INTEGER_COLUMNS) + list(stats.FLOAT_COLUMNS)],
        ),
    )
    monkeypatch.setattr(
        stats,
        "_load_dim_player",
        lambda *_args: ({"b-1": "uuid-b", "p-1": "uuid-p"}, upstream["playerIdentity"]),
    )
    monkeypatch.setattr(
        stats,
        "_load_player_priors",
        lambda *_args: (pa.table({"placeholder": []}), upstream["playerPrior"]),
    )
    annual_columns = [
        name for name in stats.SUFFICIENT_STATISTIC_COLUMNS
        if name not in (*stats.ROLLING_INTEGER_COLUMNS, *stats.FLOAT_COLUMNS)
    ]
    monkeypatch.setattr(
        stats,
        "_annual_sufficient_statistics",
        lambda *_args, **_kwargs: payload[annual_columns],
    )
    monkeypatch.setattr(
        stats,
        "_equivalence_report",
        lambda *_args, **_kwargs: {
            "validatedDevelopmentRows": 1,
            "validatedFeatureCount": 12,
            "perFeatureMaximumAbsoluteError": {},
            "maximumAbsoluteReconstructionError": 0.0,
            "tolerance": 1e-6,
            "pitcherEra9Reconstructed": False,
            "retiredQaFeaturesReconstructed": ["batter_obp", "batter_last100_contact_rate"],
        },
    )
    monkeypatch.setattr(stats, "_assert_gold_snapshot", lambda *_args: None)

    first = stats.build_current_sufficient_stats(
        current_silver_root=tmp_path / "current-silver",
        existing_silver_root=tmp_path / "existing-silver",
        current_gold_root=tmp_path / "gold",
        exchange_root=tmp_path / "exchange",
        output_root=tmp_path / "companion",
    )
    manifest_path = Path(first["manifestPath"])
    locator_path = tmp_path / "companion" / "current-sufficient-stats.json"
    preserved_timestamp_ns = 946_684_800_000_000_000
    os.utime(manifest_path, ns=(preserved_timestamp_ns, preserved_timestamp_ns))
    os.utime(locator_path, ns=(preserved_timestamp_ns, preserved_timestamp_ns))
    second = stats.build_current_sufficient_stats(
        current_silver_root=tmp_path / "current-silver",
        existing_silver_root=tmp_path / "existing-silver",
        current_gold_root=tmp_path / "gold",
        exchange_root=tmp_path / "exchange",
        output_root=tmp_path / "companion",
    )

    assert first["manifestSha256"] == second["manifestSha256"]
    assert manifest_path.stat().st_mtime_ns == preserved_timestamp_ns
    assert locator_path.stat().st_mtime_ns == preserved_timestamp_ns
    assert [item["sha256"] for item in first["partitions"]] == [
        item["sha256"] for item in second["partitions"]
    ]
    assert first["objectSha256"] == [
        item["sha256"] for item in first["partitions"]
    ]
    assert first["verified"] is True
    oot_partition = next(
        item for item in first["partitions"]
        if item["partitionRole"] == stats.FINAL_OOT_SEALED
    )
    published = pq.read_table(
        tmp_path / "companion" / oot_partition["relativePath"]
    ).to_pandas()
    oot = published.loc[published["datasetRole"].eq("FINAL_OOT")]
    assert oot[list(stats.SUFFICIENT_STATISTIC_COLUMNS)].isna().all(axis=None)
    assert oot[["game_date", "season"]].isna().all(axis=None)
    assert oot["materialization_reason"].eq(stats.FINAL_OOT_SEALED).all()
    assert first["sourceAuthorities"]["goldDeclaredUpstream"]["authorities"] == upstream

    gold_manifest_path = (
        tmp_path / "gold" / "publications" / "sha256" / ("9" * 64) / "manifest.json"
    )
    gold_manifest_path.parent.mkdir(parents=True)
    gold_key_path = tmp_path / "gold" / "objects" / "keys.parquet"
    gold_key_path.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pandas(source_identity, preserve_index=False), gold_key_path
    )
    gold_manifest["partitions"] = [
        {"relativePath": gold_key_path.relative_to(tmp_path / "gold").as_posix()}
    ]
    gold_manifest_path.write_text(json.dumps(gold_manifest), encoding="utf-8")
    monkeypatch.setattr(
        stats,
        "_gold_locator_manifest_sha",
        lambda _root, requested: str(requested),
    )
    monkeypatch.setattr(
        stats,
        "verify_current_gold",
        lambda *_args, **_kwargs: {"rowCount": 2, "verified": True},
    )
    verified = stats.verify_current_sufficient_stats(
        tmp_path / "companion", current_gold_root=tmp_path / "gold"
    )
    assert verified["verified"] is True
    assert stats._binding_authority_checksum_is_valid(verified["bindingAuthority"])


def test_build_cli_summary_reports_verified_object_shas(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sufficient_stats_cli,
        "build_current_sufficient_stats",
        lambda **_kwargs: {
            "datasetId": stats.CURRENT_SUFFICIENT_STATS_DATASET_ID,
            "manifestSha256": "a" * 64,
            "objectSha256": ["b" * 64, "c" * 64],
            "rowCount": 2,
            "developmentRowCount": 1,
            "finalOotKeyRowCount": 1,
            "verified": True,
            "manifestPath": "excluded-from-summary",
        },
    )

    assert sufficient_stats_cli.main(["--summary", "--no-publish-current"]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["objectSha256"] == ["b" * 64, "c" * 64]
    assert summary["verified"] is True
    assert "manifestPath" not in summary


def _seed_source_registration(connection: Any, registration_id: str, suffix: str) -> None:
    connection.execute(
        """
        INSERT INTO sports_dataset_registrations (
          registration_id, dataset_id, dataset_version_id, manifest_id, manifest_sha,
          package_id, sport, league, evidence_cutoff, published_at, logical_package_root,
          validation_status, registered_at, last_validated_at, registered_by, rights_status,
          limitation_count, active, totals_json, seasons_json, evidence_coverage_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, 'BASEBALL', 'MLB', '2026-08-27',
                  '2026-08-27T00:00:00Z', ?, 'VALID', '2026-08-27T00:00:00Z',
                  '2026-08-27T00:00:00Z', 'test', 'SOURCE', 0, 0, '{}', '[]', '{}', '{}')
        """,
        (
            registration_id,
            f"source-{suffix}",
            f"source-version-{suffix}",
            f"source-manifest-id-{suffix}",
            suffix * 64,
            f"source-package-{suffix}",
            f"asp://source/{suffix}",
        ),
    )


def _seed_source_right(
    connection: Any,
    rights_id: str,
) -> None:
    authority = stats._SOURCE_RIGHTS_EXPECTED[rights_id]
    connection.execute(
        """
        INSERT INTO sports_dataset_rights (
          registration_id, rights_control_id, display_name, source_name, status,
          allowed_uses_json, prohibited_uses_json, attribution, controls_json, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            authority["registrationId"],
            rights_id,
            rights_id,
            rights_id,
            authority["status"],
            json_dumps(authority["allowedUses"]),
            json_dumps(authority["prohibitedUses"]),
            authority["attribution"],
            json_dumps(authority["controls"]),
            json_dumps({"testAuthority": rights_id}),
        ),
    )


_FORBIDDEN_WAVE1_TABLES = (
    "stage3_feature_treatment_spec_versions",
    "stage3_feature_treatment_spec_events",
    "stage3_feature_set_versions",
    "stage3_feature_set_events",
    "stage3_treatment_policy_versions",
    "stage3_treatment_policy_events",
    "stage3_predicted_imputation_previews",
    "stage3_predicted_imputation_preview_events",
    "stage3_split_contract_versions",
    "stage3_split_contract_feature_sets",
    "stage3_split_contract_events",
    "models",
    "model_versions",
    "run_records",
    "analytical_runs",
    "scoring_runs",
    "sports_pa_research_runs",
    "sports_pa_candidates",
    "sports_pa_candidate_fold_metrics",
    "candidate_selection_decisions",
    "holdout_exposures",
    "evaluation_packages",
    "predictor_authorization_manifests",
    "decision_journal",
    "workflow_state",
)


def _table_counts(connection: Any, tables: tuple[str, ...]) -> dict[str, int]:
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def test_source_rights_reject_same_count_status_attribution_and_control_tampering(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "source-rights.db")
    database.initialize()
    with database.transaction() as connection:
        _seed_source_registration(connection, "sports-dataset-1b58d5d1def2c9b7", "a")
        _seed_source_registration(
            connection, "sports-dataset-current-statcast-03ca6dab30e760b2", "b"
        )
        for rights_id in stats._SOURCE_RIGHTS_EXPECTED:
            _seed_source_right(connection, rights_id)

    for column, tampered in (
        ("status", "USED"),
        ("attribution", "Nonempty but unauthorized attribution."),
        ("controls_json", json_dumps({"commercialRights": "AUTHORIZED"})),
    ):
        with database.transaction() as connection:
            original = connection.execute(
                f"SELECT {column} FROM sports_dataset_rights "
                "WHERE registration_id = ? AND rights_control_id = 'MLB_STATCAST'",
                (stats._SOURCE_RIGHTS_EXPECTED["MLB_STATCAST"]["registrationId"],),
            ).fetchone()[0]
            connection.execute(
                f"UPDATE sports_dataset_rights SET {column} = ? "
                "WHERE registration_id = ? AND rights_control_id = 'MLB_STATCAST'",
                (
                    tampered,
                    stats._SOURCE_RIGHTS_EXPECTED["MLB_STATCAST"]["registrationId"],
                ),
            )
        with database.connection() as connection:
            with pytest.raises(
                CurrentStatcastPipelineError, match="source rights authority differs"
            ):
                stats._source_rights_rows(connection)
        with database.transaction() as connection:
            connection.execute(
                f"UPDATE sports_dataset_rights SET {column} = ? "
                "WHERE registration_id = ? AND rights_control_id = 'MLB_STATCAST'",
                (
                    original,
                    stats._SOURCE_RIGHTS_EXPECTED["MLB_STATCAST"]["registrationId"],
                ),
            )


def test_registrar_is_idempotent_inactive_and_uses_only_stable_logical_uris(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = Database(tmp_path / "registry.db")
    database.initialize()
    with database.transaction() as connection:
        _seed_source_registration(connection, "sports-dataset-1b58d5d1def2c9b7", "a")
        _seed_source_registration(
            connection, "sports-dataset-current-statcast-03ca6dab30e760b2", "b"
        )
        _seed_source_right(connection, "SABR_LAHMAN_MODERN_MLB")
        _seed_source_right(connection, "CHADWICK_PERSONS_REGISTER")
        _seed_source_right(connection, "MLB_STATCAST")
        forbidden_before = _table_counts(connection, _FORBIDDEN_WAVE1_TABLES)

    manifest_sha = "c" * 64
    manifest = {
        "rowCount": 2,
        "developmentRowCount": 1,
        "finalOotKeyRowCount": 1,
        "rowsBySeason": {"2026": 1},
        "rights": stats._RIGHTS_CONTRACT,
        "physicalSchema": {
            "fields": stats._physical_schema_contract(),
            "sha256": "d" * 64,
        },
        "validationEvidenceSha256": "e" * 64,
        "sourceAuthorities": {
            "currentGold": {"manifestSha256": "f" * 64},
            "goldDeclaredUpstream": {
                "sha256": "7" * 64,
                "authorities": {"currentSilverManifestSha256": "8" * 64},
            },
        },
        "partitions": [
            {
                "season": 2026,
                "partitionRole": "DEVELOPMENT_SELECTION",
                "rowDateMaterialized": True,
                "rowSeasonMaterialized": True,
                "rowCount": 1,
                "developmentRowCount": 1,
                "finalOotKeyRowCount": 0,
                "byteCount": 61,
                "minimumDate": "2026-08-13",
                "maximumDate": "2026-08-13",
                "sha256": "1" * 64,
            },
            {
                "season": 2026,
                "partitionRole": stats.FINAL_OOT_SEALED,
                "rowDateMaterialized": False,
                "rowSeasonMaterialized": False,
                "rowCount": 1,
                "developmentRowCount": 0,
                "finalOotKeyRowCount": 1,
                "byteCount": 62,
                "minimumDate": "2026-08-14",
                "maximumDate": "2026-08-27",
                "sha256": "2" * 64,
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    unsigned_binding = {
        "schemaVersion": "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1",
        "datasetId": stats.CURRENT_SUFFICIENT_STATS_DATASET_ID,
        "manifestContract": stats.CURRENT_SUFFICIENT_STATS_CONTRACT,
        "manifestSha256": manifest_sha,
        "objectSha256": ["1" * 64, "2" * 64],
        "sourceGoldManifestSha256": "f" * 64,
        "sourceGoldUpstreamAuthoritiesSha256": "7" * 64,
        "sourceCurrentSilverManifestSha256": "8" * 64,
        "physicalSchemaSha256": "d" * 64,
        "validationEvidenceSha256": "e" * 64,
        "requiredColumns": list(stats.SUFFICIENT_STATISTIC_COLUMNS),
        "verified": True,
        "integerValidation": True,
        "equivalenceValidation": True,
        "finalOotSealed": True,
        "rightsStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
    }
    binding_checksum = sha256_bytes(canonical_json_bytes(unsigned_binding))
    binding = {
        **unsigned_binding,
        "authorityChecksum": binding_checksum,
        "authorityId": (
            "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:"
            f"{binding_checksum}"
        ),
    }
    monkeypatch.setattr(
        stats,
        "verify_current_sufficient_stats",
        lambda *_args, **_kwargs: {
            "manifestPath": str(manifest_path),
            "manifestSha256": manifest_sha,
            "bindingAuthority": binding,
        },
    )

    first = stats.register_current_sufficient_stats(
        database, output_root=tmp_path, registered_by="test"
    )
    second = stats.register_current_sufficient_stats(
        database, output_root=tmp_path, registered_by="different-operator"
    )

    assert first["registrationDisposition"] == "CREATED"
    assert second["registrationDisposition"] == "REUSED"
    assert second["writes"] == 0
    with database.connection() as connection:
        registration = connection.execute(
            "SELECT active, logical_package_root FROM sports_dataset_registrations WHERE registration_id = ?",
            (first["registrationId"],),
        ).fetchone()
        partitions = connection.execute(
            "SELECT partition_id, logical_uri FROM sports_dataset_partitions WHERE registration_id = ? ORDER BY partition_id",
            (first["registrationId"],),
        ).fetchall()
        rights = connection.execute(
            "SELECT rights_control_id FROM sports_dataset_rights WHERE registration_id = ? ORDER BY rights_control_id",
            (first["registrationId"],),
        ).fetchall()
        forbidden_after = _table_counts(connection, _FORBIDDEN_WAVE1_TABLES)
    assert registration["active"] == 0
    assert registration["logical_package_root"].startswith("asp://sports-datasets/")
    assert forbidden_after == forbidden_before == {
        table: 0 for table in _FORBIDDEN_WAVE1_TABLES
    }
    assert len({row["partition_id"] for row in partitions}) == 2
    assert len({row["logical_uri"] for row in partitions}) == 2
    assert all(
        row["logical_uri"].startswith(registration["logical_package_root"])
        for row in partitions
    )
    assert all(
        "\\" not in row["logical_uri"] and ":\\" not in row["logical_uri"]
        for row in partitions
    )
    assert [row["rights_control_id"] for row in rights] == [
        "CHADWICK_PERSONS_REGISTER",
        "MLB_STATCAST",
        "SABR_LAHMAN_MODERN_MLB",
    ]
    assert "PUBLIC_BULK_DOWNLOAD" in stats._RIGHTS_CONTRACT["prohibitedUses"]
    assert stats._RIGHTS_CONTRACT["commercialRights"] == "UNCLEAR_REQUIRES_REVIEW"

    child_tamper_cases = (
        (
            "sports_dataset_partitions",
            "logical_uri",
            "partition_id = ?",
            (partitions[0]["partition_id"],),
            "asp://tampered/same-count-partition",
        ),
        (
            "sports_dataset_schemas",
            "fields_json",
            "registration_id = ? AND family = 'sufficient_statistics'",
            (first["registrationId"],),
            "{}",
        ),
        (
            "sports_dataset_limitations",
            "description",
            "registration_id = ? AND limitation_id = ?",
            (
                first["registrationId"],
                "SUFFICIENT_STATS_COMPANION_NO_ACTIVATION",
            ),
            "Tampered limitation with unchanged row count.",
        ),
        (
            "sports_dataset_rights",
            "status",
            "registration_id = ? AND rights_control_id = 'MLB_STATCAST'",
            (first["registrationId"],),
            "USED",
        ),
        (
            "sports_dataset_rights",
            "attribution",
            "registration_id = ? AND rights_control_id = 'MLB_STATCAST'",
            (first["registrationId"],),
            "Nonempty but unauthorized attribution.",
        ),
        (
            "sports_dataset_rights",
            "controls_json",
            "registration_id = ? AND rights_control_id = 'MLB_STATCAST'",
            (first["registrationId"],),
            json_dumps({"commercialRights": "AUTHORIZED"}),
        ),
    )
    for table, column, predicate, parameters, tampered in child_tamper_cases:
        with database.transaction() as connection:
            original = connection.execute(
                f"SELECT {column} FROM {table} WHERE {predicate}", parameters
            ).fetchone()[0]
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {predicate}",
                (tampered, *parameters),
            )
        with pytest.raises(
            CurrentStatcastPipelineError,
            match=f"child content conflicts: {table}",
        ):
            stats.register_current_sufficient_stats(
                database, output_root=tmp_path, registered_by="test"
            )
        with database.transaction() as connection:
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {predicate}",
                (original, *parameters),
            )
    final_reuse = stats.register_current_sufficient_stats(
        database, output_root=tmp_path, registered_by="test"
    )
    assert final_reuse["registrationDisposition"] == "REUSED"
    assert final_reuse["writes"] == 0

    publication_manifest = (
        tmp_path
        / "sufficient-statistics"
        / "publications"
        / "sha256"
        / manifest_sha
        / "manifest.json"
    )
    publication_manifest.parent.mkdir(parents=True)
    publication_manifest.write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "current-sufficient-stats.json").write_text(
        json.dumps(
            {
                "datasetId": stats.CURRENT_SUFFICIENT_STATS_DATASET_ID,
                "manifestSha256": manifest_sha,
                "manifestRelativePath": publication_manifest.relative_to(
                    tmp_path
                ).as_posix(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(stats, "_sha_file", lambda _path: manifest_sha)
    monkeypatch.setattr(
        stats,
        "_authenticate_companion_object_metadata",
        lambda *_args, **_kwargs: ["1" * 64, "2" * 64],
    )
    assert stats.registered_sufficient_statistics_authority(
        database,
        expected_gold_manifest_sha256="f" * 64,
        output_root=tmp_path,
    ) == binding

    for field, tampered in (
        ("physicalSchemaSha256", "9" * 64),
        ("validationEvidenceSha256", "0" * 64),
        ("requiredColumns", list(reversed(stats.SUFFICIENT_STATISTIC_COLUMNS))),
    ):
        with database.transaction() as connection:
            original_metadata_json = connection.execute(
                "SELECT metadata_json FROM sports_dataset_registrations "
                "WHERE registration_id = ?",
                (first["registrationId"],),
            ).fetchone()[0]
            forged_metadata = json.loads(original_metadata_json)
            forged_binding = dict(forged_metadata["bindingAuthority"])
            forged_binding[field] = tampered
            forged_unsigned = {
                key: value
                for key, value in forged_binding.items()
                if key not in {"authorityChecksum", "authorityId"}
            }
            forged_checksum = sha256_bytes(canonical_json_bytes(forged_unsigned))
            forged_binding["authorityChecksum"] = forged_checksum
            forged_binding["authorityId"] = (
                "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:"
                f"{forged_checksum}"
            )
            assert stats._binding_authority_checksum_is_valid(forged_binding)
            forged_metadata["bindingAuthority"] = forged_binding
            connection.execute(
                "UPDATE sports_dataset_registrations SET metadata_json = ? "
                "WHERE registration_id = ?",
                (json_dumps(forged_metadata), first["registrationId"]),
            )
        assert stats.registered_sufficient_statistics_authority(
            database,
            expected_gold_manifest_sha256="f" * 64,
            output_root=tmp_path,
        ) is None
        with database.transaction() as connection:
            connection.execute(
                "UPDATE sports_dataset_registrations SET metadata_json = ? "
                "WHERE registration_id = ?",
                (original_metadata_json, first["registrationId"]),
            )

    registration_tamper_cases = (
        ("dataset_id", "tampered-dataset"),
        ("dataset_version_id", "tampered-version"),
        ("manifest_id", "tampered-manifest-id"),
        ("manifest_sha", "9" * 64),
        ("package_id", "tampered-package"),
        ("sport", "OTHER"),
        ("league", "OTHER"),
        ("evidence_cutoff", "2026-08-12"),
        ("published_at", "2026-08-26T23:59:59Z"),
        ("logical_package_root", "asp://tampered/root"),
        ("validation_status", "INVALID"),
        ("rights_status", "USED"),
        ("limitation_count", 2),
        ("active", 1),
        ("totals_json", "{}"),
        ("seasons_json", "[]"),
        ("evidence_coverage_json", "{}"),
        ("metadata_json", "{}"),
    )
    for column, tampered in registration_tamper_cases:
        with database.transaction() as connection:
            original = connection.execute(
                f"SELECT {column} FROM sports_dataset_registrations "
                "WHERE registration_id = ?",
                (first["registrationId"],),
            ).fetchone()[0]
            connection.execute(
                f"UPDATE sports_dataset_registrations SET {column} = ? "
                "WHERE registration_id = ?",
                (tampered, first["registrationId"]),
            )
        assert stats.registered_sufficient_statistics_authority(
            database,
            expected_gold_manifest_sha256="f" * 64,
            output_root=tmp_path,
        ) is None
        with database.transaction() as connection:
            connection.execute(
                f"UPDATE sports_dataset_registrations SET {column} = ? "
                "WHERE registration_id = ?",
                (original, first["registrationId"]),
            )

    for table, column, predicate, parameters, tampered in child_tamper_cases:
        with database.transaction() as connection:
            original = connection.execute(
                f"SELECT {column} FROM {table} WHERE {predicate}", parameters
            ).fetchone()[0]
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {predicate}",
                (tampered, *parameters),
            )
        assert stats.registered_sufficient_statistics_authority(
            database,
            expected_gold_manifest_sha256="f" * 64,
            output_root=tmp_path,
        ) is None
        with database.transaction() as connection:
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE {predicate}",
                (original, *parameters),
            )
    assert stats.registered_sufficient_statistics_authority(
        database,
        expected_gold_manifest_sha256="f" * 64,
        output_root=tmp_path,
    ) == binding


def test_runtime_object_gate_uses_only_parquet_metadata_and_rejects_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validated = stats._validate_payload_frame(_valid_payload_frame())
    data = stats._parquet_bytes(validated)
    object_sha = sha256_bytes(data)
    relative = f"objects/sha256/{object_sha}.parquet"
    object_path = tmp_path / relative
    object_path.parent.mkdir(parents=True)
    object_path.write_bytes(data)
    manifest = {
        "rowCount": 2,
        "partitions": [
            {"relativePath": relative, "sha256": object_sha, "rowCount": 2}
        ],
    }
    monkeypatch.setattr(
        stats.pq,
        "read_table",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("runtime authority must not load Parquet row payloads")
        ),
    )

    assert stats._authenticate_companion_object_metadata(tmp_path, manifest) == [
        object_sha
    ]

    object_path.write_bytes(data + b"tampered")
    with pytest.raises(CurrentStatcastPipelineError, match="partition SHA differs"):
        stats._authenticate_companion_object_metadata(tmp_path, manifest)


def test_binding_authority_checksum_and_id_are_both_required() -> None:
    unsigned = {
        "schemaVersion": "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1",
        "manifestSha256": "a" * 64,
        "objectSha256": ["b" * 64],
    }
    checksum = sha256_bytes(canonical_json_bytes(unsigned))
    signed = {
        **unsigned,
        "authorityChecksum": checksum,
        "authorityId": (
            "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:"
            f"{checksum}"
        ),
    }
    assert stats._binding_authority_checksum_is_valid(signed)
    assert not stats._binding_authority_checksum_is_valid(
        {**signed, "authorityChecksum": "0" * 64}
    )
    assert not stats._binding_authority_checksum_is_valid(
        {**signed, "authorityId": "forged"}
    )
