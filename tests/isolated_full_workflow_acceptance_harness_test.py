from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time

import pytest

from scripts import run_isolated_full_workflow_acceptance as harness
from scripts.hermetic_test_authority import create_child_authority, create_run_authority
from scripts.isolated_loopback_ports import LIVE_ATLAS_PORTS, reserve_dynamic_non_live_ports


def _external_parent() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(
        prefix="atlas-isolated-workflow-harness-test-",
        dir=tempfile.gettempdir(),
    )


def _layout(parent: str) -> harness.HarnessLayout:
    run = create_run_authority(parent)
    child = create_child_authority(run, "workflow-harness-unit")
    return harness.HarnessLayout(
        child=child,
        frontend_build=child.root / "frontend-build",
        logs=child.root / "logs",
        browser_profile=child.authorities["browser_storage_root"],
        browser_downloads=child.root / "authorities" / "browser-downloads",
        playwright_output=child.authorities["playwright_output_root"],
        screenshots=child.authorities["playwright_output_root"] / "screenshots",
        npm_cache=child.root / "authorities" / "npm-cache",
        network_events=child.authorities["playwright_output_root"] / "network.jsonl",
        result_file=child.authorities["playwright_output_root"] / "result.json",
    )


class _DelayedLargePayloadHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        request_started = getattr(self.server, "request_started")
        request_started.set()
        time.sleep(0.2)
        payload = b"x" * (2 * 1024 * 1024)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(payload)
        except OSError:
            pass


def test_backend_environment_is_exactly_isolated_and_public_registration_is_bounded() -> None:
    with _external_parent() as parent:
        layout = _layout(parent)
        inherited_secret = "must-not-survive-as-an-authority"
        prior = os.environ.get("ATLAS_SQLITE_PATH")
        os.environ["ATLAS_SQLITE_PATH"] = inherited_secret
        try:
            environment = harness.build_backend_environment(
                layout,
                backend_origin="http://127.0.0.1:19081",
                frontend_origin="http://127.0.0.1:19082",
            )
        finally:
            if prior is None:
                os.environ.pop("ATLAS_SQLITE_PATH", None)
            else:
                os.environ["ATLAS_SQLITE_PATH"] = prior

        assert environment["ATLAS_AUTH_ENABLED"] == "1"
        assert environment["ATLAS_ALLOW_PUBLIC_REGISTRATION"] == "1"
        assert environment["ATLAS_LOCAL_DEV"] == "0"
        assert environment["ATLAS_DEV_MODE"] == "0"
        assert environment["ATLAS_HOSTED_MODE"] == "0"
        assert environment["ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP"] == "0"
        assert environment["ATLAS_ENABLE_DEV_USER_HEADER"] == "0"
        assert environment["ATLAS_DEV_AUTH_TOOLS"] == "0"
        assert environment["ATLAS_CORS_ORIGINS"] == "http://127.0.0.1:19082"
        assert environment["ATLAS_TEST_BACKEND_URL"] == "http://127.0.0.1:19081"
        assert environment["ATLAS_SQLITE_PATH"] != inherited_secret
        assert Path(environment["ATLAS_SQLITE_PATH"]).is_relative_to(layout.child.root)
        assert len(environment["ATLAS_SESSION_SECRET"]) >= 32


def test_node_environment_forces_external_outputs_and_guarded_origins() -> None:
    with _external_parent() as parent:
        layout = _layout(parent)
        environment = harness.build_node_environment(
            layout,
            backend_origin="http://127.0.0.1:19181",
            frontend_origin="http://127.0.0.1:19182",
            proxy_origin="http://127.0.0.1:19183",
            headed=False,
        )
        assert environment["VITE_API_BASE"] == "http://127.0.0.1:19181/api"
        assert environment["ATLAS_E2E_BASE_URL"] == "http://127.0.0.1:19182"
        assert environment["ATLAS_E2E_BACKEND_URL"] == "http://127.0.0.1:19181"
        assert environment["ATLAS_E2E_NETWORK_GUARD_PROXY"] == "http://127.0.0.1:19183"
        assert environment["ATLAS_E2E_HEADLESS"] == "1"
        assert Path(environment["ATLAS_PLAYWRIGHT_OUTPUT_ROOT"]).is_relative_to(
            layout.child.root
        )
        assert Path(environment["ATLAS_BROWSER_STORAGE_ROOT"]).is_relative_to(
            layout.child.root
        )
        assert Path(environment["TEMP"]).is_relative_to(layout.child.root)
        assert "ATLAS_SESSION_SECRET" not in environment


