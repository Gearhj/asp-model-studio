from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from server.sports_current_statcast import stage3_executable_artifact as artifact
from server.sports_current_statcast import stage3_model_laboratory as lab


def project_chain(project_id):
    sha = lambda value: artifact._sha({"projectId": project_id, "value": value})
    folds = [{"foldNumber": n, "trainStart": "2024-01-01", "trainEnd": f"2024-01-0{n}", "trainRows": n, "trainGames": n,
        "validationStart": f"2024-01-0{n+1}", "validationEnd": f"2024-01-0{n+1}", "validationRows": 1, "validationGames": 1} for n in (1, 2, 3)]
    feature = {"featureSetId": project_id + "-feature", "checksum": sha("feature"), "orderedFeatures": ["alpha", "beta"]}
    policy = lambda kind: {"policyId": project_id + kind, "policyVersion": 2, "checksum": sha(kind)}
    resolved = SimpleNamespace(project_id=project_id, project_name=project_id, authority_key=sha("authority"),
        eda_authority=SimpleNamespace(source_dataset_id=project_id+"-dataset", source_manifest_sha=sha("source"), gold_manifest_sha=sha("gold"), contextual_manifest_sha=sha("context")),
        split={"contractId": project_id + "-split", "contractVersion": 2, "checksum": sha("split"), "contract": {"folds": folds},
            "development": {"startDate": "2024-01-01", "endDate": "2024-01-04", "rows": 4},
            "finalOot": {"startDate": "2024-01-05", "endDate": "2024-01-06", "rows": 2, "locked": True}},
        outlier_policy=policy("outlier"), missing_policy=policy("missing"))
    candidate = {"candidateId": project_id+"-attempt", "modelFamily": "xgboost", "featureSetId": feature["featureSetId"], "featureSetChecksum": feature["checksum"],
        "hyperparameters": {"nEstimators": 3}, "candidateSpecificationTemplateSha256": sha("template"), "durationSeconds": 0.5,
        "evaluationEvidence": {"oofPredictionEvidenceSha256": sha("oof")},
        "folds": [{**fold, "metrics": {"multiclassLogLoss": 0.25}} for fold in folds],
        **{key: 0.25 for key in artifact.EXPECTED_METRICS}}
    run = {"runId": project_id+"-run", "runReceiptSha256": sha("run"), "plan": {"projectId": project_id, "planId": project_id+"-plan", "checksum": sha("plan")},
        "environment": {"modelLabImplementationSha256": sha("implementation")}}
    chain = {"projectId": project_id, "resolvedAuthority": resolved, "sourceCandidate": candidate, "sourceRun": run,
        "experiment": {"seed": 42}, "featureSetContract": feature,
        **{key: project_id+"-"+key for key in artifact.EXPECTED_SELECTION},
        "candidateFingerprint": "stage3-candidate-spec-" + sha("fingerprint"), "candidateAttemptId": candidate["candidateId"], "candidateAttemptReceiptSha256": sha("attempt"),
        "candidateRunId": run["runId"], "candidateRunReceiptSha256": run["runReceiptSha256"]}
    run["identity"] = artifact._authority_payload(chain)
    return chain


def test_project_science_stays_separate_under_concurrent_resolution():
    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(executor.map(lambda n: artifact._accepted_science(project_chain(f"project-{n % 2}")), range(40)))
    assert {value["projectId"] for value in values} == {"project-0", "project-1"}
    for value in values:
        assert value["candidate"]["featureSetId"] == value["projectId"] + "-feature"
        assert value["selection"]["selectionDecisionId"].startswith(value["projectId"])
        assert len(value["folds"]) == 3 and value["oofRows"] == 3


@pytest.mark.parametrize("tamper", [None, "run-project", "plan-project", "candidate", "fold"])
def test_selected_project_chain_rejects_foreign_receipts(monkeypatch, tamper):
    chain = project_chain("project-a")
    monkeypatch.setattr(artifact, "candidate_specification_fingerprint", lambda *_: chain["candidateFingerprint"])
    if tamper == "run-project": chain["sourceRun"]["identity"]["projectId"] = "project-b"
    if tamper == "plan-project": chain["sourceRun"]["plan"]["projectId"] = "project-b"
    if tamper == "candidate": chain["sourceCandidate"]["featureSetChecksum"] = "f" * 64
    if tamper == "fold": chain["sourceCandidate"]["folds"][1]["trainEnd"] = "2024-01-04"
    if tamper:
        with pytest.raises(lab.Stage3ModelLaboratoryError): artifact._assert_exact_accepted_chain(chain)
    else: artifact._assert_exact_accepted_chain(chain)


def test_three_fold_project_plan_and_manifest_bind_exact_science(monkeypatch):
    chain = project_chain("project-b")
    monkeypatch.setattr(artifact, "_resolved_chain", lambda *_: chain)
    monkeypatch.setattr(artifact, "require_model_execution_authority", lambda *_: None)
    monkeypatch.setattr(artifact, "_production_environment", lambda c: {"acceptedCandidateRun": c["sourceRun"]["environment"]})
    plan = artifact.plan_executable_artifact(None, "project-b", {"nativeWorkers": 1}, actor_user_id="actor-b")["plan"]
    assert plan["workload"]["foldCount"] == 3
    assert plan["workload"]["modelFits"] == 4
    assert plan["workload"]["oofRows"] == 3 and plan["workload"]["finalFitRows"] == 4
    assert plan["executionActorUserId"] == "actor-b"
    evidence = artifact._fold_metric_reconciliation({"folds": chain["sourceCandidate"]["folds"]}, chain)
    assert len(evidence) == 3 and all(fold["status"] == "PASS" for fold in evidence)
    manifest = {**{key: deepcopy(plan[key]) for key in ("projectId", "authority", "selection", "candidate", "acceptedScience", "acceptedScienceSha256", "environment")},
        "orderedFeatures": ["alpha", "beta"], "targetOrder": list(artifact.GOLD_CLASS_ORDER), "probabilityContract": artifact._probability_contract(),
        "training": {"scope": "DEVELOPMENT_ONLY", "rows": 4, "startDate": "2024-01-01", "cutoff": "2024-01-04", "seed": 42, "finalOotRowsUsed": 0, "finalOotTargetAccessed": False},
        "oof": {"scope": "CHRONOLOGICAL_DEVELOPMENT_ONLY", "rows": 3, "foldCount": 3, "legacyEvidenceSha256": plan["candidate"]["acceptedOofEvidenceSha256"], "folds": evidence},
        "verification": {"status": "PASS", "metricReproduction": {"status": "PASS"}, "rawOofProbabilityValidation": artifact._raw_probability_diagnostics(np.full((3, 8), 0.125)),
            "reloadVerification": {"status": "PASS", "freshProcess": True}, "verificationFixture": {"status": "PASS"}}, "safety": artifact._safety_payload()}
    artifact._validate_manifest_authority(manifest)
    copied = deepcopy(manifest); copied["projectId"] = "project-a"
    with pytest.raises(lab.Stage3ModelLaboratoryError): artifact._validate_manifest_authority(copied)
    altered = deepcopy(manifest); altered["acceptedScience"]["split"]["checksum"] = "a" * 64
    with pytest.raises(lab.Stage3ModelLaboratoryError): artifact._validate_manifest_authority(altered)
