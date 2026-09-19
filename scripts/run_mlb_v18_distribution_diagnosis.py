"""Exploratory diagnostics of the already-inspected 90-game V18 cohort.

Read-only original inputs; no model fitting, provider access or production writes.
The optional logistic calibration regression is diagnostic only, never applied.
"""
from __future__ import annotations
import argparse, hashlib, json, math, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial.distance import cdist
from scipy.optimize import minimize
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast import mlb_starter_duration_quarantine as quarantine

RUNTIME = Path(r'C:\Users\james\asp-model-studio')
PREVIOUS = RUNTIME / 'outputs/mlb-v18-score-outlier-six-game-20260919-v1'
OUTPUT = RUNTIME / 'outputs/mlb-v18-score-distribution-diagnosis-20260919-v1'
CONFIG = {
 'schema':'MLB_V18_DISTRIBUTION_DIAGNOSTIC_V1',
 'status':'EXPLORATORY_ALREADY_INSPECTED_NOT_FRESH_HOLDOUT',
 'sourceTable':str(PREVIOUS/'game_results.csv'),
 'retainedOutcomeAsOfUtc':'2026-09-19T15:17:03.359113Z',
 'matureLocalDates':['2026-09-10','2026-09-17'],
 'expectedGames':90,'expectedSelected':31,'expectedUncertaintyMappingCases':7,
 'drawsPerGame':5000,'bootstrapUnit':'WHOLE_LOCAL_DATE','bootstrapReplicates':3000,
 'seed':20260919,'centralIntervals':[.5,.8,.95],
 'pit':'Fractional allocation of each discrete PIT interval [F(y-),F(y)] across ten equal bins; no random seed sensitivity',
 'probabilityBins':[0,.4,.45,.5,.55,.6,1],
 'favoriteProbabilityBins':[.5,.55,.6,1],
 'absoluteMeanMarginBins':[0,.5,1,100],
 'competingExplanations':[
 'Compression: descriptive actual-margin-on-predicted-margin slope above 1, with uncertainty; mean errors and model-defined favorite margin groups.',
 'Overdispersion: centered realized error variance below mean simulated variance; compare total, margin, home and away, discrete coverage/PIT and dependence.'
 ],
 'noCorrectionsApplied':True,'noMarketRelativeInference':True,
 'noResimulationClippingWeightSearchOrEarlyProspectiveAssessment':True,
 'newOutcomeAcquisition':False,
}

def now(): return datetime.now(timezone.utc).isoformat()
def ref(path):
    raw=Path(path).read_bytes()
    return {'path':str(Path(path).resolve()),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
def dump(path,obj):
    Path(path).write_text(json.dumps(obj,indent=2,allow_nan=False,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))+'\n',encoding='utf-8')
def crps(x,y):
    x=np.sort(np.asarray(x,dtype=float)); n=len(x)
    return float(np.mean(np.abs(x-y))-np.dot(2*np.arange(1,n+1)-n-1,x)/(n*n))
def energy(x,y):
    states,counts=np.unique(x,axis=0,return_counts=True); p=counts/len(x)
    return float(np.dot(p,np.linalg.norm(states-y,axis=1))-.5*p@cdist(states,states)@p)
def pit_fraction(lo,hi):
    edges=np.linspace(0,1,11)
    if hi==lo:
        out=np.zeros(10);out[min(9,int(lo*10))]=1;return out
    return np.maximum(0,np.minimum(edges[1:],hi)-np.maximum(edges[:-1],lo))/(hi-lo)
def slope(x,y):
    x=np.asarray(x);y=np.asarray(y);v=np.mean((x-x.mean())**2)
    return float(np.mean((x-x.mean())*(y-y.mean()))/v) if v>1e-15 else np.nan
