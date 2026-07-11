from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Dict, List

from fastapi import HTTPException

from ..datasets.dataset_registry import read_version_artifact, require_dataset

BLOCKED_SQL = r"\b(insert|update|delete|drop|alter|create|truncate|merge|exec|execute|call|pragma|attach|detach|replace|vacuum|reindex)\b"


def strip_sql_comments(sql: str) -> str:
    without_line = re.sub(r"--.*?$", "", sql or "", flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", without_line, flags=re.DOTALL)


def safe_sql_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", value or "").strip("_")
    if not safe:
        return ""
    if re.match(r"^\d", safe):
        safe = f"t_{safe}"
    return safe[:64]


def quote_identifier(value: str) -> str:
    return f'"{value.replace(chr(34), chr(34) + chr(34))}"'


def normalize_sql_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str)):
        return value
    return str(value)


def is_read_only_select(sql: str) -> bool:
    stripped = strip_sql_comments(sql).strip().rstrip(";").strip()
    if not stripped:
        return False
    if ";" in stripped:
        return False
    if re.search(BLOCKED_SQL, stripped, re.IGNORECASE):
        return False
    return bool(re.match(r"^(select|with)\b", stripped, re.IGNORECASE | re.DOTALL))


def apply_preview_limit(sql: str, max_rows: int) -> tuple[str, bool]:
    stripped = sql.strip().rstrip(";").strip()
    if re.search(r"\blimit\s+\d+\b", stripped, re.IGNORECASE):
        return stripped, False
    return f"SELECT * FROM ({stripped}) AS atlas_sql_preview LIMIT {max_rows}", True


def load_rows(conn: sqlite3.Connection, table_name: str, rows: List[Dict[str, Any]]) -> None:
    columns = sorted({str(key) for row in rows for key in row.keys()}) or ["empty"]
    quoted_columns = [quote_identifier(column) for column in columns]
    conn.execute(f"CREATE TABLE {quote_identifier(table_name)} ({', '.join(f'{column} TEXT' for column in quoted_columns)})")
    if not rows:
        return
    placeholders = ", ".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO {quote_identifier(table_name)} ({', '.join(quoted_columns)}) VALUES ({placeholders})",
        [[normalize_sql_value(row.get(column)) for column in columns] for row in rows],
    )


def infer_result_type(values: list[Any]) -> str:
    non_missing = [value for value in values if value not in (None, "")]
    if not non_missing:
        return "empty"
    numeric_count = 0
    for value in non_missing[:250]:
        try:
            float(value)
            numeric_count += 1
        except Exception:
            pass
    return "numeric" if numeric_count / max(1, min(len(non_missing), 250)) >= 0.9 else "categorical"


def profile_rows(rows: List[Dict[str, Any]], columns: list[str]) -> list[Dict[str, Any]]:
    profile: list[Dict[str, Any]] = []
    for column in columns:
        values = [row.get(column) for row in rows]
        dtype = infer_result_type(values)
        non_missing = [value for value in values if value not in (None, "")]
        entry: Dict[str, Any] = {
            "name": column,
            "type": dtype,
            "missingCount": len(values) - len(non_missing),
            "distinctCount": len({str(value) for value in non_missing}),
        }
        if dtype == "numeric":
            nums = []
            for value in non_missing:
                try:
                    nums.append(float(value))
                except Exception:
                    pass
            if nums:
                entry.update({"min": min(nums), "max": max(nums), "mean": sum(nums) / len(nums)})
        else:
            entry["sampleValues"] = list(dict.fromkeys(str(value) for value in non_missing[:8]))[:5]
        profile.append(entry)
    return profile


def validate_sql(sql: str, dataset_refs: list[Dict[str, Any]], limit: int = 100) -> Dict[str, Any]:
    warnings: list[str] = []
    if not (sql or "").strip():
        return {"ok": False, "status": "error", "warnings": [], "error": "SQL is empty."}
    if not is_read_only_select(sql):
        return {
            "ok": False,
            "status": "blocked",
            "warnings": [],
            "error": "Blocked: SQL Data Studio only allows read-only SELECT queries in this local build.",
        }
    aliases = {safe_sql_name(str(ref.get("alias") or "")) for ref in dataset_refs}
    aliases.discard("")
    if not aliases:
        warnings.append("No Dataset Library tables are selected. Preview execution needs at least one dataset reference.")
    referenced = set(re.findall(r"\bfrom\s+([A-Za-z_][A-Za-z0-9_]*)|\bjoin\s+([A-Za-z_][A-Za-z0-9_]*)", strip_sql_comments(sql), flags=re.IGNORECASE))
    referenced_tables = {safe_sql_name(item) for pair in referenced for item in pair if item}
    missing = sorted(table for table in referenced_tables if table not in aliases)
    if missing:
        return {"ok": False, "status": "error", "warnings": warnings, "error": f"Referenced table(s) not selected: {', '.join(missing)}."}
    if not re.search(r"\blimit\s+\d+\b", sql, re.IGNORECASE):
        warnings.append(f"No LIMIT was detected. ATLAS will apply a preview cap of {limit:,} rows.")
    return {"ok": True, "status": "valid_with_warning" if warnings else "valid", "warnings": warnings, "error": ""}


def run_preview_sql(sql: str, dataset_refs: list[Dict[str, Any]], limit: int = 100) -> Dict[str, Any]:
    started = time.perf_counter()
    cap = max(1, min(int(limit or 100), 1000))
    validation = validate_sql(sql, dataset_refs, cap)
    if not validation.get("ok"):
        return {
            "ok": False,
            "status": validation.get("status", "error"),
            "rowCount": 0,
            "returnedRows": 0,
            "columns": [],
            "rows": [],
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "warnings": validation.get("warnings", []),
            "error": validation.get("error", "SQL validation failed."),
        }
    warnings = list(validation.get("warnings") or [])
    try:
        with sqlite3.connect(":memory:") as conn:
            conn.row_factory = sqlite3.Row
            for ref in dataset_refs:
                dataset_id = str(ref.get("datasetId") or "")
                version_id = str(ref.get("versionId") or "")
                alias = safe_sql_name(str(ref.get("alias") or dataset_id))
                if not dataset_id or not version_id or not alias:
                    raise HTTPException(status_code=400, detail="Each dataset reference must include datasetId, versionId, and alias.")
                require_dataset(dataset_id)
                preview = read_version_artifact(dataset_id, version_id, "preview.json", {"rows": [], "columns": []})
                load_rows(conn, alias, preview.get("rows") or [])
            limited_sql, added_limit = apply_preview_limit(sql, cap)
            if added_limit:
                warnings.append(f"Preview cap applied: {cap:,} rows.")
            cursor = conn.execute(limited_sql)
            rows = [dict(row) for row in cursor.fetchall()]
            column_names = [description[0] for description in cursor.description or []]
            columns = [{"name": column, "type": infer_result_type([row.get(column) for row in rows])} for column in column_names]
            schema_profile = profile_rows(rows, column_names)
        return {
            "ok": True,
            "status": "success",
            "rowCount": len(rows),
            "returnedRows": len(rows),
            "columns": columns,
            "rows": rows,
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "warnings": warnings,
            "schemaProfile": schema_profile,
        }
    except Exception as exc:
        return {
            "ok": False,
            "status": "error",
            "rowCount": 0,
            "returnedRows": 0,
            "columns": [],
            "rows": [],
            "runtimeMs": int((time.perf_counter() - started) * 1000),
            "warnings": warnings,
            "error": str(exc),
        }

