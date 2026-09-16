"""Definition-only reconciliation of the supplied diagnostic export and saved raw summary."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask, LEDGER

OUT = ROOT / 'outputs/mlb-v18-september12-miss-analysis-v1/exposure'
HANDOFF = Path('C:/Users/james/asp-model-exchange/aisp-final-evidence/mlb-decision-economics-v1/sha256/f04d7e7b6ed70e5713b1343ed83e6b21bb0b135120ec009214317aad190224d5/decision-economics-handoff.json')


def ref(path):
    b = Path(path).read_bytes()
    return {'path': str(Path(path).resolve()), 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}


def normalized_load(path, expected):
    b = Path(path).read_bytes()
    normalized = hashlib.sha256(b.replace(b'\r\n', b'\n')).hexdigest()
    assert normalized == expected
    return json.loads(b), {**ref(path), 'declaredNormalizedLfSha256': expected,
        'physicalBytesMatchDeclared': hashlib.sha256(b).hexdigest() == expected,
        'normalizedLfBytesMatchDeclared': True}


def main():
    target = OUT / 'postgame-export-reconciliation.json'
    if target.exists(): print(json.dumps(ref(target))); return
    raw_path = OUT / 'actual-postgame-summary.json'
    raw = json.loads(raw_path.read_bytes()); rr = {v['sourceGameId']: v for v in raw['rows']}
    for r in rr.values(): assert all(final_oot_eligible_key_mask([r['gameId'], r['sourceGameId']]))
    handoff = json.loads(HANDOFF.read_bytes())
    canonical_handoff_sha = hashlib.sha256(json.dumps(handoff, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert canonical_handoff_sha == 'f04d7e7b6ed70e5713b1343ed83e6b21bb0b135120ec009214317aad190224d5'
    href = {**ref(HANDOFF), 'directoryCanonicalJsonSha256': canonical_handoff_sha,
        'physicalBytesMatchDirectoryDigest': False, 'canonicalJsonMatchesDirectoryDigest': True}
    games = handoff['postgameEvidence']['games']; assert {v['sourceGameId'] for v in games} == set(rr)
    rows = []; non_pa = {'pickoff_caught_stealing_2b', 'caught_stealing_2b'}
    for meta in games:
        pk = meta['sourceGameId']; r = rr[pk]
        assert all(final_oot_eligible_key_mask([r['gameId'], pk]))
        assert meta['source']['fileSha256'] == r['source']['sha256']
        assert meta['source']['payloadChecksum'] == r['source']['payloadSha256']
        derived, dref = normalized_load(meta['derivedFile'], meta['derivedSha256'])
        assert derived['sourceGameId'] == pk and derived['source'] == meta['source']
        assert derived['evidenceClass'] == 'POSTGAME_DIAGNOSTIC'
        assert derived['notAPregameObservation'] and derived['notARetrospectiveForecast']
        records = derived['orderedPlateAppearances']
        counts = Counter(v['eventType'] for v in records)
        assert dict(counts) == r['rawSequenceEvidence']['rawResultEventTypeCounts']
        assert len(records) == r['rawSequenceEvidence']['playRecords'] == meta['orderedPlateAppearances']['count']
        movement = Counter((m.get('startBase'), m.get('endBase'), m.get('isOut')) for v in records for m in v['runnerMovements'])
        expected_movement = Counter({(m['start'], m['end'], m['isOut']): m['count'] for m in r['rawSequenceEvidence']['runnerMovementRecordCounts']})
        assert movement == expected_movement
        assert len(derived['inningScoring']) == len(r['inningSummaries'])
        for new, old in zip(derived['inningScoring'], r['inningSummaries']):
            assert new['inning'] == old['inning']
            for side in ['away', 'home']: assert new.get(side + 'Runs') == old[side]['runs']
        pitchers = {(v['side'].upper(), str(v['playerId'])): v for v in derived['pitcherAttribution']}
        for side, s in r['sides'].items():
            for p in s['pitchers']:
                v = pitchers[(side, p['mlbamId'])]
                assert (v['battersFaced'], v['outs'], v['gamesStarted']) == (p['battersFaced'], p['outs'], p['gamesStarted'])
        excluded = [v for v in records if v['eventType'] in non_pa]
        assert len(records) - len(excluded) == r['actualTotalPA']
        for v in excluded:
            assert v['outsAfter'] == 3 and all(str(m['runnerId']) != str(v['batterId']) for m in v['runnerMovements'])
        rows.append({'sourceGameId': pk, 'gameId': r['gameId'], 'actualCompletedPA': r['actualTotalPA'],
            'exportOrderedPlateAppearancesRecords': len(records), 'nonPAEndingInningRecords': len(excluded),
            'differenceReason': 'Third-out baserunning event ends inning without completing the batter PA' if excluded else 'Counts agree',
            'nonPAEndingRecords': [{k: v[k] for k in ['atBatIndex', 'inning', 'halfInning', 'eventType', 'isComplete', 'outsAfter', 'batterId', 'runnerMovements']} for v in excluded],
            'derived': dref, 'sameAdmittedRawSource': r['source'],
            'matches': {'rawEventTypeCounts': True, 'runnerMovementTallies': True, 'inningRuns': True, 'pitcherBFOutsAndStarterFlags': True},
            'newDerivedBaseOccupancyNotIndependentlyValidated': True,
            'rawSubstitutionRecordsAvailable': len(derived['substitutions'])})
    total_actual = sum(v['actualCompletedPA'] for v in rows); total_records = sum(v['exportOrderedPlateAppearancesRecords'] for v in rows)
    assert (total_actual, total_records) == (1173, 1176)
    result = {'schemaVersion': 'MLB_V18_POSTGAME_EXPORT_DEFINITION_RECONCILIATION_V1',
        'asOfUtc': datetime.now(timezone.utc).isoformat(), 'quarantine': ref(LEDGER), 'handoff': href,
        'rawSummary': ref(raw_path), 'rows': rows, 'actualCompletedPA': total_actual, 'sourcePlayRecords': total_records,
        'all15MatchedSameRawSourceAndAggregates': True,
        'transportQualification': 'The handoff directory digest matches sorted compact canonical JSON, not physical bytes. Derived file declared hashes match CRLF-to-LF normalized bytes. Physical byte hashes are retained separately. No physical byte identity claim or immutable-path rewrite.',
        'definition': 'The export orderedPlateAppearances / complete fields include all complete provider plays. isComplete does not establish a completed batter PA; three third-out baserunning plays are present. Official team batting PA equals opposing pitching BF at 1173.',
        'observations': {'actualPA': total_actual, 'sumFrozenPAMeans': sum(r['frozenSimulationPAPopulation']['mean'] for r in rr.values()),
            'aboveGameP95': [r['sourceGameId'] for r in rr.values() if r['actualTotalPA'] > r['frozenSimulationPAPopulation']['p95']],
            'belowGameP05': [r['sourceGameId'] for r in rr.values() if r['actualTotalPA'] < r['frozenSimulationPAPopulation']['p05']],
            'interpretation': 'Only COL-DET and SEA-ATH exceed their game PA p95, each 91 vs89. NYM-NYY scores14 total with76 PA near its75.73 mean, so extra PA alone cannot explain every run miss. SEA has home starterBF12/reliefBF43 and10 away runs in innings7+, a localized usage/sequencing question; no frozen BF population exists to diagnose duration bias. High PA may itself result from hits/walks/scoring, and none of these post-scan observations establishes a correction.'},
        'code': ref(__file__), 'providerCalls': 0, 'databaseQueries': 0, 'rawFeedRereads': 0, 'fits': 0, 'simulations': 0}
    with target.open('x', encoding='utf-8') as f: json.dump(result, f, indent=2); f.write('\n')
    md = ['The export contains 1,176 complete play records; official batting PA and opposing pitcher BF both sum to 1,173. The three extra records end an inning through a baserunning out, without completing the batter PA.', '',
        '| Game | Export play records | Official PA | Extra event |', '|---|---:|---:|---|']
    for r in rows:
        if r['nonPAEndingRecords']: md.append(f"| {r['sourceGameId']} | {r['exportOrderedPlateAppearancesRecords']} | {r['actualCompletedPA']} | {r['nonPAEndingRecords'][0]['eventType']} |")
    md += ['', 'All 15 exports use the same retained raw hashes as the official summary. Event-type counts, runner movement tallies, inning runs and all pitcher BF/outs/starter flags reconcile. The other 12 game counts agree.', '',
        result['transportQualification'], '', result['observations']['interpretation'], '',
        'Reproduce: `.venv/Scripts/python.exe scripts/reconcile_mlb_v18_september12_postgame_export_v1.py`.']
    with (OUT / 'postgame-export-reconciliation.md').open('x', encoding='utf-8') as f: f.write('\n'.join(md) + '\n')
    print(json.dumps({'result': ref(target), 'rows': len(rows), 'actualCompletedPA': total_actual, 'sourcePlayRecords': total_records}))


if __name__ == '__main__': main()
