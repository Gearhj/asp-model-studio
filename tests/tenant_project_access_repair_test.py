"""Disposable HTTP reproductions; no operational database or science readers."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import sys
from urllib.parse import unquote, urlsplit
from concurrent.futures import ThreadPoolExecutor

import subprocess
import tempfile
import unittest
from types import SimpleNamespace


def run_disposable_probe(source, runtime, receipt):
    opts = SimpleNamespace(source=source, runtime=runtime, receipt=receipt)
    source = opts.source.resolve()
    runtime = opts.runtime.resolve()
    assert not runtime.exists(), 'A fresh disposable runtime is required.'
    sys.path.insert(0, str(source))
    spec = importlib.util.spec_from_file_location('security_envelope', source/'scripts/run_security_tests.py')
    envelope = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(envelope)
    environment = envelope.isolated_environment(runtime)
    environment.update({
        'ASP_MODEL_STUDIO_RUNTIME_ROOT': str(runtime/'sports-runtime'),
        'ASP_REQUIRE_ISOLATED_RUNTIME': '1',
        'ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT': str(runtime/'executable-artifacts'),
        'ATLAS_AUTH_ENABLED': '1', 'ATLAS_ALLOW_PUBLIC_REGISTRATION': '1',
        'ATLAS_ENABLE_LOCAL_USER_BOOTSTRAP': '0',
    })
    os.environ.clear()
    os.environ.update(environment)
    real_connect = sqlite3.connect
    def isolated_connect(database, *args, **kwargs):
        path = str(database)
        if path != ':memory:':
            checked = unquote(urlsplit(path).path) if path.startswith('file:') else path
            if len(checked)>2 and checked[0]=='/' and checked[2]==':':
                checked=checked[1:]
            assert Path(checked).resolve().is_relative_to(runtime), 'Database escaped disposable root'
        return real_connect(database, *args, **kwargs)
    sqlite3.connect = isolated_connect
    real_socket_connect = socket.socket.connect
    def guarded_connect(sock, address):
        # Windows implements asyncio's internal socket pair over loopback.
        if sys._getframe(1).f_code.co_name == '_fallback_socketpair' and address[0] in ('127.0.0.1','::1'):
            return real_socket_connect(sock, address)
        raise AssertionError('Network calls are forbidden in the tenant probe')
    def forbidden_network(*args, **kwargs):
        raise AssertionError('Network calls are forbidden in the tenant probe')
    socket.socket.connect = guarded_connect
    socket.create_connection = forbidden_network

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from server.security import security_store as security
    from server.security.security_router import router as security_router
    from server.persistence.persistence_router import router as persistence_router
    from server.sharing.router import router as sharing_router
    from server.persistence import initialize_persistence, get_persistence_service

    security.init_security_store()
    initialize_persistence()
    app = FastAPI()
    app.add_middleware(security.ActiveUserContextMiddleware)
    app.include_router(security_router, prefix='/api')
    app.include_router(persistence_router, prefix='/api')
    app.include_router(sharing_router, prefix='/api')
    service = get_persistence_service()
    users = {}
    clients = {}
    for label, role in [('admin','admin'),('A','data_scientist'),('B','data_scientist')]:
        password = secrets.token_urlsafe(30)+'aA1!'
        email = label.lower()+'@tenant-repair.invalid'
        user = security.create_user(email=email, display_name=label, password=password, role=role)
        service.sync_user(user)
        client = TestClient(app)
        response = client.post('/api/auth/login', json={'email':email,'password':password})
        assert response.status_code == 200, 'Synthetic login failed'
        users[label] = user['userId']
        clients[label] = client
        del password

    projects = {}
    for owner in ('A','B'):
        for number in (1,2):
            label = owner+str(number)
            response = clients[owner].post('/api/projects', json={'projectName':'Synthetic '+label})
            assert response.status_code == 200, 'Synthetic project creation failed'
            projects[label] = response.json()['project']['projectId']

    def protected_snapshot():
        tables = ['projects','resource_permissions','project_collaborators','sharing_events','audit_log','notifications']
        out = {}
        with service.database.connection() as connection:
            existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for table in tables:
                if table in existing:
                    out[table] = [tuple(row) for row in connection.execute('SELECT * FROM '+table+' ORDER BY 1')]
        return out

    checks = []
    def probe(name, label, method, path, body=None, expected=403, unchanged=False):
        before = protected_snapshot() if unchanged else None
        response = clients[label].request(method,path,json=body)
        same = before == protected_snapshot() if unchanged else None
        checks.append({'name':name,'actor':label,'method':method,'path':path,'status':response.status_code,
                       'expectedStatus':expected,'protectedStateUnchanged':same,
                       'passed':response.status_code == expected and (not unchanged or same)})
        return response

    b1 = projects['B1']; b2 = projects['B2']; a1 = projects['A1']
    initial_owner_rows=service.access.list_permissions_for_resource('project',a1)
    checks.append({'name':'Server creation bootstraps exactly one creator membership',
                   'passed':len(initial_owner_rows)==1 and initial_owner_rows[0]['principal_id']==users['A']
                    and initial_owner_rows[0]['granted_by_user_id']==users['A']})
    from server.persistence.repositories.access_repository import AccessRepository
    original_acl_list=AccessRepository.list_permissions_for_resource
    acl_list_calls=[]
    def observed_acl_list(self,resource_type,resource_id):
        acl_list_calls.append((resource_type,resource_id))
        return original_acl_list(self,resource_type,resource_id)
    try:
        AccessRepository.list_permissions_for_resource=observed_acl_list
        probe('F-004 foreign ACL read', 'A','GET',f'/api/projects/{b1}/access',unchanged=True)
    finally:
        AccessRepository.list_permissions_for_resource=original_acl_list
    checks.append({'name':'Unauthorized ACL never enumerates membership rows or counts','passed':not acl_list_calls})
    probe('F-001 self grant on foreign project','A','POST',f'/api/projects/{b1}/access/grant',
          {'userId':users['A'],'permission':'owner'},unchanged=True)
    probe('F-001 foreign project remains forbidden','A','GET',f'/api/projects/{b1}')
    probe('Unauthorized invite','A','POST',f'/api/projects/{b2}/access/grant',
          {'userId':users['A'],'permission':'editor'},unchanged=True)
    probe('Unauthorized revoke','A','POST',f'/api/projects/{b2}/access/revoke',
          {'userId':users['B']},unchanged=True)
    probe('Modern unauthorized invite','A','POST',f'/api/sharing/resources/project/{b2}/share',
          {'principalType':'user','principalId':users['A'],'permissionLevel':'admin'},unchanged=True)
    probe('Modern unauthorized ACL read','A','GET',f'/api/sharing/resources/project/{b2}',unchanged=True)
    probe('Modern unauthorized revoke','A','POST',f'/api/sharing/resources/project/{b2}/revoke',
          {'principalType':'user','principalId':users['B']},unchanged=True)
    probe('Guessed project bootstrap denied','A','POST','/api/projects/synthetic-unknown/access/grant',
          {'userId':users['A'],'permission':'owner'},unchanged=True)
    probe('POST existing project takeover denied','A','POST','/api/projects',
          {'projectId':b2,'projectName':'Attempted replacement','ownerUserId':users['A']},unchanged=True)
    probe('Owner share permitted','A','POST',f'/api/projects/{a1}/access/grant',
          {'userId':users['B'],'permission':'editor'},expected=200)
    probe('Member cannot self elevate','B','POST',f'/api/projects/{a1}/access/grant',
          {'userId':users['B'],'permission':'owner'},unchanged=True)
    probe('Member cannot use modern role escalation','B','POST',f'/api/sharing/resources/project/{a1}/share',
          {'principalType':'user','principalId':users['B'],'permissionLevel':'admin'},unchanged=True)
    probe('Member cannot alter owner in body','B','PUT',f'/api/projects/{a1}',
          {'ownerUserId':users['B'],'createdBy':users['B'],'updatedBy':users['A']},expected=403,unchanged=True)
    probe('Member cannot read full ACL','B','GET',f'/api/projects/{a1}/access',unchanged=True)
    sharing = probe('Member sharing status minimal','B','GET',f'/api/sharing/resources/project/{a1}',expected=200)
    if sharing.status_code == 200:
        status = sharing.json()['sharing']
        checks.append({'name':'Member sharing details redacted','passed':not any(status.get(k) for k in ['ownerUserId','permissions','events','shareLinks'])})
    probe('Owner ACL available','A','GET',f'/api/projects/{a1}/access',expected=200)
    probe('Administrator ACL available','admin','GET',f'/api/projects/{a1}/access',expected=200)
    probe('Owner revoke permitted','A','POST',f'/api/projects/{a1}/access/revoke',{'userId':users['B']},expected=200)
    probe('Revoked access immediately denied','B','GET',f'/api/projects/{a1}')
    probe('Administrator share permitted','admin','POST',f'/api/projects/{b2}/access/grant',
          {'userId':users['A'],'permission':'viewer'},expected=200)
    snapshot = protected_snapshot()
    probe('Duplicate share idempotent','admin','POST',f'/api/projects/{b2}/access/grant',
          {'userId':users['A'],'permission':'viewer'},expected=200,unchanged=True)

    spoof = clients['A'].post('/api/projects',json={'projectName':'Synthetic spoof input',
            'ownerUserId':users['B'],'createdBy':users['B'],'updatedBy':users['B']})
    if spoof.status_code == 200:
        record = service.projects.get(spoof.json()['project']['projectId'])
        checks.append({'name':'Creation actor comes only from authenticated context',
                       'passed':all(record[k]==users['A'] for k in ['owner_user_id','created_by','updated_by'])})
    else:
        checks.append({'name':'Creation actor comes only from authenticated context','passed':False,'status':spoof.status_code})

    foreign = clients['A'].get(f'/api/projects/{projects["B1"]}/access')
    missing = clients['A'].get('/api/projects/synthetic-unknown-two/access')
    checks.append({'name':'Unknown and foreign ACL nondisclosure','passed':foreign.status_code==missing.status_code==403 and foreign.content==missing.content})

    # Force an audit-store failure after the grant would have been written. The
    # entire ACL transaction must roll back, including collaborator/event changes.
    from server.persistence.repositories.audit_repository import AuditRepository
    original_audit_create=AuditRepository.create
    def reject_grant_audit(self, record):
        if record.get('action_type')=='resource_shared':
            raise RuntimeError('Synthetic audit storage failure')
        return original_audit_create(self,record)
    before_failure=protected_snapshot()
    try:
        AuditRepository.create=reject_grant_audit
        try:
            clients['A'].post(f'/api/projects/{projects["A2"]}/access/grant',json={'userId':users['B'],'permission':'viewer'})
        except RuntimeError:
            pass
    finally:
        AuditRepository.create=original_audit_create
    checks.append({'name':'ACL rolls back when attributable audit cannot persist','passed':before_failure==protected_snapshot()})

    with service.database.connection() as connection:
        rows=connection.execute("SELECT user_id, action_type FROM audit_log WHERE entity_type='project' AND action_type IN ('resource_shared','share_revoked')").fetchall()
    checks.append({'name':'All allowed ACL mutations have an authenticated audit actor','passed':bool(rows) and all(row['user_id'] in users.values() for row in rows)})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(clients[label].get,f'/api/projects/{projects[label+"2"]}') for label in ('A','B')]
        results=[f.result() for f in futures]
    checks.append({'name':'Two concurrent users retain own project identity', 'passed':all(r.status_code==200 and r.json()['project']['projectId']==projects[label+'2'] for label,r in zip(('A','B'),results))})

    with service.database.connection() as connection:
        integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
    receipt={'schemaVersion':'TENANT_REPAIR_DISPOSABLE_PROBE_V1','sourceRoot':str(source),'disposableRuntimeRoot':str(runtime),
             'users':3,'projectsPerOrdinaryUser':2,'checks':checks,'passed':all(x['passed'] for x in checks),
             'databaseIntegrity':integrity,'authoritativeFits':0,'providerCalls':0,'finalOotOpens':0}
    opts.receipt.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'receipt':str(opts.receipt),'checks':len(checks),'passed':sum(x['passed'] for x in checks),
                      'failed':[x['name'] for x in checks if not x['passed']],'databaseIntegrity':integrity}))



class TenantProjectAccessRepairTest(unittest.TestCase):
    def test_two_user_project_membership_and_acl_boundaries(self):
        source = Path(__file__).resolve().parents[1]
        parent = os.environ.get("ATLAS_HERMETIC_ROOT")
        with tempfile.TemporaryDirectory(prefix="tenant-project-access-", dir=parent) as temp:
            temp_root = Path(temp)
            receipt_path = temp_root / "tenant-authorization-receipt.json"
            result = subprocess.run(
                [sys.executable, "-B", str(Path(__file__).resolve()), "--probe",
                 "--source", str(source), "--runtime", str(temp_root / "runtime"),
                 "--receipt", str(receipt_path)],
                cwd=source, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(result.returncode, 0, "Disposable authorization harness failed: " + result.stderr)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["databaseIntegrity"], "ok")
            for check in receipt["checks"]:
                with self.subTest(probe=check["name"]):
                    self.assertTrue(check["passed"], json.dumps(check, sort_keys=True))


if __name__ == "__main__":
    if "--probe" in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument("--probe", action="store_true")
        parser.add_argument("--source", type=Path, required=True)
        parser.add_argument("--runtime", type=Path, required=True)
        parser.add_argument("--receipt", type=Path, required=True)
        options = parser.parse_args()
        run_disposable_probe(options.source, options.runtime, options.receipt)
    else:
        unittest.main()
