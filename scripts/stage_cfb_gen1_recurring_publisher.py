"""Stage one same-owner successor; no network, fitting, forecasts or task writes."""
import argparse
from pathlib import Path
import json
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.publication_io import reference,verified_bytes,canonical_bytes,digest
from server.sports_cfb_gen1.lifecycle import immutable,now,object_json,read_ref,POLICY
from server.sports_cfb_gen1.inputs import validate_bundle


def prediction_binding(previous, previous_ref):
    """Keep the original numerical identity across operational successors."""
    compatible = previous.get('compatiblePredictionRelease', previous_ref)
    identity = previous.get('predictionReleaseIdentity', previous_ref['sha256'])
    if compatible['sha256'] != identity:
        raise ValueError('Canonical prediction release identity mismatch')
    return compatible, identity


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--studio',default=r'C:\Users\james\asp-model-studio')
    p.add_argument('--prior-release',required=True);p.add_argument('--prior-release-sha256',required=True)
    p.add_argument('--refresh-plan',required=True);p.add_argument('--input-pointer',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args();source=Path(__file__).resolve().parents[1];root=Path(a.studio);out=Path(a.output)
    receipt=out/'release-receipt.json'
    if receipt.exists():
        saved=read_ref(reference(receipt));release=read_ref(saved['release']);manifest=read_ref(saved['deploymentManifest'])
        for m in manifest['members']:verified_bytes(dict(m,path=str(Path(saved['deploymentManifest']['path']).parent/m['relativePath'])))
        print(json.dumps(saved,indent=2));return
    previous_ref=reference(a.prior_release)
    if previous_ref['sha256']!=a.prior_release_sha256:raise ValueError('Wrong prior release')
    previous=read_ref(previous_ref);input_ref=read_ref(reference(a.input_pointer))['inputManifest']
    validate_bundle(read_ref(input_ref),previous)
    prediction_ref,prediction_id=prediction_binding(previous,previous_ref)
    plan_ref=reference(a.refresh_plan);plan=read_ref(plan_ref)
    if plan['schema']!='CFB_GEN1_RECURRING_REFRESH_PLAN_V1' or plan['networkEnabledByDefault'] is not False:
        raise ValueError('Exact disabled-default recurring plan required')
    # Every path here is reviewed executable source, not raw data or credentials.
    names=['__init__.py','pipeline.py','current.py','publication_io.py','identities.py','inputs.py','lifecycle.py','render.py','owner.py','capture.py','refresh.py']
    paths=[source/'server/__init__.py']+[source/'server/sports_cfb_gen1'/n for n in names]
    paths += [source/'scripts'/n for n in ('run_cfb_gen1_slate_publisher.py','invoke_cfb_gen1_slate_publisher.ps1','install_cfb_gen1_slate_publisher.ps1')]
    members=[dict(relativePath=x.relative_to(source).as_posix(),sha256=reference(x)['sha256'],bytes=x.stat().st_size) for x in paths]
    members.append(dict(relativePath='configuration/REFRESH_PLAN.json',sha256=plan_ref['sha256'],bytes=plan_ref['bytes']))
    identity={'schema':'CFB_GEN1_SLATE_DEPLOYMENT_IDENTITY_V1','sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),
        'members':members,'configurationIdentity':previous['configurationIdentity'],'policy':POLICY,'drawCount':10000,
        'numericalModelUnchanged':True,'canonicalTaskName':'ASP CFB Forecast Publisher',
        'supersedesUninstalledDeployment':read_ref(previous['deploymentManifest'])['deploymentId'],
        'networkEnabledByDefault':False,'predictionReleaseIdentity':prediction_id}
    deployment_id=digest(identity);deployment=root/'.deployments/cfb-gen1-slate-publisher'/deployment_id
    for file,member in zip(paths,members):immutable(deployment/member['relativePath'],file.read_bytes())
    deployed_plan=immutable(deployment/'configuration/REFRESH_PLAN.json',verified_bytes(plan_ref))
    manifest_ref=immutable(deployment/'deployment-manifest.json',canonical_bytes(dict(identity,deploymentId=deployment_id,
        createdAtUtc=now(),status='STAGED_NOT_INSTALLED',activationAuthorized=False)))
    release=dict(previous,createdAtUtc=now(),predecessor=previous_ref,deploymentId=deployment_id,
        deploymentManifest=manifest_ref,refreshPlan=deployed_plan,refreshAuthorizationProposal=deployed_plan,
        compatiblePredictionRelease=prediction_ref,predictionReleaseIdentity=prediction_id,
        inputPointer=str(Path(a.input_pointer).resolve()),initialInputVersion=input_ref,
        networkCapability=True,networkEnabledByDefault=False,installationAuthorized=False,
        stateRoot=str(root/'.runtime/cfb-gen1-slate-publisher/state'),
        successorScope='Operational capture/admission only; preserves original prospective effective time and numerical configuration')
    validate_bundle(read_ref(input_ref),release)
    release_ref=object_json(out/'releases',release,'release.json')
    saved={'schema':'CFB_GEN1_RECURRING_STAGING_RECEIPT_V1','deploymentId':deployment_id,
        'deploymentManifest':manifest_ref,'release':release_ref,'refreshPlan':deployed_plan,
        'predecessorRelease':previous_ref,'inputVersion':input_ref,'inputPointer':release['inputPointer'],
        'stateRoot':release['stateRoot'],'installed':False,'networkAuthorized':False,
        'providerCalls':0,'providerBytes':0,'costUsd':0,'aispWrites':0,'modelFits':0,'newProspectiveForecasts':0}
    immutable(receipt,canonical_bytes(saved));print(json.dumps(saved,indent=2))


if __name__=='__main__':main()
