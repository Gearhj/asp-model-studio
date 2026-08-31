"""Static Phase-1 sport registry and workflow-manifest resolver."""

from __future__ import annotations

from typing import Any, Dict, Tuple

from ..sports_basketball.manifest import NBA_WORKFLOW_MANIFEST, WNBA_WORKFLOW_MANIFEST
from ..sports_mlb.manifest import MLB_WORKFLOW_MANIFEST
from ..sports_mma.manifest import UFC_WORKFLOW_MANIFEST
from ..sports_nfl.manifest import NFL_WORKFLOW_MANIFEST
from .contracts import (
    LeagueCode,
    ParticipantType,
    SPORT_REGISTRY_V1,
    SportAvailabilityState,
    SportCode,
    SportContractError,
    SportRegistry,
    SportRegistryEntry,
    SportRegistryLeague,
    SportWorkflowManifest,
    WorkflowAvailability,
    canonical_league_code,
    canonical_sport_code,
    contract_payload,
)


WORKFLOW_MANIFESTS: Tuple[SportWorkflowManifest, ...] = (
    MLB_WORKFLOW_MANIFEST,
    NFL_WORKFLOW_MANIFEST,
    NBA_WORKFLOW_MANIFEST,
    WNBA_WORKFLOW_MANIFEST,
    UFC_WORKFLOW_MANIFEST,
)

SPORT_REGISTRY = SportRegistry(
    schemaVersion=SPORT_REGISTRY_V1,
    sports=(
        SportRegistryEntry(
            sportCode=SportCode.BASEBALL,
            displayName="Baseball",
            availability=SportAvailabilityState.LIVE,
            participantType=ParticipantType.TEAM,
            leagues=(SportRegistryLeague(
                leagueCode=LeagueCode.MLB,
                displayName="Major League Baseball",
                participantType=ParticipantType.TEAM,
                availability=WorkflowAvailability.ENABLED,
                workflowCodes=(MLB_WORKFLOW_MANIFEST.workflowCode,),
                projectCreationSelectable=True,
            ),),
        ),
        SportRegistryEntry(
            sportCode=SportCode.FOOTBALL,
            displayName="Football",
            availability=SportAvailabilityState.RESEARCH_SHADOW,
            participantType=ParticipantType.TEAM,
            leagues=(SportRegistryLeague(
                leagueCode=LeagueCode.NFL,
                displayName="National Football League",
                participantType=ParticipantType.TEAM,
                availability=WorkflowAvailability.RESEARCH_ONLY,
                workflowCodes=(NFL_WORKFLOW_MANIFEST.workflowCode,),
                projectCreationSelectable=False,
            ),),
        ),
        SportRegistryEntry(
            sportCode=SportCode.BASKETBALL,
            displayName="Basketball",
            availability=SportAvailabilityState.PLANNED,
            participantType=ParticipantType.TEAM,
            leagues=(
                SportRegistryLeague(
                    leagueCode=LeagueCode.NBA,
                    displayName="National Basketball Association",
                    participantType=ParticipantType.TEAM,
                    availability=WorkflowAvailability.PLANNED,
                    workflowCodes=(NBA_WORKFLOW_MANIFEST.workflowCode,),
                    projectCreationSelectable=False,
                ),
                SportRegistryLeague(
                    leagueCode=LeagueCode.WNBA,
                    displayName="Women's National Basketball Association",
                    participantType=ParticipantType.TEAM,
                    availability=WorkflowAvailability.PLANNED,
                    workflowCodes=(WNBA_WORKFLOW_MANIFEST.workflowCode,),
                    projectCreationSelectable=False,
                ),
            ),
        ),
        SportRegistryEntry(
            sportCode=SportCode.MMA,
            displayName="Mixed Martial Arts",
            availability=SportAvailabilityState.PLANNED,
            participantType=ParticipantType.INDIVIDUAL,
            leagues=(SportRegistryLeague(
                leagueCode=LeagueCode.UFC,
                displayName="Ultimate Fighting Championship",
                participantType=ParticipantType.INDIVIDUAL,
                availability=WorkflowAvailability.PLANNED,
                workflowCodes=(UFC_WORKFLOW_MANIFEST.workflowCode,),
                projectCreationSelectable=False,
            ),),
        ),
    ),
)

