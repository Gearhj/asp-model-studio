from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest

from server.sports_gold import game_market_mvp as M


SCHEDULED = "2024-09-20T23:00:00Z"
CAPTURED = "2024-09-20T20:00:00Z"
INGESTED = "2024-09-20T20:00:05Z"
DECISION_AT = "2024-09-20T20:01:00Z"
MODEL_SHA = "a" * 64


def _payload_sha(source_quote_id: str) -> str:
    return hashlib.sha256(source_quote_id.encode("utf-8")).hexdigest()


def _outcomes(family: M.MarketFamily, odds: int = 100) -> tuple[M.MarketOutcomeQuote, ...]:
    if family in {
        M.MarketFamily.FULL_GAME_MONEYLINE,
        M.MarketFamily.FIRST_FIVE_MONEYLINE,
    }:
        return (
            M.MarketOutcomeQuote("HOME", odds),
            M.MarketOutcomeQuote("AWAY", odds),
        )
    if family is M.MarketFamily.RUN_LINE_PLUS_MINUS_1_5:
        return (
            M.MarketOutcomeQuote("HOME", odds, -1.5),
            M.MarketOutcomeQuote("AWAY", odds, +1.5),
        )
    total = 4.5 if family is M.MarketFamily.TEAM_TOTAL else 8.5
    return (
        M.MarketOutcomeQuote("OVER", odds, total),
        M.MarketOutcomeQuote("UNDER", odds, total),
    )


def _quote(
    *,
    game_id: str = "game-a",
    family: M.MarketFamily = M.MarketFamily.FULL_GAME_MONEYLINE,
    source_quote_id: str | None = None,
    odds: int = 100,
    subject_team_id: str | None = None,
    quote_origin: M.QuoteOrigin = M.QuoteOrigin.SYNTHETIC_FIXTURE,
) -> M.MarketQuote:
    subject = (
        subject_team_id
        if family is M.MarketFamily.TEAM_TOTAL
        else None
    )
    if family is M.MarketFamily.TEAM_TOTAL and subject is None:
        subject = f"home-{game_id}"
    source_id = source_quote_id or f"source-{game_id}-{family.value}-{subject or 'game'}"
    return M.make_market_quote(
        canonical_game_id=game_id,
        game_date="2024-09-20",
        home_team_id=f"home-{game_id}",
        away_team_id=f"away-{game_id}",
        market_family=family,
        market_rules_id=f"FIXTURE_{family.value}_RULES_V1",
        outcomes=_outcomes(family, odds),
        sportsbook_id="fixture-book",
        source_provider="fixture-provider",
        source_quote_id=source_id,
        source_payload_sha256=_payload_sha(source_id),
        captured_at_utc=CAPTURED,
        ingested_at_utc=INGESTED,
        scheduled_start_utc=SCHEDULED,
        quote_origin=quote_origin,
        subject_team_id=subject,
    )


def _decision(
    quote: M.MarketQuote,
    *,
    policy: M.QualificationPolicy = M.UNSET_QUALIFICATION_POLICY,
    win_probability: float = 0.60,
    push_probability: float = 0.0,
) -> M.ShadowDecision:
    return M.make_shadow_decision(
        quote,
        selection=quote.outcomes[0].selection,
        model_id="fixture-model",
        model_artifact_sha256=MODEL_SHA,
        model_win_probability=win_probability,
        model_push_probability=push_probability,
        decision_at_utc=DECISION_AT,
        qualification_policy=policy,
    )


