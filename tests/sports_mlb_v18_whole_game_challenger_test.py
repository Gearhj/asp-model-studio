"""Essential, bounded checks for the V18 whole-game challenger handoff."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5 import base_out_transition as bt
from server.sports_current_statcast.mlb_v18_whole_game_challenger import (
    STATE_FEATURES,
    V18StateProbabilityProvider,
    apply_temperature,
    simulate_prospective_game,
    starter_removal_probability,
)


ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "outputs/mlb-v18-whole-game-challenger/latest.json"


class _FixedProvider:
    def __init__(self) -> None:
        self.vector = np.array([0.225, 0.085, 0.033, 0.140, 0.045, 0.005, 0.440, 0.027])
        self.vector /= self.vector.sum()

    def probabilities(self, **state) -> np.ndarray:
        return np.repeat(self.vector[None, :], len(state["top"]), axis=0)


def _tiny_transition_model() -> bt.TransitionModel:
    records = [
        {
            "pa_outcome": outcome,
            "outs_before": 0,
            "base_mask_before": 0,
            "outs_after": 1,
            "base_mask_after": 0,
            "runs_scored": 0,
            "season": 2021,
        }
        for outcome in bt.PA_CLASSES
    ]
    return bt.fit(records, alpha=0.5, min_cell=1, seasons=(2021,))


def _bundle() -> tuple[Path, dict]:
    pointer = json.loads(LATEST.read_text(encoding="utf-8"))
    bundle = ROOT / pointer["relativePath"]
    return bundle, json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))


def test_temperature_and_starter_hook_contracts() -> None:
    probabilities = np.array([[0.4, 0.2, 0.1, 0.1, 0.05, 0.05, 0.05, 0.05]])
    assert np.allclose(apply_temperature(probabilities, 1.0), probabilities)
    assert np.allclose(apply_temperature(probabilities, 1.7).sum(axis=1), 1.0)
    early = starter_removal_probability(
        np.array([8]), np.array([8]), np.array([8]), np.array([3])
    )
    worsening = starter_removal_probability(
        np.array([5, 7, 7]), np.array([18, 18, 18]),
        np.array([1, 1, 4]), np.array([2, 2, 2]),
    )
    assert early[0] == 0.0
    assert worsening[0] < worsening[1] < worsening[2]


def test_provider_cache_preserves_exact_one_row_wrapper_semantics() -> None:
    class Encoder:
        def transform(self, frame):
            return frame.to_numpy(dtype=float)

    class Estimator:
        classes_ = np.arange(8)

        def predict_proba(self, values):
            score = np.asarray(values)[:, 0]
            result = np.full((len(score), 8), 0.1)
            result[:, 0] = 0.2 + score * 0.01
            return result / result.sum(axis=1, keepdims=True)

    class Preprocessor:
        def __init__(self, order):
            self.ordered_features = tuple(order)
            self.encoder = Encoder()
            self.batch_calls = 0

        def transform_frame(self, frame):
            result = frame.loc[:, list(self.ordered_features)].astype(float).copy()
            if len(result) > 1:
                self.batch_calls += 1
                result["batter_avg"] = np.nextafter(result["batter_avg"], -np.inf)
            return result

    class Pipeline:
        def __init__(self, order):
            self.ordered_features = tuple(order)
            self.preprocessor = Preprocessor(order)
            self.estimator = Estimator()

        def predict_proba(self, frame):
            treated = self.preprocessor.transform_frame(frame)
            return self.estimator.predict_proba(self.preprocessor.encoder.transform(treated))

    order = ["batter_avg", *STATE_FEATURES]
    order.extend(f"batter_feature_{index}" for index in range(246 - len(order)))
    row = {name: 0.0 for name in order}
    row["batter_avg"] = 0.24383965130415958
    pipeline = Pipeline(order)
    V18StateProbabilityProvider(
        pipeline=pipeline,
        away_batters=[row] * 9,
        home_batters=[row] * 9,
        away_starter={},
        home_starter={},
        away_bullpen=[{}],
        home_bullpen=[{}],
    )
    assert pipeline.preprocessor.batch_calls == 0


def test_sequential_paths_are_legal_terminated_and_deterministic() -> None:
    kwargs = dict(
        game_id="v18-essential-fixture",
        provider=_FixedProvider(),
        transition_model=_tiny_transition_model(),
        n_sims=128,
        master_seed=20260907,
        trace_count=1,
    )
    first = simulate_prospective_game(**kwargs)
    second = simulate_prospective_game(**kwargs)
    for name in ("awayRuns", "homeRuns", "innings", "paCounts"):
        assert np.array_equal(first[name], second[name])
    assert first["traces"] == second["traces"]
    assert first["nonterminationCount"] == 0
    assert first["illegalStateCount"] == 0
    assert np.all(first["awayRuns"] != first["homeRuns"])
    assert first["traces"] and first["traces"][0]


def test_content_addressed_bundle_schema_and_pregame_boundary() -> None:
    bundle, manifest = _bundle()
    body = {key: value for key, value in manifest.items() if key not in {"bundleId", "bundleSha256"}}
    assert hashlib.sha256(canonical_json_bytes(body)).hexdigest() == manifest["bundleSha256"]
    for artifact in manifest["artifacts"]:
        raw = (bundle / artifact["relativePath"]).read_bytes()
        assert len(raw) == artifact["bytes"]
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]

    verification = json.loads((bundle / "template-verification.json").read_text(encoding="utf-8"))
    raw = pq.read_table(bundle / "prospective-raw-246.parquet")
    treated = pq.read_table(bundle / "prospective-treated-273.parquet")
    assert raw.shape == (18, 248)  # two non-model template identity columns plus 246 raw inputs
    assert treated.shape == (18, 273)
    assert len(verification["folds"]) == 5
    assert all(row["treatedInputs"] == 273 for row in verification["folds"])
    assert all(abs(row["probabilitySum"] - 1.0) < 1e-12 for row in verification["folds"])

    snapshot = json.loads((bundle / "aisp-pregame-snapshot.json").read_text(encoding="utf-8"))
    captured = datetime.fromisoformat(snapshot["capturedAt"])
    starts = datetime.fromisoformat(snapshot["game"]["starts_at"])
    handoff = json.loads((bundle / "aisp-handoff.json").read_text(encoding="utf-8"))
    assert captured < starts
    assert snapshot["outcomesRead"] is False
    assert snapshot["aispRowsModified"] == 0
    assert manifest["finalOot"] == {
        "locked": True, "featurePayloadRowsRead": 0, "targetsRead": 0, "scored": False,
    }
    assert manifest["aisp"]["modified"] is False
    assert handoff["status"] == "RESEARCH_SHADOW"
    assert handoff["executionAllowed"] is False
    assert handoff["wageringAuthority"] is False
    assert manifest["featureContract"]["treatedInputs"] == 273
    assert len(PA_CLASS_ORDER) == 8
