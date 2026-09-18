"""Offline admission from retained, hash-bound CFBD schedule/stat receipts.

No HTTP client, credential reader, fitting or target-result assessment.
"""
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .current import cfbd_2026_games
from .identities import build_aliases, resolve
from .pipeline import FEATURE_COLUMNS, build_features
from .publication_io import canonical_bytes, digest, reference, verified_bytes
from .lifecycle import atomic_json, immutable, now, object_json, owner_lock, read_ref, utc

ADMISSION_RULE='CFB_ADMISSION_V1_TARGET_CONTENT_REUSE'


def parquet(root,name,frame):
    out=io.BytesIO(); frame.to_parquet(out,index=False)
    raw=out.getvalue()
    return immutable(Path(root)/'objects/sha256'/digest(raw)/name,raw)


def data_requests(manifest):
    return [x for x in manifest['requests'] if x['endpoint'] in ('/games','/teams/fbs','/games/teams')]


def read_capture_rows(manifest, season):
    requests=data_requests(manifest)
    schedules=[x for x in requests if x['endpoint']=='/games']
    schools=[x for x in requests if x['endpoint']=='/teams/fbs']
    if len(schedules)!=1 or len(schools)!=1:
        raise ValueError('Exactly one governed season schedule and school list required')
    for item in requests:
        if item['httpStatus']!=200 or item['parameters'].get('year')!=season or utc(item['acquiredAt'])>utc(now()):
            raise ValueError('Capture season/status/clock invalid')
        verified_bytes(item)
    schedule=json.loads(verified_bytes(schedules[0]))
    teams=json.loads(verified_bytes(schools[0]))
    stats=[]; seen=set()
    for item in requests:
        if item['endpoint']=='/games/teams':
            if item['parameters'].get('seasonType')!='regular':
                raise ValueError('Mixed season types')
            rows=json.loads(verified_bytes(item))
            for game in rows:
                for team in game.get('teams',[]):
                    key=(int(game['id']),int(team['teamId']))
                    if key in seen:
                        raise ValueError('Duplicate team-game stat identity')
                    seen.add(key)
            stats.extend(rows)
    ids={int(x['id']) for x in schedule}
    if len(ids)!=len(schedule) or any(int(x['id']) not in ids for x in stats):
        raise ValueError('Duplicate schedule or orphan statistics')
    by_id={int(x['id']):x for x in schedule}
    for game in schedule:
        if int(game['season'])!=season or int(game['homeId'])<=0 or int(game['awayId'])<=0 or int(game['homeId'])==int(game['awayId']):
            raise ValueError('Schedule season or oriented school identity invalid')
        utc(game['startDate'])
    for game in stats:
        expected={int(by_id[int(game['id'])]['homeId']),int(by_id[int(game['id'])]['awayId'])}
        if len(game.get('teams',[]))!=2 or {int(t['teamId']) for t in game['teams']}!=expected:
            raise ValueError('Orphan or incomplete oriented team-game statistics')
    return requests,schedules[0],schools[0],schedule,teams,stats


