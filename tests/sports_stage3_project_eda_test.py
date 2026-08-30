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
from server.sports_current_statcast import stage3_eda


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
SOURCE_MANIFEST_SHA = "03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c"
GOLD_MANIFEST_SHA = "67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758"
CONTEXT_MANIFEST_SHA = "4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e"
EXCLUSION_MEMBERSHIP_SHA = "30fd365bf67dd6687f58864c1b7cede9ea1371028467654e9fac1b5eed833619"


class _ReadOnlyDatabase(Database):
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
    if (
        linkage.get("datasetId") != SOURCE_DATASET_ID
        or linkage.get("manifestSha") != SOURCE_MANIFEST_SHA
    ):
        pytest.skip("the exact current-Statcast project authority is not active")
    return database


def _assert_no_model_or_oot_activity(response: dict[str, object]) -> None:
    population = response["population"]
    audit = response["audit"]
    assert population["scope"] == "DEVELOPMENT_ONLY"
    assert population["developmentRows"] == 683_662
    assert population["finalOotRows"] == 14_067
    assert population["finalOotLocked"] is True
    assert population["developmentEndDate"] == "2026-08-13"
    assert audit == {
        "finalOotTargetAccessed": False,
        "finalOotUsedForSelection": False,
        "legacyGlobalMatrixUsed": False,
        "providerCalls": 0,
        "modelActivity": {
            "fits": 0,
            "scores": 0,
            "tunes": 0,
            "calibrations": 0,
            "selections": 0,
            "promotions": 0,
        },
    }


def test_stage3_metadata_is_exact_project_authority_and_redacts_oot_targets() -> None:
    response = stage3_eda.stage3_eda_metadata(_require_current_authority(), PROJECT_ID)

    assert response["authority"] == {
        "projectId": PROJECT_ID,
        "sourceDatasetId": SOURCE_DATASET_ID,
        "sourceManifestSha": SOURCE_MANIFEST_SHA,
        "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
        "goldManifestSha": GOLD_MANIFEST_SHA,
        "contextualDatasetId": "gold-table:gold_mlb_current_pa_context_v2",
        "contextualManifestSha": CONTEXT_MANIFEST_SHA,
        "exclusionMembershipArtifactSha": EXCLUSION_MEMBERSHIP_SHA,
        "reviewDigest": response["authority"]["reviewDigest"],
    }
    assert len(response["authority"]["reviewDigest"]) == 64
    _assert_no_model_or_oot_activity(response)
    assert response["population"]["sampling"] is None

    data = response["data"]
    assert len(data["variables"]) == 264
    assert len([item for item in data["variables"] if item["role"] == "SIMULATION_GENERATED_STATE"]) == 5
    assert len(data["families"]) == 7
    handoff = data["stage3Handoff"]
    assert handoff["sourceAuthority"]["manifestSha"] == SOURCE_MANIFEST_SHA
    assert handoff["goldAuthority"]["manifestSha"] == GOLD_MANIFEST_SHA
    assert handoff["contextualFeaturePack"]["manifestSha256"] == CONTEXT_MANIFEST_SHA
    assert handoff["populationReconciliation"]["excludedRows"] == 4_597
    membership = handoff["populationReconciliation"]["membershipEvidence"]
    assert membership["artifactCanonicalSha256"] == EXCLUSION_MEMBERSHIP_SHA
    assert membership["membershipStatusCounts"] == {
        "NOT_PRESENT_IN_BOUND_CURRENT_GOLD_BY_CANONICAL_PA_ID": 4_597
    }
    assert membership["causalReasonStatus"] == "FINER_SOURCE_SIDE_CAUSE_NOT_RECORDED"
    assert membership["causalReasonCounts"] == {
        "NOT_ADMITTED_TO_FROZEN_GOLD_V1_BRIDGE_MATCHED_SET": 4_597
    }
    assert sum(item["excludedRows"] for item in membership["byMonth"]) == 4_597
    assert sum(item["excludedRows"] for item in membership["byBattingTeam"]) == 4_597
    assert {item["team"] for item in membership["byBattingTeam"]} >= {"NYY", "BOS"}
    assert sum(
        item["excludedRows"]
        for item in membership["byGovernedTargetOrUnmapped"]
    ) == 4_597
    assert all(
        set(item) == {"target", "excludedRows", "shareOfExclusionsPct"}
        for item in membership["byGovernedTargetOrUnmapped"]
    )
    assert membership["identityConditions"]["nullCanonicalPaIdRows"] == 0
    assert all(
        isinstance(value, (int, float))
        for value in membership["identityConditions"].values()
    )
    assert membership["finalOotExcludedRows"] == 0
    assert membership["featureConstructionCondition"] == "PRE_FEATURE_BRIDGE_NON_ADMISSION"
    assert membership["featureConstructionConditionCounts"] == {
        "PRE_FEATURE_BRIDGE_NON_ADMISSION": 4_597,
        "FEATURE_CONSTRUCTION_ROW_LOSS": 0,
    }
    assert membership["exclusionStageStatus"] == "EXACT_DERIVED_CONSTRUCTION_STAGE_COUNTS"
    assert membership["finerSourceSideCauseStatus"] == "NOT_RECORDED"
    assert handoff["populationReconciliation"]["exclusionReasonCounts"] == {
        "NOT_ADMITTED_TO_FROZEN_GOLD_V1_BRIDGE_MATCHED_SET": 4_597
    }
    assert handoff["populationReconciliation"]["exclusionReasonStatus"] == (
        "EXACT_DERIVED_CONSTRUCTION_STAGE_COUNTS"
    )
    assert handoff["matrix"]["development"] == {
        "startDate": "2023-03-30",
        "endDate": "2026-08-13",
        "rows": 683_662,
    }
    assert handoff["matrix"]["finalOot"]["rows"] == 14_067
    assert handoff["targetTaxonomy"]["distributions"] == {"development": []}
    assert handoff["preview"]["rows"] == []
    assert handoff["missingness"]["predictors"] == []
    assert handoff["redaction"] == {
        "finalOotTargetDistributions": "OMITTED",
        "overallTargetDistributions": "OMITTED",
        "finalOotFeatureCoverage": "OMITTED",
        "previewRows": "OMITTED",
    }
    json.dumps(response, allow_nan=False)


