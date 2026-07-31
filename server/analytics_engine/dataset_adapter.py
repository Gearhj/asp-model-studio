from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

import pandas as pd
from fastapi import HTTPException

from ..core.dataset_store import DATASTORE
from ..datasets.dataset_identity import (
    active_dataset_identity,
    resolve_registered_version,
)
from .errors import InsufficientDataError


def load_dataset(payload: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Resolve a governed full artifact first; active in-memory data is explicit local scope."""
    dataset_id = str(payload.get("dataset_id") or payload.get("datasetId") or "").strip()
    version_id = str(payload.get("dataset_version_id") or payload.get("datasetVersionId") or payload.get("versionId") or "").strip()
    if dataset_id:
        if not version_id:
            raise InsufficientDataError(
                "An exact dataset_version_id is required; ATLAS will not select "
                "the latest Dataset Library version."
            )
        try:
            identity = resolve_registered_version(dataset_id, version_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise InsufficientDataError(str(getattr(exc, "detail", exc))) from exc
        path = Path(identity["artifact_path"])
        return pd.read_csv(path, low_memory=False), {
            "dataset_id": identity["dataset_id"],
            "dataset_version_id": identity["dataset_version_id"],
            "dataset_name": identity["dataset"].get("name"),
            "profile_scope": "full_dataset",
            "path": str(path),
        }
    df = DATASTORE.get_active_df(include_target=True)
    if df is None or df.empty:
        raise InsufficientDataError("A governed dataset reference or active full dataset is required before analysis.")
    project_id = str(
        payload.get("project_id")
        or payload.get("projectId")
        or DATASTORE.meta.get("project_id")
        or ""
    ).strip()
    try:
        identity = active_dataset_identity(project_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise InsufficientDataError(str(getattr(exc, "detail", exc))) from exc
    source = DATASTORE.meta.get("source") or {}
    return df, {
        "dataset_id": identity["dataset_id"],
        "dataset_version_id": identity["dataset_version_id"],
        "dataset_name": source.get("filename"),
        "profile_scope": "active_session_full_dataset",
    }


def require_columns(df: pd.DataFrame, *columns: str | None) -> None:
    missing = [str(column) for column in columns if column and str(column) not in df.columns]
    if missing:
        from .errors import MissingColumnError
        raise MissingColumnError(f"The following required columns are not available in the selected dataset: {', '.join(missing)}.")
