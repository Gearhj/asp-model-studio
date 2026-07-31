"""Governed dataset binding for sandboxed code execution.

CODE-DATAACQ-002 root cause
---------------------------
Generated Python emitted `path = Path("path/to/dataset-library-export.csv")`,
a placeholder that could never resolve. Nothing bound the generated code to the
authorized artifact, so even with execution enabled the code would fail.

Contract
--------
ATLAS resolves the authorized artifact **server-side** from the exact
(user, projectId, datasetId, versionId) and copies a read-only extract into the
sandbox's isolated working directory. Generated code never contains a server
path: it receives predefined runtime objects.

    df                  authorized dataset version as a pandas DataFrame
    TARGET              selected target column ("" when not chosen)
    SELECTED_FEATURES   approved predictor list
    ATLAS_DATASET_PATH  read-only path to the extract inside the sandbox workdir

`df` is the primary contract; ATLAS_DATASET_PATH is provided for code that
prefers to read the file itself. Parquet is used when the version has been
materialized, else CSV.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from .runtime_context import build_context_assignment, normalize_runtime_context

from ..datasets.dataset_registry import ARTIFACT_ROOT, require_dataset

#: Hard bound on rows copied into the sandbox. Execution is an interactive
#: convenience, not a bulk export channel.
MAX_SANDBOX_ROWS = int(200_000)


@dataclass
class BoundDataset:
    dataset_id: str
    version_id: str
    dataset_name: str
    artifact_path: Path
    artifact_format: str
    row_count: int
    target: str
    selected_features: List[str]


def resolve_bound_dataset(
    *,
    dataset_id: Optional[str],
    version_id: Optional[str],
    target: str = "",
    selected_features: Optional[List[str]] = None,
) -> Optional[BoundDataset]:
    """Resolves the authorized artifact for the exact immutable version.

    `require_dataset` raises 403/404 on an ACL failure -- that call IS the
    authorization check. Returns None when the caller supplied no registered
    dataset identity (an unregistered workspace upload), so the caller can fall
    back to the preview-row contract.
    """
    if bool(dataset_id) != bool(version_id):
        raise HTTPException(
            status_code=422,
            detail=(
                "Both datasetId and versionId are required to bind an exact "
                "Dataset Library version for code execution."
            ),
        )
    if not dataset_id or not version_id:
        return None

    dataset = require_dataset(dataset_id)
    versions = dataset.get("versions", [])
    version = next(
        (v for v in versions if v.get("versionId") == version_id),
        None,
    )
    if not version:
        raise HTTPException(status_code=404, detail="Dataset version not found.")

    parquet_relative = version.get("analyticalParquetPath")
    csv_relative = version.get("fullDataPath")
    chosen_relative = parquet_relative or csv_relative
    if not chosen_relative:
        return None

    candidate = (ARTIFACT_ROOT / chosen_relative).resolve()
    root = ARTIFACT_ROOT.resolve()
    if not (root in candidate.parents or candidate == root) or not candidate.exists():
        raise HTTPException(status_code=409, detail="The dataset artifact is unavailable.")

    return BoundDataset(
        dataset_id=dataset_id,
        version_id=str(version.get("versionId") or ""),
        dataset_name=str(dataset.get("name") or dataset_id),
        artifact_path=candidate,
        artifact_format="parquet" if parquet_relative else "csv",
        row_count=int(version.get("rowCount") or 0),
        target=target or str((dataset.get("sourceInfo") or {}).get("target") or ""),
        selected_features=list(selected_features or []),
    )


def stage_dataset_for_sandbox(bound: BoundDataset, workdir: Path) -> Path:
    """Copies the authorized artifact into the sandbox's isolated working
    directory. The sandbox therefore never receives a path outside its own
    workdir and cannot browse the server's artifact tree."""
    destination = workdir / f"atlas_dataset.{'parquet' if bound.artifact_format == 'parquet' else 'csv'}"
    shutil.copyfile(bound.artifact_path, destination)
    return destination


