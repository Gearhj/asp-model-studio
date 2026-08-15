from __future__ import annotations

import hashlib
import json
from io import StringIO
import logging
import os
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from . import dataset_store as dataset_store_module
from . import result_store as result_store_module
from .dataset_store import UNSCOPED_PROJECT, get_scoped_dataset_store
from .dataset_state_keys import PRETRAINING_STATE_KEYS
from .result_store import get_scoped_result_store


LOGGER = logging.getLogger("atlas.checkpoint")

# ATLAS_CHECKPOINT_PATH (Stage 6.1): lets test suites and scripts point at an
# isolated checkpoint file. The checkpoint is a full-snapshot, last-writer-wins
# file -- a second process (e.g. a test run) writing the REAL path clobbers the
# live backend's scopes, so anything that is not the one production backend
# should set this to its own path.
_DEFAULT_CHECKPOINT_PATH = (
    Path(__file__).resolve().parents[2] / ".runtime" / "workflow_checkpoint.json"
).resolve()
CHECKPOINT_PATH = Path(
    os.getenv(
        "ATLAS_CHECKPOINT_PATH",
        str(_DEFAULT_CHECKPOINT_PATH),
    )
)
_CHECKPOINT_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# STAGE 6.1: save-frequency + size-control configuration (all env-overridable
# so tests can tighten them without monkeypatching internals).
# ---------------------------------------------------------------------------
# Quiet period after the LAST schedule_checkpoint_save() call before the
# background writer performs the physical write -- rapid mutation bursts
# coalesce into one write.
CHECKPOINT_DEBOUNCE_SECONDS = float(os.getenv("ATLAS_CHECKPOINT_DEBOUNCE_SECONDS", "2.0"))
# Upper bound on how long a dirty checkpoint may remain unwritten while
# mutations keep arriving -- guarantees a continuously-busy process still
# persists at least this often.
CHECKPOINT_MAX_PENDING_SECONDS = float(os.getenv("ATLAS_CHECKPOINT_MAX_PENDING_SECONDS", "30.0"))
# Size thresholds: log-only escalation. Valid state is NEVER discarded
# because a threshold was crossed -- growth is controlled by scope lifecycle
# (GC), not by truncation.
CHECKPOINT_SIZE_WARNING_BYTES = int(os.getenv("ATLAS_CHECKPOINT_SIZE_WARNING_BYTES", str(25 * 1024 * 1024)))
CHECKPOINT_SIZE_CRITICAL_BYTES = int(os.getenv("ATLAS_CHECKPOINT_SIZE_CRITICAL_BYTES", str(100 * 1024 * 1024)))

# Instrumentation: physical-write counter and the last write's report.
# Read by tests (coalescing assertions) and by operators via logs.
CHECKPOINT_WRITE_COUNT = 0
LAST_SAVE_REPORT: Dict[str, Any] = {}

# Dirty/debounce state shared between schedulers and the single writer thread.
_DIRTY_LOCK = threading.Lock()
_DIRTY_SINCE: Optional[float] = None
_LAST_MARK: Optional[float] = None
_WAKE = threading.Event()
_WRITER_SHUTDOWN = threading.Event()
_WRITER_THREAD: Optional[threading.Thread] = None

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

