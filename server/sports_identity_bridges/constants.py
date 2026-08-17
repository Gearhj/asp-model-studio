from __future__ import annotations

from pathlib import PurePosixPath

from ..sports_datasets.constants import (
    DATASET_ID as PARENT_DATASET_ID,
    DATASET_VERSION_ID as PARENT_DATASET_VERSION_ID,
    LOGICAL_PACKAGE_ROOT as PARENT_LOGICAL_PACKAGE_ROOT,
    MANIFEST_ID as PARENT_MANIFEST_ID,
    MANIFEST_SHA as PARENT_MANIFEST_SHA,
    PACKAGE_ID as PARENT_PACKAGE_ID,
    PARTITION_AUTHORITY_SHA as PARENT_PARTITION_AUTHORITY_SHA,
    PA_CLASS_ORDER,
    PROJECT_ID,
    REGISTRATION_ID as PARENT_REGISTRATION_ID,
)


CONTRACT_NAME = "SPORTS_IDENTITY_BRIDGE"
CONTRACT_VERSION = "SPORTS_IDENTITY_BRIDGE_V1"
CANONICALIZATION_VERSION = "SPORTS_CANONICAL_JSON_V1"
PUBLISHER = "AI Sports Predictor"
SPORT = "Baseball"
LEAGUE = "MLB"
EVIDENCE_CUTOFF = "2026-08-15"
PUBLICATION_TIMESTAMP = "2026-08-17T04:20:53.179362Z"

BRIDGE_MANIFEST_SHA = "6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf"
BRIDGE_MANIFEST_ID = f"sports-identity-bridge-manifest:sha256:{BRIDGE_MANIFEST_SHA}"
BRIDGE_PACKAGE_ID = f"sha256-{BRIDGE_MANIFEST_SHA}"
BRIDGE_REGISTRATION_ID = f"sports-identity-bridge-{BRIDGE_MANIFEST_SHA[:16]}"

PACKAGE_RELATIVE_ROOT = (
    PurePosixPath("identity-bridges")
    / "mlb-fd1"
    / f"manifest-sha256-{PARENT_MANIFEST_SHA}"
    / BRIDGE_PACKAGE_ID
)
LOGICAL_PACKAGE_ROOT = f"asp-model-exchange://{PACKAGE_RELATIVE_ROOT.as_posix()}"

ALIAS_FILE = "player-identity-aliases.parquet"
DIMENSION_FILE = "active-player-dimension.parquet"
MANIFEST_FILE = "sports-identity-bridge-manifest.json"
VALIDATION_REPORT_FILE = "validation-report.json"
SOURCE_RIGHTS_FILE = "source-rights.json"

ALIAS_FILE_SHA = "21890289fdf6e9ba5a5b88d74ae131bc6f6526438a1029281573ff96a301abe6"
DIMENSION_FILE_SHA = "2e398636c5de415ad6c90fff190666397030163fd30c49cf44a25f3e2031656c"
MANIFEST_FILE_SHA = "1e10d23eb1b9fc313b02483f631595b8ff11a91284e9a56ff8ddad6a92965475"
VALIDATION_REPORT_SHA = "caacf363c6cd4205b823b5c0137fb734d9c640de12cdbffcca0e4fed972eef9b"
SOURCE_RIGHTS_SHA = "a67e626865f43911c8de14cb8287bdf810e846a625d28470b8c73573564b1e02"
README_SHA = "4d987b2b57fa8fbdf952680cb3a3fd56d5416355e4e553d3e7947aa7e0964fd7"
ATTRIBUTION_SHA = "d456cc1799e6194e1ad9d1db673b2565e2e64fbcf9b1425e5b74188ab2ba9e79"
ALIAS_AUTHORITY_SHA = "ddb828aee391b2f725ba4540a874865963313e6c210f246eacd7bbcf28025661"
DIMENSION_AUTHORITY_SHA = "6f30e1b30ca41002d6cbb2dea8b90da5abfad4f62f96237e780fbee518005acf"
ALIAS_SCHEMA_FINGERPRINT = "7c7e838d1ad5b15488cefc3b34e0f4d34ca52ddf01348e2fdf61f0d9afd6e037"
DIMENSION_SCHEMA_FINGERPRINT = "ba7486358a5897b19be44512eeff04549562598e53a3b37683a769283c295526"

