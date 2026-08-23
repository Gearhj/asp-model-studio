"""Isolation and external-access evidence for the Codex Phase 7D.5A.3 red gate.

This file is loaded before the red test modules.  It fixes every mutable root to the
runner-created disposable directory and records data/model file-open attempts without
changing the behavior under test.  In particular, the audit hook deliberately does not
"repair" the production isolation guard: R7 must still observe the production bypasses.
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
_configured = os.environ.get("CODEX_PHASE7D5A3_AUDIT_ROOT")
if not _configured:
    raise RuntimeError(
        "CODEX_PHASE7D5A3_AUDIT_ROOT must name an explicit disposable external root"
    )
_lexical_audit_root = Path(os.path.abspath(os.path.normpath(_configured)))
if not _lexical_audit_root.is_absolute():
    raise RuntimeError("CODEX_PHASE7D5A3_AUDIT_ROOT must be absolute")


def _lexically_under(path: Path, root: Path) -> bool:
    path_text = os.path.normcase(str(path))
    root_text = os.path.normcase(str(root)).rstrip("\\/")
    return path_text == root_text or path_text.startswith(root_text + os.sep)


def _assert_no_existing_reparse_component(path: Path) -> None:
    cursor = path
    while True:
        if cursor.exists():
            attrs = cursor.lstat().st_file_attributes if os.name == "nt" else 0
            if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise RuntimeError(f"red-gate mutable root traverses a reparse point: {cursor}")
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent


for _forbidden in (
    REPO_ROOT,
    REPO_ROOT / ".runtime",
    Path(r"C:\Users\james\asp-model-exchange"),
    Path(r"C:\Users\james\asp-data-staging"),
):
    if _lexically_under(_lexical_audit_root, _forbidden):
        raise RuntimeError(f"red-gate mutable root is inside a forbidden authority: {_forbidden}")
_assert_no_existing_reparse_component(_lexical_audit_root)
AUDIT_ROOT = _lexical_audit_root.resolve(strict=False)
RUNTIME_ROOT = (AUDIT_ROOT / "runtime").resolve()
TEMP_ROOT = (AUDIT_ROOT / "temp").resolve()
PYTEST_ROOT = (TEMP_ROOT / "pytest").resolve()
MODEL_EXCHANGE_ROOT = (AUDIT_ROOT / "model-exchange-disabled").resolve()

for _path in (AUDIT_ROOT, RUNTIME_ROOT, TEMP_ROOT, PYTEST_ROOT, MODEL_EXCHANGE_ROOT):
    _path.mkdir(parents=True, exist_ok=True)

# These assignments happen before red test modules import production code.
os.environ["CODEX_PHASE7D5A3_AUDIT_ROOT"] = str(AUDIT_ROOT)
os.environ["ASP_MODEL_STUDIO_RUNTIME_ROOT"] = str(RUNTIME_ROOT)
os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
os.environ["TEMP"] = str(TEMP_ROOT)
os.environ["TMP"] = str(TEMP_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["ASP_MODEL_EXCHANGE_ROOT"] = str(MODEL_EXCHANGE_ROOT)

_MANIFEST_PATH = Path(
    os.environ.get(
        "CODEX_PHASE7D5A3_EXTERNAL_ACCESS_MANIFEST",
        str(AUDIT_ROOT / "external-access.json"),
    )
)
_DATA_OR_MODEL_SUFFIXES = {
    ".arrow",
    ".csv",
    ".feather",
    ".joblib",
    ".npy",
    ".npz",
    ".parquet",
    ".pickle",
    ".pkl",
    ".pq",
}
_SENSITIVE_MARKERS = (
    "asp-data-staging",
    "asp-model-exchange",
    "sealed",
    "2025",
    "2026",
)
_events: list[dict[str, Any]] = []
_network_events: list[dict[str, Any]] = []
_event_lock = threading.Lock()


def _absolute_lexical(value: object) -> Path | None:
    if not isinstance(value, (str, bytes, os.PathLike)):
        return None
    try:
        return Path(os.path.abspath(os.path.normpath(os.fsdecode(value))))
    except (OSError, TypeError, ValueError):
        return None


def _under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _classify_open(path: Path) -> tuple[bool, str]:
    lowered = str(path).replace("/", "\\").lower()
    shared_runtime = (REPO_ROOT / ".runtime").resolve()
    if _under(path, shared_runtime):
        return False, "shared_runtime"
    if _under(path, AUDIT_ROOT):
        return True, "audit_root"
    if _under(path, REPO_ROOT):
        return True, "repository_non_runtime"
    for prefix in {Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve()}:
        if _under(path, prefix):
            return True, "python_environment"
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return False, "sensitive_external"
    if path.suffix.lower() in _DATA_OR_MODEL_SUFFIXES:
        return False, "external_data_or_model"
    return True, "unclassified_non_data"


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    if event == "open" and args:
        path = _absolute_lexical(args[0])
        if path is None:
            return
        shared_runtime = (REPO_ROOT / ".runtime").resolve()
        interesting = (
            _under(path, shared_runtime)
            or path.suffix.lower() in _DATA_OR_MODEL_SUFFIXES
            or any(marker in str(path).lower() for marker in _SENSITIVE_MARKERS)
        )
        if not interesting:
            return
        allowed, classification = _classify_open(path)
        record = {
            "event": event,
            "path": str(path),
            "allowed": allowed,
            "classification": classification,
            "existedAtAttempt": path.exists(),
            "requestingTest": os.environ.get("PYTEST_CURRENT_TEST", "<collection-or-session>"),
        }
        with _event_lock:
            _events.append(record)
        # This harness boundary is deliberately independent of the production
        # guard exercised by R7.  A harmless nonexistent probe remains observable
        # to the test, while an existing forbidden object is stopped before the
        # underlying open can return any bytes.
        if not allowed and record["existedAtAttempt"]:
            raise RuntimeError(
                "Phase 7D.5A.3 red gate blocked an existing external/shared-runtime object"
            )
    elif event in {"socket.connect", "socket.getaddrinfo"}:
        record = {
            "event": event,
            "arguments": repr(args)[:500],
            "requestingTest": os.environ.get("PYTEST_CURRENT_TEST", "<collection-or-session>"),
        }
        with _event_lock:
            _network_events.append(record)
        raise RuntimeError("Phase 7D.5A.3 red gate forbids provider/network access")


sys.addaudithook(_audit_hook)


def _write_external_manifest() -> None:
    with _event_lock:
        events = list(_events)
        network = list(_network_events)
    unexpected_existing = [
        event for event in events if not event["allowed"] and event["existedAtAttempt"]
    ]
    payload = {
        "schemaVersion": "CODEX_PHASE7D5A3_EXTERNAL_ACCESS_V1",
        "auditRoot": str(AUDIT_ROOT),
        "runtimeRoot": str(RUNTIME_ROOT),
        "attempts": events,
        "networkAttempts": network,
        "unexpectedExistingExternalDataOpens": unexpected_existing,
        "bronzeRowsOpened": any(
            event["existedAtAttempt"]
            and not event["allowed"]
            and "asp-data-staging" in event["path"].lower()
            for event in events
        ),
        "sealedRowsOpened": any(
            event["existedAtAttempt"]
            and not event["allowed"]
            and ("sealed" in event["path"].lower() or "2025" in event["path"].lower())
            for event in events
        ),
        "providerCalls": len(network),
    }
    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MANIFEST_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    _write_external_manifest()
