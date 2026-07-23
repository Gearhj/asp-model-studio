from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from . import dataset_store as dataset_store_module
from . import result_store as result_store_module
from .dataset_store import UNSCOPED_PROJECT, get_scoped_dataset_store
from .result_store import get_scoped_result_store


LOGGER = logging.getLogger("atlas.checkpoint")

CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / ".runtime" / "workflow_checkpoint.json"
_CHECKPOINT_LOCK = threading.Lock()

# =============================================================================
# STAGE 6 FIX (ATLAS_MODELING_STATE_ISOLATION_PLAN.md) -- READ THIS FIRST
# =============================================================================
#
# ROOT CAUSE of the restart scope collapse (Stages 1-5's KNOWN LIMITATION):
# the pre-Stage-6 checkpoint was a SINGLE FLAT SNAPSHOT -- {"dataset": {...},
# "results": {...}} -- of whichever ONE (user_id, project_id) scope happened
# to be AMBIENT at the moment save_checkpoint() was called (via DATASTORE/
# RESULTS's ambient proxies, resolved through _scope_key()). Every one of the
# ~15 call sites across the router layer overwrote the ENTIRE file with only
# its own caller's scope, discarding whatever any other user/project had
# previously saved -- "last writer wins," globally, across every user and
# project in the whole deployment. At startup, load_checkpoint() ran from
# @app.on_event("startup"), before any HTTP request had ever been handled,
# so active_user()/active_project_id() were always unset there -- meaning
# the restored data was written back into DATASTORE/RESULTS's shared
# ("anonymous", UNSCOPED_PROJECT) sentinel scope regardless of which real
# user had actually saved it. Ownership information was destroyed, not
# merely relabeled -- see the historical CheckpointRestoreTests docstrings
# (now rewritten; the original bug-reproduction assertions are preserved
# under new names -- see "Tests that changed classification in Stage 6"
# below) for the exact characterization that proved this.
#
# FIX: save_checkpoint() and load_checkpoint() no longer touch the AMBIENT
# DATASTORE/RESULTS proxies at all. Instead:
#
#   1. save_checkpoint() iterates EVERY (user_id, project_id) entry
#      currently resident in dataset_store_module._DATASTORES and
#      result_store_module._RESULT_STORES -- both are already, since
#      Stages 2B/3, plain in-memory dicts holding every scope touched
#      during this process's lifetime -- and serializes EACH as its own
#      explicit, structured record: {"owner_user_id": ..., "project_id":
#      ..., "dataset": {...}} (or "results"). This is a full multi-scope
#      snapshot on every save, not a single-scope one -- so it does not
#      matter which of the ~15 router call sites triggered a given save;
#      every save captures the complete, current state of every scope.
#      None of those ~15 call sites needed to change AT ALL: they still
#      just call save_checkpoint() with no arguments.
#
#   2. load_checkpoint() reads the file's own explicit owner_user_id/
#      project_id fields and calls get_scoped_dataset_store((user_id,
#      project_id)) / get_scoped_result_store((user_id, project_id)) with
#      that EXPLICIT tuple -- the same "bypass ambient resolution
#      entirely" contract those functions already exposed for tests.
#      Startup restoration therefore needs, and uses, no authenticated
#      HTTP request and no ambient ContextVar: every restored scope's
#      identity comes exclusively from the checkpoint file itself.
#
# SCHEMA: see CHECKPOINT_SCHEMA_VERSION below. A checkpoint with no
# "schema_version" key at all is the pre-Stage-6 LEGACY format -- see
# _load_legacy_checkpoint's docstring for its own, deliberately narrow
# handling (never mapped to a real user/project).
#
# TRAINING_JOBS ARCHITECTURE DECISION: TRAINING_JOBS is NOT included in the
# checkpoint, and this is a deliberate decision, not an oversight --
# 1. A job's in-memory bookkeeping (per-model transition history, the
#    threading.Event used for cancellation, ThreadPoolExecutor state) has
#    no meaning after a real process restart: the background thread that
#    was running it is gone, so a "queued"/"preparing"/"running" job can
#    never actually be resumed. Persisting such a job and reporting it as
#    still "running" after restart would be an outright lie -- nothing is
#    computing it. Not persisting it, so it simply does not exist after
#    restart, satisfies "stale running jobs must not be falsely resumed"
#    by construction, more strongly than any reconciliation-after-the-fact
#    policy could.
# 2. A completed job's only durable VALUE -- the fitted models' ranked
#    metrics and (JSON-safe) metadata -- is already written into RESULTS
#    by TrainingJobService._finalize() (job["_result_store"].
#    set_last_summary(...)/.set_model_artifacts(...)), which Stage 6 DOES
#    checkpoint. Also persisting the TRAINING_JOBS record itself would
#    duplicate that same information in two places with no reconciliation
#    path between them if they ever disagreed -- precisely what requirement
#    #12 ("do not duplicate data that already has a reliable durable
#    persistence path") warns against. RESULTS is that durable path here.
# 3. Per requirement #10 ("prefer durable persisted artifacts... over
#    treating the checkpoint as a permanent database"): TRAINING_JOBS is
#    fundamentally live orchestration state, not committed data -- it
#    belongs in-memory only, exactly like it already was pre-Stage-6.
#
# Consequence: after a real restart, TRAINING_JOBS._jobs/_project_job_ids/
# _cancel_events all start empty (a fresh TrainingJobService(), exactly as
# module import already produces) -- job history does not survive restart,
# by design. GET /model/train/jobs/{job_id} for a pre-restart job_id 404s
# post-restart (indistinguishable from "never existed," matching Stage 4's
# own not-found handling for a job that belongs to someone else). The
# job's real output remains reachable through /train/last, which IS
# checkpointed. See TrainingJobCheckpointPolicyTests for the tests proving
# this.
#
# COLLABORATOR POLICY (unchanged from Stages 2B/3/4, Option A): restoring
# scope-by-scope from explicit (user_id, project_id) records cannot itself
# grant a collaborator visibility into another user's restored draft state
# -- there is no code path here that resolves "the project's" DATASTORE/
# RESULTS; every restored record lands in its own private (user_id,
# project_id) scope, exactly as it was saved. A collaborator's own restored
# scope (if they had ever saved one) is separate and independent, per the
# same Option A policy Stages 2B/3/4 already established for live requests.
#
# =============================================================================

