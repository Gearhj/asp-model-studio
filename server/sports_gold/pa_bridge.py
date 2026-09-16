"""Deterministic, fail-closed Gen-3 target-to-Silver PA bridge.

The bridge deliberately uses no outcome column.  It resolves the two source
identity systems, groups rows by the shared pre-terminal identity/context key,
and pairs rows by source order *only* when both sources contain the same number
of rows for that key.  Every target row that cannot satisfy those invariants is
reported as an exclusion; no fallback or fuzzy match is attempted.
"""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Integral
import re
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd


DEVELOPMENT_SEASONS: tuple[int, ...] = (2021, 2022, 2023)
VALIDATION_SEASONS: tuple[int, ...] = (2024,)

_METHOD_VERSION = "MLB_GOLD_PA_BRIDGE_V1"
_TARGET_PA_RE = re.compile(r"^retrosheet:pa:([^:]+):([1-9][0-9]*)$")
_TARGET_GAME_RE = re.compile(r"^retrosheet:game:([^:]+)$")
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")
_NONNEGATIVE_INTEGER_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_YEAR_RE = re.compile(r"^[0-9]{4}$")
_PLAYER_EXACT_STATUSES = frozenset(("EXACT", "MATCHED_EXACT"))

_KEY_COLUMNS: tuple[str, ...] = (
    "canonicalGameId",
    "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId",
    "inning",
    "topBottom",
)

_MATCHED_COLUMNS: tuple[str, ...] = (
    "plate_appearance_id",
    "game_id",
    "retrosheetGameId",
    "canonicalPaId",
    "canonicalGameId",
    "season",
    "batter_canonical_player_uuid",
    "pitcher_canonical_player_uuid",
    "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId",
    "inning",
    "topBottom",
    "targetOrder",
    "silverAtBatNumber",
    "occurrenceOrdinal",
    "occurrenceResolved",
    "split",
)

_EXCLUSION_COLUMNS: tuple[str, ...] = (
    "plate_appearance_id",
    "game_id",
    "season",
    "reasonCode",
    "reasonDetail",
    "canonicalGameId",
    "targetGroupCount",
    "silverGroupCount",
    "split",
)


class PaBridgeIntegrityError(ValueError):
    """Raised when an input authority is structurally unsafe to consume."""


@dataclass(frozen=True, slots=True)
class PaBridgeResult:
    """The accepted bridge, fail-closed target exclusions, and reconciliation."""

    matched: pd.DataFrame
    exclusions: pd.DataFrame
    report: Mapping[str, Any]


def _require_columns(frame: pd.DataFrame, required: Iterable[str], *, label: str) -> None:
    if not isinstance(frame, pd.DataFrame):
        raise PaBridgeIntegrityError(f"{label} must be a pandas DataFrame")
    missing = sorted(set(required) - set(frame.columns))
    if missing:
        raise PaBridgeIntegrityError(f"{label} missing required columns: {missing}")


def _nonempty_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value if value and value == value.strip() else None


def _strict_positive_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        parsed = int(value)
        return parsed if parsed > 0 else None
    if isinstance(value, str) and _POSITIVE_INTEGER_RE.fullmatch(value):
        return int(value)
    return None


def _strict_nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        parsed = int(value)
        return parsed if parsed >= 0 else None
    if isinstance(value, str) and _NONNEGATIVE_INTEGER_RE.fullmatch(value):
        return int(value)
    return None


