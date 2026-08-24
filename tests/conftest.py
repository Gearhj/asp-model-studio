"""Phase 7D.5A.2 (Repair 7) — under the isolated gate, install the fail-closed external-data access guard.

This conftest is inert in ordinary runs: the guard is installed ONLY when ``ASP_REQUIRE_ISOLATED_RUNTIME`` is set,
so normal-environment test behavior is unchanged. Under the isolated gate it tracks the current test node and writes
a violations manifest at session finish so the runner can prove zero unexpected external-data opens.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


@pytest.hookimpl(trylast=True)
def pytest_configure(config):
    from tests import _isolated_data_guard as G
    if not G.is_active():
        return
    # D7 — generic, PROCESS-BOUND isolated-session bootstrap (production-neutral; no D7 node/fixture knowledge). The
    # canonical session root is the ACTUAL basetemp THIS session's tmp_path_factory uses (so the marker + guard agree,
    # including a spawned pytest subprocess that inherits no --basetemp and thus a different basetemp). This process
    # mints its OWN random capability + session nonce (an inherited environment capability is never trusted). Data
    # authority is granted ONLY to per-test scratch directories this session marks below; the rest of the OS temp tree
    # — including the bare session root and pytest-of-<user> — is rejected.
    factory = getattr(config, "_tmp_path_factory", None)
    basetemp = None
    if factory is not None:
        try:
            basetemp = Path(factory.getbasetemp()).resolve()
        except Exception:
            basetemp = None
    if basetemp is None:
        try:
            bt = getattr(getattr(config, "option", None), "basetemp", None)
            if bt:
                basetemp = Path(bt).resolve()
        except Exception:
            basetemp = None
    if basetemp is not None:
        os.environ["ASP_ISOLATED_TEST_TEMP"] = str(basetemp)
    G.establish_session_capability()
    G.install()
    # D7 8.3 — mark every scratch dir the SESSION's OWN factory creates by wrapping THIS factory INSTANCE's mktemp
    # (never the TempPathFactory class). Both the function-scoped ``tmp_path`` and the module/session-scoped
    # ``tmp_path_factory`` route through config._tmp_path_factory, so every session-owned scratch dir is marked; an
    # UNRELATED TempPathFactory constructed elsewhere uses the untouched class method and therefore can neither rebind
    # the active session root nor mint capability markers. A directory a test hand-constructs under the session root is
    # not created through this factory and stays unmarked/rejected.
    if factory is not None and not getattr(factory, "_asp_capability_marking", False):
        try:
            _orig_mktemp = factory.mktemp

            def _capability_marked_mktemp(basename, numbered=True):
                created = _orig_mktemp(basename, numbered=numbered)
                try:
                    G.write_session_marker(created)
                except Exception:
                    pass
                return created

            factory.mktemp = _capability_marked_mktemp
            factory._asp_capability_marking = True
        except Exception:
            pass


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
