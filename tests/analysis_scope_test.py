"""ATLAS EDA Governed Analysis Scope and Evidence Integrity, Phase 1 -- backend tests.

Covers the governance half of Target Intelligence: that the SERVER decides
whether an analysis is governed, that a workspace draft cannot become governed
evidence by any request the browser can craft, that findings are scoped honestly,
and that event prevalence and class imbalance are semantically distinct.

Registers a genuine Dataset Library asset (so the governed path exercises real
version resolution and a real artifact checksum) into a temp library root that is
removed on teardown.

Run:  .venv/Scripts/python.exe tests/analysis_scope_test.py
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
_TEST_DATA_ROOT = _REPO_ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_scope_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_scope_persistence_{_RUN_ID}.db"
_CHECKPOINT_PATH = _TEST_DATA_ROOT / f"atlas_scope_checkpoint_{_RUN_ID}.json"
_LIBRARY_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_scope_library_{_RUN_ID}_"))
_EVIDENCE_ROOT = _TEST_DATA_ROOT / f"atlas_scope_evidence_{_RUN_ID}"
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_EVIDENCE_ROOT"] = str(_EVIDENCE_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.analytics import analysis_scope as scope_module  # noqa: E402
from server.analytics import target_intelligence_service as tis  # noqa: E402
from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402


CLASS_TRAIN_ROWS = 170_884
CLASS_TRAIN_EVENTS = 360
CLASS_TRAIN_NON_EVENTS = 170_524
CLASS_TRAIN_EVENT_RATE = 360 / 170_884


def _cleanup() -> None:
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
    checkpoint.CHECKPOINT_PATH.unlink(missing_ok=True)
    shutil.rmtree(_EVIDENCE_ROOT, ignore_errors=True)


def _register(label: str) -> TestClient:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post("/api/auth/register", json={
        "email": f"{label}-{suffix}@atlas-scope-test.local",
        "displayName": f"Scope {label} {suffix}",
        "password": "ScopeTestPass!1",
        "role": "data_scientist",
    })
    assert response.status_code == 200, response.text
    return client


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _frame(rows: int = 900, event_every: int = 30, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "V4": rng.normal(size=rows).round(5),
        "Amount": rng.gamma(2.0, 30.0, size=rows).round(2),
        "Class": [1 if index % event_every == 0 else 0 for index in range(rows)],
    })


def _csv_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode("utf-8")


def _register_dataset(client: TestClient, project_id: str, frame: pd.DataFrame, name: str) -> tuple[str, str]:
    """Registers a real Dataset Library asset and links it to the project."""
    response = client.post(
        "/api/datasets/upload",
        files={"file": (f"{name}.csv", _csv_bytes(frame), "text/csv")},
        data={"name": name, "description": "scope test asset", "domain": "general", "projectId": project_id},
    )
    assert response.status_code == 200, response.text
    dataset = response.json()["dataset"]
    dataset_id = dataset["datasetId"]
    version_id = (dataset.get("latestVersion") or (dataset.get("versions") or [])[-1])["versionId"]
    link = client.post(f"/api/projects/{project_id}/datasets/link", json={
        "datasetId": dataset_id, "versionId": version_id, "role": "modeling",
    })
    assert link.status_code == 200, link.text
    activation = client.post(
        f"/api/datasets/{dataset_id}/versions/{version_id}/activate",
        params={"project_id": project_id},
    )
    assert activation.status_code == 200, activation.text
    return dataset_id, version_id


def _load_workspace(client: TestClient, project_id: str, frame: pd.DataFrame) -> None:
    response = client.post("/api/data/set_sample", json={
        "project_id": project_id,
        "headers": [str(column) for column in frame.columns],
        "rows": frame.to_dict(orient="records"),
        "target": "Class",
        "selected_columns": [column for column in frame.columns if column != "Class"],
    })
    assert response.status_code == 200, response.text


# ---------------------------------------------------------------------------
# 19-22 -- event prevalence vs class imbalance semantics (pure functions)
# ---------------------------------------------------------------------------


class PrevalenceAndImbalanceSemanticsTests(unittest.TestCase):
    # 19
    def test_event_minority_semantics_class_train(self):
        result = tis.assess_class_balance(CLASS_TRAIN_EVENTS, CLASS_TRAIN_NON_EVENTS)
        self.assertEqual(result["label"], "Extreme rare event")
        self.assertTrue(result["eventIsRare"])
        self.assertFalse(result["eventIsMajority"])
        self.assertEqual(result["classImbalance"]["label"], "Extreme imbalance")
        self.assertEqual(result["classImbalance"]["minorityClass"], "event")
        self.assertAlmostEqual(result["eventPrevalence"]["eventRate"], CLASS_TRAIN_EVENT_RATE, places=12)
        self.assertAlmostEqual(result["nonEventsPerEvent"], 473.6777777, places=5)
        self.assertAlmostEqual(result["majorityToMinorityRatio"], 473.6777777, places=5)
        self.assertIn("PR-AUC", " ".join(result["implications"]))

    # 20
    def test_event_majority_semantics(self):
        """The reversed configuration: the configured event occurs in 99.79% of rows."""
        result = tis.assess_class_balance(CLASS_TRAIN_NON_EVENTS, CLASS_TRAIN_EVENTS)
        # It is NOT a rare event, and must not be labelled one.
        self.assertNotIn("rare", result["label"].lower())
        self.assertEqual(result["label"], "Common event")
        self.assertFalse(result["eventIsRare"])
        self.assertTrue(result["eventIsMajority"])
        # The classes are still extremely uneven -- reported separately.
        self.assertEqual(result["classImbalance"]["label"], "Extreme imbalance")
        self.assertEqual(result["classImbalance"]["minorityClass"], "non_event")
        # Orientation-independent ratio is unchanged by the reversal.
        self.assertAlmostEqual(result["majorityToMinorityRatio"], 473.6777777, places=5)
        # Oriented ratio flips, as it must.
        self.assertAlmostEqual(result["nonEventsPerEvent"], 360 / 170_524, places=9)
        guidance = " ".join(result["implications"]).lower()
        self.assertIn("majority class", guidance)
        self.assertIn("non-event", guidance)

    def test_reversed_positive_value_configuration_is_symmetric_for_imbalance(self):
        forward = tis.assess_class_balance(100, 900)
        reversed_ = tis.assess_class_balance(900, 100)
        self.assertEqual(forward["classImbalance"]["label"], reversed_["classImbalance"]["label"])
        self.assertAlmostEqual(forward["majorityToMinorityRatio"], reversed_["majorityToMinorityRatio"])
        # Prevalence is NOT symmetric -- that is the point.
        self.assertNotEqual(forward["label"], reversed_["label"])

    # 21
    def test_balanced_target_semantics(self):
        result = tis.assess_class_balance(500, 500)
        self.assertEqual(result["classImbalance"]["label"], "Balanced")
        self.assertFalse(result["eventIsRare"])
        self.assertEqual(result["majorityToMinorityRatio"], 1.0)
        self.assertIn("Standard classification metrics are usable", " ".join(result["implications"]))

    # 22
    def test_zero_event_and_all_event_edge_cases_are_honest(self):
        zero = tis.assess_class_balance(0, 1_000)
        self.assertEqual(zero["label"], "No events observed")
        self.assertTrue(zero["singleClass"])
        self.assertEqual(zero["classImbalance"]["label"], "Single class present")
        self.assertIsNone(zero["nonEventsPerEvent"], "A zero denominator must not become an infinity.")
        self.assertIn("no classification model can be trained", " ".join(zero["implications"]).lower())

        every = tis.assess_class_balance(1_000, 0)
        self.assertEqual(every["label"], "No non-events observed")
        self.assertTrue(every["singleClass"])
        self.assertIsNone(every["eventsPerNonEvent"])
        # A single-class target must never be reported as a rare-event tier.
        for result in (zero, every):
            self.assertNotIn("Extreme rare event", result["label"])

    def test_event_value_absent_from_the_target_is_disclosed(self):
        folded = tis._fold_binary(
            [{"value": "0", "count": 900}, {"value": "1", "count": 100}], "fraud_confirmed", None
        )
        self.assertEqual(folded["eventValueResolution"], "requested_value_absent")
        self.assertEqual(folded["requestedEventValue"], "fraud_confirmed")
        # Falls back to the minority class rather than reporting zero events, and
        # says so, so a reviewer is never silently shown a different class.
        self.assertEqual(folded["eventValue"], "1")


# ---------------------------------------------------------------------------
# Scope contract unit behavior
# ---------------------------------------------------------------------------


class ScopeContractTests(unittest.TestCase):
    def test_workspace_scope_never_invents_governed_identity(self):
        scope = scope_module.workspace_scope(
            project_id="p", target="Class", population_rows=4_000,
            fingerprint="wsfp_abc", analysis_source="test",
        )
        self.assertEqual(scope["mode"], scope_module.WORKSPACE_DRAFT)
        self.assertIsNone(scope["datasetId"])
        self.assertIsNone(scope["datasetVersionId"])
        self.assertIsNone(scope["artifactChecksum"])
        self.assertFalse(scope["evidenceEligible"])
        self.assertFalse(scope["mddEligible"])
        self.assertFalse(scope["immutableVersion"])

    def test_governed_scope_records_immutable_identity(self):
        scope = scope_module.governed_scope(
            project_id="p", dataset_id="ds", dataset_name="CLASS_TRAIN", version_id="v1",
            artifact_checksum="abc123", target="Class", population_rows=170_884, exact=True,
            analysis_source="test",
        )
        self.assertEqual(scope["mode"], scope_module.GOVERNED_VERSION)
        self.assertTrue(scope["evidenceEligible"])
        self.assertTrue(scope["mddEligible"])
        self.assertTrue(scope["immutableVersion"])
        self.assertEqual(scope["artifactChecksum"], "abc123")

    def test_sampled_governed_scope_is_evidence_eligible_but_not_mdd_eligible(self):
        scope = scope_module.governed_scope(
            project_id="p", dataset_id="ds", dataset_name="D", version_id="v1", artifact_checksum="c",
            target="Class", population_rows=10, exact=False, analysis_source="test",
        )
        self.assertTrue(scope["evidenceEligible"])
        self.assertFalse(scope["mddEligible"])
        self.assertIn("not Model Development Document eligible", scope["disclosure"])

    def test_scope_identity_separates_modes(self):
        governed = scope_module.governed_scope(
            project_id="p", dataset_id="ds", dataset_name="D", version_id="v1", artifact_checksum="c",
            target="Class", population_rows=10, exact=True, analysis_source="t",
        )
        draft = scope_module.workspace_scope(
            project_id="p", target="Class", population_rows=10, fingerprint="f", analysis_source="t",
        )
        self.assertNotEqual(scope_module.scope_identity(governed), scope_module.scope_identity(draft))

    def test_require_evidence_eligible_rejects_a_draft_with_409(self):
        draft = scope_module.workspace_scope(
            project_id="p", target="Class", population_rows=10, fingerprint="f", analysis_source="t",
        )
        with self.assertRaises(HTTPException) as ctx:
            scope_module.require_evidence_eligible(draft)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Workspace Draft Analysis", ctx.exception.detail)

    def test_workspace_fingerprint_changes_with_content(self):
        first = _frame(seed=1)
        second = _frame(seed=2)
        self.assertNotEqual(
            scope_module.workspace_fingerprint(first, "Class", {"filename": "a.csv"}),
            scope_module.workspace_fingerprint(second, "Class", {"filename": "a.csv"}),
        )
        # Same content, same identity -- stable across calls.
        self.assertEqual(
            scope_module.workspace_fingerprint(first, "Class", {"filename": "a.csv"}),
            scope_module.workspace_fingerprint(first, "Class", {"filename": "a.csv"}),
        )


# ---------------------------------------------------------------------------
# 1-18, 23 -- endpoint governance
# ---------------------------------------------------------------------------


class GovernedScopeEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _cleanup()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)

    def setUp(self) -> None:
        self.client = _register("owner")
        self.project_id = _create_project(self.client, "Analysis Scope Project")
        self.frame = _frame()
        _load_workspace(self.client, self.project_id, self.frame)
        self.dataset_id, self.version_id = _register_dataset(
            self.client, self.project_id, self.frame, f"scope-asset-{uuid.uuid4().hex[:6]}"
        )

    def _governed_assessment(self):
        return self.client.post("/api/analytics/target-assessment", json={
            "projectId": self.project_id, "datasetId": self.dataset_id,
            "versionId": self.version_id, "target": "Class", "eventValue": 1, "nonEventValue": 0,
        })

    # 1 / 3 ------------------------------------------------------------------
    def test_governed_version_scope_with_real_identity(self):
        response = self._governed_assessment()
        self.assertEqual(response.status_code, 200, response.text)
        scope = response.json()["analysisScope"]
        self.assertEqual(scope["mode"], "governed_version")
        self.assertEqual(scope["datasetId"], self.dataset_id)
        self.assertEqual(scope["datasetVersionId"], self.version_id)
        self.assertTrue(scope["artifactChecksum"], "A governed scope must carry a durable artifact identity.")
        self.assertTrue(scope["immutableVersion"])
        self.assertTrue(scope["evidenceEligible"])
        self.assertTrue(scope["mddEligible"])
        self.assertEqual(scope["projectId"], self.project_id)

    # 2 / 4 ------------------------------------------------------------------
    def test_workspace_upload_returns_draft_scope_without_inventing_identity(self):
        response = self.client.post("/api/eda/workspace/target", json={
            "project_id": self.project_id, "target": "Class", "event_value": 1, "problem_type": "classification",
        })
        self.assertEqual(response.status_code, 200, response.text)
        scope = response.json()["analysis_scope"]
        self.assertEqual(scope["mode"], "workspace_draft")
        self.assertIsNone(scope["datasetId"])
        self.assertIsNone(scope["datasetVersionId"])
        self.assertIsNone(scope["artifactChecksum"])
        self.assertFalse(scope["evidenceEligible"])
        self.assertFalse(scope["mddEligible"])
        self.assertTrue(scope["datasetFingerprint"].startswith("wsfp_"))
        self.assertIn("not tied to an immutable dataset version", scope["disclosure"])

    def test_workspace_target_by_predictor_is_draft_scoped(self):
        response = self.client.post("/api/eda/target-by-predictor", json={
            "project_id": self.project_id, "target": "Class", "event_value": 1,
            "predictor": "V4", "analysis_type": "numeric_quantile", "bands": 5,
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["analysisScope"]["mode"], "workspace_draft")
        self.assertIsNone(body["datasetId"])
        self.assertIsNone(body["versionId"])
        self.assertEqual(
            {row["targetClass"] for row in body["boxPlotByTarget"]},
            {"event", "non_event"},
        )
        for row in body["boxPlotByTarget"]:
            self.assertLessEqual(row["q1"], row["median"])
            self.assertLessEqual(row["median"], row["q3"])
            self.assertNotIn("values", row)

    # 5 / 16 / 17 ------------------------------------------------------------
    def test_governed_evidence_save_succeeds_with_immutable_provenance(self):
        response = self.client.post("/api/analytics/target-evidence", json={
            "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
            "target": "Class", "eventValue": 1, "nonEventValue": 0, "predictor": "V4",
            "predictorAnalysisType": "numeric_quantile",
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["evidenceId"])
        self.assertEqual(body["analysisScope"]["mode"], "governed_version")

        stored = self.client.get(f"/api/evidence/{body['evidenceId']}")
        self.assertEqual(stored.status_code, 200, stored.text)
        item = stored.json()["evidence"]
        payload = item["payload"]
        # 16 -- immutable provenance.
        self.assertEqual(payload["datasetIdentity"]["datasetId"], self.dataset_id)
        self.assertEqual(payload["datasetIdentity"]["datasetVersionId"], self.version_id)
        self.assertTrue(payload["datasetIdentity"]["artifactChecksum"])
        self.assertTrue(payload["datasetIdentity"]["immutableVersion"])
        # Required governed metadata.
        for key in (
            "targetDefinition", "classCounts", "eventRate", "eventPrevalence", "classImbalance",
            "ratios", "confidenceInterval", "resolution", "analysisSpecification",
            "boundedResultDisclosure", "capturedBy", "capturedAt", "chartSpecification",
            "timeAndSegmentSelection", "selectedPredictorAnalysis",
        ):
            self.assertIn(key, payload, f"governed evidence must record {key}")
        self.assertEqual(payload["analysisSpecification"]["sourceOperation"], "POST /api/analytics/target-evidence")
        self.assertEqual(item["governance"]["resolvedBy"], "server")

        # 17 -- bounded.
        encoded = json.dumps(payload)
        self.assertLess(len(encoded.encode("utf-8")), 96 * 1024)
        # 18 -- no raw population.
        self.assertLessEqual(len(payload["selectedPredictorAnalysis"]["rows"]), 60)
        self.assertNotIn('"records"', encoded)

    def test_repeated_saves_create_distinct_immutable_artifacts(self):
        body = {
            "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
            "target": "Class", "eventValue": 1, "nonEventValue": 0,
        }
        first = self.client.post("/api/analytics/target-evidence", json=body).json()["evidenceId"]
        second = self.client.post("/api/analytics/target-evidence", json=body).json()["evidenceId"]
        self.assertNotEqual(first, second, "A repeat save must not silently overwrite the prior artifact.")
        self.assertEqual(self.client.get(f"/api/evidence/{first}").status_code, 200)

    # 6 ---------------------------------------------------------------------
    def test_draft_evidence_save_is_rejected_server_side(self):
        response = self.client.post("/api/analytics/target-evidence", json={
            "projectId": self.project_id, "datasetId": "", "versionId": "", "target": "Class",
        })
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("Workspace Draft Analysis", response.json()["detail"])

    # 7 ---------------------------------------------------------------------
    def test_crafted_governed_claims_are_rejected(self):
        # A client cannot assert governance: the fields do not exist on the model.
        crafted = self.client.post("/api/analytics/target-evidence", json={
            "projectId": self.project_id, "datasetId": "", "versionId": "", "target": "Class",
            "analysisScope": {"mode": "governed_version", "evidenceEligible": True},
            "evidenceEligible": True, "mddEligible": True,
            "artifactChecksum": "deadbeef",
        })
        self.assertIn(crafted.status_code, (409, 422), crafted.text)

        # A fabricated version id cannot be resolved.
        fake_version = self.client.post("/api/analytics/target-evidence", json={
            "projectId": self.project_id, "datasetId": self.dataset_id,
            "versionId": "v_fabricated_0000", "target": "Class",
        })
        self.assertIn(fake_version.status_code, (404, 409, 422), fake_version.text)

        # A fabricated dataset id cannot be resolved.
        fake_dataset = self.client.post("/api/analytics/target-evidence", json={
            "projectId": self.project_id, "datasetId": "ds_not_real", "versionId": self.version_id, "target": "Class",
        })
        self.assertIn(fake_dataset.status_code, (403, 404), fake_dataset.text)

    def test_a_target_absent_from_the_version_is_rejected(self):
        response = self.client.post("/api/analytics/target-evidence", json={
            "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
            "target": "NotAColumn",
        })
        self.assertEqual(response.status_code, 422, response.text)

    # 8 ---------------------------------------------------------------------
    def test_cross_project_version_substitution_is_rejected(self):
        other_project = _create_project(self.client, "Second Scope Project")
        response = self.client.post("/api/analytics/target-evidence", json={
            "projectId": other_project, "datasetId": self.dataset_id, "versionId": self.version_id, "target": "Class",
        })
        self.assertEqual(response.status_code, 403, response.text)
        self.assertIn("not linked to this project", response.json()["detail"])

    # 9 ---------------------------------------------------------------------
    def test_unauthorized_user_is_rejected(self):
        intruder = _register("intruder")
        for path, body in (
            ("/api/analytics/target-assessment", {"projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id, "target": "Class"}),
            ("/api/analytics/target-evidence", {"projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id, "target": "Class"}),
        ):
            with self.subTest(path=path):
                self.assertEqual(intruder.post(path, json=body).status_code, 403)
        self.assertEqual(
            intruder.get("/api/analytics/target-findings", params={"projectId": self.project_id}).status_code, 403
        )

    def test_unrelated_user_cannot_read_update_or_promote_a_finding(self):
        finding = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "workspaceFingerprint": "wsfp_x", "target": "Class", "title": "Draft",
        }).json()["finding"]
        intruder = _register("finding-intruder")
        finding_id = finding["targetFindingId"]
        self.assertEqual(intruder.put(f"/api/analytics/target-findings/{finding_id}", json={"projectId": self.project_id, "status": "resolved"}).status_code, 403)
        self.assertEqual(intruder.delete(f"/api/analytics/target-findings/{finding_id}", params={"projectId": self.project_id}).status_code, 403)
        self.assertEqual(
            intruder.post(f"/api/analytics/target-findings/{finding_id}/promote", json={
                "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
            }).status_code,
            403,
        )

    # 10 / 11 ----------------------------------------------------------------
    def test_draft_finding_is_scoped_to_the_workspace_fingerprint(self):
        workspace = self.client.post("/api/eda/workspace/target", json={
            "project_id": self.project_id, "target": "Class", "event_value": 1, "problem_type": "classification",
        }).json()
        fingerprint = workspace["analysis_scope"]["datasetFingerprint"]

        created = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "workspaceFingerprint": fingerprint,
            "target": "Class", "title": "Draft observation on upload A",
        })
        self.assertEqual(created.status_code, 200, created.text)
        self.assertEqual(created.json()["finding"]["scopeMode"], "workspace_draft")

        same = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "workspace_draft",
            "workspaceFingerprint": fingerprint, "target": "Class",
        })
        self.assertEqual(len(same.json()["findings"]), 1)

        # 11 -- a replacement upload produces a different fingerprint, and the
        # earlier draft finding must not follow it.
        _load_workspace(self.client, self.project_id, _frame(rows=700, event_every=25, seed=99))
        replaced = self.client.post("/api/eda/workspace/target", json={
            "project_id": self.project_id, "target": "Class", "event_value": 1, "problem_type": "classification",
        }).json()
        new_fingerprint = replaced["analysis_scope"]["datasetFingerprint"]
        self.assertNotEqual(new_fingerprint, fingerprint)

        after = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "workspace_draft",
            "workspaceFingerprint": new_fingerprint, "target": "Class",
        })
        self.assertEqual(after.json()["findings"], [], "A previous upload's draft findings must not appear.")

    # 12 ---------------------------------------------------------------------
    def test_governed_finding_is_scoped_to_exact_version_and_target(self):
        created = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
            "target": "Class", "title": "Governed observation",
        })
        self.assertEqual(created.status_code, 200, created.text)
        finding = created.json()["finding"]
        self.assertEqual(finding["scopeMode"], "governed_version")
        self.assertEqual(finding["scopeLabel"], "Governed Finding")
        self.assertEqual(finding["versionId"], self.version_id)
        self.assertTrue(finding["artifactChecksum"])

        other_target = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "governed_version",
            "datasetId": self.dataset_id, "versionId": self.version_id, "target": "Amount",
        })
        self.assertEqual(other_target.json()["findings"], [], "A finding must not cross targets.")

        other_version = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "governed_version",
            "datasetId": self.dataset_id, "versionId": "v_other", "target": "Class",
        })
        self.assertEqual(other_version.json()["findings"], [], "A finding must not cross versions.")

    def test_controlled_carry_forward_copies_and_preserves_the_draft(self):
        draft = self.client.post("/api/analytics/target-findings", json={
            "projectId": self.project_id, "workspaceFingerprint": "wsfp_carry",
            "target": "Class", "title": "Observed in draft", "severity": "warning", "status": "reviewed",
        }).json()["finding"]

        promoted = self.client.post(f"/api/analytics/target-findings/{draft['targetFindingId']}/promote", json={
            "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
        })
        self.assertEqual(promoted.status_code, 200, promoted.text)
        copy = promoted.json()["finding"]
        self.assertEqual(copy["scopeMode"], "governed_version")
        self.assertEqual(copy["promotedFromFindingId"], draft["targetFindingId"])
        self.assertTrue(copy["promotedAt"])
        # Never auto-approved: the copy starts open even though the draft was reviewed.
        self.assertEqual(copy["status"], "open")
        self.assertNotEqual(copy["targetFindingId"], draft["targetFindingId"])

        # The original draft is untouched.
        remaining = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "workspace_draft", "workspaceFingerprint": "wsfp_carry",
        }).json()["findings"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["status"], "reviewed")

    # 13 ---------------------------------------------------------------------
    def test_legacy_unversioned_finding_is_not_labeled_governed(self):
        from server.persistence.service import get_persistence_service

        service = get_persistence_service()
        service.ensure_project(self.project_id, None)
        service.target_findings.upsert({
            "target_finding_id": f"tfind_legacy_{uuid.uuid4().hex[:8]}",
            "project_id": self.project_id, "target": "Class", "title": "Written before scope existed",
            "scope_mode": "legacy_unscoped",
        })
        listing = self.client.get("/api/analytics/target-findings", params={
            "projectId": self.project_id, "scopeMode": "governed_version",
            "datasetId": self.dataset_id, "versionId": self.version_id,
        }).json()
        self.assertTrue(all(item["governed"] for item in listing["findings"]))
        legacy = listing["legacyFindings"]
        self.assertTrue(legacy, "Legacy rows must remain visible.")
        self.assertEqual(legacy[0]["scopeMode"], "legacy_unscoped")
        self.assertEqual(legacy[0]["scopeLabel"], "Legacy Finding (scope unknown)")
        self.assertFalse(legacy[0]["governed"])
        self.assertIsNone(legacy[0]["versionId"])

    # 14 / 15 ----------------------------------------------------------------
    def test_scope_transition_produces_a_different_result_identity(self):
        draft = self.client.post("/api/eda/workspace/target", json={
            "project_id": self.project_id, "target": "Class", "event_value": 1, "problem_type": "classification",
        }).json()
        governed = self._governed_assessment().json()
        self.assertNotEqual(
            draft["scope_identity"], governed["scopeIdentity"],
            "A draft result must never satisfy a governed request.",
        )
        self.assertEqual(draft["analysis_scope"]["mode"], "workspace_draft")
        self.assertEqual(governed["analysisScope"]["mode"], "governed_version")
        # 15 -- the governed figures come from the registered artifact, resolved
        # independently of the in-memory frame.
        self.assertEqual(governed["classBalance"]["totalModelingPopulation"], len(self.frame))

    def test_scope_participates_in_the_predictor_cache_identity(self):
        governed = self.client.post("/api/analytics/target-by-predictor", json={
            "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
            "target": "Class", "predictor": "V4", "analysisType": "numeric_quantile", "eventValue": 1, "bands": 5,
        }).json()
        draft = self.client.post("/api/eda/target-by-predictor", json={
            "project_id": self.project_id, "target": "Class", "event_value": 1,
            "predictor": "V4", "analysis_type": "numeric_quantile", "bands": 5,
        }).json()
        self.assertNotEqual(governed["scopeIdentity"], draft["scopeIdentity"])
        self.assertEqual(governed["analysisScope"]["mode"], "governed_version")
        self.assertEqual(draft["analysisScope"]["mode"], "workspace_draft")

    # 18 ---------------------------------------------------------------------
    def test_no_filesystem_path_or_population_rows_reach_the_browser(self):
        payloads = [
            self._governed_assessment().text,
            self.client.post("/api/eda/workspace/target", json={
                "project_id": self.project_id, "target": "Class", "event_value": 1, "problem_type": "classification",
            }).text,
            self.client.post("/api/analytics/target-by-predictor", json={
                "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
                "target": "Class", "predictor": "V4", "analysisType": "numeric_quantile", "eventValue": 1,
            }).text,
        ]
        for body in payloads:
            lowered = body.lower()
            self.assertNotIn("data_full.csv", lowered)
            self.assertNotIn("artifacts\\\\", lowered)
            self.assertNotIn(str(_LIBRARY_ROOT).lower().replace("\\", "\\\\"), lowered)
            self.assertNotIn('"records"', lowered)
            self.assertLess(len(body), 60_000, "No response may approach population size.")

    # 23 ---------------------------------------------------------------------
    def test_regression_target_receives_scope_without_classification_sections(self):
        regression_frame = pd.DataFrame({
            "x1": np.arange(400, dtype=float),
            "x2": np.linspace(0, 5, 400),
            "y": np.linspace(10.0, 900.0, 400),
        })
        _load_workspace_regression = self.client.post("/api/data/set_sample", json={
            "project_id": self.project_id, "headers": ["x1", "x2", "y"],
            "rows": regression_frame.to_dict(orient="records"),
            "target": "y", "selected_columns": ["x1", "x2"],
        })
        self.assertEqual(_load_workspace_regression.status_code, 200)

        response = self.client.post("/api/eda/workspace/target", json={
            "project_id": self.project_id, "target": "y", "problem_type": "regression",
        })
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        # Scope contract applies.
        self.assertEqual(body["analysis_scope"]["mode"], "workspace_draft")
        self.assertFalse(body["analysis_scope"]["evidenceEligible"])
        # Classification-only content is absent.
        self.assertIsNone(body["full_population_assessment"])
        self.assertEqual(body["problem_type"], "regression")
        self.assertNotIn("event_count", body["profile"])

    def test_draft_summary_export_is_marked_and_governed_export_is_not(self):
        draft = self.client.post("/api/analytics/target-summary-export", json={
            "projectId": self.project_id, "target": "Class",
        })
        self.assertEqual(draft.status_code, 200, draft.text)
        body = draft.json()
        self.assertEqual(body["scopeMode"], "workspace_draft")
        self.assertFalse(body["governed"])
        for marker in ("Workspace Draft", "Not Governed Evidence", "Not Version-Pinned", "Not MDD Eligible"):
            self.assertIn(marker, body["markers"])
        self.assertIsNone(body["datasetVersionId"])

        governed = self.client.post("/api/analytics/target-summary-export", json={
            "projectId": self.project_id, "datasetId": self.dataset_id, "versionId": self.version_id,
            "target": "Class", "eventValue": 1,
        })
        self.assertEqual(governed.status_code, 200, governed.text)
        governed_body = governed.json()
        self.assertEqual(governed_body["scopeMode"], "governed_version")
        self.assertTrue(governed_body["governed"])
        self.assertEqual(governed_body["markers"], [])
        self.assertEqual(governed_body["datasetVersionId"], self.version_id)

    def test_scope_resolution_adds_negligible_warm_overhead(self):
        self._governed_assessment()
        started = time.perf_counter()
        warm = self._governed_assessment()
        warm_ms = (time.perf_counter() - started) * 1000
        self.assertEqual(warm.status_code, 200)
        self.assertTrue(warm.json()["analysisScope"]["mode"] == "governed_version")
        print(f"\n  [perf] governed assessment warm (incl. scope resolution) = {warm_ms:.0f} ms")
        self.assertLess(warm_ms, 500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
