from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from server.sports_nfl_m1.semantic_publisher import forecast_one


def test_late_retroactive_or_unapproved_state_fails_before_inference():
    event = {"eventId": "G", "scheduledStartUtc": "2026-09-09T20:00:00+00:00"}
    packet = {"sourceCutoffUtc": "2026-09-09T10:00:00+00:00"}
    with pytest.raises(ValueError, match="NOT_A_VALID_PREGAME_PUBLICATION"):
        forecast_one(None, "sha", event, packet, now=datetime(2026,9,9,21,tzinfo=timezone.utc))
    with pytest.raises(ValueError, match="AUTHORIZED_PREGAME_STATE_REQUIRED"):
        forecast_one(None, "sha", event, packet, now=datetime(2026,9,9,12,tzinfo=timezone.utc))


def test_same_date_completed_game_evidence_rejected():
    # 00Z kickoff is still the previous Eastern calendar date.
    event = {"eventId": "G", "scheduledStartUtc": "2026-09-10T00:00:00+00:00"}
    packet = {"eventId": "G", "contract": "NFL_SEMANTIC_PREGAME_STATE_V1", "authorizedForCurrentResearchInference": True,
              "sourceCutoffUtc": "2026-09-09T10:00:00+00:00", "maximumCompletedGameEvidenceUtc": "2026-09-09T09:00:00+00:00"}
    with pytest.raises(ValueError, match="SAME_DATE_OUTCOME_EVIDENCE_FORBIDDEN"):
        forecast_one(None, "sha", event, packet, now=datetime(2026,9,9,12,tzinfo=timezone.utc))
