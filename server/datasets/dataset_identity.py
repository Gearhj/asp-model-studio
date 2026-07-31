"""Canonical Dataset Library identity for the active modeling workspace.

`dataset_version_id` in this module always means one exact immutable version
registered in the Dataset Library. Browser access/profile/preview identifiers
must never be passed to these helpers or written into the canonical fields.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException

from ..core.dataset_store import DATASTORE
from ..core.dataset_state_keys import PRETRAINING_STATE_KEYS
from ..security.security_store import audit_event, get_user
from . import dataset_registry


CANONICAL_IDENTITY_KEYS = ("project_id", "dataset_id", "dataset_version_id")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _version_membership(
    dataset_id: str,
    dataset_version_id: str,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    registry = dataset_registry.load_registry()
    datasets = registry.get("datasets") if isinstance(registry, dict) else []
    datasets = datasets if isinstance(datasets, list) else []
    dataset = next(
        (
            item
            for item in datasets
            if isinstance(item, dict) and _clean(item.get("datasetId")) == dataset_id
        ),
        None,
    )
    if not dataset or dataset.get("archived"):
        raise HTTPException(status_code=404, detail="Dataset not found.")
    version = next(
        (
            item
            for item in (dataset.get("versions") or [])
            if isinstance(item, dict)
            and _clean(item.get("versionId")) == dataset_version_id
        ),
        None,
    )
    if version is None:
        belongs_elsewhere = any(
            _clean(candidate.get("versionId")) == dataset_version_id
            for other in datasets
            if isinstance(other, dict)
            and _clean(other.get("datasetId")) != dataset_id
            for candidate in (other.get("versions") or [])
            if isinstance(candidate, dict)
        )
        if belongs_elsewhere:
            raise HTTPException(
                status_code=409,
                detail="The requested Dataset Library version does not belong to the requested dataset.",
            )
        raise HTTPException(status_code=404, detail="Dataset version not found.")
    return dataset, version


def resolve_registered_version(
    dataset_id: Any,
    dataset_version_id: Any,
    *,
    user: Optional[Dict[str, Any]] = None,
    require_artifact: bool = True,
) -> Dict[str, Any]:
    """Resolve an exact registered pair without any first/latest fallback."""
    resolved_dataset_id = _clean(dataset_id)
    resolved_version_id = _clean(dataset_version_id)
    if not resolved_dataset_id or not resolved_version_id:
        raise HTTPException(
            status_code=409,
            detail="An exact registered dataset_id and dataset_version_id are required.",
        )
    dataset, version = _version_membership(resolved_dataset_id, resolved_version_id)
    if not dataset_registry.user_can_access(dataset, user=user):
        audit_event(
            "access.denied",
            "dataset_version",
            resolved_version_id,
            "denied",
            user_id=(user or {}).get("userId"),
            reason="Dataset ACL denied for canonical version resolution",
            metadata={"datasetId": resolved_dataset_id},
        )
        raise HTTPException(status_code=403, detail="You do not have access to this dataset version.")

    artifact_path: Optional[Path] = None
    relative_path = _clean(version.get("fullDataPath"))
    if require_artifact:
        if not relative_path:
            raise HTTPException(
                status_code=409,
                detail="The registered dataset version does not contain a full immutable artifact.",
            )
        artifact_path = (dataset_registry.ARTIFACT_ROOT / relative_path).resolve()
        root = dataset_registry.ARTIFACT_ROOT.resolve()
        if root not in artifact_path.parents or not artifact_path.exists():
            raise HTTPException(
                status_code=409,
                detail="The exact registered dataset version artifact is unavailable.",
            )

    return {
        "dataset": dataset,
        "version": version,
        "dataset_id": resolved_dataset_id,
        "dataset_version_id": resolved_version_id,
        "artifact_path": artifact_path,
        "dataset_version_label": version.get("label")
        or version.get("versionLabel")
        or resolved_version_id,
        "dataset_content_hash": version.get("hash")
        or version.get("contentHash")
        or version.get("sha256"),
        "dataset_schema_hash": version.get("schemaHash"),
        "dataset_source_type": dataset.get("sourceType"),
    }


def require_exact_project_link(
    project_id: Any,
    dataset_id: Any,
    dataset_version_id: Any,
) -> Dict[str, Any]:
    """Require the project link to name this exact dataset version."""
    resolved_project_id = _clean(project_id)
    resolved_dataset_id = _clean(dataset_id)
    resolved_version_id = _clean(dataset_version_id)
    links_payload = dataset_registry.load_links()
    links = links_payload.get("links") if isinstance(links_payload, dict) else []
    links = links if isinstance(links, list) else []
    exact = next(
        (
            item
            for item in links
            if isinstance(item, dict)
            and _clean(item.get("projectId")) == resolved_project_id
            and _clean(item.get("datasetId")) == resolved_dataset_id
            and _clean(item.get("versionId")) == resolved_version_id
        ),
        None,
    )
    if exact is not None:
        return exact
    linked_other_version = any(
        isinstance(item, dict)
        and _clean(item.get("projectId")) == resolved_project_id
        and _clean(item.get("datasetId")) == resolved_dataset_id
        for item in links
    )
    detail = (
        "The project is linked to a different version of this dataset."
        if linked_other_version
        else "The project is not linked to this exact Dataset Library version."
    )
    raise HTTPException(status_code=409, detail=detail)


def resolve_project_dataset_identity(
    project_id: Any,
    dataset_id: Any,
    dataset_version_id: Any,
    *,
    user: Optional[Dict[str, Any]] = None,
    require_artifact: bool = True,
) -> Dict[str, Any]:
    resolved = resolve_registered_version(
        dataset_id,
        dataset_version_id,
        user=user,
        require_artifact=require_artifact,
    )
    link = require_exact_project_link(
        project_id,
        resolved["dataset_id"],
        resolved["dataset_version_id"],
    )
    return {
        **resolved,
        "project_id": _clean(project_id),
        "project_link": link,
    }


def stamp_active_dataset_identity(
    identity: Dict[str, Any],
    *,
    store: Any = DATASTORE,
) -> Dict[str, str]:
    """Persist one already-validated canonical identity in active state."""
    canonical = {
        "project_id": _clean(identity.get("project_id")),
        "dataset_id": _clean(identity.get("dataset_id")),
        "dataset_version_id": _clean(identity.get("dataset_version_id")),
    }
    if not all(canonical.values()):
        raise HTTPException(status_code=409, detail="Canonical dataset identity is incomplete.")
    store.meta.update(canonical)
    # Transitional response compatibility only. No request may write this alias.
    store.meta["dataset_version"] = canonical["dataset_version_id"]
    store.meta["dataset_identity_status"] = "current"
    store.meta.pop("dataset_identity_error", None)
    for field in (
        "dataset_version_label",
        "dataset_content_hash",
        "dataset_schema_hash",
        "dataset_source_type",
    ):
        value = identity.get(field)
        if value not in (None, ""):
            store.meta[field] = value
    return canonical


def invalidate_dataset_identity(
    reason: str,
    *,
    store: Any = DATASTORE,
    clear_frames: bool = False,
) -> None:
    """Mark unresolved legacy state stale without substituting another version."""
    store.meta["dataset_identity_status"] = "invalid"
    store.meta["dataset_identity_error"] = str(reason)
    store.meta["split_status"] = "stale"
    for key in PRETRAINING_STATE_KEYS:
        if key == "split_status":
            continue
        store.meta.pop(key, None)
    if clear_frames:
        store.raw_df = None
        store.processed_df = None
        store.reset_splits()


def active_dataset_identity(
    project_id: Any,
    *,
    user: Optional[Dict[str, Any]] = None,
    validate: bool = True,
    store: Any = DATASTORE,
) -> Dict[str, Any]:
    """Read canonical fields only; legacy aliases never become authority."""
    expected_project_id = _clean(project_id)
    if _clean(store.meta.get("dataset_identity_status")).casefold() == "invalid":
        detail = _clean(store.meta.get("dataset_identity_error")) or (
            "The active dataset identity is stale or invalid. Select and "
            "activate the exact registered Dataset Library version."
        )
        raise HTTPException(status_code=409, detail=detail)
    canonical = {
        "project_id": _clean(store.meta.get("project_id")),
        "dataset_id": _clean(store.meta.get("dataset_id")),
        "dataset_version_id": _clean(store.meta.get("dataset_version_id")),
    }
    if not all(canonical.values()):
        legacy = _clean(store.meta.get("dataset_version") or store.meta.get("version_id"))
        detail = (
            f"Active workflow state contains unresolved legacy dataset version '{legacy}'. "
            "Select and activate the exact registered Dataset Library version."
            if legacy
            else "No exact registered Dataset Library version is active for this project."
        )
        invalidate_dataset_identity(detail, store=store)
        raise HTTPException(status_code=409, detail=detail)
    if canonical["project_id"] != expected_project_id:
        detail = "The active dataset identity belongs to a different project."
        invalidate_dataset_identity(detail, store=store)
        raise HTTPException(status_code=409, detail=detail)
    if not validate:
        return canonical
    resolved = resolve_project_dataset_identity(
        expected_project_id,
        canonical["dataset_id"],
        canonical["dataset_version_id"],
        user=user,
    )
    return {**resolved, **canonical}


def assert_expected_active_identity(
    project_id: Any,
    *,
    expected_dataset_id: Any = None,
    expected_dataset_version_id: Any = None,
    legacy_dataset_version: Any = None,
    require_expected: bool = False,
    user: Optional[Dict[str, Any]] = None,
    store: Any = DATASTORE,
) -> Dict[str, Any]:
    """Compare client expectations to authority without mutating identity."""
    supplied_dataset_id = _clean(expected_dataset_id)
    supplied_version_id = _clean(expected_dataset_version_id)
    supplied_legacy_version = _clean(legacy_dataset_version)
    if bool(supplied_dataset_id) != bool(supplied_version_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "Both dataset_id and dataset_version_id are required to "
                "identify the exact registered Dataset Library version."
            ),
        )
    if require_expected and not (
        supplied_dataset_id and supplied_version_id
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "The exact expected dataset_id and dataset_version_id are "
                "required. Reload the project before continuing."
            ),
        )
    if (
        supplied_legacy_version
        and supplied_version_id
        and supplied_legacy_version != supplied_version_id
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Conflicting Dataset Library version identifiers were "
                "supplied. Reload the project before continuing."
            ),
        )
    active = active_dataset_identity(project_id, user=user, store=store)
    mismatch = (
        (supplied_dataset_id and supplied_dataset_id != active["dataset_id"])
        or (
            supplied_version_id
            and supplied_version_id != active["dataset_version_id"]
        )
        or (
            supplied_legacy_version
            and supplied_legacy_version != active["dataset_version_id"]
        )
    )
    if mismatch:
        raise HTTPException(
            status_code=409,
            detail=(
                "The requested dataset identity does not match the exact active "
                "Dataset Library version. Reload the project before continuing."
            ),
        )
    return active


def coalesce_identity_expectations(
    *,
    expected_dataset_id: Any = None,
    expected_dataset_version_id: Any = None,
    dataset_id: Any = None,
    dataset_version_id: Any = None,
    legacy_dataset_version: Any = None,
) -> tuple[str, str, str]:
    """Normalize compatibility fields without allowing contradictions."""
    expected_id = _clean(expected_dataset_id)
    canonical_id = _clean(dataset_id)
    expected_version = _clean(expected_dataset_version_id)
    canonical_version = _clean(dataset_version_id)
    legacy_version = _clean(legacy_dataset_version)
    if expected_id and canonical_id and expected_id != canonical_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Conflicting dataset_id values were supplied. Reload the "
                "project before continuing."
            ),
        )
    version_values = {
        value
        for value in (expected_version, canonical_version, legacy_version)
        if value
    }
    if len(version_values) > 1:
        raise HTTPException(
            status_code=409,
            detail=(
                "Conflicting Dataset Library version identifiers were "
                "supplied. Reload the project before continuing."
            ),
        )
    return (
        expected_id or canonical_id,
        expected_version or canonical_version,
        legacy_version,
    )


def validate_checkpoint_identity(
    store: Any,
    *,
    owner_user_id: str,
    project_id: str,
) -> tuple[bool, str, Optional[Dict[str, Any]]]:
    """Validate a restored scope without ambient request/user context."""
    user = get_user(owner_user_id)
    if not user:
        return False, "Checkpoint owner no longer resolves to an ATLAS user.", None
    try:
        identity = active_dataset_identity(
            project_id,
            user=user,
            validate=True,
            store=store,
        )
    except HTTPException as exc:
        return False, str(exc.detail), None
    return True, "", identity
