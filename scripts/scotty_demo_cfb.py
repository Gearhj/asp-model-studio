"""One prospective weekend baseline from retained, already admitted CFB inputs.

No acquisition, fitting, evaluation, challenger, current-pointer replacement,
or scheduler activation. Uses the unchanged Gen 1 prediction/simulation code.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.scotty_demo_release import canonical,sha,physical,checked,read,write,now,clock,NY,joint_summary,agree


def build(studio:Path, output:Path):
    import joblib
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS,predict_artifact,simulate_paired_residuals
    from server.sports_cfb_gen1.current import population_tables,interval_table,totals_probabilities
    output.mkdir(parents=True,exist_ok=True)
    done=output/'forecast.json'
    if done.exists():
        f=read(done)
        for r in f['demoReproduction']['sourceBindings']:checked(r)
        draws=pd.read_parquet(output/'baseline-joint-draws.parquet')
        s=joint_summary(draws.home_score,draws.away_score)
        agree(s['homeWin'],f['baseline']['jointHomeWinProbability'])
        return f
    current=studio/'outputs/cfb-gen1-current-v1';hist=studio/'outputs/cfb-gen1-v1'
    fp=current/'cfbd-2026-point-in-time-features.parquet'
    metadata_columns=['game_id','scheduled_at','season','is_final','both_fbs','season_type',
        'away_id','home_id','away_team','home_team','neutral_site','conference_competition','feature_max_source_game_date']
    metadata=pd.read_parquet(fp,columns=metadata_columns)
    # Select solely by schedule/support, before loading the selected feature row.
    coverage=pd.read_parquet(current/'current-history-coverage.parquet')
    support=coverage.groupby('game_id').eligible.all()
    dates=metadata.scheduled_at.dt.tz_convert(NY).dt.date.astype(str)
    eligible=metadata[(metadata.season==2026)&~metadata.is_final&metadata.both_fbs
        &(metadata.season_type==2)&dates.isin(['2026-09-19','2026-09-20'])
        &metadata.game_id.isin(support[support].index)
        &(metadata.scheduled_at>pd.Timestamp.now(tz='UTC')+pd.Timedelta(minutes=60))]
    if eligible.empty:raise ValueError('NO_ELIGIBLE_RETAINED_WEEKEND_TARGET')
    meta=eligible.sort_values(['scheduled_at','game_id']).iloc[0]
    game_id=int(meta.game_id)
    cutoff=read(current/'current-history-coverage-receipt.json')['sourceCutoff']
    selected={'schemaVersion':'ASP_SCOTTY_CFB_TARGET_SELECTION_V1','selectedAtUtc':now(),
        'selectionRule':'Earliest Saturday/Sunday America/New_York kickoff, then CFBD game ID; FBS/FBS, regular season, both sides eligible, T-60 still open',
        'gameId':game_id,'sourceCutoffUtc':cutoff,'eligibleTargetCount':len(eligible),
        'noTargetOutcomesLoaded':True,'metadataColumns':metadata_columns,
        'featurePopulation':physical(fp),'coveragePopulation':physical(current/'current-history-coverage.parquet')}
    write(output/'target-selection.json',selected)
    cols=list(dict.fromkeys(metadata_columns+FEATURE_COLUMNS+['elo_home_win_probability']))
    target=pd.read_parquet(fp,columns=cols,filters=[('game_id','=',game_id)]).iloc[0].copy()
    if not target.feature_max_source_game_date<pd.Timestamp(cutoff)<target.scheduled_at:
        raise ValueError('CFB_FEATURE_CUTOFF')
    teams=coverage[coverage.game_id==game_id]
    if len(teams)!=2 or not teams.eligible.all() or not teams.noTargetStats.all():raise ValueError('CFB_TEAM_SUPPORT')
    sp=current/'cfbd-2026-adapted-schedule.parquet'
    sm=pd.read_parquet(sp,columns=[c for c in metadata_columns if c in pq.read_schema(sp).names],filters=[('game_id','=',game_id)])
    if len(sm)!=1:raise ValueError('CFB_SCHEDULE_IDENTITY')
    for name in ['game_id','scheduled_at','home_id','away_id','home_team','away_team']:
        if sm.iloc[0][name]!=target[name]:raise ValueError('CFB_SCHEDULE_ORIENTATION')
    source_forecast=read(current/'forecast/forecast.json')
    for name in ['selectedModel','developmentCalibrator','featureContract','pairedResidualPopulation']:
        checked(source_forecast['modelBindings'][name])
    model=joblib.load(hist/'models/selected-through-2025.joblib')
    calibrator=joblib.load(hist/'models/development-margin-calibrators.joblib')['ridge_alpha100']
    # Donor metadata first; never load 2026 target labels or fit anything.
    dp=hist/'data/season-forward-predictions.parquet'
    dm=pd.read_parquet(dp,columns=['season','scheduled_at','game_id'])
    if not (dm.season<2026).all() or not (dm.scheduled_at<pd.Timestamp(cutoff)).all():raise ValueError('CFB_DONOR_CUTOFF')
    donors=pd.read_parquet(dp,columns=['game_id','season','scheduled_at','home_score','away_score',
                                    'ridge_alpha100_pred_home','ridge_alpha100_pred_away'])
    point=predict_artifact(model,target.to_frame().T)
    for k,v in [('pred_home',point['homePoints']),('pred_away',point['awayPoints'])]:target['ridge_alpha100_'+k]=v
    draws,accounting=simulate_paired_residuals(target,donors,'ridge_alpha100')
    draws.to_parquet(output/'baseline-joint-draws.parquet',index=False)
    population_tables(game_id,draws).to_parquet(output/'baseline-pmfs.parquet',index=False)
    s=joint_summary(draws.home_score,draws.away_score)
    if s['drawCount']!=10000 or s['tie']!=0:raise ValueError('CFB_POPULATION')
    ph=float(calibrator.predict_proba(np.array([[point['homeMargin']]]))[0,1]);pe=float(target.elo_home_win_probability)
    values={k:(None if pd.isna(target[k]) else float(target[k])) for k in FEATURE_COLUMNS}
    game={k:target[k] for k in ['game_id','scheduled_at','away_id','home_id','away_team','home_team','neutral_site','conference_competition']}
    game=json.loads(json.dumps(game,default=lambda v:v.isoformat() if hasattr(v,'isoformat') else v.item()))
    identity={'gameId':game_id,'sourceCutoff':cutoff,'configuration':'CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1',
        'modelSha256':physical(hist/'models/selected-through-2025.joblib')['sha256'],
        'featureValuesSha256':sha(canonical(values)), 'drawsSha256':physical(output/'baseline-joint-draws.parquet')['sha256']}
    baseline={'configuration':identity['configuration'],'drawCount':10000,
        'expectedAwayPoints':point['awayPoints'],'expectedHomePoints':point['homePoints'],
        'expectedTotal':point['totalPoints'],'expectedHomeMargin':point['homeMargin'],
        'ridgeHomeWinProbability':ph,'ridgeAwayWinProbability':1-ph,
        'eloHomeWinProbability':pe,'eloAwayWinProbability':1-pe,
        'jointHomeWinProbability':s['homeWin'],'jointAwayWinProbability':s['awayWin'],'tieProbability':0,
        'intervals':interval_table(draws),'transformationAccounting':accounting,
        'illustrativeTotals':[totals_probabilities(draws,float(round(point['totalPoints']))),totals_probabilities(draws,math.floor(point['totalPoints'])+.5)]}
    f={'schemaVersion':'CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1','forecastId':'cfb-gen1:'+sha(canonical(identity)),
        'createdAt':now(),'publishedAt':None,'status':'FROZEN_LOCAL_RESEARCH_FORECAST',
        'game':game,'sourceCutoff':cutoff,'scheduleRevisionCapturedAt':source_forecast['scheduleRevisionCapturedAt'],
        'baseline':baseline,'challenger':{'publishedAsSecondArm':False,'configuration':None},
        'modelBindings':source_forecast['modelBindings'],'sourceBindings':{'cfbdManifest':physical(current/'cfbd-source-manifest.json'),
            'retainedSchedule':physical(sp),'targetSelection':physical(output/'target-selection.json')},
        'featureValues':values,'limitations':source_forecast['limitations']+[
            'Early snapshot from September 14 inputs; later news and schedule revisions are not certified.',
            'CFBD identity supplied; exact AISP event binding still requires consumer acknowledgement.',
            'Frozen Ridge point means differ from finite-sample, transformed joint means; retain separate channels.'],
        'researchOnly':True,'aispAuthority':False,'wageringAuthority':False,'schedulerAuthority':False,
        'demoReproduction':{'sourceBindings':[physical(fp),physical(sp),physical(dp),physical(hist/'models/selected-through-2025.joblib'),physical(hist/'models/development-margin-calibrators.joblib')],
            'modelsFitted':0,'providerCalls':0,'jointSummary':s,'targetFeatureMaxSourceDate':target.feature_max_source_game_date.isoformat(),
            'targetExcluded':True,'sourcePipelineUnchanged':True}}
    if clock(f['createdAt'])>=clock(game['scheduled_at']):raise ValueError('CFB_DEADLINE')
    write(done,f)
    return f


def verify_reproduction(output: Path):
    """Replay only this task's new CFB forecast; preserve all published bytes."""
    import joblib
    import pandas as pd
    from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS, predict_artifact, simulate_paired_residuals, _seed_for
    from server.sports_cfb_gen1.current import population_tables
    f = read(output/'forecast.json')
    refs = f['demoReproduction']['sourceBindings']
    for ref in refs: checked(ref)
    features, schedule, donors_path, model_path, _ = [Path(r['path']) for r in refs]
    game_id = int(f['game']['game_id'])
    cols = list(dict.fromkeys(['game_id','scheduled_at','season','home_score','away_score']+FEATURE_COLUMNS))
    # Target outcomes are deliberately excluded. Donors are checked by metadata
    # before their earlier-season outcome columns are opened.
    cols = [c for c in cols if c not in ('home_score','away_score')]
    target = pd.read_parquet(features, columns=cols, filters=[('game_id','=',game_id)]).iloc[0].copy()
    meta = pd.read_parquet(donors_path, columns=['season','scheduled_at'])
    if not (meta.season < 2026).all() or not (meta.scheduled_at < pd.Timestamp(f['sourceCutoff'])).all():
        raise ValueError('CFB_REPLAY_DONOR_CHRONOLOGY')
    donors = pd.read_parquet(donors_path, columns=['game_id','season','scheduled_at','home_score','away_score',
        'ridge_alpha100_pred_home','ridge_alpha100_pred_away'])
    point = predict_artifact(joblib.load(model_path), target.to_frame().T)
    for side, name in [('home','homePoints'),('away','awayPoints')]:
        agree(point[name],f['baseline']['expected'+side.title()+'Points'])
        target['ridge_alpha100_pred_'+side] = point[name]
    replay, accounting = simulate_paired_residuals(target,donors,'ridge_alpha100')
    original = pd.read_parquet(output/'baseline-joint-draws.parquet')
    pd.testing.assert_frame_equal(replay,original,check_exact=True)
    pmfs = pd.read_parquet(output/'baseline-pmfs.parquet')
    pd.testing.assert_frame_equal(population_tables(game_id,original),pmfs,check_exact=True)
    if canonical(accounting) != canonical(f['baseline']['transformationAccounting']):
        raise ValueError('CFB_TRANSFORMATION_REPLAY')
    return {'schemaVersion':'ASP_DEMO_CFB_REPRODUCTION_V1','forecast':physical(output/'forecast.json'),
        'draws':physical(output/'baseline-joint-draws.parquet'),'pmfs':physical(output/'baseline-pmfs.parquet'),
        'seedPolicy':'SHA256(20260914|CFBD game ID|ridge_alpha100), original pipeline _seed_for',
        'seed':_seed_for(game_id,'ridge_alpha100'),'orderedDrawsExactlyEqual':True,'pmfsExactlyEqual':True,
        'pointPredictionAbsoluteTolerance':1e-8,'pointPredictionsReproduced':True,'verificationDraws':len(replay),
        'originalForecastsReplaced':0,'modelFits':0,'providerRequests':0,'targetOutcomesRead':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--studio',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--verify-reproduction',action='store_true')
    a=p.parse_args()
    if a.verify_reproduction:
        print(json.dumps(verify_reproduction(a.output),indent=2))
    else:
        f=build(a.studio,a.output);print(json.dumps({'forecastId':f['forecastId'],'game':f['game'],'baseline':{k:v for k,v in f['baseline'].items() if not isinstance(v,(dict,list))}},indent=2))
