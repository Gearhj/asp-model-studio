"""Classify the bounded MLB Core screen and freeze up to three clean finalists."""

from __future__ import annotations

import json
from pathlib import Path

from server.persistence.db import Database, now_iso
from server.sports_current_statcast.stage3_candidate_evaluation import (
    _persist_object,
    project_candidate_evaluation,
    save_finalist_selection,
)
from server.sports_current_statcast.stage3_model_laboratory import (
    RUN_RECEIPT_SCHEMA_VERSION_V2,
    _read_runs,
    resolve_model_lab_authority,
)


PROJECT_ID = "asp-mtlozhdx"
ACTOR_USER_ID = "user_20e0f4e20ec9434c"
DATABASE_PATH = Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db")


def _binding(group: dict[str, object]) -> dict[str, object]:
    attempts = sorted(
        (
            dict(item)
            for item in group.get("attempts") or []
            if item.get("status") == "COMPLETE"
            and item.get("evidenceSource") == "CURRENT_BATCH"
        ),
        key=lambda item: (
            str(item.get("createdAt") or ""),
            str(item.get("attemptId") or ""),
            str(item.get("runReceiptSha256") or ""),
        ),
        reverse=True,
    )
    if not attempts:
        raise RuntimeError(
            f"No completed current-batch evidence for {group['candidateFingerprint']}."
        )
    representative = next(
        (
            item
            for item in attempts
            if item.get("attemptId") == group.get("representativeAttemptId")
            and item.get("runReceiptSha256")
            == group.get("immutableEvidenceIdentity")
        ),
        attempts[0],
    )
    return {
        "candidateFingerprint": group["candidateFingerprint"],
        "evidenceSource": "CURRENT_BATCH",
        "representativeAttemptId": representative["attemptId"],
        "immutableEvidenceIdentity": representative["runReceiptSha256"],
        "attemptEvidence": [
            {
                "attemptId": item["attemptId"],
                "runId": item["runId"],
                "runReceiptSha256": item["runReceiptSha256"],
            }
            for item in attempts
        ],
    }


def _requires_repair(group: dict[str, object]) -> bool:
    if group.get("status") != "COMPLETE":
        return True
    return any(
        str(item.get("code") or "") == "ConvergenceWarning"
        for item in group.get("warnings") or []
        if isinstance(item, dict)
    )


def _failed_attempt_evidence(group: dict[str, object]) -> list[dict[str, object]]:
    attempts = [
        item
        for item in group.get("attempts") or []
        if isinstance(item, dict) and item.get("status") == "FAILED"
    ]
    attempts.sort(
        key=lambda item: (str(item.get("createdAt") or ""), str(item.get("attemptId") or "")),
        reverse=True,
    )
    return [
        {
            "attemptId": item.get("attemptId"),
            "runId": item.get("runId"),
            "runReceiptSha256": item.get("runReceiptSha256"),
            "errorCode": item.get("errorCode"),
            "errorReason": item.get("errorReason"),
        }
        for item in attempts
    ]


