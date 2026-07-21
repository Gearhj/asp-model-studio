"""Regression tests for FND-003.

FND-003: server/security/security_store.py's authenticate() wrote database
changes (failed_login_count, locked_until) and audit events inside
`with connect() as conn:` and then raised an HTTPException before the block
exited normally. Python's sqlite3 connection context manager rolls back the
transaction when the block exits via an exception, so every failed,
disabled, or locked login attempt silently discarded its own counter update
and audit event -- account lockout never activated and the audit trail had
a blind spot for exactly the events a security review would look for first.

These tests inspect persisted state directly (the users table and the
audit_events table), not just HTTP status codes, per the review brief.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# security_store.DB_PATH is a module-level constant resolved at import time,
# so this must be set BEFORE server.security.security_store is imported for
# the first time in this process. Mirrors the isolation pattern already used
# by tests/sqlite_persistence_backend_test.py and tests/persistence_authorization_test.py.
_TEST_DATA_ROOT = ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(parents=True, exist_ok=True)
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_lockout_security_{uuid.uuid4().hex[:10]}.db"
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")

from fastapi import HTTPException  # noqa: E402

from server.security import security_store  # noqa: E402


def _cleanup_db_files() -> None:
    for suffix in ("", "-wal", "-shm"):
        target = Path(f"{_SECURITY_DB_PATH}{suffix}")
        for attempt in range(25):
            try:
                target.unlink(missing_ok=True)
                break
            except PermissionError:
                if attempt < 24:
                    time.sleep(0.2)


class AuthenticationLockoutTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup_db_files()
        security_store.init_security_store()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    # ---- helpers -----------------------------------------------------

    def _create_user(self, label: str, password: str) -> tuple[str, str]:
        suffix = uuid.uuid4().hex[:10]
        email = f"{label}-{suffix}@atlas-fnd003-test.local"
        user = security_store.create_user(email=email, display_name=f"FND-003 {label}", password=password)
        return user["userId"], email

    def _row(self, user_id: str) -> sqlite3.Row:
        with sqlite3.connect(_SECURITY_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        self.assertIsNotNone(row, f"Expected a persisted user row for {user_id}.")
        return row

    def _events(self, user_id: str, action: Optional[str] = None) -> List[sqlite3.Row]:
        # authenticate() records auth events as resource_type="auth",
        # resource_id=<userId> (the `user_id` positional slot in its
        # audit_event(...) calls is resource_id, not the keyword-only
        # user_id= actor column -- that column reflects the caller's own
        # currently-authenticated session context, which is legitimately
        # empty during an anonymous login attempt). resource_id is the
        # correct, pre-existing way these events identify the affected user.
        with sqlite3.connect(_SECURITY_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            if action:
                return conn.execute(
                    "SELECT * FROM audit_events WHERE resource_id = ? AND action = ? ORDER BY timestamp",
                    (user_id, action),
                ).fetchall()
            return conn.execute("SELECT * FROM audit_events WHERE resource_id = ? ORDER BY timestamp", (user_id,)).fetchall()

    # ---- 1. failed-login counter persistence --------------------------

    def test_failed_login_persists_counter_and_audit_event(self) -> None:
        user_id, email = self._create_user("counter", "CounterTestPass123!")

        with self.assertRaises(HTTPException) as context:
            security_store.authenticate(email, "WrongPassword!")
        self.assertEqual(context.exception.status_code, 401)

        row = self._row(user_id)
        self.assertEqual(row["failed_login_count"], 1)
        self.assertIsNone(row["locked_until"])

        failures = self._events(user_id, "auth.login.failure")
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["outcome"], "failure")
        self.assertEqual(failures[0]["reason"], "Invalid credentials")

    # ---- 2. threshold and lockout --------------------------------------

    def test_threshold_triggers_lockout_and_correct_password_is_still_denied(self) -> None:
        user_id, email = self._create_user("threshold", "ThresholdTestPass123!")

        for _ in range(security_store.LOCKOUT_THRESHOLD):
            with self.assertRaises(HTTPException):
                security_store.authenticate(email, "WrongPassword!")

        row = self._row(user_id)
        self.assertEqual(row["failed_login_count"], security_store.LOCKOUT_THRESHOLD)
        self.assertIsNotNone(row["locked_until"])
        self.assertGreater(row["locked_until"], security_store.now_iso())

        # The correct password must still be rejected while locked.
        with self.assertRaises(HTTPException) as context:
            security_store.authenticate(email, "ThresholdTestPass123!")
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "Email or password is not valid.")

        denials = self._events(user_id, "auth.login.failure")
        # LOCKOUT_THRESHOLD failed-password events plus one locked-account denial.
        self.assertEqual(len(denials), security_store.LOCKOUT_THRESHOLD + 1)
        self.assertEqual(denials[-1]["reason"], "Account locked")
        self.assertEqual(denials[-1]["outcome"], "denied")

    # ---- 3. audit completeness -----------------------------------------

    def test_audit_events_are_not_duplicated_and_success_is_recorded(self) -> None:
        user_id, email = self._create_user("audit-complete", "AuditCompletePass123!")

        for index in range(3):
            with self.assertRaises(HTTPException):
                security_store.authenticate(email, f"WrongPassword{index}!")

        failures = self._events(user_id, "auth.login.failure")
        self.assertEqual(len(failures), 3)
        self.assertEqual(len({row["audit_id"] for row in failures}), 3)  # no duplicate audit rows

        row_after_failures = self._row(user_id)
        self.assertEqual(row_after_failures["failed_login_count"], 3)

        result = security_store.authenticate(email, "AuditCompletePass123!")
        self.assertIn("sessionId", result)

        successes = self._events(user_id, "auth.login.success")
        self.assertEqual(len(successes), 1)

        row_after_success = self._row(user_id)
        self.assertEqual(row_after_success["failed_login_count"], 0)
        self.assertIsNone(row_after_success["locked_until"])
        self.assertIsNotNone(row_after_success["last_login_at"])

    # ---- 4. expiration behavior ------------------------------------------

    def test_expired_lockout_does_not_permanently_block_the_account(self) -> None:
        user_id, email = self._create_user("expired-lockout", "ExpiredLockoutPass123!")
        past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        with sqlite3.connect(_SECURITY_DB_PATH) as conn:
            conn.execute(
                "UPDATE users SET failed_login_count = ?, locked_until = ? WHERE user_id = ?",
                (security_store.LOCKOUT_THRESHOLD, past, user_id),
            )
            conn.commit()

        result = security_store.authenticate(email, "ExpiredLockoutPass123!")
        self.assertIn("sessionId", result)

        row = self._row(user_id)
        self.assertEqual(row["failed_login_count"], 0)
        self.assertIsNone(row["locked_until"])

    # ---- 5. disabled-account denial -------------------------------------

    def test_disabled_account_is_denied_and_recorded_generically(self) -> None:
        user_id, email = self._create_user("disabled", "DisabledPass123!")
        security_store.update_user(user_id, {"status": "inactive"})

        with self.assertRaises(HTTPException) as context:
            security_store.authenticate(email, "DisabledPass123!")
        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "Email or password is not valid.")

        denials = self._events(user_id, "auth.login.failure")
        self.assertEqual(len(denials), 1)
        self.assertEqual(denials[0]["reason"], "Inactive user")
        self.assertEqual(denials[0]["outcome"], "denied")

        # The disabled account's failed_login_count is untouched by a denied
        # attempt (a disabled account isn't accumulating brute-force state).
        row = self._row(user_id)
        self.assertEqual(row["failed_login_count"], 0)

    # ---- 6. response parity across denial reasons ------------------------

    def test_response_parity_across_denial_reasons(self) -> None:
        responses: List[HTTPException] = []

        # Missing user.
        with self.assertRaises(HTTPException) as context:
            security_store.authenticate(f"no-such-user-{uuid.uuid4().hex[:8]}@atlas-fnd003-test.local", "whatever")
        responses.append(context.exception)

        # Wrong password.
        _wrong_user_id, wrong_email = self._create_user("parity-wrong", "ParityWrongPass123!")
        with self.assertRaises(HTTPException) as context:
            security_store.authenticate(wrong_email, "IncorrectPassword!")
        responses.append(context.exception)

        # Disabled account, correct password.
        disabled_user_id, disabled_email = self._create_user("parity-disabled", "ParityDisabledPass123!")
        security_store.update_user(disabled_user_id, {"status": "inactive"})
        with self.assertRaises(HTTPException) as context:
            security_store.authenticate(disabled_email, "ParityDisabledPass123!")
        responses.append(context.exception)

        # Locked account, correct password.
        _locked_user_id, locked_email = self._create_user("parity-locked", "ParityLockedPass123!")
        for _ in range(security_store.LOCKOUT_THRESHOLD):
            with self.assertRaises(HTTPException):
                security_store.authenticate(locked_email, "WrongPassword!")
        with self.assertRaises(HTTPException) as context:
            security_store.authenticate(locked_email, "ParityLockedPass123!")
        responses.append(context.exception)

        for exc in responses:
            self.assertEqual(exc.status_code, 401)
            self.assertEqual(exc.detail, "Email or password is not valid.")


if __name__ == "__main__":
    unittest.main()
