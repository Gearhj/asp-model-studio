from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
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
PROJECT_ID = "synthetic-stage3-project"
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


def test_numeric_gallery_target_strata_are_bounded_aggregates_in_governed_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[dict[str, object]] = []
    for index, outcome in enumerate(stage3_eda.GOLD_CLASS_ORDER):
        rows.extend(
            [
                {"feature": float(index), "game_date": "2026-04-01", "outcome": outcome},
                {"feature": float(index + 1), "game_date": "2026-04-02", "outcome": outcome},
                {"feature": None, "game_date": "2026-04-03", "outcome": outcome},
                {"feature": float(index + 3), "game_date": "2026-04-04", "outcome": outcome},
            ]
        )
    frame = pd.DataFrame(rows)
    monkeypatch.setattr(stage3_eda, "_scan", lambda *_args, **_kwargs: frame.copy())

    data, represented = stage3_eda._numeric_distribution(
        object(),
        "feature",
        {},
        {"bins": 12, "stratifyBy": "outcome"},
    )

    assert represented == 4 * len(stage3_eda.GOLD_CLASS_ORDER)
    strata = data["stratified"]
    assert [item["stratum"] for item in strata] == list(stage3_eda.GOLD_CLASS_ORDER)
    assert all(item["count"] == 4 for item in strata)
    assert all(item["observedCount"] == 3 for item in strata)
    assert all(item["missingCount"] == 1 for item in strata)
    assert all(item["missingPercent"] == 25.0 for item in strata)
    first = strata[0]
    assert first["min"] == 0.0
    assert first["q1"] == 0.5
    assert first["median"] == 1.0
    assert first["q3"] == 2.0
    assert first["max"] == 3.0
    assert first["lowerFence"] == -1.75
    assert first["upperFence"] == 4.25
    assert first["outlierCount"] == 0
    assert len(first["density"]) == 12
    assert all(set(point) == {"value", "density"} for point in first["density"])
    assert set(first) == {
        "stratum",
        "count",
        "observedCount",
        "missingCount",
        "mean",
        "min",
        "q1",
        "median",
        "q3",
        "max",
        "lowerFence",
        "upperFence",
        "outlierCount",
        "missingPercent",
        "density",
    }
    assert "rows" not in data
    json.dumps(data, allow_nan=False)


def test_categorical_gallery_keeps_missing_explicit_and_groups_other_with_target_mix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = pd.DataFrame(
        {
            "category": ["A", "A", "A", "B", "B", "C", "D", None],
            "outcome": [
                "STRIKEOUT",
                "STRIKEOUT",
                "SINGLE",
                "BIP_OUT",
                "BIP_OUT",
                "DOUBLE",
                "HOME_RUN",
                "WALK_HBP_CI",
            ],
        }
    )
    monkeypatch.setattr(stage3_eda, "_scan", lambda *_args, **_kwargs: frame.copy())

    data, represented = stage3_eda._category_counts(
        object(), "category", {}, {"topN": 2}
    )

    assert represented == 8
    assert [row["value"] for row in data["categories"]] == ["A", "B", "MISSING"]
    assert data["missingCount"] == 1
    assert data["otherCount"] == 2
    assert data["otherCategory"]["value"] == "Other"
    assert data["otherCategory"]["count"] == 2
    assert sum(
        row["count"] for row in data["otherCategory"]["targetComposition"]
    ) == 2
    assert {
        row["value"] for row in data["otherCategory"]["targetComposition"]
    } == {"DOUBLE", "HOME_RUN"}
    json.dumps(data, allow_nan=False)


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
    assert handoff["modelingTreatment"]["coldStartRowCount"] == 178_400
    assert handoff["modelingTreatment"]["coldStartPercent"] == pytest.approx(26.094766127121297)
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
    guidance = data["decisionGuidance"]
    assert guidance["defaultAnalyticalTab"] == "TARGET_AND_CLASS_BALANCE"
    assert guidance["defaultStabilityVariableExcluded"] == "context_inning"
    assert "context_inning" not in guidance["defaultStabilityVariables"]
    assert guidance["defaultStabilityVariables"] == [
        "batter_last100_contact_rate",
        "pitcher_last250_strikeout_rate",
        "batter_avg",
        "pitcher_era9",
        "batting_games_last_7_days",
        "batting_travel_distance_miles",
    ]
    selectable_names = {
        item["name"] for item in data["variables"] if item["selectable"]
    }
    assert set(guidance["defaultStabilityVariables"]) <= selectable_names
    assert guidance["selectionAuthority"] == "NONE_DESCRIPTIVE_EDA_ONLY"
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
        "settings": {"sampleSize": 25, "seed": 42, "stratifyBy": "outcome"},
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
    assert first["data"]["stratifyBy"] == "outcome"
    assert all(row["outcome"] in stage3_eda.GOLD_CLASS_ORDER for row in first["data"]["rows"])
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
            "filters": {},
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
    target = overview["data"]["targetSummary"]
    assert target["dominantClass"] == {
        "value": "BIP_OUT",
        "count": 308_513,
        "percent": pytest.approx(45.12653913776106),
    }
    assert target["rarestClass"] == {
        "value": "TRIPLE",
        "count": 2_519,
        "percent": pytest.approx(0.36845692754606807),
    }
    assert target["imbalanceRatio"] == pytest.approx(122.47439460103216)
    assert target["seasonToSeasonStability"] == {
        "status": "EXPECTED_SEASONAL_PATTERN",
        "method": "MAX_CLASS_SHARE_RANGE_PERCENTAGE_POINTS",
        "maxClassShareRangePct": pytest.approx(1.2114918702795734),
        "mostVariableClass": "BIP_OUT",
        "representedSeasons": [2023, 2024, 2025, 2026],
        "thresholdsPct": {
            "stableMax": 0.75,
            "expectedSeasonalMax": 1.5,
            "reviewMax": 3.0,
        },
    }
    assert target["minimumRareClassSampleSize"] == 494
    assert target["minimumRareClassSeason"] == 2026
    assert target["decision"] == "DESCRIPTIVE_ONLY_NO_CLASS_REBALANCING_DECISION"
    assert target["finalOotTargetsAccessed"] is False

    quality = overview["data"]["dataQualitySnapshot"]
    assert quality["overallPhysicalMissingPercent"] == pytest.approx(
        8.125505887849862
    )
    assert quality["scope"] == "DEVELOPMENT_ONLY_WITH_EXPLICIT_SUBSCOPES"
    assert quality["overallPhysicalMissingnessScope"] == (
        "ALL_REGISTERED_DEVELOPMENT_PREDICTOR_CELLS"
    )
    assert quality["predictorCount"] == 254
    assert quality["coldStartRows"] == 178_400
    assert quality["coldStartPercent"] == pytest.approx(26.094766127121297)
    assert quality["materialMissingnessThresholdPct"] == 10.0
    assert quality["featuresWithMaterialMissingness"] == 28
    assert quality["failureReasonRows"] == {
        "scope": "TEAM_GAME_CONTEXT_ROW_REASON_ANY_SIDE",
        "computationFailureRows": 0,
        "sourceMissingRows": 679_292,
        "sourceNotAvailableForEraRows": 0,
        "note": "Exact row-union counts for the registered batting/fielding team-game missing-reason fields; not a per-feature causal ledger.",
    }
    assert quality["potentialDescriptiveOutliers"]["variable"] == "pitcher_era9"
    assert quality["potentialDescriptiveOutliers"]["method"] == "IQR_1_5"
    assert quality["potentialDescriptiveOutliers"]["count"] == 31_793
    assert quality["potentialDescriptiveOutliers"]["treatmentApplied"] is False
    assert quality["actions"] == ["OPEN_MISSING_VALUES", "OPEN_OUTLIERS"]
    assert quality["decision"] == "NO_TREATMENT_APPLIED"
    assert quality["finalOotTargetsAccessed"] is False

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


