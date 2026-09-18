"""Verify authorized capture/publication without new provider calls or inference."""
import argparse,ast,csv,hashlib,json,pathlib,typing
from collections import Counter
from datetime import timedelta
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.sports_cfb_gen1.lifecycle import read_ref,immutable,now,utc
from server.sports_cfb_gen1.publication_io import canonical_bytes,reference,verified_bytes,digest
from server.sports_cfb_gen1.render import verify_package

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);a=p.parse_args();root=Path(a.root)
    out=root/'VERIFIED_RUN.json'
    if out.exists():
        saved=read_ref(reference(out));checked=set()
        def verify_references(value):
            if isinstance(value,dict):
                if {'path','sha256','bytes'}.issubset(value):
                    key=(value['path'],value['sha256'])
                    if key not in checked:verified_bytes(value);checked.add(key)
                for item in value.values():verify_references(item)
            elif isinstance(value,list):
                for item in value:verify_references(item)
        verify_references(saved)
        for row in saved['issuedGames']:verify_package(Path(row['index']['path']).parent)
        manifest=read_ref(saved['capturedManifest'])
        for ref in manifest['requests']:verified_bytes(ref)
        prep=read_ref(reference(Path(r'C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1\preparation.json')))
        for ref in prep['preservedObjects']:verified_bytes(ref)
        print(json.dumps({'disposition':'EXISTING_RECEIPT_REVERIFIED_NO_WRITES','receipt':reference(out),
            'packages':len(saved['issuedGames']),'physicalReferences':len(checked),'originalObjectsUnchanged':len(prep['preservedObjects']),
            'providerCalls':0,'inferenceRuns':0}));return
    capture_ref=reference(root/'capture/completion.json');capture=read_ref(capture_ref);manifest=read_ref(capture['sourceManifest'])
    assert capture['disposition']=='CAPTURED' and capture['providerCalls']==7 and capture['providerBytes']<=25*1024*1024
    for ref in manifest['requests']:verified_bytes(ref)
    assert sum(x['bytes'] for x in manifest['requests'])==capture['providerBytes']
    paths=[p for p in (root/'publication-launcher').glob('*.json') if not p.name.endswith(('.started.json','.runner-result.json'))]
    assert len(paths)==1;launcher_ref=reference(paths[0]);launcher=read_ref(launcher_ref)
    assert launcher['pythonExitCode']==launcher['wrapperExitCode']==0
    owner=read_ref(launcher['runner']['receipt']);runner=read_ref(owner['runnerReceipt']);discovery=read_ref(runner['discovery'])
    release=read_ref(runner['release']);prep=read_ref(reference(Path(r'C:\Users\james\asp-model-studio\outputs\cfb-gen1-slate-publisher-v1\preparation.json')))
    for ref in prep['preservedObjects']:verified_bytes(ref)
    # Execute only existing consumer read-only verifier functions, never its importer.
    source=release['consumerCodeEvidence'][0];text=verified_bytes(source).decode('utf-8-sig');tree=ast.parse(text)
    funcs=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in ('verify_package','read_pmfs')]
    ns={'pathlib':pathlib,'Any':typing.Any,'hashlib':hashlib,'json':json,'CfbImportError':ValueError,
        'INDEX_SCHEMA':'CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1','MUST_BE_FALSE':('aispAuthority','wageringAuthority'),
        'PMF_METRICS':('away_score','home_score','total','home_margin')}
    exec(compile(ast.Module(body=funcs,type_ignores=[]),source['path'],'exec'),ns)
    rows=[]
    for g in runner['games']:
        row={'gameId':g['gameId'],'disposition':g['disposition'],'currentlyEligibleAtInvocation':g['currentlyEligible']}
        if g.get('package'):
            package=g['package'];folder=Path(package['packageDirectory']);index=verify_package(folder)
            ns['verify_package'](folder);ns['read_pmfs'](folder,expected_draws=10000)
            f=json.loads((folder/'forecast.json').read_bytes());b=f['baseline'];game=f['game'];pub=utc(package['committedAtUtc'])
            assert utc(f['sourceCutoff'])<=utc(f['createdAt'])<=pub<utc(game['scheduled_at'])-timedelta(minutes=30)
            assert f['modelBindings']==release['modelBindings'] and index['configurationIdentity']==release['configurationIdentity']
            row.update(forecastId=f['forecastId'],forecast=reference(folder/'forecast.json'),index=package['index'],
                away=game['away_team'],home=game['home_team'],awayId=game['away_id'],homeId=game['home_id'],kickoff=game['scheduled_at'],
                sourceCutoff=f['sourceCutoff'],createdAt=f['createdAt'],publishedAt=package['committedAtUtc'],
                sourceInput=f['sourceBindings']['inputVersion'],population=reference(folder/'baseline-joint-draws.parquet'),
                logicalPopulationSha256=f['population']['logicalHomeAwayInt64LeSha256'],
                drawCount=b['drawCount'],expectedAway=b['expectedAwayPoints'],expectedHome=b['expectedHomePoints'],
                calibratedHomeWin=b['ridgeHomeWinProbability'],eloHomeWin=b['eloHomeWinProbability'],jointHomeWin=b['jointHomeWinProbability'],
                eligibilityValidUntilUtc=g['eligibilityValidUntilUtc'])
        else:row.update(reason=g.get('reason'),inputBlockers=g.get('inputBlockers'),nextCheckpointUtc=g.get('nextCheckpointUtc'))
        rows.append(row)
    full_inventory=immutable(root/'ALL_GAME_DISPOSITIONS.json',canonical_bytes({'asOfUtc':runner['completedAtUtc'],'games':rows}))
    issued=[r for r in rows if 'forecastId' in r]
    assert len(issued)==len(discovery['packages'])==57
    with (root/'ISSUED_GAMES.csv').open('x',newline='',encoding='utf-8') as handle:
        cols=['gameId','away','home','kickoff','forecastId','createdAt','publishedAt','sourceCutoff','drawCount','expectedAway','expectedHome','calibratedHomeWin','eloHomeWin','jointHomeWin','eligibilityValidUntilUtc']
        writer=csv.DictWriter(handle,fieldnames=cols,extrasaction='ignore');writer.writeheader();writer.writerows(issued)
    result={'schema':'CFB_GEN1_AUTHORIZED_REFRESH_PUBLICATION_VERIFICATION_V1','createdAtUtc':now(),'captureReceipt':capture_ref,
        'capturedManifest':capture['sourceManifest'],'inputVersion':runner['input'],'launcher':launcher_ref,'ownerReceipt':launcher['runner']['receipt'],
        'runnerReceipt':owner['runnerReceipt'],'discovery':runner['discovery'],'allGameDispositions':full_inventory,
        'issuedGamesCsv':reference(root/'ISSUED_GAMES.csv'),'issuedGames':issued,'dispositions':dict(Counter(g['disposition'] for g in rows)),
        'newForecasts':len(issued),'reusedForecasts':0,'allDrawCounts':10000,'totalRetainedDraws':10000*len(issued),
        'allPackagesPassedIndependentConsumerReadChecks':True,'allPrePublicationCutoffChecksPassed':True,
        'originalResearchAndModelObjectsUnchanged':len(prep['preservedObjects']),
        'providerCalls':capture['providerCalls'],'providerBytes':capture['providerBytes'],'costUsd':0,
        'cumulativeHttpRequests':8+capture['providerCalls'],'cumulativeResponseBytes':3890306+capture['providerBytes'],
        'entitlementBefore':capture['entitlementBefore'],'entitlementAfter':capture['entitlementAfter'],
        'captureSeconds':(utc(capture['completedAtUtc'])-utc(capture['startedAtUtc'])).total_seconds(),
        'publisherSeconds':(utc(launcher['completedAtUtc'])-utc(launcher['startedAtUtc'])).total_seconds(),
        'aispWrites':0,'taskInstalled':False,'consumerImportConfirmed':False,'modelFits':0,
        'caveat':'Publication is verified; import is not. Discovery eligibility leases expire and need a later authorized tick. Original forecasts remain immutable.'}
    immutable(out,canonical_bytes(result))
    print(json.dumps({k:v for k,v in result.items() if k!='issuedGames'},indent=2))

if __name__=='__main__':main()
