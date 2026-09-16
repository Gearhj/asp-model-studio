"""Passive diagnostics on exact frozen V18 inputs; never creates a model forecast."""
from datetime import datetime, timezone
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from threadpoolctl import threadpool_limits
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline
from scripts.run_mlb_v18_three_arm_pregame_v1 import shared_provider
from server.sports_current_statcast.mlb_v18_current_publication import CurrentV18Engine
from server.sports_current_statcast.mlb_v18_whole_game_challenger import simulate_prospective_game
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask, LEDGER
from server.sports_silver.canonical_ids import canonical_game_id

OUT=ROOT/'outputs/mlb-v18-population-diagnostics-v1'
CORE=ROOT/'server/sports_current_statcast/mlb_v18_whole_game_challenger.py'
CORE_SHA='d9e5151141c697d6d8080e47c3c50ebfc5297764155a7f16de455152939bcac7'
COLLECTOR=ROOT/'server/sports_current_statcast/mlb_v18_population_diagnostics.py'
ORIGINAL=ROOT/'outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-declaration.json'
CASES=('824630','823496','824870')
FIELDS=('homeRuns','awayRuns','innings','paCounts')
CATEGORIES=['CompletedPA by batting team/inning','Eight sampled PA classes by team/inning',
    'Eight probability sums conditional on simulated exposures','StarterBF and hook removal point/reason',
    'Anonymous reliefBF','Runs by team/inning','Aggregate base/out transitions and multiple-out PA proxy',
    'Third-out stranded runners; walkoff remnants separately','NonPA coverage and automatic extra-inning runner placements']


def now():return datetime.now(timezone.utc)
def utc(value):return datetime.fromisoformat(str(value).replace('Z','+00:00')).astimezone(timezone.utc)
def ref(path):
    p=Path(path).resolve();b=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read_ref(r):
    assert ref(r['path'])=={k:r[k] for k in ('path','sha256','bytes')},'CHECKSUM_MISMATCH'
    return json.loads(Path(r['path']).read_bytes())
def save(name,value):
    raw=value if isinstance(value,bytes) else (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
    digest=hashlib.sha256(raw).hexdigest();p=OUT/'objects/sha256'/digest/name;p.parent.mkdir(parents=True,exist_ok=True)
    if p.exists():assert p.read_bytes()==raw
    else:p.write_bytes(raw)
    return ref(p)
def pointer(name,r):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(r,indent=2)+'\n').encode()
    if p.exists():assert p.read_bytes()==raw,'EXISTING_DIAGNOSTIC_PRESERVED'
    else:p.write_bytes(raw)
def guard(gid,pk):
    assert all(final_oot_eligible_key_mask([gid,str(pk),canonical_game_id(int(pk))])),'WHOLE_GAME_QUARANTINE'
def core_check():assert ref(CORE)['sha256']==CORE_SHA,'FROZEN_SIMULATOR_CHANGED'


def require_gate(gate, bindings):
    assert gate['passed'] and gate['simulationsPerRun']==5000,'INVARIANCE_GATE_NOT_PASSED'
    prior=read_ref(gate['sidecar'])
    for role in ('collector','simulator'):
        assert all(prior[role][k]==bindings[role][k] for k in ('sha256','bytes')), 'INVARIANCE_IMPLEMENTATION_DIFFERS'


def declare():
    p=OUT/'declaration.json'
    if p.exists():return json.loads(p.read_bytes())
    core_check();d=json.loads(ORIGINAL.read_bytes());selected={r['sourceGameId']:r for r in d['games'] if r['sourceGameId'] in CASES}
    assert set(selected)==set(CASES)
    for r in selected.values():guard(r['gameId'],r['sourceGameId'])
    result={'schemaVersion':'MLB_V18_PASSIVE_POPULATION_DIAGNOSTIC_DECLARATION_V1',
        'declaredAtUtc':now().isoformat(),'branch':subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
        'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'existingTrackedDirtyFiles':subprocess.check_output(['git','diff','--name-only'],cwd=ROOT,text=True).splitlines(),
        'originalDeclaration':ref(ORIGINAL),'quarantine':ref(LEDGER),'frozenSimulator':ref(CORE),
        'cases':[selected[k] for k in CASES],'invarianceCase':'824630','simulationsPerRun':5000,
        'selection':'Explicit user-selected explanation cases after observed results, not independent validation.',
        'categories':CATEGORIES,'counterVersion':'MLB_V18_PASSIVE_POPULATION_DIAGNOSTICS_V1',
        'comparisons':['CompletedPA and observed eight-class events when definitions match','Starter/anonymous reliefBF','Inning scoring and supported aggregate transition/LOB measures'],
        'probabilitySumsMeaning':'Conditional on hypothetical simulated exposures, not probabilities captured before actual observed PAs.',
        'invarianceRule':'Counter-disabled and counter-enabled5000 draws on PIT must equal each other and original immutable arrays. Each later enabled run must equal its original immutable arrays and distributions.',
        'limits':{'fits':0,'calibrationChanges':0,'providerRequests':0,'productionAuthority':False,'mechanicsChanges':False},
        'driver':ref(__file__)}
    OUT.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    return result


