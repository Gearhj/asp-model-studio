"""Physical-byte bindings; no provider or consumer access."""
import hashlib
import json
from pathlib import Path


def canonical_bytes(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(value if isinstance(value,bytes) else canonical_bytes(value)).hexdigest()


def reference(path):
    p=Path(path).resolve()
    raw=p.read_bytes()
    return {'path':str(p),'sha256':digest(raw),'bytes':len(raw)}


def verified_bytes(ref):
    raw=Path(ref['path']).read_bytes()
    if len(raw)!=ref['bytes'] or digest(raw)!=ref.get('sha256',ref.get('physicalSha256')):
        raise ValueError('Physical binding mismatch: '+str(ref['path']))
    return raw
