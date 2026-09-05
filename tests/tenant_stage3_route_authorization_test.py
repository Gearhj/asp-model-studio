"""Adversarial HTTP route coverage: isolated four-project SQLite; no science execution."""
from __future__ import annotations
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from server.core import modeling_scope as scope
from server.persistence import persistence_router as P
from server.persistence.db import Database
from server.persistence.service import PersistenceService
from server.security.security_store import require_user
from server.sports_cockpit import router as C
from server.sports_cockpit import gen3_authority as A

RETIRED = {'champion', 'experiment_run', 'experiments', 'experiment', 'autopilot', 'simulate', 'eligibility', 'provider_verify', 'feature_ablation'}
STAGE3 = [r for r in [*P.router.routes, *C.router.routes] if '/sports/stage3-' in r.path or r.path.startswith('/cockpit/')]
SUPPORT = [r for r in P.router.routes if ('/projects/{project_id}/' in r.path and '/sports/stage3-' not in r.path) or (r.path == '/projects/{project_id}' and 'PUT' not in r.methods)]
ACTIVE = [r for r in STAGE3 if r.endpoint.__name__ not in RETIRED]

def dependency_calls(route):
    def walk(dep):
        yield dep.call
        for child in dep.dependencies:
            yield from walk(child)
    return set(walk(route.dependant))

def route_matrix():
    return [{
        'method': next(iter(r.methods)), 'path': '/api'+r.path,
        'handler': r.endpoint.__name__, 'authenticated': require_user in dependency_calls(r),
        'projectAuthorized': bool(dependency_calls(r) & {scope.require_project_view, scope.require_project_edit}),
        'state': 'RETIRED_410' if r.endpoint.__name__ in RETIRED else 'PROJECT_AUTHORIZED',
        'researchBindingRequired': C.require_legacy_research_project in dependency_calls(r),
        'payloadProjectConflictRejected': r.endpoint.__name__ not in RETIRED,
    } for r in STAGE3]

@pytest.fixture(scope='module')
def synthetic_projects(tmp_path_factory):
    root=tmp_path_factory.mktemp('four-project-db')
    db=Database(str(root/'projects.db')); db.initialize(); service=PersistenceService(db)
    for owner in ('user-a','user-b'):
        for index in (1,2):
            service.projects.upsert({'project_id': f'{owner}-project-{index}', 'project_name':f'Synthetic {owner} {index}', 'owner_user_id':owner})
    return service

@pytest.fixture(scope='module')
def application():
    app=FastAPI(); app.include_router(P.router,prefix='/api'); app.include_router(C.router,prefix='/api')
    def authenticated(x_test_actor: str | None=Header(default=None)):
        if not x_test_actor: raise HTTPException(401,'Authentication required.')
        return {'userId':x_test_actor,'status':'active'}
    app.dependency_overrides[require_user]=authenticated
    return app

@pytest.fixture
def env(tmp_path, monkeypatch, synthetic_projects, application):
    service=synthetic_projects
    monkeypatch.setattr('server.persistence.service.get_persistence_service',lambda:service)
    monkeypatch.setattr(P,'_service',lambda:service)
    monkeypatch.setattr(A,'STATE_ROOT',tmp_path/'authority')
    with TestClient(application) as client: yield client,service

def url(route, project='user-b-project-1'):
    import re
    path=route.path.replace('{project_id}',project)
    path=re.sub(r'\{[^}]+\}', 'a'*32, path)
    return '/api'+path+'?projectId='+project

@pytest.mark.parametrize('route',STAGE3,ids=lambda r:next(iter(r.methods))+' '+r.path)
def test_every_stage3_route_has_canonical_authentication_and_scope(route):
    calls=dependency_calls(route)
    assert require_user in calls
    if route.endpoint.__name__ not in RETIRED:
        assert calls & {scope.require_project_view,scope.require_project_edit}

@pytest.mark.parametrize('route',SUPPORT,ids=lambda r:next(iter(r.methods))+' '+r.path)
def test_supporting_project_routes_share_the_canonical_dependency(route):
    assert dependency_calls(route) & {scope.require_project_view,scope.require_project_edit}

