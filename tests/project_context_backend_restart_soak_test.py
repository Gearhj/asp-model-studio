"""Isolated FastAPI restart soak for Project Context and pre-training authority.

This executable integration test launches ``server.main:app`` on a dedicated
loopback port with every mutable ATLAS authority rooted below a UUID-specific
``.tmp`` directory.  It creates only synthetic fixture data, then proves that
Project Context, workflow state, exact Dataset Library identity, and governed
EDA readiness survive ten complete backend process replacements.

The test intentionally does not call Model Training, Evaluation,
Interpretation, promotion, or Scoring endpoints.  Its EDA assertion also
requires the server-authored ``finalHoldoutAccessed`` and
``finalHoldoutUsedForSelection`` flags to remain false.

Run:
    .venv/Scripts/python.exe -m pytest -q -s \
        tests/project_context_backend_restart_soak_test.py
"""

from __future__ import annotations

import csv
import io
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
RESTART_CYCLES = 10
CONTINUITY_ENDPOINTS = 5
STARTUP_TIMEOUT_SECONDS = 90.0
REQUEST_TIMEOUT_SECONDS = 120.0


def _fixture_csv() -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=["predictor_a", "predictor_b", "bad_flag"],
    )
    writer.writeheader()
    for index in range(120):
        writer.writerow(
            {
                "predictor_a": round(((index * 7) % 31) + ((index % 3) / 10), 2),
                "predictor_b": round(((index * 11) % 17) + ((index % 4) / 20), 2),
                "bad_flag": 1 if index % 5 in {0, 1} else 0,
            }
        )
    return buffer.getvalue().encode("utf-8")


def _available_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _listener_accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.25):
            return True
    except OSError:
        return False


def _safe_response(response: httpx.Response) -> str:
    """Return a bounded diagnostic without request headers or credentials."""

    text = response.text.replace("\r", " ").replace("\n", " ").strip()
    return text[:800]


class IsolatedBackend:
    def __init__(self, *, port: int, environment: dict[str, str], log_path: Path):
        self.port = port
        self.environment = environment
        self.log_path = log_path
        self.process: subprocess.Popen[bytes] | None = None
        self._log_handle: Any = None

    def start(self) -> int:
        if self.process is not None:
            raise AssertionError("The isolated backend is already running.")
        self._log_handle = self.log_path.open("ab")
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.process = subprocess.Popen(
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "server.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            cwd=REPO_ROOT,
            env=self.environment,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creation_flags,
        )
        deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
        last_error = ""
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError(
                    f"Isolated backend exited during startup with code {self.process.returncode}."
                )
            try:
                response = httpx.get(
                    f"http://127.0.0.1:{self.port}/api/health",
                    timeout=1.0,
                )
                if response.status_code == 200:
                    return int(self.process.pid)
                last_error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                last_error = type(exc).__name__
            time.sleep(0.2)
        raise AssertionError(
            "Isolated backend did not become healthy before the startup deadline "
            f"({last_error or 'no response'})."
        )

    def stop(self) -> dict[str, Any]:
        if self.process is None:
            return {"pid": None, "exit_code": None, "listener_stopped": True}
        process = self.process
        pid = int(process.pid)
        process.terminate()
        forced = False
        try:
            exit_code = process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            forced = True
            process.kill()
            exit_code = process.wait(timeout=10)
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and _listener_accepts(self.port):
            time.sleep(0.1)
        listener_stopped = not _listener_accepts(self.port)
        if self._log_handle is not None:
            self._log_handle.close()
        self._log_handle = None
        self.process = None
        return {
            "pid": pid,
            "exit_code": int(exit_code),
            "forced": forced,
            "listener_stopped": listener_stopped,
        }


