"""Synthetic tests for the bounded Phase 7B6 -> AISP example bridge."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from server.audit_assurance.canonical import canonical_json_bytes
from server.sports_gold import aisp_export_example as E


CLASS_ORDER = [
    "STRIKEOUT",
    "BIP_OUT",
    "WALK_HBP_CI",
    "HOME_RUN",
    "SINGLE",
    "DOUBLE",
    "TRIPLE",
    "OTHER_REACH",
]


def _distribution_points():
    return {
        "joint": [
            {"awayRuns": 3, "homeRuns": 4, "count": 6, "probability": 0.6},
            {"awayRuns": 5, "homeRuns": 2, "count": 4, "probability": 0.4},
        ],
        "margin": [
            {"homeMinusAway": 1, "count": 6, "probability": 0.6},
            {"homeMinusAway": -3, "count": 4, "probability": 0.4},
        ],
        "total": [{"totalRuns": 7, "count": 10, "probability": 1.0}],
    }


def _first_five():
    return {
        "completedSimulations": 10,
        "completionRate": 1.0,
        "homeWinProbability": 0.5,
        "awayWinProbability": 0.3,
        "tieProbability": 0.2,
        "expectedHomeRuns": 1.7,
        "expectedAwayRuns": 1.8,
        "expectedTotalRuns": 3.5,
        "jointScoreDistribution": [
            {"awayRuns": 1, "homeRuns": 2, "count": 5, "probability": 0.5},
            {"awayRuns": 2, "homeRuns": 2, "count": 2, "probability": 0.2},
            {"awayRuns": 3, "homeRuns": 1, "count": 3, "probability": 0.3},
        ],
        "runDifferenceDistribution": [
            {"homeMinusAway": 1, "count": 5, "probability": 0.5},
            {"homeMinusAway": 0, "count": 2, "probability": 0.2},
            {"homeMinusAway": -2, "count": 3, "probability": 0.3},
        ],
        "totalRunsDistribution": [
            {"totalRuns": 3, "count": 5, "probability": 0.5},
            {"totalRuns": 4, "count": 5, "probability": 0.5},
        ],
        "runUncertainty": {"totalRuns": {"standardDeviation": 0.8}},
    }


def _game_record(game_id: str, game_date: str, candidate: str) -> dict:
    points = _distribution_points()
    return {
        "schemaVersion": E.SOURCE_GAME_RESULT_SCHEMA,
        "cohortId": "HOLDOUT",
        "candidateId": candidate,
        "canonicalGameId": game_id,
        "predictionGameId": f"retrosheet:game:{game_id}",
        "awayTeamId": "team-away",
        "homeTeamId": "team-home",
        "gameDate": game_date,
        "season": int(game_date[:4]),
        "nSimulations": 10,
        "classOrder": CLASS_ORDER,
        "homeWinProbability": 0.6,
        "awayWinProbability": 0.4,
        "expectedHomeRuns": 3.2,
        "expectedAwayRuns": 3.8,
        "expectedTotalRuns": 7.0,
        "jointScoreDistribution": points["joint"],
        "runDifferenceDistribution": points["margin"],
        "totalRunsDistribution": points["total"],
        "runUncertainty": {"totalRuns": {"standardDeviation": 1.2}},
        "firstFive": _first_five(),
        "simulationStability": {
            "maximumAbsoluteDriftVsFinal": {"homeWinProbability": 0.05}
        },
        "nonterminated": 0,
        "illegalStates": 0,
    }


def _source_study(tmp_path: Path, records: list[dict]) -> Path:
    request = {
        "schemaVersion": "MLB_GOLD_GAME_SIMULATION_MARKET_MVP_REQUEST_V1",
        "sourceGold": {"logicalContentSha256": "c" * 64},
        "classOrder": CLASS_ORDER,
        "simulation": {
            "masterSeed": 90210,
            "simulationsPerGame": 10,
            "stabilityPrefixes": [10],
            "commonRandomNumbersAcrossEngines": True,
        },
        "prohibitedSeasons": [2025, 2026],
    }
    request_sha = hashlib.sha256(canonical_json_bytes(request)).hexdigest()
    root = tmp_path / "phase7b6" / "sha256" / request_sha
    root.mkdir(parents=True)
    results = {
        "schemaVersion": E.SOURCE_RESULT_SCHEMA,
        "status": E.SOURCE_STATUS,
        "requestSha256": request_sha,
        "population": {"candidateGameResultCount": len(records)},
        "candidateInventory": {"HOLDOUT": list(E.SOURCE_CANDIDATES)},
        "frozenModelEvidence": {
            "HOLDOUT": {
                "direct": {"sha256": "a" * 64},
                "e10": {"sha256": "b" * 64},
            }
        },
        "sportsbookBenchmark": {
            "status": "HISTORICAL_ODDS_INSUFFICIENT",
            "coveredGames": 0,
            "reason": "NO_GOVERNED_PERSISTED_HISTORICAL_SPORTSBOOK_QUOTES",
        },
        "paModelsFit": 0,
        "modelsPromoted": 0,
        "uses2025Or2026": False,
    }
    results_bytes = canonical_json_bytes(results)
    ledger_bytes = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    (root / "results.json").write_bytes(results_bytes)
    (root / "game-results.jsonl").write_bytes(ledger_bytes)
    artifacts = {}
    for name in ("results.json", "game-results.jsonl"):
        payload = (root / name).read_bytes()
        artifacts[name] = {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
    manifest = {
        "schemaVersion": E.SOURCE_MANIFEST_SCHEMA,
        "request": request,
        "requestSha256": request_sha,
        "resultsSha256": hashlib.sha256(results_bytes).hexdigest(),
        "artifacts": artifacts,
    }
    (root / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return root


def _paired_records() -> list[dict]:
    # Later game deliberately appears first; selection must still be chronological.
    return [
        _game_record("game-later", "2024-09-17", "E10"),
        _game_record("game-early", "2024-09-16", "DIRECT_GOLD"),
        _game_record("game-later", "2024-09-17", "DIRECT_GOLD"),
        _game_record("game-early", "2024-09-16", "E10"),
    ]


def test_bridge_verifies_selects_earliest_pair_and_publishes_exact_research_bundle(tmp_path):
    source = _source_study(tmp_path, _paired_records())
    exchange = tmp_path / "external-aisp"
    exchange.mkdir()
    evidence = E.publish_aisp_export_example(
        study_root=source, exchange_root=exchange
    )

    assert evidence.selected_event_id == "game-early"
    assert evidence.selected_event_date == "2024-09-16"
    assert len(set(evidence.forecast_ids)) == 2
    bundle = json.loads(evidence.publication.bundle_path.read_text(encoding="utf-8"))
    assert {item["engine"]["candidateId"] for item in bundle["forecasts"]} == {
        "DIRECT_GOLD",
        "E10",
    }
    assert all(item["scheduledStartUtc"] is None for item in bundle["forecasts"])
    assert all(item["forecastCutoffUtc"] is None for item in bundle["forecasts"])
    assert all(
        item["status"] == "RESEARCH_SHADOW_NOT_READY"
        for item in bundle["forecasts"]
    )
    assert bundle["marketQuotes"] == []
    assert bundle["betCandidates"] == []
    assert "HISTORICAL_ODDS_INSUFFICIENT" in bundle["readiness"]["missingInputs"]
    assert any(
        item["code"] == "HISTORICAL_ODDS_INSUFFICIENT"
        for item in bundle["explanations"]
    )
    assert bundle["forecasts"][0]["fullGame"]["jointScoreDistribution"]
    assert bundle["forecasts"][0]["firstFive"]["jointScoreDistribution"]
    wire = evidence.publication.bundle_path.read_text(encoding="utf-8")
    assert str(source) not in wire
    assert str(exchange) not in wire
    assert evidence.bundle_logical_uri.startswith("asp-model-exchange://")


def test_bridge_rejects_tampered_governed_artifact(tmp_path):
    source = _source_study(tmp_path, _paired_records())
    (source / "results.json").write_bytes((source / "results.json").read_bytes() + b"\n")
    exchange = tmp_path / "external-aisp"
    exchange.mkdir()
    with pytest.raises(E.AispExportExampleError, match="artifact bytes differ"):
        E.publish_aisp_export_example(study_root=source, exchange_root=exchange)


def test_bridge_rejects_missing_paired_holdout_engine(tmp_path):
    source = _source_study(
        tmp_path,
        [_game_record("game-a", "2024-09-16", "DIRECT_GOLD")],
    )
    exchange = tmp_path / "external-aisp"
    exchange.mkdir()
    with pytest.raises(E.AispExportExampleError, match="no paired"):
        E.publish_aisp_export_example(study_root=source, exchange_root=exchange)


def test_bridge_rejects_2025_source_before_publication(tmp_path):
    records = [
        _game_record("game-a", "2025-04-01", "DIRECT_GOLD"),
        _game_record("game-a", "2025-04-01", "E10"),
    ]
    source = _source_study(tmp_path, records)
    exchange = tmp_path / "external-aisp"
    exchange.mkdir()
    with pytest.raises(E.AispExportExampleError, match="2025"):
        E.publish_aisp_export_example(study_root=source, exchange_root=exchange)