def logit_fit(p,y):
    x=np.log(p/(1-p));y=np.asarray(y)
    def fun(b):
        z=b[0]+b[1]*x
        return np.sum(np.logaddexp(0,z)-y*z)
    result=minimize(fun,[0.,1.],method='BFGS')
    # BFGS can report precision loss after a valid stationary solution. Require
    # success or an independently checked small score gradient, never finiteness alone.
    z=result.x[0]+result.x[1]*x
    residual=1/(1+np.exp(-z))-y
    gradient=np.array([residual.sum(),np.dot(residual,x)])
    if not np.isfinite(result.fun) or np.max(np.abs(result.x))>100 or (not result.success and np.max(np.abs(gradient))>1e-4):return [np.nan,np.nan]
    return result.x.tolist()
def summary(d):
    r={'n':len(d),'dates':d.local_game_date.nunique()}
    for label in ['home','away','margin','total']:
        e=d[label+'_error'].to_numpy();v=d[label+'_var'].to_numpy()
        r.update({label+'_bias':float(e.mean()),label+'_mae':float(np.abs(e).mean()),
          label+'_rmse':float(np.sqrt(np.mean(e**2))),label+'_crps':float(d[label+'_crps'].mean()),
          label+'_simulated_sd_rms':float(np.sqrt(v.mean())),
          label+'_centered_error_variance_ratio':float(np.var(e)/v.mean()),
          label+'_mse_variance_ratio':float(np.mean(e**2)/v.mean())})
        for level in [50,80,95]:
            r[label+f'_coverage_{level}']=float(d[label+f'_covered_{level}'].mean())
            r[label+f'_model_mass_{level}']=float(d[label+f'_model_mass_{level}'].mean())
    r['team_mae']=float((d.home_error.abs()+d.away_error.abs()).mean()/2)
    r['team_rmse']=float(np.sqrt((d.home_error**2+d.away_error**2).mean()/2))
    for name in ['log_loss','brier','energy_score','joint_region_90_covered','joint_region_90_model_mass','favorite_probability','favorite_won','favorite_margin_pred','favorite_margin_actual','simulated_covariance','simulated_correlation','mcse_home_win','home_win_actual','p_home_win']:
        r[name]=float(d[name].mean())
    r['residual_home_away_covariance']=float(np.mean((d.home_error-d.home_error.mean())*(d.away_error-d.away_error.mean())))
    r['residual_home_away_correlation']=float(np.corrcoef(d.home_error,d.away_error)[0,1])
    r['margin_center_slope']=slope(d.v18_margin,d.actual_margin)
    r['total_center_slope']=slope(d.v18_total,d.actual_total)
    r['forecast_margin_sd']=float(d.v18_margin.std(ddof=0))
    r['forecast_home_probability_min']=float(d.p_home_win.min())
    r['forecast_home_probability_max']=float(d.p_home_win.max())
    return r