# Version 2 (this stage) is the multi-scope format described above.
# Pre-Stage-6 checkpoints (implicitly "version 1", though that version
# number was never written to disk) have no "schema_version" key at all --
# see _load_legacy_checkpoint.
CHECKPOINT_SCHEMA_VERSION = 2

# Sentinel (user, project) scope legacy (pre-Stage-6) checkpoints are loaded
# into -- see _load_legacy_checkpoint's docstring for the full rationale.
# This is the SAME sentinel non-HTTP callers already resolve to when no
# request ever went through authorize_modeling_scope (server/core/
# modeling_scope.py) -- e.g. tests/predictive_modeling_repair_test.py --
# not a new, separate bucket.
LEGACY_SCOPE: Tuple[str, str] = ("anonymous", UNSCOPED_PROJECT)


def _encode(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"__atlas_type__": "dataframe", "payload": json.loads(value.to_json(orient="split", date_format="iso"))}
    if isinstance(value, pd.Series):
        return {"__atlas_type__": "series", "payload": json.loads(value.to_json(orient="split", date_format="iso"))}
    try:
        json.dumps(value)
        return value
    except TypeError:
        return None


def _decode(value: Any) -> Any:
    if not isinstance(value, dict) or "__atlas_type__" not in value:
        return value
    payload = value.get("payload") or {}
    if value.get("__atlas_type__") == "dataframe":
        return pd.read_json(json.dumps(payload), orient="split")
    if value.get("__atlas_type__") == "series":
        return pd.read_json(json.dumps(payload), orient="split", typ="series")
    return None


def _encode_dataset(store: Any) -> Dict[str, Any]:
    return {
        "raw_df": _encode(store.raw_df),
        "processed_df": _encode(store.processed_df),
        "target": store.target,
        "X_train": _encode(store.X_train),
        "X_test": _encode(store.X_test),
        "y_train": _encode(store.y_train),
        "y_test": _encode(store.y_test),
        "meta": _encode(store.meta) or {},
    }


def _encode_results(store: Any) -> Dict[str, Any]:
    # Raw fitted model objects (store.model_artifacts' values, store.
    # final_model) are not JSON-serializable and have NEVER survived a
    # checkpoint round-trip, before or after this stage: _encode() returns
    # None for the whole dict as soon as json.dumps() hits a non-
    # serializable value anywhere inside it, and final_model itself was
    # never even included in the saved payload. This is a pre-existing,
    # deliberately unchanged limitation -- see the delivery report's
    # "state that intentionally does not survive restart."
    return {
        "last_training_summary": _encode(store.last_training_summary),
        "training_timestamp": store.training_timestamp,
        "model_availability": _encode(store.model_availability) or {},
        "model_artifacts": _encode(store.model_artifacts) or {},
        "final_model_metadata": _encode(store.final_model_metadata),
        "scoring_reference": _encode(store.scoring_reference),
    }


def _apply_dataset(store: Any, fields: Dict[str, Any]) -> None:
    store.raw_df = _decode(fields.get("raw_df"))
    store.processed_df = _decode(fields.get("processed_df"))
    store.target = fields.get("target")
    store.X_train = _decode(fields.get("X_train"))
    store.X_test = _decode(fields.get("X_test"))
    store.y_train = _decode(fields.get("y_train"))
    store.y_test = _decode(fields.get("y_test"))
    store.meta = fields.get("meta") or {}


