from __future__ import annotations

import sqlite3
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from ..persistence.db import PersistenceUnavailableError
from ..security.security_store import require_user
from .schemas import ApprovalRequest, CaseUpdateRequest, ChallengeRequest, ChecklistUpdateRequest, FindingRequest, ResponseRequest, SubmitValidationRequest
from .validation_service import get_validation_service


router = APIRouter(prefix="/validation")


def _execute(operation):
    try:
        return operation()
    except PersistenceUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail=f"ATLAS validation center is temporarily unavailable: {exc}") from exc


@router.get("/queue")
def validation_queue(
    status: str | None = None,
    assigned_validator_user_id: str | None = None,
    project_id: str | None = None,
    limit: int = Query(250, ge=1, le=500),
) -> Dict[str, Any]:
    payload = _execute(lambda: get_validation_service().queue({
        "status": status,
        "assigned_validator_user_id": assigned_validator_user_id,
        "project_id": project_id,
        "limit": limit,
    }))
    return {"ok": True, "cases": payload["items"], "total": payload["total"]}


@router.get("/summary")
def validation_summary() -> Dict[str, Any]:
    return {"ok": True, "summary": _execute(lambda: get_validation_service().summary())}


@router.get("/project/{project_id}")
def validation_project_lookup(project_id: str) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().project_lookup(project_id))}


@router.post("/project/{project_id}/submit")
def submit_validation(project_id: str, payload: SubmitValidationRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().create_or_submit_case(project_id, payload.model_dump(), user))}


@router.get("/cases/{validation_id}")
def validation_case_detail(validation_id: str) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().case_detail(validation_id))}


@router.post("/cases/{validation_id}/start-review")
def start_validation_review(validation_id: str, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().start_review(validation_id, user))}


@router.patch("/cases/{validation_id}")
def update_validation_case(validation_id: str, payload: CaseUpdateRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().update_case(validation_id, payload.model_dump(exclude_unset=True), user))}


@router.patch("/cases/{validation_id}/checklist/{item_key}")
def update_validation_checklist(validation_id: str, item_key: str, payload: ChecklistUpdateRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().update_checklist(validation_id, item_key, payload.model_dump(exclude_unset=True), user))}


@router.post("/cases/{validation_id}/findings")
def create_validation_finding(validation_id: str, payload: FindingRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().upsert_finding(validation_id, payload.model_dump(), user))}


@router.patch("/cases/{validation_id}/findings/{finding_id}")
def update_validation_finding(validation_id: str, finding_id: str, payload: FindingRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().upsert_finding(validation_id, payload.model_dump(exclude_unset=True), user, finding_id))}


@router.post("/cases/{validation_id}/challenges")
def create_validation_challenge(validation_id: str, payload: ChallengeRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().upsert_challenge(validation_id, payload.model_dump(), user))}


@router.patch("/cases/{validation_id}/challenges/{challenge_id}")
def update_validation_challenge(validation_id: str, challenge_id: str, payload: ChallengeRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().upsert_challenge(validation_id, payload.model_dump(exclude_unset=True), user, challenge_id))}


@router.post("/cases/{validation_id}/challenges/{challenge_id}/responses")
def create_validation_response(validation_id: str, challenge_id: str, payload: ResponseRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().add_response(validation_id, challenge_id, payload.model_dump(), user))}


@router.post("/cases/{validation_id}/approvals")
def create_validation_approval(validation_id: str, payload: ApprovalRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    return {"ok": True, **_execute(lambda: get_validation_service().approve(validation_id, payload.model_dump(), user))}
