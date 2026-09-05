"""Synchronized HTTP regression in fresh synthetic runtimes only.

The barrier is outside the write transaction on purpose: User B must be able
to commit while User A is paused. Before the repair, this is after A's stale
authorization; after the repair, authorization runs inside the transaction.
No application hook, timing sleep, live application, or external provider is
needed. Run this file directly or use --probe to retain a JSON evidence receipt.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import importlib.util
import inspect
import json
import logging
import os
from pathlib import Path
import platform
import secrets
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import unquote, urlsplit


def run_disposable_probe(source: Path, runtime: Path, receipt_path: Path,
                         repetitions: int = 25) -> dict:
    source, runtime, receipt_path = source.resolve(), runtime.resolve(), receipt_path.resolve()
    assert not runtime.exists(), "A fresh disposable runtime is required."
    assert repetitions >= 25, "The deterministic schedule must repeat at least 25 times."
    sys.dont_write_bytecode = True
    logging.disable(logging.CRITICAL)
    if os.name == "nt":
        version = sys.getwindowsversion()
        platform._uname_cache = platform.uname_result(
            "Windows", "synthetic", str(version.major),
            f"{version.major}.{version.minor}.{version.build}", "AMD64")
        platform._syscmd_ver = lambda *args, **kwargs: (
            "Windows", str(version.major), f"{version.major}.{version.minor}.{version.build}")
    violations, optional_probes = [], []

    def resolve_path(value):
        if isinstance(value, int):
            return None
        value = os.fsdecode(value)
        if value.startswith("file:"):
            value = unquote(urlsplit(value).path)
            if len(value) > 2 and value[0] == "/" and value[2] == ":":
                value = value[1:]
        return Path(value).resolve()

    def reject(reason):
        violations.append(reason)
        raise AssertionError("Disposable atomic probe safety guard: " + reason)

    def writable(path):
        return path.is_relative_to(runtime) or path == receipt_path

    def guard(event, values):
        if event == "open":
            path = resolve_path(values[0])
            if path is None:
                return
            if ".runtime" in path.parts and not path.is_relative_to(runtime):
                reject("operational_runtime_read")
            if path.suffix.lower() in {
                ".parquet", ".pq", ".arrow", ".feather", ".pkl", ".pickle",
                ".joblib", ".npy", ".npz", ".onnx", ".h5", ".hdf5", ".csv", ".xlsx",
            }:
                reject("row_or_model_file_read")
            mode, flags = str(values[1] or ""), int(values[2] or 0)
            if (any(c in mode for c in "wax+") or
                    flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                if not writable(path):
                    reject("write_outside_disposable_runtime")
        elif event == "sqlite3.connect":
            if str(values[0]) != ":memory:" and not resolve_path(values[0]).is_relative_to(runtime):
                reject("non_disposable_database")
        elif event in {"os.mkdir", "os.remove", "os.rmdir"}:
            if not writable(resolve_path(values[0])):
                reject("filesystem_mutation_outside_disposable_runtime")
        elif event in {"os.rename", "os.replace"}:
            if any(not writable(resolve_path(value)) for value in values[:2]):
                reject("filesystem_mutation_outside_disposable_runtime")
        elif event == "subprocess.Popen":
            if Path(str(values[0])).name.lower() == "lscpu" or str(values[1]) == "lscpu":
                optional_probes.append("optional_lscpu_blocked_before_launch")
                raise FileNotFoundError("Optional platform probe unavailable")
            reject("child_process_launch")
        elif event in {"os.system", "os.startfile"}:
            reject("process_launch")

    sys.addaudithook(guard)
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location(
        "atomic_probe_envelope", source / "scripts/run_security_tests.py")
    envelope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(envelope)
    environment = envelope.isolated_environment(runtime)
    environment.update({
        "ASP_MODEL_STUDIO_RUNTIME_ROOT": str(runtime / "sports-runtime"),
        "ASP_REQUIRE_ISOLATED_RUNTIME": "1",
        "ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT": str(runtime / "executable-artifacts"),
        "ATLAS_AUTH_ENABLED": "1", "ATLAS_ALLOW_PUBLIC_REGISTRATION": "1",
        "ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP": "0",
    })
    os.environ.clear()
    os.environ.update(environment)
    real_socket_connect = socket.socket.connect

    def local_testclient_socketpair(sock, address):
        # Windows uses loopback for asyncio's internal socket pair, not HTTP.
        if (sys._getframe(1).f_code.co_name == "_fallback_socketpair" and
                address[0] in {"127.0.0.1", "::1"}):
            return real_socket_connect(sock, address)
        reject("network_call")

    socket.socket.connect = local_testclient_socketpair
    socket.create_connection = lambda *args, **kwargs: reject("network_call")

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    # Fail visibly if an optional dependency's platform probe hits the guard,
    # instead of allowing a downstream optional-import fallback to obscure it.
    from sklearn.base import BaseEstimator, TransformerMixin
    from server.security import security_store as security
    from server.security.security_router import router as security_router
    from server.persistence import persistence_router as routes
    from server.persistence import initialize_persistence, get_persistence_service
    from server.persistence.repositories.audit_repository import AuditRepository
    from server.sharing.router import router as sharing_router
    from server.analytics.result_cache import RESULT_CACHE

    security.init_security_store()
    initialize_persistence()
    service = get_persistence_service()
    app = FastAPI()
    app.add_middleware(security.ActiveUserContextMiddleware)
    app.include_router(security_router, prefix="/api")
    app.include_router(routes.router, prefix="/api")
    app.include_router(sharing_router, prefix="/api")
    users, clients = {}, {}
    for label, role in (("A", "data_scientist"), ("B", "data_scientist"), ("admin", "admin")):
        password = secrets.token_urlsafe(30) + "aA1!"
        email = label.lower() + "@atomic-project-test.invalid"
        user = security.create_user(email=email, display_name=label, password=password, role=role)
        service.sync_user(user)
        client = TestClient(app)
        assert client.post("/api/auth/login", json={"email": email, "password": password}).status_code == 200
        users[label], clients[label] = user["userId"], client
        del password

    # Authentication activity can update session/user timestamps. All other
    # application tables (including workflow, cache, model, and policy records)
    # are compared. Only hashes/counts, never table rows or credentials, leave
    # the disposable process in the evidence receipt.
    def snapshot():
        result = {}
        with service.database.connection() as connection:
            names = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for name in names:
                if name == "users":
                    continue
                quoted = '"' + name.replace('"', '""') + '"'
                rows = [tuple(row) for row in connection.execute("SELECT * FROM " + quoted)]
                result["db:" + name] = sorted(rows, key=repr)
        with security.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE resource_type='project' ORDER BY audit_id").fetchall()
            result["security:project_audit_events"] = [tuple(row) for row in rows]
        result["security:visible_project_audit_events"] = sorted(
            security.list_audit_events(resource_type="project", limit=1000),
            key=lambda row: row["auditId"])
        result["runtime:artifacts"] = {
            str(path.relative_to(runtime)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in runtime.rglob("*")
            if path.is_file() and not any(token in path.name for token in (".db", ".sqlite"))
        }
        with RESULT_CACHE._lock:
            result["runtime:result_cache"] = repr(RESULT_CACHE._entries)
        return result

    def membership_count(project_id, actor):
        with service.database.connection() as connection:
            memberships = connection.execute(
                "SELECT COUNT(*) FROM project_collaborators WHERE project_id=? AND user_id=?",
                (project_id, users[actor])).fetchone()[0]
            permissions = connection.execute(
                "SELECT COUNT(*) FROM resource_permissions WHERE resource_type='project' AND resource_id=? AND principal_type='user' AND principal_id=?",
                (project_id, users[actor])).fetchone()[0]
            workflow = connection.execute(
                "SELECT COUNT(*) FROM workflow_state WHERE project_id=?", (project_id,)).fetchone()[0]
        return memberships, permissions, workflow

    def state_receipt(before, after):
        return {
            "unchanged": before == after,
            "comparedDomainTables": sum(name.startswith("db:") for name in before),
            "changedComponents": sorted(name for name in set(before) | set(after)
                                        if before.get(name) != after.get(name)),
        }

    checks = []

    def record(name, passed, **details):
        checks.append({"name": name, "passed": bool(passed), **details})

    @contextmanager
    def pause_operations(project_id, actor_labels):
        """Pause the real _execute entry immediately before operation()."""
        original = routes._execute
        arrivals = {users[label]: threading.Event() for label in actor_labels}
        release = threading.Event()

        def gate(operation):
            closure = inspect.getclosurevars(operation).nonlocals
            actor = (closure.get("user") or {}).get("userId")
            if (operation.__name__ == "operation" and closure.get("project_id") == project_id
                    and actor in arrivals):
                arrivals[actor].set()
                if not release.wait(30):
                    raise AssertionError("Synthetic pre-transaction barrier timed out")
            return original(operation)

        routes._execute = gate
        try:
            yield arrivals, release
        finally:
            release.set()
            routes._execute = original

    def create(actor, project_id, **extra):
        return clients[actor].post("/api/projects", json={
            "projectId": project_id, "projectName": "Synthetic owner " + actor,
            "metadata": {"ownerMarker": actor}, **extra})

    race_results = []
    for iteration in range(repetitions):
        project_id = f"atomic-missing-put-race-{iteration:03d}"
        assert service.projects.get(project_id) is None
        with pause_operations(project_id, ["A"]) as (arrivals, release):
            with ThreadPoolExecutor(max_workers=2) as pool:
                request = pool.submit(clients["A"].put, "/api/projects/" + project_id,
                                      json={"projectName": "Foreign replacement",
                                            "metadata": {"foreignMarker": "A"}})
                assert arrivals[users["A"]].wait(30), "A did not reach the barrier"
                assert service.projects.get(project_id) is None
                created = create("B", project_id)
                assert created.status_code == 200, "B did not commit legitimate creation"
                owner_record = service.projects.get(project_id)
                before = snapshot()
                release.set()
                response = request.result(timeout=30)
                after = snapshot()
        final = service.projects.get(project_id)
        membership, permission, workflow = membership_count(project_id, "A")
        state = state_receipt(before, after)
        row = {
            "iteration": iteration + 1, "createStatus": created.status_code,
            "putStatus": response.status_code,
            "ownerIsB": final["owner_user_id"] == users["B"],
            "creatorIsB": final["created_by"] == users["B"],
            "updaterIsNotA": final["updated_by"] != users["A"],
            "projectRowLogicallyUnchanged": final == owner_record,
            "nameUnchanged": final["project_name"] == owner_record["project_name"],
            "metadataUnchanged": final["metadata_json"] == owner_record["metadata_json"],
            "userAMembershipCount": membership, "userAPermissionCount": permission,
            "projectWorkflowRows": workflow, "domainState": state,
        }
        passed = (response.status_code in {403, 409} and final == owner_record and
                  membership == permission == workflow == 0 and state["unchanged"])
        row["passed"] = passed
        race_results.append(row)
        record(f"missing-ID PUT race repetition {iteration + 1}", **row)

    creation_results = []
    for iteration in range(10):
        project_id = f"atomic-dual-create-{iteration:02d}"
        with pause_operations(project_id, ["A", "B"]) as (arrivals, release):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = {actor: pool.submit(create, actor, project_id) for actor in ("A", "B")}
                assert all(event.wait(30) for event in arrivals.values())
                release.set()
                responses = {actor: future.result(timeout=30) for actor, future in futures.items()}
        winners = [actor for actor, response in responses.items() if response.status_code == 200]
        statuses = {actor: response.status_code for actor, response in responses.items()}
        final = service.projects.get(project_id)
        passed = len(winners) == 1
        if passed:
            winner = winners[0]
            loser = "B" if winner == "A" else "A"
            passed = (responses[loser].status_code in {403, 409} and
                      all(final[key] == users[winner] for key in ("owner_user_id", "created_by", "updated_by")) and
                      final["metadata_json"] == {"ownerMarker": winner} and
                      membership_count(project_id, winner)[:2] == (1, 1) and
                      membership_count(project_id, loser)[:2] == (0, 0))
            with service.database.connection() as connection:
                success = connection.execute(
                    "SELECT user_id FROM audit_log WHERE project_id=? AND action_type='project.created'",
                    (project_id,)).fetchall()
            passed = passed and [row[0] for row in success] == [users[winner]]
        item = {"iteration": iteration + 1, "statuses": statuses, "passed": bool(passed)}
        creation_results.append(item)
        record(f"simultaneous same-ID creation {iteration + 1}", passed, statuses=statuses)

    # Force both authenticated requests to start together; unlike the first
    # regression, success does not depend on which authorized writer wins.
    def together(requests):
        barrier = threading.Barrier(len(requests))

        def invoke(actor, project_id, payload):
            barrier.wait(timeout=30)
            return clients[actor].put("/api/projects/" + project_id, json=payload)

        with ThreadPoolExecutor(max_workers=len(requests)) as pool:
            futures = [pool.submit(invoke, *request) for request in requests]
            return [future.result(timeout=30) for future in futures]

    for iteration in range(10):
        project_id = f"atomic-owner-foreign-{iteration:02d}"
        assert create("B", project_id).status_code == 200
        owner, foreign = together([
            ("B", project_id, {"projectName": "Owner legitimate update", "metadata": {"ownerEdit": True}}),
            ("A", project_id, {"projectName": "Foreign update", "metadata": {"foreignEdit": True}}),
        ])
        final = service.projects.get(project_id)
        record(f"simultaneous owner/foreign update {iteration + 1}",
               owner.status_code == 200 and foreign.status_code == 403 and
               final["project_name"] == "Owner legitimate update" and
               final["metadata_json"] == {"ownerMarker": "B", "ownerEdit": True} and
               all(final[key] == users["B"] for key in ("owner_user_id", "created_by", "updated_by")),
               ownerStatus=owner.status_code, foreignStatus=foreign.status_code)

    for iteration in range(10):
        project_id = f"atomic-owner-admin-{iteration:02d}"
        assert create("B", project_id).status_code == 200
        owner, admin = together([
            ("B", project_id, {"metadata": {"ownerEdit": True}}),
            ("admin", project_id, {"metadata": {"adminEdit": True}}),
        ])
        final = service.projects.get(project_id)
        record(f"simultaneous legitimate owner/admin update {iteration + 1}",
               owner.status_code == admin.status_code == 200 and
               final["metadata_json"] == {"ownerMarker": "B", "ownerEdit": True, "adminEdit": True} and
               final["owner_user_id"] == final["created_by"] == users["B"] and
               final["updated_by"] in {users["B"], users["admin"]},
               ownerStatus=owner.status_code, administratorStatus=admin.status_code)

    project_id = "atomic-idempotent-creation"
    assert create("A", project_id).status_code == 200
    before = snapshot()
    duplicate = create("A", project_id, projectName="Duplicate attempted change")
    after = snapshot()
    record("duplicate legitimate POST is a governed nonmutating conflict",
           duplicate.status_code == 409 and before == after and
           membership_count(project_id, "A")[:2] == (1, 1),
           status=duplicate.status_code, domainState=state_receipt(before, after))
    before = snapshot()
    foreign_duplicate = create("B", project_id)
    after = snapshot()
    record("foreign duplicate POST preserves canonical nondisclosure denial",
           foreign_duplicate.status_code == 403 and before == after and
           foreign_duplicate.json() == {"detail": "Project creation requires a new project identity."},
           status=foreign_duplicate.status_code, domainState=state_receipt(before, after))

    missing_put = clients["A"].put("/api/projects/atomic-legitimate-put-create", json={
        "projectName": "Legitimate missing PUT", "metadata": {"ownerMarker": "A"}})
    record("legitimate missing-ID PUT creates exactly one owner membership",
           missing_put.status_code == 200 and
           membership_count("atomic-legitimate-put-create", "A")[:2] == (1, 1),
           status=missing_put.status_code)

    for index, (method, action, template) in enumerate((
        ("POST", "project.created", False), ("POST", "template.selected", True),
        ("PUT", "project.saved", False), ("PUT-missing", "project.saved", False),
    )):
        project_id = f"atomic-audit-rollback-{index}"
        if method == "PUT":
            assert create("B", project_id).status_code == 200
        original_audit = AuditRepository.create
        triggered = []

        def fail_audit(repository, audit_record):
            if audit_record.get("action_type") == action:
                triggered.append(action)
                raise sqlite3.OperationalError("Synthetic audit persistence failure")
            return original_audit(repository, audit_record)

        before = snapshot()
        try:
            AuditRepository.create = fail_audit
            body = {"projectId": project_id, "projectName": "Rollback name", "metadata": {"rollback": True}}
            if template:
                body["templateId"] = "synthetic-template"
            response = (clients["B"].post("/api/projects", json=body) if method == "POST" else
                        clients["B"].put("/api/projects/" + project_id, json=body))
        finally:
            AuditRepository.create = original_audit
        after = snapshot()
        record(f"audit failure rolls back {method} {action}",
               bool(triggered) and response.status_code >= 400 and before == after,
               auditFailureReached=bool(triggered), status=response.status_code,
               domainState=state_receipt(before, after))

    project_id = "atomic-immediate-revocation"
    assert create("B", project_id).status_code == 200
    assert clients["B"].post("/api/projects/" + project_id + "/access/grant", json={
        "userId": users["A"], "permission": "editor"}).status_code == 200
    with pause_operations(project_id, ["A"]) as (arrivals, release):
        with ThreadPoolExecutor(max_workers=2) as pool:
            pending = pool.submit(clients["A"].put, "/api/projects/" + project_id,
                                  json={"projectName": "Revoked member write"})
            assert arrivals[users["A"]].wait(30)
            revoked = clients["B"].post("/api/projects/" + project_id + "/access/revoke",
                                        json={"userId": users["A"]})
            assert revoked.status_code == 200
            before = snapshot()
            release.set()
            response = pending.result(timeout=30)
            after = snapshot()
    record("revocation before write transaction immediately denies pending editor",
           response.status_code == 403 and before == after,
           status=response.status_code, domainState=state_receipt(before, after))

    # These are synthetic audit fixtures only. Include canonical-only,
    # legacy-only, and historical mirrored events with tied timestamps, so
    # filtering, deduplication, and the global limit are exercised together.
    audit_project = "atomic-audit-projection"
    assert create("B", audit_project).status_code == 200
    timestamp = "2099-01-01T00:00:00+00:00"
    fixtures = [
        ("atomic-audit-z", "project.saved", "B", "project", audit_project, "success", True, False),
        ("atomic-audit-y", "project.created", "B", "project", audit_project, "success", True, True),
        ("atomic-audit-x", "project.opened", "A", "project", audit_project, "success", False, True),
        ("atomic-audit-w", "project.saved", "A", "project", audit_project, "denied", False, True),
        ("atomic-audit-v", "template.selected", "B", "project", audit_project, "success", True, False),
        ("atomic-audit-u", "synthetic.other", "A", "synthetic", "other", "success", False, True),
        ("atomic-audit-t", "project.saved", "B", "project", "atomic-audit-other", "success", True, False),
    ]
    for audit_id, action, actor, resource_type, resource_id, outcome, canonical, legacy in fixtures:
        metadata = {"projectId": resource_id, "fixture": "canonical", "outcome": outcome}
        if canonical:
            service.audit.create({"audit_id": audit_id, "project_id": resource_id,
                                  "user_id": users[actor], "action_type": action,
                                  "entity_type": resource_type, "entity_id": resource_id,
                                  "created_at": timestamp, "metadata_json": metadata})
        if legacy:
            with security.connect() as connection:
                connection.execute(
                    "INSERT INTO audit_events (audit_id,timestamp,user_id,action,resource_type,resource_id,outcome,reason,metadata_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (audit_id, timestamp, users[actor], action, resource_type, resource_id,
                     outcome, "historical fixture", json.dumps({**metadata, "fixture": "legacy"})))
                connection.commit()

    def fixture_ids(events):
        return [event["auditId"] for event in events if event["auditId"].startswith("atomic-audit-")]

    projection_cases = [
        ("global tied timestamp limit", {"limit": 2}, ["atomic-audit-z", "atomic-audit-y"]),
        ("project filter", {"project_id": audit_project},
         ["atomic-audit-z", "atomic-audit-y", "atomic-audit-x", "atomic-audit-w", "atomic-audit-v"]),
        ("user filter", {"project_id": audit_project, "user_id": users["A"]},
         ["atomic-audit-x", "atomic-audit-w"]),
        ("action filter", {"project_id": audit_project, "action": "project.saved"},
         ["atomic-audit-z", "atomic-audit-w"]),
        ("outcome filter", {"project_id": audit_project, "outcome": "denied"}, ["atomic-audit-w"]),
        ("resource filter", {"resource_type": "synthetic"}, ["atomic-audit-u"]),
        ("combined filter", {"project_id": audit_project, "resource_type": "project",
                              "user_id": users["B"], "action": "project.saved", "outcome": "success"},
         ["atomic-audit-z"]),
    ]
    for name, parameters, expected in projection_cases:
        actual = fixture_ids(security.list_audit_events(**parameters))
        record("audit projection " + name, actual == expected, expected=expected, actual=actual)
    resource_events = security.audit_events_for_resource("project", audit_project)
    record("audit projection per-resource filter",
           fixture_ids(resource_events) == ["atomic-audit-z", "atomic-audit-y", "atomic-audit-x", "atomic-audit-w", "atomic-audit-v"])
    duplicate_events = [event for event in resource_events if event["auditId"] == "atomic-audit-y"]
    record("audit projection preserves historical mirrored payload exactly once",
           len(duplicate_events) == 1 and duplicate_events[0]["metadata"]["fixture"] == "legacy" and
           duplicate_events[0]["reason"] == "historical fixture")
    original_connection = service.database.connection

    @contextmanager
    def unavailable_audit_store():
        raise sqlite3.OperationalError("Synthetic unavailable audit store")
        yield

    try:
        service.database.connection = unavailable_audit_store
        unavailable_status = None
        try:
            security.list_audit_events(project_id=audit_project)
        except Exception as exc:
            unavailable_status = getattr(exc, "status_code", None)
    finally:
        service.database.connection = original_connection
    record("audit projection fails explicitly when canonical audit store unavailable", unavailable_status == 503,
           status=unavailable_status)

    with service.database.connection() as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    result = {
        "schemaVersion": "ATOMIC_PROJECT_AUTHORIZATION_DISPOSABLE_PROBE_V1",
        "sourceRoot": str(source), "runtimeRoot": str(runtime),
        "synchronization": "threading.Event at identical _execute(operation) boundary before the write transaction; no timing sleeps",
        "schedule": ["A reaches pre-write boundary while ID absent", "B commits POST", "snapshot B state", "release A PUT", "compare complete domain state"],
        "raceRepetitions": repetitions, "raceResults": race_results,
        "sameIdCreationRepetitions": 10, "sameIdCreationResults": creation_results,
        "ownerForeignConcurrencyRepetitions": 10, "ownerAdminConcurrencyRepetitions": 10,
        "checks": checks, "passed": all(check["passed"] for check in checks),
        "checkCount": len(checks), "passCount": sum(check["passed"] for check in checks),
        "failedChecks": [check["name"] for check in checks if not check["passed"]],
        "databaseIntegrity": integrity, "guardViolations": violations,
        "optionalPlatformProbes": optional_probes,
        "scope": "Synthetic authenticated TestClient requests; every application table except user activity, project security audit events, disposable artifact hashes, and in-memory result cache compared. No browser is started.",
        "authoritativeModelActivity": 0, "policyAdoptions": 0, "featureRegistrations": 0,
        "finalOotAccess": 0, "currentGoldMutations": 0, "providerCalls": 0,
        "sourceHashes": {name: hashlib.sha256((source / name).read_bytes()).hexdigest()
                         for name in ("server/persistence/persistence_router.py",
                                      "server/persistence/repositories/project_repository.py",
                                      "server/security/security_store.py")},
        "testSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    receipt_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(receipt_path), "checks": len(checks),
                      "passed": result["passCount"], "failed": result["failedChecks"],
                      "raceRepetitions": repetitions, "guardViolations": len(violations)}))
    return result


class TenantProjectAtomicAuthorizationTest(unittest.TestCase):
    def test_atomic_project_authorization_under_deterministic_concurrency(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="tenant-project-atomic-",
                                         dir=os.environ.get("ATLAS_HERMETIC_ROOT")) as directory:
            parent = Path(directory)
            receipt = parent / "atomic-authorization-receipt.json"
            completed = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--probe",
                 "--source", str(source), "--runtime", str(parent / "runtime"),
                 "--receipt", str(receipt)], cwd=source, capture_output=True,
                text=True, timeout=240)
            self.assertEqual(completed.returncode, 0,
                             "Disposable atomic harness failed before producing a valid receipt.")
            result = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(result["databaseIntegrity"], "ok")
            self.assertEqual(result["guardViolations"], [])
            for check in result["checks"]:
                with self.subTest(probe=check["name"]):
                    self.assertTrue(check["passed"], json.dumps(check, sort_keys=True))


if __name__ == "__main__":
    if "--probe" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--probe", action="store_true")
        parser.add_argument("--source", type=Path, required=True)
        parser.add_argument("--runtime", type=Path, required=True)
        parser.add_argument("--receipt", type=Path, required=True)
        parser.add_argument("--repetitions", type=int, default=25)
        options = parser.parse_args()
        run_disposable_probe(options.source, options.runtime, options.receipt, options.repetitions)
    else:
        unittest.main()
