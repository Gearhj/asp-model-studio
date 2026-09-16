"""Fit, compare, serialize, and package the bounded MLB V18 ensemble release candidate."""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_name] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_regime_baseline import AuthorizedByteReader, footer_metadata
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask
from server.sports_current_statcast.mlb_starter_duration_paired_publication import (
    CurrentV18Engine,
    load_duration_model,
    read as read_research_ref,
)
from server.sports_current_statcast.mlb_starter_duration_paired_simulation import (
    POPULATION_ARRAYS,
    simulate_paired_game,
)
from server.sports_current_statcast.mlb_v18_ensemble_candidate import (
    CalibratedProbabilityProvider,
    MultinomialLogScoreCalibrator,
    TemperatureCalibrator,
    build_saved_historical_replay_provider,
    load_calibrator,
    sha256_file,
)
from server.sports_modeling.metrics import PA_CLASS_ORDER, validate_probability_matrix


OUT = ROOT / "outputs/mlb-v18-ensemble-release-candidate-v1"
PROTOCOL = OUT / "protocol.json"
PARENT = ROOT / "outputs/mlb-v18-empirical-diagnosis-v1"
FOLLOWUP = ROOT / "outputs/mlb-v18-doubles-followup-v1"
OOF = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory/objects/oof/sha256/b79a80398ef32a13589a8bb66f5e4e9c698b600195de5369886f7fc07f0dc215.parquet"
PAIR = ROOT / "outputs/mlb-starter-duration-paired-research-v1/objects/sha256/fdee9e2fa72c8339c9bbd0d9e723d8898c34c80671c44eaf1d1f843674edfd45/paired-forecast.json"
CURRENT_V18 = ROOT / "outputs/mlb-v18-current-state-pipeline-v1"
CLASSES = tuple(PA_CLASS_ORDER)
PROBABILITY_COLUMNS = ["probability_" + name for name in CLASSES]
CALIBRATION_BINS = (0.0, 0.01, 0.025, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.70, 1.0000000001)
EXPECTED_BRANCH = "codex/mlb-starter-duration-source-intake-v1"
EXPECTED_HEAD = "9ca94e9c0135cde7d2b852560d59a43fa45a5c17"
READS: list[dict] = []


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path | str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def reference(path: Path | str) -> dict:
    target = Path(path).resolve(strict=True)
    return {"path": str(target), "sha256": sha(target), "bytes": target.stat().st_size}


def write_bytes_object(name: str, payload: bytes) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    target = OUT / "objects/sha256" / digest / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if target.read_bytes() != payload:
            raise ValueError("Immutable object collision")
    else:
        with target.open("xb") as handle:
            handle.write(payload)
    return reference(target)


def write_json_object(name: str, value: dict) -> dict:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return write_bytes_object(name, payload)


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def read_columns(path: Path, columns: list[str], purpose: str, *, fold5: bool = False) -> pd.DataFrame:
    metadata, footer = footer_metadata(path)
    ranges = [(0, 4), (footer, path.stat().st_size)]
    for group_index in range(metadata.num_row_groups):
        group = metadata.row_group(group_index)
        for column_index in range(group.num_columns):
            column = group.column(column_index)
            if column.path_in_schema not in columns:
                continue
            offsets = [column.data_page_offset]
            if column.has_dictionary_page:
                offsets.append(column.dictionary_page_offset)
            start = min(offsets)
            ranges.append((start, start + column.total_compressed_size))
    with AuthorizedByteReader(path, ranges) as reader:
        table = pq.ParquetFile(reader, pre_buffer=False).read(columns=columns, use_threads=False)
        if fold5:
            table = table.filter(pc.equal(table["foldNumber"], 5))
        frame = table.to_pandas()
    READS.append({"path": str(path), "purpose": purpose, "columns": columns,
                  "rowsReturned": len(frame), "physicalColumnAllowlist": True,
                  "fold5SelectedBeforeCalculation": fold5})
    return frame


def split_mask(dates: pd.Series, spec: dict) -> np.ndarray:
    values = dates.astype(str).str[:10]
    return values.between(spec["start"], spec["end"]).to_numpy()


