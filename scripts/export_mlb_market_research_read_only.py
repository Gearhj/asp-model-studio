"""Freeze existing, nonsealed local MLB market evidence without external writes.

The materialized safe-game boundary is applied before market/outcome payload
queries. No provider, AISP ORM mutation, or model execution is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "MLB_MARKET_RESEARCH_READ_ONLY_SOURCE_V1"
BOUNDARY = """
with safe_games as materialized (
 select g.* from games g join leagues l on l.id=g.league_id
 where l.code='MLB'
 and not ((g.starts_at at time zone 'UTC')::date between date '2026-08-14' and date '2026-08-27')
 and not ((g.starts_at at time zone 'America/New_York')::date between date '2026-08-14' and date '2026-08-27')
), scoped_games as materialized (
 select g.* from safe_games g where
 exists(select 1 from markets m join market_outcomes mo on mo.market_id=m.id
        join odds_snapshots q on q.market_outcome_id=mo.id where m.game_id=g.id)
 or exists(select 1 from forecasts f where f.game_id=g.id)
 or exists(select 1 from prediction_market_snapshots p where p.canonical_game_id=g.id)
)
"""

QUERIES = {
"events": """
select g.id::text event_id, g.starts_at event_start, g.status::text event_status,
 g.created_at, g.created_at game_created_at, g.source_mode::text source_mode,
 h.team_id::text home_team_id, a.team_id::text away_team_id,
 ht.name home_team_name, at.name away_team_name,
 ht.abbreviation home_team_abbreviation, at.abbreviation away_team_abbreviation,
 g.home_score, g.away_score, g.final_at,
 null::timestamptz actual_start_at,
 'SCHEDULED_START_PROXY'::text event_start_basis
from scoped_games g
join game_teams h on h.game_id=g.id and h.is_home=true
join game_teams a on a.game_id=g.id and a.is_home=false
join teams ht on ht.id=h.team_id join teams at on at.id=a.team_id
order by g.starts_at,g.id
""",
"quotes": """
select q.id::text quote_id, g.id::text event_id, m.id::text market_id,
 mo.id::text market_outcome_id, m.market_type::text market_type,m.period,
 case when mo.participant_team_id=h.team_id then 'HOME'
      when mo.participant_team_id=a.team_id then 'AWAY'
      when lower(mo.label)='over' then 'OVER'
      when lower(mo.label)='under' then 'UNDER' else 'UNKNOWN' end side,
 mo.participant_team_id::text participant_team_id,mo.outcome_key,mo.label,
 q.point,b.key bookmaker,b.name bookmaker_name,q.source,q.source_mode::text source_mode,
 q.source_event_id,q.observed_at,q.available_as_of,q.created_at,
 q.decimal_odds,q.american_odds,q.implied_probability,q.status::text status,
 q.is_closing,q.payload_checksum,
 (q.observed_at>=g.starts_at) observed_at_or_after_scheduled_start,
 (greatest(q.observed_at,q.available_as_of,q.created_at)>=g.starts_at) operationally_known_at_or_after_scheduled_start
from scoped_games g join markets m on m.game_id=g.id
join market_outcomes mo on mo.market_id=m.id
join odds_snapshots q on q.market_outcome_id=mo.id
join sportsbooks b on b.id=q.sportsbook_id
join game_teams h on h.game_id=g.id and h.is_home=true
join game_teams a on a.game_id=g.id and a.is_home=false
order by g.starts_at,q.observed_at,q.id
""",
"forecasts": """
select f.id::text forecast_id,g.id::text event_id,mv.id::text model_id,
 mv.name model_name,mv.version model_version,mv.identity_checksum model_identity_checksum,
 mv.algorithm,mv.status::text model_status,f.version forecast_version,
 f.generated_at,f.available_as_of,f.published_at,f.created_at,
 f.source_mode::text source_mode,f.status::text status,f.lifecycle::text lifecycle,
 f.forecast_track,f.home_win_probability home_probability,f.away_win_probability away_probability,
 s.data_as_of evidence_cutoff,s.id::text feature_snapshot_id,s.checksum feature_snapshot_checksum,
 s.generated_at feature_snapshot_generated_at,s.created_at feature_snapshot_created_at,
 f.feature_snapshot_reference,f.confidence,f.readiness_score,
 s.feature_completeness,s.missing_features,s.stale_features,s.provisional_features
