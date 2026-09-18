"""Synthetic checks for evidence extraction, never historical/outcome payloads."""
import hashlib
import json
import base64
from pathlib import Path
import struct
import sys
import zlib

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mlb_v18_wager_evidence_fields import extract_forecast_evidence, _prediction_counts, _indicators


def payload(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def fixture(tmp_path, *, date="2026-09-17", feature_path=None):
    root = tmp_path / "outputs" / "mlb-v18-current-state-pipeline-v1"
    feature = {"schemaVersion": "MLB_V18_CURRENT_STATE_FEATURE_SNAPSHOT_V1", "game": {"game_id": "test-game"},
               "composition": {"coverage": {"worstRawSupportedCount": 246}, "fieldReports": [
                   {"fields": [{"status": "EXPLICIT_LEGITIMATE_MISSING_FROZEN_TREATMENT_REQUIRED", "supported": True, "physicalValueMissing": True}]}]}}
    data = payload(feature)
    feature_sha = hashlib.sha256(data).hexdigest()
    target = root / "objects" / "sha256" / feature_sha / "feature-snapshot.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    forecast = {"gameId": "test-game", "sourceGameId": "test-source", "scheduledStart": date + "T23:00:00Z",
                "capturedAt": date + "T20:00:00Z", "forecastCreatedAt": date + "T20:05:00Z",
                "probabilities": {"homeWin": .5, "awayWin": .5}, "simulation": {"count": 2, "seed": 1},
                "monteCarloUncertainty": {"homeWinProbabilityStandardError": .01}}
    execution = {"featureSnapshot": {"path": str(feature_path or target), "sha256": feature_sha, "bytes": len(data)},
                 "rawTemplates": [{"a": None, "b": 1}], "treatedRows": [{"a": .2, "b": 1}],
                 "population": {"homeRuns": [3, 1], "awayRuns": [1, 2]}, "providerInputs": {}}
    objects = {"forecast.json": payload(forecast), "execution-inputs.json": payload(execution), "pregame-evidence.json": payload({"sides": []})}
    body = {"gameId": "test-game", "artifacts": [{"relativePath": name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()} for name, value in objects.items()]}
    digest = hashlib.sha256(payload(body)).hexdigest()
    directory = root / "objects" / "sha256" / digest
    directory.mkdir()
    for name, value in objects.items():
        (directory / name).write_bytes(value)
    (directory / "manifest.json").write_bytes(payload({**body, "objectId": "fixture", "objectSha256": digest}))
    return directory


def test_supported_cells_and_physical_missing_are_separate(tmp_path):
    row = extract_forecast_evidence(fixture(tmp_path), "2026-09-17T22:00:00Z")
    assert row["raw_missing_cells"] == 1 and row["treated_missing_cells"] == 0
    assert row["explicit_legitimate_missing_cells"] == 1 and row["unsupported_field_cells"] == 0
    assert row["mc_home_win_se_recorded"] == .01 and row["full_game_win_se_recorded"] is None
    assert row["forecast_before_decision"] is True
    assert row["p_home_draw_reconciliation_abs"] == 0
    assert row["source_payload_links_followed"] == row["outcomes_read"] == 0


def test_tampered_execution_fails_closed(tmp_path):
    directory = fixture(tmp_path)
    (directory / "execution-inputs.json").write_text("{}")
    with pytest.raises(ValueError, match="hash/size mismatch"):
        extract_forecast_evidence(directory)


def test_manifest_identity_fails_closed(tmp_path):
    directory = fixture(tmp_path)
    path = directory / "manifest.json"
    body = json.loads(path.read_text())
    body["gameId"] = "another-game"
    path.write_bytes(payload(body))
    with pytest.raises(ValueError, match="manifest identity mismatch"):
        extract_forecast_evidence(directory)


def test_protected_period_rejected_before_execution_open(tmp_path):
    directory = fixture(tmp_path, date="2026-08-20")
    (directory / "execution-inputs.json").unlink()
    with pytest.raises(ValueError, match="Protected MLB target period"):
        extract_forecast_evidence(directory)


def test_feature_path_outside_approved_root_is_never_opened(tmp_path):
    directory = fixture(tmp_path, feature_path=tmp_path / "sealed" / "feature-snapshot.json")
    row = extract_forecast_evidence(directory)
    assert row["feature_snapshot_status"] == "NOT_OPENED_UNAPPROVED_OR_PROTECTED_FEATURE_PATH"
    assert "NOT_OPENED" in row["evidence_gaps_json"]


