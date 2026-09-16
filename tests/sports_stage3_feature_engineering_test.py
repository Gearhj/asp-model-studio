from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

from server.persistence.db import Database
from server.persistence.repositories.stage3_feature_set_repository import (
    NO_CURRENT_FEATURE_SET,
)
from server.sports_current_statcast import stage3_feature_engineering as feature
from server.sports_current_statcast import stage3_player_prior_authority as player_prior
from server.sports_current_statcast.contextual_features import (
    CONTEXT_FEATURES,
    ORDERED_GOLD_PLUS_CONTEXT_FEATURES,
)
from server.sports_gold.contracts import GOLD_FEATURES


def _fake_authority():
    public = {
        "projectId": "synthetic-stage3-project",
        "sourceDatasetId": "asp.mlb.statcast.current-pa.v1",
        "sourceManifestSha": "1" * 64,
        "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
        "goldManifestSha": "2" * 64,
        "contextualDatasetId": "gold-table:gold_mlb_current_pa_context_v2",
        "contextualManifestSha": "3" * 64,
        "exclusionMembershipArtifactSha": "4" * 64,
        "reviewDigest": "5" * 64,
    }
    reviews = []
    for name in ORDERED_GOLD_PLUS_CONTEXT_FEATURES:
        raw = name.removeprefix("batting_").removeprefix("fielding_")
        family = (
            "CORE_GOLD_48"
            if name in GOLD_FEATURES
            else "INTERACTION"
            if "_x_" in raw
            else "MISSINGNESS"
            if raw.endswith(("_missing", "_insufficient"))
            else "CONTEXTUAL"
        )
        reviews.append(
            {
                "name": name,
                "family": family,
                "category": "CORE_GOLD_48" if name in GOLD_FEATURES else "CONTEXTUAL_CANDIDATE",
                "definition": f"Governed definition for {name}",
                "sourceLineage": "exact accepted test authority",
                "pointInTimeTreatment": "source.game_date < target.game_date",
                "coverageOverall": 0.97,
                "coverageDevelopment": 0.96,
                "coverageFinalOot": 0.95,
                "proxyWarning": "unapproved rivalry" if raw in feature._SUBJECTIVE_RIVALRY_FEATURES else None,
            }
        )
    return SimpleNamespace(
        project_id="synthetic-stage3-project",
        registration_id="registration-current",
        dataset_version_id="dataset-version-current",
        activation_revision=7,
        source_dataset_id="asp.mlb.statcast.current-pa.v1",
        source_manifest_sha="1" * 64,
        source_publication_sha="6" * 64,
        gold_manifest_sha="2" * 64,
        contextual_manifest_sha="3" * 64,
        review_digest="5" * 64,
        contextual_review={"features": reviews},
        public=lambda: dict(public),
    )


def _fake_variables(authority):
    rows = []
    for name in ORDERED_GOLD_PLUS_CONTEXT_FEATURES:
        raw = name.removeprefix("batting_").removeprefix("fielding_")
        categorical = raw in {"holiday_name", "holiday_region", "season_phase", "rivalry_pair"}
        rows.append(
            {
                "name": name,
                "label": name.replace("_", " ").title(),
                "definition": f"Governed definition for {name}",
                "dataType": "categorical" if categorical else "numeric",
                "role": "MISSINGNESS_INDICATOR" if raw.endswith(("_missing", "_insufficient")) else "PREGAME_FEATURE",
                "featureFamily": "CORE_GOLD_48" if name in GOLD_FEATURES else "CONTEXTUAL",
                "category": "FEATURE",
                "sourceLineage": "exact accepted test authority",
                "pointInTimeTreatment": "development only",
                "availabilityEra": "2023-03-30 through 2026-08-13",
                "missingPercent": 4.0,
                "uniqueCount": None,
                "selectable": raw not in feature._SUBJECTIVE_RIVALRY_FEATURES,
                "core": name in GOLD_FEATURES,
                "proxyWarning": "unapproved rivalry" if raw in feature._SUBJECTIVE_RIVALRY_FEATURES else None,
            }
        )
    return rows


@pytest.fixture()
def service(monkeypatch, tmp_path):
    database = Database(tmp_path / "stage3-feature-engineering.db")
    database.initialize()
    authority = _fake_authority()
    monkeypatch.setattr(feature.eda, "_resolve_authority", lambda database, project_id: authority)
    monkeypatch.setattr(feature.eda, "_variables", _fake_variables)
    refs = {
        "outlier": {
            "policyId": "outlier-adopted-3",
            "policyVersion": 3,
            "checksum": "a" * 64,
            "status": "ADOPTED",
        },
        "missing": {
            "policyId": "missing-adopted-4",
            "policyVersion": 4,
            "checksum": "b" * 64,
            "status": "ADOPTED",
        },
    }
    monkeypatch.setattr(feature, "_treatment_policy_refs", lambda database, authority: refs)
    return database, authority, refs


