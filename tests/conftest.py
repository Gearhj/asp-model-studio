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


def pytest_configure(config):
    from tests import _isolated_data_guard as G
    if G.is_active():
        # D7 — generic isolated-session capability bootstrap (production-neutral; no D7 node/fixture knowledge). This
        # session's basetemp is the canonical session root, and the session establishes one random capability. Data
        # authority is then granted ONLY to per-test scratch directories this session marks (see the autouse fixture
        # below); the rest of the OS temp tree — including the bare session root and pytest-of-<user> — is rejected.
        try:
            bt = getattr(config.option, "basetemp", None)
            if bt:
                os.environ["ASP_ISOLATED_TEST_TEMP"] = str(Path(bt).resolve())
        except Exception:
            pass
        G.establish_session_capability()
        G.install()
        # Mark every pytest-created temp directory (function tmp_path AND module/session tmp_path_factory dirs) with
        # the active session's capability, so the guard authorizes exactly those session-owned subtrees. Directories
        # a test hand-constructs under the session root are NOT created here and therefore stay unmarked/rejected.
        try:
            import _pytest.tmpdir as _tmpdir

            _orig_mktemp = _tmpdir.TempPathFactory.mktemp

            def _capability_marked_mktemp(self, basename, numbered=True):
                created = _orig_mktemp(self, basename, numbered=numbered)
                try:
                    G.write_session_marker(created)
                except Exception:
                    pass
                return created

            if getattr(_tmpdir.TempPathFactory.mktemp, "__name__", "") != "_capability_marked_mktemp":
                _tmpdir.TempPathFactory.mktemp = _capability_marked_mktemp
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
