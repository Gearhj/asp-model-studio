"""MLB_CATCHER_INFLUENCE_READINESS_V1 — catcher & battery evidence readiness audit.

This module is a **readiness/data audit**, NOT a predictive catcher model. It
measures, from the existing governed *free* historical evidence only, how
reliably catcher identity can be reconstructed and how sparse pitcher-catcher and
catcher-batter histories actually are, so a future
``MLB_CATCHER_AND_BATTERY_EFFECT_V1`` study can be *designed* against real
coverage rather than assumptions.

It deliberately contains no model fitting, no coefficient estimation, no grid
search, and no calibration. Every function here is pure and operates on already
validated, normalized in-memory structures (mirroring the discipline of
``participation_features.py``): the adapter from governed Parquet to these
structures is wired by the operator at run time and is itself one of the fields
the audit reports availability for. Because the functions are pure, the algorithms
(exact catcher assignment, substitution handling, ambiguous/missing intervals,
strict prior-history sample counting with no target self-inclusion) are covered by
hermetic unit tests without touching the full dataset.

Terminology (approved): a measured association between the catcher on the field
and outcomes is a ``CATCHER_ASSOCIATED_EFFECT``; a joint pitcher+catcher
association is a ``PITCHER_CATCHER_BATTERY_EFFECT``; a catcher×batter-archetype
association is a ``CATCHER_BATTER_ARCHETYPE_INTERACTION``. This module never claims
the catcher personally *called* a pitch, never estimates framing without
pitch-location/tracking evidence, and never produces betting predictions.
"""

from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

CATCHER_READINESS_CONTRACT_NAME = "MLB_CATCHER_INFLUENCE_READINESS_V1"
CATCHER_READINESS_SCHEMA_VERSION = "MLB_CATCHER_INFLUENCE_READINESS_V1"

# Seasons the free package may support; the audit reports only those actually present.
AUDIT_SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024, 2025)
# The primary modeling-readiness population matches the Milestone A/B frozen policy.
PRIMARY_MODELING_SEASONS: tuple[int, ...] = (2023, 2024, 2025)

# Defensive-position codes that denote a catcher across common free encodings.
# Both the numeric scorekeeping code ("2") and the letter code ("C") are accepted;
# the adapter passes through the source encoding and the audit records which it saw.
CATCHER_POSITION_CODES: frozenset[str] = frozenset({"2", "C", "c"})

# Prior-history sample-size bands (left-inclusive, right-inclusive as labeled).
SAMPLE_SIZE_BANDS: tuple[str, ...] = (
    "0",
    "1-9",
    "10-24",
    "25-49",
    "50-99",
    "100-249",
    "250+",
)

# Cumulative "at least N prior" thresholds reported alongside the bands.
SAMPLE_SIZE_AT_LEAST_THRESHOLDS: tuple[int, ...] = (25, 50, 100, 250)

# Readiness thresholds (NOT proven-optimal modeling thresholds — see contract).
# These map a prior-sample count to the *lowest defensible* modeling level a
# future study could support for that unit of evidence.
BATTERY_FALLBACK_LEVELS: tuple[tuple[str, int, str], ...] = (
    ("LEVEL_0_LEAGUE_GLOBAL", 0, "No prior battery evidence; league/global fallback only."),
    ("LEVEL_1_MAIN_EFFECTS", 1, "Some prior evidence; pitcher-only / catcher-only main effects."),
    ("LEVEL_2_CATCHER_POOLED", 25, "Catcher-level pooled effect is defensible."),
    ("LEVEL_3_BATTERY_POOLED", 50, "Pitcher-catcher battery pooled effect is defensible."),
    ("LEVEL_4_BATTERY_SPECIFIC", 250, "Well-supported battery-specific effect."),
)

CatcherAssignmentStatus = Literal["DETERMINISTIC", "AMBIGUOUS", "MISSING"]

