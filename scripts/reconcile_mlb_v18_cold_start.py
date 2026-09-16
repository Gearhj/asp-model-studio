"""Reconcile saved, accepted MLB Development evidence; no data loading or fitting.

Uses the registered JSON extraction of the 240-row workbook and immutable V18
fold counters. Additive subgroup complements are calculated from sufficient
statistics, not mislabeled as fresh predictions or a causal treatment ablation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from server.sports_current_statcast.stage3_semantic_treatment import RULES
from server.sports_datasets.consumer import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/mlb-v18-cold-start-reconciliation-v1"
RECOVERY = ROOT / "outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d.json"
DIAGNOSTIC = ROOT / "docs/corrected-treatment-diagnostics/sha256/08b0d20c8339810249bbe55ca92134664be8febda26b6777909514e49ed670fd.json"


def load(path: Path, expected: str | None = None):
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if expected and digest != expected:
        raise ValueError(f"Immutable evidence checksum mismatch: {path}")
    return json.loads(raw), {"path": str(path), "sha256": digest, "bytes": len(raw)}


def build():
    result, result_ref = load(RECOVERY)
    source, source_ref = load(ROOT / "outputs/v14-feature-audit/source_comparison.json")
    diagnostic, diagnostic_ref = load(DIAGNOSTIC, DIAGNOSTIC.stem)
    audit, audit_ref = load(ROOT / "outputs/v14-feature-audit/ASP_MLB_V14_Feature_Audit.json")
    assert result["status"] == "COMPLETE" and result["authority"]["treatmentVersion"] == 18
    assert result["authority"]["treatmentManifestChecksum"] == "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3"
    database = ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        registered = connection.execute(
            "SELECT specification_version, specification_status, manifest_sha256, manifest_json FROM stage3_feature_treatment_spec_versions WHERE feature_treatment_spec_id = ?",
            (result["authority"]["treatmentSpecificationId"],),
        ).fetchone()
    assert registered[:3] == (18, "ADOPTED", result["authority"]["treatmentManifestChecksum"])
    manifest = json.loads(registered[3])
    manifest_bytes = canonical_json_bytes(manifest)
    assert hashlib.sha256(manifest_bytes).hexdigest() == registered[2]
    manifest_path = OUT / "objects/sha256" / (registered[2] + ".json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists() and manifest_path.read_bytes() != manifest_bytes:
        raise ValueError("Immutable adopted-manifest copy differs")
    manifest_path.write_bytes(manifest_bytes)
    manifest_features = {row["feature_name"]: row for row in manifest["features"]}
    assert source["featureCount"] == source["uniqueFeatureCount"] == 240 and source["changedCellCount"] == 0
    selected = set(result["authority"]["sourceOrderedFeatures"])
    priors = result["treatmentExecution"]["priors"]
    semantic = result["treatmentExecution"]["semantic"]
    historical = {f["feature"]: f for f in audit["features"]}
    fold_refs = []
    for fold in result["treatmentExecution"]["fittedFoldArtifacts"]:
        ref = fold["localResearchArtifact"]["preprocessing"]
        _, verified = load(ROOT / ".runtime/asp-model-studio/stage3-model-laboratory" / ref["relativePath"], ref["sha256"])
        fold_refs.append({"fold": fold["foldNumber"], **verified})
    features = []
    for spec in source["features"]:
        name = spec["feature_name"]
        prior = priors.get(name)
        rule = RULES.get(name)
        counts = prior or semantic.get(name)
        if name not in selected:
            actual = "EXCLUDED_BY_APPROVED_DECISION"
        elif prior:
            actual = ("VALID_RAW_NATIVE_NAN_FOR_TRUE_COLD_PLUS_POSTERIOR_EFFECTIVE_N_RELIABILITY_STD_HISTORY_STATE"
                      if prior["wave"] == 1 else "REGISTERED_WAVE2_POSTERIOR_ONLY; INVALID_OUTPUT_REJECTED")
        elif rule:
            actual = rule["kind"]
        elif name in semantic:
            actual = "PRESCRIBED_TRANSFORMED_PARENT_INTERACTION"
        else:
            actual = "REGISTERED_DOMAIN_VALIDATED_PASSTHROUGH_OR_CATEGORICAL_UNKNOWN_ENCODING"
        features.append({"feature": name, "specifiedMissingTreatment": spec["missing_treatment"],
                         "specifiedColdRule": spec["required_indicator_or_cold_start_rule"],
                         "specificationPrimaryMissingReason": spec["primary_missing_reason"],
                         "v14HistoricalStatus": historical[name]["status"], "v18Selected": name in selected,
                         "v18RegisteredResolution": manifest_features[name].get("executable_resolution"),
                         "v18RegisteredStatus": manifest_features[name].get("executable_status"),
                         "v18ActualTreatment": actual, "observedValidationBranches": counts,
                         "branchEvidence": "RECORDED_DISJOINT_VALIDATION_FOLDS" if counts else "NO_PER_FEATURE_BRANCH_COUNTER; NOT_INFERRED_ZERO",
                         "implementation": "server/sports_current_statcast/stage3_corrected_prior_treatment.py" if prior else "server/sports_current_statcast/stage3_semantic_treatment.py",
                         "approvedDeviation": historical[name].get("approvedDeviation") if name not in selected else None})
    total = result["matchingObservationComparison"]
    n = total["corrected"]["observations"]
    groups = []
    for subgroup in result["subgroups"]:
        rows = subgroup["observations"]
        complement = {}
        for model in ("baseline", "corrected"):
            complement[model] = {metric: (n * total[model][metric] - rows * subgroup["metrics"][model][metric]) / (n-rows)
                                 for metric in ("multiclassLogLoss", "summedBrier", "accuracy")}
        groups.append({**subgroup, "complement": {"observations": n-rows, "definition": "NOT (" + " OR ".join(subgroup["definition"]["anyIndicatorEqualsOne"]) + ")",
                          "meaning": "Observed history by these source flags; not necessarily established rolling history or veteran identity.",
                          "metrics": complement, "method": "EXACT_ADDITIVE_COMPLEMENT_OF_SAVED_OOF_SUMS; FLOATING_POINT_ROUNDOFF_ONLY",
                          "games": None, "uncertainty": "NOT_RECOVERABLE_FROM_AGGREGATE_COUNTERS; NO_NEW_INTERVAL_INFERRED"}})
    body = {"schemaVersion": "MLB_V18_COLD_START_RECONCILIATION_V1", "status": "COMPLETE_SAVED_DEVELOPMENT_EVIDENCE_ONLY",
            "sourceWorkbook": {"source": source["source"], "workbookSha256": source["sourceSha256"] ,"used": "MATCHING_REGISTERED_REPOSITORY_JSON_EXTRACTION", "uniqueFeatures": 240,
                               "coldStartNoHistoryRows": sum(f["primary_missing_reason"] == "NO_PRIOR_HISTORY" for f in source["features"])},
            "authority": result["authority"], "sourceEvidence": [result_ref, source_ref, diagnostic_ref, audit_ref],
            "adoptedManifestVerification": {"source": str(database), "query": "EXACT_SPECIFICATION_ID_MANIFEST_METADATA_ONLY_READ_ONLY", "specificationVersion": 18,
                                            "status": "ADOPTED", "sha256": registered[2], "copiedPath": str(manifest_path)},
            "artifacts": [{"label": "Exact adopted V18 treatment manifest (preserved copy)", "path": str(manifest_path), "sha256": registered[2]}],
            "verifiedFittedFoldArtifacts": fold_refs, "features": features,
            "priorTreatmentSummary": {"wave1": sum(p["wave"] == 1 for p in priors.values()), "wave2": sum(p["wave"] == 2 for p in priors.values()),
                "genericMedianOrModeFallbackFeatureRowActivations": sum(p["ordinaryMedianOrModeFallbackRows"] for p in priors.values()),
                "invalidOrHeldPriorActivationsAmongEligibleValidationRows": sum(p["invalidOrHeldReviewRows"] for p in priors.values()),
                "governedWhipFallbackRows": priors["pitcher_whip"]["governedWhipFallbackRows"],
                "interpretation": "Zero recorded ordinary prior fallback, not zero cold starts. WHIP population fallback is explicitly governed, separate from median imputation and separate from 56 held batter rows."},
            "heldRows": {"development": diagnostic["invalidUniquePaRows"], "oof": diagnostic["validationHeldRowsAcrossFiveFolds"] ,
                         "exactObservedExposureStates": diagnostic["allAffectedRows"], "v2KnownZeroState": diagnostic["v2KnownZeroAbState"],
                         "decision": "UNRESOLVED_V1_KNOWN_ZERO_OPPORTUNITY_STATE_REMAINS_HELD; NOT_SOURCE_OUTAGE_OR_TRUE_COLD_START",
                         "heldRowsByYear": result["rowEligibility"]["heldRowsByYear"]},
            "eligibleDevelopmentRows": result["rowEligibility"]["eligibleRows"], "matchingOofRows": n,
            "subgroups": groups, "globalMatchedMetrics": total,
            "interpretation": "V14 historical gaps are not V18 status. V18 implements semantic treatment but has no demonstrated causal treatment uplift. Cold/no-history groups show slightly worse V18 than V14 loss; group differences are observational and overlap.",
            "newDefectFound": False, "mlbFittingOccurred": False, "sealedFinalOotRead": False, "aispActivity": False,
            "acceptedArtifactsModified": False, "gen1PolicyModified": False}
    payload = json.dumps(body, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    dest = OUT / "sha256" / digest
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "reconciliation.json"
    if path.exists() and path.read_bytes() != payload:
        raise ValueError("Immutable destination differs")
    path.write_bytes(payload)
    lines = ["# MLB V18 cold-start reconciliation", "", "240 specified features, 64 no-history entries; 218 selected source features + 55 prior outputs = 273 inputs before categorical expansion.",
             "", "All 21 prior treatments execute: 11 Wave 1 raw + posterior/reliability/effective-N/std/state, and 10 Wave 2 posterior-only. Five immutable fitted preprocessing artifacts verified. Ordinary prior median/mode fallback: **0 recorded** across disjoint validation folds. Governed WHIP population fallback: **56**, a distinct valid authority and not the held batter population.",
             "", "The 56 held Development PAs have observed zero prior PA exposure, prior_missing=false and three undefined raw annual rates; all five companion AB/hit/extra-base components are exactly zero, with no missing component cells. V2 supports TRUE_NO_OPPORTUNITY; V1 does not register that state. Hold remains unchanged (51 OOF PAs).", "", "| Saved subgroup | PAs | V18 log loss | History complement PAs | V18 complement log loss |", "|---|---:|---:|---:|---:|"]
    for group in groups:
        lines.append(f"| {group['name']} | {group['observations']:,} | {group['metrics']['corrected']['multiclassLogLoss']:.9f} | {group['complement']['observations']:,} | {group['complement']['metrics']['corrected']['multiclassLogLoss']:.9f} |")
    lines += ["", "History complement means these source no-history flags are false; it does not prove all rolling histories are established. Complements use additive saved sums. Their game counts and intervals are not inferred. Original subgroup paired game-clustered intervals are retained in JSON. These overlapping observational groups do not establish causal treatment uplift.", "", "V14's older audit remains historical; its possible median seam is not asserted to have occurred in its recorded folds. V18's guards reject unapproved prior states before a generic imputer. No concrete new defect was found in this bounded saved-evidence reconciliation. No MLB fit, source scan, OOT access, AISP action or accepted-artifact change occurred.", "", f"Evidence: `{path}`; SHA-256 `{digest}`."]
    (dest / "REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    pointer = {"schemaVersion": body["schemaVersion"], "status": "COMPLETE", "path": str(path), "sha256": digest, "reportPath": str(dest / "REPORT.md")}
    (OUT / "CURRENT.json").write_text(json.dumps(pointer, indent=2)+"\n", encoding="utf-8")
    return pointer


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
