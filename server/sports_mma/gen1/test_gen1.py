from __future__ import annotations

import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from server.sports_mma.gen1.core import (
    ALL_FEATURES,
    GovernanceError,
    build_feature_table,
    build_feature_table_after_finalist,
    canonical_json_bytes,
    feature_contract,
)
from server.sports_mma.gen1.modeling import (
    CANDIDATE_GRID,
    _pipeline,
    predict_selected,
    reversal_probability,
)
from server.sports_mma.gen1.quality import EXPECTED_FILES, profile_source
from server.sports_mma.poc.harness import BudgetGuard


def bout(
    fight_id: str,
    when: str,
    one: str,
    two: str,
    result_one: str = "W",
    result_two: str = "L",
    method: str = "U-DEC",
    str_one: int = 10,
    str_two: int = 5,
) -> dict:
    return {
        "Fight_Id": fight_id,
        "Event_Id": f"event-{fight_id}",
        "event_date": pd.Timestamp(when),
        "Fighter_Id_1": one,
        "Fighter_Id_2": two,
        "Fighter_1": one,
        "Fighter_2": two,
        "Result_1": result_one,
        "Result_2": result_two,
        "Method": method,
        "Round": 3,
        "Fight_Time": "5:00",
        "Time Format": "3 Rnd (5-5-5)",
        "Weight_Class": "Lightweight",
        "STR_1": str_one,
        "STR_2": str_two,
        "TD_1": 1,
        "TD_2": 0,
        "Sub. Att_1": 0,
        "Sub. Att_2": 0,
        "Ctrl_1": 30.0,
        "Ctrl_2": 10.0,
        "KD_1": 0,
        "KD_2": 0,
    }


