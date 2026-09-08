"""Operational, pregame-only daily publisher for the accepted MLB V18 challenger.

The module deliberately keeps source capture, model execution, and immutable publication
separate.  AISP is queried in a read-only transaction and is never used as an execution
environment.  The accepted V18 PA and transition artifacts are loaded once per slate.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, date, datetime, time as datetime_time, timedelta
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import threading
import time
from typing import Any, Mapping, Protocol, Sequence
import uuid
from zoneinfo import ZoneInfo

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.persistence.db import Database
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_phase5 import base_out_transition as bt
from server.sports_current_statcast import stage3_eda as eda
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast.mlb_v18_whole_game_challenger import (
    V18StateProbabilityProvider,
    compose_raw_template,
    simulate_prospective_game,
)
from server.sports_current_statcast.stage3_model_laboratory import resolve_model_lab_authority


PUBLISHER_SCHEMA = "MLB_V18_DAILY_SLATE_PUBLISHER_V1"
GAME_SCHEMA = "MLB_V18_DAILY_GAME_FORECAST_V1"
HANDOFF_SCHEMA = "AISP_MLB_V18_DAILY_SLATE_HANDOFF_V1"
HANDOFF_SCHEMA_V2 = "AISP_MLB_V18_DAILY_SLATE_HANDOFF_V2"
RECEIPT_SCHEMA = "MLB_V18_DAILY_SLATE_RECEIPT_V1"
PARENT_BUNDLE_ID = "mlb-v18-whole-game-a6e7e99122f1b60701a4728b"
PARENT_BUNDLE_SHA256 = "a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27"
ACCEPTANCE_PROTOCOL_V2_SHA256 = "291243d7abad7f972e08f7610715bf8e693a267ea37a7b6189256f98aa4a4a7b"
POPULATION_SUPPLEMENT_ID = "mlb-v18-population-geometry-d2586fba829c059fb20b4251"
POPULATION_SUPPLEMENT_SHA256 = "d2586fba829c059fb20b4251c19a5d2fc204abf11d3634ebcdef4f19930c0621"
PA_MODEL_SHA256 = "44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b"
TRANSITION_MODEL_SHA256 = "0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253"
TREATMENT_SPECIFICATION_ID = "stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638"
TREATMENT_MANIFEST_SHA256 = "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3"
PROJECT_ID = "asp-mtlozhdx"
MASTER_SEED = 20260907
SIMULATION_COUNT = 5_000
SOURCE_START = "2026-04-01"
SOURCE_END = "2026-08-13"
BULLPEN_START = "2026-07-15"
BULLPEN_END = "2026-08-13"
BULLPEN_RULE = (
    "LATEST_ROW_PER_NON_STARTER_PITCHER_THEN_LAST_EIGHT_IN_"
    "STABLE_GAME_DATE_CANONICAL_PA_ORDER"
)
RESEARCH_FLAGS = {
    "researchShadowOnly": True,
    "wageringAuthority": False,
    "promotionStatus": "NOT_PROMOTED",
    "executionAllowedInAISP": False,
}


class DailySlateError(RuntimeError):
    """A classified failure suitable for a concise per-game receipt."""

    def __init__(self, category: str, reason: str):
        super().__init__(reason)
        self.category = category
        self.reason = reason


class SlateSource(Protocol):
    def capture_slate(
        self, *, slate_date: date, horizon_hours: int, game_ids: Sequence[str]
    ) -> tuple[datetime, list[dict[str, Any]], int]: ...


class GameEngine(Protocol):
    load_seconds: float
    model_load_count: int
    fit_count: int

    def forecast(self, snapshot: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class PublishConfig:
    slate_date: date
    horizon_hours: int = 24
    game_ids: tuple[str, ...] = ()
    limit: int | None = None
    workers: int = 1
    dry_run: bool = False
    output_root: Path = Path("outputs/mlb-v18-daily-slate")

    def __post_init__(self) -> None:
        if self.horizon_hours <= 0 or self.horizon_hours > 168:
            raise ValueError("horizon_hours must be between 1 and 168")
        if self.limit is not None and self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.workers < 1 or self.workers > 4:
            raise ValueError("workers must be between 1 and 4")


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha_json(value: Any) -> str:
    return sha_bytes(canonical_json_bytes(value))


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_bytes(canonical_json_bytes(json_safe(value)))
    os.replace(temporary, path)


def file_record(path: Path, root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "relativePath": path.relative_to(root).as_posix(),
        "bytes": len(raw),
        "sha256": sha_bytes(raw),
    }


def _as_utc(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def evidence_logical_digest(snapshot: Mapping[str, Any]) -> str:
    """Digest source evidence without the operational clock used to read it."""

    body = dict(json_safe(snapshot))
    body.pop("capturedAt", None)
    body.pop("contentSha256", None)
    return sha_json(body)


def publication_key(snapshot: Mapping[str, Any]) -> str:
    return sha_json({
        "schemaVersion": PUBLISHER_SCHEMA,
        "gameId": snapshot["game"]["game_id"],
        "scheduledStart": json_safe(snapshot["game"]["starts_at"]),
        "evidenceLogicalDigest": evidence_logical_digest(snapshot),
        "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "paModelSha256": PA_MODEL_SHA256,
        "transitionModelSha256": TRANSITION_MODEL_SHA256,
        "simulationCount": SIMULATION_COUNT,
        "masterSeed": MASTER_SEED,
    })


def validate_pregame_snapshot(snapshot: Mapping[str, Any]) -> None:
    game = snapshot.get("game") or {}
    captured = _as_utc(snapshot.get("capturedAt"))
    start = _as_utc(game.get("starts_at"))
    if captured >= start:
        raise DailySlateError("GAME_ALREADY_STARTED", "forecast capture is at or after first pitch")
    if str(game.get("status", "")).upper() not in {"SCHEDULED", "PREGAME", "PRE_GAME"}:
        raise DailySlateError("MISSING_REQUIRED_EVIDENCE", f"pregame status is not eligible: {game.get('status')}")
    sides = list(snapshot.get("sides") or [])
    if len(sides) != 2 or {row.get("side") for row in sides} != {"AWAY", "HOME"}:
        raise DailySlateError("MISSING_REQUIRED_EVIDENCE", "exactly one away and one home team are required")
    for side in sides:
        starter = side.get("starter") or {}
        if not starter.get("mlbamId") or not starter.get("availableAsOf"):
            raise DailySlateError(
                "MISSING_REQUIRED_EVIDENCE",
                f"{side.get('side')} starter identity and timestamp are required",
            )
        lineup = list(side.get("lineup") or [])
        if len(lineup) != 9 or [int(row.get("batting_order", 0)) for row in lineup] != list(range(1, 10)):
            raise DailySlateError("MISSING_REQUIRED_EVIDENCE", f"{side.get('side')} ordered nine-player lineup is unavailable")
        if any(not row.get("mlbam") for row in lineup):
            raise DailySlateError("INVALID_PARTICIPANT_MAPPING", f"{side.get('side')} lineup has an unresolved MLB identity")
        authority = side.get("lineupAuthority") or {}
        timestamps = [starter.get("availableAsOf"), authority.get("availableAsOf")]
        for timestamp in timestamps:
            if not timestamp or _as_utc(timestamp) > captured or _as_utc(timestamp) >= start:
                raise DailySlateError("MISSING_REQUIRED_EVIDENCE", f"{side.get('side')} evidence is not valid at the forecast cutoff")


def validate_forecast_payload(snapshot: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    forecast = payload.get("forecast") or {}
    simulation = forecast.get("simulation") or {}
    if forecast.get("gameId") != snapshot.get("game", {}).get("game_id"):
        raise DailySlateError("MODEL_FAILURE", "forecast game identity differs from captured evidence")
    if simulation.get("count") != SIMULATION_COUNT:
        raise DailySlateError("SIMULATION_FAILURE", "daily forecast did not contain exactly 5,000 simulations")
    if simulation.get("illegalStateCount") != 0 or simulation.get("nonterminationCount") != 0:
        raise DailySlateError("SIMULATION_FAILURE", "daily forecast contains illegal or nonterminating simulations")
    if simulation.get("deterministicReplay") is not True:
        raise DailySlateError("SIMULATION_FAILURE", "deterministic replay was not verified")
    for key, expected in RESEARCH_FLAGS.items():
        if forecast.get(key) != expected:
            raise DailySlateError("MODEL_FAILURE", f"research-only safety field differs: {key}")
    path = payload.get("representativePath") or {}
    if path.get("gameId") != forecast.get("gameId") or not path.get("events"):
        raise DailySlateError("SIMULATION_FAILURE", "renderer-ready representative path is unavailable")
    if _as_utc(forecast.get("capturedAt")) >= _as_utc(forecast.get("scheduledStart")):
        raise DailySlateError("GAME_ALREADY_STARTED", "forecast timestamp is not before first pitch")


class AispReadOnlySlateSource:
    """Capture persisted AISP schedule/participant evidence without provider calls."""

    def __init__(self, aisp_root: Path):
        from dotenv import dotenv_values
        from sqlalchemy import create_engine

        values = dotenv_values(aisp_root / ".env")
        database_url = values.get("DATABASE_URL")
        if not database_url:
            raise RuntimeError("AISP DATABASE_URL is unavailable")
        # AISP uses psycopg v3; Model Studio's pinned runtime uses psycopg2.
        # The URL adaptation changes only the local DBAPI, not the database or authority.
        database_url = str(database_url).replace("postgresql+psycopg://", "postgresql+psycopg2://")
        self._engine = create_engine(database_url)

    def close(self) -> None:
        self._engine.dispose()

    def capture_slate(
        self, *, slate_date: date, horizon_hours: int, game_ids: Sequence[str]
    ) -> tuple[datetime, list[dict[str, Any]], int]:
        from sqlalchemy import text

        captured = datetime.now(UTC)
        local = ZoneInfo("America/New_York")
        window_start = datetime.combine(slate_date, datetime_time.min, tzinfo=local).astimezone(UTC)
        window_end = window_start + timedelta(hours=horizon_hours)
        snapshots: list[dict[str, Any]] = []
        with self._engine.connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                games = connection.execute(text("""
                    select g.id::text game_id,g.starts_at,g.status::text status,
                           g.scheduled_innings,v.name venue,v.timezone,
                           (select em.external_id from external_id_mappings em
                            where em.entity_id=g.id and em.entity_type='game'
                              and em.source='MLB_STATS_API' order by em.created_at desc limit 1) source_game_id
                    from games g
                    left join venues v on v.id=g.venue_id
                    where g.starts_at >= :window_start and g.starts_at < :window_end
                      and exists (
                        select 1 from game_teams gt join teams t on t.id=gt.team_id
                        join leagues l on l.id=t.league_id
                        where gt.game_id=g.id and l.code='MLB'
                      )
                      and (cast(:all_games as boolean) or g.id::text = any(cast(:game_ids as text[])))
                    order by g.starts_at,g.id
                """), {
                    "window_start": window_start,
                    "window_end": window_end,
                    "all_games": not bool(game_ids),
                    "game_ids": list(game_ids) or [""],
                }).mappings().all()
                for game_row in games:
                    snapshots.append(self._snapshot_game(connection, dict(game_row), captured))
            finally:
                transaction.rollback()
        return captured, snapshots, 0

    def _snapshot_game(self, connection: Any, game: dict[str, Any], captured: datetime) -> dict[str, Any]:
        from sqlalchemy import text

        starts_at = _as_utc(game["starts_at"])
        sides = connection.execute(text("""
            with latest_starter as (
              select distinct on (so.team_id) so.team_id,so.confirmation_state,
                     coalesce(so.confirmed_pitcher_id,so.probable_pitcher_id) pitcher_id,
                     so.throws,so.days_rest,so.pitches_previous_day,so.pitches_last_start,
                     so.workload,so.observed_at,so.available_as_of,so.source
              from starter_observations so
              where so.game_id=cast(:game_id as uuid) and so.available_as_of <= :captured
              order by so.team_id,so.available_as_of desc
            )
            select t.id::text team_uuid,t.abbreviation,t.name,gt.is_home,
                   p.id::text pitcher_uuid,p.full_name pitcher_name,
                   pm.external_id pitcher_mlbam,ls.confirmation_state,ls.throws,
                   ls.days_rest,ls.pitches_previous_day,ls.pitches_last_start,ls.workload,
                   ls.observed_at starter_observed_at,ls.available_as_of starter_available_as_of,
                   ls.source starter_source
            from game_teams gt join teams t on t.id=gt.team_id
            left join latest_starter ls on ls.team_id=gt.team_id
            left join players p on p.id=coalesce(ls.pitcher_id,gt.probable_pitcher_id)
            left join external_id_mappings pm on pm.entity_id=p.id
              and pm.entity_type='player' and pm.source='MLB_STATS_API'
            where gt.game_id=cast(:game_id as uuid) order by gt.is_home
        """), {"game_id": game["game_id"], "captured": captured}).mappings().all()
        output_sides: list[dict[str, Any]] = []
        for side_row in sides:
            side = dict(side_row)
            current = connection.execute(text("""
                select lo.id::text observation_id,lo.lineup_status,lo.is_complete,
                       lo.observed_at,lo.available_as_of,lo.source,null::text source_game_uuid,
                       null::timestamptz source_game_start
                from lineup_observations lo
                where lo.game_id=cast(:game_id as uuid) and lo.team_id=cast(:team_id as uuid)
                  and lo.available_as_of <= :captured
                order by lo.available_as_of desc limit 1
            """), {"game_id": game["game_id"], "team_id": side["team_uuid"], "captured": captured}).mappings().first()
            projected = not (current and current["is_complete"] and current["lineup_status"] == "CONFIRMED")
            lineup = current
            if projected:
                lineup = connection.execute(text("""
                    select lo.id::text observation_id,lo.lineup_status,lo.is_complete,
                           lo.observed_at,lo.available_as_of,lo.source,g.id::text source_game_uuid,
                           g.starts_at source_game_start
                    from lineup_observations lo join games g on g.id=lo.game_id
                    where lo.team_id=cast(:team_id as uuid) and lo.is_complete=true
                      and lo.lineup_status='CONFIRMED' and lo.available_as_of <= :captured
                      and g.starts_at < :target_start
                    order by g.starts_at desc,lo.available_as_of desc limit 1
                """), {"team_id": side["team_uuid"], "captured": captured, "target_start": starts_at}).mappings().first()
            entries: list[dict[str, Any]] = []
            if lineup is not None:
                entries = [dict(row) for row in connection.execute(text("""
                    select le.batting_order,p.full_name,pm.external_id mlbam,
                           coalesce(le.bats,b.bats) bats,le.defensive_position
                    from lineup_entries le join players p on p.id=le.player_id
                    left join batters b on b.player_id=p.id
                    left join external_id_mappings pm on pm.entity_id=p.id
                      and pm.entity_type='player' and pm.source='MLB_STATS_API'
                    where le.lineup_observation_id=cast(:lineup_id as uuid) and le.is_starter=true
                    order by le.batting_order
                """), {"lineup_id": lineup["observation_id"]}).mappings().all()]
            authority = {
                "status": "PROJECTED_PRIOR_COMPLETE_LINEUP" if projected else "CONFIRMED",
                "source": lineup["source"] if lineup else None,
                "observedAt": lineup["observed_at"] if lineup else None,
                "availableAsOf": lineup["available_as_of"] if lineup else None,
                "sourceGameId": lineup["source_game_uuid"] if lineup else None,
                "sourceGameStart": lineup["source_game_start"] if lineup else None,
                "projectionMethod": "MOST_RECENT_PRIOR_COMPLETE_LINEUP_AVAILABLE_BEFORE_CAPTURE" if projected else None,
            }
            output_sides.append({
                "side": "HOME" if side["is_home"] else "AWAY",
                "team": {"uuid": side["team_uuid"], "abbreviation": side["abbreviation"], "name": side["name"]},
                "starter": {
                    "uuid": side["pitcher_uuid"], "name": side["pitcher_name"],
                    "mlbamId": side["pitcher_mlbam"], "throws": side["throws"],
                    "confirmationState": side["confirmation_state"],
                    "daysRest": side["days_rest"], "pitchesPreviousDay": side["pitches_previous_day"],
                    "pitchesLastStart": side["pitches_last_start"], "workload": side["workload"],
                    "observedAt": side["starter_observed_at"],
                    "availableAsOf": side["starter_available_as_of"], "source": side["starter_source"],
                },
                "lineupAuthority": authority,
                "lineup": entries,
            })
        weather = connection.execute(text("""
            select source,observed_at,available_as_of,temperature_f,wind_mph,
                   wind_direction,precipitation_probability,payload_checksum
            from weather_snapshots where game_id=cast(:game_id as uuid)
              and available_as_of <= :captured order by available_as_of desc limit 1
        """), {"game_id": game["game_id"], "captured": captured}).mappings().first()
        body = {
            "schemaVersion": "AISP_MLB_READ_ONLY_PREGAME_SNAPSHOT_V2",
            "captureMode": "PERSISTED_AISP_EVIDENCE_SELECT_ONLY_NO_PROVIDER_CALLS",
            "capturedAt": captured,
            "game": game,
            "sides": output_sides,
            "weather": dict(weather) if weather else None,
            "outcomesRead": False,
            "marketDataRead": False,
            "providerCalls": 0,
            "aispRowsModified": 0,
        }
        safe = json_safe(body)
        return {**safe, "contentSha256": sha_json(safe)}


def select_bullpen_rows(
    development: pd.DataFrame,
    source_order: Sequence[str],
    selected_pa_ids: set[str],
    starter_id: str,
) -> list[dict[str, Any]]:
    frame = development[development["canonicalPaId"].astype(str).isin(selected_pa_ids)].copy()
    frame = frame[frame["pitcherCanonicalPlayerId"].astype(str) != str(starter_id)].copy()
    frame.sort_values(["game_date", "canonicalPaId"], inplace=True, kind="stable")
    latest = frame.groupby("pitcherCanonicalPlayerId", sort=False).tail(1).tail(8)
    return [json_safe(row.loc[list(source_order)].to_dict()) for _, row in latest.iterrows()]


class V18ExecutionEngine:
    """One-slate accepted-artifact runtime.  It exposes no fitting method."""

    def __init__(self, root: Path):
        started = time.perf_counter()
        self.root = root.resolve()
        self.bundle = self.root / "outputs/mlb-v18-whole-game-challenger/sha256" / PARENT_BUNDLE_SHA256
        parent = self._verify_authority()
        model_path = self.bundle / "executable/v18-pa-fold5.joblib"
        self.pipeline = joblib.load(model_path)
        self.model_load_count = 1
        self.fit_count = 0
        if len(self.pipeline.ordered_features) != 246 or len(self.pipeline.preprocessor.ordered_features) != 273:
            raise RuntimeError("accepted V18 246/273 feature contract differs")
        transition_path = self.bundle / "executable/transition-fold4.json"
        self.transition = bt.TransitionModel.from_dict(json.loads(transition_path.read_text(encoding="utf-8")))
        self.authority = resolve_model_lab_authority(
            Database(self.root / ".runtime/asp-model-studio/persistence/asp_model_studio.db"), PROJECT_ID
        )
        if self.authority.split["finalOot"].get("locked") is not True:
            raise RuntimeError("Final OOT seal is not active")
        corrected_set = next((item for item in self.authority.feature_sets
            if (item.get("transformationContracts") or {}).get("semanticTreatmentVersion") == "MLB_SEMANTIC_TREATMENT_V1"
            and len(item.get("orderedFeatures") or []) == 273), None)
        if corrected_set is None:
            raise RuntimeError("registered V18 feature set is unavailable")
        self.development = lab._fold_frame(
            self.authority, corrected_set["orderedFeatures"], include_oof_identity=True, include_target=False
        )
        source_identity = self.development.attrs.get("correctedSourceIdentity") or {}
        if (
            len(self.development) != 683_662
            or source_identity.get("treatmentSpecificationId") != TREATMENT_SPECIFICATION_ID
            or source_identity.get("treatmentManifestChecksum") != TREATMENT_MANIFEST_SHA256
        ):
            raise RuntimeError("authenticated V18 Development authority differs")
        self.source_order = tuple(self.pipeline.ordered_features)
        recent = self.development[
            self.development["game_date"].astype(str).between("2026-07-01", SOURCE_END)
        ]
        cold = recent[recent["batter_prior_missing"].fillna(False).astype(bool)]
        if cold.empty:
            raise RuntimeError("accepted cold-start fallback is unavailable")
        self.cold_batter = json_safe(cold.iloc[-1].loc[list(self.source_order)].to_dict())
        self.parent = parent
        self._lock = threading.Lock()
        self.load_seconds = time.perf_counter() - started

    def _verify_authority(self) -> dict[str, Any]:
        manifest_path = self.bundle / "manifest.json"
        parent = json.loads(manifest_path.read_text(encoding="utf-8"))
        body = {key: value for key, value in parent.items() if key not in {"bundleId", "bundleSha256"}}
        if (
            parent.get("bundleId") != PARENT_BUNDLE_ID
            or parent.get("bundleSha256") != PARENT_BUNDLE_SHA256
            or sha_json(body) != PARENT_BUNDLE_SHA256
        ):
            raise RuntimeError("accepted V18 parent bundle identity differs")
        for record in parent["artifacts"]:
            path = self.bundle / record["relativePath"]
            if path.stat().st_size != record["bytes"] or sha_bytes(path.read_bytes()) != record["sha256"]:
                raise RuntimeError(f"accepted V18 artifact differs: {record['relativePath']}")
        if sha_bytes((self.bundle / "executable/v18-pa-fold5.joblib").read_bytes()) != PA_MODEL_SHA256:
            raise RuntimeError("accepted PA model identity differs")
        if sha_bytes((self.bundle / "executable/transition-fold4.json").read_bytes()) != TRANSITION_MODEL_SHA256:
            raise RuntimeError("accepted transition model identity differs")
        acceptance = self.root / "outputs/mlb-v18-acceptance-protocol-v2/sha256" / ACCEPTANCE_PROTOCOL_V2_SHA256 / "manifest.json"
        population = self.root / "outputs/mlb-v18-population-geometry/sha256" / POPULATION_SUPPLEMENT_SHA256 / "manifest.json"
        if json.loads(acceptance.read_text(encoding="utf-8")).get("contractSha256") != ACCEPTANCE_PROTOCOL_V2_SHA256:
            raise RuntimeError("Acceptance Protocol V2 identity differs")
        population_manifest = json.loads(population.read_text(encoding="utf-8"))
        if (
            population_manifest.get("supplementId") != POPULATION_SUPPLEMENT_ID
            or population_manifest.get("supplementSha256") != POPULATION_SUPPLEMENT_SHA256
        ):
            raise RuntimeError("population supplement identity differs")
        return parent

    def _identity_map(self, mlbam_ids: Sequence[str]) -> dict[str, str]:
        path = Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1\objects\sha256\ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf\object.parquet")
        table = pq.read_table(path, columns=["canonicalPlayerId", "mlbamId", "resolutionStatus"],
                              filters=[("mlbamId", "in", list(set(mlbam_ids)))])
        exact = table.to_pandas().drop_duplicates()
        exact = exact[exact["resolutionStatus"] == "MATCHED_EXACT"]
        return dict(zip(exact["mlbamId"].astype(str), exact["canonicalPlayerId"].astype(str)))

    def _latest_rows(self, players: Sequence[str], role: str) -> dict[str, dict[str, Any]]:
        identity = "batterCanonicalPlayerId" if role == "BATTER" else "pitcherCanonicalPlayerId"
        frame = self.development[
            self.development[identity].astype(str).isin(players)
            & self.development["game_date"].astype(str).between(SOURCE_START, SOURCE_END)
        ].copy()
        frame.sort_values(["game_date", "canonicalPaId"], inplace=True, kind="stable")
        return {
            str(key): json_safe(row.loc[list(self.source_order)].to_dict())
            for key, row in frame.groupby(identity, sort=False).tail(1).set_index(identity, drop=False).iterrows()
        }

    def _bullpen(self, team: str, starter_id: str) -> list[dict[str, Any]]:
        with self._lock:
            identities = eda._scan(self.authority.eda_authority, ["canonicalPaId"], {
                "startDate": BULLPEN_START, "endDate": BULLPEN_END, "fieldingTeam": [team],
            })
        rows = select_bullpen_rows(
            self.development, self.source_order,
            set(identities["canonicalPaId"].astype(str)), starter_id,
        )
        if len(rows) != 8:
            raise DailySlateError(
                "MISSING_REQUIRED_EVIDENCE",
                f"bullpen template distribution for {team} contains {len(rows)} rows; exactly eight are required",
            )
        return rows

    def forecast(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        construction_started = time.perf_counter()
        try:
            validate_pregame_snapshot(snapshot)
            sides = {row["side"]: row for row in snapshot["sides"]}
            mlbam = [str(row["starter"]["mlbamId"]) for row in sides.values()]
            mlbam.extend(str(entry["mlbam"]) for row in sides.values() for entry in row["lineup"])
            crosswalk = self._identity_map(mlbam)
            starters = {side: crosswalk.get(str(row["starter"]["mlbamId"])) for side, row in sides.items()}
            if any(value is None for value in starters.values()):
                raise DailySlateError("INVALID_PARTICIPANT_MAPPING", "a starter lacks an exact governed MLBAM crosswalk")
            pitcher_rows = self._latest_rows(list(starters.values()), "PITCHER")
            if any(value not in pitcher_rows for value in starters.values()):
                raise DailySlateError("INVALID_PARTICIPANT_MAPPING", "a starter lacks accepted Development template evidence")
            batter_ids = [crosswalk.get(str(entry["mlbam"])) for row in sides.values() for entry in row["lineup"]]
            batter_rows = self._latest_rows([value for value in batter_ids if value], "BATTER")
            lineups: dict[str, list[dict[str, Any]]] = {}
            cold_fallbacks: list[dict[str, Any]] = []
            for side, row in sides.items():
                templates = []
                for entry in row["lineup"]:
                    canonical = crosswalk.get(str(entry["mlbam"]))
                    if canonical and canonical in batter_rows:
                        templates.append(batter_rows[canonical])
                    else:
                        templates.append(dict(self.cold_batter))
                        cold_fallbacks.append({"side": side, "battingOrder": entry["batting_order"], "mlbamId": str(entry["mlbam"]), "contract": "ACCEPTED_V18_COLD_START_FALLBACK"})
                lineups[side] = templates
            away_bullpen = self._bullpen(sides["AWAY"]["team"]["abbreviation"], str(starters["AWAY"]))
            home_bullpen = self._bullpen(sides["HOME"]["team"]["abbreviation"], str(starters["HOME"]))
            raw_templates = []
            for side, opposing in (("AWAY", "HOME"), ("HOME", "AWAY")):
                for slot, batter in enumerate(lineups[side], 1):
                    raw = compose_raw_template(
                        source_order=self.source_order, batter_row=batter,
                        pitcher_row=pitcher_rows[str(starters[opposing])],
                        state={"context_inning": 1, "context_top_bottom": 0 if side == "AWAY" else 1,
                               "context_outs_before": 0, "context_base_mask_before": 0,
                               "context_batting_score_diff_before": 0},
                    )
                    raw.insert(0, "templateSide", side)
                    raw.insert(1, "templateSlot", slot)
                    raw_templates.append(raw)
            raw_frame = pd.concat(raw_templates, ignore_index=True)
            treated = self.pipeline.preprocessor.transform_frame(raw_frame.loc[:, list(self.source_order)])
            if raw_frame.shape != (18, 248) or treated.shape != (18, 273):
                raise DailySlateError("PREPROCESSING_FAILURE", "daily V18 template shape differs from 18 x 246/273")
            provider = V18StateProbabilityProvider(
                pipeline=self.pipeline, away_batters=lineups["AWAY"], home_batters=lineups["HOME"],
                away_starter=pitcher_rows[str(starters["AWAY"])],
                home_starter=pitcher_rows[str(starters["HOME"])],
                away_bullpen=away_bullpen, home_bullpen=home_bullpen, temperature=None,
            )
        except DailySlateError:
            raise
        except Exception as exc:
            raise DailySlateError("PREPROCESSING_FAILURE", str(exc)) from exc
        construction_seconds = time.perf_counter() - construction_started
        simulation_started = time.perf_counter()
        try:
            result = simulate_prospective_game(
                game_id=str(snapshot["game"]["game_id"]), provider=provider,
                transition_model=self.transition, n_sims=SIMULATION_COUNT,
                master_seed=MASTER_SEED,
                regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=1,
            )
            replay_a = simulate_prospective_game(
                game_id=str(snapshot["game"]["game_id"]), provider=provider,
                transition_model=self.transition, n_sims=64, master_seed=MASTER_SEED,
                regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=1,
            )
            replay_b = simulate_prospective_game(
                game_id=str(snapshot["game"]["game_id"]), provider=provider,
                transition_model=self.transition, n_sims=64, master_seed=MASTER_SEED,
                regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=1,
            )
            deterministic = all(np.array_equal(replay_a[name], replay_b[name]) for name in ("awayRuns", "homeRuns", "innings", "paCounts")) and replay_a["traces"] == replay_b["traces"]
            if result["nonterminationCount"] or result["illegalStateCount"] or not deterministic:
                raise RuntimeError("simulation legality or deterministic replay check failed")
        except Exception as exc:
            raise DailySlateError("SIMULATION_FAILURE", str(exc)) from exc
        simulation_seconds = time.perf_counter() - simulation_started
        home = np.asarray(result["homeRuns"], dtype=float)
        away = np.asarray(result["awayRuns"], dtype=float)
        home_p = float(result["homeWinProbability"])
        home_se = math.sqrt(home_p * (1.0 - home_p) / SIMULATION_COUNT)
        total = home + away

        def distribution(values: np.ndarray) -> list[dict[str, Any]]:
            counts = Counter(int(value) for value in values)
            return [{"value": value, "probability": count / len(values)} for value, count in sorted(counts.items())]

        execution_inputs = {
            "schemaVersion": "MLB_V18_DAILY_EXECUTION_INPUTS_V1",
            "sourceWindow": {"start": SOURCE_START, "end": SOURCE_END},
            "featureContract": {"rawInputs": 246, "treatedInputs": 273,
                                "treatmentSpecificationId": TREATMENT_SPECIFICATION_ID,
                                "manifestSha256": TREATMENT_MANIFEST_SHA256},
            "identityCrosswalk": {"requested": len(set(mlbam)), "resolved": len(set(mlbam) & set(crosswalk)),
                                  "authoritySha256": "ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf"},
            "coldStartFallbacks": cold_fallbacks,
            "rawTemplates": json_safe(raw_frame.to_dict(orient="records")),
            "providerInputs": {
                "awayBatters": lineups["AWAY"], "homeBatters": lineups["HOME"],
                "awayStarter": pitcher_rows[str(starters["AWAY"])],
                "homeStarter": pitcher_rows[str(starters["HOME"])],
                "awayBullpen": away_bullpen, "homeBullpen": home_bullpen,
            },
            "bullpenEvidence": {
                "sourceWindow": {"start": BULLPEN_START, "end": BULLPEN_END},
                "selectionRule": BULLPEN_RULE,
                "awayTeam": sides["AWAY"]["team"]["abbreviation"],
                "homeTeam": sides["HOME"]["team"]["abbreviation"],
                "awayRows": away_bullpen, "homeRows": home_bullpen,
                "awayDigest": sha_json(away_bullpen), "homeDigest": sha_json(home_bullpen),
            },
        }
        forecast = {
            "schemaVersion": GAME_SCHEMA,
            "gameId": snapshot["game"]["game_id"],
            "sourceGameId": snapshot["game"].get("source_game_id"),
            "capturedAt": snapshot["capturedAt"],
            "scheduledStart": snapshot["game"]["starts_at"],
            "pregameStatus": snapshot["game"]["status"],
            "venue": {"name": snapshot["game"].get("venue"), "timezone": snapshot["game"].get("timezone")},
            "teams": {side: sides[side]["team"] for side in ("AWAY", "HOME")},
            "starters": {side: sides[side]["starter"] for side in ("AWAY", "HOME")},
            "lineupAuthorities": {side: sides[side]["lineupAuthority"] for side in ("AWAY", "HOME")},
            "parentAuthority": {
                "bundleId": PARENT_BUNDLE_ID, "bundleSha256": PARENT_BUNDLE_SHA256,
                "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
                "populationSupplementId": POPULATION_SUPPLEMENT_ID,
                "populationSupplementSha256": POPULATION_SUPPLEMENT_SHA256,
                "paModelSha256": PA_MODEL_SHA256, "paFold": 5,
                "transitionModelSha256": TRANSITION_MODEL_SHA256, "transitionFold": 4,
                "providerCacheSemantics": "ONE_ROW_TRANSFORM_PER_TEMPLATE_V1",
            },
            "evidenceDigest": evidence_logical_digest(snapshot),
            "snapshotContentSha256": snapshot["contentSha256"],
            "executionInputDigest": sha_json(execution_inputs),
            "rawTemplateDigest": sha_json(execution_inputs["rawTemplates"]),
            "probabilities": {"homeWin": home_p, "awayWin": 1.0 - home_p},
            "expectations": {"homeRuns": float(home.mean()), "awayRuns": float(away.mean()),
                             "totalRuns": float(total.mean()), "homeMinusAwayRuns": float((home - away).mean())},
            "rates": {"oneRunGame": float(result["oneRunRate"]), "extraInning": float(result["extraInningRate"])},
            "distributions": {"homeRuns": distribution(home), "awayRuns": distribution(away),
                              "totalRuns": distribution(total), "homeMinusAwayRuns": distribution(home - away)},
            "simulation": {"count": SIMULATION_COUNT, "seed": MASTER_SEED,
                           "seedPolicy": "MASTER_SEED_PLUS_SHA256_GAME_ID_SUBSTREAMS",
                           "illegalStateCount": int(result["illegalStateCount"]),
                           "nonterminationCount": int(result["nonterminationCount"]),
                           "deterministicReplay": deterministic,
                           "representativePathCount": len(result["traces"])},
            "monteCarloUncertainty": {
                "method": "MONTE_CARLO_NORMAL_APPROXIMATION_95_PERCENT",
                "homeWinProbabilityStandardError": home_se,
                "homeWinProbabilityInterval": [max(0.0, home_p - 1.96 * home_se), min(1.0, home_p + 1.96 * home_se)],
                "awayWinProbabilityStandardError": home_se,
                "expectedHomeRunsStandardError": float(home.std(ddof=1) / math.sqrt(SIMULATION_COUNT)),
                "expectedAwayRunsStandardError": float(away.std(ddof=1) / math.sqrt(SIMULATION_COUNT)),
                "expectedTotalRunsStandardError": float(total.std(ddof=1) / math.sqrt(SIMULATION_COUNT)),
            },
            "knownLimitations": [
                "projected lineups use the latest prior complete lineup when a current confirmed lineup is unavailable",
                "no bench or substitution model; batting order remains fixed",
                "bullpen templates are a fixed Development team-staff distribution, not live bullpen workload",
                "V18 contextual evidence is carried forward only through 2026-08-13",
                "saved fold-5 PA and fold-4 transition artifacts are reused without refit or recalibration",
            ],
            "finalOot": {"locked": True, "opened": False, "featureRowsRead": 0,
                         "targetsRead": 0, "scored": False},
            "timing": {"constructionSeconds": construction_seconds, "simulationSeconds": simulation_seconds},
            **RESEARCH_FLAGS,
        }
        return {
            "forecast": forecast,
            "evidence": json_safe(snapshot),
            "executionInputs": execution_inputs,
            "representativePath": {"schemaVersion": "MLB_V18_DAILY_REPRESENTATIVE_PATH_V1",
                                   "gameId": snapshot["game"]["game_id"], "simulationIndex": 0,
                                   "events": result["traces"][0]},
        }


def _verify_existing_object(root: Path, pointer: Mapping[str, Any]) -> Path:
    object_dir = root / PurePosixPath(str(pointer["relativePath"]))
    manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
    body = {key: value for key, value in manifest.items() if key not in {"objectId", "objectSha256"}}
    if (
        manifest.get("objectSha256") != pointer.get("objectSha256")
        or sha_json(body) != manifest.get("objectSha256")
    ):
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "existing publication-key pointer is inconsistent")
    for record in manifest.get("artifacts", []):
        path = object_dir / record["relativePath"]
        if path.stat().st_size != record["bytes"] or sha_bytes(path.read_bytes()) != record["sha256"]:
            raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "existing forecast object checksum differs")
    return object_dir


def _publish_game(root: Path, snapshot: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    key = publication_key(snapshot)
    pointer_path = root / "publication-keys" / f"{key}.json"
    if pointer_path.exists():
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        object_dir = _verify_existing_object(root, pointer)
        return {"status": "DUPLICATE_ALREADY_PUBLISHED", "publicationKey": key,
                "objectSha256": pointer["objectSha256"], "relativePath": object_dir.relative_to(root).as_posix()}
    staging = root / ".staging" / uuid.uuid4().hex
    try:
        staging.mkdir(parents=True, exist_ok=False)
        write_json(staging / "forecast.json", payload["forecast"])
        write_json(staging / "pregame-evidence.json", payload["evidence"])
        write_json(staging / "execution-inputs.json", payload["executionInputs"])
        write_json(staging / "representative-path.json", payload["representativePath"])
        artifacts = [file_record(path, staging) for path in sorted(staging.iterdir())]
        manifest_body = {
            "schemaVersion": "MLB_V18_DAILY_GAME_OBJECT_MANIFEST_V1",
            "publicationKey": key, "gameId": snapshot["game"]["game_id"],
            "parentBundleSha256": PARENT_BUNDLE_SHA256, "artifacts": artifacts, **RESEARCH_FLAGS,
        }
        object_sha = sha_json(manifest_body)
        manifest = {**manifest_body, "objectId": f"mlb-v18-daily-game-{object_sha[:24]}", "objectSha256": object_sha}
        write_json(staging / "manifest.json", manifest)
        target = root / "objects" / "sha256" / object_sha
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            _verify_existing_object(root, {"relativePath": target.relative_to(root).as_posix(), "objectSha256": object_sha})
            shutil.rmtree(staging)
        else:
            os.replace(staging, target)
        pointer = {"schemaVersion": "MLB_V18_DAILY_PUBLICATION_KEY_V1", "publicationKey": key,
                   "objectSha256": object_sha, "relativePath": target.relative_to(root).as_posix()}
        write_json(pointer_path, pointer)
        return {"status": "PUBLISHED", "publicationKey": key, "objectSha256": object_sha,
                "relativePath": target.relative_to(root).as_posix()}
    except DailySlateError:
        raise
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", str(exc)) from exc


def _dry_run_row(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    try:
        validate_pregame_snapshot(snapshot)
        return {"gameId": snapshot["game"]["game_id"], "status": "ELIGIBLE_PREFLIGHT_ONLY",
                "reason": "dry run does not load or execute V18"}
    except DailySlateError as exc:
        return {"gameId": snapshot.get("game", {}).get("game_id"), "status": "SKIPPED",
                "category": exc.category, "reason": exc.reason}


def collect_slate_forecasts(output_root: Path, slate_date: date) -> list[dict[str, Any]]:
    """Return the newest verified immutable object for every game on a local-date slate."""

    root = output_root.resolve()
    selected: dict[str, dict[str, Any]] = {}
    local = ZoneInfo("America/New_York")
    objects = root / "objects" / "sha256"
    if not objects.exists():
        return []
    for object_dir in objects.iterdir():
        if not object_dir.is_dir() or not (object_dir / "manifest.json").is_file():
            continue
        try:
            manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
            pointer = {"relativePath": object_dir.relative_to(root).as_posix(),
                       "objectSha256": manifest.get("objectSha256")}
            _verify_existing_object(root, pointer)
            forecast = json.loads((object_dir / "forecast.json").read_text(encoding="utf-8"))
            evidence = json.loads((object_dir / "pregame-evidence.json").read_text(encoding="utf-8"))
            path = json.loads((object_dir / "representative-path.json").read_text(encoding="utf-8"))
            validate_forecast_payload(evidence, {"forecast": forecast, "representativePath": path})
        except Exception:
            # A corrupt or incomplete object can never enter a handoff.  A
            # direct rerun of its publication key reports the exact failure.
            continue
        start = _as_utc(forecast["scheduledStart"])
        if start.astimezone(local).date() != slate_date:
            continue
        row = {
            "gameId": forecast["gameId"], "objectSha256": manifest["objectSha256"],
            "relativePath": object_dir.relative_to(root).as_posix(),
            "forecastFile": "forecast.json", "manifestFile": "manifest.json",
            "capturedAt": forecast["capturedAt"], "scheduledStart": forecast["scheduledStart"],
        }
        # Daily view supplements are additive children of the immutable
        # forecast object.  Import lazily to avoid a module cycle.
        from server.sports_current_statcast.mlb_v18_daily_views import view_references
        views = view_references(root, manifest["objectSha256"])
        if views:
            row.update(views)
        existing = selected.get(row["gameId"])
        if existing is None or (_as_utc(row["capturedAt"]), row["objectSha256"]) > (
            _as_utc(existing["capturedAt"]), existing["objectSha256"]
        ):
            selected[row["gameId"]] = row
    return sorted(selected.values(), key=lambda row: (_as_utc(row["scheduledStart"]), row["gameId"]))


def _write_handoff(output_root: Path, slate_date: date, forecasts: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], str, str]:
    three_view = bool(forecasts) and all(
        row.get("playGeometry") and row.get("populationGeometry") for row in forecasts
    )
    keys = ["gameId", "objectSha256", "relativePath", "forecastFile", "manifestFile"]
    if three_view:
        keys.extend(["playGeometry", "populationGeometry"])
    body = {
        "schemaVersion": HANDOFF_SCHEMA_V2 if three_view else HANDOFF_SCHEMA,
        "slateDate": slate_date.isoformat(), "generatedAt": datetime.now(UTC).isoformat(),
        "parentBundleId": PARENT_BUNDLE_ID, "parentBundleSha256": PARENT_BUNDLE_SHA256,
        "acceptanceProtocolV2Sha256": ACCEPTANCE_PROTOCOL_V2_SHA256,
        "forecasts": [{key: row[key] for key in keys} for row in forecasts],
        "consumerRules": ["verify object manifest and artifact checksums", "associate only exact existing game IDs",
                          "skip unknown games", "preserve Gen 1", "import idempotently by objectSha256",
                          "settle only later from authoritative outcomes"],
        **RESEARCH_FLAGS,
    }
    digest = sha_json(body)
    handoff = {**body, "handoffId": f"mlb-v18-daily-handoff-{digest[:24]}", "handoffSha256": digest}
    directory = output_root / "handoffs" / "sha256" / digest
    if not directory.exists():
        directory.mkdir(parents=True, exist_ok=False)
        write_json(directory / "aisp-handoff.json", handoff)
    relative = (directory / "aisp-handoff.json").relative_to(output_root).as_posix()
    return handoff, digest, relative


def _write_receipt_and_locator(output_root: Path, slate_date: date, body: Mapping[str, Any]) -> dict[str, Any]:
    digest = sha_json(body)
    receipt = {**body, "receiptId": f"mlb-v18-daily-slate-{digest[:24]}", "receiptSha256": digest}
    run_dir = output_root / "slates" / slate_date.isoformat() / "sha256" / digest
    if not run_dir.exists():
        run_dir.mkdir(parents=True, exist_ok=False)
        write_json(run_dir / "slate-result.json", receipt)
    locator = {"schemaVersion": "MLB_V18_DAILY_SLATE_LOCATOR_V1", "slateDate": slate_date.isoformat(),
               "receiptSha256": digest, "relativePath": run_dir.relative_to(output_root).as_posix(),
               "handoffSha256": body["handoffSha256"]}
    write_json(output_root / "slates" / slate_date.isoformat() / "latest.json", locator)
    return receipt


def publish_daily_slate(
    config: PublishConfig,
    source: SlateSource,
    *,
    engine: GameEngine | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Capture, execute, and publish one isolated slate run."""

    started = time.perf_counter()
    captured, snapshots, aisp_writes = source.capture_slate(
        slate_date=config.slate_date, horizon_hours=config.horizon_hours, game_ids=config.game_ids
    )
    if aisp_writes != 0:
        raise RuntimeError("AISP source reported a write during read-only capture")
    discovered = len(snapshots)
    preflight_rows = [_dry_run_row(snapshot) for snapshot in snapshots]
    preflight_eligible = sum(row["status"] == "ELIGIBLE_PREFLIGHT_ONLY" for row in preflight_rows)
    if config.limit is not None:
        snapshots = snapshots[:config.limit]
    output_root = config.output_root.resolve()
    if config.dry_run:
        rows = [_dry_run_row(snapshot) for snapshot in snapshots]
        return {
            "schemaVersion": RECEIPT_SCHEMA, "mode": "DRY_RUN", "slateDate": config.slate_date.isoformat(),
            "capturedAt": captured.isoformat(), "gamesDiscovered": discovered, "gamesSelected": len(snapshots),
            "gamesEligible": sum(row["status"] == "ELIGIBLE_PREFLIGHT_ONLY" for row in rows),
            "gamesPreflightEligible": preflight_eligible,
            "gamesDeferredByLimit": discovered - len(snapshots),
            "forecastsCompleted": 0, "gamesSkipped": sum(row["status"] == "SKIPPED" for row in rows),
            "gamesFailed": 0, "games": rows, "aispRowsModified": aisp_writes,
            "providerCalls": 0, "runtimeSeconds": time.perf_counter() - started,
        }
    repository = repo_root or Path(__file__).resolve().parents[2]
    active_engine = engine or V18ExecutionEngine(repository)
    active_view_builder = None
    if engine is None:
        from server.sports_current_statcast.mlb_v18_daily_views import DailyViewBuilder
        active_view_builder = DailyViewBuilder(repository, engine=active_engine)

    def work(snapshot: Mapping[str, Any]) -> dict[str, Any]:
        game_id = snapshot.get("game", {}).get("game_id")
        try:
            validate_pregame_snapshot(snapshot)
            key = publication_key(snapshot)
            key_path = output_root / "publication-keys" / f"{key}.json"
            if key_path.exists():
                pointer = json.loads(key_path.read_text(encoding="utf-8"))
                existing = _verify_existing_object(output_root, pointer)
                if active_view_builder is not None:
                    active_view_builder.build(output_root, {
                        "relativePath": existing.relative_to(output_root).as_posix(),
                        "objectSha256": pointer["objectSha256"],
                    })
                return {"gameId": game_id, "status": "DUPLICATE_ALREADY_PUBLISHED",
                        "category": "DUPLICATE_ALREADY_PUBLISHED", "reason": "same model, evidence, and seed already published",
                        "objectSha256": pointer["objectSha256"], "artifactPath": existing.relative_to(output_root).as_posix(),
                        "capturedAt": snapshot["capturedAt"], "scheduledStart": snapshot["game"]["starts_at"]}
            payload = active_engine.forecast(snapshot)
            validate_forecast_payload(snapshot, payload)
            published = _publish_game(output_root, snapshot, payload)
            if active_view_builder is not None:
                active_view_builder.build(output_root, {
                    "relativePath": published["relativePath"],
                    "objectSha256": published["objectSha256"],
                })
            return {"gameId": game_id, "status": published["status"], "objectSha256": published["objectSha256"],
                    "artifactPath": published["relativePath"], "capturedAt": snapshot["capturedAt"],
                    "scheduledStart": snapshot["game"]["starts_at"],
                    "constructionSeconds": payload["forecast"]["timing"]["constructionSeconds"],
                    "simulationSeconds": payload["forecast"]["timing"]["simulationSeconds"]}
        except DailySlateError as exc:
            status = "SKIPPED" if exc.category in {"MISSING_REQUIRED_EVIDENCE", "INVALID_PARTICIPANT_MAPPING", "GAME_ALREADY_STARTED"} else "FAILED"
            return {"gameId": game_id, "status": status, "category": exc.category, "reason": exc.reason,
                    "capturedAt": snapshot.get("capturedAt"), "scheduledStart": snapshot.get("game", {}).get("starts_at")}
        except Exception as exc:
            return {"gameId": game_id, "status": "FAILED", "category": "MODEL_FAILURE", "reason": str(exc),
                    "capturedAt": snapshot.get("capturedAt"), "scheduledStart": snapshot.get("game", {}).get("starts_at")}

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=config.workers, thread_name_prefix="v18-slate") as pool:
        futures = {pool.submit(work, snapshot): index for index, snapshot in enumerate(snapshots)}
        ordered: dict[int, dict[str, Any]] = {}
        for future in as_completed(futures):
            ordered[futures[future]] = future.result()
        rows = [ordered[index] for index in sorted(ordered)]
    completed = [row for row in rows if row["status"] in {"PUBLISHED", "DUPLICATE_ALREADY_PUBLISHED"}]
    slate_forecasts = collect_slate_forecasts(output_root, config.slate_date)
    _, handoff_sha, handoff_path = _write_handoff(output_root, config.slate_date, slate_forecasts)
    first_pitches = [_as_utc(row["game"]["starts_at"]) for row in snapshots if row.get("game", {}).get("starts_at")]
    captures = [_as_utc(row["capturedAt"]) for row in rows if row.get("capturedAt")]
    receipt_body = {
        "schemaVersion": RECEIPT_SCHEMA, "mode": "PUBLISH", "slateDate": config.slate_date.isoformat(),
        "capturedAt": captured.isoformat(), "gamesDiscovered": discovered, "gamesSelected": len(snapshots),
        "gamesPreflightEligible": preflight_eligible,
        "gamesDeferredByLimit": discovered - len(snapshots),
        "gamesEligible": len(completed), "forecastsCompleted": sum(row["status"] == "PUBLISHED" for row in rows),
        "handoffForecasts": len(slate_forecasts),
        "duplicatesReused": sum(row["status"] == "DUPLICATE_ALREADY_PUBLISHED" for row in rows),
        "gamesSkipped": sum(row["status"] == "SKIPPED" for row in rows),
        "gamesFailed": sum(row["status"] == "FAILED" for row in rows), "games": rows,
        "earliestFirstPitch": min(first_pitches).isoformat() if first_pitches else None,
        "latestFirstPitch": max(first_pitches).isoformat() if first_pitches else None,
        "earliestForecastTimestamp": min(captures).isoformat() if captures else None,
        "latestForecastTimestamp": max(captures).isoformat() if captures else None,
        "runtime": {"startupAndLoadSeconds": active_engine.load_seconds,
                    "totalSlateSeconds": time.perf_counter() - started},
        "executionAccounting": {"modelLoads": active_engine.model_load_count, "modelFits": active_engine.fit_count,
                                "simulationsPerPublishedGame": SIMULATION_COUNT},
        "aispRowsModified": aisp_writes, "gen1RowsModified": 0, "providerCalls": 0,
        "handoffSha256": handoff_sha, "handoffPath": handoff_path, **RESEARCH_FLAGS,
        "finalOot": {"locked": True, "opened": False, "featureRowsRead": 0,
                     "targetsRead": 0, "scored": False},
    }
    return _write_receipt_and_locator(output_root, config.slate_date, receipt_body)


