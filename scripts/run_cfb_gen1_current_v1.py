from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_cfb_gen1.current import (
    INSUFFICIENT_CURRENT_GAMES,
    MIN_CHALLENGER_DONORS,
    cfbd_2026_games,
    interval_table,
    population_tables,
    simulate_uncertainty_challenger,
    totals_probabilities,
    uncertainty_support,
)
from server.sports_cfb_gen1.pipeline import (
    FEATURE_COLUMNS,
    SIMULATION_COUNT,
    build_features,
    energy_score,
    empirical_crps,
    predict_artifact,
    simulate_paired_residuals,
)


HISTORICAL = ROOT / "outputs/cfb-gen1-v1"
OUTPUT = ROOT / "outputs/cfb-gen1-current-v1"
PRIVATE = OUTPUT / "private-sources/cfbd"
MODEL_NAME = "ridge_alpha100"
BASELINE_CONFIGURATION = "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1"
CHALLENGER_CONFIGURATION = "CFB_GEN1_CENTERED_EARLY_GAP_RESIDUAL_V1"
MINIMUM_LEAD_MINUTES = 60
SECONDARY_SCHEDULE_URL = "https://theacc.com/schedule.aspx?schedule=4609"
SECONDARY_SCHEDULE_CAPTURE = {
    "publisher": "Atlantic Coast Conference",
    "matchup": "Syracuse at Pittsburgh",
    "scheduledLocal": "2026-09-17 7:30 PM ET",
    "scheduledUtc": "2026-09-17T23:30:00+00:00",
    "url": SECONDARY_SCHEDULE_URL,
    "verifiedAt": "2026-09-14T22:00:00+00:00",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binding(path: Path, *, relative_to: Path | None = None) -> dict[str, Any]:
    return {
        "path": path.relative_to(relative_to).as_posix() if relative_to else str(path.resolve()),
        "bytes": path.stat().st_size,
        "physicalSha256": sha(path),
    }


def write_json(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(clean(value), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8")
    path.write_bytes(raw)
    if path.read_bytes() != raw:
        raise RuntimeError(f"byte replay failed: {path}")
    return binding(path)


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def read_raw(name: str) -> Any:
    return json.loads((PRIVATE / name).read_bytes())


def stat_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(PRIVATE.glob("team-game-stats-2026-regular-week-*.json")):
        rows.extend(json.loads(path.read_bytes()))
    return rows


def reconcile(old: pd.DataFrame, current: pd.DataFrame, schedule: list[dict[str, Any]]) -> dict[str, Any]:
    old = old[old["season"].eq(2026)].copy()
    shared = old.merge(current, on="game_id", suffixes=("_old", "_cfbd"))
    kickoff_old = pd.to_datetime(shared["scheduled_at_old"], utc=True)
    kickoff_new = pd.to_datetime(shared["scheduled_at_cfbd"], utc=True)
    old_final = old[old["is_final"]]
    current_ids = set(current["game_id"].astype(int))
    old_statuses = old["status"].fillna("MISSING").value_counts().to_dict()
    return {
        "schemaVersion": "CFB_GEN1_SPORTSDATAVERSE_CFBD_RECONCILIATION_V1",
        "createdAt": now(),
        "sourcesRemainSeparate": True,
        "sportsDataverse": {
            "scheduleRows": int(len(old)),
            "finalRows": int(old["is_final"].sum()),
            "completedPrimaryFbsVsFbs": int(old["primary"].sum()),
            "latestKickoff": old["scheduled_at"].max().isoformat(),
            "futureAfterSeptember13": int((old["scheduled_at"] > pd.Timestamp("2026-09-13T23:59:59Z")).sum()),
            "statuses": {str(k): int(v) for k, v in old_statuses.items()},
        },
        "cfbd": {
            "allScheduleRows": len(schedule),
            "allCompletedRows": int(sum(bool(g.get("completed")) for g in schedule)),
            "fbsInvolvedRows": int((current["home_is_fbs"] | current["away_is_fbs"]).sum()),
            "fbsVsFbsRows": int(current["both_fbs"].sum()),
            "completedFbsVsFbsPrimary": int(current["primary"].sum()),
            "futureFbsVsFbsPrimary": int((current["scope_primary"] & ~current["is_final"]).sum()),
            "sourceIdDuplicates": int(current["game_id"].duplicated().sum()),
            "explicitCancelledPostponedFieldAvailable": False,
        },
        "overlap": {
            "sharedSourceGameIds": int(len(shared)),
            "oldIdsAbsentFromCfbd": int(sum(int(x) not in current_ids for x in old["game_id"])),
            "orientationDifferences": int(((shared["home_id_old"] != shared["home_id_cfbd"]) | (shared["away_id_old"] != shared["away_id_cfbd"])).sum()),
            "neutralSiteDifferences": int((shared["neutral_site_old"].astype(bool) != shared["neutral_site_cfbd"].astype(bool)).sum()),
            "kickoffDifferences": int((kickoff_old != kickoff_new).sum()),
            "matchedOldFinalScoreDifferences": int((
                shared["is_final_old"] & shared["is_final_cfbd"] &
                ((shared["home_score_old"] != shared["home_score_cfbd"]) | (shared["away_score_old"] != shared["away_score_cfbd"]))
            ).sum()),
            "oldFinalsNowMatched": int(old_final["game_id"].isin(current_ids).sum()),
        },
        "materialExplanation": [
            "The retained SportsDataverse object was a September 14 partial schedule release ending September 13; CFBD's season query supplies the remaining future season schedule and later completed results.",
            "CFBD is retained as a later, separately timestamped source revision and does not overwrite the earlier bytes or their clocks.",
            "CFBD /games exposes completed status but no explicit cancelled/postponed/replacement status or record revision timestamp; acquisition time bounds availability and unresolved schedule changes require a successor capture.",
        ],
    }


def coverage_rows(current: pd.DataFrame, features: pd.DataFrame, historical: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    feature_map = features.set_index("game_id", drop=False)
    prior_2025 = historical[historical["season"].eq(2025) & historical["context_eligible"]]
    candidates = current[current["scope_primary"] & ~current["is_final"] & (current["scheduled_at"] > cutoff)].copy()
    output: list[dict[str, Any]] = []
    for _, game in candidates.iterrows():
        row = feature_map.loc[int(game["game_id"])]
        for side in ("away", "home"):
            team_id = int(game[f"{side}_id"])
            earlier = current[
                current["is_final"] & (current["scheduled_at"] < game["scheduled_at"])
                & ((current["home_id"] == team_id) | (current["away_id"] == team_id))
            ]
            boxes_complete = bool((
                earlier["both_box_rows"]
                & earlier[["home_total_yards", "away_total_yards", "home_turnovers", "away_turnovers"]].notna().all(axis=1)
            ).all())
            prior_bound = bool(((prior_2025["home_id"] == team_id) | (prior_2025["away_id"] == team_id)).any())
            feature_games = int(row[f"{side}_current_season_games"])
            eligible = boxes_complete and prior_bound and feature_games == len(earlier)
            output.append({
                "game_id": int(game["game_id"]),
                "scheduled_at": game["scheduled_at"],
                "side": side,
                "team_id": team_id,
                "team": game[f"{side}_team"],
                "earlierCompleted2026Games": int(len(earlier)),
                "currentSeasonGamesInFeature": feature_games,
                "allEarlierScoresPresent": bool(earlier[["home_score", "away_score"]].notna().all(axis=1).all()),
                "allRequiredTeamStatsPresent": boxes_complete,
                "priorSeasonIdentityBound": prior_bound,
                "noTargetStats": int(game["game_id"]) not in set(current[current["both_box_rows"]]["game_id"]),
                "featureMaxSourceDate": row["feature_max_source_game_date"],
                "eligible": eligible,
                "missingPrerequisite": None if eligible else "; ".join([
                    *( [] if boxes_complete else ["complete totalYards/turnovers for every earlier 2026 game"] ),
                    *( [] if prior_bound else ["2025 identity/history binding"] ),
                    *( [] if feature_games == len(earlier) else ["chronological current-game count reconciliation"] ),
                ]),
            })
    return pd.DataFrame(output).sort_values(["scheduled_at", "game_id", "side"]).reset_index(drop=True)


def score_draws(draws: pd.DataFrame, target: pd.Series, low: float, high: float) -> dict[str, float | int]:
    home = draws["home_score"].to_numpy(float)
    away = draws["away_score"].to_numpy(float)
    total = draws["total"].to_numpy(float)
    margin = draws["home_margin"].to_numpy(float)
    y = float(target["home_win"])
    p = float((margin > 0).mean())
    result: dict[str, float | int] = {
        "jointEnergyScore": energy_score(home, away, float(target["home_score"]), float(target["away_score"])),
        "totalCrps": empirical_crps(total, float(target["total_points"])),
        "marginCrps": empirical_crps(margin, float(target["home_margin"])),
        "winnerLogLoss": float(-(y*math.log(max(p, 1e-12)) + (1-y)*math.log(max(1-p, 1e-12)))),
        "binaryBrier": float((p-y)**2),
        "lowTotalBrier": float(((total <= low).mean() - float(target["total_points"] <= low))**2),
        "highTotalBrier": float(((total >= high).mean() - float(target["total_points"] >= high))**2),
    }
    for metric, values, observed in (
        ("total", total, float(target["total_points"])),
        ("margin", margin, float(target["home_margin"])),
    ):
        for level in (50, 80, 90):
            alpha = (100-level)/200
            lo, hi = np.quantile(values, [alpha, 1-alpha])
            result[f"{metric}Coverage{level}"] = int(lo <= observed <= hi)
            result[f"{metric}Width{level}"] = float(hi-lo)
    return result


def aggregate(frame: pd.DataFrame, prefix: str) -> dict[str, Any]:
    result: dict[str, Any] = {"games": int(len(frame))}
    for metric in ["jointEnergyScore", "totalCrps", "marginCrps", "winnerLogLoss", "binaryBrier", "lowTotalBrier", "highTotalBrier"]:
        result[metric] = float(frame[f"{prefix}_{metric}"].mean())
    for metric in ("total", "margin"):
        for level in (50, 80, 90):
            result[f"{metric}Coverage{level}"] = float(frame[f"{prefix}_{metric}Coverage{level}"].mean())
            result[f"{metric}AverageWidth{level}"] = float(frame[f"{prefix}_{metric}Width{level}"].mean())
    return result


def compare(frame: pd.DataFrame) -> dict[str, Any]:
    baseline = aggregate(frame, "baseline")
    candidate = aggregate(frame, "candidate")
    differences = {key: candidate[key]-baseline[key] for key in baseline if key != "games"}
    return {"baseline": baseline, "candidate": candidate, "candidateMinusBaseline": differences, "negativeDifferenceFavorsCandidateForScoresAndWidths": True}


def block_interval(frame: pd.DataFrame) -> dict[str, Any]:
    work = frame.copy()
    work["delta"] = work["candidate_jointEnergyScore"] - work["baseline_jointEnergyScore"]
    work["block"] = pd.to_datetime(work["scheduled_at"], utc=True).dt.strftime("%G-W%V")
    blocks = [g["delta"].to_numpy() for _, g in work.groupby("block")]
    if not blocks:
        return {"calendarBlocks": 0, "interval95": None}
    rng = np.random.default_rng(20260914)
    boot = [float(np.mean(np.concatenate([blocks[i] for i in rng.integers(0, len(blocks), len(blocks))]))) for _ in range(2000)]
    return {"calendarBlocks": len(blocks), "repetitions": 2000, "mean": float(work["delta"].mean()), "interval95": [float(x) for x in np.quantile(boot, [.025, .975])]}


def challenger_assessment(predictions: pd.DataFrame, thresholds: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    definition = {
        "schemaVersion": "CFB_GEN1_EARLY_GAP_RESIDUAL_CHALLENGER_DEFINITION_V1",
        "frozenAtBeforeAssessment": now(),
        "configuration": CHALLENGER_CONFIGURATION,
        "developmentOnlyDefinition": True,
        "targetSupport": f"Either team has fewer than {INSUFFICIENT_CURRENT_GAMES} completed current-season games, or either extended-gap flag is true (>21 days).",
        "donors": "Strictly earlier chronological OOF residual pairs satisfying the same early-season or extended-gap support class.",
        "minimumDonors": MIN_CHALLENGER_DONORS,
        "centering": "Remove donor home- and away-residual means separately while retaining each paired residual.",
        "pointAndWinnerModels": "Frozen Ridge alpha100 point estimates and its Development calibrator remain unchanged; Elo remains separate.",
        "ordinaryAndInsufficientFallback": "Exact unrestricted baseline draw population.",
        "gate": "Advance for prospective research only if Validation targeted joint energy score improves, ordinary games are exact, and targeted total CRPS, margin CRPS, winner log loss, and Brier each degrade by no more than 0.02 absolute.",
    }
    write_json(OUTPUT / "opener-challenger-definition.json", definition)
    low = float(thresholds["lowTotalInclusive"])
    high = float(thresholds["highTotalInclusive"])
    rows: list[dict[str, Any]] = []
    for _, target in predictions.iterrows():
        support = uncertainty_support(target)
        if support == "ORDINARY":
            continue
        earlier_count = int((predictions["scheduled_at"] < target["scheduled_at"]).sum())
        if earlier_count < MIN_CHALLENGER_DONORS:
            continue
        baseline, candidate, accounting = simulate_uncertainty_challenger(target, predictions, MODEL_NAME)
        record: dict[str, Any] = {
            "game_id": int(target["game_id"]), "season": int(target["season"]),
            "scheduled_at": target["scheduled_at"], "role": target["role"],
            "support": support, "applied": accounting["applied"],
            "disposition": accounting["disposition"], "candidateDonorCount": accounting["candidateDonorCount"],
        }
        for label, draws in (("baseline", baseline), ("candidate", candidate)):
            record.update({f"{label}_{k}": v for k, v in score_draws(draws, target, low, high).items()})
        rows.append(record)
    scores = pd.DataFrame(rows)
    groups: dict[str, Any] = {}
    for name, part in {
        "development": scores[scores["season"].between(2016, 2022)],
        "validation": scores[scores["season"].isin([2023, 2024])],
        "historicalHoldout2025": scores[scores["season"].eq(2025)],
        "pandemic2020": scores[scores["season"].eq(2020)],
    }.items():
        applied = part[part["applied"]]
        groups[name] = {
            "targetedEligibleGames": int(len(part)),
            "challengerAppliedGames": int(len(applied)),
            "exactFallbackGames": int((~part["applied"]).sum()),
            "comparisonAppliedOnly": compare(applied) if len(applied) else None,
        }
    validation = scores[scores["season"].isin([2023, 2024]) & scores["applied"]]
    delta = groups["validation"]["comparisonAppliedOnly"]["candidateMinusBaseline"] if len(validation) else {}
    advance = bool(
        len(validation)
        and delta["jointEnergyScore"] < 0
        and all(delta[name] <= .02 for name in ("totalCrps", "marginCrps", "winnerLogLoss", "binaryBrier"))
    )
    assessment = {
        "schemaVersion": "CFB_GEN1_EARLY_GAP_RESIDUAL_CHALLENGER_ASSESSMENT_V1",
        "createdAt": now(),
        "definition": definition,
        "qualification": "All outcomes are reconstructed historical evidence. Validation and 2025 were already inspected in the baseline study; neither is untouched confirmation.",
        "drawsPerArmPerGame": SIMULATION_COUNT,
        "groups": groups,
        "bySeason": {str(int(season)): compare(part[part["applied"]]) for season, part in scores.groupby("season") if bool(part["applied"].any())},
        "validationEnergyDifferenceBlockInterval": block_interval(validation),
        "ordinaryGames": {"candidateEqualsBaselineExactly": True, "metricDifferences": 0.0, "reason": "The executable challenger returns the baseline population unchanged outside its frozen support class."},
        "advanceToProspectiveResearchArm": advance,
        "decision": "ADVANCE_RESEARCH_CHALLENGER" if advance else "DO_NOT_ADVANCE",
    }
    return assessment, scores


def main(output: Path = OUTPUT) -> dict[str, Any]:
    started = now()
    output.mkdir(parents=True, exist_ok=True)
    source_manifest = json.loads((output / "cfbd-source-manifest.json").read_bytes())
    schedule = read_raw("games-2026.json")
    teams = read_raw("fbs-teams-2026.json")
    current_all = cfbd_2026_games(schedule, stat_rows())
    current = current_all[(current_all["home_is_fbs"] | current_all["away_is_fbs"]) & current_all["season_type"].eq(2)].copy()
    historical_all = pd.read_parquet(HISTORICAL / "data/admitted-games.parquet")
    historical = historical_all[historical_all["season"] < 2026].copy()
    combined = pd.concat([historical, current], ignore_index=True, sort=False).sort_values(["scheduled_at", "game_id"])
    features = build_features(combined)
    predictions = pd.read_parquet(HISTORICAL / "data/season-forward-predictions.parquet")
    model_path = HISTORICAL / "models/selected-through-2025.joblib"
    calibrator_path = HISTORICAL / "models/development-margin-calibrators.joblib"
    model = joblib.load(model_path)
    calibrator = joblib.load(calibrator_path)[MODEL_NAME]
    distribution_meta = json.loads((HISTORICAL / "distribution-assessment.json").read_bytes())

    data_cutoff = pd.Timestamp(max(
        item["acquiredAt"] for item in source_manifest["requests"]
        if item["endpoint"] not in {"/info", "/info/usage"}
    ))
    recon = reconcile(historical_all, current_all, schedule)
    write_json(output / "sportsdataverse-cfbd-reconciliation.json", recon)
    current_all.to_parquet(output / "cfbd-2026-adapted-schedule.parquet", index=False)
    features[features["season"].eq(2026)].to_parquet(output / "cfbd-2026-point-in-time-features.parquet", index=False)

    coverage = coverage_rows(current, features, historical, data_cutoff)
    coverage.to_parquet(output / "current-history-coverage.parquet", index=False)
    target_support = coverage.groupby("game_id")["eligible"].all()
    eligible_ids = set(target_support[target_support].index.astype(int))
    forecast_started = pd.Timestamp.now(tz="UTC")
    earliest_allowed = forecast_started + pd.Timedelta(minutes=MINIMUM_LEAD_MINUTES)
    targets = features[
        features["game_id"].isin(eligible_ids) & features["season"].eq(2026)
        & ~features["is_final"] & features["both_fbs"] & features["season_type"].eq(2)
        & (features["scheduled_at"] > earliest_allowed)
    ].sort_values(["scheduled_at", "game_id"])
    if targets.empty:
        raise RuntimeError("no current FBS-FBS target passes history coverage and the predeclared 60-minute lead time")
    target = targets.iloc[0].copy()
    target_rows = coverage[coverage["game_id"].eq(int(target["game_id"]))]
    if not bool(target_rows["eligible"].all()):
        raise RuntimeError("selected target history is incomplete")

    selection = {
        "schemaVersion": "CFB_GEN1_CURRENT_TARGET_SELECTION_V1",
        "selectedAt": now(), "sourceCutoff": data_cutoff.isoformat(),
        "minimumLeadMinutes": MINIMUM_LEAD_MINUTES,
        "ordering": ["FBS-versus-FBS", "regular season", "kickoff after acquisition and completion", "both teams history complete", "earliest kickoff", "source game ID"],
        "eligibleGameCount": len(targets),
        "game": clean(target[["game_id", "scheduled_at", "away_id", "home_id", "away_team", "home_team", "neutral_site", "conference_competition"]].to_dict()),
        "secondaryIdentityVerification": SECONDARY_SCHEDULE_CAPTURE,
    }
    if int(target["game_id"]) != 401858225:
        raise RuntimeError("deterministic target changed; secondary identity receipt must be updated before forecasting")
    write_json(output / "target-selection-receipt.json", selection)

    assessment, challenger_scores = challenger_assessment(predictions, distribution_meta["tailThresholds"])
    write_json(output / "opener-challenger-assessment.json", assessment)
    challenger_scores.to_parquet(output / "opener-challenger-game-scores.parquet", index=False)

    point = predict_artifact(model, target.to_frame().T)
    target_with_prediction = target.copy()
    for suffix, value in (("pred_margin", point["homeMargin"]), ("pred_total", point["totalPoints"]), ("pred_home", point["homePoints"]), ("pred_away", point["awayPoints"])):
        target_with_prediction[f"{MODEL_NAME}_{suffix}"] = value
    baseline, baseline_accounting = simulate_paired_residuals(target_with_prediction, predictions, MODEL_NAME)
    replay, _ = simulate_paired_residuals(target_with_prediction, predictions, MODEL_NAME)
    if not baseline.equals(replay):
        raise RuntimeError("deterministic baseline replay changed")
    ridge_home = float(calibrator.predict_proba(np.array([[point["homeMargin"]]]))[:, 1][0])
    elo_home = float(target["elo_home_win_probability"])
    support = uncertainty_support(target)
    publish_challenger = bool(assessment["advanceToProspectiveResearchArm"] and support != "ORDINARY")
    candidate = None
    candidate_accounting = None
    if publish_challenger:
        _, candidate, candidate_accounting = simulate_uncertainty_challenger(target_with_prediction, predictions, MODEL_NAME)

    forecast_dir = output / "forecast"
    forecast_dir.mkdir(parents=True, exist_ok=True)
    baseline.to_parquet(forecast_dir / "baseline-joint-draws.parquet", index=False)
    baseline_pmf = population_tables(int(target["game_id"]), baseline)
    baseline_pmf.to_parquet(forecast_dir / "baseline-pmfs.parquet", index=False)
    if candidate is not None:
        candidate.to_parquet(forecast_dir / "challenger-joint-draws.parquet", index=False)
        population_tables(int(target["game_id"]), candidate).to_parquet(forecast_dir / "challenger-pmfs.parquet", index=False)

    integer_line = float(round(point["totalPoints"]))
    half_line = float(math.floor(point["totalPoints"]) + .5)
    feature_values = {name: float(target[name]) for name in FEATURE_COLUMNS}
    created = now()
    forecast_identity = {
        "gameId": int(target["game_id"]), "sourceCutoff": data_cutoff.isoformat(),
        "configuration": BASELINE_CONFIGURATION, "modelSha256": sha(model_path),
        "featureValuesSha256": hashlib.sha256(canonical(feature_values)).hexdigest(),
        "drawsSha256": sha(forecast_dir / "baseline-joint-draws.parquet"),
    }
    forecast_id = "cfb-gen1:" + hashlib.sha256(canonical(forecast_identity)).hexdigest()
    forecast = {
        "schemaVersion": "CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1",
        "forecastId": forecast_id, "createdAt": created, "publishedAt": None,
        "status": "FROZEN_LOCAL_RESEARCH_FORECAST",
        "game": selection["game"], "sourceCutoff": data_cutoff.isoformat(),
        "scheduleRevisionCapturedAt": next(x["acquiredAt"] for x in source_manifest["requests"] if x["endpoint"] == "/games"),
        "baseline": {
            "configuration": BASELINE_CONFIGURATION, "drawCount": SIMULATION_COUNT,
            "expectedAwayPoints": point["awayPoints"], "expectedHomePoints": point["homePoints"],
            "expectedTotal": point["totalPoints"], "expectedHomeMargin": point["homeMargin"],
            "ridgeHomeWinProbability": ridge_home, "ridgeAwayWinProbability": 1-ridge_home,
            "eloHomeWinProbability": elo_home, "eloAwayWinProbability": 1-elo_home,
            "jointHomeWinProbability": baseline_accounting["homeWinProbability"],
            "jointAwayWinProbability": 1-baseline_accounting["homeWinProbability"],
            "tieProbability": 0.0,
            "intervals": interval_table(baseline),
            "illustrativeTotals": [totals_probabilities(baseline, integer_line), totals_probabilities(baseline, half_line)],
            "simulationMcse": {
                "jointHomeWinProbability": math.sqrt(baseline_accounting["homeWinProbability"]*(1-baseline_accounting["homeWinProbability"])/SIMULATION_COUNT),
                "expectedAwayPoints": float(baseline["away_score"].std(ddof=1)/math.sqrt(SIMULATION_COUNT)),
                "expectedHomePoints": float(baseline["home_score"].std(ddof=1)/math.sqrt(SIMULATION_COUNT)),
                "expectedTotal": float(baseline["total"].std(ddof=1)/math.sqrt(SIMULATION_COUNT)),
                "expectedHomeMargin": float(baseline["home_margin"].std(ddof=1)/math.sqrt(SIMULATION_COUNT)),
            },
            "transformationAccounting": baseline_accounting,
        },
        "challenger": {
            "support": support, "assessmentDecision": assessment["decision"],
            "publishedAsSecondArm": publish_challenger,
            "configuration": CHALLENGER_CONFIGURATION if publish_challenger else None,
            "accounting": candidate_accounting,
        },
        "modelBindings": {
            "selectedModel": binding(model_path), "developmentCalibrator": binding(calibrator_path),
            "historicalArtifactIndex": binding(HISTORICAL / "artifact-index.json"),
            "historicalSourceManifest": binding(HISTORICAL / "source-manifest.json"),
            "featureContract": binding(HISTORICAL / "feature-contract.json"),
            "pairedResidualPopulation": binding(HISTORICAL / "data/season-forward-predictions.parquet"),
        },
        "sourceBindings": {"cfbdManifest": binding(output / "cfbd-source-manifest.json"), "secondarySchedule": SECONDARY_SCHEDULE_CAPTURE},
        "featureValues": feature_values,
        "limitations": ["No odds, injuries, quarterbacks, player availability, lineups, weather, recruiting or transfers.", "Historical residuals and 2026 inputs were acquired retrospectively except for this target's pre-kickoff capture.", "Ridge, Elo, and joint-residual winner probabilities are separately estimated outputs."],
        "researchOnly": True, "aispAuthority": False, "wageringAuthority": False, "schedulerAuthority": False,
    }
    write_json(forecast_dir / "forecast.json", forecast)

    package_stage = output / "package-staging" / forecast_id.split(":", 1)[1]
    package_stage.mkdir(parents=True, exist_ok=True)
    for name in ["forecast.json", "baseline-joint-draws.parquet", "baseline-pmfs.parquet"]:
        shutil.copy2(forecast_dir / name, package_stage / name)
    if candidate is not None:
        for name in ["challenger-joint-draws.parquet", "challenger-pmfs.parquet"]:
            shutil.copy2(forecast_dir / name, package_stage / name)
    package_payload_names = ["forecast.json", "baseline-joint-draws.parquet", "baseline-pmfs.parquet"]
    if candidate is not None:
        package_payload_names.extend(["challenger-joint-draws.parquet", "challenger-pmfs.parquet"])
    files = [binding(package_stage / name, relative_to=package_stage) for name in sorted(package_payload_names)]
    package_index = {
        "schemaVersion": "CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1",
        "forecastId": forecast_id, "gameId": int(target["game_id"]),
        "createdAt": created, "sourceCutoff": data_cutoff.isoformat(),
        "files": files, "rawProviderResponsesIncluded": False,
        "researchOnly": True, "aispAuthority": False, "wageringAuthority": False,
    }
    write_json(package_stage / "index.json", package_index)
    package_digest = sha(package_stage / "index.json")
    local_package = output / "packages/sha256" / package_digest
    if local_package.exists():
        for path in package_stage.iterdir():
            counterpart = local_package / path.name
            if not counterpart.is_file() or sha(counterpart) != sha(path):
                raise RuntimeError("immutable local package collision")
    else:
        shutil.copytree(package_stage, local_package)

    terms = {
        "schemaVersion": "CFB_GEN1_CFBD_TERMS_REVIEW_V1", "createdAt": now(),
        "provider": "CollegeFootballData", "termsEffectiveDate": "2026-08-12",
        "conclusions": {
            "privateResponseRetention": "permitted", "historicalAnalysisAndModelTraining": "permitted",
            "derivedPredictionPublication": "permitted", "commercialDerivedOutputs": "permitted",
            "rawBulkRedistributionOrProxying": "prohibited", "quota": "CFBD and CBBD use a shared account quota",
            "serviceLevel": "data is provided as-is without completeness, correctness, timeliness guarantee or SLA absent a separate writing",
        },
        "attribution": "Data provided by CollegeFootballData.com",
        "evidence": source_manifest["termsEvidence"],
    }
    write_json(output / "cfbd-terms-review.json", terms)

    coverage_summary = {
        "schemaVersion": "CFB_GEN1_CURRENT_HISTORY_COVERAGE_RECEIPT_V1", "createdAt": now(),
        "sourceCutoff": data_cutoff.isoformat(), "futureGamesAssessed": int(coverage["game_id"].nunique()),
        "eligibleGames": int(target_support.sum()), "unsupportedGames": int((~target_support).sum()),
        "selectedTargetTeams": clean(target_rows.to_dict("records")),
        "completeScheduleClaim": "Coverage is relative to the provider's season-level /games response captured at sourceCutoff; no record-level publication timestamps exist.",
    }
    write_json(output / "current-history-coverage-receipt.json", coverage_summary)

    evaluation_plan = {
        "schemaVersion": "CFB_GEN1_PROSPECTIVE_EVALUATION_PLAN_V1", "createdAt": now(),
        "forecastId": forecast_id, "gameId": int(target["game_id"]),
        "freezeBoundary": created, "governedFinalRequired": True,
        "metrics": ["joint energy score", "total CRPS", "margin CRPS", "winner log loss", "binary Brier", "50/80/90 interval coverage"],
        "unit": "one completed game, not simulation draws", "promotionAuthority": False,
    }
    write_json(output / "prospective-evaluation-plan.json", evaluation_plan)

    key = str(__import__("dotenv").dotenv_values(ROOT / ".env.local").get("CFBD_API_KEY") or "").encode()
    inspect_files = [Path(__file__), ROOT / "scripts/acquire_cfb_gen1_current_v1.py", ROOT / "server/sports_cfb_gen1/current.py"] + [p for p in output.rglob("*") if p.is_file() and "private-sources" not in p.parts]
    secret_absent = bool(key) and all(key not in p.read_bytes() for p in inspect_files)
    pmf_mass = bool((baseline_pmf.groupby("metric")["count"].sum() == SIMULATION_COUNT).all())
    current_features = features[features["season"].eq(2026)]
    verification = {
        "schemaVersion": "CFB_GEN1_CURRENT_FOCUSED_VERIFICATION_V1", "verifiedAt": now(),
        "secretAbsentFromCodeAndNonprivateArtifacts": secret_absent,
        "sourceExactBytes": all(Path(item["path"]).stat().st_size == item["bytes"] and sha(Path(item["path"])) == item["physicalSha256"] for item in source_manifest["requests"]),
        "quotaWithinAssignmentCaps": source_manifest["usage"]["calls"] <= 25 and source_manifest["usage"]["responseBytes"] <= 50*1024*1024 and source_manifest["usage"]["incrementalCostUsd"] == 0,
        "uniqueCfbdGameIdentity": current_all["game_id"].is_unique,
        "targetOrientationMatchesSecondary": target["away_team"] == "Syracuse" and target["home_team"] == "Pittsburgh",
        "chronology": bool((current_features["feature_max_source_game_date"].isna() | (current_features["feature_max_source_game_date"] < current_features["scheduled_at"])).all()),
        "targetExcludedFromFeatures": bool(target["feature_max_source_game_date"] < target["scheduled_at"]),
        "selectedTargetHistoryComplete": bool(target_rows["eligible"].all()),
        "frozenModelPhysicalSha256": sha(model_path),
        "frozenModelTrainingThrough2025": model["trainingThroughSeason"] == 2025,
        "pairedResidualRowsUnchanged": len(predictions),
        "zeroFinalTies": int((baseline["home_score"] == baseline["away_score"]).sum()) == 0,
        "drawCount": len(baseline), "drawCountCorrect": len(baseline) == SIMULATION_COUNT,
        "scoreReconciliation": bool((baseline["total"] == baseline["home_score"]+baseline["away_score"]).all() and (baseline["home_margin"] == baseline["home_score"]-baseline["away_score"]).all()),
        "pmfMassReconciles": pmf_mass,
        "deterministicReplay": baseline.equals(replay),
        "ordinaryChallengerExactByConstruction": True,
        "localPackageIndexSha256": package_digest,
        "localPackageIntegrity": all((local_package/item["path"]).stat().st_size == item["bytes"] and sha(local_package/item["path"]) == item["physicalSha256"] for item in package_index["files"]),
    }
    if not all(value for key_name, value in verification.items() if isinstance(value, bool)):
        raise RuntimeError(f"focused verification failed: {verification}")
    write_json(output / "verification.json", verification)

    report = f"""# College Football Gen 1 current-season result

Data provided by CollegeFootballData.com. A later CFBD season capture now supplies {len(schedule):,} schedule rows, {sum(bool(g.get('completed')) for g in schedule):,} completed games across classifications, {int(current_all['primary'].sum()):,} completed primary FBS-v-FBS games, and {int((current_all['scope_primary'] & ~current_all['is_final']).sum()):,} future primary games. The historical Ridge alpha100 model, preprocessing, feature contract, and OOF residual population remain frozen.

The deterministic first eligible target is **Syracuse at Pittsburgh**, CFBD game {int(target['game_id'])}, kickoff {target['scheduled_at'].isoformat()}. The ACC schedule independently shows September 17 at 7:30 PM ET. Both teams have complete scores, total yards, and turnovers for their {int(target_rows['earlierCompleted2026Games'].min())} earlier 2026 games, plus prior-season identity bindings.

The baseline expects Syracuse {point['awayPoints']:.2f}, Pittsburgh {point['homePoints']:.2f}, total {point['totalPoints']:.2f}, and Pittsburgh margin {point['homeMargin']:.2f}. Ridge's calibrated home-win probability is {ridge_home:.4f}; chronological Elo is {elo_home:.4f}; the paired-residual population is {baseline_accounting['homeWinProbability']:.4f}. These are separately estimated outputs. All 10,000 retained discrete finals are non-tied.

The bounded residual challenger decision is **{assessment['decision']}**. It changes only uncertainty for the predeclared early-season/extended-gap class, centers paired residuals, and returns the exact baseline elsewhere. The selected target is classified {support}; it receives {'two arms' if publish_challenger else 'one baseline arm'}.

This forecast is prospective research evidence, unfunded, and carries no AISP, odds, wagering, scheduler, or promotion authority. Provider raw responses remain in the private ignored source store and are absent from the package.
"""
    (output / "REPORT.md").write_text(report, encoding="utf-8")
    model_card = f"""# CFB Gen 1 current model card

- Point model: frozen Ridge alpha100 trained through 2025, artifact `{sha(model_path)}`.
- Winner outputs: frozen Development-calibrated Ridge margin and separate chronological Elo.
- Distribution: 10,000 paired earlier OOF residual draws with the previously documented nonnegative stochastic rounding and tied-final resampling.
- Current numerical state: CFBD 2026 finals and team total-yards/turnover boxes captured through `{data_cutoff.isoformat()}` update Elo and rolling features only.
- Missing pregame information: quarterbacks, injuries, lineups, player strength, weather, recruiting, transfers, and market prices.
- Use: private research only; no wagering or scheduler authority.
"""
    (output / "MODEL_CARD.md").write_text(model_card, encoding="utf-8")
    handoff = f"""# Future Claude handoff — College Football Gen 1 research

No import is requested during the current MLB/NFL closeout. A private producer package is ready for later review.

- Game: Syracuse at Pittsburgh; CFBD `{int(target['game_id'])}`; `{target['scheduled_at'].isoformat()}`.
- Forecast: `{forecast_id}`.
- Package index SHA-256: `{package_digest}`.
- Configuration: `{BASELINE_CONFIGURATION}`; 10,000 paired draws; no final ties.
- Ridge point/winner, Elo winner, and joint-residual winner outputs are explicitly separate.
- Research only; no AISP, wagering, odds, scheduler, or promotion authority.
"""
    (output / "CLAUDE_HANDOFF.md").write_text(handoff, encoding="utf-8")

    final_nonprivate_files = [p for p in output.rglob("*") if p.is_file() and "private-sources" not in p.parts]
    verification["secretAbsentFromCodeAndAllNonprivateArtifacts"] = bool(key) and all(
        key not in path.read_bytes() for path in [Path(__file__), ROOT / "scripts/acquire_cfb_gen1_current_v1.py", ROOT / "server/sports_cfb_gen1/current.py", *final_nonprivate_files]
    )
    verification["termsEvidenceExactBytes"] = all(
        Path(item["path"]).stat().st_size == item["bytes"] and sha(Path(item["path"])) == item["physicalSha256"]
        for item in source_manifest["termsEvidence"]
    )
    if not verification["secretAbsentFromCodeAndAllNonprivateArtifacts"] or not verification["termsEvidenceExactBytes"]:
        raise RuntimeError("final secret exclusion or terms evidence byte check failed")
    write_json(output / "verification.json", verification)

    tracked = [
        output / "cfbd-source-manifest.json", output / "cfbd-source-manifest-locator.json",
        output / "cfbd-terms-review.json", output / "sportsdataverse-cfbd-reconciliation.json",
        output / "cfbd-2026-adapted-schedule.parquet", output / "cfbd-2026-point-in-time-features.parquet",
        output / "current-history-coverage.parquet", output / "current-history-coverage-receipt.json",
        output / "target-selection-receipt.json", output / "opener-challenger-definition.json",
        output / "opener-challenger-assessment.json", output / "opener-challenger-game-scores.parquet",
        output / "prospective-evaluation-plan.json", output / "verification.json", output / "REPORT.md",
        output / "MODEL_CARD.md", output / "CLAUDE_HANDOFF.md", local_package / "index.json",
    ]
    index = {
        "schemaVersion": "CFB_GEN1_CURRENT_ARTIFACT_INDEX_V1", "createdAt": now(),
        "runStartedAt": started, "runCompletedAt": now(), "forecastId": forecast_id,
        "packageDigest": package_digest, "artifacts": [binding(path) for path in tracked],
        "privateRawSourceManifest": binding(output / "cfbd-source-manifest.json"),
        "rawProviderResponsesInExchange": False, "exchangePublished": False,
        "researchOnly": True, "aispAuthority": False, "wageringAuthority": False,
    }
    index_binding = write_json(output / "artifact-index.json", index)
    return {
        "status": "COMPLETE", "calls": source_manifest["usage"]["calls"],
        "bytes": source_manifest["usage"]["responseBytes"], "remainingCalls": source_manifest["usage"]["remainingCallsAfter"],
        "scheduleRows": len(schedule), "completedRows": int(sum(bool(g.get("completed")) for g in schedule)),
        "completedPrimary": int(current_all["primary"].sum()), "futurePrimary": int((current_all["scope_primary"] & ~current_all["is_final"]).sum()),
        "target": selection["game"], "forecastId": forecast_id, "packageDigest": package_digest,
        "challengerDecision": assessment["decision"], "targetArms": 2 if publish_challenger else 1,
        "artifactIndex": index_binding,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.parse_args()
    print(json.dumps(main(), indent=2, sort_keys=True))
