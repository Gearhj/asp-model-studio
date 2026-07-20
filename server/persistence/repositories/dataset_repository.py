from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class DatasetRepository(BaseRepository):
    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM datasets WHERE project_id = ? ORDER BY created_at DESC", (project_id,))

    def get(self, dataset_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM datasets WHERE dataset_id = ?", (dataset_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO datasets (dataset_id, project_id, dataset_name, source_type, source_label, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_id) DO UPDATE SET
              project_id = excluded.project_id,
              dataset_name = excluded.dataset_name,
              source_type = excluded.source_type,
              source_label = excluded.source_label,
              metadata_json = excluded.metadata_json
            """,
            (
                record["dataset_id"],
                record["project_id"],
                record.get("dataset_name") or "ATLAS Dataset",
                record.get("source_type"),
                record.get("source_label"),
                record.get("created_at") or now_iso(),
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get(record["dataset_id"]) or {}

    def list_versions(self, dataset_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM dataset_versions WHERE dataset_id = ? ORDER BY created_at DESC", (dataset_id,))

    def get_version(self, dataset_version_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM dataset_versions WHERE dataset_version_id = ?", (dataset_version_id,))

    def upsert_version(self, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            INSERT INTO dataset_versions (
              dataset_version_id, dataset_id, version_label, row_count, column_count,
              dataset_hash, created_at, profile_json, schema_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(dataset_version_id) DO UPDATE SET
              version_label = excluded.version_label,
              row_count = excluded.row_count,
              column_count = excluded.column_count,
              dataset_hash = excluded.dataset_hash,
              profile_json = excluded.profile_json,
              schema_json = excluded.schema_json
            """,
            (
                record["dataset_version_id"],
                record["dataset_id"],
                record.get("version_label"),
                record.get("row_count"),
                record.get("column_count"),
                record.get("dataset_hash"),
                record.get("created_at") or now_iso(),
                json_dumps(record.get("profile_json"), {}),
                json_dumps(record.get("schema_json"), {}),
            ),
        )
        return self.get_version(record["dataset_version_id"]) or {}
