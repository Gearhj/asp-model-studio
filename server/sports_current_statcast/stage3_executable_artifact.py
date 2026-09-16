"""Transactional executable artifact production for the Stage 3 challenger.

This module is intentionally research-only.  It resolves the existing current
challenger chain, reproduces its five chronological development folds, captures
row-level OOF probabilities and fitted fold pipelines, and only then fits a
final development-through-cutoff pipeline.  Publication is immutable and
content addressed outside Git.  No code path reads final OOT, calls a provider,
creates a generic-registry champion, or promotes a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import joblib
import numpy as np
import pandas as pd

from ..persistence.db import Database, json_loads, now_iso
from ..persistence.repositories.run_repository import RunRepository
from ..sports_cockpit.interprocess_lock import LockBusy, interprocess_lock
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_gold.contracts import GOLD_CLASS_ORDER
from .stage3_candidate_evaluation import (
    candidate_specification_fingerprint,
    resolve_current_research_challenger,
)
from .stage3_model_laboratory import (
    project_read_view,
    require_model_execution_authority,
    EXPECTED_DEVELOPMENT,
    EXPECTED_FINAL_OOT,
    EXPECTED_FOLDS,
    EXPECTED_GOLD_MANIFEST_SHA,
    EXPECTED_MISSING_POLICY,
    EXPECTED_OUTLIER_POLICY,
    EXPECTED_SOURCE_DATASET_ID,
    EXPECTED_SPLIT,
    RAW_PROBABILITY_ROW_SUM_ATOL,
    RAW_PROBABILITY_ROW_SUM_RTOL,
    Stage3FittedPipeline,
    Stage3ModelLaboratoryError,
    _bounded_native_workers,
    _evaluate_candidate,
    _environment_identity,
    _fold_frame,
    _metrics,
    _validate_probability_matrix,
    fit_stage3_pipeline,
)


EXECUTABLE_ARTIFACT_SUMMARY_SCHEMA_VERSION = (
    "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_SUMMARY_V1"
)
EXECUTABLE_ARTIFACT_PLAN_SCHEMA_VERSION = "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_PLAN_V1"
EXECUTABLE_ARTIFACT_JOB_SCHEMA_VERSION = "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_JOB_V1"
EXECUTABLE_ARTIFACT_MANIFEST_SCHEMA_VERSION = (
    "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_MANIFEST_V1"
)
EXECUTABLE_ARTIFACT_VERIFICATION_SCHEMA_VERSION = (
    "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_VERIFICATION_V1"
)
EXECUTABLE_ARTIFACT_RECOVERY_SCHEMA_VERSION = (
    "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_PUBLICATION_RECOVERY_V1"
)
EXECUTABLE_ARTIFACT_JOB_TYPE = "sports_stage3_executable_artifact"

EXPECTED_SELECTION = {
    "finalistSelectionId": "stage3-finalist-selection-634c2b48c4224a23878d5dc07b10afe8",
    "calibrationDecisionId": "stage3-calibration-decision-83a7738b83d149859517099b361b6b62",
    "gameEvaluationDecisionId": "stage3-game-evaluation-decision-59c8d32c50ef41f78a224ccb9773ed40",
    "selectionDecisionId": "stage3-challenger-decision-8c0c7211d9c64466b95af9607ca3376c",
    "researchHandoffId": "stage3-research-handoff-e9c5ac58b8414b15ac90eb50ce5ca50d",
    "registryEntryId": "stage3-research-challenger-94c31d6992a84b70aa5827e4cf81da05",
}
EXPECTED_CANDIDATE = {
    "candidateFingerprint": "stage3-candidate-spec-1348285dbc6b9afb0445f0c26953564675c2afb4a4d838aff913314d85e71138",
    "candidateAttemptId": "stage3-candidate-5b7841353fa24b22ae669b104b0afb20",
    "candidateAttemptReceiptSha256": "89487692000cd909361207ac0ffcd3f12b3a8e3dda4d9a80163a6420b1f24d85",
    "candidateRunId": "stage3-model-development-run-9dcba47415584a38ae6e2c1437e69472",
    "candidateRunReceiptSha256": "932211b901ed8cee25b95f4fb7a05c2a207e222719c81e83fc03490213441553",
    "candidateSpecificationTemplateSha256": "6db20983d532300c678550ff0284b855881f9d64b097136b25cc1f5da5a19d14",
    "featureSetId": "stage3-full-eligible-modeling-set-7fcc655c652527df723d581771db56b1",
    "featureSetChecksum": "7fcc655c652527df723d581771db56b18c0c46bb9cb71000048d80b0da4230d8",
    "featureCount": 234,
    "modelFamily": "xgboost",
    "seed": 20_260_901,
}
EXPECTED_SOURCE_PLAN = {
    "planId": "stage3-model-plan-bd825cfc9e5500c915e53c184ef32c7a",
    "checksum": "bd825cfc9e5500c915e53c184ef32c7a7b9e2c05fbd480571e376127522a7eff",
}
EXPECTED_OOF_EVIDENCE_SHA256 = (
    "9a93f4ef963ae2fdbe5eb25f5115a2f47dcff5428ef85e6627a9a00d0655410f"
)
EXPECTED_MODEL_LAB_IMPLEMENTATION_SHA256 = (
    "af10a7aba685b13da9526c037bfb086c081ff1938ffd4c6c9ef90e54ae474ed2"
)
EXPECTED_HYPERPARAMETERS = {
    "n_estimators": 300,
    "learning_rate": 0.07,
    "max_depth": 5,
    "min_child_weight": 1,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "gamma": 0,
    "reg_alpha": 0,
    "reg_lambda": 1,
}
EXPECTED_METRICS = {
    "meanOofLogLoss": 1.4733228988634295,
    "summedBrier": 0.7028251466344105,
    "ece": 0.004070499756391157,
    "accuracyDiagnostic": 0.45518251958771105,
    "macroF1Diagnostic": 0.09161553252322863,
}
EXPECTED_FOLD_LOG_LOSSES = (
    1.47792803270595,
    1.47857679907364,
    1.46561754968370,
    1.47411153989114,
    1.47040854089790,
)
EXPECTED_OOF_ROWS = 501_590
EXPECTED_SOURCE_MANIFEST_SHA256 = (
    "03ca6dab30e760b2b86b65308090c2d358a67127cc34dfde7a75fc198c3ba84c"
)
EXPECTED_CONTEXTUAL_MANIFEST_SHA256 = (
    "4c228116951a3505d6a5d955f00cd2b92b35b1ccb85c7c69d11d77828485320e"
)
_PROBABILITY_ATOL = 1e-8
_METRIC_ATOL = 1e-12
_ACTIVE_STATUSES = {"QUEUED", "RUNNING", "CANCEL_REQUESTED"}
_TERMINAL_STATUSES = {"COMPLETE", "FAILED", "CANCELLED", "INTERRUPTED"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_TRANSIENT_PUBLICATION_ERRORS = {5, 32, 33}
_PUBLICATION_RETRY_ATTEMPTS = 12
_PUBLICATION_RETRY_INITIAL_DELAY_SECONDS = 0.05
_PUBLICATION_RETRY_MAX_DELAY_SECONDS = 1.0
_ATOMIC_DIRECTORY_RENAME_PROTOCOL = "ATOMIC_DIRECTORY_RENAME_V1"
_MANIFEST_COMMIT_PROTOCOL = "MANIFEST_COMMIT_V1"
_VERIFIED_EXISTING_TARGET_PROTOCOL = "VERIFIED_EXISTING_TARGET_V1"
_MANIFEST_COMMIT_TEMP_TAG = ".stage3-manifest-commit-"
_FORBIDDEN_PLAN_KEYS = {
    "candidateFingerprint",
    "candidateAttemptId",
    "featureSetId",
    "features",
    "orderedFeatures",
    "folds",
    "hyperparameters",
    "seed",
    "targetOrder",
    "split",
    "gold",
    "outlierPolicy",
    "missingPolicy",
    "finalOot",
    "holdout",
    "promote",
    "champion",
    "provider",
}

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage3-executable-artifact")
_SUBMISSION_GUARD = threading.Lock()
_FUTURES_GUARD = threading.Lock()
_COORDINATOR_INSTANCE_ID = f"{os.getpid()}-{uuid.uuid4().hex}"
_FUTURES: dict[str, Future[None]] = {}
_SYNCHRONOUS_RECOVERY_JOBS: set[str] = set()


def _artifact_root() -> Path:
    configured = os.getenv("ATLAS_STAGE3_EXECUTABLE_ARTIFACT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path(__file__).resolve().parents[2]
        / ".runtime"
        / "asp-model-studio"
        / "stage3-executable-artifacts"
    )


def _sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _contained(path: Path, root: Path | None = None) -> bool:
    base = (root or _artifact_root()).resolve()
    try:
        path.resolve().relative_to(base)
        return True
    except (OSError, ValueError):
        return False


def _require_contained(path: Path, root: Path | None = None) -> Path:
    resolved = path.resolve()
    if not _contained(resolved, root):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PATH_OUTSIDE_ROOT",
            "The artifact path escapes the configured Stage 3 artifact root.",
            status_code=409,
        )
    return resolved


def _atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _atomic_bytes(path, canonical_json_bytes(dict(value)))


def _atomic_joblib(path: Path, value: Any) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=path.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        joblib.dump(value, temporary, compress=3)
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _file_record(path, path.parent.parent if path.parent.name == "fold-models" else path.parent)


def _file_record(path: Path, relative_root: Path) -> dict[str, Any]:
    return {
        "relativePath": path.relative_to(relative_root).as_posix(),
        "sha256": _sha_file(path),
        "sizeBytes": int(path.stat().st_size),
    }


def _authority_payload(chain: Mapping[str, Any]) -> dict[str, Any]:
    resolved = chain["resolvedAuthority"]
    eda_authority = resolved.eda_authority
    return {
        "projectId": chain["projectId"],
        "projectName": resolved.project_name,
        "sourceDatasetId": eda_authority.source_dataset_id,
        "sourceManifestSha": eda_authority.source_manifest_sha,
        "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
        "goldManifestSha": eda_authority.gold_manifest_sha,
        "contextualManifestSha": eda_authority.contextual_manifest_sha,
        "authorityKey": resolved.authority_key,
        "splitContractId": resolved.split["contractId"],
        "splitVersion": int(resolved.split["contractVersion"]),
        "splitChecksum": resolved.split["checksum"],
        "outlierPolicyId": resolved.outlier_policy["policyId"],
        "outlierPolicyVersion": int(resolved.outlier_policy["policyVersion"]),
        "outlierPolicyChecksum": resolved.outlier_policy["checksum"],
        "missingPolicyId": resolved.missing_policy["policyId"],
        "missingPolicyVersion": int(resolved.missing_policy["policyVersion"]),
        "missingPolicyChecksum": resolved.missing_policy["checksum"],
        "targetOrder": list(GOLD_CLASS_ORDER),
        "developmentRows": resolved.split["development"]["rows"],
        "developmentStart": resolved.split["development"]["startDate"],
        "developmentEnd": resolved.split["development"]["endDate"],
        "finalOotRows": resolved.split["finalOot"]["rows"],
        "finalOotStart": resolved.split["finalOot"]["startDate"],
        "finalOotEnd": resolved.split["finalOot"]["endDate"],
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
    }


def _selection_payload(chain: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **{key: chain.get(key) for key in EXPECTED_SELECTION},
        "candidateFingerprint": chain.get("candidateFingerprint"),
        "candidateAttemptId": chain.get("candidateAttemptId"),
        "candidateAttemptReceiptSha256": chain.get(
            "candidateAttemptReceiptSha256"
        ),
        "candidateRunId": chain.get("candidateRunId"),
        "candidateRunReceiptSha256": chain.get("candidateRunReceiptSha256"),
        "modelStatus": "RESEARCH_CHALLENGER",
        "promotionStatus": "NOT_PROMOTED",
    }


def _safety_payload() -> dict[str, Any]:
    return {
        "modelStatus": "RESEARCH_CHALLENGER",
        "promotionStatus": "NOT_PROMOTED",
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "providerCalls": 0,
        "modelsPromoted": 0,
        "championsMutated": 0,
    }


def _probability_contract() -> dict[str, Any]:
    return {
        "schemaVersion": "SPORTS_STAGE3_PROBABILITY_CONTRACT_V1",
        "rawOof": {
            "representation": "CLASS_ALIGNED_ESTIMATOR_VALUES_AS_FLOAT64",
            "normalizationApplied": False,
            "rowSumValidation": {
                "rtol": RAW_PROBABILITY_ROW_SUM_RTOL,
                "atol": RAW_PROBABILITY_ROW_SUM_ATOL,
            },
            "scientificUse": "ACCEPTED_METRICS_AND_LEGACY_OOF_DIGEST",
        },
        "executable": {
            "representation": "CLASS_ALIGNED_FLOAT64",
            "rawValidationBeforeNormalization": True,
            "normalization": (
                "DIVIDE_BY_RAW_ROW_SUM_THEN_DETERMINISTIC_FLOAT64_RESIDUAL_CORRECTION"
            ),
            "exactRowSum": 1.0,
            "scientificEvidenceMutated": False,
        },
    }


def _raw_probability_diagnostics(probabilities: Any) -> dict[str, Any]:
    values = np.asarray(probabilities, dtype=np.float64)
    row_sums = values.sum(axis=1, dtype=np.float64)
    return {
        "status": "PASS",
        "rows": int(values.shape[0]),
        "columns": int(values.shape[1]),
        "representation": "FLOAT64_PRESERVING_RAW_ESTIMATOR_VALUES",
        "minimumProbability": float(np.min(values)),
        "maximumProbability": float(np.max(values)),
        "minimumRowSum": float(np.min(row_sums)),
        "maximumRowSum": float(np.max(row_sums)),
        "maximumAbsoluteRowSumDeviation": float(
            np.max(np.abs(row_sums - 1.0))
        ),
        "rowSumRtol": RAW_PROBABILITY_ROW_SUM_RTOL,
        "rowSumAtol": RAW_PROBABILITY_ROW_SUM_ATOL,
        "normalizationApplied": False,
    }


def _valid_raw_probability_diagnostics(
    value: Any, *, expected_rows: int
) -> bool:
    if not isinstance(value, Mapping):
        return False
    try:
        minimum = float(value["minimumProbability"])
        maximum = float(value["maximumProbability"])
        minimum_sum = float(value["minimumRowSum"])
        maximum_sum = float(value["maximumRowSum"])
        maximum_deviation = float(value["maximumAbsoluteRowSumDeviation"])
        rtol = float(value["rowSumRtol"])
        atol = float(value["rowSumAtol"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return False
    expected_maximum_deviation = max(
        abs(minimum_sum - 1.0), abs(maximum_sum - 1.0)
    )
    return bool(
        value.get("status") == "PASS"
        and value.get("rows") == expected_rows
        and value.get("columns") == len(GOLD_CLASS_ORDER)
        and value.get("representation")
        == "FLOAT64_PRESERVING_RAW_ESTIMATOR_VALUES"
        and value.get("normalizationApplied") is False
        and all(
            np.isfinite(number)
            for number in (
                minimum,
                maximum,
                minimum_sum,
                maximum_sum,
                maximum_deviation,
                rtol,
                atol,
            )
        )
        and minimum >= 0.0
        and maximum <= 1.0
        and minimum <= maximum
        and minimum_sum <= maximum_sum
        and maximum_deviation >= 0.0
        and rtol == RAW_PROBABILITY_ROW_SUM_RTOL
        and atol == RAW_PROBABILITY_ROW_SUM_ATOL
        and minimum_sum >= 1.0 - RAW_PROBABILITY_ROW_SUM_ATOL
        and maximum_sum <= 1.0 + RAW_PROBABILITY_ROW_SUM_ATOL
        and maximum_deviation <= RAW_PROBABILITY_ROW_SUM_ATOL
        and np.isclose(
            maximum_deviation,
            expected_maximum_deviation,
            rtol=0.0,
            atol=np.finfo(float).eps,
        )
    )


def _production_environment(chain: Mapping[str, Any]) -> dict[str, Any]:
    current = _environment_identity()
    return {
        "acceptedCandidateRun": dict(chain["sourceRun"].get("environment") or {}),
        "artifactProduction": {
            **current,
            "artifactImplementationSha256": _sha_file(Path(__file__)),
        },
    }



def _accepted_science(chain: Mapping[str, Any]) -> dict[str, Any]:
    """Derive reproducible science only from this project's verified selected receipt."""
    resolved = chain["resolvedAuthority"]
    source = chain["sourceCandidate"]
    run = chain["sourceRun"]
    experiment = chain["experiment"]
    feature = chain["featureSetContract"]
    folds = list((resolved.split.get("contract") or {}).get("folds") or [])
    source_folds = list(source.get("folds") or [])
    keys = ("foldNumber", "trainStart", "trainEnd", "trainRows", "trainGames",
        "validationStart", "validationEnd", "validationRows", "validationGames")
    if not folds or len(folds) != len(source_folds) or any(
        any(left.get(key) != right.get(key) for key in keys)
        for left, right in zip(folds, source_folds, strict=True)):
        raise Stage3ModelLaboratoryError("STAGE3_EXECUTABLE_ARTIFACT_ACCEPTED_AUTHORITY_MISMATCH", "The selected candidate does not preserve this project's registered fold boundaries.", status_code=409)
    dev = resolved.split["development"]
    oot = resolved.split["finalOot"]
    return {
        "schemaVersion": "PROJECT_SELECTED_EXECUTABLE_SCIENCE_V1",
        "projectId": chain["projectId"],
        "selection": {key: chain.get(key) for key in EXPECTED_SELECTION},
        "candidate": {**{key: chain.get(key) for key in ("candidateFingerprint", "candidateAttemptId", "candidateAttemptReceiptSha256", "candidateRunId", "candidateRunReceiptSha256")},
            "modelFamily": source.get("modelFamily"), "featureSetId": feature.get("featureSetId"),
            "featureSetChecksum": feature.get("checksum"), "featureCount": len(feature.get("orderedFeatures") or []),
            "seed": experiment.get("seed"), "candidateSpecificationTemplateSha256": source.get("candidateSpecificationTemplateSha256")},
        "sourceDatasetId": resolved.eda_authority.source_dataset_id,
        "sourceManifestSha": resolved.eda_authority.source_manifest_sha,
        "goldManifestSha": resolved.eda_authority.gold_manifest_sha,
        "contextualManifestSha": resolved.eda_authority.contextual_manifest_sha,
        "split": {"splitContractId": resolved.split["contractId"], "version": resolved.split["contractVersion"], "checksum": resolved.split["checksum"]},
        "outlierPolicy": {key: resolved.outlier_policy.get(key) for key in ("policyId", "policyVersion", "checksum")},
        "missingPolicy": {key: resolved.missing_policy.get(key) for key in ("policyId", "policyVersion", "checksum")},
        "development": [dev["startDate"], dev["endDate"], dev["rows"]],
        "finalOot": [oot["startDate"], oot["endDate"], oot["rows"]],
        "folds": [[item[key] for key in keys] for item in folds],
        "foldLogLosses": [(item.get("metrics") or {}).get("multiclassLogLoss") for item in source_folds],
        "hyperparameters": dict(source.get("hyperparameters") or {}),
        "oofEvidenceSha256": (source.get("evaluationEvidence") or {}).get("oofPredictionEvidenceSha256"),
        "oofRows": sum(int(item["validationRows"]) for item in folds),
        "modelLabImplementationSha256": (run.get("environment") or {}).get("modelLabImplementationSha256"),
        "metrics": {key: source.get(key) for key in EXPECTED_METRICS},
        "sourcePlan": {key: (run.get("plan") or {}).get(key) for key in ("planId", "checksum")},
    }


