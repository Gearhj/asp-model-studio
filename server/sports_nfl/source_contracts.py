from __future__ import annotations

from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping


SOURCE_CONTRACT_VERSION = "NFLVERSE_SOURCE_FAMILY_V1"
BRONZE_MANIFEST_CONTRACT = "NFLVERSE_BRONZE_MANIFEST_V1"
BRONZE_CURRENT_CONTRACT = "NFLVERSE_BRONZE_CURRENT_V1"
PROVIDER_ID = "nflverse-data"
PROVIDER_REPOSITORY = "https://github.com/nflverse/nflverse-data"
LICENSE_ID = "CC-BY-4.0"
LICENSE_NAME = "Creative Commons Attribution 4.0 International"
LICENSE_URL = "https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md"
ATTRIBUTION = "nflverse / nflverse-data"


@dataclass(frozen=True)
class SourceFamilyContract:
    family_id: str
    release_tag: str
    asset_name_pattern: str
    mandatory: bool
    season_scoped: bool
    required_columns: tuple[str, ...]
    season_column: str | None
    date_column: str | None
    available_start_season: int | None = None
    available_end_season: int | None = None
    contract_version: str = SOURCE_CONTRACT_VERSION
    file_format: str = "parquet"
    license_id: str = LICENSE_ID
    license_name: str = LICENSE_NAME
    license_url: str = LICENSE_URL
    attribution: str = ATTRIBUTION


# Asset names are matched against the assets returned by the official
# nflverse-data GitHub release API.  The physical schema is intentionally not
# guessed here: every acquired Parquet schema is recorded exactly and is
# re-read and compared by the verifier.
NFLVERSE_SOURCE_FAMILIES_V1: Mapping[str, SourceFamilyContract] = MappingProxyType(
    {
        "schedules": SourceFamilyContract(
            "schedules", "schedules", r"^games\.parquet$", True, False,
            ("game_id", "season", "gameday"), "season", "gameday",
        ),
        "play_by_play": SourceFamilyContract(
            "play_by_play", "pbp", r"^play_by_play_{season}\.parquet$", True, True,
            ("game_id", "play_id", "season"), "season", "game_date", 1999, 2025,
        ),
        "teams": SourceFamilyContract(
            "teams", "teams", r"^teams_colors_logos\.parquet$", True, False,
            ("team_abbr",), None, None,
        ),
        "players": SourceFamilyContract(
            "players", "players", r"^players\.parquet$", True, False,
            ("gsis_id",), None, None,
        ),
        "rosters": SourceFamilyContract(
            "rosters", "rosters", r"^roster_{season}\.parquet$", True, True,
            ("gsis_id", "season"), "season", None, 1920, 2026,
        ),
        "weekly_rosters": SourceFamilyContract(
            "weekly_rosters", "weekly_rosters", r"^roster_weekly_{season}\.parquet$", True, True,
            ("gsis_id", "season", "week"), "season", None, 2002, 2026,
        ),
        "weekly_player_stats": SourceFamilyContract(
            "weekly_player_stats", "stats_player", r"^stats_player_week_{season}\.parquet$", True, True,
            ("player_id", "season", "week"), "season", None, 1999, 2025,
        ),
        "weekly_team_stats": SourceFamilyContract(
            "weekly_team_stats", "stats_team", r"^stats_team_week_{season}\.parquet$", True, True,
            ("team", "season", "week"), "season", None, 1999, 2025,
        ),
        "snap_counts": SourceFamilyContract(
            "snap_counts", "snap_counts", r"^snap_counts_{season}\.parquet$", False, True,
            ("season", "week"), "season", None, 2012, 2025,
        ),
        "participation": SourceFamilyContract(
            "participation", "pbp_participation", r"^pbp_participation_{season}\.parquet$", False, True,
            ("nflverse_game_id", "play_id"), None, None, 2016, 2025,
            license_id="CC-BY-SA-4.0",
            license_name="Creative Commons Attribution-ShareAlike 4.0 International",
            license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            attribution="FTN Data via nflverse",
        ),
        "ngs_passing": SourceFamilyContract(
            "ngs_passing", "nextgen_stats", r"^ngs_passing\.parquet$", False, False,
            ("season", "week"), "season", None, 2016, 2025,
        ),
        "ngs_receiving": SourceFamilyContract(
            "ngs_receiving", "nextgen_stats", r"^ngs_receiving\.parquet$", False, False,
            ("season", "week"), "season", None, 2016, 2025,
        ),
        "ngs_rushing": SourceFamilyContract(
            "ngs_rushing", "nextgen_stats", r"^ngs_rushing\.parquet$", False, False,
            ("season", "week"), "season", None, 2016, 2025,
        ),
        "ftn_charting": SourceFamilyContract(
            "ftn_charting", "ftn_charting", r"^ftn_charting_{season}\.parquet$", False, True,
            ("nflverse_game_id", "nflverse_play_id"), None, None, 2022, 2025,
            license_id="CC-BY-SA-4.0",
            license_name="Creative Commons Attribution-ShareAlike 4.0 International",
            license_url="https://creativecommons.org/licenses/by-sa/4.0/",
            attribution="FTN Data via nflverse",
        ),
        "injuries": SourceFamilyContract(
            "injuries", "injuries", r"^injuries_{season}\.parquet$", False, True,
            ("season", "week"), "season", None, 2009, 2025,
        ),
        "depth_charts": SourceFamilyContract(
            "depth_charts", "depth_charts", r"^depth_charts_{season}\.parquet$", False, True,
            # Older releases predate the timestamped `dt` schema.  Preserve
            # their actual schema without pretending a timestamp; the
            # canonical union exposes `dt` where newer source rows supply it.
            (), None, None, 2001, 2026,
        ),
        "officials": SourceFamilyContract(
            "officials", "officials", r"^officials\.parquet$", False, False,
            ("game_id",), None, None,
        ),
        "pfr_advanced_passing": SourceFamilyContract(
            "pfr_advanced_passing", "pfr_advstats", r"^advstats_week_pass_{season}\.parquet$", False, True,
            ("season", "week"), "season", None, 2018, 2025,
        ),
        "pfr_advanced_rushing": SourceFamilyContract(
            "pfr_advanced_rushing", "pfr_advstats", r"^advstats_week_rush_{season}\.parquet$", False, True,
            ("season", "week"), "season", None, 2018, 2025,
        ),
        "pfr_advanced_receiving": SourceFamilyContract(
            "pfr_advanced_receiving", "pfr_advstats", r"^advstats_week_rec_{season}\.parquet$", False, True,
            ("season", "week"), "season", None, 2018, 2025,
        ),
        "pfr_advanced_defense": SourceFamilyContract(
            "pfr_advanced_defense", "pfr_advstats", r"^advstats_week_def_{season}\.parquet$", False, True,
            ("season", "week"), "season", None, 2018, 2025,
        ),
        "draft_picks": SourceFamilyContract(
            "draft_picks", "draft_picks", r"^draft_picks\.parquet$", False, False,
            ("season",), "season", None,
        ),
        "combine": SourceFamilyContract(
            "combine", "combine", r"^combine\.parquet$", False, False,
            ("season",), "season", None,
        ),
        "trades": SourceFamilyContract(
            "trades", "trades", r"^trades\.parquet$", False, False,
            (), None, None,
        ),
        "contracts": SourceFamilyContract(
            "contracts", "contracts", r"^contracts\.parquet$", False, False,
            (), None, None,
        ),
    }
)


