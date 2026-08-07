"""Start only the isolated Bureau Metadata integration services.

The launcher deliberately contains no browser automation.  It validates the
existing 21-authority synthetic map, creates one run-specific child per
authority, pins every mutable runtime root before importing ATLAS server code,
builds the non-HMR production frontend, and starts the guarded synthetic
integration backend plus a static frontend on reserved OS-assigned ports.

Standard output contains exactly one flushed, sanitized readiness object.  The
process then waits for the requested lifetime and always tears down only the
two child process trees it owns.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import secrets
import socket
import sys
import time
from typing import Any, Callable, Mapping, MutableMapping, Sequence, TextIO
import uuid

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.isolated_loopback_ports import (
    LIVE_ATLAS_PORTS,
    ReservedLoopbackPorts,
    reserve_dynamic_non_live_ports,
    validate_non_live_ports,
)


REQUIRED_AUTHORITIES = (
    "persistence-database",
    "security-database",
    "audit-authority",
    "catalog-registry",
    "restricted-catalog",
    "catalog-install-journal",
    "project-registry",
    "dataset-registry",
    "project-links",
    "dataset-library",
    "workflow-checkpoint",
    "evidence-registry",
    "documentation-registry",
    "feature-manifests",
    "model-registry",
    "temporary-files",
    "browser-profile",
    "browser-downloads",
    "test-output",
    "logs",
    "frontend-build",
)
MAX_LIFETIME_SECONDS = 14_400.0
DEFAULT_LIFETIME_SECONDS = 3_600.0
SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|COOKIE|API_?KEY|AUTHORIZATION|DATABASE_URL|DSN)",
    re.IGNORECASE,
)
READY_KEYS = frozenset(
    {
        "run_id",
        "frontend_origin",
        "backend_origin",
        "backend_pid",
        "frontend_pid",
        "build_checksum",
        "catalog_version_id",
        "secondary_catalog_version_id",
    }
)


class IsolatedServicesError(RuntimeError):
    """Fail-closed launcher error whose message contains no physical path."""


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    return bool(int(getattr(path.stat(), "st_file_attributes", 0)) & 0x400)


def _load_authority_map(path: Path) -> tuple[Path, dict[str, Path]]:
    try:
        exact = Path(path).expanduser().resolve(strict=True)
        payload = json.loads(exact.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IsolatedServicesError("The isolated authority map is unavailable.") from exc
    if not isinstance(payload, Mapping) or int(payload.get("schema_version", 0)) != 1:
        raise IsolatedServicesError("The isolated authority map schema is unsupported.")
    try:
        base = Path(str(payload.get("base_root") or "")).resolve(strict=True)
        repository = Path(str(payload.get("repository_root") or "")).resolve(strict=True)
    except OSError as exc:
        raise IsolatedServicesError("The isolated authority boundary is unavailable.") from exc
    if (
        repository != REPOSITORY_ROOT
        or base == repository
        or repository in base.parents
        or base in repository.parents
        or _is_reparse_point(base)
    ):
        raise IsolatedServicesError("The isolated authority boundary is contradictory.")
    rows = payload.get("authorities")
    if not isinstance(rows, list):
        raise IsolatedServicesError("The isolated authority inventory is unavailable.")
    roots: dict[str, Path] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise IsolatedServicesError("The isolated authority inventory is invalid.")
        name = str(row.get("authority") or "").strip()
        try:
            candidate = Path(str(row.get("canonical_path") or "")).resolve(strict=True)
        except OSError as exc:
            raise IsolatedServicesError("An isolated authority is unavailable.") from exc
        if (
            not name
            or name in roots
            or candidate.parent != base
            or not candidate.is_dir()
            or _is_reparse_point(candidate)
            or row.get("classification") != "isolated"
            or row.get("overlap_result") != "distinct"
            or bool(row.get("reparse_point"))
        ):
            raise IsolatedServicesError("An isolated authority failed validation.")
        roots[name] = candidate
    if set(roots) != set(REQUIRED_AUTHORITIES) or len(set(roots.values())) != len(roots):
        raise IsolatedServicesError("The isolated authority inventory is incomplete.")
    return base, roots


def _create_run_scopes(roots: Mapping[str, Path]) -> tuple[str, dict[str, Path]]:
    run_id = "bureau-da-services-" + uuid.uuid4().hex
    scopes: dict[str, Path] = {}
    for name in REQUIRED_AUTHORITIES:
        scope = roots[name] / run_id
        scope.mkdir(parents=False, exist_ok=False)
        scopes[name] = scope.resolve(strict=True)
    if len(set(scopes.values())) != len(REQUIRED_AUTHORITIES):
        raise IsolatedServicesError("Run-specific authority scopes overlap.")
    return run_id, scopes


def _environment_pins(
    base: Path,
    scopes: Mapping[str, Path],
    *,
    run_id: str,
    backend_port: int,
    frontend_port: int,
) -> dict[str, str]:
    validate_non_live_ports((backend_port, frontend_port))
    temporary = scopes["temporary-files"]
    backup = temporary / "dataset-library-backup"
    python_runtime = temporary / "python-runtime"
    local_app_data = temporary / "local-app-data"
    sas_config = temporary / "sas-config"
    scoring = scopes["model-registry"] / "scoring-runs"
    vif_plans = scopes["feature-manifests"] / "vif-plans"
    for directory in (backup, python_runtime, local_app_data, sas_config, scoring, vif_plans):
        directory.mkdir(parents=False, exist_ok=False)
    frontend_origin = f"http://127.0.0.1:{frontend_port}"
    return {
        "ATLAS_ISOLATED_AUTHORITY_BASE_ROOT": str(base),
        "ATLAS_SQLITE_PATH": str(scopes["persistence-database"] / "atlas_local.sqlite3"),
        "ATLAS_SECURITY_ROOT": str(scopes["security-database"]),
        "ATLAS_SECURITY_DB_PATH": str(scopes["security-database"] / "atlas_security.sqlite3"),
        "ATLAS_ISOLATED_BUREAU_AUDIT_ROOT": str(scopes["audit-authority"]),
        "ATLAS_BUREAU_CATALOG_REGISTRY_ROOT": str(scopes["catalog-registry"]),
        "ATLAS_ISOLATED_BUREAU_ACCEPTANCE_ROOT": str(scopes["restricted-catalog"]),
        "ATLAS_RESTRICTED_METADATA_ROOT": str(scopes["restricted-catalog"]),
        "ATLAS_ISOLATED_CATALOG_INSTALL_JOURNAL_ROOT": str(scopes["catalog-install-journal"]),
        "ATLAS_ISOLATED_PROJECT_REGISTRY_ROOT": str(scopes["project-registry"]),
        "ATLAS_ISOLATED_DATASET_REGISTRY_ROOT": str(scopes["dataset-registry"]),
        "ATLAS_ISOLATED_PROJECT_LINKS_ROOT": str(scopes["project-links"]),
        "ATLAS_DATASET_LIBRARY_ROOT": str(scopes["dataset-library"]),
        "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(backup),
        "ATLAS_CHECKPOINT_PATH": str(scopes["workflow-checkpoint"] / "workflow_checkpoint.json"),
        "ATLAS_EVIDENCE_ROOT": str(scopes["evidence-registry"]),
        "ATLAS_ISOLATED_DOCUMENTATION_REGISTRY_ROOT": str(scopes["documentation-registry"]),
        "ATLAS_FEATURE_MANIFEST_ROOT": str(scopes["feature-manifests"]),
        "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": str(scopes["model-registry"]),
        "ATLAS_SCORING_RUN_ARTIFACT_ROOT": str(scoring),
        "ATLAS_VIF_PLAN_ROOT": str(vif_plans),
        "ATLAS_BROWSER_STORAGE_ROOT": str(scopes["browser-profile"]),
        "ATLAS_PLAYWRIGHT_OUTPUT_ROOT": str(scopes["test-output"]),
        "ATLAS_ISOLATED_LOG_ROOT": str(scopes["logs"]),
        "ATLAS_ISOLATED_FRONTEND_BUILD_ROOT": str(scopes["frontend-build"]),
        "ATLAS_PYTHON_RUNTIME_DIR": str(python_runtime),
        "ATLAS_SAS_CONFIG_DIR": str(sas_config),
        "ATLAS_ISOLATED_BUREAU_FRONTEND_ORIGIN": frontend_origin,
        "ATLAS_CORS_ORIGINS": frontend_origin,
        "ATLAS_ISOLATED_ACCEPTANCE_RUN_ID": run_id,
        "ATLAS_ENV": "testing",
        "ATLAS_TEST_MODE": "1",
        "ATLAS_AUTH_ENABLED": "true",
        "ATLAS_LOCAL_DEV": "false",
        "ATLAS_DEV_MODE": "false",
        "ATLAS_HOSTED_MODE": "false",
        "ATLAS_ENABLE_DEV_USER_HEADER": "false",
        "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "false",
        "ATLAS_ALLOW_PUBLIC_REGISTRATION": "false",
        "ATLAS_SESSION_SECRET": secrets.token_urlsafe(48),
        "LOCALAPPDATA": str(local_app_data),
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "PYTHONPYCACHEPREFIX": str(temporary / "python-cache"),
    }


def _apply_preimport_pins(
    environment: MutableMapping[str, str], pins: Mapping[str, str]
) -> None:
    for name in tuple(environment):
        if name.upper().startswith(("ATLAS_", "VITE_")) or SENSITIVE_ENVIRONMENT_NAME.search(name):
            environment.pop(name, None)
    environment.update({str(name): str(value) for name, value in pins.items()})


def _load_integration_helpers():
    # This import is intentionally local.  All authority pins are installed by
    # _apply_preimport_pins before this function is called.
    from scripts import run_bureau_metadata_integrated_closeout as closeout

    return closeout


def _port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        return probe.connect_ex(("127.0.0.1", int(port))) == 0


def _wait_for_port_closed_local(port: int, *, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_is_open(port):
            return
        time.sleep(0.05)
    raise IsolatedServicesError("An owned isolated listener did not close.")


def _validated_ready_payload(
    *,
    run_id: str,
    backend_port: int,
    frontend_port: int,
    backend_pid: int,
    frontend_pid: int,
    build_checksum: str,
    catalog_version_id: str,
    secondary_catalog_version_id: str,
) -> dict[str, Any]:
    validate_non_live_ports((backend_port, frontend_port))
    if set((backend_port, frontend_port)).intersection(LIVE_ATLAS_PORTS):
        raise IsolatedServicesError("A readiness origin references a live ATLAS port.")
    if (
        not run_id.startswith("bureau-da-services-")
        or int(backend_pid) < 1
        or int(frontend_pid) < 1
        or len(build_checksum) != 64
        or any(character not in "0123456789abcdef" for character in build_checksum)
        or not str(catalog_version_id).strip()
        or not str(secondary_catalog_version_id).strip()
    ):
        raise IsolatedServicesError("The isolated readiness identity is invalid.")
    payload = {
        "run_id": run_id,
        "frontend_origin": f"http://127.0.0.1:{frontend_port}",
        "backend_origin": f"http://127.0.0.1:{backend_port}",
        "backend_pid": int(backend_pid),
        "frontend_pid": int(frontend_pid),
        "build_checksum": build_checksum,
        "catalog_version_id": str(catalog_version_id),
        "secondary_catalog_version_id": str(secondary_catalog_version_id),
    }
    if set(payload) != READY_KEYS:
        raise IsolatedServicesError("The readiness payload is not bounded.")
    return payload


def run_services(
    authority_map: Path,
    *,
    lifetime_seconds: float,
    output: TextIO = sys.stdout,
    reservations: ReservedLoopbackPorts | None = None,
    helpers: Any | None = None,
    environment: MutableMapping[str, str] | None = None,
    wait: Callable[[float], Any] = time.sleep,
) -> Mapping[str, Any]:
    """Start the two isolated services, emit readiness, wait, and tear down."""

    if not (0.0 <= float(lifetime_seconds) <= MAX_LIFETIME_SECONDS):
        raise IsolatedServicesError("The isolated service lifetime is invalid.")
    owned_reservations = reservations or reserve_dynamic_non_live_ports()
    ports = dict(owned_reservations.ports)
    if set(ports) != {"backend", "frontend"}:
        owned_reservations.close()
        raise IsolatedServicesError("The isolated dynamic port plan is incomplete.")
    backend_port = int(ports["backend"])
    frontend_port = int(ports["frontend"])
    validate_non_live_ports((backend_port, frontend_port))
    backend = None
    frontend = None
    helper = helpers
    ready: Mapping[str, Any] | None = None
    teardown_errors: list[BaseException] = []
    try:
        base, roots = _load_authority_map(authority_map)
        run_id, scopes = _create_run_scopes(roots)
        pins = _environment_pins(
            base,
            scopes,
            run_id=run_id,
            backend_port=backend_port,
            frontend_port=frontend_port,
        )
        target_environment = environment if environment is not None else os.environ
        _apply_preimport_pins(target_environment, pins)
        if helper is None:
            if target_environment is not os.environ:
                raise IsolatedServicesError("Real helper imports require the pinned process environment.")
            helper = _load_integration_helpers()

        versions = helper._initialize_catalogs_without_global_patch(
            scopes["restricted-catalog"], scopes["catalog-registry"]
        )
        helper._grant_integration_entitlements(scopes, versions)
        active = versions["1.0"]
        secondary = versions["2.0"]
        recovery = helper._create_crosswalk_fixture(
            scopes,
            run_id=run_id,
            catalog_version_id=str(active["catalog_version_id"]),
        )
        recovery_pins = {
            "ATLAS_ISOLATED_CROSSWALK_GOVERNANCE_ID": str(recovery["governance_id"]),
            "ATLAS_ISOLATED_CROSSWALK_REVISION": str(recovery["revision"]),
            "ATLAS_ISOLATED_CROSSWALK_CHECKSUM": str(recovery["revision_checksum"]),
            "ATLAS_ISOLATED_RECOVERY_CATALOG_VERSION_ID": str(recovery["catalog_version_id"]),
            "ATLAS_ISOLATED_RECOVERY_CATALOG_CHECKSUM": str(recovery["catalog_checksum"]),
        }
        pins.update(recovery_pins)
        target_environment.update(recovery_pins)
        production_build = helper._build_production_frontend(
            scopes["frontend-build"],
            scopes["logs"],
            scopes["temporary-files"],
            backend_port,
        )
        if production_build.get("vite_hmr_markers_absent") is not True:
            raise IsolatedServicesError("The isolated production build was not HMR-free.")

        owned_reservations.release("backend")
        backend = helper._start_backend_cycle(
            pins, scopes["logs"], backend_port, cycle=0
        )
        helper._wait_for_guarded_health(
            backend, backend_port=backend_port, run_id=run_id
        )
        backend_pid = helper._wait_for_exact_listener(backend, backend_port)

        owned_reservations.release("frontend")
        frontend = helper._start_static_frontend(
            scopes["frontend-build"],
            scopes["logs"],
            scopes["temporary-files"],
            frontend_port,
        )
        helper._wait_for_http(
            f"http://127.0.0.1:{frontend_port}/", frontend
        )
        frontend_pid = helper._wait_for_exact_listener(frontend, frontend_port)
        ready = _validated_ready_payload(
            run_id=run_id,
            backend_port=backend_port,
            frontend_port=frontend_port,
            backend_pid=backend_pid,
            frontend_pid=frontend_pid,
            build_checksum=str(production_build["build_checksum"]),
            catalog_version_id=str(active["catalog_version_id"]),
            secondary_catalog_version_id=str(secondary["catalog_version_id"]),
        )
        output.write(json.dumps(ready, sort_keys=True, separators=(",", ":")) + "\n")
        output.flush()
        wait(float(lifetime_seconds))
        return ready
    finally:
        if helper is not None:
            for process in (frontend, backend):
                try:
                    helper._stop_owned_process_tree(process)
                except BaseException as exc:  # teardown must continue for both children
                    teardown_errors.append(exc)
        owned_reservations.close()
        for port in (frontend_port, backend_port):
            try:
                if helper is not None:
                    helper._wait_for_port_closed(port)
                else:
                    _wait_for_port_closed_local(port)
            except BaseException as exc:
                teardown_errors.append(exc)
        if teardown_errors and sys.exc_info()[0] is None:
            raise IsolatedServicesError("Isolated service teardown verification failed.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-map", required=True, type=Path)
    parser.add_argument(
        "--lifetime-seconds",
        type=float,
        default=DEFAULT_LIFETIME_SECONDS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        run_services(
            args.authority_map,
            lifetime_seconds=args.lifetime_seconds,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        sys.stderr.write(
            json.dumps(
                {"ready": False, "failure_type": type(exc).__name__},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        sys.stderr.flush()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