def _strict_year(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        parsed = int(value)
        return parsed if 1000 <= parsed <= 9999 else None
    if isinstance(value, str) and _YEAR_RE.fullmatch(value):
        return int(value)
    return None


def _target_half(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, Integral) and int(value) in (0, 1):
        return int(value)
    if value in ("0", "1"):
        return int(value)
    return None


def _silver_half(value: Any) -> int | None:
    if value == "Top":
        return 0
    if value == "Bot":
        return 1
    return None


def _split_name(
    season: int | None,
    development_seasons: frozenset[int],
    validation_seasons: frozenset[int],
) -> str:
    if season in development_seasons:
        return "DEVELOPMENT"
    if season in validation_seasons:
        return "VALIDATION"
    return "OUT_OF_SCOPE"


def _verified_game_map(game_crosswalk: pd.DataFrame) -> dict[str, str]:
    required = ("retrosheetGameId", "canonicalGameId", "resolutionStatus")
    _require_columns(game_crosswalk, required, label="game_crosswalk")
    exact = game_crosswalk.loc[
        game_crosswalk["resolutionStatus"].eq("MATCHED_EXACT"), required
    ].copy()
    valid = exact["retrosheetGameId"].map(_nonempty_string).notna() & exact[
        "canonicalGameId"
    ].map(_nonempty_string).notna()
    if not bool(valid.all()):
        raise PaBridgeIntegrityError("MATCHED_EXACT game crosswalk rows contain null/invalid IDs")
    if bool(exact["retrosheetGameId"].duplicated().any()):
        raise PaBridgeIntegrityError("game crosswalk has duplicate exact Retrosheet game IDs")
    if bool(exact["canonicalGameId"].duplicated().any()):
        raise PaBridgeIntegrityError("game crosswalk has duplicate exact canonical game IDs")
    return dict(zip(exact["retrosheetGameId"], exact["canonicalGameId"], strict=True))


def _verified_player_map(player_crosswalk: pd.DataFrame) -> dict[str, str]:
    required = ("chadwickKeyUuid", "canonicalPlayerId")
    _require_columns(player_crosswalk, required, label="player_crosswalk")
    rows = player_crosswalk.loc[:, required].copy()
    # ``dim_player`` carries the authoritative resolution state.  Also accept an
    # already-verified two-column projection so the pure core remains convenient
    # for hermetic tests.
    if "resolutionStatus" in player_crosswalk.columns:
        rows = rows.loc[
            player_crosswalk["resolutionStatus"].isin(_PLAYER_EXACT_STATUSES)
        ].copy()
    valid = rows["chadwickKeyUuid"].map(_nonempty_string).notna() & rows[
        "canonicalPlayerId"
    ].map(_nonempty_string).notna()
    if not bool(valid.all()):
        raise PaBridgeIntegrityError("player crosswalk contains null/invalid IDs")
    if bool(rows["chadwickKeyUuid"].duplicated().any()):
        raise PaBridgeIntegrityError("player crosswalk has duplicate Chadwick UUIDs")
    if bool(rows["canonicalPlayerId"].duplicated().any()):
        raise PaBridgeIntegrityError("player crosswalk has duplicate canonical player IDs")
    return dict(zip(rows["chadwickKeyUuid"], rows["canonicalPlayerId"], strict=True))


def _exclusion(
    *,
    plate_appearance_id: Any,
    game_id: Any,
    season: int | None,
    reason_code: str,
    reason_detail: str,
    split: str,
    canonical_game_id: str | None = None,
    target_group_count: int | None = None,
    silver_group_count: int | None = None,
) -> dict[str, Any]:
    return {
        "plate_appearance_id": plate_appearance_id,
        "game_id": game_id,
        "season": season,
        "reasonCode": reason_code,
        "reasonDetail": reason_detail,
        "canonicalGameId": canonical_game_id,
        "targetGroupCount": target_group_count,
        "silverGroupCount": silver_group_count,
        "split": split,
    }


def _prepare_targets(
    targets: pd.DataFrame,
    *,
    game_map: Mapping[str, str],
    player_map: Mapping[str, str],
    development_seasons: frozenset[int],
    validation_seasons: frozenset[int],
) -> tuple[pd.DataFrame, list[dict[str, Any]], list[int | None]]:
    required = (
        "plate_appearance_id",
        "game_id",
        "season",
        "batter_canonical_player_uuid",
        "pitcher_canonical_player_uuid",
        "context_inning",
        "context_top_bottom",
    )
    _require_columns(targets, required, label="targets")
    source = targets.loc[:, required].reset_index(drop=True)
    if bool(source["plate_appearance_id"].duplicated().any()):
        raise PaBridgeIntegrityError("targets contain duplicate plate_appearance_id values")

    prepared: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    input_seasons: list[int | None] = []
    for row in source.itertuples(index=False, name=None):
        (
            pa_id,
            game_id,
            raw_season,
            batter_uuid,
            pitcher_uuid,
            raw_inning,
            raw_half,
        ) = row
        season = _strict_year(raw_season)
        input_seasons.append(season)
        split = _split_name(season, development_seasons, validation_seasons)
        pa_match = _TARGET_PA_RE.fullmatch(pa_id) if isinstance(pa_id, str) else None
        game_match = _TARGET_GAME_RE.fullmatch(game_id) if isinstance(game_id, str) else None
        if season is None:
            exclusions.append(
                _exclusion(
                    plate_appearance_id=pa_id,
                    game_id=game_id,
                    season=None,
                    reason_code="TARGET_SEASON_INVALID",
                    reason_detail="season is not a canonical four-digit integer",
                    split=split,
                )
            )
            continue
        if pa_match is None or game_match is None or pa_match.group(1) != game_match.group(1):
            exclusions.append(
                _exclusion(
                    plate_appearance_id=pa_id,
                    game_id=game_id,
                    season=season,
                    reason_code="TARGET_LINEAGE_INVALID",
                    reason_detail="Retrosheet PA/game IDs are malformed or disagree",
                    split=split,
                )
            )
            continue
        retrosheet_game_id = pa_match.group(1)
        target_order = _strict_positive_integer(pa_match.group(2))
        inning = _strict_positive_integer(raw_inning)
        half = _target_half(raw_half)
        if target_order is None or inning is None or half is None:
            exclusions.append(
                _exclusion(
                    plate_appearance_id=pa_id,
                    game_id=game_id,
                    season=season,
                    reason_code="TARGET_ORDER_OR_CONTEXT_INVALID",
                    reason_detail="PA suffix, inning, or half is outside the strict typed contract",
                    split=split,
                )
            )
            continue
        canonical_game_id = game_map.get(retrosheet_game_id)
        if canonical_game_id is None:
            exclusions.append(
                _exclusion(
                    plate_appearance_id=pa_id,
                    game_id=game_id,
                    season=season,
                    reason_code="GAME_IDENTITY_UNMAPPED",
                    reason_detail="no MATCHED_EXACT Retrosheet-to-canonical game authority",
                    split=split,
                )
            )
            continue
        batter_uuid = _nonempty_string(batter_uuid)
        pitcher_uuid = _nonempty_string(pitcher_uuid)
        batter_id = player_map.get(batter_uuid) if batter_uuid is not None else None
        pitcher_id = player_map.get(pitcher_uuid) if pitcher_uuid is not None else None
        if batter_id is None or pitcher_id is None:
            missing_roles = ",".join(
                role
                for role, value in (("BATTER", batter_id), ("PITCHER", pitcher_id))
                if value is None
            )
            exclusions.append(
                _exclusion(
                    plate_appearance_id=pa_id,
                    game_id=game_id,
                    season=season,
                    reason_code="PLAYER_IDENTITY_UNMAPPED",
                    reason_detail=f"no exact canonical player authority for: {missing_roles}",
                    split=split,
                    canonical_game_id=canonical_game_id,
                )
            )
            continue
        prepared.append(
            {
                "plate_appearance_id": pa_id,
                "game_id": game_id,
                "retrosheetGameId": retrosheet_game_id,
                "season": season,
                "batter_canonical_player_uuid": batter_uuid,
                "pitcher_canonical_player_uuid": pitcher_uuid,
                "canonicalGameId": canonical_game_id,
                "batterCanonicalPlayerId": batter_id,
                "pitcherCanonicalPlayerId": pitcher_id,
                "inning": inning,
                "topBottom": half,
                "targetOrder": target_order,
                "split": split,
            }
        )

    frame = pd.DataFrame.from_records(prepared)
    if frame.empty:
        frame = pd.DataFrame(
            columns=(
                "plate_appearance_id",
                "game_id",
                "retrosheetGameId",
                "season",
                "batter_canonical_player_uuid",
                "pitcher_canonical_player_uuid",
                *_KEY_COLUMNS,
                "targetOrder",
                "split",
            )
        )
    duplicate_order = frame.duplicated([*_KEY_COLUMNS, "targetOrder"], keep=False)
    if bool(duplicate_order.any()):
        example = frame.loc[
            duplicate_order, [*_KEY_COLUMNS, "targetOrder"]
        ].iloc[0].to_dict()
        raise PaBridgeIntegrityError(
            f"targets contain duplicate source order inside a bridge key: {example}"
        )
    return frame, exclusions, input_seasons


def _prepare_silver(silver_pa: pd.DataFrame) -> pd.DataFrame:
    required = (
        "canonicalPaId",
        "canonicalGameId",
        "atBatNumber",
        "batterCanonicalPlayerId",
        "pitcherCanonicalPlayerId",
        "season",
        "inning",
        "inningTopBot",
    )
    _require_columns(silver_pa, required, label="silver_pa")
    source = silver_pa.loc[:, required].reset_index(drop=True)
    if bool(source["canonicalPaId"].duplicated().any()):
        raise PaBridgeIntegrityError("silver_pa contains duplicate canonicalPaId values")

    prepared: list[dict[str, Any]] = []
    for row_number, row in enumerate(source.itertuples(index=False, name=None)):
        (
            canonical_pa_id,
            canonical_game_id,
            raw_order,
            batter_id,
            pitcher_id,
            raw_season,
            raw_inning,
            raw_half,
        ) = row
        canonical_pa_id = _nonempty_string(canonical_pa_id)
        canonical_game_id = _nonempty_string(canonical_game_id)
        batter_id = _nonempty_string(batter_id)
        pitcher_id = _nonempty_string(pitcher_id)
        # Statcast's at_bat_number is a zero-based source order.  Retrosheet's
        # target PA suffix remains independently constrained to positive 1+.
        order = _strict_nonnegative_integer(raw_order)
        season = _strict_year(raw_season)
        inning = _strict_positive_integer(raw_inning)
        half = _silver_half(raw_half)
        if None in (
            canonical_pa_id,
            canonical_game_id,
            batter_id,
            pitcher_id,
            order,
            season,
            inning,
            half,
        ):
            raise PaBridgeIntegrityError(
                f"silver_pa row {row_number} violates the typed identity/order/context contract"
            )
        prepared.append(
            {
                "canonicalPaId": canonical_pa_id,
                "canonicalGameId": canonical_game_id,
                "batterCanonicalPlayerId": batter_id,
                "pitcherCanonicalPlayerId": pitcher_id,
                "silverSeason": season,
                "inning": inning,
                "topBottom": half,
                "silverAtBatNumber": order,
            }
        )

    frame = pd.DataFrame.from_records(prepared)
    if frame.empty:
        frame = pd.DataFrame(
            columns=(
                "canonicalPaId",
                *_KEY_COLUMNS,
                "silverSeason",
                "silverAtBatNumber",
            )
        )
    duplicate_order = frame.duplicated([*_KEY_COLUMNS, "silverAtBatNumber"], keep=False)
    if bool(duplicate_order.any()):
        example = frame.loc[
            duplicate_order, [*_KEY_COLUMNS, "silverAtBatNumber"]
        ].iloc[0].to_dict()
        raise PaBridgeIntegrityError(
            f"silver_pa contains duplicate source order inside a bridge key: {example}"
        )
    return frame


def _count_report(
    *,
    target_seasons: Sequence[int | None],
    matched: pd.DataFrame,
    exclusions: pd.DataFrame,
    silver_rows: int,
    development_seasons: tuple[int, ...],
    validation_seasons: tuple[int, ...],
) -> dict[str, Any]:
    def subset(seasons: frozenset[int]) -> dict[str, Any]:
        target_rows = sum(season in seasons for season in target_seasons)
        matched_rows = int(matched["season"].isin(seasons).sum()) if not matched.empty else 0
        excluded_rows = int(exclusions["season"].isin(seasons).sum()) if not exclusions.empty else 0
        occurrence_rows = (
            int(
                (
                    matched["season"].isin(seasons)
                    & matched["occurrenceResolved"].astype(bool)
                ).sum()
            )
            if not matched.empty
            else 0
        )
        return {
            "seasons": sorted(seasons),
            "targetRows": int(target_rows),
            "matchedRows": matched_rows,
            "excludedRows": excluded_rows,
            "naturallyUniqueRows": matched_rows - occurrence_rows,
            "occurrenceResolvedRows": occurrence_rows,
            "postOrdinalAmbiguousRows": 0,
        }

    parsed_seasons = sorted({season for season in target_seasons if season is not None})
    per_season: dict[str, Any] = {}
    for season in parsed_seasons:
        per_season[str(season)] = subset(frozenset((season,)))
    unknown_rows = sum(season is None for season in target_seasons)
    if unknown_rows:
        per_season["UNKNOWN"] = {
            "targetRows": int(unknown_rows),
            "matchedRows": 0,
            "excludedRows": int(exclusions["season"].isna().sum()),
            "naturallyUniqueRows": 0,
            "occurrenceResolvedRows": 0,
            "postOrdinalAmbiguousRows": 0,
        }

    duplicate_rows = int(matched.duplicated().sum())
    duplicate_target_ids = int(matched["plate_appearance_id"].duplicated().sum())
    duplicate_silver_ids = int(matched["canonicalPaId"].duplicated().sum())
    if duplicate_rows or duplicate_target_ids or duplicate_silver_ids:
        raise PaBridgeIntegrityError("bridge output contains duplicate source or Silver PA identities")
    reason_counts = (
        {str(key): int(value) for key, value in exclusions["reasonCode"].value_counts().items()}
        if not exclusions.empty
        else {}
    )
    occurrence_rows = (
        int(matched["occurrenceResolved"].astype(bool).sum()) if not matched.empty else 0
    )
    return {
        "schemaVersion": "MLB_GOLD_PA_BRIDGE_REPORT_V1",
        "methodVersion": _METHOD_VERSION,
        "keyColumns": list(_KEY_COLUMNS),
        "ordering": {
            "target": "positive integer suffix of retrosheet:pa:<game>:<order>",
            "silver": "strictly typed nonnegative integer atBatNumber",
            "withinKey": "zero-based occurrence ordinal",
        },
        "acceptanceRule": "TARGET_GROUP_COUNT_EQUALS_SILVER_GROUP_COUNT",
        "outcomeColumnsUsed": [],
        "counts": {
            "targetRows": len(target_seasons),
            "silverRows": int(silver_rows),
            "matchedRows": int(len(matched)),
            "excludedRows": int(len(exclusions)),
            "naturallyUniqueRows": int(len(matched) - occurrence_rows),
            "occurrenceResolvedRows": occurrence_rows,
            "postOrdinalAmbiguousRows": 0,
            "duplicateOutputRows": duplicate_rows,
            "duplicateOutputPlateAppearanceIds": duplicate_target_ids,
            "duplicateOutputCanonicalPaIds": duplicate_silver_ids,
        },
        "splits": {
            "development": subset(frozenset(development_seasons)),
            "validation": subset(frozenset(validation_seasons)),
        },
        "perSeason": per_season,
        "exclusionReasonCounts": reason_counts,
    }


def bridge_plate_appearances(
    targets: pd.DataFrame,
    silver_pa: pd.DataFrame,
    game_crosswalk: pd.DataFrame,
    player_crosswalk: pd.DataFrame,
    *,
    development_seasons: Sequence[int] = DEVELOPMENT_SEASONS,
    validation_seasons: Sequence[int] = VALIDATION_SEASONS,
) -> PaBridgeResult:
    """Build the deterministic target-to-Silver plate-appearance bridge.

    ``targets`` may contain an ``outcome`` column, but it is neither selected nor
    inspected.  Crosswalk ambiguity or malformed Silver authority raises
    :class:`PaBridgeIntegrityError`.  Target rows lacking exact authority or an
    equal-count bridge group are returned in ``exclusions``.
    """

    development = tuple(int(value) for value in development_seasons)
    validation = tuple(int(value) for value in validation_seasons)
    if not development or not validation:
        raise PaBridgeIntegrityError("development and validation seasons must be non-empty")
    if set(development) & set(validation):
        raise PaBridgeIntegrityError("development and validation seasons must be disjoint")
    development_set = frozenset(development)
    validation_set = frozenset(validation)

    game_map = _verified_game_map(game_crosswalk)
    player_map = _verified_player_map(player_crosswalk)
    target_frame, exclusion_records, input_seasons = _prepare_targets(
        targets,
        game_map=game_map,
        player_map=player_map,
        development_seasons=development_set,
        validation_seasons=validation_set,
    )
    silver_frame = _prepare_silver(silver_pa)

    if not target_frame.empty:
        target_counts = (
            target_frame.groupby(list(_KEY_COLUMNS), sort=False)
            .size()
            .rename("targetGroupCount")
            .reset_index()
        )
        silver_counts = (
            silver_frame.groupby(list(_KEY_COLUMNS), sort=False)
            .size()
            .rename("silverGroupCount")
            .reset_index()
        )
        counted = target_frame.merge(
            target_counts, on=list(_KEY_COLUMNS), how="left", validate="m:1"
        ).merge(silver_counts, on=list(_KEY_COLUMNS), how="left", validate="m:1")
        counted["silverGroupCount"] = counted["silverGroupCount"].fillna(0).astype(int)
        counted["targetGroupCount"] = counted["targetGroupCount"].astype(int)
        accepted_mask = counted["targetGroupCount"].eq(counted["silverGroupCount"])
        rejected = counted.loc[~accepted_mask]
        for row in rejected.itertuples(index=False):
            exclusion_records.append(
                _exclusion(
                    plate_appearance_id=row.plate_appearance_id,
                    game_id=row.game_id,
                    season=int(row.season),
                    reason_code="KEY_GROUP_COUNT_MISMATCH",
                    reason_detail="target and Silver bridge-key populations differ; no fallback match",
                    split=row.split,
                    canonical_game_id=row.canonicalGameId,
                    target_group_count=int(row.targetGroupCount),
                    silver_group_count=int(row.silverGroupCount),
                )
            )
        accepted = counted.loc[accepted_mask].copy()
    else:
        accepted = target_frame.copy()

    if accepted.empty:
        matched = pd.DataFrame(columns=_MATCHED_COLUMNS)
    else:
        equal_keys = accepted.loc[:, list(_KEY_COLUMNS)].drop_duplicates()
        accepted = accepted.sort_values(
            [*_KEY_COLUMNS, "targetOrder", "plate_appearance_id"], kind="mergesort"
        )
        accepted["occurrenceOrdinal"] = accepted.groupby(
            list(_KEY_COLUMNS), sort=False
        ).cumcount()
        accepted["occurrenceResolved"] = accepted["targetGroupCount"].gt(1)

        silver_equal = silver_frame.merge(
            equal_keys, on=list(_KEY_COLUMNS), how="inner", validate="m:1"
        ).sort_values(
            [*_KEY_COLUMNS, "silverAtBatNumber", "canonicalPaId"], kind="mergesort"
        )
        silver_equal["occurrenceOrdinal"] = silver_equal.groupby(
            list(_KEY_COLUMNS), sort=False
        ).cumcount()
        joined = accepted.merge(
            silver_equal,
            on=[*_KEY_COLUMNS, "occurrenceOrdinal"],
            how="inner",
            validate="1:1",
        )
        if len(joined) != len(accepted):
            raise PaBridgeIntegrityError("equal-count occurrence join did not reconcile one-to-one")
        if not bool(joined["season"].eq(joined["silverSeason"]).all()):
            raise PaBridgeIntegrityError("target and Silver seasons disagree after exact bridge")
        matched = joined.loc[:, _MATCHED_COLUMNS].sort_values(
            ["season", "game_id", "targetOrder", "plate_appearance_id"], kind="mergesort"
        ).reset_index(drop=True)

    exclusions = pd.DataFrame.from_records(exclusion_records, columns=_EXCLUSION_COLUMNS)
    if not exclusions.empty:
        exclusions = exclusions.sort_values(
            ["season", "game_id", "plate_appearance_id", "reasonCode"],
            kind="mergesort",
            na_position="last",
        ).reset_index(drop=True)
    if len(matched) + len(exclusions) != len(targets):
        raise PaBridgeIntegrityError("target reconciliation failed: matched + excluded != input")

    report = _count_report(
        target_seasons=input_seasons,
        matched=matched,
        exclusions=exclusions,
        silver_rows=len(silver_pa),
        development_seasons=development,
        validation_seasons=validation,
    )
    return PaBridgeResult(matched=matched, exclusions=exclusions, report=report)


# A concise alias for callers that name builders by their output artifact.
build_pa_bridge = bridge_plate_appearances


__all__ = [
    "DEVELOPMENT_SEASONS",
    "VALIDATION_SEASONS",
    "PaBridgeIntegrityError",
    "PaBridgeResult",
    "bridge_plate_appearances",
    "build_pa_bridge",
]
