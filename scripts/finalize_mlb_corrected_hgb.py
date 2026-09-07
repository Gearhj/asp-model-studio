"""Analyze the one frozen corrected HGB study; never fit, tune, or open OOT."""
from __future__ import annotations

import base64
import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
os.environ.setdefault("ATLAS_SECURITY_ROOT", str(RUNTIME_ROOT / "security"))
os.environ.setdefault("ATLAS_SECURITY_DB_PATH", str(RUNTIME_ROOT / "security" / "asp_model_studio_security.db"))

from server.persistence.db import Database
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast.mlb_core_challenger_tuning import read_oof
from server.sports_current_statcast.mlb_corrected_hgb_study import (
    BASELINE_CANDIDATE_ID, BASELINE_CANDIDATE_SHA, BASELINE_RUN_SHA, BOOTSTRAP_REPLICATES, BOOTSTRAP_SEED,
    PROJECT_ID, RESULT_SCHEMA, baseline_authority, content_sha, fold_population,
    game_clustered_difference, matching_job, metrics_allow_absent_classes,
    paired_frames, paired_metrics, read_immutable_json, verify_coverage_ledger, _probabilities,
)
from server.sports_current_statcast.stage3_model_jobs import list_model_development_jobs

DATABASE_PATH = RUNTIME_ROOT / "persistence" / "asp_model_studio.db"
OUTPUT_ROOT = REPOSITORY_ROOT / "outputs" / "mlb-corrected-treatment"
ORIGINAL_STUDY_DIRECTORY = "corrected-hgb-study"
RECOVERY_STUDY_DIRECTORY = "corrected-hgb-recovery-1"
ORIGINAL_FAILED_STUDY_CHECKSUM = "94ce59613407da613b40c1fb7357e148b1053fc064977eeec6efb32acea7e4d0"
PROVISIONAL_PREFLIGHT_RECEIPTS = (
    "e4c4872d2438439ee6b4c8c7d730dd13b9eb7bc8c64b8aa2e54bc2449ec82e84",
    "19836b2464b48a1941af8f58061592d4693f39e8bf2f2643304d27083f9e4dc6",
    "e5bc9efadb8d39337b8a1cea0fa3200bda666d5c2e7662baba42012e56676548",
    "cdf6cda911e1a71323b3b783ac8cc0c1fd7de4b16e131d7dfee03a8ff08c280a",
    "8594d892090ae030ecf8e7ddebcd00e1d27c54d5f9fe430a91e67313b396ed07",
)


