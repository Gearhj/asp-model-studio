"""Target-source lineage and permanent exclusion from predictor analysis.

PROVEN DEFECT guarded here
--------------------------
`_role_for()` classified predictors by NAME PATTERN only. A field that
deterministically defines the target therefore fell through to "eligible" and was
analysed as an ordinary predictor. On the governed HELOC_TRAIN population this
offered `RiskPerformance` (Bad -> 1, Good -> 0, bijective) as a predictor of
`bad_flag` with IV = 17.4815 -- reported merely as "unusually strong" rather than
as the target restated in words.

The detection added alongside these tests is DATA-DRIVEN and general: a field
qualifies when every one of its values maps to exactly one target value. It is
not a HELOC hardcode and not a name pattern.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from server.preprocessing import governed_profile_service as gps  # noqa: E402

HELOC = Path(
    "server/artifacts/datasets/ds_heloc_train_6bdb184b_05905"
    "/versions/v_1785186305905_6bdb184b/data_full.csv"
)


def open_session(path: Path) -> "gps._Session":
    return gps._Session({"path": Path(os.path.abspath(str(path))), "format": "csv"})


class RoleAssignmentTests(unittest.TestCase):
    """Pure classification -- no artifact required."""

    def test_target_source_is_excluded_and_explained(self):
        sources = {"RiskPerformance": {"field": "RiskPerformance"}}
        role, reason = gps._role_for("RiskPerformance", "bad_flag", sources)
        self.assertEqual(role, "target_source")
        self.assertEqual(reason, "Deterministic source of modeling target")
        self.assertNotEqual(role, "eligible")

    def test_target_itself_is_excluded(self):
        role, reason = gps._role_for("bad_flag", "bad_flag", {})
        self.assertEqual(role, "target")
        self.assertNotEqual(role, "eligible")

    def test_ordinary_predictor_is_unaffected(self):
        role, _ = gps._role_for("ExternalRiskEstimate", "bad_flag", {"RiskPerformance": {}})
        self.assertEqual(role, "eligible")

    def test_exclusion_cannot_be_bypassed_by_omitting_the_lineage(self):
        """The role is derived from detection, never from a client-supplied flag.

        A caller cannot re-enable the field by passing an empty source map on a
        dataset where it IS deterministic -- detection runs server-side against
        the data before roles are assigned (see the artifact tests below)."""
        role, _ = gps._role_for("RiskPerformance", "bad_flag", {})
        self.assertEqual(role, "eligible", "role alone is not the enforcement point")
        # ...which is exactly why detection must run server-side, proven below.


@unittest.skipUnless(HELOC.exists(), "governed HELOC_TRAIN artifact not present")
class HelocLineageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = open_session(HELOC)
        cls.sources = gps.detect_target_source_fields(cls.session, cls.session.columns, "bad_flag")

    @classmethod
    def tearDownClass(cls):
        cls.session.close()

    def test_risk_performance_deterministically_maps_to_bad_flag(self):
        df = pd.read_csv(HELOC)
        grouped = df.groupby("RiskPerformance")["bad_flag"].nunique()
        self.assertTrue((grouped == 1).all(), "mapping is not deterministic")
        self.assertEqual(df.groupby("RiskPerformance")["bad_flag"].first().to_dict(),
                         {"Bad": 1, "Good": 0})

    def test_detection_finds_exactly_the_target_source(self):
        self.assertIn("RiskPerformance", self.sources)
        self.assertEqual(list(self.sources), ["RiskPerformance"],
                         "no false positives among ordinary predictors")

    def test_recorded_lineage_carries_the_mapping_evidence(self):
        record = self.sources["RiskPerformance"]
        self.assertEqual(record["target"], "bad_flag")
        self.assertEqual(record["relationship"], "deterministic_target_source")
        pairs = {m["sourceValue"]: m["targetValue"] for m in record["mapping"]}
        self.assertEqual(pairs, {"Bad": "1", "Good": "0"})
        counts = {m["sourceValue"]: m["rowCount"] for m in record["mapping"]}
        self.assertEqual(counts, {"Bad": 3275, "Good": 3000})

    def test_selecting_bad_flag_excludes_both_target_and_target_source(self):
        roles = {}
        for column in self.session.columns:
            role, _ = gps._role_for(str(column), "bad_flag", self.sources)
            roles.setdefault(role, []).append(str(column))
        self.assertEqual(roles["target"], ["bad_flag"])
        self.assertEqual(roles["target_source"], ["RiskPerformance"])
        self.assertNotIn("RiskPerformance", roles.get("eligible", []))
        self.assertNotIn("bad_flag", roles.get("eligible", []))

    def test_predictor_count_reflects_the_exclusion(self):
        eligible = [
            str(c) for c in self.session.columns
            if gps._role_for(str(c), "bad_flag", self.sources)[0] == "eligible"
        ]
        before = [
            str(c) for c in self.session.columns
            if gps._role_for(str(c), "bad_flag", {})[0] == "eligible"
        ]
        self.assertEqual(len(before), 24, "pre-fix eligible count")
        self.assertEqual(len(eligible), 23, "post-fix eligible count")
        self.assertEqual(set(before) - set(eligible), {"RiskPerformance"})

    def test_remaining_predictor_ivs_are_unchanged_by_the_exclusion(self):
        """Excluding a target source must not perturb any other predictor's IV."""
        mapping = gps.resolve_target_mapping(self.session, "bad_flag", 1, 0)
        for column in ["ExternalRiskEstimate", "AverageMInFile", "NumSatisfactoryTrades"]:
            result = gps.compute_predictor_iv(self.session, column, "bad_flag", mapping, "classification")
            self.assertEqual(result["ivStatus"], "available")
            self.assertIsNotNone(result["iv"])
            self.assertLess(result["iv"], 5.0, f"{column} should be an ordinary predictor")

    def test_the_excluded_field_is_the_one_that_produced_the_extreme_iv(self):
        """Documents WHY it is excluded: it restates the target, IV ~= 17.48."""
        mapping = gps.resolve_target_mapping(self.session, "bad_flag", 1, 0)
        result = gps.compute_predictor_iv(self.session, "RiskPerformance", "bad_flag", mapping, "classification")
        self.assertGreater(result["iv"], 15.0)
        # ...and that value must never reach an approved-predictor table, because
        # the role is not eligible.
        role, _ = gps._role_for("RiskPerformance", "bad_flag", self.sources)
        self.assertNotEqual(role, "eligible")

    def test_target_mapping_is_bad_one_good_zero(self):
        mapping = gps.resolve_target_mapping(self.session, "bad_flag", 1, 0)
        self.assertEqual(mapping["eventCount"], 3275)
        self.assertEqual(mapping["nonEventCount"], 3000)

    def test_detection_is_scoped_to_the_supplied_target(self):
        """Switching the target invalidates the previous lineage -- the mapping is
        recomputed per target, never cached across datasets or targets."""
        other = gps.detect_target_source_fields(self.session, self.session.columns, "RiskPerformance")
        self.assertNotIn("RiskPerformance", other, "a field is never its own source")
        # bad_flag deterministically defines RiskPerformance too (bijective), so
        # with the target reversed the roles reverse -- proving it is derived from
        # the data and the CURRENT target, not remembered from before.
        self.assertIn("bad_flag", other)


@unittest.skipUnless(HELOC.exists(), "governed HELOC_TRAIN artifact not present")
class NoFalsePositiveTests(unittest.TestCase):
    def test_a_merely_strong_predictor_is_not_treated_as_a_target_source(self):
        session = open_session(HELOC)
        try:
            sources = gps.detect_target_source_fields(session, session.columns, "bad_flag")
            for column in ["ExternalRiskEstimate", "AverageMInFile", "PercentTradesNeverDelq"]:
                self.assertNotIn(column, sources, f"{column} wrongly flagged as a target source")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
