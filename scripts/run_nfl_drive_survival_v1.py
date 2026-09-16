"""Separate immutable research outputs; no provider, publisher or AISP calls."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.spatial.distance import pdist
from sklearn.metrics import roc_auc_score
from threadpoolctl import threadpool_limits
from server.sports_nfl_m1.drive_survival import (
    CAUSES,FEATURES,READ_COLUMNS,reconstruct,fit_hazard,SurvivalAdapter,features,seed_for,
    sample_cause,drive_rollout)
from server.sports_nfl_m1.play_model import fit_play_model
from server.sports_nfl_m1.play_engine import simulate_play_game

OUT=ROOT/'outputs/nfl-drive-competing-risks-v1'
OLD=ROOT/'outputs/nfl-play-level-engine-v1'
VPATH=OLD/'runs/62369d15834b6dc7017329b1bad4120e4ea3918b9af484a4f2eca6fb81c2b538/validation.json'
BRONZE=Path('C:/Users/james/asp-data-staging/nfl/bronze-v1')

def now():return datetime.now(timezone.utc).isoformat()
def process_memory():
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(n,ctypes.c_size_t) for n in
          ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
           'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    c=Counters();c.cb=ctypes.sizeof(c)
    fn=ctypes.windll.psapi.GetProcessMemoryInfo
    fn.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    ok=fn(wintypes.HANDLE(-1),ctypes.byref(c),c.cb)
    return dict(workingSetBytes=int(c.WorkingSetSize),peakWorkingSetBytes=int(c.PeakWorkingSetSize)) if ok else {'status':'UNAVAILABLE'}
def ref(p):
    p=Path(p);b=p.read_bytes();return dict(path=str(p.resolve()),sha256=hashlib.sha256(b).hexdigest(),bytes=len(b))
def clean(v):
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    if isinstance(v,np.ndarray):return clean(v.tolist())
    if isinstance(v,np.generic):return clean(v.item())
    if isinstance(v,float) and not np.isfinite(v):return None
    return v
def write(p,v):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes((json.dumps(clean(v),ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2)+'\n').encode())
def verify(r):
    got=ref(r['path']);assert got['sha256']==r['sha256']
    assert got['bytes']==r.get('bytes',r.get('byteCount'));return Path(r['path'])

def audit():
    if (OUT/'DESIGN.json').exists():raise ValueError('audit already frozen; use retained artifacts')
    OUT.mkdir(parents=True,exist_ok=True)
    v=json.loads(VPATH.read_bytes())
    originals=[]
    roots=[OLD,ROOT/'outputs/nfl-forward-vintages-v1',ROOT/'outputs/nfl-week2-paper-eligibility-20260915-v1',
           ROOT/'outputs/nfl-paper-research-eligibility-20260914-v1',ROOT/'outputs/nfl-paper-eligibility-utf8-successor-v1',
           ROOT/'outputs/nfl-current-state-cold-start-v2',ROOT/'outputs/nfl-existing-track-current-shadow-v1']
    for root in roots:
        if root.exists():
            for p in sorted(root.rglob('*')):
                if p.is_file(): originals.append(ref(p))
    code=[ref(ROOT/'server/sports_nfl_m1'/n) for n in ('play_model.py','play_engine.py','play_evidence.py','play_validation.py')]
    write(OUT/'protected-originals.json',dict(createdAtUtc=now(),files=originals,baselineCode=code))
    source=json.loads((BRONZE/'current.json').read_bytes()); mp=BRONZE/source['manifestRelativePath']
    assert ref(mp)['sha256']==source['manifestSha256']
    manifest=json.loads(mp.read_bytes()); frames=[];sources=[]
    for p in sorted((p for p in manifest['partitions'] if p['familyId']=='play_by_play' and p.get('season') in range(2018,2025)),key=lambda p:p['season']):
        path=BRONZE/p['relativePath'];r=ref(path);assert r['sha256']==p['fileSha256']
        q=pq.ParquetFile(path); cols=[c for c in READ_COLUMNS if c in q.schema_arrow.names]
        f=q.read(columns=cols).to_pandas();assert f.season.eq(p['season']).all()
        frames.append(f);sources.append(dict(**r,season=p['season'],license=p['license']))
    assert len(frames)==7
    raw=pd.concat(frames,ignore_index=True)
    risk,drives,games,a=reconstruct(raw)
    risk.to_parquet(OUT/'risk-rows.parquet',index=False);drives.to_parquet(OUT/'drive-audit.parquet',index=False)
    games.to_parquet(OUT/'game-identities-finals.parquet',index=False)
    trainreceipt=json.loads(verify(v['trainingFitReceipt']).read_bytes())
    # Cached corrected model supplies exact normalized donor rows, no normalization refit.
    baseline_path=OLD/'fits/bb19bf9c9a030067d434c18c01b7f09a5ebdef0f2088410e4e9149378dddc53f/model.joblib'
    baseline=joblib.load(baseline_path)
    sources_meta=dict(sourceManifest=ref(mp),sources=sources,baselineValidation=ref(VPATH),
                      baselineModel=ref(baseline_path),sourceAvailability=v['sourceAvailability'],
                      priorMetrics=json.loads(verify(v['historicalGameValidation']).read_bytes())['metrics'],
                      sourceCountDiscrepancies=['340587 raw,287007 normalized,1942 games verified against original receipt.',
                        'RPS .217 and drive TD MAE .081 are not metrics in this play-engine validation; do not attribute them to it.'],
                      chronology='Retrospective archives acquired 2026-08-29. Earlier completed seasons only; no historical release-vintage certification.',
                      normalizedBaselineCounts=dict(plays=baseline.training_plays,games=baseline.training_games,throughSeason=baseline.training_season))
    write(OUT/'source-bindings.json',sources_meta)
    cohorts={}
    for season in (2021,2022,2023,2024):
        x=games[(games.season==season)&games.season_type.eq('REG')&games.score_reconciled&~games.duplicate_play]
        x=x.sort_values(['week','game_id'],kind='stable').groupby('week',sort=True).head(1 if season<=2022 else 2)
        cohorts[str(season)]=x.game_id.tolist()
    design=dict(schemaVersion='NFL_DRIVE_COMPETING_RISKS_DESIGN_V1',createdAtUtc=now(),
       baseline=ref(baseline_path),sourceBindings=ref(OUT/'source-bindings.json'),
       audit= a, features=list(FEATURES),causes=list(CAUSES),
       roles={'warmupTraining':'2018-2020','developmentOOF':'2021-2022','secondaryReusedEarlierTraining':'2023',
              'primaryReusedValidation':'2024','sealedNotRead':[2025],'currentNotRead':[2026]},
       candidates=[{'id':'MULTINOMIAL_L2_C0_1','C':.1,'max_iter':600,'solver':'lbfgs',
                     'preprocessing':'earlier-fold StandardScaler; no imputation; complete preplay inputs required'}],
       integration={'weight':.25,'proposalCount':16,'mechanism':'75% exact baseline branch;25% hazard-projected selection from16 original baseline joint donors',
                    'limitation':'Finite proposal support projection; integrated marginal hazards need empirical assessment, not assumed equal to classifier.',
                    'fallback':'exact baseline sampler without consuming RNG for unsupported state, OT, or zero weight',
                    'support':'within full earlier-training numeric feature ranges; quarter<=4; target season after fit'},
       gameCohorts=cohorts,gameSelection='first1 REG game/week by canonical ID for2021-22;first2 for2023-24; no outcome ranking',
       drawsPerGame=200,driveRolloutDraws=128,driveRolloutSelection='first64 eligible cohort drives by SHA256 drive ID; starts and midpoint',
       conditionalHazardDraws=128,seedPolicy='sha256 UTF8 components,first4 little-endian; shared game/drive seeds across arms; event alignment can diverge',
       donors='completed earlier seasons exclusively; frozen2023 baseline artifact reused for2024; earlier fits identical baseline config',
       causeRules='one terminal per wholly supported drive; End of half/game observed terminal, unsupported drives whole-drive excluded; tries/kickoffs/admin separate',
       primaryMetric='2024 joint final-score energy; paired football-week bootstrap2000 seed191515',
       gates={'minimumLaterGames':30,'minimumDriveGames':20,'driveNllMaxDegradation':.01,
              'gameEnergyPointMustImprove':True,'gameEnergyUpper95MaxDegradation':.20,
              'winnerLogLossMaxDegradation':.01,'marginCrpsMaxDegradation':.10,'totalCrpsMaxDegradation':.10,
              'causeCalibrationMeanAbsMaxDegradation':.01,'runtimeRatioMax':6.,
              'bothLaterSeasonsEnergyMustImprove':True,'exactMassLegalityFallback':True},
       uncertainty='Games/calendar football weeks, never individual plays or simulation draws. No untouched holdout.',
       authority={'researchOnly':True,'executionAllowedInAISP':False,'wageringAuthority':False,'promotion':False})
    write(OUT/'DESIGN.json',design);write(OUT/'drive-construction-audit.json',a)
    print(json.dumps(a),flush=True)
    # Reproduce original saved complete reload sequence before candidate fitting.
    fixture=json.loads(verify(v['reloadVerification']).read_bytes())
    write(OUT/'original-replay-metadata.json',dict(reference=v['reloadVerification'],keys=list(fixture)))
    print('AUDIT_FROZEN',ref(OUT/'DESIGN.json')['sha256'],flush=True)

def fit():
    if (OUT/'FROZEN_SELECTION.json').exists():
        old=json.loads((OUT/'FROZEN_SELECTION.json').read_bytes())
        for x in old['fitted']:verify(x)
        print('FROZEN_FITS_REUSED_NO_REFIT',flush=True);return
    d=json.loads((OUT/'DESIGN.json').read_bytes());risk=pd.read_parquet(OUT/'risk-rows.parquet')
    assert (OUT/'endpoint-clock-verification.json').exists(), 'finish drive eligibility verification first'
    source=json.loads((OUT/'source-bindings.json').read_bytes());base=joblib.load(verify(source['baselineModel']))
    normalized=pd.DataFrame(base.rows);normalized['date']=normalized.date.astype(str)
    (OUT/'models').mkdir(exist_ok=True);timings=[]
    for season in (2021,2022,2023,2024):
        p=OUT/f'models/hazard-through-{season-1}.joblib'
        bp=OUT/f'models/baseline-through-{season-1}.joblib'
        if p.exists() and (season==2024 or bp.exists()):continue
        train=risk[risk.season<season].copy();t=time.perf_counter()
        if p.exists():h=joblib.load(p)
        else:
            with threadpool_limits(limits=1):h=fit_hazard(train,season-1)
            joblib.dump(h,p,compress=3)
        if season<2024:
            b=fit_play_model(normalized[normalized.season<season],end_season=season-1)
            joblib.dump(b,OUT/f'models/baseline-through-{season-1}.joblib',compress=3)
        timings.append(dict(targetSeason=season,trainingRows=h.training_rows,seconds=time.perf_counter()-t,
                            iterations=h.model.n_iter_.tolist(),classes=h.model.classes_.tolist()))
        print('FIT',timings[-1],flush=True)
    write(OUT/'FROZEN_SELECTION.json',dict(createdAtUtc=now(),design=ref(OUT/'DESIGN.json'),
           selected='MULTINOMIAL_L2_C0_1',selection='single predeclared candidate; no score-based configuration search',
           fitted=[ref(p) for p in sorted((OUT/'models').glob('*.joblib'))],timings=timings))

def finalize_data():
    """Additional endpoint/clock integrity check, before any fitting or scores."""
    assert not (OUT/'FROZEN_SELECTION.json').exists()
    assert not list((OUT/'models').glob('*.joblib')), 'eligibility cannot change after fitting'
    risk=pd.read_parquet(OUT/'risk-rows.parquet');drives=pd.read_parquet(OUT/'drive-audit.parquet')
    bindings=json.loads((OUT/'source-bindings.json').read_bytes());bad={}
    for source in bindings['sources']:
        f=pq.ParquetFile(verify(source)).read(columns=['game_id','fixed_drive','play_id','drive_play_id_started','drive_play_id_ended']).to_pandas()
        for (gid,did),g in f.groupby(['game_id','fixed_drive'],dropna=False,sort=False):
            if pd.isna(did):continue
            k=f'{gid}:{did:g}';starts=g.drive_play_id_started.dropna().unique();ends=g.drive_play_id_ended.dropna().unique()
            if not len(starts) or not len(ends):bad[k]='MISSING_DRIVE_ENDPOINT_METADATA'
            elif not (set(starts).issubset(set(g.play_id)) and set(ends).issubset(set(g.play_id))):bad[k]='TRUNCATED_DRIVE_ENDPOINT_NOT_RETAINED'
    for k,g in risk.groupby('drive_key',sort=False):
        if np.any(np.diff(g.sort_values('index').half_seconds)>0):bad[k]='AMBIGUOUS_WITHIN_DRIVE_CLOCK_REVISION'
        if g.quarter_seconds.le(0).any():bad[k]='UNTIMED_OR_ZERO_CLOCK_DECISION_UNSUPPORTED'
    removed=drives[drives.eligible&drives.drive_key.isin(bad)].copy()
    if len(removed):
        prior=OUT/'pre-endpoint-audit'
        if prior.exists():prior=OUT/f'pre-eligibility-{len(list(OUT.glob("pre-*audit")))+len(list(OUT.glob("pre-eligibility-*")))+1}'
        prior.mkdir(exist_ok=False)
        for name in ['risk-rows.parquet','drive-audit.parquet','drive-construction-audit.json','DESIGN.json']:
            p=OUT/name;(prior/name).write_bytes(p.read_bytes())
        mask=drives.eligible&drives.drive_key.isin(bad)
        drives.loc[mask,'eligible']=False;drives.loc[mask,'exclusion']=drives.loc[mask,'drive_key'].map(bad)
        risk=risk[~risk.drive_key.isin(removed.drive_key)]
        risk.to_parquet(OUT/'risk-rows.parquet',index=False);drives.to_parquet(OUT/'drive-audit.parquet',index=False)
        audit=json.loads((OUT/'drive-construction-audit.json').read_bytes());audit.update(supportedDrives=int(drives.eligible.sum()),
            riskRows=len(risk),exclusions=drives.exclusion.value_counts().to_dict(),
            terminalCounts=risk.loc[risk.cause.ne(0),'cause'].map(lambda c:CAUSES[c]).value_counts().to_dict())
        write(OUT/'drive-construction-audit.json',audit)
        d=json.loads((OUT/'DESIGN.json').read_bytes());d.update(audit=audit,endpointVerificationAddedBeforeFittingAtUtc=now(),predecessorDesign=ref(prior/'DESIGN.json'))
        write(OUT/'DESIGN.json',d)
    write(OUT/'endpoint-clock-verification.json',dict(createdAtUtc=now(),checkedEligibleDrives=int(drives.eligible.sum()),
        additionalRemovedDrives=len(removed),removed=removed[['drive_key','season']].assign(reason=removed.drive_key.map(bad)).to_dict('records'),
        riskRows=len(risk),allRemainingHaveRetainedEndpointsAndNonincreasingHalfClock=True))
    print('FINAL_ELIGIBILITY',len(risk),int(drives.eligible.sum()),'removed',len(removed),flush=True)

def verify_preplay_scores():
    risk=pd.read_parquet(OUT/'risk-rows.parquet')
    bindings=json.loads((OUT/'source-bindings.json').read_bytes());checks=[]
    for b in bindings['sources']:
        assert 2018<=b['season']<=2024
        f=pd.read_parquet(verify(b),columns=['game_id','play_id','order_sequence','total_home_score',
            'total_away_score','posteam','home_team','score_differential'])
        f=f.sort_values(['game_id','order_sequence','play_id'])
        for c in ['total_home_score','total_away_score']:
            f[c]=f.groupby('game_id')[c].ffill().fillna(0)
            f['pre_'+c]=f.groupby('game_id')[c].shift().fillna(0)
        f['expected_pre_differential']=(f.pre_total_home_score-f.pre_total_away_score)*np.where(f.posteam==f.home_team,1,-1)
        eligible=risk[risk.season==b['season']][['game_id','play_id','score_differential']].merge(
            f[['game_id','play_id','expected_pre_differential']],on=['game_id','play_id'],validate='one_to_one')
        bad=eligible[eligible.score_differential!=eligible.expected_pre_differential]
        checks.append(dict(season=b['season'],rows=len(eligible),mismatches=len(bad),examples=bad.head(10).to_dict('records')))
    assert sum(x['mismatches'] for x in checks)==0 and sum(x['rows'] for x in checks)==len(risk)
    path=OUT/'preplay-score-verification.json'
    if path.exists():assert json.loads(path.read_bytes())['checks']==checks
    else:write(path,dict(createdAtUtc=now(),checks=checks,allSupportedRows=len(risk),mismatches=0,
        definition='Recorded offense-relative score differential compared with preceding ordered post-play scoreboard; no target score increment used.'))
    print('PREPLAY_SCORES_VERIFIED',len(risk),flush=True)

def baseline_for(season):
    if season==2024:
        return joblib.load(verify(json.loads((OUT/'source-bindings.json').read_bytes())['baselineModel']))
    return joblib.load(OUT/f'models/baseline-through-{season-1}.joblib')

def crps(x,y):
    x=np.sort(np.asarray(x,float));n=len(x)
    return float(np.mean(np.abs(x-y))-np.sum((2*np.arange(n)-n+1)*x)/(n*n))

def game_metrics(draws,home,away):
    x=np.asarray(draws,float);n=len(x);y=np.array([home,away])
    h,a=x[:,0],x[:,1];margin=h-a;total=h+a
    p=np.array([(h>a).mean(),(h<a).mean(),(h==a).mean()]);target=0 if home>away else 1 if home<away else 2
    z=dict(energy=float(np.linalg.norm(x-y,axis=1).mean()-pdist(x).sum()/(n*n)),
           logLoss=float(-np.log(max(p[target],1e-15))),brier=float(np.sum((p-np.eye(3)[target])**2)),
           homeWinProbability=p[0],awayWinProbability=p[1],tieProbability=p[2],
           homeMean=h.mean(),awayMean=a.mean(),homeMae=abs(h.mean()-home),awayMae=abs(a.mean()-away),
           marginMae=abs(margin.mean()-(home-away)),totalMae=abs(total.mean()-(home+away)),
           homeBias=h.mean()-home,awayBias=a.mean()-away,totalBias=total.mean()-home-away,
           marginBias=margin.mean()-home+away,accuracy=float(np.argmax(p)==target),
           lowTotalProbability=float((total<=30).mean()),highTotalProbability=float((total>=60).mean()),
           blowoutProbability=float((np.abs(margin)>=21).mean()),oneScoreProbability=float((np.abs(margin)<=8).mean()),
           zeroObservedClassProbability=bool(p[target]==0))
    for name,vals,actual in [('home',h,home),('away',a,away),('margin',margin,home-away),('total',total,home+away)]:
        z[name+'Crps']=crps(vals,actual)
        for level in (.5,.8,.9):
            lo,hi=np.quantile(vals,[(1-level)/2,(1+level)/2])
            z[f'{name}Coverage{int(level*100)}']=float(lo<=actual<=hi)
            z[f'{name}Width{int(level*100)}']=float(hi-lo)
    return clean(z)

def evaluate(season):
    d=json.loads((OUT/'DESIGN.json').read_bytes());assert (OUT/'FROZEN_SELECTION.json').exists()
    root=OUT/f'evaluation/{season}';root.mkdir(parents=True,exist_ok=True)
    base=baseline_for(season);hazard=joblib.load(OUT/f'models/hazard-through-{season-1}.joblib')
    adapter=SurvivalAdapter(base,hazard)
    games=pd.read_parquet(OUT/'game-identities-finals.parquet').set_index('game_id')
    risk=pd.read_parquet(OUT/'risk-rows.parquet');risk=risk[risk.game_id.isin(d['gameCohorts'][str(season)])]
    timing=[]
    for gid in d['gameCohorts'][str(season)]:
        dest=root/f'{gid}.json'
        if dest.exists():continue
        row=games.loc[gid];scores={};results={};diag={}
        for arm,model in [('baseline',base),('survival',adapter)]:
            begin=time.perf_counter();cpu_begin=time.process_time();draws=[];c=Counter()
            for i in range(d['drawsPerGame']):
                if arm=='survival':adapter.reset();adapter.home_team=row.home_team
                game=simulate_play_game(model,home_team=row.home_team,away_team=row.away_team,season=season,
                     seed=seed_for('NFL_DRIVE_V1',gid,i),include_geometry=False)
                draws.append((game['homeScore'],game['awayScore']))
                c.update({k:game['diagnostics'][k] for k in ('drives','scrimmagePlays','turnovers','points','impossibleStateCount','scoreReconciliationMismatch')})
                c['overtime']+=game['reachedOvertime'];c['finalTie']+=game['finalTie']
                if i==0:write(root/f'{gid}-{arm}-example.json',game)
            elapsed=time.perf_counter()-begin
            scores[arm]=np.array(draws,dtype=np.int16);results[arm]=game_metrics(draws,row.home_score,row.away_score)
            diag[arm]=dict(c);diag[arm]['processMemory']=process_memory()
            timing.append(dict(game=gid,arm=arm,seconds=elapsed))
            results[arm]['runtimeSeconds']=elapsed
            results[arm]['runtimeCpuSeconds']=time.process_time()-cpu_begin
        np.savez_compressed(root/f'{gid}-draws.npz',**scores)
        write(dest,dict(gameId=gid,season=season,week=int(row.week),date=row.date,home=row.home_team,away=row.away_team,
                       actualHome=int(row.home_score),actualAway=int(row.away_score),drawCount=d['drawsPerGame'],
                       scores=results,accounting=diag,pairedSeedPolicy=d['seedPolicy'],status='REUSED_HISTORICAL'))
        print('GAME',season,gid,round(results['survival']['energy']-results['baseline']['energy'],4),flush=True)
    write(root/'adapter-accounting.json',dict(adapter.counts))
    # Conditional current-play hazard predictions on all supported cohort decisions.
    if not (root/'hazard-predictions.parquet').exists():
        predictions=[];begin=time.perf_counter()
        for i,s in enumerate(risk.to_dict('records')):
            rng=np.random.default_rng(seed_for('HAZARD',s['game_id'],s['play_id']))
            causes=[sample_cause(s,base.sample(s,rng)) for _ in range(d['conditionalHazardDraws'])]
            q=np.bincount(causes,minlength=len(CAUSES))/len(causes)
            p=hazard.predict(s) if hazard.supported(s) else q
            projected=[]
            if hazard.supported(s):
                for block in np.asarray(causes).reshape(-1,16):
                    w=np.where(np.bincount(block,minlength=len(CAUSES))>0,p,0.)
                    projected.append(w/w.sum() if w.sum()>0 else np.bincount(block,minlength=len(CAUSES))/16)
                integrated=.75*q+.25*np.mean(projected,axis=0)
            else:integrated=q
            predictions.append(dict(**s,baseline_probability=q.tolist(),raw_classifier_probability=p.tolist(),
                                    survival_probability=integrated.tolist(),supported=hazard.supported(s),
                                    cold_start=any(base.banks.get((unit,s[team],'SCRIMMAGE')) is None or
                                        base.banks[(unit,s[team],'SCRIMMAGE')].mass*.65**(season-base.training_season)<400
                                        for unit,team in [('offense','offense_team'),('defense','defense_team')])))
        pd.DataFrame(predictions).to_parquet(root/'hazard-predictions.parquet',index=False)
        print('HAZARDS',season,len(predictions),time.perf_counter()-begin,flush=True)
    # Future-state rollout from starts and midpoint, never teacher-forced horizons.
    if not (root/'drive-rollouts.parquet').exists():
        keys=sorted(risk.drive_key.unique(),key=lambda k:seed_for('DRIVE_SELECT',k))[:64]
        results=[];population={}
        for k in keys:
            rr=risk[risk.drive_key==k].sort_values('index')
            for position in sorted(set([0,len(rr)//2])):
                s=rr.iloc[position].to_dict()
                previous=rr.iloc[:position];previous=previous[previous.kind.ne('PENALTY')]
                s['recent_pass_flags']=previous.kind.isin(['PASS_COMPLETE','PASS_INCOMPLETE','INTERCEPTION','SACK','QB_SCRAMBLE','SPIKE']).tail(3).astype(int).tolist()
                for arm,model in [('baseline',base),('survival',adapter)]:
                    vals=[drive_rollout(model,s,seed_for('ROLLOUT',k,position,i)) for i in range(d['driveRolloutDraws'])]
                    arr=pd.DataFrame(vals);p=np.bincount(arr.cause,minlength=len(CAUSES))/len(arr)
                    y=int(s['final_cause']);actual_n=int(s['remaining_decisions']);actual_time=s['remaining_seconds']
                    out=dict(drive_key=k,game_id=s['game_id'],season=season,week=s['week'],position=position,arm=arm,
                        start_yard=s['yardline_100'],quarter=s['quarter'],half_seconds=s['half_seconds'],home=s['home'],score=s['score_differential'],
                        down=s['down'],distance=s['yards_to_go'],actual_cause=y,probabilities=p.tolist(),
                        causeBrier=float(np.sum((p-np.eye(len(CAUSES))[y])**2)),causeNll=float(-np.log(max(p[y],1e-15))),
                        actualDecisions=actual_n,expectedDecisions=float(arr.decisions.mean()),
                        lengthMae=abs(arr.decisions.mean()-actual_n),lengthCrps=crps(arr.decisions,actual_n),
                        actualSeconds=actual_time,expectedSeconds=float(arr.seconds.mean()),
                        timeMae=abs(arr.seconds.mean()-actual_time) if pd.notna(actual_time) else None,
                        expectedNetDrivePoints=float(arr.points.mean()),
                        expectedOffensivePointsBeforeTry=float(arr.points.clip(lower=0).mean()),
                        offensivePointsError=abs(arr.points.clip(lower=0).mean()-(6 if y==1 else 3 if y==2 else 0)))
                    for horizon in (1,3,5,10,20):
                        cif=np.array([((arr.cause==c)&(arr.decisions<=horizon)).mean() for c in range(1,len(CAUSES))])
                        truth=np.array([int(y==c and actual_n<=horizon) for c in range(1,len(CAUSES))])
                        out[f'cif{horizon}']=cif.tolist();out[f'cifBrier{horizon}']=float(np.sum((cif-truth)**2))
                    results.append(out);population[f'{k}:{position}:{arm}']=arr[['cause','decisions','seconds','points']].to_numpy()
        pd.DataFrame(results).to_parquet(root/'drive-rollouts.parquet',index=False)
        np.savez_compressed(root/'drive-populations.npz',**population)
        print('DRIVE_ROLLOUTS',season,len(results),flush=True)

def bootstrap_delta(frame, metric, blocks=('season','week')):
    if frame.empty:
        return dict(mean=None,lower95=None,upper95=None,games=0,blocks=0,
                    bootstrapReplicates=0,status='UNAVAILABLE_NO_SUPPORTED_OBSERVATIONS')
    x=frame.copy();x['block']=x[list(blocks)].astype(str).agg('|'.join,axis=1)
    b=x.groupby('block')[metric].agg(['sum','count']);rng=np.random.default_rng(191515)
    draws=rng.integers(0,len(b),size=(2000,len(b)))
    values=b['sum'].to_numpy()[draws].sum(1)/b['count'].to_numpy()[draws].sum(1)
    return dict(mean=float(x[metric].mean()),lower95=float(np.quantile(values,.025)),
                upper95=float(np.quantile(values,.975)),games=len(x),blocks=len(b),bootstrapReplicates=2000)

def calibration(p,y):
    p=np.asarray(p,float);y=np.asarray(y,float)
    bands=[]
    for lo in np.arange(0,1,.1):
        mask=(p>=lo)&(p<(lo+.1) if lo<.9 else p<=1)
        if mask.any():bands.append(dict(lower=float(lo),n=int(mask.sum()),predicted=float(p[mask].mean()),observed=float(y[mask].mean())))
    fit=None
    if len(np.unique(y))==2:
        from sklearn.linear_model import LogisticRegression
        z=np.log(np.clip(p,1e-6,1-1e-6)/(1-np.clip(p,1e-6,1-1e-6))).reshape(-1,1)
        model=LogisticRegression(C=1e6).fit(z,y)
        fit=dict(intercept=float(model.intercept_[0]),slope=float(model.coef_[0,0]))
    return dict(bands=bands,diagnosticLogisticFit=fit)

def summarize_games(rows):
    result={}
    for arm in ('baseline','survival'):
        f=pd.DataFrame([dict(gameId=r['gameId'],season=r['season'],week=r['week'],
                            actualHome=r['actualHome'],actualAway=r['actualAway'],**r['scores'][arm]) for r in rows])
        numeric=f.select_dtypes(include='number').columns.difference(['season','week','actualHome','actualAway'])
        result[arm]=dict(games=len(f),metrics={k:float(f[k].mean()) for k in numeric},
            auc=float(roc_auc_score(f.actualHome>f.actualAway,f.homeWinProbability)) if (f.actualHome>f.actualAway).nunique()>1 else None,
            reliability=calibration(f.homeWinProbability,(f.actualHome>f.actualAway).astype(int)),
            tailCalibration={})
        for label,pcol,y in [('lowTotal','lowTotalProbability',(f.actualHome+f.actualAway)<=30),
                            ('highTotal','highTotalProbability',(f.actualHome+f.actualAway)>=60),
                            ('blowout','blowoutProbability',abs(f.actualHome-f.actualAway)>=21),
                            ('oneScore','oneScoreProbability',abs(f.actualHome-f.actualAway)<=8)]:
            result[arm]['tailCalibration'][label]=dict(predicted=float(f[pcol].mean()),observed=float(y.mean()),
                events=int(y.sum()),supportedForInterpretation=len(f)>=20 and y.sum()>=10)
        favorite=f.homeWinProbability>=f.awayWinProbability
        upset=np.where(favorite,f.actualAway>f.actualHome,f.actualHome>f.actualAway)
        pred=np.where(favorite,f.awayWinProbability,f.homeWinProbability)
        result[arm]['favoriteUpset']=dict(predicted=float(pred.mean()),observed=float(upset.mean()),
                                         trueTieRate=float((f.actualAway==f.actualHome).mean()))
    delta=[]
    metrics=['energy','logLoss','brier','marginCrps','totalCrps','marginMae','totalMae','homeMae','awayMae',
             'homeBias','awayBias','totalBias','marginBias']
    for r in rows:
        delta.append(dict(season=r['season'],week=r['week'],**{m:r['scores']['survival'][m]-r['scores']['baseline'][m] for m in metrics}))
    result['pairedDifferences']={m:bootstrap_delta(pd.DataFrame(delta),m) for m in metrics}
    result['runtimeRatio']=sum(r['scores']['survival']['runtimeSeconds'] for r in rows)/sum(r['scores']['baseline']['runtimeSeconds'] for r in rows)
    return result

def summarize_hazards(f):
    y=f.cause.to_numpy(int);truth=np.eye(len(CAUSES))[y];result={};individual=[]
    for arm,column in [('baseline','baseline_probability'),('survival','survival_probability'),('rawClassifier','raw_classifier_probability')]:
        p=np.stack(f[column]);stabilized=(128*p+.5)/(128+.5*len(CAUSES))
        loss=-np.log(stabilized[np.arange(len(f)),y]);raw=-np.log(np.maximum(p[np.arange(len(f)),y],1e-15))
        brier=((p-truth)**2).sum(1)
        result[arm]=dict(rows=len(f),games=int(f.game_id.nunique()),drives=int(f.drive_key.nunique()),
            stabilizedNll=float(loss.mean()),rawNll=float(raw.mean()),multiclassBrier=float(brier.mean()),
            zeroObservedClassProbabilities=int((p[np.arange(len(f)),y]==0).sum()),
            causeCalibration={c:dict(predicted=float(p[:,i].mean()),observed=float((y==i).mean()),
                 brier=float(((p[:,i]-truth[:,i])**2).mean()),reliability=calibration(p[:,i],truth[:,i])) for i,c in enumerate(CAUSES)})
        result[arm]['causeCalibrationMeanAbsoluteError']=float(abs(p.mean(0)-truth.mean(0)).mean())
        if arm in ('baseline','survival'):
            ff=f[['game_id','season','week']].copy();ff['nll']=loss;ff['brier']=brier;ff['arm']=arm
            individual.append(ff.groupby(['game_id','season','week','arm']).mean().reset_index())
    a=pd.concat(individual);wide=a.pivot(index=['game_id','season','week'],columns='arm',values=['nll','brier'])
    delta=pd.DataFrame({m:wide[(m,'survival')]-wide[(m,'baseline')] for m in ('nll','brier')}).reset_index()
    result['pairedGameWeightedDifferences']={m:bootstrap_delta(delta,m) for m in ('nll','brier')}
    return result

def summarize_rollouts(f):
    result={};scorecols=['causeBrier','causeNll','lengthMae','lengthCrps','timeMae','offensivePointsError']+[f'cifBrier{h}' for h in (1,3,5,10,20)]
    for arm in ('baseline','survival'):
        g=f[f.arm==arm];p=np.stack(g.probabilities);y=g.actual_cause.to_numpy(int)
        result[arm]=dict(origins=len(g),drives=int(g.drive_key.nunique()),games=int(g.game_id.nunique()),
            metrics={m:float(g[m].mean()) for m in scorecols},
            discreteIntegratedBrier=float(g[[f'cifBrier{h}' for h in (1,3,5,10,20)]].to_numpy().mean()),
            expectedDecisions=float(g.expectedDecisions.mean()),observedDecisions=float(g.actualDecisions.mean()),
            expectedSeconds=float(g.expectedSeconds.mean()),observedSeconds=float(g.actualSeconds.mean()),
            expectedOffensivePointsBeforeTry=float(g.expectedOffensivePointsBeforeTry.mean()),
            causes={c:dict(predicted=float(p[:,i].mean()),observed=float((y==i).mean()),events=int((y==i).sum()),
                    supportedForInterpretation=(y==i).sum()>=10) for i,c in enumerate(CAUSES) if i},horizonCalibration={})
        for h in (1,3,5,10,20):
            cif=np.stack(g[f'cif{h}']);observed=np.column_stack([(y==c)&(g.actualDecisions.to_numpy()<=h) for c in range(1,len(CAUSES))])
            result[arm]['horizonCalibration'][str(h)]=dict(predictedCumulativeIncidence=cif.mean(0).tolist(),
                observedCumulativeIncidence=observed.mean(0).tolist(),causes=list(CAUSES[1:]))
    wide=f.pivot(index=['drive_key','game_id','season','week','position'],columns='arm',values=scorecols)
    delta=pd.DataFrame({m:wide[(m,'survival')]-wide[(m,'baseline')] for m in scorecols}).reset_index().groupby(['game_id','season','week'])[scorecols].mean().reset_index()
    result['pairedGameWeightedDifferences']={m:bootstrap_delta(delta.dropna(subset=[m]),m) for m in scorecols}
    return result

def report():
    design=json.loads((OUT/'DESIGN.json').read_bytes());allgames=[];allhaz=[];alldrives=[]
    for season in (2021,2022,2023,2024):
        root=OUT/f'evaluation/{season}'
        for gid in design['gameCohorts'][str(season)]:allgames.append(json.loads((root/f'{gid}.json').read_bytes()))
        allhaz.append(pd.read_parquet(root/'hazard-predictions.parquet'));alldrives.append(pd.read_parquet(root/'drive-rollouts.parquet'))
    hazards=pd.concat(allhaz);drives=pd.concat(alldrives);partitions={}
    totals={r['gameId']:r['actualHome']+r['actualAway'] for r in allgames}
    hazards['actual_game_total']=hazards.game_id.map(totals)
    for name,seasons in [('development',[2021,2022]),('reused2023',[2023]),('reusedValidation2024',[2024])]:
        rows=[r for r in allgames if r['season'] in seasons]
        partitions[name]=dict(game=summarize_games(rows),hazard=summarize_hazards(hazards[hazards.season.isin(seasons)]),
                              drive=summarize_rollouts(drives[drives.season.isin(seasons)]))
    situations={}
    for name,mask in [('red_zone',hazards.yardline_100<=20),('opponent_territory',hazards.drive_start_yard<50),
       ('backed_up',hazards.drive_start_yard>=90),('two_minute',hazards.half_seconds<=120),
       ('fourth_quarter',hazards.quarter==4),('leading',hazards.score_differential>0),('trailing',hazards.score_differential<0),
       ('short_yardage',hazards.yards_to_go<=2),('home',hazards.home==1),('away',hazards.home==0),
       ('early_season',hazards.week<=3),('cold_start',hazards.cold_start),
       ('low_total_games',hazards.actual_game_total<=30),('high_total_games',hazards.actual_game_total>=60),
       ('overtime',hazards.quarter>4)]:
        subset=hazards[mask&hazards.season.isin([2023,2024])]
        situations[name]=dict(rows=len(subset),games=int(subset.game_id.nunique()),supportedForInterpretation=subset.game_id.nunique()>=20,
                             results=summarize_hazards(subset) if len(subset) else None)
    seasons={str(s):summarize_games([r for r in allgames if r['season']==s]) for s in (2021,2022,2023,2024)}
    game_situations={}
    for label,condition in [('early_season',lambda r:r['week']<=3),
        ('low_total',lambda r:r['actualHome']+r['actualAway']<=30),
        ('high_total',lambda r:r['actualHome']+r['actualAway']>=60),
        ('one_score',lambda r:abs(r['actualHome']-r['actualAway'])<=8),
        ('blowout',lambda r:abs(r['actualHome']-r['actualAway'])>=21)]:
        rows=[r for r in allgames if r['season'] in (2023,2024) and condition(r)]
        game_situations[label]=dict(games=len(rows),supportedForInterpretation=len(rows)>=20,
            results=summarize_games(rows) if rows else None,
            qualification='Exploratory; total/margin cells use realized outcomes, not pregame membership.')
    mechanics={}
    for arm in ('baseline','survival'):
        mechanics[arm]=dict(draws=sum(r['drawCount'] for r in allgames),
            overtime=sum(r['accounting'][arm]['overtime'] for r in allgames),
            finalTies=sum(r['accounting'][arm]['finalTie'] for r in allgames),
            impossibleStates=sum(r['accounting'][arm]['impossibleStateCount'] for r in allgames),
            scoreReconciliationMismatches=sum(r['accounting'][arm]['scoreReconciliationMismatch'] for r in allgames),
            gamesWithZeroEmpiricalObservedWinnerProbability=sum(r['scores'][arm]['zeroObservedClassProbability'] for r in allgames),
            runtimeSeconds=sum(r['scores'][arm]['runtimeSeconds'] for r in allgames),
            runtimeCpuSeconds=sum(r['scores'][arm]['runtimeCpuSeconds'] for r in allgames),
            peakProcessWorkingSetBytes=max(r['accounting'][arm]['processMemory'].get('peakWorkingSetBytes',0) for r in allgames),
            scoreTransformations=0)
    integration_accounting={}
    for season in (2021,2022,2023,2024):
        counts=json.loads((OUT/f'evaluation/{season}/adapter-accounting.json').read_bytes())
        branch=counts.get('hazard_branch',0)
        integration_accounting[str(season)]=dict(counts=counts,
            meanClassifierProbabilityAbsentFromProposalSet=(counts.get('missing_cause_probability_millionths',0)/(1e6*branch) if branch else None),
            scope='Full declared full-game cohort' if season>=2023 else 'Full-game calls after restart; five earlier completed game rows preserved separately',
            phaseFallback='exact_baseline_calls includes kicks/tries; unsupported_exact_fallback includes OT and out-of-training-range states; not separately identifiable here')
    primary=partitions['reusedValidation2024'];gs=primary['game'];hs=primary['hazard'];gates=design['gates']
    verification=json.loads((OUT/'replay-verification.json').read_bytes())
    checks=dict(adequateGames=gs['baseline']['games']>=gates['minimumLaterGames'],
        adequateDriveGames=primary['drive']['baseline']['games']>=gates['minimumDriveGames'],
        exactMassLegalityFallback=verification['status']=='REPLAY_VERIFIED' and
            verification['exactFullGameFallbackChecks']==8 and
            verification['retainedGameDrawsReconciled']==sum(len(v) for v in design['gameCohorts'].values())*400,
        driveNll=hs['survival']['stabilizedNll']-hs['baseline']['stabilizedNll']<=gates['driveNllMaxDegradation'],
        energyImproves=gs['pairedDifferences']['energy']['mean']<0,
        energyUpperBound=gs['pairedDifferences']['energy']['upper95']<gates['gameEnergyUpper95MaxDegradation'],
        winnerGuardrail=gs['pairedDifferences']['logLoss']['mean']<gates['winnerLogLossMaxDegradation'],
        marginGuardrail=gs['pairedDifferences']['marginCrps']['mean']<gates['marginCrpsMaxDegradation'],
        totalGuardrail=gs['pairedDifferences']['totalCrps']['mean']<gates['totalCrpsMaxDegradation'],
        calibrationGuardrail=hs['survival']['causeCalibrationMeanAbsoluteError']-hs['baseline']['causeCalibrationMeanAbsoluteError']<gates['causeCalibrationMeanAbsMaxDegradation'],
        bothLaterSeasons=all(seasons[str(s)]['pairedDifferences']['energy']['mean']<0 for s in (2023,2024)),
        runtime=gs['runtimeRatio']<=gates['runtimeRatioMax'])
    disposition='SUPPORTED_FOR_FURTHER_RESEARCH' if all(checks.values()) else 'RETAIN_EXISTING_PLAY_ENGINE'
    a=dict(schemaVersion='NFL_DRIVE_COMPETING_RISKS_ASSESSMENT_V1',createdAtUtc=now(),disposition=disposition,
           design=ref(OUT/'DESIGN.json'),frozenSelection=ref(OUT/'FROZEN_SELECTION.json'),
           partitions=partitions,seasons=seasons,situationDiagnostics=situations,
           gameSituationDiagnostics=game_situations,simulationMechanics=mechanics,
           integrationAccounting=integration_accounting,admissionChecks=checks,
           scoringConvention=json.loads((OUT/'EVALUATION_SPEC.json').read_bytes()),
           weighting='Conditional point summaries pool supported decision rows; paired conditional intervals first average within game and resample weeks. Game forecast scores give each game equal weight.',
           integrityVerification=ref(OUT/'replay-verification.json'),
           drivePointTimeAccounting=ref(OUT/'drive-point-time-accounting.json'),
           preplayScoreVerification=ref(OUT/'preplay-score-verification.json'),
           noUntouchedHoldout=True,providerRequests=0,aispWrites=0,new2026Forecasts=0)
    write(OUT/'ASSESSMENT.json',a);write(OUT/'paired-full-game-assessment.json',allgames)
    lines=['# NFL drive competing-risks survival challenger V1','',f'**{disposition}**','',
        'One frozen L2 multinomial hazard candidate; no operational model change. Historical archives acquired August 29, 2026 qualify these as reconstructed research, not certified pregame vintages. 2025 remains sealed and 2026 outcomes were not used.',
        '', f"The current-decision hazard scores improve, but this does not establish stable full-game improvement. Failed admission checks: {', '.join(k for k,v in checks.items() if not v) or 'none'}. The primary 2024 energy upper bound is {gs['pairedDifferences']['energy']['upper95']:+.4f} against the frozen +0.2000 limit; total CRPS changes {gs['pairedDifferences']['totalCrps']['mean']:+.4f} against the +0.1000 guardrail.",
        '', 'Red-zone and two-minute conditional hazard scores improve in the declared later cells. Backed-up drives have no supported gain. Remaining-drive length CRPS worsens slightly in both later seasons, and 2024 cumulative-incidence Brier also worsens slightly. Improved next-decision classification is insufficient to advance this integrated component.',
        '', '## Matched full-game assessment', '',
        'Candidate minus baseline; negative proper-score differences are better. 95% intervals resample football weeks, not plays or draws. 200 paired-seed simulations per configuration per target; stochastic paths can diverge.', '',
        '| Role | Games | Baseline energy | Candidate energy | Energy change [95% interval] | Winner LL change | Margin CRPS change | Total CRPS change | Runtime ratio |',
        '|---|---:|---:|---:|---|---:|---:|---:|---:|']
    for name,p in partitions.items():
        g=p['game'];x=g['pairedDifferences'];e=x['energy']
        lines.append(f"| {name} | {g['baseline']['games']} | {g['baseline']['metrics']['energy']:.4f} | {g['survival']['metrics']['energy']:.4f} | {e['mean']:+.4f} [{e['lower95']:+.4f}, {e['upper95']:+.4f}] | {x['logLoss']['mean']:+.4f} | {x['marginCrps']['mean']:+.4f} | {x['totalCrps']['mean']:+.4f} | {g['runtimeRatio']:.2f}x |")
    lines+=['','## Drive predictions','',
        '| Role | Supported recorded states | Baseline / integrated hazard stabilized NLL | Baseline / candidate Brier sum | Baseline / candidate drive-length CRPS |',
        '|---|---:|---:|---:|---:|']
    for name,p in partitions.items():
        h=p['hazard'];r=p['drive'];lines.append(f"| {name} | {h['baseline']['rows']} | {h['baseline']['stabilizedNll']:.4f} / {h['survival']['stabilizedNll']:.4f} | {h['baseline']['multiclassBrier']:.4f} / {h['survival']['multiclassBrier']:.4f} | {r['baseline']['metrics']['lengthCrps']:.4f} / {r['survival']['metrics']['lengthCrps']:.4f} |")
    lines+=['','### Reused 2024 current-decision causes','',
        'Rates use supported recorded decision states as the denominator, not whole drives. Brier changes are descriptive contributions to the multiclass score.', '',
        '| Cause | Observed rate | Baseline rate | Candidate rate | Candidate minus baseline Brier |',
        '|---|---:|---:|---:|---:|']
    for cause,b in hs['baseline']['causeCalibration'].items():
        c=hs['survival']['causeCalibration'][cause]
        lines.append(f"| {cause} | {b['observed']:.4f} | {b['predicted']:.4f} | {c['predicted']:.4f} | {c['brier']-b['brier']:+.5f} |")
    lines+=['','### Predeclared situation diagnostics, reused 2023/2024','',
        'Overlapping cells; exploratory intervals are unadjusted. Fewer than 20 represented games is insufficient for interpretation.', '',
        '| Situation | Games | Integrated hazard NLL change [95% interval] | Interpretation support |',
        '|---|---:|---|---|']
    for name,cell in situations.items():
        if cell['results']:
            v=cell['results']['pairedGameWeightedDifferences']['nll']
            delta=f"{v['mean']:+.4f} [{v['lower95']:+.4f}, {v['upper95']:+.4f}]"
        else:delta='Unavailable'
        lines.append(f"| {name} | {cell['games']} | {delta} | {'Supported exploratory cell' if cell['supportedForInterpretation'] else 'Insufficient'} |")
    lines+=['','Conditional probabilities use a fixed 128-proposal estimate. Primary conditional NLL applies the same Jeffreys 0.5-per-cell score stabilization to both arms; raw zero-count and classifier scores are retained separately. The integrated law projects hazards to a finite feasible proposal set; it is not the raw classifier law.',
      '', 'The complete JSON retains terminal-cause Brier/reliability, cumulative incidence at 1/3/5/10/20 decisions, remaining length/time, offensive points before tries, game AUC/accuracy, scoring biases, all 50/80/90 intervals, tails and situation diagnostics. Sparse cells are marked.',
      '', '## Admission and limitations','',f'Frozen gate results: `{json.dumps(checks,sort_keys=True)}`.',
      '', 'Drive exclusions are whole-drive exclusions. No-play penalties are separate decision transitions; timeouts/administrative markers are not snaps; period endings are observed terminals, not ordinary censoring. Exclusion-related selection bias remains attached to conditional results. Full-game evaluations include all declared supported identities, using pregame team identities/season and earlier-season priors only.',
      '', 'Postseason is excluded from full-game comparison because the existing engine rejects postseason overtime. Overtime uses the unchanged legal regular-season engine and exact hazard fallback. Ties remain genuine final ties in a three-class Brier sum. Scores are produced through legal scoring events: no final-score clipping, rounding or rejection is added.',
      '', '2024 is reused Validation. 2023 was previously included in baseline training and is secondary reused evidence; its new target fold trains only through 2022. No independent prospective superiority claim is available.',
      '', 'New drive ordering uses retained order_sequence. Initial play-ID-only auditing produced 619 apparent score-order failures; all 1,942 scores reconcile after the documented research-label correction. Original donor normalization and published artifacts remain unchanged. Its existing period-end/clock support limitations are not repaired by this challenger.',
      '', 'The game cohort was fixed by canonical identity within week. It overrepresents alphabetically earlier team IDs and is not a league-representative random sample. The 108 games are assessment units; 43,200 simulated outcomes are not independent football observations.',
      '', 'With 200 game draws, a single empirical class probability has maximum binomial sampling standard error about 0.0354. This is simulation precision, not a bound on model error. Winner log loss uses the declared 1e-15 numerical floor for zero empirical observed-class probabilities; zero counts remain explicit in the assessment.',
      '', 'The original play engine receipt supports held-out play log loss 1.182461 versus 1.516647. The supplied orientation values RPS 0.217 and drive-TD MAE 0.081 were not present in that authoritative receipt and are not attributed to this baseline.',
      '', 'Adapter branch counters for 2021/2022 cover only games executed after the documented midpoint-history correction restart; retained earlier full-game draws are unchanged. The 2023/2024 counters cover their complete game runs. CPU and wall timings are descriptive: baseline runs first and warms the shared donor cache. Peak memory is process-wide, not isolated component memory.',
      '', '## Reproduction','', '```powershell',
      '.\\.venv\\Scripts\\python.exe -B scripts\\run_nfl_drive_survival_v1.py --stage replay','```','']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print('ASSESSMENT',disposition,json.dumps(checks),flush=True)

def index_artifacts():
    import sklearn,scipy
    paths=[p for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='artifact-index.json']
    write(OUT/'artifact-index.json',dict(schemaVersion='NFL_DRIVE_SURVIVAL_ARTIFACT_INDEX_V1',createdAtUtc=now(),
        artifacts={str(p.relative_to(OUT)):ref(p) for p in paths},
        implementation=[ref(ROOT/p) for p in ['server/sports_nfl_m1/drive_survival.py',
                         'scripts/run_nfl_drive_survival_v1.py','tests/test_nfl_drive_survival.py']],
        software=dict(python=sys.version,numpy=np.__version__,pandas=pd.__version__,scikitLearn=sklearn.__version__,
                      scipy=scipy.__version__,joblib=joblib.__version__),
        identitySemantics='All sha256 fields are hashes of exact physical bytes. No logical exchange package was published.'))

def replay():
    index_path=OUT/'artifact-index.json'
    if index_path.exists():
        idx=json.loads(index_path.read_bytes())
        for x in idx['artifacts'].values():verify(x)
        for x in idx['implementation']:verify(x)
    protected=json.loads((OUT/'protected-originals.json').read_bytes())
    for x in protected['files']+protected['baselineCode']:verify(x)
    bindings=json.loads((OUT/'source-bindings.json').read_bytes())
    for x in bindings['sources']:verify(x)
    for x in ('baselineModel','baselineValidation','sourceManifest'):verify(bindings[x])
    selection=json.loads((OUT/'FROZEN_SELECTION.json').read_bytes())
    verify(selection['design'])
    for x in selection['fitted']:verify(x)
    design=json.loads((OUT/'DESIGN.json').read_bytes());risk=pd.read_parquet(OUT/'risk-rows.parquet')
    assert risk.season.between(2018,2024).all()
    assert risk.groupby('drive_key').cause.apply(lambda x:(x!=0).sum()).eq(1).all()
    assert not risk.duplicated(['game_id','play_id']).any()
    assert risk.remaining_seconds.notna().all() and risk.remaining_seconds.ge(0).all()
    drive_audit=pd.read_parquet(OUT/'drive-audit.parquet')
    finals=pd.read_parquet(OUT/'game-identities-finals.parquet').set_index('game_id')
    increments=drive_audit.groupby('game_id')[['home_points','away_points']].sum()
    np.testing.assert_array_equal(increments.home_points,finals.loc[increments.index].home_score)
    np.testing.assert_array_equal(increments.away_points,finals.loc[increments.index].away_score)
    examples=0;population_rows=0;fallback_checks=0;drive_replays=0
    class Unsupported:
        def supported(self,s):return False
    for season in (2021,2022,2023,2024):
        base=baseline_for(season);h=joblib.load(OUT/f'models/hazard-through-{season-1}.joblib')
        assert base.training_season==h.through_season==season-1
        assert max(r['date'] for r in base.rows)<f'{season}-03-01'
        for row in risk[risk.season==season].head(16).to_dict('records'):
            expected=h.model.predict_proba(h.scaler.transform(features(row)[None]))[0]
            np.testing.assert_allclose(h.predict(row)[h.model.classes_.astype(int)],expected,atol=1e-12)
        root=OUT/f'evaluation/{season}'
        for gid in design['gameCohorts'][str(season)]:
            r=json.loads((root/f'{gid}.json').read_bytes());p=np.load(root/f'{gid}-draws.npz')
            for arm in ('baseline','survival'):
                draws=p[arm];assert draws.shape==(200,2);assert (draws>=0).all();assert (draws%1==0).all()
                metrics=game_metrics(draws,r['actualHome'],r['actualAway'])
                for key,value in metrics.items():assert np.isclose(value,r['scores'][arm][key]),(gid,arm,key)
                assert r['accounting'][arm]['impossibleStateCount']==0
                assert r['accounting'][arm]['scoreReconciliationMismatch']==0
                population_rows+=len(draws)
        gid=design['gameCohorts'][str(season)][0]
        r=json.loads((root/f'{gid}.json').read_bytes())
        for arm,model in [('baseline',base),('survival',SurvivalAdapter(base,h,home_team=r['home']))]:
            game=simulate_play_game(model,home_team=r['home'],away_team=r['away'],season=season,
                   seed=seed_for('NFL_DRIVE_V1',gid,0),include_geometry=False)
            expected=json.loads((root/f'{gid}-{arm}-example.json').read_bytes())
            assert game==expected,(season,arm,'full sequence mismatch');examples+=1
        for weight,model in [(0,h),(.25,Unsupported())]:
            adapter=SurvivalAdapter(base,model,weight=weight,home_team=r['home'])
            game=simulate_play_game(adapter,home_team=r['home'],away_team=r['away'],season=season,
                    seed=seed_for('NFL_DRIVE_V1',gid,0),include_geometry=False)
            assert game==json.loads((root/f'{gid}-baseline-example.json').read_bytes());fallback_checks+=1
        hp=pd.read_parquet(root/'hazard-predictions.parquet')
        for key in ('baseline_probability','survival_probability','raw_classifier_probability'):
            p=np.stack(hp[key]);assert (p>=0).all();np.testing.assert_allclose(p.sum(1),1,atol=1e-12)
        pops=np.load(root/'drive-populations.npz')
        for key in pops:
            a=pops[key];assert a.shape==(128,4);assert np.isin(a[:,0],np.arange(1,9)).all()
            assert (a[:,1]>=1).all() and (a[:,2]>=0).all()
        eligible_risk=risk[risk.game_id.isin(design['gameCohorts'][str(season)])]
        key=sorted(eligible_risk.drive_key.unique(),key=lambda k:seed_for('DRIVE_SELECT',k))[0]
        rr=eligible_risk[eligible_risk.drive_key==key].sort_values('index')
        for position in sorted(set([0,len(rr)//2])):
            s=rr.iloc[position].to_dict();previous=rr.iloc[:position]
            previous=previous[previous.kind.ne('PENALTY')]
            s['recent_pass_flags']=previous.kind.isin(['PASS_COMPLETE','PASS_INCOMPLETE','INTERCEPTION','SACK','QB_SCRAMBLE','SPIKE']).tail(3).astype(int).tolist()
            for arm,model in [('baseline',base),('survival',SurvivalAdapter(base,h,home_team=s['home_team']))]:
                for i in range(2):
                    got=drive_rollout(model,s,seed_for('ROLLOUT',key,position,i))
                    np.testing.assert_array_equal([got[k] for k in ('cause','decisions','seconds','points')],
                                                  pops[f'{key}:{position}:{arm}'][i])
                    drive_replays+=1
    receipt=dict(status='REPLAY_VERIFIED',createdAtUtc=now(),fullSequencesReproduced=examples,exactFullGameFallbackChecks=fallback_checks,
                         completeDriveFuturesReproduced=drive_replays,
                         retainedGameDrawsReconciled=population_rows,protectedFilesVerified=len(protected['files']),
                         baselineCodeUnchanged=True,providerRequests=0,aispWrites=0,new2026Forecasts=0)
    # Preserve the first completion receipt so repeating replay does not invalidate its index.
    receipt_path=OUT/'replay-verification.json'
    if not receipt_path.exists():write(receipt_path,receipt)
    print(json.dumps(receipt),flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['audit','finalize-data','verify-preplay','fit','evaluate','report','index','replay'],required=True)
    p.add_argument('--season',type=int,choices=[2021,2022,2023,2024]);a=p.parse_args()
    if a.stage=='audit':audit()
    elif a.stage=='finalize-data':finalize_data()
    elif a.stage=='verify-preplay':verify_preplay_scores()
    elif a.stage=='fit':fit()
    elif a.stage=='evaluate':evaluate(a.season)
    elif a.stage=='report':report()
    elif a.stage=='index':index_artifacts()
    elif a.stage=='replay':replay()

if __name__=='__main__':main()
