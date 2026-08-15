"""Run real ATLAS Playwright specs against a disposable, isolated full stack.

The harness never binds the normal ATLAS ports and never imports ``server`` in
the orchestrator process.  A source-only hermetic child owns every mutable
backend authority.  The production frontend, browser profile, Playwright
artifacts, service logs, and network evidence also live below that child's
UUID-scoped Windows Temp root.

Browser traffic is forced through a deny-by-default loopback proxy.  Only the
exact isolated frontend and backend origins are forwarded.  Requests for the
normal ATLAS ports, unexpected origins, CONNECT tunnels, and WebSockets are
blocked without recording request headers, cookies, bodies, or query strings.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import SplitResult, urlsplit
from urllib.request import urlopen

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.hermetic_test_authority import (
    ChildAuthority,
    SYSTEM_ENV_ALLOWLIST,
    build_child_environment,
    create_child_authority,
    create_run_authority,
    prepare_child,
    validate_external_root,
)
from scripts.isolated_loopback_ports import (
    LIVE_ATLAS_PORTS,
    LOOPBACK_HOST,
    ReservedLoopbackPorts,
    reserve_dynamic_non_live_ports,
    validate_non_live_ports,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
E2E_ROOT = REPOSITORY_ROOT / "tests" / "e2e"
ISOLATED_PLAYWRIGHT_CONFIG = E2E_ROOT / "playwright.isolated.config.ts"
ISOLATED_MIGRATION = (
    "server/persistence/migrations/"
    "0028_project_deletion_append_only_cascade.sql"
)
DEFAULT_TIMEOUT_SECONDS = 20 * 60
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
UNSAFE_SPEC_MARKERS = (
    "atlas_session",
    "sessionStorage.setItem",
    "claude\\temp",
    "claude/temp",
)


class IsolatedWorkflowHarnessError(RuntimeError):
    """A bounded harness failure safe to include in the result summary."""

    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        super().__init__(message)


@dataclass(frozen=True)
class HarnessLayout:
    child: ChildAuthority
    frontend_build: Path
    logs: Path
    browser_profile: Path
    browser_downloads: Path
    playwright_output: Path
    screenshots: Path
    npm_cache: Path
    network_events: Path
    result_file: Path


@dataclass(frozen=True)
class NetworkDecision:
    allowed: bool
    reason: str
    origin: str
    path: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validated_temp_parent(value: str | Path | None = None) -> Path:
    """Require the run parent to be the OS Temp tree, never the repository."""

    system_temp = Path(tempfile.gettempdir()).resolve(strict=True)
    parent = Path(value).expanduser().resolve(strict=True) if value else system_temp
    if parent != system_temp and system_temp not in parent.parents:
        raise IsolatedWorkflowHarnessError(
            "unsafe-temp-root", "The isolated run parent must be below Windows Temp."
        )
    validate_external_root(parent)
    return parent


def _origin(parts: SplitResult) -> str:
    if not parts.scheme or not parts.hostname:
        return ""
    try:
        port = parts.port
    except ValueError:
        return ""
    default = 80 if parts.scheme == "http" else 443 if parts.scheme == "https" else None
    suffix = "" if port is None or port == default else f":{port}"
    return f"{parts.scheme.lower()}://{parts.hostname.lower()}{suffix}"


def validated_isolated_origin(value: str) -> str:
    """Return a normalized HTTP loopback origin that cannot be a live port."""

    parts = urlsplit(str(value).strip())
    if (
        parts.scheme.lower() != "http"
        or parts.hostname != LOOPBACK_HOST
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
        or parts.query
        or parts.fragment
    ):
        raise IsolatedWorkflowHarnessError(
            "unsafe-origin", "Isolated services require an exact HTTP loopback origin."
        )
    try:
        port = int(parts.port or 80)
    except ValueError as exc:
        raise IsolatedWorkflowHarnessError(
            "unsafe-origin", "The isolated origin contained an invalid port."
        ) from exc
    try:
        validate_non_live_ports((port,))
    except Exception as exc:
        raise IsolatedWorkflowHarnessError(
            "unsafe-origin", "A protected or invalid service port was selected."
        ) from exc
    return f"http://{LOOPBACK_HOST}:{port}"


class NetworkGuardPolicy:
    """Pure request classifier shared by the proxy and focused tests."""

    def __init__(self, allowed_origins: Iterable[str]) -> None:
        normalized = tuple(validated_isolated_origin(item) for item in allowed_origins)
        if len(normalized) != 2 or len(set(normalized)) != 2:
            raise IsolatedWorkflowHarnessError(
                "unsafe-origin-plan",
                "The network guard requires distinct frontend and backend origins.",
            )
        self.frontend_origin, self.backend_origin = normalized
        self.allowed_origins = frozenset(normalized)

    def decide(
        self,
        raw_url: str,
        *,
        method: str = "GET",
        upgrade: str = "",
        host_header: str = "",
    ) -> NetworkDecision:
        if str(method).upper() == "CONNECT":
            connect_target = urlsplit(f"//{str(raw_url).strip()}")
            try:
                connect_port = int(connect_target.port or 443)
            except (TypeError, ValueError):
                return NetworkDecision(False, "invalid_url", "", "")
            if (
                (connect_target.hostname or "").casefold()
                in {LOOPBACK_HOST.casefold(), "localhost", "::1"}
                and connect_port in LIVE_ATLAS_PORTS
            ):
                return NetworkDecision(False, "live_port", "", "")
            return NetworkDecision(False, "connect_tunnel", "", "")
        if str(upgrade).strip().lower() == "websocket":
            return NetworkDecision(False, "websocket", "", "")
        candidate = str(raw_url).strip()
        if candidate.startswith("/") and host_header:
            candidate = f"http://{host_header}{candidate}"
        parts = urlsplit(candidate)
        origin = _origin(parts)
        safe_path = parts.path or "/"
        try:
            port = int(parts.port or (80 if parts.scheme == "http" else 443))
        except (TypeError, ValueError):
            return NetworkDecision(False, "invalid_url", origin, safe_path)
        if port in LIVE_ATLAS_PORTS:
            return NetworkDecision(False, "live_port", origin, safe_path)
        if parts.scheme.lower() != "http":
            return NetworkDecision(False, "unexpected_scheme", origin, safe_path)
        if origin not in self.allowed_origins:
            return NetworkDecision(False, "unexpected_origin", origin, safe_path)
        if origin == self.frontend_origin and (
            safe_path == "/api" or safe_path.startswith("/api/")
        ):
            return NetworkDecision(False, "frontend_api", origin, safe_path)
        if origin == self.backend_origin and not (
            safe_path == "/api" or safe_path.startswith("/api/")
        ):
            return NetworkDecision(False, "backend_non_api", origin, safe_path)
        return NetworkDecision(True, "allowed", origin, safe_path)


class NetworkEvidence:
    """Thread-safe, header-free network counters and JSONL evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {
            "allowed": 0,
            "blocked": 0,
            "live_port": 0,
            "unexpected_origin": 0,
            "unexpected_scheme": 0,
            "frontend_api": 0,
            "backend_non_api": 0,
            "websocket": 0,
            "connect_tunnel": 0,
            "invalid_url": 0,
            "upstream_error": 0,
            "downstream_disconnect": 0,
        }

    def record(self, decision: NetworkDecision, method: str) -> None:
        event = {
            "schema_version": 1,
            "occurred_at": _utc_now(),
            "method": str(method).upper()[:12],
            "outcome": "allowed" if decision.allowed else "blocked",
            "reason": decision.reason,
            "origin": decision.origin,
            # Deliberately omit query, fragment, headers, cookies, and body.
            "path": decision.path,
        }
        with self._lock:
            self._counts["allowed" if decision.allowed else "blocked"] += 1
            if decision.reason in self._counts and decision.reason != "allowed":
                self._counts[decision.reason] += 1
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

    def _record_transport_event(
        self,
        decision: NetworkDecision,
        method: str,
        *,
        reason: str,
        phase: str,
        error: BaseException,
    ) -> None:
        event = {
            "schema_version": 1,
            "occurred_at": _utc_now(),
            "method": str(method).upper()[:12],
            "outcome": "transport_error",
            "reason": reason,
            "origin": decision.origin,
            # Keep transport diagnostics as safe as request evidence: no query,
            # fragment, headers, cookies, or body, and no exception message.
            "path": decision.path,
            "phase": phase,
            "error_type": type(error).__name__[:80],
        }
        with self._lock:
            self._counts[reason] += 1
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")

    def upstream_error(
        self,
        decision: NetworkDecision,
        method: str,
        error: BaseException,
    ) -> None:
        self._record_transport_event(
            decision,
            method,
            reason="upstream_error",
            phase="upstream",
            error=error,
        )

    def downstream_disconnect(
        self,
        decision: NetworkDecision,
        method: str,
        error: BaseException,
    ) -> None:
        self._record_transport_event(
            decision,
            method,
            reason="downstream_disconnect",
            phase="downstream",
            error=error,
        )

    def summary(self) -> dict[str, int | bool]:
        with self._lock:
            counts = dict(self._counts)
        return {
            **counts,
            "service_workers_blocked_by_playwright": True,
            "live_port_contacted": counts["live_port"] > 0,
            "unexpected_origin_contacted": counts["unexpected_origin"] > 0,
            "websocket_contacted": counts["websocket"] > 0,
        }


