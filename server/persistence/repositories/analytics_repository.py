from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class AnalyticsRepository(BaseRepository):
    def upsert_run(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO analytical_runs (analytical_run_id, project_id, workflow_type, analysis_type, analysis_version,
              dataset_id, dataset_version_id, source_run_record_id, status, requested_by_user_id, started_at, completed_at,
              parameter_json, input_reference_json, result_summary_json, warning_count, error_message, reproducibility_json,
              metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(analytical_run_id) DO UPDATE SET status=excluded.status, completed_at=excluded.completed_at,
              parameter_json=excluded.parameter_json, input_reference_json=excluded.input_reference_json,
              result_summary_json=excluded.result_summary_json, warning_count=excluded.warning_count,
              error_message=excluded.error_message, reproducibility_json=excluded.reproducibility_json,
              metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
            """,
            (record["analytical_run_id"], record.get("project_id"), record.get("workflow_type"), record["analysis_type"],
             record.get("analysis_version") or "1.0.0", record.get("dataset_id"), record.get("dataset_version_id"),
             record.get("source_run_record_id"), record.get("status") or "queued", record.get("requested_by_user_id"),
             record.get("started_at") or timestamp, record.get("completed_at"), json_dumps(record.get("parameter_json"), {}),
             json_dumps(record.get("input_reference_json"), {}), json_dumps(record.get("result_summary_json"), {}),
             int(record.get("warning_count") or 0), record.get("error_message"), json_dumps(record.get("reproducibility_json"), {}),
             json_dumps(record.get("metadata_json"), {}), record.get("created_at") or timestamp, timestamp),
        )
        return self.get_run(record["analytical_run_id"]) or {}

    def get_run(self, run_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM analytical_runs WHERE analytical_run_id = ?", (run_id,))

    def list_runs(self, *, project_id: str | None = None, analysis_type: str | None = None, status: str | None = None, limit: int = 250) -> List[Dict[str, Any]]:
        query, params = "SELECT * FROM analytical_runs WHERE 1=1", []
        if project_id:
            query += " AND project_id = ?"; params.append(project_id)
        if analysis_type:
            query += " AND analysis_type = ?"; params.append(analysis_type)
        if status:
            query += " AND status = ?"; params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"; params.append(max(1, min(int(limit), 1000)))
        return self._many(query, params)

    def replace_outputs(self, run_id: str, result: Dict[str, Any]) -> None:
        with self.database.transaction() as connection:
            for table in ("analytical_results", "analytical_tables", "analytical_charts", "analytical_interpretations"):
                connection.execute(f"DELETE FROM {table} WHERE analytical_run_id = ?", (run_id,))
            timestamp = now_iso()
            for index, item in enumerate(result.get("tables") or []):
                rows = item.get("rows") or []
                connection.execute("INSERT INTO analytical_tables (analytical_table_id, analytical_run_id, table_name, table_title, table_json, row_count, column_count, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"atbl_{run_id}_{index}", run_id, item.get("table_id") or f"table_{index}", item.get("title"), json_dumps(item), len(rows), len(item.get("columns") or []), timestamp, json_dumps(item.get("metadata"), {})))
            for index, item in enumerate(result.get("charts") or []):
                connection.execute("INSERT INTO analytical_charts (analytical_chart_id, analytical_run_id, chart_type, chart_title, chart_spec_json, chart_data_json, documentation_caption, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"achart_{run_id}_{index}", run_id, item.get("chart_type") or "table", item.get("title") or "Analytical chart", json_dumps({k: v for k, v in item.items() if k != "data"}), json_dumps(item.get("data"), []), item.get("documentation_caption"), timestamp, json_dumps(item.get("metadata"), {})))
            for index, item in enumerate(result.get("interpretations") or []):
                connection.execute("INSERT INTO analytical_interpretations (interpretation_id, analytical_run_id, interpretation_type, severity, title, interpretation_text, supporting_statistic_json, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"aint_{run_id}_{index}", run_id, item.get("type") or "finding", item.get("severity"), item.get("title"), item.get("finding") or item.get("text") or "", json_dumps(item.get("supporting_statistic"), {}), timestamp, json_dumps(item)))
            connection.execute("INSERT INTO analytical_results (analytical_result_id, analytical_run_id, result_type, result_name, result_json, sequence_number, created_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"ares_{run_id}", run_id, "full_result", result.get("analysis_type") or "analytical_result", json_dumps(result), 0, timestamp, json_dumps({"analysis_version": result.get("analysis_version")}, {})))

    def full_result(self, run_id: str) -> Dict[str, Any] | None:
        row = self._one("SELECT result_json FROM analytical_results WHERE analytical_run_id = ? AND result_type = 'full_result' ORDER BY sequence_number LIMIT 1", (run_id,))
        return (row or {}).get("result_json")
