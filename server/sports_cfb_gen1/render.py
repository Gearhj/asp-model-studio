"""Exact retained CFB Gen1 model and simulation, new prospective bindings only."""
import json
from pathlib import Path
import uuid

import joblib
import numpy as np
import pandas as pd

from .pipeline import FEATURE_COLUMNS, predict_artifact, simulate_paired_residuals, _seed_for
from .current import population_tables, interval_table, totals_probabilities
from .publication_io import canonical_bytes, digest, reference, verified_bytes
from .lifecycle import immutable, now, read_ref, utc

CONFIGURATION='CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1'
MODEL='ridge_alpha100'


def numerical_population(target, model_bindings, cutoff):
    for ref in model_bindings.values(): verified_bytes(ref)
    model=joblib.load(model_bindings['selectedModel']['path'])
    if model['trainingThroughSeason']!=2025 or model['parameters']!={'alpha':100.0} or model['featureColumns']!=FEATURE_COLUMNS:
        raise ValueError('Wrong retained Gen1 numerical baseline')
    donor_ref=model_bindings['pairedResidualPopulation']
    metadata=pd.read_parquet(donor_ref['path'],columns=['season','scheduled_at'])
    if not (metadata.season<2026).all() or not (metadata.scheduled_at<pd.Timestamp(cutoff)).all():
        raise ValueError('Residual donor chronology')
    donors=pd.read_parquet(donor_ref['path'],columns=['game_id','season','scheduled_at','home_score','away_score',
        MODEL+'_pred_home',MODEL+'_pred_away'])
    point=predict_artifact(model,target.to_frame().T)
    row=target.copy()
    row[MODEL+'_pred_home']=point['homePoints'];row[MODEL+'_pred_away']=point['awayPoints']
    draws,accounting=simulate_paired_residuals(row,donors,MODEL)
    calibrator=joblib.load(model_bindings['developmentCalibrator']['path'])[MODEL]
    ph=float(calibrator.predict_proba(np.array([[point['homeMargin']]]))[0,1])
    return point,ph,draws,accounting


def render(row,bundle_ref,release_ref,key,build_root):
    bundle,release=read_ref(bundle_ref),read_ref(release_ref)
    target=row['target'];gid=int(target['game_id'])
    cols=list(dict.fromkeys(FEATURE_COLUMNS+['game_id','season','scheduled_at','home_id','away_id','elo_home_win_probability','feature_max_source_game_date']))
    selected=pd.read_parquet(bundle['features']['path'],columns=cols,filters=[('game_id','=',gid)])
    if len(selected)!=1: raise ValueError('Unique target feature row required')
    feature=selected.iloc[0]
    if any(int(feature[k])!=int(target[k]) for k in ('home_id','away_id')) or utc(target['scheduled_at'])!=feature.scheduled_at:
        raise ValueError('Feature/schedule orientation mismatch')
    cutoff=bundle['sourceCutoffUtc']
    if not pd.isna(feature.feature_max_source_game_date) and not feature.feature_max_source_game_date<pd.Timestamp(cutoff)<feature.scheduled_at:
        raise ValueError('Target feature chronology')
    point,ph,draws,accounting=numerical_population(feature,release['modelBindings'],cutoff)
    if min(point['homePoints'],point['awayPoints'])<0:
        raise ValueError('Negative point expectation unsupported; no clipping of point model')
    build=Path(build_root)/uuid.uuid4().hex;build.mkdir(parents=True)
    draws.to_parquet(build/'baseline-joint-draws.parquet',index=False)
    pmfs=population_tables(gid,draws);pmfs.to_parquet(build/'baseline-pmfs.parquet',index=False)
    created=now()
    joint_home=float((draws.home_score>draws.away_score).mean())
    elo=float(feature.elo_home_win_probability)
    values={k:(None if pd.isna(feature[k]) else float(feature[k])) for k in FEATURE_COLUMNS}
    baseline={'configuration':CONFIGURATION,'drawCount':10000,
        'expectedAwayPoints':point['awayPoints'],'expectedHomePoints':point['homePoints'],
        'expectedTotal':point['totalPoints'],'expectedHomeMargin':point['homeMargin'],
        'ridgeHomeWinProbability':ph,'ridgeAwayWinProbability':1-ph,
        'eloHomeWinProbability':elo,'eloAwayWinProbability':1-elo,
        'jointHomeWinProbability':joint_home,'jointAwayWinProbability':1-joint_home,'tieProbability':0.,
        'jointMeanHomePoints':float(draws.home_score.mean()),'jointMeanAwayPoints':float(draws.away_score.mean()),
        'jointMeanTotal':float(draws.total.mean()),'jointMeanHomeMargin':float(draws.home_margin.mean()),
        'intervals':interval_table(draws),'transformationAccounting':accounting,
        'illustrativeTotals':[totals_probabilities(draws,float(round(point['totalPoints']))),
                             totals_probabilities(draws,float(round(point['totalPoints']))+.5)],
        'simulationMcse':{'jointHomeWin':float(np.sqrt(joint_home*(1-joint_home)/10000)),
                          'interpretation':'Simulation sampling precision only, not predictive uncertainty'}}
    identity={'revisionKey':key,'gameId':gid,'createdAtUtc':created,'sourceCutoffUtc':cutoff,
              'modelBindings':release['modelBindings'],'featureValuesSha256':digest(values),
              'populationSha256':reference(build/'baseline-joint-draws.parquet')['sha256']}
    forecast={'schemaVersion':'CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1',
        'forecastId':'cfb-gen1:'+digest(identity),'createdAt':created,'publishedAt':None,
        'status':'STAGED_PROSPECTIVE_BASELINE_NO_CONSUMER_AUTHORITY','game':target,'sourceCutoff':cutoff,
        'scheduleRevisionCapturedAt':bundle['scheduleCapturedAtUtc'],'baseline':baseline,
        'challenger':{'publishedAsSecondArm':False,'configuration':None},
        'modelBindings':release['modelBindings'],'featureValues':values,
        'sourceBindings':{'inputVersion':bundle_ref,'cfbdManifest':bundle['sourceManifest'],
                          'schoolAliases':bundle['aliases'],'publisherRelease':release_ref},
        'population':{'drawCount':10000,'orientation':'HOME_AWAY','paired':True,
            'drawArtifact':reference(build/'baseline-joint-draws.parquet'),
            'logicalHomeAwayInt64LeSha256':digest(draws[['home_score','away_score']].to_numpy(dtype='<i8').tobytes()),
            'seed':_seed_for(gid,MODEL),'seedPolicy':'SHA256(20260914|CFBD game ID|ridge_alpha100)',
            'jointWinnerMcse':float(np.sqrt(joint_home*(1-joint_home)/10000))},
        'authorityChannels':{'points':'Fitted Ridge alpha100 margin/total models',
            'calibratedWinner':'Frozen Development margin calibrator, separately estimated',
            'eloWinner':'Frozen chronological Elo feature rule, diagnostic separate channel',
            'jointScoresTotalsWinner':'Existing paired chronological residual population and unchanged final-score transformation'},
        'prospectiveEffectiveAtUtc':release['prospectiveEffectiveAtUtc'],'revisionKey':key,
        'limitations':release['limitations']+bundle['sourceLimitations'],
        'researchOnly':True,'aispAuthority':False,'wageringAuthority':False,'schedulerAuthority':False,
        'modelPromotionAuthority':False,'modelFits':0}
    immutable(build/'forecast.json',canonical_bytes(forecast))
    members=[{'path':p.name,'physicalSha256':reference(p)['sha256'],'bytes':p.stat().st_size} for p in sorted(build.iterdir()) if p.is_file()]
    index={'schemaVersion':'CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1','forecastId':forecast['forecastId'],
        'gameId':gid,'createdAt':created,'sourceCutoff':cutoff,'publishedAtUtc':None,
        'publicationClockAuthority':'Cumulative discovery bound immutable publicationReceipt.committedAtUtc',
        'configurationIdentity':CONFIGURATION,'revisionKey':key,'drawCount':10000,'files':members,
        'researchOnly':True,'aispAuthority':False,'wageringAuthority':False,'rawProviderResponsesIncluded':False}
    immutable(build/'index.json',canonical_bytes(index))
    verify_package(build)
    return build


