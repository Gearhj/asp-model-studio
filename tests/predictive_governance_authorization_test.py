"""Cross-project authorization checks for Predictive Modeling governance surfaces."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP_ROOT = ROOT / ".tmp"
TMP_ROOT.mkdir(exist_ok=True)
RUN_ID = uuid.uuid4().hex[:10]
SECURITY_DB = TMP_ROOT / f"predictive_governance_security_{RUN_ID}.db"
PERSISTENCE_DB = TMP_ROOT / f"predictive_governance_persistence_{RUN_ID}.db"
CHECKPOINT = TMP_ROOT / f"predictive_governance_checkpoint_{RUN_ID}.json"
DOCUMENT_ROOT = TMP_ROOT / f"predictive_governance_documents_{RUN_ID}"

os.environ["ATLAS_SECURITY_DB_PATH"] = str(SECURITY_DB)
os.environ["ATLAS_SQLITE_PATH"] = str(PERSISTENCE_DB)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(CHECKPOINT)
os.environ["ATLAS_AUTH_ENABLED"] = "true"
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.model_documentation import documentation_store  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402


def cleanup() -> None:
    for base in (SECURITY_DB, PERSISTENCE_DB):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(20):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt == 19:
                        break
                    time.sleep(0.1)
    CHECKPOINT.unlink(missing_ok=True)
    shutil.rmtree(DOCUMENT_ROOT, ignore_errors=True)


def register(label: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{RUN_ID}@predictive-governance.test",
            "displayName": f"Predictive Governance {label}",
            "password": "PredictiveGovernanceTest!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client


def create_project(client: TestClient) -> str:
    response = client.post(
        "/api/projects",
        json={
            "projectName": "Disposable Predictive Governance Authorization",
            "projectType": "predictive-modeling",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def run_checks() -> None:
    init_security_store()
    assert initialize_persistence()["ok"] is True

    documentation_store.DOCUMENTATION_ROOT = DOCUMENT_ROOT
    documentation_store.DOCUMENT_INDEX_PATH = DOCUMENT_ROOT / "document_index.json"

    owner = register("owner")
    outsider = register("outsider")
    project_id = create_project(owner)

    created_plan = owner.post(f"/api/monitoring/projects/{project_id}/create-plan", json={})
    assert created_plan.status_code == 200, created_plan.text
    plan_id = created_plan.json()["plan"]["monitoring_plan_id"]

    assert outsider.get(f"/api/monitoring/projects/{project_id}/plan").status_code == 403
    assert outsider.get(f"/api/monitoring/plans/{plan_id}").status_code == 403
    assert outsider.put(f"/api/monitoring/plans/{plan_id}", json={}).status_code == 403

    outsider_plans = outsider.get("/api/monitoring/plans")
    assert outsider_plans.status_code == 200, outsider_plans.text
    assert outsider_plans.json()["items"] == []
    outsider_summary = outsider.get("/api/monitoring/summary")
    assert outsider_summary.status_code == 200, outsider_summary.text
    assert outsider_summary.json()["summary"]["total_plans"] == 0

    owner_plans = owner.get("/api/monitoring/plans")
    assert owner_plans.status_code == 200, owner_plans.text
    assert [item["monitoring_plan_id"] for item in owner_plans.json()["items"]] == [plan_id]

    assert outsider.get(f"/api/model-documentation/project-context/{project_id}").status_code == 403
    assert outsider.post(
        "/api/model-documentation/create",
        json={
            "projectId": project_id,
            "templateType": "model_development_document",
            "createdBy": "spoofed actor",
        },
    ).status_code == 403

    document_id = f"doc-{project_id}-authorization"
    DOCUMENT_ROOT.mkdir(parents=True, exist_ok=True)
    (DOCUMENT_ROOT / f"{document_id}.json").write_text(
        json.dumps(
            {
                "documentId": document_id,
                "projectId": project_id,
                "projectName": "Disposable Predictive Governance Authorization",
                "templateType": "model_development_document",
            }
        ),
        encoding="utf-8",
    )
    assert owner.get(f"/api/model-documentation/{document_id}").status_code == 200
    assert outsider.get(f"/api/model-documentation/{document_id}").status_code == 403
    assert outsider.post(
        f"/api/model-documentation/{document_id}/quality-check",
        json={},
    ).status_code == 403
    assert outsider.post(
        f"/api/model-documentation/{document_id}/export/word",
        json={},
    ).status_code == 403

    print(
        {
            "monitoring_direct_object_denied": True,
            "monitoring_global_lists_filtered": True,
            "monitoring_summary_filtered": True,
            "documentation_project_denied": True,
            "documentation_direct_object_denied": True,
            "documentation_export_denied": True,
        }
    )
    owner.close()
    outsider.close()


if __name__ == "__main__":
    try:
        cleanup()
        run_checks()
    finally:
        cleanup()
