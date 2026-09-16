"""Versioned Silver table/schema + temporal-semantic contracts (Phase 7B1, Sections 26 & 29).

No Silver object is published without a governing contract. A material change in column meaning/type/nullability/key/
temporal semantics/source authority/identity method must produce a NEW contract version; old immutable objects and
their contracts are never rewritten (Section 47).

Temporal-field classes (Section 29) — the classification does NOT make a field model-eligible; it exists so the future
feature layer never treats an outcome as a predictor:
  IDENTITY, EVENT_CONTEXT, PRE_EVENT_OBSERVABLE, EVENT_RESULT, POST_EVENT_RESULT, SOURCE_LINEAGE, TEMPORAL_METADATA.
"""
from __future__ import annotations

from typing import Any

SILVER_TABLE_CONTRACT = "MLB_SILVER_TABLE_CONTRACT_V1"

IDENTITY = "IDENTITY"
EVENT_CONTEXT = "EVENT_CONTEXT"
PRE_EVENT_OBSERVABLE = "PRE_EVENT_OBSERVABLE"
EVENT_RESULT = "EVENT_RESULT"
POST_EVENT_RESULT = "POST_EVENT_RESULT"
SOURCE_LINEAGE = "SOURCE_LINEAGE"
TEMPORAL_METADATA = "TEMPORAL_METADATA"

# Every produced Silver object carries exactly this governance state (Section 6/31).
QUARANTINE_STATE = {
    "status": "SILVER_NORMALIZED", "quarantine": "QUARANTINED", "modelEligible": False,
    "approvedForTraining": False, "selectable": False,
}


def table_contract(*, name: str, schema_version: str, natural_key: list[str], canonical_id_fields: list[str],
                   required: list[str], nullable: list[str], source_systems: list[str], seasons: list[int],
                   row_semantics: str, temporal_semantics: str, field_classes: dict[str, str],
                   limitations: list[str] | None = None) -> dict[str, Any]:
    all_fields = sorted(set(required) | set(nullable))
    unclassified = [f for f in all_fields if f not in field_classes]
    if unclassified:
        raise ValueError(f"{name}: fields lack a temporal classification: {unclassified}")
    body = {
        "contract": SILVER_TABLE_CONTRACT, "tableName": name, "schemaVersion": schema_version,
        "naturalKey": list(natural_key), "canonicalIdentityFields": list(canonical_id_fields),
        "requiredFields": sorted(required), "nullableFields": sorted(nullable),
        "sourceSystems": sorted(source_systems), "seasons": sorted(seasons),
        "rowSemantics": row_semantics, "temporalSemantics": temporal_semantics,
        "fieldClasses": dict(sorted(field_classes.items())),
        "knownLimitations": sorted(limitations or []),
        **QUARANTINE_STATE,
    }
    return body


# ---- concrete contracts for the objects produced in this phase --------------------------------------------------
def dim_player_contract(seasons: list[int]) -> dict[str, Any]:
    return table_contract(
        name="dim_player", schema_version="1.0.0", natural_key=["canonicalPlayerId"],
        canonical_id_fields=["canonicalPlayerId"],
        required=["canonicalPlayerId", "chadwickKeyPerson", "resolutionStatus"],
        nullable=["chadwickKeyUuid", "mlbamId", "retrosheetId", "bbrefId", "fangraphsId",
                  "nameLast", "nameFirst", "mlbPlayedFirst", "mlbPlayedLast", "sourceProvenance"],
        source_systems=["chadwick"], seasons=seasons,
        row_semantics="one canonical person from the Chadwick cross-source register",
        temporal_semantics="register identity; no event/knowledge time",
        field_classes={"canonicalPlayerId": IDENTITY, "chadwickKeyPerson": IDENTITY, "chadwickKeyUuid": IDENTITY,
                       "mlbamId": IDENTITY, "retrosheetId": IDENTITY, "bbrefId": IDENTITY, "fangraphsId": IDENTITY,
                       "nameLast": IDENTITY, "nameFirst": IDENTITY, "mlbPlayedFirst": SOURCE_LINEAGE,
                       "mlbPlayedLast": SOURCE_LINEAGE, "resolutionStatus": SOURCE_LINEAGE,
                       "sourceProvenance": SOURCE_LINEAGE})


