"""Point-in-time contracts for NFL quarterback, personnel, and injury evidence.

The module is deliberately free of network, database, model, and publication
side effects.  Finalized historical snapshots are not upgraded to point-in-
time evidence merely because they contain a date column.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence


CONTRACT = "NFL_PREGAME_PERSONNEL_EVIDENCE_V1"


class EvidenceError(ValueError):
    """Raised when evidence cannot safely enter a pregame feature."""


class Admissibility(str, Enum):
    HISTORICALLY_POINT_IN_TIME_ADMISSIBLE = "HISTORICALLY_POINT_IN_TIME_ADMISSIBLE"
    RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY = "RECONSTRUCTED_HISTORICAL_RESEARCH_ONLY"
    PROSPECTIVE_ONLY = "PROSPECTIVE_ONLY"
    PROHIBITED_POSTGAME_EVIDENCE = "PROHIBITED_POSTGAME_EVIDENCE"


class Missingness(str, Enum):
    PLAYER_ABSENT_FROM_REPORT = "PLAYER_ABSENT_FROM_REPORT"
    PLAYER_REPORTED_HEALTHY = "PLAYER_REPORTED_HEALTHY"
    SOURCE_NOT_PUBLISHED = "SOURCE_NOT_PUBLISHED"
    PLAYER_IDENTITY_UNRESOLVED = "PLAYER_IDENTITY_UNRESOLVED"
    STATUS_UNKNOWN = "STATUS_UNKNOWN"
    NO_PRIOR_NFL_HISTORY = "NO_PRIOR_NFL_HISTORY"
    NO_PRIOR_START = "NO_PRIOR_START"
    STRUCTURAL_NOT_APPLICABLE = "STRUCTURAL_NOT_APPLICABLE"


PRACTICE_STATUS = frozenset({"DID_NOT_PARTICIPATE", "LIMITED", "FULL", "OUT", "NOT_LISTED", "UNKNOWN"})
GAME_STATUS = frozenset({"OUT", "DOUBTFUL", "QUESTIONABLE", "PROBABLE", "NO_DESIGNATION", "NOTE", "UNKNOWN"})
ROSTER_STATUS = frozenset({"ACTIVE", "INACTIVE", "RESERVE", "PRACTICE_SQUAD", "UNKNOWN"})
EXPECTED_ROLE = frozenset({"STARTER", "BACKUP", "ROTATION", "SPECIAL_TEAMS", "UNKNOWN"})
EXPECTED_AVAILABILITY = frozenset({"EXPECTED_ACTIVE", "EXPECTED_INACTIVE", "UNCERTAIN", "UNKNOWN"})
POSITION_GROUP = frozenset({"QB", "OFFENSIVE_LINE", "SKILL", "DEFENSIVE_FRONT", "SECONDARY", "SPECIAL_TEAMS", "OTHER", "UNKNOWN"})


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise EvidenceError(f"{field} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class PregamePersonnelRecord:
    canonical_game_id: str
    canonical_player_id: str
    canonical_team_id: str
    source_id: str
    source_asset_id: str
    source_release_id: str
    source_publication_time_utc: str | None
    retrieval_time_utc: str
    effective_time_utc: str
    scheduled_kickoff_utc: str
    feature_cutoff_utc: str
    practice_status: str
    game_status: str
    roster_status: str
    expected_role: str
    position_group: str
    expected_availability: str
    confirmed_inactive: bool | None
    actual_participation: bool | None
    revision: int
    predecessor_sha256: str | None
    source_row_sha256: str
    admissibility: Admissibility

    def validate(self) -> None:
        for name in ("canonical_game_id", "canonical_player_id", "canonical_team_id", "source_id",
                     "source_asset_id", "source_release_id", "source_row_sha256"):
            if not str(getattr(self, name)).strip():
                raise EvidenceError(f"{name} is required; display-name-only identity is forbidden")
        if len(self.source_row_sha256) != 64:
            raise EvidenceError("source_row_sha256 must be a physical SHA-256")
        if self.practice_status not in PRACTICE_STATUS or self.game_status not in GAME_STATUS:
            raise EvidenceError("injury status is outside the frozen vocabulary")
        if self.roster_status not in ROSTER_STATUS or self.expected_role not in EXPECTED_ROLE:
            raise EvidenceError("roster/role state is outside the frozen vocabulary")
        if self.position_group not in POSITION_GROUP:
            raise EvidenceError("position group is outside the frozen vocabulary")
        if self.expected_availability not in EXPECTED_AVAILABILITY:
            raise EvidenceError("expected availability is outside the frozen vocabulary")
        if self.revision < 1:
            raise EvidenceError("revision must be positive")
        cutoff = _utc(self.feature_cutoff_utc, "feature_cutoff_utc")
        kickoff = _utc(self.scheduled_kickoff_utc, "scheduled_kickoff_utc")
        retrieved = _utc(self.retrieval_time_utc, "retrieval_time_utc")
        effective = _utc(self.effective_time_utc, "effective_time_utc")
        published = _utc(self.source_publication_time_utc, "source_publication_time_utc") if self.source_publication_time_utc else None
        if cutoff >= kickoff:
            raise EvidenceError("feature cutoff must precede kickoff")
        if self.admissibility is Admissibility.HISTORICALLY_POINT_IN_TIME_ADMISSIBLE:
            if published is None or published > cutoff or effective > cutoff:
                raise EvidenceError("historical point-in-time evidence requires a proven pre-cutoff publication and effective time")
        if published is not None and published > retrieved:
            raise EvidenceError("source publication time cannot follow retrieval time")
        if self.admissibility is Admissibility.PROSPECTIVE_ONLY:
            if retrieved > cutoff or published is None or published > cutoff or effective > cutoff:
                raise EvidenceError("captured prospective evidence requires pre-cutoff retrieval, publication, and effectivity")
        if self.actual_participation is not None:
            raise EvidenceError("actual target-game participation is prohibited in a pregame record")
        if self.confirmed_inactive is not None and published is None:
            raise EvidenceError("confirmed inactive requires a timestamped source publication")

    def content(self) -> dict[str, Any]:
        value = asdict(self)
        value["admissibility"] = self.admissibility.value
        value["schemaVersion"] = CONTRACT
        return value

    def digest(self) -> str:
        self.validate()
        return sha256_json(self.content())


def append_revision(existing: Sequence[PregamePersonnelRecord], candidate: PregamePersonnelRecord) -> tuple[PregamePersonnelRecord, ...]:
    """Append one correction without overwriting or reordering source state."""
    candidate.validate()
    rows = tuple(existing)
    if not rows:
        if candidate.revision != 1 or candidate.predecessor_sha256 is not None:
            raise EvidenceError("first revision must be revision 1 without a predecessor")
        return (candidate,)
    for row in rows:
        row.validate()
    natural = lambda row: (row.canonical_game_id, row.canonical_player_id, row.canonical_team_id, row.source_id)
    if any(natural(row) != natural(candidate) for row in rows):
        raise EvidenceError("revision chain changed its canonical natural key")
    last = rows[-1]
    if candidate.revision != last.revision + 1 or candidate.predecessor_sha256 != last.digest():
        raise EvidenceError("revision/predecessor does not extend the immutable chain")
    if _utc(candidate.retrieval_time_utc, "retrieval_time_utc") < _utc(last.retrieval_time_utc, "retrieval_time_utc"):
        raise EvidenceError("retrieval time moved backwards")
    if candidate.source_publication_time_utc and last.source_publication_time_utc:
        if _utc(candidate.source_publication_time_utc, "source_publication_time_utc") < _utc(last.source_publication_time_utc, "source_publication_time_utc"):
            raise EvidenceError("source publication time moved backwards")
    return rows + (candidate,)


def resolve_canonical_player(source_ids: Mapping[str, str | None], identity_rows: Iterable[Mapping[str, Any]]) -> str:
    """Resolve by exact governed IDs only; names are intentionally ignored."""
    usable = {str(key): str(value) for key, value in source_ids.items() if value is not None and str(value).strip()}
    if not usable:
        raise EvidenceError("no source player identifier supplied")
    matches: set[str] = set()
    for row in identity_rows:
        if any(str(row.get(key) or "") == value for key, value in usable.items()):
            canonical = str(row.get("canonical_player_id") or "")
            if canonical:
                matches.add(canonical)
    if len(matches) != 1:
        raise EvidenceError("player identity is unresolved or ambiguous")
    return next(iter(matches))


def normalize_injury_status(value: Any, *, kind: str) -> str:
    text = " ".join(str(value or "").split()).casefold()
    if kind == "practice":
        mapping = {
            "did not participate in practice": "DID_NOT_PARTICIPATE",
            "limited participation in practice": "LIMITED",
            "full participation in practice": "FULL",
            "out (definitely will not play)": "OUT",
            "": "UNKNOWN", "note": "UNKNOWN",
        }
        normalized = mapping.get(text, "UNKNOWN")
        if normalized not in PRACTICE_STATUS:
            raise EvidenceError("invalid normalized practice status")
        return normalized
    if kind == "game":
        mapping = {
            "out": "OUT", "doubtful": "DOUBTFUL", "questionable": "QUESTIONABLE",
            "probable": "PROBABLE", "note": "NOTE", "": "NO_DESIGNATION",
        }
        normalized = mapping.get(text, "UNKNOWN")
        if normalized not in GAME_STATUS:
            raise EvidenceError("invalid normalized game status")
        return normalized
    raise EvidenceError("kind must be practice or game")


@dataclass(frozen=True)
class PriorQuarterbackObservation:
    canonical_game_id: str
    canonical_player_id: str
    season: int
    available_time_utc: str
    started: bool
    attempts: int
    epa_sum: float
    successes: int
    sacks: int
    interceptions: int
    cpoe_sum: float | None = None
    cpoe_attempts: int = 0


@dataclass(frozen=True)
class PriorRoleObservation:
    canonical_game_id: str
    canonical_player_id: str
    canonical_team_id: str
    available_time_utc: str
    offense_snaps: int
    defense_snaps: int
    special_teams_snaps: int


def quarterback_prior_features(*, expected_player_id: str, target_game_id: str, target_season: int,
                               cutoff_utc: str, observations: Iterable[PriorQuarterbackObservation],
                               prior_exposure: float = 100.0, league_epa_per_dropback: float = 0.0) -> dict[str, Any]:
    """Build a strictly prior-only QB summary with transparent league shrinkage."""
    if not expected_player_id:
        raise EvidenceError("expected quarterback identity is required")
    cutoff = _utc(cutoff_utc, "cutoff_utc")
    admitted: list[PriorQuarterbackObservation] = []
    for row in observations:
        if row.canonical_game_id == target_game_id:
            raise EvidenceError("target-game quarterback evidence is prohibited")
        available = _utc(row.available_time_utc, "available_time_utc")
        if available >= cutoff:
            continue
        if row.canonical_player_id == expected_player_id:
            admitted.append(row)
    current = [row for row in admitted if row.season == target_season]
    prior = [row for row in admitted if row.season < target_season]
    attempts = sum(row.attempts for row in admitted)
    epa_sum = sum(row.epa_sum for row in admitted)
    denominator = attempts + prior_exposure
    return {
        "expectedPlayerId": expected_player_id,
        "priorGames": len(admitted),
        "priorStarts": sum(int(row.started) for row in admitted),
        "currentSeasonStarts": sum(int(row.started) for row in current),
        "priorSeasonStarts": sum(int(row.started) for row in prior),
        "attempts": attempts,
        "epaPerDropbackShrunk": (epa_sum + prior_exposure * league_epa_per_dropback) / denominator,
        "successRate": sum(row.successes for row in admitted) / attempts if attempts else None,
        "sackRate": sum(row.sacks for row in admitted) / attempts if attempts else None,
        "interceptionRate": sum(row.interceptions for row in admitted) / attempts if attempts else None,
        "cpoe": (sum(row.cpoe_sum or 0.0 for row in admitted) /
                 sum(row.cpoe_attempts for row in admitted)) if sum(row.cpoe_attempts for row in admitted) else None,
        "support": "NO_PRIOR_NFL_HISTORY" if not admitted else "SUPPORTED_PRIOR_ONLY",
        "uncertaintyExposure": denominator,
        "sourceGameIds": sorted(row.canonical_game_id for row in admitted),
    }


def quarterback_cold_start(*, expected_player_id: str | None, prior_starts: int | None,
                           current_season_starts: int | None, rookie_season: int | None,
                           target_season: int, draft_record_present: bool,
                           undrafted_explicit: bool | None) -> dict[str, Any]:
    """Classify sparse support without treating a missing draft row as undrafted."""
    if not expected_player_id:
        return {"state": "UNRESOLVED_QUARTERBACK", "firstNflStart": None, "rookie": None,
                "missingness": Missingness.PLAYER_IDENTITY_UNRESOLVED.value}
    if prior_starts is None:
        return {"state": "NO_PRIOR_START_EVIDENCE", "firstNflStart": None, "rookie": None,
                "missingness": Missingness.NO_PRIOR_START.value}
    if not draft_record_present and undrafted_explicit is None:
        draft_state = "DRAFT_STATUS_UNKNOWN"
    else:
        draft_state = "UNDRAFTED" if undrafted_explicit else "DRAFTED"
    rookie = rookie_season == target_season if rookie_season is not None else None
    first = prior_starts == 0
    return {"state": "FIRST_NFL_START" if first else "EXPERIENCED_STARTER",
            "firstNflStart": first, "rookie": rookie,
            "currentSeasonStarts": current_season_starts,
            "draftState": draft_state, "missingness": None}


def prior_role_features(*, canonical_player_id: str, canonical_team_id: str, target_game_id: str,
                        cutoff_utc: str, observations: Iterable[PriorRoleObservation]) -> dict[str, Any]:
    """Summarize completed prior-game role; target-game snaps fail closed."""
    cutoff = _utc(cutoff_utc, "cutoff_utc")
    admitted: list[PriorRoleObservation] = []
    for row in observations:
        if row.canonical_game_id == target_game_id:
            raise EvidenceError("target-game snap shares are prohibited")
        if row.canonical_player_id != canonical_player_id or row.canonical_team_id != canonical_team_id:
            continue
        if _utc(row.available_time_utc, "available_time_utc") < cutoff:
            admitted.append(row)
    admitted.sort(key=lambda item: (item.available_time_utc, item.canonical_game_id))
    recent = admitted[-4:]
    return {"priorGameCount": len(recent), "priorGameIds": [row.canonical_game_id for row in recent],
            "meanOffenseSnaps": sum(row.offense_snaps for row in recent) / len(recent) if recent else None,
            "meanDefenseSnaps": sum(row.defense_snaps for row in recent) / len(recent) if recent else None,
            "meanSpecialTeamsSnaps": sum(row.special_teams_snaps for row in recent) / len(recent) if recent else None,
            "missingness": None if recent else Missingness.NO_PRIOR_NFL_HISTORY.value}


def injury_burden_counts(records: Iterable[PregamePersonnelRecord], *, feature_cutoff_utc: str) -> dict[str, Any]:
    """Count reported statuses by position without estimating availability."""
    cutoff = _utc(feature_cutoff_utc, "feature_cutoff_utc")
    counts: dict[str, dict[str, int]] = {}
    total = 0
    for row in records:
        row.validate()
        if _utc(row.feature_cutoff_utc, "feature_cutoff_utc") != cutoff:
            raise EvidenceError("injury burden mixed feature cutoffs")
        if row.admissibility not in {Admissibility.HISTORICALLY_POINT_IN_TIME_ADMISSIBLE, Admissibility.PROSPECTIVE_ONLY}:
            raise EvidenceError("reconstructed or postgame evidence cannot enter injury burden")
        bucket = counts.setdefault(row.position_group, {})
        key = f"{row.practice_status}|{row.game_status}|{row.expected_availability}"
        bucket[key] = bucket.get(key, 0) + 1
        total += 1
    return {"listedPlayerCount": total, "countsByPositionAndStatus": counts,
            "availabilityWeightsApplied": False,
            "missingness": None if total else Missingness.SOURCE_NOT_PUBLISHED.value}


def status_vocabulary() -> dict[str, Any]:
    return {
        "schemaVersion": "NFL_PERSONNEL_STATUS_VOCABULARY_V1",
        "practiceStatus": sorted(PRACTICE_STATUS), "gameStatus": sorted(GAME_STATUS),
        "rosterStatus": sorted(ROSTER_STATUS), "expectedRole": sorted(EXPECTED_ROLE),
        "expectedAvailability": sorted(EXPECTED_AVAILABILITY),
        "positionGroup": sorted(POSITION_GROUP),
        "missingness": [item.value for item in Missingness],
        "rules": [
            "QUESTIONABLE, DOUBTFUL, and LIMITED never imply a deterministic availability probability.",
            "PLAYER_ABSENT_FROM_REPORT and PLAYER_REPORTED_HEALTHY are distinct states.",
            "confirmedInactive and actualParticipation are separate observations; actual target-game participation is prohibited as a pregame input.",
            "A missing draft record does not imply undrafted status.",
        ],
    }


__all__ = [
    "Admissibility", "CONTRACT", "EvidenceError", "Missingness", "PregamePersonnelRecord",
    "PriorQuarterbackObservation", "PriorRoleObservation", "append_revision", "canonical_json_bytes", "quarterback_cold_start",
    "prior_role_features", "injury_burden_counts",
    "quarterback_prior_features", "resolve_canonical_player", "normalize_injury_status", "sha256_json", "status_vocabulary",
]
