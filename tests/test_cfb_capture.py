"""Synthetic transport only. No provider calls or real credentials."""
import json
from pathlib import Path
import uuid
import pytest
from server.sports_cfb_gen1.capture import capture,entitlement,request_sequence
from server.sports_cfb_gen1.lifecycle import object_json,read_ref,immutable
from server.sports_cfb_gen1.publication_io import canonical_bytes,reference

@pytest.fixture
def space(monkeypatch):
    monkeypatch.setattr('server.sports_cfb_gen1.inputs.now',lambda:'2026-09-19T00:00:00Z')
    p=Path(__file__).resolve().parents[1]/'outputs/cfb-capture-tests'/uuid.uuid4().hex;p.mkdir(parents=True);return p

def setup(space):
    rights=object_json(space/'rights',{'evidence':[],'conclusions':{k:'permitted' for k in ('privateResponseRetention','historicalAnalysisAndModelTraining','derivedPredictionPublication')}})
    assets=[{'endpoint':e,'parameters':{} if e=='/info' else {'year':2026,'week':1,'seasonType':'regular'},
             'url':'https://api.collegefootballdata.com'+e,'maximumCalls':2 if e=='/info' else 1}
            for e in ('/info','/teams/fbs','/games','/games/teams')]
    plan={'schema':'CFB_GEN1_RECURRING_REFRESH_PLAN_V1','validFromUtc':'2026-09-01T00:00:00Z','validUntilUtc':'2026-10-01T00:00:00Z',
        'maxCostUsd':0,'retryCount':0,'rightsEvidence':rights,'allowedAssets':assets,'maxRequests':5,'maxResponseBytes':100000,
        'maxSingleResponseBytes':20000,'minimumSecondsBetweenRequests':0,'season':2026,'schemaRequirements':{'games':['id','season','week','seasonType','startDate','completed','homeId','awayId']}}
    ref=object_json(space/'plan',plan)
    grant=object_json(space/'grant',{'approvedBy':'James','liveCaptureAuthorized':True,'planSha256':ref['sha256'],'deploymentId':'SYNTHETIC',
        'validFromUtc':plan['validFromUtc'],'validUntilUtc':plan['validUntilUtc']})
    return plan,ref,grant

class Fake:
    def __init__(self,fail=None):self.calls=0;self.fail=fail
    def __call__(self,asset,headers,limit,meter):
        self.calls+=1
        if self.fail=='network':raise RuntimeError('SYNTHETIC_HTTP_FAILURE')
        if asset['endpoint']=='/info':v={'monthlyLimit':1000,'remainingCalls':995 if self.calls==1 else 992}
        elif asset['endpoint']=='/teams/fbs':v=[{'id':1,'school':'A','alternateNames':[]},{'id':2,'school':'B','alternateNames':[]}]
        elif asset['endpoint']=='/games':v=[{'id':100,'season':2026,'week':1,'seasonType':'regular','startDate':'2026-09-20T00:00:00Z',
            'startTimeTBD':False,'completed':False,'homeId':1,'awayId':2,'homeTeam':'A','awayTeam':'B','homeClassification':'fbs','awayClassification':'fbs',
            'neutralSite':False,'conferenceGame':False}]
        else:v=[]
        if self.fail=='entitlement' and self.calls==1:v={'remainingCalls':0,'monthlyLimit':1000}
        raw=canonical_bytes(v)
        if len(raw)>limit:raise RuntimeError('SYNTHETIC_BYTE_CEILING')
        meter(len(raw));return 200,{'etag':'synthetic-etag'},raw

def run(space,ref,grant,fake,**kwargs):
    return capture(plan_ref=ref,grant_ref=grant,deployment='SYNTHETIC',root=space/'run',enabled=True,
        transport_factory=lambda:fake,clock=lambda:'2026-09-18T16:00:00Z',sleeper=lambda _:None,**kwargs)

def test_capture_receipts_counts_exact_reuse_no_second_request(space):
    _,ref,grant=setup(space);fake=Fake();out=run(space,ref,grant,fake)
    assert out['disposition']=='CAPTURED' and fake.calls==out['providerCalls']==5
    manifest=read_ref(out['sourceManifest'])
    assert sum(x['responseBytes'] for x in manifest['requests'])==out['providerBytes']
    assert len(list((space/'run/request-starts').glob('*.json')))==5
    assert run(space,ref,grant,fake)==out and fake.calls==5

