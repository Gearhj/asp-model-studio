"""Pure, inactive prospective evidence contracts for cross-game research.

This module has no filesystem, network, database, provider, exchange, model, or
scheduler client.  It validates immutable evidence values and computes only
identity, pair classification, and frozen-gate readiness counts.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence


PRE_OUTCOME_SCHEMA = "ASP_PROSPECTIVE_FORECAST_EVIDENCE_V1"
POST_OUTCOME_SCHEMA = "ASP_PROSPECTIVE_FORECAST_ASSESSMENT_V1"
CALIBRATION_SCHEMA = "ASP_PROSPECTIVE_CALIBRATION_CERTIFICATE_V1"
READINESS_SCHEMA = "ASP_CROSS_GAME_PROSPECTIVE_READINESS_V1"
SIDECAR_SCHEMA = "ASP_PROSPECTIVE_EVIDENCE_SIDECAR_BINDING_V1"
AVAILABILITY_SCHEMA = "ASP_PROSPECTIVE_AVAILABILITY_RECEIPT_V1"
FROZEN_DESIGN_SHA256 = "5749b2457b52589a612b3a2597341185a5baf9b814d300715ec115a4c8dda87f"
FROZEN_RESULTS_SHA256 = "fafc0b9bd9997e65fa6db209bceb6dacb91943528e136ed23603daf922ffef24"
SUPPORTED_SPORTS = frozenset({"MLB", "NFL", "NBA", "CFB", "MMA"})
DEPENDENCY_STATES = frozenset({"CONFIRMED", "RULED_OUT", "UNKNOWN"})
DEPENDENCY_KEYS = (
    "SHARED_PARTICIPANT",
    "DOUBLEHEADER",
    "SHARED_VENUE",
    "GEOGRAPHIC_WEATHER_SYSTEM",
    "SHARED_WEATHER_INPUT_REVISION",
    "SHARED_PLAYER_ROSTER_UNCERTAINTY",
    "SHARED_INJURY_SOURCE_UNCERTAINTY",
    "TOURNAMENT_POSTSEASON_LINKAGE",
    "SEQUENTIAL_INCENTIVE",
    "STANDINGS_QUALIFICATION",
    "SHARED_SOURCE_INCIDENT",
    "SHARED_FEATURE_PIPELINE_INCIDENT",
    "AMBIGUOUS_REVISION",
    "PARTICIPANT_REPLACEMENT",
    "UNSUPPORTED_DEPENDENCY_STATE",
)
FROZEN_THRESHOLDS = {
    "minimumGames": 500,
    "minimumDates": 50,
    "minimumUniqueUnorderedPairs": 1000,
    "minimumSupportedReliabilityBands": 2,
    "minimumReliabilityBandPairs": 200,
    "minimumReliabilityBandDates": 20,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ProspectiveEvidenceError(ValueError):
    """Fail-closed evidence contract error with a stable code."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sha256_identity(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProspectiveEvidenceError("MAPPING_REQUIRED", f"{field} must be an object")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProspectiveEvidenceError("TEXT_REQUIRED", f"{field} must be non-empty text")
    return value


