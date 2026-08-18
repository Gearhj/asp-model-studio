"""Regression: an absent user context must never become administrator authority.

Engineering integrity audit finding P2-2. ``dataset_registry.current_user()``
previously returned a synthesized ``{"role": "admin"}`` context when there was
neither an authenticated request user nor an explicitly provisioned local
bootstrap user. That is a latent fail-open for any non-request caller
(background jobs, scheduled retraining, ingestion, scoring, monitoring, CLI or
service tasks), because ``user_can_access`` short-circuits to True for admins.

These tests are hermetic: they patch the two collaborators imported into the
``dataset_registry`` module namespace (``active_user`` and ``get_user``) so no
security database, request context, or model training is involved. They pin the
new fail-closed contract while proving explicit and legitimate-bootstrap
authority is unchanged.
"""

import unittest
from unittest.mock import patch

from server.datasets import dataset_registry


ADMIN = {"userId": "user_admin", "role": "admin"}
OWNER = {"userId": "user_owner", "role": "data_scientist"}
VIEWER = {"userId": "user_viewer", "role": "data_scientist"}
LOCAL_BOOTSTRAP_ADMIN = {"userId": "local-user", "role": "admin", "displayName": "Local ATLAS User"}

DATASET = {
    "datasetId": "ds_example",
    "ownerUserId": "user_owner",
    "access": [{"userId": "user_viewer", "role": "viewer"}],
}
NULL_OWNER_DATASET = {"datasetId": "ds_null_owner", "ownerUserId": None, "access": []}


class CurrentUserFailClosedTest(unittest.TestCase):
    # --- fallback contract -------------------------------------------------
    def test_fallback_is_not_admin(self) -> None:
        with patch.object(dataset_registry, "active_user", return_value=None), \
             patch.object(dataset_registry, "get_user", return_value=None):
            context = dataset_registry.current_user()
        self.assertNotEqual(context.get("role"), "admin")
        self.assertEqual(context.get("role"), "none")

    def test_fallback_has_no_identity(self) -> None:
        with patch.object(dataset_registry, "active_user", return_value=None), \
             patch.object(dataset_registry, "get_user", return_value=None):
            context = dataset_registry.current_user()
        self.assertIsNone(context.get("userId"))

    def test_fallback_is_a_copy_not_shared_mutable_state(self) -> None:
        with patch.object(dataset_registry, "active_user", return_value=None), \
             patch.object(dataset_registry, "get_user", return_value=None):
            first = dataset_registry.current_user()
            first["role"] = "admin"  # a caller mutating its copy must not poison the next
            second = dataset_registry.current_user()
        self.assertEqual(second.get("role"), "none")

    # --- fail-closed access without a real user ----------------------------
    def test_user_can_access_fails_closed_without_context(self) -> None:
        with patch.object(dataset_registry, "active_user", return_value=None), \
             patch.object(dataset_registry, "get_user", return_value=None):
            self.assertFalse(dataset_registry.user_can_access(DATASET))
            self.assertFalse(dataset_registry.user_can_access(DATASET, write=True))

    def test_user_can_access_fails_closed_on_null_owner_dataset(self) -> None:
        # Guard against None == None matching a null-owner dataset.
        with patch.object(dataset_registry, "active_user", return_value=None), \
             patch.object(dataset_registry, "get_user", return_value=None):
            self.assertFalse(dataset_registry.user_can_access(NULL_OWNER_DATASET))

    def test_list_accessible_datasets_is_empty_without_context(self) -> None:
        with patch.object(dataset_registry, "active_user", return_value=None), \
             patch.object(dataset_registry, "get_user", return_value=None), \
             patch.object(dataset_registry, "load_registry", return_value={"datasets": [DATASET, NULL_OWNER_DATASET]}), \
             patch.object(dataset_registry, "summarize_dataset", side_effect=lambda item: item):
            self.assertEqual(dataset_registry.list_accessible_datasets(), [])

    # --- explicit authority is unchanged -----------------------------------
    def test_explicit_admin_user_unchanged(self) -> None:
        self.assertTrue(dataset_registry.user_can_access(DATASET, user=ADMIN))
        self.assertTrue(dataset_registry.user_can_access(DATASET, user=ADMIN, write=True))

    def test_explicit_owner_unchanged(self) -> None:
        self.assertTrue(dataset_registry.user_can_access(DATASET, user=OWNER))
        self.assertTrue(dataset_registry.user_can_access(DATASET, user=OWNER, write=True))

    def test_explicit_viewer_read_only_unchanged(self) -> None:
        self.assertTrue(dataset_registry.user_can_access(DATASET, user=VIEWER))
        self.assertFalse(dataset_registry.user_can_access(DATASET, user=VIEWER, write=True))

    def test_unrelated_user_denied(self) -> None:
        stranger = {"userId": "user_stranger", "role": "data_scientist"}
        self.assertFalse(dataset_registry.user_can_access(DATASET, user=stranger))

    # --- legitimate explicit contexts still work ---------------------------
    def test_explicit_active_user_context_is_used(self) -> None:
        with patch.object(dataset_registry, "active_user", return_value=OWNER):
            self.assertEqual(dataset_registry.current_user().get("userId"), "user_owner")
            self.assertTrue(dataset_registry.user_can_access(DATASET))

    def test_local_bootstrap_admin_preserved(self) -> None:
        # An explicitly provisioned local-user (only created under
        # ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP) is a real identity, not synthesized.
        with patch.object(dataset_registry, "active_user", return_value=None), \
             patch.object(dataset_registry, "get_user", return_value=LOCAL_BOOTSTRAP_ADMIN):
            context = dataset_registry.current_user()
        self.assertEqual(context.get("userId"), "local-user")
        self.assertEqual(context.get("role"), "admin")


if __name__ == "__main__":
    unittest.main()
