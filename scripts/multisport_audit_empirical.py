"""Bounded historical grouped permutation audit; never a production refit.

Read paths are allowlisted. Data readers project columns and restrict season
before returning any labels. No current input snapshot or MLB outcome reader.
"""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from sklearn.metrics import roc_auc_score
from threadpoolctl import threadpool_limits
from run_multisport_feature_audit_v1 import ROOT,OUT,ref,write,now
from server.sports_nba_gen1.rest_support import feature_contract,transform_rest
from server.sports_nfl.gold import GAME_FEATURES
from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS,_fit_pair
from server.sports_nfl_m1.models import IndependentHomeAwayScoreModel
from server.sports_nfl_m1.contracts import XGBOOST_SCORE_CONFIG

SEED=9152601
NFL=Path('C:/Users/james/asp-data-staging/nfl/foundation-v1/objects/sha256/c13393c738f7629f4f7ff812069fa5cb29402e9bf08690e8d63586dacf9cd295/object.parquet')
NBA=ROOT/'outputs/nba-gen1-recent-v1'
REST=ROOT/'outputs/nba-gen1-long-gap-v1'
CFB=ROOT/'outputs/cfb-gen1-v1'

def clean(v):
    if isinstance(v,dict):return {str(k):clean(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)):return [clean(x) for x in v]
    if isinstance(v,np.ndarray):return clean(v.tolist())
    if isinstance(v,np.generic):return clean(v.item())
    if isinstance(v,float) and not np.isfinite(v):return None
    return v
def save(p,v):write(p,clean(v))
def digest(v):return hashlib.sha256(json.dumps(clean(v),sort_keys=True,separators=(',',':')).encode()).hexdigest()
def names(sport):return list(feature_contract()['numericFeatures'] if sport=='NBA' else GAME_FEATURES if sport=='NFL' else FEATURE_COLUMNS)
def family(sport,n):
    if sport=='NBA':
        if 'elo' in n:return 'ELO'
        if any(x in n for x in ['rest','back_to_back','games_last_']):return 'REST_SCHEDULE'
        if 'std' in n:return 'SCORING_VARIABILITY'
        if n.startswith('league_') or any(x in n for x in ['supported','weight','season_games','rolling_games','early_season','fallback']):return 'SUPPORT_LEAGUE'
        if 'prior_' in n:return 'PRIOR_SCORING'
        return 'RECENT_SCORING'
    if sport=='NFL':
        if '_epa_' in n:return 'EPA'
        if 'explosive' in n:return 'EXPLOSIVENESS'
        if 'success' in n:return 'SUCCESS'
        if any(x in n for x in ['conversion','red_zone']):return 'DOWN_RED_ZONE'
        if any(x in n for x in ['points_for','points_against']):return 'SCORING'
        if any(x in n for x in ['turnover','sack','penalty','seconds_per_play']):return 'TURNOVER_PRESSURE_PACE'
        return 'SCHEDULE_SUPPORT_VENUE'
    if 'elo' in n:return 'ELO'
    if 'trailing5' in n:return 'RECENT_FIVE'
    if 'prior_' in n:return 'PRIOR_SCORING'
    if 'yards' in n:return 'YARDAGE'
    if 'turnover' in n or 'takeaway' in n:return 'TURNOVERS'
    if 'points_' in n:return 'SEASON_SCORING'
    return 'SCHEDULE_SUPPORT_CONTEXT'