def _authority_key(authority) -> str:
    return ":".join(
        (
            authority.source_manifest_sha,
            authority.gold_manifest_sha,
            authority.contextual_manifest_sha,
            authority.review_digest,
        )
    )


def test_summary_reconciles_exact_inventory_families_and_interactions(service):
    database, authority, refs = service
    response = feature.feature_studio_summary(authority.project_id, database)
    assert response["ok"] is True
    assert response["authority"]["authorityKey"] == _authority_key(authority)
    assert response["population"]["rows"] == 683_662
    assert response["audit"]["featureEngineeringActivity"] == {
        "sourceRowsMutated": 0,
        "goldRowsMutated": 0,
        "preprocessingFits": 0,
        "modelFits": 0,
        "scores": 0,
        "candidateRegistrations": 0,
        "promotions": 0,
    }
    data = response["data"]
    assert data["summary"]["coreFeatureCount"] == 48
    assert data["summary"]["contextualFeatureCount"] == 206
    assert data["summary"]["totalCandidateCount"] == 254
    assert data["summary"]["eligibleContextualCount"] == 194
    # Twelve rivalry fields plus all thirteen current nonexecutable prior
    # fields are intrinsically held closed even before a combined treatment
    # DRAFT exists.
    assert data["summary"]["inactiveFeatureCount"] == 25
    assert data["summary"]["unavailableFeatureCount"] == 2
    assert data["summary"]["familyCount"] == 7
    assert data["summary"]["interactionCounts"] == {
        "total": 11,
        "materialized": 8,
        "inactivePendingRivalry": 1,
        "sourceUnavailable": 2,
    }
    assert data["summary"]["finalOotRows"] == 14_067
    assert data["summary"]["finalOotLocked"] is True
    assert len(data["families"]) == 7
    assert len(data["recommendedSets"]) == 8
    assert [item["setId"] for item in data["recommendedSets"]] == [
        "BASELINE_CORE_48",
        "CORE_PLUS_CALENDAR",
        "CORE_PLUS_REST_TRAVEL",
        "CORE_PLUS_CIRCADIAN",
        "CORE_PLUS_DIVISION",
        "CORE_PLUS_CALENDAR_TRAVEL",
        "FULL_ELIGIBLE_CONTEXTUAL",
        "CUSTOM",
    ]
    assert [item["name"] for item in data["interactions"]][-2:] == [
        "travel_x_recent_bullpen_workload",
        "month_x_temperature",
    ]
    assert all(item["status"] == "EXCLUDED_SOURCE_UNAVAILABLE" for item in data["interactions"][-2:])
    assert data["treatmentPolicies"] == refs
    assert data["featureSetState"]["expectedChecksum"] == NO_CURRENT_FEATURE_SET
    baseline = data["recommendedSets"][0]
    assert set(player_prior.WAVE2_ENGINE_PRIOR_FEATURES).isdisjoint(
        baseline["orderedFeatures"]
    )
    assert set(player_prior.RETIRED_PRIOR_FEATURES).isdisjoint(
        baseline["orderedFeatures"]
    )
    assert {
        item["feature"] for item in baseline["exclusions"]
    }.issuperset(
        player_prior.WAVE2_ENGINE_PRIOR_FEATURES
        | player_prior.RETIRED_PRIOR_FEATURES
    )


def test_unselected_interactions_are_not_transitively_activatable() -> None:
    contracts = {
        item["name"]: item
        for item in feature._interaction_contracts(
            (
                "batting_long_travel_x_short_rest",
                "fielding_long_travel_x_short_rest",
            )
        )
    }

    assert contracts["long_travel_x_short_rest"]["status"] == "MATERIALIZED"
    assert contracts["long_travel_x_short_rest"]["mayActivate"] is True
    for name in ("home_x_holiday", "doubleheader_x_short_rest"):
        assert contracts[name]["status"] == "EXCLUDED_FROM_FEATURE_SET"
        assert contracts[name]["selectedPhysicalFeatures"] == []
        assert contracts[name]["mayActivate"] is False


