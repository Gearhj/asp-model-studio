"""Consume the single AISP pregame sealer, privately, under the unchanged frozen protocol.

This is an ingestion/assessment runner, not an acquisition or forecast owner.
Only complete hash-bound pregame seals enter the archive. Original seals never
change; later validation and scheduled assessments carry their actual clocks.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re

from mlb_v18_market_storage import (PROTOCOL_SHA, RULE_SHA, SCHEMA_SHA, RetainedRefs, encode,
    file_ref, load_ledger, now_utc, schema_errors, sha, stamp, write_once, write_pointer)
from mlb_v18_market_producer_audit import audit_producer
from mlb_v18_market_admission import validate_packet

RUNTIME = Path(r'C:\Users\james\asp-model-studio')
OUTPUT = RUNTIME / 'outputs/mlb-v18-market-prospective-v1'
CONSUMER = RUNTIME.parent / 'asp-model-exchange/mlb-v18-market-prospective-v1/consumer-packets'
CODE = Path(__file__).resolve().parent
CODE_NAMES = ['run_mlb_v18_market_private_v1.py', 'mlb_v18_market_storage.py',
              'mlb_v18_market_producer_audit.py', 'mlb_v18_market_admission.py',
              'mlb_v18_market_assessment.py']
FORBIDDEN = {'outcome', 'outcomes', 'home_score', 'away_score', 'final_score', 'final_home_score',
             'final_away_score', 'profit_loss', 'pnl', 'settled_at', 'settlement_result', 'winner'}


def no_outcomes(value):
    if isinstance(value, dict):
        if FORBIDDEN.intersection(k.lower() for k in value):
            raise ValueError('OUTCOME_FIELD_IN_PREGAME_EXPORT')
        for child in value.values():
            no_outcomes(child)
    elif isinstance(value, list):
        for child in value:
            no_outcomes(child)


def safe_key(key):
    if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', key):
        raise ValueError('UNSAFE_EPISODE_KEY')
    return key


def read_protocol(output):
    frozen = json.loads((output / 'FROZEN.json').read_bytes())
    if frozen.get('protocolSha256') != PROTOCOL_SHA:
        raise ValueError('FROZEN_PROTOCOL_CHANGED')
    loaded = {}
    for key, expected in [('protocol', PROTOCOL_SHA), ('rules', RULE_SHA), ('packetSchema', SCHEMA_SHA)]:
        data = Path(frozen[key]['path']).read_bytes()
        if sha(data) != expected or len(data) != frozen[key]['bytes']:
            raise ValueError('FROZEN_DOCUMENT_CHANGED:' + key)
        loaded[key] = json.loads(data) if key != 'rules' else data
    return loaded['protocol'], loaded['packetSchema']


def check_bindings(output):
    binding = json.loads((output / 'RUNNER_FROZEN.json').read_bytes())
    if binding['protocolSha256'] != PROTOCOL_SHA:
        raise ValueError('RUNNER_PROTOCOL_BINDING_MISMATCH')
    for item in binding['code']:
        path = CODE / Path(item['path']).name
        physical = file_ref(path)
        if physical['sha256'] != item['sha256'] or physical['bytes'] != item['bytes']:
            raise ValueError('RUNNER_CODE_BINDING_CHANGED:' + path.name)
    if set(Path(r['path']).name for r in binding['code']) != set(CODE_NAMES):
        raise ValueError('RUNNER_CODE_BINDING_INCOMPLETE')
    return binding


def quarantine_gate(game, ledger):
    def flatten(value):
        if isinstance(value, dict):
            return {s for v in value.values() for s in flatten(v)}
        if isinstance(value, (list, tuple)):
            return {s for v in value for s in flatten(v)}
        return {str(value)} if value is not None else set()
    aliases = {str(game.get('canonicalGameId'))}
    aliases.update(flatten(game.get('sourceGameIds', {})))
    aliases.update(flatten(game.get('aliases', [])))
    denied = {str(row[k]) for row in ledger['games'] for k in ('canonicalGameId', 'mlbamGamePk') if k in row}
    denied |= {'mlbam:game:' + str(row['mlbamGamePk']) for row in ledger['games']}
    if aliases.intersection(denied):
        raise ValueError('PERMANENT_WHOLE_GAME_QUARANTINE')
    date = stamp(game['scheduledStartUtc']).date().isoformat()
    if not '2026-09-19' <= date <= '2026-09-28':
        raise ValueError('TARGET_OUTSIDE_FUTURE_PILOT')


def publication_candidates(runtime, game_id, anchor):
    """Metadata only, fixed filename; never inspect old source/outcome payloads."""
    candidates = []
    root = runtime / 'outputs/mlb-v18-unattended-v1/objects/sha256'
    for path in root.glob('*/incremental-publication.json'):
        data = path.read_bytes()
        if sha(data) != path.parent.name:
            raise ValueError('INCREMENTAL_PUBLICATION_RECEIPT_HASH_MISMATCH')
        row = json.loads(data)
        exposed = row.get('packageExposedAtUtc')
        if row.get('gameId') != game_id or not row.get('completedObjectIncluded') or not exposed:
            continue
        if stamp(exposed) <= anchor and row.get('selectedObjectSha256') == row.get('objectSha256'):
            candidates.append((stamp(exposed), 'mlb-v18-daily-' + row['objectSha256'], row, file_ref(path)))
    return sorted(candidates, key=lambda x: (-x[0].timestamp(), x[1]))


def process_seal(seal, seal_ref, universe, refs, protocol, schema, binding, now, runtime):
    key = safe_key(seal['episodeKey'])
    path = refs.consumer / (key + '.json')
    data = path.read_bytes()
    if sha(data) != seal['packetSha256'] or len(data) != seal['packetBytes']:
        raise ValueError('SEALED_PACKET_HASH_MISMATCH')
    packet = json.loads(data)
    no_outcomes(packet)
    errors = schema_errors(packet, schema)
    if errors:
        raise ValueError('PACKET_SCHEMA_INVALID:' + ';'.join(errors[:5]))
    if packet['episodeKey'] != key:
        raise ValueError('EPISODE_IDENTITY_MISMATCH')
    # Metadata quarantine and future date gate precede any producer or source access.
    qref = file_ref(runtime / 'server/artifacts/governance/mlb-final-oot-quarantine-v1.json')
    quarantine_gate(packet['game'], refs(qref))
    first = universe.get(key)
    if not first:
        raise ValueError('NO_PREGAME_UNIVERSE_RECORD')
    if packet['game']['canonicalGameId'] != first['canonicalGameId'] or stamp(packet['game']['scheduledStartUtc']) != stamp(first['scheduledStartUtc']):
        raise ValueError('UNIVERSE_PACKET_IDENTITY_MISMATCH')
    if stamp(first['firstSeenBySealerUtc']) > stamp(packet['anchor']['atUtc'] or packet['anchor']['researchLockUtc']):
        raise ValueError('UNIVERSE_FIRST_SEEN_AFTER_ANCHOR')
    evidence_name = seal['evidenceFile']
    if Path(evidence_name).name != evidence_name or not evidence_name.startswith(key + '.evidence-'):
        raise ValueError('UNSAFE_EVIDENCE_FILE_NAME')
    evidence_path = refs.consumer / evidence_name
    evidence_bytes = evidence_path.read_bytes()
    if sha(evidence_bytes) != seal['evidenceSha256']:
        raise ValueError('SEALED_EVIDENCE_HASH_MISMATCH')
    evidence = json.loads(evidence_bytes)
    no_outcomes(evidence)
    if evidence.get('mode') != 'PROSPECTIVE_SEAL' or evidence.get('episodeKey') != key or evidence.get('protocolSha256') != PROTOCOL_SHA:
        raise ValueError('NONPROSPECTIVE_OR_FOREIGN_EVIDENCE')
    sidecar = (refs.consumer / (key + '.sha256')).read_text('ascii').splitlines()
    if sidecar != [seal['packetSha256'] + '  ' + key + '.json', seal['evidenceSha256'] + '  ' + evidence_name]:
        raise ValueError('SEAL_SIDECAR_MISMATCH')
    refs.phase_metadata = evidence.get('files', {}).get('phaseEvidence')
    context = {'sealCompletedAtUtc': seal['writtenAtUtc'], 'sealLedgerRef': seal_ref,
               'packetSha256': seal['packetSha256'], 'readinessAtUtc': binding['readyAtUtc'],
               'authorityExpiresAtUtc': binding['authorityExpiresAtUtc'], 'quarantineRef': qref,
               'evidenceDoc': evidence, 'verifiedEvidence': evidence,
               'earliestResearchLockUtc': min((u['researchLockUtc'] for u in universe.values()
                    if u['canonicalGameId'] == first['canonicalGameId']), key=stamp),
               'researchForecastSelectionVerified': False}
    audit, audit_error = None, None
    try:
        audit = audit_producer(packet, refs, runtime)
        if packet['forecast'] and packet['anchor']['atUtc']:
            pubs = publication_candidates(runtime, packet['game']['canonicalGameId'], stamp(packet['anchor']['atUtc']))
            own = [p for p in pubs if p[1] == packet['forecast']['forecastIdentity'] and
                   p[0] >= stamp(packet['forecast']['publicationCompletedAtUtc'])]
            if own and audit:
                # Earliest proven exposure of this exact object, not a later cumulative copy.
                earliest = min(own, key=lambda p: p[0])
                if not audit['publicationCompletedAtUtc'] or earliest[0] < stamp(audit['publicationCompletedAtUtc']):
                    audit['publicationCompletedAtUtc'] = earliest[2]['packageExposedAtUtc']
                    audit['publicationAvailabilityBasis'] = 'RECORDED_ATOMIC_EXCHANGE_EXPOSURE'
                    audit['physicalProducerRefs'].append(earliest[3])
                audit['deploymentAttestation'] = earliest[2].get('deploymentIdentity')
            context['researchForecastSelectionVerified'] = bool(pubs and pubs[0][1] == packet['forecast']['forecastIdentity'])
            context['researchForecastSelectionCandidates'] = [p[3] for p in pubs]
    except (ValueError, KeyError, TypeError, OSError) as exc:
        audit_error = str(exc)
        if 'HASH_MISMATCH' in audit_error or 'PHYSICAL_REFERENCE_MISMATCH' in audit_error:
            raise
    enriched = deepcopy(protocol)
    enriched['protocolSha256'] = PROTOCOL_SHA
    enriched['_admissionContext'] = context
    result = validate_packet(packet, enriched, refs, now, forecast_audit=audit)
    if audit_error:
        result['producerAuditError'] = audit_error
    result.update({'packetSha256': seal['packetSha256'], 'episodeKey': key,
                   'gameId': packet['game']['canonicalGameId'], 'sourceGameIds': packet['game']['sourceGameIds'],
                   'homeId': packet['game']['homeId'], 'awayId': packet['game']['awayId'],
                   'scheduledStartUtc': packet['game']['scheduledStartUtc'], 'researchLockUtc': packet['anchor']['researchLockUtc'],
                   'originalSealedAtUtc': packet['sealedAtUtc'], 'sealCompletedAtUtc': seal['writtenAtUtc'],
                   'validatedAtUtc': now.isoformat(), 'selectionStatus': packet['selection']['statusAtResearchLock'],
                   'anchorKind': packet['anchor']['kind'], 'pHome': (packet['forecast'] or {}).get('pHome'),
                   'consumerDeclaredEligibility': packet['eligibility'], 'consumerDeclaredMarketStatus': packet['market']['status'],
                   'originalPacketRef': file_ref(path), 'originalEvidenceRef': file_ref(evidence_path),
                   'sealLedgerRef': seal_ref, 'runnerProtocolSha256': PROTOCOL_SHA})
    result['producerAudit'] = audit
    result['referenceRecoveries'] = list(refs.recoveries)
    return packet, evidence, result, data, evidence_bytes


def records_for_assessment(output):
    records = []
    for path in (output / 'private-collection/episodes').glob('*.json'):
        row = json.loads(path.read_bytes())
        receipt_path = output / 'private-collection/sealed' / row['packetSha256'] / 'admission-ref.json'
        receipt = json.loads(receipt_path.read_bytes())
        if any(file_ref(path)[key] != receipt[key] for key in ('sha256', 'bytes')):
            raise ValueError('PRIVATE_ADMISSION_RECEIPT_HASH_MISMATCH')
        audit = row.get('producerAudit') or {}
        row['scorePairs'] = audit.get('scorePairs')
        records.append(row)
    return records


def apply_schedule_dispositions(records, universe):
    """Keep original packets; a changed start discovered after lock excludes that episode."""
    result = deepcopy(records)
    for row in result:
        changes = [u for u in universe.values() if u['canonicalGameId'] == row['gameId'] and
                   stamp(u['scheduledStartUtc']) != stamp(row['scheduledStartUtc']) and
                   stamp(u['firstSeenBySealerUtc']) > stamp(row['researchLockUtc'])]
        if changes:
            row['originalForecastEligible'] = row['forecastEligible']
            row['forecastEligible'] = False
            row['enrollmentEligible'] = False
            row['pairedMetricEligible'] = False
            row['scheduleDisposition'] = 'EXCLUDED_POST_LOCK_SCHEDULE_CHANGE_ORIGINAL_PACKET_PRESERVED'
            row['scheduleChangeEvidence'] = changes
            row['reasons'] = row.get('reasons', []) + [row['scheduleDisposition']]
            row['reasonCodes'] = row['reasons']
    return result


def finish_private_index(obj, destination, packet_sha):
    """Expose an admission only after its immutable byte binding is complete.

    This also completes an interrupted index write using the ORIGINAL validated
    receipt, without recomputing evidence or changing any saved clock.
    """
    data = (obj / 'admission.json').read_bytes()
    row = json.loads(data)
    if row.get('packetSha256') != packet_sha or sha((obj / 'packet.json').read_bytes()) != packet_sha:
        raise ValueError('PRIVATE_ARCHIVE_PACKET_HASH_MISMATCH')
    seal = json.loads((obj / 'seal-receipt.json').read_bytes())
    if sha((obj / 'evidence.json').read_bytes()) != seal['evidenceSha256']:
        raise ValueError('PRIVATE_ARCHIVE_EVIDENCE_HASH_MISMATCH')
    write_once(obj / 'admission-ref.json', encode({'path': str(destination.resolve()), 'sha256': sha(data), 'bytes': len(data)}))
    write_once(destination, data)


def scheduled_assessments(output, protocol, now, records):
    from mlb_v18_market_assessment import assess
    made = []
    for logical in protocol['assessmentsUtc']:
        if stamp(logical) > now:
            continue
        key = stamp(logical).strftime('%Y%m%dT%H%M%SZ')
        target = output / 'private-collection/assessments' / (key + '.json')
        if target.exists():
            continue
        # Only per-game files for already admitted future predictions are enumerated.
        outcomes = []
        incoming = CONSUMER.parent / 'consumer-outcomes'
        for row in records:
            if not row.get('forecastEligible'):
                continue
            quarantine_gate({'canonicalGameId': row['gameId'], 'sourceGameIds': row['sourceGameIds'],
                             'scheduledStartUtc': row['scheduledStartUtc']},
                            json.loads((RUNTIME / 'server/artifacts/governance/mlb-final-oot-quarantine-v1.json').read_bytes()))
            for path in (incoming / safe_key(row['gameId'])).glob('*.json'):
                data = path.read_bytes()
                if path.stem != sha(data):
                    raise ValueError('OUTCOME_REVISION_FILE_HASH_MISMATCH')
                item = json.loads(data)
                if item.get('recordType') != 'MLB_V18_MARKET_ADMITTED_OUTCOME_V1' or item.get('gameId') != row['gameId']:
                    raise ValueError('OUTCOME_IDENTITY_MISMATCH')
                if item.get('homeId') != row['homeId'] or item.get('awayId') != row['awayId'] or item.get('sourceGameIds') != row['sourceGameIds']:
                    raise ValueError('OUTCOME_ORIENTATION_OR_SOURCE_ALIAS_MISMATCH')
                if item.get('consumerAdmissionVerified') is not True or not item.get('sourceRevisionIdentity'):
                    raise ValueError('OUTCOME_ADMISSION_NOT_ESTABLISHED')
                if stamp(item['admittedAtUtc']) > now or (item['status'] in {'DECISIVE', 'TIE'} and
                        stamp(item['finalAtUtc']) < stamp(row['scheduledStartUtc'])):
                    raise ValueError('OUTCOME_CHRONOLOGY_INVALID')
                if stamp(item['sourceCapturedAtUtc']) > stamp('2026-10-01T00:00:00Z'):
                    raise ValueError('OUTCOME_SOURCE_CAPTURE_AFTER_EXISTING_AUTHORITY')
                item['sourceRef'] = file_ref(path)
                outcomes.append(item)
        result = assess(records, outcomes, logical, now.isoformat())
        result['outcomeSourceStatus'] = 'ADMITTED_CONSUMER_REVISIONS' if outcomes else 'NO_ADMITTED_OUTCOME_EXPORT_AVAILABLE'
        result['protocolSha256'] = PROTOCOL_SHA
        write_once(target, encode(result))
        made.append(file_ref(target))
    return made


def run(output=OUTPUT, consumer=CONSUMER, runtime=RUNTIME):
    now = datetime.now(timezone.utc)
    protocol, schema = read_protocol(output)
    binding = check_bindings(output)
    private = output / 'private-collection'
    private.mkdir(parents=True, exist_ok=True)
    if (private / 'STOP.json').exists():
        raise ValueError('PRIVATE_ADMISSION_STOP_PRESENT')
    lock = private / 'runner.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {'status': 'BUSY_PRIVATE_RUNNER_LOCK_NO_FORCE', 'asOfUtc': now.isoformat()}
    try:
        with os.fdopen(descriptor, 'w') as handle:
            handle.write(json.dumps({'pid': os.getpid(), 'startedAtUtc': now.isoformat()}))
        ledger, prefix = load_ledger(consumer / 'attempt-ledger.jsonl')
        if any(row['kind'] == 'SYSTEMIC_STOP' for row, _ in ledger):
            raise ValueError('CONSUMER_REPORTED_SYSTEMIC_PROVENANCE_STOP')
        prior_path = private / 'LEDGER_PREFIX.json'
        if prior_path.exists():
            prior = json.loads(prior_path.read_bytes())
            if sha(prefix[:prior['bytes']]) != prior['sha256'] or len(prefix) < prior['bytes']:
                raise ValueError('CONSUMER_LEDGER_PREVIOUS_PREFIX_CHANGED')
        write_once(private / 'ledger-snapshots' / (sha(prefix) + '.jsonl'), prefix)
        write_pointer(prior_path, {'sha256': sha(prefix), 'bytes': len(prefix), 'lines': len(ledger), 'checkedAtUtc': now.isoformat()})
        refs = RetainedRefs(consumer, runtime, ledger)
        universe = {row['episodeKey']: row for row, _ in ledger if row['kind'] == 'UNIVERSE_FIRST_SEEN'}
        group = defaultdict(list)
        for row in universe.values():
            group[row['canonicalGameId']].append(row)
        seals, new, rejected = {}, [], []
        for row, ref in ledger:
            if row['kind'] != 'SEALED':
                continue
            key = safe_key(row['episodeKey'])
            if key in seals and seals[key]['packetSha256'] != row['packetSha256']:
                raise ValueError('CONSUMER_DUPLICATE_SEAL_REPLACEMENT')
            seals[key] = row
            destination = private / 'episodes' / (key + '.json')
            obj = private / 'sealed' / row['packetSha256']
            rejection_path = private / 'rejected-episodes' / (key + '.json')
            if rejection_path.exists():
                prior = json.loads(rejection_path.read_bytes())
                if prior['packetSha256'] != row['packetSha256']:
                    raise ValueError('CONSUMER_DUPLICATE_SEAL_REPLACEMENT')
                continue
            if destination.exists():
                saved = json.loads(destination.read_bytes())
                if saved['packetSha256'] != row['packetSha256'] or sha((consumer / (key + '.json')).read_bytes()) != saved['packetSha256']:
                    raise ValueError('PREVIOUSLY_SEALED_PACKET_REPLACED')
                continue
            if (obj / 'admission.json').exists():
                if sha((consumer / (key + '.json')).read_bytes()) != row['packetSha256']:
                    raise ValueError('PREVIOUSLY_SEALED_PACKET_REPLACED')
                finish_private_index(obj, destination, row['packetSha256'])
                new.append(key)
                continue
            try:
                earliest = min(stamp(u['researchLockUtc']) for u in group[universe[key]['canonicalGameId']])
                if stamp(universe[key]['researchLockUtc']) != earliest:
                    raise ValueError('LATER_REVISION_REQUIRES_EXPLICIT_POSTPONEMENT_EVIDENCE')
                packet, evidence, result, raw_packet, raw_evidence = process_seal(row, ref, universe, refs, protocol, schema, binding, now, runtime)
                if any(reason.startswith('FROZEN_MODEL_') and reason.endswith('_MISMATCH') for reason in result.get('reasons', [])):
                    raise ValueError('SYSTEMIC_CHANGED_NUMERICAL_MODEL_RECIPE')
                write_once(obj / 'packet.json', raw_packet)
                write_once(obj / 'evidence.json', raw_evidence)
                write_once(obj / 'seal-receipt.json', encode(row))
                write_once(obj / 'admission.json', encode(result))
                finish_private_index(obj, destination, row['packetSha256'])
                new.append(key)
            except (ValueError, KeyError, TypeError, OSError) as exc:
                failure = {'episodeKey': key, 'packetSha256': row['packetSha256'], 'validatedAtUtc': now.isoformat(),
                           'status': 'EXCLUDED_NO_ENROLLMENT', 'reason': str(exc), 'sealLedgerRef': ref}
                write_once(rejection_path, encode(failure))
                rejected.append(failure)
                if any(word in str(exc) for word in ('HASH_MISMATCH', 'REPLACED', 'NONPROSPECTIVE_OR_FOREIGN', 'OUTCOME_FIELD', 'SYSTEMIC_CHANGED')):
                    raise
        records = apply_schedule_dispositions(records_for_assessment(output), universe)
        assessments = scheduled_assessments(output, protocol, now, records)
        pending = []
        for key, row in universe.items():
            if key in seals:
                continue
            earliest = min(stamp(u['researchLockUtc']) for u in group[row['canonicalGameId']])
            status = ('SUPERSEDED_LATER_LOCK_EPISODE' if stamp(row['researchLockUtc']) > earliest else
                      'MISSING_SEAL_DEADLINE_PASSED' if now > stamp(row['sealDeadlineUtc']) else 'AWAITING_RESEARCH_LOCK_OR_SEAL')
            pending.append({'episodeKey': key, 'gameId': row['canonicalGameId'], 'status': status,
                            'researchLockUtc': row['researchLockUtc'], 'sealDeadlineUtc': row['sealDeadlineUtc']})
        coverage = {'universeEpisodes': len(universe), 'distinctUniverseGames': len(group), 'consumerSealedPackets': len(seals),
                    'validatedPackets': len(records), 'forecastEligible': sum(bool(r.get('forecastEligible')) for r in records),
                    'priceEvaluable': sum(bool(r.get('forecastEligible') and r.get('priceEvaluable')) for r in records),
                    'unpricedEligibleForecasts': sum(bool(r.get('forecastEligible') and not r.get('priceEvaluable')) for r in records),
                    'selectionAscertained': sum(bool(r.get('selectionAscertained')) for r in records),
                    'consumerLedgerEventCounts': dict(Counter(r['kind'] for r, _ in ledger)),
                    'rejectedPacketIdentities': len(list((private / 'rejected-episodes').glob('*.json'))),
                    'pendingStatusCounts': dict(Counter(r['status'] for r in pending)),
                    'validationReasonCounts': dict(Counter(reason for r in records for reason in r.get('reasons', [])))}
        status = {'schema': 'MLB_V18_MARKET_PRIVATE_COLLECTION_STATUS_V1', 'asOfUtc': now.isoformat(),
                  'protocolSha256': PROTOCOL_SHA, 'runnerBindingRef': file_ref(output / 'RUNNER_FROZEN.json'),
                  'status': 'OPERATING_AWAITING_FIRST_GENUINE_SEAL' if not records else 'OPERATING_PRIVATE_COLLECTION',
                  'coverage': coverage, 'newlyValidatedEpisodes': new, 'newRejections': rejected,
                  'pendingEpisodes': pending, 'assessmentsCreated': assessments,
                  'nextAssessmentUtc': next((s for s in protocol['assessmentsUtc'] if stamp(s) > now), None),
                  'consumerLedgerPrefix': {'sha256': sha(prefix), 'bytes': len(prefix), 'lines': len(ledger)},
                  'sourceAcquisitionCalls': 0, 'productionChanges': False,
                  'priceCoverageConclusion': 'CURRENT_RETAINED_EXPORTS_LACK_REQUIRED_LEG_CLOCKS_AND_CONVENTIONS_EXPECT_NEAR_ZERO_PAIRS',
                  'sealOwner': 'AISP asp-rx-v18-market-pilot-seal (existing every-two-minute research export)',
                  'privateValidationOwner': 'Model Studio existing thread heartbeat, exclusive private runner.lock',
                  'limitations': ['Universe metadata is not enrollment.', 'Fixture checks are never prospective captures.',
                                  'Consumer-declared FRESH_PAIRED is independently checked; missing proofs stay UNPRICED.',
                                  'No new model, quote purchase, policy change or formal advancement authority.']}
        snapshot = private / 'runs' / (sha(encode(status)) + '.json')
        write_once(snapshot, encode(status))
        status['runReceipt'] = file_ref(snapshot)
        write_pointer(output / 'COLLECTION_STATUS.json', status)
        lines = ['# Private V18 fresh-market collection coverage', '', 'As of ' + now.isoformat() + '.', '',
                 'The frozen protocol is unchanged. This is operational coverage, not an interim performance assessment.', '',
                 '| Population | Count |', '|---|---:|']
        lines += ['| ' + key + ' | ' + str(coverage[key]) + ' |' for key in (
            'universeEpisodes', 'distinctUniverseGames', 'consumerSealedPackets', 'validatedPackets',
            'forecastEligible', 'priceEvaluable', 'unpricedEligibleForecasts', 'selectionAscertained', 'rejectedPacketIdentities')]
        lines += ['', 'Fixtures are excluded. Zero sealed packets means no prospective enrollment yet.', '',
                  'Current retained timing evidence: 20/90 historical timing candidates, 0/60 since September 14. '
                  'Those exports lack required per-leg clocks and established pitcher/action conventions; '
                  'none is a fully eligible protocol price. Expected coverage remains approximately zero under current captures.', '',
                  'Next scheduled assessment: ' + str(status['nextAssessmentUtc']) + '.', '',
                  '| Episode | State | Lock UTC |', '|---|---|---|']
        lines += ['| ' + p['episodeKey'] + ' | ' + p['status'] + ' | ' + p['researchLockUtc'] + ' |' for p in pending]
        report = private / 'COVERAGE.md'
        temporary = report.with_name('COVERAGE.md.' + str(os.getpid()) + '.pending')
        temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.replace(temporary, report)
        return status
    except Exception as exc:
        failure = {'atUtc': now_utc(), 'status': 'STOPPED_PRIVATE_ADMISSION_ONLY', 'reason': str(exc),
                   'productionAndOtherCollectorsUnchanged': True}
        write_once(private / 'STOP.json', encode(failure))
        raise
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze-runner', action='store_true', help='Write the once-only private implementation binding after review; not a new protocol')
    args = parser.parse_args()
    if args.freeze_runner:
        read_protocol(OUTPUT)
        binding = {'schema': 'MLB_V18_MARKET_PRIVATE_RUNNER_BINDING_V1', 'protocolSha256': PROTOCOL_SHA,
                   'readyAtUtc': now_utc(), 'authorityExpiresAtUtc': '2026-10-01T00:00:00Z',
                   'collectionClosesAtUtc': '2026-09-28T04:00:00Z',
                   'code': [file_ref(CODE / name) for name in CODE_NAMES],
                   'consumerAcknowledgement': file_ref(RUNTIME.parent / 'aisp-analysis/wagering-record-20260918/consumer-followup/EXPORTS_READY.md'),
                   'scope': 'PRIVATE_RESEARCH_VALIDATION_AND_SCHEDULED_REPORTS_ONLY; NO_ACQUISITION',
                   'pregameSealOwner': 'EXISTING_AISP_ASP_RX_V18_MARKET_PILOT_SEAL',
                   'validationSchedule': 'EXISTING_MODEL_STUDIO_HOURLY_THREAD_HEARTBEAT',
                   'syntheticFixturesAreEnrollment': False}
        write_once(OUTPUT / 'RUNNER_FROZEN.json', encode(binding))
        print(json.dumps({'status': 'PRIVATE_RUNNER_BOUND', 'binding': file_ref(OUTPUT / 'RUNNER_FROZEN.json')}))
    else:
        result = run()
        print(json.dumps({k: result.get(k) for k in ('status', 'asOfUtc', 'coverage', 'newlyValidatedEpisodes', 'newRejections', 'nextAssessmentUtc', 'runReceipt')}, indent=2))


if __name__ == '__main__':
    main()
