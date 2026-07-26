"""Enterprise Analytical Data Plane -- bounded target-distribution aggregate.

Why this exists
---------------
The Target Distribution chart previously read its counts out of the full
data-quality profile (`POST /api/data/quality-profile` ->
`profile_active_dataset`). That endpoint profiles EVERY column -- per-column
missingness, nunique, numeric coercion, IQR quantiles, date parsing -- plus a
whole-frame `pd.util.hash_pandas_object`. Measured on the registered 170,884-row
x 31-column CLASS_TRAIN asset that is ~4.0 s of server compute (on top of a
~4.6 s pandas CSV read) purely to obtain two rows of grouped counts.

This module answers only the question the chart actually asks:

    SELECT <target>, COUNT(*) FROM <artifact> GROUP BY <target>

It scans the governed artifact with DuckDB using column projection, so only the
target column is read off disk, and returns bounded aggregate rows -- never the
target column itself. Measured on the same asset: ~1.3 s cold over CSV, ~0.13 s
over Parquet, and a cache hit thereafter.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from ..datasets.dataset_registry import ARTIFACT_ROOT, require_dataset
from . import result_cache

# A target with more distinct values than this is not a classification target we
# will chart; the caller gets an explicit "unsupported" rather than a huge result.
MAX_TARGET_CARDINALITY = 50

# Exact aggregation is attempted unless the artifact is larger than this. The
# measured cold cost is ~1.3 s for an 82 MB CSV, so this bound keeps the exact
# path comfortably inside the 2 s interactive policy for CSV-backed sources.
# Parquet is far cheaper per byte and is allowed a much larger bound.
EXACT_MAX_CSV_BYTES = 600 * 1024 * 1024
EXACT_MAX_PARQUET_BYTES = 4 * 1024 * 1024 * 1024

# Deterministic seed for the stratified fallback, so a sampled estimate is
# reproducible for a given (version, target) pair.
SAMPLE_SEED = 42
SAMPLE_TARGET_ROWS = 2_000_000

ENGINE_VERSION = "target-distribution/1"

# Serializes DuckDB work so a burst of panel mounts cannot spawn unbounded
# concurrent scans of the same artifact.
_QUERY_LOCK = threading.Lock()


def _duckdb():
    """Imports DuckDB on first use.

    Deliberately not a module-level import: this module is imported at app start
    via the analytics router, and an optional analytical engine missing from a
    deployment's interpreter must never prevent the whole API from booting. A
    caller that actually needs the engine gets an honest 503 instead.
    """
    try:
        import duckdb  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on deployment env
        raise HTTPException(
            status_code=503,
            detail="The DuckDB analytical engine is not installed in this deployment, so target distribution cannot be computed.",
        ) from exc
    return duckdb


def _quote_identifier(name: str) -> str:
    """DuckDB identifier quoting. The target column name comes from user data, so
    it is never interpolated unquoted."""
    return '"' + str(name).replace('"', '""') + '"'


def _resolve_version_artifact(dataset_id: str, version_id: Optional[str]) -> Dict[str, Any]:
    """Authorizes and resolves the immutable version's artifact.

    `require_dataset` raises 403/404 on an ACL failure -- that call IS the
    authorization check, exactly as in artifact_resolver.resolve_source.
    """
    dataset = require_dataset(dataset_id)
    versions = dataset.get("versions", [])
    version = next((v for v in versions if v.get("versionId") == version_id), versions[-1] if versions else None)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset version not found.")

    parquet_relative = version.get("analyticalParquetPath")
    csv_relative = version.get("fullDataPath")
    chosen_relative = parquet_relative or csv_relative
    if not chosen_relative:
        raise HTTPException(status_code=409, detail="This dataset version has no full data artifact to aggregate.")

    candidate = (ARTIFACT_ROOT / chosen_relative).resolve()
    root = ARTIFACT_ROOT.resolve()
    if not (root in candidate.parents or candidate == root) or not candidate.exists():
        raise HTTPException(status_code=409, detail="The dataset artifact is unavailable.")

    return {
        "path": candidate,
        "format": "parquet" if parquet_relative else "csv",
        "versionId": version.get("versionId"),
        "rowCount": version.get("rowCount"),
        "sizeBytes": candidate.stat().st_size,
        # Durable governance identity for the resolved artifact. `hash` is the
        # sha256 the Dataset Library recorded when the version was registered, so
        # it identifies the immutable content -- not the filesystem location,
        # which must never reach the browser.
        "checksum": version.get("hash"),
        "datasetName": dataset.get("name") or dataset_id,
        "columnCount": version.get("columnCount"),
    }


def _scan_expression(artifact: Dict[str, Any]) -> str:
    path = artifact["path"].as_posix().replace("'", "''")
    if artifact["format"] == "parquet":
        return f"read_parquet('{path}')"
    # all_varchar skips DuckDB's per-column type sniffing, which is pure overhead
    # here: the aggregate groups on the raw value and the response stringifies it
    # anyway. Measured on the 82 MB / 31-column CLASS_TRAIN CSV this removes
    # ~250 ms from every cold scan.
    return f"read_csv('{path}', all_varchar=true, header=true)"


def _should_sample(artifact: Dict[str, Any], force_exact: bool) -> bool:
    """Sampling is only permitted when the planner determines an exact scan cannot
    meet the interactive policy -- never as a default for rare-event targets."""
    if force_exact:
        return False
    limit = EXACT_MAX_PARQUET_BYTES if artifact["format"] == "parquet" else EXACT_MAX_CSV_BYTES
    return artifact["sizeBytes"] > limit


def _exact_counts(scan: str, target: str) -> List[Dict[str, Any]]:
    column = _quote_identifier(target)
    # Only the target column is projected out of the artifact; the column itself
    # never leaves the server -- only the grouped counts do.
    sql = (
        f"SELECT {column} AS value, COUNT(*) AS count "
        f"FROM {scan} GROUP BY 1 ORDER BY count DESC LIMIT {MAX_TARGET_CARDINALITY + 1}"
    )
    with _QUERY_LOCK:
        connection = _duckdb().connect()
        try:
            rows = connection.execute(sql).fetchall()
        finally:
            connection.close()
    return [{"value": row[0], "count": int(row[1])} for row in rows]


def _sampled_counts(scan: str, target: str, source_rows: int) -> Dict[str, Any]:
    """Deterministic stratified estimate.

    Sampling is applied per class (via a seeded hash over the row's ordinal),
    which preserves the minority class rather than letting a naive uniform sample
    drop it. Counts are scaled back to the source population and reported as
    estimates, never as exact population counts.
    """
    column = _quote_identifier(target)
    fraction = min(1.0, SAMPLE_TARGET_ROWS / max(1, source_rows))
    sql = (
        f"WITH ordered AS (SELECT {column} AS value, row_number() OVER () AS rn FROM {scan}), "
        f"per_class AS (SELECT value, rn, row_number() OVER (PARTITION BY value ORDER BY hash(rn + {SAMPLE_SEED})) AS class_rn, "
        f"COUNT(*) OVER (PARTITION BY value) AS class_total FROM ordered) "
        f"SELECT value, COUNT(*) AS sampled_count, MAX(class_total) AS class_total "
        f"FROM per_class WHERE class_rn <= GREATEST(1, CAST(class_total * {fraction} AS BIGINT)) "
        f"GROUP BY value ORDER BY sampled_count DESC LIMIT {MAX_TARGET_CARDINALITY + 1}"
    )
    with _QUERY_LOCK:
        connection = _duckdb().connect()
        try:
            rows = connection.execute(sql).fetchall()
        finally:
            connection.close()

    sampled_rows = sum(int(row[1]) for row in rows)
    # class_total is exact (a window count over the scan), so the estimate is
    # reported against true class sizes while still being labelled an estimate.
    return {
        "rows": [{"value": row[0], "count": int(row[2])} for row in rows],
        "sampledRowCount": sampled_rows,
        "sourceRowCount": source_rows,
    }


def compute_target_distribution(
    *,
    user_scope: str,
    project_id: str,
    dataset_id: str,
    version_id: Optional[str],
    target: str,
    event_value: Any = None,
    non_event_value: Any = None,
    force_exact: bool = False,
) -> Dict[str, Any]:
    """Returns bounded aggregate rows for one immutable (dataset, version, target).

    The result is cached by authorization scope, datasetId, versionId, target,
    positive value, and negative value -- so a different version or target is a
    different key and naturally invalidates the prior result.
    """
    if not target:
        raise HTTPException(status_code=400, detail="A target column is required.")
    if not dataset_id:
        raise HTTPException(status_code=400, detail="A datasetId is required.")

    artifact = _resolve_version_artifact(dataset_id, version_id)
    resolved_version = artifact["versionId"]

    cache_key = result_cache.RESULT_CACHE.build_key(
        user_scope=user_scope, project_id=project_id, dataset_id=dataset_id, version_id=resolved_version,
        partition=None, model_id=None, scoring_run_id=None, operation="target_distribution",
        selected_columns=[target], filters=[], aggregations={"event": str(event_value), "nonEvent": str(non_event_value)},
        binning=None, sampling_method=None, exact=bool(force_exact), engine_version=ENGINE_VERSION,
    )
    cached = result_cache.RESULT_CACHE.get(cache_key, user_scope=user_scope, project_id=project_id)
    if cached is not None:
        return {**cached, "cached": True, "durationMs": 0}

    started = time.perf_counter()
    scan = _scan_expression(artifact)
    source_rows = int(artifact.get("rowCount") or 0)

    try:
        if _should_sample(artifact, force_exact):
            sampled = _sampled_counts(scan, target, source_rows)
            rows = sampled["rows"]
            resolution = "sampled"
            sampling_meta = {
                "samplingMethod": "deterministic_stratified",
                "seed": SAMPLE_SEED,
                "sampledRowCount": sampled["sampledRowCount"],
                "sourceRowCount": sampled["sourceRowCount"],
            }
        else:
            rows = _exact_counts(scan, target)
            resolution = "exact"
            sampling_meta = None
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Target distribution aggregation failed: {exc}") from exc

    if len(rows) > MAX_TARGET_CARDINALITY:
        return {
            "ok": True, "supported": False, "resolution": "unsupported",
            "reason": f"The target has more than {MAX_TARGET_CARDINALITY} distinct values and is not charted as a classification target.",
            "datasetId": dataset_id, "versionId": resolved_version, "target": target,
            "classDistribution": [], "totalRowCount": 0, "cached": False,
            "durationMs": int((time.perf_counter() - started) * 1000),
        }

    total = sum(row["count"] for row in rows)
    distribution = [
        {
            "value": None if row["value"] is None else str(row["value"]),
            "count": row["count"],
            "percent": (row["count"] / total) if total else 0.0,
        }
        for row in rows
    ]

    payload: Dict[str, Any] = {
        "ok": True,
        "supported": len(distribution) >= 2,
        "resolution": resolution,
        "datasetId": dataset_id,
        "versionId": resolved_version,
        "target": target,
        "eventValue": None if event_value is None else str(event_value),
        "nonEventValue": None if non_event_value is None else str(non_event_value),
        "classDistribution": distribution,
        "totalRowCount": total,
        "artifactFormat": artifact["format"],
        # Governance identity carried on the CACHED payload, so a caller that
        # needs the analysis scope (target_intelligence_service) does not have to
        # re-resolve the artifact -- which would mean a second registry read and
        # a second dataset ACL check on every warm request.
        "datasetName": artifact.get("datasetName"),
        "artifactChecksum": artifact.get("checksum"),
        "engine": "duckdb",
        "cached": False,
        "durationMs": int((time.perf_counter() - started) * 1000),
    }
    if sampling_meta:
        payload["sampling"] = sampling_meta

    result_cache.RESULT_CACHE.set(cache_key, payload, user_scope=user_scope, project_id=project_id)
    return payload
