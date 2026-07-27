"""Router-level API integration tests for FND-005.

FND-005: server/validation/validation_service.py's approve() checked only
that the caller held a qualifying validator role (VALIDATOR_ROLES); it never
checked whether the caller was the same person who submitted the case
(validation_cases.submitted_by), so a validator/manager/admin who submitted
their own project's validation case could also approve it themselves --
self-approval, which financial-services model governance requires be
impossible regardless of role.

These tests drive the real FastAPI app through fastapi.testclient -- real
HTTP requests, real routing, real Depends(require_user) -- rather than
calling ValidationService directly, per the task's requirement not to rely
solely on service-level unit tests.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# security_store.DB_PATH is a module-level constant resolved at import time,
# so this must be set BEFORE server.main (or anything importing
# server.security.security_store) is imported for the first time in this
# process. Mirrors tests/persistence_authorization_test.py and
# tests/project_access_consolidation_test.py.
_TEST_DATA_ROOT = ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_validation_sod_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_validation_sod_persistence_{_RUN_ID}.db"
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import create_user, init_security_store  # noqa: E402


def _cleanup_db_files() -> None:
    for base in (_SECURITY_DB_PATH, _PERSISTENCE_DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(25):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 24:
                        time.sleep(0.2)


class ValidationSegregationOfDutiesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    # ---- helpers -----------------------------------------------------

    def _register(self, label: str, role: str = "validator") -> tuple[TestClient, str]:
        client = TestClient(app)
        suffix = uuid.uuid4().hex[:10]
        email = f"{label}-{suffix}@atlas-fnd005-test.local"
        created = create_user(
            email=email,
            display_name=f"FND-005 Test {label} {suffix}",
            password="AuthFnd005TestPass!",
            role=role,
        )
        response = client.post(
            "/api/auth/login",
            json={"email": email, "password": "AuthFnd005TestPass!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return client, created["userId"]

    def _create_project(self, client: TestClient, name: str) -> str:
        response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["project"]["projectId"]

    def _submit_case(self, client: TestClient, project_id: str) -> str:
        response = client.post(
            f"/api/validation/project/{project_id}/submit",
            json={"risk_tier": "Tier 2", "summary": "Submitted for FND-005 testing."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["case"]["validation_id"]

    def _case_row(self, validation_id: str) -> sqlite3.Row:
        with sqlite3.connect(_PERSISTENCE_DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM validation_cases WHERE validation_id = ?", (validation_id,)).fetchone()
        self.assertIsNotNone(row)
        return row

    def _self_approval_denied_audit_rows(self, validation_id: str) -> list[sqlite3.Row]:
        with sqlite3.connect(_PERSISTENCE_DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(
                "SELECT * FROM audit_log WHERE entity_id = ? AND action_type = 'validation.self_approval_denied'",
                (validation_id,),
            ).fetchall()

    def _approval_rows(self, validation_id: str) -> list[sqlite3.Row]:
        with sqlite3.connect(_PERSISTENCE_DB_PATH) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute("SELECT * FROM validation_approvals WHERE validation_id = ?", (validation_id,)).fetchall()

    # ---- 1. submitter cannot approve their own case ---------------------

    def test_submitter_cannot_approve_own_validation_case(self) -> None:
        # Registered with a qualifying validator role so the denial is
        # specifically the segregation-of-duties rule, not a plain role check.
        submitter, _submitter_id = self._register("submitter", role="validator")
        project_id = self._create_project(submitter, "FND-005 Self-Approval Project")
        validation_id = self._submit_case(submitter, project_id)

        response = submitter.post(f"/api/validation/cases/{validation_id}/approvals", json={"decision": "approved"})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            response.json()["detail"],
            "This validation case must be approved by another qualified validator.",
        )

        self.assertEqual(self._approval_rows(validation_id), [])
        audit_rows = self._self_approval_denied_audit_rows(validation_id)
        self.assertEqual(len(audit_rows), 1)
        self.assertIsNotNone(audit_rows[0]["created_at"])

    # ---- 2. a different qualified validator can approve normally --------

    def test_different_validator_can_approve(self) -> None:
        submitter, _submitter_id = self._register("owner-sub", role="validator")
        approver, approver_id = self._register("approver", role="validator")
        project_id = self._create_project(submitter, "FND-005 Cross-Validator Project")
        validation_id = self._submit_case(submitter, project_id)

        response = approver.post(
            f"/api/validation/cases/{validation_id}/approvals",
            json={"decision": "approved", "decision_rationale": "Independently reviewed and approved."},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["case"]["status"], "approved")

        approvals = self._approval_rows(validation_id)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["approver_user_id"], approver_id)
        self.assertEqual(self._self_approval_denied_audit_rows(validation_id), [])

    # ---- 3. administrator behavior: role policy preserved, SoD applies uniformly

    def test_administrator_can_approve_a_case_they_did_not_submit(self) -> None:
        # Existing policy: "admin" is in VALIDATOR_ROLES and may approve
        # cases like any other qualifying validator. That is unchanged here.
        submitter, _submitter_id = self._register("admin-case-owner", role="data_scientist")
        admin, admin_id = self._register("admin-approver", role="admin")
        project_id = self._create_project(submitter, "FND-005 Admin Approval Project")
        validation_id = self._submit_case(submitter, project_id)

        response = admin.post(f"/api/validation/cases/{validation_id}/approvals", json={"decision": "approved"})
        self.assertEqual(response.status_code, 200, response.text)
        approvals = self._approval_rows(validation_id)
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0]["approver_user_id"], admin_id)

    def test_administrator_cannot_approve_their_own_submission(self) -> None:
        # No new administrator behavior is introduced: there was no existing
        # rule granting admins an exception from being a different person
        # than the submitter (there was no such rule for anyone -- that was
        # the bug), so the segregation-of-duties check applies to an admin
        # exactly as it does to any other role.
        admin, _admin_id = self._register("admin-self", role="admin")
        project_id = self._create_project(admin, "FND-005 Admin Self-Approval Project")
        validation_id = self._submit_case(admin, project_id)

        response = admin.post(f"/api/validation/cases/{validation_id}/approvals", json={"decision": "approved"})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(self._approval_rows(validation_id), [])

    # ---- 4. denied self-approval leaves the case completely unchanged ----

    def test_denied_self_approval_leaves_validation_case_unchanged(self) -> None:
        submitter, _submitter_id = self._register("unchanged-sub", role="validator")
        project_id = self._create_project(submitter, "FND-005 Status Integrity Project")
        validation_id = self._submit_case(submitter, project_id)

        before = dict(self._case_row(validation_id))

        response = submitter.post(f"/api/validation/cases/{validation_id}/approvals", json={"decision": "approved"})
        self.assertEqual(response.status_code, 403, response.text)

        after = dict(self._case_row(validation_id))
        self.assertEqual(before["status"], after["status"])
        self.assertEqual(before["business_status_label"], after["business_status_label"])
        self.assertEqual(before["final_disposition"], after["final_disposition"])
        self.assertEqual(before["final_score"], after["final_score"])
        self.assertEqual(before["review_completed_at"], after["review_completed_at"])
        self.assertEqual(before["updated_at"], after["updated_at"])
        self.assertIsNone(after["review_completed_at"])
        self.assertIsNone(after["final_disposition"])

    # ---- owner-is-submitter framing from the task brief -------------------

    def test_project_owner_who_is_also_submitter_cannot_approve(self) -> None:
        # The project owner (projects.owner_user_id, set to the creator at
        # project-creation time) is, in this scenario, also the submitter --
        # exactly the case the brief calls out explicitly. It is denied for
        # the same reason as test 1: approver_id == submitted_by.
        owner, _owner_id = self._register("owner-submitter", role="manager")
        project_id = self._create_project(owner, "FND-005 Owner-Submitter Project")
        validation_id = self._submit_case(owner, project_id)

        response = owner.post(f"/api/validation/cases/{validation_id}/approvals", json={"decision": "approved"})
        self.assertEqual(response.status_code, 403, response.text)


if __name__ == "__main__":
    unittest.main()
