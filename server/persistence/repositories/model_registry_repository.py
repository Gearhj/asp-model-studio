from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository

_MODEL_FILTERABLE = {"project_id", "problem_type", "status", "owner_user_id"}
_VERSION_FILTERABLE = {"model_id", "algorithm", "approval_status", "validation_status", "training_run_id"}


class ModelRepository(BaseRepository):
    def list(
        self,
        *,
        project_id: Optional[str] = None,
        problem_type: Optional[str] = None,
        status: Optional[str] = None,
        owner_user_id: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        filters = {"project_id": project_id, "problem_type": problem_type, "status": status, "owner_user_id": owner_user_id}
        clauses: List[str] = []
        params: List[Any] = []
        for column, value in filters.items():
            if value is None or column not in _MODEL_FILTERABLE:
                continue
            clauses.append(f"{column} = ?")
            params.append(value)
        if not include_archived:
            clauses.append("archived = 0")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded_limit = max(1, min(int(limit or 200), 1000))
        query = f"SELECT * FROM models {where} ORDER BY created_at DESC LIMIT ?"
        params.append(bounded_limit)
        return self._many(query, tuple(params))

    def get(self, model_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM models WHERE model_id = ?", (model_id,))

    def find_by_name(self, project_id: str, name: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM models WHERE project_id = ? AND name = ? AND archived = 0", (project_id, name))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO models (
              model_id, project_id, name, problem_type, status, owner_user_id,
              created_at, updated_at, current_version_id, archived, archived_at, tags_json, description
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_id) DO UPDATE SET
              status = excluded.status,
              updated_at = excluded.updated_at,
              current_version_id = excluded.current_version_id,
              archived = excluded.archived,
              archived_at = excluded.archived_at,
              tags_json = excluded.tags_json,
              description = excluded.description
            """,
            (
                record["model_id"], record.get("project_id"), record.get("name") or "Untitled Model",
                record.get("problem_type"), record.get("status") or "active", record.get("owner_user_id"),
                timestamp, record.get("updated_at") or timestamp, record.get("current_version_id"),
                int(bool(record.get("archived"))), record.get("archived_at"),
                json_dumps(record.get("tags_json"), []), record.get("description"),
            ),
        )
        return self.get(record["model_id"]) or {}

    def archive_for_project(self, project_id: str) -> int:
        rows = self.list(project_id=project_id, include_archived=False, limit=1000)
        timestamp = now_iso()
        for row in rows:
            self._write(
                "UPDATE models SET archived = 1, archived_at = ?, updated_at = ? WHERE model_id = ?",
                (timestamp, timestamp, row["model_id"]),
            )
        return len(rows)


class ModelVersionRepository(BaseRepository):
    def list(
        self,
        *,
        model_id: Optional[str] = None,
        algorithm: Optional[str] = None,
        approval_status: Optional[str] = None,
        validation_status: Optional[str] = None,
        training_run_id: Optional[str] = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        filters = {
            "model_id": model_id, "algorithm": algorithm, "approval_status": approval_status,
            "validation_status": validation_status, "training_run_id": training_run_id,
        }
        clauses: List[str] = []
        params: List[Any] = []
        for column, value in filters.items():
            if value is None or column not in _VERSION_FILTERABLE:
                continue
            clauses.append(f"{column} = ?")
            params.append(value)
        if not include_archived:
            clauses.append("archived_at IS NULL")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        bounded_limit = max(1, min(int(limit or 200), 1000))
        query = f"SELECT * FROM model_versions {where} ORDER BY version_number DESC LIMIT ?"
        params.append(bounded_limit)
        return self._many(query, tuple(params))

    def get(self, model_version_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM model_versions WHERE model_version_id = ?", (model_version_id,))

    def get_many(self, model_version_ids: List[str]) -> List[Dict[str, Any]]:
        if not model_version_ids:
            return []
        placeholders = ",".join("?" for _ in model_version_ids)
        return self._many(f"SELECT * FROM model_versions WHERE model_version_id IN ({placeholders})", tuple(model_version_ids))

    def next_version_number(self, model_id: str) -> int:
        row = self._one("SELECT MAX(version_number) AS max_version FROM model_versions WHERE model_id = ?", (model_id,))
        current = (row or {}).get("max_version")
        return int(current) + 1 if current is not None else 1

    def insert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """INSERT only -- a ModelVersion's content is immutable once created.
        There is deliberately no upsert/update path for the content columns
        here (see archive() below for the one legitimate later mutation)."""
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO model_versions (
              model_version_id, model_id, version_number, training_run_id, project_id,
              dataset_id, dataset_version_id, feature_manifest_version, algorithm, algorithm_version,
              hyperparameters_json, training_parameters_json, metrics_summary_json,
              evaluation_summary_json, interpretation_summary_json,
              artifact_reference, artifact_format, training_timestamp, checksum,
              approval_status, validation_status, documentation_status, lineage_json,
              archived_at, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["model_version_id"], record["model_id"], int(record["version_number"]),
                record.get("training_run_id"), record.get("project_id"), record.get("dataset_id"),
                record.get("dataset_version_id"), record.get("feature_manifest_version"),
                record.get("algorithm"), record.get("algorithm_version"),
                json_dumps(record.get("hyperparameters_json"), {}), json_dumps(record.get("training_parameters_json"), {}),
                json_dumps(record.get("metrics_summary_json"), {}), json_dumps(record.get("evaluation_summary_json"), {}),
                json_dumps(record.get("interpretation_summary_json"), {}),
                record.get("artifact_reference"), record.get("artifact_format"),
                record.get("training_timestamp"), record.get("checksum"),
                record.get("approval_status") or "unreviewed", record.get("validation_status") or "not_validated",
                record.get("documentation_status") or "not_documented", json_dumps(record.get("lineage_json"), {}),
                record.get("archived_at"), record.get("created_by"), timestamp,
            ),
        )
        return self.get(record["model_version_id"]) or {}

    def set_governance_status(
        self, model_version_id: str, *,
        approval_status: Optional[str] = None, validation_status: Optional[str] = None, documentation_status: Optional[str] = None,
    ) -> Dict[str, Any] | None:
        """The one legitimate class of post-creation mutation: workflow status
        transitions (approval/validation/documentation progress), never the
        model's substantive content (metrics/hyperparameters/artifact/checksum)."""
        current = self.get(model_version_id)
        if current is None:
            return None
        self._write(
            "UPDATE model_versions SET approval_status = ?, validation_status = ?, documentation_status = ? WHERE model_version_id = ?",
            (
                approval_status or current.get("approval_status") or "unreviewed",
                validation_status or current.get("validation_status") or "not_validated",
                documentation_status or current.get("documentation_status") or "not_documented",
                model_version_id,
            ),
        )
        return self.get(model_version_id)

    def archive(self, model_version_id: str) -> Dict[str, Any] | None:
        self._write("UPDATE model_versions SET archived_at = ? WHERE model_version_id = ?", (now_iso(), model_version_id))
        return self.get(model_version_id)

    def archive_for_project(self, project_id: str) -> int:
        rows = self._many("SELECT model_version_id FROM model_versions WHERE project_id = ? AND archived_at IS NULL", (project_id,))
        timestamp = now_iso()
        for row in rows:
            self._write("UPDATE model_versions SET archived_at = ? WHERE model_version_id = ?", (timestamp, row["model_version_id"]))
        return len(rows)
