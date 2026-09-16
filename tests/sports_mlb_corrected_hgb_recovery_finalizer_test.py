from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import finalize_mlb_corrected_hgb as finalizer
from server.sports_datasets.consumer import canonical_json_bytes


def test_recovery_job_matching_cannot_select_or_replace_original_failed_job():
    original = {"jobId": "old", "status": "PARTIAL", "plan": {"batchName": "MLB corrected treatment bounded HGB comparison", "checksum": "old-plan"}}
    recovery = {"jobId": "recovery", "status": "COMPLETE", "plan": {"batchName": "MLB corrected treatment bounded HGB recovery 1", "checksum": "new-plan"}}
    study = {"plan": recovery["plan"]}
    assert finalizer._matching_frozen_job([original, recovery], study) is recovery
    assert finalizer._matching_frozen_job([original], study) is None
    with pytest.raises(RuntimeError, match="Multiple jobs"):
        finalizer._matching_frozen_job([recovery, copy.deepcopy(recovery)], study)
    with pytest.raises(RuntimeError, match="checksum"):
        finalizer._matching_frozen_job([recovery], {"plan": {**recovery["plan"], "checksum": "altered"}})


def test_finalizer_directory_scope_is_explicit():
    assert finalizer._study_path("corrected-hgb-recovery-1").parent.name == "corrected-hgb-recovery-1"
    assert finalizer._study_path("corrected-hgb-study").parent.name == "corrected-hgb-study"
    with pytest.raises(ValueError, match="explicit recovery-1"):
        finalizer._study_path("../corrected-hgb-study")


def _recovery_fixture():
    root = finalizer.REPOSITORY_ROOT / ".runtime" / "synthetic-recovery-finalizer"
    study_path = root / "corrected-hgb-recovery-1" / "study.json"
    preserved_path = root / "corrected-hgb-study" / "study.json"
    preserved = b'{"preserved":true}'
    predecessor = {"studyChecksum": finalizer.ORIGINAL_FAILED_STUDY_CHECKSUM,
                   "immutableFiles": [{"path": str(preserved_path), "sha256": hashlib.sha256(preserved).hexdigest()}]}
    study = {"authority": {"treatmentVersion": 18}, "rowEligibility": {"treatmentManifestChecksum": "manifest"},
             "plan": {"batchName": "MLB corrected treatment bounded HGB recovery 1", "experiments": [{"featureSetContract": {"transformationContracts": {"treatmentManifestChecksum": "manifest", "modelFeatureSchemaChecksum": "schema"}}}]},
             "recovery": {"recoveryId": "recovery-1", "recoveryAttemptNumber": 1, "predecessor": predecessor,
                          "authorityVerification": {"status": "FROZEN_COMPATIBILITY"}, "workerVerification": {"status": "ABSENT"},
                          "actualFitTelemetry": {"path": str(study_path.parent / "fit-events.jsonl"), "accountingPath": str(study_path.parent / "fit-accounting.json")}}}
    return study, study_path, preserved_path, preserved


def test_recovery_actual_calls_are_separate_from_failed_scheduler_slots(monkeypatch):
    study, path, preserved_path, preserved = _recovery_fixture()
    original_read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: preserved if self.resolve() == preserved_path.resolve() else original_read(self))
    accounting = {"actualFitStarts": 2, "actualFitCompletions": 1, "completedFolds": 1, "status": "FAILED"}
    monkeypatch.setattr(finalizer, "_read_recovery_accounting", lambda *args, **kwargs: (accounting, {"accountingPath": "synthetic"}))
    monkeypatch.setattr(finalizer, "_recovery_timing", lambda *args, **kwargs: {"folds": []})
    body = {"status": "PARTIAL", "executionAccounting": {"scheduledFitSlotsMarkedFailed": 4, "actualEstimatorFitCallsStarted": None}}
    result = finalizer._attach_recovery_evidence(body, study, {"status": "PARTIAL", "progress": {"failedFits": 4}}, study_path=path)
    assert result["executionAccounting"]["actualEstimatorFitCallsStarted"] == 2
    assert result["executionAccounting"]["actualEstimatorFitCallsCompleted"] == 1
    assert result["executionAccounting"]["scheduledFitSlotsMarkedFailed"] == 4
    assert body["executionAccounting"]["actualEstimatorFitCallsStarted"] is None
    assert result["recoveryExecutionEvidence"]["treatmentIdentity"]["treatmentManifestChecksum"] == "manifest"
    assert result["recoveryExecutionEvidence"]["observedProvisionalPreflightComparison"]["status"].startswith("NOT_AVAILABLE")
    with pytest.raises(RuntimeError, match="five authenticated actual starts"):
        finalizer._attach_recovery_evidence(body, study, {"status": "COMPLETE", "progress": {}}, study_path=path)


