from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.session_checkpoint import save_checkpoint
from .split_service import split_service, target_distribution


router = APIRouter()


class SplitConfigPayload(BaseModel):
    split_strategy: Literal["holdout"] = "holdout"
    test_size: float = Field(default=0.2, ge=0.1, le=0.5)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    stratify: bool = True
    balance_method: Literal["none", "undersample", "oversample", "smote"] = "none"
    minority_share: float = Field(default=0.5, ge=0.05, le=0.5)
    problem_type: Literal["classification", "regression"] = "classification"
    event_value: Any | None = None
    selected_features: list[str] = Field(default_factory=list)
    feature_manifest_version: str = ""
    dataset_version: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _selected_manifest_features(manifest: dict[str, Any]) -> list[str]:
    return [
        str(row.get("feature_name"))
        for row in manifest.get("features", [])
        if isinstance(row, dict) and row.get("selected") and row.get("eligibility_status") == "eligible"
    ]


def _require_full_dataset():
    frame = DATASTORE.get_base_df()
    if frame is None or frame.empty:
        raise HTTPException(status_code=400, detail="No full backend dataset is loaded.")
    target = str(DATASTORE.target or "")
    if not target or target not in frame.columns:
        raise HTTPException(status_code=400, detail="Confirm a target column before creating a split.")
    return frame, target


def _current_status() -> dict[str, Any]:
    meta = DATASTORE.meta
    record = meta.get("split_record") if isinstance(meta.get("split_record"), dict) else {}
    manifest = meta.get("feature_manifest") if isinstance(meta.get("feature_manifest"), dict) else {}
    stored_status = str(meta.get("split_status") or "not_created")
    has_split = all(part is not None for part in DATASTORE.get_splits())
    status = stored_status
    reason = ""
    current_dataset_version = str(meta.get("dataset_version") or manifest.get("dataset_version") or "in-memory")
    current_manifest_version = str(manifest.get("manifest_version") or "")
    current_selected = _selected_manifest_features(manifest) or DATASTORE.get_selected_columns()
    current_target = str(DATASTORE.target or "")
    record_selected = [str(value) for value in record.get("selected_features") or []]
    if status == "current" and not has_split:
        status = "stale"
        reason = "Validation split is stale because split data is not loaded in the backend session."
    elif status == "current" and record.get("dataset_version") and record.get("dataset_version") != current_dataset_version:
        status = "stale"
        reason = "Validation split is stale because the dataset version changed."
    elif status == "current" and record.get("feature_manifest_version") and record.get("feature_manifest_version") != current_manifest_version:
        status = "stale"
        reason = "Validation split is stale because engineered features were updated."
    elif status == "current" and record_selected and record_selected != current_selected:
        status = "stale"
        reason = "Validation split is stale because the selected feature set changed."
    elif status == "current" and record.get("target") and record.get("target") != current_target:
        status = "stale"
        reason = "Validation split is stale because the target changed."
    elif status == "current":
        train_distribution = (record.get("distributions") or {}).get("train_after_balancing") or {}
        holdout_distribution = (record.get("distributions") or {}).get("holdout_untouched") or {}
        if train_distribution.get("events") == 0:
            status = "stale"
            reason = "Training split has zero events."
        elif holdout_distribution.get("events") == 0:
            status = "stale"
            reason = "Holdout split has zero events."
    if not reason:
        if status == "current":
            reason = "Ready for next step. Validation split is current."
        elif has_split:
            reason = "Validation split is stale. Rebuild Validation Split."
        else:
            reason = "Create a governed validation split before continuing."
    return {
        "ok": True,
        "status": status,
        "ready": status == "current" and has_split,
        "readiness_reason": reason,
        "has_split": has_split,
        "split_id": record.get("split_id"),
        "config_hash": record.get("config_hash"),
        "selected_feature_hash": record.get("selected_feature_hash"),
        "split_config_hash": record.get("split_config_hash"),
        "balancing_config_hash": record.get("balancing_config_hash"),
        "created_at": record.get("created_at"),
        "dataset_version": record.get("dataset_version"),
        "target": record.get("target"),
        "event_value": record.get("event_value"),
        "feature_manifest_version": record.get("feature_manifest_version"),
        "selected_features": record.get("selected_features") or [],
        "feature_count": len(record.get("selected_features") or []),
        "config": record.get("config") or {},
        "distributions": record.get("distributions") or {},
        "n_train": record.get("n_train"),
        "n_test": record.get("n_test"),
        "original_train_rows": record.get("original_train_rows"),
        "duration_ms": record.get("duration_ms"),
        "execution_ms": record.get("execution_ms") or record.get("duration_ms"),
    }


