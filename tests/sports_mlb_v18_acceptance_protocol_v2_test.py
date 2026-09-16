"""Focused tests for V2 formal-inference and Gen 1 cohort rules."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from server.sports_current_statcast import mlb_v18_acceptance_protocol_v2 as v2
from server.sports_current_statcast.mlb_bet_readiness_cohort import (
    EXPORT_SCHEMA_VERSION, CohortError, build_cohort, validate_export,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures/mlb_v18_acceptance_records.json"


def _records(count: int, *, mode: str = "neutral", one_week: bool = False) -> list[dict]:
    template = json.loads(FIXTURE.read_text(encoding="utf-8"))["records"][0]
    result = []
    for index in range(count):
        row = deepcopy(template)
        start = datetime(2026, 4, 1, 23, tzinfo=timezone.utc) + timedelta(
            days=index % 7 if one_week else index, minutes=index if one_week else 0
        )
        forecast = start-timedelta(hours=2)
        group = index // 2
        if mode in {"favorable", "adverse"}:
            home_wins = group % 5 < (3 if index % 2 == 0 else 2)
        else:
            home_wins = index % 2 == 0
        if mode == "favorable":
            p18, p1 = ((.60, .50) if index % 2 == 0 else (.40, .50))
        elif mode == "adverse":
            p18, p1 = ((.40, .60) if index % 2 == 0 else (.60, .40))
        else:
            p18 = p1 = .50
        row.update({"gameId": f"v2-game-{index}", "scheduledStart": start.isoformat()})
        row["v18"].update({"gameId": row["gameId"], "forecastId": f"v18-{index}",
                           "forecastAt": forecast.isoformat(), "evidenceCutoff": (forecast-timedelta(minutes=1)).isoformat(),
                           "lineupObservedAt": (forecast-timedelta(hours=1)).isoformat(),
                           "starterObservedAt": (forecast-timedelta(hours=1)).isoformat(),
                           "homeWinProbability": p18, "pathDigest": f"{index:064x}"})
        row["v18"]["inputReceipts"] = [{"source": "FIXTURE",
            "observedAt": (forecast-timedelta(hours=1)).isoformat(),
            "receivedAt": (forecast-timedelta(minutes=30)).isoformat(), "lineageSha256": "a"*64}]
        se = (p18*(1-p18)/5000) ** .5
        row["v18"].update({"monteCarloStandardError": se, "monteCarlo95HalfWidth": 1.96*se})
        row["gen1"].update({"gameId": row["gameId"], "forecastId": f"gen1-{index}",
                            "forecastAt": (forecast-timedelta(minutes=10)).isoformat(), "homeWinProbability": p1})
        row["settlement"].update({"gameId": row["gameId"], "settlementId": f"settlement-{index}",
                                  "settledAt": (start+timedelta(hours=4)).isoformat(),
                                  "homeRuns": 5 if home_wins else 2, "awayRuns": 2 if home_wins else 5})
        result.append(row)
    return result


def _payload(records: list[dict], look: int | None = None) -> dict:
    payload = {"schemaVersion": v2.SCHEMA_VERSION, "protocolSha256": v2.protocol_sha256(), "records": records}
    if look:
        payload["formalLook"] = {"lookNumber": look, "checkpointPairedGames": v2.FORMAL_LOOKS[look],
                                 "lookId": f"look-{look}", "immutable": True}
    return payload


def test_corrected_labels_and_unapproved_margin() -> None:
    assert "detectableTwoSided95AbsoluteDifference" not in v2.PROTOCOL["planningBasis"]
    assert v2.PROTOCOL["planningBasis"]["evidenceStatus"] == "ASSUMPTION_NOT_EMPIRICALLY_ESTIMATED"
    assert v2.PROTOCOL["noninferiorityMargin"]["disposition"] == "PROPOSED_NOT_APPROVED"
    assert v2.PROTOCOL["noninferiorityMargin"]["automaticAdvancementEnabled"] is False


def test_daily_and_too_few_blocks_remain_descriptive() -> None:
    daily = v2.evaluate(_payload(_records(250, mode="favorable")))
    assert daily["evidenceState"] == "CONTINUE_RESEARCH_SHADOW"
    assert daily["formalInference"]["status"] == "DESCRIPTIVE_ONLY_NO_FORMAL_LOOK"
    blocked = v2.evaluate(_payload(_records(250, mode="favorable", one_week=True), 1))
    assert blocked["formalInference"]["status"] == "INSUFFICIENT_TEMPORAL_BLOCKS"
    assert blocked["evidenceState"] == "CONTINUE_RESEARCH_SHADOW"


def test_fixed_alpha_formal_states_and_noninferiority_disabled() -> None:
    superior = v2.evaluate(_payload(_records(250, mode="favorable"), 1))
    assert superior["formalInference"]["primaryInterval"]["confidenceLevel"] == .975
    assert superior["formalInference"]["primaryInterval"]["blocks"] >= 8
    assert superior["evidenceState"] == "ADVANCE_AS_SUPERIOR"
    neutral = v2.evaluate(_payload(_records(250), 1))
    assert neutral["formalInference"]["decision"] == "NONINFERIORITY_BOUND_MET_MARGIN_NOT_APPROVED"
    assert neutral["evidenceState"] == "RETAIN_AS_DIVERSITY_CHALLENGER"
    adverse = v2.evaluate(_payload(_records(250, mode="adverse"), 1))
    assert adverse["evidenceState"] == "MATERIAL_REGRESSION"


def _decision(decision_id: str, *, price_age: float | None, outcome: bool, qualified: bool = False) -> dict:
    start = datetime(2026, 8, 2, 23, tzinfo=timezone.utc)
    recommended = start-timedelta(hours=2)
    quote = None if price_age is None else (recommended-timedelta(minutes=price_age)).isoformat()
    return {
        "experimentId": "experiment-1", "experimentVersion": 1, "experimentName": "control",
        "decisionPolicy": "policy-v1", "recommendationPolicyVersion": "recommend-v1",
        "stakingPolicyVersion": "stake-v1", "decisionId": decision_id, "eventId": "event-1",
        "eventStart": start.isoformat(), "eventStatus": "final", "phase": "FINAL_PREGAME",
        "market": "MONEYLINE", "period": "Full game", "selection": "HOME", "line": None,
        "sportsbook": None if price_age is None else "Book", "americanOdds": None if price_age is None else -110,
        "decimalOdds": None if price_age is None else 1.91, "quoteObservedAt": quote,
        "forecastId": "forecast-1", "forecastGeneratedAt": (recommended-timedelta(hours=1)).isoformat(),
        "forecastCutoff": recommended.isoformat(), "forecastVersion": "1", "modelVersionId": "model-1",
        "modelName": "Gen1", "modelVersion": "1", "modelIdentityChecksum": "a"*64,
        "recommendedAt": recommended.isoformat(), "modelProbability": .55, "noVigProbability": .52,
        "edge": .03, "expectedValue": .01, "readiness": 90, "uncertainty": .02,
        "recommendation": "QUALIFIED_BET" if qualified else "NO_BET",
        "recommendationReason": "Latest quote is stale" if price_age and price_age > 15 else "No complete same-sportsbook two-sided MONEYLINE quote",
        "qualificationReasons": ["Latest quote is stale"] if price_age and price_age > 15 else [],
        "evidence": {"lineup": "CONFIRMED", "starter_home": "CONFIRMED", "starter_away": "PROBABLE_STABLE"},
        "outcome": {"status": "FINAL", "homeScore": 5, "awayScore": 3} if outcome else None,
        "position": None,
    }


def _export(rows: list[dict]) -> dict:
    return {"schemaVersion": EXPORT_SCHEMA_VERSION, "extractedAt": "2026-09-08T00:00:00+00:00",
            "source": {"readOnlyTransaction": True, "aispRowsModified": 0, "providerCalls": 0}, "decisions": rows}


def test_cohort_preserves_multiple_decisions_and_price_states() -> None:
    payload = _export([_decision("d1", price_age=None, outcome=True),
                       _decision("d2", price_age=30, outcome=True),
                       _decision("d3", price_age=5, outcome=True, qualified=True)])
    first, second = build_cohort(payload), build_cohort(payload)
    assert first == second
    assert first["funnel"]["decisionEvaluations"] == 3
    assert first["funnel"]["distinctEvents"] == 1
    assert first["coverage"]["priceCoverage"] == {"FRESH": 1, "MISSING": 1, "STALE": 1}
    assert first["records"][0]["derived"]["counterfactualProfitabilityComputed"] is False


def test_export_contract_rejects_write_or_duplicate_identity() -> None:
    bad = _export([_decision("d1", price_age=5, outcome=True)])
    bad["source"]["aispRowsModified"] = 1
    with pytest.raises(CohortError):
        validate_export(bad)
    duplicate = _decision("d1", price_age=5, outcome=True)
    with pytest.raises(CohortError):
        validate_export(_export([duplicate, deepcopy(duplicate)]))
