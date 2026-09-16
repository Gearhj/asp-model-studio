"""Fail-closed isolation evidence for the Phase 7D.5A.11 final-red suite.

The runner establishes every mutable root before Python imports this module.
This hook records relevant data/model opens and rejects existing external data
or all network access without changing any D3, D7, or D8 production decision.
"""
from __future__ import annotations

import json
import os
import socket
import stat
import sys
import threading
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
_configured = os.environ.get("CODEX_PHASE7D5A11_AUDIT_ROOT", "").strip()
if not _configured:
    raise RuntimeError("CODEX_PHASE7D5A11_AUDIT_ROOT must name an explicit disposable root")


def _absolute_lexical(value: object) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    try:
        return Path(os.path.abspath(os.path.normpath(os.fsdecode(value))))
    except (OSError, TypeError, ValueError):
        return None


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _assert_no_existing_reparse_component(path: Path) -> None:
    cursor = path
    while True:
        try:
            if cursor.exists():
                attrs = cursor.lstat().st_file_attributes if os.name == "nt" else 0
                if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise RuntimeError(f"audit root crosses a reparse point: {cursor}")
        except OSError as exc:
            raise RuntimeError(f"cannot inspect audit-root component {cursor}: {exc}") from exc
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent


_lexical_root = _absolute_lexical(_configured)
if _lexical_root is None or not _lexical_root.is_absolute():
    raise RuntimeError("CODEX_PHASE7D5A11_AUDIT_ROOT must be an absolute path")
for _forbidden in (
    REPO_ROOT,
    REPO_ROOT / ".runtime",
    Path(r"C:\Users\james\asp-model-exchange"),
    Path(r"C:\Users\james\asp-data-staging"),
):
    forbidden = _absolute_lexical(_forbidden) or _forbidden
    if _under(_lexical_root, forbidden):
        raise RuntimeError(f"audit root is inside forbidden authority: {forbidden}")
_assert_no_existing_reparse_component(_lexical_root)

AUDIT_ROOT = _lexical_root.resolve(strict=False)
RUNTIME_ROOT = AUDIT_ROOT / "runtime"
TEMP_ROOT = AUDIT_ROOT / "temp"
MODEL_EXCHANGE_ROOT = AUDIT_ROOT / "model-exchange-disabled"
for _path in (AUDIT_ROOT, RUNTIME_ROOT, TEMP_ROOT, MODEL_EXCHANGE_ROOT):
    if not _under(_path, AUDIT_ROOT):
        raise RuntimeError(f"mutable child escaped audit root: {_path}")
    _path.mkdir(parents=True, exist_ok=True)

