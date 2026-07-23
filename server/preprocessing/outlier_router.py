from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..core.session_checkpoint import save_checkpoint
from ..security.security_store import require_user
from .outlier_service import outlier_service


router = APIRouter()


class OutlierSummaryRequest(BaseModel):
    project_id: str
    target: str | None = None
    event_value: Any = None
    problem_type: str | None = None
    method: str | None = None
    z_thresh: float = 3.0


class OutlierApplyRequest(BaseModel):
    project_id: str
    config: dict[str, str] = Field(default_factory=dict)
    global_method: str = "IQR_1_5"
    target: str | None = None
    event_value: Any = None
    problem_type: str | None = None


def _source_df():
    df = DATASTORE.get_raw_active_df()
    if df is None or df.empty:
        raise HTTPException(status_code=400, detail="No full registered dataset is loaded.")
    return df


@router.post("/summary")
def outliers_summary(request: OutlierSummaryRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "view")
    try:
        result = outlier_service.summary(
            _source_df(),
            target=request.target or DATASTORE.target,
            event_value=request.event_value,
            problem_type=request.problem_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result["dataset_version"] = DATASTORE.meta.get("dataset_version") or "unversioned"
    result["application"] = DATASTORE.meta.get("outlier_application")
    return json_safe(result)


@router.post("/apply")
def apply_outlier_treatments(request: OutlierApplyRequest, user: Dict[str, Any] = Depends(require_user)):
    authorize_modeling_scope(user, request.project_id, "edit")
    target = request.target or DATASTORE.target
    try:
        work, applied = outlier_service.apply(
            _source_df(),
            config=request.config,
            global_method=request.global_method,
            target=target,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    applied_at = datetime.now(timezone.utc).isoformat()
    application = {
        "applied_at": applied_at,
        "dataset_version": DATASTORE.meta.get("dataset_version") or "unversioned",
        "row_count": int(len(work)),
        "global_method": request.global_method,
        "config": dict(request.config),
        "treatments": applied,
        "changed_values": int(sum(int(row.get("changed_values") or 0) for row in applied)),
    }
    DATASTORE.set_processed(work)
    DATASTORE.meta["processed_stage"] = "outliers"
    DATASTORE.meta["outlier_application"] = application
    DATASTORE.meta.pop("missing_application", None)
    DATASTORE.meta.pop("missing_config", None)
    DATASTORE.meta["split_status"] = "stale"
    manifest = DATASTORE.meta.get("feature_manifest")
    if isinstance(manifest, dict):
        manifest["split_status"] = "stale"

    if not save_checkpoint():
        raise HTTPException(status_code=500, detail="Outlier treatments were calculated, but ATLAS could not persist the workflow checkpoint.")
    return json_safe({"ok": True, "scope": "full_dataset", "application": application})
