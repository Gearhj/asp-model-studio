from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository

# Scope modes a finding may declare. `legacy_unscoped` exists only for rows
# written before the scope contract, and is never produced by new writes.
GOVERNED_VERSION = "governed_version"
WORKSPACE_DRAFT = "workspace_draft"
LEGACY_UNSCOPED = "legacy_unscoped"
SCOPE_MODES = (GOVERNED_VERSION, WORKSPACE_DRAFT, LEGACY_UNSCOPED)


class TargetFindingRepository(BaseRepository):
    """Durable EDA Target Intelligence findings.

    Every row declares the analytical scope it was written against:

      * a governed finding names the immutable (dataset, version) and the
        artifact checksum;
      * a draft finding names the workspace dataset fingerprint, and never
        claims a dataset version;
      * a legacy finding predates the contract and is labeled as such rather
        than being assumed governed.

    Listing is scope-aware, so a draft finding written against one uploaded file
    does not surface after a different file is loaded, and a governed finding
    for one version never appears against another.
    """

    def upsert(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        scope_mode = record.get("scope_mode") or LEGACY_UNSCOPED
        if scope_mode not in SCOPE_MODES:
            scope_mode = LEGACY_UNSCOPED
        self._write(
            """
            INSERT INTO target_findings (target_finding_id, project_id, dataset_id, dataset_version_id, target,
              analysis_type, title, detail, severity, status, created_by_user_id, created_at, updated_at, metadata_json,
              scope_mode, workspace_fingerprint, artifact_checksum, promoted_from_finding_id, promoted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(target_finding_id) DO UPDATE SET
              title=excluded.title, detail=excluded.detail, severity=excluded.severity,
              status=excluded.status, metadata_json=excluded.metadata_json, updated_at=excluded.updated_at
            """,
            (
                record["target_finding_id"], record["project_id"], record.get("dataset_id") or "",
                record.get("dataset_version_id") or "", record.get("target") or "",
                record.get("analysis_type") or "target_intelligence", record.get("title") or "Target finding",
                record.get("detail") or "", record.get("severity") or "review", record.get("status") or "open",
                record.get("created_by_user_id"), record.get("created_at") or timestamp, timestamp,
                json_dumps(record.get("metadata_json"), {}),
                scope_mode, record.get("workspace_fingerprint") or "", record.get("artifact_checksum") or "",
                record.get("promoted_from_finding_id"), record.get("promoted_at"),
            ),
        )
        return self.get(record["target_finding_id"]) or {}

    def get(self, finding_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM target_findings WHERE target_finding_id = ?", (finding_id,))

    def list(
        self,
        *,
        project_id: str,
        scope_mode: str | None = None,
        dataset_id: str | None = None,
        version_id: str | None = None,
        workspace_fingerprint: str | None = None,
        target: str | None = None,
        include_legacy: bool = True,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        """Scope-aware listing.

        A governed query filters on the exact (dataset, version); a draft query
        filters on the exact workspace fingerprint. Neither can return the
        other's rows, which is what keeps a previous upload's draft findings from
        appearing against a replacement dataset.
        """
        query = "SELECT * FROM target_findings WHERE project_id = ?"
        params: List[Any] = [project_id]

        if scope_mode == GOVERNED_VERSION:
            query += " AND scope_mode = ?"
            params.append(GOVERNED_VERSION)
            if dataset_id:
                query += " AND dataset_id = ?"; params.append(dataset_id)
            if version_id:
                query += " AND dataset_version_id = ?"; params.append(version_id)
        elif scope_mode == WORKSPACE_DRAFT:
            query += " AND scope_mode = ?"
            params.append(WORKSPACE_DRAFT)
            # A draft query without a fingerprint must return nothing rather than
            # every draft in the project -- an unidentified workspace has no
            # claim on another workspace's findings.
            query += " AND workspace_fingerprint = ?"
            params.append(workspace_fingerprint or "\x00-no-fingerprint")
        else:
            if dataset_id:
                query += " AND dataset_id = ?"; params.append(dataset_id)
            if version_id:
                query += " AND dataset_version_id = ?"; params.append(version_id)

        if not include_legacy:
            query += " AND scope_mode <> ?"
            params.append(LEGACY_UNSCOPED)
        if target:
            query += " AND target = ?"
            params.append(target)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return self._many(query, params)

    def list_legacy(self, *, project_id: str, target: str | None = None, limit: int = 200) -> List[Dict[str, Any]]:
        """Legacy rows, surfaced separately so they are visible but never
        presented as governed."""
        query = "SELECT * FROM target_findings WHERE project_id = ? AND scope_mode = ?"
        params: List[Any] = [project_id, LEGACY_UNSCOPED]
        if target:
            query += " AND target = ?"
            params.append(target)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 500)))
        return self._many(query, params)

    def delete(self, finding_id: str) -> None:
        self._write("DELETE FROM target_findings WHERE target_finding_id = ?", (finding_id,))