@pytest.mark.parametrize(
    "origin",
    (
        "http://127.0.0.1:5174",
        "http://127.0.0.1:8001",
        "http://localhost:19081",
        "https://127.0.0.1:19081",
        "http://user:secret@127.0.0.1:19081",
        "http://127.0.0.1:19081/path",
    ),
)
def test_isolated_origin_rejects_live_nonexact_or_credentialed_values(origin: str) -> None:
    with pytest.raises(harness.IsolatedWorkflowHarnessError):
        harness.validated_isolated_origin(origin)


def test_network_policy_allows_only_the_two_exact_origins_and_redacts_query() -> None:
    policy = harness.NetworkGuardPolicy(
        ("http://127.0.0.1:19281", "http://127.0.0.1:19282")
    )
    frontend = policy.decide("http://127.0.0.1:19281/assets/app.js?token=secret")
    backend = policy.decide("http://127.0.0.1:19282/api/projects")
    assert frontend.allowed is True and frontend.path == "/assets/app.js"
    assert backend.allowed is True

    cases = {
        "live": policy.decide("http://127.0.0.1:8001/api/projects"),
        "unexpected": policy.decide("http://example.test/resource"),
        "frontend_api": policy.decide("http://127.0.0.1:19281/api/projects"),
        "backend_non_api": policy.decide("http://127.0.0.1:19282/projects"),
        "websocket": policy.decide(
            "http://127.0.0.1:19281/socket", upgrade="websocket"
        ),
        "connect": policy.decide("example.test:443", method="CONNECT"),
    }
    assert cases["live"].reason == "live_port"
    assert cases["unexpected"].reason == "unexpected_origin"
    assert cases["frontend_api"].reason == "frontend_api"
    assert cases["backend_non_api"].reason == "backend_non_api"
    assert cases["websocket"].reason == "websocket"
    assert cases["connect"].reason == "connect_tunnel"
    assert all(not decision.allowed for decision in cases.values())


def test_listener_ownership_accepts_only_the_spawned_process_tree() -> None:
    parents = {
        400: 300,
        300: 200,
        200: 100,
        999: 998,
        998: 0,
        777: 776,
        776: 777,
    }
    lookup = lambda process_id: parents.get(process_id)

    assert harness._listener_belongs_to_process_tree(100, 100, lookup)
    assert harness._listener_belongs_to_process_tree(200, 100, lookup)
    assert harness._listener_belongs_to_process_tree(400, 100, lookup)
    assert not harness._listener_belongs_to_process_tree(999, 100, lookup)
    assert not harness._listener_belongs_to_process_tree(777, 100, lookup)
    assert not harness._listener_belongs_to_process_tree(0, 100, lookup)


def test_network_evidence_never_serializes_query_headers_or_body() -> None:
    with _external_parent() as parent:
        path = Path(parent) / "network.jsonl"
        evidence = harness.NetworkEvidence(path)
        evidence.record(
            harness.NetworkDecision(
                allowed=False,
                reason="unexpected_origin",
                origin="http://example.test",
                path="/resource",
            ),
            "GET",
        )
        payload = path.read_text(encoding="utf-8")
        row = json.loads(payload)
        assert set(row) == {
            "schema_version",
            "occurred_at",
            "method",
            "outcome",
            "reason",
            "origin",
            "path",
        }
        assert "token" not in payload
        assert "cookie" not in payload.casefold()
        assert evidence.summary()["unexpected_origin"] == 1


