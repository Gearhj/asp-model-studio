"""Pure scheduled summaries for the frozen private V18 market pilot.

The caller verifies immutable packets, outcome-source hashes, chronology,
regular-season admission and quarantine before calling ``assess``. This module
has no file, provider, database, model-fitting or publication access. scorePairs
are the original 5,000 [home, away] scores, never generated here.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import random

PROTOCOL_SHA = 'f75aeccd8f0e472b399d1f470c29d6a443d77078f7c69333023292019d956bf7'
ASSESSMENTS = ('2026-09-22T16:00:00Z', '2026-09-29T16:00:00Z', '2026-10-02T16:00:00Z')
STATUSES = {'DECISIVE', 'PUSH', 'TIE', 'REFUND', 'NO_CONTEST', 'VOID', 'PENDING'}
SELECTIONS = ('SELECTED', 'EVALUATED_NOT_SELECTED', 'NO_FINAL_DECISION', 'UNRESOLVED')
EPSILON = 1e-15
RESAMPLES = 5000
SEED = 20260919


def _stamp(value):
    parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('TIMESTAMP_WITHOUT_TIMEZONE')
    return parsed.astimezone(timezone.utc)


def _utc(value):
    return _stamp(value).isoformat().replace('+00:00', 'Z')


def _prob(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError('INVALID_PROBABILITY')
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('INVALID_PROBABILITY')
    return float(value)


def _mean(values):
    return math.fsum(values) / len(values) if values else None


def _loss(p, y):
    scoring = min(1 - EPSILON, max(EPSILON, p))
    return -(y * math.log(scoring) + (1 - y) * math.log1p(-scoring)), scoring != p


def _score(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError('INVALID_FINAL_OR_RETAINED_SCORE')
    return value


def _latest_outcomes(outcomes, cutoff):
    by_game = defaultdict(list)
    revisions = {}
    for original in outcomes:
        admitted = _stamp(original['admittedAtUtc'])
        if admitted > cutoff:
            continue
        if not original['gameId'] or not original['revisionId'] or not original.get('sourceRef'):
            raise ValueError('MISSING_OUTCOME_REVISION_PROVENANCE')
        game = str(original['gameId'])
        revision = str(original['revisionId'])
        if original['status'] not in STATUSES:
            raise ValueError('INVALID_OUTCOME_STATUS')
        if original['status'] != 'PENDING':
            final = _stamp(original['finalAtUtc'])
            if final > admitted or final > cutoff:
                raise ValueError('FINAL_NOT_AVAILABLE_BY_ADMISSION')
        if original['status'] == 'DECISIVE':
            if _score(original['homeScore']) == _score(original['awayScore']):
                raise ValueError('DECISIVE_OUTCOME_HAS_TIED_SCORE')
        if original['status'] == 'TIE':
            if _score(original['homeScore']) != _score(original['awayScore']):
                raise ValueError('TIE_OUTCOME_HAS_DECISIVE_SCORE')
        encoded = json.dumps(original, sort_keys=True, separators=(',', ':'), allow_nan=False)
        key = (game, revision)
        if key in revisions:
            if revisions[key] != encoded:
                raise ValueError('CONFLICTING_OUTCOME_REVISION')
            continue
        revisions[key] = encoded
        by_game[game].append((admitted, original))
    result = {}
    for game, choices in by_game.items():
        last_time = max(item[0] for item in choices)
        latest = [item[1] for item in choices if item[0] == last_time]
        if len(latest) != 1:
            raise ValueError('AMBIGUOUS_LATEST_OUTCOME_REVISION')
        result[game] = latest[0]
    return result


def _crps(values, observed):
    values = sorted(values)
    n = len(values)
    return math.fsum(abs(x - observed) for x in values) / n - math.fsum(
        (2 * i - n - 1) * x for i, x in enumerate(values, 1)
    ) / (n * n)


def _score_distribution(pairs, outcome, p_home):
    if len(pairs) != 5000:
        raise ValueError('RETAINED_SCORE_POPULATION_NOT_5000')
    for pair in pairs:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError('INVALID_RETAINED_SCORE_PAIR')
        if _score(pair[0]) == _score(pair[1]):
            raise ValueError('TIED_RETAINED_SCORE_PATH')
    if sum(h > a for h, a in pairs) / 5000 != p_home:
        raise ValueError('PROBABILITY_SCORE_POPULATION_MISMATCH')
    home = [p[0] for p in pairs]
    away = [p[1] for p in pairs]
    values = {'home': home, 'away': away,
              'margin': [h - a for h, a in pairs], 'total': [h + a for h, a in pairs]}
    h, a = outcome['homeScore'], outcome['awayScore']
    observed = {'home': h, 'away': a, 'margin': h - a, 'total': h + a}
    return {name: {'predictedMean': _mean(sample), 'observed': observed[name],
                   'error': _mean(sample) - observed[name],
                   'crps': _crps(sample, observed[name])}
            for name, sample in values.items()}


def _score_summary(rows):
    scored = [row['scoreDistribution'] for row in rows if row.get('scoreDistribution')]
    result = {'games': len(scored), 'marketScoreDistribution': 'NOT_AVAILABLE_FROM_MONEYLINE'}
    for component in ('home', 'away', 'margin', 'total'):
        errors = [item[component]['error'] for item in scored]
        result[component] = {'bias': _mean(errors), 'mae': _mean([abs(x) for x in errors]),
                             'rmse': math.sqrt(_mean([x * x for x in errors])) if errors else None,
                             'crps': _mean([item[component]['crps'] for item in scored])}
    return result


def _paired_summary(rows):
    return {'games': len(rows), 'homeWins': sum(row['homeWon'] for row in rows),
            'homeLosses': sum(1 - row['homeWon'] for row in rows),
            'v18LogLoss': _mean([r['v18LogLoss'] for r in rows]),
            'marketLogLoss': _mean([r['marketLogLoss'] for r in rows]),
            'logLossDifferenceV18MinusMarket': _mean([r['logLossDifference'] for r in rows]),
            'v18Brier': _mean([r['v18Brier'] for r in rows]),
            'marketBrier': _mean([r['marketBrier'] for r in rows]),
            'brierDifferenceV18MinusMarket': _mean([r['brierDifference'] for r in rows]),
            'meanProbabilityDisagreement': _mean([r['pHome'] - r['qHome'] for r in rows]),
            'meanAbsoluteProbabilityDisagreement': _mean([abs(r['pHome'] - r['qHome']) for r in rows])}


def _quantile(sorted_values, probability):
    place = (len(sorted_values) - 1) * probability
    low = int(place)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (place - low)


def _bootstrap(rows, checkpoint):
    by_date = defaultdict(list)
    for row in rows:
        by_date[row['utcDate']].append(row)
    minimum = 100 if checkpoint == ASSESSMENTS[1] else 20
    reasons = []
    if len(rows) < minimum:
        reasons.append('SEPTEMBER_29_REQUIRES_100_PAIRS' if minimum == 100 else 'FEWER_THAN_20_PAIRS')
    if len(by_date) < 5:
        reasons.append('FEWER_THAN_FIVE_UTC_DATES')
    result = {'status': 'INSUFFICIENT_EVIDENCE' if reasons else 'DESCRIPTIVE_SENSITIVITY_ONLY',
              'reasonCodes': reasons, 'resamples': RESAMPLES, 'seed': SEED,
              'quantileProbabilities': [0.025, 0.5, 0.975],
              'intervalMeaning': 'Descriptive percentile sensitivity; not a formal confidence or advancement gate',
              'independentUnit': 'game or complete UTC-date block; never simulation draws',
              'game': None, 'utcDateBlock': None, 'leaveOneDateOut': []}
    if reasons:
        return result
    metrics = ('logLossDifference', 'brierDifference')
    vectors = [[r[m] for m in metrics] for r in rows]
    dates = sorted(by_date)
    blocks = [(len(by_date[d]), [math.fsum(r[m] for r in by_date[d]) for m in metrics]) for d in dates]
    game_samples = [[] for _ in metrics]
    block_samples = [[] for _ in metrics]
    rng_game, rng_block = random.Random(SEED), random.Random(SEED)
    for _ in range(RESAMPLES):
        indices = rng_game.choices(range(len(vectors)), k=len(vectors))
        for j in range(len(metrics)):
            game_samples[j].append(math.fsum(vectors[i][j] for i in indices) / len(vectors))
        selected_blocks = rng_block.choices(blocks, k=len(blocks))
        count = sum(block[0] for block in selected_blocks)
        for j in range(len(metrics)):
            block_samples[j].append(math.fsum(block[1][j] for block in selected_blocks) / count)
    for label, samples in (('game', game_samples), ('utcDateBlock', block_samples)):
        result[label] = {metric: [_quantile(sorted(samples[j]), p) for p in result['quantileProbabilities']]
                         for j, metric in enumerate(metrics)}
    result['leaveOneDateOut'] = [dict(omittedUtcDate=d,
                                     **_paired_summary([r for r in rows if r['utcDate'] != d])) for d in dates]
    return result


def _coverage(rows):
    statuses = Counter(r['outcomeStatus'] for r in rows)
    result = {'attempts': len(rows), 'distinctGames': len({r['gameId'] for r in rows}),
              'legitimateForecasts': sum(r['forecastEligible'] for r in rows),
              'freshPairedPrices': sum(r['forecastEligible'] and r['priceEvaluable'] for r in rows),
              'admittedDecisiveFinalPairs': sum(r['pairedScored'] for r in rows),
              'selectionAscertained': sum(r['selectionAscertained'] for r in rows),
              'unpricedLegitimateForecasts': sum(r['forecastEligible'] and not r['priceEvaluable'] for r in rows),
              'outcomeStatus': {status: statuses[status] for status in sorted(STATUSES | {'PENDING_NO_ADMITTED_OUTCOME'})},
              'exclusionReasons': dict(sorted(Counter(code for row in rows for code in set(row['reasonCodes'])).items()))}
    return result


def _calibration(rows):
    result = {}
    bands = ((0, .4, '[0,0.4)'), (.4, .5, '[0.4,0.5)'),
             (.5, .6, '[0.5,0.6)'), (.6, 1, '[0.6,1]'))
    for model, key in (('v18', 'pHome'), ('market', 'qHome')):
        result[model] = []
        for lower, upper, label in bands:
            group = [r for r in rows if lower <= r[key] and (r[key] < upper or (upper == 1 and r[key] == 1))]
            result[model].append({'band': label, 'games': len(group),
                                   'meanPredicted': _mean([r[key] for r in group]),
                                   'observedHomeWinRate': _mean([r['homeWon'] for r in group]),
                                   'supportStatus': 'DESCRIPTIVE_SUPPORTED' if len(group) >= 30 else 'INSUFFICIENT_EVIDENCE',
                                   'minimumGames': 30})
    return result


def assess(records, outcomes, as_of, executed_at):
    """Return a JSON-safe report only for an exact scheduled frozen checkpoint.

    records are validated pregame packet projections. All records, including
    excluded/unpriced attempts, are retained in coverage. Optional metadata:
    reasonCodes/exclusionReasonCodes, anchorKind, quoteMetadata. Outcome source
    hashes are verified by the caller; revisionId/sourceRef are preserved here.
    No current clock is read: the caller supplies actual execution time.
    """
    checkpoint = _utc(as_of)
    if checkpoint not in ASSESSMENTS:
        raise ValueError('UNSCHEDULED_ASSESSMENT_FORBIDDEN')
    if _stamp(executed_at) < _stamp(as_of):
        raise ValueError('ASSESSMENT_EXECUTED_BEFORE_SCHEDULED_CHECKPOINT')
    latest = _latest_outcomes(outcomes, _stamp(as_of))
    seen_episodes, eligible_games = set(), set()
    rows = []
    for record in sorted(records, key=lambda r: (_stamp(r['scheduledStartUtc']), r['gameId'], r['episodeKey'])):
        game, episode = str(record['gameId']), str(record['episodeKey'])
        if not record['gameId'] or not record['episodeKey'] or not record.get('packetSha256'):
            raise ValueError('MISSING_PACKET_IDENTITY')
        if episode in seen_episodes:
            raise ValueError('DUPLICATE_EPISODE')
        seen_episodes.add(episode)
        for key in ('forecastEligible', 'priceEvaluable', 'selectionAscertained'):
            if not isinstance(record[key], bool):
                raise ValueError('ELIGIBILITY_FLAG_NOT_BOOLEAN')
        if record['selectionStatus'] not in SELECTIONS:
            raise ValueError('INVALID_SELECTION_STATUS')
        if record['forecastEligible']:
            if game in eligible_games:
                raise ValueError('AMBIGUOUS_MULTIPLE_ELIGIBLE_GAME_EPISODES')
            eligible_games.add(game)
        start = _stamp(record['scheduledStartUtc'])
        iso = start.isocalendar()
        outcome = latest.get(game)
        status = outcome['status'] if outcome else 'PENDING_NO_ADMITTED_OUTCOME'
        row = {key: deepcopy(record.get(key)) for key in ('packetSha256', 'episodeKey', 'gameId',
                'scheduledStartUtc', 'forecastEligible', 'priceEvaluable', 'selectionAscertained',
                'selectionStatus', 'pHome', 'qHome', 'anchorKind', 'quoteMetadata')}
        row.update(utcDate=start.date().isoformat(), isoWeek=f'{iso.year}-W{iso.week:02}',
                   selectionStratum=record['selectionStatus'] if record['selectionAscertained'] else 'UNRESOLVED',
                   outcomeStatus=status, outcomeRevision=deepcopy(outcome), pairedScored=False,
                   reasonCodes=list(dict.fromkeys(record.get('reasonCodes', []) + record.get('exclusionReasonCodes', []))),
                   scoreDistribution=None, clampedForScoring={'v18': False, 'market': False})
        if not record['forecastEligible']:
            row['reasonCodes'].append('FORECAST_INELIGIBLE')
        elif not record['priceEvaluable']:
            row['reasonCodes'].append('UNPRICED')
        if status != 'DECISIVE':
            row['reasonCodes'].append(status)
        if record['forecastEligible']:
            p = _prob(record['pHome'])
            if record['priceEvaluable']:
                q = _prob(record['qHome'])
            if status == 'DECISIVE':
                y = int(outcome['homeScore'] > outcome['awayScore'])
                row['homeWon'] = y
                row['v18LogLoss'], row['clampedForScoring']['v18'] = _loss(p, y)
                row['v18Brier'] = (p - y) ** 2
                if record.get('scorePairs') is not None:
                    row['scoreDistribution'] = _score_distribution(record['scorePairs'], outcome, p)
                if record['priceEvaluable']:
                    row['marketLogLoss'], row['clampedForScoring']['market'] = _loss(q, y)
                    row['marketBrier'] = (q - y) ** 2
                    row['logLossDifference'] = row['v18LogLoss'] - row['marketLogLoss']
                    row['brierDifference'] = row['v18Brier'] - row['marketBrier']
                    row['pairedScored'] = True
        rows.append(row)
    paired = [r for r in rows if r['pairedScored']]
    model_only = [r for r in rows if r['forecastEligible'] and r['outcomeStatus'] == 'DECISIVE']
    by_date, by_week, by_selection, by_anchor = {}, {}, {}, {}
    for field, target in (('utcDate', by_date), ('isoWeek', by_week),
                           ('selectionStratum', by_selection), ('anchorKind', by_anchor)):
        values = {r[field] or 'UNRECORDED' for r in rows}
        if field == 'selectionStratum':
            values.update(SELECTIONS)
        for value in sorted(values):
            subset = [r for r in rows if (r[field] or 'UNRECORDED') == value]
            scores = [r for r in subset if r['pairedScored']]
            target[value] = {'coverage': _coverage(subset), 'paired': _paired_summary(scores)}
            if field == 'selectionStratum':
                s = target[value]['paired']
                supported = s['games'] >= 50 and s['homeWins'] >= 10 and s['homeLosses'] >= 10
                target[value]['supportStatus'] = ('DESCRIPTIVE_SUPPORTED' if supported else 'INSUFFICIENT_EVIDENCE')
                target[value]['minimumEvidence'] = {'games': 50, 'homeWins': 10, 'homeLosses': 10}
    threshold = 20 if checkpoint == ASSESSMENTS[0] else 50
    result = {'schema': 'MLB_V18_PRIVATE_MARKET_SCHEDULED_ASSESSMENT_V1', 'protocolSha256': PROTOCOL_SHA,
              'plannedAsOfUtc': checkpoint, 'executedAtUtc': _utc(executed_at),
              'lateExecution': _stamp(executed_at) > _stamp(as_of), 'formalLook': False,
              'productionOrPromotionAuthority': False, 'status': 'DESCRIPTIVE_ONLY' if len(paired) >= threshold else 'INSUFFICIENT_EVIDENCE',
              'scheduledCheckpoint': ('OPERATIONAL_COVERAGE' if checkpoint == ASSESSMENTS[0] else
                                      'REGULAR_SEASON_ASSESSMENT' if checkpoint == ASSESSMENTS[1] else 'FINAL_CLOSEOUT'),
              'primaryMetric': 'PAIRED_HOME_WIN_LOG_LOSS_V18_MINUS_MARKET',
              'negativeDifferenceFavors': 'V18_STANDALONE_SCORE_ONLY_NOT_CONDITIONAL_INFORMATION_OR_WAGERING_EDGE',
              'coverage': _coverage(rows), 'paired': _paired_summary(paired),
              'byUtcDate': by_date, 'byIsoWeek': by_week, 'bySelection': by_selection, 'byAnchorKind': by_anchor,
              'calibration': _calibration(paired), 'uncertainty': _bootstrap(paired, checkpoint),
              'pairedPopulationScoreDiagnostics': _score_summary(paired),
              'modelOnlyScoreDiagnostics': _score_summary(model_only),
              'scoringClamp': {'epsilon': EPSILON, 'savedProbabilitiesChanged': False,
                  'v18Games': sum(r['clampedForScoring']['v18'] for r in rows),
                  'marketGames': sum(r['clampedForScoring']['market'] for r in rows),
                  'affected': [{'episodeKey': r['episodeKey'], 'pHome': r['pHome'], 'qHome': r['qHome'],
                                'clamped': r['clampedForScoring']} for r in rows if any(r['clampedForScoring'].values())]},
              'records': rows}
    # Guard the API contract against accidental NaN, datetime or non-JSON values.
    json.dumps(result, allow_nan=False)
    return result
