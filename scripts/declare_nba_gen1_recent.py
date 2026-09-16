"""Metadata-first registration for the recent score/date model comparison."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import reference, verified_bytes, immutable_json, json_bytes, RESEARCH_FLAGS
from server.sports_nba_gen1.recent_features import recent_feature_contract

OUT=ROOT/'outputs/nba-gen1-recent-v1'
ENDS={2020:'2020-08-14',2021:'2021-05-16',2022:'2022-04-10',2023:'2023-04-09',2024:'2024-04-14',2025:'2025-04-13'}
CUPS=[{'seasonEnd':2024,'date':'2023-12-09','teams':['IND','LAL']},
      {'seasonEnd':2025,'date':'2024-12-17','teams':['MIL','OKC']}]


def key(year,day,one,two):
    return ':'.join(['nba-neil',str(year),day,*sorted([one,two])])


def main():
    pointer=OUT/'declaration.json'
    if pointer.exists():
        value=json.loads(pointer.read_bytes())
        verified_bytes(value['declaration'])
        print(json.dumps(value,indent=2))
        return
    acquisition=json.loads((OUT/'acquisition.json').read_bytes())
    verified_bytes(acquisition['sourceReview'])
    meta=pd.read_parquet(OUT/'scope-metadata.parquet')
    meta['game_key']=[key(r.season,r.date,r.team1,r.team2) for r in meta.itertuples()]
    cupkeys={key(c['seasonEnd'],c['date'],*c['teams']) for c in CUPS}
    admitted,contexts,counts={}, {}, []
    for year,last in ENDS.items():
        all_season=meta[(meta.season==year)&(meta.playoff=='')&(meta.date<=last)]
        cup=all_season[all_season.game_key.isin(cupkeys)]
        regular=all_season[~all_season.game_key.isin(cupkeys)]
        for _,pair in all_season.groupby('game_key'):
            assert len(pair)==2
            assert pair.team1.iloc[0]==pair.team2.iloc[1] and pair.team2.iloc[0]==pair.team1.iloc[1]
            assert pair.neutral.nunique()==1
            assert pair.is_home.tolist().count(1)==(0 if pair.neutral.iloc[0] else 1)
        admitted[str(year)]=sorted(regular.game_key.unique())
        contexts[str(year)]=sorted(cup.game_key.unique())
        roles={2020:'INITIAL_FIT',2021:'DEVELOPMENT',2022:'DEVELOPMENT',2023:'DEVELOPMENT',2024:'VALIDATION',2025:'FINAL_CATEGORY_A_HOLDOUT'}
        counts.append({'seasonEnd':year,'season':f'{year-1}-{str(year)[2:]}','role':roles[year],
                       'regularGames':regular.game_key.nunique(),'orientedTargets':int((regular.is_home==1).sum()),
                       'neutralRegularHistoryOnly':int((regular.neutral==1).sum()/2),
                       'cupDateOnlyEvents':cup.game_key.nunique(),'sourceTeamCodes':sorted(regular.team1.unique())})
    assert sum(r['regularGames'] for r in counts)==7059
    assert sum(r['orientedTargets'] for r in counts)==6952
    assert set.union(*(set(row['sourceTeamCodes']) for row in counts))==set(counts[0]['sourceTeamCodes'])
    # Cross-check only historical identity/orientation metadata, not old pilot
    # outcomes, fits, results or license approval.
    prior=pd.read_parquet(ROOT/'outputs/nba-gen1-historical-pilot-v1/identity-metadata.parquet')
    prior=prior[(prior.lg_id=='NBA')&(prior.is_playoffs==0)&prior.year_id.between(2010,2015)&(prior.game_location=='H')]
    prior_dates=pd.to_datetime(prior.date_game,format='%m/%d/%Y').dt.strftime('%Y-%m-%d')
    # Publisher retained NOH/CHA season aliases in the older export and uses
    # NOP/CHO in the updated archive. The older identity-only fran_id mapping
    # confirms those pairs refer to the same franchises; no score comparison.
    aliases={'NOH':'NOP','CHA':'CHO'}
    expected={(d,aliases.get(a,a),aliases.get(b,b)) for d,a,b in zip(prior_dates,prior.team_id,prior.opp_id)}
    recent=meta[meta.season.between(2010,2015)&(meta.playoff=='')&(meta.is_home==1)]
    observed={(r.date,r.team1,r.team2) for r in recent.itertuples()}
    assert expected==observed,'Source home orientation disagrees with prior explicit H/A identities'
    payload={'schemaVersion':'NBA_GEN1_RECENT_POINT_STUDY_DECLARATION_V1','createdAtUtc':datetime.now(timezone.utc).isoformat(),
             'evidenceClass':'A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION','performanceExamined':False,
             'source':reference(OUT/'acquisition.json'),'scopeMetadata':reference(OUT/'scope-metadata.parquet'),
             'scopeClassification':reference(OUT/'scope-classification.json'),
             'regularSeasonEndDates':{str(k):v for k,v in ENDS.items()},'cupFinals':CUPS,
             'admittedSourceKeysBySeason':admitted,'contextOnlySourceKeysBySeason':contexts,'population':counts,
             'homeOrientationCrossCheck':{'priorExplicitHomeIdentityGames':len(expected),'agreement':True,'outcomesRead':False,'explicitPriorSeasonAliasMapping':aliases},
             'coverageChoice':'Latest six completed regular seasons in admitted source metadata. No 2025-26 source rows. Calendar and explicit Cup identities, not source blank playoff flag alone, define regular-season games.',
             'historyPolicy':'Regular-season neutral games are history only, with zero home advantage. Cup finals supply dates only for rest/density; their scores never enter feature/Elo history or assessment. All same-day and later results are excluded from target features.',
             'populationChronology':'2020 warmup; expanding earlier-season fits assess2021,2022,2023 Development; select hyperparameters there.2024 Validation chooses point configuration. Freeze before one-time2025 holdout. No prior2015 assessment is reused for tuning or confirmation.',
             'featureContract':recent_feature_contract(),
             'candidates':[{'id':'league','family':'league','params':{}},{'id':'elo','family':'elo','params':{}},
                           {'id':'ridge_a10','family':'ridge','params':{'alpha':10.0}},
                           {'id':'ridge_a100','family':'ridge','params':{'alpha':100.0}},
                           {'id':'hgb_l2_10','family':'hgb','params':{'l2_regularization':10.0}},
                           {'id':'hgb_l2_50','family':'hgb','params':{'l2_regularization':50.0}}],
             'trainingRules':'Existing league/Elo methods and modest Ridge/HGB settings. Imputers, scalers and model parameters fit earlier-season training rows only. No early-stopping random split, source Elo/probabilities, odds, player models or box fabrication.',
             'winnerChannel':'League uses earlier-training home-win fraction. Elo and each Ridge/HGB POINT configuration retain the same independently rebuilt chronological Elo winner probability. Candidate point-score changes do not change this probability channel; identical winner proper scores are reported as such, never attributed to Ridge/HGB.',
             'pointSelection':{'primary':'team_score_mse = mean((home_error^2+away_error^2)/2), proper for conditional score means; equals mean((margin_error^2+total_error^2)/4)',
                               'development':'Choose alpha/l2 within each family by lowest common-cohort mean team_score_mse across three chronological Development folds. Ties favor Ridge alpha100 or HGB l2=50.',
                               'validationGate':'Candidate must improve team_score_mse by at least1% over Elo and neither margin nor total MAE may degrade by more than2%. If no candidate qualifies, keep Elo. Of qualifying families choose lower MSE; if within0.5%, prefer Ridge.',
                               'holdout':'Freeze winner channel, point configuration and all four benchmark/finalist artifacts before2025 outcomes. Report all locked comparisons once; no tuning or new candidate chosen from holdout.',
                               'promotion':'Research point baseline only. Original full Gen1 joint-energy gate remains unavailable, so no full joint-distribution champion or production authority.'},
             'metrics':['winner_log_loss','binary_brier','winner_pick_accuracy','home_mae','away_mae','margin_mae','total_mae','team_score_mse'],
             'brier':'(pHomeWin-I(home_score>away_score))^2, pAwayWin=1-pHomeWin, pTie=0',
             'uncertainty':'Paired whole-game calendar-week block bootstrap,2000 replicates,seed731201; no simulation-draw sample-size claim. Calendar dates are grouping labels, not inferred publication times.',
             'distributionStatus':'Paired season-forward residuals retained. No joint simulator run: missing overtime-period evidence under existing unchanged gate. No energy/CRPS/interval/tie-adjustment claim.',
             'postHoldoutRefit':'After immutable final assessment, refit the already selected point configuration and Elo on all admitted earlier records through2024-25. Separate research artifact; this does not refit selection or recreate past forecasts.',
             'historicalPublicationTimes':None,'protectedPartitions':'Prior2014-15 pilot remains inspected/historical. Original modern NBA proposed roles were never registered; no MLB/NFL protected payload accessed.',
             'authority':RESEARCH_FLAGS,
             'numericalModules':{name:reference(ROOT/'server/sports_nba_gen1'/name) for name in ('historical_features.py','models.py','recent_features.py','recent_models.py')}}
    bound=immutable_json(OUT,'declaration.json',payload)
    pointer.write_bytes(json_bytes({'declaration':bound}))
    print(json.dumps({'declaration':bound,'counts':[{k:v for k,v in r.items() if k!='sourceTeamCodes'} for r in counts],
                      'orientationMetadataMatches':len(expected)},indent=2))


if __name__=='__main__':
    main()
