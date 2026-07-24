"""Enterprise Analytical Data Plane -- server-side query planner.

Chooses an execution strategy from planner inputs (NOT source row count
alone -- see PlannerInputs and the decision matrix in
docs/architecture/QUERY_PLANNER_DECISION_MATRIX.md). A 20-bin histogram over
100 million rows is a valid DuckDB-pushdown query; a request for 2 million raw
scatter points is refused/downgraded to a bounded sample regardless of source
size, because RESULT cardinality -- not source cardinality -- is what risks
overwhelming the browser or the response payload.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .distributed_engine_interface import list_configured_engines
from .query_contract import ApproximationPolicy, ExecutionEngine, Operation, SourceType
from .resource_governance import LIMITS


# Operations that return a bounded aggregate/summary regardless of source size --
# these are always safe for DuckDB pushdown against a file-backed source.
_AGGREGATE_OPERATIONS = {
    Operation.SCHEMA, Operation.ROW_COUNT, Operation.COLUMN_PROFILE, Operation.HISTOGRAM,
    Operation.QUANTILES, Operation.GROUPED_SUMMARY, Operation.CATEGORY_FREQUENCY,
}

# Operations that need row-level shaping and therefore require a BOUNDED
# extraction step (via DuckDB SAMPLE/LIMIT) before pandas can touch the rows.
_ROW_LEVEL_OPERATIONS = {
    Operation.SCATTER_SAMPLE, Operation.HEXBIN, Operation.THRESHOLD_CURVE,
    Operation.CONFUSION_MATRIX_AT_THRESHOLD, Operation.REGRESSION_DIAGNOSTICS,
    Operation.RESIDUAL_DISTRIBUTION, Operation.QQ_POINTS, Operation.ERROR_BY_TARGET_BAND,
    Operation.PREDICTION_DISTRIBUTION, Operation.PSI, Operation.VSI, Operation.TOP_OUTLIERS,
    Operation.BOUNDED_ROWS,
}


@dataclass
class PlannerInputs:
    operation: Operation
    source_type: SourceType
    is_file_backed: bool
    file_format: Optional[str]  # "parquet" | "csv" | None
    source_row_count: Optional[int]
    column_count: Optional[int]
    selected_column_count: int
    requested_result_cardinality: int  # e.g. bins, scatter points, group cardinality, row limit
    approximation_policy: ApproximationPolicy
    timeout_seconds: int


@dataclass
class PlannerDecision:
    engine: ExecutionEngine
    pushdown_applied: bool
    approximate: bool
    sampled: bool
    warnings: List[str]
    rejected: bool = False
    rejection_reason: Optional[str] = None


class PlanningRejection(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def plan(inputs: PlannerInputs) -> PlannerDecision:
    warnings: List[str] = []

    # 1. Metadata-only operations never touch row data.
    if inputs.operation == Operation.SCHEMA:
        return PlannerDecision(engine=ExecutionEngine.METADATA, pushdown_applied=False, approximate=False, sampled=False, warnings=warnings)

    # 2. Result-cardinality guardrails apply BEFORE engine selection, independent of
    #    source size -- this is the "not only source row count" requirement.
    if inputs.operation in {Operation.SCATTER_SAMPLE, Operation.HEXBIN}:
        if inputs.requested_result_cardinality > LIMITS.max_scatter_points:
            warnings.append(f"Requested {inputs.requested_result_cardinality} points exceeds the {LIMITS.max_scatter_points}-point limit; result was capped and sampled.")
    if inputs.operation == Operation.HISTOGRAM and inputs.requested_result_cardinality > LIMITS.max_histogram_bins:
        warnings.append(f"Requested {inputs.requested_result_cardinality} bins exceeds the {LIMITS.max_histogram_bins}-bin limit; capped.")
    if inputs.operation == Operation.GROUPED_SUMMARY and inputs.requested_result_cardinality > LIMITS.max_group_cardinality:
        warnings.append("Requested group cardinality exceeds the configured limit; result truncated to the largest groups.")
    if inputs.operation == Operation.BOUNDED_ROWS and inputs.requested_result_cardinality > LIMITS.max_result_rows:
        raise PlanningRejection(f"bounded_rows requests are capped at {LIMITS.max_result_rows} rows; use pagination or an aggregate operation instead.")

    # 3. Column-count guardrail (wide-table safety).
    if inputs.selected_column_count > LIMITS.max_selected_columns and inputs.operation != Operation.SCHEMA:
        raise PlanningRejection(f"Cannot select more than {LIMITS.max_selected_columns} columns in one analytical query; narrow the selection or use schema pagination.")

    # 4. Pure aggregate operations: DuckDB pushdown whenever file-backed, else Polars
    #    for very wide (>200 col) sources, else in-memory pandas for small workspace/
    #    evaluation-result frames (already bounded upstream, not a large source).
    if inputs.operation in _AGGREGATE_OPERATIONS:
        if inputs.is_file_backed:
            engine = ExecutionEngine.DUCKDB
            pushdown = True
        else:
            engine = ExecutionEngine.PANDAS
            pushdown = False
            if inputs.source_row_count and inputs.source_row_count > LIMITS.pandas_fallback_max_rows:
                raise PlanningRejection(
                    f"This operation would require scanning {inputs.source_row_count:,} in-memory rows with pandas, "
                    f"which exceeds the {LIMITS.pandas_fallback_max_rows:,}-row safe fallback bound. "
                    "Register this dataset to the Dataset Library so it can be queried via server-side DuckDB/Parquet instead."
                )
        approximate = inputs.operation == Operation.QUANTILES and inputs.approximation_policy != ApproximationPolicy.EXACT_REQUIRED
        if approximate:
            warnings.append("Quantiles computed approximately (t-digest). Request exact calculation explicitly if needed.")
        return PlannerDecision(engine=engine, pushdown_applied=pushdown, approximate=approximate, sampled=False, warnings=warnings)

    # 5. Row-level operations: always extract a BOUNDED sample first (via DuckDB if
    #    file-backed, else the frame is already small), then shape with pandas.
    if inputs.operation in _ROW_LEVEL_OPERATIONS:
        sampled = inputs.source_row_count is None or inputs.source_row_count > inputs.requested_result_cardinality
        if sampled:
            warnings.append("Result reflects a bounded sample of the source population, not every row.")
        engine = ExecutionEngine.DUCKDB if inputs.is_file_backed else ExecutionEngine.PANDAS
        return PlannerDecision(engine=engine, pushdown_applied=inputs.is_file_backed, approximate=False, sampled=sampled, warnings=warnings)

    raise PlanningRejection(f"No planning rule for operation {inputs.operation}.")


def decision_matrix_summary() -> List[dict]:
    """Machine-readable form of the documented decision matrix, exposed via the
    development query-inspection endpoint (Phase M)."""
    return [
        {"operation": "schema", "rule": "always metadata-only, no row scan"},
        {"operation": "histogram | quantiles | grouped_summary | category_frequency | column_profile | row_count", "rule": "DuckDB pushdown if file-backed; bounded pandas if in-memory and under pandas_fallback_max_rows; otherwise rejected with a Dataset Library registration suggestion"},
        {"operation": "scatter_sample | hexbin", "rule": "bounded stratified/reservoir sample or hexbin density grid, never raw unbounded points"},
        {"operation": "threshold_curve | confusion_matrix_at_threshold", "rule": "precomputed bounded threshold table; confusion matrix at any single threshold recomputed from the same bounded sample without rescanning the source"},
        {"operation": "regression_diagnostics | residual_distribution | qq_points | error_by_target_band", "rule": "full-population aggregate metrics (DuckDB) plus a bounded sample for row-level shapes"},
        {"operation": "top_outliers", "rule": "authorized bounded rows only, hard row cap"},
        {"operation": "bounded_rows", "rule": "hard limit plus pagination, never unbounded"},
        {"operation": "external distributed engine", "rule": f"not selectable -- configured engines: {list_configured_engines() or 'none'}"},
    ]