def test_inventory_is_paginated_searchable_and_rejects_oot_target_access(service):
    database, authority, _ = service
    response = feature.feature_inventory(
        authority.project_id,
        database,
        {
            "search": "travel",
            "families": ["CONTEXTUAL"],
            "page": 1,
            "pageSize": 10,
            "sortBy": "name",
            "sortDirection": "asc",
        },
    )
    assert response["data"]["total"] > 10
    assert len(response["data"]["rows"]) == 10
    assert all("travel" in row["name"] for row in response["data"]["rows"])
    assert all(row["finalOotTargetEvidenceUsed"] is False for row in response["data"]["rows"])
    with pytest.raises(feature.Stage3FeatureEngineeringError) as caught:
        feature.feature_inventory(
            authority.project_id,
            database,
            {"population": "FINAL_OOT", "includeFinalOotOutcome": True},
        )
    assert caught.value.code == "FINAL_OOT_TARGET_ACCESS_PROHIBITED"
    with pytest.raises(feature.Stage3FeatureEngineeringError) as caught:
        feature.feature_inventory(
            authority.project_id,
            database,
            {"filters": {"outcomes": ["HOME_RUN"]}},
        )
    assert caught.value.code == "TARGET_DERIVED_FEATURE_SELECTION_PROHIBITED"


def test_feature_detail_scans_development_predictor_only(service, monkeypatch):
    database, authority, _ = service
    calls = []

    def scan(authority, columns, filters):
        calls.append((list(columns), dict(filters)))
        return pd.DataFrame(
            {
                "batter_avg": [0.200, 0.250, None, 0.300],
                "season": [2023, 2024, 2025, 2026],
                "game_date": ["2023-04-01", "2024-04-01", "2025-05-01", "2026-06-01"],
            }
        )

    monkeypatch.setattr(feature.eda, "_scan", scan)
    response = feature.feature_detail(authority.project_id, database, "batter_avg")
    assert calls == [(["batter_avg", "season", "game_date"], {})]
    assert "outcome" not in calls[0][0]
    detail = response["data"]
    assert detail["developmentSummary"]["developmentRows"] == 4
    assert detail["developmentSummary"]["missingRows"] == 1
    assert detail["developmentSummary"]["finalOotTargetsAccessed"] is False
    assert detail["finalOotPredictorCoverage"]["predictorOnly"] is True
    assert detail["finalOotPredictorCoverage"]["targetCountsAvailable"] is False


def test_draft_registration_supersession_retirement_and_concurrency(service):
    database, authority, refs = service
    key = _authority_key(authority)
    base = {
        "authorityKey": key,
        "featureSetKey": "mlb-pa-challenger",
        "name": "MLB PA Challenger",
        "orderedFeatures": list(GOLD_FEATURES[:3]),
        "transformationContracts": {
            GOLD_FEATURES[0]: ["STANDARDIZE"],
            GOLD_FEATURES[1]: ["RETAIN_RAW"],
            GOLD_FEATURES[2]: ["RETAIN_RAW"],
        },
        "expectedChecksum": NO_CURRENT_FEATURE_SET,
    }
    first = feature.save_feature_set_draft(authority.project_id, database, base, "user-1")
    draft = first["data"]["featureSet"]
    assert draft["status"] == "DRAFT"
    assert draft["orderedFeatures"] == list(GOLD_FEATURES[:3])
    assert draft["treatmentPolicies"] == refs
    with pytest.raises(feature.Stage3FeatureEngineeringError) as caught:
        feature.save_feature_set_draft(authority.project_id, database, base, "user-2")
    assert caught.value.code == "FEATURE_SET_CONCURRENT_MODIFICATION"

    registered_one = feature.register_feature_set(
        authority.project_id,
        database,
        {
            "authorityKey": key,
            "draftFeatureSetId": draft["featureSetId"],
            "expectedChecksum": draft["checksum"],
        },
        "user-1",
    )["data"]["featureSet"]
    assert registered_one["status"] == "REGISTERED"
    assert registered_one["registeredFromFeatureSetId"] == draft["featureSetId"]

    second = feature.save_feature_set_draft(
        authority.project_id,
        database,
        {
            **base,
            "orderedFeatures": list(GOLD_FEATURES[:4]),
            "transformationContracts": None,
            "expectedChecksum": registered_one["checksum"],
        },
        "user-2",
    )["data"]["featureSet"]
    registered_two = feature.register_feature_set(
        authority.project_id,
        database,
        {
            "authorityKey": key,
            "draftFeatureSetId": second["featureSetId"],
            "expectedChecksum": second["checksum"],
        },
        "user-2",
    )["data"]["featureSet"]
    state = feature.feature_set_state(authority.project_id, database)["data"]
    assert state["registered"]["featureSetId"] == registered_two["featureSetId"]
    assert len(state["registeredSets"]) == 1
    assert len(state["history"]) == 4

    retired = feature.retire_feature_set(
        authority.project_id,
        database,
        {
            "authorityKey": key,
            "registeredFeatureSetId": registered_two["featureSetId"],
            "expectedChecksum": registered_two["checksum"],
        },
        "user-2",
    )["data"]["featureSet"]
    assert retired["status"] == "RETIRED"
    state = feature.feature_set_state(authority.project_id, database)["data"]
    assert state["registered"] is None
    assert len(state["history"]) == 5

    with database.connection() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE stage3_feature_set_versions SET notes = 'changed' WHERE feature_set_id = ?",
                (draft["featureSetId"],),
            )
        events = connection.execute(
            "SELECT event_type FROM stage3_feature_set_events ORDER BY rowid"
        ).fetchall()
    assert [row[0] for row in events] == [
        "DRAFT_CREATED",
        "FEATURE_SET_REGISTERED",
        "DRAFT_REVISED",
        "FEATURE_SET_SUPERSEDED",
        "FEATURE_SET_REGISTERED",
        "FEATURE_SET_RETIRED",
    ]


