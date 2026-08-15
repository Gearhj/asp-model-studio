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
import hashlib
import json
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
    durable_active_dataset_identity,
    invalidate_dataset_identity,
)
from ..security.security_store import require_user
from ..persistence.service import get_persistence_service
from ..persistence.db import now_iso
from ..preprocessing.predictor_authorization import (
    PredictorAuthorizationIntegrityError,
    governed_predictor_authorization,
    verify_durable_predictor_authorization,
)
from ..analysis_partition.service import analysis_partition_service
from ..analysis_partition.types import (
    ANALYSIS_PARTITION_REQUIRED,
    AnalysisPartitionError,
)
from ..preprocessing.development_scope import (
    resolve_development_analysis_scope,
    scope_http_exception,
)

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
    event_value: Optional[Any] = None
    non_event_value: Optional[Any] = None


def _stable_contract_id(prefix: str, payload: Dict[str, Any]) -> str:
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:20]}"


def _persist_predictor_authorization(
    *,
    project_id: str,
    identity: Dict[str, Any],
    target: Optional[str],
    event_value: Any,
    non_event_value: Any,
    frame: pd.DataFrame,
    selected_columns: List[str],
    user: Dict[str, Any],
) -> Dict[str, Any]:
    """Create the durable pre-partition predictor authorization manifest.

    Data Acquisition still owns the unsealed registered target at this point,
    so deterministic target sources are detected once here and persisted with
    their mappings. Downstream EDA consumes this lineage without rediscovering
    against a sealed final-holdout target.
    """

    target_contract = {
        "project_id": project_id,
        "dataset_id": str(identity.get("dataset_id") or ""),
        "dataset_version_id": str(identity.get("dataset_version_id") or ""),
        "target": target,
        "positive_value": event_value,
        "negative_value": non_event_value,
    }
    target_contract_id = _stable_contract_id("target-contract", target_contract)
    resolved = governed_predictor_authorization(
        frame,
        target,
        selected_columns,
        detect_target_sources=True,
        include_prior_authorization=False,
    )
    manifest_base = {
        **target_contract,
        "target_contract_id": target_contract_id,
        "authorized_predictors": sorted(resolved["authorized_predictors"]),
        "excluded_predictors": resolved["excluded_predictors"],
        "selected_predictors": sorted(resolved["selected_predictors"]),
        "target_source_excluded": resolved["target_source_excluded"],
        "target_source_fields": resolved["target_source_fields"],
        "target_source_detection_scope": resolved["target_source_detection_scope"],
        "source": "data_acquisition",
    }
    predictor_authorization_id = _stable_contract_id(
        "predictor-auth", manifest_base
    )
    created_at = now_iso()
    manifest = {
        **manifest_base,
        "manifest_version": predictor_authorization_id,
        "predictor_authorization_id": predictor_authorization_id,
        "target_source_evidence_ref": predictor_authorization_id,
        "artifact_hash": predictor_authorization_id.removeprefix("predictor-auth-"),
        "status": "current",
        "created_at": created_at,
        "created_by": str(user.get("userId") or "atlas-user"),
    }
    persistence = get_persistence_service()
    persistence.ensure_project(project_id, user)
    persistence.predictor_authorizations.set_current(manifest)
    persistence.evidence.upsert(
        {
            "evidence_id": predictor_authorization_id,
            "project_id": project_id,
            "workflow_type": "predictive_modeling",
            "step_id": "data_acquisition",
            "artifact_type": "predictor_authorization_manifest",
            "status": "confirmed",
            "title": "Data Acquisition Predictor Authorization",
            "summary": (
                f"{len(manifest['authorized_predictors'])} predictors authorized "
                "before the Analysis Partition was reserved; "
                f"{len(manifest['target_source_excluded'])} deterministic target "
                "source field(s) excluded with registered-population evidence."
            ),
            "source_ref": (
                f"dataset:{identity.get('dataset_id')}:"
                f"version:{identity.get('dataset_version_id')}"
            ),
            "artifact_hash": manifest["artifact_hash"],
            "created_by": manifest["created_by"],
            "created_at": created_at,
            "captured_at": created_at,
            "approved_at": created_at,
            "payload_json": manifest,
        }
    )
    return manifest


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
        previous_manifest = (
            scoped_store.meta.get("predictor_authorization_manifest")
            if isinstance(
                scoped_store.meta.get("predictor_authorization_manifest"), dict
            )
            else {}
        )
        if not previous_manifest:
            durable_previous = (
                get_persistence_service()
                .predictor_authorizations.get_current_exact(
                    payload.project_id,
                    str(identity.get("dataset_id") or ""),
                    str(identity.get("dataset_version_id") or ""),
                )
            )
            durable_previous_manifest = (durable_previous or {}).get(
                "manifest_json"
            )
            if isinstance(durable_previous_manifest, dict):
                previous_manifest = durable_previous_manifest
        previous_target = previous_target or previous_manifest.get("target")
        previous_selected = sorted(
            str(value)
            for value in (
                previous_manifest.get("authorized_predictors")
                or scoped_store.get_selected_columns()
                or []
            )
        )
        previous_event_value = scoped_store.meta.get(
            "event_value",
            previous_manifest.get("positive_value"),
        )
        previous_non_event_value = scoped_store.meta.get(
            "non_event_value",
            previous_manifest.get("negative_value"),
        )
        if payload.target:
            if payload.target not in df.columns:
                return {"ok": False, "error": f"Target column '{payload.target}' is not present in the loaded dataset."}
            scoped_store.set_target(payload.target)
        else:
            scoped_store.set_target(None)

        columns = [str(col) for col in df.columns]
        requested_columns = [
            str(col)
            for col in (payload.selected_columns or [])
            if str(col) in columns and str(col) != scoped_store.target
        ]
        authorization_manifest = _persist_predictor_authorization(
            project_id=payload.project_id,
            identity=identity,
            target=scoped_store.target,
            event_value=payload.event_value,
            non_event_value=payload.non_event_value,
            frame=df,
            selected_columns=requested_columns,
            user=user,
        )
        # System, split, target-source, and prohibited fields are never written
        # back into the governed selected-column contract.  Compare canonical
        # sets so browser ordering and a stray ``atlas_split`` field cannot
        # invalidate a valid partition or downstream design.
        selected_columns = list(authorization_manifest["authorized_predictors"])
        target_contract_changed = (
            previous_target != scoped_store.target
            or str(previous_event_value) != str(payload.event_value)
            or str(previous_non_event_value) != str(payload.non_event_value)
        )
        predictor_contract_changed = previous_selected != sorted(selected_columns)
        contract_changed = target_contract_changed or predictor_contract_changed
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
        scoped_store.meta["event_value"] = payload.event_value
        scoped_store.meta["non_event_value"] = payload.non_event_value
        scoped_store.meta["target_contract_id"] = authorization_manifest[
            "target_contract_id"
        ]
        scoped_store.meta["predictor_authorization_id"] = authorization_manifest[
            "predictor_authorization_id"
        ]
        scoped_store.meta["predictor_authorization"] = authorization_manifest
        scoped_store.meta["predictor_authorization_manifest"] = (
            authorization_manifest
        )
        _record_subordinate_metadata(payload)
        if target_contract_changed:
            # The durable Analysis Partition owns row membership independently
            # from later feature/split materialization.  A target definition
            # change is one of the few events that makes that membership stale.
            try:
                from ..analysis_partition.service import analysis_partition_service

                analysis_partition_service.invalidate(
                    project_id=payload.project_id,
                    reason="The governed target or class mapping changed.",
                    user=user,
                    expected_dataset_id=str(identity.get("dataset_id") or ""),
                    expected_dataset_version_id=str(
                        identity.get("dataset_version_id") or ""
                    ),
                )
            except ImportError:
                # During additive migration rollout the new authority may not
                # yet be importable.  Exact identity checks still fail closed;
                # production builds include the service and exercise this path.
                pass
        if contract_changed:
            invalidate_downstream_training_state(
                (
                    "The governed target or class mapping changed."
                    if target_contract_changed
                    else "The governed predictor authorization changed; the row partition was preserved."
                ),
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
        "target_contract_id": authorization_manifest["target_contract_id"],
        "predictor_authorization_id": authorization_manifest[
            "predictor_authorization_id"
        ],
        "predictor_authorization": authorization_manifest,
        "eda_readiness": {
            "status": (
                "current"
                if isinstance(scoped_store.meta.get("analysis_partition"), dict)
                and scoped_store.meta["analysis_partition"].get("status")
                == "current"
                else "analysis_partition_required"
            ),
            "code": (
                None
                if isinstance(scoped_store.meta.get("analysis_partition"), dict)
                and scoped_store.meta["analysis_partition"].get("status")
                == "current"
                else "analysis_partition_required"
            ),
            "predictor_authorization_id": authorization_manifest[
                "predictor_authorization_id"
            ],
            "predictor_count": len(selected_columns),
            "analysis_partition": scoped_store.meta.get("analysis_partition"),
        },
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


def _reproducibility_context_id(payload: Dict[str, Any]) -> str:
    """Fingerprint only the safe, exact metadata returned to the browser."""

    return _stable_contract_id("repro-context", payload)


def _reproducibility_identity(
    identity: Dict[str, Any],
) -> Dict[str, Any]:
    dataset = identity.get("dataset")
    dataset = dataset if isinstance(dataset, dict) else {}
    version = identity.get("version")
    version = version if isinstance(version, dict) else {}
    return {
        "project_id": str(identity.get("project_id") or ""),
        "dataset_name": str(dataset.get("name") or ""),
        "dataset_id": str(identity.get("dataset_id") or ""),
        "dataset_version_id": str(identity.get("dataset_version_id") or ""),
        "dataset_version_label": str(
            identity.get("dataset_version_label") or ""
        ),
        "source_type": str(identity.get("dataset_source_type") or ""),
        "activation_revision": int(identity.get("activation_revision") or 0),
        "governed_population_rows": (
            int(version.get("rowCount"))
            if version.get("rowCount") is not None
            else None
        ),
        "source_columns": (
            int(version.get("columnCount"))
            if version.get("columnCount") is not None
            else None
        ),
    }


def _reproducibility_response(
    *,
    state: str,
    project_id: str,
    identity: Optional[Dict[str, Any]] = None,
    target_contract: Optional[Dict[str, Any]] = None,
    predictor_authorization: Optional[Dict[str, Any]] = None,
    analysis_partition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "ok": True,
        "state": state,
        "project_id": project_id,
        "identity": identity,
        "target_contract": target_contract,
        "predictor_authorization": predictor_authorization,
        "analysis_partition": analysis_partition,
        "authority": {
            "binding": "exact_registered_version",
            "fallback_used": False,
            "browser_state_authoritative": False,
            "row_data_included": False,
            "assignments_included": False,
            "target_aggregates_included": False,
            "final_holdout_access": "protected_metadata_only",
        },
    }
    return {
        **payload,
        "context_id": _reproducibility_context_id(payload),
    }


@router.get("/data/reproducibility-context")
def get_reproducibility_context(
    project_id: str = Query(..., min_length=1),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """Return exact, metadata-only Data Acquisition reproducibility context.

    This read never consults browser state, workflow checkpoints, a first/latest
    dataset version, or a historical Analysis Partition.  It intentionally
    excludes rows, partition assignments, target aggregates, physical paths,
    and final-holdout values.
    """

    resolved_project_id = authorize_modeling_scope(user, project_id, "view")
    persistence = get_persistence_service()
    project_state = persistence.project_dataset_activations.get_project_state(
        resolved_project_id
    )
    selection = project_state.get("active_selection")
    selection = selection if isinstance(selection, dict) else {}
    selection_status = str(selection.get("activation_status") or "").casefold()
    if selection_status == "contradictory":
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "code": "dataset_identity_contradictory",
                "message": (
                    "The durable active dataset relationship is contradictory. "
                    "No reproducibility context was published."
                ),
                "project_id": resolved_project_id,
            },
        )
    if not selection or selection_status != "active":
        return _reproducibility_response(
            state="identity_pending",
            project_id=resolved_project_id,
        )

    identity = durable_active_dataset_identity(
        resolved_project_id,
        user=user,
        require_artifact=True,
    )
    safe_identity = _reproducibility_identity(identity)
    if (
        not safe_identity["dataset_id"]
        or not safe_identity["dataset_version_id"]
        or int(safe_identity["activation_revision"] or 0) <= 0
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "code": "dataset_identity_contradictory",
                "message": (
                    "The durable active dataset identity is incomplete. "
                    "No reproducibility context was published."
                ),
                "project_id": resolved_project_id,
            },
        )

    dataset_id = safe_identity["dataset_id"]
    dataset_version_id = safe_identity["dataset_version_id"]
    authorization_record = persistence.predictor_authorizations.get_current_exact(
        resolved_project_id,
        dataset_id,
        dataset_version_id,
    )
    if authorization_record is None:
        return _reproducibility_response(
            state="target_pending",
            project_id=resolved_project_id,
            identity=safe_identity,
        )
    try:
        manifest = verify_durable_predictor_authorization(
            authorization_record,
            project_id=resolved_project_id,
            dataset_id=dataset_id,
            dataset_version_id=dataset_version_id,
        )
    except PredictorAuthorizationIntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "code": "predictor_authorization_integrity_failed",
                "message": (
                    "The exact predictor authorization failed integrity "
                    "verification. No reproducibility context was published."
                ),
                "project_id": resolved_project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
            },
        ) from exc

    target_contract = {
        "target_contract_id": str(manifest.get("target_contract_id") or ""),
        "target": str(manifest.get("target") or ""),
        "event_value": manifest.get("positive_value"),
        "non_event_value": manifest.get("negative_value"),
    }
    authorized_predictors = [
        str(value)
        for value in manifest.get("authorized_predictors", [])
        if str(value)
    ]
    selected_predictors = [
        str(value)
        for value in manifest.get("selected_predictors", [])
        if str(value)
    ]
    excluded_fields = {
        str(name): str(reason)
        for name, reason in dict(
            manifest.get("excluded_predictors") or {}
        ).items()
    }
    deterministic_source_exclusions = [
        str(value)
        for value in manifest.get("target_source_excluded", [])
        if str(value)
    ]
    deterministic_names = set(deterministic_source_exclusions)
    source_column_count = int(safe_identity.get("source_columns") or 0)
    target_exclusions = (
        [
            {
                "field": target_contract["target"],
                "reason": "Selected modeling outcome; never authorized as a predictor",
            }
        ]
        if target_contract["target"]
        else []
    )
    predictor_authorization = {
        "predictor_authorization_id": str(
            manifest.get("predictor_authorization_id") or ""
        ),
        "status": str(manifest.get("status") or "current"),
        "authorized_predictors": authorized_predictors,
        "selected_predictors": selected_predictors,
        "excluded_fields": excluded_fields,
        "deterministic_source_exclusions": deterministic_source_exclusions,
        "target_source_detection_scope": str(
            manifest.get("target_source_detection_scope") or ""
        ),
        "funnel": {
            "source_column_count": source_column_count,
            "target_exclusions": target_exclusions,
            "candidate_predictor_count": max(
                source_column_count - len(target_exclusions), 0
            ),
            "selected_predictor_count": len(selected_predictors),
            "authorized_predictor_count": len(authorized_predictors),
            "additional_exclusions": {
                name: reason
                for name, reason in excluded_fields.items()
                if name not in deterministic_names
            },
            "model_ready_status": "not_established_in_data_acquisition",
        },
    }

    partition_record = persistence.analysis_partitions.get_current_exact(
        resolved_project_id,
        dataset_id,
        dataset_version_id,
    )
    if partition_record is None:
        return _reproducibility_response(
            state="partition_pending",
            project_id=resolved_project_id,
            identity=safe_identity,
            target_contract=target_contract,
            predictor_authorization=predictor_authorization,
        )

    # Integrity verification is delegated to the one Analysis Partition
    # authority. Its internal membership proof is never copied into this
    # response, and target-authority compatibility must also succeed.
    from ..analysis_partition.service import analysis_partition_service
    from ..analysis_partition.types import AnalysisPartitionError

    try:
        governed_partition = analysis_partition_service.current(
            resolved_project_id,
            dataset_id,
            dataset_version_id,
            target=target_contract["target"],
            target_contract_id=target_contract["target_contract_id"],
            predictor_authorization_id=predictor_authorization[
                "predictor_authorization_id"
            ],
        )
        analysis_partition_service.target_authority_compatibility(
            governed_partition
        )
    except AnalysisPartitionError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=exc.as_detail(),
        ) from exc
    safe_partition = {
        "analysis_partition_id": str(
            governed_partition.get("analysis_partition_id") or ""
        ),
        "revision": int(governed_partition.get("revision") or 0),
        "status": str(governed_partition.get("status") or ""),
        "development_share": governed_partition.get("development_share"),
        "holdout_share": governed_partition.get("holdout_share"),
        "development_rows": int(
            governed_partition.get("development_count") or 0
        ),
        "sealed_holdout_rows": int(
            governed_partition.get("holdout_count") or 0
        ),
        "random_seed": governed_partition.get("random_seed"),
        "stratification_policy": str(
            governed_partition.get("stratification_policy") or ""
        ),
        "stratification_field": str(
            governed_partition.get("stratification_field") or ""
        ),
        "final_holdout_status": str(
            governed_partition.get("final_holdout_status") or ""
        ),
        "holdout_isolation_status": str(
            governed_partition.get("holdout_isolation_status") or ""
        ),
    }
    if (
        safe_partition["status"] != "current"
        or safe_partition["revision"] <= 0
        or safe_partition["final_holdout_status"] != "sealed"
        or safe_partition["holdout_isolation_status"] != "verified"
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "ok": False,
                "code": "analysis_partition_integrity_failed",
                "message": (
                    "The exact Analysis Partition is not a current, verified, "
                    "sealed authority. No reproducibility context was published."
                ),
                "project_id": resolved_project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
            },
        )

    return _reproducibility_response(
        state="current",
        project_id=resolved_project_id,
        identity=safe_identity,
        target_contract=target_contract,
        predictor_authorization=predictor_authorization,
        analysis_partition=safe_partition,
    )


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
def get_sample(
    project_id: str = Query(...),
    max_rows: int = Query(5000, ge=1, le=5000),
    expected_dataset_id: Optional[str] = Query(None),
    expected_dataset_version_id: Optional[str] = Query(None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    """
    Target-free structural sample of the exact active registered dataset.

    Once an Analysis Partition exists, only its integrity-verified positional
    development membership is materialized.  Before the first partition is
    created, full-population predictor rows are allowed for structural review,
    but the target column is still never serialized.  A stale, contradictory,
    or invalid partition fails closed instead of falling back to the full
    population or to browser/checkpoint state.

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
    if bool(str(expected_dataset_id or "").strip()) != bool(
        str(expected_dataset_version_id or "").strip()
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Both expected_dataset_id and expected_dataset_version_id are "
                "required when either exact identity field is supplied."
            ),
        )

    # This always resolves the durable active-selection row and exact immutable
    # artifact.  Optional expectations are comparison-only compatibility for
    # older callers; they can never select or activate a version.
    identity = assert_expected_active_identity(
        project_id,
        expected_dataset_id=expected_dataset_id,
        expected_dataset_version_id=expected_dataset_version_id,
        require_expected=False,
        user=user,
        store=DATASTORE,
    )
    scoped_store = DATASTORE.current()
    dataset_id = str(identity.get("dataset_id") or "").strip()
    dataset_version_id = str(
        identity.get("dataset_version_id") or ""
    ).strip()
    source_checksum = str(
        identity.get("dataset_content_hash")
        or scoped_store.meta.get("dataset_content_hash")
        or ""
    ).strip()
    if not source_checksum:
        raise HTTPException(
            status_code=409,
            detail=(
                "The exact registered dataset checksum is unavailable; a "
                "browser sample cannot be published safely."
            ),
        )

    persistence = get_persistence_service()
    authorization_record = persistence.predictor_authorizations.get_current_exact(
        project_id,
        dataset_id,
        dataset_version_id,
    )
    authorization: Dict[str, Any] = {}
    if authorization_record is not None:
        try:
            authorization = verify_durable_predictor_authorization(
                authorization_record,
                project_id=project_id,
                dataset_id=dataset_id,
                dataset_version_id=dataset_version_id,
            )
        except PredictorAuthorizationIntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "code": "predictor_authorization_integrity_failed",
                    "message": (
                        "The exact predictor authorization failed integrity "
                        "verification. No browser sample was returned."
                    ),
                    "project_id": project_id,
                    "dataset_id": dataset_id,
                    "dataset_version_id": dataset_version_id,
                },
            ) from exc

    authorized_target = str(authorization.get("target") or "").strip()
    target = (
        authorized_target
        or str(scoped_store.target or "").strip()
        or str((identity.get("dataset") or {}).get("target") or "").strip()
        or None
    )
    target_contract_id = str(
        authorization.get("target_contract_id") or ""
    ).strip()
    predictor_authorization_id = str(
        authorization.get("predictor_authorization_id") or ""
    ).strip()
    problem_type: Optional[str] = None
    actor = str(user.get("userId") or "").strip()
    timestamp = now_iso()

    try:
        current_partition = analysis_partition_service.current(
            project_id,
            dataset_id,
            dataset_version_id,
            target=authorized_target or None,
            target_contract_id=target_contract_id or None,
            predictor_authorization_id=predictor_authorization_id or None,
            require_documentation_ready=True,
        )
    except AnalysisPartitionError as exc:
        if exc.code != ANALYSIS_PARTITION_REQUIRED:
            raise scope_http_exception(exc) from exc
        current_partition = None

    if current_partition is not None:
        try:
            development_scope = resolve_development_analysis_scope(
                scoped_store,
                identity,
                expected_analysis_partition_id=current_partition.get(
                    "analysis_partition_id"
                ),
                expected_analysis_partition_revision=current_partition.get(
                    "revision"
                ),
                require_documentation_ready=True,
                actor=actor,
                timestamp=timestamp,
            )
            # Re-resolve after materialization so a concurrent reset cannot
            # publish rows from a superseded partition.
            confirmed_partition = analysis_partition_service.current(
                project_id,
                dataset_id,
                dataset_version_id,
                target=development_scope.target,
                target_contract_id=development_scope.target_authority.get(
                    "target_contract_id"
                ),
                predictor_authorization_id=development_scope.predictor_authorization.get(
                    "predictor_authorization_id"
                ),
                require_documentation_ready=True,
            )
        except AnalysisPartitionError as exc:
            raise scope_http_exception(exc) from exc
        if (
            str(confirmed_partition.get("analysis_partition_id") or "")
            != str(current_partition.get("analysis_partition_id") or "")
            or int(confirmed_partition.get("revision") or 0)
            != int(current_partition.get("revision") or 0)
        ):
            raise HTTPException(
                status_code=409,
                detail={
                    "ok": False,
                    "code": "analysis_partition_contradictory",
                    "message": (
                        "The Analysis Partition changed while the target-free "
                        "sample was materialized. Retry against the current revision."
                    ),
                    "project_id": project_id,
                    "dataset_id": dataset_id,
                    "dataset_version_id": dataset_version_id,
                },
            )
        frame = development_scope.development_features
        target = development_scope.target or target
        problem_type = development_scope.problem_type or None
        target_contract_id = str(
            development_scope.target_authority.get("target_contract_id") or ""
        )
        scope = {
            **development_scope.metadata(),
            "analytical_scope": "development_population_predictors_only",
            "target_values_included": False,
            "holdout_target_accessed": False,
        }
    else:
        raw = scoped_store.raw_df
        if raw is None or raw.empty:
            frame = pd.DataFrame()
        else:
            authorized_predictors = [
                str(value)
                for value in authorization.get("authorized_predictors", [])
                if str(value) in raw.columns and str(value) != target
            ]
            if not authorized_predictors:
                authorized_predictors = [
                    str(column)
                    for column in raw.columns
                    if str(column) != target
                ]
            frame = raw.loc[:, authorized_predictors].copy()
        scope = {
            "scope": "full_governed_population_predictors_only",
            "analysis_scope": "full_governed_population_predictors_only",
            "analytical_scope": "full_governed_population_predictors_only",
            "source_population": "exact_registered_dataset_version",
            "scope_resolution": "durable_current_exact_pre_partition",
            "row_selection_method": "registered_order_structural_sample",
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "population_id": f"full-governed-population:{dataset_version_id}",
            "population_count": int(len(frame)),
            "partition_id": "",
            "partition_revision": 0,
            "holdout_excluded": False,
            "target_values_included": False,
            "holdout_target_accessed": False,
            "source_checksum": source_checksum,
            "actor": actor,
            "timestamp": timestamp,
        }

    # Defense in depth: target metadata may be returned, but a target column
    # or target cell is never included in this endpoint's serialized sample.
    if target and target in frame.columns:
        frame = frame.drop(columns=[target])
    sample_df = frame.head(max_rows)
    headers = [str(column) for column in sample_df.columns if str(column) != target]
    rows = sample_df.loc[:, headers].to_dict(orient="records") if headers else []
    if target and any(target in row for row in rows):  # pragma: no cover - invariant
        raise HTTPException(
            status_code=500,
            detail="Target-free sample serialization invariant failed.",
        )

    return {
        "ok": True,
        "headers": headers,
        "rows": rows,
        "target": target,
        "target_contract_id": target_contract_id or None,
        "problem_type": problem_type,
        "selected_columns": headers,
        "registered_row_count": int(
            len(scoped_store.raw_df)
            if scoped_store.raw_df is not None
            else len(frame)
        ),
        "sample_row_count": int(len(sample_df)),
        "target_values_included": False,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_version_id": dataset_version_id,
        "activation_revision": int(identity.get("activation_revision") or 0),
        "source_checksum": source_checksum,
        "scope": scope,
    }
