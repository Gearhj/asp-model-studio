"""Canonical Dataset Library identity for the active modeling workspace.

`dataset_version_id` in this module always means one exact immutable version
registered in the Dataset Library. Browser access/profile/preview identifiers
must never be passed to these helpers or written into the canonical fields.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import HTTPException

from ..core.dataset_store import DATASTORE
from ..core.dataset_state_keys import PRETRAINING_STATE_KEYS
from ..core.modeling_scope import authorize_modeling_scope
from ..core.pretraining_invalidation import invalidate_downstream_training_state
from ..core.result_store import RESULTS
from ..persistence.repositories.project_dataset_activation_repository import (
    ProjectDatasetActivationConflictError,
)
from ..security.security_store import active_user, audit_event, get_user
from . import dataset_registry


CANONICAL_IDENTITY_KEYS = ("project_id", "dataset_id", "dataset_version_id")
_IDENTITY_STABILITY_RETRIES = 8


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _authenticated_identity_user(
    user: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve only an authenticated request/explicit user, never a dev fallback."""
    resolved = user or active_user()
    if not isinstance(resolved, dict) or not _clean(resolved.get("userId")):
        raise HTTPException(
            status_code=401,
            detail="An authenticated user is required to resolve dataset identity.",
        )
    return resolved


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
    authenticated_user = _authenticated_identity_user(user)
    resolved_dataset_id = _clean(dataset_id)
    resolved_version_id = _clean(dataset_version_id)
    if not resolved_dataset_id or not resolved_version_id:
        raise HTTPException(
            status_code=409,
            detail="An exact registered dataset_id and dataset_version_id are required.",
        )
    dataset, version = _version_membership(resolved_dataset_id, resolved_version_id)
    if not dataset_registry.user_can_access(dataset, user=authenticated_user):
        audit_event(
            "access.denied",
            "dataset_version",
            resolved_version_id,
            "denied",
            user_id=authenticated_user.get("userId"),
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
    """Require the durable project-to-dataset authorization relationship.

    Project authorization and active modeling selection are deliberately
    separate contracts.  The link therefore names a dataset, never a version;
    the exact version is verified against the durable active-selection row by
    :func:`active_dataset_identity`.
    """
    resolved_project_id = _clean(project_id)
    resolved_dataset_id = _clean(dataset_id)
    if not resolved_project_id or not resolved_dataset_id or not _clean(dataset_version_id):
        raise HTTPException(
            status_code=409,
            detail="An exact project, dataset, and dataset version are required.",
        )
    from ..persistence.service import get_persistence_service

    link = get_persistence_service().project_dataset_activations.get_link(
        resolved_project_id,
        resolved_dataset_id,
    )
    if not link or _clean(link.get("link_status")).casefold() != "active":
        raise HTTPException(
            status_code=409,
            detail="The project does not have an active authorized link to this Dataset Library asset.",
        )
    return link


def durable_active_dataset_identity(
    project_id: Any,
    *,
    user: Optional[Dict[str, Any]] = None,
    require_artifact: bool = True,
) -> Dict[str, Any]:
    """Resolve one revision-stable exact durable active selection.

    Readers intentionally do not acquire the process-local activation lock.
    Some modeling services already own the runtime store lock when they check
    identity, while activation owns the project lock until its cache has been
    published.  Taking the project lock here would invert those locks.  The
    repository snapshot and post-validation signature check instead provide
    an optimistic, exact read of one committed activation revision.
    """

    resolved_project_id = _clean(project_id)
    if not resolved_project_id:
        raise HTTPException(status_code=400, detail="A project_id is required.")
    return _durable_active_dataset_identity_optimistic(
        resolved_project_id,
        user=user,
        require_artifact=require_artifact,
    )


def _selection_signature(selection: Any) -> tuple[str, str, str, int]:
    selection = selection if isinstance(selection, dict) else {}
    try:
        revision = int(selection.get("activation_revision") or 0)
    except (TypeError, ValueError):
        revision = 0
    return (
        _clean(selection.get("activation_status")).casefold(),
        _clean(selection.get("dataset_id")),
        _clean(selection.get("dataset_version_id")),
        revision,
    )


def _authority_signature(state: Dict[str, Any] | None) -> tuple[str, str, str, int, str]:
    """Fingerprint only fields that grant exact active-version authority."""

    state = state or {}
    selection = (
        state.get("active_selection")
        if isinstance(state.get("active_selection"), dict)
        else {}
    )
    status, dataset_id, dataset_version_id, revision = _selection_signature(selection)
    links = state.get("links") if isinstance(state.get("links"), list) else []
    selected_link_status = next(
        (
            _clean(link.get("link_status")).casefold()
            for link in links
            if isinstance(link, dict)
            and _clean(link.get("dataset_id")) == dataset_id
        ),
        "",
    )
    return status, dataset_id, dataset_version_id, revision, selected_link_status


def _same_durable_identity(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    return (
        _clean(first.get("project_id")),
        _clean(first.get("dataset_id")),
        _clean(first.get("dataset_version_id")),
        int(first.get("activation_revision") or 0),
        _selection_signature(first.get("active_selection")),
    ) == (
        _clean(second.get("project_id")),
        _clean(second.get("dataset_id")),
        _clean(second.get("dataset_version_id")),
        int(second.get("activation_revision") or 0),
        _selection_signature(second.get("active_selection")),
    )


def _durable_active_dataset_identity_optimistic(
    project_id: Any,
    *,
    user: Optional[Dict[str, Any]] = None,
    require_artifact: bool = True,
) -> Dict[str, Any]:
    """Resolve the exact durable active selection without consulting a cache.

    Workflow state, browser state, and the checkpoint are intentionally absent
    from this function.  They may mirror identity, but they cannot grant either
    project-dataset authorization or active-version authority.
    """
    resolved_project_id = _clean(project_id)
    if not resolved_project_id:
        raise HTTPException(status_code=400, detail="A project_id is required.")
    authenticated_user = _authenticated_identity_user(user)
    authorize_modeling_scope(authenticated_user, resolved_project_id, "view")
    from ..persistence.service import get_persistence_service

    service = get_persistence_service()
    repository = service.project_dataset_activations
    for _attempt in range(_IDENTITY_STABILITY_RETRIES):
        state_before = repository.get_project_state(resolved_project_id)
        selection = state_before.get("active_selection")
        selection = selection if isinstance(selection, dict) else {}
        selection_status, dataset_id, dataset_version_id, revision = (
            _selection_signature(selection)
        )
        if selection_status == "contradictory":
            raise HTTPException(
                status_code=409,
                detail=(
                    "The durable active dataset relationship is contradictory and "
                    "requires explicit controlled repair."
                ),
            )
        if not selection or selection_status != "active":
            raise HTTPException(
                status_code=409,
                detail="No exact registered Dataset Library version is active for this project.",
            )

        links = state_before.get("links")
        links = links if isinstance(links, list) else []
        link = next(
            (
                item
                for item in links
                if isinstance(item, dict)
                and _clean(item.get("dataset_id")) == dataset_id
                and _clean(item.get("link_status")).casefold() == "active"
            ),
            None,
        )
        structural_error: HTTPException | None = None
        resolved: Dict[str, Any] | None = None
        if not dataset_id or not dataset_version_id or revision < 1:
            structural_error = HTTPException(
                status_code=409,
                detail="The durable active dataset selection is incomplete or contradictory.",
            )
        elif link is None:
            structural_error = HTTPException(
                status_code=409,
                detail=(
                    "The project does not have an active authorized link to this "
                    "Dataset Library asset."
                ),
            )
        else:
            try:
                resolved = resolve_registered_version(
                    dataset_id,
                    dataset_version_id,
                    user=authenticated_user,
                    require_artifact=require_artifact,
                )
            except HTTPException as exc:
                if exc.status_code == 403:
                    # A caller-specific ACL denial does not make the project's
                    # durable relationship structurally contradictory.
                    raise
                structural_error = exc

        state_after = repository.get_project_state(resolved_project_id)
        if _authority_signature(state_before) != _authority_signature(state_after):
            continue
        if structural_error is None and resolved is not None and link is not None:
            return {
                **resolved,
                "project_id": resolved_project_id,
                "project_link": link,
                "active_selection": selection,
                "activation_revision": revision,
            }

        # The same exact committed revision remained structurally invalid
        # across validation.  Record the diagnostic only if that revision and
        # triple are still current; a concurrent repair causes a retry instead
        # of poisoning the newer activation.
        actor_user_id = _clean(authenticated_user.get("userId"))
        if actor_user_id and structural_error is not None:
            try:
                repository.record_contradiction_if_current(
                    project_id=resolved_project_id,
                    actor_user_id=actor_user_id,
                    reason=str(structural_error.detail),
                    expected_dataset_id=dataset_id,
                    expected_dataset_version_id=dataset_version_id,
                    expected_activation_revision=revision,
                    metadata={
                        "detectedBy": "durable_active_dataset_identity",
                        "datasetId": dataset_id,
                        "datasetVersionId": dataset_version_id,
                    },
                )
            except ProjectDatasetActivationConflictError:
                continue
            except Exception:
                # The original identity failure remains authoritative even if
                # the best-effort diagnostic write itself cannot complete.
                pass
        raise HTTPException(
            status_code=409,
            detail=(
                "The durable active dataset relationship is contradictory and "
                "requires explicit controlled repair."
            ),
        ) from structural_error

    raise HTTPException(
        status_code=409,
        detail=(
            "The active Dataset Library version changed while its identity was "
            "being resolved. Retry the request."
        ),
    )


def resolve_project_dataset_identity(
    project_id: Any,
    dataset_id: Any,
    dataset_version_id: Any,
    *,
    user: Optional[Dict[str, Any]] = None,
    require_artifact: bool = True,
) -> Dict[str, Any]:
    authenticated_user = _authenticated_identity_user(user)
    resolved_project_id = authorize_modeling_scope(
        authenticated_user,
        _clean(project_id),
        "view",
    )
    resolved = resolve_registered_version(
        dataset_id,
        dataset_version_id,
        user=authenticated_user,
        require_artifact=require_artifact,
    )
    link = require_exact_project_link(
        resolved_project_id,
        resolved["dataset_id"],
        resolved["dataset_version_id"],
    )
    return {
        **resolved,
        "project_id": resolved_project_id,
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


def _paired_runtime_results(store: Any, result_store: Any = None) -> Any:
    if result_store is not None:
        return result_store
    try:
        current_store = DATASTORE.current()
    except Exception:
        return None
    if store is DATASTORE or store is current_store:
        try:
            return RESULTS.current()
        except Exception:
            return None
    return None


def active_dataset_identity(
    project_id: Any,
    *,
    user: Optional[Dict[str, Any]] = None,
    validate: bool = True,
    store: Any = DATASTORE,
    hydrate: bool = True,
    result_store: Any = None,
) -> Dict[str, Any]:
    """Return and publish one revision-stable durable dataset identity.

    Durable resolution never takes the activation lock.  Cache publication is
    optimistic: validate one exact revision, prepare its immutable frame,
    recheck while owning the runtime lock, publish, then recheck once more.
    If activation commits anywhere in that window, retry against the newer
    revision.  This remains safe both for ordinary callers and callers that
    already own ``store.state_lock``.
    """

    expected_project_id = _clean(project_id)
    if not expected_project_id:
        raise HTTPException(status_code=400, detail="A project_id is required.")
    for _attempt in range(_IDENTITY_STABILITY_RETRIES):
        durable = durable_active_dataset_identity(
            expected_project_id,
            user=user,
            require_artifact=validate or hydrate,
        )
        frame: pd.DataFrame | None = None
        with store.state_lock:
            needs_preparation = _runtime_cache_needs_hydration(
                durable,
                store=store,
                hydrate=hydrate,
            )
        if needs_preparation:
            artifact_path = durable.get("artifact_path")
            if artifact_path is None:
                raise HTTPException(
                    status_code=409,
                    detail="The exact registered dataset version artifact is unavailable.",
                )
            try:
                frame = pd.read_csv(artifact_path)
            except Exception as exc:
                raise HTTPException(
                    status_code=409,
                    detail="The exact registered dataset version could not be rehydrated.",
                ) from exc

        with store.state_lock:
            confirmed = durable_active_dataset_identity(
                expected_project_id,
                user=user,
                require_artifact=validate or hydrate,
            )
            if not _same_durable_identity(durable, confirmed):
                continue
            needs_hydration = _runtime_cache_needs_hydration(
                confirmed,
                store=store,
                hydrate=hydrate,
            )
            if needs_hydration and frame is None:
                # The cache changed after the first snapshot.  Prepare the
                # exact still-current artifact outside this lock and retry.
                continue
            if needs_hydration:
                _publish_active_dataset_identity(
                    confirmed,
                    frame=frame,
                    store=store,
                    result_store=result_store,
                )
            elif not _runtime_cache_matches(confirmed, store=store):
                raise HTTPException(
                    status_code=409,
                    detail="The runtime dataset cache contradicts the durable active selection.",
                )

            post_publication = durable_active_dataset_identity(
                expected_project_id,
                user=user,
                require_artifact=validate or hydrate,
            )
            if _same_durable_identity(confirmed, post_publication):
                return post_publication

    raise HTTPException(
        status_code=409,
        detail=(
            "The active Dataset Library version changed while the runtime cache "
            "was being synchronized. Retry the request."
        ),
    )


def _runtime_cache_matches(
    durable: Dict[str, Any],
    *,
    store: Any,
) -> bool:
    canonical = {
        "project_id": durable["project_id"],
        "dataset_id": durable["dataset_id"],
        "dataset_version_id": durable["dataset_version_id"],
    }
    cached = {
        "project_id": _clean(store.meta.get("project_id")),
        "dataset_id": _clean(store.meta.get("dataset_id")),
        "dataset_version_id": _clean(store.meta.get("dataset_version_id")),
    }
    try:
        cached_revision = int(store.meta.get("activation_revision") or 0)
    except (TypeError, ValueError):
        cached_revision = 0
    durable_revision = int(durable.get("activation_revision") or 0)
    return cached == canonical and cached_revision == durable_revision


def _runtime_cache_needs_hydration(
    durable: Dict[str, Any],
    *,
    store: Any,
    hydrate: bool,
) -> bool:
    cache_matches = _runtime_cache_matches(durable, store=store)
    active_frame = None
    try:
        active_frame = store.get_active_df()
    except Exception:
        active_frame = None
    return (
        hydrate
        and (
            not cache_matches
            or _clean(store.meta.get("dataset_identity_status")).casefold() != "current"
            or active_frame is None
            or active_frame.empty
        )
    )


def _publish_active_dataset_identity(
    durable: Dict[str, Any],
    *,
    frame: pd.DataFrame,
    store: Any,
    result_store: Any = None,
) -> None:
    """Publish one already rechecked durable revision while store is locked."""

    cache_matches = _runtime_cache_matches(durable, store=store)
    paired_results = _paired_runtime_results(store, result_store)
    if not cache_matches and paired_results is not None:
        invalidate_downstream_training_state(
            "The durable dataset activation revision changed; prior "
            "preparation, split, candidate, and model state requires revalidation.",
            store=store,
            result_store=paired_results,
            split_status="not_created",
            bump_revision=False,
        )
    store.set_raw(frame)
    registered_target = _clean(durable.get("dataset", {}).get("target"))
    target = registered_target if registered_target in frame.columns else None
    store.set_target(target)
    store.meta["selected_columns"] = [
        str(column) for column in frame.columns if str(column) != target
    ]
    canonical = stamp_active_dataset_identity(durable, store=store)
    store.meta["activation_revision"] = int(
        durable.get("activation_revision") or 0
    )
    store.meta["source"] = {
        "kind": "dataset_library",
        "dataset_id": canonical["dataset_id"],
        "dataset_version_id": canonical["dataset_version_id"],
        "datasetId": canonical["dataset_id"],
        "versionId": canonical["dataset_version_id"],
        "filename": durable.get("version", {}).get("originalFilename")
        or durable.get("dataset", {}).get("name"),
        "rows": int(frame.shape[0]),
        "columns": int(frame.shape[1]),
    }


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
    """Validate a restored cache against durable authority.

    The checkpoint may accelerate recovery only when its exact canonical
    triple matches both the durable authorized link and active-selection row.
    It can never create either relationship.
    """
    user = get_user(owner_user_id)
    if not user:
        return False, "Checkpoint owner no longer resolves to an ATLAS user.", None
    checkpoint_identity = {
        "project_id": _clean(store.meta.get("project_id")),
        "dataset_id": _clean(store.meta.get("dataset_id")),
        "dataset_version_id": _clean(store.meta.get("dataset_version_id")),
    }
    if not all(checkpoint_identity.values()):
        return False, "Checkpoint does not contain one exact canonical dataset identity.", None
    if checkpoint_identity["project_id"] != _clean(project_id):
        return False, "Checkpoint dataset identity belongs to another project.", None
    try:
        checkpoint_revision = int(store.meta.get("activation_revision") or 0)
    except (TypeError, ValueError):
        checkpoint_revision = 0
    if checkpoint_revision < 1:
        return False, "Checkpoint does not contain a durable activation revision.", None
    try:
        identity = durable_active_dataset_identity(
            project_id,
            user=user,
            require_artifact=True,
        )
    except HTTPException as exc:
        return False, str(exc.detail), None
    durable_identity = {
        key: _clean(identity.get(key)) for key in CANONICAL_IDENTITY_KEYS
    }
    if checkpoint_identity != durable_identity:
        return (
            False,
            "Checkpoint identity does not match the exact durable active dataset selection.",
            None,
        )
    if checkpoint_revision != int(identity.get("activation_revision") or 0):
        return (
            False,
            "Checkpoint activation revision does not match the durable active selection.",
            None,
        )
    return True, "", identity