def bridge_player_identity_contract(seasons: list[int]) -> dict[str, Any]:
    return table_contract(
        name="bridge_player_identity", schema_version="1.0.0",
        natural_key=["sourceSystem", "sourceId"], canonical_id_fields=["canonicalPlayerId"],
        required=["sourceSystem", "sourceId", "resolutionStatus", "resolutionMethod"],
        nullable=["canonicalPlayerId", "candidateCanonicalPlayerIds"],
        source_systems=["chadwick", "mlbam", "retrosheet", "bbref", "fangraphs"], seasons=seasons,
        row_semantics="one (source system, source id) -> canonical player mapping with resolution state",
        temporal_semantics="register identity; no event/knowledge time",
        field_classes={"sourceSystem": IDENTITY, "sourceId": IDENTITY, "canonicalPlayerId": IDENTITY,
                       "candidateCanonicalPlayerIds": SOURCE_LINEAGE, "resolutionStatus": SOURCE_LINEAGE,
                       "resolutionMethod": SOURCE_LINEAGE})


def dim_game_contract(seasons: list[int]) -> dict[str, Any]:
    return table_contract(
        name="dim_game", schema_version="1.0.0", natural_key=["canonicalGameId"],
        canonical_id_fields=["canonicalGameId"],
        required=["canonicalGameId", "mlbamGamePk", "gameDate", "season", "homeTeam", "awayTeam", "gameType"],
        nullable=["retrosheetGameId", "gameNumber", "reconciliationStatus"],
        source_systems=["statcast", "retrosheet"], seasons=seasons,
        row_semantics="one canonical game",
        temporal_semantics="gameDate is EVENT_CONTEXT; final score/result are POST_EVENT and excluded from dim_game",
        field_classes={"canonicalGameId": IDENTITY, "mlbamGamePk": IDENTITY, "retrosheetGameId": IDENTITY,
                       "gameDate": EVENT_CONTEXT, "season": EVENT_CONTEXT, "homeTeam": EVENT_CONTEXT,
                       "awayTeam": EVENT_CONTEXT, "gameType": EVENT_CONTEXT, "gameNumber": EVENT_CONTEXT,
                       "reconciliationStatus": SOURCE_LINEAGE})


def dim_team_contract(seasons: list[int]) -> dict[str, Any]:
    return table_contract(
        name="dim_team", schema_version="1.0.0", natural_key=["canonicalTeamId"],
        canonical_id_fields=["canonicalTeamId"], required=["canonicalTeamId", "teamAbbrev"],
        nullable=["aliases", "retroTeamCode", "nickname", "city"], source_systems=["statcast", "retrosheet"], seasons=seasons,
        row_semantics="one canonical team (2019-2024 window) keyed by the Statcast abbrev, carrying the derived "
                      "Retrosheet code + nickname/city evidence", temporal_semantics="identity; no event time",
        field_classes={"canonicalTeamId": IDENTITY, "teamAbbrev": IDENTITY, "retroTeamCode": IDENTITY,
                       "aliases": SOURCE_LINEAGE, "nickname": SOURCE_LINEAGE, "city": SOURCE_LINEAGE})


def fact_statcast_pitch_contract(seasons: list[int]) -> dict[str, Any]:
    identity = ["canonicalPitchId", "canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber", "pitchNumber",
                "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId"]
    context = ["season", "gameDate", "gameType", "inning", "inningTopBot", "stand", "pThrows", "homeTeam", "awayTeam"]
    telemetry = ["pitchType", "releaseSpeed", "bbType", "pitchResultType"]     # PRE-event pitch telemetry / descriptors
    result = ["events", "description", "des"]                                  # EVENT_RESULT of the pitch/PA
    lineage = ["sourcePartitionId", "sourceRowIndex"]
    fc = {f: IDENTITY for f in identity}
    fc.update({f: EVENT_CONTEXT for f in context})
    fc.update({f: PRE_EVENT_OBSERVABLE for f in telemetry})
    fc.update({f: EVENT_RESULT for f in result})
    fc.update({f: SOURCE_LINEAGE for f in lineage})
    req = identity + context + lineage
    return table_contract(
        name="fact_statcast_pitch", schema_version="1.0.0",
        natural_key=["mlbamGamePk", "atBatNumber", "pitchNumber"], canonical_id_fields=["canonicalPitchId"],
        required=req, nullable=telemetry + result, source_systems=["statcast"], seasons=seasons,
        row_semantics="one Statcast pitch, bound to canonical game/PA/batter/pitcher identity with lineage",
        temporal_semantics="events/description/des are EVENT_RESULT and MUST NOT be used as pre-event predictors",
        field_classes=fc,
        limitations=["Statcast historical CSV has no true publication/knowledge timestamps; knowledge time unavailable"])


