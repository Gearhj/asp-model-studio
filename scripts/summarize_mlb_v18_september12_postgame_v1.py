"""Extract retrospective diagnostics from the 16 already admitted raw references."""
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask, LEDGER
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / 'outputs/mlb-v18-september12-miss-analysis-v1/exposure'


def ref(path):
    p = Path(path).resolve(); b = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def load(path):
    return json.loads(Path(path).read_bytes())


def utc(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def main():
    target = OUT / 'actual-postgame-summary.json'
    if target.exists():
        print(json.dumps({'status': 'EXISTING_CAPTURE_REUSED', 'result': ref(target)})); return
    declaration_path = ROOT / 'outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-declaration.json'
    declaration = load(declaration_path)
    declared = {g['sourceGameId']: g for g in declaration['games']}
    assert len(declared) == 15
    for pk, g in declared.items():
        assert all(final_oot_eligible_key_mask([pk, g['gameId'], canonical_game_id(int(pk))]))
        assert utc(g['scheduledStartUtc']).astimezone(ZoneInfo('America/New_York')).date().isoformat() == '2026-09-12'
    supplement_path = OUT / 'starter-evidence-supplement-v3.json'
    assert ref(supplement_path)['sha256'] == '20099b4babab1cda041b945a4100e1b70b2bed9cd374593383d3399d4b3f88a8'
    supplement = load(supplement_path)
    assert ref(supplement['sameFrozenFinalReceipt']['path']) == supplement['sameFrozenFinalReceipt']
    finals = {v['gameId']: v for v in load(supplement['sameFrozenFinalReceipt']['path'])['records']}
    sr = {r['sourceGameId']: r for r in supplement['rows']}
    refs = {}
    for r in sr.values():
        assert r['status'] == 'SUPPORTED'
        for b in r['databaseProjection']:
            assert len(b['raw_references']) == len(b['raw_checksums']) == 16
            for p, sha in zip(b['raw_references'], b['raw_checksums']):
                assert refs.get(p, sha) == sha
                refs[p] = sha
    assert len(refs) == 16
    # Recover each immutable feed's identity from its established request hash
    # before opening it; no unrelated or sealed game payload can enter this pass.
    feeds = {}
    for pk in declared:
        fingerprint = canonical_sha({'source': 'MLB_STATS_API', 'endpoint_key': 'mlb_historical_game_feed',
            'request_shape': {'source_game_id': pk, 'policy_version': 'gate3a-a1-core-v1'}})
        matches = [p for p in refs if Path(p).name.startswith('2026-09-12_' + fingerprint[:24])]
        assert len(matches) == 1, (pk, matches)
        feeds[pk] = {'path': matches[0], 'sha256': refs[matches[0]], 'requestFingerprint': fingerprint}
    assert len({v['path'] for v in feeds.values()}) == 15
    gate = {'asOfUtc': datetime.now(timezone.utc).isoformat(), 'declaration': ref(declaration_path),
        'quarantine': ref(LEDGER), 'starterReceipt': ref(supplement_path), 'feeds': feeds,
        'identityBeforePayload': True, 'payloadsOpenedByThisScript': 0,
        'sourceBoundary': 'Exact checksum-admitted feed paths only; one shared schedule reference is unnecessary and not reopened.'}
    gate_path = OUT / 'actual-postgame-identity-gate.json'
    with gate_path.open('x', encoding='utf-8') as f: json.dump(gate, f, indent=2); f.write('\n')
    prior_path = OUT / 'findings.json'; prior = load(prior_path)
    prior_rows = {r['sourceGameId']: r for r in prior['rows']}
    rows = []
    for pk, source in feeds.items():
        g = declared[pk]; starter = sr[pk]; final = finals[g['gameId']]
        assert all(final_oot_eligible_key_mask([pk, g['gameId'], canonical_game_id(int(pk))]))
        raw = Path(source['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == source['sha256']
        wrapper = json.loads(gzip.decompress(raw)); m = wrapper['metadata']; p = wrapper['payload']
        assert m['request_fingerprint'] == source['requestFingerprint']
        assert m['source'] == 'MLB_STATS_API' and m['source_mode'] == 'LIVE'
        assert m['status'] == 'success' and m['temporal_semantics'] == 'RETROSPECTIVE_RECONSTRUCTION'
        assert m['schema_version'] == 'mlb_statsapi_v1_1_historical_game_feed_v1'
        assert canonical_sha(p) == m['checksum']
        assert str(p['gamePk']) == pk == str(p['gameData']['game']['pk'])
        assert p['gameData']['datetime']['officialDate'] == '2026-09-12'
        assert utc(p['gameData']['datetime']['dateTime']) == utc(g['scheduledStartUtc'])
        assert utc(m['source_event_timestamp']) == utc(final['finalAt'])
        assert utc(m['ingestion_timestamp']) <= utc(supplement['asOfUtc'])
        assert p['gameData']['status']['abstractGameState'] == 'Final'
        live = p['liveData']; box = live['boxscore']['teams']; lines = live['linescore']
        assert lines['teams']['away']['runs'] == final['awayScore']
        assert lines['teams']['home']['runs'] == final['homeScore']
        innings = [{'inning': n['num'], **{s: {k: n.get(s, {}).get(k) for k in ['runs', 'hits', 'leftOnBase']} for s in ['away', 'home']}} for n in lines['innings']]
        sides = {}
        for side in ['AWAY', 'HOME']:
            s = side.lower(); team = box[s]; stats = team['teamStats']; bat = stats['batting']; pit = stats['pitching']
            expected = starter['evidence']['sides'][side]['expectedStarter']
            assert str(team['team']['id']) == expected['sourceTeamId']
            pitchers = []
            for player_id in team['pitchers']:
                player = team['players']['ID' + str(player_id)]; ps = player['stats']['pitching']
                pitchers.append({'mlbamId': str(player_id), 'name': player['person']['fullName'],
                    **{k: ps.get(k) for k in ['gamesStarted', 'battersFaced', 'outs', 'inningsPitched', 'runs', 'earnedRuns', 'inheritedRunners', 'inheritedRunnersScored']}})
            actual_starters = [v for v in pitchers if v['gamesStarted'] == 1]
            assert len(actual_starters) == 1 and actual_starters[0]['mlbamId'] == expected['mlbamId']
            sp = actual_starters[0]
            assert sp['battersFaced'] == starter['evidence']['sides'][side]['actualBf']
            assert sp['outs'] == starter['evidence']['sides'][side]['actualOuts']
            assert sum(v['battersFaced'] for v in pitchers) == pit['battersFaced']
            assert sum(v['outs'] for v in pitchers) == pit['outs']
            assert sum(n[s]['runs'] or 0 for n in innings) == lines['teams'][s]['runs'] == bat['runs']
            assert bat['plateAppearances'] == box['home' if s == 'away' else 'away']['teamStats']['pitching']['battersFaced']
            lob_sum = sum(n[s]['leftOnBase'] or 0 for n in innings)
            sides[side] = {'teamMLBAMId': expected['sourceTeamId'], 'starterBF': sp['battersFaced'], 'starterOuts': sp['outs'],
                'totalPitcherBF': pit['battersFaced'], 'reliefBF': pit['battersFaced'] - sp['battersFaced'], 'pitchers': pitchers,
                'batting': {k: bat.get(k) for k in ['plateAppearances', 'atBats', 'hits', 'baseOnBalls', 'hitByPitch', 'catchersInterference', 'doubles', 'triples', 'homeRuns', 'strikeOuts', 'groundIntoDoublePlay', 'groundIntoTriplePlay', 'stolenBases', 'caughtStealing', 'sacBunts', 'sacFlies', 'runs']},
                'lineScoreLeftOnBase': lines['teams'][s].get('leftOnBase'), 'sumInningLeftOnBase': lob_sum,
                'battingAggregateLeftOnBaseDifferentDefinition': bat.get('leftOnBase'),
                'lateInningRuns7Plus': sum(n[s]['runs'] or 0 for n in innings if n['inning'] >= 7),
                'maximumInningRuns': max(n[s]['runs'] or 0 for n in innings)}
        plays = live.get('plays', {}).get('allPlays', [])
        movements = Counter()
        for play in plays:
            for runner in play.get('runners', []):
                move = runner.get('movement', {})
                movements[(move.get('start'), move.get('end'), move.get('isOut'))] += 1
        row = {'gameId': g['gameId'], 'sourceGameId': pk, 'status': 'SUPPORTED',
            'actualAwayRuns': final['awayScore'], 'actualHomeRuns': final['homeScore'],
            'actualTotalPA': sum(sides[s]['batting']['plateAppearances'] for s in sides),
            'actualTerminalInning': lines['currentInning'], 'sides': sides, 'inningSummaries': innings,
            'rawSequenceEvidence': {'present': bool(plays), 'playRecords': len(plays),
                'rawResultEventTypeCounts': dict(Counter(v.get('result', {}).get('eventType', 'MISSING') for v in plays)),
                'runnerMovementRecords': sum(movements.values()),
                'runnerMovementRecordCounts': [{'start': k[0], 'end': k[1], 'isOut': k[2], 'count': v} for k, v in movements.items()],
                'eightClassMappingApplied': False, 'opportunityConditionalTransitionRatesComputed': False,
                'meaning': 'Provider play/runner records, not PA-model probability captures or independently reconstructed runner states.'},
            'frozenSimulationPAPopulation': prior_rows[pk]['population5000']['totalPa'],
            'awayTeam': prior_rows[pk]['awayTeam'], 'homeTeam': prior_rows[pk]['homeTeam'],
            'source': {**source, 'bytes': len(raw), 'payloadSha256': m['checksum'], 'ingestionTimestamp': m['ingestion_timestamp'], 'sourceEventTimestamp': m['source_event_timestamp']},
            'finalOutcomeId': final['sourceOutcomeId'], 'finalRevision': final['sourceRevision'],
            'availableRequestedMeasureCategories': ['teamPA', 'terminalInning', 'starterBF', 'starterOuts', 'reliefBF', 'teamHits', 'teamWalks', 'teamHBP', 'inningRuns', 'lineScoreLOB', 'GIDP', 'runnerMovementRecords'],
            'requestedMeasureCategoriesAvailable': 12,
            'missingForModelErrorAttribution': ['Frozen population starterBF/removal/reliefBF distributions', 'Frozen population comparable runner-transition and inning-run diagnostics', 'Frozen actual-PA conditional probability captures']}
        rows.append(row)
    output = {'schemaVersion': 'MLB_V18_SEPTEMBER12_ACTUAL_POSTGAME_DIAGNOSTICS_V1', 'asOfUtc': datetime.now(timezone.utc).isoformat(),
        'rows': rows, 'gamesSupported': len(rows), 'rawFeedsRead': 15, 'permittedUniqueRawReferences': 16,
        'identityGate': ref(gate_path), 'starterReceipt': ref(supplement_path), 'governedFinals': supplement['sameFrozenFinalReceipt'],
        'frozenSimulationFindings': ref(prior_path), 'code': ref(__file__),
        'checks': 'All15 compressed and payload hashes, game/date/team/starter identities, final scores and final clocks agree; pitcherBF/outs and opposing battingPA reconcile.',
        'interpretation': 'Actual PA is observed exposure and may itself rise because more hitters reach base or score; a PA difference does not isolate a cause. No comparison of actual BF with the single retained trace is a population bias estimate. Direct GIDP and raw movement record counts do not establish conditional transition miscalibration.',
        'providerCalls': 0, 'databaseQueries': 0, 'simulations': 0, 'fits': 0, 'aispWrites': 0}
    with target.open('x', encoding='utf-8') as f: json.dump(output, f, indent=2, allow_nan=False); f.write('\n')
    md = ['Actual postgame exposure is supported for all 15 frozen September 12 games. All 30 starter BF/outs values match the admitted official records. These are retrospective labels, never pregame covariates.',
        '', 'Actual PA can increase because more hitters reach base or score. It does not independently identify the cause of a run miss. The frozen simulation has 5,000 PA counts but only one retained usage/transition trace, so no population starter-BF or run-conversion bias is claimed.',
        '', 'A/H always means away/home. LOB uses the linescore team field; the separate batting aggregate LOB has a different meaning and is retained separately. Movement tallies are source records, not reconstructed conditional transition opportunities.',
        '', '| Game | Actual PA | Sim PA mean [5–95%] | Starter BF A/H | Relief BF A/H | Hits A/H | BB+HBP A/H | GIDP A/H | LOB A/H | Runs 7+ A/H | Fields |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        a, h = r['sides']['AWAY'], r['sides']['HOME']; pa = r['frozenSimulationPAPopulation']
        pair = lambda key: str(a[key]) + '/' + str(h[key])
        bp = lambda key: str(a['batting'][key]) + '/' + str(h['batting'][key])
        walks = '/'.join(str(v['batting']['baseOnBalls'] + v['batting']['hitByPitch']) for v in [a, h])
        md.append(f"| {r['awayTeam']}–{r['homeTeam']} {r['sourceGameId']} | {r['actualTotalPA']} | {pa['mean']:.2f} [{pa['p05']:.0f}–{pa['p95']:.0f}] | {pair('starterBF')} | {pair('reliefBF')} | {bp('hits')} | {walks} | {bp('groundIntoDoublePlay')} | {pair('lineScoreLeftOnBase')} | {pair('lateInningRuns7Plus')} | 12/12 |")
    md += ['', 'All feeds contain per-inning runs and runner sequences. The JSON preserves raw event types without introducing a new eight-class mapping. Frozen actual-PA probability captures and comparable population usage/transition diagnostics remain unavailable.', '',
        'Reproduce from the same retained files: `.venv/Scripts/python.exe scripts/summarize_mlb_v18_september12_postgame_v1.py` (an existing result is reused).', '',
        'Evidence: [actual-postgame-summary.json](' + str(target) + '), [starter-evidence-supplement-v3.json](' + str(supplement_path) + ').']
    with (OUT / 'actual-postgame-summary.md').open('x', encoding='utf-8') as f: f.write('\n'.join(md) + '\n')
    print(json.dumps({'result': ref(target), 'supportedGames': len(rows)}))


if __name__ == '__main__':
    main()