class _GuardProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(
        self,
        address: tuple[str, int],
        policy: NetworkGuardPolicy,
        evidence: NetworkEvidence,
    ) -> None:
        self.policy = policy
        self.evidence = evidence
        super().__init__(address, _GuardProxyHandler)


class _GuardProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ATLAS-Isolated-Network-Guard"
    sys_version = ""

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_CONNECT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        self._handle()

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def do_PUT(self) -> None:  # noqa: N802
        self._handle()

    def do_PATCH(self) -> None:  # noqa: N802
        self._handle()

    def do_DELETE(self) -> None:  # noqa: N802
        self._handle()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._handle()

    @property
    def guard_server(self) -> _GuardProxyServer:
        return self.server  # type: ignore[return-value]

    def _handle(self) -> None:
        decision = self.guard_server.policy.decide(
            self.path,
            method=self.command,
            upgrade=self.headers.get("Upgrade", ""),
            host_header=self.headers.get("Host", ""),
        )
        self.guard_server.evidence.record(decision, self.command)
        if not decision.allowed:
            payload = b"Blocked by isolated ATLAS network guard."
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
            self.close_connection = True
            return
        self._forward(decision)

    def _forward(self, decision: NetworkDecision) -> None:
        parts = urlsplit(self.path)
        if not parts.hostname:
            parts = urlsplit(f"{decision.origin}{self.path}")
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length) if content_length else None
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.casefold() not in HOP_BY_HOP_HEADERS
        }
        headers["Host"] = parts.netloc
        target = parts.path or "/"
        if parts.query:
            target = f"{target}?{parts.query}"
        connection = http.client.HTTPConnection(
            parts.hostname,
            int(parts.port or 80),
            timeout=60,
        )
        try:
            connection.request(self.command, target, body=body, headers=headers)
            response = connection.getresponse()
            payload = response.read()
            response_status = response.status
            response_reason = response.reason
            response_headers = tuple(response.getheaders())
        except (OSError, http.client.HTTPException) as error:
            self.guard_server.evidence.upstream_error(
                decision,
                self.command,
                error,
            )
            payload = b"Isolated upstream unavailable."
            try:
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Connection", "close")
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(payload)
            except OSError as downstream_error:
                self.guard_server.evidence.downstream_disconnect(
                    decision,
                    self.command,
                    downstream_error,
                )
            return
        finally:
            connection.close()

        try:
            self.send_response(response_status, response_reason)
            for key, value in response_headers:
                if key.casefold() not in HOP_BY_HOP_HEADERS | {"content-length"}:
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)
        except OSError as downstream_error:
            # A browser can cancel in-flight fetches while closing a page or
            # context.  The upstream request already succeeded, so this is
            # evidence of a downstream cancellation, not an unavailable or
            # escaped network contact.
            self.guard_server.evidence.downstream_disconnect(
                decision,
                self.command,
                downstream_error,
            )
        finally:
            self.close_connection = True


