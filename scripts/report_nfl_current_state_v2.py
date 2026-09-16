"""Report a completed, published NFL V2 study without importing/executing models.

All numerical results come from checksum-verified saved JSON/JSONL artifacts.
This command never reads PBP, OOT, estimator objects, quotes from a service, or
any AISP database. Outputs are deterministic, content-addressed and exclusive.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1"
EVIDENCE = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
COMPONENTS = ("DYNAMIC", "HIERARCHICAL", "RESIDUAL", "ENSEMBLE")
GROUPS = ("WEEK_1", "WEEKS_1_4", "WEEKS_5_8", "FULL_SEASON")
LEGACY = ("M1_RECIPE_FOLD_REFIT", "HGB_T2", "C2", "C3")
AUTHORITY = {"status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
             "wageringAuthority": False, "executionAllowedInAISP": False}


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("INCOMPLETE_OR_INCONSISTENT_REPORT_INPUT: " + reason)


def canonical(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + "\n").encode("utf-8")


def file_record(path: Path) -> dict:
    path = path.resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "byteCount": path.stat().st_size}


def _json(payload: bytes) -> Any:
    def invalid(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    return json.loads(payload, parse_constant=invalid)


def read_ref(ref: dict) -> Any:
    path = Path(ref["path"]).resolve(strict=True)
    require(path.is_relative_to((ROOT / "outputs").resolve()), "only saved Model Studio output JSON may be read")
    require(path.suffix == ".json", "JSON reference required; model/data payloads are not report inputs")
    actual = file_record(path)
    require(all(actual[key] == ref[key] for key in ("sha256", "byteCount")), f"checksum/size: {path}")
    return _json(path.read_bytes())


def artifact_ref(result: dict, path: Path) -> dict:
    matches = [ref for ref in result["artifacts"] if Path(ref["path"]).resolve() == path.resolve()]
    require(len(matches) == 1, f"exactly one declared artifact: {path.name}")
    return matches[0]


def _metric(metric: dict, expected_games: int | None = None) -> None:
    require(metric.get("evidenceClass") == EVIDENCE, "metric evidence class")
    count = metric.get("games")
    require(isinstance(count, int) and count >= 0, "metric game count")
    if expected_games is not None:
        require(count == expected_games, "metric cohort count")
    if count == 0:
        require(metric.get("status") == "EMPTY_COHORT", "empty metric status")
        return
    for key in ("multiclassLogLoss", "multiclassBrier", "homeWinEce", "homeScoreMae",
                "awayScoreMae", "marginMae", "totalMae"):
        require(isinstance(metric.get(key), (int, float)) and math.isfinite(metric[key]), f"finite {key}")
    require(set(metric.get("calibration", {})) == {"away", "tie", "home"}, "all class calibration diagnostics")
    for diagnostic in metric["calibration"].values():
        require(diagnostic.get("use") == "DIAGNOSTIC_ONLY_NOT_APPLIED_TO_FORECAST", "diagnostic calibration only")


def load_inputs(delivery_path: Path, result_path: Path) -> dict:
    result_path = result_path.resolve(strict=True)
    delivery_path = delivery_path.resolve(strict=True)
    require(result_path.is_relative_to((OUTPUT / "runs").resolve()), "dedicated completed study path")
    require(delivery_path.is_relative_to((OUTPUT / "deliveries").resolve()), "dedicated delivery receipt path")
    result_ref, delivery_ref = file_record(result_path), file_record(delivery_path)
    result, delivery = read_ref(result_ref), read_ref(delivery_ref)
    require(result.get("contract") == "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2", "study contract")
    require(delivery.get("contract") == "NFL_CURRENT_STATE_V2_DELIVERY_RECEIPT", "delivery contract")
    require(result.get("completedAtUtc") and result.get("runId") == result_path.parent.name, "completed run identity")
    require(delivery.get("study") == result_ref, "delivery must refer to the exact supplied study")
    require(result.get("evidenceClass") == delivery.get("evidenceClass") == EVIDENCE, "study/delivery evidence")
    require(all(result.get(k) == v for k, v in AUTHORITY.items()), "research-only authority")
    for key in ("genericMedianFallbacks", "genericModeFallbacks", "appliedCalibratorFits"):
        require(result.get(key) == 0, key)
    require(result.get("finalOotAccessed") is False, "sealed OOT exclusion")
    expected_verification = {"allPublicationChecksumsValid": True, "allScoreDistributionObjectsValid": True,
                             "finalOotRead": False, "aispWrites": 0, "providerCalls": 0, "modelFits": 0}
    require(all(delivery.get("verification", {}).get(k) == v for k, v in expected_verification.items()), "finalization verification")
    require(delivery.get("registrationRerun", {}).get("status") == "NO_OP", "idempotent registration receipt")
    declaration = read_ref(result["declaration"])
    methodology = read_ref(result["methodology"])
    require(declaration.get("runId") == result["runId"], "declaration run identity")
    require(declaration.get("methodology") == result["methodology"], "declared methodology identity")
    source = declaration["sourceEvidence"]
    require(source.get("evidenceClass") == EVIDENCE and source.get("sealedOotRead") is False, "source evidence boundary")
    require(source.get("seasonsRead") == list(range(1999, 2025)), "physical Development season inventory")
    require(result["developmentGames"] == declaration["developmentGames"] == source["gameCount"], "source counts reconcile")
    n = result["validationGamesPerLag"]
    require(n == declaration["validationGames"] == sum(declaration["validationSeasonCounts"].values()), "validation counts reconcile")
    require(set(declaration["validationSeasonCounts"]) == {str(y) for y in range(2020, 2025)}, "all validation seasons")
    require(declaration.get("modelTrainingStartSeason") == 2000, "declared source-only warmup")
    warmup = read_ref(declaration["warmupClarification"])
    clarifications = read_ref(declaration["implementationClarifications"])
    inventory_ref = artifact_ref(result, result_path.parent / "treatment-inventory.json")
    inventory = read_ref(inventory_ref)
    rows = inventory["rows"]
    require(len(rows) == len({row["feature"] for row in rows}) == 44, "exact 44-field inventory")
    require(all(row.get("eligibilityClass") == "A_RECONSTRUCTABLE_WITH_B_SEASON_START_PRIOR"
                and row.get("genericMedianOrModeFallback") is False and row.get("evidenceClass") == EVIDENCE
                for row in rows), "all 44 A+B treatments are fallback-free")
    expected_pipelines = {f"{component}_LAG{lag}" for lag in (48, 72) for component in COMPONENTS}
    leaderboard = result["leaderboard"]
    require(len(leaderboard) == 8 and {row["pipelineId"] for row in leaderboard} == expected_pipelines, "all eight candidate/lag results")
    for row in leaderboard:
        _metric(row, n)
        for group in GROUPS:
            _metric(row["subgroups"][group], n if group == "FULL_SEASON" else None)
        require(set(row.get("distribution", {})) == {"home", "away", "margin", "total"}, "candidate distribution diagnostics")
    require(set(result["legacyComparators"]) == set(LEGACY), "four saved reference recipes")
    for reference in result["legacyComparators"].values():
        for group in GROUPS:
            _metric(reference["subgroups"][group], n if group == "FULL_SEASON" else None)
            if reference["savedCalibratedSubgroups"] is not None:
                _metric(reference["savedCalibratedSubgroups"][group], n if group == "FULL_SEASON" else None)
    expected_folds = {(lag, year) for lag in (48, 72) for year in range(2020, 2025)}
    require(len(result["fittedModels"]) == 10 and {(r["lagHours"], r["validationSeason"]) for r in result["fittedModels"]} == expected_folds, "ten fitted outer systems")
    require(len(result["foldReports"]) == 40 and {(r["lagHours"], r["season"], r["component"]) for r in result["foldReports"]}
            == {(lag, year, component) for lag, year in expected_folds for component in COMPONENTS}, "forty component-fold reports")
    for key in ("pairedComparisons", "pairedComparisonsAgainstSavedCalibratedLegacy"):
        require(set(result[key]) == expected_pipelines, "paired candidate coverage")
        for references in result[key].values():
            expected_refs = set(LEGACY) if key == "pairedComparisons" else {
                name for name, ref in result["legacyComparators"].items() if ref["savedCalibratedSubgroups"] is not None}
            require(set(references) == expected_refs, "paired comparator coverage")
            for comparisons in references.values():
                for group in GROUPS:
                    comparison = comparisons[group]
                    require(comparison.get("evidenceClass") == EVIDENCE and len(comparison.get("interval95", [])) == 2, "paired interval")
                    require(comparison.get("events") == n if group == "FULL_SEASON" else comparison.get("events", 0) > 0, "paired event count")
    require(set(result["lag72Minus48"]) == set(COMPONENTS), "all lag sensitivities")
    require(all(row["matchedGames"] == n and row["lateCorrectionBiasEstimated"] is False for row in result["lag72Minus48"].values()), "lag interpretation")
    receipt_ref = artifact_ref(result, result_path.parent / "fit-receipts.jsonl")
    actual_receipt = file_record(Path(receipt_ref["path"]))
    require(all(actual_receipt[k] == receipt_ref[k] for k in ("sha256", "byteCount")), "fit receipt identity")
    fit_events = [_json(line.encode("utf-8")) for line in Path(receipt_ref["path"]).read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = dict(Counter(event["event"] for event in fit_events))
    require(counts == result["actualFitAccounting"], "fit events equal result accounting")
    require(counts.get("FOLD_COMPLETE") == 10 and counts.get("FINAL_MODEL_RELOAD_VERIFIED") == 1, "completed folds and final reload")
    require(counts.get("ESTIMATOR_FIT_COMPLETE") == methodology["fitBudget"]["totalPlannedEstimatorFits"], "declared estimator-fit budget completed")
    for key, value in counts.items():
        if key.endswith("_START"):
            require(counts.get(key[:-6] + "_COMPLETE") == value, f"start/completion balance for {key}")
    require(not any(event.get("reloadMismatch", event.get("mismatchCount", 0)) for event in fit_events), "zero serialization mismatch")
    diagnostics = result["calibrationDiagnosticsAccounting"]
    require(diagnostics.get("optimizerStarts", 0) == diagnostics.get("optimizerSuccesses", 0) + diagnostics.get("optimizerFailures", 0), "diagnostic optimizer completion accounting")
    fitted_state_ref = artifact_ref(result, Path(result["finalModel"]["path"]).with_name("fitted-state.json"))
    fitted_state = read_ref(fitted_state_ref)
    require(fitted_state.get("semanticInputs") == 44 and fitted_state.get("uncertaintyIsCalibrated") is False, "fitted semantic/calibration state")
    publication = delivery["publication"]
    handoff = read_ref(publication["handoff"])
    manifest = read_ref(publication["manifest"])
    require(handoff.get("schemaVersion") == "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2", "distribution handoff contract")
    require(handoff.get("study") == result_ref, "published study identity")
    require(all(handoff.get(k) == v for k, v in AUTHORITY.items()), "handoff authority")
    require(handoff.get("trainingEvidenceClass") == EVIDENCE and handoff.get("forecastObservationEvidenceClass") == "OBSERVED_AS_OF", "forecast evidence distinction")
    require(handoff.get("modelFits") == handoff.get("providerCalls") == handoff.get("aispWrites") == 0 and handoff.get("sealed2025Read") is False, "publication boundaries")
    require(manifest.get("handoff") == publication["handoff"], "publication manifest handoff")
    require(publication["forecastCount"] == handoff["forecastCount"] == len(handoff["forecasts"]), "published forecast counts")
    require(handoff["artifactCount"] == len(handoff["artifacts"]) == handoff["forecastCount"], "distribution count")
    require(publication["eventCount"] == handoff["forecastEventCount"] and publication["skipCount"] == len(publication["skips"]), "publication event/skip counts")
    require(publication["skips"] == handoff["skips"], "handoff skips reconcile")
    require(bool(handoff.get("importInstruction")), "exact AISP import instruction")
    context = read_ref(publication["context"])
    require(context.get("numericallyIncorporated") is False and context.get("evidenceClass") == "OBSERVED_AS_OF", "current context is supplemental only")
    forecasts = []
    for ref in handoff["forecasts"]:
        forecast = read_ref(ref)
        require(forecast.get("schemaVersion") == "NFL_CURRENT_STATE_GAME_FORECAST_V2", "current forecast contract")
        require(forecast.get("currentContextNumericallyIncorporated") is False and forecast.get("sealed2025Excluded") is True, "current forecast limitations")
        require(forecast.get("noGenericMedianOrModeFallback") is True and forecast["uncertainty"].get("isCalibrated") is False, "forecast fallback/uncertainty")
        keep = ("forecastId", "eventId", "model", "homeTeam", "awayTeam", "scheduledStartUtc", "forecastCreatedUtc",
                "forecastCutoffUtc", "sourceCutoffUtc", "sourceCutoffMeaning", "historicalEvidenceThroughDate",
                "trainingEvidenceClass", "forecastObservationEvidenceClass", "missingInputs", "uncertainty",
                "treatmentBranchCounts", "expectedHomeScore", "expectedAwayScore", "homeWinProbability",
                "awayWinProbability", "tieProbability", "scoreMeanEstimator", "numericalIdentitySha256")
        forecasts.append({**{key: forecast[key] for key in keep if key in forecast}, "artifact": ref})
    require(len({(r["eventId"], r["model"]["engineId"]) for r in forecasts}) == len(forecasts), "unique current event/model forecasts")
    require(len({r["eventId"] for r in forecasts}) == handoff["forecastEventCount"], "unique forecast events")
    market = read_ref(delivery["marketComparison"]["comparison"])
    market_contract = read_ref(delivery["marketComparison"]["contract"])
    require(market.get("status") == delivery["marketComparison"]["status"], "market status")
    require(market["forecastCount"] == handoff["forecastCount"], "market forecast count")
    play = read_ref(delivery["independentPlayComparison"]) if delivery.get("independentPlayComparison") else None
    if play is not None:
        require(play.get("comparisonStatus") == "NOT_COUPLED_NOT_CALIBRATED_TO_MATCH" and play.get("actualGameOutcomesRead") is False, "independent play comparison meaning")
    auxiliary_refs = {name: file_record(OUTPUT / filename) for name, filename in (
        ("cohortReconciliation", "cohort-reconciliation.json"), ("forwardArchiveSchedule", "forward-archive-schedule.json"))}
    reconciliation, schedule = (read_ref(auxiliary_refs[name]) for name in ("cohortReconciliation", "forwardArchiveSchedule"))
    require(reconciliation["reconstructedCacheManifest"]["gameCount"] == result["developmentGames"], "reconciliation source cohort")
    require(reconciliation.get("validation2020Through2024MembershipChanged") is False, "validation reconciliation")
    require(reconciliation["existingDevelopmentReference"]["gameCount"] - len(reconciliation["missingFromReconstructedPbpCohort"]) + len(reconciliation["extraReconstructedGames"]) == result["developmentGames"], "missing-game arithmetic")
    require(schedule.get("cadenceHours") == 6 and schedule.get("status") == "ACTIVE", "active archival schedule receipt")
    return {"result": result, "delivery": delivery, "declaration": declaration, "methodology": methodology,
            "warmup": warmup, "clarifications": clarifications, "inventory": inventory, "fitEvents": fit_events,
            "fittedState": fitted_state, "handoff": handoff, "manifest": manifest, "context": context,
            "forecasts": forecasts, "market": market, "marketContract": market_contract, "play": play,
            "reconciliation": reconciliation, "schedule": schedule,
            "refs": {"study": result_ref, "delivery": delivery_ref, "inventory": inventory_ref,
                     "fitReceipts": receipt_ref, "fittedState": fitted_state_ref, **auxiliary_refs}}


def fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def cell(value: Any) -> str:
    return fmt(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def table(headers: list[str], rows: list[list[Any]]) -> str:
    return "\n".join(["| " + " | ".join(map(cell, headers)) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
                     + ["| " + " | ".join(map(cell, row)) + " |" for row in rows])


def link(ref: dict, label: str) -> str:
    return f"[{label}](<{Path(ref['path']).as_posix()}>)"


def metric_row(label: str, metric: dict) -> list:
    return [label, metric["games"]] + [metric.get(key) for key in (
        "multiclassLogLoss", "multiclassBrier", "homeWinEce", "homeScoreMae", "awayScoreMae", "marginMae", "totalMae")]


def summarize_state(state: dict) -> dict:
    omitted = {"observedTrainingCenters", "observedTrainingScales", "leaguePrior", "residualAuthorities"}
    summary = {key: value for key, value in state.items() if key not in omitted}
    summary["leaguePrior"] = {key: value for key, value in state["leaguePrior"].items() if key != "training_ids"}
    summary["residualAuthorities"] = {name: {key: value for key, value in bank.items() if key != "rowIds"}
                                      for name, bank in state["residualAuthorities"].items()}
    summary["fullStateIncludesTransformAndRowIdentities"] = True
    return summary


def build_card(data: dict) -> dict:
    result, declaration, delivery = (data[k] for k in ("result", "declaration", "delivery"))
    return {"contract": "NFL_CURRENT_STATE_V2_FINAL_MODEL_CARD_V1", **AUTHORITY,
            "evidenceClass": EVIDENCE, "completedAtUtc": result["completedAtUtc"], "runId": result["runId"],
            "reportingScope": "SAVED_COMPLETED_RUN_AND_DELIVERY_ONLY; NO_MODEL_EXECUTION_OR_NEW_EVALUATION",
            "sources": data["refs"], "generatingCode": declaration["generatingCode"],
            "methodology": data["methodology"], "sourceEvidence": declaration["sourceEvidence"],
            "warmupClarification": data["warmup"], "implementationClarifications": data["clarifications"],
            "cohortReconciliation": data["reconciliation"], "treatmentInventory": data["inventory"],
            "developmentGames": result["developmentGames"], "validationGamesPerLag": result["validationGamesPerLag"],
            "validationSeasonCounts": declaration["validationSeasonCounts"],
            "sourceOnlyWarmupGames": declaration["sourceOnlyWarmupGames"],
            "fittedStateSummary": summarize_state(data["fittedState"]),
            "results": {key: result[key] for key in ("leaderboard", "foldReports", "legacyComparators", "pairedComparisons",
                "pairedComparisonsAgainstSavedCalibratedLegacy", "lag72Minus48", "finalEnsembleResidualWeight", "finalEnsembleDisposition",
                "actualFitAccounting", "runtimeSeconds", "calibrationDiagnosticsAccounting", "appliedCalibratorFits",
                "genericMedianFallbacks", "genericModeFallbacks", "finalOotAccessed", "lateCorrections", "unsupportedHistoricalSubgroups", "selection")},
            "fitAccountingScope": "This completed run only. No claim about unrecorded or separately abandoned attempts.",
            "completionStatus": "PARTIAL_CURRENT_LEARNED_CHALLENGER_BLOCKED" if data.get("admission") else "COMPLETED_RESEARCH_ONLY",
            "currentPublication": data.get("admittedPublication", delivery["publication"]), "currentForecastSummaries": data["forecasts"],
            "predecessorPublication": delivery["publication"] if data.get("admission") else None,
            "predecessorForecastSummariesWithheldExceptDynamic": data.get("predecessorForecasts"),
            "publicationAdmission": data.get("admission"), "currentLearnedModelDiagnostic": data.get("diagnostic"),
            "correctiveCompletion": data.get("correctiveCompletion"),
            "currentObservedContext": data["context"],
            "distributionHandoff": {key: value for key, value in data["handoff"].items() if key not in ("artifacts", "forecasts")},
            "independentPlayComparison": data["play"],
            "independentPlayComparisonScope": "PREDECESSOR_AUDIT_NOT_AUTHORITY_TO_IMPORT_WITHHELD_MODELS" if data.get("admission") else "CURRENT_PUBLICATION",
            "marketComparison": data["market"],
            "marketJoinContract": data["marketContract"], "forwardArchiveSchedule": data["schedule"],
            "registration": data.get("correctiveCompletion", delivery)["registration"],
            "registrationRerun": data.get("correctiveCompletion", delivery)["registrationRerun"],
            "finalizationVerification": delivery["verification"],
            "actualPublicationIdempotency": data.get("publicationVerification"),
            "calibrationAppliedToNewForecasts": False, "productionSuperiorityEstablished": False,
            "historicalPublicationVintagesEstablished": False, "currentContextNumericallyIncorporated": False,
            "sealed2025ReadByReporter": False, "newFitsByReporter": 0, "providerCallsByReporter": 0, "aispAccessByReporter": False}


def build_markdown(data: dict, card_ref: dict) -> str:
    r, d, h, source = data["result"], data["declaration"], data["handoff"], data["declaration"]["sourceEvidence"]
    publication = data.get("admittedPublication", data["delivery"]["publication"])
    market_publication = data.get("admittedMarketComparison", data["delivery"]["marketComparison"])
    parts = ["# NFL current-state V2 — partial completion; learned current challenger blocked" if data.get("admission")
             else "# NFL current-state V2 — completed research report",
        f"Run `{r['runId']}` · Study completed {r['completedAtUtc']}.\n\n"
        "RESEARCH_SHADOW / NOT_PROMOTED. M1 is not replaced. No wagering authority or model execution in AISP is granted.",
        "## Bottom line",
        f"The completed study used {r['developmentGames']:,} reconstructed source games and {r['validationGamesPerLag']:,} "
        "out-of-fold games at each availability lag. All 44 registered fields use A+B evidence treatment, with zero generic median/mode fallbacks. "
        "The comparisons below describe finalized historical archives—not genuine historical publication snapshots or proof of production superiority. "
        "The current numerical core ends with 2024-season evidence; sealed 2025 was not read. Current roster/depth context is separate and is not a numerical model input.",
        "## Evidence and chronology",
        table(["Class / scope", "What the evidence supports"], [
            ["RETROSPECTIVE_RECONSTRUCTED_AS_OF", "Historical features, targets, OOF forecasts and metrics from eligible prior events in finalized archives; unknown late corrections remain."],
            ["OBSERVED_AS_OF", "Actually captured current source bytes and timestamps; current saved forecast observation, not observed game outcomes or historical model-input vintages."],
            ["Current-2026-only supplemental context", "Archived roster/depth identities and available named-player priors; no inferred confirmed starter, roster-weighted numerical carry-forward or historical uplift claim."],
            ["Excluded / unsupported", ", ".join(r["unsupportedHistoricalSubgroups"]) + "; sealed 2025, untimed prices and future/target/same-slate outcomes."]]),
        f"Completion rule: {data['methodology']['completionRule']}\n\nCutoff rule: {data['methodology']['forecastCutoffRule']}\n\n"
        f"Source rows potentially exposed to unverified corrections: {r['lateCorrections']['rowsSubjectToUnverifiedLateCorrections']:,} "
        f"({100*r['lateCorrections']['fraction']:.1f}%). Correction-bias magnitude: {fmt(r['lateCorrections']['correctionBiasMagnitude'])}. "
        "The 48/72-hour comparison measures the declared availability-mask sensitivity, not revision bias.",
        "## Cohort and warmup",
        table(["Quantity", "Recorded count"], [["Source games", r["developmentGames"]], ["Raw PBP rows", source["rawPlayRows"]],
            ["Team-game metric rows", source["teamMetricRows"]], ["QB-game rows", source["qbGameRows"]],
            ["1999 source-only warmup games", d["sourceOnlyWarmupGames"]], ["Model training begins", d["modelTrainingStartSeason"]],
            *[[f"Validation season {year}", count] for year, count in sorted(d["validationSeasonCounts"].items())],
            ["Validation games per lag (same IDs)", r["validationGamesPerLag"]]]),
        "The first source season supplies prior history but is not a training-target season. Three schedule-derived historical rows in the prior "
        "semantic cohort have no eligible PBP team-game here; no score-only pseudo-exposures were manufactured. The 2020–2024 validation membership is unchanged.",
        table(["Excluded historical game", "Date", "Reason"], [[row["gameId"], row["date"], "No corresponding eligible reconstructed PBP team-game"]
              for row in data["reconciliation"]["missingFromReconstructedPbpCohort"]]),
        "## Model and treatment method",
        "Numerator/exposure evidence is opponent-adjusted and pooled into league/team/unit priors. Observed zero with positive exposure is data; zero opportunities "
        "add no observation. Fold-selected retention provides between-season regression; lagged prior-usage QB evidence is not a target-starter designation. "
        "The historical QB-labeled layer is pass-attempt-weighted prior usage grouped by the source passer_player_id; it may include occasional non-QB passers "
        "and is not independently verified historical QB-role or target-starter identity. "
        "Unavailable linear increments are excluded with an explicit indicator; the nonlinear branch retains native missing values. Neither is a replacement raw median.",
        table(["Component", "Declared method"], [[name, data["clarifications"]["dynamicComponentScope"] if name == "DYNAMIC"
                                                else data["methodology"]["candidatePlan"][name]] for name in COMPONENTS]),
        f"Recency scope: {data['clarifications']['recencyMeaning']}.\n\n"
        f"Uncertainty scope: {data['clarifications']['uncertaintyMeaning']}. This is not a fully propagated Bayesian posterior.",
        f"Final selected retention: {fmt(data['fittedState']['selectedRetention'])}; final residual ensemble weight: "
        f"{fmt(r['finalEnsembleResidualWeight'])}; disposition: `{r['finalEnsembleDisposition']['status']}`. "
        "Decay is selected on the last training season; paired score residuals come from chronological inner holdout, not in-sample residuals. "
        "The ensemble uses earlier outer OOF seasons only and falls back to its declared hierarchical warmup when unsupported. "
        "Final-score targets include overtime; the numerical model does not reconstruct an overtime decision process.",
        "### Exact 44-field inventory",
        "Every row below is `A_RECONSTRUCTABLE_WITH_B_SEASON_START_PRIOR`, uses reconstructed evidence, and has `genericMedianOrModeFallback=false`. "
        "Full treatment, missingness, uncertainty and exclusion metadata are retained in the model card and inventory artifact.",
        table(["Field", "Unit", "Numerator / measurement", "Actual exposure denominator"],
              [[row["feature"], row["unit"], row["definition"], row["exposureDenominator"]] for row in data["inventory"]["rows"]]),
        "### Recorded treatment coverage",
        "Counts below are game × semantic-field cells, reported once per fold because the components share their treatment state. "
        "The separate excluded-incremental count also covers supplemental inputs and is not an additional mutually exclusive 44-field branch.",
        table(["Lag", "Validation season", "Games", "Prior-only cells", "Current-evidence cells", "Unknown-source cells", "Excluded incremental cells"],
              [[row["lagHours"], row["season"], row["branchCounts"]["games"], row["branchCounts"]["priorOnlyCells"],
                row["branchCounts"]["currentEvidenceCells"], row["branchCounts"]["sourceUnknownCells"],
                row["branchCounts"]["excludedUnavailableIncrementalCells"]] for row in r["foldReports"] if row["component"] == "DYNAMIC"]),
        "The turnover definition deliberately requires both flags to be observed rather than converting missing flags into zero. "
        "Historical EPA is the provider-derived historical label, not a newly fold-trained EPA model. Clock evidence is elapsed source game clock, "
        "not a fitted legal play-duration process. No historical target-game starters, roster, injuries, venue/weather or market prices are introduced.",
        "## Full-season candidate comparison",
        "Lower log loss, Brier and MAE are better. Brier is the sum across away/tie/home classes. The new candidates are raw distributions; "
        "no fitted calibration is applied to them. All numbers are saved OOF results on the same validation game identities.",
        table(["Pipeline", "Games", "Log loss", "Brier Σ3", "Home ECE", "Home MAE", "Away MAE", "Margin MAE", "Total MAE"],
              [metric_row(row["pipelineId"], row) for row in r["leaderboard"]]),
        "### Saved M1 / HGB-T2 / C2 / C3 comparators",
        "These saved recipes retain their legacy prior-date availability treatment; they were not retrained under the new 48/72-hour embargo. "
        "Saved chronological calibrations are reused where present, without refitting. Differences therefore cannot be attributed solely to the 44-field change."]
    legacy_rows = []
    for name in LEGACY:
        reference = r["legacyComparators"][name]
        legacy_rows.append(metric_row(name + " raw", reference["subgroups"]["FULL_SEASON"]))
        if reference["savedCalibratedSubgroups"] is not None:
            legacy_rows.append(metric_row(name + " saved calibrated", reference["savedCalibratedSubgroups"]["FULL_SEASON"]))
        else:
            legacy_rows.append([name + " saved calibrated", "not available"] + [None] * 7)
    parts.append(table(["Reference", "Games", "Log loss", "Brier Σ3", "Home ECE", "Home MAE", "Away MAE", "Margin MAE", "Total MAE"], legacy_rows))
    parts.extend(["## Early-season calibration and distribution coverage",
        "Classwise intercept/slope are diagnostic fits only, not deployed calibrators. A missing diagnostic is not a successful fit. "
        "Coverage targets 90%; sharpness is interval width in score points. Week-1 inference has few season/week blocks and is descriptive. "
        "All class reliability bins, tie diagnostics, key-number masses, CRPS, home/away coverage and subgroup metrics are included in the model card."])
    early = []
    for row in r["leaderboard"]:
        for group in GROUPS:
            m = row["subgroups"][group]
            calibration = m.get("calibration", {}).get("home", {})
            distribution = m.get("distribution", {})
            early.append([row["pipelineId"], group, m["games"], m.get("multiclassLogLoss"), m.get("homeWinEce"),
                calibration.get("intercept"), calibration.get("slope"), calibration.get("status"),
                distribution.get("margin", {}).get("coverage90"), distribution.get("total", {}).get("coverage90"),
                distribution.get("margin", {}).get("sharpness90"), distribution.get("total", {}).get("sharpness90")])
    parts.append(table(["Pipeline", "Cohort", "N", "Log loss", "Home ECE", "Home intercept", "Home slope", "Diagnostic status",
                        "Margin 90% coverage", "Total 90% coverage", "Margin width", "Total width"], early))
    parts.extend(["### Saved reference early-season calibration",
        "These diagnostic summaries describe each saved raw or saved-calibrated probability series; score forecasts themselves are not recalibrated by this report."])
    early_legacy = []
    for name in LEGACY:
        for variant, key in (("raw", "subgroups"), ("saved calibrated", "savedCalibratedSubgroups")):
            groups = r["legacyComparators"][name][key]
            if groups is None:
                continue
            for group in GROUPS[:-1]:
                m = groups[group]
                c = m["calibration"]["home"]
                early_legacy.append([name, variant, group, m["games"], m["multiclassLogLoss"], m["multiclassBrier"],
                                     m["homeWinEce"], c.get("intercept"), c.get("slope"), c["status"]])
    parts.append(table(["Reference", "Probability series", "Cohort", "N", "Log loss", "Brier Σ3", "Home ECE", "Home intercept", "Home slope", "Status"], early_legacy))
    parts.extend(["## Paired log-loss differences and comparisons with M1",
        "Difference = new candidate minus saved reference: negative favors the new candidate on this metric; positive favors the reference. "
        "Intervals use 2,000 whole season/week block resamples and are exploratory after Development model selection, not independent confirmation. "
        "The primary RESIDUAL_LAG48 comparisons are below; all eight pipelines against every available raw/calibrated reference remain in the model card."])
    paired_rows = []
    for variant, key in (("raw", "pairedComparisons"), ("saved calibrated", "pairedComparisonsAgainstSavedCalibratedLegacy")):
        for name, groups in r[key]["RESIDUAL_LAG48"].items():
            for group in GROUPS:
                v = groups[group]
                lower, upper = v["interval95"]
                interpretation = "interval spans zero" if lower <= 0 <= upper else "lower candidate loss" if upper < 0 else "higher candidate loss"
                paired_rows.append([name, variant, group, v["events"], v["pairedMean"], f"[{fmt(lower)}, {fmt(upper)}]", v["seasonWeekBlocks"], interpretation])
    parts.append(table(["Reference", "Series", "Cohort", "N", "Δ log loss", "95% interval", "Blocks", "Descriptive reading"], paired_rows))
    m1 = r["pairedComparisons"]["RESIDUAL_LAG48"]["M1_RECIPE_FOLD_REFIT"]["FULL_SEASON"]
    reading = "lower" if m1["pairedMean"] < 0 else "higher" if m1["pairedMean"] > 0 else "equal"
    parts.append(f"Against the saved raw M1 recipe, the primary challenger's full-season mean log loss is {reading}: "
                 f"Δ={fmt(m1['pairedMean'])}, 95% interval [{fmt(m1['interval95'][0])}, {fmt(m1['interval95'][1])}]. "
                 "This does not establish production superiority or justify promotion. Other metrics and early-season comparisons may disagree.")
    parts.extend(["## 72-hour minus 48-hour sensitivity",
        table(["Component", "Matched games", "Changed-probability games", "Mean |class Δp|", "Maximum |class Δp|", "Δ full log loss", "95% interval"],
            [[name, v["matchedGames"], v["probabilityChangedGames"], v["meanAbsoluteClassProbabilityChange"], v["maximumAbsoluteClassProbabilityChange"],
              v["lossComparisons"]["FULL_SEASON"]["pairedMean"], str(v["lossComparisons"]["FULL_SEASON"]["interval95"])] for name, v in r["lag72Minus48"].items()]),
        "## Current 2026 publication",
        f"Published {h['forecastCount']:,} immutable forecasts and {h['artifactCount']:,} joint-score artifacts for {h['forecastEventCount']:,} "
        f"forecast events from {h['eventCount']:,} selected schedule events; {len(h['skips']):,} explicit skip records. "
        f"Each published distribution represents {h['drawsPerForecast']:,} paired score draws. Forecast summaries and every source reference are in the model card.",
        "The stale 2024-season numerical history is regressed across intervening seasons. Missing sealed 2025 initialization is explicitly recorded; "
        "the extra uncertainty is not calibrated. A fresh archive retrieval does not make the underlying team statistics current. "
        "Current roster/depth and named-player context is supplemental only: no confirmed current starter, roster-weighted numerical carry-forward, "
        "injury, coaching or weather adjustment is claimed. Current-2026 listed-QB context uses the archived source position=QB designation, "
        "but remains nonnumerical. The current numerical historical-source guard accepts only 1999–2024; future incorporation of 2026 statistics "
        "into the numerical core is not implemented or claimed. Forward archival begins now and is a separate capability.",
        table(["Current source family", "Recorded status", "Observed at", "Object effective at", "Selected row effective times", "Selected QB rows"],
              [[name, row.get("status"), row.get("observedAtUtc"), row.get("effectiveAt"),
                ", ".join(row.get("selectedEffectiveTimes", [])) or None, row.get("selectedQbRows")]
               for name, row in data["context"]["families"].items()]),
        table(["Engine", "Published forecasts"], sorted(Counter(f["model"]["engineId"] for f in data["forecasts"]).items()))])
    displayed_engine = "NFL_CURRENT_STATE_DYNAMIC_V2" if data.get("admission") else "NFL_CURRENT_STATE_RESIDUAL_V2"
    primary_forecasts = [f for f in data["forecasts"] if f["model"]["engineId"] == displayed_engine]
    if primary_forecasts:
        parts.extend(["### Admitted dynamic-baseline research forecasts" if data.get("admission") else "### Primary residual research forecasts",
            "Means below are the published empirical joint-law expectations, not a separate unrounded mean estimator. Admitted forecast summaries and uncertainty/source timestamps are retained in the model card. "
            "The historical-through date includes the 2024 season's postseason in calendar 2025; the sealed exclusion is the 2025 NFL season.",
            table(["Event", "Away", "Home", "Expected away", "Expected home", "Away win", "Tie", "Home win", "Forecast cutoff UTC", "Historical evidence through"],
                  [[f["eventId"], f["awayTeam"]["abbreviation"], f["homeTeam"]["abbreviation"], f["expectedAwayScore"],
                    f["expectedHomeScore"], f["awayWinProbability"], f["tieProbability"], f["homeWinProbability"],
                    f["forecastCutoffUtc"], f["historicalEvidenceThroughDate"]] for f in primary_forecasts])])
        if not data.get("admission") and all(f["homeWinProbability"] > f["awayWinProbability"] for f in primary_forecasts):
            parts.append(f"Current-slate warning: all {len(primary_forecasts)} primary forecasts favor the home team; saved home-win probabilities range "
                         f"from {min(f['homeWinProbability'] for f in primary_forecasts):.4f} to {max(f['homeWinProbability'] for f in primary_forecasts):.4f}. "
                         "This concentration requires review. It is not calibrated confidence, evidence of accuracy or a diagnosed cause; the saved predictions remain unchanged.")
    if h["skips"]:
        parts.extend(["### Explicit skips", "```json\n" + json.dumps(h["skips"], ensure_ascii=False, indent=2, allow_nan=False) + "\n```"])
    else:
        parts.append("The completed handoff records no skipped events.")
    parts.extend(["### Joint-law and independent play-engine limits",
        "Home/away/tie, expected scores, margin, total and score-distribution queries reconcile to the same empirical joint score law. "
        "Paired inner-holdout residuals retain score dependence, but nonnegative integer final scores are not constrained to legal scoring sequences. "
        "This is not a play/drive simulator; no trajectories, overtime incidence or tactical path is inferred. The independent play engine remains a different generating law."])
    if data["play"] is not None:
        p = data["play"]
        parts.append(("Predecessor audit only; this comparison does not admit withheld models. " if data.get("admission") else "")
                     + f"Saved-law comparison: {p['matchedEventCount']:,} matched events / {p['matchedEventModelRows']:,} event-model rows, "
                     f"status `{p['comparisonStatus']}`. Models executed: {p['modelsExecuted']}; calibration fits: {p['calibrationFits']}; new play paths: {p['newPlayPaths']}. "
                     "Any disagreement is not an accuracy result, outcome test or wagering edge. Full deltas and differing source timestamps are retained in the model card.")
    else:
        parts.append("No completed independent play-law comparison was supplied in this delivery receipt; none is claimed.")
    parts.extend(["## Fit accounting, runtime and verification",
        f"Study runtime: {r['runtimeSeconds']:.2f} seconds ({r['runtimeSeconds']/60:.2f} minutes). "
        "This is the runtime recorded by the study, not an inferred end-to-end duration including source preparation/publication. "
        "The table is reconciled against the exact saved fit-event ledger. It covers this completed run only, not unrecorded or separately abandoned attempts.",
        table(["Recorded event", "Count"], [[key, value] for key, value in sorted(r["actualFitAccounting"].items())]),
        table(["Calibration diagnostics accounting", "Count"], [[key, r["calibrationDiagnosticsAccounting"].get(key, 0)]
            for key in ("optimizerStarts", "optimizerSuccesses", "optimizerFailures", "insufficientClassSupport")]),
        f"Applied calibrator fits: {r['appliedCalibratorFits']}. Generic median fallbacks: {r['genericMedianFallbacks']}; generic mode fallbacks: {r['genericModeFallbacks']}. "
        "All ten completed folds and the final model have zero recorded serialization mismatches. Diagnostic optimizer failures/insufficient support remain "
        "explicitly accounted above; a completed run is not a claim that every calibration diagnostic succeeded. Finalization recorded zero model fits, provider calls "
        "and AISP writes, and verified publication checksums/distribution objects. Registration rerun was NO_OP.",
        "## Forward archive and prospective markets",
        f"The archival schedule receipt is `{data['schedule']['status']}` at a {data['schedule']['cadenceHours']}-hour cadence. "
        f"{data['schedule']['operatingRequirement']} {data['schedule']['scope']}. "
        "Captured observation time is the actual capture time, not backdated source retrieval. Missing families stay unavailable. "
        "This creates evidence for future genuine OBSERVED_AS_OF validation; it cannot repair missing historical vintages.",
        f"Prospective market status: `{data['market']['status']}`; supplied timestamped quote snapshots: {data['market']['suppliedQuoteCount']}. "
        "Model-only forecasts remain separate. No untimed price tuning or wagering edge is authorized. The exact export contract is linked below; "
        "quote observation and first-availability must precede the frozen forecast cutoff and kickoff. "
        "This bounded comparison supports eligible two-way moneylines only; spread/total records may be retained but automated line comparison remains unsupported.",
        "## Claude / AISP import instruction",
        "The following is copied from the completed handoff; this report does not assert that an AISP import has happened:",
        "> " + data.get("importInstruction", h["importInstruction"]).replace("\n", "\n> "),
        "## Immutable delivery references",
        table(["Artifact", "Path", "SHA-256"], [[label, link(ref, label), ref["sha256"]] for label, ref in [
            ("Report model card (all saved metrics, intervals and forecast summaries)", card_ref),
            ("Completed study", data["refs"]["study"]),
            ("Original delivery receipt (predecessor audit)" if data.get("admission") else "Delivery receipt", data["refs"]["delivery"]),
            ("Methodology", r["methodology"]), ("44-field inventory", data["refs"]["inventory"]),
            ("Fitted state metadata (no execution)", data["refs"]["fittedState"]),
            ("Fit receipts", data["refs"]["fitReceipts"]), ("Admitted distribution handoff" if data.get("admission") else "Distribution handoff", publication["handoff"]),
            ("Admitted publication manifest" if data.get("admission") else "Publication manifest", publication["manifest"]),
            ("Timestamped quote export contract", market_publication["contract"]),
            ("Forward archive schedule receipt", data["refs"]["forwardArchiveSchedule"]),
            ("Three-game cohort reconciliation", data["refs"]["cohortReconciliation"])]]),
        "## What remains scientifically unproven",
        "Genuine historical publication timing and late-correction magnitude; production superiority; target-starter/rookie, injury, coaching, roster-turnover "
        "or weather uplift; calibrated current cold-start uncertainty; legal score-path/OT dynamics; and betting value against timestamped, settlement-compatible "
        "prices remain unproven. Prospective evidence capture and independent validation are still required. No promotion, champion replacement or wagering activation occurred."])
    if data.get("admission"):
        admission = data["admission"]
        parts.insert(parts.index("## Bottom line") + 1,
            "Partial completion: the fallback-free historical treatment, Development study and forward archive are implemented. "
            "The learned HIERARCHICAL, RESIDUAL and ENSEMBLE current forecasts are BLOCKED and scientifically unusable in the missing-2025 regime "
            "because an uncertainty flag also shifted their score means. Only the separate DYNAMIC baseline is admitted, research-only. "
            "Do not import the original 64-forecast handoff as the current usable package.")
        position = parts.index("## Current 2026 publication") + 1
        parts.insert(position,
            f"Corrective admission: {admission['admittedForecastCount']} DYNAMIC baseline forecasts admitted; "
            f"{admission['withheldForecastCount']} learned event-model forecasts withheld. These are model-specific withholdings, not missing games. "
            "The original forecasts, historical OOF results and fit records remain unchanged for audit; no corrective refit or replacement forecast is claimed. "
            + link(data["refs"]["admission"], "Admission receipt") + ". "
            + link(data["refs"]["diagnostic"], "Exact saved contribution diagnostic") + ".")
        diagnostic = data["diagnostic"]
        parts.insert(position + 1, "Diagnosed limitation: " + diagnostic["interpretation"] + "\n\n"
            + table(["Saved missing-season mean term", "Minimum contribution", "Maximum contribution"],
                [[label, diagnostic["summary"][key][0], diagnostic["summary"][key][1]] for label, key in (
                    ("Home score points", "homeMeanContributionRange"), ("Away score points", "awayMeanContributionRange"),
                    ("Home-minus-away margin points", "marginContributionRange"))])
            + "\n\nThese are saved linear-term contributions, not newly recomputed or corrected forecasts. "
            + link(data["refs"]["correctiveCompletion"], "Corrective completion, market and registration receipt") + ".")
        position = parts.index("## Claude / AISP import instruction") + 1
        parts.insert(position, "Use only the corrective admitted handoff linked below. The predecessor 64-forecast handoff is audit evidence, "
                     "not current import authority. HIERARCHICAL, RESIDUAL and ENSEMBLE are withheld.")
        position = parts.index("## What remains scientifically unproven") + 1
        parts.insert(position, "The learned current challenger is blocked by a diagnosed mean-extrapolation defect, not merely awaiting promotion. "
                     "Future repair and a separately authorized validation are required before those learned current forecasts can be scientifically used.")
    if data.get("publicationVerification"):
        verification = data["publicationVerification"]
        position = parts.index("## Forward archive and prospective markets")
        parts[position:position] = ["### Actual publication rerun verification",
            ("This verifies the preserved original 64-forecast publication before corrective admission, not admission of the blocked models. " if data.get("admission") else "")
            + f"The separate completed rerun receipt records `{verification['status']}`: "
            f"{verification['sameForecastObjectReferenceCount']} of {verification['comparedForecastCount']} forecast object references were identical; "
            f"{verification['newNumericalForecasts']} new numerical forecasts; "
            f"{len(verification['probabilityAndDistributionMismatches'])} probability/distribution mismatches. "
            f"The rerun covered {verification['rerunPublication']['eventCount']} events with {verification['rerunPublication']['skipCount']} skips "
            f"in {verification['runtimeSeconds']:.2f} seconds. Original delivery, handoff, manifest, pointer, frozen model and statistics were unchanged. "
            f"Model fits: {verification['modelFits']}; provider calls: {verification['providerCalls']}; AISP writes: {verification['aispWrites']}. "
            "This verifies publication reuse, not predictive accuracy. " + link(data["refs"]["publicationVerification"], "Exact verification receipt") + "."]
    return "\n\n".join(parts) + "\n"


def immutable(root: Path, name: str, payload: bytes) -> dict:
    digest = hashlib.sha256(payload).hexdigest()
    path = root / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        require(path.read_bytes() == payload, "existing content-addressed report differs")
    return file_record(path)


def apply_corrective_completion(data: dict, path: Path) -> None:
    """Apply only recorded admission, never recompute or change any forecast."""
    ref = file_record(path)
    completion = read_ref(ref)
    require(completion.get("contract") == "NFL_CURRENT_STATE_V2_CORRECTIVE_COMPLETION_RECEIPT", "corrective completion contract")
    require(completion.get("evidenceClass") == "OBSERVED_AS_OF", "corrective observation evidence")
    require(completion.get("originalDelivery") == data["refs"]["delivery"] and completion.get("study") == data["refs"]["study"], "corrective predecessor identities")
    require(completion.get("registrationRerun", {}).get("status") == "NO_OP", "corrective idempotent registration")
    for key, expected in {"noRefits": True, "originalForecastsPreserved": True, "sealed2025Read": False, "aispWrites": 0}.items():
        require(completion.get("verification", {}).get(key) == expected, "corrective verification: " + key)
    admission = read_ref(completion["admission"])
    require(admission.get("contract") == "NFL_CURRENT_STATE_V2_ADMISSION_SUPPLEMENT_V1", "admission contract")
    require(admission.get("originalHandoff") == data["delivery"]["publication"]["handoff"], "admission predecessor handoff")
    publication = completion["publication"]
    require(admission.get("admittedHandoff") == publication["handoff"] and admission.get("manifest") == publication["manifest"], "admitted publication references")
    handoff, manifest = read_ref(publication["handoff"]), read_ref(publication["manifest"])
    require(handoff.get("schemaVersion") == "NFL_CURRENT_STATE_JOINT_DISTRIBUTION_HANDOFF_V2", "admitted handoff contract")
    require(all(handoff.get(k) == v for k, v in AUTHORITY.items()), "admitted research-only authority")
    require(handoff.get("study") == data["refs"]["study"] and manifest.get("handoff") == publication["handoff"], "admitted study/manifest identity")
    require(admission["admittedForecastCount"] == publication["forecastCount"] == handoff["forecastCount"] == len(handoff["forecasts"]), "admitted counts")
    require(admission["withheldForecastCount"] == publication["withheldForecastCount"], "withheld counts")
    require(admission["admittedForecastCount"] + admission["withheldForecastCount"] == data["handoff"]["forecastCount"], "admitted plus withheld equals original")
    original = {item["artifact"]["sha256"]: item for item in data["forecasts"]}
    admitted = []
    for forecast_ref in handoff["forecasts"]:
        require(forecast_ref["sha256"] in original, "admission must reuse an original forecast")
        forecast = original[forecast_ref["sha256"]]
        require(forecast["artifact"] == forecast_ref and forecast["model"]["engineId"] == "NFL_CURRENT_STATE_DYNAMIC_V2", "only exact original DYNAMIC forecasts admitted")
        admitted.append(forecast)
    require(len({f["eventId"] for f in admitted}) == publication["eventCount"] == handoff["forecastEventCount"], "admitted event counts")
    require(handoff["artifactCount"] == len(handoff["artifacts"]) == len(admitted), "admitted distribution count")
    require(bool(admission.get("importInstruction")), "corrective import instruction required")
    diagnostic = read_ref(admission["diagnostic"])
    require(diagnostic.get("contract") == "NFL_CURRENT_STATE_MISSING_SEASON_DIAGNOSIS_V1", "saved diagnosis contract")
    require(diagnostic.get("originalHandoff") == data["delivery"]["publication"]["handoff"]
            and diagnostic.get("study") == data["refs"]["study"], "diagnosis predecessor identity")
    require(diagnostic.get("modelFits") == diagnostic.get("newForecastInference") == diagnostic.get("providerCalls")
            == diagnostic.get("aispWrites") == 0 and diagnostic.get("sealed2025Read") is False, "read-only diagnosis boundaries")
    market_publication = completion["marketComparison"]
    market, market_contract = read_ref(market_publication["comparison"]), read_ref(market_publication["contract"])
    require(market["forecastCount"] == handoff["forecastCount"] and market["eventCount"] == publication["eventCount"], "corrective market coverage")
    require(market["handoff"] == publication["handoff"], "corrective market handoff identity")
    data["predecessorForecasts"] = data["forecasts"]
    data.update(admission=admission, diagnostic=diagnostic, correctiveCompletion=completion,
                admittedPublication=publication, admittedMarketComparison=market_publication,
                handoff=handoff, manifest=manifest, forecasts=admitted, market=market,
                marketContract=market_contract, importInstruction=admission["importInstruction"])
    data["refs"].update(correctiveCompletion=ref, admission=completion["admission"], diagnostic=admission["diagnostic"])


def generate(delivery: Path, study: Path, output: Path | None = None, *, publication_verification: Path | None = None,
             corrective_completion: Path | None = None) -> dict:
    destination = (output or OUTPUT / "reports").resolve()
    require(destination.is_relative_to((OUTPUT / "reports").resolve()), "dedicated report output only")
    data = load_inputs(delivery, study)
    if publication_verification is not None:
        verification_ref = file_record(publication_verification)
        verification = read_ref(verification_ref)
        require(verification.get("contract") == "NFL_CURRENT_STATE_V2_ACTUAL_PUBLICATION_IDEMPOTENCY_V1", "publication verification contract")
        require(verification.get("originalDelivery") == data["refs"]["delivery"], "verification delivery identity")
        require(verification.get("originalHandoff") == data["delivery"]["publication"]["handoff"], "verification handoff identity")
        require(verification.get("status") == "EXACT_REUSE" and verification.get("completedAtUtc"), "completed publication reuse verification")
        require(verification.get("sameForecastObjectReferenceCount") == verification.get("comparedForecastCount")
                == verification.get("originalForecastCount") == data["handoff"]["forecastCount"], "verified reuse counts")
        for key in ("newNumericalForecasts", "modelFits", "providerCalls", "aispWrites"):
            require(verification.get(key) == 0, "publication verification boundary: " + key)
        for key in ("allRerunFileChecksumsValid", "frozenModelAndStatisticsUnchanged", "originalDeliveryHandoffManifestAndPointerUnchanged"):
            require(verification.get(key) is True, "publication verification preservation: " + key)
        require(verification.get("sealed2025Read") is False and verification.get("forecastObjectReferenceMismatches") == []
                and verification.get("probabilityAndDistributionMismatches") == [], "publication verification mismatch/OOT guards")
        data["publicationVerification"] = verification
        data["refs"]["publicationVerification"] = verification_ref
    if corrective_completion is not None:
        apply_corrective_completion(data, corrective_completion)
    # Render/serialize everything before publishing any report: incomplete data
    # must not leave behind a report that looks completed.
    card = build_card(data)
    card["reportGenerator"] = file_record(Path(__file__))
    card_bytes = canonical(card)
    card_sha = hashlib.sha256(card_bytes).hexdigest()
    planned_card = {"path": str(destination / "sha256" / card_sha / "model-card.json"),
                    "sha256": card_sha, "byteCount": len(card_bytes)}
    markdown = build_markdown(data, planned_card).encode("utf-8")
    card_ref = immutable(destination, "model-card.json", card_bytes)
    report_ref = immutable(destination, "research-report.md", markdown)
    manifest = {"contract": "NFL_CURRENT_STATE_V2_REPORT_MANIFEST_V1", **AUTHORITY,
                "evidenceClass": EVIDENCE, "runId": data["result"]["runId"],
                "studyCompletedAtUtc": data["result"]["completedAtUtc"], "inputs": data["refs"],
                "generator": card["reportGenerator"], "files": [report_ref, card_ref],
                "modelsExecuted": 0, "modelsFit": 0, "providerCalls": 0, "aispAccessed": False,
                "sealed2025Read": False, "newEvaluationPerformed": False}
    manifest_ref = immutable(destination, "report-manifest.json", canonical(manifest))
    return {"report": report_ref, "modelCard": card_ref, "manifest": manifest_ref}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, type=Path, help="completed immutable delivery.json")
    parser.add_argument("--study", required=True, type=Path, help="the exact completed result.json in that delivery")
    parser.add_argument("--output", type=Path, help="optional child of the dedicated reports directory")
    parser.add_argument("--publication-verification", type=Path, help="completed actual-publication-idempotency.json receipt")
    parser.add_argument("--corrective-completion", type=Path, help="predecessor-linked completed corrective admission/market/registration receipt")
    args = parser.parse_args()
    try:
        output = generate(args.delivery, args.study, args.output, publication_verification=args.publication_verification,
                          corrective_completion=args.corrective_completion)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Report not generated: {error}\n")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
