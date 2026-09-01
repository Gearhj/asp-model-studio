from __future__ import annotations

import json

import pytest
from fastapi.routing import APIRoute
from pydantic import ValidationError

from server.main import create_app
from server.security.security_store import require_user
from server.sports_mlb.manifest import MLB_WORKFLOW_MANIFEST
from server.sports_nfl.manifest import NFL_WORKFLOW_MANIFEST
from server.sports_shared.contracts import (
    DatasetBindingDescriptor,
    DatasetIdentityEnvelope,
    LeagueCode,
    ModelSportMetadataEnvelope,
    SPORT_MODEL_METADATA_V1,
    SPORT_REGISTRY_V1,
    SPORT_SIMULATION_METADATA_V1,
    SPORT_WORKFLOW_MANIFEST_V1,
    SimulationSportMetadataEnvelope,
    SportCode,
    SportContractError,
    SportWorkflowManifest,
    WorkflowAvailability,
    contract_payload,
    validate_dataset_binding,
    validate_model_sport_metadata,
    validate_simulation_sport_metadata,
)
from server.sports_shared.registry import (
    SPORT_REGISTRY,
    WORKFLOW_MANIFESTS,
    get_workflow_manifest,
    list_workflow_manifests,
    validate_workflow_identity,
)
from server.sports_shared.router import read_sport_capabilities, read_sport_manifests


def _has_require_user(route: APIRoute) -> bool:
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        if dependency.call is require_user:
            return True
        pending.extend(dependency.dependencies)
    return False


def _dataset(*, sport=SportCode.BASEBALL, league=LeagueCode.MLB, grain="PLATE_APPEARANCE", eligible=True):
    return DatasetBindingDescriptor(
        datasetId="dataset-1",
        datasetVersionId="dataset-version-1",
        manifestSha256="a" * 64,
        sportCode=sport,
        leagueCode=league,
        datasetGrain=grain,
        predictionUnits=("PLATE_APPEARANCE", "GAME"),
        activationEligible=eligible,
    )


def test_sport_registry_v1_relations_are_canonical_and_complete():
    assert SPORT_REGISTRY.schemaVersion == SPORT_REGISTRY_V1
    relation = {
        sport.sportCode: tuple(league.leagueCode for league in sport.leagues)
        for sport in SPORT_REGISTRY.sports
    }
    assert relation == {
        SportCode.BASEBALL: (LeagueCode.MLB,),
        SportCode.FOOTBALL: (LeagueCode.NFL,),
        SportCode.BASKETBALL: (LeagueCode.NBA, LeagueCode.WNBA),
        SportCode.MMA: (LeagueCode.UFC,),
    }


def test_manifest_contract_requires_every_field_and_rejects_extras():
    payload = contract_payload(MLB_WORKFLOW_MANIFEST)
    assert payload["schemaVersion"] == SPORT_WORKFLOW_MANIFEST_V1
    missing = dict(payload)
    missing.pop("pointInTimePolicy")
    with pytest.raises(ValidationError):
        SportWorkflowManifest.model_validate(missing)
    with_extra = {**payload, "mlbOnlyShortcut": True}
    with pytest.raises(ValidationError):
        SportWorkflowManifest.model_validate(with_extra)


def test_mlb_manifest_is_exact_enabled_reference_package():
    manifest = get_workflow_manifest("mlb-forecasting")
    assert manifest is MLB_WORKFLOW_MANIFEST
    assert manifest.workflowCode == "MLB_GAME_FORECAST_WORKFLOW_V1"
    assert manifest.availability == WorkflowAvailability.ENABLED
    assert manifest.projectTemplateSelectable is True
    assert manifest.supportedPredictionUnits == ("PLATE_APPEARANCE", "PLAYER_GAME", "TEAM_GAME", "GAME")
    assert manifest.supportedTargets == (
        "EIGHT_CLASS_PLATE_APPEARANCE_OUTCOME",
        "JOINT_SCORE_DISTRIBUTION",
        "HOME_WIN_PROBABILITY",
        "RUN_DIFFERENTIAL",
        "TOTAL_RUNS",
    )
    assert len(manifest.workflowStages) == 9
    assert len(manifest.developmentSteps) == 14
    model_lab_index = manifest.developmentSteps.index("MODEL_LAB")
    assert manifest.developmentSteps[model_lab_index + 1] == "EVALUATION"
    assert manifest.validationTemplates[0].rules == (
        "CHRONOLOGICAL",
        "DATE_ATOMIC",
        "CANONICAL_GAME_GROUPED",
        "EXPANDING_WINDOW",
        "FINAL_OOT_LOCKED",
    )
    assert manifest.simulatorAdapterCode == "MLB_WHOLE_GAME_MONTE_CARLO_SIMULATOR"
    assert manifest.supportedMarketTypes == (
        "FULL_GAME_MONEYLINE",
        "FIRST_FIVE_MONEYLINE",
        "RUN_LINE",
        "FULL_GAME_TOTAL",
        "FIRST_FIVE_TOTAL",
    )


def test_nfl_manifest_is_football_specific_and_honestly_research_only():
    manifest = NFL_WORKFLOW_MANIFEST
    payload = json.dumps(contract_payload(manifest), sort_keys=True).upper()
    assert manifest.sportCode == SportCode.FOOTBALL
    assert manifest.availability == WorkflowAvailability.RESEARCH_ONLY
    assert manifest.projectTemplateSelectable is False
    assert manifest.liveNavigationVisible is False
    assert manifest.modelingEnabled is False
    assert manifest.simulationEnabled is False
    assert manifest.supportedPredictionUnits == ("PLAY", "DRIVE", "PLAYER_GAME", "TEAM_GAME", "GAME")
    assert "QUARTERBACK_DEPTH_CHART" in manifest.optionalEvidenceFamilies
    assert "WEEKLY_SLATES" in manifest.validationTemplates[0].rules
    assert manifest.simulatorAdapterCode == "NFL_MONTE_CARLO_FIELD_SIMULATOR"
    for baseball_semantic in ("PLATE_APPEARANCE", "BATTER", "PITCHER", "BASE_STATE"):
        assert baseball_semantic not in payload
    assert {"RESEARCH_SHADOW", "NOT_PROMOTED", "NOT_EXECUTABLE"}.issubset(manifest.deploymentRestrictions)


