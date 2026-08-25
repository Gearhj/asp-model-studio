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
        nullable=["aliases"], source_systems=["statcast"], seasons=seasons,
        row_semantics="one canonical team (2019-2024 window)", temporal_semantics="identity; no event time",
        field_classes={"canonicalTeamId": IDENTITY, "teamAbbrev": IDENTITY, "aliases": SOURCE_LINEAGE})


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
