"""Run a fully isolated synthetic acceptance of the Bureau Catalog admin surface.

The command requires an explicit, empty Windows Temp child.  It never imports
the ATLAS application entrypoint, opens a live database, or starts/stops the
live ports.  The backend subprocess hosts the production catalog router over a
synthetic registry and catalog root; the frontend subprocess serves the actual
React application on an explicitly non-live port.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.run_bureau_metadata_operational_soak import (
    ALL_OPERATIONS,
    _publish_synthetic_catalog,
)
from server.bureau_metadata import catalog_registry
from server.bureau_metadata.catalog_registry import CatalogRegistry
from server.bureau_metadata.normalizer import canonical_json_bytes


ADMIN_PRINCIPAL = "synthetic-admin"
READER_PRINCIPAL = "synthetic-reader"
TRANSIENT_PRINCIPAL = "synthetic-transient-reader"
TENANT_ID = "synthetic-tenant"
READ_OPERATIONS = (
    "attribute_lookup",
    "catalog_health",
    "manifest_read",
    "special_value_lookup",
    "value_classification",
)


class IsolatedAcceptanceError(RuntimeError):
    """A synthetic acceptance invariant failed."""


def _safe_temp_root(value: str) -> Path:
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise IsolatedAcceptanceError("The isolated acceptance root must be absolute.")
    root = root.resolve(strict=True)
    temp = Path(tempfile.gettempdir()).resolve(strict=True)
    if temp not in root.parents:
        raise IsolatedAcceptanceError("The isolated acceptance root must be a Windows Temp child.")
    if root == temp or root == REPOSITORY_ROOT or REPOSITORY_ROOT in root.parents:
        raise IsolatedAcceptanceError("The isolated acceptance root is too broad or overlaps the repository.")
    if any(root.iterdir()):
        raise IsolatedAcceptanceError("The isolated acceptance root must be empty.")
    return root


def _assert_non_live_ports(backend_port: int, frontend_port: int) -> None:
    ports = {int(backend_port), int(frontend_port)}
    if len(ports) != 2 or ports.intersection({8001, 5174}):
        raise IsolatedAcceptanceError("Acceptance ports must be distinct and non-live.")
    if any(port < 1024 or port > 65535 for port in ports):
        raise IsolatedAcceptanceError("Acceptance ports are outside the permitted range.")


def _patch_temp_registry_roots(*exact_roots: Path) -> None:
    permitted = {root.resolve(strict=True) for root in exact_roots}

    def validate(root: str | Path | None, **_kwargs: Any) -> Path:
        candidate = Path(str(root or "")).resolve(strict=True)
        if candidate not in permitted:
            raise IsolatedAcceptanceError("Registry attempted to use an unexpected root.")
        return candidate

    catalog_registry.validate_restricted_metadata_root = validate


def _storage_reference(version: str, checksum: str) -> str:
    digest = hashlib.sha256(f"{version}:{checksum}".encode("utf-8")).hexdigest()
    return "restricted-catalog:" + digest[:32]


def _initialize_synthetic_authority(
    root: Path,
    registry_root: Path,
) -> dict[str, dict[str, Any]]:
    _patch_temp_registry_roots(root, registry_root)
    registry = CatalogRegistry(
        root,
        repository_root=REPOSITORY_ROOT,
        registry_root=registry_root,
    )
    versions: dict[str, dict[str, Any]] = {}
    for version_number in (1, 2):
        _key, checksum, _exact, manifest = _publish_synthetic_catalog(root, version_number)
        record = registry.register_manifest(
            manifest,
            storage_reference=_storage_reference(str(version_number), checksum),
            actor=ADMIN_PRINCIPAL,
            country_or_region="synthetic-test-region",
            supported_bureau_versions=(f"synthetic-{version_number}",),
        )
        registry.grant_entitlement(
            principal_id=ADMIN_PRINCIPAL,
            tenant_id=TENANT_ID,
            catalog_version_id=record.catalog_version_id,
            operations=ALL_OPERATIONS,
            granted_by=ADMIN_PRINCIPAL,
        )
        registry.grant_entitlement(
            principal_id=READER_PRINCIPAL,
            tenant_id=TENANT_ID,
            catalog_version_id=record.catalog_version_id,
            operations=READ_OPERATIONS,
            granted_by=ADMIN_PRINCIPAL,
        )
        versions[record.source_release_version] = {
            "catalog_version_id": record.catalog_version_id,
            "catalog_checksum": record.normalized_catalog_checksum,
            "dictionary_version": record.source_release_version,
            "registry_revision": record.registry_revision,
        }
    return versions


def _headers(principal: str, role: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Synthetic-Principal": principal,
        "X-Synthetic-Role": role,
        "X-Synthetic-Tenant": TENANT_ID,
    }


def _request_json(
    base_url: str,
    path: str,
    *,
    principal: str,
    role: str,
    method: str = "GET",
    payload: Mapping[str, Any] | None = None,
    expected_status: int = 200,
) -> Mapping[str, Any]:
    encoded = None if payload is None else canonical_json_bytes(dict(payload))
    headers = _headers(principal, role)
    if encoded is not None:
        headers["Content-Type"] = "application/json"
    request = Request(base_url + path, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=10) as response:
            status = response.status
            body = response.read()
    except HTTPError as exc:
        status = exc.code
        body = exc.read()
    except URLError as exc:
        raise IsolatedAcceptanceError("The isolated backend request failed.") from exc
    if status != expected_status:
        raise IsolatedAcceptanceError(
            f"Isolated request status mismatch for {method} {path}: expected {expected_status}, received {status}."
        )
    try:
        decoded = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IsolatedAcceptanceError("The isolated backend returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise IsolatedAcceptanceError("The isolated backend returned a non-object response.")
    return decoded


def _wait_for_http(url: str, process: subprocess.Popen[bytes], *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise IsolatedAcceptanceError("An isolated service exited before becoming healthy.")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError):
            pass
        time.sleep(0.1)
    raise IsolatedAcceptanceError("An isolated service did not become healthy in time.")


def _start_backend(
    root: Path,
    registry_root: Path,
    audit_root: Path,
    port: int,
    frontend_port: int,
) -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment["ATLAS_ISOLATED_BUREAU_ACCEPTANCE_ROOT"] = str(root)
    environment["ATLAS_BUREAU_CATALOG_REGISTRY_ROOT"] = str(registry_root)
    environment["ATLAS_ISOLATED_BUREAU_AUDIT_ROOT"] = str(audit_root)
    environment["ATLAS_ISOLATED_BUREAU_FRONTEND_ORIGIN"] = f"http://127.0.0.1:{frontend_port}"
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
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _start_frontend(port: int, backend_port: int) -> subprocess.Popen[bytes]:
    vite = REPOSITORY_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite.is_file():
        raise IsolatedAcceptanceError("The workspace Vite runtime is unavailable.")
    environment = os.environ.copy()
    environment["VITE_API_BASE"] = f"http://127.0.0.1:{backend_port}/api"
    return subprocess.Popen(
        [
            "node",
            str(vite),
            "--mode",
            "modeling",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _stop_spawned(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _assert_public_payload_safe(payloads: list[Mapping[str, Any]], root: Path) -> None:
    rendered = json.dumps(payloads, sort_keys=True)
    forbidden = (
        str(root),
        "restricted_storage_reference",
        "attribute_definitions.jsonl",
        "special_value_definitions.jsonl",
        "catalog_manifest.json",
        "full_catalog",
    )
    if any(value.casefold() in rendered.casefold() for value in forbidden):
        raise IsolatedAcceptanceError("A public response exposed restricted storage or bulk-catalog metadata.")


def _run_browser_acceptance(
    frontend_port: int,
    evidence_root: Path,
    version_id: str,
) -> Mapping[str, Any]:
    completed = subprocess.run(
        [
            "node",
            "tests/bureauCatalogAdmin.isolated.acceptance.mjs",
            "--frontend-url",
            f"http://127.0.0.1:{frontend_port}",
            "--output-directory",
            str(evidence_root),
            "--expected-version-id",
            version_id,
            "--expected-attribute-code",
            "SYN000",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace")[-2_000:]
        diagnostic = diagnostic.replace(str(REPOSITORY_ROOT), "<repository>")
        diagnostic = diagnostic.replace(str(evidence_root), "<evidence-root>")
        raise IsolatedAcceptanceError(
            "The isolated React admin acceptance failed. Safe synthetic diagnostic: "
            + " ".join(diagnostic.split())
        )
    try:
        result = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IsolatedAcceptanceError("The isolated browser acceptance returned invalid evidence.") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise IsolatedAcceptanceError("The isolated browser acceptance did not pass.")
    return result


def run_acceptance(base_root: Path, *, backend_port: int, frontend_port: int) -> Mapping[str, Any]:
    restricted_root = base_root / "restricted-catalog"
    registry_root = base_root / "catalog-registry"
    audit_root = base_root / "audit-authority"
    evidence_root = base_root / "evidence"
    restricted_root.mkdir()
    registry_root.mkdir()
    audit_root.mkdir()
    evidence_root.mkdir()
    marker = {
        "schema_version": "1.0",
        "record_type": "synthetic_isolated_bureau_admin_acceptance",
        "live_authority_used": False,
        "vendor_content_used": False,
    }
    (base_root / "synthetic-acceptance-marker.json").write_bytes(canonical_json_bytes(marker))
    versions_by_dictionary = _initialize_synthetic_authority(restricted_root, registry_root)
    active = versions_by_dictionary["1.0"]
    reload_target = versions_by_dictionary["2.0"]
    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None
    restarted_backend: subprocess.Popen[bytes] | None = None
    responses: list[Mapping[str, Any]] = []
    try:
        backend = _start_backend(
            restricted_root,
            registry_root,
            audit_root,
            backend_port,
            frontend_port,
        )
        _wait_for_http(f"http://127.0.0.1:{backend_port}/health", backend)
        backend_pid_before = backend.pid
        api = f"http://127.0.0.1:{backend_port}"

        denial = _request_json(
            api,
            "/api/admin/bureau-catalogs",
            principal=READER_PRINCIPAL,
            role="user",
            expected_status=403,
        )
        unentitled = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/health",
            principal="synthetic-unentitled",
            role="user",
            expected_status=403,
        )
        listing = _request_json(
            api,
            "/api/bureau-catalogs?offset=0&limit=2",
            principal=READER_PRINCIPAL,
            role="user",
        )
        health = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/health",
            principal=READER_PRINCIPAL,
            role="user",
        )
        search = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/attributes?q=synthetic%20operational&offset=0&limit=2",
            principal=READER_PRINCIPAL,
            role="user",
        )
        bounded = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/attributes?q=synthetic&limit=51",
            principal=READER_PRINCIPAL,
            role="user",
            expected_status=422,
        )
        exact = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/attributes/SYN000",
            principal=READER_PRINCIPAL,
            role="user",
        )
        special = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/attributes/SYN000/special-values?offset=0&limit=1",
            principal=READER_PRINCIPAL,
            role="user",
        )
        availability = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/attributes/SYN000/availability",
            principal=READER_PRINCIPAL,
            role="user",
        )
        validated = _request_json(
            api,
            f"/api/admin/bureau-catalogs/{active['catalog_version_id']}/validate",
            principal=ADMIN_PRINCIPAL,
            role="admin",
            method="POST",
            payload={},
        )
        granted = _request_json(
            api,
            f"/api/admin/bureau-catalogs/{active['catalog_version_id']}/entitlements",
            principal=ADMIN_PRINCIPAL,
            role="admin",
            method="POST",
            payload={
                "principal_id": TRANSIENT_PRINCIPAL,
                "tenant_id": TENANT_ID,
                "operations": ["catalog_health"],
            },
        )
        transient_health = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/health",
            principal=TRANSIENT_PRINCIPAL,
            role="user",
        )
        entitlement_id = str(granted["entitlement"]["entitlement_id"])
        revoked = _request_json(
            api,
            f"/api/admin/bureau-catalog-entitlements/{entitlement_id}/revoke",
            principal=ADMIN_PRINCIPAL,
            role="admin",
            method="POST",
            payload={"reason": "synthetic acceptance complete"},
        )
        revoked_denial = _request_json(
            api,
            f"/api/bureau-catalogs/{active['catalog_version_id']}/health",
            principal=TRANSIENT_PRINCIPAL,
            role="user",
            expected_status=403,
        )
        responses.extend(
            [
                denial,
                unentitled,
                listing,
                health,
                search,
                bounded,
                exact,
                special,
                availability,
                validated,
                granted,
                transient_health,
                revoked,
                revoked_denial,
            ]
        )
        if int(listing.get("returned", -1)) != 2 or int(search.get("returned", -1)) > 2:
            raise IsolatedAcceptanceError("A bounded list or search exceeded its requested page.")
        if exact.get("attribute", {}).get("attribute_code") != "SYN000":
            raise IsolatedAcceptanceError("Exact attribute lookup returned a different code.")
        if int(special.get("returned", 0)) != 1:
            raise IsolatedAcceptanceError("Bounded special-value lookup returned an unexpected count.")
        if availability.get("availability", {}).get("attribute_code") != "SYN000":
            raise IsolatedAcceptanceError("Availability lookup returned a different code.")
        if validated.get("verification", {}).get("catalog_checksum") != active["catalog_checksum"]:
            raise IsolatedAcceptanceError("Administrative validation returned a contradictory checksum.")
        if revoked.get("entitlement", {}).get("status") != "revoked":
            raise IsolatedAcceptanceError("Entitlement revocation did not persist.")
        _assert_public_payload_safe(responses, restricted_root)

        frontend = _start_frontend(frontend_port, backend_port)
        _wait_for_http(f"http://127.0.0.1:{frontend_port}/", frontend)
        browser = _run_browser_acceptance(
            frontend_port,
            evidence_root,
            str(active["catalog_version_id"]),
        )

        admin_listing = _request_json(
            api,
            "/api/admin/bureau-catalogs?offset=0&limit=10",
            principal=ADMIN_PRINCIPAL,
            role="admin",
        )
        current = next(
            item
            for item in admin_listing["catalogs"]
            if item["catalog_version_id"] == active["catalog_version_id"]
        )
        retired = _request_json(
            api,
            f"/api/admin/bureau-catalogs/{active['catalog_version_id']}/retire",
            principal=ADMIN_PRINCIPAL,
            role="admin",
            method="POST",
            payload={"expected_revision": current["registry_revision"]},
        )
        if retired.get("catalog", {}).get("retired_status") != "retired":
            raise IsolatedAcceptanceError("The explicitly confirmed retirement did not persist.")
        responses.extend([admin_listing, retired])
        _assert_public_payload_safe(responses, restricted_root)

        _stop_spawned(frontend)
        frontend = None
        _stop_spawned(backend)
        backend = None
        restarted_backend = _start_backend(
            restricted_root,
            registry_root,
            audit_root,
            backend_port,
            frontend_port,
        )
        _wait_for_http(f"http://127.0.0.1:{backend_port}/health", restarted_backend)
        backend_pid_after = restarted_backend.pid
        if backend_pid_after == backend_pid_before:
            raise IsolatedAcceptanceError("The isolated backend listener PID did not change.")
        recovered = _request_json(
            api,
            f"/api/bureau-catalogs/{reload_target['catalog_version_id']}/health",
            principal=READER_PRINCIPAL,
            role="user",
        )
        recovered_listing = _request_json(
            api,
            "/api/admin/bureau-catalogs?offset=0&limit=10",
            principal=ADMIN_PRINCIPAL,
            role="admin",
        )
        recovered_catalog = recovered.get("catalog", {})
        if (
            recovered_catalog.get("catalog_version_id") != reload_target["catalog_version_id"]
            or recovered_catalog.get("normalized_catalog_checksum") != reload_target["catalog_checksum"]
            or recovered_catalog.get("integrity_status") != "verified"
        ):
            raise IsolatedAcceptanceError("Exact catalog identity or integrity did not survive restart.")
        recovered_ids = {item["catalog_version_id"] for item in recovered_listing["catalogs"]}
        if active["catalog_version_id"] in recovered_ids or reload_target["catalog_version_id"] not in recovered_ids:
            raise IsolatedAcceptanceError("Retirement or active-version state did not survive restart.")
        responses.extend([recovered, recovered_listing])
        _assert_public_payload_safe(responses, restricted_root)

        summary = {
            "ok": True,
            "schema_version": "1.0",
            "synthetic_content_only": True,
            "live_services_touched": False,
            "live_databases_touched": False,
            "backend_process_restart": {
                "old_pid_stopped": True,
                "new_pid_started": True,
                "pid_changed": True,
                "exact_version_recovered": True,
                "integrity_verified_after_restart": True,
                "retirement_persisted": True,
                "entitlement_persisted": True,
            },
            "api_acceptance": {
                "non_admin_admin_route_denied": True,
                "unentitled_exact_version_denied": True,
                "bounded_catalog_list": True,
                "bounded_attribute_search": True,
                "exact_attribute_lookup": True,
                "bounded_special_value_lookup": True,
                "availability_lookup": True,
                "admin_integrity_validate": True,
                "entitlement_grant_revoke": True,
                "explicit_retirement": True,
                "no_path_or_bulk_catalog_exposure": True,
            },
            "browser_acceptance": dict(browser),
            "catalog_versions": [
                {
                    "catalog_version_id": item["catalog_version_id"],
                    "catalog_checksum": item["catalog_checksum"],
                    "dictionary_version": item["dictionary_version"],
                }
                for item in sorted(
                    versions_by_dictionary.values(),
                    key=lambda value: str(value["dictionary_version"]),
                )
            ],
            "screenshot_files": ["synthetic-bureau-catalog-admin.png"],
        }
        (base_root / "isolated-admin-acceptance-summary.json").write_bytes(
            canonical_json_bytes(summary)
        )
        return summary
    finally:
        _stop_spawned(frontend)
        _stop_spawned(backend)
        _stop_spawned(restarted_backend)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-root", required=True)
    parser.add_argument("--backend-port", type=int, required=True)
    parser.add_argument("--frontend-port", type=int, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    _assert_non_live_ports(args.backend_port, args.frontend_port)
    root = _safe_temp_root(args.base_root)
    summary = run_acceptance(
        root,
        backend_port=args.backend_port,
        frontend_port=args.frontend_port,
    )
    public = {
        "ok": summary["ok"],
        "synthetic_content_only": summary["synthetic_content_only"],
        "live_services_touched": summary["live_services_touched"],
        "live_databases_touched": summary["live_databases_touched"],
        "backend_process_restart": summary["backend_process_restart"],
        "api_acceptance": summary["api_acceptance"],
        "browser_acceptance": summary["browser_acceptance"],
        "screenshot_count": len(summary["screenshot_files"]),
    }
    sys.stdout.write(json.dumps(public, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
