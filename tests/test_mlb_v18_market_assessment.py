from copy import deepcopy
import math
import unittest

from scripts.mlb_v18_market_assessment import ASSESSMENTS, assess


def record(i=0, **changes):
    row = {'packetSha256': f'{i:064x}', 'episodeKey': f'episode-{i}', 'gameId': f'game-{i}',
           'scheduledStartUtc': f'2026-09-{19 + i % 5:02}T18:00:00Z',
           'forecastEligible': True, 'priceEvaluable': True, 'selectionAscertained': True,
           'selectionStatus': 'SELECTED' if i % 2 else 'EVALUATED_NOT_SELECTED',
           'pHome': .6, 'qHome': .5, 'anchorKind': 'ACTUAL_DECISION'}
    row.update(changes)
    return row


def outcome(i=0, **changes):
    row = {'gameId': f'game-{i}', 'status': 'DECISIVE', 'revisionId': f'revision-{i}-1',
           'admittedAtUtc': f'2026-09-{19 + i % 5:02}T22:00:00Z',
           'finalAtUtc': f'2026-09-{19 + i % 5:02}T21:00:00Z',
           'homeScore': 5 if i % 2 else 2, 'awayScore': 3,
           'sourceRef': {'path': f'fixture/{i}.json', 'sha256': 'a' * 64}}
    row.update(changes)
    return row


