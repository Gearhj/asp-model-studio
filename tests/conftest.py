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
        G.install()


def pytest_runtest_setup(item):
    from tests import _isolated_data_guard as G
    if G._installed["on"]:
        G.set_current_nodeid(item.nodeid)


def pytest_sessionfinish(session, exitstatus):
    from tests import _isolated_data_guard as G
    if not G._installed["on"]:
        return
    out = os.getenv("ASP_ISOLATED_DATA_MANIFEST")
    if not out:
        try:
            from server.sports_cockpit.engine import RUNTIME_ROOT
            out = str(Path(RUNTIME_ROOT) / "isolated-data-violations.json")
        except Exception:
            return
    try:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps({"schema": "PHASE_7D5A2_ISOLATED_DATA_MANIFEST_V1",
                                         "violations": G.violations()}, indent=2), encoding="utf-8")
    except OSError:
        pass