def test_contract_and_historical_coverage_fail_closed_exactly() -> None:
    contract = M.market_mvp_contract()
    assert contract["marketFamilies"] == [family.value for family in M.MARKET_FAMILY_ORDER]
    assert contract["marketFamilies"][-1] == "TEAM_TOTAL"
    assert contract["teamTotal"] == {
        "sportNeutralFamily": "TEAM_TOTAL",
        "subjectTeamIdRequired": True,
        "perGameSubjects": ["HOME_TEAM", "AWAY_TEAM"],
        "expectedRowsPerGame": 2,
    }
    assert contract["expectedBoardRowsPerGame"] == 7
    assert contract["quoteOrigins"] == ["OBSERVED_PROVIDER", "SYNTHETIC_FIXTURE"]
    assert contract["decisionStates"] == ["NO_BET", "WATCH", "QUALIFIED_BET"]
    assert contract["staking"] == {
        "kellyMultiplier": 0.25,
        "normalUnitFraction": 0.005,
        "maximumPositionFraction": 0.01,
        "maximumSameGameExposureFraction": 0.02,
        "maximumDailyExposureFraction": 0.05,
        "normalUnitIsMinimumStake": False,
        "bankrollAmount": None,
    }
    assert contract["qualificationPolicy"] == {
        "policyId": "UNSET",
        "configured": False,
        "minimumEdge": None,
        "minimumExpectedValue": None,
        "maximumQuoteAgeSeconds": None,
    }
    assert contract["unsetPolicyBehavior"] == {"state": "NO_BET", "stakeFraction": 0.0}
    assert contract["historicalBacktestEligible"] is False
    assert contract["fabricatedDefaultOddsAllowed"] is False
    assert contract["parlaysAllowed"] is False

    coverage = M.zero_historical_market_coverage()
    assert [row["periodId"] for row in coverage] == [
        "FOLD_1", "FOLD_2", "FOLD_3", "FOLD_4", "FOLD_5", "FINAL_HOLDOUT"
    ]
    assert [(row["startDate"], row["endDate"], row["goldMatchedGames"]) for row in coverage] == [
        ("2022-04-07", "2022-07-25", 1_403),
        ("2022-07-26", "2023-05-03", 1_406),
        ("2023-05-04", "2023-08-19", 1_382),
        ("2023-08-20", "2024-05-29", 1_393),
        ("2024-05-30", "2024-09-15", 1_396),
        ("2024-09-16", "2024-09-29", 183),
    ]
    for row in coverage:
        assert row["persistedQuoteCount"] == 0
        assert row["timestampedQuoteCount"] == 0
        assert row["twoSidedMarketCount"] == 0
        assert row["coveredGameCount"] == 0
        assert row["coveredGameRate"] == 0.0
        assert row["minimumQuoteTimestampUtc"] is None
        assert row["maximumQuoteTimestampUtc"] is None
        assert row["marketCoverage"] == {family.value: 0 for family in M.MARKET_FAMILY_ORDER}
        assert row["backtestEligible"] is False


def test_proportional_no_vig_and_push_aware_quarter_kelly_match_hand_math() -> None:
    result = M.two_sided_no_vig([-110, -110])
    assert result.raw_implied_probabilities == pytest.approx((11 / 21, 11 / 21))
    assert result.fair_probabilities == pytest.approx((0.5, 0.5))
    assert result.overround == pytest.approx(1 / 21)
    assert sum(M.proportional_no_vig([-110, -110])) == pytest.approx(1.0)

    assert M.full_kelly_fraction(2.0, 0.60) == pytest.approx(0.20)
    assert M.quarter_kelly_fraction(2.0, 0.60) == pytest.approx(0.05)
    # 0.54 win / 0.10 push / 0.36 loss becomes 0.60 / 0.40 on resolution.
    assert M.full_kelly_fraction(2.0, 0.54, 0.10) == pytest.approx(0.20)
    assert M.quarter_kelly_fraction(2.0, 0.54, 0.10) == pytest.approx(0.05)
    with pytest.raises(M.MarketContractError, match="exactly two"):
        M.proportional_no_vig([-110])


@pytest.mark.parametrize("family", list(M.MARKET_FAMILY_ORDER))
def test_each_exact_market_family_accepts_one_valid_two_sided_snapshot(
    family: M.MarketFamily,
) -> None:
    quote = _quote(family=family)
    assert quote.market_family is family
    assert tuple(outcome.selection for outcome in quote.outcomes) == tuple(
        M.market_mvp_contract()["twoSidedSelections"][family.value]
    )
    assert quote.record()["twoSided"] is True
    assert quote.record()["quoteOrigin"] == "SYNTHETIC_FIXTURE"
    assert quote.record()["syntheticQuote"] is True
    assert quote.subject_team_id == (
        "home-game-a" if family is M.MarketFamily.TEAM_TOTAL else None
    )
    assert quote.record()["shadowOnly"] is True
    assert quote.record()["executionAllowed"] is False
    assert len(quote.quote_sha256) == 64


