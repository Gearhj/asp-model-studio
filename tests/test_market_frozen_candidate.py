from datetime import datetime, timezone
from pathlib import Path

from server.market_intelligence.frozen_candidate import prospective_record, register_candidate


def test_original_folds_reload_idempotently_and_missing_current_tape_skips():
    """Uses only existing safe research fixtures; no estimator is fitted."""
    root = Path(__file__).resolve().parents[1]
    first = register_candidate(root)
    assert register_candidate(root) == first
    record = prospective_record(root, first, {}, now=datetime(2026, 9, 10, 17, tzinfo=timezone.utc))
    assert record["status"] == "SKIPPED"
    assert "MISSING_FRESH_TWO_BOOK_CONSENSUS" in record["skipReasons"]
    assert "homeWinProbability" not in record
    assert record["replacesV18"] is False
