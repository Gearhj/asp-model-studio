"""Synthetic, zero-network owner orchestration and conservative quota checks."""
import copy
import json
from pathlib import Path
import uuid
import pytest
from server.sports_cfb_gen1.lifecycle import object_json, atomic_json, read_ref, revision_key
from server.sports_cfb_gen1.publication_io import reference, canonical_bytes
from server.sports_cfb_gen1.refresh import due, usage_snapshot, budget_reason, statistics_selector
from server.sports_cfb_gen1.owner import invoke


@pytest.fixture
def space():
    p=Path(__file__).resolve().parents[1]/'outputs/cfb-recurring-fixtures'/uuid.uuid4().hex
    p.mkdir(parents=True);return p


def setup(space):
    stamp='2030-10-21T14:00:00Z'
    rights=object_json(space/'rights',{'evidence':[],'conclusions':{k:'permitted' for k in
        ('privateResponseRetention','historicalAnalysisAndModelTraining','derivedPredictionPublication')}})
    plan={'schema':'CFB_GEN1_RECURRING_REFRESH_PLAN_V1','validFromUtc':'2030-10-01T00:00:00Z','validUntilUtc':'2030-11-10T00:00:00Z',
        'maxCostUsd':0,'retryCount':0,'rightsEvidence':rights,'minimumCaptureSpacingMinutes':90,'dailyCheckHourNewYork':10,
        'checkpointCaptureLeadMinutes':45,'maxRequests':7,'maxRequestsPerUtcDay':28,'maxResponseBytes':100000,
        'maxResponseBytesPerUtcDay':400000,'maxRequestsForPeriodIncludingCarryForward':200,'maxRetainedBytes':2000000,
        'allowedAssets':[{'endpoint':'/games','url':'https://synthetic.invalid/games','parameters':{'year':2030}},
                         {'endpoint':'/teams/fbs','url':'https://synthetic.invalid/schools','parameters':{'year':2030}}]}
    planref=object_json(space/'plan',plan)
    grant=object_json(space/'grant',{'approvedBy':'James','liveCaptureAuthorized':True,'planSha256':planref['sha256'],
        'deploymentId':'SYNTHETIC','validFromUtc':plan['validFromUtc'],'validUntilUtc':plan['validUntilUtc']})
    def raw(value,endpoint,params):
        ref=object_json(space/'raw',value)
        return dict(endpoint=endpoint,parameters=params,acquiredAt='2030-10-21T00:00:00Z',
                    physicalSha256=ref['sha256'],path=ref['path'],bytes=ref['bytes'])
    manifest=object_json(space/'source',{'requests':[raw([], '/games',{'year':2030}),raw([], '/teams/fbs',{'year':2030})]})
    bundle={'schema':'CFB_GEN1_SLATE_INPUT_V1','classification':'SYNTHETIC_TEST_ONLY','sourceManifest':manifest,
        'scheduleCapturedAtUtc':'2030-10-21T00:00:00Z','historyCompleteThroughUtc':'2030-10-21T00:00:00Z','historyMissingGameIds':[],
        'games':[{'gameId':str(i),'predictionInputIdentity':'same-features','target':{'game_id':i,'scheduled_at':'2030-10-22T00:00:00Z','status':'SCHEDULED'}} for i in range(2)]}
    br=object_json(space/'inputs/versions',bundle);pointer=space/'inputs/current.json';atomic_json(pointer,{'inputManifest':br})
    release={'refreshPlan':planref,'deploymentId':'SYNTHETIC','prospectiveEffectiveAtUtc':'2030-10-01T00:00:00Z'}
    rr=object_json(space/'release',release)
    return stamp,plan,grant,bundle,br,pointer,rr