def declare():
    p=OUT/'EMPIRICAL_DESIGN.json'
    if p.exists():raise ValueError('Method already frozen')
    groups={s:{g:[n for n in names(s) if family(s,n)==g] for g in sorted({family(s,n) for n in names(s)})} for s in ['NBA','NFL','CFB']}
    assert all(len(g)<=8 for g in groups.values())
    sources=[NFL,NBA/'development/features.parquet',NBA/'validation/features.parquet',NBA/'holdout/features.parquet',CFB/'data/point-in-time-features.parquet',CFB/'data/season-forward-predictions.parquet']
    # Identity/schema metadata only; no labels are loaded in declaration.
    schemas={str(p):pq.read_schema(p).names for p in sources}
    save(p,dict(createdAtUtc=now(),seed=SEED,groups=groups,sourceSchemas=schemas,
      seasons={'Development':{'NBA':[2021,2022,2023],'NFL':[2022],'CFB':[2021,2022]},'ReusedLater':{'NBA':[2024,2025],'NFL':[2023,2024],'CFB':[2023,2024]}},
      method='One deterministic joint within-calendar-month row permutation per family and assessment season, fixed existing estimator/preprocessor. No drop-column refit, hyperparameter tuning, outcome-selected slices, probability calibration or distribution simulation. Each family keeps its own internal correlation and both side columns together. Cross-family dependencies can break; conditional incremental value is not identified.',
      baseline='NBA reload exact earlier-season corrected Ridge artifacts and match original point predictions. CFB reproduce fixed alpha100 earlier-season recipe and match stored season-forward predictions. NFL fit ONE frozen XGBoost recipe per origin on earlier 2000+ seasons only, research clone; do not load current all-history artifact containing 2025/2026 residuals. NFL proxy probabilities are not the published joint law.',
      probabilityMetrics='NBA Elo unchanged by point-family perturbations: no artificial point-to-probability conversion. NFL three-outcome distribution scores unavailable without simulation; binary diagnostics exclude actual ties and label the native normal-margin proxy. CFB native Development-only frozen calibrator evaluated only on later periods; Development probability diagnostics unavailable to avoid same-population calibration leakage.',
      metrics=['marginMAE','totalMAE','homeMAE','awayMAE','scoreMAE','logLoss','binaryBrier','AUC','accuracy','calibrationBias'],
      uncertainty='2000 paired calendar-week block bootstrap for margin/total/score error deltas; one permutation per family, so intervals condition on this perturbation and do not measure permutation variability.',
      stability='Every assessed season; HOME/AWAY error channels; pregame favorite/underdog by mean margin; support split; all individual teams with >=20 assessed exposures. No choosing subgroups after scores.',
      roles='Previously inspected historical evidence; no untouched test. All rows calendar<2026 and season<=2024 NFL/CFB, season_end<=2025 NBA; no MLB outcomes. Historical finalized source revisions acquired later do not certify original information availability.',
      boundaries='Allowlisted projected parquet reads; no generic current input snapshots; no production pickle load for NFL; no MLB labels. ACCESS_EXCEPTION.json remains disclosed separately.'))

def read(p,columns,season_col,max_season):
    allowed={NFL,*[NBA/s/'features.parquet' for s in ['development','validation','holdout']],CFB/'data/point-in-time-features.parquet',CFB/'data/season-forward-predictions.parquet',REST/'development/predictions.parquet',REST/'reused-diagnostics/predictions.parquet'}
    if p not in allowed:raise ValueError('Unregistered data path')
    f=pq.read_table(p,columns=list(dict.fromkeys(columns)),filters=[(season_col,'<=',max_season)]).to_pandas()
    assert f[season_col].le(max_season).all()
    date=next(c for c in ['game_date','scheduled_at'] if c in f)
    assert pd.to_datetime(f[date],utc=True).lt(pd.Timestamp('2026-01-01',tz='UTC')).all()
    return f