@dataclass
class RunningNetworkGuard:
    server: _GuardProxyServer
    thread: threading.Thread

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=10)


def start_network_guard(
    port: int,
    policy: NetworkGuardPolicy,
    evidence: NetworkEvidence,
) -> RunningNetworkGuard:
    server = _GuardProxyServer((LOOPBACK_HOST, int(port)), policy, evidence)
    thread = threading.Thread(
        target=server.serve_forever,
        name="atlas-isolated-network-guard",
        daemon=True,
    )
    thread.start()
    return RunningNetworkGuard(server, thread)


def network_summary_has_violation(summary: Mapping[str, int | bool]) -> bool:
    """Return whether the browser crossed or could not reach its allowed boundary.

    Browser-side disconnects after a successful upstream response are retained
    as diagnostic evidence but are not network-boundary violations. Chromium's
    deny-proxy CONNECT attempts are likewise retained and blocked before any
    tunnel exists; they are containment evidence, not successful contacts.
    """

    fatal_reasons = (
        "live_port",
        "unexpected_origin",
        "unexpected_scheme",
        "frontend_api",
        "backend_non_api",
        "websocket",
        "invalid_url",
        "upstream_error",
    )
    if any(int(summary.get(reason, 0)) > 0 for reason in fatal_reasons):
        return True
    classified_blocked = sum(
        int(summary.get(reason, 0))
        for reason in (*fatal_reasons[:-1], "connect_tunnel")
    )
    return int(summary.get("blocked", 0)) != classified_blocked