# V1 is immutable verification authority for every already published Bronze
# manifest. V2 changes only the three core families whose physical 2026 assets
# were verified in official release metadata on 2026-09-13. Optional families
# are not inferred available from the calendar year.
CORE_2026_FAMILIES = ("play_by_play", "weekly_player_stats", "weekly_team_stats")
COVERAGE_POLICY_V2 = "NFLVERSE_CORE_CURRENT_2026_V2"
BRONZE_MANIFEST_CONTRACT_V2 = "NFLVERSE_BRONZE_MANIFEST_V2"
SOURCE_CONTRACT_VERSION_V2 = "NFLVERSE_SOURCE_FAMILY_V2"
NFLVERSE_SOURCE_FAMILIES: Mapping[str, SourceFamilyContract] = MappingProxyType({
    family: replace(contract, available_end_season=2026,
                    contract_version=SOURCE_CONTRACT_VERSION_V2)
    if family in CORE_2026_FAMILIES else contract
    for family, contract in NFLVERSE_SOURCE_FAMILIES_V1.items()
})


def source_families_for_manifest(manifest: Mapping) -> Mapping[str, SourceFamilyContract]:
    """Select exact completeness rules from the immutable manifest version."""
    identity = (manifest.get("contract"), manifest.get("version"))
    if identity == (BRONZE_MANIFEST_CONTRACT, 1) and "coveragePolicy" not in manifest:
        return NFLVERSE_SOURCE_FAMILIES_V1
    if identity == (BRONZE_MANIFEST_CONTRACT_V2, 2) and manifest.get("coveragePolicy") == COVERAGE_POLICY_V2:
        return NFLVERSE_SOURCE_FAMILIES
    raise ValueError("Unknown NFL Bronze manifest coverage policy")


def source_contract_for_partition(families: Mapping[str, SourceFamilyContract],
                                  family_id: str, season: int | None) -> SourceFamilyContract:
    """Historical partition metadata retains its original V1 source contract."""
    contract = families[family_id]
    if family_id in CORE_2026_FAMILIES and season != 2026:
        return NFLVERSE_SOURCE_FAMILIES_V1[family_id]
    return contract


MANDATORY_FAMILIES = tuple(
    family_id for family_id, contract in NFLVERSE_SOURCE_FAMILIES.items() if contract.mandatory
)
OPTIONAL_FAMILIES = tuple(
    family_id for family_id, contract in NFLVERSE_SOURCE_FAMILIES.items() if not contract.mandatory
)