@pytest.mark.parametrize('route',ACTIVE,ids=lambda r:next(iter(r.methods))+' '+r.path)
def test_every_active_stage3_route_rejects_cross_user_before_service(env, route):
    client,_=env
    for actor,project in [('user-a','user-b-project-1'),('user-b','user-a-project-2')]:
        response=client.request(next(iter(route.methods)),url(route,project),json={'projectId':project},headers={'x-test-actor':actor})
        assert response.status_code==403, (route.path,response.status_code,response.text)
        assert response.json()=={'detail':'Project access is not permitted.'}

@pytest.mark.parametrize('route',ACTIVE,ids=lambda r:next(iter(r.methods))+' '+r.path)
def test_every_active_stage3_route_rejects_anonymous(env,route):
    response=env[0].request(next(iter(route.methods)),url(route),json={'projectId':'user-b-project-1'})
    assert response.status_code==401

@pytest.mark.parametrize('body',[{'projectId':'user-b-project-1'},{'project_id':'user-b-project-1'},{'specification':{'projectId':'user-b-project-1'}}])
def test_path_query_and_nested_payload_cannot_change_project(env,body):
    response=env[0].post('/api/projects/user-a-project-1/sports/stage3-model-laboratory/plan',json=body,headers={'x-test-actor':'user-a'})
    assert response.status_code==409

def test_unknown_and_foreign_ids_have_identical_denial_without_writes(env):
    client,service=env
    before=Path(service.database.path).read_bytes()
    responses=[client.get('/api/cockpit/data-preview?projectId='+pid,headers={'x-test-actor':'user-a'}) for pid in ('unknown-project','user-b-project-1')]
    assert [(r.status_code,r.json()) for r in responses]==[(403,{'detail':'Project access is not permitted.'})]*2
    assert Path(service.database.path).read_bytes()==before

def test_f006_reproduction_now_denied_before_shared_reader(env,monkeypatch):
    reads=[]
    monkeypatch.setattr(C.E,'data_preview',lambda **kw:reads.append(kw) or {'syntheticMarker':'shared-unscoped-research'})
    response=env[0].get('/api/cockpit/data-preview?projectId=user-b-project-1',headers={'x-test-actor':'user-a'})
    assert response.status_code==403 and reads==[]

def test_legacy_view_missing_binding_fails_closed_without_global_fallback(env,monkeypatch):
    monkeypatch.setattr(C.E,'data_preview',lambda **kw:pytest.fail('Unbound project reached global research'))
    response=env[0].get('/api/cockpit/data-preview?projectId=user-a-project-1',headers={'x-test-actor':'user-a'})
    assert response.status_code==409
    assert response.json()['detail']['code']=='PROJECT_RESEARCH_BINDING_REQUIRED'

def bind_fake_research(monkeypatch):
    monkeypatch.setattr(A,'active_binding',lambda *,project_id:{'projectId':project_id,'generation':'GEN2','bindingId':'synthetic-binding','datasetVersionId':'synthetic-research','datasetContentSha256':'1'*64,'revision':1})
    monkeypatch.setattr(A,'_selectable_research_entry',lambda generation:{'datasetVersionId':'synthetic-research','objectKind':'gen2-research','logicalContentSha256':'1'*64,'physicalParquetSha256':'2'*64,'contractBundleSha256':'3'*64})

@pytest.mark.parametrize('changed',[
    {'projectId':'user-b-project-1'}, {'generation':'GEN3'},
    {'datasetVersionId':'substituted-dataset'}, {'datasetContentSha256':'4'*64},
])
def test_foreign_or_stale_binding_cannot_reach_cached_data(env,monkeypatch,changed):
    bind_fake_research(monkeypatch)
    original=A.active_binding(project_id='user-a-project-1')
    monkeypatch.setattr(A,'active_binding',lambda **kw:{**original,**changed})
    monkeypatch.setattr(C.E,'data_preview',lambda **kw:pytest.fail('Substituted authority reached global research'))
    assert env[0].get('/api/cockpit/data-preview?projectId=user-a-project-1',headers={'x-test-actor':'user-a'}).status_code==409

