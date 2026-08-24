"""Hermetic audit boundary for the Phase 7D.5A.5 delta-red suite.

The runner establishes every mutable root before Python starts.  This hook
validates that authority, records relevant file access, and blocks any existing
external/shared-runtime data object before bytes can be returned.  It does not
alter the production behavior exercised by the delta tests.
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
_configured = os.environ.get("CODEX_PHASE7D5A5_AUDIT_ROOT", "").strip()
if not _configured:
    raise RuntimeError(
        "CODEX_PHASE7D5A5_AUDIT_ROOT must name an explicit disposable external root"
    )


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
                    raise RuntimeError(
                        f"delta-red mutable root traverses a reparse point: {cursor}"
                    )
        except OSError as exc:
            raise RuntimeError(f"cannot validate mutable-root component {cursor}: {exc}") from exc
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent


_lexical_audit_root = _absolute_lexical(_configured)
if _lexical_audit_root is None or not _lexical_audit_root.is_absolute():
    raise RuntimeError("CODEX_PHASE7D5A5_AUDIT_ROOT must be an absolute filesystem path")

for _forbidden in (
    REPO_ROOT,
    REPO_ROOT / ".runtime",
    Path(r"C:\Users\james\asp-model-exchange"),
    Path(r"C:\Users\james\asp-data-staging"),
):
    if _under(_lexical_audit_root, _absolute_lexical(_forbidden) or _forbidden):
        raise RuntimeError(f"delta-red mutable root is inside forbidden authority: {_forbidden}")

_assert_no_existing_reparse_component(_lexical_audit_root)
AUDIT_ROOT = _lexical_audit_root.resolve(strict=False)
RUNTIME_ROOT = AUDIT_ROOT / "runtime"
TEMP_ROOT = AUDIT_ROOT / "temp"
PYTEST_ROOT = TEMP_ROOT / "pytest"
MODEL_EXCHANGE_ROOT = AUDIT_ROOT / "model-exchange-disabled"

for _path in (AUDIT_ROOT, RUNTIME_ROOT, TEMP_ROOT, PYTEST_ROOT, MODEL_EXCHANGE_ROOT):
    if not _under(_path, AUDIT_ROOT):
        raise RuntimeError(f"mutable child escapes audit root: {_path}")
    _path.mkdir(parents=True, exist_ok=True)

# These values are repeated defensively before delta test modules import the
# production services.  The runner sets the same values before Python starts.
os.environ["CODEX_PHASE7D5A5_AUDIT_ROOT"] = str(AUDIT_ROOT)
os.environ["ASP_MODEL_STUDIO_RUNTIME_ROOT"] = str(RUNTIME_ROOT)
os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
os.environ["ASP_ISOLATED_TEST_TEMP"] = str(PYTEST_ROOT)
os.environ["TEMP"] = str(TEMP_ROOT)
os.environ["TMP"] = str(TEMP_ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.environ["ASP_MODEL_EXCHANGE_ROOT"] = str(MODEL_EXCHANGE_ROOT)

_manifest_path = Path(
    os.environ.get(
        "CODEX_PHASE7D5A5_EXTERNAL_ACCESS_MANIFEST",
        str(AUDIT_ROOT / "external-access.json"),
    )
)
if not _under(_absolute_lexical(_manifest_path) or _manifest_path, AUDIT_ROOT):
    raise RuntimeError("external-access manifest must remain under the audit root")

_data_suffixes = {
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
_sensitive_markers = ("asp-data-staging", "asp-model-exchange", "sealed", "2025", "2026")
_events: list[dict[str, Any]] = []
_network_events: list[dict[str, Any]] = []
_event_lock = threading.Lock()


def _classify_open(path: Path) -> tuple[bool, str]:
    shared_runtime = (REPO_ROOT / ".runtime").resolve()
    lowered = str(path).replace("/", "\\").lower()
    if _under(path, shared_runtime):
        return False, "shared_runtime"
    if _under(path, AUDIT_ROOT):
        return True, "audit_root"
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
        interesting = (
            _under(path, shared_runtime)
            or path.suffix.lower() in _data_suffixes
            or any(marker in lowered for marker in _sensitive_markers)
        )
        if not interesting:
            return
        allowed, classification = _classify_open(path)
        existed = path.exists()
        record = {
            "event": event,
            "path": str(path),
            "allowed": allowed,
            "classification": classification,
            "existedAtAttempt": existed,
            "requestingTest": os.environ.get("PYTEST_CURRENT_TEST", "<collection-or-session>"),
        }
        with _event_lock:
            _events.append(record)
        if not allowed and existed:
            raise RuntimeError(
                "Phase 7D.5A.5 delta-red gate blocked an existing external/shared-runtime object"
            )
    elif event in {"socket.connect", "socket.getaddrinfo"}:
        record = {
            "event": event,
            "arguments": repr(args)[:500],
            "requestingTest": os.environ.get("PYTEST_CURRENT_TEST", "<collection-or-session>"),
        }
        with _event_lock:
            _network_events.append(record)
        raise RuntimeError("Phase 7D.5A.5 delta-red gate forbids provider/network access")


sys.addaudithook(_audit_hook)


def _write_external_manifest() -> None:
    with _event_lock:
        events = list(_events)
        network = list(_network_events)
    unexpected_existing = [
        item for item in events if not item["allowed"] and item["existedAtAttempt"]
    ]
    payload = {
        "schemaVersion": "CODEX_PHASE7D5A5_EXTERNAL_ACCESS_V1",
        "auditRoot": str(AUDIT_ROOT),
        "runtimeRoot": str(RUNTIME_ROOT),
        "attempts": events,
        "networkAttempts": network,
        "unexpectedExistingExternalDataOpens": unexpected_existing,
        "bronzeRowsOpened": any(
            item["existedAtAttempt"]
            and not item["allowed"]
            and "asp-data-staging" in item["path"].lower()
            for item in events
        ),
        "sealedRowsOpened": any(
            item["existedAtAttempt"]
            and not item["allowed"]
            and ("sealed" in item["path"].lower() or "2025" in item["path"].lower())
            for item in events
        ),
        "providerCalls": len(network),
    }
    _manifest_path.parent.mkdir(parents=True, exist_ok=True)
    _manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    _write_external_manifest()