from scoped_games g join forecasts f on f.game_id=g.id
join model_versions mv on mv.id=f.model_version_id
left join game_feature_snapshots s on s.id=f.feature_snapshot_id
order by g.starts_at,f.generated_at,f.id
""",
"game_state_observations": """
select s.id::text observation_id,s.game_id::text event_id,s.scheduled_at,
 s.status::text status,s.is_postponed,s.postponement_reason,s.doubleheader_status,
 s.game_number,s.observed_at,s.available_as_of,s.created_at,s.source,
 s.source_mode::text source_mode,s.source_record_id,s.payload_checksum
from scoped_games g join game_state_observations s on s.game_id=g.id
where not ((s.scheduled_at at time zone 'UTC')::date between date '2026-08-14' and date '2026-08-27')
and not ((s.scheduled_at at time zone 'America/New_York')::date between date '2026-08-14' and date '2026-08-27')
order by g.starts_at,s.observed_at,s.id
""",
"final_state_observations": """
select s.id::text observation_id,s.game_id::text event_id,s.status::text status,
 s.home_score,s.away_score,s.final_at,s.observed_at,s.available_as_of,s.created_at,
 s.source,s.source_mode::text source_mode,s.source_record_id,s.payload_checksum
from scoped_games g join game_state_observations s on s.game_id=g.id
where upper(s.status::text)='FINAL' and s.home_score is not null and s.away_score is not null
and not ((s.scheduled_at at time zone 'UTC')::date between date '2026-08-14' and date '2026-08-27')
and not ((s.scheduled_at at time zone 'America/New_York')::date between date '2026-08-14' and date '2026-08-27')
order by g.starts_at,greatest(s.observed_at,s.available_as_of,s.created_at),s.id
""",
"official_outcomes": """
select o.id::text outcome_id,o.game_id::text event_id,o.home_score,o.away_score,
 o.outcome_status,o.revision,o.official,o.final_at,o.source_published_at,o.retrieved_at,
 o.label_available_at,o.availability_basis,o.created_at,o.source_mode::text source_mode,
 o.source_record_id,o.payload_checksum,o.temporal_semantics,o.evidence_classification,
 o.quality_tier,o.completion_time_basis,o.completion_time_limitation
from scoped_games g join game_final_outcomes o on o.game_id=g.id
order by g.starts_at,o.revision,o.id
""",
"prediction_markets": """
select p.id::text snapshot_id,p.canonical_game_id::text event_id,p.provider,
 p.contract_id::text contract_id,p.provider_market_id,p.provider_outcome_id,
 p.market_type,p.selection,p.line_value,
 case when p.market_type like 'FULL_GAME_%' then 'full_game' else null end period,
 'MARKET_TYPE_LABEL_ONLY_NOT_APPROVED_SEMANTICS'::text period_basis,
 p.midpoint,p.best_bid,p.best_ask,p.bid_ask_spread,p.volume,p.open_interest,p.liquidity,
 p.provider_observed_at,p.aisp_received_at,p.created_at,p.game_starts_at,
 p.mapping_status,p.semantics_status,p.quality_tier,p.quality_flags,
 p.quote_fresh,p.pregame_eligible,p.in_play,p.source_status,p.raw_payload_sha256,
 p.adapter_version,p.timeline_cut,p.book_complete,p.market_liquid
from scoped_games g join prediction_market_snapshots p on p.canonical_game_id=g.id
order by g.starts_at,p.provider_observed_at,p.id
""",
"prediction_market_contracts": """
select c.id::text contract_id,c.created_at,c.provider,c.provider_event_id,
 c.provider_market_id,c.provider_outcome_id,c.market_type,c.selection,c.line_value,
 c.sport,c.league,c.outcome_label,c.provider_home_team,c.provider_away_team,
 c.scheduled_start_at,c.provider_game_start_at,c.market_question,c.market_subtitle,
 c.resolution_rules,c.rules_sha256,c.market_close_at,c.settlement_source,
 c.market_status,c.line_source,c.version,c.content_checksum,c.adapter_version
