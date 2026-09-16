"""Two focused offline checks for stale execution and explicit input authority."""
from copy import deepcopy

from server.sports_current_statcast.mlb_rf_prospective_support import account_games, assess_game_support


def valid_record():
    inputs = {'status': 'VERIFIED_COMPATIBLE', 'completeForFrozenModel': True, 'canonicalEventId': 'game-1',
              'modelSha256': '1' * 64, 'inputArtifactSha256': '2' * 64, 'orderedSchemaSha256': '3' * 64,
              'compatibilityReceiptSha256': '4' * 64, 'currentEventContextVerified': True,
              'sourceObservedAtUtc': '2026-09-10T12:00:00Z', 'sourceAvailableAsOfUtc': '2026-09-10T12:05:00Z'}
    return {'canonicalEventId': 'game-1', 'canonicalHomeTeamId': 'home', 'canonicalAwayTeamId': 'away',
            'sourceEventId': 'provider-1', 'identityStatus': 'VERIFIED_EXACT', 'eventStatus': 'SCHEDULED',
            'scheduledStartUtc': '2026-09-10T18:00:00Z', 'capturedAtUtc': '2026-09-10T13:00:00Z',
            'evidenceCutoffUtc': '2026-09-10T12:05:00Z', 'originalStatus': 'PUBLISHED',
            'inputCompatibility': {'V18': deepcopy(inputs), 'RF': deepcopy(inputs)}}


def test_original_pregame_capture_cannot_authorize_execution_after_kickoff_and_skips_survive():
    record = valid_record()
    original = deepcopy(record)
    result = assess_game_support(record, execution_time='2026-09-10T18:00:00Z')
    assert result['status'] == 'EXPIRED_NONPROSPECTIVE'
    assert result['supported'] is False
    assert 'EXECUTION_AT_OR_AFTER_KICKOFF' in result['reasons']
    assert record == original
    skipped = deepcopy(record)
    skipped.update(canonicalEventId='game-2', originalStatus='SKIPPED', originalSkipReason='Missing starter')
    output = account_games([record, skipped], execution_time='2026-09-11T00:00:00Z')
    assert output['expiredNonprospectiveCount'] == 2
    assert output['originalSkipCount'] == 1
    assert output['games'][1]['originalSkipReason'] == 'Missing starter'
    assert output['nextSlate']['scheduledGameCount'] is None
    assert output['nextSlate']['supportedGameCount'] == 0


def test_identity_each_frozen_input_contract_and_source_cutoff_are_required():
    record = valid_record()
    assert assess_game_support(record, execution_time='2026-09-10T14:00:00Z')['supported'] is True
    missing = deepcopy(record)
    del missing['inputCompatibility']['RF']['completeForFrozenModel']
    assert assess_game_support(missing, execution_time='2026-09-10T14:00:00Z')['supported'] is False
    leaked = deepcopy(record)
    leaked['inputCompatibility']['RF']['sourceAvailableAsOfUtc'] = '2026-09-10T18:00:00Z'
    result = assess_game_support(leaked, execution_time='2026-09-10T14:00:00Z')
    assert 'RF:INPUT_SOURCE_AT_OR_AFTER_KICKOFF' in result['reasons']
    assert result['supported'] is False
    wrong = deepcopy(record)
    wrong['canonicalAwayTeamId'] = wrong['canonicalHomeTeamId']
    assert 'HOME_AWAY_IDENTITY_COLLISION' in assess_game_support(wrong, execution_time='2026-09-10T14:00:00Z')['reasons']
