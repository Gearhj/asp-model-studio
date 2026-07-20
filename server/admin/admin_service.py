from __future__ import annotations

import uuid
import csv
import io
import json
from typing import Any, Dict

from fastapi import HTTPException

from ..persistence.db import now_iso
from ..persistence.service import PersistenceService, get_persistence_service
from ..security.security_store import create_user, get_user, list_users, public_user, set_user_role, set_user_status, update_user
from ..sharing.sharing_service import PERMISSION_LEVELS, RESOURCE_TYPES, SharingService, _audit, _user_id

PLATFORM_ROLES = ["admin", "data_scientist", "validator", "manager", "business_owner", "viewer"]


ROLE_DEFINITIONS = {
    "admin": ["manage users", "manage groups", "grant/revoke access", "view all projects", "edit all projects", "view all audit logs", "manage platform settings"],
    "data_scientist": ["create projects", "edit owned/shared projects", "register datasets", "run workflows", "capture evidence", "generate exports", "share owned resources"],
    "validator": ["view assigned validation projects", "view evidence and documentation", "create findings", "approve, return, or reject when assigned"],
    "manager": ["view dashboard", "view registry", "view shared projects", "view documentation and recommendations", "approve only if assigned"],
    "business_owner": ["view assigned projects", "review recommendations", "approve business decisions if assigned", "view implementation plans"],
    "viewer": ["read-only access to shared items"],
}


def _require_admin(user: Dict[str, Any]) -> None:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role is required for this operation.")


