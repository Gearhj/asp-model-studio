from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np

from server.sports_current_statcast import mlb_v18_current_publication as publication
from server.sports_current_statcast import mlb_v18_player_prop_prospective_capture as capture
from server.sports_current_statcast.mlb_v18_player_prop_sidecar import PlayerPropCollector
from tests.test_mlb_v18_current_publication import (
    _SyntheticClock, _SyntheticPackagingEngine, _synthetic_complete_inputs,
)
from scripts.verify_mlb_v18_prospective_player_prop_capture import verify as verify_capture_root


def _event(pa: int, half: str, slot: int, outcome: str = "BIP_OUT"):
    return {"pa": pa, "half": half, "battingOrderPosition": slot,
            "pitcherState": "STARTER", "outcome": outcome}


def _payload(draws: int = 2):
    scheduled = "2099-04-01T18:00:00+00:00"
    captured = "2099-04-01T10:00:00+00:00"
    sides = []
    inputs = {}
    for side, batter_key, starter_key in (
        ("AWAY", "awayBatters", "awayStarter"),
        ("HOME", "homeBatters", "homeStarter"),
    ):
        authority = {"status": "CONFIRMED", "isComplete": True,
                     "observationId": side + "-lineup-v1", "availableAsOf": captured}
        starter = {"uuid": side + "-starter", "mlbamId": side + "P",
                   "name": side + " Starter", "observationId": side + "-starter-v1",
                   "availableAsOf": captured, "confirmationState": "CONFIRMED"}
        lineup = [{"player_id": f"{side}-batter-{slot}", "mlbam": f"{side}{slot}",
                   "full_name": f"{side} Batter {slot}", "batting_order": slot}
                  for slot in range(1, 10)]
        sides.append({"side": side, "team": {"uuid": side + "-team"},
                      "lineupAuthority": authority, "starter": starter, "lineup": lineup})
        inputs[batter_key] = [{"batterCanonicalPlayerId": f"model-{side}-{slot}"}
                              for slot in range(1, 10)]
        inputs[starter_key] = {"pitcherCanonicalPlayerId": "model-" + side + "-starter"}
    forecast = {
        "gameId": "game-1", "sourceGameId": "999", "capturedAt": captured,
        "forecastCreatedAt": "2099-04-01T10:01:00+00:00", "scheduledStart": scheduled,
        "sourceCutoff": {"snapshotCapturedAt": captured, "evidenceAvailableAt": captured},
        "teams": {row["side"]: row["team"] for row in sides},
        "starters": {row["side"]: row["starter"] for row in sides},
        "lineupAuthorities": {row["side"]: row["lineupAuthority"] for row in sides},
        "parentAuthority": {"bundleSha256": "b" * 64, "paModelSha256": "c" * 64,
                            "transitionModelSha256": "d" * 64, "paFold": 5,
                            "transitionFold": 4},
        "simulation": {"count": draws, "seed": 17},
    }
    population = {"simulationCount": draws, "paCounts": np.full(draws, 2),
                  "awayRuns": np.arange(draws) % 2, "homeRuns": np.ones(draws, dtype=int)}
    payload = {"forecast": forecast,
               "evidence": {"capturedAt": captured,
                            "game": {"game_id": "game-1", "starts_at": scheduled},
                            "sides": sides},
               "executionInputs": {"providerInputs": inputs, "population": population},
               "representativePath": {"gameId": "game-1", "events": [{"x": 1}]}}
    snapshot = payload["evidence"]
    return snapshot, payload


def test_forecast_identity_preview_matches_existing_publisher_bytes(tmp_path):
    snapshot, payload = _payload()
    planned = capture.planned_forecast_manifest(snapshot, payload)
    pointer = publication.daily._publish_game(tmp_path, snapshot, payload)
    actual = json.loads((tmp_path / pointer["relativePath"] / "manifest.json").read_bytes())
    assert pointer["objectSha256"] == planned["objectSha256"]
    assert actual == planned


