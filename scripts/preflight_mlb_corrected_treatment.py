"""Development-only treatment preflight. Starts zero predictive model fits."""
from __future__ import annotations

import dataclasses
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNTIME = ROOT / ".runtime" / "asp-model-studio"
os.environ.setdefault("ATLAS_SECURITY_ROOT", str(RUNTIME / "security"))
os.environ.setdefault("ATLAS_SECURITY_DB_PATH", str(RUNTIME / "security" / "asp_model_studio_security.db"))

from server.persistence.db import Database
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast.stage3_corrected_treatment_spec import corrected_transformation_contracts, SEMANTIC_TREATMENT_VERSION
from server.sports_current_statcast.stage3_feature_treatment_spec import compile_project_specification
from server.sports_current_statcast.stage3_corrected_preprocessing_artifacts import persist_json, _array_digest
from server.sports_current_statcast.stage3_corrected_eligibility import eligibility_mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eligibility-only", action="store_true")
    args = parser.parse_args()
    database = Database(RUNTIME / "persistence" / "asp_model_studio.db")
    resolved = lab.resolve_model_lab_authority(database, "asp-mtlozhdx")
    compiled = compile_project_specification(database, "asp-mtlozhdx", semantic_treatment_version=SEMANTIC_TREATMENT_VERSION)
    registered = [item for item in resolved.feature_sets if lab._uses_corrected_treatment(item)]
    if len(registered) > 1:
        raise RuntimeError("Ambiguous corrected feature-set authority.")
    feature_set = registered[0] if registered else {"featureSetId": "UNREGISTERED_CORRECTED_PREFLIGHT_ONLY", "checksum": compiled["manifestChecksum"],
        "orderedFeatures": compiled["modelFeatureSchema"]["orderedFeatures"],
        "transformationContracts": corrected_transformation_contracts(compiled)}
    provisional = dataclasses.replace(resolved, feature_sets=(feature_set,))
    frame = lab._fold_frame(provisional, feature_set["orderedFeatures"], include_oof_identity=True, include_target=False)
    print(json.dumps({"event": "DEVELOPMENT_SCANNED", "rows": len(frame), "columns": len(frame.columns), "predictiveFits": 0}), flush=True)
    _, eligibility = eligibility_mask(frame.drop(columns=[name for name in frame if name in {"outcome", "target", "label", "observedClassIndex"}]), feature_set)
    eligibility_reference = persist_json(eligibility, root=lab._runtime_root())
    print(json.dumps({"event": "ELIGIBILITY_FROZEN", "sourceRows": eligibility["sourceRows"], "eligibleRows": eligibility["eligibleRows"], "heldRows": eligibility["heldRows"], "artifact": eligibility_reference}), flush=True)
    if args.eligibility_only:
        return
    for fold in resolved.split["contract"]["folds"]:
        train = lab._date_mask(frame, fold["trainStart"], fold["trainEnd"])
        validation = lab._date_mask(frame, fold["validationStart"], fold["validationEnd"])
        try:
            training, valid, prior, payload = lab._prepare_corrected_fold(frame,
                train_mask=train, validation_mask=validation, fold=fold, feature_set=feature_set,
                model_family="histogram_gradient_boosting", seed=20260906 + int(fold["foldNumber"]))
            encoder, _ = lab._preprocessor(training[feature_set["orderedFeatures"]], feature_set, dense_categoricals=True)
            encoder.fit(training[feature_set["orderedFeatures"]])
            values = encoder.transform(valid[feature_set["orderedFeatures"]])
            evidence = {"scope": "PREFLIGHT_PREPROCESSING_ONLY_NOT_A_MODEL_RUN", "predictiveFits": 0,
                "fold": fold, "trainingBranchCounts": payload["trainingBranchCounts"],
                "validationBranchCounts": payload["validationBranchCounts"], "priorExecution": prior,
                "modelInputValidation": payload["validationModelInputValidation"],
                "rowEligibility": payload["rowEligibility"],
                "modelTrainRows": len(training), "modelValidationRows": len(valid),
                "validationValuesSha256": _array_digest(values), "transformedColumns": int(values.shape[1]),
                "finalOotRowsRead": 0, "status": "PASS"}
            reference = persist_json(evidence, root=lab._runtime_root())
            print(json.dumps({"event": "FOLD_TREATMENT_PASSED", "fold": fold["foldNumber"], "evidence": reference, "transformedColumns": int(values.shape[1]), "predictiveFits": 0}), flush=True)
            del training, valid, values, encoder, payload
        except Exception as error:
            failure = {"scope": "PREFLIGHT_PREPROCESSING_ONLY_NOT_A_MODEL_RUN", "predictiveFits": 0,
                "fold": fold, "status": "BLOCKED", "code": getattr(error, "code", type(error).__name__),
                "message": str(error), "evidence": getattr(error, "evidence", {}), "finalOotRowsRead": 0}
            reference = persist_json(failure, root=lab._runtime_root())
            print(json.dumps({"event": "PREFLIGHT_BLOCKED", "fold": fold["foldNumber"],
                              "code": failure["code"], "message": failure["message"],
                              "evidence": failure["evidence"], "artifact": reference}), flush=True)
            raise


if __name__ == "__main__":
    main()