class AdminService:
    def __init__(self, persistence: PersistenceService | None = None) -> None:
        self.persistence = persistence or get_persistence_service()
        self.sharing = SharingService(self.persistence)

    def list_users(self, actor: Dict[str, Any]) -> list[Dict[str, Any]]:
        _require_admin(actor)
        rows = []
        for user in list_users():
            persisted = self.persistence.sync_user(user) or {}
            summary = self.persistence.users.activity_summary(user["userId"])
            user_permissions = self.persistence.access.list_permissions_for_user(user["userId"])
            rows.append(
                {
                    **user,
                    "lastActiveAt": persisted.get("last_active_at") or user.get("lastLoginAt"),
                    "sharedResourceCount": len(user_permissions),
                    "projectsOwned": summary.get("projectCount", 0),
                    "evidenceCaptured": summary.get("evidenceCount", 0),
                    "validationsAssigned": summary.get("validationCount", 0),
                    **summary,
                }
            )
        return rows

    def get_user(self, actor: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        _require_admin(actor)
        user = get_user(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found.")
        return public_user(user)

    def create_user(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        user = create_user(
            email=payload["email"],
            display_name=payload["displayName"],
            password=payload.get("password") or "AtlasLocal123!",
            role=payload.get("role") or "data_scientist",
        )
        if payload.get("status") and payload["status"] != user.get("status"):
            user = set_user_status(user["userId"], payload["status"])
        self.persistence.sync_user(user)
        _audit(self.persistence, _user_id(actor), "user_created", "user", user["userId"], f"Created user {user.get('displayName')}.", {"role": user.get("role")})
        return user

    def update_user(self, actor: Dict[str, Any], user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        updates = {key: value for key, value in payload.items() if value is not None}
        if "displayName" in updates:
            updates["displayName"] = updates.pop("displayName")
        result = update_user(user_id, updates)
        self.persistence.sync_user(result)
        _audit(self.persistence, _user_id(actor), "user_updated", "user", user_id, f"Updated user {user_id}.", {"fields": sorted(updates)})
        return result

    def update_role(self, actor: Dict[str, Any], user_id: str, role: str) -> Dict[str, Any]:
        _require_admin(actor)
        result = set_user_role(user_id, role)
        self.persistence.sync_user(result)
        _audit(self.persistence, _user_id(actor), "user_role_changed", "user", user_id, f"Changed user {user_id} role to {role}.", {"role": role})
        return result

    def update_status(self, actor: Dict[str, Any], user_id: str, status: str) -> Dict[str, Any]:
        _require_admin(actor)
        result = set_user_status(user_id, status)
        self.persistence.sync_user(result)
        _audit(self.persistence, _user_id(actor), "user_status_changed", "user", user_id, f"Changed user {user_id} status to {status}.", {"status": status})
        return result

    def list_groups(self, actor: Dict[str, Any]) -> list[Dict[str, Any]]:
        _require_admin(actor)
        members = self.persistence.access.list_group_members()
        counts: dict[str, int] = {}
        for member in members:
            if member.get("status") == "active":
                counts[member["group_id"]] = counts.get(member["group_id"], 0) + 1
        return [{**group, "memberCount": counts.get(group["group_id"], 0)} for group in self.persistence.access.list_groups()]

    def get_group(self, actor: Dict[str, Any], group_id: str) -> Dict[str, Any]:
        _require_admin(actor)
        group = self.persistence.access.get_group(group_id)
        if not group:
            raise HTTPException(status_code=404, detail="Group not found.")
        return {**group, "members": self.persistence.access.list_group_members(group_id)}

    def create_group(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        group = self.persistence.access.upsert_group(
            {
                "group_id": f"group_{uuid.uuid4().hex}",
                "group_name": payload["groupName"],
                "description": payload.get("description"),
                "status": payload.get("status") or "active",
                "created_by_user_id": _user_id(actor),
                "metadata_json": payload.get("metadata") or {},
            }
        )
        _audit(self.persistence, _user_id(actor), "group_created", "user_group", group["group_id"], f"Created group {group['group_name']}.")
        return group

    def update_group(self, actor: Dict[str, Any], group_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        existing = self.persistence.access.get_group(group_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Group not found.")
        group = self.persistence.access.upsert_group(
            {
                **existing,
                "group_id": group_id,
                "group_name": payload.get("groupName") or existing["group_name"],
                "description": payload.get("description", existing.get("description")),
                "status": payload.get("status") or existing.get("status") or "active",
                "updated_at": now_iso(),
                "metadata_json": payload.get("metadata") or existing.get("metadata_json") or {},
            }
        )
        _audit(self.persistence, _user_id(actor), "group_updated", "user_group", group_id, f"Updated group {group_id}.")
        return group

    def add_group_member(self, actor: Dict[str, Any], group_id: str, user_id: str, role_in_group: str | None = None) -> Dict[str, Any]:
        _require_admin(actor)
        if not self.persistence.access.get_group(group_id):
            raise HTTPException(status_code=404, detail="Group not found.")
        if not get_user(user_id):
            raise HTTPException(status_code=404, detail="User not found.")
        member = self.persistence.access.add_group_member(
            {
                "membership_id": f"member_{uuid.uuid4().hex}",
                "group_id": group_id,
                "user_id": user_id,
                "role_in_group": role_in_group,
                "added_by_user_id": _user_id(actor),
            }
        )
        _audit(self.persistence, _user_id(actor), "group_member_added", "user_group", group_id, f"Added user {user_id} to group {group_id}.", {"target_user_id": user_id})
        return member

    def remove_group_member(self, actor: Dict[str, Any], group_id: str, user_id: str) -> Dict[str, Any]:
        _require_admin(actor)
        removed = self.persistence.access.remove_group_member(group_id, user_id)
        _audit(self.persistence, _user_id(actor), "group_member_removed", "user_group", group_id, f"Removed user {user_id} from group {group_id}.", {"target_user_id": user_id})
        return {"removed": removed}

    def grant_permission(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        result = self.sharing.share_resource(
            actor,
            payload["resourceType"],
            payload["resourceId"],
            {
                "principalType": payload["principalType"],
                "principalId": payload["principalId"],
                "permissionLevel": payload["permissionLevel"],
                "expiresAt": payload.get("expiresAt"),
                "metadata": payload.get("metadata") or {},
            },
        )
        _audit(self.persistence, _user_id(actor), "permission_granted", payload["resourceType"], payload["resourceId"], "Granted resource permission.", payload)
        return result["permission"]

    def revoke_permission(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        result = self.sharing.revoke_share(actor, payload["resourceType"], payload["resourceId"], payload["principalType"], payload["principalId"])
        _audit(self.persistence, _user_id(actor), "permission_revoked", payload["resourceType"], payload["resourceId"], "Revoked resource permission.", payload)
        return result

    def summary(self, actor: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        users = self.list_users(actor)
        groups = self.list_groups(actor)
        pending = self.persistence.access.list_access_requests(status="pending")
        active_permissions = []
        with self.persistence.database.connection() as connection:
            active_permissions = [dict(row) for row in connection.execute("SELECT * FROM resource_permissions WHERE status = 'active'").fetchall()]
        role_counts = {role: sum(1 for user in users if user.get("role") == role) for role in PLATFORM_ROLES}
        return {
            "totalUsers": len(users),
            "activeUsers": sum(1 for user in users if user.get("status") == "active"),
            "roleCounts": role_counts,
            "groupCount": len(groups),
            "pendingAccessRequests": len(pending),
            "activeSharedResources": len(active_permissions),
            "permissionLevels": PERMISSION_LEVELS,
            "resourceTypes": RESOURCE_TYPES,
            "roleDefinitions": ROLE_DEFINITIONS,
        }

    def audit_log(self, actor: Dict[str, Any], filters: Dict[str, Any]) -> list[Dict[str, Any]]:
        _require_admin(actor)
        return self.persistence.audit.search(
            user_id=filters.get("userId"),
            action_type=filters.get("actionType"),
            entity_type=filters.get("resourceType"),
            entity_id=filters.get("resourceId"),
            project_id=filters.get("projectId"),
            date_from=filters.get("dateFrom"),
            date_to=filters.get("dateTo"),
            text=filters.get("text"),
            sharing_only=bool(filters.get("sharingOnly")),
            admin_only=bool(filters.get("adminOnly")),
            limit=int(filters.get("limit") or 1000),
        )

    def audit_csv(self, actor: Dict[str, Any], filters: Dict[str, Any]) -> str:
        rows = self.audit_log(actor, filters)
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["created_at", "user_id", "action_type", "entity_type", "entity_id", "project_id", "title", "summary", "metadata_json"])
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row.get(field), sort_keys=True) if isinstance(row.get(field), (dict, list)) else row.get(field) for field in writer.fieldnames})
        return output.getvalue()

    def request_ownership_transfer(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        resource_type = payload["resourceType"]
        resource_id = payload["resourceId"]
        self.sharing.assert_can_manage(actor, resource_type, resource_id)
        from_user_id = self.sharing._owner_user_id(resource_type, resource_id)
        record = self.persistence.collaboration.create_ownership_transfer(
            {
                "transfer_id": f"transfer_{uuid.uuid4().hex}",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "from_user_id": from_user_id,
                "to_user_id": payload["toUserId"],
                "requested_by_user_id": _user_id(actor),
                "status": "approved" if actor.get("role") == "admin" else "pending",
                "reason": payload.get("reason"),
                "approved_by_user_id": _user_id(actor) if actor.get("role") == "admin" else None,
                "approved_at": now_iso() if actor.get("role") == "admin" else None,
                "metadata_json": {},
            }
        )
        _audit(self.persistence, _user_id(actor), "ownership_transfer_requested", resource_type, resource_id, "Requested ownership transfer.", record)
        if actor.get("role") == "admin":
            record = self.complete_ownership_transfer(actor, record["transfer_id"])
        return record

    def complete_ownership_transfer(self, actor: Dict[str, Any], transfer_id: str) -> Dict[str, Any]:
        _require_admin(actor)
        transfer = self.persistence.collaboration.get_ownership_transfer(transfer_id)
        if not transfer:
            raise HTTPException(status_code=404, detail="Ownership transfer not found.")
        resource_type = transfer["resource_type"]
        resource_id = transfer["resource_id"]
        to_user_id = transfer["to_user_id"]
        if resource_type in {"project", "registry_asset", "workflow_state"}:
            project = self.persistence.projects.get(resource_id)
            if project:
                self.persistence.projects.upsert({**project, "owner_user_id": to_user_id, "updated_by": _user_id(actor)})
        elif resource_type in {"dataset", "dataset_version", "scored_dataset"}:
            with self.persistence.database.transaction() as connection:
                connection.execute(
                    "UPDATE datasets SET metadata_json = json_set(COALESCE(metadata_json, '{}'), '$.owner_user_id', ?) WHERE dataset_id = ?",
                    (to_user_id, resource_id.split(":", 1)[0]),
                )
        resolved = self.persistence.collaboration.update_ownership_transfer(
            transfer_id,
            {"status": "completed", "approved_by_user_id": _user_id(actor), "approved_at": transfer.get("approved_at") or now_iso(), "completed_at": now_iso()},
        )
        _audit(self.persistence, _user_id(actor), "ownership_transfer_completed", resource_type, resource_id, "Completed ownership transfer.", resolved)
        self.persistence.notifications.create(
            {
                "notification_id": f"notif_{uuid.uuid4().hex}",
                "recipient_user_id": to_user_id,
                "actor_user_id": _user_id(actor),
                "notification_type": "ownership_transferred",
                "title": "Ownership transferred to you",
                "message": f"You are now recorded as owner for {resource_type} {resource_id}.",
                "resource_type": resource_type,
                "resource_id": resource_id,
                "project_id": resource_id if resource_type == "project" else None,
                "priority": "high",
                "metadata_json": {"transfer_id": transfer_id},
            }
        )
        return resolved

    def reject_ownership_transfer(self, actor: Dict[str, Any], transfer_id: str, notes: str | None = None) -> Dict[str, Any]:
        _require_admin(actor)
        transfer = self.persistence.collaboration.update_ownership_transfer(transfer_id, {"status": "rejected", "metadata_json": {"notes": notes}})
        _audit(self.persistence, _user_id(actor), "ownership_transfer_rejected", transfer.get("resource_type", "resource"), transfer.get("resource_id", transfer_id), "Rejected ownership transfer.", transfer)
        return transfer

    def create_access_review(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        review = self.persistence.collaboration.create_access_review(
            {
                "review_id": f"review_{uuid.uuid4().hex}",
                "review_name": payload["reviewName"],
                "resource_type": payload.get("resourceType"),
                "resource_id": payload.get("resourceId"),
                "scope": payload.get("scope") or "resource",
                "owner_user_id": payload.get("ownerUserId"),
                "status": "active",
                "due_date": payload.get("dueDate"),
                "created_by_user_id": _user_id(actor),
                "metadata_json": {},
            }
        )
        permissions = []
        if payload.get("resourceType") and payload.get("resourceId"):
            permissions = self.persistence.access.list_permissions_for_resource(payload["resourceType"], payload["resourceId"])
        elif payload.get("ownerUserId"):
            permissions = [row for row in self.persistence.access.list_permissions_for_user(payload["ownerUserId"]) if row.get("status") == "active"]
        for permission in permissions:
            self.persistence.collaboration.create_access_review_item(
                {
                    "review_item_id": f"review_item_{uuid.uuid4().hex}",
                    "review_id": review["review_id"],
                    "resource_type": permission["resource_type"],
                    "resource_id": permission["resource_id"],
                    "principal_type": permission["principal_type"],
                    "principal_id": permission["principal_id"],
                    "permission_level": permission["permission_level"],
                    "metadata_json": {"permission_id": permission.get("permission_id")},
                }
            )
        _audit(self.persistence, _user_id(actor), "access_review_created", payload.get("resourceType") or "access_review", payload.get("resourceId") or review["review_id"], "Created access review.", review)
        return {**review, "items": self.persistence.collaboration.list_access_review_items(review["review_id"])}

    def decide_access_review_item(self, actor: Dict[str, Any], review_item_id: str, decision: str, notes: str | None = None) -> Dict[str, Any]:
        _require_admin(actor)
        item = self.persistence.collaboration.decide_access_review_item(review_item_id, decision, _user_id(actor), notes)
        if decision == "revoke":
            self.persistence.access.revoke_permission(item["resource_type"], item["resource_id"], item["principal_type"], item["principal_id"])
        _audit(self.persistence, _user_id(actor), f"access_review_item_{decision}", item["resource_type"], item["resource_id"], f"Access review decision: {decision}.", item)
        return item

    def complete_access_review(self, actor: Dict[str, Any], review_id: str) -> Dict[str, Any]:
        _require_admin(actor)
        review = self.persistence.collaboration.update_access_review(review_id, {"status": "completed", "completed_at": now_iso()})
        _audit(self.persistence, _user_id(actor), "access_review_completed", review.get("resource_type") or "access_review", review.get("resource_id") or review_id, "Completed access review.", review)
        return {**review, "items": self.persistence.collaboration.list_access_review_items(review_id)}

    def list_access_reviews(self, actor: Dict[str, Any]) -> list[Dict[str, Any]]:
        _require_admin(actor)
        reviews = self.persistence.collaboration.list_access_reviews()
        return [{**review, "items": self.persistence.collaboration.list_access_review_items(review["review_id"])} for review in reviews]

    def list_ownership_transfers(self, actor: Dict[str, Any]) -> list[Dict[str, Any]]:
        _require_admin(actor)
        return self.persistence.collaboration.list_ownership_transfers()

    def _bulk_resources(self, payload: Dict[str, Any]) -> list[Dict[str, Any]]:
        resource_type = payload["resourceType"]
        if resource_type == "project":
            rows = self.persistence.projects.list()
            if payload.get("workflowType"):
                rows = [row for row in rows if row.get("workflow_type") == payload["workflowType"]]
            if payload.get("ownerUserId"):
                rows = [row for row in rows if row.get("owner_user_id") == payload["ownerUserId"]]
            if payload.get("lifecycleStatus"):
                rows = [row for row in rows if row.get("status") == payload["lifecycleStatus"]]
            return [{"resourceType": "project", "resourceId": row["project_id"], "resourceName": row.get("project_name")} for row in rows]
        if resource_type == "dataset":
            with self.persistence.database.connection() as connection:
                rows = [dict(row) for row in connection.execute("SELECT * FROM datasets ORDER BY created_at DESC").fetchall()]
            return [{"resourceType": "dataset", "resourceId": row["dataset_id"], "resourceName": row.get("dataset_name")} for row in rows]
        if resource_type == "validation_case":
            return [{"resourceType": "validation_case", "resourceId": row["validation_id"], "resourceName": row.get("summary") or row["validation_id"]} for row in self.persistence.validation.list_cases(limit=500)]
        return []

    def bulk_permission_preview(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        resources = self._bulk_resources(payload)
        return {"groupId": payload["groupId"], "permissionLevel": payload["permissionLevel"], "resourceType": payload["resourceType"], "resources": resources, "affectedCount": len(resources)}

    def bulk_permission_apply(self, actor: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        _require_admin(actor)
        preview = self.bulk_permission_preview(actor, payload)
        selected_ids = set(payload.get("resourceIds") or [row["resourceId"] for row in preview["resources"]])
        applied = []
        for resource in preview["resources"]:
            if resource["resourceId"] not in selected_ids:
                continue
            applied.append(
                self.sharing.share_resource(
                    actor,
                    resource["resourceType"],
                    resource["resourceId"],
                    {
                        "principalType": "group",
                        "principalId": payload["groupId"],
                        "permissionLevel": payload["permissionLevel"],
                        "expiresAt": payload.get("expiresAt"),
                        "metadata": {"bulkAccess": True},
                    },
                )["permission"]
            )
        _audit(self.persistence, _user_id(actor), "bulk_group_permission_applied", payload["resourceType"], payload["groupId"], f"Applied bulk group access to {len(applied)} resources.", {"resource_ids": [row["resource_id"] for row in applied]})
        return {"appliedCount": len(applied), "permissions": applied}