@pytest.mark.parametrize('problem',['entitlement','network'])
def test_failure_stops_without_retry_and_persists_consumed_attempt(space,problem):
    _,ref,grant=setup(space);fake=Fake(problem);out=run(space,ref,grant,fake)
    assert out['disposition']=='STOPPED_FAILED_CLOSED' and out['providerCalls']==fake.calls==1
    assert run(space,ref,grant,fake)==out and fake.calls==1
    assert not (space/'run/manifests').exists()

def test_wrong_grant_disabled_and_interrupted_capture_make_zero_calls(space):
    _,ref,grant=setup(space);fake=Fake()
    with pytest.raises(PermissionError):capture(plan_ref=ref,grant_ref=grant,deployment='SYNTHETIC',root=space/'run',enabled=False)
    with pytest.raises(PermissionError):capture(plan_ref=ref,grant_ref=grant,deployment='OTHER',root=space/'run',enabled=True,clock=lambda:'2026-09-18T16:00:00Z')
    immutable(space/'run/started.json',b'{}')
    with pytest.raises(RuntimeError,match='NO_AUTOMATIC_RETRY'):run(space,ref,grant,fake)
    assert fake.calls==0

def test_conditional_304_reuses_bound_bytes(space):
    _,ref,grant=setup(space);first=run(space,ref,grant,Fake())
    class Unchanged(Fake):
        def __call__(self,asset,headers,limit,meter):
            if asset['endpoint']=='/info':return super().__call__(asset,headers,limit,meter)
            self.calls+=1;assert headers=={'If-None-Match':'synthetic-etag'};return 304,{},b''
    out=capture(plan_ref=ref,grant_ref=grant,deployment='SYNTHETIC',root=space/'second',enabled=True,
        transport_factory=Unchanged,clock=lambda:'2026-09-18T17:00:00Z',sleeper=lambda _:None,
        predecessor=first['sourceManifest'],conditional=True)
    assert out['disposition']=='CAPTURED'
    data=[x for x in read_ref(out['sourceManifest'])['requests'] if x['endpoint']!='/info']
    assert all(x['transportHttpStatus']==304 and x['responseBytes']==0 and x['originalAcquiredAt']=='2026-09-18T16:00:00Z' for x in data)

def test_request_ceiling_before_transport(space):
    plan,_,_=setup(space);plan['maxRequests']=4;ref=object_json(space/'limited',plan)
    grant=object_json(space/'limited-grant',{'approvedBy':'James','liveCaptureAuthorized':True,'planSha256':ref['sha256'],'deploymentId':'SYNTHETIC',
        'validFromUtc':plan['validFromUtc'],'validUntilUtc':plan['validUntilUtc']})
    fake=Fake()
    with pytest.raises(ValueError,match='CEILING'):run(space,ref,grant,fake)
    assert fake.calls==0


def test_dynamic_conditional_capture_preserves_cached_week_and_actual_acquisition(space):
    _,ref,grant=setup(space);first=run(space,ref,grant,Fake());plan=read_ref(ref)
    selected=[a for a in plan['allowedAssets'] if a['endpoint']=='/games']
    class Unchanged(Fake):
        def __call__(self,asset,headers,limit,meter):
            if asset['endpoint']=='/info':return super().__call__(asset,headers,limit,meter)
            self.calls+=1;assert headers;return 304,{},b''
    fake=Unchanged()
    out=capture(plan_ref=ref,grant_ref=grant,deployment='SYNTHETIC',root=space/'dynamic',enabled=True,
        transport_factory=lambda:fake,clock=lambda:'2026-09-18T17:00:00Z',sleeper=lambda _:None,
        predecessor=first['sourceManifest'],conditional=True,selected=selected,after_schedule=lambda games:[])
    assert out['disposition']=='CAPTURED' and fake.calls==3
    manifest=read_ref(out['sourceManifest']);rows=manifest['requests']
    schedule=next(x for x in rows if x['endpoint']=='/games')
    cached=next(x for x in rows if x['endpoint']=='/games/teams')
    assert schedule['acquiredAt']=='2026-09-18T16:00:00Z' and schedule['validatedAtUtc']=='2026-09-18T17:00:00Z'
    assert cached['acquiredAt']=='2026-09-18T16:00:00Z' and 'validatedAtUtc' not in cached
    assert len(manifest['wireRequests'])==3 and len(rows)==5
    assert not (space/'dynamic/raw/sha256'/schedule['physicalSha256']).exists()
