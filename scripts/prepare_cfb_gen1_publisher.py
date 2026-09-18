"""Discover exact retained CFB baseline; reproduce, admit offline, no fitting/HTTP."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
from server.sports_cfb_gen1.publication_io import reference,verified_bytes,canonical_bytes,digest
from server.sports_cfb_gen1.lifecycle import immutable,now,read_ref,object_json,POLICY,eligibility
from server.sports_cfb_gen1.inputs import admit,parquet
from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS
from server.sports_cfb_gen1.render import numerical_population,CONFIGURATION,verify_package


def main():
    p=argparse.ArgumentParser();p.add_argument('--studio',default=r'C:\Users\james\asp-model-studio')
    p.add_argument('--output',required=True);a=p.parse_args()
    root=Path(a.studio);out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    receipt=out/'preparation.json'
    if receipt.exists():
        prior=read_ref(reference(receipt))
        for ref in prior['preservedObjects']:verified_bytes(ref)
        print(json.dumps({'status':'REUSED_PREPARATION','receipt':reference(receipt)}));return
    current=root/'outputs/cfb-gen1-current-v1';hist=root/'outputs/cfb-gen1-v1'
    source_forecast=read_ref(reference(current/'forecast/forecast.json'))
    bindings=source_forecast['modelBindings']
    assert source_forecast['baseline']['configuration']==CONFIGURATION
    preserved=[]
    for ref in bindings.values():
        verified_bytes(ref);preserved.append(reference(ref['path']))
    donor_meta=pd.read_parquet(bindings['pairedResidualPopulation']['path'],columns=['season','scheduled_at'])
    assert donor_meta.season.max()<=2025
    numerical=[]
    for directory in [current/'forecast',root/'.runtime/scotty-demo-20260916-v1/cfb-weekend']:
        f=read_ref(reference(directory/'forecast.json'));gid=f['game']['game_id']
        cols=list(dict.fromkeys(FEATURE_COLUMNS+['game_id','season','scheduled_at','elo_home_win_probability']))
        target=pd.read_parquet(current/'cfbd-2026-point-in-time-features.parquet',columns=cols,filters=[('game_id','=',gid)]).iloc[0]
        point,ph,draws,accounting=numerical_population(target,bindings,f['sourceCutoff'])
        original=pd.read_parquet(directory/'baseline-joint-draws.parquet')
        pd.testing.assert_frame_equal(draws,original,check_exact=True)
        for key,name in [('homePoints','expectedHomePoints'),('awayPoints','expectedAwayPoints'),('homeMargin','expectedHomeMargin'),('totalPoints','expectedTotal')]:
            assert abs(point[key]-f['baseline'][name])<1e-8
        assert abs(ph-f['baseline']['ridgeHomeWinProbability'])<1e-12
        assert abs(float((draws.home_score>draws.away_score).mean())-f['baseline']['jointHomeWinProbability'])<1e-12
        numerical.append({'gameId':gid,'forecastId':f['forecastId'],'forecast':reference(directory/'forecast.json'),
            'draws':reference(directory/'baseline-joint-draws.parquet'),'point':point,'calibratedHomeWin':ph,
            'jointHomeWin':f['baseline']['jointHomeWinProbability'],'orderedDrawsExactlyEqual':True,
            'drawCount':len(draws),'transformationAccounting':accounting})
        for name in ('forecast.json','baseline-joint-draws.parquet','baseline-pmfs.parquet'):
            preserved.append(reference(directory/name))
    original_delivery=read_ref(reference(current/'delivery-index.json'))
    demo=read_ref(reference(Path(__file__).resolve().parents[1]/'docs/scotty-demo-release-v1/PUBLICATION.json'))
    package_indexes=[original_delivery['exchangeIndex'],demo['cfbWeekendPackage']]
    for bound in package_indexes:
        index=read_ref(bound);directory=Path(bound['path']).parent
        verify_package(directory)
        for path in directory.iterdir():
            if path.is_file():preserved.append(reference(path))
    source_history=reference(hist/'data/admitted-games.parquet')
    history_meta=pd.read_parquet(source_history['path'],columns=['season','game_id','scheduled_at'])
    history=pd.read_parquet(source_history['path'],filters=[('season','<',2026)])
    assert len(history)==int((history_meta.season<2026).sum())
    history_ref=parquet(out/'frozen-inputs','historical-through-2025.parquet',history)
    rights_ref=reference(current/'cfbd-terms-review.json')
    rights=read_ref(rights_ref)
    for ref in rights['evidence']:verified_bytes(ref)
    consumer_files=[Path(r'C:\Users\james\ai-sports-predictor\server\app\cfb\research_import.py'),
        Path(r'C:\Users\james\ai-sports-predictor\server\app\services\house_divided.py')]
    provisional={'schema':'CFB_GEN1_STAGED_BASELINE_CONFIGURATION_V1','configurationIdentity':CONFIGURATION,
        'modelBindings':bindings,'historicalGames':history_ref,'historicalSourceGames':source_history,
        'historicalProjectionRule':'season < 2026; unchanged original pipeline input rule',
        'featureColumns':FEATURE_COLUMNS,'trainingThroughSeason':2025,'simulationCount':10000,
        'seedPolicy':'SHA256(20260914|CFBD game ID|ridge_alpha100)','policy':POLICY,
        'rightsEvidence':rights_ref,'consumerCodeEvidence':[reference(x) for x in consumer_files],
        'consumerDeadline':{'minutesBeforeKickoff':15,'producerCloseMinutesBeforeKickoff':30,
            'qualification':'AISP House Divided common cutoff; CFB official decision pipeline absent. Consumer activation and discovery integration remain separate.'},
        'limitations':source_forecast['limitations']+[
            'Early-season lack of current support remains disclosed; no new model selection.',
            'Point expectations, calibrated winner, Elo, and transformed joint probabilities remain separate.',
            'Existing joint draws floor negatives, stochastically round and resample tied full games; no explicit football drive or overtime model.',
            'No schedule-strength or conference-identity challenger is enabled; existing conference_competition indicator is unchanged.'],
        'prospectiveEffectiveAtUtc':now(),'preservedResearchPackages':package_indexes}
    frozen_ref=object_json(out/'configuration',provisional,'configuration.json')
    input_ref=admit(manifest_ref=reference(current/'cfbd-source-manifest.json'),release=provisional,
                    registry_root=out/'inputs')
    b=read_ref(input_ref)
    old=pd.read_parquet(current/'cfbd-2026-point-in-time-features.parquet',columns=['game_id']+FEATURE_COLUMNS).sort_values('game_id').reset_index(drop=True)
    new=pd.read_parquet(b['features']['path'],columns=['game_id']+FEATURE_COLUMNS).sort_values('game_id').reset_index(drop=True)
    pd.testing.assert_frame_equal(old,new,check_exact=True)
    clock=now();inventory=[{'gameId':x['gameId'],'target':x['target'],**eligibility(x,b,clock)} for x in b['games']]
    inv_ref=object_json(out/'inventory',{'createdAtUtc':clock,'games':inventory,'inputVersion':input_ref},'inventory.json')
    result={'schema':'CFB_GEN1_PUBLISHER_PREPARATION_V1','createdAtUtc':clock,'configuration':frozen_ref,
        'inputVersion':input_ref,'inventory':inv_ref,'baselineReproductions':numerical,
        'allRetainedFeatureRowsExactlyReproduced':len(new),'preservedObjects':preserved,
        'providerCalls':0,'aispWrites':0,'modelFits':0,'targetOutcomesReadForAssessment':False,
        'simulationDrawsReproduced':20000,'newProspectiveForecasts':0}
    immutable(receipt,canonical_bytes(result))
    print(json.dumps({'receipt':reference(receipt),'configuration':frozen_ref,'inputVersion':input_ref,
        'featureRows':len(new),'baselineReproductions':[{k:x[k] for k in ('gameId','forecastId','point','calibratedHomeWin','jointHomeWin','orderedDrawsExactlyEqual')} for x in numerical]},indent=2))


if __name__=='__main__':main()
