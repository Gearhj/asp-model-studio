"""Verify staged bytes and preserved baseline without inference, network or installation."""
import argparse,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.publication_io import reference,verified_bytes
from server.sports_cfb_gen1.lifecycle import read_ref
from server.sports_cfb_gen1.inputs import validate_bundle


def main():
    p=argparse.ArgumentParser();p.add_argument('--receipt',required=True);a=p.parse_args()
    r=read_ref(reference(a.receipt));release=read_ref(r['release']);manifest=read_ref(r['deploymentManifest'])
    for m in manifest['members']:
        verified_bytes(dict(m,path=str(Path(r['deploymentManifest']['path']).parent/m['relativePath'])))
    prep=read_ref(r['preparation'])
    for ref in prep['preservedObjects']:verified_bytes(ref)
    validate_bundle(read_ref(r['inputVersion']),release)
    assert release['configurationIdentity']=='CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1'
    assert release['networkCapability'] is False and r['installed'] is False
    assert release['policy']['checkpointsMinutesBeforeKickoff']==[10080,1440,360,60]
    assert release['policy']['lastPublicationMinutesBeforeKickoff']==30
    print(json.dumps({'status':'STAGED_BYTES_AND_BASELINE_PRESERVED','deployment':r['deploymentId'],
        'members':len(manifest['members']),'preservedObjects':len(prep['preservedObjects']),
        'modelFits':0,'simulations':0,'providerCalls':0,'aispWrites':0,'taskChanges':0}))


if __name__=='__main__':main()
