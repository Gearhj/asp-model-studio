"""Hermetic tests for E1 leakage-safe feature materialization (no model training)."""

import unittest

import pandas as pd

from server.sports_phase4 import pitch_sequence_run as run


def _seq(rows):
    cols = ["batter_id", "pitcher_id", "season", "game_date", "source_pitch_sequence"]
    return pd.DataFrame(rows, columns=cols)


class ParseCountsTest(unittest.TestCase):
    def test_counts_frame(self):
        df = _seq([["b1", "p1", 2023, "2023-04-01", "CCX"]])
        counts = run.parse_pa_counts(df)
        row = counts.iloc[0]
        self.assertEqual(int(row["pitches"]), 3)
        self.assertEqual(int(row["called_strikes"]), 2)
        self.assertEqual(int(row["in_play"]), 1)
        self.assertEqual(int(row["pas"]), 1)


class LeakageSafeCumulativeTest(unittest.TestCase):
    def _features(self):
        df = _seq([
            ["b1", "p1", 2023, "2023-04-01", "CCX"],    # 3 pitches, 2 called
            ["b1", "p2", 2023, "2023-04-01", "BBBB"],   # same date, 4 balls
            ["b1", "p3", 2023, "2023-04-10", "SSX"],    # 9 days later
            ["b1", "p4", 2023, "2023-06-01", "BX"],     # >30 days later
        ])
        counts = run.parse_pa_counts(df)
        return run.build_features(counts), df

    def test_same_date_excluded_from_own_history(self):
        feats, df = self._features()
        # The two 2023-04-01 PAs have no strictly-earlier date -> missing history.
        apr1 = feats[feats["_ord"] == feats["_ord"].min()]
        self.assertTrue((apr1["batter_cum_prior_pas"] == 0).all())
        self.assertTrue((apr1["batter_cum_missing_history"] == 1).all())

    def test_cumulative_prior_counts_earlier_dates_only(self):
        feats, df = self._features()
        # The 2023-04-10 PA sees exactly the two 2023-04-01 PAs (7 pitches, 4 balls).
        apr10 = feats.sort_values("_ord").iloc[2]
        self.assertEqual(int(apr10["batter_cum_prior_pas"]), 2)
        self.assertEqual(int(apr10["batter_cum_prior_pitches"]), 7)
        self.assertAlmostEqual(float(apr10["batter_cum_ball_rate"]), 4 / 7, places=6)

    def test_trailing_window_excludes_out_of_window_history(self):
        feats, df = self._features()
        # The 2023-06-01 PA: cumulative sees 3 prior PAs, but trailing-30d sees only
        # the 2023-04-10 PA if within 30 days -- 04-10 to 06-01 is >30 days, so
        # trailing prior_pas is 0 while cumulative prior_pas is 3.
        jun1 = feats.sort_values("_ord").iloc[3]
        self.assertEqual(int(jun1["batter_cum_prior_pas"]), 3)
        self.assertEqual(int(jun1["batter_trail30_prior_pas"]), 0)
        self.assertEqual(int(jun1["batter_trail30_missing_history"]), 1)


class ReadinessPayloadTest(unittest.TestCase):
    def test_payload_shape_and_no_model_metrics(self):
        df = _seq([
            ["b1", "p1", 2023, "2023-04-01", "CCX"],
            ["b1", "p1", 2023, "2023-04-10", "SSX"],
            ["b2", "p2", 2024, "2024-05-01", "BBX"],
        ])
        counts = run.parse_pa_counts(df)
        feats = run.build_features(counts)
        quality = {"parseSuccessRate": 1.0, "nonEmptySequenceRows": 3, "totalRows": 3}
        payload = run.compute_pitch_sequence_readiness(
            counts, feats, quality, {"2023": quality},
            dataset_authority={"registrationId": "r", "manifestSha": "m"},
            identity_bridge_authority={}, feature_columns=[c for c in feats.columns if c.startswith(("batter_", "pitcher_"))],
        )
        self.assertEqual(payload["terminalStatus"], "PITCH_SEQUENCE_FEATURES_READY")
        self.assertGreater(payload["batterFeatureCount"], 0)
        self.assertGreater(payload["pitcherFeatureCount"], 0)
        self.assertIn("strikeout", payload["strikeoutWalkReadiness"])
        text = repr(payload).lower()
        for forbidden in ("logloss", "brier", "accuracy", "auc", "champion", "challenger_metric"):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
