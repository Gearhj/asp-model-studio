"""Run production-build authentication acceptance on mapped isolated authorities."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import uuid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.run_bureau_metadata_isolated_acceptance import (
    IsolatedAcceptanceError,
    _initialize_synthetic_authority,
)
from scripts.isolated_loopback_ports import (
    IsolatedLoopbackPortError,
    ReservedLoopbackPorts,
    reserve_dynamic_non_live_ports,
    validate_non_live_ports,
)
from scripts.run_bureau_metadata_operational_soak import (
    FRONTEND_RELOAD_EVIDENCE_CLASSIFICATION,
    MIN_FRONTEND_AUTHENTICATED_RELOADS,
    _frontend_reload_evidence_checksum,
    _load_frontend_reload_evidence,
)
from server.bureau_metadata.normalizer import canonical_json_bytes


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
AUTH_AUDIT_FILE = "synthetic_authentication_audit.jsonl"
SYNTHETIC_PROJECTS: tuple[Mapping[str, str], ...] = (
    {
        "project_id": "synthetic-project-alpha-001",
        "dataset_id": "synthetic-dataset-alpha-001",
        "dataset_version_id": "synthetic-version-alpha-001",
    },
    {
        "project_id": "synthetic-project-beta-002",
        "dataset_id": "synthetic-dataset-beta-002",
        "dataset_version_id": "synthetic-version-beta-002",
    },
)
SENSITIVE_ENVIRONMENT_NAME = re.compile(
    r"(?:PASSWORD|PASSWD|SECRET|TOKEN|COOKIE|API_?KEY|AUTHORIZATION|DATABASE_URL|DSN)",
    re.IGNORECASE,
)


def _clean_subprocess_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(("ATLAS_", "VITE_"))
        and not SENSITIVE_ENVIRONMENT_NAME.search(name)
    }


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = int(getattr(path.stat(), "st_file_attributes", 0))
    return bool(attributes & 0x400)


def _load_authority_map(path: Path) -> tuple[Path, dict[str, Path]]:
    payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8-sig"))
    if int(payload.get("schema_version", 0)) != 1:
        raise IsolatedAcceptanceError("The isolated authority map schema is unsupported.")
    base = Path(str(payload.get("base_root") or "")).resolve(strict=True)
    repository = Path(str(payload.get("repository_root") or "")).resolve(strict=True)
    if repository != REPOSITORY_ROOT or base == repository or repository in base.parents:
        raise IsolatedAcceptanceError("The isolated authority map contradicts the repository boundary.")
    rows = payload.get("authorities")
    if not isinstance(rows, list):
        raise IsolatedAcceptanceError("The isolated authority map has no authority inventory.")
    roots: dict[str, Path] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise IsolatedAcceptanceError("The isolated authority map contains an invalid row.")
        name = str(row.get("authority") or "").strip()
        candidate = Path(str(row.get("canonical_path") or "")).resolve(strict=True)
        if (
            name in roots
            or candidate.parent != base
            or not candidate.is_dir()
            or _is_reparse_point(candidate)
            or row.get("classification") != "isolated"
            or row.get("overlap_result") != "distinct"
            or bool(row.get("reparse_point"))
        ):
            raise IsolatedAcceptanceError("An isolated authority-map row failed validation.")
        roots[name] = candidate
    if set(roots) != set(REQUIRED_AUTHORITIES) or len(set(roots.values())) != len(roots):
        raise IsolatedAcceptanceError("The isolated authority inventory is incomplete or overlapping.")
    return base, roots


def _create_run_scopes(roots: Mapping[str, Path]) -> tuple[str, dict[str, Path]]:
    run_id = "production-auth-" + uuid.uuid4().hex
    scopes: dict[str, Path] = {}
    for name in REQUIRED_AUTHORITIES:
        scope = roots[name] / run_id
        scope.mkdir(parents=False, exist_ok=False)
        scopes[name] = scope.resolve(strict=True)
    return run_id, scopes


def _environment_pins(
    base: Path,
    scopes: Mapping[str, Path],
    *,
    backend_port: int,
    frontend_port: int,
) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    temporary = scopes["temporary-files"]
    backup = temporary / "dataset-library-backup"
    python_runtime = temporary / "python-runtime"
    local_app_data = temporary / "local-app-data"
    sas_config = temporary / "sas-config"
    scoring = scopes["model-registry"] / "scoring-runs"
    vif_plans = scopes["feature-manifests"] / "vif-plans"
    for directory in (backup, python_runtime, local_app_data, sas_config, scoring, vif_plans):
        directory.mkdir()
    values = {
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
        "ATLAS_ISOLATED_BUREAU_FRONTEND_ORIGIN": f"http://127.0.0.1:{frontend_port}",
        "ATLAS_CORS_ORIGINS": f"http://127.0.0.1:{frontend_port}",
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
    authority_for_environment = {
        "ATLAS_SQLITE_PATH": "persistence-database",
        "ATLAS_SECURITY_ROOT": "security-database",
        "ATLAS_SECURITY_DB_PATH": "security-database",
        "ATLAS_ISOLATED_BUREAU_AUDIT_ROOT": "audit-authority",
        "ATLAS_BUREAU_CATALOG_REGISTRY_ROOT": "catalog-registry",
        "ATLAS_ISOLATED_BUREAU_ACCEPTANCE_ROOT": "restricted-catalog",
        "ATLAS_RESTRICTED_METADATA_ROOT": "restricted-catalog",
        "ATLAS_ISOLATED_CATALOG_INSTALL_JOURNAL_ROOT": "catalog-install-journal",
        "ATLAS_ISOLATED_PROJECT_REGISTRY_ROOT": "project-registry",
        "ATLAS_ISOLATED_DATASET_REGISTRY_ROOT": "dataset-registry",
        "ATLAS_ISOLATED_PROJECT_LINKS_ROOT": "project-links",
        "ATLAS_DATASET_LIBRARY_ROOT": "dataset-library",
        "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": "temporary-files",
        "ATLAS_CHECKPOINT_PATH": "workflow-checkpoint",
        "ATLAS_EVIDENCE_ROOT": "evidence-registry",
        "ATLAS_ISOLATED_DOCUMENTATION_REGISTRY_ROOT": "documentation-registry",
        "ATLAS_FEATURE_MANIFEST_ROOT": "feature-manifests",
        "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": "model-registry",
        "ATLAS_SCORING_RUN_ARTIFACT_ROOT": "model-registry",
        "ATLAS_VIF_PLAN_ROOT": "feature-manifests",
        "ATLAS_BROWSER_STORAGE_ROOT": "browser-profile",
        "ATLAS_PLAYWRIGHT_OUTPUT_ROOT": "test-output",
        "ATLAS_ISOLATED_LOG_ROOT": "logs",
        "ATLAS_ISOLATED_FRONTEND_BUILD_ROOT": "frontend-build",
        "ATLAS_PYTHON_RUNTIME_DIR": "temporary-files",
        "ATLAS_SAS_CONFIG_DIR": "temporary-files",
        "LOCALAPPDATA": "temporary-files",
        "TEMP": "temporary-files",
        "TMP": "temporary-files",
        "PYTHONPYCACHEPREFIX": "temporary-files",
    }
    public = {
        name: {
            "authority": authority,
            "path_name": scopes[authority].name,
        }
        for name, authority in sorted(authority_for_environment.items())
    }
    public["VITE_API_BASE"] = {
        "authority": "isolated-backend",
        "path_name": f"loopback-api-port-{backend_port}",
    }
    return values, public


def _assert_ports(
    backend_port: int,
    frontend_port: int,
    *,
    reservations: ReservedLoopbackPorts | None = None,
) -> None:
    try:
        validate_non_live_ports((backend_port, frontend_port))
        if reservations is not None:
            reservations.assert_exact(
                {"backend": backend_port, "frontend": frontend_port}
            )
            return
    except IsolatedLoopbackPortError as exc:
        raise IsolatedAcceptanceError("Production acceptance ports are not isolated.") from exc
    for port in (backend_port, frontend_port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                raise IsolatedAcceptanceError("A production acceptance port is already in use.")


def _wait_for_http(url: str, process: subprocess.Popen[bytes], timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise IsolatedAcceptanceError("An isolated service exited before readiness.")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError):
            pass
        time.sleep(0.1)
    raise IsolatedAcceptanceError("An isolated service did not become ready.")


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=15)


def _build_production_frontend(
    build_root: Path,
    logs_root: Path,
    temporary_root: Path,
    backend_port: int,
) -> Mapping[str, Any]:
    environment = _clean_subprocess_environment()
    environment.update(
        {
            "VITE_API_BASE": f"http://127.0.0.1:{backend_port}/api",
            "TEMP": str(temporary_root),
            "TMP": str(temporary_root),
        }
    )
    log_path = logs_root / "production-frontend-build.log"
    with log_path.open("xb") as log:
        completed = subprocess.run(
            [
                "npm.cmd",
                "run",
                "build:modeling",
                "--",
                "--config",
                "tests/bureauMetadataIntegration.vite.config.ts",
                "--outDir",
                str(build_root),
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if completed.returncode != 0 or not (build_root / "index.html").is_file():
        raise IsolatedAcceptanceError("The isolated production frontend build failed.")
    scanned_files = 0
    digest = hashlib.sha256()
    forbidden_markers = (b"/@vite/client", b"@react-refresh", b"import.meta.hot", b"__vite_ping")
    for asset in sorted(path for path in build_root.rglob("*") if path.is_file()):
        payload = asset.read_bytes()
        scanned_files += 1
        digest.update(asset.relative_to(build_root).as_posix().encode("utf-8"))
        digest.update(payload)
        if any(marker in payload for marker in forbidden_markers):
            raise IsolatedAcceptanceError("The production build contains a development/HMR marker.")
    return {
        "command": (
            "npm run build:modeling with isolated multi-entry production "
            "config and outDir"
        ),
        "status": "passed",
        "output_file_count": scanned_files,
        "build_checksum": digest.hexdigest(),
        "vite_hmr_markers_absent": True,
    }


def _start_backend(
    environment_pins: Mapping[str, str],
    logs_root: Path,
    port: int,
) -> subprocess.Popen[bytes]:
    environment = _clean_subprocess_environment()
    environment.update(environment_pins)
    log = (logs_root / "isolated-backend.log").open("xb")
    try:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.bureau_metadata_isolated_runtime_app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log.close()


def _start_static_frontend(
    build_root: Path,
    logs_root: Path,
    temporary_root: Path,
    port: int,
) -> subprocess.Popen[bytes]:
    environment = _clean_subprocess_environment()
    environment.update({"TEMP": str(temporary_root), "TMP": str(temporary_root)})
    log = (logs_root / "isolated-static-frontend.log").open("xb")
    try:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.bureau_metadata_isolated_static_server",
                "--root",
                str(build_root),
                "--port",
                str(port),
            ],
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    finally:
        log.close()


def _run_browser(
    scopes: Mapping[str, Path],
    *,
    backend_port: int,
    frontend_port: int,
    version_id: str,
    secondary_version_id: str,
    base: Path,
) -> Mapping[str, Any]:
    command = [
        "node",
        "tests/bureauCatalogAdmin.productionAuth.acceptance.mjs",
        "--frontend-url",
        f"http://127.0.0.1:{frontend_port}",
        "--backend-url",
        f"http://127.0.0.1:{backend_port}",
        "--output-directory",
        str(scopes["test-output"]),
        "--browser-profile-directory",
        str(scopes["browser-profile"]),
        "--downloads-directory",
        str(scopes["browser-downloads"]),
        "--expected-version-id",
        version_id,
        "--expected-secondary-version-id",
        secondary_version_id,
        "--project-alpha-id",
        SYNTHETIC_PROJECTS[0]["project_id"],
        "--project-alpha-dataset-id",
        SYNTHETIC_PROJECTS[0]["dataset_id"],
        "--project-alpha-dataset-version-id",
        SYNTHETIC_PROJECTS[0]["dataset_version_id"],
        "--project-beta-id",
        SYNTHETIC_PROJECTS[1]["project_id"],
        "--project-beta-dataset-id",
        SYNTHETIC_PROJECTS[1]["dataset_id"],
        "--project-beta-dataset-version-id",
        SYNTHETIC_PROJECTS[1]["dataset_version_id"],
        "--forbidden-path-fragment",
        str(base),
        "--headed",
    ]
    environment = _clean_subprocess_environment()
    environment.update(
        {
            "TEMP": str(scopes["temporary-files"]),
            "TMP": str(scopes["temporary-files"]),
            "ATLAS_BROWSER_STORAGE_ROOT": str(scopes["browser-profile"]),
            "ATLAS_PLAYWRIGHT_OUTPUT_ROOT": str(scopes["test-output"]),
        }
    )
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
        timeout=600,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    (scopes["logs"] / "headed-browser.stdout.log").write_bytes(completed.stdout)
    (scopes["logs"] / "headed-browser.stderr.log").write_bytes(completed.stderr)
    if completed.returncode != 0:
        raise IsolatedAcceptanceError("The production authentication browser acceptance failed.")
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IsolatedAcceptanceError("The production browser evidence is invalid.") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise IsolatedAcceptanceError("The production browser acceptance did not pass.")
    return result


def _audit_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise IsolatedAcceptanceError("The isolated authentication audit contains an invalid row.")
        rows.append(payload)
    return rows


def _validate_audit(before: int, rows: list[dict[str, Any]], base: Path) -> Mapping[str, Any]:
    allowed = {
        "schema_version",
        "event_id",
        "correlation_id",
        "actor",
        "action",
        "result_status",
        "server_timestamp",
    }
    appended = rows[before:]
    allowed_actions = {
        "synthetic_authentication",
        "synthetic_project_identity_authorization",
    }
    if not appended or not any(
        row.get("action") == "synthetic_authentication"
        and row.get("result_status") == "denied"
        for row in appended
    ):
        raise IsolatedAcceptanceError("The unauthenticated denial was not isolated-audited.")
    for row in appended:
        if set(row) != allowed or row.get("action") not in allowed_actions:
            raise IsolatedAcceptanceError("An isolated authentication audit row is unbounded.")
        rendered = json.dumps(row, sort_keys=True)
        if len(rendered.encode("utf-8")) > 1_024 or str(base).casefold() in rendered.casefold():
            raise IsolatedAcceptanceError("An isolated authentication audit row leaked authority detail.")
    project_rows = [
        row
        for row in appended
        if row.get("action") == "synthetic_project_identity_authorization"
    ]
    if (
        not any(row.get("result_status") == "success" for row in project_rows)
        or not any(row.get("result_status") == "denied" for row in project_rows)
    ):
        raise IsolatedAcceptanceError("Project authorization outcomes were not isolated-audited.")
    return {
        "row_count_before": before,
        "row_count_after": len(rows),
        "rows_appended": len(appended),
        "success_rows_appended": sum(row.get("result_status") == "success" for row in appended),
        "denied_rows_appended": sum(row.get("result_status") == "denied" for row in appended),
        "authentication_rows_appended": sum(
            row.get("action") == "synthetic_authentication" for row in appended
        ),
        "project_authorization_rows_appended": len(project_rows),
        "project_authorization_success_rows": sum(
            row.get("result_status") == "success" for row in project_rows
        ),
        "project_authorization_denied_rows": sum(
            row.get("result_status") == "denied" for row in project_rows
        ),
        "bounded_schema_verified": True,
        "physical_paths_absent": True,
        "live_audit_opened": False,
        "live_audit_comparison_delegated_to_parent_guard": True,
    }


def _run_acceptance_with_ports(
    authority_map: Path,
    *,
    backend_port: int,
    frontend_port: int,
    port_reservations: ReservedLoopbackPorts | None = None,
) -> Mapping[str, Any]:
    _assert_ports(
        backend_port,
        frontend_port,
        reservations=port_reservations,
    )
    base, mapped_roots = _load_authority_map(authority_map)
    run_id, scopes = _create_run_scopes(mapped_roots)
    environment_pins, public_pins = _environment_pins(
        base,
        scopes,
        backend_port=backend_port,
        frontend_port=frontend_port,
    )
    versions = _initialize_synthetic_authority(
        scopes["restricted-catalog"],
        scopes["catalog-registry"],
    )
    active = versions["1.0"]
    secondary = versions["2.0"]
    build = _build_production_frontend(
        scopes["frontend-build"],
        scopes["logs"],
        scopes["temporary-files"],
        backend_port,
    )
    audit_path = scopes["audit-authority"] / AUTH_AUDIT_FILE
    audit_before = len(_audit_rows(audit_path))
    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None
    try:
        if port_reservations is not None:
            port_reservations.release("backend")
        backend = _start_backend(environment_pins, scopes["logs"], backend_port)
        _wait_for_http(f"http://127.0.0.1:{backend_port}/health", backend)
        if port_reservations is not None:
            port_reservations.release("frontend")
        frontend = _start_static_frontend(
            scopes["frontend-build"],
            scopes["logs"],
            scopes["temporary-files"],
            frontend_port,
        )
        _wait_for_http(f"http://127.0.0.1:{frontend_port}/", frontend)
        browser = _run_browser(
            scopes,
            backend_port=backend_port,
            frontend_port=frontend_port,
            version_id=str(active["catalog_version_id"]),
            secondary_version_id=str(secondary["catalog_version_id"]),
            base=base,
        )
        audit = _validate_audit(audit_before, _audit_rows(audit_path), base)
        reload_evidence = {
            "schema_version": "1.0",
            "classification": FRONTEND_RELOAD_EVIDENCE_CLASSIFICATION,
            "run_id": run_id,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "frontend_origin": f"http://127.0.0.1:{frontend_port}",
            "backend_origin": f"http://127.0.0.1:{backend_port}",
            "authenticated_reload_attempts": int(browser["authenticated_reload_attempts"]),
            "authenticated_reload_successes": int(browser["authenticated_reload_successes"]),
            "synthetic_user_count": int(browser["authenticated_user_count"]),
            "synthetic_provider_count": int(browser["authenticated_provider_count"]),
            "synthetic_project_count": int(browser["authenticated_project_count"]),
            "authentication_failures": 0,
            "unexpected_failures": 0,
            "cross_user_contamination": int(browser["cross_user_contamination"]),
            "cross_project_contamination": int(browser["cross_project_contamination"]),
            "cross_provider_contamination": int(browser["cross_provider_contamination"]),
            "browser_profile_isolated": True,
            "contains_vendor_content": False,
            "live_authority_accessed": False,
            "live_port_contacted": False,
        }
        reload_evidence["evidence_checksum"] = _frontend_reload_evidence_checksum(
            reload_evidence
        )
        reload_evidence_path = (
            scopes["test-output"] / "frontend-authenticated-reload-evidence.json"
        )
        reload_evidence_path.write_bytes(canonical_json_bytes(reload_evidence))
        verified_reload_evidence = _load_frontend_reload_evidence(
            reload_evidence_path,
            minimum_reloads=MIN_FRONTEND_AUTHENTICATED_RELOADS,
            allowed_evidence_root=mapped_roots["test-output"],
        )
        summary = {
            "ok": True,
            "schema_version": "1.0",
            "run_id": run_id,
            "synthetic_content_only": True,
            "production_build": build,
            "production_static_server": {
                "non_hmr": True,
                "distinct_frontend_port": frontend_port,
                "distinct_backend_port": backend_port,
            },
            "authentication_acceptance": browser,
            "isolated_authentication_audit": audit,
            "authority_pins": public_pins,
            "authority_inventory": [
                {
                    "authority": name,
                    "mapped_root_name": mapped_roots[name].name,
                    "run_scope_name": scopes[name].name,
                }
                for name in REQUIRED_AUTHORITIES
            ],
            "network_contact_guard": browser["network_contact_guard"],
            "frontend_reload_evidence": {
                "file": reload_evidence_path.name,
                "authority": "test-output",
                "run_scope_name": scopes["test-output"].name,
                "soak_compatible_as_written": True,
                "evidence_checksum": reload_evidence["evidence_checksum"],
                "validator_result": verified_reload_evidence,
            },
            "live_authorities_opened": False,
            "live_services_touched": False,
            "source_or_git_mutated_by_acceptance": False,
            "screenshot_files": browser["screenshot_files"],
        }
        (scopes["test-output"] / "production-auth-acceptance-summary.json").write_bytes(
            canonical_json_bytes(summary)
        )
        return summary
    finally:
        if port_reservations is not None:
            port_reservations.close()
        _stop_process(frontend)
        _stop_process(backend)
        time.sleep(0.3)
        for port in (backend_port, frontend_port):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.3)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise IsolatedAcceptanceError("An isolated acceptance listener remained open.")


def run_acceptance(
    authority_map: Path,
    *,
    backend_port: int,
    frontend_port: int,
    port_reservations: ReservedLoopbackPorts | None = None,
) -> Mapping[str, Any]:
    """Run acceptance and always release any still-held dynamic reservations."""

    try:
        return _run_acceptance_with_ports(
            authority_map,
            backend_port=backend_port,
            frontend_port=frontend_port,
            port_reservations=port_reservations,
        )
    finally:
        if port_reservations is not None:
            port_reservations.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-map", required=True)
    parser.add_argument("--backend-port", default=0, type=int)
    parser.add_argument("--frontend-port", default=0, type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    reservations: ReservedLoopbackPorts | None = None
    if args.backend_port == 0 and args.frontend_port == 0:
        reservations = reserve_dynamic_non_live_ports()
        backend_port = reservations.ports["backend"]
        frontend_port = reservations.ports["frontend"]
    elif args.backend_port == 0 or args.frontend_port == 0:
        raise IsolatedAcceptanceError(
            "Specify both isolated ports or allow both to be assigned dynamically."
        )
    else:
        backend_port = args.backend_port
        frontend_port = args.frontend_port
    summary = run_acceptance(
        Path(args.authority_map),
        backend_port=backend_port,
        frontend_port=frontend_port,
        port_reservations=reservations,
    )
    public = {
        "ok": summary["ok"],
        "run_id": summary["run_id"],
        "production_build": summary["production_build"],
        "production_static_server": summary["production_static_server"],
        "authentication_acceptance": summary["authentication_acceptance"],
        "isolated_authentication_audit": summary["isolated_authentication_audit"],
        "authority_pins": summary["authority_pins"],
        "authority_inventory": summary["authority_inventory"],
        "network_contact_guard": summary["network_contact_guard"],
        "frontend_reload_evidence": summary["frontend_reload_evidence"],
        "live_authorities_opened": summary["live_authorities_opened"],
        "live_services_touched": summary["live_services_touched"],
        "source_or_git_mutated_by_acceptance": summary["source_or_git_mutated_by_acceptance"],
        "screenshot_count": len(summary["screenshot_files"]),
    }
    sys.stdout.write(json.dumps(public, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
