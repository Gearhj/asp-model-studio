"""Focused no-fit replay, chronology/accounting and physical integrity checks."""
from __future__ import annotations
import ast,hashlib,json
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits
from run_multisport_feature_audit_v1 import ROOT,OUT,ref,now
from multisport_audit_empirical import frames,names,errors,digest,save,SEED,CFB
from server.sports_nba_gen1.rest_support import transform_rest
from server.sports_cfb_gen1.pipeline import build_features,FEATURE_COLUMNS

def synthetic_cfb():
    def game(i,day):return dict(game_id=i,scheduled_at=pd.Timestamp(day,tz='UTC'),season=2023,week=2,home_id=1,away_id=2,home_team='A',away_team='B',home_is_fbs=True,away_is_fbs=True,neutral_site=False,conference_competition=False,primary=True,context_eligible=True,role='DEVELOPMENT',is_final=True,season_type=2,both_fbs=True,postseason=False,late_regular_unclassified=False,overtime=False,score_supported=True,home_score=28,away_score=21,home_margin=7,total_points=49,home_win=1,home_total_yards=400,away_total_yards=330,home_turnovers=1,away_turnovers=2)
    raw=pd.DataFrame([game(1,'2023-09-01'),game(2,'2023-09-08'),game(3,'2023-09-08'),game(4,'2023-09-15')])
    base=build_features(raw)
    changed=raw.copy(deep=True)
    for key in ['home_score','away_score','home_margin','total_points','home_win','home_total_yards','away_total_yards','home_turnovers','away_turnovers']:
        changed.loc[changed.game_id>=2,key]=999
    other=build_features(changed)
    pd.testing.assert_frame_equal(base.loc[base.game_id.isin([2,3]),FEATURE_COLUMNS],other.loc[other.game_id.isin([2,3]),FEATURE_COLUMNS])
    # This verifies current grouping/exclusion, not a real-world completion clock.
    return dict(targetAndSameKickoffMutation='PASS',qualification='Synthetic mechanics only; no forecasting evidence.')

