"""Verify the dated private publication against GitHub and an independent clone.

Read-only except for a local verification receipt. No model loads or checkout.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime/github-publication-20260916-v1'
CLONE=OUT/'fresh-clone'

def git(*args, cwd=ROOT, data=None, check=True):
    p=subprocess.run(['git',*args],cwd=cwd,input=data,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if check and p.returncode: raise RuntimeError(p.stderr.decode('utf-8','replace')[:1000])
    return p

def tree(commit, cwd):
    result={}
    for raw in git('ls-tree','-r','-z',commit,cwd=cwd).stdout.split(b'\0'):
        if not raw:continue
        meta,path=raw.split(b'\t',1);mode,kind,oid=meta.decode().split()
        if kind=='blob':result[path.decode()]={'mode':mode,'oid':oid}
    return result

def main():
    plan=json.loads((OUT/'branch-publication-plan.json').read_bytes())
    checkpoints=json.loads((OUT/'source-checkpoint-receipt.json').read_bytes())
    expected={x['ref']:x['sha'] for x in plan if x['action']!='WITHHOLD'}
    expected.update({x['ref']:x['sha'] for x in checkpoints})
    final_path=OUT/'final-documentation-commit.json'
    if final_path.exists():
        final=json.loads(final_path.read_bytes());expected[final['ref']]=final['sha']
    raw=git('ls-remote','--heads','--tags','origin').stdout.decode()
    remote={line.split()[1]:line.split()[0] for line in raw.splitlines()}
    assert remote==expected, 'Remote refs differ from the explicit publication plan'
    clone_refs={}
    for ref,oid in expected.items():
        local_ref=ref.replace('refs/heads/','refs/remotes/origin/',1)
        got=git('rev-parse',local_ref,cwd=CLONE).stdout.decode().strip()
        assert got==oid,(ref,got,oid)
        clone_refs[ref]=got
    assert not git('for-each-ref','--format=%(objectname)','refs/tags',cwd=CLONE).stdout.strip()
    assert not (CLONE/'.git/objects/info/alternates').exists()
    assert not (CLONE/'.git/shallow').exists()
    assert git('remote','get-url','origin',cwd=CLONE).stdout.decode().strip()=='https://github.com/Gearhj/asp-model-studio.git'
    assert not git('config','--get','remote.origin.promisor',cwd=CLONE,check=False).stdout.strip()
    fsck=git('fsck','--connectivity-only','--no-reflogs',cwd=CLONE)
    source=[]
    for item in checkpoints:
        oid=expected[item['ref']]
        manifest=json.loads(git('show',oid+':SOURCE_SNAPSHOT.json',cwd=CLONE).stdout)
        actual=tree(oid,CLONE);actual.pop('SOURCE_SNAPSHOT.json')
        assert actual==manifest['files'],item['ref']
        assert not manifest['originalHistoryIncluded'] and not manifest['deploymentAuthority']
        source.append({'ref':item['ref'],'sha':oid,'filesVerified':len(actual)})
    deploy=checkpoints[1]
    manifest=json.loads((ROOT/'.deployments/mlb-v18-unattended/77d39e1ae08e05be82e19bdb0bab21999fba1d3b/deployment-build.json').read_bytes())
    deployed_tree=tree(deploy['sha'],CLONE)
    process=subprocess.Popen(['git','cat-file','--batch'],cwd=CLONE,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        for file in manifest['files']:
            oid=deployed_tree[file['path']]['oid']
            process.stdin.write((oid+'\n').encode());process.stdin.flush()
            head=process.stdout.readline().split();size=int(head[2]);body=process.stdout.read(size)
            assert process.stdout.read(1)==b'\n'
            assert size==file['bytes'] and hashlib.sha256(body).hexdigest()==file['sha256'],file['path']
    finally:
        process.stdin.close();process.stdout.close();process.wait()
    unavailable={}
    for oid in ('0c786297534c1ffc9892fbcd199d7d7af5ec8bae','77d39e1ae08e05be82e19bdb0bab21999fba1d3b'):
        unavailable[oid]=git('cat-file','-e',oid+'^{commit}',cwd=CLONE,check=False).returncode!=0
    assert all(unavailable.values()),'Unexpected original history: investigate before claiming scope'
    checks={}
    for path,prior in json.loads((OUT/'preexisting-working-files.json').read_bytes()).items():
        checks[path]={'originalSha256':prior['sha256'],'currentSha256':hashlib.sha256((ROOT/path).read_bytes()).hexdigest()}
    assert checks['server/sports_current_statcast/mlb_v18_prospective_transform.py']['currentSha256']==checks['server/sports_current_statcast/mlb_v18_prospective_transform.py']['originalSha256']
    assert git('rev-parse','HEAD').stdout.decode().strip()=='0c786297534c1ffc9892fbcd199d7d7af5ec8bae'
    assert hashlib.sha256((ROOT/'.git/index').read_bytes()).hexdigest()==(OUT/'original-index.sha256').read_text().strip()
    value={'verifiedAt':datetime.now(timezone.utc).isoformat(),'repository':'https://github.com/Gearhj/asp-model-studio',
           'expectedRemoteRefs':expected,'remoteRefsExact':True,'freshCloneRefsExact':True,'refCount':len(expected),'tags':0,
           'clone':str(CLONE),'cloneIndependent':True,'cloneShallow':False,'cloneFiltered':False,'checkoutPerformed':False,
           'connectivityExitCode':fsck.returncode,'sourceSnapshotChecks':source,'deployedSourceSha256Checks':len(manifest['files']),
           'originalCommitsUnavailableInClone':unavailable,'preexistingWorkingFileHashes':checks,'realIndexAndHeadUnchanged':True,
           'qualification':'Source checkpoints do not preserve omitted original ancestry or model/runtime artifacts. An independent existing owner advanced the NFL CURRENT pointer; this task did not restore or write it.'}
    (OUT/'fresh-clone-verification.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:value[k] for k in ('verifiedAt','refCount','tags','remoteRefsExact','freshCloneRefsExact','connectivityExitCode','deployedSourceSha256Checks','originalCommitsUnavailableInClone','realIndexAndHeadUnchanged')}))

if __name__=='__main__':main()