def test_registration_rechecks_for_a_newest_pending_combined_specification(
    service, monkeypatch
):
    database, authority, _ = service
    key = _authority_key(authority)
    saved = feature.save_feature_set_draft(
        authority.project_id,
        database,
        {
            "authorityKey": key,
            "featureSetKey": "pending-treatment-gate",
            "name": "Pending treatment gate",
            "orderedFeatures": list(GOLD_FEATURES[:3]),
            "expectedChecksum": NO_CURRENT_FEATURE_SET,
        },
        "user-1",
    )["data"]["featureSet"]
    monkeypatch.setattr(
        feature.Stage3TreatmentRepository,
        "combined_spec_state",
        lambda self, project_id, review_digest: {
            "history": [
                {"status": "DRAFT", "specificationVersion": 4},
                {"status": "ADOPTED", "specificationVersion": 3},
            ]
        },
    )
    with pytest.raises(feature.Stage3FeatureEngineeringError) as caught:
        feature.register_feature_set(
            authority.project_id,
            database,
            {
                "authorityKey": key,
                "draftFeatureSetId": saved["featureSetId"],
                "expectedChecksum": saved["checksum"],
            },
            "user-1",
        )
    assert caught.value.code == "FEATURE_SET_TREATMENT_SPEC_DRAFT_PENDING"
    with database.connection() as connection:
        registered = connection.execute(
            "SELECT COUNT(*) FROM stage3_feature_set_versions WHERE feature_set_status = 'REGISTERED'"
        ).fetchone()[0]
        registration_events = connection.execute(
            "SELECT COUNT(*) FROM stage3_feature_set_events WHERE event_type = 'FEATURE_SET_REGISTERED'"
        ).fetchone()[0]
    assert registered == 0
    assert registration_events == 0


def test_inactive_rivalry_and_incompatible_transformations_fail_closed(service):
    database, authority, _ = service
    key = _authority_key(authority)
    with pytest.raises(feature.Stage3FeatureEngineeringError) as caught:
        feature.save_feature_set_draft(
            authority.project_id,
            database,
            {
                "authorityKey": key,
                "featureSetKey": "rivalry-invalid",
                "name": "Rivalry invalid",
                "orderedFeatures": ["batting_rivalry_game"],
                "expectedChecksum": NO_CURRENT_FEATURE_SET,
            },
            "user-1",
        )
    assert caught.value.code == "FEATURE_SET_INACTIVE_FEATURE"

    categorical = "holiday_name"
    assert categorical in CONTEXT_FEATURES
    with pytest.raises(feature.Stage3FeatureEngineeringError) as caught:
        feature.save_feature_set_draft(
            authority.project_id,
            database,
            {
                "authorityKey": key,
                "featureSetKey": "transform-invalid",
                "name": "Transform invalid",
                "orderedFeatures": [categorical],
                "transformationContracts": {categorical: ["STANDARDIZE"]},
                "expectedChecksum": NO_CURRENT_FEATURE_SET,
            },
            "user-1",
        )
    assert caught.value.code == "TRANSFORMATION_TYPE_INCOMPATIBLE"
