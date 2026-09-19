"""Private replay implementation v2: lossless arrays and authenticated resume.

Preserves the original v1 driver and frozen scientific design. No changed models.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE))
RUNTIME=Path(r'C:\Users\james\asp-model-studio')
OUT=RUNTIME/'outputs/mlb-v18-instrumented-replay-20260919-v1'
PRIOR=RUNTIME/'outputs/mlb-v18-score-distribution-diagnosis-20260919-v1'
TABLE=PRIOR/'game_results.csv'
TABLE_SHA='fd3223d32b7b7df332c21a42927fab556bb05e0be9084293cf95101a622aa7cd'
from server.sports_current_statcast import mlb_starter_duration_quarantine as quarantine
from server.sports_current_statcast import mlb_v18_whole_game_challenger as core
from server.sports_current_statcast import mlb_v18_current_publication as publication
from server.sports_current_statcast import mlb_v18_current_slate as slate
from server.sports_current_statcast.mlb_v18_ensemble_candidate import build_saved_historical_replay_provider
from scripts.mlb_v18_replay_instrumentation import ReplayDiagnostics,RNGStreamAudit,compact_draw_records

def now():return datetime.now(timezone.utc).isoformat()
def ref(path):
    p=Path(path).resolve();b=p.read_bytes()
    return dict(path=str(p),sha256=hashlib.sha256(b).hexdigest(),bytes=len(b))
def write(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    def native(x):
        if isinstance(x,np.ndarray):return x.tolist()
        if isinstance(x,np.generic):return x.item()
        if isinstance(x,Path):return str(x)
        raise TypeError(type(x).__name__)
    p.write_text(json.dumps(obj,indent=2,allow_nan=False,default=native)+'\n',encoding='utf-8')
def read_ref(r):
    if any(ref(r['path'])[k]!=r[k] for k in ('sha256','bytes')):raise ValueError('SOURCE_HASH_MISMATCH')
    return json.loads(Path(r['path']).read_bytes())
def guard():
    quarantine.LEDGER=RUNTIME/'server/artifacts/governance/mlb-final-oot-quarantine-v1.json'
    quarantine.LEDGER_ARCHIVE=quarantine.LEDGER.parent/'mlb-final-oot-quarantine-history/sha256'
    if ref(TABLE)['sha256']!=TABLE_SHA:raise ValueError('REUSED_COHORT_CHANGED')
    cols=['game_id','source_game_id','forecast_object_sha256','local_game_date','selected','uncertainty_defect_selection','v18_margin','v18_total','home_team','away_team']
    d=pd.read_csv(TABLE,usecols=cols)
    for col in ['game_id','source_game_id']:
        if not all(quarantine.final_oot_eligible_key_mask(d[col].astype(str).tolist())):raise ValueError('QUARANTINED_IDENTITY')
    if not d.local_game_date.between('2026-09-10','2026-09-17').all() or len(d)!=90:raise ValueError('MATURE_SCOPE_CHANGED')
    return d

def declare():
    d=guard();OUT.mkdir(parents=True,exist_ok=True)
    existing=OUT/'DESIGN.json'
    if existing.exists():return json.loads(existing.read_bytes())
    selected=[]
    groups={'NONSELECTED':~d.selected,'SELECTED_ORIGINAL_MAPPING':d.selected&~d.uncertainty_defect_selection,'SELECTED_UNCERTAINTY_MAPPING':d.uncertainty_defect_selection}
    for name,mask in groups.items():
        g=d.loc[mask].sort_values(['v18_margin','source_game_id']).reset_index(drop=True)
        for q in [.25,.75]:
            row=g.iloc[int(np.floor((len(g)-1)*q))].to_dict()
            row.update(replay_stratum=name,within_stratum_margin_quantile=q)
            selected.append(row)
    core_ref=ref(SOURCE/'server/sports_current_statcast/mlb_v18_whole_game_challenger.py')
    runtime_core=RUNTIME/'server/sports_current_statcast/mlb_v18_whole_game_challenger.py'
    if (SOURCE/'server/sports_current_statcast/mlb_v18_whole_game_challenger.py').read_text()!=runtime_core.read_text():raise ValueError('REPLAY_CORE_NOT_RETAINED_CORE')
    result={'schemaVersion':'MLB_V18_INSTRUMENTED_REPLAY_DESIGN_V1','declaredAtUtc':now(),
      'classification':'EXPLORATORY_DEVELOPMENT_ON_PREVIOUSLY_INSPECTED_OUTCOMES_NOT_VALIDATION',
      'sourceTable':ref(TABLE),'quarantine':ref(quarantine.LEDGER),'identityEligibleGames':90,'wholeGameExclusionsInThisCohort':0,
      'sealedAugustPayloadOpened':False,'fullCohortSelected':31,'fullCohortUncertaintyMappingCases':7,
      'selection':'Six cases: signed predicted-margin 25th and 75th order-statistic positions within nonselected, selected ordinary mapping, selected uncertainty-mapping strata. Stable source-ID tie break. No outcomes used in subset selection.',
      'cases':selected,'drawsPerGame':5000,'fits':0,'providerRequests':0,'threadLimit':2,
      'baselineCore':core_ref,'retainedCore':ref(runtime_core),'coreTextIdenticalLineEndingsOnly':True,
      'invariance':'All six instrumented arrays/scalars/traces must equal exact originals; first case in each stratum additionally counter-disabled vs enabled and all three RNG stream calls, value counts, initial/final states.',
      'candidate':'ONE terminal-credit sensitivity: only terminal non-HOME_RUN walkoff credit is limited to winning run; preserve every HOME_RUN in full. Keep sampled transition separately. Not an official-rules certification; inside-park/over-fence, touches, awards and force/time play details are absent.',
      'candidateChoiceBasis':'Localized retained source and outcome-free synthetic tied-game loaded-base double: raw 2 runs are credited before walkoff termination. No historical score/profit tuning.',
      'candidateInvariants':['Winner indicators','PA and inning counts','All RNG streams','All nonterminal paths','Away scores','Home-run terminal credits'],
      'comparison':['winner log loss','winner Brier','margin CRPS','total CRPS','joint energy score','score/margin/total MAE and bias'],
      'uncertainty':'Paired games and whole local dates; six purposively stratified cases are not a representative generalization estimate. No uncertainty across simulation draws.',
      'missingAttribution':['Actual PA-probability captures','Within-play scoring order/force-outs','Inherited runner identity/responsibility','Reliever identity/availability','Player fatigue and actual hook causality'],
      'noProductionChanges':True,'noEarlyFrozenAssessments':True,'noParameterSearch':True,
      'reusedHistoricalReplaySources':[ref(SOURCE/'server/sports_current_statcast'/f) for f in ['mlb_v18_ensemble_candidate.py','mlb_v18_prospective_transform.py']],
      'reusedCounterSource':ref(SOURCE/'server/sports_current_statcast/mlb_v18_population_diagnostics.py')}
    write(existing,result)
    write(OUT/'IDENTITY_GATE.json',{'checkedAtUtc':now(),'quarantine':result['quarantine'],'cohort':d[['game_id','source_game_id','local_game_date']].to_dict('records'),'removed':[],'AugustPayloadsOpened':False})
    print(json.dumps({'stage':'DECLARED','cases':[(r['source_game_id'],r['replay_stratum']) for r in selected]}),flush=True)
    return result

def compare(actual,expected):
    arrays={k:bool(np.array_equal(actual[k],expected[k])) for k in ['homeRuns','awayRuns','innings','paCounts']}
    scalars={k:bool(actual[k]==v) for k,v in expected.items() if isinstance(v,(int,float,bool))}
    trace=actual['traces']==expected['traces']
    if not all(arrays.values()) or not all(scalars.values()) or not trace:raise ValueError('ORIGINAL_REPRODUCTION_FAILED')
    return {'arrays':arrays,'scalars':scalars,'trace':trace}

def load_case(row):
    from scripts import run_mlb_v18_transition_shrinkage_v1 as reused
    reused.OBJECTS=RUNTIME/'outputs/mlb-v18-current-state-pipeline-v1/objects/sha256'
    return reused.load_baseline(row['forecast_object_sha256'])

def run(only=None,candidate=False):
    design=declare();publication.ROOT=RUNTIME;slate.ROOT=RUNTIME
    sources=[ref(__file__),ref(SOURCE/'scripts/mlb_v18_replay_instrumentation.py'),design['baselineCore'],design['reusedCounterSource'],*design['reusedHistoricalReplaySources']]
    def validate_sources():
        for s in sources:
            if ref(s['path'])!=s:raise ValueError('SOURCE_BINDING_CHANGED')
    validate_sources()
    if candidate:
        from scripts.mlb_v18_walkoff_experiment import build_terminal_credit_simulator
        candidate_fn,candidate_binding=build_terminal_credit_simulator(core)
        sources.append(ref(SOURCE/'scripts/mlb_v18_walkoff_experiment.py'))
    with threadpool_limits(limits=2):
        engine=publication.CurrentV18Engine()
        for i,row in enumerate(design['cases']):
            pk=str(row['source_game_id'])
            if only and pk!=str(only):continue
            folder=OUT/'games'/pk;folder.mkdir(parents=True,exist_ok=True)
            done=folder/('COMPARISON_RUN.json' if candidate else 'REPLAY.json')
            if done.exists():
                saved=json.loads(done.read_bytes())
                if saved['case']!=row:raise ValueError('RESUME_CASE_MISMATCH')
                for key in (['candidate','baselineInput'] if candidate else ['input','forecast','diagnostics','drawSummaries']):
                    r=saved[key]
                    if ref(r['path'])!=r:raise ValueError('RESUME_OUTPUT_MISMATCH')
                print(json.dumps({'stage':'REUSED_COMPLETE','game':pk}),flush=True);continue
            started=now();clock=time.perf_counter()
            def progress(stage):
                event={'stage':stage,'game':pk,'atUtc':now(),'elapsedSeconds':round(time.perf_counter()-clock,3)}
                print(json.dumps(event),flush=True);write(folder/'PROGRESS.json',event)
            progress('LOADING_AUTHENTIC_INPUTS')
            b=load_case(row);f=b['forecast'];x=b['execution'];feature=read_ref(x['featureSnapshot'])
            composition=feature['composition']
            if x['sourceCutoff']!=f['sourceCutoff'] or x['sourceCutoff']!=composition['sourceCutoff']:raise ValueError('INPUT_CUTOFF_DIFFERS')
            provider,reload=build_saved_historical_replay_provider(engine,b['snapshot'],composition,x,
                snapshot_sha256=x['featureSnapshot']['sha256'],original_forecast_created_at=f['forecastCreatedAt'])
            kwargs={'game_id':f['gameId'],'transition_model':engine.transition,'n_sims':5000,'master_seed':f['simulation']['seed'],
                    'regulation':int(b['snapshot']['game'].get('scheduled_innings') or 9),'trace_count':1}
            disabled=None;disabled_audit=None
            if i%2==0 or candidate:
                progress('UNCHANGED_5000_DRAWS')
                with RNGStreamAudit(core) as disabled_audit:disabled=core.simulate_prospective_game(provider=provider,**kwargs)
                compare(disabled,b['baseline'])
                progress('UNCHANGED_EXACT_ORIGINAL')
            if not (folder/'REPLAY.json').exists():
                collector=ReplayDiagnostics(5000,regulation=kwargs['regulation'])
                progress('INSTRUMENTED_5000_DRAWS')
                with RNGStreamAudit(core) as instrumented_audit:
                    baseline=core.simulate_prospective_game(provider=collector.wrap_provider(provider),event_observer=collector,**kwargs)
                invariant=compare(baseline,b['baseline'])
                if disabled_audit is not None:disabled_audit.assert_equivalent(instrumented_audit)
                arrays,metadata=collector.finalize(baseline)
                np.savez_compressed(folder/'diagnostics.npz',**arrays)
                pd.DataFrame(compact_draw_records(arrays)).to_csv(folder/'draw_summaries.csv.gz',index=False,compression='gzip')
                validate_sources()
                write(folder/'REPLAY.json',{'schemaVersion':'MLB_V18_PRIVATE_EXACT_REPLAY_V1','startedAtUtc':started,'completedAtUtc':now(),
                    'case':row,'input':ref(b['directory']/'execution-inputs.json'),'forecast':ref(b['directory']/'forecast.json'),
                    'featureSnapshot':x['featureSnapshot'],'model':engine.model_identity,'reload':reload,'invariance':invariant,
                    'disabledEnabledRngAudit':disabled_audit is not None,'instrumentedRng':instrumented_audit.receipt(),
                    'diagnostics':ref(folder/'diagnostics.npz'),'drawSummaries':ref(folder/'draw_summaries.csv.gz'),
                    'metadata':metadata,'sources':sources,'runtimeSeconds':time.perf_counter()-clock,'newForecast':False})
                progress('INSTRUMENTATION_EXACT_AND_SAVED')
            if candidate:
                progress('TERMINAL_CREDIT_SENSITIVITY_5000')
                with RNGStreamAudit(core) as candidate_audit:
                    changed=candidate_fn(provider=provider,**kwargs)
                disabled_audit.assert_equivalent(candidate_audit)
                for key in ['awayRuns','innings','paCounts']:
                    if not np.array_equal(disabled[key],changed[key]):raise ValueError('CANDIDATE_PATH_CHANGED:'+key)
                if not np.array_equal(np.asarray(disabled['homeRuns'])>disabled['awayRuns'],np.asarray(changed['homeRuns'])>changed['awayRuns']):raise ValueError('CANDIDATE_WINNERS_CHANGED')
                write(folder/'candidate_population.json',changed)
                validate_sources()
                write(done,{'startedAtUtc':started,'completedAtUtc':now(),'case':row,'candidateBinding':candidate_binding,
                    'candidate':ref(folder/'candidate_population.json'),'baselineInput':ref(b['directory']/'execution-inputs.json'),
                    'rngEquivalent':True,'rng':candidate_audit.receipt(),'allWinnersAndPaAndInningsUnchanged':True,'sources':sources,
                    'runtimeSeconds':time.perf_counter()-clock,'researchOnly':True})
                progress('CANDIDATE_SAVED')
            for s in sources:
                if ref(s['path'])!=s:raise ValueError('SOURCE_CHANGED_DURING_RUN')
    write(OUT/'LAST_RUN.json',{'completedAtUtc':now(),'candidateIncluded':candidate,'gameFilter':only,'noProviderRequests':True,'noProductionWrites':True})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['declare','run']);p.add_argument('--game');p.add_argument('--candidate',action='store_true');a=p.parse_args()
    if a.command=='declare':declare()
    else:run(a.game,a.candidate)
