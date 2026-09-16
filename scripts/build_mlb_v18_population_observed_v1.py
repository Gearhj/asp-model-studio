"""Three fixed observed games; retained labels only, no inference or acquisition."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_silver.current_statcast_pa import EVENT_TO_OUTCOME, map_pa_event
from server.sports_current_statcast.mlb_starter_duration_history import NON_PA_EVENTS
from server.sports_current_statcast.mlb_starter_duration_quarantine import LEDGER, final_oot_eligible_key_mask
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / 'outputs/mlb-v18-population-diagnostics-v1/observed'
OLD = ROOT / 'outputs/mlb-v18-september12-miss-analysis-v1/exposure'
SELECTED = ('823496', '824870', '824630')
SIDES = ('AWAY', 'HOME')


def ref(path):
    p = Path(path).resolve(); b = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}


def write(path, value):
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, indent=2, allow_nan=False); f.write('\n')
    return ref(path)


def empty():
    return {'completed_pa': 0, 'outcome_counts': dict.fromkeys(PA_CLASS_ORDER, 0), 'runs': 0,
        'outs_recorded': 0, 'non_pa_records': 0, 'non_pa_outs': 0, 'non_pa_runs': 0,
        'transitionCounts': dict.fromkeys(['BASES_EMPTY_BEFORE', 'RUNNERS_ON_BEFORE', 'RISP_BEFORE',
            'NO_OUT_PA', 'ONE_OUT_PA', 'MULTIOUT_PA_PROXY', 'RUN_SCORING_PA', 'BASE_OCCUPANCY_INCREASE',
            'BASE_OCCUPANCY_DECREASE', 'BASE_OCCUPANCY_UNCHANGED', 'THIRD_OUT_PA', 'RISP_NO_RUN_PA'], 0),
        'thirdOutConservationLOB': 0, 'nonPAEndingInningLOB': 0,
        'starter_bf': 0, 'relief_bf': 0, 'starter_outs': 0, 'relief_outs': 0}


def main():
    OUT.mkdir(parents=True, exist_ok=True); target = OUT / 'observed.json'
    if target.exists(): print(json.dumps({'status': 'EXISTING_RESULT_REUSED', 'result': ref(target)})); return
    declaration_path = ROOT / 'outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-declaration.json'
    declaration = json.loads(declaration_path.read_bytes())
    declared = {r['sourceGameId']: r for r in declaration['games'] if r['sourceGameId'] in SELECTED}
    assert set(declared) == set(SELECTED)
    for pk, g in declared.items():
        assert all(final_oot_eligible_key_mask([pk, g['gameId'], canonical_game_id(int(pk))]))
    source_summary = OLD / 'actual-postgame-summary.json'
    source_reconciliation = OLD / 'postgame-export-reconciliation.json'
    assert ref(source_summary)['sha256'] == 'cf267a40adc406fbd8b2c5de3b72333d5bd81a20c683746d230d67968db091d6'
    assert ref(source_reconciliation)['sha256'] == 'c4cc097e53abee37d85fe60a1dd74976734c136663530a8de5f0778439f3a062'
    summary = json.loads(source_summary.read_bytes())
    raw = {r['sourceGameId']: r for r in summary['rows'] if r['sourceGameId'] in SELECTED}
    reconciliation = json.loads(source_reconciliation.read_bytes())
    export_refs = {r['sourceGameId']: r['derived'] for r in reconciliation['rows'] if r['sourceGameId'] in SELECTED}
    gate = write(OUT / 'identity-gate.json', {'atUtc': datetime.now(timezone.utc).isoformat(), 'quarantine': ref(LEDGER),
        'declaration': ref(declaration_path), 'selected': [{'sourceGameId': pk, 'gameId': declared[pk]['gameId'], 'derived': export_refs[pk]} for pk in SELECTED],
        'newGamePayloadsRead': False, 'basis': 'Fixed three-game subset; quarantine checked before loading retained label records.'})
    games = []
    for pk in SELECTED:
        g = declared[pk]; s = raw[pk]; dref = export_refs[pk]
        assert all(final_oot_eligible_key_mask([pk, g['gameId'], canonical_game_id(int(pk))]))
        b = Path(dref['path']).read_bytes()
        assert hashlib.sha256(b).hexdigest() == dref['sha256']
        assert hashlib.sha256(b.replace(b'\r\n', b'\n')).hexdigest() == dref['declaredNormalizedLfSha256']
        d = json.loads(b); assert d['sourceGameId'] == pk and d['evidenceClass'] == 'POSTGAME_DIAGNOSTIC'
        assert d['source']['fileSha256'] == s['source']['sha256'] and d['source']['payloadChecksum'] == s['source']['payloadSha256']
        starter = {side: next(p['mlbamId'] for p in s['sides'][side]['pitchers'] if p['gamesStarted'] == 1) for side in SIDES}
        counts = defaultdict(empty); outs_last = {}; masks_last = {}; scores = {'AWAY': 0, 'HOME': 0}
        events = []; unsupported = []; before_mismatches = []; conservation_failures = []
        observed_roles = {}; runner_records = Counter()
        for p in d['orderedPlateAppearances']:
            inning = int(p['inning']); batting = 'AWAY' if p['halfInning'] == 'top' else 'HOME'; pitching = 'HOME' if batting == 'AWAY' else 'AWAY'
            key = (batting, inning); a = counts[key]; pa_class = map_pa_event(p['eventType'])
            completed = pa_class is not None
            if not completed and p['eventType'] not in NON_PA_EVENTS:
                unsupported.append({'atBatIndex': p['atBatIndex'], 'eventType': p['eventType']}); continue
            assert p['isComplete'] is True
            outs_before = outs_last.get(key, 0); outs_after = int(p['outsAfter']); delta = outs_after - outs_before
            assert 0 <= outs_before <= outs_after <= 3
            before = masks_last.get(key, 0)
            after = sum((1 << i) for i, n in enumerate(['first', 'second', 'third']) if p['basesAfter'][n])
            supplied_before = sum((1 << i) for i, n in enumerate(['first', 'second', 'third']) if p['basesBefore'][n])
            if supplied_before != before: before_mismatches.append(p['atBatIndex'])
            runs = int(p[batting.lower() + 'ScoreAfter']) - scores[batting]; assert runs >= 0
            scores[batting] += runs; outs_last[key] = outs_after; masks_last[key] = after
            on_before = before.bit_count(); on_after = after.bit_count()
            remaining = on_before + int(completed) - delta - runs
            if outs_after < 3 and remaining != on_after:
                conservation_failures.append({'atBatIndex': p['atBatIndex'], 'expectedAfter': remaining, 'savedAfter': on_after})
            if outs_after >= 3: assert 0 <= remaining <= 3
            role = 'STARTER' if str(p['pitcherId']) == starter[pitching] else 'RELIEF'
            observed_roles[p['atBatIndex']] = role
            if completed:
                a['completed_pa'] += 1; a['outcome_counts'][pa_class] += 1; a['outs_recorded'] += delta; a['runs'] += runs
                pc = counts[(pitching, inning)]
                pc['starter_bf' if role == 'STARTER' else 'relief_bf'] += 1
                pc['starter_outs' if role == 'STARTER' else 'relief_outs'] += delta
                t = a['transitionCounts']
                t['BASES_EMPTY_BEFORE' if before == 0 else 'RUNNERS_ON_BEFORE'] += 1
                if before & 6: t['RISP_BEFORE'] += 1
                t['NO_OUT_PA' if delta == 0 else 'ONE_OUT_PA' if delta == 1 else 'MULTIOUT_PA_PROXY'] += 1
                if runs: t['RUN_SCORING_PA'] += 1
                if before & 6 and not runs: t['RISP_NO_RUN_PA'] += 1
                if outs_after >= 3:
                    t['THIRD_OUT_PA'] += 1; a['thirdOutConservationLOB'] += remaining
                else:
                    t['BASE_OCCUPANCY_INCREASE' if on_after > on_before else 'BASE_OCCUPANCY_DECREASE' if on_after < on_before else 'BASE_OCCUPANCY_UNCHANGED'] += 1
            else:
                a['non_pa_records'] += 1; a['non_pa_outs'] += delta; a['non_pa_runs'] += runs
                counts[(pitching, inning)]['starter_outs' if role == 'STARTER' else 'relief_outs'] += delta
                if outs_after >= 3: a['nonPAEndingInningLOB'] += remaining
            for movement in p['runnerMovements']:
                runner_records[(movement.get('startBase'), movement.get('endBase'), movement.get('isOut'))] += 1
            events.append({'atBatIndex': p['atBatIndex'], 'inning': inning, 'battingSide': batting, 'pitchingSide': pitching,
                'eventType': p['eventType'], 'completedPA': completed, 'paClass': pa_class,
                'pitcherMLBAMId': str(p['pitcherId']), 'pitcherRole': role, 'outsBefore': outs_before, 'outsAfter': outs_after,
                'baseMaskBeforeDerivedFromPreviousEnd': before, 'baseMaskAfterSaved': after, 'runs': runs})
        assert not unsupported and not conservation_failures
        per_team = {}
        for side in SIDES:
            team = empty()
            for (k, _), row in counts.items():
                if k != side: continue
                for metric, value in row.items():
                    if isinstance(value, dict):
                        for name, n in value.items(): team[metric][name] += n
                    else: team[metric] += value
            official = s['sides'][side]
            assert team['completed_pa'] == official['batting']['plateAppearances']
            assert team['starter_bf'] == official['starterBF'] and team['relief_bf'] == official['reliefBF']
            assert team['starter_outs'] == official['starterOuts']
            assert team['thirdOutConservationLOB'] + team['nonPAEndingInningLOB'] == official['lineScoreLeftOnBase']
            assert team['runs'] + team['non_pa_runs'] == official['batting']['runs']
            assert sum(team['outcome_counts'].values()) == team['completed_pa']
            # No new event crosswalk: direct boxscore counts reconcile the mapped classes.
            bat = official['batting']
            assert team['outcome_counts']['HOME_RUN'] == bat['homeRuns']
            assert team['outcome_counts']['DOUBLE'] == bat['doubles'] and team['outcome_counts']['TRIPLE'] == bat['triples']
            assert team['outcome_counts']['SINGLE'] == bat['hits'] - bat['doubles'] - bat['triples'] - bat['homeRuns']
            assert team['outcome_counts']['WALK_HBP_CI'] == bat['baseOnBalls'] + bat['hitByPitch'] + bat['catchersInterference']
            changes = [v for v in d['substitutions'] if v['eventType'] == 'pitching_substitution' and
                ('HOME' if v['halfInning'] == 'top' else 'AWAY') == side]
            first_relief = next((e for e in events if e['pitchingSide'] == side and e['pitcherRole'] == 'RELIEF'), None)
            assert first_relief and changes and changes[0]['atBatIndex'] == first_relief['atBatIndex']
            assert str(changes[0]['playerId']) == first_relief['pitcherMLBAMId']
            per_team[side] = {**team, 'starterMLBAMId': starter[side], 'officialPitcherOuts': sum(v['outs'] for v in official['pitchers']),
                'starterRemoval': {'status': 'EXPLICIT_FIRST_RELIEF_SUBSTITUTION', 'inning': changes[0]['inning'],
                    'atBatIndex': changes[0]['atBatIndex'], 'replacementMLBAMId': str(changes[0]['playerId']),
                    'sourceSubstitution': changes[0], 'starterBFAfterLastAppearance': official['starterBF'],
                    'comparison': 'Entry inning comparable to simulated pre-PA role switch; exact manager decision time is not inferred.'},
                'officialGIDP': bat['groundIntoDoublePlay'], 'officialLineScoreLOB': official['lineScoreLeftOnBase'],
                'battingAggregateLOBDifferentDefinition': official['battingAggregateLeftOnBaseDifferentDefinition'],
                'lateRuns7Plus': official['lateInningRuns7Plus'], 'maximumInningRuns': official['maximumInningRuns']}
        assert sum(v['completed_pa'] for v in per_team.values()) == s['actualTotalPA']
        games.append({'sourceGameId': pk, 'gameId': g['gameId'], 'awayTeam': s['awayTeam'], 'homeTeam': s['homeTeam'],
            'source': {'derived': dref, 'raw': s['source'], 'governedFinalOutcomeId': s['finalOutcomeId'], 'governedFinalRevision': s['finalRevision']},
            'completedPA': s['actualTotalPA'], 'sourcePlayRecords': len(events), 'perTeam': per_team,
            'perTeamInning': [{'teamSide': side, 'inning': inning, **counts[(side, inning)]} for side, inning in sorted(counts)],
            'inningRunsAndLOB': s['inningSummaries'], 'observedPlayBoundaries': events,
            'runnerMovementRecordTallies': [{'startBase': k[0], 'endBase': k[1], 'isOut': k[2], 'count': v} for k, v in runner_records.items()],
            'baseStateValidation': {'exportedBasesBeforeAccepted': False, 'exportedBeforeMismatchAtBatIndices': before_mismatches,
                'replacement': 'Previous saved basesAfter within the same half inning; initial empty state. These three games are regulation and need no extra-inning runner initialization.',
                'nonThirdOutConservationFailures': conservation_failures, 'officialLOBReconcilesBothTeams': True},
            'unknownCompletedEventTypes': unsupported,
            'comparability': {'PAClassCounts': 'SAME_EXISTING_EIGHT_CLASS_MAPPING', 'teamInningPAAndRuns': 'DIRECT_LABELS_SAME_AGGREGATION',
                'starterAndReliefBF': 'ACTUAL_NAMED_PITCHERS_COLLAPSED_TO_STARTER_VS_RELIEF', 'multioutPA': 'SAME_NET_OUTS_ADDED_AT_LEAST_TWO_NOT_GIDP_DEFINITION',
                'baseDependentCounts': 'OBSERVED_BOUNDARY_DERIVED_AND_CONSERVATION_VALIDATED',
                'LOB': 'THIRD_OUT_CONSERVATION_MATCHES_OFFICIAL_HERE; WALKOFF/INCOMPLETE_INNING_NOT_ESTIMATED',
                'runnerMovementTallies': 'SOURCE_RECORDS_ONLY_NOT_SAME_AS_ANONYMOUS_SIMULATED_RUNNER_TEMPLATES',
                'PAProbabilities': 'UNAVAILABLE_NO_ACTUAL_PA_PREDICTIONS', 'nonPAEvents': 'OBSERVED_SEPARATE; SIMULATOR_HAS_NO_STANDALONE_NONPA_EVENT_STEP'}})
    output = {'schemaVersion': 'MLB_V18_THREE_GAME_OBSERVED_POPULATION_DIAGNOSTICS_V1', 'asOfUtc': datetime.now(timezone.utc).isoformat(),
        'fixedSourceGameIds': list(SELECTED), 'teamOrder': list(SIDES), 'PA_CLASS_ORDER': list(PA_CLASS_ORDER), 'rows': games,
        'identityGate': gate, 'sourceSummary': ref(source_summary), 'sourceReconciliation': ref(source_reconciliation),
        'mapping': {'function': 'server.sports_silver.current_statcast_pa.map_pa_event', 'eventToOutcome': dict(EVENT_TO_OUTCOME),
            'nonPATypes': sorted(NON_PA_EVENTS), 'source': ref(ROOT / 'server/sports_silver/current_statcast_pa.py')},
        'simulatorDefinitions': {'source': ref(ROOT / 'server/sports_current_statcast/mlb_v18_whole_game_challenger.py'),
            'samplerSource': ref(ROOT / 'server/sports_phase5/whole_game_monte_carlo.py'),
            'transitionSource': ref(ROOT / 'server/sports_phase5/base_out_transition.py'),
            'eventMeaning': 'One sampled completed PA; outs/base/runs are aggregate accepted transition; independent non-PA events absent.'},
        'countDefinition': 'Previous full slate contains1176 provider play records but1173 completedPA. Three baserunning outs are excluded by existing NON_PA_EVENTS. This fixed subset has223 completedPA and224 play records; no new PA rows or predictions.',
        'code': ref(__file__), 'gitHead': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'providerCalls': 0, 'databaseQueries': 0, 'rawFeedReads': 0, 'modelFits': 0, 'modelRuns': 0}
    assert sum(r['completedPA'] for r in games) == 223 and sum(r['sourcePlayRecords'] for r in games) == 224
    result = write(target, output)
    print(json.dumps({'result': result, 'supportedGames': len(games), 'completedPA': 223, 'sourcePlayRecords': 224}))


if __name__ == '__main__': main()
