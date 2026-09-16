"""One bounded postgame-label read for frozen Sep12 pitchers; no rescoring."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask, LEDGER
from server.sports_silver.canonical_ids import canonical_game_id
from server.sports_current_statcast.mlb_starter_duration_paired_scoring import (
    STARTER_FINAL_QUERY, FINAL_METADATA_QUERY, MINIMUM_PILOT_START,
    _starter_final_evidence, _final_metadata_ready, _serialized, _utc,
)

OUT=ROOT/'outputs/mlb-v18-september12-miss-analysis-v1/exposure'
DECLARATION=ROOT/'outputs/mlb-v18-position-and-survival-verification-v1/slate-assessment-declaration.json'
FINALS=ROOT/'outputs/mlb-v18-september12-miss-analysis-v1/governed-finals.json'

# Same narrow existing projection; source/actual-starter and retrospective gates
# are applied in SQL before exposure labels are returned, then rechecked by the
# unchanged validator. No other player, game, source acquisition or final score.
SQL=STARTER_FINAL_QUERY.replace('where h.latest_rank=1', '''where h.latest_rank=1
 and h.final_outcome_id::text=:final_outcome_id
 and h.started=true and h."values"->>'actual_starting_pitcher'='true'
 and h."values"->>'starter_provenance' is not null
 and h.source_mode::text='LIVE' and s.source_mode::text='LIVE'
 and s.source_classification::text='OFFICIAL_PRIMARY'
 and s.evaluation_eligible=true and s.quality_tier::text<>'EXCLUDED'
 and c.status::text='SUCCEEDED' and c.source_mode::text='LIVE'
 and c.temporal_semantics::text='RETROSPECTIVE_RECONSTRUCTION'
 and c.source_version_id=h.source_version_id
 and c.requested_at<=c.completed_at and c.completed_at<=:query_started_at
 and h.evidence_end_at>=:declared_start and h.evidence_end_at<=:query_started_at''')


def ref(path):
    p=Path(path).resolve();b=p.read_bytes()
    return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}


def verified(r):
    assert ref(r['path'])==r
    return json.loads(Path(r['path']).read_bytes())


def write(name,value):
    p=OUT/name
    with p.open('x',encoding='utf-8')as f:json.dump(value,f,indent=2,default=str,allow_nan=False);f.write('\n')
    return ref(p)


def main(successor=False,final_followup=False):
    suffix='-v3' if final_followup else '-v2' if successor else ''
    finals_path=ROOT/'outputs/mlb-v18-september12-miss-analysis-v1/final-revision-followup/governed-finals.json' if final_followup else FINALS
    finals_sha='88f69738238572e107578e18c17e09ec5b614295b0be5e8b0e2f9bd14293685c' if final_followup else '9ac89f5f0585d011dca71cd9ef544d8c1bc1e26c79501cab2eefe99ea1528d9f'
    target=OUT/('starter-evidence-supplement'+suffix+'.json')
    if target.exists():
        print(json.dumps({'status':'EXISTING_CAPTURE_REUSED_NO_NEW_READ','result':ref(target)},indent=2));return
    d=json.loads(DECLARATION.read_text());assert len(d['games'])==15
    for r in d['games']:
        assert all(final_oot_eligible_key_mask([r['gameId'],r['sourceGameId'],canonical_game_id(int(r['sourceGameId']))]))
    assert ref(finals_path)['sha256']==finals_sha
    finals=json.loads(finals_path.read_text());fmap={r['gameId']:r for r in finals['records']}
    expected=[]
    for r in d['games']:
        snap=verified(r['pregameEvidence']);g=snap['game'];assert g['game_id']==r['gameId']
        assert str(g['source_game_id'])==r['sourceGameId'] and _utc(g['starts_at'])==_utc(r['scheduledStartUtc'])
        sides={}
        for s in snap['sides']:
            label=s['side'];starter=s['starter'];team=s['team'];declared=r['starters'][label]
            assert starter['uuid']==declared['uuid'] and str(starter['mlbamId'])==str(declared['mlbamId'])
            assert team['uuid']==r['teams'][label]['uuid']
            mappings={str(t['mlbam_id']) for t in snap['teamIdentityCrosswalk'] if t['team_id']==team['uuid']}
            assert len(mappings)==1
            sides[label]={'playerId':starter['uuid'],'teamId':team['uuid'],'mlbamId':str(starter['mlbamId']),
                          'sourceTeamId':next(iter(mappings)),'sourceGameId':r['sourceGameId']}
        assert set(sides)=={'HOME','AWAY'}
        expected.append({'gameId':r['gameId'],'sourceGameId':r['sourceGameId'],'scheduledStartUtc':r['scheduledStartUtc'],
                         'inputReference':r['pregameEvidence'],'sides':sides,
                         'basis':'Original frozen pregame expected starters only; actual-start attribution must come from explicit official postgame fields.',
                         'finalMetadata':{k:fmap.get(r['gameId'],{}).get(k)for k in ['status','sourceOutcomeId','sourceRevision','sourceCreatedAt','finalAt']}})
    now=datetime.now(timezone.utc)
    gate=write('starter-evidence-identity-gate'+suffix+'.json',{'atUtc':now.isoformat(),'declaration':ref(DECLARATION),'finals':ref(finals_path),
         'quarantine':ref(LEDGER),'expected':expected,'outcomeLabelsRead':False,'inferredActualStarters':False,
         'descriptorResolution':'Use the authenticated ordinary-forecast pregameEvidence descriptor directly with the same expected identity shape. No synthetic duration-pair input or mutation of old pair namespace.',
         'baseQuerySha256':hashlib.sha256(STARTER_FINAL_QUERY.encode()).hexdigest(),'query':SQL,'querySha256':hashlib.sha256(SQL.encode()).hexdigest()})
    from sqlalchemy import create_engine,text
    from sqlalchemy.engine import make_url
    from dotenv import dotenv_values
    url=make_url(dotenv_values('C:/Users/james/ai-sports-predictor/.env')['DATABASE_URL'].replace('postgresql+psycopg://','postgresql+psycopg2://'))
    assert url.get_backend_name()=='postgresql' and url.host in ('localhost','127.0.0.1','::1')
    engine=create_engine(url);rows=[];metadata_queries=starter_queries=0;failed=False
    try:
        with engine.connect() as c:
            tx=c.begin()
            try:
                c.exec_driver_sql('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                assert c.exec_driver_sql('SHOW transaction_read_only').scalar()=='on'
                for e in expected:
                    final=fmap.get(e['gameId'],{});result={'gameId':e['gameId'],'sourceGameId':e['sourceGameId'],'status':'WITHHELD_WITHOUT_GOVERNED_FINAL','recordsReturned':0}
                    if final.get('status')!='FINAL':rows.append(result);continue
                    if failed:result['status']='NOT_ATTEMPTED_AFTER_FIRST_QUERY_FAILURE';rows.append(result);continue
                    params={'game_id':e['gameId'],'declared_start':_utc(e['scheduledStartUtc']),'minimum_start':MINIMUM_PILOT_START,'query_started_at':now,
                            'home_player_id':e['sides']['HOME']['playerId'],'away_player_id':e['sides']['AWAY']['playerId'],'final_outcome_id':final['sourceOutcomeId']}
                    try:
                        meta=c.execute(text(FINAL_METADATA_QUERY),params).mappings().one_or_none();metadata_queries+=1
                        okay,reason=_final_metadata_ready(meta,queried_at=now)if meta is not None else(False,'GAME_OR_START_IDENTITY_NOT_MATCHED')
                        identity_match=False
                        if meta is not None:
                            raw_id,raw_revision=meta['outcome_id'],meta['revision']
                            metadata_values={k:_serialized(v) for k,v in meta.items()}
                            result['currentFinalMetadata']=metadata_values
                            result['expectedFinalMetadata']={k:final[k]for k in ['sourceOutcomeId','sourceRevision','sourceCreatedAt','finalAt']}
                            result['comparison']={'returnedOutcomeIdType':type(raw_id).__name__,'returnedRevisionType':type(raw_revision).__name__,
                                'expectedOutcomeIdType':type(final['sourceOutcomeId']).__name__,'expectedRevisionType':type(final['sourceRevision']).__name__,
                                'originalOutcomeIdEquality':str(raw_id)==final['sourceOutcomeId'],'originalRevisionEquality':raw_revision==final['sourceRevision']}
                            if raw_id is not None and raw_revision is not None:
                                normalized_id=str(UUID(raw_id.decode('utf-8')if isinstance(raw_id,bytes)else str(raw_id)))
                                assert not isinstance(raw_revision,bool)
                                revision_text=raw_revision.decode('utf-8')if isinstance(raw_revision,bytes)else str(raw_revision)
                                assert revision_text.isdigit()
                                normalized_revision=int(revision_text)
                                id_equal=normalized_id==str(UUID(final['sourceOutcomeId']))
                                revision_equal=normalized_revision==int(final['sourceRevision'])
                                result['comparison'].update(normalizedReturnedOutcomeId=normalized_id,normalizedReturnedRevision=normalized_revision,
                                                            normalizedOutcomeIdEquality=id_equal,normalizedRevisionEquality=revision_equal)
                                identity_match=id_equal and revision_equal
                        if not okay or not identity_match:
                            result.update(status='WITHHELD_FINAL_METADATA_CHANGED',reason=reason if not okay else 'FINAL_REVISION_CHANGED',outcomeLabelsRead=False);rows.append(result);continue
                        starter_queries+=1
                        records=[dict(v)for v in c.execute(text(SQL),params).mappings()]
                        evidence=_starter_final_evidence(records,e,final,queried_at=now)
                        result.update(status=evidence['status'],recordsReturned=len(records),evidence=evidence,
                                      databaseProjection=[{k:_serialized(v)for k,v in rec.items()}for rec in records],
                                      finalOutcomeId=final['sourceOutcomeId'],finalRevision=final['sourceRevision'])
                    except Exception as exc:
                        diag=getattr(getattr(exc,'orig',None),'diag',None)
                        result.update(status='BOUNDED_QUERY_FAILED',errorType=type(exc).__name__,
                                      diagnostics={k:str(getattr(diag,k))for k in ['sqlstate','column_name','table_name','message_primary']if getattr(diag,k,None)})
                        failed=True
                    rows.append(result)
            finally:tx.rollback()
    finally:engine.dispose()
    summary={'schemaVersion':'MLB_V18_SEPTEMBER12_STARTER_LABEL_SUPPLEMENT_V1','asOfUtc':now.isoformat(),'identityGate':gate,'code':ref(__file__),
             'declaration':ref(DECLARATION),'sameFrozenFinalReceipt':ref(finals_path),'rows':rows,
             'metadataQueriesExecuted':metadata_queries,'starterQueriesExecuted':starter_queries,
             'starterRecordsReturned':sum(r['recordsReturned']for r in rows),
             'supportedGames':sum(r['status']=='SUPPORTED'for r in rows),'withheldWithoutGovernedFinal':sum(r['status']=='WITHHELD_WITHOUT_GOVERNED_FINAL'for r in rows),
             'oneBoundedReadPass':True,'readOnlyTransactionVerified':True,'finalScoreQueries':0,'rescoring':False,'providerCalls':0,'modelFits':0,'simulations':0,'aispWrites':0,
             'interpretation':'Only explicit same-final official retrospective starter records can support actual BF/outs. Zero returned rows means none under this exact identity/provenance query, not zero actual batters or proof no other source contains the labels. A schema/provenance failure is reported without retries or schema-wide search.',
             'nextAction':'Use supported labels only to localize exposure against retained diagnostics; otherwise preserve the exact missing-record/provenance or query failure. Population-wide frozen starterBF/removal distributions remain unretained, so one representative trace is not a baseline exposure distribution.'}
    if successor:
        summary['correctionLineage']={'priorReceipt':ref(OUT/'starter-evidence-supplement.json'),
            'comparisonReview':ref(OUT/'starter-evidence-comparison-review.json'),
            'priorCollectorSnapshot':ref(OUT/'code-snapshots/13c18e284298b08392b02cb1915dcf2bc49189b0e883b0a198a4f0a7cccbe30e/read_mlb_v18_september12_starter_evidence_v1.py'),
            'change':'Retain expected and returned metadata/types and each equality result; normalize valid UUID/integer representations before exact identity comparison. No forecast or outcome revision is substituted.'}
    if final_followup:
        summary['correctionLineage']={'priorReceipt':ref(OUT/'starter-evidence-supplement-v2.json'),
            'priorCollectorSnapshot':ref(OUT/'code-snapshots/3e7e3ebfe7d75056eaaf8586f8e30511acd286e69910263f8dfea0076cd62c89/read_mlb_v18_september12_starter_evidence_v1.py'),
            'change':'Use the owner-authorized latest governed final receipt for all15 members of the unchanged fixed cohort; retain identical actual-starter/source/clock checks. No final score query or rescoring in this pass.'}
    result=write(target.name,summary);print(json.dumps({'result':result,'starterRecordsReturned':summary['starterRecordsReturned'],'supportedGames':summary['supportedGames'],'failed':failed},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--metadata-successor',action='store_true');parser.add_argument('--final-revision-followup',action='store_true');args=parser.parse_args()
    main(args.metadata_successor,args.final_revision_followup)
