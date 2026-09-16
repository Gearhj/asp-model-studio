import json
from pathlib import Path

import pandas as pd

from server.sports_current_statcast.mlb_v18_current_inputs import compose_current_input


def _fixture():
    root = Path(__file__).resolve().parents[1]
    metadata = json.loads((root / '.runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/4171306af87bee46e74d2b5141189a5916382967322592243bf71e9eed9cf684.json').read_text())
    source = {'sourceIdentity': 'fixture-current-schedule', 'observedAt': '2026-09-10T12:00:00Z',
              'availableAsOf': '2026-09-10T12:01:00Z', 'eventId': 'current-game'}
    event = {'canonicalGameId': 'current-game', 'gameDate': '2026-09-10',
             'startsAtUtc': '2026-09-10T23:00:00Z', 'venueTimezone': 'America/New_York',
             'homeTeamId': 'BAL', 'awayTeamId': 'CLE', 'venueId': 'fixture-venue', 'source': source}
    evidence = {
        'canonicalPaId': {**source, 'value': 'hypothetical-first-pa', 'identityKind': 'HYPOTHETICAL_PA'},
        'batterCanonicalPlayerId': {**source, 'value': 'batter-current'},
        'pitcherCanonicalPlayerId': {**source, 'value': 'pitcher-current'},
        'batterBats': {**source, 'value': 'S', 'playerId': 'batter-current'},
        'pitcherThrows': {**source, 'value': 'L', 'playerId': 'pitcher-current'},
    }
    return metadata, event, evidence


def test_current_identity_calendar_and_orientation_are_not_historical_templates():
    metadata, event, evidence = _fixture()
    frame, coverage = compose_current_input(source_order=metadata['sourceColumns'], event=event,
        batting_side='AWAY', as_of_utc='2026-09-10T13:00:00Z', field_evidence=evidence,
        treated_order=metadata['orderedFeatures'], prior_output_schema=metadata['prior']['outputSchema'])
    assert list(frame.columns) == metadata['sourceColumns'] and frame.shape == (1, 246)
    assert frame.loc[0, 'game_date'] == '2026-09-10'
    assert frame.loc[0, 'pitcherCanonicalPlayerId'] == 'pitcher-current'
    assert frame.loc[0, 'context_top_bottom'] == 0
    assert frame.loc[0, 'context_inning'] == 1 and frame.loc[0, 'context_base_mask_before'] == 0
    assert frame.loc[0, 'local_start_hour'] == 19 and frame.loc[0, 'game_month'] == 9
    assert frame.loc[0, 'game_day_of_week'] == 'THURSDAY'
    assert frame.loc[0, 'matchup_batter_bats_switch'] == 1 and frame.loc[0, 'matchup_platoon_advantage'] == 1
    assert pd.isna(frame.loc[0, 'batter_last100_walk_hbp_rate'])
    assert coverage['treatedInputCount'] == 273 and coverage['rawMissingCount'] > 0
    assert not coverage['inferenceExecuted'] and not coverage['dateGuardBypassed']


def test_stale_rolling_incomplete_context_and_wrong_player_evidence_stay_missing():
    metadata, event, evidence = _fixture()
    source = event['source']
    del evidence['batterBats']
    evidence.update({
        'batter_last100_walk_hbp_rate': {**source, 'value': .1, 'playerId': 'batter-current', 'historyCompleteThrough': '2026-08-06'},
        'pitcher_so_per_bfp': {**source, 'value': .24, 'playerId': 'historical-opponent'},
        'batting_games_last_7_days': {**source, 'value': 0},
        'fielding_games_last_7_days': {**source, 'value': 6, 'historyCompleteThrough': '2026-09-09'},
        'fielding_travel_distance_miles': {**source, 'value': 80, 'eventId': 'different-game', 'historyCompleteThrough': '2026-09-09'},
        'matchup_platoon_advantage': {**source, 'value': 1},
    })
    frame, coverage = compose_current_input(source_order=metadata['sourceColumns'], event=event,
        batting_side='HOME', as_of_utc='2026-09-10T13:00:00Z', field_evidence=evidence)
    states = {row['field']: row['status'] for row in coverage['fields']}
    assert states['batter_last100_walk_hbp_rate'] == 'STALE_HISTORY_WINDOW'
    assert states['pitcher_so_per_bfp'] == 'PLAYER_SOURCE_IDENTITY_MISMATCH'
    assert states['batting_games_last_7_days'] == 'HISTORY_WINDOW_COMPLETENESS_NOT_PROVEN'
    assert states['fielding_travel_distance_miles'] == 'SOURCE_EVENT_IDENTITY_MISMATCH'
    assert frame.loc[0, 'fielding_games_last_7_days'] == 6 and frame.loc[0, 'context_top_bottom'] == 1
    assert pd.isna(frame.loc[0, 'batting_games_last_7_days'])
    assert pd.isna(frame.loc[0, 'matchup_platoon_advantage'])
    assert states['matchup_platoon_advantage'] == 'VERIFIED_PARTICIPANT_HANDEDNESS_REQUIRED'
    assert not coverage['coldStartInferredFromMissingEvidence']