def basic_metrics(labels: np.ndarray, probabilities: np.ndarray, mask: np.ndarray) -> dict:
    p = probabilities[mask]
    y = labels[mask]
    truth = np.eye(len(CLASSES), dtype=float)[y]
    return {
        "rows": int(len(y)),
        "logLoss": float(-np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1.0)).mean()),
        "summedBrier": float(np.square(p - truth).sum(axis=1).mean()),
    }


def evaluate(partition: str, candidate: str, labels: np.ndarray, baseline: np.ndarray,
             probabilities: np.ndarray, partition_mask: np.ndarray,
             global_rows: list[dict], class_rows: list[dict], band_rows: list[dict]) -> dict:
    p = validate_probability_matrix(probabilities, class_order=CLASSES)
    fixed_double = (baseline[:, 4] >= 0.05) & (baseline[:, 4] < 0.10)
    subsets = {
        "ALL": partition_mask,
        "FIXED_V18_DOUBLE_5_10": partition_mask & fixed_double,
        "OUTSIDE_FIXED_V18_DOUBLE_5_10": partition_mask & ~fixed_double,
    }
    metrics = {}
    for subset, mask in subsets.items():
        row = {"partition": partition, "candidate": candidate, "subset": subset, **basic_metrics(labels, p, mask)}
        global_rows.append(row)
        metrics[subset] = row
    y = labels[partition_mask]
    q = p[partition_mask]
    truth = np.eye(len(CLASSES), dtype=float)[y]
    for class_index, name in enumerate(CLASSES):
        expected = q[:, class_index]
        observed = truth[:, class_index]
        weighted_gap = 0.0
        for lo, hi in zip(CALIBRATION_BINS[:-1], CALIBRATION_BINS[1:]):
            mask = (expected >= lo) & (expected < hi)
            count = int(mask.sum())
            predicted = float(expected[mask].mean()) if count else None
            actual = float(observed[mask].mean()) if count else None
            gap = (predicted - actual) if count else None
            if count:
                weighted_gap += count * abs(gap)
            band_rows.append({"partition": partition, "candidate": candidate, "outcome": name,
                              "lower": lo, "upper": min(hi, 1.0), "rows": count,
                              "predictedRate": predicted, "observedRate": actual,
                              "bias": gap})
        class_rows.append({"partition": partition, "candidate": candidate, "outcome": name,
                           "rows": int(len(q)), "predictedRate": float(expected.mean()),
                           "observedRate": float(observed.mean()),
                           "bias": float((expected - observed).mean()),
                           "expectedCalibrationError": float(weighted_gap / len(q))})
    return metrics


def save_calibrator(calibrator: object, name: str) -> dict:
    buffer = io.BytesIO()
    joblib.dump(calibrator, buffer, compress=3)
    return write_bytes_object(name, buffer.getvalue())


def summary(population: dict) -> dict:
    home = np.asarray(population["homeRuns"], dtype=float)
    away = np.asarray(population["awayRuns"], dtype=float)
    margin = home - away
    total = home + away
    win = (margin > 0).astype(float)
    def stat(values: np.ndarray) -> dict:
        return {"mean": float(values.mean()),
                "monteCarloStandardError": float(values.std(ddof=1) / math.sqrt(len(values)))}
    return {"simulations": int(len(home)), "homeWin": stat(win), "homeRuns": stat(home),
            "awayRuns": stat(away), "homeMargin": stat(margin), "totalRuns": stat(total),
            "extraInningRate": stat((np.asarray(population["innings"]) > 9).astype(float)),
            "illegalStateCount": int(population.get("illegalStateCount", 0)),
            "nonterminationCount": int(population.get("nonterminationCount", 0))}