def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    config_path=OUTPUT/'CONFIG.json'
    if config_path.exists():
        if json.loads(config_path.read_text()) != CONFIG:raise ValueError('CONFIG_CHANGED')
    else:
        dump(config_path,CONFIG)
        dump(OUTPUT/'DESIGN_RECEIPT.json',{'declaredAtUtc':now(),'configuration':ref(config_path),'outcomesPreviouslyInspected':True,'newDiagnosticComputationStarted':False})
    quarantine.LEDGER=RUNTIME/'server/artifacts/governance/mlb-final-oot-quarantine-v1.json'
    quarantine.LEDGER_ARCHIVE=quarantine.LEDGER.parent/'mlb-final-oot-quarantine-history/sha256'
    if ref(CONFIG['sourceTable'])['sha256']!='7898155c845d5d737968e32d15a19cce6f687cc9252e9d9bd5e2792488e0b8b4':raise ValueError('REUSED_TABLE_CHANGED_FROM_PRIOR_DELIVERY')
    ids=pd.read_csv(CONFIG['sourceTable'],usecols=['game_id','source_game_id','local_game_date','forecast_identity'],dtype=str)
    gate=np.array(quarantine.final_oot_eligible_key_mask(ids.game_id.tolist())) & np.array(quarantine.final_oot_eligible_key_mask(ids.source_game_id.tolist()))
    if not gate.all() or not ids.local_game_date.between('2026-09-10','2026-09-18').all():raise ValueError('IDENTITY_OR_SEALED_DATE_GATE')
    allowed=set(ids.loc[ids.local_game_date.between(*CONFIG['matureLocalDates']),'game_id'])
    dump(OUTPUT/'IDENTITY_GATE.json',{'checkedAtUtc':now(),'identities':len(ids),'matureGameIds':sorted(allowed),'quarantine':ref(quarantine.LEDGER),'permanentExclusionsInThisTable':0,'sealedOutcomesLoaded':0,'laterOutcomesAdmitted':0,'studyIsFinalOot':False})
    # Outcome values are used only after identity and date quarantine checks.
    source=pd.read_csv(CONFIG['sourceTable'],keep_default_na=False)
    d=source.loc[source.game_id.isin(allowed)].copy()
    assert len(d)==90 and d.game_id.nunique()==90
    for flag in ['selected','uncertainty_defect_selection']:
        d[flag]=d[flag].astype(str).str.lower().eq('true')
    assert d.selected.sum()==31 and d.uncertainty_defect_selection.sum()==7
    for c in ['actual_home','actual_away','v18_home','v18_away','v18_margin','v18_total','p_home_win']:
        d[c]=pd.to_numeric(d[c],errors='raise')
    assert d[['actual_home','actual_away']].notna().all().all()
    keep=['game_id','source_game_id','forecast_identity','forecast_object_sha256','position_id','selected','population','uncertainty_defect_selection','uncertainty_defect_label','local_game_date','scheduled_start','input_captured_at','forecast_created_at','original_handoff_at','decision_cutoff_utc','home_team','away_team','pa_model_sha256','transition_model_sha256','numerical_identity_status','historical_deployment_attestation','distribution_ref','outcome_authority','outcome_source_revision','outcome_source_sha256','outcome_capture_utc','outcome_status','actual_home','actual_away','v18_home','v18_away','v18_margin','v18_total','p_home_win','selected_side','odds_american','odds_decimal','stake','profit_actual','expected_profit_raw','expected_profit_controlling','wager_result']
    d=d[[k for k in keep if k in d]].copy()
    refs=[ref(CONFIG['sourceTable']),ref(PREVIOUS/'VERIFICATION.json'),ref(PREVIOUS/'DELIVERY_RECEIPT.json'),ref(quarantine.LEDGER)]
    records=[];pit_records=[]
    for row in d.to_dict('records'):
        binding=json.loads(row['distribution_ref']);actual_ref=ref(binding['path'])
        if actual_ref['sha256']!=binding['sha256'] or actual_ref['bytes']!=binding['bytes']:raise ValueError('ORIGINAL_SIMULATION_BINDING_CHANGED')
        refs.append(actual_ref)
        population=json.loads(Path(binding['path']).read_text(encoding='utf-8-sig'))['population']
        home=np.array(population['homeRuns'],dtype=float);away=np.array(population['awayRuns'],dtype=float)
        assert len(home)==len(away)==5000 and np.all(home!=away) and np.all(home>=0) and np.all(away>=0)
        assert np.max(np.abs(home-np.round(home)))==0 and np.max(np.abs(away-np.round(away)))==0
        assert abs(home.mean()-row['v18_home'])<1e-10 and abs(away.mean()-row['v18_away'])<1e-10
        p=float(np.mean(home>away));assert abs(p-row['p_home_win'])<1e-12
        pair=np.column_stack([home,away]);target=np.array([row['actual_home'],row['actual_away']])
        row['actual_margin']=target[0]-target[1];row['actual_total']=target.sum()
        assert row['actual_margin']!=0
        for name,x,y in [('home',home,target[0]),('away',away,target[1]),('margin',home-away,row['actual_margin']),('total',home+away,row['actual_total'])]:
            row[name+'_error']=float(x.mean()-y) # forecast minus actual throughout
            row[name+'_var']=float(x.var());row[name+'_crps']=crps(x,y)
            lo=float(np.mean(x<y));hi=float(np.mean(x<=y))
            row[name+'_pit_lower']=lo;row[name+'_pit_upper']=hi;row[name+'_pit_midpoint']=(lo+hi)/2
            row[name+'_mass_at_outcome']=hi-lo
            pit_records.append({'game_id':row['game_id'],'local_game_date':row['local_game_date'],'target':name,**{f'bin_{i}':v for i,v in enumerate(pit_fraction(lo,hi))}})
            for level in [50,80,95]:
                alpha=(1-level/100)/2
                qlo,qhi=np.quantile(x,[alpha,1-alpha],method='inverted_cdf')
                row[name+f'_lower_{level}']=qlo;row[name+f'_upper_{level}']=qhi
                row[name+f'_covered_{level}']=int(qlo<=y<=qhi)
                row[name+f'_model_mass_{level}']=float(np.mean((qlo<=x)&(x<=qhi)))
        row['energy_score']=energy(pair,target)
        states,counts=np.unique(pair,axis=0,return_counts=True)
        sorted_counts=np.sort(counts)[::-1];threshold=sorted_counts[np.searchsorted(np.cumsum(sorted_counts),.9*len(pair))]
        included=counts>=threshold
        row['joint_region_90_model_mass']=float(counts[included].sum()/len(pair))
        row['joint_region_90_covered']=int(np.any(np.all(states[included]==target,axis=1)))
        row['simulated_covariance']=float(np.mean((home-home.mean())*(away-away.mean())))
        row['simulated_correlation']=float(np.corrcoef(home,away)[0,1])
        y=int(target[0]>target[1]);row['home_win_actual']=y
        row['log_loss']=float(-math.log(p if y else 1-p));row['brier']=float((p-y)**2)
        row['mcse_home_win']=float(np.sqrt(p*(1-p)/5000))
        sign=1 if p>=.5 else -1
        row['favorite_side']='home' if sign==1 else 'away'
        row['favorite_probability']=max(p,1-p);row['favorite_won']=int((target[0]-target[1])*sign>0)
        row['favorite_margin_pred']=float((home.mean()-away.mean())*sign)
        row['favorite_margin_actual']=float((target[0]-target[1])*sign)
        row['absolute_mean_margin']=abs(row['v18_margin'])
        row['winner_mean_sign_disagreement']=bool((home.mean()-away.mean())*sign<0)
        row['selected_probability']= (p if str(row.get('selected_side')).lower()=='home' else 1-p) if row['selected'] else None
        row['max_individual_team_draw']=int(max(home.max(),away.max()))
        row['prob_any_team_above_14']=float(np.mean((home>14)|(away>14)))
        row['actual_any_team_above_14']=int(np.max(target)>14)
        records.append(row)
    result=pd.DataFrame(records)
    result.to_csv(OUTPUT/'game_results.csv',index=False)
    pd.DataFrame(pit_records).to_csv(OUTPUT/'discrete_pit.csv',index=False)
    groups={'ALL':result,'SELECTED':result[result.selected],'NONSELECTED':result[~result.selected],
       'SEVEN_MAPPING_CASES':result[result.uncertainty_defect_selection],
       'OTHER_SELECTED':result[result.selected & ~result.uncertainty_defect_selection]}
    aggregates={name:summary(g) for name,g in groups.items()}
    pd.DataFrame(aggregates).T.to_csv(OUTPUT/'group_summary.csv',index_label='group')
    # Resample complete dates; never simulation draws or individual teams.
    rng=np.random.default_rng(CONFIG['seed']);dates=result.local_game_date.unique();blocks={day:result.index[result.local_game_date==day].to_numpy() for day in dates}
    metrics=['home_bias','away_bias','margin_bias','total_bias','margin_center_slope','total_center_slope','margin_centered_error_variance_ratio','total_centered_error_variance_ratio','home_centered_error_variance_ratio','away_centered_error_variance_ratio','residual_home_away_covariance','residual_home_away_correlation','log_loss','brier','energy_score','favorite_won','favorite_probability']
    boot={m:[] for m in metrics}
    coverage_keys=[f'{target}_{kind}_{level}' for target in ['margin','total'] for level in [50,80,95] for kind in ['coverage','model_mass']]
    boot.update({m:[] for m in coverage_keys})
    boot['favorite_win_minus_probability']=[]
    group_boot={name:{m:[] for m in ['log_loss','brier','favorite_win_minus_probability']} for name in ['SELECTED','NONSELECTED','SEVEN_MAPPING_CASES','OTHER_SELECTED']}
    for _ in range(CONFIG['bootstrapReplicates']):
        ix=np.concatenate([blocks[x] for x in rng.choice(dates,len(dates),replace=True)])
        s=summary(result.loc[ix])
        for m in metrics+coverage_keys:boot[m].append(s[m])
        boot['favorite_win_minus_probability'].append(s['favorite_won']-s['favorite_probability'])
        sample=result.loc[ix]
        masks={'SELECTED':sample.selected,'NONSELECTED':~sample.selected,'SEVEN_MAPPING_CASES':sample.uncertainty_defect_selection,'OTHER_SELECTED':sample.selected & ~sample.uncertainty_defect_selection}
        for name,mask in masks.items():
            g=sample[mask]
            if len(g):
                group_boot[name]['log_loss'].append(float(g.log_loss.mean()))
                group_boot[name]['brier'].append(float(g.brier.mean()))
                group_boot[name]['favorite_win_minus_probability'].append(float((g.favorite_won-g.favorite_probability).mean()))
    intervals={m:{'estimate':aggregates['ALL'].get(m,aggregates['ALL']['favorite_won']-aggregates['ALL']['favorite_probability']),
       'lower95':float(np.nanquantile(v,.025)),'upper95':float(np.nanquantile(v,.975))} for m,v in boot.items()}
    point_logit=logit_fit(result.p_home_win,result.home_win_actual)
    lboot=[]
    for _ in range(1000):
        ix=np.concatenate([blocks[x] for x in rng.choice(dates,len(dates),replace=True)])
        lboot.append(logit_fit(result.loc[ix].p_home_win,result.loc[ix].home_win_actual))
    logit={'intercept':point_logit[0],'slope':point_logit[1],'bootstrapReplicates':1000,'usableReplicates':int(np.isfinite(lboot).all(axis=1).sum()),'lower95':np.nanquantile(lboot,.025,axis=0).tolist(),'upper95':np.nanquantile(lboot,.975,axis=0).tolist(),'appliedToPredictions':False}
    bins=[]
    for name,field,edges in [('home_probability','p_home_win',CONFIG['probabilityBins']),('favorite_probability','favorite_probability',CONFIG['favoriteProbabilityBins']),('absolute_mean_margin','absolute_mean_margin',CONFIG['absoluteMeanMarginBins'])]:
        cut=pd.cut(result[field],edges,include_lowest=True)
        for label,g in result.groupby(cut,observed=True):
            s=summary(g);bins.append({'grouping':name,'bin':str(label),**s})
    pd.DataFrame(bins).to_csv(OUTPUT/'calibration_bins.csv',index=False)
    wagers=[]
    selected=result[result.selected].copy()
    selected['model_selected_underdog']=selected.selected_probability<.5
    for name,g in [('ALL',selected),('MODEL_FAVORITE',selected[~selected.model_selected_underdog]),('MODEL_UNDERDOG',selected[selected.model_selected_underdog]),('SEVEN_MAPPING_CASES',selected[selected.uncertainty_defect_selection])]:
        if not len(g):continue
        won=(g.actual_margin>0)==g.selected_side.astype(str).str.lower().eq('home')
        assert (won.to_numpy()==g.wager_result.astype(str).str.upper().eq('WIN').to_numpy()).all(), 'WAGER_RESULT_ORIENTATION_MISMATCH'
        wagers.append({'group':name,'n':len(g),'wins':int(won.sum()),'losses':int((~won).sum()),'mean_original_probability':float(g.selected_probability.mean()),'mean_decimal_odds':float(pd.to_numeric(g.odds_decimal).mean()),**{c:float(pd.to_numeric(g[c]).sum()) for c in ['stake','profit_actual','expected_profit_raw','expected_profit_controlling']}})
    pd.DataFrame(wagers).to_csv(OUTPUT/'original_wager_groups.csv',index=False)
    # Reconcile reused baseline rather than re-running the previous study.
    previous=source[source.game_id.isin(allowed)].set_index('game_id')
    assert abs(aggregates['ALL']['team_mae']-pd.to_numeric(previous.v18_team_mae).mean())<1e-10
    assert abs(aggregates['ALL']['log_loss']-pd.to_numeric(previous.v18_log_loss).mean())<1e-10
    assert abs(aggregates['ALL']['brier']-pd.to_numeric(previous.v18_brier).mean())<1e-10
    group_ci={name:{m:{'lower95':float(np.quantile(v,.025)),'upper95':float(np.quantile(v,.975)),'nonemptyReplicates':len(v)} for m,v in values.items()} for name,values in group_boot.items()}
    dump(OUTPUT/'SUMMARY.json',{'computedAtUtc':now(),'groups':aggregates,'dateBlockIntervals':intervals,'groupDateBlockIntervals':group_ci,'logisticDiagnostic':logit,'winnerMeanSignDisagreements':int(result.winner_mean_sign_disagreement.sum()),'dateCounts':result.local_game_date.value_counts().to_dict(),'wagers':wagers,'severeTail':{'meanPredictedAnyTeamAbove14':float(result.prob_any_team_above_14.mean()),'actualCount':int(result.actual_any_team_above_14.sum())},'coverageExclusions':{'laterUnscoredForecasts':15,'legacyModelsSeparate':True,'sealedAndQuarantinedGamesLoaded':0}})
    dump(OUTPUT/'SOURCE_INDEX.json',{'configuration':ref(config_path),'sources':refs,'code':ref(__file__),'reuse':'Exact prior population/authority reconciliation reused; physical simulation hashes and point/probability moments checked here.'})
    plots(result,pd.DataFrame(pit_records),intervals,bins)
    dump(OUTPUT/'VERIFICATION.json',{'atUtc':now(),'status':'PASS','games':90,'dates':8,'selected':31,'uncertaintyMappingCases':7,'originalDraws':450000,'allOriginalPopulationHashesMatch':True,'allPairedIntegerNoTiePopulationsMatch':True,'priorMeanLogLossBrierReconciliation':True,'simulationDrawsUsedAsIndependentObservations':False,'noProductionChanges':True,'newProviderRequests':0,'newOutcomesLoaded':0,'noEarlyProspectiveAssessment':True})
    print(json.dumps({'output':str(OUTPUT),'all':aggregates['ALL'],'ci':intervals,'logit':logit},indent=2))