def frames(sport,stage):
    frozen=OUT/'permitted-input-projections'/f'{sport}.parquet'
    if frozen.exists():
        limit={'NBA':2023 if stage=='development' else 2025,'NFL':2022 if stage=='development' else 2024,'CFB':2022 if stage=='development' else 2024}[sport]
        f=pq.read_table(frozen,filters=[('audit_season','<=',limit)]).to_pandas()
        assert f.audit_season.le(limit).all()
        assert pd.to_datetime(f.game_date,utc=True).lt(pd.Timestamp('2026-01-01',tz='UTC')).all()
        return f
    if sport=='NBA':
        stages=['development'] if stage=='development' else ['development','validation','holdout']
        cols=names(sport)+['game_id','season_end','game_date','home_team_id','away_team_id','home_score','away_score','history_latest_game_date','target_eligible','neutral_site']
        f=pd.concat([read(NBA/s/'features.parquet',cols,'season_end',2023 if stage=='development' else 2025) for s in stages],ignore_index=True).drop_duplicates('game_id')
        f=f[f.target_eligible & ~f.neutral_site].copy()
        assert (pd.to_datetime(f.history_latest_game_date,utc=True).isna() | (pd.to_datetime(f.history_latest_game_date,utc=True)<pd.to_datetime(f.game_date,utc=True))).all()
        return f.rename(columns={'season_end':'audit_season','home_team_id':'home_team','away_team_id':'away_team'})
    if sport=='CFB':
        cols=names(sport)+['game_id','season','scheduled_at','home_id','away_id','home_margin','total_points','home_score','away_score','primary','is_final','feature_max_source_game_date']
        f=read(CFB/'data/point-in-time-features.parquet',cols,'season',2022 if stage=='development' else 2024)
        f=f[f.primary & f.is_final].copy()
        assert (pd.to_datetime(f.feature_max_source_game_date,utc=True).isna() | (pd.to_datetime(f.feature_max_source_game_date,utc=True)<pd.to_datetime(f.scheduled_at,utc=True))).all()
        return f.rename(columns={'season':'audit_season','scheduled_at':'game_date','home_id':'home_team','away_id':'away_team'})
    cols=names(sport)+['canonical_game_id','game_date','canonical_home_team_id','canonical_away_team_id','home_points','away_points','game_state','governed_population']
    f=read(NFL,cols,'season',2022 if stage=='development' else 2024)
    f=f[f.home_points.notna() & f.away_points.notna() & f.game_type.isin(['REG','POST'])].copy()
    return f.rename(columns={'canonical_game_id':'game_id','canonical_home_team_id':'home_team','canonical_away_team_id':'away_team','home_points':'home_score','away_points':'away_score'}).assign(audit_season=lambda z:z.season)

def ci(delta,dates,seed):
    v=np.asarray(delta,float); blocks=pd.to_datetime(dates,utc=True).dt.strftime('%G-%V'); ids=sorted(set(blocks))
    sums=np.array([v[blocks==b].sum() for b in ids]); ns=np.array([(blocks==b).sum() for b in ids]);rng=np.random.default_rng(seed)
    ii=rng.integers(0,len(ids),size=(2000,len(ids)));r=sums[ii].sum(1)/ns[ii].sum(1)
    return [float(x) for x in np.quantile(r,[.025,.975])]
def errors(y,pred):
    h,a=pred[:,0],pred[:,1];yh,ya=y[:,0],y[:,1]
    return dict(homeMAE=np.abs(h-yh),awayMAE=np.abs(a-ya),marginMAE=np.abs(h-a-yh+ya),totalMAE=np.abs(h+a-yh-ya),scoreMAE=(np.abs(h-yh)+np.abs(a-ya))/2)
def prob_metrics(y,p):
    if p is None:return None
    mask=y[:,0]!=y[:,1];t=(y[mask,0]>y[mask,1]).astype(int);v=np.clip(np.asarray(p)[mask],1e-12,1-1e-12)
    return dict(n=int(mask.sum()),excludedTies=int((~mask).sum()),logLoss=float(np.mean(-t*np.log(v)-(1-t)*np.log(1-v))),binaryBrier=float(np.mean((v-t)**2)),AUC=float(roc_auc_score(t,v)) if len(set(t))==2 else None,accuracy=float(np.mean((v>=.5)==t)),calibrationBias=float(np.mean(v-t)))

