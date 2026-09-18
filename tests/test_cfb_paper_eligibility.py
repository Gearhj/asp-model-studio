"""Synthetic, local-only contract and timing checks; no live source data."""
from copy import deepcopy
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd
import pytest

from scripts.publish_multisport_paper_eligibility import policy
from server.sports_cfb_gen1.current import population_tables
from server.sports_cfb_gen1.lifecycle import immutable, object_json, read_ref
from server.sports_cfb_gen1.publication_io import canonical_bytes, digest, reference
from server.sports_cfb_gen1 import paper_eligibility as pe
from server.sports_shared.paper_research_eligibility import GOVERNANCE, verify_package


@pytest.fixture
def env():
    root = Path(__file__).resolve().parents[1] / 'outputs/cfb-paper-fixtures' / uuid.uuid4().hex
    root.mkdir(parents=True)
    model = object_json(root / 'model', {'syntheticOnly': True})
    plan = object_json(root / 'plan', {'syntheticOnly': True, 'validUntilUtc': '2026-10-01T00:00:00Z'})
    prior = {
        'schemaVersion': pe.SCHEMA, 'artifactVersion': 'ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1',
        'kind': pe.KIND, 'sport': 'CFB', 'governance': GOVERNANCE, 'simulation': {'kind': 'NONE', 'count': 0},
        'binding': {'modelArtifactSha256': model['sha256']},
        'summaries': {
            'authorization': policy('CFB'),
            'probabilityChannels': {'controllingChannel': 'JOINT_PAIRED_RESIDUAL_BASELINE', 'units': 'FRACTIONS_0_TO_1'},
            'probabilitySemantics': {'settlementMustBeExplicit': True},
            'unsupported': {'wagerMarkets': ['SPREAD', 'TOTAL'], 'profitabilityEstablished': False},
        },
    }
    prior_ref = object_json(root / 'prior', prior)
    grant = dict(schema='CFB_VIRTUAL_POLICY_EXTENSION_AUTHORIZATION_V1', approvedBy='James',
        userReply='Authorize unchanged virtual-only policy', consumerVirtualExperimentAuthorized=True,
        realMoneyAuthorized=False, modelPromotionAuthorized=False, noAispWriteAuthorityForProducer=True,
        modelConfiguration=pe.CONFIGURATION, policyVersion='AISP_CFB_PAPER_POLICY_V1',
        planSha256=plan['sha256'], policyAuthorization=prior['summaries']['authorization'],
        priorPolicySupplement=prior_ref, retainedAtUtc='2026-09-18T12:00:00Z', validUntilUtc='2026-10-01T00:00:00Z')
    gr = object_json(root / 'grant', grant)
    release = dict(configurationIdentity=pe.CONFIGURATION, simulationCount=10000,
        refreshPlan=plan, modelBindings={'selectedModel': model}, paperEligibilityAuthorization=gr)
    rr = object_json(root / 'release', release)
    directory = root / 'build'
    directory.mkdir()
    draws = pd.DataFrame(dict(draw=np.arange(10000), home_score=np.tile([28,21],5000), away_score=np.tile([21,28],5000)))
    draws['total'] = draws.home_score + draws.away_score
    draws['home_margin'] = draws.home_score - draws.away_score
    draws.to_parquet(directory / 'baseline-joint-draws.parquet', index=False)
    population_tables(1, draws).to_parquet(directory / 'baseline-pmfs.parquet', index=False)
    forecast = dict(schemaVersion='CFB_GEN1_PROSPECTIVE_RESEARCH_FORECAST_V1', researchOnly=True,
        aispAuthority=False, wageringAuthority=False, forecastId='cfb-gen1:synthetic-only',
        game=dict(game_id=1, home_id=10, away_id=20, home_team='SYN H', away_team='SYN A',
            scheduled_at='2026-09-19T00:00:00Z', status='SCHEDULED'),
        modelBindings=release['modelBindings'], challenger=dict(publishedAsSecondArm=False),
        sourceCutoff='2026-09-18T13:00:00Z', scheduleRevisionCapturedAt='2026-09-18T13:00:00Z',
        createdAt='2026-09-18T13:01:00Z',
        baseline=dict(configuration=pe.CONFIGURATION, drawCount=10000, tieProbability=0.,
            jointHomeWinProbability=.5, jointAwayWinProbability=.5,
            ridgeHomeWinProbability=.7, ridgeAwayWinProbability=.3,
            eloHomeWinProbability=.6, eloAwayWinProbability=.4,
            expectedHomePoints=28., expectedAwayPoints=21., expectedTotal=49., expectedHomeMargin=7.))
    immutable(directory / 'forecast.json', canonical_bytes(forecast))
    index = dict(schemaVersion='CFB_GEN1_PRIVATE_RESEARCH_PACKAGE_INDEX_V1', researchOnly=True,
        aispAuthority=False, wageringAuthority=False, rawProviderResponsesIncluded=False,
        gameId=1, forecastId=forecast['forecastId'], files=[dict(path=p.name,
            physicalSha256=reference(p)['sha256'], bytes=p.stat().st_size) for p in sorted(directory.iterdir())])
    immutable(directory / 'index.json', canonical_bytes(index))
    address = digest((directory / 'index.json').read_bytes())
    package = root / 'production/forecasts/sha256' / address
    package.parent.mkdir(parents=True)
    directory.rename(package)
    row = dict(forecastId=forecast['forecastId'], packageAddress=address, gameId='1',
        packageDirectory=str(package.resolve()), index=reference(package / 'index.json'),
        committedAtUtc='2026-09-18T13:02:00Z', currentlyEligible=True,
        eligibilityValidUntilUtc='2026-09-19T00:00:00Z')
    row['publicationReceipt'] = object_json(root / 'publication', deepcopy(row))
    discovery = dict(schemaVersion='CFB_GEN1_SLATE_DISCOVERY_V1', release=rr,
        createdAtUtc='2026-09-18T13:10:00Z', packages=[row])
    return dict(root=root, grant=grant, gr=gr, release=release, rr=rr, row=row,
        discovery=discovery, dr=object_json(root / 'discovery', discovery), package=package)


