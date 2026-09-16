"""Canonical, append-only MMA POC evidence records."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

MMA_SPORT = "MMA"

def utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None: raise ValueError("TIMESTAMP_MUST_BE_TIMEZONE_AWARE")
    return parsed.astimezone(timezone.utc)

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

def digest(value: Any) -> str: return sha256(canonical_bytes(value)).hexdigest()
def schema_fingerprint(value: dict[str, Any]) -> str:
    return digest(sorted((key, type(item).__name__) for key, item in value.items()))

@dataclass(frozen=True)
class Capture:
    capture_id: str; sport: str; provider: str; endpoint: str; retrieved_at: str
    payload_sha256: str; payload_bytes: int; schema_fingerprint: str
    source_published_at: str | None = None; source_updated_at: str | None = None
    predecessor_capture_id: str | None = None

@dataclass(frozen=True)
class Fighter:
    canonical_fighter_id: str; sport: str; display_name: str; source_ids: dict[str, str]
    aliases: tuple[str, ...] = ()

@dataclass(frozen=True)
class EventVersion:
    canonical_event_id: str; sport: str; version: int; promotion: str; scheduled_start: str
    observed_at: str; source_event_ids: dict[str, str]; status: str
    predecessor_version: int | None = None; change_reason: str | None = None

@dataclass(frozen=True)
class BoutVersion:
    canonical_bout_id: str; canonical_event_id: str; sport: str; version: int
    red_fighter_id: str; blue_fighter_id: str; weight_class: str; scheduled_rounds: int
    observed_at: str; source_bout_ids: dict[str, str]; status: str = "SCHEDULED"
    predecessor_version: int | None = None; predecessor_bout_id: str | None = None
    change_reason: str | None = None

@dataclass(frozen=True)
class OddsSnapshot:
    canonical_bout_id: str; sport: str; provider: str; bookmaker: str; market: str
    region: str; observed_at: str; source_last_update: str; outcomes: dict[str, float]
    capture_id: str

@dataclass(frozen=True)
class ResultRevision:
    canonical_bout_id: str; sport: str; revision: int; status: str
    winner_fighter_id: str | None; method: str | None; round: int | None
    finish_time: str | None; observed_at: str; capture_id: str; round_stats_complete: bool
    round_stats_rounds: tuple[int, ...] = ()
    predecessor_revision: int | None = None; correction_reason: str | None = None

@dataclass
class EvidenceBundle:
    forecast_cutoff: str; captures: list[Capture] = field(default_factory=list)
    fighters: list[Fighter] = field(default_factory=list); events: list[EventVersion] = field(default_factory=list)
    bouts: list[BoutVersion] = field(default_factory=list); odds: list[OddsSnapshot] = field(default_factory=list)
    results: list[ResultRevision] = field(default_factory=list)
    def to_dict(self) -> dict[str, Any]:
        return {"forecast_cutoff":self.forecast_cutoff,"captures":[asdict(x) for x in self.captures],
                "fighters":[asdict(x) for x in self.fighters],"events":[asdict(x) for x in self.events],
                "bouts":[asdict(x) for x in self.bouts],"odds":[asdict(x) for x in self.odds],
                "results":[asdict(x) for x in self.results]}
