"""Phase 2A evidence persistence must bind to one authorized dataset version."""
from __future__ import annotations

import atexit
import io
import os
import shutil
import sys
import time
import unittest
import uuid
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
TEST_ROOT = REPO_ROOT / ".tmp" / f"evidence_identity_{uuid.uuid4().hex}"
TEST_ROOT.mkdir(parents=True, exist_ok=False)

ENVIRONMENT = {
    "ATLAS_SECURITY_DB_PATH": str(TEST_ROOT / "security.db"),
    "ATLAS_SQLITE_PATH": str(TEST_ROOT / "persistence.db"),
    "ATLAS_CHECKPOINT_PATH": str(TEST_ROOT / "checkpoint.json"),
    "ATLAS_DATASET_LIBRARY_ROOT": str(TEST_ROOT / "dataset-library"),
    "ATLAS_EVIDENCE_ROOT": str(TEST_ROOT / "evidence"),
    "ATLAS_AUTH_ENABLED": "true",
    "ATLAS_ALLOW_PUBLIC_REGISTRATION": "true",
}
ORIGINAL_ENVIRONMENT = {key: os.environ.get(key) for key in ENVIRONMENT}
os.environ.update(ENVIRONMENT)

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402


CLIENTS: list[TestClient] = []


def cleanup() -> None:
    for client in list(CLIENTS):
        client.close()
    CLIENTS.clear()
    for base_name in ("security.db", "persistence.db"):
        base = TEST_ROOT / base_name
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(20):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 19:
                        time.sleep(0.1)
    shutil.rmtree(TEST_ROOT, ignore_errors=True)
    for key, value in ORIGINAL_ENVIRONMENT.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


atexit.register(cleanup)