def run(e, stamp='2026-09-18T13:15:00Z', clock=None):
    return pe.publish_eligible(discovery_ref=e['dr'], release_ref=e['rr'], grant_ref=e['gr'],
        exchange_family_root=e['root'] / 'research', output_root=e['root'] / 'receipts',
        clock=clock or (lambda: stamp))


def revised_discovery(e):
    e['dr'] = object_json(e['root'] / 'discovery', e['discovery'])


def test_exact_contract_original_clocks_and_no_network_or_regeneration(env, monkeypatch):
    import urllib.request
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: pytest.fail('Network forbidden'))
    before = {p.name: reference(p) for p in env['package'].iterdir()}
    result = run(env)
    assert result['publishedCount'] == 1 and result['exitCode'] == 0
    package = Path(result['games'][0]['exchangeDirectory'])
    verified = verify_package(package)
    doc = verified['document']
    assert doc['summaries']['authorization'] == env['grant']['policyAuthorization']
    assert doc['summaries']['authorizationScope']['grant'] == env['gr']
    assert doc['summaries']['authorizationScope']['validUntilUtc'] == '2026-10-01T00:00:00Z'
    assert doc['binding']['sourcePackageAddress'] == env['row']['packageAddress']
    assert doc['summaries']['originalClocks']['originalExchangePublishedAtUtc'] == env['row']['committedAtUtc']
    assert doc['summaries']['frozenConfiguration']['homeWinProbability'] == .5
    assert doc['summaries']['probabilityChannels']['separateRidge']['homeWin'] == .7
    assert doc['summaries']['probabilityChannels']['separateElo']['homeWin'] == .6
    assert b'\\u2014' not in (package / 'supplement.json').read_bytes()
    assert verified['address'] != verified['manifest']['sha256']
    assert before == {p.name: reference(p) for p in env['package'].iterdir()}
    assert all(result[k] == 0 for k in ('providerCalls', 'providerBytes', 'modelExecutions', 'aispWrites'))


def test_repeat_and_after_t30_reuse_keep_exact_bytes_and_publication_clock(env):
    first = run(env)
    supplement = Path(first['games'][0]['supplement']['path'])
    before = supplement.read_bytes()
    env['discovery']['createdAtUtc'] = '2026-09-18T23:35:00Z'
    revised_discovery(env)
    again = run(env, '2026-09-18T23:35:01Z')
    assert again['reusedCount'] == 1 and again['publishedCount'] == 0
    assert again['games'][0]['publishedUtc'] == first['games'][0]['publishedUtc']
    assert supplement.read_bytes() == before
    assert len(list((env['root'] / 'research/paper-eligibility/sha256').iterdir())) == 1


@pytest.mark.parametrize('stamp,reason', [
    ('2026-09-18T23:30:00Z', 'PAPER_PUBLICATION_CUTOFF_PASSED'),
    ('2026-09-19T00:00:00Z', 'DISCOVERY_LEASE_EXPIRED'),
])
def test_new_supplement_rejected_at_deadline(env, stamp, reason):
    result = run(env, stamp)
    assert result['games'][0]['disposition'] == reason
    assert result['publishedCount'] == 0


