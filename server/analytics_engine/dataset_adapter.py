from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd

from ..core.dataset_store import DATASTORE
from ..datasets.dataset_registry import latest_version_id, require_dataset, version_dir
from .errors import InsufficientDataError


def load_dataset(payload: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Resolve a governed full artifact first; active in-memory data is explicit local scope."""
    dataset_id = str(payload.get("dataset_id") or payload.get("datasetId") or "").strip()
    version_id = str(payload.get("dataset_version_id") or payload.get("datasetVersionId") or payload.get("versionId") or "").strip()
    if dataset_id:
        dataset = require_dataset(dataset_id)
        version_id = version_id or str(latest_version_id(dataset) or "")
        path: Path = version_dir(dataset_id, version_id) / "data_full.csv"
        if not path.exists():
            raise InsufficientDataError("Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before running analysis.")
        return pd.read_csv(path, low_memory=False), {"dataset_id": dataset_id, "dataset_version_id": version_id, "dataset_name": dataset.get("name"), "profile_scope": "full_dataset", "path": str(path)}
    df = DATASTORE.get_active_df(include_target=True)
    if df is None or df.empty:
        raise InsufficientDataError("A governed dataset reference or active full dataset is required before analysis.")
    source = DATASTORE.meta.get("source") or {}
    return df, {"dataset_id": source.get("datasetId"), "dataset_version_id": DATASTORE.meta.get("dataset_version"), "dataset_name": source.get("filename"), "profile_scope": "active_session_full_dataset"}


def require_columns(df: pd.DataFrame, *columns: str | None) -> None:
    missing = [str(column) for column in columns if column and str(column) not in df.columns]
    if missing:
        from .errors import MissingColumnError
        raise MissingColumnError(f"The following required columns are not available in the selected dataset: {', '.join(missing)}.")