def declare_future(object_sha):
    core_check();b=load_baseline(object_sha);f=b['forecast'];guard(f['gameId'],f['sourceGameId'])
    assert str(f['sourceGameId'])!='824225','COMPLETED_COL_DET_PUBLICATION_PRESERVED'
    from datetime import timedelta
    cutoff=utc(f['scheduledStart'])-timedelta(minutes=15)
    assert now()<cutoff,'FUTURE_CUTOFF_EXPIRED'
    r={'schemaVersion':'MLB_V18_ONE_FUTURE_PASSIVE_DIAGNOSTIC_CAPTURE_V1','declaredAtUtc':now().isoformat(),
       'gameId':f['gameId'],'sourceGameId':str(f['sourceGameId']),'teams':f['teams'],'baselineObjectSha256':object_sha,
       'baselineForecastId':'mlb-v18-daily-'+object_sha,'forecast':ref(b['directory']/'forecast.json'),
       'executionInputs':ref(b['directory']/'execution-inputs.json'),'scheduledStartUtc':utc(f['scheduledStart']).isoformat(),
       'deadlineUtc':cutoff.isoformat(),'originalCaptureUtc':f['capturedAt'],'originalForecastCreatedAt':f['forecastCreatedAt'],
       'categories':CATEGORIES,'simulationCount':5000,'masterSeed':f['simulation']['seed'],
       'selection':'One already eligible immutable ordinary baseline, selected before outcomes. No new scheduler or changed forecast.',
       'outcomesRead':False,'mechanicsChanges':False,'candidateAuthority':False,
       'stoppingRule':'Exactly this baseline and game. Stop at original cutoff; do not substitute later inputs or extend deadline.'}
    descriptor=save('future-declaration.json',r);pointer('future-declaration.json',descriptor);return descriptor


def compare_population(actual,expected):
    checks={k:bool(np.array_equal(np.asarray(actual[k]),np.asarray(expected[k]))) for k in FIELDS}
    scalar_checks={k:bool(actual[k]==expected[k]) for k in expected if k not in FIELDS and k not in ('traces','schemaVersion','gameId') and isinstance(expected[k],(int,float,bool))}
    traces=actual['traces']==expected['traces']
    assert all(checks.values()) and all(scalar_checks.values()) and traces,'NUMERICAL_FORECAST_INVARIANCE_FAILED'
    return {'drawArraysExact':checks,'summaryScalarsExact':scalar_checks,'representativeTraceExact':traces,
            'mismatchedDraws':0,'maximumAbsoluteDrawDifference':0}