class MarketAssessmentTests(unittest.TestCase):
    def test_exact_scheduled_cutoff_and_execution_time_required(self):
        with self.assertRaisesRegex(ValueError, 'UNSCHEDULED'):
            assess([], [], '2026-09-21T16:00:00Z', ASSESSMENTS[0])
        with self.assertRaisesRegex(ValueError, 'EXECUTED_BEFORE'):
            assess([], [], ASSESSMENTS[0], '2026-09-22T15:59:59Z')
        empty = assess([], [], '2026-09-22T12:00:00-04:00', ASSESSMENTS[0])
        self.assertEqual(empty['coverage']['attempts'], 0)
        self.assertEqual(empty['status'], 'INSUFFICIENT_EVIDENCE')
        self.assertEqual(empty['coverage']['outcomeStatus']['VOID'], 0)
        self.assertEqual(empty['bySelection']['UNRESOLVED']['coverage']['attempts'], 0)

    def test_same_admitted_revision_for_both_and_future_revision_ignored(self):
        revisions = [outcome(0), outcome(0, revisionId='revision-0-2',
                     admittedAtUtc='2026-09-23T22:00:00Z', homeScore=6)]
        result = assess([record()], revisions, ASSESSMENTS[0], ASSESSMENTS[1])
        row = result['records'][0]
        self.assertEqual(row['outcomeRevision']['revisionId'], 'revision-0-1')
        self.assertAlmostEqual(row['logLossDifference'], -math.log(.4) + math.log(.5))
        later = assess([record()], revisions, ASSESSMENTS[1], ASSESSMENTS[1])
        self.assertEqual(later['records'][0]['outcomeRevision']['revisionId'], 'revision-0-2')
        self.assertEqual(later['records'][0]['pHome'], .6)

    def test_ambiguous_revisions_and_duplicate_primary_game_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'AMBIGUOUS_LATEST'):
            assess([record()], [outcome(), outcome(revisionId='another')], ASSESSMENTS[0], ASSESSMENTS[0])
        with self.assertRaisesRegex(ValueError, 'CONFLICTING_OUTCOME'):
            assess([record()], [outcome(), outcome(homeScore=6)], ASSESSMENTS[0], ASSESSMENTS[0])
        with self.assertRaisesRegex(ValueError, 'MULTIPLE_ELIGIBLE'):
            assess([record(), record(episodeKey='new-episode')], [outcome()], ASSESSMENTS[0], ASSESSMENTS[0])

    def test_missing_price_and_unknown_selection_are_distinct(self):
        records = [record(0, selectionStatus='UNRESOLVED', selectionAscertained=False),
                   record(1, priceEvaluable=False, qHome=None), record(2, forecastEligible=False)]
        result = assess(records, [outcome(i) for i in range(3)], ASSESSMENTS[0], ASSESSMENTS[0])
        self.assertEqual(result['coverage']['attempts'], 3)
        self.assertEqual(result['coverage']['legitimateForecasts'], 2)
        self.assertEqual(result['coverage']['freshPairedPrices'], 1)
        self.assertEqual(result['paired']['games'], 1)
        self.assertEqual(result['bySelection']['UNRESOLVED']['paired']['games'], 1)
        self.assertEqual(result['coverage']['unpricedLegitimateForecasts'], 1)

    def test_push_tie_void_and_pending_never_become_losses(self):
        statuses = ['PUSH', 'TIE', 'REFUND', 'NO_CONTEST', 'VOID', 'PENDING']
        records = [record(i) for i in range(7)]
        outcomes = [outcome(i, status=status, homeScore=3 if status == 'TIE' else 5)
                    for i, status in enumerate(statuses)]
        result = assess(records, outcomes, ASSESSMENTS[1], ASSESSMENTS[1])
        self.assertEqual(result['paired']['games'], 0)
        for status in statuses + ['PENDING_NO_ADMITTED_OUTCOME']:
            self.assertEqual(result['coverage']['outcomeStatus'][status], 1)

    def test_retained_score_crps_clamps_and_inputs_remain_unchanged(self):
        records = [record(pHome=1, qHome=0, scorePairs=[[5, 3]] * 5000)]
        original = deepcopy(records)
        result = assess(records, [outcome(homeScore=6, awayScore=3)], ASSESSMENTS[0], ASSESSMENTS[0])
        self.assertEqual(records, original)
        self.assertEqual(result['scoringClamp']['v18Games'], 1)
        self.assertEqual(result['scoringClamp']['marketGames'], 1)
        scores = result['pairedPopulationScoreDiagnostics']
        self.assertEqual(scores['home']['mae'], 1)
        self.assertEqual(scores['home']['crps'], 1)
        self.assertEqual(scores['away']['crps'], 0)
        self.assertEqual(scores['margin']['crps'], 1)
        self.assertEqual(scores['total']['crps'], 1)
        self.assertEqual(result['records'][0]['pHome'], 1)

    def test_non_degenerate_empirical_crps(self):
        pairs = [[1, 0]] * 2500 + [[3, 0]] * 2500
        result = assess([record(pHome=1, scorePairs=pairs)], [outcome(homeScore=2, awayScore=0)],
                        ASSESSMENTS[0], ASSESSMENTS[0])
        self.assertEqual(result['pairedPopulationScoreDiagnostics']['home']['crps'], .5)

    def test_distribution_probability_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'POPULATION_MISMATCH'):
            assess([record(scorePairs=[[5, 3]] * 5000)], [outcome()], ASSESSMENTS[0], ASSESSMENTS[0])

    def test_support_gates_and_bootstrap_determinism(self):
        records, outcomes = [record(i) for i in range(20)], [outcome(i) for i in range(20)]
        september = assess(records, outcomes, ASSESSMENTS[1], ASSESSMENTS[1])
        self.assertIsNone(september['uncertainty']['game'])
        self.assertIn('SEPTEMBER_29_REQUIRES_100_PAIRS', september['uncertainty']['reasonCodes'])
        first = assess(records, outcomes, ASSESSMENTS[2], ASSESSMENTS[2])
        second = assess(records, outcomes, ASSESSMENTS[2], ASSESSMENTS[2])
        self.assertEqual(first, second)
        self.assertEqual(first['uncertainty']['resamples'], 5000)
        self.assertEqual(len(first['uncertainty']['leaveOneDateOut']), 5)
        self.assertEqual(first['bySelection']['SELECTED']['supportStatus'], 'INSUFFICIENT_EVIDENCE')
        self.assertTrue(all(b['supportStatus'] == 'INSUFFICIENT_EVIDENCE' for b in first['calibration']['v18']))

    def test_fewer_than_five_dates_blocks_interval_even_with_100_pairs(self):
        records = [record(i, scheduledStartUtc='2026-09-19T18:00:00Z') for i in range(100)]
        result = assess(records, [outcome(i) for i in range(100)], ASSESSMENTS[1], ASSESSMENTS[1])
        self.assertIsNone(result['uncertainty']['game'])
        self.assertIn('FEWER_THAN_FIVE_UTC_DATES', result['uncertainty']['reasonCodes'])

    def test_september_29_supported_descriptive_population_and_band_edges(self):
        records = [record(i, selectionStatus='SELECTED') for i in range(100)]
        result = assess(records, [outcome(i) for i in range(100)], ASSESSMENTS[1], ASSESSMENTS[1])
        self.assertEqual(result['uncertainty']['status'], 'DESCRIPTIVE_SENSITIVITY_ONLY')
        self.assertEqual(result['bySelection']['SELECTED']['supportStatus'], 'DESCRIPTIVE_SUPPORTED')
        self.assertEqual(result['calibration']['v18'][3]['games'], 100)
        self.assertEqual(result['calibration']['market'][2]['games'], 100)
        self.assertEqual(result['calibration']['market'][2]['supportStatus'], 'DESCRIPTIVE_SUPPORTED')
        self.assertFalse(result['formalLook'])
        self.assertFalse(result['productionOrPromotionAuthority'])


if __name__ == '__main__':
    unittest.main()
