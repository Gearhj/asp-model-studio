"""Governed target-dependent profiling routes.

One endpoint, one server-derived scope. The caller does not choose whether the
result is governed: supplying a dataset and version REQUESTS the governed path,
and the server decides whether it can honour that (authorized, resolvable,
complete artifact) or must refuse with `full_artifact_missing`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..analysis_partition.types import AnalysisPartitionError
from ..core.modeling_scope import authorize_modeling_scope
from ..datasets.dataset_identity import assert_expected_active_identity
from ..security.security_store import audit_event, require_user, user_can_access_project
from .governed_profile_service import governed_target_profile, workspace_target_profile


router = APIRouter(dependencies=[Depends(require_user)])


class TargetProfileRequest(BaseModel):
    """Only SELECTION comes from the client.

    Deliberately absent: scope mode, profile scope, exact status, evidence
    eligibility, artifact checksum, population size, governance status. Extra
    fields are rejected rather than carried, so a crafted request cannot assert
    that a preview is a governed population.
    """

    model_config = {"extra": "forbid"}

    project_id: str
    dataset_id: Optional[str] = None
    version_id: Optional[str] = None
    target: str
    event_value: Any = None
    non_event_value: Any = None
    problem_type: str = "classification"
    include_iv: bool = True
    selected_columns: List[str] = Field(default_factory=list)


def _check_project(user: Dict[str, Any], project_id: str) -> None:
    if not project_id:
        raise HTTPException(status_code=400, detail="A project_id is required.")
    if not user_can_access_project(project_id):
        audit_event(
            "access.denied", "project", project_id, "denied",
            user_id=str(user.get("userId") or ""), reason="Target profiling denied for project ACL",
        )
        raise HTTPException(status_code=403, detail="You do not have access to profiling for this project.")


@router.post("/data/target-profile")
def target_profile(payload: TargetProfileRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """Target-dependent data quality and Information Value.

    Governed when a dataset version is supplied and resolves; otherwise the
    in-memory workspace population, declared as `workspace_draft` or, when the
    backend demonstrably holds less than the source declares, `preview_only`.
    """
    _check_project(user, payload.project_id)
    authorize_modeling_scope(user, payload.project_id, "view")
    user_scope = str(user.get("userId") or "anonymous")

    if bool(payload.dataset_id) != bool(payload.version_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "Both dataset_id and version_id are required for a governed "
                "target profile."
            ),
        )
    if payload.dataset_id and payload.version_id:
        identity = assert_expected_active_identity(
            payload.project_id,
            expected_dataset_id=payload.dataset_id,
            expected_dataset_version_id=payload.version_id,
            require_expected=True,
            user=user,
        )
        try:
            return governed_target_profile(
                user_scope=user_scope, project_id=identity["project_id"],
                dataset_id=identity["dataset_id"],
                version_id=identity["dataset_version_id"],
                target=payload.target, event_value=payload.event_value,
                non_event_value=payload.non_event_value, problem_type=payload.problem_type,
                include_iv=payload.include_iv, selected_columns=payload.selected_columns,
            )
        except AnalysisPartitionError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.as_detail(),
            ) from exc

    return workspace_target_profile(
        user_scope=user_scope, project_id=payload.project_id, target=payload.target,
        event_value=payload.event_value, non_event_value=payload.non_event_value,
        problem_type=payload.problem_type, include_iv=payload.include_iv,
        selected_columns=payload.selected_columns,
    )
