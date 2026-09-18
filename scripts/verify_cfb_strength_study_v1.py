"""Independent bounded verification of completed private CFB strength research.

This program makes no acquisitions, fits no model, and writes only a verification
receipt beneath the study output. Run only after the Development freeze and the
separate reused-assessment stage have completed. No 2026 rows are materialized.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_cfb_gen1 import pipeline

DEFAULT_OUT = Path(r"C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1")
ARMS = ("baseline", "A", "B", "U_A", "U_B")
METRICS = ("jointEnergyScore", "jointWinnerLogLoss", "jointBinaryBrier", "marginCrps", "totalCrps",
           "scoreAbsoluteError", "marginAbsoluteError", "totalAbsoluteError")


def require(condition, message):
    if not bool(condition):
        raise AssertionError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


class Reader:
    def __init__(self):
        self.refs = {}

    def bind(self, path):
        item = ref(path)
        self.refs[item["path"]] = item
        return item

    def json(self, path):
        self.bind(path)
        return json.loads(Path(path).read_bytes())

    def parquet(self, path, **kwargs):
        self.bind(path)
        frame = pd.read_parquet(path, **kwargs)
        if "season" in frame:
            require(frame.season.le(2025).all(), f"2026 row materialized: {path}")
        return frame

    def artifact(self, path):
        self.bind(path)
        return joblib.load(path)


def independent_lambda(grid, target_season):
    earlier = grid[(grid.season < target_season) & grid.season.between(2017, 2022)]
    if earlier.season.nunique() < 2:
        return 12.0
    means = {penalty: float(earlier.loc[earlier.lambda_prior.eq(penalty), "jointEnergyScore"].mean())
             for penalty in (4.0, 12.0)}
    require(all(np.isfinite(list(means.values()))), "incomplete Development grid")
    return 12.0 if means[12.0] <= min(means.values()) + 0.005 else 4.0


def independent_paired_bootstrap(base, candidate, repetitions=2000):
    """Use block multiplicities and matrix products, not the study's scorer."""
    left = base.set_index("game_id").sort_index()
    right = candidate.set_index("game_id").sort_index()
    require(left.index.equals(right.index), "paired population differs")
    difference = right[list(METRICS)].to_numpy() - left[list(METRICS)].to_numpy()
    table = pd.DataFrame(difference, columns=METRICS)
    table["season"] = left.season.to_numpy()
    table["week_block"] = left.scheduled_at.dt.strftime("%G-W%V").to_numpy()
    table["game_count"] = 1
    generator = np.random.default_rng(20260918)
    numerators = np.zeros((repetitions, len(METRICS)))
    denominators = np.zeros(repetitions)
    block_count = 0
    for season, season_rows in table.groupby("season", sort=True):
        blocks = season_rows.groupby("week_block", sort=True)[[*METRICS, "game_count"]].sum()
        count = len(blocks)
        sample = generator.integers(0, count, size=(repetitions, count))
        multiplicities = np.asarray([np.bincount(row, minlength=count) for row in sample])
        numerators += multiplicities @ blocks[list(METRICS)].to_numpy()
        denominators += multiplicities @ blocks.game_count.to_numpy()
        block_count += count
    replicates = numerators / denominators[:, None]
    return {"games": len(left), "blocks": block_count, "bootstrapReplicates": repetitions,
            "metrics": {name: {"delta": float(difference[:, j].mean()),
                               "low95": float(np.percentile(replicates[:, j], 2.5)),
                               "high95": float(np.percentile(replicates[:, j], 97.5))}
                        for j, name in enumerate(METRICS)}}


def independent_crps(values, observation):
    # Exact empirical mass formula on distinct integers, independent of sorted
    # rank-weight implementation in pipeline.empirical_crps.
    unique, frequencies = np.unique(np.asarray(values, dtype=float), return_counts=True)
    probability = frequencies / frequencies.sum()
    absolute_pair_distance = np.abs(unique[:, None] - unique[None, :])
    return float(probability @ np.abs(unique - observation)
                 - 0.5 * probability @ absolute_pair_distance @ probability)