def register_client(label: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    CLIENTS.append(client)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-evidence-test.local",
            "displayName": f"Evidence Identity {label} {suffix}",
            "password": "EvidenceIdentityTestPass!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()["user"]["userId"]


class EvidenceCanonicalIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_security_store()
        initialize_persistence()
        cls.owner, cls.owner_id = register_client("owner")
        cls.other_user, cls.other_user_id = register_client("other-user")
        cls.viewer, cls.viewer_id = register_client("viewer")
        project = cls.owner.post(
            "/api/projects",
            json={
                "projectName": "Canonical Evidence Project",
                "projectType": "predictive-modeling",
            },
        )
        assert project.status_code == 200, project.text
        cls.project_id = project.json()["project"]["projectId"]
        # Registration creates the security principal; one authenticated
        # request synchronizes its persistence user row before sharing.
        assert cls.viewer.get("/api/auth/me").status_code == 200
        share = cls.owner.post(
            f"/api/sharing/resources/project/{cls.project_id}/share",
            json={
                "principalType": "user",
                "principalId": cls.viewer_id,
                "permissionLevel": "view",
            },
        )
        assert share.status_code == 200, share.text

        frame = pd.DataFrame(
            {
                "predictor_a": [float(value % 8) for value in range(40)],
                "predictor_b": [float((value * 3) % 7) for value in range(40)],
                "bad_flag": [(value // 10) % 2 for value in range(40)],
            }
        )
        upload = cls.owner.post(
            "/api/datasets/upload",
            files={
                "file": (
                    "evidence-identity.csv",
                    io.BytesIO(frame.to_csv(index=False).encode("utf-8")),
                    "text/csv",
                )
            },
            data={"name": "Evidence Identity Asset"},
        )
        assert upload.status_code == 200, upload.text
        dataset = upload.json()["dataset"]
        cls.dataset_id = dataset["datasetId"]
        cls.version_id = dataset["created_dataset_version_id"]
        link = cls.owner.post(
            f"/api/projects/{cls.project_id}/datasets/link",
            json={
                "datasetId": cls.dataset_id,
                "versionId": cls.version_id,
                "datasetRole": "modeling",
            },
        )
        assert link.status_code == 200, link.text
        activation = cls.owner.post(
            f"/api/datasets/{cls.dataset_id}/versions/{cls.version_id}/activate",
            params={"project_id": cls.project_id},
        )
        assert activation.status_code == 200, activation.text
        target = cls.owner.post(
            "/api/data/set_target",
            json={
                "project_id": cls.project_id,
                "target": "bad_flag",
                "selected_columns": ["predictor_a", "predictor_b"],
                "expected_dataset_id": cls.dataset_id,
                "expected_dataset_version_id": cls.version_id,
            },
        )
        assert target.status_code == 200, target.text

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup()

    def canonical_payload(self, evidence_id: str, **overrides: object) -> dict:
        payload = {
            "evidenceId": evidence_id,
            "lineage_contract": "canonical_dataset_version",
            "project_id": self.project_id,
            "dataset_id": self.dataset_id,
            "dataset_version_id": self.version_id,
            "evidenceType": "outliers",
            "title": "Canonical preparation evidence",
            "summary": "Exact immutable dataset lineage.",
            "sourcePage": "Outlier Analysis",
            "sourceRoute": "/step03",
            "tags": ["predictive_modeling", "outliers"],
            "lineage": {
                "project_id": self.project_id,
                "dataset_id": self.dataset_id,
                "dataset_version_id": self.version_id,
                "lineage_contract": "canonical_dataset_version",
            },
            "payload": {"treatment": "IQR_1_5"},
        }
        payload.update(overrides)
        return payload

    def test_exact_create_persists_canonical_fields_and_derived_aliases(self) -> None:
        evidence_id = f"evidence-exact-{uuid.uuid4().hex}"
        response = self.owner.post(
            "/api/evidence",
            json=self.canonical_payload(evidence_id),
        )
        self.assertEqual(response.status_code, 200, response.text)
        evidence = response.json()["evidence"]
        self.assertEqual(evidence["project_id"], self.project_id)
        self.assertEqual(evidence["dataset_id"], self.dataset_id)
        self.assertEqual(evidence["dataset_version_id"], self.version_id)
        self.assertEqual(evidence["projectId"], self.project_id)
        self.assertEqual(evidence["datasetIds"], [self.dataset_id])
        self.assertEqual(evidence["lineage"]["datasetVersion"], self.version_id)

    def test_preparation_evidence_cannot_use_legacy_only_lineage(self) -> None:
        evidence_id = f"evidence-legacy-{uuid.uuid4().hex}"
        response = self.owner.post(
            "/api/evidence",
            json={
                "evidenceId": evidence_id,
                "projectId": self.project_id,
                "datasetIds": [self.dataset_id],
                "evidenceType": "outliers",
                "lineage": {
                    "datasetId": self.dataset_id,
                    "datasetVersion": self.version_id,
                },
            },
        )
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            self.owner.get(f"/api/evidence/{evidence_id}").status_code,
            404,
        )

    def test_eda_and_bureau_evidence_cannot_bypass_canonical_validation(self) -> None:
        legacy_cases = (
            {
                "evidenceType": "eda",
                "sourceRoute": "/step02",
                "tags": ["predictive_modeling", "eda"],
            },
            {
                "evidenceType": "dataset",
                "sourceRoute": "/step01?section=credit-bureau-review",
                "tags": ["predictive_modeling", "bureau_review"],
            },
            {
                "evidenceType": "dataset",
                "sourceRoute": "/step01",
                "tags": [],
            },
            {
                "evidenceType": "dataset",
                "sourcePage": "Data Acquisition",
                "tags": ["predictive_modeling"],
            },
        )
        for index, evidence_fields in enumerate(legacy_cases):
            evidence_id = f"legacy-phase2a-{index}-{uuid.uuid4().hex}"
            with self.subTest(evidence_fields=evidence_fields):
                response = self.owner.post(
                    "/api/evidence",
                    json={
                        "evidenceId": evidence_id,
                        "projectId": self.project_id,
                        "datasetIds": [self.dataset_id],
                        "lineage": {
                            "datasetId": self.dataset_id,
                            "datasetVersion": self.version_id,
                        },
                        **evidence_fields,
                    },
                )
                self.assertEqual(response.status_code, 409, response.text)
                self.assertEqual(
                    self.owner.get(f"/api/evidence/{evidence_id}").status_code,
                    404,
                )

        exact_cases = (
            {
                "evidenceType": "eda",
                "sourceRoute": "/step02",
                "tags": ["predictive_modeling", "eda"],
            },
            {
                "evidenceType": "dataset",
                "sourceRoute": "/step01?section=credit-bureau-review",
                "tags": ["predictive_modeling", "bureau_review"],
            },
        )
        for index, evidence_fields in enumerate(exact_cases):
            evidence_id = f"exact-phase2a-{index}-{uuid.uuid4().hex}"
            with self.subTest(evidence_fields=evidence_fields):
                response = self.owner.post(
                    "/api/evidence",
                    json=self.canonical_payload(
                        evidence_id,
                        **evidence_fields,
                    ),
                )
                self.assertEqual(response.status_code, 200, response.text)
                evidence = response.json()["evidence"]
                self.assertEqual(evidence["project_id"], self.project_id)
                self.assertEqual(evidence["dataset_id"], self.dataset_id)
                self.assertEqual(
                    evidence["dataset_version_id"],
                    self.version_id,
                )

    def test_mismatch_unknown_and_contradictory_aliases_fail_before_write(self) -> None:
        cases = (
            {"dataset_version_id": "version-does-not-exist"},
            {"dataset_id": "dataset-does-not-exist"},
            {"projectId": "contradictory-project-alias"},
            {"datasetIds": ["contradictory-dataset-alias"]},
            {"dataset_version": "browser-profile-snapshot"},
        )
        for index, override in enumerate(cases):
            evidence_id = f"evidence-rejected-{index}-{uuid.uuid4().hex}"
            with self.subTest(override=override):
                response = self.owner.post(
                    "/api/evidence",
                    json=self.canonical_payload(evidence_id, **override),
                )
                self.assertIn(response.status_code, {404, 409}, response.text)
                self.assertEqual(
                    self.owner.get(f"/api/evidence/{evidence_id}").status_code,
                    404,
                )

    def test_user_without_project_edit_access_cannot_capture_evidence(self) -> None:
        evidence_id = f"evidence-unauthorized-{uuid.uuid4().hex}"
        response = self.other_user.post(
            "/api/evidence",
            json=self.canonical_payload(evidence_id),
        )
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(
            self.owner.get(f"/api/evidence/{evidence_id}").status_code,
            404,
        )

    def test_evidence_reads_and_mutations_enforce_owning_project_acl(self) -> None:
        evidence_id = f"evidence-private-{uuid.uuid4().hex}"
        created = self.owner.post(
            "/api/evidence",
            json=self.canonical_payload(evidence_id),
        )
        self.assertEqual(created.status_code, 200, created.text)

        # A project viewer may use every read surface.
        self.assertEqual(
            self.viewer.get(f"/api/evidence/{evidence_id}").status_code,
            200,
        )
        self.assertIn(
            evidence_id,
            {
                row["evidenceId"]
                for row in self.viewer.get(
                    "/api/evidence",
                    params={"projectId": self.project_id},
                ).json()["items"]
            },
        )
        self.assertIn(
            evidence_id,
            {
                node.get("evidenceId")
                for node in self.viewer.get(
                    "/api/evidence/graph",
                    params={"projectId": self.project_id},
                ).json()["graph"]["nodes"]
            },
        )
        self.assertEqual(
            self.viewer.get(
                f"/api/evidence/coverage/{self.project_id}",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.viewer.get(
                f"/api/evidence/project/{self.project_id}",
            ).status_code,
            200,
        )
        self.assertIn(
            evidence_id,
            {
                row["evidenceId"]
                for row in self.viewer.get(
                    f"/api/evidence/dataset/{self.dataset_id}",
                ).json()["items"]
            },
        )
        self.assertEqual(
            self.viewer.post(
                "/api/evidence/export/excel",
                json={"projectId": self.project_id},
            ).status_code,
            200,
        )

        # Mutations require edit, and item endpoints conceal existence.
        self.assertEqual(
            self.viewer.put(
                f"/api/evidence/{evidence_id}",
                json={"summary": "Viewer overwrite"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.viewer.delete(f"/api/evidence/{evidence_id}").status_code,
            404,
        )
        self.assertEqual(
            self.viewer.post(
                "/api/evidence/auto-capture",
                json={"projectId": self.project_id},
            ).status_code,
            403,
        )

        # An unrelated signed-in user cannot enumerate, read, export, or
        # mutate evidence from the owner's project.
        unscoped = self.other_user.get("/api/evidence")
        self.assertEqual(unscoped.status_code, 200, unscoped.text)
        self.assertNotIn(
            evidence_id,
            {row["evidenceId"] for row in unscoped.json()["items"]},
        )
        self.assertEqual(
            self.other_user.get(
                "/api/evidence",
                params={"projectId": self.project_id},
            ).status_code,
            403,
        )
        self.assertNotIn(
            evidence_id,
            {
                row["evidenceId"]
                for row in self.other_user.get(
                    f"/api/evidence/dataset/{self.dataset_id}",
                ).json()["items"]
            },
        )
        unscoped_graph = self.other_user.get("/api/evidence/graph")
        self.assertEqual(unscoped_graph.status_code, 200, unscoped_graph.text)
        self.assertNotIn(
            evidence_id,
            {
                node.get("evidenceId")
                for node in unscoped_graph.json()["graph"]["nodes"]
            },
        )
        self.assertEqual(
            self.other_user.get(
                "/api/evidence/graph",
                params={"projectId": self.project_id},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.other_user.get(
                f"/api/evidence/coverage/{self.project_id}",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.other_user.get(
                f"/api/evidence/project/{self.project_id}",
            ).status_code,
            403,
        )
        self.assertEqual(
            self.other_user.post(
                "/api/evidence/export/excel",
                json={"projectId": self.project_id},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.other_user.get(f"/api/evidence/{evidence_id}").status_code,
            404,
        )
        self.assertEqual(
            self.other_user.put(
                f"/api/evidence/{evidence_id}",
                json={"summary": "Unauthorized overwrite"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.other_user.delete(f"/api/evidence/{evidence_id}").status_code,
            404,
        )
        self.assertEqual(
            self.other_user.post(
                "/api/evidence/auto-capture",
                json={"projectId": self.project_id},
            ).status_code,
            403,
        )

        unchanged = self.owner.get(f"/api/evidence/{evidence_id}")
        self.assertEqual(unchanged.status_code, 200, unchanged.text)
        self.assertEqual(
            unchanged.json()["evidence"]["summary"],
            "Exact immutable dataset lineage.",
        )

    def test_legacy_ownerless_evidence_is_quarantined(self) -> None:
        from server.evidence.evidence_store import (
            delete_evidence,
            get_evidence,
            upsert_evidence,
        )

        evidence_id = f"legacy-ownerless-{uuid.uuid4().hex}"
        upsert_evidence(
            {
                "evidenceId": evidence_id,
                "evidenceType": "notebook",
                "title": "Ownerless legacy evidence",
                "datasetIds": [self.dataset_id],
            }
        )
        try:
            self.assertEqual(
                self.owner.get(f"/api/evidence/{evidence_id}").status_code,
                404,
            )
            self.assertNotIn(
                evidence_id,
                {
                    row["evidenceId"]
                    for row in self.owner.get("/api/evidence").json()["items"]
                },
            )
            self.assertNotIn(
                evidence_id,
                {
                    row["evidenceId"]
                    for row in self.owner.get(
                        f"/api/evidence/dataset/{self.dataset_id}",
                    ).json()["items"]
                },
            )
            self.assertEqual(
                self.owner.delete(f"/api/evidence/{evidence_id}").status_code,
                404,
            )
            self.assertIsNotNone(get_evidence(evidence_id))
        finally:
            delete_evidence(evidence_id)

    def test_auto_capture_requires_an_exact_project_dataset_link(self) -> None:
        frame = pd.DataFrame(
            {
                "unlinked_predictor": [1.0, 2.0, 3.0],
                "unlinked_target": [0, 1, 0],
            }
        )
        upload = self.owner.post(
            "/api/datasets/upload",
            files={
                "file": (
                    "unlinked-evidence.csv",
                    io.BytesIO(frame.to_csv(index=False).encode("utf-8")),
                    "text/csv",
                )
            },
            data={"name": "Unlinked Evidence Asset"},
        )
        self.assertEqual(upload.status_code, 200, upload.text)
        unlinked_dataset_id = upload.json()["dataset"]["datasetId"]

        captured = self.owner.post(
            "/api/evidence/auto-capture",
            json={
                "projectId": self.project_id,
                "projectName": "Canonical Evidence Project",
            },
        )
        self.assertEqual(captured.status_code, 200, captured.text)
        captured_dataset_ids = {
            dataset_id
            for row in captured.json()["items"]
            for dataset_id in row.get("datasetIds", [])
        }
        self.assertIn(self.dataset_id, captured_dataset_ids)
        self.assertNotIn(unlinked_dataset_id, captured_dataset_ids)
        catalog_item = next(
            row
            for row in captured.json()["items"]
            if row.get("dataset_id") == self.dataset_id
        )
        self.assertEqual(
            catalog_item["lineage_contract"],
            "canonical_dataset_version",
        )
        self.assertEqual(catalog_item["project_id"], self.project_id)
        self.assertEqual(catalog_item["dataset_version_id"], self.version_id)
        self.assertEqual(
            catalog_item["lineage"]["dataset_version_id"],
            self.version_id,
        )
        self.assertTrue(
            catalog_item["sourceRoute"].endswith(
                f"/versions/{self.version_id}"
            )
        )

    def test_legacy_dataset_catalog_evidence_without_version_is_quarantined(
        self,
    ) -> None:
        from server.evidence.evidence_store import (
            delete_evidence,
            get_evidence,
            upsert_evidence,
        )

        legacy_id = f"legacy-dataset-catalog-{uuid.uuid4().hex}"
        upsert_evidence(
            {
                "evidenceId": legacy_id,
                "projectId": self.project_id,
                "projectName": "Canonical Evidence Project",
                "evidenceType": "dataset",
                "title": "Legacy Dataset Library capture",
                "sourcePage": "Dataset Library",
                "sourceRoute": f"/datasets/{self.dataset_id}",
                "artifactType": "dataset",
                "artifactId": self.dataset_id,
                "datasetIds": [self.dataset_id],
                "lineage": {"registry": "datasets/registry.json"},
            }
        )
        try:
            self.assertEqual(
                self.owner.get(f"/api/evidence/{legacy_id}").status_code,
                404,
            )
            listed = self.owner.get(
                "/api/evidence",
                params={
                    "projectId": self.project_id,
                    "datasetId": self.dataset_id,
                },
            )
            self.assertEqual(listed.status_code, 200, listed.text)
            self.assertNotIn(
                legacy_id,
                {row["evidenceId"] for row in listed.json()["items"]},
            )

            captured = self.owner.post(
                "/api/evidence/auto-capture",
                json={
                    "projectId": self.project_id,
                    "projectName": "Canonical Evidence Project",
                },
            )
            self.assertEqual(captured.status_code, 200, captured.text)
            current = next(
                row
                for row in captured.json()["items"]
                if row.get("dataset_id") == self.dataset_id
            )
            self.assertNotEqual(current["evidenceId"], legacy_id)
            legacy = get_evidence(legacy_id)
            self.assertIsNotNone(legacy)
            self.assertNotIn("dataset_version_id", legacy or {})
        finally:
            delete_evidence(legacy_id)

    def test_version_aware_generated_ids_and_filters_prevent_cross_version_overwrite(
        self,
    ) -> None:
        first_capture = self.owner.post(
            "/api/evidence/auto-capture",
            json={
                "projectId": self.project_id,
                "projectName": "Canonical Evidence Project",
            },
        )
        self.assertEqual(first_capture.status_code, 200, first_capture.text)
        first = next(
            row
            for row in first_capture.json()["items"]
            if row.get("dataset_id") == self.dataset_id
        )
        self.assertEqual(first["dataset_version_id"], self.version_id)

        replacement = pd.DataFrame(
            {
                "predictor_a": [10.0, 11.0, 12.0, 13.0],
                "predictor_b": [3.0, 2.0, 1.0, 0.0],
                "bad_flag": [0, 1, 0, 1],
            }
        )
        created = self.owner.post(
            f"/api/datasets/{self.dataset_id}/versions",
            files={
                "file": (
                    "evidence-identity-v2.csv",
                    io.BytesIO(
                        replacement.to_csv(index=False).encode("utf-8")
                    ),
                    "text/csv",
                )
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        second_version_id = created.json()["version"]["versionId"]
        self.assertNotEqual(second_version_id, self.version_id)

        try:
            linked = self.owner.post(
                f"/api/projects/{self.project_id}/datasets/link",
                json={
                    "datasetId": self.dataset_id,
                    "versionId": second_version_id,
                    "datasetRole": "modeling",
                },
            )
            self.assertEqual(linked.status_code, 200, linked.text)
            activated = self.owner.post(
                (
                    f"/api/datasets/{self.dataset_id}/versions/"
                    f"{second_version_id}/activate"
                ),
                params={"project_id": self.project_id},
            )
            self.assertEqual(activated.status_code, 200, activated.text)

            second_capture = self.owner.post(
                "/api/evidence/auto-capture",
                json={
                    "projectId": self.project_id,
                    "projectName": "Canonical Evidence Project",
                },
            )
            self.assertEqual(
                second_capture.status_code,
                200,
                second_capture.text,
            )
            second = next(
                row
                for row in second_capture.json()["items"]
                if row.get("dataset_id") == self.dataset_id
            )
            self.assertEqual(
                second["dataset_version_id"],
                second_version_id,
            )
            self.assertNotEqual(second["evidenceId"], first["evidenceId"])

            first_version_rows = self.owner.get(
                "/api/evidence",
                params={
                    "projectId": self.project_id,
                    "datasetId": self.dataset_id,
                    "dataset_version_id": self.version_id,
                },
            )
            self.assertEqual(
                first_version_rows.status_code,
                200,
                first_version_rows.text,
            )
            first_ids = {
                row["evidenceId"]
                for row in first_version_rows.json()["items"]
            }
            self.assertIn(first["evidenceId"], first_ids)
            self.assertNotIn(second["evidenceId"], first_ids)

            second_version_rows = self.owner.get(
                f"/api/evidence/dataset/{self.dataset_id}",
                params={"datasetVersionId": second_version_id},
            )
            self.assertEqual(
                second_version_rows.status_code,
                200,
                second_version_rows.text,
            )
            second_ids = {
                row["evidenceId"]
                for row in second_version_rows.json()["items"]
            }
            self.assertIn(second["evidenceId"], second_ids)
            self.assertNotIn(first["evidenceId"], second_ids)
            contradictory_filter = self.owner.get(
                "/api/evidence",
                params={
                    "projectId": self.project_id,
                    "dataset_version_id": self.version_id,
                    "datasetVersionId": second_version_id,
                },
            )
            self.assertEqual(
                contradictory_filter.status_code,
                409,
                contradictory_filter.text,
            )
        finally:
            restored_link = self.owner.post(
                f"/api/projects/{self.project_id}/datasets/link",
                json={
                    "datasetId": self.dataset_id,
                    "versionId": self.version_id,
                    "datasetRole": "modeling",
                },
            )
            self.assertEqual(
                restored_link.status_code,
                200,
                restored_link.text,
            )
            restored_activation = self.owner.post(
                (
                    f"/api/datasets/{self.dataset_id}/versions/"
                    f"{self.version_id}/activate"
                ),
                params={"project_id": self.project_id},
            )
            self.assertEqual(
                restored_activation.status_code,
                200,
                restored_activation.text,
            )

    def test_project_persistence_endpoint_revalidates_exact_identity(self) -> None:
        exact_id = f"sqlite-evidence-exact-{uuid.uuid4().hex}"
        exact = self.owner.post(
            f"/api/projects/{self.project_id}/evidence",
            json=self.canonical_payload(exact_id),
        )
        self.assertEqual(exact.status_code, 200, exact.text)
        stored = self.owner.get(f"/api/projects/{self.project_id}/evidence")
        self.assertEqual(stored.status_code, 200, stored.text)
        record = next(
            row
            for row in stored.json()["evidence"]
            if row["evidenceId"] == exact_id
        )
        self.assertEqual(record["payload"]["project_id"], self.project_id)
        self.assertEqual(record["payload"]["dataset_id"], self.dataset_id)
        self.assertEqual(
            record["payload"]["dataset_version_id"],
            self.version_id,
        )

        stale_id = f"sqlite-evidence-stale-{uuid.uuid4().hex}"
        stale = self.owner.post(
            f"/api/projects/{self.project_id}/evidence",
            json=self.canonical_payload(
                stale_id,
                dataset_version_id="stale-version",
            ),
        )
        self.assertEqual(stale.status_code, 409, stale.text)

    def test_existing_evidence_id_cannot_migrate_between_versions(self) -> None:
        file_id = f"immutable-file-evidence-{uuid.uuid4().hex}"
        relational_id = f"immutable-sqlite-evidence-{uuid.uuid4().hex}"
        file_created = self.owner.post(
            "/api/evidence",
            json=self.canonical_payload(file_id),
        )
        relational_created = self.owner.post(
            f"/api/projects/{self.project_id}/evidence",
            json=self.canonical_payload(relational_id),
        )
        self.assertEqual(file_created.status_code, 200, file_created.text)
        self.assertEqual(
            relational_created.status_code,
            200,
            relational_created.text,
        )

        # Metadata edits retain the original canonical identity.
        file_metadata = self.owner.put(
            f"/api/evidence/{file_id}",
            json={"summary": "Updated without changing lineage."},
        )
        relational_metadata = self.owner.put(
            (
                f"/api/projects/{self.project_id}/evidence/"
                f"{relational_id}"
            ),
            json={"summary": "Updated without changing lineage."},
        )
        self.assertEqual(file_metadata.status_code, 200, file_metadata.text)
        self.assertEqual(
            relational_metadata.status_code,
            200,
            relational_metadata.text,
        )

        replacement = pd.DataFrame(
            {
                "predictor_a": [20.0, 21.0, 22.0, 23.0],
                "predictor_b": [4.0, 3.0, 2.0, 1.0],
                "bad_flag": [0, 1, 0, 1],
            }
        )
        created = self.owner.post(
            f"/api/datasets/{self.dataset_id}/versions",
            files={
                "file": (
                    "evidence-identity-immutable-v2.csv",
                    io.BytesIO(
                        replacement.to_csv(index=False).encode("utf-8")
                    ),
                    "text/csv",
                )
            },
        )
        self.assertEqual(created.status_code, 200, created.text)
        second_version_id = created.json()["version"]["versionId"]

        try:
            linked = self.owner.post(
                f"/api/projects/{self.project_id}/datasets/link",
                json={
                    "datasetId": self.dataset_id,
                    "versionId": second_version_id,
                    "datasetRole": "modeling",
                },
            )
            self.assertEqual(linked.status_code, 200, linked.text)
            activated = self.owner.post(
                (
                    f"/api/datasets/{self.dataset_id}/versions/"
                    f"{second_version_id}/activate"
                ),
                params={"project_id": self.project_id},
            )
            self.assertEqual(activated.status_code, 200, activated.text)

            def migrated_payload(evidence_id: str) -> dict:
                return self.canonical_payload(
                    evidence_id,
                    dataset_version_id=second_version_id,
                    lineage={
                        "project_id": self.project_id,
                        "dataset_id": self.dataset_id,
                        "dataset_version_id": second_version_id,
                        "lineage_contract": "canonical_dataset_version",
                    },
                )

            migration_requests = (
                self.owner.put(
                    f"/api/evidence/{file_id}",
                    json=migrated_payload(file_id),
                ),
                self.owner.post(
                    "/api/evidence",
                    json=migrated_payload(file_id),
                ),
                self.owner.put(
                    (
                        f"/api/projects/{self.project_id}/evidence/"
                        f"{relational_id}"
                    ),
                    json=migrated_payload(relational_id),
                ),
                self.owner.post(
                    f"/api/projects/{self.project_id}/evidence",
                    json=migrated_payload(relational_id),
                ),
            )
            for response in migration_requests:
                with self.subTest(url=str(response.request.url)):
                    self.assertEqual(response.status_code, 409, response.text)

            file_stored = self.owner.get(f"/api/evidence/{file_id}")
            self.assertEqual(file_stored.status_code, 200, file_stored.text)
            self.assertEqual(
                file_stored.json()["evidence"]["dataset_version_id"],
                self.version_id,
            )
            relational_stored = self.owner.get(
                f"/api/projects/{self.project_id}/evidence"
            )
            self.assertEqual(
                relational_stored.status_code,
                200,
                relational_stored.text,
            )
            relational_record = next(
                row
                for row in relational_stored.json()["evidence"]
                if row["evidenceId"] == relational_id
            )
            self.assertEqual(
                relational_record["payload"]["dataset_version_id"],
                self.version_id,
            )
        finally:
            restored_link = self.owner.post(
                f"/api/projects/{self.project_id}/datasets/link",
                json={
                    "datasetId": self.dataset_id,
                    "versionId": self.version_id,
                    "datasetRole": "modeling",
                },
            )
            self.assertEqual(
                restored_link.status_code,
                200,
                restored_link.text,
            )
            restored_activation = self.owner.post(
                (
                    f"/api/datasets/{self.dataset_id}/versions/"
                    f"{self.version_id}/activate"
                ),
                params={"project_id": self.project_id},
            )
            self.assertEqual(
                restored_activation.status_code,
                200,
                restored_activation.text,
            )

    def test_legacy_evidence_id_cannot_gain_canonical_lineage(self) -> None:
        file_id = f"legacy-file-evidence-{uuid.uuid4().hex}"
        relational_id = f"legacy-sqlite-evidence-{uuid.uuid4().hex}"
        file_created = self.owner.post(
            "/api/evidence",
            json={
                "evidenceId": file_id,
                "projectId": self.project_id,
                "evidenceType": "notebook",
                "title": "Legacy notebook evidence",
            },
        )
        relational_created = self.owner.post(
            f"/api/projects/{self.project_id}/evidence",
            json={
                "evidenceId": relational_id,
                "projectId": self.project_id,
                "evidenceType": "notebook",
                "title": "Legacy relational notebook evidence",
            },
        )
        self.assertEqual(file_created.status_code, 200, file_created.text)
        self.assertEqual(
            relational_created.status_code,
            200,
            relational_created.text,
        )

        file_upgrade = self.owner.put(
            f"/api/evidence/{file_id}",
            json=self.canonical_payload(file_id),
        )
        relational_upgrade = self.owner.put(
            (
                f"/api/projects/{self.project_id}/evidence/"
                f"{relational_id}"
            ),
            json=self.canonical_payload(relational_id),
        )
        self.assertEqual(file_upgrade.status_code, 409, file_upgrade.text)
        self.assertEqual(
            relational_upgrade.status_code,
            409,
            relational_upgrade.text,
        )

    def test_authorized_non_modeling_evidence_remains_compatible(self) -> None:
        evidence_id = f"non-modeling-evidence-{uuid.uuid4().hex}"
        response = self.owner.post(
            "/api/evidence",
            json={
                "evidenceId": evidence_id,
                "projectId": self.project_id,
                "evidenceType": "notebook",
                "title": "Notebook evidence",
                "summary": "Non-modeling evidence remains supported.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.json()["evidence"]["projectId"],
            self.project_id,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
