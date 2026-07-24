"""Enterprise Analytical Data Plane -- Polars adapter.

Used specifically for wide-table (hundreds-to-thousands of columns) schema
retrieval and lazy scanning, where Polars' lazy API lets us project a small
column subset and collect only metadata (dtype, null count) without loading
the full table -- important for the "1,000-column metadata-only fixture"
target scale, where even DuckDB's DESCRIBE would still need to open the file
but Polars' schema inspection on a lazy scan is cheaper for very wide Parquet
files specifically because it does not need to plan a query at all.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl

from ..resource_governance import LIMITS


def lazy_scan(file_path: Path, file_format: Optional[str]) -> pl.LazyFrame:
    if file_format == "parquet":
        return pl.scan_parquet(file_path)
    return pl.scan_csv(file_path, infer_schema_length=1000)


def get_schema_paginated(file_path: Path, file_format: Optional[str], offset: int = 0, limit: int = 100, search: Optional[str] = None, dtype_filter: Optional[str] = None) -> Dict[str, Any]:
    """Lazy schema retrieval with server-side pagination/search/type-filtering --
    Phase O requirement: never render/return all 1,000 columns from a single call
    by default."""
    lf = lazy_scan(file_path, file_format)
    schema = lf.collect_schema()
    all_columns = [{"name": name, "dtype": str(dtype)} for name, dtype in schema.items()]
    if search:
        needle = search.lower()
        all_columns = [c for c in all_columns if needle in c["name"].lower()]
    if dtype_filter:
        all_columns = [c for c in all_columns if dtype_filter.lower() in c["dtype"].lower()]
    total = len(all_columns)
    page = all_columns[offset: offset + min(limit, 500)]
    return {"columns": page, "totalColumns": total, "offset": offset, "limit": limit}


def row_count(file_path: Path, file_format: Optional[str]) -> int:
    lf = lazy_scan(file_path, file_format)
    return int(lf.select(pl.len()).collect().item())


def lightweight_column_profile(file_path: Path, file_format: Optional[str], column: str) -> Dict[str, Any]:
    """'Lightweight profile mode' (Phase O item 12): null count + dtype only, no
    full statistical scan -- cheap enough to run for many columns on demand."""
    lf = lazy_scan(file_path, file_format)
    schema = lf.collect_schema()
    if column not in schema:
        raise ValueError(f"Column not found: {column}")
    result = lf.select([
        pl.col(column).null_count().alias("null_count"),
        pl.len().alias("total_count"),
    ]).collect()
    row = result.row(0, named=True)
    return {"column": column, "dtype": str(schema[column]), "nullCount": int(row["null_count"]), "totalCount": int(row["total_count"])}


def deep_column_profile(file_path: Path, file_format: Optional[str], column: str) -> Dict[str, Any]:
    """'Deep profile mode' (Phase O item 13): full numeric summary -- more expensive,
    intended for profile-on-demand rather than automatic at page load."""
    lf = lazy_scan(file_path, file_format)
    is_numeric = "Int" in str(lf.collect_schema()[column]) or "Float" in str(lf.collect_schema()[column])
    if not is_numeric:
        return lightweight_column_profile(file_path, file_format, column)
    result = lf.select([
        pl.col(column).null_count().alias("null_count"),
        pl.len().alias("total_count"),
        pl.col(column).min().alias("min_v"),
        pl.col(column).max().alias("max_v"),
        pl.col(column).mean().alias("mean_v"),
        pl.col(column).std().alias("std_v"),
        pl.col(column).median().alias("median_v"),
    ]).collect()
    row = result.row(0, named=True)
    return {
        "column": column, "nullCount": int(row["null_count"]), "totalCount": int(row["total_count"]),
        "minimum": row["min_v"], "maximum": row["max_v"], "mean": row["mean_v"], "std": row["std_v"], "median": row["median_v"],
    }


def top_feature_summary(file_path: Path, file_format: Optional[str], max_columns: int = 20) -> List[Dict[str, Any]]:
    """A bounded 'top features' summary -- null-count ranked, capped at max_columns
    so a 1,000-column table never triggers 1,000 profile computations at once."""
    lf = lazy_scan(file_path, file_format)
    schema = lf.collect_schema()
    numeric_cols = [name for name, dtype in schema.items() if "Int" in str(dtype) or "Float" in str(dtype)][:max_columns]
    if not numeric_cols:
        return []
    exprs = []
    for col in numeric_cols:
        exprs.append(pl.col(col).null_count().alias(f"{col}__nulls"))
    result = lf.select(exprs).collect()
    row = result.row(0, named=True)
    return [{"column": col, "nullCount": int(row[f"{col}__nulls"])} for col in numeric_cols]
