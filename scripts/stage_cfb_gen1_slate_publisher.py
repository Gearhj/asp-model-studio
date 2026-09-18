"""Stage the exact retained baseline and offline slate publisher; never install."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.publication_io import reference,verified_bytes,canonical_bytes,digest
from server.sports_cfb_gen1.lifecycle import immutable,now,object_json,read_ref,POLICY,eligibility
from server.sports_cfb_gen1.inputs import admit


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--studio',default=r'C:\Users\james\asp-model-studio')
    p.add_argument('--preparation',required=True)
    p.add_argument('--requirements',required=True)
    p.add_argument('--output',required=True)
    a=p.parse_args();source=Path(__file__).resolve().parents[1];root=Path(a.studio);out=Path(a.output)
    receipt=out/'release-receipt.json'
    if receipt.exists():
        saved=read_ref(reference(receipt))
        manifest=read_ref(saved['deploymentManifest']);read_ref(saved['release'])
        for m in manifest['members']:verified_bytes(dict(m,path=str(Path(saved['deploymentManifest']['path']).parent/m['relativePath'])))
        print(json.dumps(saved,indent=2));return
    prep=read_ref(reference(a.preparation));configuration=read_ref(prep['configuration'])
    for ref in prep['preservedObjects']:verified_bytes(ref)
    requirements=reference(a.requirements);req=read_ref(requirements)
    if req['schema']!='CFB_GEN1_REFRESH_AUTHORIZATION_REQUIREMENTS_V1' or req['networkEnabledByDefault'] is not False:
        raise ValueError('Wrong acquisition requirements')
    names=['__init__.py','pipeline.py','current.py','publication_io.py','identities.py','inputs.py','lifecycle.py','render.py','owner.py']
    paths=[source/'server/__init__.py']+[source/'server/sports_cfb_gen1'/n for n in names]
    paths += [source/'scripts'/n for n in ('run_cfb_gen1_slate_publisher.py','invoke_cfb_gen1_slate_publisher.ps1','install_cfb_gen1_slate_publisher.ps1')]
    members=[dict(relativePath=x.relative_to(source).as_posix(),sha256=reference(x)['sha256'],bytes=x.stat().st_size) for x in paths]
    members.append(dict(relativePath='configuration/REFRESH_REQUIREMENTS.json',sha256=requirements['sha256'],bytes=requirements['bytes']))
    identity={'schema':'CFB_GEN1_SLATE_DEPLOYMENT_IDENTITY_V1','sourceCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip(),
        'members':members,'configurationIdentity':configuration['configurationIdentity'],'policy':POLICY,
        'drawCount':10000,'numericalModelUnchanged':True,'canonicalTaskName':'ASP CFB Forecast Publisher'}
    deployment_id=digest(identity);deployment=root/'.deployments/cfb-gen1-slate-publisher'/deployment_id
    for file,member in zip(paths,members):immutable(deployment/member['relativePath'],file.read_bytes())
    requirements=immutable(deployment/'configuration/REFRESH_REQUIREMENTS.json',verified_bytes(requirements))
    manifest_ref=immutable(deployment/'deployment-manifest.json',canonical_bytes(dict(identity,deploymentId=deployment_id,
        createdAtUtc=now(),status='STAGED_NOT_INSTALLED',activationAuthorized=False)))
    # Refresh only the local admission representation, never its evidence clocks.
    original_input=read_ref(prep['inputVersion'])
    input_ref=admit(manifest_ref=original_input['sourceManifest'],release=configuration,registry_root=out/'inputs')
    import pandas as pd
    from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS
    new_input=read_ref(input_ref)
    cols=['game_id']+FEATURE_COLUMNS
    pd.testing.assert_frame_equal(pd.read_parquet(original_input['features']['path'],columns=cols),
                                  pd.read_parquet(new_input['features']['path'],columns=cols),check_exact=True)
    effective=now()
    release=dict(configuration,schema='CFB_GEN1_SLATE_RELEASE_V1',createdAtUtc=effective,
        prospectiveEffectiveAtUtc=effective,deploymentManifest=manifest_ref,
        refreshAuthorizationProposal=requirements,initialInputVersion=input_ref,
        inputPointer=str((out/'inputs/current.json').resolve()),networkCapability=False,
        installationAuthorized=False,consumerActivated=False,policy=POLICY,
        publicationClockAuthority='Cumulative discovery bound publicationReceipt.committedAtUtc; no restamping of source forecasts')
    release_ref=object_json(out/'releases',release,'release.json')
    inventory=[dict(gameId=x['gameId'],target=x['target'],underlyingInputBlockers=x.get('inputBlockers',[]),
        **eligibility(x,new_input,effective)) for x in new_input['games']]
    inventory_ref=object_json(out/'inventory',dict(createdAtUtc=effective,inputVersion=input_ref,games=inventory),'inventory.json')
    saved=dict(schema='CFB_GEN1_SLATE_STAGING_RECEIPT_V1',deploymentId=deployment_id,deploymentManifest=manifest_ref,
        release=release_ref,preparation=reference(a.preparation),refreshRequirements=requirements,inputVersion=input_ref,
        inputPointer=release['inputPointer'],inventory=inventory_ref,installed=False,providerCalls=0,providerBytes=0,costUsd=0,
        aispWrites=0,modelFits=0,newProspectiveForecasts=0)
    immutable(receipt,canonical_bytes(saved));print(json.dumps(saved,indent=2))


if __name__=='__main__':main()
