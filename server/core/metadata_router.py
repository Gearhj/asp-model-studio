# server/core/metadata_router.py
# =============================================================================
# Metadata + Data router – compatibility endpoints for legacy frontend calls:
#
#   GET  /api/columns
#   GET  /api/data/get_sample
#   POST /api/data/set_sample
#
# These are used by:
#   • Step01_DataAcquisition.tsx
#   • Step02_EDA.tsx
#   • Step03/04/05 pages that need columns or samples
#
# They operate on the in-memory DATASTORE and only mutate it to:
#   • set raw_df
#   • optionally set target
# =============================================================================

from __future__ import annotations

from typing import Dict, Any, List, Optional
import re

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .dataset_store import DATASTORE
from .modeling_scope import authorize_modeling_scope
from .pretraining_invalidation import invalidate_downstream_training_state
from .result_store import RESULTS
from .session_checkpoint import schedule_checkpoint_save
from ..datasets.dataset_identity import (
    active_dataset_identity,
    assert_expected_active_identity,
    coalesce_identity_expectations,
    invalidate_dataset_identity,
)
from ..security.security_store import require_user

router = APIRouter()


def _current_df() -> Optional[pd.DataFrame]:
    """
    Prefer processed_df if available, otherwise raw_df, restricted to the
    selected modeling columns from Data Acquisition.
    """
    return DATASTORE.get_active_df()


def _infer_target(
    df: pd.DataFrame,
    *,
    persist: bool = True,
) -> Optional[str]:
    """
    Very light heuristic to guess a target column if not already set:

      • Exact case-insensitive match on: fraud, target, label
    """
    # If already set and valid, keep it
    if DATASTORE.target is not None and DATASTORE.target in df.columns:
        return DATASTORE.target

    pattern = re.compile(
        r"^(fraud|target|label|class|y|bad|default|outcome|response|event)$",
        flags=re.IGNORECASE,
    )
    for col in df.columns:
        if pattern.search(str(col)):
            if persist:
                DATASTORE.set_target(str(col))
            return str(col)

    for col in reversed(list(df.columns)):
        s = df[col].dropna()
        if s.empty:
            continue
        unique = pd.unique(s)
        if 1 < len(unique) <= 2:
            if persist:
                DATASTORE.set_target(str(col))
            return str(col)

    return None


# -----------------------------------------------------------------------------
# Pydantic model for /data/set_sample
# -----------------------------------------------------------------------------
class SetSamplePayload(BaseModel):
    project_id: str
    headers: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    target: Optional[str] = None
    selected_columns: Optional[List[str]] = None
    expected_dataset_id: Optional[str] = None
    expected_dataset_version_id: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_version_id: Optional[str] = None
    dataset_version: Optional[str] = None
    access_metadata_id: Optional[str] = None
    profile_snapshot_id: Optional[str] = None


class SetTargetPayload(BaseModel):
    project_id: str
    target: Optional[str] = None
    selected_columns: Optional[List[str]] = None
    expected_dataset_id: Optional[str] = None
    expected_dataset_version_id: Optional[str] = None
    dataset_id: Optional[str] = None
    dataset_version_id: Optional[str] = None
    dataset_version: Optional[str] = None
    access_metadata_id: Optional[str] = None
    profile_snapshot_id: Optional[str] = None


def _payload_expected_identity(
    payload: Any,
) -> tuple[str, str, str]:
    return coalesce_identity_expectations(
        expected_dataset_id=payload.expected_dataset_id,
        expected_dataset_version_id=payload.expected_dataset_version_id,
        dataset_id=payload.dataset_id,
        dataset_version_id=payload.dataset_version_id,
        legacy_dataset_version=payload.dataset_version,
    )


def _record_subordinate_metadata(payload: Any) -> None:
    if payload.access_metadata_id:
        DATASTORE.meta["access_metadata_id"] = str(payload.access_metadata_id)
    if payload.profile_snapshot_id:
        DATASTORE.meta["profile_snapshot_id"] = str(payload.profile_snapshot_id)