def test_not_due_spacing_dst_and_all_ceiling_dimensions(space):
    stamp,plan,_,b,*_=setup(space)
    b['scheduleCapturedAtUtc']='2030-10-21T13:59:00Z'
    assert not due(b,plan,stamp)['due'] or due(b,plan,stamp)['reasons']==['DAILY_SCHEDULE_CORRECTION_CHECK']
    b['scheduleCapturedAtUtc']=stamp
    assert due(b,plan,stamp)['networkIntentRequests']==0
    assert due(b,plan,'2030-10-21T15:00:00Z',stamp)['disposition']=='REFRESH_COALESCED'
    b['games'][0]['target']['scheduled_at']='2030-11-04T20:00:00Z'
    b['games']=b['games'][:1];b['scheduleCapturedAtUtc']='2030-11-03T14:00:00Z'
    # 10:00 EST is 15:00Z after DST ends, not 14:00Z.
    assert 'DAILY_SCHEDULE_CORRECTION_CHECK' not in due(b,plan,'2030-11-03T14:30:00Z')['reasons']
    assert 'DAILY_SCHEDULE_CORRECTION_CHECK' in due(b,plan,'2030-11-03T15:00:00Z')['reasons']
    usage={'utcDayRequests':0,'periodRequestsIncludingCarryForward':0,'utcDayBytes':0}
    assert budget_reason(usage,plan,0) is None
    for field,n,expected in [('utcDayRequests',22,'UTC_DAY_REQUEST_BUDGET'),('periodRequestsIncludingCarryForward',194,'PERIOD_REQUEST_BUDGET'),('utcDayBytes',300001,'UTC_DAY_BYTE_BUDGET')]:
        assert budget_reason(dict(usage,**{field:n}),plan,0)==expected
    assert budget_reason(usage,plan,1900001)=='RETAINED_STORAGE_BUDGET'


def test_midnight_interruption_and_carry_forward_cannot_reset_quota(space):
    stamp,plan,*_=setup(space)
    carried=object_json(space/'carry',{'startedAtUtc':'2030-10-20T23:59:00Z','completedAtUtc':'2030-10-21T00:01:00Z','providerCalls':7,'providerBytes':30})
    plan['carryForwardCaptureReceipts']=[carried]
    atomic_json(space/'attempts/unfinished/started.json',{'startedAtUtc':stamp})
    usage=usage_snapshot(space,plan,stamp)
    assert usage['utcDayRequests']==usage['periodRequestsIncludingCarryForward']==14
    assert usage['utcDayBytes']==100030


def test_required_weeks_and_bounded_correction_rotation(space):
    stamp,plan,_,b,*_=setup(space)
    def ref(data,endpoint,week=None,acquired='2030-10-01T00:00:00Z'):
        r=object_json(space/'records',data)
        return dict(path=r['path'],physicalSha256=r['sha256'],bytes=r['bytes'],endpoint=endpoint,
                    parameters={} if week is None else {'week':week},acquiredAt=acquired)
    games=[{'id':w,'week':w,'seasonType':'regular','completed':True,'homeClassification':'fbs','awayClassification':'fbs','homePoints':20,'awayPoints':10} for w in range(1,4)]
    previous=object_json(space/'prior',{'requests':[ref(games,'/games'),ref([],'/teams/fbs',acquired=stamp),*[ref([],'/games/teams',w) for w in range(1,4)]]})
    plan['allowedAssets'] += [{'endpoint':'/teams/fbs','url':'synthetic-schools','parameters':{}}]+[{'endpoint':'/games/teams','url':f'synthetic-{w}','parameters':{'week':w}} for w in range(1,6)]
    choose=statistics_selector(plan,previous,stamp)
    assert [a['parameters']['week'] for a in choose(games)]==[1,3]
    changed=copy.deepcopy(games);changed[1]['homePoints']=21
    assert [a['parameters']['week'] for a in choose(changed)]==[1,2,3]
    with pytest.raises(ValueError,match='OUTSIDE_AUTHORIZATION'):choose(games+[dict(games[0],id=6,week=6)])


