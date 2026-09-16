"""Build offline MLB market/RFF research from a checksum-verified local export.

No database or provider access and no official model/policy execution.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.market_intelligence.market_tape import build_tape
from server.market_intelligence.research_models import run_research


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def write_immutable(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if path.read_bytes()!=data: raise ValueError('Immutable content conflict: '+str(path))
    else:
        with path.open('xb') as f: f.write(data)
    return {'path':str(path.relative_to(ROOT)).replace('\\','/'),
        'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}


def run(source_manifest):
    raw=source_manifest.read_bytes()
    source=json.loads(raw)
    families={}
    entries=source['files']
    if isinstance(entries,dict): entries=[dict(v,name=k) for k,v in entries.items()]
    for entry in entries:
        path=Path(entry['path'])
        if not path.is_absolute():
            path=source_manifest.parent/path if (source_manifest.parent/path).exists() else ROOT/path
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=entry['sha256'] or len(data)!=entry['bytes']:
            raise ValueError('Source checksum/length mismatch: '+str(path))
        name=entry.get('name',path.name).replace('.json.gz','').replace('.json','').replace('-','_')
        families[name]=json.loads(gzip.decompress(data) if path.suffix=='.gz' else data)
    source_digest=hashlib.sha256(raw).hexdigest()
    tape=build_tape(families['events'],families['quotes'],families['forecasts'],
        source.get('capturedAt',source.get('captured_at',source.get('capturedAtUtc',source.get('extractedAt')))),
        families.get('prediction_markets',families.get('prediction_market_snapshots',[])),
        families.get('game_state_observations',[]))
    implementation={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
        'scripts/run_market_intelligence_rff.py','server/market_intelligence/market_tape.py',
        'server/market_intelligence/research_models.py','docs/rff_component_contract_v1.json')}
    identity={'schemaVersion':'MARKET_INTELLIGENCE_RFF_RESEARCH_V1','sourceSha256':source_digest,
              'implementation':implementation,'seed':20260910}
    identity_digest=hashlib.sha256(canonical(identity)).hexdigest()
    output=ROOT/'outputs/market-intelligence-rff-v1/research/sha256'/identity_digest
    refs=[]
    for name in ('pairs','quote_exclusions','checkpoints','ledger'):
        refs.append(write_immutable(output/(name+'.json.gz'),gzip.compress(canonical(tape[name]),mtime=0)))
    comparison=run_research(tape['checkpoints'],output/'fitted-artifacts')
    refs.append(write_immutable(output/'model-comparison.json',canonical(comparison)))
    ledger=tape['ledger']
    coverage={'schemaVersion':'RFF_EVIDENCE_COVERAGE_V1','gameCount':len({r['event_id'] for r in ledger}),
        'checkpointRows':len(ledger),'componentSupportedCounts':dict(Counter(k for r in ledger for k,v in r['components'].items() if v is not None)),
        'statusCounts':dict(Counter(r['status'] for r in ledger)),
        'essentialHandleEvidenceAvailable':any(r['essential_handle_available'] for r in ledger),
        'coverageIsNotPredictiveConfidence':True,
        'unavailable':['public_ticket_shares','public_handle_shares','coherent_same_source_handle_prices',
                       'validated_role_uncertainty_manifest','archived_social_narrative_baseline'],
        'predictionMarketRestriction':'Only contemporaneously semantics-matched full-game contracts may contribute; volume is not sportsbook handle.'}
    refs.append(write_immutable(output/'rff-evidence-coverage.json',canonical(coverage)))
    refs.append(write_immutable(output/'tape-summary.json',canonical(tape['summary'])))
    manifest={**identity,'identitySha256':identity_digest,'sourceManifest':str(source_manifest),
        'files':refs,'status':'RESEARCH_SHADOW','promotion':'NOT_PROMOTED','wageringAuthority':False,
        'executionAllowedInAISP':False,'positionsCreated':0,'providerCalls':0,'finalOotPayloadAccess':False,
        'handoffDisposition':'READ_ONLY_RESEARCH_ARTIFACTS_ONLY_NOT_FORECAST_OR_POSITION_IMPORT',
        'rights':'LOCAL_PRIVATE_RESEARCH_ONLY_SOURCE_LICENSE_RESTRICTIONS_RETAINED_NO_REDISTRIBUTION_OR_COMMERCIAL_RIGHTS_GRANTED',
        'notes':['Source event payload excluded at SQL boundary for August14–27 2026.',
                 'Fixed research age/checkpoint conventions do not alter official policy thresholds.',
                 'RFF bounds are missing-component bounds, not statistical confidence intervals.']}
    # Include all fitted objects, each containing estimator/preprocessor/order/reload fixture.
    for path in sorted((output/'fitted-artifacts').glob('**/*')):
        if path.is_file():
            data=path.read_bytes()
            manifest['files'].append({'path':str(path.relative_to(ROOT)).replace('\\','/'),
                'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    reference=write_immutable(output/'manifest.json',canonical(manifest))
    print(json.dumps({'manifest':reference,'summary':tape['summary'],'coverage':coverage,
        'comparisonStatus':comparison.get('status'), 'researchIdentity':identity_digest},indent=2))
    return reference


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',type=Path,required=True)
    run(parser.parse_args().source_manifest.resolve())
