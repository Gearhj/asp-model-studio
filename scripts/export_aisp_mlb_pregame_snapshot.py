"""Export one immutable, read-only AISP MLB pregame snapshot for Model Studio.

Run this script with AISP's virtual environment.  It performs SELECT statements only,
uses no provider, and writes one artifact that is subsequently consumed without database
coupling.  When the target game's lineup is not yet published, the most recent prior
complete lineup available before the export instant becomes an explicitly projected lineup.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--aisp-root", type=Path, required=True)
    parser.add_argument("--game-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    load_dotenv(args.aisp_root / ".env")
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("AISP DATABASE_URL is unavailable")
    captured = datetime.now(UTC)
    engine = create_engine(database_url)
    with engine.connect() as connection:
        games = connection.execute(text("""
            select g.id::text game_id, g.starts_at, g.status::text status,
                   g.scheduled_innings, v.name venue, v.timezone,
                   gm.external_id source_game_id
            from games g left join venues v on v.id=g.venue_id
            left join external_id_mappings gm on gm.entity_id=g.id
              and gm.entity_type='game' and gm.source='MLB_STATS_API'
            where g.id=cast(:game_id as uuid)
        """), {"game_id": args.game_id}).mappings().all()
        if len(games) != 1:
            raise RuntimeError("exactly one AISP game is required")
        game = dict(games[0])
        starts_at = game["starts_at"]
        if captured >= starts_at.astimezone(UTC):
            raise RuntimeError("prospective snapshot capture must precede scheduled first pitch")

        sides = connection.execute(text("""
            with latest_starter as (
              select distinct on (so.team_id) so.team_id, so.confirmation_state,
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
        """), {"game_id": args.game_id, "captured": captured}).mappings().all()
        if len(sides) != 2 or any(not row["pitcher_mlbam"] for row in sides):
            raise RuntimeError("both pregame starter identities are required")

        output_sides = []
        for side in sides:
            team_id = side["team_uuid"]
            current = connection.execute(text("""
                select lo.id::text observation_id,lo.lineup_status,lo.is_complete,
                       lo.observed_at,lo.available_as_of,lo.source
                from lineup_observations lo
                where lo.game_id=cast(:game_id as uuid) and lo.team_id=cast(:team_id as uuid)
                  and lo.available_as_of <= :captured
                order by lo.available_as_of desc limit 1
            """), {"game_id": args.game_id, "team_id": team_id, "captured": captured}).mappings().first()
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
                """), {"team_id": team_id, "captured": captured, "target_start": starts_at}).mappings().first()
            if lineup is None:
                raise RuntimeError(f"no pregame lineup or prior complete projection exists for {side['abbreviation']}")
            entries = connection.execute(text("""
                select le.batting_order,p.full_name,pm.external_id mlbam,
                       coalesce(le.bats,b.bats) bats,le.defensive_position
                from lineup_entries le join players p on p.id=le.player_id
                left join batters b on b.player_id=p.id
                left join external_id_mappings pm on pm.entity_id=p.id
                  and pm.entity_type='player' and pm.source='MLB_STATS_API'
                where le.lineup_observation_id=cast(:lineup_id as uuid) and le.is_starter=true
                order by le.batting_order
            """), {"lineup_id": lineup["observation_id"]}).mappings().all()
            if len(entries) != 9 or [row["batting_order"] for row in entries] != list(range(1, 10)):
                raise RuntimeError("selected lineup is not a complete ordered nine")
            if any(not row["mlbam"] for row in entries):
                raise RuntimeError("selected lineup contains an unresolved MLB identity")
            authority = {
                "status": "PROJECTED_PRIOR_COMPLETE_LINEUP" if projected else "CONFIRMED",
                "source": lineup["source"],
                "observedAt": lineup["observed_at"],
                "availableAsOf": lineup["available_as_of"],
                "projectionMethod": "MOST_RECENT_PRIOR_COMPLETE_LINEUP_AVAILABLE_BEFORE_CAPTURE" if projected else None,
            }
            output_sides.append({
                "side": "HOME" if side["is_home"] else "AWAY",
                "team": {"uuid": team_id, "abbreviation": side["abbreviation"], "name": side["name"]},
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
                "lineup": [dict(row) for row in entries],
            })

        weather = connection.execute(text("""
            select source,observed_at,available_as_of,temperature_f,wind_mph,
                   wind_direction,precipitation_probability,payload_checksum
            from weather_snapshots where game_id=cast(:game_id as uuid)
              and available_as_of <= :captured order by available_as_of desc limit 1
        """), {"game_id": args.game_id, "captured": captured}).mappings().first()
        inventory = connection.execute(text("""
            select
              (select count(*) from roster_availability_observations r
                where r.available_as_of <= :captured) roster_observations,
              (select count(*) from player_talent_estimates p
                where p.available_as_of <= :captured) talent_estimates,
              (select count(*) from bullpen_availability_observations b
                where b.available_as_of <= :captured) bullpen_observations,
              (select count(*) from park_factor_versions p
                where p.available_as_of <= :captured) park_factor_versions
        """), {"captured": captured}).mappings().one()

    body = {
        "schemaVersion": "AISP_MLB_READ_ONLY_PREGAME_SNAPSHOT_V1",
        "captureMode": "PERSISTED_AISP_EVIDENCE_SELECT_ONLY_NO_PROVIDER_CALLS",
        "capturedAt": captured,
        "game": game,
        "sides": output_sides,
        "weather": dict(weather) if weather else None,
        "inventoryCounts": dict(inventory),
        "outcomesRead": False,
        "marketDataRead": False,
        "aispRowsModified": 0,
    }
    raw = _json(body)
    payload = {**body, "contentSha256": hashlib.sha256(raw).hexdigest()}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(_json(payload))
    print(json.dumps({
        "output": str(args.output.resolve()), "contentSha256": payload["contentSha256"],
        "gameId": args.game_id, "capturedAt": captured.isoformat(),
        "lineupModes": [side["lineupAuthority"]["status"] for side in output_sides],
        "aispRowsModified": 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
