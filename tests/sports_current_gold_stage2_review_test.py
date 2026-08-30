from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from server.persistence.db import Database
from server.persistence.sports_forecast_contract import (
    SportsForecastContractError,
    SportsForecastContractStore,
)
from server.sports_current_statcast import stage2_review
from server.sports_datasets.registry import SportsDatasetRegistry


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DATABASE = (
    REPOSITORY_ROOT
    / ".runtime"
    / "asp-model-studio"
    / "persistence"
    / "asp_model_studio.db"
)
PROJECT_ID = "asp-mtddc6pw"

SOURCE_DATASET_ID = "asp.mlb.statcast.current-pa.v1"
SOURCE_DATASET_VERSION_ID = (
    "asp.mlb.statcast.current-pa.v1:partition-authority-sha256:"
    "6e134d8726587ad88d0807effb6e6b12ad39f39b99acb7f523ae6ae98155df34"
)
SOURCE_MANIFEST_SHA = "03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c"
GOLD_DATASET_ID = "gold-table:gold_mlb_current_pa_v1"
GOLD_MANIFEST_SHA = "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758"
CONTEXT_MANIFEST_SHA = "4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e"

EXPECTED_ROWS_BY_SEASON = {
    "2023": 182_072,
    "2024": 180_711,
    "2025": 182_847,
    "2026": 152_099,
}
EXPECTED_SOURCE_ROWS_BY_SEASON = {
    "2023": 184_497,
    "2024": 182_883,
    "2025": 182_847,
    "2026": 152_099,
}
EXPECTED_ORDERED_PREDICTORS = (
    "context_inning",
    "context_top_bottom",
    "context_outs_before",
    "context_base_mask_before",
    "context_batting_score_diff_before",
    "batter_log1p_pa",
    "batter_avg",
    "batter_obp",
    "batter_slg",
    "batter_so_per_pa",
    "batter_bb_hbp_per_pa",
    "batter_hr_per_pa",
    "batter_prior_missing",
    "pitcher_log1p_bfp",
    "pitcher_era9",
    "pitcher_whip",
    "pitcher_so_per_bfp",
    "pitcher_bb_per_bfp",
    "pitcher_hr_per_bfp",
    "pitcher_hbp_per_bfp",
    "pitcher_gs_per_g",
    "pitcher_prior_missing",
    "batter_prior_pa_count",
    "batter_last100_pa_count",
    "batter_last100_strikeout_rate",
    "batter_last100_walk_hbp_rate",
    "batter_last100_contact_rate",
    "batter_last100_whiff_rate",
    "batter_last100_insufficient",
    "batter_last100_whiff_missing",
    "pitcher_prior_bf_count",
    "pitcher_last250_bf_count",
    "pitcher_last250_strikeout_rate",
    "pitcher_last250_walk_rate",
    "pitcher_last250_whiff_rate",
    "pitcher_last250_avg_fastball_velocity",
    "pitcher_last250_fastball_usage",
    "pitcher_last250_breaking_usage",
    "pitcher_last250_offspeed_usage",
    "pitcher_last250_insufficient",
    "pitcher_last250_whiff_missing",
    "pitcher_last250_velocity_missing",
    "matchup_batter_bats_left",
    "matchup_batter_bats_switch",
    "matchup_batter_hand_missing",
    "matchup_pitcher_throws_left",
    "matchup_pitcher_hand_missing",
    "matchup_platoon_advantage",
)
EXPECTED_TARGET_ORDER = (
    "STRIKEOUT",
    "WALK_HBP_CI",
    "HOME_RUN",
    "SINGLE",
    "DOUBLE",
    "TRIPLE",
    "BIP_OUT",
    "OTHER_REACH",
)
EXPECTED_IDENTITY_ZEROS = (
    "duplicateCanonicalPaIdentities",
    "duplicatePlateAppearanceIdentities",
    "unresolvedPlayerIdentities",
    "ambiguousPlayerIdentities",
    "unresolvedGameIdentities",
    "ambiguousGameIdentities",
    "nullIdentityRows",
)


class _ReadOnlyDatabase(Database):
    """Use the real persisted authority while making SQLite writes impossible."""

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            f"file:{self.path.as_posix()}?mode=ro",
            uri=True,
            timeout=10.0,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection


def _require_current_authority() -> _ReadOnlyDatabase:
    if not RUNTIME_DATABASE.is_file():
        pytest.skip("local project persistence authority is not present")

    database = _ReadOnlyDatabase(RUNTIME_DATABASE)
    try:
        linkage = SportsForecastContractStore(database).get_evidence_dataset(PROJECT_ID)
    except (SportsForecastContractError, sqlite3.Error) as exc:
        pytest.skip(f"project-scoped current-Statcast authority is not present: {exc}")

    expected_linkage = {
        "datasetId": SOURCE_DATASET_ID,
        "datasetVersionId": SOURCE_DATASET_VERSION_ID,
        "manifestSha": SOURCE_MANIFEST_SHA,
    }
    if any(linkage.get(key) != value for key, value in expected_linkage.items()):
        pytest.skip("the frozen project-scoped 2026 current-Statcast authority is not active")

    registration = SportsDatasetRegistry(database).get(str(linkage["registrationId"]))
    if registration is None:
        pytest.skip("the project-linked current-Statcast registration is not present")

    gold_manifest = (
        stage2_review._gold_root()
        / "publications"
        / "sha256"
        / GOLD_MANIFEST_SHA
        / "manifest.json"
    )
    if not gold_manifest.is_file() or not stage2_review._existing_silver_root().is_dir():
        pytest.skip("the exact local Silver/Gold authority is not present")
    contextual_manifest = (
        stage2_review._contextual_gold_root()
        / "publications"
        / "sha256"
        / CONTEXT_MANIFEST_SHA
        / "manifest.json"
    )
    if not contextual_manifest.is_file():
        pytest.skip("the exact local contextual Gold authority is not present")
    return database