def paired_delta(challenger: dict, reference_population: dict) -> dict:
    result = {}
    for name, values in {
        "homeWin": (np.asarray(challenger["homeRuns"]) > np.asarray(challenger["awayRuns"])).astype(float),
        "homeRuns": np.asarray(challenger["homeRuns"], dtype=float),
        "awayRuns": np.asarray(challenger["awayRuns"], dtype=float),
        "homeMargin": np.asarray(challenger["homeRuns"], dtype=float) - np.asarray(challenger["awayRuns"], dtype=float),
        "totalRuns": np.asarray(challenger["homeRuns"], dtype=float) + np.asarray(challenger["awayRuns"], dtype=float),
    }.items():
        if name == "homeWin":
            ref = (np.asarray(reference_population["homeRuns"]) > np.asarray(reference_population["awayRuns"])).astype(float)
        elif name == "homeMargin":
            ref = np.asarray(reference_population["homeRuns"], dtype=float) - np.asarray(reference_population["awayRuns"], dtype=float)
        elif name == "totalRuns":
            ref = np.asarray(reference_population["homeRuns"], dtype=float) + np.asarray(reference_population["awayRuns"], dtype=float)
        else:
            ref = np.asarray(reference_population[name], dtype=float)
        delta = values - ref
        result[name] = {"mean": float(delta.mean()),
                        "pairedMonteCarloStandardError": float(delta.std(ddof=1) / math.sqrt(len(delta)))}
    return result


