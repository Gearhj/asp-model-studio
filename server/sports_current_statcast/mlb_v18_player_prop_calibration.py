"""Fail-closed registration for future V18 player-prop calibration captures.

The module is intentionally pure and inactive.  It authenticates the already
implemented player-prop sidecar against one immutable pregame forecast and
classifies whether the player population was retained before first pitch.  It
does not read results, contact a provider, publish an artifact, or grant model
or wagering authority.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from server.sports_current_statcast.mlb_v18_player_prop_sidecar import (
    canonical_json_bytes,
    sha256_bytes,
    verify_sidecar,
)


SCHEMA_VERSION = "MLB_V18_PLAYER_PROP_CALIBRATION_CAPTURE_V1"


class PlayerPropCalibrationCaptureError(ValueError):
    """Raised when a proposed calibration capture cannot be admitted."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def _time(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise PlayerPropCalibrationCaptureError("TIME_INVALID", field) from error
    if parsed.tzinfo is None:
        raise PlayerPropCalibrationCaptureError("TIME_INVALID", field + " must be timezone-aware")
    return parsed


def _identity(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise PlayerPropCalibrationCaptureError("IDENTITY_MISSING", field)
    return text


def _forbid_outcome_inputs(value: Any, path: str = "input") -> None:
    """Reject fields that would turn a pregame capture into a result join."""

    prohibited = {
        "actual", "actualhits", "actualtotalbases", "actualhomeruns",
        "actualstrikeouts", "actualstarterbattersfaced", "finalscore",
        "postgameparticipation", "realizedplateappearances", "playergameresult",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).replace("_", "").lower()
            if normalized in prohibited:
                raise PlayerPropCalibrationCaptureError(
                    "OUTCOME_INPUT_PROHIBITED", f"{path}.{key}"
                )
            _forbid_outcome_inputs(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _forbid_outcome_inputs(item, f"{path}[{index}]")


def _side_bindings(evidence: Mapping[str, Any], forecast: Mapping[str, Any]) -> list[dict[str, Any]]:
    sides = {str(row.get("side", "")).upper(): row for row in evidence.get("sides", [])}
    result: list[dict[str, Any]] = []
    for side in ("AWAY", "HOME"):
        row = sides.get(side) or {}
        authority = row.get("lineupAuthority") or {}
        lineup = list(row.get("lineup") or [])
        slots = sorted(int(item.get("batting_order", 0)) for item in lineup)
        if authority.get("status") != "CONFIRMED" or authority.get("isComplete") is not True:
            raise PlayerPropCalibrationCaptureError("LINEUP_NOT_CONFIRMED", side)
        if len(lineup) != 9 or slots != list(range(1, 10)):
            raise PlayerPropCalibrationCaptureError("LINEUP_INCOMPLETE", side)
        if len({_identity(item.get("player_id"), f"{side}.lineup.player_id") for item in lineup}) != 9:
            raise PlayerPropCalibrationCaptureError("LINEUP_IDENTITY_CONFLICT", side)
        starter = row.get("starter") or {}
        starter_id = _identity(starter.get("uuid"), f"{side}.starter.uuid")
        _identity(starter.get("mlbamId"), f"{side}.starter.mlbamId")
        forecast_authority = ((forecast.get("lineupAuthorities") or {}).get(side) or {})
        if forecast_authority.get("observationId") != authority.get("observationId"):
            raise PlayerPropCalibrationCaptureError("LINEUP_REVISION_MISMATCH", side)
        forecast_starter = ((forecast.get("starters") or {}).get(side) or {})
        if str(forecast_starter.get("uuid") or "") != starter_id:
            raise PlayerPropCalibrationCaptureError("STARTER_REVISION_MISMATCH", side)
        result.append({
            "side": side,
            "teamId": _identity((row.get("team") or {}).get("uuid"), f"{side}.team.uuid"),
            "lineupObservationId": _identity(authority.get("observationId"), f"{side}.lineup.observationId"),
            "lineupAvailableAsOf": _time(authority.get("availableAsOf"), f"{side}.lineup.availableAsOf").isoformat(),
            "lineupStatus": "CONFIRMED",
            "lineupSize": 9,
            "starterPlayerId": starter_id,
            "starterMlbamId": str(starter["mlbamId"]),
            "starterObservationId": _identity(starter.get("observationId"), f"{side}.starter.observationId"),
            "starterAvailableAsOf": _time(starter.get("availableAsOf"), f"{side}.starter.availableAsOf").isoformat(),
            "starterConfirmationState": str(starter.get("confirmationState") or "UNSPECIFIED"),
        })
    return result


def build_capture_record(
    *,
    forecast_manifest: Mapping[str, Any],
    forecast: Mapping[str, Any],
    pregame_evidence: Mapping[str, Any],
    sidecar_payload: bytes | None,
    sidecar_sha256: str | None,
    model_training_end: date,
    recorded_at: str,
    historical_feature_chronology: str,
) -> tuple[bytes, str]:
    """Return one canonical, outcome-free prospective capture declaration.

    A missing sidecar is a valid pending declaration.  A sidecar created after
    first pitch is retained as retrospective mechanical evidence but cannot
    enter the prospective calibration cohort.
    """

    for value in (forecast_manifest, forecast, pregame_evidence):
        _forbid_outcome_inputs(value)
    if historical_feature_chronology not in {
        "CERTIFIED", "UNCERTIFIED_HISTORICAL_FEATURE_CHRONOLOGY"
    }:
        raise PlayerPropCalibrationCaptureError(
            "MODEL_CHRONOLOGY_STATUS_INVALID", historical_feature_chronology
        )
    object_sha = _identity(forecast_manifest.get("objectSha256"), "manifest.objectSha256")
    forecast_id = _identity(forecast_manifest.get("objectId"), "manifest.objectId")
    game_id = _identity(forecast.get("gameId"), "forecast.gameId")
    source_game_id = _identity(forecast.get("sourceGameId"), "forecast.sourceGameId")
    created = _time(forecast.get("forecastCreatedAt"), "forecast.forecastCreatedAt")
    captured = _time(forecast.get("capturedAt"), "forecast.capturedAt")
    scheduled = _time(forecast.get("scheduledStart"), "forecast.scheduledStart")
    registered = _time(recorded_at, "recordedAt")
    cutoff = forecast.get("sourceCutoff") or {}
    available = _time(cutoff.get("evidenceAvailableAt"), "forecast.sourceCutoff.evidenceAvailableAt")
    snapshot = _time(cutoff.get("snapshotCapturedAt"), "forecast.sourceCutoff.snapshotCapturedAt")
    if not (available <= created and snapshot <= created and captured <= created < scheduled):
        raise PlayerPropCalibrationCaptureError(
            "PREGAME_CHRONOLOGY_INVALID", "source/capture/create/start order differs"
        )
    if model_training_end >= scheduled.date():
        raise PlayerPropCalibrationCaptureError(
            "MODEL_TARGET_OVERLAP", "training end is not earlier than the target game"
        )
    sides = _side_bindings(pregame_evidence, forecast)
    for row in sides:
        if _time(row["lineupAvailableAsOf"], "lineupAvailableAsOf") > created:
            raise PlayerPropCalibrationCaptureError("LINEUP_AFTER_FORECAST", row["side"])
        if _time(row["starterAvailableAsOf"], "starterAvailableAsOf") > created:
            raise PlayerPropCalibrationCaptureError("STARTER_AFTER_FORECAST", row["side"])

    sidecar_record: dict[str, Any]
    blockers: list[str] = []
    if sidecar_payload is None or sidecar_sha256 is None:
        sidecar_record = {"status": "PENDING", "sha256": None, "createdAt": None}
        blockers.append("PLAYER_PROP_SIDECAR_NOT_CAPTURED")
        disposition = "SIDECAR_PENDING"
    else:
        document = verify_sidecar(sidecar_payload, sidecar_sha256)
        _forbid_outcome_inputs(document, "sidecar")
        binding = document.get("binding") or {}
        comparisons = {
            "gameId": game_id,
            "sourceGameId": source_game_id,
            "forecastId": forecast_id,
            "forecastObjectSha256": object_sha,
            "modelArtifactSha256": (forecast.get("parentAuthority") or {}).get("paModelSha256"),
            "transitionArtifactSha256": (forecast.get("parentAuthority") or {}).get("transitionModelSha256"),
            "simulationCount": int((forecast.get("simulation") or {}).get("count", 0)),
        }
        for field, expected in comparisons.items():
            if binding.get(field) != expected:
                raise PlayerPropCalibrationCaptureError("SIDECAR_BINDING_MISMATCH", field)
        sidecar_created = _time(document.get("createdAt"), "sidecar.createdAt")
        sidecar_record = {
            "status": "AUTHENTICATED",
            "sha256": sidecar_sha256,
            "createdAt": sidecar_created.isoformat(),
            "capturedBeforeScheduledStart": sidecar_created < scheduled,
        }
        if sidecar_created >= scheduled:
            blockers.append("SIDECAR_DERIVED_AFTER_SCHEDULED_START")
            disposition = "RETROSPECTIVE_DERIVATION_ONLY"
        else:
            disposition = "PROSPECTIVE_CALIBRATION_CAPTURE_READY"

    parent = forecast.get("parentAuthority") or {}
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "recordedAt": registered.isoformat(),
        "disposition": disposition,
        "assessmentEligible": disposition == "PROSPECTIVE_CALIBRATION_CAPTURE_READY",
        "blockers": blockers,
        "game": {
            "gameId": game_id,
            "sourceGameId": source_game_id,
            "scheduledStart": scheduled.isoformat(),
        },
        "forecast": {
            "forecastId": forecast_id,
            "objectSha256": object_sha,
            "createdAt": created.isoformat(),
            "capturedAt": captured.isoformat(),
            "sourceCutoff": cutoff,
            "simulationCount": int((forecast.get("simulation") or {}).get("count", 0)),
            "masterSeed": int((forecast.get("simulation") or {}).get("seed", 0)),
        },
        "model": {
            "modelId": "MLB_V18_HGB_PA",
            "paFold": parent.get("paFold"),
            "paModelSha256": parent.get("paModelSha256"),
            "transitionFold": parent.get("transitionFold"),
            "transitionModelSha256": parent.get("transitionModelSha256"),
            "trainingEnd": model_training_end.isoformat(),
            "targetAndLaterEvidenceExcludedByDate": True,
            "historicalFeatureChronology": historical_feature_chronology,
        },
        "participants": sides,
        "sidecar": sidecar_record,
        "resultJoin": {
            "status": "NOT_PERFORMED",
            "requiredFutureAuthority": "GOVERNED_PLAYER_GAME_RESULT_WITH_REVISION_AND_CAPTURE_TIMES",
        },
        "limitations": [
            "FIXED_CONFIRMED_STARTING_LINEUP_WITHOUT_SUBSTITUTION_MODEL",
            "STARTER_REMOVAL_AND_ANONYMOUS_RELIEF_LIMIT_STARTER_STRIKEOUT_INTERPRETATION",
            "NO_SCRATCH_NONPARTICIPATION_OR_VOID_PROBABILITY",
            historical_feature_chronology,
        ],
        "authority": {
            "researchOnly": True,
            "resultAccess": False,
            "exchangePublication": False,
            "aispDisplay": False,
            "calibrationFit": False,
            "modelPromotion": False,
            "wagering": False,
        },
    }
    payload = canonical_json_bytes(record)
    return payload, sha256_bytes(payload)


__all__ = [
    "PlayerPropCalibrationCaptureError",
    "SCHEMA_VERSION",
    "build_capture_record",
]