def test_historical_or_expired_lease_not_opened_or_reauthorized(env, monkeypatch):
    env['discovery']['packages'][0]['currentlyEligible'] = False
    revised_discovery(env)
    monkeypatch.setattr(pe, '_forecast', lambda *a: pytest.fail('Historical package must not be read'))
    assert run(env)['games'][0]['disposition'] == 'HISTORICAL_NO_CURRENT_LEASE'
    env['discovery']['packages'][0]['currentlyEligible'] = True
    env['discovery']['packages'][0]['eligibilityValidUntilUtc'] = '2026-09-18T13:15:00Z'
    revised_discovery(env)
    assert run(env)['games'][0]['disposition'] == 'DISCOVERY_LEASE_EXPIRED'


def test_deadline_crossing_during_verification_cannot_publish(env):
    times = iter(['2026-09-18T23:29:59Z'] * 5 + ['2026-09-18T23:30:00Z'] * 10)
    result = run(env, clock=lambda: next(times))
    assert result['publishedCount'] == 0 and result['exitCode'] == 1
    assert result['games'][0]['reason'] == 'PAPER_PUBLICATION_CUTOFF_PASSED'
    assert not list((env['root'] / 'research/paper-eligibility/sha256').glob('*/manifest.json'))


@pytest.mark.parametrize('mutation', ['policy', 'plan', 'grant_binding', 'expired'])
def test_authorization_fail_closed(env, mutation):
    if mutation == 'expired':
        with pytest.raises(ValueError, match='GRANT_NOT_CURRENT'):
            run(env, '2026-10-01T00:00:00Z')
        return
    if mutation == 'policy':
        env['grant']['policyAuthorization']['positionCapFraction'] = .01
        env['gr'] = object_json(env['root'] / 'grant', env['grant'])
        env['release']['paperEligibilityAuthorization'] = env['gr']
    elif mutation == 'plan':
        env['release']['refreshPlan'] = object_json(env['root'] / 'plan', {'different': True})
    else:
        env['release'].pop('paperEligibilityAuthorization')
    env['rr'] = object_json(env['root'] / 'release', env['release'])
    with pytest.raises(ValueError):
        run(env)


@pytest.mark.parametrize('mutation', ['forecast', 'publication', 'orientation', 'model'])
def test_exact_physical_and_identity_binding(env, mutation):
    if mutation == 'forecast':
        (env['package'] / 'forecast.json').write_bytes(b'{}')
    elif mutation == 'publication':
        env['discovery']['packages'][0]['committedAtUtc'] = '2026-09-18T13:03:00Z'
        revised_discovery(env)
    elif mutation == 'orientation':
        env['discovery']['packages'][0]['gameId'] = '2'
        revised_discovery(env)
    else:
        # An operational successor cannot substitute even a non-selected model binding.
        env['release']['modelBindings']['pairedResidualPopulation'] = {'sha256': 'different'}
        env['rr'] = object_json(env['root'] / 'release', env['release'])
        env['discovery']['release'] = env['rr']
        revised_discovery(env)
    result = run(env)
    assert result['publishedCount'] == 0 and result['exitCode'] == 1
    assert result['games'][0]['disposition'] == 'FAILED_CLOSED'


def test_started_game_never_reuses_even_with_erroneous_extended_lease(env):
    run(env)
    env['discovery']['packages'][0]['eligibilityValidUntilUtc'] = '2026-09-20T00:00:00Z'
    revised_discovery(env)
    assert run(env, '2026-09-19T00:00:00Z')['games'][0]['disposition'] == 'GAME_ALREADY_STARTED'


@pytest.mark.parametrize('mutation', ['empty', 'removed_scope'])
def test_existing_published_supplement_tamper_fails_closed(env, mutation):
    result = run(env)
    path = Path(result['games'][0]['supplement']['path'])
    doc = json.loads(path.read_bytes())
    if mutation == 'empty':
        path.write_bytes(b'{}')
    else:
        doc['summaries'].pop('authorizationScope')
        path.write_bytes(canonical_bytes(doc))
    # A corrupted package cannot hide its identity and cause re-publication with
    # a new timestamp/address for the same supplement ID.
    with pytest.raises(ValueError, match='EXISTING_PAPER_SUPPLEMENT_CORRUPT'):
        run(env, '2026-09-18T13:16:00Z')
    assert len(list((env['root'] / 'research/paper-eligibility/sha256').iterdir())) == 1