def admit(*, manifest_ref, release, registry_root, season=2026, precommit=None):
    root=Path(registry_root)
    with owner_lock(root/'admission.lock'):
        manifest=read_ref(manifest_ref)
        requests,schedule_request,school_request,schedule,teams,stats=read_capture_rows(manifest,season)
        cutoff=max((x['acquiredAt'] for x in requests),key=utc)
        schedule_clock=schedule_request['acquiredAt']
        # Only completed records captured before this cutoff may update state.
        final_ids={int(x['id']) for x in schedule if x.get('completed')}
        if any(int(x['id']) not in final_ids for x in stats):
            raise ValueError('Non-final game statistics supplied as pregame evidence')
        current_all=cfbd_2026_games(schedule,stats)
        current=current_all[(current_all.home_is_fbs|current_all.away_is_fbs)&current_all.season_type.eq(2)].copy()
        if not current.loc[current.is_final,'context_eligible'].all():
            raise ValueError('Final lacks valid scores/identity')
        finals=current[current.context_eligible]
        if any(finals.scheduled_at>=pd.Timestamp(cutoff)):
            raise ValueError('Future-dated final')
        if not (finals.both_box_rows & finals[['home_total_yards','away_total_yards','home_turnovers','away_turnovers']].notna().all(axis=1)).all():
            raise ValueError('Missing completed-game team yards/turnovers')
        scores=finals[['home_score','away_score']].to_numpy(float)
        if not np.isfinite(scores).all() or (scores<0).any() or (scores!=np.floor(scores)).any() or (finals.home_score==finals.away_score).any():
            raise ValueError('Invalid/tied final score')
        unresolved=current[~current.is_final & (current.scheduled_at<=pd.Timestamp(schedule_clock))]
        if not unresolved.empty:
            raise ValueError('UNRESOLVED_ELAPSED_SCHEDULE:'+','.join(map(str,unresolved.game_id.tolist())))
        history_ref=release['historicalGames']
        # Inspect chronological metadata before historical outcome columns.
        meta=pd.read_parquet(io.BytesIO(verified_bytes(history_ref)),columns=['season','scheduled_at'])
        if not (meta.season<season).all() or not (meta.scheduled_at<pd.Timestamp(cutoff)).all():
            raise ValueError('Frozen historical input contains current/future season')
        history=pd.read_parquet(history_ref['path'])
        combined=pd.concat([history,current],ignore_index=True,sort=False).sort_values(['scheduled_at','game_id'])
        if combined.game_id.duplicated().any():
            raise ValueError('Conflicting historical/current game identity')
        # Existing implementation, no redefinition of rolling statistics or fits.
        features=build_features(combined)
        features=features[features.season.eq(season)].copy()
        aliases=build_aliases(teams,season,school_request['acquiredAt'],schedule_ref_of(school_request))
        aliases_ref=object_json(root/'aliases',aliases,'aliases.json')
        source_games={int(x['id']):x for x in schedule}
        f_by_id=features.set_index('game_id')
        games=[]
        for row in current_all.sort_values(['scheduled_at','game_id']).to_dict('records'):
            gid=int(row['game_id']); original=source_games[gid]
            target={k:row[k] for k in ('game_id','season','week','home_id','away_id','home_team','away_team','neutral_site','conference_competition')}
            target.update(scheduled_at=row['scheduled_at'].isoformat(),status='SCHEDULED' if not row['is_final'] else 'STATUS_FINAL',
                          provider='CFBD',source_revision=schedule_request['physicalSha256'])
            item={'gameId':str(gid),'target':target,'inputBlockers':[]}
            if not row['scope_primary']:
                item['exclusion']='OUTSIDE_FBS_FBS_REGULAR_WEEKS_1_14'
            elif original.get('startTimeTBD') is True:
                item['exclusion']='KICKOFF_TIME_TBD'
            else:
                for side in ('home','away'):
                    try:
                        resolve(aliases,target[side+'_id'],target[side+'_team'],target['scheduled_at'],cutoff)
                    except ValueError as exc:
                        item['inputBlockers'].append(str(exc))
                    team_id=target[side+'_id']
                    prior=history[history.season.eq(season-1)&history.context_eligible&((history.home_id==team_id)|(history.away_id==team_id))]
                    if prior.empty:
                        item['inputBlockers'].append('PRIOR_SEASON_IDENTITY_UNSUPPORTED:'+str(team_id))
                    earlier=finals[(finals.scheduled_at<row['scheduled_at'])&((finals.home_id==team_id)|(finals.away_id==team_id))]
                    if gid in f_by_id.index and int(f_by_id.loc[gid,side+'_current_season_games'])!=len(earlier):
                        item['inputBlockers'].append('HISTORY_FEATURE_COUNT_MISMATCH:'+str(team_id))
            if gid in f_by_id.index:
                values=f_by_id.loc[gid,FEATURE_COLUMNS+['elo_home_win_probability']]
                item['predictionInputIdentity']=digest({k:None if pd.isna(v) else float(v) for k,v in values.items()})
            games.append(item)
        feature_ref=parquet(root,'features.parquet',features)
        schedule_ref=parquet(root,'schedule.parquet',current_all)
        old=read_ref(reference(root/'current.json'))['inputManifest'] if (root/'current.json').exists() else None
        if old:
            prior=read_ref(old)
            if utc(cutoff)<utc(prior['sourceCutoffUtc']):
                raise ValueError('Capture clock regression')
            if prior['sourceManifest']['sha256']==manifest_ref['sha256'] and prior.get('admissionRule')==ADMISSION_RULE:
                return old
        bundle={'schema':'CFB_GEN1_SLATE_INPUT_V1','classification':'REAL_GOVERNED_CFBD_INPUTS','admissionRule':ADMISSION_RULE,
            'admittedAtUtc':now(),'predecessor':old,'sourceManifest':manifest_ref,'sourceCutoffUtc':cutoff,
            'scheduleCapturedAtUtc':schedule_clock,'historyCompleteThroughUtc':schedule_clock,
            'historicalGames':history_ref,'features':feature_ref,'schedule':schedule_ref,'aliases':aliases_ref,
            'modelBindings':release['modelBindings'],'season':season,'games':games,'historyMissingGameIds':[],
            'predictionInputIdentity':digest({'features':feature_ref['sha256'],'schedule':schedule_ref['sha256'],
                'modelBindings':release['modelBindings'],'aliases':aliases_ref['sha256']}),
            'sourceLimitations':['No explicit cancellation/postponement/replacement status in retained CFBD schema.',
                'Acquisition timestamps certify availability; no original historical publication vintages.',
                'Per-record final availability not provided; only source-completed records captured before cutoff update future features.'],
            'modelFits':0,'providerCalls':0}
        bound=object_json(root/'versions',bundle,'input.json')
        validate_bundle(bundle,release)
        if precommit: precommit(bundle)
        atomic_json(root/'current.json',{'schema':'CFB_GEN1_SLATE_INPUT_POINTER_V1','inputManifest':bound})
        return bound