def execute(stage):
    design=json.loads((OUT/'EMPIRICAL_DESIGN.json').read_text())
    if stage=='later':
        if not (OUT/'DEVELOPMENT_REVIEW.json').exists():raise ValueError('Development review required')
    allresults=[]; allrows=[]; coefs=[]; coverage=[]; bindings=[]
    for sport in ['NBA','CFB','NFL']:
        f=frames(sport,stage).sort_values(['game_date','game_id']).reset_index(drop=True)
        assert not f.game_id.duplicated().any()
        seasons=design['seasons']['Development' if stage=='development' else 'ReusedLater'][sport]
        for year in seasons:
            tr=f[f.audit_season<year].copy();te=f[f.audit_season==year].copy().reset_index(drop=True)
            assert len(tr) and len(te) and pd.to_datetime(tr.game_date,utc=True).max()<pd.to_datetime(te.game_date,utc=True).min()
            cols=names(sport); modelref=None; pfunc=None
            if sport=='NBA':
                folder='development' if year<=2023 else 'reused-diagnostics'
                mpath=REST/folder/'models'/str(year)/'ridge_a100_rest.joblib';m=joblib.load(mpath);modelref=ref(mpath)
                assert set(m.training_game_ids)==set(tr.game_id)
                x,_=transform_rest(te.rename(columns={'audit_season':'season_end','home_team':'home_team_id','away_team':'away_team_id'}),m.rest_support)
                pipe=m.estimators['margin_total']; x=x[cols]
                def predict(z):
                    mt=pipe.predict(z.to_numpy(float));return np.column_stack(((mt[:,1]+mt[:,0])/2,(mt[:,1]-mt[:,0])/2))
                base=predict(x)
                pc=['game_id','season_end','game_date','expected_home_score','expected_away_score','model_id']
                old=read(REST/folder/'predictions.parquet',pc,'season_end',2023 if stage=='development' else 2025)
                old=old[old.model_id.str.contains('rest',case=False)].set_index('game_id').loc[te.game_id]
                oldvalues=old[['expected_home_score','expected_away_score']].to_numpy()
                coeff=pipe.named_steps['model'].coef_
                for j,n in enumerate(cols):coefs.append(dict(sport=sport,season=year,feature=n,family=family(sport,n),standardizedMargin=float(coeff[0,j]),standardizedTotal=float(coeff[1,j])))
                # Separate Elo channel is explicitly invariant to point-model feature perturbation.
                pbase=te.elo_home_win_probability.to_numpy();pfunc=lambda z:pbase
            elif sport=='CFB':
                # API expects original season name only in metadata; fixed 35 predictors unchanged.
                m=_fit_pair(tr,'ridge',{'alpha':100.0}); x=te[cols].copy()
                def predict(z):
                    mg=m['margin'].predict(z);tt=m['total'].predict(z);return np.column_stack(((tt+mg)/2,(tt-mg)/2))
                base=predict(x)
                old=read(CFB/'data/season-forward-predictions.parquet',['game_id','season','scheduled_at','ridge_alpha100_pred_home','ridge_alpha100_pred_away'],'season',2022 if stage=='development' else 2024).set_index('game_id').loc[te.game_id]
                oldvalues=old[['ridge_alpha100_pred_home','ridge_alpha100_pred_away']].to_numpy()
                for j,n in enumerate(cols):coefs.append(dict(sport=sport,season=year,feature=n,family=family(sport,n),standardizedMargin=float(m['margin'].named_steps['model'].coef_[j]),standardizedTotal=float(m['total'].named_steps['model'].coef_[j])))
                if stage=='later':
                    cal=joblib.load(CFB/'models/development-margin-calibrators.joblib')['ridge_alpha100']
                    pfunc=lambda z:cal.predict_proba(m['margin'].predict(z).reshape(-1,1))[:,1]
                pbase=None if pfunc is None else pfunc(x)
            else:
                tr=tr[tr.season>=2000]
                m=IndependentHomeAwayScoreModel(XGBOOST_SCORE_CONFIG,tuple(cols),seed=731001).fit(tr[cols],tr.home_score,tr.away_score,training_row_ids=tr.game_id)
                x=te[cols].copy()
                def predict(z):
                    r=m.predict(z);return np.column_stack((r.expected_home_points,r.expected_away_points))
                base=predict(x);oldvalues=base.copy();pfunc=lambda z:m.predict(z).home_win_probability;pbase=pfunc(x)
                expanded=m.preprocessor.transformer.get_feature_names_out().tolist()
                for channel,est in [('home',m.home_estimator),('away',m.away_estimator)]:
                    vals=est.get_booster().get_score(importance_type='total_gain')
                    for k,v in vals.items():coefs.append(dict(sport=sport,season=year,feature=expanded[int(k[1:])],channel=channel,totalGain=float(v),kind='DESCRIPTIVE_ONLY'))
            tolerance=float(np.max(np.abs(base-oldvalues)))
            assert tolerance<1e-6,(sport,year,'original baseline disagreement',tolerance)
            outmodel=OUT/'empirical'/stage/'models'/f'{sport}-{year}.joblib';outmodel.parent.mkdir(parents=True,exist_ok=True)
            if sport!='NBA':joblib.dump(m,outmodel,compress=3);modelref=ref(outmodel)
            for n in cols:
                vals=x[n];coverage.append(dict(sport=sport,season=year,feature=n,family=family(sport,n),n=len(x),missing=int(vals.isna().sum()),distinct=int(vals.nunique(dropna=True)),role='assessment input after governed treatment; constant does not mean absent'))
            y=te[['home_score','away_score']].to_numpy();b=errors(y,base)
            for group,gcols in design['groups'][sport].items():
                salt=int(hashlib.sha256(f'{sport}/{year}/{group}'.encode()).hexdigest()[:8],16);rng=np.random.default_rng(SEED+salt)
                perm=np.arange(len(te));months=pd.to_datetime(te.game_date,utc=True).dt.strftime('%Y-%m')
                for month in sorted(set(months)):
                    ix=np.flatnonzero(months==month);perm[ix]=rng.permutation(ix)
                xx=x.copy(deep=True);xx.loc[:,gcols]=x.iloc[perm][gcols].to_numpy()
                cp=predict(xx);e=errors(y,cp);bp=prob_metrics(y,pbase);cq=prob_metrics(y,None if pfunc is None else pfunc(xx))
                item=dict(sport=sport,season=year,role=stage,family=group,features=len(gcols),games=len(te),permutationSha256=digest(perm.tolist()),fixedRows=int((perm==np.arange(len(te))).sum()),baseline={k:float(v.mean()) for k,v in b.items()},perturbed={k:float(v.mean()) for k,v in e.items()},delta={k:float((e[k]-b[k]).mean()) for k in b},interval95={k:ci(e[k]-b[k],te.game_date,SEED) for k in ['marginMAE','totalMAE','scoreMAE']},baselineProbability=bp,perturbedProbability=cq)
                item['probabilityDelta']=None if bp is None else {k:cq[k]-bp[k] for k in ['logLoss','binaryBrier','AUC','accuracy','calibrationBias'] if bp[k] is not None}
                allresults.append(item)
                for i,r in te.iterrows():
                    low=(min(r.get('home_season_games_played',r.get('home_current_season_games',r.get('home_prior_season_games',99))),r.get('away_season_games_played',r.get('away_current_season_games',r.get('away_prior_season_games',99)))))<5
                    allrows.append(dict(sport=sport,season=year,role=stage,family=group,game_id=str(r.game_id),date=str(r.game_date),home_team=str(r.home_team),away_team=str(r.away_team),support='LOW_LT5' if low else 'HIGH_GE5',favoriteSide='HOME' if base[i,0]>=base[i,1] else 'AWAY',**{k:float(e[k][i]-b[k][i]) for k in b}))
            bindings.append(dict(sport=sport,season=year,trainN=len(tr),assessmentN=len(te),trainingLatest=str(tr.game_date.max()),assessmentEarliest=str(te.game_date.min()),trainIdSha256=digest(tr.game_id.tolist()),assessmentIdSha256=digest(te.game_id.tolist()),artifact=modelref,baselineMaxAbsoluteDifference=tolerance,baselineComparison='original frozen points' if sport!='NFL' else 'new fixed-recipe research clone; reload equality checked separately',expandedCount=len(expanded) if sport=='NFL' else len(cols)))
            check=predict(x);assert np.array_equal(base,check)
            print(json.dumps(dict(sport=sport,season=year,games=len(te),baselineDifference=tolerance)),flush=True)
    target=OUT/'empirical'/stage;target.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(allrows).to_parquet(target/'paired-error-deltas.parquet',index=False)
    pd.DataFrame(coverage).to_csv(target/'coverage.csv',index=False)
    save(target/'results.json',dict(createdAtUtc=now(),design=ref(OUT/'EMPIRICAL_DESIGN.json'),results=allresults,bindings=bindings))
    save(target/'coefficients-and-gain.json',coefs)
    if stage=='development':
        save(OUT/'DEVELOPMENT_REVIEW.json',dict(createdAtUtc=now(),results=ref(target/'results.json'),methodRetained=True,groupChanges=0,hyperparameterChanges=0,laterAccessAuthorized='Same frozen method on previously inspected later periods only; no 2026 rows. No performance-driven selection changes.'))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--stage',choices=['declare','development','later'],required=True);a=p.parse_args()
    with threadpool_limits(limits=1):
        if a.stage=='declare':declare()
        else:execute(a.stage)
