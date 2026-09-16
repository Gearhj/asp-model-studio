"""One bounded, free, licensed source download and identity-only coverage scan."""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_nba_gen1.authority import json_bytes, reference, verified_bytes

OUT = ROOT/'outputs/nba-gen1-historical-pilot-v1'
URL = 'https://raw.githubusercontent.com/fivethirtyeight/data/6d880e939ad3d11d94c137c911681b3cf718fd74/nba-elo/nbaallelo.csv'
SIZE = 18173265
GIT_BLOB = '6d6ccd07151aed322e1a77c57ea83b8ea58c5523'
METADATA_COLUMNS = ['gameorder','game_id','lg_id','_iscopy','year_id','date_game','is_playoffs',
                    'team_id','fran_id','opp_id','opp_fran','game_location']


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    pointer = OUT/'acquisition.json'
    if pointer.exists():
        receipt = json.loads(pointer.read_bytes())
        verified_bytes(receipt['original'])
        verified_bytes(receipt['metadata'])
        print(json.dumps({'status':'REUSED_ORIGINAL_BYTES','receipt':reference(pointer)},indent=2))
        return
    started = datetime.now(timezone.utc).isoformat()
    request = Request(URL, headers={'User-Agent':'ASP-Model-Studio-NBA-Research/1.0'})
    with urlopen(request, timeout=90) as response:
        headers = dict(response.headers.items())
        raw = response.read(SIZE+1)
    assert len(raw) == SIZE, 'Unexpected source size; no retries or extra requests'
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == GIT_BLOB
    acquired = datetime.now(timezone.utc).isoformat()
    sha = hashlib.sha256(raw).hexdigest()
    path = OUT/'source/sha256'/sha/'nbaallelo.csv'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(raw)
    # The source bytes are retained; only identity/date/scope columns enter this scan.
    metadata = pd.read_csv(io.BytesIO(raw), usecols=METADATA_COLUMNS, dtype={'game_id':str})
    meta_path = OUT/'identity-metadata.parquet'
    metadata.to_parquet(meta_path,index=False)
    nba = metadata[(metadata.lg_id == 'NBA') & (metadata.is_playoffs == 0)]
    coverage = []
    for season, group in nba.groupby('year_id',sort=True):
        dates = pd.to_datetime(group.date_game, format='%m/%d/%Y', errors='raise')
        coverage.append({'seasonEndYear':int(season),'sourceRows':len(group),'distinctGames':group.game_id.nunique(),
            'firstGameDate':dates.min().date().isoformat(),'lastRegularGameDate':dates.max().date().isoformat(),
            'sourceTeamCodes':int(pd.concat([group.team_id,group.opp_id]).nunique()),
            'locations':group.game_location.value_counts().to_dict()})
    receipt = {'schemaVersion':'NBA_GEN1_FTE_HISTORICAL_ACQUISITION_V1',
        'sourceClassification':'A_HISTORICAL_FINALIZED_RECORD_RECONSTRUCTION',
        'downloadStartedAtUtc':started,'acquiredAtUtc':acquired,'url':URL,
        'publisher':'FiveThirtyEight','dataLicense':'CC-BY-4.0','upstreamGameProvenance':'Basketball-Reference, as disclosed by publisher',
        'sourceCommit':'6d880e939ad3d11d94c137c911681b3cf718fd74','gitBlobSha1':GIT_BLOB,
        'sourceCommitIsNotRowAvailability':True,'httpHeaders':headers,
        'original':reference(path),'metadata':reference(meta_path),'metadataColumns':METADATA_COLUMNS,
        'outcomeColumnsLoadedForAnalysis':False,'performanceExamined':False,'coverage':coverage,
        'dataRequests':1,'sourceBytes':len(raw),'requestLimit':1,'maximumBytes':SIZE,
        'costUsd':0,'accountsCreated':0,'sportsbookCreditsUsed':0,'providerKeyUsed':False,
        'historicalTipoffTimes':None,'historicalPublicationTimes':None,'originalRevisionVintages':None,
        'restrictions':'Attribute FiveThirtyEight and original source, link CC-BY4, indicate transformations, no endorsement. This is not verified-at-the-time or prospective evidence.'}
    pointer.write_bytes(json_bytes(receipt))
    print(json.dumps({'receipt':reference(pointer),'original':receipt['original'],'latestCoverage':coverage[-8:]},indent=2))


if __name__ == '__main__':
    main()
