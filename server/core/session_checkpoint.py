from __future__ import annotations

import pickle
import threading
import uuid
from pathlib import Path
from typing import Any, Dict

from .dataset_store import DATASTORE
from .result_store import RESULTS


CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / ".runtime" / "workflow_checkpoint.pkl"
_CHECKPOINT_LOCK = threading.Lock()


def save_checkpoint() -> bool:
    try:
        CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False
    payload: Dict[str, Any] = {
        "dataset": {
            "raw_df": DATASTORE.raw_df,
            "processed_df": DATASTORE.processed_df,
            "target": DATASTORE.target,
            "X_train": DATASTORE.X_train,
            "X_test": DATASTORE.X_test,
            "y_train": DATASTORE.y_train,
            "y_test": DATASTORE.y_test,
            "meta": DATASTORE.meta,
        },
        "results": {
            "last_training_summary": RESULTS.last_training_summary,
            "training_timestamp": RESULTS.training_timestamp,
            "model_availability": RESULTS.model_availability,
            "model_artifacts": RESULTS.model_artifacts,
            "final_model": RESULTS.final_model,
            "final_model_metadata": RESULTS.final_model_metadata,
            "scoring_reference": RESULTS.scoring_reference,
        },
    }
    temp_path = CHECKPOINT_PATH.with_name(f"{CHECKPOINT_PATH.name}.{uuid.uuid4().hex}.tmp")
    try:
        with _CHECKPOINT_LOCK:
            with temp_path.open("wb") as handle:
                pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
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
        with CHECKPOINT_PATH.open("rb") as handle:
            payload = pickle.load(handle)
    except Exception:
        return False

    dataset = payload.get("dataset") or {}
    DATASTORE.raw_df = dataset.get("raw_df")
    DATASTORE.processed_df = dataset.get("processed_df")
    DATASTORE.target = dataset.get("target")
    DATASTORE.X_train = dataset.get("X_train")
    DATASTORE.X_test = dataset.get("X_test")
    DATASTORE.y_train = dataset.get("y_train")
    DATASTORE.y_test = dataset.get("y_test")
    DATASTORE.meta = dataset.get("meta") or {}

    results = payload.get("results") or {}
    RESULTS.last_training_summary = results.get("last_training_summary")
    RESULTS.training_timestamp = results.get("training_timestamp")
    RESULTS.model_availability = results.get("model_availability") or {}
    RESULTS.model_artifacts = results.get("model_artifacts") or {}
    RESULTS.final_model = results.get("final_model")
    RESULTS.final_model_metadata = results.get("final_model_metadata")
    RESULTS.scoring_reference = results.get("scoring_reference")
    return True
