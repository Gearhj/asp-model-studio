"""Offline bounded CFB owner; accepts only hash-bound locally captured versions."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.publication_io import reference,verified_bytes,canonical_bytes
from server.sports_cfb_gen1.lifecycle import read_ref,now,object_json,immutable
from server.sports_cfb_gen1.owner import invoke


def main():
    p=argparse.ArgumentParser()
    for name in ('release','release-sha256','input-pointer','state-root','exchange-root','result-file'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--capture-pointer')
    a=p.parse_args()
    try:
        ref=reference(a.release)
        if ref['sha256']!=a.release_sha256:raise ValueError('Release physical hash mismatch')
        release=read_ref(ref);manifest=read_ref(release['deploymentManifest'])
        for member in manifest['members']:
            verified_bytes(dict(member,path=str(Path(release['deploymentManifest']['path']).parent/member['relativePath'])))
        value,bound=invoke(release_ref=ref,input_pointer=a.input_pointer,state_root=a.state_root,
            exchange_root=a.exchange_root,capture_pointer=a.capture_pointer)
    except Exception as exc:
        value={'schema':'CFB_GEN1_OWNER_FAILURE_V1','createdAtUtc':now(),'disposition':'FAILED_CLOSED',
            'reason':str(exc),'exitCode':1,'providerCalls':0,'providerBytes':0,'costUsd':0,'aispWrites':0}
        bound=object_json(Path(a.state_root)/'runner-receipts',value)
    result={'disposition':value['disposition'],'exitCode':value['exitCode'],'receipt':bound,'providerCalls':0,'providerBytes':0}
    immutable(Path(a.result_file),canonical_bytes(result));print(json.dumps(result));return value['exitCode']


if __name__=='__main__':sys.exit(main())
