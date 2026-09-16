"""Write exact collection and execution evidence for the Phase 7D.5A.11 runner."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


_COLLECTED: list[str] = []
_PHASES: dict[str, dict[str, dict[str, Any]]] = {}
_COLLECTION_ERRORS: list[str] = []


def _audit_root() -> Path:
    raw = os.environ.get("CODEX_PHASE7D5A11_ACTIVE_PHASE_ROOT", "").strip()
    if not raw:
        raise RuntimeError("CODEX_PHASE7D5A11_ACTIVE_PHASE_ROOT is required")
    root = Path(raw).resolve()
    if not root.is_absolute():
        raise RuntimeError("Phase 7D.5A.11 active phase root must be absolute")
    return root


def _evidence_path(variable: str) -> Path | None:
    raw = os.environ.get(variable, "").strip()
    if not raw:
        return None
    root = _audit_root()
    path = Path(raw).resolve()
    if path != root and root not in path.parents:
        raise RuntimeError(f"{variable} escaped the active phase root")
    return path


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def pytest_collection_finish(session: Any) -> None:
    global _COLLECTED
    _COLLECTED = [item.nodeid.replace("\\", "/") for item in session.items]
    if len(_COLLECTED) != len(set(_COLLECTED)):
        raise RuntimeError("duplicate exact pytest node IDs in Phase 7D.5A.11 collection")
    path = _evidence_path("CODEX_PHASE7D5A11_COLLECTION_MANIFEST")
    if path is not None:
        _atomic_json(
            path,
            {
                "schemaVersion": "CODEX_PHASE7D5A11_COLLECTION_MANIFEST_V1",
                "nodeCount": len(_COLLECTED),
                "nodes": _COLLECTED,
            },
        )


def pytest_collectreport(report: Any) -> None:
    if report.failed:
        _COLLECTION_ERRORS.append(str(report.longrepr))


def pytest_runtest_logreport(report: Any) -> None:
    node = report.nodeid.replace("\\", "/")
    phases = _PHASES.setdefault(node, {})
    phases[report.when] = {
        "outcome": report.outcome,
        "wasxfail": str(report.wasxfail) if hasattr(report, "wasxfail") else None,
        "longrepr": str(report.longrepr) if report.failed else None,
    }


def _status(phases: dict[str, dict[str, Any]]) -> str:
    setup = phases.get("setup", {})
    call = phases.get("call", {})
    teardown = phases.get("teardown", {})
    if setup.get("outcome") == "failed" or teardown.get("outcome") == "failed":
        return "error"
    if setup.get("outcome") == "skipped":
        return "xfailed" if setup.get("wasxfail") else "skipped"
    if call.get("wasxfail"):
        return "xfailed" if call.get("outcome") == "skipped" else "xpassed"
    if call.get("outcome") == "failed":
        return "failed"
    if call.get("outcome") == "skipped":
        return "skipped"
    if call.get("outcome") == "passed":
        return "passed"
    return "error"


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    del session
    path = _evidence_path("CODEX_PHASE7D5A11_EXECUTION_MANIFEST")
    if path is None:
        return
    results = []
    for node in _COLLECTED:
        phases = _PHASES.get(node, {})
        results.append({"nodeId": node, "status": _status(phases), "phases": phases})
    _atomic_json(
        path,
        {
            "schemaVersion": "CODEX_PHASE7D5A11_EXECUTION_MANIFEST_V1",
            "exitStatus": int(exitstatus),
            "collectionErrors": _COLLECTION_ERRORS,
            "resultCount": len(results),
            "results": results,
        },
    )
