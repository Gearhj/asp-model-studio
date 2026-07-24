"""Enterprise Analytical Data Plane -- typed, versioned query contract.

CONTRACT_VERSION governs response shape compatibility. Bump on any breaking
change to AnalyticalQueryResponse's field set or semantics.

Security note: AnalyticalQueryRequest.userId does NOT exist as a client-settable
field. The authenticated user is always resolved server-side from the session
(require_user), exactly like every other ATLAS endpoint -- see query_service.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

CONTRACT_VERSION = "1.0"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_query_id() -> str:
    return f"aq-{uuid.uuid4().hex[:16]}"


class SourceType(str, Enum):
    WORKSPACE = "workspace"
    REGISTERED = "registered"
    SCORING_SESSION = "scoring-session"
    EVALUATION_RESULT = "evaluation-result"
    INTERPRETATION_RESULT = "interpretation-result"
    DERIVED = "derived"
    SERVER_AGGREGATE = "server-aggregate"


class Partition(str, Enum):
    TRAIN = "train"
    TEST = "test"
    OOT = "oot"


class Operation(str, Enum):
    SCHEMA = "schema"
    ROW_COUNT = "row_count"
    COLUMN_PROFILE = "column_profile"
    HISTOGRAM = "histogram"
    QUANTILES = "quantiles"
    GROUPED_SUMMARY = "grouped_summary"
    CATEGORY_FREQUENCY = "category_frequency"
    SCATTER_SAMPLE = "scatter_sample"
    HEXBIN = "hexbin"
    THRESHOLD_CURVE = "threshold_curve"
    CONFUSION_MATRIX_AT_THRESHOLD = "confusion_matrix_at_threshold"
    REGRESSION_DIAGNOSTICS = "regression_diagnostics"
    RESIDUAL_DISTRIBUTION = "residual_distribution"
    QQ_POINTS = "qq_points"
    ERROR_BY_TARGET_BAND = "error_by_target_band"
    PREDICTION_DISTRIBUTION = "prediction_distribution"
    PSI = "psi"
    VSI = "vsi"
    TOP_OUTLIERS = "top_outliers"
    BOUNDED_ROWS = "bounded_rows"


class ApproximationPolicy(str, Enum):
    EXACT_REQUIRED = "exact_required"
    APPROXIMATE_PREFERRED = "approximate_preferred"
    APPROXIMATE_ALLOWED = "approximate_allowed"


class SampleMethod(str, Enum):
    NONE = "none"
    RANDOM = "random"
    STRATIFIED = "stratified"
    CLASS_STRATIFIED = "class_stratified"
    TARGET_BAND_STRATIFIED = "target_band_stratified"
    QUANTILE_PRESERVING = "quantile_preserving"
    RESERVOIR = "reservoir"
    TOP_N = "top_n"
    HEXBIN_DENSITY = "hexbin_density"


class QueryStatus(str, Enum):
    QUEUED = "queued"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class ExecutionEngine(str, Enum):
    METADATA = "metadata"
    DUCKDB = "duckdb"
    POLARS = "polars"
    PANDAS = "pandas"
    CACHE = "cache"
    SOURCE_PUSHDOWN = "source_pushdown"


class FilterOp(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    IS_NULL = "is_null"
    IS_NOT_NULL = "is_not_null"


class QueryFilter(BaseModel):
    column: str
    op: FilterOp
    value: Any = None


class SamplingRequest(BaseModel):
    method: SampleMethod = SampleMethod.NONE
    size: int = Field(default=2000, ge=1, le=50_000)
    seed: Optional[int] = None
    stratifyColumn: Optional[str] = None


class AnalyticalQueryRequest(BaseModel):
    """Client-supplied query. `userId` is deliberately absent -- see module docstring."""

    queryId: str = Field(default_factory=new_query_id)
    clientRequestId: Optional[str] = None
    projectId: str
    datasetId: Optional[str] = None
    versionId: Optional[str] = None
    sourceType: SourceType = SourceType.WORKSPACE
    partition: Optional[Partition] = None
    modelId: Optional[str] = None
    scoringRunId: Optional[str] = None
    operation: Operation
    selectedColumns: List[str] = Field(default_factory=list)
    filters: List[QueryFilter] = Field(default_factory=list)
    groupBy: List[str] = Field(default_factory=list)
    # Dual-purpose: for aggregate operations this maps column -> agg function name
    # (e.g. {"amount": "mean"}); for row-level operations it also carries small
    # scalar parameters the operation needs (targetColumn, predictionColumn,
    # positiveValue, threshold, metricColumn) -- Any, not str, because some of
    # those scalars are numeric/boolean, not text.
    aggregations: Dict[str, Any] = Field(default_factory=dict)
    binning: Optional[int] = Field(default=None, ge=2, le=200)
    quantiles: List[float] = Field(default_factory=list)
    # Wide-table schema browsing (operation="schema" only) -- server-side pagination/
    # search/type-filter so a 500+ column source never renders an eagerly-populated
    # dropdown in the browser (Visual Intelligence Production Integration, Phase C).
    offset: int = Field(default=0, ge=0)
    search: Optional[str] = None
    dtypeFilter: Optional[str] = None
    sampling: Optional[SamplingRequest] = None
    sorting: Optional[str] = None
    limit: int = Field(default=1000, ge=1, le=100_000)
    approximationPolicy: ApproximationPolicy = ApproximationPolicy.APPROXIMATE_ALLOWED
    timeoutSeconds: int = Field(default=10, ge=1, le=120)
    priority: int = Field(default=5, ge=1, le=9)


class AnalyticalQueryResponse(BaseModel):
    queryId: str
    status: QueryStatus
    contractVersion: str = CONTRACT_VERSION
    sourceIdentity: str = ""
    datasetId: Optional[str] = None
    versionId: Optional[str] = None
    projectId: str
    partition: Optional[Partition] = None
    modelId: Optional[str] = None
    scoringRunId: Optional[str] = None
    exact: bool = True
    approximate: bool = False
    sampled: bool = False
    sampleMethod: SampleMethod = SampleMethod.NONE
    sourceRowCount: Optional[int] = None
    rowsScanned: Optional[int] = None
    resultRowCount: Optional[int] = None
    columnsScanned: Optional[int] = None
    executionEngine: Optional[ExecutionEngine] = None
    pushdownApplied: bool = False
    cacheStatus: str = "miss"  # "hit" | "miss" | "not_cacheable"
    startedAt: str = Field(default_factory=now_iso)
    completedAt: Optional[str] = None
    durationMs: Optional[float] = None
    warnings: List[str] = Field(default_factory=list)
    resultSchema: List[Dict[str, str]] = Field(default_factory=list)
    result: Any = None
    continuationToken: Optional[str] = None
    error: Optional[str] = None
