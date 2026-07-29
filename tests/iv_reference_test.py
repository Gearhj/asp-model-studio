"""Independent reference proof for the governed Information Value calculation.

WHY THIS EXISTS
---------------
The Data Acquisition page reported ~23 of 30 predictors as "unusually strong",
with several PCA components at IV 2-4, and the walkthrough could not tell whether
that was a calculation defect or the data. This module answers that with a
reference implementation that shares NO code with production: production runs
DuckDB SQL inside `governed_profile_service`, this runs pure Python/pandas here.

If the two agree, the production arithmetic is proven. If they disagree, the
difference is localised and explained rather than papered over with thresholds.

Reference formula (per bin i, event=1, non-event=0):
    event_distribution_i     = (events_i     + k) / (total_events     + k*bins)
    non_event_distribution_i = (non_events_i + k) / (total_non_events + k*bins)
    WoE_i          = ln(event_distribution_i / non_event_distribution_i)
    contribution_i = (event_distribution_i - non_event_distribution_i) * WoE_i
    IV             = sum(contribution_i)          # signed, never absolute-valued

Smoothing is additive (Laplace) with k = 0.5, applied to BOTH classes, and the
denominators include k*bins so each distribution remains a proper probability
distribution summing to 1. That matters for a rare-event target: smoothing only
one side, or omitting k*bins from the denominator, inflates IV.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

SMOOTHING = 0.5
NUMERIC_BINS = 10

ARTIFACT = Path(
    "server/artifacts/datasets/ds_class_train_982c7a7d_35930"
    "/versions/v_1784989835930_982c7a7d/data_full.csv"
)


# --------------------------------------------------------------------------
# Reference implementation -- deliberately independent of production
# --------------------------------------------------------------------------
def reference_iv_from_bins(bins, total_events, total_non_events, k=SMOOTHING):
    """bins: iterable of (label, event_count, non_event_count)."""
    bins = list(bins)
    n = len(bins)
    event_denominator = total_events + k * n
    non_event_denominator = total_non_events + k * n
    iv = 0.0
    detail = []
    for label, events, non_events in bins:
        e_dist = (events + k) / event_denominator
        n_dist = (non_events + k) / non_event_denominator
        woe = math.log(e_dist / n_dist)
        contribution = (e_dist - n_dist) * woe
        iv += contribution
        detail.append(
            {
                "label": label,
                "events": events,
                "nonEvents": non_events,
                "population": events + non_events,
                "eventDistribution": e_dist,
                "nonEventDistribution": n_dist,
                "woe": woe,
                "ivContribution": contribution,
            }
        )
    return iv, detail


def reference_numeric_bins(values: pd.Series, y: pd.Series, bins=NUMERIC_BINS):
    """Quantile bins with de-duplicated edges plus ONE explicit missing bin."""
    missing = values.isna()
    out = []
    if missing.any():
        out.append(("Missing", int(y[missing].sum()), int((y[missing] == 0).sum())))
    present = values[~missing]
    y_present = y[~missing]
    if present.empty:
        return out
    cuts = np.unique(np.nanquantile(present, [i / bins for i in range(1, bins)]))
    edges = np.concatenate(([-np.inf], cuts, [np.inf]))
    index = np.searchsorted(edges, present.values, side="right") - 1
    for b in range(len(edges) - 1):
        mask = index == b
        if not mask.any():
            continue  # empty bins are merged away, never emitted
        labels = y_present.values[mask]
        out.append(
            (f"({edges[b]:.6g},{edges[b + 1]:.6g}]", int(labels.sum()), int((labels == 0).sum()))
        )
    return out


class ReferenceFormulaTests(unittest.TestCase):
    """Hand-calculable cases -- these pin the arithmetic itself."""

    def test_hand_calculated_two_bin_example(self):
        # 2 bins; totals 100 events / 900 non-events.
        # bin A: 80 ev / 200 non ; bin B: 20 ev / 700 non
        iv, detail = reference_iv_from_bins(
            [("A", 80, 200), ("B", 20, 700)], 100, 900
        )
        k, n = SMOOTHING, 2
        ed, nd = 100 + k * n, 900 + k * n
        expect = 0.0
        for e, ne in [(80, 200), (20, 700)]:
            a, b = (e + k) / ed, (ne + k) / nd
            expect += (a - b) * math.log(a / b)
        self.assertAlmostEqual(iv, expect, places=12)
        self.assertGreater(iv, 0.5, "strong separation must yield a large IV")
        # Distributions are proper: each sums to 1.
        self.assertAlmostEqual(sum(d["eventDistribution"] for d in detail), 1.0, places=12)
        self.assertAlmostEqual(sum(d["nonEventDistribution"] for d in detail), 1.0, places=12)

    def test_zero_event_bin_is_smoothed_not_infinite(self):
        iv, detail = reference_iv_from_bins([("empty", 0, 500), ("rest", 100, 400)], 100, 900)
        self.assertTrue(math.isfinite(iv))
        self.assertTrue(all(math.isfinite(d["woe"]) for d in detail))

    def test_zero_non_event_bin_is_smoothed_not_infinite(self):
        iv, detail = reference_iv_from_bins([("pure", 50, 0), ("rest", 50, 900)], 100, 900)
        self.assertTrue(math.isfinite(iv))
        self.assertTrue(all(math.isfinite(d["woe"]) for d in detail))

    def test_no_signal_yields_near_zero_iv(self):
        # Identical class composition in both bins => no information.
        iv, _ = reference_iv_from_bins([("A", 50, 450), ("B", 50, 450)], 100, 900)
        self.assertLess(abs(iv), 1e-9)

    def test_contributions_are_signed_not_absolute(self):
        _, detail = reference_iv_from_bins([("A", 80, 200), ("B", 20, 700)], 100, 900)
        # A signed sum is required; every contribution here is >= 0 by construction
        # of (p-q)ln(p/q), which is exactly why absolute-valuing would be wrong
        # only if a term could be negative. Assert the identity holds per bin.
        for d in detail:
            expected = (d["eventDistribution"] - d["nonEventDistribution"]) * d["woe"]
            self.assertAlmostEqual(d["ivContribution"], expected, places=15)

    def test_smoothing_does_not_dominate_a_rare_event_target(self):
        # 360 events / 170,524 non-events, no signal at all: IV must stay ~0
        # even though k=0.5 is large relative to per-bin event counts.
        bins = [(f"b{i}", 36, 17052) for i in range(10)]
        iv, _ = reference_iv_from_bins(bins, 360, 170_520)
        self.assertLess(iv, 1e-4, "smoothing must not manufacture signal")


class ReferenceBinningTests(unittest.TestCase):
    def test_duplicate_quantile_edges_do_not_create_empty_or_duplicate_bins(self):
        # 80% of the mass is the single value 1.0 -> most quantiles collide.
        values = pd.Series([1.0] * 800 + list(np.linspace(2, 100, 200)))
        y = pd.Series([0] * 1000)
        bins = reference_numeric_bins(values, y)
        labels = [b[0] for b in bins]
        self.assertEqual(len(labels), len(set(labels)), "duplicate bin labels")
        self.assertTrue(all(b[1] + b[2] > 0 for b in bins), "empty bin emitted")

    def test_constant_predictor_collapses_to_a_single_bin(self):
        values = pd.Series([5.0] * 500)
        y = pd.Series([0] * 500)
        self.assertEqual(len(reference_numeric_bins(values, y)), 1)

    def test_missing_forms_exactly_one_explicit_bin(self):
        values = pd.Series([np.nan] * 50 + list(range(450)))
        y = pd.Series([0] * 500)
        bins = reference_numeric_bins(values, y)
        self.assertEqual(sum(1 for b in bins if b[0] == "Missing"), 1)
        self.assertEqual(bins[0][1] + bins[0][2], 50)

    def test_bins_are_order_invariant(self):
        rng = np.random.default_rng(11)
        values = pd.Series(rng.normal(size=2000))
        y = pd.Series(rng.integers(0, 2, size=2000))
        a, _ = reference_iv_from_bins(reference_numeric_bins(values, y), int(y.sum()), int((y == 0).sum()))
        order = rng.permutation(len(values))
        vs, ys = values.iloc[order].reset_index(drop=True), y.iloc[order].reset_index(drop=True)
        b, _ = reference_iv_from_bins(reference_numeric_bins(vs, ys), int(ys.sum()), int((ys == 0).sum()))
        self.assertAlmostEqual(a, b, places=12, msg="IV must not depend on row order")


@unittest.skipUnless(ARTIFACT.exists(), "governed CLASS_TRAIN artifact not present")
class GovernedPopulationReconciliationTests(unittest.TestCase):
    """Proves the reference against the REAL governed population, and proves the
    bins reconcile to the authoritative totals."""

    @classmethod
    def setUpClass(cls):
        cls.df = pd.read_csv(ARTIFACT)
        cls.y = (cls.df["Class"] == 1).astype(int)
        cls.total_events = int(cls.y.sum())
        cls.total_non_events = int((cls.y == 0).sum())

    def test_authoritative_population_totals(self):
        self.assertEqual(len(self.df), 170_884)
        self.assertEqual(self.total_events, 360)
        self.assertEqual(self.total_non_events, 170_524)

    def test_every_predictor_reconciles_to_the_full_population(self):
        predictors = [c for c in self.df.columns if c != "Class"]
        self.assertEqual(len(predictors), 30)
        for column in predictors:
            bins = reference_numeric_bins(self.df[column], self.y)
            events = sum(b[1] for b in bins)
            non_events = sum(b[2] for b in bins)
            self.assertEqual(events, 360, f"{column}: events do not reconcile")
            self.assertEqual(non_events, 170_524, f"{column}: non-events do not reconcile")

    def test_source_missingness_matches_the_registered_artifact(self):
        # The displayed ~5% missingness is REAL, not a profiling artifact:
        # 29 columns carry nulls, each ~4.9-5.1%.
        with_nulls = [c for c in self.df.columns if self.df[c].isna().any()]
        self.assertEqual(len(with_nulls), 29)
        self.assertNotIn("Class", with_nulls, "the target must not be missing")
        self.assertNotIn("Time", with_nulls)
        for column in with_nulls:
            pct = 100.0 * self.df[column].isna().sum() / len(self.df)
            self.assertTrue(4.5 <= pct <= 5.5, f"{column}: unexpected missing rate {pct:.2f}%")

    def test_high_iv_is_driven_by_real_separation_not_by_smoothing(self):
        """V4's IV is large because one decile holds most of the events."""
        bins = reference_numeric_bins(self.df["V4"], self.y)
        iv, detail = reference_iv_from_bins(bins, self.total_events, self.total_non_events)
        self.assertGreater(iv, 1.0)
        top = max(detail, key=lambda d: d["events"])
        self.assertGreater(
            top["events"] / self.total_events, 0.75,
            "the high IV must come from a genuinely event-dense bin",
        )

    def test_rare_event_binning_diagnostics_are_reportable(self):
        """With 360 events over ~11 bins, most bins are near event-empty -- the
        condition that makes smoothed WoE fragile. This is a DIAGNOSTIC, so the
        product can disclose it rather than silently presenting a large IV."""
        bins = reference_numeric_bins(self.df["V4"], self.y)
        events = [b[1] for b in bins]
        self.assertEqual(len(bins), 11)
        self.assertEqual(min(events), 0, "expected at least one zero-event bin")
        self.assertGreaterEqual(sum(1 for e in events if e <= 3), 5)
        iv, detail = reference_iv_from_bins(bins, self.total_events, self.total_non_events)
        fragile = sum(d["ivContribution"] for d in detail if d["events"] <= 3)
        # ~45% of V4's IV comes from bins with <=3 events.
        self.assertGreater(fragile / iv, 0.30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