def test_recovery_refuses_changed_predecessor_metadata(monkeypatch):
    study, path, preserved_path, _ = _recovery_fixture()
    original_read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"changed" if self.resolve() == preserved_path.resolve() else original_read(self))
    with pytest.raises(RuntimeError, match="Preserved failed-study evidence changed"):
        finalizer._attach_recovery_evidence({}, study, {"status": "PARTIAL"}, study_path=path)


def test_provisional_matrix_and_branch_comparison_preserves_distinct_identity(monkeypatch):
    semantic_counts = {"feature": {"rows": 20, "nativeMissingRows": 2, "changedRows": 0}}
    prior = {"feature": "prior", "wave": 1, "rows": 20}
    provisional = {"status": "PASS", "scope": "PREFLIGHT_PREPROCESSING_ONLY_NOT_A_MODEL_RUN", "predictiveFits": 0, "finalOotRowsRead": 0,
                   "fold": {"foldNumber": 1}, "validationValuesSha256": "same-matrix", "transformedColumns": 432,
                   "modelValidationRows": 20, "modelTrainRows": 100, "rowEligibility": {"featureSetId": "UNREGISTERED_PREFLIGHT", "treatmentManifestChecksum": "old-provisional"},
                   "trainingBranchCounts": {"features": semantic_counts}, "validationBranchCounts": {"features": semantic_counts},
                   "priorExecution": {"train": {"features": [prior]}, "validation": {"features": [prior]}}}
    actual = {"transformedFeatureNames": list(range(432)), "prior": {"modelEligibleTrainRows": 100},
              "trainingBranchCounts": {"features": semantic_counts}, "validationBranchCounts": {"features": semantic_counts},
              "priorExecution": {"train": {"features": [{**prior, "newCounter": 0}]}, "validation": {"features": [{**prior, "newCounter": 0}]}}}
    record = {"foldNumber": 1, "fittedArtifact": {"sha256": "new-v18"}, "localResearchArtifact": {"transformedValidationSha256": "same-matrix", "validationRows": 20}}
    monkeypatch.setattr(finalizer, "read_immutable_json", lambda *args: provisional)
    monkeypatch.setattr(finalizer, "_artifact_payload", lambda *args: actual)
    result = finalizer._compare_provisional_preflight({"treatmentExecution": {"fittedFoldArtifacts": [record]}})
    assert result["status"] == "ALL_COMPLETED_FOLDS_OBSERVED_COMPATIBLE"
    assert result["folds"][0]["provisionalIdentity"]["treatmentManifestChecksum"] == "old-provisional"
    assert result["folds"][0]["v18FittedArtifact"]["sha256"] == "new-v18"
    assert result["folds"][0]["priorBranchComparison"]["train"]["sharedFeatureCountersEqual"]
    assert not result["folds"][0]["priorBranchComparison"]["train"]["fullCounterPayloadEquality"]
    record["localResearchArtifact"]["transformedValidationSha256"] = "different-matrix"
    result = finalizer._compare_provisional_preflight({"treatmentExecution": {"fittedFoldArtifacts": [record]}})
    assert result["status"] == "OBSERVED_DIFFERENCES_REQUIRE_REVIEW"
    assert result["matrixPayloadsReadForComparison"] == 0


def test_original_failed_markdown_is_byte_unchanged_when_existing_report_available():
    path = finalizer.OUTPUT_ROOT / "corrected-hgb-comparison-58bb89910289c8d38329b1b9e848934c382586dbd749ab37fba2a68a46210eae.json"
    if not path.is_file():
        pytest.skip("Original immutable local failure report is not present in this checkout.")
    report = json.loads(path.read_bytes())
    assert finalizer._report_markdown(report).encode("utf-8") == path.with_suffix(".md").read_bytes()


