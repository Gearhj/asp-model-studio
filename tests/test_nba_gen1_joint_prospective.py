"""Focused distribution-contract checks; no source acquisition or game outcomes."""
import numpy as np

from scripts.publish_nba_gen1_joint_prospective import interval, pmf, summarize


def sample():
    # Complete untied integer HOME/AWAY finals with both winner directions.
    base = np.array([[110, 108], [111, 108], [107, 109], [114, 109],
                     [105, 106], [118, 112], [100, 103], [120, 115]])
    return np.tile(base, (1250, 1))


def test_summary_reconciles_mass_intervals_and_totals_queries():
    value = summarize(sample())
    assert value["drawCount"] == 10_000
    assert value["winnerProbabilities"]["tie"] == 0
    assert value["winnerProbabilities"]["homeDET"] + value["winnerProbabilities"]["awayBOS"] == 1
    for distribution in value["pmfs"].values():
        assert sum(x["count"] for x in distribution) == 10_000
        assert sum(x["probability"] for x in distribution) == 1
    for query in value["illustrativeTotals"]:
        assert query["over"]["win"] + query["over"]["push"] + query["over"]["loss"] == 1
        assert query["under"]["win"] == query["over"]["loss"]


def test_exact_winner_and_total_preservation_is_visible_to_summary():
    baseline = sample()
    changed = baseline.copy()
    changed[0] = [111, 107]
    changed[1] = [112, 107]
    changed[2] = [106, 110]
    assert np.array_equal(baseline.sum(axis=1), changed.sum(axis=1))
    assert np.array_equal(baseline[:, 0] > baseline[:, 1], changed[:, 0] > changed[:, 1])
    left, right = summarize(baseline), summarize(changed)
    assert left["winnerProbabilities"] == right["winnerProbabilities"]
    assert left["pmfs"]["total"] == right["pmfs"]["total"]
    assert left["illustrativeTotals"] == right["illustrativeTotals"]


def test_pmf_and_interval_are_integer_and_counted():
    values = np.array([1, 1, 2, 4])
    assert pmf(values) == [{"value": 1, "count": 2, "probability": .5},
                           {"value": 2, "count": 1, "probability": .25},
                           {"value": 4, "count": 1, "probability": .25}]
    result = interval(values, 80)
    assert result["lower"] == 1 and result["upper"] == 4
