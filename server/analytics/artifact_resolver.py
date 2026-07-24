"""Enterprise Analytical Data Plane -- server-side artifact resolution.

This is the ONLY place a queryId's data source is turned into a physical file
path or in-memory frame. No visualization client ever supplies a path; every
resolution here re-derives the location from (projectId, datasetId, versionId,
sourceType) and re-checks authorization, exactly like the equivalent existing
ATLAS endpoints (authorize_modeling_scope, require_dataset). Path traversal is
prevented by resolving to an absolute path and verifying it stays within
ARTIFACT_ROOT before any file is opened.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import HTTPException

from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import authorize_modeling_scope
from ..core.result_store import RESULTS
from ..datasets.dataset_registry import ARTIFACT_ROOT, require_dataset
from ..scoring_runs.scoring_run_artifacts import resolve_scoring_run_artifact_path
from ..persistence.service import get_persistence_service
from .query_contract import AnalyticalQueryRequest, SourceType


@dataclass
class ResolvedSource:
    source_type: SourceType
    dataset_id: Optional[str]
    version_id: Optional[str]
    file_path: Optional[Path]  # set only when a real on-disk file backs this source
    file_format: Optional[str]  # "parquet" | "csv" | None (in-memory only)
    frame: Optional[pd.DataFrame]  # set when the source is already in-memory (workspace, evaluation-result)
    source_identity: str
    target: Optional[str]
    problem_type: Optional[str]


def _within_artifact_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return ARTIFACT_ROOT.resolve() in resolved.parents or resolved == ARTIFACT_ROOT.resolve()
    except (OSError, RuntimeError):
        return False


def resolve_source(user: Dict[str, Any], request: AnalyticalQueryRequest) -> ResolvedSource:
    """Authorize and resolve `request`'s data source. Raises HTTPException(400/403/404)
    on any authorization or identity failure -- callers must not catch these to
    silently continue with unauthorized data."""

    if request.sourceType == SourceType.WORKSPACE:
        authorize_modeling_scope(user, request.projectId, "view")
        df = DATASTORE.get_active_df()
        if df is None:
            raise HTTPException(status_code=404, detail="No workspace dataset is loaded for this project.")
        return ResolvedSource(
            source_type=SourceType.WORKSPACE, dataset_id=None, version_id=None,
            file_path=None, file_format=None, frame=df,
            source_identity=f"workspace:{request.projectId}",
            target=DATASTORE.target, problem_type=DATASTORE.meta.get("problem_type"),
        )

    if request.sourceType == SourceType.REGISTERED:
        if not request.datasetId:
            raise HTTPException(status_code=400, detail="datasetId is required for a registered-source query.")
        dataset = require_dataset(request.datasetId)  # raises 403/404 on ACL failure -- this IS the authorization check
        versions = dataset.get("versions", [])
        version = next((v for v in versions if v.get("versionId") == request.versionId), versions[-1] if versions else None)
        if not version:
            raise HTTPException(status_code=404, detail="Dataset version not found.")
        version_id = version.get("versionId")

        # Prefer a governed Parquet representation (Phase F) when one exists, else CSV.
        parquet_relative = version.get("analyticalParquetPath")
        csv_relative = version.get("fullDataPath")
        chosen_relative = parquet_relative or csv_relative
        chosen_format = "parquet" if parquet_relative else "csv"
        if not chosen_relative:
            raise HTTPException(status_code=409, detail="This dataset version has no full data artifact to query.")

        candidate = (ARTIFACT_ROOT / chosen_relative).resolve()
        if not _within_artifact_root(candidate) or not candidate.exists():
            raise HTTPException(status_code=409, detail="The dataset artifact is unavailable.")

        return ResolvedSource(
            source_type=SourceType.REGISTERED, dataset_id=request.datasetId, version_id=version_id,
            file_path=candidate, file_format=chosen_format, frame=None,
            source_identity=f"registered:{request.datasetId}:{version_id}",
            target=(dataset.get("sourceInfo") or {}).get("target"),
            problem_type=(dataset.get("sourceInfo") or {}).get("problemType"),
        )

    if request.sourceType == SourceType.EVALUATION_RESULT:
        authorize_modeling_scope(user, request.projectId, "view")
        summary = RESULTS.get_last_summary()
        if not summary:
            raise HTTPException(status_code=404, detail="No training result is available for this project.")
        model_key = request.modelId or ""
        raw = (summary.get("raw") or {}).get(model_key)
        if raw is None:
            raise HTTPException(status_code=404, detail=f"No result found for model '{model_key}'.")
        y_true = raw.get("y_true") or []
        y_score = raw.get("y_score") or []
        frame = pd.DataFrame({"actual": y_true, "prediction": y_score})
        frame["residual"] = frame["actual"] - frame["prediction"]
        return ResolvedSource(
            source_type=SourceType.EVALUATION_RESULT, dataset_id=request.datasetId, version_id=request.versionId,
            file_path=None, file_format=None, frame=frame,
            source_identity=f"evaluation-result:{request.projectId}:{model_key}",
            target=summary.get("target"), problem_type=summary.get("problem_type"),
        )

    if request.sourceType == SourceType.SCORING_SESSION:
        if not request.scoringRunId:
            raise HTTPException(status_code=400, detail="scoringRunId is required for a scoring-session query.")
        run = get_persistence_service().scoring_runs.get(request.scoringRunId)
        if run is None:
            raise HTTPException(status_code=404, detail="Scoring run not found.")
        if run.get("project_id") and run["project_id"] != request.projectId:
            # A query's projectId must match the scoring run's own project -- never
            # resolve a scoring run belonging to a different project even if the
            # caller happens to have access to both (no cross-project leakage).
            raise HTTPException(status_code=403, detail="This scoring run does not belong to the requested project.")
        authorize_modeling_scope(user, request.projectId, "view")
        artifact_path = run.get("output_artifact_path")
        if not artifact_path:
            raise HTTPException(status_code=409, detail="This scoring run has no queryable output artifact.")
        try:
            candidate = resolve_scoring_run_artifact_path(artifact_path)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ResolvedSource(
            source_type=SourceType.SCORING_SESSION, dataset_id=run.get("dataset_id"), version_id=run.get("dataset_version_id"),
            file_path=candidate, file_format="parquet", frame=None,
            source_identity=f"scoring-session:{request.scoringRunId}",
            target=run.get("target"), problem_type=run.get("problem_type"),
        )

    raise HTTPException(status_code=400, detail=f"Unsupported sourceType for server-side query: {request.sourceType}.")
