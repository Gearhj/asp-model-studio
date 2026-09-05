"""Disposable full-app browser acceptance. No operational services are touched."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import re
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import uuid
from urllib.parse import urlsplit,unquote

WORK = Path(r'C:\Users\james\worktrees\asp-model-studio-tenant-workflow-repair-v1')
PRIMARY_RUNTIME = Path(r'C:\Users\james\asp-model-studio\.runtime\asp-model-studio')
SCRATCH = Path(__file__).resolve().parent
SOURCE_DB = PRIMARY_RUNTIME / 'persistence' / 'asp_model_studio.db'
NODE = Path(r'C:\Program Files\nodejs\node.exe')

def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def stage3_snapshot(connection):
    tables = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'stage3_%'")]
    return {table: sha(canonical(sorted([list(r) for r in connection.execute('SELECT * FROM "'+table+'"')], key=repr))) for table in tables}

def metadata_snapshot(connection, tables):
    return {table: sha(canonical(sorted([list(r) for r in connection.execute('SELECT * FROM "'+table+'"')], key=repr))) for table in tables}

def clone_allowlisted_metadata(source, target):
    """Copy schema and reviewed science/project metadata only; credential tables stay empty."""
    tables = source.execute("SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid").fetchall()
    names={row[0] for row in tables}
    allowed={name for name in names if name.startswith('stage3_')} | {
        'projects','users','datasets','dataset_versions','project_dataset_links',
        'active_modeling_dataset_versions','sports_dataset_registrations','sports_dataset_partitions',
        'sports_dataset_schemas','sports_dataset_populations','sports_dataset_temporal_folds',
        'sports_dataset_rights','sports_dataset_limitations','sports_research_projects',
    }
    sensitive=re.compile(r'password|passwd|secret|token|cookie|credential|api_?key|authorization|connection.?string|dsn',re.I)
    def inspect(value):
        if isinstance(value,dict):
            if any(sensitive.search(key) and item not in (None,'',False,[],{}) for key,item in value.items()): raise RuntimeError('Credential-bearing metadata cannot enter browser fixture')
            for item in value.values(): inspect(item)
        elif isinstance(value,list):
            for item in value: inspect(item)
        elif isinstance(value,str) and re.search(r'(?i)(?:postgres(?:ql)?|mysql|mongodb)://[^/@]+:[^/@]+@',value): raise RuntimeError('Connection credential cannot enter browser fixture')
    counts={}
    target.execute('PRAGMA foreign_keys=OFF')
    for name,sql in tables:
        target.execute(sql)
        if name not in allowed: continue
        columns=[r[1] for r in source.execute('PRAGMA table_info("'+name+'")')]
        assert not any(sensitive.search(column) for column in columns)
        projection=','.join("'{}'" if (name=='dataset_versions' and column=='profile_json') or (name=='users' and column=='metadata_json') else '"'+column+'"' for column in columns)
        rows=source.execute('SELECT '+projection+' FROM "'+name+'"').fetchall()
        for row in rows:
            for column,value in zip(columns,row):
                if column.endswith('_json') and value:
                    inspect(json.loads(value))
            target.execute('INSERT INTO "'+name+'" VALUES ('+','.join('?' for _ in row)+')',tuple(row))
        counts[name]=len(rows)
    for sql, in source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY rowid"):
        target.execute(sql)
    target.commit()
    return counts

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist')
    parser.add_argument('--metadata-only', action='store_true')
    parser.add_argument('--explore', action='store_true')
    args = parser.parse_args()
    dist = Path(args.dist).resolve(strict=True) if args.dist else None
    assert args.metadata_only or (dist is not None and (dist / 'index.html').is_file())
    if dist: assert dist.is_relative_to(WORK) or dist.is_relative_to(SCRATCH) or dist.is_relative_to(Path(os.environ.get('TEMP', r'C:\Users\james\AppData\Local\Temp')))
    run = SCRATCH / ('browser-acceptance-' + uuid.uuid4().hex[:12])
    run.mkdir()
    print(json.dumps({'runRoot':str(run),'phase':'preparing isolated metadata'}),flush=True)
    sys.path.insert(0, str(WORK))
    from scripts.run_security_tests import isolated_environment
    env = isolated_environment(run)
    env.update({
        'ATLAS_AUTH_ENABLED':'1', 'ATLAS_ENABLE_DEV_USER_HEADER':'0', 'ATLAS_COOKIE_SECURE':'0',
        'ASP_MODEL_STUDIO_RUNTIME_ROOT':str(run / 'runtime'), 'ASP_REQUIRE_ISOLATED_RUNTIME':'1',
        'ASP_MLB_PLAYER_PRIOR_V2_ROOT':str(run / 'runtime' / 'stage3-player-prior-authorities-v2'),
        'ATLAS_STAGE3_MODEL_LAB_ROOT':str(run / 'runtime' / 'stage3-model-laboratory'),
        'ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT':str(run / 'runtime' / 'stage3-executable-artifacts'),
    })
    os.environ.clear()
    os.environ.update(env)
    copied = []
    source = sqlite3.connect(SOURCE_DB.as_uri()+'?mode=ro', uri=True)
    source.execute('PRAGMA query_only=ON')
    source_stage3 = stage3_snapshot(source)
    target = sqlite3.connect(env['ATLAS_SQLITE_PATH'])
    cloned_tables=clone_allowlisted_metadata(source,target)
    assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert stage3_snapshot(target) == source_stage3
    source.close()
    target.close()
    library=Path(env['ATLAS_DATASET_LIBRARY_ROOT'])
    for name,value in (('registry.json',{'datasets':[]}),('project_links.json',{'links':[]}),('users.json',{'users':[]})):
        (library/name).write_text(json.dumps(value),encoding='utf-8')
    for namespace, files in (
        ('stage3-player-prior-authorities-v2', sorted((PRIMARY_RUNTIME/'stage3-player-prior-authorities-v2').rglob('*.json'))),
        ('stage3-model-laboratory', sorted((PRIMARY_RUNTIME/'stage3-model-laboratory'/'objects'/'sha256').glob('*.json'))),
    ):
        original_root = PRIMARY_RUNTIME / namespace
        for item in files:
            assert not item.is_symlink()
            assert item.resolve().is_relative_to(original_root.resolve())
            raw = item.read_bytes()
            value = json.loads(raw)
            content = sha(canonical(value))
            if item.name == 'manifest.json': assert content == item.parent.name
            elif item.name != 'current.json': assert content == item.stem
            destination = run / 'runtime' / namespace / item.relative_to(original_root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            assert sha(destination.read_bytes()) == sha(raw)
            copied.append({'relativePath':str(destination.relative_to(run)), 'bytes':len(raw), 'sha256':sha(raw)})
    assert len(copied) == 15
    violations = []
    violation_context=[]
    blocked_platform_probes = []
    writes = []
    requests = []
    controller_thread = threading.get_ident()
    subprocess_allowed = False
    owned_port = None
    owned_sockets=[]
    forbidden_extensions = {'.parquet','.pq','.arrow','.feather','.pkl','.pickle','.joblib','.npy','.npz','.onnx','.h5','.hdf5','.csv','.xlsx'}
    def reject(kind):
        violations.append(kind)
        violation_context.append({'kind':kind,'frames':[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name} for frame in traceback.extract_stack()[-9:-1]]})
        raise RuntimeError('Disposable browser boundary rejected '+kind)
    def audit(event, details):
        if event == 'open' and not isinstance(details[0], int):
            p = Path(os.fsdecode(details[0])).resolve()
            if 'ai-sports-predictor' in str(p).lower(): reject('excluded_repository_read')
            if p.is_relative_to(PRIMARY_RUNTIME): reject('operational_runtime_read')
            if p.suffix.lower() in forbidden_extensions: reject('row_or_model_file_open')
            mode = str(details[1] or '')
            flags = int(details[2] or 0)
            if any(letter in mode for letter in 'wax+') or flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC):
                if not p.is_relative_to(run): reject('write_outside_disposable_root')
                writes.append(str(p.relative_to(run)))
        if event == 'sqlite3.connect':
            if str(details[0]) == ':memory:': return
            value=str(details[0])
            if value.startswith('file:'):
                value=unquote(urlsplit(value).path)
                if re.match(r'^/[A-Za-z]:/',value): value=value[1:]
            p = Path(value).resolve()
            if not p.is_relative_to(run): reject('database_outside_disposable_root')
        if event in ('os.mkdir','os.remove','os.rmdir','os.rename','os.replace','os.link','os.symlink'):
            paths = details[:2] if event in ('os.rename','os.replace','os.link','os.symlink') else details[:1]
            for value in paths:
                if isinstance(value, (str,bytes)) and not Path(os.fsdecode(value)).resolve().is_relative_to(run): reject('filesystem_mutation_outside_disposable_root')
        if event == 'socket.connect':
            address = details[1]
            ports={owned_port}
            for owned_socket in owned_sockets:
                try:
                    if owned_socket.fileno()!=-1: ports.add(owned_socket.getsockname()[1])
                except OSError: pass
            if not isinstance(address, tuple) or address[0] not in ('127.0.0.1','::1') or address[1] not in ports: reject('non_owned_network_connect')
        if event == 'socket.bind':
            address = details[1]
            if not isinstance(address, tuple) or address[0] != '127.0.0.1' or address[1] != 0: reject('non_ephemeral_loopback_bind')
            owned_sockets.append(details[0])
        if event in ('subprocess.Popen','os.system'):
            if event=='subprocess.Popen' and (str(details[0])=='lscpu' or str(details[1])=='lscpu'):
                blocked_platform_probes.append('numpy_optional_lscpu_probe')
                raise FileNotFoundError('Optional platform probe intentionally unavailable')
            if not subprocess_allowed or threading.get_ident() != controller_thread or event != 'subprocess.Popen' or not str(details[1]).startswith('"'+str(NODE)+'"'): reject('application_subprocess')
    sys.addaudithook(audit)
    logging.disable(logging.CRITICAL)
    import platform
    win=sys.getwindowsversion()
    platform._uname_cache=platform.uname_result('Windows','disposable-acceptance',str(win.major),f'{win.major}.{win.minor}.{win.build}','AMD64')
    platform._syscmd_ver=lambda *args,**kwargs: ('Windows',str(win.major),f'{win.major}.{win.minor}.{win.build}')
    import pandas as pd
    import pyarrow.parquet as parquet
    import pyarrow.dataset as arrow_dataset
    import numpy as np
    def row_reader_forbidden(*args,**kwargs): reject('row_or_model_reader_called')
    for module,names in ((pd,('read_parquet','read_csv','read_excel','read_feather','read_pickle')),(parquet,('ParquetFile','read_table','read_pandas')),(arrow_dataset,('dataset',)),(np,('load','loadtxt','genfromtxt'))):
        for name in names: setattr(module,name,row_reader_forbidden)
    from server.security.security_store import init_security_store, create_user
    from server.persistence import get_persistence_service
    init_security_store()
    service = get_persistence_service()
    users = {}
    for label, role in (('admin','admin'),('alpha','data_scientist'),('beta','data_scientist')):
        password = secrets.token_urlsafe(32)+'aA9!'
        email = label+'@disposable.invalid'
        user = create_user(email=email, display_name='Disposable '+label.title(), password=password, role=role, user_id='browser-'+label)
        service.sync_user(user)
        users[label] = {'email':email, 'password':password, 'userId':user['userId']}
    from server.sharing.sharing_service import SharingService
    sharing = SharingService(service)
    admin = {'userId':'browser-admin','role':'admin'}
    for project, label in (('asp-mtlozhdx','alpha'),('asp-mtddc6pw','beta')):
        sharing.share_resource(admin,'project',project,{'principalType':'user','principalId':'browser-'+label,'permissionLevel':'edit'})
        service.projects.upsert_workflow_state(project,{'current_step_id':'mlb-03','completed_steps_json':[],'workflow_status_json':{'fixtureScope':'empty presentation history; science metadata remains exact'},'step_evidence_status_json':{}})
    from server.main import create_app
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
    from server.sports_current_statcast import stage3_model_jobs,stage3_executable_artifact
    jobs_before={'modelCoordinatorFutures':len(stage3_model_jobs._COORDINATOR_FUTURES),'executableFutures':len(stage3_executable_artifact._FUTURES),'runtimeFiles':sorted(str(item.relative_to(run/'runtime')) for item in (run/'runtime').rglob('*') if item.is_file())}
    with service.database.connection() as check:
        metadata_before=metadata_snapshot(check,sorted(set(cloned_tables)|{'workflow_state'}))
        source_users_before=sha(canonical(sorted([list(row) for row in check.execute("SELECT * FROM users WHERE user_id NOT IN ('browser-admin','browser-alpha','browser-beta')")],key=repr)))
    from server.sports_current_statcast.stage3_model_laboratory import persisted_project_workflow_state
    probe=[]
    for project_id in ('asp-mtlozhdx','asp-mtddc6pw'):
        value=persisted_project_workflow_state(service.database,project_id,**({'include_registered_history':True} if project_id=='asp-mtddc6pw' else {}))
        probe.append({'projectId':project_id,'treatmentStatus':value['treatment']['status'],'developmentRows':value['population']['developmentRows'],'historicalRuns':len(value.get('historicalEvidence',{}).get('runs',[])),'priorStatus':value.get('priorAuthority',{}).get('status')})
    (run/'metadata-probe.json').write_text(json.dumps(probe,indent=2),encoding='utf-8')
    from server.sports_datasets.registry import SportsDatasetRegistry
    catalog=SportsDatasetRegistry(service.database)
    catalog_probe=[]
    for registration in catalog.list_valid():
        try:
            catalog.public_dataset(registration)
            catalog_probe.append({'registrationId':registration['registration_id'],'publicView':'ok'})
        except Exception as error:
            catalog_probe.append({'registrationId':registration['registration_id'],'exceptionType':type(error).__name__,'frames':[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name} for frame in traceback.extract_tb(error.__traceback__)]})
    (run/'catalog-probe.json').write_text(json.dumps(catalog_probe,indent=2),encoding='utf-8')
    if args.metadata_only:
        print(json.dumps({'metadataProbe':probe,'catalogProbe':catalog_probe,'guardViolations':violations,'blockedOptionalPlatformProbes':blocked_platform_probes,'clonedTableCount':len(cloned_tables)}),flush=True)
        return 0
    app = create_app()
    @app.middleware('http')
    async def readonly_browser_http(request, call_next):
        path = request.url.path
        requests.append({'method':request.method,'path':path})
        metadata_autosave=request.method=='PUT' and path in ('/api/projects/asp-mtlozhdx','/api/projects/asp-mtddc6pw','/api/projects/asp-mtlozhdx/workflow-state','/api/projects/asp-mtddc6pw/workflow-state')
        if request.method not in ('GET','HEAD','OPTIONS') and path not in ('/api/auth/login','/api/auth/logout') and not metadata_autosave:
            return JSONResponse({'ok':False,'detail':'Disposable acceptance permits read-only application navigation.'},status_code=409)
        return await call_next(request)
    app.mount('/assets', StaticFiles(directory=str(dist/'assets')), name='acceptance-assets')
    @app.get('/{frontend_path:path}')
    async def frontend(frontend_path: str):
        if frontend_path.startswith('api/'):
            return JSONResponse({'detail':'Not Found'},status_code=404)
        candidate=(dist/frontend_path).resolve()
        if candidate.is_relative_to(dist) and candidate.is_file(): return FileResponse(candidate)
        return FileResponse(dist/'index.html')
    listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    listener.bind(('127.0.0.1',0))
    owned_port=listener.getsockname()[1]
    listener.listen(128)
    config=uvicorn.Config(app,host='127.0.0.1',port=owned_port,log_config=None,access_log=False,lifespan='off',loop='asyncio')
    server=uvicorn.Server(config)
    thread=threading.Thread(target=lambda:server.run(sockets=[listener]),daemon=True)
    thread.start()
    for _ in range(400):
        if server.started: break
        time.sleep(.05)
    assert server.started
    build_files={str(path.relative_to(dist)):sha(path.read_bytes()) for path in sorted(dist.rglob('*')) if path.is_file() and path.suffix.lower() in {'.html','.js','.css','.svg','.png','.jpg','.jpeg','.webp','.woff','.woff2'}}
    (run/'setup.json').write_text(json.dumps({'metadataCloneIntegrity':'ok','clonedAllowlistedTables':cloned_tables,'allOtherTables':'schema only; no source records copied','presentationFixtures':'empty Dataset Library catalog and empty workflow history; no data files copied','sourceStage3MetadataPreservedInClone':True,'copiedJsonFiles':copied,'frontendBuildFileHashes':build_files,'frontendBuildFingerprint':sha(canonical(build_files)),'lifespan':'off','startupScanner':'intentionally not invoked','origin':f'http://127.0.0.1:{owned_port}'},indent=2),encoding='utf-8')
    print(json.dumps({'ready':True,'runRoot':str(run),'port':owned_port}),flush=True)
    subprocess_allowed=True
    child=subprocess.Popen([str(NODE),str(SCRATCH/'repair_browser_acceptance.mjs')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=str(WORK),env={**os.environ,'LOCALAPPDATA':r'C:\Users\james\AppData\Local'},creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    subprocess_allowed=False
    try:
        stdout,stderr=child.communicate(json.dumps({'origin':f'http://127.0.0.1:{owned_port}','runRoot':str(run),'work':str(WORK),'users':users,'explore':args.explore}),timeout=900)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=15)
        server.should_exit=True
        thread.join(timeout=20)
        listener.close()
    with service.database.connection() as check:
        preserved=stage3_snapshot(check)==source_stage3
        metadata_after=metadata_snapshot(check,sorted(set(cloned_tables)|{'workflow_state'}))
        source_users_after=sha(canonical(sorted([list(row) for row in check.execute("SELECT * FROM users WHERE user_id NOT IN ('browser-admin','browser-alpha','browser-beta')")],key=repr)))
    json_preserved=all(sha((run/item['relativePath']).read_bytes())==item['sha256'] for item in copied)
    jobs_after={'modelCoordinatorFutures':len(stage3_model_jobs._COORDINATOR_FUTURES),'executableFutures':len(stage3_executable_artifact._FUTURES),'runtimeFiles':sorted(str(item.relative_to(run/'runtime')) for item in (run/'runtime').rglob('*') if item.is_file())}
    receipt={'browserExitCode':child.returncode,'stage3MetadataUnchanged':preserved,'copiedAuthorityAndRunJsonUnchanged':json_preserved,'guardViolations':violations,'guardViolationContext':violation_context,'blockedOptionalPlatformProbes':blocked_platform_probes,'applicationRequests':requests,'scratchWritePaths':sorted(set(writes)),'browserStdout':stdout[-1500:],'browserStderrPresent':bool(stderr),'ownedServerStopped':not thread.is_alive()}
    receipt.update({'jobsBefore':jobs_before,'jobsAfter':jobs_after,'jobsAndRuntimeStateUnchanged':jobs_before==jobs_after})
    changed_metadata=[name for name in metadata_before if metadata_before[name]!=metadata_after[name]]
    receipt.update({'metadataTableHashesBefore':metadata_before,'metadataTableHashesAfter':metadata_after,'changedMetadataTables':changed_metadata,'clonedSourceUserRowsUnchanged':source_users_before==source_users_after,'onlyPresentationAndSyntheticIdentityMetadataChanged':set(changed_metadata).issubset({'projects','workflow_state','users'}) and source_users_before==source_users_after})
    receipt['disposableProjectMetadataAutosaves']=sum(item['method']=='PUT' and item['path'] in ('/api/projects/asp-mtlozhdx','/api/projects/asp-mtddc6pw') for item in requests)
    receipt['disposableWorkflowMetadataAutosaves']=sum(item['method']=='PUT' and item['path'] in ('/api/projects/asp-mtlozhdx/workflow-state','/api/projects/asp-mtddc6pw/workflow-state') for item in requests)
    if stderr:
        safe_stderr=stderr
        for value in [env['ATLAS_SESSION_SECRET'],*[item['password'] for item in users.values()]]:
            safe_stderr=safe_stderr.replace(value,'[redacted synthetic credential]')
        receipt['browserErrorPrefix']=safe_stderr[:650]
    (run/'guard-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps({'runRoot':str(run),'browserExitCode':child.returncode,'stage3MetadataUnchanged':preserved,'guardViolations':violations,'browserStdout':stdout[-1500:],'browserStderrPresent':bool(stderr),'browserErrorPrefix':receipt.get('browserErrorPrefix')}),flush=True)
    return child.returncode

if __name__=='__main__':
    try: raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'harnessFailed':True,'exceptionType':type(error).__name__,'frames':[{'file':Path(frame.filename).name,'line':frame.lineno,'function':frame.name} for frame in traceback.extract_tb(error.__traceback__)]}),flush=True)
        raise SystemExit(1)