def run(pk=None,future=False):
    declaration=declare();core_check()
    if future:
        fd=read_ref(json.loads((OUT/'future-declaration.json').read_bytes()))
        pk=fd['sourceGameId'];object_sha=fd['baselineObjectSha256']
    else:
        row=next(r for r in declaration['cases'] if r['sourceGameId']==pk);object_sha=row['objectSha256'];fd=None
    destination=f"{'future' if future else 'retrospective'}/{pk}/current.json"
    if (OUT/destination).exists():return {'reused':True,'sidecar':json.loads((OUT/destination).read_bytes())}
    if future:assert now()<utc(fd['deadlineUtc']),'FUTURE_DEADLINE_EXPIRED_NO_CAPTURE'
    bindings={'driver':ref(__file__),'collector':ref(COLLECTOR),'simulator':ref(CORE)}
    if pk!=declaration['invarianceCase'] or future:
        gate=read_ref(json.loads((OUT/'invariance.json').read_bytes()));require_gate(gate,bindings)
    from scripts.seal_mlb_v18_population_diagnostics_v1 import archive_source
    source_archives=[archive_source(role,descriptor) for role,descriptor in bindings.items()]
    from server.sports_current_statcast.mlb_v18_population_diagnostics import PopulationDiagnostics
    b=load_baseline(object_sha);f=b['forecast'];guard(f['gameId'],f['sourceGameId'])
    started=now();clock=time.perf_counter()
    def progress(stage):print(json.dumps({'stage':stage,'sourceGameId':pk,'elapsedSeconds':round(time.perf_counter()-clock,2)}),flush=True)
    progress('LOADING_EXACT_FROZEN_PROVIDER')
    with threadpool_limits(limits=4):
        engine=CurrentV18Engine()
        if future:
            provider,reload=shared_provider(engine,b)
        else:
            from server.sports_current_statcast.mlb_v18_ensemble_candidate import build_saved_historical_replay_provider
            feature_ref=b['execution']['featureSnapshot']
            composition=read_ref(feature_ref)['composition']
            assert b['execution']['sourceCutoff']==f['sourceCutoff']==composition['sourceCutoff']
            provider,reload=build_saved_historical_replay_provider(
                engine,b['snapshot'],composition,b['execution'],snapshot_sha256=feature_ref['sha256'],
                original_forecast_created_at=f['forecastCreatedAt'])
        kwargs={'game_id':f['gameId'],'transition_model':engine.transition,'n_sims':5000,
                'master_seed':f['simulation']['seed'],'regulation':int(b['snapshot']['game'].get('scheduled_innings') or 9),'trace_count':1}
        disabled=None
        if pk==declaration['invarianceCase'] and not future:
            progress('COUNTERS_DISABLED_5000')
            disabled=simulate_prospective_game(provider=provider,**kwargs)
            disabled_check=compare_population(disabled,b['baseline']);progress('DISABLED_EXACT_ORIGINAL_MATCH')
        collector=PopulationDiagnostics(5000,regulation=kwargs['regulation'])
        progress('COUNTERS_ENABLED_5000')
        enabled=simulate_prospective_game(provider=collector.wrap_provider(provider),event_observer=collector,**kwargs)
        invariant=compare_population(enabled,b['baseline'])
        if disabled is not None:compare_population(enabled,disabled)
        arrays,metadata=collector.finalize(enabled)
        progress('INVARIANCE_AND_ACCOUNTING_PASSED')
    for descriptor in bindings.values():
        assert ref(descriptor['path'])==descriptor,'EXECUTION_SOURCE_CHANGED_DURING_RUN'
    if future:assert now()<utc(fd['deadlineUtc']),'FUTURE_CAPTURE_EXPIRED_DURING_EXECUTION'
    stream=io.BytesIO();np.savez_compressed(stream,**arrays)
    arrays_ref=save('population-diagnostics.npz',stream.getvalue())
    created=now()
    if future:assert created<utc(fd['deadlineUtc']),'FUTURE_ARRAY_PERSISTENCE_EXPIRED'
    result={'schemaVersion':'MLB_V18_POPULATION_DIAGNOSTIC_SIDECAR_V1','createdAtUtc':created.isoformat(),'executionStartedAtUtc':started.isoformat(),
       'classification':'PROSPECTIVE_PREGAME_DIAGNOSTIC_CAPTURE' if future else 'RETROSPECTIVE_REPRODUCTION_AFTER_OBSERVED_RESULTS',
       'gameId':f['gameId'],'sourceGameId':pk,'baselineForecastId':'mlb-v18-daily-'+object_sha,'baselineObjectSha256':object_sha,
       'forecast':ref(b['directory']/'forecast.json'),'executionInputs':ref(b['directory']/'execution-inputs.json'),
       'featureSnapshot':b['execution']['featureSnapshot'],'originalSourceCutoff':f['sourceCutoff'],
       'originalCaptureUtc':f['capturedAt'],'originalForecastCreatedAtUtc':f['forecastCreatedAt'],
       'scheduledStartUtc':utc(f['scheduledStart']).isoformat(),'newForecastCreated':False,'originalForecastModified':False,
       'futureDeclaration':json.loads((OUT/'future-declaration.json').read_bytes()) if future else None,
       'declaration':ref(OUT/'declaration.json'),'simulationConfiguration':kwargs|{'transition_model':engine.model_identity['transitionArtifact']},
       'simulator':bindings['simulator'],'collector':bindings['collector'],
       'driver':bindings['driver'],'executionSourceArchives':source_archives,
       'providerReload':reload,'population':arrays_ref,'counters':metadata,
       'invariance':invariant,'runtimeSeconds':time.perf_counter()-clock,'fits':0,'providerRequests':0,
       'candidateAuthority':False,'productionAuthority':False,'calibrationChanges':False,
       'limitations':['Anonymous team/staff relief templates only','Probability sums are conditional on simulated paths, not actual-PA captures',
                       'Retrospective selected cases provide explanation, not independent confirmation']}
    descriptor=save('diagnostic-sidecar.json',result)
    if future:assert now()<utc(fd['deadlineUtc']),'FUTURE_RAW_SIDECAR_PERSISTENCE_EXPIRED'
    pointer(destination,descriptor)
    if disabled is not None:
        gate=save('invariance.json',{'passed':True,'sourceGameId':pk,'counterDisabledVsOriginal':disabled_check,
             'counterEnabledVsOriginal':invariant,'counterEnabledVsDisabledExact':True,'sidecar':descriptor,'simulationsPerRun':5000,
             'additionalRandomDraws':0,'frozenSimulatorSourceUnchanged':ref(CORE)['sha256']==CORE_SHA})
        pointer('invariance.json',gate)
    return {'sidecar':descriptor,'arrays':arrays_ref,'classification':result['classification'],'invariance':invariant}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('declare');f=sub.add_parser('declare-future');f.add_argument('--baseline',required=True)
    r=sub.add_parser('run');selection=r.add_mutually_exclusive_group(required=True)
    selection.add_argument('--game',choices=CASES);selection.add_argument('--future',action='store_true')
    args=p.parse_args()
    result=declare() if args.command=='declare' else declare_future(args.baseline) if args.command=='declare-future' else run(args.game,args.future)
    if args.command=='run':
        from scripts.seal_mlb_v18_population_diagnostics_v1 import seal
        pk=read_ref(result['sidecar'])['sourceGameId']
        result['sealed']=seal(pk,args.future)
    print(json.dumps(result,indent=2),flush=True)
