"""Bounded, event-atomic market research; no operational policy authority.

The caller supplies point-in-time full-game moneyline checkpoints. Only T-60m
is eligible for fitting; other checkpoints remain descriptive. Signal values
without availability evidence are absent, never silently made contemporaneous.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, logit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from .market_tape import sealed


MOVEMENT_SIGNALS = ("movement", "velocity", "acceleration", "dispersion", "cross_book_range", "synchronized_fraction")
RFF_SIGNALS = ("rff_cross_book_dispersion", "rff_model_market_disagreement", "rff_late_synchronized_movement",
               "rff_prediction_market_disagreement")
ALL_SIGNALS = ("model_disagreement", *MOVEMENT_SIGNALS, *RFF_SIGNALS)
SEED = 20260910
EPSILON = 1e-9
TARGETS = {
    "home_win": "Binary home win; logistic residual means logit(p_market)+f(X), not logistic regression of y-p_market.",
    "next_movement": "Next observed pregame consensus home probability minus checkpoint consensus; probability units, not betting returns.",
    "disagreement_survival": "Initial nonzero model-minus-market disagreement retains its sign against closing consensus, holding checkpoint model probability fixed; zero closing disagreement is not survival.",
}


def _json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [_json(v) for v in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return _json(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _bytes(value: Any) -> bytes:
    return json.dumps(_json(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(output: Path, value: Any) -> dict:
    raw = _bytes(value)
    path = output / "objects" / (_sha(raw) + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable research JSON conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return {"path": str(path.resolve()), "sha256": _sha(raw), "bytes": len(raw)}


def _time(value: Any) -> pd.Timestamp | None:
    try:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            return None
        return timestamp.tz_convert("UTC")
    except (TypeError, ValueError):
        return None


def _number(value: Any, *, probability: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    if not np.isfinite(result) or (probability and not 0 <= result <= 1):
        return float("nan")
    return result


def _checkpoint(value: Any) -> str:
    label = str(value).lower().replace(" ", "").replace("_", "")
    return "60m" if label in {"60", "60m", "60min", "60minutes", "t-60", "t-60m", "t-60min"} else str(value)


def _prepare(checkpoints: list[dict]) -> tuple[pd.DataFrame, list[dict]]:
    rows, excluded = [], []
    now = pd.Timestamp(datetime.now(timezone.utc))
    for index, original in enumerate(checkpoints):
        event_id = str(original.get("event_id") or "")
        start, checkpoint = _time(original.get("event_start")), _time(original.get("checkpoint_at"))
        reason = None
        market_type = str(original.get("market_type", "MONEYLINE")).upper()
        if market_type not in {"MONEYLINE", "ML"} or str(original.get("period", "FULL_GAME")).upper() != "FULL_GAME":
            reason = "NOT_FULL_GAME_MONEYLINE"
        elif _number(original.get("book_count")) < 2 or not np.isfinite(_number(original.get("book_count"))):
            reason = "FEWER_THAN_TWO_SUPPORTED_BOOKS"
        elif str(original.get("status", "SUPPORTED")).upper() != "SUPPORTED":
            reason = "UNSUPPORTED_POINT_IN_TIME_CHECKPOINT"
        elif not event_id or start is None or checkpoint is None or checkpoint >= start:
            reason = "INVALID_OR_NONPREGAME_CHECKPOINT"
        elif original.get("final_oot") is True or sealed(start):
            reason = "SEALED_FINAL_OOT"
        p = _number(original.get("consensus_probability"), probability=True)
        if reason is None and not np.isfinite(p):
            reason = "MISSING_VALID_CONSENSUS_PROBABILITY"
        if reason:
            excluded.append({"inputIndex": index, "event_id": event_id, "reason": reason})
            continue
        availability = original.get("signal_available_at") or {}
        model = _number(original.get("model_probability"), probability=True)
        model_at = _time(original.get("model_available_at", availability.get("model_probability")))
        model_valid = (original.get("model_probability_pit_valid") is True and np.isfinite(model)
                       and model_at is not None and model_at <= checkpoint)
        model = model if model_valid else float("nan")
        row = {"event_id": event_id, "event_start": start, "checkpoint_at": checkpoint,
               "checkpoint": _checkpoint(original.get("checkpoint")), "consensus_probability": p,
               "market_logit": float(logit(np.clip(p, EPSILON, 1-EPSILON))),
               "model_probability": model, "rff_supported": original.get("rff_supported") is True}
        for name in (*MOVEMENT_SIGNALS, *RFF_SIGNALS):
            available = _time(availability.get(name))
            value = _number(original.get(name))
            row[name] = value if available is not None and available <= checkpoint and (
                not name.startswith("rff_") or row["rff_supported"]) else float("nan")
        row["model_disagreement"] = model-p if model_valid else float("nan")
        settled_at = _time(original.get("target_available_at"))
        y = _number(original.get("target_home_win"))
        row["home_win"] = y if y in {0., 1.} and settled_at is not None and start <= settled_at <= now else float("nan")
        row["home_win_available_at"] = settled_at
        next_at = _time(original.get("next_at"))
        next_available = _time(original.get("next_available_at", original.get("next_at")))
        next_p = _number(original.get("next_probability"), probability=True)
        next_valid = next_at is not None and next_available is not None and checkpoint < next_at <= next_available < start and next_available <= now
        row["next_movement"] = next_p-p if next_valid and np.isfinite(next_p) else float("nan")
        row["next_movement_available_at"] = next_available
        close_at = _time(original.get("closing_at"))
        close_available = _time(original.get("closing_available_at", original.get("closing_at")))
        close_p = _number(original.get("closing_probability"), probability=True)
        close_valid = close_at is not None and close_available is not None and checkpoint < close_at <= close_available < start and close_available <= now
        discrepancy = model-p
        row["disagreement_survival"] = float(discrepancy*(model-close_p) > 0) if (
            close_valid and model_valid and np.isfinite(close_p) and discrepancy != 0) else float("nan")
        row["disagreement_survival_available_at"] = close_available
        row["closing_consensus_minus_checkpoint"] = close_p-p if close_valid and np.isfinite(close_p) else float("nan")
        rows.append(row)
    return pd.DataFrame(rows), excluded


def _metrics(y: np.ndarray, prediction: np.ndarray, *, regression: bool = False) -> dict:
    if regression:
        residual = prediction-y
        return {"observations": len(y), "mae": float(np.mean(np.abs(residual))),
                "rmse": float(np.sqrt(np.mean(residual**2))), "meanPredictionBias": float(residual.mean())}
    p = np.clip(prediction, EPSILON, 1-EPSILON)
    bins = np.minimum((p*10).astype(int), 9)
    reliability = [{"bin": b, "observations": int((bins == b).sum()),
                    "meanProbability": float(p[bins == b].mean()), "observedRate": float(y[bins == b].mean())}
                   for b in range(10) if np.any(bins == b)]
    return {"observations": len(y), "logLoss": float(np.mean(-y*np.log(p)-(1-y)*np.log1p(-p))),
            "brier": float(np.mean((prediction-y)**2)), "observedRate": float(y.mean()),
            "meanProbability": float(prediction.mean()), "meanProbabilityBias": float((prediction-y).mean()),
            "ece10EqualWidth": float(sum(v['observations']*abs(v['meanProbability']-v['observedRate']) for v in reliability)/len(y)),
            "reliability": reliability, "calibrationFitted": False}


def _folds(frame: pd.DataFrame, target: str) -> tuple[list[tuple[np.ndarray, np.ndarray, dict]], dict]:
    eligible = frame[np.isfinite(frame[target])].sort_values(["event_start", "event_id"]).reset_index(drop=True)
    n = len(eligible)
    gate = {"target": target, "uniqueEligibleEvents": n, "minimumEvents": 60,
            "minimumInitialTrainingEvents": 30, "minimumValidationEventsPerFold": 10, "requiredFolds": 3}
    if n < 60:
        return [], {**gate, "status": "INSUFFICIENT_HISTORY"}
    initial = max(30, n//2)
    windows = np.array_split(np.arange(initial, n), 3)
    folds = []
    for number, validation in enumerate(windows, 1):
        cutoff = eligible.iloc[validation].checkpoint_at.min()
        first_event = eligible.iloc[validation].event_start.min()
        training = np.asarray([i for i in range(int(validation[0]))
                               if eligible.iloc[i][target + '_available_at'] <= cutoff
                               and eligible.iloc[i].event_start < first_event], dtype=int)
        if len(training) < 30 or len(validation) < 10:
            return [], {**gate, "status": "INSUFFICIENT_CHRONOLOGICAL_TARGET_AVAILABILITY",
                        "failedFold": number, "trainingEvents": len(training), "validationEvents": len(validation)}
        contract = {"fold": number, "trainingCutoff": cutoff.isoformat(),
                    "trainingEvents": eligible.iloc[training].event_id.tolist(),
                    "validationEvents": eligible.iloc[validation].event_id.tolist(),
                    "maximumTrainingTargetAvailableAt": eligible.iloc[training][target+'_available_at'].max().isoformat(),
                    "validationCheckpointStart": cutoff.isoformat(), "eventAtomic": True}
        folds.append((training, validation, contract))
    return folds, {**gate, "status": "ELIGIBLE", "eligibleFrame": eligible}


@dataclass
class RidgeEstimator:
    coefficients: np.ndarray
    regression: bool
    converged: bool

    @classmethod
    def fit(cls, values: np.ndarray, y: np.ndarray, offset: np.ndarray, *, regression: bool = False):
        x = np.column_stack([np.ones(len(values)), values])
        ridge = np.full(x.shape[1], .1)
        ridge[0] = .01
        if regression:
            coefficients = np.linalg.solve(x.T@x/len(x) + np.diag(ridge), x.T@y/len(x))
            return cls(coefficients, True, True)
        def objective(coefficients):
            eta = offset+x@coefficients
            loss = np.mean(np.logaddexp(0, eta)-y*eta) + .5*np.sum(ridge*coefficients**2)
            gradient = x.T@(expit(eta)-y)/len(x) + ridge*coefficients
            return float(loss), gradient
        fitted = minimize(objective, np.zeros(x.shape[1]), method="L-BFGS-B", jac=True,
                          options={"maxiter": 200, "ftol": 1e-11, "gtol": 1e-7})
        return cls(fitted.x, False, bool(fitted.success))

    def predict(self, values: np.ndarray, offset: np.ndarray) -> np.ndarray:
        score = np.column_stack([np.ones(len(values)), values])@self.coefficients
        return score if self.regression else expit(offset+score)


@dataclass
class FittedResearchArtifact:
    model: str
    target: str
    features: tuple[str, ...]
    preprocessor: Any
    estimator: Any
    fold_contract: dict
    offset_recipe: str
    target_definition: str
    fixed_hyperparameters: dict

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        # The persisted artifact owns its native-thread budget, including reloads.
        with threadpool_limits(limits=4):
            x = self.preprocessor.transform(frame.loc[:, list(self.features)])
            if isinstance(self.estimator, RidgeEstimator):
                offset = frame.market_logit.to_numpy() if self.offset_recipe == "LOGIT_CHECKPOINT_MARKET_CONSENSUS" else np.zeros(len(frame))
                return self.estimator.predict(x, offset)
            return self.estimator.predict_proba(x)[:, list(self.estimator.classes_).index(1)]


def _persist_artifact(artifact: FittedResearchArtifact, validation: pd.DataFrame, expected: np.ndarray, output: Path) -> dict:
    # Serialized state is content-addressed; the temporary file is new and local.
    import io
    buffer = io.BytesIO()
    joblib.dump(artifact, buffer, compress=3)
    raw = buffer.getvalue()
    path = output / "objects" / (_sha(raw) + ".joblib")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Immutable research model conflict")
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    reloaded = joblib.load(path)
    actual = reloaded.predict(validation)
    maximum = float(np.max(np.abs(actual-expected)))
    if maximum > 1e-12:
        raise ValueError("Research artifact reload mismatch")
    fixture_columns = list(dict.fromkeys([*artifact.features, "market_logit", "event_id"]))
    fixture = {"model": artifact.model, "target": artifact.target, "orderedFeatures": artifact.features,
               "offsetRecipe": artifact.offset_recipe, "rows": validation.iloc[:5][fixture_columns].to_dict("records"),
               "expectedPredictions": expected[:5], "foldContract": artifact.fold_contract,
               "modelSha256": _sha(raw), "scope": "RESEARCH_ONLY_NOT_OPERATIONAL"}
    return {"model": artifact.model, "target": artifact.target, "fold": artifact.fold_contract["fold"],
            "path": str(path.resolve()), "sha256": _sha(raw), "bytes": len(raw),
            "reloadFixture": _write_json(output, fixture), "reloadedValidationEvents": len(validation),
            "maximumAbsoluteReloadDifference": maximum, "bitwiseEqual": bool(np.array_equal(actual, expected)),
            "orderedFeatures": list(artifact.features), "offsetRecipe": artifact.offset_recipe}


def _block_intervals(frame: pd.DataFrame, y: np.ndarray, p: np.ndarray, baseline: np.ndarray) -> dict:
    # Nonoverlapping 28-day blocks, at least eight. Independence is an assumption,
    # not something event volume proves; these intervals never authorize policy.
    block = frame.event_start.map(lambda value: int(value.timestamp()//(28*86400))).to_numpy()
    groups = np.unique(block)
    if len(groups) < 8:
        return {"status": "INSUFFICIENT_TEMPORAL_BLOCKS", "observed28DayBlocks": len(groups),
                "minimumBlocks": 8, "formalInference": False}
    safe, base = np.clip(p, EPSILON, 1-EPSILON), np.clip(baseline, EPSILON, 1-EPSILON)
    delta = np.column_stack([-y*np.log(safe)-(1-y)*np.log1p(-safe)+y*np.log(base)+(1-y)*np.log1p(-base),
                             (p-y)**2-(baseline-y)**2])
    totals = np.asarray([delta[block == group].sum(axis=0) for group in groups])
    counts = np.asarray([(block == group).sum() for group in groups])
    draws = np.random.default_rng(SEED).multinomial(len(groups), np.full(len(groups), 1/len(groups)), size=1000)
    samples = draws@totals/(draws@counts)[:, None]
    return {"status": "DESCRIPTIVE_BLOCK_INTERVAL_AVAILABLE", "observed28DayBlocks": len(groups),
            "method": "NONOVERLAPPING_28_DAY_BLOCK_BOOTSTRAP", "replicates": 1000,
            "logLossDifference95": np.quantile(samples[:, 0], [.025, .975]).tolist(),
            "brierDifference95": np.quantile(samples[:, 1], [.025, .975]).tolist(),
            "temporalIndependenceAssumedNotProven": True, "formalInference": False}


def run_research(checkpoints: list[dict], output_dir: Path, *, model_names: set[str] | None = None) -> dict:
    """Run only predeclared supported research comparisons or explain failed gates."""
    output = Path(output_dir)
    frame, excluded = _prepare(checkpoints)
    result = {"schemaVersion": "MARKET_INFORMATION_RESEARCH_COMPARISON_V1", "primaryCheckpoint": "60m",
              "inputCheckpoints": len(checkpoints), "inputDigest": _sha(_bytes(checkpoints)),
              "targetDefinitions": TARGETS, "excludedRows": excluded, "descriptive": [], "gates": {},
              "models": [], "artifacts": [], "actualEstimatorFitStarts": 0, "completedEstimatorFits": 0,
              "failures": [], "researchOnly": True, "wageringAuthority": False, "policySelection": False,
              "scope": "SUPPLIED_PIT_FULL_GAME_HOME_MONEYLINE_EVIDENCE_ONLY"}
    if frame.empty:
        result["status"] = "INSUFFICIENT_HISTORY_NO_FITS"
        result["receipt"] = _write_json(output, result)
        return result
    for checkpoint, group in frame.groupby("checkpoint", sort=True):
        settled = group[np.isfinite(group.home_win)]
        row = {"checkpoint": checkpoint, "events": group.event_id.nunique(), "rows": len(group),
               "settledEvents": settled.event_id.nunique(), "role": "PRIMARY_PREDECLARED" if checkpoint == "60m" else "DESCRIPTIVE_ONLY_NO_SELECTION"}
        if len(settled):
            row["marketConsensus"] = _metrics(settled.home_win.to_numpy(), settled.consensus_probability.to_numpy())
            model = settled[np.isfinite(settled.model_probability)]
            if len(model):
                row["aispAlone"] = _metrics(model.home_win.to_numpy(), model.model_probability.to_numpy())
                row["marketOnSameAispPopulation"] = _metrics(model.home_win.to_numpy(), model.consensus_probability.to_numpy())
        for target in ("next_movement", "disagreement_survival", "closing_consensus_minus_checkpoint"):
            values = group.loc[np.isfinite(group[target]), target]
            row[target] = {"observations": len(values), "mean": float(values.mean()) if len(values) else None,
                           "scope": "DESCRIPTIVE_TARGET_NOT_WAGERING_RETURN"}
        result["descriptive"].append(row)
    primary = frame[frame.checkpoint.eq("60m")].copy()
    duplicated = primary.event_id.duplicated(keep=False)
    result["duplicatePrimaryEventsExcluded"] = sorted(primary.loc[duplicated, "event_id"].unique().tolist())
    primary = primary[~duplicated]
    model_specs = [
        ("MARKET_PLUS_MODEL_DISAGREEMENT", ("model_disagreement",), "model", False),
        ("MARKET_PLUS_MOVEMENT_DISPERSION", MOVEMENT_SIGNALS, "movement", False),
        ("MARKET_PLUS_SUPPORTED_RFF", RFF_SIGNALS, "rff", False),
        ("INTERPRETABLE_LOGISTIC_OFFSET", ALL_SIGNALS, "any", False),
        ("HGB_RESEARCH_CHALLENGER", ("market_logit", *ALL_SIGNALS), "any", True),
        ("HGB_MARKET_ONLY_CONTROL", ("market_logit",), "market", True),
    ]
    if model_names is None or "HGB_MARKET_ONLY_CONTROL" in model_names:
        result["exploratoryControls"] = [{
            "model": "HGB_MARKET_ONLY_CONTROL", "features": ["market_logit"],
            "registrationTiming": "EXPLORATORY_ADDED_AFTER_OBSERVING_COMPOSITE_HGB_GAIN",
            "purpose": "Distinguish composite-feature gain from nonlinear market-only recalibration on the same folds.",
            "sameHgbHyperparametersAndSeeds": True, "predeclaredBeforeOutcomeInspection": False,
            "independentConfirmation": False,
        }]
    if model_names is not None:
        allowed = {spec[0] for spec in model_specs} | {"RIDGE_NEXT_MOVEMENT", "LOGISTIC_DISAGREEMENT_SURVIVAL"}
        unknown = set(model_names)-allowed
        if unknown:
            raise ValueError(f"Unknown requested research models: {sorted(unknown)}")
        result["requestedModelNames"] = sorted(model_names)
    for target in TARGETS:
        regression = target == "next_movement"
        specs = model_specs if target == "home_win" else [
            ("RIDGE_NEXT_MOVEMENT" if regression else "LOGISTIC_DISAGREEMENT_SURVIVAL", ALL_SIGNALS, "any", False)]
        if model_names is not None:
            specs = [spec for spec in specs if spec[0] in model_names]
            if not specs:
                result["gates"][target] = {"target": target, "status": "NOT_REQUESTED_NO_FITS"}
                continue
        folds, gate = _folds(primary, target)
        eligible = gate.pop("eligibleFrame", None)
        result["gates"][target] = gate
        if not folds:
            continue
        assert eligible is not None
        validation_union = np.concatenate([validation for _, validation, _ in folds])
        eval_frame = eligible.iloc[validation_union]
        if target == "home_win":
            for name, column in (("MARKET_CONSENSUS", "consensus_probability"), ("EXISTING_AISP_ALONE", "model_probability")):
                take = np.isfinite(eval_frame[column])
                subset = eval_frame[take]
                if len(subset):
                    result["models"].append({"model": name, "target": target, "status": "FROZEN_INPUT_BENCHMARK_NO_FIT",
                        "events": len(subset), "metrics": _metrics(subset[target].to_numpy(), subset[column].to_numpy()),
                        "eventIds": subset.event_id.tolist(), "folds": [contract for _, _, contract in folds]})
        for name, features, support, hgb in specs:
            if support == "market":
                supported = np.isfinite(eligible.market_logit.to_numpy())
            elif support == "model":
                supported = np.isfinite(eligible.model_probability.to_numpy())
            else:
                columns = RFF_SIGNALS if support == "rff" else MOVEMENT_SIGNALS if support == "movement" else ALL_SIGNALS
                supported = np.isfinite(eligible[list(columns)].to_numpy(dtype=float)).any(axis=1)
            qualified = []
            for training, validation, contract in folds:
                tr, va = training[supported[training]], validation[supported[validation]]
                if len(tr) < 30 or len(va) < 10 or (not regression and eligible.iloc[tr][target].nunique() < 2):
                    break
                qualified.append((tr, va, contract))
            if len(qualified) != 3:
                result["models"].append({"model": name, "target": target, "status": "INSUFFICIENT_SUPPORTED_CHRONOLOGICAL_HISTORY",
                                         "fitted": False, "supportedEvents": int(supported.sum())})
                continue
            predictions, originals, baselines, fold_rows = [], [], [], []
            for training, validation, raw_contract in qualified:
                train, valid = eligible.iloc[training], eligible.iloc[validation]
                contract = {**raw_contract, "trainingEvents": train.event_id.tolist(), "validationEvents": valid.event_id.tolist()}
                try:
                    preprocessing = make_pipeline(SimpleImputer(strategy="median", add_indicator=True, keep_empty_features=True), StandardScaler())
                    x = preprocessing.fit_transform(train.loc[:, list(features)])
                    y = train[target].to_numpy(dtype=float)
                    offset_recipe = "LOGIT_CHECKPOINT_MARKET_CONSENSUS" if target == "home_win" and not hgb else "NONE"
                    result["actualEstimatorFitStarts"] += 1
                    with threadpool_limits(limits=4):
                        if hgb:
                            parameters = {"max_iter": 50, "max_leaf_nodes": 7, "min_samples_leaf": 10,
                                          "learning_rate": .05, "l2_regularization": 1., "early_stopping": False,
                                          "random_state": SEED+contract["fold"]}
                            estimator = HistGradientBoostingClassifier(**parameters).fit(x, y)
                        else:
                            parameters = {"ridge": .1, "interceptRidge": .01, "maxIterations": 200}
                            offset = train.market_logit.to_numpy() if target == "home_win" else np.zeros(len(train))
                            estimator = RidgeEstimator.fit(x, y, offset, regression=regression)
                            if not estimator.converged:
                                raise ValueError("Fixed ridge estimator did not converge; no retry")
                    result["completedEstimatorFits"] += 1
                    artifact = FittedResearchArtifact(name, target, tuple(features), preprocessing, estimator,
                                                     contract, offset_recipe, TARGETS[target], parameters)
                    prediction = artifact.predict(valid)
                    result["artifacts"].append(_persist_artifact(artifact, valid, prediction, output))
                    baseline = valid.consensus_probability.to_numpy() if target == "home_win" else np.full(len(valid), y.mean())
                    fold_rows.append({**contract, "metrics": _metrics(valid[target].to_numpy(), prediction, regression=regression),
                                      "baselineMetricsSameEvents": _metrics(valid[target].to_numpy(), baseline, regression=regression),
                                      "supportedSignalCountsTraining": {field: int(np.isfinite(train[field]).sum()) for field in features}})
                    predictions.append(prediction)
                    baselines.append(baseline)
                    originals.append(valid)
                except Exception as exc:
                    result["failures"].append({"model": name, "target": target, "fold": contract["fold"], "error": repr(exc), "retried": False})
                    break
            if not predictions:
                continue
            scored = pd.concat(originals, ignore_index=True)
            prediction, baseline = np.concatenate(predictions), np.concatenate(baselines)
            y = scored[target].to_numpy()
            result["models"].append({"model": name, "target": target,
                "status": "COMPLETED_THREE_CHRONOLOGICAL_FOLDS" if len(fold_rows) == 3 else "PARTIAL_NOT_COMPARISON_COMPLETE",
                "events": len(scored), "eventIds": scored.event_id.tolist(), "metrics": _metrics(y, prediction, regression=regression),
                "baselineMetricsSameEvents": _metrics(y, baseline, regression=regression), "folds": fold_rows,
                "uncertainty": _block_intervals(scored, y, prediction, baseline) if not regression else {
                    "status": "DESCRIPTIVE_ONLY_NO_FORMAL_MOVEMENT_INFERENCE"}})
    result["status"] = "RESEARCH_COMPARISONS_COMPLETED" if result["completedEstimatorFits"] and not result["failures"] else (
        "PARTIAL_RESEARCH_WITH_FAILURES" if result["failures"] else "INSUFFICIENT_HISTORY_NO_FITS")
    result["limitations"] = [
        "One predeclared checkpoint per event; alternative checkpoints are not extra independent samples or selection opportunities.",
        "Each model reports its supported event population and a baseline on those exact events; differing coverage is not a matched-model comparison.",
        "Only supplied timestamp-verified signals enter fold-local median imputation with missing indicators; unavailable components are not observed zeros.",
        "Equal-width calibration summaries may conceal rare-probability miscalibration; no calibration fitting or promotion test is performed.",
        "Probability movement and disagreement survival are information targets, not realized profit, monetary CLV, or proof of wagering edge.",
        "All outputs remain research-only and do not select, change, or activate betting policy.",
    ]
    result["receipt"] = _write_json(output, result)
    return _json(result)
