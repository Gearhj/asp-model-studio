"""One separate free future-schedule capture; never read outcome columns."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request,urlopen

import pandas as pd
import pyarrow.parquet as pq

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import reference,json_bytes,verified_bytes
from server.sports_nba_gen1.current_history_source import _team,TEAM_IDENTITIES

OUT=ROOT/'outputs/nba-gen1-long-gap-v1'
URL='https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_schedules/nba_schedule_2027.parquet'
SIZE=86466
SHA='d4ffe0d974dbec227af1ea5d731e0f36426839a170bfd0bbffc39b65f933a090'
COLUMNS=['id','game_id','date','game_date','game_date_time','season','season_type','type_id','type_abbreviation',
         'neutral_site','status_type_name','status_type_state','status_type_completed',
         'home_id','home_abbreviation','home_display_name','away_id','away_abbreviation','away_display_name']


def now():return datetime.now(timezone.utc).isoformat()


def main():
    receipt_path=OUT/'future-schedule-capture.json'
    if receipt_path.exists():
        old=json.loads(receipt_path.read_bytes());verified_bytes(old['source']);verified_bytes(old['metadata'])
        print(json.dumps({'status':'REUSED_NO_NETWORK','receipt':reference(receipt_path),'selectedTarget':old['selectedTarget']},indent=2));return
    admission=OUT/'source-review/admission.json'
    old=json.loads(admission.read_text(encoding='utf-8-sig'))
    assert old['license']=='CC-BY-4.0' and old['status']=='ADMITTED_FOR_METADATA_FIRST_CATEGORY_A_RESEARCH'
    prior=OUT/'source-review/future-schedule-candidate.json'
    candidate=json.loads(prior.read_bytes())
    assert candidate['asset']['size']==SIZE and candidate['asset']['digest']=='sha256:'+SHA
    addendum=OUT/'source-review/future-intake-addendum.json'
    assert not addendum.exists(),'Separate future GET already declared; no allowance reset or automatic retry.'
    declaration={'schema':'nba-gen1-future-schedule-intake-addendum-v1','createdAtUtc':now(),
        'reason':'Complete the user-authorized conditional genuine future research forecast using current history and an eligible future schedule.',
        'originalDeclaration':reference(OUT/'declaration.json'),'sourceAdmission':reference(admission),
        'publishedAssetMetadata':reference(prior),'script':reference(Path(__file__)),
        'license':'Existing SportsDataverse/hoopR data CC BY4.0 admission; no new source-rights assumption',
        'newAllowance':{'logicalDatasetGets':1,'maximumBytes':100000,'knownCostUsd':0},
        'old2026Allowance':{'usedLogicalGets':1,'usedBytes':525802,'unchanged':True},
        'selectionRule':'Earliest season-end2027 NBA regular-season STD game with status pre, completed=false, nonneutral, two explicitly mappedNBAteams, and scheduledUTCtipoff after actual capture; break same-time ties by stable ESPNgameID.',
        'outcomeColumnsPermitted':[],'forecastsOrModelPerformancePermitted':False,
        'historicalPublicationClockInvented':False,'accountsOrTrials':0,'sportsbookCredits':0}
    addendum.write_bytes(json_bytes(declaration))
    started=now()
    with urlopen(Request(URL,headers={'User-Agent':'ASP-Model-Studio-NBA-Research/1.0'}),timeout=45) as response:
        status=response.status
        headers={k:v for k,v in response.headers.items() if k.lower() in {'content-length','content-type','etag','last-modified','date'}}
        raw=response.read(100001)
    captured=now();actual_sha=hashlib.sha256(raw).hexdigest()
    source=OUT/'source/sha256'/actual_sha/'nba_schedule_2027.parquet'
    source.parent.mkdir(parents=True,exist_ok=True)
    source.write_bytes(raw)
    assert status==200 and len(raw)==SIZE and actual_sha==SHA,'Future export changed: preserve response, no further GET or outcome access.'
    schema=pq.read_schema(source)
    missing=set(COLUMNS)-set(schema.names)
    assert not missing,f'Required future schedule metadata absent: {sorted(missing)}'
    table=pq.read_table(source,columns=COLUMNS)
    metadata_path=OUT/'future-schedule-metadata.parquet';pq.write_table(table,metadata_path)
    frame=table.to_pandas()
    assert not frame.id.duplicated().any() and (frame.id==frame.game_id).all()
    eligible=[];dispositions={}
    for row in frame.to_dict('records'):
        reason=None
        if int(row['season'])!=2027:reason='OUTSIDE_2027_SEASON'
        elif int(row['season_type'])!=2 or int(row['type_id'])!=1 or row['type_abbreviation']!='STD':reason='NOT_REGULAR_STD'
        elif row['neutral_site']:reason='NEUTRAL'
        elif row['status_type_state']!='pre' or bool(row['status_type_completed']):reason='NOT_UNSTARTED'
        elif int(row['home_id']) not in TEAM_IDENTITIES or int(row['away_id']) not in TEAM_IDENTITIES:reason='UNMAPPED_TEAM'
        if reason:
            dispositions[reason]=dispositions.get(reason,0)+1;continue
        home,away=_team(row,'home'),_team(row,'away')
        stamp=pd.to_datetime(row['date'],utc=True)
        if stamp<=pd.to_datetime(captured,utc=True):
            dispositions['EXPIRED']=dispositions.get('EXPIRED',0)+1;continue
        game_day=str(row['game_date'])
        assert stamp.tz_convert('America/New_York').date().isoformat()==game_day
        assert home!=away
        eligible.append({'game_id':f"nba-espn:game:{int(row['id'])}",'source_game_id':int(row['id']),
            'season_end':2027,'game_date':game_day,'scheduled_tipoff_utc':stamp.isoformat(),
            'home_team_id':f'nba-neil:franchise:{home}','away_team_id':f'nba-neil:franchise:{away}',
            'home_team_code':home,'away_team_code':away,'neutral_site':False,'orientation':'SOURCE_HOME_AWAY',
            'home_source_id':int(row['home_id']),'away_source_id':int(row['away_id']),
            'home_display_name':row['home_display_name'],'away_display_name':row['away_display_name'],
            'source_status_name':row['status_type_name'],'source_status_state':'pre','source_completed':False})
    eligible.sort(key=lambda x:(x['scheduled_tipoff_utc'],x['source_game_id']))
    receipt={'schema':'nba-gen1-genuine-future-schedule-capture-v1','createdAtUtc':now(),
        'downloadStartedAtUtc':started,'capturedAtUtc':captured,'sourceCutoffUtc':captured,
        'addendum':reference(addendum),'source':reference(source),'metadata':reference(metadata_path),
        'httpStatus':status,'responseHeaders':headers,'sourceRows':len(frame),'eligibleFutureGames':len(eligible),
        'dispositions':dispositions,'selectedTarget':eligible[0] if eligible else None,
        'selectionRule':declaration['selectionRule'],'metadataColumns':COLUMNS,
        'dataUse':'Genuine future schedule captured before target cutoff; no prediction or outcome interpretation performed by capture.',
        'outcomeColumnsRead':[],'newLogicalDatasetGets':1,'newSourceBytes':SIZE,'newCostUsd':0,
        'cumulativeNbaCorpusGets':4,'cumulativeNbaCorpusBytes':34273400,'priorAllowancesReset':False,
        'futureForecastPublished':False}
    if eligible:
        chosen=eligible[0]
        target={key:chosen[key] for key in ['game_id','source_game_id','season_end','game_date',
            'home_team_id','away_team_id','home_team_code','away_team_code','neutral_site','scheduled_tipoff_utc']}
        target.update({'season_type':'REGULAR','status':'SCHEDULED',
            'source_revision':'github-asset:552084615:sha256:'+SHA})
        evidence={'schema':'NBA_GEN1_REDUCED_SCHEDULE_EVIDENCE_V1','dataClassification':'REAL_UNSCRAMBLED_GAMES',
            'reviewedBy':'Codex NBA source review (/root/nba_recent_source)',
            'capturedAtUtc':captured,'sourceObject':reference(source),
            'rightsEvidence':[reference(admission),reference(OUT/'source-review/hoopr-LICENSE.md')],
            'target':target,'selectionRule':declaration['selectionRule'],
            'metadataProjection':reference(metadata_path),'intakeAddendum':reference(addendum),
            'sourceRevisionIsHistoricalPublicationClock':False}
        evidence_path=OUT/'future-schedule-evidence.json'
        evidence_path.write_bytes(json_bytes(evidence))
        receipt['forecastScheduleEvidence']=reference(evidence_path)
    receipt_path.write_bytes(json_bytes(receipt))
    print(json.dumps({'receipt':reference(receipt_path),'sourceRows':len(frame),'eligible':len(eligible),
        'dispositions':dispositions,'selectedTarget':receipt['selectedTarget']},indent=2))


if __name__=='__main__':main()