def _manifest_science(manifest: Mapping[str, Any]) -> dict[str, Any]:
    value = manifest.get("acceptedScience")
    if value is not None:
        if (not isinstance(value, Mapping) or value.get("schemaVersion") != "PROJECT_SELECTED_EXECUTABLE_SCIENCE_V1"
            or value.get("projectId") != manifest.get("projectId")
            or _sha(value) != manifest.get("acceptedScienceSha256")):
            raise Stage3ModelLaboratoryError("STAGE3_ARTIFACT_ACCEPTED_SCIENCE_INVALID", "The artifact's selected project science does not authenticate.", status_code=409)
        return dict(value)
    # Read-only compatibility for already-hashed historical artifacts. New plans
    # and producers always embed their exact verified project science above.
    return {"selection": EXPECTED_SELECTION, "candidate": EXPECTED_CANDIDATE,
        "sourceDatasetId": EXPECTED_SOURCE_DATASET_ID, "sourceManifestSha": EXPECTED_SOURCE_MANIFEST_SHA256,
        "goldManifestSha": EXPECTED_GOLD_MANIFEST_SHA, "contextualManifestSha": EXPECTED_CONTEXTUAL_MANIFEST_SHA256,
        "split": EXPECTED_SPLIT, "outlierPolicy": EXPECTED_OUTLIER_POLICY, "missingPolicy": EXPECTED_MISSING_POLICY,
        "development": EXPECTED_DEVELOPMENT, "finalOot": EXPECTED_FINAL_OOT,
        "folds": EXPECTED_FOLDS, "foldLogLosses": EXPECTED_FOLD_LOG_LOSSES,
        "hyperparameters": EXPECTED_HYPERPARAMETERS, "oofEvidenceSha256": EXPECTED_OOF_EVIDENCE_SHA256,
        "oofRows": EXPECTED_OOF_ROWS, "modelLabImplementationSha256": EXPECTED_MODEL_LAB_IMPLEMENTATION_SHA256,
        "metrics": EXPECTED_METRICS, "sourcePlan": EXPECTED_SOURCE_PLAN}


def _assert_exact_accepted_chain(chain: Mapping[str, Any]) -> None:
    """Validate exact current receipt links; no project inherits pilot science."""
    science = _accepted_science(chain)
    source = chain["sourceCandidate"]
    run = chain["sourceRun"]
    identity = run.get("identity") or {}
    resolved = chain["resolvedAuthority"]
    feature = chain["featureSetContract"]
    authority = _authority_payload(chain)
    required_identity = ("projectId", "sourceDatasetId", "sourceManifestSha", "goldManifestSha",
        "contextualManifestSha", "authorityKey", "splitContractId", "splitVersion", "splitChecksum",
        "outlierPolicyId", "outlierPolicyVersion", "outlierPolicyChecksum", "missingPolicyId", "missingPolicyVersion", "missingPolicyChecksum")
    mismatches = ["sourceRun.identity." + key for key in required_identity if identity.get(key) != authority[key]]
    if chain.get("projectId") != resolved.project_id or (run.get("plan") or {}).get("projectId") != resolved.project_id:
        mismatches.append("projectId")
    if any(not value for value in science["selection"].values()): mismatches.append("selection")
    if (run.get("runId") != chain.get("candidateRunId") or run.get("runReceiptSha256") != chain.get("candidateRunReceiptSha256")
        or source.get("candidateId") != chain.get("candidateAttemptId")
        or source.get("featureSetId") != feature.get("featureSetId")
        or source.get("featureSetChecksum") != feature.get("checksum")
        or candidate_specification_fingerprint(run, source) != chain.get("candidateFingerprint")):
        mismatches.append("candidateReceipt")
    hashes = [science["oofEvidenceSha256"], science["modelLabImplementationSha256"],
        science["sourcePlan"]["checksum"], science["candidate"]["featureSetChecksum"],
        chain.get("candidateAttemptReceiptSha256"), chain.get("candidateRunReceiptSha256")]
    if not re.fullmatch(r"stage3-candidate-spec-[0-9a-f]{64}", str(chain.get("candidateFingerprint") or "")): mismatches.append("candidateSpecificationFingerprint")
    if any(not _SHA256_RE.fullmatch(str(value or "")) for value in hashes): mismatches.append("contentAddress")
    if science["candidate"]["modelFamily"] != "xgboost":
        raise Stage3ModelLaboratoryError("STAGE3_EXECUTABLE_ARTIFACT_MODEL_FAMILY_UNSUPPORTED", "Executable artifact production currently requires a project-selected XGBoost research challenger.", status_code=409)
    try:
        if any(not np.isfinite(float(value)) for value in [*science["metrics"].values(), *science["foldLogLosses"]]): mismatches.append("acceptedMetrics")
    except (TypeError, ValueError): mismatches.append("acceptedMetrics")
    if (list(identity.get("targetOrder") or []) != list(GOLD_CLASS_ORDER)
        or not feature.get("orderedFeatures") or len(set(feature["orderedFeatures"])) != len(feature["orderedFeatures"])
        or resolved.split["finalOot"].get("locked") is not True
        or science["development"][1] >= science["finalOot"][0]): mismatches.append("developmentContract")
    if mismatches:
        raise Stage3ModelLaboratoryError("STAGE3_EXECUTABLE_ARTIFACT_ACCEPTED_AUTHORITY_MISMATCH", "Artifact construction stopped at stale project receipt fields: " + ", ".join(mismatches), status_code=409)


def _resolved_chain(database: Database, project_id: str) -> dict[str, Any]:
    chain = resolve_current_research_challenger(database, project_id)
    _assert_exact_accepted_chain(chain)
    return chain


def plan_executable_artifact(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_PLAN_INVALID",
            "The executable-artifact plan request must be an object.",
        )
    forbidden = sorted(_FORBIDDEN_PLAN_KEYS & set(payload))
    unknown = sorted(set(payload) - {"selectionId", "nativeWorkers"})
    if forbidden or unknown:
        supplied = list(dict.fromkeys([*forbidden, *unknown]))
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_PLAN_OPTION_FORBIDDEN",
            "Artifact science is immutable; unsupported options: "
            + ", ".join(supplied),
            status_code=409,
        )
    chain = _resolved_chain(database, project_id)
    science = _accepted_science(chain)
    require_model_execution_authority(database, chain["resolvedAuthority"], actor_user_id)
    requested_selection = str(payload.get("selectionId") or "")
    if requested_selection and requested_selection != chain["selectionDecisionId"]:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_SELECTION_STALE",
            "The requested research-challenger selection is not current.",
            status_code=409,
        )
    requested_workers = payload.get("nativeWorkers", 4)
    if isinstance(requested_workers, bool):
        requested_workers = 0
    try:
        native_workers = int(requested_workers)
    except (TypeError, ValueError, OverflowError):
        native_workers = 0
    if native_workers < 1 or native_workers > 4:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_NATIVE_WORKERS_INVALID",
            "nativeWorkers must be an integer from 1 through 4.",
        )
    feature_contract = chain["featureSetContract"]
    ordered_features = list(feature_contract.get("orderedFeatures") or [])
    identity = {
        "schemaVersion": EXECUTABLE_ARTIFACT_PLAN_SCHEMA_VERSION,
        "projectId": project_id,
        "executionActorUserId": actor_user_id,
        "acceptedScience": science,
        "acceptedScienceSha256": _sha(science),
        "selection": _selection_payload(chain),
        "authority": _authority_payload(chain),
        "candidate": {
            "modelFamily": "xgboost",
            "estimatorClass": "XGBClassifier",
            "objective": "multi:softprob",
            "evaluationMetric": "mlogloss",
            "featureSetId": feature_contract.get("featureSetId"),
            "featureSetChecksum": feature_contract.get("checksum"),
            "featureCount": len(ordered_features),
            "orderedFeaturesSha256": _sha(
                {"orderedFeatures": ordered_features}
            ),
            "hyperparameters": dict(science["hyperparameters"]),
            "seed": science["candidate"]["seed"],
            "targetOrder": list(GOLD_CLASS_ORDER),
            "acceptedOofEvidenceSha256": science["oofEvidenceSha256"],
            "acceptedModelLabImplementationSha256": (
                science["modelLabImplementationSha256"]
            ),
        },
        "workload": {
            "foldCount": len(science["folds"]),
            "oofRows": science["oofRows"],
            "finalFitRows": science["development"][2],
            "modelFits": len(science["folds"]) + 1,
            "estimatedSecondsFromAcceptedRun": (float(chain["sourceCandidate"]["runtimeMs"]) / 1000 if isinstance(chain["sourceCandidate"].get("runtimeMs"), (int, float)) else chain["sourceCandidate"].get("durationSeconds")),
        },
        "execution": {
            "computeClass": "VERY_HIGH",
            "nativeWorkers": native_workers,
            "exclusiveCandidate": True,
            "maximumConcurrentSameAlgorithm": 1,
            "nestedOversubscriptionProhibited": True,
            "schedulingPolicy": "MODEL_FAMILY_ROUND_ROBIN_RESOURCE_AWARE_V1",
        },
        "environment": _production_environment(chain),
        "expectedArtifacts": [
            *[f"fold-models/fold-{index}.joblib" for index in range(1, len(science["folds"]) + 1)],
            "oof-predictions.parquet",
            "model.joblib",
            "preprocessor.joblib",
            "verification-fixture.json",
            "verification-receipt.json",
            "manifest.json",
        ],
        "safety": _safety_payload(),
    }
    checksum = _sha(identity)
    plan = {
        **identity,
        "planId": f"stage3-executable-artifact-plan-{checksum[:32]}",
        "checksum": checksum,
        "createdAt": now_iso(),
        "createdByUserId": actor_user_id,
        "status": "READY",
        "executable": True,
        "executionBlocker": None,
    }
    return {"ok": True, "plan": plan}


def _plan_identity(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in plan.items()
        if key
        not in {
            "planId",
            "checksum",
            "createdAt",
            "createdByUserId",
            "status",
            "executable",
            "executionBlocker",
        }
    }


def _assert_reviewed_plan(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    expected_id = str(payload.get("expectedPlanId") or "")
    expected_checksum = str(payload.get("expectedPlanChecksum") or "")
    if not expected_id or not expected_checksum:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_EXACT_PLAN_REVIEW_REQUIRED",
            "Review the exact executable-artifact plan immediately before starting it.",
            status_code=409,
        )
    plan_payload = {
        key: payload[key]
        for key in ("selectionId", "nativeWorkers")
        if key in payload
    }
    result = plan_executable_artifact(
        database, project_id, plan_payload, actor_user_id=actor_user_id
    )
    plan = result["plan"]
    if plan["planId"] != expected_id or plan["checksum"] != expected_checksum:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_REVIEWED_PLAN_CHANGED",
            "The executable plan changed after review; review it again before fitting.",
            status_code=409,
        )
    if _sha(_plan_identity(plan)) != plan["checksum"]:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_PLAN_CHECKSUM_INVALID",
            "The reviewed artifact plan failed its canonical checksum.",
            status_code=409,
        )
    return plan


def _decode_job(row: Mapping[str, Any]) -> dict[str, Any]:
    plan = json_loads(row.get("parameters_json"), {})
    if plan.get("projectId") != row.get("project_id") or (plan.get("executionActorUserId", row.get("created_by")) != row.get("created_by") and not (json_loads(row.get("artifacts_json"), {}).get("publicationRecovery") or {}).get("sourceJobId")):
        raise Stage3ModelLaboratoryError("STAGE3_EXECUTABLE_ARTIFACT_JOB_PROJECT_MISMATCH", "The persisted artifact job belongs to another project or actor.", status_code=409)
    artifacts = json_loads(row.get("artifacts_json"), {})
    error = json_loads(row.get("error_json"), {})
    normalized_error = (
        {"code": str(error.get("code")), "message": str(error.get("message"))}
        if isinstance(error, Mapping) and error.get("code") and error.get("message")
        else None
    )
    return {
        "schemaVersion": EXECUTABLE_ARTIFACT_JOB_SCHEMA_VERSION,
        "jobId": row.get("run_id"),
        "projectId": row.get("project_id"),
        "status": str(row.get("status") or "").upper(),
        "createdAt": row.get("started_at"),
        "startedAt": (json_loads(row.get("metrics_json"), {}) or {}).get(
            "startedAt"
        ),
        "completedAt": row.get("completed_at"),
        "plan": json_loads(row.get("parameters_json"), {}),
        "progress": json_loads(row.get("metrics_json"), {}),
        "artifact": artifacts.get("artifact"),
        "publicationRecovery": artifacts.get("publicationRecovery"),
        "safety": artifacts.get("safety") or _safety_payload(),
        "error": normalized_error,
    }


def _job_state_lock(project_id: str) -> Path:
    return _artifact_root() / "locks" / f"{project_id}.job-state.lock"


def _project_fit_lock(project_id: str) -> Path:
    return _artifact_root() / "locks" / f"{project_id}.fit.lock"


def _upsert_job(database: Database, record: Mapping[str, Any]) -> dict[str, Any]:
    return RunRepository(database).upsert(dict(record))


def _windows_process_alive(pid: int) -> bool:
    """Query Windows without using ``os.kill(pid, 0)``.

    Windows does not implement the POSIX signal-zero existence probe.  A
    failed query is treated conservatively as alive unless Windows positively
    reports that the PID does not exist.
    """

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    still_active = 259
    error_invalid_parameter = 87
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    ctypes.set_last_error(0)
    handle = kernel32.OpenProcess(
        process_query_limited_information, False, int(pid)
    )
    if not handle:
        return ctypes.get_last_error() != error_invalid_parameter
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return int(exit_code.value) == still_active
    finally:
        kernel32.CloseHandle(handle)


