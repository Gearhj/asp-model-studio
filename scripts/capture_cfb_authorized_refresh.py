"""Execute only the exact, once-authorized CFB refresh; dry-run by default."""
import argparse,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.capture import capture,HttpTransport,validate_grant,request_sequence
from server.sports_cfb_gen1.lifecycle import read_ref,now,atomic_json
from server.sports_cfb_gen1.publication_io import reference

def main():
    p=argparse.ArgumentParser()
    for key in ('plan','plan-sha256','grant','deployment','output','env-file'):p.add_argument('--'+key,required=True)
    p.add_argument('--execute',action='store_true');p.add_argument('--capture-pointer')
    a=p.parse_args();ref=reference(a.plan)
    if ref['sha256']!=a.plan_sha256:raise ValueError('Exact physical proposal hash mismatch')
    plan=read_ref(ref)
    if not a.execute:
        print(json.dumps({'disposition':'DRY_RUN_NO_NETWORK','requests':request_sequence(plan),'maxBytes':plan['maxResponseBytes']}));return 0
    grant=reference(a.grant);validate_grant(ref,grant,a.deployment,True,now())
    result=capture(plan_ref=ref,grant_ref=grant,deployment=a.deployment,root=a.output,enabled=True,
        transport_factory=lambda:HttpTransport(a.env_file),predecessor=plan['priorRecordedUsage']['manifest'])
    if result['disposition']=='CAPTURED' and a.capture_pointer:
        atomic_json(a.capture_pointer,{'schema':'CFB_CAPTURE_POINTER_V1','sourceManifest':result['sourceManifest'],
                                    'captureReceipt':reference(Path(a.output)/'completion.json')})
    print(json.dumps(result,indent=2));return 0 if result['disposition']=='CAPTURED' else 1

if __name__=='__main__':sys.exit(main())
