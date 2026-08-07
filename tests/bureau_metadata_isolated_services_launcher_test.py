from __future__ import annotations

import ast
from io import StringIO
import json
import os
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from scripts import run_bureau_metadata_isolated_services as launcher


class FakeReservations:
    def __init__(self, backend: int = 19081, frontend: int = 19082) -> None:
        self.ports = {"backend": backend, "frontend": frontend}
        self.released: list[str] = []
        self.closed = False

    def release(self, name: str) -> int:
        self.released.append(name)
        return self.ports[name]

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


def isolated_case_root(label: str) -> Path:
    authority = Path(
        os.environ.get("ATLAS_HERMETIC_ROOT")
        or os.environ.get("TEMP")
        or os.getcwd()
    ).resolve()
    root = authority / "authorities" / "isolated-services-tests" / f"{label}-{uuid.uuid4().hex}"
    root.mkdir(parents=True, exist_ok=False)
    return root


def authority_map(case_root: Path) -> Path:
    base = case_root / "isolated-authorities"
    base.mkdir()
    rows = []
    for name in launcher.REQUIRED_AUTHORITIES:
        root = base / name
        root.mkdir()
        rows.append(
            {
                "authority": name,
                "canonical_path": str(root.resolve()),
                "classification": "isolated",
                "overlap_result": "distinct",
                "reparse_point": False,
            }
        )
    path = case_root / "isolated-authority-map.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "base_root": str(base.resolve()),
                "repository_root": str(launcher.REPOSITORY_ROOT),
                "authorities": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def fake_helpers(events: list[object], *, fail_health: bool = False):
    active = {
        "catalog_version_id": "synthetic-catalog-version-primary",
        "catalog_checksum": "a" * 64,
    }
    secondary = {
        "catalog_version_id": "synthetic-catalog-version-secondary",
        "catalog_checksum": "b" * 64,
    }

    def initialize(restricted, registry):
        events.append(("initialize", restricted, registry))
        return {"1.0": active, "2.0": secondary}

    def grant(scopes, versions):
        events.append(("grant", len(scopes), tuple(versions)))

    def crosswalk(scopes, *, run_id, catalog_version_id):
        events.append(("crosswalk", run_id, catalog_version_id))
        return {
            "governance_id": "synthetic-governance",
            "revision": 1,
            "revision_checksum": "c" * 64,
            "catalog_version_id": catalog_version_id,
            "catalog_checksum": "a" * 64,
        }

    def build(build_root, logs_root, temporary_root, backend_port):
        events.append(("build", backend_port, build_root, logs_root, temporary_root))
        return {"build_checksum": "d" * 64, "vite_hmr_markers_absent": True}

    def start_backend(pins, logs, port, *, cycle):
        assert pins["ATLAS_ISOLATED_ACCEPTANCE_RUN_ID"].startswith("bureau-da-services-")
        assert pins["ATLAS_SQLITE_PATH"]
        assert pins["ATLAS_ISOLATED_CROSSWALK_GOVERNANCE_ID"] == "synthetic-governance"
        events.append(("start-backend", port, cycle, logs))
        return FakeProcess(21001)

    def health(process, *, backend_port, run_id):
        events.append(("health", process.pid, backend_port, run_id))
        if fail_health:
            raise RuntimeError("synthetic health failure")

    def listener(process, port):
        events.append(("listener", process.pid, port))
        return process.pid

    def start_frontend(build_root, logs_root, temporary_root, port):
        events.append(("start-frontend", port, build_root, logs_root, temporary_root))
        return FakeProcess(21002)

    def wait_http(url, process):
        events.append(("http", url, process.pid))

    def stop(process):
        events.append(("stop", None if process is None else process.pid))

    def closed(port):
        events.append(("closed", port))

    return SimpleNamespace(
        _initialize_catalogs_without_global_patch=initialize,
        _grant_integration_entitlements=grant,
        _create_crosswalk_fixture=crosswalk,
        _build_production_frontend=build,
        _start_backend_cycle=start_backend,
        _wait_for_guarded_health=health,
        _wait_for_exact_listener=listener,
        _start_static_frontend=start_frontend,
        _wait_for_http=wait_http,
        _stop_owned_process_tree=stop,
        _wait_for_port_closed=closed,
    )


