"""One additive revision-1 assessment of already published September 13 pairs.

Reads retained governed finals and original distributions. No inference, provider
access, acquisition, mutable old report, or automatic final polling.
"""
from __future__ import annotations

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.close_mlb_existing_prospective_comparisons_v1 import (
    ARMS, FIELDS, LIMITED, SURVIVAL, TARGETS, ref, require_summary, summary, verify,
)
from scripts.run_mlb_v18_transition_shrinkage_v1 import load_baseline
from scripts.score_mlb_v18_score_limited_v1 import score_arm
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import (
    _digest, _final_identity, joint_energy_score, score_pair,
)
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask

OLD = ROOT / 'outputs/mlb-prospective-closeout-and-explanations-v1'
OUT = OLD / 'formal-revision1'
FINAL_SHA = '4b5dd5c0aad2c56abd18176fc7576a2c736a5f2a942a37a20e328785fb99cdf0'
GATE_SHA = '91716d35ecf91f51e01e8ee236a298186184aa8e7f475217b4efe3c9963c8d1f'
METRICS = ('winnerLogLoss', 'winnerBrier', 'jointEuclideanEnergyScore')


def raw_json(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def immutable(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, 'IMMUTABLE_CONFLICT'
    else:
        path.write_bytes(raw)
    return ref(path)


def save(name, value):
    raw = raw_json(value)
    return immutable(OUT / 'objects/sha256' / hashlib.sha256(raw).hexdigest() / name, raw)


def read(bound):
    return json.loads(verify(bound))


def array_population(bound):
    with np.load(io.BytesIO(verify(bound)), allow_pickle=False) as z:
        return {k: z[k].copy() for k in z.files}


def delta(base, candidate):
    return {**{k: candidate[k] - base[k] for k in METRICS},
        'marginals': {k: {m: candidate['marginals'][k][m] - base['marginals'][k][m]
            for m in ('predictedMean', 'signedError', 'absoluteError', 'squaredError', 'crps')}
            for k in ('homeRuns', 'awayRuns', 'totalRuns', 'homeMargin')}}


def main():
    # Metadata gate is checked before the retained governed outcome bytes open.
    assert all(final_oot_eligible_key_mask(list(TARGETS) + list(TARGETS.values())))
    gate_ref = ref(OUT / 'identity-before-outcomes.json')
    assert gate_ref['sha256'] == GATE_SHA
    gate = read(gate_ref)
    assert gate['wholeGameQuarantineApplied'] and not gate['outcomesRead'] and not gate['sealedOotRead']
    assert set(gate['sourceGameIdentities']) == set(TARGETS)
    originals = [ref(SURVIVAL), ref(LIMITED), ref(OLD/'prospective-closeout.json'),
                 ref(OLD/'RESULTS.md'), ref(OLD/'final-inventory.json')]
    for p in (SURVIVAL, LIMITED):
        assert ref(p)['sha256'] == p.parent.name
    s, c = (json.loads(p.read_bytes()) for p in (SURVIVAL, LIMITED))
    prior_ref = json.loads((OLD/'prospective-closeout.json').read_bytes())
    prior = read(prior_ref)
    originals.extend([prior_ref, s['population'], c['acceptedPopulation'], s['baselineForecast'], c['baselineForecast']])
    bundles = {pk: load_baseline(obj) for pk, obj in (
        ('824225', s['sourceForecastObjectSha256']), ('823734', c['baselineObjectSha256']))}
    finals_ref = ref(OUT/'governed-finals.json')
    assert finals_ref['sha256'] == FINAL_SHA and finals_ref['bytes'] == 2790
    final_receipt = read(finals_ref)
    digest_body = {k: v for k, v in final_receipt.items() if k != 'receiptSha256'}
    assert _digest(digest_body) == final_receipt['receiptSha256']
    assert final_receipt['source']['readOnlyTransactionVerified']
    assert final_receipt['source']['providerCalls'] == final_receipt['source']['aispRowsModified'] == 0
    finals = {f['gameId']: f for f in final_receipt['records']}
    assert len(finals) == 2 and set(finals) == set(TARGETS.values())
    for pk, execution in (('824225', s), ('823734', c)):
        game_id, start, baseline_id = gate['sourceGameIdentities'][pk]
        f = finals[game_id]
        assert execution['gameId'] == game_id == TARGETS[pk]
        assert execution['scheduledStartUtc'] == f['scheduledStartUtc'] == start
        assert execution['baselineForecastId'] == f['commonPairId'] == baseline_id
        assert f['status'] == 'FINAL' and f['sourceRevision'] == 1 and f['sourceOutcomeId']
        assert datetime.fromisoformat(start) < datetime.fromisoformat(f['finalAt']) <= datetime.now(timezone.utc)
        assert datetime.fromisoformat(execution['frozenAtUtc']) < datetime.fromisoformat(execution['deadlineUtc'])
    assert [(finals[TARGETS[pk]]['awayScore'], finals[TARGETS[pk]]['homeScore'])
            for pk in ('824225', '823734')] == [(1, 8), (4, 3)]

    z = array_population(s['population'])
    populations, summaries = {}, {}
    for arm in ARMS:
        populations[arm] = {k: z[arm+'_'+k] for k in FIELDS}
        assert all(v.shape == (5000,) for v in populations[arm].values())
        summaries[arm] = summary(populations[arm])
        require_summary(summaries[arm], s['arms'][arm]['summary'])
        if arm == 'V18_BASE':
            assert all(np.array_equal(populations[arm][k], bundles['824225']['baseline'][k]) for k in FIELDS)
        else:
            assert s['arms'][arm]['status'] == 'APPLIED'
    rows, score_refs = [], []
    ids = {'V18_BASE': s['baselineForecastId'],
        'V18_SURVIVAL_ONLY': 'mlb-v18-survival-'+SURVIVAL.parent.name,
        'V18_TRANSITION_ONLY': 'mlb-v18-transition-'+SURVIVAL.parent.name}
    for arm in ARMS[1:]:
        pair = {'gameId': s['gameId'], 'commonPairId': ids[arm], 'scheduledStartUtc': s['scheduledStartUtc']}
        scored = score_pair(pair, {'reference': populations['V18_BASE'], 'challenger': populations[arm]}, finals[s['gameId']])
        # The shared scorer's legacy duration labels do not identify this component.
        scored['arms']['reference']['arm'] = 'V18_BASE'
        scored['arms']['challenger']['arm'] = arm
        score_refs.append(save(arm.lower()+'-score.json', scored))
        if not rows:
            rows.append({'gamePk': '824225', 'game': 'COL–DET', 'arm': 'BASELINE',
                'forecastId': ids['V18_BASE'], 'summary': summaries['V18_BASE'], 'metrics': scored['arms']['reference']})
        rows.append({'gamePk': '824225', 'game': 'COL–DET', 'arm': arm, 'forecastId': ids[arm],
            'summary': summaries[arm], 'metrics': scored['arms']['challenger'],
            'candidateMinusBaseline': scored['challengerMinusReference'], 'scoringReceipt': score_refs[-1]})
        # Existing qualified consumer scores must agree; preserve their original identity.
        old_metrics = prior['consumerEvaluations'][arm]['metrics']
        for new_key, old_key in (('winnerLogLoss', 'winnerLogLoss'), ('winnerBrier', 'winnerBinaryBrier')):
            assert np.isclose(rows[-1]['metrics'][new_key], old_metrics[old_key], atol=1e-14, rtol=0)
        for key, old_key in (('homeRuns', 'homeCRPS'), ('awayRuns', 'awayCRPS'), ('totalRuns', 'totalCRPS'), ('homeMargin', 'marginCRPS')):
            assert np.isclose(rows[-1]['metrics']['marginals'][key]['crps'], old_metrics[old_key], atol=1e-12, rtol=0)

    z = array_population(c['acceptedPopulation'])
    ix = z['accepted_indices']
    assert ix.dtype.kind in 'iu' and len(ix) == c['retainedDrawCount'] == 4722 and np.all(np.diff(ix) > 0)
    assert np.array_equal(np.flatnonzero(z['acceptance_mask']), ix)
    for k in FIELDS:
        assert len(z['baseline_'+k]) == c['originalDrawCount'] == 5000
        assert np.array_equal(z['baseline_'+k], bundles['823734']['baseline'][k])
        assert np.array_equal(z['accepted_'+k], z['baseline_'+k][ix])
    limited_metrics = {}
    f = finals[c['gameId']]
    for arm, saved in (('baseline', c['baselineSummary']), ('accepted', c['summary'])):
        h, a = z[arm+'_homeRuns'], z[arm+'_awayRuns']
        scored = score_arm(h, a, f['homeScore'], f['awayScore'], saved)
        scored['jointEuclideanEnergyScore'] = joint_energy_score(h, a, (f['homeScore'], f['awayScore']))
        limited_metrics[arm] = scored
        rows.append({'gamePk': '823734', 'game': 'CIN–MIL', 'arm': 'BASELINE' if arm == 'baseline' else 'SCORE_LIMITED',
            'forecastId': c['baselineForecastId'] if arm == 'baseline' else prior['scoreLimited']['forecastId'],
            'summary': summary({'homeRuns': h, 'awayRuns': a}), 'metrics': scored})
    difference = delta(limited_metrics['baseline'], limited_metrics['accepted'])
    rows[-1]['candidateMinusBaseline'] = difference
    limited_score = {'schemaVersion': 'MLB_EXISTING_UNEQUAL_N_SCORE_LIMIT_ASSESSMENT_V1',
        'gameId': c['gameId'], 'baselineForecastId': c['baselineForecastId'], 'candidateForecastId': rows[-1]['forecastId'],
        'execution': ref(LIMITED), 'population': c['acceptedPopulation'], 'final': f,
        'finalIdentitySha256': _digest(_final_identity(f)), 'arms': limited_metrics,
        'candidateMinusBaseline': difference, 'originalDrawCount': 5000, 'retainedDrawCount': 4722,
        'exclusionRate': c['exclusionRate'], 'excludedDrawCount': c['excludedDrawCount'],
        'simulationUncertainty': c['uncertainty'], 'pairedEqualNScorerUsed': False,
        'subsetOrderAndValuesPreserved': True}
    limited_score['scoreIdentity'] = _digest(limited_score)
    rows[-1]['scoringReceipt'] = save('score-limited-score.json', limited_score)
    score_refs.append(rows[-1]['scoringReceipt'])
    for row in rows:
        f = finals[TARGETS[row['gamePk']]]
        row['finalIdentity'] = _final_identity(f)
        row['actualAwayHome'] = [f['awayScore'], f['homeScore']]
        row['winnerPick'] = 'HOME' if row['summary']['homeWinProbability'] > .5 else 'AWAY'
        row['correctPick'] = row['winnerPick'] == ('HOME' if f['homeScore'] > f['awayScore'] else 'AWAY')
        assert row['summary']['tieProbability'] == 0 and row['correctPick']
    for bound in originals:
        verify(bound)
    report = {'schemaVersion': 'MLB_EXISTING_PROSPECTIVE_FORMAL_CLOSEOUT_V1',
        'createdAtUtc': datetime.now(timezone.utc).isoformat(), 'classification': 'ASSESSMENT_OF_ORIGINAL_PROSPECTIVELY_FROZEN_FORECASTS',
        'priorQualifiedCloseoutPreserved': prior_ref, 'identityBeforeOutcomes': gate_ref, 'governedFinals': finals_ref,
        'rows': rows, 'scoringReceipts': score_refs, 'distinctGames': 2, 'interventions': 3,
        'fallbacks': 0, 'originalForecastClocks': {'survivalAndTransition': prior['survivalAndTransition'],
            'scoreLimited': {k: prior['scoreLimited'][k] for k in ('execution', 'forecastId', 'baselineForecastId',
                'sourceCutoff', 'frozenAtUtc', 'deadlineUtc', 'importedAt', 'frozenLimits', 'rule', 'rulePublication')}},
        'pitcherAllocationAssessment': {'status': 'UNAVAILABLE',
            'reason': 'Original baseline starter/relief counters and final-bound actual pitcher evidence unavailable. Existing candidate-only summaries remain in the prior receipt; no allocation gain can be measured.'},
        'scoreLimited': {'originalDrawCount': 5000, 'retainedDrawCount': 4722, 'excludedDrawCount': 278,
            'exclusionRate': .0556, 'wrongToRight': 0, 'rightToWrong': 0, 'bothCorrect': True},
        'decisions': {'survival': 'Small realized winner-score gain, mixed distribution results; do not advance.',
            'transition': 'Small realized winner-score loss, mixed distribution results; do not advance.',
            'scoreLimited': 'Realized winner and run-distribution scores improve on this game; same correct CIN pick. One observation cannot establish recurring improvement; do not advance.',
            'archetypeBAndC': 'Completed rejection remains unchanged.'},
        'definitions': {'difference': 'Candidate minus baseline; negative loss, Brier, CRPS, energy and absolute-error differences favor the candidate.',
            'brier': 'Binary (pHome-yHome)^2 after exact zero-tie verification; not summed class Brier.',
            'probabilities': 'Fractions from zero to one; original empirical denominators retained.',
            'distributionScores': 'Exact empirical CRPS for away, home, total and home-minus-away margin; Euclidean energy uses original paired home/away draws.',
            'uncertainty': 'MCSE measures conditional simulation precision. No across-game improvement interval is justified by one game per intervention. Unequal-N score limits use original retained subset uncertainty, not equal-N pairing.',
            'economics': 'Correct picks and proper forecast scores do not establish offered-price profitability.'},
        'verification': {'originalPhysicalArtifactsUnchanged': originals, 'originalBaselineArraysExact': True,
            'acceptedSubsetExact': True, 'allCountsAndSummaryMeansReconciled': True, 'sameFinalPerGameAcrossArms': True,
            'priorColConsumerScoresReconciled': True, 'newFits': 0, 'newSimulations': 0, 'providerRequests': 0,
            'aispWrites': 0, 'productionAuthority': False},
        'sourceCode': [ref(Path(__file__)), ref(ROOT/'scripts/score_mlb_v18_score_limited_v1.py'),
            ref(ROOT/'server/sports_current_statcast/mlb_starter_duration_paired_scoring.py')],
        'newHandoffAcknowledged': False}
    result_ref = save('formal-assessment.json', report)
    immutable(OUT/'assessment.json', raw_json(result_ref))
    lines = ['September 13: formal revision-1 assessment', '',
        'COL–DET finished 1–8; CIN–MIL finished 4–3. Two distinct prospective games, three research interventions. Every arm uses its exact original frozen population and the same governed final revision within each game.', '',
        '| Game / arm | N | P(home) | Expected away/home | Log loss | Binary Brier | CRPS away/home/total/margin | Joint energy |',
        '|---|---:|---:|---|---:|---:|---|---:|']
    for r in rows:
        q, m = r['summary'], r['metrics']
        crps = '/'.join(f"{m['marginals'][k]['crps']:.6f}" for k in ('awayRuns', 'homeRuns', 'totalRuns', 'homeMargin'))
        lines.append(f"| {r['game']} / {r['arm']} | {q['drawCount']} | {q['homeWinProbability']:.6f} | {q['meanAwayRuns']:.4f}/{q['meanHomeRuns']:.4f} | {m['winnerLogLoss']:.6f} | {m['winnerBrier']:.6f} | {crps} | {m['jointEuclideanEnergyScore']:.6f} |")
    lines += ['', 'Candidate minus baseline; negative is better for every score below.', '',
        '| Game / candidate | Δ log loss | Δ binary Brier | Δ CRPS away/home/total/margin | Δ joint energy | Δ absolute margin/total error |',
        '|---|---:|---:|---|---:|---|']
    for r in rows:
        if 'candidateMinusBaseline' not in r:
            continue
        d = r['candidateMinusBaseline']
        crps = '/'.join(f"{d['marginals'][k]['crps']:+.6f}" for k in ('awayRuns', 'homeRuns', 'totalRuns', 'homeMargin'))
        ae = '/'.join(f"{d['marginals'][k]['absoluteError']:+.6f}" for k in ('homeMargin', 'totalRuns'))
        lines.append(f"| {r['game']} / {r['arm']} | {d['winnerLogLoss']:+.6f} | {d['winnerBrier']:+.6f} | {crps} | {d['jointEuclideanEnergyScore']:+.6f} | {ae} |")
    lines += ['', 'Survival improves winner scores slightly; transition worsens them slightly. Both have mixed marginal results. CIN score limits improve winner scores, every marginal CRPS and joint energy on this realized game; both configurations already selected CIN correctly. There were zero pick changes. These are individual outcomes, not evidence of recurring improvement or profitability; no arm advances.', '',
        'Score limits retained 4,722/5,000 draws (278 excluded, 5.56%); fixed limits remain 5 runs per played half-inning and 14 per team per game. The original 5,000-draw baseline and full scoring tail remain unchanged. Existing simulation MCSE is retained in the scoring receipts; it does not bound model error.', '',
        'Pitcher-allocation improvement remains unavailable: the original baseline lacks starter/relief counters and no exact-final-bound actual pitcher evidence is retained. This does not block whole-game scoring. Prior qualified consumer reports remain unchanged; this is an additive formal completion.', '',
        f"Governed final receipt: `{finals_ref['path']}`, physical SHA-256 `{finals_ref['sha256']}`.",
        'COL–DET: `cd779bf5-e277-4d9c-a631-6eb3e422a0f1`, revision 1. CIN–MIL: `105dc37c-8fbe-4dbf-abf4-a81bfddb2194`, revision 1.', '',
        f"Formal result: `{result_ref['path']}`, physical SHA-256 `{result_ref['sha256']}`.", '',
        'Reproduce from retained finals and draws: `.venv/Scripts/python.exe -B scripts/assess_mlb_existing_prospective_finals_v1.py`.',
        'To preserve one-shot artifacts, remove no files: after completion the command verifies the retained receipt instead of resimulation or outcome polling.']
    immutable(OUT/'RESULTS.md', ('\n'.join(lines)+'\n').encode())
    print(json.dumps({'result': result_ref, 'rows': len(rows), 'distinctGames': 2, 'scoringReceipts': score_refs}, indent=2))


if __name__ == '__main__':
    if (OUT/'assessment.json').exists():
        bound = json.loads((OUT/'assessment.json').read_bytes())
        result = read(bound)
        for item in result['scoringReceipts'] + result['verification']['originalPhysicalArtifactsUnchanged']:
            verify(item)
        print(json.dumps({'status': 'EXISTING_FORMAL_ASSESSMENT_VERIFIED', 'result': bound}, indent=2))
    else:
        main()
