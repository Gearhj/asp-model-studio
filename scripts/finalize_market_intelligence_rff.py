"""One explicit supported-context recovery of the failed HGB research slots.

Preserves the original attempt and reuses every completed fitted artifact. No
automatic retry loop; changed data or failure stops this recovery.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import joblib
import numpy as np
import pandas as pd
from server.market_intelligence.market_tape import build_tape
from server.market_intelligence.research_models import run_research
from scripts.run_market_intelligence_rff import canonical,write_immutable


def read_ref(ref,base=ROOT):
    path=Path(ref['path'])
    if not path.is_absolute(): path=base/path
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=ref['sha256'] or len(data)!=ref['bytes']:
        raise ValueError('Immutable checksum mismatch: '+str(path))
    return json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)


def finalize(previous_manifest):
    previous_raw=previous_manifest.read_bytes()
    previous=json.loads(previous_raw)
    refs={Path(r['path']).name:r for r in previous['files']}
    original=read_ref(refs['model-comparison.json'])
    source_path=Path(previous['sourceManifest'])
    source_raw=source_path.read_bytes()
    if hashlib.sha256(source_raw).hexdigest()!=previous['sourceSha256']:
        raise ValueError('Source manifest changed')
    source=json.loads(source_raw)
    families={k:read_ref(v,source_path.parent) for k,v in source['files'].items()}
    tape=build_tape(families['events'],families['quotes'],families['forecasts'],source['capturedAt'],
        families['prediction_markets'],families['game_state_observations'])
    checkpoints=read_ref(refs['checkpoints.json.gz'])
    if canonical(checkpoints)!=canonical(tape['checkpoints']):
        raise ValueError('Final safety guards changed the actual checkpoint population; recovery refused')
    # Reuse only completed artifacts whose original fixtures reload exactly.
    reloaded=[]
    for artifact in original['artifacts']:
        data=Path(artifact['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=artifact['sha256']:
            raise ValueError('Completed estimator changed')
        fixture=read_ref(artifact['reloadFixture'])
        fitted=joblib.load(artifact['path'])
        actual=fitted.predict(pd.DataFrame(fixture['rows']))
        difference=float(np.max(np.abs(actual-np.asarray(fixture['expectedPredictions']))))
        # The original artifact contract already uses 1e-12. Five-row fixture
        # replay can round matrix products differently from the full fold batch.
        if difference>1e-12:
            raise ValueError('Completed estimator no longer reproduces original fixture')
        reloaded.append({'sha256':artifact['sha256'],'fixtureRows':len(actual),
            'maximumDifference':difference,'tolerance':1e-12,'bitwiseEqual':difference==0})
    expected_failure=[f for f in original['failures'] if f['model']=='HGB_RESEARCH_CHALLENGER' and f['fold']==1 and 'PermissionError' in f['error']]
    if len(original['failures'])!=1 or len(expected_failure)!=1:
        raise ValueError('Recovery only supports the exact recorded single failed HGB first fold')
    implementation={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in (
        ROOT/'scripts/finalize_market_intelligence_rff.py',ROOT/'scripts/run_market_intelligence_rff.py',
        ROOT/'server/market_intelligence/market_tape.py',ROOT/'server/market_intelligence/research_models.py',
        ROOT/'docs/rff_component_contract_v1.json')}
    identity={'schemaVersion':'MARKET_RFF_HGB_RECOVERY_V1','predecessorSha256':hashlib.sha256(previous_raw).hexdigest(),
        'sourceSha256':previous['sourceSha256'],'implementation':implementation,
        'allowedModels':['HGB_RESEARCH_CHALLENGER'],'automaticRetry':False}
    output=ROOT/'outputs/market-intelligence-rff-v1/recovery/sha256'/hashlib.sha256(canonical(identity)).hexdigest()
    if (output/'manifest.json').exists():
        print(json.dumps({'status':'EXISTING_IMMUTABLE_RECOVERY_REUSED','manifest':str(output/'manifest.json')}))
        return
    if (output/'attempt.json').exists():
        raise ValueError('Recovery already started without a completed manifest; no automatic retry permitted')
    write_immutable(output/'attempt.json',canonical(identity))
    recovered=run_research(checkpoints,output/'fitted-artifacts',model_names={'HGB_RESEARCH_CHALLENGER'})
    recovery_ref=write_immutable(output/'recovery-comparison.json',canonical(recovered))
    if recovered['failures'] or recovered['completedEstimatorFits']!=3:
        raise ValueError('Bounded recovery failed; preserved receipt '+str(recovery_ref))
    combined={**original,'status':'BOUNDED_RESEARCH_COMPLETED_WITH_RECORDED_RECOVERY',
        'models':[m for m in original['models'] if m['model']!='HGB_RESEARCH_CHALLENGER']+
            [m for m in recovered['models'] if m['model']=='HGB_RESEARCH_CHALLENGER'],
        'artifacts':original['artifacts']+recovered['artifacts'],
        'actualEstimatorFitStarts':original['actualEstimatorFitStarts']+recovered['actualEstimatorFitStarts'],
        'completedEstimatorFits':original['completedEstimatorFits']+recovered['completedEstimatorFits'],
        'predecessorAttempt':refs['model-comparison.json'],'recoveryAttempt':recovery_ref,
        'originalFailuresPreserved':True,'newFailures':recovered['failures'],
        'unchangedCompletedEstimatorReloads':reloaded,'checkpointReconstructionBitwiseEqual':True}
    comparison_ref=write_immutable(output/'model-comparison.json',canonical(combined))
    manifest={**identity,'status':'RESEARCH_SHADOW','promotion':'NOT_PROMOTED',
        'wageringAuthority':False,'executionAllowedInAISP':False,'sourceManifest':str(source_path),
        'predecessorManifest':str(previous_manifest),'currentComparison':comparison_ref,
        'files':[comparison_ref,recovery_ref]+[r for r in previous['files'] if Path(r['path']).name!='model-comparison.json'],
        'originalFailedAttemptPreserved':True,'supportedWindowsRecovery':True,
        'checkpointReconstructionBitwiseEqual':True,'unchangedCompletedEstimatorReloads':reloaded,
        'rights':previous['rights'],'aispImportAction':'NONE_NO_FORECAST_OR_POLICY_IMPORT; LOCAL_READ_ONLY_RESEARCH_REVIEW_ONLY'}
    for p in sorted((output/'fitted-artifacts').glob('**/*')):
        if p.is_file():
            raw=p.read_bytes();manifest['files'].append({'path':str(p.relative_to(ROOT)).replace('\\','/'),
                'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)})
    ref=write_immutable(output/'manifest.json',canonical(manifest))
    print(json.dumps({'manifest':ref,'actualEstimatorFitStarts':combined['actualEstimatorFitStarts'],
        'completedEstimatorFits':combined['completedEstimatorFits'],'reusedCompletedFits':len(reloaded),
        'recoveryCompletedFits':recovered['completedEstimatorFits'],'models':[
            {k:m.get(k) for k in ('model','target','status','events','metrics','baselineMetricsSameEvents')}
            for m in combined['models']]},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--previous-manifest',type=Path,required=True)
    finalize(parser.parse_args().previous_manifest.resolve())
