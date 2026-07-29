"""Governed Experimental Design workflow integration and statistical checks.

Run:
    .venv/Scripts/python.exe tests/experimental_design_premium_backend_test.py
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP_ROOT = ROOT / ".tmp"
TMP_ROOT.mkdir(exist_ok=True)
RUN_ID = uuid.uuid4().hex[:10]
SECURITY_DB = TMP_ROOT / f"experimental_design_security_{RUN_ID}.db"
PERSISTENCE_DB = TMP_ROOT / f"experimental_design_persistence_{RUN_ID}.db"
CHECKPOINT = TMP_ROOT / f"experimental_design_checkpoint_{RUN_ID}.json"
os.environ["ATLAS_SECURITY_DB_PATH"] = str(SECURITY_DB)
os.environ["ATLAS_SQLITE_PATH"] = str(PERSISTENCE_DB)
os.environ["ATLAS_CHECKPOINT_PATH"] = str(CHECKPOINT)
os.environ["ATLAS_AUTH_ENABLED"] = "true"
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from server.experimental_design.service import (  # noqa: E402
    EXPERIMENTAL_DESIGN,
    ExperimentalDesignService,
    analyze_observations,
    calculate_power,
    generate_design,
    normalize_contract,
    recommend_designs,
)
from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence.service import get_persistence_service  # noqa: E402
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


def register(label: str) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{RUN_ID}@experimental-design.test",
            "displayName": f"Experimental Design {label}",
            "password": "ExperimentalDesignTest!1",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client


def create_project(client: TestClient) -> str:
    response = client.post(
        "/api/projects",
        json={"projectName": "Disposable Experimental Design Acceptance", "projectType": "experimental-design"},
    )
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def governed_contract(project_id: str) -> dict:
    return normalize_contract(
        project_id,
        {
            "title": "Contact strategy factorial study",
            "objective": {
                "businessObjective": "Select a contact strategy that improves completed applications.",
                "decision": "Choose the treatment cell for a controlled rollout.",
                "population": "Eligible consenting applicants",
                "unitOfRandomization": "Applicant",
                "primaryResponse": {
                    "name": "Completion score",
                    "type": "continuous",
                    "direction": "maximize",
                    "unit": "points",
                },
                "nullHypothesis": "Treatment cell means are equal.",
                "alternativeHypothesis": "At least one cell mean differs.",
                "successCriterion": "Observed improvement exceeds 0.5 points with acceptable uncertainty.",
            },
            "factors": [
                {
                    "factorId": "factor-channel",
                    "name": "Channel",
                    "kind": "categorical",
                    "levels": ["Email", "SMS"],
                    "unit": "",
                    "controllable": True,
                },
                {
                    "factorId": "factor-message",
                    "name": "Message",
                    "kind": "categorical",
                    "levels": ["Standard", "Enhanced"],
                    "unit": "",
                    "controllable": True,
                },
            ],
            "nuisanceFactors": [
                {
                    "nuisanceId": "nuisance-week",
                    "name": "Week",
                    "strategy": "measure",
                    "levels": ["Week 1", "Week 2"],
                }
            ],
            "design": {
                "family": "full_factorial",
                "analystConfirmed": True,
                "replicates": 2,
                "centerPoints": 3,
                "rationale": "All four treatment cells fit operational capacity and interactions matter.",
            },
            "power": {
                "alpha": 0.05,
                "targetPower": 0.8,
                "minimumDetectableEffect": 0.5,
                "standardDeviation": 1.0,
                "responseKind": "continuous",
                "effectsTested": 3,
            },
            "randomization": {"seed": 918273, "restricted": False, "restriction": ""},
            "limitations": ["Synthetic acceptance outcomes are not operational evidence."],
        },
    )


def statistical_unit_checks(project_id: str) -> None:
    contract = governed_contract(project_id)
    recommendation = recommend_designs(contract)
    assert recommendation["analystDecisionRequired"] is True
    assert recommendation["recommendation"] == "full_factorial"
    assert any(item["family"] == "response_surface" and not item["eligible"] for item in recommendation["catalog"])

    power = calculate_power(contract)
    assert power["perCell"] > 2
    assert power["achievedPower"] >= 0.8
    assert power["totalSample"] == power["perCell"] * 4
    assert len(power["curve"]) >= 20

    design = generate_design(contract)
    assert design["family"] == "full_factorial"
    assert design["runCount"] == 8
    assert len({row["runId"] for row in design["rows"]}) == 8
    assert design["aliasStructure"] == []

    observations = []
    for index, row in enumerate(design["rows"]):
        coded = row["_coded"]
        response = 10 + 0.8 * coded["Channel"] + 0.5 * coded["Message"] + 0.35 * coded["Channel"] * coded["Message"]
        response += (-0.08 if index % 2 else 0.08)
        observations.append({"runId": row["runId"], "response": response})
    analysis = analyze_observations(design, observations)
    assert analysis["observationCount"] == 8
    assert analysis["cellCount"] == 4
    assert analysis["anovaTable"][1]["df"] == 4
    assert any(row["term"] == "Channel × Message" for row in analysis["effects"])
    assert analysis["recommendation"]["bestObservedCell"]

    fractional = normalize_contract(
        project_id,
        {
            **contract,
            "factors": [
                {"factorId": f"f-{name}", "name": name, "kind": "categorical", "levels": ["Low", "High"]}
                for name in ("A", "B", "C", "D")
            ],
            "design": {"family": "fractional_factorial", "analystConfirmed": True, "replicates": 1},
        },
    )
    fractional_design = generate_design(fractional)
    assert fractional_design["runCount"] == 8
    assert fractional_design["aliasStructure"]
    assert any("I =" in row["definingRelation"] for row in fractional_design["aliasStructure"])


def api_integration_checks() -> None:
    init_security_store()
    migration_health = initialize_persistence()
    assert migration_health["ok"] is True
    assert "experimental_design_studies" in migration_health["tables"]
    owner = register("owner")
    outsider = register("outsider")
    project_id = create_project(owner)
    statistical_unit_checks(project_id)

    denied = outsider.get("/api/experimental-design/study", params={"project_id": project_id})
    assert denied.status_code == 403, denied.text

    initial = owner.get("/api/experimental-design/study", params={"project_id": project_id})
    assert initial.status_code == 200, initial.text
    assert initial.json()["persisted"] is False

    contract = governed_contract(project_id)
    saved = owner.put(
        f"/api/experimental-design/study/{project_id}",
        json={"contract": contract, "changeSummary": "Confirmed acceptance study contract."},
    )
    assert saved.status_code == 200, saved.text
    saved_body = saved.json()
    assert saved_body["study"]["currentVersion"] == 1
    assert saved_body["study"]["blockers"] == []

    recommendation = owner.post(
        "/api/experimental-design/recommend",
        json={"projectId": project_id},
    )
    assert recommendation.status_code == 200, recommendation.text
    assert recommendation.json()["analystDecisionRequired"] is True

    power_started = time.perf_counter()
    power = owner.post("/api/experimental-design/power", json={"projectId": project_id})
    assert power.status_code == 200, power.text
    power_duration_ms = (time.perf_counter() - power_started) * 1000
    assert power_duration_ms < 2_000
    assert power.json()["totalSample"] > 0

    design_started = time.perf_counter()
    design_response = owner.post("/api/experimental-design/design/generate", json={"projectId": project_id})
    assert design_response.status_code == 200, design_response.text
    design_duration_ms = (time.perf_counter() - design_started) * 1000
    assert design_duration_ms < 2_000
    design = design_response.json()
    assert design["runCount"] == 8
    assert design["designVersion"].startswith("design-")

    first_randomization = owner.post(
        "/api/experimental-design/randomize",
        json={"projectId": project_id, "seed": 918273},
    )
    second_randomization = owner.post(
        "/api/experimental-design/randomize",
        json={"projectId": project_id, "seed": 918273},
    )
    assert first_randomization.status_code == 200, first_randomization.text
    assert second_randomization.status_code == 200, second_randomization.text
    first_order = [row["runId"] for row in first_randomization.json()["rows"]]
    second_order = [row["runId"] for row in second_randomization.json()["rows"]]
    assert first_order == second_order
    assert first_randomization.json()["randomizationVersion"] == second_randomization.json()["randomizationVersion"]

    job_started = time.perf_counter()
    simulation_response = owner.post(
        "/api/experimental-design/simulations",
        json={"projectId": project_id, "iterations": 1200, "seed": 918273},
    )
    assert simulation_response.status_code == 200, simulation_response.text
    simulation_submit_ms = (time.perf_counter() - job_started) * 1000
    assert simulation_submit_ms < 1_000
    job_id = simulation_response.json()["job"]["simulationJobId"]
    simulation_poll_started = time.perf_counter()
    deadline = time.time() + 15
    job = {}
    while time.time() < deadline:
        poll = owner.get(
            f"/api/experimental-design/simulations/{job_id}",
            params={"project_id": project_id},
        )
        assert poll.status_code == 200, poll.text
        job = poll.json()["job"]
        if job["status"] in {"complete", "failed", "cancelled", "interrupted"}:
            break
        time.sleep(0.05)
    assert job["status"] == "complete", job
    assert job["progress"] == 1.0
    assert 0 <= job["results"]["empiricalPower"] <= 1
    assert job["results"]["scope"] == "simulated_operating_characteristics"
    simulation_complete_ms = (time.perf_counter() - simulation_poll_started) * 1000

    outsider_job = outsider.get(
        f"/api/experimental-design/simulations/{job_id}",
        params={"project_id": project_id},
    )
    assert outsider_job.status_code == 403

    # Hold both worker slots so a third job is deterministically queued, then
    # prove cancellation and retry behavior without relying on timing races.
    assert EXPERIMENTAL_DESIGN._capacity.acquire(timeout=1)
    assert EXPERIMENTAL_DESIGN._capacity.acquire(timeout=1)
    try:
        queued_response = owner.post(
            "/api/experimental-design/simulations",
            json={"projectId": project_id, "iterations": 20_000, "seed": 445566},
        )
        assert queued_response.status_code == 200, queued_response.text
        queued_job_id = queued_response.json()["job"]["simulationJobId"]
        cancelled = owner.post(
            f"/api/experimental-design/simulations/{queued_job_id}/cancel",
            json={"projectId": project_id},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["job"]["status"] == "cancelling"
    finally:
        EXPERIMENTAL_DESIGN._capacity.release()
        EXPERIMENTAL_DESIGN._capacity.release()

    deadline = time.time() + 5
    cancelled_job = {}
    while time.time() < deadline:
        cancelled_poll = owner.get(
            f"/api/experimental-design/simulations/{queued_job_id}",
            params={"project_id": project_id},
        )
        assert cancelled_poll.status_code == 200, cancelled_poll.text
        cancelled_job = cancelled_poll.json()["job"]
        if cancelled_job["status"] == "cancelled":
            break
        time.sleep(0.02)
    assert cancelled_job["status"] == "cancelled", cancelled_job
    assert cancelled_job["error"]["recoverable"] is True

    retry = owner.post(
        f"/api/experimental-design/simulations/{queued_job_id}/retry",
        json={"projectId": project_id},
    )
    assert retry.status_code == 200, retry.text
    retry_job_id = retry.json()["job"]["simulationJobId"]
    assert retry.json()["job"]["retryParentJobId"] == queued_job_id
    deadline = time.time() + 15
    retried_job = {}
    while time.time() < deadline:
        retry_poll = owner.get(
            f"/api/experimental-design/simulations/{retry_job_id}",
            params={"project_id": project_id},
        )
        assert retry_poll.status_code == 200, retry_poll.text
        retried_job = retry_poll.json()["job"]
        if retried_job["status"] in {"complete", "failed", "cancelled", "interrupted"}:
            break
        time.sleep(0.05)
    assert retried_job["status"] == "complete", retried_job

    # Simulate a process exit after a durable job was written but before it
    # reached a terminal state. A fresh service instance must fail it closed
    # as recoverable rather than presenting a phantom running job.
    recovery_record = service_record = get_persistence_service().experimental_design.get_job(retry_job_id)
    assert service_record is not None
    recovery_record.update(
        {
            "status": "running",
            "progress": 0.42,
            "error_json": {},
            "completed_at": None,
        }
    )
    get_persistence_service().experimental_design.upsert_job(recovery_record)
    recovered_service = ExperimentalDesignService()
    recovered_service.repository
    interrupted_job = recovered_service.get_job(project_id, retry_job_id)["job"]
    assert interrupted_job["status"] == "interrupted"
    assert interrupted_job["error"]["code"] == "server_restart"
    assert interrupted_job["error"]["recoverable"] is True

    observations = []
    for index, row in enumerate(design["rows"]):
        coded = row["_coded"]
        response = 10 + 0.8 * coded["Channel"] + 0.5 * coded["Message"]
        response += (-0.1 if index % 2 else 0.1)
        observations.append({"runId": row["runId"], "response": response})
    analysis_response = owner.post(
        "/api/experimental-design/analyze",
        json={"projectId": project_id, "observations": observations},
    )
    assert analysis_response.status_code == 200, analysis_response.text
    assert analysis_response.json()["status"] == "observed_analysis"
    assert analysis_response.json()["anovaTable"]

    documentation = owner.post(
        "/api/experimental-design/documentation/capture",
        json={"projectId": project_id},
    )
    assert documentation.status_code == 200, documentation.text
    assert documentation.json()["documentation"]["readinessScore"] == 100

    reopen_started = time.perf_counter()
    reopened = owner.get("/api/experimental-design/study", params={"project_id": project_id})
    reopen_duration_ms = (time.perf_counter() - reopen_started) * 1000
    assert reopened.status_code == 200, reopened.text
    reopened_body = reopened.json()
    assert reopened_body["persisted"] is True
    assert reopened_body["study"]["currentVersion"] == 1
    assert set(reopened_body["study"]["artifacts"]) >= {
        "power",
        "design",
        "randomization",
        "simulation",
        "analysis",
        "documentation",
    }
    assert reopened_body["versions"][0]["versionNumber"] == 1

    evidence = owner.get(f"/api/projects/{project_id}/evidence")
    assert evidence.status_code == 200, evidence.text
    evidence_types = {item["artifactType"] for item in evidence.json()["evidence"]}
    assert {"study_contract", "design_matrix", "randomization_plan", "simulation_results", "observed_analysis", "documentation_package"}.issubset(evidence_types)

    decisions = owner.get(f"/api/projects/{project_id}/decisions")
    assert decisions.status_code == 200, decisions.text
    assert any(item["decisionType"] == "experimental_design_family_selection" for item in decisions.json()["decisions"])

    changed_contract = reopened_body["study"]["contract"]
    changed_contract["factors"][0]["levels"] = ["Email", "SMS", "Phone"]
    changed = owner.put(
        f"/api/experimental-design/study/{project_id}",
        json={"contract": changed_contract, "changeSummary": "Added an operating level."},
    )
    assert changed.status_code == 200, changed.text
    changed_body = changed.json()
    assert changed_body["study"]["currentVersion"] == 2
    assert "design" in changed_body["invalidatedArtifacts"]
    assert changed_body["study"]["artifacts"] == {}

    service = get_persistence_service()
    persisted_versions = service.experimental_design.list_versions(project_id)
    assert [row["version_number"] for row in persisted_versions] == [2, 1]
    assert persisted_versions[1]["contract_json"]["factors"][0]["levels"] == ["Email", "SMS"]

    print(
        {
            "study_versions": 2,
            "design_runs": design["runCount"],
            "simulation_iterations": job["iterations"],
            "empirical_power": round(job["results"]["empiricalPower"], 4),
            "evidence_types": sorted(evidence_types),
            "cross_user_denied": True,
            "reopen_persistence": True,
            "downstream_invalidation": changed_body["invalidatedArtifacts"],
            "job_lifecycle": {
                "cancelled": cancelled_job["status"],
                "retry_completed_before_restart_probe": True,
                "restart_recovery": interrupted_job["status"],
            },
            "performance_ms": {
                "power": round(power_duration_ms, 2),
                "design_generation": round(design_duration_ms, 2),
                "simulation_submit": round(simulation_submit_ms, 2),
                "simulation_1200_complete": round(simulation_complete_ms, 2),
                "reopen": round(reopen_duration_ms, 2),
            },
        }
    )


if __name__ == "__main__":
    try:
        cleanup()
        api_integration_checks()
    finally:
        cleanup()
