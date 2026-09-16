"""Read-only publication review. Never print secret values or open protected data.

Writes local audit metadata beneath .runtime; no git refs or files are altered.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime' / 'github-publication-20260916-v1'
OUT.mkdir(parents=True, exist_ok=True)

def git(*args, cwd=ROOT, data=None):
    r = subprocess.run(['git', *args], cwd=cwd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if r.returncode:
        raise RuntimeError(f'git {args[0]} failed: '+r.stderr.decode('utf-8', 'replace')[:1000])
    return r.stdout

def write(name, value):
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def protected(path):
    p=path.lower()
    return bool(re.search(r'(final[-_ ]?oot|sealed|holdout|quarantin|protected[-_ ]?(payload|outcome|set))',p))

TEXT_SUFFIX={'.py','.ps1','.sh','.cmd','.bat','.js','.jsx','.mjs','.cjs','.ts','.tsx','.md','.toml','.yaml','.yml','.ini','.cfg','.html','.css','.txt','.sql','.gitignore','.gitattributes'}
DATA_SUFFIX={'.parquet','.csv','.tsv','.jsonl','.ndjson','.npy','.npz','.pkl','.pickle','.joblib','.db','.sqlite','.sqlite3','.zip','.gz','.tgz','.bz2','.7z','.tar','.xlsx','.xls','.pdf','.png','.jpg','.jpeg','.ico','.woff','.woff2','.ttf','.bin','.onnx','.ubj','.feather','.arrow'}

def category(path):
    p=path.lower();s=Path(p).suffix
    if protected(path) and s not in TEXT_SUFFIX:return 'protected_payload_not_opened'
    if s in DATA_SUFFIX:return 'data_or_binary_metadata_only'
    if '/private-sources/' in p or p.startswith(('asp-data-staging/','.runtime/','.deployments/')):return 'private_runtime_metadata_only'
    if s=='.json':
        if p.startswith(('src/','scripts/','tests/','tools/')) or p in {'package.json','package-lock.json','tsconfig.json','tsconfig.app.json','tsconfig.node.json'}:return 'source_text'
        return 'evidence_json_metadata_only'
    if s in TEXT_SUFFIX or Path(p).name.startswith('.env') or p in {'.gitignore','.gitattributes','dockerfile','license'}:return 'source_text'
    return 'unknown_metadata_only'

def inventory():
    refs=[]
    for line in git('for-each-ref','--format=%(refname) %(objectname)').decode().splitlines():
        name,sha=line.split(' ',1);refs.append({'ref':name,'sha':sha})
    status=git('status','--porcelain=v1','-z','--untracked-files=no').decode('utf-8','replace').split('\0')
    untracked=[x for x in git('ls-files','--others','--exclude-standard','-z').decode('utf-8','replace').split('\0') if x]
    u=[]
    for path in untracked:
        try: st=(ROOT/path).stat();size=st.st_size;error=None
        except OSError as ex:size=None;error=type(ex).__name__
        u.append({'path':path,'bytes':size,'category':category(path),'statError':error})
    worktrees=[]
    for block in git('worktree','list','--porcelain').decode('utf-8','replace').strip().split('\n\n'):
        fields=dict(line.split(' ',1) if ' ' in line else (line,True) for line in block.splitlines())
        path=fields['worktree']
        try:
            fields['trackedStatus']=git('status','--porcelain=v1','--untracked-files=no',cwd=path).decode('utf-8','replace').splitlines()
            fields['untrackedPaths']=[x for x in git('ls-files','--others','--exclude-standard','-z',cwd=path).decode('utf-8','replace').split('\0') if x]
        except (OSError,RuntimeError) as ex:fields['inspectionError']=str(ex)
        worktrees.append(fields)
    result={'createdAt':datetime.now(timezone.utc).isoformat(),'head':git('rev-parse','HEAD').decode().strip(),'branch':git('branch','--show-current').decode().strip(),'refs':refs,'trackedStatus':[x for x in status if x],'untracked':u,'worktrees':worktrees,'stash':git('stash','list','--format=%gd %H %s').decode().splitlines(),'remotes':git('remote','-v').decode().splitlines()}
    write('local-inventory.json',result)
    objects={}
    for line in git('rev-list','--objects','--all').decode('utf-8','replace').splitlines():
        oid,_,path=line.partition(' ');objects[oid]={'oid':oid,'path':path}
    batch=''.join(oid+'\n' for oid in objects).encode()
    for line in git('cat-file','--batch-check=%(objectname) %(objecttype) %(objectsize)',data=batch).decode().splitlines():
        oid,kind,size=line.split();objects[oid].update(type=kind,bytes=int(size))
    remote_oids=set(line.split(' ',1)[0] for line in git('rev-list','--objects','--remotes=origin').decode().splitlines())
    blobs=[]
    for obj in objects.values():
        if obj['type']!='blob':continue
        obj['category']=category(obj['path']);obj['alreadyOnRemote']=obj['oid'] in remote_oids;blobs.append(obj)
    write('reachable-objects.json',list(objects.values()))
    write('blob-inventory.json',blobs)
    summary={'localBranches':sum(x['ref'].startswith('refs/heads/') for x in refs),'tags':sum(x['ref'].startswith('refs/tags/') for x in refs),'stashes':len(result['stash']),'worktrees':len(worktrees),'trackedChanges':len(result['trackedStatus']),'untrackedFiles':len(u),'untrackedBytes':sum(x['bytes'] or 0 for x in u),'untrackedCategories':dict(Counter(x['category'] for x in u)),'reachableObjects':len(objects),'blobCount':len(blobs),'blobBytes':sum(x['bytes'] for x in blobs),'blobCategories':dict(Counter(x['category'] for x in blobs)),'newBlobs':sum(not x['alreadyOnRemote'] for x in blobs),'newOver100MiB':[x for x in blobs if not x['alreadyOnRemote'] and x['bytes']>100*1024*1024],'largestNewBlobs':sorted([x for x in blobs if not x['alreadyOnRemote']],key=lambda x:-x['bytes'])[:25]}
    write('inventory-summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))

PATTERNS = {
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----'),
    'github_token': re.compile(rb'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'aws_access_id': re.compile(rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'provider_key': re.compile(rb'\b(?:sk-proj-[A-Za-z0-9_-]{30,}|sk-ant-[A-Za-z0-9_-]{30,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[0-9A-Za-z_-]{30,})\b'),
    'literal_credential': re.compile(rb'''(?i)(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password|passwd|secret[_-]?key)\s*["']?\s*[:=]\s*["']([^"'\r\n]{12,180})["']'''),
    'url_userinfo': re.compile(rb'https?://[^\s/@:]+:[^\s/@]{5,}@'),
}

def secret_scan(include_safe_evidence=False):
    blobs=json.loads((OUT/'blob-inventory.json').read_text(encoding='utf-8'))
    findings=[];scanned=[];skipped=[]
    eligible=None
    if include_safe_evidence:
        matrix=json.loads((OUT/'branch-risk-matrix.json').read_text())
        refs=[x['sha'] for x in matrix if not x['largeBlobCount'] and not x['restrictedSourceBlobCount']]
        eligible={x.split(' ',1)[0] for x in git('rev-list','--objects',*refs).decode().splitlines()}
    process=subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
    try:
        for obj in blobs:
            path=obj['path'];cat=obj['category']
            # Opaque data, archives and potentially protected payloads are never decoded.
            supplemental_text=Path(path).suffix.lower() in {'.xml','.svg','.patch','.rmd','.lock','.webmanifest','.sha256'}
            text_ok=cat=='source_text' or (include_safe_evidence and (cat=='evidence_json_metadata_only' or supplemental_text) and obj['oid'] in eligible)
            if not text_ok or obj['bytes']>16*1024*1024:
                skipped.append({'oid':obj['oid'],'path':path,'reason':cat});continue
            process.stdin.write((obj['oid']+'\n').encode());process.stdin.flush()
            header=process.stdout.readline().split();size=int(header[2]);body=process.stdout.read(size);assert process.stdout.read(1)==b'\n'
            scanned.append(obj['oid'])
            for rule,rx in PATTERNS.items():
                for m in rx.finditer(body):
                    value=m.group(1) if rule=='literal_credential' else m.group()
                    # Suppress obvious code/config expressions, fixture markers and hashes.
                    if rule=='literal_credential':
                        if re.fullmatch(rb'[a-fA-F0-9]{32,128}',value):continue
                        if re.search(rb'(?i)(example|placeholder|dummy|fake|test|your[_ -]|redacted|changeme|os\.|process\.|settings\.|environ|api[_-]?key|access[_-]?token|secret[_-]?key|not[-_ ]a[-_ ]|\s|[{}<>])',value):continue
                    findings.append({'oid':obj['oid'],'path':path,'rule':rule,'line':body[:m.start()].count(b'\n')+1,'valueSha256':hashlib.sha256(value).hexdigest(),'valueLength':len(value),'alreadyOnRemote':obj['alreadyOnRemote']})
    finally:
        process.stdin.close();process.stdout.close();process.wait()
    # Commit/tag messages are source-control metadata, not outcome payloads.
    messages=git('log','--all','--format=%H%n%B%x00')
    for block in messages.split(b'\0'):
        oid=block.strip().split(b'\n',1)[0].decode('ascii','replace')
        for rule,rx in PATTERNS.items():
            if rule=='literal_credential':continue
            for m in rx.finditer(block):findings.append({'oid':oid,'path':'<commit-message>','rule':rule,'line':None,'valueSha256':hashlib.sha256(m.group()).hexdigest(),'valueLength':len(m.group()),'alreadyOnRemote':None})
    write('secret-scan-expanded.json' if include_safe_evidence else 'secret-scan.json',{'scope':'All reachable source-text blobs and commit messages, including already-published ancestry; optional non-protected JSON on preliminarily publishable branches. Metadata-only exclusion for opaque data/binary/protected blobs is explicit; not a clean bill for those files.','scannedBlobCount':len(scanned),'scannedOids':scanned,'findings':findings,'skipped':skipped})
    print(json.dumps({'scannedBlobCount':len(scanned),'findingsCount':len(findings),'findingRules':dict(Counter(x['rule'] for x in findings)),'skippedCount':len(skipped)}))

if __name__=='__main__':
    import sys
    if '--scan' in sys.argv:secret_scan('--safe-evidence' in sys.argv)
    else:inventory()
