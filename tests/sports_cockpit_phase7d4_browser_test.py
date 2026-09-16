"""Phase 7D.4 Gate 16 (browser) — focused PA Modeling Cockpit acceptance, orchestrated in Python.

Reuses the proven scratch-backend + HTTP provisioning (Gate 16) to stand up a REAL, isolated cockpit stack, then
drives Chromium through the actual UI via the installed JS Playwright runner:

  build hermetic Gen-3 dataset (isolated runtime root)
  -> start a fresh scratch Uvicorn (isolated ATLAS + ASP_MODEL_STUDIO_RUNTIME_ROOT seam)
  -> provision real authenticated projects with real V2 active candidates over HTTP (register/project/bind/run/
     execute/activate); tamper one project's immutable evidence to force a failed-verification state
  -> start `vite dev` (mode modeling) proxying /api to the scratch backend
  -> run tests/e2e-cockpit/cockpit.spec.ts (login through the real UI -> the provisioned project cockpit).

Scientific API responses are never mocked; zero external provider calls; only processes this test starts are
terminated; the shared .runtime is never touched.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

from server.sports_cockpit import gen3_authority as A
from tests._hermetic_gen3 import build_hermetic_gen3

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
NPX = shutil.which("npx")
VITE_JS = REPO / "node_modules" / "vite" / "bin" / "vite.js"
CHROMIUM = list((Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright").glob("chromium-*")) if os.environ.get("LOCALAPPDATA") else []
_TOOLING = bool(NODE and NPX and VITE_JS.is_file() and (REPO / "node_modules" / "@playwright" / "test").is_dir() and CHROMIUM)

pytestmark = pytest.mark.skipif(not _TOOLING, reason="browser tooling (node/npx/vite/@playwright + chromium) not available")


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _backend_env(runtime_root: Path, backup_root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATLAS_")}
    for k in ("DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"):
        env.pop(k, None)
    r = runtime_root
    paths = {
        "ATLAS_SECURITY_ROOT": r / "security", "ATLAS_SECURITY_DB_PATH": r / "security" / "security.db",
        "ATLAS_SQLITE_PATH": r / "persistence" / "atlas.db", "ATLAS_CHECKPOINT_PATH": r / "checkpoint" / "workflow.json",
        "ATLAS_DATASET_LIBRARY_ROOT": r / "dataset-library", "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": backup_root,
        "ATLAS_EVIDENCE_ROOT": r / "evidence", "ATLAS_FEATURE_MANIFEST_ROOT": r / "feature-manifests",
        "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": r / "model-registry", "ATLAS_SCORING_RUN_ARTIFACT_ROOT": r / "scoring-runs",
        "ATLAS_VIF_PLAN_ROOT": r / "vif-plans", "ATLAS_PYTHON_RUNTIME_DIR": r / "python-runtime",
    }
    for name, p in paths.items():
        (p if name.endswith("_ROOT") or name.endswith("_DIR") else p.parent).mkdir(parents=True, exist_ok=True)
    (r / "temp").mkdir(parents=True, exist_ok=True)
    env.update({name: str(p) for name, p in paths.items()})
    env.update({
        "PYTHONPATH": str(REPO), "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(r),
        "ATLAS_ENV": "testing", "ATLAS_TEST_MODE": "1", "ATLAS_AUTH_ENABLED": "true",
        "ATLAS_ALLOW_PUBLIC_REGISTRATION": "true", "ATLAS_LOCAL_DEV": "false", "ATLAS_DEV_MODE": "false",
        "ATLAS_HOSTED_MODE": "false", "ATLAS_ENABLE_DEV_USER_HEADER": "false",
        "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "false", "ATLAS_DEV_AUTH_TOOLS": "false", "ATLAS_COOKIE_SECURE": "false",
        "ATLAS_ENABLE_PYTHON_RUN": "0", "ATLAS_SESSION_SECRET": secrets.token_hex(48),
        "ATLAS_DEFAULT_ADMIN_PASSWORD": f"Unused!{secrets.token_hex(24)}", "ATLAS_CHECKPOINT_DEBOUNCE_SECONDS": "0.1",
        "TEMP": str(r / "temp"), "TMP": str(r / "temp"),
    })
    return env


def _wait_http(url: str, timeout: float, proc: subprocess.Popen | None = None, expect=(200,)) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise AssertionError(f"process exited early rc={proc.returncode}")
        try:
            if httpx.get(url, timeout=2.0).status_code in expect:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise AssertionError(f"timed out waiting for {url}")


def _register(base: str, email: str, password: str) -> httpx.Client:
    c = httpx.Client(base_url=base, timeout=120.0)
    r = c.post("/api/auth/register", json={"email": email, "displayName": "Gate16 Browser",
                                           "password": password, "role": "data_scientist"})
    assert r.status_code == 200, r.text
    return c


def _new_project(c: httpx.Client) -> str:
    p = c.post("/api/projects", json={"projectName": "Cockpit Browser Project", "projectType": "predictive-modeling",
                                      "workflowType": "predictive-modeling"})
    assert p.status_code == 200, p.text
    return str(p.json()["project"]["projectId"])


def _provision_active_candidate(c: httpx.Client, project_id: str, gen3_id: str) -> str:
    b = c.post("/api/cockpit/gen3/bind", json={"projectId": project_id, "datasetVersionId": gen3_id})
    assert b.status_code == 200, b.text
    binding_id, revision = b.json()["bindingId"], b.json()["revision"]
    au = c.post("/api/cockpit/gen3/run-authority", json={"projectId": project_id, "bindingId": binding_id,
                "modelFamily": "governed_hgb", "hyperparameters": {"maxIter": 15}, "featureSet": "base"})
    assert au.status_code == 200, au.text
    ex = c.post("/api/cockpit/gen3/execute", json={"projectId": project_id, "runAuthorityId": au.json()["runAuthorityId"]})
    assert ex.status_code == 200, ex.text
    run_id = ex.json()["experimentRunId"]
    act = c.post("/api/cockpit/gen3/activate", json={"projectId": project_id, "runId": run_id,
                                                     "expectedBindingRevision": revision})
    assert act.status_code == 200, act.text
    return run_id


def test_cockpit_browser_acceptance(tmp_path):
    runtime_root = tmp_path / "runtime"
    backup_root = tmp_path / "backup"; backup_root.mkdir(parents=True, exist_ok=True)
    # publish the hermetic Gen-3 dataset into the env-seam runtime root (physical files the backend will resolve)
    import _pytest.monkeypatch
    mp = _pytest.monkeypatch.MonkeyPatch()
    try:
        build_hermetic_gen3(runtime_root, mp)
        gen3_id = {c["generation"]: c["datasetVersionId"] for c in A.catalog()}["GEN3"]

        backend_port = _port(); frontend_port = _port()
        base = f"http://127.0.0.1:{backend_port}"
        logs = (runtime_root / "logs"); logs.mkdir(parents=True, exist_ok=True)
        be_log = (logs / "backend.log").open("ab")
        fe_log = (logs / "frontend.log").open("ab")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(backend_port),
             "--log-level", "warning", "--no-access-log"],
            cwd=str(REPO), env=_backend_env(runtime_root, backup_root), stdout=be_log, stderr=subprocess.STDOUT,
            creationflags=flags)
        frontend = None
        try:
            _wait_http(f"{base}/api/health", 60.0, backend)

            # provision real isolated scientific state over HTTP
            email1 = f"primary-{uuid.uuid4().hex}@asp-test.invalid"; pw1 = f"Gate16!{secrets.token_hex(12)}"
            c1 = _register(base, email1, pw1)
            valid_pid = _new_project(c1); _provision_active_candidate(c1, valid_pid, gen3_id)
            fail_pid = _new_project(c1); fail_run = _provision_active_candidate(c1, fail_pid, gen3_id)
            email2 = f"secondary-{uuid.uuid4().hex}@asp-test.invalid"; pw2 = f"Gate16!{secrets.token_hex(12)}"
            _register(base, email2, pw2)   # a second authenticated user who owns NOTHING

            # tamper the fail project's immutable evidence -> its active-candidate read fails verification (422)
            v = A.verify_model_run_receipt(project_id=fail_pid, run_id=fail_run)
            (v["bundleDir"] / "aggregate-metrics.json").write_bytes(b'{"tampered": true}')

            fe_base = f"http://127.0.0.1:{frontend_port}"
            fixture = runtime_root / "cockpit_fixture.json"
            fixture.write_text(json.dumps({
                "baseURL": fe_base,
                "primary": {"email": email1, "password": pw1},
                "secondary": {"email": email2, "password": pw2},
                "validProjectId": valid_pid,            # owned by primary; secondary hitting it -> 403
                "unauthorizedProjectId": valid_pid,
                "failedProjectId": fail_pid,            # tampered evidence -> 422 verification-failed
            }), encoding="utf-8")

            # start vite dev proxying /api to the scratch backend
            fe_env = {**os.environ, "VITE_API_PROXY_TARGET": base,
                      "ASP_MODEL_STUDIO_FRONTEND_PORT": str(frontend_port), "PLAYWRIGHT_BROWSERS_PATH": "0"}
            frontend = subprocess.Popen(
                [NODE, str(VITE_JS), "--mode", "modeling", "--host", "127.0.0.1", "--port", str(frontend_port), "--strictPort"],
                cwd=str(REPO), env=fe_env, stdout=fe_log, stderr=subprocess.STDOUT, creationflags=flags)
            _wait_http(f"{fe_base}/", 120.0, frontend, expect=(200,))

            # run the JS Playwright acceptance against the live scratch stack
            r = subprocess.run(
                [NPX, "playwright", "test", "--config", "tests/e2e-cockpit/playwright.config.ts", "--project", "chromium"],
                cwd=str(REPO), env={**os.environ, "COCKPIT_E2E_BASE_URL": fe_base, "COCKPIT_FIXTURE": str(fixture)},
                capture_output=True, text=True, timeout=600)
            assert r.returncode == 0, f"playwright failed:\n{r.stdout[-6000:]}\n{r.stderr[-2000:]}"
        finally:
            for proc in (frontend, backend):
                if proc is not None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=20)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            be_log.close(); fe_log.close()
    finally:
        mp.undo()
