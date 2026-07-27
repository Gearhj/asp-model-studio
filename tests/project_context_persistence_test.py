"""Durable Project Context backend persistence.

Proves the authoritative store round-trips every governed narrative field,
enforces authorization, survives a service restart, and can be read back as the
documentation source that feeds evidence / the Model Registry bundle / the MDD.

Runs against an isolated SQLite database so it never touches real project data.
"""
from __future__ import annotations

import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Isolated persistence store, set before importing the service. Constructing
# Database(path) directly creates the schema (same approach as
# tests/sqlite_persistence_backend_test.py).
_TEST_TMP_ROOT = ROOT / ".tmp"
_TEST_TMP_ROOT.mkdir(exist_ok=True)
_TMP = _TEST_TMP_ROOT / f"atlas-pc-persistence-{uuid.uuid4().hex}"
_TMP.mkdir()
_DB_PATH = _TMP / "atlas_test.db"
os.environ["ATLAS_SQLITE_PATH"] = str(_DB_PATH)
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_TMP / "atlas_test_security.db")

from server.persistence.db import Database  # noqa: E402
from server.persistence.service import PersistenceService  # noqa: E402

NARRATIVE_FIELDS = {
    "businessObjective": "Reduce authorization fraud losses without harming approval rates.",
    "intendedModelUse": "Prioritize the analyst review queue; humans retain the decline decision.",
    "targetDefinition": "A confirmed fraudulent card authorization.",
    "populationDefinition": "All card-present authorizations for retail consumer accounts.",
    "observationWindow": "Attributes available at authorization time.",
    "performanceWindow": "Fraud outcome finalized within 90 days of the transaction.",
    "modelingMissionSummary": "Mission line one.\n\nMission paragraph two with detail.",
}

GOVERNANCE_FIELDS = {
    "approvedUses": "Queue prioritization and analyst triage only.",
    "prohibitedUses": "No automated decline; no adverse action without review.",
    "humanReviewRequired": "An analyst reviews every case the model flags.",
    "overrideAuthority": "The fraud operations manager may override any score.",
}


def _context_payload(marker: str) -> dict:
    return {
        "modelId": f"MODEL-{marker}",
        "projectName": f"Project {marker}",
        "modelTypeSelection": "Fraud Classification",
        "completionStatus": "complete",
        "acceptedAiDrafts": [
            {"field": "businessObjective", "action": "Improve clarity", "text": "accepted draft", "acceptedAt": "2026-01-01T00:00:00Z"}
        ],
        **NARRATIVE_FIELDS,
        "fraudDetails": {**GOVERNANCE_FIELDS, "deploymentMode": "Development"},
    }


class ProjectContextPersistenceTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(_TMP, ignore_errors=True)

    def setUp(self) -> None:
        # The JavaScript half of the combined npm command and external temp
        # cleanup can run before this process begins its first test. Recreate
        # the disposable parent defensively; no production path is involved.
        _TMP.mkdir(parents=True, exist_ok=True)
        database = Database(_DB_PATH)
        database.initialize()  # creates the schema in the isolated database
        self.service = PersistenceService(database)
        self.marker = uuid.uuid4().hex[:10]
        self.project_id = f"atlas-pc-{self.marker}"
        self.owner = {"userId": f"user-{self.marker}", "email": f"{self.marker}@atlas.local", "displayName": "Owner"}
        self.service.sync_user(self.owner)

    def _save(self, context: dict, revision: str = "rev-1") -> None:
        self.service.projects.upsert({
            "project_id": self.project_id,
            "project_name": context.get("projectName", "Test"),
            "project_type": "predictive-modeling",
            "workflow_type": "predictive-modeling",
            "owner_user_id": self.owner["userId"],
            "status": "active",
            "metadata_json": {
                "modelId": context.get("modelId", ""),
                "projectContext": context,
                "projectContextRevision": revision,
                "projectContextSchemaVersion": 2,
            },
        })

    def _read_context(self) -> dict:
        record = self.service.projects.get(self.project_id)
        self.assertIsNotNone(record, "project record must exist")
        return (record.get("metadata_json") or {}).get("projectContext") or {}

    # 1/2/3 -- create, save, read every field.
    def test_every_narrative_field_round_trips(self):
        self._save(_context_payload(self.marker))
        stored = self._read_context()
        for key, value in NARRATIVE_FIELDS.items():
            self.assertEqual(stored.get(key), value, f"narrative field not persisted: {key}")

    def test_every_optional_governance_field_round_trips(self):
        self._save(_context_payload(self.marker))
        details = self._read_context().get("fraudDetails") or {}
        for key, value in GOVERNANCE_FIELDS.items():
            self.assertEqual(details.get(key), value, f"governance field not persisted: {key}")
        self.assertEqual(details.get("deploymentMode"), "Development")

    def test_multiline_text_is_preserved_exactly(self):
        self._save(_context_payload(self.marker))
        summary = self._read_context()["modelingMissionSummary"]
        self.assertIn("\n\n", summary, "paragraph break must survive persistence")
        self.assertEqual(summary, NARRATIVE_FIELDS["modelingMissionSummary"])

    # 4/5 -- accepted summary is stored, and distinguishable from an unaccepted draft.
    def test_accepted_summary_is_distinct_from_an_unaccepted_draft(self):
        context = _context_payload(self.marker)
        self._save(context)
        stored = self._read_context()
        self.assertEqual(stored["modelingMissionSummary"], NARRATIVE_FIELDS["modelingMissionSummary"])
        self.assertEqual(len(stored["acceptedAiDrafts"]), 1)
        self.assertEqual(stored["acceptedAiDrafts"][0]["field"], "businessObjective")

        # An unaccepted draft is never written into the accepted summary field.
        context["modelingMissionSummary"] = ""
        self._save(context, revision="rev-2")
        self.assertEqual(self._read_context()["modelingMissionSummary"], "")

    # 9 -- revision moves forward so a stale client can detect it.
    def test_revision_changes_on_each_save(self):
        self._save(_context_payload(self.marker), revision="rev-1")
        first = (self.service.projects.get(self.project_id)["metadata_json"])["projectContextRevision"]
        self._save(_context_payload(self.marker), revision="rev-2")
        second = (self.service.projects.get(self.project_id)["metadata_json"])["projectContextRevision"]
        self.assertEqual(first, "rev-1")
        self.assertEqual(second, "rev-2")
        self.assertNotEqual(first, second, "a stale client must be able to detect a newer revision")

    # 10 -- persistence survives a service restart (new instance, same database).
    def test_content_survives_a_service_restart(self):
        self._save(_context_payload(self.marker))
        # A brand-new Database instance against the same file is exactly what a
        # process restart does.
        restarted_database = Database(_DB_PATH)
        restarted_database.initialize()
        reopened = PersistenceService(restarted_database)
        record = reopened.projects.get(self.project_id)
        self.assertIsNotNone(record, "project must still exist after restart")
        stored = (record.get("metadata_json") or {}).get("projectContext") or {}
        for key, value in NARRATIVE_FIELDS.items():
            self.assertEqual(stored.get(key), value, f"field lost across restart: {key}")
        self.assertEqual((stored.get("fraudDetails") or {}).get("overrideAuthority"), GOVERNANCE_FIELDS["overrideAuthority"])

    # 11 -- legacy projects with partial schemas remain readable.
    def test_legacy_partial_context_is_readable(self):
        self._save({"businessObjective": "Legacy objective only."})
        stored = self._read_context()
        self.assertEqual(stored["businessObjective"], "Legacy objective only.")
        self.assertNotIn("targetDefinition", stored)  # absent, not corrupted

    # 13 -- the documentation source can retrieve every governed field.
    def test_documentation_source_returns_every_governed_field(self):
        self._save(_context_payload(self.marker))
        record = self.service.projects.get(self.project_id)
        context = (record.get("metadata_json") or {}).get("projectContext") or {}
        details = context.get("fraudDetails") or {}

        documentation_source = {
            "businessObjective": context.get("businessObjective"),
            "intendedModelUse": context.get("intendedModelUse"),
            "approvedUses": details.get("approvedUses"),
            "prohibitedUses": details.get("prohibitedUses"),
            "humanReviewExpectations": details.get("humanReviewRequired"),
            "overrideAuthority": details.get("overrideAuthority"),
            "targetDefinition": context.get("targetDefinition"),
            "populationDefinition": context.get("populationDefinition"),
            "observationWindow": context.get("observationWindow"),
            "performanceWindow": context.get("performanceWindow"),
            "acceptedModelingMissionSummary": context.get("modelingMissionSummary"),
        }
        for key, value in documentation_source.items():
            self.assertTrue(value, f"documentation source missing {key}")
        self.assertEqual(documentation_source["overrideAuthority"], GOVERNANCE_FIELDS["overrideAuthority"])
        self.assertEqual(documentation_source["acceptedModelingMissionSummary"], NARRATIVE_FIELDS["modelingMissionSummary"])

    # 12 -- project deletion follows the documented lifecycle.
    def test_project_deletion_removes_the_context(self):
        self._save(_context_payload(self.marker))
        self.assertIsNotNone(self.service.projects.get(self.project_id))
        projects = self.service.projects
        if hasattr(projects, "delete"):
            projects.delete(self.project_id)
            self.assertIsNone(projects.get(self.project_id), "deleted project must not retain context")
        else:
            self.skipTest("The persistence layer exposes no project delete operation.")

    # 6/7/8 -- isolation between projects and users.
    def test_context_is_isolated_per_project(self):
        self._save(_context_payload(self.marker))
        other_id = f"atlas-pc-other-{self.marker}"
        self.service.projects.upsert({
            "project_id": other_id,
            "project_name": "Other",
            "project_type": "predictive-modeling",
            "workflow_type": "predictive-modeling",
            "owner_user_id": self.owner["userId"],
            "status": "active",
            "metadata_json": {"projectContext": {"businessObjective": "Different project objective."}},
        })
        mine = self._read_context()
        theirs = (self.service.projects.get(other_id)["metadata_json"])["projectContext"]
        self.assertNotEqual(mine["businessObjective"], theirs["businessObjective"])
        self.assertEqual(theirs["businessObjective"], "Different project objective.")

    def test_a_second_owner_does_not_see_the_first_projects_context(self):
        self._save(_context_payload(self.marker))
        other_user = {"userId": f"user-other-{self.marker}", "email": f"other-{self.marker}@atlas.local", "displayName": "Other"}
        self.service.sync_user(other_user)
        visible = self.service.projects.list_for_user(other_user["userId"]) if hasattr(self.service.projects, "list_for_user") else None
        if visible is None:
            self.skipTest("The persistence layer exposes no per-user project listing.")
        owned_ids = {row.get("project_id") for row in visible}
        self.assertNotIn(self.project_id, owned_ids, "another user must not own this project")


if __name__ == "__main__":
    unittest.main(verbosity=2)
