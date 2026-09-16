"""Export the actual next MLB slate from AISP using SELECT-only local access.

No prior-game lineup substitution, forecasts, providers, or historical/OOT
payloads are executed/read. Output is evidence, not a model publication.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
SAFE_CURRENT_START = datetime(2026, 8, 28, tzinfo=timezone.utc)


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str, allow_nan=False).encode('utf-8')


def latest_roster_batches(observations):
    """Use the latest complete provider roster retrieval per team/source.

    AISP retains old per-player ACTIVE observations after players disappear from
    subsequent active-roster responses. Absence is not an invented inactive
    status: preserve those observations separately, but never carry them forward.
    """
    def key(row):
        return row['team_id'], row['source'], row['source_mode']
    latest = {}
    for row in observations:
        if row.get('observed_at') is not None:
            latest[key(row)] = max(latest.get(key(row), row['observed_at']), row['observed_at'])
    selected = [r for r in observations if r.get('observed_at') == latest.get(key(r))]
    excluded = [r for r in observations if r.get('observed_at') != latest.get(key(r))]
    return selected, excluded


def capture_current_slate(*, output_root=None, aisp_root=Path('C:/Users/james/ai-sports-predictor'), slate_date=None, game_ids=None):
    captured = datetime.now(timezone.utc)
    if captured < datetime(2026, 9, 10, tzinfo=timezone.utc):
        raise ValueError('This bounded inventory requires the authorized September 10+ execution clock')
    url = make_url(dotenv_values(aisp_root / '.env')['DATABASE_URL'].replace(
        'postgresql+psycopg://', 'postgresql+psycopg2://'))
    if url.host not in ('localhost', '127.0.0.1'):
        raise ValueError('Only the existing local read-only database is authorized')
    engine = create_engine(url)
    queries = []
    with engine.connect().execution_options(isolation_level='REPEATABLE READ') as connection:
        transaction = connection.begin()
        connection.execute(text('SET TRANSACTION READ ONLY'))
        read_only = connection.execute(text('SHOW transaction_read_only')).scalar()
        if read_only != 'on':
            raise ValueError('Database read-only transaction was not confirmed')

        def rows(query, **parameters):
            queries.append({'sqlSha256': hashlib.sha256(query.encode()).hexdigest(), 'parameters': parameters})
            return [dict(row) for row in connection.execute(text(query), parameters).mappings()]

        schedule = rows('''select g.id::text game_id,g.starts_at,g.status,g.created_at schedule_record_created_at,
              g.scheduled_innings,g.source_mode,g.venue_id::text venue_id,v.name venue,v.timezone,
              v.latitude venue_latitude,v.longitude venue_longitude,
              (select em.external_id from external_id_mappings em where em.entity_id=g.venue_id
                and em.entity_type='venue' and em.source='MLB_STATS_API' order by em.created_at desc limit 1) source_venue_id,
              (select em.external_id from external_id_mappings em where em.entity_id=g.id
                and em.entity_type='game' and em.source='MLB_STATS_API' order by em.created_at desc limit 1) source_game_id
            from games g join leagues l on l.id=g.league_id left join venues v on v.id=g.venue_id
            where l.code='MLB' and g.starts_at>=:captured and g.starts_at<:horizon
            order by g.starts_at,g.id''', captured=captured, horizon=captured + timedelta(days=7))
        roster_refresh_runs = rows('''select id::text id,source,job_name,status,started_at,completed_at,
              records_processed,warnings,error_message,raw_reference,schema_version,source_metadata
            from ingestion_runs where source='MLB_STATS_API' and job_name='refresh-mlb-data'
              and completed_at<=:captured order by completed_at desc,id desc limit 3''', captured=captured)
        daily_pipeline_runs = rows('''select id::text id,job_name,status,started_at,completed_at,
              parameters,result,error_message
            from job_runs where job_name='daily-pipeline' and completed_at<=:captured
              order by completed_at desc,id desc limit 3''', captured=captured)
        latest_owner_date = ((daily_pipeline_runs[0].get('parameters') or {}).get('event_date')
                             if daily_pipeline_runs else None)
        latest_owner_target_teams = rows('''select distinct t.abbreviation
            from games g join game_teams gt on gt.game_id=g.id join teams t on t.id=gt.team_id
            join leagues l on l.id=g.league_id where l.code='MLB'
              and (g.starts_at at time zone 'America/New_York')::date=cast(:event_date as date)
            order by t.abbreviation''', event_date=latest_owner_date) if latest_owner_date else []
        roster_refresh_owner = {
            'owner': 'AISP_ASP_DAILY_PIPELINE',
            'jobName': 'daily-pipeline/refresh-mlb-data',
            'schedule': '06:00 America/New_York',
            'provider': 'MLB_STATS_API',
            'endpoint': '/api/v1/teams/{mlbamTeamId}/roster?rosterType=active&date={eventDate}&hydrate=person',
            'latestIngestionRuns': roster_refresh_runs,
            'latestOwnerRuns': daily_pipeline_runs,
            'latestOwnerTargetTeams': [row['abbreviation'] for row in latest_owner_target_teams],
        }
        if slate_date is not None:
            from datetime import date
            slate_date = date.fromisoformat(str(slate_date))
        else:
            slate_date = schedule[0]['starts_at'].astimezone(ZoneInfo('America/New_York')).date() if schedule else None
        schedule = [r for r in schedule if r['starts_at'].astimezone(ZoneInfo('America/New_York')).date() == slate_date]
        if game_ids is not None:
            schedule = [r for r in schedule if r['game_id'] in set(game_ids)]
        output, snapshots, all_ingestion_ids = [], [], set()
        for game in schedule:
            game_id = game['game_id']
            params = {'game_id': game_id, 'captured': captured}
            teams = rows('''select gt.team_id::text team_id,gt.is_home,t.abbreviation,t.name,
                 gt.probable_pitcher_id::text schedule_probable_pitcher_id,gt.pitcher_status_observed_at,
                 gt.pitcher_confirmed from game_teams gt join teams t on t.id=gt.team_id
                 where gt.game_id=cast(:game_id as uuid) order by gt.is_home''', game_id=game_id)
            starters = rows('''select distinct on (so.team_id) so.id::text id,so.team_id::text team_id,
                 coalesce(so.confirmed_pitcher_id,so.probable_pitcher_id)::text player_id,p.full_name,
                 (select external_id from external_id_mappings em where em.entity_id=p.id and em.entity_type='player'
                   and em.source='MLB_STATS_API' order by em.created_at desc limit 1) mlbam_id,
                 so.confirmation_state,so.throws,so.days_rest,so.pitches_previous_day,so.pitches_last_start,
                 so.workload,so.observed_at,so.available_as_of,so.created_at ingested_at,so.source,so.source_mode,so.source_record_id,
                 so.payload_checksum,so.ingestion_run_id::text ingestion_run_id
                 from starter_observations so left join players p on p.id=coalesce(so.confirmed_pitcher_id,so.probable_pitcher_id)
                 where so.game_id=cast(:game_id as uuid) and so.available_as_of<=:captured
                 order by so.team_id,so.available_as_of desc,so.observed_at desc,so.id''', **params)
            by_team = {row['team_id']: row for row in starters}
            sides, reasons = [], []
            for team in teams:
                side = 'HOME' if team['is_home'] else 'AWAY'
                starter = by_team.get(team['team_id']) or {}
                lineup_rows = rows('''select lo.id::text observation_id,lo.lineup_status,lo.is_complete,
                    lo.observed_at,lo.available_as_of,lo.created_at ingested_at,lo.source,lo.source_mode,lo.source_record_id,
                    lo.payload_checksum,lo.ingestion_run_id::text ingestion_run_id
                    from lineup_observations lo where lo.game_id=cast(:game_id as uuid)
                    and lo.team_id=cast(:team_id as uuid) and lo.available_as_of<=:captured
                    order by lo.available_as_of desc,lo.observed_at desc,lo.id limit 1''', **params, team_id=team['team_id'])
                lineup = lineup_rows[0] if lineup_rows else None
                entries = rows('''select le.player_id::text player_id,le.batting_order,p.full_name,
                    (select external_id from external_id_mappings em where em.entity_id=p.id and em.entity_type='player'
                     and em.source='MLB_STATS_API' order by em.created_at desc limit 1) mlbam,
                    coalesce(le.bats,b.bats) bats,le.defensive_position
                    from lineup_entries le join players p on p.id=le.player_id left join batters b on b.player_id=p.id
                    where le.lineup_observation_id=cast(:lineup_id as uuid) and le.is_starter=true
                    order by le.batting_order,le.player_id''', lineup_id=lineup['observation_id']) if lineup else []
                complete = bool(lineup and lineup['is_complete'] and len(entries) == 9 and
                    [e['batting_order'] for e in entries] == list(range(1, 10)) and all(e['mlbam'] for e in entries))
                if not starter.get('mlbam_id') or not starter.get('available_as_of'):
                    reasons.append(side + '_STARTER_IDENTITY_OR_TIMESTAMP_UNAVAILABLE')
                if not complete:
                    reasons.append(side + '_CURRENT_GAME_ORDERED_LINEUP_UNAVAILABLE')
                for observation in (starter, lineup or {}):
                    if observation.get('ingestion_run_id'):
                        all_ingestion_ids.add(observation['ingestion_run_id'])
                sides.append({'side': side, 'team': {'uuid': team['team_id'], 'abbreviation': team['abbreviation'], 'name': team['name']},
                    'starter': {'uuid': starter.get('player_id'), 'name': starter.get('full_name'), 'mlbamId': starter.get('mlbam_id'),
                        'throws': starter.get('throws'), 'confirmationState': starter.get('confirmation_state'),
                        'daysRest': starter.get('days_rest'), 'pitchesPreviousDay': starter.get('pitches_previous_day'),
                        'pitchesLastStart': starter.get('pitches_last_start'), 'workload': starter.get('workload'),
                        'observedAt': starter.get('observed_at'), 'availableAsOf': starter.get('available_as_of'),
                        'ingestedAt': starter.get('ingested_at'),
                        'source': starter.get('source'), 'observationId': starter.get('id'),
                        'payloadChecksum': starter.get('payload_checksum')},
                    'lineupAuthority': {'status': lineup['lineup_status'] if lineup else 'UNAVAILABLE',
                        'isComplete': complete, 'source': lineup.get('source') if lineup else None,
                        'observedAt': lineup.get('observed_at') if lineup else None,
                        'availableAsOf': lineup.get('available_as_of') if lineup else None,
                        'ingestedAt': lineup.get('ingested_at') if lineup else None,
                        'observationId': lineup.get('observation_id') if lineup else None,
                        'payloadChecksum': lineup.get('payload_checksum') if lineup else None,
                        'sourceGameId': game_id, 'projectionMethod': None}, 'lineup': entries,
                    'scheduleProbablePitcherId': team['schedule_probable_pitcher_id']})
            weather = rows('''select id::text id,source,observed_at,available_as_of,temperature_f,wind_mph,
                 wind_direction,precipitation_probability,payload_checksum,source_mode from weather_snapshots
                 where game_id=cast(:game_id as uuid) and available_as_of<=:captured
                 order by available_as_of desc,observed_at desc,id limit 1''', **params)
            state = rows('''select id::text id,scheduled_at,status,is_postponed,postponement_reason,
                 doubleheader_status,game_number,scheduled_innings,observed_at,available_as_of,source,source_mode,
                 source_record_id,payload_checksum,ingestion_run_id::text ingestion_run_id
                 from game_state_observations where game_id=cast(:game_id as uuid) and available_as_of<=:captured
                 order by available_as_of desc,observed_at desc,id limit 1''', **params)
            feature_snapshots = rows('''select id::text id,generated_at,data_as_of,feature_schema_version,
                 feature_version_id::text feature_version_id,checksum,source_mode,feature_completeness,
                 missing_features,stale_features,provisional_features,source_evidence,feature_values,
                 home_lineup_observation_id::text home_lineup_observation_id,
                 away_lineup_observation_id::text away_lineup_observation_id,
                 home_starter_observation_id::text home_starter_observation_id,
                 away_starter_observation_id::text away_starter_observation_id
                 from game_feature_snapshots where game_id=cast(:game_id as uuid) and data_as_of<=:captured
                   and generated_at<=:captured order by generated_at desc,id limit 1''', **params)
            components = {}
            for table in ('batting_features', 'pitching_features', 'team_features', 'bullpen_features'):
                components[table] = rows(f'''select distinct on (team_id) id::text id,team_id::text team_id,
                    feature_version_id::text feature_version_id,observed_at,available_as_of,values,source,source_mode
                    from {table} where game_id=cast(:game_id as uuid) and available_as_of<=:captured
                    order by team_id,available_as_of desc,observed_at desc,id''', **params)
            bullpen = rows('''select distinct on (team_id,player_id) id::text id,team_id::text team_id,
                 player_id::text player_id,role,throws,pitches_previous_day,appearances_last_three_days,
                 innings_last_three_days,used_consecutive_days,expected_available,participation_probability,
                 workload,observed_at,available_as_of,source,source_mode,payload_checksum
                 from bullpen_availability_observations where game_id=cast(:game_id as uuid)
                 and available_as_of<=:captured order by team_id,player_id,available_as_of desc,id''', **params)
            forecasts = rows('''select distinct on (f.model_version_id) f.id::text id,f.version,f.generated_at,
                 f.available_as_of,f.forecast_track,f.status,f.source_mode,f.feature_snapshot_id::text feature_snapshot_id,
                 f.feature_snapshot_reference,m.id::text model_version_id,m.name model_name,m.version model_version,
                 m.algorithm,m.artifact_uri,m.artifact_checksum,m.feature_names,m.training_window,m.trained_at
                 from forecasts f join model_versions m on m.id=f.model_version_id
                 where f.game_id=cast(:game_id as uuid) and f.generated_at<=:captured
                 order by f.model_version_id,f.generated_at desc,f.version desc''', **params)
            player_ids = sorted({p for s in sides for p in [s['starter']['uuid'], *[e['player_id'] for e in s['lineup']]]} - {None})
            team_ids = [r['team_id'] for r in teams]
            player_meta = {}
            for table in ('statcast_player_observations', 'player_talent_estimates'):
                player_meta[table] = rows(f'''select source,source_mode,role,count(*) observation_count,
                    count(distinct player_id) players,min(observed_at) first_observed_at,max(observed_at) latest_observed_at,
                    min(available_as_of) first_available_as_of,max(available_as_of) latest_available_as_of,
                    min(evidence_cutoff) first_evidence_cutoff,max(evidence_cutoff) latest_evidence_cutoff
                    from {table} where player_id=any(cast(:player_ids as uuid[])) and available_as_of<=:captured
                    and observed_at>=:safe_start group by source,source_mode,role''', player_ids=player_ids,
                    captured=captured, safe_start=SAFE_CURRENT_START) if player_ids else []
            roster = rows('''select source,source_mode,count(*) observation_count,count(distinct player_id) players,
                min(observed_at) first_observed_at,max(observed_at) latest_observed_at,
                max(available_as_of) latest_available_as_of from roster_availability_observations
                where team_id=any(cast(:team_ids as uuid[])) and available_as_of<=:captured and observed_at>=:safe_start
                group by source,source_mode''', team_ids=team_ids, captured=captured, safe_start=SAFE_CURRENT_START)
            current_roster = rows('''select distinct on (r.team_id,r.player_id)
                r.id::text observation_id,r.team_id::text team_id,r.player_id::text player_id,
                t.abbreviation team_code,p.full_name,p.position,pi.throws,
                (select em.external_id from external_id_mappings em where em.entity_id=p.id
                 and em.entity_type='player' and em.source='MLB_STATS_API'
                 order by em.created_at desc limit 1) mlbam_id,
                r.availability_status,r.active_roster,r.effective_at,r.transaction_status,
                r.observed_at,r.available_as_of,r.created_at ingested_at,
                r.source,r.source_mode,r.payload_checksum
                from roster_availability_observations r join players p on p.id=r.player_id
                join teams t on t.id=r.team_id left join pitchers pi on pi.player_id=r.player_id
                where r.team_id=any(cast(:team_ids as uuid[])) and r.available_as_of<=:captured
                and r.observed_at>=:safe_start and r.effective_at<=:captured and r.created_at<=:captured
                order by r.team_id,r.player_id,r.available_as_of desc,r.observed_at desc,r.id''',
                team_ids=team_ids, captured=captured, safe_start=SAFE_CURRENT_START)
            current_roster, superseded_roster = latest_roster_batches(current_roster)
            team_crosswalk = rows('''select t.id::text team_id,t.abbreviation,em.external_id mlbam_id
                from teams t join leagues l on l.id=t.league_id join external_id_mappings em
                on em.entity_id=t.id and em.entity_type='team' and em.source='MLB_STATS_API'
                where l.code='MLB' order by t.abbreviation,em.created_at''')
            ratings = rows('''select distinct on (team_id) id::text id,team_id::text team_id,method,version,evidence_cutoff,
                sample_size,observed_at,available_as_of,source,source_mode,payload_checksum
                from team_rating_observations where team_id=any(cast(:team_ids as uuid[]))
                and available_as_of<=:captured and observed_at>=:safe_start
                order by team_id,available_as_of desc,id''', team_ids=team_ids, captured=captured, safe_start=SAFE_CURRENT_START)
            snapshot = {'schemaVersion': 'AISP_MLB_READ_ONLY_PREGAME_SNAPSHOT_V2',
                'captureMode': 'CURRENT_GAME_ONLY_READ_ONLY_REPEATABLE_READ_NO_PROVIDER', 'capturedAt': captured,
                'game': game, 'sides': sides, 'weather': weather[0] if weather else None,
                'outcomesRead': False, 'marketDataRead': False, 'providerCalls': 0, 'aispRowsModified': 0,
                'priorGameLineupReuse': False, 'gameState': state,
                'currentRoster': current_roster, 'teamIdentityCrosswalk': team_crosswalk,
                'rosterRefreshOwner': roster_refresh_owner,
                'rosterSelection': 'LATEST_PROVIDER_TEAM_ROSTER_RETRIEVAL_NOT_LATEST_ACTIVE_ROW_PER_PLAYER',
                'supersededRosterObservations': superseded_roster}
            snapshot = json.loads(encode(snapshot))
            snapshot['contentSha256'] = hashlib.sha256(encode(snapshot)).hexdigest()
            snapshots.append(snapshot)
            output.append({'game': game, 'sides': sides, 'currentParticipantGateReasons': reasons,
                'currentParticipantsAvailable': not reasons, 'weather': weather, 'gameState': state,
                'currentGameFeatureSnapshot': feature_snapshots, 'componentFeatureOutputs': components,
                'bullpenObservations': bullpen, 'currentPlayerEvidenceMetadata': player_meta,
                'currentRosterEvidenceMetadata': roster, 'currentTeamRatingMetadata': ratings,
                'currentRoster': current_roster, 'teamIdentityCrosswalk': team_crosswalk,
                'rosterRefreshOwner': roster_refresh_owner,
                'existingForecastMetadata': forecasts, 'snapshotContentSha256': snapshot['contentSha256']})
            print(json.dumps({'event': 'GAME_CURRENT_INPUTS_CAPTURED', 'gameId': game_id,
                'teams': [t['abbreviation'] for t in teams], 'start': str(game['starts_at']),
                'participantReasons': reasons, 'featureCompleteness': feature_snapshots[0]['feature_completeness'] if feature_snapshots else None,
                'bullpenRows': len(bullpen)}, sort_keys=True), flush=True)
        source_runs = rows('''select id::text id,source,job_name,status,started_at,completed_at,raw_reference,schema_version
            from ingestion_runs where id=any(cast(:ids as uuid[])) and started_at>=:safe_start''',
            ids=sorted(all_ingestion_ids), safe_start=SAFE_CURRENT_START) if all_ingestion_ids else []
        transaction.rollback()
    engine.dispose()
    result = {'schemaVersion': 'MLB_V18_CURRENT_SLATE_INPUT_INVENTORY_V1', 'capturedAtUtc': captured,
        'database': {'host': url.host, 'port': url.port, 'database': url.database, 'transactionReadOnlyVerified': read_only},
        'slateDateEastern': str(slate_date) if slate_date else None, 'scheduledGameCount': len(schedule) if slate_date else None,
        'currentParticipantCompleteGameCount': sum(r['currentParticipantsAvailable'] for r in output),
        'games': output, 'sourceIngestionRuns': source_runs, 'rosterRefreshOwner': roster_refresh_owner,
        'reasonCounts': dict(Counter(reason for r in output for reason in r['currentParticipantGateReasons'])),
        'queryReceipts': queries, 'sourceSnapshotContract': 'CURRENT_GAME_ONLY_NO_HISTORICAL_LINEUP_REUSE',
        'scope': 'PERSISTED_CURRENT_INPUT_EVIDENCE_NOT_FROZEN_V18_FEATURE_COMPATIBILITY_ATTESTATION',
        'activity': {'aispRowsModified': 0, 'modelFits': 0, 'modelExecutions': 0, 'providerCalls': 0,
                     'finalOotPayloadBytesRead': 0, 'outcomesRead': False, 'marketsRead': False},
        'limitations': ['Current Gen1 feature snapshots are not automatically V18 raw246/treated273 inputs.',
            'Player/roster/rating metadata query is bounded to observations since August 28; it does not claim all historical evidence is absent.',
            'No underlying provider/raw payload was opened; raw_reference paths are reported as provenance only.',
            'Current capture timestamps do not replace original observed/available/evidence-cutoff times.']}
    raw = encode(result)
    digest = hashlib.sha256(raw).hexdigest()
    directory = (output_root or ROOT / 'outputs/mlb-v18-current-slate-v1/inventory') / 'sha256' / digest
    directory.mkdir(parents=True, exist_ok=False)
    with (directory / 'current-slate-input-inventory.json').open('xb') as handle:
        handle.write(raw)
    snapshot_raw = encode({'schemaVersion': 'MLB_CURRENT_GAME_SNAPSHOT_COLLECTION_V1', 'capturedAt': captured, 'snapshots': snapshots})
    with (directory / 'current-game-pregame-snapshots.json').open('xb') as handle:
        handle.write(snapshot_raw)
    references = {'inventoryPath': str(directory / 'current-slate-input-inventory.json'), 'sha256': digest,
        'snapshotsPath': str(directory / 'current-game-pregame-snapshots.json'),
        'snapshotsSha256': hashlib.sha256(snapshot_raw).hexdigest(), 'games': len(output),
        'participantsComplete': result['currentParticipantCompleteGameCount']}
    return json.loads(raw), references


if __name__ == '__main__':
    _, references = capture_current_slate()
    print(json.dumps(references, sort_keys=True), flush=True)