def independent_draw_metrics(draws, target):
    scores = draws[["home_score", "away_score"]].to_numpy(float)
    actual = np.array([target.home_score, target.away_score])
    require(len(scores) % 2 == 0, "even frozen draw count required")
    half = len(scores) // 2
    # The original energy estimator pairs the two halves in both directions.
    first = np.sqrt(np.square(scores - actual).sum(axis=1)).mean()
    second = np.sqrt(np.square(scores[:half] - scores[half:]).sum(axis=1)).mean()
    margin = scores[:, 0] - scores[:, 1]
    total = scores.sum(axis=1)
    probability = np.clip((margin > 0).mean(), 1e-12, 1 - 1e-12)
    return {"jointEnergyScore": float(first - 0.5 * second),
            "jointWinnerLogLoss": float(-target.home_win * np.log(probability)
                                        - (1 - target.home_win) * np.log1p(-probability)),
            "jointBinaryBrier": float(((margin > 0).mean() - target.home_win) ** 2),
            "marginCrps": independent_crps(margin, target.home_margin),
            "totalCrps": independent_crps(total, target.total_points)}


def independent_frozen_precision_energy(draws, target):
    """Account explicitly for the frozen int16/float32 pair-distance path."""
    integers = draws[["home_score", "away_score"]].to_numpy(dtype=np.int16)
    actual = np.array([target.home_score, target.away_score], dtype=float)
    first = np.sqrt(np.square(integers.astype(float) - actual).sum(axis=1)).mean()
    half = len(integers) // 2
    other_half = np.concatenate([integers[half:], integers[:half]])
    difference = integers - other_half
    distances = np.hypot(difference[:, 0], difference[:, 1])
    return float(first - 0.5 * distances.mean()), str(distances.dtype)


def verify_freezes(reader, out):
    required = ("DESIGN.json", "FROZEN_SELECTION.json", "SOURCE_GATE_THROUGH_2022.json",
                "SOURCE_GATE_THROUGH_2025.json", "COMMON_POPULATION_PREDICTIONS.parquet",
                "COMMON_POPULATION_SCORES.parquet", "PAIRED_EFFECTS.json", "DECISION.json")
    require(all((out / name).is_file() for name in required), "assessment must be complete before verification")
    design = reader.json(out / "DESIGN.json")
    frozen = reader.json(out / "FROZEN_SELECTION.json")
    before = reader.json(out / "SOURCE_GATE_THROUGH_2022.json")
    later = reader.json(out / "SOURCE_GATE_THROUGH_2025.json")
    require(reader.bind(design["design"]["path"]) == design["design"], "design text binding changed")
    require(reader.bind(design["sourcePopulation"]["path"]) == design["sourcePopulation"], "source binding changed")
    require(reader.bind(out / "DESIGN.json") == frozen["design"], "selection design binding changed")
    for key in ("gridScores", "developmentScores"):
        require(reader.bind(frozen[key]["path"]) == frozen[key], f"frozen {key} binding changed")
    clocks = list(map(pd.Timestamp, [design["frozenAtUtc"], before["loadedAtUtc"],
                                    frozen["frozenAtUtc"], later["loadedAtUtc"]]))
    require(all(a < b for a, b in zip(clocks, clocks[1:])), "design/Development/selection/later-read order failed")
    require(frozen["maximumOutcomeSeasonRead"] == 2022 and not frozen["laterEvidenceOpenedByThisStage"],
            "selection used later outcomes")
    require(before["loadedMaximumSeason"] == 2022 and later["loadedMaximumSeason"] == 2025,
            "source season bounds differ")
    for gate in (before, later):
        require(gate["featureReproductionExact"] and gate["finalStatusFiniteScoresAnd48HourGatePassed"],
                "baseline source gates not passed")
        require(gate["minimumFeatureAgeHoursAtUTCDateOrigin"] >= 48, "baseline source embargo violated")
        require(gate["providerCalls"] == 0, "unexpected provider request")
    clarification = reader.json(out / "DESIGN_CLARIFICATION_001.json")
    require(clarification["beforeAnyComparisonScoreFile"], "clarification was not recorded before comparisons")
    require(pd.Timestamp(clarification["recordedAtUtc"]) < pd.Timestamp(frozen["frozenAtUtc"]),
            "clarification followed selection")
    require(not any(clarification[key] for key in ("numericalChanges", "searchChanges", "gateChanges")),
            "clarification introduced an unbound design change")
    require(reader.bind(clarification["clarification"]["path"]) == clarification["clarification"],
            "clarification text binding changed")
    implementation = reader.json(out / "IMPLEMENTATION_BINDING.json")
    require(implementation["designSha256"] == reader.bind(out / "DESIGN.json")["sha256"],
            "implementation design binding differs")
    for item in implementation["sources"]:
        actual = reader.bind(item["path"])
        require(all(actual[key] == item[key] for key in ("path", "sha256", "bytes")),
                f"frozen implementation changed: {item['path']}")
    return design, frozen, {"clocksStrictlyOrdered": [str(x) for x in clocks],
                            "minimumFeatureAgeHours": later["minimumFeatureAgeHoursAtUTCDateOrigin"],
                            "dynamicAblationQualification": "B-versus-A changes the full recursive dynamic procedure, including prior-season means; it does not isolate only the last update.",
                            "preComparisonClarificationBound": True, "implementationBindingsVerified": len(implementation["sources"])}