_MANIFEST_BY_CODE = {manifest.workflowCode: manifest for manifest in WORKFLOW_MANIFESTS}
_MANIFEST_BY_COMPATIBLE_ID = {
    compatible_id: manifest
    for manifest in WORKFLOW_MANIFESTS
    for compatible_id in manifest.compatibleWorkflowIds
}


def get_workflow_manifest(workflow_code: str) -> SportWorkflowManifest:
    value = str(workflow_code).strip()
    manifest = _MANIFEST_BY_CODE.get(value) or _MANIFEST_BY_COMPATIBLE_ID.get(value)
    if manifest is None:
        raise SportContractError(f"Unknown workflow manifest: {value!r}")
    return manifest


def list_workflow_manifests(
    *,
    sport_code: SportCode | str | None = None,
    league_code: LeagueCode | str | None = None,
    selectable_only: bool = False,
) -> Tuple[SportWorkflowManifest, ...]:
    sport = canonical_sport_code(sport_code) if sport_code is not None else None
    league = canonical_league_code(league_code) if league_code is not None else None
    result = tuple(
        manifest for manifest in WORKFLOW_MANIFESTS
        if (sport is None or manifest.sportCode == sport)
        and (league is None or manifest.leagueCode == league)
        and (not selectable_only or manifest.projectTemplateSelectable)
    )
    if sport is not None and league is not None and league.value not in {item.leagueCode.value for entry in SPORT_REGISTRY.sports if entry.sportCode == sport for item in entry.leagues}:
        raise SportContractError("Requested league does not belong to requested sport")
    return result


def validate_workflow_identity(
    *,
    saved_sport_code: SportCode | str,
    saved_league_code: LeagueCode | str,
    saved_workflow_code: str,
    route_sport_code: SportCode | str | None = None,
    route_league_code: LeagueCode | str | None = None,
    require_selectable: bool = False,
) -> SportWorkflowManifest:
    manifest = get_workflow_manifest(saved_workflow_code)
    saved_sport = canonical_sport_code(saved_sport_code)
    saved_league = canonical_league_code(saved_league_code)
    if manifest.sportCode != saved_sport or manifest.leagueCode != saved_league:
        raise SportContractError("Saved project sport, league, and workflow identities do not agree")
    if route_sport_code is not None and canonical_sport_code(route_sport_code) != manifest.sportCode:
        raise SportContractError("Route sport does not match the saved project workflow")
    if route_league_code is not None and canonical_league_code(route_league_code) != manifest.leagueCode:
        raise SportContractError("Route league does not match the saved project workflow")
    if require_selectable and not manifest.projectTemplateSelectable:
        raise SportContractError("Workflow is not selectable for a live project")
    return manifest


def workflow_capability(manifest: SportWorkflowManifest) -> Dict[str, Any]:
    return {
        "sportCode": manifest.sportCode.value,
        "leagueCode": manifest.leagueCode.value,
        "workflowCode": manifest.workflowCode,
        "availability": manifest.availability.value,
        "projectTemplateSelectable": manifest.projectTemplateSelectable,
        "liveNavigationVisible": manifest.liveNavigationVisible,
        "datasetBindingAllowed": manifest.projectTemplateSelectable,
        "modelingEnabled": manifest.modelingEnabled,
        "simulationEnabled": manifest.simulationEnabled,
        "simulatorAdapterCode": manifest.simulatorAdapterCode,
        "readinessMessage": manifest.readinessMessage,
    }


def registry_payload() -> Dict[str, Any]:
    return contract_payload(SPORT_REGISTRY)


__all__ = [
    "SPORT_REGISTRY",
    "WORKFLOW_MANIFESTS",
    "get_workflow_manifest",
    "list_workflow_manifests",
    "registry_payload",
    "validate_workflow_identity",
    "workflow_capability",
]
