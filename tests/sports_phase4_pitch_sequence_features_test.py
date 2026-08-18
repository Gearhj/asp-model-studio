"""Hermetic tests for the E1 pitch-sequence parser (no model training, no data)."""

import unittest

from server.sports_phase4 import pitch_sequence_features as ps


class ParserSupportedSymbolsTest(unittest.TestCase):
    def test_core_categories(self):
        self.assertEqual(ps.classify_symbol("B"), "BALL")
        self.assertEqual(ps.classify_symbol("C"), "CALLED_STRIKE")
        self.assertEqual(ps.classify_symbol("S"), "SWINGING_STRIKE")
        self.assertEqual(ps.classify_symbol("F"), "FOUL")
        self.assertEqual(ps.classify_symbol("X"), "IN_PLAY")
        self.assertEqual(ps.classify_symbol("H"), "HIT_BY_PITCH")

    def test_non_pitch_markers(self):
        for m in (".", ">", "*", "1", "2", "3", "N"):
            self.assertEqual(ps.classify_symbol(m), "NON_PITCH")

    def test_unknown_symbol(self):
        self.assertEqual(ps.classify_symbol("Z"), "UNKNOWN")
        self.assertEqual(ps.classify_symbol("R"), "NON_PITCH")  # documented runner marker


class ParseSequenceTest(unittest.TestCase):
    def test_real_sample_with_markers(self):
        # 'S>B.B.X': swing, (marker), ball, (marker), ball, (marker), in-play.
        r = ps.parse_sequence("S>B.B.X")
        self.assertEqual(r.pitches, 4)
        self.assertEqual(r.balls, 2)
        self.assertEqual(r.swinging_strikes, 1)
        self.assertEqual(r.in_play, 1)
        self.assertEqual(r.non_pitch_markers, 3)
        self.assertEqual(r.terminal_category, "IN_PLAY")
        self.assertTrue(r.first_pitch_strike)
        self.assertFalse(r.reached_two_strikes)

    def test_two_strike_reconstruction(self):
        # C C F F X : strike, strike (2), foul (stays 2), foul (stays 2), in-play.
        r = ps.parse_sequence("CCFFX")
        self.assertTrue(r.reached_two_strikes)
        self.assertEqual(r.two_strike_pitches, 3)  # 2 fouls + in-play at two strikes
        self.assertEqual(r.two_strike_foul, 2)
        self.assertEqual(r.two_strike_in_play, 1)

    def test_foul_does_not_add_third_strike(self):
        r = ps.parse_sequence("CCF")
        self.assertEqual(r.called_strikes, 2)
        self.assertEqual(r.fouls, 1)
        self.assertTrue(r.reached_two_strikes)

    def test_walk_sequence(self):
        r = ps.parse_sequence("BBBB")
        self.assertEqual(r.balls, 4)
        self.assertEqual(r.pitches, 4)
        self.assertFalse(r.reached_two_strikes)
        self.assertFalse(r.first_pitch_strike)

    def test_empty_sequence(self):
        r = ps.parse_sequence("")
        self.assertEqual(r.pitches, 0)
        self.assertEqual(r.terminal_category, "NONE")

    def test_hit_by_pitch_terminal(self):
        r = ps.parse_sequence("BBH")
        self.assertEqual(r.hit_by_pitch, 1)
        self.assertEqual(r.terminal_category, "HIT_BY_PITCH")

    def test_unknown_counted_not_dropped(self):
        r = ps.parse_sequence("BZB")
        self.assertEqual(r.unknown_tokens, 1)
        self.assertEqual(r.balls, 2)

    def test_deterministic(self):
        seq = "FCBFBS"
        self.assertEqual(ps.parse_sequence(seq), ps.parse_sequence(seq))


class ParseQualityTest(unittest.TestCase):
    def test_quality_counts(self):
        q = ps.parse_quality(["FCBFBS", "SX", "", "BZB"])
        self.assertEqual(q["totalRows"], 4)
        self.assertEqual(q["emptySequenceRows"], 1)
        self.assertEqual(q["unknownSymbols"], 1)
        self.assertEqual(q["rowsWithAnyUnknown"], 1)
        self.assertIn(q["parseSuccessRate"], [q["classifiedSymbols"] / q["totalSymbols"]])

    def test_readiness_thresholds(self):
        ready = {"parseSuccessRate": 0.999, "nonEmptySequenceRows": 100, "totalRows": 100}
        self.assertEqual(ps.readiness_from_quality(ready), "PITCH_SEQUENCE_READY")
        partial = {"parseSuccessRate": 0.96, "nonEmptySequenceRows": 95, "totalRows": 100}
        self.assertEqual(ps.readiness_from_quality(partial), "PITCH_SEQUENCE_PARTIALLY_READY")
        blocked = {"parseSuccessRate": 0.80, "nonEmptySequenceRows": 50, "totalRows": 100}
        self.assertEqual(ps.readiness_from_quality(blocked), "PITCH_SEQUENCE_BLOCKED")

    def test_category_table_only_supported(self):
        for row in ps.parser_category_table():
            self.assertEqual(row["support"], "SUPPORTED")


if __name__ == "__main__":
    unittest.main()
