from __future__ import annotations

from pathlib import PurePosixPath


CONTRACT_NAME = "SPORTS_DATASET_MANIFEST"
CONTRACT_VERSION = "SPORTS_DATASET_MANIFEST_V1"
CANONICALIZATION_VERSION = "SPORTS_CANONICAL_JSON_V1"
DATASET_ID = "asp.mlb.open-data.fd1"
PUBLISHER = "AI Sports Predictor"
SPORT = "Baseball"
LEAGUE = "MLB"
EVIDENCE_CUTOFF = "2026-08-15"
PUBLISHED_AT = "2026-08-16T05:21:08.171241Z"

MANIFEST_SHA = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
PARTITION_AUTHORITY_SHA = "8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437"
SUPERSEDED_MANIFEST_PREFIX = "6c6cde"
README_SHA = "2e6c216881c3098d99c5d0575ce78c0b0afe3e56250bbc7ec98eb8efaaa8fe34"
VALIDATION_REPORT_SHA = "48854d42ab97ac174877f05ea9a84e22ebd54ec3ead2af34e444f562ff09c5cf"

MANIFEST_ID = f"sports-dataset-manifest:sha256:{MANIFEST_SHA}"
DATASET_VERSION_ID = f"{DATASET_ID}:sha256:{MANIFEST_SHA}"
PACKAGE_ID = f"sha256-{MANIFEST_SHA}"
PACKAGE_RELATIVE_ROOT = PurePosixPath("datasets") / "mlb-fd1" / PACKAGE_ID
LOGICAL_PACKAGE_ROOT = f"asp-model-exchange://{PACKAGE_RELATIVE_ROOT.as_posix()}"

EXPECTED_METADATA_FILES = frozenset(
    {
        "README.md",
        "attribution.md",
        "schema-registry.json",
        "source-rights.json",
        "sports-dataset-manifest.json",
        "validation-report.json",
    }
)

EXPECTED_TOTALS = {
    "package_files": 335,
    "parquet_files": 329,
    "rows": 3_738_096,
    "parquet_bytes": 337_421_353,
    "logical_families": 10,
    "physical_variants": 33,
}

EXPECTED_POPULATIONS = {
    "strict_deployable": 1_460_755,
    "enhanced_research": 785_808,
    "prior_only": 1_491_533,
}

EXPECTED_FAMILIES = (
    "bullpen_usage",
    "pitch_sequence",
    "plate_appearance",
    "play_transition",
    "player_game_batting",
    "player_game_fielding",
    "player_game_pitching",
    "player_prior",
    "starter_usage",
    "weather",
)

PA_CLASS_ORDER = (
    "STRIKEOUT",
    "WALK_HBP_CI",
    "HOME_RUN",
    "SINGLE",
    "DOUBLE",
    "TRIPLE",
    "BIP_OUT",
    "OTHER_REACH",
)

EXPECTED_FOLDS = {
    "train-2023-validate-2024": {
        "training_seasons": [2023],
        "validation_season": 2024,
        "training_rows": 184_104,
        "validation_rows": 182_449,
    },
    "train-through-2024-validate-2025": {
        "training_seasons": [2023, 2024],
        "validation_season": 2025,
        "training_rows": 366_553,
        "validation_rows": 182_926,
    },
}

EXPECTED_RIGHTS_IDS = (
    "CHADWICK_PERSONS_REGISTER",
    "LAHMAN_SEAMHEADS_NEGRO_LEAGUES_EXCLUDED",
    "NOAA_NCEI_LCDV2_ZERO_USE",
    "OPEN_METEO_FREE_HOSTED_ZERO_USE",
    "RETROSHEET",
    "SABR_LAHMAN_MODERN_MLB",
)

EXPECTED_ALLOWED_USES = (
    "INTERNAL_DERIVED_ANALYTICS",
    "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
    "READ_ONLY_REGISTRATION",
)

EXPECTED_PROHIBITED_USES = (
    "PUBLIC_BULK_DOWNLOAD",
    "PUBLIC_RAW_REDISTRIBUTION",
    "RAW_DATA_RESALE",
    "UNREVIEWED_COMMERCIAL_REDISTRIBUTION",
)

EXPECTED_POPULATION_PROHIBITIONS = {
    "prior_only": (*EXPECTED_PROHIBITED_USES, "PRIMARY_2023_2025_TARGET_TRAINING"),
    "enhanced_research": (*EXPECTED_PROHIBITED_USES, "STRICT_DEPLOYABLE_PREGAME_FEATURE_USE"),
    "strict_deployable": EXPECTED_PROHIBITED_USES,
}

EXPECTED_LIMITATION_IDS = (
    "INCOMPLETE_ACTUAL_LINEUP_COVERAGE",
    "HISTORICAL_ACTUAL_LINEUP_TIMING_RISK",
    "HISTORICAL_ACTUAL_STARTER_TIMING_RISK",
    "HISTORICAL_ACTUAL_WEATHER_TIMING_RISK",
    "NO_MULTI_SEASON_STATCAST",
    "NO_VELOCITY_SPIN_MOVEMENT_LOCATION",
    "NO_LAUNCH_SPEED_ANGLE",
    "NO_BARREL_HARD_HIT_XWOBA",
    "NO_TRACKING_DEFENSE_OR_RUNNER_SPEED",
    "NO_HISTORICAL_MARKET_CLOSING_LINE_OR_CLV",
    "RETROSPECTIVE_EVIDENCE_NOT_PROSPECTIVE_PROOF",
    "NOT_PRODUCTION_MODEL_APPROVAL",
)

REGISTRATION_ID = f"sports-dataset-{MANIFEST_SHA[:16]}"
PROJECT_ID = f"sports-project-mlb-fd1-{MANIFEST_SHA[:12]}"
PROJECT_NAME = "MLB Gen-2 Free-Data Baseline"
