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
import sys
import tempfile
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
        ROOT / "server" / "artifacts" / "feature_manifests",
        ROOT / "server" / "artifacts" / "model_registry",
        ROOT / "server" / "artifacts" / "scoring_runs",
    )
)
SECURITY_ENTRY_TIMEOUT_SECONDS = 180.0


def _stop_owned_process_tree(process: subprocess.Popen[str]) -> None:
    """Stop only the timed-out security-suite process and its descendants."""

    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=30,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


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
        "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": runtime_root / "dataset-backups",
        "ATLAS_BUREAU_CATALOG_REGISTRY_ROOT": runtime_root / "bureau-catalog-registry",
        "ATLAS_RESTRICTED_METADATA_ROOT": runtime_root / "restricted-bureau-metadata",
        "ATLAS_ISOLATED_CATALOG_INSTALL_JOURNAL_ROOT": runtime_root / "catalog-install-journal",
        "ATLAS_EVIDENCE_ROOT": runtime_root / "evidence",
        "ATLAS_FEATURE_MANIFEST_ROOT": runtime_root / "feature-manifests",
        "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": runtime_root / "model-registry",
        "ATLAS_SCORING_RUN_ARTIFACT_ROOT": runtime_root / "scoring-runs",
        "ATLAS_VIF_PLAN_ROOT": runtime_root / "vif-plans",
        "ATLAS_PYTHON_RUNTIME_DIR": runtime_root / "python-runtime",
        "ATLAS_SAS_CONFIG_DIR": runtime_root / "sas-config",
        "ATLAS_BROWSER_STORAGE_ROOT": runtime_root / "browser-storage",
        "ATLAS_PLAYWRIGHT_OUTPUT_ROOT": runtime_root / "playwright-output",
    }
    for label, path in paths.items():
        resolved = path.resolve()
        if resolved != runtime_root and runtime_root not in resolved.parents:
            raise RuntimeError(f"{label} escaped the security gate temporary root: {resolved}")
        for forbidden in CHECKED_IN_MUTABLE_ROOTS:
            if (
                resolved == forbidden
                or forbidden in resolved.parents
                or resolved in forbidden.parents
            ):
                raise RuntimeError(f"{label} targets checked-in runtime state: {resolved}")

    for variable, path in paths.items():
        if variable.endswith("_ROOT"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
    inherited_keys = {
        "ALLUSERSPROFILE",
        "COMSPEC",
        "NUMBER_OF_PROCESSORS",
        "OS",
        "PATH",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "WINDIR",
        "PYTHONPATH",
        "ATLAS_HERMETIC_MODE",
        "ATLAS_HERMETIC_ROOT",
        "ATLAS_HERMETIC_SOURCE_ROOT",
        "ATLAS_LIVE_REPOSITORY_ROOT",
        "ATLAS_LIVE_DATASET_LIBRARY_BACKUP_ROOT",
        "ATLAS_RUN_ID",
        "ATLAS_TEST_BACKEND_URL",
    }
    environment = {
        name: value for name, value in os.environ.items() if name.upper() in inherited_keys
    }
    environment.update({name: str(path) for name, path in paths.items()})
    environment.update(
        {
            "ATLAS_TEST_MODE": "1",
            "ATLAS_ENV": "testing",
            "ATLAS_PROCESS_ROLE": "test",
            "ATLAS_HERMETIC_GUARD_PASSED": "0",
            "ATLAS_SESSION_SECRET": uuid.uuid4().hex + uuid.uuid4().hex,
            "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "0",
            "ATLAS_ALLOW_PUBLIC_REGISTRATION": "0",
            "ATLAS_LOCAL_DEV": "0",
            "ATLAS_HOSTED_MODE": "0",
            "ATLAS_AUTH_ENABLED": "0",
            "TEMP": str(runtime_root / "process-temp"),
            "TMP": str(runtime_root / "process-temp"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(runtime_root / "pycache"),
        }
    )
    for directory in (
        runtime_root / "process-temp",
        runtime_root / "pycache",
    ):
        directory.mkdir(parents=True, exist_ok=True)
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
    environment["ATLAS_TEST_NAME"] = suite_name
    print(f"\n[{kind}] {path}: {entry['description']}", flush=True)
    log_path = gate_root / f"{suite_name}.log"
    timeout_seconds = float(entry.get("timeoutSeconds", SECURITY_ENTRY_TIMEOUT_SECONDS))
    if timeout_seconds <= 0 or timeout_seconds > SECURITY_ENTRY_TIMEOUT_SECONDS:
        raise SystemExit(2)
    timed_out = False
    return_code = 1
    with log_path.open("x", encoding="utf-8", newline="\n") as output:
        # Ensure a timeout always leaves a durable, non-empty diagnostic even
        # when Windows process startup stalls before the child can emit its
        # first line. Child output is appended to the same bounded log.
        output.write(f"ATLAS security entry started: kind={kind}\n")
        output.flush()
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            text=True,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=environment,
        )
        try:
            return_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _stop_owned_process_tree(process)
            return_code = 124
    rendered_output = log_path.read_text(encoding="utf-8")
    print(rendered_output, end="")
    if timed_out:
        print(f"Required security suite timed out safely: {path}", file=sys.stderr)
        raise SystemExit(124)
    if re.search(r"\bskipped(?:\s*=|\s+\()", rendered_output, flags=re.IGNORECASE):
        print(f"Required security suite reported skipped tests: {path}", file=sys.stderr)
        raise SystemExit(3)
    if return_code:
        raise SystemExit(return_code)


def main() -> None:
    inventory = load_inventory()
    behavioral = inventory["behavioral"]
    structural = inventory["structural"]
    print(
        f"ATLAS security inventory: {len(behavioral)} behavioral suites, "
        f"{len(structural)} structural suite."
    )
    configured_hermetic_root = os.getenv("ATLAS_HERMETIC_ROOT")
    if configured_hermetic_root:
        temp_parent = Path(configured_hermetic_root).resolve() / "authorities" / "security-gate"
        temp_parent.mkdir(parents=True, exist_ok=True)
        gate_root = (temp_parent / f"atlas_security_gate_{uuid.uuid4().hex}").resolve()
    else:
        gate_root = Path(
            tempfile.mkdtemp(prefix=f"atlas_security_gate_{uuid.uuid4().hex}_")
        ).resolve()
    gate_root.mkdir(parents=True, exist_ok=True)
    for entry in behavioral:
        run_entry("behavioral", entry, gate_root)
    for entry in structural:
        run_entry("structural security check", entry, gate_root)
    print(
        f"\nATLAS security gate passed: {len(behavioral)} behavioral suites and "
        f"{len(structural)} structural suite."
    )


if __name__ == "__main__":
    main()
