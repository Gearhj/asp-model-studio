"""Canonical ATLAS security release gate.

Behavioral suites are reported separately from structural source checks.
Required files must be present and wired, and skipped required tests fail the
gate.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "tests" / "security_test_inventory.json"
CHECKED_IN_MUTABLE_ROOTS = tuple(
    path.resolve()
    for path in (
        ROOT / ".runtime",
        ROOT / "server" / "data",
        ROOT / "server" / "artifacts" / "datasets",
        ROOT / "server" / "artifacts" / "security",
        ROOT / "server" / "artifacts" / "evidence",
        ROOT / "server" / "artifacts" / "model_registry",
        ROOT / "server" / "artifacts" / "scoring_runs",
    )
)


def isolated_environment(runtime_root: Path) -> dict[str, str]:
    """Return a complete mutable-runtime envelope for one subprocess.

    Several security suites import ``server.main``. Supplying only their
    primary SQLite file leaves cached dataset/checkpoint/artifact modules free
    to bind to the developer runtime. Set every mutable root before process
    creation so import order cannot make a release-gate test write there.
    """
    runtime_root = runtime_root.resolve()
    paths = {
        "ATLAS_SECURITY_ROOT": runtime_root / "security",
        "ATLAS_SECURITY_DB_PATH": runtime_root / "security" / "atlas_security.db",
        "ATLAS_SQLITE_PATH": runtime_root / "persistence" / "atlas_local.db",
        "ATLAS_CHECKPOINT_PATH": runtime_root / "checkpoint" / "workflow_checkpoint.json",
        "ATLAS_DATASET_LIBRARY_ROOT": runtime_root / "dataset-library",
        "ATLAS_EVIDENCE_ROOT": runtime_root / "evidence",
        "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": runtime_root / "model-registry",
        "ATLAS_SCORING_RUN_ARTIFACT_ROOT": runtime_root / "scoring-runs",
    }
    for label, path in paths.items():
        resolved = path.resolve()
        if resolved != runtime_root and runtime_root not in resolved.parents:
            raise RuntimeError(f"{label} escaped the security gate temporary root: {resolved}")
        for forbidden in CHECKED_IN_MUTABLE_ROOTS:
            if resolved == forbidden or forbidden in resolved.parents:
                raise RuntimeError(f"{label} targets checked-in runtime state: {resolved}")

    for variable, path in paths.items():
        if variable.endswith("_ROOT"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({name: str(path) for name, path in paths.items()})
    return environment


def python_executable() -> str:
    configured = os.getenv("ATLAS_PYTHON")
    if configured:
        return configured
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / ".venv" / "bin" / "python",
    ]
    return str(next((candidate for candidate in candidates if candidate.exists()), Path(sys.executable)))


def load_inventory() -> dict:
    with INVENTORY_PATH.open(encoding="utf-8") as handle:
        inventory = json.load(handle)
    wired = {
        entry["path"]
        for category in ("behavioral", "structural")
        for entry in inventory.get(category, [])
    }
    missing = [path for path in inventory.get("requiredFiles", []) if not (ROOT / path).is_file()]
    unwired = [path for path in inventory.get("requiredFiles", []) if path not in wired]
    if missing or unwired:
        if missing:
            print("Missing required security tests:", ", ".join(missing), file=sys.stderr)
        if unwired:
            print("Unwired required security tests:", ", ".join(unwired), file=sys.stderr)
        raise SystemExit(2)
    return inventory


def run_entry(kind: str, entry: dict, gate_root: Path) -> None:
    path = entry["path"]
    runner = entry.get("runner", "python")
    command = [python_executable(), path] if runner == "python" else [runner, path]
    suite_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", path).strip("-")
    environment = isolated_environment(gate_root / suite_name)
    print(f"\n[{kind}] {path}: {entry['description']}", flush=True)
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=environment,
    )
    print(result.stdout, end="")
    if re.search(r"\bskipped(?:\s*=|\s+\()", result.stdout, flags=re.IGNORECASE):
        print(f"Required security suite reported skipped tests: {path}", file=sys.stderr)
        raise SystemExit(3)
    if result.returncode:
        raise SystemExit(result.returncode)


def main() -> None:
    inventory = load_inventory()
    behavioral = inventory["behavioral"]
    structural = inventory["structural"]
    print(
        f"ATLAS security inventory: {len(behavioral)} behavioral suites, "
        f"{len(structural)} structural suite."
    )
    temp_parent = ROOT / ".tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    gate_root = (
        temp_parent / f"atlas_security_gate_{uuid.uuid4().hex}"
    ).resolve()
    gate_root.mkdir(parents=True, exist_ok=True)
    try:
        for entry in behavioral:
            run_entry("behavioral", entry, gate_root)
        for entry in structural:
            run_entry("structural security check", entry, gate_root)
    finally:
        shutil.rmtree(gate_root, ignore_errors=True)
    print(
        f"\nATLAS security gate passed: {len(behavioral)} behavioral suites and "
        f"{len(structural)} structural suite."
    )


if __name__ == "__main__":
    main()
