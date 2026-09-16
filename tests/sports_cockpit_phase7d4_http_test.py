"""Phase 7D.4 Gate 16 — authenticated HTTP scratch-server acceptance.

Starts a FRESH Uvicorn process on 127.0.0.1:<scratch port> with isolated temporary ATLAS + cockpit runtime roots
(the ASP_MODEL_STUDIO_RUNTIME_ROOT env seam points the cockpit at a hermetic Gen-3 dataset published there), creates
a temporary authorized user through the REAL /api/auth/register route, owns a project, and drives the repaired
cockpit paths over ACTUAL authenticated HTTP: catalog -> bind -> run-authority -> execute -> activate ->
active-candidate -> evaluation -> calibration -> registry-evidence -> feature-family-comparison. It asserts every
verified response validates against its strict V2 DTO, stale/failed verification is explicit, unauthorized requests
fail, no route exposes 2025, and no malformed payload can be served as a nominal V2 success. No external calls; only
the process this test starts is terminated.
"""
from __future__ import annotations

import os
import secrets
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

from server.sports_cockpit.cockpit_dtos import (
    ActiveCandidateResponseV2, FeatureFamilyComparisonResponseV2, ModelCalibrationResponseV2,
    ModelEvaluationResponseV2, ModelRegistryEvidenceResponseV2,
)
from tests._hermetic_gen3 import ADVANCED_FEATURE, build_hermetic_gen3

REPO = Path(__file__).resolve().parents[1]
STARTUP_TIMEOUT = 60.0


def _port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _no_2025_except_label(payload: dict) -> None:
    import json
    scrubbed = {k: v for k, v in payload.items() if k != "validationLabel"}
    assert "2025" not in json.dumps(scrubbed), f"2025 leaked into a response: {scrubbed}"