TERMINAL_STATUSES: tuple[str, ...] = (
    "CATCHER_INFLUENCE_READY_FOR_RESEARCH_DESIGN",
    "CATCHER_INFLUENCE_PARTIALLY_READY",
    "CATCHER_INFLUENCE_DATA_AUDIT_BLOCKED",
)

# READY thresholds: high reconstruction + assignment coverage and reliable linkage.
READY_STARTING_CATCHER_COVERAGE = 0.97
READY_PA_ASSIGNMENT_COVERAGE = 0.90
PARTIAL_STARTING_CATCHER_COVERAGE = 0.80
PARTIAL_PA_ASSIGNMENT_COVERAGE = 0.50


class CatcherReadinessError(RuntimeError):
    """Raised when the audit inputs violate the governed readiness contract."""


# ---------------------------------------------------------------------------
# Normalized input contract (adapter target). All identities are exact canonical
# UUIDs resolved through the governed identity bridge -- never player names.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FieldingAppearance:
    """One player's defensive appearance in one game (from player_game_fielding)."""

    game_id: str
    team_id: str
    player_uuid: str
    season: int
    game_date: str
    final_ordinal: int
    position_code: str
    is_start: bool
    innings_caught: float | None = None

    def is_catcher(self) -> bool:
        return str(self.position_code) in CATCHER_POSITION_CODES


@dataclass(frozen=True)
class CatcherSubstitution:
    """An in-game catcher change with an ordered event index (from play events)."""

    game_id: str
    team_id: str
    incoming_catcher_uuid: str
    event_index: int
    outgoing_catcher_uuid: str | None = None


@dataclass(frozen=True)
class PlateAppearanceRow:
    """One plate appearance with exact pitcher identity (from plate_appearance)."""

    game_id: str
    defense_team_id: str
    season: int
    game_date: str
    game_ordinal: int
    pa_index: int
    pitcher_uuid: str
    batter_uuid: str
    pitcher_role: str | None = None  # "STARTER" / "RELIEVER" where role evidence supports it


@dataclass(frozen=True)
class TeamGameCatcher:
    """Reconstruction result for one team-game's starting catcher."""

    game_id: str
    team_id: str
    season: int
    status: CatcherAssignmentStatus
    catcher_uuid: str | None
    candidate_catchers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlateAppearanceCatcher:
    """Assignment result for one plate appearance's active catcher."""

    game_id: str
    defense_team_id: str
    season: int
    pa_index: int
    pitcher_uuid: str
    batter_uuid: str
    status: CatcherAssignmentStatus
    catcher_uuid: str | None
    pitcher_role: str | None = None


# ---------------------------------------------------------------------------
# 1. Catcher identity reconstruction
# ---------------------------------------------------------------------------
def reconstruct_starting_catchers(
    fielding: Iterable[FieldingAppearance],
) -> list[TeamGameCatcher]:
    """Deterministic starting catcher per team-game from defensive appearances.

    A team-game is DETERMINISTIC when exactly one player has a catcher *start*
    (``is_start`` and a catcher position code). It is AMBIGUOUS when more than one
    distinct player claims a catcher start (never silently pick one), and MISSING
    when no catcher start is present. Non-starting catcher appearances (mid-game
    substitutions) do not establish the *starting* catcher.
    """

    starts: dict[tuple[str, str], set[str]] = defaultdict(set)
    seasons: dict[tuple[str, str], int] = {}
    for appearance in fielding:
        key = (appearance.game_id, appearance.team_id)
        seasons.setdefault(key, appearance.season)
        if appearance.is_catcher() and appearance.is_start:
            starts[key].add(appearance.player_uuid)
    results: list[TeamGameCatcher] = []
    for key in sorted(seasons):
        catchers = starts.get(key, set())
        if len(catchers) == 1:
            status: CatcherAssignmentStatus = "DETERMINISTIC"
            catcher = next(iter(catchers))
        elif len(catchers) == 0:
            status, catcher = "MISSING", None
        else:
            status, catcher = "AMBIGUOUS", None
        results.append(
            TeamGameCatcher(
                game_id=key[0],
                team_id=key[1],
                season=seasons[key],
                status=status,
                catcher_uuid=catcher,
                candidate_catchers=tuple(sorted(catchers)),
            )
        )
    return results


