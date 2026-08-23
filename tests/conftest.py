"""Phase 7D.5A.2 (Repair 7) — under the isolated gate, install the fail-closed external-data access guard.

This conftest is inert in ordinary runs: the guard is installed ONLY when ``ASP_REQUIRE_ISOLATED_RUNTIME`` is set,
so normal-environment test behavior is unchanged. Under the isolated gate it tracks the current test node and writes
a violations manifest at session finish so the runner can prove zero unexpected external-data opens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def pytest_configure(config):
    from tests import _isolated_data_guard as G
    if G.is_active():
        # declare THIS pytest session's basetemp as the one allowed isolated test-temp root, so the narrowed data
        # guard permits tmp_path reads (which live under the isolated audit temp, not the runtime root) while still
        # rejecting the rest of the OS temp tree. A subprocess reader probe that does not load this conftest keeps
        # the strict [runtime + env] roots.
        try:
            bt = getattr(config.option, "basetemp", None)
            if bt:
                os.environ["ASP_ISOLATED_TEST_TEMP"] = str(Path(bt).resolve())
        except Exception:
            pass
        G.install()


def pytest_runtest_setup(item):
    from tests import _isolated_data_guard as G
    if G._installed["on"]:
        G.set_current_nodeid(item.nodeid)


MANIFEST_SCHEMA = "PHASE_7D5A2_ISOLATED_DATA_MANIFEST_V1"


def _fail_session(session, msg: str) -> None:
    import sys
    sys.stderr.write(f"ISOLATED-DATA-MANIFEST FATAL: {msg}\n")
    session.exitstatus = 1


def pytest_sessionfinish(session, exitstatus):
    """R7 — the external-data manifest is MANDATORY under the isolated guard: it is always written, it MERGES with
    any prior (collection-time) violations so execution cannot overwrite them, and a write failure is FATAL (the
    session returns nonzero) rather than silently swallowed."""
    from tests import _isolated_data_guard as G
    if not G._installed["on"]:
        return
    out = os.getenv("ASP_ISOLATED_DATA_MANIFEST")
    if not out:
        try:
            from server.sports_cockpit.engine import RUNTIME_ROOT
            out = str(Path(RUNTIME_ROOT) / "isolated-data-violations.json")
        except Exception:
            out = ""
    if not out:
        _fail_session(session, "no isolated-data manifest path is configured")
        return
    existing = []
    try:
        if Path(out).is_file():
            existing = json.loads(Path(out).read_text(encoding="utf-8")).get("violations", [])
    except Exception:
        existing = []
    merged = list(existing) + [v for v in G.violations() if v not in existing]
    try:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps({"schema": MANIFEST_SCHEMA, "violations": merged}, indent=2), encoding="utf-8")
    except OSError as exc:
        _fail_session(session, f"the mandatory external-data manifest could not be written ({out}): {exc}")