# =============================================================================
# STAGE 6.1: CHECKPOINT LIFECYCLE CONTRACT (architecture decision record)
# =============================================================================
#
# CONFIRMED DEFECT this stage repairs: the Stage 6 multi-scope snapshot had no
# lifecycle at all. Scopes were created lazily on ANY access (including reads),
# lived for the whole process lifetime, were reloaded en masse at startup, and
# were ALL re-serialized on every save. Deleting a project or user removed the
# database rows but never the in-memory scope or its checkpoint record, so the
# file grew without bound (observed: 322 MB / 37 scopes, all of them belonging
# to deleted temporary audit projects) and every mutating request paid a full
# multi-hundred-MB serialization (observed: 90+ second request latency).
#
# THE CONTRACT: the checkpoint is a RECOVERY SNAPSHOT OF ACTIVE, NON-DURABLE
# MODELING DRAFT STATE -- the in-progress dataset/preprocessing/split draft
# (DATASTORE) and the lightweight training/evaluation result metadata
# (RESULTS) for scopes whose user and project still exist. It is NOT a
# permanent database, an archive of deleted projects, an audit-history store,
# or a substitute for the Dataset Library / durable persistence tables.
#
# WHAT IS SERIALIZED PER SCOPE (unchanged from Stage 6, deliberately): the
# DATASTORE draft frames (raw/processed/splits/target/meta) and the RESULTS
# JSON-safe metadata. raw_df/processed_df/splits stay in the checkpoint
# because for browser-driven drafts they are the ONLY server-side copy -- the
# durable Dataset Library reference is optional -- and post-restart flows
# (e.g. score_development_split) consume the restored splits directly.
# Removing them would break required restart behavior; the growth problem was
# scope ACCUMULATION, not any single field, and is fixed by lifecycle below.
# Raw fitted model objects and TRAINING_JOBS remain excluded (see the Stage 6
# sections above).
#
# LIFECYCLE (Stage 6.1):
#   1. GC ON DELETE: project deletion (persistence_router.delete_project)
#      now calls discard_modeling_scopes(project_id=...) -- every resident
#      scope for that project, across ALL owners (including collaborators'
#      private scopes), is dropped from _DATASTORES/_RESULT_STORES -- and
#      then flush_checkpoint(), so the file reflects the deletion
#      immediately. This is also the sanctioned cleanup path for temporary
#      E2E scopes: delete the project through the normal API instead of
#      editing checkpoint JSON.
#   2. SAVE-TIME FILTERING: save_checkpoint() excludes (a) scopes whose
#      project no longer exists in the persistence database, (b) scopes
#      whose owner no longer exists in the security store (there is no
#      user-deletion endpoint in the product today, so this covers users
#      removed administratively), and (c) EMPTY scopes -- ones whose
#      DATASTORE holds no frames, no target, and no meta, and whose RESULTS
#      holds nothing; lazy get_scoped_*_store() calls on read paths create
#      such husks constantly and they carry no recoverable state. A scope
#      with ANY draft state (even just meta configuration) is NOT empty and
#      is kept. Existence checks FAIL OPEN: if the persistence or security
#      store cannot be queried, no scope is dropped for that reason.
#   3. LOAD-TIME FILTERING: load_checkpoint() skips records whose project or
#      owner no longer exists (same fail-open rule), so a deleted project
#      can never be resurrected from a stale checkpoint file.
#   4. UNSCOPED EXEMPTION: scopes whose project half is UNSCOPED_PROJECT
#      (non-HTTP service/test callers, and LEGACY_SCOPE restores) cannot be
#      validated against the projects table by construction and are exempt
#      from existence filtering -- but not from the empty-scope rule.
#
# SAVE FREQUENCY (Stage 6.1): save_checkpoint() remains a SYNCHRONOUS
# immediate write with its Stage 6 semantics (tests and the two preprocessing
# routers that surface persistence failure as HTTP 500 depend on that).
# Routine mutating endpoints now call schedule_checkpoint_save() instead:
# it marks the checkpoint dirty and returns immediately; a single daemon
# writer thread coalesces marks and performs ONE physical write once the
# burst has been quiet for CHECKPOINT_DEBOUNCE_SECONDS (bounded by
# CHECKPOINT_MAX_PENDING_SECONDS under continuous load). flush_checkpoint()
# forces a synchronous write (clearing any pending mark) and is called from
# the FastAPI shutdown hook and after project deletion. All physical writes
# -- scheduled, direct, or flushed -- serialize under _CHECKPOINT_LOCK and
# keep the Stage 6 atomic temp-file + os.replace() pattern, so concurrent
# writers cannot interleave partial files.
#
# SIZE CONTROL (Stage 6.1): every physical write logs scope counts, byte
# count, and duration (LAST_SAVE_REPORT mirrors it for tests/inspection);
# crossing CHECKPOINT_SIZE_WARNING_BYTES logs a warning and
# CHECKPOINT_SIZE_CRITICAL_BYTES logs an error. Thresholds NEVER discard
# state. server/core/checkpoint_inspect.py reports the largest scopes and
# fields of any checkpoint file for diagnosis.
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


def _encode(value: Any, _seen: Optional[Set[int]] = None) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"__atlas_type__": "dataframe", "payload": json.loads(value.to_json(orient="split", date_format="iso"))}
    if isinstance(value, pd.Series):
        return {"__atlas_type__": "series", "payload": json.loads(value.to_json(orient="split", date_format="iso"))}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return {"__atlas_type__": "datetime", "payload": value.isoformat()}
    if isinstance(value, Path):
        return {"__atlas_type__": "path", "payload": str(value)}
    if _seen is None:
        _seen = set()
    if isinstance(value, (dict, list, tuple, set)):
        identity = id(value)
        if identity in _seen:
            return None
        _seen.add(identity)
        try:
            if isinstance(value, dict):
                return {
                    str(key): _encode(item, _seen)
                    for key, item in value.items()
                }
            if isinstance(value, set):
                return [_encode(item, _seen) for item in sorted(value, key=repr)]
            return [_encode(item, _seen) for item in value]
        finally:
            _seen.discard(identity)
    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _encode(item_method(), _seen)
        except (TypeError, ValueError):
            pass
    try:
        json.dumps(value)
        return value
    except TypeError:
        return None