def _substitution_intervals(
    starting_catcher: str | None,
    substitutions: Sequence[CatcherSubstitution],
) -> list[tuple[int, str | None, bool]] | None:
    """Return ordered (event_index_start, catcher_uuid, ambiguous) intervals.

    Returns ``None`` when the substitution record is internally contradictory
    (e.g. an outgoing catcher that does not match the currently active catcher),
    which must be surfaced as ambiguity rather than silently forward-filled.
    """

    ordered = sorted(substitutions, key=lambda item: item.event_index)
    intervals: list[tuple[int, str | None, bool]] = [(-1, starting_catcher, starting_catcher is None)]
    active = starting_catcher
    for sub in ordered:
        if sub.outgoing_catcher_uuid is not None and active is not None and sub.outgoing_catcher_uuid != active:
            return None  # contradictory chain -> caller marks the remainder ambiguous
        active = sub.incoming_catcher_uuid
        intervals.append((sub.event_index, active, False))
    return intervals


def assign_catcher_at_plate_appearances(
    plate_appearances: Iterable[PlateAppearanceRow],
    starting_catchers: Mapping[tuple[str, str], TeamGameCatcher],
    substitutions: Mapping[tuple[str, str], Sequence[CatcherSubstitution]] | None = None,
) -> list[PlateAppearanceCatcher]:
    """Assign the active catcher to each PA using the reconstructed starter and,
    where available, ordered in-game substitution events.

    Assignment is DETERMINISTIC only when the defensive team-game has a
    deterministic starting catcher and the PA falls inside an unambiguous
    substitution interval. It is AMBIGUOUS across a contradictory substitution
    chain (never forward-filled through it) and when the starting catcher itself
    is ambiguous; it is MISSING when no starting catcher exists. PA ordering uses
    ``pa_index`` as the in-game event clock.
    """

    substitutions = substitutions or {}
    results: list[PlateAppearanceCatcher] = []
    for pa in plate_appearances:
        key = (pa.game_id, pa.defense_team_id)
        team_game = starting_catchers.get(key)
        base = PlateAppearanceCatcher(
            game_id=pa.game_id,
            defense_team_id=pa.defense_team_id,
            season=pa.season,
            pa_index=pa.pa_index,
            pitcher_uuid=pa.pitcher_uuid,
            batter_uuid=pa.batter_uuid,
            status="MISSING",
            catcher_uuid=None,
            pitcher_role=pa.pitcher_role,
        )
        if team_game is None or team_game.status == "MISSING":
            results.append(base)
            continue
        if team_game.status == "AMBIGUOUS":
            results.append(_with_status(base, "AMBIGUOUS", None))
            continue
        subs = substitutions.get(key) or ()
        if not subs:
            results.append(_with_status(base, "DETERMINISTIC", team_game.catcher_uuid))
            continue
        intervals = _substitution_intervals(team_game.catcher_uuid, subs)
        if intervals is None:
            results.append(_with_status(base, "AMBIGUOUS", None))
            continue
        boundaries = [start for start, _uuid, _amb in intervals]
        slot = bisect.bisect_right(boundaries, pa.pa_index) - 1
        _start, catcher_uuid, ambiguous = intervals[slot]
        if ambiguous or catcher_uuid is None:
            results.append(_with_status(base, "AMBIGUOUS", None))
        else:
            results.append(_with_status(base, "DETERMINISTIC", catcher_uuid))
    return results


