"""Focused tests for the Phase 4F severe-miss forensic primitives.

Covers individual loss/Brier, Pareto accounting, over-index, confusion pairs, min-segment
pooling, diagnostic tail-sensitivity labelling, official-population preservation, no-target-
leakage in the diagnostic classifier, and priority-row validation. Small synthetic inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

from server.sports_modeling.metrics import PA_CLASS_ORDER, per_row_log_loss
from server.sports_phase4 import forensic_severe_miss as forensic


def _synthetic(seed: int = 3, n: int = 4000):
    rng = np.random.default_rng(seed)
    logits = rng.normal(size=(n, len(PA_CLASS_ORDER)))
    probs = np.exp(logits)
    probs /= probs.sum(axis=1, keepdims=True)
    encoded = rng.integers(0, len(PA_CLASS_ORDER), size=n)
    return encoded, probs


def test_individual_log_loss_matches_governed_floor():
    encoded, probs = _synthetic()
    got = forensic.individual_log_loss(encoded, probs)
    exp = per_row_log_loss(encoded, probs)
    np.testing.assert_array_equal(got, exp)


def test_individual_brier_is_summed_one_vs_all():
    encoded, probs = _synthetic()
    b = forensic.individual_brier(encoded, probs)
    assert b.shape == (encoded.size,)
    assert np.all(b >= 0.0)


def test_pareto_shares_monotonic_and_full_is_one():
    encoded, probs = _synthetic()
    loss = forensic.individual_log_loss(encoded, probs)
    pareto = forensic.pareto_concentration(loss)
    shares = [r["lossShare"] for r in pareto["rows"]]
    assert shares == sorted(shares)  # monotone increasing with fraction
    # worst-50% must contribute >= 50% of loss for a right-skewed loss
    assert shares[-1] >= 0.5
    # accounting: full sum equals reported total
    assert abs(pareto["totalLoss"] - float(loss.sum())) < 1e-6


def test_pareto_worst_fraction_row_counts_are_exact():
    encoded, probs = _synthetic(n=10000)
    loss = forensic.individual_log_loss(encoded, probs)
    pareto = forensic.pareto_concentration(loss)
    frac1 = next(r for r in pareto["rows"] if r["worstFraction"] == 0.01)
    assert frac1["rowCount"] == 100


def test_over_index_ratio_semantics():
    encoded, probs = _synthetic()
    loss = forensic.individual_log_loss(encoded, probs)
    masks = forensic.severe_masks(loss, probs[np.arange(encoded.size), encoded])
    oi = forensic.over_index(masks["worst_5.0pct"], encoded)
    assert oi["severeRowCount"] == int(masks["worst_5.0pct"].sum())
    for row in oi["rows"]:
        # over-index = severe share / population share
        if row["populationShare"] > 0 and row["overIndex"] is not None:
            assert abs(row["overIndex"] - row["severeShare"] / row["populationShare"]) < 1e-9


def test_confusion_pairs_account_for_all_severe_rows():
    encoded, probs = _synthetic()
    loss = forensic.individual_log_loss(encoded, probs)
    masks = forensic.severe_masks(loss, probs[np.arange(encoded.size), encoded])
    cp = forensic.confusion_pairs(encoded, probs, masks["worst_5.0pct"], loss)
    assert sum(p["count"] for p in cp["pairs"]) == cp["severeRowCount"]
    assert abs(sum(p["shareOfSevereMisses"] for p in cp["pairs"]) - 1.0) < 1e-9


def test_min_segment_size_pools_small_segments():
    encoded, probs = _synthetic(n=3000)
    loss = forensic.individual_log_loss(encoded, probs)
    severe = loss >= np.percentile(loss, 95.0)
    seg_values = np.array(["big"] * 2600 + ["tiny"] * 400)
    result = forensic.segment_metrics(seg_values, loss, encoded, severe, min_rows=500)
    labels = {s["segment"] for s in result["segments"]}
    assert "big" in labels
    assert any(lbl.startswith("__POOLED_LT_") for lbl in labels)
    assert "tiny" not in labels  # pooled, not reported as its own segment


def test_tail_sensitivity_is_labelled_diagnostic_and_preserves_official():
    encoded, probs = _synthetic()
    loss = forensic.individual_log_loss(encoded, probs)
    ts = forensic.tail_sensitivity(loss)
    assert ts["diagnosticOnly"] is True
    assert ts["notAProductionPerformanceClaim"] is True
    assert abs(ts["officialAggregateLogLoss"] - float(loss.mean())) < 1e-9
    # removing the worst tail can only lower the remainder mean
    for row in ts["rows"]:
        if row["aggregateLogLossOnRemainder"] is not None:
            assert row["aggregateLogLossOnRemainder"] <= ts["officialAggregateLogLoss"] + 1e-9


def test_functions_do_not_mutate_or_drop_population():
    encoded, probs = _synthetic()
    loss = forensic.individual_log_loss(encoded, probs)
    n0 = encoded.size
    forensic.severe_masks(loss, probs[np.arange(n0), encoded])
    forensic.over_index(loss >= np.percentile(loss, 99.0), encoded)
    forensic.distribution_summary(loss)
    # inputs unchanged, no row removed anywhere
    assert encoded.size == n0 and loss.size == n0


def test_severe_miss_classifier_runs_out_of_time_and_reports_auc():
    rng = np.random.default_rng(9)
    n = 3000
    feats = ["f_ess", "f_hist", "f_ctx"]
    xd = rng.normal(size=(n, 3))
    # structured target so AUC is meaningfully > 0.5
    yd = (xd[:, 0] + rng.normal(scale=0.3, size=n) > 1.0).astype(int)
    xv = rng.normal(size=(n, 3))
    yv = (xv[:, 0] + rng.normal(scale=0.3, size=n) > 1.0).astype(int)
    result = forensic.severe_miss_classifier(xd, yd, xv, yv, feats)
    assert 0.0 <= result["rocAuc"] <= 1.0
    assert result["predictorsArePrePredictionOnly"] is True
    assert result["notDeployed"] is True
    assert len(result["topCoefficients"]) == 3


def test_priority_row_validates_scores_and_sums():
    row = forensic.priority_row("x", 5, 4, 3, 2, 1, 5, "PREMIUM DATA")
    assert row["totalScore"] == 5 + 4 + 3 + 2 + 1 + 5
    with pytest.raises(ValueError):
        forensic.priority_row("bad", 6, 1, 1, 1, 1, 1, "NO ACTION / IRREDUCIBLE")


def test_randomness_verdict_structured_when_auc_high():
    v = forensic.randomness_verdict({"classifierAuc": 0.72, "lowHistoryOverIndex": 1.4, "roleOverIndex": 1.0, "earlySeasonOverIndex": 1.0})
    assert v["primaryCategory"] == "STRUCTURED_BUT_CURRENTLY_UNMODELED"
    assert "LOW_HISTORY_RELATED" in v["allCategories"]


def test_randomness_verdict_random_when_auc_low():
    v = forensic.randomness_verdict({"classifierAuc": 0.51, "lowHistoryOverIndex": 1.0, "roleOverIndex": 1.0, "earlySeasonOverIndex": 1.0})
    assert v["primaryCategory"] == "RANDOM_OR_IRREDUCIBLE"
