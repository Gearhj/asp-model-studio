from datetime import datetime, timedelta, timezone

import joblib
import numpy as np
import pandas as pd

from server.market_intelligence.research_models import _prepare, run_research


def test_research_keeps_events_atomic_target_times_safe_and_reloads_artifact(tmp_path):
    checkpoints = []
    first = datetime(2024, 1, 1, 20, tzinfo=timezone.utc)
    for i in range(60):
        start = first+timedelta(days=i)
        cutoff = start-timedelta(hours=1)
        p = .45+.02*(i % 5)
        row = {"event_id": f"game-{i:03d}", "event_start": start.isoformat(), "checkpoint": "60m",
               "book_count": 2, "period": "full_game",
               "checkpoint_at": cutoff.isoformat(), "consensus_probability": p,
               "model_probability": p+(.04 if i % 2 else -.04), "model_probability_pit_valid": True,
               "model_available_at": cutoff.isoformat(),
               "target_home_win": i % 2, "target_available_at": (start+timedelta(hours=4)).isoformat(),
               "movement": .005*(i % 3), "dispersion": .01+.001*(i % 4),
               "signal_available_at": {"movement": cutoff.isoformat(), "dispersion": cutoff.isoformat(),
                                       "velocity": (cutoff+timedelta(minutes=1)).isoformat()},
               "velocity": 999.0,
               "next_probability": p+.005, "next_at": (start-timedelta(minutes=30)).isoformat(),
               "closing_probability": p+(.08 if i % 4 == 1 else .01), "closing_at": (start-timedelta(minutes=5)).isoformat()}
        checkpoints.extend([row, {**row, "checkpoint": "5m", "checkpoint_at": (start-timedelta(minutes=5)).isoformat()}])
    missing_clock = {**checkpoints[0], "model_available_at": None}
    prepared, _ = _prepare([missing_clock])
    assert np.isnan(prepared.iloc[0].model_probability)
    _, excluded = _prepare([{**checkpoints[0], "event_start": "2026-08-20T20:00:00+00:00",
                             "checkpoint_at": "2026-08-20T19:00:00+00:00"}])
    assert excluded[0]["reason"] == "SEALED_FINAL_OOT"
    result = run_research(checkpoints, tmp_path)
    assert result["gates"]["home_win"]["uniqueEligibleEvents"] == 60
    assert result["actualEstimatorFitStarts"] == result["completedEstimatorFits"]
    assert result["artifacts"] and not result["failures"]
    for model in result["models"]:
        for fold in model.get("folds", []):
            assert set(fold["trainingEvents"]).isdisjoint(fold["validationEvents"])
            assert pd.Timestamp(fold["maximumTrainingTargetAvailableAt"]) <= pd.Timestamp(fold["trainingCutoff"])
    artifact_ref = result["artifacts"][0]
    artifact = joblib.load(artifact_ref["path"])
    import json
    fixture = json.loads(open(artifact_ref["reloadFixture"]["path"], encoding="utf-8").read())
    np.testing.assert_allclose(artifact.predict(pd.DataFrame(fixture["rows"])), fixture["expectedPredictions"], atol=1e-12, rtol=0)
    assert all(item["maximumAbsoluteReloadDifference"] == 0 for item in result["artifacts"])
    movement = next(m for m in result["models"] if m["model"] == "MARKET_PLUS_MOVEMENT_DISPERSION")
    assert all(f["supportedSignalCountsTraining"]["velocity"] == 0 for f in movement["folds"])
    assert all(m["uncertainty"]["status"] == "INSUFFICIENT_TEMPORAL_BLOCKS" for m in result["models"] if "uncertainty" in m and m["target"] == "home_win")