def _legacy_context_aliases(context: Optional[Dict[str, Any]]) -> str:
    """Backward-compatible names for previously-saved user code.

    Analytics Workbench and Notebook Studio code written before governed dataset
    binding referenced `preview_rows`, `primary_preview_rows`,
    `secondary_preview_rows`, `dataset_name`, and `version_id`. Those names stay
    available so existing saved programs keep running.
    """
    # JSON is embedded as a quoted string literal and parsed at runtime. Pasting
    # json.dumps() output straight into source produced `null`/`true`/`false`,
    # which are not Python literals -- a single missing dataset cell raised
    # NameError before the user's program ran.
    normalized, _conversions = normalize_runtime_context(context or {})
    return (
        build_context_assignment("ATLAS_CONTEXT", normalized)
        + "preview_rows = ATLAS_CONTEXT.get('previewRows', ATLAS_CONTEXT.get('preview_rows', []))\n"
        "primary_preview_rows = ATLAS_CONTEXT.get('primary_preview_rows', preview_rows)\n"
        "secondary_preview_rows = ATLAS_CONTEXT.get('secondary_preview_rows', [])\n"
        "dataset_name = ATLAS_CONTEXT.get('datasetName', ATLAS_CONTEXT.get('dataset_name', ''))\n"
        "version_id = ATLAS_CONTEXT.get('versionId', ATLAS_CONTEXT.get('version_id', ''))\n"
    )


def build_runtime_prelude(
    bound: Optional[BoundDataset],
    staged_path: Optional[Path],
    preview_rows: Optional[List[Dict[str, Any]]] = None,
    target: str = "",
    selected_features: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """Emits the predefined-runtime-object prelude prepended to user code.

    Every branch defines df, TARGET, SELECTED_FEATURES and ATLAS_DATASET_PATH so
    user code can rely on the documented contract regardless of source type.
    """
    features = list(selected_features or (bound.selected_features if bound else []))
    resolved_target = target or (bound.target if bound else "")

    if bound and staged_path:
        reader = "pd.read_parquet" if bound.artifact_format == "parquet" else "pd.read_csv"
        return (
            "# ATLAS governed runtime. Objects below are provided by the platform.\n"
            "import json\n"
            "import pandas as pd\n"
            + build_context_assignment("ATLAS_DATASET_PATH", staged_path.name)
            + build_context_assignment("DATASET_ID", bound.dataset_id)
            + build_context_assignment("DATASET_VERSION", bound.version_id)
            + build_context_assignment("DATASET_NAME", bound.dataset_name)
            + build_context_assignment("TARGET", resolved_target)
            + build_context_assignment("SELECTED_FEATURES", features)
            + f"df = {reader}(ATLAS_DATASET_PATH)\n"
            f"if len(df) > {MAX_SANDBOX_ROWS}:\n"
            f"    df = df.head({MAX_SANDBOX_ROWS})\n"
            + _legacy_context_aliases(context)
            + "\n"
        )

    # Unregistered workspace source: the browser preview is all ATLAS has.
    return (
        "# ATLAS governed runtime. Objects below are provided by the platform.\n"
        "# This project has no registered Dataset Library version, so df is built\n"
        "# from the browser preview rows rather than a governed artifact.\n"
        "import json\n"
        "import pandas as pd\n"
        + build_context_assignment("ATLAS_PREVIEW_ROWS", normalize_runtime_context({"rows": list(preview_rows or [])})[0]["rows"])
        + "ATLAS_DATASET_PATH = None\n"
        + build_context_assignment("TARGET", resolved_target)
        + build_context_assignment("SELECTED_FEATURES", features)
        + "df = pd.DataFrame(ATLAS_PREVIEW_ROWS)\n"
        + _legacy_context_aliases(context)
        + "\n"
    )


def runtime_contract_description(bound: Optional[BoundDataset]) -> Dict[str, Any]:
    """Machine-readable description of what user code can rely on, shown above
    the editor so the contract is visible before running anything."""
    return {
        "primary": "dataframe",
        "objects": [
            {"name": "df", "description": "Authorized dataset version loaded as a pandas DataFrame"},
            {"name": "TARGET", "description": "Selected target column"},
            {"name": "SELECTED_FEATURES", "description": "Approved predictor list"},
            {"name": "ATLAS_DATASET_PATH", "description": "Read-only path to the staged dataset inside the sandbox working directory"},
        ],
        "datasetId": bound.dataset_id if bound else "",
        "versionId": bound.version_id if bound else "",
        "datasetName": bound.dataset_name if bound else "",
        "artifactFormat": bound.artifact_format if bound else "",
        "rowCount": bound.row_count if bound else 0,
        "source": "registered_version" if bound else "browser_preview",
    }
