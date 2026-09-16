"""Register the immutable MLB Core Challenger feature/split authorities.

This command is intentionally narrow and idempotent for project
``asp-mtlozhdx``. It never reads Final OOT payloads and never starts a model.
"""

from __future__ import annotations

import json
from pathlib import Path

from server.persistence.db import Database
from server.persistence.repositories.stage3_feature_set_repository import (
    NO_CURRENT_FEATURE_SET,
    Stage3FeatureSetRepository,
)
from server.persistence.repositories.stage3_split_contract_repository import (
    Stage3SplitContractRepository,
)
from server.persistence.repositories.stage3_treatment_repository import (
    Stage3TreatmentRepository,
)
from server.sports_current_statcast import stage3_feature_engineering as features
from server.sports_current_statcast import stage3_split_balance as splits
from server.sports_current_statcast.stage3_feature_treatment_spec import (
    adopt_treatment_specification,
    compile_project_specification,
    save_treatment_specification_draft,
)


PROJECT_ID = "asp-mtlozhdx"
FEATURE_SET_KEY = "MLB_CORE_CHALLENGER_V4"
ACTOR_USER_ID = "user_20e0f4e20ec9434c"
DATABASE_PATH = Path(
    r".runtime\asp-model-studio\persistence\asp_model_studio.db"
)


