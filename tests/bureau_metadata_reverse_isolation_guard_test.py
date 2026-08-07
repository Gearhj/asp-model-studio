from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
import pytest

from tests.bureau_metadata_reverse_isolation_guard import (
    SyntheticReverseIsolationGuard,
)
from tests.hermetic_test_roots import temporary_test_root


RUN_ID = "synthetic-reverse-guard-current-run"
FRONTEND_ORIGIN = "http://127.0.0.1:19082"


@pytest.fixture
def writable_root() -> Path:
    with temporary_test_root(
        "reverse-isolation-guard-",
        scope="reverse-isolation-guard-fixtures",
    ) as root:
        yield root


def _app(root: Path) -> tuple[FastAPI, SyntheticReverseIsolationGuard]:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Content-Type",
            "X-Synthetic-Principal",
            "X-Synthetic-Role",
            "X-Synthetic-Tenant",
            "X-Synthetic-Run-Id",
        ],
    )
    guard = SyntheticReverseIsolationGuard(
        expected_run_id=RUN_ID,
        frontend_origin=FRONTEND_ORIGIN,
        violation_path=root / "integrated-network-isolation-violation.jsonl",
    )

    @app.middleware("http")
    async def reverse_guard(request, call_next):
        return await guard.middleware(request, call_next)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/api/value")
    def value():
        return {"ok": True, "value": "bounded"}

    return app, guard


def _browser_headers(**updates: str) -> dict[str, str]:
    headers = {
        "Origin": FRONTEND_ORIGIN,
        "X-Synthetic-Principal": "synthetic-project-user-alpha",
        "X-Synthetic-Role": "user",
        "X-Synthetic-Tenant": "synthetic-tenant",
        "X-Synthetic-Run-Id": RUN_ID,
    }
    headers.update(updates)
    return headers


def test_exact_current_browser_origin_and_run_succeed_without_violation(
    writable_root: Path,
) -> None:
    app, guard = _app(writable_root)
    with TestClient(app) as client:
        preflight = client.options(
            "/api/value",
            headers={
                "Origin": FRONTEND_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": (
                    "x-synthetic-principal,x-synthetic-role,"
                    "x-synthetic-run-id,x-synthetic-tenant"
                ),
            },
        )
        response = client.get("/api/value", headers=_browser_headers())
    assert preflight.status_code == 200
    assert response.status_code == 200
    assert response.json() == {"ok": True, "value": "bounded"}
    metrics = guard.metrics()
    assert metrics["accepted_preflight_count"] == 1
    assert metrics["accepted_request_count"] == 1
    assert metrics["denied_request_count"] == 0
    assert metrics["persistent_violation_evidence_present"] is False
    assert metrics["zero_reverse_contamination"] is True


def test_missing_or_mismatched_run_and_unexpected_origin_fail_without_leakage(
    writable_root: Path,
) -> None:
    app, guard = _app(writable_root)
    violation = writable_root / "integrated-network-isolation-violation.jsonl"
    with TestClient(app) as client:
        missing = _browser_headers()
        missing.pop("X-Synthetic-Run-Id")
        responses = [
            client.get("/api/value", headers=missing),
            client.get(
                "/api/value",
                headers=_browser_headers(
                    **{"X-Synthetic-Run-Id": "synthetic-other-run"}
                ),
            ),
            client.get(
                "/api/value",
                headers=_browser_headers(Origin="http://127.0.0.1:19083"),
            ),
        ]
    for response in responses:
        assert response.status_code == 403
        assert response.json() == {
            "detail": "Isolated acceptance request denied."
        }
        encoded = json.dumps(response.json(), sort_keys=True)
        assert RUN_ID not in encoded
        assert "synthetic-other-run" not in encoded
        assert FRONTEND_ORIGIN not in encoded
    rows = [json.loads(line) for line in violation.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 3
    assert {row["reason"] for row in rows} == {"run_identity", "origin"}
    evidence = violation.read_text(encoding="utf-8")
    assert RUN_ID not in evidence
    assert "synthetic-other-run" not in evidence
    assert FRONTEND_ORIGIN not in evidence
    metrics = guard.metrics()
    assert metrics["denied_request_count"] == 3
    assert metrics["persistent_violation_evidence_present"] is True
    assert metrics["zero_reverse_contamination"] is False


def test_non_browser_probe_envelope_is_narrow_and_persistent_across_restart(
    writable_root: Path,
) -> None:
    app, guard = _app(writable_root)
    violation = writable_root / "integrated-network-isolation-violation.jsonl"
    base_headers = {"X-Synthetic-Run-Id": RUN_ID}
    with TestClient(app) as client:
        health = client.get(
            "/health",
            headers={**base_headers, "X-Synthetic-Probe": "health"},
        )
        smoke = client.get(
            "/api/value",
            headers={**base_headers, "X-Synthetic-Probe": "backend-smoke"},
        )
        denied = client.get("/health", headers=base_headers)
    assert health.status_code == 200
    assert smoke.status_code == 200
    assert denied.status_code == 403
    assert guard.metrics()["zero_reverse_contamination"] is False

    restarted = SyntheticReverseIsolationGuard(
        expected_run_id=RUN_ID,
        frontend_origin=FRONTEND_ORIGIN,
        violation_path=violation,
    )
    restarted_metrics = restarted.metrics()
    assert restarted_metrics["denied_request_count"] == 0
    assert restarted_metrics["persistent_violation_evidence_present"] is True
    assert restarted_metrics["zero_reverse_contamination"] is False


@pytest.mark.parametrize("origin", ["http://127.0.0.1:5174", "http://127.0.0.1:8001"])
def test_live_frontend_or_backend_port_cannot_be_configured(
    writable_root: Path,
    origin: str,
) -> None:
    with pytest.raises(RuntimeError, match="frontend origin is invalid"):
        SyntheticReverseIsolationGuard(
            expected_run_id=RUN_ID,
            frontend_origin=origin,
            violation_path=writable_root / "violation.jsonl",
        )
