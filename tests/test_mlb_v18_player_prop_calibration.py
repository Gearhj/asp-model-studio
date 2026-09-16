from __future__ import annotations

from datetime import date
import json

import numpy as np
import pytest

from server.sports_current_statcast.mlb_v18_player_prop_calibration import (
    PlayerPropCalibrationCaptureError,
    build_capture_record,
)
from server.sports_current_statcast.mlb_v18_player_prop_sidecar import (
    PlayerPropCollector,
    build_sidecar,
)


def _forecast():
    authority = {
        side: {"observationId": f"{side.lower()}-lineup"}
        for side in ("AWAY", "HOME")
    }
    starters = {
        side: {"uuid": f"{side.lower()}-starter"}
        for side in ("AWAY", "HOME")
    }
    return {
        "gameId": "game-1", "sourceGameId": "123",
        "forecastCreatedAt": "2026-09-16T16:00:00-04:00",
        "capturedAt": "2026-09-16T19:59:00Z",
        "scheduledStart": "2026-09-16T18:40:00-04:00",
        "sourceCutoff": {
            "evidenceAvailableAt": "2026-09-16T15:00:00-04:00",
            "snapshotCapturedAt": "2026-09-16T19:59:00Z",
            "playerHistoryCompleteThrough": "2026-09-15",
        },
        "lineupAuthorities": authority, "starters": starters,
        "simulation": {"count": 2, "seed": 7},
        "parentAuthority": {
            "paFold": 5, "paModelSha256": "c" * 64,
            "transitionFold": 4, "transitionModelSha256": "d" * 64,
        },
    }


def _evidence():
    sides = []
    for side in ("AWAY", "HOME"):
        sides.append({
            "side": side, "team": {"uuid": f"{side.lower()}-team"},
            "lineupAuthority": {
                "status": "CONFIRMED", "isComplete": True,
                "observationId": f"{side.lower()}-lineup",
                "availableAsOf": "2026-09-16T15:55:00-04:00",
            },
            "lineup": [
                {"player_id": f"{side.lower()}-batter-{slot}",
                 "mlbam": f"{side[0]}{slot}", "batting_order": slot}
                for slot in range(1, 10)
            ],
            "starter": {
                "uuid": f"{side.lower()}-starter", "mlbamId": f"{side[0]}P",
                "observationId": f"{side.lower()}-starter-observation",
                "availableAsOf": "2026-09-16T15:50:00-04:00",
                "confirmationState": "PROBABLE",
            },
        })
    return {"sides": sides}


def _sidecar(created_at: str):
    collector = PlayerPropCollector(2)
    collector(0, {"pa": 1, "half": "TOP", "battingOrderPosition": 1,
                  "pitcherState": "STARTER", "outcome": "SINGLE"})
    collector(1, {"pa": 1, "half": "BOTTOM", "battingOrderPosition": 1,
                  "pitcherState": "STARTER", "outcome": "STRIKEOUT"})
    accounting = collector.finalize({"simulationCount": 2, "paCounts": np.array([1, 1])})
    lineups = {
        side: [{"playerId": f"{side.lower()}-batter-{slot}", "mlbamId": f"{side[0]}{slot}",
                "displayName": f"{side} {slot}", "teamId": f"{side.lower()}-team",
                "modelTemplatePlayerId": f"model-{side}-{slot}", "battingOrderPosition": slot}
               for slot in range(1, 10)]
        for side in ("AWAY", "HOME")
    }
    starters = {
        side: {"playerId": f"{side.lower()}-starter", "mlbamId": f"{side[0]}P",
               "displayName": f"{side} starter", "teamId": f"{side.lower()}-team",
               "modelTemplatePlayerId": f"model-{side}-starter"}
        for side in ("AWAY", "HOME")
    }
    binding = {
        "gameId": "game-1", "sourceGameId": "123", "forecastId": "forecast-1",
        "forecastObjectSha256": "a" * 64, "populationSha256": "b" * 64,
        "modelId": "MLB_V18_HGB_PA", "modelArtifactSha256": "c" * 64,
        "transitionArtifactSha256": "d" * 64,
        "sourceCutoff": _forecast()["sourceCutoff"],
        "forecastCreatedAt": _forecast()["forecastCreatedAt"],
        "simulationCount": 2, "masterSeed": 7,
        "lineupAuthorities": _forecast()["lineupAuthorities"],
    }
    return build_sidecar(collector=collector, accounting=accounting, binding=binding,
                         lineups=lineups, starters=starters, created_at=created_at)