def test_quote_contract_rejects_mixed_sides_lines_and_nonpregame_timestamps() -> None:
    common = dict(
        canonical_game_id="game-a",
        game_date="2024-09-20",
        home_team_id="home-a",
        away_team_id="away-a",
        market_rules_id="FIXTURE_RULES_V1",
        sportsbook_id="book",
        source_provider="provider",
        source_quote_id="quote-a",
        source_payload_sha256=_payload_sha("quote-a"),
        captured_at_utc=CAPTURED,
        ingested_at_utc=INGESTED,
        scheduled_start_utc=SCHEDULED,
        quote_origin=M.QuoteOrigin.SYNTHETIC_FIXTURE,
    )
    with pytest.raises(M.MarketContractError, match="two sides"):
        M.make_market_quote(
            **common,
            market_family=M.MarketFamily.FULL_GAME_MONEYLINE,
            outcomes=(M.MarketOutcomeQuote("HOME", -110), M.MarketOutcomeQuote("OVER", -110)),
        )
    with pytest.raises(M.MarketContractError, match="must not carry a line"):
        M.make_market_quote(
            **common,
            market_family=M.MarketFamily.FULL_GAME_MONEYLINE,
            outcomes=(M.MarketOutcomeQuote("HOME", -110, 1.5), M.MarketOutcomeQuote("AWAY", -110, -1.5)),
        )
    with pytest.raises(M.MarketContractError, match="same positive total line"):
        M.make_market_quote(
            **common,
            market_family=M.MarketFamily.FULL_GAME_TOTAL,
            outcomes=(M.MarketOutcomeQuote("OVER", -110, 8.5), M.MarketOutcomeQuote("UNDER", -110, 9.0)),
        )
    with pytest.raises(M.MarketContractError, match="requires subject_team_id"):
        M.make_market_quote(
            **common,
            market_family=M.MarketFamily.TEAM_TOTAL,
            outcomes=_outcomes(M.MarketFamily.TEAM_TOTAL),
        )
    with pytest.raises(M.MarketContractError, match="quote home or away team"):
        M.make_market_quote(
            **common,
            market_family=M.MarketFamily.TEAM_TOTAL,
            subject_team_id="unrelated-team",
            outcomes=_outcomes(M.MarketFamily.TEAM_TOTAL),
        )
    with pytest.raises(M.MarketContractError, match="only for TEAM_TOTAL"):
        M.make_market_quote(
            **common,
            market_family=M.MarketFamily.FULL_GAME_TOTAL,
            subject_team_id="home-a",
            outcomes=_outcomes(M.MarketFamily.FULL_GAME_TOTAL),
        )
    with pytest.raises(M.MarketContractError, match="unsupported market family"):
        M.make_market_quote(
            **common,
            market_family="PARLAY",
            outcomes=_outcomes(M.MarketFamily.FULL_GAME_MONEYLINE),
        )
    with pytest.raises(M.MarketContractError, match="complementary"):
        M.make_market_quote(
            **common,
            market_family=M.MarketFamily.RUN_LINE_PLUS_MINUS_1_5,
            outcomes=(M.MarketOutcomeQuote("HOME", -110, -1.5), M.MarketOutcomeQuote("AWAY", -110, -1.5)),
        )
    with pytest.raises(M.MarketContractError, match="before scheduled"):
        M.make_market_quote(
            **{**common, "captured_at_utc": SCHEDULED, "ingested_at_utc": SCHEDULED},
            market_family=M.MarketFamily.FULL_GAME_MONEYLINE,
            outcomes=_outcomes(M.MarketFamily.FULL_GAME_MONEYLINE),
        )
    with pytest.raises(M.MarketContractError, match="timezone"):
        M.make_market_quote(
            **{**common, "captured_at_utc": "2024-09-20T20:00:00"},
            market_family=M.MarketFamily.FULL_GAME_MONEYLINE,
            outcomes=_outcomes(M.MarketFamily.FULL_GAME_MONEYLINE),
        )