def bridge_game_identity_contract(seasons: list[int]) -> dict[str, Any]:
    return table_contract(
        name="bridge_game_identity", schema_version="1.0.0",
        natural_key=["canonicalGameId"], canonical_id_fields=["canonicalGameId"],
        required=["canonicalGameId", "mlbamGamePk", "gameDate", "homeTeam", "awayTeam", "resolutionStatus", "resolutionMethod"],
        nullable=["retrosheetGameId"], source_systems=["statcast", "retrosheet"], seasons=seasons,
        row_semantics="one canonical game -> (statcast game_pk, retrosheet game id) with reconciliation state",
        temporal_semantics="identity; gameDate is EVENT_CONTEXT; no outcome used as identity",
        field_classes={"canonicalGameId": IDENTITY, "mlbamGamePk": IDENTITY, "retrosheetGameId": IDENTITY,
                       "gameDate": EVENT_CONTEXT, "homeTeam": EVENT_CONTEXT, "awayTeam": EVENT_CONTEXT,
                       "resolutionStatus": SOURCE_LINEAGE, "resolutionMethod": SOURCE_LINEAGE})


def dim_park_contract(seasons: list[int]) -> dict[str, Any]:
    return table_contract(
        name="dim_park", schema_version="1.0.0", natural_key=["retroParkId"], canonical_id_fields=["canonicalParkId"],
        required=["canonicalParkId", "retroParkId"], nullable=["seasons"], source_systems=["retrosheet"], seasons=seasons,
        row_semantics="one canonical park from Retrosheet game site ids",
        temporal_semantics="identity; no event time",
        field_classes={"canonicalParkId": IDENTITY, "retroParkId": IDENTITY, "seasons": SOURCE_LINEAGE})


def fact_retrosheet_event_contract(seasons: list[int]) -> dict[str, Any]:
    ident = ["canonicalGameId", "retroGameId", "eventSequence", "retroBatterId", "batterCanonicalPlayerId"]
    ctx = ["season", "inning", "half", "count"]
    result = ["eventText"]
    lineage = ["pitches", "sourceArchive", "sourceMember", "sourceLine"]
    fc = {f: IDENTITY for f in ident}; fc.update({f: EVENT_CONTEXT for f in ctx})
    fc.update({f: EVENT_RESULT for f in result}); fc.update({f: SOURCE_LINEAGE for f in lineage})
    return table_contract(
        name="fact_retrosheet_event", schema_version="1.0.0",
        natural_key=["retroGameId", "eventSequence"], canonical_id_fields=["canonicalGameId"],
        required=ident + ctx + lineage, nullable=result, source_systems=["retrosheet"], seasons=seasons,
        row_semantics="one Retrosheet play/event in source sequence order, bound to canonical game/batter",
        temporal_semantics="eventText is EVENT_RESULT; sequence is source order (not a fabricated identity)",
        field_classes=fc, limitations=["batterCanonicalPlayerId null when the retro id is unresolved/ambiguous"])


def fact_lineup_participation_contract(seasons: list[int]) -> dict[str, Any]:
    ident = ["canonicalGameId", "retroGameId", "retroPlayerId", "playerCanonicalPlayerId", "recordType"]
    ctx = ["season", "homeAway", "battingOrder", "fieldPosition"]
    lineage = ["playerName", "sourceArchive", "sourceMember", "sourceLine"]
    fc = {f: IDENTITY for f in ident}; fc.update({f: EVENT_CONTEXT for f in ctx}); fc.update({f: SOURCE_LINEAGE for f in lineage})
    return table_contract(
        name="fact_lineup_participation", schema_version="1.0.0",
        natural_key=["retroGameId", "retroPlayerId", "recordType", "battingOrder", "fieldPosition"],
        canonical_id_fields=["canonicalGameId", "playerCanonicalPlayerId"],
        required=ident + ctx + lineage, nullable=[], source_systems=["retrosheet"], seasons=seasons,
        row_semantics="one starting-lineup or substitution participation record bound to canonical game/player",
        temporal_semantics="participation identity; no outcome", field_classes=fc,
        limitations=["playerCanonicalPlayerId null when the retro id is unresolved/ambiguous"])