def _build(*, sidecar_created="2026-09-16T16:05:00-04:00", sidecar=True):
    payload, digest = _sidecar(sidecar_created) if sidecar else (None, None)
    return build_capture_record(
        forecast_manifest={"objectSha256": "a" * 64, "objectId": "forecast-1"},
        forecast=_forecast(), pregame_evidence=_evidence(),
        sidecar_payload=payload, sidecar_sha256=digest,
        model_training_end=date(2026, 5, 1),
        recorded_at="2026-09-16T16:06:00-04:00",
        historical_feature_chronology="UNCERTIFIED_HISTORICAL_FEATURE_CHRONOLOGY",
    )


def test_pregame_sidecar_is_ready_and_canonical():
    first, digest = _build(); second, second_digest = _build()
    assert first == second and digest == second_digest
    record = json.loads(first)
    assert record["assessmentEligible"] is True
    assert record["disposition"] == "PROSPECTIVE_CALIBRATION_CAPTURE_READY"
    assert record["resultJoin"]["status"] == "NOT_PERFORMED"
    assert len(record["participants"]) == 2


def test_missing_and_late_sidecars_fail_closed_for_assessment():
    pending, _ = _build(sidecar=False)
    assert json.loads(pending)["disposition"] == "SIDECAR_PENDING"
    late, _ = _build(sidecar_created="2026-09-16T18:41:00-04:00")
    value = json.loads(late)
    assert value["disposition"] == "RETROSPECTIVE_DERIVATION_ONLY"
    assert value["assessmentEligible"] is False


def test_lineup_revision_and_outcome_inputs_are_rejected():
    evidence = _evidence()
    evidence["sides"][0]["lineupAuthority"]["observationId"] = "later-lineup"
    with pytest.raises(PlayerPropCalibrationCaptureError, match="LINEUP_REVISION_MISMATCH"):
        build_capture_record(
            forecast_manifest={"objectSha256": "a" * 64, "objectId": "forecast-1"},
            forecast=_forecast(), pregame_evidence=evidence,
            sidecar_payload=None, sidecar_sha256=None,
            model_training_end=date(2026, 5, 1),
            recorded_at="2026-09-16T16:06:00-04:00",
            historical_feature_chronology="CERTIFIED",
        )
    forecast = _forecast(); forecast["actualHits"] = 3
    with pytest.raises(PlayerPropCalibrationCaptureError, match="OUTCOME_INPUT_PROHIBITED"):
        build_capture_record(
            forecast_manifest={"objectSha256": "a" * 64, "objectId": "forecast-1"},
            forecast=forecast, pregame_evidence=_evidence(),
            sidecar_payload=None, sidecar_sha256=None,
            model_training_end=date(2026, 5, 1),
            recorded_at="2026-09-16T16:06:00-04:00",
            historical_feature_chronology="CERTIFIED",
        )


def test_target_overlap_and_postforecast_evidence_are_rejected():
    with pytest.raises(PlayerPropCalibrationCaptureError, match="MODEL_TARGET_OVERLAP"):
        build_capture_record(
            forecast_manifest={"objectSha256": "a" * 64, "objectId": "forecast-1"},
            forecast=_forecast(), pregame_evidence=_evidence(),
            sidecar_payload=None, sidecar_sha256=None,
            model_training_end=date(2026, 9, 16),
            recorded_at="2026-09-16T16:06:00-04:00",
            historical_feature_chronology="CERTIFIED",
        )
    evidence = _evidence()
    evidence["sides"][1]["starter"]["availableAsOf"] = "2026-09-16T16:01:00-04:00"
    with pytest.raises(PlayerPropCalibrationCaptureError, match="STARTER_AFTER_FORECAST"):
        build_capture_record(
            forecast_manifest={"objectSha256": "a" * 64, "objectId": "forecast-1"},
            forecast=_forecast(), pregame_evidence=evidence,
            sidecar_payload=None, sidecar_sha256=None,
            model_training_end=date(2026, 5, 1),
            recorded_at="2026-09-16T16:06:00-04:00",
            historical_feature_chronology="CERTIFIED",
        )