# -----------------------------------------------------------------------------
# POST /api/data/set_sample
# -----------------------------------------------------------------------------
@router.post("/data/set_sample")
def set_sample(payload: SetSamplePayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """
    Legacy-compatible endpoint used by Step01_DataAcquisition.tsx.

    Payload shape:

        {
          "project_id": "...",
          "headers": [...],
          "rows": [ {col: val, ...}, ... ],
          "target": "TARGET" | null,
          "selected_columns": [...]
        }

    We:
      • Build a DataFrame from rows
      • Store it into DATASTORE.raw_df, scoped to (user, project_id)
      • Optionally set DATASTORE.target
    """
    authorize_modeling_scope(user, payload.project_id, "edit")
    (
        expected_dataset_id,
        expected_version_id,
        legacy_version,
    ) = _payload_expected_identity(payload)
    has_active_identity = bool(
        DATASTORE.meta.get("dataset_id") and DATASTORE.meta.get("dataset_version_id")
    )
    if has_active_identity:
        assert_expected_active_identity(
            payload.project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_version_id,
            legacy_dataset_version=legacy_version,
            user=user,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                "Raw rows cannot replace an activated immutable Dataset Library "
                "version. Register and activate the new dataset first."
            ),
        )
    if expected_dataset_id or expected_version_id or payload.dataset_version:
        raise HTTPException(
            status_code=409,
            detail="No exact registered Dataset Library version is active for the supplied identity.",
        )
    if not payload.rows:
        return {"ok": False, "error": "No rows provided."}

    try:
        df = pd.DataFrame(payload.rows)
    except Exception as exc:
        return {"ok": False, "error": f"Failed to build DataFrame: {exc}"}

    if df.empty:
        return {"ok": False, "error": "Constructed DataFrame is empty."}

    resolved_target = (
        payload.target
        if payload.target and payload.target in df.columns
        else _infer_target(df, persist=False)
    )

    columns = [str(col) for col in df.columns]
    selected_columns = [
        str(col)
        for col in (payload.selected_columns or [])
        if str(col) in columns and str(col) != resolved_target
    ]
    # Preserve the complete source frame. selected_columns governs the active
    # modeling view without destroying columns that a reviewer may restore.
    scoped_store = DATASTORE.current()
    scoped_results = RESULTS.current()
    with scoped_store.state_lock:
        scoped_store.set_raw(df)
        scoped_store.set_target(resolved_target)
        invalidate_dataset_identity(
            "Legacy sample rows are a workspace draft. Register and activate an exact Dataset Library version before governed modeling.",
            store=scoped_store,
        )
        # Identity invalidation clears preparation metadata, so restore the
        # user's draft predictor contract only after that fail-closed reset.
        scoped_store.meta["selected_columns"] = selected_columns
        _record_subordinate_metadata(payload)
        invalidate_downstream_training_state(
            "The workspace sample changed.",
            store=scoped_store,
            result_store=scoped_results,
            split_status="",
            bump_revision=False,
        )

    schedule_checkpoint_save()

    return {
        "ok": True,
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": [str(c) for c in df.columns],
        "target": DATASTORE.target,
        "selected_columns": selected_columns,
        "dataset_identity_status": DATASTORE.meta.get("dataset_identity_status"),
    }