def _sha(value: Any, field: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    text = _text(value, field)
    if not _SHA256.fullmatch(text):
        raise ProspectiveEvidenceError("SHA256_INVALID", f"{field} must be lowercase physical SHA-256")
    return text


def _time(value: Any, field: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProspectiveEvidenceError("TIMESTAMP_INVALID", f"{field} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProspectiveEvidenceError("TIMESTAMP_TIMEZONE_REQUIRED", f"{field} must be timezone-aware")
    return parsed


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProspectiveEvidenceError("INTEGER_INVALID", f"{field} must be an integer >= {minimum}")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], field: str) -> None:
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        raise ProspectiveEvidenceError(
            "FIELDS_INVALID", f"{field} missing={sorted(missing)} extra={sorted(extra)}"
        )


def _validate_dependency(key: str, value: Any) -> None:
    assertion = _mapping(value, f"dependencies.{key}")
    _exact_keys(assertion, {"state", "evidenceSource", "observedAt", "ruleOrReviewer",
                            "confidence", "reviewState", "relatedGameIds"}, f"dependencies.{key}")
    if assertion["state"] not in DEPENDENCY_STATES:
        raise ProspectiveEvidenceError("DEPENDENCY_STATE_INVALID", key)
    _text(assertion["evidenceSource"], f"dependencies.{key}.evidenceSource")
    _time(assertion["observedAt"], f"dependencies.{key}.observedAt")
    _text(assertion["ruleOrReviewer"], f"dependencies.{key}.ruleOrReviewer")
    if assertion["confidence"] not in {"HIGH", "MEDIUM", "LOW", "NOT_ESTABLISHED"}:
        raise ProspectiveEvidenceError("DEPENDENCY_CONFIDENCE_INVALID", key)
    if assertion["reviewState"] not in {"AUTOMATED_RULE", "HUMAN_REVIEWED", "UNREVIEWED"}:
        raise ProspectiveEvidenceError("DEPENDENCY_REVIEW_STATE_INVALID", key)
    related = assertion["relatedGameIds"]
    if not isinstance(related, list) or any(not isinstance(item, str) or not item for item in related):
        raise ProspectiveEvidenceError("DEPENDENCY_RELATED_GAMES_INVALID", key)


def validate_pre_outcome(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one immutable pre-outcome envelope and return a deep copy."""
    value = _mapping(record, "record")
    expected = {
        "schemaVersion", "evidenceSeriesId", "sport", "season", "slateDate", "canonicalGameId",
        "participants", "scheduledStart", "forecastId", "forecastRevision", "forecastHorizon",
        "model", "authority", "integrity", "timing", "supersedes", "supportedMarkets",
        "calibrationCertificate", "dependencies", "captureReceipt", "limitations",
    }
    _exact_keys(value, expected, "preOutcome")
    if value["schemaVersion"] != PRE_OUTCOME_SCHEMA:
        raise ProspectiveEvidenceError("SCHEMA_VERSION_INVALID", "pre-outcome schema differs")
    sport = _text(value["sport"], "sport").upper()
    if sport not in SUPPORTED_SPORTS or sport != value["sport"]:
        raise ProspectiveEvidenceError("SPORT_INVALID", str(value["sport"]))
    for field in ("evidenceSeriesId", "season", "canonicalGameId", "forecastId", "forecastHorizon"):
        _text(value[field], field)
    if not _DATE.fullmatch(_text(value["slateDate"], "slateDate")):
        raise ProspectiveEvidenceError("SLATE_DATE_INVALID", "slateDate must be YYYY-MM-DD")
    participants = value["participants"]
    if not isinstance(participants, list) or len(participants) != 2:
        raise ProspectiveEvidenceError("PARTICIPANTS_INVALID", "exactly two canonical participants required")
    participant_ids: list[str] = []
    participant_roles: list[str] = []
    for index, participant in enumerate(participants):
        item = _mapping(participant, f"participants[{index}]")
        _exact_keys(item, {"canonicalParticipantId", "displayName", "role"}, f"participants[{index}]")
        participant_ids.append(_text(item["canonicalParticipantId"], "canonicalParticipantId"))
        participant_roles.append(_text(item["role"], "role"))
        _text(item["displayName"], "displayName")
    if len(set(participant_ids)) != 2 or len(set(participant_roles)) != 2:
        raise ProspectiveEvidenceError("PARTICIPANT_IDENTITY_INVALID", "participants and roles must be distinct")
    start = _time(value["scheduledStart"], "scheduledStart")
    _integer(value["forecastRevision"], "forecastRevision", minimum=1)

    model = _mapping(value["model"], "model")
    _exact_keys(model, {"modelId", "modelVersion", "configurationId"}, "model")
    for field in model:
        _text(model[field], f"model.{field}")
    authority = _mapping(value["authority"], "authority")
    _exact_keys(authority, {"forecastAuthority", "researchOnlyEvidence", "decisionAuthority",
                            "positionAuthority", "stakeAuthority", "modelPromotionAuthority"}, "authority")
    if authority["forecastAuthority"] not in {"PRODUCTION_CHAMPION", "RESEARCH_ONLY"}:
        raise ProspectiveEvidenceError("FORECAST_AUTHORITY_INVALID", str(authority["forecastAuthority"]))
    if authority["researchOnlyEvidence"] is not True or any(
        authority[field] is not False for field in
        ("decisionAuthority", "positionAuthority", "stakeAuthority", "modelPromotionAuthority")
    ):
        raise ProspectiveEvidenceError("EVIDENCE_AUTHORITY_ESCALATION", "sidecar grants research evidence only")

    integrity = _mapping(value["integrity"], "integrity")
    _exact_keys(integrity, {"packageSha256", "populationSha256", "drawCount"}, "integrity")
    _sha(integrity["packageSha256"], "integrity.packageSha256")
    draws = _integer(integrity["drawCount"], "integrity.drawCount")
    population = _sha(integrity["populationSha256"], "integrity.populationSha256", nullable=True)
    if (draws == 0) != (population is None):
        raise ProspectiveEvidenceError(
            "POPULATION_BINDING_INVALID", "drawCount=0 requires null population; positive draws require a hash"
        )

    timing = _mapping(value["timing"], "timing")
    _exact_keys(timing, {"sourceCutoff", "forecastCreatedAt", "producerPublishedAt",
                         "exchangeDiscoveredAt", "consumerAcknowledgedAt",
                         "decisionWindowAvailableAt"}, "timing")
    cutoff = _time(timing["sourceCutoff"], "timing.sourceCutoff")
    created = _time(timing["forecastCreatedAt"], "timing.forecastCreatedAt")
    published = _time(timing["producerPublishedAt"], "timing.producerPublishedAt")
    discovered = _time(timing["exchangeDiscoveredAt"], "timing.exchangeDiscoveredAt", nullable=True)
    acknowledged = _time(timing["consumerAcknowledgedAt"], "timing.consumerAcknowledgedAt", nullable=True)
    decision_available = _time(timing["decisionWindowAvailableAt"], "timing.decisionWindowAvailableAt", nullable=True)
    if not cutoff <= created <= published < start:
        raise ProspectiveEvidenceError(
            "PREGAME_CHRONOLOGY_INVALID", "require sourceCutoff <= creation <= publication < start"
        )
    for field, observed in (("exchangeDiscoveredAt", discovered), ("consumerAcknowledgedAt", acknowledged),
                            ("decisionWindowAvailableAt", decision_available)):
        if observed is not None and observed < published:
            raise ProspectiveEvidenceError("DOWNSTREAM_TIME_INVALID", f"{field} precedes publication")

    supersedes = value["supersedes"]
    if supersedes is not None:
        prior = _mapping(supersedes, "supersedes")
        _exact_keys(prior, {"forecastId", "forecastRevision", "packageSha256", "evidenceSha256"}, "supersedes")
        _text(prior["forecastId"], "supersedes.forecastId")
        _integer(prior["forecastRevision"], "supersedes.forecastRevision", minimum=1)
        _sha(prior["packageSha256"], "supersedes.packageSha256")
        _sha(prior["evidenceSha256"], "supersedes.evidenceSha256")
        if prior["forecastRevision"] >= value["forecastRevision"]:
            raise ProspectiveEvidenceError("SUPERSESSION_INVALID", "superseded revision must be earlier")
    elif value["forecastRevision"] != 1:
        raise ProspectiveEvidenceError("SUPERSESSION_REQUIRED", "revision > 1 must bind its predecessor")

    markets = value["supportedMarkets"]
    if not isinstance(markets, list) or any(not isinstance(item, str) or not item for item in markets):
        raise ProspectiveEvidenceError("SUPPORTED_MARKETS_INVALID", "supportedMarkets must be a text list")
    if len(set(markets)) != len(markets):
        raise ProspectiveEvidenceError("SUPPORTED_MARKETS_DUPLICATED", "supportedMarkets contains duplicates")
    calibration = _mapping(value["calibrationCertificate"], "calibrationCertificate")
    _exact_keys(calibration, {"certificateId", "certificateSha256", "status"}, "calibrationCertificate")
    _text(calibration["certificateId"], "calibrationCertificate.certificateId")
    _sha(calibration["certificateSha256"], "calibrationCertificate.certificateSha256")
    if calibration["status"] not in {"CERTIFIED", "UNCERTIFIED"}:
        raise ProspectiveEvidenceError("CALIBRATION_STATUS_INVALID", str(calibration["status"]))

    dependencies = _mapping(value["dependencies"], "dependencies")
    _exact_keys(dependencies, set(DEPENDENCY_KEYS), "dependencies")
    for key in DEPENDENCY_KEYS:
        _validate_dependency(key, dependencies[key])
    receipt = _mapping(value["captureReceipt"], "captureReceipt")
    _exact_keys(receipt, {"receiptId", "receiptSha256", "capturedAt"}, "captureReceipt")
    _text(receipt["receiptId"], "captureReceipt.receiptId")
    _sha(receipt["receiptSha256"], "captureReceipt.receiptSha256")
    captured = _time(receipt["capturedAt"], "captureReceipt.capturedAt")
    if captured < published or captured >= start:
        raise ProspectiveEvidenceError("CAPTURE_TIME_INVALID", "pre-outcome capture must follow publication and precede start")
    if any(_time(dependencies[key]["observedAt"], f"dependencies.{key}.observedAt") > captured
           for key in DEPENDENCY_KEYS):
        raise ProspectiveEvidenceError("DEPENDENCY_TIME_INVALID", "dependency evidence must exist by capture")
    if not isinstance(value["limitations"], list) or any(not isinstance(item, str) or not item for item in value["limitations"]):
        raise ProspectiveEvidenceError("LIMITATIONS_INVALID", "limitations must be explicit text")
    return deepcopy(dict(value))


def append_revision(existing: Sequence[Mapping[str, Any]], new_record: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Append exactly one successor without changing prior records."""
    prior = [validate_pre_outcome(item) for item in existing]
    new = validate_pre_outcome(new_record)
    if not prior:
        if new["forecastRevision"] != 1 or new["supersedes"] is not None:
            raise ProspectiveEvidenceError("REVISION_CHAIN_INVALID", "first record must be revision 1")
        return (new,)
    latest = max(prior, key=lambda item: item["forecastRevision"])
    if len({item["forecastRevision"] for item in prior}) != len(prior):
        raise ProspectiveEvidenceError("REVISION_CHAIN_DUPLICATED", "duplicate revision")
    if new["evidenceSeriesId"] != latest["evidenceSeriesId"] or new["canonicalGameId"] != latest["canonicalGameId"]:
        raise ProspectiveEvidenceError("REVISION_CHAIN_IDENTITY_MISMATCH", "series and game must match")
    if new["forecastRevision"] != latest["forecastRevision"] + 1:
        raise ProspectiveEvidenceError("REVISION_CHAIN_NOT_APPEND_ONLY", "successor must increment latest revision")
    expected = {
        "forecastId": latest["forecastId"],
        "forecastRevision": latest["forecastRevision"],
        "packageSha256": latest["integrity"]["packageSha256"],
        "evidenceSha256": sha256_identity(latest),
    }
    if new["supersedes"] != expected:
        raise ProspectiveEvidenceError("SUPERSESSION_BINDING_MISMATCH", "successor does not bind exact predecessor")
    if _time(new["timing"]["forecastCreatedAt"], "new.created") <= _time(
        latest["timing"]["forecastCreatedAt"], "latest.created"
    ):
        raise ProspectiveEvidenceError("REVISION_TIME_NOT_APPEND_ONLY", "successor creation must be later")
    return tuple(deepcopy(prior + [new]))


def validate_calibration_certificate(record: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(record, "certificate")
    expected = {"schemaVersion", "certificateId", "status", "sport", "modelId", "configurationId",
                "probabilityChannel", "trainingPopulation", "evaluationPopulation", "evaluationDates",
                "sampleSize", "calibrationMethod", "metrics", "certifiedAt", "expirationRule",
                "artifacts", "authority", "missingRequirements"}
    _exact_keys(value, expected, "certificate")
    if value["schemaVersion"] != CALIBRATION_SCHEMA:
        raise ProspectiveEvidenceError("SCHEMA_VERSION_INVALID", "calibration schema differs")
    if value["status"] not in {"CERTIFIED", "UNCERTIFIED"}:
        raise ProspectiveEvidenceError("CALIBRATION_STATUS_INVALID", str(value["status"]))
    if value["sport"] not in SUPPORTED_SPORTS:
        raise ProspectiveEvidenceError("SPORT_INVALID", str(value["sport"]))
    for field in ("certificateId", "modelId", "configurationId", "probabilityChannel",
                  "trainingPopulation", "evaluationPopulation", "calibrationMethod", "expirationRule"):
        _text(value[field], field)
    dates = _mapping(value["evaluationDates"], "evaluationDates")
    _exact_keys(dates, {"start", "end"}, "evaluationDates")
    for field in dates:
        if not _DATE.fullmatch(_text(dates[field], f"evaluationDates.{field}")):
            raise ProspectiveEvidenceError("EVALUATION_DATE_INVALID", field)
    _integer(value["sampleSize"], "sampleSize")
    _time(value["certifiedAt"], "certifiedAt", nullable=value["status"] == "UNCERTIFIED")
    metrics = _mapping(value["metrics"], "metrics")
    metric_fields = {"preCalibration", "postCalibration", "reliabilityBands", "brier", "logLoss",
                     "calibrationIntercept", "calibrationSlope"}
    _exact_keys(metrics, metric_fields, "metrics")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, list):
        raise ProspectiveEvidenceError("CALIBRATION_ARTIFACTS_INVALID", "artifacts must be a list")
    for index, artifact in enumerate(artifacts):
        item = _mapping(artifact, f"artifacts[{index}]")
        _exact_keys(item, {"artifactId", "sha256", "bytes"}, f"artifacts[{index}]")
        _text(item["artifactId"], "artifactId")
        _sha(item["sha256"], "artifact.sha256")
        _integer(item["bytes"], "artifact.bytes", minimum=1)
    if value["authority"] not in {"RESEARCH_ONLY", "OPERATIONAL_CONSTITUENT_PROBABILITY"}:
        raise ProspectiveEvidenceError("CALIBRATION_AUTHORITY_INVALID", str(value["authority"]))
    missing = value["missingRequirements"]
    if not isinstance(missing, list) or any(not isinstance(item, str) or not item for item in missing):
        raise ProspectiveEvidenceError("MISSING_REQUIREMENTS_INVALID", "must be an explicit text list")
    if value["status"] == "UNCERTIFIED":
        if not missing:
            raise ProspectiveEvidenceError("UNCERTIFIED_REASON_REQUIRED", "missing requirement required")
    else:
        if missing or value["sampleSize"] <= 0 or not artifacts or any(metrics[field] is None for field in metric_fields):
            raise ProspectiveEvidenceError("CERTIFICATION_EVIDENCE_INCOMPLETE", "certified record requires complete metrics and artifacts")
    return deepcopy(dict(value))


def validate_post_outcome(record: Mapping[str, Any], pre_outcome: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an append-only assessment that refers to, but never embeds, pre-outcome evidence."""
    pre = validate_pre_outcome(pre_outcome)
    value = _mapping(record, "assessment")
    expected = {"schemaVersion", "assessmentId", "sport", "canonicalGameId", "preOutcomeEvidenceSha256",
                "scoredForecast", "finalResult", "outcomeAvailableAt", "assessmentCapturedAt",
                "assessmentDisposition", "exclusionReason", "frozenGateSegments", "frozenGateBinding"}
    _exact_keys(value, expected, "assessment")
    if value["schemaVersion"] != POST_OUTCOME_SCHEMA:
        raise ProspectiveEvidenceError("SCHEMA_VERSION_INVALID", "post-outcome schema differs")
    if value["sport"] != pre["sport"] or value["canonicalGameId"] != pre["canonicalGameId"]:
        raise ProspectiveEvidenceError("ASSESSMENT_GAME_IDENTITY_MISMATCH", "assessment and envelope differ")
    if _sha(value["preOutcomeEvidenceSha256"], "preOutcomeEvidenceSha256") != sha256_identity(pre):
        raise ProspectiveEvidenceError("PRE_OUTCOME_BINDING_MISMATCH", "assessment does not bind exact evidence bytes")
    scored = _mapping(value["scoredForecast"], "scoredForecast")
    _exact_keys(scored, {"forecastId", "forecastRevision", "packageSha256"}, "scoredForecast")
    if scored != {"forecastId": pre["forecastId"], "forecastRevision": pre["forecastRevision"],
                  "packageSha256": pre["integrity"]["packageSha256"]}:
        raise ProspectiveEvidenceError("SCORED_FORECAST_MISMATCH", "assessment forecast differs")
    final = _mapping(value["finalResult"], "finalResult")
    _exact_keys(final, {"resultId", "revision", "status", "participantResults", "resultSha256"}, "finalResult")
    _text(final["resultId"], "finalResult.resultId")
    _integer(final["revision"], "finalResult.revision", minimum=1)
    if final["status"] != "FINAL":
        raise ProspectiveEvidenceError("FINAL_RESULT_REQUIRED", str(final["status"]))
    _sha(final["resultSha256"], "finalResult.resultSha256")
    if not isinstance(final["participantResults"], list) or len(final["participantResults"]) != 2:
        raise ProspectiveEvidenceError("PARTICIPANT_RESULTS_INVALID", "two participant results required")
    result_ids = []
    for index, result in enumerate(final["participantResults"]):
        item = _mapping(result, f"participantResults[{index}]")
        _exact_keys(item, {"canonicalParticipantId", "outcome", "score"}, f"participantResults[{index}]")
        result_ids.append(_text(item["canonicalParticipantId"], "canonicalParticipantId"))
        if item["outcome"] not in {"WIN", "LOSS", "TIE", "DRAW", "NO_CONTEST"}:
            raise ProspectiveEvidenceError("PARTICIPANT_OUTCOME_INVALID", str(item["outcome"]))
        if item["score"] is not None and (
            isinstance(item["score"], bool) or not isinstance(item["score"], (int, float))
            or not math.isfinite(float(item["score"]))
        ):
            raise ProspectiveEvidenceError("PARTICIPANT_SCORE_INVALID", str(item["score"]))
    if set(result_ids) != {item["canonicalParticipantId"] for item in pre["participants"]}:
        raise ProspectiveEvidenceError("PARTICIPANT_RESULTS_IDENTITY_MISMATCH", "final participants differ")
    start = _time(pre["scheduledStart"], "scheduledStart")
    available = _time(value["outcomeAvailableAt"], "outcomeAvailableAt")
    captured = _time(value["assessmentCapturedAt"], "assessmentCapturedAt")
    if available < start or captured < available:
        raise ProspectiveEvidenceError("POST_OUTCOME_CHRONOLOGY_INVALID", "outcome follows start; capture follows outcome")
    if value["assessmentDisposition"] not in {"INCLUDED", "EXCLUDED"}:
        raise ProspectiveEvidenceError("ASSESSMENT_DISPOSITION_INVALID", str(value["assessmentDisposition"]))
    if (value["assessmentDisposition"] == "EXCLUDED") != bool(value["exclusionReason"]):
        raise ProspectiveEvidenceError("ASSESSMENT_EXCLUSION_REASON_INVALID", "excluded requires reason; included requires null")
    if not isinstance(value["frozenGateSegments"], list) or any(
        not isinstance(item, str) or not item for item in value["frozenGateSegments"]
    ):
        raise ProspectiveEvidenceError("FROZEN_SEGMENTS_INVALID", "segments must be text")
    binding = _mapping(value["frozenGateBinding"], "frozenGateBinding")
    _exact_keys(binding, {"designSha256", "resultsSha256"}, "frozenGateBinding")
    if binding != {"designSha256": FROZEN_DESIGN_SHA256, "resultsSha256": FROZEN_RESULTS_SHA256}:
        raise ProspectiveEvidenceError("FROZEN_GATE_BINDING_INVALID", "v1 gate hashes cannot change")
    return deepcopy(dict(value))


def validate_availability_receipt(record: Mapping[str, Any], pre_outcome: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an additive downstream clock without mutating producer evidence."""
    pre = validate_pre_outcome(pre_outcome)
    value = _mapping(record, "availabilityReceipt")
    expected = {"schemaVersion", "receiptId", "preOutcomeEvidenceSha256", "stage", "observedAt",
                "evidenceSource", "capturedAt", "pregameAvailable"}
    _exact_keys(value, expected, "availabilityReceipt")
    if value["schemaVersion"] != AVAILABILITY_SCHEMA:
        raise ProspectiveEvidenceError("SCHEMA_VERSION_INVALID", "availability schema differs")
    _text(value["receiptId"], "receiptId")
    if _sha(value["preOutcomeEvidenceSha256"], "preOutcomeEvidenceSha256") != sha256_identity(pre):
        raise ProspectiveEvidenceError("PRE_OUTCOME_BINDING_MISMATCH", "availability does not bind exact evidence")
    if value["stage"] not in {"EXCHANGE_DISCOVERY", "CONSUMER_ACKNOWLEDGEMENT", "DECISION_WINDOW_AVAILABILITY"}:
        raise ProspectiveEvidenceError("AVAILABILITY_STAGE_INVALID", str(value["stage"]))
    observed = _time(value["observedAt"], "observedAt")
    captured = _time(value["capturedAt"], "capturedAt")
    published = _time(pre["timing"]["producerPublishedAt"], "producerPublishedAt")
    start = _time(pre["scheduledStart"], "scheduledStart")
    if observed < published or captured < observed:
        raise ProspectiveEvidenceError("AVAILABILITY_CHRONOLOGY_INVALID", "observed follows publication; capture follows observation")
    expected_pregame = observed < start
    if value["pregameAvailable"] is not expected_pregame:
        raise ProspectiveEvidenceError("PREGAME_AVAILABILITY_INVALID", "pregameAvailable must be derived from observedAt")
    _text(value["evidenceSource"], "evidenceSource")
    return deepcopy(dict(value))


def unordered_pair_id(game_a: str, game_b: str) -> str:
    left, right = sorted((_text(game_a, "gameA"), _text(game_b, "gameB")))
    if left == right:
        raise ProspectiveEvidenceError("SAME_GAME_PAIR_FORBIDDEN", left)
    return left + "|" + right


def classify_pair(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    left, right = validate_pre_outcome(first), validate_pre_outcome(second)
    pair_id = unordered_pair_id(left["canonicalGameId"], right["canonicalGameId"])
    if left["slateDate"] != right["slateDate"]:
        raise ProspectiveEvidenceError("PAIR_DATE_MISMATCH", "prospective gate pairs must share slateDate")
    left_ids = {item["canonicalParticipantId"] for item in left["participants"]}
    right_ids = {item["canonicalParticipantId"] for item in right["participants"]}
    shared = sorted(left_ids & right_ids)
    shared_state = "CONFIRMED" if shared else "RULED_OUT"
    doubleheader = "CONFIRMED" if left["sport"] == right["sport"] == "MLB" and shared else "RULED_OUT"
    return {
        "pairId": pair_id,
        "gameIds": sorted([left["canonicalGameId"], right["canonicalGameId"]]),
        "slateDate": left["slateDate"],
        "sportPair": "+".join(sorted([left["sport"], right["sport"]])),
        "sharedParticipant": {"state": shared_state, "canonicalParticipantIds": shared,
                              "rule": "DERIVED_FROM_CANONICAL_PARTICIPANT_IDENTITY"},
        "doubleheader": {"state": doubleheader,
                         "rule": "MLB_SAME_DATE_SHARED_PARTICIPANT"},
        "eligibleForUnrelatedCategory": not shared,
    }


def readiness_state(category_id: str, pair_observations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count coverage only; never execute or authorize the frozen assessment."""
    _text(category_id, "categoryId")
    pairs: dict[str, dict[str, Any]] = {}
    for index, observation in enumerate(pair_observations):
        row = _mapping(observation, f"pairObservations[{index}]")
        _exact_keys(row, {"pairId", "gameIds", "slateDate", "probabilityBand", "eligible"},
                    f"pairObservations[{index}]")
        game_ids = row["gameIds"]
        if not isinstance(game_ids, list) or len(game_ids) != 2:
            raise ProspectiveEvidenceError("PAIR_GAMES_INVALID", str(index))
        expected = unordered_pair_id(game_ids[0], game_ids[1])
        if row["pairId"] != expected or game_ids != sorted(game_ids):
            raise ProspectiveEvidenceError("PAIR_IDENTITY_INVALID", str(index))
        if row["pairId"] in pairs:
            raise ProspectiveEvidenceError("PAIR_DUPLICATED", row["pairId"])
        if not _DATE.fullmatch(_text(row["slateDate"], "slateDate")):
            raise ProspectiveEvidenceError("SLATE_DATE_INVALID", str(row["slateDate"]))
        _text(row["probabilityBand"], "probabilityBand")
        if not isinstance(row["eligible"], bool):
            raise ProspectiveEvidenceError("PAIR_ELIGIBILITY_INVALID", str(index))
        pairs[row["pairId"]] = dict(row)
    admitted = [row for row in pairs.values() if row["eligible"]]
    games = {game for row in admitted for game in row["gameIds"]}
    dates = {row["slateDate"] for row in admitted}
    bands: dict[str, dict[str, Any]] = {}
    for band in sorted({row["probabilityBand"] for row in admitted}):
        part = [row for row in admitted if row["probabilityBand"] == band]
        band_dates = {row["slateDate"] for row in part}
        supported = (len(part) >= FROZEN_THRESHOLDS["minimumReliabilityBandPairs"] and
                     len(band_dates) >= FROZEN_THRESHOLDS["minimumReliabilityBandDates"])
        bands[band] = {"pairs": len(part), "dates": len(band_dates), "supported": supported}
    supported_bands = sum(int(item["supported"]) for item in bands.values())
    checks = {
        "games": len(games) >= FROZEN_THRESHOLDS["minimumGames"],
        "dates": len(dates) >= FROZEN_THRESHOLDS["minimumDates"],
        "uniqueUnorderedPairs": len(admitted) >= FROZEN_THRESHOLDS["minimumUniqueUnorderedPairs"],
        "reliabilityBands": supported_bands >= FROZEN_THRESHOLDS["minimumSupportedReliabilityBands"],
    }
    return {
        "schemaVersion": READINESS_SCHEMA,
        "categoryId": category_id,
        "frozenGateBinding": {"designSha256": FROZEN_DESIGN_SHA256, "resultsSha256": FROZEN_RESULTS_SHA256},
        "thresholds": deepcopy(FROZEN_THRESHOLDS),
        "coverage": {"games": len(games), "dates": len(dates), "uniqueUnorderedPairs": len(admitted),
                     "excludedPairs": len(pairs) - len(admitted), "supportedReliabilityBands": supported_bands,
                     "reliabilityBands": bands},
        "checks": checks,
        "readiness": "READY_FOR_FROZEN_ASSESSMENT" if all(checks.values()) else "COLLECTING",
        "assessmentAuthorized": False,
        "assessmentExecuted": False,
    }


def validate_readiness_record(record: Mapping[str, Any]) -> dict[str, Any]:
    value = _mapping(record, "readiness")
    expected = {"schemaVersion", "categoryId", "frozenGateBinding", "thresholds", "coverage",
                "checks", "readiness", "assessmentAuthorized", "assessmentExecuted"}
    _exact_keys(value, expected, "readiness")
    if value["schemaVersion"] != READINESS_SCHEMA:
        raise ProspectiveEvidenceError("SCHEMA_VERSION_INVALID", "readiness schema differs")
    _text(value["categoryId"], "categoryId")
    if value["frozenGateBinding"] != {"designSha256": FROZEN_DESIGN_SHA256,
                                      "resultsSha256": FROZEN_RESULTS_SHA256}:
        raise ProspectiveEvidenceError("FROZEN_GATE_BINDING_INVALID", "v1 gate hashes cannot change")
    if value["thresholds"] != FROZEN_THRESHOLDS:
        raise ProspectiveEvidenceError("FROZEN_THRESHOLDS_INVALID", "v1 readiness thresholds cannot change")
    coverage = _mapping(value["coverage"], "coverage")
    required_coverage = {"games", "dates", "uniqueUnorderedPairs", "excludedPairs",
                         "supportedReliabilityBands", "reliabilityBands"}
    _exact_keys(coverage, required_coverage, "coverage")
    for field in required_coverage - {"reliabilityBands"}:
        _integer(coverage[field], f"coverage.{field}")
    if not isinstance(coverage["reliabilityBands"], Mapping):
        raise ProspectiveEvidenceError("RELIABILITY_BANDS_INVALID", "must be an object")
    checks = _mapping(value["checks"], "checks")
    _exact_keys(checks, {"games", "dates", "uniqueUnorderedPairs", "reliabilityBands"}, "checks")
    if any(not isinstance(item, bool) for item in checks.values()):
        raise ProspectiveEvidenceError("READINESS_CHECK_INVALID", "checks must be boolean")
    expected_status = "READY_FOR_FROZEN_ASSESSMENT" if all(checks.values()) else "COLLECTING"
    if value["readiness"] != expected_status:
        raise ProspectiveEvidenceError("READINESS_STATUS_INVALID", "status and checks differ")
    if value["assessmentAuthorized"] is not False or value["assessmentExecuted"] is not False:
        raise ProspectiveEvidenceError("READINESS_AUTHORITY_INVALID", "readiness cannot authorize or execute")
    return deepcopy(dict(value))


def evidence_sidecar_binding(pre_outcome: Mapping[str, Any]) -> dict[str, Any]:
    record = validate_pre_outcome(pre_outcome)
    evidence_sha = sha256_identity(record)
    return {
        "schemaVersion": SIDECAR_SCHEMA,
        "packageSha256": record["integrity"]["packageSha256"],
        "preOutcomeEvidenceSha256": evidence_sha,
        "additiveObjectPath": f"prospective-cross-game-evidence-v1/objects/sha256/{evidence_sha}/pre-outcome-evidence.json",
        "activationState": "INACTIVE_NOT_PUBLISHED",
        "existingPackageMutation": False,
        "discoveryUpdate": False,
    }


def producer_integration_matrix() -> dict[str, dict[str, Any]]:
    return deepcopy({
        "MLB": {"owner": "server/sports_current_statcast/mlb_v18_current_publication.py",
                "hook": "after immutable forecast/package verification, before discovery update"},
        "NFL": {"owner": "server/sports_nfl_m1/current_state_repaired_publication.py",
                "hook": "after immutable forecast/package verification, before prospective index update"},
        "NBA": {"owner": "scripts/publish_nba_gen1_joint_prospective.py",
                "hook": "after research package verification, before any future discovery update"},
        "CFB": {"owner": "scripts/publish_cfb_gen1_current_v1.py",
                "hook": "after research package verification, before exchange publication"},
        "MMA": {"owner": "UNIMPLEMENTED_FUTURE_MMA_PUBLISHER",
                "hook": "future post-package-verification sidecar adapter"},
    })


__all__ = [
    "AVAILABILITY_SCHEMA", "CALIBRATION_SCHEMA", "DEPENDENCY_KEYS", "FROZEN_DESIGN_SHA256", "FROZEN_RESULTS_SHA256",
    "FROZEN_THRESHOLDS", "POST_OUTCOME_SCHEMA", "PRE_OUTCOME_SCHEMA", "ProspectiveEvidenceError",
    "READINESS_SCHEMA", "append_revision", "canonical_json_bytes", "classify_pair",
    "evidence_sidecar_binding", "producer_integration_matrix", "readiness_state", "sha256_identity",
    "unordered_pair_id", "validate_calibration_certificate", "validate_post_outcome", "validate_pre_outcome",
    "validate_availability_receipt", "validate_readiness_record",
]