from prediction_market_contracts c where exists (
 select 1 from scoped_games g join prediction_market_snapshots p on p.canonical_game_id=g.id
 where p.contract_id=c.id)
order by c.id
""",
"prediction_market_mappings": """
select m.id::text mapping_id,m.created_at,m.provider,m.provider_event_id,
 m.canonical_game_id::text event_id,m.mapping_status,m.semantics_status,
 m.decision_source,m.reason,m.start_time_delta_seconds,m.decided_at,m.supersedes_id::text supersedes_id
from scoped_games g join prediction_market_mappings m on m.canonical_game_id=g.id
order by m.decided_at,m.id
""",
"lineup_observations": """
select l.id::text observation_id,l.game_id::text event_id,l.team_id::text team_id,
 l.lineup_status,l.is_complete,l.observed_at,l.available_as_of,l.created_at,
 l.source,l.source_mode::text source_mode,l.source_record_id,l.payload_checksum
from scoped_games g join lineup_observations l on l.game_id=g.id
order by g.starts_at,l.observed_at,l.id
""",
"starter_observations": """
select s.id::text observation_id,s.game_id::text event_id,s.team_id::text team_id,
 s.probable_pitcher_id::text probable_pitcher_id,s.confirmed_pitcher_id::text confirmed_pitcher_id,
 s.confirmation_state,s.observed_at,s.available_as_of,s.created_at,
 s.source,s.source_mode::text source_mode,s.source_record_id,s.payload_checksum
