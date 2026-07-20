from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import HTTPException

from ..datasets.dataset_registry import latest_version_id, require_dataset, version_dir


TRANSPORTATION_REQUIRED_INPUT_ROLES = (
    "transportationCost",
    "demand",
    "supplyMax",
    "transportCapacity",
)

TRANSPORTATION_OPTIONAL_INPUT_ROLES = (
    "inventoryCost",
)

TRANSPORTATION_INPUT_ROLES = TRANSPORTATION_REQUIRED_INPUT_ROLES + TRANSPORTATION_OPTIONAL_INPUT_ROLES

TRANSPORTATION_INPUT_LABELS = {
    "transportationCost": "Route cost matrix",
    "demand": "Demand table",
    "supplyMax": "Supply maximum table",
    "transportCapacity": "Transportation capacity table",
    "inventoryCost": "Inventory or handling cost table",
}


def _version_record(dataset: dict[str, Any], version_id: str) -> dict[str, Any]:
    return next(
        (version for version in dataset.get("versions", []) if version.get("versionId") == version_id),
        {},
    )


def resolve_full_dataset_reference(reference: dict[str, Any], role: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    dataset_id = str(reference.get("datasetId") or "").strip()
    if not dataset_id:
        raise HTTPException(
            status_code=422,
            detail=f"{TRANSPORTATION_INPUT_LABELS.get(role, role)} has not been selected.",
        )
    dataset = require_dataset(dataset_id)
    resolved_version = str(reference.get("versionId") or latest_version_id(dataset) or "").strip()
    if not resolved_version:
        raise HTTPException(status_code=422, detail=f"{dataset.get('name') or dataset_id} has no registered version.")
    path = version_dir(dataset_id, resolved_version) / "data_full.csv"
    if not path.exists():
        raise HTTPException(
            status_code=409,
            detail=(
                f"Full dataset artifact is not loaded for {dataset.get('name') or dataset_id}. "
                "Reload the confirmed dataset before building the optimization input bundle."
            ),
        )
    frame = pd.read_csv(path, low_memory=False)
    version = _version_record(dataset, resolved_version)
    metadata = {
        "role": role,
        "label": TRANSPORTATION_INPUT_LABELS.get(role, role),
        "datasetId": dataset_id,
        "versionId": resolved_version,
        "datasetName": dataset.get("name") or dataset_id,
        "fileName": version.get("originalFilename") or dataset.get("name") or path.name,
        "rowCount": int(len(frame)),
        "columnCount": int(len(frame.columns)),
        "columns": [str(column) for column in frame.columns],
        "hash": version.get("hash") or "",
        "path": str(path),
        "fullArtifact": True,
    }
    return frame, metadata


def load_transportation_input_bundle(payload: dict[str, Any]) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    references = payload.get("bundle") or {}
    missing = [role for role in TRANSPORTATION_REQUIRED_INPUT_ROLES if not (references.get(role) or {}).get("datasetId")]
    if missing:
        labels = ", ".join(TRANSPORTATION_INPUT_LABELS[role] for role in missing)
        raise HTTPException(status_code=422, detail=f"Transportation input bundle is incomplete. Missing: {labels}.")

    frames: dict[str, pd.DataFrame] = {}
    metadata: list[dict[str, Any]] = []
    assigned_roles = [
        role
        for role in TRANSPORTATION_INPUT_ROLES
        if (references.get(role) or {}).get("datasetId")
    ]
    for role in assigned_roles:
        frame, table_metadata = resolve_full_dataset_reference(references[role], role)
        frames[role] = frame
        metadata.append(table_metadata)
    return frames, metadata


def artifact_path_from_reference(reference: dict[str, Any], role: str) -> Path:
    _, metadata = resolve_full_dataset_reference(reference, role)
    return Path(metadata["path"])
