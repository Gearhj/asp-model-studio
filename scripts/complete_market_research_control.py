"""Run the single matched market-only nonlinear control; never repeat prior fits."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
from server.market_intelligence.research_models import run_research
from scripts.run_market_intelligence_rff import canonical,write_immutable
from scripts.finalize_market_intelligence_rff import read_ref


def complete(parent_path):
    raw=parent_path.read_bytes();parent=json.loads(raw)
    previous=read_ref(parent['currentComparison'])
    checkpoints=read_ref(next(r for r in parent['files'] if Path(r['path']).name=='checkpoints.json.gz'))
    identity={'schemaVersion':'MARKET_RESEARCH_MATCHED_NONLINEAR_CONTROL_V1',
        'parentSha256':hashlib.sha256(raw).hexdigest(),
        'exploratoryNotPredeclared':'Market-only control added after observing composite HGB gain, to distinguish flexibility from information.',
        'implementation':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'scripts/complete_market_research_control.py','server/market_intelligence/research_models.py')},
        'allowedModels':['HGB_MARKET_ONLY_CONTROL'],'newModelFamilies':0}
    folder=ROOT/'outputs/market-intelligence-rff-v1/completed/sha256'/hashlib.sha256(canonical(identity)).hexdigest()
    if (folder/'manifest.json').exists():
        print(json.dumps({'status':'EXISTING_COMPLETED_CONTROL_REUSED','manifest':str(folder/'manifest.json')}));return
    if (folder/'attempt.json').exists(): raise ValueError('Prior incomplete control; no automatic retry')
    write_immutable(folder/'attempt.json',canonical(identity))
    control=run_research(checkpoints,folder/'fitted-artifacts',model_names={'HGB_MARKET_ONLY_CONTROL'})
    control_ref=write_immutable(folder/'control-comparison.json',canonical(control))
    if control['completedEstimatorFits']!=3 or control['failures']:
        raise ValueError('Control incomplete; retained '+str(control_ref))
    fitted=next(m for m in control['models'] if m['model']=='HGB_MARKET_ONLY_CONTROL')
    composite=next(m for m in previous['models'] if m['model']=='HGB_RESEARCH_CHALLENGER')
    if fitted['eventIds']!=composite['eventIds']:
        raise ValueError('Control and composite have different validation populations')
    for a,b in zip(fitted['folds'],composite['folds'],strict=True):
        if a['trainingEvents']!=b['trainingEvents'] or a['validationEvents']!=b['validationEvents']:
            raise ValueError('Control and composite chronological folds differ')
    movement=next(m for m in previous['models'] if m['target']=='next_movement')
    wanted=set(movement['eventIds'])
    deltas=np.array([r['next_probability']-r['consensus_probability'] for r in checkpoints
        if r['event_id'] in wanted and r['checkpoint']=='60M' and r['market_type']=='MONEYLINE' and r['period']=='full_game'])
    contrast={'sameGames':len(fitted['eventIds']),'sameTrainingAndValidationFolds':True,
        'compositeMinusMarketOnlyLogLoss':composite['metrics']['logLoss']-fitted['metrics']['logLoss'],
        'compositeMinusMarketOnlyBrier':composite['metrics']['brier']-fitted['metrics']['brier'],
        'interpretation':'Negative means sample improvement from composite; exploratory, not isolated component evidence or independent confirmation.',
        'movementZeroChangeBaseline':{'events':len(deltas),'mae':float(np.mean(np.abs(deltas))),
            'rmse':float(np.sqrt(np.mean(deltas**2))),'exactZeroTargets':int(np.sum(deltas==0))}}
    combined={**previous,'status':'BOUNDED_MARKET_RESEARCH_COMPLETE_EXPLORATORY_ONLY',
        'models':previous['models']+[fitted], 'artifacts':previous['artifacts']+control['artifacts'],
        'actualEstimatorFitStarts':previous['actualEstimatorFitStarts']+control['actualEstimatorFitStarts'],
        'completedEstimatorFits':previous['completedEstimatorFits']+control['completedEstimatorFits'],
        'exploratoryMatchedControl':contrast,'controlReceipt':control_ref}
    result=write_immutable(folder/'model-comparison.json',canonical(combined))
    manifest={**identity,'sourceSha256':parent['sourceSha256'],'sourceManifest':parent['sourceManifest'],
        'predecessorManifest':str(parent_path),'currentComparison':result,'status':'RESEARCH_SHADOW',
        'promotion':'NOT_PROMOTED','wageringAuthority':False,'executionAllowedInAISP':False,
        'aispImportAction':'NONE_NO_FORECAST_OR_POLICY_IMPORT; READ_ONLY_RESEARCH_REVIEW_ONLY',
        'rights':parent['rights'],
        'files':[r for r in parent['files'] if Path(r['path']).name!='model-comparison.json']+[result,control_ref]}
    for p in sorted((folder/'fitted-artifacts').glob('**/*')):
        if p.is_file():
            data=p.read_bytes();manifest['files'].append({'path':str(p.relative_to(ROOT)).replace('\\','/'),
                'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    ref=write_immutable(folder/'manifest.json',canonical(manifest))
    print(json.dumps({'manifest':ref,'contrast':contrast,'controlMetrics':fitted['metrics'],
        'actualEstimatorFitStarts':combined['actualEstimatorFitStarts'],'completedEstimatorFits':combined['completedEstimatorFits']},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-manifest',type=Path,required=True)
    complete(parser.parse_args().parent_manifest.resolve())
