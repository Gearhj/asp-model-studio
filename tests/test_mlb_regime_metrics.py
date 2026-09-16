"""Focused synthetic verification of paired contribution/interval accounting."""
import json

import numpy as np
import pandas as pd
import pytest

from server.sports_current_statcast.mlb_regime_metrics import metric_contributions, paired_uncertainty, predictive_metrics


def test_exact_metrics_grouped_pairing_and_explicit_missing_inference():
    y = np.tile(np.arange(8), 32)
    baseline = np.full((len(y), 8), 0.1)
    baseline[np.arange(len(y)), y] = 0.3
    candidate = np.full((len(y), 8), 0.65 / 7)
    candidate[np.arange(len(y)), y] = 0.35
    original = baseline.copy()
    contributions = metric_contributions(y, baseline)
    assert np.allclose(contributions["logLoss"], -np.log(0.3), atol=1e-14)
    assert np.allclose(contributions["brier"], 0.56, atol=1e-14)
    assert np.allclose(contributions["calibrationResidual"].sum(axis=1), 0.0, atol=1e-14)
    metrics = predictive_metrics(y, baseline)
    assert metrics["logLoss"] == pytest.approx(-np.log(0.3))
    assert metrics["brier"] == pytest.approx(0.56)
    assert len(metrics["perClass"]) == 8 and metrics["rareClass"] == []
    assert all(sum(bin_["observations"] for bin_ in row["reliability"]) == len(y) for row in metrics["perClass"])
    assert all(row["calibration"]["status"] == "UNDEFINED_SEPARATION_OR_SINGULAR_INFORMATION" for row in metrics["perClass"])
    np.testing.assert_array_equal(baseline, original)
    constant = predictive_metrics(y, np.full((len(y), 8), 1 / 8))
    assert all(row["calibration"]["slope"] is None for row in constant["perClass"])
    assert metric_contributions(y, np.eye(8)[y])["brier"].sum() == 0
    # Known one-vs-rest calibration curve: both orientation and coefficient scale.
    logits = np.linspace(-2, 2, 9)
    probability = 1 / (1 + np.exp(-logits))
    counts = np.round(1000 / (1 + np.exp(-(0.2 + 0.8 * logits)))).astype(int)
    calibration_y = np.concatenate([np.r_[np.zeros(count, dtype=int), np.ones(1000 - count, dtype=int)] for count in counts])
    calibration_p = np.zeros((9000, 8))
    calibration_p[:, 0] = np.repeat(probability, 1000)
    calibration_p[:, 1] = 1 - calibration_p[:, 0]
    known = predictive_metrics(calibration_y, calibration_p)["perClass"][0]["calibration"]
    assert known["status"] == "ESTIMATED"
    assert known["intercept"] == pytest.approx(0.2, abs=0.004)
    assert known["slope"] == pytest.approx(0.8, abs=0.004)

    game = np.arange(len(y)) // 4
    frame = pd.DataFrame({"canonicalGameId": game, "game_date": pd.Timestamp("2024-01-01") + pd.to_timedelta(game * 2, unit="D"),
                          "batterCanonicalPlayerId": np.arange(len(y)) % 13,
                          "pitcherCanonicalPlayerId": (np.arange(len(y)) % 7).astype(float),
                          "battingTeamId": game % 4})
    frame.loc[0, "pitcherCanonicalPlayerId"] = np.nan
    paired = paired_uncertainty(frame, y, baseline, candidate, replicates=64)
    assert paired == paired_uncertainty(frame, y, baseline, candidate, replicates=64)
    expected = float(-np.log(0.35) + np.log(0.3))
    assert paired["estimate"]["logLoss"] == pytest.approx(expected)
    assert paired["games"] == 64 and paired["dates"] == 64 and paired["observations"] == 256
    for method in ("gameClusterBootstrap", "calendarWeekBlockBootstrap"):
        assert paired[method]["status"] == "AVAILABLE"
        assert paired[method]["intervals"]["logLoss"]["lower"] == pytest.approx(expected)
        assert paired[method]["intervals"]["logLoss"]["upper"] == pytest.approx(expected)
    assert paired["repeatedIdentitySensitivity"]["pitcherCanonicalPlayerId"]["excludedObservations"] == 1
    assert paired["repeatedIdentitySensitivity"]["fieldingTeamId"]["status"] == "UNAVAILABLE_IDENTITY_FIELD"
    short = paired_uncertainty(frame.iloc[:16], y[:16], baseline[:16], candidate[:16], replicates=32)
    assert short["calendarWeekBlockBootstrap"]["status"] == "INSUFFICIENT_TEMPORAL_BLOCKS"
    json.dumps({"metrics": metrics, "paired": paired, "short": short}, allow_nan=False)
    with pytest.raises(ValueError, match="Complete canonicalGameId"):
        paired_uncertainty(frame.drop(columns=["canonicalGameId"]), y, baseline, candidate, replicates=32)
    invalid = frame.copy()
    invalid.loc[0, "game_date"] += pd.Timedelta(days=1)
    with pytest.raises(ValueError, match="conflicting calendar dates"):
        paired_uncertainty(invalid, y, baseline, candidate, replicates=32)
