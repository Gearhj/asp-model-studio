"""Local, same-owner supplements for explicitly authorized CFB virtual research.

Call only while the existing publisher lock is held, after its current discovery
is durable. No provider, model execution, consumer or scheduler operation lives
here. A supplement never renews the independently required discovery lease.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import uuid

from .lifecycle import immutable, now, object_json, read_ref, utc
from .publication_io import canonical_bytes, digest, reference
from .render import CONFIGURATION, verify_package as verify_forecast
from server.sports_shared.paper_research_eligibility import (
    GOVERNANCE, KIND, MANIFEST_SCHEMA, SCHEMA, package_address,
    validate_document, validate_policy, verify_package,
)


def _sha(ref):
    return ref.get('sha256', ref.get('physicalSha256'))


def _supplement_id(row, grant, grant_ref):
    return 'cfb-paper-eligibility:' + digest({
        'forecastId': row['forecastId'], 'sourcePackageAddress': row['packageAddress'],
        'policyVersion': grant['policyVersion'], 'authorizationSha256': _sha(grant_ref),
    }) + ':v1'


def validate_authorization(grant_ref, release, stamp):
    """The installed release binds the exact new grant, not inferred authority."""
    grant = read_ref(grant_ref)
    required = {
        'schema': 'CFB_VIRTUAL_POLICY_EXTENSION_AUTHORIZATION_V1',
        'approvedBy': 'James', 'userReply': 'Authorize unchanged virtual-only policy',
        'consumerVirtualExperimentAuthorized': True, 'realMoneyAuthorized': False,
        'modelPromotionAuthorized': False, 'noAispWriteAuthorityForProducer': True,
        'modelConfiguration': CONFIGURATION, 'policyVersion': 'AISP_CFB_PAPER_POLICY_V1',
    }
    if any(grant.get(k) != v for k, v in required.items()):
        raise ValueError('PAPER_POLICY_GRANT_SCOPE_DIFFERS')
    if release.get('paperEligibilityAuthorization') != grant_ref:
        raise ValueError('PAPER_POLICY_GRANT_NOT_BOUND_TO_RELEASE')
    if grant['planSha256'] != _sha(release['refreshPlan']):
        raise ValueError('PAPER_POLICY_ACQUISITION_PLAN_DIFFERS')
    plan = read_ref(release['refreshPlan'])
    # Physical plan binding is authoritative. Its spelling of expiry is not
    # assumed; the explicit paper grant controls paper eligibility duration.
    if not plan:
        raise ValueError('PAPER_POLICY_EMPTY_PLAN')
    if not utc(grant['retainedAtUtc']) <= utc(stamp) < utc(grant['validUntilUtc']):
        raise ValueError('PAPER_POLICY_GRANT_NOT_CURRENT')
    prior = read_ref(grant['priorPolicySupplement'])
    if (prior.get('artifactVersion') != 'ASP_CFB_PAPER_RESEARCH_ELIGIBILITY_V1'
            or prior.get('kind') != KIND or prior.get('sport') != 'CFB'):
        raise ValueError('PAPER_POLICY_PREDECESSOR_DIFFERS')
    policy = grant['policyAuthorization']
    validate_policy(policy)
    if policy != prior['summaries']['authorization']:
        raise ValueError('PAPER_POLICY_TERMS_CHANGED')
    if (release['configurationIdentity'] != CONFIGURATION
            or release['simulationCount'] != 10000
            or _sha(release['modelBindings']['selectedModel']) != prior['binding']['modelArtifactSha256']):
        raise ValueError('PAPER_POLICY_FROZEN_MODEL_DIFFERS')
    return grant, prior


def _current(row, grant, stamp, forecast=None, *, new_publication=True):
    at = utc(stamp)
    if row.get('currentlyEligible') is not True:
        return 'HISTORICAL_NO_CURRENT_LEASE'
    if not row.get('eligibilityValidUntilUtc') or at >= utc(row['eligibilityValidUntilUtc']):
        return 'DISCOVERY_LEASE_EXPIRED'
    if at >= utc(grant['validUntilUtc']):
        return 'PAPER_POLICY_GRANT_EXPIRED'
    if forecast:
        if at >= utc(forecast['game']['scheduled_at']):
            return 'GAME_ALREADY_STARTED'
        if new_publication and at >= utc(forecast['game']['scheduled_at']) - timedelta(minutes=30):
            return 'PAPER_PUBLICATION_CUTOFF_PASSED'
    return None


def _forecast(row, release):
    directory = Path(row['packageDirectory'])
    index_ref = reference(directory / 'index.json')
    if row['index'] != index_ref or index_ref['sha256'] != row['packageAddress']:
        raise ValueError('PAPER_FORECAST_PACKAGE_ADDRESS_DIFFERS')
    index = verify_forecast(directory)
    forecast = json.loads((directory / 'forecast.json').read_bytes())
    publication = read_ref(row['publicationReceipt'])
    for key in ('forecastId', 'packageAddress', 'gameId', 'index', 'committedAtUtc'):
        if publication[key] != row[key]:
            raise ValueError('PAPER_ORIGINAL_PUBLICATION_BINDING_DIFFERS:' + key)
    if (forecast['forecastId'] != row['forecastId'] or index['forecastId'] != row['forecastId']
            or str(forecast['game']['game_id']) != str(row['gameId'])
            or forecast['modelBindings'] != release['modelBindings']
            or forecast['baseline']['configuration'] != CONFIGURATION
            or forecast['baseline']['drawCount'] != 10000
            or forecast['baseline']['tieProbability'] != 0
            or forecast['game'].get('status') != 'SCHEDULED'
            or forecast.get('challenger', {}).get('publishedAsSecondArm') is not False):
        raise ValueError('PAPER_FROZEN_FORECAST_BINDING_DIFFERS')
    return forecast


def _document(row, forecast, grant, prior, grant_ref, discovery_ref, release_ref, stamp):
    """Reuse the original consumer contract and policy terms without translation."""
    document = deepcopy(prior)
    document.pop('predecessorSupplementAddress', None)
    directory = Path(row['packageDirectory'])
    baseline = forecast['baseline']
    fid = forecast['forecastId']
    model_sha = _sha(forecast['modelBindings']['selectedModel'])
    population = reference(directory / 'baseline-joint-draws.parquet')
    document.update(
        supplementId=_supplement_id(row, grant, grant_ref),
        sourceCutoffUtc=forecast['sourceCutoff'], publishedUtc=stamp,
        binding=dict(eventId='cfbd:' + str(row['gameId']), providerGameId=str(row['gameId']),
            forecastId=fid, engineId='CFB_GEN1_JOINT_BASELINE', modelArtifactSha256=model_sha,
            configurationIdentity=CONFIGURATION, sourcePackageAddress=row['packageAddress']),
    )
    summaries = document['summaries']
    summaries['authorization'] = deepcopy(grant['policyAuthorization'])
    summaries['authorizationScope'] = {
        'grant': grant_ref, 'validUntilUtc': grant['validUntilUtc'],
        'priorPolicySupplement': grant['priorPolicySupplement'], 'planSha256': grant['planSha256'],
        'currentDiscoveryLeaseRequiredAtDecision': True,
        'consumerDecisionAndQuotePolicyStillRequired': True,
        'producerLeaseIsNotConsumerPositionAuthority': True,
    }
    summaries['game'] = deepcopy(forecast['game'])
    summaries['originalClocks'] = {
        'sourceCutoffUtc': forecast['sourceCutoff'],
        'scheduleRevisionCapturedAtUtc': forecast['scheduleRevisionCapturedAt'],
        'forecastCreatedAtUtc': forecast['createdAt'],
        'originalExchangePublishedAtUtc': row['committedAtUtc'],
        'eligibilityPublishedAtUtc': stamp,
    }
    clocks = summaries['originalClocks']
    if not (utc(clocks['sourceCutoffUtc']) <= utc(clocks['forecastCreatedAtUtc'])
            <= utc(clocks['originalExchangePublishedAtUtc']) <= utc(stamp)
            < utc(forecast['game']['scheduled_at']) - timedelta(minutes=30)):
        raise ValueError('PAPER_FORECAST_PUBLICATION_CHRONOLOGY_DIFFERS')
    summaries['frozenForecast'] = dict(arm='baseline', forecastId=fid,
        forecastSha256=reference(directory / 'forecast.json')['sha256'],
        configurationIdentity=CONFIGURATION,
        expectedScores=dict(away=baseline['expectedAwayPoints'], home=baseline['expectedHomePoints'],
            homeMargin=baseline['expectedHomeMargin'], total=baseline['expectedTotal']),
        population=dict(forecastId=fid, drawCount=10000, artifact=population))
    summaries['frozenConfiguration'] = dict(forecastId=fid, configurationIdentity=CONFIGURATION,
        engineId='CFB_GEN1_JOINT_BASELINE', modelArtifactSha256=model_sha,
        awayWinProbability=baseline['jointAwayWinProbability'],
        homeWinProbability=baseline['jointHomeWinProbability'], tieProbability=baseline['tieProbability'],
        executionAllowed=False, modelPromotionAllowed=False,
        originalPopulation=dict(drawCount=10000, artifact=population))
    channels = summaries['probabilityChannels']
    channels['controllingJoint'] = dict(awayWin=baseline['jointAwayWinProbability'],
        homeWin=baseline['jointHomeWinProbability'], tie=baseline['tieProbability'])
    for name, prefix in [('separateRidge', 'ridge'), ('separateElo', 'elo')]:
        channels[name] = dict(awayWin=baseline[prefix + 'AwayWinProbability'],
            homeWin=baseline[prefix + 'HomeWinProbability'])
    document['producer'] = dict(forecastRegenerated=False, modelExecution=False, providerRequests=0,
        discoveryAtEligibilityPublication=discovery_ref, releaseAtEligibilityPublication=release_ref,
        physicalReferences=[row['index'], reference(directory / 'forecast.json'), population,
            row['publicationReceipt'], grant_ref, grant['priorPolicySupplement'], discovery_ref, release_ref])
    validate_document(document)
    return document


def _existing(root):
    found = {}
    for path in sorted((Path(root) / 'paper-eligibility/sha256').glob('*/supplement.json')):
        raw = path.read_bytes()
        doc = json.loads(raw)
        manifest = json.loads((path.parent / 'manifest.json').read_bytes())
        address = manifest.pop('supplementSha256')
        # Validate old package bytes too, without requiring legacy supplement
        # encoding or dereferencing its original source population. Corruption
        # must not hide an existing ID and permit a conflicting new package.
        if (address != path.parent.name or package_address(manifest) != address
                or manifest['artifacts'] != [dict(file='supplement.json', sha256=digest(raw), bytes=len(raw))]
                or manifest['supplementId'] != doc['supplementId']):
            raise ValueError('EXISTING_PAPER_SUPPLEMENT_CORRUPT')
        if 'authorizationScope' not in doc.get('summaries', {}):
            continue  # Preserve the earlier single-game supplements as delivered.
        key = doc['supplementId']
        if key in found:
            raise ValueError('DUPLICATE_PAPER_SUPPLEMENT_ID')
        found[key] = path.parent
    return found


def _commit(document, *, family, precommit):
    raw = canonical_bytes(document)
    identity = dict(schemaVersion=MANIFEST_SCHEMA, contractVersion=SCHEMA,
        supplementId=document['supplementId'], kind=KIND, sport='CFB', governance=GOVERNANCE,
        artifacts=[dict(file='supplement.json', sha256=digest(raw), bytes=len(raw))])
    address = package_address(identity)
    manifest = dict(identity, supplementSha256=address)
    # Preparation is outside the discoverable sha256 directory. Both complete
    # canonical files become visible in one same-volume directory rename.
    stage = family / 'paper-eligibility/staging' / uuid.uuid4().hex / address
    immutable(stage / 'supplement.json', raw)
    immutable(stage / 'manifest.json', canonical_bytes(manifest))
    verify_package(stage)
    destination = family / 'paper-eligibility/sha256' / address
    destination.parent.mkdir(parents=True, exist_ok=True)
    precommit()
    if destination.exists():
        if verify_package(destination)['document'] != document:
            raise ValueError('IMMUTABLE_PAPER_SUPPLEMENT_CONFLICT')
    else:
        stage.rename(destination)
    return dict(supplementAddress=address, supplementId=document['supplementId'],
        exchangeDirectory=str(destination.resolve()), manifest=reference(destination / 'manifest.json'),
        supplement=reference(destination / 'supplement.json'), publishedUtc=document['publishedUtc'])


def publish_eligible(*, discovery_ref, release_ref, grant_ref, exchange_family_root,
                     output_root, clock=now):
    """Publish/reuse eligible immutable forecasts during one existing owner tick.

    ``exchange_family_root`` is cfb-gen1-research-v1, not the owner's production
    family. The caller must hold its existing owner lock throughout this call.
    Errors isolate one package, are retained, and return exitCode=1. No retry,
    lease renewal, source acquisition or change to any forecast is performed.
    """
    started = clock()
    release = read_ref(release_ref)
    grant, prior = validate_authorization(grant_ref, release, started)
    discovery = read_ref(discovery_ref)
    if (discovery.get('schemaVersion') != 'CFB_GEN1_SLATE_DISCOVERY_V1'
            or discovery['release'] != release_ref or utc(discovery['createdAtUtc']) > utc(started)):
        raise ValueError('PAPER_CURRENT_DISCOVERY_BINDING_DIFFERS')
    family = Path(exchange_family_root)
    existing = _existing(family)
    result = dict(schema='CFB_PAPER_ELIGIBILITY_OWNER_RECEIPT_V1', startedAtUtc=started,
        discovery=discovery_ref, release=release_ref, authorization=grant_ref, games=[],
        providerCalls=0, providerBytes=0, modelExecutions=0, aispWrites=0, exitCode=0,
        consumerAcknowledgement='NOT_ESTABLISHED')
    for row in discovery['packages']:
        item = dict(forecastId=row['forecastId'], packageAddress=row['packageAddress'], gameId=row['gameId'])
        try:
            reason = _current(row, grant, clock())
            if reason:
                item['disposition'] = reason
                continue
            forecast = _forecast(row, release)
            reason = _current(row, grant, clock(), forecast, new_publication=False)
            if reason:
                item['disposition'] = reason
                continue
            old = existing.get(_supplement_id(row, grant, grant_ref))
            if old:
                verified = verify_package(old)
                saved = verified['document']
                expected = _document(row, forecast, grant, prior, grant_ref,
                    saved['producer']['discoveryAtEligibilityPublication'],
                    saved['producer']['releaseAtEligibilityPublication'], saved['publishedUtc'])
                if saved != expected:
                    raise ValueError('PAPER_SUPPLEMENT_ID_BYTES_CONFLICT')
                reason = _current(row, grant, clock(), forecast, new_publication=False)
                if reason:
                    item['disposition'] = reason
                    continue
                item.update(disposition='REUSED_IMMUTABLE', supplementAddress=verified['address'],
                    supplementId=saved['supplementId'], publishedUtc=saved['publishedUtc'],
                    supplement=verified['supplement'], manifest=verified['manifest'], exchangeDirectory=str(old))
            else:
                reason = _current(row, grant, clock(), forecast)
                if reason:
                    item['disposition'] = reason
                    continue
                doc = _document(row, forecast, grant, prior, grant_ref, discovery_ref, release_ref, clock())
                def precommit():
                    stamp = clock()
                    reason = _current(row, grant, stamp, forecast)
                    if reason:
                        raise ValueError(reason)
                    if utc(stamp) < utc(doc['publishedUtc']):
                        raise ValueError('PAPER_CLOCK_MOVED_BACKWARDS')
                delivered = _commit(doc, family=family, precommit=precommit)
                existing[doc['supplementId']] = Path(delivered['exchangeDirectory'])
                item.update(disposition='PUBLISHED', **delivered)
        except Exception as exc:
            item.update(disposition='FAILED_CLOSED', reason=str(exc), errorType=type(exc).__name__)
            result['exitCode'] = 1
        finally:
            result['games'].append(item)
    result.update(completedAtUtc=clock(), publishedCount=sum(g['disposition'] == 'PUBLISHED' for g in result['games']),
        reusedCount=sum(g['disposition'] == 'REUSED_IMMUTABLE' for g in result['games']))
    result['receipt'] = object_json(Path(output_root) / 'receipts', result)
    return result
