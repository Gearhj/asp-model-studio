"""Verify one completed historical close-score replay; never regenerate a forecast.

The input is the lossless original paired count table, expanded in canonical
HOME/AWAY cell and replica order. This is not the original random sample order.
No fitting, donor sampling, provider access, publication, or existing file writes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from server.sports_nba_gen1.authority import json_bytes, reference, verified_bytes

DEFAULT = ROOT / "outputs/nba-gen1-close-score-v1/completed"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def same(left, right):
    """Parquet nullable scalar equality, including the no-pick value."""
    if pd.isna(left) or pd.isna(right):
        return bool(pd.isna(left) and pd.isna(right))
    return bool(left == right)


def one(frame, label):
    require(len(frame) == 1, f"Expected one {label}, found {len(frame)}")
    return frame.iloc[0]


def cells(frame, expected_draws):
    columns = ["home_score", "away_score", "count"]
    result = frame.sort_values(columns[:2])[columns].to_numpy()
    require(result.ndim == 2 and result.shape[0] > 0, "Missing retained game cells")
    require(np.issubdtype(result.dtype, np.integer), "Noninteger retained cells")
    result = result.astype(np.int64)
    require((result[:, :2] >= 0).all() and (result[:, 0] != result[:, 1]).all(), "Invalid NBA final-score support")
    require((result[:, 2] > 0).all() and int(result[:, 2].sum()) == expected_draws, "Retained count denominator differs")
    require(len(np.unique(result[:, :2], axis=0)) == len(result), "Duplicate retained joint cell")
    return result, digest(result.astype("<i8").tobytes())


def replay(game_id):
    # Completion is required before opening assessment labels, including 2024-26.
    run_path = DEFAULT / "run-receipt.json"
    require(run_path.is_file(), "Assessment is not complete; wait for its existing run-receipt, without rerunning it")
    bindings = {}

    def verify(bound):
        key = str(Path(bound["path"]).resolve())
        if key in bindings:
            require(bindings[key] == bound, "Conflicting physical artifact bindings: " + key)
            return
        verified_bytes(bound)
        bindings[key] = {k: bound[k] for k in ("path", "sha256", "bytes")}

    def read(bound):
        verify(bound)
        return json.loads(Path(bound["path"]).read_bytes())

    def named(refs, path):
        target = Path(path).resolve()
        matches = [r for r in refs if Path(r["path"]).resolve() == target]
        require(len(matches) == 1, "Missing unique bound artifact: " + str(target))
        verify(matches[0])
        return matches[0]

    run = read(reference(run_path))
    require(run.get("originalCohortExact") is True and run.get("originalSimulationReexecuted") is False,
            "Completed retained-population run receipt required")
    method_ref = reference(DEFAULT / "method-freeze.json")
    method = read(method_ref)
    require(method["schema"] == "NBA_GEN1_CLOSE_SCORE_METHOD_FREEZE_V1" and method["drawCount"] == 10000,
            "Unsupported frozen close-score method")
    for bound in method["code"]:
        verify(bound)
    original_index = read(method["parent"])
    original_root = Path(method["parent"]["path"]).parent
    original_method = read(method["parentMethod"])
    for bound in original_index["code"]:
        verify(bound)
    # The original index binds the final assessment CLI; its older method binds
    # the unchanged numerical sampler/scorers after the separately retained fix.
    for bound in original_method["code"][1:]:
        verify(bound)
    cohort = read(method["parentCohort"])
    named(original_index["artifacts"], method["parentMethod"]["path"])
    named(original_index["artifacts"], method["parentCohort"]["path"])
    identities = [g["game_id"] for g in cohort["eligible"]]
    require(len(set(identities)) == len(identities) == run["games"], "Completed cohort identity/count mismatch")
    require(digest("\n".join(identities).encode()) == method["cohort"]["eligibleIdentitySha256"], "Original cohort changed")
    matches = [g for g in cohort["eligible"] if g["game_id"] == game_id]
    require(len(matches) == 1, "Requested game is not uniquely in the original eligible cohort")
    target = matches[0]
    season, date = int(target["season_end"]), str(target["game_date"])
    require(run["candidateDraws"] == len(identities) * method["drawCount"], "Completed run denominator mismatch")
    for year, count in method["cohort"]["seasons"].items():
        receipt = read(reference(DEFAULT / "assessment" / str(year) / "receipt.json"))
        require(receipt["frozenMethod"] == method_ref and receipt["games"] == count,
                "Season receipt does not complete the declared cohort")

    original_folder = original_root / "assessment" / str(season)
    candidate_folder = DEFAULT / "assessment" / str(season)
    original_receipt = read(named(original_index["artifacts"], original_folder / "receipt.json"))
    candidate_receipt = read(reference(candidate_folder / "receipt.json"))
    require(original_receipt["method"] == method["parentMethod"], "Original season method binding differs")
    for filename in ("scores.parquet", "populations.parquet", "paired-joint-counts.parquet"):
        path = original_folder / filename
        require(named(original_receipt["artifacts"], path) == named(original_index["artifacts"], path),
                "Original season/index physical bindings differ")
    for filename in ("scores.parquet", "transformations.parquet", "joint-counts.parquet"):
        named(candidate_receipt["artifacts"], candidate_folder / filename)

    diagnosis = read(method["developmentDiagnosis"])
    verify(diagnosis["calibrationGames"])
    # Identity/date projection only: do not refit the kernel or reinterpret labels.
    dev = pd.read_parquet(diagnosis["calibrationGames"]["path"], columns=["game_id", "game_date", "season_end"])
    require(len(dev) == diagnosis["games"] == 3338 and set(dev.season_end) <= {2021, 2022, 2023},
            "Calibration metadata escapes the frozen Development population")
    require(not dev.game_id.duplicated().any(), "Duplicate calibration game")
    require(dev.equals(dev.sort_values(["game_date", "game_id"]).reset_index(drop=True)), "Calibration prefix order changed")
    cutoff = int(np.searchsorted(dev.game_date.to_numpy(), date, side="left"))
    prior_ids = dev.iloc[:cutoff].game_id.tolist()
    latest = None if cutoff == 0 else str(dev.iloc[cutoff-1].game_date)
    require(game_id not in prior_ids and (latest is None or latest < date), "Calibration chronology violated")
    kernel_ref = reference(DEFAULT / "kernel-artifacts.json")
    kernels = read(kernel_ref)
    kid = kernels["kernelByDate"][date]
    wrapper = kernels["kernels"][kid]
    require(digest(json_bytes(wrapper)) == kid, "Kernel wrapper identity differs")
    require(wrapper["calibrationLatestDate"] == latest and
            wrapper["calibrationGameIdentitySha256"] == digest("\n".join(prior_ids).encode()) and
            wrapper["kernel"]["calibrationGames"] == cutoff, "Saved kernel does not bind the exact earlier Development prefix")
    frozen = read(method["frozenDevelopmentKernel"])
    if season > 2023:
        require(cutoff == 3338 and wrapper["kernel"] == frozen["kernel"] and
                latest == frozen["calibrationLastDate"] and
                wrapper["calibrationGameIdentitySha256"] == frozen["calibrationGameIdentitySha256"],
                "Later assessment did not use the unchanged frozen Development kernel")
    # If the completed delivery index is present, also enforce its physical refs.
    index_path = DEFAULT / "index.json"
    if index_path.exists():
        index = read(reference(index_path))
        for path in (run_path, method_ref["path"], kernel_ref["path"], candidate_folder / "receipt.json"):
            named(index["artifacts"], path)

    # Import numerical code only after verifying its declared physical bindings.
    from server.sports_nba_gen1.close_score import CONFIGURATION, transform
    from server.sports_nba_gen1.joint_residual import joint_counts, totals_query
    from scripts.run_nba_gen1_joint_residual import score
    require(method["engine"] == kernels["engine"] == CONFIGURATION, "Component configuration mismatch")
    baseline = one(pd.read_parquet(original_folder / "scores.parquet",
                   filters=[("game_id", "==", game_id), ("configuration", "==", "paired")]), "baseline score")
    candidate = one(pd.read_parquet(candidate_folder / "scores.parquet", filters=[("game_id", "==", game_id)]), "candidate score")
    effect = one(pd.read_parquet(candidate_folder / "transformations.parquet", filters=[("game_id", "==", game_id)]), "transformation")
    population = one(pd.read_parquet(original_folder / "populations.parquet",
                     filters=[("game_id", "==", game_id), ("configuration", "==", "paired")]), "original population")
    game_index = int(baseline.game_index)
    for row in (baseline, candidate, effect, population):
        require(int(row.game_index) == game_index, "Saved game index mismatch")
    for row in (baseline, candidate, effect):
        require(str(row.game_date) == date, "Saved game date mismatch")
    require(candidate.configuration == "close_score" and candidate.kernel_id == effect.kernel_id == kid,
            "Candidate and transformation do not bind the saved daily kernel")
    require(int(effect.calibration_games) == cutoff and same(effect.calibration_latest_date, latest),
            "Transformation calibration prefix mismatch")
    require(bool(candidate.correction_supported) == bool(effect.correction_supported) == wrapper["kernel"]["ready"],
            "Supported/fallback disposition differs")
    original_cells, original_sha = cells(pd.read_parquet(original_folder / "paired-joint-counts.parquet",
                                         filters=[("game_index", "==", game_index)]), method["drawCount"])
    require(original_sha == population.joint_counts_int64_le_sha256 == effect.original_joint_counts_sha256,
            "Original retained population digest differs")
    draws = np.repeat(original_cells[:, :2], original_cells[:, 2], axis=0)
    changed, summary = transform(draws, game_id, wrapper["kernel"])
    require(json.loads(effect.effects_json) == summary, "Deterministic transformation accounting differs")
    candidate_draw_sha = digest(changed.astype("<i8").tobytes())
    require(candidate_draw_sha == effect.canonical_candidate_draws_sha256, "Candidate canonical replica draw digest differs")
    pairs, frequencies = joint_counts(changed)
    replay_cells = np.column_stack([pairs, frequencies])
    retained_cells, retained_sha = cells(pd.read_parquet(candidate_folder / "joint-counts.parquet",
                                         filters=[("game_index", "==", game_index)]), method["drawCount"])
    require(np.array_equal(replay_cells, retained_cells), "Replayed candidate measure differs from actual retained cells")
    require(digest(replay_cells.astype("<i8").tobytes()) == retained_sha == effect.candidate_joint_counts_sha256,
            "Candidate joint count digest differs")
    require(np.array_equal(draws.sum(axis=1), changed.sum(axis=1)) and
            np.array_equal(draws[:, 0] > draws[:, 1], changed[:, 0] > changed[:, 1]), "Total/winner invariant violated")
    outer = abs(draws[:, 0] - draws[:, 1]) > 8
    require(np.array_equal(draws[outer], changed[outer]), "Outer-margin paired scores changed")
    for name in ("actual_home", "actual_away", "elo_home_win_probability", "ridge_expected_home", "ridge_expected_away"):
        require(same(baseline[name], candidate[name]), "Unchanged metadata differs: " + name)
    changed_count = int(np.any(draws != changed, axis=1).sum())
    require(changed_count == effect.changed_draw_count, "Changed replica count differs")
    for name, column in (("home", 0), ("away", 1)):
        require(float((changed[:, column] - draws[:, column]).mean()) == effect[name + "_mean_change"], "Per-draw mean effect differs")
    for k in range(1, 9):
        require(float((abs(changed[:, 0]-changed[:, 1]) == k).mean()) == candidate[f"abs_margin_{k}_probability"], "Candidate close-margin mass differs")
        require(float((abs(draws[:, 0]-draws[:, 1]) == k).mean()) == candidate[f"baseline_abs_margin_{k}_probability"], "Original close-margin mass differs")

    total_keys = [key for key in baseline.index if key.startswith("total_")]
    winner_keys = ["home_win_probability", "away_win_probability", "tie_probability", "log_loss", "binary_brier"]
    for key in total_keys + winner_keys:
        require(same(baseline[key], candidate[key]), "Invariant saved score differs: " + key)
    recomputed = score(changed, int(baseline.actual_home), int(baseline.actual_away))
    roundoff = {}
    exact_metrics = []
    if changed_count:
        for key, value in recomputed.items():
            if key.startswith("total_"):
                error = abs(float(value) - float(candidate[key]))
                require(error <= 1e-12, "Total score exceeds declared order-roundoff tolerance: " + key)
                if error:
                    roundoff[key] = error
            else:
                require(same(value, candidate[key]), "Recomputed candidate metric differs exactly: " + key)
                exact_metrics.append(key)
        score_status = "CANDIDATE_NON_TOTAL_METRICS_RECOMPUTED_EXACTLY; ORIGINAL_TOTAL_VALUES_RETAINED"
    else:
        for key in recomputed:
            require(same(baseline[key], candidate[key]), "Exact fallback saved metric differs: " + key)
        score_status = "EXACT_BASELINE_FALLBACK_METRICS_RETAINED; NO_BITWISE_RANDOM_ORDER_RESCORING_CLAIM"
    queries = []
    for line in (225, 225.5):
        original_query, candidate_query = totals_query(draws, line), totals_query(changed, line)
        require(original_query == candidate_query, "Invariant totals query differs")
        require(line == 225 or candidate_query["over"]["push"] == 0, "Half-point push mass is nonzero")
        queries.append({"baselineEqualsCandidate": True, **candidate_query})
    metric_names = ["energy", "home_crps", "away_crps", "margin_crps", "total_crps", "log_loss", "binary_brier",
                    "home_mean", "away_mean", "margin_mean", "total_mean", "one_point_probability"]
    metrics = {k: {"baseline": float(baseline[k]), "candidate": float(candidate[k]),
                   "candidateMinusBaseline": float(candidate[k] - baseline[k])} for k in metric_names}
    return {
        "schema": "NBA_GEN1_CLOSE_SCORE_ONE_GAME_REPLAY_V1", "verifiedAtUtc": datetime.now(timezone.utc).isoformat(),
        "gameId": game_id, "gameDate": date, "seasonEnd": season, "configuration": CONFIGURATION,
        "evidenceClassification": "REUSED_CATEGORY_A_HISTORICAL_RESEARCH; NOT_A_NEW_FORECAST",
        "kernelId": kid, "innerKernelSha256": wrapper["kernel"]["kernelSha256"],
        "calibrationGames": cutoff, "calibrationLatestDate": latest,
        "calibrationIdentitySha256": wrapper["calibrationGameIdentitySha256"],
        "supported": bool(wrapper["kernel"]["ready"]), "drawCount": len(changed), "changedDrawCount": changed_count,
        "originalJointCountsSha256": original_sha, "candidateJointCountsSha256": retained_sha,
        "canonicalCandidateDrawsSha256": candidate_draw_sha,
        "checks": {"kernelChronologyAndIdentity": True, "retainedCandidateCellsExact": True,
                   "originalInputPopulationUnchanged": True, "everyTotalAndWinnerExact": True,
                   "outerMarginPairsExact": True, "originalTotalAndWinnerMetricsExact": True,
                   "candidateNonTotalMetricExactCount": len(exact_metrics)},
        "scoreReproduction": score_status, "totalOrderRoundoff": roundoff, "metrics": metrics,
        "jointHomeWinProbability": float(candidate.home_win_probability),
        "jointAwayWinProbability": float(candidate.away_win_probability), "jointTieProbability": 0.0,
        "separateEloHomeWinProbability": float(candidate.elo_home_win_probability),
        "probabilityUnits": "FRACTIONS_0_TO_1", "illustrativeTotalsQueries": queries,
        "orderQualification": "Canonical HOME/AWAY cell then replica; original temporal draw order is not claimed",
        "scoringQualification": "Lower proper scores are better; one historical game is not evidence of recurring improvement",
        "originalSimulationReexecuted": False, "modelRefitted": False, "consumerPublication": False,
        "numericalForecastsWritten": 0, "physicalBindings": list(bindings.values()), "replayCode": reference(__file__),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--output", type=Path, help="Optional NEW immutable verification receipt; an existing path is rejected")
    args = parser.parse_args()
    if args.output is not None:
        require(not args.output.exists(), "Verification output already exists; refusing overwrite")
    receipt = replay(args.game_id)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("xb") as handle:
            handle.write(json_bytes(receipt))
    concise = {k: v for k, v in receipt.items() if k not in ("physicalBindings", "replayCode")}
    concise["verifiedPhysicalArtifacts"] = len(receipt["physicalBindings"])
    if args.output is not None:
        concise["verificationReceipt"] = reference(args.output)
    print(json.dumps(concise, indent=2, sort_keys=True, allow_nan=False))