from scoped_games g join starter_observations s on s.game_id=g.id
order by g.starts_at,s.observed_at,s.id
""",
}


def normalize(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Naive source datetime: time zone cannot be invented")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, (date, UUID)):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize(v) for v in value]
    return value


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def extract(output_root: Path, max_rows: int = 500_000):
    url = dotenv_values("C:/Users/james/ai-sports-predictor/.env")["DATABASE_URL"]
    url = url.replace("postgresql+psycopg://", "postgresql+psycopg2://")
    parsed = make_url(url)
    if parsed.host not in {"localhost", "127.0.0.1", "::1"} or parsed.database != "asp":
        raise ValueError("Only the existing local AISP asp database is authorized")
    output_root = output_root.resolve()
    if not output_root.is_relative_to(ROOT / "outputs" / "market-intelligence-rff-v1" / "source"):
        raise ValueError("Output must remain within this Model Studio source-export root")
    engine = create_engine(url)
    arrays = {}
    captured_at = datetime.now(UTC).isoformat()
    try:
        with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
            transaction = conn.begin()
            conn.execute(text("SET TRANSACTION READ ONLY"))
            if conn.execute(text("SHOW transaction_read_only")).scalar_one() != "on":
                raise RuntimeError("Read-only transaction was not enforced")
            safe_count = conn.execute(text(BOUNDARY + "select count(*) from safe_games")).scalar_one()
            for name, query in QUERIES.items():
                rows = conn.execute(text(BOUNDARY + query)).mappings()
                result = []
                for row in rows:
                    if len(result) >= max_rows:
                        raise RuntimeError(f"{name} exceeds the declared {max_rows} row limit; no partial export published")
                    result.append(normalize(dict(row)))
                arrays[name] = result
                print(json.dumps({"readOnlyExtracted": name, "rows": len(result)}), flush=True)
            transaction.rollback()
    finally:
        engine.dispose()

    event_map = {r["event_id"]: r for r in arrays["events"]}
    for event in event_map.values():
        event.update(outcome_available_at=None, outcome_source=None, outcome_observation_id=None,
                     outcome_availability_basis="UNKNOWN", schedule_observed_at=None)
        if event["home_score"] is not None and event["away_score"] is not None:
            event["outcome_source"] = "CANONICAL_GAME_SCORE_AVAILABILITY_UNKNOWN"
    for row in arrays["game_state_observations"]:
        event = event_map[row["event_id"]]
        if row["scheduled_at"] == event["event_start"]:
            known = max(row[k] for k in ("observed_at", "available_as_of", "created_at") if row[k])
            if event["schedule_observed_at"] is None or known < event["schedule_observed_at"]:
                event["schedule_observed_at"] = known
    for row in arrays["final_state_observations"]:
        event = event_map[row["event_id"]]
        if row["home_score"] == event["home_score"] and row["away_score"] == event["away_score"]:
            known = max(row[k] for k in ("observed_at", "available_as_of", "created_at") if row[k])
            if event["outcome_available_at"] is None or known < event["outcome_available_at"]:
                event.update(outcome_available_at=known, outcome_source=row["source"],
                             outcome_observation_id=row["observation_id"],
                             outcome_availability_basis="FIRST_STORED_FINAL_OBSERVATION_MATCHING_CURRENT_CANONICAL_SCORE_MAX_OBSERVED_AVAILABLE_CREATED")
    for row in arrays["official_outcomes"]:
        event = event_map[row["event_id"]]
        if row["official"] and row["home_score"] == event["home_score"] and row["away_score"] == event["away_score"]:
            known = max((row[k] for k in ("label_available_at", "created_at", "retrieved_at") if row[k]), default=None)
            event.update(outcome_available_at=known, outcome_source="REVISIONED_OFFICIAL_FINAL_OUTCOME",
                         outcome_observation_id=row["outcome_id"],
                         outcome_availability_basis="MAX_LABEL_AVAILABLE_RETRIEVED_CREATED_OF_CURRENT_OFFICIAL_REVISION")

    counts = {k: len(v) for k, v in arrays.items()}
    summary = {
        "safeMlbEventsBeforeMarketScope": safe_count,
        "counts": counts,
        "eventDateMin": min((r["event_start"] for r in arrays["events"]), default=None),
        "eventDateMax": max((r["event_start"] for r in arrays["events"]), default=None),
        "quoteSourceModes": dict(Counter(f'{r["source"]}|{r["source_mode"]}' for r in arrays["quotes"])),
        "quoteSides": dict(Counter(r["side"] for r in arrays["quotes"])),
        "quoteObservedAfterScheduledStart": sum(r["observed_at_or_after_scheduled_start"] for r in arrays["quotes"]),
        "quoteOperationallyKnownAfterScheduledStart": sum(r["operationally_known_at_or_after_scheduled_start"] for r in arrays["quotes"]),
        "forecastStatuses": dict(Counter(f'{r["status"]}|{r["lifecycle"]}|{r["source_mode"]}' for r in arrays["forecasts"])),
        "forecastsPublishedAtRecorded": sum(r["published_at"] is not None for r in arrays["forecasts"]),
        "forecastsOperationallyKnownBeforeStart": sum(all(r[k] is not None for k in ("generated_at", "available_as_of", "created_at")) and max(r[k] for k in ("generated_at", "available_as_of", "created_at")) < event_map[r["event_id"]]["event_start"] for r in arrays["forecasts"]),
        "forecastsPublishedBeforeStart": sum(r["published_at"] is not None and max(r[k] for k in ("generated_at", "available_as_of", "created_at", "published_at") if r[k]) < event_map[r["event_id"]]["event_start"] for r in arrays["forecasts"]),
        "pmSemantics": dict(Counter(f'{r["mapping_status"]}|{r["semantics_status"]}|{r["quality_tier"]}' for r in arrays["prediction_markets"])),
        "eventOutcomeAvailability": dict(Counter(r["outcome_availability_basis"] for r in arrays["events"])),
    }
    files = {}
    blobs = {}
    for name, rows in arrays.items():
        payload = encoded(rows)
        blob = gzip.compress(payload, compresslevel=6, mtime=0)
        filename = name + ".json.gz"
        files[name] = {"path": filename, "sha256": digest(blob), "bytes": len(blob),
                       "uncompressedSha256": digest(payload), "uncompressedBytes": len(payload),
                       "rowCount": len(rows), "format": "JSON_ARRAY_GZIP"}
        blobs[filename] = blob
    manifest = {
        "schemaVersion": SCHEMA, "capturedAt": captured_at,
        "database": {"host": "localhost", "database": "asp", "transaction": "REPEATABLE_READ_READ_ONLY"},
        "sealedBoundary": {"excludedDatesInclusive": ["2026-08-14", "2026-08-27"],
                           "zonesChecked": ["UTC", "America/New_York"],
                           "mechanism": "MATERIALIZED_SAFE_GAMES_SQL_BEFORE_PAYLOAD_QUERIES",
                           "sealedEventPayloadRowsRead": 0},
        "scope": "ALL_EXISTING_LOCAL_MLB_HISTORY_WITH_ODDS_FORECAST_OR_PREDICTION_MARKET_EVIDENCE_EXCLUDING_SEALED_DATES",
        "completeWithinScope": True, "rowLimitPerArray": max_rows,
        "sourceFiles": {"script": str(Path(__file__).resolve()), "scriptSha256": digest(Path(__file__).read_bytes())},
        "querySha256": {k: digest((BOUNDARY + v).encode()) for k, v in QUERIES.items()},
        "timestampSemantics": {
            "quoteObservedAt": "Provider market last_update (ingestion/normalizer.py ingest_odds).",
            "quoteAvailableAsOf": "Caller-supplied ingestion knowledge time; not provider publication time.",
            "createdAt": "AISP persistence insertion clock, preserved separately to identify operational late arrival or backfill.",
            "primaryOperationalPIT": "Require all relevant timestamps and max(observed_at, available_as_of, created_at) <= checkpoint.",
            "forecastPublishedAt": "Preserved; null remains unknown. Availability and publication are distinct.",
            "eventStart": "SCHEDULED_START_PROXY; actual first-pitch timestamp unavailable in this source contract.",
            "outcomeAvailableAt": "Known time of stored matching final-score evidence, never inferred from final_at.",
            "predictionMarketMapping": "All recorded mapping decisions exported; a checkpoint must not use decided_at or created_at later than itself.",
        },
        "pairing": {"nativePairedTwoSidedIdentity": False,
                    "preservedPairingFields": ["event_id", "market_id", "market_type", "period", "bookmaker", "source", "source_event_id", "observed_at", "available_as_of", "point", "side"],
                    "rule": "Consumer must verify contemporaneous compatible two-sided prices; do not treat unrelated snapshots as a native pair."},
        "unavailableEvidence": ["PUBLIC_TICKET_PERCENTAGES", "PUBLIC_HANDLE_PERCENTAGES", "ACTUAL_SPORTSBOOK_LIABILITY", "SOCIAL_NARRATIVE_TIMELINE", "ACTUAL_FIRST_PITCH_TIMESTAMP"],
        "limitations": ["Prediction-market EXACT identity mapping does not imply approved settlement semantics.",
                        "LIVE source mode is provider provenance, not proof of historical operational availability.",
                        "Canonical scheduled starts may be revised; schedule observation history must govern checkpoint identity.",
                        "Lineup/starter observations show only the existing local observation coverage, not complete news or injury coverage."],
        "activity": {"providerCalls": 0, "aispWrites": 0, "modelFits": 0, "ootPayloadReads": 0},
        "summary": summary, "files": files,
    }
    manifest_bytes = encoded(manifest)
    manifest_digest = digest(manifest_bytes)
    destination = output_root / "sha256" / manifest_digest
    destination.mkdir(parents=True, exist_ok=True)
    for filename, blob in {**blobs, "manifest.json": manifest_bytes}.items():
        target = destination / filename
        if target.exists():
            if target.read_bytes() != blob:
                raise RuntimeError(f"Immutable artifact collision: {target}")
        else:
            with target.open("xb") as handle:
                handle.write(blob)
        if digest(target.read_bytes()) != digest(blob):
            raise RuntimeError(f"Reload checksum mismatch: {target}")
    receipt = {"manifestPath": str(destination / "manifest.json"), "sha256": manifest_digest, **summary}
    print(json.dumps(receipt, indent=2), flush=True)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs" / "market-intelligence-rff-v1" / "source")
    parser.add_argument("--max-rows-per-array", type=int, default=500_000)
    args = parser.parse_args()
    extract(args.output_root, args.max_rows_per_array)
