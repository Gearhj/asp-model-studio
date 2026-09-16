"""Bind corrected V2 source records to the already verified three-game transform."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_silver.current_statcast_pa import map_pa_event
from server.sports_current_statcast.mlb_starter_duration_history import NON_PA_EVENTS
from server.sports_current_statcast.mlb_starter_duration_quarantine import LEDGER, final_oot_eligible_key_mask
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / 'outputs/mlb-v18-population-diagnostics-v1/observed-v2'
PREDECESSOR = ROOT / 'outputs/mlb-v18-population-diagnostics-v1/observed/observed.json'
INDEX = Path('C:/Users/james/asp-model-exchange/aisp-final-evidence/mlb-postgame-diagnostic-v2/postgame-diagnostic-index.json')
INDEX_SHA = '1d4a2c0db380794425d719228f4354461865d9ae0dc566492cba7afbe94803b3'
CASES = ('823496', '824870', '824630')


def ref(path):
    p = Path(path).resolve(); b = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}


def write(name, value):
    path = OUT / name
    with path.open('x', encoding='utf-8') as f: json.dump(value, f, indent=2, allow_nan=False); f.write('\n')
    return ref(path)


def main():
    target = OUT / 'observed.json'
    if target.exists(): print(json.dumps(ref(target))); return
    OUT.mkdir(parents=True, exist_ok=True)
    # The declaration and identity metadata are examined before corrected labels.
    declaration_path = ROOT / 'outputs/mlb-v18-population-diagnostics-v1/declaration.json'
    declaration = json.loads(declaration_path.read_bytes())
    declared = {r['sourceGameId']: r for r in declaration['cases']}
    assert set(declared) == set(CASES)
    for pk in CASES:
        assert all(final_oot_eligible_key_mask([pk, declared[pk]['gameId'], canonical_game_id(int(pk))]))
    assert ref(INDEX) == {'path': str(INDEX), 'sha256': INDEX_SHA, 'bytes': 19665}
    index = json.loads(INDEX.read_bytes())
    assert index['schemaVersion'] == 'AISP_MLB_POSTGAME_DIAGNOSTIC_INDEX_V2'
    assert index['totals'] == {'completedPlateAppearances': 1173, 'inningEndingBaserunningOuts': 3, 'playRecords': 1176}
    refs = {r['sourceGameId']: r for r in index['games'] if r['sourceGameId'] in CASES}
    assert set(refs) == set(CASES)
    gate = write('identity-gate.json', {'asOfUtc': datetime.now(timezone.utc).isoformat(), 'quarantine': ref(LEDGER),
        'declaration': ref(declaration_path), 'index': ref(INDEX), 'selectedGameIds': list(CASES),
        'physicalGameReferences': {pk: {'path': refs[pk]['derivedFile'], 'sha256': refs[pk]['physicalFileSha256'], 'bytes': refs[pk]['physicalBytes']} for pk in CASES},
        'correctedGamePayloadsOpened': 0, 'identityGateBeforeCorrectedPayloads': True})
    assert ref(PREDECESSOR)['sha256'] == 'dd856d31cf60c146e0f60b49d961ce83b77d3bc1d7a8ce8f6c7e8a61299a01b3'
    predecessor = json.loads(PREDECESSOR.read_bytes()); output = deepcopy(predecessor)
    by_pk = {r['sourceGameId']: r for r in output['rows']}; findings = []
    for pk in CASES:
        meta = refs[pk]; row = by_pk[pk]
        assert all(final_oot_eligible_key_mask([pk, row['gameId'], canonical_game_id(int(pk))]))
        reference = {'path': meta['derivedFile'], 'sha256': meta['physicalFileSha256'], 'bytes': meta['physicalBytes']}
        assert ref(reference['path']) == reference
        data = json.loads(Path(reference['path']).read_bytes())
        canonical = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
        assert canonical == meta['canonicalDocumentSha256']
        assert data['schemaVersion'] == 'AISP_MLB_POSTGAME_DIAGNOSTIC_V2' and data['sourceGameId'] == pk
        assert data['notAPregameObservation'] and data['notARetrospectiveForecast'] and data['evidenceClass'] == 'POSTGAME_DIAGNOSTIC'
        assert data['source'] == meta['source']
        raw = row['source']['raw']
        assert (meta['source']['rawFileReference'], meta['source']['fileSha256'], meta['source']['payloadChecksum']) == (raw['path'], raw['sha256'], raw['payloadSha256'])
        old_events = {r['atBatIndex']: r for r in row['observedPlayBoundaries']}
        records = data['playRecords']; assert len(records) == len(old_events) == row['sourcePlayRecords']
        assert len({p['atBatIndex'] for p in records}) == len(records)
        previous = {}; scores = {'AWAY': 0, 'HOME': 0}; movements = Counter(); mismatch = []
        completed = non_pa = 0; different_runner_events = []; all_exported_before_empty = True
        for p in records:
            old = old_events[p['atBatIndex']]; side = 'AWAY' if p['halfInning'] == 'top' else 'HOME'; key = (p['inning'], side)
            assert old['inning'] == p['inning'] and old['battingSide'] == side
            assert old['eventType'] == p['eventType'] and old['pitcherMLBAMId'] == str(p['pitcherId'])
            mapped = map_pa_event(p['eventType'])
            is_pa = p['recordType'] == 'COMPLETED_PLATE_APPEARANCE'
            assert p['recordType'] in ('COMPLETED_PLATE_APPEARANCE', 'INNING_ENDING_BASERUNNING_OUT')
            assert is_pa == old['completedPA'] and mapped == old['paClass']
            assert p['playIsComplete'] is True  # completeness is checked, never the PA classifier
            if is_pa: completed += 1; assert mapped is not None
            else: non_pa += 1; assert mapped is None and p['eventType'] in NON_PA_EVENTS and p['outsAfter'] == 3
            before_mask, before_outs = previous.get(key, (0, 0))
            after_mask = sum(1 << i for i, name in enumerate(('first', 'second', 'third')) if p['basesAfter'][name])
            supplied_before = sum(1 << i for i, name in enumerate(('first', 'second', 'third')) if p['basesBefore'][name])
            if supplied_before: all_exported_before_empty = False
            if supplied_before != before_mask: mismatch.append(p['atBatIndex'])
            assert before_mask == old['baseMaskBeforeDerivedFromPreviousEnd'] and before_outs == old['outsBefore']
            assert after_mask == old['baseMaskAfterSaved'] and p['outsAfter'] == old['outsAfter']
            runs = p[side.lower() + 'ScoreAfter'] - scores[side]; scores[side] += runs
            assert runs == old['runs']
            remaining = before_mask.bit_count() + int(is_pa) - (p['outsAfter'] - before_outs) - runs
            assert 0 <= remaining <= 3
            if p['outsAfter'] < 3: assert remaining == after_mask.bit_count()
            previous[key] = (after_mask, p['outsAfter'])
            for m in p['runnerMovements']:
                movements[(m.get('startBase'), m.get('endBase'), m.get('isOut'))] += 1
                if is_pa and m['event'] != p['event']:
                    different_runner_events.append({'atBatIndex': p['atBatIndex'], 'terminalEventType': p['eventType'], 'runnerMovement': m})
            # Retain every within-play movement; do not turn it into another PA.
            old.update(sourceRecordType=p['recordType'], playIsComplete=p['playIsComplete'],
                runnerMovements=p['runnerMovements'], sourcePlayActions=p.get('actions'),
                sourcePlayActionsAvailability='PRESENT' if 'actions' in p else 'NOT_EXPORTED',
                attribution='Aggregate whole-play boundaries, including runner activity within a completed PA; runs are not proved to arise only from the terminal PA class.')
        assert completed == row['completedPA'] and meta['recordCounts'] == data['recordCounts'] == {
            'completedPlateAppearances': completed, 'inningEndingBaserunningOuts': non_pa, 'playRecords': len(records)}
        assert len(data['inningEndingBaserunningOuts']) == non_pa
        assert movements == Counter({(m['startBase'], m['endBase'], m['isOut']): m['count'] for m in row['runnerMovementRecordTallies']})
        for side in ('AWAY', 'HOME'):
            team = row['perTeam'][side]
            pitcher_rows = [p for p in data['pitcherAttribution'] if p['side'].upper() == side]
            starter_rows = [p for p in pitcher_rows if p['gamesStarted'] == 1]; assert len(starter_rows) == 1
            assert starter_rows[0]['battersFaced'] == team['starter_bf'] and starter_rows[0]['outs'] == team['starter_outs']
            assert sum(p['battersFaced'] for p in pitcher_rows) == team['starter_bf'] + team['relief_bf']
            assert sum(p['outs'] for p in pitcher_rows) == team['starter_outs'] + team['relief_outs']
            assert team['starterRemoval']['sourceSubstitution'] in data['substitutions']
        for actual, old_inning in zip(data['inningScoring'], row['inningRunsAndLOB'], strict=True):
            assert actual['inning'] == old_inning['inning']
            for side in ('away', 'home'): assert actual.get(side + 'Runs') == old_inning[side]['runs']
        assert mismatch == row['baseStateValidation']['exportedBeforeMismatchAtBatIndices']
        old_source = row['source']['derived']; row['source']['derived'] = {**reference, 'canonicalDocumentSha256': canonical, 'physicalHashVerified': True}
        row['source']['predecessorDerivedHistoricallyQualified'] = old_source
        row['source']['correctedPackageIndex'] = ref(INDEX)
        row['baseStateValidation'].update(correctedV2BasesBeforeUsable=not bool(mismatch),
            correctedV2ExportedBeforeAllEmpty=all_exported_before_empty, correctedV2BeforeMismatchAtBatIndices=mismatch,
            previousEndStateDerivationStillRequired=bool(mismatch), allCorrectedEndStatesAndDerivedBoundariesMatchPredecessor=True)
        row['withinCompletedPARunnerActivity'] = {'allRunnerMovementsRetainedPerPlay': True,
            'runnerEventsDifferingFromTerminalEvent': different_runner_events,
            'perPitchActions': 'Not exported by V2; no missing action list was invented.',
            'meaning': 'Terminal recordType and existing eight-class map are unchanged by runner movement within a completed PA.'}
        row['comparability']['runOnClassAndTransitionAttribution'] = 'AGGREGATE_WHOLE_PLAY_BOUNDARY_INCLUDING_WITHIN_PA_RUNNER_ACTIVITY_NOT_TERMINAL_CLASS_ONLY_CAUSATION'
        row['comparability']['transport'] = 'V2_EXACT_PHYSICAL_HASH_VERIFIED; V1_NORMALIZATION_QUALIFICATION_RETAINED_AS_PREDECESSOR_ONLY'
        findings.append({'sourceGameId': pk, 'completedPA': completed, 'playRecords': len(records), 'inningEndingBaserunningOuts': non_pa,
            'actualNumericMetricsChanged': False, 'stateBoundaryValuesChanged': False, 'basesBeforeUsable': not bool(mismatch),
            'suppliedBeforeMismatchRecords': len(mismatch), 'withinCompletedPADifferentRunnerEventRecords': len(different_runner_events), 'physicalGameReference': reference})
    output.update(schemaVersion='MLB_V18_THREE_GAME_OBSERVED_POPULATION_DIAGNOSTICS_V2', asOfUtc=datetime.now(timezone.utc).isoformat(),
        identityGate=gate, predecessor=ref(PREDECESSOR), correctedPackageIndex=ref(INDEX), correctedPackageRecordTypes=index['recordTypes'],
        denominatorRule=index['denominatorRule'], sourceQualification='V2 index and selected game physical bytes verified exactly without normalization; predecessor retained unchanged.',
        bindingFindings=findings, observedTransformReusedWithoutNumericalChanges=True, code=ref(__file__),
        countDefinition='Full slate1176 play records=1173 completedPA+3 inning-ending baserunning outs. Fixed subset224=223+1. Published recordType is the classifier; playIsComplete alone does not identify a completed PA. Within-PA runner activity remains inside its whole-play boundary and is separately retained.')
    result = write('observed.json', output)
    print(json.dumps({'result': result, 'findings': findings}, indent=2))


if __name__ == '__main__': main()
