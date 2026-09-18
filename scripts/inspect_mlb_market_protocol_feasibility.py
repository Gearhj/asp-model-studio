"""One read-only metadata extraction. No scores, outcomes or provider calls.

Run with AISP's existing Python environment. Outputs are private research
metadata, not a forecast/quote enrollment or an acquisition authorization.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, r'C:\Users\james\ai-sports-predictor\server')
import sqlalchemy as sa
from app.core.config import get_settings

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path, default=Path(
    r'C:\Users\james\asp-model-studio\outputs\mlb-v18-market-prospective-v1\FEASIBILITY_METADATA.json'))
args = parser.parse_args()
path = args.output
if path.exists():
    raise FileExistsError('Retain the original metadata snapshot; choose a new --output path')

settings = get_settings()
engine = sa.create_engine(settings.database_url)
queries = {
 'future_schedule_by_date': """select (g.starts_at at time zone 'America/New_York')::date as event_date,g.source_mode,g.status,count(*) as games,min(g.starts_at) as first_start,max(g.starts_at) as last_start from games g join leagues l on l.id=g.league_id where l.code='MLB' and g.starts_at>=now() group by 1,2,3 order by 1,2,3""",
 'future_games': """select g.id::text as game_id,g.starts_at,g.status,g.source_mode,g.scheduled_innings,g.created_at,s.name as season,ht_t.abbreviation as home_abbreviation,at_t.abbreviation as away_abbreviation from games g join leagues l on l.id=g.league_id left join seasons s on s.id=g.season_id left join game_teams ht on ht.game_id=g.id and ht.is_home left join teams ht_t on ht_t.id=ht.team_id left join game_teams at on at.game_id=g.id and not at.is_home left join teams at_t on at_t.id=at.team_id where l.code='MLB' and g.starts_at>=now() order by g.starts_at,g.id""",
 'quote_timestamp_metadata': """select g.id::text as game_id,g.starts_at,m.id::text as market_id,m.period,mo.participant_team_id::text as team_id,gt.is_home,s.sportsbook_id::text as sportsbook_id,b.name as book,s.observed_at,s.available_as_of,s.status,s.source,s.source_mode,s.source_event_id,s.payload_checksum,(s.american_odds is not null and s.decimal_odds>1) as priced from odds_snapshots s join market_outcomes mo on mo.id=s.market_outcome_id join markets m on m.id=mo.market_id join games g on g.id=m.game_id join leagues l on l.id=g.league_id join sportsbooks b on b.id=s.sportsbook_id left join game_teams gt on gt.game_id=g.id and gt.team_id=mo.participant_team_id where l.code='MLB' and m.market_type='MONEYLINE' and g.starts_at>='2026-09-12T00:00:00Z' and s.observed_at<=now() order by g.starts_at,s.observed_at,s.sportsbook_id,gt.is_home""",
 'forecast_identity_clocks': """select sf.canonical_game_id::text as game_id,sf.forecast_id,sf.engine_id,sf.model_artifact_sha256,sf.feature_vector_sha256,sf.event_date,sf.season,sf.season_type,sf.status,sf.scheduled_start_utc,sf.schedule_as_of_utc,sf.source_cutoff_utc,sf.forecast_cutoff_utc,sf.available_as_of_utc,sf.created_at from shadow_forecasts sf where sf.engine_id='MLB_V18_WHOLE_GAME' and sf.event_date>='2026-09-12' order by sf.scheduled_start_utc,sf.created_at""",
 'schedule_coverage_bounds': """select g.source_mode,count(*) as games,min(g.starts_at) as first_start,max(g.starts_at) as last_start from games g join leagues l on l.id=g.league_id where l.code='MLB' and g.starts_at>='2026-09-18T00:00:00Z' group by 1 order by 1""",
}
out = {'schema':'MLB_V18_MARKET_FEASIBILITY_METADATA_ONLY_V1',
       'observedAtUtc':datetime.now(timezone.utc).isoformat(), 'readOnly':True,
       'outcomeColumnsSelected':[], 'providerCalls':0, 'queries':queries}
with engine.connect() as conn:
    with conn.begin():
        conn.execute(sa.text('SET TRANSACTION READ ONLY'))
        conn.execute(sa.text("SET LOCAL statement_timeout='30s'"))
        for name, sql in queries.items():
            out[name] = [dict(row._mapping) for row in conn.execute(sa.text(sql))]
out['settings'] = {key:getattr(settings,key) for key in (
    'odds_polling_enabled','odds_poll_interval_minutes','odds_checkpoint_collection_enabled',
    'owns_odds_collection','scheduler_core_jobs_enabled','live_shadow_enabled')}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(out,default=str,indent=2),encoding='utf-8')
print(json.dumps({key:len(out[key]) for key in queries}))
print(json.dumps(out['future_schedule_by_date'],default=str))
print(json.dumps(out['settings']))