def verify_populations(predictions, scores):
    require(set(predictions.arm) == set(ARMS) == set(scores.arm), "missing or extra arm")
    require(set(predictions.season) == set(range(2016, 2026)), "point seasons differ")
    require(set(scores.season) == set(range(2017, 2026)), "distribution seasons differ")
    require(not predictions.duplicated(["arm", "game_id"]).any(), "duplicate point prediction")
    require(not scores.duplicated(["arm", "game_id"]).any(), "duplicate distribution target")
    results = []
    for season in range(2016, 2026):
        point = predictions[predictions.season.eq(season)]
        expected_ids = set(point.loc[point.arm.eq("baseline"), "game_id"])
        for arm in ARMS:
            current = point[point.arm.eq(arm)]
            require(set(current.game_id) == expected_ids, f"point common population failed: {season}/{arm}")
            require(current.trainingThroughSeason.lt(season).all(), "point training origin failed")
            require(current.calibrationThroughSeason.dropna().lt(season).all(), "calibration origin failed")
            subset = scores[scores.season.eq(season) & scores.arm.eq(arm)]
            if season == 2016:
                require(subset.empty, "2016 is residual warmup only")
                continue
            require(set(subset.game_id) == expected_ids, f"distribution population failed: {season}/{arm}")
            donors = predictions[predictions.arm.eq(arm) & predictions.season.lt(season)].sort_values(["scheduled_at", "game_id"])
            digest = hashlib.sha256(canonical(donors.game_id.tolist())).hexdigest()
            require(len(donors) >= 500, "too few residual donors")
            require(donors.scheduled_at.max() < current.scheduled_at.min(), "donor timestamp chronology failed")
            require(subset.donorIdentitySha256.eq(digest).all(), "donor identity digest differs")
            require(subset.donorCount.eq(len(donors)).all(), "donor count differs")
            require(subset.donorMaximumSeason.eq(donors.season.max()).all(), "donor maximum season differs")
        results.append({"season": season, "pointGamesPerArm": len(expected_ids),
                        "distributionGamesPerArm": len(expected_ids) if season >= 2017 else 0})
    return results


def verify_support(reader, design, predictions, scores):
    columns = ["game_id", "season", "scheduled_at", "home_id", "away_id", "primary", "is_final", "score_supported"]
    source = reader.parquet(design["sourcePopulation"]["path"], columns=columns, filters=[("season", "<=", 2025)])
    calendar_2026 = source[source.scheduled_at.dt.year.eq(2026)]
    calendar_accounting = {"sourceRowsScheduledInCalendar2026": len(calendar_2026),
                           "sourceSeasonsOfThoseRows": sorted(map(int, calendar_2026.season.unique())),
                           "primarySourceRowsScheduledInCalendar2026": int(calendar_2026.primary.sum()),
                           "primaryEvaluationRowsScheduledInCalendar2026": int(scores.scheduled_at.dt.year.eq(2026).sum()),
                           "qualification": "Season2026 outcomes are excluded; season2025 includes January2026 nonprimary postseason context. A season cutoff is not a calendar-year cutoff."}
    require(calendar_accounting["primaryEvaluationRowsScheduledInCalendar2026"] == 0, "unexpected calendar2026 primary evaluation")
    source = source[source.primary & source.is_final & source.score_supported]
    records = pd.concat([source.rename(columns={"home_id": "team_id"})[["team_id", "season", "scheduled_at"]],
                         source.rename(columns={"away_id": "team_id"})[["team_id", "season", "scheduled_at"]]])
    clocks = {(int(team), int(season)): np.sort(group.scheduled_at.astype("int64").to_numpy())
              for (team, season), group in records.groupby(["team_id", "season"])}
    base = predictions[predictions.arm.eq("baseline")].sort_values("game_id")
    checked = []
    for row in base.itertuples():
        cutoff = (row.scheduled_at.floor("D") - pd.Timedelta(hours=48)).value
        current = [int(np.searchsorted(clocks.get((int(team), int(row.season)), np.array([], dtype="int64")), cutoff, side="right"))
                   for team in (row.home_id, row.away_id)]
        prior = [int(np.searchsorted(clocks.get((int(team), int(row.season) - 1), np.array([], dtype="int64")), cutoff, side="right"))
                 for team in (row.home_id, row.away_id)]
        expected_low = row.week <= 3 or min(current) < 2
        checked.append({"game_id": row.game_id, "home_current_support": current[0], "away_current_support": current[1],
                        "home_prior_support": prior[0], "away_prior_support": prior[1],
                        "low_support": expected_low, "opener": min(current) == 0, "zero_prior_support": min(prior) == 0})
    expected = pd.DataFrame(checked).set_index("game_id")
    for frame, kind in ((predictions, "prediction"), (scores, "score")):
        keys = [key for key in expected if key in frame]
        matched = expected.loc[frame.game_id, keys].to_numpy()
        require(np.array_equal(frame[keys].to_numpy(), matched), f"independent {kind} support membership differs")
    return {"gamesChecked": len(expected), "currentSupportRecomputedFrom": "source-final primary identity metadata under UTC-date48h embargo",
            "lowSupportGames": int(expected.low_support.sum()), "openerGames": int(expected.opener.sum()),
            "zeroPriorSupportGames": int(expected.zero_prior_support.sum()), "calendarVersusSeasonAccounting": calendar_accounting}


