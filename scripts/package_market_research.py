"""Package frozen research for read-only review, never forecast/position import."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.run_market_intelligence_rff import canonical,write_immutable
from scripts.finalize_market_intelligence_rff import read_ref
from server.market_intelligence.research_models import _prepare,_metrics
import joblib
import numpy as np


def package(manifest_path):
    manifest_raw=manifest_path.read_bytes();manifest=json.loads(manifest_raw)
    for ref in manifest['files']:
        data=(ROOT/ref['path']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=ref['sha256'] or len(data)!=ref['bytes']:
            raise ValueError('Research checksum mismatch')
    names=('docs/MARKET_INTELLIGENCE_RFF_RESEARCH_REPORT_V1.md',
        'docs/MARKET_INFORMATION_CONTRACT_FEATURE_SPEC_V1.md','docs/rff_component_contract_v1.json',
        'outputs/market-intelligence-rff-v1/verification.json')
    payloads={Path(name).name:(ROOT/name).read_bytes() for name in names}
    comparison=read_ref(manifest['currentComparison'])
    checkpoints=read_ref(next(r for r in manifest['files'] if Path(r['path']).name=='checkpoints.json.gz'))
    frame,_=_prepare(checkpoints)
    primary=frame[frame.checkpoint.eq('60m')].set_index('event_id',drop=False)
    predictions=[]
    for ref in comparison['artifacts']:
        fitted=joblib.load(ref['path'])
        valid=primary.loc[fitted.fold_contract['validationEvents']]
        actual=fitted.predict(valid)
        for (_,r),p in zip(valid.iterrows(),actual,strict=True):
            predictions.append({'event_id':r.event_id,'event_start':r.event_start.isoformat(),
                'checkpoint_at':r.checkpoint_at.isoformat(),'model':fitted.model,'target':fitted.target,
                'fold':fitted.fold_contract['fold'],'prediction':float(p),'actual':float(r[fitted.target]),
                'market_probability':float(r.consensus_probability),'estimator_sha256':ref['sha256']})
    maximum_metric_error=0.
    for model in comparison['models']:
        selected=[r for r in predictions if r['model']==model['model'] and r['target']==model['target']]
        if not selected: continue
        metrics=_metrics(np.array([r['actual'] for r in selected]),np.array([r['prediction'] for r in selected]),
            regression=model['target']=='next_movement')
        for key in ('logLoss','brier','mae','rmse'):
            if key in metrics:
                maximum_metric_error=max(maximum_metric_error,abs(metrics[key]-model['metrics'][key]))
    if maximum_metric_error>1e-12: raise ValueError('Reloaded OOF metrics differ from the completed study')
    payloads['oof-predictions.json.gz']=gzip.compress(canonical(predictions),mtime=0)
    refs={name:{'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)} for name,raw in payloads.items()}
    descriptor={'schemaVersion':'MARKET_RFF_READ_ONLY_RESEARCH_HANDOFF_V1','sport':'MLB',
        'researchManifest':{'path':str(manifest_path.relative_to(ROOT)).replace('\\','/'),
            'sha256':hashlib.sha256(manifest_raw).hexdigest(),'bytes':len(manifest_raw)},
        'sourceManifestPath':manifest['sourceManifest'],'sourceManifestSha256':manifest['sourceSha256'],
        'documents':refs,'status':'RESEARCH_SHADOW','promotionStatus':'NOT_PROMOTED',
        'oofReload':{'predictionRows':len(predictions),'estimatorFits':0,'maximumMetricDifference':maximum_metric_error},
        'wageringAuthority':False,'executionAllowedInAISP':False,'forecastRows':0,
        'importDisposition':'READ_ONLY_REVIEW_ONLY_EXISTING_AISP_FORECAST_IMPORTERS_NOT_APPLICABLE',
        'rights':manifest['rights'],'findings':'EXPLORATORY_COMPOSITE_GAIN_SMALL_SAMPLE; NO_VALIDATED_COMPONENT_OR_WAGERING_EDGE; COMPLETE_RFF_UNSUPPORTED'}
    raw=canonical(descriptor);digest=hashlib.sha256(raw).hexdigest()
    folder=ROOT/'outputs/market-intelligence-rff-v1/handoff/sha256'/digest
    for name,data in payloads.items(): write_immutable(folder/name,data)
    reference=write_immutable(folder/'manifest.json',raw)
    print(json.dumps({'handoff':reference,'documents':len(payloads),'forecasts':0},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--research-manifest',type=Path,required=True)
    package(parser.parse_args().research_manifest.resolve())
