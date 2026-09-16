"""Dated, explicit source preservation; never changes the checkout or real index.

These new branches are source snapshots, NOT replacements for omitted original
history or deployments. Run prepare, review its manifest, then run --create.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone

from repository_publication_audit import PATTERNS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/github-publication-20260916-v1'
DEV = '0c786297534c1ffc9892fbcd199d7d7af5ec8bae'
DEPLOYED = '77d39e1ae08e05be82e19bdb0bab21999fba1d3b'
SAFE_PARENT = 'fe9fd790b4bb713256763b13fcd319044d35df27'
DOC = 'docs/repository-publication/2026-09-16'

def git(*args, data=None, env=None):
    r = subprocess.run(['git', *args], cwd=ROOT, input=data,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if r.returncode:
        raise RuntimeError(r.stderr.decode('utf-8', 'replace')[:1000])
    return r.stdout

def js(value):
    return (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def tree(commit):
    result = {}
    for raw in git('ls-tree', '-r', '-z', commit).split(b'\0'):
        if not raw: continue
        meta, path = raw.split(b'\t', 1)
        mode, kind, oid = meta.decode().split()
        if kind == 'blob': result[path.decode()] = {'mode': mode, 'oid': oid}
    return result

def source_path(path):
    p = Path(path); parts = p.parts; suffix = p.suffix.lower()
    if path in {'.env.modeling', '.env.scheduling', '.gitignore', '.gitattributes'}:
        return True
    if path == 'server/artifacts/governance/mlb-final-oot-quarantine-v1.json':
        return True  # Identity-only permanent policy; no outcome payload.
    if any(x in parts for x in ('node_modules', '__pycache__', 'data', 'artifacts', 'private-sources', 'prospective-only-source-quarantine')):
        return False
    text = {'.py','.ps1','.sh','.cmd','.bat','.js','.jsx','.mjs','.cjs','.ts','.tsx','.md','.toml','.yaml','.yml','.ini','.cfg','.html','.css','.sql'}
    if len(parts) == 1:
        return suffix in text or path in {'package.json','package-lock.json','tsconfig.json','requirements.txt','LICENSE'}
    if parts[0] in {'src','server','scripts','tests','tools','shared','.github','public'}:
        return suffix in text | {'.json','.svg','.txt'}
    return parts[0] in {'docs','outputs'} and suffix == '.md'

def findings(data, path, known):
    unknown = []
    for rule, rx in PATTERNS.items():
        for m in rx.finditer(data):
            value = m.group(1) if rule == 'literal_credential' else m.group()
            if rule == 'literal_credential':
                if re.fullmatch(rb'[a-fA-F0-9]{32,128}', value): continue
                if re.search(rb'(?i)(example|placeholder|dummy|fake|test|your[_ -]|redacted|changeme|os\.|process\.|settings\.|environ|api[_-]?key|access[_-]?token|secret[_-]?key|not[-_ ]a[-_ ]|\s|[{}<>])', value): continue
            digest = sha(value)
            if digest not in known:
                unknown.append({'path':path, 'rule':rule, 'valueSha256':digest})
    return unknown

def prepare():
    assert git('rev-parse','HEAD').decode().strip() == DEV
    original = tree(DEV)
    development = {p:dict(v, source='git') for p,v in original.items() if source_path(p)}
    build_path = ROOT / '.deployments/mlb-v18-unattended' / DEPLOYED / 'deployment-build.json'
    build = json.loads(build_path.read_bytes())
    deployment = {}
    for f in build['files']:
        p = f['path']; assert source_path(p), p
        physical = build_path.parent/p
        body = physical.read_bytes()
        assert len(body) == f['bytes'] and sha(body) == f['sha256'], p
        deployment[p] = {'mode':'100644', 'source':'file', 'file':str(physical), 'sha256':sha(body), 'bytes':len(body)}
    inventory = json.loads((OUT/'local-inventory.json').read_bytes())
    unfinished = {}
    for f in inventory['untracked']:
        p = f['path']
        if p.split('/')[0] in {'scripts','server','docs'} and source_path(p):
            unfinished[p] = {'mode':'100644','source':'file','file':str(ROOT/p)}
    p = 'server/sports_current_statcast/mlb_v18_prospective_transform.py'
    unfinished[p] = {'mode':'100644','source':'file','file':str(ROOT/p)}
    # Preserve the portable prior management handoff; not its generated app/cache.
    handoff = ROOT/'outputs/project-management-handoff-20260915-v1'
    for p in sorted(handoff.glob('*')):
        if p.is_file() and p.suffix.lower() in {'.md','.py'}:
            rel = p.relative_to(ROOT).as_posix()
            unfinished[rel] = {'mode':'100644','source':'file','file':str(p)}
    audit_paths = ['.gitignore','docs/REPOSITORY_WORKFLOW.md',
                   'scripts/repository_publication_audit.py',
                   'scripts/publish_reviewed_repository_refs.py',
                   'scripts/preserve_reviewed_source_checkpoints.py']
    audit_paths += [p.relative_to(ROOT).as_posix() for p in (ROOT/DOC).glob('*') if p.is_file()]
    audit = {p:{'mode':'100644','source':'file','file':str(ROOT/p)} for p in audit_paths}
    # Audit scripts belong in their own implementation/documentation commit.
    for p in audit: unfinished.pop(p, None)
    scan = json.loads((OUT/'secret-scan-expanded.json').read_bytes())
    known = {f['valueSha256'] for f in scan['findings']}
    scanned = set(scan['scannedOids'])
    unknown=[]; newly_scanned=0
    for group in (development,deployment,unfinished,audit):
        for p,v in group.items():
            if v['source']=='git':
                if v['oid'] in scanned: continue
                if p == 'server/artifacts/governance/mlb-final-oot-quarantine-v1.json': continue
                body = git('cat-file','blob',v['oid'])
            else:
                body=Path(v['file']).read_bytes()
                v.update(sha256=sha(body),bytes=len(body))
            newly_scanned += 1
            unknown.extend(findings(body,p,known))
    plan={'createdAt':datetime.now(timezone.utc).isoformat(),'originalDevelopment':DEV,
          'originalDeployment':DEPLOYED,'safeParent':SAFE_PARENT,
          'development':development,'deployment':deployment,
          'unfinished':unfinished,'audit':audit,
          'excludedDevelopmentPaths':[p for p in original if p not in development],
          'additionalScannedFiles':newly_scanned,'unresolvedSecretFindings':unknown,
          'notice':'Independent source snapshots. Original blocked ancestry is NOT included. No model or production authority.'}
    (OUT/'source-checkpoint-plan.json').write_bytes(js(plan))
    print(json.dumps({'counts':{k:len(plan[k]) for k in ('development','deployment','unfinished','audit','excludedDevelopmentPaths')},'additionalScannedFiles':newly_scanned,'unresolvedSecretFindings':unknown}))

def commit_snapshot(ref, entries, parent, message, manifest):
    existing = subprocess.run(['git','show-ref','--verify','--quiet',ref],cwd=ROOT)
    assert existing.returncode == 1, 'Ref already exists; no overwrite: '+ref
    env=dict(os.environ, GIT_INDEX_FILE=str(OUT/(ref.rsplit('/',1)[-1]+'.index')))
    git('read-tree','--empty',env=env)  # Only the dedicated alternate index.
    complete={}
    for p,v in entries.items():
        if v['source']=='file':
            body=Path(v['file']).read_bytes()
            assert sha(body)==v['sha256'] and len(body)==v['bytes'],p
            oid=git('hash-object','-w','--stdin',data=body).decode().strip()
        else: oid=v['oid']
        complete[p]={'mode':v['mode'],'oid':oid}
    manifest.update(files=complete, originalHistoryIncluded=False,
                    modelArtifactsIncluded=False, deploymentAuthority=False)
    body=js(manifest)
    oid=git('hash-object','-w','--stdin',data=body).decode().strip()
    complete['SOURCE_SNAPSHOT.json']={'mode':'100644','oid':oid}
    index_data=b''.join((v['mode']+' '+v['oid']+'\t'+p).encode()+b'\0' for p,v in sorted(complete.items()))
    git('update-index','-z','--index-info',data=index_data,env=env)
    tree_oid=git('write-tree',env=env).decode().strip()
    commit=git('commit-tree',tree_oid,'-p',parent,data=(message+'\n').encode()).decode().strip()
    git('update-ref',ref,commit,'0'*40)
    return {'ref':ref,'sha':commit,'parent':parent,'files':len(complete),'manifestSha256':sha(body)}

def create():
    plan=json.loads((OUT/'source-checkpoint-plan.json').read_bytes())
    assert not plan['unresolvedSecretFindings']
    index=ROOT/'.git/index'; original_index=index.read_bytes()
    assert sha(original_index)==(OUT/'original-index.sha256').read_text().strip()
    assert git('rev-parse','HEAD').decode().strip()==DEV
    result=[]
    result.append(commit_snapshot('refs/heads/codex/archive/development-source-0c786297',plan['development'],SAFE_PARENT,
        'archive: preserve reviewed development source from 0c786297 (not original history)',
        {'kind':'development-source-only','sourceCommit':DEV,'omittedPathCount':len(plan['excludedDevelopmentPaths'])}))
    result.append(commit_snapshot('refs/heads/codex/archive/mlb-owner-source-77d39e1a',plan['deployment'],SAFE_PARENT,
        'archive: preserve 872 verified deployed MLB owner source files (no activation)',
        {'kind':'deployed-code-only','sourceCommit':DEPLOYED,'deploymentBuildSha256':'0622b5395072283903669646ab993c80a3ebf3c01e4299132ce086fabca1d3ce'}))
    unfinished=dict(plan['development']);unfinished.update(plan['unfinished'])
    result.append(commit_snapshot('refs/heads/codex/checkpoint/unfinished-source-20260916',unfinished,result[0]['sha'],
        'checkpoint: preserve reviewed unfinished source and handoff; unvalidated, unpromoted',
        {'kind':'unfinished-source-checkpoint','originalDevelopment':DEV,'unfinishedPaths':list(plan['unfinished']),'validation':'not run; preservation only'}))
    audit=dict(unfinished);audit.update(plan['audit'])
    result.append(commit_snapshot('refs/heads/codex/repository-publication-20260916',audit,result[2]['sha'],
        'docs: record private publication review and scoped repository hygiene',
        {'kind':'repository-publication-documentation','originalDevelopment':DEV,'unfinishedSourceParent':result[2]['sha'],'cleanupPaths':list(plan['audit'])}))
    assert index.read_bytes()==original_index
    assert git('rev-parse','HEAD').decode().strip()==DEV
    (OUT/'source-checkpoint-receipt.json').write_bytes(js(result))
    print(json.dumps(result))

if __name__=='__main__':
    create() if '--create' in sys.argv else prepare()
