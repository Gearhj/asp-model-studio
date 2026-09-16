"""Report a completed repair and delivery using saved JSON only; never fit/evaluate.

Model files are checksum-verified as opaque bytes, never deserialized. The report
is deliberately gated on the completed delivery and written content-addressed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1"
OLD = ROOT / "outputs/nfl-current-state-cold-start-v2/reconstructed-study-v1"
EVIDENCE = "RETROSPECTIVE_RECONSTRUCTED_AS_OF"
COMPONENTS = ("DYNAMIC", "HIERARCHICAL", "RESIDUAL", "ENSEMBLE")
GROUPS = ("WEEK_1", "WEEKS_1_4", "FULL_SEASON")
LABELS = {"WEEK_1": "Week 1", "WEEKS_1_4": "Weeks 1–4", "FULL_SEASON": "Full"}
SHORT = {"DYNAMIC": "DYN", "HIERARCHICAL": "HIER", "RESIDUAL": "RES", "ENSEMBLE": "ENS", "M1": "M1"}
AUTHORITY = {"status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
             "wageringAuthority": False, "executionAllowedInAISP": False}


def require(condition, message):
    if not condition:
        raise ValueError("INCOMPLETE_OR_INCONSISTENT_REPORT_INPUT: " + message)


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def record(path):
    path = Path(path).resolve(strict=True)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path), "sha256": digest.hexdigest(), "byteCount": path.stat().st_size}


def checked(ref):
    path = Path(ref["path"]).resolve(strict=True)
    require(path.is_relative_to((ROOT / "outputs").resolve()), "only Model Studio saved outputs may be inspected")
    require(path.suffix in (".json", ".jsonl", ".joblib"), "no source or feature payload access")
    actual = record(path)
    require(all(actual[key] == ref[key] for key in ("sha256", "byteCount")), "checksum/size: " + str(path))
    return path


def read(ref):
    path = checked(ref)
    require(path.suffix == ".json", "JSON only; never deserialize an estimator")
    def reject(value):
        raise ValueError("Nonfinite JSON value: " + value)
    return json.loads(path.read_bytes(), parse_constant=reject)


def artifact(result, path):
    matches = [ref for ref in result["artifacts"] if Path(ref["path"]).resolve() == Path(path).resolve()]
    require(len(matches) == 1, "exactly one declared artifact: " + str(path))
    return matches[0]


def finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def validate_metric(metric, games=None):
    require(metric.get("evidenceClass") == EVIDENCE, "metric evidence")
    require(isinstance(metric.get("games"), int) and metric["games"] > 0, "nonempty evaluation cohort")
    if games is not None:
        require(metric["games"] == games, "matched metric cohort")
    for name in ("multiclassLogLoss", "multiclassBrier", "homeWinEce", "homeScoreMae", "awayScoreMae", "marginMae", "totalMae"):
        require(finite(metric.get(name)), "finite metric: " + name)
    for side in ("home", "away", "margin", "total"):
        require(finite(metric.get("signedBiasPredictedMinusActual", {}).get(side)), "signed bias: " + side)
    require(set(metric.get("calibration", {})) == {"home", "away", "tie"}, "all class calibration diagnostics")
    for item in metric["calibration"].values():
        require(item.get("use") == "DIAGNOSTIC_ONLY_NOT_APPLIED_TO_FORECAST", "descriptive calibration only")


def load_inputs(study_path, delivery_path):
    study_ref, delivery_ref = record(study_path), record(delivery_path)
    require(Path(study_ref["path"]).is_relative_to((OUTPUT / "runs").resolve()), "new repair run only")
    require(Path(delivery_ref["path"]).is_relative_to(OUTPUT.resolve()), "new repair delivery only")
    result, delivery = read(study_ref), read(delivery_ref)
    require(result.get("repairContract") == "NFL_UNCERTAINTY_MEAN_SEPARATION_REPAIR_RESULT_V1", "repair result contract")
    require(result.get("contract") == "NFL_CURRENT_STATE_RECONSTRUCTED_STUDY_RESULT_V2", "study contract")
    require(result.get("completedAtUtc") and result.get("runId") == Path(study_ref["path"]).parent.name, "completed run identity")
    require(delivery.get("contract") == "NFL_UNCERTAINTY_REPAIR_DELIVERY_RECEIPT_V1", "completed repair delivery contract")
    require(delivery.get("study") == study_ref, "delivery/study exact identity")
    require(all(result.get(key) == value for key, value in AUTHORITY.items()), "research-only authority")
    require(result.get("evidenceClass") == EVIDENCE and result.get("finalOotAccessed") is False, "reconstructed evidence / sealed OOT")
    for name in ("genericMedianFallbacks", "genericModeFallbacks", "currentPublicationCalibratorFits"):
        require(result.get(name) == 0, name)
    require(result.get("currentRosterDepthNumericallyIncorporated") is False, "historical-prior classification")
    require(result.get("predecessorArtifactsPreserved") is True, "predecessor preservation")
    require(result.get("developmentGames") == 6988 and result.get("validationGamesPerLag") == 1408, "frozen cohort counts")
    require(len(result.get("fittedModels", [])) == 10 and len(result.get("foldReports", [])) == 40, "complete outer folds")
    declaration, protocol = read(result["declaration"]), read(result["methodology"])
    require(declaration.get("runId") == result["runId"] and declaration.get("protocol") == result["methodology"], "declaration identity")
    require(len(declaration["meanInputNames"]) == 52 and len(declaration["uncertaintyOnlyNames"]) == 6
            and not set(declaration["meanInputNames"]) & set(declaration["uncertaintyOnlyNames"]), "52 mean / 6 uncertainty roles")
    accounting = result["actualFitAccounting"]
    for name, budget in (("ESTIMATOR", "meanFitBudget"), ("UNCERTAINTY", "varianceFitBudget"),
                         ("EVALUATION_CALIBRATOR", "evaluationCalibratorFitBudget")):
        require(accounting.get(name + "_FIT_START") == accounting.get(name + "_FIT_COMPLETE") == declaration[budget], "complete fit accounting: " + name)
    require(accounting.get("FOLD_COMPLETE") == 10 and accounting.get("FINAL_MODEL_RELOAD_VERIFIED") == 1, "all systems verified")
    require(result["appliedEvaluationCalibratorFits"] == accounting["EVALUATION_CALIBRATOR_FIT_COMPLETE"], "applied calibrator count")
    require(all(declaration.get(key) == 0 for key in ("newRetentionSearches", "m1MeanFits", "dynamicMeanFits")), "bounded reuse")
    run = Path(study_ref["path"]).parent
    ledger_ref = artifact(result, run / "fit-receipts.jsonl")
    events = [json.loads(line) for line in checked(ledger_ref).read_text().splitlines() if line.strip()]
    require(dict(Counter(item["event"] for item in events)) == accounting, "saved fit ledger reconciliation")
    require(all(item.get("mismatchCount") == 0 for item in events if item["event"] == "FINAL_MODEL_RELOAD_VERIFIED"), "final reload")
    models, verifications, calibration = [], [], []
    require({(ref["lagHours"], ref["validationSeason"]) for ref in result["fittedModels"]}
            == {(lag, year) for lag in (48, 72) for year in range(2020, 2025)}, "exact lag/season systems")
    for ref in [*result["fittedModels"], result["finalModel"]]:
        checked(ref)
        models.append({key: ref[key] for key in ("path", "sha256", "byteCount")})
    for ref in result["fittedModels"]:
        verification = read(artifact(result, Path(ref["path"]).parent / "verification.json"))
        require(all(verification.get(key) == 0 for key in ("uncertaintyMeanMismatches", "unchangedDynamicMeanMismatches", "reloadMismatches")), "fold invariance/reload")
        require(0 <= verification["week1TrainCurrentFeatureParityMaximumAbsoluteDifference"] <= 1e-10, "train/current parity")
        verifications.append(verification)
    final_state_ref = artifact(result, Path(result["finalModel"]["path"]).parent / "fitted-state.json")
    final_state = read(final_state_ref)
    require(final_state["meanInputNames"] == declaration["meanInputNames"]
            and final_state["uncertaintyOnlyNames"] == declaration["uncertaintyOnlyNames"], "fitted field roles")
    for lag in (48, 72):
        for name in COMPONENTS:
            ref = artifact(result, run / "evaluation-calibration" / f"{name}-lag{lag}" / "receipts.json")
            receipt = read(ref)
            require(receipt.get("C") == 1 and receipt.get("currentPublicationApplied") is False, "fixed evaluation calibration")
            for fold in receipt["folds"]:
                if "artifact" in fold:
                    checked(fold["artifact"])
                    models.append(fold["artifact"])
                    require(fold.get("reloadMismatch") == 0 and max(fold["trainingSeasons"]) < fold["validationSeason"], "chronological calibration")
            calibration.append({"component": name, "lagHours": lag, "receipt": receipt, "ref": ref})
    leaders = {row["pipelineId"]: row for row in result["leaderboard"]}
    require(set(leaders) == {f"{name}_LAG{lag}" for name in COMPONENTS for lag in (48, 72)}, "complete candidate matrix")
    baseline = result["legacyComparators"]["M1"]
    for group in GROUPS:
        n = baseline["raw"][group]["games"]
        for metric in [baseline["raw"][group], baseline["equivalentCalibrated"][group],
                       *[row[key][group] for row in leaders.values() for key in ("subgroups", "equivalentCalibratedSubgroups")]]:
            validate_metric(metric, n)
    publication = delivery["publication"]
    handoff, manifest = read(publication["handoff"]), read(publication["manifest"])
    require(handoff.get("study") == study_ref and handoff.get("model") == result["finalModel"], "publication final model/study")
    require(handoff.get("publicationDisposition") == "REPAIRED_HISTORICAL_PRIOR_BASELINE"
            and handoff.get("forecastType") == "HISTORICAL_PRIOR_BASELINE", "repaired prior-only publication")
    require(manifest.get("handoff") == publication["handoff"], "publication manifest linkage")
    for key in ("forecastCount",):
        require(publication[key] == handoff[key] == manifest[key], "publication counts")
    require(publication["eventCount"] == handoff["forecastEventCount"] == manifest["eventCount"], "published event counts")
    require(handoff["forecastCount"] == len(handoff["forecasts"]) and handoff["skips"] == publication["skips"], "forecasts and skips")
    require(all(handoff.get(key) == 0 for key in ("providerCalls", "modelFits", "aispWrites"))
            and handoff.get("sealed2025Read") is False, "publication boundaries")
    require(delivery["registrationRerun"].get("status") == "NO_OP", "registration idempotency")
    verification = delivery["verification"]
    expected = {"allStudyAndPublicationChecksumsValid": True, "allScoreDistributionObjectsValid": True,
                "finalModelUncertaintyMeanMismatchCount": 0, "invariantFixtureIsNewForecastOrPerformanceEvidence": False,
                "reproductionMismatchCount": 0, "modelFitsDuringFinalization": 0, "providerCalls": 0, "aispWrites": 0,
                "finalOotRead": False, "mlbChanges": False, "m1Retained": True, "originalArtifactsAndWithheldOutputsPreserved": True}
    require(all(verification.get(key) == value for key, value in expected.items()), "completed finalization verification")
    require(verification["pregameAndOrientationCheckedForecasts"] == handoff["forecastCount"]
            and 0 <= verification["maximumPublishedMeanQuantizationError"] <= .5/5000+1e-12, "publication orientation/mean checks")
    rerun = verification["publicationRerun"]
    read(rerun["handoff"])
    read(rerun["manifest"])
    require(rerun["reused"] == rerun["forecastCount"] == verification["commonRerunForecasts"], "actual-clock exact common-object reuse")
    require(delivery["marketComparison"]["status"] == "NOT_RUN_IN_BOUNDED_UNCERTAINTY_REPAIR", "no expanded market study")
    tests = read(delivery["tests"]["receipt"])
    require(tests.get("contract") == "NFL_UNCERTAINTY_REPAIR_FOCUSED_TEST_RECEIPT_V1"
            and tests.get("passed") == sum(row["passed"] for row in tests["checks"]), "focused check receipt")
    require(all(delivery["tests"].get(key) == value for key, value in tests.items()), "embedded check receipt identity")
    read(delivery["previousCurrentPointer"])
    forecasts = [read(ref) for ref in handoff["forecasts"]]
    for forecast in forecasts:
        require(forecast.get("currentContextNumericallyIncorporated") is False
                and forecast.get("currentRosterDepthNumericallyIncorporated") is False, "no current numerical context")
        require(forecast.get("model", {}).get("modelArtifact") == result["finalModel"], "forecast model linkage")
    diagnostic_ref = delivery["diagnostic"]
    archive_ref = delivery["archiveOperatingRequirements"]
    diagnostic, archive = read(diagnostic_ref), read(archive_ref)
    require(diagnostic.get("contract") == "NFL_UNCERTAINTY_REPAIR_PREDECESSOR_IMPACT_TRACE_V1"
            and diagnostic.get("sourceStudy") == result["predecessor"], "frozen predecessor impact trace")
    require(diagnostic.get("allProtectedInputsUnchanged") is True, "diagnostic preservation")
    require(archive.get("schemaVersion") == "NFL_FORWARD_ARCHIVE_AUTOMATION_OPERATING_REQUIREMENTS_V1", "archive operating receipt")
    reconciliation_ref = record(OLD / "cohort-reconciliation.json")
    reconciliation = read(reconciliation_ref)
    require(reconciliation.get("validation2020Through2024MembershipChanged") is False, "cohort reconciliation")
    refs = {"study": study_ref, "delivery": delivery_ref, "declaration": result["declaration"],
            "protocol": result["methodology"], "impactTrace": diagnostic_ref, "archiveOperatingRequirements": archive_ref,
            "cohortReconciliation": reconciliation_ref, "finalState": final_state_ref,
            "handoff": publication["handoff"], "publicationManifest": publication["manifest"], "fitReceipts": ledger_ref,
            "tests": delivery["tests"]["receipt"], "previousCurrentPointer": delivery["previousCurrentPointer"]}
    return dict(result=result, delivery=delivery, declaration=declaration, protocol=protocol, leaders=leaders,
                handoff=handoff, forecasts=forecasts, diagnostic=diagnostic, archive=archive, finalState=final_state,
                calibration=calibration, verifications=verifications, reconciliation=reconciliation, refs=refs,
                verifiedModels=models)


def f(value, digits=4):
    return f"{value:.{digits}f}" if finite(value) else "unavailable"


def cell(value):
    return str(value).replace("|", "/").replace("\n", " ")


def table(headers, rows):
    return "\n".join(["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |",
                      *["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]])


def link(label, ref):
    return f"[{label}](<{Path(ref['path']).as_posix()}>)"


def interval(item):
    return f"{f(item['pairedMean'])} [{f(item['interval95'][0])}, {f(item['interval95'][1])}]"


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def build_markdown(data):
    result, delivery, leaders = data["result"], data["delivery"], data["leaders"]
    primary = result["pairedComparisons"]["RESIDUAL_LAG48"]
    raw, cal = primary["rawVsM1Raw"]["FULL_SEASON"], primary["calibratedVsM1Calibrated"]["FULL_SEASON"]
    conclusion = lambda item: "lower" if item["pairedMean"] < 0 else "higher" if item["pairedMean"] > 0 else "equal"
    parts = ["# NFL uncertainty/mean-separation repair — research report",
        f"Completed study: {result['completedAtUtc']}. Run `{result['runId']}`. Research shadow; not promoted; no wagering or AISP execution authority.",
        "## Scientific conclusion",
        f"The fixed primary RESIDUAL/48h has **{conclusion(raw)} raw log loss than saved M1** over the matched {raw['events']:,} Development games: ΔLL {interval(raw)}. "
        f"Under the equivalent chronological calibration recipe, its log loss is **{conclusion(cal)} than calibrated M1**: ΔLL {interval(cal)}. "
        "These exploratory season/week-block intervals do not establish prospective superiority. No raw/calibrated winner is selected. "
        "Correctness repair does not imply better prediction or coverage. M1 and all superseded/withheld artifacts remain retained.",
        "## What was wrong, and where it mattered",
        "Six uncertainty-only fields entered predecessor score means: home/away passer posterior SD, prior-season gap and missing-season count. "
        "Replay of saved sufficient statistics identified `2002_01_DAL_HOU` (2002-09-08): HOU had no eligible prior team rows. "
        "The source-start fallback `season − 1999` produced gap 3 and missing-count 2. This is an unseen-team counter, **not verification that HOU had two missing historical seasons**. "
        "Each frozen training system contained this one nonzero home count; the final training set had 6,729 zeros and one value 2. Away counts were all zero."]
    diagnosis = data["diagnostic"]["currentMissingSeasonDiagnosis"]
    parts += [f"For each of the 16 original current events, home missing-count 1 became a standardized value near 41.009. Its saved linear term contributed "
        f"{f(diagnosis['homeMeanContributionRange'][0], 6)} home points and {f(diagnosis['awayMeanContributionRange'][0], 6)} away points, "
        f"or **{f(diagnosis['marginContributionRange'][0], 6)} home-margin points**. "
        "All ten validation systems were affected: missing counts were zero but centering created a constant term; "
        "passer SD was nonzero throughout, season gaps varied, and HGB split on uncertainty-only fields. "
        "Their combined linear terms ranged approximately −3.985 to +4.353 historical margin points. Attribution is not causal refit impact: correlated coefficients, residuals and mixtures change.",
        "DYNAMIC means never used these fields. Its distributions still used the old variance heuristic: posterior variance, arbitrary `1 + gap²` multiplication and residual-reference adjustment. "
        "Historical validation’s gap multiplier was always 1, unlike the current regime. The repair reuses DYNAMIC means, replaces uncertainty laws and refits ten learned outer systems plus the final system. "
        + link("Exact historical/current impact trace", data["refs"]["impactTrace"]) + ".",
        "## Treatment, fitting and limits",
        "The 52 mean inputs are 44 home/away reconstructed football-rate/score estimates plus each side’s historical passer EPA mean, effective passer exposure, prior-game count and current-game count. "
        "Six uncertainty-only fields and rate posterior SD metadata are excluded from means. Measured exposure/continuity remain legitimate state inputs. "
        "This does not assert that deleting actual historical observations leaves reconstructed ability estimates unchanged. "
        "No generic median/mode replacement is introduced; unknown evidence differs from observed zero. "
        "The passer layer is pass-attempt-weighted prior `passer_player_id` usage, not independently verified historical QB position or a known target starter.",
        "DYNAMIC is scoring-only; HIERARCHICAL uses the 52-field Ridge correction and RESIDUAL adds fixed small HGB corrections. "
        "Retention/architecture/seeds are inherited. Ensemble weights/diversity use earlier OOF only, otherwise hierarchical warmup.",
        "Each component’s variance law is a nonnegative least-squares regression of inner chronological holdout squared score error on an intercept, score posterior variance, passer posterior variance and missing-age count. "
        "Home/away share coefficients. Fixed previous-season-observation dropout supplies one paired case with equal normal/dropout weights, not independent new games. "
        "The gap coefficient requires independent design rank, not merely positive gap cases. Only observations are dropped; inner prior parameters and mean-model parameters stay frozen. "
        "This does not validate missing training data, historical vintages or two-year estimator staleness.",
        "Paired centered inner residuals supply the joint shape. Nonnegative projection and balanced integer rounding preserve means within 0.5/draw count. "
        "Latent and constrained-draw variance are distinct. This is not a legal scoring-path engine or full Bayesian parameter posterior; uncertainty is not presumed calibrated.",
        "## Evidence and matched evaluation",
        f"The source cohort has {result['developmentGames']:,} games from 1999–2024, with 1999 source-only warmup (258 games) and training targets from 2000. "
        f"Outer validation is 2020–24, {result['validationGamesPerLag']:,} identical games at each lag. "
        "The three schedule-derived semantic rows absent from eligible reconstructed play evidence are "
        + ", ".join(f"`{row['gameId']}`" for row in data["reconciliation"]["missingFromReconstructedPbpCohort"]) + ". "
        "They are not manufactured into exposure evidence; 2020–24 membership is unchanged.",
        "Historical estimates are `RETROSPECTIVE_RECONSTRUCTED_AS_OF`, not archived point-in-time vintages. Availability uses the next-day noon New York conservative completion upper bound plus 48/72h and strict whole-slate cutoffs, not an observed release time. "
        "Late corrections remain unidentified; 72h sensitivity does not estimate them. Sealed 2025-season payloads and target starter/injury/weather/current numeric roster inputs are excluded.",
        "Saved M1 shares outcomes, not the 48/72h retraining or availability recipe. "
        "Compare raw/raw and calibrated/calibrated. Fixed multinomial logit on log probabilities (C=1, earlier OOF seasons only) is not selected after outcomes. "
        "No earlier OOF or fewer than three classes means labeled raw warmup. Calibration changes outcome probabilities only—not scores, bias, MAE or intervals—and is not applied to current publication."]
    warmup = sorted({fold["validationSeason"] for row in data["calibration"] for fold in row["receipt"]["folds"] if fold.get("status") == "RAW_INSUFFICIENT_EARLIER_OOF"})
    parts += [f"Saved repaired calibration warmup seasons: {', '.join(map(str, warmup)) or 'none'}. "
              f"Completed evaluation calibrator fits: {result['appliedEvaluationCalibratorFits']}; current-publication calibrator fits: {result['currentPublicationCalibratorFits']}.",
        "## Primary 48h results",
        "DYN/HIER/RES/ENS are repaired components. `raw` is uncalibrated; `cal` uses earlier OOF. Lower LL/Brier is better; Brier sums three classes. "
        "Bias = prediction minus actual; positive margin favors home. Slash-separated metrics are **home / away / margin / total**; Full is the 2020–24 regular-season and postseason cohort, not regular-season games alone."]
    rows, calibration_rows = [], []
    for group in GROUPS:
        for name in ("M1", *COMPONENTS):
            source = result["legacyComparators"]["M1"] if name == "M1" else leaders[name + "_LAG48"]
            for mode, key in (("raw", "raw" if name == "M1" else "subgroups"), ("cal", "equivalentCalibrated" if name == "M1" else "equivalentCalibratedSubgroups")):
                metric = source[key][group]
                bias = metric["signedBiasPredictedMinusActual"]
                rows.append([SHORT[name] + " " + mode, LABELS[group], metric["games"], f(metric["multiclassLogLoss"]), f(metric["multiclassBrier"]),
                             " / ".join(f(bias[side], 2) for side in ("home", "away", "margin", "total")),
                             " / ".join(f(metric[field], 2) for field in ("homeScoreMae", "awayScoreMae", "marginMae", "totalMae"))])
                diagnostic = metric["calibration"]["home"]
                distribution = metric.get("distribution", {})
                coverage = " / ".join(f(distribution.get(side, {}).get("coverage90"), 3) for side in ("home", "away", "margin", "total")) if distribution else "unavailable"
                calibration_rows.append([SHORT[name] + " " + mode, LABELS[group], coverage, f(metric["homeWinEce"]),
                    f(diagnostic.get("meanPredicted")), f(diagnostic.get("observedRate")), f(diagnostic.get("intercept")), f(diagnostic.get("slope"))])
    parts += [table(["Series", "Cohort", "N", "LL", "Brier", "Bias H/A/M/T", "MAE H/A/M/T"], rows),
        "### Coverage and home-outcome calibration",
        "Coverage is observed inclusion in the raw 90% interval, not a calibration claim. Unavailable M1 intervals stay unavailable. "
        "Home intercept/slope are descriptive one-vs-rest diagnostics (ideal 0/1); unsupported/failed estimates remain unavailable. Home p/rate compare mean prediction with observed wins; ties stay separate.",
        table(["Series", "Cohort", "90% coverage H/A/M/T", "Home ECE", "Home p", "Home rate", "Intercept", "Slope"], calibration_rows),
        "### Matched primary loss differences",
        "ΔLL = RES/48h minus reference; negative favors RES. The 2,000 whole-season/week block resamples are exploratory; crossing zero does not establish a difference. Complete comparisons remain in the result JSON."]
    comparison_rows = []
    for key, label in (("rawVsM1Raw", "raw − M1 raw"), ("calibratedVsM1Calibrated", "cal − M1 cal"),
                       ("rawVsRepairedDynamic", "raw − DYN raw"), ("calibratedVsRepairedDynamicCalibrated", "cal − DYN cal")):
        for group in GROUPS:
            item = primary[key][group]
            comparison_rows.append([label, LABELS[group], item["events"], item["seasonWeekBlocks"], interval(item)])
    parts += [table(["Comparison", "Cohort", "N", "Blocks", "ΔLL [95% interval]"], comparison_rows), "## 72h sensitivity"]
    sensitivity = []
    for name in COMPONENTS:
        item = result["lag72Minus48"][name]
        sensitivity.append([SHORT[name], f(leaders[name + "_LAG48"]["multiclassLogLoss"]), f(leaders[name + "_LAG72"]["multiclassLogLoss"]),
            interval(item["lossComparisons"]["FULL_SEASON"]), f"{item['probabilityChangedGames']}/{item['matchedGames']}", f(item["meanAbsoluteClassProbabilityChange"], 6)])
    parts += [table(["Component", "48h raw LL", "72h raw LL", "72h − 48h ΔLL [95% interval]", "Changed games", "Mean absolute Δp"], sensitivity),
        "This is the fixed availability sensitivity, not selection. Complete 72h early-season raw/cal metrics remain in the result.",
        "## Final uncertainty parameters versus actual coverage",
        "Parameters below are final through-2024 estimates, not the outer-fold coverage measured above. Order: intercept / score posterior variance / passer posterior variance / missing-age count. Nonnegative does not mean calibrated."]
    variance_rows = []
    for name, law in data["finalState"]["varianceLaws"].items():
        variance_rows.append([SHORT[name], " / ".join(f(value, 6) for value in law["coefficients"]), law["normalGames"], law["dropoutCases"],
            law["varianceDesignRank"], "design estimable; fitted " + f(law["coefficients"][3], 6) if law["gapIdentifiable"] else "excluded: not independently identified"])
    parts += [table(["Component", "NNLS coefficients", "Normal games", "Dropout cases", "Rank", "Explicit gap"], variance_rows),
        f"Final ensemble residual weight: {f(result['finalEnsembleResidualWeight'], 6)}; disposition: `{result['finalEnsembleDisposition'].get('status', 'see saved receipt')}`. "
        "Weak dropout support or poor coverage is not resolved by calling variance a posterior.",
        "## Completion, verification and current delivery"]
    accounting = result["actualFitAccounting"]
    parts += [f"Actual completed mean-estimator fits: {accounting['ESTIMATOR_FIT_COMPLETE']}; separate variance fits: {accounting['UNCERTAINTY_FIT_COMPLETE']}; "
        f"separate applied evaluation-calibrator fits: {accounting['EVALUATION_CALIBRATOR_FIT_COMPLETE']}. "
        f"Completed outer systems: {accounting['FOLD_COMPLETE']}; final model reload verifications: {accounting['FINAL_MODEL_RELOAD_VERIFIED']}. "
        f"Study runtime: {f(result['runtimeSeconds'], 2)} seconds. Diagnostic calibration accounting: `{compact(result['calibrationDiagnosticsAccounting'])}`. "
        "Starts/completions reconcile with saved receipts; eleven system and all evaluation-calibrator hashes were checked without loading models.",
        "Every outer verification records zero uncertainty-to-mean changes, zero DYNAMIC-mean changes and zero reload differences. "
        f"Largest Week-1 training/current feature discrepancy: {max(row['week1TrainCurrentFeatureParityMaximumAbsoluteDifference'] for row in data['verifications']):.3g}. "
        "These are fixed fixtures, not an exhaustive proof.",
        delivery["tests"]["summary"] + " Distinct model/study/publication/UI-registration counts: "
        + " / ".join(str(row["passed"]) for row in delivery["tests"]["checks"]) + ". "
        + link("Executed commands and scope", data["refs"]["tests"]) + "; no full repository suite or new evaluation by this report."]
    handoff = data["handoff"]
    reasons = Counter(row["reason"] for row in handoff["skips"])
    parts += [f"The completed repaired handoff contains {handoff['forecastCount']} forecasts for {handoff['forecastEventCount']} events; "
        f"{len(handoff['skips'])} saved skip records: `{compact(dict(reasons))}`. "
        f"Published at {handoff['publishedAtUtc']}, using the actual execution clock and {handoff['drawsPerForecast']:,} score draws per forecast. "
        "At/after-kickoff events are skipped, never backdated. Inputs end with the 2024 season; 2025 is sealed. "
        "Roster/depth context has **NONE numerically incorporated**; no confirmed target starter is claimed. "
        "Classification: `HISTORICAL_PRIOR_BASELINE`, not fully current roster-informed forecasts. Future numeric 2026 incorporation is not established.",
        f"Actual final-model mean/distribution-mean perturbation mismatches: {delivery['verification']['finalModelUncertaintyMeanMismatchCount']}; "
        f"pregame/orientation-checked forecasts: {delivery['verification']['pregameAndOrientationCheckedForecasts']}; "
        f"maximum published mean quantization error: {f(delivery['verification']['maximumPublishedMeanQuantizationError'], 8)} points. "
        f"Fresh-clock rerun reused {delivery['verification']['commonRerunForecasts']} common objects with {delivery['verification']['reproductionMismatchCount']} mismatches. "
        f"Registration rerun: `{delivery['registrationRerun']['status']}`. The former CURRENT pointer is preserved. "
        "Market comparison: `NOT_RUN_IN_BOUNDED_UNCERTAINTY_REPAIR` (no new quote/decision-study authority). No M1 promotion, old-artifact deletion, wagering action or AISP write.",
        "Exact saved import instruction for the separately versioned research objects:",
        "> " + handoff["importInstruction"],
        "## Forward archive: actual owner and persistence"]
    automation = data["archive"]["automation"]
    config = automation["configuration"]
    parts += [f"Observed local configuration: `{automation['id']}`, status `{automation['status']}`, cadence {automation['cadence'].lower()}, "
        f"owner `{config['filesystemOwner']}`, shell identity `{automation['currentShellAccount']}`. "
        f"Configuration path: `{config['path']}`; SHA-256 `{config['sha256']}`. "
        f"Command: `{automation['configuredCommand']}` in `{automation['workingDirectory']}`. "
        "Observed heartbeat ownership is not a dedicated service/run-as guarantee.",
        "Persistence after closure/reboot is a filesystem inference, not a reboot test. No archiving occurs with the app closed or computer off. "
        "Reopen the same profile, preserve project/interpreter access and verify active status after reboot; startup/catch-up are not guaranteed. "
        "This matches the [official scheduled-task operating requirement](https://learn.chatgpt.com/docs/automations?surface=app). "
        "Only existing authorized local snapshots are archived—no provider refresh or backdating. Archival begins now, not retrospectively.",
        "## Complete evidence and handoff",
        "; ".join(link(label, data["refs"][key]) for key, label in (("study", "Complete numerical results"), ("delivery", "Delivery and test receipt"),
            ("protocol", "Frozen repair protocol"), ("finalState", "Final fitted metadata"), ("handoff", "Exact repaired import handoff"),
            ("archiveOperatingRequirements", "Archive operating receipt"))) + ". "
        "Manifest: exact input/model hashes and generator identity. Rendering makes no model/source reads, fits, evaluations, forecasts or provider calls (models are hashed as opaque bytes only).",
        "This bounded repair ends with the saved scientific result, even if it loses. "
        "**Stop NFL expansion; retain M1 and prior/withheld artifacts, and return to MLB only under the next authorized task.**"]
    return "\n\n".join(parts) + "\n"


def immutable(destination, name, payload):
    digest = hashlib.sha256(payload).hexdigest()
    path = destination / "sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError:
        require(path.read_bytes() == payload, "immutable report collision")
    return {"path": str(path), "sha256": digest, "byteCount": len(payload)}


def generate(study, delivery, output=None):
    destination = (output or OUTPUT / "reports").resolve()
    require(destination.is_relative_to((OUTPUT / "reports").resolve()), "dedicated new report directory")
    data = load_inputs(study, delivery)
    payload = build_markdown(data).encode("utf-8")
    require(10000 <= len(payload) <= 22000, "bounded technical report length")
    manifest = {"contract": "NFL_UNCERTAINTY_REPAIR_REPORT_MANIFEST_V1", **AUTHORITY,
        "evidenceClass": EVIDENCE, "runId": data["result"]["runId"],
        "studyCompletedAtUtc": data["result"]["completedAtUtc"], "inputs": data["refs"],
        "generator": record(Path(__file__)), "verifiedModelFiles": data["verifiedModels"],
        "modelsDeserialized": 0, "modelFits": 0, "newEvaluationPerformed": False,
        "sourcePayloadReads": 0, "sealed2025Read": False, "newForecastInference": 0, "providerCalls": 0, "aispWrites": 0}
    # Validate all metadata and render before publishing a completed-looking report.
    canonical(manifest)
    report_ref = immutable(destination, "research-report.md", payload)
    manifest["report"] = report_ref
    manifest_ref = immutable(destination, "report-manifest.json", canonical(manifest))
    return {"report": report_ref, "manifest": manifest_ref}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--delivery", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = generate(args.study, args.delivery, args.output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(2, f"Report not generated: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
