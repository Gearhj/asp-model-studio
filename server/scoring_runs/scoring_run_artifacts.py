"""ATLAS Persistent Scoring Runs -- governed Parquet artifact storage for
row-level scored output.

Mirrors server/analytics/parquet_service.py's discipline: metadata (the
`scoring_runs` SQLite table) never holds the full row-level table (Phase C).
The scored DataFrame is written once, on scoring-run creation, to a
per-run Parquet file under ARTIFACT_ROOT, and is never mutated afterward --
a ScoringRun is immutable once created. CSV export is available on demand
(Phase C: "CSV export optional") by reading the Parquet artifact back and
re-encoding, never by keeping a second copy on disk.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pa_parquet

ARTIFACT_ROOT = Path(
    os.getenv("ATLAS_SCORING_RUN_ARTIFACT_ROOT")
    or (Path(__file__).resolve().parent.parent / "artifacts" / "scoring_runs")
).resolve()


def _within_artifact_root(path: Path) -> bool:
    try:
        resolved = path.resolve()
        return ARTIFACT_ROOT in resolved.parents or resolved == ARTIFACT_ROOT
    except (OSError, RuntimeError):
        return False


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_scoring_run_parquet(scoring_run_id: str, frame: pd.DataFrame) -> Dict[str, Any]:
    """Writes `frame` (the full scored-row output, already built by
    eval_service.score_dataset) to a governed, per-run Parquet file. Returns
    the relative path (for storage in the scoring_runs row), checksum, and
    row/column counts. Never called twice for the same scoring_run_id -- a
    ScoringRun is immutable once created."""
    run_dir = (ARTIFACT_ROOT / scoring_run_id).resolve()
    if not _within_artifact_root(run_dir):
        raise ValueError("Resolved scoring run artifact path escapes the governed artifact root.")
    run_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = run_dir / "predictions.parquet"

    # Arrow cannot infer a schema for a frame with zero rows and zero columns;
    # an empty-but-typed frame (columns known, no rows) still round-trips fine.
    table = pa.Table.from_pandas(frame, preserve_index=False)
    pa_parquet.write_table(table, parquet_path, compression="snappy")

    checksum = _sha256_of_file(parquet_path)
    return {
        "path": str(parquet_path.relative_to(ARTIFACT_ROOT)),
        "absolutePath": parquet_path,
        "rowCount": int(table.num_rows),
        "columnCount": int(table.num_columns),
        "checksum": checksum,
        "sizeBytes": parquet_path.stat().st_size,
    }


def resolve_scoring_run_artifact_path(relative_path: str) -> Path:
    candidate = (ARTIFACT_ROOT / relative_path).resolve()
    if not _within_artifact_root(candidate) or not candidate.exists():
        raise ValueError("Scoring run artifact is unavailable or outside the governed artifact root.")
    return candidate


def read_scoring_run_rows(relative_path: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """Bounded read for the scoring-run rows/preview endpoint -- never used by
    the Enterprise Analytical Data Plane's own DuckDB pushdown path, which
    scans the Parquet file directly via artifact_resolver.py instead of going
    through pandas."""
    path = resolve_scoring_run_artifact_path(relative_path)
    frame = pd.read_parquet(path)
    total_rows = int(len(frame))
    bounded = frame.head(limit) if limit else frame
    return {
        "columns": [str(c) for c in frame.columns],
        "rows": bounded.to_dict(orient="records"),
        "totalRowCount": total_rows,
        "truncated": limit is not None and total_rows > limit,
    }


def delete_scoring_run_artifacts(scoring_run_id: str) -> bool:
    """Used only by test cleanup / explicit retention-policy purges -- never
    called from the normal scoring-run lifecycle (archival, not deletion, is
    the default -- see ScoringRunRepository.archive_for_project)."""
    run_dir = (ARTIFACT_ROOT / scoring_run_id).resolve()
    if not _within_artifact_root(run_dir) or not run_dir.exists():
        return False
    for child in run_dir.glob("*"):
        child.unlink()
    run_dir.rmdir()
    return True