def test_launcher_has_no_browser_runtime_or_command() -> None:
    source = Path(launcher.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name.casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        str(node.module or "").casefold()
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any("playwright" in name or "selenium" in name for name in imported)
    assert "chromium" not in source.casefold()
    assert ".mjs" not in source.casefold()
    assert "launchpersistentcontext" not in source.casefold()
    assert "subprocess" not in imported


def test_dynamic_non_live_services_emit_one_bounded_ready_line_and_teardown():
    events: list[object] = []
    reservations = FakeReservations()
    output = StringIO()
    environment = {"ATLAS_SQLITE_PATH": "forbidden-live-value", "VITE_API_BASE": "forbidden"}
    waited: list[float] = []
    result = launcher.run_services(
        authority_map(isolated_case_root("ready")),
        lifetime_seconds=0.25,
        output=output,
        reservations=reservations,  # type: ignore[arg-type]
        helpers=fake_helpers(events),
        environment=environment,
        wait=waited.append,
    )
    lines = output.getvalue().splitlines()
    assert len(lines) == 1
    ready = json.loads(lines[0])
    assert ready == result
    assert set(ready) == launcher.READY_KEYS
    assert ready["backend_origin"] == "http://127.0.0.1:19081"
    assert ready["frontend_origin"] == "http://127.0.0.1:19082"
    assert ready["catalog_version_id"] == "synthetic-catalog-version-primary"
    assert ready["secondary_catalog_version_id"] == "synthetic-catalog-version-secondary"
    assert ready["build_checksum"] == "d" * 64
    assert waited == [0.25]
    assert reservations.released == ["backend", "frontend"]
    assert reservations.closed is True
    assert ("stop", 21002) in events and ("stop", 21001) in events
    assert ("closed", 19082) in events and ("closed", 19081) in events
    assert environment["ATLAS_SQLITE_PATH"] != "forbidden-live-value"
    assert "VITE_API_BASE" not in environment


def test_failure_before_ready_still_stops_owned_children_and_verifies_ports():
    events: list[object] = []
    reservations = FakeReservations(19181, 19182)
    output = StringIO()
    with pytest.raises(RuntimeError, match="synthetic health failure"):
        launcher.run_services(
            authority_map(isolated_case_root("failure")),
            lifetime_seconds=0,
            output=output,
            reservations=reservations,  # type: ignore[arg-type]
            helpers=fake_helpers(events, fail_health=True),
            environment={},
            wait=lambda _seconds: None,
        )
    assert output.getvalue() == ""
    assert reservations.closed is True
    assert ("stop", 21001) in events
    assert ("closed", 19182) in events and ("closed", 19181) in events


@pytest.mark.parametrize(
    ("backend_port", "frontend_port"),
    [(8001, 19082), (19081, 5174), (19081, 19081)],
)
def test_ready_payload_rejects_live_or_duplicate_origins(
    backend_port: int, frontend_port: int
) -> None:
    with pytest.raises(Exception):
        launcher._validated_ready_payload(
            run_id="bureau-da-services-" + "a" * 32,
            backend_port=backend_port,
            frontend_port=frontend_port,
            backend_pid=1,
            frontend_pid=2,
            build_checksum="d" * 64,
            catalog_version_id="primary",
            secondary_catalog_version_id="secondary",
        )


def test_cli_exposes_only_dynamic_port_service_controls() -> None:
    parsed = launcher._parser().parse_args(
        ["--authority-map", "isolated-authority-map.json"]
    )
    assert parsed.lifetime_seconds == launcher.DEFAULT_LIFETIME_SECONDS
    option_strings = {
        option
        for action in launcher._parser()._actions
        for option in action.option_strings
    }
    assert "--backend-port" not in option_strings
    assert "--frontend-port" not in option_strings