def verify_folds(reader, out, predictions, frozen):
    grid = reader.parquet(out / "data/development-grid-scores.parquet")
    require(grid.season.between(2017, 2022).all(), "grid contains non-Development seasons")
    require(set(grid.gridMode) == {"A", "B"}, "unplanned grid arm")
    require(float(frozen["lambdaPrior"]) == independent_lambda(grid, 2023), "final lambda selection differs")
    development = reader.parquet(out / "data/development-scores.parquet")
    mean_a = float(development.loc[development.arm.eq("A"), "jointEnergyScore"].mean())
    mean_b = float(development.loc[development.arm.eq("B"), "jointEnergyScore"].mean())
    require(frozen["selectedArm"] == ("B" if mean_b < mean_a - 0.02 else "A"), "Development arm selection differs")
    receipt_checks = []
    for season in range(2016, 2026):
        receipt = reader.json(out / "models" / f"fold-{season}-receipt.json")
        expected_lambda = independent_lambda(grid, season) if season <= 2022 else float(frozen["lambdaPrior"])
        require(float(receipt["lambdaPrior"]) == expected_lambda, f"nested lambda differs: {season}")
        error = max(receipt["pointPredictionMaximumDifference"].values())
        require(error <= 1e-9, f"baseline OOF reconciliation failed: {season}")
        actual = predictions[predictions.season.eq(season) & predictions.arm.ne("baseline")]
        require(actual.lambda_prior.eq(expected_lambda).all(), "point configuration differs from origin selection")
        receipt_checks.append({"season": season, "lambdaPrior": expected_lambda, "maximumBaselineDifference": error})
    features = reader.parquet(out / "data/baseline-features-through-2025.parquet")
    require((features.feature_max_source_game_date.isna()
             | features.feature_max_source_game_date.le(features.research_origin - pd.Timedelta(hours=48))).all(),
            "recorded baseline feature source embargo failed")
    primary = features[features.primary & features.is_final]
    indexed = features.set_index("game_id")
    sample_checks = []
    for season in (2018, 2023, 2025):
        expected_train = primary[primary.season.lt(season)]
        for arm in ("baseline", "A", "B"):
            artifact = reader.artifact(out / "models" / f"fold-{season}-{arm}.joblib")
            require(set(artifact["trainingGameIds"]) == set(expected_train.game_id), "fitted training population differs")
            require(len(artifact["trainingGameIds"]) == len(expected_train), "fitted training IDs duplicated")
            train_rows = indexed.loc[artifact["trainingGameIds"]]
            require(train_rows.season.lt(season).all() and artifact["trainingThroughSeason"] < season,
                    "fitted artifact training chronology failed")
            earlier = predictions[predictions.arm.eq(arm) & predictions.season.lt(season)].sort_values(["scheduled_at", "game_id"])
            require(artifact["calibrationGameIds"] == earlier.game_id.tolist(), "calibrator population differs")
            target = predictions[predictions.arm.eq(arm) & predictions.season.eq(season)]
            require(earlier.scheduled_at.max() < target.scheduled_at.min(), "artifact calibration clocks failed")
            require(artifact["researchOnly"] and not artifact["productionAuthority"], "artifact scope changed")
            max_prediction_difference = 0.0
            for key in ("margin", "total"):
                model = artifact["models"][key]
                reproduced = model.predict(target[artifact["columns"]])
                max_prediction_difference = max(max_prediction_difference,
                                                float(np.max(np.abs(reproduced - target[f"pred_{key}"].to_numpy()))))
                if arm == "baseline":
                    raw = train_rows[pipeline.FEATURE_COLUMNS].to_numpy(float)
                    medians = np.nanmedian(raw, axis=0)
                    expected_scaled_input = np.where(np.isnan(raw), medians, raw)
                    np.testing.assert_allclose(model.named_steps["imputer"].statistics_, medians, rtol=0, atol=1e-10)
                    np.testing.assert_allclose(model.named_steps["scale"].mean_, expected_scaled_input.mean(axis=0), rtol=0, atol=1e-10)
            require(max_prediction_difference <= 1e-9, "sample fitted artifact predictions differ")
            sample_checks.append({"season": season, "arm": arm, "trainingGames": len(train_rows),
                                  "calibrationGames": len(earlier), "maximumPredictionDifference": max_prediction_difference,
                                  "baselineMedianAndScalerIndependentlyRecomputed": arm == "baseline"})
    return {"allFoldReceipts": receipt_checks, "sampleArtifacts": sample_checks}


