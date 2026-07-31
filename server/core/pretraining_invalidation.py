"""Atomic invalidation for state downstream of governed preparation.

Every caller operates on one already-authorized modeling scope. The dataset
store lock is also used by training finalization and Dataset Library
activation, making the dataset metadata and scoped ResultStore transition as
one in-process critical section.
"""
from __future__ import annotations

from typing import Any

from .dataset_store import DATASTORE
from .result_store import RESULTS


DOWNSTREAM_TRAINING_STATE_KEYS = (
    "split_record",
    "split_config",
    "validation_design",
    "target_prevalence",
    "training_execution",
    "model_selection_decision",
    "active_training_job_id",
)


def invalidate_downstream_training_state(
    reason: str,
    *,
    store: Any = None,
    result_store: Any = None,
    split_status: str = "stale",
    bump_revision: bool = True,
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
        }