def _append(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError(f"Append-only final report conflicts with existing contents: {path}")
        return
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _study_path(directory_name: str) -> Path:
    if directory_name not in {ORIGINAL_STUDY_DIRECTORY, RECOVERY_STUDY_DIRECTORY}:
        raise ValueError("Finalization accepts only the original bounded study or its explicit recovery-1 directory.")
    return lab._runtime_root() / directory_name / "study.json"


def _matching_frozen_job(jobs: list[dict[str, Any]], study: dict[str, Any]) -> dict[str, Any] | None:
    batch_name = str(study.get("plan", {}).get("batchName") or "")
    if not batch_name:
        raise RuntimeError("The frozen study has no batch identity.")
    matches = [job for job in jobs if (job.get("plan") or {}).get("batchName") == batch_name]
    if len(matches) > 1:
        raise RuntimeError("Multiple jobs share the frozen study batch identity; finalization is ambiguous.")
    if not matches:
        return None
    if matches[0]["plan"].get("checksum") != study["plan"]["checksum"]:
        raise RuntimeError("The study batch job differs from its frozen plan checksum.")
    return matches[0]


def _read_recovery_accounting(study: dict[str, Any], *, study_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    from server.sports_current_statcast.mlb_hgb_recovery_telemetry import summarize_events

    recovery = study["recovery"]
    telemetry = recovery["actualFitTelemetry"]
    event_path = Path(telemetry["path"]).resolve()
    expected_event_path = (study_path.parent / "fit-events.jsonl").resolve()
    if event_path != expected_event_path:
        raise RuntimeError("Recovery telemetry must belong to this exact recovery study directory.")
    accounting_path = Path(telemetry["accountingPath"]).resolve()
    if accounting_path != (study_path.parent / "fit-accounting.json").resolve():
        raise RuntimeError("Recovery fit accounting must belong to this exact recovery study directory.")
    raw = accounting_path.read_bytes()
    accounting = json.loads(raw)
    if (accounting.get("schemaVersion") != "MLB_HGB_RECOVERY_FIT_ACCOUNTING_V1"
            or accounting.get("recoveryId") != recovery["recoveryId"]
            or content_sha({key: value for key, value in accounting.items() if key != "accountingChecksum"}) != accounting.get("accountingChecksum")
            or accounting != summarize_events(event_path)):
        raise RuntimeError("Recovery fit accounting does not reconcile with its authenticated append-only event log.")
    reference = {"accountingPath": str(accounting_path.resolve()), "accountingFileSha256": hashlib.sha256(raw).hexdigest(),
                 "accountingChecksum": accounting["accountingChecksum"], "eventPath": str(event_path),
                 "eventsSha256": accounting["eventsSha256"], "lastEventChecksum": accounting["lastEventChecksum"]}
    return accounting, reference


def _recovery_event_timing(accounting: dict[str, Any]) -> dict[str, Any]:
    """Derive durations only from the already authenticated, unchanged log."""
    raw = Path(accounting["eventPath"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != accounting["eventsSha256"]:
        raise RuntimeError("Recovery event log changed after accounting authentication.")
    events = [json.loads(line) for line in raw.splitlines()]
    previous = None
    by_fold: dict[int, dict[str, Any]] = {}
    timestamp_fields = {"FIT_STARTED": "fitStartUtc", "FIT_COMPLETED": "fitCompletedUtc", "FOLD_COMPLETED": "foldCompletedUtc"}
    for event in events:
        try:
            timestamp = datetime.fromisoformat(event["utc"].replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RuntimeError("Recovery event timing requires valid authenticated UTC timestamps.") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() != timedelta(0) or (previous is not None and timestamp < previous):
            raise RuntimeError("Recovery event UTC timestamps are not in nondecreasing sequence.")
        previous = timestamp
        field = timestamp_fields.get(event["event"])
        if field:
            number = event["foldNumber"]
            row = by_fold.setdefault(number, {"foldNumber": number, "fitStartUtc": None, "fitCompletedUtc": None, "foldCompletedUtc": None})
            if row[field] is not None:
                raise RuntimeError("Recovery timing contains a duplicate fold milestone.")
            row[field] = event["utc"]
    for row in by_fold.values():
        def elapsed(start: str, finish: str) -> float | None:
            if row[finish] is None:
                return None
            if row[start] is None:
                raise RuntimeError("Recovery timing completion lacks its preceding milestone.")
            seconds = (datetime.fromisoformat(row[finish].replace("Z", "+00:00")) - datetime.fromisoformat(row[start].replace("Z", "+00:00"))).total_seconds()
            if seconds < 0:
                raise RuntimeError("Recovery timing cannot contain a negative duration.")
            return seconds
        row["estimatorFitSeconds"] = elapsed("fitStartUtc", "fitCompletedUtc")
        row["postFitToFoldCompletionSeconds"] = elapsed("fitCompletedUtc", "foldCompletedUtc")
    if (sorted(by_fold) != accounting["startedFoldNumbers"]
            or [n for n, row in sorted(by_fold.items()) if row["fitCompletedUtc"] is not None] != accounting["fitCompletedFoldNumbers"]
            or [n for n, row in sorted(by_fold.items()) if row["foldCompletedUtc"] is not None] != accounting["completedFoldNumbers"]):
        raise RuntimeError("Recovery timing milestones differ from authenticated fit accounting.")
    return {"basis": "AUTHENTICATED_EVENT_UTC_DIFFERENCES", "eventsSha256": accounting["eventsSha256"],
            "folds": [by_fold[number] for number in sorted(by_fold)],
            "caveat": "UTC wall-clock differences, not CPU time. Post-fit-to-fold-completion includes prediction, metrics, artifact persistence/reload, and other fold completion work; it is not pure reload time. Missing milestones remain NULL, not zero."}


def _recovery_timing(study: dict[str, Any], job: dict[str, Any], accounting: dict[str, Any], *, study_path: Path) -> dict[str, Any]:
    timing = _recovery_event_timing(accounting)
    _, baseline, _ = baseline_authority()
    timing["originalBaselineFoldRuntimes"] = {"candidateId": BASELINE_CANDIDATE_ID, "candidateReceiptSha256": BASELINE_CANDIDATE_SHA,
        "scope": "RECORDED_WHOLE_FOLD_RUNTIME_NOT_ESTIMATOR_ONLY", "folds": [{"foldNumber": fold["foldNumber"], "runtimeMs": fold["runtimeMs"]} for fold in baseline["folds"]]}
    timing["recoveryRuntimeSeconds"] = None
    timing["recoveryRuntimeStatus"] = "NOT_AVAILABLE_NO_TERMINAL_COORDINATOR_RECEIPT"
    terminal_path = study_path.parent / "terminal.json"
    if terminal_path.is_file():
        raw = terminal_path.read_bytes()
        terminal = json.loads(raw)
        seconds = terminal.get("recoveryRuntimeSeconds")
        if (terminal.get("recoveryId") != study["recovery"]["recoveryId"] or terminal.get("studyChecksum") != study["studyChecksum"]
                or terminal.get("jobId") != job["jobId"] or terminal.get("status") != job["status"]
                or terminal.get("actualFitAccounting") != accounting or isinstance(seconds, bool)
                or not isinstance(seconds, (int, float)) or not np.isfinite(seconds) or seconds < 0):
            raise RuntimeError("Recovery terminal timing does not reconcile with this terminal job and authenticated accounting.")
        timing.update(recoveryRuntimeSeconds=seconds, recoveryRuntimeStatus="RECORDED_COORDINATOR_ELAPSED_RUNTIME",
                      terminalReceipt={"path": str(terminal_path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()})
    return timing


def _compare_provisional_preflight(body: dict[str, Any]) -> dict[str, Any]:
    folds = (body.get("treatmentExecution") or {}).get("fittedFoldArtifacts") or []
    if not folds:
        return {"status": "NOT_AVAILABLE_NO_COMPLETED_V18_FITTED_FOLD_ARTIFACTS", "folds": [], "modelFitsPerformedForComparison": 0}
    results = []
    for fold in folds:
        number = int(fold["foldNumber"])
        if not 1 <= number <= len(PROVISIONAL_PREFLIGHT_RECEIPTS):
            raise RuntimeError("Unexpected V18 fold number in provisional preflight comparison.")
        checksum = PROVISIONAL_PREFLIGHT_RECEIPTS[number - 1]
        path = lab._runtime_root() / "objects" / "corrected-preprocessing" / "sha256" / (checksum + ".json")
        provisional = read_immutable_json(path, checksum)
        actual = _artifact_payload(fold["fittedArtifact"])
        if (provisional.get("status") != "PASS" or provisional.get("scope") != "PREFLIGHT_PREPROCESSING_ONLY_NOT_A_MODEL_RUN"
                or provisional.get("predictiveFits") != 0 or provisional.get("finalOotRowsRead") != 0
                or provisional["fold"]["foldNumber"] != number):
            raise RuntimeError("The preserved provisional preflight reference does not authenticate its original scope/fold.")
        transform = fold["localResearchArtifact"]
        actual_columns = len(actual["transformedFeatureNames"])
        checks = {"validationMatrixDigestEqual": provisional["validationValuesSha256"] == transform["transformedValidationSha256"],
                  "transformedColumnCountEqual": provisional["transformedColumns"] == actual_columns,
                  "eligibleValidationRowCountEqual": provisional["modelValidationRows"] == transform["validationRows"],
                  "eligibleTrainingRowCountEqual": provisional["modelTrainRows"] == actual["prior"]["modelEligibleTrainRows"],
                  "trainingSemanticBranchCountsEqual": provisional["trainingBranchCounts"]["features"] == actual["trainingBranchCounts"]["features"],
                  "validationSemanticBranchCountsEqual": provisional["validationBranchCounts"]["features"] == actual["validationBranchCounts"]["features"]}
        prior = {}
        for partition in ("train", "validation"):
            left = {row["feature"]: row for row in provisional["priorExecution"][partition]["features"]}
            right = {row["feature"]: row for row in actual["priorExecution"][partition]["features"]}
            shared_equal = set(left) == set(right)
            differences = {}
            instrumentation = {}
            for feature in sorted(set(left) & set(right)):
                differing = [key for key in sorted(set(left[feature]) & set(right[feature])) if left[feature][key] != right[feature][key]]
                if differing:
                    differences[feature] = differing
                    shared_equal = False
                if set(left[feature]) != set(right[feature]):
                    instrumentation[feature] = {"onlyInProvisional": sorted(set(left[feature]) - set(right[feature])), "onlyInV18": sorted(set(right[feature]) - set(left[feature]))}
            prior[partition] = {"sharedFeatureCountersEqual": shared_equal, "fullCounterPayloadEquality": left == right,
                                "differentSharedCounterKeys": differences, "instrumentationFieldDifferences": instrumentation}
            checks[partition + "PriorSharedCountersEqual"] = shared_equal
        results.append({"foldNumber": number, "status": "OBSERVED_BEHAVIORAL_COMPATIBILITY" if all(checks.values()) else "OBSERVED_DIFFERENCES_REQUIRE_REVIEW",
                        "provisionalReceipt": {"sha256": checksum, "path": str(path)}, "provisionalIdentity": {
                            "featureSetId": (provisional.get("rowEligibility") or {}).get("featureSetId"),
                            "treatmentManifestChecksum": (provisional.get("rowEligibility") or {}).get("treatmentManifestChecksum")},
                        "v18FittedArtifact": fold["fittedArtifact"], "checks": checks,
                        "validationMatrixDigests": {"provisional": provisional["validationValuesSha256"], "v18": transform["transformedValidationSha256"]},
                        "transformedColumnCounts": {"provisional": provisional["transformedColumns"], "v18": actual_columns}, "priorBranchComparison": prior})
    return {"status": "ALL_COMPLETED_FOLDS_OBSERVED_COMPATIBLE" if all(row["status"] == "OBSERVED_BEHAVIORAL_COMPATIBILITY" for row in results) else "OBSERVED_DIFFERENCES_REQUIRE_REVIEW",
            "folds": results, "modelFitsPerformedForComparison": 0, "matrixPayloadsReadForComparison": 0,
            "scope": "EXACT_STORED_MATRIX_DIGEST_COLUMN_COUNT_AND_BRANCH_COUNTER_COMPARISON",
            "limitation": "Matching validation matrices and observed counters support behavioral compatibility on these recorded populations, not proof of identical historical source code or all unseen inputs. Original provisional identities are preserved and are not relabeled V18."}


def _attach_recovery_evidence(body: dict[str, Any], study: dict[str, Any], job: dict[str, Any], *, study_path: Path) -> dict[str, Any]:
    recovery = study.get("recovery") or {}
    predecessor = recovery.get("predecessor") or {}
    if (recovery.get("recoveryAttemptNumber") != 1
            or predecessor.get("studyChecksum") != ORIGINAL_FAILED_STUDY_CHECKSUM
            or study["plan"].get("batchName") != "MLB corrected treatment bounded HGB recovery 1"
            or int(study["authority"].get("treatmentVersion") or 0) != 18
            or not recovery.get("authorityVerification") or not recovery.get("workerVerification")):
        raise RuntimeError("Recovery must link the exact failed study, V18, and frozen compatibility verifications.")
    verified_predecessor_files = []
    for reference in predecessor.get("immutableFiles") or []:
        path = Path(reference["path"]).resolve()
        if REPOSITORY_ROOT.resolve() not in path.parents or path.suffix.lower() not in {".json", ".md"}:
            raise RuntimeError("Predecessor preservation verification accepts repository metadata/report files only.")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != reference["sha256"]:
            raise RuntimeError("Preserved failed-study evidence changed: " + str(path))
        verified_predecessor_files.append({"path": str(path), "sha256": actual})
    if not verified_predecessor_files:
        raise RuntimeError("Recovery has no frozen predecessor-file preservation evidence.")
    accounting, reference = _read_recovery_accounting(study, study_path=study_path)
    starts = accounting["actualFitStarts"]
    completions = accounting["actualFitCompletions"]
    folds = accounting["completedFolds"]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (starts, completions, folds)) or not 0 <= folds <= completions <= starts <= 5:
        raise RuntimeError("Recovery actual-fit telemetry violates the bounded five-fit authorization.")
    if job["status"] == "COMPLETE" and (accounting.get("status") != "COMPLETE" or (starts, completions, folds) != (5, 5, 5)
            or any(accounting.get(key) != [1, 2, 3, 4, 5] for key in ("startedFoldNumbers", "fitCompletedFoldNumbers", "completedFoldNumbers"))):
        raise RuntimeError("A complete recovery requires five authenticated actual starts, completions, and complete folds.")
    transformations = study["plan"]["experiments"][0]["featureSetContract"]["transformationContracts"]
    manifest = transformations["treatmentManifestChecksum"]
    if manifest != study["rowEligibility"]["treatmentManifestChecksum"]:
        raise RuntimeError("Recovery V18 manifest differs between treatment and eligibility authority.")
    evidence = {"recoveryId": recovery["recoveryId"], "recoveryAttemptNumber": 1,
                "frozenRecoveryContext": recovery, "failedStudyEvidencePreserved": verified_predecessor_files,
                "actualFitAccounting": accounting, "actualFitAccountingReference": reference,
                "timing": _recovery_timing(study, job, accounting, study_path=study_path),
                "scheduledSlotAccounting": {key: (job.get("progress") or {}).get(key) for key in ("totalFits", "completedFits", "failedFits", "cancelledFits", "completedConfigurations", "failedConfigurations")},
                "treatmentIdentity": {**study["authority"], "treatmentManifestChecksum": manifest, "modelFeatureSchemaChecksum": transformations["modelFeatureSchemaChecksum"]},
                "preflightCompatibility": {"authorityVerification": recovery["authorityVerification"], "workerVerification": recovery["workerVerification"],
                                            "basis": "EXACT_PRE_EXECUTION_FROZEN_REFERENCES_PROVISIONAL_PREFLIGHT_IDENTITIES_NOT_RELABELED"},
                "observedProvisionalPreflightComparison": _compare_provisional_preflight(body),
                "finalizerReads": "TERMINAL_HASH_CHAIN_AND_METADATA_ONLY_NO_FIT_OR_EVENT_LOG_REPAIR"}
    result = {**body, "studyDirectoryName": RECOVERY_STUDY_DIRECTORY, "recoveryExecutionEvidence": evidence}
    if "executionAccounting" in result:
        result["executionAccounting"] = {**result["executionAccounting"], "actualEstimatorFitCallsStarted": starts,
                                        "actualEstimatorFitCallsCompleted": completions, "completedFoldsFromRecoveryTelemetry": folds,
                                        "actualEstimatorFitCallsStartedStatus": "AUTHENTICATED_APPEND_ONLY_RECOVERY_FIT_TELEMETRY",
                                        "accountingCaveat": "Actual calls come from the separately authenticated recovery event log; failed scheduled slots remain scheduler bookkeeping, not a count of actual attempts."}
    return result


def _recovery_markdown_lines(result: dict[str, Any]) -> list[str]:
    evidence = result.get("recoveryExecutionEvidence")
    if not evidence:
        return []
    accounting = evidence["actualFitAccounting"]
    reference = evidence["actualFitAccountingReference"]
    predecessor = evidence["frozenRecoveryContext"]["predecessor"]
    preflight = evidence["observedProvisionalPreflightComparison"]
    lines = ["", "## Recovery provenance and actual fit telemetry", "",
            f"Recovery `{evidence['recoveryId']}` is distinct from preserved failed study `{predecessor['studyChecksum']}`. No failed-study artifact was overwritten.",
            f"V18 manifest: `{evidence['treatmentIdentity']['treatmentManifestChecksum']}`; model-schema checksum: `{evidence['treatmentIdentity']['modelFeatureSchemaChecksum']}`.",
            f"Authenticated recovery telemetry: {accounting['actualFitStarts']} actual estimator-fit starts; {accounting['actualFitCompletions']} actual fit completions; {accounting['completedFolds']} completed folds. Scheduler slot counters remain separate in JSON.",
            f"Fit accounting: `{reference['accountingPath']}` (SHA-256 `{reference['accountingFileSha256']}`). Event log: `{reference['eventPath']}` (SHA-256 `{reference['eventsSha256']}`).",
            "Exact preflight authority/worker compatibility references are preserved in JSON. Provisional preflight identities remain provisional; they are not relabeled as fitted V18 model artifacts.",
            f"Recorded V18 validation-matrix digest/column-count/branch comparison with the five immutable provisional preflight receipts: `{preflight['status']}`. This compares stored evidence only; no model or transform was fitted or replayed for the comparison."]
    timing = evidence["timing"]
    lines.extend(["", "| Recovery fold | Estimator fit seconds | Post-fit to fold completion seconds |", "| --- | ---: | ---: |"])
    for fold in timing["folds"]:
        values = ["Not completed" if fold[key] is None else f"{fold[key]:.3f}" for key in ("estimatorFitSeconds", "postFitToFoldCompletionSeconds")]
        lines.append(f"| {fold['foldNumber']} | " + " | ".join(values) + " |")
    lines.extend(["", timing["caveat"], "Exact fit-start, fit-completion, and fold-completion UTCs and original V14 whole-fold runtimes are preserved in JSON."])
    if timing["recoveryRuntimeSeconds"] is not None:
        lines.append(f"Total recovery coordinator elapsed time: {timing['recoveryRuntimeSeconds']:.3f} seconds, from the separately referenced terminal receipt.")
    return lines


def _artifact_payload(reference: dict[str, Any]) -> dict[str, Any]:
    root = lab._runtime_root().resolve()
    path = (root / reference["relativePath"]).resolve()
    allowed = root / "objects" / "corrected-preprocessing" / "sha256"
    if path.parent != allowed or path.name != reference["sha256"] + ".json":
        raise RuntimeError("Fitted treatment reference is outside the exact corrected artifact store.")
    return read_immutable_json(path, reference["sha256"])


def _v14_input_change_summary(semantic: dict[str, Any], priors: dict[str, Any], kinds: dict[str, str], baseline_paths: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Separate raw transformations from historic model-input comparisons.

    Historic ordinary medians and V1 parameter payloads were not recovered.
    Only operation/representation deductions supported by recorded paths are
    made here; successor raw/posterior differences are not historic replay.
    """
    features = {}
    future_paths = {}
    deterministic = {}
    for name, counts in semantic.items():
        kind = kinds.get(name, "UNCLASSIFIED_RECORDED_BRANCH")
        paths = baseline_paths.get(name) or []
        median_path = bool(paths) and all(path["numericMissingTreatment"] == "TRAINING_FOLD_MEDIAN" and path["steps"] == ["RETAIN_RAW"] for path in paths)
        binary_passthrough = bool(paths) and all(path["steps"] == ["BINARY_PASSTHROUGH"] for path in paths)
        row = {"kind": kind, "observations": counts.get("rows", 0),
               "rawToSuccessorChangedRows": counts.get("changedRows", 0),
               "baselineRecordedPaths": paths, "confirmedV14ValueDifferentRows": None,
               "historicalImputationValuesRecovered": False}
        native = counts.get("nativeMissingRows", 0)
        if kind in {"NO_PRIOR_CONTEXT", "TRAVEL_INTERACTION"}:
            row.update({"successorNativeMissingRows": native,
                        "confirmedV14RepresentationDifferentRows": native if median_path else None,
                        "comparisonStatus": "NATIVE_MISSING_VERSUS_RECORDED_V14_MEDIAN_PATH" if median_path else "HISTORICAL_PATH_NOT_VERIFIED",
                        "basis": "Successor native NULL is a different model-input representation from V14's recorded numeric median-imputation path. Exact historic median values/difference magnitudes are unavailable; raw NULL staying NULL is not evidence of unchanged model input."})
        elif kind in {"STRUCTURAL_ZERO", "COLD_EXPOSURE"}:
            row.update({"semanticZeroBranchRows": counts.get("semanticZeroRows", 0),
                        "comparisonStatus": "REASON_AWARE_ZERO_AUTHORITY_IMPLEMENTED_HISTORICAL_VALUE_EQUALITY_UNRESOLVED",
                        "basis": "Verified no-history zero assignment is now governed. It may equal V14's old median/mode; changedRows only compares source to successor, not historic model values."})
        elif kind == "REPEAT_OPPONENT_BOOLEAN":
            changed = counts.get("booleanDomainRepairRows", 0)
            row.update({"booleanCountToAnyRepairRows": changed,
                        "confirmedV14ValueDifferentRows": changed if binary_passthrough else None,
                        "comparisonStatus": "COUNT_TO_BOOLEAN_DIFFERS_FROM_RECORDED_RAW_BINARY_PASSTHROUGH" if binary_passthrough else "HISTORICAL_PATH_NOT_VERIFIED"})
        elif kind in {"DETERMINISTIC_INTERACTION", "MATCHUP_BOOLEAN"}:
            recomputed = counts.get("recomputedRows", counts.get("deterministicRecomputedRows", 0))
            row.update({"deterministicRecomputedRows": recomputed,
                        "comparisonStatus": "DETERMINISTIC_EXECUTED_WITHOUT_RAW_VALUE_CHANGE" if counts.get("changedRows", 0) == 0 else "DETERMINISTIC_RECOMPUTATION_CHANGED_RAW_VALUES_HISTORIC_EQUALITY_NOT_REPLAYED"})
            # Complete finite unchanged outputs could not have invoked the
            # legacy numeric imputer; this zero-difference claim is bounded.
            if median_path and counts.get("changedRows", 0) == 0 and not native:
                row["confirmedV14ValueDifferentRows"] = 0
            deterministic[name] = {"recomputedRows": recomputed, "rawToSuccessorChangedRows": counts.get("changedRows", 0)}
        elif kind == "REQUIRED_COMPLETE":
            future_paths[name] = {"validatedRows": counts.get("rows", 0), "futureMissingRejectedRows": counts.get("futureMissingRejectedRows", 0),
                                  "sourceUnavailableRows": counts.get("sourceUnavailableRows", 0), "invalidRows": counts.get("invalidRows", 0),
                                  "rawToSuccessorChangedRows": counts.get("changedRows", 0)}
            row["comparisonStatus"] = "FUTURE_MISSING_REJECTION_GUARD_RECORDED_SEPARATELY_FROM_OBSERVED_VALUE_CHANGES"
        else:
            row["comparisonStatus"] = "RAW_TO_SUCCESSOR_COUNTS_ONLY_NO_HISTORIC_VALUE_REPLAY"
        features[name] = row
    wave1 = {}
    for name, counts in priors.items():
        if counts["wave"] == 1:
            wave1[name] = {"observations": counts.get("rows", 0), "rawSlotPreservedRows": counts.get("preservedRawRows", 0),
                           "rawVsSuccessorPosteriorDifferentRows": counts.get("rawValueDifferentFromPosteriorRows", 0),
                           "trueColdRawMissingRetainedRows": counts.get("trueColdRawMissingRetainedRows", 0),
                           "requiredDerivedColumnsAdded": counts.get("requiredDerivedOutputColumnsAdded", 0),
                           "observationsReceivingAdditionalChannels": counts.get("rows", 0),
                           "confirmedHistoricalV14NumericalDifferenceRows": None,
                           "comparisonStatus": "RAW_PLUS_FIVE_REQUIRED_CHANNELS_VERSUS_V14_POSTERIOR_ONLY",
                           "historicalParameterCaveat": "Raw/new-posterior differences are measured successor evidence, not an exact historical V14 replay. V14 V1 parameter payloads were hash-only, not recovered."}
    row_counts = {counts["observations"] for counts in wave1.values()}
    if len(row_counts) > 1:
        raise RuntimeError("Wave 1 additional-channel coverage differs across source features.")
    added = sum(counts["requiredDerivedColumnsAdded"] for counts in wave1.values())
    observations = next(iter(row_counts), 0)
    return {"scope": "MATCHED_CORRECTED_VALIDATION_OBSERVATIONS_ONLY_OPERATION_AND_SCHEMA_COMPARISONS_NOT_HISTORICAL_TRANSFORM_REPLAY",
            "features": features, "wave1Representation": wave1,
            "additionalWave1Schema": {"sourceFeatures": len(wave1), "requiredColumnsAddedBeforeOneHot": added,
                                     "observationsReceivingAddedSchema": observations, "addedChannelObservationCells": added * observations},
            "futureMissingGuards": future_paths, "futureMissingGuardFeatureCount": len(future_paths),
            "futureMissingRejectedFeatureRowActivations": sum(row["futureMissingRejectedRows"] for row in future_paths.values()),
            "deterministicExecution": deterministic,
            "featuresWithProvenV14RepresentationOrValueChanges": sorted([name for name, row in features.items() if (row.get("confirmedV14RepresentationDifferentRows") or 0) > 0 or (row.get("confirmedV14ValueDifferentRows") or 0) > 0] + list(wave1)),
            "countingCaveat": "Per-feature PA counts overlap. Summing them gives feature-observation cells, not distinct affected PAs. Zero raw-to-successor changes does not mean zero V14 model-input changes."}


def _branch_summary(folds: list[dict[str, Any]], baseline_folds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    semantic_totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    prior_totals: dict[str, dict[str, Any]] = {}
    kinds: dict[str, str] = {}
    baseline_paths: dict[str, list[dict[str, Any]]] = defaultdict(list)
    baseline_by_fold = {row["foldNumber"]: row for row in baseline_folds or []}
    fitted = []
    # Validation fold populations are disjoint; summing training-branch counts
    # across expanding prefixes would double count observations.
    for fold in folds:
        prep = fold["preprocessing"]
        reload = prep.get("localResearchArtifact") or {}
        if (reload.get("status") != "PERSISTED_AND_RELOADED_WITHOUT_REFITTING"
                or reload.get("refitsDuringReload") != 0 or reload.get("finalOotRowsRead") != 0
                or reload.get("transformedValidationSha256") != reload.get("reloadedTransformedValidationSha256")
                or int(reload.get("validationRows") or 0) != fold["validationRows"]
                or not 0.0 <= float(reload.get("probabilityMaximumAbsoluteDifference", float("inf"))) <= 1e-14):
            raise RuntimeError("Every fold must retain a passing full-validation artifact reload receipt.")
        payload = _artifact_payload(prep["fittedArtifact"])
        if (payload["fold"]["foldNumber"] != fold["foldNumber"]
                or payload["validationRowsUsedForParameters"] != 0 or payload["finalOotRowsUsedForParameters"] != 0
                or payload["prior"]["fitRows"] != fold["registeredTrainRows"]
                or payload["semantic"]["trainingRows"] != fold["registeredTrainRows"]
                or payload["prior"]["validationRowsUsedForFit"] != 0
                or payload["semantic"]["validationRowsFit"] != 0):
            raise RuntimeError("Fitted payload does not match its fold training-only authority.")
        implementation = _artifact_payload(payload["implementationSnapshot"])
        if implementation.get("schemaVersion") != "MLB_LOCAL_RESEARCH_IMPLEMENTATION_SNAPSHOT_V1" or not implementation.get("files"):
            raise RuntimeError("The full implementation snapshot is absent.")
        for name, source in implementation["files"].items():
            raw = base64.b64decode(source["sourceBytesBase64"], validate=True)
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise RuntimeError(f"Persisted implementation bytes do not reconcile: {name}.")
        for name, counts in payload["validationBranchCounts"]["features"].items():
            kind = (payload["semantic"].get("rules", {}).get(name) or {}).get("kind")
            if name in payload["semantic"].get("travelInteractions", []):
                kind = "TRAVEL_INTERACTION"
            if name in payload["semantic"].get("deterministicInteractions", []):
                kind = "DETERMINISTIC_INTERACTION"
            if kind:
                if name in kinds and kinds[name] != kind:
                    raise RuntimeError("Recorded semantic feature kind differs between folds.")
                kinds[name] = kind
            if fold["foldNumber"] in baseline_by_fold:
                historic = baseline_by_fold[fold["foldNumber"]]["preprocessing"]
                steps = next((row["steps"] for row in historic.get("registeredOrderedTransformations", []) if row["feature"] == name), [])
                baseline_paths[name].append({"foldNumber": fold["foldNumber"], "steps": steps, "numericMissingTreatment": historic.get("numericMissingTreatment"), "preprocessingArtifactSha256": historic.get("artifactSha256")})
            for key, value in counts.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    semantic_totals[name][key] += value
        for counts in payload["priorExecution"]["validation"]["features"]:
            name = counts["feature"]
            row = prior_totals.setdefault(name, {"wave": counts["wave"], "historyStateCounts": defaultdict(int), "priorLevelCounts": defaultdict(int)})
            for key, value in counts.items():
                if key in {"historyStateCounts", "priorLevelCounts"}:
                    for state, count in value.items():
                        row[key][state] += count
                elif key == "requiredDerivedOutputColumnsAdded":
                    if key in row and row[key] != value:
                        raise RuntimeError("V1 required derived-output schema differs between folds.")
                    row[key] = value
                elif isinstance(value, int) and not isinstance(value, bool) and key != "wave":
                    row[key] = row.get(key, 0) + value
        # Hash the stored model blob without loading it or making predictions.
        model_ref = reload["model"]
        model_path = (lab._runtime_root() / model_ref["relativePath"]).resolve()
        allowed_model = (lab._runtime_root() / "objects" / "research-model" / "sha256").resolve()
        if model_path.parent != allowed_model or model_path.name != model_ref["sha256"] + ".joblib":
            raise RuntimeError("Research model reference is outside its exact object store.")
        from server.sports_current_statcast.stage3_corrected_preprocessing_artifacts import _file_digest
        if _file_digest(model_path) != model_ref["sha256"]:
            raise RuntimeError("Saved model bytes do not match the replay receipt.")
        fitted.append({"foldNumber": fold["foldNumber"], "fittedArtifact": prep["fittedArtifact"], "localResearchArtifact": reload, "implementationSnapshot": payload.get("implementationSnapshot"), "priorFittedChecksum": payload["prior"]["fittedTreatmentChecksum"], "semanticFittedChecksum": payload["semantic"]["fittedChecksum"], "trainingBranchCounts": payload["trainingBranchCounts"], "validationBranchCounts": payload["validationBranchCounts"], "rowEligibility": prep.get("rowEligibility")})
    semantic = {name: dict(counts) for name, counts in sorted(semantic_totals.items())}
    prior = {name: {key: dict(value) if isinstance(value, dict) else value for key, value in counts.items()} for name, counts in sorted(prior_totals.items())}
    return {"countingScope": "DISJOINT_FIVE_VALIDATION_FOLDS_ONLY_TRAINING_COUNTS_RETAINED_PER_FOLD",
            "semanticChangedRowsMeaning": "RAW_SOURCE_TO_SUCCESSOR_TRANSFORM_ONLY_NOT_V14_MODEL_INPUT_COMPARISON",
            "semantic": semantic, "priors": prior,
            "featuresWithRawToSuccessorValueChanges": [name for name, counts in semantic.items() if counts.get("changedRows", 0) > 0],
            "featuresWithoutRawToSuccessorValueChanges": [name for name, counts in semantic.items() if counts.get("changedRows", 0) == 0],
            "v14ComparisonInputChanges": _v14_input_change_summary(semantic, prior, kinds, dict(baseline_paths)),
            "fittedFoldArtifacts": fitted, "reloadVerifiedFoldCount": len(fitted)}


def _subgroup_results(database: Database, study: dict[str, Any], matched: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    resolved = lab.resolve_model_lab_authority(database, PROJECT_ID)
    if (resolved.authority_key != study["authority"]["authorityKey"]
            or resolved.split["checksum"] != study["authority"]["splitChecksum"]):
        raise RuntimeError("Current Development authority differs from the frozen study; refusing a subgroup scan.")
    requested = sorted({name for row in study["subgroups"] for name in row["anyIndicatorEqualsOne"]})
    # This established loader restricts the scan to the registered Development
    # interval. Called only after a complete terminal five-fit run is verified.
    source = lab._fold_frame(resolved, requested, include_oof_identity=True, include_target=False)
    if len(source) != 683662 or source["canonicalPaId"].duplicated().any():
        raise RuntimeError("Subgroup authority is not the one-to-one registered Development population.")
    flags = source[["canonicalPaId", "canonicalGameId", *requested]].copy()
    for name in requested:
        values = pd.to_numeric(flags[name], errors="coerce")
        if values.isna().any() or not values.isin([0, 1]).all():
            raise RuntimeError(f"Subgroup indicator {name} lacks complete Boolean authority.")
        flags[name] = values.astype(np.int8)
    combined = matched.merge(flags, on=["canonicalPaId", "canonicalGameId"], how="left", validate="one_to_one")
    if len(combined) != len(matched) or combined[requested].isna().any().any():
        raise RuntimeError("Matched OOF rows lack exact Development subgroup identity.")
    results = []
    for definition in study["subgroups"]:
        selected = combined[definition["anyIndicatorEqualsOne"]].eq(1).any(axis=1)
        subset = combined.loc[selected]
        result = {"name": definition["name"], "definition": definition, "observations": len(subset), "games": int(subset["canonicalGameId"].nunique()), "proportionOfMatchingOOF": float(len(subset)/len(combined)), "metrics": paired_metrics(subset, columns)}
        if len(subset):
            result["pairedGameClusteredUncertainty"] = game_clustered_difference(subset, columns)
        else:
            result["pairedGameClusteredUncertainty"] = {"status": "NO_MATCHING_OBSERVATIONS"}
        results.append(result)
    return results


def _incomplete_result(study: dict[str, Any], job: dict[str, Any], *, study_path: Path | None = None) -> dict[str, Any]:
    """Report terminal metadata only; do not read/replay any OOF or model."""
    baseline_run, baseline, seed = baseline_authority()
    artifacts = job.get("artifacts") or {}
    progress = job.get("progress") or {}
    run_sha = artifacts.get("modelRunReceiptSha256") or artifacts.get("runReceiptSha256")
    run = None
    references = []
    candidates = []
    if run_sha:
        run_path = lab._runtime_root() / "objects" / "sha256" / f"{run_sha}.json"
        run = read_immutable_json(run_path, run_sha)
        if (run.get("status") != job["status"] or run["plan"]["checksum"] != study["plan"]["checksum"]
                or run["identity"]["targetOrder"] != study["targetOrder"]
                or run.get("finalOotAccessed") is not False or run.get("finalOotTargetsMaterialized") is not False
                or run["population"].get("finalOotLocked") is not True
                or run["population"].get("finalOotTargetAccessed") is not False
                or run["population"].get("finalOotScored") is not False):
            raise RuntimeError("Incomplete run receipt does not match the frozen plan or sealed population.")
        candidates = list(run.get("candidates") or [])
        if len(candidates) > 1:
            raise RuntimeError("The incomplete study exceeds its one-configuration authorization.")
        references.append({"kind": "RUN_RECEIPT", "sha256": run_sha, "path": str(run_path)})
        for reference in run.get("candidateAttemptReceipts") or []:
            checksum = reference["candidateReceiptSha256"]
            path = lab._runtime_root() / "candidate-attempts" / "objects" / "sha256" / f"{checksum}.json"
            receipt = read_immutable_json(path, checksum)
            candidate = next((row for row in candidates if row["candidateId"] == reference["candidateId"]), None)
            if (receipt.get("candidate") != candidate or receipt.get("jobId") != job["jobId"]
                    or receipt.get("planChecksum") != study["plan"]["checksum"]
                    or receipt.get("finalOotTargetAccessed") is not False):
                raise RuntimeError("Failed candidate attempt does not authenticate the terminal run.")
            references.append({"kind": "CANDIDATE_ATTEMPT", "sha256": checksum, "candidateId": reference["candidateId"], "path": str(path)})
    original_metrics = {"status": "RECORDED_IMMUTABLE_V14_METRICS_NOT_RECOMPUTED", "observations": baseline["evaluationEvidence"]["rowCount"],
                        "multiclassLogLoss": baseline["meanOofLogLoss"], "summedBrier": baseline["summedBrier"], "macroOvrRocAuc": baseline["macroOvrRocAuc"],
                        "ece": baseline["ece"], "accuracy": baseline.get("accuracyDiagnostic"), "macroF1": baseline.get("macroF1Diagnostic"),
                        "classCalibration": baseline["classCalibration"], "reliabilityBands": baseline["reliabilityBands"]}
    completed_receipts = sum(len(candidate.get("folds") or []) for candidate in candidates)
    accounting = {"authorizedConfigurations": 1, "authorizedFitSlots": 5,
                  "completedFitMilestones": int(progress.get("completedFits") or 0), "completedFoldReceipts": completed_receipts,
                  "completedConfigurations": int(progress.get("completedConfigurations") or 0),
                  "failedConfigurations": int(progress.get("failedConfigurations") or 0),
                  "scheduledFitSlotsMarkedFailed": int(progress.get("failedFits") or 0),
                  "actualEstimatorFitCallsStarted": None,
                  "actualEstimatorFitCallsStartedStatus": "UNKNOWN_NO_FIT_START_EVENT_IN_TERMINAL_EVIDENCE",
                  "accountingCaveat": "The queue marks expected fits minus completed milestones as failed slots after one configuration exception. Five failed slots are not evidence of five estimator.fit calls. Failure stage/fit-start count cannot be recovered from the recorded exception text alone."}
    unavailable = {"status": "NOT_AVAILABLE_INCOMPLETE_FIVE_FOLD_STUDY", "correctedMetrics": None, "matchedComparison": None,
                   "pairedGameClusteredConfidenceInterval": None, "subgroupResults": None,
                   "predictiveArtifactReloadVerification": "NOT_EVALUATED_NO_COMPLETED_STUDY_REPLAY",
                   "completedFoldReloadReceipts": sum(bool((fold.get("preprocessing") or {}).get("localResearchArtifact")) for candidate in candidates for fold in candidate.get("folds") or [])}
    return {"schemaVersion": RESULT_SCHEMA, "studyChecksum": study["studyChecksum"], "status": job["status"], "projectId": PROJECT_ID,
            "authority": study["authority"], "studyArtifactPath": str(study_path or _study_path(ORIGINAL_STUDY_DIRECTORY)),
            "executionAccounting": accounting, "runtimeMs": run.get("runtimeMs") if run else None,
            "failure": {"jobId": job["jobId"], "progress": progress, "error": job.get("error") or {}, "artifacts": artifacts,
                        "runStatus": run.get("status") if run else None, "runFailures": run.get("failures") if run else None, "candidates": candidates},
            "immutableArtifactReferences": references,
            "baseline": {"runReceiptSha256": BASELINE_RUN_SHA, "candidateId": BASELINE_CANDIDATE_ID, "candidateReceiptSha256": BASELINE_CANDIDATE_SHA,
                         "targetOrder": baseline_run["identity"]["targetOrder"], "originalPopulationMetrics": original_metrics,
                         "perFold": [{"foldNumber": fold["foldNumber"], "observations": fold["validationRows"], "metrics": fold["metrics"]} for fold in baseline["folds"]],
                         "oofArtifactReferenceNotRead": {key: value for key, value in baseline["evaluationEvidence"].items() if key.startswith("reloadableArtifact")}},
            "correctedComparison": unavailable,
            "frozenDesignNotAnExecutedResult": {"registeredDevelopmentRows": study["development"]["rows"],
                                               "eligibleDevelopmentRows": study["rowEligibility"]["eligibleRows"],
                                               "quarantinedDevelopmentRows": study["rowEligibility"]["heldRows"],
                                               "plannedEligibleOofRows": sum(row["validationRows"] for row in study["modelFoldPopulations"]),
                                               "featureCountBeforeOneHot": 273, "additionalWave1Columns": 55, "seed": seed,
                                               "plannedFoldSeeds": study["foldSeeds"]},
            "executionResourceComparison": study["executionResourceComparison"],
            "finalOot": {"rows": 14067, "locked": True, "accessed": False, "scored": False, "targetsMaterialized": False},
            "finalizerActivity": {"modelFits": 0, "ooFPredictionPayloadsRead": 0, "developmentFeaturePayloadRowsRead": 0, "modelArtifactReplays": 0, "additionalSubmissions": 0},
            "recommendation": "Address the evidenced Windows execution blocker while retaining V14 as the research baseline; the corrected challenger cannot be finalized without the authorized comparison. Do not retry this terminal study automatically. Bet-readiness remains next after challenger finalization."}


def _report_markdown(result: dict[str, Any]) -> str:
    lines = ["# Corrected MLB treatment — bounded HGB comparison", "", f"Status: `{result['status']}`. Study `{result['studyChecksum']}`.", ""]
    if result["status"] != "COMPLETE":
        accounting = result["executionAccounting"]
        baseline = result["baseline"]["originalPopulationMetrics"]
        reasons = sorted({str(row.get("reason") or row.get("errorReason")) for row in (result["failure"].get("runFailures") or result["failure"].get("candidates") or [])})
        starts = accounting.get("actualEstimatorFitCallsStarted")
        start_description = ("Actual fit starts are unknown from the retained terminal evidence." if starts is None else f"The separate recovery event log records {starts} actual fit starts and {accounting.get('actualEstimatorFitCallsCompleted')} actual completions.")
        lines.extend(["The authorized study did not complete. No automatic retry or additional fits were started by the finalizer.", "",
                      f"{accounting['completedFitMilestones']} completed fit milestones; {accounting['completedFoldReceipts']} completed fold receipts; {accounting['failedConfigurations']} configuration failure(s). The queue's {accounting['scheduledFitSlotsMarkedFailed']} failed fit slots are scheduling/accounting entries—not evidence of that many actual estimator.fit calls. {start_description}", "",
                      "Recorded error: " + "; ".join(reasons) + ".", "",
                      f"Runtime: {result['runtimeMs'] / 1000:.3f} seconds." if result["runtimeMs"] is not None else "Runtime unavailable.", "",
                      f"The original V14 benchmark remains on its original {baseline['observations']:,}-PA OOF population. These are unchanged stored metrics; no prediction payload was reread:", "",
                      "| Original V14 metric | Stored value |", "| --- | ---: |"])
        for name in ("multiclassLogLoss", "summedBrier", "macroOvrRocAuc", "ece"):
            lines.append(f"| {name} | {baseline[name]:.12f} |")
        lines.extend(["", "Corrected log loss/Brier/AUC/calibration, matched-observation comparisons, paired confidence intervals, subgroup results, and predictive-artifact reload verification are unavailable. No corrected predictive result or comparative lift is inferred from preprocessing-only tests or preflight receipts. The 273-column schema/55 added Wave 1 columns remain the frozen design, not evidence of a completed predictive run.", "",
                      "Final OOT: all 14,067 rows remain sealed; no access, scoring, or targets materialized. No promotion, export, or deployment.", "",
                      "## Immutable evidence", "",
                      f"Study: `{result['studyArtifactPath']}`.", f"Baseline run: `{BASELINE_RUN_SHA}`; candidate: `{BASELINE_CANDIDATE_ID}`."])
        for reference in result["immutableArtifactReferences"]:
            lines.append(f"- {reference['kind']}: `{reference['path']}` (SHA-256 `{reference['sha256']}`).")
        lines.extend(["", "The adjacent JSON preserves exact failure/candidate/job evidence, baseline per-fold/calibration diagnostics, fit-accounting limitations, and frozen design metadata."])
        lines.extend(_recovery_markdown_lines(result))
        lines.extend(["", f"Recommendation: {result['recommendation']}"])
        return "\n".join(lines) + "\n"
    authority = result["authority"]
    coverage = result["coverage"]
    original = result["originalPopulationMetrics"]
    lines.extend([f"Treatment V{authority['treatmentVersion']}; {authority['featureCount']} source/derived predictors from {authority['sourceFeatureCount']} original source features. Exactly one HGB configuration completed all five chronological fits.", "",
                  f"Registered Development remains 683,662 PAs. The frozen, outcome-independent `{result['rowEligibility']['heldObservations'][0]['reason'] if result['rowEligibility']['heldObservations'] else 'NO_EXCLUSIONS'}` policy quarantined {result['rowEligibility']['heldRows']:,} Development PAs, including {coverage['baselineOnlyRows']:,} V14 OOF PAs. They were not imputed or relabeled as cold starts. No source rows were deleted.", "",
                  f"Original V14 OOF result: {original['baseline']['multiclassLogLoss']:.12f} log loss on {coverage['baselineOriginalRows']:,} PAs. Corrected original OOF result: {original['corrected']['multiclassLogLoss']:.12f} on {coverage['correctedOriginalRows']:,} PAs. The table below compares both models only on the same {coverage['matchingRows']:,} observations.", "",
                  "| Matched OOF metric | V14 baseline | Corrected | Corrected − V14 |", "| --- | ---: | ---: | ---: |"])
    comparison = result["matchingObservationComparison"]
    for key in ("multiclassLogLoss", "summedBrier", "macroOvrRocAuc", "ece"):
        vals = [comparison["baseline"].get(key), comparison["corrected"].get(key), comparison["correctedMinusBaseline"].get(key)]
        formatted = [f"{value:.12f}" if value is not None else "Unavailable" for value in vals]
        lines.append(f"| {key} | " + " | ".join(formatted) + " |")
    ci = result["pairedGameClusteredUncertainty"]
    resources = result["executionResourceComparison"]
    lines.extend(["", f"The exact 218-source feature order is preserved. HGB estimator native workers: V14 {resources['baseline']['nativeWorkers']}; corrected {resources['corrected']['nativeWorkers']}. Full resource metadata and baseline/current batch scheduling are frozen separately in JSON; identical batch scheduling is not assumed."])
    lines.extend(["", f"Paired game-clustered log-loss difference: {ci['estimate']:.12f}; 95% CI [{ci['confidenceInterval']['lower']:.12f}, {ci['confidenceInterval']['upper']:.12f}]. {ci['rowCount']:,} matched PAs; {ci['gameClusterCount']:,} game clusters; {ci['replicates']:,} resamples, seed {ci['seed']}.", "", "Metrics and uncertainty use pooled PA weighting. Training prefixes overlap; reported aggregate treatment-change counts use the disjoint validation folds only.", "", "| Fold | Validation rows | V14 log loss | Corrected log loss | Difference |", "| --- | ---: | ---: | ---: | ---: |"])
    for fold in result["perFold"]:
        m = fold["metrics"]
        lines.append(f"| {fold['foldNumber']} | {fold['observations']:,} | {m['baseline']['multiclassLogLoss']:.12f} | {m['corrected']['multiclassLogLoss']:.12f} | {m['correctedMinusBaseline']['multiclassLogLoss']:.12f} |")
    lines.extend(["", "| Predefined subgroup | PAs | Games | V14 log loss | Corrected log loss |", "| --- | ---: | ---: | ---: | ---: |"])
    for subgroup in result["subgroups"]:
        m = subgroup["metrics"]
        before, after = m["baseline"].get("multiclassLogLoss"), m["corrected"].get("multiclassLogLoss")
        lines.append(f"| {subgroup['name']} | {subgroup['observations']:,} | {subgroup['games']:,} | {before:.12f} | {after:.12f} |" if before is not None and after is not None else f"| {subgroup['name']} | 0 | 0 | Not estimable | Not estimable |")
    lines.extend(["", "Full per-class AUC/Brier/calibration, confidence reliability bands, subgroup intervals, original-population metrics, and coverage are preserved in the adjacent JSON report.", "", "## Treatment branches and reproducibility", "", "Raw-source→successor counts below are not V14 model-input comparisons: source NULL remaining NULL has zero raw change but differs from V14's median-imputation path.", "", "| Semantic feature with raw-source→successor changes | Raw-source→successor changed PAs |", "| --- | ---: |"])
    branches = result["treatmentExecution"]
    for name in branches["featuresWithRawToSuccessorValueChanges"]:
        lines.append(f"| {name} | {branches['semantic'][name]['changedRows']:,} |")
    changes = branches["v14ComparisonInputChanges"]
    lines.extend(["", "| Native-missing feature vs recorded V14 median path | Corrected native-NULL PAs | Proven representation-change PAs |", "| --- | ---: | ---: |"])
    for name, row in changes["features"].items():
        if "successorNativeMissingRows" in row:
            confirmed = row["confirmedV14RepresentationDifferentRows"]
            lines.append(f"| {name} | {row['successorNativeMissingRows']:,} | {confirmed:,} |" if confirmed is not None else f"| {name} | {row['successorNativeMissingRows']:,} | Historical path unverified |")
    lines.extend(["", "Exact historical median/mode values were not recovered. Reason-aware structural-zero assignments may equal V14's prior fill value; their semantic-authority repair is established, but historical numerical equality is unresolved. Repeat-opponent count→Boolean changes are measured against V14's recorded raw passthrough in JSON.", "", "| Wave 1 raw slot preserved | Raw ≠ successor posterior PAs | True-cold raw NULL retained | Added required columns |", "| --- | ---: | ---: | ---: |"])
    for name, counts in branches["priors"].items():
        if counts["wave"] == 1:
            lines.append(f"| {name} | {counts['rawValueDifferentFromPosteriorRows']:,} | {counts['trueColdRawMissingRetainedRows']:,} | {counts['requiredDerivedOutputColumnsAdded']} |")
    addition = changes["additionalWave1Schema"]
    lines.extend(["", f"All {addition['observationsReceivingAddedSchema']:,} corrected OOF PAs receive the {addition['requiredColumnsAddedBeforeOneHot']} additional required Wave 1 columns before one-hot expansion. Raw/new-posterior differences above are successor evidence, not a reconstructed V14 posterior replay. Per-feature counts overlap and must not be summed as distinct affected PAs.", "", "| Deterministic treatment | Recomputed PAs | Raw-source→successor changed PAs |", "| --- | ---: | ---: |"])
    for name, row in changes["deterministicExecution"].items():
        lines.append(f"| {name} | {row['recomputedRows']:,} | {row['rawToSuccessorChangedRows']:,} |")
    lines.extend(["", f"The {changes['futureMissingGuardFeatureCount']} required-complete future-missing guards recorded {changes['futureMissingRejectedFeatureRowActivations']:,} missing-rejection activations in the successful validation transforms; zero activations means the guard was not exercised by these recorded inputs. Synthetic rejection tests remain distinct evidence."])
    lines.extend(["", "Failure paths with zero observed activations remain tested guards; this report does not claim such failures occurred in Development. The JSON retains all per-feature branch counts and prior history-state counts.", "", f"All {branches['reloadVerifiedFoldCount']} saved transforms/models passed full validation-data/prediction reload without refitting. Runtime: {result['execution']['runtimeMs']/3600000:.3f} hours. Failures: {result['execution']['failedFits']}.", "", "V1 exact parameters are newly fitted successor evidence, not recovered historical V14 parameters. V2 parameters are the existing exact fold authorities. Parent-only ablations remain explicitly deferred; optional V2 outputs were not added. The 22 approved exclusions remain preserved.", "", "Final OOT: 14,067 rows remain sealed; no access, scoring, calibration, or selection. No champion, promotion, production export, or deployment.", "", f"Recommendation: {result['recommendation']}", "", "## Exact artifact references", "", f"Corrected run: `{result['execution']['modelRunReceiptSha256']}`.", f"Baseline run: `{BASELINE_RUN_SHA}`; candidate `{BASELINE_CANDIDATE_ID}`."])
    for fold in branches["fittedFoldArtifacts"]:
        lines.append(f"- Fold {fold['foldNumber']}: preprocessing `{fold['fittedArtifact']['relativePath']}`; model `{fold['localResearchArtifact']['model']['relativePath']}`.")
    lines.extend(_recovery_markdown_lines(result))
    return "\n".join(lines) + "\n"


def finalize_study(study_directory_name: str = ORIGINAL_STUDY_DIRECTORY) -> dict[str, Any]:
    study_path = _study_path(study_directory_name)
    study = json.loads(study_path.read_bytes())
    if content_sha({key: value for key, value in study.items() if key != "studyChecksum"}) != study.get("studyChecksum"):
        raise RuntimeError("Frozen study checksum mismatch.")
    database = Database(DATABASE_PATH)
    jobs = list_model_development_jobs(database, PROJECT_ID)["jobs"]
    job = matching_job(jobs, study) if study_directory_name == ORIGINAL_STUDY_DIRECTORY else _matching_frozen_job(jobs, study)
    if job is None or job["status"] not in {"COMPLETE", "PARTIAL", "FAILED", "CANCELLED", "CANCELLED_PARTIAL"}:
        raise RuntimeError("The bounded study must have one terminal job before finalization.")
    if job["status"] != "COMPLETE":
        body = _incomplete_result(study, job, study_path=study_path)
    else:
        artifacts = job["artifacts"]
        run_sha = artifacts.get("modelRunReceiptSha256") or artifacts.get("runReceiptSha256")
        if not run_sha:
            raise RuntimeError("Completed job has no immutable run receipt.")
        run = read_immutable_json(lab._runtime_root() / "objects" / "sha256" / f"{run_sha}.json", run_sha)
        baseline_run, baseline, seed = baseline_authority()
        candidates = run.get("candidates") or []
        if (run.get("status") != "COMPLETE" or len(candidates) != 1
                or run["plan"]["checksum"] != study["plan"]["checksum"]
                or run["identity"]["targetOrder"] != study["targetOrder"]):
            raise RuntimeError("Terminal run differs from the frozen one-configuration study.")
        candidate = candidates[0]
        if (candidate.get("modelFamily") != "histogram_gradient_boosting"
                or candidate.get("hyperparameters") != study["hyperparameters"]
                or candidate.get("seed") != seed or candidate.get("foldsCompleted") != 5
                or candidate.get("featureCount") != 273 or candidate.get("status") != "COMPLETE"
                or candidate.get("executionResources") != study["executionResourceComparison"]["corrected"]
                or candidate.get("rowEligibility") != study["rowEligibility"]
                or len(candidate.get("folds") or []) != 5):
            raise RuntimeError("Corrected HGB configuration, seed, schema, or five fold populations changed.")
        for actual, expected in zip(candidate["folds"], study["modelFoldPopulations"], strict=True):
            if any(actual.get(key) != expected[key] for key in (*tuple(study["folds"][0]), "registeredTrainRows", "registeredValidationRows")):
                raise RuntimeError("Corrected fold counts differ from registered boundaries and the frozen quarantine ledger.")
            eligibility = (actual.get("preprocessing") or {}).get("rowEligibility") or {}
            if (eligibility.get("modelTrainRows") != expected["trainRows"]
                    or eligibility.get("modelValidationRows") != expected["validationRows"]
                    or eligibility.get("quarantinedTrainRows") != expected["quarantinedTrainRows"]
                    or eligibility.get("quarantinedValidationRows") != expected["quarantinedValidationRows"]):
                raise RuntimeError("Per-fold preprocessing eligibility does not reconcile with the frozen exclusions.")
        population = run["population"]
        if (population.get("rows") != 683662 or population.get("finalOotLocked") is not True
                or population.get("finalOotTargetAccessed") is not False or population.get("finalOotScored") is not False
                or run.get("finalOotAccessed") is not False or run.get("finalOotTargetsMaterialized") is not False):
            raise RuntimeError("Run population or Final OOT seal does not reconcile.")
        baseline_oof = read_oof(baseline)
        corrected_oof = read_oof(candidate)
        matched, coverage, columns = paired_frames(corrected_oof, baseline_oof)
        coverage_ledger = verify_coverage_ledger(baseline_oof, corrected_oof, study)
        if len(baseline_oof) != sum(row["validationRows"] for row in study["folds"]) or len(corrected_oof) != sum(row["validationRows"] for row in study["modelFoldPopulations"]):
            raise RuntimeError("Original or corrected OOF row coverage does not reconcile with frozen fold counts.")
        comparison = paired_metrics(matched, columns)
        interval = game_clustered_difference(matched, columns)
        if not np.isclose(interval["estimate"], comparison["correctedMinusBaseline"]["multiclassLogLoss"], rtol=0.0, atol=1e-12):
            raise RuntimeError("Clustered uncertainty and headline metric weighting differ.")
        original_before = metrics_allow_absent_classes(_probabilities(baseline_oof, columns), baseline_oof["observedClassIndex"].to_numpy(dtype=np.int64))
        original_after = metrics_allow_absent_classes(_probabilities(corrected_oof, columns), corrected_oof["observedClassIndex"].to_numpy(dtype=np.int64))
        if abs(original_before["multiclassLogLoss"] - baseline["meanOofLogLoss"]) > 1e-12 or abs(original_after["multiclassLogLoss"] - candidate["meanOofLogLoss"]) > 1e-12:
            raise RuntimeError("Recomputed original OOF metrics differ from the immutable run receipts.")
        per_fold = []
        for actual, expected in zip(candidate["folds"], study["modelFoldPopulations"], strict=True):
            part = matched.loc[matched["foldNumber"].eq(actual["foldNumber"])]
            if len(part) != expected["validationRows"] or part["canonicalGameId"].nunique() != actual["modelValidationGames"]:
                raise RuntimeError("Corrected OOF fold membership count disagrees with its fitted-fold receipt.")
            per_fold.append({"foldNumber": actual["foldNumber"], "observations": len(part), "games": int(part["canonicalGameId"].nunique()), "registeredPopulation": study["folds"][actual["foldNumber"] - 1], "correctedModelPopulation": {**expected, "modelTrainGames": actual["modelTrainGames"], "modelValidationGames": actual["modelValidationGames"]}, "metrics": paired_metrics(part, columns), "originalV14FoldMetrics": baseline["folds"][actual["foldNumber"] - 1]["metrics"]})
        branches = _branch_summary(candidate["folds"], baseline["folds"])
        subgroups = _subgroup_results(database, study, matched, columns)
        recommendation = ("Retain the V14 model as the research comparison baseline pending assessment of the evidenced loss regression under corrected preprocessing; do not restore the incorrect treatment paths. Bet-readiness remains next after challenger finalization." if interval["confidenceInterval"]["lower"] > 0.0 else "Proceed toward challenger finalization with the corrected preprocessing and this preserved comparison; conduct bet-readiness and qualification analysis next. This is not a promotion or champion declaration.")
        body = {"schemaVersion": RESULT_SCHEMA, "status": "COMPLETE", "studyChecksum": study["studyChecksum"], "projectId": PROJECT_ID, "authority": study["authority"], "studyArtifactPath": str(study_path), "baseline": {"runReceiptSha256": BASELINE_RUN_SHA, "candidateId": BASELINE_CANDIDATE_ID}, "execution": {"jobId": job["jobId"], "modelRunId": run["runId"], "modelRunReceiptSha256": run_sha, "candidateId": candidate["candidateId"], "completedFits": 5, "failedFits": int(job["progress"].get("failedFits") or 0), "runtimeMs": run["runtimeMs"], "hyperparameters": candidate["hyperparameters"], "seed": seed, "foldSeeds": study["foldSeeds"]}, "executionResourceComparison": study["executionResourceComparison"], "sourceFeatureOrderMatchesBaselineExactly": study["sourceFeatureOrderMatchesBaselineExactly"], "coverage": coverage, "coverageLedgerVerification": coverage_ledger, "rowEligibility": study["rowEligibility"], "rowEligibilityReceipt": study["rowEligibilityReceipt"], "originalPopulationMetrics": {"baseline": original_before, "corrected": original_after}, "matchingObservationComparison": comparison, "pairedGameClusteredUncertainty": interval, "perFold": per_fold, "subgroups": subgroups, "treatmentExecution": branches, "finalOot": {"rows": 14067, "locked": True, "accessed": False, "scored": False, "targetsMaterialized": False}, "remainingWork": {"approvedExclusions": 22, "parentOnlyAblations": "DEFERRED_BY_EXPLICIT_USER_DECISION", "optionalWave2Outputs": "NOT_SELECTED_NOT_REQUIRED", "historicalV1Payloads": "NOT_RECOVERED_NEW_SUCCESSOR_FITS_ARE_DISTINCT"}, "recommendation": recommendation, "additionalFitsStartedByFinalizer": 0}
    if study_directory_name == RECOVERY_STUDY_DIRECTORY:
        body = _attach_recovery_evidence(body, study, job, study_path=study_path)
    checksum = content_sha(body)
    result = {**body, "resultChecksum": checksum}
    report_prefix = "corrected-hgb-comparison" if study_directory_name == ORIGINAL_STUDY_DIRECTORY else "corrected-hgb-recovery-1-comparison"
    json_path = OUTPUT_ROOT / f"{report_prefix}-{checksum}.json"
    md_path = OUTPUT_ROOT / f"{report_prefix}-{checksum}.md"
    _append(json_path, canonical_json_bytes(result))
    _append(md_path, _report_markdown(result).encode("utf-8"))
    output = {"status": result["status"], "resultChecksum": checksum, "jsonReport": str(json_path), "markdownReport": str(md_path)}
    print(json.dumps(output, sort_keys=True), flush=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-directory", choices=(ORIGINAL_STUDY_DIRECTORY, RECOVERY_STUDY_DIRECTORY), default=ORIGINAL_STUDY_DIRECTORY)
    arguments = parser.parse_args()
    finalize_study(arguments.study_directory)


if __name__ == "__main__":
    main()