def _process_alive(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return True
    if pid <= 0:
        return True
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            return _windows_process_alive(pid)
        except Exception:  # inconclusive OS diagnostic must not orphan live work
            return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except OSError:
        return True
    except Exception:
        return True


def _reconcile_interrupted_job(
    database: Database, row: Mapping[str, Any]
) -> dict[str, Any]:
    if str(row.get("status") or "").upper() not in _ACTIVE_STATUSES:
        return dict(row)
    artifacts = json_loads(row.get("artifacts_json"), {})
    job_id = str(row.get("run_id") or "")
    instance = str(artifacts.get("coordinatorInstanceId") or "")
    pid = artifacts.get("coordinatorProcessId")
    alive = _process_alive(pid)
    if int(pid or -1) == os.getpid() and instance == _COORDINATOR_INSTANCE_ID:
        with _FUTURES_GUARD:
            future = _FUTURES.get(job_id)
            synchronous_recovery_active = job_id in _SYNCHRONOUS_RECOVERY_JOBS
        alive = synchronous_recovery_active or (
            future is not None and not future.done()
        )
        if future is None and not synchronous_recovery_active:
            registered = float(artifacts.get("coordinatorRegisteredClock") or 0.0)
            alive = bool(registered and time.time() - registered <= 30.0)
    if alive:
        return dict(row)
    progress = json_loads(row.get("metrics_json"), {})
    updated = _upsert_job(
        database,
        {
            **dict(row),
            "status": "INTERRUPTED",
            "completed_at": now_iso(),
            "parameters_json": json_loads(row.get("parameters_json"), {}),
            "metrics_json": {
                **progress,
                "state": "INTERRUPTED",
                "latestCheckpoint": progress.get("latestCheckpoint"),
                "resumability": "COMPLETED_FOLD_CHECKPOINTS_PRESERVED_MANUAL_RETRY",
                "message": "The artifact coordinator ended; verified completed-fold checkpoints remain preserved.",
            },
            "artifacts_json": {
                **artifacts,
                "interruptedAt": now_iso(),
            },
            "error_json": {
                "code": "STAGE3_EXECUTABLE_ARTIFACT_COORDINATOR_INTERRUPTED",
                "message": "The persisted coordinator process is no longer running.",
            },
        },
    )
    return updated


def _artifact_rows(database: Database, project_id: str) -> list[dict[str, Any]]:
    rows = [
        row
        for row in RunRepository(database).list_for_project(project_id)
        if row.get("run_type") == EXECUTABLE_ARTIFACT_JOB_TYPE
    ]
    return rows


def _active_job(database: Database, project_id: str) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in _artifact_rows(database, project_id)
            if str(row.get("status") or "").upper() in _ACTIVE_STATUSES
        ),
        None,
    )


def enqueue_executable_artifact_job(
    database: Database,
    project_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_JOB_REQUEST_INVALID",
            "The executable-artifact job request must be an object.",
        )
    allowed = {
        "selectionId",
        "nativeWorkers",
        "expectedPlanId",
        "expectedPlanChecksum",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_JOB_OPTION_FORBIDDEN",
            "Unsupported job options: " + ", ".join(unknown),
            status_code=409,
        )
    plan = _assert_reviewed_plan(
        database, project_id, payload, actor_user_id=actor_user_id
    )
    with _SUBMISSION_GUARD:
        claim = _artifact_root() / "locks" / f"{project_id}.job-claim.lock"
        try:
            with interprocess_lock(
                claim, blocking=True, timeout=10.0, stale_after=120.0
            ):
                active = _active_job(database, project_id)
                if active is not None:
                    active_plan = json_loads(active.get("parameters_json"), {})
                    if active_plan.get("checksum") == plan["checksum"]:
                        return {
                            "ok": True,
                            "job": {
                                **_decode_job(active),
                                "idempotentReplay": True,
                            },
                        }
                    raise Stage3ModelLaboratoryError(
                        "STAGE3_EXECUTABLE_ARTIFACT_JOB_ALREADY_ACTIVE",
                        f"Artifact job {active.get('run_id')} is already active.",
                        status_code=409,
                    )
                completed = next(
                    (
                        row
                        for row in _artifact_rows(database, project_id)
                        if str(row.get("status") or "").upper() == "COMPLETE"
                        and json_loads(row.get("parameters_json"), {}).get("checksum")
                        == plan["checksum"]
                    ),
                    None,
                )
                if completed is not None:
                    decoded = _decode_job(completed)
                    artifact = decoded.get("artifact") or {}
                    verify_artifact_bundle(
                        str(artifact.get("relativePath") or ""),
                        expected_manifest_sha256=str(
                            artifact.get("manifestSha256") or ""
                        ),
                    )
                    return {
                        "ok": True,
                        "job": {**decoded, "idempotentReplay": True},
                    }
                job_id = "stage3-executable-artifact-job-" + uuid.uuid4().hex
                created = now_iso()
                row = _upsert_job(
                    database,
                    {
                        "run_id": job_id,
                        "project_id": project_id,
                        "run_type": EXECUTABLE_ARTIFACT_JOB_TYPE,
                        "workflow_type": "sports_stage3_executable_artifact",
                        "status": "QUEUED",
                        "started_at": created,
                        "completed_at": None,
                        "parameters_json": plan,
                        "metrics_json": {
                            "state": "QUEUED",
                            "startedAt": None,
                            "currentFold": None,
                            "foldRowsProcessed": 0,
                            "oofRowsPersisted": 0,
                            "finalFitState": "PENDING",
                            "artifactStagingState": "PENDING",
                            "reloadVerificationState": "PENDING",
                            "elapsedSeconds": 0.0,
                            "latestCheckpoint": None,
                            "resumability": "NOT_STARTED",
                            "modelFitsByPurpose": {
                                "oofFold": 0,
                                "finalDevelopment": 0,
                            },
                            "message": "Waiting for the exclusive project artifact worker.",
                        },
                        "artifacts_json": {
                            "coordinatorProcessId": os.getpid(),
                            "coordinatorInstanceId": _COORDINATOR_INSTANCE_ID,
                            "coordinatorRegisteredClock": time.time(),
                            "artifact": None,
                            "safety": _safety_payload(),
                        },
                        "error_json": {},
                        "created_by": actor_user_id,
                    },
                )
        except LockBusy as exc:
            raise Stage3ModelLaboratoryError(
                "STAGE3_EXECUTABLE_ARTIFACT_JOB_CLAIM_BUSY",
                "Another process is claiming a Stage 3 artifact job.",
                status_code=409,
            ) from exc
        try:
            future = _EXECUTOR.submit(
                _execute_artifact_job,
                str(database.path),
                job_id,
                project_id,
                actor_user_id,
                plan,
            )
        except Exception as exc:
            _fail_job(
                database,
                job_id,
                "STAGE3_EXECUTABLE_ARTIFACT_COORDINATOR_SUBMISSION_FAILED",
                str(exc),
            )
            raise Stage3ModelLaboratoryError(
                "STAGE3_EXECUTABLE_ARTIFACT_COORDINATOR_SUBMISSION_FAILED",
                "The persistent artifact job could not be submitted.",
                status_code=503,
            ) from exc
        with _FUTURES_GUARD:
            _FUTURES[job_id] = future
        future.add_done_callback(
            lambda done: _artifact_future_finished(
                str(database.path), job_id, done
            )
        )
    return {"ok": True, "job": _decode_job(row)}


def _artifact_future_finished(
    database_path: str, job_id: str, future: Future[None]
) -> None:
    database = Database(database_path)
    try:
        row = RunRepository(database).get(job_id) or {}
        if future.cancelled():
            _cancel_terminal(database, row, before_start=True)
        elif future.exception() is not None:
            _fail_job(
                database,
                job_id,
                "STAGE3_EXECUTABLE_ARTIFACT_COORDINATOR_CRASHED",
                str(future.exception()),
            )
        elif str(row.get("status") or "").upper() in _ACTIVE_STATUSES:
            _fail_job(
                database,
                job_id,
                "STAGE3_EXECUTABLE_ARTIFACT_COORDINATOR_NO_TERMINAL_STATE",
                "The coordinator returned without persisting a terminal state.",
            )
    finally:
        with _FUTURES_GUARD:
            _FUTURES.pop(job_id, None)


def _update_progress(
    database: Database,
    job_id: str,
    started_clock: float,
    **changes: Any,
) -> dict[str, Any]:
    row = RunRepository(database).get(job_id) or {}
    prior = json_loads(row.get("metrics_json"), {})
    status = str(row.get("status") or "").upper()
    if status not in _ACTIVE_STATUSES:
        return dict(row)
    progress = {
        **prior,
        **changes,
        "elapsedSeconds": float(time.perf_counter() - started_clock),
        "heartbeatAt": now_iso(),
    }
    return _upsert_job(
        database,
        {
            **dict(row),
            "status": "CANCEL_REQUESTED" if status == "CANCEL_REQUESTED" else "RUNNING",
            "parameters_json": json_loads(row.get("parameters_json"), {}),
            "metrics_json": progress,
            "artifacts_json": json_loads(row.get("artifacts_json"), {}),
            "error_json": json_loads(row.get("error_json"), {}),
        },
    )


def _cancel_requested(database: Database, job_id: str) -> bool:
    row = RunRepository(database).get(job_id) or {}
    return str(row.get("status") or "").upper() == "CANCEL_REQUESTED"


def _cancel_terminal(
    database: Database, row: Mapping[str, Any], *, before_start: bool = False
) -> None:
    if not row:
        return
    progress = json_loads(row.get("metrics_json"), {})
    _upsert_job(
        database,
        {
            **dict(row),
            "status": "CANCELLED",
            "completed_at": now_iso(),
            "parameters_json": json_loads(row.get("parameters_json"), {}),
            "metrics_json": {
                **progress,
                "state": "CANCELLED",
                "resumability": (
                    "NOTHING_STARTED"
                    if before_start
                    else "COMPLETED_FOLD_CHECKPOINTS_PRESERVED_MANUAL_RETRY"
                ),
                "message": (
                    "The artifact job was cancelled before any fit began."
                    if before_start
                    else "Unstarted work was cancelled; completed fold evidence remains preserved."
                ),
            },
            "artifacts_json": json_loads(row.get("artifacts_json"), {}),
            "error_json": {},
        },
    )


def _fail_job(database: Database, job_id: str, code: str, message: str) -> None:
    row = RunRepository(database).get(job_id) or {}
    if not row or str(row.get("status") or "").upper() in _TERMINAL_STATUSES:
        return
    progress = json_loads(row.get("metrics_json"), {})
    _upsert_job(
        database,
        {
            **dict(row),
            "status": "FAILED",
            "completed_at": now_iso(),
            "parameters_json": json_loads(row.get("parameters_json"), {}),
            "metrics_json": {
                **progress,
                "state": "FAILED",
                "resumability": "COMPLETED_FOLD_CHECKPOINTS_PRESERVED_MANUAL_RETRY",
                "message": message,
            },
            "artifacts_json": json_loads(row.get("artifacts_json"), {}),
            "error_json": {"code": code, "message": message},
        },
    )


def _json_scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    return value


def _prediction_checksum(
    *,
    canonical_pa_id: str,
    canonical_game_id: str,
    game_date: str,
    fold_number: int,
    outcome: str,
    probabilities: Sequence[float],
    candidate_fingerprint: str,
    feature_set_id: str,
    split_contract_id: str,
    preprocessing_identity: str,
    model_identity: str,
) -> str:
    return _sha(
        {
            "canonicalPaId": canonical_pa_id,
            "canonicalGameId": canonical_game_id,
            "gameDate": game_date,
            "foldNumber": int(fold_number),
            "outcome": outcome,
            "probabilities": [float(value) for value in probabilities],
            "candidateFingerprint": candidate_fingerprint,
            "featureSetId": feature_set_id,
            "splitContractId": split_contract_id,
            "preprocessingIdentity": preprocessing_identity,
            "modelIdentity": model_identity,
        }
    )


def _write_parquet_atomic(frame: pd.DataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp.parquet", dir=path.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        frame.to_parquet(temporary, index=False, engine="pyarrow")
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return _file_record(path, path.parent)


def _metric_reconciliation(
    reproduced: Mapping[str, Any], accepted: Mapping[str, Any]
) -> dict[str, Any]:
    differences: dict[str, float] = {}
    key_map = {
        "meanOofLogLoss": "meanOofLogLoss",
        "summedBrier": "summedBrier",
        "ece": "ece",
        "accuracyDiagnostic": "accuracyDiagnostic",
        "macroF1Diagnostic": "macroF1Diagnostic",
    }
    for output_key, accepted_key in key_map.items():
        differences[output_key] = abs(
            float(reproduced[output_key]) - float(accepted[accepted_key])
        )
    max_difference = max(differences.values(), default=0.0)
    if max_difference > _METRIC_ATOL:
        first = next(key for key, value in differences.items() if value > _METRIC_ATOL)
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_METRIC_REPRODUCTION_FAILED",
            f"Accepted OOF metric {first} differs by {differences[first]:.17g}.",
            status_code=409,
        )
    return {
        "status": "PASS",
        "tolerance": _METRIC_ATOL,
        "maxAbsoluteDifference": float(max_difference),
        "differences": differences,
    }