def plots(d,pit,ci,bins):
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':130})
    colors={False:'#607d8b',True:'#c26432'}
    fig,axs=plt.subplots(1,3,figsize=(14,4.3),layout='constrained')
    for selected,g in d.groupby('selected'):
        for ax,x,y in [(axs[0],'v18_margin','actual_margin'),(axs[1],'v18_total','actual_total')]:
            ax.scatter(g[x],g[y],c=colors[selected],alpha=.7,s=28,label='Selected' if selected else 'Nonselected')
    axs[0].axhline(0,color='#bbb',lw=.7);axs[0].plot([-3,3],[-3,3],color='#222',lw=1,label='Perfect center')
    axs[0].set(xlabel='Original predicted home − away runs',ylabel='Actual home − away runs',title='A narrow range of forecast margins')
    axs[1].plot([6,12],[6,12],color='#222',lw=1);axs[1].set(xlabel='Original predicted total runs',ylabel='Actual total runs',title='Game totals: center versus result')
    targets=['home','away','margin','total'];vals=[ci[t+'_bias']['estimate'] for t in targets]
    err=np.array([[v-ci[t+'_bias']['lower95'] for t,v in zip(targets,vals)],[ci[t+'_bias']['upper95']-v for t,v in zip(targets,vals)]])
    axs[2].errorbar(vals,targets,xerr=err,fmt='o',color='#35618d',capsize=3);axs[2].axvline(0,color='#999',lw=1)
    axs[2].set(xlabel='Forecast − actual runs; 95% date-block interval',title='Average bias is not variance calibration')
    axs[0].legend(fontsize=8);fig.suptitle('V18 scoring centers · 90 inspected games / 8 dates',fontsize=14)
    fig.savefig(OUTPUT/'01_scoring_centers.png');plt.close(fig)
    fig,axs=plt.subplots(2,2,figsize=(11,8),layout='constrained')
    for j,target in enumerate(['margin','total']):
        model=[];obs=[];err=[]
        for level in [50,80,95]:
            k=f'{target}_coverage_{level}';obs.append(ci[k]['estimate']);model.append(ci[f'{target}_model_mass_{level}']['estimate']);err.append([ci[k]['estimate']-ci[k]['lower95'],ci[k]['upper95']-ci[k]['estimate']])
        axs[0,j].errorbar(model,obs,yerr=np.array(err).T,fmt='o',color='#35618d',capsize=4)
        axs[0,j].plot([.45,1],[.45,1],color='#999',ls='--');axs[0,j].set(xlim=(.45,1.01),ylim=(.4,1.01),xlabel='Actual model mass inside integer interval',ylabel='Observed coverage',title=target.title()+' intervals (50%, 80%, 95%)')
        masses=pit[pit.target==target][[f'bin_{i}' for i in range(10)]].mean().to_numpy()
        axs[1,j].bar(np.arange(10)/10+.05,masses,width=.085,color='#607d8b');axs[1,j].axhline(.1,color='#c26432',ls='--')
        axs[1,j].set(xlabel='Discrete PIT (fractionally allocated)',ylabel='Fraction of games',title=target.title()+': tails versus center',xticks=[0,.25,.5,.75,1])
    fig.suptitle('V18 distribution shape · coverage uncertainty resamples dates',fontsize=14);fig.savefig(OUTPUT/'02_distribution_shape.png');plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(11,4.5),layout='constrained')
    for name,color in [('ALL','#35618d'),('SELECTED','#c26432'),('NONSELECTED','#607d8b')]:
        g=d if name=='ALL' else d[d.selected.eq(name=='SELECTED')]
        cut=pd.cut(g.p_home_win,CONFIG['probabilityBins'],include_lowest=True)
        points=g.groupby(cut,observed=True).agg(p=('p_home_win','mean'),y=('home_win_actual','mean'),n=('game_id','size'))
        axs[0].plot(points.p,points.y,'o-',color=color,label=name.title(),alpha=.9)
        if name=='ALL':
            for _,r in points.iterrows():axs[0].annotate(f'n={int(r.n)}',(r.p,r.y),xytext=(3,5),textcoords='offset points',fontsize=8)
    axs[0].plot([.3,.7],[.3,.7],ls='--',color='#999');axs[0].set(xlabel='Original home-win probability',ylabel='Observed home-win fraction',title='Small probability bins are descriptive',ylim=(0,1));axs[0].legend(fontsize=8)
    v=[ci[t+'_centered_error_variance_ratio']['estimate'] for t in ['home','away','margin','total']]
    er=np.array([[x-ci[t+'_centered_error_variance_ratio']['lower95'] for t,x in zip(['home','away','margin','total'],v)],[ci[t+'_centered_error_variance_ratio']['upper95']-x for t,x in zip(['home','away','margin','total'],v)]])
    axs[1].errorbar(v,['home','away','margin','total'],xerr=er,fmt='o',color='#35618d',capsize=3);axs[1].axvline(1,color='#999',ls='--')
    axs[1].set(xlabel='Centered realized error variance / simulated variance',title='Below 1: evidence compatible with excess spread')
    fig.suptitle('Winner calibration and competing variance explanation',fontsize=14);fig.savefig(OUTPUT/'03_probability_and_dispersion.png');plt.close(fig)

if __name__=='__main__':main()
