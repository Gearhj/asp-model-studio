"""Chronological, date-atomic temporal design for NFL M1."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Sequence

from .data_authority import NflM1DataError


DEFAULT_VALIDATION_SEASONS = (2020, 2021, 2022, 2023, 2024)
DEFAULT_FINAL_OOT_SEASON = 2025


@dataclass(frozen=True)
class TemporalFold:
    fold_id: str
    train_start_date: date
    train_end_date: date
    train_start_season: int
    train_end_season: int
    train_count: int
    validation_season: int
    validation_start_date: date
    validation_end_date: date
    validation_count: int
    train_game_ids: tuple[str, ...]
    validation_game_ids: tuple[str, ...]


@dataclass(frozen=True)
class TemporalDesign:
    folds: tuple[TemporalFold, ...]
    oof_game_count: int
    oof_game_ids: tuple[str, ...]
    final_oot_season: int
    final_oot_start_date: date
    final_oot_end_date: date
    final_oot_count: int
    final_oot_game_ids: tuple[str, ...]
    prospective_seasons: tuple[int, ...]
    date_atomic: bool


def _ordered(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    try:
        return sorted(
            rows,
            key=lambda row: (
                row["game_date"], str(row["canonical_game_id"]),
            ),
        )
    except (KeyError, TypeError) as exc:
        raise NflM1DataError("NFL temporal rows lack game date/identity") from exc


def build_temporal_design(
    rows: Sequence[Mapping[str, Any]],
    *,
    validation_seasons: Sequence[int] = DEFAULT_VALIDATION_SEASONS,
    requested_oot_season: int = DEFAULT_FINAL_OOT_SEASON,
    complete_seasons: Sequence[int] | None = None,
) -> TemporalDesign:
    """Freeze five expanding folds and one untouched completed-season OOT.

    The function never infers completion merely from the presence of rows when
    ``complete_seasons`` is supplied by the source-schedule population audit.
    """

    ordered = _ordered(rows)
    if not ordered:
        raise NflM1DataError("NFL temporal population is empty")
    identities = [str(row.get("canonical_game_id") or "") for row in ordered]
    if any(not value for value in identities) or len(set(identities)) != len(identities):
        raise NflM1DataError("NFL temporal population has missing/duplicate identities")
    seasons = {int(row["season"]) for row in ordered}
    complete = set(int(value) for value in (complete_seasons or seasons))
    eligible_oot = sorted(season for season in seasons if season in complete and season <= requested_oot_season)
    if not eligible_oot:
        raise NflM1DataError("no fully completed NFL season is available for final OOT")
    oot_season = requested_oot_season if requested_oot_season in complete and requested_oot_season in seasons else eligible_oot[-1]
    if oot_season <= max(int(value) for value in validation_seasons):
        raise NflM1DataError("final NFL OOT does not follow all validation folds")

    dates_to_seasons: dict[date, set[int]] = defaultdict(set)
    for row in ordered:
        dates_to_seasons[row["game_date"]].add(int(row["season"]))
    if any(len(value) != 1 for value in dates_to_seasons.values()):
        raise NflM1DataError("an NFL game date crosses temporal season roles")

    folds = []
    oof_ids = []
    for position, validation_season in enumerate(validation_seasons, start=1):
        validation_season = int(validation_season)
        train = [row for row in ordered if int(row["season"]) < validation_season]
        validation = [row for row in ordered if int(row["season"]) == validation_season]
        if not train or not validation:
            raise NflM1DataError(f"NFL fold {position} lacks train/validation rows")
        if max(row["game_date"] for row in train) >= min(row["game_date"] for row in validation):
            raise NflM1DataError(f"NFL fold {position} is not chronological")
        train_ids = tuple(str(row["canonical_game_id"]) for row in train)
        validation_ids = tuple(str(row["canonical_game_id"]) for row in validation)
        oof_ids.extend(validation_ids)
        folds.append(
            TemporalFold(
                fold_id=f"FOLD_{position}",
                train_start_date=min(row["game_date"] for row in train),
                train_end_date=max(row["game_date"] for row in train),
                train_start_season=min(int(row["season"]) for row in train),
                train_end_season=max(int(row["season"]) for row in train),
                train_count=len(train),
                validation_season=validation_season,
                validation_start_date=min(row["game_date"] for row in validation),
                validation_end_date=max(row["game_date"] for row in validation),
                validation_count=len(validation),
                train_game_ids=train_ids,
                validation_game_ids=validation_ids,
            )
        )
    if any(count != 1 for count in Counter(oof_ids).values()):
        raise NflM1DataError("NFL OOF fold membership is not exactly once")
    oot = [row for row in ordered if int(row["season"]) == oot_season]
    if not oot:
        raise NflM1DataError("NFL final OOT is empty")
    oot_ids = tuple(str(row["canonical_game_id"]) for row in oot)
    if set(oof_ids) & set(oot_ids):
        raise NflM1DataError("NFL final OOT intersects development OOF")
    prospective = tuple(sorted(season for season in seasons if season > oot_season))
    return TemporalDesign(
        folds=tuple(folds),
        oof_game_count=len(oof_ids),
        oof_game_ids=tuple(oof_ids),
        final_oot_season=oot_season,
        final_oot_start_date=min(row["game_date"] for row in oot),
        final_oot_end_date=max(row["game_date"] for row in oot),
        final_oot_count=len(oot),
        final_oot_game_ids=oot_ids,
        prospective_seasons=prospective,
        date_atomic=True,
    )


__all__ = [
    "DEFAULT_FINAL_OOT_SEASON",
    "DEFAULT_VALIDATION_SEASONS",
    "TemporalDesign",
    "TemporalFold",
    "build_temporal_design",
]
