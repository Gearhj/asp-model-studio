"""Reverse-isolation middleware for the synthetic integration runtime only."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hmac
import json
import os
from pathlib import Path
import threading
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse


_REQUIRED_BROWSER_HEADERS = frozenset(
    {
        "x-synthetic-principal",
        "x-synthetic-role",
        "x-synthetic-run-id",
        "x-synthetic-tenant",
    }
)
_PROBE_KINDS = frozenset({"backend-smoke", "orchestrator"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _exact_origin(value: str) -> str:
    candidate = value.strip()
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or not parsed.port
        or parsed.port in {5174, 8001}
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise RuntimeError("The isolated frontend origin is invalid.")
    return f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"


def _route_class(path: str) -> str:
    if path == "/health":
        return "health"
    if path.startswith("/api/"):
        return "api"
    return "other"


class SyntheticReverseIsolationGuard:
    """Require one exact run and origin/probe envelope for every request."""

    def __init__(
        self,
        *,
        expected_run_id: str,
        frontend_origin: str,
        violation_path: Path,
    ) -> None:
        run_id = expected_run_id.strip()
        if not run_id or len(run_id) > 256:
            raise RuntimeError("The isolated acceptance run identity is invalid.")
        self._expected_run_id = run_id
        self._frontend_origin = _exact_origin(frontend_origin)
        self._violation_path = violation_path.resolve(strict=False)
        self._violation_path.parent.resolve(strict=True)
        self._lock = threading.RLock()
        self._counts: Counter[str] = Counter()

    def _record_denial(self, request: Request, reason: str) -> None:
        row = {
            "schema_version": "1.0",
            "classification": "synthetic_reverse_isolation_violation",
            "occurred_at": _utc_now(),
            "method": request.method[:8],
            "reason": reason,
            "route_class": _route_class(request.url.path),
            "status": 403,
        }
        encoded = json.dumps(
            row,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ) + "\n"
        if len(encoded.encode("utf-8")) > 768:
            raise RuntimeError("The reverse-isolation evidence row exceeded its bound.")
        with self._lock:
            self._counts["denied_request_count"] += 1
            self._counts[f"denied_{reason}"] += 1
            with self._violation_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())

    def _run_matches(self, request: Request) -> bool:
        supplied = (request.headers.get("x-synthetic-run-id") or "").strip()
        return bool(supplied) and hmac.compare_digest(
            supplied.encode("utf-8"),
            self._expected_run_id.encode("utf-8"),
        )

    def _preflight_allowed(self, request: Request) -> bool:
        if request.url.path.startswith("/api/") is False:
            return False
        if (request.headers.get("origin") or "").strip() != self._frontend_origin:
            return False
        requested = {
            value.strip().casefold()
            for value in (
                request.headers.get("access-control-request-headers") or ""
            ).split(",")
            if value.strip()
        }
        return _REQUIRED_BROWSER_HEADERS.issubset(requested)

    def _actual_request_decision(self, request: Request) -> tuple[bool, str]:
        if not self._run_matches(request):
            return False, "run_identity"
        route_class = _route_class(request.url.path)
        origin = (request.headers.get("origin") or "").strip()
        if origin:
            if origin != self._frontend_origin:
                return False, "origin"
            if route_class != "api":
                return False, "browser_route"
            return True, "browser"
        probe = (request.headers.get("x-synthetic-probe") or "").strip().casefold()
        if route_class == "health" and request.method == "GET" and probe == "health":
            return True, "health_probe"
        if route_class == "api" and probe in _PROBE_KINDS:
            return True, f"{probe}_probe"
        return False, "probe_envelope"

    async def middleware(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method == "OPTIONS":
            if not self._preflight_allowed(request):
                self._record_denial(request, "preflight")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Isolated acceptance request denied."},
                )
            with self._lock:
                self._counts["accepted_preflight_count"] += 1
            return await call_next(request)

        allowed, category = self._actual_request_decision(request)
        if not allowed:
            self._record_denial(request, category)
            return JSONResponse(
                status_code=403,
                content={"detail": "Isolated acceptance request denied."},
            )
        with self._lock:
            self._counts["accepted_request_count"] += 1
            self._counts[f"accepted_{category}_count"] += 1
        return await call_next(request)

    def metrics(self) -> dict[str, object]:
        with self._lock:
            counts = dict(sorted(self._counts.items()))
        persisted_violation = self._violation_path.is_file()
        denied = int(counts.get("denied_request_count", 0))
        return {
            "schema_version": "1.0",
            "classification": "synthetic_reverse_isolation_guard_metrics",
            "exact_run_id_required": True,
            "exact_frontend_origin_required": True,
            "explicit_non_browser_probe_required": True,
            "accepted_request_count": int(counts.get("accepted_request_count", 0)),
            "accepted_preflight_count": int(counts.get("accepted_preflight_count", 0)),
            "denied_request_count": denied,
            "denials_by_reason": {
                key.removeprefix("denied_"): int(value)
                for key, value in counts.items()
                if key.startswith("denied_") and key != "denied_request_count"
            },
            "persistent_violation_evidence_present": persisted_violation,
            "zero_reverse_contamination": denied == 0 and not persisted_violation,
        }


__all__ = ["SyntheticReverseIsolationGuard"]
