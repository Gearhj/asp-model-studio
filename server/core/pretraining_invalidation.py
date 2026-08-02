"""Atomic invalidation for state downstream of governed preparation.

Every caller operates on one already-authorized modeling scope. The dataset
store lock is also used by training finalization and Dataset Library
activation, making the dataset metadata and scoped ResultStore transition as
one in-process critical section.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .dataset_store import DATASTORE
from .result_store import RESULTS
from ..persistence.service import get_persistence_service


DOWNSTREAM_TRAINING_STATE_KEYS = (
    "split_record",
    "split_config",
    "validation_design",
    "target_prevalence",
    "training_execution",
    "training_preflight",
    "model_selection_decision",
    "active_training_job_id",
)


def _exact_holdout_partition_identity(store: Any) -> dict[str, str] | None:
    split_record = (
        store.meta.get("split_record")
        if isinstance(store.meta.get("split_record"), dict)
        else {}
    )
    validation_design = (
        split_record.get("validation_design")
        if isinstance(split_record.get("validation_design"), dict)
        else store.meta.get("validation_design")
        if isinstance(store.meta.get("validation_design"), dict)
        else {}
    )
    identity = {
        "project_id": str(
            split_record.get("project_id")
            or store.meta.get("project_id")
            or ""
        ),
        "dataset_id": str(
            split_record.get("dataset_id")
            or store.meta.get("dataset_id")
            or ""
        ),
        "dataset_version_id": str(
            split_record.get("dataset_version_id")
            or store.meta.get("dataset_version_id")
            or ""
        ),
        "validation_design_id": str(
            validation_design.get("validation_design_id") or ""
        ),
        "validation_design_version_id": str(
            validation_design.get("design_version")
            or validation_design.get("validation_design_version_id")
            or ""
        ),
        "split_id": str(split_record.get("split_id") or ""),
        "final_holdout_partition_id": str(
            split_record.get("final_holdout_partition_id")
            or split_record.get("holdout_population_id")
            or ""
        ),
    }
    return identity if all(identity.values()) else None


def invalidate_downstream_training_state(
    reason: str,
    *,
    store: Any = None,
    result_store: Any = None,
    split_status: str = "stale",
    bump_revision: bool = True,
    governance_repository: Any = None,
    invalidated_by: str = "system:pretraining-invalidation",
) -> dict[str, Any]:
    """Clear split/design/training state and all scoped model results.

    ``reason`` is returned to callers/tests but deliberately is not persisted
    as a second source of workflow truth. ``data_revision`` is monotonic and is
    captured by background training jobs.
    """

    scoped_store = store if store is not None else DATASTORE.current()
    scoped_results = (
        result_store if result_store is not None else RESULTS.current()
    )
    with scoped_store.state_lock:
        durable_invalidated: list[dict[str, Any]] = []
        partition_identity = _exact_holdout_partition_identity(scoped_store)
        if partition_identity is not None:
            repository = (
                governance_repository
                if governance_repository is not None
                else get_persistence_service().holdout_governance
            )
            durable_exposure = (
                repository.invalidate_holdout_exposure_for_partition(
                    **partition_identity,
                    reason=str(reason),
                    invalidated_by=str(invalidated_by),
                )
            )
            if durable_exposure is not None:
                durable_invalidated.append(durable_exposure)
        if bump_revision:
            scoped_store.data_revision += 1
        scoped_store.reset_splits()
        removed = [
            key
            for key in DOWNSTREAM_TRAINING_STATE_KEYS
            if key in scoped_store.meta
        ]
        for key in DOWNSTREAM_TRAINING_STATE_KEYS:
            scoped_store.meta.pop(key, None)
        if split_status:
            scoped_store.meta["split_status"] = str(split_status)
        else:
            scoped_store.meta.pop("split_status", None)
        manifest = scoped_store.meta.get("feature_manifest")
        if isinstance(manifest, dict):
            manifest["split_status"] = str(split_status or "not_created")
        invalidated_holdouts = scoped_results.invalidate_holdout_evaluations(
            reason=str(reason),
            invalidated_at=datetime.now(timezone.utc).isoformat(),
        )
        scoped_results.clear_model_artifacts()
        # Availability is cached per modeling scope and can include a stale
        # completed-run portfolio. Recompute it after the preparation contract
        # changes instead of carrying that cache across revisions.
        scoped_results.set_model_availability({})
        return {
            "reason": str(reason),
            "data_revision": int(scoped_store.data_revision),
            "invalidated_keys": removed,
            "split_status": scoped_store.meta.get("split_status"),
            "invalidated_holdout_exposures": invalidated_holdouts,
            "durably_invalidated_holdout_exposures": durable_invalidated,
        }