def main() -> None:
    database = Database(DATABASE_PATH)
    resolved = resolve_model_lab_authority(database, PROJECT_ID)
    evaluation = project_candidate_evaluation(database, PROJECT_ID)
    terminal_runs = [
        item
        for item in _read_runs(PROJECT_ID, resolved)
        if item.get("schemaVersion") == RUN_RECEIPT_SCHEMA_VERSION_V2
    ]
    if not terminal_runs:
        raise RuntimeError("The terminal Core screen receipt is unavailable.")
    terminal_run = terminal_runs[0]
    seeds = {
        int(experiment["seed"])
        for item in terminal_runs
        for experiment in (item.get("plan") or {}).get("experiments") or []
        if experiment.get("seed") is not None
    }
    if len(seeds) != 1:
        raise RuntimeError(
            f"The screen receipts do not reconcile to one deterministic seed: {sorted(seeds)}"
        )
    deterministic_seed = next(iter(seeds))
    groups = [dict(item) for item in evaluation.get("currentBatches") or []]
    expected_families = {
        "class_frequency_null",
        "multinomial_logistic",
        "histogram_gradient_boosting",
        "random_forest",
        "sgd_classifier",
    }
    observed_families = {str(item.get("modelFamily") or "") for item in groups}
    if observed_families != expected_families:
        raise RuntimeError(
            "The exact five-family Core screen is not terminal and fully visible. "
            f"Observed: {sorted(observed_families)}"
        )
    successful_challengers = sorted(
        (
            item
            for item in groups
            if item.get("modelFamily") != "class_frequency_null"
            and not _requires_repair(item)
            and item.get("meanOofLogLoss") is not None
        ),
        key=lambda item: (
            float(item["meanOofLogLoss"]),
            float(item.get("foldStandardDeviation") or float("inf")),
            float(item.get("ece") or float("inf")),
            str(item.get("candidateFingerprint") or ""),
        ),
    )
    if len(successful_challengers) < 2:
        raise RuntimeError(
            "Fewer than two completed non-null challengers are available; repair before tuning."
        )
    finalists = successful_challengers[:3]
    finalist_fingerprints = {
        str(item["candidateFingerprint"]) for item in finalists
    }
    selection = save_finalist_selection(
        database,
        PROJECT_ID,
        {
            "candidateFingerprints": [
                item["candidateFingerprint"] for item in finalists
            ],
            "candidateSelections": [_binding(item) for item in finalists],
            "rationale": (
                "Advance up to the three strongest clean completed MLB Core Development-only "
                "screen candidates by OOF multiclass log loss, using fold stability and "
                "ECE as deterministic tie-break diagnostics; this is not champion or "
                "promotion authority."
            ),
            "evaluationBatch": "CURRENT_BATCH",
        },
        actor_user_id=ACTOR_USER_ID,
    )["selection"]
    classifications = []
    for item in sorted(groups, key=lambda row: str(row.get("modelFamily") or "")):
        family = str(item.get("modelFamily") or "")
        fingerprint = str(item.get("candidateFingerprint") or "")
        failed_attempts = _failed_attempt_evidence(item)
        representative_failed = item.get("status") != "COMPLETE"
        representative_error = failed_attempts[0] if representative_failed and failed_attempts else {}
        if family == "class_frequency_null":
            disposition = "RETAIN_AS_BASELINE"
        elif _requires_repair(item):
            disposition = "NEEDS_REPAIR"
        elif fingerprint in finalist_fingerprints:
            disposition = "ADVANCE_TO_TUNING"
        else:
            disposition = "DROP_AFTER_SCREEN"
        classifications.append(
            {
                "modelFamily": family,
                "candidateFingerprint": fingerprint,
                "immutableEvidenceIdentity": item.get("immutableEvidenceIdentity"),
                "status": item.get("status"),
                "disposition": disposition,
                "meanOofLogLoss": item.get("meanOofLogLoss"),
                "foldStandardDeviation": item.get("foldStandardDeviation"),
                "summedBrier": item.get("summedBrier"),
                "ece": item.get("ece"),
                "macroOvrRocAuc": item.get("macroOvrRocAuc"),
                "macroF1Diagnostic": item.get("macroF1"),
                "accuracyDiagnostic": item.get("accuracy"),
                "runtimeMs": item.get("runtimeMs"),
                "warnings": item.get("warnings") or [],
                "errorCode": representative_error.get("errorCode") if representative_failed else None,
                "errorReason": representative_error.get("errorReason") if representative_failed else None,
                "failedAttemptEvidence": failed_attempts,
            }
        )
    body = {
        "schemaVersion": "MLB_CORE_CHALLENGER_SCREEN_DECISION_V1",
        "decisionId": "MLB_CORE_CHALLENGER_FIRST_SCREEN_DECISION",
        "createdAt": now_iso(),
        "createdByUserId": ACTOR_USER_ID,
        "projectId": PROJECT_ID,
        "authority": evaluation["authority"],
        "population": evaluation["population"],
        "authorityBindings": {
            "startingGitHead": "711c41e23b340cd859528ba3cbd8c5e2b573f912",
            "modelLabImplementationSha256": (
                terminal_run.get("environment") or {}
            ).get("modelLabImplementationSha256"),
            "datasetId": resolved.eda_authority.source_dataset_id,
            "datasetVersionId": resolved.eda_authority.dataset_version_id,
            "sourceManifestSha256": resolved.eda_authority.source_manifest_sha,
            "goldManifestSha256": resolved.eda_authority.gold_manifest_sha,
            "treatmentSpecificationId": (
                resolved.treatment_specification or {}
            ).get("specificationId"),
            "treatmentReceiptChecksum": (
                resolved.treatment_specification or {}
            ).get("checksum"),
            "treatmentManifestChecksum": (
                resolved.treatment_specification or {}
            ).get("manifestChecksum"),
            "featureSetId": resolved.feature_sets[0].get("featureSetId"),
            "featureSetChecksum": resolved.feature_sets[0].get("checksum"),
            "splitContractId": resolved.split.get("contractId"),
            "splitContractChecksum": resolved.split.get("checksum"),
            "wave1PriorAuthorityId": (
                (resolved.treatment_specification or {}).get("manifest") or {}
            ).get("priorAuthority", {}).get("wave1AuthorityId"),
            "wave2PriorAuthorityId": (
                (resolved.treatment_specification or {}).get("manifest") or {}
            ).get("priorAuthority", {}).get("authorityId"),
            "modelRunId": terminal_run.get("runId"),
            "modelRunReceiptSha256": terminal_run.get("runReceiptSha256"),
            "modelPlanId": (terminal_run.get("plan") or {}).get("planId"),
            "screenRunReceipts": [
                {
                    "runId": item.get("runId"),
                    "runReceiptSha256": item.get("runReceiptSha256"),
                    "status": item.get("status"),
                    "modelFamilies": [
                        candidate.get("modelFamily")
                        for candidate in item.get("candidates") or []
                    ],
                }
                for item in terminal_runs
            ],
            "deterministicSeed": deterministic_seed,
        },
        "rights": {
            "effectiveStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
            "permittedUse": "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
            "attributionObligationsRetained": True,
            "commercialRightsReviewRequired": True,
            "sourceAuthorityIntersection": ["FD1_LAHMAN", "MLB_STATCAST"],
        },
        "classificationRule": (
            "BASELINE_RETAINED; FAILED_OR_MATERIAL_CONVERGENCE_WARNING_NEEDS_REPAIR; "
            "TOP_THREE_CLEAN_COMPLETED_NON_NULL_BY_LOG_LOSS_THEN_FOLD_SD_THEN_ECE_"
            "ADVANCE; REMAINDER_DROP"
        ),
        "classifications": classifications,
        "finalistSelectionId": selection["selectionId"],
        "finalistSelectionReceiptSha256": selection["receiptSha256"],
        "advancedCount": len(finalists),
        "championSelected": False,
        "promotionStatus": "NOT_PROMOTED",
        "exportStatus": "NOT_EXPORTED",
        "finalOotLocked": True,
        "finalOotTargetAccessed": False,
        "nextSingleStep": "BOUNDED_TUNING_OF_ADVANCE_TO_TUNING_CANDIDATES",
    }
    decision = _persist_object("screen-decisions", body)
    print(json.dumps(decision, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