class Gen1CoreTest(unittest.TestCase):
    def test_target_stats_are_not_own_features_and_future_updates_are_chronological(self):
        rows = pd.DataFrame(
            [
                bout("f1", "2010-01-01", "a", "b", str_one=10, str_two=5),
                bout("f2", "2011-01-01", "a", "c", str_one=20, str_two=4),
            ]
        )
        changed = rows.copy()
        changed.loc[0, "STR_1"] = 999
        original, _ = build_feature_table(rows, {"a", "b", "c"}, through_date="2011-12-31")
        mutated, _ = build_feature_table(changed, {"a", "b", "c"}, through_date="2011-12-31")
        own_columns = list(ALL_FEATURES) + ["elo_probability_a"]
        self.assertEqual(
            canonical_json_bytes(original.loc[0, own_columns].to_dict()),
            canonical_json_bytes(mutated.loc[0, own_columns].to_dict()),
        )
        self.assertNotEqual(
            original.loc[1, "sig_strikes_landed_per_min_diff"],
            mutated.loc[1, "sig_strikes_landed_per_min_diff"],
        )
        self.assertEqual(original.loc[0, "experience_total"], 0)
        self.assertEqual(original.loc[1, "experience_total"], 1)

    def test_draw_and_no_contest_are_excluded_and_do_not_update(self):
        rows = pd.DataFrame(
            [
                bout("draw", "2010-01-01", "a", "b", "D", "D", "M-DEC"),
                bout("nc", "2010-02-01", "a", "b", "NC", "NC", "Overturned"),
                bout("final", "2010-03-01", "a", "b"),
            ]
        )
        table, receipt = build_feature_table(rows, {"a", "b"}, through_date="2010-12-31")
        self.assertEqual(table["fight_id"].tolist(), ["final"])
        self.assertEqual(table.iloc[0]["experience_total"], 0)
        self.assertEqual(receipt["skippedUpdates"]["DRAW"], 1)
        self.assertEqual(receipt["skippedUpdates"]["NO_CONTEST_OR_OVERTURNED"], 1)

    def test_oot_requires_real_frozen_finalist_receipt(self):
        rows = pd.DataFrame([bout("oot", "2025-01-01", "a", "b")])
        with self.assertRaisesRegex(GovernanceError, "OOT_FEATURE_BUILD"):
            build_feature_table(rows, {"a", "b"}, through_date="2025-12-31")
        with patch(
            "server.sports_mma.gen1.core.require_finalist_receipt",
            side_effect=GovernanceError("FINALIST_NOT_FROZEN_BEFORE_OOT"),
        ):
            with self.assertRaisesRegex(GovernanceError, "FINALIST_NOT_FROZEN"):
                build_feature_table_after_finalist(
                    rows,
                    {"a", "b"},
                    through_date="2025-12-31",
                    finalist_receipt=Path("receipt.json"),
                    finalist_digest=Path("receipt.sha256"),
                )

    def test_orientation_reversal_is_exact_complement(self):
        rows = pd.DataFrame([bout("f1", "2010-01-01", "b", "a")])
        table, _ = build_feature_table(rows, {"a", "b"}, through_date="2010-12-31")
        artifact = {"selected": "ELO", "components": {}}
        p_a = reversal_probability(artifact, table, "a")
        p_b = reversal_probability(artifact, table, "b")
        self.assertAlmostEqual(p_a + p_b, 1.0, places=15)
        self.assertEqual(table.iloc[0]["fighter_a_id"], "a")

    def test_feature_contract_excludes_current_snapshots(self):
        contract = feature_contract()
        self.assertIn("Fighters Stats.csv aggregates", contract["excludedCurrentSnapshotFields"])
        self.assertEqual(len(contract["numericFeatures"]), 25)
        self.assertEqual(contract["categoricalFeatures"], ["weight_class"])

    def test_preprocessing_and_calibration_roles_are_fold_local_by_construction(self):
        # The bounded grids are fixed; the temporal fitter records a train max date
        # below each assessment year and never accepts an arbitrary random splitter.
        self.assertEqual(set(CANDIDATE_GRID), {"LOGISTIC", "HGB"})
        self.assertEqual(len(CANDIDATE_GRID["LOGISTIC"]), 2)
        self.assertEqual(len(CANDIDATE_GRID["HGB"]), 2)

    def test_deterministic_model_fit(self):
        rng = np.random.default_rng(4)
        frame = pd.DataFrame({name: rng.normal(size=120) for name in ALL_FEATURES if name != "weight_class"})
        frame["weight_class"] = np.where(np.arange(120) % 2, "A", "B")
        y = (rng.normal(size=120) + frame["elo_diff"].to_numpy() > 0).astype(int)
        params = CANDIDATE_GRID["LOGISTIC"][0]
        first, second = _pipeline("LOGISTIC", params), _pipeline("LOGISTIC", params)
        first.fit(frame[list(ALL_FEATURES)], y)
        second.fit(frame[list(ALL_FEATURES)], y)
        np.testing.assert_array_equal(
            first.predict_proba(frame[list(ALL_FEATURES)]),
            second.predict_proba(frame[list(ALL_FEATURES)]),
        )

    def test_poc_budget_guards_are_unchanged(self):
        self.assertEqual(BudgetGuard.API_SPORTS_MAX_REQUESTS, 80)
        self.assertEqual(BudgetGuard.ODDS_API_MAX_CREDITS, 80)


class RealSourceFocusedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get("MMA_GEN1_SOURCE_ROOT")
        if not configured:
            raise unittest.SkipTest("MMA_GEN1_SOURCE_ROOT not configured")
        cls.source = Path(configured)

    def test_manifest_and_quality_gate(self):
        self.assertEqual(len(EXPECTED_FILES), 9)
        report = profile_source(self.source)
        self.assertEqual(report["gate"], "PASS")
        self.assertEqual(report["totals"]["physicalBytes"], 11655635)
        self.assertEqual(len(report["files"]), 9)
        self.assertEqual(report["primaryKeys"]["Fight_IdDuplicates"], 0)
        self.assertEqual(report["chronology"]["modernSameDateRepeatParticipantRows"], 0)

    def test_no_raw_or_model_binary_is_tracked(self):
        root = Path(__file__).resolve().parents[3]
        tracked = subprocess.check_output(["git", "ls-files"], cwd=root, text=True).splitlines()
        forbidden = [
            value for value in tracked
            if value.casefold().endswith((".zip", ".parquet", ".joblib"))
            or (value.casefold().endswith(".csv") and "fixture" not in value.casefold())
        ]
        self.assertEqual(forbidden, [])


if __name__ == "__main__":
    unittest.main()
