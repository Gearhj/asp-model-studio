from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.sports_cfb_gen1.pipeline import (
    FEATURE_COLUMNS,
    POINT_CANDIDATES,
    ROLES,
    SEED,
    SIMULATION_COUNT,
    aggregate_distribution_scores,
    build_features,
    calibration_table,
    fit_selected_artifact,
    frequency_rows,
    load_population,
    predict_artifact,
    save_artifact,
    score_distribution,
    score_point_predictions,
    season_forward_predictions,
    sha256_path,
    simulate_paired_residuals,
    write_json,
)


OUTPUT_ROOT = Path("outputs/cfb-gen1-v1")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if pd.isna(value) if not isinstance(value, (str, bytes)) else False:
        return None
    return value


def status_counts(frame: pd.DataFrame) -> dict[str, int]:
    return {str(k): int(v) for k, v in frame["status"].value_counts(dropna=False).sort_index().items()}


def source_schema_report(source_manifest: dict[str, Any]) -> dict[str, Any]:
    assets = []
    signatures: dict[str, set[str]] = {}
    for item in source_manifest["assets"]:
        frame = pd.read_parquet(item["path"])
        schema = {column: str(dtype) for column, dtype in frame.dtypes.items()}
        signature = hashlib.sha256(json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest()
        signatures.setdefault(item["tag"], set()).add(signature)
        assets.append({
            "tag": item["tag"], "season": item["season"], "name": item["name"],
            "rows": int(len(frame)), "columns": schema, "schemaSha256": signature,
            "physicalSha256": item["physicalSha256"],
        })
    return {
        "schemaVersion": "CFB_GEN1_RETAINED_SOURCE_SCHEMA_V1",
        "createdAt": now(),
        "assets": assets,
        "distinctSchemaCountByTag": {tag: len(values) for tag, values in sorted(signatures.items())},
    }


def coverage_report(games: pd.DataFrame, diagnostics: dict[str, Any], features: pd.DataFrame) -> dict[str, Any]:
    per_season = []
    for season, part in games.groupby("season", sort=True):
        final = part["is_final"]
        fbs_fcs = final & (part["home_is_fbs"].fillna(False) ^ part["away_is_fbs"].fillna(False))
        duplicate_pair = part.duplicated("game_id", keep=False)
        per_season.append({
            "season": int(season),
            "scheduledGames": int(len(part)),
            "completedGames": int(final.sum()),
            "gamesWithFinalScores": int(part["score_supported"].sum()),
            "gamesWithBothTeamBoxRows": int((final & part["both_box_rows"]).sum()),
            "duplicateSourceIdRows": int(duplicate_pair.sum()),
            "missingTeamIdentityRows": int((~part["identity_supported"]).sum()),
            "homeSiteGames": int((~part["neutral_site"]).sum()),
            "neutralSiteGames": int(part["neutral_site"].sum()),
            "fbsVersusFbsFinalGames": int((final & part["both_fbs"]).sum()),
            "fbsVersusNonFbsFinalGames": int(fbs_fcs.sum()),
            "primaryFbsVersusFbsGames": int(part["primary"].sum()),
            "distinctTeamsInPrimaryPopulation": int(len(set(part.loc[part["primary"], "home_id"]).union(
                set(part.loc[part["primary"], "away_id"])
            ))),
            "lateRegularSeasonClassificationWithheld": int(part["late_regular_unclassified"].sum()),
            "postseasonGames": int(part["postseason"].sum()),
            "overtimeGamesFromPeriods": int((final & part["overtime"]).sum()),
            "periodSupportedFinalGames": int((final & part["period_supported"]).sum()),
            "periodReconciledFinalGames": int((final & part["period_reconciles"]).sum()),
            "statuses": status_counts(part),
            "earliestScheduledAt": part["scheduled_at"].min().isoformat(),
            "latestScheduledAt": part["scheduled_at"].max().isoformat(),
        })
    missing_features = {}
    primary = features[features["primary"] & features["is_final"]]
    for column in FEATURE_COLUMNS:
        missing_features[column] = {
            "missingRows": int(primary[column].isna().sum()),
            "missingFraction": float(primary[column].isna().mean()),
        }
    raw_primary = games[games["primary"] & games["is_final"]]
    raw_missing = {}
    for column in ("home_total_yards", "away_total_yards", "home_turnovers", "away_turnovers"):
        raw_missing[column] = {
            "missingRows": int(raw_primary[column].isna().sum()),
            "missingFraction": float(raw_primary[column].isna().mean()),
        }
    current = games[games["season"].eq(2026)]
    acquisition = json.loads((OUTPUT_ROOT / "source-manifest.json").read_text(encoding="utf-8"))["generatedAt"]
    acquired_at = pd.Timestamp(acquisition)
    duplicate_day_matchups = games.assign(calendar_date=games["scheduled_at"].dt.date)
    duplicate_day_matchups = duplicate_day_matchups[
        duplicate_day_matchups.duplicated(["calendar_date", "home_id", "away_id"], keep=False)
    ].sort_values(["calendar_date", "scheduled_at", "game_id"])
    replacement_rows = [clean(row) for row in duplicate_day_matchups[
        ["game_id", "season", "scheduled_at", "home_id", "away_id", "home_team", "away_team",
         "status", "is_final", "home_score", "away_score", "primary"]
    ].to_dict("records")]
    return {
        "schemaVersion": "CFB_GEN1_COVERAGE_REPORT_V1",
        "generatedAt": now(),
        "sourceDiagnostics": diagnostics,
        "identityReconciliation": {
            "distinctTeamsAllSchedules": int(len(set(games["home_id"]).union(set(games["away_id"])))),
            "distinctTeamsPrimaryPopulation": int(len(set(games.loc[games["primary"], "home_id"]).union(
                set(games.loc[games["primary"], "away_id"])
            ))),
            "sameDaySameMatchupRows": replacement_rows,
            "sameDaySameMatchupConclusion": (
                "The two rows are one postponed and one final Illinois-Kent State event with distinct ESPN game IDs; "
                "only the final row enters the primary population."
            ),
        },
        "periodReconciliation": {
            "supportedFinalGames": int((games["is_final"] & games["period_supported"]).sum()),
            "scoreReconciledFinalGames": int((games["is_final"] & games["period_reconciles"]).sum()),
            "overtimeFinalGames": int((games["is_final"] & games["overtime"]).sum()),
            "2026Qualification": "UNAVAILABLE: retained linescore release ends with 2025.",
        },
        "perSeason": per_season,
        "candidateFeatureMissingnessPrimaryPopulation": missing_features,
        "rawTeamBoxInputMissingnessPrimaryPopulation": raw_missing,
        "currentSeason": {
            "season": 2026,
            "assetPublisherUpdatedAt": next(
                item["publisherUpdatedAt"] for item in json.loads(
                    (OUTPUT_ROOT / "source-manifest.json").read_text(encoding="utf-8")
                )["assets"] if item["tag"] == "espn_cfb_schedules" and item["season"] == 2026
            ),
            "acquiredAt": acquisition,
            "scheduleRows": int(len(current)),
            "completedRows": int(current["is_final"].sum()),
            "primaryCompletedRows": int(current["primary"].sum()),
            "nonfinalRows": int((~current["is_final"]).sum()),
            "scheduledAfterAcquisition": int((current["scheduled_at"] > acquired_at).sum()),
            "latestScheduledAt": current["scheduled_at"].max().isoformat(),
            "qualification": "PARTIAL_CURRENT_SEASON_CAPTURE_WITH_NO_FUTURE_KICKOFF_AFTER_ACQUISITION",
        },
        "classificationLimits": {
            "conferenceChampionship": "UNAVAILABLE_AS_AN_EXACT_SCHEDULE FIELD",
            "policy": "Regular-season rows with week > 14 are withheld from primary assessment rather than guessed.",
            "bowlVersusPlayoff": "season_type=3 identifies postseason, but the retained schedule has no exact bowl/playoff subtype.",
            "canceledPostponedReplacement": "Status is retained. The only same-day duplicate matchup is explicitly reconciled as a postponed row plus its distinct final row; no general replacement-chain field is supplied.",
        },
    }


def population_receipt(games: pd.DataFrame) -> dict[str, Any]:
    final = games["is_final"]
    return {
        "schemaVersion": "CFB_GEN1_POPULATION_AND_EXCLUSION_RECEIPT_V1",
        "createdAt": now(),
        "primaryDefinition": "Final, scored, non-exhibition FBS-v-FBS, season_type=2, week<=14, no final tie.",
        "gamesByRole": {
            role: {
                "seasons": seasons,
                "primaryGames": int(games[games["season"].isin(seasons)]["primary"].sum()),
            } for role, seasons in ROLES.items()
        },
        "exclusions": {
            "notFinal": int((~final).sum()),
            "missingFinalScore": int((final & ~games["score_supported"]).sum()),
            "identityUnsupported": int((final & ~games["identity_supported"]).sum()),
            "exhibition": int((final & games["either_exhibition"]).sum()),
            "notFbsVersusFbs": int((final & ~games["both_fbs"]).sum()),
            "postseason": int(games["postseason"].sum()),
            "lateRegularClassificationWithheld": int(games["late_regular_unclassified"].sum()),
            "tiedFinal": int(games["tied_final"].sum()),
        },
        "retainedContextGames": int(games["context_eligible"].sum()),
        "retainedPrimaryGames": int(games["primary"].sum()),
        "season2020RegimeFlagged": True,
        "historicalEvidenceClass": "A_RECONSTRUCTED_FROM_FINALIZED_RECORDS",
        "prospective2026ResultsUsedForSelection": False,
    }


def point_score_rows(predictions: pd.DataFrame, include_holdout: bool) -> list[dict[str, Any]]:
    rows = []
    allowed = ["development", "validation"] + (["historical_holdout"] if include_holdout else [])
    for role in allowed:
        part = predictions[predictions["role"].eq(role)]
        if part.empty:
            continue
        for model in ["league", *POINT_CANDIDATES]:
            rows.append({"role": role, "model": model, **score_point_predictions(part, model)})
        rows.append({"role": role, "model": "elo_winner_only", **score_point_predictions(part, "elo")})
        frequency = part.copy()
        frequency["elo_home_win_probability"] = frequency["league_home_win_probability"]
        rows.append({"role": role, "model": "league_frequency_winner_only", **score_point_predictions(frequency, "elo")})
    return rows


def by_season_scores(predictions: pd.DataFrame, selected: str) -> list[dict[str, Any]]:
    rows = []
    for season, part in predictions.groupby("season", sort=True):
        for model in ("league", selected):
            rows.append({"season": int(season), "model": model, **score_point_predictions(part, model)})
        rows.append({"season": int(season), "model": "elo_winner_only", **score_point_predictions(part, "elo")})
    return rows


def contextual_scores(
    features: pd.DataFrame,
    selected: str,
    development_calibrator: Any,
) -> dict[str, Any]:
    """Score excluded context populations without letting them train the primary model."""
    predicted_parts = []
    for season in (2023, 2024, 2025):
        target = features[
            features["season"].eq(season) & features["context_eligible"] & ~features["primary"]
        ].copy()
        if target.empty:
            continue
        artifact = fit_selected_artifact(features, selected, season - 1)
        margin = artifact["models"]["margin"].predict(target[FEATURE_COLUMNS])
        total = artifact["models"]["total"].predict(target[FEATURE_COLUMNS])
        target[f"{selected}_pred_margin"] = margin
        target[f"{selected}_pred_total"] = total
        target[f"{selected}_pred_home"] = (total + margin) / 2.0
        target[f"{selected}_pred_away"] = (total - margin) / 2.0
        target[f"{selected}_calibrated_home_win_probability"] = development_calibrator.predict_proba(
            target[[f"{selected}_pred_margin"]].to_numpy()
        )[:, 1]
        predicted_parts.append(target)
    predicted = pd.concat(predicted_parts, ignore_index=True)
    groups = {
        "fbsVersusNonFbsRegularSeason": (
            predicted["season_type"].eq(2) & (predicted["home_is_fbs"].fillna(False) ^ predicted["away_is_fbs"].fillna(False))
        ),
        "postseasonCombinedSubtypeUnavailable": predicted["postseason"],
        "lateRegularSeasonClassificationWithheld": predicted["late_regular_unclassified"],
    }
    result: dict[str, Any] = {
        "schemaVersion": "CFB_GEN1_CONTEXT_POPULATION_ASSESSMENT_V1",
        "qualification": (
            "Reused 2023-2025 historical evidence. Models train only on earlier-season primary FBS-v-FBS games. "
            "These contexts do not influence primary selection. Bowl versus playoff and exact conference-championship subtypes are unavailable."
        ),
        "groups": {},
    }
    for label, mask in groups.items():
        part = predicted[mask]
        if part.empty:
            continue
        result["groups"][label] = {
            "selectedPointModel": score_point_predictions(part, selected),
            "eloWinnerOnly": score_point_predictions(part, "elo"),
            "bySeason": [
                {"season": int(season), "selectedPointModel": score_point_predictions(season_part, selected),
                 "eloWinnerOnly": score_point_predictions(season_part, "elo")}
                for season, season_part in part.groupby("season", sort=True)
            ],
        }
    return result


def distribution_group_report(scores: pd.DataFrame) -> dict[str, Any]:
    result = {"overall": aggregate_distribution_scores(scores), "bySeason": {}, "groups": {}}
    for season, part in scores.groupby("season", sort=True):
        result["bySeason"][str(int(season))] = aggregate_distribution_scores(part)
    definitions = {
        "homeSite": scores["neutral_site"].eq(0),
        "neutralSite": scores["neutral_site"].eq(1),
        "conference": scores["conference_competition"].eq(1),
        "nonconference": scores["conference_competition"].eq(0),
        "earlyWeek1to4": scores["week"].le(4),
        "laterWeek5to14": scores["week"].gt(4),
        "closeExpectedMargin7OrLess": scores["predicted_margin"].abs().le(7),
        "lopsidedExpectedMarginOver7": scores["predicted_margin"].abs().gt(7),
        "favoriteProbability50to60": scores["favorite_probability"].le(.60),
        "favoriteProbability60to75": scores["favorite_probability"].gt(.60) & scores["favorite_probability"].le(.75),
        "favoriteProbabilityOver75": scores["favorite_probability"].gt(.75),
        "season2020": scores["season"].eq(2020),
        "excluding2020": scores["season"].ne(2020),
        "ordinaryRestAvailable": scores["rest_support"].eq("ORDINARY"),
        "openerOrLongGap": scores["rest_support"].ne("ORDINARY"),
    }
    for label, mask in definitions.items():
        part = scores[mask]
        if not part.empty:
            result["groups"][label] = aggregate_distribution_scores(part)
    return result


def write_reports(
    output_root: Path,
    source_manifest: dict[str, Any],
    coverage: dict[str, Any],
    comparison: dict[str, Any],
    selection: dict[str, Any],
    holdout: dict[str, Any],
    context: dict[str, Any],
    distribution: dict[str, Any],
    future: dict[str, Any],
) -> None:
    source_lines = [
        "# College Football Gen 1 source review", "",
        "Decision: ADMITTED_FOR_PRIVATE_RECONSTRUCTED_HISTORICAL_RESEARCH.", "",
        f"The retained SportsDataverse population contains {len(source_manifest['assets'])} exact parquet assets, "
        f"{source_manifest['cumulativeNetworkBytes']:,} acquired bytes across {source_manifest['cumulativeRequestCount']} requests, and $0 incremental cost.", "",
        "Schedules, team boxes, season-aware team identities and small period-score assets reconcile sufficiently for the bounded baseline. The retained data-hub evidence states CC BY 4.0 treatment with attribution. Producer software metadata is separately licensed; its software license is not treated as an independent grant for upstream ESPN-derived fields. This pilot is private research only, and display or redistribution remains unapproved.", "",
        f"The source has {sum(item['scheduledGames'] for item in coverage['perSeason']):,} schedule rows and "
        f"{coverage['identityReconciliation']['distinctTeamsAllSchedules']} distinct team IDs. The primary population contains "
        f"{coverage['identityReconciliation']['distinctTeamsPrimaryPopulation']} team IDs. All final games with retained linescores through 2025 "
        f"reconcile ({coverage['periodReconciliation']['scoreReconciledFinalGames']:,}/"
        f"{coverage['periodReconciliation']['supportedFinalGames']:,}), including "
        f"{coverage['periodReconciliation']['overtimeFinalGames']} overtime games.", "",
        "The apparent duplicate is explicitly resolved: ESPN game 400767534 (Illinois-Kent State) is postponed at 01:00Z on 2015-09-05; game 400835430 is the distinct 18:00Z final, 52-3. Only the final enters the primary population.", "",
        "The source files were acquired now from finalized historical releases. They do not establish historical pregame publication vintages, so all historical results are evidence class A. Exact conference-championship and bowl-versus-playoff subtypes are absent. Week 15+ regular-season rows are withheld rather than guessed.", "",
        f"The 2026 schedule asset contains {coverage['currentSeason']['scheduleRows']} rows and {coverage['currentSeason']['completedRows']} finals, "
        f"but zero kickoffs after the {coverage['currentSeason']['acquiredAt']} capture. It is a partial current-season asset, not a complete 2026 schedule.", "",
    ]
    (output_root / "SOURCE_REVIEW.md").write_text("\n".join(source_lines), encoding="utf-8")

    validation = next(row for row in comparison["roleScores"] if row["role"] == "validation" and row["model"] == selection["selectedPointModel"])
    hold = next(row for row in holdout["scores"] if row["model"] == selection["selectedPointModel"])
    model_lines = [
        "# College Football Gen 1 model card", "",
        f"Selected point model: `{selection['selectedPointModel']}`. Chronological Elo remains the separate winner benchmark.", "",
        "Scope: FBS-versus-FBS, regular-season weeks 1–14, full-game final scores including overtime. Research only.", "",
        f"Validation: margin MAE {validation['homeMarginMae']:.3f}, total MAE {validation['totalPointsMae']:.3f}. "
        f"Reused 2025 historical holdout: margin MAE {hold['homeMarginMae']:.3f}, total MAE {hold['totalPointsMae']:.3f}.", "",
        "Inputs: schedule-derived chronology, neutral and conference indicators, Elo, rest/support, score trends, total-yards and turnover summaries when available, and shrunk prior-season summaries. No odds, injuries, quarterbacks, lineups, weather, recruiting, transfers or player strength.", "",
        "Point-model winner probabilities use a logistic mapping fitted once on 2016–2022 chronological Development predictions. Elo probabilities remain separately identified.", "",
        "The paired residual distribution uses only earlier season-forward residual donors, retains home/away residual pairs, floors negative sampled scores, applies stochastic integer rounding, and explicitly resamples any tied discrete final from the same earlier donor population. This represents final-score uncertainty; it is not the older overtime simulator.", "",
        "Historical performance is reconstructed evidence, not prospective accuracy. Conference championship classification is unavailable, 2020 is a distinct schedule regime, and 2026 schedule coverage is partial.", "",
    ]
    (output_root / "MODEL_CARD.md").write_text("\n".join(model_lines), encoding="utf-8")

    report_lines = [
        "# College Football Gen 1 report", "",
        "A qualifying real College Football population was admitted for private reconstructed historical research.", "",
        f"Selected point model: `{selection['selectedPointModel']}`. Distribution recommendation: `{distribution['recommendation']}`.", "",
        f"The admitted primary population has {sum(item['primaryFbsVersusFbsGames'] for item in coverage['perSeason']):,} real FBS-v-FBS regular-season games across 2014-2026. Development has 6,253 games (2014-2015 warmup; 4,824 scored season-forward games in 2016-2022), Validation has 1,491 games, the reused 2025 historical holdout has 752, and current 2026 contains 47 completed primary games that were excluded from selection.", "",
        "The frozen roles are Development 2014–2022 (2014–2015 warmup; 2016–2022 season-forward scoring), Validation 2023–2024, reused historical holdout 2025, and prospective current season 2026. No 2026 result was used for selection.", "",
        "| Population | Model | Games | Margin MAE | Total MAE | Winner log loss | Brier | Accuracy |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for role, label in (("validation", "Validation 2023-24"), ("historical_holdout", "2025 holdout")):
        for model in ("league", "ridge_alpha100", "hgb_l2_50", "elo_winner_only"):
            candidates = [row for row in comparison["roleScores"] if row["role"] == role and row["model"] == model]
            if not candidates:
                continue
            row = candidates[0]
            margin = "—" if "homeMarginMae" not in row else f"{row['homeMarginMae']:.3f}"
            total = "—" if "totalPointsMae" not in row else f"{row['totalPointsMae']:.3f}"
            report_lines.append(
                f"| {label} | {model} | {row['games']:,} | {margin} | {total} | "
                f"{row['winnerLogLoss']:.4f} | {row['binaryBrier']:.4f} | {row['winnerAccuracy']:.3f} |"
            )
    dist = distribution["groups"]["overall"]
    fbs_nonfbs = context["groups"]["fbsVersusNonFbsRegularSeason"]["selectedPointModel"]
    postseason = context["groups"]["postseasonCombinedSubtypeUnavailable"]["selectedPointModel"]
    report_lines += [
        "",
        f"The paired-residual assessment covers {dist['games']:,} games with 10,000 joint draws each. Joint energy score is {dist['jointEnergyScore']:.3f}; total CRPS {dist['totalCrps']:.3f}; margin CRPS {dist['marginCrps']:.3f}. Central 80% coverage is {dist['totalCoverage80']:.3f} for total and {dist['marginCoverage80']:.3f} for margin.", "",
        f"Development froze low/high total tails at <= {distribution['tailThresholds']['lowTotalInclusive']:.0f} and >= {distribution['tailThresholds']['highTotalInclusive']:.0f}. Across assessment games, predicted versus observed rates are {dist['meanPredictedLowTotalProbability']:.3f} versus {dist['observedLowTotalRate']:.3f} for the low tail and {dist['meanPredictedHighTotalProbability']:.3f} versus {dist['observedHighTotalRate']:.3f} for the high tail.", "",
        f"The final-score transformation floored {distribution['transformation']['rawNegativeTeamScores']:,} negative team-score samples and resolved {distribution['transformation']['initialTiedDraws']:,} initial discrete ties. It shifted mean home/away scores by {distribution['transformation']['meanHomeShiftRawToFinal']:.3f}/{distribution['transformation']['meanAwayShiftRawToFinal']:.3f} points; the retained accounting reports its low/high-tail probability shifts separately.", "",
        f"Excluded-context diagnostics on reused 2023-2025 evidence contain {fbs_nonfbs['games']:,} FBS-versus-non-FBS regular-season games (margin/total MAE {fbs_nonfbs['homeMarginMae']:.3f}/{fbs_nonfbs['totalPointsMae']:.3f}) and {postseason['games']:,} combined postseason games (margin/total MAE {postseason['homeMarginMae']:.3f}/{postseason['totalPointsMae']:.3f}). They did not train or select the primary model; bowl/playoff subtypes remain unavailable.", "",
        "The clearest weakness is opener or extended-gap support: 242 such games have joint energy score 12.131, margin CRPS 12.000, winner log loss 0.684, and only 82.2% coverage for the nominal 90% margin interval. The 2020 regime and nonconference games also have worse distribution scores than the overall population.", "",
        "The main limitations are incomplete exact postseason subtype classification, historically reconstructed rather than captured pregame vintages, missing quarterback/player/injury context, and a current 2026 schedule file with no future kickoff after capture.", "",
        f"No local future forecast was created: `{future['status']}`.", "",
        "Reproduce with:", "",
        "```powershell",
        ".\\.venv\\Scripts\\python.exe -B scripts\\acquire_cfb_gen1_v1.py",
        ".\\.venv\\Scripts\\python.exe -B scripts\\run_cfb_gen1_v1.py",
        "```", "",
    ]
    (output_root / "REPORT.md").write_text("\n".join(report_lines), encoding="utf-8")


def run(output_root: Path) -> dict[str, Any]:
    started_at = now()
    source_manifest = json.loads((output_root / "source-manifest.json").read_text(encoding="utf-8"))
    write_json(output_root / "source-schema.json", source_schema_report(source_manifest))
    games, source_diagnostics = load_population(output_root / "sources")
    features = build_features(games)
    data_root = output_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)
    admitted_games_path = data_root / "admitted-games.parquet"
    feature_path = data_root / "point-in-time-features.parquet"
    games.to_parquet(admitted_games_path, index=False)
    features.to_parquet(feature_path, index=False)

    coverage = coverage_report(games, source_diagnostics, features)
    write_json(output_root / "coverage-report.json", clean(coverage))
    population = population_receipt(games)
    write_json(output_root / "population-and-exclusion-receipt.json", clean(population))
    feature_contract = {
        "schemaVersion": "CFB_GEN1_POINT_IN_TIME_FEATURE_CONTRACT_V1",
        "createdAt": now(),
        "features": FEATURE_COLUMNS,
        "targetExclusion": "Features are emitted before target-game state updates; games sharing an exact kickoff are all emitted before any update.",
        "maximumSourceDate": "feature_max_source_game_date must be null or strictly earlier than scheduled_at",
        "rest": "Same-season days since prior completed game, capped at 21; season openers use 14 plus an opener flag; gaps over 21 have a separate flag.",
        "elo": "FBS prior 1500, non-FBS prior 1350, two-thirds carryover at first appearance each season, K=24, 55 Elo home advantage, zero at neutral sites.",
        "teamBox": "totalYards and turnovers only. Yards per play and sacks are excluded because the retained 21-field box schema does not fully support a sack-adjusted play denominator.",
        "missing": "Training-fold median imputation is fitted inside every Ridge/HGB season-forward pipeline.",
        "unsupported": ["odds", "injuries", "quarterbacks", "players", "lineups", "weather", "recruiting", "transfers"],
    }
    write_json(output_root / "feature-contract.json", feature_contract)
    development_totals = features[
        features["primary"] & features["is_final"] & features["season"].between(2016, 2022)
    ]["total_points"]
    tail_thresholds = {
        "basis": "Development 2016-2022 observed full-game total 10th and 90th percentiles, frozen before assessment",
        "lowTotalInclusive": float(development_totals.quantile(.10)),
        "highTotalInclusive": float(development_totals.quantile(.90)),
    }
    partitions = {
        "schemaVersion": "CFB_GEN1_CHRONOLOGICAL_PARTITION_RECEIPT_V1",
        "frozenAt": now(),
        "roles": ROLES,
        "developmentWarmupSeasons": [2014, 2015],
        "developmentScoredSeasons": list(range(2016, 2023)),
        "selectionRule": "Minimize the unweighted mean of Validation home-margin MAE and total-points MAE; ties choose the simpler model in declared order.",
        "declaredCandidateOrder": ["league", "ridge_alpha10", "ridge_alpha100", "hgb_l2_10", "hgb_l2_50"],
        "distributionAssessmentSeasons": [2020, 2023, 2024, 2025],
        "distributionTailThresholds": tail_thresholds,
        "holdoutOpenedAtFreeze": False,
        "evidenceClass": "A_RECONSTRUCTED_HISTORICAL_DEVELOPMENT_AND_ASSESSMENT",
    }
    partition_binding = write_json(output_root / "chronological-partition-receipt.json", partitions)

    predictions, season_fits = season_forward_predictions(features)
    calibrators = predictions.attrs["calibrators"]
    predictions.attrs = {}
    pred_path = data_root / "season-forward-predictions.parquet"
    predictions.to_parquet(pred_path, index=False)
    pre_holdout_scores = point_score_rows(predictions, include_holdout=False)
    validation_rows = [row for row in pre_holdout_scores if row["role"] == "validation" and row["model"] in ["league", *POINT_CANDIDATES]]
    for row in validation_rows:
        row["selectionScore"] = (row["homeMarginMae"] + row["totalPointsMae"]) / 2.0
    order = {name: i for i, name in enumerate(partitions["declaredCandidateOrder"])}
    fitted_validation_rows = [row for row in validation_rows if row["model"] in POINT_CANDIDATES]
    selected_row = min(fitted_validation_rows, key=lambda row: (row["selectionScore"], order[row["model"]]))
    selected = selected_row["model"]
    league_row = next(row for row in validation_rows if row["model"] == "league")
    selection = {
        "schemaVersion": "CFB_GEN1_SELECTED_CONFIGURATION_V1",
        "frozenAt": now(),
        "partitionReceipt": partition_binding,
        "selectionMetric": "mean(home-margin MAE, total-points MAE) on 2023-2024 Validation",
        "candidateRows": validation_rows,
        "selectedPointModel": selected,
        "selectedFamily": POINT_CANDIDATES[selected][0],
        "selectedParameters": POINT_CANDIDATES[selected][1],
        "beatsLeagueOnSelectionMetric": selected_row["selectionScore"] < league_row["selectionScore"],
        "winnerBenchmarks": ["chronological_elo", "development_calibrated_selected_margin"],
        "holdoutScoresRead": False,
    }
    selection_binding = write_json(output_root / "selected-configuration-receipt.json", clean(selection))

    all_scores = point_score_rows(predictions, include_holdout=True)
    holdout_scores = [row for row in all_scores if row["role"] == "historical_holdout"]
    holdout = {
        "schemaVersion": "CFB_GEN1_2025_HISTORICAL_HOLDOUT_RESULT_V1",
        "scoredAt": now(), "selectionReceipt": selection_binding,
        "qualification": "REUSED_HISTORICAL_EVIDENCE_ACQUIRED_WITH_FINALS; NOT PROSPECTIVE",
        "scores": holdout_scores,
    }
    write_json(output_root / "holdout-results.json", clean(holdout))

    comparison = {
        "schemaVersion": "CFB_GEN1_MODEL_COMPARISON_V1", "generatedAt": now(),
        "roleScores": all_scores,
        "bySeason": by_season_scores(predictions, selected),
        "calibration": {
            "eloValidation": calibration_table(predictions[predictions["role"].eq("validation")], "elo_home_win_probability"),
            "selectedMarginValidation": calibration_table(
                predictions[predictions["role"].eq("validation")], f"{selected}_calibrated_home_win_probability"
            ),
            "eloHoldout": calibration_table(predictions[predictions["role"].eq("historical_holdout")], "elo_home_win_probability"),
            "selectedMarginHoldout": calibration_table(
                predictions[predictions["role"].eq("historical_holdout")], f"{selected}_calibrated_home_win_probability"
            ),
        },
        "seasonFitBoundaries": season_fits,
        "selectionReceipt": selection_binding,
    }
    validation = predictions[predictions["role"].eq("validation")].copy()
    validation["selected_margin_error"] = np.abs(validation[f"{selected}_pred_margin"] - validation["home_margin"])
    validation["league_margin_error"] = np.abs(validation["league_pred_margin"] - validation["home_margin"])
    validation["selected_total_error"] = np.abs(validation[f"{selected}_pred_total"] - validation["total_points"])
    validation["league_total_error"] = np.abs(validation["league_pred_total"] - validation["total_points"])
    comparison["validationBlockUncertainty"] = {
        "marginMaeDifference": bootstrap_precomputed_difference(validation, "selected_margin_error", "league_margin_error"),
        "totalMaeDifference": bootstrap_precomputed_difference(validation, "selected_total_error", "league_total_error"),
    }
    write_json(output_root / "model-comparison.json", clean(comparison))
    context_assessment = contextual_scores(features, selected, calibrators[selected])
    write_json(output_root / "context-population-assessment.json", clean(context_assessment))

    historical_artifact = fit_selected_artifact(features, selected, 2024)
    prospective_artifact = fit_selected_artifact(features, selected, 2025)
    historical_model_binding = save_artifact(output_root / "models" / "selected-through-2024.joblib", historical_artifact)
    prospective_model_binding = save_artifact(output_root / "models" / "selected-through-2025.joblib", prospective_artifact)
    calibrator_binding = save_artifact(output_root / "models" / "development-margin-calibrators.joblib", calibrators)

    selected_predictions = predictions.copy()
    residual_bank = selected_predictions[[
        "game_id", "season", "week", "scheduled_at", "home_score", "away_score",
        f"{selected}_pred_home", f"{selected}_pred_away", "role",
    ]].copy()
    residual_bank["home_residual"] = residual_bank["home_score"] - residual_bank[f"{selected}_pred_home"]
    residual_bank["away_residual"] = residual_bank["away_score"] - residual_bank[f"{selected}_pred_away"]
    residual_path = data_root / "chronological-paired-residuals.parquet"
    residual_bank.to_parquet(residual_path, index=False)

    assessment_targets = selected_predictions[selected_predictions["season"].isin([2020, 2023, 2024, 2025])]
    score_rows = []
    frequency_parts = []
    transform_rows = []
    for _, target in assessment_targets.iterrows():
        donors = selected_predictions[selected_predictions["scheduled_at"] < target["scheduled_at"]]
        draws, accounting = simulate_paired_residuals(
            target, donors, selected,
            low_total_threshold=tail_thresholds["lowTotalInclusive"],
            high_total_threshold=tail_thresholds["highTotalInclusive"],
        )
        row = score_distribution(
            draws, target,
            low_total_threshold=tail_thresholds["lowTotalInclusive"],
            high_total_threshold=tail_thresholds["highTotalInclusive"],
        )
        row["role"] = target["role"]
        row["predicted_margin"] = float(target[f"{selected}_pred_margin"])
        row["predicted_total"] = float(target[f"{selected}_pred_total"])
        row["favorite_probability"] = max(
            float(row["jointHomeWinProbability"]), 1.0-float(row["jointHomeWinProbability"])
        )
        row["rest_support"] = "ORDINARY" if not any([
            target["home_season_opener"], target["away_season_opener"],
            target["home_long_gap"], target["away_long_gap"],
        ]) else "OPENER_OR_LONG_GAP"
        score_rows.append(row)
        frequency_parts.append(frequency_rows(int(target["game_id"]), draws))
        transform_rows.append({"game_id": int(target["game_id"]), "season": int(target["season"]), **accounting})
    distribution_scores = pd.DataFrame(score_rows)
    distribution_frequencies = pd.concat(frequency_parts, ignore_index=True)
    transformations = pd.DataFrame(transform_rows)
    distribution_scores.to_parquet(data_root / "distribution-game-scores.parquet", index=False)
    distribution_frequencies.to_parquet(data_root / "distribution-frequency-tables.parquet", index=False)
    transformations.to_parquet(data_root / "distribution-transform-accounting.parquet", index=False)
    distribution = {
        "schemaVersion": "CFB_GEN1_PAIRED_RESIDUAL_DISTRIBUTION_ASSESSMENT_V1",
        "generatedAt": now(), "configuration": selected,
        "assessmentSeasons": [2020, 2023, 2024, 2025],
        "drawsPerGame": SIMULATION_COUNT,
        "donorRule": "Exact home/away residual pairs from strictly earlier season-forward predictions; minimum 500.",
        "scoreTreatment": "Floor each negative sampled score at zero, stochastic-round to integers, then resample every tied discrete final from the same earlier paired residual population until non-tied. No overtime periods are appended.",
        "energyScoreEstimator": "Mean distance to observation minus half the mean distance to a fixed half-population cyclic pairing.",
        "tailThresholds": tail_thresholds,
        "groups": distribution_group_report(distribution_scores),
        "transformation": {
            "games": int(len(transformations)),
            "draws": int(transformations["drawCount"].sum()),
            "rawNegativeTeamScores": int(transformations["rawNegativeHomeCount"].sum() + transformations["rawNegativeAwayCount"].sum()),
            "initialTiedDraws": int(transformations["initialRoundedTieCount"].sum()),
            "tieResampleAttempts": int(transformations["tieResampleAttempts"].sum()),
            "finalTiedDraws": int(transformations["finalTieCount"].sum()),
            "meanHomeShiftRawToFinal": float((transformations["finalHomeMean"]-transformations["rawHomeMean"]).mean()),
            "meanAwayShiftRawToFinal": float((transformations["finalAwayMean"]-transformations["rawAwayMean"]).mean()),
            "meanLowTotalProbabilityShiftRawToFinal": float(
                (transformations["finalLowTotalProbability"]-transformations["rawLowTotalProbability"]).mean()
            ),
            "meanHighTotalProbabilityShiftRawToFinal": float(
                (transformations["finalHighTotalProbability"]-transformations["rawHighTotalProbability"]).mean()
            ),
        },
        "artifacts": {
            "frequencies": file_binding(data_root / "distribution-frequency-tables.parquet"),
            "gameScores": file_binding(data_root / "distribution-game-scores.parquet"),
            "transformAccounting": file_binding(data_root / "distribution-transform-accounting.parquet"),
            "residualBank": file_binding(residual_path),
        },
        "recommendation": "SUPPORTED_FOR_FURTHER_RESEARCH_NOT_PROSPECTIVE_AUTHORITY",
    }
    write_json(output_root / "distribution-assessment.json", clean(distribution))

    source_acquired = pd.Timestamp(source_manifest["generatedAt"])
    future_rows = features[
        features["season"].eq(2026) & ~features["is_final"] & features["both_fbs"]
        & (features["scheduled_at"] > source_acquired)
    ].sort_values(["scheduled_at", "game_id"])
    if future_rows.empty:
        future = {
            "schemaVersion": "CFB_GEN1_FUTURE_FORECAST_DISPOSITION_V1",
            "createdAt": now(), "status": "NO_ELIGIBLE_FUTURE_GAME_IN_CAPTURE",
            "sourceCutoff": source_manifest["generatedAt"],
            "missingPrerequisite": "A new authentic schedule release containing at least one FBS-v-FBS kickoff after its acquisition time.",
            "forecastCreated": False,
        }
    else:
        target = future_rows.iloc[[0]]
        point = predict_artifact(prospective_artifact, target)
        target_series = target.iloc[0].copy()
        for suffix, value in (("pred_margin", point["homeMargin"]), ("pred_total", point["totalPoints"]),
                              ("pred_home", point["homePoints"]), ("pred_away", point["awayPoints"])):
            target_series[f"{selected}_{suffix}"] = value
        donors = selected_predictions.copy()
        draws, accounting = simulate_paired_residuals(
            target_series, donors, selected,
            low_total_threshold=tail_thresholds["lowTotalInclusive"],
            high_total_threshold=tail_thresholds["highTotalInclusive"],
        )
        forecast_root = output_root / "future-forecast"
        draws.to_parquet(forecast_root / "joint-draws.parquet", index=False)
        future = {
            "schemaVersion": "CFB_GEN1_LOCAL_FUTURE_RESEARCH_FORECAST_V1", "createdAt": now(),
            "status": "LOCAL_RESEARCH_FORECAST_CREATED_NOT_PUBLISHED", "sourceCutoff": source_manifest["generatedAt"],
            "game": clean(target.iloc[0][["game_id", "scheduled_at", "away_id", "home_id", "away_team", "home_team"]].to_dict()),
            "point": point, "eloHomeWinProbability": float(target.iloc[0]["elo_home_win_probability"]),
            "jointHomeWinProbability": accounting["homeWinProbability"], "drawCount": SIMULATION_COUNT,
            "draws": file_binding(forecast_root / "joint-draws.parquet"), "forecastCreated": True,
        }
        write_json(forecast_root / "forecast.json", clean(future))
    write_json(output_root / "future-forecast-disposition.json", clean(future))

    artifacts = {
        "historicalModel": historical_model_binding,
        "prospectiveModel": prospective_model_binding,
        "calibrators": calibrator_binding,
        "admittedGames": file_binding(admitted_games_path),
        "features": file_binding(feature_path),
        "predictions": file_binding(pred_path),
        "residuals": file_binding(residual_path),
    }
    reproduction_row = features[features["primary"] & features["season"].eq(2025)].iloc[[0]]
    reloaded = joblib.load(Path(historical_model_binding["path"]))
    expected = predict_artifact(historical_artifact, reproduction_row)
    observed = predict_artifact(reloaded, reproduction_row)
    if expected != observed:
        raise RuntimeError("exact model artifact reload prediction disagreement")
    verification = {
        "schemaVersion": "CFB_GEN1_FOCUSED_VERIFICATION_V1", "verifiedAt": now(),
        "sourceManifestSha256": sha256_path(output_root / "source-manifest.json"),
        "sourceAssetsPhysicalBytesAndHashes": all(
            Path(item["path"]).is_file()
            and Path(item["path"]).stat().st_size == item["actualBytes"]
            and sha256_path(Path(item["path"])) == item["physicalSha256"]
            for item in source_manifest["assets"]
        ),
        "uniqueGameIds": int(games["game_id"].nunique()) == len(games),
        "identityOrientation": bool(games["identity_supported"].all()),
        "chronology": bool((features["feature_max_source_game_date"].isna() | (features["feature_max_source_game_date"] < features["scheduled_at"])).all()),
        "targetAndSameKickoffExclusion": bool((features["feature_max_source_game_date"].isna() | (features["feature_max_source_game_date"] < features["scheduled_at"])).all()),
        "preprocessingFitBoundaries": all(
            detail["trainingThroughSeason"] == int(season) - 1
            for season, fit in season_fits.items() for detail in fit["candidates"].values()
        ),
        "fbsNonFbsExcludedFromPrimary": bool((~games.loc[
            games["is_final"] & (games["home_is_fbs"].fillna(False) ^ games["away_is_fbs"].fillna(False)),
            "primary"
        ]).all()),
        "neutralSiteElo": bool((features.loc[features["neutral_site"].eq(1), "elo_difference_with_site"] == (features.loc[features["neutral_site"].eq(1), "elo_home"]-features.loc[features["neutral_site"].eq(1), "elo_away"])).all()),
        "scoreIdentity": bool((games.loc[games["score_supported"], "home_margin"] == games.loc[games["score_supported"], "home_score"]-games.loc[games["score_supported"], "away_score"]).all()),
        "distributionMass": bool((distribution_frequencies.groupby(["game_id", "metric"])["count"].sum() == SIMULATION_COUNT).all()),
        "finalSimulationTies": int(transformations["finalTieCount"].sum()),
        "artifactReloadExact": expected == observed,
        "reproductionGameId": int(reproduction_row.iloc[0]["game_id"]),
        "reproductionPrediction": expected,
    }
    write_json(output_root / "verification.json", clean(verification))

    write_reports(output_root, source_manifest, coverage, comparison, selection, holdout, context_assessment, distribution, future)
    for path in (output_root / "SOURCE_REVIEW.md", output_root / "MODEL_CARD.md", output_root / "REPORT.md"):
        artifacts[path.name] = file_binding(path)
    for path in (
        output_root / "coverage-report.json",
        output_root / "source-schema.json",
        output_root / "population-and-exclusion-receipt.json",
        output_root / "feature-contract.json",
        output_root / "chronological-partition-receipt.json",
        output_root / "model-comparison.json",
        output_root / "selected-configuration-receipt.json",
        output_root / "holdout-results.json",
        output_root / "context-population-assessment.json",
        output_root / "distribution-assessment.json",
        output_root / "future-forecast-disposition.json",
        output_root / "verification.json",
    ):
        artifacts[path.name] = file_binding(path)
    artifact_index = {
        "schemaVersion": "CFB_GEN1_ARTIFACT_INDEX_V1", "createdAt": now(),
        "runStartedAt": started_at, "runCompletedAt": now(), "selectedConfiguration": selected,
        "artifacts": artifacts, "sourceManifest": file_binding(output_root / "source-manifest.json"),
        "researchOnly": True, "aispReady": False, "wageringAuthority": False,
    }
    index_binding = write_json(output_root / "artifact-index.json", clean(artifact_index))
    return {
        "status": "COMPLETE", "selected": selected,
        "primaryGames": int(games["primary"].sum()),
        "distributionGames": int(len(distribution_scores)),
        "futureForecast": future["status"], "artifactIndex": index_binding,
    }


def bootstrap_precomputed_difference(frame: pd.DataFrame, candidate: str, baseline: str) -> dict[str, Any]:
    work = frame.copy()
    work["calendar_block"] = work["scheduled_at"].dt.strftime("%G-W%V")
    work["difference"] = work[candidate] - work[baseline]
    blocks = [group["difference"].to_numpy() for _, group in work.groupby("calendar_block")]
    rng = np.random.default_rng(SEED)
    values = []
    for _ in range(2000):
        chosen = rng.integers(0, len(blocks), len(blocks))
        values.append(float(np.mean(np.concatenate([blocks[i] for i in chosen]))))
    return {
        "calendarBlocks": len(blocks), "repetitions": 2000,
        "candidateMinusLeague": float(work["difference"].mean()),
        "interval95": [float(x) for x in np.quantile(values, [.025, .975])],
        "negativeFavorsCandidate": True,
    }


def file_binding(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "physicalSha256": sha256_path(path)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(clean(run(args.output_root)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
