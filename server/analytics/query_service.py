"""Enterprise Analytical Data Plane -- query orchestration and async lifecycle.

Mirrors the existing TrainingJobService pattern (server/training/training_job_service.py):
an in-process dict of job records keyed by queryId, a threading.Event per job for
best-effort cancellation, and a background thread for operations expensive enough
to warrant not blocking the request. Fast/bounded operations (the large majority,
by design -- see the planner) complete inline within the same request instead of
round-tripping through queued/polling for no reason.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Dict, Optional

import pandas as pd

from ..security.security_store import audit_event
from . import result_cache
from .artifact_resolver import resolve_source
from .engines import duckdb_engine, pandas_engine, polars_engine
from .query_contract import (
    AnalyticalQueryRequest, AnalyticalQueryResponse, ExecutionEngine, Operation,
    QueryStatus, SourceType, now_iso,
)
from .query_planner import PlannerInputs, PlanningRejection, plan
from .resource_governance import CONCURRENCY, LIMITS, ResourceRejection

_INLINE_OPERATIONS = {
    Operation.SCHEMA, Operation.ROW_COUNT, Operation.COLUMN_PROFILE, Operation.HISTOGRAM,
    Operation.QUANTILES, Operation.GROUPED_SUMMARY, Operation.CATEGORY_FREQUENCY,
    Operation.THRESHOLD_CURVE, Operation.CONFUSION_MATRIX_AT_THRESHOLD, Operation.PREDICTION_DISTRIBUTION,
    Operation.RESIDUAL_DISTRIBUTION, Operation.QQ_POINTS, Operation.ERROR_BY_TARGET_BAND,
    Operation.REGRESSION_DIAGNOSTICS, Operation.BOUNDED_ROWS, Operation.PSI, Operation.VSI, Operation.TOP_OUTLIERS,
}


class _QueryJobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._cancel_events: Dict[str, threading.Event] = {}

    def create(self, query_id: str, user_id: str, project_id: str) -> None:
        with self._lock:
            self._jobs[query_id] = {"status": QueryStatus.QUEUED, "userId": user_id, "projectId": project_id, "createdAt": now_iso()}
            self._cancel_events[query_id] = threading.Event()

    def update(self, query_id: str, **fields: Any) -> None:
        with self._lock:
            if query_id in self._jobs:
                self._jobs[query_id].update(fields)

    def get(self, query_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            job = self._jobs.get(query_id)
            return dict(job) if job else None

    def cancel(self, query_id: str, user_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(query_id)
            if not job or job.get("userId") != user_id:
                return False
            event = self._cancel_events.get(query_id)
            if event:
                event.set()
            if job.get("status") in (QueryStatus.QUEUED, QueryStatus.PLANNING, QueryStatus.RUNNING):
                job["status"] = QueryStatus.CANCELLED
            return True

    def is_cancelled(self, query_id: str) -> bool:
        event = self._cancel_events.get(query_id)
        return bool(event and event.is_set())


JOBS = _QueryJobStore()


def _in_memory_schema_paginated(frame: pd.DataFrame, request: AnalyticalQueryRequest) -> Dict[str, Any]:
    """In-memory equivalent of polars_engine.get_schema_paginated for workspace/
    evaluation-result/scoring-session (frame-resident) sources, so wide-table
    server-side search/pagination is not exclusive to file-backed Parquet
    sources -- an in-progress project's workspace dataset gets the same
    no-eager-500-column-dropdown guarantee."""
    columns = [{"name": str(c), "dtype": str(frame[c].dtype)} for c in frame.columns]
    if request.search:
        needle = request.search.lower()
        columns = [c for c in columns if needle in c["name"].lower()]
    if request.dtypeFilter:
        needle = request.dtypeFilter.lower()
        columns = [c for c in columns if needle in c["dtype"].lower()]
    total = len(columns)
    limit = min(request.limit or 100, 500)
    page = columns[request.offset: request.offset + limit]
    return {"columns": page, "totalColumns": total, "offset": request.offset, "limit": limit}


def _engine_frame_operation(engine: ExecutionEngine, request: AnalyticalQueryRequest, resolved) -> tuple[Any, Dict[str, Any]]:
    """Runs one operation against the chosen engine. Returns (result_payload, extra_meta)."""
    warnings: list[str] = []

    if request.operation == Operation.SCHEMA:
        if resolved.file_path is not None:
            page = polars_engine.get_schema_paginated(
                resolved.file_path, resolved.file_format,
                offset=request.offset, limit=request.limit or 100,
                search=request.search, dtype_filter=request.dtypeFilter,
            )
            return page, {"columnsScanned": page["totalColumns"]}
        return _in_memory_schema_paginated(resolved.frame, request), {"columnsScanned": len(resolved.frame.columns)}

    if engine == ExecutionEngine.DUCKDB:
        conn = duckdb_engine.open_bounded_connection()
        try:
            duckdb_engine.register_source(conn, resolved.file_path, resolved.file_format, resolved.frame)
            if request.operation == Operation.ROW_COUNT:
                return {"rowCount": duckdb_engine.get_row_count(conn, request.filters)}, {}
            if request.operation == Operation.COLUMN_PROFILE:
                column = request.selectedColumns[0] if request.selectedColumns else None
                if not column:
                    raise ValueError("column_profile requires selectedColumns[0].")
                return duckdb_engine.column_profile(conn, column), {}
            if request.operation == Operation.HISTOGRAM:
                column = request.selectedColumns[0] if request.selectedColumns else None
                if not column:
                    raise ValueError("histogram requires selectedColumns[0].")
                positive_value = request.aggregations.get("positiveValue") if request.aggregations else None
                result = duckdb_engine.histogram(conn, column, request.binning or 20, request.filters, target=request.aggregations.get("targetColumn"), positive_value=positive_value)
                return result, {}
            if request.operation == Operation.QUANTILES:
                column = request.selectedColumns[0] if request.selectedColumns else None
                exact = request.approximationPolicy.value == "exact_required"
                values = duckdb_engine.quantiles(conn, column, request.quantiles or [0.25, 0.5, 0.75], exact, request.filters)
                return {"quantiles": dict(zip(request.quantiles or [0.25, 0.5, 0.75], values))}, {}
            if request.operation == Operation.GROUPED_SUMMARY:
                return duckdb_engine.grouped_summary(conn, request.groupBy, request.aggregations, request.filters), {}
            if request.operation == Operation.CATEGORY_FREQUENCY:
                column = request.selectedColumns[0] if request.selectedColumns else None
                return duckdb_engine.category_frequency(conn, column, request.filters, top_n=request.limit or 50), {}

            # Row-level operations: extract a bounded sample first, then shape with pandas.
            sample_size = min(request.sampling.size if request.sampling else request.limit, LIMITS.max_result_rows)
            bounded = duckdb_engine.bounded_sql_sample(conn, request.selectedColumns or None, request.filters, sample_size, seed=(request.sampling.seed if request.sampling else None))
            return _shape_row_level(request, bounded), {"rowsScanned": duckdb_engine.get_row_count(conn, request.filters)}
        finally:
            conn.close()

    # In-memory pandas path (workspace / evaluation-result sources).
    frame = resolved.frame
    if request.operation == Operation.ROW_COUNT:
        return {"rowCount": int(len(frame))}, {}
    if request.operation == Operation.COLUMN_PROFILE:
        column = request.selectedColumns[0] if request.selectedColumns else None
        series = frame[column]
        return {
            "column": column, "totalCount": int(len(series)), "nullCount": int(series.isna().sum()),
            "minimum": series.min() if pd.api.types.is_numeric_dtype(series) else None,
            "maximum": series.max() if pd.api.types.is_numeric_dtype(series) else None,
            "mean": float(series.mean()) if pd.api.types.is_numeric_dtype(series) else None,
            "std": float(series.std()) if pd.api.types.is_numeric_dtype(series) else None,
            "median": float(series.median()) if pd.api.types.is_numeric_dtype(series) else None,
        }, {}
    if request.operation == Operation.HISTOGRAM:
        column = request.selectedColumns[0] if request.selectedColumns else None
        import numpy as np
        values = frame[column].astype(float).dropna()
        if values.empty:
            return {"bins": [], "minimum": None, "maximum": None}, {}
        counts, edges = np.histogram(values, bins=min(request.binning or 20, LIMITS.max_histogram_bins))
        return {"bins": [{"x0": float(edges[i]), "x1": float(edges[i + 1]), "count": int(counts[i])} for i in range(len(counts))], "minimum": float(edges[0]), "maximum": float(edges[-1])}, {}
    if request.operation == Operation.QUANTILES:
        column = request.selectedColumns[0] if request.selectedColumns else None
        from . import sampling as sampling_mod
        exact = request.approximationPolicy.value == "exact_required"
        values = sampling_mod.exact_quantiles(frame[column], request.quantiles or [0.25, 0.5, 0.75]) if exact else sampling_mod.approximate_quantiles(frame[column], request.quantiles or [0.25, 0.5, 0.75])
        return {"quantiles": dict(zip(request.quantiles or [0.25, 0.5, 0.75], values))}, {}
    if request.operation == Operation.GROUPED_SUMMARY:
        return _pandas_grouped_summary(frame, request.groupBy, request.aggregations), {}
    if request.operation == Operation.CATEGORY_FREQUENCY:
        column = request.selectedColumns[0] if request.selectedColumns else None
        return _pandas_category_frequency(frame, column, request.limit or 50), {}
    return _shape_row_level(request, frame), {"rowsScanned": int(len(frame))}


def _pandas_grouped_summary(frame: pd.DataFrame, group_by: list, aggregations: Dict[str, str]) -> Dict[str, Any]:
    allowed_aggs = {"mean": "mean", "sum": "sum", "count": "count", "min": "min", "max": "max", "std": "std"}
    group_cols = [c for c in group_by[:5] if c in frame.columns]
    if not group_cols:
        return {"rows": [], "cardinalityCapped": False}
    # `aggregations` is a dual-purpose bag (column->aggfunc mapping for grouped
    # summaries, but also scalar params like positiveValue/threshold for
    # row-level operations) -- defensively skip any non-string value here
    # rather than erroring, since a single request should never mix both uses,
    # but nothing prevents a caller from doing so.
    agg_map = {
        col: allowed_aggs[agg.lower()] for col, agg in list(aggregations.items())[:10]
        if isinstance(agg, str) and agg.lower() in allowed_aggs and col in frame.columns
    }
    grouped = frame.groupby(group_cols, observed=True)
    result = grouped.agg(agg_map) if agg_map else grouped.size().to_frame("row_count")
    result["row_count"] = grouped.size()
    result = result.reset_index()
    result.columns = [f"{c[0]}_{c[1]}" if isinstance(c, tuple) and c[1] else (c[0] if isinstance(c, tuple) else c) for c in result.columns]
    result = result.sort_values("row_count", ascending=False).head(LIMITS.max_group_cardinality)
    truncated = len(result) >= LIMITS.max_group_cardinality
    return {"rows": result.to_dict(orient="records"), "cardinalityCapped": truncated}


def _pandas_category_frequency(frame: pd.DataFrame, column: Optional[str], top_n: int) -> Dict[str, Any]:
    if not column or column not in frame.columns:
        return {"categories": [], "totalRows": 0, "cardinalityCapped": False}
    top_n = min(top_n, LIMITS.max_group_cardinality)
    counts = frame[column].value_counts().head(top_n)
    return {
        "categories": [{"value": value, "count": int(count)} for value, count in counts.items()],
        "totalRows": int(len(frame)), "cardinalityCapped": len(counts) >= top_n,
    }


def _shape_row_level(request: AnalyticalQueryRequest, bounded: pd.DataFrame) -> Any:
    op = request.operation
    target = request.aggregations.get("targetColumn", "actual")
    prediction_col = request.aggregations.get("predictionColumn", "prediction")
    positive_value = request.aggregations.get("positiveValue", 1)

    if op == Operation.REGRESSION_DIAGNOSTICS:
        return pandas_engine.regression_diagnostics(bounded, target, prediction_col)
    if op == Operation.RESIDUAL_DISTRIBUTION:
        return pandas_engine.residual_distribution(bounded, target, prediction_col, bins=request.binning or 20)
    if op == Operation.QQ_POINTS:
        return {"points": pandas_engine.qq_points(bounded, target, prediction_col)}
    if op == Operation.ERROR_BY_TARGET_BAND:
        return pandas_engine.error_by_target_band(bounded, target, prediction_col, bands=request.binning or 8)
    if op == Operation.THRESHOLD_CURVE:
        return pandas_engine.threshold_curve(bounded, target, prediction_col, num_points=request.binning or 50, positive_value=positive_value)
    if op == Operation.CONFUSION_MATRIX_AT_THRESHOLD:
        threshold = float(request.aggregations.get("threshold", 0.5))
        return pandas_engine.confusion_matrix_at_threshold(bounded, target, prediction_col, threshold, positive_value=positive_value)
    if op == Operation.PREDICTION_DISTRIBUTION:
        return pandas_engine.prediction_distribution(bounded, prediction_col, bins=request.binning or 20)
    if op in (Operation.SCATTER_SAMPLE, Operation.BOUNDED_ROWS):
        return {"rows": bounded.head(request.limit).to_dict(orient="records"), "rowCount": len(bounded)}
    if op == Operation.HEXBIN:
        from . import sampling as sampling_mod
        x_col = request.selectedColumns[0] if len(request.selectedColumns) > 0 else target
        y_col = request.selectedColumns[1] if len(request.selectedColumns) > 1 else prediction_col
        return sampling_mod.hexbin_density(bounded[x_col], bounded[y_col], grid_size=request.binning or 30)
    if op == Operation.TOP_OUTLIERS:
        metric = request.aggregations.get("metricColumn", "residual")
        return {"rows": pandas_engine.top_outliers(bounded, metric, n=request.limit).to_dict(orient="records")}
    if op in (Operation.PSI, Operation.VSI):
        # PSI/VSI need TWO resolved sources (a baseline partition and a comparison
        # partition). ATLAS's TEST/OOT scoring results have no backend retrieval
        # endpoint today (Visual Intelligence Foundation Phase 1's documented Known
        # Constraint #1/#2, unchanged by this phase) -- so a second durable source to
        # compare against is not yet resolvable via this contract. pandas_engine.psi()/
        # vsi() ARE implemented and unit-tested against two explicit in-memory series;
        # wiring them through this single-source query contract is deferred honestly
        # rather than faked with a single-source workaround. See the ADR's "Known
        # limitations" section.
        raise ValueError(
            "psi/vsi require an explicit comparison partition, which is not yet resolvable through this "
            "single-source query contract (see the ADR's ephemeral-scoring-result limitation). "
            "The underlying pandas_engine.psi()/vsi() functions are implemented and tested directly."
        )
    raise ValueError(f"Unsupported row-level operation: {op}")


def execute_query(user: Dict[str, Any], request: AnalyticalQueryRequest) -> AnalyticalQueryResponse:
    """Synchronous execution path -- authorize, plan, execute, cache, audit. Used
    both for inline (fast) operations and inside the background thread for queued
    (heavy) operations."""
    started = time.monotonic()
    warnings: list[str] = []
    user_id = str(user.get("userId") or "anonymous")

    try:
        resolved = resolve_source(user, request)
    except Exception as exc:
        audit_event("analytics.query.denied", "project", request.projectId, "denied", user_id=user_id, reason=str(exc))
        raise

    planner_inputs = PlannerInputs(
        operation=request.operation, source_type=request.sourceType,
        is_file_backed=resolved.file_path is not None, file_format=resolved.file_format,
        source_row_count=None if resolved.frame is None else int(len(resolved.frame)),
        column_count=None, selected_column_count=len(request.selectedColumns),
        requested_result_cardinality=request.binning or request.limit or 20,
        approximation_policy=request.approximationPolicy, timeout_seconds=request.timeoutSeconds,
    )
    decision = plan(planner_inputs)
    warnings.extend(decision.warnings)

    # Schema browsing's pagination/search/type-filter parameters are folded into the
    # cache-key aggregations bag (rather than widening build_key's fixed signature)
    # so two different schema pages/searches never collide on the same cache entry.
    cache_key_aggregations = dict(request.aggregations)
    if request.operation == Operation.SCHEMA:
        cache_key_aggregations = {**cache_key_aggregations, "_offset": request.offset, "_search": request.search, "_dtypeFilter": request.dtypeFilter}
    cache_key = result_cache.RESULT_CACHE.build_key(
        user_scope=user_id, project_id=request.projectId, dataset_id=resolved.dataset_id, version_id=resolved.version_id,
        partition=request.partition.value if request.partition else None, model_id=request.modelId, scoring_run_id=request.scoringRunId,
        operation=request.operation.value, selected_columns=request.selectedColumns,
        filters=[f.model_dump() for f in request.filters], aggregations=cache_key_aggregations,
        binning=request.binning, sampling_method=(request.sampling.method.value if request.sampling else None),
        exact=not decision.approximate, engine_version="1.0",
    )
    cached = result_cache.RESULT_CACHE.get(cache_key, user_scope=user_id, project_id=request.projectId)
    cache_status = "hit" if cached is not None else "miss"

    if cached is not None:
        result_payload = cached
        extra_meta: Dict[str, Any] = {}
    else:
        result_payload, extra_meta = _engine_frame_operation(decision.engine, request, resolved)
        # Immutable, write-once sources are reusable across identical requests; workspace/eval
        # results are not (they can change without the source identity changing).
        cacheable = resolved.source_type in (SourceType.REGISTERED, SourceType.SCORING_SESSION)
        result_cache.RESULT_CACHE.set(cache_key, result_payload, user_scope=user_id, project_id=request.projectId, cacheable=cacheable)

    duration_ms = (time.monotonic() - started) * 1000
    response = AnalyticalQueryResponse(
        queryId=request.queryId, status=QueryStatus.COMPLETED, sourceIdentity=resolved.source_identity,
        datasetId=resolved.dataset_id, versionId=resolved.version_id, projectId=request.projectId,
        partition=request.partition, modelId=request.modelId, scoringRunId=request.scoringRunId,
        exact=not decision.approximate, approximate=decision.approximate, sampled=decision.sampled,
        sampleMethod=(request.sampling.method if request.sampling and decision.sampled else "none"),
        sourceRowCount=planner_inputs.source_row_count, rowsScanned=extra_meta.get("rowsScanned"),
        resultRowCount=(len(result_payload.get("rows", [])) if isinstance(result_payload, dict) and "rows" in result_payload else None),
        columnsScanned=extra_meta.get("columnsScanned"), executionEngine=decision.engine, pushdownApplied=decision.pushdown_applied,
        cacheStatus=cache_status, completedAt=now_iso(), durationMs=duration_ms, warnings=warnings, result=result_payload,
    )

    audit_event(
        "analytics.query.executed", "project", request.projectId, "success", user_id=user_id,
        metadata={
            "queryId": request.queryId, "operation": request.operation.value, "engine": decision.engine.value,
            "pushdownApplied": decision.pushdown_applied, "exact": not decision.approximate, "sampled": decision.sampled,
            "sampleMethod": (request.sampling.method.value if request.sampling and decision.sampled else None),
            "durationMs": duration_ms, "cacheStatus": cache_status, "datasetId": resolved.dataset_id, "versionId": resolved.version_id,
        },
    )
    return response


def run_async(user: Dict[str, Any], request: AnalyticalQueryRequest) -> None:
    query_id = request.queryId
    JOBS.update(query_id, status=QueryStatus.RUNNING)
    try:
        if JOBS.is_cancelled(query_id):
            JOBS.update(query_id, status=QueryStatus.CANCELLED)
            return
        response = execute_query(user, request)
        if JOBS.is_cancelled(query_id):
            JOBS.update(query_id, status=QueryStatus.CANCELLED)
            return
        JOBS.update(query_id, status=QueryStatus.COMPLETED, response=response.model_dump())
    except PlanningRejection as exc:
        JOBS.update(query_id, status=QueryStatus.REJECTED, error=exc.reason)
    except ResourceRejection as exc:
        JOBS.update(query_id, status=QueryStatus.REJECTED, error=exc.reason)
    except Exception as exc:  # noqa: BLE001 -- convert any engine failure into a job-visible failure, never a hung "running" job
        JOBS.update(query_id, status=QueryStatus.FAILED, error=str(exc), traceback=traceback.format_exc(limit=5))


def is_heavy(request: AnalyticalQueryRequest) -> bool:
    """Heuristic for the async-vs-inline split -- row-level operations against a
    file-backed (potentially enterprise-scale) source are the only ones expected
    to take long enough to warrant not blocking the request thread."""
    return request.operation not in _INLINE_OPERATIONS or request.sourceType == SourceType.REGISTERED and request.operation in (
        Operation.SCATTER_SAMPLE, Operation.HEXBIN, Operation.TOP_OUTLIERS,
    )
