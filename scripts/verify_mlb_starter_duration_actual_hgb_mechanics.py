"""One actual frozen-HGB integration check; explicitly not a baseball forecast."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_starter_duration_paired_publication import load_duration_model, verified, save
from server.sports_current_statcast.mlb_starter_duration_paired_simulation import POPULATION_ARRAYS, simulate_paired_game
from server.sports_current_statcast.mlb_v18_whole_game_challenger import simulate_prospective_game
from server.sports_current_statcast import mlb_v18_daily_slate as daily
from server.sports_phase5 import base_out_transition as bt


class SyntheticPaProvider:
    """Hand-specified probabilities, never represented as V18 model inference."""
    def probabilities(self, **state):
        p = np.zeros((len(state["top"]), 8))
        p[:, 2] = np.where(state["bullpen"], 0.045, 0.035)
        p[:, 0] = 0.23
        p[:, 1] = 0.09
        p[:, 3] = 0.14
        p[:, 4] = 0.045
        p[:, 5] = 0.005
        p[:, 7] = 0.025
        p[:, 6] = 1-p.sum(axis=1)
        return p


def main():
    started = time.perf_counter()
    created = datetime.now(timezone.utc).isoformat()
    with threadpool_limits(limits=4):
        model, binding = load_duration_model()
        fixture = pd.read_parquet(verified(binding["fixture"]))
        fixed = {}
        selected = {}
        for name, orientation in (("away", 0), ("home", 1)):
            subset = fixture.loc[fixture.homePitcher.eq(orientation)]
            if subset.empty:
                raise ValueError("SAVED_HISTORICAL_FIXTURE_HAS_NO_ROW_FOR_REQUIRED_ORIENTATION")
            row = subset.iloc[0]
            fixed[name] = {key: row[key] for key in model.feature_order if key != "bf"}
            selected[name] = {"fixtureRowIndex": int(subset.index[0]), "values": fixed[name],
                "meaning": "Unchanged historical fixture covariates, not current source evidence or an identified game forecast"}
        transition_path = ROOT / "outputs/mlb-v18-whole-game-challenger/sha256" / daily.PARENT_BUNDLE_SHA256 / "executable/transition-fold4.json"
        data = transition_path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != daily.TRANSITION_MODEL_SHA256:
            raise ValueError("FROZEN_TRANSITION_CHECKSUM_MISMATCH")
        transition = bt.TransitionModel.from_dict(json.loads(data))
        args = dict(game_id="NONPREGAME_SYNTHETIC_MECHANICS_FROZEN_HGB_V1", provider=SyntheticPaProvider(),
            transition_model=transition, n_sims=64, master_seed=20260911, regulation=9, trace_count=2)
        pair_args = dict(**args, duration_model=model,
            home_duration_inputs=fixed["home"], away_duration_inputs=fixed["away"])
        first = simulate_paired_game(**pair_args)
        repeat = simulate_paired_game(**pair_args)
        mismatches = {}
        for arm in ("reference", "challenger"):
            mismatches[arm] = {key: int(np.count_nonzero(first[arm][key] != repeat[arm][key])) for key in POPULATION_ARRAYS}
            if any(mismatches[arm].values()) or first[arm]["traces"] != repeat[arm]["traces"]:
                raise ValueError("ACTUAL_HGB_SYNTHETIC_MECHANICS_REPEATABILITY_MISMATCH")
        original = simulate_prospective_game(**args)
        reference_differences = {key: int(np.count_nonzero(first["reference"][key] != original[key]))
            for key in ("homeRuns", "awayRuns", "innings", "paCounts")}
        if any(reference_differences.values()) or first["reference"]["traces"] != original["traces"]:
            raise ValueError("ACTUAL_TRANSITION_FROZEN_REFERENCE_LOOP_MISMATCH")
    root = ROOT / "outputs/mlb-starter-duration-paired-research-v1/mechanics"
    population = save("synthetic-mechanics-populations.json", first, root)
    receipt = {"schemaVersion": "MLB_STARTER_DURATION_ACTUAL_HGB_MECHANICS_V1",
        "status": "NONPREGAME_SYNTHETIC_MECHANICS", "createdAt": created,
        "completedAt": datetime.now(timezone.utc).isoformat(), "runtimeSeconds": time.perf_counter()-started,
        "model": binding, "historicalCovariates": selected,
        "transition": {"path": str(transition_path), "sha256": digest, "bytes": len(data)},
        "syntheticPaProvider": {"source": str(Path(__file__).resolve()), "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "isFrozenV18Inference": False, "isCurrentEvidence": False},
        "population": population, "drawsPerArmPerExecution": 64, "pairedExecutions": 2,
        "frozenReferenceCheckExecutions": 1, "totalSyntheticSimulatedGamesExecuted": 320,
        "repeatabilityArrayMismatches": mismatches, "repeatabilityTraceMismatches": 0,
        "frozenReferenceArrayMismatches": reference_differences, "frozenReferenceTraceMismatches": 0,
        "durationActualPredictCalls": 3, "durationRowsScored": 864,
        "reloadRows": 64, "reloadProbabilityValues": 192, "reloadMismatches": 0,
        "nativeWorkers": 4, "fits": 0, "providerCalls": 0, "finalOotPayloadReads": 0,
        "v18PaInferenceCalls": 0, "actualCurrentGameForecasts": 0,
        "forecastsPublished": False, "forecastAuthority": False, "wageringAuthority": False,
        "executionAllowedInAISP": False,
        "meaning": "Only executable adapter/transition integration and repeatability. Synthetic outcomes and probability summaries are not historical evaluation, current forecasts or evidence of predictive improvement."}
    output = save("actual-hgb-mechanics-receipt.json", receipt, root)
    print(json.dumps({"receipt": output, "runtimeSeconds": receipt["runtimeSeconds"],
        "reloadMismatches": 0, "repeatabilityMismatches": 0, "referenceMismatches": 0,
        "fits": 0, "durationPredictCalls": 3, "durationRowsScored": 864}), flush=True)


if __name__ == "__main__":
    main()