def verify_package(package):
    package=Path(package);index=json.loads((package/'index.json').read_bytes())
    if index.get('schemaVersion')!='CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1' or index.get('researchOnly') is not True:
        raise ValueError('CFB package contract')
    if any(index.get(k) is not False for k in ('aispAuthority','wageringAuthority','rawProviderResponsesIncluded')):
        raise ValueError('Unauthorized package')
    if len(package.name)==64 and digest((package/'index.json').read_bytes())!=package.name:
        raise ValueError('Physical package address')
    seen=set()
    for m in index['files']:
        rel=Path(m['path'])
        if rel.is_absolute() or '..' in rel.parts or m['path'] in seen: raise ValueError('Member path invalid')
        seen.add(m['path']);verified_bytes(dict(m,path=str(package/rel)))
    f=json.loads((package/'forecast.json').read_bytes())
    if f.get('schemaVersion')!='CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1' or f.get('researchOnly') is not True or any(f.get(k) is not False for k in ('aispAuthority','wageringAuthority')):
        raise ValueError('Forecast schema/authority mismatch')
    if f['forecastId']!=index['forecastId'] or f['game']['game_id']!=index['gameId']:
        raise ValueError('Forecast identity mismatch')
    d=pd.read_parquet(package/'baseline-joint-draws.parquet')
    if len(d)!=10000 or list(d.draw)!=list(range(10000)) or (d[['home_score','away_score']]<0).any().any() or (d.home_score==d.away_score).any():
        raise ValueError('Draw support or count mismatch')
    if not (d.total==d.home_score+d.away_score).all() or not (d.home_margin==d.home_score-d.away_score).all():
        raise ValueError('Total/margin accounting')
    p=pd.read_parquet(package/'baseline-pmfs.parquet')
    pd.testing.assert_frame_equal(p,population_tables(index['gameId'],d),check_exact=True)
    b=f['baseline']
    for channel in ('ridge','elo','joint'):
        ph=b[channel+'HomeWinProbability'];pa=b[channel+'AwayWinProbability']
        if not 0<=ph<=1 or not 0<=pa<=1 or abs(ph+pa-1)>1e-12: raise ValueError('Probability mass')
    if abs(b['jointHomeWinProbability']-float((d.home_score>d.away_score).mean()))>1e-12 or b['tieProbability']!=0:
        raise ValueError('Joint probability orientation')
    if abs(b['expectedHomePoints']+b['expectedAwayPoints']-b['expectedTotal'])>1e-10 or abs(b['expectedHomePoints']-b['expectedAwayPoints']-b['expectedHomeMargin'])>1e-10:
        raise ValueError('Point score orientation')
    if not utc(f['sourceCutoff'])<=utc(f['createdAt'])<utc(f['game']['scheduled_at']):
        raise ValueError('Publication chronology')
    if f.get('population') and digest(d[['home_score','away_score']].to_numpy(dtype='<i8').tobytes())!=f['population']['logicalHomeAwayInt64LeSha256']:
        raise ValueError('Joint population identity mismatch')
    return index