EXPECTED_FILES = {
    DIMENSION_FILE: (183_341, DIMENSION_FILE_SHA),
    "attribution.md": (1_424, ATTRIBUTION_SHA),
    ALIAS_FILE: (1_848_549, ALIAS_FILE_SHA),
    "README.md": (2_027, README_SHA),
    SOURCE_RIGHTS_FILE: (9_576, SOURCE_RIGHTS_SHA),
    MANIFEST_FILE: (18_467, MANIFEST_FILE_SHA),
    VALIDATION_REPORT_FILE: (8_356, VALIDATION_REPORT_SHA),
}
EXPECTED_PACKAGE_FILES = 7
EXPECTED_PACKAGE_BYTES = 2_071_740
EXPECTED_SEMANTIC_FILES = 4
EXPECTED_SEMANTIC_BYTES = 2_042_890
EXPECTED_ALIAS_ROWS = 13_460
EXPECTED_ACTIVE_PLAYER_ROWS = 2_692
EXPECTED_GOVERNED_ACTIVE_PLAYERS = 2_693
EXPECTED_PRIMARY_PORTABLE_PLAYERS = 2_070
EXPECTED_PRIMARY_GOVERNED_PLAYERS = 2_071
EXPECTED_NAMESPACE_COUNT = 5
EXPECTED_ALIASES_PER_NAMESPACE = 2_692
EXPECTED_JOIN_CONTRACTS = 10
EXPECTED_JOIN_REFERENCES = 4_633_762
EXPECTED_Y_MINUS_1_RECORDS = 6

EXPECTED_NAMESPACES = (
    "RETROSHEET",
    "LAHMAN",
    "CHADWICK",
    "MLBAM",
    "BASEBALL_REFERENCE",
)

EXPECTED_NAMESPACE_SOURCES = {
    "RETROSHEET": (
        "CHADWICK_REGISTER_ARCHIVES",
        "4a4956de-0769-4bb0-9dc4-cc30515ba16a",
        "8aa66c044fb49ceb681af16fb4c20bef582f94e56cdcc790f2634d26f1bf36b0",
    ),
    "LAHMAN": (
        "SABR_LAHMAN_BOX_DOWNLOADS",
        "3af682f0-ecdb-47d8-8e14-660ec5f7455c",
        "61d462de4f4030263ce46a01ee213d211adbd26ff869365ec18b3477063a3cf5",
    ),
    "CHADWICK": (
        "CHADWICK_REGISTER_ARCHIVES",
        "4a4956de-0769-4bb0-9dc4-cc30515ba16a",
        "8aa66c044fb49ceb681af16fb4c20bef582f94e56cdcc790f2634d26f1bf36b0",
    ),
    "MLBAM": (
        "CHADWICK_REGISTER_ARCHIVES",
        "4a4956de-0769-4bb0-9dc4-cc30515ba16a",
        "8aa66c044fb49ceb681af16fb4c20bef582f94e56cdcc790f2634d26f1bf36b0",
    ),
    "BASEBALL_REFERENCE": (
        "CHADWICK_REGISTER_ARCHIVES",
        "4a4956de-0769-4bb0-9dc4-cc30515ba16a",
        "8aa66c044fb49ceb681af16fb4c20bef582f94e56cdcc790f2634d26f1bf36b0",
    ),
}

ALIAS_SCHEMA = (
    ("canonical_player_uuid", "String"),
    ("namespace", "String"),
    ("source_player_id", "String"),
    ("parent_join_key", "String"),
    ("source_key", "String"),
    ("source_version_id", "String"),
    ("source_version_identity_sha256", "String"),
    ("mapping_confidence", "String"),
    ("mapping_status", "String"),
    ("mapping_basis", "String"),
    ("first_represented_season", "Int64"),
    ("last_represented_season", "Int64"),
    ("primary_2023_2025", "Boolean"),
    ("source_row_number", "Int64"),
    ("source_row_sha256", "String"),
    ("source_row_identity", "String"),
    ("evidence_logical_uri", "String"),
    ("mapping_identity_sha256", "String"),
    ("row_sha256", "String"),
)

