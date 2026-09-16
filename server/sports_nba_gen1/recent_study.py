"""Staged recent Category-A point-model assessment; unchanged Elo winner link."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .authority import reference, verified_bytes, json_bytes, immutable_json, RESEARCH_FLAGS
from .historical_pilot import score_predictions
from .models import fit_model
from .recent_features import build_recent_features, recent_feature_contract
from .recent_models import fit_reduced_model
from .recent_source import normalize_recent_source

VERSION='NBA_GEN1_RECENT_SCORE_DATE_RESEARCH_V1'
METRICS=('log_loss','binary_brier','correct_pick','home_mae','away_mae','margin_mae','total_mae','team_score_mse')


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path,value):
    raw=json_bytes(value)
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=raw:
        raise ValueError(f'Refusing to replace saved evidence: {path}')
    path.write_bytes(raw)
    return reference(path)


def bindings():
    p=Path(__file__).parent
    names=('recent_study.py','recent_source.py','recent_features.py','recent_models.py','models.py','historical_features.py','historical_pilot.py')
    return {name:reference(p/name) for name in names}


def summarize(frame):
    return {'games':len(frame),'correctPicks':int(frame.correct_pick.sum()),
            **{name:float(frame[name].mean()) for name in METRICS}}


def pair_interval(ledger,challenger,baseline='elo'):
    a=ledger[ledger.model_id==baseline].set_index('game_id').sort_index()
    b=ledger[ledger.model_id==challenger].set_index('game_id').sort_index()
    if not a.index.equals(b.index) or not a.game_date.equals(b.game_date):
        raise ValueError('Common assessment cohort required')
    differences=b[list(METRICS)].to_numpy()-a[list(METRICS)].to_numpy()
    # Date labels only; no historical tipoff/publication clock is invented.
    labels=pd.to_datetime(a.game_date,format='%Y-%m-%d').dt.strftime('%G-%V')
    weeks,index=np.unique(labels,return_inverse=True)
    sums=np.zeros((len(weeks),len(METRICS)))
    counts=np.zeros(len(weeks),dtype=int)
    np.add.at(sums,index,differences)
    np.add.at(counts,index,1)
    picks=np.random.default_rng(731201).integers(0,len(weeks),(2000,len(weeks)))
    boot=sums[picks].sum(axis=1)/counts[picks].sum(axis=1)[:,None]
    return {'challenger':challenger,'baseline':baseline,'direction':'challenger-minus-baseline; negative improves errors, positive improves correct_pick',
            'games':len(a),'calendarWeeks':len(weeks),'replicates':2000,'seed':731201,
            'metrics':{name:{'difference':float(differences[:,i].mean()),'interval95':np.quantile(boot[:,i],[.025,.975]).tolist()}
                       for i,name in enumerate(METRICS)}}


def assess(ledger):
    overall={name:summarize(group) for name,group in ledger.groupby('model_id')}
    season=[{'seasonEnd':int(year),'modelId':name,**summarize(group)}
            for (year,name),group in ledger.groupby(['season_end','model_id'])]
    intervals={name:pair_interval(ledger,name) for name in overall if name!='elo'}
    return {'overall':overall,'bySeason':season,'pairedVersusElo':intervals,
            'winnerSemantics':'All point challengers retain exactly the same Elo winner probability. Identical log loss/Brier/picks are by construction, not evidence of new winner improvement.',
            'properPointMetric':'mean((home_error^2+away_error^2)/2); margin and total MAE are separate guards',
            'unavailable':['joint energy','CRPS','prediction intervals','tie-resolution effect','certified contemporaneous information availability']}


def choose_development(assessment,configs):
    selected={}
    for family in ('ridge','hgb'):
        options=[c for c in configs if c['family']==family]
        # Equal MSE favors stronger regularization, as declared.
        selected[family]=min(options,key=lambda c:(assessment['overall'][c['id']]['team_score_mse'],
                                                  -next(iter(c['params'].values()))))
    return selected


def choose_validation(assessment,finalists):
    baseline=assessment['overall']['elo']
    records=[]
    for config in finalists:
        if config['family'] not in ('ridge','hgb'):
            continue
        result=assessment['overall'][config['id']]
        qualified=(result['team_score_mse']<=.99*baseline['team_score_mse']
                   and result['margin_mae']<=1.02*baseline['margin_mae']
                   and result['total_mae']<=1.02*baseline['total_mae'])
        records.append({'config':config,'passesPointGate':bool(qualified),
                        'mseChangeFraction':result['team_score_mse']/baseline['team_score_mse']-1,
                        'marginMaeChangeFraction':result['margin_mae']/baseline['margin_mae']-1,
                        'totalMaeChangeFraction':result['total_mae']/baseline['total_mae']-1})
    qualified=[r['config'] for r in records if r['passesPointGate']]
    selected={'id':'elo','family':'elo','params':{}}
    if qualified:
        selected=min(qualified,key=lambda c:assessment['overall'][c['id']]['team_score_mse'])
        ridge=next((c for c in qualified if c['family']=='ridge'),None)
        if ridge and assessment['overall'][ridge['id']]['team_score_mse']<=1.005*assessment['overall'][selected['id']]['team_score_mse']:
            selected=ridge
    return {'selectedPointConfig':selected,'candidateGates':records,
            'winnerChannel':'UNCHANGED_CHRONOLOGICAL_ELO','selectionPopulation':'VALIDATION_ONLY',
            'authority':'RESEARCH_POINT_BASELINE_ONLY; full joint-energy gate unavailable'}


def fit_bound(config,train,folder):
    if not train.target_eligible.all() or train.neutral_site.any():
        raise ValueError('Fitting must exclude neutral/history-only targets')
    model=(fit_model(config['family'],config['params'],train,train) if config['family'] in ('league','elo')
           else fit_reduced_model(config['family'],config['params'],train,train))
    path=folder/(config['id']+'.joblib')
    if path.exists():
        raise ValueError('Cannot replace fitted model')
    path.parent.mkdir(parents=True,exist_ok=True)
    joblib.dump(model,path,compress=3)
    return {'config':config,'artifact':reference(path),'trainingGames':len(train),
            'trainingGameIds':list(model.training_game_ids),'trainingIdentitySha256':model.training_identity_sha256,
            'trainingLastDate':str(train.game_date.max()),'trainingHomeWinFraction':float((train.home_score>train.away_score).mean()),
            'featureContract':recent_feature_contract(),'coefficients':model.diagnostic_coefficients,
            'numericalModules':bindings(),'futurePublicationEligible':False}


def predict(bound,target):
    verified_bytes(bound['artifact'])
    model=joblib.load(bound['artifact']['path'])
    if set(target.game_id)&set(bound['trainingGameIds']) or not (target.game_date>bound['trainingLastDate']).all():
        raise ValueError('Targets must follow and exclude the fitted training population')
    if not target.target_eligible.all() or target.neutral_site.any():
        raise ValueError('History-only target entered prediction cohort')
    if not (target.history_latest_game_date<target.game_date).all():
        raise ValueError('Target or same-day outcomes entered history')
    scores=model.predict(target)
    cols=['game_id','season_end','game_date','home_team_id','away_team_id','home_team_code','away_team_code',
          'home_score','away_score','home_elo','away_elo','history_latest_game_date','history_identity_sha256',
          'home_history_supported','away_history_supported','home_season_games_played','away_season_games_played',
          'home_rest_days','away_rest_days','home_back_to_back','away_back_to_back']
    frame=target[cols].copy()
    frame['model_id']=bound['config']['id']
    frame['family']=bound['config']['family']
    frame['model_sha256']=bound['artifact']['sha256']
    frame['evidence_class']='A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION'
    frame['expected_home_score']=scores[:,0]
    frame['expected_away_score']=scores[:,1]
    league=bound['config']['family']=='league'
    frame['p_home_win']=bound['trainingHomeWinFraction'] if league else target.elo_home_win_probability.to_numpy()
    frame['winner_probability_source']='TRAINING_LEAGUE_HOME_FREQUENCY' if league else 'UNCHANGED_CHRONOLOGICAL_ELO'
    frame=score_predictions(frame)
    frame['team_score_mse']=(frame.home_residual**2+frame.away_residual**2)/2
    return frame


def load_declaration(root):
    bound=json.loads((root/'declaration.json').read_bytes())['declaration']
    value=json.loads(verified_bytes(bound))
    for reference_ in value['numericalModules'].values():
        verified_bytes(reference_)
    assert value['featureContract']==recent_feature_contract()
    assert value['performanceExamined'] is False
    return value,bound


def run(root,stage):
    root=Path(root).resolve()
    done=root/f'{stage}-receipt.json'
    if done.exists():
        receipt=json.loads(done.read_bytes())
        for artifact in receipt['artifacts'].values():
            verified_bytes(artifact)
        return {'status':'REUSED_IMMUTABLE_STAGE_NO_NEW_ASSESSMENT','receipt':reference(done)}
    declaration,decl_ref=load_declaration(root)
    acquisition=json.loads(verified_bytes(declaration['source']))
    verified_bytes(acquisition['sourceReview'])
    folder=root/stage
    if folder.exists():
        raise ValueError('Partial stage exists; inspect rather than overwrite or silently repeat')
    frozen=None
    if stage=='development':
        allowed=list(range(2020,2024)); years=[2021,2022,2023]; configs=declaration['candidates']
    elif stage in ('validation','holdout'):
        previous='development' if stage=='validation' else 'validation'
        earlier=json.loads((root/f'{previous}-receipt.json').read_bytes())
        frozen=json.loads(verified_bytes(earlier['artifacts']['nextStageFreeze']))
        assert frozen['nextStage']==stage and frozen['nextStageOutcomesInspected'] is False
        for artifact in frozen['numericalModules'].values():
            verified_bytes(artifact)
        years=[2024 if stage=='validation' else 2025]
        allowed=list(range(2020,years[0]+1))
        configs=frozen['configs']
    else:
        raise ValueError('Unknown stage')
    folder.mkdir(parents=True)
    access=save(folder/'outcome-access.json',{'stage':stage,'startedAtUtc':now(),'declaration':decl_ref,
                'allowedSeasonEnds':allowed,'purpose':'DECLARED_CATEGORY_A_CHRONOLOGICAL_ASSESSMENT',
                'numericalModules':bindings(),'firstAccessForStage':True})
    source=verified_bytes(acquisition['original'])
    games,reconciliation=normalize_recent_source(source,allowed,declaration)
    features,audit=build_recent_features(games,context_events=reconciliation['contextOnlyEvents'])
    for row in declaration['population']:
        year=row['seasonEnd']
        if year in allowed:
            part=features[features.season_end==year]
            assert len(part)==row['regularGames']
            assert int(part.target_eligible.sum())==row['orientedTargets']
    games.to_parquet(folder/'games.parquet',index=False)
    features.to_parquet(folder/'features.parquet',index=False)
    reconciliation.update(source=acquisition['original'],actualAcquiredAtUtc=acquisition['acquiredAtUtc'],declaration=decl_ref)
    artifacts={'access':access,'games':reference(folder/'games.parquet'),'features':reference(folder/'features.parquet'),
               'reconciliation':save(folder/'reconciliation.json',reconciliation),
               'featureAudit':save(folder/'feature-audit.json',audit)}
    ledgers=[]; model_bindings=[]
    for year in years:
        target=features[(features.season_end==year)&features.target_eligible]
        train=features[(features.season_end<year)&features.target_eligible]
        for config in configs:
            bound=(fit_bound(config,train,folder/'models'/str(year)) if stage=='development'
                   else frozen['models'][config['id']])
            model_bindings.append({'assessmentSeasonEnd':year,**bound})
            ledgers.append(predict(bound,target))
    ledger=pd.concat(ledgers,ignore_index=True)
    ledger.to_parquet(folder/'predictions-and-paired-residuals.parquet',index=False)
    artifacts['predictions']=reference(folder/'predictions-and-paired-residuals.parquet')
    artifacts['models']=save(folder/'models.json',model_bindings)
    results=assess(ledger)
    artifacts['assessment']=save(folder/'assessment.json',results)
    if stage=='development':
        winners=choose_development(results,configs)
        finalists=[c for c in configs if c['family'] in ('league','elo')]+list(winners.values())
        decision={'familyHyperparameters':winners,'selectionPopulation':'DEVELOPMENT_ONLY','criterion':'mean team_score_mse'}
    elif stage=='validation':
        finalists=configs
        decision=choose_validation(results,configs)
    else:
        decision=frozen['selection']
    artifacts['selection']=save(folder/'selection.json',decision)
    if stage!='holdout':
        next_stage='validation' if stage=='development' else 'holdout'
        next_models={c['id']:fit_bound(c,features[features.target_eligible],folder/'next-stage-models') for c in finalists}
        freeze={'schemaVersion':VERSION+'_NEXT_STAGE_FREEZE','createdAtUtc':now(),'nextStage':next_stage,
                'nextStageOutcomesInspected':False,'declaration':decl_ref,'assessment':artifacts['assessment'],
                'configs':finalists,'models':next_models,'selection':decision,'numericalModules':bindings(),'authority':RESEARCH_FLAGS}
        artifacts['nextStageFreeze']=immutable_json(root,next_stage+'-freeze.json',freeze)
    # Preserve the one-time assessment before the distinct post-assessment refit.
    verification={'uniqueGamePerModel':not ledger.duplicated(['game_id','model_id']).any(),
                  'probabilityMassMaximumError':float(abs(ledger.p_home_win+ledger.p_away_win+ledger.p_tie-1).max()),
                  'historyStrictlyEarlier':bool((ledger.history_latest_game_date<ledger.game_date).all()),
                  'unsupportedAssessmentGameRows':int(((ledger.home_history_supported==0)|(ledger.away_history_supported==0)).sum()),
                  'winnerChannelSameForAllPointArms':bool(ledger[ledger.family!='league'].groupby('game_id').p_home_win.nunique().eq(1).all()),
                  'simulationDraws':0,'jointDistributionValidated':False}
    artifacts['verification']=save(folder/'verification.json',verification)
    receipt={'schemaVersion':VERSION,'stage':stage,'completedAtUtc':now(),'declaration':decl_ref,
             'evidenceClass':declaration['evidenceClass'],'artifacts':artifacts,'authority':RESEARCH_FLAGS,
             'sourceRequestsDuringModeling':0,'prospectiveForecastsPublished':0}
    save(done,receipt)
    if stage=='holdout':
        point=decision['selectedPointConfig']
        refit_configs=[{'id':'elo','family':'elo','params':{}}]+([] if point['id']=='elo' else [point])
        refits={c['id']:fit_bound(c,features[features.target_eligible],root/'post-assessment-refit/models') for c in refit_configs}
        save(root/'post-assessment-refit/receipt.json',{'schemaVersion':VERSION+'_POST_ASSESSMENT_REFIT',
             'createdAtUtc':now(),'assessedHoldoutReceipt':reference(done),'selection':decision,'models':refits,
             'latestRecordedGameDate':str(features.game_date.max()),'sourceAcquiredAtUtc':acquisition['acquiredAtUtc'],
             'evidenceClass':declaration['evidenceClass'],'authority':RESEARCH_FLAGS,
             'sourceCoverageThroughSeasonEnd':2025,'futureScheduleAvailable':False,'genuineFutureForecastPublished':False})
    return {'status':'COMPLETED','receipt':reference(done),'overall':results['overall'],'selection':decision,'verification':verification}
