"""Freeze one separately authorized private prospective pilot before collection."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sports_cfb_gen1.prospective_collection import now, utc, read, reference, save_json, canonical
from sports_cfb_gen1.prospective_sources import load_discovery

OUT = Path(r"C:\Users\james\asp-model-studio\outputs\cfb-strength-prospective-v1")
HISTORICAL = OUT.parent / "cfb-opponent-adjusted-strength-v1"
DISCOVERY = r"C:\Users\james\asp-model-exchange\cfb-gen1-production-v1\slate-discovery\current.json"
FINALS = r"C:\Users\james\asp-model-exchange\cfb-gen1-production-v1\final-result-evidence\current.json"


def freeze():
    if (OUT / "FROZEN_PROTOCOL.json").exists() or (OUT / "PAIRS.json").exists():
        raise FileExistsError("Protocol already frozen or enrollment exists; do not overwrite")
    candidate = json.loads((OUT / "FROZEN_CANDIDATE.json").read_text())
    manifest = read(candidate["manifest"])
    selection = json.loads((HISTORICAL / "FROZEN_SELECTION.json").read_text())
    decision = json.loads((HISTORICAL / "DECISION.json").read_text())
    assert selection["selectedArm"] == "B" and selection["lambdaPrior"] == 4
    assert decision["disposition"] == "DO_NOT_ADVANCE_UNDER_FROZEN_GATE"
    assert manifest["fixedRecipe"]["arm"] == "B" and manifest["fixedRecipe"]["lambdaPrior"] == 4
    preflight = json.loads((OUT / "COVERAGE_PREFLIGHT.json").read_text())
    metadata = preflight["candidateMetadata"]
    first = min(metadata, key=lambda row: (utc(row["kickoffUtc"]), row["gameId"]))
    frozen = now()
    assert utc(manifest["finalFitCompletedAtUtc"]) < utc(frozen) < utc(first["latestPairCutoffUtc"])
    discovery = load_discovery(DISCOVERY, as_of_utc=frozen)
    bundle = read(discovery["document"]["inputVersion"])
    files = sorted((ROOT / "server/sports_cfb_gen1").glob("*.py"))
    files += [ROOT / "scripts" / name for name in ("run_cfb_strength_prospective_v1.py", "freeze_cfb_strength_protocol_v1.py", "freeze_cfb_strength_candidate_v1.py")]
    protocol = {
        "schema": "CFB_STRENGTH_PRIVATE_PROSPECTIVE_PROTOCOL_V1", "studyId": "CFB_B_LAMBDA4_PRIVATE_PROSPECTIVE_20260918_V1",
        "frozenAtUtc": frozen, "enrollmentStartsAtUtc": frozen, "enrollmentEndsAtUtc": "2026-10-01T00:00:00Z",
        "kickoffBeforeUtc": "2026-10-01T00:00:00Z", "acquisitionExpiresAtUtc": "2026-10-01T00:00:00Z",
        "firstEligibleForecastDefinition": "Earliest kickoff, then numeric game ID, among live canonical eligible forecasts first paired after this freeze and durably committed before T-30; one first valid pair per game, never backdated.",
        "firstScheduledOpportunity": {"gameId": first["gameId"], "away": first["awayTeam"], "home": first["homeTeam"], "kickoffUtc": first["kickoffUtc"], "cutoffUtc": first["latestPairCutoffUtc"]},
        "preexistingCanonicalControlAllowed": "An unchanged currently eligible Gen1 forecast may predate protocol freeze. Its original timestamps are retained; the new paired declaration and B forecast must be created and committed after freeze and before cutoff.",
        "historicalFinding": "POSITIVE_HISTORICAL_MODELING_FINDING_WITH_INSUFFICIENT_EVIDENCE_UNDER_ITS_FROZEN_GATE",
        "historicalDecision": reference(HISTORICAL / "DECISION.json"),
        "historicalSelection": reference(HISTORICAL / "FROZEN_SELECTION.json"),
        "historicalRequirementUnchanged": {"minimumValidationWeekBlocks": 15, "selectedArm": "B", "lambdaPrior": 4, "append2025ToRescueValidation": False},
        "candidateManifest": candidate["manifest"], "candidateArtifact": candidate["candidate"],
        "candidateHistoryCompatibility": reference(OUT / "CANDIDATE_HISTORY_COMPATIBILITY.json"),
        "fixedRecipe": manifest["fixedRecipe"], "canonicalModelBindings": bundle["modelBindings"], "canonicalHistoricalGames": bundle["historicalGames"],
        "codeBindings": [reference(path) for path in files],
        "protocolText": reference(OUT / "PROTOCOL.md"), "coveragePreflight": reference(OUT / "COVERAGE_PREFLIGHT.json"),
        "discoveryPointer": DISCOVERY, "finalEvidencePointer": FINALS,
        "inputPolicy": "Exact original canonical Gen1 feature snapshot; identical first35 features; B adds unchanged two strength features. Current strength-state finals require literal completion captured before that input cutoff, plus the frozen target-UTC-date minus48h kickoff embargo. No final regression/calibration/donor/hyperparameter updates.",
        "populations": {"overall": "All admitted future FBS/FBS regular weeks1-14 common pairs within window", "low_support": "Scheduled week<=3 OR either team has fewer than2 eligible current-season primary games", "zero_prior_support": "Either team has zero eligible2025 primary games"},
        "expectedCoverage": {"timedScheduledGames": len(metadata), "additionalTbdGamesNotYetEligible": len(preflight["coverage"]["withheldTbdOrOtherBlocker"]), "utcDates": len({row["utcKickoffDate"] for row in metadata}), "isoWeeks": len({row["isoCalendarWeek"] for row in metadata}), "lowSupportScheduleBounds": [sum(row["lowSupportUnderAllScheduledPriorGamesCompleting"] for row in metadata), sum(row["lowSupportIfNoFurtherPriorFinalsObserved"] for row in metadata)], "zeroPriorSupportGames": sum(row["zeroPriorSeasonPrimarySupport"] for row in metadata), "countsAreNotGuaranteed": True},
        "adequacy": {"overall": {"minimumGames": 80, "minimumUtcDates": 6, "minimumIsoWeeks": 2}, "low_support": {"minimumGames": 40, "minimumUtcDates": 3, "minimumIsoWeeks": 2}, "zero_prior_support": {"descriptiveOnly": True, "disposition": "INSUFFICIENT_SUBGROUP_EVIDENCE"}},
        "primaryMetric": "jointEnergyScore", "guardrails": {"jointWinnerLogLoss": .005, "jointBinaryBrier": .002, "marginCrps": .05, "totalCrps": .05},
        "otherMetrics": ["scoreAbsoluteError", "marginAbsoluteError", "totalAbsoluteError"],
        "uncertainty": {"bootstrapReplicates": 2000, "seed": 20260918, "primary": "PAIRED_UTC_KICKOFF_DATE_BLOCK_BOOTSTRAP_STRATIFIED_BY_ISO_WEEK", "sensitivity": "PAIRED_GAME_BOOTSTRAP_AND_SEPARATE_WEEK_EFFECTS", "limitations": "Only2footballweeks; UTCdate blocks may split oneUSslate. Diagnostic pilot intervals do not certify season transport or subgroup safety; simulation draws are not observations."},
        "pilotSignal": {"minimumEnergyImprovement": .10, "requireEnergyUpper95BelowZero": True, "lowSupportMaximumMeanDegradation": .05, "lowSupportMaximumUpper95": .15, "maximumAuthority": "PROMISING_PROSPECTIVE_PILOT_ONLY_NO_PROMOTION_OR_BROAD_SHADOW_AUTHORITY"},
        "assessmentSchedule": [{"id": "interim-20260922", "atUtc": "2026-09-22T16:00:00Z", "kind": "interim"}, {"id": "final-20261001", "atUtc": "2026-10-01T12:00:00Z", "kind": "final"}, {"id": "closure-20261002", "atUtc": "2026-10-02T12:00:00Z", "kind": "closure"}],
        "interimHarmStop": {"minimumGames": 30, "energyDegradation": .5, "marginCrpsDegradation": .5},
        "stopping": "No positive early stop or tuning. Stop enrollment at expiry, on fixed interim substantial harm rule, or fail closed on identity/code/cutoff failures. Missing subgroups remain insufficient; no extension without new authorization.",
        "outcomePolicy": "Both predictions scored against the same hash-bound admitted source-final row revision in private research only. Literal completed=true, matching identities/orientation/schedule, actual capture after prediction and kickoff. Preserve corrections; do not assert AISP canonical admission or settlement. Assess using only revisions actually observed by each scheduled logical cutoff; finals source acquisition must precede authorization expiry.",
        "execution": "Private idempotent hourly read-only local collector; distinct local lock and output tree; no network, duplicate acquisition owner, publication into production discovery, or production scheduler edits.",
        "productionChampion": "CFB_GEN1_RIDGE_A100_PAIRED_RESIDUAL_V1", "productionChanges": False,
        "authorizedAcquisitionPlanSha256": "3fead29fb55a23eb91a1d7051a762a3f1786b87421d2eff8c009e55e34975a60",
        "authorizedOwnerDeployment": "83e8bb75a410c23bd72029a5d341d89c5d95a7d26f3a7e329e07de24647f8a14",
        "newProviderRequests": 0, "paidDataSpend": 0, "consumerAuthority": False, "wageringAuthority": False,
        "separateUserAuthorization": "James explicitly authorized this separate private prospective implementation and collection after the historical study; no historical advancement decision is changed."}
    bound = save_json(OUT, protocol, "protocol.json")
    with (OUT / "FROZEN_PROTOCOL.json").open("xb") as handle:
        handle.write(canonical({"schema": "CFB_STRENGTH_PROTOCOL_POINTER_V1", "protocol": bound, "frozenAtUtc": frozen}))
    print(json.dumps({"protocol": bound, "frozenAtUtc": frozen}, indent=2))


if __name__ == "__main__":
    freeze()
