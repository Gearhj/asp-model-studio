"""Research-only calibration and invocation helpers for the MLB V18 release candidate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression

from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


CALIBRATION_FLOOR = 1e-15


def _log_probabilities(probabilities: Any) -> np.ndarray:
    values = validate_probability_matrix(probabilities, class_order=PA_CLASS_ORDER)
    return np.log(np.clip(values, CALIBRATION_FLOOR, 1.0))


@dataclass
class TemperatureCalibrator:
    """One-parameter confidence calibration that preserves class ranking."""

    temperature: float = 1.0
    method: str = "TEMPERATURE_SCALING"
    class_order: tuple[str, ...] = PA_CLASS_ORDER
    fit_metadata: dict[str, Any] = field(default_factory=dict)

    def fit(self, probabilities: Any, labels: Any) -> "TemperatureCalibrator":
        p = validate_probability_matrix(probabilities, class_order=self.class_order)
        y = np.asarray(labels, dtype=np.int64)
        if y.shape != (len(p),) or np.any(y < 0) or np.any(y >= len(self.class_order)):
            raise ValueError("Temperature calibration labels are invalid")

        def objective(value: float) -> float:
            q = self._transform(p, value)
            return float(-np.log(np.clip(q[np.arange(len(y)), y], CALIBRATION_FLOOR, 1.0)).mean())

        result = minimize_scalar(objective, bounds=(0.5, 2.0), method="bounded", options={"xatol": 1e-10})
        if not result.success:
            raise ValueError("Temperature calibration did not converge")
        self.temperature = float(result.x)
        self.fit_metadata = {
            "optimizer": "scipy.optimize.minimize_scalar bounded",
            "bounds": [0.5, 2.0],
            "iterations": int(result.nfev),
            "fitRows": int(len(p)),
            "objective": "mean eight-class log loss",
        }
        return self

    @staticmethod
    def _transform(probabilities: np.ndarray, temperature: float) -> np.ndarray:
        if not math.isfinite(temperature) or temperature <= 0:
            raise ValueError("Temperature must be finite and positive")
        logits = np.log(np.clip(probabilities, CALIBRATION_FLOOR, 1.0)) / temperature
        logits -= logits.max(axis=1, keepdims=True)
        result = np.exp(logits)
        return result / result.sum(axis=1, keepdims=True)

    def transform(self, probabilities: Any) -> np.ndarray:
        p = validate_probability_matrix(probabilities, class_order=self.class_order)
        return validate_probability_matrix(self._transform(p, self.temperature), class_order=self.class_order)


@dataclass
class MultinomialLogScoreCalibrator:
    """Regularized multinomial calibration on the full vector of saved log scores."""

    regularization_c: float = 1.0
    random_state: int = 20260912
    method: str = "MULTINOMIAL_LOG_SCORE_CALIBRATION"
    class_order: tuple[str, ...] = PA_CLASS_ORDER
    fit_metadata: dict[str, Any] = field(default_factory=dict)
    estimator: LogisticRegression | None = None

    def fit(self, probabilities: Any, labels: Any) -> "MultinomialLogScoreCalibrator":
        x = _log_probabilities(probabilities)
        y = np.asarray(labels, dtype=np.int64)
        if y.shape != (len(x),) or set(np.unique(y)) != set(range(len(self.class_order))):
            raise ValueError("Multinomial calibration fit must contain every frozen class")
        self.estimator = LogisticRegression(
            C=self.regularization_c,
            solver="lbfgs",
            max_iter=1000,
            random_state=self.random_state,
        )
        self.estimator.fit(x, y)
        if not np.array_equal(self.estimator.classes_, np.arange(len(self.class_order))):
            raise ValueError("Multinomial calibrator class order differs from the frozen order")
        self.fit_metadata = {
            "estimator": "sklearn.linear_model.LogisticRegression",
            "input": "natural log of all eight probabilities with 1e-15 floor",
            "C": self.regularization_c,
            "solver": "lbfgs",
            "iterations": [int(v) for v in self.estimator.n_iter_],
            "fitRows": int(len(x)),
            "objective": "regularized multinomial log loss",
        }
        return self

    def transform(self, probabilities: Any) -> np.ndarray:
        if self.estimator is None:
            raise ValueError("Multinomial calibrator is not fitted")
        result = np.asarray(self.estimator.predict_proba(_log_probabilities(probabilities)), dtype=np.float64)
        return validate_probability_matrix(result, class_order=self.class_order)


@dataclass
class CalibratedProbabilityProvider:
    """Apply a fitted eight-class calibrator after an unchanged V18 provider call."""

    provider: Any
    calibrator: Any

    def probabilities(self, **state: Any) -> np.ndarray:
        raw = self.provider.probabilities(**state)
        return self.calibrator.transform(raw)


class FrozenHistoricalReplayPreprocessor:
    """Replay saved pregame rows without weakening the live prospective-time guard."""

    def __init__(self, frozen: Any, authority: Any) -> None:
        self.frozen = frozen
        self.authority = authority
        self.encoder = frozen.encoder
        self.ordered_features = frozen.ordered_features
        self.source_columns = frozen.source_columns
        self.feature_set = frozen.feature_set

    def transform_frame(self, frame: pd.DataFrame) -> pd.DataFrame:
        from .mlb_v18_prospective_transform import authorize_frame

        if not isinstance(frame, pd.DataFrame):
            raise ValueError("Historical replay requires a DataFrame")
        return self.frozen.transform_frame(authorize_frame(frame, self.authority))

    def transform(self, frame: pd.DataFrame) -> Any:
        return self.encoder.transform(self.transform_frame(frame))

    def get_feature_names_out(self, input_features: Any = None) -> Any:
        return self.frozen.get_feature_names_out(input_features)


def build_saved_historical_replay_provider(engine: Any, snapshot: Mapping[str, Any],
                                           composition: Mapping[str, Any], execution: Mapping[str, Any],
                                           *, snapshot_sha256: str,
                                           original_forecast_created_at: str) -> tuple[Any, dict]:
    """Rebuild a provider only after exact archived initial-probability reproduction."""
    from .mlb_v18_current_publication import current_template
    from .mlb_v18_prospective_transform import HistoricalReplayFrameAuthority
    from .mlb_v18_whole_game_challenger import V18StateProbabilityProvider
    from .stage3_model_laboratory import Stage3FittedPipeline

    if not composition.get("canSimulate") or composition.get("blockers"):
        raise ValueError("Archived historical replay composition is incomplete")
    game_id = str(snapshot["game"]["game_id"])
    game_date = str(composition["rows"][0]["game_date"])[:10]
    authority = HistoricalReplayFrameAuthority(
        event_id=game_id, game_date=game_date,
        evidence_cutoff_utc=execution["sourceCutoff"]["evidenceAvailableAt"],
        captured_at_utc=snapshot["capturedAt"],
        original_forecast_created_at_utc=original_forecast_created_at,
        kickoff_utc=snapshot["game"]["starts_at"], snapshot_sha256=snapshot_sha256,
        replay_authorized_at_utc=datetime.now(timezone.utc).isoformat(),
        venue_timezone=composition["venueTimezone"],
    )
    authority.validate()
    preprocessor = FrozenHistoricalReplayPreprocessor(engine.pipeline.preprocessor, authority)
    pipeline = Stage3FittedPipeline(ordered_features=engine.pipeline.ordered_features,
                                    target_order=engine.pipeline.target_order,
                                    preprocessor=preprocessor, estimator=engine.pipeline.estimator)
    raw = pd.DataFrame(composition["rows"], columns=engine.contract["rawFeatureColumns"])
    actual = np.concatenate([pipeline.predict_proba(raw.iloc[[index]]) for index in range(len(raw))])
    expected = np.asarray(execution["initialPaProbabilities"], dtype=np.float64)
    if actual.shape != expected.shape or not np.array_equal(actual, expected):
        raise ValueError("Historical replay does not reproduce archived initial V18 probabilities")
    inputs = execution["providerInputs"]
    if inputs != composition["providerInputs"]:
        raise ValueError("Archived historical replay provider inputs differ")
    provider = V18StateProbabilityProvider(
        pipeline, away_batters=inputs["awayBatters"], home_batters=inputs["homeBatters"],
        away_starter=inputs["awayStarter"], home_starter=inputs["homeStarter"],
        away_bullpen=inputs["awayBullpen"], home_bullpen=inputs["homeBullpen"],
        temperature=None, template_composer=current_template,
    )
    return provider, {"mode": "CHECKSUM_VERIFIED_HISTORICAL_REPLAY_ONLY",
                      "archivedPregameCapture": snapshot["capturedAt"],
                      "rowsReproduced": int(len(raw)), "probabilityValuesReproduced": int(expected.size),
                      "initialProbabilityMismatches": 0, "liveProspectiveGuardChanged": False}


def sha256_file(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_calibrator(reference: Mapping[str, Any]) -> Any:
    path = Path(reference["path"]).resolve(strict=True)
    if sha256_file(path) != reference["sha256"] or path.stat().st_size != int(reference["bytes"]):
        raise ValueError("Calibration artifact checksum mismatch")
    calibrator = joblib.load(path)
    if tuple(calibrator.class_order) != PA_CLASS_ORDER:
        raise ValueError("Calibration artifact class order differs from the frozen order")
    probe = np.full((2, len(PA_CLASS_ORDER)), 1.0 / len(PA_CLASS_ORDER), dtype=np.float64)
    validate_probability_matrix(calibrator.transform(probe), class_order=PA_CLASS_ORDER)
    return calibrator


__all__ = [
    "CalibratedProbabilityProvider",
    "FrozenHistoricalReplayPreprocessor",
    "MultinomialLogScoreCalibrator",
    "TemperatureCalibrator",
    "build_saved_historical_replay_provider",
    "load_calibrator",
    "sha256_file",
]
