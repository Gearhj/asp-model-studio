"""Filter existing frozen V18 populations; never simulate, fit, or load outcomes."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts.package_mlb_v18_transition_adapter_v2 import canonical, reference, verify_ref, immutable, aware
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_v18_score_limited import apply_score_limits, COMPONENT_ID, BASELINE_ARRAY_NAMES

OUT = ROOT/'outputs/mlb-v18-score-limited-v1'
PRIOR = ROOT/'outputs/mlb-v18-population-diagnostics-v1'
MODULE = ROOT/'server/sports_current_statcast/mlb_v18_score_limited.py'
FLAGS = dict(executionAllowed=False, wageringAuthority=False, activatesModel=False,
             executionAllowedInAISP=False, candidateAuthority=False, productionAuthority=False)

def now():
    return datetime.now(timezone.utc).isoformat()

def object_bytes(name, raw):
    digest = hashlib.sha256(raw).hexdigest()
    return immutable(OUT/'objects/sha256'/digest/name, raw)

def read_ref(item):
    return json.loads(verify_ref(item).read_bytes())

def guard(row):
    if not all(final_oot_eligible_key_mask([row['gameId'], str(row['sourceGameId'])])):
        raise ValueError('WHOLE_GAME_QUARANTINE')
    if '2026-08-14' <= row['scheduledStartUtc'][:10] <= '2026-08-27':
        raise ValueError('SEALED_FINAL_OOT')

def run():
    inventory_ref = reference(OUT/'inventory/coverage.json')
    inventory = read_ref(inventory_ref)
    rule_ref = json.loads((OUT/'development-rule/current.json').read_bytes())['rule']
    rule = read_ref(rule_ref)
    publication_ref = reference(OUT/'publication/rule-publication.json')
    publication = read_ref(publication_ref)
    assert publication['status'] == 'PUBLISHED_RULE' and publication['rule'] == rule_ref
    delivered = publication['deliveredRule']
    verify_ref(delivered)
    assert (delivered['sha256'], delivered['bytes']) == (rule_ref['sha256'], rule_ref['bytes'])
    assert aware(publication['publishedAtUtc']) <= datetime.now(timezone.utc)
    # Inventory is identity metadata. Quarantine every game before any score payload.
    for row in inventory['ordinaryForecasts']:
        guard(row)
    protocol_path = OUT/'protocol-before-filter.json'
    if not protocol_path.exists():
        immutable(protocol_path, canonical({'schemaVersion':'MLB_V18_SCORE_LIMIT_PROTOCOL_V1',
            'createdAtUtc':now(), 'rule':rule_ref,'rulePublication':publication_ref,
            'inventory':inventory_ref,'population':'Every eligible immutable ordinary V18 object available at the recorded inventory time',
            'counterCoverage':inventory['summary'], 'futureGame':inventory['prospectiveCandidate'],
            'prospectiveStoppingRule':'Exactly the declared CIN-MIL 823734 baseline before its original 17:55Z cutoff; no extension or backfill.',
            'winnerPick':'HOME if pHome>0.5; AWAY if pHome<0.5; exactly0.5 NO_PICK',
            'primaryMetrics':['correct winner picks','wrong to right','right to wrong','winner log loss','binary Brier'],
            'secondaryMetrics':['both-team expected-score MAE','total-run MAE'],
            'minimumRetainedDraws':1000,'thresholdOptimization':False,
            'historicalStatus':'EXPLORATORY; previously observed and selected diagnostic cases',
            'economics':'Argmax winner picks are separate from offered-price team selection; no economics claim or policy change.',
            'outcomesRead':False, **FLAGS}))
    protocol_ref = reference(protocol_path)
    executions = []
    # Freeze the future comparison first, with no outcome access anywhere in this program.
    rows = sorted(inventory['counterPopulations'], key=lambda r: (str(r['sourceGameId']) != '823734', str(r['sourceGameId'])))
    for row in rows:
        guard(row)
        game = str(row['sourceGameId'])
        pointer = OUT/'executions'/game/'current.json'
        if pointer.exists():
            saved_ref = json.loads(pointer.read_bytes())
            saved = read_ref(saved_ref)
            assert saved['rule'] == rule_ref and saved['baselineObjectSha256'] == row['baselineObjectSha256']
            assert saved['componentSource'] == reference(MODULE)
            if saved['status'] == 'SUPPORTED':
                verify_ref(saved['acceptedPopulation'])
            else:
                assert saved['acceptedPopulation'] is None
            executions.append(saved_ref)
            continue
        started = now()
        prospective = game == str(inventory['prospectiveCandidate']['sourceGameId'])
        if prospective and aware(started) >= aware(row['cutoffUtc']):
            status = object_bytes('expired.json', canonical({'status':'EXPIRED_UNPUBLISHED','sourceGameId':game,
                'createdAtUtc':started,'deadlineUtc':row['cutoffUtc'],'rule':rule_ref,**FLAGS}))
            executions.append(status)
            continue
        bundle = load_baseline(row['baselineObjectSha256'])
        f = bundle['forecast']
        snapshot_ref = bundle['execution']['featureSnapshot']
        baseline_ref = reference(bundle['directory']/'forecast.json')
        source_execution = reference(bundle['directory']/'execution-inputs.json')
        baseline = {k:np.asarray(bundle['baseline'][k]) for k in BASELINE_ARRAY_NAMES}
        before = {k:v.copy() for k,v in baseline.items()}
        sidecar_pointer = PRIOR/('future' if prospective else 'retrospective')/game/'enriched.json'
        sidecar_ref = json.loads(sidecar_pointer.read_bytes())
        sidecar = read_ref(sidecar_ref)
        assert sidecar['baselineObjectSha256'] == row['baselineObjectSha256']
        assert sidecar['forecast'] == baseline_ref and sidecar['executionInputs'] == source_execution
        assert sidecar['featureSnapshot'] == snapshot_ref and sidecar['originalSourceCutoff'] == f['sourceCutoff']
        assert sidecar['parentInvariancePassed'] and sidecar['originalArraysExact'] and sidecar['parentAccountingPassed']
        if prospective:
            assert sidecar['eligibleProspectiveCapture'] and aware(sidecar['artifactsCompletedAtUtc']) < aware(row['cutoffUtc'])
        population_ref = sidecar['enrichedPopulation']
        with np.load(verify_ref(population_ref), allow_pickle=False) as z:
            diagnostics = {k:z[k] for k in z.files}
        result = apply_score_limits(baseline, diagnostics, rule['limits'])
        assert all(np.array_equal(before[k], baseline[k]) for k in baseline)
        assert reference(bundle['directory']/'forecast.json') == baseline_ref
        assert reference(bundle['directory']/'execution-inputs.json') == source_execution
        accepted_ref = None
        if result['status'] == 'SUPPORTED':
            payload = {**{'baseline_'+k:v for k,v in baseline.items()},
                **{'accepted_'+k:v for k,v in result['retainedArrays'].items()},
                'accepted_indices':result['acceptedDrawIndices'], 'acceptance_mask':result['acceptMask']}
            buffer = io.BytesIO()
            np.savez_compressed(buffer, **payload)
            accepted_ref = object_bytes('accepted-population.npz', buffer.getvalue())
        retained_result = {k:v for k,v in result.items() if k not in ('retainedArrays','acceptedDrawIndices','acceptMask')}
        frozen = now()
        classification = 'PROSPECTIVE_SCORE_LIMITED_RESEARCH' if prospective else 'EXPLORATORY_RETROSPECTIVE'
        if prospective and aware(frozen) >= aware(row['cutoffUtc']):
            classification = 'EXPIRED_UNPUBLISHED'
        execution = {**retained_result, 'schemaVersion':'MLB_V18_SCORE_LIMITED_EXECUTION_V1',
            'classification':classification,'componentIdentity':COMPONENT_ID,'componentSource':reference(MODULE),
            'runner':reference(__file__),'createdAtUtc':started,'frozenAtUtc':frozen,
            'baselineObjectSha256':row['baselineObjectSha256'],
            'baselineForecastId':'mlb-v18-daily-'+row['baselineObjectSha256'],
            'gameId':f['gameId'],'sourceGameId':game,
            'awayTeam':f['teams']['AWAY']['abbreviation'],'homeTeam':f['teams']['HOME']['abbreviation'],
            'scheduledStartUtc':row['scheduledStartUtc'],'deadlineUtc':row['cutoffUtc'],
            'rule':rule_ref,'rulePublication':publication_ref,'protocol':protocol_ref,
            'sourcePopulation':population_ref,'sourceSidecar':sidecar_ref,'acceptedPopulation':accepted_ref,
            'baselineForecast':baseline_ref,'sourceExecutionInputs':source_execution,
            'featureSnapshot':snapshot_ref,'sourceCutoff':f['sourceCutoff'],
            'sourceCaptureUtc':f['capturedAt'],'originalForecastCreatedAtUtc':f['forecastCreatedAt'],
            'sourceSimulationCount':5000,'originalDrawCount':5000,'seed':f['simulation']['seed'],
            'baselineUnchangedExact':True, 'outcomesRead':False,'simulationReruns':0,
            'newRandomDraws':0,'providerRequests':0,'sourceCountMeaning':'Original frozen V18 population',
            'sequenceMeaning':'Original draw indices and all saved counters remain bound. No full unsaved sequences reconstructed.',
            **FLAGS}
        if execution['summary'] is not None:
            execution['summary']['retainedDrawCount'] = result['retainedDrawCount']
        execution_ref = object_bytes('execution.json', canonical(execution))
        immutable(pointer, canonical(execution_ref))
        executions.append(execution_ref)
    current = {'schemaVersion':'MLB_V18_SCORE_LIMITED_EXECUTION_INDEX_V1','createdAtUtc':now(),
        'rule':rule_ref,'rulePublication':publication_ref,'protocol':protocol_ref,'inventory':inventory_ref,
        'executions':executions,'unsupportedMissingCounters':[r for r in inventory['ordinaryForecasts']
            if r['counterCoverage'] != 'FULL_PER_DRAW_INNING_RUNS'],**FLAGS}
    index = OUT/'executions/current.json'
    if not index.exists():
        immutable(index, canonical(current))
    else:
        assert json.loads(index.read_bytes())['executions'] == executions
    return reference(index)

if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(run()))
