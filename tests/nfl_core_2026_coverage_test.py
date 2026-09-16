"""Focused source-policy checks; synthetic metadata only, no provider calls."""
from unittest.mock import patch

from server.sports_nfl import current_season_sync as sync
from server.sports_nfl.bronze_acquisition import ReleaseAsset, focused_current_core_checks
from server.sports_nfl.pipeline import NflFoundationConfig
from server.sports_nfl.source_contracts import CORE_2026_FAMILIES


def test_v1_preservation_and_v2_completeness():
    # Exercises actual Bronze verification on tiny synthetic Parquet objects;
    # checks invalid V2 completeness/policy/source-version rejection as well.
    result = focused_current_core_checks()
    assert result["allPassed"]


def test_catch_up_probe_preserves_historical_partition_contracts():
    config = sync.NflCurrentSeasonSyncConfig(
        foundation=NflFoundationConfig(seasons=(2025, 2026)), mode=sync.CATCH_UP)
    calls = []

    def discover(contract, season, **kwargs):
        calls.append((contract.family_id, season, contract.contract_version))
        return ReleaseAsset(contract.family_id, contract.release_tag,
            "2026-09-13T00:00:00Z", "synthetic.parquet", "https://example.invalid/synthetic",
            1, 1, "sha256:" + "0"*64, "2026-09-13T00:00:00Z", "2026-09-13T00:00:00Z")

    with patch.object(sync, "_allowed_family_ids", return_value=CORE_2026_FAMILIES), \
            patch.object(sync, "discover_release_asset", side_effect=discover):
        snapshot = sync._default_probe_sources(config)
    expected = [(family, season, "NFLVERSE_SOURCE_FAMILY_V1" if season == 2025 else "NFLVERSE_SOURCE_FAMILY_V2")
                for family in CORE_2026_FAMILIES for season in (2025, 2026)]
    assert calls == expected
    assert {(row["familyId"], row["season"], row["contractVersion"]) for row in snapshot["assets"]} == set(expected)