def main() -> None:
    database = Database(DATABASE_PATH)
    authority = features.eda._resolve_authority(database, PROJECT_ID)
    authority_key = ":".join(
        (
            authority.source_manifest_sha,
            authority.gold_manifest_sha,
            authority.contextual_manifest_sha,
            authority.review_digest,
        )
    )
    compiled = compile_project_specification(database, PROJECT_ID)
    treatment_repository = Stage3TreatmentRepository(database)
    treatment_state = treatment_repository.combined_spec_state(
        PROJECT_ID, authority.review_digest
    )
    adopted_treatment = treatment_state.get("adopted")
    if not adopted_treatment or str(adopted_treatment.get("manifestChecksum") or "") != str(
        compiled["manifestChecksum"]
    ):
        save_treatment_specification_draft(
            database,
            PROJECT_ID,
            {
                "authorityKey": authority_key,
                "expectedManifestChecksum": compiled["manifestChecksum"],
            },
            actor_user_id=ACTOR_USER_ID,
        )
        latest_draft = treatment_repository.combined_spec_state(
            PROJECT_ID, authority.review_digest
        ).get("latestDraft")
        if not latest_draft:
            raise RuntimeError("The exact Core treatment draft was not persisted.")
        adopt_treatment_specification(
            database,
            PROJECT_ID,
            {
                "authorityKey": authority_key,
                "specificationDraftId": latest_draft["specificationId"],
                "expectedManifestChecksum": latest_draft["manifestChecksum"],
            },
            actor_user_id=ACTOR_USER_ID,
        )
        adopted_treatment = treatment_repository.combined_spec_state(
            PROJECT_ID, authority.review_digest
        ).get("adopted")
    prior_by_feature = {
        str(item["feature"]): item
        for item in (compiled.get("priorAuthority") or {}).get("bindings") or []
        if item.get("feature")
    }
    ordered = [
        str(item["feature_name"])
        for item in compiled["features"]
        if item.get("executable_selectable") is True
        or (
            item.get("executable_status") == "READY_GOVERNED_PRIOR_V2"
            and item.get("preprocessing_executable") is True
        )
    ]
    if len(ordered) != 218 or len(ordered) != len(set(ordered)):
        raise RuntimeError(
            f"Expected 218 distinct Core Challenger predictors, found {len(ordered)}."
        )
    rows, catalog = features._catalog(authority)
    features._apply_treatment_spec_draft_gates(rows, database, authority)
    transformations = features._default_transformations(ordered, catalog)
    transformations["ordered"] = [
        {
            "feature": name,
            "steps": (
                ["GOVERNED_PRIOR_POSTERIOR_MEAN"]
                if str((prior_by_feature.get(name) or {}).get("status") or "")
                in {"READY_GOVERNED_PRIOR_V1", "READY_GOVERNED_PRIOR_V2"}
                else features._default_steps(catalog[name])
            ),
        }
        for name in ordered
    ]
    governed = [
        item["feature"]
        for item in transformations["ordered"]
        if item["steps"] == ["GOVERNED_PRIOR_POSTERIOR_MEAN"]
    ]
    if len(governed) != 21:
        raise RuntimeError(f"Expected 21 governed prior predictors, found {len(governed)}.")

    feature_repository = Stage3FeatureSetRepository(database)
    feature_state = feature_repository.feature_set_state(
        PROJECT_ID, authority.review_digest
    )
    registered = next(
        (
            item
            for item in feature_state.get("registeredSets") or []
            if item.get("featureSetKey") == FEATURE_SET_KEY
        ),
        None,
    )
    if registered is None:
        expected = (feature_state.get("expectedChecksumByKey") or {}).get(
            FEATURE_SET_KEY, NO_CURRENT_FEATURE_SET
        )
        draft_result = features.save_feature_set_draft(
            PROJECT_ID,
            database,
            {
                "authorityKey": authority_key,
                "featureSetKey": FEATURE_SET_KEY,
                "name": "MLB Core Challenger",
                "description": (
                    "Complete project-bound Core Challenger using 21 governed "
                    "posterior-mean priors and excluding deferred, retired, and "
                    "source-unavailable fields."
                ),
                "notes": (
                    "Development-only challenger authority. Sixteen contextual "
                    "source fields and derived holiday bindings remain deferred "
                    "with no transitive reachability; "
                    "Final OOT remains sealed."
                ),
                "orderedFeatures": ordered,
                "transformationContracts": transformations,
                "expectedChecksum": expected,
            },
            ACTOR_USER_ID,
        )
        draft = draft_result["data"]["featureSet"]
        register_result = features.register_feature_set(
            PROJECT_ID,
            database,
            {
                "authorityKey": authority_key,
                "draftFeatureSetId": draft["featureSetId"],
                "expectedChecksum": draft["checksum"],
            },
            ACTOR_USER_ID,
        )
        registered = register_result["data"]["featureSet"]

    split_repository = Stage3SplitContractRepository(database)
    split_state = split_repository.contract_state(PROJECT_ID, authority.review_digest)
    current = split_state.get("currentRegistered")
    if not current or list(current.get("selectedFeatureSetIds") or []) != [
        registered["featureSetId"]
    ]:
        split_payload = {
            "authorityKey": authority_key,
            "mode": "AUTOMATIC",
            "foldCount": 5,
            "trainingPolicy": "EXPANDING_WINDOW",
            "classPolicy": "NATURAL_BASE_RATES",
            "deterministicSeed": 20260906,
            "selectedFeatureSetIds": [registered["featureSetId"]],
            "expectedChecksum": split_state["expectedChecksum"],
            "notes": (
                "Five expanding-window chronological folds for the first Core "
                "Challenger competition; preprocessing and priors fit within "
                "training folds only; Final OOT sealed."
            ),
        }
        split_draft_result = splits.save_split_draft(
            PROJECT_ID, database, split_payload, ACTOR_USER_ID
        )
        split_draft = split_draft_result["data"]["contract"]
        split_register_result = splits.register_split_contract(
            PROJECT_ID,
            database,
            {
                "authorityKey": authority_key,
                "contractId": split_draft["contractId"],
                "expectedChecksum": split_draft["checksum"],
            },
            ACTOR_USER_ID,
        )
        current = split_register_result["data"]["contract"]

    output = {
        "projectId": PROJECT_ID,
        "treatmentSpecificationId": compiled["specificationId"],
        "treatmentManifestChecksum": compiled["manifestChecksum"],
        "adoptedTreatment": adopted_treatment,
        "featureSet": registered,
        "splitContract": current,
        "includedFeatureCount": len(ordered),
        "governedPriorFeatureCount": len(governed),
        "finalOotPayloadRowsRead": 0,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
