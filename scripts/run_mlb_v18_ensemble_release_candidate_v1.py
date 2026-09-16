"""Run the immutable MLB V18 ensemble research candidate for prediction or replay."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_starter_duration_paired_publication import (
    CurrentV18Engine,
    load_duration_model,
    read as read_research_ref,
)
from server.sports_current_statcast.mlb_starter_duration_paired_simulation import simulate_paired_game
from server.sports_current_statcast.mlb_v18_ensemble_candidate import (
    CalibratedProbabilityProvider,
    build_saved_historical_replay_provider,
    load_calibrator,
    sha256_file,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


DEFAULT_CURRENT = ROOT / "outputs/mlb-v18-ensemble-release-candidate-v1/current.json"
CURRENT_V18 = ROOT / "outputs/mlb-v18-current-state-pipeline-v1"


def load_reference(reference: dict) -> Path:
    path = Path(reference["path"]).resolve(strict=True)
    if sha256_file(path) != reference["sha256"] or path.stat().st_size != int(reference["bytes"]):
        raise ValueError("Package reference checksum mismatch")
    return path


def load_package(current_path: Path) -> tuple[dict, dict]:
    current = json.loads(current_path.read_text(encoding="utf-8"))
    package_path = load_reference(current["package"])
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if package["classOrder"] != list(PA_CLASS_ORDER) or not package["researchShadowOnly"]:
        raise ValueError("Frozen class order or research authority mismatch")
    return current, package


def selected_calibrator(package: dict):
    component = package["components"]["calibration"]
    if component["status"] != "ENABLED_RESEARCH_CANDIDATE":
        return None
    return load_calibrator(component["artifact"])


def replay_calibrator(package: dict):
    component = package["components"]["calibration"]
    reference = component.get("artifact") or component.get("comparisonArtifact")
    if reference is None:
        raise ValueError("No serialized calibration artifact is available for replay")
    return load_calibrator(reference)


def summarize(population: dict) -> dict:
    home = np.asarray(population["homeRuns"], dtype=float)
    away = np.asarray(population["awayRuns"], dtype=float)
    margin = home - away
    def stat(values: np.ndarray) -> dict:
        return {"mean": float(values.mean()),
                "monteCarloStandardError": float(values.std(ddof=1) / math.sqrt(len(values)))}
    return {"simulations": len(home), "homeWin": stat((margin > 0).astype(float)),
            "homeRuns": stat(home), "awayRuns": stat(away), "homeMargin": stat(margin),
            "totalRuns": stat(home + away), "illegalStateCount": int(population.get("illegalStateCount", 0)),
            "nonterminationCount": int(population.get("nonterminationCount", 0))}


def predict(args: argparse.Namespace, package: dict) -> None:
    value = json.loads(Path(args.probabilities_json).read_text(encoding="utf-8"))
    raw = value["probabilities"] if isinstance(value, dict) else value
    probabilities = validate_probability_matrix(raw, class_order=PA_CLASS_ORDER)
    calibrator = selected_calibrator(package)
    result = calibrator.transform(probabilities) if calibrator is not None else probabilities
    print(json.dumps({"candidateId": package["candidateId"], "configuration": package["defaultConfiguration"],
                      "classOrder": list(PA_CLASS_ORDER), "probabilities": result.tolist()}, allow_nan=False))


def duration_supported(duration_inputs: dict) -> bool:
    required = {"homePitcher", "calendarMonth", "priorStartCount", "priorStartBfMean", "daysRest", "historyMissing"}
    return (duration_inputs.get("status") == "SUPPORTED"
            and all(required <= set(duration_inputs.get(side, {})) for side in ("home", "away")))


def simulate(args: argparse.Namespace, package: dict) -> None:
    game_ref = package["comparison"]["game"]
    game = json.loads(load_reference(game_ref).read_text(encoding="utf-8"))
    pair = json.loads(load_reference(game["v18Pair"]).read_text(encoding="utf-8"))
    inputs = read_research_ref(pair["inputs"])
    requested = args.configuration
    wants_duration = requested in ("C", "D")
    if args.force_unsupported_duration:
        inputs = json.loads(json.dumps(inputs))
        inputs["durationInputs"]["status"] = "UNSUPPORTED_TEST_FIXTURE"
    actual = requested
    fallback = None
    if wants_duration and not duration_supported(inputs["durationInputs"]):
        actual = "B" if requested == "D" else "A"
        fallback = {"requested": requested, "actual": actual,
                    "reason": "SUPPORTED_CERTIFIED_DURATION_INPUTS_ABSENT"}

    saved = read_research_ref(pair["population"])
    if actual in ("A", "C"):
        population = saved["reference" if actual == "A" else "challenger"]
    else:
        calibrator = replay_calibrator(package)
        source = CURRENT_V18 / inputs["v18SourceObject"]["relativePath"]
        snapshot = json.loads((source / "pregame-evidence.json").read_text(encoding="utf-8"))
        execution = json.loads((source / "execution-inputs.json").read_text(encoding="utf-8"))
        feature = read_research_ref(inputs["featureSnapshot"])
        with threadpool_limits(limits=4):
            engine = CurrentV18Engine()
            base_provider, _ = build_saved_historical_replay_provider(
                engine, snapshot, feature["composition"], execution,
                snapshot_sha256=inputs["featureSnapshot"]["sha256"],
                original_forecast_created_at=inputs["originalForecastCreatedAt"])
            provider = CalibratedProbabilityProvider(base_provider, calibrator)
            duration_model, _ = load_duration_model()
            replay = simulate_paired_game(
                game_id=pair["gameId"], provider=provider, transition_model=engine.transition,
                duration_model=duration_model, home_duration_inputs=inputs["durationInputs"]["home"],
                away_duration_inputs=inputs["durationInputs"]["away"], n_sims=pair["simulationsPerArm"],
                master_seed=pair["masterSeed"], regulation=int(snapshot["game"].get("scheduled_innings") or 9),
                trace_count=1,
            )
        population = replay["reference" if actual == "B" else "challenger"]
    print(json.dumps({"candidateId": package["candidateId"], "requestedConfiguration": requested,
                      "actualConfiguration": actual, "fallback": fallback,
                      "status": "LABELED_HISTORICAL_REPLAY_NOT_FORECAST",
                      "gameId": pair["gameId"], "summary": summarize(population)}, indent=2, allow_nan=False))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_CURRENT,
                        help="Candidate current.json pointer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    predict_parser = subparsers.add_parser("predict")
    predict_parser.add_argument("--probabilities-json", required=True)
    simulate_parser = subparsers.add_parser("simulate")
    simulate_parser.add_argument("--configuration", choices=("A", "B", "C", "D"), default="B")
    simulate_parser.add_argument("--force-unsupported-duration", action="store_true",
                                 help="Integration fixture: verify C/D falls back to A/B")
    args = parser.parse_args()
    _, package = load_package(args.package)
    if args.command == "predict":
        predict(args, package)
    else:
        simulate(args, package)


if __name__ == "__main__":
    main()