os.environ["ASP_MODEL_STUDIO_RUNTIME_ROOT"] = str(RUNTIME_ROOT)
os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
os.environ["ASP_MODEL_EXCHANGE_ROOT"] = str(MODEL_EXCHANGE_ROOT)
os.environ["TEMP"] = str(TEMP_ROOT)
os.environ["TMP"] = str(TEMP_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Every Python subprocess launched by D7/D8 imports the child guard before its
# target script.  Keep the repository on PYTHONPATH for the actual production
# modules while placing the guard's sitecustomize directory first.
_childsite = REPO_ROOT / "tests" / "codex_phase7d5a11_final_red_gate" / "childsite"
_child_log = AUDIT_ROOT / "child-audit.jsonl"
_inherited_pythonpath = os.environ.get("PYTHONPATH", "")
_pythonpath_parts = [str(_childsite), str(REPO_ROOT)]
if _inherited_pythonpath:
    _pythonpath_parts.append(_inherited_pythonpath)
os.environ["PYTHONPATH"] = os.pathsep.join(_pythonpath_parts)
os.environ["CODEX_PHASE7D5A11_REPO_ROOT"] = str(REPO_ROOT)
os.environ["CODEX_PHASE7D5A11_CHILD_AUDIT_LOG"] = str(_child_log)

_manifest_path = Path(
    os.environ.get(
        "CODEX_PHASE7D5A11_EXTERNAL_ACCESS_MANIFEST",
        str(AUDIT_ROOT / "external-access.json"),
    )
).resolve()
if not _under(_manifest_path, AUDIT_ROOT):
    raise RuntimeError("external-access manifest escaped the audit root")

_data_suffixes = {
    ".arrow", ".csv", ".feather", ".joblib", ".npy", ".npz",
    ".parquet", ".pickle", ".pkl", ".pq",
}
_sensitive_markers = ("asp-data-staging", "asp-model-exchange", "sealed", "2025", "2026")
_events: list[dict[str, Any]] = []
_network_events: list[dict[str, Any]] = []
_event_lock = threading.Lock()


def _write_mode(args: tuple[Any, ...]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else None
    if isinstance(mode, str) and any(token in mode for token in ("w", "a", "x", "+")):
        return True
    if isinstance(flags, int):
        mask = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        return bool(flags & mask)
    return False


def _classify_open(path: Path, *, writing: bool) -> tuple[bool, str]:
    shared_runtime = (REPO_ROOT / ".runtime").resolve()
    lowered = str(path).replace("/", "\\").lower()
    if lowered in {"nul", "\\\\.\\nul", "\\dev\\null"}:
        return True, "operating_system_null_device"
    if _under(path, shared_runtime):
        return False, "shared_runtime"
    if _under(path, AUDIT_ROOT):
        return True, "audit_root"
    if writing:
        return False, "write_outside_audit_root"
    if _under(path, REPO_ROOT):
        return True, "repository_non_runtime"
    for prefix in {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}:
        if _under(path, prefix):
            return True, "python_environment"
    if any(marker in lowered for marker in _sensitive_markers):
        return False, "sensitive_external"
    if path.suffix.lower() in _data_suffixes:
        return False, "external_data_or_model"
    return True, "unclassified_non_data"


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if event == "open" and args:
        path = _absolute_lexical(args[0])
        if path is None:
            return
        shared_runtime = (REPO_ROOT / ".runtime").resolve()
        lowered = str(path).lower()
        writing = _write_mode(args)
        interesting = (
            writing
            or
            _under(path, shared_runtime)
            or path.suffix.lower() in _data_suffixes
            or any(marker in lowered for marker in _sensitive_markers)
        )
        if not interesting:
            return
        allowed, classification = _classify_open(path, writing=writing)
        existed = path.exists()
        record = {
            "event": event,
            "path": str(path),
            "allowed": allowed,
            "classification": classification,
            "writing": writing,
            "existedAtAttempt": existed,
            "requestingTest": os.environ.get("PYTEST_CURRENT_TEST", "<collection-or-session>"),
        }
        with _event_lock:
            _events.append(record)
        if not allowed:
            raise RuntimeError(
                f"Phase 7D.5A.11 blocked {classification}: {path}"
            )
    elif event in {"socket.connect", "socket.getaddrinfo"}:
        record = {
            "event": event,
            "arguments": repr(args)[:500],
            "requestingTest": os.environ.get("PYTEST_CURRENT_TEST", "<collection-or-session>"),
        }
        with _event_lock:
            _network_events.append(record)
        raise RuntimeError("Phase 7D.5A.11 forbids network/provider access")


sys.addaudithook(_audit_hook)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    del session, exitstatus
    with _event_lock:
        events = list(_events)
        network = list(_network_events)
    child_events: list[dict[str, Any]] = []
    if _child_log.is_file():
        for line in _child_log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                child_events.append(json.loads(line))
    unexpected = [item for item in events if not item["allowed"]]
    child_violations = [item for item in child_events if item.get("allowed") is False]
    child_network = [item for item in child_events if item.get("kind") == "network"]
    payload = {
        "schemaVersion": "CODEX_PHASE7D5A11_EXTERNAL_ACCESS_V1",
        "auditRoot": str(AUDIT_ROOT),
        "runtimeRoot": str(RUNTIME_ROOT),
        "attempts": events,
        "childAttempts": child_events,
        "childProcessStarts": sum(item.get("kind") == "process_start" for item in child_events),
        "childViolations": child_violations,
        "networkAttempts": network,
        "childNetworkAttempts": child_network,
        "unexpectedExternalDataAttempts": unexpected,
        "unexpectedExistingExternalDataOpens": [
            item for item in unexpected if item["existedAtAttempt"]
        ],
        "bronzeRowsOpened": any(
            item["existedAtAttempt"] and "asp-data-staging" in item["path"].lower()
            for item in events
        ),
        "sealedRowsOpened": any(
            item["existedAtAttempt"]
            and ("sealed" in item["path"].lower() or "2025" in item["path"].lower())
            for item in events
        ),
        "providerCalls": len(network) + len(child_network),
    }
    _manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
