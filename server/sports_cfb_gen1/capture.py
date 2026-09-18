"""Bounded CFBD capture. Zero network without an exact separately bound grant.

Reservations precede HTTP. An interrupted batch is never automatically retried.
Credentials exist only inside the transport and are never serialized or hashed.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
import uuid

from .publication_io import reference,verified_bytes,digest,canonical_bytes
from .lifecycle import atomic_json,immutable,object_json,read_ref,now,utc,owner_lock
from .inputs import read_capture_rows

SAFE_HEADERS={'content-type','content-length','date','etag','last-modified','x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset'}
ONE_TIME_PLAN_SHA='40f4a5dc2130e6ad9135d62fcf92448db04590dc9e66c8be7e65b3b103782415'
ONE_TIME_DEPLOYMENT='7934282ddb839f8fbcde4f63c7e0710cccf07967db26abdb7acca9e1c6fb66b9'


def schema_profile(value):
    def kind(v):
        if v is None:return 'null'
        if isinstance(v,bool):return 'boolean'
        if isinstance(v,int):return 'integer'
        if isinstance(v,float):return 'number'
        if isinstance(v,list):return 'array'
        if isinstance(v,dict):return 'object'
        return 'string'
    if isinstance(value,list):
        rows=[x for x in value if isinstance(x,dict)]
        return {'type':'array','itemTypes':sorted({kind(x) for x in value}),
                'fields':{k:sorted({kind(x[k]) for x in rows if k in x}) for k in sorted({k for x in rows for k in x})}}
    if isinstance(value,dict):return {'type':'object','fields':{k:kind(v) for k,v in sorted(value.items())}}
    return {'type':kind(value)}


def entitlement(document,needed):
    if not isinstance(document,dict):raise ValueError('ENTITLEMENT_SCHEMA_FAILURE')
    remaining,limit=document.get('remainingCalls'),document.get('monthlyLimit')
    if not isinstance(remaining,int) or isinstance(remaining,bool) or not isinstance(limit,int) or isinstance(limit,bool) or limit<=0 or remaining<needed or remaining>limit:
        raise ValueError('INSUFFICIENT_OR_UNKNOWN_FREE_ENTITLEMENT')
    return {'remainingCalls':remaining,'monthlyLimit':limit,'sharedPool':document.get('sharedPool'),
            'resetAt':document.get('resetAt'),'incrementalCostUsd':0}


def validate_grant(plan_ref,grant_ref,deployment,enabled,clock):
    if not enabled or not grant_ref:raise PermissionError('NETWORK_DISABLED_NO_EXACT_GRANT')
    plan=read_ref(plan_ref);grant=read_ref(grant_ref)
    if (grant.get('approvedBy')!='James' or grant.get('liveCaptureAuthorized') is not True
        or grant.get('planSha256')!=plan_ref['sha256'] or grant.get('deploymentId')!=deployment
        or grant.get('validFromUtc')!=plan['validFromUtc'] or grant.get('validUntilUtc')!=plan['validUntilUtc']
        or not utc(plan['validFromUtc'])<=utc(clock)<utc(plan['validUntilUtc'])):
        raise PermissionError('EXACT_VALID_REFRESH_GRANT_REQUIRED')
    if plan['schema']=='CFB_GEN1_REFRESH_AUTHORIZATION_REQUIREMENTS_V1':
        if plan_ref['sha256']!=ONE_TIME_PLAN_SHA or deployment!=ONE_TIME_DEPLOYMENT:
            raise PermissionError('WRONG_ONE_TIME_PROPOSAL_OR_DEPLOYMENT')
    elif plan['schema']!='CFB_GEN1_RECURRING_REFRESH_PLAN_V1':raise PermissionError('UNKNOWN_PLAN_SCHEMA')
    if plan['maxCostUsd']!=0 or plan['retryCount']!=0:raise PermissionError('FREE_ZERO_RETRY_REQUIRED')
    rights=read_ref(plan['rightsEvidence'])
    for ref in rights['evidence']:verified_bytes(ref)
    for field in ('privateResponseRetention','historicalAnalysisAndModelTraining','derivedPredictionPublication'):
        if rights['conclusions'].get(field)!='permitted':raise PermissionError('RETAINED_RIGHTS_FAILURE')
    return plan


class HttpTransport:
    def __init__(self,env_file):
        secret=os.environ.get('CFBD_API_KEY','').strip()
        if not secret:
            # Read only this configured variable; never emit or fingerprint the file.
            for line in Path(env_file).read_text(encoding='utf-8-sig').splitlines():
                key,sep,value=line.strip().partition('=')
                if sep and key.strip()=='CFBD_API_KEY':
                    secret=value.strip().strip('\"\'');break
        if not secret:raise RuntimeError('LOCAL_CFBD_CREDENTIAL_MISSING')
        self._secret=secret

    def __call__(self,asset,headers,limit,meter):
        url=asset['url'];parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.netloc!='api.collegefootballdata.com' or parsed.username or parsed.fragment:
            raise ValueError('UNAUTHORIZED_SOURCE_URL')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        opener=urllib.request.build_opener(NoRedirect())
        request=urllib.request.Request(url,headers={'User-Agent':'asp-model-studio-cfb-governed-capture/1.0',
            'Accept':'application/json','Accept-Encoding':'identity','Authorization':'Bearer '+self._secret,**headers})
        try:
            response=opener.open(request,timeout=90)
        except urllib.error.HTTPError as exc:
            response=exc
        except Exception as exc:
            raise RuntimeError('HTTP_TRANSPORT_FAILURE_'+type(exc).__name__) from None
        with response:
            status=int(response.status if hasattr(response,'status') else response.code)
            safe={k.lower():v for k,v in response.headers.items() if k.lower() in SAFE_HEADERS}
            declared=safe.get('content-length')
            if declared and int(declared)>limit:raise RuntimeError('RESPONSE_DECLARED_OVER_BYTE_LIMIT')
            body=bytearray()
            while len(body)<limit:
                chunk=response.read(min(65536,limit-len(body)))
                if not chunk:break
                meter(len(chunk));body.extend(chunk)
            if len(body)>=limit and (not declared or int(declared)>len(body)):
                raise RuntimeError('RESPONSE_BYTE_LIMIT_REACHED')
            raw=bytes(body)
            if self._secret.encode() in raw or any(self._secret in v for v in safe.values()):
                raise RuntimeError('SENSITIVE_ECHO_QUARANTINED_NOT_RETAINED')
            return status,safe,raw


def request_sequence(plan,selected=None):
    info=[a for a in plan['allowedAssets'] if a['endpoint']=='/info']
    data=[a for a in plan['allowedAssets'] if a['endpoint']!='/info']
    if selected is not None:
        allowed={a['url']:a for a in data}
        if any(a['url'] not in allowed or a!=allowed[a['url']] for a in selected):raise ValueError('ASSET_OUTSIDE_PLAN')
        data=selected
    if len({a['url'] for a in data})!=len(data):raise ValueError('DUPLICATE_ASSET_EXCEEDS_PER_ASSET_CEILING')
    if len(info)!=1 or info[0]['maximumCalls']!=2:raise ValueError('ENTITLEMENT_BRACKETS_REQUIRED')
    return [info[0],*data,info[0]]


def capture(*,plan_ref,grant_ref,deployment,root,enabled=False,transport_factory=None,
            clock=now,sleeper=time.sleep,selected=None,predecessor=None,conditional=None,after_schedule=None):
    root=Path(root);started=clock()
    plan=validate_grant(plan_ref,grant_ref,deployment,enabled,started)
    requests=request_sequence(plan,selected)
    if len(requests)>plan['maxRequests']:raise ValueError('REQUEST_PLAN_EXCEEDS_CEILING')
    with owner_lock(root/'capture.lock'):
        # One-time permission remains exhausted after any started batch, even if
        # it stopped early. Recurring owners use one directory per capture window.
        completion=root/'completion.json'
        if completion.exists():return read_ref(reference(completion))
        if (root/'started.json').exists():
            raise RuntimeError('CAPTURE_INTERRUPTED_NO_AUTOMATIC_RETRY')
        initial={'schema':'CFB_BOUNDED_CAPTURE_START_V1','startedAtUtc':started,'plan':plan_ref,
            'grant':grant_ref,'deploymentId':deployment,'plannedRequests':plan['maxRequests'] if after_schedule else len(requests),'predecessor':predecessor}
        immutable(root/'started.json',canonical_bytes(initial))
        ledger={'schema':'CFB_BOUNDED_CAPTURE_LEDGER_V1','attemptedRequests':0,'responseBytes':0,'requests':[],
            'startedAtUtc':started,'plan':plan_ref,'costUsd':0,'priorRecordedUsage':plan.get('priorRecordedUsage')}
        def save():atomic_json(root/'usage.json',ledger)
        save();transport=None;records=[];before=None;after=None;result=None
        previous={} if not predecessor else { (x['endpoint'],json.dumps(x['parameters'],sort_keys=True)):x for x in read_ref(predecessor)['requests'] }
        try:
            transport=transport_factory()
            for seq,asset in enumerate(requests,1):
                if seq>1:sleeper(plan['minimumSecondsBetweenRequests'])
                if not utc(plan['validFromUtc'])<=utc(clock())<utc(plan['validUntilUtc']):raise PermissionError('AUTHORIZATION_EXPIRED')
                if ledger['attemptedRequests']>=plan['maxRequests']:raise RuntimeError('REQUEST_CEILING')
                budget=min(plan['maxSingleResponseBytes'],plan['maxResponseBytes']-ledger['responseBytes'])
                if budget<=0:raise RuntimeError('BYTE_CEILING')
                reservation={'sequence':seq,'url':asset['url'],'endpoint':asset['endpoint'],
                    'parameters':asset['parameters'],'startedAtUtc':clock(),'status':'RESERVED_NOT_KNOWN_COMPLETE'}
                ledger['attemptedRequests']+=1;ledger['requests'].append(reservation);save()
                immutable(root/'request-starts'/f'{seq:02d}.json',canonical_bytes(reservation))
                def meter(n):
                    ledger['responseBytes']+=n
                    if ledger['responseBytes']>plan['maxResponseBytes']:raise RuntimeError('BYTE_CEILING')
                    save()
                old=previous.get((asset['endpoint'],json.dumps(asset['parameters'],sort_keys=True)))
                headers={}
                if conditional and old and asset['endpoint']!='/info':
                    if old.get('responseHeaders',{}).get('etag'):headers['If-None-Match']=old['responseHeaders']['etag']
                    elif old.get('responseHeaders',{}).get('last-modified'):headers['If-Modified-Since']=old['responseHeaders']['last-modified']
                prior_bytes=ledger['responseBytes']
                status,response_headers,raw=transport(asset,headers,budget,meter)
                if ledger['responseBytes']-prior_bytes!=len(raw):raise RuntimeError('RESPONSE_BYTE_ACCOUNTING_FAILURE')
                captured=clock()
                if status==304:
                    if not conditional or not old or not headers or raw:raise ValueError('UNBOUND_304')
                    verified_bytes(old);record=dict(old,sequence=seq,httpStatus=200,
                        transportHttpStatus=304,validatedAtUtc=captured,originalAcquiredAt=old.get('originalAcquiredAt',old['acquiredAt']),
                        responseBytes=0,priorObject=dict(path=old['path'],physicalSha256=old['physicalSha256'],bytes=old['bytes']))
                    value=json.loads(verified_bytes(old))
                    immutable(root/'response-receipts'/f'{seq:02d}.json',canonical_bytes(record))
                else:
                    if old and old['physicalSha256']==digest(raw) and old['bytes']==len(raw):
                        verified_bytes(old);bound=reference(old['path'])
                    else:bound=immutable(root/'raw/sha256'/digest(raw)/'response.json',raw)
                    record=dict(sequence=seq,url=asset['url'],endpoint=asset['endpoint'],parameters=asset['parameters'],
                        acquiredAt=captured,httpStatus=status,responseHeaders=response_headers,path=bound['path'],
                        physicalSha256=bound['sha256'],bytes=bound['bytes'],responseBytes=len(raw),
                        predecessor=None if not old else dict(path=old['path'],physicalSha256=old['physicalSha256'],bytes=old['bytes']))
                    reservation.update(status='RECEIVED',httpStatus=status,responseBytes=len(raw),object=bound);save()
                    immutable(root/'response-receipts'/f'{seq:02d}.json',canonical_bytes(record))
                    if status!=200:raise RuntimeError('SOURCE_HTTP_'+str(status))
                    try:value=json.loads(raw)
                    except Exception:raise ValueError('SOURCE_JSON_SCHEMA_FAILURE') from None
                record['schemaFingerprint']=digest(schema_profile(value));records.append(record)
                if asset['endpoint']=='/info':
                    check=entitlement(value,(plan['maxRequests'] if after_schedule else len(requests))-seq if seq==1 else 0)
                    if seq==1:before=check
                    else:after=check
                else:
                    if not isinstance(value,list):raise ValueError('SOURCE_ARRAY_REQUIRED')
                    if asset['endpoint']=='/teams/fbs' and (not value or any(not {'id','school','alternateNames'}.issubset(x) for x in value)):
                        raise ValueError('SCHOOL_SCHEMA_FAILURE')
                    if asset['endpoint']=='/teams/fbs' and old:
                        prior=json.loads(verified_bytes(old))
                        prior_names={(int(x['id']),name) for x in prior for name in [x['school'],*(x.get('alternateNames') or [])]}
                        names={(int(x['id']),name) for x in value for name in [x['school'],*(x.get('alternateNames') or [])]}
                        if names-prior_names:raise ValueError('SCHOOL_IDENTITY_REVIEW_REQUIRED')
                    if asset['endpoint']=='/games' and (not value or any(not set(plan['schemaRequirements']['games']).issubset(x) for x in value)):
                        raise ValueError('SCHEDULE_SCHEMA_FAILURE')
                    if asset['endpoint']=='/games/teams' and any('id' not in x or 'teams' not in x for x in value):
                        raise ValueError('TEAM_STAT_SCHEMA_FAILURE')
                    if asset['endpoint']=='/games' and after_schedule:
                        extra=after_schedule(value)
                        # Validate against exact enumerated assets before extending
                        # the batch; entitlement reserved the worst-case ceiling.
                        sequence=request_sequence(plan,extra)
                        if any(x['endpoint']=='/games' for x in extra) or seq+len(extra)+1>plan['maxRequests']:
                            raise ValueError('REQUIRED_ASSETS_EXCEED_CAPTURE_CEILING')
                        requests[seq:]=sequence[1:]
                reservation.update(status='VERIFIED',httpStatus=status,responseBytes=len(raw),completedAtUtc=captured);save()
            # Join/account validation precedes publishing a capture pointer. Full
            # chronological features are admitted separately by the publisher.
            # Unrequested immutable historical weeks remain bound to their actual
            # old clocks. Do not claim that a schedule refresh downloaded them.
            source_records=records
            if after_schedule:
                merged={k:v for k,v in previous.items() if k[0]!='/info'}
                for x in records:
                    if x['endpoint']!='/info':merged[(x['endpoint'],json.dumps(x['parameters'],sort_keys=True))]=x
                source_records=[x for x in records if x['endpoint']=='/info']+list(merged.values())
            proposed={'schemaVersion':'CFB_GEN1_CURRENT_CFBD_SOURCE_MANIFEST_V1','createdAt':clock(),
                'season':plan['season'],'provider':'CollegeFootballData','rightsEvidence':plan['rightsEvidence'],
                'authorization':grant_ref,'refreshPlan':plan_ref,'predecessor':predecessor,'requests':source_records,'wireRequests':records,
                'usage':{'calls':ledger['attemptedRequests'],'responseBytes':ledger['responseBytes'],'incrementalCostUsd':0,
                         'entitlementBefore':before,'entitlementAfter':after},
                'credentialRetained':False,'rawResponsePolicy':'Private outside Git; no raw exchange publication',
                'availabilityBoundary':'Actual capture/conditional revalidation; original acquisition preserved for 304'}
            read_capture_rows(proposed,plan['season'])
            ref=object_json(root/'manifests',proposed,'manifest.json')
            result={'schema':'CFB_BOUNDED_CAPTURE_COMPLETION_V1','disposition':'CAPTURED','sourceManifest':ref,
                'providerCalls':ledger['attemptedRequests'],'providerBytes':ledger['responseBytes'],'costUsd':0,
                'entitlementBefore':before,'entitlementAfter':after,'startedAtUtc':started,'completedAtUtc':clock()}
        except Exception as exc:
            # Controlled messages only; transport deliberately never propagates
            # URLs/headers/credential values from third-party exception strings.
            reason=str(exc) if isinstance(exc,(ValueError,PermissionError,RuntimeError)) else type(exc).__name__
            result={'schema':'CFB_BOUNDED_CAPTURE_COMPLETION_V1','disposition':'STOPPED_FAILED_CLOSED',
                'reason':reason,'providerCalls':ledger['attemptedRequests'],'providerBytes':ledger['responseBytes'],
                'costUsd':0,'startedAtUtc':started,'completedAtUtc':clock(),'entitlementBefore':before,'entitlementAfter':after}
        immutable(completion,canonical_bytes(result));return result
