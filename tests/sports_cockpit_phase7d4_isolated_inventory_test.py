"""Phase 7D.4 Gate 15 — the governed inventory runs against ISOLATED temporary roots and never mutates the
shared development .runtime.

The runtime roots are injectable two ways without weakening production containment: the four-attribute
monkeypatch (in-process) and the ASP_MODEL_STUDIO_RUNTIME_ROOT env seam (subprocess). This battery runs the full
governed pipeline (publish -> register -> bind -> run both families -> V2 evidence -> activate -> evaluate ->
calibrate -> registry-evidence -> comparison) under isolated roots, runs a representative governed test file under
the env seam, and asserts in every case that the canonical .runtime registry is byte-for-byte unchanged and that
no isolated project state leaked into the shared .runtime.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from server.sports_cockpit import gen3_authority as A
from tests._hermetic_gen3 import ADVANCED_FEATURE, build_hermetic_gen3

REPO = Path(__file__).resolve().parents[1]
# Captured at import (before any monkeypatch), these are the REAL shared .runtime paths.
REAL_REGISTRY = Path(A.ASP_REGISTRY)
REAL_STATE = Path(A.STATE_ROOT)


def _registry_fingerprint() -> str | None:
    return hashlib.sha256(REAL_REGISTRY.read_bytes()).hexdigest() if REAL_REGISTRY.is_file() else None


def _no_leaked_projects(project_ids: list[str]) -> None:
    for pid in project_ids:
        key = hashlib.sha256(pid.encode("utf-8")).hexdigest()[:32]
        assert not (REAL_STATE / key).exists(), f"isolated project {pid} leaked into the shared .runtime"


def _env(tmp: Path) -> dict:
    return {**os.environ, "PYTHONPATH": str(REPO), "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(tmp)}


# ---------------- 1. full inventory in isolated (monkeypatched) roots ----------------
def test_full_governed_inventory_isolated_leaves_runtime_untouched(tmp_path, monkeypatch):
    before = _registry_fingerprint()
    h = build_hermetic_gen3(tmp_path, monkeypatch)
    proj = "iso-inventory"
    b = A.create_binding(actor="t@asp", project_id=proj, dataset_version_id=h["researchId"])
    for fs in ("base", "advanced"):
        au = A.issue_run_authority(actor="t@asp", project_id=proj, binding_id=b["bindingId"],
                                   model_family="governed_hgb", hyperparameters={"maxIter": 15}, feature_set=fs)
        ev = A.execute(actor="t@asp", project_id=proj, run_authority_id=au["runAuthorityId"])
        adv_run = ev["experimentRunId"] if fs == "advanced" else None
    A.activate_candidate(actor="t@asp", project_id=proj, run_id=adv_run, expected_binding_revision=b["revision"])
    assert A.get_active_candidate(project_id=proj)["runId"] == adv_run
    assert A.active_candidate_evaluation(project_id=proj)["recomputationMatchesStored"]
    assert A.active_candidate_calibration(project_id=proj)["calibrationStatus"] == "RAW_UNCALIBRATED"
    assert A.active_candidate_registry_evidence(project_id=proj)["modelSha256"]
    comp = A.run_feature_family_ablation(actor="t@asp", project_id=proj, binding_id=b["bindingId"],
                                         model_family="governed_hgb", control_feature_set="base",
                                         challenger_feature_set="advanced", hyperparameters={"maxIter": 15},
                                         bootstrap_iterations=150)
    assert comp["featureFamilyAdded"] == [ADVANCED_FEATURE]

    # writes landed in the isolated temp root (positive), and the shared .runtime is untouched
    assert (tmp_path / "artifacts" / "datasets" / "registry.json").is_file()
    assert list((tmp_path / "sports-modeling" / "mlb-pa-gen3-v2" / "authority").iterdir())
    assert _registry_fingerprint() == before          # canonical .runtime registry byte-identical
    _no_leaked_projects([proj])


# ---------------- 2. isolated inventory via the env seam (subprocess) ----------------
def test_isolated_inventory_via_env_seam_subprocess_leaves_runtime_untouched(tmp_path, monkeypatch):
    before = _registry_fingerprint()
    h = build_hermetic_gen3(tmp_path, monkeypatch)    # physical objects under tmp_path (== env-seam layout)
    proj = "iso-env-subproc"
    r = subprocess.run([sys.executable, "-m", "tests._interprocess_worker", "execute", proj, h["researchId"]],
                       cwd=str(REPO), env=_env(tmp_path), capture_output=True, text=True, timeout=90)
    assert r.stdout.strip().startswith("RUN "), r.stdout + r.stderr    # the subprocess ran against tmp roots
    assert _registry_fingerprint() == before          # shared .runtime registry byte-identical
    _no_leaked_projects([proj])


# ---------------- 3. a representative governed test FILE under isolated roots ----------------
def test_representative_governed_file_runs_under_isolated_roots(tmp_path):
    before = _registry_fingerprint()
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/sports_cockpit_phase7d4_production_chain_test.py", "-q",
         "-p", "no:cacheprovider", "-o", f"cache_dir={tmp_path / 'pcache'}"],
        cwd=str(REPO), env=_env(tmp_path / "runtime"), capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"isolated governed file failed:\n{r.stdout[-3000:]}\n{r.stderr[-1500:]}"
    assert _registry_fingerprint() == before          # even a full governed file run leaves .runtime untouched