def _apply_results(store: Any, fields: Dict[str, Any]) -> None:
    store.last_training_summary = _decode(fields.get("last_training_summary"))
    store.training_timestamp = fields.get("training_timestamp")
    store.model_availability = fields.get("model_availability") or {}
    store.model_artifacts = fields.get("model_artifacts") or {}
    store.model_artifact_metadata = {}
    store.final_model = None
    store.final_model_metadata = _decode(fields.get("final_model_metadata"))
    store.scoring_reference = _decode(fields.get("scoring_reference"))


def save_checkpoint() -> bool:
    """Snapshot EVERY (user_id, project_id) scope currently resident in
    _DATASTORES/_RESULT_STORES into one checkpoint file.

    Callers (~15 call sites across data acquisition, preprocessing,
    features, splitting, training, and evaluation/scoring routers) do not
    pass a scope and do not need to: each already runs inside its own
    authorized request, but this function serializes ALL known scopes on
    every call, not just the caller's own -- see the module docstring's
    "STAGE 6 FIX" section for why that is what makes concurrent/
    interleaved activity across many users and projects all restore
    correctly.
    """
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        LOGGER.warning("Could not create checkpoint directory: %r", exc)
        return False

    datastore_scopes: List[Dict[str, Any]] = []
    for (user_id, project_id), store in dataset_store_module._DATASTORES.items():
        datastore_scopes.append({
            "owner_user_id": user_id,
            "project_id": project_id,
            "dataset": _encode_dataset(store),
        })

    results_scopes: List[Dict[str, Any]] = []
    for (user_id, project_id), store in result_store_module._RESULT_STORES.items():
        results_scopes.append({
            "owner_user_id": user_id,
            "project_id": project_id,
            "results": _encode_results(store),
        })

    payload: Dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "datastore_scopes": datastore_scopes,
        "results_scopes": results_scopes,
    }

    # Atomic write: write the FULL payload to a uniquely-named temp file in
    # the same directory (so the later replace() is a same-filesystem
    # rename, not a cross-filesystem copy), then atomically replace the
    # live checkpoint. Path.replace() is an atomic rename on both POSIX and
    # Windows -- there is no window where CHECKPOINT_PATH exists but
    # contains partially-written bytes. If anything fails before the
    # replace, the previous good checkpoint (if any) is left completely
    # untouched, and the temp file is cleaned up.
    temp_path = CHECKPOINT_PATH.with_name(f"{CHECKPOINT_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        with _CHECKPOINT_LOCK:
            temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            temp_path.replace(CHECKPOINT_PATH)
        return True
    except Exception as exc:
        LOGGER.warning("Failed to save workflow checkpoint: %r", exc)
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def _parse_scope_entry(entry: Any, payload_key: str) -> Optional[Tuple[Tuple[str, str], Dict[str, Any]]]:
    """Validate one scope record from the checkpoint file. Returns None
    (skip this entry, log a warning) rather than raising, so one malformed
    record among many valid ones does not abort the whole restoration --
    distinct from a genuinely corrupt/unsupported-version FILE, which
    load_checkpoint() rejects outright before any restoration is attempted.
    """
    if not isinstance(entry, dict):
        LOGGER.warning("Skipping malformed checkpoint scope entry (not an object): %r", entry)
        return None
    user_id = entry.get("owner_user_id")
    project_id = entry.get("project_id")
    fields = entry.get(payload_key)
    if not isinstance(user_id, str) or not user_id.strip():
        LOGGER.warning("Skipping checkpoint scope entry with missing/invalid owner_user_id: %r", entry)
        return None
    if not isinstance(project_id, str) or not project_id.strip():
        LOGGER.warning("Skipping checkpoint scope entry with missing/invalid project_id: %r", entry)
        return None
    if not isinstance(fields, dict):
        LOGGER.warning("Skipping checkpoint scope entry with missing/invalid %r payload: %r", payload_key, entry)
        return None
    return (user_id, project_id), fields


def _load_legacy_checkpoint(payload: Dict[str, Any]) -> bool:
    """Handle a pre-Stage-6 checkpoint: a single flat {"dataset": ...,
    "results": ...} snapshot with no schema_version and no concept of
    scope at all (Stages 1-5's single-ambient-scope format).

    DECISION (requirement #24): load legacy state ONLY into the sentinel
    LEGACY_SCOPE = ("anonymous", UNSCOPED_PROJECT) -- never into any real
    user or project. UNSCOPED_PROJECT can never be a real, persisted
    project_id (authorize_modeling_scope 404s on it, exactly like any
    other never-created project), and "anonymous" is never a real
    authenticated userId -- so this data is structurally UNREACHABLE
    through any authenticated HTTP endpoint. This is the same property the
    OLD pre-Stage-6 behavior already had, just now happening deliberately
    instead of by accident (every KNOWN LIMITATION test through Stage 4
    proved restart always landed exactly here). Chosen over discarding the
    legacy file outright so existing local development data is not
    destroyed -- it stays inspectable via direct store access
    (get_scoped_dataset_store(LEGACY_SCOPE)) for anyone who explicitly
    wants it, without ever being exposed through a real authenticated
    project. See LegacyCheckpointCompatibilityTests for the tests proving
    this stays true.
    """
    dataset = payload.get("dataset")
    results = payload.get("results")
    if not isinstance(dataset, dict) and not isinstance(results, dict):
        LOGGER.warning(
            "Workflow checkpoint %s has no schema_version and no recognizable legacy fields; skipping restoration.",
            CHECKPOINT_PATH,
        )
        return False
    LOGGER.warning(
        "Workflow checkpoint %s is a pre-Stage-6 legacy, unscoped snapshot. Loading it into the "
        "non-HTTP-reachable %r scope only -- it will NOT appear in any authenticated user's real "
        "project. Save a new checkpoint from a real project to migrate.",
        CHECKPOINT_PATH, LEGACY_SCOPE,
    )
    if isinstance(dataset, dict):
        _apply_dataset(get_scoped_dataset_store(LEGACY_SCOPE), dataset)
    if isinstance(results, dict):
        _apply_results(get_scoped_result_store(LEGACY_SCOPE), results)
    return True


def load_checkpoint() -> bool:
    """Restore every scope from the checkpoint file at startup.

    Deliberately reads NOTHING from ambient context: called from
    @app.on_event("startup") in server/main.py, before any HTTP request has
    ever been handled, so active_user()/active_project_id() are always
    unset here regardless. Every restored scope's identity comes
    exclusively from the checkpoint file's own explicit owner_user_id/
    project_id fields, passed as an EXPLICIT tuple to get_scoped_dataset_
    store()/get_scoped_result_store() -- never through their ambient/
    ContextVar-resolved default path.

    Fails safe on any structural problem: a missing file, invalid JSON, a
    non-object payload, an unsupported schema_version, or a payload missing
    the expected scope-list structure all return False WITHOUT modifying
    any in-memory state and WITHOUT touching (let alone overwriting) the
    checkpoint file itself -- corrupt files remain on disk exactly as
    found, for inspection. Individual malformed scope RECORDS within an
    otherwise-valid file are skipped with a warning rather than aborting
    the whole restoration -- see _parse_scope_entry.
    """
    if not CHECKPOINT_PATH.exists():
        return False
    try:
        raw = CHECKPOINT_PATH.read_text(encoding="utf-8")
    except Exception as exc:
        LOGGER.warning("Could not read workflow checkpoint %s: %r", CHECKPOINT_PATH, exc)
        return False
    try:
        payload = json.loads(raw)
    except Exception as exc:
        LOGGER.warning("Workflow checkpoint %s is corrupt (invalid JSON); skipping restoration: %r", CHECKPOINT_PATH, exc)
        return False
    if not isinstance(payload, dict):
        LOGGER.warning("Workflow checkpoint %s is malformed (not a JSON object); skipping restoration.", CHECKPOINT_PATH)
        return False

    schema_version = payload.get("schema_version")
    if schema_version is None:
        return _load_legacy_checkpoint(payload)
    if schema_version != CHECKPOINT_SCHEMA_VERSION:
        LOGGER.warning(
            "Workflow checkpoint %s has unsupported schema_version %r (expected %r); skipping restoration.",
            CHECKPOINT_PATH, schema_version, CHECKPOINT_SCHEMA_VERSION,
        )
        return False

    datastore_scopes = payload.get("datastore_scopes")
    results_scopes = payload.get("results_scopes")
    if not isinstance(datastore_scopes, list) or not isinstance(results_scopes, list):
        LOGGER.warning("Workflow checkpoint %s is malformed (missing scope lists); skipping restoration.", CHECKPOINT_PATH)
        return False

    restored_datasets = 0
    for entry in datastore_scopes:
        parsed = _parse_scope_entry(entry, "dataset")
        if parsed is None:
            continue
        scope_key, fields = parsed
        _apply_dataset(get_scoped_dataset_store(scope_key), fields)
        restored_datasets += 1

    restored_results = 0
    for entry in results_scopes:
        parsed = _parse_scope_entry(entry, "results")
        if parsed is None:
            continue
        scope_key, fields = parsed
        _apply_results(get_scoped_result_store(scope_key), fields)
        restored_results += 1

    LOGGER.info(
        "Restored workflow checkpoint %s: %d DATASTORE scope(s), %d RESULTS scope(s).",
        CHECKPOINT_PATH, restored_datasets, restored_results,
    )
    return True
