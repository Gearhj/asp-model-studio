from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository

# Columns a caller may filter list() by -- fixed allowlist, never built from
# arbitrary client-supplied column names (mirrors the identifier-safety
# discipline in server/analytics/engines/duckdb_engine.py).
_FILTERABLE_COLUMNS = {
    "project_id", "dataset_id", "model_id", "partition", "status", "problem_type",
}


class ScoringRunRepository(BaseRepository):
    def list(
        self,
        *,
        project_id: Optional[str] = None,
        dataset_id: Optional[str] = None,
        model_id: Optional[str] = None,
        partition: Optional[str] = None,
        status: Optional[str] = None,
        problem_type: Optional[str] = None,
        created_after: Optional[str] = None,
        created_before: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        filters = {
            "project_id": project_id, "dataset_id": dataset_id, "model_id": model_id,
            "partition": partition, "status": status, "problem_type": problem_type,
        }
        clauses: List[str] = []
        params: List[Any] = []
        for column, value in filters.items():
            if value is None:
                continue
            if column not in _FILTERABLE_COLUMNS:
                continue  # defensive -- every key above is already in the allowlist
            clauses.append(f"{column} = ?")
            params.append(value)
        if created_after:
            clauses.append("created_at >= ?")
            params.append(created_after)
        if created_before:
            clauses.append("created_at <= ?")
            params.append(created_before)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded_limit = max(1, min(int(limit or 200), 1000))
        query = f"SELECT * FROM scoring_runs {where} ORDER BY created_at DESC LIMIT ?"
        params.append(bounded_limit)
        return self._many(query, tuple(params))

    def get(self, scoring_run_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM scoring_runs WHERE scoring_run_id = ?", (scoring_run_id,))

    def get_many(self, scoring_run_ids: List[str]) -> List[Dict[str, Any]]:
        if not scoring_run_ids:
            return []
        placeholders = ",".join("?" for _ in scoring_run_ids)
        return self._many(f"SELECT * FROM scoring_runs WHERE scoring_run_id IN ({placeholders})", tuple(scoring_run_ids))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO scoring_runs (
              scoring_run_id, project_id, user_id, dataset_id, dataset_version_id, dataset_identity,
              partition, model_id, model_version, feature_manifest_version, problem_type, target,
              status, created_at, completed_at, started_by, execution_engine, query_version, row_count,
              prediction_column, probability_column, residual_column,
              output_artifact_id, output_artifact_path, output_artifact_format,
              metrics_json, diagnostics_json, psi_json, vsi_json,
              evidence_links_json, documentation_links_json, lineage_json,
              retention_policy, archived_at, checksum, error_message, updated_at,
              output_dataset_id, output_dataset_version_id, registration_status, registered_at, registered_by,
              model_version_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scoring_run_id) DO UPDATE SET
              status = excluded.status,
              completed_at = excluded.completed_at,
              row_count = excluded.row_count,
              output_artifact_id = excluded.output_artifact_id,
              output_artifact_path = excluded.output_artifact_path,
              output_artifact_format = excluded.output_artifact_format,
              metrics_json = excluded.metrics_json,
              diagnostics_json = excluded.diagnostics_json,
              psi_json = excluded.psi_json,
              vsi_json = excluded.vsi_json,
              evidence_links_json = excluded.evidence_links_json,
              documentation_links_json = excluded.documentation_links_json,
              lineage_json = excluded.lineage_json,
              retention_policy = excluded.retention_policy,
              archived_at = excluded.archived_at,
              checksum = excluded.checksum,
              error_message = excluded.error_message,
              updated_at = excluded.updated_at,
              output_dataset_id = excluded.output_dataset_id,
              output_dataset_version_id = excluded.output_dataset_version_id,
              registration_status = excluded.registration_status,
              registered_at = excluded.registered_at,
              registered_by = excluded.registered_by,
              model_version_id = excluded.model_version_id
            """,
            (
                record["scoring_run_id"],
                record.get("project_id"),
                record.get("user_id"),
                record.get("dataset_id"),
                record.get("dataset_version_id"),
                record.get("dataset_identity"),
                record.get("partition") or "test",
                record.get("model_id"),
                record.get("model_version"),
                record.get("feature_manifest_version"),
                record.get("problem_type"),
                record.get("target"),
                record.get("status") or "running",
                timestamp,
                record.get("completed_at"),
                record.get("started_by"),
                record.get("execution_engine"),
                record.get("query_version"),
                record.get("row_count"),
                record.get("prediction_column"),
                record.get("probability_column"),
                record.get("residual_column"),
                record.get("output_artifact_id"),
                record.get("output_artifact_path"),
                record.get("output_artifact_format"),
                json_dumps(record.get("metrics_json"), {}),
                json_dumps(record.get("diagnostics_json"), {}),
                json_dumps(record.get("psi_json"), {}),
                json_dumps(record.get("vsi_json"), {}),
                json_dumps(record.get("evidence_links_json"), []),
                json_dumps(record.get("documentation_links_json"), []),
                json_dumps(record.get("lineage_json"), {}),
                record.get("retention_policy") or "standard",
                record.get("archived_at"),
                record.get("checksum"),
                record.get("error_message"),
                record.get("updated_at") or now_iso(),
                record.get("output_dataset_id"),
                record.get("output_dataset_version_id"),
                record.get("registration_status") or "not_registered",
                record.get("registered_at"),
                record.get("registered_by"),
                record.get("model_version_id"),
            ),
        )
        return self.get(record["scoring_run_id"]) or {}

    def mark_registered(self, scoring_run_id: str, *, dataset_id: str, version_id: Optional[str], registered_by: str) -> Dict[str, Any] | None:
        """Phase K cross-link: records that this ScoringRun's output has been
        registered as a Dataset Library asset. Idempotent at the caller level --
        this method itself just writes the four columns; the caller
        (register_scored_dataset) is responsible for checking registration_status
        first so a run is never registered twice."""
        timestamp = now_iso()
        self._write(
            """
            UPDATE scoring_runs
            SET output_dataset_id = ?, output_dataset_version_id = ?, registration_status = 'registered',
                registered_at = ?, registered_by = ?, updated_at = ?
            WHERE scoring_run_id = ?
            """,
            (dataset_id, version_id, timestamp, registered_by, timestamp, scoring_run_id),
        )
        return self.get(scoring_run_id)

    def archive_for_project(self, project_id: str) -> int:
        """Durable-lifecycle hook for project deletion: marks every non-archived
        scoring run for `project_id` as archived, but never deletes the row --
        matches the Dataset Library precedent (assets survive project deletion,
        just unlinked/archived)."""
        rows = self.list(project_id=project_id, include_archived=False, limit=1000)
        timestamp = now_iso()
        for row in rows:
            self._write(
                "UPDATE scoring_runs SET archived_at = ?, updated_at = ? WHERE scoring_run_id = ?",
                (timestamp, timestamp, row["scoring_run_id"]),
            )
        return len(rows)