@router.get("/status")
def balancing_split_status():
    return _current_status()


@router.post("/config")
def balancing_split_config(payload: SplitConfigPayload):
    started = time.perf_counter()
    frame, target = _require_full_dataset()
    manifest = DATASTORE.meta.get("feature_manifest") if isinstance(DATASTORE.meta.get("feature_manifest"), dict) else {}
    current_manifest_version = str(manifest.get("manifest_version") or "")
    current_dataset_version = str(DATASTORE.meta.get("dataset_version") or manifest.get("dataset_version") or "in-memory")

    if payload.feature_manifest_version and current_manifest_version and payload.feature_manifest_version != current_manifest_version:
        raise HTTPException(status_code=409, detail="The feature manifest changed. Refresh Final Predictor Review before creating the split.")
    if payload.dataset_version and current_dataset_version and payload.dataset_version != current_dataset_version:
        raise HTTPException(status_code=409, detail="The dataset version changed. Reload this page before creating the split.")

    manifest_selected = _selected_manifest_features(manifest)
    selected = list(dict.fromkeys(payload.selected_features or manifest_selected or DATASTORE.get_selected_columns()))
    missing = [name for name in selected if name not in frame.columns]
    if missing:
        raise HTTPException(status_code=409, detail="Selected engineered features must be materialized before splitting: " + ", ".join(missing))
    if target in selected:
        raise HTTPException(status_code=400, detail="The target cannot be included in the predictor manifest.")

    config = payload.model_dump(exclude={"selected_features", "feature_manifest_version", "dataset_version"})
    config["target"] = target
    try:
        result = split_service.make_dev_split(frame, target, selected, config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    DATASTORE.meta["selected_columns"] = selected
    DATASTORE.set_splits(result.X_train, result.X_test, result.y_train, result.y_test)
    config_payload = {
        **config,
        "dataset_version": current_dataset_version,
        "feature_manifest_version": current_manifest_version,
        "selected_features": selected,
    }
    config_hash = _stable_hash(config_payload)[:20]
    selected_feature_hash = _stable_hash({"selected_features": selected})[:20]
    split_config_hash = _stable_hash({"split": {key: config.get(key) for key in ("split_strategy", "test_size", "random_seed", "stratify")}})[:20]
    balancing_config_hash = _stable_hash({"balancing": {key: config.get(key) for key in ("balance_method", "minority_share")}})[:20]
    split_id = f"split-{config_hash}"
    distributions = {
        "full_dataset": target_distribution(frame[target], payload.event_value),
        "train_before_balancing": result.original_train_distribution,
        "train_after_balancing": result.applied_train_distribution,
        "holdout_untouched": result.test_distribution,
    }
    record = {
        "split_id": split_id,
        "config_hash": config_hash,
        "selected_feature_hash": selected_feature_hash,
        "split_config_hash": split_config_hash,
        "balancing_config_hash": balancing_config_hash,
        "created_at": _now(),
        "dataset_version": current_dataset_version,
        "target": target,
        "event_value": payload.event_value,
        "feature_manifest_version": current_manifest_version,
        "selected_features": selected,
        "config": config,
        "distributions": distributions,
        "n_train": int(len(result.y_train)),
        "n_test": int(len(result.y_test)),
        "original_train_rows": result.original_train_rows,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }
    record["execution_ms"] = record["duration_ms"]
    DATASTORE.meta["split_record"] = record
    DATASTORE.meta["split_config"] = config_payload
    DATASTORE.meta["target_prevalence"] = {
        "original": distributions["full_dataset"].get("event_rate"),
        "train": distributions["train_after_balancing"].get("event_rate"),
        "test": distributions["holdout_untouched"].get("event_rate"),
    }
    DATASTORE.meta["split_status"] = "current"
    if manifest:
        manifest["split_status"] = "current"
        DATASTORE.meta["feature_manifest"] = manifest
    save_checkpoint()
    return {
        "ok": True,
        "status": "current",
        "ready": True,
        "readiness_reason": "Ready for next step. Validation split is current.",
        "has_split": True,
        **record,
    }
