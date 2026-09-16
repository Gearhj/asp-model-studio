"""Single pinned licensed archive GET, then metadata-only scope inspection."""
from datetime import datetime, timezone
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_nba_gen1.authority import reference, verified_bytes, json_bytes

OUT=ROOT/'outputs/nba-gen1-recent-v1'
URL='https://raw.githubusercontent.com/Neil-Paine-1/NBA-elo/9a485bacef9f18f6a8e3ec671f13b9609386f0fa/NBA%20Elo%202025%20-%20nba_elo.csv'
SIZE=15487867
BLOB='4752ac88d1d5e62c430914767e4e56d91560a5df'


def main():
    pointer=OUT/'acquisition.json'
    if pointer.exists():
        old=json.loads(pointer.read_bytes())
        verified_bytes(old['original'])
        verified_bytes(old['metadata'])
        print(json.dumps({'status':'REUSE_EXISTING_BYTES_NO_REQUEST','receipt':reference(pointer)},indent=2))
        return
    review=OUT/'source-review.json'
    assert review.is_file(),'Published source terms and exact bounded admission must be reviewed first'
    started=datetime.now(timezone.utc).isoformat()
    with urlopen(Request(URL,headers={'User-Agent':'ASP-Model-Studio-NBA-Internal-Research/1.0'}),timeout=90) as response:
        headers=dict(response.headers.items())
        raw=response.read(SIZE+1)
    assert len(raw)==SIZE,'Unexpected size; no automatic retry or alternative download'
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==BLOB
    acquired=datetime.now(timezone.utc).isoformat()
    sha=hashlib.sha256(raw).hexdigest()
    path=OUT/'source/sha256'/sha/'NBA-Elo-2025-nba-elo.csv'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))
    columns=reader.fieldnames
    assert {'date','season','neutral','playoff','team1','team2','score1','score2'} <= set(columns)
    rows=[]
    for line,row in enumerate(reader,start=2):
        # Final-score presence is an eligibility flag; no numeric score or
        # publisher rating/probability is interpreted in the scope scan.
        rows.append({**{key:row[key] for key in ('date','season','neutral','playoff','team1','team2')},
                     'has_both_scores':bool(row['score1'].strip() and row['score2'].strip()),
                     'source_row_number':line})
    meta=pd.DataFrame(rows)
    meta.season=pd.to_numeric(meta.season,errors='raise').astype(int)
    meta_path=OUT/'identity-metadata.parquet'
    meta.to_parquet(meta_path,index=False)
    coverage=[]
    for season,group in meta.groupby('season'):
        coverage.append({'seasonEnd':int(season),'sourceRows':len(group),
                         'rowsWithBothScores':int(group.has_both_scores.sum()),
                         'firstDate':group.date.min(),'lastDate':group.date.max(),
                         'playoffClassCounts':group.playoff.value_counts(dropna=False).to_dict(),
                         'neutralFlagCounts':group.neutral.value_counts(dropna=False).to_dict(),
                         'sourceTeamCodes':sorted(set(group.team1)|set(group.team2))})
    old=json.loads((ROOT/'outputs/nba-gen1-historical-pilot-v1/acquisition.json').read_bytes())
    receipt={'schemaVersion':'NBA_GEN1_RECENT_NEIL_PAINE_ACQUISITION_V1','sourceReview':reference(review),
             'evidenceClass':'A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION',
             'downloadStartedAtUtc':started,'acquiredAtUtc':acquired,'url':URL,'httpHeaders':headers,
             'sourceRepositoryCommit':'9a485bacef9f18f6a8e3ec671f13b9609386f0fa',
             'fileLastCommit':'37db89481b02cbdf5f7d0bc1e41271ebb11bd283','fileLastCommitAtUtc':'2025-04-14T22:31:06Z',
             'commitClockIsNotGameAvailability':True,'gitBlobSha1':BLOB,
             'original':reference(path),'metadata':reference(meta_path),'sourceColumns':columns,
             'scoreValuesInspected':False,'publisherRatingsUsed':False,'coverage':coverage,
             'datasetRequestsThisAssignment':1,'datasetBytesThisAssignment':len(raw),'maximumCalls':1,'maximumBytes':SIZE,
             'datasetRequestsCumulativeWithPriorPilot':old['dataRequests']+1,
             'datasetBytesCumulativeWithPriorPilot':old['sourceBytes']+len(raw),
             'priorDatasetAllowanceReset':False,'remainingCallsForThisAsset':0,'costUsd':0,'providerCreditsUsed':0,
             'historicalGameAvailabilityTimes':None,'historicalScheduleVintages':None,'perGameRevisionClocks':None}
    pointer.write_bytes(json_bytes(receipt))
    print(json.dumps({'receipt':reference(pointer),'columns':columns,'latestCoverage':coverage[-9:]},indent=2))


if __name__=='__main__':
    main()
