"""Synthetic-only checks of the metadata verifier; no dataset or model reads."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from scripts import verify_mlb_hgb_recovery_authority as verifier


def signed(value, field="evidenceChecksum"):
    return {**value, field: verifier._sha(value)}


def fixture_authorities():
    source = [f"source_{index}" for index in range(218)]
    ordered = source + [f"derived_{index}" for index in range(55)]
    observations = [{"canonicalPaId": f"pa-{index:03d}", "gameDate": "2024-01-01" if index < 5 else "2025-01-01"} for index in range(56)]
    held_sha = hashlib.sha256(("\n".join(item["canonicalPaId"] for item in observations) + "\n").encode()).hexdigest()
    policy = signed({"expectedDevelopmentHeldRows": 56, "expectedDevelopmentEligibleRows": 683606,
                     "heldCanonicalPaIdNewlineChecksum": held_sha}, "policyChecksum")
    schema = signed({"orderedFeatures": ordered, "sourceOrderedFeatures": source,
                     "wave1SourceFeatures": source[:11], "wave2SourceFeatures": source[11:21],
                     "rowEligibilityPolicy": policy}, "schemaChecksum")
    manifest = {"modelFeatureSchema": schema, "correctedTreatment": {
        "preservedExcludedWorkbookFeatures": [f"excluded_{index}" for index in range(22)],
        "implementationSourceSha256": {"example.py": hashlib.sha256(b"x = 1\n").hexdigest()}}}
    manifest_sha = verifier._sha(manifest)
    shared = {"projectId": verifier.PROJECT_ID, "finalOot": {"locked": True}, "development": {"rows": 683662}}
    fold = {"trainStart": "2024-01-01", "trainEnd": "2024-12-31", "validationStart": "2025-01-01",
            "validationEnd": "2025-12-31", "trainRows": 182072, "validationRows": 99782,
            "selectedFeatureSetIds": [verifier.FEATURE_ID], "checksum": "registered-fold"}
    contract = {"sourceOrderedFeatures": source, "modelFeatureSchemaChecksum": schema["schemaChecksum"],
                "treatmentManifestChecksum": manifest_sha, "ordered": [{"feature": name} for name in ordered],
                "rowEligibilityPolicy": policy}
    registration = {
        "adoptedTreatment": {**shared, "specificationId": verifier.V18_ID, "specificationVersion": 18, "status": "ADOPTED",
                              "manifestChecksum": manifest_sha, "manifest": manifest, "checksum": "treatment-content"},
        "featureSet": {**shared, "featureSetId": verifier.FEATURE_ID, "status": "REGISTERED", "orderedFeatures": ordered,
                       "transformationContracts": contract, "checksum": "feature-content"},
        "splitContract": {**shared, "contractId": verifier.SPLIT_ID, "status": "REGISTERED",
                          "selectedFeatureSetIds": [verifier.FEATURE_ID], "contract": {"folds": [copy.deepcopy(fold) for _ in range(5)]},
                          "checksum": "split-content"},
    }
    base_evidence = {"targetColumnsRead": [], "finalOotRowsRead": 0}
    eligibility = signed({"featureSetId": "UNREGISTERED_CORRECTED_PREFLIGHT_ONLY", "treatmentManifestChecksum": verifier.PROVISIONAL_SHA,
                          "modelFeatureSchemaChecksum": schema["schemaChecksum"], "policyChecksum": policy["policyChecksum"],
                          "sourceRows": 683662, "heldRows": 56, "eligibleRows": 683606, "heldObservations": observations}, "eligibilityChecksum")
    preflight = {"scope": "PREFLIGHT_PREPROCESSING_ONLY_NOT_A_MODEL_RUN", "status": "PASS", "predictiveFits": 0,
                 "finalOotRowsRead": 0, "fold": {**fold, "selectedFeatureSetIds": ["UNREGISTERED_CORRECTED_PREFLIGHT_ONLY"], "checksum": "provisional-fold"},
                 "rowEligibility": eligibility, "modelTrainRows": 182067, "modelValidationRows": 99731, "transformedColumns": 432,
                 "validationValuesSha256": "synthetic-validation-values",
                 "trainingBranchCounts": signed({**base_evidence, "fittedChecksum": "provisional-semantic"}),
                 "validationBranchCounts": signed(base_evidence),
                 "modelInputValidation": signed({**base_evidence, "status": "PASS", "modelFeatureCount": 273, "ordinaryFallbackRows": 0}),
                 "priorExecution": signed({**base_evidence, "wave1Features": source[:11], "wave2Features": source[11:21],
                                           "validationRowsUsedForFit": 0, "fittedTreatmentChecksum": "provisional-prior"})}
    return registration, preflight


def test_source_hash_normalization_keeps_physical_hash_separate(tmp_path, monkeypatch):
    monkeypatch.setattr(verifier, "BOUND_FILES", frozenset({"example.py"}))
    source = tmp_path / "server" / "sports_current_statcast" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x = 1\r\n")
    expected = hashlib.sha256(b"x = 1\n").hexdigest()
    evidence = verifier._source_hashes(tmp_path, {"example.py": expected})[0]
    assert evidence["actualNormalizedLfSha256"] == expected
    assert evidence["physicalSha256"] == hashlib.sha256(b"x = 1\r\n").hexdigest()
    assert evidence["physicalSha256"] != expected
    source.write_bytes(b"x = 2\r\n")
    with pytest.raises(verifier.RecoveryAuthorityError, match="source changed"):
        verifier._source_hashes(tmp_path, {"example.py": expected})


def test_exact_registration_checks(monkeypatch):
    registration, _ = fixture_authorities()
    monkeypatch.setattr(verifier, "V18_SHA", registration["adoptedTreatment"]["manifestChecksum"])
    verifier._validate_registration(registration)
    registration["featureSet"]["finalOot"]["locked"] = False
    with pytest.raises(verifier.RecoveryAuthorityError, match="remain sealed"):
        verifier._validate_registration(registration)


def test_compatible_preflight_preserves_provisional_identity():
    registration, preflight = fixture_authorities()
    original = copy.deepcopy(preflight)
    evidence = verifier._compare_preflight(preflight, registration, 0)
    assert evidence["status"] == "OBSERVABLE_CONTRACT_COMPATIBLE_NOT_FITTED_V18_EVIDENCE"
    assert evidence["foldDifferencePaths"] == ["/checksum", "/selectedFeatureSetIds"]
    assert evidence["provisionalTreatmentManifestChecksum"] == verifier.PROVISIONAL_SHA
    assert evidence["fittedParametersRefit"] is False
    assert preflight == original


@pytest.mark.parametrize("failure", ["fold", "identity", "policy", "held_key", "population", "target", "prior_fit", "nested_checksum"])
def test_preflight_fails_closed_for_incompatibility(failure):
    registration, preflight = fixture_authorities()
    if failure == "fold":
        preflight["fold"]["trainStart"] = "2023-01-01"
    elif failure == "identity":
        preflight["rowEligibility"]["treatmentManifestChecksum"] = verifier.V18_SHA
    elif failure == "policy":
        preflight["rowEligibility"]["policyChecksum"] = "different-policy"
    elif failure == "held_key":
        preflight["rowEligibility"]["heldObservations"][0]["canonicalPaId"] = "changed-key"
        preflight["rowEligibility"] = signed(verifier._without(preflight["rowEligibility"], "eligibilityChecksum"), "eligibilityChecksum")
    elif failure == "population":
        preflight["modelTrainRows"] += 1
    elif failure == "target":
        preflight["priorExecution"]["targetColumnsRead"] = ["target"]
        preflight["priorExecution"] = signed(verifier._without(preflight["priorExecution"], "evidenceChecksum"))
    elif failure == "prior_fit":
        preflight["priorExecution"]["validationRowsUsedForFit"] = 1
        preflight["priorExecution"] = signed(verifier._without(preflight["priorExecution"], "evidenceChecksum"))
    else:
        preflight["trainingBranchCounts"]["fittedChecksum"] = "tampered"
    with pytest.raises(verifier.RecoveryAuthorityError):
        verifier._compare_preflight(preflight, registration, 0)


def test_content_addressed_receipts_fail_on_tampering(tmp_path):
    raw = b'{"status":"PASS"}'
    digest = hashlib.sha256(raw).hexdigest()
    path = tmp_path / f"{digest}.json"
    path.write_bytes(raw)
    assert verifier._cas(tmp_path, digest)[0] == {"status": "PASS"}
    path.write_bytes(b'{"status":"FAIL"}')
    with pytest.raises(verifier.RecoveryAuthorityError, match="CAS content mismatch"):
        verifier._cas(tmp_path, digest)


def test_full_verifier_is_read_only_and_exposes_history_limit(tmp_path, monkeypatch):
    registration, preflight = fixture_authorities()
    monkeypatch.setattr(verifier, "V18_SHA", registration["adoptedTreatment"]["manifestChecksum"])
    monkeypatch.setattr(verifier, "BOUND_FILES", frozenset({"example.py"}))
    monkeypatch.setattr(verifier.sys, "executable", str(tmp_path / ".venv" / "Scripts" / "python.exe"))
    source = tmp_path / "server" / "sports_current_statcast" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"x = 1\n")
    cas_root = tmp_path / ".runtime" / "asp-model-studio" / "stage3-model-laboratory" / "objects" / "corrected-preprocessing" / "sha256"
    cas_root.mkdir(parents=True)

    def store(value):
        raw = json.dumps(value, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()
        (cas_root / f"{digest}.json").write_bytes(raw)
        return digest

    monkeypatch.setattr(verifier, "REGISTRATION_SHA", store(registration))
    monkeypatch.setattr(verifier, "PREFLIGHT_SHAS", tuple(store(preflight) for _ in range(5)))
    database = tmp_path / "metadata.sqlite3"
    treatment, feature, split = (registration[key] for key in ("adoptedTreatment", "featureSet", "splitContract"))
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE stage3_feature_treatment_spec_versions (project_id,feature_treatment_spec_id,specification_version,specification_status,manifest_sha256,manifest_json,content_sha256)")
        connection.execute("INSERT INTO stage3_feature_treatment_spec_versions VALUES (?,?,?,?,?,?,?)", (verifier.PROJECT_ID, verifier.V18_ID, 18, "ADOPTED", verifier.V18_SHA, json.dumps(treatment["manifest"]), treatment["checksum"]))
        connection.execute("CREATE TABLE stage3_feature_set_versions (feature_set_id,feature_set_status,content_sha256,ordered_features_json,transformation_contracts_json)")
        connection.execute("INSERT INTO stage3_feature_set_versions VALUES (?,?,?,?,?)", (verifier.FEATURE_ID, "REGISTERED", feature["checksum"], json.dumps(feature["orderedFeatures"]), json.dumps(feature["transformationContracts"])))
        connection.execute("CREATE TABLE stage3_split_contract_versions (split_contract_id,contract_status,content_sha256,contract_json)")
        connection.execute("INSERT INTO stage3_split_contract_versions VALUES (?,?,?,?)", (verifier.SPLIT_ID, "REGISTERED", split["checksum"], json.dumps(split["contract"])))
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    evidence = verifier.verify_authority(database, repository_root=tmp_path)
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert set(evidence["operations"].values()) == {0}
    assert evidence["historicalProvisionalCodeEvidence"]["provisionalCodeHashes"] is None
    assert evidence["historicalProvisionalCodeEvidence"]["status"].endswith("NOT_PROVEN")
    assert len(evidence["preflightCompatibility"]) == 5
    assert evidence["verificationChecksum"] == verifier._sha(verifier._without(evidence, "verificationChecksum"))
    assert evidence["boundSourceHashesPhysical"] == evidence["boundSourceHashes"]