def test_unset_policy_forces_no_bet_zero_stake_and_content_addressed_append_only_records() -> None:
    quote = _quote(source_quote_id="immutable-source-id")
    pending = _decision(quote)
    assert pending.state is M.DecisionState.NO_BET
    assert pending.reason_codes == ("QUALIFICATION_POLICY_UNSET",)
    assert pending.stake_fraction == 0.0
    final = M.allocate_shadow_stakes([pending])[0]
    assert final.allocation_status == "FINAL"
    assert final.state is M.DecisionState.NO_BET
    assert final.stake_fraction == 0.0
    assert final.record()["bankrollAmount"] is None
    assert final.record()["executionAllowed"] is False

    ledger = M.ShadowMarketLedger(activated_at_utc="2024-09-20T19:00:00Z")
    assert ledger.append_quote(quote) is quote
    assert ledger.append_quote(quote) is quote
    assert ledger.quote_count == 1
    assert ledger.append_decision(final) is final
    assert ledger.append_decision(final) is final
    assert ledger.decision_count == 1
    assert ledger.quote(quote.quote_sha256) == quote
    assert ledger.decision(final.decision_sha256) == final

    canonical_quote = json.dumps(
        quote.content_record(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert hashlib.sha256(canonical_quote).hexdigest() == quote.quote_sha256

    conflicting = _quote(source_quote_id="immutable-source-id", odds=120)
    with pytest.raises(M.MarketContractError, match="cannot be changed in place"):
        ledger.append_quote(conflicting)
    with pytest.raises(M.MarketContractError, match="before activation"):
        M.ShadowMarketLedger(
            activated_at_utc="2024-09-20T21:00:00Z"
        ).append_quote(quote)
    with pytest.raises(M.MarketContractError, match="FINAL"):
        M.ShadowMarketLedger(activated_at_utc="2024-09-20T19:00:00Z").append_decision(pending)


def test_explicit_synthetic_policy_can_produce_all_three_board_states_without_defaults() -> None:
    qualified_policy = M.QualificationPolicy("SYNTHETIC-QUALIFY", 0.0, 0.0, 3_600.0)
    watch_policy = M.QualificationPolicy("SYNTHETIC-WATCH", 0.20, 0.20, 3_600.0)
    quotes = (
        _quote(family=M.MarketFamily.FULL_GAME_MONEYLINE),
        _quote(family=M.MarketFamily.FIRST_FIVE_MONEYLINE),
        _quote(family=M.MarketFamily.RUN_LINE_PLUS_MINUS_1_5),
    )
    pending = (
        _decision(quotes[0], policy=qualified_policy, win_probability=0.60),
        _decision(quotes[1], policy=watch_policy, win_probability=0.55),
        _decision(quotes[2]),
    )
    final = M.allocate_shadow_stakes(pending)
    board = M.build_shadow_board(
        canonical_game_id="game-a",
        game_date="2024-09-20",
        home_team_id="home-game-a",
        away_team_id="away-game-a",
        scheduled_start_utc=SCHEDULED,
        forecast_generated_at_utc="2024-09-20T19:55:00Z",
        quotes=quotes,
        decisions=final,
    )
    assert [row.market_family for row in board.rows] == [
        *M.MARKET_FAMILY_ORDER,
        M.MarketFamily.TEAM_TOTAL,
    ]
    assert [row.state for row in board.rows[:3]] == [
        M.DecisionState.QUALIFIED_BET,
        M.DecisionState.WATCH,
        M.DecisionState.NO_BET,
    ]
    assert all(row.state is M.DecisionState.NO_BET for row in board.rows[3:])
    assert board.rows[0].stake_fraction == pytest.approx(0.01)
    assert board.rows[0].stake_normal_units == pytest.approx(2.0)
    assert board.rows[1].stake_fraction == 0.0
    assert board.rows[2].reason_codes == ("QUALIFICATION_POLICY_UNSET",)
    assert board.rows[3].reason_codes == ("NO_PERSISTED_TWO_SIDED_QUOTE",)
    record = board.record()
    assert record["rowCount"] == 7
    assert record["allMarketSlotsPresentExactlyOnce"] is True
    assert record["forecastAvailable"] is True
    assert record["forecastGeneratedAtUtc"] == "2024-09-20T19:55:00.000000Z"
    assert record["parlaysAllowed"] is False
    assert record["shadowOnly"] is True
    assert record["executionAllowed"] is False


def test_team_total_has_two_subject_slots_and_explicit_quote_provenance() -> None:
    home_quote = _quote(
        family=M.MarketFamily.TEAM_TOTAL,
        subject_team_id="home-game-a",
        source_quote_id="synthetic-home-team-total",
    )
    away_quote = _quote(
        family=M.MarketFamily.TEAM_TOTAL,
        subject_team_id="away-game-a",
        source_quote_id="observed-away-team-total",
        quote_origin=M.QuoteOrigin.OBSERVED_PROVIDER,
    )
    final = M.allocate_shadow_stakes(
        [_decision(home_quote), _decision(away_quote)]
    )
    board = M.build_shadow_board(
        canonical_game_id="game-a",
        game_date="2024-09-20",
        home_team_id="home-game-a",
        away_team_id="away-game-a",
        scheduled_start_utc=SCHEDULED,
        quotes=(home_quote, away_quote),
        decisions=final,
    )
    team_total_rows = [
        row for row in board.rows if row.market_family is M.MarketFamily.TEAM_TOTAL
    ]
    assert [row.subject_team_id for row in team_total_rows] == [
        "home-game-a",
        "away-game-a",
    ]
    assert [row.quote_origin for row in team_total_rows] == [
        M.QuoteOrigin.SYNTHETIC_FIXTURE,
        M.QuoteOrigin.OBSERVED_PROVIDER,
    ]
    assert [row.record()["syntheticQuote"] for row in team_total_rows] == [
        True,
        False,
    ]
    assert all(row.state is M.DecisionState.NO_BET for row in team_total_rows)
    assert all(row.stake_fraction == 0.0 for row in team_total_rows)


def test_daily_zero_quote_board_has_complete_null_priced_no_bet_rows() -> None:
    boards = tuple(
        M.build_shadow_board(
            canonical_game_id=game_id,
            game_date="2024-09-20",
            home_team_id=f"home-{game_id}",
            away_team_id=f"away-{game_id}",
            scheduled_start_utc=SCHEDULED,
        )
        for game_id in ("game-a", "game-b")
    )
    daily = M.build_daily_shadow_board(
        board_date="2024-09-20",
        game_boards=boards,
    )
    record = daily.record()
    assert record["gameCount"] == 2
    assert record["marketFamilyCount"] == 6
    assert record["rowCount"] == 14
    assert record["stateCounts"] == {
        "NO_BET": 14,
        "WATCH": 0,
        "QUALIFIED_BET": 0,
    }
    assert record["forecastAvailableGameCount"] == 0
    assert record["sourceQuoteCount"] == 0
    assert record["syntheticQuoteCount"] == 0
    assert record["observedProviderQuoteCount"] == 0
    assert record["dailyExposureFraction"] == 0.0
    assert record["fabricatedDefaultOddsAllowed"] is False
    assert record["parlaysAllowed"] is False
    assert record["virtualPolicyCaps"] == {
        "kellyMultiplier": 0.25,
        "normalUnitFraction": 0.005,
        "maximumPositionFraction": 0.01,
        "maximumSameGameExposureFraction": 0.02,
        "maximumDailyExposureFraction": 0.05,
        "bankrollAmount": None,
    }
    rows = [row for game in record["games"] for row in game["rows"]]
    assert all(row["state"] == "NO_BET" for row in rows)
    assert all(row["americanOdds"] is None for row in rows)
    assert all(row["line"] is None for row in rows)
    assert all(row["noVigProbability"] is None for row in rows)
    assert all(row["stakeFraction"] == 0.0 for row in rows)
    assert [
        row["subjectTeamId"]
        for row in record["games"][0]["rows"]
        if row["marketFamily"] == "TEAM_TOTAL"
    ] == ["home-game-a", "away-game-a"]


def test_quarter_kelly_allocation_enforces_position_same_game_and_daily_caps() -> None:
    policy = M.QualificationPolicy("SYNTHETIC-CAPS", 0.0, 0.0, 3_600.0)
    quote_specs = [
        ("game-a", M.MarketFamily.FULL_GAME_MONEYLINE),
        ("game-a", M.MarketFamily.FIRST_FIVE_MONEYLINE),
        ("game-a", M.MarketFamily.RUN_LINE_PLUS_MINUS_1_5),
        ("game-b", M.MarketFamily.FULL_GAME_MONEYLINE),
        ("game-c", M.MarketFamily.FULL_GAME_MONEYLINE),
        ("game-d", M.MarketFamily.FULL_GAME_MONEYLINE),
        ("game-e", M.MarketFamily.FULL_GAME_MONEYLINE),
    ]
    quotes = tuple(_quote(game_id=game, family=family) for game, family in quote_specs)
    pending = tuple(_decision(quote, policy=policy, win_probability=0.60) for quote in quotes)
    final = M.allocate_shadow_stakes(pending)

    assert [item.stake_fraction for item in final] == pytest.approx(
        [0.01, 0.01, 0.0, 0.01, 0.01, 0.01, 0.0]
    )
    assert sum(item.stake_fraction for item in final) == pytest.approx(0.05)
    assert sum(item.stake_fraction for item in final if item.canonical_game_id == "game-a") == pytest.approx(0.02)
    assert all(item.stake_fraction <= 0.01 for item in final)
    assert all(item.stake_normal_units <= 2.0 for item in final)
    assert final[2].state is M.DecisionState.NO_BET
    assert "EXPOSURE_CAP_REACHED" in final[2].reason_codes
    assert final[-1].state is M.DecisionState.NO_BET
    assert "EXPOSURE_CAP_REACHED" in final[-1].reason_codes
    assert all(
        "STAKE_CAPPED" in item.reason_codes
        for item in final
        if item.state is M.DecisionState.QUALIFIED_BET
    )

    boards = tuple(
        M.build_shadow_board(
            canonical_game_id=game_id,
            game_date="2024-09-20",
            home_team_id=f"home-{game_id}",
            away_team_id=f"away-{game_id}",
            scheduled_start_utc=SCHEDULED,
            forecast_generated_at_utc="2024-09-20T19:55:00Z",
            quotes=quotes,
            decisions=final,
        )
        for game_id in ("game-a", "game-b", "game-c", "game-d", "game-e")
    )
    daily = M.build_daily_shadow_board(
        board_date="2024-09-20",
        game_boards=boards,
    ).record()
    assert daily["dailyExposureFraction"] == pytest.approx(0.05)
    assert daily["stateCounts"]["QUALIFIED_BET"] == 5
    assert daily["syntheticQuoteCount"] == len(quotes)
    assert daily["observedProviderQuoteCount"] == 0
    assert all(
        game["sameGameExposureFraction"] <= 0.02
        for game in daily["games"]
    )


def test_decision_rejects_post_start_or_pre_ingestion_scoring() -> None:
    quote = _quote()
    with pytest.raises(M.MarketContractError, match="must not precede quote ingestion"):
        M.make_shadow_decision(
            quote,
            selection="HOME",
            model_id="fixture-model",
            model_artifact_sha256=MODEL_SHA,
            model_win_probability=0.60,
            decision_at_utc=CAPTURED,
        )
    with pytest.raises(M.MarketContractError, match="before scheduled start"):
        M.make_shadow_decision(
            quote,
            selection="HOME",
            model_id="fixture-model",
            model_artifact_sha256=MODEL_SHA,
            model_win_probability=0.60,
            decision_at_utc=SCHEDULED,
        )


def test_ledger_rejects_decision_forged_against_another_quote_identity() -> None:
    quote = _quote()
    final = M.allocate_shadow_stakes([_decision(quote)])[0]
    forged = replace(final, canonical_game_id="different-game")
    ledger = M.ShadowMarketLedger(activated_at_utc="2024-09-20T19:00:00Z")
    ledger.append_quote(quote)
    with pytest.raises(M.MarketContractError, match="decision does not match"):
        ledger.append_decision(forged)
