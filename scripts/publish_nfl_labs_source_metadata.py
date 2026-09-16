"""Metadata-only immutable correction; no estimator or simulation execution."""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_nfl_m1.labs_simulation import (
    AUTHORITY, FAMILY, file_record, immutable_json, publish_object,
    registered_source_availability, verify_object, utc,
)


def run() -> dict:
    exchange = Path(r"C:\Users\james\asp-model-exchange")
    output = Path("outputs/nfl-labs-simulation-v1")
    pointer_path = exchange / FAMILY / "current.json"
    pointer = json.loads(pointer_path.read_bytes())
    previous_handoff = pointer["driveResearchHandoff"]
    existing_receipt_path = output / "source-metadata-correction-v1.json"
    if existing_receipt_path.exists():
        existing_receipt = json.loads(existing_receipt_path.read_bytes())
        if existing_receipt["handoff"] == previous_handoff:
            for item in json.loads(Path(previous_handoff["path"]).read_bytes())["artifacts"]:
                verify_object(item)
            return existing_receipt
    previous = json.loads(Path(previous_handoff["path"]).read_bytes())
    fit_receipt = json.loads(Path(previous["fitReceipt"]["path"]).read_bytes())
    availability = registered_source_availability(Path(r"C:\Users\james\asp-data-staging\nfl\bronze-v1"), fit_receipt)
    artifacts = []
    protected_fields = ["forecastId", "model", "scoreSummary", "jointScoreDistribution", "scoreMarginDistribution",
                        "totalScoreDistribution", "populationFinals", "quantiles", "simulatedDrives", "representativeFinals",
                        "scenario", "drawCount", "seed", "forecastCreatedUtc", "inferenceStartedUtc",
                        "regulationTieProbability", "reachingOvertimeProbability", "finalTieProbability"]
    for reference in previous["artifacts"]:
        original = verify_object(reference)
        if utc(availability["sourceCutoffUtc"]) > utc(original["inferenceStartedUtc"]):
            raise ValueError("registered evidence retrieval was after forecast inference")
        if original.get("sourceAvailability") == availability:
            artifacts.append(reference)
            continue
        corrected = dict(original)
        corrected.update({"sourceCutoffUtc": availability["sourceCutoffUtc"], "sourceAvailability": availability,
                          "historicalEvidenceThroughDate": availability["historicalEvidenceThroughDate"],
                          "historicalEvidencePrecision": availability["historicalEvidencePrecision"],
                          "originalForecastPublishedAtUtc": original["publishedAtUtc"],
                          "publishedAtUtc": datetime.now(timezone.utc).isoformat(),
                          "metadataPredecessorArtifact": reference,
                          "metadataCorrection": {"schemaVersion": "NFL_LABS_SOURCE_AVAILABILITY_CORRECTION_V1",
                                                 "supersededDateBoundaryLabel": original["sourceCutoffUtc"],
                                                 "reason": "DATE_DERIVED_23_59_59_WAS_NOT_A_MEASURED_SOURCE_AVAILABILITY_TIMESTAMP",
                                                 "numericalForecastChanged": False, "modelFitOccurred": False, "simulationReplayOccurred": False}})
        before = canonical_json_bytes({key: original[key] for key in protected_fields})
        after = canonical_json_bytes({key: corrected[key] for key in protected_fields})
        if before != after: raise ValueError("metadata correction changed protected numerical/sequence/identity fields")
        item = publish_object(corrected, exchange / FAMILY)
        verify_object(item); verify_object(reference)
        artifacts.append(item)
    receipt = {**previous, "publishedAtUtc": datetime.now(timezone.utc).isoformat(), "artifacts": artifacts,
               "predecessorMetadataHandoff": previous_handoff, "sourceAvailability": availability,
               "metadataOnly": True, "modelFitsDuringCorrection": 0, "simulationReplaysDuringCorrection": 0,
               "protectedNumericalAndSequenceFieldsExactlyUnchanged": True}
    digest = hashlib.sha256(canonical_json_bytes(receipt)).hexdigest()
    handoff = immutable_json(output / "sha256" / digest / "drive-handoff.json", receipt)
    merged = {**pointer, "publishedAtUtc": receipt["publishedAtUtc"], "driveResearchHandoff": handoff,
              "artifacts": [item for item in pointer["artifacts"] if item["artifactSchemaVersion"] != "NFL_LABS_DRIVE_SIMULATION_V1"]+artifacts}
    temporary = pointer_path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("xb") as stream: stream.write(canonical_json_bytes(merged))
    os.replace(temporary, pointer_path)
    result = {"handoff": handoff, "artifactCount": len(artifacts), "sourceCutoffUtc": availability["sourceCutoffUtc"],
              "historicalEvidenceThroughDate": availability["historicalEvidenceThroughDate"],
              "numericalForecastAndSequencesUnchanged": True, "modelFits": 0, "simulationReplays": 0}
    immutable_json(output / "source-metadata-correction-v1.json", result)
    return result


if __name__ == "__main__": print(json.dumps(run(), indent=2))
