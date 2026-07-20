from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any, Dict, List

from fastapi import HTTPException

from ..persistence.db import now_iso
from ..persistence.service import PersistenceService, get_persistence_service

PERMISSION_LEVELS = ["view", "comment", "edit", "validate", "approve", "export", "admin"]
RESOURCE_TYPES = [
    "project",
    "dataset",
    "dataset_version",
    "workflow_state",
    "evidence_artifact",
    "run_record",
    "model_result",
    "scored_dataset",
    "documentation_package",
    "export_artifact",
    "decision_journal_entry",
    "validation_case",
    "registry_asset",
    "audit_log_view",
    "management_dashboard",
    "model_run_result",
    "optimization_solution",
    "forecast_result",
    "evaluation_report",
    "validation_result",
]


def _user_id(user: Dict[str, Any] | None) -> str:
    return str((user or {}).get("userId") or (user or {}).get("user_id") or "")


def _permission_rank(permission: str) -> int:
    normalized = permission if permission in PERMISSION_LEVELS else "view"
    return PERMISSION_LEVELS.index(normalized)


def _audit(service: PersistenceService, actor_id: str, action: str, resource_type: str, resource_id: str, summary: str, metadata: Dict[str, Any] | None = None) -> None:
    service.audit.create(
        {
            "audit_id": f"audit_{uuid.uuid4().hex}",
            "project_id": resource_id if resource_type == "project" else None,
            "user_id": actor_id,
            "action_type": action,
            "entity_type": resource_type,
            "entity_id": resource_id,
            "title": action.replace("_", " ").title(),
            "summary": summary,
            "created_at": now_iso(),
            "metadata_json": metadata or {},
        }
    )