def schedule_ref_of(item):
    return {'path':item['path'],'sha256':item['physicalSha256'],'bytes':item['bytes']}


def validate_bundle(bundle,release):
    if bundle['schema']!='CFB_GEN1_SLATE_INPUT_V1' or bundle['classification']!='REAL_GOVERNED_CFBD_INPUTS':
        raise ValueError('Wrong sport or fixture input')
    if bundle['modelBindings']!=release['modelBindings'] or bundle['historicalGames']!=release['historicalGames']:
        raise ValueError('Frozen baseline binding changed')
    for ref in [bundle['sourceManifest'],bundle['features'],bundle['schedule'],bundle['aliases'],bundle['historicalGames'],*bundle['modelBindings'].values()]:
        verified_bytes(ref)
    manifest=read_ref(bundle['sourceManifest'])
    req=data_requests(manifest)
    if max((x['acquiredAt'] for x in req),key=utc)!=bundle['sourceCutoffUtc'] or next(x['acquiredAt'] for x in req if x['endpoint']=='/games')!=bundle['scheduleCapturedAtUtc'] or bundle['historyCompleteThroughUtc']!=bundle['scheduleCapturedAtUtc']:
        raise ValueError('Source clock binding mismatch')
    for x in req: verified_bytes(x)
    schedule=pd.read_parquet(bundle['schedule']['path'],columns=['game_id','scheduled_at','home_id','away_id','home_team','away_team','is_final'])
    if schedule.game_id.duplicated().any() or len(schedule)!=len(bundle['games']):
        raise ValueError('Schedule grain mismatch')
    by=schedule.set_index('game_id')
    for item in bundle['games']:
        t=item['target']; r=by.loc[int(t['game_id'])]
        if any(t[k]!=r[k] for k in ('home_id','away_id','home_team','away_team')) or utc(t['scheduled_at'])!=r['scheduled_at'].to_pydatetime():
            raise ValueError('Schedule orientation/clock drift')
        if (t['status']=='STATUS_FINAL')!=bool(r.is_final):
            raise ValueError('Schedule status drift')