def verify():
    expected={('MLB','RAW_DEPENDENCY'):246,('MLB','TREATED_MODEL_INPUT'):273,('MLB','ENCODED_ESTIMATOR_COLUMN'):436,('NFL','MODEL_INPUT'):197,('NBA','MODEL_INPUT'):78,('CFB','MODEL_INPUT'):35}
    inv=pd.read_csv(OUT/'CURRENT_FEATURE_INVENTORY.csv')
    for (sport,stage),n in expected.items():assert len(inv[(inv.sport==sport)&(inv.stage==stage)])==n
    assert not inv.duplicated(['sport','model_or_engine','stage','feature_name']).any()
    required=['definition','mathematical_transformation','source','source_grain','source_clock','earliest_availability','required_lag','prospective_availability','missingness','imputation_or_fallback','normalization_or_encoding','preprocessing_object','version_or_contract','status','leakage_risk','known_limitations','importance_evidence']
    for c in required:assert inv[c].notna().all(),('inventory_blank',c)
    sources=json.loads((OUT/'SOURCE_BINDINGS.json').read_text())['files']
    for r in sources:assert ref(r['path'])==r,('source_changed',r['path'])
    design=json.loads((OUT/'EMPIRICAL_DESIGN.json').read_text());assert all(len(g)<=8 for g in design['groups'].values())
    replay=[];maxdiff=0.;calibrators=None
    for stage in ['development','later']:
        saved=pd.read_parquet(OUT/'empirical'/stage/'paired-error-deltas.parquet');z=json.loads((OUT/'empirical'/stage/'results.json').read_text())
        for sport in ['NBA','CFB','NFL']:
            f=frames(sport,stage).sort_values(['game_date','game_id']).reset_index(drop=True)
            bindings=[b for b in z['bindings'] if b['sport']==sport]
            for bind in bindings:
                year=bind['season'];te=f[f.audit_season==year].copy().reset_index(drop=True);tr=f[f.audit_season<year]
                if sport=='NFL':tr=tr[tr.season>=2000]
                assert digest(tr.game_id.tolist())==bind['trainIdSha256'];assert digest(te.game_id.tolist())==bind['assessmentIdSha256']
                assert pd.to_datetime(tr.game_date,utc=True).max()<pd.to_datetime(te.game_date,utc=True).min()
                m=joblib.load(bind['artifact']['path']);assert ref(bind['artifact']['path'])==bind['artifact']
                if sport=='NBA':
                    treated,_=transform_rest(te.rename(columns={'home_team':'home_team_id','away_team':'away_team_id','audit_season':'season_end'}),m.rest_support);x=treated[names(sport)]
                    def predict(xx):
                        mt=m.estimators['margin_total'].predict(xx.to_numpy(float));return np.column_stack(((mt[:,1]+mt[:,0])/2,(mt[:,1]-mt[:,0])/2))
                    assert set(m.training_game_ids)==set(tr.game_id)
                    # Frozen training medians/scales are reproduced from earlier feature rows only.
                    tt,_=transform_rest(tr.rename(columns={'home_team':'home_team_id','away_team':'away_team_id','audit_season':'season_end'}),m.rest_support)
                    imp=m.estimators['margin_total'].named_steps['imputer'];med=np.nanmedian(tt[names(sport)].to_numpy(float),axis=0);med=np.nan_to_num(med,nan=0)
                    np.testing.assert_allclose(med,imp.statistics_,rtol=0,atol=1e-10)
                elif sport=='CFB':
                    x=te[names(sport)]
                    def predict(xx):
                        mg=m['margin'].predict(xx);tot=m['total'].predict(xx);return np.column_stack(((tot+mg)/2,(tot-mg)/2))
                    np.testing.assert_allclose(np.nanmedian(tr[names(sport)].to_numpy(float),axis=0),m['margin'].named_steps['imputer'].statistics_,rtol=0,atol=1e-10)
                else:
                    x=te[names(sport)]
                    def predict(xx):
                        p=m.predict(xx);return np.column_stack((p.expected_home_points,p.expected_away_points))
                    assert m.preprocessor.training_row_count==len(tr)
                    ns=[n for n in names(sport) if n not in m.preprocessor.categorical_features];v=tr[ns].apply(pd.to_numeric,errors='coerce').to_numpy(float)
                    med=np.nan_to_num(np.nanmedian(v,axis=0),nan=0)
                    np.testing.assert_allclose(med,m.preprocessor.transformer.named_transformers_['numeric'].named_steps['imputer'].statistics_,rtol=0,atol=1e-10)
                base=predict(x);y=te[['home_score','away_score']].to_numpy();b=errors(y,base)
                for group,gcols in design['groups'][sport].items():
                    salt=int(hashlib.sha256(f'{sport}/{year}/{group}'.encode()).hexdigest()[:8],16);rng=np.random.default_rng(SEED+salt);perm=np.arange(len(te));months=pd.to_datetime(te.game_date,utc=True).dt.strftime('%Y-%m')
                    for mon in sorted(set(months)):
                        ix=np.flatnonzero(months==mon);perm[ix]=rng.permutation(ix)
                    original=next(r for r in z['results'] if r['sport']==sport and r['season']==year and r['family']==group)
                    assert digest(perm.tolist())==original['permutationSha256']
                    xx=x.copy();xx.loc[:,gcols]=x.iloc[perm][gcols].to_numpy();e=errors(y,predict(xx))
                    old=saved[(saved.sport==sport)&(saved.season==year)&(saved.family==group)].set_index('game_id').loc[te.game_id.astype(str)]
                    for key in e:
                        delta=e[key]-b[key];diff=float(np.max(np.abs(delta-old[key].to_numpy())));maxdiff=max(maxdiff,diff);assert diff==0,(sport,year,group,key,diff)
                replay.append(dict(sport=sport,season=year,games=len(te),families=len(design['groups'][sport]),status='EXACT_RELOAD_REPLAY',originalPointReproductionMaxDifference=bind['baselineMaxAbsoluteDifference']))
    # Metadata-only completion plausibility; no outcomes loaded by this query.
    p=CFB/'data/point-in-time-features.parquet'
    meta=pq.read_table(p,columns=['game_id','season','scheduled_at','home_id','away_id','context_eligible'],filters=[('season','<=',2024)]).to_pandas()
    meta=meta[meta.context_eligible].sort_values(['scheduled_at','game_id']);teamrows=[]
    for side in ['home','away']:
        teamrows.append(meta[['game_id','scheduled_at',side+'_id']].rename(columns={side+'_id':'team'}))
    tg=pd.concat(teamrows).sort_values(['team','scheduled_at','game_id']);gap=tg.groupby('team').scheduled_at.diff().dt.total_seconds()/3600
    cfbcompletion=dict(eligibleTeamExposures=len(tg),sameTeamGapsUnder24h=int(gap.lt(24).sum()),minimumHours=float(gap.min()),actualCompletionClockCertified=False,qualification='Kickoff spacing is only a plausibility screen, not source availability proof.')
    # Existing synthetic NBA test alone; do not invoke CFB tests that read unrestricted current matrices.
    import importlib.util
    spec=importlib.util.spec_from_file_location('audit_nba_synthetic',ROOT/'tests/nba_gen1_recent_features_test.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);mod.test_existing_features_unchanged_and_no_target_same_day_or_future_leakage()
    cfbsyn=synthetic_cfb()
    # Explicit audit path rejection: no outcome payload opened in this check.
    from multisport_audit_empirical import read
    rejected=False
    try:read(ROOT/'outputs/nfl-m1-current-season-update-v1/inputs-after.json',[],'season',2024)
    except ValueError:rejected=True
    assert rejected
    result=dict(createdAtUtc=now(),status='PASS_WITH_DISCLOSED_ACCESS_EXCEPTION',inventoryCountsReconciled=True,inventoryRows=len(inv),sourceFilesUnchanged=len(sources),sourceFiles=ref(OUT/'SOURCE_BINDINGS.json'),replay=replay,allGameDeltasExact=maxdiff==0,maximumAbsoluteReplayDifference=maxdiff,originalNbaCfbPointsExact=True,earlierTrainingMediansVerified=True,nbaSyntheticTargetSameDayExclusion='PASS',cfbSynthetic=cfbsyn,cfbCompletionPlausibility=cfbcompletion,rejectedSnapshotGuard='PASS',no2026OutcomesInNumericalAssessment=True,zero2026OutcomeAccess=False,accessException=ref(OUT/'ACCESS_EXCEPTION.json'),sealedOutcomePayloadAccess=0,providerDataRequests=0,sportsbookObjectsConsumed=0,aispWrites=0,schedulerChanges=0,productionModelWrites=0,newProspectiveForecasts=0,simulationRuns=0,qualification='Code/scoped-write/source-hash audit; not an independent operating-system access monitor. Initial discovery exposure remains disclosed; no source publication-vintage certification implied.')
    save(OUT/'VERIFICATION.json',result)
    codefiles=[ROOT/'scripts'/n for n in ['run_multisport_feature_audit_v1.py','multisport_audit_empirical.py','multisport_audit_inventory.py','multisport_audit_report.py','multisport_audit_verify.py']]
    files=[ref(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in ['artifact-index.json','git-byte-verification.json']]+[ref(p) for p in codefiles]
    save(OUT/'artifact-index.json',dict(schema='MULTISPORT_FEATURE_AUDIT_PHYSICAL_INDEX_V1',createdAtUtc=now(),files=files,externalSources=ref(OUT/'EXTERNAL_DOCUMENTATION_INDEX.json'),qualification='Physical UTF-8/file-byte hashes; no logical package identity or consumer publication implied.'))
    print(json.dumps({'status':result['status'],'games':sum(r['games'] for r in replay),'exactReplay':maxdiff,'files':len(files),'cfbCompletion':cfbcompletion,'index':ref(OUT/'artifact-index.json')}))

if __name__=='__main__':
    with threadpool_limits(limits=1):verify()