def test_client_disconnect_after_healthy_upstream_is_nonfatal_downstream_evidence() -> None:
    with _external_parent() as parent:
        reservations = reserve_dynamic_non_live_ports(
            ("frontend", "backend", "network_guard")
        )
        ports = dict(reservations.ports)
        upstream: ThreadingHTTPServer | None = None
        upstream_thread: threading.Thread | None = None
        guard: harness.RunningNetworkGuard | None = None
        client: socket.socket | None = None
        try:
            reservations.release("frontend")
            upstream = ThreadingHTTPServer(
                (harness.LOOPBACK_HOST, ports["frontend"]),
                _DelayedLargePayloadHandler,
            )
            upstream.request_started = threading.Event()  # type: ignore[attr-defined]
            upstream_thread = threading.Thread(
                target=upstream.serve_forever,
                name="isolated-guard-test-upstream",
                daemon=True,
            )
            upstream_thread.start()

            frontend_origin = f"http://{harness.LOOPBACK_HOST}:{ports['frontend']}"
            backend_origin = f"http://{harness.LOOPBACK_HOST}:{ports['backend']}"
            evidence_path = Path(parent) / "disconnect-network.jsonl"
            evidence = harness.NetworkEvidence(evidence_path)
            policy = harness.NetworkGuardPolicy((frontend_origin, backend_origin))
            reservations.release("network_guard")
            guard = harness.start_network_guard(
                ports["network_guard"], policy, evidence
            )

            client = socket.create_connection(
                (harness.LOOPBACK_HOST, ports["network_guard"]), timeout=5
            )
            request = (
                f"GET {frontend_origin}/payload?private-marker=must-not-record "
                "HTTP/1.1\r\n"
                f"Host: {harness.LOOPBACK_HOST}:{ports['frontend']}\r\n"
                "Connection: close\r\n\r\n"
            )
            client.sendall(request.encode("ascii"))
            assert upstream.request_started.wait(5)  # type: ignore[attr-defined]
            linger_format = "hh" if os.name == "nt" else "ii"
            client.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_LINGER,
                struct.pack(linger_format, 1, 0),
            )
            client.close()
            client = None

            deadline = time.monotonic() + 8
            while (
                evidence.summary()["downstream_disconnect"] == 0
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)

            summary = evidence.summary()
            assert summary["allowed"] == 1
            assert summary["upstream_error"] == 0
            assert summary["downstream_disconnect"] == 1
            assert harness.network_summary_has_violation(summary) is False

            serialized = evidence_path.read_text(encoding="utf-8")
            rows = [json.loads(line) for line in serialized.splitlines()]
            transport = [row for row in rows if row["outcome"] == "transport_error"]
            assert len(transport) == 1
            assert transport[0]["reason"] == "downstream_disconnect"
            assert transport[0]["phase"] == "downstream"
            assert transport[0]["path"] == "/payload"
            assert transport[0]["error_type"] in {
                "BrokenPipeError",
                "ConnectionAbortedError",
                "ConnectionResetError",
            }
            assert "must-not-record" not in serialized
        finally:
            if client is not None:
                client.close()
            if guard is not None:
                guard.stop()
            if upstream is not None:
                upstream.shutdown()
                upstream.server_close()
            if upstream_thread is not None:
                upstream_thread.join(timeout=5)
            reservations.close()