@router.post("/data/set_target")
def set_target(payload: SetTargetPayload, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """
    Update target/selected feature metadata without replacing DATASTORE.raw_df.

    This is required after large backend CSV imports: the browser only keeps a
    preview sample, but the backend must retain the full imported dataset.
    """
    authorize_modeling_scope(user, payload.project_id, "edit")
    (
        expected_dataset_id,
        expected_version_id,
        legacy_version,
    ) = _payload_expected_identity(payload)
    scoped_store = DATASTORE.current()
    scoped_results = RESULTS.current()
    with scoped_store.state_lock:
        identity = assert_expected_active_identity(
            payload.project_id,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_version_id,
            legacy_dataset_version=legacy_version,
            require_expected=True,
            user=user,
            store=scoped_store,
        )
        df = scoped_store.get_base_df()
        if df is None or df.empty:
            return {"ok": False, "error": "No backend dataset is loaded."}

        previous_target = scoped_store.target
        previous_selected = scoped_store.get_selected_columns()
        if payload.target:
            if payload.target not in df.columns:
                return {"ok": False, "error": f"Target column '{payload.target}' is not present in the loaded dataset."}
            scoped_store.set_target(payload.target)
        else:
            scoped_store.set_target(None)

        columns = [str(col) for col in df.columns]
        selected_columns = [
            str(col)
            for col in (payload.selected_columns or [])
            if str(col) in columns and str(col) != scoped_store.target
        ]
        contract_changed = (
            previous_target != scoped_store.target
            or previous_selected != selected_columns
        )
        if contract_changed:
            scoped_store.processed_df = None
            for key in (
                "processed_stage",
                "outlier_application",
                "missing_application",
                "missing_config",
                "missing_validation",
                "materialized_feature_names",
                "feature_manifest",
                "feature_preview",
            ):
                scoped_store.meta.pop(key, None)
        scoped_store.meta["selected_columns"] = selected_columns
        _record_subordinate_metadata(payload)
        if contract_changed:
            invalidate_downstream_training_state(
                "The governed target or predictor selection changed.",
                store=scoped_store,
                result_store=scoped_results,
                split_status="",
            )

        active_df = scoped_store.get_active_df()
        active_columns = (
            [str(col) for col in active_df.columns]
            if active_df is not None
            else columns
        )
    schedule_checkpoint_save()

    return {
        "ok": True,
        "n_rows": int(active_df.shape[0] if active_df is not None else df.shape[0]),
        "n_cols": int(active_df.shape[1] if active_df is not None else df.shape[1]),
        "columns": active_columns,
        "target": scoped_store.target,
        "selected_columns": selected_columns,
        "project_id": identity.get("project_id") if identity else payload.project_id,
        "dataset_id": identity.get("dataset_id") if identity else None,
        "dataset_version_id": identity.get("dataset_version_id") if identity else None,
        "dataset_identity_status": scoped_store.meta.get("dataset_identity_status"),
    }


@router.get("/data/active-identity")
def get_active_identity(
    project_id: str = Query(...),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    identity = active_dataset_identity(project_id, user=user)
    link = identity.get("project_link") or {}
    selection = identity.get("active_selection") or {}
    return {
        "ok": True,
        "project_id": identity["project_id"],
        "dataset_id": identity["dataset_id"],
        "dataset_version_id": identity["dataset_version_id"],
        "dataset_version_label": identity.get("dataset_version_label"),
        "dataset_content_hash": identity.get("dataset_content_hash"),
        "dataset_schema_hash": identity.get("dataset_schema_hash"),
        "dataset_source_type": identity.get("dataset_source_type"),
        "activation_revision": identity.get("activation_revision"),
        "link": {
            "project_id": link.get("project_id"),
            "dataset_id": link.get("dataset_id"),
            "link_status": link.get("link_status"),
            "linked_by": link.get("linked_by"),
            "linked_at": link.get("linked_at"),
            "updated_at": link.get("updated_at"),
        },
        "active_selection": {
            "project_id": selection.get("project_id"),
            "dataset_id": selection.get("dataset_id"),
            "dataset_version_id": selection.get("dataset_version_id"),
            "activation_revision": selection.get("activation_revision"),
            "activation_status": selection.get("activation_status"),
            "activated_by": selection.get("activated_by"),
            "activated_at": selection.get("activated_at"),
            "updated_at": selection.get("updated_at"),
        },
    }


# -----------------------------------------------------------------------------
# GET /api/columns
# -----------------------------------------------------------------------------
@router.get("/columns")
def get_columns(project_id: str = Query(...), user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """
    Column metadata used by several steps.

    Response shape matches frontend expectations:

        {
          "ok": true,
          "columns": [
            {"name": "AGE", "dtype": "float64", "role": "feature"},
            {"name": "TARGET", "dtype": "int64", "role": "target"}
          ],
          "target": "TARGET"
        }
    """
    authorize_modeling_scope(user, project_id, "view")
    df = _current_df()
    if df is None or df.empty:
        return {"ok": True, "columns": [], "target": None}

    # Read-only discovery may suggest a target but must never persist it.
    # Governed target changes belong exclusively to /data/set_target.
    target = _infer_target(df, persist=False)

    columns: List[Dict[str, Any]] = []
    for name in df.columns:
        s = df[name]
        columns.append(
            {
                "name": str(name),
                "dtype": str(s.dtype),
                "role": "target" if target is not None and str(name) == target else "feature",
            }
        )

    return {
        "ok": True,
        "columns": columns,
        "target": target,
    }


# -----------------------------------------------------------------------------
# GET /api/data/get_sample
# -----------------------------------------------------------------------------
@router.get("/data/get_sample")
def get_sample(project_id: str = Query(...), max_rows: int = 5000, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    """
    Sample of the current dataset.

    Shape aligns with what Step04_Outliers.tsx expects:

        {
          "ok": true,
          "headers": [...],
          "rows": [{"col": "value", ...}, ...],
          "target": "TARGET",
          "selected_columns": null
        }
    """
    authorize_modeling_scope(user, project_id, "view")
    df = _current_df()
    if df is None or df.empty:
        return {
            "ok": True,
            "headers": [],
            "rows": [],
            "target": DATASTORE.target,
            "selected_columns": None,
        }

    sample_df = df.head(max_rows)
    headers = [str(c) for c in sample_df.columns]
    rows = sample_df.to_dict(orient="records")

    return {
        "ok": True,
        "headers": headers,
        "rows": rows,
        "target": DATASTORE.target,
        "selected_columns": DATASTORE.meta.get("selected_columns"),
    }
