"""Recover only the exact forecast already named by the consumer's pregame seal.

No alternate forecast, final score, source history, simulation or fitted model load.
The result is a later verification receipt, never a replacement pregame packet.
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from mlb_v18_market_storage import encode, sha, file_ref, stamp


def compact_sha(value):
    return sha(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                          allow_nan=False).encode())


def audit_producer(packet, refs, runtime):
    pf = packet['forecast']
    if not pf:
        return None
    identity = pf['forecastIdentity']
    match = re.fullmatch(r'mlb-v18-daily-([0-9a-f]{64})', identity)
    if not match:
        raise ValueError('FORECAST_IDENTITY_NOT_CONTENT_ADDRESSED')
    digest = match[1]
    root = Path(runtime).resolve() / 'outputs/mlb-v18-current-state-pipeline-v1/objects/sha256'
    directory = root / digest
    # Original consumer content address must agree, even when file access was absent.
    original = refs(pf['objectRef'])
    if original.get('objectSha256') != digest:
        raise ValueError('CONSUMER_OBJECT_REFERENCE_DISAGREES')
    manifest_ref = file_ref(directory / 'manifest.json')
    manifest = refs(manifest_ref)
    body = {k: v for k, v in manifest.items() if k not in {'objectId', 'objectSha256'}}
    if compact_sha(body) != digest or manifest.get('objectSha256') != digest:
        raise ValueError('PRODUCER_MANIFEST_LOGICAL_HASH_MISMATCH')
    if manifest.get('gameId') != packet['game']['canonicalGameId']:
        raise ValueError('PRODUCER_MANIFEST_GAME_MISMATCH')
    required = {'forecast.json', 'execution-inputs.json', 'pregame-evidence.json'}
    allowed = required | {'representative-path.json'}
    members = {}
    for item in manifest['artifacts']:
        name = item['relativePath']
        if name not in allowed or name in members:
            raise ValueError('PRODUCER_MANIFEST_UNEXPECTED_MEMBER')
        members[name] = {**item, 'path': str(directory / name)}
    if not required <= members.keys():
        raise ValueError('PRODUCER_REQUIRED_MEMBER_ABSENT')
    f = refs(members['forecast.json'])
    if f['gameId'] != packet['game']['canonicalGameId'] or stamp(f['scheduledStart']) != stamp(packet['game']['scheduledStartUtc']):
        raise ValueError('PRODUCER_GAME_OR_SCHEDULE_MISMATCH')
    # Must be a new study date before any prediction input children are loaded.
    if not ('2026-09-19' <= stamp(f['scheduledStart']).date().isoformat() <= '2026-09-28'):
        raise ValueError('PRODUCER_TARGET_OUTSIDE_FUTURE_STUDY')
    e, p = refs(members['execution-inputs.json']), refs(members['pregame-evidence.json'])
    if p.get('game', {}).get('game_id') != f['gameId']:
        raise ValueError('PRODUCER_INPUT_GAME_MISMATCH')
    if f.get('snapshotContentSha256') != p.get('contentSha256'):
        raise ValueError('PRODUCER_INPUT_CONTENT_BINDING_MISMATCH')
    input_note = refs(pf['inputSnapshotRef'])
    snapshot_sha = input_note.get('snapshotContentSha256', input_note.get('contentSha256'))
    if snapshot_sha != f.get('snapshotContentSha256'):
        raise ValueError('CONSUMER_INPUT_CONTENT_BINDING_MISMATCH')
    for k, original_value in [('createdAtUtc', f['forecastCreatedAt']), ('sourceCutoffUtc', f['capturedAt'])]:
        if stamp(pf[k]) != stamp(original_value):
            raise ValueError('CONSUMER_PRODUCER_CLOCK_MISMATCH:' + k)
    if pf['seed'] != f['simulation']['seed']:
        raise ValueError('CONSUMER_PRODUCER_SEED_MISMATCH')
    for key, other in [('pHome', 'homeWin'), ('pAway', 'awayWin')]:
        if abs(float(pf[key]) - float(f['probabilities'][other])) > 1e-12:
            raise ValueError('CONSUMER_PRODUCER_PROBABILITY_MISMATCH')
    if abs(float(pf['samplingError']['value']) - float(f['monteCarloUncertainty']['homeWinProbabilityStandardError'])) > 1e-12:
        raise ValueError('CONSUMER_PRODUCER_MCSE_MISMATCH')
    captured = stamp(f['capturedAt'])
    start = stamp(f['scheduledStart'])
    max_age = timedelta(minutes=30) if start - captured <= timedelta(hours=4) else timedelta(hours=24)
    eligibility = p.get('game', {}).get('status', '').upper() in {'SCHEDULED', 'PREGAME', 'PRE_GAME'}
    eligibility &= captured + timedelta(minutes=5) < start
    sides = p.get('sides', [])
    eligibility &= len(sides) == 2 and {s.get('side') for s in sides} == {'HOME', 'AWAY'}
    clocks = []
    for side in sides:
        starter, authority = side.get('starter', {}), side.get('lineupAuthority', {})
        lineup = side.get('lineup', [])
        eligibility &= bool(starter.get('mlbamId')) and len(lineup) == 9
        eligibility &= authority.get('status') == 'CONFIRMED'
        eligibility &= str(side.get('team', {}).get('uuid')) == str(packet['game'][side['side'].lower() + 'Id'])
        eligibility &= [int(r.get('batting_order', 0)) for r in lineup] == list(range(1, 10))
        eligibility &= all(r.get('mlbam') for r in lineup)
        for kind, evidence in [('starter', starter), ('lineup', authority)]:
            for clock in ['availableAsOf', 'observedAt', 'ingestedAt']:
                value = evidence.get(clock)
                eligibility &= bool(value) and stamp(value) <= captured
                clocks.append({'side': side['side'], 'kind': kind, 'clock': clock, 'atUtc': value})
            eligibility &= bool(evidence.get('observedAt')) and captured - stamp(evidence['observedAt']) <= max_age
        roster = [row for row in p.get('currentRoster', []) if row.get('team_id') == side.get('team', {}).get('uuid')
                  and row.get('active_roster') is True and row.get('position') in {'P', 'SP', 'RP'}]
        eligibility &= bool(roster) and all(row.get('observed_at') and
            timedelta(0) <= captured - stamp(row['observed_at']) <= timedelta(hours=30) for row in roster)
    m, pop, sim = e['modelIdentity'], e['population'], f['simulation']
    if e.get('featureSnapshot'):
        feature = refs(e['featureSnapshot'])
        composition = feature.get('composition', {})
        eligibility &= not composition.get('blockers')
    # Hash the two explicitly bound executable files without deserializing either.
    physical = [manifest_ref, *[members[k] for k in sorted(required)]]
    for key in ['paArtifact', 'transitionArtifact']:
        artifact = m[key]
        target = Path(artifact['path']).resolve()
        parent_root = Path(runtime).resolve() / 'outputs/mlb-v18-whole-game-challenger/sha256' / m['parentBundleSha256'] / 'executable'
        if target.parent != parent_root or target.suffix not in {'.joblib', '.json'}:
            raise ValueError('MODEL_ARTIFACT_OUTSIDE_BOUND_EXECUTABLE')
        verified = file_ref(target)
        if any(verified[k] != artifact[k] for k in ['sha256', 'bytes']):
            raise ValueError('MODEL_ARTIFACT_HASH_MISMATCH')
        physical.append(verified)
    if sim.get('deterministicReplay') is not True or e.get('refits') != 0:
        eligibility = False
    model = {'engine': 'MLB_V18_WHOLE_GAME', 'paSha256': m['paArtifact']['sha256'],
             'transitionSha256': m['transitionArtifact']['sha256'], 'parentBundleSha256': m['parentBundleSha256'],
             'treatmentManifestSha256': m['treatmentManifestSha256'], 'calibration': 'RETAIN_RAW_V18'}
    # Raw calibration is established by the original score frequency, not a current model setting.
    home, away = pop['homeRuns'], pop['awayRuns']
    if len(home) != 5000 or len(away) != 5000 or any(h == a for h, a in zip(home, away)):
        eligibility = False
    else:
        eligibility &= abs(sum(h > a for h, a in zip(home, away)) / 5000 - float(pf['pHome'])) <= 1e-12
    if any(len(row) != 246 for row in e.get('rawTemplates', [])) or not e.get('rawTemplates'):
        eligibility = False
    if any(len(row) != 273 for row in e.get('treatedRows', [])) or not e.get('treatedRows'):
        eligibility = False
    # Consumer completion is a conservative availability bound. Never call generatedAt a rename.
    publication_bound = None
    if pf.get('importReceiptRef'):
        receipt = refs(pf['importReceiptRef'])
        bundle = refs(pf['operationalEvidence']['bundleRef'])
        if receipt.get('names_handoff_sha256') == bundle.get('bundle_sha256_handoff') and receipt.get('completed_at'):
            publication_bound = receipt['completed_at']
            if stamp(publication_bound) < stamp(pf['publicationCompletedAtUtc']):
                raise ValueError('IMPORT_COMPLETION_PRECEDES_HANDOFF')
    return {'forecastIdentity': identity, 'objectRef': pf['objectRef'], 'inputSnapshotRef': pf['inputSnapshotRef'],
            'modelIdentity': model, 'createdAtUtc': f['forecastCreatedAt'], 'sourceCutoffUtc': f['capturedAt'],
            'seed': sim['seed'], 'scorePairs': list(map(list, zip(home, away))),
            'rawInputCount': m['rawInputCount'], 'treatedInputCount': m['treatedInputCount'],
            'illegalStateCount': sim['illegalStateCount'], 'nonterminationCount': sim['nonterminationCount'],
            'sourceEligibilityVerified': bool(eligibility), 'sourceClockEvidence': clocks,
            'publicationCompletedAtUtc': publication_bound,
            'publicationAvailabilityBasis': 'COMPLETED_CONSUMER_IMPORT_UPPER_BOUND' if publication_bound else 'UNPROVEN_GENERATION_IS_NOT_EXPOSURE',
            'physicalProducerRefs': physical, 'sourcePopulationRef': {**members['execution-inputs.json'], 'locator': '/population'},
            'deploymentAttestation': pf.get('deploymentAttestation'),
            'recoveryMeaning': 'VERIFIED_LATER_FROM_EXACT_PREGAME_SEALED_OBJECT_REFERENCE_NOT_A_NEW_FORECAST'}