def _with_status(
    row: PlateAppearanceCatcher, status: CatcherAssignmentStatus, catcher_uuid: str | None
) -> PlateAppearanceCatcher:
    return PlateAppearanceCatcher(
        game_id=row.game_id,
        defense_team_id=row.defense_team_id,
        season=row.season,
        pa_index=row.pa_index,
        pitcher_uuid=row.pitcher_uuid,
        batter_uuid=row.batter_uuid,
        status=status,
        catcher_uuid=catcher_uuid,
        pitcher_role=row.pitcher_role,
    )


# ---------------------------------------------------------------------------
# 2. Coverage metrics
# ---------------------------------------------------------------------------
def starting_catcher_coverage(team_games: Sequence[TeamGameCatcher]) -> dict[str, Any]:
    by_season: dict[int, Counter[str]] = defaultdict(Counter)
    for tg in team_games:
        by_season[tg.season][tg.status] += 1
    seasons: dict[str, Any] = {}
    for season in sorted(by_season):
        counts = by_season[season]
        total = sum(counts.values())
        deterministic = counts["DETERMINISTIC"]
        seasons[str(season)] = {
            "teamGames": total,
            "deterministicStartingCatcher": deterministic,
            "ambiguous": counts["AMBIGUOUS"],
            "missing": counts["MISSING"],
            "startingCatcherCoverageRate": (deterministic / total) if total else None,
        }
    return seasons


def pa_assignment_coverage(pa_catchers: Sequence[PlateAppearanceCatcher]) -> dict[str, Any]:
    by_season: dict[int, Counter[str]] = defaultdict(Counter)
    unique_catchers: dict[int, set[str]] = defaultdict(set)
    for row in pa_catchers:
        by_season[row.season][row.status] += 1
        if row.catcher_uuid is not None:
            unique_catchers[row.season].add(row.catcher_uuid)
    seasons: dict[str, Any] = {}
    for season in sorted(by_season):
        counts = by_season[season]
        total = sum(counts.values())
        deterministic = counts["DETERMINISTIC"]
        seasons[str(season)] = {
            "plateAppearances": total,
            "deterministicCatcherAssignment": deterministic,
            "ambiguous": counts["AMBIGUOUS"],
            "missing": counts["MISSING"],
            "paCatcherAssignmentCoverageRate": (deterministic / total) if total else None,
            "uniqueCatchers": len(unique_catchers[season]),
        }
    return seasons


# ---------------------------------------------------------------------------
# 3. Prior-history sample-size distributions (strict, no target self-inclusion)
# ---------------------------------------------------------------------------
def _band_for(count: int) -> str:
    if count <= 0:
        return "0"
    if count <= 9:
        return "1-9"
    if count <= 24:
        return "10-24"
    if count <= 49:
        return "25-49"
    if count <= 99:
        return "50-99"
    if count <= 249:
        return "100-249"
    return "250+"


