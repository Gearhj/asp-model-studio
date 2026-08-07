"""Run the isolated production-runtime and operational catalog closeout soak.

This orchestrator closes the gap between the in-process operational workload
and a real FastAPI listener lifecycle.  It consumes one explicit 21-authority
map, allocates a unique child under every authority, builds the production
frontend once, serves it without HMR, runs the operational workload, replaces
only its own isolated backend listener, and emits one checksummed aggregate.

The CLI always enforces release minimums.  Focused tests may construct
``IntegratedCloseoutSettings`` with ``enforce_release_minimums=False``; no CLI
switch exposes that bypass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.run_bureau_metadata_isolated_acceptance import (
    ADMIN_PRINCIPAL,
    TENANT_ID,
    _initialize_synthetic_authority,
)
from scripts.isolated_loopback_ports import (
    ReservedLoopbackPorts,
    reserve_dynamic_non_live_ports,
)
from scripts.run_bureau_metadata_operational_soak import (
    ALL_OPERATIONS,
    DEFAULT_DURATION_SECONDS,
    FRONTEND_RELOAD_EVIDENCE_CLASSIFICATION,
    MIN_BOUNDED_OPERATIONS,
    MIN_CATALOG_VERSIONS,
    MIN_CROSSWALK_PREVIEWS,
    MIN_DECISION_WRITES,
    MIN_FRONTEND_AUTHENTICATED_RELOADS,
    MIN_PROJECTS,
    MIN_SERVICE_RELOADS,
    MIN_USERS,
    SoakConfigurationError,
    SoakSettings,
    _frontend_reload_evidence_checksum,
    _load_authority_map as _load_soak_authority_map,
    _load_frontend_reload_evidence,
    run_soak,
)
from scripts.run_bureau_metadata_production_auth_acceptance import (
    REQUIRED_AUTHORITIES,
    SYNTHETIC_PROJECTS,
    _assert_ports,
    _build_production_frontend,
    _clean_subprocess_environment,
    _create_run_scopes,
    _environment_pins,
    _load_authority_map,
    _start_static_frontend,
    _stop_process,
    _wait_for_http,
)
from server.bureau_metadata import catalog_registry
from server.bureau_metadata.catalog_registry import CatalogRegistry
from server.bureau_metadata.crosswalk_governance import (
    CrosswalkAuditMetadata,
    CrosswalkEvidenceReference,
    CrosswalkLineage,
    GovernedMappingDecision,
    build_governed_revision,
    governance_identity,
)
from server.bureau_metadata.crosswalk_governance_repository import (
    SQLiteGovernedCrosswalkRepository,
)
from server.bureau_metadata.normalizer import canonical_json_bytes
from server.bureau_metadata.types import BureauCatalogKey


MIN_ACTUAL_BACKEND_RESTARTS = 10
MIN_TIMED_WINDOW_AUTHENTICATED_RELOADS = 60
INTEGRATION_EVENT_FILE = "bureau-metadata-integration-events.jsonl"
INTEGRATION_ENTITLED_PRINCIPALS = (
    "synthetic-project-user-alpha",
    "synthetic-project-user-beta",
    "synthetic-project-user-delta",
    "synthetic-project-user-epsilon",
)
LIVE_FRONTEND_PORT = 5174
LIVE_BACKEND_PORT = 8001
VIOLATION_FILE = "integrated-network-isolation-violation.jsonl"
SUMMARY_FILE = "integrated-catalog-closeout-summary.json"
PROGRESS_FILE = "integrated-catalog-closeout-progress.jsonl"
MAX_WINDOWS_BROWSER_PROFILE_PHASE_LENGTH = 140


class IntegratedCloseoutError(RuntimeError):
    """A release gate failed without exposing authority or credential detail."""


def _browser_profile_cli_path(path: Path) -> Path:
    """Return the same isolated profile through a bounded Windows path alias.

    Chromium creates cache descendants below ``user-data-dir``.  The canonical
    authority remains unchanged, but its fully qualified Windows spelling can
    leave too little room for those descendants.  A filesystem-provided 8.3
    alias is accepted only when it resolves back to the exact same existing
    authority directory.
    """

    canonical = path.resolve(strict=True)
    if os.name != "nt":
        return canonical

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_short_path = kernel32.GetShortPathNameW
    get_short_path.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
    )
    get_short_path.restype = wintypes.DWORD
    buffer = ctypes.create_unicode_buffer(32_768)
    written = int(get_short_path(str(canonical), buffer, len(buffer)))
    if written <= 0 or written >= len(buffer) or not buffer.value:
        raise IntegratedCloseoutError(
            "The isolated browser profile has no bounded Windows path alias."
        )
    candidate = Path(buffer.value)
    if candidate.resolve(strict=True) != canonical:
        raise IntegratedCloseoutError(
            "The isolated browser profile path alias resolved to another directory."
        )
    if len(str(candidate)) > MAX_WINDOWS_BROWSER_PROFILE_PHASE_LENGTH:
        raise IntegratedCloseoutError(
            "The isolated browser profile path remains too long for Chromium."
        )
    return candidate


@dataclass(frozen=True, slots=True)
class BrowserPhaseReloadPlan:
    admin_reload_attempts: int
    project_reload_attempts_per_project: int
    integration_reload_attempts: int

    @property
    def expected_authenticated_reloads(self) -> int:
        return (
            self.admin_reload_attempts
            + (2 * self.project_reload_attempts_per_project)
            + self.integration_reload_attempts
        )


BROWSER_PHASE_RELOAD_PLANS: Mapping[str, BrowserPhaseReloadPlan] = {
    "initial": BrowserPhaseReloadPlan(10, 5, 6),
    "timed-window": BrowserPhaseReloadPlan(20, 5, 30),
    "final": BrowserPhaseReloadPlan(10, 5, 6),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _checksum(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(payload))).hexdigest()


@dataclass(frozen=True, slots=True)
class IntegratedCloseoutSettings:
    authority_map: Path
    backend_port: int
    frontend_port: int
    duration_seconds: float = DEFAULT_DURATION_SECONDS
    restart_cycle_count: int = MIN_ACTUAL_BACKEND_RESTARTS
    user_count: int = MIN_USERS
    project_count: int = MIN_PROJECTS
    catalog_version_count: int = MIN_CATALOG_VERSIONS
    bounded_operation_count: int = MIN_BOUNDED_OPERATIONS
    crosswalk_preview_count: int = MIN_CROSSWALK_PREVIEWS
    decision_write_count: int = MIN_DECISION_WRITES
    service_reload_count: int = MIN_SERVICE_RELOADS
    unauthorized_attempt_count: int = 250
    conflict_trial_count: int = 25
    max_workers: int = MIN_USERS
    heartbeat_seconds: float = 60.0
    headed_browser: bool = True
    enforce_release_minimums: bool = True

    def validate(
        self,
        *,
        port_reservations: ReservedLoopbackPorts | None = None,
    ) -> None:
        if port_reservations is None:
            _assert_ports(self.backend_port, self.frontend_port)
        else:
            _assert_ports(
                self.backend_port,
                self.frontend_port,
                reservations=port_reservations,
            )
        if self.duration_seconds <= 0:
            raise IntegratedCloseoutError("The integrated soak duration must be positive.")
        if self.restart_cycle_count < 1:
            raise IntegratedCloseoutError("At least one actual backend restart is required.")
        if self.enforce_release_minimums:
            minimums = {
                "duration_seconds": (self.duration_seconds, DEFAULT_DURATION_SECONDS),
                "restart_cycle_count": (
                    self.restart_cycle_count,
                    MIN_ACTUAL_BACKEND_RESTARTS,
                ),
                "user_count": (self.user_count, MIN_USERS),
                "project_count": (self.project_count, MIN_PROJECTS),
                "catalog_version_count": (
                    self.catalog_version_count,
                    MIN_CATALOG_VERSIONS,
                ),
                "bounded_operation_count": (
                    self.bounded_operation_count,
                    MIN_BOUNDED_OPERATIONS,
                ),
                "crosswalk_preview_count": (
                    self.crosswalk_preview_count,
                    MIN_CROSSWALK_PREVIEWS,
                ),
                "decision_write_count": (
                    self.decision_write_count,
                    MIN_DECISION_WRITES,
                ),
                "service_reload_count": (
                    self.service_reload_count,
                    MIN_SERVICE_RELOADS,
                ),
                "max_workers": (self.max_workers, MIN_USERS),
            }
            below = [
                f"{name}={actual} (minimum {minimum})"
                for name, (actual, minimum) in minimums.items()
                if actual < minimum
            ]
            if below or self.headed_browser is not True:
                detail = "; ".join(below) or "headed_browser=false"
                raise IntegratedCloseoutError(
                    "Integrated release minimums are not satisfied: " + detail
                )


class _ProgressEvidence:
    def __init__(self, path: Path, run_id: str, started: float) -> None:
        self.path = path
        self.run_id = run_id
        self.started = started
        self.lock = threading.RLock()
        self.count = 0

    def append(self, event: str, **values: Any) -> None:
        row = {
            "schema_version": "1.0",
            "classification": "synthetic_integrated_closeout_progress",
            "run_id": self.run_id,
            "event": event,
            "recorded_at": _utc_now(),
            "elapsed_seconds": round(time.monotonic() - self.started, 6),
            **values,
        }
        row["event_checksum"] = _checksum(row)
        encoded = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
        with self.lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
            self.count += 1


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        return probe.connect_ex(("127.0.0.1", int(port))) == 0


def _listener_pids(port: int) -> set[int]:
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
                text=True,
                errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise IntegratedCloseoutError(
                "Listener PID verification was unavailable."
            ) from exc
        if completed.returncode != 0:
            raise IntegratedCloseoutError("Listener PID verification was unavailable.")
        listeners: set[int] = set()
        for line in completed.stdout.splitlines():
            fields = line.split()
            if len(fields) != 5 or fields[0].upper() != "TCP":
                continue
            if fields[3].upper() != "LISTENING":
                continue
            try:
                local_port = int(fields[1].rsplit(":", 1)[1])
                pid = int(fields[4])
            except (IndexError, ValueError):
                continue
            if local_port == int(port):
                listeners.add(pid)
        return listeners
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - release environment contract
        raise IntegratedCloseoutError(
            "Listener PID verification requires the bounded psutil runtime dependency."
        ) from exc
    listeners: set[int] = set()
    try:
        connections = psutil.net_connections(kind="tcp")
    except Exception as exc:  # pragma: no cover - platform permission failure
        raise IntegratedCloseoutError("Listener PID verification was unavailable.") from exc
    for connection in connections:
        local = connection.laddr
        local_port = getattr(local, "port", local[1] if local else None)
        if (
            local_port == int(port)
            and str(connection.status).upper() == "LISTEN"
            and connection.pid is not None
        ):
            listeners.add(int(connection.pid))
    return listeners


def _owned_process_pids(process: subprocess.Popen[bytes]) -> set[int]:
    """Return the launcher and every currently live descendant PID."""

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            unsigned_pointer = (
                ctypes.c_ulonglong
                if ctypes.sizeof(ctypes.c_void_p) == 8
                else ctypes.c_ulong
            )

            class ProcessEntry32W(ctypes.Structure):
                _fields_ = (
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", unsigned_pointer),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260),
                )

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
            kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            kernel32.Process32FirstW.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(ProcessEntry32W),
            )
            kernel32.Process32FirstW.restype = wintypes.BOOL
            kernel32.Process32NextW.argtypes = (
                wintypes.HANDLE,
                ctypes.POINTER(ProcessEntry32W),
            )
            kernel32.Process32NextW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
            if snapshot == wintypes.HANDLE(-1).value:
                raise OSError(ctypes.get_last_error(), "Process snapshot unavailable")
            parent_by_pid: dict[int, int] = {}
            try:
                entry = ProcessEntry32W()
                entry.dwSize = ctypes.sizeof(entry)
                present = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
                while present:
                    parent_by_pid[int(entry.th32ProcessID)] = int(
                        entry.th32ParentProcessID
                    )
                    present = bool(kernel32.Process32NextW(snapshot, ctypes.byref(entry)))
            finally:
                kernel32.CloseHandle(snapshot)
        except Exception as exc:  # pragma: no cover - platform API failure
            raise IntegratedCloseoutError(
                "Listener process-tree verification was unavailable."
            ) from exc
    else:
        try:
            import psutil  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - release environment contract
            raise IntegratedCloseoutError(
                "Listener ownership verification requires the bounded psutil runtime dependency."
            ) from exc
        try:
            parent_by_pid = {}
            for candidate in psutil.process_iter(attrs=("pid", "ppid")):
                try:
                    pid = int(candidate.info["pid"])
                    parent_by_pid[pid] = int(candidate.info["ppid"])
                except (
                    KeyError,
                    TypeError,
                    ValueError,
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                ):
                    continue
        except Exception as exc:  # pragma: no cover - platform enumeration failure
            raise IntegratedCloseoutError(
                "Listener process-tree verification was unavailable."
            ) from exc

    owned = {int(process.pid)}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in parent_by_pid.items():
            if pid not in owned and parent_pid in owned:
                owned.add(pid)
                changed = True
    return owned


def _stop_owned_process_tree(process: subprocess.Popen[bytes] | None) -> None:
    """Stop only the exact subprocess tree launched by this orchestrator."""

    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(int(process.pid)), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        return

    psutil_module: Any = None
    try:
        import psutil as psutil_module  # type: ignore[import-not-found]

        descendant_pids = _owned_process_pids(process) - {int(process.pid)}
        descendants = []
        for pid in descendant_pids:
            try:
                descendants.append(psutil_module.Process(pid))
            except psutil_module.NoSuchProcess:
                continue
    except Exception:
        descendants = []
    for child in reversed(descendants):
        try:
            child.terminate()
        except Exception:
            pass
    _stop_process(process)
    if descendants and psutil_module is not None:
        _gone, survivors = psutil_module.wait_procs(descendants, timeout=10)
        for survivor in survivors:
            try:
                survivor.kill()
            except Exception:
                pass
        psutil_module.wait_procs(survivors, timeout=10)


def _wait_for_exact_listener(
    process: subprocess.Popen[bytes], port: int, *, timeout: float = 30.0
) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise IntegratedCloseoutError(
                "An isolated process exited before listener verification."
            )
        listeners = _listener_pids(port)
        owned_pids = _owned_process_pids(process)
        if len(listeners) == 1 and listeners.issubset(owned_pids) and _port_is_open(port):
            return next(iter(listeners))
        if listeners - owned_pids:
            raise IntegratedCloseoutError(
                "An isolated port was owned by an unexpected listener process."
            )
        if len(listeners) > 1:
            raise IntegratedCloseoutError(
                "An isolated port had more than one owned listener process."
            )
        time.sleep(0.1)
    raise IntegratedCloseoutError("The isolated listener PID could not be verified.")


def _wait_for_port_closed(port: int, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_is_open(port) and not _listener_pids(port):
            return
        time.sleep(0.1)
    raise IntegratedCloseoutError("An isolated listener port did not close.")


def _request_json(
    origin: str,
    path: str,
    *,
    run_id: str,
    expected_status: int = 200,
) -> Mapping[str, Any]:
    request = Request(
        origin + path,
        headers={
            "Accept": "application/json",
            "X-Synthetic-Principal": ADMIN_PRINCIPAL,
            "X-Synthetic-Role": "admin",
            "X-Synthetic-Tenant": TENANT_ID,
            "X-Synthetic-Run-Id": run_id,
            "X-Synthetic-Probe": (
                "health" if path == "/health" else "orchestrator"
            ),
        },
    )
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
            body = response.read()
    except HTTPError as exc:
        status = exc.code
        body = exc.read()
    except (URLError, TimeoutError) as exc:
        raise IntegratedCloseoutError("An isolated recovery request failed.") from exc
    if status != expected_status:
        raise IntegratedCloseoutError("An isolated recovery request returned an unexpected status.")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegratedCloseoutError("An isolated recovery response was invalid.") from exc
    if not isinstance(payload, Mapping):
        raise IntegratedCloseoutError("An isolated recovery response was not bounded JSON.")
    return payload


def _wait_for_guarded_health(
    process: subprocess.Popen[bytes],
    *,
    backend_port: int,
    run_id: str,
    timeout: float = 60.0,
) -> None:
    deadline = time.monotonic() + timeout
    origin = f"http://127.0.0.1:{backend_port}"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise IntegratedCloseoutError("The isolated backend exited before readiness.")
        try:
            payload = _request_json(origin, "/health", run_id=run_id)
            if payload.get("ok") is True:
                return
        except IntegratedCloseoutError:
            pass
        time.sleep(0.1)
    raise IntegratedCloseoutError("The isolated backend did not become healthy.")


def _start_backend_cycle(
    environment_pins: Mapping[str, str],
    logs_root: Path,
    port: int,
    *,
    cycle: int,
) -> subprocess.Popen[bytes]:
    cycle_root = logs_root / f"backend-listener-{cycle:02d}"
    cycle_root.mkdir(parents=False, exist_ok=False)
    environment = _clean_subprocess_environment()
    environment.update(environment_pins)
    log = (cycle_root / "isolated-backend.log").open("xb")
    try:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.bureau_metadata_integration_runtime_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log.close()


def _initialize_catalogs_without_global_patch(
    restricted_root: Path,
    registry_root: Path,
) -> Mapping[str, Mapping[str, Any]]:
    original = catalog_registry.validate_restricted_metadata_root
    try:
        return _initialize_synthetic_authority(restricted_root, registry_root)
    finally:
        catalog_registry.validate_restricted_metadata_root = original


def _grant_integration_entitlements(
    scopes: Mapping[str, Path],
    versions: Mapping[str, Mapping[str, Any]],
) -> None:
    """Grant only the synthetic project principals required by scenarios A/B/D/E."""

    original = catalog_registry.validate_restricted_metadata_root
    permitted = {
        scopes["restricted-catalog"].resolve(strict=True),
        scopes["catalog-registry"].resolve(strict=True),
    }

    def validate(root: object, **_kwargs: Any) -> Path:
        candidate = Path(str(root or "")).resolve(strict=True)
        if candidate not in permitted:
            raise IntegratedCloseoutError(
                "An integration entitlement operation escaped its isolated roots."
            )
        return candidate

    try:
        catalog_registry.validate_restricted_metadata_root = validate
        registry = CatalogRegistry(
            scopes["restricted-catalog"],
            repository_root=REPOSITORY_ROOT,
            registry_root=scopes["catalog-registry"],
        )
        for version in versions.values():
            catalog_version_id = str(version["catalog_version_id"])
            for principal in INTEGRATION_ENTITLED_PRINCIPALS:
                registry.grant_entitlement(
                    principal_id=principal,
                    tenant_id=TENANT_ID,
                    catalog_version_id=catalog_version_id,
                    operations=ALL_OPERATIONS,
                    granted_by=ADMIN_PRINCIPAL,
                )
    finally:
        catalog_registry.validate_restricted_metadata_root = original


def _create_crosswalk_fixture(
    scopes: Mapping[str, Path],
    *,
    run_id: str,
    catalog_version_id: str,
) -> Mapping[str, Any]:
    registry = CatalogRegistry(
        scopes["restricted-catalog"],
        repository_root=REPOSITORY_ROOT,
        registry_root=scopes["catalog-registry"],
    )
    catalog = registry.get_version(catalog_version_id)
    catalog_key = BureauCatalogKey(
        provider=catalog.provider_name,
        product=catalog.product_name,
        edition=catalog.edition,
        dictionary_version=catalog.source_release_version,
    )
    lineage = CrosswalkLineage(
        project_id=SYNTHETIC_PROJECTS[0]["project_id"],
        dataset_id=SYNTHETIC_PROJECTS[0]["dataset_id"],
        dataset_version_id=SYNTHETIC_PROJECTS[0]["dataset_version_id"],
        activation_revision=1,
        target_contract_id="synthetic-target-contract",
        predictor_authorization_id="synthetic-predictor-authorization",
        schema_checksum=_checksum({"run_id": run_id, "schema": ["SYN000"]}),
        catalog_key=catalog_key,
        catalog_checksum=catalog.normalized_catalog_checksum,
    )
    created_at = _utc_now()
    evidence = tuple(
        CrosswalkEvidenceReference(
            evidence_id=f"synthetic-restart-evidence-{kind}",
            evidence_kind=kind,  # type: ignore[arg-type]
            authority_id="synthetic-integrated-closeout",
            checksum=_checksum({"run_id": run_id, "evidence": kind}),
            created_by=ADMIN_PRINCIPAL,
            created_at=created_at,
        )
        for kind in ("catalog_definition", "exact_match", "analyst_review")
    )
    decision = GovernedMappingDecision(
        dataset_field="SYN000",
        mapping_state="exact_verified",
        candidate_attribute_code="SYN000",
        evidence=evidence,
        analyst_confirmed=True,
        rationale="Synthetic exact-identity restart evidence.",
        reviewer_id=ADMIN_PRINCIPAL,
    )
    source_id = "synthetic-restart-source"
    governance_id = governance_identity(lineage, source_id)
    revision = build_governed_revision(
        governance_id=governance_id,
        revision=1,
        lifecycle_state="confirmed",
        lineage=lineage,
        source_crosswalk_id=source_id,
        source_crosswalk_checksum=_checksum(
            {"run_id": run_id, "source_crosswalk_id": source_id}
        ),
        decisions=(decision,),
        audit=CrosswalkAuditMetadata(
            actor_id=ADMIN_PRINCIPAL,
            request_id="synthetic-restart-request",
            occurred_at=created_at,
            reason="Create bounded synthetic restart-recovery evidence.",
        ),
    )
    repository = SQLiteGovernedCrosswalkRepository(
        scopes["restricted-catalog"],
        repository_root=REPOSITORY_ROOT,
    )
    repository.append(revision, expected_revision=0)
    return {
        "run_id": run_id,
        "governance_id": governance_id,
        "revision": revision.revision,
        "revision_checksum": revision.revision_checksum,
        "catalog_version_id": catalog.catalog_version_id,
        "catalog_checksum": catalog.normalized_catalog_checksum,
    }


def _run_integration_browser_phase(
    scopes: Mapping[str, Path],
    *,
    base: Path,
    run_id: str,
    phase: str,
    backend_port: int,
    frontend_port: int,
    catalog_version_id: str,
    reload_attempts: int,
    headed: bool,
    violation_path: Path,
    abort_check: Callable[[], None] | None = None,
) -> Mapping[str, Any]:
    phase_output = scopes["test-output"] / f"browser-{phase}-integration"
    phase_profile = scopes["browser-profile"] / f"browser-{phase}-integration"
    phase_downloads = scopes["browser-downloads"] / f"browser-{phase}-integration"
    for directory in (phase_output, phase_profile, phase_downloads):
        directory.mkdir(parents=False, exist_ok=False)
    profile_cli_path = _browser_profile_cli_path(phase_profile)
    command = [
        "node",
        "tests/bureauMetadataIntegration.production.acceptance.mjs",
        "--frontend-url",
        f"http://127.0.0.1:{frontend_port}",
        "--backend-url",
        f"http://127.0.0.1:{backend_port}",
        "--output-directory",
        str(phase_output),
        "--browser-profile-directory",
        str(profile_cli_path),
        "--downloads-directory",
        str(phase_downloads),
        "--expected-version-id",
        catalog_version_id,
        "--synthetic-run-id",
        run_id,
        "--network-violation-file",
        str(violation_path),
        "--reload-attempts",
        str(reload_attempts),
    ]
    if headed:
        command.append("--headed")
    environment = _clean_subprocess_environment()
    environment.update(
        {
            "TEMP": str(scopes["temporary-files"]),
            "TMP": str(scopes["temporary-files"]),
            "ATLAS_BROWSER_STORAGE_ROOT": str(phase_profile),
            "ATLAS_PLAYWRIGHT_OUTPUT_ROOT": str(phase_output),
        }
    )
    stdout_path = scopes["logs"] / f"browser-{phase}-integration.stdout.log"
    stderr_path = scopes["logs"] / f"browser-{phase}-integration.stderr.log"
    with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    deadline = time.monotonic() + 900
    try:
        while process.poll() is None:
            if violation_path.exists():
                raise IntegratedCloseoutError(
                    "A non-orchestrated client contacted the isolated backend."
                )
            if abort_check is not None:
                abort_check()
            if time.monotonic() >= deadline:
                raise IntegratedCloseoutError(
                    "The Data Acquisition integration browser phase timed out."
                )
            time.sleep(0.1)
    except BaseException:
        _stop_owned_process_tree(process)
        raise
    if process.returncode != 0:
        raise IntegratedCloseoutError(
            "The Data Acquisition integration production-browser phase failed."
        )
    try:
        result = json.loads(stdout_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegratedCloseoutError(
            "Data Acquisition integration browser evidence was invalid."
        ) from exc
    if (
        not isinstance(result, Mapping)
        or result.get("ok") is not True
        or result.get("synthetic_run_id") != run_id
        or result.get("canonical_eda_handoff_verified") is not True
        or result.get("final_holdout_accessed") is not False
        or result.get("training_started") is not False
    ):
        raise IntegratedCloseoutError(
            "Data Acquisition integration browser evidence did not pass."
        )
    network = result.get("network_contact_guard")
    if not isinstance(network, Mapping) or any(
        int(network.get(field, -1)) != 0
        for field in (
            "unexpected_fetch_xhr_count",
            "websocket_count",
            "blocked_request_count",
            "live_port_contact_count",
        )
    ):
        raise IntegratedCloseoutError(
            "The Data Acquisition integration browser contacted a prohibited origin."
        )
    if int(network.get("fetch_xhr_count", 0)) != int(
        network.get("isolated_backend_fetch_xhr_count", -1)
    ):
        raise IntegratedCloseoutError(
            "Data Acquisition integration network evidence is contradictory."
        )
    return dict(result)


def _run_browser_phase(
    scopes: Mapping[str, Path],
    *,
    base: Path,
    run_id: str,
    phase: str,
    backend_port: int,
    frontend_port: int,
    catalog_version_id: str,
    secondary_catalog_version_id: str,
    headed: bool,
    violation_path: Path,
    abort_check: Callable[[], None] | None = None,
) -> Mapping[str, Any]:
    try:
        reload_plan = BROWSER_PHASE_RELOAD_PLANS[phase]
    except KeyError as exc:
        raise IntegratedCloseoutError(
            "Authenticated browser phase has no bounded reload plan."
        ) from exc
    phase_output = scopes["test-output"] / f"browser-{phase}"
    phase_profile = scopes["browser-profile"] / f"browser-{phase}"
    phase_downloads = scopes["browser-downloads"] / f"browser-{phase}"
    for directory in (phase_output, phase_profile, phase_downloads):
        directory.mkdir(parents=False, exist_ok=False)
    profile_cli_path = _browser_profile_cli_path(phase_profile)
    command = [
        "node",
        "tests/bureauCatalogAdmin.productionAuth.acceptance.mjs",
        "--frontend-url",
        f"http://127.0.0.1:{frontend_port}",
        "--backend-url",
        f"http://127.0.0.1:{backend_port}",
        "--output-directory",
        str(phase_output),
        "--browser-profile-directory",
        str(profile_cli_path),
        "--downloads-directory",
        str(phase_downloads),
        "--expected-version-id",
        catalog_version_id,
        "--expected-secondary-version-id",
        secondary_catalog_version_id,
        "--project-alpha-id",
        SYNTHETIC_PROJECTS[0]["project_id"],
        "--project-alpha-dataset-id",
        SYNTHETIC_PROJECTS[0]["dataset_id"],
        "--project-alpha-dataset-version-id",
        SYNTHETIC_PROJECTS[0]["dataset_version_id"],
        "--project-beta-id",
        SYNTHETIC_PROJECTS[1]["project_id"],
        "--project-beta-dataset-id",
        SYNTHETIC_PROJECTS[1]["dataset_id"],
        "--project-beta-dataset-version-id",
        SYNTHETIC_PROJECTS[1]["dataset_version_id"],
        "--forbidden-path-fragment",
        str(base),
        "--synthetic-run-id",
        run_id,
        "--network-violation-file",
        str(violation_path),
        "--authenticated-reload-attempts",
        str(reload_plan.admin_reload_attempts),
        "--project-reload-attempts",
        str(reload_plan.project_reload_attempts_per_project),
    ]
    if headed:
        command.append("--headed")
    environment = _clean_subprocess_environment()
    environment.update(
        {
            "TEMP": str(scopes["temporary-files"]),
            "TMP": str(scopes["temporary-files"]),
            "ATLAS_BROWSER_STORAGE_ROOT": str(phase_profile),
            "ATLAS_PLAYWRIGHT_OUTPUT_ROOT": str(phase_output),
        }
    )
    started_at = _utc_now()
    stdout_path = scopes["logs"] / f"browser-{phase}.stdout.log"
    stderr_path = scopes["logs"] / f"browser-{phase}.stderr.log"
    stdout_handle = stdout_path.open("xb")
    stderr_handle = stderr_path.open("xb")
    try:
        process = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    deadline = time.monotonic() + 900
    try:
        while process.poll() is None:
            if violation_path.exists():
                raise IntegratedCloseoutError(
                    "A non-orchestrated client contacted the isolated backend."
                )
            if abort_check is not None:
                abort_check()
            if time.monotonic() >= deadline:
                raise IntegratedCloseoutError("An authenticated browser phase timed out.")
            time.sleep(0.1)
    except BaseException:
        _stop_owned_process_tree(process)
        raise
    if process.returncode != 0:
        raise IntegratedCloseoutError("An authenticated production-browser phase failed.")
    stdout = stdout_path.read_bytes()
    try:
        result = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegratedCloseoutError("Authenticated browser evidence was invalid.") from exc
    if not isinstance(result, Mapping) or result.get("ok") is not True:
        raise IntegratedCloseoutError("Authenticated browser evidence did not pass.")
    if result.get("synthetic_run_id") != run_id:
        raise IntegratedCloseoutError(
            "Authenticated browser evidence was not tied to the current run."
        )
    network = result.get("network_contact_guard")
    if not isinstance(network, Mapping) or any(
        int(network.get(field, -1)) != 0
        for field in (
            "unexpected_fetch_xhr_count",
            "websocket_count",
            "blocked_request_count",
            "live_port_contact_count",
        )
    ):
        raise IntegratedCloseoutError("The production browser contacted a prohibited origin.")
    if int(network.get("fetch_xhr_count", 0)) != int(
        network.get("isolated_backend_fetch_xhr_count", -1)
    ):
        raise IntegratedCloseoutError("The production browser network evidence is contradictory.")
    integration = _run_integration_browser_phase(
        scopes,
        base=base,
        run_id=run_id,
        phase=phase,
        backend_port=backend_port,
        frontend_port=frontend_port,
        catalog_version_id=catalog_version_id,
        reload_attempts=reload_plan.integration_reload_attempts,
        headed=headed,
        violation_path=violation_path,
        abort_check=abort_check,
    )
    integration_network = integration["network_contact_guard"]
    combined_network = {
        field: int(network.get(field, 0)) + int(integration_network.get(field, 0))
        for field in (
            "fetch_xhr_count",
            "isolated_backend_fetch_xhr_count",
            "unexpected_fetch_xhr_count",
            "websocket_count",
            "blocked_request_count",
            "live_port_contact_count",
        )
    }
    phase_result = {
        "phase": phase,
        "run_id": run_id,
        "setup_only": phase == "initial",
        "inside_operational_window": phase == "timed-window",
        "started_at": started_at,
        "completed_at": _utc_now(),
        "headed_browser": bool(result.get("headed_browser")),
        "authenticated_reload_attempts": int(result["authenticated_reload_attempts"])
        + int(integration["authenticated_reload_attempts"]),
        "authenticated_reload_successes": int(result["authenticated_reload_successes"])
        + int(integration["authenticated_reload_successes"]),
        "synthetic_user_count": max(
            int(result["authenticated_user_count"]),
            int(integration["synthetic_user_count"]),
        ),
        "synthetic_project_count": max(
            int(result["authenticated_project_count"]),
            int(integration["synthetic_project_count"]),
        ),
        "synthetic_provider_count": max(
            int(result["authenticated_provider_count"]),
            int(integration["synthetic_provider_count"]),
        ),
        "cross_user_contamination": int(result["cross_user_contamination"])
        + int(integration["cross_user_contamination"]),
        "cross_project_contamination": int(result["cross_project_contamination"])
        + int(integration["cross_project_contamination"]),
        "cross_provider_contamination": int(result["cross_provider_contamination"])
        + int(integration["cross_provider_contamination"]),
        "network_contact_guard": combined_network,
        "screenshot_authority": "test-output",
        "screenshot_scope": phase_output.name,
        "screenshot_files": list(result.get("screenshot_files") or ())
        + list(integration.get("screenshot_files") or ()),
        "integration_screenshot_scope": f"browser-{phase}-integration",
        "project_scenarios": list(integration.get("project_scenarios") or ()),
        "canonical_eda_handoff_verified": True,
        "final_holdout_accessed": False,
        "training_started": False,
    }
    if (
        phase_result["authenticated_reload_attempts"]
        != reload_plan.expected_authenticated_reloads
    ):
        raise IntegratedCloseoutError(
            "Authenticated browser phase did not execute its exact reload plan."
        )
    return phase_result


def _write_reload_evidence(
    path: Path,
    *,
    run_id: str,
    frontend_port: int,
    backend_port: int,
    phases: Sequence[Mapping[str, Any]],
    allowed_evidence_root: Path,
) -> Mapping[str, Any]:
    if not phases or any(phase.get("run_id") != run_id for phase in phases):
        raise IntegratedCloseoutError(
            "Frontend reload phases were not tied to the current integrated run."
        )
    attempts, successes = _reload_totals(phases)
    payload: dict[str, Any] = {
        "schema_version": "1.0",
        "classification": FRONTEND_RELOAD_EVIDENCE_CLASSIFICATION,
        "run_id": run_id,
        "created_at": _utc_now(),
        "frontend_origin": f"http://127.0.0.1:{frontend_port}",
        "backend_origin": f"http://127.0.0.1:{backend_port}",
        "authenticated_reload_attempts": attempts,
        "authenticated_reload_successes": successes,
        "synthetic_user_count": min(int(phase["synthetic_user_count"]) for phase in phases),
        "synthetic_project_count": min(
            int(phase["synthetic_project_count"]) for phase in phases
        ),
        "synthetic_provider_count": min(
            int(phase["synthetic_provider_count"]) for phase in phases
        ),
        "authentication_failures": 0,
        "unexpected_failures": 0,
        "cross_user_contamination": sum(
            int(phase["cross_user_contamination"]) for phase in phases
        ),
        "cross_project_contamination": sum(
            int(phase["cross_project_contamination"]) for phase in phases
        ),
        "cross_provider_contamination": sum(
            int(phase["cross_provider_contamination"]) for phase in phases
        ),
        "browser_profile_isolated": True,
        "contains_vendor_content": False,
        "live_authority_accessed": False,
        "live_port_contacted": False,
    }
    payload["evidence_checksum"] = _frontend_reload_evidence_checksum(payload)
    path.write_bytes(canonical_json_bytes(payload))
    _load_frontend_reload_evidence(
        path,
        minimum_reloads=MIN_FRONTEND_AUTHENTICATED_RELOADS,
        allowed_evidence_root=allowed_evidence_root,
    )
    return payload


def _reload_totals(
    phases: Sequence[Mapping[str, Any]],
    *,
    inside_operational_window_only: bool = False,
) -> tuple[int, int]:
    selected = (
        phase
        for phase in phases
        if not inside_operational_window_only
        or phase.get("inside_operational_window") is True
    )
    attempts = 0
    successes = 0
    for phase in selected:
        attempts += int(phase["authenticated_reload_attempts"])
        successes += int(phase["authenticated_reload_successes"])
    return attempts, successes


def _load_integration_event_counts(path: Path) -> Mapping[str, Any]:
    categories: dict[str, int] = {}
    statuses: dict[str, int] = {}
    total = 0
    if not path.is_file():
        raise IntegratedCloseoutError(
            "The Data Acquisition integration event evidence is unavailable."
        )
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IntegratedCloseoutError(
                "The Data Acquisition integration event evidence is invalid."
            ) from exc
        if (
            not isinstance(row, Mapping)
            or row.get("classification")
            != "synthetic_bureau_metadata_integration_event"
        ):
            raise IntegratedCloseoutError(
                "The Data Acquisition integration event evidence is contradictory."
            )
        category = str(row.get("category") or "other")
        status = str(int(row.get("status") or 0))
        categories[category] = categories.get(category, 0) + 1
        statuses[status] = statuses.get(status, 0) + 1
        total += 1
    required = {
        "binding_preview": 1,
        "crosswalk_preview": 1,
        "decision_write": 1,
        "binding_link_retry": 1,
        "semantic_batch": 1,
        "catalog_search_or_lookup": 1,
        "entitlement_revoke": 1,
    }
    missing = [
        name for name, minimum in required.items()
        if categories.get(name, 0) < minimum
    ]
    if missing or int(statuses.get("409", 0)) < 1 or int(statuses.get("422", 0)) < 1:
        raise IntegratedCloseoutError(
            "The Data Acquisition integration event matrix is incomplete."
        )
    payload = {
        "total_events": total,
        "categories": dict(sorted(categories.items())),
        "http_statuses": dict(sorted(statuses.items())),
        "required_categories_present": True,
        "conflict_count": int(statuses.get("409", 0)),
        "malformed_count": int(statuses.get("422", 0)),
    }
    payload["evidence_checksum"] = _checksum(payload)
    return payload


def _runtime_metric_delta(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> Mapping[str, Any]:
    def delta(name: str) -> int | None:
        left = before.get(name)
        right = after.get(name)
        if isinstance(left, int) and isinstance(right, int):
            return right - left
        return None

    return {
        "before": dict(before),
        "after": dict(after),
        "rss_delta_bytes": delta("rss_bytes"),
        "handle_delta": delta("handles"),
        "reported_unavailable_not_zero": (
            before.get("available") is not True or after.get("available") is not True
        ),
    }


def _validate_exact_recovery(
    payload: Mapping[str, Any], expected: Mapping[str, Any]
) -> Mapping[str, Any]:
    catalog = payload.get("catalog")
    entitlement = payload.get("entitlement")
    crosswalk = payload.get("crosswalk")
    if (
        payload.get("ok") is not True
        or payload.get("run_id") != expected["run_id"]
        or payload.get("no_first_or_latest_fallback") is not True
        or not isinstance(catalog, Mapping)
        or not isinstance(entitlement, Mapping)
        or not isinstance(crosswalk, Mapping)
        or catalog.get("catalog_version_id") != expected["catalog_version_id"]
        or catalog.get("catalog_checksum") != expected["catalog_checksum"]
        or catalog.get("integrity_status") != "verified"
        or catalog.get("exact_identity_verified") is not True
        or entitlement.get("catalog_health_verified") is not True
        or entitlement.get("crosswalk_candidate_verified") is not True
        or crosswalk.get("governance_id") != expected["governance_id"]
        or int(crosswalk.get("revision") or 0) != int(expected["revision"])
        or crosswalk.get("revision_checksum") != expected["revision_checksum"]
        or crosswalk.get("checksum_verified") is not True
    ):
        raise IntegratedCloseoutError("Exact restart recovery evidence was contradictory.")
    return {
        "http_status": 200,
        "exact_catalog_recovered": True,
        "catalog_integrity_verified": True,
        "catalog_entitlement_verified": True,
        "crosswalk_entitlement_verified": True,
        "exact_crosswalk_recovered": True,
        "crosswalk_checksum_verified": True,
        "no_first_or_latest_fallback": True,
    }


def _restart_schedule(duration_seconds: float, cycle_count: int) -> tuple[float, ...]:
    if duration_seconds <= 0 or cycle_count < 1:
        raise IntegratedCloseoutError("The restart schedule is invalid.")
    interval = duration_seconds / (cycle_count + 1)
    return tuple(interval * number for number in range(1, cycle_count + 1))


def _resolve_operational_authority_map(
    configured_map: Path,
    *,
    isolated_base: Path,
) -> Path:
    """Resolve and verify the canonical in-base map used by the soak worker."""

    try:
        configured = Path(configured_map).expanduser().resolve(strict=True)
        base = Path(isolated_base).expanduser().resolve(strict=True)
    except OSError as exc:
        raise IntegratedCloseoutError(
            "The configured authority-map identity is unavailable."
        ) from exc
    if not configured.is_file() or not base.is_dir():
        raise IntegratedCloseoutError(
            "The configured authority-map identity is unavailable."
        )

    candidate = base / configured.name
    if candidate.parent != base or not candidate.is_file():
        raise IntegratedCloseoutError(
            "The canonical in-base authority map is unavailable."
        )
    try:
        canonical = candidate.resolve(strict=True)
    except OSError as exc:
        raise IntegratedCloseoutError(
            "The canonical in-base authority map is unavailable."
        ) from exc
    if canonical.parent != base or not canonical.is_file():
        raise IntegratedCloseoutError(
            "The canonical authority map is not directly under its isolated base."
        )

    try:
        configured_bytes = configured.read_bytes()
        canonical_bytes = canonical.read_bytes()
    except OSError as exc:
        raise IntegratedCloseoutError(
            "Authority-map comparison evidence is unavailable."
        ) from exc
    configured_checksum = hashlib.sha256(configured_bytes).hexdigest()
    canonical_checksum = hashlib.sha256(canonical_bytes).hexdigest()
    if (
        canonical_bytes != configured_bytes
        or canonical_checksum != configured_checksum
    ):
        raise IntegratedCloseoutError(
            "The canonical in-base authority map does not match the configured safety copy."
        )

    try:
        operational_paths = _load_soak_authority_map(canonical)
    except (OSError, SoakConfigurationError) as exc:
        raise IntegratedCloseoutError(
            "The canonical in-base authority map failed operational validation."
        ) from exc
    if operational_paths.authority_map_checksum != canonical_checksum:
        raise IntegratedCloseoutError(
            "The canonical in-base authority-map checksum is contradictory."
        )
    return canonical


def _soak_settings(
    settings: IntegratedCloseoutSettings,
    reload_evidence: Path,
    *,
    authority_map: Path,
) -> SoakSettings:
    return SoakSettings(
        authority_map=authority_map,
        duration_seconds=settings.duration_seconds,
        user_count=settings.user_count,
        project_count=settings.project_count,
        catalog_version_count=settings.catalog_version_count,
        bounded_operation_count=settings.bounded_operation_count,
        crosswalk_preview_count=settings.crosswalk_preview_count,
        decision_write_count=settings.decision_write_count,
        service_reload_count=settings.service_reload_count,
        unauthorized_attempt_count=settings.unauthorized_attempt_count,
        conflict_trial_count=settings.conflict_trial_count,
        max_workers=settings.max_workers,
        heartbeat_seconds=settings.heartbeat_seconds,
        enforce_release_minimums=settings.enforce_release_minimums,
        frontend_reload_evidence=reload_evidence,
        frontend_authenticated_reload_minimum=MIN_FRONTEND_AUTHENTICATED_RELOADS,
    )


def _operational_worker(
    settings: SoakSettings,
    output: Any,
) -> None:
    """Run the workload in a terminable isolated child and emit bounded facts."""

    def report(payload: Mapping[str, Any]) -> None:
        output.put(
            {
                "kind": "progress",
                "elapsed_seconds": float(payload.get("elapsed_seconds") or 0),
                "total_requests": int(payload.get("total_requests") or 0),
                "unexpected_failures": int(payload.get("unexpected_failures") or 0),
            }
        )

    try:
        summary = run_soak(settings, progress=report)
    except BaseException as exc:
        output.put({"kind": "failure", "failure_type": type(exc).__name__})
        return
    output.put({"kind": "result", "summary": dict(summary)})


def _run_integrated_closeout_with_ports(
    settings: IntegratedCloseoutSettings,
    *,
    port_reservations: ReservedLoopbackPorts | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    settings.validate(port_reservations=port_reservations)
    if port_reservations is None and (
        _port_is_open(settings.backend_port) or _port_is_open(settings.frontend_port)
    ):
        raise IntegratedCloseoutError("An isolated closeout port is already in use.")
    base, mapped_roots = _load_authority_map(settings.authority_map)
    operational_authority_map = _resolve_operational_authority_map(
        settings.authority_map,
        isolated_base=base,
    )
    run_id, scopes = _create_run_scopes(mapped_roots)
    scope_names = {path.name for path in scopes.values()}
    if len(scopes) != len(REQUIRED_AUTHORITIES) or len(scope_names) != 1:
        raise IntegratedCloseoutError("The unique 21-authority run scope is contradictory.")
    authority_scope_id = next(iter(scope_names))
    started_at = _utc_now()
    wall_started = time.monotonic()
    progress = _ProgressEvidence(scopes["test-output"] / PROGRESS_FILE, run_id, wall_started)
    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None
    operational_process: multiprocessing.Process | None = None
    operational_queue: Any = None
    initial_pid = 0
    listener_pids_seen: set[int] = set()
    restart_cycles: list[Mapping[str, Any]] = []
    browser_phases: list[Mapping[str, Any]] = []
    production_build: Mapping[str, Any] = {}
    operational_summary: Mapping[str, Any] = {}
    failure_type: str | None = None
    teardown_ports_closed = False
    violation_path = scopes["logs"] / VIOLATION_FILE
    expected_recovery: Mapping[str, Any] = {}
    initial_reload_evidence: Mapping[str, Any] = {}
    combined_reload_evidence: Mapping[str, Any] = {}
    soak_window_started_at: str | None = None
    soak_window_completed_at: str | None = None
    soak_window_elapsed_seconds = 0.0
    integration_event_counts: Mapping[str, Any] = {}
    runtime_metrics_before: Mapping[str, Any] = {}
    runtime_metrics_after: Mapping[str, Any] = {}
    failure_stage: str | None = None
    try:
        failure_stage = "initialize_isolated_authorities"
        progress.append("run_started", mapped_authority_count=len(scopes))
        versions = _initialize_catalogs_without_global_patch(
            scopes["restricted-catalog"], scopes["catalog-registry"]
        )
        _grant_integration_entitlements(scopes, versions)
        active = versions["1.0"]
        secondary = versions["2.0"]
        expected_recovery = _create_crosswalk_fixture(
            scopes,
            run_id=run_id,
            catalog_version_id=str(active["catalog_version_id"]),
        )
        environment_pins, _public_pins = _environment_pins(
            base,
            scopes,
            backend_port=settings.backend_port,
            frontend_port=settings.frontend_port,
        )
        environment_pins.update(
            {
                "ATLAS_ISOLATED_ACCEPTANCE_RUN_ID": run_id,
                "ATLAS_ISOLATED_CROSSWALK_GOVERNANCE_ID": str(
                    expected_recovery["governance_id"]
                ),
                "ATLAS_ISOLATED_CROSSWALK_REVISION": str(expected_recovery["revision"]),
                "ATLAS_ISOLATED_CROSSWALK_CHECKSUM": str(
                    expected_recovery["revision_checksum"]
                ),
                "ATLAS_ISOLATED_RECOVERY_CATALOG_VERSION_ID": str(
                    expected_recovery["catalog_version_id"]
                ),
                "ATLAS_ISOLATED_RECOVERY_CATALOG_CHECKSUM": str(
                    expected_recovery["catalog_checksum"]
                ),
            }
        )
        failure_stage = "build_production_frontend"
        production_build = _build_production_frontend(
            scopes["frontend-build"],
            scopes["logs"],
            scopes["temporary-files"],
            settings.backend_port,
        )
        progress.append("production_frontend_built", hmr_markers_absent=True)
        failure_stage = "start_initial_backend"
        if port_reservations is not None:
            port_reservations.release("backend")
        backend = _start_backend_cycle(
            environment_pins,
            scopes["logs"],
            settings.backend_port,
            cycle=0,
        )
        failure_stage = "wait_initial_backend_health"
        _wait_for_guarded_health(
            backend,
            backend_port=settings.backend_port,
            run_id=run_id,
        )
        failure_stage = "verify_initial_backend_listener"
        progress.append(
            "initial_backend_listener_observed",
            launcher_pid=int(backend.pid),
            listener_pids=sorted(_listener_pids(settings.backend_port)),
            owned_process_pids=sorted(_owned_process_pids(backend)),
        )
        initial_pid = _wait_for_exact_listener(backend, settings.backend_port)
        listener_pids_seen.add(initial_pid)
        failure_stage = "start_static_frontend"
        if port_reservations is not None:
            port_reservations.release("frontend")
        frontend = _start_static_frontend(
            scopes["frontend-build"],
            scopes["logs"],
            scopes["temporary-files"],
            settings.frontend_port,
        )
        failure_stage = "wait_static_frontend"
        _wait_for_http(f"http://127.0.0.1:{settings.frontend_port}/", frontend)
        _wait_for_exact_listener(frontend, settings.frontend_port)
        progress.append(
            "isolated_runtime_ready",
            backend_pid=initial_pid,
            frontend_pid=int(frontend.pid),
        )
        runtime_metrics_before = _request_json(
            f"http://127.0.0.1:{settings.backend_port}",
            "/api/isolated/runtime-metrics",
            run_id=run_id,
        )
        failure_stage = "initial_authenticated_browser"
        initial_browser = _run_browser_phase(
            scopes,
            base=base,
            run_id=run_id,
            phase="initial",
            backend_port=settings.backend_port,
            frontend_port=settings.frontend_port,
            catalog_version_id=str(active["catalog_version_id"]),
            secondary_catalog_version_id=str(secondary["catalog_version_id"]),
            headed=settings.headed_browser,
            violation_path=violation_path,
        )
        browser_phases.append(initial_browser)
        initial_evidence_path = scopes["test-output"] / "frontend-reload-evidence-initial.json"
        initial_reload_evidence = _write_reload_evidence(
            initial_evidence_path,
            run_id=run_id,
            frontend_port=settings.frontend_port,
            backend_port=settings.backend_port,
            phases=browser_phases,
            allowed_evidence_root=mapped_roots["test-output"],
        )
        progress.append(
            "initial_authenticated_reload_passed",
            reload_successes=initial_browser["authenticated_reload_successes"],
        )
        if violation_path.exists():
            raise IntegratedCloseoutError(
                "A non-orchestrated client contacted the isolated backend."
            )

        failure_stage = "start_operational_soak"
        process_context = multiprocessing.get_context("spawn")
        operational_queue = process_context.Queue()
        operational_process = process_context.Process(
            target=_operational_worker,
            args=(
                _soak_settings(
                    settings,
                    initial_evidence_path,
                    authority_map=operational_authority_map,
                ),
                operational_queue,
            ),
            name="synthetic-isolated-catalog-operational-soak",
        )
        operational_process.start()

        def drain_operational_messages() -> str | None:
            nonlocal operational_summary
            failure: str | None = None
            if operational_queue is None:
                return "OperationalQueueUnavailable"
            while True:
                try:
                    message = operational_queue.get_nowait()
                except queue.Empty:
                    break
                kind = str(message.get("kind") or "")
                if kind == "progress":
                    progress.append(
                        "operational_soak_heartbeat",
                        soak_elapsed_seconds=float(message.get("elapsed_seconds") or 0),
                        total_requests=int(message.get("total_requests") or 0),
                        unexpected_failures=int(message.get("unexpected_failures") or 0),
                    )
                elif kind == "result" and isinstance(message.get("summary"), Mapping):
                    operational_summary = dict(message["summary"])
                elif kind == "failure":
                    failure = str(message.get("failure_type") or "OperationalSoakFailure")
                else:
                    failure = "OperationalSoakEvidenceError"
            return failure

        soak_window_started = time.monotonic()
        soak_window_started_at = _utc_now()

        def assert_operational_window_active() -> None:
            failure = drain_operational_messages()
            if failure is not None or operational_process.exitcode is not None:
                raise IntegratedCloseoutError(
                    "The operational workload ended during authenticated reload."
                )
            if backend is None or backend.poll() is not None:
                raise IntegratedCloseoutError(
                    "The isolated backend exited during authenticated reload."
                )

        failure_stage = "timed_authenticated_browser"
        timed_browser = _run_browser_phase(
            scopes,
            base=base,
            run_id=run_id,
            phase="timed-window",
            backend_port=settings.backend_port,
            frontend_port=settings.frontend_port,
            catalog_version_id=str(active["catalog_version_id"]),
            secondary_catalog_version_id=str(secondary["catalog_version_id"]),
            headed=settings.headed_browser,
            violation_path=violation_path,
            abort_check=assert_operational_window_active,
        )
        browser_phases.append(timed_browser)
        progress.append(
            "timed_window_authenticated_reload_passed",
            reload_successes=timed_browser["authenticated_reload_successes"],
        )
        schedule = _restart_schedule(settings.duration_seconds, settings.restart_cycle_count)
        for cycle_number, target_elapsed in enumerate(schedule, start=1):
            failure_stage = f"restart_cycle_{cycle_number:02d}_wait"
            while time.monotonic() - soak_window_started < target_elapsed:
                operational_failure = drain_operational_messages()
                if operational_failure is not None:
                    raise IntegratedCloseoutError(
                        "The operational workload failed during the listener window."
                    )
                if operational_process.exitcode is not None:
                    drain_operational_messages()
                    raise IntegratedCloseoutError(
                        "The operational workload ended before all listener cycles."
                    )
                if violation_path.exists():
                    raise IntegratedCloseoutError(
                        "A non-orchestrated client contacted the isolated backend."
                    )
                if backend.poll() is not None:
                    raise IntegratedCloseoutError(
                        "The isolated backend exited outside a planned restart."
                    )
                sleep(min(0.25, max(0.01, target_elapsed - (time.monotonic() - soak_window_started))))
            cycle_started = _utc_now()
            failure_stage = f"restart_cycle_{cycle_number:02d}_stop"
            old_pid = _wait_for_exact_listener(backend, settings.backend_port)
            old_process = backend
            _stop_owned_process_tree(old_process)
            old_exit_code = old_process.returncode
            backend = None
            _wait_for_port_closed(settings.backend_port)
            closed_at = _utc_now()
            failure_stage = f"restart_cycle_{cycle_number:02d}_start"
            backend = _start_backend_cycle(
                environment_pins,
                scopes["logs"],
                settings.backend_port,
                cycle=cycle_number,
            )
            _wait_for_guarded_health(
                backend,
                backend_port=settings.backend_port,
                run_id=run_id,
            )
            new_pid = _wait_for_exact_listener(backend, settings.backend_port)
            if new_pid == old_pid or new_pid in listener_pids_seen:
                raise IntegratedCloseoutError(
                    "An isolated backend restart did not replace the listener PID."
                )
            listener_pids_seen.add(new_pid)
            failure_stage = f"restart_cycle_{cycle_number:02d}_recovery"
            path = (
                "/api/isolated/integrated-recovery/"
                + quote(str(expected_recovery["catalog_version_id"]), safe="")
                + "/"
                + quote(str(expected_recovery["governance_id"]), safe="")
                + "/"
                + str(expected_recovery["revision"])
            )
            recovery = _validate_exact_recovery(
                _request_json(
                    f"http://127.0.0.1:{settings.backend_port}",
                    path,
                    run_id=run_id,
                ),
                expected_recovery,
            )
            cycle = {
                "cycle": cycle_number,
                "started_at": cycle_started,
                "old_pid": old_pid,
                "old_listener_stopped": True,
                "old_process_exit_code": old_exit_code,
                "port_closed_at": closed_at,
                "port_closed_before_restart": True,
                "new_pid": new_pid,
                "pid_changed": True,
                "healthy_at": _utc_now(),
                **recovery,
            }
            restart_cycles.append(cycle)
            progress.append(
                "backend_restart_recovery_passed",
                cycle=cycle_number,
                old_pid=old_pid,
                new_pid=new_pid,
                port_closed=True,
            )
        failure_stage = "wait_operational_soak_completion"
        while operational_process.is_alive():
            operational_failure = drain_operational_messages()
            if operational_failure is not None:
                raise IntegratedCloseoutError(
                    "The operational workload failed after listener recovery."
                )
            if violation_path.exists():
                raise IntegratedCloseoutError(
                    "A non-orchestrated client contacted the isolated backend."
                )
            if backend.poll() is not None:
                raise IntegratedCloseoutError(
                    "The isolated backend exited after listener recovery."
                )
            sleep(0.25)
        operational_process.join(timeout=5)
        operational_failure = None
        result_deadline = time.monotonic() + 10
        while (
            not operational_summary
            and operational_failure is None
            and time.monotonic() < result_deadline
        ):
            operational_failure = drain_operational_messages()
            if not operational_summary and operational_failure is None:
                sleep(0.05)
        if operational_process.exitcode != 0 or operational_failure is not None:
            raise IntegratedCloseoutError("The operational workload child did not exit cleanly.")
        if not operational_summary:
            raise IntegratedCloseoutError("The operational workload produced no aggregate evidence.")
        soak_window_elapsed_seconds = time.monotonic() - soak_window_started
        soak_window_completed_at = _utc_now()
        if operational_summary.get("passed") is not True:
            raise IntegratedCloseoutError("The operational catalog workload did not pass.")
        if float(operational_summary.get("timed_soak_elapsed_seconds") or 0) < float(
            settings.duration_seconds
        ):
            raise IntegratedCloseoutError("The uninterrupted operational window was too short.")
        if violation_path.exists():
            raise IntegratedCloseoutError(
                "A non-orchestrated client contacted the isolated backend."
            )
        failure_stage = "final_authenticated_browser"
        final_browser = _run_browser_phase(
            scopes,
            base=base,
            run_id=run_id,
            phase="final",
            backend_port=settings.backend_port,
            frontend_port=settings.frontend_port,
            catalog_version_id=str(active["catalog_version_id"]),
            secondary_catalog_version_id=str(secondary["catalog_version_id"]),
            headed=settings.headed_browser,
            violation_path=violation_path,
        )
        browser_phases.append(final_browser)
        runtime_metrics_after = _request_json(
            f"http://127.0.0.1:{settings.backend_port}",
            "/api/isolated/runtime-metrics",
            run_id=run_id,
        )
        integration_event_counts = _load_integration_event_counts(
            scopes["logs"] / INTEGRATION_EVENT_FILE
        )
        combined_reload_evidence = _write_reload_evidence(
            scopes["test-output"] / "frontend-reload-evidence-combined.json",
            run_id=run_id,
            frontend_port=settings.frontend_port,
            backend_port=settings.backend_port,
            phases=browser_phases,
            allowed_evidence_root=mapped_roots["test-output"],
        )
        progress.append(
            "final_authenticated_reload_passed",
            reload_successes=final_browser["authenticated_reload_successes"],
        )
        if violation_path.exists():
            raise IntegratedCloseoutError(
                "A non-orchestrated client contacted the isolated backend."
            )
        failure_stage = None
    except BaseException as exc:
        failure_type = type(exc).__name__
        progress.append(
            "run_failed",
            failure_type=failure_type,
            failure_stage=failure_stage or "unspecified",
        )
    finally:
        if port_reservations is not None:
            port_reservations.close()
        if operational_process is not None and operational_process.is_alive():
            operational_process.terminate()
            operational_process.join(timeout=15)
            if operational_process.is_alive():
                operational_process.kill()
                operational_process.join(timeout=15)
        if operational_queue is not None:
            operational_queue.close()
            operational_queue.join_thread()
        try:
            _stop_owned_process_tree(frontend)
            _stop_owned_process_tree(backend)
            _wait_for_port_closed(settings.frontend_port)
            _wait_for_port_closed(settings.backend_port)
            teardown_ports_closed = True
        except BaseException as teardown_exc:
            failure_type = failure_type or type(teardown_exc).__name__

    elapsed = time.monotonic() - wall_started
    progress.append(
        "isolated_runtime_torn_down",
        restart_cycles=len(restart_cycles),
        isolated_ports_closed=teardown_ports_closed,
        failure_type=failure_type,
    )
    progress_bytes = progress.path.read_bytes() if progress.path.exists() else b""
    network_totals = {
        field: sum(
            int(phase.get("network_contact_guard", {}).get(field, 0))
            for phase in browser_phases
        )
        for field in (
            "fetch_xhr_count",
            "isolated_backend_fetch_xhr_count",
            "unexpected_fetch_xhr_count",
            "websocket_count",
            "blocked_request_count",
            "live_port_contact_count",
        )
    }
    in_window_reload_attempts, in_window_reload_successes = _reload_totals(
        browser_phases,
        inside_operational_window_only=True,
    )
    passed = (
        failure_type is None
        and teardown_ports_closed
        and production_build.get("status") == "passed"
        and production_build.get("vite_hmr_markers_absent") is True
        and operational_summary.get("passed") is True
        and integration_event_counts.get("required_categories_present") is True
        and soak_window_elapsed_seconds >= settings.duration_seconds
        and len(restart_cycles) >= settings.restart_cycle_count
        and len(listener_pids_seen) == len(restart_cycles) + 1
        and all(
            cycle.get("pid_changed") is True
            and cycle.get("port_closed_before_restart") is True
            and cycle.get("old_process_exit_code") is not None
            and cycle.get("exact_catalog_recovered") is True
            and cycle.get("exact_crosswalk_recovered") is True
            for cycle in restart_cycles
        )
        and len(browser_phases) == 3
        and all(
            phase.get("canonical_eda_handoff_verified") is True
            and phase.get("final_holdout_accessed") is False
            and phase.get("training_started") is False
            and len(phase.get("project_scenarios") or ()) == 5
            for phase in browser_phases
        )
        and any(
            phase.get("phase") == "timed-window"
            and phase.get("inside_operational_window") is True
            for phase in browser_phases
        )
        and int(combined_reload_evidence.get("authenticated_reload_successes") or 0)
        == int(combined_reload_evidence.get("authenticated_reload_attempts") or -1)
        and int(combined_reload_evidence.get("authenticated_reload_successes") or 0)
        >= MIN_FRONTEND_AUTHENTICATED_RELOADS
        and in_window_reload_successes == in_window_reload_attempts
        and in_window_reload_successes
        >= MIN_TIMED_WINDOW_AUTHENTICATED_RELOADS
        and network_totals["unexpected_fetch_xhr_count"] == 0
        and network_totals["websocket_count"] == 0
        and network_totals["blocked_request_count"] == 0
        and network_totals["live_port_contact_count"] == 0
        and not violation_path.exists()
    )
    if settings.enforce_release_minimums:
        passed = (
            passed
            and float(operational_summary.get("timed_soak_elapsed_seconds") or 0)
            >= DEFAULT_DURATION_SECONDS
            and soak_window_elapsed_seconds >= DEFAULT_DURATION_SECONDS
            and len(restart_cycles) >= MIN_ACTUAL_BACKEND_RESTARTS
        )
    summary: dict[str, Any] = {
        "schema_version": "1.0",
        "classification": "synthetic_integrated_catalog_closeout",
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": _utc_now(),
        "elapsed_seconds": round(elapsed, 6),
        "passed": passed,
        "failure_type": failure_type,
        "failure_stage": failure_stage if failure_type else None,
        "authority_map": {
            "checksum": hashlib.sha256(settings.authority_map.read_bytes()).hexdigest(),
            "mapped_authority_count": len(scopes),
            "unique_disjoint_run_children": True,
            "run_scope_id": authority_scope_id,
        },
        "production_build": dict(production_build),
        "static_frontend": {
            "non_hmr": True,
            "frontend_port": settings.frontend_port,
            "backend_port": settings.backend_port,
            "initial_backend_pid": initial_pid,
        },
        "operational_soak": dict(operational_summary),
        "data_acquisition_integration_events": dict(integration_event_counts),
        "isolated_backend_resource_metrics": _runtime_metric_delta(
            runtime_metrics_before, runtime_metrics_after
        ),
        "actual_backend_restart_cycles": restart_cycles,
        "actual_backend_restart_count": len(restart_cycles),
        "timed_window_authenticated_reload_attempts": in_window_reload_attempts,
        "timed_window_authenticated_reload_successes": in_window_reload_successes,
        "backend_listener_pid_count": len(listener_pids_seen),
        "backend_listener_pids_unique": len(listener_pids_seen)
        == len(restart_cycles) + 1,
        "authenticated_frontend_phases": browser_phases,
        "uninterrupted_operational_window": {
            "started_at": soak_window_started_at,
            "completed_at": soak_window_completed_at,
            "configured_seconds": settings.duration_seconds,
            "elapsed_seconds": round(soak_window_elapsed_seconds, 6),
            "authenticated_reload_phase": "timed-window",
            "actual_listener_restart_count": len(restart_cycles),
            "same_run_id": run_id,
        },
        "initial_frontend_reload_evidence_checksum": initial_reload_evidence.get(
            "evidence_checksum"
        ),
        "combined_frontend_reload_evidence_checksum": combined_reload_evidence.get(
            "evidence_checksum"
        ),
        "network_contact_guard": network_totals,
        "isolation": {
            "live_frontend_port_contacted": False,
            "live_backend_port_contacted": False,
            "non_orchestrated_client_contact_detected": violation_path.exists(),
            "live_authorities_opened": False,
            "live_services_manipulated": False,
            "isolated_ports_closed_after_teardown": teardown_ports_closed,
        },
        "progress_evidence": {
            "file": PROGRESS_FILE,
            "event_count": progress.count,
            "sha256": hashlib.sha256(progress_bytes).hexdigest(),
        },
        "contains_vendor_content": False,
        "live_project_accessed": False,
        "sealed_holdout_accessed": False,
        "training_started": False,
        "source_or_git_mutated_by_run": False,
        "summary_file": SUMMARY_FILE,
    }
    summary["evidence_checksum"] = _checksum(summary)
    with (scopes["test-output"] / SUMMARY_FILE).open("xb") as handle:
        handle.write(canonical_json_bytes(summary))
        handle.flush()
        os.fsync(handle.fileno())
    if not passed:
        raise IntegratedCloseoutError(
            "The integrated catalog closeout failed; inspect its isolated aggregate evidence."
        )
    return summary


def run_integrated_closeout(
    settings: IntegratedCloseoutSettings,
    *,
    port_reservations: ReservedLoopbackPorts | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Mapping[str, Any]:
    """Run closeout and always release any still-held dynamic reservations."""

    try:
        return _run_integrated_closeout_with_ports(
            settings,
            port_reservations=port_reservations,
            sleep=sleep,
        )
    finally:
        if port_reservations is not None:
            port_reservations.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-map", required=True, type=Path)
    parser.add_argument("--backend-port", default=0, type=int)
    parser.add_argument("--frontend-port", default=0, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reservations: ReservedLoopbackPorts | None = None
    try:
        if args.backend_port == 0 and args.frontend_port == 0:
            reservations = reserve_dynamic_non_live_ports()
            backend_port = reservations.ports["backend"]
            frontend_port = reservations.ports["frontend"]
        elif args.backend_port == 0 or args.frontend_port == 0:
            raise IntegratedCloseoutError(
                "Specify both isolated ports or allow both to be assigned dynamically."
            )
        else:
            backend_port = args.backend_port
            frontend_port = args.frontend_port
        summary = run_integrated_closeout(
            IntegratedCloseoutSettings(
                authority_map=args.authority_map,
                backend_port=backend_port,
                frontend_port=frontend_port,
            ),
            port_reservations=reservations,
        )
    except Exception as exc:
        sys.stderr.write(
            json.dumps(
                {
                    "ok": False,
                    "classification": "synthetic_integrated_catalog_closeout",
                    "failure_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 1
    sys.stdout.write(
        json.dumps(
            {
                "ok": summary["passed"],
                "run_id": summary["run_id"],
                "elapsed_seconds": summary["elapsed_seconds"],
                "actual_backend_restart_count": summary[
                    "actual_backend_restart_count"
                ],
                "network_contact_guard": summary["network_contact_guard"],
                "isolation": summary["isolation"],
                "evidence_checksum": summary["evidence_checksum"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