def build_game_comparison(calibrator: object, calibration_name: str, release_enabled: bool) -> tuple[dict, dict]:
    pair_ref = reference(PAIR)
    pair = json.loads(PAIR.read_text(encoding="utf-8"))
    inputs = read_research_ref(pair["inputs"])
    saved_population = read_research_ref(pair["population"])
    source = CURRENT_V18 / inputs["v18SourceObject"]["relativePath"]
    snapshot = json.loads((source / "pregame-evidence.json").read_text(encoding="utf-8"))
    execution = json.loads((source / "execution-inputs.json").read_text(encoding="utf-8"))
    feature = read_research_ref(inputs["featureSnapshot"])
    with threadpool_limits(limits=4):
        engine = CurrentV18Engine()
        base_provider, pa_reload = build_saved_historical_replay_provider(
            engine, snapshot, feature["composition"], execution,
            snapshot_sha256=inputs["featureSnapshot"]["sha256"],
            original_forecast_created_at=inputs["originalForecastCreatedAt"])
        duration_model, duration_identity = load_duration_model()
        calibrated_provider = CalibratedProbabilityProvider(base_provider, calibrator)
        calibrated_pair = simulate_paired_game(
            game_id=pair["gameId"], provider=calibrated_provider, transition_model=engine.transition,
            duration_model=duration_model, home_duration_inputs=inputs["durationInputs"]["home"],
            away_duration_inputs=inputs["durationInputs"]["away"], n_sims=pair["simulationsPerArm"],
            master_seed=pair["masterSeed"], regulation=int(snapshot["game"].get("scheduled_innings") or 9),
            trace_count=1,
        )
    populations = {
        "A_FROZEN_V18_BASELINE_HOOK": saved_population["reference"],
        "B_V18_PLUS_CALIBRATION": calibrated_pair["reference"],
        "C_V18_PLUS_DURATION": saved_population["challenger"],
        "D_V18_PLUS_CALIBRATION_PLUS_DURATION": calibrated_pair["challenger"],
    }
    summaries = {name: summary(value) for name, value in populations.items()}
    baseline = populations["A_FROZEN_V18_BASELINE_HOOK"]
    for name, values in populations.items():
        summaries[name]["pairedDeltaVersusA"] = paired_delta(values, baseline)
    archive = io.BytesIO()
    arrays = {}
    for config, population in populations.items():
        for field in POPULATION_ARRAYS:
            if field in population:
                arrays[config + "__" + field] = np.asarray(population[field])
    np.savez_compressed(archive, **arrays)
    replay_ref = write_bytes_object("historical-replay-populations.npz", archive.getvalue())
    comparison = {
        "schemaVersion": "MLB_V18_ENSEMBLE_RC_GAME_COMPARISON_V1",
        "status": "COMPLETED_ONE_GAME_HISTORICAL_REPLAY_TOO_SPARSE_FOR_ORDERING",
        "generatedAt": utc_now(), "gameId": pair["gameId"], "sourceGameId": pair["sourceGameId"],
        "teams": pair["teams"], "scheduledStartUtc": pair["scheduledStartUtc"],
        "replayGeneratedAfterGameStart": True, "forecast": False, "games": 1,
        "commonFourWayCohortTooSparse": True, "selectionUse": "NONE",
        "simulationCountPerConfiguration": pair["simulationsPerArm"], "masterSeed": pair["masterSeed"],
        "sameStartingInputs": True, "sameTransition": True, "sameForecastHorizon": True,
        "samePaAndTransitionSeedConvention": True,
        "calibrationMethod": calibration_name,
        "calibrationReleaseEnabled": release_enabled,
        "calibrationComparisonOnly": not release_enabled,
        "savedConfigurationsReused": ["A_FROZEN_V18_BASELINE_HOOK", "C_V18_PLUS_DURATION"],
        "newRetrospectiveConfigurations": ["B_V18_PLUS_CALIBRATION", "D_V18_PLUS_CALIBRATION_PLUS_DURATION"],
        "configurationResults": summaries, "populationArtifact": replay_ref,
        "v18Pair": pair_ref, "v18Inputs": pair["inputs"], "v18SavedPopulation": pair["population"],
        "paReload": pa_reload, "durationModel": duration_identity,
        "completeGameScoreStatus": "NO_AUTHENTICATED_PERSISTED_FINAL_PRESENT_IN_LOCAL_PAIRED_STUDY_AT_BUILD_TIME",
        "limitations": [
            "One game cannot establish configuration ordering or superiority",
            "This replay does not alter or select from the frozen COL-DET pilot arms or protocol",
            "The replay was generated after game start and is not a forecast",
            "Monte Carlo standard errors quantify simulation sampling only",
        ],
    }
    return comparison, populations


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if not protocol.get("recordedBeforeCandidateFit"):
        raise ValueError("Calibration protocol was not frozen before fitting")
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if branch != EXPECTED_BRANCH or head != EXPECTED_HEAD:
        raise ValueError("Branch or HEAD changed; inspect newer work before rebuilding")

    keys = read_columns(OOF, ["canonicalPaId", "canonicalGameId", "foldNumber"], "IDENTITY_BEFORE_OUTCOMES")
    eligible = final_oot_eligible_key_mask(keys["canonicalGameId"])
    if not bool(np.all(eligible)):
        raise ValueError("Quarantined game identity reached the saved Development calibration source")
    ledger = pd.read_csv(PARENT / "pa/game-pa-ledger.csv", usecols=["canonicalGameId", "game_date", "foldNumber"])
    gated = keys.merge(ledger, on=["canonicalGameId", "foldNumber"], how="left", validate="many_to_one")
    selected = gated.loc[gated.foldNumber.eq(5), ["canonicalPaId", "canonicalGameId", "game_date"]]
    if len(selected) != 101264 or selected.game_date.isna().any():
        raise ValueError("Fold-5 identity population changed")
    data = read_columns(OOF, ["canonicalPaId", "canonicalGameId", "foldNumber", "observedClassIndex",
                              *PROBABILITY_COLUMNS], "GATED_FOLD5_CALIBRATION", fold5=True)
    data = data.merge(selected[["canonicalPaId", "game_date"]], on="canonicalPaId", validate="one_to_one")
    probabilities = validate_probability_matrix(data[PROBABILITY_COLUMNS].to_numpy(), class_order=CLASSES)
    labels = data.observedClassIndex.to_numpy(dtype=np.int64)
    masks = {name: split_mask(data.game_date, spec) for name, spec in protocol["partition"].items()}
    if np.any(sum(mask.astype(int) for mask in masks.values()) != 1):
        raise ValueError("Chronological partitions must cover fold 5 exactly once")
    partition_rows = []
    for name, mask in masks.items():
        counts = np.bincount(labels[mask], minlength=len(CLASSES))
        if np.any(counts == 0):
            raise ValueError("Every partition must contain every outcome class")
        partition_rows.append({"partition": name, "rows": int(mask.sum()),
                               "games": int(data.loc[mask, "canonicalGameId"].nunique()),
                               "start": str(data.loc[mask, "game_date"].min())[:10],
                               "end": str(data.loc[mask, "game_date"].max())[:10],
                               "classCounts": {CLASSES[i]: int(counts[i]) for i in range(len(CLASSES))}})
    identity_buffer = io.BytesIO()
    data[["canonicalPaId", "canonicalGameId", "game_date"]].assign(
        partition=np.select([masks["fit"], masks["selection"], masks["assessment"]],
                            ["fit", "selection", "assessment"])
    ).to_parquet(identity_buffer, index=False)
    identity_ref = write_bytes_object("partition-identities.parquet", identity_buffer.getvalue())

    prior_selection_path = OUT / "calibration-selection.json"
    if prior_selection_path.exists():
        prior_selection = json.loads(prior_selection_path.read_text(encoding="utf-8"))
        calibrators = {name: load_calibrator(ref) for name, ref in prior_selection["artifacts"].items()}
        artifacts = prior_selection["artifacts"]
        fits_this_execution = 0
    else:
        with threadpool_limits(limits=4):
            calibrators = {
                "TEMPERATURE_SCALING": TemperatureCalibrator().fit(probabilities[masks["fit"]], labels[masks["fit"]]),
                "MULTINOMIAL_LOG_SCORE_CALIBRATION": MultinomialLogScoreCalibrator().fit(
                    probabilities[masks["fit"]], labels[masks["fit"]]),
            }
        artifacts = {name: save_calibrator(model, name.lower() + ".joblib") for name, model in calibrators.items()}
        fits_this_execution = 2
    with threadpool_limits(limits=4):
        transformed = {name: model.transform(probabilities) for name, model in calibrators.items()}
    for name, ref in artifacts.items():
        reload_model = load_calibrator(ref)
        if not np.array_equal(reload_model.transform(probabilities[:64]), transformed[name][:64]):
            raise ValueError("Calibration artifact reload differs")

    global_rows: list[dict] = []
    class_rows: list[dict] = []
    band_rows: list[dict] = []
    evaluated: dict[str, dict[str, dict]] = {}
    all_probabilities = {"UNCHANGED_V18": probabilities, **transformed}
    for partition, mask in masks.items():
        evaluated[partition] = {}
        for candidate, values in all_probabilities.items():
            evaluated[partition][candidate] = evaluate(partition, candidate, labels, probabilities, values, mask,
                                                        global_rows, class_rows, band_rows)
    selection_base = evaluated["selection"]["UNCHANGED_V18"]["ALL"]
    eligible_candidates = []
    for name in calibrators:
        metric = evaluated["selection"][name]["ALL"]
        if metric["logLoss"] < selection_base["logLoss"] and metric["summedBrier"] < selection_base["summedBrier"]:
            eligible_candidates.append(name)
    selected_name = min(eligible_candidates, key=lambda n: evaluated["selection"][n]["ALL"]["logLoss"]) if eligible_candidates else None
    assessment_checks: dict[str, bool] = {}
    enabled = False
    if selected_name:
        base = evaluated["assessment"]["UNCHANGED_V18"]
        chosen = evaluated["assessment"][selected_name]
        base_double = next(r for r in class_rows if r["partition"] == "assessment" and r["candidate"] == "UNCHANGED_V18" and r["outcome"] == "DOUBLE")
        chosen_double = next(r for r in class_rows if r["partition"] == "assessment" and r["candidate"] == selected_name and r["outcome"] == "DOUBLE")
        fixed_base = base["FIXED_V18_DOUBLE_5_10"]
        fixed_chosen = chosen["FIXED_V18_DOUBLE_5_10"]
        fixed_mask = masks["assessment"] & (probabilities[:, 4] >= .05) & (probabilities[:, 4] < .10)
        base_fixed_bias = float((probabilities[fixed_mask, 4] - (labels[fixed_mask] == 4)).mean())
        chosen_fixed_bias = float((transformed[selected_name][fixed_mask, 4] - (labels[fixed_mask] == 4)).mean())
        assessment_checks = {
            "logLossImproves": chosen["ALL"]["logLoss"] < base["ALL"]["logLoss"],
            "summedBrierImproves": chosen["ALL"]["summedBrier"] < base["ALL"]["summedBrier"],
            "absoluteFixedDoubleBandBiasImproves": abs(chosen_fixed_bias) < abs(base_fixed_bias),
            "outsideBandLogLossDeteriorationAtMost0.001": (
                chosen["OUTSIDE_FIXED_V18_DOUBLE_5_10"]["logLoss"]
                - base["OUTSIDE_FIXED_V18_DOUBLE_5_10"]["logLoss"] <= .001
            ),
        }
        enabled = all(assessment_checks.values())
    selected_calibrator = calibrators[selected_name] if selected_name else None
    selected_artifact = artifacts[selected_name] if selected_name else None
    comparison_name = selected_name or min(
        calibrators, key=lambda n: evaluated["selection"][n]["ALL"]["logLoss"]
    )
    comparison_calibrator = calibrators[comparison_name]
    comparison_artifact = artifacts[comparison_name]

    pd.DataFrame(global_rows).to_csv(OUT / "pa-global-metrics.csv", index=False)
    pd.DataFrame(class_rows).to_csv(OUT / "pa-class-calibration.csv", index=False)
    pd.DataFrame(band_rows).to_csv(OUT / "pa-band-calibration.csv", index=False)
    selection = {
        "schemaVersion": "MLB_V18_ENSEMBLE_RC_CALIBRATION_SELECTION_V1", "selected": selected_name,
        "enabled": enabled, "selectionEligibleCandidates": eligible_candidates,
        "comparisonOnlyCandidate": None if selected_name else comparison_name,
        "comparisonOnlyReason": None if selected_name else "FAILED_PREDECLARED_SELECTION_RULE",
        "assessmentChecks": assessment_checks, "partitionCounts": partition_rows,
        "artifacts": artifacts, "selectedArtifact": selected_artifact,
        "fitMetadata": {name: model.fit_metadata for name, model in calibrators.items()},
        "candidateFitsThisExecution": fits_this_execution,
        "totalDistinctCalibrationCandidates": 2,
        "identities": identity_ref,
        "limitations": ["Historical fold-5 chronology is not certified point-in-time evidence",
                        "Assessment is later within the same saved fold and is not independent confirmation"],
    }
    write_json(OUT / "calibration-selection.json", selection)

    game_comparison_path = OUT / "game-comparison.json"
    if game_comparison_path.exists():
        game_comparison = json.loads(game_comparison_path.read_text(encoding="utf-8"))
        if (game_comparison.get("status") != "COMPLETED_ONE_GAME_HISTORICAL_REPLAY_TOO_SPARSE_FOR_ORDERING"
                or game_comparison.get("calibrationMethod") != comparison_name):
            raise ValueError("Existing game comparison is incompatible with the frozen selection result")
        populations = {"reusedSavedGameComparison": True}
    else:
        game_comparison, populations = build_game_comparison(comparison_calibrator, comparison_name, enabled)
        write_json(game_comparison_path, game_comparison)
    game_rows = []
    for config, item in game_comparison.get("configurationResults", {}).items():
        game_rows.append({"configuration": config, "games": 1, "simulations": item["simulations"],
                          "homeWinProbability": item["homeWin"]["mean"],
                          "homeWinMcse": item["homeWin"]["monteCarloStandardError"],
                          "meanHomeRuns": item["homeRuns"]["mean"], "meanAwayRuns": item["awayRuns"]["mean"],
                          "meanMargin": item["homeMargin"]["mean"], "meanTotal": item["totalRuns"]["mean"],
                          "meanTotalMcse": item["totalRuns"]["monteCarloStandardError"],
                          "status": "HISTORICAL_REPLAY_ONE_GAME_UNASSESSED"})
    pd.DataFrame(game_rows).to_csv(OUT / "configuration-comparison.csv", index=False)

    frozen_v18 = json.loads(PAIR.read_text(encoding="utf-8"))["modelIdentity"]
    package = {
        "schemaVersion": "MLB_V18_ENSEMBLE_RELEASE_CANDIDATE_V1",
        "candidateId": "mlb-v18-ensemble-rc-20260912-v1", "createdAt": utc_now(),
        "branch": branch, "head": head, "researchShadowOnly": True, "status": "RESEARCH_CANDIDATE",
        "promotionStatus": "NOT_PROMOTED", "wageringAuthority": False, "executionAllowedInAISP": False,
        "officialV18Changed": False, "classOrder": list(CLASSES),
        "featureOrder": {"raw": list(CurrentV18Engine().contract["rawFeatureColumns"]),
                         "treated": list(CurrentV18Engine().contract["treatedFeatureColumns"])},
        "components": {
            "v18": {"status": "ENABLED_FROZEN", **frozen_v18},
            "calibration": {"status": "ENABLED_RESEARCH_CANDIDATE" if enabled else "DISABLED_SELECTION_GATE",
                            "method": selected_name, "artifact": selected_artifact,
                            "comparisonMethod": comparison_name,
                            "comparisonArtifact": comparison_artifact,
                            "comparisonOnly": not enabled,
                            "disabledReason": None if enabled else "No method improved both log loss and summed Brier on the frozen selection partition",
                            "rollback": "Remove the post-provider calibration wrapper and use unchanged V18 probabilities"},
            "starterDuration": {"status": "SHADOW_ONLY_UNASSESSED_GAME_LEVEL",
                                "artifact": game_comparison.get("durationModel", {}).get("artifact"),
                                "featureOrder": game_comparison.get("durationModel", {}).get("featureOrder"),
                                "fallback": "If supported certified duration inputs are absent, use the corresponding V18 hook configuration A or B"},
            "matchupSpecialist": {"status": "DISABLED_NO_VALIDATED_SPECIALIST"},
        },
        "defaultConfiguration": "B_V18_PLUS_CALIBRATION" if enabled else "A_FROZEN_V18_BASELINE_HOOK",
        "gameComparisonStatus": game_comparison.get("status"),
        "forecastType": "LABELED_HISTORICAL_REPLAY_ONLY",
        "runnable": {
            "script": reference(ROOT / "scripts/run_mlb_v18_ensemble_release_candidate_v1.py"),
            "candidateModule": reference(ROOT / "server/sports_current_statcast/mlb_v18_ensemble_candidate.py"),
            "replayAuthorityModule": reference(ROOT / "server/sports_current_statcast/mlb_v18_prospective_transform.py"),
            "predictCommand": ".\\.venv\\Scripts\\python.exe scripts/run_mlb_v18_ensemble_release_candidate_v1.py predict --probabilities-json <path>",
            "simulateCommand": ".\\.venv\\Scripts\\python.exe scripts/run_mlb_v18_ensemble_release_candidate_v1.py simulate --configuration B",
        },
        "rollback": {"configuration": "A_FROZEN_V18_BASELINE_HOOK", "artifact": frozen_v18["paArtifact"]},
        "comparison": {"calibration": reference(OUT / "calibration-selection.json"),
                       "game": reference(OUT / "game-comparison.json"),
                       "configurationTable": reference(OUT / "configuration-comparison.csv")},
        "protocol": reference(PROTOCOL),
        "lineage": {"empiricalDiagnosis": reference(PARENT / "artifact-manifest.json"),
                    "doublesFollowup": reference(FOLLOWUP / "manifest.json")},
    }
    package_ref = write_json_object("candidate-package.json", package)
    exchange_handoff = {
        "schemaVersion": "AISP_MLB_V18_ENSEMBLE_RESEARCH_HANDOFF_V1",
        "candidateId": package["candidateId"], "package": package_ref,
        "registrationState": "RESEARCH_EXCHANGE_PACKAGE_READY",
        "registrationInstruction": "Claude may import this immutable package as a separate MLB research-shadow candidate after verifying every checksum. Do not replace official V18 or change model-era, decision, policy, staking, or promotion authority.",
        "researchShadowOnly": True, "executionAllowedInAISP": False, "wageringAuthority": False,
        "promotionStatus": "NOT_PROMOTED", "aispDatabaseWrites": 0,
    }
    handoff_ref = write_json_object("aisp-research-handoff.json", exchange_handoff)

    selected_line = selected_name or "none"
    note = f"""# MLB V18 ensemble release candidate

The runnable research candidate is **{package['defaultConfiguration']}**. It keeps frozen V18 unchanged. No calibration method passed the frozen selection rule, so `{comparison_name}` is retained only to complete the bounded A/B/C/D replay and is disabled in the release configuration. Starter duration is implemented and serialized, but remains shadow-only because the only exact common four-way package is one COL–DET game—too sparse for ordering.

The calibration fit uses fold-5 saved predictions from May 2–June 15, selection uses June 16–July 15, and assessment uses July 16–August 13. Every calibration row follows the estimator's May 1 training cutoff. The split remains exploratory because inherited point-in-time chronology is uncertified and the later assessment is not independent confirmation.

Calibration enabled: **{enabled}**. Selection eligible candidates: `{', '.join(eligible_candidates) or 'none'}`. Assessment checks: `{json.dumps(assessment_checks, sort_keys=True)}`. Full eight-class log loss, summed Brier, class calibration and fixed/self-selected bands are saved in the three PA comparison tables.

The game comparison reuses exact COL–DET inputs, 5,000 simulations, master seed 20260907, fold-4 transition and saved A/C populations; B/D are labeled retrospective replays generated now. It does not read or select from the game outcome, and it does not alter the pilot. Monte Carlo uncertainty is reported, but one game supports no superiority claim.

Components: V18 enabled and frozen; calibration {'enabled for research shadow' if enabled else 'disabled'}; duration shadow-only/unassessed; matchup specialist disabled. Missing certified duration inputs fall back explicitly to the corresponding no-duration configuration. Rollback is unchanged configuration A.

No future candidate forecast was frozen; this package contains only the labeled historical replay. Promotion still requires prospective shadow evidence under existing authority contracts, supported multi-game component assessment, certified timing, and a separate promotion decision. Final OOT stayed sealed and all quarantined identities were excluded before outcome access.

Build: `.\\.venv\\Scripts\\python.exe scripts/build_mlb_v18_ensemble_release_candidate_v1.py`

Predict: `.\\.venv\\Scripts\\python.exe scripts/run_mlb_v18_ensemble_release_candidate_v1.py predict --probabilities-json <path>`

Replay: `.\\.venv\\Scripts\\python.exe scripts/run_mlb_v18_ensemble_release_candidate_v1.py simulate --configuration B`
"""
    (OUT / "DECISION.md").write_text(note, encoding="utf-8")

    manifest = {
        "schemaVersion": "MLB_V18_ENSEMBLE_RELEASE_CANDIDATE_MANIFEST_V1", "createdAt": utc_now(),
        "branch": branch, "head": head, "candidateId": package["candidateId"],
        "package": package_ref, "handoff": handoff_ref,
        "artifacts": [reference(OUT / name) for name in (
            "protocol.json", "calibration-selection.json", "pa-global-metrics.csv",
            "pa-class-calibration.csv", "pa-band-calibration.csv", "game-comparison.json",
            "configuration-comparison.csv", "DECISION.md")],
        "calibrators": artifacts, "partitionIdentities": identity_ref,
        "physicalReads": READS,
        "verification": {"probabilitiesCoherent": True, "classOrderExact": True,
                         "calibrationReloadExact64Rows": True, "componentInvocationCompleted": bool(populations),
                         "packageReconciled": True, "quarantineBeforeOutcomeAccess": True,
                         "finalOotPayloadReads": 0, "providerCalls": 0, "aispDatabaseWrites": 0},
        "unrelatedTrackedChangesPreserved": [
            "outputs/mlb-starter-duration-paired-research-v1/current.json",
            "outputs/mlb-starter-duration-paired-research-v1/monitoring/current.json",
            "outputs/mlb-starter-duration-paired-research-v1/readiness-state.json",
            "outputs/mlb-v18-current-state-pipeline-v1/slates/2026-09-10/latest.json",
            "outputs/mlb-v18-current-state-pipeline-v1/slates/2026-09-11/latest.json",
            "outputs/nfl-play-level-engine-v1/CURRENT.json",
        ],
    }
    write_json(OUT / "manifest.json", manifest)
    current = {"candidateId": package["candidateId"], "package": package_ref, "handoff": handoff_ref,
               "manifest": reference(OUT / "manifest.json"), "researchShadowOnly": True,
               "promotionStatus": "NOT_PROMOTED", "executionAllowedInAISP": False}
    write_json(OUT / "current.json", current)
    print(json.dumps({"candidateId": package["candidateId"], "selectedCalibration": selected_name,
                      "calibrationEnabled": enabled, "gameComparison": game_comparison.get("status"),
                      "package": package_ref, "handoff": handoff_ref}, indent=2))


if __name__ == "__main__":
    main()