def verify_effects(reader, out, scores, frozen):
    saved = reader.json(out / "PAIRED_EFFECTS.json")
    checks = []
    for subgroup in ("overall", "low_support"):
        rows = scores[scores.season.isin([2023, 2024])]
        if subgroup == "low_support":
            rows = rows[rows.low_support]
        computed = independent_paired_bootstrap(rows[rows.arm.eq("baseline")], rows[rows.arm.eq(frozen["selectedArm"])])
        reported = next(item for item in saved if item["period"] == "reused_validation" and item["subgroup"] == subgroup
                        and item["reference"] == "baseline" and item["arm"] == frozen["selectedArm"])
        require(computed["games"] == reported["games"] and computed["blocks"] == reported["blocks"], "bootstrap population differs")
        max_difference = 0.0
        for metric in METRICS:
            for statistic in ("delta", "low95", "high95"):
                difference = abs(computed["metrics"][metric][statistic] - reported["metrics"][metric][statistic])
                max_difference = max(max_difference, difference)
        require(max_difference <= 1e-10, "independent block confidence intervals differ")
        checks.append({"period": "reused_validation", "subgroup": subgroup, "selectedArm": frozen["selectedArm"],
                       "maximumAbsoluteDifference": max_difference, "independentResult": computed})
    return checks


def verify_draw_samples(predictions, scores):
    baseline_rows = predictions[predictions.arm.eq("baseline")]
    sample_ids = []
    for season in (2018, 2023, 2025):
        for low_support in (True, False):
            candidates = baseline_rows[baseline_rows.season.eq(season) & baseline_rows.low_support.eq(low_support)]
            require(not candidates.empty, "planned deterministic sample subgroup missing")
            sample_ids.append(int(candidates.sort_values(["scheduled_at", "game_id"]).iloc[0].game_id))
    results = []
    for game_id in sample_ids:
        for arm in ("baseline", "A", "B"):
            target = predictions[predictions.arm.eq(arm) & predictions.game_id.eq(game_id)].iloc[0].copy()
            donors = predictions[predictions.arm.eq(arm) & predictions.season.lt(target.season)].sort_values(["scheduled_at", "game_id"]).copy()
            for side in ("home", "away"):
                donors[f"ridge_alpha100_pred_{side}"] = donors[f"pred_{side}"]
                target[f"ridge_alpha100_pred_{side}"] = target[f"pred_{side}"]
            draws, accounting = pipeline.simulate_paired_residuals(target, donors, "ridge_alpha100", draw_count=10000)
            manual = independent_draw_metrics(draws, target)
            saved = scores[scores.arm.eq(arm) & scores.game_id.eq(game_id)].iloc[0]
            frozen_precision_energy, pair_dtype = independent_frozen_precision_energy(draws, target)
            difference = max([abs(frozen_precision_energy - saved.jointEnergyScore)]
                             + [abs(value - saved[name]) for name, value in manual.items() if name != "jointEnergyScore"])
            require(difference <= 1e-10, "independent sampled score differs")
            float64_energy_difference = abs(manual["jointEnergyScore"] - saved.jointEnergyScore)
            # Conservative pairwise-reduction roundoff envelope; this is a
            # verification precision tolerance, not a model or advancement gate.
            float32_bound = float(np.finfo(np.float32).eps * np.ceil(np.log2(len(draws)))
                                  * max(1.0, np.hypot(draws.home_score.max(), draws.away_score.max())))
            require(float64_energy_difference <= float32_bound, "float64 energy discrepancy exceeds reduction roundoff")
            require(len(draws) == 10000 and (draws.home_score != draws.away_score).all(), "sample support/count violated")
            results.append({"game_id": game_id, "season": int(target.season), "arm": arm,
                            "lowSupport": bool(target.low_support), "drawCount": 10000,
                            "donorCount": len(donors), "maximumMetricDifference": float(difference),
                            "drawPairsSha256": hashlib.sha256(draws[["home_score", "away_score"]].to_numpy(dtype="<i2").tobytes()).hexdigest(),
                            "manualFloat64Metrics": manual, "frozenPrecisionEnergy": frozen_precision_energy,
                            "frozenPairDistanceDtype": pair_dtype, "float64EnergyDifference": float64_energy_difference,
                            "float32ReductionRoundoffBound": float32_bound,
                            "finalTieCount": accounting["finalTieCount"]})
    return results


