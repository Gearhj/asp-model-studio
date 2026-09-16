"""Frozen Phase 7B2 Gold V1 feature and research-experiment contracts.

Gold V1 is a derived, research-only plate-appearance view.  Its first 22
predictors are the accepted Gen-3 base predictors in their exact existing
order.  The remaining 26 predictors are deliberately bounded to information
that is either:

* aggregated from games on dates strictly before the target game date; or
* handedness context known for the target plate appearance before it begins.

The Gold view contains target seasons 2021-2024 only.  Historical Silver rows
from 2019-2024 may contribute to a prior-day aggregate, but they are not Gold
target rows.  Seasons 2025 and 2026 are never part of this contract.

The current Phase 7B1 Silver V1 pitch schema does not retain exit velocity or a
governed barrel field.  Gold V1 therefore does not fabricate exit-velocity,
hard-hit, or barrel predictors.  Adding them requires a new immutable Silver
schema/object version and a new Gold contract identity.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_modeling.feature_contract import FEATURE_NAMES as _ACCEPTED_BASE_FEATURES
from ..sports_modeling.metrics import PA_CLASS_ORDER as _PA_CLASS_ORDER


GOLD_CONTRACT_NAME = "MLB_ADVANCED_PA_FEATURE_VIEW"
GOLD_CONTRACT_VERSION = "MLB_ADVANCED_PA_FEATURE_VIEW_V1"
GOLD_CONTRACT_SCHEMA_VERSION = "MLB_GOLD_FEATURE_CONTRACT_V1"
GOLD_FEATURE_SCHEMA_VERSION = "MLB_ADVANCED_PA_FEATURE_SCHEMA_V1"

# Gold target rows and the controlled experiment split.  The order is part of
# the contract, rather than merely a set-membership statement.
GOLD_TARGET_SEASONS: tuple[int, ...] = (2021, 2022, 2023, 2024)
DEVELOPMENT_SEASONS: tuple[int, ...] = (2021, 2022, 2023)
VALIDATION_SEASON = 2024
SEALED_OR_PROSPECTIVE_SEASONS: tuple[int, ...] = (2025, 2026)

# Earlier Silver facts may seed 2021 histories.  This is source lineage, not an
# authorization to create 2019/2020 Gold target rows.
HISTORY_SOURCE_SEASONS: tuple[int, ...] = (2019, 2020, 2021, 2022, 2023, 2024)

EXPECTED_SEASON_ROWS: Mapping[int, int] = {
    2021: 181_752,
    2022: 181_979,
    2023: 184_104,
    2024: 182_449,
}
EXPECTED_DEVELOPMENT_ROWS = 547_835
EXPECTED_VALIDATION_ROWS = 182_449
EXPECTED_TOTAL_ROWS = 730_284

# Gold V1 contains only the exact, one-to-one Silver bridge population.  The
# difference from the governed target population is retained in the immutable
# reason-coded exclusion ledger rather than silently dropped.
EXPECTED_GOLD_SEASON_ROWS: Mapping[int, int] = {
    2021: 178_522,
    2022: 175_508,
    2023: 182_072,
    2024: 180_711,
}
EXPECTED_GOLD_DEVELOPMENT_ROWS = 536_102
EXPECTED_GOLD_VALIDATION_ROWS = 180_711
EXPECTED_GOLD_TOTAL_ROWS = 716_813
EXPECTED_EXCLUDED_ROWS = 13_471

GOLD_CLASS_ORDER: tuple[str, ...] = tuple(_PA_CLASS_ORDER)
BASE_FEATURE_NAMES: tuple[str, ...] = tuple(_ACCEPTED_BASE_FEATURES)

BATTER_HISTORY_WINDOW_PA = 100
PITCHER_HISTORY_WINDOW_BF = 250

BATTER_HISTORY_FEATURES: tuple[str, ...] = (
    "batter_prior_pa_count",
    "batter_last100_pa_count",
    "batter_last100_strikeout_rate",
    "batter_last100_walk_hbp_rate",
    "batter_last100_contact_rate",
    "batter_last100_whiff_rate",
    "batter_last100_insufficient",
    "batter_last100_whiff_missing",
)

PITCHER_HISTORY_FEATURES: tuple[str, ...] = (
    "pitcher_prior_bf_count",
    "pitcher_last250_bf_count",
    "pitcher_last250_strikeout_rate",
    "pitcher_last250_walk_rate",
    "pitcher_last250_whiff_rate",
    "pitcher_last250_avg_fastball_velocity",
    "pitcher_last250_fastball_usage",
    "pitcher_last250_breaking_usage",
    "pitcher_last250_offspeed_usage",
    "pitcher_last250_insufficient",
    "pitcher_last250_whiff_missing",
    "pitcher_last250_velocity_missing",
)

MATCHUP_FEATURES: tuple[str, ...] = (
    "matchup_batter_bats_left",
    "matchup_batter_bats_switch",
    "matchup_batter_hand_missing",
    "matchup_pitcher_throws_left",
    "matchup_pitcher_hand_missing",
    "matchup_platoon_advantage",
)

ADVANCED_FEATURE_NAMES: tuple[str, ...] = (
    *BATTER_HISTORY_FEATURES,
    *PITCHER_HISTORY_FEATURES,
    *MATCHUP_FEATURES,
)
GOLD_FEATURE_NAMES: tuple[str, ...] = (*BASE_FEATURE_NAMES, *ADVANCED_FEATURE_NAMES)

# Stable public vocabulary used by the Gold builder/model suite.  Keep the
# *_NAMES forms above for consistency with the accepted base contract, while
# exporting the shorter exact names expected by Phase 7B2 consumers.
ADVANCED_FEATURES: tuple[str, ...] = ADVANCED_FEATURE_NAMES
GOLD_FEATURES: tuple[str, ...] = GOLD_FEATURE_NAMES

BASE_FEATURE_COUNT = 22
ADVANCED_FEATURE_COUNT = 26
GOLD_FEATURE_COUNT = 48

# The controlled Gold experiment may fit research challengers.  These flags do
# not make Gold a production/champion authority and do not alter Silver's
# existing QUARANTINED / NOT_MODEL_ELIGIBLE state.
RESEARCH_ONLY_FLAGS: Mapping[str, Any] = {
    "status": "RESEARCH_ONLY",
    "researchOnly": True,
    "researchModelEligible": True,
    "controlledResearchTrainingEligible": True,
    "productionSelectable": False,
    "approvedForProduction": False,
    "promotionEligible": False,
    "championEligible": False,
}
GOLD_GOVERNANCE: Mapping[str, Any] = RESEARCH_ONLY_FLAGS

HISTORY_CUTOFF = (
    "source.gameDate < target.game_date; the source calendar day must be complete; "
    "the target PA, every other PA on the target date (including doubleheaders), "
    "and every future PA are excluded"
)
MATCHUP_CUTOFF = (
    "target-PA handedness is resolved before the target plate appearance begins; "
    "no pitch result or target outcome is used"
)

# Frozen pitch-result vocabulary for contact/whiff aggregates.  Unrecognized or
# missing values never silently become contact or a whiff.
WHIFF_PITCH_RESULTS: tuple[str, ...] = (
    "swinging_strike",
    "swinging_strike_blocked",
    "missed_bunt",
)
CONTACT_PITCH_RESULTS: tuple[str, ...] = (
    "foul",
    "foul_bunt",
    "foul_tip",
    "hit_into_play",
    "hit_into_play_no_out",
    "hit_into_play_score",
)
SWING_PITCH_RESULTS: tuple[str, ...] = WHIFF_PITCH_RESULTS + CONTACT_PITCH_RESULTS

# Frozen pitch grouping.  Unsupported/missing types remain outside the three
# numerators but stay in the all-pitch usage denominator, so the three reported
# shares may sum to less than one rather than fabricating a classification.
FASTBALL_PITCH_TYPES: tuple[str, ...] = ("FA", "FF", "FC", "SI")
BREAKING_PITCH_TYPES: tuple[str, ...] = ("CU", "KC", "CS", "SL", "ST", "SV")
OFFSPEED_PITCH_TYPES: tuple[str, ...] = ("CH", "FS", "FO", "SC", "KN", "EP")


def _spec(
    *,
    family: str,
    tables: Sequence[str],
    fields: Sequence[str],
    calculation: str,
    window: str,
    cutoff: str,
    missing: str,
) -> dict[str, Any]:
    return {
        "family": family,
        "dtype": "float64",
        "source": {"tables": list(tables), "fields": list(fields)},
        "calculation": calculation,
        "window": window,
        "cutoff": cutoff,
        "missing": missing,
        "knowledgeTimeClass": (
            "HISTORICAL_COMPLETED_DAY" if cutoff == HISTORY_CUTOFF else "TARGET_PRE_PA_CONTEXT"
        ),
    }


_PA_SOURCE = "fact_statcast_plate_appearance"
_PITCH_SOURCE = "fact_statcast_pitch"
_BATTER_ALL_PRIOR = "all resolved PAs for the same canonical batter on completed prior dates"
_BATTER_LAST100 = "last min(100, prior PA count) resolved PAs for the same canonical batter"
_PITCHER_ALL_PRIOR = "all resolved batters faced by the same canonical pitcher on completed prior dates"
_PITCHER_LAST250 = "last min(250, prior BF count) resolved batters faced by the same canonical pitcher"


ADVANCED_FEATURE_SPECS: Mapping[str, Mapping[str, Any]] = {
    "batter_prior_pa_count": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("batterCanonicalPlayerId", "canonicalPaId", "gameDate"),
        calculation="count distinct canonicalPaId for the target batter after applying the strict prior-day cutoff",
        window=_BATTER_ALL_PRIOR,
        cutoff=HISTORY_CUTOFF,
        missing="0.0 when no eligible prior PA exists; this is an observed empty history, not an imputed rate",
    ),
    "batter_last100_pa_count": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("batterCanonicalPlayerId", "canonicalPaId", "gameDate"),
        calculation="min(100, batter_prior_pa_count)",
        window=_BATTER_LAST100,
        cutoff=HISTORY_CUTOFF,
        missing="0.0 when no eligible prior PA exists",
    ),
    "batter_last100_strikeout_rate": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("batterCanonicalPlayerId", "canonicalPaId", "gameDate", "paEvent"),
        calculation=(
            "count(paEvent in {strikeout, strikeout_double_play}) divided by batter_last100_pa_count"
        ),
        window=_BATTER_LAST100,
        cutoff=HISTORY_CUTOFF,
        missing="null when batter_last100_pa_count is zero; never filled from a later date",
    ),
    "batter_last100_walk_hbp_rate": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("batterCanonicalPlayerId", "canonicalPaId", "gameDate", "paEvent"),
        calculation=(
            "count(paEvent in {walk, intent_walk, hit_by_pitch}) divided by batter_last100_pa_count"
        ),
        window=_BATTER_LAST100,
        cutoff=HISTORY_CUTOFF,
        missing="null when batter_last100_pa_count is zero; never filled from a later date",
    ),
    "batter_last100_contact_rate": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=(
            "batterCanonicalPlayerId",
            "canonicalPaId",
            "gameDate",
            "pitchResultType",
        ),
        calculation=(
            "classified contact pitches / classified swing pitches, using the frozen "
            "CONTACT_PITCH_RESULTS and SWING_PITCH_RESULTS vocabularies"
        ),
        window=_BATTER_LAST100,
        cutoff=HISTORY_CUTOFF,
        missing="null when the window contains zero classifiable swings; batter_last100_whiff_missing=1",
    ),
    "batter_last100_whiff_rate": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=(
            "batterCanonicalPlayerId",
            "canonicalPaId",
            "gameDate",
            "pitchResultType",
        ),
        calculation=(
            "classified whiff pitches / classified swing pitches, using the frozen "
            "WHIFF_PITCH_RESULTS and SWING_PITCH_RESULTS vocabularies"
        ),
        window=_BATTER_LAST100,
        cutoff=HISTORY_CUTOFF,
        missing="null when the window contains zero classifiable swings; batter_last100_whiff_missing=1",
    ),
    "batter_last100_insufficient": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("batterCanonicalPlayerId", "canonicalPaId", "gameDate"),
        calculation="1.0 when batter_last100_pa_count < 100, otherwise 0.0",
        window=_BATTER_LAST100,
        cutoff=HISTORY_CUTOFF,
        missing="never null; an empty history is explicitly insufficient",
    ),
    "batter_last100_whiff_missing": _spec(
        family="batter_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=("batterCanonicalPlayerId", "canonicalPaId", "gameDate", "pitchResultType"),
        calculation="1.0 when the last-100-PA window contains zero classifiable swings, otherwise 0.0",
        window=_BATTER_LAST100,
        cutoff=HISTORY_CUTOFF,
        missing="never null; it is the missingness indicator for both contact and whiff rates",
    ),
    "pitcher_prior_bf_count": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate"),
        calculation="count distinct canonicalPaId for the target pitcher after applying the strict prior-day cutoff",
        window=_PITCHER_ALL_PRIOR,
        cutoff=HISTORY_CUTOFF,
        missing="0.0 when no eligible prior BF exists; this is an observed empty history",
    ),
    "pitcher_last250_bf_count": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate"),
        calculation="min(250, pitcher_prior_bf_count)",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="0.0 when no eligible prior BF exists",
    ),
    "pitcher_last250_strikeout_rate": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate", "paEvent"),
        calculation=(
            "count(paEvent in {strikeout, strikeout_double_play}) divided by pitcher_last250_bf_count"
        ),
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="null when pitcher_last250_bf_count is zero; never filled from a later date",
    ),
    "pitcher_last250_walk_rate": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate", "paEvent"),
        calculation="count(paEvent in {walk, intent_walk}) divided by pitcher_last250_bf_count",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="null when pitcher_last250_bf_count is zero; hit-by-pitch is not counted as a walk",
    ),
    "pitcher_last250_whiff_rate": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=(
            "pitcherCanonicalPlayerId",
            "canonicalPaId",
            "gameDate",
            "pitchResultType",
        ),
        calculation=(
            "classified whiff pitches / classified swing pitches, using the frozen "
            "WHIFF_PITCH_RESULTS and SWING_PITCH_RESULTS vocabularies"
        ),
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="null for zero classifiable swings; pitcher_last250_whiff_missing=1",
    ),
    "pitcher_last250_avg_fastball_velocity": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=(
            "pitcherCanonicalPlayerId",
            "canonicalPaId",
            "gameDate",
            "pitchType",
            "releaseSpeed",
        ),
        calculation=(
            "arithmetic mean of finite releaseSpeed for pitches whose pitchType is in "
            "FASTBALL_PITCH_TYPES"
        ),
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="null when no eligible fastball has finite releaseSpeed; pitcher_last250_velocity_missing=1",
    ),
    "pitcher_last250_fastball_usage": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate", "pitchType"),
        calculation="count(pitchType in FASTBALL_PITCH_TYPES) divided by all pitch rows in the BF window",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="null when the BF window contains zero pitch rows; unsupported/missing types remain in the denominator",
    ),
    "pitcher_last250_breaking_usage": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate", "pitchType"),
        calculation="count(pitchType in BREAKING_PITCH_TYPES) divided by all pitch rows in the BF window",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="null when the BF window contains zero pitch rows; unsupported/missing types remain in the denominator",
    ),
    "pitcher_last250_offspeed_usage": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate", "pitchType"),
        calculation="count(pitchType in OFFSPEED_PITCH_TYPES) divided by all pitch rows in the BF window",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="null when the BF window contains zero pitch rows; unsupported/missing types remain in the denominator",
    ),
    "pitcher_last250_insufficient": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE,),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate"),
        calculation="1.0 when pitcher_last250_bf_count < 250, otherwise 0.0",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="never null; an empty history is explicitly insufficient",
    ),
    "pitcher_last250_whiff_missing": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=("pitcherCanonicalPlayerId", "canonicalPaId", "gameDate", "pitchResultType"),
        calculation="1.0 when the BF window contains zero classifiable swings, otherwise 0.0",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="never null; it is the missingness indicator for pitcher_last250_whiff_rate",
    ),
    "pitcher_last250_velocity_missing": _spec(
        family="pitcher_completed_day_history",
        tables=(_PA_SOURCE, _PITCH_SOURCE),
        fields=(
            "pitcherCanonicalPlayerId",
            "canonicalPaId",
            "gameDate",
            "pitchType",
            "releaseSpeed",
        ),
        calculation="1.0 when no eligible fastball has finite releaseSpeed, otherwise 0.0",
        window=_PITCHER_LAST250,
        cutoff=HISTORY_CUTOFF,
        missing="never null; it is the missingness indicator for average fastball velocity",
    ),
    "matchup_batter_bats_left": _spec(
        family="target_pa_handedness_matchup",
        tables=(_PA_SOURCE,),
        fields=("canonicalPaId", "stand"),
        calculation="1.0 when normalized target-PA stand == 'L', otherwise 0.0",
        window="target PA pre-event context only",
        cutoff=MATCHUP_CUTOFF,
        missing="0.0 for missing/unknown stand; matchup_batter_hand_missing=1 disambiguates",
    ),
    "matchup_batter_bats_switch": _spec(
        family="target_pa_handedness_matchup",
        tables=(_PA_SOURCE,),
        fields=("canonicalPaId", "stand"),
        calculation="1.0 only when normalized target-PA stand explicitly equals 'S', otherwise 0.0",
        window="target PA pre-event context only",
        cutoff=MATCHUP_CUTOFF,
        missing="0.0 for missing/unknown stand; no switch status is inferred from names or future appearances",
    ),
    "matchup_batter_hand_missing": _spec(
        family="target_pa_handedness_matchup",
        tables=(_PA_SOURCE,),
        fields=("canonicalPaId", "stand"),
        calculation="1.0 when normalized target-PA stand is not one of {L, R, S}, otherwise 0.0",
        window="target PA pre-event context only",
        cutoff=MATCHUP_CUTOFF,
        missing="never null; it is the batter-hand missingness indicator",
    ),
    "matchup_pitcher_throws_left": _spec(
        family="target_pa_handedness_matchup",
        tables=(_PA_SOURCE,),
        fields=("canonicalPaId", "pThrows"),
        calculation="1.0 when normalized target-PA pThrows == 'L', otherwise 0.0",
        window="target PA pre-event context only",
        cutoff=MATCHUP_CUTOFF,
        missing="0.0 for missing/unknown pThrows; matchup_pitcher_hand_missing=1 disambiguates",
    ),
    "matchup_pitcher_hand_missing": _spec(
        family="target_pa_handedness_matchup",
        tables=(_PA_SOURCE,),
        fields=("canonicalPaId", "pThrows"),
        calculation="1.0 when normalized target-PA pThrows is not one of {L, R}, otherwise 0.0",
        window="target PA pre-event context only",
        cutoff=MATCHUP_CUTOFF,
        missing="never null; it is the pitcher-hand missingness indicator",
    ),
    "matchup_platoon_advantage": _spec(
        family="target_pa_handedness_matchup",
        tables=(_PA_SOURCE,),
        fields=("canonicalPaId", "stand", "pThrows"),
        calculation=(
            "when both hands are known: 1.0 for an explicit switch batter or for opposite-side "
            "batter/pitcher hands, otherwise 0.0"
        ),
        window="target PA pre-event context only",
        cutoff=MATCHUP_CUTOFF,
        missing=(
            "0.0 when either hand is missing; matchup_batter_hand_missing and "
            "matchup_pitcher_hand_missing disambiguate"
        ),
    ),
}
FEATURE_SPECIFICATION: Mapping[str, Mapping[str, Any]] = ADVANCED_FEATURE_SPECS
BASE_FEATURE_SPECIFICATION: Mapping[str, Mapping[str, Any]] = {
    name: {
        "family": "governed_base",
        "dtype": "governed Gen3 dtype",
        "source": {"tables": ["governedGen3Target"], "fields": [name]},
        "calculation": "copied unchanged from the verified governed Gen3 PA research view",
        "window": "existing governed base-feature contract",
        "cutoff": "existing governed pre-PA point-in-time semantics",
        "missing": "preserved from Gen3; fold-only preprocessing is learned on development rows",
        "knowledgeTimeClass": "GOVERNED_PRE_PA_BASE",
    }
    for name in BASE_FEATURE_NAMES
}

# These requested contact-quality concepts are intentionally absent from the
# 48-feature order.  Silver V1's bbType is not a substitute for any of them.
UNSUPPORTED_CONTACT_QUALITY_FEATURES: tuple[str, ...] = (
    "exit_velocity",
    "hard_hit_rate",
    "barrel_rate",
)
CONTACT_QUALITY_LIMITATION: Mapping[str, Any] = {
    "status": "UNSUPPORTED_BY_CURRENT_SILVER_V1",
    "features": list(UNSUPPORTED_CONTACT_QUALITY_FEATURES),
    "reason": (
        "Phase 7B1 Silver V1 does not retain launch_speed, launch_angle, "
        "launch_speed_angle, or another governed barrel indicator"
    ),
    "guardrail": (
        "Gold V1 must not infer, zero-fill, approximate, or relabel bbType as exit velocity, "
        "hard-hit, or barrel evidence"
    ),
    "futureRequirement": (
        "a new immutable Silver schema/object version with exact source lineage, followed by a new Gold contract"
    ),
}


class GoldContractError(ValueError):
    """Gold V1 constants or a caller-supplied contract view differ from authority."""


def validate_gold_contract(
    *,
    feature_order: Sequence[str] = GOLD_FEATURE_NAMES,
    seasons: Sequence[int] = GOLD_TARGET_SEASONS,
    class_order: Sequence[str] = GOLD_CLASS_ORDER,
    research_flags: Mapping[str, Any] = RESEARCH_ONLY_FLAGS,
) -> None:
    """Fail closed unless order, seasons, class order, specs, and status are exact."""

    observed_features = tuple(feature_order)
    if observed_features != GOLD_FEATURE_NAMES:
        raise GoldContractError("Gold feature order differs from the exact frozen 48-feature order")
    if observed_features[:BASE_FEATURE_COUNT] != BASE_FEATURE_NAMES:
        raise GoldContractError("Gold feature order does not preserve the accepted base-22 prefix")
    if len(BASE_FEATURE_NAMES) != BASE_FEATURE_COUNT:
        raise GoldContractError("accepted base feature authority no longer contains exactly 22 features")
    if len(ADVANCED_FEATURE_NAMES) != ADVANCED_FEATURE_COUNT or len(GOLD_FEATURE_NAMES) != GOLD_FEATURE_COUNT:
        raise GoldContractError("Gold feature counts must remain base=22, advanced=26, total=48")
    if len(set(GOLD_FEATURE_NAMES)) != GOLD_FEATURE_COUNT:
        raise GoldContractError("Gold feature order contains a duplicate feature")

    if tuple(seasons) != GOLD_TARGET_SEASONS:
        raise GoldContractError("Gold target seasons must be exactly ordered 2021, 2022, 2023, 2024")
    if any(season in tuple(seasons) for season in SEALED_OR_PROSPECTIVE_SEASONS):
        raise GoldContractError("Gold target seasons may never contain 2025 or 2026")
    if DEVELOPMENT_SEASONS != (2021, 2022, 2023) or VALIDATION_SEASON != 2024:
        raise GoldContractError("Gold development/validation split differs from the frozen contract")
    if set(EXPECTED_SEASON_ROWS) != set(GOLD_TARGET_SEASONS):
        raise GoldContractError("Gold expected row counts cover a season outside 2021-2024")
    if sum(EXPECTED_SEASON_ROWS[s] for s in DEVELOPMENT_SEASONS) != EXPECTED_DEVELOPMENT_ROWS:
        raise GoldContractError("Gold development row count does not reconcile")
    if EXPECTED_SEASON_ROWS[VALIDATION_SEASON] != EXPECTED_VALIDATION_ROWS:
        raise GoldContractError("Gold validation row count does not reconcile")
    if sum(EXPECTED_SEASON_ROWS.values()) != EXPECTED_TOTAL_ROWS:
        raise GoldContractError("Gold total row count does not reconcile")
    if set(EXPECTED_GOLD_SEASON_ROWS) != set(GOLD_TARGET_SEASONS):
        raise GoldContractError("Gold matched row counts cover a season outside 2021-2024")
    if sum(EXPECTED_GOLD_SEASON_ROWS[s] for s in DEVELOPMENT_SEASONS) != EXPECTED_GOLD_DEVELOPMENT_ROWS:
        raise GoldContractError("Gold matched development row count does not reconcile")
    if EXPECTED_GOLD_SEASON_ROWS[VALIDATION_SEASON] != EXPECTED_GOLD_VALIDATION_ROWS:
        raise GoldContractError("Gold matched validation row count does not reconcile")
    if sum(EXPECTED_GOLD_SEASON_ROWS.values()) != EXPECTED_GOLD_TOTAL_ROWS:
        raise GoldContractError("Gold matched total row count does not reconcile")
    if EXPECTED_TOTAL_ROWS - EXPECTED_GOLD_TOTAL_ROWS != EXPECTED_EXCLUDED_ROWS:
        raise GoldContractError("Gold matched and excluded populations do not reconcile to target")

    if tuple(class_order) != tuple(_PA_CLASS_ORDER):
        raise GoldContractError("Gold class order differs from the frozen eight-class PA authority")

    required_flags = {
        "status": "RESEARCH_ONLY",
        "researchOnly": True,
        "researchModelEligible": True,
        "controlledResearchTrainingEligible": True,
        "productionSelectable": False,
        "approvedForProduction": False,
        "promotionEligible": False,
        "championEligible": False,
    }
    for key, expected in required_flags.items():
        if research_flags.get(key) != expected:
            raise GoldContractError(f"Gold research-only flag {key!r} must equal {expected!r}")

    if tuple(ADVANCED_FEATURE_SPECS) != ADVANCED_FEATURE_NAMES:
        raise GoldContractError("advanced feature specs differ from the exact ordered advanced features")
    required_spec_fields = {
        "family",
        "dtype",
        "source",
        "calculation",
        "window",
        "cutoff",
        "missing",
        "knowledgeTimeClass",
    }
    for feature_id in ADVANCED_FEATURE_NAMES:
        spec = ADVANCED_FEATURE_SPECS[feature_id]
        if set(spec) != required_spec_fields:
            raise GoldContractError(f"{feature_id}: feature spec fields differ from the frozen contract")
        source = spec["source"]
        if not isinstance(source, Mapping) or not source.get("tables") or not source.get("fields"):
            raise GoldContractError(f"{feature_id}: feature source lineage is incomplete")
        for field in ("calculation", "window", "cutoff", "missing"):
            if not str(spec[field]).strip():
                raise GoldContractError(f"{feature_id}: {field} is empty")

    forbidden_names = set(UNSUPPORTED_CONTACT_QUALITY_FEATURES)
    if forbidden_names & set(GOLD_FEATURE_NAMES):
        raise GoldContractError("unsupported contact-quality features entered Gold V1")
    if CONTACT_QUALITY_LIMITATION.get("status") != "UNSUPPORTED_BY_CURRENT_SILVER_V1":
        raise GoldContractError("Gold V1 contact-quality limitation is missing")


def gold_contract_payload() -> dict[str, Any]:
    """Return the canonical, serialization-safe Gold V1 contract payload."""

    validate_gold_contract()
    return {
        "contract": GOLD_CONTRACT_NAME,
        "contractVersion": GOLD_CONTRACT_VERSION,
        "schemaVersion": GOLD_CONTRACT_SCHEMA_VERSION,
        "featureSchemaVersion": GOLD_FEATURE_SCHEMA_VERSION,
        "baseFeaturePrefix": list(BASE_FEATURE_NAMES),
        "advancedFeatureOrder": list(ADVANCED_FEATURE_NAMES),
        "exactFeatureOrder": list(GOLD_FEATURE_NAMES),
        "baseFeatureCount": BASE_FEATURE_COUNT,
        "advancedFeatureCount": ADVANCED_FEATURE_COUNT,
        "featureCount": GOLD_FEATURE_COUNT,
        "classOrder": list(GOLD_CLASS_ORDER),
        "targetSeasons": list(GOLD_TARGET_SEASONS),
        "historySourceSeasons": list(HISTORY_SOURCE_SEASONS),
        "developmentSeasons": list(DEVELOPMENT_SEASONS),
        "validationSeason": VALIDATION_SEASON,
        "sealedOrProspectiveSeasons": list(SEALED_OR_PROSPECTIVE_SEASONS),
        "expectedGovernedTargetSeasonRows": {
            str(k): int(v) for k, v in EXPECTED_SEASON_ROWS.items()
        },
        "expectedDevelopmentRows": EXPECTED_DEVELOPMENT_ROWS,
        "expectedValidationRows": EXPECTED_VALIDATION_ROWS,
        "expectedTotalRows": EXPECTED_TOTAL_ROWS,
        "expectedGoldSeasonRows": {
            str(k): int(v) for k, v in EXPECTED_GOLD_SEASON_ROWS.items()
        },
        "expectedGoldDevelopmentRows": EXPECTED_GOLD_DEVELOPMENT_ROWS,
        "expectedGoldValidationRows": EXPECTED_GOLD_VALIDATION_ROWS,
        "expectedGoldTotalRows": EXPECTED_GOLD_TOTAL_ROWS,
        "expectedExcludedRows": EXPECTED_EXCLUDED_ROWS,
        "historyCutoff": HISTORY_CUTOFF,
        "advancedFeatureSpecs": {
            feature_id: dict(ADVANCED_FEATURE_SPECS[feature_id])
            for feature_id in ADVANCED_FEATURE_NAMES
        },
        "baseFeatureSpecs": {
            feature_id: dict(BASE_FEATURE_SPECIFICATION[feature_id])
            for feature_id in BASE_FEATURE_NAMES
        },
        "pitchResultVocabularies": {
            "whiff": list(WHIFF_PITCH_RESULTS),
            "contact": list(CONTACT_PITCH_RESULTS),
            "swing": list(SWING_PITCH_RESULTS),
        },
        "pitchTypeGroups": {
            "fastball": list(FASTBALL_PITCH_TYPES),
            "breaking": list(BREAKING_PITCH_TYPES),
            "offspeed": list(OFFSPEED_PITCH_TYPES),
        },
        "researchState": dict(RESEARCH_ONLY_FLAGS),
        "limitations": [dict(CONTACT_QUALITY_LIMITATION)],
    }


def gold_contract_sha256() -> str:
    """Content identity of the complete canonical Gold V1 contract payload."""

    return sha256_bytes(canonical_json_bytes(gold_contract_payload()))


def _addressed_contract(name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(payload)
    digest = sha256_bytes(canonical_json_bytes(body))
    return {
        "id": f"{name}:sha256:{digest}",
        "sha256": digest,
        "payload": body,
    }


def gold_contract_bundle() -> dict[str, Any]:
    """Return independently addressed temporal/schema/target authorities.

    ``bundleSha256`` binds the exact component names and component digests.  A
    consumer can therefore verify one component and the bundle without relying
    on an unversioned Python constant or caller-supplied feature order.
    """

    validate_gold_contract()
    temporal = _addressed_contract(
        "MLB_GOLD_TEMPORAL_CONTRACT_V1",
        {
            "contractVersion": "MLB_GOLD_TEMPORAL_CONTRACT_V1",
            "targetSeasons": list(GOLD_TARGET_SEASONS),
            "historySourceSeasons": list(HISTORY_SOURCE_SEASONS),
            "developmentSeasons": list(DEVELOPMENT_SEASONS),
            "validationSeason": VALIDATION_SEASON,
            "sealedOrProspectiveSeasons": list(SEALED_OR_PROSPECTIVE_SEASONS),
            "historyCutoff": HISTORY_CUTOFF,
            "sameDayEvidenceEligible": False,
            "expectedGovernedTargetSeasonRows": {
                str(k): int(v) for k, v in EXPECTED_SEASON_ROWS.items()
            },
            "expectedGoldSeasonRows": {
                str(k): int(v) for k, v in EXPECTED_GOLD_SEASON_ROWS.items()
            },
            "expectedGoldTotalRows": EXPECTED_GOLD_TOTAL_ROWS,
            "expectedExcludedRows": EXPECTED_EXCLUDED_ROWS,
        },
    )
    feature_schema = _addressed_contract(
        GOLD_FEATURE_SCHEMA_VERSION,
        {
            "contractVersion": GOLD_FEATURE_SCHEMA_VERSION,
            "goldContractSha256": gold_contract_sha256(),
            "baseFeaturePrefix": list(BASE_FEATURE_NAMES),
            "advancedFeatureOrder": list(ADVANCED_FEATURES),
            "exactFeatureOrder": list(GOLD_FEATURES),
            "featureCount": GOLD_FEATURE_COUNT,
            "advancedFeatureSpecs": {
                feature_id: dict(FEATURE_SPECIFICATION[feature_id])
                for feature_id in ADVANCED_FEATURES
            },
            "baseFeatureSpecs": {
                feature_id: dict(BASE_FEATURE_SPECIFICATION[feature_id])
                for feature_id in BASE_FEATURE_NAMES
            },
            "unsupportedContactQuality": dict(CONTACT_QUALITY_LIMITATION),
        },
    )
    target = _addressed_contract(
        "MLB_GOLD_TARGET_CONTRACT_V1",
        {
            "contractVersion": "MLB_GOLD_TARGET_CONTRACT_V1",
            "targetColumn": "outcome",
            "problemType": "MULTICLASS_CLASSIFICATION",
            "classOrder": list(GOLD_CLASS_ORDER),
            "classCount": len(GOLD_CLASS_ORDER),
            "targetExcludedFromPredictors": True,
        },
    )
    governance = _addressed_contract(
        "MLB_GOLD_GOVERNANCE_CONTRACT_V1",
        {
            "contractVersion": "MLB_GOLD_GOVERNANCE_CONTRACT_V1",
            **dict(GOLD_GOVERNANCE),
            "silverGovernanceUnchanged": True,
        },
    )
    components = {
        "temporal": temporal,
        "featureSchema": feature_schema,
        "target": target,
        "governance": governance,
    }
    bundle_sha = sha256_bytes(
        canonical_json_bytes({name: item["sha256"] for name, item in sorted(components.items())})
    )
    return {**components, "bundleSha256": bundle_sha}


# Import-time self-check: a dependency change that reorders or expands the
# accepted base authority cannot silently change Gold V1.
validate_gold_contract()


__all__ = [
    "ADVANCED_FEATURE_COUNT",
    "ADVANCED_FEATURES",
    "ADVANCED_FEATURE_NAMES",
    "ADVANCED_FEATURE_SPECS",
    "BASE_FEATURE_COUNT",
    "BASE_FEATURE_NAMES",
    "BASE_FEATURE_SPECIFICATION",
    "BATTER_HISTORY_FEATURES",
    "BATTER_HISTORY_WINDOW_PA",
    "BREAKING_PITCH_TYPES",
    "CONTACT_PITCH_RESULTS",
    "CONTACT_QUALITY_LIMITATION",
    "DEVELOPMENT_SEASONS",
    "EXPECTED_DEVELOPMENT_ROWS",
    "EXPECTED_EXCLUDED_ROWS",
    "EXPECTED_GOLD_DEVELOPMENT_ROWS",
    "EXPECTED_GOLD_SEASON_ROWS",
    "EXPECTED_GOLD_TOTAL_ROWS",
    "EXPECTED_GOLD_VALIDATION_ROWS",
    "EXPECTED_SEASON_ROWS",
    "EXPECTED_TOTAL_ROWS",
    "EXPECTED_VALIDATION_ROWS",
    "FASTBALL_PITCH_TYPES",
    "FEATURE_SPECIFICATION",
    "GOLD_CLASS_ORDER",
    "GOLD_CONTRACT_NAME",
    "GOLD_CONTRACT_SCHEMA_VERSION",
    "GOLD_CONTRACT_VERSION",
    "GOLD_FEATURE_COUNT",
    "GOLD_FEATURES",
    "GOLD_FEATURE_NAMES",
    "GOLD_FEATURE_SCHEMA_VERSION",
    "GOLD_GOVERNANCE",
    "GOLD_TARGET_SEASONS",
    "GoldContractError",
    "HISTORY_CUTOFF",
    "HISTORY_SOURCE_SEASONS",
    "MATCHUP_CUTOFF",
    "MATCHUP_FEATURES",
    "OFFSPEED_PITCH_TYPES",
    "PITCHER_HISTORY_FEATURES",
    "PITCHER_HISTORY_WINDOW_BF",
    "RESEARCH_ONLY_FLAGS",
    "SEALED_OR_PROSPECTIVE_SEASONS",
    "SWING_PITCH_RESULTS",
    "UNSUPPORTED_CONTACT_QUALITY_FEATURES",
    "VALIDATION_SEASON",
    "WHIFF_PITCH_RESULTS",
    "gold_contract_payload",
    "gold_contract_bundle",
    "gold_contract_sha256",
    "validate_gold_contract",
]