def test_unavailable_allowed_upstream_remains_a_fatal_network_violation() -> None:
    with _external_parent() as parent:
        reservations = reserve_dynamic_non_live_ports(
            ("frontend", "backend", "network_guard")
        )
        ports = dict(reservations.ports)
        guard: harness.RunningNetworkGuard | None = None
        connection = None
        try:
            frontend_origin = f"http://{harness.LOOPBACK_HOST}:{ports['frontend']}"
            backend_origin = f"http://{harness.LOOPBACK_HOST}:{ports['backend']}"
            evidence_path = Path(parent) / "unavailable-network.jsonl"
            evidence = harness.NetworkEvidence(evidence_path)
            policy = harness.NetworkGuardPolicy((frontend_origin, backend_origin))
            reservations.release("backend")
            reservations.release("network_guard")
            guard = harness.start_network_guard(
                ports["network_guard"], policy, evidence
            )

            connection = harness.http.client.HTTPConnection(
                harness.LOOPBACK_HOST, ports["network_guard"], timeout=5
            )
            connection.request("GET", f"{backend_origin}/api/unavailable")
            response = connection.getresponse()
            assert response.status == 502
            response.read()

            summary = evidence.summary()
            assert summary["allowed"] == 1
            assert summary["upstream_error"] == 1
            assert summary["downstream_disconnect"] == 0
            assert harness.network_summary_has_violation(summary) is True

            rows = [
                json.loads(line)
                for line in evidence_path.read_text(encoding="utf-8").splitlines()
            ]
            transport = [row for row in rows if row["outcome"] == "transport_error"]
            assert len(transport) == 1
            assert transport[0]["reason"] == "upstream_error"
            assert transport[0]["phase"] == "upstream"
            assert transport[0]["path"] == "/api/unavailable"
            assert "message" not in transport[0]
        finally:
            if connection is not None:
                connection.close()
            if guard is not None:
                guard.stop()
            reservations.close()


def test_spec_validation_accepts_stage_a_and_rejects_session_seed_stage_b() -> None:
    accepted = harness.validate_playwright_specs(
        ("predictive-modeling-classification-stage-a.spec.ts",)
    )
    assert accepted == ("predictive-modeling-classification-stage-a.spec.ts",)
    with pytest.raises(harness.IsolatedWorkflowHarnessError, match="session state"):
        harness.validate_playwright_specs(
            ("predictive-modeling-classification-stage-b.spec.ts",)
        )
    with pytest.raises(harness.IsolatedWorkflowHarnessError):
        harness.validate_playwright_specs(("../regression.test.mjs",))


def test_isolated_playwright_config_requires_proxy_and_external_authorities() -> None:
    config = Path(harness.ISOLATED_PLAYWRIGHT_CONFIG).read_text(encoding="utf-8")
    helper = (harness.E2E_ROOT / "helpers" / "isolatedHarness.ts").read_text(
        encoding="utf-8"
    )
    assert 'serviceWorkers: "block"' in config
    assert "proxy: { server: isolated.proxyOrigin }" in config
    assert '"--proxy-bypass-list=<-loopback>"' in helper
    for variable in (
        "ATLAS_E2E_BASE_URL",
        "ATLAS_E2E_BACKEND_URL",
        "ATLAS_E2E_NETWORK_GUARD_PROXY",
        "ATLAS_PLAYWRIGHT_OUTPUT_ROOT",
        "ATLAS_BROWSER_STORAGE_ROOT",
    ):
        assert variable in helper
    assert "http://127.0.0.1:5174" not in config
    assert "http://127.0.0.1:8001" not in config


def test_three_service_ports_are_held_distinct_and_never_use_live_ports() -> None:
    reservations = reserve_dynamic_non_live_ports(
        ("backend", "frontend", "network_guard")
    )
    try:
        assert set(reservations.ports) == {"backend", "frontend", "network_guard"}
        assert len(set(reservations.ports.values())) == 3
        assert not set(reservations.ports.values()).intersection(LIVE_ATLAS_PORTS)
        reservations.assert_exact(reservations.ports)
    finally:
        reservations.close()


def test_cli_requires_at_least_one_named_spec_and_exposes_no_port_override() -> None:
    parser = harness._parser()
    parsed = parser.parse_args(
        ["--spec", "predictive-modeling-classification-stage-a.spec.ts"]
    )
    assert parsed.spec == ["predictive-modeling-classification-stage-a.spec.ts"]
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--backend-port" not in option_strings
    assert "--frontend-port" not in option_strings
