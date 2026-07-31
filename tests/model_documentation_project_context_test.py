"""Fail-closed project identity tests for Model Documentation context.

The suite uses isolated SQLite databases and artifact roots.  It never reads
or mutates the checked-in runtime project registry, dataset registry, analytics
store, documentation index, checkpoint, or atlas_local.db.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
import unittest
from unittest.mock import patch
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP_PARENT = ROOT / ".tmp"
TMP_PARENT.mkdir(exist_ok=True)
RUN_ROOT = (
    TMP_PARENT
    / f"model-documentation-project-context-{uuid.uuid4().hex}"
)
RUN_ROOT.mkdir(parents=True)
SECURITY_DB = RUN_ROOT / "security.db"
PERSISTENCE_DB = RUN_ROOT / "persistence.db"
CHECKPOINT_PATH = RUN_ROOT / "checkpoint.json"
DATASET_ROOT = RUN_ROOT / "datasets"
PROJECT_ROOT = RUN_ROOT / "projects"
ANALYTICS_ROOT = RUN_ROOT / "analytics"
DOCUMENT_ROOT = RUN_ROOT / "model_documentation"
RUN_ID = uuid.uuid4().hex[:10]

os.environ["ATLAS_SECURITY_DB_PATH"] = str(SECURITY_DB)
os.environ["ATLAS_SQLITE_PATH"] = str(PERSISTENCE_DB)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(CHECKPOINT_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(DATASET_ROOT)
os.environ["ATLAS_AUTH_ENABLED"] = "true"
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from server.analytics import analytics_store  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402
from server.main import app  # noqa: E402
from server.model_documentation import documentation_router  # noqa: E402
from server.model_documentation import documentation_store  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.projects import project_registry  # noqa: E402
from server.security import security_store  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402


PROJECT_A = f"synthetic-context-a-{RUN_ID}"
PROJECT_B = f"synthetic-context-b-{RUN_ID}"
LEGACY_ONLY = f"synthetic-legacy-only-{RUN_ID}"
DATASET_A = f"synthetic-dataset-a-{RUN_ID}"
DATASET_B = f"synthetic-dataset-b-{RUN_ID}"
DOCUMENT_A = f"synthetic-document-a-{RUN_ID}"
DOCUMENT_B = f"synthetic-document-b-{RUN_ID}"
B_SENTINEL = f"PROJECT-B-SENTINEL-{RUN_ID}"


def configure_isolated_artifact_paths() -> None:
    project_registry.PROJECT_ARTIFACT_ROOT = PROJECT_ROOT
    project_registry.PROJECT_REGISTRY_PATH = (
        PROJECT_ROOT / "project_registry.json"
    )
    analytics_store.ANALYTICS_ROOT = ANALYTICS_ROOT
    analytics_store.INSIGHTS_PATH = ANALYTICS_ROOT / "insights.json"
    documentation_store.DOCUMENTATION_ROOT = DOCUMENT_ROOT
    documentation_store.DOCUMENT_INDEX_PATH = (
        DOCUMENT_ROOT / "document_index.json"
    )


def register(label: str) -> tuple[TestClient, dict]:
    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{RUN_ID}@model-documentation.test",
            "displayName": f"Synthetic Documentation {label}",
            "password": "SyntheticDocumentationTest!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()["user"]


def create_project(
    client: TestClient,
    project_id: str,
    project_name: str,
) -> None:
    response = client.post(
        "/api/projects",
        json={
            "projectId": project_id,
            "projectName": project_name,
            "projectType": "predictive-modeling",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["project"]["projectId"] == project_id


def dataset_record(
    dataset_id: str,
    name: str,
    owner_user_id: str,
    viewer_user_id: str,
) -> dict:
    return {
        "datasetId": dataset_id,
        "name": name,
        "description": f"Synthetic isolated dataset {name}",
        "sourceType": "test_fixture",
        "ownerUserId": owner_user_id,
        "ownerDisplayName": "Synthetic Fixture Owner",
        "access": [{"userId": viewer_user_id, "role": "viewer"}],
        "versions": [
            {
                "versionId": f"version-{dataset_id}",
                "rowCount": 10,
                "columnCount": 3,
            }
        ],
        "sourceInfo": {
            "targetColumn": f"target-{dataset_id}",
            "task": "classification",
        },
        "createdAt": "2026-01-01T00:00:00+00:00",
        "updatedAt": "2026-01-01T00:00:00+00:00",
    }


def project_record(
    project_id: str,
    name: str,
    *,
    target: str,
    champion: str,
    linked_datasets: list[dict] | None = None,
) -> dict:
    return {
        "projectId": project_id,
        "name": name,
        "projectType": "predictive_modeling",
        "taskType": "classification",
        "target": target,
        "championModel": champion,
        "linkedDatasets": linked_datasets or [],
        "createdAt": "2026-01-01T00:00:00+00:00",
        "lastSavedAt": "2026-01-02T00:00:00+00:00",
        "storageLocation": "legacy_registry",
        "recoveryStatus": "Exact synthetic enrichment",
    }


def insight(
    insight_id: str,
    project_id: str,
    dataset_id: str,
    title: str,
    analysis_type: str,
) -> dict:
    return {
        "insightId": insight_id,
        "projectId": project_id,
        "datasetId": dataset_id,
        "title": title,
        "summary": f"Synthetic isolated insight {title}",
        "analysisType": analysis_type,
        "createdIn": (
            "ATLAS Model Diagnostics"
            if analysis_type == "model_diagnostics"
            else "Analytics Workbench"
        ),
        "createdAt": "2026-01-03T00:00:00+00:00",
    }


def write_document_fixture(
    document_id: str,
    project_id: str,
    project_name: str,
) -> dict:
    DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
    document = {
        "documentId": document_id,
        "projectId": project_id,
        "projectName": project_name,
        "templateType": "model_development_document",
        "sections": [],
    }
    (DOCUMENT_ROOT / f"{document_id}.json").write_text(
        json.dumps(document),
        encoding="utf-8",
    )
    return document


class ModelDocumentationProjectContextTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        configure_isolated_artifact_paths()
        init_security_store()
        assert initialize_persistence()["ok"] is True

        cls.owner_a, cls.user_a = register("owner-a")
        cls.owner_b, cls.user_b = register("owner-b")
        create_project(
            cls.owner_a,
            PROJECT_A,
            "Synthetic Relational Project A",
        )
        create_project(
            cls.owner_b,
            PROJECT_B,
            "Synthetic Relational Project B",
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.owner_a.close()
        cls.owner_b.close()

    def setUp(self) -> None:
        project_registry.save_project_registry(
            {
                "projects": [
                    project_record(
                        PROJECT_B,
                        f"{B_SENTINEL} Project",
                        target=f"{B_SENTINEL}-TARGET",
                        champion=f"{B_SENTINEL}-CHAMPION",
                    )
                ]
            }
        )
        dataset_registry.save_registry(
            {
                "datasets": [
                    dataset_record(
                        DATASET_B,
                        f"{B_SENTINEL} Dataset",
                        self.user_b["userId"],
                        self.user_a["userId"],
                    )
                ]
            }
        )
        dataset_registry.save_links(
            {
                "links": [
                    {
                        "projectId": PROJECT_B,
                        "datasetId": DATASET_B,
                        "datasetRole": "TRAIN",
                        "versionId": f"version-{DATASET_B}",
                    }
                ]
            }
        )
        analytics_store.save_store(
            {
                "insights": [
                    insight(
                        f"diagnostic-b-{RUN_ID}",
                        PROJECT_B,
                        DATASET_B,
                        f"{B_SENTINEL} Diagnostic",
                        "model_diagnostics",
                    ),
                    insight(
                        f"chart-b-{RUN_ID}",
                        PROJECT_B,
                        DATASET_B,
                        f"{B_SENTINEL} Chart",
                        "chart_studio",
                    ),
                    insight(
                        f"analytics-b-{RUN_ID}",
                        PROJECT_B,
                        DATASET_B,
                        f"{B_SENTINEL} Analytics",
                        "dataset_overview",
                    ),
                ]
            }
        )

        document_a = write_document_fixture(
            DOCUMENT_A,
            PROJECT_A,
            "Synthetic Relational Project A",
        )
        document_b = write_document_fixture(
            DOCUMENT_B,
            PROJECT_B,
            "Synthetic Relational Project B",
        )
        dataset_registry.write_json(
            documentation_store.DOCUMENT_INDEX_PATH,
            {"documents": [document_b, document_a]},
        )

    def build_as_owner_a(self, project_id: str) -> dict:
        token = security_store.ACTIVE_USER.set(self.user_a)
        try:
            return documentation_store.build_project_context(project_id)
        finally:
            security_store.ACTIVE_USER.reset(token)

    def test_direct_context_uses_exact_relational_project_without_legacy_entry(
        self,
    ) -> None:
        context = self.build_as_owner_a(PROJECT_A)

        self.assertEqual(context["project"]["projectId"], PROJECT_A)
        self.assertEqual(
            context["project"]["projectName"],
            "Synthetic Relational Project A",
        )
        self.assertEqual(context["datasets"], [])
        self.assertEqual(context["analyticsInsights"], [])
        self.assertEqual(context["chartInsights"], [])
        self.assertEqual(context["diagnosticInsights"], [])
        self.assertNotIn(B_SENTINEL, json.dumps(context))

    def test_context_api_does_not_borrow_other_project_collections(self) -> None:
        response = self.owner_a.get(
            f"/api/model-documentation/project-context/{PROJECT_A}"
        )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["context"]["project"]["projectId"], PROJECT_A)
        self.assertEqual(payload["context"]["datasets"], [])
        self.assertEqual(payload["context"]["analyticsInsights"], [])
        self.assertEqual(payload["context"]["chartInsights"], [])
        self.assertEqual(payload["context"]["diagnosticInsights"], [])
        self.assertEqual(
            [item["documentId"] for item in payload["documents"]],
            [DOCUMENT_A],
        )
        self.assertNotIn(B_SENTINEL, response.text)

        evidence = self.owner_a.get(
            f"/api/model-documentation/{DOCUMENT_A}/evidence-library",
            params={"projectId": PROJECT_A},
        )
        self.assertEqual(evidence.status_code, 200, evidence.text)
        self.assertNotIn(B_SENTINEL, evidence.text)

    def test_exact_legacy_record_enriches_only_matching_project(self) -> None:
        dataset_a = dataset_record(
            DATASET_A,
            "Synthetic Dataset A",
            self.user_a["userId"],
            self.user_a["userId"],
        )
        dataset_b = dataset_record(
            DATASET_B,
            f"{B_SENTINEL} Dataset",
            self.user_b["userId"],
            self.user_a["userId"],
        )
        dataset_registry.save_registry({"datasets": [dataset_a, dataset_b]})
        dataset_registry.save_links(
            {
                "links": [
                    {
                        "projectId": PROJECT_A,
                        "datasetId": DATASET_A,
                        "datasetRole": "TRAIN",
                        "versionId": f"version-{DATASET_A}",
                    },
                    {
                        "projectId": PROJECT_B,
                        "datasetId": DATASET_B,
                        "datasetRole": "TRAIN",
                        "versionId": f"version-{DATASET_B}",
                    },
                ]
            }
        )
        project_registry.save_project_registry(
            {
                "projects": [
                    project_record(
                        PROJECT_B,
                        f"{B_SENTINEL} Project",
                        target=f"{B_SENTINEL}-TARGET",
                        champion=f"{B_SENTINEL}-CHAMPION",
                    ),
                    project_record(
                        PROJECT_A,
                        "Legacy Name Must Not Replace Relational Name",
                        target="synthetic_target_a",
                        champion="Synthetic Champion A",
                    ),
                ]
            }
        )
        analytics_store.save_store(
            {
                "insights": [
                    insight(
                        f"diagnostic-a-{RUN_ID}",
                        PROJECT_A,
                        DATASET_A,
                        "Synthetic Diagnostic A",
                        "model_diagnostics",
                    ),
                    insight(
                        f"diagnostic-b-{RUN_ID}",
                        PROJECT_B,
                        DATASET_B,
                        f"{B_SENTINEL} Diagnostic",
                        "model_diagnostics",
                    ),
                ]
            }
        )

        context = self.build_as_owner_a(PROJECT_A)

        self.assertEqual(context["project"]["projectId"], PROJECT_A)
        self.assertEqual(
            context["project"]["projectName"],
            "Synthetic Relational Project A",
        )
        self.assertEqual(
            context["project"]["target"],
            "synthetic_target_a",
        )
        self.assertEqual(
            context["project"]["championModel"],
            "Synthetic Champion A",
        )
        self.assertEqual(
            [item["datasetId"] for item in context["datasets"]],
            [DATASET_A],
        )
        self.assertEqual(
            [item["title"] for item in context["diagnosticInsights"]],
            ["Synthetic Diagnostic A"],
        )
        self.assertNotIn(B_SENTINEL, json.dumps(context))

    def test_legacy_only_nonexistent_project_is_404(self) -> None:
        project_registry.save_project_registry(
            {
                "projects": [
                    project_record(
                        LEGACY_ONLY,
                        "Synthetic Legacy-Only Project",
                        target="legacy_only_target",
                        champion="Legacy-Only Champion",
                    )
                ]
            }
        )

        response = self.owner_a.get(
            f"/api/model-documentation/project-context/{LEGACY_ONLY}"
        )

        self.assertEqual(response.status_code, 404, response.text)

    def test_user_a_cannot_receive_project_b_context(self) -> None:
        denied = self.owner_a.get(
            f"/api/model-documentation/project-context/{PROJECT_B}"
        )
        self.assertEqual(denied.status_code, 403, denied.text)

        own = self.owner_a.get(
            f"/api/model-documentation/project-context/{PROJECT_A}"
        )
        self.assertEqual(own.status_code, 200, own.text)
        self.assertEqual(
            own.json()["context"]["project"]["projectId"],
            PROJECT_A,
        )
        self.assertNotIn(B_SENTINEL, own.text)

    def test_route_rejects_and_audits_mismatched_context(self) -> None:
        mismatched = {
            "project": {
                "projectId": PROJECT_B,
                "projectName": f"{B_SENTINEL} Project",
            },
            "datasets": [{"dataset": f"{B_SENTINEL} Dataset"}],
        }

        with (
            patch.object(
                documentation_router,
                "build_project_context",
                return_value=mismatched,
            ),
            patch.object(documentation_router, "audit_event") as audit,
        ):
            response = self.owner_a.get(
                f"/api/model-documentation/project-context/{PROJECT_A}"
            )

        self.assertEqual(response.status_code, 500, response.text)
        self.assertEqual(
            response.json()["detail"],
            "ATLAS could not safely resolve the requested project context.",
        )
        self.assertNotIn(B_SENTINEL, response.text)
        audit.assert_called_once()
        args, kwargs = audit.call_args
        self.assertEqual(
            args[:4],
            (
                "model_documentation.project_context.integrity_failure",
                "project",
                PROJECT_A,
                "failure",
            ),
        )
        self.assertEqual(kwargs["user_id"], self.user_a["userId"])
        self.assertEqual(kwargs["metadata"]["projectId"], PROJECT_A)
        self.assertEqual(kwargs["metadata"]["resolvedProjectId"], PROJECT_B)


def cleanup() -> None:
    for database in (SECURITY_DB, PERSISTENCE_DB):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{database}{suffix}")
            for attempt in range(20):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt == 19:
                        break
                    time.sleep(0.1)
    shutil.rmtree(RUN_ROOT, ignore_errors=True)


if __name__ == "__main__":
    try:
        result = unittest.main(verbosity=2, exit=False).result
    finally:
        cleanup()
    raise SystemExit(0 if result.wasSuccessful() else 1)