DIMENSION_SCHEMA = (
    ("canonical_player_uuid", "String"),
    ("first_represented_season", "Int64"),
    ("last_represented_season", "Int64"),
    ("prior_history_2021_2022", "Boolean"),
    ("primary_active_2023_2025", "Boolean"),
    ("has_retrosheet_alias", "Boolean"),
    ("has_lahman_alias", "Boolean"),
    ("has_chadwick_alias", "Boolean"),
    ("has_mlbam_alias", "Boolean"),
    ("has_baseball_reference_alias", "Boolean"),
    ("has_player_prior", "Boolean"),
    ("minimum_player_prior_target_season", "Int64"),
    ("maximum_player_prior_target_season", "Int64"),
    ("batter_reference_count", "Int64"),
    ("pitcher_reference_count", "Int64"),
    ("other_player_reference_count", "Int64"),
    ("player_prior_row_count", "Int64"),
    ("row_sha256", "String"),
)

EXPECTED_JOIN_VALIDATION = {
    "bullpen_usage.player_id.retrosheet-to-canonical": (80_314, 1_621, 1_621),
    "pitch_sequence.batter_id.retrosheet-to-canonical": (943_682, 1_560, 1_560),
    "pitch_sequence.pitcher_id.retrosheet-to-canonical": (943_682, 1_743, 1_743),
    "plate_appearance.batter_id.retrosheet-to-canonical": (913_349, 1_557, 1_557),
    "plate_appearance.pitcher_id.retrosheet-to-canonical": (913_349, 1_743, 1_743),
    "player_game_batting.player_id.retrosheet-to-canonical": (356_498, 2_692, 2_692),
    "player_game_fielding.player_id.retrosheet-to-canonical": (332_159, 2_684, 2_684),
    "player_game_pitching.player_id.retrosheet-to-canonical": (104_610, 1_743, 1_743),
    "player_prior.canonical_player_id.canonical-to-dimension": (21_823, 2_692, 2_692),
    "starter_usage.player_id.retrosheet-to-canonical": (24_296, 850, 850),
}

EXPECTED_PRIMARY_PA_ROWS = {2023: 184_104, 2024: 182_449, 2025: 182_926}
EXPECTED_Y_MINUS_1 = {
    (2023, "BATTER"): (184_104, 169_005, 15_099, 2022),
    (2023, "PITCHER"): (184_104, 159_568, 24_536, 2022),
    (2024, "BATTER"): (182_449, 170_594, 11_855, 2023),
    (2024, "PITCHER"): (182_449, 160_914, 21_535, 2023),
    (2025, "BATTER"): (182_926, 167_720, 15_206, 2024),
    (2025, "PITCHER"): (182_926, 164_678, 18_248, 2024),
}

ALLOWED_PURPOSES = (
    "INTERNAL_DERIVED_ANALYTICS",
    "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
    "READ_ONLY_REGISTRATION",
)
PROHIBITED_PURPOSES = (
    "IDENTITY_DATA_RESALE",
    "PUBLIC_BULK_DOWNLOAD",
    "PUBLIC_RAW_BRIDGE_DOWNLOAD",
    "PUBLIC_RAW_REDISTRIBUTION",
    "UNRESTRICTED_COMMERCIAL_REDISTRIBUTION",
)
RIGHTS_CONTROL_IDS = (
    "CHADWICK_PERSONS_REGISTER",
    "RETROSHEET",
    "SABR_LAHMAN_MODERN_MLB",
)

EXPECTED_LIMITATION_IDS = (
    "NO_NAMES_OR_FUZZY_MATCHING",
    "PARENT_PHYSICAL_SCOPE_OMITS_ONE_GOVERNED_ROSTER_IDENTITY",
    "PUBLIC_RAW_DISTRIBUTION_NOT_AUTHORIZED",
    "ROOKIE_MISSING_PRIOR_IS_VALID",
    "Y_MINUS_1_ONLY",
)
