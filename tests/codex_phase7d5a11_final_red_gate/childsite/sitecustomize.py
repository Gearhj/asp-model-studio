"""Inherited subprocess isolation guard for the Phase 7D.5A.11 gate.

Python imports ``sitecustomize`` during interpreter startup.  The parent pytest
session places this directory first on ``PYTHONPATH`` so every D7/D8 child is
guarded before it can import or execute the production boundary under test.
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


_state = threading.local()


def _absolute(value: object) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    try:
        return Path(os.path.abspath(os.path.normpath(os.fsdecode(value)))).resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return None


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _write_mode(mode: object, flags: object) -> bool:
    if isinstance(mode, str) and any(token in mode for token in ("w", "a", "x", "+")):
        return True
    if isinstance(flags, int):
        mask = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        return bool(flags & mask)
    return False


def _append(record: dict[str, Any]) -> None:
    if getattr(_state, "writing", False):
        return
    _state.writing = True
    try:
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(_LOG_PATH, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
    finally:
        _state.writing = False


def _classify(path: Path, *, writing: bool) -> tuple[bool, str]:
    lowered = str(path).replace("/", "\\").lower()
    if lowered in {"nul", "\\\\.\\nul", "\\dev\\null"}:
        return True, "operating_system_null_device"
    if _under(path, _SHARED_RUNTIME):
        return False, "shared_runtime"
    if _under(path, _AUDIT_ROOT):
        return True, "audit_root"
    if writing:
        return False, "write_outside_audit_root"
    if _under(path, _REPO_ROOT):
        return True, "repository_non_runtime"
    for prefix in _PYTHON_ROOTS:
        if _under(path, prefix):
            return True, "python_environment"
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return False, "sensitive_external"
    if path.suffix.lower() in _DATA_SUFFIXES:
        return False, "external_data_or_model"
    return True, "unclassified_non_data_read"


def _audit(event: str, args: tuple[Any, ...]) -> None:
    if getattr(_state, "writing", False):
        return
    if event == "open" and args:
        path = _absolute(args[0])
        if path is None:
            return
        writing = _write_mode(args[1] if len(args) > 1 else None, args[2] if len(args) > 2 else None)
        allowed, classification = _classify(path, writing=writing)
        interesting = writing or not allowed or path.suffix.lower() in _DATA_SUFFIXES
        if interesting:
            _append({
                "kind": "open",
                "pid": os.getpid(),
                "path": str(path),
                "writing": writing,
                "allowed": allowed,
                "classification": classification,
                "existedAtAttempt": path.exists(),
            })
        if not allowed:
            raise RuntimeError(f"Phase 7D.5A.11 child isolation rejected {classification}")
    elif event in {"socket.connect", "socket.getaddrinfo"}:
        _append({"kind": "network", "pid": os.getpid(), "event": event, "arguments": repr(args)[:500]})
        raise RuntimeError("Phase 7D.5A.11 forbids child network/provider access")


try:
    _AUDIT_ROOT = _absolute(os.environ["CODEX_PHASE7D5A11_AUDIT_ROOT"])
    _REPO_ROOT = _absolute(os.environ["CODEX_PHASE7D5A11_REPO_ROOT"])
    _LOG_PATH_VALUE = _absolute(os.environ["CODEX_PHASE7D5A11_CHILD_AUDIT_LOG"])
    if _AUDIT_ROOT is None or _REPO_ROOT is None or _LOG_PATH_VALUE is None:
        raise RuntimeError("invalid child-audit path authority")
    _LOG_PATH = str(_LOG_PATH_VALUE)
    if not _under(_LOG_PATH_VALUE, _AUDIT_ROOT):
        raise RuntimeError("child-audit log escaped the audit root")
    _SHARED_RUNTIME = (_REPO_ROOT / ".runtime").resolve(strict=False)
    _PYTHON_ROOTS = {
        Path(sys.prefix).resolve(strict=False),
        Path(sys.base_prefix).resolve(strict=False),
    }
    _DATA_SUFFIXES = {
        ".arrow", ".csv", ".db", ".feather", ".gz", ".joblib", ".jsonl",
        ".npy", ".npz", ".parquet", ".pickle", ".pkl", ".pq", ".sqlite",
    }
    _SENSITIVE_MARKERS = ("asp-data-staging", "asp-model-exchange", "sealed", "2025", "2026")
    sys.addaudithook(_audit)
    _append({"kind": "process_start", "pid": os.getpid(), "executable": sys.executable})
except BaseException as exc:  # fail closed before child code can run
    try:
        sys.stderr.write(f"Phase 7D.5A.11 child isolation bootstrap failed: {type(exc).__name__}\n")
        sys.stderr.flush()
    finally:
        os._exit(97)
