"""Preview or append the exact authorized corrected treatment/feature/split.

Default is read-only. ``--apply`` performs only the authorized registration and
adoption; it never launches a model or reads Final OOT feature/target payloads.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNTIME = ROOT / ".runtime" / "asp-model-studio"
os.environ.setdefault("ATLAS_SECURITY_ROOT", str(RUNTIME / "security"))
os.environ.setdefault("ATLAS_SECURITY_DB_PATH", str(RUNTIME / "security" / "asp_model_studio_security.db"))

from server.persistence.db import Database
from server.persistence.repositories.stage3_feature_set_repository import NO_CURRENT_FEATURE_SET, Stage3FeatureSetRepository
from server.persistence.repositories.stage3_split_contract_repository import Stage3SplitContractRepository
from server.persistence.repositories.stage3_treatment_repository import Stage3TreatmentRepository
from server.sports_current_statcast import stage3_feature_engineering as features
from server.sports_current_statcast import stage3_split_balance as splits
from server.sports_current_statcast.stage3_corrected_treatment_spec import CORRECTED_FEATURE_SET_KEY, REFERENCE_V14_ID, SEMANTIC_TREATMENT_VERSION, corrected_transformation_contracts
from server.sports_current_statcast.stage3_feature_treatment_spec import adopt_treatment_specification, compile_project_specification, save_treatment_specification_draft

PROJECT_ID = "asp-mtlozhdx"
REFERENCE_SPLIT_ID = "stage3-split-contract-87fdac0b668d4c9b862a2fd8f0760342"
DEFAULT_DATABASE_PATH = Path(r".runtime\asp-model-studio\persistence\asp_model_studio.db")


def same_fold_population(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    """Feature binding changes its fold hash, never its population or policies."""
    def population(folds: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{key: value for key, value in fold.items() if key not in {"checksum", "selectedFeatureSetIds"}} for fold in folds]
    return population(left) == population(right)


def register_corrected_authorities(database: Database, *, actor_user_id: str, apply: bool = False) -> dict[str, Any]:
    authority = features.eda._resolve_authority(database, PROJECT_ID)
    authority_key = features._authority_payload(authority)["authorityKey"]
    treatment_repository = Stage3TreatmentRepository(database)
    before = treatment_repository.combined_spec_state(PROJECT_ID, authority.review_digest)
    predecessor = next((item for item in before["history"] if item["specificationId"] == REFERENCE_V14_ID), None)
    if predecessor is None:
        raise RuntimeError("Exact V14 treatment predecessor is absent.")
    compiled = compile_project_specification(database, PROJECT_ID, semantic_treatment_version=SEMANTIC_TREATMENT_VERSION)
    if not compiled["canAdopt"]:
        raise RuntimeError("Corrected treatment has unresolved blockers: " + "; ".join(compiled["blockers"]))
    schema = compiled["modelFeatureSchema"]
    transformations = corrected_transformation_contracts(compiled)
    split_repository = Stage3SplitContractRepository(database)
    split_before = split_repository.contract_state(PROJECT_ID, authority.review_digest)
    reference_split = next((item for item in split_before["history"] if item["contractId"] == REFERENCE_SPLIT_ID), None)
    if reference_split is None:
        raise RuntimeError("Exact V14 five-fold split predecessor is absent.")
    reference_folds = reference_split["contract"]["folds"]
    if len(reference_folds) != 5:
        raise RuntimeError("The reference split is not the authorized five-fold contract.")
    preview = {
        "projectId": PROJECT_ID,
        "mode": "APPLY" if apply else "READ_ONLY_PREVIEW",
        "semanticTreatmentVersion": SEMANTIC_TREATMENT_VERSION,
        "compiledTreatmentId": compiled["specificationId"],
        "treatmentManifestChecksum": compiled["manifestChecksum"],
        "modelFeatureSchemaChecksum": schema["schemaChecksum"],
        "sourceFeatureCount": schema["sourceFeatureCount"],
        "modelFeatureCount": schema["modelFeatureCount"],
        "orderedFeatures": schema["orderedFeatures"],
        "sourceOrderedFeatures": schema["sourceOrderedFeatures"],
        "referenceSplitId": REFERENCE_SPLIT_ID,
        "referenceFolds": reference_folds,
        "preservedExclusions": compiled["correctedTreatment"]["preservedExcludedWorkbookFeatures"],
        "decision": compiled["correctedTreatmentDecision"],
        "modelFitsStarted": 0,
        "finalOotPayloadRowsRead": 0,
    }
    if not apply:
        return preview
    adopted = before.get("adopted")
    if not adopted or adopted["manifestChecksum"] != compiled["manifestChecksum"]:
        save_treatment_specification_draft(database, PROJECT_ID, {
            "authorityKey": authority_key,
            "semanticTreatmentVersion": SEMANTIC_TREATMENT_VERSION,
            "expectedManifestChecksum": compiled["manifestChecksum"],
        }, actor_user_id=actor_user_id)
        draft = treatment_repository.combined_spec_state(PROJECT_ID, authority.review_digest)["latestDraft"]
        adopt_treatment_specification(database, PROJECT_ID, {
            "authorityKey": authority_key,
            "semanticTreatmentVersion": SEMANTIC_TREATMENT_VERSION,
            "specificationDraftId": draft["specificationId"],
            "expectedManifestChecksum": compiled["manifestChecksum"],
        }, actor_user_id=actor_user_id)
        adopted = treatment_repository.combined_spec_state(PROJECT_ID, authority.review_digest)["adopted"]
    feature_repository = Stage3FeatureSetRepository(database)
    feature_state = feature_repository.feature_set_state(PROJECT_ID, authority.review_digest)
    registered = next((item for item in feature_state.get("registeredSets", []) if item.get("featureSetKey") == CORRECTED_FEATURE_SET_KEY and item.get("transformationContracts") == transformations), None)
    if registered is None:
        draft_result = features.save_feature_set_draft(PROJECT_ID, database, {
            "authorityKey": authority_key,
            "featureSetKey": CORRECTED_FEATURE_SET_KEY,
            "name": "MLB Core Challenger — Corrected Treatment",
            "description": "218 authorized source features and 55 required Wave 1 derived outputs; 273 explicit model inputs before fold-local one-hot encoding.",
            "notes": "Exact semantic-treatment successor. Parent-only ablations deferred by user; V2 optional auxiliary channels not selected; Final OOT sealed.",
            "orderedFeatures": schema["orderedFeatures"],
            "transformationContracts": transformations,
            "expectedChecksum": (feature_state.get("expectedChecksumByKey") or {}).get(CORRECTED_FEATURE_SET_KEY, NO_CURRENT_FEATURE_SET),
        }, actor_user_id)
        draft = draft_result["data"]["featureSet"]
        registered = features.register_feature_set(PROJECT_ID, database, {
            "authorityKey": authority_key,
            "draftFeatureSetId": draft["featureSetId"],
            "expectedChecksum": draft["checksum"],
        }, actor_user_id)["data"]["featureSet"]
    state = split_repository.contract_state(PROJECT_ID, authority.review_digest)
    current = state.get("currentRegistered")
    if not current or list(current.get("selectedFeatureSetIds", [])) != [registered["featureSetId"]]:
        split_draft_result = splits.save_split_draft(PROJECT_ID, database, {
            "authorityKey": authority_key,
            "mode": "AUTOMATIC",
            "foldCount": 5,
            "trainingPolicy": "EXPANDING_WINDOW",
            "classPolicy": "NATURAL_BASE_RATES",
            "deterministicSeed": 20260906,
            "selectedFeatureSetIds": [registered["featureSetId"]],
            "expectedChecksum": state["expectedChecksum"],
            "notes": "Corrected-treatment comparison: preserve exact V14 game-grouped five chronological folds and Development population; one HGB configuration only; OOT sealed.",
        }, actor_user_id)
        split_draft = split_draft_result["data"]["contract"]
        if not same_fold_population(split_draft["contract"]["folds"], reference_folds):
            raise RuntimeError("The new split draft changes reference fold membership/boundaries; registration refused.")
        current = splits.register_split_contract(PROJECT_ID, database, {
            "authorityKey": authority_key,
            "contractId": split_draft["contractId"],
            "expectedChecksum": split_draft["checksum"],
        }, actor_user_id)["data"]["contract"]
    if not same_fold_population(current["contract"]["folds"], reference_folds):
        raise RuntimeError("Corrected split does not preserve the exact reference chronological folds.")
    after = treatment_repository.combined_spec_state(PROJECT_ID, authority.review_digest)
    preserved = next(item for item in after["history"] if item["specificationId"] == REFERENCE_V14_ID)
    if preserved != predecessor:
        raise RuntimeError("V14 immutable predecessor evidence changed unexpectedly.")
    return {**preview, "adoptedTreatment": adopted, "featureSet": registered, "splitContract": current, "v14Preserved": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--actor-user-id", default="user_20e0f4e20ec9434c")
    parser.add_argument("--apply", action="store_true", help="Append and adopt the authorized corrected treatment and register its feature/split authorities.")
    arguments = parser.parse_args()
    result = register_corrected_authorities(Database(arguments.database), actor_user_id=arguments.actor_user_id, apply=arguments.apply)
    summary = {key: result[key] for key in ("mode", "treatmentManifestChecksum", "modelFeatureSchemaChecksum", "sourceFeatureCount", "modelFeatureCount", "modelFitsStarted", "finalOotPayloadRowsRead")}
    if arguments.apply:
        from server.sports_current_statcast.stage3_corrected_preprocessing_artifacts import persist_json
        from server.sports_current_statcast.stage3_model_laboratory import _runtime_root
        summary["registrationReceipt"] = persist_json(result, root=_runtime_root())
        summary.update({"adoptedTreatmentId": result["adoptedTreatment"]["specificationId"],
                        "adoptedTreatmentVersion": result["adoptedTreatment"]["specificationVersion"],
                        "featureSetId": result["featureSet"]["featureSetId"],
                        "splitContractId": result["splitContract"]["contractId"],
                        "v14Preserved": result["v14Preserved"]})
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
