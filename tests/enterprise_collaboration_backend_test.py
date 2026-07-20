from __future__ import annotations

import os
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.admin.admin_service import AdminService
from server.notifications.notification_service import NotificationService
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.sharing.sharing_service import SharingService


ADMIN = {"userId": "user_eecc3a44ed694307", "email": "admin@atlas.local", "displayName": "ATLAS Local Admin", "role": "admin", "status": "active"}
ANALYST = {"userId": "demo_ds_1", "email": "demo.ds1@atlas.local", "displayName": "Demo Analyst", "role": "data_scientist", "status": "active"}
VALIDATOR = {"userId": "demo_validator", "email": "demo.validator@atlas.local", "displayName": "Demo Validator", "role": "validator", "status": "active"}


class EnterpriseCollaborationBackendTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp_root = ROOT / ".tmp"
        tmp_root.mkdir(exist_ok=True)
        self.db_path = tmp_root / f"atlas_enterprise_collab_{uuid.uuid4().hex}.db"
        os.environ["ATLAS_SQLITE_PATH"] = str(self.db_path)
        self.database = Database(self.db_path)
        self.database.initialize()
        self.persistence = PersistenceService(self.database)
        for user in [ADMIN, ANALYST, VALIDATOR]:
            self.persistence.sync_user(user)
        self.project_id = "project_enterprise_collaboration"
        self.persistence.projects.upsert(
            {
                "project_id": self.project_id,
                "project_name": "Enterprise Collaboration Test",
                "project_type": "predictive-modeling",
                "workflow_type": "predictive-modeling",
                "status": "active",
                "owner_user_id": ADMIN["userId"],
                "created_by": ADMIN["userId"],
                "updated_by": ADMIN["userId"],
                "metadata_json": {},
            }
        )
        self.persistence.datasets.upsert(
            {
                "dataset_id": "dataset_enterprise_collaboration",
                "project_id": self.project_id,
                "dataset_name": "Collaboration Dataset",
                "source_type": "uploaded",
                "source_label": "test",
                "metadata_json": {},
            }
        )
        self.admin = AdminService(self.persistence)
        self.sharing = SharingService(self.persistence)
        self.notifications = NotificationService(self.persistence)

    def tearDown(self) -> None:
        os.environ.pop("ATLAS_SQLITE_PATH", None)
        for suffix in ["", "-wal", "-shm"]:
            try:
                self.db_path.with_name(self.db_path.name + suffix).unlink()
            except FileNotFoundError:
                pass

    def test_new_collaboration_tables_exist(self) -> None:
        tables = self.database.health()["tables"]
        for table in ["notifications", "ownership_transfers", "access_reviews", "access_review_items"]:
            self.assertIn(table, tables)

    def test_notification_lifecycle(self) -> None:
        notification = self.notifications.create(
            {
                "recipientUserId": ANALYST["userId"],
                "actorUserId": ADMIN["userId"],
                "notificationType": "project_shared",
                "title": "Project shared",
                "message": "A project was shared.",
                "resourceType": "project",
                "resourceId": self.project_id,
            }
        )
        self.assertEqual(self.notifications.unread_count(ANALYST), 1)
        self.notifications.mark_read(ANALYST, notification["notification_id"])
        self.assertEqual(self.notifications.unread_count(ANALYST), 0)
        dismissed = self.notifications.dismiss(ANALYST, notification["notification_id"])
        self.assertEqual(dismissed["status"], "dismissed")

    def test_share_and_access_request_create_notifications(self) -> None:
        self.sharing.share_resource(ADMIN, "project", self.project_id, {"principalType": "user", "principalId": ANALYST["userId"], "permissionLevel": "view"})
        self.assertGreaterEqual(self.notifications.unread_count(ANALYST), 1)
        request = self.sharing.request_access(VALIDATOR, "project", self.project_id, "validate", "Need validation access.")
        self.assertGreaterEqual(self.notifications.unread_count(ADMIN), 1)
        self.sharing.resolve_access_request(ADMIN, request["request_id"], True, "Approved.")
        self.assertGreaterEqual(self.notifications.unread_count(VALIDATOR), 1)

    def test_audit_search_and_exports_are_real(self) -> None:
        self.sharing.share_resource(ADMIN, "project", self.project_id, {"principalType": "user", "principalId": ANALYST["userId"], "permissionLevel": "view"})
        rows = self.admin.audit_log(ADMIN, {"sharingOnly": True})
        self.assertTrue(any(row["action_type"] == "resource_shared" for row in rows))
        csv_text = self.admin.audit_csv(ADMIN, {"sharingOnly": True})
        self.assertIn("resource_shared", csv_text)

    def test_ownership_transfer_completes_for_project(self) -> None:
        transfer = self.admin.request_ownership_transfer(ADMIN, {"resourceType": "project", "resourceId": self.project_id, "toUserId": ANALYST["userId"], "reason": "Coverage transfer."})
        self.assertEqual(transfer["status"], "completed")
        project = self.persistence.projects.get(self.project_id)
        self.assertEqual(project["owner_user_id"], ANALYST["userId"])

    def test_access_review_keep_and_revoke(self) -> None:
        self.sharing.share_resource(ADMIN, "project", self.project_id, {"principalType": "user", "principalId": ANALYST["userId"], "permissionLevel": "view"})
        review = self.admin.create_access_review(ADMIN, {"reviewName": "Project access review", "resourceType": "project", "resourceId": self.project_id})
        self.assertEqual(len(review["items"]), 1)
        item = self.admin.decide_access_review_item(ADMIN, review["items"][0]["review_item_id"], "revoke", "No longer needed.")
        self.assertEqual(item["decision"], "revoke")
        completed = self.admin.complete_access_review(ADMIN, review["review_id"])
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(self.sharing.check_permission(ANALYST, "project", self.project_id, "view")["allowed"])

    def test_bulk_group_permission_preview_and_apply(self) -> None:
        group = self.admin.create_group(ADMIN, {"groupName": "Forecasting Review Team", "description": "Reviewers"})
        self.admin.add_group_member(ADMIN, group["group_id"], VALIDATOR["userId"])
        preview = self.admin.bulk_permission_preview(ADMIN, {"groupId": group["group_id"], "resourceType": "project", "permissionLevel": "view"})
        self.assertGreaterEqual(preview["affectedCount"], 1)
        result = self.admin.bulk_permission_apply(ADMIN, {"groupId": group["group_id"], "resourceType": "project", "permissionLevel": "view", "resourceIds": [self.project_id]})
        self.assertEqual(result["appliedCount"], 1)
        self.assertTrue(self.sharing.check_permission(VALIDATOR, "project", self.project_id, "view")["allowed"])


if __name__ == "__main__":
    unittest.main()