def _percentile(sorted_values: Sequence[int], probability: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    position = (len(sorted_values) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return float(sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction)


def prior_pair_sample_distribution(
    events: Sequence[tuple[str, int]],
) -> dict[str, Any]:
    """Distribution of prior same-pair sample sizes over a modeling population.

    ``events`` is a sequence of ``(pair_key, event_ordinal)`` for every unit in the
    modeling population (e.g. one entry per PA, keyed by battery or catcher-batter
    pair, ordinalized by a strictly-increasing event clock). For each event the
    "prior sample size" is the number of *earlier* events for the same pair —
    strictly before this event's ordinal, so a target PA is **never** counted in
    its own history. Ties on the same ordinal (e.g. same game) are excluded from
    the prior count as well (``bisect_left``), matching the leakage-safe policy.
    """

    ordinals_by_pair: dict[str, list[int]] = defaultdict(list)
    for pair_key, ordinal in events:
        ordinals_by_pair[pair_key].append(int(ordinal))
    for values in ordinals_by_pair.values():
        values.sort()

    band_counts: Counter[str] = Counter({band: 0 for band in SAMPLE_SIZE_BANDS})
    prior_counts: list[int] = []
    for pair_key, ordinal in events:
        ordinals = ordinals_by_pair[pair_key]
        prior = bisect.bisect_left(ordinals, int(ordinal))
        band_counts[_band_for(prior)] += 1
        prior_counts.append(prior)

    population = len(events)
    prior_counts.sort()
    at_least = {
        f">={threshold}": sum(1 for value in prior_counts if value >= threshold)
        for threshold in SAMPLE_SIZE_AT_LEAST_THRESHOLDS
    }
    return {
        "population": population,
        "uniquePairs": len(ordinals_by_pair),
        "bands": {
            band: {
                "count": band_counts[band],
                "percentOfPopulation": (band_counts[band] / population) if population else None,
            }
            for band in SAMPLE_SIZE_BANDS
        },
        "medianPriorSamples": _percentile(prior_counts, 0.50),
        "p75PriorSamples": _percentile(prior_counts, 0.75),
        "p90PriorSamples": _percentile(prior_counts, 0.90),
        "p95PriorSamples": _percentile(prior_counts, 0.95),
        "maxPriorSamples": prior_counts[-1] if prior_counts else None,
        "atLeast": {
            key: {
                "count": value,
                "percentOfPopulation": (value / population) if population else None,
            }
            for key, value in at_least.items()
        },
    }


def battery_fallback_distribution(prior_counts: Sequence[int]) -> dict[str, Any]:
    """Assign each modeling unit to the lowest defensible battery-effect level.

    These are *readiness* levels (defensible given sample support), explicitly not
    proven-optimal modeling thresholds — see the contract.
    """

    level_counts: Counter[str] = Counter({name: 0 for name, _t, _d in BATTERY_FALLBACK_LEVELS})
    ascending = sorted(BATTERY_FALLBACK_LEVELS, key=lambda item: item[1])
    for count in prior_counts:
        assigned = ascending[0][0]
        for name, threshold, _desc in ascending:
            if count >= threshold:
                assigned = name
        level_counts[assigned] += 1
    population = len(prior_counts)
    return {
        "levels": [
            {
                "level": name,
                "minPriorSamples": threshold,
                "description": desc,
                "count": level_counts[name],
                "percentOfPopulation": (level_counts[name] / population) if population else None,
            }
            for name, threshold, desc in BATTERY_FALLBACK_LEVELS
        ],
        "population": population,
    }


# ---------------------------------------------------------------------------
# 4. Feature availability inventory & premium-data gaps (static, honest)
# ---------------------------------------------------------------------------
def free_feature_inventory() -> list[dict[str, str]]:
    """Availability of catcher-related features from existing governed *free* data.

    Availability is intentionally conservative and is confirmed at run time by the
    audit against the resolved schema (the audit overrides an entry to UNAVAILABLE
    if the backing family/field is absent). ``label`` values are drawn from the
    governed vocabulary AVAILABLE / DERIVABLE / PARTIALLY_AVAILABLE / UNRELIABLE /
    UNAVAILABLE.
    """

    return [
        {"field": "catcher_starts", "label": "DERIVABLE", "source": "player_game_fielding"},
        {"field": "catcher_appearances", "label": "DERIVABLE", "source": "player_game_fielding"},
        {"field": "days_rest", "label": "DERIVABLE", "source": "player_game_fielding (prior dates)"},
        {"field": "consecutive_catching_days", "label": "DERIVABLE", "source": "player_game_fielding"},
        {"field": "trailing_catcher_workload", "label": "DERIVABLE", "source": "player_game_fielding"},
        {"field": "innings_caught", "label": "PARTIALLY_AVAILABLE", "source": "player_game_fielding (if present)"},
        {"field": "plate_appearances_caught", "label": "DERIVABLE", "source": "reconstructed catcher × plate_appearance"},
        {"field": "pitcher_catcher_prior_pa_count", "label": "DERIVABLE", "source": "reconstructed battery history"},
        {"field": "prior_battery_outcome_distribution", "label": "DERIVABLE", "source": "reconstructed battery × plate_appearance"},
        {"field": "catcher_batter_prior_pa_count", "label": "DERIVABLE", "source": "reconstructed catcher × batter"},
        {"field": "passed_balls", "label": "PARTIALLY_AVAILABLE", "source": "player_game_fielding / play events"},
        {"field": "putouts", "label": "PARTIALLY_AVAILABLE", "source": "player_game_fielding"},
        {"field": "assists", "label": "PARTIALLY_AVAILABLE", "source": "player_game_fielding"},
        {"field": "errors", "label": "PARTIALLY_AVAILABLE", "source": "player_game_fielding"},
        {"field": "double_plays", "label": "PARTIALLY_AVAILABLE", "source": "player_game_fielding"},
        {"field": "stolen_base_attempts_catcher_active", "label": "PARTIALLY_AVAILABLE", "source": "play_transition (catcher-observable)"},
        {"field": "caught_stealing_catcher_active", "label": "PARTIALLY_AVAILABLE", "source": "play_transition (catcher-observable)"},
        {"field": "pitch_sequence_characteristics_catcher_active", "label": "PARTIALLY_AVAILABLE", "source": "pitch_sequence (no pitch call)"},
        {"field": "battery_continuity", "label": "DERIVABLE", "source": "reconstructed battery history"},
        {"field": "catcher_substitution_frequency", "label": "DERIVABLE", "source": "play events / fielding"},
    ]


def premium_gap_inventory() -> list[dict[str, str]]:
    """Catcher fields current free evidence does NOT support reliably.

    Each is classified as PREMIUM_TRACKING_LIKELY_REQUIRED, NEW_DATA_SOURCE_REQUIRED,
    or CURRENTLY_UNAVAILABLE. None of these are ever fabricated by this audit.
    """

    return [
        {"field": "pitch_target_location", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "actual_pitch_location", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "catcher_framing", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "called_strike_probability_added", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "blocks_above_average", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "blocking_difficulty", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "pop_time", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "catcher_arm_strength", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "throw_velocity", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "exchange_time", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "catcher_pitch_selection_caller_identity", "classification": "NEW_DATA_SOURCE_REQUIRED"},
        {"field": "pitcher_execution_relative_to_target", "classification": "PREMIUM_TRACKING_LIKELY_REQUIRED"},
        {"field": "abs_challenge_opportunity", "classification": "NEW_DATA_SOURCE_REQUIRED"},
        {"field": "abs_challenge_decision", "classification": "NEW_DATA_SOURCE_REQUIRED"},
        {"field": "abs_challenge_success_value", "classification": "NEW_DATA_SOURCE_REQUIRED"},
    ]


# ---------------------------------------------------------------------------
# 5. Readiness decision
# ---------------------------------------------------------------------------
def decide_readiness(
    *,
    starting_catcher_coverage_rate: float | None,
    pa_assignment_coverage_rate: float | None,
    identity_linkage_reliable: bool,
    battery_distribution_present: bool,
    feature_inventory_present: bool,
) -> dict[str, Any]:
    """Return the governed terminal readiness status and its rationale.

    READY requires high starting-catcher reconstruction coverage, high PA
    catcher-assignment coverage, reliable identity linkage, a quantified battery
    distribution, and an honest feature inventory. READY explicitly does NOT mean a
    catcher effect has been proven predictive.
    """

    start_rate = starting_catcher_coverage_rate or 0.0
    pa_rate = pa_assignment_coverage_rate or 0.0
    reasons: list[str] = []
    if not identity_linkage_reliable:
        reasons.append("Catcher identity linkage through the governed bridge is not reliable.")
    if not battery_distribution_present:
        reasons.append("Battery prior-history distribution was not quantified.")
    if not feature_inventory_present:
        reasons.append("Free/premium feature inventory is incomplete.")

    if (
        identity_linkage_reliable
        and battery_distribution_present
        and feature_inventory_present
        and start_rate >= READY_STARTING_CATCHER_COVERAGE
        and pa_rate >= READY_PA_ASSIGNMENT_COVERAGE
    ):
        status = "CATCHER_INFLUENCE_READY_FOR_RESEARCH_DESIGN"
        rationale = (
            "Starting-catcher reconstruction and PA catcher-assignment coverage are high, "
            "identity linkage is reliable, and battery sample support is quantified. This "
            "authorizes a future catcher/battery study *design* only; no catcher effect is "
            "proven predictive."
        )
    elif (
        start_rate >= PARTIAL_STARTING_CATCHER_COVERAGE
        and pa_rate >= PARTIAL_PA_ASSIGNMENT_COVERAGE
        and identity_linkage_reliable
    ):
        status = "CATCHER_INFLUENCE_PARTIALLY_READY"
        rationale = (
            "Starting-catcher coverage is usable but PA-level assignment or evidence support "
            "is incomplete; a future study must treat catcher assignment as partially "
            "observed. " + " ".join(reasons)
        ).strip()
    else:
        status = "CATCHER_INFLUENCE_DATA_AUDIT_BLOCKED"
        rationale = (
            "Catcher reconstruction or identity linkage coverage is insufficient to design a "
            "catcher/battery study on current free evidence. " + " ".join(reasons)
        ).strip()
    return {
        "status": status,
        "rationale": rationale,
        "startingCatcherCoverageRate": starting_catcher_coverage_rate,
        "paAssignmentCoverageRate": pa_assignment_coverage_rate,
        "thresholds": {
            "readyStartingCatcherCoverage": READY_STARTING_CATCHER_COVERAGE,
            "readyPaAssignmentCoverage": READY_PA_ASSIGNMENT_COVERAGE,
            "partialStartingCatcherCoverage": PARTIAL_STARTING_CATCHER_COVERAGE,
            "partialPaAssignmentCoverage": PARTIAL_PA_ASSIGNMENT_COVERAGE,
            "note": "Readiness thresholds, not proven-optimal modeling thresholds.",
        },
    }


# ---------------------------------------------------------------------------
# 6. Future model design (documentation payload only — no estimation)
# ---------------------------------------------------------------------------
def future_model_design() -> dict[str, Any]:
    """The recommended ``MLB_CATCHER_AND_BATTERY_EFFECT_V1`` ablation design.

    Documentation only. This module never estimates any coefficient.
    """

    return {
        "contract": "MLB_CATCHER_AND_BATTERY_EFFECT_V1",
        "status": "DESIGN_ONLY_NOT_IMPLEMENTED",
        "ablation": [
            {"id": "M0", "definition": "Existing batter + pitcher + D3 state model."},
            {"id": "M1", "definition": "M0 + CATCHER_ASSOCIATED_EFFECT (catcher main effect)."},
            {"id": "M2", "definition": "M1 + PITCHER_CATCHER_BATTERY_EFFECT interaction."},
            {"id": "M3", "definition": "M2 + CATCHER_BATTER_ARCHETYPE_INTERACTION."},
            {"id": "M4", "definition": "M3 + free pitch-sequence tendencies (no pitch call/location)."},
            {"id": "M5", "definition": "M4 + premium tracking / framing / blocking data."},
        ],
        "pooling": (
            "Hierarchical partial pooling: sparse batteries shrink toward pitcher, "
            "catcher, archetype, then league effects."
        ),
        "note": "No coefficients estimated. Ablation is documentation for a future study.",
    }


# ---------------------------------------------------------------------------
# 7. Audit assembly (registry-ready evidence payload)
# ---------------------------------------------------------------------------
@dataclass
class CatcherReadinessAudit:
    """Registry-ready audit evidence. Content is JSON-serializable and hashable."""

    dataset_authority: Mapping[str, Any]
    identity_bridge_authority: Mapping[str, Any]
    seasons: Sequence[int]
    starting_catcher_coverage: Mapping[str, Any]
    pa_assignment_coverage: Mapping[str, Any]
    battery_distribution: Mapping[str, Any]
    battery_fallback: Mapping[str, Any]
    catcher_batter_distribution: Mapping[str, Any]
    feature_inventory: Sequence[Mapping[str, str]]
    premium_gaps: Sequence[Mapping[str, str]]
    decision: Mapping[str, Any]
    limitations: Sequence[str] = field(default_factory=tuple)

    def to_registry_payload(self, *, run_id: str, contract_sha: str) -> dict[str, Any]:
        return {
            "schemaVersion": CATCHER_READINESS_SCHEMA_VERSION,
            "contractName": CATCHER_READINESS_CONTRACT_NAME,
            "contractSha": contract_sha,
            "runId": run_id,
            "datasetAuthority": dict(self.dataset_authority),
            "identityBridgeAuthority": dict(self.identity_bridge_authority),
            "seasons": list(self.seasons),
            "primaryModelingSeasons": list(PRIMARY_MODELING_SEASONS),
            "startingCatcherCoverage": dict(self.starting_catcher_coverage),
            "paCatcherAssignmentCoverage": dict(self.pa_assignment_coverage),
            "batterySampleDistribution": dict(self.battery_distribution),
            "batteryFallbackLevels": dict(self.battery_fallback),
            "catcherBatterSampleDistribution": dict(self.catcher_batter_distribution),
            "freeFeatureInventory": [dict(item) for item in self.feature_inventory],
            "premiumDataGaps": [dict(item) for item in self.premium_gaps],
            "futureModelDesign": future_model_design(),
            "decision": dict(self.decision),
            "terminalStatus": self.decision.get("status"),
            "limitations": list(self.limitations),
        }


DEFAULT_LIMITATIONS: tuple[str, ...] = (
    "This is a data-availability audit, not a catcher predictive model; no catcher "
    "effect is estimated or proven.",
    "Catcher identity is reconstructed from defensive appearances and (where present) "
    "in-game substitution events; ambiguous or missing intervals are reported, never "
    "forward-filled.",
    "No pitch caller, framing, pitch location/target, or tracking metric is claimed; "
    "those require premium/new sources (see premiumDataGaps).",
    "Stolen bases, passed balls, and wild pitches are catcher-observable events, not "
    "proof of catcher causal responsibility.",
    "Readiness thresholds are defensible availability gates, not proven-optimal "
    "modeling thresholds.",
)


__all__ = [
    "AUDIT_SEASONS",
    "BATTERY_FALLBACK_LEVELS",
    "CATCHER_POSITION_CODES",
    "CATCHER_READINESS_CONTRACT_NAME",
    "CATCHER_READINESS_SCHEMA_VERSION",
    "CatcherReadinessAudit",
    "CatcherReadinessError",
    "CatcherSubstitution",
    "DEFAULT_LIMITATIONS",
    "FieldingAppearance",
    "PRIMARY_MODELING_SEASONS",
    "PlateAppearanceCatcher",
    "PlateAppearanceRow",
    "SAMPLE_SIZE_BANDS",
    "TERMINAL_STATUSES",
    "TeamGameCatcher",
    "assign_catcher_at_plate_appearances",
    "battery_fallback_distribution",
    "decide_readiness",
    "free_feature_inventory",
    "future_model_design",
    "pa_assignment_coverage",
    "premium_gap_inventory",
    "prior_pair_sample_distribution",
    "reconstruct_starting_catchers",
    "starting_catcher_coverage",
]
