from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.admin.admin_service import AdminService
from server.persistence.db import Database, now_iso
from server.persistence.service import PersistenceService
from server.sharing.sharing_service import SharingService


ADMIN = {
    "userId": "user_eecc3a44ed694307",
    "email": "admin@atlas.local",
    "displayName": "ATLAS Local Admin",
    "role": "admin",
    "status": "active",
}

ANALYST = {
    "userId": "demo_ds_1",
    "email": "demo.ds1@atlas.local",
    "displayName": "Demo Data Scientist",
    "role": "data_scientist",
    "status": "active",
}

VALIDATOR = {
    "userId": "demo_validator",
    "email": "demo.validator@atlas.local",
    "displayName": "Demo Validator",
    "role": "validator",
    "status": "active",
}


class AdminSharingBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT / ".tmp"
        tmp_root.mkdir(exist_ok=True)
        self.db_path = tmp_root / f"atlas_admin_sharing_test_{uuid.uuid4().hex}.db"
        os.environ["ATLAS_SQLITE_PATH"] = str(self.db_path)
        self.database = Database(self.db_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        for user in [ADMIN, ANALYST, VALIDATOR]:
            self.persistence.sync_user(user)
        self.project_id = "project_admin_sharing_test"
        self.persistence.projects.upsert(
            {
                "project_id": self.project_id,
                "project_name": "Admin Sharing Test Project",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "status": "active",
                "owner_user_id": ADMIN["userId"],
                "created_by": ADMIN["userId"],
                "updated_by": ADMIN["userId"],
                "metadata_json": {},
            }
        )
        self.admin_service = AdminService(self.persistence)
        self.sharing_service = SharingService(self.persistence)

    def tearDown(self) -> None:
        os.environ.pop("ATLAS_SQLITE_PATH", None)
        for suffix in ["", "-wal", "-shm"]:
            try:
                self.db_path.with_name(self.db_path.name + suffix).unlink()
            except FileNotFoundError:
                pass

    def test_migration_tables_exist(self) -> None:
        health = self.database.health()
        for table in [
            "user_groups",
            "user_group_members",
            "access_policies",
            "resource_permissions",
            "sharing_events",
            "share_links",
            "access_requests",
            "project_collaborators",
        ]:
            self.assertIn(table, health["tables"])

    def test_admin_lists_users_and_manages_groups(self) -> None:
        with patch("server.admin.admin_service.list_users", return_value=[ADMIN, ANALYST, VALIDATOR]), patch(
            "server.admin.admin_service.get_user",
            side_effect=lambda user_id: {user["userId"]: user for user in [ADMIN, ANALYST, VALIDATOR]}.get(user_id),
        ):
            users = self.admin_service.list_users(ADMIN)
            self.assertEqual(len(users), 3)
            group = self.admin_service.create_group(ADMIN, {"groupName": "Model Validators", "description": "Validation team"})
            member = self.admin_service.add_group_member(ADMIN, group["group_id"], VALIDATOR["userId"], "reviewer")
            self.assertEqual(member["user_id"], VALIDATOR["userId"])
            detail = self.admin_service.get_group(ADMIN, group["group_id"])
            self.assertEqual(len(detail["members"]), 1)
            removed = self.admin_service.remove_group_member(ADMIN, group["group_id"], VALIDATOR["userId"])
            self.assertTrue(removed["removed"])

    def test_direct_share_grants_and_revokes_project_access(self) -> None:
        result = self.sharing_service.share_resource(
            ADMIN,
            "project",
            self.project_id,
            {"principalType": "user", "principalId": ANALYST["userId"], "permissionLevel": "edit", "message": "Collaborate on modeling."},
        )
        self.assertEqual(result["permission"]["permission_level"], "edit")
        check = self.sharing_service.check_permission(ANALYST, "project", self.project_id, "view")
        self.assertTrue(check["allowed"])
        status = self.sharing_service.sharing_status(ADMIN, "project", self.project_id)
        self.assertEqual(len(status["permissions"]), 1)
        revoked = self.sharing_service.revoke_share(ADMIN, "project", self.project_id, "user", ANALYST["userId"])
        self.assertTrue(revoked["revoked"])
        check_after = self.sharing_service.check_permission(ANALYST, "project", self.project_id, "view")
        self.assertFalse(check_after["allowed"])

    def test_group_share_conveys_permission(self) -> None:
        group = self.persistence.access.upsert_group(
            {
                "group_id": "group_validation",
                "group_name": "Validation Team",
                "description": "Validators",
                "status": "active",
                "created_by_user_id": ADMIN["userId"],
                "metadata_json": {},
            }
        )
        self.persistence.access.add_group_member(
            {
                "membership_id": "member_validation",
                "group_id": group["group_id"],
                "user_id": VALIDATOR["userId"],
                "role_in_group": "validator",
                "added_by_user_id": ADMIN["userId"],
            }
        )
        self.sharing_service.share_resource(
            ADMIN,
            "project",
            self.project_id,
            {"principalType": "group", "principalId": group["group_id"], "permissionLevel": "validate"},
        )
        check = self.sharing_service.check_permission(VALIDATOR, "project", self.project_id, "validate")
        self.assertTrue(check["allowed"])
        self.assertEqual(check["permission"], "validate")

    def test_access_request_approval_and_denial_are_persisted(self) -> None:
        request = self.sharing_service.request_access(ANALYST, "project", self.project_id, "view", "Need review access.")
        approved = self.sharing_service.resolve_access_request(ADMIN, request["request_id"], True, "Approved.")
        self.assertEqual(approved["status"], "approved")
        check = self.sharing_service.check_permission(ANALYST, "project", self.project_id, "view")
        self.assertTrue(check["allowed"])

        second = self.sharing_service.request_access(VALIDATOR, "project", self.project_id, "approve", "Need approval access.")
        denied = self.sharing_service.resolve_access_request(ADMIN, second["request_id"], False, "Not assigned.")
        self.assertEqual(denied["status"], "denied")

    def test_share_links_are_recorded_as_disabled_local_prototypes(self) -> None:
        link = self.sharing_service.create_share_link(ADMIN, "project", self.project_id, "view", expires_at=now_iso())
        self.assertFalse(link["enabled"])
        self.assertIn("token", link)
        revoked = self.sharing_service.revoke_share_link(ADMIN, link["share_link_id"])
        self.assertEqual(revoked["status"], "revoked")

    def test_audit_log_records_sharing_actions(self) -> None:
        self.sharing_service.share_resource(
            ADMIN,
            "project",
            self.project_id,
            {"principalType": "user", "principalId": ANALYST["userId"], "permissionLevel": "view"},
        )
        with self.database.connection() as connection:
            actions = [
                row["action_type"]
                for row in connection.execute("SELECT action_type FROM audit_log WHERE entity_id = ?", (self.project_id,)).fetchall()
            ]
        self.assertIn("resource_shared", actions)


if __name__ == "__main__":
    unittest.main()