def test_stage3_temporal_returns_written_multi_variable_stability_without_deciding() -> None:
    response = stage3_eda.stage3_eda_query(
        _require_current_authority(),
        PROJECT_ID,
        {
            "queryType": "temporal",
            "variables": [
                "batter_last100_contact_rate",
                "pitcher_last250_strikeout_rate",
            ],
            "filters": {"seasons": [2026]},
            "settings": {"granularity": "month"},
        },
    )

    _assert_no_model_or_oot_activity(response)
    data = response["data"]
    assert data["variable"] == "batter_last100_contact_rate"
    assert data["variables"] == [
        "batter_last100_contact_rate",
        "pitcher_last250_strikeout_rate",
    ]
    assert set(data["seriesByVariable"]) == set(data["variables"])
    assert set(data["driftByVariable"]) == set(data["variables"])
    assert data["series"] == data["seriesByVariable"][data["variable"]]
    assert data["drift"] == data["driftByVariable"][data["variable"]]

    assessment = data["stabilityAssessment"]
    assert assessment["overallStatus"] in {
        "STABLE", "EXPECTED_SEASONAL_PATTERN", "REVIEW", "MATERIAL_SHIFT"
    }
    assert assessment["targetMix"]["status"] == "REVIEW"
    assert assessment["targetMix"]["representedSeasons"] == [2026]
    counts = assessment["featureCounts"]
    assert counts["scope"] == "SELECTED_VARIABLES"
    assert (
        counts["stable"]
        + counts["moderateReview"]
        + counts["highReview"]
        + counts["sourceEraChange"]
    ) == 2
    assert [item["variable"] for item in assessment["selectedVariables"]] == data[
        "variables"
    ]
    assert all(
        item["decision"] == "NO_AUTOMATIC_FEATURE_SELECTION_OR_REJECTION"
        for item in assessment["selectedVariables"]
    )
    assert assessment["coldStartShift"]["byPeriod"]
    assert assessment["sourceEraChanges"] == []
    assert assessment["sourceEraEvidenceStatus"] == (
        "NO_EXACT_SOURCE_ERA_CHANGE_REGISTERED_FOR_SELECTED_VARIABLES"
    )
    assert "offseason" in assessment["rowVolumeNote"].lower()
    assert assessment["decision"] == "NO_MODEL_OR_FEATURE_DECISION_MADE"
    assert assessment["finalOotTargetsAccessed"] is False
    json.dumps(response, allow_nan=False)