def test_stage3_filters_are_real_and_pairwise_sampling_is_deterministic() -> None:
    database = _require_current_authority()
    payload = {
        "queryType": "pairwise_sample",
        "variables": ["batter_avg", "pitcher_era9"],
        "filters": {
            "seasons": [2026],
            "battingTeam": "NYY",
            "homeAway": "HOME",
            "historyStatus": "ESTABLISHED",
            "simulationState": {"field": "context_outs_before", "value": 2},
            "minimumSampleSize": 1,
        },
        "settings": {"sampleSize": 25, "seed": 42},
    }

    first = stage3_eda.stage3_eda_query(database, PROJECT_ID, payload)
    second = stage3_eda.stage3_eda_query(database, PROJECT_ID, payload)

    _assert_no_model_or_oot_activity(first)
    assert first["population"]["filtersApplied"] == {
        "battingTeam": ["NYY"],
        "seasons": [2026],
        "historyStatus": "ESTABLISHED",
        "homeAway": "HOME",
        "simulationState": {"field": "context_outs_before", "value": 2},
        "minimumSampleSize": 1,
    }
    assert 25 <= first["population"]["rowsRepresented"] < 683_662
    assert first["population"]["sampling"] == {
        "method": "HASH_SMALLEST_CANONICAL_PA_V1",
        "seed": 42,
        "sampleSize": 25,
        "populationSize": first["population"]["rowsRepresented"],
    }
    assert first["data"]["rows"] == second["data"]["rows"]
    assert len(first["data"]["rows"]) == 25
    assert all("canonicalPaId" not in row for row in first["data"]["rows"])
    assert second["cacheStatus"] == "HIT"
    json.dumps(first, allow_nan=False)


