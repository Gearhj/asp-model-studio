"""Read-only frozen V18 and historical preflight compatibility verifier.

No compilation, adoption, data scan, transform, fit, model load or OOT file
access occurs. Earlier provisional receipts retain their original identity.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "asp-mtlozhdx"
V18_ID = "stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638"
V18_SHA = "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3"
FEATURE_ID = "stage3-feature-set-486aefc6482f46ddac2bed94b210e05d"
SPLIT_ID = "stage3-split-contract-53bb07e31caa444b8246e260ba7761e0"
REGISTRATION_SHA = "7e43d29cdecd976465d26bddb30d4f5d67ec0b0d0d2e299981f1d87fef11172c"
PROVISIONAL_SHA = "48de9ecbe2932fedd33cbce401dc4478a00d5a41b4d327a4d14152764c41807c"
PREFLIGHT_SHAS = (
    "e4c4872d2438439ee6b4c8c7d730dd13b9eb7bc8c64b8aa2e54bc2449ec82e84",
    "19836b2464b48a1941af8f58061592d4693f39e8bf2f2643304d27083f9e4dc6",
    "e5bc9efadb8d39337b8a1cea0fa3200bda666d5c2e7662baba42012e56676548",
    "cdf6cda911e1a71323b3b783ac8cc0c1fd7de4b16e131d7dfee03a8ff08c280a",
    "8594d892090ae030ecf8e7ddebcd00e1d27c54d5f9fe430a91e67313b396ed07",
)
BOUND_FILES = frozenset({
    "stage3_feature_treatment_spec.py", "stage3_corrected_treatment_spec.py",
    "stage3_semantic_treatment.py", "stage3_corrected_prior_treatment.py",
    "stage3_corrected_eligibility.py", "stage3_corrected_preprocessing_artifacts.py",
    "stage3_model_laboratory.py",
})


class RecoveryAuthorityError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RecoveryAuthorityError(message)


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _without(value: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key not in keys}


def _cas(root: Path, digest: str) -> tuple[dict[str, Any], Path]:
    path = root / f"{digest}.json"
    raw = path.read_bytes()
    _require(hashlib.sha256(raw).hexdigest() == digest, f"CAS content mismatch: {path}")
    value = json.loads(raw)
    _require(isinstance(value, dict), f"CAS JSON is not an object: {path}")
    return value, path


def _source_hashes(repository_root: Path, expected: Mapping[str, str]) -> list[dict[str, Any]]:
    _require(set(expected) == BOUND_FILES, "V18 bound source inventory differs from the exact seven-file authority.")
    result = []
    for name in sorted(expected):
        path = repository_root / "server" / "sports_current_statcast" / name
        raw = path.read_bytes()
        normalized = hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest()
        _require(normalized == expected[name], f"Frozen V18 source changed: {name}")
        result.append({"filename": name, "path": str(path.resolve()), "manifestNormalizedLfSha256": expected[name],
                       "actualNormalizedLfSha256": normalized, "physicalSha256": hashlib.sha256(raw).hexdigest(), "match": True})
    return result


def _validate_registration(receipt: Mapping[str, Any]) -> None:
    treatment, feature, split = (receipt[key] for key in ("adoptedTreatment", "featureSet", "splitContract"))
    manifest = treatment["manifest"]
    _require(treatment.get("specificationId") == V18_ID and treatment.get("specificationVersion") == 18 and treatment.get("status") == "ADOPTED", "Exact adopted V18 identity required.")
    _require(treatment.get("manifestChecksum") == V18_SHA and _sha(manifest) == V18_SHA, "Frozen V18 manifest checksum mismatch.")
    _require(feature.get("featureSetId") == FEATURE_ID and feature.get("status") == "REGISTERED", "Exact registered V18 feature set required.")
    _require(split.get("contractId") == SPLIT_ID and split.get("status") == "REGISTERED", "Exact registered V18 split required.")
    _require(all(item.get("projectId") == PROJECT_ID for item in (treatment, feature, split)), "Cross-project authority is prohibited.")
    _require(all(item.get("finalOot", {}).get("locked") is True for item in (treatment, feature, split)), "Final OOT must remain sealed.")
    schema, contract = manifest["modelFeatureSchema"], feature["transformationContracts"]
    _require(_sha(_without(schema, "schemaChecksum")) == schema["schemaChecksum"], "Model schema checksum mismatch.")
    _require(len(schema["orderedFeatures"]) == len(set(schema["orderedFeatures"])) == 273, "Exactly273 unique model columns required.")
    _require(len(schema["sourceOrderedFeatures"]) == len(set(schema["sourceOrderedFeatures"])) == 218, "Exactly218 unique source columns required.")
    _require(schema["orderedFeatures"][:218] == schema["sourceOrderedFeatures"] and feature["orderedFeatures"] == schema["orderedFeatures"], "Model/source column identity or order changed.")
    _require(contract["sourceOrderedFeatures"] == schema["sourceOrderedFeatures"] and contract["modelFeatureSchemaChecksum"] == schema["schemaChecksum"] and contract["treatmentManifestChecksum"] == V18_SHA, "Feature contracts do not bind exact V18.")
    _require([item["feature"] for item in contract["ordered"]] == feature["orderedFeatures"], "Transformation ordering changed.")
    _require(contract["rowEligibilityPolicy"] == schema["rowEligibilityPolicy"], "Row eligibility policy differs from schema.")
    policy = schema["rowEligibilityPolicy"]
    _require(_sha(_without(policy, "policyChecksum")) == policy["policyChecksum"], "Row eligibility policy checksum mismatch.")
    _require(policy["expectedDevelopmentHeldRows"] == 56 and policy["expectedDevelopmentEligibleRows"] == 683606, "Frozen quarantine population changed.")
    excluded = manifest["correctedTreatment"]["preservedExcludedWorkbookFeatures"]
    _require(len(excluded) == 22 and not set(excluded) & set(schema["sourceOrderedFeatures"]), "Approved exclusions changed or became reachable.")
    _require(len(schema["wave1SourceFeatures"]) == 11 and len(schema["wave2SourceFeatures"]) == 10, "Prior feature families changed.")
    _require(split["selectedFeatureSetIds"] == [FEATURE_ID], "Split does not bind the exact feature set.")
    _require(treatment["development"] == feature["development"] == split["development"] and split["development"]["rows"] == 683662, "Registered source population changed.")
    _require(len(split["contract"]["folds"]) == 5, "Exactly five frozen chronological folds required.")


def _fold_payload(fold: Mapping[str, Any]) -> dict[str, Any]:
    return _without(fold, "checksum", "selectedFeatureSetIds")


def _compare_preflight(preflight: Mapping[str, Any], registration: Mapping[str, Any], index: int) -> dict[str, Any]:
    """Compare only evidence actually present; never infer fitted V18 identity."""
    schema = registration["adoptedTreatment"]["manifest"]["modelFeatureSchema"]
    fold = registration["splitContract"]["contract"]["folds"][index]
    eligibility = preflight["rowEligibility"]
    _require(preflight.get("scope") == "PREFLIGHT_PREPROCESSING_ONLY_NOT_A_MODEL_RUN" and preflight.get("status") == "PASS", "Preflight is not the recorded passing preprocessing-only check.")
    _require(preflight.get("predictiveFits") == 0 and preflight.get("finalOotRowsRead") == 0, "Preflight boundary assertions differ.")
    _require(_fold_payload(preflight["fold"]) == _fold_payload(fold), "Provisional preflight fold population/policies differ from V18.")
    _require(eligibility.get("featureSetId") == "UNREGISTERED_CORRECTED_PREFLIGHT_ONLY" and eligibility.get("treatmentManifestChecksum") == PROVISIONAL_SHA, "Provisional identity must remain unchanged, never relabeled V18.")
    _require(eligibility["modelFeatureSchemaChecksum"] == schema["schemaChecksum"] and eligibility["policyChecksum"] == schema["rowEligibilityPolicy"]["policyChecksum"], "Provisional model schema or row policy is incompatible with V18.")
    _require(_sha(_without(eligibility, "eligibilityChecksum")) == eligibility["eligibilityChecksum"], "Preflight row evidence checksum mismatch.")
    _require(eligibility["sourceRows"] == 683662 and eligibility["heldRows"] == 56 and eligibility["eligibleRows"] == 683606, "Provisional full-source coverage changed.")
    observations = eligibility["heldObservations"]
    keys = sorted(item["canonicalPaId"] for item in observations)
    expected_key_sha = schema["rowEligibilityPolicy"]["heldCanonicalPaIdNewlineChecksum"]
    _require(len(keys) == len(set(keys)) == 56 and hashlib.sha256(("\n".join(keys) + "\n").encode()).hexdigest() == expected_key_sha, "Provisional held immutable keys differ from frozen V18 policy.")
    held_train = sum(fold["trainStart"] <= item["gameDate"] <= fold["trainEnd"] for item in observations)
    held_valid = sum(fold["validationStart"] <= item["gameDate"] <= fold["validationEnd"] for item in observations)
    _require(preflight["modelTrainRows"] == fold["trainRows"] - held_train and preflight["modelValidationRows"] == fold["validationRows"] - held_valid, "Provisional eligible fold population differs.")
    validation = preflight["modelInputValidation"]
    _require(validation["status"] == "PASS" and validation["modelFeatureCount"] == 273 and validation["ordinaryFallbackRows"] == 0, "Model-input validation is incompatible.")
    for key in ("trainingBranchCounts", "validationBranchCounts", "modelInputValidation", "priorExecution"):
        item = preflight[key]
        _require(_sha(_without(item, "evidenceChecksum")) == item["evidenceChecksum"], f"Nested preflight evidence checksum mismatch: {key}")
        _require(item.get("finalOotRowsRead") == 0 and item.get("targetColumnsRead") == [], f"Target/OOT-free evidence absent: {key}")
    prior = preflight["priorExecution"]
    _require(prior["wave1Features"] == schema["wave1SourceFeatures"] and prior["wave2Features"] == schema["wave2SourceFeatures"] and prior["validationRowsUsedForFit"] == 0, "Prior scope/fit boundaries changed.")
    return {"foldNumber": index + 1, "status": "OBSERVABLE_CONTRACT_COMPATIBLE_NOT_FITTED_V18_EVIDENCE",
            "provisionalTreatmentManifestChecksum": PROVISIONAL_SHA, "v18TreatmentManifestChecksum": V18_SHA,
            "matchingModelSchemaChecksum": schema["schemaChecksum"], "matchingPolicyChecksum": eligibility["policyChecksum"],
            "foldDifferencePaths": [item["path"] for item in _difference_paths(preflight["fold"], fold)], "allOtherFoldFieldsEqual": True,
            "sourceTrainRows": fold["trainRows"], "sourceValidationRows": fold["validationRows"],
            "modelTrainRows": preflight["modelTrainRows"], "modelValidationRows": preflight["modelValidationRows"],
            "encodedColumns": preflight["transformedColumns"], "validationValuesSha256": preflight["validationValuesSha256"],
            "provisionalFittedSemanticChecksum": preflight["trainingBranchCounts"]["fittedChecksum"],
            "provisionalFittedPriorChecksum": prior["fittedTreatmentChecksum"],
            "fittedParametersRefit": False, "validationTransformReplayed": False}


def _difference_paths(left: Any, right: Any, prefix: str = "") -> list[dict[str, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        return [row for key in sorted(set(left) | set(right)) for row in _difference_paths(left.get(key), right.get(key), prefix + "/" + key)]
    return [] if left == right else [{"path": prefix, "before": left, "after": right}]


def verify_authority(database: Any, *, repository_root: Path = ROOT) -> dict[str, Any]:
    """Return auditable metadata or raise; database is Database.path or Path."""
    repository_root = Path(repository_root).resolve()
    intended_python = repository_root / ".venv" / "Scripts" / "python.exe"
    _require(Path(sys.executable).resolve() == intended_python.resolve(), "Run verifier using the intended project .venv Python.")
    database_path = Path(getattr(database, "path", database)).resolve()
    cas_root = repository_root / ".runtime" / "asp-model-studio" / "stage3-model-laboratory" / "objects" / "corrected-preprocessing" / "sha256"
    registration, registration_path = _cas(cas_root, REGISTRATION_SHA)
    _validate_registration(registration)
    manifest = registration["adoptedTreatment"]["manifest"]
    expected_hashes = manifest["correctedTreatment"]["implementationSourceSha256"]
    sources = _source_hashes(repository_root, expected_hashes)
    with sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        versions = [dict(row) for row in connection.execute("SELECT feature_treatment_spec_id,specification_version,specification_status,manifest_sha256,manifest_json,content_sha256 FROM stage3_feature_treatment_spec_versions WHERE project_id=? ORDER BY specification_version DESC", (PROJECT_ID,))]
        latest = next((row for row in versions if row["specification_status"] == "ADOPTED"), None)
        _require(latest is not None and latest["feature_treatment_spec_id"] == V18_ID and latest["manifest_sha256"] == V18_SHA, "Current adopted authority is not exact V18.")
        _require(not any(row["specification_status"] == "DRAFT" and row["specification_version"] > 18 for row in versions), "A newer unresolved draft exists.")
        _require(json.loads(latest["manifest_json"]) == manifest and latest["content_sha256"] == registration["adoptedTreatment"]["checksum"], "Database V18 differs from immutable registration receipt.")
        feature = connection.execute("SELECT * FROM stage3_feature_set_versions WHERE feature_set_id=?", (FEATURE_ID,)).fetchone()
        split = connection.execute("SELECT * FROM stage3_split_contract_versions WHERE split_contract_id=?", (SPLIT_ID,)).fetchone()
        _require(feature is not None and split is not None, "Registered V18 feature/split metadata absent.")
        _require(feature["feature_set_status"] == split["contract_status"] == "REGISTERED" and feature["content_sha256"] == registration["featureSet"]["checksum"] and split["content_sha256"] == registration["splitContract"]["checksum"], "Feature/split DB identity mismatch.")
        _require(json.loads(feature["ordered_features_json"]) == registration["featureSet"]["orderedFeatures"] and json.loads(feature["transformation_contracts_json"]) == registration["featureSet"]["transformationContracts"], "DB feature contents differ from frozen registration.")
        _require(json.loads(split["contract_json"]) == registration["splitContract"]["contract"], "DB split contents differ from frozen registration.")
    prior_manifest_rows = [row for row in versions if row["manifest_sha256"] == PROVISIONAL_SHA]
    provisional_code = json.loads(prior_manifest_rows[0]["manifest_json"])["correctedTreatment"]["implementationSourceSha256"] if prior_manifest_rows else None
    previous = next((json.loads(row["manifest_json"]) for row in versions if row["specification_version"] == 16), None)
    preflights = []
    for index, digest in enumerate(PREFLIGHT_SHAS):
        evidence, path = _cas(cas_root, digest)
        preflights.append({**_compare_preflight(evidence, registration, index), "receiptSha256": digest, "receiptPath": str(path), "receiptContentVerified": True})
    result = {
        "schemaVersion": "MLB_HGB_RECOVERY_AUTHORITY_VERIFICATION_V1", "status": "PASS_FROZEN_V18_AND_OBSERVABLE_PREFLIGHT_COMPATIBILITY",
        "projectId": PROJECT_ID, "treatmentSpecificationId": V18_ID, "treatmentVersion": 18, "treatmentManifestChecksum": V18_SHA,
        "featureSetId": FEATURE_ID, "featureSetChecksum": registration["featureSet"]["checksum"], "featureCount": 273, "sourceFeatureCount": 218,
        "splitContractId": SPLIT_ID, "splitChecksum": registration["splitContract"]["checksum"],
        "registrationReceipt": {"path": str(registration_path), "sha256": REGISTRATION_SHA, "verified": True},
        "pythonExecutable": str(Path(sys.executable).resolve()), "databaseAccess": "SQLITE_URI_MODE_RO_NO_RUNTIME_AUTHORITY_LOADING",
        "manifestSourceHashes": dict(expected_hashes), "sourceHashNormalization": "SHA256_AFTER_CRLF_TO_LF_ONLY_MATCHES_V18_COMPILER",
        "boundSourceHashes": {item["path"]: item["actualNormalizedLfSha256"] for item in sources},
        "boundSourceHashesPhysical": {item["path"]: item["physicalSha256"] for item in sources}, "sourceFiles": sources,
        "preservedV16ToV18ContentDifferences": _difference_paths(previous, manifest) if previous else None,
        "preflightCompatibility": preflights,
        "historicalProvisionalCodeEvidence": {"status": "RECOVERED_FROM_REGISTERED_MANIFEST" if provisional_code else "NOT_EMBEDDED_IN_RECEIPTS_OR_REGISTERED_HISTORY_NOT_PROVEN",
            "provisionalManifestChecksum": PROVISIONAL_SHA, "provisionalCodeHashes": provisional_code,
            "differenceFromV18": _difference_paths(provisional_code, expected_hashes) if provisional_code else None,
            "limitation": "Observable schema/policy/fold/evidence compatibility does not establish exact historical source-byte or fitted-parameter identity with V18. New V18 fitted-run evidence must retain its own identity."},
        "operations": {"databaseWrites": 0, "dataRowsRead": 0, "finalOotFilesOpened": 0, "priorFits": 0, "predictiveFits": 0, "modelLoads": 0, "transformsReplayed": 0},
    }
    return {**result, "verificationChecksum": _sha(result)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / ".runtime" / "asp-model-studio" / "persistence" / "asp_model_studio.db")
    args = parser.parse_args()
    print(json.dumps(verify_authority(args.database), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
