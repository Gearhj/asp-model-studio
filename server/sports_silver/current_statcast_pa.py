"""Fail-closed current-season Statcast pitch and PA normalization.

This module is deliberately separate from :mod:`statcast_normalize`, whose
2019--2024 output is frozen.  It normalizes the 2025--2026 extension one daily
Bronze partition at a time and emits facts only for games present in a supplied
MLB final-game authority.  A complete plate appearance is the governed unit of
acceptance: when any row in a ``(game_pk, at_bat_number)`` group is invalid,
neither its PA nor any of its pitches is emitted.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
import math
from typing import Any

from .canonical_ids import canonical_game_id, canonical_pa_id, canonical_pitch_id
from ..sports_datasets.constants import PA_CLASS_ORDER as _GOVERNED_PA_CLASS_ORDER
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes


NORMALIZER_CONTRACT = "MLB_CURRENT_STATCAST_PA_NORMALIZER_V2"
FINAL_GAME_AUTHORITY_CONTRACT = "MLB_FINAL_GAME_PK_AUTHORITY_V1"
PA_CLASS_ORDER: tuple[str, ...] = tuple(_GOVERNED_PA_CLASS_ORDER)

# This is an explicit allow-list, not a heuristic.  Any newly observed Statcast
# terminal event must be reviewed and added deliberately before it can enter the
# governed eight-class target.
EVENT_TO_OUTCOME: Mapping[str, str] = {
    "strikeout": "STRIKEOUT",
    "strikeout_double_play": "STRIKEOUT",
    "walk": "WALK_HBP_CI",
    "intent_walk": "WALK_HBP_CI",
    "hit_by_pitch": "WALK_HBP_CI",
    "catcher_interf": "WALK_HBP_CI",
    "home_run": "HOME_RUN",
    "single": "SINGLE",
    "double": "DOUBLE",
    "triple": "TRIPLE",
    "field_out": "BIP_OUT",
    "force_out": "BIP_OUT",
    "grounded_into_double_play": "BIP_OUT",
    "double_play": "BIP_OUT",
    "fielders_choice_out": "BIP_OUT",
    "sac_bunt": "BIP_OUT",
    "sac_fly": "BIP_OUT",
    "sac_bunt_double_play": "BIP_OUT",
    "sac_fly_double_play": "BIP_OUT",
    "triple_play": "BIP_OUT",
    "batter_interference": "BIP_OUT",
    "field_error": "OTHER_REACH",
    "fielders_choice": "OTHER_REACH",
}
if set(EVENT_TO_OUTCOME.values()) != set(PA_CLASS_ORDER):
    raise RuntimeError("current Statcast event crosswalk does not cover the governed PA class contract")

_LINEAGE_FIELDS: tuple[str, ...] = (
    "sourcePartitionId",
    "sourcePartitionDate",
    "sourceCutoff",
    "sourcePartitionSha256",
    "sourceManifestSha256",
    "finalGameAuthoritySha256",
    "rulesRegime",
    "is2026RulesRegime",
    "normalizerContract",
)
PITCH_FIELDS: tuple[str, ...] = (
    "canonicalPitchId", "canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber", "pitchNumber",
    "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId", "season",
    "gameDate", "gameType", "inning", "inningTopBot", "stand", "pThrows", "homeTeam", "awayTeam",
    "pitchType", "releaseSpeed", "bbType", "pitchResultType", "events", "description", "des",
    "sourceRowIndex", *_LINEAGE_FIELDS,
)
PA_FIELDS: tuple[str, ...] = (
    "canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber", "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId", "season", "gameDate", "gameType",
    "homeTeam", "awayTeam", "inning", "inningTopBot", "outsBeforePa", "onFirstMlbamIdBeforePa",
    "onSecondMlbamIdBeforePa", "onThirdMlbamIdBeforePa", "onFirstOccupiedBeforePa",
    "onSecondOccupiedBeforePa", "onThirdOccupiedBeforePa", "homeScoreBeforePa", "awayScoreBeforePa",
    "batScoreBeforePa", "fieldScoreBeforePa", "stand", "pThrows", "paEvent", "outcome", "pitchCount",
    "firstPitchNumber", "lastPitchNumber", "terminalSourceRowIndex", *_LINEAGE_FIELDS,
)
REJECT_FIELDS: tuple[str, ...] = (
    "mlbamGamePk", "atBatNumber", "gameDate", "batterMlbamId", "pitcherMlbamId", "rawEvent",
    "normalizedEvent", "observedRawEvents", "reason", "detail", "pitchRowCount", "sourceRowIndices",
    *_LINEAGE_FIELDS,
)

_READ_COLUMNS: tuple[str, ...] = (
    "game_pk",
    "game_date",
    "game_year",
    "game_type",
    "home_team",
    "away_team",
    "inning",
    "inning_topbot",
    "outs_when_up",
    "on_1b",
    "on_2b",
    "on_3b",
    "home_score",
    "away_score",
    "bat_score",
    "fld_score",
    "at_bat_number",
    "pitch_number",
    "batter",
    "pitcher",
    "stand",
    "p_throws",
    "pitch_type",
    "release_speed",
    "bb_type",
    "events",
    "description",
    "des",
)

_DEFAULT_RULES_REGIME: Mapping[int, str] = {
    2025: "MLB_2025_REGULAR_RULES",
    2026: "MLB_2026_REGULAR_RULES",
}


class CurrentStatcastNormalizationError(ValueError):
    """The caller supplied an invalid normalization authority or contract."""


@dataclass(frozen=True)
class CurrentPartitionResult:
    """Facts, explicit rejects, and accounting for one daily partition."""

    fact_pitch: list[dict[str, Any]]
    fact_pa: list[dict[str, Any]]
    rejects: list[dict[str, Any]]
    counts: dict[str, Any]


def _scalar(value: Any) -> Any:
    return value.as_py() if hasattr(value, "as_py") else value


def _text(value: Any) -> str | None:
    value = _scalar(value)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    result = str(value).strip()
    return result or None


def _integer(value: Any) -> int | None:
    value = _scalar(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    return int(parsed) if math.isfinite(parsed) and parsed.is_integer() else None


def _event(value: Any) -> str | None:
    text = _text(value)
    return text.casefold() if text else None


def _iso_date(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def map_pa_event(raw_event: Any) -> str | None:
    """Map one reviewed Statcast terminal event to the exact eight-class target."""

    normalized = _event(raw_event)
    return EVENT_TO_OUTCOME.get(normalized) if normalized else None


def _column_lists(table: Any) -> dict[str, list[Any]]:
    names = set(table.column_names)
    missing = sorted(set(_READ_COLUMNS) - names)
    if missing:
        raise CurrentStatcastNormalizationError(
            f"Statcast partition is missing required source columns: {missing}"
        )
    rows = int(table.num_rows)
    return {
        name: table.column(name).to_pylist() if name in names else [None] * rows
        for name in _READ_COLUMNS
    }


def _lineage(
    *,
    partition_id: str,
    partition_date: str,
    source_cutoff: str,
    source_partition_sha256: str,
    source_manifest_sha256: str,
    final_game_authority_sha256: str,
    rules_regime: str | None,
) -> dict[str, Any]:
    return {
        "sourcePartitionId": partition_id,
        "sourcePartitionDate": partition_date,
        "sourceCutoff": source_cutoff,
        "sourcePartitionSha256": source_partition_sha256,
        "sourceManifestSha256": source_manifest_sha256,
        "finalGameAuthoritySha256": final_game_authority_sha256,
        "rulesRegime": rules_regime,
        "is2026RulesRegime": rules_regime == "MLB_2026_REGULAR_RULES",
        "normalizerContract": NORMALIZER_CONTRACT,
    }


def _reject(
    rows: list[dict[str, Any]],
    *,
    reason: str,
    detail: str,
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    first = rows[0]
    events = sorted({_text(row["events"]) for row in rows if _text(row["events"]) is not None})
    terminal = max(
        rows,
        key=lambda row: (
            _integer(row["pitch_number"]) if _integer(row["pitch_number"]) is not None else -1,
            row["_source_row_index"],
        ),
    )
    return {
        "mlbamGamePk": _text(first["game_pk"]),
        "atBatNumber": _text(first["at_bat_number"]),
        "gameDate": _text(first["game_date"]),
        "batterMlbamId": _text(first["batter"]),
        "pitcherMlbamId": _text(first["pitcher"]),
        "rawEvent": _text(terminal["events"]),
        "normalizedEvent": _event(terminal["events"]),
        "observedRawEvents": events,
        "reason": reason,
        "detail": detail,
        "pitchRowCount": len(rows),
        "sourceRowIndices": [row["_source_row_index"] for row in rows],
        **lineage,
    }


def _validate_authority(
    *,
    partition_id: str,
    partition_date: str,
    source_cutoff: str,
    source_partition_sha256: str,
    source_manifest_sha256: str,
    final_game_pks: Collection[int | str],
) -> tuple[str, frozenset[int]]:
    if not all(
        _text(value)
        for value in (
            partition_id,
            source_cutoff,
            source_partition_sha256,
            source_manifest_sha256,
        )
    ):
        raise CurrentStatcastNormalizationError("complete source lineage is required")
    for name, value in (
        ("source_partition_sha256", source_partition_sha256),
        ("source_manifest_sha256", source_manifest_sha256),
    ):
        digest = str(value).casefold()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise CurrentStatcastNormalizationError(f"{name} must be an exact SHA-256 digest")
    normalized_date = _iso_date(partition_date)
    if normalized_date is None:
        raise CurrentStatcastNormalizationError("partition_date must be an ISO calendar date")
    normalized_games: set[int] = set()
    for value in final_game_pks:
        parsed = _integer(value)
        if parsed is None:
            raise CurrentStatcastNormalizationError("final_game_pks must contain integer MLB game_pk values")
        normalized_games.add(parsed)
    return normalized_date, frozenset(normalized_games)


def _final_game_authority_sha256(partition_date: str, final_game_pks: Collection[int]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {
                "contract": FINAL_GAME_AUTHORITY_CONTRACT,
                "partitionDate": partition_date,
                "finalGamePks": sorted(final_game_pks),
            }
        )
    )


def _is_canonical_player_id(value: Any) -> bool:
    text = _text(value)
    if text is None or not text.startswith("player-") or len(text) != 31:
        return False
    return all(character in "0123456789abcdef" for character in text[7:])


def normalize_current_partition(
    table: Any,
    *,
    partition_id: str,
    partition_date: str,
    source_cutoff: str,
    source_partition_sha256: str,
    source_manifest_sha256: str,
    final_game_pks: Collection[int | str],
    resolved_mlbam: Mapping[str, str],
    rules_regime_by_season: Mapping[int, str] | None = None,
) -> CurrentPartitionResult:
    """Normalize one current-season daily Statcast partition.

    ``final_game_pks`` is the exact MLB Stats API final-game authority for the
    partition date.  Rows from any other game fail closed.  The pre-PA context
    is taken from the minimum pitch number and the target only from the maximum
    pitch number, independent of physical source-row order.
    """

    normalized_partition_date, final_games = _validate_authority(
        partition_id=partition_id,
        partition_date=partition_date,
        source_cutoff=source_cutoff,
        source_partition_sha256=source_partition_sha256,
        source_manifest_sha256=source_manifest_sha256,
        final_game_pks=final_game_pks,
    )
    partition_id = str(partition_id).strip()
    source_cutoff = str(source_cutoff).strip()
    source_partition_sha256 = str(source_partition_sha256).casefold()
    source_manifest_sha256 = str(source_manifest_sha256).casefold()
    regimes = dict(_DEFAULT_RULES_REGIME)
    if rules_regime_by_season is not None:
        regimes.update(rules_regime_by_season)
    final_authority_sha256 = _final_game_authority_sha256(
        normalized_partition_date, final_games
    )

    columns = _column_lists(table)
    source_rows: list[dict[str, Any]] = []
    for index in range(int(table.num_rows)):
        source_rows.append({name: columns[name][index] for name in _READ_COLUMNS} | {"_source_row_index": index})

    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    orphan_rows: list[list[dict[str, Any]]] = []
    for row in source_rows:
        game_pk = _integer(row["game_pk"])
        at_bat_number = _integer(row["at_bat_number"])
        if game_pk is None or at_bat_number is None:
            orphan_rows.append([row])
        else:
            grouped[(game_pk, at_bat_number)].append(row)

    fact_pitch: list[dict[str, Any]] = []
    fact_pa: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = defaultdict(int)
    rejected_pitch_rows = 0

    for rows in orphan_rows:
        season = _integer(rows[0]["game_year"])
        lineage = _lineage(
            partition_id=partition_id,
            partition_date=normalized_partition_date,
            source_cutoff=source_cutoff,
            source_partition_sha256=source_partition_sha256,
            source_manifest_sha256=source_manifest_sha256,
            final_game_authority_sha256=final_authority_sha256,
            rules_regime=regimes.get(season) if season is not None else None,
        )
        reason = "MISSING_PA_NATURAL_KEY"
        rejects.append(
            _reject(
                rows,
                reason=reason,
                detail="game_pk and at_bat_number are both required",
                lineage=lineage,
            )
        )
        reason_counts[reason] += 1
        rejected_pitch_rows += 1

    for (game_pk, at_bat_number), rows in sorted(grouped.items()):
        rows = sorted(
            rows,
            key=lambda row: (
                _integer(row["pitch_number"]) if _integer(row["pitch_number"]) is not None else -1,
                row["_source_row_index"],
            ),
        )
        first = rows[0]
        season = _integer(first["game_year"])
        rules_regime = regimes.get(season) if season is not None else None
        lineage = _lineage(
            partition_id=partition_id,
            partition_date=normalized_partition_date,
            source_cutoff=source_cutoff,
            source_partition_sha256=source_partition_sha256,
            source_manifest_sha256=source_manifest_sha256,
            final_game_authority_sha256=final_authority_sha256,
            rules_regime=rules_regime,
        )

        reason: str | None = None
        detail = ""
        pitch_numbers = [_integer(row["pitch_number"]) for row in rows]
        if any(number is None for number in pitch_numbers):
            reason, detail = "MISSING_PITCH_NUMBER", "every pitch in the PA requires an integer pitch_number"
        elif len(set(pitch_numbers)) != len(pitch_numbers):
            reason, detail = "DUPLICATE_PITCH_NATURAL_KEY", "pitch_number repeats within game_pk + at_bat_number"
        elif game_pk not in final_games:
            reason, detail = "GAME_NOT_FINAL", "game_pk is absent from the supplied final-game authority"
        elif _iso_date(first["game_date"]) != normalized_partition_date or any(
            _iso_date(row["game_date"]) != normalized_partition_date for row in rows
        ):
            reason, detail = "PARTITION_DATE_MISMATCH", "all PA rows must match the governed partition date"
        elif season not in _DEFAULT_RULES_REGIME or not _text(rules_regime):
            reason, detail = "MISSING_RULES_REGIME", "season has no explicit current-season rules regime"
        elif any(_text(row["game_type"]) != "R" for row in rows):
            reason, detail = "NON_REGULAR_GAME", "only regular-season Statcast PAs are authorized"
        elif any(_integer(row["game_year"]) != season for row in rows):
            reason, detail = "CONTRADICTORY_GAME_CONTEXT", "game_year changes within the PA"
        elif any(
            _integer(row["game_pk"]) != game_pk
            or _integer(row["at_bat_number"]) != at_bat_number
            for row in rows
        ):
            reason, detail = "CONTRADICTORY_PA_IDENTITY", "source rows disagree on the PA natural key"

        batters = {_text(row["batter"]) for row in rows}
        pitchers = {_text(row["pitcher"]) for row in rows}
        if reason is None and (None in batters or None in pitchers):
            reason, detail = "MISSING_PLAYER_IDENTITY", "batter and pitcher MLBAM ids are required on every pitch"
        elif reason is None and (len(batters) != 1 or len(pitchers) != 1):
            reason, detail = "CONTRADICTORY_PLAYER_IDENTITY", "batter and pitcher must be stable within a PA"

        batter = next(iter(batters)) if len(batters) == 1 else None
        pitcher = next(iter(pitchers)) if len(pitchers) == 1 else None
        batter_canonical = resolved_mlbam.get(batter) if batter is not None else None
        pitcher_canonical = resolved_mlbam.get(pitcher) if pitcher is not None else None
        if reason is None and (
            not _is_canonical_player_id(batter_canonical)
            or not _is_canonical_player_id(pitcher_canonical)
        ):
            reason, detail = "UNRESOLVED_PLAYER_IDENTITY", "both MLBAM ids require governed canonical-player mappings"

        terminal = rows[-1]
        terminal_event = _event(terminal["events"])
        observed_events = {_event(row["events"]) for row in rows if _event(row["events"]) is not None}
        if reason is None and terminal_event is None:
            reason, detail = "MISSING_TERMINAL_EVENT", "the maximum pitch_number row has no terminal Statcast event"
        elif reason is None and terminal_event not in EVENT_TO_OUTCOME:
            reason, detail = "UNKNOWN_TERMINAL_EVENT", f"unreviewed terminal Statcast event: {terminal_event!r}"
        elif reason is None and any(event not in EVENT_TO_OUTCOME for event in observed_events):
            unknown = sorted(event for event in observed_events if event not in EVENT_TO_OUTCOME)
            reason, detail = "UNKNOWN_PA_EVENT", f"unreviewed nonterminal Statcast event(s): {unknown!r}"
        elif reason is None and any(event != terminal_event for event in observed_events):
            reason = "CONTRADICTORY_PA_EVENTS"
            detail = f"observed terminal-event values disagree: {sorted(observed_events)!r}"

        if reason is not None:
            rejects.append(_reject(rows, reason=reason, detail=detail, lineage=lineage))
            reason_counts[reason] += 1
            rejected_pitch_rows += len(rows)
            continue

        assert batter is not None and pitcher is not None
        assert batter_canonical is not None and pitcher_canonical is not None
        assert terminal_event is not None and season is not None and rules_regime is not None
        assert all(number is not None for number in pitch_numbers)
        context = rows[0]
        canonical_game = canonical_game_id(game_pk)
        canonical_pa = canonical_pa_id(canonical_game, at_bat_number, batter_canonical)
        outcome = EVENT_TO_OUTCOME[terminal_event]

        pa_row = {
            "canonicalPaId": canonical_pa,
            "canonicalGameId": canonical_game,
            "mlbamGamePk": str(game_pk),
            "atBatNumber": str(at_bat_number),
            "batterCanonicalPlayerId": batter_canonical,
            "pitcherCanonicalPlayerId": pitcher_canonical,
            "batterMlbamId": batter,
            "pitcherMlbamId": pitcher,
            "season": str(season),
            "gameDate": normalized_partition_date,
            "gameType": _text(context["game_type"]),
            "homeTeam": _text(context["home_team"]),
            "awayTeam": _text(context["away_team"]),
            "inning": _integer(context["inning"]),
            "inningTopBot": _text(context["inning_topbot"]),
            "outsBeforePa": _integer(context["outs_when_up"]),
            "onFirstMlbamIdBeforePa": _text(context["on_1b"]),
            "onSecondMlbamIdBeforePa": _text(context["on_2b"]),
            "onThirdMlbamIdBeforePa": _text(context["on_3b"]),
            "onFirstOccupiedBeforePa": _text(context["on_1b"]) is not None,
            "onSecondOccupiedBeforePa": _text(context["on_2b"]) is not None,
            "onThirdOccupiedBeforePa": _text(context["on_3b"]) is not None,
            "homeScoreBeforePa": _integer(context["home_score"]),
            "awayScoreBeforePa": _integer(context["away_score"]),
            "batScoreBeforePa": _integer(context["bat_score"]),
            "fieldScoreBeforePa": _integer(context["fld_score"]),
            "stand": _text(context["stand"]),
            "pThrows": _text(context["p_throws"]),
            "paEvent": terminal_event,
            "outcome": outcome,
            "pitchCount": len(rows),
            "firstPitchNumber": pitch_numbers[0],
            "lastPitchNumber": pitch_numbers[-1],
            "terminalSourceRowIndex": terminal["_source_row_index"],
            **lineage,
        }
        fact_pa.append(pa_row)

        for row, pitch_number in zip(rows, pitch_numbers, strict=True):
            assert pitch_number is not None
            fact_pitch.append(
                {
                    "canonicalPitchId": canonical_pitch_id(canonical_game, at_bat_number, pitch_number),
                    "canonicalPaId": canonical_pa,
                    "canonicalGameId": canonical_game,
                    "mlbamGamePk": str(game_pk),
                    "atBatNumber": str(at_bat_number),
                    "pitchNumber": str(pitch_number),
                    "batterCanonicalPlayerId": batter_canonical,
                    "pitcherCanonicalPlayerId": pitcher_canonical,
                    "batterMlbamId": batter,
                    "pitcherMlbamId": pitcher,
                    "season": str(season),
                    "gameDate": normalized_partition_date,
                    "gameType": _text(row["game_type"]),
                    "inning": _text(row["inning"]),
                    "inningTopBot": _text(row["inning_topbot"]),
                    "stand": _text(row["stand"]),
                    "pThrows": _text(row["p_throws"]),
                    "homeTeam": _text(row["home_team"]),
                    "awayTeam": _text(row["away_team"]),
                    "pitchType": _text(row["pitch_type"]),
                    "releaseSpeed": _text(row["release_speed"]),
                    "bbType": _text(row["bb_type"]),
                    "pitchResultType": _text(row["description"]),
                    "events": _text(row["events"]),
                    "description": _text(row["description"]),
                    "des": _text(row["des"]),
                    "sourceRowIndex": row["_source_row_index"],
                    **lineage,
                }
            )

    fact_pa.sort(key=lambda row: (row["gameDate"], int(row["mlbamGamePk"]), int(row["atBatNumber"])))
    fact_pitch.sort(
        key=lambda row: (
            row["gameDate"],
            int(row["mlbamGamePk"]),
            int(row["atBatNumber"]),
            int(row["pitchNumber"]),
        )
    )
    rejects.sort(
        key=lambda row: (
            row["gameDate"] or "",
            int(row["mlbamGamePk"]) if row["mlbamGamePk"] and row["mlbamGamePk"].isdigit() else -1,
            int(row["atBatNumber"]) if row["atBatNumber"] and row["atBatNumber"].isdigit() else -1,
            row["sourceRowIndices"],
        )
    )
    source_pa_groups = len(grouped) + len(orphan_rows)
    counts: dict[str, Any] = {
        "sourcePitchRows": len(source_rows),
        "acceptedPitchRows": len(fact_pitch),
        "rejectedPitchRows": rejected_pitch_rows,
        "sourcePlateAppearanceGroups": source_pa_groups,
        "acceptedPlateAppearances": len(fact_pa),
        "rejectedPlateAppearances": len(rejects),
        "reasonCounts": dict(sorted(reason_counts.items())),
        "finalGameAuthorityCount": len(final_games),
        "finalGameAuthoritySha256": final_authority_sha256,
        "representedFinalGameCount": len({int(row["mlbamGamePk"]) for row in fact_pa}),
        "classCounts": {
            name: sum(row["outcome"] == name for row in fact_pa) for name in PA_CLASS_ORDER
        },
        "pitchRowsReconcile": len(source_rows) == len(fact_pitch) + rejected_pitch_rows,
        "paGroupsReconcile": source_pa_groups == len(fact_pa) + len(rejects),
    }
    return CurrentPartitionResult(
        fact_pitch=fact_pitch,
        fact_pa=fact_pa,
        rejects=rejects,
        counts=counts,
    )


__all__ = [
    "CurrentPartitionResult",
    "CurrentStatcastNormalizationError",
    "EVENT_TO_OUTCOME",
    "FINAL_GAME_AUTHORITY_CONTRACT",
    "NORMALIZER_CONTRACT",
    "PA_CLASS_ORDER",
    "PA_FIELDS",
    "PITCH_FIELDS",
    "REJECT_FIELDS",
    "map_pa_event",
    "normalize_current_partition",
]
