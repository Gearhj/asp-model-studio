from __future__ import annotations

from typing import Any, Dict, List

from ..db import json_dumps, now_iso
from .base_repository import BaseRepository


class AccessRepository(BaseRepository):
    def list_groups(self) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM user_groups ORDER BY group_name")

    def get_group(self, group_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM user_groups WHERE group_id = ?", (group_id,))

    def upsert_group(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO user_groups (
              group_id, group_name, description, status, created_by_user_id,
              created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
              group_name = excluded.group_name,
              description = excluded.description,
              status = excluded.status,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["group_id"],
                record["group_name"],
                record.get("description"),
                record.get("status") or "active",
                record.get("created_by_user_id"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_group(record["group_id"]) or {}

    def list_group_members(self, group_id: str | None = None) -> List[Dict[str, Any]]:
        if group_id:
            return self._many("SELECT * FROM user_group_members WHERE group_id = ? ORDER BY added_at DESC", (group_id,))
        return self._many("SELECT * FROM user_group_members ORDER BY added_at DESC")

    def list_user_group_ids(self, user_id: str) -> List[str]:
        return [
            row["group_id"]
            for row in self._many(
                "SELECT group_id FROM user_group_members WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
        ]

    def add_group_member(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("added_at") or now_iso()
        self._write(
            """
            INSERT INTO user_group_members (
              membership_id, group_id, user_id, role_in_group, status,
              added_by_user_id, added_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_id, user_id) DO UPDATE SET
              role_in_group = excluded.role_in_group,
              status = excluded.status,
              added_by_user_id = excluded.added_by_user_id,
              added_at = excluded.added_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["membership_id"],
                record["group_id"],
                record["user_id"],
                record.get("role_in_group"),
                record.get("status") or "active",
                record.get("added_by_user_id"),
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one(
            "SELECT * FROM user_group_members WHERE group_id = ? AND user_id = ?",
            (record["group_id"], record["user_id"]),
        ) or {}

    def remove_group_member(self, group_id: str, user_id: str) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute("DELETE FROM user_group_members WHERE group_id = ? AND user_id = ?", (group_id, user_id))
            return int(cursor.rowcount or 0)

    def list_policies(self) -> List[Dict[str, Any]]:
        return self._many("SELECT * FROM access_policies ORDER BY resource_type, permission_level")

    def upsert_policy(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("updated_at") or now_iso()
        self._write(
            """
            INSERT INTO access_policies (
              policy_id, policy_name, description, resource_type, permission_level,
              created_by_user_id, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(policy_id) DO UPDATE SET
              policy_name = excluded.policy_name,
              description = excluded.description,
              permission_level = excluded.permission_level,
              updated_at = excluded.updated_at,
              metadata_json = excluded.metadata_json
            """,
            (
                record["policy_id"],
                record["policy_name"],
                record.get("description"),
                record["resource_type"],
                record["permission_level"],
                record.get("created_by_user_id"),
                record.get("created_at") or timestamp,
                timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM access_policies WHERE policy_id = ?", (record["policy_id"],)) or {}

    def list_permissions_for_resource(self, resource_type: str, resource_id: str) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM resource_permissions
            WHERE resource_type = ? AND resource_id = ? AND status = 'active'
            ORDER BY granted_at DESC
            """,
            (resource_type, resource_id),
        )

    def list_permissions_for_principal(self, principal_type: str, principal_id: str) -> List[Dict[str, Any]]:
        return self._many(
            """
            SELECT * FROM resource_permissions
            WHERE principal_type = ? AND principal_id = ? AND status = 'active'
            ORDER BY granted_at DESC
            """,
            (principal_type, principal_id),
        )

    def list_permissions_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        group_ids = self.list_user_group_ids(user_id)
        rows = self.list_permissions_for_principal("user", user_id)
        for group_id in group_ids:
            rows.extend(self.list_permissions_for_principal("group", group_id))
        return rows

    def grant_permission(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("granted_at") or now_iso()
        self._write(
            """
            INSERT INTO resource_permissions (
              permission_id, resource_type, resource_id, principal_type, principal_id,
              permission_level, granted_by_user_id, granted_at, expires_at, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(resource_type, resource_id, principal_type, principal_id) DO UPDATE SET
              permission_level = excluded.permission_level,
              granted_by_user_id = excluded.granted_by_user_id,
              granted_at = excluded.granted_at,
              expires_at = excluded.expires_at,
              status = 'active',
              metadata_json = excluded.metadata_json
            """,
            (
                record["permission_id"],
                record["resource_type"],
                record["resource_id"],
                record["principal_type"],
                record["principal_id"],
                record["permission_level"],
                record.get("granted_by_user_id"),
                timestamp,
                record.get("expires_at"),
                record.get("status") or "active",
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one(
            """
            SELECT * FROM resource_permissions
            WHERE resource_type = ? AND resource_id = ? AND principal_type = ? AND principal_id = ?
            """,
            (record["resource_type"], record["resource_id"], record["principal_type"], record["principal_id"]),
        ) or {}

    def revoke_permission(self, resource_type: str, resource_id: str, principal_type: str, principal_id: str) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE resource_permissions
                SET status = 'revoked'
                WHERE resource_type = ? AND resource_id = ? AND principal_type = ? AND principal_id = ?
                """,
                (resource_type, resource_id, principal_type, principal_id),
            )
            return int(cursor.rowcount or 0)

    def list_access_requests(self, *, status: str | None = None, requester_user_id: str | None = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM access_requests WHERE 1=1"
        params: list[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if requester_user_id:
            query += " AND requester_user_id = ?"
            params.append(requester_user_id)
        query += " ORDER BY created_at DESC"
        return self._many(query, params)

    def get_access_request(self, request_id: str) -> Dict[str, Any] | None:
        return self._one("SELECT * FROM access_requests WHERE request_id = ?", (request_id,))

    def create_access_request(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("created_at") or now_iso()
        self._write(
            """
            INSERT INTO access_requests (
              request_id, requester_user_id, resource_type, resource_id,
              requested_permission, reason, status, reviewed_by_user_id,
              reviewed_at, review_notes, created_at, updated_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["request_id"],
                record["requester_user_id"],
                record["resource_type"],
                record["resource_id"],
                record["requested_permission"],
                record.get("reason"),
                record.get("status") or "pending",
                record.get("reviewed_by_user_id"),
                record.get("reviewed_at"),
                record.get("review_notes"),
                timestamp,
                record.get("updated_at") or timestamp,
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self.get_access_request(record["request_id"]) or {}

    def resolve_access_request(self, request_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        self._write(
            """
            UPDATE access_requests
            SET status = ?, reviewed_by_user_id = ?, reviewed_at = ?, review_notes = ?, updated_at = ?
            WHERE request_id = ?
            """,
            (
                record["status"],
                record.get("reviewed_by_user_id"),
                record.get("reviewed_at") or now_iso(),
                record.get("review_notes"),
                record.get("updated_at") or now_iso(),
                request_id,
            ),
        )
        return self.get_access_request(request_id) or {}

    def upsert_project_collaborator(self, record: Dict[str, Any]) -> Dict[str, Any]:
        timestamp = record.get("added_at") or now_iso()
        self._write(
            """
            INSERT INTO project_collaborators (
              collaborator_id, project_id, user_id, project_role, added_by_user_id,
              added_at, status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, user_id) DO UPDATE SET
              project_role = excluded.project_role,
              added_by_user_id = excluded.added_by_user_id,
              added_at = excluded.added_at,
              status = excluded.status,
              metadata_json = excluded.metadata_json
            """,
            (
                record["collaborator_id"],
                record["project_id"],
                record["user_id"],
                record["project_role"],
                record.get("added_by_user_id"),
                timestamp,
                record.get("status") or "active",
                json_dumps(record.get("metadata_json"), {}),
            ),
        )
        return self._one("SELECT * FROM project_collaborators WHERE project_id = ? AND user_id = ?", (record["project_id"], record["user_id"])) or {}

    def remove_project_collaborator(self, project_id: str, user_id: str) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(
                "UPDATE project_collaborators SET status = 'revoked' WHERE project_id = ? AND user_id = ?",
                (project_id, user_id),
            )
            return int(cursor.rowcount or 0)
