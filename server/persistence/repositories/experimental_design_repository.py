from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class ExperimentalDesignRepository(BaseRepository):
    def get_for_project(self, project_id: str) -> Dict[str, Any] | None:
        return self._one(
            "SELECT * FROM experimental_design_studies WHERE project_id = ?",
            (project_id,),
        )

    def get(self, study_id: str) -> Dict[str, Any] | None:
        return self._one(
            "SELECT * FROM experimental_design_studies WHERE study_id = ?",
            (study_id,),
        )

    def upsert_study(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO experimental_design_studies (
              study_id, project_id, current_version, status, contract_hash,
              contract_json, artifacts_json, blockers_json, created_by,
              updated_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(study_id) DO UPDATE SET
              current_version = excluded.current_version,
              status = excluded.status,
              contract_hash = excluded.contract_hash,
              contract_json = excluded.contract_json,
              artifacts_json = excluded.artifacts_json,
              blockers_json = excluded.blockers_json,
              updated_by = excluded.updated_by,
              updated_at = excluded.updated_at
            """,
            (
                record["study_id"],
                record["project_id"],
                int(record.get("current_version") or 0),
                record.get("status") or "draft",
                record.get("contract_hash"),
                json_dumps(record.get("contract_json"), {}),
                json_dumps(record.get("artifacts_json"), {}),
                json_dumps(record.get("blockers_json"), []),
                record.get("created_by"),
                record.get("updated_by"),
                record.get("created_at") or timestamp,
                timestamp,
            ),
        )
        return self.get(record["study_id"]) or {}

    def add_version(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO experimental_design_versions (
              study_version_id, study_id, project_id, version_number,
              contract_hash, change_summary, contract_json, artifacts_json,
              created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["study_version_id"],
                record["study_id"],
                record["project_id"],
                int(record["version_number"]),
                record["contract_hash"],
                record.get("change_summary"),
                json_dumps(record.get("contract_json"), {}),
                json_dumps(record.get("artifacts_json"), {}),
                record.get("created_by"),
                record.get("created_at") or now_iso(),
            ),
        )
        return self._one(
            "SELECT * FROM experimental_design_versions WHERE study_version_id = ?",
            (record["study_version_id"],),
        ) or {}

    def list_versions(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM experimental_design_versions
            WHERE project_id = ?
            ORDER BY version_number DESC
            """,
            (project_id,),
        )

    def get_job(self, job_id: str) -> Dict[str, Any] | None:
        return self._one(
            """
            SELECT * FROM experimental_design_simulation_jobs
            WHERE simulation_job_id = ?
            """,
            (job_id,),
        )

    def list_jobs(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM experimental_design_simulation_jobs
            WHERE project_id = ?
            ORDER BY created_at DESC
            """,
            (project_id,),
        )

    def upsert_job(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO experimental_design_simulation_jobs (
              simulation_job_id, project_id, study_id, study_version,
              design_version, owner_user_id, status, progress, seed,
              iterations, parameters_json, results_json, error_json,
              cancellation_requested, retry_parent_job_id, created_at,
              started_at, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(simulation_job_id) DO UPDATE SET
              status = excluded.status,
              progress = excluded.progress,
              results_json = excluded.results_json,
              error_json = excluded.error_json,
              cancellation_requested = excluded.cancellation_requested,
              started_at = excluded.started_at,
              completed_at = excluded.completed_at,
              updated_at = excluded.updated_at
            """,
            (
                record["simulation_job_id"],
                record["project_id"],
                record["study_id"],
                int(record["study_version"]),
                record["design_version"],
                record["owner_user_id"],
                record.get("status") or "queued",
                float(record.get("progress") or 0),
                int(record.get("seed") or 0),
                int(record.get("iterations") or 0),
                json_dumps(record.get("parameters_json"), {}),
                json_dumps(record.get("results_json"), {}),
                json_dumps(record.get("error_json"), {}),
                1 if record.get("cancellation_requested") else 0,
                record.get("retry_parent_job_id"),
                record.get("created_at") or timestamp,
                record.get("started_at"),
                record.get("completed_at"),
                timestamp,
            ),
        )
        return self.get_job(record["simulation_job_id"]) or {}

    def interrupt_active_jobs(self) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE experimental_design_simulation_jobs
                SET status = 'interrupted',
                    error_json = ?,
                    completed_at = ?,
                    updated_at = ?
                WHERE status IN ('queued', 'running', 'cancelling')
                """,
                (
                    json_dumps(
                        {
                            "code": "server_restart",
                            "message": "The simulation was interrupted by a server restart and can be retried.",
                            "recoverable": True,
                        }
                    ),
                    now_iso(),
                    now_iso(),
                ),
            )
            return int(cursor.rowcount or 0)
