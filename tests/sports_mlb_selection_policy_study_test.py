from __future__ import annotations

from copy import deepcopy

import pytest

from server.sports_current_statcast.mlb_selection_policy_study import (
    BASE_GATES,
    CONTROL_MIN_ADJUSTED_EDGE,
    PolicyStudyError,
    build_study,
    qualifies,
    replay,
)


def row(*, decision_id: str = "d1", edge: float = 0.02, ev: float = 0.01) -> dict:
    return {
        "decisionId": decision_id,
        "eventId": "event-1",
        "eventStatus": "scheduled",
        "eventStart": "2026-09-02T00:00:00+00:00",
        "recommendedAt": "2026-09-01T20:00:00+00:00",
        "market": "MONEYLINE",
        "period": "FULL_GAME",
        "selection": "AAA ML",
        "line": None,
        "sportsbook": "book",
        "decimalOdds": 2.0,
        "readiness": 60.0,
        "recommendation": "QUALIFIED_BET" if edge >= CONTROL_MIN_ADJUSTED_EDGE and ev > 0 else "NO_BET",
        "position": None,
        "derived": {
            "decisionPregame": True,
            "forecastLegitimatePregame": True,
            "quoteAgeMinutes": 5.0,
            "priceCoverageState": "FRESH",
            "outcomeAvailable": True,
        },
        "evidenceSummary": {
            "gates_passed": sorted(BASE_GATES),
            "adjusted_probability": 0.51,
            "market_probability": 0.49,
            "adjusted_edge": edge,
            "adjusted_expected_value": ev,
            "lineup": {"state": "CONFIRMED_COMPLETE"},
            "starter_home": {"state": "PROBABLE_STABLE"},
            "starter_away": {"state": "PROBABLE_STABLE"},
        },
        "decisionPolicy": "AISP_PRACTICAL_PREGAME_POLICY_V2_1",
    }


def cohort() -> dict:
    return {
        "cohortSha256": "cd44ef70d6d4a5f3258cfad2cd6222accc5a39431d131184cf7b851ecced5785",
        "extractedAt": "2026-09-08T00:02:54+00:00",
        "source": {"readOnlyTransaction": True},
        "lineage": {"finalOotAccessed": False},
        "missingDataRequirements": {},
        "coverage": {},
    }


def handoff() -> dict:
    return {
        "handoffSha256": "v18-handoff",
        "forecasts": [{}] * 13,
        "promotionStatus": "NOT_PROMOTED",
        "researchShadowOnly": True,
        "wageringAuthority": False,
    }


def test_control_and_relaxed_arithmetic_boundaries() -> None:
    assert qualifies(row(edge=0.020), 0.020)
    assert not qualifies(row(edge=0.0199), 0.020)
    assert qualifies(row(edge=0.0175), 0.0175)
    assert not qualifies(row(edge=0.020, ev=0.0), 0.020)


def test_every_hard_gate_is_required() -> None:
    for gate in BASE_GATES:
        sample = row()
        sample["evidenceSummary"]["gates_passed"].remove(gate)
        assert not qualifies(sample, 0.015)


def test_temporal_leakage_stops_are_unconditional() -> None:
    after_cutoff = row()
    after_cutoff["derived"]["forecastLegitimatePregame"] = False
    assert not qualifies(after_cutoff, 0.015)
    after_start = row()
    after_start["derived"]["decisionPregame"] = False
    assert not qualifies(after_start, 0.015)


def test_replay_is_deterministic_and_deduplicates_a_selection() -> None:
    first = row(decision_id="a")
    second = row(decision_id="b")
    second["recommendedAt"] = "2026-09-01T21:00:00+00:00"
    assert replay([second, first], 0.020) == replay([first, second], 0.020)
    assert replay([first, second], 0.020)["distinctSelections"] == 1


def test_build_study_preserves_track_separation_and_authority() -> None:
    study, _ = build_study([row()], cohort(), handoff())
    assert study["trackSeparation"]["combinedPerformanceStatistics"] is False
    assert study["trackSeparation"]["v18ResearchShadow"]["forecastObjects"] == 13
    assert study["authority"]["officialPolicyChanged"] is False
    assert study["verdict"] == "MLB_STRICT_POLICY_RETAINED"


def test_control_replay_mismatch_fails_closed() -> None:
    sample = row()
    sample["recommendation"] = "NO_BET"
    with pytest.raises(PolicyStudyError, match="control replay"):
        build_study([sample], cohort(), handoff())


def test_source_identity_and_final_oot_are_immutable_gates() -> None:
    wrong = deepcopy(cohort())
    wrong["lineage"]["finalOotAccessed"] = True
    with pytest.raises(PolicyStudyError, match="Final OOT"):
        build_study([row()], wrong, handoff())
