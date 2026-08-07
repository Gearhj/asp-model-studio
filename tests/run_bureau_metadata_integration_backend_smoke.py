"""Run a short non-browser process smoke for the isolated bureau integration.

This helper intentionally does not start a frontend or browser.  It proves
that the production catalog, binding, crosswalk, semantic handoff, evidence,
MDD, entitlement, and restart-recovery routes compose over the synthetic
isolated authorities.  Browser acceptance remains a separate controlled gate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.isolated_loopback_ports import reserve_dynamic_non_live_ports
from scripts.run_bureau_metadata_integrated_closeout import (
    INTEGRATION_EVENT_FILE,
    _create_crosswalk_fixture,
    _create_run_scopes,
    _environment_pins,
    _grant_integration_entitlements,
    _initialize_catalogs_without_global_patch,
    _listener_pids,
    _load_authority_map,
    _load_integration_event_counts,
    _start_backend_cycle,
    _stop_owned_process_tree,
    _validate_exact_recovery,
    _wait_for_exact_listener,
    _wait_for_guarded_health,
    _wait_for_port_closed,
)


TENANT = "synthetic-tenant"
PROJECTS = {
    "A": (
        "synthetic-project-alpha-001",
        "synthetic-dataset-alpha-001",
        "synthetic-version-alpha-001",
        "synthetic-project-user-alpha",
    ),
    "C": (
        "synthetic-project-gamma-003",
        "synthetic-dataset-gamma-003",
        "synthetic-version-gamma-003",
        "synthetic-project-user-gamma",
    ),
    "D": (
        "synthetic-project-delta-004",
        "synthetic-dataset-delta-004",
        "synthetic-version-delta-004",
        "synthetic-project-user-delta",
    ),
    "E": (
        "synthetic-project-epsilon-005",
        "synthetic-dataset-epsilon-005",
        "synthetic-version-epsilon-005",
        "synthetic-project-user-epsilon",
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authority-map", required=True, type=Path)
    return parser


def _headers(run_id: str, principal: str, role: str = "user") -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Synthetic-Principal": principal,
        "X-Synthetic-Role": role,
        "X-Synthetic-Tenant": TENANT,
        "X-Synthetic-Run-Id": run_id,
        "X-Synthetic-Probe": "backend-smoke",
    }


def _request(
    base: str,
    path: str,
    *,
    run_id: str,
    principal: str,
    role: str = "user",
    method: str = "GET",
    body: Mapping[str, Any] | None = None,
) -> tuple[int, Mapping[str, Any]]:
    headers = _headers(run_id, principal, role)
    encoded = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        encoded = json.dumps(dict(body), sort_keys=True).encode("utf-8")
    request = Request(base + path, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            status = int(response.status)
            raw = response.read()
    except HTTPError as exc:
        status = int(exc.code)
        raw = exc.read()
    parsed = json.loads(raw.decode("utf-8")) if raw else {}
    if not isinstance(parsed, Mapping):
        raise RuntimeError("The isolated integration response was not an object.")
    return status, parsed


def _base_path(project: tuple[str, str, str, str]) -> str:
    return (
        f"/api/projects/{quote(project[0], safe='')}"
        f"/datasets/{quote(project[1], safe='')}"
        f"/versions/{quote(project[2], safe='')}/bureau-metadata"
    )


def _require(status: int, expected: int, message: str) -> None:
    if status != expected:
        raise RuntimeError(message)


def _exercise_api(
    base: str,
    *,
    run_id: str,
    catalog_version_id: str,
    catalog_checksum: str,
) -> Mapping[str, Any]:
    project_a = PROJECTS["A"]
    a_path = _base_path(project_a)
    status, listed = _request(
        base,
        "/api/bureau-catalogs?offset=0&limit=50",
        run_id=run_id,
        principal=project_a[3],
    )
    _require(status, 200, "The entitled catalog list failed.")
    listed_versions = listed.get("versions") or listed.get("items") or []
    if not any(
        isinstance(row, Mapping)
        and row.get("catalog_version_id") == catalog_version_id
        for row in listed_versions
    ):
        raise RuntimeError("The exact catalog version was absent from the entitled list.")

    status, preview = _request(
        base,
        a_path + "/binding/preview",
        run_id=run_id,
        principal=project_a[3],
        method="POST",
        body={
            "catalog_version_id": catalog_version_id,
            "catalog_checksum": catalog_checksum,
        },
    )
    _require(status, 200, "The exact binding preview failed.")
    preview_row = preview.get("preview")
    if not isinstance(preview_row, Mapping):
        raise RuntimeError("The exact binding preview payload was unavailable.")
    status, confirmed = _request(
        base,
        a_path + "/binding/confirm",
        run_id=run_id,
        principal=project_a[3],
        method="POST",
        body={
            "catalog_version_id": catalog_version_id,
            "catalog_checksum": catalog_checksum,
            "expected_revision": preview_row.get("expected_revision"),
            "preview_checksum": preview_row.get("preview_checksum"),
            "analyst_rationale": "Synthetic isolated backend acceptance.",
        },
    )
    _require(status, 200, "The exact binding confirmation failed.")
    binding = confirmed.get("binding")
    if confirmed.get("ok") is not True or not isinstance(binding, Mapping):
        raise RuntimeError("The exact binding confirmation was contradictory.")

    status, crosswalk_preview = _request(
        base,
        a_path + "/crosswalk/preview",
        run_id=run_id,
        principal=project_a[3],
    )
    _require(status, 200, "The exact crosswalk preview failed.")
    initial = crosswalk_preview.get("initial_decisions")
    if not isinstance(initial, list) or not initial:
        raise RuntimeError("The exact crosswalk preview had no bounded decisions.")
    decisions = []
    for row in initial:
        if not isinstance(row, Mapping):
            raise RuntimeError("A crosswalk preview row was invalid.")
        candidate = row.get("candidate_attribute_code")
        decision: dict[str, Any] = {
            "dataset_field": row.get("dataset_field"),
            "mapping_state": "exact_verified" if candidate else "out_of_catalog",
            "rationale": "Synthetic provider code and bounded definition reviewed.",
        }
        if candidate:
            decision["candidate_attribute_code"] = candidate
        decisions.append(decision)
    status, saved = _request(
        base,
        a_path + "/crosswalk/decisions",
        run_id=run_id,
        principal=project_a[3],
        method="POST",
        body={
            "expected_crosswalk_revision": 0,
            "expected_binding_revision": binding.get("revision"),
            "decisions": decisions,
            "analyst_reason": "Synthetic exact mappings reviewed independently.",
            "confirm_crosswalk": True,
        },
    )
    _require(status, 200, "The exact governed crosswalk write failed.")
    if saved.get("binding_linked") is not True:
        raise RuntimeError("The exact crosswalk did not link to the binding.")

    status, annotations = _request(
        base,
        a_path + "/annotations",
        run_id=run_id,
        principal=project_a[3],
    )
    _require(status, 200, "The semantic annotation batch failed.")
    annotation_set = annotations.get("annotation_set")
    if not isinstance(annotation_set, Mapping):
        raise RuntimeError("The semantic annotation identity was unavailable.")
    status, handoff = _request(
        base,
        "/api/isolated/canonical-eda-handoff/"
        + "/".join(quote(value, safe="") for value in project_a[:3]),
        run_id=run_id,
        principal=project_a[3],
    )
    _require(status, 200, "The canonical DA-to-EDA handoff failed.")
    if handoff.get("final_holdout_accessed") is not False or handoff.get(
        "training_started"
    ) is not False:
        raise RuntimeError("The canonical handoff crossed its analytical boundary.")

    status, _ = _request(
        base,
        a_path + "/crosswalk/binding-link",
        run_id=run_id,
        principal=project_a[3],
        method="POST",
        body={
            "crosswalk_revision": annotation_set.get("crosswalk_revision"),
            "expected_binding_revision": annotation_set.get("binding_revision"),
            "analyst_reason": "Synthetic idempotent binding-link retry.",
        },
    )
    _require(status, 200, "The idempotent binding-link retry failed.")

    status, _ = _request(
        base,
        f"/api/bureau-catalogs/{quote(catalog_version_id, safe='')}/attributes?q=synthetic&offset=0&limit=5",
        run_id=run_id,
        principal=project_a[3],
    )
    _require(status, 200, "The bounded catalog search failed.")
    status, _ = _request(
        base,
        a_path + "/binding/preview",
        run_id=run_id,
        principal=project_a[3],
        method="POST",
        body={
            "catalog_version_id": catalog_version_id,
            "catalog_checksum": "invalid",
        },
    )
    _require(status, 422, "The malformed binding request did not fail closed.")
    status, _ = _request(
        base,
        a_path + "/crosswalk/decisions",
        run_id=run_id,
        principal=project_a[3],
        method="POST",
        body={
            "expected_crosswalk_revision": 999,
            "expected_binding_revision": annotation_set.get("binding_revision"),
            "decisions": decisions,
            "analyst_reason": "Synthetic stale revision conflict.",
            "confirm_crosswalk": False,
        },
    )
    _require(status, 409, "The stale crosswalk revision did not fail closed.")

    project_c = PROJECTS["C"]
    status, unentitled = _request(
        base,
        "/api/bureau-catalogs?offset=0&limit=50",
        run_id=run_id,
        principal=project_c[3],
    )
    _require(status, 200, "The no-entitlement inventory request failed.")
    if unentitled.get("versions") or unentitled.get("items"):
        raise RuntimeError("The no-entitlement inventory leaked catalog identity.")
    status, _ = _request(
        base,
        _base_path(project_c) + "/binding",
        run_id=run_id,
        principal=project_c[3],
    )
    _require(status, 404, "The no-entitlement binding did not remain unavailable.")

    project_d = PROJECTS["D"]
    status, _ = _request(
        base,
        f"/api/isolated/project-integration-identity/{quote(project_d[0], safe='')}",
        run_id=run_id,
        principal=project_d[3],
    )
    _require(status, 200, "The non-bureau project identity failed.")

    project_e = PROJECTS["E"]
    identity_path = (
        f"/api/isolated/project-integration-identity/{quote(project_e[0], safe='')}"
    )
    status, owner = _request(
        base, identity_path, run_id=run_id, principal=project_e[3]
    )
    _require(status, 200, "The Project E owner identity failed.")
    if owner.get("dataset_version_id") != project_e[2]:
        raise RuntimeError("The Project E exact identity was contradictory.")
    status, intruder = _request(
        base, identity_path, run_id=run_id, principal=project_a[3]
    )
    _require(status, 403, "Cross-user project access did not fail closed.")
    if project_e[2] in json.dumps(dict(intruder), sort_keys=True):
        raise RuntimeError("Cross-user denial leaked the exact dataset version.")

    status, grant = _request(
        base,
        f"/api/admin/bureau-catalogs/{quote(catalog_version_id, safe='')}/entitlements",
        run_id=run_id,
        principal="synthetic-admin",
        role="admin",
        method="POST",
        body={
            "principal_id": "synthetic-integration-transient",
            "tenant_id": TENANT,
            "operations": ["catalog_health"],
        },
    )
    _require(status, 200, "The transient isolated entitlement grant failed.")
    entitlement = grant.get("entitlement")
    if not isinstance(entitlement, Mapping):
        raise RuntimeError("The transient entitlement identity was unavailable.")
    status, revoked = _request(
        base,
        "/api/admin/bureau-catalog-entitlements/"
        + quote(str(entitlement.get("entitlement_id")), safe="")
        + "/revoke",
        run_id=run_id,
        principal="synthetic-admin",
        role="admin",
        method="POST",
        body={"reason": "Synthetic non-browser smoke complete"},
    )
    _require(status, 200, "The transient isolated entitlement revoke failed.")
    if (revoked.get("entitlement") or {}).get("status") != "revoked":
        raise RuntimeError("The transient entitlement did not become revoked.")

    return {
        "binding_revision": annotation_set.get("binding_revision"),
        "crosswalk_revision": annotation_set.get("crosswalk_revision"),
        "annotation_set_id": annotation_set.get("annotation_set_id"),
        "project_scenarios": 5,
        "final_holdout_accessed": False,
        "training_started": False,
    }


def main() -> int:
    args = _parser().parse_args()
    reservations = None
    backend = None
    backend_port = 0
    try:
        base, mapped = _load_authority_map(args.authority_map)
        run_id, scopes = _create_run_scopes(mapped)
        versions = _initialize_catalogs_without_global_patch(
            scopes["restricted-catalog"], scopes["catalog-registry"]
        )
        _grant_integration_entitlements(scopes, versions)
        active = versions["1.0"]
        expected_recovery = _create_crosswalk_fixture(
            scopes,
            run_id=run_id,
            catalog_version_id=str(active["catalog_version_id"]),
        )
        reservations = reserve_dynamic_non_live_ports()
        backend_port = reservations.ports["backend"]
        frontend_port = reservations.ports["frontend"]
        environment, _ = _environment_pins(
            base,
            scopes,
            backend_port=backend_port,
            frontend_port=frontend_port,
        )
        environment.update(
            {
                "ATLAS_ISOLATED_ACCEPTANCE_RUN_ID": run_id,
                "ATLAS_ISOLATED_CROSSWALK_GOVERNANCE_ID": str(
                    expected_recovery["governance_id"]
                ),
                "ATLAS_ISOLATED_CROSSWALK_REVISION": str(
                    expected_recovery["revision"]
                ),
                "ATLAS_ISOLATED_CROSSWALK_CHECKSUM": str(
                    expected_recovery["revision_checksum"]
                ),
                "ATLAS_ISOLATED_RECOVERY_CATALOG_VERSION_ID": str(
                    expected_recovery["catalog_version_id"]
                ),
                "ATLAS_ISOLATED_RECOVERY_CATALOG_CHECKSUM": str(
                    expected_recovery["catalog_checksum"]
                ),
            }
        )
        reservations.release("backend")
        backend = _start_backend_cycle(environment, scopes["logs"], backend_port, cycle=0)
        _wait_for_guarded_health(backend, backend_port=backend_port, run_id=run_id)
        initial_pid = _wait_for_exact_listener(backend, backend_port)
        base_url = f"http://127.0.0.1:{backend_port}"
        api_result = _exercise_api(
            base_url,
            run_id=run_id,
            catalog_version_id=str(active["catalog_version_id"]),
            catalog_checksum=str(active["catalog_checksum"]),
        )

        _stop_owned_process_tree(backend)
        backend = None
        _wait_for_port_closed(backend_port)
        backend = _start_backend_cycle(environment, scopes["logs"], backend_port, cycle=1)
        _wait_for_guarded_health(backend, backend_port=backend_port, run_id=run_id)
        restarted_pid = _wait_for_exact_listener(backend, backend_port)
        if restarted_pid == initial_pid:
            raise RuntimeError("The isolated backend listener PID did not change.")
        recovery_path = (
            "/api/isolated/integrated-recovery/"
            + quote(str(expected_recovery["catalog_version_id"]), safe="")
            + "/"
            + quote(str(expected_recovery["governance_id"]), safe="")
            + "/"
            + str(expected_recovery["revision"])
        )
        status, recovery_payload = _request(
            base_url,
            recovery_path,
            run_id=run_id,
            principal="synthetic-admin",
            role="admin",
        )
        _require(status, 200, "The exact restart-recovery route failed.")
        recovery = _validate_exact_recovery(recovery_payload, expected_recovery)
        project_a = PROJECTS["A"]
        status, _ = _request(
            base_url,
            _base_path(project_a) + "/annotations",
            run_id=run_id,
            principal=project_a[3],
        )
        _require(status, 200, "The exact semantic contract did not survive restart.")
        events = _load_integration_event_counts(scopes["logs"] / INTEGRATION_EVENT_FILE)
        result = {
            "classification": "synthetic_bureau_metadata_integration_backend_smoke",
            "ok": True,
            "run_id": run_id,
            "dynamic_backend_port": backend_port,
            "initial_listener_pid": initial_pid,
            "restarted_listener_pid": restarted_pid,
            "listener_pid_changed": True,
            "exact_restart_recovery": recovery,
            "api_contract": api_result,
            "event_matrix": events,
            "frontend_started": False,
            "browser_started": False,
            "live_ports_contacted": False,
            "sealed_holdout_accessed": False,
            "training_started": False,
        }
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "classification": "synthetic_bureau_metadata_integration_backend_smoke",
                    "ok": False,
                    "failure_type": type(exc).__name__,
                },
                sort_keys=True,
            )
        )
        return 1
    finally:
        _stop_owned_process_tree(backend)
        if backend_port:
            try:
                _wait_for_port_closed(backend_port)
            except Exception:
                pass
        if reservations is not None:
            reservations.close()


if __name__ == "__main__":
    raise SystemExit(main())
