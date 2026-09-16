"""Staged, permitted Category-A point/Elo research. No prospective publisher.

The strict Gen1 real-time gates and joint simulator are deliberately unchanged.
This runner reads score fields only for declared seasons, freezes the two point
benchmarks before holdout analysis, and never imports publisher predictions.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .authority import json_bytes, reference, verified_bytes, immutable_json, RESEARCH_FLAGS
from .historical_features import build_historical_features, historical_feature_contract, FEATURE_COLUMNS
from .historical_source import normalize_source
from .models import fit_model

VERSION = 'NBA_GEN1_FTE_CATEGORY_A_POINT_ELO_PILOT_V1'
METRICS = ('log_loss', 'binary_brier', 'correct_pick', 'home_mae', 'away_mae', 'margin_mae', 'total_mae')


def now():
    return datetime.now(timezone.utc).isoformat()


def put_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json_bytes(value)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f'Refusing to replace historical evidence: {path}')
    path.write_bytes(raw)
    return reference(path)


def score_predictions(frame):
    """One assessment unit per game; binary NBA Brier, never draw-based N."""
    result = frame.copy()
    if result.game_id.duplicated().any():
        raise ValueError('One prediction per game/configuration is required')
    p = result.p_home_win.to_numpy(float)
    scores = result[['home_score', 'away_score']].to_numpy(float)
    predicted = result[['expected_home_score', 'expected_away_score']].to_numpy(float)
    if (not np.isfinite(p).all() or not ((p > 0) & (p < 1)).all()
            or not np.isfinite(scores).all() or not np.isfinite(predicted).all()
            or (scores[:, 0] == scores[:, 1]).any()):
        raise ValueError('Finite scores, untied NBA finals and interior probabilities required')
    observed = scores[:, 0] > scores[:, 1]
    result['p_away_win'] = 1-p
    result['p_tie'] = 0.0
    result['log_loss'] = -np.log(np.where(observed, p, 1-p))
    result['binary_brier'] = (p-observed)**2
    result['correct_pick'] = ((p >= .5) == observed).astype(int)
    result['home_mae'] = abs(predicted[:,0]-scores[:,0])
    result['away_mae'] = abs(predicted[:,1]-scores[:,1])
    result['margin_mae'] = abs((predicted[:,0]-predicted[:,1])-(scores[:,0]-scores[:,1]))
    result['total_mae'] = abs(predicted.sum(axis=1)-scores.sum(axis=1))
    result['home_residual'] = scores[:,0]-predicted[:,0]
    result['away_residual'] = scores[:,1]-predicted[:,1]
    return result


def summary(frame):
    return {'games':len(frame), **{metric:float(frame[metric].mean()) for metric in METRICS},
            'correctPicks':int(frame.correct_pick.sum())}


def paired_differences(ledger, replicates=2000, seed=731101):
    """Calendar-week block bootstrap, preserving paired whole-game losses."""
    a = ledger[ledger.family == 'league'].set_index('game_id').sort_index()
    b = ledger[ledger.family == 'elo'].set_index('game_id').sort_index()
    if not a.index.equals(b.index) or not a.game_date.equals(b.game_date):
        raise ValueError('Paired assessment cohorts differ')
    delta = b[list(METRICS)].to_numpy()-a[list(METRICS)].to_numpy()
    # Calendar dates are grouping labels, not invented observed tipoff clocks.
    week = pd.to_datetime(a.game_date, format='%Y-%m-%d').dt.strftime('%G-%V')
    labels, groups = np.unique(week, return_inverse=True)
    sums = np.zeros((len(labels),len(METRICS)))
    sizes = np.zeros(len(labels),dtype=int)
    np.add.at(sums, groups, delta)
    np.add.at(sizes, groups, 1)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0,len(labels),(replicates,len(labels)))
    bootstrap = sums[picks].sum(axis=1)/sizes[picks].sum(axis=1)[:,None]
    return {'direction':'ELO_MINUS_LEAGUE; negative is better except correct_pick',
            'unit':'Paired observed games, resampled in calendar-week blocks',
            'games':len(a),'calendarWeeks':len(labels),'replicates':replicates,'seed':seed,
            'metrics':{key:{'meanDifference':float(delta[:,i].mean()),
                            'interval95':np.quantile(bootstrap[:,i],[.025,.975]).tolist()}
                       for i,key in enumerate(METRICS)}}


def reliability(frame):
    result=[]
    bins=np.minimum((frame.p_home_win.to_numpy()*10).astype(int),9)
    for index in range(10):
        subset=frame.loc[bins == index]
        if len(subset):
            result.append({'band':f'[{index/10:.1f},{(index+1)/10:.1f})', 'games':len(subset),
                           'meanProbability':float(subset.p_home_win.mean()),
                           'observedHomeWinRate':float((subset.home_score>subset.away_score).mean())})
    return result


def report(ledger):
    rows=[]
    for (year,family),group in ledger.groupby(['season_end','family']):
        rows.append({'seasonEnd':int(year),'family':family,**summary(group)})
    roles={2011:'DEVELOPMENT',2012:'DEVELOPMENT',2013:'DEVELOPMENT',2014:'VALIDATION',2015:'FINAL_CATEGORY_A_HOLDOUT'}
    with_roles=ledger.assign(role=ledger.season_end.map(roles))
    by_role={}
    for role,group in with_roles.groupby('role'):
        by_role[role]={'models':{family:summary(part) for family,part in group.groupby('family')},
                       'paired':paired_differences(group),
                       'reliability':{family:reliability(part) for family,part in group.groupby('family')}}
    slices=[]
    for (role,family),group in with_roles.groupby(['role','family']):
        for field in ('support_band','back_to_back_band','minimum_rest_band'):
            for band,part in group.groupby(field):
                slices.append({'role':role,'family':family,'dimension':field,'band':str(band),**summary(part)})
    return {'bySeason':rows,'byRole':by_role,'slices':slices,
            'unavailable':{'jointEnergy':'No supported joint simulation produced',
                           'CRPSAndIntervalCoverage':'No supported joint simulation produced',
                           'paceBands':'No possessions or box statistics',
                           'tailDiagnostics':'Point and winner models only; no retained simulated score population'},
            'calibration':'No fitted post-processing; reliability tables are descriptive, never used for tuning.'}


def numerical_bindings():
    folder=Path(__file__).parent
    return {name:reference(folder/name) for name in ('historical_pilot.py','historical_source.py','historical_features.py','models.py')}


def fit_bound_model(family,train,folder):
    if not train.target_eligible.all():
        raise ValueError('Neutral publisher axes cannot enter home/away target fitting')
    model=fit_model(family,{},train,train)
    path=folder/f'{family}.joblib'
    if path.exists():
        raise ValueError('Refusing to replace fitted artifact')
    folder.mkdir(parents=True,exist_ok=True)
    joblib.dump(model,path,compress=3)
    return {'family':family,'pointArtifact':reference(path),
            'trainingGameIds':list(model.training_game_ids),
            'trainingIdentitySha256':model.training_identity_sha256,
            'trainingFeatureSha256':hashlib.sha256(pd.util.hash_pandas_object(train,index=False).values.tobytes()).hexdigest(),
            'trainingLastGameDate':str(train.game_date.max()),
            'trainingHomeWinFraction':float((train.home_score>train.away_score).mean()),
            'coefficients':model.diagnostic_coefficients,
            'probabilityMechanism':'Earlier-training home-win fraction' if family=='league' else 'Fixed rebuilt Elo logistic formula; distinct from point-model OLS margin link',
            'preprocessing':'No scaler/encoder; Elo difference median is fitted on training data only',
            'prospectiveEligible':False}


def predictions(bound,target):
    verified_bytes(bound['pointArtifact'])
    model=joblib.load(bound['pointArtifact']['path'])
    if set(target.game_id) & set(bound['trainingGameIds']):
        raise ValueError('Target leaked into training')
    if str(target.game_date.min()) <= bound['trainingLastGameDate']:
        raise ValueError('Point-model training is not strictly before assessment season')
    expected=model.predict(target)
    fields=['game_id','season_end','game_date','home_team_id','away_team_id','home_team_code','away_team_code',
            'home_score','away_score','home_elo','away_elo','history_latest_game_date','history_identity_sha256',
            'home_history_supported','away_history_supported','home_season_games_played','away_season_games_played',
            'home_back_to_back','away_back_to_back','home_rest_days','away_rest_days']
    output=target[fields].copy()
    if not (output.history_latest_game_date < output.game_date).all():
        raise ValueError('A reconstructed feature used a same-date or future result')
    output['family']=bound['family']
    output['model_sha256']=bound['pointArtifact']['sha256']
    output['evidence_class']='A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION'
    output['expected_home_score']=expected[:,0]
    output['expected_away_score']=expected[:,1]
    output['p_home_win']=(bound['trainingHomeWinFraction'] if bound['family']=='league'
                          else target.elo_home_win_probability.to_numpy())
    early=(target[['home_season_games_played','away_season_games_played']].min(axis=1)<10)
    output['support_band']=np.where(early,'EITHER_TEAM_LT10_CURRENT_SEASON','BOTH_GE10_CURRENT_SEASON')
    b2b=target[['home_back_to_back','away_back_to_back']].max(axis=1)>0
    output['back_to_back_band']=np.where(b2b,'EITHER_BACK_TO_BACK','NEITHER_BACK_TO_BACK')
    rest=target[['home_rest_days','away_rest_days']].min(axis=1,skipna=False)
    output['minimum_rest_band']=np.where(rest.isna(),'UNKNOWN',np.where(rest==0,'0',np.where(rest==1,'1','2+')))
    return score_predictions(output)


def run(root,stage):
    root=Path(root).resolve()
    done=root/f'{stage}-receipt.json'
    if done.exists():
        receipt=json.loads(done.read_bytes())
        for item in receipt['artifacts'].values():
            verified_bytes(item)
        return {'status':'REUSED_IMMUTABLE_STAGE','receipt':reference(done)}
    declaration_ref=json.loads((root/'declaration.json').read_bytes())['declaration']
    declaration=json.loads(verified_bytes(declaration_ref))
    for bound in declaration['numericalModules'].values():
        verified_bytes(bound)
    if historical_feature_contract()['sha256'] != declaration['featureContract']['sha256']:
        raise ValueError('Feature declaration changed')
    if declaration['performanceExaminedAtDeclaration'] is not False:
        raise ValueError('An unexamined metadata-first declaration is required')
    acquisition=json.loads(verified_bytes(declaration['source']))
    verified_bytes(declaration['rightsReview'])
    folder=root/stage
    if folder.exists():
        raise ValueError('Partial stage exists: inspect it before resuming, never overwrite')
    freeze=None
    if stage=='holdout':
        val=json.loads((root/'development-validation-receipt.json').read_bytes())
        freeze=json.loads(verified_bytes(val['artifacts']['holdoutFreeze']))
        for bound in freeze['numericalModules'].values():
            verified_bytes(bound)
        assert freeze['decision']=='RETAIN_BOTH_FIXED_BENCHMARKS_NO_FULL_GEN1_CHAMPION'
        assert freeze['holdoutOutcomeAnalysisStarted'] is False
        allowed=list(range(2010,2016))
    elif stage=='development-validation':
        allowed=list(range(2010,2015))
    else:
        raise ValueError('Unknown stage')
    started=now()
    raw=verified_bytes(acquisition['original'])
    games,reconciliation=normalize_source(raw,allowed)
    for population in declaration['population']:
        year=population['seasonEnd']
        if year not in allowed:
            continue
        subset=games[games.season_end == year]
        source_ids=set(subset.source_game_id)
        if source_ids != set(population['sourceGameIds']):
            raise ValueError('Normalized identities disagree with frozen metadata population')
        assert len(subset)==population['games']
        assert int((~subset.neutral_site).sum())==population['eligibleHomeAway']
    features,audit=build_historical_features(games)
    folder.mkdir(parents=True)
    games.to_parquet(folder/'normalized-games.parquet',index=False)
    features.to_parquet(folder/'features.parquet',index=False)
    reconciliation.update(evidenceClass=declaration['evidenceClass'],source=acquisition['original'],
                          actualAcquiredAtUtc=acquisition['acquiredAtUtc'],declaration=declaration_ref)
    artifacts={'population':reference(folder/'normalized-games.parquet'),'features':reference(folder/'features.parquet'),
               'reconciliation':put_json(folder/'reconciliation.json',reconciliation),
               'featureAudit':put_json(folder/'feature-audit.json',audit)}
    bounds=[]
    ledger=[]
    for year in ([2015] if stage=='holdout' else list(range(2011,2015))):
        target=features[(features.season_end == year) & features.target_eligible]
        train=features[(features.season_end < year) & features.target_eligible]
        for family in ('league','elo'):
            bound=(freeze['models'][family] if stage=='holdout' else fit_bound_model(family,train,folder/'models'/str(year)))
            bounds.append({'assessmentSeasonEnd':year,**bound})
            ledger.append(predictions(bound,target))
    ledger=pd.concat(ledger,ignore_index=True)
    ledger.to_parquet(folder/'predictions-and-residuals.parquet',index=False)
    artifacts['predictions']=reference(folder/'predictions-and-residuals.parquet')
    artifacts['models']=put_json(folder/'models.json',bounds)
    assessment=report(ledger)
    artifacts['assessment']=put_json(folder/'assessment.json',assessment)
    if stage=='development-validation':
        holdout_models={family:fit_bound_model(family,features[features.target_eligible],folder/'holdout-models') for family in ('league','elo')}
        freeze={'schemaVersion':VERSION+'_HOLDOUT_FREEZE','createdAtUtc':now(),'declaration':declaration_ref,
                'validationAssessment':artifacts['assessment'],'models':holdout_models,
                'decision':'RETAIN_BOTH_FIXED_BENCHMARKS_NO_FULL_GEN1_CHAMPION',
                'reason':'Full primary joint energy gate is unavailable. Report both predeclared point/winner benchmarks without retuning or calibration.',
                'holdoutOutcomeAnalysisStarted':False,'holdoutSeasonEnd':2015,
                'numericalModules':numerical_bindings(),'authority':RESEARCH_FLAGS}
        artifacts['holdoutFreeze']=immutable_json(root,'holdout-freeze.json',freeze)
    verification={'oneRowPerGamePerFamily':not ledger.duplicated(['family','game_id']).any(),
                  'probabilityMassMaximumError':float(abs(ledger.p_home_win+ledger.p_away_win+ledger.p_tie-1).max()),
                  'observedFinalTies':int((ledger.home_score==ledger.away_score).sum()),
                  'allHistoryDatesStrictlyEarlier':bool((ledger.history_latest_game_date<ledger.game_date).all()),
                  'unsupportedAssessmentGamesPerArm':int(((ledger.home_history_supported!=1)|(ledger.away_history_supported!=1)).sum()/2),
                  'neutralHistoryOnly':int(games.neutral_site.sum()),'pairedAssessmentGames':int(len(ledger)/2),
                  'simulations':0,'jointDistributionClaims':False,'calibrationFitted':False}
    artifacts['verification']=put_json(folder/'verification.json',verification)
    receipt={'schemaVersion':VERSION,'stage':stage,'analysisStartedAtUtc':started,'completedAtUtc':now(),
             'acquisition':declaration['source'],'declaration':declaration_ref,'artifacts':artifacts,
             'evidenceClass':declaration['evidenceClass'],'authority':RESEARCH_FLAGS,
             'historicalPublicationTimes':None,'prospectiveForecasts':0,'sourceRequestsDuringFit':0}
    put_json(done,receipt)
    return {'status':'COMPLETED','receipt':reference(done),'bySeason':assessment['bySeason'],'verification':verification}
