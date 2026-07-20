from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class ExportRepository(BaseRepository):
    def list_for_project(self, project_id: str) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM export_artifacts WHERE project_id = ? ORDER BY created_at DESC", (project_id,))

    def get(self, export_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM export_artifacts WHERE export_id = ?", (export_id,))

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        requested_path = record.get("file_path")
        storage_mode = record.get("storage_mode") or (
            "server_file" if requested_path and requested_path not in {"-", "client_generated", "not_applicable_client_download"}
            else "client_generated"
        )
        file_path = requested_path if storage_mode == "server_file" else "not_applicable_client_download"
        self._write(
            """
            INSERT INTO export_artifacts (
              export_id, project_id, export_type, file_name, file_path,
              created_by, created_at, artifact_hash, metadata_json, storage_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(export_id) DO UPDATE SET
              export_type = excluded.export_type,
              file_name = excluded.file_name,
              file_path = excluded.file_path,
              artifact_hash = excluded.artifact_hash,
              metadata_json = excluded.metadata_json,
              storage_mode = excluded.storage_mode
            """,
            (
                record["export_id"],
                record["project_id"],
                record.get("export_type") or "download",
                record.get("file_name") or "atlas-export",
                file_path,
                record.get("created_by"),
                record.get("created_at") or now_iso(),
                record.get("artifact_hash"),
                json_dumps(record.get("metadata_json"), {}),
                storage_mode,
            ),
        )
        return self.get(record["export_id"]) or {}