def create_harness_layout(base_temp: str | Path | None = None) -> HarnessLayout:
    run = create_run_authority(validated_temp_parent(base_temp))
    child = create_child_authority(run, "isolated-full-workflow-acceptance")
    prepare_child(child, isolated_migrations=(ISOLATED_MIGRATION,))
    paths = {
        "frontend_build": child.root / "frontend-build",
        "logs": child.root / "logs",
        "browser_profile": child.authorities["browser_storage_root"],
        "browser_downloads": child.root / "authorities" / "browser-downloads",
        "playwright_output": child.authorities["playwright_output_root"],
        "screenshots": child.authorities["playwright_output_root"] / "screenshots",
        "npm_cache": child.root / "authorities" / "npm-cache",
    }
    for path in paths.values():
        Path(path).mkdir(parents=True, exist_ok=True)
    network_events = Path(paths["playwright_output"]) / "network-events.jsonl"
    network_events.touch(exist_ok=False)
    return HarnessLayout(
        child=child,
        frontend_build=Path(paths["frontend_build"]),
        logs=Path(paths["logs"]),
        browser_profile=Path(paths["browser_profile"]),
        browser_downloads=Path(paths["browser_downloads"]),
        playwright_output=Path(paths["playwright_output"]),
        screenshots=Path(paths["screenshots"]),
        npm_cache=Path(paths["npm_cache"]),
        network_events=network_events,
        result_file=Path(paths["playwright_output"]) / "acceptance-result.json",
    )


def build_backend_environment(
    layout: HarnessLayout,
    *,
    backend_origin: str,
    frontend_origin: str,
) -> dict[str, str]:
    backend = validated_isolated_origin(backend_origin)
    frontend = validated_isolated_origin(frontend_origin)
    if backend == frontend:
        raise IsolatedWorkflowHarnessError(
            "unsafe-origin-plan", "Frontend and backend origins must be distinct."
        )
    environment = build_child_environment(layout.child, inherited=os.environ)
    environment.update(
        {
            "ATLAS_AUTH_ENABLED": "1",
            "ATLAS_ALLOW_PUBLIC_REGISTRATION": "1",
            "ATLAS_LOCAL_DEV": "0",
            "ATLAS_DEV_MODE": "0",
            "ATLAS_HOSTED_MODE": "0",
            "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "0",
            "ATLAS_ENABLE_DEV_USER_HEADER": "0",
            "ATLAS_DEV_AUTH_TOOLS": "0",
            "ATLAS_CORS_ORIGINS": frontend,
            "ATLAS_TEST_BACKEND_URL": backend,
            "ATLAS_COOKIE_SECURE": "0",
        }
    )
    return environment


def _playwright_browser_root() -> str | None:
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if configured and Path(configured).is_dir():
        return configured
    local = os.environ.get("LOCALAPPDATA", "").strip()
    candidate = Path(local) / "ms-playwright" if local else None
    return str(candidate) if candidate is not None and candidate.is_dir() else None


def build_node_environment(
    layout: HarnessLayout,
    *,
    backend_origin: str,
    frontend_origin: str,
    proxy_origin: str,
    headed: bool,
) -> dict[str, str]:
    backend = validated_isolated_origin(backend_origin)
    frontend = validated_isolated_origin(frontend_origin)
    proxy = validated_isolated_origin(proxy_origin)
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in SYSTEM_ENV_ALLOWLIST
    }
    environment.update(
        {
            "TEMP": str(layout.child.root / "t"),
            "TMP": str(layout.child.root / "t"),
            "HOME": str(layout.child.root / "authorities" / "home"),
            "USERPROFILE": str(layout.child.root / "authorities" / "home"),
            "APPDATA": str(layout.child.root / "authorities" / "appdata"),
            "LOCALAPPDATA": str(layout.child.root / "authorities" / "localappdata"),
            "npm_config_cache": str(layout.npm_cache),
            "NODE_COMPILE_CACHE": str(layout.child.root / "authorities" / "node-cache"),
            "VITE_APP_TARGET": "modeling",
            "VITE_API_BASE": f"{backend}/api",
            "ATLAS_E2E_BASE_URL": frontend,
            "ATLAS_E2E_BACKEND_URL": backend,
            "ATLAS_E2E_NETWORK_GUARD_PROXY": proxy,
            "ATLAS_E2E_HEADLESS": "0" if headed else "1",
            "ATLAS_E2E_RUN_ID": layout.child.run_id,
            "ATLAS_E2E_STOP_AFTER_INTERPRETATION": (
                "1"
                if os.environ.get(
                    "ATLAS_E2E_STOP_AFTER_INTERPRETATION", ""
                ).strip()
                == "1"
                else "0"
            ),
            "E2E_AUDIT_RUN_ID": layout.child.run_id,
            "E2E_AUDIT_DIR": str(layout.screenshots),
            "ATLAS_BROWSER_STORAGE_ROOT": str(layout.browser_profile),
            "ATLAS_PLAYWRIGHT_OUTPUT_ROOT": str(layout.playwright_output),
        }
    )
    browser_root = _playwright_browser_root()
    if browser_root:
        environment["PLAYWRIGHT_BROWSERS_PATH"] = browser_root
    return environment


