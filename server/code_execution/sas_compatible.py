from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Dict, List

import pandas as pd


SUPPORTED_PROCS = ["CONTENTS", "MEANS", "FREQ", "CORR", "PRINT", "SQL", "RANK"]


@dataclass
class SasTable:
    title: str
    columns: list[str]
    rows: list[dict[str, Any]]


def run_sas_compatible(code: str, context: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    stdout: list[str] = []
    unsupported: list[str] = []
    result_tables: list[SasTable] = []
    #: Per-statement outcome report (CODE-DATAACQ-004). Every submitted statement
    #: appears exactly once with an explicit outcome, so "partial" is explainable.
    statement_report: list[dict[str, Any]] = []
    active_table = active_table_identity(context)
    translated: list[str] = [
        "# ATLAS SAS-Compatible translated Python",
        "import pandas as pd",
        f"# work.{active_table} is loaded from the active ATLAS dataset",
    ]

    def record(statement: str, outcome: str, detail: str = "") -> None:
        statement_report.append({
            "statement": _statement_label(statement),
            "outcome": outcome,
            "detail": detail,
        })

    try:
        work = _build_work_library(context)
        statements = _split_sas_blocks(code or "")
        if not statements:
            return _response(
                "failed", stdout="", stderr="No SAS-compatible code was submitted.", tables=[],
                unsupported=[], translated=translated, started=started, report=[], active_table=active_table,
            )

        for statement in statements:
            normalized = statement.strip()
            lower = normalized.lower()
            try:
                if lower.startswith("proc contents"):
                    table = _proc_contents(normalized, work, translated)
                    result_tables.append(table)
                    stdout.append(f"PROC CONTENTS completed for {table.title}.")
                elif lower.startswith("proc means"):
                    tables = _proc_means(normalized, work, translated)
                    result_tables.extend(tables)
                    stdout.append("PROC MEANS completed.")
                elif lower.startswith("proc freq"):
                    tables = _proc_freq(normalized, work, translated)
                    result_tables.extend(tables)
                    stdout.append("PROC FREQ completed.")
                elif lower.startswith("proc corr"):
                    table = _proc_corr(normalized, work, translated)
                    result_tables.append(table)
                    stdout.append("PROC CORR completed.")
                elif lower.startswith("proc print"):
                    table = _proc_print(normalized, work, translated)
                    result_tables.append(table)
                    stdout.append("PROC PRINT completed.")
                elif lower.startswith("proc sql"):
                    table = _proc_sql(normalized, work, translated)
                    result_tables.append(table)
                    stdout.append("PROC SQL SELECT completed.")
                elif lower.startswith("proc rank"):
                    table_name = _proc_rank(normalized, work, translated)
                    stdout.append(f"PROC RANK completed. Output table: {table_name}.")
                elif lower.startswith("data "):
                    table_name = _data_step(normalized, work, translated)
                    stdout.append(f"DATA step completed. Output table: {table_name}.")
                elif _is_nonmaterial(lower):
                    # TITLE/OPTIONS/comments carry no analytical result; accepted,
                    # but they must not count as "material work completed".
                    record(normalized, "translated", "Accepted with no analytical output.")
                    continue
                else:
                    unsupported.append(_unsupported_label(normalized))
                    record(normalized, "skipped_unsupported", "This statement is outside the SAS-compatible subset.")
                    continue
                record(normalized, "executed")
            except InputUnavailable as exc:
                unsupported.append(str(exc))
                record(normalized, "input_unavailable", str(exc))
            except UnsupportedSasStatement as exc:
                unsupported.append(str(exc))
                record(normalized, "skipped_unsupported", str(exc))
            except Exception as exc:
                unsupported.append(f"{_unsupported_label(normalized)}: {exc}")
                record(normalized, "failed", str(exc))

        return _response(
            _derive_status(statement_report), stdout="\n".join(stdout), stderr="", tables=result_tables,
            unsupported=unsupported, translated=translated, started=started,
            report=statement_report, active_table=active_table,
        )
    except Exception as exc:
        return _response(
            "failed", stdout="\n".join(stdout), stderr=f"ATLAS SAS-Compatible execution failed: {exc}",
            tables=result_tables, unsupported=unsupported, translated=translated, started=started,
            report=statement_report, active_table=active_table,
        )


class UnsupportedSasStatement(Exception):
    """A statement outside the supported SAS-compatible subset."""


class InputUnavailable(UnsupportedSasStatement):
    """A referenced input table is not registered for the active dataset."""


#: Accepted for compatibility but producing no analytical result.
_NONMATERIAL_PREFIXES = ("title", "footnote", "options", "ods ", "%let", "run;", "quit;", "*")


def _is_nonmaterial(lower_statement: str) -> bool:
    return lower_statement.startswith(_NONMATERIAL_PREFIXES)


def _derive_status(report: list[dict[str, Any]]) -> str:
    """Honest status semantics (CODE-DATAACQ-004).

    completed -- every material statement executed or translated successfully
    partial   -- at least one material statement succeeded AND at least one was
                 skipped, failed, or had unavailable input
    failed    -- no material analytical statement completed
    """
    material = [row for row in report if row["outcome"] != "translated"]
    executed = [row for row in material if row["outcome"] == "executed"]
    problems = [row for row in material if row["outcome"] in {"skipped_unsupported", "failed", "input_unavailable"}]

    if not material:
        # Only non-material statements ran: nothing analytical completed.
        return "failed"
    if executed and problems:
        return "partial"
    if executed:
        return "completed"
    return "failed"


def _response(
    status: str,
    stdout: str,
    stderr: str,
    tables: list[SasTable],
    unsupported: list[str],
    translated: list[str],
    started: float,
    report: list[dict[str, Any]] | None = None,
    active_table: str = "",
) -> dict[str, Any]:
    report = report or []
    counts = {
        outcome: sum(1 for row in report if row["outcome"] == outcome)
        for outcome in ("executed", "translated", "skipped_unsupported", "failed", "input_unavailable")
    }
    # A partial run is NOT an unqualified success: return code 0 is reserved for
    # a fully completed program (CODE-DATAACQ-004).
    return_code = 0 if status == "completed" else 1
    return {
        # `ok` means the request was serviced; `status` carries the analytical outcome.
        "ok": status in {"completed", "partial"},
        "status": status,
        "statementReport": report,
        "statementCounts": counts,
        "activeTable": active_table,
        "executionKind": "sas_compatible_translated",
        "engineNote": "ATLAS translated a supported subset of SAS to pandas. This is not a SASPy session or a licensed SAS runtime.",
        "stdout": stdout,
        "stderr": stderr,
        "tables": [{"title": table.title, "columns": table.columns, "rows": table.rows} for table in tables],
        "charts": [],
        "translatedPython": "\n".join(translated),
        "unsupportedStatements": unsupported,
        "runtimeMs": int((time.perf_counter() - started) * 1000),
        "returnCode": return_code,
    }


def active_table_identity(context: dict[str, Any]) -> str:
    """The one authoritative SAS table name for the active dataset.

    CODE-DATAACQ-003 root cause: this module used to register a hard-coded
    `work.reg_train` (a regression-era name) as an always-present alias, use it
    as the fallback dataset name, and name it in every "table not available"
    message -- so a classification project was told to use `work.reg_train`
    regardless of which dataset was actually active. The identity is now derived
    solely from the active dataset, keyed by the caller's dataset/version.
    """
    raw = str(context.get("datasetName") or "").strip()
    if not raw:
        raw = str(context.get("datasetId") or "").strip()
    if not raw:
        # No active dataset identity at all -- use a neutral placeholder rather
        # than _safe_name("")'s degenerate "atlas_" output.
        return "atlas_dataset"
    return _safe_name(raw) or "atlas_dataset"


def _build_work_library(context: dict[str, Any]) -> dict[str, pd.DataFrame]:
    rows = context.get("previewRows") or context.get("preview_rows") or []
    df = pd.DataFrame(rows if isinstance(rows, list) else [])
    dataset_name = active_table_identity(context)
    # Only the active dataset's identity is registered. Lookups are
    # case-insensitive (see _resolve_table), so work.CLASS_TRAIN and
    # work.class_train both resolve to this one table.
    return {
        dataset_name: df.copy(),
        f"work.{dataset_name}": df.copy(),
        f"atlas.{dataset_name}": df.copy(),
    }


def _split_sas_blocks(code: str) -> list[str]:
    cleaned = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    pattern = re.compile(r"((?:proc|data)\s+.*?(?:\brun\s*;|\bquit\s*;))", re.IGNORECASE | re.DOTALL)
    return [match.group(1).strip() for match in pattern.finditer(cleaned)]


def _proc_contents(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> SasTable:
    df = _table_from_statement(statement, work)
    translated.append("contents = pd.DataFrame({'Column': df.columns, 'Type': [str(df[c].dtype) for c in df.columns]})")
    rows = []
    for column in df.columns:
        series = df[column]
        rows.append({
            "Column": column,
            "Type": str(series.dtype),
            "Non Missing": int(series.notna().sum()),
            "Missing": int(series.isna().sum()),
            "Distinct": int(series.nunique(dropna=True)),
        })
    return SasTable("PROC CONTENTS", ["Column", "Type", "Non Missing", "Missing", "Distinct"], rows)


def _proc_means(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> list[SasTable]:
    df = _table_from_statement(statement, work)
    vars_ = _parse_var_list(statement, df)
    class_vars = _parse_class_list(statement, df)
    stats = _parse_means_stats(statement)
    translated.append(f"means = df[{vars_!r}].agg({stats!r})")
    if class_vars:
        rows: list[dict[str, Any]] = []
        grouped = df.groupby(class_vars, dropna=False)
        for keys, group in grouped:
            if not isinstance(keys, tuple):
                keys = (keys,)
            base = {class_vars[i]: _json_value(keys[i]) for i in range(len(class_vars))}
            for var in vars_:
                series = pd.to_numeric(group[var], errors="coerce")
                row = {**base, "Variable": var}
                row.update(_stats_for_series(series, stats))
                rows.append(row)
        columns = [*class_vars, "Variable", *_stat_labels(stats)]
        return [SasTable("PROC MEANS by CLASS", columns, rows)]
    rows = []
    for var in vars_:
        series = pd.to_numeric(df[var], errors="coerce")
        row = {"Variable": var}
        row.update(_stats_for_series(series, stats))
        rows.append(row)
    return [SasTable("PROC MEANS", ["Variable", *_stat_labels(stats)], rows)]


def _proc_freq(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> list[SasTable]:
    df = _table_from_statement(statement, work)
    match = re.search(r"\btables\s+([^;]+);", statement, re.IGNORECASE)
    columns = _valid_columns((match.group(1).split() if match else list(df.columns[:1])), df)
    translated.append("# PROC FREQ: df[column].value_counts(dropna=False)")
    tables = []
    for column in columns:
        counts = df[column].value_counts(dropna=False).head(50)
        total = max(int(counts.sum()), 1)
        rows = [{"Value": _json_value(index), "Count": int(count), "Percent": round(float(count) / total * 100, 2)} for index, count in counts.items()]
        tables.append(SasTable(f"PROC FREQ: {column}", ["Value", "Count", "Percent"], rows))
    return tables


def _proc_corr(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> SasTable:
    df = _table_from_statement(statement, work)
    vars_ = _parse_var_list(statement, df)
    numeric = df[vars_].apply(pd.to_numeric, errors="coerce")
    corr = numeric.corr().fillna(0)
    translated.append(f"corr = df[{vars_!r}].corr()")
    rows = []
    for row_name in corr.index:
        row = {"Variable": row_name}
        for column in corr.columns:
            row[column] = round(float(corr.loc[row_name, column]), 4)
        rows.append(row)
    return SasTable("PROC CORR", ["Variable", *list(corr.columns)], rows)


def _proc_print(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> SasTable:
    table_name, df = _resolve_table(_extract_data_name(statement), work)
    obs_match = re.search(r"\(\s*obs\s*=\s*(\d+)\s*\)", statement, re.IGNORECASE)
    obs = int(obs_match.group(1)) if obs_match else 10
    obs = max(1, min(obs, 100))
    translated.append(f"printed = work[{table_name!r}].head({obs})")
    preview = df.head(obs)
    return SasTable(f"PROC PRINT: {table_name}", list(preview.columns), _records(preview))


def _proc_sql(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> SasTable:
    select_match = re.search(r"select\s+(.*?)\s+from\s+([A-Za-z0-9_.]+)(?:\s+limit\s+(\d+))?", statement, re.IGNORECASE | re.DOTALL)
    if not select_match:
        raise UnsupportedSasStatement("PROC SQL supports SELECT column-list FROM table LIMIT n in v1.")
    columns_text = select_match.group(1).strip()
    table_name = _normalize_table_name(select_match.group(2))
    limit = int(select_match.group(3) or 25)
    _, df = _resolve_table(table_name, work)
    conn = sqlite3.connect(":memory:")
    try:
        df.to_sql(table_name.replace(".", "_"), conn, index=False, if_exists="replace")
        sql_columns = "*" if columns_text == "*" else ", ".join([_quote_sql(col.strip()) for col in columns_text.split(",") if col.strip()])
        sql = f"select {sql_columns} from {_quote_sql(table_name.replace('.', '_'))} limit {max(1, min(limit, 100))}"
        translated.append(f"sql = {sql!r}")
        result = pd.read_sql_query(sql, conn)
        return SasTable("PROC SQL SELECT", list(result.columns), _records(result))
    finally:
        conn.close()


def _proc_rank(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> str:
    table_name, df = _resolve_table(_extract_data_name(statement), work)
    groups_match = re.search(r"\bgroups\s*=\s*(\d+)", statement, re.IGNORECASE)
    out_match = re.search(r"\bout\s*=\s*([A-Za-z0-9_.]+)", statement, re.IGNORECASE)
    groups = max(2, min(int(groups_match.group(1)) if groups_match else 5, 20))
    out_name = _normalize_table_name(out_match.group(1)) if out_match else f"{table_name}_ranked"
    vars_ = _parse_var_list(statement, df)
    ranks_match = re.search(r"\branks\s+([^;]+);", statement, re.IGNORECASE)
    rank_names = ranks_match.group(1).split() if ranks_match else [f"{var}_band" for var in vars_]
    ranked = df.copy()
    for index, var in enumerate(vars_):
        target = rank_names[index] if index < len(rank_names) else f"{var}_band"
        values = pd.to_numeric(ranked[var], errors="coerce")
        ranked[target] = pd.qcut(values.rank(method="first"), q=groups, labels=False, duplicates="drop")
    work[out_name] = ranked
    work[f"work.{out_name.split('.')[-1]}"] = ranked
    translated.append(f"work[{out_name!r}] = df.copy(); work[{out_name!r}][rank_columns] = pd.qcut(...)")
    return out_name


def _data_step(statement: str, work: dict[str, pd.DataFrame], translated: list[str]) -> str:
    data_match = re.match(r"\s*data\s+([A-Za-z0-9_.]+)\s*;", statement, re.IGNORECASE)
    set_match = re.search(r"\bset\s+([A-Za-z0-9_.]+)\s*;", statement, re.IGNORECASE)
    if not data_match or not set_match:
        raise UnsupportedSasStatement("DATA step v1 supports DATA target; SET source; simple assignments; RUN;")
    output_name = _normalize_table_name(data_match.group(1))
    _, source = _resolve_table(_normalize_table_name(set_match.group(1)), work)
    df = source.copy()
    assignments = re.findall(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^;]+);", statement, re.IGNORECASE | re.MULTILINE)
    for column, expr in assignments:
        df[column] = _evaluate_data_step_expr(df, expr.strip())
    work[output_name] = df
    work[f"work.{output_name.split('.')[-1]}"] = df
    translated.append(f"work[{output_name!r}] = work[source].copy()  # DATA step simple assignments")
    return output_name


def _evaluate_data_step_expr(df: pd.DataFrame, expr: str) -> Any:
    numeric_literal = re.fullmatch(r"-?\d+(?:\.\d+)?", expr)
    if numeric_literal:
        return float(expr) if "." in expr else int(expr)
    if expr in df.columns:
        return df[expr]
    binary = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_]*)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)", expr)
    if binary and binary.group(1) in df.columns:
        left = pd.to_numeric(df[binary.group(1)], errors="coerce")
        value = float(binary.group(3))
        op = binary.group(2)
        if op == "+":
            return left + value
        if op == "-":
            return left - value
        if op == "*":
            return left * value
        if op == "/":
            return left / value if value != 0 else None
    raise UnsupportedSasStatement(f"Unsupported DATA step assignment expression: {expr}")


def _table_from_statement(statement: str, work: dict[str, pd.DataFrame]) -> pd.DataFrame:
    _, df = _resolve_table(_extract_data_name(statement), work)
    return df


def _extract_data_name(statement: str) -> str:
    match = re.search(r"\bdata\s*=\s*([A-Za-z0-9_.]+)", statement, re.IGNORECASE)
    if not match:
        raise UnsupportedSasStatement("Expected DATA=work.table in this SAS-compatible statement.")
    return _normalize_table_name(match.group(1))


def _resolve_table(name: str, work: dict[str, pd.DataFrame]) -> tuple[str, pd.DataFrame]:
    normalized = _normalize_table_name(name)
    aliases = [normalized, normalized.lower(), normalized.replace("atlas.", "work."), normalized.replace("work.", ""), f"work.{normalized}"]
    for alias in aliases:
        if alias in work:
            return alias, work[alias]
    # The guidance names the table that is actually registered for this project,
    # never a hard-coded regression-era default.
    available = sorted({key for key in work if key.startswith("work.")}) or sorted(work)
    suggestion = available[0] if available else "the active ATLAS dataset"
    raise InputUnavailable(f"Table {name} is not available. Use {suggestion} for the active ATLAS dataset.")


def _normalize_table_name(name: str) -> str:
    return name.strip().strip(";").lower()


def _parse_var_list(statement: str, df: pd.DataFrame) -> list[str]:
    match = re.search(r"\bvar\s+([^;]+);", statement, re.IGNORECASE)
    if not match:
        return [column for column in df.columns if pd.api.types.is_numeric_dtype(pd.to_numeric(df[column], errors="coerce"))][:12]
    return _valid_columns(match.group(1).split(), df)


def _parse_class_list(statement: str, df: pd.DataFrame) -> list[str]:
    match = re.search(r"\bclass\s+([^;]+);", statement, re.IGNORECASE)
    return _valid_columns(match.group(1).split(), df) if match else []


def _valid_columns(candidates: list[str], df: pd.DataFrame) -> list[str]:
    lookup = {column.lower(): column for column in df.columns}
    columns = [lookup[item.strip().lower()] for item in candidates if item.strip().lower() in lookup]
    if not columns:
        raise UnsupportedSasStatement(f"None of the requested columns are available: {' '.join(candidates)}")
    return columns


def _parse_means_stats(statement: str) -> list[str]:
    header = statement.split(";", 1)[0].lower()
    stats = [item for item in ["n", "mean", "median", "std", "min", "max"] if re.search(rf"\b{item}\b", header)]
    return stats or ["n", "mean", "std", "min", "max"]


def _stat_labels(stats: list[str]) -> list[str]:
    return [{"n": "N", "mean": "Mean", "median": "Median", "std": "Std", "min": "Min", "max": "Max"}[stat] for stat in stats]


def _stats_for_series(series: pd.Series, stats: list[str]) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce")
    values: dict[str, Any] = {}
    for stat, label in zip(stats, _stat_labels(stats)):
        if stat == "n":
            values[label] = int(numeric.notna().sum())
        elif stat == "mean":
            values[label] = _round(numeric.mean())
        elif stat == "median":
            values[label] = _round(numeric.median())
        elif stat == "std":
            values[label] = _round(numeric.std())
        elif stat == "min":
            values[label] = _round(numeric.min())
        elif stat == "max":
            values[label] = _round(numeric.max())
    return values


def _quote_sql(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(key): _json_value(value) for key, value in row.items()} for row in df.fillna("").to_dict(orient="records")]


def _json_value(value: Any) -> Any:
    if hasattr(value, "item"):
        try:
            value = value.item()
        except Exception:
            pass
    if pd.isna(value):
        return ""
    if isinstance(value, float):
        return _round(value)
    return value


def _round(value: Any) -> Any:
    try:
        if pd.isna(value):
            return ""
        return round(float(value), 4)
    except Exception:
        return value


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()
    if not cleaned or cleaned[0].isdigit():
        cleaned = f"atlas_{cleaned}"
    return cleaned[:32]


def _statement_label(statement: str) -> str:
    """Plain excerpt of the statement. The outcome is carried by the report's
    `outcome` field, so the label must not assert that it was unsupported."""
    return " ".join(statement.strip().split())[:140]


def _unsupported_label(statement: str) -> str:
    return f"Unsupported statement detected: {_statement_label(statement)}"
