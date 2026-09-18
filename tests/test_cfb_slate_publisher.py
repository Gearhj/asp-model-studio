"""Synthetic lifecycle cases only; never provider data or forecasting evidence."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

import pytest

from server.sports_cfb_gen1.publication_io import reference
from server.sports_cfb_gen1.publication_io import canonical_bytes, digest
from server.sports_cfb_gen1.lifecycle import (
    POLICY, eligibility, immutable, object_json, owner_lock, read_ref, tick,
)


@pytest.fixture
def space():
    # No pytest tmp_path/0700 Windows ACL mutation.
    p = Path(__file__).resolve().parents[1] / 'outputs/cfb-slate-fixture-tests' / uuid.uuid4().hex
    p.mkdir(parents=True)
    return p


def row(gid=1):
    return {'gameId': f'synthetic:{gid}', 'target': {'game_id': f'synthetic:{gid}',
        'scheduled_at': '2030-10-22T00:00:00+00:00', 'status': 'SCHEDULED'}}


def env(space, count=3):
    b = {'schema': 'CFB_GEN1_SLATE_INPUT_V1', 'classification': 'SYNTHETIC_TEST_ONLY',
         'scheduleCapturedAtUtc': '2030-10-21T00:00:00+00:00',
         'historyCompleteThroughUtc': '2030-10-21T00:00:00+00:00',
         'games': [row(i) for i in range(count)], 'historyMissingGameIds': []}
    r = {'prospectiveEffectiveAtUtc': '2030-01-01T00:00:00+00:00'}
    return b, object_json(space / 'input', b), object_json(space / 'release', r)


class Renderer:
    def __init__(self):
        self.calls = 0
        self.fail = set()

    def __call__(self, row, bundle, release, key, path):
        self.calls += 1
        if row['gameId'] in self.fail:
            raise ValueError('Synthetic isolated game failure')
        folder = path / 'complete'
        index = {'schemaVersion': 'SYNTHETIC_PACKAGE_ONLY', 'forecastId': key,
                 'publishedAtUtc': None, 'revisionKey': key, 'game': row['target']}
        immutable(folder / 'index.json', canonical_bytes(index))
        return folder


def verifier(path):
    index = json.loads((path / 'index.json').read_bytes())
    assert index['schemaVersion'] == 'SYNTHETIC_PACKAGE_ONLY'
    return index


def run(space, bundle, release, renderer, stamp='2030-10-21T02:00:00+00:00', fault=None):
    return tick(bundle_ref=bundle, release_ref=release, state_root=space / 'state',
        exchange_root=space / 'fixture-exchange', renderer=renderer, verifier=verifier,
        clock=lambda: stamp, fault=fault)[0]


def test_multi_game_idempotency_and_discovery_preserves_every_revision(space):
    b, br, rr = env(space)
    render = Renderer()
    first = run(space, br, rr, render)
    assert first['disposition'] == 'PUBLISHED'
    assert render.calls == 3
    indexes = [g['package']['index'] for g in first['games']]
    again = run(space, br, rr, render)
    assert again['disposition'] == 'REUSED_IMMUTABLE' and render.calls == 3
    assert [g['package']['index'] for g in again['games']] == indexes
    b['scheduleCapturedAtUtc'] = '2030-10-21T01:00:00+00:00'
    b2 = object_json(space / 'input', b)
    changed = run(space, b2, rr, render)
    assert render.calls == 6
    discovery = read_ref(changed['discovery'])
    assert len(discovery['packages']) == 6
    assert sum(p['currentlyEligible'] for p in discovery['packages']) == 3
    assert discovery['predecessor'] == again['discovery']


def test_freshness_and_post_tipoff_are_checked_before_reuse(space):
    _, br, rr = env(space, 1)
    render = Renderer()
    run(space, br, rr, render)
    stale = run(space, br, rr, render, '2030-10-21T23:00:00+00:00')
    assert stale['games'][0]['disposition'] == 'STALE_INPUT_REJECTED'
    assert not read_ref(stale['discovery'])['packages'][0]['currentlyEligible']
    late = run(space, br, rr, render, '2030-10-22T00:01:00+00:00')
    assert late['games'][0]['disposition'] == 'POST_KICKOFF_REJECTED'
    assert render.calls == 1


@pytest.mark.parametrize('phase', ['prepared', 'published'])
def test_interruption_recovery_does_not_resimulate_or_erase_success(space, phase):
    _, br, rr = env(space)
    render = Renderer()
    def fault(stage, gid):
        if stage == phase and gid == 'synthetic:1':
            raise RuntimeError('Synthetic interruption')
    failed = run(space, br, rr, render, fault=fault)
    assert failed['exitCode'] == 1
    assert len(read_ref(failed['discovery'])['packages']) == 2
    recovered = run(space, br, rr, render)
    assert recovered['exitCode'] == 0 and render.calls == 3
    assert len(read_ref(recovered['discovery'])['packages']) == 3


def test_isolated_failure_does_not_hide_game_or_erase_other_packages(space):
    _, br, rr = env(space)
    render = Renderer()
    render.fail.add('synthetic:1')
    result = run(space, br, rr, render)
    assert [g['disposition'] for g in result['games']] == ['PUBLISHED_NEW_PROSPECTIVE', 'GAME_FAILED', 'PUBLISHED_NEW_PROSPECTIVE']
    assert len(read_ref(result['discovery'])['packages']) == 2
    assert list((space / 'state/runner-receipts/sha256').glob('*/receipt.json'))


def test_not_due_status_changed_and_cutoff_semantics(space):
    b, br, rr = env(space, 1)
    render = Renderer()
    assert run(space, br, rr, render, '2030-10-10T02:00:00+00:00')['disposition'] == 'NOT_DUE'
    b['games'][0]['target']['status'] = 'STATUS_POSTPONED'
    br2 = object_json(space / 'input', b)
    assert run(space, br2, rr, render)['games'][0]['disposition'] == 'GAME_NOT_SCHEDULED'
    assert run(space, br, rr, render, '2030-10-21T23:30:00+00:00')['games'][0]['disposition'] == 'PUBLICATION_CUTOFF_PASSED'
    assert render.calls == 0


def test_due_crosses_deadline_during_render_is_not_published(space):
    b, br, rr = env(space, 1)
    b['scheduleCapturedAtUtc'] = b['historyCompleteThroughUtc'] = '2030-10-21T23:00:00+00:00'
    br = object_json(space / 'input', b)
    calls = [0]
    def clock():
        calls[0] += 1
        return '2030-10-21T23:29:00+00:00' if calls[0] <= 2 else '2030-10-21T23:31:00+00:00'
    result, _ = tick(bundle_ref=br, release_ref=rr, state_root=space / 'state', exchange_root=space / 'fixture-exchange',
        renderer=Renderer(), verifier=verifier, clock=clock)
    assert result['games'][0]['disposition'] == 'PUBLICATION_CUTOFF_PASSED'
    assert read_ref(result['discovery'])['packages'] == []


def test_no_concurrent_owner_and_tamper_rejected(space):
    _, br, rr = env(space, 1)
    with owner_lock(space / 'state/publisher.lock'):
        result = run(space, br, rr, Renderer())
    assert result['disposition'] == 'FAILED' and result['reason'] == 'OWNER_BUSY'
    Path(br['path']).write_bytes(b'{}')
    assert run(space, br, rr, Renderer())['disposition'] == 'FAILED'




def test_checkpoint_contract_and_dst():
    from zoneinfo import ZoneInfo
    from server.sports_cfb_gen1.lifecycle import utc
    assert POLICY['checkpointsMinutesBeforeKickoff']==[10080,1440,360,60]
    start=utc('2030-11-03T20:00:00Z')
    b={'scheduleCapturedAtUtc':'2030-11-03T18:00:00Z','historyCompleteThroughUtc':'2030-11-03T18:00:00Z'}
    r={'target':{'scheduled_at':start.isoformat(),'status':'SCHEDULED'}}
    assert start.astimezone(ZoneInfo('America/New_York')).hour==15
    assert eligibility(r,b,'2030-11-03T19:00:00Z')['checkpointMinutesBeforeKickoff']==60
    assert eligibility(r,b,'2030-11-03T19:30:00Z')['disposition']=='PUBLICATION_CUTOFF_PASSED'


def test_unchanged_capture_clock_reuses_but_target_features_change_revision(space):
    b,_,rr=env(space,1);b['games'][0]['predictionInputIdentity']='frozen-target-features'
    render=Renderer();br=object_json(space/'input',b)
    run(space,br,rr,render)
    b['scheduleCapturedAtUtc']='2030-10-21T01:00:00Z'
    b['games'][0]['target']['source_revision']='new-capture-same-prediction-inputs'
    assert run(space,object_json(space/'input',b),rr,render)['disposition']=='REUSED_IMMUTABLE'
    b['games'][0]['predictionInputIdentity']='genuinely-changed-target-features'
    assert run(space,object_json(space/'input',b),rr,render)['disposition']=='PUBLISHED'
    assert render.calls==2


def test_aliases_effectivity_ambiguity_and_future_capture():
    from server.sports_cfb_gen1.identities import build_aliases,resolve
    m=build_aliases([{'id':1,'school':'School A','alternateNames':['A']}],2026,'2026-09-01T00:00:00Z',{})
    assert resolve(m,1,'a','2026-10-01T00:00:00Z','2026-09-02T00:00:00Z')=='School A'
    for kickoff,cutoff in [('2027-09-01T00:00:00Z','2026-09-02T00:00:00Z'),('2026-10-01T00:00:00Z','2026-08-31T00:00:00Z')]:
        with pytest.raises(ValueError):resolve(m,1,'A',kickoff,cutoff)
    m['aliases'].append(dict(m['aliases'][0],sourceTeamId=2))
    with pytest.raises(ValueError):resolve(m,1,m['aliases'][0]['alias'],'2026-10-01T00:00:00Z','2026-09-02T00:00:00Z')


def test_pending_and_wrong_sport_fail_closed(space):
    from server.sports_cfb_gen1.inputs import validate_bundle
    for schema in ('NBA_GEN1_SLATE_INPUT_V1','NFL_INPUT','MLB_INPUT'):
        with pytest.raises(ValueError):validate_bundle({'schema':schema},{})
    b,_,rr=env(space,1);b['games'][0]['inputBlockers']=['UNKNOWN_SCHOOL']
    result=run(space,object_json(space/'input',b),rr,Renderer())
    assert result['disposition']=='INPUTS_BLOCKED'


def test_real_renderer_with_synthetic_population_and_independent_consumer(space,monkeypatch):
    import ast,hashlib,pathlib,typing
    import pandas as pd
    import numpy as np
    from server.sports_cfb_gen1 import render as sr
    f={name:0. for name in sr.FEATURE_COLUMNS}
    f.update(game_id=1,season=2099,home_id=10,away_id=20,scheduled_at=pd.Timestamp('2099-10-22T00:00:00Z'),
        elo_home_win_probability=.6,feature_max_source_game_date=pd.Timestamp('2026-09-01T00:00:00Z'))
    pd.DataFrame([f]).to_parquet(space/'features.parquet',index=False)
    fake=object_json(space/'synthetic',{'source':'NON_PROVIDER_FIXTURE'})
    br=object_json(space/'bundle',{'features':reference(space/'features.parquet'),'sourceCutoffUtc':'2026-09-02T00:00:00Z',
        'scheduleCapturedAtUtc':'2026-09-02T00:00:00Z','sourceManifest':fake,'aliases':fake,'sourceLimitations':['Synthetic test only']})
    rr=object_json(space/'release',{'modelBindings':{},'prospectiveEffectiveAtUtc':'2026-09-01T00:00:00Z','limitations':['Synthetic test only']})
    target={'game_id':1,'season':2099,'home_id':10,'away_id':20,'home_team':'SYN_H','away_team':'SYN_A','scheduled_at':'2099-10-22T00:00:00Z','status':'SCHEDULED'}
    d=pd.DataFrame({'draw':np.arange(10000),'home_score':np.tile([20,30],5000),'away_score':np.tile([28,21],5000)})
    d['total']=d.home_score+d.away_score;d['home_margin']=d.home_score-d.away_score
    monkeypatch.setattr(sr,'numerical_population',lambda *a:({'awayPoints':24.,'homePoints':28.,'homeMargin':4.,'totalPoints':52.},.7,d,{'drawCount':10000}))
    directory=sr.render({'target':target},br,rr,'synthetic-key',space/'build')
    f=json.loads((directory/'forecast.json').read_bytes())
    assert f['baseline']['jointHomeWinProbability']==.5 and f['baseline']['ridgeHomeWinProbability']==.7
    assert f['baseline']['eloHomeWinProbability']==.6
    assert f['baseline']['jointMeanTotal']==49.5 and f['baseline']['expectedTotal']==52.
    addressed=space/digest((directory/'index.json').read_bytes());directory.rename(addressed)
    # Execute only the consumer's existing pure physical verifier and PMF reader.
    # No import_package/session/SQLAlchemy/database or AISP writes.
    consumer=Path(r'C:\Users\james\ai-sports-predictor\server\app\cfb\research_import.py')
    tree=ast.parse(consumer.read_text(encoding='utf-8'))
    functions=[x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name in ('verify_package','read_pmfs')]
    ns={'pathlib':pathlib,'Any':typing.Any,'hashlib':hashlib,'json':json,'CfbImportError':ValueError,
        'INDEX_SCHEMA':'CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1','MUST_BE_FALSE':('aispAuthority','wageringAuthority'),
        'PMF_METRICS':('away_score','home_score','total','home_margin')}
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(consumer),'exec'),ns)
    assert len(ns['verify_package'](addressed)['members'])==3
    assert len(ns['read_pmfs'](addressed,expected_draws=10000))==4
    assert 'illustrativeTotals' in f['baseline']
    (addressed/'forecast.json').write_bytes(b'tampered')
    with pytest.raises(ValueError):ns['verify_package'](addressed)
    with pytest.raises(ValueError):sr.verify_package(addressed)


def test_no_network_owner_and_durable_failures(space,monkeypatch):
    import urllib.request
    from server.sports_cfb_gen1.owner import invoke
    from server.sports_cfb_gen1.lifecycle import atomic_json
    monkeypatch.setattr(urllib.request,'urlopen',lambda *a,**k:pytest.fail('Network forbidden'))
    b,br,rr=env(space,2);atomic_json(space/'inputs/current.json',{'inputManifest':br})
    args=dict(release_ref=rr,input_pointer=space/'inputs/current.json',state_root=space/'owner-state',exchange_root=space/'fixture-exchange',
        renderer=Renderer(),verifier=verifier,bundle_validator=lambda *a:None,clock=lambda:'2030-10-21T02:00:00Z')
    value,bound=invoke(**args)
    assert value['providerCalls']==0 and value['disposition']=='PUBLISHED'
    for phase in value['phases']:assert read_ref(phase['receipt'])
    before=(space/'inputs/current.json').read_bytes()
    cap=object_json(space/'capture',{})
    atomic_json(space/'capture-current.json',{'sourceManifest':cap})
    b['sourceManifest']={'sha256':'older'};atomic_json(space/'inputs/current.json',{'inputManifest':object_json(space/'input',b)})
    before=(space/'inputs/current.json').read_bytes()
    def fail(**kwargs):raise ValueError('Synthetic missing team statistics')
    value,_=invoke(**args,capture_pointer=space/'capture-current.json',admitter=fail)
    assert value['disposition']=='FAILED_CLOSED' and (space/'inputs/current.json').read_bytes()==before
    assert read_ref(value['runnerReceipt'])['disposition']=='PUBLICATION_SKIPPED'


def test_admission_corrected_history_target_exclusion_atomicity_and_identity(space):
    import pandas as pd
    from server.sports_cfb_gen1.inputs import admit
    from server.sports_cfb_gen1.current import cfbd_2026_games
    from server.sports_cfb_gen1.publication_io import reference
    def game(gid,year,stamp,completed=True,home=28):
        return dict(id=gid,season=year,week=1,seasonType='regular',startDate=stamp,completed=completed,
                    homeId=10,awayId=20,homeTeam='School H',awayTeam='School A',homeClassification='fbs',awayClassification='fbs',
                    homePoints=home if completed else None,awayPoints=21 if completed else None)
    def stats(gid):
        return {'id':gid,'teams':[{'teamId':tid,'stats':[{'category':'totalYards','stat':'350'},{'category':'turnovers','stat':'1'}]} for tid in (10,20)]}
    history=cfbd_2026_games([game(100,2025,'2025-09-01T00:00:00Z')],[stats(100)])
    history.to_parquet(space/'history.parquet',index=False)
    release={'historicalGames':reference(space/'history.parquet'),'modelBindings':{}}
    def capture(score=28,stamp='2026-09-02T12:00:00Z',broken=None):
        schedule=[game(200,2026,'2026-09-01T00:00:00Z',home=score),game(300,2026,'2026-09-03T00:00:00Z',False)]
        teamstats=[stats(200)]
        if broken=='team':teamstats[0]['teams'][0]['teamId']=999
        if broken=='missing':teamstats=[]
        if broken=='future':teamstats.append(stats(300))
        if broken=='duplicate':schedule.append(schedule[0])
        if broken=='missing-score':schedule[0]['homePoints']=None
        schools=[{'id':10,'school':'School H'},{'id':20,'school':'School A'}]
        requests=[]
        for endpoint,value in [('/games',schedule),('/teams/fbs',schools),('/games/teams',teamstats)]:
            ref=object_json(space/'raw-fixture',value)
            requests.append(dict(path=ref['path'],bytes=ref['bytes'],physicalSha256=ref['sha256'],endpoint=endpoint,
                                 acquiredAt=stamp,httpStatus=200,parameters={'year':2026,'seasonType':'regular','week':1}))
        return object_json(space/'capture',{'requests':requests})
    root=space/'registry'
    first=admit(manifest_ref=capture(),release=release,registry_root=root)
    b1=read_ref(first);f1=pd.read_parquet(b1['features']['path']).set_index('game_id')
    assert f1.loc[200,'home_current_season_games']==0
    assert f1.loc[300,'home_current_season_games']==1
    again=admit(manifest_ref=capture(),release=release,registry_root=root)
    assert again==first
    before=(root/'current.json').read_bytes()
    for broken in ('team','missing','future','duplicate','missing-score'):
        with pytest.raises(ValueError):admit(manifest_ref=capture(broken=broken),release=release,registry_root=root)
        assert (root/'current.json').read_bytes()==before
    def interrupt(*args):raise RuntimeError('Synthetic power interruption before input pointer commit')
    correction=capture(score=35,stamp='2026-09-02T13:00:00Z')
    with pytest.raises(RuntimeError):admit(manifest_ref=correction,release=release,registry_root=root,precommit=interrupt)
    assert (root/'current.json').read_bytes()==before
    second=admit(manifest_ref=correction,release=release,registry_root=root)
    b2=read_ref(second);f2=pd.read_parquet(b2['features']['path']).set_index('game_id')
    assert b2['predecessor']==first and f2.loc[300,'home_points_for_season']!=f1.loc[300,'home_points_for_season']
    # The completed game's own revised outcome cannot leak into its predictors.
    from server.sports_cfb_gen1.pipeline import FEATURE_COLUMNS
    pd.testing.assert_series_equal(f1.loc[200,FEATURE_COLUMNS],f2.loc[200,FEATURE_COLUMNS],check_exact=True)
    assert (Path(first['path']).read_bytes())


def test_recovery_after_admission_advances_all_games_once(space):
    from server.sports_cfb_gen1.owner import invoke
    from server.sports_cfb_gen1.lifecycle import atomic_json
    b,_,rr=env(space,2);b['sourceManifest']={'sha256':'old'}
    br=object_json(space/'input',b);pointer=space/'inputs/current.json'
    atomic_json(pointer,{'inputManifest':br})
    capture=object_json(space/'new-capture',{})
    atomic_json(space/'capture-current.json',{'sourceManifest':capture})
    newer=copy.deepcopy(b);newer['sourceManifest']=capture
    newref=object_json(space/'input',newer)
    admitted=[]
    def admitter(**kwargs):
        admitted.append(True);atomic_json(pointer,{'inputManifest':newref});return newref
    def crash(phase):raise RuntimeError('Interrupted after committed input version')
    renderer=Renderer()
    args=dict(release_ref=rr,input_pointer=pointer,state_root=space/'owner-state',exchange_root=space/'fixture-exchange',
        renderer=renderer,verifier=verifier,bundle_validator=lambda *a:None,admitter=admitter,
        capture_pointer=space/'capture-current.json',clock=lambda:'2030-10-21T02:00:00Z')
    assert invoke(**args,fault=crash)[0]['disposition']=='FAILED_CLOSED'
    assert renderer.calls==0 and len(admitted)==1
    assert invoke(**args)[0]['disposition']=='PUBLISHED'
    assert invoke(**args)[0]['disposition']=='REUSED_IMMUTABLE'
    assert renderer.calls==2 and len(admitted)==1
