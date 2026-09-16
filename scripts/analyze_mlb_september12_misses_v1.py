"""Focused successor diagnosis of the original 15 frozen September 12 forecasts.

No inference, simulation, fitting, provider acquisition or position mutation.
The original declaration and captured finals are reused on every offline replay.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from scripts import assess_mlb_v18_frozen_slate_20260912_v1 as prior
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import (
    read_persisted_finals, _marginal, joint_energy_score,
)

OUT = ROOT / 'outputs/mlb-v18-september12-miss-analysis-v1'
PREVIOUS = ROOT / 'outputs/mlb-v18-position-and-survival-verification-v1'
DECLARATION_SHA = '7af5ee29f9f09631e02e25c1606e6b11692a745d78e7ee7fee10b1e8e67ec88a'


def ref(path):
    p = Path(path).resolve(); b = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}


def read_ref(item):
    assert ref(item['path']) == {k: item[k] for k in ('path', 'sha256', 'bytes')}
    return json.loads(Path(item['path']).read_bytes())


def save(name, value):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    raw = (json.dumps(value, indent=2, allow_nan=False, default=str) + '\n').encode()
    if path.exists():
        assert path.read_bytes() == raw, 'PRESERVE_SAVED_SUCCESSOR_EVIDENCE'
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return ref(path)


def prepare():
    descriptor = ref(PREVIOUS / 'slate-assessment-declaration.json')
    assert descriptor['sha256'] == DECLARATION_SHA
    declaration = read_ref(descriptor)
    assert len(declaration['games']) == 15
    aliases = [prior.guard(row) for row in declaration['games']]
    path = OUT / 'analysis-declaration.json'
    if not path.exists():
        save(path.name, {
            'schemaVersion': 'MLB_SEPTEMBER12_FOCUSED_MISS_DECLARATION_V1',
            'recordedAtUtc': datetime.now(timezone.utc).isoformat(),
            'branch': subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip(),
            'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'workOrder': ref(Path(r'C:\Users\james\.codex\attachments\8ef2b9ba-ef48-4a1f-bd0a-66ab42f195b7\pasted-text.txt')),
            'frozenSlateDeclaration': descriptor, 'quarantine': ref(prior.LEDGER),
            'quarantineAliasesCheckedBeforeNewOutcomeAccess': aliases,
            'cohortRule': 'All original 15 September12 forecasts; funded subset identified separately. No worst-case selection or new matchup rule.',
            'outcomeRule': 'One capture of latest eligible governed finals, retaining unavailable cases and prior revision lineage.',
            'metrics': ['original winner log loss/Brier', 'original marginal CRPS and joint energy',
                        'original discrete central interval coverage', 'signed/absolute mean errors',
                        'inclusive lower/upper outcome tail mass', 'finite-draw standard errors'],
            'scoreReuse': 'Reuse previously verified scores when actual away/home runs are identical; rescore only new or changed finals.',
            'intervalRule': 'Reuse established scorer levels and inverse-CDF convention; display central95% coverage with all levels retained.',
            'tailRule': 'Report empirical P(X<=actual) and P(X>=actual), inclusive for integer outcomes; no selected significance threshold.',
            'mcRule': 'Standard errors describe finite simulated-draw precision conditional on the fixed simulator, not uncertainty about its accuracy.',
            'comparators': 'Preserve previous unmatched-horizon comparisons as descriptive only; no refreshed or newly validated comparator is selected.',
            'limits': {'modelFits': 0, 'newHistoricalSimulations': 0, 'providerRequests': 0, 'aispWrites': 0},
        })
    return declaration


def capture():
    declaration = prepare()
    # The current nine-game identity quarantine is reapplied immediately before
    # opening new outcome evidence, even though the cohort was already frozen.
    [prior.guard(row) for row in declaration['games']]
    path = OUT / 'governed-finals.json'
    if path.exists():
        return ref(path)
    from dotenv import dotenv_values
    url = dotenv_values(Path(r'C:\Users\james\ai-sports-predictor\.env'))['DATABASE_URL']
    url = url.replace('postgresql+psycopg://', 'postgresql+psycopg2://')
    pairs = [{'gameId': r['gameId'], 'commonPairId': r['forecastId'],
              'scheduledStartUtc': r['scheduledStartUtc']} for r in declaration['games']]
    return save(path.name, read_persisted_finals(pairs, database_url=url))


def score():
    declaration = prepare()
    finals_ref = capture(); finals = read_ref(finals_ref)
    old_ref = ref(PREVIOUS / 'slate-assessment.json'); old = read_ref(old_ref)
    old_rows = {r['gameId']: r for r in old['rows']}
    final_rows = {r['gameId']: r for r in finals['records']}
    audit_ref = ref(PREVIOUS / 'positions/position-audit.json')
    selected = {r['gameId']: r for r in read_ref(audit_ref)['positions']}
    rows = []; reused = fresh = 0
    for frozen in declaration['games']:
        gid = frozen['gameId']; final = final_rows.get(gid, {})
        position = selected.get(gid)
        row = {'gameId': gid, 'sourceGameId': frozen['sourceGameId'],
               'game': frozen['teams']['AWAY']['abbreviation'] + ' at ' + frozen['teams']['HOME']['abbreviation'],
               'forecastId': frozen['forecastId'], 'forecast': frozen['forecast'],
               'retainedDraws': frozen['executionInputsAndPairedDraws'],
               'expected': frozen['expectations'], 'probabilities': frozen['probabilities'],
               'final': final, 'previousFinal': old_rows[gid]['final'],
               'status': 'AWAITING_ELIGIBLE_FINAL',
               'fundedPosition': {k: position[k] for k in ['positionId', 'selectedTeam', 'selectedSide']} if position else None,
               'selectedSideProbability': frozen['probabilities']['homeWin' if position['selectedSide']=='HOME' else 'awayWin'] if position else None,
               'inputDiagnostics': {'sourceCutoff': frozen['sourceCutoff'],
                                    'forecastHorizonHours': frozen['forecastHorizonHours'],
                                    'lineupAuthorities': frozen['lineupAuthorities'],
                                    'starters': frozen['starters'],
                                    'identityAuditReused': True,
                                    'fullInvalidationHistoryVerified': False},
               'paDiagnostic': 'PENDING_RETAINED_EVIDENCE_REVIEW',
               'exposureDiagnostic': 'PENDING_RETAINED_EVIDENCE_REVIEW'}
        if final.get('status') == 'FINAL':
            home, away = int(final['homeScore']), int(final['awayScore'])
            assert home != away and min(home, away) >= 0
            previous = old_rows[gid]
            unchanged = ('scores' in previous and previous['final']['homeScore'] == home
                         and previous['final']['awayScore'] == away)
            bundle = prior.load_baseline(frozen['objectSha256'])
            h = np.asarray(bundle['baseline']['homeRuns']); a = np.asarray(bundle['baseline']['awayRuns'])
            if unchanged:
                scores = previous['scores']; reused += 1
                row['scoreComputation'] = 'REUSED_VERIFIED_IDENTICAL_OUTCOME_SCORES'
                row['scoreSource'] = old_ref
            else:
                scores = prior.winner(frozen['probabilities']['homeWin'], home, away)
                scores['marginals'] = {k: _marginal(v, y) for k, v, y in [
                    ('homeRuns', h, home), ('awayRuns', a, away), ('totalRuns', h+a, home+away), ('homeMargin', h-a, home-away)]}
                scores['jointEuclideanEnergyScore'] = joint_energy_score(h, a, (home, away))
                fresh += 1; row['scoreComputation'] = 'NEW_OR_CHANGED_FINAL_USING_EXISTING_SCORERS'
            row.update(status='SCORED_GOVERNED_FINAL', scores=scores,
                       actual={'awayRuns': away, 'homeRuns': home, 'totalRuns': home+away, 'homeMinusAwayRuns': home-away})
            row['distributionDiagnostics'] = {}
            for k, values, actual in [('awayRuns', a, away), ('homeRuns', h, home), ('totalRuns', h+a, home+away), ('homeMargin', h-a, home-away)]:
                row['distributionDiagnostics'][k] = {
                    'sampleStandardDeviation': float(np.std(values, ddof=1)),
                    'meanMonteCarloStandardError': float(np.std(values, ddof=1)/np.sqrt(len(values))),
                    'inclusiveLowerTailMass': float(np.mean(values <= actual)),
                    'inclusiveUpperTailMass': float(np.mean(values >= actual)),
                    'minimumRetainedDraw': int(np.min(values)), 'maximumRetainedDraw': int(np.max(values)),
                    'centralPredictionIntervals': scores['marginals'][k]['centralPredictionIntervals'],
                }
            p = frozen['probabilities']['homeWin']
            row['winProbabilityMonteCarloStandardError'] = float(np.sqrt(p*(1-p)/len(h)))
        rows.append(row)
    result = {'schemaVersion': 'MLB_SEPTEMBER12_FOCUSED_GAME_SCORES_V1',
              'asOfUtc': finals['source']['queryStartedAt'], 'analysisDeclaration': ref(OUT/'analysis-declaration.json'),
              'governedFinals': finals_ref, 'previousScores': old_ref, 'positionAudit': audit_ref,
              'rows': rows, 'scoreCounts': {'reusedUnchangedFinals': reused, 'newOrChangedFinals': fresh,
                                          'pending': sum(r['status']=='AWAITING_ELIGIBLE_FINAL' for r in rows)},
              'allEligibleFinalized': prior.aggregate([r['scores'] for r in rows if 'scores' in r]),
              'fundedFinalized': prior.aggregate([r['scores'] for r in rows if 'scores' in r and r['fundedPosition']]),
              'newModelFits': 0, 'newHistoricalSimulations': 0, 'providerRequests': 0, 'aispWrites': 0,
              'code': ref(__file__), 'scorer': ref(ROOT/'server/sports_current_statcast/mlb_starter_duration_paired_scoring.py')}
    return save('game-scores.json', result)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture-only', action='store_true')
    args = parser.parse_args()
    print(json.dumps(capture() if args.capture_only else score(), indent=2))