def validate_playwright_specs(specs: Iterable[str | Path]) -> tuple[str, ...]:
    validated: list[str] = []
    e2e_root = E2E_ROOT.resolve()
    for supplied in specs:
        raw = Path(str(supplied))
        candidate = raw if raw.is_absolute() else E2E_ROOT / raw
        resolved = candidate.resolve(strict=True)
        if e2e_root not in resolved.parents or not resolved.name.endswith(".spec.ts"):
            raise IsolatedWorkflowHarnessError(
                "unsafe-spec", "Playwright specs must be TypeScript specs below tests/e2e."
            )
        source = resolved.read_text(encoding="utf-8", errors="strict")
        lowered = source.casefold()
        if any(marker.casefold() in lowered for marker in UNSAFE_SPEC_MARKERS):
            raise IsolatedWorkflowHarnessError(
                "unsafe-spec", "A selected Playwright spec injects or depends on session state."
            )
        validated.append(resolved.relative_to(e2e_root).as_posix())
    if not validated:
        raise IsolatedWorkflowHarnessError(
            "missing-spec", "Specify at least one isolated Playwright spec."
        )
    return tuple(dict.fromkeys(validated))


def _node_bin(name: str) -> Path:
    suffix = ".cmd" if os.name == "nt" else ""
    candidate = REPOSITORY_ROOT / "node_modules" / ".bin" / f"{name}{suffix}"
    if not candidate.is_file():
        raise IsolatedWorkflowHarnessError(
            "missing-runtime", f"The required local {name} executable is unavailable."
        )
    return candidate


def _python_executable() -> Path:
    candidate = (
        REPOSITORY_ROOT / ".venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else REPOSITORY_ROOT / ".venv" / "bin" / "python"
    )
    if candidate.is_file():
        return candidate
    return Path(sys.executable)


