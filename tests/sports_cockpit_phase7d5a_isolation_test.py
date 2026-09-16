"""Phase 7D.5A (Workstream E) — the isolation infrastructure itself, under test.

Proves from committed code (no reliance on a pre-existing .runtime) that:

* the engine runtime-root resolver fails closed under ``ASP_REQUIRE_ISOLATED_RUNTIME=1`` unless an explicit
  throwaway override is given, and refuses to resolve back to the shared development ``.runtime``;
* the committed governed seeder refuses to seed into a missing / relative / repo-internal / ``.runtime``-overlapping
  root; and
* seeding a fresh throwaway root through the PRODUCTION publisher yields a registry the seam-resolved engine can
  actually resolve (a Gen-3 v2 authority + the synthetic-seed marker), reproducibly, without copying ``.runtime``.

The end-to-end seed+resolve step runs in a SUBPROCESS so the engine's import-time seam binds to the throwaway root.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from server.sports_cockpit import engine as E
from tests import _governed_runtime_seed as SEED

REPO = Path(__file__).resolve().parents[1]
REAL_RUNTIME = REPO / ".runtime" / "asp-model-studio"


# ------------------------------------------------------------------ isolation guard (engine resolver)
def test_guard_requires_explicit_override(monkeypatch):
    monkeypatch.setenv("ASP_REQUIRE_ISOLATED_RUNTIME", "1")
    monkeypatch.delenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", raising=False)
    with pytest.raises(ValueError):
        E._resolve_runtime_root()                     # no override -> refuse the shared-default fallback


def test_guard_refuses_resolving_back_to_shared_runtime(monkeypatch):
    monkeypatch.setenv("ASP_REQUIRE_ISOLATED_RUNTIME", "1")
    monkeypatch.setenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", str(REAL_RUNTIME))
    with pytest.raises(ValueError):
        E._resolve_runtime_root()                     # override == shared .runtime -> refused


def test_guard_allows_explicit_throwaway_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ASP_REQUIRE_ISOLATED_RUNTIME", "1")
    monkeypatch.setenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", str(tmp_path))
    assert E._resolve_runtime_root() == tmp_path.resolve()


def test_relative_override_is_rejected(monkeypatch):
    monkeypatch.delenv("ASP_REQUIRE_ISOLATED_RUNTIME", raising=False)
    monkeypatch.setenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", "relative/path")
    with pytest.raises(ValueError):
        E._resolve_runtime_root()


# ------------------------------------------------------------------ seeder fail-closed refusals
def test_seeder_refuses_without_root(monkeypatch):
    monkeypatch.delenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", raising=False)
    with pytest.raises(SystemExit) as ei:
        SEED.main()
    assert ei.value.code == 2


def test_seeder_refuses_relative_root(monkeypatch):
    monkeypatch.setenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", "relative/root")
    with pytest.raises(SystemExit) as ei:
        SEED.main()
    assert ei.value.code == 2


def test_seeder_refuses_shared_runtime(monkeypatch):
    monkeypatch.setenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", str(REAL_RUNTIME))
    with pytest.raises(SystemExit) as ei:
        SEED.main()
    assert ei.value.code == 2


def test_seeder_refuses_repo_internal_root(monkeypatch):
    monkeypatch.setenv("ASP_MODEL_STUDIO_RUNTIME_ROOT", str(REPO / "some" / "inside"))
    with pytest.raises(SystemExit) as ei:
        SEED.main()
    assert ei.value.code == 2


# ------------------------------------------------------------------ end-to-end: seed then resolve, in isolation
def _run(args, root):
    env = {**os.environ, "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(root), "ASP_REQUIRE_ISOLATED_RUNTIME": "1",
           "PYTHONPATH": str(REPO), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, *args], cwd=str(REPO), env=env, capture_output=True, text=True)


def test_seed_then_resolve_reproducibly_from_empty_root(tmp_path):
    root = tmp_path / "iso-runtime"                    # a fresh EMPTY throwaway root, nothing copied in
    seed = _run(["-m", "tests._governed_runtime_seed"], root)
    assert seed.returncode == 0, seed.stdout + seed.stderr
    assert (root / ".governed-synthetic-seed").is_file()
    assert (root / "sports-modeling" / "mlb-pa-gen3-v2" / "registration.json").is_file()
    inv = json.loads((root / "seed-inventory.json").read_text(encoding="utf-8"))
    assert inv["schema"] == "GOVERNED_SYNTHETIC_SEED_V1" and "gen3_publish.publish_object" in inv["publisher"]

    # the seam-resolved engine can actually resolve a Gen-3 authority from the freshly seeded registry
    probe = _run(["-c", "from server.sports_cockpit import gen3_authority as A; "
                        "print(sorted(c['generation'] for c in A.catalog()))"], root)
    assert probe.returncode == 0, probe.stdout + probe.stderr
    assert "GEN3" in probe.stdout and "GEN2" in probe.stdout
