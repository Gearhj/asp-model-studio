"""Pure Phase 7B6 SHADOW market primitives.

The module deliberately has no provider, filesystem, database, CLI, or model-fitting
integration.  It defines the smallest honest boundary for prospectively captured,
two-sided market quotes and research-only decisions.  The audited historical corpus
contains no governed sportsbook quotes, so the fixed historical inventory below fails
closed at zero coverage.  It must never be interpreted as a backtest.

Qualification thresholds are intentionally unset.  The default policy therefore emits
``NO_BET`` with a zero stake.  A caller may construct an explicitly versioned policy in
synthetic or future prospective work, but this module supplies no threshold defaults.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any


SCHEMA_VERSION = "MLB_GOLD_GAME_MARKET_MVP_V2"
QUOTE_SCHEMA_VERSION = "MLB_SHADOW_TWO_SIDED_MARKET_QUOTE_V2"
DECISION_SCHEMA_VERSION = "MLB_SHADOW_MARKET_DECISION_V2"
BOARD_SCHEMA_VERSION = "MLB_SHADOW_MARKET_BOARD_V2"
DAILY_BOARD_SCHEMA_VERSION = "MLB_SHADOW_DAILY_MARKET_BOARD_V1"
HISTORICAL_COVERAGE_SCHEMA_VERSION = "MLB_SHADOW_HISTORICAL_MARKET_COVERAGE_V2"

NORMAL_UNIT_FRACTION = 0.005
MAX_POSITION_FRACTION = 0.01
MAX_SAME_GAME_EXPOSURE_FRACTION = 0.02
MAX_DAILY_EXPOSURE_FRACTION = 0.05
KELLY_MULTIPLIER = 0.25


class MarketContractError(ValueError):
    """Raised when a quote, decision, or board violates the fixed SHADOW contract."""


class MarketFamily(str, Enum):
    FULL_GAME_MONEYLINE = "FULL_GAME_MONEYLINE"
    FIRST_FIVE_MONEYLINE = "FIRST_FIVE_MONEYLINE"
    RUN_LINE_PLUS_MINUS_1_5 = "RUN_LINE_PLUS_MINUS_1_5"
    FULL_GAME_TOTAL = "FULL_GAME_TOTAL"
    FIRST_FIVE_TOTAL = "FIRST_FIVE_TOTAL"
    TEAM_TOTAL = "TEAM_TOTAL"


class QuoteOrigin(str, Enum):
    OBSERVED_PROVIDER = "OBSERVED_PROVIDER"
    SYNTHETIC_FIXTURE = "SYNTHETIC_FIXTURE"


class DecisionState(str, Enum):
    NO_BET = "NO_BET"
    WATCH = "WATCH"
    QUALIFIED_BET = "QUALIFIED_BET"


MARKET_FAMILY_ORDER: tuple[MarketFamily, ...] = tuple(MarketFamily)
DECISION_STATE_ORDER: tuple[DecisionState, ...] = tuple(DecisionState)

_SELECTION_ORDER: Mapping[MarketFamily, tuple[str, str]] = {
    MarketFamily.FULL_GAME_MONEYLINE: ("HOME", "AWAY"),
    MarketFamily.FIRST_FIVE_MONEYLINE: ("HOME", "AWAY"),
    MarketFamily.RUN_LINE_PLUS_MINUS_1_5: ("HOME", "AWAY"),
    MarketFamily.FULL_GAME_TOTAL: ("OVER", "UNDER"),
    MarketFamily.FIRST_FIVE_TOTAL: ("OVER", "UNDER"),
    MarketFamily.TEAM_TOTAL: ("OVER", "UNDER"),
}


@dataclass(frozen=True)
class HistoricalEvaluationPeriod:
    period_id: str
    start_date: str
    end_date: str
    pa_rows: int
    gold_matched_games: int
    active_dates: int


HISTORICAL_EVALUATION_PERIODS: tuple[HistoricalEvaluationPeriod, ...] = (
    HistoricalEvaluationPeriod("FOLD_1", "2022-04-07", "2022-07-25", 105_063, 1_403, 107),
    HistoricalEvaluationPeriod("FOLD_2", "2022-07-26", "2023-05-03", 105_289, 1_406, 107),
    HistoricalEvaluationPeriod("FOLD_3", "2023-05-04", "2023-08-19", 104_339, 1_382, 104),
    HistoricalEvaluationPeriod("FOLD_4", "2023-08-20", "2024-05-29", 105_172, 1_393, 108),
    HistoricalEvaluationPeriod("FOLD_5", "2024-05-30", "2024-09-15", 104_662, 1_396, 105),
    HistoricalEvaluationPeriod("FINAL_HOLDOUT", "2024-09-16", "2024-09-29", 13_766, 183, 14),
)


def _canonical_sha256(record: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_text(value: Any, name: str) -> str:
    parsed = str(value).strip()
    if not parsed:
        raise MarketContractError(f"{name} must be non-empty")
    return parsed


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise MarketContractError(f"{name} must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise MarketContractError(f"{name} must be a finite number")
    return parsed


def _sha256(value: Any, name: str) -> str:
    parsed = _required_text(value, name).lower()
    if len(parsed) != 64 or any(character not in "0123456789abcdef" for character in parsed):
        raise MarketContractError(f"{name} must be a lowercase SHA-256 hex digest")
    return parsed


def _utc_iso(value: str | datetime, name: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = _required_text(value, name)
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise MarketContractError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MarketContractError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _iso_date(value: Any, name: str) -> str:
    raw = _required_text(value, name)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise MarketContractError(f"{name} must be an ISO-8601 calendar date") from exc
    return parsed.isoformat()


def _as_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _market_family(value: MarketFamily | str) -> MarketFamily:
    try:
        return value if isinstance(value, MarketFamily) else MarketFamily(str(value))
    except ValueError as exc:
        raise MarketContractError(f"unsupported market family: {value!r}") from exc


def _quote_origin(value: QuoteOrigin | str) -> QuoteOrigin:
    try:
        return value if isinstance(value, QuoteOrigin) else QuoteOrigin(str(value))
    except ValueError as exc:
        raise MarketContractError(f"unsupported quote origin: {value!r}") from exc


def american_to_decimal(american_odds: int) -> float:
    """Convert valid American odds to decimal odds."""

    if isinstance(american_odds, bool) or not isinstance(american_odds, int):
        raise MarketContractError("american_odds must be an integer")
    if american_odds >= 100:
        return 1.0 + american_odds / 100.0
    if american_odds <= -100:
        return 1.0 + 100.0 / abs(american_odds)
    raise MarketContractError("american_odds must be <= -100 or >= +100")


def american_implied_probability(american_odds: int) -> float:
    """Return the raw implied probability for valid American odds."""

    decimal_odds = american_to_decimal(american_odds)
    return 1.0 / decimal_odds


@dataclass(frozen=True)
class NoVigResult:
    raw_implied_probabilities: tuple[float, float]
    fair_probabilities: tuple[float, float]
    overround: float

    def record(self) -> dict[str, Any]:
        return {
            "method": "PROPORTIONAL_TWO_SIDED_NO_VIG",
            "rawImpliedProbabilities": list(self.raw_implied_probabilities),
            "fairProbabilities": list(self.fair_probabilities),
            "overround": self.overround,
        }


def two_sided_no_vig(american_odds: Sequence[int]) -> NoVigResult:
    """Remove vig proportionally from exactly two prices from one quote snapshot."""

    if len(american_odds) != 2:
        raise MarketContractError("two-sided no-vig conversion requires exactly two prices")
    raw = tuple(american_implied_probability(value) for value in american_odds)
    denominator = sum(raw)
    if not math.isfinite(denominator) or denominator <= 0.0:
        raise MarketContractError("two-sided implied-probability sum must be positive")
    fair = (raw[0] / denominator, raw[1] / denominator)
    return NoVigResult(raw, fair, denominator - 1.0)


def proportional_no_vig(american_odds: Sequence[int]) -> tuple[float, float]:
    """Return only the two proportional no-vig probabilities."""

    return two_sided_no_vig(american_odds).fair_probabilities


def full_kelly_fraction(
    decimal_odds: float,
    win_probability: float,
    push_probability: float = 0.0,
) -> float:
    """Return nonnegative full Kelly, conditioning on resolution when pushes exist."""

    decimal = _finite(decimal_odds, "decimal_odds")
    win = _finite(win_probability, "win_probability")
    push = _finite(push_probability, "push_probability")
    if decimal <= 1.0:
        raise MarketContractError("decimal_odds must exceed 1")
    if not 0.0 <= win <= 1.0 or not 0.0 <= push <= 1.0 or win + push > 1.0:
        raise MarketContractError("win and push probabilities must define a valid outcome")
    resolved = 1.0 - push
    if resolved <= 0.0:
        raise MarketContractError("Kelly sizing requires positive resolved probability mass")
    conditional_win = win / resolved
    conditional_loss = (1.0 - win - push) / resolved
    profit_multiple = decimal - 1.0
    fraction = (profit_multiple * conditional_win - conditional_loss) / profit_multiple
    return min(1.0, max(0.0, fraction))


def quarter_kelly_fraction(
    decimal_odds: float,
    win_probability: float,
    push_probability: float = 0.0,
) -> float:
    """Return exactly one quarter of nonnegative full Kelly."""

    return KELLY_MULTIPLIER * full_kelly_fraction(
        decimal_odds, win_probability, push_probability
    )


@dataclass(frozen=True)
class MarketOutcomeQuote:
    selection: str
    american_odds: int
    line: float | None = None

    def __post_init__(self) -> None:
        selection = _required_text(self.selection, "selection").upper()
        american_to_decimal(self.american_odds)
        line = None if self.line is None else _finite(self.line, "line")
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "line", line)

    @property
    def decimal_odds(self) -> float:
        return american_to_decimal(self.american_odds)

    @property
    def raw_implied_probability(self) -> float:
        return american_implied_probability(self.american_odds)

    def record(self) -> dict[str, Any]:
        return {
            "selection": self.selection,
            "line": self.line,
            "americanOdds": self.american_odds,
            "decimalOdds": self.decimal_odds,
            "rawImpliedProbability": self.raw_implied_probability,
        }


@dataclass(frozen=True)
class MarketQuote:
    canonical_game_id: str
    game_date: str
    home_team_id: str
    away_team_id: str
    market_family: MarketFamily | str
    market_rules_id: str
    outcomes: tuple[MarketOutcomeQuote, ...]
    sportsbook_id: str
    source_provider: str
    source_quote_id: str
    source_payload_sha256: str
    captured_at_utc: str | datetime
    ingested_at_utc: str | datetime
    scheduled_start_utc: str | datetime
    quote_origin: QuoteOrigin | str
    subject_team_id: str | None = None
    quote_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        game_id = _required_text(self.canonical_game_id, "canonical_game_id")
        game_date = _iso_date(self.game_date, "game_date")
        home = _required_text(self.home_team_id, "home_team_id")
        away = _required_text(self.away_team_id, "away_team_id")
        if home == away:
            raise MarketContractError("home and away teams must differ")
        family = _market_family(self.market_family)
        origin = _quote_origin(self.quote_origin)
        subject = (
            None
            if self.subject_team_id is None
            else _required_text(self.subject_team_id, "subject_team_id")
        )
        if family is MarketFamily.TEAM_TOTAL:
            if subject is None:
                raise MarketContractError("TEAM_TOTAL requires subject_team_id")
            if subject not in {home, away}:
                raise MarketContractError(
                    "TEAM_TOTAL subject_team_id must be the quote home or away team"
                )
        elif subject is not None:
            raise MarketContractError(
                "subject_team_id is permitted only for TEAM_TOTAL"
            )
        market_rules_id = _required_text(self.market_rules_id, "market_rules_id")
        book = _required_text(self.sportsbook_id, "sportsbook_id")
        provider = _required_text(self.source_provider, "source_provider")
        source_quote_id = _required_text(self.source_quote_id, "source_quote_id")
        payload_sha = _sha256(self.source_payload_sha256, "source_payload_sha256")
        captured = _utc_iso(self.captured_at_utc, "captured_at_utc")
        ingested = _utc_iso(self.ingested_at_utc, "ingested_at_utc")
        scheduled = _utc_iso(self.scheduled_start_utc, "scheduled_start_utc")
        if _as_datetime(ingested) < _as_datetime(captured):
            raise MarketContractError("ingested_at_utc must be at or after captured_at_utc")
        if _as_datetime(captured) >= _as_datetime(scheduled):
            raise MarketContractError("captured_at_utc must be before scheduled_start_utc")
        if _as_datetime(ingested) >= _as_datetime(scheduled):
            raise MarketContractError("ingested_at_utc must be before scheduled_start_utc")

        if len(self.outcomes) != 2 or not all(
            isinstance(item, MarketOutcomeQuote) for item in self.outcomes
        ):
            raise MarketContractError("a quote must contain exactly two MarketOutcomeQuote values")
        by_selection = {item.selection: item for item in self.outcomes}
        expected = _SELECTION_ORDER[family]
        if set(by_selection) != set(expected) or len(by_selection) != 2:
            raise MarketContractError(
                f"{family.value} requires exactly the two sides {list(expected)}"
            )
        outcomes = tuple(by_selection[selection] for selection in expected)
        self._validate_lines(family, outcomes)

        object.__setattr__(self, "canonical_game_id", game_id)
        object.__setattr__(self, "game_date", game_date)
        object.__setattr__(self, "home_team_id", home)
        object.__setattr__(self, "away_team_id", away)
        object.__setattr__(self, "market_family", family)
        object.__setattr__(self, "quote_origin", origin)
        object.__setattr__(self, "subject_team_id", subject)
        object.__setattr__(self, "market_rules_id", market_rules_id)
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "sportsbook_id", book)
        object.__setattr__(self, "source_provider", provider)
        object.__setattr__(self, "source_quote_id", source_quote_id)
        object.__setattr__(self, "source_payload_sha256", payload_sha)
        object.__setattr__(self, "captured_at_utc", captured)
        object.__setattr__(self, "ingested_at_utc", ingested)
        object.__setattr__(self, "scheduled_start_utc", scheduled)
        object.__setattr__(self, "quote_sha256", _canonical_sha256(self.content_record()))

    @staticmethod
    def _validate_lines(
        family: MarketFamily,
        outcomes: tuple[MarketOutcomeQuote, MarketOutcomeQuote],
    ) -> None:
        if family in {
            MarketFamily.FULL_GAME_MONEYLINE,
            MarketFamily.FIRST_FIVE_MONEYLINE,
        }:
            if any(item.line is not None for item in outcomes):
                raise MarketContractError("moneyline outcomes must not carry a line")
            return
        if family is MarketFamily.RUN_LINE_PLUS_MINUS_1_5:
            lines = [item.line for item in outcomes]
            if any(line is None for line in lines):
                raise MarketContractError("run-line outcomes require both line values")
            parsed = [float(line) for line in lines if line is not None]
            if not all(math.isclose(abs(line), 1.5, abs_tol=1e-12) for line in parsed):
                raise MarketContractError("run lines must be exactly +1.5 and -1.5")
            if not math.isclose(sum(parsed), 0.0, abs_tol=1e-12):
                raise MarketContractError("run-line sides must be complementary")
            return
        lines = [item.line for item in outcomes]
        if any(line is None for line in lines):
            raise MarketContractError("total outcomes require a line value")
        parsed = [float(line) for line in lines if line is not None]
        if parsed[0] <= 0.0 or not math.isclose(parsed[0], parsed[1], abs_tol=1e-12):
            raise MarketContractError("OVER and UNDER must use the same positive total line")

    @property
    def source_identity(self) -> tuple[str, str, str]:
        return self.source_provider, self.sportsbook_id, self.source_quote_id

    def content_record(self) -> dict[str, Any]:
        return {
            "schemaVersion": QUOTE_SCHEMA_VERSION,
            "recordMode": "PROSPECTIVE_SHADOW_ONLY",
            "canonicalGameId": self.canonical_game_id,
            "gameDate": self.game_date,
            "homeTeamId": self.home_team_id,
            "awayTeamId": self.away_team_id,
            "marketFamily": self.market_family.value,
            "subjectTeamId": self.subject_team_id,
            "marketRulesId": self.market_rules_id,
            "sportsbookId": self.sportsbook_id,
            "sourceProvider": self.source_provider,
            "sourceQuoteId": self.source_quote_id,
            "sourcePayloadSha256": self.source_payload_sha256,
            "quoteOrigin": self.quote_origin.value,
            "syntheticQuote": self.quote_origin is QuoteOrigin.SYNTHETIC_FIXTURE,
            "capturedAtUtc": self.captured_at_utc,
            "ingestedAtUtc": self.ingested_at_utc,
            "scheduledStartUtc": self.scheduled_start_utc,
            "twoSided": True,
            "outcomes": [outcome.record() for outcome in self.outcomes],
            "shadowOnly": True,
            "executionAllowed": False,
        }

    def record(self) -> dict[str, Any]:
        return {**self.content_record(), "quoteSha256": self.quote_sha256}


def make_market_quote(
    *,
    canonical_game_id: str,
    game_date: str,
    home_team_id: str,
    away_team_id: str,
    market_family: MarketFamily | str,
    market_rules_id: str,
    outcomes: Sequence[MarketOutcomeQuote],
    sportsbook_id: str,
    source_provider: str,
    source_quote_id: str,
    source_payload_sha256: str,
    captured_at_utc: str | datetime,
    ingested_at_utc: str | datetime,
    scheduled_start_utc: str | datetime,
    quote_origin: QuoteOrigin | str,
    subject_team_id: str | None = None,
) -> MarketQuote:
    """Build and validate one exact, two-sided, prospective SHADOW quote."""

    return MarketQuote(
        canonical_game_id=canonical_game_id,
        game_date=game_date,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        market_family=market_family,
        market_rules_id=market_rules_id,
        outcomes=tuple(outcomes),
        sportsbook_id=sportsbook_id,
        source_provider=source_provider,
        source_quote_id=source_quote_id,
        source_payload_sha256=source_payload_sha256,
        captured_at_utc=captured_at_utc,
        ingested_at_utc=ingested_at_utc,
        scheduled_start_utc=scheduled_start_utc,
        quote_origin=quote_origin,
        subject_team_id=subject_team_id,
    )


@dataclass(frozen=True)
class QualificationPolicy:
    """Explicit future status policy; all thresholds are unset by default."""

    policy_id: str = "UNSET"
    minimum_edge: float | None = None
    minimum_expected_value: float | None = None
    maximum_quote_age_seconds: float | None = None

    def __post_init__(self) -> None:
        policy_id = _required_text(self.policy_id, "policy_id")
        object.__setattr__(self, "policy_id", policy_id)
        for name in (
            "minimum_edge",
            "minimum_expected_value",
            "maximum_quote_age_seconds",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            parsed = _finite(value, name)
            if parsed < 0.0:
                raise MarketContractError(f"{name} must be nonnegative when configured")
            if name == "maximum_quote_age_seconds" and parsed == 0.0:
                raise MarketContractError("maximum_quote_age_seconds must be positive")
            object.__setattr__(self, name, parsed)

    @property
    def configured(self) -> bool:
        return (
            self.policy_id != "UNSET"
            and self.minimum_edge is not None
            and self.minimum_expected_value is not None
            and self.maximum_quote_age_seconds is not None
        )

    def record(self) -> dict[str, Any]:
        return {
            "policyId": self.policy_id,
            "configured": self.configured,
            "minimumEdge": self.minimum_edge,
            "minimumExpectedValue": self.minimum_expected_value,
            "maximumQuoteAgeSeconds": self.maximum_quote_age_seconds,
        }


UNSET_QUALIFICATION_POLICY = QualificationPolicy()


@dataclass(frozen=True)
class ShadowDecision:
    quote_sha256: str
    canonical_game_id: str
    game_date: str
    market_family: MarketFamily
    subject_team_id: str | None
    market_rules_id: str
    selection: str
    model_id: str
    model_artifact_sha256: str
    decision_at_utc: str
    scheduled_start_utc: str
    sportsbook_id: str
    line: float | None
    american_odds: int
    decimal_odds: float
    raw_implied_probability: float
    no_vig_probability: float
    model_win_probability: float
    model_push_probability: float
    model_conditional_win_probability: float
    edge: float
    expected_value_per_unit: float
    quote_age_seconds: float
    full_kelly_fraction: float
    quarter_kelly_fraction: float
    qualification_policy: QualificationPolicy
    state: DecisionState
    reason_codes: tuple[str, ...]
    allocation_status: str = "PENDING"
    stake_fraction: float = 0.0
    stake_normal_units: float = 0.0
    decision_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        if self.allocation_status not in {"PENDING", "FINAL"}:
            raise MarketContractError("allocation_status must be PENDING or FINAL")
        if self.stake_fraction < 0.0 or self.stake_fraction > MAX_POSITION_FRACTION + 1e-15:
            raise MarketContractError("stake_fraction violates the per-position cap")
        if self.state is not DecisionState.QUALIFIED_BET and self.stake_fraction != 0.0:
            raise MarketContractError("only QUALIFIED_BET may carry a nonzero stake")
        object.__setattr__(self, "decision_sha256", _canonical_sha256(self.content_record()))

    @property
    def slate_date(self) -> str:
        return self.game_date

    def content_record(self) -> dict[str, Any]:
        return {
            "schemaVersion": DECISION_SCHEMA_VERSION,
            "recordMode": "PROSPECTIVE_SHADOW_ONLY",
            "quoteSha256": self.quote_sha256,
            "canonicalGameId": self.canonical_game_id,
            "gameDate": self.game_date,
            "marketFamily": self.market_family.value,
            "subjectTeamId": self.subject_team_id,
            "marketRulesId": self.market_rules_id,
            "selection": self.selection,
            "modelId": self.model_id,
            "modelArtifactSha256": self.model_artifact_sha256,
            "decisionAtUtc": self.decision_at_utc,
            "scheduledStartUtc": self.scheduled_start_utc,
            "sportsbookId": self.sportsbook_id,
            "line": self.line,
            "americanOdds": self.american_odds,
            "decimalOdds": self.decimal_odds,
            "rawImpliedProbability": self.raw_implied_probability,
            "noVigProbability": self.no_vig_probability,
            "modelWinProbability": self.model_win_probability,
            "modelPushProbability": self.model_push_probability,
            "modelConditionalWinProbability": self.model_conditional_win_probability,
            "edge": self.edge,
            "expectedValuePerUnit": self.expected_value_per_unit,
            "quoteAgeSeconds": self.quote_age_seconds,
            "fullKellyFraction": self.full_kelly_fraction,
            "quarterKellyFraction": self.quarter_kelly_fraction,
            "normalUnitFraction": NORMAL_UNIT_FRACTION,
            "maximumPositionFraction": MAX_POSITION_FRACTION,
            "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
            "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
            "qualificationPolicy": self.qualification_policy.record(),
            "state": self.state.value,
            "reasonCodes": list(self.reason_codes),
            "allocationStatus": self.allocation_status,
            "stakeFraction": self.stake_fraction,
            "stakeNormalUnits": self.stake_normal_units,
            "stakeAmount": None,
            "bankrollAmount": None,
            "shadowOnly": True,
            "executionAllowed": False,
        }

    def record(self) -> dict[str, Any]:
        return {**self.content_record(), "decisionSha256": self.decision_sha256}


def make_shadow_decision(
    quote: MarketQuote,
    *,
    selection: str,
    model_id: str,
    model_artifact_sha256: str,
    model_win_probability: float,
    model_push_probability: float = 0.0,
    decision_at_utc: str | datetime,
    qualification_policy: QualificationPolicy = UNSET_QUALIFICATION_POLICY,
) -> ShadowDecision:
    """Evaluate one side, deriving status rather than accepting it from a caller."""

    if not isinstance(quote, MarketQuote):
        raise TypeError("quote must be a MarketQuote")
    chosen = _required_text(selection, "selection").upper()
    by_selection = {outcome.selection: outcome for outcome in quote.outcomes}
    if chosen not in by_selection:
        raise MarketContractError("selection is not one of the exact quote outcomes")
    model = _required_text(model_id, "model_id")
    artifact_sha = _sha256(model_artifact_sha256, "model_artifact_sha256")
    win = _finite(model_win_probability, "model_win_probability")
    push = _finite(model_push_probability, "model_push_probability")
    if not 0.0 <= win <= 1.0 or not 0.0 <= push <= 1.0 or win + push > 1.0:
        raise MarketContractError("model probabilities must define win/push/loss mass")
    if win + push >= 1.0 and push >= 1.0:
        raise MarketContractError("decision requires positive resolved probability mass")

    decision_at = _utc_iso(decision_at_utc, "decision_at_utc")
    decision_dt = _as_datetime(decision_at)
    if decision_dt < _as_datetime(str(quote.ingested_at_utc)):
        raise MarketContractError("decision_at_utc must not precede quote ingestion")
    if decision_dt >= _as_datetime(str(quote.scheduled_start_utc)):
        raise MarketContractError("decision_at_utc must be before scheduled start")

    outcome_index = [item.selection for item in quote.outcomes].index(chosen)
    no_vig = two_sided_no_vig([item.american_odds for item in quote.outcomes])
    outcome = by_selection[chosen]
    resolved_mass = 1.0 - push
    if resolved_mass <= 0.0:
        raise MarketContractError("decision requires positive resolved probability mass")
    conditional_win = win / resolved_mass
    fair = no_vig.fair_probabilities[outcome_index]
    edge = conditional_win - fair
    loss = 1.0 - win - push
    expected_value = win * (outcome.decimal_odds - 1.0) - loss
    age = (decision_dt - _as_datetime(str(quote.captured_at_utc))).total_seconds()
    full_kelly = full_kelly_fraction(outcome.decimal_odds, win, push)
    quarter_kelly = KELLY_MULTIPLIER * full_kelly

    reasons: list[str] = []
    if not qualification_policy.configured:
        state = DecisionState.NO_BET
        reasons.append("QUALIFICATION_POLICY_UNSET")
    else:
        assert qualification_policy.maximum_quote_age_seconds is not None
        assert qualification_policy.minimum_edge is not None
        assert qualification_policy.minimum_expected_value is not None
        if age > qualification_policy.maximum_quote_age_seconds:
            state = DecisionState.NO_BET
            reasons.append("QUOTE_AGE_LIMIT_EXCEEDED")
        else:
            if edge < qualification_policy.minimum_edge:
                reasons.append("EDGE_BELOW_CONFIGURED_THRESHOLD")
            if expected_value < qualification_policy.minimum_expected_value:
                reasons.append("EV_BELOW_CONFIGURED_THRESHOLD")
            state = DecisionState.WATCH if reasons else DecisionState.QUALIFIED_BET

    return ShadowDecision(
        quote_sha256=quote.quote_sha256,
        canonical_game_id=quote.canonical_game_id,
        game_date=quote.game_date,
        market_family=quote.market_family,
        subject_team_id=quote.subject_team_id,
        market_rules_id=quote.market_rules_id,
        selection=chosen,
        model_id=model,
        model_artifact_sha256=artifact_sha,
        decision_at_utc=decision_at,
        scheduled_start_utc=str(quote.scheduled_start_utc),
        sportsbook_id=quote.sportsbook_id,
        line=outcome.line,
        american_odds=outcome.american_odds,
        decimal_odds=outcome.decimal_odds,
        raw_implied_probability=outcome.raw_implied_probability,
        no_vig_probability=fair,
        model_win_probability=win,
        model_push_probability=push,
        model_conditional_win_probability=conditional_win,
        edge=edge,
        expected_value_per_unit=expected_value,
        quote_age_seconds=age,
        full_kelly_fraction=full_kelly,
        quarter_kelly_fraction=quarter_kelly,
        qualification_policy=qualification_policy,
        state=state,
        reason_codes=tuple(reasons),
    )


def allocate_shadow_stakes(decisions: Sequence[ShadowDecision]) -> tuple[ShadowDecision, ...]:
    """Finalize decisions under quarter-Kelly and all fixed exposure caps.

    The 0.50% normal unit is a reporting denomination, not a minimum stake.  This
    prevents a low Kelly recommendation from being rounded up.  No currency amount is
    produced because no bankroll amount is authorized.
    """

    if any(not isinstance(item, ShadowDecision) for item in decisions):
        raise TypeError("decisions must contain only ShadowDecision values")
    if any(item.allocation_status != "PENDING" for item in decisions):
        raise MarketContractError("stake allocation accepts PENDING decisions exactly once")
    if len({item.decision_sha256 for item in decisions}) != len(decisions):
        raise MarketContractError("stake allocation rejects duplicate decisions")

    ordered = sorted(
        decisions,
        key=lambda item: (
            item.decision_at_utc,
            item.slate_date,
            item.canonical_game_id,
            MARKET_FAMILY_ORDER.index(item.market_family),
            item.selection,
            item.decision_sha256,
        ),
    )
    same_game_exposure: dict[str, float] = {}
    daily_exposure: dict[str, float] = {}
    finalized_by_pending_sha: dict[str, ShadowDecision] = {}
    for decision in ordered:
        reasons = list(decision.reason_codes)
        state = decision.state
        stake = 0.0
        if state is DecisionState.QUALIFIED_BET:
            desired = min(decision.quarter_kelly_fraction, MAX_POSITION_FRACTION)
            if desired <= 0.0:
                state = DecisionState.NO_BET
                reasons.append("NONPOSITIVE_KELLY")
            else:
                game_remaining = max(
                    0.0,
                    MAX_SAME_GAME_EXPOSURE_FRACTION
                    - same_game_exposure.get(decision.canonical_game_id, 0.0),
                )
                day_remaining = max(
                    0.0,
                    MAX_DAILY_EXPOSURE_FRACTION
                    - daily_exposure.get(decision.slate_date, 0.0),
                )
                stake = min(desired, game_remaining, day_remaining)
                if stake <= 0.0:
                    state = DecisionState.NO_BET
                    reasons.append("EXPOSURE_CAP_REACHED")
                    stake = 0.0
                else:
                    if stake + 1e-15 < decision.quarter_kelly_fraction:
                        reasons.append("STAKE_CAPPED")
                    same_game_exposure[decision.canonical_game_id] = (
                        same_game_exposure.get(decision.canonical_game_id, 0.0) + stake
                    )
                    daily_exposure[decision.slate_date] = (
                        daily_exposure.get(decision.slate_date, 0.0) + stake
                    )
        finalized_by_pending_sha[decision.decision_sha256] = replace(
            decision,
            state=state,
            reason_codes=tuple(dict.fromkeys(reasons)),
            allocation_status="FINAL",
            stake_fraction=stake,
            stake_normal_units=stake / NORMAL_UNIT_FRACTION,
        )
    return tuple(
        finalized_by_pending_sha[original.decision_sha256]
        for original in decisions
    )


class ShadowMarketLedger:
    """Process-local append-only content-addressed store for SHADOW records."""

    def __init__(self, *, activated_at_utc: str | datetime) -> None:
        self.activated_at_utc = _utc_iso(activated_at_utc, "activated_at_utc")
        self._quotes: dict[str, MarketQuote] = {}
        self._quote_source_identities: dict[tuple[str, str, str], str] = {}
        self._decisions: dict[str, ShadowDecision] = {}

    @property
    def quote_count(self) -> int:
        return len(self._quotes)

    @property
    def decision_count(self) -> int:
        return len(self._decisions)

    def append_quote(self, quote: MarketQuote) -> MarketQuote:
        if not isinstance(quote, MarketQuote):
            raise TypeError("quote must be a MarketQuote")
        if _as_datetime(str(quote.captured_at_utc)) < _as_datetime(self.activated_at_utc):
            raise MarketContractError(
                "prospective SHADOW ledger rejects quotes captured before activation"
            )
        if _canonical_sha256(quote.content_record()) != quote.quote_sha256:
            raise MarketContractError("quote content address does not match its complete record")
        existing_sha = self._quote_source_identities.get(quote.source_identity)
        if existing_sha is not None and existing_sha != quote.quote_sha256:
            raise MarketContractError("an existing source quote identity cannot be changed in place")
        existing = self._quotes.get(quote.quote_sha256)
        if existing is not None:
            return existing
        self._quotes[quote.quote_sha256] = quote
        self._quote_source_identities[quote.source_identity] = quote.quote_sha256
        return quote

    def append_decision(self, decision: ShadowDecision) -> ShadowDecision:
        if not isinstance(decision, ShadowDecision):
            raise TypeError("decision must be a ShadowDecision")
        if decision.allocation_status != "FINAL":
            raise MarketContractError("only FINAL allocated decisions may enter the ledger")
        if decision.quote_sha256 not in self._quotes:
            raise MarketContractError("decision quote must already exist in the ledger")
        quote = self._quotes[decision.quote_sha256]
        if (
            decision.canonical_game_id != quote.canonical_game_id
            or decision.game_date != quote.game_date
            or decision.market_family is not quote.market_family
            or decision.subject_team_id != quote.subject_team_id
            or decision.market_rules_id != quote.market_rules_id
            or decision.sportsbook_id != quote.sportsbook_id
            or decision.scheduled_start_utc != quote.scheduled_start_utc
            or decision.selection not in {outcome.selection for outcome in quote.outcomes}
        ):
            raise MarketContractError("decision does not match its content-addressed quote")
        if _canonical_sha256(decision.content_record()) != decision.decision_sha256:
            raise MarketContractError("decision content address does not match its complete record")
        existing = self._decisions.get(decision.decision_sha256)
        if existing is not None:
            return existing
        self._decisions[decision.decision_sha256] = decision
        return decision

    def quote(self, quote_sha256: str) -> MarketQuote:
        return self._quotes[_sha256(quote_sha256, "quote_sha256")]

    def decision(self, decision_sha256: str) -> ShadowDecision:
        return self._decisions[_sha256(decision_sha256, "decision_sha256")]

    def quotes(self) -> tuple[MarketQuote, ...]:
        return tuple(self._quotes[key] for key in sorted(self._quotes))

    def decisions(self) -> tuple[ShadowDecision, ...]:
        return tuple(self._decisions[key] for key in sorted(self._decisions))


def _board_slots(
    home_team_id: str,
    away_team_id: str,
) -> tuple[tuple[MarketFamily, str | None], ...]:
    ordinary = tuple(
        (family, None)
        for family in MARKET_FAMILY_ORDER
        if family is not MarketFamily.TEAM_TOTAL
    )
    return ordinary + (
        (MarketFamily.TEAM_TOTAL, home_team_id),
        (MarketFamily.TEAM_TOTAL, away_team_id),
    )


@dataclass(frozen=True, kw_only=True)
class MarketBoardRow:
    canonical_game_id: str
    game_date: str
    home_team_id: str
    away_team_id: str
    market_family: MarketFamily
    subject_team_id: str | None
    state: DecisionState
    reason_codes: tuple[str, ...]
    market_rules_id: str | None = None
    quote_sha256: str | None = None
    quote_origin: QuoteOrigin | None = None
    source_provider: str | None = None
    source_quote_id: str | None = None
    decision_sha256: str | None = None
    decision_at_utc: str | None = None
    sportsbook_id: str | None = None
    captured_at_utc: str | None = None
    selection: str | None = None
    line: float | None = None
    american_odds: int | None = None
    no_vig_probability: float | None = None
    model_id: str | None = None
    model_artifact_sha256: str | None = None
    model_win_probability: float | None = None
    model_push_probability: float | None = None
    edge: float | None = None
    expected_value_per_unit: float | None = None
    quote_age_seconds: float | None = None
    quarter_kelly_fraction: float | None = None
    stake_fraction: float = 0.0
    stake_normal_units: float = 0.0

    def record(self) -> dict[str, Any]:
        return {
            "canonicalGameId": self.canonical_game_id,
            "gameDate": self.game_date,
            "homeTeamId": self.home_team_id,
            "awayTeamId": self.away_team_id,
            "marketFamily": self.market_family.value,
            "subjectTeamId": self.subject_team_id,
            "marketRulesId": self.market_rules_id,
            "state": self.state.value,
            "reasonCodes": list(self.reason_codes),
            "quoteSha256": self.quote_sha256,
            "quoteOrigin": None if self.quote_origin is None else self.quote_origin.value,
            "syntheticQuote": (
                None
                if self.quote_origin is None
                else self.quote_origin is QuoteOrigin.SYNTHETIC_FIXTURE
            ),
            "sourceProvider": self.source_provider,
            "sourceQuoteId": self.source_quote_id,
            "decisionSha256": self.decision_sha256,
            "decisionAtUtc": self.decision_at_utc,
            "sportsbookId": self.sportsbook_id,
            "capturedAtUtc": self.captured_at_utc,
            "selection": self.selection,
            "line": self.line,
            "americanOdds": self.american_odds,
            "noVigProbability": self.no_vig_probability,
            "modelId": self.model_id,
            "modelArtifactSha256": self.model_artifact_sha256,
            "modelWinProbability": self.model_win_probability,
            "modelPushProbability": self.model_push_probability,
            "edge": self.edge,
            "expectedValuePerUnit": self.expected_value_per_unit,
            "quoteAgeSeconds": self.quote_age_seconds,
            "quarterKellyFraction": self.quarter_kelly_fraction,
            "stakeFraction": self.stake_fraction,
            "stakeNormalUnits": self.stake_normal_units,
            "shadowOnly": True,
            "executionAllowed": False,
        }


@dataclass(frozen=True)
class ShadowMarketBoard:
    canonical_game_id: str
    game_date: str
    home_team_id: str
    away_team_id: str
    scheduled_start_utc: str
    forecast_generated_at_utc: str | None
    rows: tuple[MarketBoardRow, ...]

    def __post_init__(self) -> None:
        game_id = _required_text(self.canonical_game_id, "canonical_game_id")
        game_date = _iso_date(self.game_date, "game_date")
        home = _required_text(self.home_team_id, "home_team_id")
        away = _required_text(self.away_team_id, "away_team_id")
        if home == away:
            raise MarketContractError("home and away teams must differ")
        scheduled = _utc_iso(self.scheduled_start_utc, "scheduled_start_utc")
        forecast = (
            None
            if self.forecast_generated_at_utc is None
            else _utc_iso(
                self.forecast_generated_at_utc,
                "forecast_generated_at_utc",
            )
        )
        if forecast is not None and _as_datetime(forecast) >= _as_datetime(scheduled):
            raise MarketContractError("forecast_generated_at_utc must be pregame")
        rows = tuple(self.rows)
        expected_slots = _board_slots(home, away)
        actual_slots = tuple(
            (row.market_family, row.subject_team_id) for row in rows
        )
        if actual_slots != expected_slots:
            raise MarketContractError(
                "board must contain the exact five ordinary slots and two TEAM_TOTAL subjects"
            )
        if any(
            row.canonical_game_id != game_id
            or row.game_date != game_date
            or row.home_team_id != home
            or row.away_team_id != away
            for row in rows
        ):
            raise MarketContractError("board row game/team identity differs")
        if self.same_game_exposure_fraction > MAX_SAME_GAME_EXPOSURE_FRACTION + 1e-15:
            raise MarketContractError("board violates maximum same-game exposure")
        object.__setattr__(self, "canonical_game_id", game_id)
        object.__setattr__(self, "game_date", game_date)
        object.__setattr__(self, "home_team_id", home)
        object.__setattr__(self, "away_team_id", away)
        object.__setattr__(self, "scheduled_start_utc", scheduled)
        object.__setattr__(self, "forecast_generated_at_utc", forecast)
        object.__setattr__(self, "rows", rows)

    @property
    def forecast_available(self) -> bool:
        return self.forecast_generated_at_utc is not None

    @property
    def same_game_exposure_fraction(self) -> float:
        return float(sum(row.stake_fraction for row in self.rows))

    def record(self) -> dict[str, Any]:
        state_counts = {
            state.value: sum(row.state is state for row in self.rows)
            for state in DECISION_STATE_ORDER
        }
        return {
            "schemaVersion": BOARD_SCHEMA_VERSION,
            "canonicalGameId": self.canonical_game_id,
            "gameDate": self.game_date,
            "homeTeamId": self.home_team_id,
            "awayTeamId": self.away_team_id,
            "matchup": {
                "awayTeamId": self.away_team_id,
                "homeTeamId": self.home_team_id,
            },
            "scheduledStartUtc": self.scheduled_start_utc,
            "forecastGeneratedAtUtc": self.forecast_generated_at_utc,
            "forecastAvailable": self.forecast_available,
            "expectedMarketFamilyCount": len(MARKET_FAMILY_ORDER),
            "expectedRowCount": len(_board_slots(self.home_team_id, self.away_team_id)),
            "rowCount": len(self.rows),
            "allMarketSlotsPresentExactlyOnce": True,
            "stateCounts": state_counts,
            "sameGameExposureFraction": self.same_game_exposure_fraction,
            "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
            "rows": [row.record() for row in self.rows],
            "fabricatedDefaultOddsAllowed": False,
            "parlaysAllowed": False,
            "shadowOnly": True,
            "executionAllowed": False,
        }


def build_shadow_board(
    *,
    canonical_game_id: str,
    game_date: str,
    home_team_id: str,
    away_team_id: str,
    scheduled_start_utc: str | datetime,
    forecast_generated_at_utc: str | datetime | None = None,
    quotes: Sequence[MarketQuote] = (),
    decisions: Sequence[ShadowDecision] = (),
) -> ShadowMarketBoard:
    """Build five ordinary rows plus one TEAM_TOTAL row per subject team."""

    game_id = _required_text(canonical_game_id, "canonical_game_id")
    game_day = _iso_date(game_date, "game_date")
    home = _required_text(home_team_id, "home_team_id")
    away = _required_text(away_team_id, "away_team_id")
    if home == away:
        raise MarketContractError("home and away teams must differ")
    scheduled = _utc_iso(scheduled_start_utc, "scheduled_start_utc")
    relevant_quotes = [item for item in quotes if item.canonical_game_id == game_id]
    relevant_decisions = [item for item in decisions if item.canonical_game_id == game_id]
    if any(item.allocation_status != "FINAL" for item in relevant_decisions):
        raise MarketContractError("board accepts FINAL decisions only")

    slots = _board_slots(home, away)
    quotes_by_slot: dict[tuple[MarketFamily, str | None], list[MarketQuote]] = {
        slot: [] for slot in slots
    }
    for quote in relevant_quotes:
        if (
            str(quote.scheduled_start_utc) != scheduled
            or quote.game_date != game_day
            or quote.home_team_id != home
            or quote.away_team_id != away
        ):
            raise MarketContractError("board quote game/team/start identity differs")
        quotes_by_slot[(quote.market_family, quote.subject_team_id)].append(quote)
    decisions_by_slot: dict[
        tuple[MarketFamily, str | None], list[ShadowDecision]
    ] = {slot: [] for slot in slots}
    for decision in relevant_decisions:
        if decision.game_date != game_day:
            raise MarketContractError("board decision game date differs")
        decisions_by_slot[(decision.market_family, decision.subject_team_id)].append(
            decision
        )

    rows: list[MarketBoardRow] = []
    for family, subject_team_id in slots:
        family_quotes = quotes_by_slot[(family, subject_team_id)]
        family_decisions = decisions_by_slot[(family, subject_team_id)]
        if len(family_decisions) > 1:
            raise MarketContractError(
                "the MVP board requires at most one finalized decision per market slot"
            )
        common = {
            "canonical_game_id": game_id,
            "game_date": game_day,
            "home_team_id": home,
            "away_team_id": away,
            "market_family": family,
            "subject_team_id": subject_team_id,
        }
        if not family_decisions:
            if family_quotes:
                latest = max(
                    family_quotes,
                    key=lambda item: (str(item.captured_at_utc), item.quote_sha256),
                )
                rows.append(
                    MarketBoardRow(
                        **common,
                        state=DecisionState.NO_BET,
                        reason_codes=("NO_FINAL_SHADOW_DECISION",),
                        market_rules_id=latest.market_rules_id,
                        quote_sha256=latest.quote_sha256,
                        quote_origin=latest.quote_origin,
                        source_provider=latest.source_provider,
                        source_quote_id=latest.source_quote_id,
                        sportsbook_id=latest.sportsbook_id,
                        captured_at_utc=str(latest.captured_at_utc),
                    )
                )
            else:
                rows.append(
                    MarketBoardRow(
                        **common,
                        state=DecisionState.NO_BET,
                        reason_codes=("NO_PERSISTED_TWO_SIDED_QUOTE",),
                    )
                )
            continue
        decision = family_decisions[0]
        matching = [
            item
            for item in family_quotes
            if item.quote_sha256 == decision.quote_sha256
        ]
        if len(matching) != 1:
            raise MarketContractError(
                "board decision must bind exactly one supplied quote"
            )
        quote = matching[0]
        rows.append(
            MarketBoardRow(
                **common,
                state=decision.state,
                reason_codes=decision.reason_codes,
                market_rules_id=quote.market_rules_id,
                quote_sha256=quote.quote_sha256,
                quote_origin=quote.quote_origin,
                source_provider=quote.source_provider,
                source_quote_id=quote.source_quote_id,
                decision_sha256=decision.decision_sha256,
                decision_at_utc=decision.decision_at_utc,
                sportsbook_id=quote.sportsbook_id,
                captured_at_utc=str(quote.captured_at_utc),
                selection=decision.selection,
                line=decision.line,
                american_odds=decision.american_odds,
                no_vig_probability=decision.no_vig_probability,
                model_id=decision.model_id,
                model_artifact_sha256=decision.model_artifact_sha256,
                model_win_probability=decision.model_win_probability,
                model_push_probability=decision.model_push_probability,
                edge=decision.edge,
                expected_value_per_unit=decision.expected_value_per_unit,
                quote_age_seconds=decision.quote_age_seconds,
                quarter_kelly_fraction=decision.quarter_kelly_fraction,
                stake_fraction=decision.stake_fraction,
                stake_normal_units=decision.stake_normal_units,
            )
        )
    forecast = (
        None
        if forecast_generated_at_utc is None
        else _utc_iso(forecast_generated_at_utc, "forecast_generated_at_utc")
    )
    return ShadowMarketBoard(
        game_id,
        game_day,
        home,
        away,
        scheduled,
        forecast,
        tuple(rows),
    )


@dataclass(frozen=True)
class DailyShadowMarketBoard:
    board_date: str
    game_boards: tuple[ShadowMarketBoard, ...]

    def __post_init__(self) -> None:
        board_date = _iso_date(self.board_date, "board_date")
        if any(not isinstance(board, ShadowMarketBoard) for board in self.game_boards):
            raise TypeError("game_boards must contain only ShadowMarketBoard values")
        boards = tuple(
            sorted(
                self.game_boards,
                key=lambda board: (board.scheduled_start_utc, board.canonical_game_id),
            )
        )
        if len({board.canonical_game_id for board in boards}) != len(boards):
            raise MarketContractError("daily board rejects duplicate games")
        if any(board.game_date != board_date for board in boards):
            raise MarketContractError("daily board game date differs from board_date")
        if self.daily_exposure_fraction > MAX_DAILY_EXPOSURE_FRACTION + 1e-15:
            raise MarketContractError("daily board violates maximum daily exposure")
        object.__setattr__(self, "board_date", board_date)
        object.__setattr__(self, "game_boards", boards)

    @property
    def daily_exposure_fraction(self) -> float:
        return float(
            sum(board.same_game_exposure_fraction for board in self.game_boards)
        )

    def record(self) -> dict[str, Any]:
        rows = [row for board in self.game_boards for row in board.rows]
        state_counts = {
            state.value: sum(row.state is state for row in rows)
            for state in DECISION_STATE_ORDER
        }
        return {
            "schemaVersion": DAILY_BOARD_SCHEMA_VERSION,
            "boardDate": self.board_date,
            "gameCount": len(self.game_boards),
            "marketFamilyCount": len(MARKET_FAMILY_ORDER),
            "rowCount": len(rows),
            "stateCounts": state_counts,
            "forecastAvailableGameCount": sum(
                board.forecast_available for board in self.game_boards
            ),
            "sourceQuoteCount": sum(row.quote_sha256 is not None for row in rows),
            "syntheticQuoteCount": sum(
                row.quote_origin is QuoteOrigin.SYNTHETIC_FIXTURE for row in rows
            ),
            "observedProviderQuoteCount": sum(
                row.quote_origin is QuoteOrigin.OBSERVED_PROVIDER for row in rows
            ),
            "dailyExposureFraction": self.daily_exposure_fraction,
            "virtualPolicyCaps": {
                "kellyMultiplier": KELLY_MULTIPLIER,
                "normalUnitFraction": NORMAL_UNIT_FRACTION,
                "maximumPositionFraction": MAX_POSITION_FRACTION,
                "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
                "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
                "bankrollAmount": None,
            },
            "games": [board.record() for board in self.game_boards],
            "fabricatedDefaultOddsAllowed": False,
            "parlaysAllowed": False,
            "shadowOnly": True,
            "executionAllowed": False,
        }


def build_daily_shadow_board(
    *,
    board_date: str,
    game_boards: Sequence[ShadowMarketBoard],
) -> DailyShadowMarketBoard:
    """Aggregate already-built typed per-game boards under the daily exposure cap."""

    return DailyShadowMarketBoard(board_date, tuple(game_boards))


def zero_historical_market_coverage() -> tuple[dict[str, Any], ...]:
    """Return the audited fail-closed zero coverage for the fixed OOF/holdout periods."""

    return tuple(
        {
            "schemaVersion": HISTORICAL_COVERAGE_SCHEMA_VERSION,
            "periodId": period.period_id,
            "startDate": period.start_date,
            "endDate": period.end_date,
            "goldPaRows": period.pa_rows,
            "goldMatchedGames": period.gold_matched_games,
            "activeDates": period.active_dates,
            "persistedQuoteCount": 0,
            "timestampedQuoteCount": 0,
            "twoSidedMarketCount": 0,
            "coveredGameCount": 0,
            "coveredGameRate": 0.0,
            "minimumQuoteTimestampUtc": None,
            "maximumQuoteTimestampUtc": None,
            "marketCoverage": {family.value: 0 for family in MARKET_FAMILY_ORDER},
            "backtestEligible": False,
            "status": "UNAVAILABLE",
            "reason": "NO_GOVERNED_PERSISTED_HISTORICAL_SPORTSBOOK_QUOTES",
        }
        for period in HISTORICAL_EVALUATION_PERIODS
    )


def market_mvp_contract() -> dict[str, Any]:
    """Return the complete fixed schema/cap inventory without implying readiness."""

    return {
        "schemaVersion": SCHEMA_VERSION,
        "quoteSchemaVersion": QUOTE_SCHEMA_VERSION,
        "decisionSchemaVersion": DECISION_SCHEMA_VERSION,
        "boardSchemaVersion": BOARD_SCHEMA_VERSION,
        "dailyBoardSchemaVersion": DAILY_BOARD_SCHEMA_VERSION,
        "marketFamilies": [family.value for family in MARKET_FAMILY_ORDER],
        "teamTotal": {
            "sportNeutralFamily": MarketFamily.TEAM_TOTAL.value,
            "subjectTeamIdRequired": True,
            "perGameSubjects": ["HOME_TEAM", "AWAY_TEAM"],
            "expectedRowsPerGame": 2,
        },
        "expectedBoardRowsPerGame": len(MARKET_FAMILY_ORDER) + 1,
        "decisionStates": [state.value for state in DECISION_STATE_ORDER],
        "quoteOrigins": [origin.value for origin in QuoteOrigin],
        "twoSidedSelections": {
            family.value: list(_SELECTION_ORDER[family]) for family in MARKET_FAMILY_ORDER
        },
        "noVigMethod": "PROPORTIONAL_TWO_SIDED_NO_VIG",
        "staking": {
            "kellyMultiplier": KELLY_MULTIPLIER,
            "normalUnitFraction": NORMAL_UNIT_FRACTION,
            "maximumPositionFraction": MAX_POSITION_FRACTION,
            "maximumSameGameExposureFraction": MAX_SAME_GAME_EXPOSURE_FRACTION,
            "maximumDailyExposureFraction": MAX_DAILY_EXPOSURE_FRACTION,
            "normalUnitIsMinimumStake": False,
            "bankrollAmount": None,
        },
        "qualificationPolicy": UNSET_QUALIFICATION_POLICY.record(),
        "unsetPolicyBehavior": {"state": "NO_BET", "stakeFraction": 0.0},
        "appendOnly": True,
        "contentAddressed": True,
        "prospectiveLedgerRequiresActivationUtc": True,
        "historicalBackfillAllowed": False,
        "syntheticQuotesRequireExplicitOrigin": True,
        "fabricatedDefaultOddsAllowed": False,
        "parlaysAllowed": False,
        "shadowOnly": True,
        "executionAllowed": False,
        "historicalBacktestEligible": False,
    }


__all__ = [
    "BOARD_SCHEMA_VERSION",
    "DAILY_BOARD_SCHEMA_VERSION",
    "DECISION_SCHEMA_VERSION",
    "DECISION_STATE_ORDER",
    "HISTORICAL_EVALUATION_PERIODS",
    "KELLY_MULTIPLIER",
    "MARKET_FAMILY_ORDER",
    "MAX_DAILY_EXPOSURE_FRACTION",
    "MAX_POSITION_FRACTION",
    "MAX_SAME_GAME_EXPOSURE_FRACTION",
    "NORMAL_UNIT_FRACTION",
    "QUOTE_SCHEMA_VERSION",
    "DecisionState",
    "DailyShadowMarketBoard",
    "MarketBoardRow",
    "MarketContractError",
    "MarketFamily",
    "MarketOutcomeQuote",
    "MarketQuote",
    "NoVigResult",
    "QualificationPolicy",
    "QuoteOrigin",
    "ShadowDecision",
    "ShadowMarketBoard",
    "ShadowMarketLedger",
    "UNSET_QUALIFICATION_POLICY",
    "allocate_shadow_stakes",
    "american_implied_probability",
    "american_to_decimal",
    "build_shadow_board",
    "build_daily_shadow_board",
    "full_kelly_fraction",
    "make_market_quote",
    "make_shadow_decision",
    "market_mvp_contract",
    "proportional_no_vig",
    "quarter_kelly_fraction",
    "two_sided_no_vig",
    "zero_historical_market_coverage",
]