def rebuild_slate_handoff(output_root: Path, slate_date: date) -> dict[str, Any]:
    """Re-index existing verified objects without source access or model execution."""

    started = time.perf_counter()
    root = output_root.resolve()
    forecasts = collect_slate_forecasts(root, slate_date)
    _, handoff_sha, handoff_path = _write_handoff(root, slate_date, forecasts)
    prior_receipts = sorted((root / "slates" / slate_date.isoformat() / "sha256").glob("*/slate-result.json"))
    unresolved: dict[str, dict[str, Any]] = {}
    source_receipts: list[str] = []
    published_ids = {row["gameId"] for row in forecasts}
    for path in prior_receipts:
        receipt = json.loads(path.read_text(encoding="utf-8"))
        source_receipts.append(str(receipt.get("receiptSha256")))
        for row in receipt.get("games", []):
            game_id = row.get("gameId")
            if not game_id or game_id in published_ids:
                continue
            existing = unresolved.get(game_id)
            if existing is None or _as_utc(row.get("capturedAt")) > _as_utc(existing.get("capturedAt")):
                unresolved[game_id] = row
    games = [
        {"gameId": row["gameId"], "status": "PUBLISHED", "objectSha256": row["objectSha256"],
         "artifactPath": row["relativePath"], "capturedAt": row["capturedAt"],
         "scheduledStart": row["scheduledStart"]}
        for row in forecasts
    ] + sorted(unresolved.values(), key=lambda row: (str(row.get("scheduledStart")), str(row.get("gameId"))))
    starts = [_as_utc(row["scheduledStart"]) for row in games if row.get("scheduledStart")]
    captures = [_as_utc(row["capturedAt"]) for row in games if row.get("capturedAt")]
    body = {
        "schemaVersion": RECEIPT_SCHEMA, "mode": "HANDOFF_REBUILD_NO_MODEL_EXECUTION",
        "slateDate": slate_date.isoformat(), "generatedAt": datetime.now(UTC).isoformat(),
        "gamesDiscovered": len(games), "gamesSelected": 0, "gamesPreflightEligible": None,
        "gamesDeferredByLimit": 0, "gamesEligible": len(forecasts), "forecastsCompleted": 0,
        "handoffForecasts": len(forecasts), "duplicatesReused": len(forecasts),
        "gamesSkipped": sum(row.get("status") == "SKIPPED" for row in unresolved.values()),
        "gamesFailed": sum(row.get("status") == "FAILED" for row in unresolved.values()),
        "games": games,
        "earliestFirstPitch": min(starts).isoformat() if starts else None,
        "latestFirstPitch": max(starts).isoformat() if starts else None,
        "earliestForecastTimestamp": min(captures).isoformat() if captures else None,
        "latestForecastTimestamp": max(captures).isoformat() if captures else None,
        "runtime": {"startupAndLoadSeconds": 0.0, "totalSlateSeconds": time.perf_counter() - started},
        "executionAccounting": {"modelLoads": 0, "modelFits": 0, "simulationsPerPublishedGame": SIMULATION_COUNT},
        "sourceReceiptSha256s": source_receipts,
        "aispRowsModified": 0, "gen1RowsModified": 0, "providerCalls": 0,
        "handoffSha256": handoff_sha, "handoffPath": handoff_path, **RESEARCH_FLAGS,
        "finalOot": {"locked": True, "opened": False, "featureRowsRead": 0, "targetsRead": 0, "scored": False},
    }
    return _write_receipt_and_locator(root, slate_date, body)


