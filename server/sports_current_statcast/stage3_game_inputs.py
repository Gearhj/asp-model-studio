"""Fail-closed pregame evidence boundary for Stage 3 whole-game scoring.

This module is deliberately pure.  It does not discover games, call a data provider, open
Gold, or inspect target-game outcomes.  A caller must supply one already-governed point-in-
time evidence object.  Only then can the object be reduced to the eighteen immutable batter
versus announced-starter templates consumed by the simulator adapter.

The five changing game-state predictors are *not* accepted in a pregame template.  They are
owned by :mod:`stage3_game_probability_adapter` and are injected from simulated state at each
plate appearance.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from server.sports_datasets.consumer import canonical_json_bytes


GAME_INPUT_SCHEMA_VERSION = "SPORTS_STAGE3_GOVERNED_PREGAME_GAME_INPUT_V1"
GAME_READINESS_SCHEMA_VERSION = "SPORTS_STAGE3_GAME_READINESS_V1"
LINEUP_SIZE = 9
TEMPLATE_ROWS = 18
EXPECTED_SOURCE_FEATURE_COUNT = 234

SIMULATION_STATE_FEATURES: tuple[str, ...] = (
    "context_inning",
    "context_top_bottom",
    "context_outs_before",
    "context_base_mask_before",
    "context_batting_score_diff_before",
)

_SIDE_ORDER: tuple[str, ...] = ("AWAY",) * LINEUP_SIZE + ("HOME",) * LINEUP_SIZE
_SLOT_ORDER: tuple[int, ...] = tuple(range(1, LINEUP_SIZE + 1)) * 2
_FORBIDDEN_PREDICTOR_NAMES = {
    "outcome",
    "target",
    "target_outcome",
    "actual_outcome",
    "actual_home_runs",
    "actual_away_runs",
    "home_final_score",
    "away_final_score",
    "winner",
    "runs_scored",
}
_FORBIDDEN_PREDICTOR_FRAGMENTS = (
    "sportsbook",
    "betting_odds",
    "market_odds",
    "actual_substitution",
    "actual_reliever",
)


class Stage3GameInputError(ValueError):
    """A governed game cannot cross the pregame feature boundary."""

    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self)}


def _fail(code: str, message: str) -> Stage3GameInputError:
    return Stage3GameInputError(code, message)


def _mapping(value: Any, *, code: str, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(code, f"{label} must be a governed evidence object.")
    return value


def _aliases(value: Mapping[str, Any], *names: str, required: bool = True) -> Any:
    present = [(name, value[name]) for name in names if name in value]
    if len(present) > 1:
        first = present[0][1]
        if any(candidate != first for _, candidate in present[1:]):
            raise _fail(
                "PREGAME_EVIDENCE_ALIAS_CONFLICT",
                f"Conflicting aliases were supplied for {names[0]}.",
            )
    if present:
        return present[0][1]
    if required:
        raise _fail(
            "PREGAME_EVIDENCE_FIELD_MISSING",
            f"Required governed evidence field {names[0]} is missing.",
        )
    return None


def _identifier(value: Any, *, code: str, label: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise _fail(code, f"{label} must be a non-empty canonical identifier.")
    return value


def _sha256(value: Any, *, code: str, label: str) -> str:
    digest = _identifier(value, code=code, label=label).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise _fail(code, f"{label} must be a lowercase SHA-256 digest.")
    return digest


def _instant(value: Any, *, code: str, label: str) -> datetime:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise _fail(code, f"{label} must be an explicit timezone-aware ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _fail(code, f"{label} must be an explicit timezone-aware ISO timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _fail(code, f"{label} must include a timezone offset.")
    return parsed.astimezone(timezone.utc)


def _canonical_instant(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _authority(
    raw: Any,
    *,
    kind: str,
    accepted_statuses: set[str],
    scheduled_first_pitch: datetime | None = None,
) -> dict[str, str]:
    evidence = _mapping(
        raw,
        code=f"GOVERNED_PREGAME_{kind}_AUTHORITY_UNAVAILABLE",
        label=f"{kind.lower()} evidence",
    )
    status = str(_aliases(evidence, "status", required=False) or "").upper()
    if status not in accepted_statuses:
        raise _fail(
            f"GOVERNED_PREGAME_{kind}_AUTHORITY_UNAVAILABLE",
            f"{kind.title()} evidence must be confirmed under a governed authority; {status or 'MISSING'} is not scoreable.",
        )
    result = {
        "status": status,
        "authorityId": _identifier(
            _aliases(evidence, "authorityId", "authority_id"),
            code=f"GOVERNED_PREGAME_{kind}_AUTHORITY_UNAVAILABLE",
            label=f"{kind.lower()} authority ID",
        ),
        "sourceId": _identifier(
            _aliases(evidence, "sourceId", "source_id"),
            code=f"GOVERNED_PREGAME_{kind}_AUTHORITY_UNAVAILABLE",
            label=f"{kind.lower()} source ID",
        ),
        "checksumSha256": _sha256(
            _aliases(evidence, "checksumSha256", "checksum_sha256"),
            code=f"GOVERNED_PREGAME_{kind}_AUTHORITY_UNAVAILABLE",
            label=f"{kind.lower()} evidence checksum",
        ),
    }
    authority_times: dict[str, datetime] = {}
    for public_name, aliases in (
        ("sourceCutoff", ("sourceCutoff", "source_cutoff")),
        ("observationTimestamp", ("observationTimestamp", "observation_timestamp")),
        ("receiptTimestamp", ("receiptTimestamp", "receipt_timestamp")),
    ):
        raw_time = _aliases(evidence, *aliases, required=False)
        if raw_time is None:
            continue
        parsed = _instant(
            raw_time,
            code=f"GOVERNED_PREGAME_{kind}_TIMESTAMP_INVALID",
            label=f"{kind.lower()} {public_name}",
        )
        if scheduled_first_pitch is not None and parsed >= scheduled_first_pitch:
            raise _fail(
                f"GOVERNED_PREGAME_{kind}_EVIDENCE_LATE",
                f"{kind.title()} evidence timestamps must precede scheduled first pitch.",
            )
        authority_times[public_name] = parsed
        result[public_name] = _canonical_instant(parsed)
    cutoff = authority_times.get("sourceCutoff")
    observed = authority_times.get("observationTimestamp")
    received = authority_times.get("receiptTimestamp")
    if cutoff and observed and cutoff > observed or observed and received and observed > received:
        raise _fail(
            f"GOVERNED_PREGAME_{kind}_CHRONOLOGY_INVALID",
            f"{kind.title()} evidence timestamps are not chronological.",
        )
    return result


def _lineup(
    lineup_evidence: Mapping[str, Any], side: str
) -> tuple[tuple[int, str], ...]:
    raw = _aliases(lineup_evidence, side.lower())
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != LINEUP_SIZE:
        raise _fail(
            "CONFIRMED_LINEUP_INCOMPLETE",
            f"The confirmed {side.lower()} lineup must contain exactly nine ordered batters.",
        )
    output: list[tuple[int, str]] = []
    for index, item in enumerate(raw, start=1):
        row = _mapping(
            item,
            code="CONFIRMED_LINEUP_INVALID",
            label=f"{side.lower()} lineup slot {index}",
        )
        record_type = _aliases(row, "recordType", "record_type", required=False)
        if record_type is not None and str(record_type).upper() not in {
            "START",
            "STARTER",
            "CONFIRMED_START",
        }:
            raise _fail(
                "ACTUAL_SUBSTITUTION_EVIDENCE_PROHIBITED",
                "Confirmed lineup evidence may contain starting participants only.",
            )
        try:
            slot = int(_aliases(row, "battingOrderSlot", "batting_order_slot"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise _fail(
                "CONFIRMED_LINEUP_INVALID",
                f"The {side.lower()} batting-order slot must be an integer.",
            ) from exc
        if isinstance(_aliases(row, "battingOrderSlot", "batting_order_slot"), bool) or slot != index:
            raise _fail(
                "CONFIRMED_LINEUP_ORDER_INVALID",
                f"The confirmed {side.lower()} lineup must be ordered in exact slots 1 through 9.",
            )
        player_id = _identifier(
            _aliases(row, "canonicalPlayerId", "canonical_player_id"),
            code="CONFIRMED_LINEUP_PLAYER_ID_INVALID",
            label=f"{side.lower()} batter canonical player ID",
        )
        output.append((slot, player_id))
    players = [player for _, player in output]
    if len(set(players)) != LINEUP_SIZE:
        raise _fail(
            "CONFIRMED_LINEUP_DUPLICATE_PLAYER",
            f"The confirmed {side.lower()} lineup must contain nine unique canonical player IDs.",
        )
    return tuple(output)


def _starter(starter_evidence: Mapping[str, Any], side: str) -> str:
    row = _mapping(
        _aliases(starter_evidence, side.lower()),
        code="ANNOUNCED_STARTER_INVALID",
        label=f"{side.lower()} announced starter",
    )
    role = _aliases(row, "role", "pitcherRole", "pitcher_role", required=False)
    if role is not None and str(role).upper() not in {
        "STARTER",
        "ANNOUNCED_STARTER",
        "STARTING_PITCHER",
    }:
        raise _fail(
            "ACTUAL_RELIEVER_EVIDENCE_PROHIBITED",
            "Starter evidence cannot bind an actual reliever.",
        )
    return _identifier(
        _aliases(row, "canonicalPlayerId", "canonical_player_id"),
        code="ANNOUNCED_STARTER_PLAYER_ID_INVALID",
        label=f"{side.lower()} announced starter canonical player ID",
    )


def _feature_order(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise _fail(
            "STAGE3_FEATURE_ORDER_INVALID",
            "The Stage 3 feature order must be an ordered sequence.",
        )
    ordered = tuple(values)
    if (
        len(ordered) != EXPECTED_SOURCE_FEATURE_COUNT
        or any(not isinstance(name, str) or not name or name.strip() != name for name in ordered)
        or len(set(ordered)) != len(ordered)
    ):
        raise _fail(
            "STAGE3_FEATURE_ORDER_INVALID",
            "The Stage 3 scoring contract requires exactly 234 unique ordered source predictors.",
        )
    if any(ordered.count(name) != 1 for name in SIMULATION_STATE_FEATURES):
        raise _fail(
            "SIMULATION_STATE_FEATURE_CONTRACT_INVALID",
            "The artifact feature order must contain each of the five simulated-state predictors exactly once.",
        )
    lowered = tuple(name.lower() for name in ordered)
    if any(name in _FORBIDDEN_PREDICTOR_NAMES for name in lowered) or any(
        fragment in name for name in lowered for fragment in _FORBIDDEN_PREDICTOR_FRAGMENTS
    ):
        raise _fail(
            "PROHIBITED_GAME_PREDICTOR",
            "Target, actual-participant, result, and sportsbook fields are prohibited from the scoring feature contract.",
        )
    return ordered


def _missing(value: Any) -> bool:
    if value is None:
        return True
    if type(value).__name__ in {"NAType", "NaTType"}:
        return True
    try:
        result = value != value
    except Exception:
        return False
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False


def _canonical_feature_value(
    value: Any, *, feature: str, authorized_missing: frozenset[str]
) -> Any:
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if _missing(value):
        if feature not in authorized_missing:
            raise _fail(
                "PREGAME_REQUIRED_FEATURE_MISSING",
                f"Required pregame predictor {feature} is missing without contract authorization.",
            )
        return None
    if isinstance(value, float) and not math.isfinite(value):
        raise _fail(
            "PREGAME_FEATURE_VALUE_INVALID",
            f"Pregame predictor {feature} contains an infinite value.",
        )
    if not isinstance(value, (str, int, float, bool)):
        raise _fail(
            "PREGAME_FEATURE_VALUE_INVALID",
            f"Pregame predictor {feature} is not a scalar model input.",
        )
    return value


@dataclass(frozen=True)
class Stage3PregameTemplate:
    batting_side: str
    batting_order_slot: int
    batter_canonical_player_id: str
    pitcher_canonical_player_id: str
    frozen_predictor_names: tuple[str, ...]
    frozen_predictor_values: tuple[Any, ...]
    feature_row_sha256: str

    def predictor_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(dict(zip(self.frozen_predictor_names, self.frozen_predictor_values)))

    def record(self) -> dict[str, Any]:
        return {
            "battingSide": self.batting_side,
            "battingOrderSlot": self.batting_order_slot,
            "batterCanonicalPlayerId": self.batter_canonical_player_id,
            "pitcherCanonicalPlayerId": self.pitcher_canonical_player_id,
            "featureRowSha256": self.feature_row_sha256,
        }


@dataclass(frozen=True)
class Stage3GameInputs:
    canonical_game_id: str
    canonical_away_team_id: str
    canonical_home_team_id: str
    scheduled_first_pitch: str
    game_date: str
    observation_timestamp: str
    receipt_timestamp: str
    source_cutoff: str
    ordered_features: tuple[str, ...]
    non_simulation_features: tuple[str, ...]
    templates: tuple[Stage3PregameTemplate, ...]
    lineup_authority: Mapping[str, str]
    starter_authority: Mapping[str, str]
    feature_authority: Mapping[str, str]
    feature_vector_sha256: str

    @property
    def away_batter_ids(self) -> tuple[str, ...]:
        return tuple(row.batter_canonical_player_id for row in self.templates[:LINEUP_SIZE])

    @property
    def home_batter_ids(self) -> tuple[str, ...]:
        return tuple(row.batter_canonical_player_id for row in self.templates[LINEUP_SIZE:])

    @property
    def away_starter_id(self) -> str:
        return self.templates[LINEUP_SIZE].pitcher_canonical_player_id

    @property
    def home_starter_id(self) -> str:
        return self.templates[0].pitcher_canonical_player_id

    def record(self) -> dict[str, Any]:
        return {
            "schemaVersion": GAME_INPUT_SCHEMA_VERSION,
            "gameId": self.canonical_game_id,
            "gameDate": self.game_date,
            "awayTeamId": self.canonical_away_team_id,
            "homeTeamId": self.canonical_home_team_id,
            "scheduledFirstPitch": self.scheduled_first_pitch,
            "observationTimestamp": self.observation_timestamp,
            "receiptTimestamp": self.receipt_timestamp,
            "featureCutoff": self.source_cutoff,
            "templateCount": len(self.templates),
            "featureCount": len(self.ordered_features),
            "nonSimulationFeatureCount": len(self.non_simulation_features),
            "simulationGeneratedStateFeatures": list(SIMULATION_STATE_FEATURES),
            "lineupAuthority": dict(self.lineup_authority),
            "starterAuthority": dict(self.starter_authority),
            "featureAuthority": dict(self.feature_authority),
            "featureVectorSha256": self.feature_vector_sha256,
            "templates": [row.record() for row in self.templates],
            "confirmedStartingLineupsOnly": True,
            "announcedStartersHeldConstant": True,
            "actualSubstitutionsUsed": False,
            "actualRelieversUsed": False,
            "targetGameOutcomesRead": False,
            "providerCalls": 0,
        }


@dataclass(frozen=True)
class GameInputReadiness:
    game_id: str | None
    game_date: str | None
    away_team_id: str | None
    home_team_id: str | None
    scheduled_first_pitch: str | None
    lineup_evidence: Mapping[str, Any] | None
    starter_evidence: Mapping[str, Any] | None
    feature_cutoff: str | None
    missing_predictors: tuple[str, ...]
    scoreable: bool
    blocked_reasons: tuple[Mapping[str, str], ...]

    @property
    def status(self) -> str:
        return "SCOREABLE" if self.scoreable else "BLOCKED"

    def record(self) -> dict[str, Any]:
        return {
            "schemaVersion": GAME_READINESS_SCHEMA_VERSION,
            "gameId": self.game_id,
            "gameDate": self.game_date,
            "awayTeamId": self.away_team_id,
            "homeTeamId": self.home_team_id,
            "scheduledFirstPitch": self.scheduled_first_pitch,
            "lineupEvidence": dict(self.lineup_evidence) if self.lineup_evidence else None,
            "starterEvidence": dict(self.starter_evidence) if self.starter_evidence else None,
            "featureCutoff": self.feature_cutoff,
            "missingPredictors": list(self.missing_predictors),
            "scoreable": self.scoreable,
            "status": self.status,
            "blockedReasons": [dict(item) for item in self.blocked_reasons],
        }


@dataclass(frozen=True)
class GameInputPreparation:
    readiness: GameInputReadiness
    game_inputs: Stage3GameInputs | None


def build_stage3_game_inputs(
    evidence: Mapping[str, Any],
    *,
    ordered_features: Sequence[str],
    authorized_missing_predictors: Sequence[str] = (),
) -> Stage3GameInputs:
    """Validate governed pregame evidence and materialize exactly eighteen templates.

    ``authorized_missing_predictors`` must come from the registered missingness contract;
    the evidence object is never allowed to authorize its own missing fields.
    """

    source = _mapping(
        evidence,
        code="GOVERNED_PREGAME_GAME_AUTHORITY_UNAVAILABLE",
        label="pregame game evidence",
    )
    features = _feature_order(ordered_features)
    non_simulation = tuple(name for name in features if name not in SIMULATION_STATE_FEATURES)
    if len(non_simulation) != EXPECTED_SOURCE_FEATURE_COUNT - len(SIMULATION_STATE_FEATURES):
        raise _fail(
            "SIMULATION_STATE_FEATURE_CONTRACT_INVALID",
            "Exactly 229 predictors must remain frozen after the five simulated-state fields are removed.",
        )
    missing_authority = frozenset(authorized_missing_predictors)
    if not missing_authority.issubset(non_simulation):
        raise _fail(
            "MISSINGNESS_CONTRACT_INVALID",
            "Authorized missing predictors must be a subset of the 229 frozen predictors.",
        )

    game_id = _identifier(
        _aliases(source, "canonicalGameId", "canonical_game_id"),
        code="CANONICAL_GAME_ID_UNRESOLVED",
        label="canonical game ID",
    )
    away_team_id = _identifier(
        _aliases(source, "canonicalAwayTeamId", "canonical_away_team_id"),
        code="CANONICAL_TEAM_ID_UNRESOLVED",
        label="canonical away team ID",
    )
    home_team_id = _identifier(
        _aliases(source, "canonicalHomeTeamId", "canonical_home_team_id"),
        code="CANONICAL_TEAM_ID_UNRESOLVED",
        label="canonical home team ID",
    )
    if away_team_id == home_team_id:
        raise _fail(
            "CANONICAL_TEAM_ID_AMBIGUOUS",
            "Home and away canonical team IDs must be distinct.",
        )

    first_pitch = _instant(
        _aliases(source, "scheduledFirstPitch", "scheduled_first_pitch"),
        code="SCHEDULED_FIRST_PITCH_INVALID",
        label="scheduled first pitch",
    )
    observed = _instant(
        _aliases(source, "observationTimestamp", "observation_timestamp"),
        code="PREGAME_OBSERVATION_TIMESTAMP_INVALID",
        label="pregame observation timestamp",
    )
    received = _instant(
        _aliases(source, "receiptTimestamp", "receipt_timestamp"),
        code="PREGAME_RECEIPT_TIMESTAMP_INVALID",
        label="pregame receipt timestamp",
    )
    cutoff = _instant(
        _aliases(source, "sourceCutoff", "source_cutoff", "featureCutoff"),
        code="PREGAME_FEATURE_CUTOFF_INVALID",
        label="pregame source cutoff",
    )
    if not cutoff <= observed <= received:
        raise _fail(
            "PREGAME_EVIDENCE_CHRONOLOGY_INVALID",
            "Pregame evidence must satisfy source cutoff <= observation <= receipt.",
        )
    if any(value >= first_pitch for value in (cutoff, observed, received)):
        raise _fail(
            "PREGAME_EVIDENCE_LATE",
            "Source cutoff, observation, and receipt must all precede scheduled first pitch.",
        )

    lineup_raw = _mapping(
        _aliases(source, "lineupEvidence", "lineup_evidence", required=False),
        code="GOVERNED_PREGAME_LINEUP_AUTHORITY_UNAVAILABLE",
        label="lineup evidence",
    )
    lineup_authority = _authority(
        lineup_raw,
        kind="LINEUP",
        accepted_statuses={"CONFIRMED"},
        scheduled_first_pitch=first_pitch,
    )
    away_lineup = _lineup(lineup_raw, "AWAY")
    home_lineup = _lineup(lineup_raw, "HOME")

    starter_raw = _mapping(
        _aliases(source, "starterEvidence", "starter_evidence", required=False),
        code="GOVERNED_PREGAME_STARTER_AUTHORITY_UNAVAILABLE",
        label="starter evidence",
    )
    starter_authority = _authority(
        starter_raw,
        kind="STARTER",
        accepted_statuses={"ANNOUNCED", "CONFIRMED", "ANNOUNCED_CONFIRMED"},
        scheduled_first_pitch=first_pitch,
    )
    away_starter = _starter(starter_raw, "AWAY")
    home_starter = _starter(starter_raw, "HOME")

    feature_raw = _mapping(
        _aliases(source, "featureEvidence", "feature_evidence", required=False),
        code="GOVERNED_PREGAME_FEATURE_AUTHORITY_UNAVAILABLE",
        label="pregame feature evidence",
    )
    feature_authority = _authority(
        feature_raw,
        kind="FEATURE",
        accepted_statuses={"COMPLETE", "VERIFIED"},
        scheduled_first_pitch=first_pitch,
    )
    rows = _aliases(feature_raw, "templates", "rows", required=False)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)) or len(rows) != TEMPLATE_ROWS:
        raise _fail(
            "PREGAME_FEATURE_TEMPLATE_COUNT_INVALID",
            "Pregame feature evidence must contain exactly eighteen ordered templates.",
        )

    expected_players = tuple(player for _, player in away_lineup + home_lineup)
    templates: list[Stage3PregameTemplate] = []
    for index, raw_row in enumerate(rows):
        row = _mapping(
            raw_row,
            code="PREGAME_FEATURE_TEMPLATE_INVALID",
            label=f"pregame template {index + 1}",
        )
        normalized_row_keys = {
            "".join(character for character in str(name).lower() if character.isalnum())
            for name in row
        }
        if normalized_row_keys.intersection(
            {
                "outcome",
                "targetoutcome",
                "actualoutcome",
                "actualresult",
                "actualrelieverid",
                "actualsubstitutionid",
                "homescorefinal",
                "awayscorefinal",
            }
        ):
            raise _fail(
                "TARGET_GAME_RESULT_OR_PARTICIPANT_EVIDENCE_PROHIBITED",
                "Pregame templates must not carry target outcomes, final scores, substitutions, or actual relievers.",
            )
        side = str(_aliases(row, "battingSide", "batting_side")).upper()
        try:
            slot_raw = _aliases(row, "battingOrderSlot", "batting_order_slot")
            slot = int(slot_raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise _fail(
                "PREGAME_FEATURE_TEMPLATE_ORDER_INVALID",
                "Every template batting-order slot must be an integer.",
            ) from exc
        if isinstance(slot_raw, bool) or side != _SIDE_ORDER[index] or slot != _SLOT_ORDER[index]:
            raise _fail(
                "PREGAME_FEATURE_TEMPLATE_ORDER_INVALID",
                "Templates must be ordered AWAY slots 1-9 followed by HOME slots 1-9.",
            )
        batter_id = _identifier(
            _aliases(row, "batterCanonicalPlayerId", "batter_canonical_player_id"),
            code="PREGAME_FEATURE_BATTER_ID_INVALID",
            label="template batter canonical player ID",
        )
        pitcher_id = _identifier(
            _aliases(row, "pitcherCanonicalPlayerId", "pitcher_canonical_player_id"),
            code="PREGAME_FEATURE_PITCHER_ID_INVALID",
            label="template pitcher canonical player ID",
        )
        expected_pitcher = home_starter if side == "AWAY" else away_starter
        if batter_id != expected_players[index] or pitcher_id != expected_pitcher:
            raise _fail(
                "PREGAME_TEMPLATE_PARTICIPANT_MISMATCH",
                "Template participants must exactly match the confirmed lineup and opposing announced starter.",
            )
        predictors = _mapping(
            _aliases(row, "predictors", "frozenPredictors", "frozen_predictors"),
            code="PREGAME_FEATURE_VECTOR_INVALID",
            label="template frozen predictors",
        )
        if any(name in predictors for name in SIMULATION_STATE_FEATURES):
            raise _fail(
                "ACTUAL_TARGET_GAME_STATE_PROHIBITED",
                "The five simulation-generated state fields must not be read from target-game evidence.",
            )
        if tuple(predictors.keys()) != non_simulation:
            missing = [name for name in non_simulation if name not in predictors]
            unexpected = [str(name) for name in predictors if name not in non_simulation]
            raise _fail(
                "PREGAME_FEATURE_ORDER_MISMATCH",
                "Frozen predictors must contain the exact 229 non-simulation fields in artifact order"
                f" (missing={missing[:3]}, unexpected={unexpected[:3]}).",
            )
        values = tuple(
            _canonical_feature_value(
                predictors[name], feature=name, authorized_missing=missing_authority
            )
            for name in non_simulation
        )
        row_payload = {
            "gameId": game_id,
            "battingSide": side,
            "battingOrderSlot": slot,
            "batterCanonicalPlayerId": batter_id,
            "pitcherCanonicalPlayerId": pitcher_id,
            "frozenPredictors": list(zip(non_simulation, values)),
        }
        row_sha = hashlib.sha256(canonical_json_bytes(row_payload)).hexdigest()
        templates.append(
            Stage3PregameTemplate(
                batting_side=side,
                batting_order_slot=slot,
                batter_canonical_player_id=batter_id,
                pitcher_canonical_player_id=pitcher_id,
                frozen_predictor_names=non_simulation,
                frozen_predictor_values=values,
                feature_row_sha256=row_sha,
            )
        )

    vector_payload = {
        "schemaVersion": GAME_INPUT_SCHEMA_VERSION,
        "gameId": game_id,
        "sourceCutoff": _canonical_instant(cutoff),
        "orderedFeatures": list(features),
        "rowShas": [row.feature_row_sha256 for row in templates],
        "lineupChecksumSha256": lineup_authority["checksumSha256"],
        "starterChecksumSha256": starter_authority["checksumSha256"],
        "featureAuthorityChecksumSha256": feature_authority["checksumSha256"],
    }
    feature_vector_sha = hashlib.sha256(canonical_json_bytes(vector_payload)).hexdigest()
    declared_vector_sha = _aliases(
        feature_raw, "featureVectorSha256", "feature_vector_sha256", required=False
    )
    if declared_vector_sha is not None and _sha256(
        declared_vector_sha,
        code="PREGAME_FEATURE_VECTOR_CHECKSUM_INVALID",
        label="declared feature-vector checksum",
    ) != feature_vector_sha:
        raise _fail(
            "PREGAME_FEATURE_VECTOR_CHECKSUM_MISMATCH",
            "The declared feature-vector checksum differs from the eighteen governed templates.",
        )

    return Stage3GameInputs(
        canonical_game_id=game_id,
        canonical_away_team_id=away_team_id,
        canonical_home_team_id=home_team_id,
        scheduled_first_pitch=_canonical_instant(first_pitch),
        game_date=first_pitch.date().isoformat(),
        observation_timestamp=_canonical_instant(observed),
        receipt_timestamp=_canonical_instant(received),
        source_cutoff=_canonical_instant(cutoff),
        ordered_features=features,
        non_simulation_features=non_simulation,
        templates=tuple(templates),
        lineup_authority=MappingProxyType(lineup_authority),
        starter_authority=MappingProxyType(starter_authority),
        feature_authority=MappingProxyType(feature_authority),
        feature_vector_sha256=feature_vector_sha,
    )


def prepare_stage3_game_inputs(
    evidence: Mapping[str, Any] | None,
    *,
    ordered_features: Sequence[str],
    authorized_missing_predictors: Sequence[str] = (),
) -> GameInputPreparation:
    """Return scoreable inputs or an exact blocked readiness record without I/O."""

    if evidence is None:
        reasons = (
            {
                "code": "GOVERNED_PREGAME_GAME_AUTHORITY_UNAVAILABLE",
                "message": "No governed pregame game inventory is configured in Model Studio.",
            },
            {
                "code": "GOVERNED_PREGAME_LINEUP_AUTHORITY_UNAVAILABLE",
                "message": "Confirmed point-in-time lineup authority is unavailable.",
            },
            {
                "code": "GOVERNED_PREGAME_STARTER_AUTHORITY_UNAVAILABLE",
                "message": "Confirmed announced-starter authority is unavailable.",
            },
        )
        readiness = GameInputReadiness(
            game_id=None,
            game_date=None,
            away_team_id=None,
            home_team_id=None,
            scheduled_first_pitch=None,
            lineup_evidence=None,
            starter_evidence=None,
            feature_cutoff=None,
            missing_predictors=(),
            scoreable=False,
            blocked_reasons=tuple(MappingProxyType(dict(item)) for item in reasons),
        )
        return GameInputPreparation(readiness=readiness, game_inputs=None)

    try:
        game_inputs = build_stage3_game_inputs(
            evidence,
            ordered_features=ordered_features,
            authorized_missing_predictors=authorized_missing_predictors,
        )
    except Stage3GameInputError as exc:
        def safe(*names: str) -> Any:
            try:
                return _aliases(evidence, *names, required=False)
            except Stage3GameInputError:
                return None

        scheduled = safe("scheduledFirstPitch", "scheduled_first_pitch")
        game_date = scheduled[:10] if isinstance(scheduled, str) and len(scheduled) >= 10 else None
        feature = safe("featureEvidence", "feature_evidence")
        missing: tuple[str, ...] = ()
        if isinstance(feature, Mapping):
            raw_missing = feature.get("missingPredictors") or feature.get("missing_predictors") or []
            if isinstance(raw_missing, list):
                missing = tuple(str(item) for item in raw_missing)
        readiness = GameInputReadiness(
            game_id=safe("canonicalGameId", "canonical_game_id"),
            game_date=game_date,
            away_team_id=safe("canonicalAwayTeamId", "canonical_away_team_id"),
            home_team_id=safe("canonicalHomeTeamId", "canonical_home_team_id"),
            scheduled_first_pitch=scheduled,
            lineup_evidence=safe("lineupEvidence", "lineup_evidence") if isinstance(safe("lineupEvidence", "lineup_evidence"), Mapping) else None,
            starter_evidence=safe("starterEvidence", "starter_evidence") if isinstance(safe("starterEvidence", "starter_evidence"), Mapping) else None,
            feature_cutoff=safe("sourceCutoff", "source_cutoff", "featureCutoff"),
            missing_predictors=missing,
            scoreable=False,
            blocked_reasons=(MappingProxyType(exc.public_detail()),),
        )
        return GameInputPreparation(readiness=readiness, game_inputs=None)

    readiness = GameInputReadiness(
        game_id=game_inputs.canonical_game_id,
        game_date=game_inputs.game_date,
        away_team_id=game_inputs.canonical_away_team_id,
        home_team_id=game_inputs.canonical_home_team_id,
        scheduled_first_pitch=game_inputs.scheduled_first_pitch,
        lineup_evidence=game_inputs.lineup_authority,
        starter_evidence=game_inputs.starter_authority,
        feature_cutoff=game_inputs.source_cutoff,
        missing_predictors=(),
        scoreable=True,
        blocked_reasons=(),
    )
    return GameInputPreparation(readiness=readiness, game_inputs=game_inputs)


__all__ = [
    "EXPECTED_SOURCE_FEATURE_COUNT",
    "GAME_INPUT_SCHEMA_VERSION",
    "GAME_READINESS_SCHEMA_VERSION",
    "GameInputPreparation",
    "GameInputReadiness",
    "LINEUP_SIZE",
    "SIMULATION_STATE_FEATURES",
    "Stage3GameInputError",
    "Stage3GameInputs",
    "Stage3PregameTemplate",
    "TEMPLATE_ROWS",
    "build_stage3_game_inputs",
    "prepare_stage3_game_inputs",
]
