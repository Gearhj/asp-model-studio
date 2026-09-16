"""Outcome-free later-cohort PA gate; never reads targets or predictions."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd
import pyarrow.parquet as pq
from server.sports_datasets.consumer import canonical_json_bytes

INTEGRITY = ROOT / "outputs/mlb-v18-conditional-champion-v1/development-integrity/sha256/853fc330c98e56e987905980e06225190cbe8985c4c19f4c2b035c20dba2078f"
RUNTIME = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory"
OUTPUT = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/pa-eligibility"
NYN_CANONICAL = "game-a34b10e030531832f1709061"
PRIOR_REVIEW = OUTPUT / "sha256/3502acb9d6700d7fa27a50c8d119bf667750ef5154229c9a8d8582d727f919dc/eligibility-review.json"
TIMING = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1/duration-data/sha256/9d12bb87e31b77c4f088705dd15a713c0b29795fcd9e7e2d32aac4b41420fbc4/timing-only-evidence.json"


def reference(path, expected=None):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected is not None and digest != expected:
        raise ValueError(f"Source checksum differs: {path}")
    return {"path": str(path.resolve()), "sha256": digest, "bytes": path.stat().st_size}


def date_fields(state):
    names = ("trainingStart", "trainingEnd", "trainingRows", "fitRows", "modelEligibleTrainRows",
        "validationRowsUsedForFit", "validationRowsFit", "targetColumnsRead", "finalOotRowsRead")
    return {key: state[key] for key in names if key in state}


def main():
    manifest = json.loads((INTEGRITY / "manifest.json").read_text())
    refs = {name: reference(INTEGRITY/name, row["sha256"]) for name, row in manifest["artifacts"].items()}
    impact = json.loads((INTEGRITY / "integrity-impact.json").read_text())
    completion = json.loads((INTEGRITY / "completion-authority.json").read_text())
    study_path = RUNTIME / "corrected-hgb-recovery-1/study.json"
    study = json.loads(study_path.read_text())
    folds = []
    for row in impact["foldImpacts"]:
        state_ref = reference(row["fittedPreprocessing"]["path"], row["fittedPreprocessing"]["sha256"])
        state = json.loads(Path(state_ref["path"]).read_text())
        folds.append({"foldNumber": row["foldNumber"], "frozenEstimator": reference(RUNTIME/row["frozenModel"]["relativePath"], row["frozenModel"]["sha256"]),
            "frozenPreprocessing": state_ref, "registeredSplit": next(f for f in study["modelFoldPopulations"] if f["foldNumber"] == row["foldNumber"]),
            "prior": date_fields(state["prior"]), "wave1": date_fields(state["prior"]["wave1FittedAuthority"]),
            "wave2": date_fields(state["prior"]["wave2FittedAuthority"]), "semantic": date_fields(state["semantic"]),
            "interaction": date_fields(state["semantic"]["interactionFitted"]),
            "calibration": {"usedForThisReference": "IDENTITY_RAW_V18", "fittedCalibrationRows": 0},
            "knownFutureTrainingLabelsMinimum": row["provenFutureTrainingLabelsMinimum"],
            "unknownGameFinalizationTrainRows": row["unknownCompletionTrainingRowsExcludedFromDateReconstruction"],
            "informationAvailabilityCertificate": "NOT_ESTABLISHED_BY_NOMINAL_FITTED_DATES"})
    # Existing projection is physically Development-only and contains no targets.
    columns = ["canonicalPaId", "canonicalGameId", "game_date", "foldNumber",
        "potentialKnownFeatureExposure", "knownSuspensionIntervalCalendarMask",
        "batterCanonicalPlayerIdReorderExposed", "pitcherCanonicalPlayerIdReorderExposed"]
    projection = pd.read_parquet(refs["pa-diagnostic-projection.parquet"]["path"], columns=columns)
    if projection.game_date.max() > "2026-08-06" or projection.canonicalPaId.duplicated().any():
        raise ValueError("Authorized isolated identity projection differs")
    windows = []
    for name, fold, start, end in (
        ("FOLD1_2024_BEFORE_FIRST_KNOWN_2024_SUSPENSION", 1, "2024-03-20", "2024-05-20"),
        ("FOLD2_2024_AFTER_ALL_KNOWN_2024_COMPLETIONS", 2, "2024-08-29", "2024-09-29")):
        rows = projection[projection.foldNumber.eq(fold) & projection.game_date.between(start, end)]
        suspect = rows[["potentialKnownFeatureExposure", "knownSuspensionIntervalCalendarMask",
            "batterCanonicalPlayerIdReorderExposed", "pitcherCanonicalPlayerIdReorderExposed"]].any(axis=1)
        windows.append({"name": name, "frozenReferenceFold": fold, "start": start, "end": end,
            "candidatePasBeforeLineageCertification": len(rows), "candidateGamesBeforeLineageCertification": int(rows.canonicalGameId.nunique()),
            "knownDateDiagnosticSuspectPas": int(suspect.sum()),
            "certifiedEligiblePas": 0, "actualComparisonPerformed": False,
            "meaning": "OUTCOME_INDEPENDENT_POSSIBILITY_CHECK_NOT_ORIGINAL_FIVE_FOLD_COHORT"})
    # Safe 2023 original Gold identity columns retain the exact FD1-to-Silver link.
    gold = Path("C:/Users/james/asp-data-staging/mlb-current-statcast-context-gold-v2/objects/sha256/ed6475ac22d4759a49c07626a9c4c367486a78070178253d6b2e2158861930bb.parquet")
    gold_ref = reference(gold, gold.stem)
    bridge = pd.read_parquet(gold, filters=[("canonicalGameId", "=", NYN_CANONICAL)],
        columns=["canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_date", "context_inning"])
    retained = projection[projection.canonicalGameId.eq(NYN_CANONICAL)]
    if set(bridge.canonicalPaId) != set(retained.canonicalPaId) or len(bridge) != 61:
        raise ValueError("NYN frozen projection/exact source-PA bridge differs")
    timing_ref = reference(TIMING, "5f4ecc0bdf5ec1476952f2081be62d75b03e20a9a8cd60e96e72f525618fff52")
    timing = next(row for row in json.loads(TIMING.read_text()) if row["gameId"] == "NYN202309280")
    if set(bridge.plate_appearance_id) != set(timing["terminalPaIdentities"]):
        raise ValueError("Exact frozen canonical/source/FD1 retained-PA identity bridge differs")
    nyn = {"status": "EXACT_61_FROZEN_CANONICAL_TO_SOURCE_PA_IDENTITIES_VERIFIED",
        "identityBridgeArtifact": gold_ref, "canonicalGameId": NYN_CANONICAL,
        "sourceGameId": "NYN202309280", "retainedPas": len(bridge),
        "fd1TimingEvidence": timing_ref, "exactFd1TerminalSourceIdsMatched": len(bridge),
        "sourceIdentityMismatches": 0,
        "innings": sorted(int(v) for v in bridge.context_inning.unique()),
        "voidedNinthInningPasPresent": int(bridge.context_inning.ge(9).sum()),
        "rows": bridge.sort_values("plate_appearance_id").to_dict(orient="records"),
        "qualification": "This disproves inclusion of ninth-inning rows, but does not establish official reversion publication time or complete all-feature availability."}
    result = {"schemaVersion": "MLB_PA_HIERARCHY_FROZEN_BASELINE_ELIGIBILITY_REVIEW_V2",
        "predecessor": reference(PRIOR_REVIEW, PRIOR_REVIEW.parent.name),
        "status": "PA_REAL_COMPARISON_BLOCKED_SHARED_FEATURE_CHRONOLOGY",
        "candidateFitAuthorized": False,
        "declaration": reference(ROOT / "docs/MLB_STARTER_SURVIVAL_HIERARCHY_DECLARATION_V1.json", "51b886ecb20137ea7e8ab0ce1abb8601c3f86df0dfe77dae95d07d8ca01bcc9d"),
        "registeredStudy": reference(study_path), "sourceCompletionAuthority": refs["completion-authority.json"],
        "sourceImpact": refs["integrity-impact.json"], "identityOnlyProjection": refs["pa-diagnostic-projection.parquet"],
        "actualRegisteredSplitId": study["authority"]["splitContractId"], "developmentSeasons": [2023, 2024, 2025, 2026],
        "heldDevelopmentPas": 56, "finalOot": study["finalOot"], "fittedFoldAuthorities": folds,
        "laterWindowConsiderations": windows, "nynRetainedIdentityEvidence": nyn,
        "proposedCommonRuleBeforeTargets": [
            "Declare one later window and frozen V18 artifact before any candidate target/performance read; this is a new retrospective estimand, not the original split experiment.",
            "All fitted estimator/prior/semantic/encoding/calibration information must be available before the prediction window under the expressly declared conservative historical reconstruction rule.",
            "No invented completion/reversion/publication dates. PA occurrence and retained-label disposition are distinguished from official game finalization; no void events are admitted.",
            "Repair/order previous PA and game contributions by supported occurrence/completion availability. Same-day/resumption ordering that matters to a last-N window must be resolved or excluded.",
            "Construct and authenticate identical valid raw246/treated273/encoded features for A/B/C. Changing evaluation vectors alone does not certify frozen fitted-state information; matching dimensions alone does not prove lineage.",
            "Preserve the original56-PA hold, exact8classes, uniquePA IDs and game-atomic temporal split. Exclude any game crossing the declared training/evaluation boundary.",
            "Unknown shared feature lineage fails closed. Outcome-independent coverage is reported separately from certified eligible comparison rows."],
        "remainingGate": ["Retained-label occurrence and reversion disposition must support the declared PA information bound without representing a derived FD1 date as observed publication.",
            "Exact last100/250 and context-history dependencies have no complete repaired shared-vector certificate; diagnostic nonexposure flags alone are insufficient.",
            "Freeze the resulting exact common cohort and shared feature contract before any real hierarchy fit."],
        "boundedConclusion": {
            "candidateWindowsWereExaminedWithoutTargets": True,
            "certifiedMatchedComparisonPas": 0,
            "certifiedMatchedComparisonGames": 0,
            "laterCalendarDatesSolveKnownDirectTrainingCrossing": True,
            "laterCalendarDatesCertifyRecursiveFeatureOrdering": False,
            "noFittedFinalCalibratorApplied": True,
            "retainedNynRowsAreNotVoidedNinthInning": True,
            "laterComparisonProvenImpossible": False,
            "realPaComparisonPerformed": False,
            "reason": "A nominal later cutoff does not supply the missing authenticated, identically constructed rolling/context inputs for frozen A and new B/C. Repairing only new candidate histories would confound architecture with input changes; retaining known official-date ordering would not meet the requested timing-valid shared feature rule.",
            "completedImplementation": "Executable lossless B/C soft hierarchy, training-only conditional frequencies, learned heads sharing exactly one root, full fitted-state reload and NLL decomposition; verified only on clearly synthetic fixtures."},
        "smallestNextRepair": "Use the established exact canonical/source PA bridge plus safe2023/24 event-occurrence metadata to certify/rebuild only affected shared histories. If fitted-state availability still cannot be established, separately authorize a repaired historical reference; do not replace frozen V18 here.",
        "bounds": {"targetsRead": 0, "predictionPayloadsRead": 0, "fits": 0, "modelInferenceCalls": 0,
            "providerCalls": 0, "finalOotPayloadReads": 0, "mixed2026RawReads": 0, "aispWrites": 0}}
    payload = canonical_json_bytes(result)
    digest = hashlib.sha256(payload).hexdigest()
    path = OUTPUT / "sha256" / digest / "eligibility-review.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("Immutable PA eligibility review differs")
    else:
        with path.open("xb") as stream:
            stream.write(payload)
    print(json.dumps({"artifact": reference(path), "windows": windows, "nyn": {k: v for k, v in nyn.items() if k != "rows"}}), flush=True)


if __name__ == "__main__":
    main()