def test_finalizer_authenticates_actual_event_chain_without_mutating_or_fitting(monkeypatch):
    from server.sports_current_statcast import mlb_hgb_recovery_telemetry as telemetry

    study, study_path, _, _ = _recovery_fixture()
    event_path = (study_path.parent / "fit-events.jsonl").resolve()
    accounting_path = (study_path.parent / "fit-accounting.json").resolve()
    rows = []
    previous = None
    for event, fold in (("OBSERVER_INSTALLED", None), ("FIT_STARTED", 1),
                        ("FIT_COMPLETED", 1), ("FOLD_COMPLETED", 1),
                        ("FIT_STARTED", 2), ("FAILURE", 2), ("OBSERVER_CLOSED", None)):
        body = {"schemaVersion": telemetry.EVENT_SCHEMA, "sequence": len(rows) + 1,
                "previousEventSha256": previous, "recoveryId": study["recovery"]["recoveryId"],
                "event": event, "foldNumber": fold, "utc": "2026-09-07T00:00:00+00:00"}
        previous = finalizer.content_sha(body)
        rows.append({**body, "eventSha256": previous})
    files = {event_path: b"".join(canonical_json_bytes(row) + b"\n" for row in rows)}
    monkeypatch.setattr(Path, "read_bytes", lambda self: files[self.resolve()])
    monkeypatch.setattr(Path, "write_bytes", lambda *args, **kwargs: pytest.fail("Read-only finalization wrote an event log."))
    summary = telemetry.summarize_events(event_path)
    files[accounting_path] = canonical_json_bytes(summary)
    result, reference = finalizer._read_recovery_accounting(study, study_path=study_path)
    assert result["actualFitStarts"] == 2
    assert result["actualFitCompletions"] == result["completedFolds"] == 1
    assert result["status"] == "FAILED"
    assert reference["eventsSha256"] == hashlib.sha256(files[event_path]).hexdigest()
    # A separately valid summary checksum cannot substitute for reconciliation
    # with the underlying actual-event chain.
    altered = {key: value for key, value in summary.items() if key != "accountingChecksum"}
    altered["actualFitStarts"] = 5
    files[accounting_path] = canonical_json_bytes({**altered, "accountingChecksum": finalizer.content_sha(altered)})
    with pytest.raises(RuntimeError, match="does not reconcile"):
        finalizer._read_recovery_accounting(study, study_path=study_path)


def test_recovery_timing_uses_authenticated_utc_sequence_and_preserves_missing_milestones(monkeypatch):
    events = [{"event": "FIT_STARTED", "foldNumber": 1, "utc": "2026-09-07T01:00:00+00:00"},
              {"event": "FIT_COMPLETED", "foldNumber": 1, "utc": "2026-09-07T01:10:00+00:00"},
              {"event": "FOLD_COMPLETED", "foldNumber": 1, "utc": "2026-09-07T01:10:45.250000+00:00"},
              {"event": "FIT_STARTED", "foldNumber": 2, "utc": "2026-09-07T01:12:00+00:00"}]
    raw = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
    monkeypatch.setattr(Path, "read_bytes", lambda self: raw)
    accounting = {"eventPath": "synthetic.jsonl", "eventsSha256": hashlib.sha256(raw).hexdigest(),
                  "startedFoldNumbers": [1, 2], "fitCompletedFoldNumbers": [1], "completedFoldNumbers": [1]}
    timing = finalizer._recovery_event_timing(accounting)
    assert timing["folds"][0]["estimatorFitSeconds"] == 600
    assert timing["folds"][0]["postFitToFoldCompletionSeconds"] == 45.25
    assert timing["folds"][0]["fitStartUtc"] == events[0]["utc"]
    assert timing["folds"][1]["estimatorFitSeconds"] is None
    assert timing["folds"][1]["foldCompletedUtc"] is None
    assert "not pure reload time" in timing["caveat"]
    events[1]["utc"] = "2026-09-07T00:59:59+00:00"
    raw = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
    accounting["eventsSha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(RuntimeError, match="nondecreasing sequence"):
        finalizer._recovery_event_timing(accounting)
    events[1]["utc"] = "2026-09-07T01:10:00"
    raw = b"".join(canonical_json_bytes(event) + b"\n" for event in events)
    accounting["eventsSha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(RuntimeError, match="UTC timestamps"):
        finalizer._recovery_event_timing(accounting)


def test_recovery_terminal_elapsed_and_baseline_fold_runtimes_are_metadata_only(monkeypatch):
    study, study_path, _, _ = _recovery_fixture()
    study["studyChecksum"] = "study-sha"
    job = {"jobId": "recovery-job", "status": "COMPLETE"}
    accounting = {"actualFitStarts": 5}
    terminal = {"studyChecksum": "study-sha", "recoveryId": study["recovery"]["recoveryId"],
                **job, "actualFitAccounting": accounting, "recoveryRuntimeSeconds": 1200.5}
    monkeypatch.setattr(finalizer, "_recovery_event_timing", lambda value: {"folds": []})
    monkeypatch.setattr(finalizer, "baseline_authority", lambda: ({}, {"folds": [{"foldNumber": 1, "runtimeMs": 550123}]}, 1))
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    monkeypatch.setattr(Path, "read_bytes", lambda self: canonical_json_bytes(terminal))
    timing = finalizer._recovery_timing(study, job, accounting, study_path=study_path)
    assert timing["recoveryRuntimeSeconds"] == 1200.5
    assert timing["originalBaselineFoldRuntimes"]["folds"] == [{"foldNumber": 1, "runtimeMs": 550123}]
    terminal["recoveryRuntimeSeconds"] = -1
    with pytest.raises(RuntimeError, match="terminal timing does not reconcile"):
        finalizer._recovery_timing(study, job, accounting, study_path=study_path)