def _fold_metric_reconciliation(
    reproduced: Mapping[str, Any],
    chain: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Bind every reproduced fold to the accepted split and log-loss evidence."""

    science = _accepted_science(chain)
    raw_folds = list(reproduced.get("folds") or [])
    if len(raw_folds) != len(science["folds"]):
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_FOLD_REPRODUCTION_FAILED",
            "Reproduction did not return the registered chronological folds.",
            status_code=409,
        )
    evidence: list[dict[str, Any]] = []
    for raw, boundary, accepted_loss in zip(
        raw_folds, science["folds"], science["foldLogLosses"], strict=True
    ):
        expected_boundary = {
            "foldNumber": boundary[0],
            "trainStart": boundary[1],
            "trainEnd": boundary[2],
            "trainRows": boundary[3],
            "trainGames": boundary[4],
            "validationStart": boundary[5],
            "validationEnd": boundary[6],
            "validationRows": boundary[7],
            "validationGames": boundary[8],
        }
        if any(raw.get(key) != value for key, value in expected_boundary.items()):
            raise Stage3ModelLaboratoryError(
                "STAGE3_EXECUTABLE_ARTIFACT_FOLD_REPRODUCTION_FAILED",
                f"Fold {boundary[0]} differs from the accepted chronological boundary.",
                status_code=409,
            )
        try:
            observed_loss = float((raw.get("metrics") or {})["multiclassLogLoss"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise Stage3ModelLaboratoryError(
                "STAGE3_EXECUTABLE_ARTIFACT_FOLD_REPRODUCTION_FAILED",
                f"Fold {boundary[0]} has no valid reproduced multiclass log loss.",
                status_code=409,
            ) from exc
        delta = observed_loss - float(accepted_loss)
        if not np.isfinite(observed_loss) or abs(delta) > _METRIC_ATOL:
            raise Stage3ModelLaboratoryError(
                "STAGE3_EXECUTABLE_ARTIFACT_FOLD_REPRODUCTION_FAILED",
                f"Fold {boundary[0]} accepted log loss differs by {delta:.17g}.",
                status_code=409,
            )
        evidence.append(
            {
                **expected_boundary,
                "observedLogLoss": observed_loss,
                "expectedAcceptedLogLoss": float(accepted_loss),
                "delta": float(delta),
                "absoluteDifference": float(abs(delta)),
                "tolerance": _METRIC_ATOL,
                "status": "PASS",
            }
        )
    return evidence


def _read_fixture(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FIXTURE_INVALID",
            "The verification fixture is missing or invalid.",
            status_code=409,
        ) from exc
    if not isinstance(value, Mapping):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FIXTURE_INVALID",
            "The verification fixture must be a JSON object.",
            status_code=409,
        )
    return dict(value)


def verify_staged_model(
    directory: Path | str,
    *,
    expected_model_sha256: str,
    expected_fixture_sha256: str,
) -> dict[str, Any]:
    """Hash-check a staged model and fixture before trusted-local loading."""

    root = _artifact_root()
    artifact_dir = _require_contained(Path(directory), root)
    model_path = _require_contained(artifact_dir / "model.joblib", root)
    fixture_path = _require_contained(
        artifact_dir / "verification-fixture.json", root
    )
    if (
        not _SHA256_RE.fullmatch(expected_model_sha256)
        or _sha_file(model_path) != expected_model_sha256
        or not _SHA256_RE.fullmatch(expected_fixture_sha256)
        or _sha_file(fixture_path) != expected_fixture_sha256
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_STAGED_CHECKSUM_MISMATCH",
            "The staged model or verification fixture checksum differs.",
            status_code=409,
        )
    # joblib is trusted-local only, and deserialization happens strictly after
    # both expected hashes have been established.
    pipeline = joblib.load(model_path)
    if not isinstance(pipeline, Stage3FittedPipeline):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PIPELINE_TYPE_INVALID",
            "The staged model is not a Stage3FittedPipeline.",
            status_code=409,
        )
    fixture = _read_fixture(fixture_path)
    features = list(fixture.get("orderedFeatures") or [])
    if features != list(pipeline.ordered_features):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FIXTURE_FEATURE_ORDER_MISMATCH",
            "The verification fixture feature order differs from the model.",
            status_code=409,
        )
    frame = pd.DataFrame(fixture.get("rows") or [], columns=features)
    observed = pipeline.predict_proba(frame)
    expected = np.asarray(fixture.get("expectedProbabilities") or [], dtype=float)
    _validate_probability_matrix(expected, expected_rows=len(frame))
    if observed.shape != expected.shape:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FIXTURE_SHAPE_MISMATCH",
            "The reloaded fixture probability shape differs.",
            status_code=409,
        )
    max_difference = float(np.max(np.abs(observed - expected))) if observed.size else 0.0
    if max_difference > _METRIC_ATOL:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FIXTURE_REPRODUCTION_FAILED",
            f"Reloaded fixture probabilities differ by {max_difference:.17g}.",
            status_code=409,
        )
    return {
        "status": "PASS",
        "freshProcess": False,
        "maxAbsoluteDifference": max_difference,
        "rows": int(len(frame)),
    }


def _fresh_process_reload_check(
    directory: Path,
    *,
    expected_model_sha256: str,
    expected_fixture_sha256: str,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "server.sports_current_statcast.stage3_executable_artifact",
        "--verify-staged",
        str(directory),
        "--model-sha256",
        expected_model_sha256,
        "--fixture-sha256",
        expected_fixture_sha256,
    ]
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FRESH_PROCESS_RELOAD_FAILED",
            "A fresh Python process could not reload and reproduce the fixture: "
            + detail,
            status_code=409,
        )
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FRESH_PROCESS_RECEIPT_INVALID",
            "The fresh-process verifier did not return a valid receipt.",
            status_code=409,
        ) from exc
    return {**result, "freshProcess": True}


@dataclass(frozen=True)
class LoadedStage3Artifact:
    pipeline: Stage3FittedPipeline
    manifest: dict[str, Any]
    artifact_path: Path
    verified: bool = True
    fold_number: int | None = None


@dataclass(frozen=True)
class ArtifactPublication:
    artifact_path: Path
    reused: bool
    protocol: str
    fallback_used: bool


def resolve_executable_artifact_path(relative_path: str) -> Path:
    normalized = str(relative_path or "").replace("\\", "/")
    parts = Path(normalized).parts
    if (
        len(parts) != 3
        or parts[0] != "objects"
        or parts[1] != "sha256"
        or not _SHA256_RE.fullmatch(parts[2])
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PATH_INVALID",
            "Only canonical content-addressed Stage 3 artifact paths may be loaded.",
            status_code=409,
        )
    return _require_contained(_artifact_root().joinpath(*parts))


def _validate_manifest_authority(manifest: Mapping[str, Any]) -> None:
    science = _manifest_science(manifest)
    authority = manifest.get("authority") or {}
    selection = manifest.get("selection") or {}
    candidate = manifest.get("candidate") or {}
    training = manifest.get("training") or {}
    oof = manifest.get("oof") or {}
    environment = manifest.get("environment") or {}
    verification = manifest.get("verification") or {}
    ordered_features = list(manifest.get("orderedFeatures") or [])
    mismatches: list[str] = []
    expected_authority = {
        "projectId": manifest.get("projectId"),
        "sourceDatasetId": science["sourceDatasetId"],
        "sourceManifestSha": science["sourceManifestSha"],
        "goldDatasetId": "gold-table:gold_mlb_current_pa_v1",
        "goldManifestSha": science["goldManifestSha"],
        "contextualManifestSha": science["contextualManifestSha"],
        "splitContractId": science["split"]["splitContractId"],
        "splitVersion": science["split"]["version"],
        "splitChecksum": science["split"]["checksum"],
        "outlierPolicyId": science["outlierPolicy"]["policyId"],
        "outlierPolicyVersion": science["outlierPolicy"]["policyVersion"],
        "outlierPolicyChecksum": science["outlierPolicy"]["checksum"],
        "missingPolicyId": science["missingPolicy"]["policyId"],
        "missingPolicyVersion": science["missingPolicy"]["policyVersion"],
        "missingPolicyChecksum": science["missingPolicy"]["checksum"],
        "developmentRows": science["development"][2],
        "developmentStart": science["development"][0],
        "developmentEnd": science["development"][1],
        "finalOotRows": science["finalOot"][2],
        "finalOotStart": science["finalOot"][0],
        "finalOotEnd": science["finalOot"][1],
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
    }
    for key, expected in expected_authority.items():
        if authority.get(key) != expected:
            mismatches.append(f"authority.{key}")
    for key, expected in science["selection"].items():
        if selection.get(key) != expected:
            mismatches.append(f"selection.{key}")
    for key in (
        "candidateFingerprint",
        "candidateAttemptId",
        "candidateAttemptReceiptSha256",
        "candidateRunId",
        "candidateRunReceiptSha256",
    ):
        if selection.get(key) != science["candidate"][key]:
            mismatches.append(f"selection.{key}")
    expected_candidate = {
        "modelFamily": "xgboost",
        "estimatorClass": "XGBClassifier",
        "objective": "multi:softprob",
        "evaluationMetric": "mlogloss",
        "featureSetId": science["candidate"]["featureSetId"],
        "featureSetChecksum": science["candidate"]["featureSetChecksum"],
        "featureCount": science["candidate"]["featureCount"],
        "seed": science["candidate"]["seed"],
        "targetOrder": list(GOLD_CLASS_ORDER),
        "acceptedOofEvidenceSha256": science["oofEvidenceSha256"],
        "acceptedModelLabImplementationSha256": (
            science["modelLabImplementationSha256"]
        ),
    }
    for key, expected in expected_candidate.items():
        if candidate.get(key) != expected:
            mismatches.append(f"candidate.{key}")
    if candidate.get("hyperparameters") != science["hyperparameters"]:
        mismatches.append("candidate.hyperparameters")
    if (
        len(ordered_features) != science["candidate"]["featureCount"]
        or len(ordered_features) != len(set(ordered_features))
        or candidate.get("orderedFeaturesSha256")
        != _sha({"orderedFeatures": ordered_features})
    ):
        mismatches.append("orderedFeatures")
    if list(manifest.get("targetOrder") or []) != list(GOLD_CLASS_ORDER):
        mismatches.append("targetOrder")
    if manifest.get("probabilityContract") != _probability_contract():
        mismatches.append("probabilityContract")
    expected_training = {
        "scope": "DEVELOPMENT_ONLY",
        "rows": science["development"][2],
        "startDate": science["development"][0],
        "cutoff": science["development"][1],
        "seed": science["candidate"]["seed"],
        "finalOotRowsUsed": 0,
        "finalOotTargetAccessed": False,
    }
    for key, expected in expected_training.items():
        if training.get(key) != expected:
            mismatches.append(f"training.{key}")
    if (
        oof.get("scope") not in {"CHRONOLOGICAL_DEVELOPMENT_ONLY", "FIVE_FOLD_CHRONOLOGICAL_DEVELOPMENT_ONLY"}
        or oof.get("rows") != science["oofRows"]
        or oof.get("foldCount") != len(science["folds"])
        or oof.get("legacyEvidenceSha256") != science["oofEvidenceSha256"]
    ):
        mismatches.append("oof")
    fold_evidence = oof.get("folds")
    if not isinstance(fold_evidence, list) or len(fold_evidence) != len(science["folds"]):
        mismatches.append("oof.folds")
    else:
        for item, boundary, expected_loss in zip(
            fold_evidence, science["folds"], science["foldLogLosses"], strict=True
        ):
            fold_number = boundary[0]
            expected_boundary = {
                "foldNumber": fold_number,
                "trainStart": boundary[1],
                "trainEnd": boundary[2],
                "trainRows": boundary[3],
                "trainGames": boundary[4],
                "validationStart": boundary[5],
                "validationEnd": boundary[6],
                "validationRows": boundary[7],
                "validationGames": boundary[8],
            }
            if not isinstance(item, Mapping) or any(
                item.get(key) != value for key, value in expected_boundary.items()
            ):
                mismatches.append(f"oof.folds[{fold_number}].boundary")
                continue
            try:
                observed_loss = float(item["observedLogLoss"])
                recorded_expected = float(item["expectedAcceptedLogLoss"])
                delta = float(item["delta"])
                absolute_difference = float(item["absoluteDifference"])
                tolerance = float(item["tolerance"])
            except (KeyError, TypeError, ValueError, OverflowError):
                mismatches.append(f"oof.folds[{fold_number}].metrics")
                continue
            if (
                not all(
                    np.isfinite(value)
                    for value in (
                        observed_loss,
                        recorded_expected,
                        delta,
                        absolute_difference,
                        tolerance,
                    )
                )
                or recorded_expected != float(expected_loss)
                or tolerance != _METRIC_ATOL
                or item.get("status") != "PASS"
                or abs(observed_loss - recorded_expected) > _METRIC_ATOL
                or not np.isclose(
                    delta,
                    observed_loss - recorded_expected,
                    rtol=0.0,
                    atol=np.finfo(float).eps,
                )
                or not np.isclose(
                    absolute_difference,
                    abs(delta),
                    rtol=0.0,
                    atol=np.finfo(float).eps,
                )
            ):
                mismatches.append(f"oof.folds[{fold_number}].metrics")
    if (
        (environment.get("acceptedCandidateRun") or {}).get(
            "modelLabImplementationSha256"
        )
        != science["modelLabImplementationSha256"]
    ):
        mismatches.append("environment.acceptedCandidateRun")
    if (
        verification.get("status") != "PASS"
        or (verification.get("metricReproduction") or {}).get("status") != "PASS"
        or not _valid_raw_probability_diagnostics(
            verification.get("rawOofProbabilityValidation"),
            expected_rows=science["oofRows"],
        )
        or (verification.get("reloadVerification") or {}).get("status") != "PASS"
        or (verification.get("reloadVerification") or {}).get("freshProcess")
        is not True
        or (verification.get("verificationFixture") or {}).get("status")
        != "PASS"
    ):
        mismatches.append("verification")
    if manifest.get("safety") != _safety_payload():
        mismatches.append("safety")
    if mismatches:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_MANIFEST_AUTHORITY_INVALID",
            "The manifest differs from accepted authority at: "
            + ", ".join(mismatches),
            status_code=409,
        )


def _manifest_member_records(
    manifest: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    science = _manifest_science(manifest)
    files = manifest.get("files") or {}
    required_records: list[Mapping[str, Any]] = []
    for key in (
        "model",
        "preprocessor",
        "oofPredictions",
        "verificationFixture",
        "verificationReceipt",
    ):
        record = files.get(key)
        if not isinstance(record, Mapping):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_PARTIAL_PUBLICATION",
                f"The published artifact is missing {key}.",
                status_code=409,
            )
        required_records.append(record)
    fold_records = files.get("foldModels")
    valid_fold_records = (
        isinstance(fold_records, list)
        and len(fold_records) == len(science["folds"])
        and all(isinstance(item, Mapping) for item in fold_records)
    )
    try:
        fold_numbers = (
            [int(item.get("foldNumber") or 0) for item in fold_records]
            if valid_fold_records
            else []
        )
    except (TypeError, ValueError, OverflowError):
        fold_numbers = []
    if not valid_fold_records or fold_numbers != list(range(1, len(science["folds"]) + 1)):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PARTIAL_PUBLICATION",
            "The published artifact must contain every accepted chronological fold pipeline.",
            status_code=409,
        )
    required_records.extend(fold_records)
    oof_fold_evidence = list((manifest.get("oof") or {}).get("folds") or [])
    for record, expected, evidence in zip(
        fold_records, science["folds"], oof_fold_evidence, strict=True
    ):
        if not isinstance(evidence, Mapping) or any(
            record.get(key) != value for key, value in evidence.items()
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_FOLD_AUTHORITY_MISMATCH",
                f"Fold {expected[0]} artifact boundaries differ from the registered split.",
                status_code=409,
            )
    return required_records


def _canonical_manifest_member_records(
    manifest: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    declared: dict[str, Mapping[str, Any]] = {}
    for record in _manifest_member_records(manifest):
        relative = str(record.get("relativePath") or "")
        checksum = str(record.get("sha256") or "")
        relative_path = Path(relative)
        try:
            size = int(record.get("sizeBytes"))
        except (TypeError, ValueError, OverflowError):
            size = -1
        if (
            not relative
            or relative == "manifest.json"
            or relative_path.is_absolute()
            or bool(relative_path.drive)
            or relative_path.as_posix() != relative
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or relative in declared
            or not _SHA256_RE.fullmatch(checksum)
            or size < 0
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_MEMBER_PATH_INVALID",
                "Every manifest member must have one unique canonical path, checksum, and size.",
                status_code=409,
            )
        declared[relative] = record
    return declared


def _declared_member_directories(
    declared: Mapping[str, Mapping[str, Any]],
) -> set[str]:
    directories: set[str] = set()
    for relative in declared:
        parent = Path(relative).parent
        while parent != Path("."):
            directories.add(parent.as_posix())
            parent = parent.parent
    return directories


def _ordinary_tree_inventory(directory: Path) -> tuple[set[str], set[str]]:
    """Inventory ordinary files/directories and fail closed on reparse or special entries."""

    directory = _require_contained(directory)
    if not directory.is_dir() or _path_is_reparse_point(directory):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_TREE_INVALID",
            "An artifact bundle root must be one ordinary contained directory.",
            status_code=409,
        )
    files: set[str] = set()
    directories: set[str] = set()
    try:
        entries = list(directory.rglob("*"))
    except OSError as exc:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_TREE_INVALID",
            "The artifact bundle tree could not be safely inventoried.",
            status_code=409,
        ) from exc
    for path in entries:
        relative = path.relative_to(directory).as_posix()
        if _path_is_reparse_point(path):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_REPARSE_POINT_REJECTED",
                f"Artifact entry {relative} is a symlink or junction.",
                status_code=409,
            )
        if path.is_file():
            files.add(relative)
        elif path.is_dir():
            directories.add(relative)
        else:
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_TREE_INVALID",
                f"Artifact entry {relative} is not an ordinary file or directory.",
                status_code=409,
            )
    return files, directories


def _verify_manifest_members(
    directory: Path, manifest: Mapping[str, Any]
) -> None:
    """Hash every member and reject undeclared files, directories, and reparses."""

    directory = _require_contained(directory)
    declared = _canonical_manifest_member_records(manifest)
    for relative, record in declared.items():
        checksum = str(record.get("sha256") or "")
        path = _require_contained(directory / relative)
        try:
            path.relative_to(directory)
        except ValueError as exc:
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_MEMBER_PATH_INVALID",
                "A manifest member escapes its immutable object directory.",
                status_code=409,
            ) from exc
        if (
            not path.is_file()
            or not _SHA256_RE.fullmatch(checksum)
            or _sha_file(path) != checksum
            or int(record.get("sizeBytes")) != path.stat().st_size
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_MEMBER_CHECKSUM_MISMATCH",
                f"Artifact member {relative or '<missing>'} is missing or modified.",
                status_code=409,
            )
    actual_files, actual_directories = _ordinary_tree_inventory(directory)
    actual_files.discard("manifest.json")
    if (
        actual_files != set(declared)
        or actual_directories != _declared_member_directories(declared)
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PARTIAL_PUBLICATION",
            "The artifact directory contains missing or undeclared bundle files or directories.",
            status_code=409,
        )


def _verify_bundle_directory(
    directory: Path, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    directory = _require_contained(directory)
    manifest_path = _require_contained(directory / "manifest.json")
    if (
        not manifest_path.is_file()
        or _sha_file(manifest_path) != expected_manifest_sha256
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_MANIFEST_CHECKSUM_MISMATCH",
            "The executable artifact manifest is missing or has been modified.",
            status_code=409,
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_MANIFEST_INVALID",
            "The executable artifact manifest is invalid.",
            status_code=409,
        ) from exc
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schemaVersion")
        != EXECUTABLE_ARTIFACT_MANIFEST_SCHEMA_VERSION
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_MANIFEST_AUTHORITY_INVALID",
            "The manifest does not preserve the governed research-only authority.",
            status_code=409,
        )
    science = _manifest_science(manifest)
    _validate_manifest_authority(manifest)
    _verify_manifest_members(directory, manifest)
    receipt_record = manifest["files"]["verificationReceipt"]
    receipt_path = _require_contained(directory / receipt_record["relativePath"])
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_VERIFICATION_RECEIPT_INVALID",
            "The checksum-valid verification receipt is not valid JSON.",
            status_code=409,
        ) from exc
    manifest_raw_validation = (manifest.get("verification") or {}).get(
        "rawOofProbabilityValidation"
    )
    if (
        not isinstance(receipt, Mapping)
        or receipt.get("schemaVersion")
        != EXECUTABLE_ARTIFACT_VERIFICATION_SCHEMA_VERSION
        or receipt.get("status") != "PASS"
        or receipt.get("probabilityContract") != _probability_contract()
        or receipt.get("probabilityContract") != manifest.get("probabilityContract")
        or receipt.get("rawOofProbabilityValidation") != manifest_raw_validation
        or not _valid_raw_probability_diagnostics(
            receipt.get("rawOofProbabilityValidation"),
            expected_rows=science["oofRows"],
        )
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_VERIFICATION_RECEIPT_INVALID",
            "The verification receipt does not bind the exact raw and executable probability contract.",
            status_code=409,
        )
    return {
        "status": "PASS",
        "manifestSha256": expected_manifest_sha256,
        "manifest": dict(manifest),
        "artifactPath": directory,
    }


def _verify_staged_bundle(
    staging: Path, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    """Verify the complete private bundle before its atomic publication rename."""

    if not _SHA256_RE.fullmatch(str(expected_manifest_sha256 or "")):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_EXPECTED_MANIFEST_REQUIRED",
            "An exact 64-character manifest checksum is required.",
            status_code=409,
        )
    if _path_is_reparse_point(staging):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_REPARSE_POINT_REJECTED",
            "The private staging root must not be a symlink or junction.",
            status_code=409,
        )
    return _verify_bundle_directory(
        staging, expected_manifest_sha256=expected_manifest_sha256
    )


def verify_artifact_bundle(
    relative_path: str, *, expected_manifest_sha256: str
) -> dict[str, Any]:
    if not _SHA256_RE.fullmatch(str(expected_manifest_sha256 or "")):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_EXPECTED_MANIFEST_REQUIRED",
            "An exact 64-character manifest checksum is required.",
            status_code=409,
        )
    directory = resolve_executable_artifact_path(relative_path)
    if directory.name != expected_manifest_sha256:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_ADDRESS_MISMATCH",
            "The artifact address differs from the expected manifest checksum.",
            status_code=409,
        )
    return _verify_bundle_directory(
        directory, expected_manifest_sha256=expected_manifest_sha256
    )


def load_executable_artifact(
    relative_path: str,
    *,
    expected_manifest_sha256: str,
    fold_number: int | None = None,
) -> LoadedStage3Artifact:
    verified = verify_artifact_bundle(
        relative_path, expected_manifest_sha256=expected_manifest_sha256
    )
    manifest = verified["manifest"]
    directory = verified["artifactPath"]
    if fold_number is None:
        model_record = manifest["files"]["model"]
    elif isinstance(fold_number, bool) or fold_number not in range(1, int(manifest["oof"]["foldCount"]) + 1):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_FOLD_NUMBER_INVALID",
            "A fold artifact number must identify a fold in the verified project manifest.",
            status_code=409,
        )
    else:
        model_record = next(
            (
                item
                for item in manifest["files"]["foldModels"]
                if int(item.get("foldNumber") or 0) == fold_number
            ),
            None,
        )
        if model_record is None:  # pragma: no cover - manifest verification guards this
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_FOLD_MODEL_MISSING",
                "The requested verified fold pipeline is unavailable.",
                status_code=409,
            )
    # Every manifest member was verified above; only now may trusted-local
    # pickle deserialization occur.
    pipeline = joblib.load(directory / model_record["relativePath"])
    if not isinstance(pipeline, Stage3FittedPipeline):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PIPELINE_TYPE_INVALID",
            "The executable object is not a Stage3FittedPipeline.",
            status_code=409,
        )
    if (
        list(pipeline.ordered_features) != list(manifest.get("orderedFeatures") or [])
        or list(pipeline.target_order) != list(GOLD_CLASS_ORDER)
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PIPELINE_CONTRACT_MISMATCH",
            "The reloaded pipeline differs from its manifest feature or target contract.",
            status_code=409,
        )
    return LoadedStage3Artifact(
        pipeline=pipeline,
        manifest=dict(manifest),
        artifact_path=directory,
        verified=True,
        fold_number=fold_number,
    )


def _is_transient_windows_publication_error(exc: OSError) -> bool:
    if os.name != "nt":
        return False
    try:
        winerror = int(getattr(exc, "winerror", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return winerror in _WINDOWS_TRANSIENT_PUBLICATION_ERRORS


def _verified_public_artifact_target(
    target: Path, manifest_sha256: str
) -> dict[str, Any]:
    root = _artifact_root()
    relative_path = target.relative_to(root).as_posix()
    return verify_artifact_bundle(
        relative_path, expected_manifest_sha256=manifest_sha256
    )


def _discard_redundant_staging(staging: Path) -> bool:
    """Best-effort cleanup after another publisher produced the exact object."""

    try:
        if not staging.exists():
            return True
        if _path_is_reparse_point(staging) or any(
            _path_is_reparse_point(path) for path in staging.rglob("*")
        ):
            return False
        shutil.rmtree(staging)
    except OSError:
        return False
    return not staging.exists()


def _directory_replace(source: Path, destination: Path) -> None:
    os.replace(source, destination)


def _member_rename(source: Path, destination: Path) -> None:
    # The manifest-last fallback is Windows-only, where os.rename refuses to
    # replace an existing destination. This preserves immutable member names.
    os.rename(source, destination)


def _manifest_rename(source: Path, destination: Path) -> None:
    # Destination must remain absent until this no-overwrite commit operation.
    os.rename(source, destination)


def _content_address_target(root: Path, manifest_sha256: str) -> Path:
    if not _SHA256_RE.fullmatch(str(manifest_sha256 or "")):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_EXPECTED_MANIFEST_REQUIRED",
            "An exact 64-character manifest checksum is required.",
            status_code=409,
        )
    lexical_objects = root / "objects"
    lexical_parent = lexical_objects / "sha256"
    for directory in (lexical_objects, lexical_parent):
        if _path_entry_exists(directory) and _path_is_reparse_point(directory):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_PUBLICATION_TARGET_INVALID",
                "The content-addressed publication ancestry contains a reparse point.",
                status_code=409,
            )
    lexical_parent.mkdir(parents=True, exist_ok=True)
    if any(
        _path_is_reparse_point(directory)
        for directory in (lexical_objects, lexical_parent)
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_INVALID",
            "The content-addressed publication ancestry contains a reparse point.",
            status_code=409,
        )
    parent = _require_contained(lexical_parent, root)
    candidate = lexical_parent / manifest_sha256
    if _path_is_reparse_point(candidate):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_INVALID",
            "The exact content-addressed publication target is a reparse point.",
            status_code=409,
        )
    target = _require_contained(candidate, root)
    if target.parent != parent or target.name != manifest_sha256:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_INVALID",
            "Publication is restricted to the exact direct content-addressed target.",
            status_code=409,
        )
    return target


def _manifest_commit_temp_name(
    destination: Path, manifest_sha256: str, token: str | None = None
) -> str:
    return (
        f".{destination.name}{_MANIFEST_COMMIT_TEMP_TAG}"
        f"{manifest_sha256[:16]}-{token or uuid.uuid4().hex}.tmp"
    )


def _recognized_manifest_commit_temp(
    relative: str,
    declared: Mapping[str, Mapping[str, Any]],
    manifest_sha256: str,
) -> bool:
    candidate = Path(relative)
    possible_destinations = [Path("manifest.json"), *map(Path, declared)]
    for destination in possible_destinations:
        prefix = (
            f".{destination.name}{_MANIFEST_COMMIT_TEMP_TAG}"
            f"{manifest_sha256[:16]}-"
        )
        if candidate.parent != destination.parent:
            continue
        if not candidate.name.startswith(prefix) or not candidate.name.endswith(
            ".tmp"
        ):
            continue
        token = candidate.name[len(prefix) : -4]
        return bool(re.fullmatch(r"[0-9a-f]{32}", token))
    return False


def _target_has_manifest_marker(target: Path) -> bool:
    if not target.exists():
        return False
    files, _directories = _ordinary_tree_inventory(target)
    return "manifest.json" in files


def _path_entry_exists(path: Path) -> bool:
    return os.path.lexists(path)


def _verify_partial_target_member(
    path: Path, relative: str, record: Mapping[str, Any]
) -> None:
    if (
        _path_is_reparse_point(path)
        or not path.is_file()
        or _sha_file(path) != str(record.get("sha256") or "")
        or path.stat().st_size != int(record.get("sizeBytes"))
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_MEMBER_MISMATCH",
            f"Unpublished target member {relative} is modified.",
            status_code=409,
        )


def _validate_partial_manifest_commit_target(
    target: Path,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
) -> set[str]:
    """Validate and clean a crash-resumable target whose commit marker is absent."""

    declared = _canonical_manifest_member_records(manifest)
    files, directories = _ordinary_tree_inventory(target)
    if "manifest.json" in files:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_ALREADY_COMMITTED",
            "The publication target acquired a manifest commit marker during resume.",
            status_code=409,
        )
    expected_directories = _declared_member_directories(declared)
    if not directories.issubset(expected_directories):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_UNEXPECTED_CONTENT",
            "An unpublished target contains an undeclared directory.",
            status_code=409,
        )
    existing_members: set[str] = set()
    recognized_temporaries: list[Path] = []
    for relative in sorted(files):
        record = declared.get(relative)
        path = _require_contained(target / relative)
        if record is not None:
            _verify_partial_target_member(path, relative, record)
            existing_members.add(relative)
            continue
        if _recognized_manifest_commit_temp(relative, declared, manifest_sha256):
            recognized_temporaries.append(path)
            continue
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TARGET_UNEXPECTED_CONTENT",
            f"Unpublished target entry {relative} is not declared or safely resumable.",
            status_code=409,
        )
    for temporary in recognized_temporaries:
        try:
            temporary.unlink()
        except OSError as exc:
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_PUBLICATION_TEMP_CLEANUP_FAILED",
                "A recognized incomplete publication temporary file could not be removed.",
                status_code=503,
            ) from exc
    return existing_members


def _rename_member_with_retries(
    source: Path, destination: Path, record: Mapping[str, Any]
) -> None:
    relative = str(record.get("relativePath") or destination.name)
    for attempt in range(1, _PUBLICATION_RETRY_ATTEMPTS + 1):
        if _path_entry_exists(destination):
            _verify_partial_target_member(destination, relative, record)
            return
        try:
            _member_rename(source, destination)
            return
        except OSError as exc:
            if _path_entry_exists(destination):
                _verify_partial_target_member(destination, relative, record)
                return
            if not _is_transient_windows_publication_error(exc):
                raise
            if attempt >= _PUBLICATION_RETRY_ATTEMPTS:
                raise Stage3ModelLaboratoryError(
                    "STAGE3_ARTIFACT_MANIFEST_COMMIT_MEMBER_RETRY_EXHAUSTED",
                    "A verified member remains temporary after bounded Windows "
                    "sharing-error retries.",
                    status_code=503,
                ) from exc
            delay = min(
                _PUBLICATION_RETRY_INITIAL_DELAY_SECONDS * (2 ** (attempt - 1)),
                _PUBLICATION_RETRY_MAX_DELAY_SECONDS,
            )
            time.sleep(delay)


def _copy_manifest_member_for_commit(
    source: Path,
    destination: Path,
    record: Mapping[str, Any],
    manifest_sha256: str,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / _manifest_commit_temp_name(
        destination, manifest_sha256
    )
    digest = hashlib.sha256()
    copied = 0
    try:
        with source.open("rb") as reader, temporary.open("xb") as writer:
            for chunk in iter(lambda: reader.read(1024 * 1024), b""):
                writer.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if (
            digest.hexdigest() != str(record.get("sha256") or "")
            or copied != int(record.get("sizeBytes"))
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_MANIFEST_COMMIT_COPY_MISMATCH",
                f"Copied artifact member {destination.name} differs from its manifest.",
                status_code=409,
            )
        _rename_member_with_retries(temporary, destination, record)
        _verify_partial_target_member(destination, destination.name, record)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # A future recovery accepts and safely cleans only this exact name shape.
            pass


def _remove_losing_manifest_temporary(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError as exc:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TEMP_CLEANUP_FAILED",
            "The losing manifest temporary could not be removed before "
            "winner verification.",
            status_code=503,
        ) from exc
    if _path_entry_exists(temporary):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_PUBLICATION_TEMP_CLEANUP_FAILED",
            "The losing manifest temporary remains before winner verification.",
            status_code=503,
        )


def _install_manifest_commit_marker(
    *,
    source_manifest: Path,
    target: Path,
    manifest_sha256: str,
) -> bool:
    """Install manifest last. Return False if a valid concurrent marker wins."""

    manifest_path = target / "manifest.json"
    manifest_bytes = source_manifest.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_MANIFEST_CHECKSUM_MISMATCH",
            "The private source manifest changed before publication commit.",
            status_code=409,
        )
    temporary = target / _manifest_commit_temp_name(
        manifest_path, manifest_sha256
    )
    try:
        with temporary.open("xb") as stream:
            stream.write(manifest_bytes)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(1, _PUBLICATION_RETRY_ATTEMPTS + 1):
            if _path_entry_exists(manifest_path):
                _remove_losing_manifest_temporary(temporary)
                _verified_public_artifact_target(target, manifest_sha256)
                return False
            try:
                _manifest_rename(temporary, manifest_path)
                return True
            except OSError as exc:
                if _path_entry_exists(manifest_path):
                    _remove_losing_manifest_temporary(temporary)
                    _verified_public_artifact_target(target, manifest_sha256)
                    return False
                if not _is_transient_windows_publication_error(exc):
                    raise
                if attempt >= _PUBLICATION_RETRY_ATTEMPTS:
                    raise Stage3ModelLaboratoryError(
                        "STAGE3_ARTIFACT_MANIFEST_COMMIT_RETRY_EXHAUSTED",
                        "The verified bundle remains unpublished because its "
                        "manifest commit marker could not be installed.",
                        status_code=503,
                    ) from exc
                delay = min(
                    _PUBLICATION_RETRY_INITIAL_DELAY_SECONDS
                    * (2 ** (attempt - 1)),
                    _PUBLICATION_RETRY_MAX_DELAY_SECONDS,
                )
                time.sleep(delay)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _reuse_verified_public_target(
    staging: Path,
    target: Path,
    manifest_sha256: str,
    *,
    protocol: str = _VERIFIED_EXISTING_TARGET_PROTOCOL,
    fallback_used: bool = False,
) -> ArtifactPublication:
    verified = _verified_public_artifact_target(target, manifest_sha256)
    if verified["status"] != "PASS":  # pragma: no cover - defensive
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_CONTENT_ADDRESS_COLLISION",
            "An existing artifact address did not verify.",
            status_code=409,
        )
    _discard_redundant_staging(staging)
    return ArtifactPublication(
        artifact_path=target,
        reused=True,
        protocol=protocol,
        fallback_used=fallback_used,
    )


def _commit_staging_manifest_last(
    staging: Path,
    target: Path,
    manifest_sha256: str,
    verified_staging: Mapping[str, Any],
) -> ArtifactPublication:
    if os.name != "nt":
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_MANIFEST_COMMIT_PLATFORM_UNSUPPORTED",
            "Manifest-last publication is enabled only on Windows, where file "
            "rename is atomic and no-overwrite.",
            status_code=503,
        )
    manifest = verified_staging["manifest"]
    declared = _canonical_manifest_member_records(manifest)
    if target.exists() and _target_has_manifest_marker(target):
        return _reuse_verified_public_target(
            staging,
            target,
            manifest_sha256,
            protocol=_MANIFEST_COMMIT_PROTOCOL,
            fallback_used=True,
        )
    if not target.exists():
        try:
            target.mkdir(exist_ok=False)
        except FileExistsError:
            pass
    if _target_has_manifest_marker(target):
        return _reuse_verified_public_target(
            staging,
            target,
            manifest_sha256,
            protocol=_MANIFEST_COMMIT_PROTOCOL,
            fallback_used=True,
        )
    try:
        existing = _validate_partial_manifest_commit_target(
            target, manifest, manifest_sha256
        )
    except Stage3ModelLaboratoryError as exc:
        if (
            exc.code
            != "STAGE3_ARTIFACT_PUBLICATION_TARGET_ALREADY_COMMITTED"
        ):
            raise
        return _reuse_verified_public_target(
            staging,
            target,
            manifest_sha256,
            protocol=_MANIFEST_COMMIT_PROTOCOL,
            fallback_used=True,
        )
    for relative, record in sorted(declared.items()):
        if relative in existing:
            continue
        if _target_has_manifest_marker(target):
            return _reuse_verified_public_target(
                staging,
                target,
                manifest_sha256,
                protocol=_MANIFEST_COMMIT_PROTOCOL,
                fallback_used=True,
            )
        source = _require_contained(staging / relative)
        destination = _require_contained(target / relative)
        _copy_manifest_member_for_commit(
            source, destination, record, manifest_sha256
        )
    # This validates exact files, exact directories, hashes, and sizes while
    # manifest.json is deliberately absent and therefore no loader can accept it.
    _verify_manifest_members(target, manifest)
    installed = _install_manifest_commit_marker(
        source_manifest=_require_contained(staging / "manifest.json"),
        target=target,
        manifest_sha256=manifest_sha256,
    )
    _verified_public_artifact_target(target, manifest_sha256)
    _discard_redundant_staging(staging)
    return ArtifactPublication(
        artifact_path=target,
        reused=not installed,
        protocol=_MANIFEST_COMMIT_PROTOCOL,
        fallback_used=True,
    )


def _finalize_staging(
    staging: Path, manifest_sha256: str
) -> ArtifactPublication:
    root = _artifact_root()
    if _path_is_reparse_point(staging):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_REPARSE_POINT_REJECTED",
            "The private staging root must not be a symlink or junction.",
            status_code=409,
        )
    staging = _require_contained(staging, root)
    target = _content_address_target(root, manifest_sha256)
    # This is the publication boundary.  The private directory must already be
    # complete and every byte must match the canonical manifest before the
    # first atomic rename can make it addressable.
    verified_staging = _verify_staged_bundle(
        staging, expected_manifest_sha256=manifest_sha256
    )
    if target.exists():
        if _target_has_manifest_marker(target):
            return _reuse_verified_public_target(staging, target, manifest_sha256)
        return _commit_staging_manifest_last(
            staging, target, manifest_sha256, verified_staging
        )
    for attempt in range(1, _PUBLICATION_RETRY_ATTEMPTS + 1):
        if target.exists():
            if _target_has_manifest_marker(target):
                return _reuse_verified_public_target(
                    staging, target, manifest_sha256
                )
            return _commit_staging_manifest_last(
                staging, target, manifest_sha256, verified_staging
            )
        try:
            _directory_replace(staging, target)
        except OSError as exc:
            # Another same-content publisher can win between the existence
            # check and rename. Verify that object immediately, including on
            # the final retry, before treating it as an idempotent reuse.
            if target.exists():
                if _target_has_manifest_marker(target):
                    return _reuse_verified_public_target(
                        staging, target, manifest_sha256
                    )
                return _commit_staging_manifest_last(
                    staging, target, manifest_sha256, verified_staging
                )
            if not _is_transient_windows_publication_error(exc):
                raise
            if attempt >= _PUBLICATION_RETRY_ATTEMPTS:
                return _commit_staging_manifest_last(
                    staging, target, manifest_sha256, verified_staging
                )
            delay = min(
                _PUBLICATION_RETRY_INITIAL_DELAY_SECONDS * (2 ** (attempt - 1)),
                _PUBLICATION_RETRY_MAX_DELAY_SECONDS,
            )
            time.sleep(delay)
            continue
        _verified_public_artifact_target(target, manifest_sha256)
        return ArtifactPublication(
            artifact_path=target,
            reused=False,
            protocol=_ATOMIC_DIRECTORY_RENAME_PROTOCOL,
            fallback_used=False,
        )
    raise AssertionError("publication retry loop ended without a terminal result")


def _execute_artifact_job(
    database_path: str,
    job_id: str,
    project_id: str,
    actor_user_id: str,
    reviewed_plan: Mapping[str, Any],
) -> None:
    database = Database(database_path)
    started_clock = time.perf_counter()
    row = RunRepository(database).get(job_id) or {}
    if row.get("project_id") != project_id or row.get("created_by") != actor_user_id:
        raise Stage3ModelLaboratoryError("STAGE3_EXECUTABLE_ARTIFACT_JOB_PROJECT_MISMATCH", "The queued artifact job does not authenticate its originating project and user.", status_code=409)
    _decode_job(row)
    if str(row.get("status") or "").upper() == "CANCEL_REQUESTED":
        _cancel_terminal(database, row, before_start=True)
        return
    try:
        with interprocess_lock(
            _project_fit_lock(project_id),
            blocking=True,
            timeout=30.0,
            stale_after=6 * 60 * 60,
        ):
            current_plan = plan_executable_artifact(
                database,
                project_id,
                {
                    "selectionId": reviewed_plan["selection"]["selectionDecisionId"],
                    "nativeWorkers": reviewed_plan["execution"]["nativeWorkers"],
                },
                actor_user_id=actor_user_id,
            )["plan"]
            if current_plan["checksum"] != reviewed_plan.get("checksum"):
                raise Stage3ModelLaboratoryError(
                    "STAGE3_EXECUTABLE_ARTIFACT_AUTHORITY_CHANGED_BEFORE_FIT",
                    "The accepted research authority changed before execution.",
                    status_code=409,
                )
            chain = _resolved_chain(database, project_id)
            science = _accepted_science(chain)
            started_at = now_iso()
            _update_progress(
                database,
                job_id,
                started_clock,
                state="RUNNING",
                startedAt=started_at,
                artifactStagingState="CREATING",
                message="Creating a unique ignored staging directory.",
            )
            root = _artifact_root()
            staging = _require_contained(
                root / "staging" / f"{job_id}-{uuid.uuid4().hex}", root
            )
            staging.mkdir(parents=True, exist_ok=False)
            fold_dir = staging / "fold-models"
            checkpoint_dir = staging / "oof-fold-checkpoints"
            fold_dir.mkdir(parents=True)
            checkpoint_dir.mkdir(parents=True)
            job_row = RunRepository(database).get(job_id) or {}
            artifacts_state = json_loads(job_row.get("artifacts_json"), {})
            _upsert_job(
                database,
                {
                    **dict(job_row),
                    "parameters_json": json_loads(
                        job_row.get("parameters_json"), {}
                    ),
                    "metrics_json": json_loads(job_row.get("metrics_json"), {}),
                    "artifacts_json": {
                        **artifacts_state,
                        "stagingPath": str(staging),
                    },
                    "error_json": {},
                },
            )
            features = list(chain["featureSetContract"]["orderedFeatures"])
            frame = _fold_frame(
                chain["resolvedAuthority"], features, include_oof_identity=True
            )
            if "canonicalPaId" not in frame or frame["canonicalPaId"].isna().any():
                raise Stage3ModelLaboratoryError(
                    "STAGE3_EXECUTABLE_ARTIFACT_PA_IDENTITY_MISSING",
                    "Every authorized development row must have a canonical PA identity.",
                    status_code=409,
                )
            fold_files: list[dict[str, Any]] = []
            checkpoint_paths: list[Path] = []
            oof_rows_persisted = 0

            def progress(event: dict[str, Any]) -> None:
                if event.get("event") == "FOLD_STARTED":
                    require_model_execution_authority(database, chain["resolvedAuthority"], actor_user_id)
                    _update_progress(
                        database,
                        job_id,
                        started_clock,
                        state="RUNNING",
                        currentFold=int(event["fold"]),
                        foldRowsProcessed=0,
                        message=f"Fitting chronological fold {int(event['fold'])} of {len(science['folds'])}.",
                    )
                elif event.get("event") == "FOLD_ESTIMATOR_FIT_COMPLETED":
                    fold_number = int(event["fold"])
                    _update_progress(
                        database,
                        job_id,
                        started_clock,
                        state="RUNNING",
                        currentFold=fold_number,
                        foldRowsProcessed=0,
                        latestCheckpoint=(
                            f"FOLD_{fold_number}_ESTIMATOR_FIT_COMPLETED_AWAITING_VALIDATION"
                        ),
                        modelFitsByPurpose={
                            "oofFold": fold_number,
                            "finalDevelopment": 0,
                        },
                        message=(
                            f"Fold {fold_number} estimator fit completed; validating raw "
                            "probabilities before persisting evidence."
                        ),
                    )

            def capture(payload: dict[str, Any]) -> None:
                nonlocal oof_rows_persisted
                fold = payload["fold"]
                fold_number = int(fold["foldNumber"])
                if _cancel_requested(database, job_id):
                    # The just-completed fold is still persisted before the
                    # remaining unstarted work is cancelled.
                    pass
                model_path = fold_dir / f"fold-{fold_number}.joblib"
                _atomic_joblib(model_path, payload["pipeline"])
                model_record = _file_record(model_path, staging)
                model_record.update(
                    {
                        "foldNumber": fold_number,
                        "trainStart": fold["trainStart"],
                        "trainEnd": fold["trainEnd"],
                        "trainRows": int(fold["trainRows"]),
                        "validationStart": fold["validationStart"],
                        "validationEnd": fold["validationEnd"],
                        "validationRows": int(fold["validationRows"]),
                    }
                )
                fold_files.append(model_record)
                mask = payload["validationMask"]
                validation = frame.loc[
                    mask, ["canonicalPaId", "canonicalGameId", "game_date", "outcome"]
                ].reset_index(drop=True)
                probabilities = np.asarray(payload["probabilities"], dtype=float)
                preprocessing_identity = str(
                    payload["preprocessing"]["artifactSha256"]
                )
                rows = {
                    "canonicalPaId": validation["canonicalPaId"].astype(str),
                    "canonicalGameId": validation["canonicalGameId"].astype(str),
                    "gameDate": validation["game_date"].astype(str),
                    "foldNumber": np.full(len(validation), fold_number, dtype=np.int16),
                    "outcome": validation["outcome"].astype(str),
                }
                for class_index, class_name in enumerate(GOLD_CLASS_ORDER):
                    rows[f"probability_{class_name}"] = probabilities[:, class_index]
                rows.update(
                    {
                        "candidateFingerprint": chain["candidateFingerprint"],
                        "candidateAttemptId": chain["candidateAttemptId"],
                        "featureSetId": chain["featureSetContract"]["featureSetId"],
                        "splitContractId": chain["resolvedAuthority"].split[
                            "contractId"
                        ],
                        "preprocessingIdentity": preprocessing_identity,
                        "modelIdentity": model_record["sha256"],
                    }
                )
                output = pd.DataFrame(rows)
                output["predictionChecksum"] = [
                    _prediction_checksum(
                        canonical_pa_id=str(identity.canonicalPaId),
                        canonical_game_id=str(identity.canonicalGameId),
                        game_date=str(identity.gameDate),
                        fold_number=fold_number,
                        outcome=str(identity.outcome),
                        probabilities=probability_row,
                        candidate_fingerprint=chain["candidateFingerprint"],
                        feature_set_id=chain["featureSetContract"]["featureSetId"],
                        split_contract_id=chain["resolvedAuthority"].split[
                            "contractId"
                        ],
                        preprocessing_identity=preprocessing_identity,
                        model_identity=model_record["sha256"],
                    )
                    for identity, probability_row in zip(
                        output[
                            [
                                "canonicalPaId",
                                "canonicalGameId",
                                "gameDate",
                                "outcome",
                            ]
                        ].itertuples(index=False),
                        probabilities,
                        strict=True,
                    )
                ]
                checkpoint_path = checkpoint_dir / f"fold-{fold_number}.parquet"
                _write_parquet_atomic(output, checkpoint_path)
                checkpoint_paths.append(checkpoint_path)
                oof_rows_persisted += len(output)
                _update_progress(
                    database,
                    job_id,
                    started_clock,
                    state="RUNNING",
                    currentFold=fold_number,
                    foldRowsProcessed=len(output),
                    oofRowsPersisted=oof_rows_persisted,
                    latestCheckpoint=f"FOLD_{fold_number}_PIPELINE_AND_OOF_PERSISTED",
                    resumability="COMPLETED_FOLD_CHECKPOINTS_PRESERVED_MANUAL_RETRY",
                    modelFitsByPurpose={
                        "oofFold": fold_number,
                        "finalDevelopment": 0,
                    },
                    message=f"Persisted verified fold {fold_number} pipeline and OOF rows.",
                )
                if _cancel_requested(database, job_id):
                    raise _CancelAfterCheckpoint()

            try:
                reproduced = _evaluate_candidate(
                    frame,
                    model_family="xgboost",
                    feature_set=chain["featureSetContract"],
                    split=chain["resolvedAuthority"].split,
                    seed=science["candidate"]["seed"],
                    hyperparameters=science["hyperparameters"],
                    native_workers=_bounded_native_workers(
                        reviewed_plan["execution"]["nativeWorkers"]
                    ),
                    progress_callback=progress,
                    artifact_callback=capture,
                )
            except _CancelAfterCheckpoint:
                _cancel_terminal(
                    database, RunRepository(database).get(job_id) or {}
                )
                return
            metric_reproduction = _metric_reconciliation(
                reproduced, chain["sourceCandidate"]
            )
            fold_reproduction = _fold_metric_reconciliation(reproduced, chain)
            fold_reproduction_by_number = {
                int(item["foldNumber"]): item for item in fold_reproduction
            }
            for fold_file in fold_files:
                evidence = fold_reproduction_by_number[int(fold_file["foldNumber"])]
                fold_file.update(
                    {
                        key: value
                        for key, value in evidence.items()
                        if key
                        not in {
                            "foldNumber",
                            "trainStart",
                            "trainEnd",
                            "trainRows",
                            "validationStart",
                            "validationEnd",
                            "validationRows",
                        }
                    }
                )
            reproduced_digest = str(
                (reproduced.get("evaluationEvidence") or {}).get(
                    "oofPredictionEvidenceSha256"
                )
                or ""
            )
            if reproduced_digest != science["oofEvidenceSha256"]:
                raise Stage3ModelLaboratoryError(
                    "STAGE3_EXECUTABLE_ARTIFACT_OOF_DIGEST_MISMATCH",
                    "Reproduced OOF label/probability bytes differ from the accepted legacy digest.",
                    status_code=409,
                )
            oof = pd.concat(
                [pd.read_parquet(path) for path in checkpoint_paths],
                ignore_index=True,
            )
            if (
                len(oof) != science["oofRows"]
                or oof["canonicalPaId"].duplicated().any()
                or set(oof["foldNumber"].unique()) != {item[0] for item in science["folds"]}
                or oof["gameDate"].astype(str).gt(science["development"][1]).any()
            ):
                raise Stage3ModelLaboratoryError(
                    "STAGE3_EXECUTABLE_ARTIFACT_OOF_RECONCILIATION_FAILED",
                    "OOF rows, canonical PA uniqueness, folds, or dates failed reconciliation.",
                    status_code=409,
                )
            probability_columns = [
                f"probability_{class_name}" for class_name in GOLD_CLASS_ORDER
            ]
            raw_oof_probabilities = oof[probability_columns].to_numpy(dtype=float)
            _validate_probability_matrix(
                raw_oof_probabilities,
                expected_rows=science["oofRows"],
            )
            raw_probability_validation = _raw_probability_diagnostics(
                raw_oof_probabilities
            )
            oof_path = staging / "oof-predictions.parquet"
            _write_parquet_atomic(oof, oof_path)
            shutil.rmtree(checkpoint_dir)
            _update_progress(
                database,
                job_id,
                started_clock,
                state="RUNNING",
                currentFold=None,
                foldRowsProcessed=0,
                oofRowsPersisted=science["oofRows"],
                finalFitState="RUNNING",
                latestCheckpoint="OOF_ARTIFACT_RECONCILED",
                message="OOF evidence matched accepted metrics and digest; fitting the final development-only pipeline.",
            )
            require_model_execution_authority(database, chain["resolvedAuthority"], actor_user_id)
            final_pipeline, final_fit = fit_stage3_pipeline(
                frame,
                model_family="xgboost",
                feature_set=chain["featureSetContract"],
                seed=science["candidate"]["seed"],
                hyperparameters=science["hyperparameters"],
                native_workers=reviewed_plan["execution"]["nativeWorkers"],
            )
            _update_progress(
                database,
                job_id,
                started_clock,
                finalFitState="RUNNING",
                latestCheckpoint=(
                    "FINAL_ESTIMATOR_FIT_COMPLETED_AWAITING_VALIDATION"
                ),
                modelFitsByPurpose={"oofFold": len(science["folds"]), "finalDevelopment": 1},
                message=(
                    "Final development-only estimator fit completed; validating and "
                    "staging the executable pipeline."
                ),
            )
            if final_fit["fitRows"] != science["development"][2]:
                raise Stage3ModelLaboratoryError(
                    "STAGE3_EXECUTABLE_ARTIFACT_FINAL_FIT_ROW_MISMATCH",
                    "The final pipeline was not fit on exactly the authorized development rows.",
                    status_code=409,
                )
            model_path = staging / "model.joblib"
            preprocessor_path = staging / "preprocessor.joblib"
            _atomic_joblib(model_path, final_pipeline)
            _atomic_joblib(preprocessor_path, final_pipeline.preprocessor)
            model_record = _file_record(model_path, staging)
            preprocessor_record = _file_record(preprocessor_path, staging)
            fixture_indices = np.unique(
                np.linspace(0, len(frame) - 1, num=16, dtype=np.int64)
            )
            fixture_frame = frame.iloc[fixture_indices].loc[:, features].copy()
            expected_probabilities = final_pipeline.predict_proba(fixture_frame)
            fixture = {
                "schemaVersion": "SPORTS_STAGE3_EXECUTABLE_ARTIFACT_FIXTURE_V1",
                "scope": "DEVELOPMENT_ONLY",
                "developmentCutoff": science["development"][1],
                "canonicalPaIds": frame.iloc[fixture_indices]["canonicalPaId"]
                .astype(str)
                .tolist(),
                "orderedFeatures": features,
                "targetOrder": list(GOLD_CLASS_ORDER),
                "rows": [
                    [_json_scalar(value) for value in row_values]
                    for row_values in fixture_frame.itertuples(index=False, name=None)
                ],
                "expectedProbabilities": expected_probabilities.tolist(),
                "finalOotTargetAccessed": False,
            }
            fixture_path = staging / "verification-fixture.json"
            _atomic_json(fixture_path, fixture)
            fixture_record = _file_record(fixture_path, staging)
            _update_progress(
                database,
                job_id,
                started_clock,
                finalFitState="COMPLETE",
                artifactStagingState="VERIFYING",
                reloadVerificationState="RUNNING",
                latestCheckpoint="FINAL_DEVELOPMENT_PIPELINE_STAGED",
                modelFitsByPurpose={"oofFold": len(science["folds"]), "finalDevelopment": 1},
                message="Final development-only pipeline staged; verifying in a fresh process.",
            )
            reload_result = _fresh_process_reload_check(
                staging,
                expected_model_sha256=model_record["sha256"],
                expected_fixture_sha256=fixture_record["sha256"],
            )
            verification_receipt = {
                "schemaVersion": EXECUTABLE_ARTIFACT_VERIFICATION_SCHEMA_VERSION,
                "status": "PASS",
                "createdAt": now_iso(),
                "projectId": project_id,
                "planChecksum": reviewed_plan["checksum"],
                "metricReproduction": metric_reproduction,
                "foldReproduction": fold_reproduction,
                "probabilityContract": _probability_contract(),
                "rawOofProbabilityValidation": raw_probability_validation,
                "legacyOofEvidence": {
                    "status": "PASS",
                    "expectedSha256": science["oofEvidenceSha256"],
                    "observedSha256": reproduced_digest,
                },
                "reloadVerification": reload_result,
                "verificationFixture": {
                    "status": reload_result["status"],
                    "maxAbsoluteDifference": reload_result[
                        "maxAbsoluteDifference"
                    ],
                    "rows": reload_result["rows"],
                },
                "featureOrderVerified": True,
                "targetOrderVerified": True,
                "probabilitiesVerified": True,
                "finalOotTargetAccessed": False,
                "providerCalls": 0,
                "modelsPromoted": 0,
            }
            verification_path = staging / "verification-receipt.json"
            _atomic_json(verification_path, verification_receipt)
            verification_record = _file_record(verification_path, staging)
            oof_record = _file_record(oof_path, staging)
            fold_files.sort(key=lambda item: int(item["foldNumber"]))
            artifact_id = (
                "stage3-executable-artifact-" + str(reviewed_plan["checksum"])[:32]
            )
            manifest = {
                "schemaVersion": EXECUTABLE_ARTIFACT_MANIFEST_SCHEMA_VERSION,
                "artifactId": artifact_id,
                "createdAt": now_iso(),
                "projectId": project_id,
                "executionActorUserId": actor_user_id,
                "acceptedScience": science,
                "acceptedScienceSha256": _sha(science),
                "authority": _authority_payload(chain),
                "selection": _selection_payload(chain),
                "candidate": reviewed_plan["candidate"],
                "orderedFeatures": features,
                "targetOrder": list(GOLD_CLASS_ORDER),
                "probabilityContract": _probability_contract(),
                "training": {
                    "scope": "DEVELOPMENT_ONLY",
                    "rows": science["development"][2],
                    "startDate": science["development"][0],
                    "cutoff": science["development"][1],
                    "seed": science["candidate"]["seed"],
                    "finalOotRowsUsed": 0,
                    "finalOotTargetAccessed": False,
                },
                "oof": {
                    "scope": "CHRONOLOGICAL_DEVELOPMENT_ONLY",
                    "rows": science["oofRows"],
                    "foldCount": len(science["folds"]),
                    "legacyEvidenceSha256": reproduced_digest,
                    "metrics": {
                        key: reproduced[key] for key in science["metrics"]
                    },
                    "folds": fold_reproduction,
                },
                "preprocessing": {
                    "kind": "REGISTERED_DEVELOPMENT_ONLY_TRANSFORMATION_CONTRACT",
                    "validationRowsUsedForParameters": 0,
                    "finalOotRowsUsedForParameters": 0,
                    "registeredOrderedTransformations": final_fit[
                        "registeredOrderedTransformations"
                    ],
                    "transformedFeatureCount": final_fit[
                        "transformedFeatureCount"
                    ],
                },
                "environment": _production_environment(chain),
                "files": {
                    "model": model_record,
                    "preprocessor": preprocessor_record,
                    "foldModels": fold_files,
                    "oofPredictions": oof_record,
                    "verificationFixture": fixture_record,
                    "verificationReceipt": verification_record,
                },
                "verification": {
                    "status": "PASS",
                    "metricReproduction": metric_reproduction,
                    "rawOofProbabilityValidation": raw_probability_validation,
                    "reloadVerification": reload_result,
                    "verificationFixture": verification_receipt[
                        "verificationFixture"
                    ],
                },
                "safety": _safety_payload(),
            }
            manifest_path = staging / "manifest.json"
            _atomic_json(manifest_path, manifest)
            manifest_sha = _sha_file(manifest_path)
            # Verify every staged member before the directory becomes public.
            if manifest_sha != _sha(manifest):
                raise Stage3ModelLaboratoryError(
                    "STAGE3_ARTIFACT_MANIFEST_CANONICALIZATION_FAILED",
                    "The written manifest differs from its canonical bytes.",
                    status_code=409,
                )
            _update_progress(
                database,
                job_id,
                started_clock,
                artifactStagingState="PUBLICATION_PENDING",
                reloadVerificationState="COMPLETE",
                latestCheckpoint="COMPLETE_BUNDLE_VERIFIED_AWAITING_PUBLICATION",
                stagedManifestSha256=manifest_sha,
                sourcePlanChecksum=reviewed_plan["checksum"],
                message=(
                    "The complete bundle and fresh-process receipt are staged; "
                    "publishing the immutable content-addressed directory."
                ),
            )
            publication = _finalize_staging(staging, manifest_sha)
            target = publication.artifact_path
            relative_path = target.relative_to(root).as_posix()
            loaded = load_executable_artifact(
                relative_path, expected_manifest_sha256=manifest_sha
            )
            final_observed = loaded.pipeline.predict_proba(fixture_frame)
            final_max_diff = float(
                np.max(np.abs(final_observed - expected_probabilities))
            )
            if final_max_diff > _METRIC_ATOL:
                raise Stage3ModelLaboratoryError(
                    "STAGE3_ARTIFACT_FINALIZED_FIXTURE_REPRODUCTION_FAILED",
                    "The finalized artifact did not reproduce its fixture.",
                    status_code=409,
                )
            artifact = {
                "artifactId": artifact_id,
                "status": "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED",
                "registryEntryId": chain["registryEntryId"],
                "researchHandoffId": chain["researchHandoffId"],
                "selectionDecisionId": chain["selectionDecisionId"],
                "candidateFingerprint": chain["candidateFingerprint"],
                "relativePath": relative_path,
                "manifestSha256": manifest_sha,
                "modelSha256": model_record["sha256"],
                "preprocessingSha256": preprocessor_record["sha256"],
                "oofArtifactSha256": oof_record["sha256"],
                "legacyOofEvidenceSha256": reproduced_digest,
                "oofRows": science["oofRows"],
                "metricReproduction": {
                    "status": "PASS",
                    "maxAbsoluteDifference": metric_reproduction[
                        "maxAbsoluteDifference"
                    ],
                },
                "reloadVerification": {
                    "status": "PASS",
                    "freshProcess": True,
                },
                "verificationFixture": {
                    "status": "PASS",
                    "maxAbsoluteDifference": final_max_diff,
                },
                "trainingRows": science["development"][2],
                "trainingCutoff": science["development"][1],
                "modelStatus": "RESEARCH_CHALLENGER",
                "promotionStatus": "NOT_PROMOTED",
                "finalOotLocked": True,
                "idempotentContentReplay": publication.reused,
                "publicationProtocol": publication.protocol,
                "publicationFallbackUsed": publication.fallback_used,
            }
            current = RunRepository(database).get(job_id) or {}
            current_artifacts = json_loads(current.get("artifacts_json"), {})
            _upsert_job(
                database,
                {
                    **dict(current),
                    "status": "COMPLETE",
                    "completed_at": now_iso(),
                    "parameters_json": reviewed_plan,
                    "metrics_json": {
                        **json_loads(current.get("metrics_json"), {}),
                        "state": "COMPLETE",
                        "currentFold": None,
                        "foldRowsProcessed": 0,
                        "oofRowsPersisted": science["oofRows"],
                        "finalFitState": "COMPLETE",
                        "artifactStagingState": "COMPLETE",
                        "reloadVerificationState": "COMPLETE",
                        "publicationProtocol": publication.protocol,
                        "publicationFallbackUsed": publication.fallback_used,
                        "elapsedSeconds": float(
                            time.perf_counter() - started_clock
                        ),
                        "latestCheckpoint": "IMMUTABLE_ARTIFACT_FINALIZED_AND_RELOADED",
                        "resumability": "NOT_REQUIRED_COMPLETE",
                        "modelFitsByPurpose": {
                            "oofFold": len(science["folds"]),
                            "finalDevelopment": 1,
                        },
                        "message": "Executable research artifact verified and materialized without promotion.",
                    },
                    "artifacts_json": {
                        **current_artifacts,
                        "artifact": artifact,
                        "safety": _safety_payload(),
                    },
                    "error_json": {},
                },
            )
    except LockBusy as exc:
        _fail_job(
            database,
            job_id,
            "STAGE3_EXECUTABLE_ARTIFACT_PROJECT_LOCK_BUSY",
            "Another project artifact fit owns the exclusive execution lock.",
        )
    except Stage3ModelLaboratoryError as exc:
        _fail_job(database, job_id, exc.code, str(exc))
    except Exception as exc:  # fail closed while preserving staging checkpoints
        _fail_job(
            database,
            job_id,
            "STAGE3_EXECUTABLE_ARTIFACT_EXECUTION_FAILED",
            str(exc),
        )


class _CancelAfterCheckpoint(RuntimeError):
    pass


def _path_is_reparse_point(path: Path) -> bool:
    try:
        metadata = path.lstat()
        file_attributes = int(getattr(metadata, "st_file_attributes", 0) or 0)
        if file_attributes & int(
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0) or 0
        ):
            return True
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(callable(is_junction) and is_junction())
    except FileNotFoundError:
        return False
    except OSError:
        return True


def _recovery_staging_path(
    source_job: Mapping[str, Any],
    source_job_id: str,
    *,
    inspect_contents: bool = True,
) -> Path:
    root = _artifact_root()
    artifacts = json_loads(source_job.get("artifacts_json"), {})
    raw_value = str(artifacts.get("stagingPath") or "")
    raw_path = Path(raw_value)
    if not raw_value or not raw_path.is_absolute() or _path_is_reparse_point(raw_path):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_STAGING_PATH_INVALID",
            "The failed job does not bind one ordinary absolute private staging path.",
            status_code=409,
        )
    staging = _require_contained(raw_path, root)
    private_root = _require_contained(root / "staging", root)
    if (
        staging.parent != private_root
        or not (
            staging.name == source_job_id
            or staging.name.startswith(f"{source_job_id}-")
        )
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_STAGING_PATH_INVALID",
            "The failed job staging path is not its direct private child under the artifact root.",
            status_code=409,
        )
    if staging.exists():
        if not staging.is_dir():
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_RECOVERY_STAGING_PATH_INVALID",
                "The failed job staging path is not a directory.",
                status_code=409,
            )
        if inspect_contents and any(
            _path_is_reparse_point(path) for path in staging.rglob("*")
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_RECOVERY_STAGING_REPARSE_POINT",
                "Publication recovery rejects symlinks and junctions in private staging.",
                status_code=409,
            )
    return staging


def _source_plan_for_recovery(
    source_job: Mapping[str, Any], expected_plan_checksum: str
) -> dict[str, Any]:
    plan = json_loads(source_job.get("parameters_json"), {})
    if (
        not isinstance(plan, Mapping)
        or plan.get("schemaVersion") != EXECUTABLE_ARTIFACT_PLAN_SCHEMA_VERSION
        or plan.get("projectId") != source_job.get("project_id")
        or plan.get("executionActorUserId", source_job.get("created_by")) != source_job.get("created_by")
        or plan.get("checksum") != expected_plan_checksum
        or not _SHA256_RE.fullmatch(expected_plan_checksum)
        or _sha(_plan_identity(plan)) != expected_plan_checksum
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_SOURCE_PLAN_INVALID",
            "The failed job does not preserve the exact reviewed artifact plan checksum.",
            status_code=409,
        )
    return dict(plan)


def _validate_recovery_source_progress(source_job: Mapping[str, Any]) -> None:
    plan = json_loads(source_job.get("parameters_json"), {})
    science = _manifest_science(plan)
    artifacts = json_loads(source_job.get("artifacts_json"), {})
    progress = json_loads(source_job.get("metrics_json"), {})
    fits = progress.get("modelFitsByPurpose") or {}
    try:
        exact_counts = (
            int(progress.get("oofRowsPersisted") or 0) == science["oofRows"]
            and int(fits.get("oofFold") or 0) == len(science["folds"])
            and int(fits.get("finalDevelopment") or 0) == 1
        )
    except (TypeError, ValueError, OverflowError):
        exact_counts = False
    if (
        str(source_job.get("status") or "").upper()
        not in {"FAILED", "INTERRUPTED"}
        or artifacts.get("artifact") is not None
        or progress.get("finalFitState") != "COMPLETE"
        or not exact_counts
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_SOURCE_JOB_INELIGIBLE",
            "Only a terminal no-artifact job with all registered OOF fits, one final fit, and complete OOF evidence may recover publication.",
            status_code=409,
        )


def _verify_recovery_bundle_binding(
    *,
    directory: Path,
    is_private_staging: bool,
    manifest_sha256: str,
    source_plan: Mapping[str, Any],
    chain: Mapping[str, Any],
) -> dict[str, Any]:
    if is_private_staging:
        verified = _verify_staged_bundle(
            directory, expected_manifest_sha256=manifest_sha256
        )
    else:
        verified = _verified_public_artifact_target(directory, manifest_sha256)
    manifest = verified["manifest"]
    expected_artifact_id = (
        "stage3-executable-artifact-" + str(source_plan["checksum"])[:32]
    )
    mismatches: list[str] = []
    if manifest.get("projectId") != chain.get("projectId"):
        mismatches.append("projectId")
    if manifest.get("artifactId") != expected_artifact_id:
        mismatches.append("artifactId")
    if manifest.get("authority") != _authority_payload(chain):
        mismatches.append("authority")
    if manifest.get("selection") != _selection_payload(chain):
        mismatches.append("selection")
    if manifest.get("authority") != source_plan.get("authority"):
        mismatches.append("sourcePlan.authority")
    if manifest.get("selection") != source_plan.get("selection"):
        mismatches.append("sourcePlan.selection")
    if manifest.get("candidate") != source_plan.get("candidate"):
        mismatches.append("sourcePlan.candidate")
    if manifest.get("environment") != source_plan.get("environment"):
        mismatches.append("sourcePlan.environment")
    if list(manifest.get("orderedFeatures") or []) != list(
        (chain.get("featureSetContract") or {}).get("orderedFeatures") or []
    ):
        mismatches.append("orderedFeatures")
    receipt_record = (manifest.get("files") or {}).get("verificationReceipt") or {}
    receipt_path = _require_contained(
        directory / str(receipt_record.get("relativePath") or "")
    )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_RECEIPT_INVALID",
            "The checksum-valid recovery source receipt is unreadable.",
            status_code=409,
        ) from exc
    if not isinstance(receipt, Mapping) or receipt.get("planChecksum") != source_plan.get(
        "checksum"
    ):
        mismatches.append("verificationReceipt.planChecksum")
    if mismatches:
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_AUTHORITY_MISMATCH",
            "Publication recovery stopped because staged evidence differs at: "
            + ", ".join(mismatches),
            status_code=409,
        )
    return verified


def _recovered_artifact_payload(
    *,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    relative_path: str,
    reload_result: Mapping[str, Any],
    publication: ArtifactPublication,
) -> dict[str, Any]:
    files = manifest["files"]
    verification = manifest["verification"]
    metric_reproduction = verification["metricReproduction"]
    return {
        "artifactId": manifest["artifactId"],
        "status": "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED",
        "registryEntryId": manifest["selection"]["registryEntryId"],
        "researchHandoffId": manifest["selection"]["researchHandoffId"],
        "selectionDecisionId": manifest["selection"]["selectionDecisionId"],
        "candidateFingerprint": manifest["selection"]["candidateFingerprint"],
        "relativePath": relative_path,
        "manifestSha256": manifest_sha256,
        "modelSha256": files["model"]["sha256"],
        "preprocessingSha256": files["preprocessor"]["sha256"],
        "oofArtifactSha256": files["oofPredictions"]["sha256"],
        "legacyOofEvidenceSha256": manifest["oof"]["legacyEvidenceSha256"],
        "oofRows": int(manifest["oof"]["rows"]),
        "metricReproduction": {
            "status": metric_reproduction["status"],
            "maxAbsoluteDifference": float(
                metric_reproduction["maxAbsoluteDifference"]
            ),
        },
        "reloadVerification": {
            "status": reload_result["status"],
            "freshProcess": bool(reload_result["freshProcess"]),
        },
        "verificationFixture": {
            "status": reload_result["status"],
            "maxAbsoluteDifference": float(reload_result["maxAbsoluteDifference"]),
        },
        "trainingRows": int(manifest["training"]["rows"]),
        "trainingCutoff": manifest["training"]["cutoff"],
        "modelStatus": "RESEARCH_CHALLENGER",
        "promotionStatus": "NOT_PROMOTED",
        "finalOotLocked": True,
        "idempotentContentReplay": bool(publication.reused),
        "publicationProtocol": publication.protocol,
        "publicationFallbackUsed": publication.fallback_used,
    }


def recover_failed_executable_artifact_publication(
    database: Database,
    project_id: str,
    source_job_id: str,
    payload: Mapping[str, Any],
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    """Publish an already-complete verified bundle without performing any fit."""

    if not isinstance(payload, Mapping):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_REQUEST_INVALID",
            "The publication-recovery request must be an object.",
        )
    allowed = {"expectedManifestSha256", "expectedSourcePlanChecksum"}
    unknown = sorted(set(payload) - allowed)
    manifest_sha256 = str(payload.get("expectedManifestSha256") or "")
    expected_plan_checksum = str(payload.get("expectedSourcePlanChecksum") or "")
    if unknown or not _SHA256_RE.fullmatch(manifest_sha256) or not _SHA256_RE.fullmatch(
        expected_plan_checksum
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_ARTIFACT_RECOVERY_EXACT_REVIEW_REQUIRED",
            "Recovery requires only the exact reviewed manifest and source-plan checksums.",
            status_code=409,
        )

    claim = _artifact_root() / "locks" / f"{project_id}.job-claim.lock"
    with _SUBMISSION_GUARD:
        try:
            with interprocess_lock(
                claim, blocking=True, timeout=10.0, stale_after=120.0
            ), interprocess_lock(
                _job_state_lock(project_id),
                blocking=True,
                timeout=10.0,
                stale_after=120.0,
            ), interprocess_lock(
                _project_fit_lock(project_id),
                blocking=True,
                timeout=30.0,
                stale_after=6 * 60 * 60,
            ):
                repository = RunRepository(database)
                source_job = repository.get(source_job_id)
                if (
                    source_job is None
                    or source_job.get("project_id") != project_id
                    or source_job.get("run_type") != EXECUTABLE_ARTIFACT_JOB_TYPE
                ):
                    raise Stage3ModelLaboratoryError(
                        "STAGE3_EXECUTABLE_ARTIFACT_JOB_NOT_FOUND",
                        "The project-scoped recovery source job was not found.",
                        status_code=404,
                    )
                _validate_recovery_source_progress(source_job)
                source_plan = _source_plan_for_recovery(
                    source_job, expected_plan_checksum
                )
                chain = _resolved_chain(database, project_id)
                require_model_execution_authority(database, chain["resolvedAuthority"], actor_user_id)
                science = _accepted_science(chain)

                for prior in repository.list_for_project(project_id):
                    prior_artifacts = json_loads(prior.get("artifacts_json"), {})
                    recovery = prior_artifacts.get("publicationRecovery") or {}
                    if (
                        prior.get("run_type") == EXECUTABLE_ARTIFACT_JOB_TYPE
                        and str(prior.get("status") or "").upper() == "COMPLETE"
                        and recovery.get("sourceJobId") == source_job_id
                        and recovery.get("manifestSha256") == manifest_sha256
                        and recovery.get("sourcePlanChecksum")
                        == expected_plan_checksum
                    ):
                        decoded = _decode_job(prior)
                        published_artifact = decoded.get("artifact") or {}
                        prior_verified = verify_artifact_bundle(
                            str(published_artifact.get("relativePath") or ""),
                            expected_manifest_sha256=str(
                                published_artifact.get("manifestSha256") or ""
                            ),
                        )
                        _verify_recovery_bundle_binding(
                            directory=prior_verified["artifactPath"],
                            is_private_staging=False,
                            manifest_sha256=manifest_sha256,
                            source_plan=source_plan,
                            chain=chain,
                        )
                        return {
                            "ok": True,
                            "job": {**decoded, "idempotentReplay": True},
                        }

                active = _active_job(database, project_id)
                if active is not None:
                    raise Stage3ModelLaboratoryError(
                        "STAGE3_EXECUTABLE_ARTIFACT_JOB_ALREADY_ACTIVE",
                        f"Artifact job {active.get('run_id')} is already active.",
                        status_code=409,
                    )

                root = _artifact_root()
                target = _content_address_target(root, manifest_sha256)
                staging = _recovery_staging_path(
                    source_job, source_job_id, inspect_contents=False
                )
                if target.exists() and _target_has_manifest_marker(target):
                    verified = _verify_recovery_bundle_binding(
                        directory=target,
                        is_private_staging=False,
                        manifest_sha256=manifest_sha256,
                        source_plan=source_plan,
                        chain=chain,
                    )
                elif staging.exists():
                    verified = _verify_recovery_bundle_binding(
                        directory=staging,
                        is_private_staging=True,
                        manifest_sha256=manifest_sha256,
                        source_plan=source_plan,
                        chain=chain,
                    )
                else:
                    raise Stage3ModelLaboratoryError(
                        "STAGE3_ARTIFACT_RECOVERY_EVIDENCE_MISSING",
                        "Neither the exact private staging bundle nor its public content address exists.",
                        status_code=409,
                    )
                manifest = verified["manifest"]
                recovery_job_id = (
                    "stage3-executable-artifact-recovery-" + uuid.uuid4().hex
                )
                recovery_started_clock = time.perf_counter()
                started_at = now_iso()
                source_error = json_loads(source_job.get("error_json"), {})
                recovery_evidence = {
                    "schemaVersion": EXECUTABLE_ARTIFACT_RECOVERY_SCHEMA_VERSION,
                    "sourceJobId": source_job_id,
                    "sourceActorUserId": source_job.get("created_by"),
                    "publicationActorUserId": actor_user_id,
                    "sourceJobStatus": str(source_job.get("status") or "").upper(),
                    "sourceJobError": source_error,
                    "manifestSha256": manifest_sha256,
                    "sourcePlanChecksum": expected_plan_checksum,
                    "recoveryImplementationSha256": _sha_file(Path(__file__)),
                    "fitPerformed": False,
                    "reusedModelFitsByPurpose": {
                        "oofFold": len(science["folds"]),
                        "finalDevelopment": 1,
                    },
                }
                recovery_row = _upsert_job(
                    database,
                    {
                        "run_id": recovery_job_id,
                        "project_id": project_id,
                        "run_type": EXECUTABLE_ARTIFACT_JOB_TYPE,
                        "workflow_type": (
                            "sports_stage3_executable_artifact_publication_recovery"
                        ),
                        "status": "RUNNING",
                        "started_at": started_at,
                        "completed_at": None,
                        "parameters_json": source_plan,
                        "metrics_json": {
                            "state": "RUNNING",
                            "startedAt": started_at,
                            "currentFold": None,
                            "foldRowsProcessed": 0,
                            "oofRowsPersisted": science["oofRows"],
                            "finalFitState": "COMPLETE",
                            "artifactStagingState": "VERIFYING",
                            "reloadVerificationState": "PENDING",
                            "elapsedSeconds": 0.0,
                            "latestCheckpoint": (
                                "VERIFIED_STAGED_BUNDLE_RECOVERY_CLAIMED"
                            ),
                            "resumability": "PUBLICATION_ONLY_NO_REFIT",
                            "modelFitsByPurpose": {
                                "oofFold": len(science["folds"]),
                                "finalDevelopment": 1,
                            },
                            "modelFitsPerformedByThisJob": {
                                "oofFold": 0,
                                "finalDevelopment": 0,
                            },
                            "message": (
                                "Recovering an exact verified staged bundle; no model fit is authorized."
                            ),
                        },
                        "artifacts_json": {
                            "coordinatorProcessId": os.getpid(),
                            "coordinatorInstanceId": _COORDINATOR_INSTANCE_ID,
                            "coordinatorRegisteredClock": time.time(),
                            "stagingPath": str(staging),
                            "artifact": None,
                            "publicationRecovery": recovery_evidence,
                            "safety": _safety_payload(),
                        },
                        "error_json": {},
                        "created_by": actor_user_id,
                    },
                )
                with _FUTURES_GUARD:
                    _SYNCHRONOUS_RECOVERY_JOBS.add(recovery_job_id)
                try:
                    if target.exists() and _target_has_manifest_marker(target):
                        publication = _reuse_verified_public_target(
                            staging, target, manifest_sha256
                        )
                    elif staging.exists():
                        publication = _finalize_staging(staging, manifest_sha256)
                    else:
                        raise Stage3ModelLaboratoryError(
                            "STAGE3_ARTIFACT_RECOVERY_EVIDENCE_MISSING",
                            "The verified recovery evidence disappeared before publication.",
                            status_code=409,
                        )
                    target = publication.artifact_path
                    relative_path = target.relative_to(root).as_posix()
                    final_verified = verify_artifact_bundle(
                        relative_path,
                        expected_manifest_sha256=manifest_sha256,
                    )
                    model_record = final_verified["manifest"]["files"]["model"]
                    fixture_record = final_verified["manifest"]["files"][
                        "verificationFixture"
                    ]
                    reload_result = _fresh_process_reload_check(
                        target,
                        expected_model_sha256=model_record["sha256"],
                        expected_fixture_sha256=fixture_record["sha256"],
                    )
                    if (
                        reload_result.get("status") != "PASS"
                        or reload_result.get("freshProcess") is not True
                    ):
                        raise Stage3ModelLaboratoryError(
                            "STAGE3_ARTIFACT_RECOVERY_RELOAD_FAILED",
                            "The recovered public artifact did not pass a fresh-process reload.",
                            status_code=409,
                        )
                    load_executable_artifact(
                        relative_path,
                        expected_manifest_sha256=manifest_sha256,
                    )
                    artifact_payload = _recovered_artifact_payload(
                        manifest=final_verified["manifest"],
                        manifest_sha256=manifest_sha256,
                        relative_path=relative_path,
                        reload_result=reload_result,
                        publication=publication,
                    )
                    completed_at = now_iso()
                    completed_recovery = {
                        **recovery_evidence,
                        "publishedAt": completed_at,
                        "publicRelativePath": relative_path,
                        "publicBundleVerified": True,
                        "freshProcessReloadVerified": True,
                        "existingTargetReused": bool(publication.reused),
                        "publicationProtocol": publication.protocol,
                        "publicationFallbackUsed": publication.fallback_used,
                        "privateStagingCleanupPending": staging.exists(),
                    }
                    completed = _upsert_job(
                        database,
                        {
                            **dict(recovery_row),
                            "status": "COMPLETE",
                            "completed_at": completed_at,
                            "parameters_json": source_plan,
                            "metrics_json": {
                                **json_loads(recovery_row.get("metrics_json"), {}),
                                "state": "COMPLETE",
                                "artifactStagingState": "COMPLETE",
                                "reloadVerificationState": "COMPLETE",
                                "publicationProtocol": publication.protocol,
                                "publicationFallbackUsed": (
                                    publication.fallback_used
                                ),
                                "elapsedSeconds": float(
                                    time.perf_counter() - recovery_started_clock
                                ),
                                "latestCheckpoint": (
                                    "IMMUTABLE_ARTIFACT_RECOVERED_AND_RELOADED"
                                ),
                                "resumability": "NOT_REQUIRED_COMPLETE",
                                "message": (
                                    "Verified staged evidence was published and reloaded without refitting."
                                ),
                            },
                            "artifacts_json": {
                                **json_loads(recovery_row.get("artifacts_json"), {}),
                                "artifact": artifact_payload,
                                "publicationRecovery": completed_recovery,
                                "safety": _safety_payload(),
                            },
                            "error_json": {},
                        },
                    )
                except Stage3ModelLaboratoryError as exc:
                    _fail_job(database, recovery_job_id, exc.code, str(exc))
                    raise
                except Exception as exc:
                    code = "STAGE3_ARTIFACT_PUBLICATION_RECOVERY_FAILED"
                    _fail_job(database, recovery_job_id, code, str(exc))
                    raise Stage3ModelLaboratoryError(
                        code,
                        "The verified publication recovery failed; no refit was performed and recoverable evidence remains preserved.",
                        status_code=503,
                    ) from exc
                finally:
                    with _FUTURES_GUARD:
                        _SYNCHRONOUS_RECOVERY_JOBS.discard(recovery_job_id)
                return {"ok": True, "job": _decode_job(completed)}
        except LockBusy as exc:
            raise Stage3ModelLaboratoryError(
                "STAGE3_ARTIFACT_PUBLICATION_RECOVERY_LOCK_BUSY",
                "Another artifact operation owns the project publication lock.",
                status_code=409,
            ) from exc


def list_executable_artifact_jobs(
    database: Database, project_id: str
) -> dict[str, Any]:
    _resolved_chain(database, project_id)
    return {
        "ok": True,
        "jobs": [_decode_job(row) for row in _artifact_rows(database, project_id)],
    }


def get_executable_artifact_job(
    database: Database, project_id: str, job_id: str
) -> dict[str, Any]:
    _resolved_chain(database, project_id)
    row = RunRepository(database).get(job_id)
    if (
        row is None
        or row.get("project_id") != project_id
        or row.get("run_type") != EXECUTABLE_ARTIFACT_JOB_TYPE
    ):
        raise Stage3ModelLaboratoryError(
            "STAGE3_EXECUTABLE_ARTIFACT_JOB_NOT_FOUND",
            "The project-scoped executable-artifact job was not found.",
            status_code=404,
        )
    return {"ok": True, "job": _decode_job(row)}


def cancel_unstarted_executable_artifact_work(
    database: Database,
    project_id: str,
    job_id: str,
    *,
    actor_user_id: str,
) -> dict[str, Any]:
    _resolved_chain(database, project_id)
    with interprocess_lock(
        _job_state_lock(project_id),
        blocking=True,
        timeout=10.0,
        stale_after=120.0,
    ):
        row = RunRepository(database).get(job_id)
        if (
            row is None
            or row.get("project_id") != project_id
            or row.get("run_type") != EXECUTABLE_ARTIFACT_JOB_TYPE
        ):
            raise Stage3ModelLaboratoryError(
                "STAGE3_EXECUTABLE_ARTIFACT_JOB_NOT_FOUND",
                "The project-scoped executable-artifact job was not found.",
                status_code=404,
            )
        status = str(row.get("status") or "").upper()
        if status in _TERMINAL_STATUSES:
            return {"ok": True, "job": _decode_job(row), "idempotentReplay": True}
        progress = json_loads(row.get("metrics_json"), {})
        updated = _upsert_job(
            database,
            {
                **dict(row),
                "status": "CANCEL_REQUESTED",
                "parameters_json": json_loads(row.get("parameters_json"), {}),
                "metrics_json": {
                    **progress,
                    "state": "CANCEL_REQUESTED",
                    "cancelRequestedAt": now_iso(),
                    "cancelRequestedByUserId": actor_user_id,
                    "message": "Cancellation requested for work that has not started; completed fold checkpoints will be retained.",
                },
                "artifacts_json": json_loads(row.get("artifacts_json"), {}),
                "error_json": {},
            },
        )
        with _FUTURES_GUARD:
            future = _FUTURES.get(job_id)
        if status == "QUEUED" and future is not None and future.cancel():
            _cancel_terminal(database, updated, before_start=True)
            updated = RunRepository(database).get(job_id) or updated
    return {"ok": True, "job": _decode_job(updated), "idempotentReplay": False}


@project_read_view
def executable_artifact_summary(
    database: Database, project_id: str
) -> dict[str, Any]:
    chain = _resolved_chain(database, project_id)
    rows = _artifact_rows(database, project_id)
    current_active = next(
        (
            _decode_job(row)
            for row in rows
            if str(row.get("status") or "").upper() in _ACTIVE_STATUSES
        ),
        None,
    )
    current_job = _decode_job(rows[0]) if rows else None
    completed = next(
        (
            _decode_job(row)
            for row in rows
            if str(row.get("status") or "").upper() == "COMPLETE"
        ),
        None,
    )
    artifact = (completed or {}).get("artifact")
    verified_artifact = None
    if artifact:
        try:
            verified = verify_artifact_bundle(
                str(artifact.get("relativePath") or ""),
                expected_manifest_sha256=str(artifact.get("manifestSha256") or ""),
            )
            manifest = verified["manifest"]
            if manifest.get("projectId") != project_id or manifest.get("authority") != _authority_payload(chain) or manifest.get("selection") != _selection_payload(chain):
                raise Stage3ModelLaboratoryError("STAGE3_ARTIFACT_PROJECT_AUTHORITY_MISMATCH", "The artifact does not match this project's current selected authority.", status_code=409)
            verified_artifact = artifact
        except Stage3ModelLaboratoryError as exc:
            verified_artifact = {
                **artifact,
                "status": "EXECUTABLE_RESEARCH_ARTIFACT_VERIFICATION_FAILED",
                "verificationError": exc.public_detail(),
            }
    artifact_ready = bool(
        verified_artifact
        and verified_artifact.get("status")
        == "EXECUTABLE_RESEARCH_ARTIFACT_MATERIALIZED"
    )
    progress = (current_job or {}).get("progress") or {}
    activity = {
        "modelFitsByPurpose": progress.get("modelFitsByPurpose")
        or {"oofFold": 0, "finalDevelopment": 0},
        "finalOotRowsAccessed": 0,
        "providerCalls": 0,
        "modelsPromoted": 0,
        "championsMutated": 0,
    }
    return {
        "ok": True,
        "schemaVersion": EXECUTABLE_ARTIFACT_SUMMARY_SCHEMA_VERSION,
        "authority": _authority_payload(chain),
        "selection": _selection_payload(chain),
        "artifact": verified_artifact,
        "currentJob": current_job,
        "gates": {
            "researchChallengerCurrent": True,
            "artifactPlanReady": not artifact_ready and current_active is None,
            "artifactJobActive": current_active is not None,
            "artifactReady": artifact_ready,
            "scoringReady": artifact_ready,
        },
        "limitations": [
            "FINAL_OOT_EVALUATION_NOT_AUTHORIZED",
            "MODEL_REMAINS_RESEARCH_CHALLENGER_NOT_PROMOTED",
            "PROSPECTIVE_GAME_SCORING_REQUIRES_SEPARATE_GOVERNED_PREGAME_LINEUP_AND_STARTER_EVIDENCE",
        ],
        "safety": _safety_payload(),
        "activity": activity,
    }


def _main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--verify-staged")
    parser.add_argument("--model-sha256")
    parser.add_argument("--fixture-sha256")
    args = parser.parse_args()
    if not args.verify_staged:
        return 2
    try:
        result = verify_staged_model(
            args.verify_staged,
            expected_model_sha256=str(args.model_sha256 or ""),
            expected_fixture_sha256=str(args.fixture_sha256 or ""),
        )
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "message": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


__all__ = [
    "EXECUTABLE_ARTIFACT_JOB_SCHEMA_VERSION",
    "EXECUTABLE_ARTIFACT_JOB_TYPE",
    "EXECUTABLE_ARTIFACT_MANIFEST_SCHEMA_VERSION",
    "EXECUTABLE_ARTIFACT_PLAN_SCHEMA_VERSION",
    "EXECUTABLE_ARTIFACT_RECOVERY_SCHEMA_VERSION",
    "EXECUTABLE_ARTIFACT_SUMMARY_SCHEMA_VERSION",
    "LoadedStage3Artifact",
    "cancel_unstarted_executable_artifact_work",
    "enqueue_executable_artifact_job",
    "executable_artifact_summary",
    "get_executable_artifact_job",
    "list_executable_artifact_jobs",
    "load_executable_artifact",
    "plan_executable_artifact",
    "recover_failed_executable_artifact_publication",
    "resolve_executable_artifact_path",
    "verify_artifact_bundle",
    "verify_staged_model",
]


if __name__ == "__main__":  # pragma: no cover - fresh-process verification entry
    raise SystemExit(_main())