class _Backend:
    def __init__(self, runtime_root: Path, backup_root: Path):
        self.runtime_root = runtime_root
        self.backup_root = backup_root
        self.port = _port()
        self.proc: subprocess.Popen | None = None
        self.log = (runtime_root / "backend.log").open("ab")

    def _env(self) -> dict:
        env = os.environ.copy()
        for k in list(env):
            if k.startswith("ATLAS_"):
                env.pop(k, None)
        for k in ("DATABASE_URL", "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD"):
            env.pop(k, None)
        r = self.runtime_root
        temp = r / "temp"
        paths = {
            "ATLAS_SECURITY_ROOT": r / "security", "ATLAS_SECURITY_DB_PATH": r / "security" / "security.db",
            "ATLAS_SQLITE_PATH": r / "persistence" / "atlas.db", "ATLAS_CHECKPOINT_PATH": r / "checkpoint" / "workflow.json",
            "ATLAS_DATASET_LIBRARY_ROOT": r / "dataset-library", "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": self.backup_root,
            "ATLAS_EVIDENCE_ROOT": r / "evidence", "ATLAS_FEATURE_MANIFEST_ROOT": r / "feature-manifests",
            "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": r / "model-registry", "ATLAS_SCORING_RUN_ARTIFACT_ROOT": r / "scoring-runs",
            "ATLAS_VIF_PLAN_ROOT": r / "vif-plans", "ATLAS_PYTHON_RUNTIME_DIR": r / "python-runtime",
        }
        for name, p in paths.items():
            (p if name.endswith("_ROOT") or name.endswith("_DIR") else p.parent).mkdir(parents=True, exist_ok=True)
        temp.mkdir(parents=True, exist_ok=True)
        env.update({name: str(p) for name, p in paths.items()})
        env.update({
            "PYTHONPATH": str(REPO), "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(r),                 # the cockpit env seam -> hermetic dataset
            "ATLAS_ENV": "testing", "ATLAS_TEST_MODE": "1", "ATLAS_AUTH_ENABLED": "true",
            "ATLAS_ALLOW_PUBLIC_REGISTRATION": "true", "ATLAS_LOCAL_DEV": "false", "ATLAS_DEV_MODE": "false",
            "ATLAS_HOSTED_MODE": "false", "ATLAS_ENABLE_DEV_USER_HEADER": "false",
            "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "false", "ATLAS_DEV_AUTH_TOOLS": "false",
            "ATLAS_COOKIE_SECURE": "false", "ATLAS_ENABLE_PYTHON_RUN": "0", "ATLAS_SESSION_SECRET": secrets.token_hex(48),
            "ATLAS_DEFAULT_ADMIN_PASSWORD": f"Unused!{secrets.token_hex(24)}", "ATLAS_CHECKPOINT_DEBOUNCE_SECONDS": "0.1",
            "TEMP": str(temp), "TMP": str(temp),
        })
        return env

    def start(self) -> None:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(self.port),
             "--log-level", "warning", "--no-access-log"],
            cwd=str(REPO), env=self._env(), stdout=self.log, stderr=subprocess.STDOUT, creationflags=flags)
        deadline = time.monotonic() + STARTUP_TIMEOUT
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise AssertionError(f"backend exited during startup rc={self.proc.returncode}")
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/api/health", timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise AssertionError("backend did not become healthy in time")

    def stop(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        try:
            self.log.close()
        except Exception:
            pass


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    backup_root = tmp_path / "backup"                       # OUTSIDE the runtime + dataset-library roots
    backup_root.mkdir(parents=True, exist_ok=True)
    build_hermetic_gen3(runtime_root, monkeypatch)          # publish the hermetic Gen-3 dataset into the env-seam root
    be = _Backend(runtime_root, backup_root)
    be.start()
    try:
        yield be
    finally:
        be.stop()


def _client(be: _Backend) -> httpx.Client:
    return httpx.Client(base_url=f"http://127.0.0.1:{be.port}", timeout=120.0)


def test_authenticated_http_cockpit_flow_through_the_v2_chain(backend):
    with _client(backend) as c:
        # real login: register (public registration enabled) -> session cookie is captured in the client jar
        reg = c.post("/api/auth/register", json={"email": f"gate16-{uuid.uuid4().hex}@asp-test.invalid",
                                                  "displayName": "Gate16", "password": f"Gate16!{secrets.token_hex(12)}",
                                                  "role": "data_scientist"})
        assert reg.status_code == 200, reg.text
        pid = str(c.post("/api/projects", json={"projectName": "Gate16 Project", "projectType": "predictive-modeling",
                                                "workflowType": "predictive-modeling"}).json()["project"]["projectId"])

        # before activation the active-candidate read is an explicit 404 (no candidate), not a fake success
        assert c.get(f"/api/cockpit/gen3/active-candidate/{pid}").status_code == 404

        cat = c.get("/api/cockpit/gen3/catalog"); assert cat.status_code == 200
        entries = {e["generation"]: e for e in cat.json()["datasets"]}
        gen3_id = entries["GEN3"]["datasetVersionId"]

        b = c.post("/api/cockpit/gen3/bind", json={"projectId": pid, "datasetVersionId": gen3_id})
        assert b.status_code == 200, b.text
        binding_id, revision = b.json()["bindingId"], b.json()["revision"]

        au = c.post("/api/cockpit/gen3/run-authority", json={"projectId": pid, "bindingId": binding_id,
                    "modelFamily": "governed_hgb", "hyperparameters": {"maxIter": 15}, "featureSet": "advanced"})
        assert au.status_code == 200, au.text
        ex = c.post("/api/cockpit/gen3/execute", json={"projectId": pid, "runAuthorityId": au.json()["runAuthorityId"]})
        assert ex.status_code == 200, ex.text
        run_id = ex.json()["experimentRunId"]

        # activation of an UNKNOWN run (missing immutable evidence) fails closed over HTTP
        assert c.post("/api/cockpit/gen3/activate", json={"projectId": pid, "runId": "0" * 32}).status_code == 422

        act = c.post("/api/cockpit/gen3/activate", json={"projectId": pid, "runId": run_id,
                                                         "expectedBindingRevision": revision})
        assert act.status_code == 200, act.text

        # each verified read validates against its strict V2 DTO, carries immutable V2 identities, and hides 2025
        ac = c.get(f"/api/cockpit/gen3/active-candidate/{pid}"); assert ac.status_code == 200
        acm = ActiveCandidateResponseV2.model_validate(ac.json())
        assert acm.runId == run_id and acm.runReceiptSha256 and acm.bundleManifestSha256
        _no_2025_except_label(ac.json())

        ev = c.get(f"/api/cockpit/gen3/evaluation/{pid}"); assert ev.status_code == 200
        evm = ModelEvaluationResponseV2.model_validate(ev.json())
        assert evm.recomputationMatchesStored and evm.featureCount >= 23
        import json as _json
        assert "2025" not in _json.dumps(evm.metrics.model_dump())

        cal = c.get(f"/api/cockpit/gen3/calibration/{pid}"); assert cal.status_code == 200
        calm = ModelCalibrationResponseV2.model_validate(cal.json())
        assert calm.calibrationStatus == "RAW_UNCALIBRATED" and calm.calibratorConfigured is False

        rge = c.get(f"/api/cockpit/gen3/registry-evidence/{pid}"); assert rge.status_code == 200
        rgm = ModelRegistryEvidenceResponseV2.model_validate(rge.json())
        assert rgm.modelSha256 and rgm.predictionSha256 and rgm.runReceiptSha256 == acm.runReceiptSha256
        _no_2025_except_label(rge.json())

        cmp = c.post("/api/cockpit/gen3/feature-family-ablation", json={"projectId": pid, "bindingId": binding_id,
                     "modelFamily": "governed_hgb", "controlFeatureSet": "base", "challengerFeatureSet": "advanced",
                     "hyperparameters": {"maxIter": 15}, "bootstrapIterations": 150})
        assert cmp.status_code == 200, cmp.text
        cmpm = FeatureFamilyComparisonResponseV2.model_validate(cmp.json())
        assert cmpm.featureFamilyAdded == [ADVANCED_FEATURE] and cmpm.control.runReceiptSha256

        # stale authority: rebinding to another dataset makes the active candidate STALE -> explicit 404
        gen2_id = entries["GEN2"]["datasetVersionId"]
        assert c.post("/api/cockpit/gen3/bind", json={"projectId": pid, "datasetVersionId": gen2_id}).status_code == 200
        assert c.get(f"/api/cockpit/gen3/active-candidate/{pid}").status_code == 404

    # unauthorized (no session cookie) is refused
    with _client(backend) as anon:
        assert anon.get(f"/api/cockpit/gen3/active-candidate/{pid}").status_code in (401, 403)
