"""Prepare the September 19-20 release from explicit retained authorities.

Only aggregate historical reports, governed forecast objects, model hashes and
operational receipts are inspected. No model selection or protected outcomes.
"""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.scotty_demo_release import *

MLB_MANIFEST='3e8dcc1c50dcdfd2d748e5e0de8e7595ad0b50a2c62eb9baadb4ffe9e5d640c2'
NFL_MANIFEST='ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9'
NBA_POINT='85e3d7414ccaac4b79c524096af3f7fa894169041e143ee3dc5894002f53e2e0'
NBA_JOINT='00cd49902fc00beb0a8edea9bb8a18ffa6e78d5e5da6c397c6a986c0af397a9d'
READS={}


def ref(p):
    r=physical(p);READS[r['path']]=r;return r


def load(p):
    ref(p);return read(p)


def artifacts(refs):
    result=[]
    for r in refs:
        v=checked(r);READS[v['path']]=v;result.append(v)
    return result


def declaration(sport,model,training,features,channels,metrics,authority,limits,bindings,horizons):
    return {'schemaVersion':DECLARATION,'sport':sport,'competition':'NCAA Division I FBS' if sport=='CFB' else sport,
        'modelIdentity':model,'training':training,'featureContract':features,'channels':channels,
        'historicalMetrics':metrics,'authority':authority,'limitations':limits,'artifacts':bindings,
        'validForecastHorizons':horizons,'selectionChanged':False,'claimOfProfitability':False}


