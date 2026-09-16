"""UNIT_ONLY future-clock/target guards; no fabricated forecast is generated."""
import unittest

import pandas as pd

from server.sports_nba_gen1.authority import NbaAdmissionError
from server.sports_nba_gen1.forecast import _target


class NbaGen1ForecastGateTests(unittest.TestCase):
    def unit_target(self):
        return {"game_id": "UNIT_ONLY", "source_game_id": "UNIT_SOURCE", "season": 2026,
                "season_type": "REGULAR", "home_team_id": "UNIT_HOME", "away_team_id": "UNIT_AWAY",
                "scheduled_tipoff_utc": "2026-10-20T23:00:00Z",
                "schedule_available_at_utc": "2026-10-01T12:00:00Z",
                "status": "SCHEDULED", "source_revision": 1}

    def test_no_outcome_fields_or_started_game_can_pass(self):
        target = self.unit_target()
        cutoff, now = pd.Timestamp("2026-10-20T20:00:00Z"), pd.Timestamp("2026-10-20T21:00:00Z")
        accepted, _ = _target(target, cutoff, now)
        self.assertEqual(accepted["game_id"], "UNIT_ONLY")
        with self.assertRaises(NbaAdmissionError):
            _target({**target, "home_score": 110}, cutoff, now)
        with self.assertRaises(NbaAdmissionError):
            _target(target, cutoff, pd.Timestamp("2026-10-20T23:00:00Z"))

    def test_source_clock_and_identity_cannot_be_invented(self):
        target = self.unit_target()
        cutoff, now = pd.Timestamp("2026-10-20T20:00:00Z"), pd.Timestamp("2026-10-20T21:00:00Z")
        with self.assertRaises(NbaAdmissionError):
            _target({**target, "scheduled_tipoff_utc": "2026-10-20T23:00:00"}, cutoff, now)
        with self.assertRaises(NbaAdmissionError):
            _target({**target, "schedule_available_at_utc": "2026-10-20T20:30:00Z"}, cutoff, now)
        with self.assertRaises(NbaAdmissionError):
            _target({**target, "away_team_id": "UNIT_HOME"}, cutoff, now)


if __name__ == "__main__":
    unittest.main()
