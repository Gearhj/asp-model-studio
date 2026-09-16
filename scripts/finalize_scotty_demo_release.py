"""Finalize unpublished release staging and publish one new CFB package.

Existing sport discovery pointers and forecast versions are never replaced.
The demo release's own discovery is updated only by scotty_demo_release.py.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.scotty_demo_release import *


def finish(stage,exchange):
    stage=Path(stage);exchange=Path(exchange)
    if (stage/'package-manifest.json').exists():
        raise ValueError('RELEASE_ALREADY_SEALED_USE_VERIFY_OR_IDEMPOTENT_PUBLISH')
    release=read(stage/'release.json')
    c=next(x for x in release['forecasts'] if x['sport']=='CFB')
    local=Path(c['localPackage']);dest=Path(c['intendedPackage'])
    expected_root=exchange/'cfb-gen1-research-v1/current-v1/packages/sha256'
    if dest.parent.resolve()!=expected_root.resolve():raise ValueError('CFB_DESTINATION')
    if not dest.exists():
        tmp=expected_root.parent/'.demo-staging'/dest.name
        if tmp.exists():raise ValueError('CFB_INCOMPLETE_STAGE')
        shutil.copytree(local,tmp)
        from scripts.publish_cfb_gen1_current_v1 import verify_package
        verify_package(tmp)
        verify_index_package(tmp)
        forecast=read(tmp/'forecast.json')
        pub=now()
        chronology(forecast['sourceCutoff'],forecast['createdAt'],pub,forecast['game']['scheduled_at'])
        if (clock(forecast['game']['scheduled_at'])-clock(pub)).total_seconds()<3600:
            raise ValueError('CFB_ORIGINAL_T60_RULE')
        write(tmp/'publication-receipt.json',{'schemaVersion':'CFB_GEN1_RESEARCH_PUBLICATION_RECEIPT_V1',
            'publishedAtUtc':pub,'forecastId':forecast['forecastId'],'packageDigest':dest.name,
            'consumerAcknowledgement':None,'newForecasts':1,'modelFits':0,'providerRequests':0,
            'authorityChanged':False,'currentPointerReplaced':False})
        dest.parent.mkdir(parents=True,exist_ok=True);os.rename(tmp,dest)
    index,verification=verify_index_package(dest)
    from scripts.publish_cfb_gen1_current_v1 import verify_package
    verify_package(dest)
    c['package']=verification['index'];c['packageVerification']=verification
    pub=read(dest/'publication-receipt.json');c['publicationClock']=pub['publishedAtUtc'];c['publicationReceipt']=physical(dest/'publication-receipt.json')
    c['scheduledStartUtc']=c['game']['scheduled_at'];c['clocks']=chronology(c['sourceCutoffUtc'],c['createdAtUtc'],c['publicationClock'],c['scheduledStartUtc'])
    c.pop('localPackage',None)
    # These are explicit operational limitations, not a change to any authority.
    release['blockers']={
        'blocksLiveDemo':[
            'MLB weekend FINAL_PREGAME forecasts do not yet exist. Existing owner must receive eligible inputs and publish before consumer T-15; research deadline remains T-5.',
            'Exact AISP acknowledgement of this release and new CFB forecast is required; no import or display is claimed.',
            'CFB weekend canonical event binding to CFBD 401869940 must be confirmed by the consumer.'],
        'doesNotBlockTruthfulResearchDemo':[
            'NBA season inactive: use original early BOS-DET example, never a current/live card.',
            'MLB exact exchange-directory access was denied for inspection; local immutable forecast/draw bytes verified. Consumer must verify its own published package before import.',
            'NFL tie mass is not independently validated and personnel inputs remain incomplete.',
            'Historical availability limitations remain; none of the declarations establish profitability.',
            'OneDrive encrypted recovery remains paused after safe local staging; source preservation is unchanged.']}
    release['accounting']={'newCfbForecasts':1,'newCfbSimulatedDraws':10000,'modelFits':0,'providerRequests':0,
        'providerBytes':0,'incrementalCostUsd':0,'sportsbookRequests':0,'aispWrites':0,
        'schedulerChanges':0,'sealedPayloadReads':0,'modelPromotions':0,
        'backgroundOwnerActivity':'Existing independent owners may acquire/publish; those calls are not initiated by this release.'}
    stage.joinpath('release.json').write_bytes(canonical(release))
    # Freeze moving pointer bytes as evidence at the actual capture time.
    paths=[exchange/'aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json',
           exchange/'nfl-labs-supplements/nfl-labs-supplement-index.json',exchange/'show-preview-forecasts-v1/discovery.json']
    captures=[]
    for p in paths:
        data=p.read_bytes();digest=sha(data);q=stage/'discovery-snapshots'/(digest+'.json');q.parent.mkdir(exist_ok=True);q.write_bytes(data)
        captures.append({'source':str(p),'capturedAtUtc':now(),'relativePath':q.relative_to(stage).as_posix(),'sha256':digest,'bytes':len(data)})
    write(stage/'discovery-snapshots.json',captures)
    handoff=render_handoff(release)
    (stage/'CLAUDE_HANDOFF.md').write_text(handoff,encoding='utf-8',newline='\n')
    return {'cfb':c['package'],'newCfbPublication':c['publicationReceipt'],'stage':str(stage)}


def render_handoff(r):
    nfl=[x for x in r['forecasts'] if x['sport']=='NFL'];nba=[x for x in r['forecasts'] if x['sport']=='NBA'];cfb=next(x for x in r['forecasts'] if x['sport']=='CFB')
    lines=['# Scotty demo: producer release handoff','',
        'This is a declaration/delivery manifest, not a new betting policy or model promotion. Verify package-manifest.json using ASP_FILENAME_TO_SHA256_MAP_CANONICAL_JSON_UTF8_V1. The package directory is the logical member-map identity; physical manifest and discovery hashes are separate.','',
        '## Expected consumer imports','',
        '1. Read four declarations in champions/. Keep MLB conditional controlling-final, NFL research/paper, and NBA/CFB research-only labels. Existing exact-bound paper supplements remain separate; this release grants no authority.',
        '2. Reuse the 16 exact CURRENT NFL Week 2 objects below and their exact eligibility supplements. Import bundle then supplement using existing adapters. Unchanged objects are idempotent; do not restamp. A later FINAL_PREGAME successor needs its own bound supplement.',
        '3. Preserve NBA point/Elo package '+nba[0]['package']['sha256']+'. Select only baseline from joint package '+nba[1]['package']['sha256']+'. The close-score arm is retained in that comparison package but not selected or promoted. Point/Elo drawCount remains zero; joint baseline has 10,000.',
        '4. Import CFB package '+cfb['packageIndexSha256']+' at `'+cfb['intendedPackage']+'`. Bind CFBD 401869940: Coastal Carolina away, Delaware home, September 19 15:30 UTC / 11:30 EDT. Source cutoff September 14 is an early snapshot; do not call this a fresh final forecast.',
        '5. Existing Show Preview discovery is separate: 16 NFL and one CFB editorial derivative. A preview can never substitute for CURRENT/FINAL_PREGAME. The new CFB forecast is PROSPECTIVE_RESEARCH, not SHOW_PREVIEW.',
        '6. MLB: preserve the natural owner and ordinary exchange path. No September 19-20 final was fabricated. The historical local example is for explanation, not a current decision import. The release contains the latest natural tick, deployment hash, timing contract, blockers and original draw reconciliation.','',
        'The new versioned release/declaration envelope is additive. If AISP does not parse this envelope yet, it can use these exact existing forecast-package adapters; it must not infer market eligibility from the declaration label. No AISP code/configuration/database was edited.','',
        '| NFL event | Forecast | Bundle SHA-256 | Eligibility physical SHA-256 |','|---|---|---|---|']
    lines += [f"| {x['eventId']} | `{x['forecastId']}` | `{x['package']['sha256']}` | `{x['eligibility']['sha256']}` |" for x in nfl]
    lines += ['', '## Channels and permissions','',
        'MLB ordinary V18 retains unrestricted 5,000 paired scores and confirmed lineups. NFL uses 10,000 paired score draws; equal-score tie mass is not separately calibrated. NBA Elo winners, Ridge points and paired-residual distributions are different channels. CFB Ridge-margin calibrated winner, Elo winner and joint-residual winner are likewise separate.',
        'NFL live paper assessment is possible only under its existing exact-forecast authorization and consumer timing/quote/policy gates. MLB requires its existing eligible final forecast and consumer authority. Existing NBA/CFB V2 paper supplements are referenced in paper-eligibility-audit.json: NBA binds only the original BOS-DET joint baseline; CFB binds only the original September 17 Syracuse-Pittsburgh forecast. Neither binding transfers to another forecast. NBA remains season inactive for this demo. The new Coastal Carolina-Delaware forecast has no new paper supplement and supports research display/illustrative line queries only. This release grants no wagering or virtual-position authority.',
        'Probability units are fractions 0–1. For totals: Over win T>L, push T=L, loss T<L; Under reverses win/loss. Use complete paired totals, never the average score. Expected return per stake = pWin*(decimalOdds-1)-pLoss; push-aware fair odds = 1+pLoss/pWin when pWin>0. No actual quote or profitability claim is supplied.',
        'Historical metrics are inherited qualified evidence. MLB PA Brier sums eight classes; NFL Brier sums AWAY/TIE/HOME; NBA/CFB winner Brier is (pHome-y)^2. Simulation count/MCSE is numerical precision, not independent game evidence.','',
        '## Acknowledgement','',
        'Prior NBA point/Elo consumer acknowledgement is retained in nba-package-audit.json; it is not acknowledgement of this release or of the joint baseline. After import/display verification, write an additive receipt under demo-releases-v1/consumer-receipts naming this release address, each imported forecast ID and physical hash, canonical event bindings, reused/new counts, display checks and actual UTC time. Publication alone establishes none of those actions.',
        'No model fit, new research, sealed evidence, sportsbook collection, AISP write, account operation or scheduler change was performed.']
    return '\n'.join(lines)+'\n'


def complete_checks(stage, exchange):
    """Review current pure consumer validator and preserve existing paper scopes.

    Operates only on unpublished release staging and reads existing packages.
    Never modifies consumer code, original preview plans or paper supplements.
    """
    import pandas as pd
    from server.sports_shared.show_preview import consumer_validator, verify_package as preview_verify
    from server.sports_shared.paper_research_eligibility import verify_package as paper_verify
    stage, exchange = Path(stage), Path(exchange)
    if (stage/'package-manifest.json').exists():
        raise ValueError('RELEASE_ALREADY_SEALED')
    release = read(stage/'release.json')
    validator_path = exchange.parent/'ai-sports-predictor/server/app/show_preview/contract.py'
    validator_sha = '35715f3241c3f2b6c1d2ce33f01728da2562c93485ffc47cd06fc72e2beac083'
    validator = consumer_validator(validator_path, validator_sha)
    preview_results = []
    for entry in release['showPreview']['packages']:
        path = exchange/'show-preview-forecasts-v1'/entry['package_path']
        doc = preview_verify(path, validator)
        if doc['forecast_id'] != entry['forecast_id']:
            raise ValueError('PREVIEW_DISCOVERY_BINDING')
        preview_results.append({'forecastId': entry['forecast_id'], 'sport': entry['sport'],
            'manifest': physical(path/'manifest.json'), 'forecast': physical(path/'forecast.json'),
            'exactDerivationReplay': True})
    preview_receipt = {'schemaVersion': 'ASP_DEMO_PREVIEW_COMPATIBILITY_V1',
        'previousPlanValidatorSha256': '1a6771cb0fbf7c41cdc1e05e09141a7a4db513b82a7993399aec64fc6ea9f275',
        'reviewedCurrentValidator': physical(validator_path), 'verifiedPackages': preview_results,
        'oldPlanModified': False, 'consumerWrites': 0, 'simulationExecutions': 0,
        'qualification': 'Read-only release compatibility check under reviewed successor pure validator; no owner activation or original-plan update.'}
    write(stage/'show-preview-compatibility.json', preview_receipt)

    # The older CFB object is retained because the existing paper supplement
    # is exact-bound to it, not to this release's newly produced weekend game.
    cfb_path = exchange/'cfb-gen1-research-v1/current-v1/packages/sha256/72a91840c7f0a88a7248d3a36c9723e4011dd75969859e05d65b7be971ae298f'
    if not any(f['forecastId']=='cfb-gen1:51e40da85f05b98dc58144627f4a8902606c0aebc10182461c4f0402b8eee1ce' for f in release['forecasts']):
        from scripts.publish_cfb_gen1_current_v1 import verify_package as cfb_verify
        cfb_verify(cfb_path)
        _, verification = verify_index_package(cfb_path)
        f = read(cfb_path/'forecast.json'); b = f['baseline']; pub = read(cfb_path/'publication-receipt.json')
        draws = pd.read_parquet(cfb_path/'baseline-joint-draws.parquet')
        s = joint_summary(draws.home_score, draws.away_score)
        agree(s['homeWin'], b['jointHomeWinProbability'])
        if s['drawCount'] != 10000 or s['tie'] != 0: raise ValueError('CFB_ORIGINAL_POPULATION')
        release['forecasts'].append({'sport':'CFB', 'eventId':'cfbd:401858225', 'providerGameId':401858225,
            'forecastId':f['forecastId'], 'horizon':'PROSPECTIVE_RESEARCH', 'game':f['game'],
            'sourceCutoffUtc':f['sourceCutoff'], 'createdAtUtc':f['createdAt'],
            'publicationClock':pub['publishedAtUtc'], 'package':verification['index'],
            'packageVerification':verification, 'channels':b, 'numericalVerification':s,
            'clocks':chronology(f['sourceCutoff'],f['createdAt'],pub['publishedAtUtc'],f['game']['scheduled_at']),
            'consumerUse':'EXACT_EXISTING_PAPER_SUPPLEMENT_SUBJECT_TO_AISP_GATES',
            'marketAuthorityGrantedByRelease':False, 'consumerAcknowledgement':None})
    papers = []
    for sport, tree, address in [
        ('NBA','nba-gen1-research-v1','ef3fd91d9444e4e0ec8959e2cf888bb117efd7b3486632c9539122f6eaf46f12'),
        ('CFB','cfb-gen1-research-v1','7d653fec4ce94caf853d58db17348751ad5a5286539581be581bb81e826193e7')]:
        verified = paper_verify(exchange/tree/'paper-eligibility/sha256'/address)
        doc = verified.pop('document'); binding = doc['binding']
        row = next(f for f in release['forecasts'] if f['forecastId']==binding['forecastId'])
        if row['eventId'] != binding['eventId'] or row['package']['sha256'] != binding['sourcePackageAddress']:
            raise ValueError('EXISTING_PAPER_EXACT_BINDING')
        row['existingPaperEligibility'] = {'address':address, 'binding':binding,
            'supplement':verified['supplement'], 'scope':'EXACT_EXISTING_FORECAST_ONLY_NO_TRANSFER'}
        papers.append({**verified,'sport':sport,'binding':binding,'authorization':doc['summaries']['authorization']})
        champion = next(c for c in release['champions'] if c['sport']==sport)
        champion['authority']['existingPaperSupplement'] = row['existingPaperEligibility']
        champion['authority']['permittedConsumerUse'] = (
            'Research display/illustrative queries. Existing exact-bound V2 paper supplement is preserved separately; '
            'no new forecast is made eligible by this declaration. Consumer timing/quote/policy gates remain mandatory.')
    write(stage/'paper-eligibility-audit.json', papers)
    release['showPreview']['compatibilityReceipt'] = physical(stage/'show-preview-compatibility.json')
    release['existingPaperEligibilityAudit'] = physical(stage/'paper-eligibility-audit.json')
    release['blockers']['doesNotBlockTruthfulResearchDemo'].append(
        'New CFB weekend forecast is not bound to the existing Syracuse-Pittsburgh paper supplement; research display is supported, paper eligibility is not inferred.')
    release['blockers']['doesNotBlockTruthfulResearchDemo'] = list(dict.fromkeys(release['blockers']['doesNotBlockTruthfulResearchDemo']))
    for c in release['champions']:
        (stage/'champions'/f"{c['sport']}.json").write_bytes(canonical(c))
    validate_release(release)
    (stage/'release.json').write_bytes(canonical(release))
    (stage/'CLAUDE_HANDOFF.md').write_text(render_handoff(release),encoding='utf-8',newline='\n')
    return {'previewPackagesVerified':len(preview_results),'existingPaperSupplementsVerified':len(papers),
        'forecastRows':len(release['forecasts']),'originalArtifactsChanged':False}


def final_local_verification(stage):
    """Reconcile immutable bindings after all release checks, before sealing."""
    stage = Path(stage)
    if (stage/'package-manifest.json').exists(): raise ValueError('RELEASE_ALREADY_SEALED')
    release = read(stage/'release.json')
    captures = read(stage/'discovery-snapshots.json')
    moving = {r['source'] for r in captures}
    refs = read(stage/'source-bindings.json')['files']
    checked_refs = [checked(r) for r in refs if r['path'] not in moving]
    for r in captures:
        checked({'path':str(stage/r['relativePath']),'sha256':r['sha256'],'bytes':r['bytes']})
    for f in release['forecasts']:
        if f['sport'] == 'NFL':
            checked(f['package']); checked(f['eligibility'])
            c = f['clocks']
            if c.get('publishedAtUtc') is not None:
                c['bundleGeneratedAtUtc'] = c.pop('publishedAtUtc')
                c['publishedAtUtc'] = None
            c.setdefault('publicationObservedAtUtc',now())
            c['publicationClockQualification'] = 'Exact original publication instant absent from bundle contract; immutable package is physically present at audit.'
            if clock(c['publicationObservedAtUtc']) >= clock(c['scheduledStartUtc']):
                raise ValueError('NFL_FORECAST_NO_LONGER_FUTURE')
            deadline = clock(c['scheduledStartUtc'])-timedelta(minutes=15)
            c['consumerDecisionCutoffUtc'] = deadline.isoformat()
            c['consumerWindowOpensUtc'] = (deadline-timedelta(minutes=15)).isoformat()
        if 'numericalVerification' in f:
            n = f['numericalVerification']; probabilities(n['homeWin'],n['awayWin'],n['tie'])
    replay_path = stage/'cfb-reproduction.json'
    replay = read(replay_path)
    if replay.pop('pointPredictionsExactlyReproducedWithin1e8',False):
        replay['pointPredictionAbsoluteTolerance'] = 1e-8
        replay['pointPredictionsReproduced'] = True
        replay_path.write_bytes(canonical(replay))
    release['accounting']['verificationOnlyCfbDraws'] = replay['verificationDraws']
    release['accounting']['existingForecastsRegenerated'] = 0
    write(stage/'source-preservation-verification.json',{
        'schemaVersion':'ASP_DEMO_SOURCE_PRESERVATION_V1','immutableReferences':checked_refs,
        'movingPointersHandledAsSnapshots':captures,'allCheckedBytesUnchanged':True,
        'scope':'Exact selected dependencies only; not a whole-filesystem audit. Independent owners continue normally.'})
    release['verification'] = {'sourcePreservation':physical(stage/'source-preservation-verification.json'),
        'cfbReproduction':physical(replay_path),'focusedSoftwareChecks':'tests/test_scotty_demo_release.py; see retained execution receipt'}
    (stage/'nfl-week2-audit.json').write_bytes(canonical([f for f in release['forecasts'] if f['sport']=='NFL']))
    (stage/'release.json').write_bytes(canonical(release))
    (stage/'CLAUDE_HANDOFF.md').write_text(render_handoff(release),encoding='utf-8',newline='\n')
    return {'unchangedImmutableReferences':len(checked_refs),'movingSnapshots':len(captures),'forecastRows':len(release['forecasts'])}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--exchange',type=Path,required=True)
    p.add_argument('--checks-only',action='store_true')
    p.add_argument('--final-local-verification',action='store_true')
    a=p.parse_args()
    if a.final_local_verification:
        print(json.dumps(final_local_verification(a.stage),indent=2))
    else:
        if not a.checks_only: finish(a.stage,a.exchange)
        print(json.dumps(complete_checks(a.stage,a.exchange),indent=2))