def _run_logged(
    command: Sequence[str | Path],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    with log_path.open("xb") as log:
        process = subprocess.Popen(
            [str(item) for item in command],
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            returncode = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _stop_owned_process_tree(process)
            raise IsolatedWorkflowHarnessError(
                "command-timeout", "An isolated harness command exceeded its timeout."
            ) from exc
    return subprocess.CompletedProcess(command, returncode)


def _start_logged_process(
    command: Sequence[str | Path],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    log_path: Path,
) -> subprocess.Popen[bytes]:
    log = log_path.open("xb")
    try:
        return subprocess.Popen(
            [str(item) for item in command],
            cwd=cwd,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log.close()


def _stop_owned_process_tree(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=15)


def _wait_for_http(url: str, process: subprocess.Popen[bytes], timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise IsolatedWorkflowHarnessError(
                "service-exited", "An isolated service exited before readiness."
            )
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError, OSError):
            pass
        time.sleep(0.1)
    raise IsolatedWorkflowHarnessError(
        "service-timeout", "An isolated service did not become ready."
    )


def _wait_for_port_closed(port: int, timeout: int = 15) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.2)
            if probe.connect_ex((LOOPBACK_HOST, int(port))) != 0:
                return True
        time.sleep(0.1)
    return False


def _scan_production_build(build_root: Path, backend_origin: str) -> dict[str, Any]:
    if not (build_root / "index.html").is_file():
        raise IsolatedWorkflowHarnessError(
            "frontend-build", "The isolated production frontend did not produce index.html."
        )
    digest = hashlib.sha256()
    count = 0
    forbidden = (
        b"/@vite/client",
        b"@react-refresh",
        b"import.meta.hot",
        b"__vite_ping",
    )
    live_backend_marker = b"http://127.0.0.1:8001"
    live_backend_marker_present = False
    isolated_api = f"{validated_isolated_origin(backend_origin)}/api".encode("utf-8")
    isolated_api_present = False
    for path in sorted(item for item in build_root.rglob("*") if item.is_file()):
        payload = path.read_bytes()
        relative = path.relative_to(build_root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(payload)
        count += 1
        isolated_api_present = isolated_api_present or isolated_api in payload
        live_backend_marker_present = live_backend_marker_present or live_backend_marker in payload
        if any(marker in payload for marker in forbidden):
            raise IsolatedWorkflowHarnessError(
                "frontend-build", "The production frontend contains a live or HMR marker."
            )
    if not isolated_api_present:
        raise IsolatedWorkflowHarnessError(
            "frontend-build", "The isolated backend origin was absent from the production build."
        )
    return {
        "file_count": count,
        "sha256": digest.hexdigest(),
        "hmr_markers_absent": True,
        # Runtime proxy evidence remains authoritative: a dead fallback literal
        # may survive minification, but it can never be contacted by this run.
        "live_backend_marker_absent": not live_backend_marker_present,
        "isolated_backend_origin_present": True,
    }


def _production_source_fingerprint() -> str:
    """Hash product source read by the isolated build, excluding runtime output."""

    roots = (
        REPOSITORY_ROOT / "src",
        REPOSITORY_ROOT / "shared",
        REPOSITORY_ROOT / "server",
    )
    standalone = (
        REPOSITORY_ROOT / "index.html",
        REPOSITORY_ROOT / "package.json",
        REPOSITORY_ROOT / "vite.config.ts",
        *sorted(REPOSITORY_ROOT.glob("tsconfig*.json")),
    )
    allowed_suffixes = {
        ".css",
        ".html",
        ".js",
        ".json",
        ".mjs",
        ".py",
        ".sql",
        ".ts",
        ".tsx",
    }
    files: list[Path] = [path for path in standalone if path.is_file()]
    for root in roots:
        files.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.casefold() in allowed_suffixes
            and "__pycache__" not in path.parts
            and "artifacts" not in path.parts
            and "data" not in path.parts
        )
    digest = hashlib.sha256()
    for path in sorted(set(files)):
        digest.update(path.relative_to(REPOSITORY_ROOT).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _listener_pid(port: int) -> int | None:
    if os.name != "nt":
        return None
    powershell = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    completed = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "Get-NetTCPConnection -LocalAddress 127.0.0.1 "
                f"-LocalPort {int(port)} -State Listen -ErrorAction SilentlyContinue "
                "| Select-Object -First 1 -ExpandProperty OwningProcess"
            ),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        return None
    rendered = completed.stdout.decode("utf-8", errors="ignore").strip()
    return int(rendered) if rendered.isdigit() else None


def _process_parent_pid(process_id: int) -> int | None:
    """Resolve one Windows parent PID without trusting command-line text.

    A virtual-environment ``python.exe`` launcher can remain as the owned root
    process while the base-interpreter child owns the socket. Listener
    ownership therefore has to be proven against the spawned process tree, not
    only by PID equality.
    """

    if os.name != "nt" or int(process_id) <= 0:
        return None
    powershell = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / (
        "System32/WindowsPowerShell/v1.0/powershell.exe"
    )
    completed = subprocess.run(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "Get-CimInstance Win32_Process -Filter "
                f"'ProcessId = {int(process_id)}' -ErrorAction SilentlyContinue "
                "| Select-Object -First 1 -ExpandProperty ParentProcessId"
            ),
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        return None
    rendered = completed.stdout.decode("utf-8", errors="ignore").strip()
    return int(rendered) if rendered.isdigit() else None


def _listener_belongs_to_process_tree(
    owner_pid: int,
    root_pid: int,
    parent_lookup: Callable[[int], int | None] | None = None,
) -> bool:
    """Return true only when ``owner_pid`` is ``root_pid`` or its descendant."""

    owner = int(owner_pid)
    root = int(root_pid)
    if owner <= 0 or root <= 0:
        return False
    lookup = parent_lookup or _process_parent_pid
    current = owner
    visited: set[int] = set()
    for _ in range(32):
        if current == root:
            return True
        if current <= 0 or current in visited:
            return False
        visited.add(current)
        parent = lookup(current)
        if parent is None or int(parent) <= 0:
            return False
        current = int(parent)
    return False


def _require_owned_listener(process: subprocess.Popen[bytes], port: int) -> None:
    if os.name != "nt":
        return
    owner = _listener_pid(port)
    if owner is None or not _listener_belongs_to_process_tree(owner, process.pid):
        raise IsolatedWorkflowHarnessError(
            "listener-ownership",
            "An isolated service was not the exact owner of its listener.",
        )


def _write_result(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def run_acceptance(
    specs: Iterable[str | Path],
    *,
    base_temp: str | Path | None = None,
    headed: bool = False,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    reservations: ReservedLoopbackPorts | None = None,
) -> dict[str, Any]:
    selected_specs = validate_playwright_specs(specs)
    layout = create_harness_layout(base_temp)
    owned_reservations = reservations or reserve_dynamic_non_live_ports(
        ("backend", "frontend", "network_guard")
    )
    try:
        ports = {key: int(value) for key, value in owned_reservations.ports.items()}
        if set(ports) != {"backend", "frontend", "network_guard"}:
            raise IsolatedWorkflowHarnessError(
                "port-plan", "The isolated port reservation plan was incomplete."
            )
        validate_non_live_ports(ports.values())
        backend_origin = f"http://{LOOPBACK_HOST}:{ports['backend']}"
        frontend_origin = f"http://{LOOPBACK_HOST}:{ports['frontend']}"
        proxy_origin = f"http://{LOOPBACK_HOST}:{ports['network_guard']}"
        backend_environment = build_backend_environment(
            layout,
            backend_origin=backend_origin,
            frontend_origin=frontend_origin,
        )
        node_environment = build_node_environment(
            layout,
            backend_origin=backend_origin,
            frontend_origin=frontend_origin,
            proxy_origin=proxy_origin,
            headed=headed,
        )
        source_fingerprint_before = _production_source_fingerprint()
    except BaseException:
        owned_reservations.close()
        raise
    result: dict[str, Any] = {
        "schema_version": 1,
        "ok": False,
        "run_id": layout.child.run_id,
        "started_at": _utc_now(),
        "completed_at": None,
        "specs": list(selected_specs),
        "origins": {
            "backend": backend_origin,
            "frontend": frontend_origin,
            "network_guard": proxy_origin,
        },
        "protected_live_ports": sorted(LIVE_ATLAS_PORTS),
        "authority_isolation": {
            "all_mutable_authorities_external": True,
            "migration_0028_isolated_only": True,
            "live_data_opened": False,
            "live_services_touched": False,
            "disposable_public_registration": True,
            "local_user_bootstrap": False,
        },
        "services": {},
        "production_build": None,
        "production_source": {
            "before_sha256": source_fingerprint_before,
            "after_sha256": None,
            "unchanged": None,
        },
        "playwright": {
            "headed": bool(headed),
            "exit_code": None,
            "service_workers": "blocked",
            "browser_profile_external": True,
            "output_external": True,
        },
        "network_guard": None,
        "teardown": {},
        "failure": None,
        "evidence": {
            "output_root": str(layout.playwright_output),
            "logs_root": str(layout.logs),
            "screenshots_root": str(layout.screenshots),
            "browser_profile_root": str(layout.browser_profile),
            "result": str(layout.result_file),
            "network_events": str(layout.network_events),
        },
    }
    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None
    browser: subprocess.Popen[bytes] | None = None
    guard: RunningNetworkGuard | None = None
    evidence = NetworkEvidence(layout.network_events)
    try:
        build_result = _run_logged(
            [
                _node_bin("vite"),
                "build",
                "--mode",
                "modeling",
                "--config",
                REPOSITORY_ROOT / "vite.config.ts",
                "--outDir",
                layout.frontend_build,
                "--emptyOutDir",
            ],
            cwd=REPOSITORY_ROOT,
            environment=node_environment,
            log_path=layout.logs / "frontend-build.log",
            timeout=min(timeout_seconds, 10 * 60),
        )
        if build_result.returncode != 0:
            raise IsolatedWorkflowHarnessError(
                "frontend-build", "The isolated production frontend build failed."
            )
        result["production_build"] = _scan_production_build(
            layout.frontend_build, backend_origin
        )

        owned_reservations.release("backend")
        backend = _start_logged_process(
            [
                _python_executable(),
                "-m",
                "uvicorn",
                "server.main:app",
                "--host",
                LOOPBACK_HOST,
                "--port",
                str(ports["backend"]),
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            cwd=layout.child.source_root,
            environment=backend_environment,
            log_path=layout.logs / "backend.log",
        )
        _wait_for_http(f"{backend_origin}/api/health", backend)
        _require_owned_listener(backend, ports["backend"])

        owned_reservations.release("frontend")
        frontend = _start_logged_process(
            [
                _python_executable(),
                "-m",
                "tests.bureau_metadata_isolated_static_server",
                "--root",
                layout.frontend_build,
                "--port",
                str(ports["frontend"]),
            ],
            cwd=layout.child.source_root,
            environment=backend_environment,
            log_path=layout.logs / "frontend.log",
        )
        _wait_for_http(f"{frontend_origin}/", frontend)
        _require_owned_listener(frontend, ports["frontend"])

        owned_reservations.release("network_guard")
        policy = NetworkGuardPolicy((frontend_origin, backend_origin))
        guard = start_network_guard(ports["network_guard"], policy, evidence)
        result["services"] = {
            "backend_pid": backend.pid,
            "frontend_pid": frontend.pid,
            "network_guard_thread": guard.thread.name,
            "backend_health": 200,
            "frontend_health": 200,
        }

        browser_log = (layout.logs / "playwright.log").open("xb")
        try:
            browser = subprocess.Popen(
                [
                    str(_node_bin("playwright")),
                    "test",
                    "--config",
                    str(ISOLATED_PLAYWRIGHT_CONFIG),
                    "--workers",
                    "1",
                    *selected_specs,
                ],
                cwd=REPOSITORY_ROOT,
                env=node_environment,
                stdin=subprocess.DEVNULL,
                stdout=browser_log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        finally:
            browser_log.close()
        try:
            browser_exit = browser.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _stop_owned_process_tree(browser)
            raise IsolatedWorkflowHarnessError(
                "playwright-timeout", "The isolated Playwright acceptance timed out."
            ) from exc
        result["playwright"]["exit_code"] = browser_exit
        network_summary = evidence.summary()
        result["network_guard"] = network_summary
        if browser_exit != 0:
            raise IsolatedWorkflowHarnessError(
                "playwright-failed", "One or more isolated Playwright specs failed."
            )
        if network_summary_has_violation(network_summary):
            raise IsolatedWorkflowHarnessError(
                "network-violation",
                "The isolated browser attempted a blocked or unavailable network contact.",
            )
        result["ok"] = True
    except BaseException as exc:
        code = (
            exc.code
            if isinstance(exc, IsolatedWorkflowHarnessError)
            else "unexpected-harness-failure"
        )
        message = (
            str(exc)
            if isinstance(exc, IsolatedWorkflowHarnessError)
            else "The isolated harness failed unexpectedly; inspect external logs."
        )
        result["failure"] = {"code": code, "message": message}
    finally:
        _stop_owned_process_tree(browser)
        if guard is not None:
            guard.stop()
        _stop_owned_process_tree(frontend)
        _stop_owned_process_tree(backend)
        owned_reservations.close()
        closed = {
            name: _wait_for_port_closed(port)
            for name, port in ports.items()
        }
        result["teardown"] = {
            "owned_processes_stopped": True,
            "ports_closed": closed,
            "all_ports_closed": all(closed.values()),
        }
        if not all(closed.values()):
            result["ok"] = False
            result["failure"] = {
                "code": "teardown-failure",
                "message": "An isolated listener remained open after teardown.",
            }
        result["network_guard"] = evidence.summary()
        source_fingerprint_after = _production_source_fingerprint()
        result["production_source"] = {
            "before_sha256": source_fingerprint_before,
            "after_sha256": source_fingerprint_after,
            "unchanged": source_fingerprint_after == source_fingerprint_before,
        }
        if source_fingerprint_after != source_fingerprint_before:
            result["ok"] = False
            result["failure"] = {
                "code": "source-mutated",
                "message": "Product source changed during isolated acceptance.",
            }
        result["completed_at"] = _utc_now()
        checksum_payload = json.dumps(
            result,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        result["result_checksum"] = hashlib.sha256(checksum_payload).hexdigest()
        _write_result(layout.result_file, result)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        action="append",
        required=True,
        help="TypeScript Playwright spec below tests/e2e; repeat for multiple specs.",
    )
    parser.add_argument("--base-temp", help="Optional external parent for the UUID run root.")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.timeout_seconds < 60:
            raise IsolatedWorkflowHarnessError(
                "invalid-timeout",
                "The isolated acceptance timeout must be at least 60 seconds.",
            )
        validated_temp_parent(args.base_temp)
        result = run_acceptance(
            args.spec,
            base_temp=args.base_temp,
            headed=args.headed,
            timeout_seconds=args.timeout_seconds,
        )
    except BaseException as exc:
        code = (
            exc.code
            if isinstance(exc, IsolatedWorkflowHarnessError)
            else "unexpected-harness-failure"
        )
        message = (
            str(exc)
            if isinstance(exc, IsolatedWorkflowHarnessError)
            else "The isolated harness failed unexpectedly; no unsafe detail was emitted."
        )
        result = {
            "schema_version": 1,
            "ok": False,
            "completed_at": _utc_now(),
            "failure": {"code": code, "message": message},
            "live_data_opened": False,
            "live_services_touched": False,
        }
    # This bounded JSON contains no environment values, credentials, headers,
    # cookies, request bodies, or query strings.
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HarnessLayout",
    "IsolatedWorkflowHarnessError",
    "NetworkDecision",
    "NetworkEvidence",
    "NetworkGuardPolicy",
    "build_backend_environment",
    "build_node_environment",
    "create_harness_layout",
    "network_summary_has_violation",
    "run_acceptance",
    "start_network_guard",
    "validate_playwright_specs",
    "validated_isolated_origin",
    "validated_temp_parent",
]
