"""Focused safeguards for the diagnosis population, using synthetic identities."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from extract_mlb_v18_wager_evidence import identity_gate


def authority(tmp_path, **changes):
    row = {"position_id": "position-1", "game_id": "game-1", "sport": "MLB", "kickoff_utc": "2026-09-12T23:00:00Z", "era": "older model", "forecast_identity": "unused", "decision_timestamp_utc": "2026-09-12T22:40:00Z", "final_home_score": "DO_NOT_READ_IN_IDENTITY_GATE", "result": "DO_NOT_READ_IN_IDENTITY_GATE"}
    row.update(changes)
    path = tmp_path / "positions.csv"
    pd.DataFrame([row]).to_csv(path, index=False)
    return path


def test_sealed_date_stops_before_any_outcome_read(tmp_path, monkeypatch):
    path = authority(tmp_path, kickoff_utc="2026-08-17T23:00:00Z")
    original = pd.read_csv
    calls = []

    def reader(*args, **kwargs):
        calls.append(kwargs.get("usecols"))
        assert "result" not in kwargs["usecols"]
        assert "final_home_score" not in kwargs["usecols"]
        return original(*args, **kwargs)

    monkeypatch.setattr(pd, "read_csv", reader)
    with pytest.raises(ValueError, match="PROTECTED_DATE"):
        identity_gate(path, tmp_path)
    assert len(calls) == 1


def test_missing_mlb_date_fails_closed(tmp_path):
    path = authority(tmp_path, kickoff_utc="")
    with pytest.raises(ValueError, match="MISSING_MLB_DATE"):
        identity_gate(path, tmp_path)


def test_duplicate_positions_fail_before_join(tmp_path):
    path = authority(tmp_path)
    data = pd.read_csv(path)
    pd.concat([data, data]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="DUPLICATE_AUTHORITY_POSITION_ID"):
        identity_gate(path, tmp_path)