def fact_umpire_game_contract(seasons: list[int]) -> dict[str, Any]:
    ident = ["canonicalGameId", "retroGameId", "umpirePosition", "retroUmpireId", "umpireCanonicalPlayerId"]
    ctx = ["season"]
    lineage = ["sourceArchive", "sourceMember"]
    fc = {f: IDENTITY for f in ident}; fc.update({f: EVENT_CONTEXT for f in ctx}); fc.update({f: SOURCE_LINEAGE for f in lineage})
    return table_contract(
        name="fact_umpire_game", schema_version="1.0.0",
        natural_key=["retroGameId", "umpirePosition"], canonical_id_fields=["canonicalGameId"],
        required=ident + ctx + lineage, nullable=[], source_systems=["retrosheet"], seasons=seasons,
        row_semantics="one umpire assignment per (game, position)", temporal_semantics="assignment identity",
        field_classes=fc, limitations=["umpireCanonicalPlayerId null when the retro umpire id is not in the register"])


def fact_team_game_contract(seasons: list[int]) -> dict[str, Any]:
    ident = ["canonicalGameId", "retroGameId", "canonicalTeamId", "retroTeamCode", "homeAway"]
    ctx = ["season", "gameDate", "gameNumber", "retroOpponentCode", "parkId"]
    result = ["runsScored", "runsAllowed"]
    lineage = ["retroManagerId", "sourceArchive", "sourceMember", "sourceLine"]
    fc = {f: IDENTITY for f in ident}; fc.update({f: EVENT_CONTEXT for f in ctx})
    fc.update({f: POST_EVENT_RESULT for f in result}); fc.update({f: SOURCE_LINEAGE for f in lineage})
    return table_contract(
        name="fact_team_game", schema_version="1.0.0",
        natural_key=["retroGameId", "homeAway"], canonical_id_fields=["canonicalGameId", "canonicalTeamId"],
        required=ident + ctx + lineage, nullable=result, source_systems=["retrosheet"], seasons=seasons,
        row_semantics="one team's participation + historical outcome in a game (Retrosheet game-log)",
        temporal_semantics="runsScored/runsAllowed are POST_EVENT_RESULT historical facts, NOT pregame predictors",
        field_classes=fc)


def fact_player_game_contract(seasons: list[int]) -> dict[str, Any]:
    ident = ["canonicalGameId", "canonicalPlayerId", "canonicalTeamId", "retroGameId"]
    ctx = ["season", "homeAway", "startedGame", "battingOrder", "fieldPosition"]
    lineage = ["retroPlayerId", "sourceArchive", "sourceMember"]
    fc = {f: IDENTITY for f in ident}; fc.update({f: EVENT_CONTEXT for f in ctx}); fc.update({f: SOURCE_LINEAGE for f in lineage})
    return table_contract(
        name="fact_player_game", schema_version="1.0.0",
        natural_key=["retroGameId", "canonicalPlayerId"], canonical_id_fields=["canonicalGameId", "canonicalPlayerId"],
        required=ident + ctx + lineage, nullable=[], source_systems=["retrosheet"], seasons=seasons,
        row_semantics="one player's participation in a game (start/role) from Retrosheet lineups",
        temporal_semantics="participation identity; not a pregame feature", field_classes=fc,
        limitations=["only players with a resolved canonical identity are included; unresolved go to the reject artifact"])


def fact_statcast_plate_appearance_contract(seasons: list[int]) -> dict[str, Any]:
    identity = ["canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber",
                "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "batterMlbamId", "pitcherMlbamId"]
    context = ["season", "gameDate", "gameType", "inning", "inningTopBot", "stand", "pThrows"]
    result = ["paEvent"]
    lineage = ["pitchCount", "firstPitchNumber", "lastPitchNumber"]
    fc = {f: IDENTITY for f in identity}
    fc.update({f: EVENT_CONTEXT for f in context})
    fc.update({f: EVENT_RESULT for f in result})
    fc.update({f: SOURCE_LINEAGE for f in lineage})
    return table_contract(
        name="fact_statcast_plate_appearance", schema_version="1.0.0",
        natural_key=["canonicalPaId"], canonical_id_fields=["canonicalPaId"],
        required=identity + context + lineage, nullable=result, source_systems=["statcast"], seasons=seasons,
        row_semantics="one canonical plate appearance aggregating its pitches; deterministic linkage to pitches preserved",
        temporal_semantics="paEvent is EVENT_RESULT; pitch lineage preserved via first/last pitch numbers",
        field_classes=fc,
        limitations=["knowledge time unavailable in historical Statcast CSV"])