def _decode(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "__atlas_type__" not in value:
        return {key: _decode(item) for key, item in value.items()}
    payload = value.get("payload")
    if value.get("__atlas_type__") == "dataframe":
        return pd.read_json(StringIO(json.dumps(payload or {})), orient="split")
    if value.get("__atlas_type__") == "series":
        return pd.read_json(
            StringIO(json.dumps(payload or {})), orient="split", typ="series"
        )
    if value.get("__atlas_type__") == "datetime":
        return payload
    if value.get("__atlas_type__") == "path":
        return payload
    return None


def _encode_dataset(store: Any) -> Dict[str, Any]:
    return {
        "data_revision": int(getattr(store, "data_revision", 0)),
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
        "evaluation_packages": _encode(store.evaluation_packages) or {},
        "holdout_evaluations": _encode(store.holdout_evaluations) or {},
        "selection_integrity_records": _encode(store.selection_integrity_records) or {},
    }


def _apply_dataset(store: Any, fields: Dict[str, Any]) -> None:
    try:
        store.data_revision = max(0, int(fields.get("data_revision") or 0))
    except (TypeError, ValueError):
        store.data_revision = 0
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
    store.evaluation_packages = _decode(fields.get("evaluation_packages")) or {}
    store.holdout_evaluations = _decode(fields.get("holdout_evaluations")) or {}
    store.selection_integrity_records = (
        _decode(fields.get("selection_integrity_records")) or {}
    )


def _record_has_exact_identity(
    record: Any,
    identity: Dict[str, Any],
) -> bool:
    if not isinstance(record, dict):
        return False
    if any(
        str(record.get(key) or "") != str(identity.get(key) or "")
        for key in ("project_id", "dataset_id", "dataset_version_id")
    ):
        return False
    legacy_version = str(record.get("dataset_version") or "").strip()
    return (
        not legacy_version
        or legacy_version == str(identity["dataset_version_id"])
    )


def _checkpoint_pretraining_lineage_errors(
    store: Any,
    identity: Dict[str, Any],
) -> List[str]:
    """Reject retained derived state that cannot prove its exact source."""
    errors: List[str] = []
    identity_bound_keys = (
        "outlier_application",
        "missing_application",
        "missing_validation",
        "preprocessing_policy",
        "feature_manifest",
        "feature_preview",
        "validation_design",
        "split_record",
        "training_execution",
        "training_model_portfolio",
        "training_preflight",
        "model_selection_decision",
    )
    for key in identity_bound_keys:
        record = store.meta.get(key)
        if record is not None and not _record_has_exact_identity(
            record,
            identity,
        ):
            errors.append(f"{key} lacks the exact canonical dataset identity")

    meta = store.meta
    partition = (
        meta.get("analysis_partition")
        if isinstance(meta.get("analysis_partition"), dict)
        else {}
    )
    authorization = (
        meta.get("predictor_authorization")
        if isinstance(meta.get("predictor_authorization"), dict)
        else {}
    )
    special_review = (
        meta.get("special_value_review")
        if isinstance(meta.get("special_value_review"), dict)
        else {}
    )
    expected_preprocessing_lineage = {
        "project_id": identity.get("project_id"),
        "dataset_id": identity.get("dataset_id"),
        "dataset_version_id": identity.get("dataset_version_id"),
        "target": store.target,
        "target_contract_id": (
            partition.get("target_contract_id")
            or meta.get("target_contract_id")
        ),
        "predictor_authorization_id": (
            authorization.get("predictor_authorization_id")
            or meta.get("predictor_authorization_id")
        ),
        "analysis_partition_id": (
            partition.get("analysis_partition_id")
            or meta.get("analysis_partition_id")
        ),
        "analysis_partition_revision": (
            partition.get("revision")
            or meta.get("analysis_partition_revision")
        ),
        "source_checksum": (
            partition.get("source_checksum")
            or meta.get("source_checksum")
        ),
        "special_value_review_id": (
            special_review.get("special_value_review_id")
            or meta.get("special_value_review_id")
        ),
        "special_value_review_revision": (
            special_review.get("revision")
            or meta.get("special_value_review_revision")
            or 0
        ),
        "special_value_detection_fingerprint": (
            special_review.get("detection_fingerprint")
            or meta.get("special_value_detection_fingerprint")
        ),
    }
    preprocessing_records = {
        key: meta.get(key)
        for key in (
            "outlier_application",
            "missing_application",
            "missing_validation",
            "preprocessing_policy",
        )
        if meta.get(key) is not None
    }
    for key, record in preprocessing_records.items():
        if not isinstance(record, dict) or int(
            record.get("preprocessing_contract_version") or 0
        ) != 2:
            errors.append(
                f"{key} is an unverifiable legacy preprocessing artifact"
            )
            continue
        for field, expected in expected_preprocessing_lineage.items():
            if expected in (None, ""):
                continue
            actual = record.get(field)
            if field.endswith("revision"):
                matches = int(actual or 0) == int(expected or 0)
            else:
                matches = str(actual or "") == str(expected or "")
            if not matches:
                errors.append(
                    f"{key} {field} does not match current preprocessing authority"
                )
        if key == "preprocessing_policy":
            nested = record.get("lineage")
            if not isinstance(nested, dict):
                errors.append("preprocessing_policy lacks nested exact lineage")
            else:
                for field, expected in expected_preprocessing_lineage.items():
                    if expected in (None, ""):
                        continue
                    actual = nested.get(field)
                    if field.endswith("revision"):
                        matches = int(actual or 0) == int(expected or 0)
                    else:
                        matches = str(actual or "") == str(expected or "")
                    if not matches:
                        errors.append(
                            "preprocessing_policy nested lineage does not match "
                            f"current {field} authority"
                        )

    for key in ("outlier_policy", "missing_policy"):
        policy = meta.get(key)
        if policy is not None and (
            not isinstance(policy, dict)
            or int(policy.get("preprocessing_contract_version") or 0) != 2
        ):
            errors.append(f"{key} is not a preprocessing-v2 policy")
    legacy_preparation_present = any(
        meta.get(key) is not None
        for key in (
            "outlier_application",
            "missing_application",
            "missing_validation",
            "missing_config",
            "processed_stage",
        )
    )
    if legacy_preparation_present and not isinstance(
        meta.get("preprocessing_policy"), dict
    ):
        errors.append(
            "preparation state lacks the canonical preprocessing-v2 policy"
        )

    stage = str(store.meta.get("processed_stage") or "")
    stage_record = {
        "outliers": "outlier_application",
        "missing_values": "missing_application",
        "feature_engineering": "feature_manifest",
    }.get(stage)
    if store.processed_df is not None:
        if stage in {"outliers", "missing_values"}:
            errors.append(
                "preprocessing v2 forbids a globally materialized outlier or missing-value frame"
            )
        if not stage_record:
            errors.append("processed_df has no governed processed_stage")
        elif not _record_has_exact_identity(
            store.meta.get(stage_record),
            identity,
        ):
            errors.append(
                f"processed_df cannot be proven by {stage_record}"
            )
        combined = meta.get("preprocessing_policy")
        if stage == "feature_engineering" and (
            not isinstance(combined, dict)
            or int(combined.get("preprocessing_contract_version") or 0) != 2
            or combined.get("status") != "approved"
            or not bool(combined.get("executable"))
        ):
            errors.append(
                "feature-engineering processed state depends on an unverified preprocessing policy"
            )

    has_splits = any(
        value is not None
        for value in (
            store.X_train,
            store.X_test,
            store.y_train,
            store.y_test,
        )
    )
    if has_splits and not _record_has_exact_identity(
        store.meta.get("split_record"),
        identity,
    ):
        errors.append("restored split frames lack an exact split_record")
    return errors


def _quarantine_checkpoint_pretraining_state(
    store: Any,
    errors: List[str],
) -> None:
    """Keep the exact source/target but discard unverifiable derivatives."""
    history = store.meta.get("preprocessing_audit_history")
    history = history if isinstance(history, list) else []
    quarantined_at = datetime.now(timezone.utc).isoformat()
    reason = "; ".join(errors)
    for key in PRETRAINING_STATE_KEYS:
        record = store.meta.get(key)
        if record is None:
            continue
        history.append(
            {
                "state_key": key,
                "status": "stale_quarantined_on_checkpoint_restore",
                "reason": reason,
                "quarantined_at": quarantined_at,
                "record": record,
            }
        )
    if store.processed_df is not None:
        processed = store.processed_df
        try:
            hashed = pd.util.hash_pandas_object(processed, index=True).values
            processed_hash = hashlib.sha256(hashed.tobytes()).hexdigest()
        except Exception:
            processed_hash = "unavailable"
        history.append(
            {
                "state_key": "processed_df",
                "status": "stale_quarantined_on_checkpoint_restore",
                "reason": reason,
                "quarantined_at": quarantined_at,
                "record": {
                    "processed_stage": store.meta.get("processed_stage"),
                    "row_count": int(len(processed)),
                    "columns": [str(value) for value in processed.columns],
                    "processed_frame_hash": processed_hash,
                    "frame_retained_as_current": False,
                },
            }
        )
    store.processed_df = None
    store.X_train = None
    store.X_test = None
    store.y_train = None
    store.y_test = None
    for key in PRETRAINING_STATE_KEYS:
        # Target and exact source identity remain authoritative; every derived
        # contract must be rebuilt from the immutable registered artifact.
        store.meta.pop(key, None)
    if history:
        store.meta["preprocessing_audit_history"] = history
    store.meta["pretraining_state_status"] = "stale"
    store.meta["pretraining_state_reason"] = (
        "Checkpoint-derived state was quarantined because its exact Dataset "
        "Library lineage could not be proven: " + "; ".join(errors)
    )
    store.data_revision += 1


def _is_dataset_store_empty(store: Any) -> bool:
    """True when a DatasetStore holds no recoverable draft state at all.
    Deliberately conservative: ANY meta content (draft configuration for a
    not-yet-uploaded project, manifests, split records) keeps the scope."""
    return (
        store.raw_df is None
        and store.processed_df is None
        and store.target is None
        and store.X_train is None
        and store.X_test is None
        and store.y_train is None
        and store.y_test is None
        and not store.meta
    )


def _is_result_store_empty(store: Any) -> bool:
    """True when a ResultStore holds nothing that survives a checkpoint
    round-trip anyway (final_model / model_artifact_metadata are never
    serialized -- see _encode_results)."""
    return (
        store.last_training_summary is None
        and store.training_timestamp is None
        and not store.model_availability
        and not store.model_artifacts
        and store.final_model_metadata is None
        and store.scoring_reference is None
        and not store.evaluation_packages
        and not store.holdout_evaluations
        and not store.selection_integrity_records
    )


def _live_identity_sets() -> Tuple[Optional[Set[str]], Optional[Set[str]]]:
    """Return (live_project_ids, live_user_ids) for existence filtering.

    Either element is None when its backing store cannot be queried --
    callers must then FAIL OPEN (keep the scope) rather than discard state
    on the strength of an unavailable database.
    """
    live_projects: Optional[Set[str]] = None
    live_users: Optional[Set[str]] = None
    try:
        from ..persistence.service import get_persistence_service

        live_projects = {
            str(record.get("project_id"))
            for record in get_persistence_service().projects.list()
            if record.get("project_id")
        }
    except Exception as exc:
        LOGGER.debug("Checkpoint existence filter: projects unavailable (%r); failing open.", exc)
    try:
        from ..security.security_store import list_users

        live_users = {str(user.get("userId")) for user in list_users() if user.get("userId")}
    except Exception as exc:
        LOGGER.debug("Checkpoint existence filter: users unavailable (%r); failing open.", exc)
    return live_projects, live_users


def _scope_is_live(
    user_id: str,
    project_id: str,
    live_projects: Optional[Set[str]],
    live_users: Optional[Set[str]],
) -> bool:
    """Existence filter shared by save and load. UNSCOPED_PROJECT scopes
    (non-HTTP service/test callers, LEGACY_SCOPE) cannot be validated
    against the projects table by construction and are always kept."""
    if project_id == UNSCOPED_PROJECT:
        return True
    if live_projects is not None and project_id not in live_projects:
        return False
    if live_users is not None and user_id not in live_users and user_id != "anonymous":
        return False
    return True


def save_checkpoint() -> bool:
    """Snapshot every LIVE, NON-EMPTY (user_id, project_id) scope currently
    resident in _DATASTORES/_RESULT_STORES into one checkpoint file.

    Synchronous immediate write -- unchanged Stage 6 contract for callers
    that must know persistence succeeded (outlier/missing routers surface a
    failure as HTTP 500; tests assert on the returned bool). Routine
    mutating endpoints should call schedule_checkpoint_save() instead so
    bursts coalesce into one physical write. Stage 6.1 additionally applies
    the lifecycle filters (deleted project/user, empty scope) documented in
    the STAGE 6.1 contract above, and records size/duration instrumentation
    in LAST_SAVE_REPORT.
    """
    global CHECKPOINT_WRITE_COUNT, LAST_SAVE_REPORT
    if (
        os.getenv("ATLAS_ENV", "").strip().casefold() in {"test", "testing"}
        or os.getenv("ATLAS_TEST_MODE", "").strip().casefold()
        in {"1", "true", "yes"}
        or bool(os.getenv("PYTEST_CURRENT_TEST"))
    ):
        configured = os.getenv("ATLAS_CHECKPOINT_PATH")
        try:
            configured_path = (
                Path(configured).expanduser().resolve() if configured else None
            )
            active_path = CHECKPOINT_PATH.expanduser().resolve()
        except OSError as exc:
            LOGGER.error("Unsafe checkpoint test path: %s", type(exc).__name__)
            return False
        if (
            configured_path is None
            or active_path != configured_path
            or active_path == _DEFAULT_CHECKPOINT_PATH
        ):
            LOGGER.error(
                "Refusing checkpoint test write because the cached path is not "
                "the explicit isolated ATLAS_CHECKPOINT_PATH."
            )
            return False
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        LOGGER.warning("Could not create checkpoint directory: %r", exc)
        return False

    started = time.perf_counter()
    live_projects, live_users = _live_identity_sets()
    skipped_orphaned = 0
    skipped_empty = 0

    datastore_scopes: List[Dict[str, Any]] = []
    results_scopes: List[Dict[str, Any]] = []
    paired_result_scopes: Set[Tuple[str, str]] = set()
    for (user_id, project_id), store in list(dataset_store_module._DATASTORES.items()):
        if not _scope_is_live(user_id, project_id, live_projects, live_users):
            skipped_orphaned += 1
            continue
        scope_key = (user_id, project_id)
        paired_results = result_store_module._RESULT_STORES.get(scope_key)
        # Training finalization, dataset activation, and preparation
        # invalidation all use this same per-scope lock. Encode the DatasetStore
        # and its paired ResultStore in one critical section so a checkpoint
        # can never combine pre-mutation dataset metadata with post-mutation
        # model results (or vice versa).
        with store.state_lock:
            if _is_dataset_store_empty(store):
                skipped_empty += 1
                continue
            datastore_scopes.append({
                "owner_user_id": user_id,
                "project_id": project_id,
                "dataset": _encode_dataset(store),
            })
            if paired_results is not None:
                paired_result_scopes.add(scope_key)
                if _is_result_store_empty(paired_results):
                    skipped_empty += 1
                else:
                    results_scopes.append({
                        "owner_user_id": user_id,
                        "project_id": project_id,
                        "results": _encode_results(paired_results),
                    })

    # Preserve the existing non-HTTP/legacy save behavior for result-only
    # scopes. Schema-v2 restore intentionally suppresses these because they
    # have no exact paired Dataset Library identity, but retaining them in the
    # serialized diagnostic snapshot avoids silently discarding historical
    # state at save time.
    for (user_id, project_id), store in list(result_store_module._RESULT_STORES.items()):
        if (user_id, project_id) in paired_result_scopes:
            continue
        if not _scope_is_live(user_id, project_id, live_projects, live_users):
            skipped_orphaned += 1
            continue
        if _is_result_store_empty(store):
            skipped_empty += 1
            continue
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
        serialized = json.dumps(payload, indent=2, sort_keys=True)
        with _CHECKPOINT_LOCK:
            temp_path.write_text(serialized, encoding="utf-8")
            # Windows can transiently reject an otherwise valid atomic
            # replace while an indexing/antivirus reader releases its file
            # handle. Keep the operation bounded and serialized; a persistent
            # sharing violation still fails closed and leaves the previous
            # checkpoint untouched.
            replace_attempts = 8 if os.name == "nt" else 1
            for attempt in range(replace_attempts):
                try:
                    temp_path.replace(CHECKPOINT_PATH)
                    break
                except PermissionError:
                    if attempt + 1 >= replace_attempts:
                        raise
                    time.sleep(0.01 * (2**attempt))
    except Exception as exc:
        LOGGER.warning("Failed to save workflow checkpoint: %r", exc)
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False

    duration = time.perf_counter() - started
    size_bytes = len(serialized.encode("utf-8"))
    CHECKPOINT_WRITE_COUNT += 1
    LAST_SAVE_REPORT = {
        "datastore_scope_count": len(datastore_scopes),
        "results_scope_count": len(results_scopes),
        "skipped_orphaned": skipped_orphaned,
        "skipped_empty": skipped_empty,
        "size_bytes": size_bytes,
        "duration_seconds": duration,
        "write_count": CHECKPOINT_WRITE_COUNT,
    }
    LOGGER.info(
        "Saved workflow checkpoint: %d DATASTORE scope(s), %d RESULTS scope(s), %d bytes in %.3fs "
        "(skipped %d orphaned, %d empty).",
        len(datastore_scopes), len(results_scopes), size_bytes, duration, skipped_orphaned, skipped_empty,
    )
    if size_bytes >= CHECKPOINT_SIZE_CRITICAL_BYTES:
        LOGGER.error(
            "Workflow checkpoint is critically large: %d bytes (critical threshold %d). "
            "No state was discarded; investigate scope lifecycle with server/core/checkpoint_inspect.py.",
            size_bytes, CHECKPOINT_SIZE_CRITICAL_BYTES,
        )
    elif size_bytes >= CHECKPOINT_SIZE_WARNING_BYTES:
        LOGGER.warning(
            "Workflow checkpoint is large: %d bytes (warning threshold %d). "
            "No state was discarded; investigate scope lifecycle with server/core/checkpoint_inspect.py.",
            size_bytes, CHECKPOINT_SIZE_WARNING_BYTES,
        )
    return True


def schedule_checkpoint_save() -> bool:
    """Mark the checkpoint dirty and return immediately.

    A single daemon writer thread performs one physical save_checkpoint()
    once no further marks have arrived for CHECKPOINT_DEBOUNCE_SECONDS
    (or CHECKPOINT_MAX_PENDING_SECONDS have elapsed since the first
    unwritten mark, whichever comes first) -- so a burst of rapid mutations
    costs one write instead of one write per mutation. Returns True when
    the save was scheduled (the write itself is asynchronous; failures are
    logged by save_checkpoint and retried on the next mark or flush)."""
    global _DIRTY_SINCE, _LAST_MARK
    now = time.monotonic()
    with _DIRTY_LOCK:
        _LAST_MARK = now
        if _DIRTY_SINCE is None:
            _DIRTY_SINCE = now
        _ensure_writer_thread()
    _WAKE.set()
    return True


def flush_checkpoint() -> bool:
    """Force one synchronous physical write now, absorbing any pending
    scheduled save. Used by the FastAPI shutdown hook, by project deletion
    (so the file reflects the deletion immediately), and by tests."""
    global _DIRTY_SINCE, _LAST_MARK
    with _DIRTY_LOCK:
        _DIRTY_SINCE = None
        _LAST_MARK = None
    _WAKE.clear()
    return save_checkpoint()


def shutdown_checkpoint_writer() -> None:
    """Graceful-shutdown hook: stop the writer thread and flush any pending
    state so the most recent draft mutations are not lost."""
    _WRITER_SHUTDOWN.set()
    _WAKE.set()  # unblock the writer loop so it can observe shutdown
    flush_checkpoint()


def _ensure_writer_thread() -> None:
    global _WRITER_THREAD
    if _WRITER_THREAD is not None and _WRITER_THREAD.is_alive():
        return
    _WRITER_SHUTDOWN.clear()
    _WRITER_THREAD = threading.Thread(
        target=_checkpoint_writer_loop, name="atlas-checkpoint-writer", daemon=True
    )
    _WRITER_THREAD.start()


def _checkpoint_writer_loop() -> None:
    global _DIRTY_SINCE
    while not _WRITER_SHUTDOWN.is_set():
        _WAKE.wait()
        if _WRITER_SHUTDOWN.is_set():
            return
        # Debounce: wait until the burst has been quiet for
        # CHECKPOINT_DEBOUNCE_SECONDS, bounded by CHECKPOINT_MAX_PENDING_SECONDS.
        while not _WRITER_SHUTDOWN.is_set():
            with _DIRTY_LOCK:
                if _DIRTY_SINCE is None:
                    # A flush absorbed the pending work while we debounced.
                    _WAKE.clear()
                    break
                now = time.monotonic()
                quiet = now - (_LAST_MARK or now)
                pending = now - _DIRTY_SINCE
                due = quiet >= CHECKPOINT_DEBOUNCE_SECONDS or pending >= CHECKPOINT_MAX_PENDING_SECONDS
                if due:
                    _DIRTY_SINCE = None
                    _WAKE.clear()
            if due:
                save_checkpoint()
                break
            time.sleep(min(CHECKPOINT_DEBOUNCE_SECONDS, 0.25))


def discard_modeling_scopes(
    project_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, int]:
    """Drop resident modeling scopes from _DATASTORES and _RESULT_STORES.

    Matching: with only project_id, every scope for that project is removed
    across ALL owners (the owner's scope and any collaborator-private
    scopes -- correct for whole-project deletion). With only user_id, every
    scope that user owns is removed across all projects (administrative
    user removal). With both, exactly that one scope. Callers that need the
    on-disk file updated immediately should follow with flush_checkpoint().
    """
    if project_id is None and user_id is None:
        return {"datastore_scopes_removed": 0, "results_scopes_removed": 0}

    def _matches(scope: Tuple[str, str]) -> bool:
        scope_user, scope_project = scope
        if project_id is not None and scope_project != project_id:
            return False
        if user_id is not None and scope_user != user_id:
            return False
        return True

    removed_datasets = 0
    for scope in [key for key in dataset_store_module._DATASTORES if _matches(key)]:
        if dataset_store_module.discard_scoped_dataset_store(scope):
            removed_datasets += 1
    removed_results = 0
    for scope in [key for key in result_store_module._RESULT_STORES if _matches(key)]:
        if result_store_module.discard_scoped_result_store(scope):
            removed_results += 1
    if removed_datasets or removed_results:
        LOGGER.info(
            "Discarded modeling scopes (project_id=%r, user_id=%r): %d DATASTORE, %d RESULTS.",
            project_id, user_id, removed_datasets, removed_results,
        )
    return {"datastore_scopes_removed": removed_datasets, "results_scopes_removed": removed_results}


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

    # Stage 6.1: skip records whose project or owner no longer exists, so a
    # deleted project can never be resurrected from a stale checkpoint file.
    # Fail-open like save-time filtering: an unavailable persistence or
    # security store never causes valid records to be dropped.
    live_projects, live_users = _live_identity_sets()
    skipped_orphaned = 0

    restored_datasets = 0
    invalid_dataset_identities = 0
    invalid_dataset_scopes: Set[Tuple[str, str]] = set()
    valid_dataset_scopes: Set[Tuple[str, str]] = set()
    for entry in datastore_scopes:
        parsed = _parse_scope_entry(entry, "dataset")
        if parsed is None:
            continue
        scope_key, fields = parsed
        if not _scope_is_live(scope_key[0], scope_key[1], live_projects, live_users):
            skipped_orphaned += 1
            continue
        store = get_scoped_dataset_store(scope_key)
        _apply_dataset(store, fields)
        # Every non-empty DATASTORE checkpoint record is dataset-bound.  A
        # target-only, split-only, or legacy-meta record must therefore prove
        # the same exact immutable identity as a record carrying raw data.
        has_dataset_state = not _is_dataset_store_empty(store)
        if has_dataset_state:
            from ..datasets.dataset_identity import (
                invalidate_dataset_identity,
                validate_checkpoint_identity,
            )

            valid, reason, identity = validate_checkpoint_identity(
                store,
                owner_user_id=scope_key[0],
                project_id=scope_key[1],
            )
            if not valid or identity is None:
                invalid_dataset_scopes.add(scope_key)
                # RESULTS is the paired model state for the same
                # (owner_user_id, project_id) scope.  Remove any stale
                # in-memory copy immediately and suppress the checkpoint's
                # paired results record below.
                result_store_module.discard_scoped_result_store(scope_key)
                invalidate_dataset_identity(
                    "Checkpoint dataset identity is stale or invalid: " + reason,
                    store=store,
                    clear_frames=True,
                )
                invalid_dataset_identities += 1
                LOGGER.warning(
                    "Restored checkpoint scope %r as blocked state because its exact "
                    "Dataset Library version could not be resolved: %s",
                    scope_key,
                    reason,
                )
            else:
                try:
                    # Reload the exact immutable source artifact. Processed data
                    # and valid split state remain the checkpoint's downstream
                    # snapshot, but raw authority never comes from an unchecked
                    # checkpoint frame or a latest/first-version fallback.
                    store.raw_df = pd.read_csv(identity["artifact_path"])
                    lineage_errors = _checkpoint_pretraining_lineage_errors(
                        store,
                        identity,
                    )
                    if lineage_errors:
                        _quarantine_checkpoint_pretraining_state(
                            store,
                            lineage_errors,
                        )
                        LOGGER.warning(
                            "Quarantined unverifiable pre-training checkpoint "
                            "state for scope %r: %s",
                            scope_key,
                            "; ".join(lineage_errors),
                        )
                    else:
                        valid_dataset_scopes.add(scope_key)
                except Exception as exc:
                    reason = f"The exact registered dataset artifact could not be reloaded: {exc}"
                    invalid_dataset_scopes.add(scope_key)
                    result_store_module.discard_scoped_result_store(scope_key)
                    invalidate_dataset_identity(
                        "Checkpoint dataset identity is stale or invalid: " + reason,
                        store=store,
                        clear_frames=True,
                    )
                    invalid_dataset_identities += 1
                    LOGGER.warning("Blocked checkpoint scope %r: %s", scope_key, reason)
        restored_datasets += 1

    restored_results = 0
    skipped_invalid_results = 0
    for entry in results_scopes:
        parsed = _parse_scope_entry(entry, "results")
        if parsed is None:
            continue
        scope_key, fields = parsed
        if not _scope_is_live(scope_key[0], scope_key[1], live_projects, live_users):
            skipped_orphaned += 1
            continue
        if (
            scope_key in invalid_dataset_scopes
            or scope_key not in valid_dataset_scopes
        ):
            # Fail closed: summaries, availability flags, JSON-safe model
            # artifacts, final-model metadata, and scoring references cannot
            # survive when their paired dataset version did not validate or
            # when no paired DatasetStore checkpoint exists at all.
            result_store_module.discard_scoped_result_store(scope_key)
            skipped_invalid_results += 1
            LOGGER.warning(
                "Skipping checkpoint RESULTS scope %r because its paired "
                "Dataset Library identity is absent or invalid.",
                scope_key,
            )
            continue
        _apply_results(get_scoped_result_store(scope_key), fields)
        restored_results += 1

    LOGGER.info(
        "Restored workflow checkpoint %s: %d DATASTORE scope(s), %d RESULTS scope(s) "
        "(skipped %d orphaned and %d invalid paired RESULTS; blocked %d invalid dataset identities).",
        CHECKPOINT_PATH,
        restored_datasets,
        restored_results,
        skipped_orphaned,
        skipped_invalid_results,
        invalid_dataset_identities,
    )
    return True
