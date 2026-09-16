"""Build deterministic, synthetic prospective cross-game evidence fixtures."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_shared.prospective_cross_game_evidence import (
    AVAILABILITY_SCHEMA,
    CALIBRATION_SCHEMA,
    DEPENDENCY_KEYS,
    FROZEN_DESIGN_SHA256,
    FROZEN_RESULTS_SHA256,
    POST_OUTCOME_SCHEMA,
    PRE_OUTCOME_SCHEMA,
    append_revision,
    canonical_json_bytes,
    evidence_sidecar_binding,
    readiness_state,
    sha256_identity,
    validate_calibration_certificate,
    validate_availability_receipt,
    validate_post_outcome,
    validate_pre_outcome,
)


def dependency_fixture(observed_at: str) -> dict[str, Any]:
    return {
        key: {
            "state": "UNKNOWN",
            "evidenceSource": "SYNTHETIC_NO_PROVIDER_FIXTURE",
            "observedAt": observed_at,
            "ruleOrReviewer": "SYNTHETIC_FIXTURE_RULE_V1",
            "confidence": "NOT_ESTABLISHED",
            "reviewState": "AUTOMATED_RULE",
            "relatedGameIds": [],
        }
        for key in DEPENDENCY_KEYS
    }


def pre_outcome_fixture(*, game_id: str = "synthetic-nfl-2026-09-20-a",
                        forecast_id: str = "synthetic-forecast-r1",
                        participants: tuple[str, str] = ("synthetic-away", "synthetic-home")) -> dict[str, Any]:
    observed = "2026-09-19T18:30:00-04:00"
    record = {
        "schemaVersion": PRE_OUTCOME_SCHEMA,
        "evidenceSeriesId": "synthetic-series-20260920-a",
        "sport": "NFL",
        "season": "2026",
        "slateDate": "2026-09-20",
        "canonicalGameId": game_id,
        "participants": [
            {"canonicalParticipantId": participants[0], "displayName": "Synthetic Away", "role": "AWAY"},
            {"canonicalParticipantId": participants[1], "displayName": "Synthetic Home", "role": "HOME"},
        ],
        "scheduledStart": "2026-09-20T13:00:00-04:00",
        "forecastId": forecast_id,
        "forecastRevision": 1,
        "forecastHorizon": "CURRENT_RESEARCH",
        "model": {"modelId": "SYNTHETIC_MODEL", "modelVersion": "v1", "configurationId": "SYNTHETIC_CONFIG_V1"},
        "authority": {"forecastAuthority": "RESEARCH_ONLY", "researchOnlyEvidence": True,
                      "decisionAuthority": False, "positionAuthority": False, "stakeAuthority": False,
                      "modelPromotionAuthority": False},
        "integrity": {"packageSha256": "1" * 64, "populationSha256": "2" * 64, "drawCount": 5000},
        "timing": {"sourceCutoff": "2026-09-19T18:00:00-04:00",
                   "forecastCreatedAt": "2026-09-19T18:10:00-04:00",
                   "producerPublishedAt": "2026-09-19T18:20:00-04:00",
                   "exchangeDiscoveredAt": None, "consumerAcknowledgedAt": None,
                   "decisionWindowAvailableAt": None},
        "supersedes": None,
        "supportedMarkets": ["MONEYLINE", "TOTAL"],
        "calibrationCertificate": {"certificateId": "synthetic-uncertified-nfl-v1",
                                   "certificateSha256": "3" * 64, "status": "UNCERTIFIED"},
        "dependencies": dependency_fixture(observed),
        "captureReceipt": {"receiptId": "synthetic-capture-v1", "receiptSha256": "4" * 64,
                           "capturedAt": "2026-09-19T18:30:00-04:00"},
        "limitations": ["Synthetic non-provider fixture", "No consumer or wagering authority"],
    }
    return validate_pre_outcome(record)


def successor_fixture(first: dict[str, Any]) -> dict[str, Any]:
    second = deepcopy(first)
    second["forecastId"] = "synthetic-forecast-r2"
    second["forecastRevision"] = 2
    second["integrity"]["packageSha256"] = "5" * 64
    second["timing"]["sourceCutoff"] = "2026-09-19T19:00:00-04:00"
    second["timing"]["forecastCreatedAt"] = "2026-09-19T19:10:00-04:00"
    second["timing"]["producerPublishedAt"] = "2026-09-19T19:20:00-04:00"
    second["captureReceipt"] = {"receiptId": "synthetic-capture-v2", "receiptSha256": "6" * 64,
                                "capturedAt": "2026-09-19T19:30:00-04:00"}
    second["supersedes"] = {"forecastId": first["forecastId"], "forecastRevision": 1,
                            "packageSha256": first["integrity"]["packageSha256"],
                            "evidenceSha256": sha256_identity(first)}
    return append_revision([first], second)[-1]


def calibration_fixture() -> dict[str, Any]:
    record = {
        "schemaVersion": CALIBRATION_SCHEMA,
        "certificateId": "synthetic-uncertified-nfl-v1",
        "status": "UNCERTIFIED",
        "sport": "NFL",
        "modelId": "SYNTHETIC_MODEL",
        "configurationId": "SYNTHETIC_CONFIG_V1",
        "probabilityChannel": "HOME_WIN",
        "trainingPopulation": "SYNTHETIC_NONE",
        "evaluationPopulation": "SYNTHETIC_NONE",
        "evaluationDates": {"start": "2026-01-01", "end": "2026-01-01"},
        "sampleSize": 0,
        "calibrationMethod": "NONE",
        "metrics": {"preCalibration": None, "postCalibration": None, "reliabilityBands": None,
                    "brier": None, "logLoss": None, "calibrationIntercept": None, "calibrationSlope": None},
        "certifiedAt": None,
        "expirationRule": "Requires a separately authorized timestamp-certified evaluation",
        "artifacts": [],
        "authority": "RESEARCH_ONLY",
        "missingRequirements": ["Timestamp-certified prospective evaluation population",
                                "Frozen proper-score and reliability report"],
    }
    return validate_calibration_certificate(record)


def post_outcome_fixture(pre: dict[str, Any]) -> dict[str, Any]:
    record = {
        "schemaVersion": POST_OUTCOME_SCHEMA,
        "assessmentId": "synthetic-assessment-v1",
        "sport": pre["sport"],
        "canonicalGameId": pre["canonicalGameId"],
        "preOutcomeEvidenceSha256": sha256_identity(pre),
        "scoredForecast": {"forecastId": pre["forecastId"], "forecastRevision": pre["forecastRevision"],
                           "packageSha256": pre["integrity"]["packageSha256"]},
        "finalResult": {"resultId": "synthetic-final-v1", "revision": 1, "status": "FINAL",
                        "participantResults": [
                            {"canonicalParticipantId": pre["participants"][0]["canonicalParticipantId"],
                             "outcome": "LOSS", "score": 17},
                            {"canonicalParticipantId": pre["participants"][1]["canonicalParticipantId"],
                             "outcome": "WIN", "score": 24},
                        ], "resultSha256": "7" * 64},
        "outcomeAvailableAt": "2026-09-20T16:30:00-04:00",
        "assessmentCapturedAt": "2026-09-20T16:40:00-04:00",
        "assessmentDisposition": "INCLUDED",
        "exclusionReason": None,
        "frozenGateSegments": ["SAME_SPORT_UNRELATED_REGULAR"],
        "frozenGateBinding": {"designSha256": FROZEN_DESIGN_SHA256,
                              "resultsSha256": FROZEN_RESULTS_SHA256},
    }
    return validate_post_outcome(record, pre)


def availability_fixture(pre: dict[str, Any]) -> dict[str, Any]:
    record = {
        "schemaVersion": AVAILABILITY_SCHEMA,
        "receiptId": "synthetic-consumer-ack-v1",
        "preOutcomeEvidenceSha256": sha256_identity(pre),
        "stage": "CONSUMER_ACKNOWLEDGEMENT",
        "observedAt": "2026-09-19T18:40:00-04:00",
        "evidenceSource": "SYNTHETIC_CONSUMER_RECEIPT",
        "capturedAt": "2026-09-19T18:41:00-04:00",
        "pregameAvailable": True,
    }
    return validate_availability_receipt(record, pre)


def readiness_fixture() -> dict[str, Any]:
    rows = [
        {"pairId": "synthetic-game-a|synthetic-game-b",
         "gameIds": ["synthetic-game-a", "synthetic-game-b"],
         "slateDate": "2026-09-20", "probabilityBand": "0.20-0.30", "eligible": True}
    ]
    return readiness_state("SYNTHETIC_UNRELATED_REGULAR", rows)


def build(output: Path) -> dict[str, Any]:
    first = pre_outcome_fixture()
    files = {
        "pre-outcome.json": first,
        "pre-outcome-successor.json": successor_fixture(first),
        "calibration-uncertified.json": calibration_fixture(),
        "availability-receipt.json": availability_fixture(first),
        "post-outcome.json": post_outcome_fixture(first),
        "readiness-state.json": readiness_fixture(),
        "sidecar-binding.json": evidence_sidecar_binding(first),
    }
    output.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, value in sorted(files.items()):
        payload = canonical_json_bytes(value)
        (output / name).write_bytes(payload)
        result[name] = {"bytes": len(payload), "sha256": sha256_identity(value)}
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), sort_keys=True))


if __name__ == "__main__":
    main()