def test_stage2_simulation_state_role_contract_is_exact() -> None:
    assert stage2_review.SIMULATION_STATE_FIELDS == (
        "context_inning",
        "context_top_bottom",
        "context_outs_before",
        "context_base_mask_before",
        "context_batting_score_diff_before",
    )
    assert {
        name: stage2_review._column_role(name)
        for name in stage2_review.SIMULATION_STATE_FIELDS
    } == {
        name: "SIMULATION_GENERATED_STATE"
        for name in stage2_review.SIMULATION_STATE_FIELDS
    }


def test_project_scoped_current_gold_stage2_review_matches_frozen_authority() -> None:
    database = _require_current_authority()

    review = stage2_review.current_gold_stage2_review(
        database,
        PROJECT_ID,
        limit=1,
        sample="head",
    )

    assert review["schemaVersion"] == stage2_review.REVIEW_SCHEMA_VERSION
    assert review["projectId"] == PROJECT_ID
    source = review["sourceAuthority"]
    assert source["datasetId"] == SOURCE_DATASET_ID
    assert source["datasetVersionId"] == SOURCE_DATASET_VERSION_ID
    assert source["manifestSha"] == SOURCE_MANIFEST_SHA
    assert source["rowCount"] == 702_326
    assert source["rowsBySeason"] == EXPECTED_SOURCE_ROWS_BY_SEASON

    gold = review["goldAuthority"]
    assert gold["datasetId"] == GOLD_DATASET_ID
    assert gold["manifestSha"] == GOLD_MANIFEST_SHA
    assert gold["verified"] is True
    assert gold["rowCount"] == 697_729
    assert gold["featureCount"] == 48
    assert gold["rowsBySeason"] == EXPECTED_ROWS_BY_SEASON

    matrix = review["matrix"]
    assert matrix["predictorCount"] == 48
    assert matrix["orderedPredictors"] == list(EXPECTED_ORDERED_PREDICTORS)
    assert matrix["seasons"] == [2023, 2024, 2025, 2026]
    assert matrix["development"] == {
        "startDate": "2023-03-30",
        "endDate": "2026-08-13",
        "rows": 683_662,
    }
    assert matrix["finalOot"] == {
        "startDate": "2026-08-14",
        "endDate": "2026-08-27",
        "rows": 14_067,
    }

    assert review["targetTaxonomy"]["column"] == "outcome"
    assert review["targetTaxonomy"]["classOrder"] == list(EXPECTED_TARGET_ORDER)
    assert all(review["identity"][name] == 0 for name in EXPECTED_IDENTITY_ZEROS)

    simulation_columns = [
        column["name"]
        for column in matrix["columns"]
        if column["classification"] == "SIMULATION_GENERATED_STATE"
    ]
    assert simulation_columns == list(stage2_review.SIMULATION_STATE_FIELDS)
    assert review["pointInTimeReview"]["status"] == "PASS"
    assert review["leakageGate"]["status"] == "PASS_WITH_CONDITIONS"
    assert review["acceptance"] == {"allowed": True, "blockers": []}
    assert review["populationReconciliation"] == {
        "sourceRows": 702_326,
        "goldRows": 697_729,
        "excludedRows": 4_597,
        "bySeason": [
            {"season": 2023, "sourceRows": 184_497, "goldRows": 182_072, "excludedRows": 2_425},
            {"season": 2024, "sourceRows": 182_883, "goldRows": 180_711, "excludedRows": 2_172},
            {"season": 2025, "sourceRows": 182_847, "goldRows": 182_847, "excludedRows": 0},
            {"season": 2026, "sourceRows": 152_099, "goldRows": 152_099, "excludedRows": 0},
        ],
        "exclusionReasonCounts": {},
        "exclusionReasonStatus": "NOT_AVAILABLE_IN_REGISTERED_STAGE2_AUTHORITY",
    }
    context = review["contextualFeaturePack"]
    assert context["datasetId"] == "gold-table:gold_mlb_current_pa_context_v2"
    assert context["verified"] is True
    assert context["manifestSha256"] == CONTEXT_MANIFEST_SHA
    assert context["sourceGoldManifestSha256"] == GOLD_MANIFEST_SHA
    assert context["rowCount"] == 697_729
    assert context["coreFeatureCount"] == 48
    assert context["addedFeatureCount"] == 206
    assert context["totalFeatureCount"] == 254
    assert context["teamGameRowCount"] == 18_600
    assert context["rivalryMappingStatus"] == "PROPOSED_NOT_APPROVED"
    assert [item["name"] for item in context["families"]] == [
        "A CORE_GOLD_48",
        "B CORE_PLUS_CALENDAR",
        "C CORE_PLUS_REST_TRAVEL",
        "D CORE_PLUS_CIRCADIAN",
        "E CORE_PLUS_DIVISION_RIVALRY",
        "F CORE_PLUS_CALENDAR_TRAVEL",
        "G FULL_CONTEXTUAL_CHALLENGER",
    ]
    assert all(not item["includedByDefault"] for item in context["features"][48:])
    json.dumps(review, allow_nan=False)
