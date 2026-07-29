from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.modeling_scope import authorize_modeling_scope
from ..security.security_store import require_user
from .service import EXPERIMENTAL_DESIGN, recommend_designs


router = APIRouter()


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/experimental-design/study")
def get_study(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    return EXPERIMENTAL_DESIGN.read(authorize_modeling_scope(user, project_id, "view"))


@router.put("/experimental-design/study/{project_id}")
def save_study(project_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, project_id, "edit")
    contract = payload.get("contract") if isinstance(payload.get("contract"), dict) else payload
    return EXPERIMENTAL_DESIGN.save(project_id, contract, user, str(payload.get("changeSummary") or ""))


@router.post("/experimental-design/recommend")
def recommend(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "view")
    study = EXPERIMENTAL_DESIGN.read(project_id)["study"]
    return recommend_designs(payload.get("contract") if isinstance(payload.get("contract"), dict) else study["contract"])


@router.post("/experimental-design/power")
def calculate_power(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    try:
        return EXPERIMENTAL_DESIGN.power(project_id, user)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/experimental-design/design/generate")
def generate_design(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    try:
        return EXPERIMENTAL_DESIGN.design(project_id, user)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/experimental-design/randomize")
def randomize(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    try:
        return EXPERIMENTAL_DESIGN.randomize(project_id, user, payload.get("seed"))
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/experimental-design/simulations")
def create_simulation(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    try:
        return EXPERIMENTAL_DESIGN.create_simulation(project_id, user, payload)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/experimental-design/simulations/{job_id}")
def get_simulation(job_id: str, project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, project_id, "view")
    try:
        return EXPERIMENTAL_DESIGN.get_job(project_id, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/experimental-design/simulations/{job_id}/cancel")
def cancel_simulation(job_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    try:
        return EXPERIMENTAL_DESIGN.cancel_job(project_id, job_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/experimental-design/simulations/{job_id}/retry")
def retry_simulation(job_id: str, payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    try:
        return EXPERIMENTAL_DESIGN.retry_job(project_id, job_id, user)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/experimental-design/analyze")
def analyze(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    observations = payload.get("observations") if isinstance(payload.get("observations"), list) else []
    try:
        return EXPERIMENTAL_DESIGN.analyze(project_id, user, observations)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/experimental-design/documentation/capture")
def capture_documentation(payload: Dict[str, Any], user: Dict[str, Any] = Depends(require_user)):
    project_id = authorize_modeling_scope(user, str(payload.get("projectId") or ""), "edit")
    try:
        return EXPERIMENTAL_DESIGN.capture_documentation(project_id, user)
    except ValueError as exc:
        raise _bad_request(exc) from exc
