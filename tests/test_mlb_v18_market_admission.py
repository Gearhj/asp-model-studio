"""Synthetic evidence only: no filesystem, provider, model or outcome access."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math

import pytest

from scripts.mlb_v18_market_admission import validate_packet


def _fixture():
    documents = {}
    def ref(value):
        raw = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
        digest = hashlib.sha256(raw).hexdigest()
        path = 'synthetic/' + digest + '.json'
        documents[path] = (raw, value)
        return {'path': path, 'sha256': digest, 'bytes': len(raw)}
    def verify(value):
        raw, result = documents[value['path']]
        if hashlib.sha256(raw).hexdigest() != value['sha256'] or len(raw) != value['bytes']:
            raise ValueError('Hash mismatch')
        return deepcopy(result)
    model = {'engine': 'MLB_V18_WHOLE_GAME', 'paSha256': 'a' * 64,
             'transitionSha256': 'b' * 64, 'parentBundleSha256': 'c' * 64,
             'treatmentManifestSha256': 'd' * 64, 'calibration': 'RETAIN_RAW_V18'}
    protocol = {'protocolSha256': 'f' * 64, 'frozenAtUtc': '2026-09-18T23:00:00Z',
        'model': model, 'window': {'openingUtc': '2026-09-19T04:00:00Z', 'closeUtc': '2026-09-28T04:00:00Z'}}
    ledger_ref = ref({'permanent': True, 'games': [
        {'canonicalGameId': 'quarantined', 'mlbamGamePk': 823343}]})
    protocol['quarantineLedgerAtFreeze'] = ledger_ref
    generic = ref({'scope': 'SYNTHETIC_COMPLETE_PREGAME_PROOF'})
    decision = {'id': 'decision-1', 'game_id': 'game-1', 'phase': 'FINAL_PREGAME',
        'recommended_at': '2026-09-19T19:40:00Z', 'shadow_forecast_id': 'shadow-1',
        'forecast_id': 'forecast-1', 'recommendation': 'NO_BET'}
    evidence = {'rows': {'shadow_experiment_decisions': {'decision-1': decision},
        'official_asp_positions': {}, 'shadow_forecasts': {}}}
    candidate_ref = ref({'allFinalPregameDecisionIds': ['decision-1'],
                         'candidateDecisionIds': ['decision-1']})
    selection_ref = ref({'completeAsOfExport': True, 'experimentId': 'experiment',
                         'freezeRunsInFlightAtBuild': []})
    packet = {'protocolSha256': protocol['protocolSha256'], 'episodeKey': 'game-1/revision-1',
        'sealedAtUtc': '2026-09-19T19:51:00Z', 'attemptLedgerRef': generic,
        'game': {'canonicalGameId': 'game-1', 'sourceGameIds': {'MLB_STATS_API': 'future-1'},
            'homeId': 'home', 'awayId': 'away', 'scheduleRevision': 'revision-1',
            'scheduledStartUtc': '2026-09-19T20:05:00Z', 'firstSeenAtUtc': '2026-09-19T07:00:00Z',
            'phase': 'R', 'phaseEvidenceRef': ref({'archivedAtUtc': '2026-09-19T07:00:00Z',
                'fields': {'gamePk': 'future-1', 'gameType': 'R'}}),
            'quarantineIdentityGate': {'ledgerSha256': ledger_ref['sha256'], 'eligible': True, 'reasonCodes': []}},
        'anchor': {'kind': 'ACTUAL_DECISION', 'atUtc': '2026-09-19T19:40:00Z',
            'researchLockUtc': '2026-09-19T19:50:00Z', 'sealDeadlineUtc': '2026-09-19T20:00:00Z',
            'decisionId': 'decision-1', 'candidateDecisionsRef': candidate_ref},
        'forecast': {'forecastIdentity': 'forecast-1', 'objectRef': generic, 'inputSnapshotRef': generic,
            'modelIdentity': deepcopy(model), 'createdAtUtc': '2026-09-19T19:35:00Z',
            'sourceCutoffUtc': '2026-09-19T19:30:00Z', 'publicationReceiptRef': generic,
            'publicationCompletedAtUtc': '2026-09-19T19:36:00Z', 'importReceiptRef': generic,
            'importReceiptCompletedAtUtc': '2026-09-19T19:38:00Z',
            'pHome': .6, 'pAway': .4, 'scorePopulationRef': generic, 'simulationCount': 5000,
            'seed': 42, 'samplingError': {'producerField': 'synthetic producer MCSE',
                'value': math.sqrt(.6 * .4 / 5000), 'meaning': 'Synthetic saved original field'},
            'sourceClockEvidence': [{'atUtc': '2026-09-19T19:29:00Z'}],
            'operationalEvidence': {}, 'deploymentAttestation': None},
        'selection': {'statusAtResearchLock': 'EVALUATED_NOT_SELECTED',
            'recordedAtUtc': '2026-09-19T19:51:00Z', 'positionIds': [],
            'consumerExportRef': selection_ref, 'completeAsOfExport': True, 'reasonCodes': []},
        'market': {'status': 'FRESH_PAIRED', 'candidates': [], 'selectedBookKey': None,
            'selectedProviderKey': None, 'pair': None, 'qHome': None, 'reasonCodes': []},
        'eligibility': {'forecastEligible': True, 'priceEvaluable': True, 'selectionAscertained': True,
            'reasonCodes': [], 'firstFailure': None}, 'sourceRefs': [ref(evidence)]}
    audit = {'forecastIdentity': 'forecast-1', 'objectRef': generic, 'inputSnapshotRef': generic,
        'modelIdentity': deepcopy(model), 'createdAtUtc': '2026-09-19T19:35:00Z',
        'sourceCutoffUtc': '2026-09-19T19:30:00Z', 'publicationCompletedAtUtc': '2026-09-19T19:37:00Z',
        'scorePairs': [[5, 3]] * 3000 + [[3, 5]] * 2000, 'seed': 42,
        'rawInputCount': 246, 'treatedInputCount': 273, 'illegalStateCount': 0, 'nonterminationCount': 0,
        'sourceEligibilityVerified': True, 'physicalProducerRefs': [generic]}
    context = {'sealCompletedAtUtc': '2026-09-19T19:51:05Z', 'packetSha256': 'e' * 64,
        'sealLedgerRef': ref({'kind': 'SEALED', 'episodeKey': packet['episodeKey'],
            'packetSha256': 'e' * 64, 'writtenAtUtc': '2026-09-19T19:51:05Z'}),
        'readinessAtUtc': '2026-09-19T03:00:00Z', 'authorityExpiresAtUtc': '2026-10-01T00:00:00Z',
        'evidenceDoc': evidence, 'researchForecastSelectionVerified': True}
    protocol['_admissionContext'] = context
    def book(name='a-book', provider='provider', snapshot='snapshot-1', updated='2026-09-19T19:35:00Z',
             available='2026-09-19T19:36:00Z', home_american=-110, away_american=100):
        conventions = {'market': 'two-way full-game moneyline', 'extraInnings': 'INCLUDED',
                       'settlementRule': 'TWO_WAY_NO_TIE', 'pitcherActionRule': 'ACTION'}
        conventions['evidenceRef'] = ref(deepcopy(conventions))
        response = ref({'snapshotId': snapshot, 'providerKey': provider, 'canonicalGameId': 'game-1',
                        'rawResponseSha256': '9' * 64})
        pair = {'bookKey': name, 'providerKey': provider, 'marketId': 'moneyline', 'period': 'full_game',
                'conventions': conventions, 'sourceResponseRef': response, 'snapshotId': snapshot,
                'eligible': False, 'reasonCodes': ['IGNORED_EXPORTER_FLAGS']}
        for side, american in [('home', home_american), ('away', away_american)]:
            pair[side] = {'teamId': side, 'american': american,
                'decimal': 1 + (american / 100 if american > 0 else 100 / -american),
                'quoteUpdatedAtUtc': updated, 'availableByUtc': available, 'status': 'OPEN',
                'availableByIsReceipt': True, 'clockMeaning': 'BOOKMAKER_PER_LEG_UPDATE',
                'availabilityReceiptRef': ref({'status': 'COMPLETED', 'completedAtUtc': available}),
                'rowRef': ref({'teamId': side, 'quoteUpdatedAtUtc': updated, 'quoteClockSource': 'BOOKMAKER_PER_LEG_UPDATE',
                    'american': american, 'bookKey': name, 'providerKey': provider, 'marketId': 'moneyline', 'snapshotId': snapshot}),
                'bookKey': name, 'providerKey': provider, 'marketId': 'moneyline', 'snapshotId': snapshot,
                'period': 'full_game', 'conventions': deepcopy(conventions)}
        return pair
    packet['market']['candidates'] = [book()]
    return packet, protocol, audit, verify, ref, book


def _run(fixture):
    packet, protocol, audit, verify, _, _ = fixture
    return validate_packet(packet, protocol, verify, datetime(2026, 9, 20, tzinfo=timezone.utc), forecast_audit=audit)


def test_valid_packet_can_be_verified_later_without_backdating_or_trusting_flags():
    fixture = _fixture()
    before = deepcopy(fixture[:3])
    result = _run(fixture)
    assert result['reasons'] == []
    assert result['forecastEligible'] and result['priceEvaluable'] and result['selectionAscertained']
    assert result['enrollmentEligible'] and result['pairedMetricEligible']
    assert result['qHome'] == pytest.approx((1 / (1 + 100 / 110)) / ((1 / (1 + 100 / 110)) + .5))
    assert result['validatedAtUtc'] == '2026-09-20T00:00:00+00:00'
    assert fixture[:3] == before


@pytest.mark.parametrize('mode,reason', [
    ('late', 'LATE_OR_BACKDATED_PACKET_SEAL'), ('hash', 'SEALED_PACKET_HASH_MISMATCH'),
    ('phase', 'PHASE_NOT_CERTIFIED_R'), ('quarantine', 'PERMANENT_WHOLE_GAME_QUARANTINE'),
    ('refhash', 'SOURCE_REFERENCE_VERIFICATION_FAILED'), ('authority', 'ENROLLMENT_WINDOW_OR_AUTHORITY_VIOLATION'),
])
def test_packet_provenance_and_clock_failures(mode, reason):
    fixture = _fixture()
    packet, protocol, _, _, ref, _ = fixture
    context = protocol['_admissionContext']
    if mode == 'late':
        context['sealCompletedAtUtc'] = '2026-09-19T20:01:00Z'
        context['sealLedgerRef'] = ref({'kind': 'SEALED', 'episodeKey': packet['episodeKey'],
            'packetSha256': context['packetSha256'], 'writtenAtUtc': context['sealCompletedAtUtc']})
    elif mode == 'hash':
        context['packetSha256'] = '1' * 64
    elif mode == 'phase':
        packet['game']['phase'] = 'UNKNOWN'
    elif mode == 'quarantine':
        packet['game']['sourceGameIds']['alias'] = 'mlbam:game:823343'
    elif mode == 'refhash':
        packet['sourceRefs'][0]['sha256'] = '1' * 64
    elif mode == 'authority':
        context['authorityExpiresAtUtc'] = '2026-09-19T19:45:00Z'
    result = _run(fixture)
    assert reason in result['reasons']
    assert not result['enrollmentEligible']


@pytest.mark.parametrize('mode,reason', [
    ('stale', 'HOME_QUOTE_STALE_FUTURE_OR_NO_ANCHOR'),
    ('future', 'AWAY_QUOTE_STALE_FUTURE_OR_NO_ANCHOR'),
    ('sharedclock', 'HOME_INDIVIDUAL_QUOTE_CLOCK_UNPROVEN'),
    ('unknown', 'PITCHER_ACTION_CONVENTION_UNPROVEN'),
    ('fetch', 'HOME_RECEIPT_BOUND_UNPROVEN'),
    ('decimal', 'HOME_AMERICAN_DECIMAL_DISAGREEMENT'),
    ('oneleg', 'AWAY_LEG_MISSING'),
    ('book', 'HOME_BOOKKEY_BINDING_UNPROVEN'),
    ('response', 'SAME_PROVIDER_RESPONSE_IDENTITY_UNPROVEN'),
])
def test_bad_prices_remain_unpriced_legitimate_forecasts(mode, reason):
    fixture = _fixture()
    packet, _, _, _, ref, _ = fixture
    pair = packet['market']['candidates'][0]
    if mode == 'stale':
        pair['home']['quoteUpdatedAtUtc'] = '2026-09-19T19:24:59Z'
    elif mode == 'future':
        pair['away']['quoteUpdatedAtUtc'] = '2026-09-19T19:40:01Z'
    elif mode == 'sharedclock':
        pair['home']['clockMeaning'] = 'pair’s OLDER provider side update applied to both legs (per-side stamps not retained)'
    elif mode == 'unknown':
        pair['conventions']['pitcherActionRule'] = 'NOT_RETAINED_UNKNOWN'
    elif mode == 'fetch':
        pair['home']['availableByIsReceipt'] = False
    elif mode == 'decimal':
        pair['home']['decimal'] = 2.4
    elif mode == 'oneleg':
        pair['away'] = None
    elif mode == 'book':
        pair['home']['bookKey'] = 'other-book'
    elif mode == 'response':
        pair['sourceResponseRef'] = ref({'snapshotId': 'snapshot-1'})
    result = _run(fixture)
    assert result['enrollmentEligible'] and result['forecastEligible']
    assert not result['priceEvaluable'] and result['marketStatus'] == 'UNPRICED'
    assert result['qHome'] is None and reason in result['reasons']


def test_book_choice_uses_latest_snapshot_then_lexical_book_provider_not_price():
    fixture = _fixture()
    packet, _, _, _, _, book = fixture
    packet['market']['selectedBookKey'] = 'z-best-price'  # explicitly ignored
    packet['market']['candidates'] = [
        book('z-best-price', home_american=300),
        book('a-book', 'z-provider', 'newest-any', updated='2026-09-19T19:39:00Z', available='2026-09-19T19:39:05Z'),
        book('a-book', 'a-provider', 'old', updated='2026-09-19T19:25:00Z', available='2026-09-19T19:26:00Z'),
        book('a-book', 'a-provider', 'z-tie', updated='2026-09-19T19:38:00Z', available='2026-09-19T19:38:05Z'),
        book('a-book', 'a-provider', 'a-tie', updated='2026-09-19T19:38:00Z', available='2026-09-19T19:38:05Z'),
    ]
    result = _run(fixture)
    assert result['priceEvaluable']
    assert (result['selectedPair']['bookKey'], result['selectedPair']['providerKey'], result['selectedPair']['snapshotId']) == (
        'a-book', 'a-provider', 'a-tie')


@pytest.mark.parametrize('mode,reason', [
    ('latepub', 'FORECAST_NOT_AVAILABLE_BY_ANCHOR'),
    ('model', 'FROZEN_MODEL_PASHA256_MISMATCH'),
    ('draws', 'ORIGINAL_PAIRED_POPULATION_5000_REQUIRED'),
    ('tie', 'PAIRED_POPULATION_ILLEGAL_SCORE_OR_TIE'),
    ('probability', 'RAW_PROBABILITY_POPULATION_MISMATCH'),
    ('source', 'SOURCE_OBSERVATION_AFTER_CUTOFF'),
    ('sampling', 'RECORDED_SAMPLING_ERROR_MISSING_OR_MISMATCH'),
])
def test_forecast_cannot_be_rescued_by_eligible_claim(mode, reason):
    fixture = _fixture()
    packet, _, audit, _, _, _ = fixture
    if mode == 'latepub':
        audit['publicationCompletedAtUtc'] = '2026-09-19T19:41:00Z'
    elif mode == 'model':
        audit['modelIdentity']['paSha256'] = '1' * 64
    elif mode == 'draws':
        audit['scorePairs'].pop()
    elif mode == 'tie':
        audit['scorePairs'][0] = [4, 4]
    elif mode == 'probability':
        packet['forecast'].update(pHome=.7, pAway=.3)
    elif mode == 'source':
        packet['forecast']['sourceClockEvidence'][0]['atUtc'] = '2026-09-19T19:31:00Z'
    elif mode == 'sampling':
        packet['forecast']['samplingError']['value'] = .02
    result = _run(fixture)
    assert not result['forecastEligible'] and not result['enrollmentEligible']
    assert reason in result['reasons']


def test_unknown_selection_does_not_filter_full_population():
    fixture = _fixture()
    fixture[0]['selection']['statusAtResearchLock'] = 'UNRESOLVED'
    fixture[0]['selection']['completeAsOfExport'] = False
    result = _run(fixture)
    assert result['pairedMetricEligible'] and result['enrollmentEligible']
    assert not result['selectionAscertained']


def test_later_decision_cannot_replace_named_actual_forecast():
    fixture = _fixture()
    packet, protocol, _, _, ref, _ = fixture
    evidence = protocol['_admissionContext']['evidenceDoc']
    second = deepcopy(evidence['rows']['shadow_experiment_decisions']['decision-1'])
    second.update(id='decision-2', recommended_at='2026-09-19T19:45:00Z', forecast_id='forecast-2')
    evidence['rows']['shadow_experiment_decisions']['decision-2'] = second
    packet['anchor']['candidateDecisionsRef'] = ref({'allFinalPregameDecisionIds': ['decision-1', 'decision-2']})
    result = _run(fixture)
    assert not result['forecastEligible']
    assert 'ACTUAL_DECISION_ANCHOR_MISMATCH' in result['reasons']


def test_selected_position_binds_original_decision_and_conflicts_fail_closed():
    fixture = _fixture()
    packet, protocol, _, _, ref, _ = fixture
    evidence = protocol['_admissionContext']['evidenceDoc']
    first = evidence['rows']['shadow_experiment_decisions']['decision-1']
    first['recommendation'] = 'QUALIFIED_BET'
    evidence['rows']['official_asp_positions']['position-1'] = {
        'id': 'position-1', 'shadow_decision_id': 'decision-1', 'shadow_forecast_id': 'shadow-1', 'placed_at': '2026-09-19T19:41:00Z'}
    second = deepcopy(first)
    second.update(id='decision-2', recommended_at='2026-09-19T19:45:00Z', forecast_id='forecast-2')
    evidence['rows']['shadow_experiment_decisions']['decision-2'] = second
    packet['anchor']['candidateDecisionsRef'] = ref({'allFinalPregameDecisionIds': ['decision-1', 'decision-2']})
    packet['selection'].update(statusAtResearchLock='SELECTED', positionIds=['position-1'])
    assert _run(fixture)['forecastEligible']
    evidence['rows']['official_asp_positions']['position-2'] = {
        'id': 'position-2', 'shadow_decision_id': 'decision-2', 'shadow_forecast_id': 'shadow-1', 'placed_at': '2026-09-19T19:46:00Z'}
    result = _run(fixture)
    assert not result['forecastEligible']
    assert 'ANCHOR_AMBIGUOUS_MULTIPLE_POSITION_DECISIONS' in result['reasons']


def test_conflicting_stable_snapshot_identity_is_not_order_dependent():
    fixture = _fixture()
    packet, _, _, _, _, book = fixture
    packet['market']['candidates'] = [book(home_american=-110), book(home_american=-120)]
    first = _run(fixture)
    packet['market']['candidates'].reverse()
    second = _run(fixture)
    assert not first['priceEvaluable'] and not second['priceEvaluable']
    assert first['firstFailure'] == second['firstFailure'] == 'UNPRICED_CONFLICTING_STABLE_SNAPSHOT_ID'
    assert first['forecastEligible'] and second['forecastEligible']


def test_wrong_type_packet_is_a_countable_exclusion():
    fixture = _fixture()
    fixture[0]['game'] = 'invalid game object'
    result = _run(fixture)
    assert not result['enrollmentEligible']
    assert result['firstFailure'] == 'MALFORMED_PACKET_OR_CONTEXT'


def test_exact_fifteen_minute_leg_age_is_eligible_but_availability_must_precede_anchor():
    fixture = _fixture()
    packet, _, _, _, _, book = fixture
    packet['market']['candidates'] = [book(updated='2026-09-19T19:25:00Z', available='2026-09-19T19:40:00Z')]
    assert _run(fixture)['priceEvaluable']
    packet['market']['candidates'] = [book(updated='2026-09-19T19:25:00Z', available='2026-09-19T19:40:01Z')]
    result = _run(fixture)
    assert not result['priceEvaluable'] and result['forecastEligible']


def test_research_anchor_requires_verified_latest_original_forecast_selection():
    fixture = _fixture()
    packet, protocol, _, _, ref, book = fixture
    protocol['_admissionContext']['evidenceDoc'] = {'rows': {}}
    packet['sourceRefs'] = [ref({'rows': {}})]
    packet['anchor'].update(kind='RESEARCH_T_MINUS_15', atUtc='2026-09-19T19:50:00Z', decisionId=None,
        candidateDecisionsRef=ref({'allFinalPregameDecisionIds': []}))
    packet['selection']['statusAtResearchLock'] = 'NO_FINAL_DECISION'
    packet['market']['candidates'] = [book(updated='2026-09-19T19:40:00Z', available='2026-09-19T19:41:00Z')]
    assert _run(fixture)['pairedMetricEligible']
    protocol['_admissionContext']['researchForecastSelectionVerified'] = False
    result = _run(fixture)
    assert not result['forecastEligible']
    assert 'LATEST_RESEARCH_FORECAST_SELECTION_UNPROVEN' in result['reasons']


def test_nested_array_game_alias_cannot_hide_permanent_quarantine():
    fixture = _fixture()
    fixture[0]['game']['sourceGameIds']['otherProviderAliases'] = [
        'future-alias', {'priorAliases': ['unrelated', ['mlbam:game:823343']]}]
    result = _run(fixture)
    assert not result['forecastEligible'] and not result['enrollmentEligible']
    assert 'PERMANENT_WHOLE_GAME_QUARANTINE' in result['reasons']
