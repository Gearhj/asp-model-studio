"""Enterprise Analytical Data Plane -- server-side DuckDB adapter.

DuckDB is the primary engine for SQL-shaped aggregation (histogram, quantiles,
grouped summaries, category frequency, schema, row count) because it can scan
a Parquet or CSV file directly -- column pruning and predicate pushdown happen
inside DuckDB's own scanner, so a multi-GB source file is never materialized
in Python process memory. It is also used to pull a BOUNDED sample or
aggregate from a large source before handing that already-small result to
pandas for row-level statistical shaping (regression diagnostics, threshold
curves, etc.) -- pandas never touches the full source for those operations
either. See query_planner.py for the routing decision and
docs/architecture/EXECUTION_ENGINE_GUIDE.md for the full rationale.

Security: every query built here uses DuckDB's own parameter binding for
user-controlled VALUES (filter thresholds, category values). Column/table
identifiers are never taken from arbitrary client text -- selected_columns
and group_by are validated against the resolved source's own schema before
being interpolated as identifiers (SQL does not support parameterized
identifiers), and every identifier is double-quote-escaped.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import duckdb
import pandas as pd

from ..query_contract import QueryFilter, FilterOp
from ..resource_governance import LIMITS

_IDENTIFIER_SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .\-]*$")


def quote_identifier(name: str) -> str:
    if not _IDENTIFIER_SAFE.match(name):
        raise ValueError(f"Unsafe column identifier rejected: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def open_bounded_connection() -> duckdb.DuckDBPyConnection:
    """A fresh, short-lived connection per query (per-query lifecycle, not a shared
    global connection) with memory/thread limits from resource_governance.py applied
    immediately -- never an unbounded default connection."""
    conn = duckdb.connect(":memory:")
    conn.execute(f"SET memory_limit='{LIMITS.duckdb_memory_limit_mb}MB'")
    conn.execute(f"SET threads TO {LIMITS.duckdb_thread_limit}")
    conn.execute("SET autoinstall_known_extensions = false")
    conn.execute("SET autoload_known_extensions = false")
    # NOTE: local file reads remain enabled -- this connection legitimately needs to
    # scan artifact-root-resolved Parquet/CSV files. The security boundary against
    # arbitrary file access is enforced upstream, in artifact_resolver.py's
    # _within_artifact_root() check, BEFORE a path ever reaches this connection --
    # no path from any less-trusted source is ever passed to register_source().
    # What IS disabled here: any extension auto-install/auto-load (no remote
    # extension code can be pulled in), so this connection can only do what
    # DuckDB's built-in engine supports, never anything an extension would add
    # (e.g. httpfs for remote URLs).
    return conn


def register_source(conn: duckdb.DuckDBPyConnection, file_path: Optional[Path], file_format: Optional[str], frame: Optional[pd.DataFrame]) -> str:
    """Registers exactly one source as the view `source`. File-backed sources are
    scanned (read_parquet/read_csv_auto), never fully loaded before scanning; an
    in-memory pandas frame (workspace/evaluation-result) is registered as-is since
    it is already bounded by upload/training-run limits."""
    if frame is not None:
        conn.register("source_frame", frame)
        conn.execute("CREATE VIEW source AS SELECT * FROM source_frame")
        return "source"
    if file_path is None:
        raise ValueError("No file path or frame provided to register_source.")
    if file_format == "parquet":
        conn.execute(f"CREATE VIEW source AS SELECT * FROM read_parquet('{file_path.as_posix()}')")
    else:
        conn.execute(f"CREATE VIEW source AS SELECT * FROM read_csv_auto('{file_path.as_posix()}', sample_size=-1)")
    return "source"


def _filter_clause(filters: Sequence[QueryFilter], params: List[Any]) -> str:
    clauses = []
    op_sql = {
        FilterOp.EQ: "=", FilterOp.NEQ: "!=", FilterOp.GT: ">", FilterOp.GTE: ">=",
        FilterOp.LT: "<", FilterOp.LTE: "<=",
    }
    for f in filters:
        col = quote_identifier(f.column)
        if f.op == FilterOp.IS_NULL:
            clauses.append(f"{col} IS NULL")
        elif f.op == FilterOp.IS_NOT_NULL:
            clauses.append(f"{col} IS NOT NULL")
        elif f.op == FilterOp.IN:
            values = f.value if isinstance(f.value, list) else [f.value]
            placeholders = ",".join(["?"] * len(values))
            clauses.append(f"{col} IN ({placeholders})")
            params.extend(values)
        elif f.op in op_sql:
            clauses.append(f"{col} {op_sql[f.op]} ?")
            params.append(f.value)
    return (" WHERE " + " AND ".join(clauses)) if clauses else ""


def get_schema(conn: duckdb.DuckDBPyConnection) -> List[Dict[str, str]]:
    rows = conn.execute("DESCRIBE SELECT * FROM source").fetchall()
    return [{"name": r[0], "dtype": r[1]} for r in rows]


def get_row_count(conn: duckdb.DuckDBPyConnection, filters: Sequence[QueryFilter]) -> int:
    params: List[Any] = []
    clause = _filter_clause(filters, params)
    return int(conn.execute(f"SELECT COUNT(*) FROM source{clause}", params).fetchone()[0])


def column_profile(conn: duckdb.DuckDBPyConnection, column: str) -> Dict[str, Any]:
    col = quote_identifier(column)
    row = conn.execute(
        f"SELECT COUNT(*) AS n, COUNT({col}) AS non_null, "
        f"MIN({col}) AS min_v, MAX({col}) AS max_v, "
        f"AVG(TRY_CAST({col} AS DOUBLE)) AS mean_v, STDDEV_SAMP(TRY_CAST({col} AS DOUBLE)) AS std_v, "
        f"APPROX_QUANTILE(TRY_CAST({col} AS DOUBLE), 0.5) AS median_v "
        f"FROM source"
    ).fetchone()
    n, non_null, min_v, max_v, mean_v, std_v, median_v = row
    return {
        "column": column, "totalCount": int(n), "nullCount": int(n) - int(non_null),
        "minimum": min_v, "maximum": max_v, "mean": mean_v, "std": std_v, "median": median_v,
    }


def histogram(conn: duckdb.DuckDBPyConnection, column: str, bins: int, filters: Sequence[QueryFilter], target: Optional[str] = None, positive_value: Any = None) -> Dict[str, Any]:
    bins = min(bins, LIMITS.max_histogram_bins)
    col = quote_identifier(column)
    params: List[Any] = []
    clause = _filter_clause(filters, params)
    bounds = conn.execute(f"SELECT MIN(TRY_CAST({col} AS DOUBLE)), MAX(TRY_CAST({col} AS DOUBLE)) FROM source{clause}", params).fetchone()
    lo, hi = bounds[0], bounds[1]
    if lo is None or hi is None:
        return {"bins": [], "minimum": None, "maximum": None}
    if lo == hi:
        hi = lo + 1
    width = (hi - lo) / bins
    target_expr = ""
    if target and positive_value is not None:
        target_col = quote_identifier(target)
        target_expr = f", AVG(CASE WHEN {target_col} = ? THEN 1.0 ELSE 0.0 END) AS target_rate"
        params.append(positive_value)
    elif target:
        target_col = quote_identifier(target)
        target_expr = f", AVG(TRY_CAST({target_col} AS DOUBLE)) AS avg_target"
    sql = (
        f"SELECT LEAST({bins - 1}, GREATEST(0, CAST((TRY_CAST({col} AS DOUBLE) - ?) / ? AS INTEGER))) AS bin_index, "
        f"COUNT(*) AS n{target_expr} FROM source{clause} AND {col} IS NOT NULL GROUP BY 1 ORDER BY 1"
        if clause else
        f"SELECT LEAST({bins - 1}, GREATEST(0, CAST((TRY_CAST({col} AS DOUBLE) - ?) / ? AS INTEGER))) AS bin_index, "
        f"COUNT(*) AS n{target_expr} FROM source WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY 1"
    )
    bin_params = [lo, width] + params
    rows = conn.execute(sql, bin_params).fetchall()
    by_index = {r[0]: r for r in rows}
    result_bins = []
    for i in range(bins):
        r = by_index.get(i)
        entry = {"x0": lo + i * width, "x1": lo + (i + 1) * width, "count": int(r[1]) if r else 0}
        if target and r and len(r) > 2:
            entry["targetRate" if positive_value is not None else "avgTarget"] = r[2]
        result_bins.append(entry)
    return {"bins": result_bins, "minimum": lo, "maximum": hi}


def quantiles(conn: duckdb.DuckDBPyConnection, column: str, qs: List[float], exact: bool, filters: Sequence[QueryFilter]) -> List[Optional[float]]:
    col = quote_identifier(column)
    params: List[Any] = []
    clause = _filter_clause(filters, params)
    func = "QUANTILE_CONT" if exact else "APPROX_QUANTILE"
    results = []
    for q in qs:
        row = conn.execute(f"SELECT {func}(TRY_CAST({col} AS DOUBLE), {float(q)}) FROM source{clause}", params).fetchone()
        results.append(row[0] if row else None)
    return results


def grouped_summary(conn: duckdb.DuckDBPyConnection, group_by: List[str], aggregations: Dict[str, Any], filters: Sequence[QueryFilter]) -> Dict[str, Any]:
    allowed_aggs = {"mean": "AVG", "sum": "SUM", "count": "COUNT", "min": "MIN", "max": "MAX", "std": "STDDEV_SAMP"}
    group_cols = [quote_identifier(c) for c in group_by[:5]]
    select_aggs = []
    for col, agg in list(aggregations.items())[:10]:
        # `aggregations` is a dual-purpose bag (column->aggfunc mapping here, but
        # also scalar params like positiveValue/threshold for row-level operations)
        # -- skip non-string values defensively rather than erroring.
        if not isinstance(agg, str):
            continue
        agg_fn = allowed_aggs.get(agg.lower())
        if not agg_fn:
            continue
        select_aggs.append(f"{agg_fn}(TRY_CAST({quote_identifier(col)} AS DOUBLE)) AS {quote_identifier(f'{col}_{agg}')}")
    params: List[Any] = []
    clause = _filter_clause(filters, params)
    select_clause = ", ".join(group_cols + select_aggs + ["COUNT(*) AS row_count"])
    group_clause = f" GROUP BY {', '.join(str(i + 1) for i in range(len(group_cols)))}" if group_cols else ""
    sql = f"SELECT {select_clause} FROM source{clause}{group_clause} ORDER BY row_count DESC LIMIT {LIMITS.max_group_cardinality}"
    result = conn.execute(sql, params)
    columns = [d[0] for d in result.description]
    rows = [dict(zip(columns, row)) for row in result.fetchall()]
    truncated = len(rows) >= LIMITS.max_group_cardinality
    return {"rows": rows, "cardinalityCapped": truncated}


def category_frequency(conn: duckdb.DuckDBPyConnection, column: str, filters: Sequence[QueryFilter], top_n: int = 50) -> Dict[str, Any]:
    col = quote_identifier(column)
    params: List[Any] = []
    clause = _filter_clause(filters, params)
    top_n = min(top_n, LIMITS.max_group_cardinality)
    sql = f"SELECT {col} AS category, COUNT(*) AS n FROM source{clause} GROUP BY 1 ORDER BY n DESC LIMIT {top_n}"
    rows = conn.execute(sql, params).fetchall()
    total = get_row_count(conn, filters)
    return {"categories": [{"value": r[0], "count": int(r[1])} for r in rows], "totalRows": total, "cardinalityCapped": len(rows) >= top_n}


def bounded_sql_sample(conn: duckdb.DuckDBPyConnection, columns: Optional[List[str]], filters: Sequence[QueryFilter], limit: int, seed: Optional[int] = None) -> pd.DataFrame:
    """Pulls a bounded, optionally column-projected sample as a pandas DataFrame --
    this is the ONLY point where DuckDB hands rows to pandas, and it is always
    limited to `limit` rows (never the full source)."""
    limit = min(limit, LIMITS.max_result_rows)
    select_clause = ", ".join(quote_identifier(c) for c in columns) if columns else "*"
    params: List[Any] = []
    clause = _filter_clause(filters, params)
    sample_clause = f"USING SAMPLE reservoir({limit} ROWS) REPEATABLE ({seed})" if seed is not None else f"USING SAMPLE reservoir({limit} ROWS)"
    sql = f"SELECT {select_clause} FROM source{clause} {sample_clause}"
    return conn.execute(sql, params).fetchdf()


def bounded_rows(conn: duckdb.DuckDBPyConnection, columns: Optional[List[str]], filters: Sequence[QueryFilter], limit: int, sort: Optional[str]) -> pd.DataFrame:
    limit = min(limit, LIMITS.max_result_rows)
    select_clause = ", ".join(quote_identifier(c) for c in columns) if columns else "*"
    params: List[Any] = []
    clause = _filter_clause(filters, params)
    order_clause = ""
    if sort:
        direction = "DESC" if sort.startswith("-") else "ASC"
        order_clause = f" ORDER BY {quote_identifier(sort.lstrip('-'))} {direction}"
    sql = f"SELECT {select_clause} FROM source{clause}{order_clause} LIMIT {limit}"
    return conn.execute(sql, params).fetchdf()
