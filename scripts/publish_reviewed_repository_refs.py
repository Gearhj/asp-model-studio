"""Publish only the frozen reviewed ref plan; never force, merge or reset."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime/github-publication-20260916-v1'
plan=json.loads((OUT/'branch-publication-plan.json').read_text())
selected=[r for r in plan if r['action'].startswith('PUBLISH_')]
assert selected and all(not r['largeBlobCount'] and not r['restrictedSourceBlobCount'] for r in selected)
assert subprocess.check_output(['git','remote','get-url','origin'],cwd=ROOT,text=True).strip()=='https://github.com/Gearhj/asp-model-studio.git'
remote={line.split()[1]:line.split()[0] for line in subprocess.check_output(['git','-c','credential.interactive=never','ls-remote','--heads','--tags','origin'],cwd=ROOT,text=True).splitlines()}
for r in selected:
    assert subprocess.check_output(['git','rev-parse',r['ref']],cwd=ROOT,text=True).strip()==r['sha'],r['ref']
    actual=remote.get(r['remoteRef'])
    assert actual in {r['priorRemoteSha'],r['sha']},'Remote changed: '+r['remoteRef']
mode='publish' if '--publish' in sys.argv else 'dry-run'
command=['git','-c','credential.interactive=never','push','--atomic','--porcelain']
if mode=='dry-run':command+=['--dry-run']
command+=['origin']+[r['sha']+':'+r['remoteRef'] for r in selected]
r=subprocess.run(command,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
receipt={'createdAt':datetime.now(timezone.utc).isoformat(),'mode':mode,'refCount':len(selected),'refs':selected,'exitCode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'force':False,'atomic':True}
(OUT/(mode+'-receipt.json')).write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'mode':mode,'refCount':len(selected),'exitCode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}))
raise SystemExit(r.returncode)