def mlb(studio,stage):
    base=studio/'outputs/mlb-v18-conditional-champion-v1'
    m=load(base/'champion/sha256'/MLB_MANIFEST/'champion-manifest.json')
    refs=artifacts([m['paArtifact'],m['fittedPreprocessor']['artifact']])
    dep_path=studio/'.runtime/mlb-v18-unattended/deployment.json';dep=load(dep_path)
    state=read(studio/'.runtime/mlb-v18-unattended/state.json');tick=load(state['latestReceipt']['path'])
    checked(state['latestReceipt'])
    if tick['deploymentIdentity']['commit']!=dep['deployed_commit']:raise ValueError('MLB_DEPLOYMENT_BINDING')
    invocation={'receipt':state['latestReceipt'],'status':tick['status'],'completedAt':tick['completedAt']}
    tick_ref=state['latestReceipt']
    if tick['status']=='NOT_DUE_NO_PROVIDER_OR_MODEL_ACTIVITY':
        # A normal no-op invocation is not an owner failure. Keep it alongside
        # the most recent substantive receipt; never restamp that receipt.
        recent=sorted((studio/'outputs/mlb-v18-unattended-v1/objects/sha256').glob('*/tick.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:20]
        match=next((p for p in recent if read(p).get('status')=='BOUNDED_TICK_COMPLETED'),None)
        if match is None:raise ValueError('MLB_SUBSTANTIVE_RECEIPT_UNAVAILABLE')
        tick=load(match);tick_ref=ref(match)
    if tick['status']!='BOUNDED_TICK_COMPLETED':raise ValueError('MLB_NATURAL_TICK_FAILED')
    if tick['deploymentIdentity']['commit']!=dep['deployed_commit']:raise ValueError('MLB_SUBSTANTIVE_DEPLOYMENT_BINDING')
    installed={x['path']:x for x in dep['code_hashes']}
    for name in ['scripts/invoke_mlb_v18_unattended.ps1','scripts/run_mlb_v18_unattended.py',
                 'server/sports_current_statcast/mlb_v18_unattended.py']:
        r=ref(Path(dep['code_root'])/name);expected=installed[name]
        if r['sha256']!=expected['sha256'] or r['bytes']!=expected['bytes']:raise ValueError('MLB_INSTALLED_CODE')
    timing=tick['timingContract']
    for key,expected in [('producerChecksBeginMinutesBeforeStart',60),('producerDeliveryTargetMinutesBeforeStart',45),
                         ('consumerFinalPregameWindowOpensMinutesBeforeStart',30),('consumerDecisionCutoffMinutesBeforeStart',15),
                         ('producerResearchPublicationCutoffMinutesBeforeStart',5)]:
        if timing[key]!=expected:raise ValueError('MLB_TIMING_CONTRACT')
    launches=sorted((studio/'.runtime/mlb-v18-unattended/launcher-receipts').glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    launch=None
    for p in launches[:6]:
        d=load(p)
        if d.get('context',{}).get('details',{}).get('python_exit_code')==0:
            if d['context']['manifest_sha256']!=physical(dep_path)['sha256']:raise ValueError('MLB_LAUNCHER_DEPLOYMENT')
            launch={'receipt':ref(p),'value':d,'qualification':'Most recent retained launcher completion; current natural tick is separately bound.'};break
    operational={'deployment':ref(dep_path),'deployedCommit':dep['deployed_commit'],
        'taskName':dep['task_name'],'logonType':dep['logon_type'],'ownerMarker':dep['owner_marker'],
        'latestInvocation':invocation,'latestNaturalTick':tick_ref,'tickCompletedAt':tick['completedAt'],
        'tickStatus':tick['status'],'launcher':launch,'timingContract':timing,
        'noManualInvocation':True,'stopFilePresent':Path(dep['kill_switch']).exists(),
        'scheduleQualification':'Live task enumeration was inaccessible in the prior read-only recovery check; configured owner and natural receipts are verified, not a new single-task enumeration.',
        'games':[{k:g.get(k) for k in ['gameId','canonicalGameId','mlbamGamePk','scheduledStartUtc','gameDate','status','reason','blockers','checkpoint','awayTeamMlbamId','homeTeamMlbamId']} for g in tick['games']],
        'statusCounts':dict(Counter(g['status'] for g in tick['games']))}
    write(stage/'mlb-operational-evidence.json',operational)
    # Use latest retained ordinary handoff only as an explicitly historical example.
    root=studio/'outputs/mlb-v18-current-state-pipeline-v1'
    candidates=sorted((root/'handoffs/sha256').glob('*/aisp-handoff.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    hp,h=next((p,read(p)) for p in candidates if read(p).get('forecasts'))
    f=max(h['forecasts'],key=lambda x:clock(x['forecastCreatedAt']))
    obj=root/f['relativePath'];forecast=load(obj/'forecast.json');execution=load(obj/'execution-inputs.json')
    manifest=load(obj/'manifest.json')
    for a in manifest['artifacts']:artifacts([{**a,'path':str(obj/a['relativePath'])}])
    s=joint_summary(execution['population']['homeRuns'],execution['population']['awayRuns'])
    if s['drawCount']!=5000:raise ValueError('MLB_UNRESTRICTED_POPULATION')
    for a,b in [('expectedHome','homeRuns'),('expectedAway','awayRuns'),('expectedTotal','totalRuns')]:agree(s[a],forecast['expectations'][b])
    for a,b in [('homeWin','homeWin'),('awayWin','awayWin')]:agree(s[a],forecast['probabilities'][b])
    agree(s['tie'],0)
    if forecast['parentAuthority']['paModelSha256']!=m['modelIdentity']['artifactSha256']:raise ValueError('MLB_PA_IDENTITY')
    if not clock(forecast['capturedAt'])<=clock(forecast['forecastCreatedAt'])<clock(forecast['scheduledStart']):raise ValueError('MLB_CHRONOLOGY')
    for side in ['HOME','AWAY']:
        lineup=forecast['lineupAuthorities'][side]
        if lineup['status']!='CONFIRMED' or not lineup['isComplete']:raise ValueError('MLB_LINEUP')
        for evidence in [lineup,forecast['starters'][side]]:
            for k in ['availableAsOf','ingestedAt','observedAt']:
                if clock(evidence[k])>clock(forecast['capturedAt']):raise ValueError('MLB_INPUT_AFTER_CAPTURE')
    frow={'sport':'MLB','eventId':forecast['gameId'],'providerGameId':forecast['sourceGameId'],
        'forecastId':manifest['objectId'],'objectSha256':manifest['objectSha256'],'horizon':'FINAL_PREGAME',
        'demoState':'HISTORICAL_FROZEN_EXAMPLE_UPCOMING_FINALS_WAIT_FOR_OWNER_INPUTS',
        'away':forecast['teams']['AWAY'],'home':forecast['teams']['HOME'],
        'sourceCutoff':forecast['sourceCutoff'],'createdAtUtc':forecast['forecastCreatedAt'],
        'scheduledStartUtc':clock(forecast['scheduledStart']).isoformat(),
        'originalObject':ref(obj/'manifest.json'),'originalForecast':ref(obj/'forecast.json'),
        'originalHandoff':ref(hp),'numericalVerification':s,
        'lineupStatus':{k:v['status'] for k,v in forecast['lineupAuthorities'].items()},
        'starterStatus':{k:v['confirmationState'] for k,v in forecast['starters'].items()},
        'exchangeVerification':'EXACT_EXCHANGE_PACKAGE_PENDING_ACCESS_OR_BOUND_RECEIPT',
        'publicationClock':None,'consumerUse':'HISTORICAL_DISPLAY_ONLY_THIS_EXAMPLE',
        'marketAuthorityGrantedByRelease':False,'consumerAcknowledgement':None}
    metrics={'basis':'REUSED_HISTORICAL_PA_DIAGNOSTIC_NOT_CERTIFIED_PREGAME_VALIDATION',
        'operationalFold5':{'paCount':101264,'registeredGames':1342,'logLoss':1.470973,'brierSum8Classes':.701268},
        'scoringConvention':'Natural-log PA log loss; summed squared error over eight PA classes, not winner Brier',
        'report':ref(studio/'outputs/mlb-v18-empirical-diagnosis-v1/REPORT.md'),
        'cleanHistoricalValidationEligibleRows':0,'finalOotReadThisRun':False}
    d=declaration('MLB',{'registryModelId':m['modelId'],**m['modelIdentity']},
        {'nominalCutoff':m['trainingIdentity']['nominalTrainingCutoff'],'fitTimestamp':m['trainingIdentity']['originalTrainingTimestamp'],
         'availabilityCertified':False,'operationalFold':m['trainingIdentity']['operationalFold']},
        {k:v for k,v in m['featureContract'].items() if k not in ['rawOrderedFields','encodedOrderedFields','treatedOrderedFields']},
        {'pointAndWinner':'Unrestricted 5000-draw accepted game simulator driven by frozen V18 fold5 PA model; accepted transition fold4.',
         'distribution':'Paired full-game scores including extra innings; no score-limit/survival/transition challenger.',
         'calibration':'Identity; no fitted recalibration enabled'},metrics,
        {'championStatus':'CONDITIONAL_OPERATIONAL_CONTROLLING_FINAL','retainedAuthority':m['authority'],
         'consumerUse':m['wageringAuthority'],'releaseGrantsNoNewAuthority':True},
        [m['historicalIntegrityLimitation'],*forecast['knownLimitations'],'Exact fresh lineups and source evidence remain mandatory; current weekend forecasts cannot be promised.'],
        [ref(base/'champion/sha256'/MLB_MANIFEST/'champion-manifest.json'),*refs],['FINAL_PREGAME'])
    return d,[frow],operational


def nfl(studio,exchange,stage):
    index_path=exchange/'aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json';idx=load(index_path)
    latest={}
    for digest in idx['currentBundleSha256s']:
        p=exchange/'aisp-daily-forecast-bundles/sha256'/digest/'bundle.json';b=read(p)
        for f in b['forecasts']:
            if f['eventId'].startswith('2026_02_') and f['snapshotType']=='CURRENT':
                prev=latest.get(f['eventId'])
                if prev is None or f['snapshotVersion']>prev[1]['snapshotVersion']:latest[f['eventId']]=(p,f)
    si=load(exchange/'nfl-labs-supplements/nfl-labs-supplement-index.json');supplements={}
    for digest in si['currentSupplementSha256s']:
        p=exchange/'nfl-labs-supplements/sha256'/digest;s=load(p/'supplement.json');supplements[s['binding']['forecastId']]=p
    rows=[]
    for p,f in sorted(latest.values(),key=lambda x:x[1]['scheduledStartUtc']):
        if f['forecastId'] not in supplements:raise ValueError('NFL_SUCCESSOR_ELIGIBILITY_MISSING')
        rows.append(audit_nfl(p,f['forecastId'],supplements[f['forecastId']]))
        ref(p);ref(supplements[f['forecastId']]/'manifest.json')
    if len(rows)!=16:raise ValueError('NFL_WEEK2_COHORT')
    modelroot=studio.parent/'asp-data-staging/nfl/m1-modeling-benchmark-v1/research-artifact/objects/sha256'/NFL_MANIFEST
    model=load(modelroot/'manifest.json');binary=checked({'path':str(modelroot/'model.joblib'),
        'sha256':rows[0]['engine']['modelBinarySha256'],'bytes':model['modelArtifact']['byteCount']})
    READS[binary['path']]=binary
    bpath=studio/'outputs/nfl-research-benchmarks-v1/sha256/c48e045a628d4ab8ad6a74b5ccf3a6485ccc6dcedf9f5d948e2267c8d5721bae/scoreboard.json'
    bench=load(bpath);metric=next(x for x in bench['modelBenchmarks'] if x['modelId']=='M1_RECIPE_RAW')
    d=declaration('NFL',rows[0]['engine'],model['training'],
        {'sha256':rows[0]['engine']['featureContractSha256'],'featureCount':model['featureCount'],
         'preprocessing':'Frozen training-only imputation/encoding embedded in model.joblib','modelArtifact':binary},
        {'pointAndWinner':'10000 paired-residual final-score draws; empirical score means and away/tie/home mass.',
         'ties':'Equal retained score pairs; not a validated overtime/tie probability. Paper experiment refunds tie stake.',
         'lineQueries':'Modeled line scenarios are not sportsbook quotes','calibration':model['calibration']},
        {'population':'1408 matched Development events across 2020-2024; recipe/season-forward model versions, not direct validation of all-history refit',
         'metrics':metric,'convention':'Three-way natural-log loss; summed squared error AWAY/TIE/HOME, not MLB binary conversion',
         'report':ref(bpath),'qualifiedAfterSelection':True},
        {'championStatus':'CURRENT_RESEARCH_PAPER_CHAMPION','researchOnly':True,
         'permittedConsumerUse':'Existing exact-forecast NFL virtual-paper supplements; all consumer timing/quote/policy gates still apply',
         'realMoney':False,'releaseGrantsNoNewAuthority':True},
        ['No validated-champion or profitability claim.','Inherited finalized-source vintage limitations.',
         'Player/injury/QB availability not certified; frozen missing-feature imputation is explicit per forecast.',
         'A later revision needs its own eligibility supplement; old creation time is preserved on exact reuse.'],
        [ref(modelroot/'manifest.json'),binary,ref(index_path)],['EARLY','CURRENT','FINAL_PREGAME','SHOW_PREVIEW_DERIVED_ARTIFACT_ONLY'])
    write(stage/'nfl-week2-audit.json',rows)
    return d,rows


def nba(studio,exchange,stage):
    import pandas as pd
    import numpy as np
    pp=exchange/'nba-gen1-research-v1/point-elo-v1/packages/sha256'/NBA_POINT
    jp=exchange/'nba-gen1-research-v1/joint-comparison-v1/packages/sha256'/NBA_JOINT
    pi,pv=verify_index_package(pp);ji,jv=verify_index_package(jp)
    f=load(pp/'forecast.json');j=load(jp/'forecasts/baseline.json')
    df=pd.read_parquet(jp/'populations/baseline-joint-draws.parquet')
    home='homeDET';away='awayBOS'
    s=joint_summary(df[home],df[away]);sim=j['jointSimulation']
    for a,b in [('expectedHome','homeDET'),('expectedAway','awayBOS'),('expectedTotal','total')]:agree(s[a],sim['expectedScores'][b])
    for a,b in [('homeWin','homeDET'),('awayWin','awayBOS'),('tie','tie')]:agree(s[a],sim['winnerProbabilities'][b])
    if s['drawCount']!=10000 or s['tie']!=0:raise ValueError('NBA_DRAW_SUPPORT')
    artifact=load(studio/'outputs/nba-gen1-long-gap-v1/current-research/receipt.json')
    refs=artifacts([artifact['models'][k]['artifact'] for k in ['elo','ridge_a100_rest']])
    pointmetrics=load(studio/'outputs/nba-gen1-long-gap-v1/assessment-2026/assessment.json')
    jointmetrics=load(studio/'outputs/nba-gen1-joint-residual-v1/assessment.json')
    metrics={'qualification':'Reused finalized-record historical evidence, not prospective performance.',
        'pointElo2025_26':next(x for x in pointmetrics['bySeason'] if x['modelId']=='ridge_a100_rest'),
        'pairedJoint7009Games':jointmetrics['groups']['all']['paired'],
        'conventions':'Binary home-win Brier (p-y)^2; natural-log winner loss; energy/CRPS in points.',
        'assessmentFiles':[ref(studio/'outputs/nba-gen1-long-gap-v1/assessment-2026/assessment.json'),ref(studio/'outputs/nba-gen1-joint-residual-v1/assessment.json')]}
    d=declaration('NBA',{'configuration':'NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1',
        'jointConfiguration':j['configurationIdentity'],'closeScoreCorrection':'RETAINED_SEPARATE_RESEARCH_ARM_NOT_SELECTED'},
        {'lastGameDate':artifact['latestRecordedGameDate'],'seasonEnd':2026,'trainingGames':artifact['trainingGames'],'evidenceClass':artifact['evidenceClass']},
        {'featureCount':78,'sha256':pi['originalModelInputBindings']['featureContractSha256'],
         'preprocessing':'Training-only ordinary-rest support, median imputation and scaler embedded in Ridge artifact'},
        {'expectedPoints':'Corrected Ridge alpha100','winner':'Chronological Elo, independently estimated',
         'joint':'10000 pooled paired chronological OOF-residual draws around Ridge, with explicit final lattice support.',
         'jointWinner':'Derived from separate joint population; do not overwrite Elo or imply equality.',
         'pointDrawCount':0,'distributionDrawCount':10000},metrics,
        {'championStatus':'CURRENT_RESEARCH_BASELINE','researchOnly':True,'permittedConsumerUse':'Early research display and illustrative distribution queries only',
         'wagering':False,'releaseGrantsNoNewAuthority':True},
        ['Regular season inactive during demo; BOS-DET is an early captured October schedule, not live or final.',
         'No player/lineup/injury information; unsupported rest unavailable rather than fabricated.',
         'One-point margin mass too high; close-score arm not promoted. Low-total tail and opener calibration weaknesses remain.',
         'Joint means differ slightly from Ridge points; empirical donors do not certify unseen extremes.'],
        [*refs,ref(studio/'outputs/nba-gen1-joint-residual-v1/method-freeze.json'),ref(studio/'outputs/nba-gen1-joint-residual-v1/residual-provenance.json')],
        ['EARLY_RESEARCH_POINT_ELO','PROSPECTIVE_JOINT_RESEARCH','SHOW_PREVIEW_DERIVED_ARTIFACT_ONLY'])
    rows=[]
    for label,forecast,pkg,verification in [('POINT_ELO',f,pp,pv),('JOINT_BASELINE',j,jp,jv)]:
        pub=load(pkg/'publication-receipt.json')
        clocks=chronology(forecast['sourceCutoffUtc'],forecast['createdAtUtc'],pub['publishedAtUtc'],forecast['game']['scheduled_tipoff_utc'])
        rows.append({'sport':'NBA','eventId':forecast['game']['game_id'],'providerGameId':401909088,
            'forecastId':forecast['forecastId'],'horizon':'EARLY_RESEARCH_'+label,'clocks':clocks,
            'away':'BOS','home':'DET','package':verification['index'],'packageVerification':verification,
            'channels':{'ridge':j['ridgePointExpectations'],'elo':j['separateEloProbabilities'],'joint':s if label=='JOINT_BASELINE' else None},
            'drawCount':0 if label=='POINT_ELO' else 10000,'consumerUse':'SEASON_INACTIVE_EARLY_RESEARCH_DISPLAY',
            'marketAuthorityGrantedByRelease':False,'consumerAcknowledgement':None})
    ack=pp.parent.parent.parent/'consumer-receipts/aisp-consumer-receipt-85e3d741.json'
    if ack.exists():rows[0]['consumerAcknowledgement']={'receipt':ref(ack),'details':load(ack),'scope':'PRIOR_POINT_PACKAGE_ONLY_NOT_THIS_RELEASE'}
    write(stage/'nba-package-audit.json',rows)
    return d,rows


def cfb(studio,exchange,cfb_dir,stage):
    import pandas as pd
    f=load(cfb_dir/'forecast.json');draws=pd.read_parquet(cfb_dir/'baseline-joint-draws.parquet');s=joint_summary(draws.home_score,draws.away_score)
    b=f['baseline'];agree(s['homeWin'],b['jointHomeWinProbability'])
    if s['drawCount']!=b['drawCount'] or s['tie']!=0:raise ValueError('CFB_POPULATION')
    refs=artifacts([f['modelBindings'][k] for k in ['selectedModel','developmentCalibrator','featureContract','pairedResidualPopulation']])
    hist=studio/'outputs/cfb-gen1-v1';selection=load(hist/'selected-configuration-receipt.json');holdout=load(hist/'holdout-results.json');dist=load(hist/'distribution-assessment.json')
    d=declaration('CFB',{'point':'CFB_GEN1_RIDGE_A100','configuration':b['configuration'],
        'elo':'CHRONOLOGICAL_ELO','challengers':'CLUSTER_AND_GAP_NOT_PROMOTED'},
        {'throughSeason':2025,'currentInputCutoff':f['sourceCutoff'],'historicalPartition':load(hist/'chronological-partition-receipt.json')},
        {'featureCount':35,'artifact':refs[2],'preprocessing':'Frozen fitted imputation/scaling in selected model; Development-only logistic margin calibrator'},
        {'expectedPoints':'Ridge alpha100','winner':'Development-calibrated Ridge margin',
         'separateElo':'Chronological Elo benchmark; not joint winner probability',
         'distribution':'10000 paired earlier OOF residuals; nonnegative stochastic integer support and tied-final resampling',
         'jointWinner':'Count-based separate channel','modeledTotal':'Full final including overtime'},
        {'validation':next(x for x in selection['candidateRows'] if x['model']=='ridge_alpha100'),
         'reused2025':next(x for x in holdout['scores'] if x['model']=='ridge_alpha100'),
         'distribution2025':dist['groups']['bySeason']['2025'],
         'conventions':'Binary home Brier (p-y)^2; natural-log winner loss; energy/CRPS/MAE points',
         'qualification':holdout['qualification'],'reports':[ref(hist/'selected-configuration-receipt.json'),ref(hist/'holdout-results.json'),ref(hist/'distribution-assessment.json')]},
        {'championStatus':'CURRENT_RESEARCH_BASELINE','researchOnly':True,'permittedConsumerUse':'Research display, illustrative line queries; no wagering authority',
         'releaseGrantsNoNewAuthority':True},f['limitations'],refs,['PROSPECTIVE_RESEARCH','SHOW_PREVIEW_DERIVED_ARTIFACT_ONLY'])
    # The existing CFB physical-index contract, new immutable package only.
    files=[{'path':name,'bytes':ref(cfb_dir/name)['bytes'],'physicalSha256':ref(cfb_dir/name)['sha256']}
           for name in ['forecast.json','baseline-joint-draws.parquet','baseline-pmfs.parquet','target-selection.json']]
    index={'schemaVersion':'CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1','forecastId':f['forecastId'],
        'gameId':f['game']['game_id'],'files':files,'researchOnly':True,'aispAuthority':False,'wageringAuthority':False,
        'rawProviderResponsesIncluded':False,'sourceCutoff':f['sourceCutoff'],
        'currentPointerNotReplaced':True,'createdAt':now()}
    # A completed stage is reused on retry; its publication clock never changes.
    local=stage.parent/'cfb-package'
    if not (local/'index.json').exists():
        local.mkdir(exist_ok=True)
        for item in files:shutil.copyfile(cfb_dir/item['path'],local/item['path'])
        write(local/'index.json',index)
    else:index=read(local/'index.json')
    digest=sha((local/'index.json').read_bytes())
    destination=exchange/'cfb-gen1-research-v1/current-v1/packages/sha256'/digest
    row={'sport':'CFB','eventId':'cfbd:'+str(f['game']['game_id']),'providerGameId':f['game']['game_id'],
        'forecastId':f['forecastId'],'horizon':'PROSPECTIVE_RESEARCH','game':f['game'],
        'sourceCutoffUtc':f['sourceCutoff'],'createdAtUtc':f['createdAt'],'publicationClock':None,
        'intendedPackage':str(destination),'packageIndexSha256':digest,'localPackage':str(local),
        'channels':{k:b[k] for k in ['expectedAwayPoints','expectedHomePoints','ridgeHomeWinProbability','eloHomeWinProbability','jointHomeWinProbability']},
        'numericalVerification':s,'consumerUse':'RESEARCH_DISPLAY_ONLY','consumerGameBinding':'PENDING_EXACT_CFBD_ID_BINDING',
        'marketAuthorityGrantedByRelease':False,'consumerAcknowledgement':None}
    return d,[row]


def build(studio,exchange,out,cfb_dir):
    stage=out/'release-stage';stage.mkdir(parents=True,exist_ok=True)
    champions=[];forecasts=[]
    d,rows,op=mlb(studio,stage);champions.append(d);forecasts+=rows
    d,rows=nfl(studio,exchange,stage);champions.append(d);forecasts+=rows
    d,rows=nba(studio,exchange,stage);champions.append(d);forecasts+=rows
    d,rows=cfb(studio,exchange,cfb_dir,stage);champions.append(d);forecasts+=rows
    preview_index=load(exchange/'show-preview-forecasts-v1/discovery.json')
    preview={'discovery':ref(exchange/'show-preview-forecasts-v1/discovery.json'),
        'packages':preview_index['packages'],'consumerUse':'EDITORIAL_ONLY','notFinalPregame':True,
        'scope':'Existing 17 NFL/CFB wrappers; not recreated or relabeled by this release.'}
    write(stage/'show-preview-references.json',preview)
    for c in champions:write(stage/'champions'/f"{c['sport']}.json",c)
    release={'schemaVersion':SCHEMA,'createdAtUtc':now(),'weekendEastern':['2026-09-19','2026-09-20'],
        'sourceBranch':'codex/scotty-demo-model-readiness-v1','sourceBase':'8067db9f338fde006e2f95ed92646457ab567f69',
        'champions':champions,'forecasts':forecasts,'showPreview':preview,
        'authority':{'modelPromotion':False,'wagering':False,'positions':False,'schedulerActivation':False,'aispWrites':False},
        'verificationScope':'Bounded retained-model/package audit. No model-selection rerun, target outcomes, sealed payloads, provider calls or consumer writes.',
        'consumerAcknowledgement':None,'mlbOperationalEvidence':physical(stage/'mlb-operational-evidence.json')}
    validate_release(release);write(stage/'release.json',release)
    write(stage/'source-bindings.json',{'files':list(READS.values()),'externalDependenciesRemainExternal':True})
    print(json.dumps({'stage':str(stage),'champions':len(champions),'forecastRows':len(forecasts),'mlbTick':op['tickCompletedAt']}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--studio',type=Path,required=True);p.add_argument('--exchange',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--cfb',type=Path,required=True)
    a=p.parse_args();build(a.studio,a.exchange,a.output,a.cfb)