def verify(out):
    reader = Reader()
    design, frozen, freeze_checks = verify_freezes(reader, out)
    predictions = reader.parquet(out / "COMMON_POPULATION_PREDICTIONS.parquet", filters=[("season", "<=", 2025)])
    scores = reader.parquet(out / "COMMON_POPULATION_SCORES.parquet", filters=[("season", "<=", 2025)])
    # Inspect season metadata separately so a bad2026 append cannot hide behind
    # the mandatory filter, while never materializing its outcome columns.
    for name in ("COMMON_POPULATION_PREDICTIONS.parquet", "COMMON_POPULATION_SCORES.parquet"):
        reader.parquet(out / name, columns=["season"])
    checks = {"freezeAndSourceChronology": freeze_checks,
              "commonPopulationsAndDonors": verify_populations(predictions, scores),
              "independentSupportMembership": verify_support(reader, design, predictions, scores),
              "foldFitsAndSelection": verify_folds(reader, out, predictions, frozen),
              "independentPairedEffects": verify_effects(reader, out, scores, frozen),
              "independentSmallDrawReplay": verify_draw_samples(predictions, scores)}
    decision = reader.json(out / "DECISION.json")
    low = next(item["independentResult"] for item in checks["independentPairedEffects"] if item["subgroup"] == "low_support")
    adequate = low["games"] >= 100 and low["blocks"] >= 15
    require(decision["gates"]["lowSupportAdequate"] == adequate, "reported low-support adequacy gate differs")
    checks["independentLowSupportAdequacyGate"] = {"games": low["games"], "blocks": low["blocks"],
                                                  "minimumGames": 100, "minimumBlocks": 15, "passes": adequate,
                                                  "gateRelaxed": False,
                                                  "qualification": "A favorable diagnostic interval does not override insufficient chronological block support."}
    receipt = {"schema": "CFB_STRENGTH_INDEPENDENT_VERIFICATION_V1", "status": "PASSED",
               "verifiedAtUtc": datetime.now(timezone.utc).isoformat(),
               "qualification": "PRIVATE_CLASS_A_RECONSTRUCTED_RESEARCH;2023-2025_REUSED;NO_CERTIFIED_HISTORICAL_AVAILABILITY",
               "checks": checks, "inputBindings": sorted(reader.refs.values(), key=lambda item: item["path"]),
               "verifierSource": ref(__file__), "fullStudyRerun": False, "modelFits": 0,
               "providerCalls": 0, "productionWrites": 0, "consumerWrites": 0,
               "season2026OutcomeRowsMaterialized": 0}
    raw = canonical(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    destination = out / "verification/sha256" / digest / "receipt.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        require(destination.read_bytes() == raw, "immutable verification receipt collision")
    else:
        destination.write_bytes(raw)
    pointer = {"status": "PASSED", "receipt": ref(destination)}
    (out / "VERIFICATION.json").write_bytes(canonical(pointer))
    print(json.dumps(pointer, indent=2), flush=True)
    return pointer


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        verify(args.output.resolve())


if __name__ == "__main__":
    main()
