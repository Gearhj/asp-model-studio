"""Only the temporary heartbeat expiry/completion decision; no task mutation."""
from datetime import datetime, timedelta, timezone
import pytest
from scripts.manage_mlb_pair_monitor import restoration_reason
import scripts.manage_mlb_pair_monitor as monitor


def test_restoration_is_first_of_all_saved_pairs_scored_and_24h(monkeypatch):
    paused = datetime(2026, 9, 11, 20, 52, tzinfo=timezone.utc)
    limit = paused + timedelta(hours=24)
    assert restoration_reason(1, 0, limit, paused) is None
    assert restoration_reason(0, 0, limit, paused) is None
    assert restoration_reason(2, 1, limit, paused) is None
    assert restoration_reason(1, 1, limit, paused) == 'ALL_CURRENT_PAIRS_SCORED'
    assert restoration_reason(2, 2, limit, paused) == 'ALL_CURRENT_PAIRS_SCORED'
    assert restoration_reason(1, 0, limit, limit) == '24_HOUR_LIMIT'
    assert restoration_reason(0, 0, limit, limit + timedelta(days=1)) == '24_HOUR_LIMIT'
    with pytest.raises(ValueError, match='INVALID_PAIR_SCORE_ACCOUNTING'):
        restoration_reason(1, 2, limit, paused)
    monkeypatch.setattr(monitor, 'now', lambda: limit)
    monkeypatch.setattr(monitor, 'state', lambda: {'restoreNoLaterThanUtc': limit.isoformat()})
    monkeypatch.setattr(monitor, 'mlb_pause_arguments', lambda: {'id': 'mlb'})
    monkeypatch.setattr(monitor, 'restoration_arguments', lambda: {'id': 'nfl'})
    def corrupt_mlb(*args):
        raise ValueError('CORRUPT_MLB_ARTIFACT')
    monkeypatch.setattr(monitor, 'original', corrupt_mlb)
    monkeypatch.setattr(monitor, 'published_pairs', corrupt_mlb)
    assert monitor.decision()['action'] == 'RESTORE_NFL_NOW'
    monkeypatch.setattr(monitor, 'state', lambda: {'nfl_restored': {'sha256': 'saved'}})
    monkeypatch.setattr(monitor, 'mlb_pause_arguments', corrupt_mlb)
    assert monitor.decision()['action'] == 'NFL_ALREADY_RESTORED'
    rows = [{'gameId': g, 'status': 'PENDING_INPUTS'} for g in ('frozen', 'expired', 'pending')]
    declaration = {'games': [{'gameId': g, 'deadlineUtc': (limit if g != 'pending' else limit + timedelta(hours=1)).isoformat()} for g in ('frozen', 'expired', 'pending')]}
    counts = monitor.readiness_counts(rows, declaration, ['frozen'], 0, limit)
    assert counts == {'gamesAccountedFor': 3, 'expired': 1, 'pending': 1, 'pairsPublished': 1, 'awaitingFinals': 1, 'scored': 0}
