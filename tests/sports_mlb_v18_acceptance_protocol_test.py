"""Focused synthetic tests for the predeclared V18 acceptance protocol."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_v18_acceptance_protocol import (
    BUNDLE_ID,
    BUNDLE_SHA256,
    PROTOCOL,
    SCHEMA_VERSION,
    TREATMENT_MANIFEST_SHA256,
    TREATMENT_SPECIFICATION_ID,
    AcceptanceProtocolError,
    chronological_block_ci,
    evaluate,
    protocol_sha256,
    validate_input,
)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _record(index: int, *, v18_probability: float = 0.5, gen1_probability: float = 0.5,
            home_wins: bool | None = None) -> dict:
    start = datetime(2026, 4, 1, 23, tzinfo=timezone.utc) + timedelta(days=index)
    forecast_at = start - timedelta(hours=2)
    if home_wins is None:
        home_wins = index % 2 == 0
    se = (v18_probability * (1-v18_probability) / 5000) ** 0.5
    regime = {name: None for name in PROTOCOL["regimeAtlasFields"]}
    regime.update({
        "league": "MLB", "season": 2026, "gameDate": start.date().isoformat(),
        "scheduledStart": _iso(start), "homeTeam": "HOME", "awayTeam": "AWAY",
        "lineupState": "CONFIRMED", "starterState": "PROBABLE",
        "starterHandedness": "R", "weatherAvailability": "AVAILABLE", "dayNight": "NIGHT",
        "predictedTotalBand": "[7,9)", "predictedWinProbabilityBand": "[0.4,0.6)",
        "unsupportedCapabilityFlags": [],
    })
    return {
        "gameId": f"game-{index:04d}", "league": "MLB", "season": 2026,
        "scheduledStart": _iso(start), "gameStatus": "FINAL", "scheduleRevisionId": "schedule-v1",
        "v18": {
            "forecastId": f"v18-{index:04d}", "gameId": f"game-{index:04d}",
            "bundleId": BUNDLE_ID, "bundleSha256": BUNDLE_SHA256,
            "forecastAt": _iso(forecast_at), "evidenceCutoff": _iso(forecast_at-timedelta(minutes=1)),
            "inputReceipts": [{
                "source": "FIXTURE", "observedAt": _iso(forecast_at-timedelta(hours=1)),
                "receivedAt": _iso(forecast_at-timedelta(minutes=30)), "lineageSha256": "a"*64,
            }],
            "lineupState": "CONFIRMED", "lineupObservedAt": _iso(forecast_at-timedelta(hours=1)),
            "starterState": "PROBABLE", "starterObservedAt": _iso(forecast_at-timedelta(hours=1)),
            "treatmentSpecificationId": TREATMENT_SPECIFICATION_ID,
            "treatmentManifestSha256": TREATMENT_MANIFEST_SHA256,
            "rawInputCount": 246, "treatedInputCount": 273,
            "paProbabilitiesNormalized": True, "probabilityNormalizationMaxError": 1e-12,
            "simulationCount": 5000, "monteCarloStandardError": se,
            "monteCarlo95HalfWidth": 1.96*se, "seedPolicy": "FIXED_LINEAGE_V1",
            "pathDigest": f"{index:064x}", "nonterminationCount": 0, "illegalStateCount": 0,
            "deterministicReplayVerified": True, "persistenceCount": 1,
            "homeWinProbability": v18_probability, "expectedHomeRuns": 4.2,
            "expectedAwayRuns": 4.0, "expectedTotalRuns": 8.2, "expectedRunDifferential": 0.2,
            "oneRunProbability": 0.28, "extraInningProbability": 0.10, "totalRunPmf": [],
            "wageringAuthority": False, "gen1HistoryMutated": False, "regime": regime,
        },
        "gen1": {
            "forecastId": f"gen1-{index:04d}", "gameId": f"game-{index:04d}",
            "forecastAt": _iso(forecast_at-timedelta(minutes=10)),
            "homeWinProbability": gen1_probability, "persistenceCount": 1,
            "reconstructedAfterEvent": False,
        },
        "settlement": {
            "settlementId": f"settled-{index:04d}", "gameId": f"game-{index:04d}",
            "status": "FINAL", "settledAt": _iso(start+timedelta(hours=4)), "immutable": True,
            "homeRuns": 5 if home_wins else 2, "awayRuns": 2 if home_wins else 5,
            "extraInnings": False, "lineageSha256": "b"*64,
        },
        "markets": [],
    }


def _payload(records: list[dict]) -> dict:
    return {"schemaVersion": SCHEMA_VERSION, "protocolSha256": protocol_sha256(), "records": records}


def test_contract_validation_and_checksum() -> None:
    payload = _payload([])
    validate_input(payload)
    assert protocol_sha256() == hashlib.sha256(canonical_json_bytes(PROTOCOL)).hexdigest()
    with pytest.raises(AcceptanceProtocolError):
        validate_input({**payload, "schemaVersion": "WRONG"})
    with pytest.raises(AcceptanceProtocolError):
        validate_input({**payload, "protocolSha256": "0"*64})


def test_pairing_exclusions_are_immutable_and_output_is_deterministic() -> None:
    duplicate = _record(1)
    payload = _payload([duplicate, deepcopy(duplicate)])
    first, second = evaluate(payload), evaluate(payload)
    assert first == second
    assert first["metrics"]["pairedGames"] == 0
    assert all("DUPLICATE_GAME_ID" in row["pairReasons"] for row in first["exclusions"])


def test_metric_and_confidence_interval_direction() -> None:
    values = [-0.04] * 40
    dates = [_iso(datetime(2026, 4, 1, tzinfo=timezone.utc) + timedelta(days=i)) for i in range(40)]
    interval = chronological_block_ci(values, dates, resamples=500)
    assert interval["upper"] < 0
    records = [
        _record(i, v18_probability=0.60 if i % 2 == 0 else 0.40,
                gen1_probability=0.55 if i % 2 == 0 else 0.45)
        for i in range(100)
    ]
    result = evaluate(_payload(records))
    assert result["metrics"]["primary"]["difference"] < 0
    assert result["metrics"]["primary"]["confidenceInterval"]["upper"] < 0


def test_evidence_states_and_insufficient_evidence() -> None:
    assert evaluate(_payload([]))["evidenceState"] == "NOT_STARTED"
    assert evaluate(_payload([_record(1)]))["evidenceState"] == "INSUFFICIENT_EVIDENCE"
    neutral = evaluate(_payload([_record(i) for i in range(250)]))
    assert neutral["evidenceState"] == "ADVANCE_AS_NONINFERIOR"
    adverse = [
        _record(i, v18_probability=0.40 if i % 2 == 0 else 0.60,
                gen1_probability=0.60 if i % 2 == 0 else 0.40)
        for i in range(100)
    ]
    assert evaluate(_payload(adverse))["evidenceState"] == "MATERIAL_REGRESSION"
    broken = [_record(i) for i in range(20)]
    broken[0]["v18"]["bundleSha256"] = "0"*64
    assert evaluate(_payload(broken))["evidenceState"] == "OPERATIONAL_FAILURE"


def test_missing_market_is_not_failure() -> None:
    result = evaluate(_payload([_record(i) for i in range(20)]))
    assert result["market"]["status"] == "NOT_EVALUABLE"
    assert result["evidenceState"] == "CONTINUE_RESEARCH_SHADOW"
    assert result["operational"]["accepted"] is True
    assert result["operational"]["participantStateCoverage"]["lineupConfirmationCoverage"] == 1.0
    assert result["operational"]["monteCarloUncertainty"]["minimumSimulationCount"] == 5000


def test_checked_in_fixture_executes_as_insufficient_evidence() -> None:
    path = Path(__file__).resolve().parent / "fixtures/mlb_v18_acceptance_records.json"
    result = evaluate(json.loads(path.read_text(encoding="utf-8")))
    assert result["evidenceState"] == "INSUFFICIENT_EVIDENCE"
    assert result["metrics"]["pairedGames"] == 1
    assert result["market"]["status"] == "NOT_EVALUABLE"