def test_decision_without_timezone_rejected(tmp_path):
    with pytest.raises(ValueError, match="timestamp without timezone"):
        extract_forecast_evidence(fixture(tmp_path), "2026-09-17T22:00:00")


def vector(values):
    raw = struct.pack("<" + "H" * len(values), *values)
    return {"encoding": "BASE64_ZLIB_UINT16_LE_V1", "count": len(values),
            "rawSha256": hashlib.sha256(raw).hexdigest(), "data": base64.b64encode(zlib.compress(raw)).decode()}


def test_prediction_vector_decoder_rejects_corruption_and_excess_size():
    value = vector([10, 20])
    assert _prediction_counts(value, 2) == [10, 20]
    with pytest.raises(ValueError, match="checksum mismatch"):
        _prediction_counts({**value, "rawSha256": "0" * 64}, 2)
    with pytest.raises(ValueError, match="size invalid"):
        _prediction_counts({**vector([10, 20, 30]), "count": 2}, 2)


def test_affirmative_indicators_are_not_null_counts():
    assert _indicators([{"a_missing": 1, "b_insufficient": 1.0, "c_missing": 0,
                         "d_missing": None, "observed_runs": 1}]) == {"a_missing": 1, "b_insufficient": 1}


def test_observer_summary_and_original_late_diagnostic_clock(tmp_path):
    directory = fixture(tmp_path)
    object_sha = directory.name
    root = directory.parents[2].parent / "mlb-v18-player-prop-prospective-v1"
    registered = "2026-09-17T21:00:00Z"
    population_cells = [{"awayScore": 1, "homeScore": 3, "count": 1}, {"awayScore": 2, "homeScore": 1, "count": 1}]
    sidecar = {"schemaVersion": "ASP_MLB_V18_PLAYER_PROP_POPULATION_V1", "createdAt": registered,
               "binding": {"forecastObjectSha256": object_sha, "gameId": "test-game", "simulationCount": 2,
                           "masterSeed": 1, "populationSha256": hashlib.sha256(payload(population_cells)).hexdigest(),
                           "modelArtifactSha256": None, "transitionArtifactSha256": None,
                           "scheduledStart": "2026-09-17T23:00:00Z"},
               "startingPitchers": [{"side": side, "mlbamId": None, "playerId": None,
                                     "statistics": {"BATTERS_FACED": vector([10, 20]), "STRIKEOUTS": vector([2, 4])}}
                                    for side in ("AWAY", "HOME")],
               "anonymousReliefSummary": {side: {"BATTERS_FACED": vector([20, 10]), "STRIKEOUTS": vector([4, 2])}
                                          for side in ("AWAY", "HOME")}}
    registration = {"forecastObjectSha256": object_sha, "registeredAt": registered,
                    "timing": {"scheduledStart": "2026-09-17T23:00:00Z"}}
    parts = {"sidecar.json": payload(sidecar), "registration.json": payload(registration), "capture.json": payload({})}
    body = {"forecastObjectSha256": object_sha, "members": [{"relativePath": name, "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()} for name, value in parts.items()]}
    package_sha = hashlib.sha256(payload(body)).hexdigest()
    target = root / "objects" / "sha256" / package_sha
    target.mkdir(parents=True)
    for name, value in parts.items():
        (target / name).write_bytes(value)
    manifest = payload({**body, "packageId": "fixture", "packageSha256": package_sha})
    (target / "manifest.json").write_bytes(manifest)
    discovery = payload({"forecastObjectSha256": object_sha, "package": {"path": str(target), "sha256": package_sha, "manifestPhysicalSha256": hashlib.sha256(manifest).hexdigest()}})
    discovery_path = root / "discovery" / (package_sha + ".json")
    discovery_path.parent.mkdir()
    discovery_path.write_bytes(discovery)
    key_path = root / "forecast-keys" / (object_sha + ".json")
    key_path.parent.mkdir()
    key_path.write_bytes(payload({"forecastObjectSha256": object_sha, "discovery": {"path": str(discovery_path), "bytes": len(discovery), "sha256": hashlib.sha256(discovery).hexdigest()}}))
    row = extract_forecast_evidence(directory, "2026-09-17T20:30:00Z")
    assert row["observer_registered_at"] == registered
    assert row["observer_created_after_decision"] is True
    assert row["observer_registered_before_decision"] is False
    assert row["observer_registered_by_t15"] is True
    assert row["away_starter_bf_mean_derived"] == 15
    assert row["home_starter_k_mean_derived"] == 3
