"""Synthetic, source-free tests for the sport-neutral AISP export boundary."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from server.sports_gold import aisp_export_contracts as A


SHA_A = "a" * 64
SHA_B = "b" * 64


def _period(*, first_five: bool = False) -> dict:
    if first_five:
        return {
            "available": True,
            "missingReason": None,
            "completedSimulations": 1000,
            "completionRate": 1.0,
            "homeWinProbability": 0.5,
            "awayWinProbability": 0.3,
            "tieProbability": 0.2,
            "expectedHomeScore": 1.7,
            "expectedAwayScore": 1.8,
            "expectedTotalScore": 3.5,
            "jointScoreDistribution": [
                {"awayScore": 1, "homeScore": 2, "probability": 0.5},
                {"awayScore": 2, "homeScore": 2, "probability": 0.2},
                {"awayScore": 3, "homeScore": 1, "probability": 0.3},
            ],
            "scoreMarginDistribution": [
                {"homeMinusAway": 1, "probability": 0.5},
                {"homeMinusAway": 0, "probability": 0.2},
                {"homeMinusAway": -2, "probability": 0.3},
            ],
            "totalScoreDistribution": [
                {"totalScore": 3, "probability": 0.5},
                {"totalScore": 4, "probability": 0.5},
            ],
        }
    return {
        "available": True,
        "missingReason": None,
        "completedSimulations": 1000,
        "completionRate": 1.0,
        "homeWinProbability": 0.6,
        "awayWinProbability": 0.4,
        "tieProbability": 0.0,
        "expectedHomeScore": 3.2,
        "expectedAwayScore": 3.8,
        "expectedTotalScore": 7.0,
        "jointScoreDistribution": [
            {"awayScore": 3, "homeScore": 4, "probability": 0.6},
            {"awayScore": 5, "homeScore": 2, "probability": 0.4},
        ],
        "scoreMarginDistribution": [
            {"homeMinusAway": 1, "probability": 0.6},
            {"homeMinusAway": -3, "probability": 0.4},
        ],
        "totalScoreDistribution": [{"totalScore": 7, "probability": 1.0}],
    }


def _forecast() -> dict:
    record = {
        "schemaVersion": A.AISP_GAME_FORECAST_EXPORT_V1,
        "forecastId": "PENDING",
        "sport": "BASEBALL",
        "league": "MLB",
        "eventId": "game-a",
        "sourceEventId": "retrosheet:game:AAA202404010",
        "eventDate": "2024-04-01",
        "season": 2024,
        "homeTeam": {"teamId": "team-home", "displayName": None},
        "awayTeam": {"teamId": "team-away", "displayName": None},
        # The governed historical authority has no scheduled-start timestamp.
        "scheduledStartUtc": None,
        "forecastCutoffUtc": None,
        "engine": {
            "engineId": "E10",
            "engineVersion": "PHASE_7B5_FROZEN",
            "candidateId": "E10",
            "modelArtifactSha256": SHA_A,
            "inputDataSha256": SHA_B,
            "classOrder": [
                "STRIKEOUT",
                "BIP_OUT",
                "WALK_HBP_CI",
                "HOME_RUN",
                "SINGLE",
                "DOUBLE",
                "TRIPLE",
                "OTHER_REACH",
            ],
        },
        "simulator": {
            "simulatorId": "WHOLE_GAME_MONTE_CARLO",
            "simulatorVersion": "V1",
            "seed": 17,
            "simulationCount": 1000,
            "completedSimulations": 1000,
            "nonterminationCount": 0,
            "illegalStateCount": 0,
        },
        "fullGame": _period(),
        "firstFive": _period(first_five=True),
        "uncertainty": {
            "method": "COMMON_RNG_BATCH_INTERVAL",
            "confidenceLevel": 0.95,
            "homeWinProbabilityLower": 0.57,
            "homeWinProbabilityUpper": 0.63,
            "awayWinProbabilityLower": 0.37,
            "awayWinProbabilityUpper": 0.43,
            "firstFiveHomeWinProbabilityLower": 0.47,
            "firstFiveHomeWinProbabilityUpper": 0.53,
            "expectedTotalScoreStdError": 0.08,
            "firstFiveExpectedTotalScoreStdError": 0.05,
            "maxBatchProbabilityDelta": 0.02,
        },
        "readiness": {
            "isReady": False,
            "score": 80,
            "threshold": 85,
            "missingInputs": ["SCHEDULED_START_UTC", "FORECAST_CUTOFF_UTC"],
            "reasonCodes": ["TIMESTAMP_AUTHORITY_UNAVAILABLE"],
        },
        "explanations": [
            {
                "code": "RESEARCH_ONLY_ENGINE",
                "summary": "Frozen research simulation",
                "detail": "No model was promoted and no execution is permitted.",
            }
        ],
        "status": "RESEARCH_SHADOW_NOT_READY",
        "researchShadowOnly": True,
        "executionAllowed": False,
        "modelPromotionAllowed": False,
    }
    record["forecastId"] = A.derive_game_forecast_id(record)
    return record


def _quote() -> dict:
    decimal_odds = 1.0 + 100.0 / 110.0
    implied = 1.0 / decimal_odds
    outcomes = []
    for selection in ("OVER", "UNDER"):
        outcomes.append(
            {
                "selection": selection,
                "line": 4.5,
                "americanOdds": -110,
                "decimalOdds": decimal_odds,
                "rawImpliedProbability": implied,
                "breakEvenProbability": implied,
                "noVigProbability": 0.5,
                "fairDecimalOdds": 2.0,
                "fairAmericanOdds": 100.0,
            }
        )
    return {
        "schemaVersion": A.AISP_MARKET_QUOTE_V1,
        "quoteId": "quote-game-a-home-total",
        "sport": "BASEBALL",
        "league": "MLB",
        "eventId": "game-a",
        "eventDate": "2024-04-01",
        "homeTeamId": "team-home",
        "awayTeamId": "team-away",
        "marketFamily": "TEAM_TOTAL",
        "subjectTeamId": "team-home",
        "marketRulesId": "MLB_TEAM_TOTAL_FULL_GAME_V1",
        "outcomes": outcomes,
        "sportsbookId": "synthetic-book",
        "sourceProvider": "SYNTHETIC_TEST_ONLY",
        "sourceQuoteId": "source-quote-a",
        "sourcePayloadSha256": SHA_A,
        "quoteOrigin": "SYNTHETIC_FIXTURE",
        "isSynthetic": True,
        "capturedAtUtc": "2024-04-01T10:00:00Z",
        "ingestedAtUtc": "2024-04-01T10:01:00Z",
        "scheduledStartUtc": None,
        "status": "RESEARCH_SHADOW_NOT_READY",
        "missingInputs": ["SCHEDULED_START_UTC"],
        "isParlay": False,
        "researchShadowOnly": True,
        "executionAllowed": False,
    }


def _candidate(forecast: dict, quote: dict) -> dict:
    validated_forecast = A.validate_game_forecast_export(forecast)
    validated_quote = A.validate_market_quote(quote)
    offered = validated_quote["outcomes"][0]
    win = 0.58
    push = 0.0
    lower = 0.54
    return {
        "schemaVersion": A.AISP_BET_CANDIDATE_V1,
        "candidateId": "candidate-game-a-home-over",
        "sport": "BASEBALL",
        "league": "MLB",
        "eventId": "game-a",
        "eventDate": "2024-04-01",
        "forecastId": validated_forecast["forecastId"],
        "forecastContentSha256": A.record_content_sha256(validated_forecast),
        "quoteId": validated_quote["quoteId"],
        "quoteContentSha256": A.record_content_sha256(validated_quote),
        "marketFamily": "TEAM_TOTAL",
        "subjectTeamId": "team-home",
        "selection": "OVER",
        "line": 4.5,
        "modelWinProbability": win,
        "modelPushProbability": push,
        "modelProbabilityLowerBound": lower,
        "offeredAmericanOdds": offered["americanOdds"],
        "offeredDecimalOdds": offered["decimalOdds"],
        "rawImpliedProbability": offered["rawImpliedProbability"],
        "breakEvenProbability": offered["breakEvenProbability"],
        "noVigProbability": offered["noVigProbability"],
        "fairDecimalOdds": offered["fairDecimalOdds"],
        "fairAmericanOdds": offered["fairAmericanOdds"],
        "modelFairDecimalOdds": 1.0 / win,
        "modelFairAmericanOdds": -100.0 * win / (1.0 - win),
        "edge": win - offered["noVigProbability"],
        "uncertaintyAdjustedEdge": lower - offered["noVigProbability"],
        "expectedValuePerUnit": win * (offered["decimalOdds"] - 1.0) - (1.0 - win - push),
        "status": "WATCH",
        "reasonCodes": ["EVENT_TIME_AUTHORITY_MISSING"],
        "explanations": [
            {
                "code": "UNCERTAINTY_ADJUSTED_EDGE",
                "summary": "Lower-bound edge remains positive",
                "detail": "Research evidence only; qualification policy is not authorized.",
            }
        ],
        "isParlay": False,
        "researchShadowOnly": True,
        "executionAllowed": False,
    }


def _bundle() -> dict:
    forecast = _forecast()
    quote = _quote()
    candidate = _candidate(forecast, quote)
    record = {
        "schemaVersion": A.AISP_DAILY_FORECAST_BUNDLE_V1,
        "bundleId": "PENDING",
        "sport": "BASEBALL",
        "league": "MLB",
        "slateDate": "2024-04-01",
        "generatedAtUtc": "2026-08-26T12:00:00Z",
        "forecastCutoffUtc": None,
        "status": "RESEARCH_SHADOW_NOT_READY",
        "readiness": {
            "isReady": False,
            "score": 80,
            "threshold": 85,
            "missingInputs": ["FORECAST_CUTOFF_UTC", "READY_CHILD_RECORDS"],
            "reasonCodes": ["TIMESTAMP_AUTHORITY_UNAVAILABLE"],
        },
        "forecasts": [forecast],
        "marketQuotes": [quote],
        "betCandidates": [candidate],
        "explanations": [
            {
                "code": "RESEARCH_SHADOW_BUNDLE",
                "summary": "No executable output",
                "detail": "The bundle is immutable evidence for a separate AISP consumer.",
            }
        ],
        "researchShadowOnly": True,
        "executionAllowed": False,
        "modelPromotionAllowed": False,
        "parlaysAllowed": False,
    }
    record["bundleId"] = A.derive_daily_forecast_bundle_id(record)
    return record


def test_forecast_accepts_honest_missing_times_and_rejects_2025_or_false_readiness():
    record = A.validate_game_forecast_export(_forecast())
    assert record["scheduledStartUtc"] is None
    assert record["forecastCutoffUtc"] is None
    assert record["status"] == "RESEARCH_SHADOW_NOT_READY"
    assert record["forecastId"].startswith(A.FORECAST_ID_PREFIX)

    arbitrary_id = _forecast()
    arbitrary_id["forecastId"] = "forecast-game-a-e10"
    with pytest.raises(A.AispExportContractError, match="forecastId"):
        A.validate_game_forecast_export(arbitrary_id)

    future = _forecast()
    future["eventDate"] = "2025-04-01"
    future["season"] = 2025
    with pytest.raises(A.AispExportContractError, match="2025"):
        A.validate_game_forecast_export(future)

    dishonest = _forecast()
    dishonest["readiness"]["missingInputs"] = []
    with pytest.raises(A.AispExportContractError, match="known missing"):
        A.validate_game_forecast_export(dishonest)


def test_team_total_quote_requires_subject_and_exact_no_vig_pricing_and_no_parlay():
    quote = A.validate_market_quote(_quote())
    assert quote["marketFamily"] == "TEAM_TOTAL"
    assert quote["subjectTeamId"] == "team-home"
    assert sum(row["noVigProbability"] for row in quote["outcomes"]) == 1.0

    no_subject = _quote()
    no_subject["subjectTeamId"] = None
    with pytest.raises(A.AispExportContractError, match="subjectTeamId"):
        A.validate_market_quote(no_subject)

    bad_price = _quote()
    bad_price["outcomes"][0]["fairDecimalOdds"] = 1.99
    with pytest.raises(A.AispExportContractError, match="pricing"):
        A.validate_market_quote(bad_price)

    parlay = _quote()
    parlay["isParlay"] = True
    with pytest.raises(A.AispExportContractError, match="parlay"):
        A.validate_market_quote(parlay)

    mislabeled = _quote()
    mislabeled["quoteOrigin"] = "OBSERVED_PROVIDER"
    with pytest.raises(A.AispExportContractError, match="origin"):
        A.validate_market_quote(mislabeled)


def test_candidate_recomputes_edge_uncertainty_edge_ev_and_binds_exact_parents():
    assert A.BET_STATUSES == {"NO_BET", "WATCH", "QUALIFIED_BET"}
    forecast, quote = _forecast(), _quote()
    candidate = _candidate(forecast, quote)
    validated = A.validate_bet_candidate(candidate)
    assert validated["edge"] == pytest.approx(0.08)
    assert validated["uncertaintyAdjustedEdge"] == pytest.approx(0.04)
    assert validated["breakEvenProbability"] == pytest.approx(
        1.0 / validated["offeredDecimalOdds"]
    )
    assert validated["modelFairDecimalOdds"] == pytest.approx(1.0 / 0.58)
    assert validated["executionAllowed"] is False

    bad_ev = copy.deepcopy(candidate)
    bad_ev["expectedValuePerUnit"] += 0.01
    with pytest.raises(A.AispExportContractError, match="EV"):
        A.validate_bet_candidate(bad_ev)

    bundle = _bundle()
    bundle["betCandidates"][0]["quoteContentSha256"] = SHA_B
    with pytest.raises(A.AispExportContractError, match="parent binding"):
        A.validate_daily_forecast_bundle(bundle)


def test_daily_bundle_is_strict_cross_bound_research_only_and_rejects_unknown_fields():
    record = A.validate_daily_forecast_bundle(_bundle())
    assert record["status"] == "RESEARCH_SHADOW_NOT_READY"
    assert record["bundleId"].startswith(A.BUNDLE_ID_PREFIX)
    assert record["parlaysAllowed"] is False
    assert record["modelPromotionAllowed"] is False
    assert record["generatedAtUtc"].startswith("2026-")  # metadata time, not event data

    stray = _bundle()
    stray["unexpected"] = True
    with pytest.raises(A.AispExportContractError, match="extra"):
        A.validate_daily_forecast_bundle(stray)


def test_bundle_writer_is_canonical_content_addressed_immutable_and_caller_rooted(tmp_path):
    external = tmp_path / "external-aisp-exchange"
    external.mkdir()
    first = A.write_daily_forecast_bundle(external, _bundle())
    assert first.created is True
    assert first.bundle_path == (
        external
        / A.BUNDLE_OBJECT_FAMILY
        / "sha256"
        / first.bundle_sha256
        / "bundle.json"
    )
    assert json.loads(first.bundle_path.read_text(encoding="utf-8"))["schemaVersion"] == A.AISP_DAILY_FORECAST_BUNDLE_V1
    assert {path.name for path in first.bundle_path.parent.iterdir()} == {
        "bundle.json",
        "consumer-import-fixture.json",
        "VALIDATION.md",
    }
    fixture = json.loads(first.consumer_fixture_path.read_text(encoding="utf-8"))
    assert fixture["bundleSha256"] == first.bundle_sha256
    assert fixture["bundleLogicalUri"].startswith("asp-model-exchange://")
    assert str(external) not in first.consumer_fixture_path.read_text(encoding="utf-8")
    assert first.validation_instructions_sha256 == fixture["validationInstructionsSha256"]

    retry = A.write_daily_forecast_bundle(external, _bundle())
    assert retry.created is False
    assert retry.bundle_sha256 == first.bundle_sha256
    assert A.verify_daily_forecast_bundle(external, first.bundle_sha256).record["bundleId"] == _bundle()["bundleId"]

    first.bundle_path.write_bytes(first.bundle_path.read_bytes() + b"\n")
    with pytest.raises(A.AispExportContractError, match="content address"):
        A.verify_daily_forecast_bundle(external, first.bundle_sha256)

    with pytest.raises(A.AispExportContractError, match="absolute"):
        A.write_daily_forecast_bundle(Path("relative-root"), _bundle())