def test_exact_legacy_bindings_preserve_views_and_partition_simultaneous_users(env,monkeypatch):
    bind_fake_research(monkeypatch)
    monkeypatch.setattr(C.E,'data_preview',lambda **kw:{'scope':C.E.RESEARCH_REQUEST_SCOPE.get(),'cacheScope':C.E._research_cache_scope()})
    requests=[('user-a','user-a-project-1'),('user-a','user-a-project-2'),('user-b','user-b-project-1'),('user-b','user-b-project-2')]
    def read(pair):
        actor,project=pair
        response=env[0].get('/api/cockpit/data-preview?projectId='+project,headers={'x-test-actor':actor})
        assert response.status_code==200
        assert response.headers['cache-control']=='private, no-store'
        assert response.json()['scope']['projectId']==project
        assert response.json()['scope']['userId']==actor
        return response.json()['cacheScope']
    with ThreadPoolExecutor(max_workers=4) as pool: assert len(set(pool.map(read,requests)))==4

@pytest.mark.parametrize('getter,kind,id_name',[('get_binding','bindings','binding_id'),('get_run_authority','authorities','run_authority_id'),('get_run','runs','run_id')])
def test_guessed_and_copied_foreign_gen3_identifiers_fail_closed(env,getter,kind,id_name):
    identity='a'*32
    foreign=A._state('user-b-project-1',kind,identity+'.json'); foreign.parent.mkdir(parents=True)
    foreign.write_text(json.dumps({'projectId':'user-b-project-1','status':'ACTIVE'}),encoding='utf-8')
    with pytest.raises(A.AuthorityError):getattr(A,getter)(project_id='user-a-project-1',**{id_name:identity})
    copied=A._state('user-a-project-1',kind,identity+'.json'); copied.parent.mkdir(parents=True)
    copied.write_bytes(foreign.read_bytes())
    with pytest.raises(A.AuthorityError,match='does not belong'):getattr(A,getter)(project_id='user-a-project-1',**{id_name:identity})


@pytest.mark.parametrize('route', SUPPORT, ids=lambda r:next(iter(r.methods))+' '+r.path)
def test_configuration_exports_evidence_and_support_routes_deny_nonmembers(env, route):
    response = env[0].request(next(iter(route.methods)), url(route),
        json={'projectId':'user-b-project-1'}, headers={'x-test-actor':'user-a'})
    assert response.status_code == 403


def test_projectless_request_and_duplicate_identity_are_rejected(env):
    client, _ = env
    headers = {'x-test-actor':'user-a'}
    assert client.get('/api/cockpit/profile', headers=headers).status_code == 400
    response = client.get('/api/cockpit/profile?projectId=user-a-project-1&projectId=user-a-project-2', headers=headers)
    assert response.status_code == 409

@pytest.mark.parametrize('field', ['datasetVersionId','logicalContentSha256','physicalParquetSha256','contractBundleSha256'])
def test_research_authority_changed_between_authorization_and_read_is_rejected(monkeypatch, field):
    verified = {'datasetVersionId':'exact-research', 'logicalContentSha256':'1'*64,
        'physicalParquetSha256':'2'*64, 'contractBundleSha256':'3'*64, 'path':Path('synthetic-not-opened')}
    request_scope = {'datasetVersionId':'exact-research', 'datasetContentSha256':'1'*64,
        'physicalParquetSha256':'2'*64, 'contractBundleSha256':'3'*64}
    token = C.E.RESEARCH_REQUEST_SCOPE.set(request_scope)
    monkeypatch.setattr(A, 'verified_research_object', lambda generation:{**verified, field:'tampered'})
    try:
        with pytest.raises(C.E.CockpitError, match='changed before'):
            C.E._feature_view_path()
    finally:
        C.E.RESEARCH_REQUEST_SCOPE.reset(token)