def test_stage3_filter_contract_fails_closed_for_oot_inert_and_undersized_queries() -> None:
    schema = {
        "game_date",
        "season",
        "outcome",
        "batter_avg",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
        *stage3_eda.SIMULATION_STATE_FIELDS,
    }
    with pytest.raises(stage3_eda.Stage3EdaError, match="final OOT is locked") as oot:
        stage3_eda._normalize_filters(
            {"endDate": "2026-08-14"}, schema, ["batter_avg"]
        )
    assert oot.value.code == "FINAL_OOT_FILTER_PROHIBITED"

    with pytest.raises(stage3_eda.Stage3EdaError) as inert:
        stage3_eda._normalize_filters(
            {"featureFamily": "A CORE_GOLD_48"}, schema, ["batter_avg"]
        )
    assert inert.value.code == "EDA_FILTER_UNSUPPORTED"

    with pytest.raises(stage3_eda.Stage3EdaError) as invalid_state:
        stage3_eda._normalize_filters(
            {"simulationState": {"field": "actual_target_game_state", "value": 1}},
            schema,
            ["batter_avg"],
        )
    assert invalid_state.value.code == "EDA_SIMULATION_FILTER_INVALID"

    with pytest.raises(stage3_eda.Stage3EdaError) as nonselectable:
        stage3_eda.stage3_eda_query(
            _require_current_authority(),
            PROJECT_ID,
            {
                "queryType": "pairwise_sample",
                "variables": ["canonicalPaId", "outcome"],
                "filters": {},
                "settings": {"sampleSize": 5, "seed": 1},
            },
        )
    assert nonselectable.value.code == "EDA_VARIABLE_UNKNOWN"

    database = _require_current_authority()
    with pytest.raises(stage3_eda.Stage3EdaError) as threshold:
        stage3_eda.stage3_eda_query(
            database,
            PROJECT_ID,
            {
                "queryType": "distribution",
                "variables": ["batter_avg"],
                "filters": {
                    "batter": ["CANONICAL_PLAYER_THAT_DOES_NOT_EXIST"],
                    "minimumSampleSize": 1,
                },
                "settings": {},
            },
        )
    assert threshold.value.code == "EDA_MINIMUM_SAMPLE_NOT_MET"


def test_stage3_overview_and_cold_start_are_development_only() -> None:
    database = _require_current_authority()
    overview = stage3_eda.stage3_eda_query(
        database,
        PROJECT_ID,
        {
            "queryType": "overview",
            "variables": [],
            "filters": {"seasons": [2026]},
            "settings": {},
        },
    )
    _assert_no_model_or_oot_activity(overview)
    assert overview["data"]["summary"]["endDate"] == "2026-08-13"
    assert overview["data"]["summary"]["rowExclusions"]["excludedRows"] == 4_597
    overview_membership = overview["data"]["summary"]["rowExclusions"][
        "membershipEvidence"
    ]
    assert overview_membership["artifactCanonicalSha256"] == EXCLUSION_MEMBERSHIP_SHA
    assert overview_membership["finalOotExcludedRows"] == 0
    assert overview["data"]["targetByMonth"]
    assert overview["data"]["targetBySimulationState"]

    cold = stage3_eda.stage3_eda_query(
        database,
        PROJECT_ID,
        {
            "queryType": "cold_start",
            "variables": [],
            "filters": {"seasons": [2026]},
            "settings": {},
        },
    )
    _assert_no_model_or_oot_activity(cold)
    assert cold["data"]["summary"]["affectedGames"] > 0
    assert cold["data"]["summary"]["affectedTeams"] == 30
    assert cold["data"]["batter"]["affectedGames"] > 0
    assert cold["data"]["batter"]["affectedTeams"] == 30
    assert cold["data"]["pitcher"]["affectedGames"] > 0
    assert cold["data"]["pitcher"]["affectedTeams"] == 30
    json.dumps(cold, allow_nan=False)
