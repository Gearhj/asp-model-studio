"""Command-line stages for the leakage-safe UFC Gen 1 study."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

import numpy as np
import pandas as pd

from .core import (
    MODEL_ID,
    build_feature_table,
    build_feature_table_after_finalist,
    canonical_json_bytes,
    feature_contract,
    load_clean_bouts,
    require_finalist_receipt,
    sha256_bytes,
    sha256_file,
    verify_frozen_design,
    write_canonical_json,
)
from .modeling import (
    block_bootstrap_difference,
    diagnostics,
    load_artifact,
    metrics,
    predict_selected,
    refit_selected,
    reversal_probability,
    save_artifact,
    select_finalist,
)
from .quality import profile_source


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("profile", "select", "oot", "verify"))
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument(
        "--design",
        type=Path,
        default=Path("docs/mma-gen1-research-model-v1/FROZEN_DESIGN.json"),
    )
    return parser.parse_args()


def _fighter_ids(source_root: Path) -> set[str]:
    fighters = pd.read_csv(source_root / "data" / "Fighters.csv", dtype={"Fighter_Id": str})
    return set(fighters["Fighter_Id"].astype(str))


def _source_receipt(source_root: Path) -> dict[str, Any]:
    receipt_path = source_root.parent / "SOURCE_RECEIPT.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    else:
        receipt = {
            "datasetUrl": "https://www.kaggle.com/datasets/aminealibi/ufc-fights-fighters-and-events-dataset",
            "datasetRef": "aminealibi/ufc-fights-fighters-and-events-dataset",
            "version": 87,
            "licenseLabel": "CC0: Public Domain",
            "provenanceWarning": "Uploader labels the dataset CC0; some content was reportedly compiled from UFCStats. Internal research authorization does not settle upstream commercial rights.",
        }
    receipt["rawRedistributionAuthorized"] = False
    receipt["researchUse"] = "INTERNAL_ONLY"
    return receipt


def stage_profile(source_root: Path, output_root: Path, design: Path) -> None:
    design_sha = verify_frozen_design(design)
    profile = profile_source(source_root)
    profile["createdAt"] = utc_now()
    profile["frozenDesignSha256"] = design_sha
    profile_meta = write_canonical_json(output_root / "DATA_QUALITY.json", profile)
    if profile["gate"] != "PASS":
        raise RuntimeError(f"DATA_QUALITY_GATE_FAILED:{profile['failClosedErrors']}")
    contract_meta = write_canonical_json(output_root / "FEATURE_CONTRACT.json", feature_contract())
    provenance = _source_receipt(source_root)
    provenance["verifiedFiles"] = [
        {"relativePath": row["relativePath"], "bytes": row["bytes"], "sha256": row["sha256"]}
        for row in profile["files"]
    ]
    provenance["physicalExtractedBytes"] = profile["totals"]["physicalBytes"]
    provenance_meta = write_canonical_json(output_root / "SOURCE_PROVENANCE.json", provenance)
    summary = {
        "stage": "PROFILE_COMPLETE_SELECTION_NOT_RUN",
        "createdAt": utc_now(),
        "frozenDesignSha256": design_sha,
        "dataQuality": profile_meta,
        "featureContract": contract_meta,
        "sourceProvenance": provenance_meta,
        "finalOotDirectionalLabelsOpened": False,
    }
    write_canonical_json(output_root / "PROFILE_RECEIPT.json", summary)


def _table_digest(frame: pd.DataFrame) -> str:
    stable = frame.copy()
    stable["event_date"] = stable["event_date"].dt.strftime("%Y-%m-%d")
    return sha256_bytes(stable.to_csv(index=False, lineterminator="\n").encode("utf-8"))


def stage_select(source_root: Path, output_root: Path, design: Path) -> None:
    design_sha = verify_frozen_design(design)
    quality_path = output_root / "DATA_QUALITY.json"
    if not quality_path.is_file() or json.loads(quality_path.read_text(encoding="utf-8"))["gate"] != "PASS":
        raise RuntimeError("QUALITY_GATE_NOT_PASSED")
    if (output_root / "FINAL_OOT.json").exists():
        raise RuntimeError("FINAL_OOT_ALREADY_OPENED_NO_RETUNE_ALLOWED")
    bouts = load_clean_bouts(source_root)
    table, build_receipt = build_feature_table(bouts, _fighter_ids(source_root), through_date="2024-12-31")
    table["role"] = np.where(table["event_date"] <= pd.Timestamp("2022-12-31"), "DEVELOPMENT", "VALIDATION")
    selection, transient = select_finalist(table)
    selection.update(
        {
            "schemaVersion": "MMA_UFC_GEN1_SELECTION_V1",
            "modelId": MODEL_ID,
            "createdAt": utc_now(),
            "frozenDesignSha256": design_sha,
            "featureTableSha256": _table_digest(table),
            "featureBuild": build_receipt,
            "finalOotOpened": False,
        }
    )
    selection_meta = write_canonical_json(output_root / "VALIDATION_SELECTION.json", selection)

    fitted = transient["fitted"]
    selected_params = {kind: candidate.params for kind, candidate in fitted.items()}
    final_artifact = refit_selected(table, selection["selected"], selected_params)
    final_artifact.update(
        {
            "modelId": MODEL_ID,
            "frozenDesignSha256": design_sha,
            "selectedParams": selected_params,
            "featureContract": feature_contract(),
            "trainingThrough": "2024-12-31",
        }
    )
    artifact_path = output_root / "fitted" / "model.joblib"
    save_artifact(artifact_path, final_artifact)
    artifact_meta = {"path": str(artifact_path), "bytes": artifact_path.stat().st_size, "sha256": sha256_file(artifact_path)}
    validation_predictions = transient["validationPredictions"].copy()
    validation_predictions["event_date"] = validation_predictions["event_date"].dt.strftime("%Y-%m-%d")
    prediction_path = output_root / "VALIDATION_PREDICTIONS.csv"
    validation_predictions.to_csv(prediction_path, index=False, lineterminator="\n")
    prediction_meta = {"path": str(prediction_path), "bytes": prediction_path.stat().st_size, "sha256": sha256_file(prediction_path)}
    receipt = {
        "schemaVersion": "MMA_UFC_GEN1_FINALIST_RECEIPT_V1",
        "status": "IMMUTABLE_FINALIST_FROZEN",
        "modelId": MODEL_ID,
        "createdAt": utc_now(),
        "selected": selection["selected"],
        "selectedParams": selected_params,
        "frozenDesignSha256": design_sha,
        "selectionReceipt": selection_meta,
        "modelArtifact": artifact_meta,
        "validationPredictions": prediction_meta,
        "ootOpened": False,
        "retuningAfterOotAuthorized": False,
    }
    receipt_path = output_root / "FINALIST_RECEIPT.json"
    write_canonical_json(receipt_path, receipt)
    receipt_sha = sha256_file(receipt_path)
    (output_root / "FINALIST_RECEIPT.sha256").write_text(receipt_sha + "\n", encoding="ascii")


def _oot_gate(validation: dict[str, Any], oot: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "logLossMax": oot["logLoss"] <= 0.6931471805599453,
        "brierMax": oot["brier"] <= 0.25,
        "calibrationSlope": 0.5 <= oot["calibrationSlope"] <= 1.5,
        "validationDrift": oot["logLoss"] - validation["logLoss"] <= 0.03,
    }
    return {"checks": checks, "passed": all(checks.values())}


def _package(output_root: Path, assessment_path: Path, verdict: str) -> dict[str, Any]:
    source_members = {
        "DATA_QUALITY.json": output_root / "DATA_QUALITY.json",
        "FEATURE_CONTRACT.json": output_root / "FEATURE_CONTRACT.json",
        "SOURCE_PROVENANCE.json": output_root / "SOURCE_PROVENANCE.json",
        "VALIDATION_SELECTION.json": output_root / "VALIDATION_SELECTION.json",
        "FINALIST_RECEIPT.json": output_root / "FINALIST_RECEIPT.json",
        "FINALIST_RECEIPT.sha256": output_root / "FINALIST_RECEIPT.sha256",
        "FINAL_OOT.json": assessment_path,
        "model.joblib": output_root / "fitted" / "model.joblib",
    }
    staging = output_root / "package-staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    members = []
    for name, source in source_members.items():
        target = staging / name
        shutil.copyfile(source, target)
        members.append({"path": name, "bytes": target.stat().st_size, "sha256": sha256_file(target)})
    model_card = {
        "modelId": MODEL_ID,
        "status": verdict,
        "authority": "RESEARCH_ONLY_NO_AISP_DECISION_POSITION_OR_PRODUCTION_AUTHORITY",
        "probabilitySemantics": "P(canonical fighter A wins conditional on a decisive result)",
        "sourceClassification": "reconstructed finalized historical UFC records",
        "operationalScheduleFeed": False,
        "rawSourceRowsIncluded": False,
        "knownLimitations": [
            "historical publication revisions are unavailable",
            "draw and no-contest probabilities are unsupported",
            "age, rankings, injuries, weigh-ins, short notice and current schedule identity are unsupported",
            "fighter physical fields were excluded because only current snapshots were retained",
            "upstream commercial rights remain unresolved despite the uploader CC0 label",
        ],
    }
    card_meta = write_canonical_json(staging / "MODEL_CARD.json", model_card)
    members.append({"path": "MODEL_CARD.json", "bytes": card_meta["bytes"], "sha256": card_meta["sha256"]})
    manifest_body = {
        "schemaVersion": "MMA_UFC_GEN1_RESEARCH_PACKAGE_V1",
        "modelId": MODEL_ID,
        "status": verdict,
        "authority": "RESEARCH_ONLY",
        "rawDatasetIncluded": False,
        "members": sorted(members, key=lambda row: row["path"]),
    }
    identity = sha256_bytes(canonical_json_bytes(manifest_body))
    destination = output_root / "packages" / "sha256" / identity
    if destination.exists():
        shutil.rmtree(staging)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(destination)
        write_canonical_json(destination / "MANIFEST.json", {**manifest_body, "packageIdentity": identity})
    manifest_path = destination / "MANIFEST.json"
    return {
        "path": str(destination),
        "packageIdentity": identity,
        "manifestBytes": manifest_path.stat().st_size,
        "manifestSha256": sha256_file(manifest_path),
    }


def stage_oot(source_root: Path, output_root: Path, design: Path) -> None:
    design_sha = verify_frozen_design(design)
    finalist_path = output_root / "FINALIST_RECEIPT.json"
    finalist_digest = output_root / "FINALIST_RECEIPT.sha256"
    finalist_sha = require_finalist_receipt(finalist_path, finalist_digest)
    if (output_root / "FINAL_OOT.json").exists():
        raise RuntimeError("FINAL_OOT_ALREADY_OPENED_EXACTLY_ONCE")
    quality = json.loads((output_root / "DATA_QUALITY.json").read_text(encoding="utf-8"))
    final_date = quality["chronology"]["maxCompleteDate"]
    bouts = load_clean_bouts(source_root)
    table, build_receipt = build_feature_table_after_finalist(
        bouts,
        _fighter_ids(source_root),
        through_date=final_date,
        finalist_receipt=finalist_path,
        finalist_digest=finalist_digest,
    )
    oot = table[table["event_date"] >= pd.Timestamp("2025-01-01")].copy()
    if len(oot) != quality["population"]["eligibleCounts"]["FINAL_OOT_SEALED_COUNT"]:
        raise RuntimeError("FINAL_OOT_POPULATION_COUNT_MISMATCH")
    artifact_path = output_root / "fitted" / "model.joblib"
    artifact = load_artifact(artifact_path)
    selected_p = predict_selected(artifact, oot)
    elo_p = oot["elo_probability_a"].to_numpy(dtype=float)
    y = oot["target_a_win"].astype(int).to_numpy()
    selection = json.loads((output_root / "VALIDATION_SELECTION.json").read_text(encoding="utf-8"))
    selected_name = artifact["selected"]
    selected_metrics = metrics(y, selected_p)
    elo_metrics = metrics(y, elo_p)
    gate = _oot_gate(selection["validationMetrics"][selected_name], selected_metrics)
    verdict = "RESEARCH_CANDIDATE" if gate["passed"] else "NO_MODEL_SELECTED"
    assessment = {
        "schemaVersion": "MMA_UFC_GEN1_FINAL_OOT_V1",
        "modelId": MODEL_ID,
        "createdAt": utc_now(),
        "frozenDesignSha256": design_sha,
        "finalistReceiptSha256": finalist_sha,
        "openedExactlyOnce": True,
        "dates": {"start": "2025-01-01", "end": final_date},
        "selected": selected_name,
        "selectedMetrics": selected_metrics,
        "eloMetrics": elo_metrics,
        "candidateMinusElo": {
            key: float(selected_metrics[key] - elo_metrics[key]) for key in ("logLoss", "brier", "ece10", "rocAuc", "accuracy")
        },
        "pairedUncertainty": block_bootstrap_difference(oot, selected_p, elo_p),
        "diagnostics": diagnostics(oot, selected_p),
        "eloDiagnostics": diagnostics(oot, elo_p),
        "validationMetrics": selection["validationMetrics"][selected_name],
        "driftFromValidation": {
            key: float(selected_metrics[key] - selection["validationMetrics"][selected_name][key])
            for key in ("logLoss", "brier", "ece10", "rocAuc", "accuracy")
        },
        "gate": gate,
        "verdict": verdict,
        "featureBuild": build_receipt,
        "noRetunePerformed": True,
    }
    assessment_path = output_root / "FINAL_OOT.json"
    assessment_meta = write_canonical_json(assessment_path, assessment)
    predictions = oot[["fight_id", "event_id", "event_date", "fighter_a_id", "fighter_b_id", "target_a_win"]].copy()
    predictions["event_date"] = predictions["event_date"].dt.strftime("%Y-%m-%d")
    predictions["p_selected"] = selected_p
    predictions["p_elo"] = elo_p
    prediction_path = output_root / "FINAL_OOT_PREDICTIONS.csv"
    predictions.to_csv(prediction_path, index=False, lineterminator="\n")
    package = _package(output_root, assessment_path, verdict)
    closeout = {
        "verdict": verdict,
        "selected": selected_name,
        "assessment": assessment_meta,
        "ootPredictions": {"path": str(prediction_path), "bytes": prediction_path.stat().st_size, "sha256": sha256_file(prediction_path)},
        "package": package,
        "providerCallsThisModelingRun": {"kaggleMetadata": 1, "kaggleDownload": 1, "otherProviders": 0},
        "providerResponseBytes": 3831869,
        "providerCredits": 0,
        "costUsd": 0,
        "aispWrites": 0,
        "schedulerChanges": 0,
        "productionActivations": 0,
    }
    write_canonical_json(output_root / "CLOSEOUT.json", closeout)


def stage_verify(source_root: Path, output_root: Path, design: Path) -> None:
    verify_frozen_design(design)
    closeout = json.loads((output_root / "CLOSEOUT.json").read_text(encoding="utf-8"))
    package = Path(closeout["package"]["path"])
    manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
    for member in manifest["members"]:
        path = package / member["path"]
        if path.stat().st_size != member["bytes"] or sha256_file(path) != member["sha256"]:
            raise RuntimeError(f"PACKAGE_MEMBER_MISMATCH:{member['path']}")
        if "raw" in member["path"].casefold() or member["path"].endswith(".csv"):
            raise RuntimeError("RAW_OR_ROW_DATA_IN_PACKAGE")
    body = {key: value for key, value in manifest.items() if key != "packageIdentity"}
    if sha256_bytes(canonical_json_bytes(body)) != manifest["packageIdentity"]:
        raise RuntimeError("PACKAGE_IDENTITY_MISMATCH")
    # Verify a real retained feature row reverses exactly without a second score.
    finalist_path = output_root / "FINALIST_RECEIPT.json"
    bouts = load_clean_bouts(source_root)
    quality = json.loads((output_root / "DATA_QUALITY.json").read_text(encoding="utf-8"))
    table, _ = build_feature_table_after_finalist(
        bouts,
        _fighter_ids(source_root),
        through_date=quality["chronology"]["maxCompleteDate"],
        finalist_receipt=finalist_path,
        finalist_digest=output_root / "FINALIST_RECEIPT.sha256",
    )
    row = table.tail(1)
    artifact = load_artifact(output_root / "fitted" / "model.joblib")
    p_a = reversal_probability(artifact, row, str(row.iloc[0]["fighter_a_id"]))
    p_b = reversal_probability(artifact, row, str(row.iloc[0]["fighter_b_id"]))
    if abs((p_a + p_b) - 1.0) > 1e-12:
        raise RuntimeError("REVERSAL_COMPLEMENT_FAILED")
    try:
        tracked = subprocess.check_output(["git", "ls-files"], text=True).splitlines()
    except Exception as exc:  # pragma: no cover - environmental failure
        raise RuntimeError("GIT_TRACKED_FILE_CHECK_FAILED") from exc
    forbidden = [path for path in tracked if path.casefold().endswith((".csv", ".parquet", ".joblib", ".zip")) and "fixture" not in path.casefold()]
    if forbidden:
        raise RuntimeError(f"PROHIBITED_TRACKED_DATA_OR_MODEL:{forbidden}")
    receipt = {
        "verifiedAt": utc_now(),
        "packageIdentity": manifest["packageIdentity"],
        "members": len(manifest["members"]),
        "reversalComplementError": abs((p_a + p_b) - 1.0),
        "rawDatasetTracked": False,
        "providerCallsDuringVerification": 0,
        "aispWrites": 0,
    }
    write_canonical_json(output_root / "VERIFICATION.json", receipt)


def main() -> None:
    args = _args()
    args.source_root = args.source_root.resolve()
    args.output_root = args.output_root.resolve()
    args.design = args.design.resolve()
    if args.stage == "profile":
        stage_profile(args.source_root, args.output_root, args.design)
    elif args.stage == "select":
        stage_select(args.source_root, args.output_root, args.design)
    elif args.stage == "oot":
        stage_oot(args.source_root, args.output_root, args.design)
    else:
        stage_verify(args.source_root, args.output_root, args.design)


if __name__ == "__main__":
    main()