def test_owner_disabled_and_not_due_never_construct_transport(space):
    stamp,plan,grant,b,br,pointer,rr=setup(space)
    def forbidden():pytest.fail('No credential access/network intent permitted')
    def renderer(row,bundle,release,key,path):
        folder=path/'ready';folder.mkdir(parents=True);(folder/'index.json').write_bytes(canonical_bytes({'forecastId':key}));return folder
    args=dict(release_ref=rr,input_pointer=pointer,state_root=space/'state',exchange_root=space/'fixture-exchange',
        clock=lambda:stamp,transport_factory=forbidden,renderer=renderer,verifier=lambda p:json.loads((p/'index.json').read_bytes()),bundle_validator=lambda *a:None)
    out,_=invoke(**args)
    assert out['providerCalls']==0 and out['exitCode']==0
    assert any(p['disposition']=='NETWORK_DISABLED' for p in out['phases'])
    b['scheduleCapturedAtUtc']=b['historyCompleteThroughUtc']=stamp
    atomic_json(pointer,{'inputManifest':object_json(space/'inputs/versions',b)})
    out,_=invoke(**args,enable_network=True,grant_ref=grant)
    assert out['providerCalls']==0 and any(p['disposition']=='REFRESH_NOT_DUE' for p in out['phases'])


@pytest.mark.parametrize('interruption',['captured','admitted'])
def test_same_owner_capture_admission_publication_recovery(space,interruption):
    stamp,plan,grant,b,br,pointer,rr=setup(space)
    calls=[];admissions=[];renders=[]
    newmanifest=object_json(space/'new-source',dict(read_ref(b['sourceManifest']),revision=2))
    def capturer(**kw):
        calls.append(True)
        atomic_json(kw['root']/'started.json',{'startedAtUtc':stamp})
        result={'disposition':'CAPTURED','startedAtUtc':stamp,'completedAtUtc':stamp,'sourceManifest':newmanifest,'providerCalls':5,'providerBytes':321}
        atomic_json(kw['root']/'completion.json',result);return result
    def admitter(**kw):
        admissions.append(True);new=dict(b,sourceManifest=newmanifest,scheduleCapturedAtUtc=stamp,historyCompleteThroughUtc=stamp)
        ref=object_json(space/'inputs/versions',new);atomic_json(pointer,{'inputManifest':ref});return ref
    def renderer(row,bundle,release,key,path):
        renders.append(key);folder=path/'ready';folder.mkdir(parents=True);(folder/'index.json').write_bytes(canonical_bytes({'forecastId':key}));return folder
    def crash(phase):
        if phase==interruption:raise RuntimeError('Synthetic interruption')
    args=dict(release_ref=rr,input_pointer=pointer,state_root=space/'state',exchange_root=space/'fixture-exchange',clock=lambda:stamp,
        enable_network=True,grant_ref=grant,capturer=capturer,admitter=admitter,renderer=renderer,
        verifier=lambda p:json.loads((p/'index.json').read_bytes()),bundle_validator=lambda *a:None)
    first,_=invoke(**args,fault=crash)
    assert first['exitCode']==1 and first['providerCalls']==5 and not renders
    recovered,_=invoke(**args)
    assert recovered['exitCode']==0 and recovered['providerCalls']==0 and len(renders)==2
    assert len(calls)==len(admissions)==1
    again,_=invoke(**args)
    assert again['disposition']=='REUSED_IMMUTABLE' and again['providerCalls']==0 and len(renders)==2
    for p in recovered['phases']:assert read_ref(p['receipt'])


def test_uncertain_capture_fails_without_retry_or_partial_publication(space):
    stamp,plan,grant,b,br,pointer,rr=setup(space);before=pointer.read_bytes()
    atomic_json(space/'state/capture/active.json',{'status':'STARTED','directory':str(space/'state/capture/attempts/lost')})
    out,_=invoke(release_ref=rr,input_pointer=pointer,state_root=space/'state',exchange_root=space/'fixture-exchange',clock=lambda:stamp,
        enable_network=True,grant_ref=grant,capturer=lambda **kw:pytest.fail('No automatic retry'))
    assert out['exitCode']==1 and out['providerCalls']==0 and 'REVIEW' in out['reason']
    assert pointer.read_bytes()==before and not (space/'fixture-exchange').exists()


def test_operational_successor_preserves_numerical_revision_key(space):
    _,_,_,b,br,_,rr=setup(space)
    successor=object_json(space/'release',dict(read_ref(rr),predictionReleaseIdentity=rr['sha256'],deploymentId='NEW'))
    assert revision_key(b['games'][0],br,rr)==revision_key(b['games'][0],br,successor)