class RestartSoak:
    def __init__(self) -> None:
        run_id = uuid.uuid4().hex
        self.runtime_root = (
            REPO_ROOT / ".tmp" / f"atlas_project_context_restart_soak_{run_id}"
        ).resolve()
        self.runtime_root.mkdir(parents=True, exist_ok=False)
        self.backup_root = (
            Path(tempfile.gettempdir())
            / f"atlas_project_context_restart_backups_{run_id}"
        ).resolve()
        self.backup_root.mkdir(parents=True, exist_ok=False)
        self.result_path = self.runtime_root / "restart-soak-result.json"
        self.log_path = self.runtime_root / "backend.log"
        self.port = _available_loopback_port()
        self.environment = self._isolated_environment()
        self.backend = IsolatedBackend(
            port=self.port,
            environment=self.environment,
            log_path=self.log_path,
        )
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{self.port}",
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self.request_counts: Counter[str] = Counter()
        self.restart_records: list[dict[str, Any]] = []
        self.continuity_records: list[dict[str, Any]] = []
        self.identifiers: dict[str, Any] = {}
        self.started_at = time.time()

    def _isolated_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        # Do not inherit a live ATLAS authority, hosted credential, or remote
        # database configuration into this disposable subprocess.
        for key in list(environment):
            if key.startswith("ATLAS_"):
                environment.pop(key, None)
        for key in (
            "DATABASE_URL",
            "PGHOST",
            "PGPORT",
            "PGDATABASE",
            "PGUSER",
            "PGPASSWORD",
        ):
            environment.pop(key, None)

        paths = {
            "ATLAS_SECURITY_ROOT": self.runtime_root / "security",
            "ATLAS_SECURITY_DB_PATH": self.runtime_root / "security" / "security.db",
            "ATLAS_SQLITE_PATH": self.runtime_root / "persistence" / "atlas.db",
            "ATLAS_CHECKPOINT_PATH": self.runtime_root / "checkpoint" / "workflow.json",
            "ATLAS_DATASET_LIBRARY_ROOT": self.runtime_root / "dataset-library",
            # Production requires Dataset Library safety backups to be
            # physically outside the repository and outside the library root.
            # Windows Temp is the second disposable root authorized by this
            # harness; it remains UUID-scoped and never overlaps live state.
            "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": self.backup_root,
            "ATLAS_EVIDENCE_ROOT": self.runtime_root / "evidence",
            "ATLAS_FEATURE_MANIFEST_ROOT": self.runtime_root / "feature-manifests",
            "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": self.runtime_root / "model-registry",
            "ATLAS_SCORING_RUN_ARTIFACT_ROOT": self.runtime_root / "scoring-runs",
            "ATLAS_VIF_PLAN_ROOT": self.runtime_root / "vif-plans",
            "ATLAS_PYTHON_RUNTIME_DIR": self.runtime_root / "python-runtime",
        }
        for name, path in paths.items():
            resolved = path.resolve()
            allowed_external_backup = (
                name == "ATLAS_DATASET_LIBRARY_BACKUP_ROOT"
                and resolved == self.backup_root
            )
            if (
                not allowed_external_backup
                and resolved != self.runtime_root
                and self.runtime_root not in resolved.parents
            ):
                raise AssertionError(f"{name} escaped the disposable runtime root.")
            if name.endswith("_ROOT") or name.endswith("_DIR"):
                resolved.mkdir(parents=True, exist_ok=True)
            else:
                resolved.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.runtime_root / "temp"
        temporary.mkdir(parents=True, exist_ok=True)
        environment.update({name: str(path) for name, path in paths.items()})
        environment.update(
            {
                "ATLAS_ENV": "testing",
                "ATLAS_TEST_MODE": "1",
                "ATLAS_AUTH_ENABLED": "true",
                "ATLAS_ALLOW_PUBLIC_REGISTRATION": "true",
                "ATLAS_LOCAL_DEV": "false",
                "ATLAS_DEV_MODE": "false",
                "ATLAS_HOSTED_MODE": "false",
                "ATLAS_ENABLE_DEV_USER_HEADER": "false",
                "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "false",
                "ATLAS_DEV_AUTH_TOOLS": "false",
                "ATLAS_COOKIE_SECURE": "false",
                "ATLAS_ENABLE_PYTHON_RUN": "0",
                "ATLAS_SESSION_SECRET": secrets.token_hex(48),
                "ATLAS_DEFAULT_ADMIN_PASSWORD": f"Unused!{secrets.token_hex(24)}",
                "ATLAS_CHECKPOINT_DEBOUNCE_SECONDS": "0.1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "TEMP": str(temporary),
                "TMP": str(temporary),
            }
        )
        return environment

    def _request(
        self,
        method: str,
        path: str,
        *,
        expected_status: int = 200,
        **kwargs: Any,
    ) -> httpx.Response:
        route_key = f"{method.upper()} {path.split('?', 1)[0]}"
        self.request_counts[route_key] += 1
        response = self.client.request(method, path, **kwargs)
        if response.status_code != expected_status:
            raise AssertionError(
                f"{route_key} returned HTTP {response.status_code}; "
                f"safe response: {_safe_response(response)}"
            )
        return response

    @staticmethod
    def _assert_exact_identity(
        payload: dict[str, Any],
        *,
        project_id: str,
        dataset_id: str,
        dataset_version_id: str,
        activation_revision: int,
    ) -> None:
        assert payload["project_id"] == project_id
        assert payload["dataset_id"] == dataset_id
        assert payload["dataset_version_id"] == dataset_version_id
        assert int(payload["activation_revision"]) == activation_revision
        assert payload["link"]["project_id"] == project_id
        assert payload["link"]["dataset_id"] == dataset_id
        assert payload["active_selection"]["project_id"] == project_id
        assert payload["active_selection"]["dataset_id"] == dataset_id
        assert (
            payload["active_selection"]["dataset_version_id"]
            == dataset_version_id
        )

    def create_fixture(self) -> None:
        self._request(
            "POST",
            "/api/auth/register",
            json={
                "email": f"restart-soak-{uuid.uuid4().hex}@atlas-test.invalid",
                "displayName": "Isolated Restart Soak",
                "password": f"RestartSoak!{secrets.token_hex(12)}",
                "role": "data_scientist",
            },
        )
        project = self._request(
            "POST",
            "/api/projects",
            json={
                "projectName": "Isolated Project Context Restart Soak",
                "projectType": "predictive-modeling",
                "workflowType": "predictive-modeling",
            },
        ).json()["project"]
        project_id = str(project["projectId"])
        model_id = f"model-{project_id}"
        context = {
            "projectName": "Isolated Project Context Restart Soak",
            "modelId": model_id,
            "modelType": "generic classification",
            "modelTypeSelection": "Generic Binary Classification",
            "businessObjective": "Verify isolated restart continuity.",
            "intendedModelUse": "Synthetic pre-training acceptance only.",
            "targetDefinition": "bad_flag is the synthetic binary outcome.",
            "populationDefinition": "The disposable 120-row fixture population.",
            "observationWindow": "Synthetic fixed observation window.",
            "performanceWindow": "Synthetic fixed performance window.",
        }
        self._request(
            "PUT",
            f"/api/projects/{project_id}",
            json={
                "metadata": {
                    "modelId": model_id,
                    "projectContext": context,
                    "projectContextRevision": 1,
                    "projectContextSchemaVersion": 2,
                }
            },
        )
        upload = self._request(
            "POST",
            "/api/datasets/upload",
            files={
                "file": (
                    "isolated_restart_soak.csv",
                    _fixture_csv(),
                    "text/csv",
                )
            },
            data={
                "name": "Isolated Restart Soak Dataset",
                "description": "Disposable restart-resilience fixture",
            },
        ).json()["dataset"]
        dataset_id = str(upload["datasetId"])
        dataset_version_id = str(upload["created_dataset_version_id"])
        self._request(
            "POST",
            f"/api/projects/{project_id}/datasets/link",
            json={
                "datasetId": dataset_id,
                "versionId": dataset_version_id,
                "datasetRole": "modeling",
            },
        )
        activation = self._request(
            "POST",
            f"/api/datasets/{dataset_id}/versions/{dataset_version_id}/activate",
            params={"project_id": project_id},
        ).json()
        activation_revision = int(activation["activation_revision"])
        assert activation_revision > 0

        target_contract = self._request(
            "POST",
            "/api/data/set_target",
            json={
                "project_id": project_id,
                "target": "bad_flag",
                "selected_columns": ["predictor_a", "predictor_b"],
                "expected_dataset_id": dataset_id,
                "expected_dataset_version_id": dataset_version_id,
            },
        ).json()
        partition = self._request(
            "POST",
            "/api/analysis-partitions/confirm",
            json={
                "project_id": project_id,
                "dataset_id": dataset_id,
                "dataset_version_id": dataset_version_id,
                "target_contract_id": target_contract["target_contract_id"],
                "target": "bad_flag",
                "positive_value": 1,
                "negative_value": 0,
                "predictor_authorization_id": target_contract[
                    "predictor_authorization_id"
                ],
                "development_share": 0.8,
                "holdout_share": 0.2,
                "random_seed": 42,
                "stratification_policy": "target",
                "stratification_field": "bad_flag",
                "confirmation_acknowledged": True,
                "reset_existing": False,
                "reset_reason": "",
                "acknowledge_invalidation": False,
            },
        ).json()
        analysis_partition = partition["analysis_partition"]
        assert partition["readiness"] == "current"
        assert analysis_partition["final_holdout_status"] == "sealed"
        assert analysis_partition["holdout_isolation_status"] == "verified"

        self._request(
            "PUT",
            f"/api/projects/{project_id}/workflow-state",
            json={
                "currentStepId": "step02",
                "historicalCompletedSteps": ["step00", "step01"],
                "workflowStatus": {
                    "projectType": "predictive-modeling",
                    "datasetIdentity": {
                        "project_id": project_id,
                        "dataset_id": dataset_id,
                        "dataset_version_id": dataset_version_id,
                    },
                    "identityValidity": {
                        "status": "current",
                        "activationRevision": activation_revision,
                    },
                },
                "stepEvidenceStatus": {},
            },
        )
        self.identifiers = {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            "activation_revision": activation_revision,
            "target_contract_id": target_contract["target_contract_id"],
            "predictor_authorization_id": target_contract[
                "predictor_authorization_id"
            ],
            "analysis_partition_id": analysis_partition["analysis_partition_id"],
            "development_partition_id": analysis_partition[
                "development_partition_id"
            ],
        }

    def verify_continuity(self, label: str, pid: int) -> None:
        project_id = self.identifiers["project_id"]
        dataset_id = self.identifiers["dataset_id"]
        version_id = self.identifiers["dataset_version_id"]
        revision = int(self.identifiers["activation_revision"])

        health = self._request("GET", "/api/health").json()
        assert health.get("ok") is True

        project = self._request(
            "GET", f"/api/projects/{project_id}"
        ).json()["project"]
        assert project["projectId"] == project_id
        assert (
            project["metadata"]["projectContext"]["businessObjective"]
            == "Verify isolated restart continuity."
        )
        assert int(project["metadata"]["projectContextRevision"]) == 1
        assert len(project["links"]) == 1
        assert project["links"][0]["datasetId"] == dataset_id
        assert project["activeSelection"]["datasetVersionId"] == version_id
        assert int(project["activeSelection"]["activationRevision"]) == revision

        workflow = self._request(
            "GET", f"/api/projects/{project_id}/workflow-state"
        ).json()["workflowState"]
        assert workflow["projectId"] == project_id
        workflow_status = workflow["workflowStatus"]
        assert workflow_status["datasetIdentity"] == {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "activation_revision": 1,
        }
        assert int(
            workflow_status["identityValidity"]["activationRevision"]
        ) == revision

        identity = self._request(
            "GET",
            "/api/data/active-identity",
            params={"project_id": project_id},
        ).json()
        self._assert_exact_identity(
            identity,
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            activation_revision=revision,
        )

        overview = self._request(
            "POST",
            "/api/eda/workspace/overview",
            json={
                "project_id": project_id,
                "target": "bad_flag",
                "event_value": 1,
                "problem_type": "classification",
                "expected_dataset_id": dataset_id,
                "expected_dataset_version_id": version_id,
            },
        ).json()
        assert overview["ok"] is True
        assert overview.get("partial") is not True
        assert overview["project_id"] == project_id
        assert overview["dataset_id"] == dataset_id
        assert overview["dataset_version_id"] == version_id
        assert overview["target"] == "bad_flag"
        assert overview["scope"] == "development_population"
        assert overview["analysis_scope"]["decisionReady"] is True
        assert overview["analysis_scope"]["finalHoldoutAccessed"] is False
        assert (
            overview["analysis_scope"]["finalHoldoutUsedForSelection"] is False
        )
        assert overview["analysis_scope"]["populationRows"] == 96
        assert overview["analysis_scope"]["fullGovernedPopulationRows"] == 120

        self.continuity_records.append(
            {
                "label": label,
                "pid": pid,
                "health_status": 200,
                "project_status": 200,
                "workflow_status": 200,
                "active_identity_status": 200,
                "eda_overview_status": 200,
                "project_context_revision": 1,
                "activation_revision": revision,
                "eda_scope": overview["scope"],
                "development_rows": overview["analysis_scope"]["populationRows"],
                "final_holdout_accessed": False,
                "final_holdout_used_for_selection": False,
            }
        )

    def _write_result(self, *, status: str, error: str | None = None) -> None:
        forbidden_routes = [
            route
            for route in self.request_counts
            if any(
                token in route.casefold()
                for token in (
                    "/training",
                    "/evaluate",
                    "/evaluation",
                    "/interpretation",
                    "/scoring",
                    "/model-registry",
                )
            )
        ]
        payload = {
            "status": status,
            "runtime_seconds": round(time.time() - self.started_at, 3),
            "restart_cycles_required": RESTART_CYCLES,
            "restart_cycles_completed": len(self.restart_records),
            "continuity_passes": len(self.continuity_records),
            "continuity_endpoints_per_pass": CONTINUITY_ENDPOINTS,
            "continuity_http_200_checks": (
                len(self.continuity_records) * CONTINUITY_ENDPOINTS
            ),
            "identifiers": self.identifiers,
            "restart_records": self.restart_records,
            "continuity_records": self.continuity_records,
            "request_counts": dict(sorted(self.request_counts.items())),
            "forbidden_routes_called": forbidden_routes,
            "training_performed": False,
            "scoring_performed": False,
            "final_holdout_accessed": False,
            "live_heloc_authority_used": False,
            "mutable_runtime_root": str(self.runtime_root),
            "dataset_backup_root": str(self.backup_root),
            "backend_log": str(self.log_path),
            "error": error,
        }
        temporary = self.result_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(self.result_path)

    def run(self) -> None:
        current_pid: int | None = None
        failure: BaseException | None = None
        try:
            current_pid = self.backend.start()
            self.create_fixture()
            self.verify_continuity("baseline", current_pid)
            for cycle in range(1, RESTART_CYCLES + 1):
                old_pid = current_pid
                stop_result = self.backend.stop()
                assert stop_result["pid"] == old_pid
                assert stop_result["listener_stopped"] is True
                assert self.backend.process is None
                current_pid = self.backend.start()
                assert current_pid != old_pid
                assert self.backend.process is not None
                assert self.backend.process.poll() is None
                self.restart_records.append(
                    {
                        "cycle": cycle,
                        "old_pid": old_pid,
                        "old_exit_code": stop_result["exit_code"],
                        "old_listener_stopped": stop_result["listener_stopped"],
                        "forced_stop": stop_result.get("forced", False),
                        "new_pid": current_pid,
                        "new_listener_healthy": True,
                    }
                )
                self.verify_continuity(f"restart-{cycle}", current_pid)

            assert len(self.restart_records) == RESTART_CYCLES
            assert len(self.continuity_records) == RESTART_CYCLES + 1
            assert all(
                record["old_pid"] != record["new_pid"]
                for record in self.restart_records
            )
            assert not [
                route
                for route in self.request_counts
                if any(
                    token in route.casefold()
                    for token in (
                        "/training",
                        "/evaluate",
                        "/evaluation",
                        "/interpretation",
                        "/scoring",
                        "/model-registry",
                    )
                )
            ]
        except BaseException as exc:  # retain sanitized forensic evidence
            failure = exc
            raise
        finally:
            self.backend.stop()
            self.client.close()
            self._write_result(
                status="failed" if failure is not None else "passed",
                error=(
                    f"{type(failure).__name__}: {str(failure)[:800]}"
                    if failure is not None
                    else None
                ),
            )
            print(f"restart_soak_result={self.result_path}")
            print(f"restart_soak_backend_log={self.log_path}")


def test_project_context_authority_survives_ten_backend_restarts() -> None:
    RestartSoak().run()


if __name__ == "__main__":
    test_project_context_authority_survives_ten_backend_restarts()