def test_planned_workflows_are_registered_but_never_selectable_or_live():
    planned = [manifest for manifest in WORKFLOW_MANIFESTS if manifest.leagueCode in {LeagueCode.NBA, LeagueCode.WNBA, LeagueCode.UFC}]
    assert len(planned) == 3
    assert all(manifest.availability == WorkflowAvailability.PLANNED for manifest in planned)
    assert all(not manifest.projectTemplateSelectable for manifest in planned)
    assert all(not manifest.liveNavigationVisible for manifest in planned)
    assert list_workflow_manifests(selectable_only=True) == (MLB_WORKFLOW_MANIFEST,)


def test_project_and_route_workflow_identity_mismatches_fail_closed():
    assert validate_workflow_identity(
        saved_sport_code="Baseball",
        saved_league_code="MLB",
        saved_workflow_code="mlb-forecasting",
        route_sport_code="BASEBALL",
        route_league_code="MLB",
        require_selectable=True,
    ) is MLB_WORKFLOW_MANIFEST
    with pytest.raises(SportContractError):
        validate_workflow_identity(
            saved_sport_code="BASEBALL",
            saved_league_code="MLB",
            saved_workflow_code="mlb-forecasting",
            route_sport_code="FOOTBALL",
        )
    with pytest.raises(SportContractError):
        validate_workflow_identity(
            saved_sport_code="FOOTBALL",
            saved_league_code="NFL",
            saved_workflow_code="nfl-forecasting",
            require_selectable=True,
        )


def test_dataset_binding_rejects_cross_sport_wrong_grain_and_read_only_authority():
    assert validate_dataset_binding(
        MLB_WORKFLOW_MANIFEST,
        _dataset(),
        required_prediction_unit="PLATE_APPEARANCE",
    ).datasetId == "dataset-1"
    with pytest.raises(SportContractError):
        validate_dataset_binding(
            MLB_WORKFLOW_MANIFEST,
            _dataset(sport=SportCode.FOOTBALL, league=LeagueCode.NFL, grain="GAME_PREGAME"),
        )
    with pytest.raises(SportContractError):
        validate_dataset_binding(MLB_WORKFLOW_MANIFEST, _dataset(grain="POSSESSION"))
    with pytest.raises(SportContractError):
        validate_dataset_binding(MLB_WORKFLOW_MANIFEST, _dataset(eligible=False))


def test_model_and_simulation_envelopes_retain_sport_identity():
    identity = DatasetIdentityEnvelope(
        datasetId="gold-table:gold_mlb_current_pa_v1",
        datasetVersionId="gold-version-1",
        manifestSha256="b" * 64,
        sportCode=SportCode.BASEBALL,
        leagueCode=LeagueCode.MLB,
        datasetGrain="PLATE_APPEARANCE",
    )
    model = ModelSportMetadataEnvelope(
        schemaVersion=SPORT_MODEL_METADATA_V1,
        modelId="model-1",
        modelVersion="v1",
        sportCode=SportCode.BASEBALL,
        leagueCode=LeagueCode.MLB,
        workflowCode="MLB_GAME_FORECAST_WORKFLOW_V1",
        predictionUnit="PLATE_APPEARANCE",
        target="EIGHT_CLASS_PLATE_APPEARANCE_OUTCOME",
        datasetIdentity=identity,
        featureContract="CORE_GOLD_48",
        validationContract="MLB_EXPANDING_DATE_ATOMIC_GAME_GROUPED_V1",
        simulatorAdapterCode="MLB_WHOLE_GAME_MONTE_CARLO_SIMULATOR",
        promotionState="NOT_PROMOTED",
    )
    assert validate_model_sport_metadata(MLB_WORKFLOW_MANIFEST, model) is model
    simulation = SimulationSportMetadataEnvelope(
        schemaVersion=SPORT_SIMULATION_METADATA_V1,
        simulationId="simulation-1",
        sportCode=SportCode.BASEBALL,
        leagueCode=LeagueCode.MLB,
        workflowCode="mlb-forecasting",
        predictionUnit="GAME",
        target="JOINT_SCORE_DISTRIBUTION",
        datasetIdentity=identity,
        modelId="model-1",
        modelVersion="v1",
        simulatorAdapterCode="MLB_WHOLE_GAME_MONTE_CARLO_SIMULATOR",
        seed=731026,
        draws=10000,
        assumptions=("PREGAME_EVIDENCE_ONLY",),
        executable=True,
        deploymentState="RESEARCH_ONLY",
    )
    assert validate_simulation_sport_metadata(MLB_WORKFLOW_MANIFEST, simulation) is simulation


def test_discovery_routes_are_authenticated_and_static_only():
    app = create_app()
    routes = {
        route.path: route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/sports/")
    }
    for path in (
        "/api/sports/registry",
        "/api/sports/manifests",
        "/api/sports/manifests/{workflow_code}",
        "/api/sports/capabilities",
    ):
        assert path in routes
        assert _has_require_user(routes[path])

    capabilities = read_sport_capabilities()
    assert set(capabilities["activity"].values()) == {0}
    assert len(read_sport_manifests(None, None, False)["manifests"]) == 5