def _notify(
    service: PersistenceService,
    recipient_user_id: str,
    actor_user_id: str,
    notification_type: str,
    title: str,
    message: str,
    resource_type: str,
    resource_id: str,
    *,
    project_id: str | None = None,
    priority: str = "normal",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return service.notifications.create(
        {
            "notification_id": f"notif_{uuid.uuid4().hex}",
            "recipient_user_id": recipient_user_id,
            "actor_user_id": actor_user_id,
            "notification_type": notification_type,
            "title": title,
            "message": message,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "project_id": project_id or (resource_id if resource_type == "project" else None),
            "priority": priority,
            "metadata_json": metadata or {},
        }
    )


class SharingService:
    def __init__(self, persistence: PersistenceService | None = None) -> None:
        self.persistence = persistence or get_persistence_service()

    def _owner_user_id(self, resource_type: str, resource_id: str) -> str | None:
        service = self.persistence
        if resource_type in {"project", "registry_asset", "workflow_state"}:
            project = service.projects.get(resource_id)
            return (project or {}).get("owner_user_id") or (project or {}).get("created_by")
        if resource_type in {"dataset", "dataset_version", "scored_dataset"}:
            dataset_id = resource_id.split(":", 1)[0]
            dataset = service.datasets.get(dataset_id)
            return (dataset or {}).get("owner_user_id") or (dataset or {}).get("created_by")
        table_map = {
            "evidence_artifact": ("evidence_artifacts", "artifact_id"),
            "run_record": ("run_records", "run_id"),
            "model_run_result": ("run_records", "run_id"),
            "documentation_package": ("documentation_packages", "package_id"),
            "export_artifact": ("export_artifacts", "export_id"),
            "optimization_solution": ("export_artifacts", "export_id"),
            "forecast_result": ("export_artifacts", "export_id"),
            "evaluation_report": ("export_artifacts", "export_id"),
            "decision_journal_entry": ("decision_journal", "decision_id"),
            "validation_case": ("validation_cases", "validation_id"),
            "validation_result": ("validation_cases", "validation_id"),
        }
        mapping = table_map.get(resource_type)
        if not mapping:
            return None
        table, key = mapping
        with service.database.connection() as connection:
            row = connection.execute(f"SELECT * FROM {table} WHERE {key} = ?", (resource_id,)).fetchone()
        if not row:
            return None
        return row["created_by"] if "created_by" in row.keys() else row["owner_user_id"] if "owner_user_id" in row.keys() else None

    def check_permission(self, user: Dict[str, Any], resource_type: str, resource_id: str, permission: str = "view") -> Dict[str, Any]:
        user_id = _user_id(user)
        if not user_id:
            return {"allowed": False, "permission": "none", "reason": "No user context."}
        if user.get("role") == "admin":
            return {"allowed": True, "permission": "admin", "reason": "Admin role."}
        owner_id = self._owner_user_id(resource_type, resource_id)
        if owner_id and owner_id == user_id:
            return {"allowed": True, "permission": "admin", "reason": "Resource owner."}
        effective = "none"
        for row in self.persistence.access.list_permissions_for_user(user_id):
            if row.get("resource_type") == resource_type and row.get("resource_id") == resource_id:
                level = str(row.get("permission_level") or "view")
                if effective == "none" or _permission_rank(level) > _permission_rank(effective):
                    effective = level
        allowed = effective != "none" and _permission_rank(effective) >= _permission_rank(permission)
        return {"allowed": allowed, "permission": effective, "reason": "Explicit permission." if allowed else "No active permission."}

    def assert_can_manage(self, user: Dict[str, Any], resource_type: str, resource_id: str) -> None:
        check = self.check_permission(user, resource_type, resource_id, "admin")
        if not check["allowed"] and user.get("role") != "admin":
            owner_id = self._owner_user_id(resource_type, resource_id)
            if owner_id != _user_id(user):
                raise HTTPException(status_code=403, detail="Only the owner or admin can manage access for this resource.")

    def share_resource(self, user: Dict[str, Any], resource_type: str, resource_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if resource_type not in RESOURCE_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported shareable resource type: {resource_type}")
        self.assert_can_manage(user, resource_type, resource_id)
        actor_id = _user_id(user)
        principal_type = payload["principalType"]
        principal_id = payload["principalId"]
        permission_level = payload["permissionLevel"]
        record = self.persistence.access.grant_permission(
            {
                "permission_id": f"perm_{uuid.uuid4().hex}",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "principal_type": principal_type,
                "principal_id": principal_id,
                "permission_level": permission_level,
                "granted_by_user_id": actor_id,
                "expires_at": payload.get("expiresAt"),
                "metadata_json": payload.get("metadata") or {},
            }
        )
        if resource_type == "project" and principal_type == "user":
            self.persistence.access.upsert_project_collaborator(
                {
                    "collaborator_id": f"collab_{uuid.uuid4().hex}",
                    "project_id": resource_id,
                    "user_id": principal_id,
                    "project_role": permission_level,
                    "added_by_user_id": actor_id,
                    "metadata_json": {"source": "resource_permissions"},
                }
            )
        event = self.persistence.sharing.create_event(
            {
                "sharing_event_id": f"share_{uuid.uuid4().hex}",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "shared_by_user_id": actor_id,
                "principal_type": principal_type,
                "principal_id": principal_id,
                "permission_level": permission_level,
                "message": payload.get("message"),
                "metadata_json": {"expiresAt": payload.get("expiresAt")},
            }
        )
        _audit(
            self.persistence,
            actor_id,
            "resource_shared",
            resource_type,
            resource_id,
            f"Shared {resource_type} {resource_id} with {principal_type} {principal_id} as {permission_level}.",
            {"principal_type": principal_type, "principal_id": principal_id, "permission_level": permission_level},
        )
        recipients = [principal_id] if principal_type == "user" else [row["user_id"] for row in self.persistence.access.list_group_members(principal_id) if row.get("status") == "active"]
        for recipient_id in recipients:
            if recipient_id and recipient_id != actor_id:
                _notify(
                    self.persistence,
                    recipient_id,
                    actor_id,
                    f"{resource_type}_shared" if resource_type in {"project", "dataset", "evidence_artifact", "documentation_package", "export_artifact"} else "permission_granted",
                    f"{resource_type.replace('_', ' ').title()} shared with you",
                    f"You were granted {permission_level} access to {resource_type} {resource_id}.",
                    resource_type,
                    resource_id,
                    metadata={"principal_type": principal_type, "principal_id": principal_id, "permission_level": permission_level},
                )
        return {"permission": record, "event": event}

    def revoke_share(self, user: Dict[str, Any], resource_type: str, resource_id: str, principal_type: str, principal_id: str) -> Dict[str, Any]:
        self.assert_can_manage(user, resource_type, resource_id)
        removed = self.persistence.access.revoke_permission(resource_type, resource_id, principal_type, principal_id)
        if resource_type == "project" and principal_type == "user":
            self.persistence.access.remove_project_collaborator(resource_id, principal_id)
        _audit(
            self.persistence,
            _user_id(user),
            "share_revoked",
            resource_type,
            resource_id,
            f"Revoked {principal_type} {principal_id} access to {resource_type} {resource_id}.",
            {"principal_type": principal_type, "principal_id": principal_id},
        )
        return {"revoked": removed}

    def sharing_status(self, user: Dict[str, Any], resource_type: str, resource_id: str) -> Dict[str, Any]:
        permission = self.check_permission(user, resource_type, resource_id)
        if not permission["allowed"] and user.get("role") != "admin":
            self.assert_can_manage(user, resource_type, resource_id)
        permissions = self.persistence.access.list_permissions_for_resource(resource_type, resource_id)
        return {
            "resourceType": resource_type,
            "resourceId": resource_id,
            "currentUserPermission": permission,
            "ownerUserId": self._owner_user_id(resource_type, resource_id),
            "permissions": permissions,
            "events": self.persistence.sharing.list_events_for_resource(resource_type, resource_id),
            "shareLinks": self.persistence.sharing.list_share_links_for_resource(resource_type, resource_id),
        }

    def shared_with_me(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        user_id = _user_id(user)
        rows = self.persistence.access.list_permissions_for_user(user_id)
        return [row for row in rows if row.get("status") == "active"]

    def shared_by_me(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        return self.persistence.sharing.list_events_by_user(_user_id(user))

    def request_access(self, user: Dict[str, Any], resource_type: str, resource_id: str, requested_permission: str, reason: str | None = None) -> Dict[str, Any]:
        record = self.persistence.access.create_access_request(
            {
                "request_id": f"access_{uuid.uuid4().hex}",
                "requester_user_id": _user_id(user),
                "resource_type": resource_type,
                "resource_id": resource_id,
                "requested_permission": requested_permission,
                "reason": reason,
                "metadata_json": {},
            }
        )
        _audit(
            self.persistence,
            _user_id(user),
            "access_requested",
            resource_type,
            resource_id,
            f"Requested {requested_permission} access to {resource_type} {resource_id}.",
            {"reason": reason},
        )
        owner_id = self._owner_user_id(resource_type, resource_id)
        if owner_id and owner_id != _user_id(user):
            _notify(
                self.persistence,
                owner_id,
                _user_id(user),
                "access_requested",
                "Access request submitted",
                f"{_user_id(user)} requested {requested_permission} access to {resource_type} {resource_id}.",
                resource_type,
                resource_id,
                priority="high",
                metadata={"request_id": record["request_id"], "reason": reason},
            )
        return record

    def resolve_access_request(self, user: Dict[str, Any], request_id: str, approved: bool, notes: str | None = None) -> Dict[str, Any]:
        request = self.persistence.access.get_access_request(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Access request not found.")
        self.assert_can_manage(user, request["resource_type"], request["resource_id"])
        status = "approved" if approved else "denied"
        resolved = self.persistence.access.resolve_access_request(
            request_id,
            {
                "status": status,
                "reviewed_by_user_id": _user_id(user),
                "review_notes": notes,
            },
        )
        if approved:
            self.share_resource(
                user,
                request["resource_type"],
                request["resource_id"],
                {
                    "principalType": "user",
                    "principalId": request["requester_user_id"],
                    "permissionLevel": request["requested_permission"],
                    "message": notes,
                },
            )
        _notify(
            self.persistence,
            request["requester_user_id"],
            _user_id(user),
            "access_request_approved" if approved else "access_request_denied",
            "Access request approved" if approved else "Access request denied",
            f"Your request for {request['requested_permission']} access to {request['resource_type']} {request['resource_id']} was {status}.",
            request["resource_type"],
            request["resource_id"],
            priority="high" if approved else "normal",
            metadata={"request_id": request_id, "review_notes": notes},
        )
        _audit(
            self.persistence,
            _user_id(user),
            "access_request_approved" if approved else "access_request_denied",
            request["resource_type"],
            request["resource_id"],
            f"{status.title()} access request {request_id}.",
            {"request_id": request_id, "review_notes": notes},
        )
        return resolved

    def create_share_link(self, user: Dict[str, Any], resource_type: str, resource_id: str, permission_level: str = "view", expires_at: str | None = None) -> Dict[str, Any]:
        self.assert_can_manage(user, resource_type, resource_id)
        token = secrets.token_urlsafe(32)
        record = self.persistence.sharing.create_share_link(
            {
                "share_link_id": f"link_{uuid.uuid4().hex}",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest(),
                "permission_level": permission_level,
                "created_by_user_id": _user_id(user),
                "expires_at": expires_at,
                "metadata_json": {"localPrototype": True, "enabled": False},
            }
        )
        _audit(self.persistence, _user_id(user), "share_link_created", resource_type, resource_id, "Created a guarded local share link.", {"share_link_id": record.get("share_link_id")})
        return {**record, "token": token, "enabled": False}

    def revoke_share_link(self, user: Dict[str, Any], share_link_id: str) -> Dict[str, Any]:
        link = None
        with self.persistence.database.connection() as connection:
            row = connection.execute("SELECT * FROM share_links WHERE share_link_id = ?", (share_link_id,)).fetchone()
            if row:
                link = dict(row)
        if not link:
            raise HTTPException(status_code=404, detail="Share link not found.")
        self.assert_can_manage(user, link["resource_type"], link["resource_id"])
        revoked = self.persistence.sharing.revoke_share_link(share_link_id)
        _audit(self.persistence, _user_id(user), "share_link_revoked", link["resource_type"], link["resource_id"], "Revoked local share link.", {"share_link_id": share_link_id})
        return revoked or {}
