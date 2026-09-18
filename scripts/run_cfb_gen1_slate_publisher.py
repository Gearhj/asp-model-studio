"""Bounded CFB owner; live refresh requires explicit flag and exact local grant."""
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
    p.add_argument('--enable-network',action='store_true');p.add_argument('--grant');p.add_argument('--grant-sha256')
    p.add_argument('--env-file',default=r'C:\Users\james\asp-model-studio\.env.local')
    a=p.parse_args()
    try:
        ref=reference(a.release)
        if ref['sha256']!=a.release_sha256:raise ValueError('Release physical hash mismatch')
        release=read_ref(ref);manifest=read_ref(release['deploymentManifest'])
        for member in manifest['members']:
            verified_bytes(dict(member,path=str(Path(release['deploymentManifest']['path']).parent/member['relativePath'])))
        grant=None
        if a.enable_network:
            from server.sports_cfb_gen1.capture import HttpTransport,validate_grant
            if not a.grant or not a.grant_sha256:raise PermissionError('Exact recurring grant required')
            grant=reference(a.grant)
            if grant['sha256']!=a.grant_sha256:raise PermissionError('Grant physical digest mismatch')
            validate_grant(release['refreshPlan'],grant,release['deploymentId'],True,now())
        value,bound=invoke(release_ref=ref,input_pointer=a.input_pointer,state_root=a.state_root,
            exchange_root=a.exchange_root,capture_pointer=a.capture_pointer,enable_network=a.enable_network,grant_ref=grant,
            transport_factory=(lambda:HttpTransport(a.env_file)) if a.enable_network else None)
    except Exception as exc:
        value={'schema':'CFB_GEN1_OWNER_FAILURE_V1','createdAtUtc':now(),'disposition':'FAILED_CLOSED',
            'reason':str(exc),'exitCode':1,'providerCalls':0,'providerBytes':0,'costUsd':0,'aispWrites':0}
        bound=object_json(Path(a.state_root)/'runner-receipts',value)
    result={'disposition':value['disposition'],'exitCode':value['exitCode'],'receipt':bound,
            'providerCalls':value['providerCalls'],'providerBytes':value['providerBytes']}
    immutable(Path(a.result_file),canonical_bytes(result));print(json.dumps(result));return value['exitCode']


if __name__=='__main__':sys.exit(main())
