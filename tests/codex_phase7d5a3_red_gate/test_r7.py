"""Repair 7 red gate: reader interception and gate manifests must fail closed."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from ._helpers import REPO, assert_external_temp


RUNNER = REPO / "scripts" / "run_phase7d5a_isolated_gate.ps1"


def _probe_reader(root: Path, operation: str) -> dict:
    code = r'''
import builtins, json, os, sys
from pathlib import Path

os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
from tests import _isolated_data_guard as G

root = Path(sys.argv[1])
operation = sys.argv[2]
isolated = root / "isolated-runtime"
isolated.mkdir(parents=True, exist_ok=True)
repo = root / "synthetic-repo"
repo.mkdir(parents=True, exist_ok=True)

# Keep this probe independent of the machine's real repository/runtime and
# temp roots.  The guarded path is harmless and intentionally nonexistent.
G._allowed_roots = lambda: [isolated.resolve()]
G._repo_root = lambda: repo.resolve()
G._real_runtime = lambda: (repo / ".runtime").resolve()
G.install()
G.set_current_nodeid("codex-red::" + operation)
suffix = ".joblib" if operation == "joblib.load" else ".parquet"
path = root.parent / "synthetic-disallowed" / ("sealed-2025" + suffix)

try:
    if operation == "builtins.open":
        builtins.open(path, "rb")
    elif operation == "Path.read_bytes":
        path.read_bytes()
    elif operation == "joblib.load":
        import joblib
        joblib.load(path)
    elif operation == "pyarrow.dataset.dataset":
        import pyarrow.dataset as ds
        ds.dataset(path)
    else:
        raise AssertionError(operation)
except Exception as exc:
    result = {
        "exception": type(exc).__name__,
        "message": str(exc),
        "violations": G.violations(),
    }
else:
    result = {"exception": None, "message": "", "violations": G.violations()}
print(json.dumps(result))
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(root), operation],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def _assert_guard_rejected(record: dict, operation: str) -> None:
    assert record["exception"] == "IsolatedDataViolation", record
    assert len(record["violations"]) == 1, record
    violation = record["violations"][0]
    assert violation["test"] == f"codex-red::{operation}"
    assert violation["reader"]
    assert violation["sealedOr2025"] is True


def test_guard_blocks_builtin_open_outside_allowed_roots(tmp_path):
    operation = "builtins.open"
    record = _probe_reader(assert_external_temp(tmp_path), operation)
    _assert_guard_rejected(record, operation)


def test_guard_blocks_path_read_bytes_outside_allowed_roots(tmp_path):
    operation = "Path.read_bytes"
    record = _probe_reader(assert_external_temp(tmp_path), operation)
    _assert_guard_rejected(record, operation)


def test_guard_blocks_joblib_load_outside_allowed_roots(tmp_path):
    operation = "joblib.load"
    record = _probe_reader(assert_external_temp(tmp_path), operation)
    _assert_guard_rejected(record, operation)


def test_guard_blocks_pyarrow_dataset_outside_allowed_roots(tmp_path):
    operation = "pyarrow.dataset.dataset"
    record = _probe_reader(assert_external_temp(tmp_path), operation)
    _assert_guard_rejected(record, operation)


def test_os_temp_root_is_not_blanket_allowed(tmp_path):
    root = assert_external_temp(tmp_path)
    code = r'''
import json, os, sys, tempfile
from pathlib import Path

os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
from tests import _isolated_data_guard as G

root = Path(sys.argv[1])
isolated = root / "isolated-runtime"
isolated.mkdir(parents=True, exist_ok=True)
G.install()
G.set_current_nodeid("codex-red::temp-sibling")
path = Path(tempfile.gettempdir()) / "codex-phase7d5a3-unrelated" / "sealed-2025.parquet"
try:
    G.check_open(path, "direct-policy-probe")
except Exception as exc:
    out = {"exception": type(exc).__name__, "violations": G.violations()}
else:
    out = {"exception": None, "violations": G.violations()}
print(json.dumps(out))
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(root)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(root / "isolated-runtime"),
        },
    )
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(result.stdout.strip().splitlines()[-1])
    assert record["exception"] == "IsolatedDataViolation", record
    assert len(record["violations"]) == 1, record


def test_guard_install_failure_is_fatal(tmp_path):
    root = assert_external_temp(tmp_path)
    code = r'''
import builtins, json, os, sys

os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
from tests import _isolated_data_guard as G

real_import = builtins.__import__
def reject_required_reader(name, globals=None, locals=None, fromlist=(), level=0):
    if name.startswith("pyarrow.parquet"):
        raise ImportError("synthetic required-reader install failure")
    return real_import(name, globals, locals, fromlist, level)

builtins.__import__ = reject_required_reader
try:
    G.install()
finally:
    builtins.__import__ = real_import
print(json.dumps({"fatal": False, "installed": G._installed["on"]}))
'''
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(root / "isolated-runtime"),
        },
    )
    assert result.returncode != 0, (
        "guard installation returned success after a required reader failed to install:\n"
        + result.stdout
        + result.stderr
    )


def _harmless_test(root: Path, name: str) -> Path:
    test_file = root / name
    test_file.write_text("def test_harmless():\n    assert True\n", encoding="utf-8")
    return test_file


def _pytest_env(root: Path, manifest: Path) -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "PYTHONDONTWRITEBYTECODE": "1",
        "ASP_REQUIRE_ISOLATED_RUNTIME": "1",
        "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(root / "isolated-runtime"),
        "ASP_ISOLATED_DATA_MANIFEST": str(manifest),
    }


def _run_manifest_session(root: Path, test_file: Path, manifest: Path, *, collect_only: bool = False):
    command = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-q",
        "-p",
        "tests.conftest",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(root / ("collect-basetemp" if collect_only else "execute-basetemp")),
    ]
    if collect_only:
        command.append("--collect-only")
    return subprocess.run(
        command,
        cwd=REPO,
        env=_pytest_env(root, manifest),
        capture_output=True,
        text=True,
        timeout=45,
    )


def _unwritable_manifest(root: Path, name: str) -> Path:
    blocker = root / name
    blocker.write_text("this path is deliberately a file", encoding="utf-8")
    return blocker / "isolated-data-violations.json"


def test_manifest_write_failure_is_fatal(tmp_path):
    root = assert_external_temp(tmp_path)
    manifest = _unwritable_manifest(root, "manifest-parent-is-a-file")
    result = _run_manifest_session(root, _harmless_test(root, "test_manifest_write.py"), manifest)
    assert not manifest.exists()
    assert result.returncode != 0, "pytest passed although its mandatory guard manifest could not be written"


def test_missing_collection_manifest_is_fatal(tmp_path):
    root = assert_external_temp(tmp_path)
    manifest = _unwritable_manifest(root, "collection-manifest-parent-is-a-file")
    result = _run_manifest_session(
        root,
        _harmless_test(root, "test_collection_manifest.py"),
        manifest,
        collect_only=True,
    )
    assert not manifest.exists()
    assert result.returncode != 0, "collection passed without its mandatory data-access manifest"


def test_missing_execution_manifest_is_fatal(tmp_path):
    root = assert_external_temp(tmp_path)
    manifest = _unwritable_manifest(root, "execution-manifest-parent-is-a-file")
    result = _run_manifest_session(root, _harmless_test(root, "test_execution_manifest.py"), manifest)
    assert not manifest.exists()
    assert result.returncode != 0, "execution passed without its mandatory data-access manifest"


def test_collection_and_execution_manifests_are_distinct():
    source = RUNNER.read_text(encoding="utf-8")
    collection = re.search(r"\$(?:collection|collect)[A-Za-z]*DataManifest\s*=", source, re.IGNORECASE)
    execution = re.search(r"\$(?:execution|execute)[A-Za-z]*DataManifest\s*=", source, re.IGNORECASE)
    assert collection and execution, "runner does not define distinct collection and execution data manifests"
    assert collection.group(0).lower() != execution.group(0).lower()


def test_collection_violation_cannot_be_overwritten_by_execution(tmp_path):
    root = assert_external_temp(tmp_path)
    collection_test = root / "test_collection_probe.py"
    collection_test.write_text(
        "from tests import _isolated_data_guard as G\n"
        "try:\n"
        "    G.check_open(r'C:\\\\codex-phase7d5a3-red-gate\\\\sealed-2025.parquet', 'collection-probe')\n"
        "except G.IsolatedDataViolation:\n"
        "    pass\n"
        "def test_ok():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    execution_test = _harmless_test(root, "test_execution_probe.py")
    manifest = root / "shared-isolated-data-manifest.json"

    collect = _run_manifest_session(root, collection_test, manifest, collect_only=True)
    assert collect.returncode == 0, collect.stdout + collect.stderr
    first = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(first["violations"]) == 1, first

    execute = _run_manifest_session(root, execution_test, manifest)
    assert execute.returncode == 0, execute.stdout + execute.stderr
    final = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(final["violations"]) >= 1, "execution overwrote the collection-time violation"


def test_gate_fails_when_manifest_schema_is_invalid():
    source = RUNNER.read_text(encoding="utf-8")
    assert "PHASE_7D5A2_ISOLATED_DATA_MANIFEST_V1" in source, "runner does not declare the required manifest schema"
    schema_check = re.search(r"\.schema\b[^\r\n]*-ne[^\r\n]*PHASE_7D5A2_ISOLATED_DATA_MANIFEST_V1", source)
    assert schema_check, "runner never rejects an invalid external-data manifest schema"