def test_prospective_capture_is_content_addressed_development_only_and_idempotent(tmp_path):
    snapshot, payload = _payload()
    collector = PlayerPropCollector(2)
    for draw in range(2):
        collector(draw, _event(1, "TOP", 1, "SINGLE" if draw == 0 else "BIP_OUT"))
        collector(draw, _event(2, "BOTTOM", 1, "STRIKEOUT"))
    planned = capture.planned_forecast_manifest(snapshot, payload)
    created = datetime(2099, 4, 1, 10, 2, tzinfo=timezone.utc)
    first = capture.finalize_and_register(
        collector=collector, forecast_manifest=planned, payload=payload,
        output_root=tmp_path, created_at=created, observer_seconds=0.25,
    )
    assert first["status"] == "PROSPECTIVE_CAPTURE_REGISTERED"
    assert first["role"] == "DEVELOPMENT"
    assert first["additionalSimulationDraws"] == first["providerCalls"] == first["outcomeReads"] == 0
    manifest = json.loads((Path(first["packagePath"]) / "manifest.json").read_bytes())
    registration = json.loads((Path(first["packagePath"]) / "registration.json").read_bytes())
    assert manifest["forecastObjectSha256"] == planned["objectSha256"]
    assert registration["validationResultAccessAuthorized"] is False
    assert registration["roleDateAtomic"] is True
    assert registration["authority"]["aispWrite"] is False
    # A second collector with the same events and frozen clock must reuse exact bytes.
    again = PlayerPropCollector(2)
    for draw in range(2):
        again(draw, _event(1, "TOP", 1, "SINGLE" if draw == 0 else "BIP_OUT"))
        again(draw, _event(2, "BOTTOM", 1, "STRIKEOUT"))
    second = capture.finalize_and_register(
        collector=again, forecast_manifest=planned, payload=payload,
        output_root=tmp_path, created_at=created, observer_seconds=0.25,
    )
    assert second["packageSha256"] == first["packageSha256"]
    assert second["objectDisposition"] == "REUSED_BYTE_IDENTICAL"
    assert second["discoveryDisposition"] == "REUSED_BYTE_IDENTICAL"
    verified = verify_capture_root(tmp_path)
    assert verified["status"] == "VERIFIED" and verified["captureCount"] == 1


class _ObserverTransportEngine(_SyntheticPackagingEngine):
    def __init__(self):
        super().__init__()
        self.clean_payload = None

    def forecast(self, snapshot, composition, feature_snapshot):
        payload = super().forecast(snapshot, composition, feature_snapshot)
        self.clean_payload = deepcopy(payload)
        payload["_playerPropCapture"] = {"collector": object(), "observerSeconds": 0.1}
        return payload


def test_capture_failure_is_fail_open_and_forecast_bytes_remain_exact(tmp_path, monkeypatch):
    monkeypatch.setattr(publication, "datetime", _SyntheticClock)
    _SyntheticClock.current = datetime(2099, 4, 1, 11, tzinfo=timezone.utc)
    special = ["canonicalGameId", "canonicalPaId", "game_date",
               "batterCanonicalPlayerId", "pitcherCanonicalPlayerId"]
    columns = special + [f"synthetic_feature_{index}" for index in range(241)]
    monkeypatch.setattr(publication, "load_contract", lambda: {
        "rawFeatureColumns": columns, "treatedFeatureColumns": columns + ["treated"] * 27,
    })
    source, composed = _synthetic_complete_inputs("SYNTHETIC_CAPTURE_FAIL_OPEN")
    engine = _ObserverTransportEngine()
    monkeypatch.setattr(publication, "finalize_player_prop_capture",
                        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic")))
    result = publication.publish_composed_game(
        source, composed, output_root=tmp_path, engine=engine,
        player_prop_capture_root=tmp_path / "capture",
    )
    assert result["status"] == "PUBLISHED"
    assert result["playerPropCapture"]["status"] == "PLAYER_PROP_CAPTURE_FAILED_FORECAST_CONTINUES"
    object_root = tmp_path / result["relativePath"]
    manifest = json.loads((object_root / "manifest.json").read_bytes())
    assert manifest["objectSha256"] == result["objectSha256"]
    assert set(path.name for path in object_root.iterdir()) == {
        "forecast.json", "pregame-evidence.json", "execution-inputs.json",
        "representative-path.json", "manifest.json",
    }
    assert not any("_playerPropCapture" in path.read_text(encoding="utf-8")
                   for path in object_root.iterdir() if path.suffix == ".json")
    failures = list((tmp_path / "capture" / "failures" / "sha256").glob("*/failure.json"))
    assert len(failures) == 1
    failure = json.loads(failures[0].read_bytes())
    assert failure["forecastObjectSha256"] == result["objectSha256"]
    assert failure["forecastPublicationContinues"] is True


def test_no_cross_sport_or_authority_surface_is_present():
    source = Path(capture.__file__).read_text(encoding="utf-8")
    assert "event_observer" not in source  # observer wiring stays in the existing V18 engine
    assert '"providerCalls": 0' in source
    assert capture.AUTHORITY == {
        "researchOnly": True, "outcomeAccess": False, "exchangePublication": False,
        "aispWrite": False, "aispDisplay": False, "calibrationFit": False,
        "modelPromotion": False, "wagering": False,
    }


def test_observer_failure_disables_capture_without_raising_into_simulator():
    class BrokenCollector:
        def __call__(self, simulation, event):
            raise RuntimeError("synthetic observer failure")
    observer = capture.FailOpenPlayerPropObserver(BrokenCollector())
    observer(0, {"event": 1})
    observer(0, {"event": 2})
    assert observer.failure_category == "RuntimeError"
