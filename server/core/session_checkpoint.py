from __future__ import annotations

import json
import threading
import uuid
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from .dataset_store import DATASTORE
from .result_store import RESULTS


CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / ".runtime" / "workflow_checkpoint.json"
_CHECKPOINT_LOCK = threading.Lock()


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


def save_checkpoint() -> bool:
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    payload: Dict[str, Any] = {
        "dataset": {
            "raw_df": _encode(DATASTORE.raw_df),
            "processed_df": _encode(DATASTORE.processed_df),
            "target": DATASTORE.target,
            "X_train": _encode(DATASTORE.X_train),
            "X_test": _encode(DATASTORE.X_test),
            "y_train": _encode(DATASTORE.y_train),
            "y_test": _encode(DATASTORE.y_test),
            "meta": _encode(DATASTORE.meta) or {},
        },
        "results": {
            "last_training_summary": _encode(RESULTS.last_training_summary),
            "training_timestamp": RESULTS.training_timestamp,
            "model_availability": _encode(RESULTS.model_availability) or {},
            "model_artifacts": _encode(RESULTS.model_artifacts) or {},
            "final_model_metadata": _encode(RESULTS.final_model_metadata),
            "scoring_reference": _encode(RESULTS.scoring_reference),
        },
    }
    temp_path = CHECKPOINT_PATH.with_name(f"{CHECKPOINT_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        with _CHECKPOINT_LOCK:
            temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            temp_path.replace(CHECKPOINT_PATH)
        return True
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


def load_checkpoint() -> bool:
    if not CHECKPOINT_PATH.exists():
        return False
    try:
        payload = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return False

    dataset = payload.get("dataset") or {}
    DATASTORE.raw_df = _decode(dataset.get("raw_df"))
    DATASTORE.processed_df = _decode(dataset.get("processed_df"))
    DATASTORE.target = dataset.get("target")
    DATASTORE.X_train = _decode(dataset.get("X_train"))
    DATASTORE.X_test = _decode(dataset.get("X_test"))
    DATASTORE.y_train = _decode(dataset.get("y_train"))
    DATASTORE.y_test = _decode(dataset.get("y_test"))
    DATASTORE.meta = dataset.get("meta") or {}

    results = payload.get("results") or {}
    RESULTS.last_training_summary = _decode(results.get("last_training_summary"))
    RESULTS.training_timestamp = results.get("training_timestamp")
    RESULTS.model_availability = results.get("model_availability") or {}
    RESULTS.model_artifacts = results.get("model_artifacts") or {}
    RESULTS.final_model = None
    RESULTS.final_model_metadata = _decode(results.get("final_model_metadata"))
    RESULTS.scoring_reference = _decode(results.get("scoring_reference"))
    return True