def read_status(output_root: Path, slate_date: date) -> dict[str, Any]:
    root = output_root.resolve()
    locator_path = root / "slates" / slate_date.isoformat() / "latest.json"
    if not locator_path.exists():
        return {"status": "NO_RUN", "slateDate": slate_date.isoformat(), "outputRoot": str(root)}
    locator = json.loads(locator_path.read_text(encoding="utf-8"))
    receipt_path = root / PurePosixPath(locator["relativePath"]) / "slate-result.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_body = {key: value for key, value in receipt.items() if key not in {"receiptId", "receiptSha256"}}
    if receipt.get("receiptSha256") != locator.get("receiptSha256") or sha_json(receipt_body) != receipt.get("receiptSha256"):
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "latest slate receipt identity differs")
    handoff_path = root / PurePosixPath(receipt["handoffPath"])
    handoff = json.loads(handoff_path.read_text(encoding="utf-8"))
    handoff_body = {key: value for key, value in handoff.items() if key not in {"handoffId", "handoffSha256"}}
    if (
        handoff.get("handoffSha256") != receipt.get("handoffSha256")
        or handoff.get("handoffSha256") != locator.get("handoffSha256")
        or sha_json(handoff_body) != handoff.get("handoffSha256")
    ):
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "latest AISP handoff identity differs")
    current = collect_slate_forecasts(root, slate_date)
    three_view = bool(current) and all(
        row.get("playGeometry") and row.get("populationGeometry") for row in current
    )
    keys = ["gameId", "objectSha256", "relativePath", "forecastFile", "manifestFile"]
    if three_view:
        keys.extend(["playGeometry", "populationGeometry"])
    expected = [{key: row[key] for key in keys} for row in current]
    if handoff.get("forecasts") != expected:
        raise DailySlateError("PERSISTENCE_PUBLICATION_FAILURE", "latest handoff does not index the current verified slate objects")
    return {"status": "AVAILABLE", "verification": "PASS", "verifiedForecasts": len(expected),
            "locator": locator, "receipt": receipt}


__all__ = [
    "AispReadOnlySlateSource", "DailySlateError", "PublishConfig", "V18ExecutionEngine",
    "collect_slate_forecasts", "evidence_logical_digest", "publication_key", "publish_daily_slate",
    "read_status", "rebuild_slate_handoff",
    "select_bullpen_rows", "validate_forecast_payload", "validate_pregame_snapshot",
]
