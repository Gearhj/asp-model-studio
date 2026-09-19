"""Private runner integration with synthetic temporary files only.

No fixture calls read_protocol, run, a freeze operation, a provider, a database,
or a real producer audit. The process_seal I/O and admission checks remain real.
"""
from copy import deepcopy
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path

import pytest

from scripts import mlb_v18_market_storage as storage
from test_mlb_v18_market_admission import _fixture


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('run_mlb_v18_market_private_v1')


def _ledger_bytes(records, newline=b'\n'):
    output, previous = b'', None
    for sequence, source in enumerate(records, 1):
        row = {**source, 'seq': sequence, 'prevLineSha256': previous,
               'protocolSha256': storage.PROTOCOL_SHA}
        raw = storage.encode(row).rstrip(b'\n')
        output += raw + newline
        previous = storage.sha(raw)
    return output


def test_ledger_line_hash_excludes_newline_and_incomplete_tail_is_ignored(tmp_path):
    ledger = tmp_path / 'attempt-ledger.jsonl'
    complete = _ledger_bytes([{'kind': 'UNIVERSE_FIRST_SEEN'}, {'kind': 'SEAL_ATTEMPT'}], b'\r\n')
    ledger.write_bytes(complete + b'{"seq":3,"kind":"SEA')
    records, prefix = storage.load_ledger(ledger)
    assert len(records) == 2 and prefix == complete
    first = complete.splitlines()[0]
    assert records[0][1]['sha256'] == storage.sha(first)
    assert records[0][1]['bytes'] == len(first)
    assert records[1][0]['prevLineSha256'] == storage.sha(first)


def test_altered_prior_ledger_line_breaks_chain(tmp_path):
    ledger = tmp_path / 'attempt-ledger.jsonl'
    data = _ledger_bytes([{'kind': 'UNIVERSE_FIRST_SEEN'}, {'kind': 'SEAL_ATTEMPT'}])
    ledger.write_bytes(data.replace(b'UNIVERSE_FIRST_SEEN', b'ALTERED_FIRST_SEEN'))
    with pytest.raises(ValueError, match='CHAIN_MISMATCH'):
        storage.load_ledger(ledger)


def test_interrupted_private_index_reuses_original_validated_clock(tmp_path, runner):
    obj = tmp_path / 'sealed'
    obj.mkdir()
    packet = storage.encode({'label': 'SYNTHETIC_NOT_ENROLLMENT'})
    evidence = storage.encode({'mode': 'SYNTHETIC_FIXTURE'})
    digest = storage.sha(packet)
    original = {'packetSha256': digest, 'validatedAtUtc': '2026-09-19T20:10:00Z'}
    (obj / 'packet.json').write_bytes(packet)
    (obj / 'evidence.json').write_bytes(evidence)
    (obj / 'seal-receipt.json').write_bytes(storage.encode({'evidenceSha256': storage.sha(evidence)}))
    (obj / 'admission.json').write_bytes(storage.encode(original))
    destination = tmp_path / 'episodes' / 'synthetic.json'
    assert not destination.exists()
    runner.finish_private_index(obj, destination, digest)
    assert json.loads(destination.read_bytes()) == original
    assert json.loads((obj / 'admission-ref.json').read_bytes())['sha256'] == storage.sha(destination.read_bytes())
    runner.finish_private_index(obj, destination, digest)
    assert json.loads(destination.read_bytes())['validatedAtUtc'] == original['validatedAtUtc']


def test_private_index_refuses_changed_archive_before_exposure(tmp_path, runner):
    obj = tmp_path / 'sealed'
    obj.mkdir()
    (obj / 'admission.json').write_bytes(storage.encode({'packetSha256': '0' * 64}))
    (obj / 'packet.json').write_bytes(b'changed')
    destination = tmp_path / 'episodes' / 'synthetic.json'
    with pytest.raises(ValueError, match='PACKET_HASH_MISMATCH'):
        runner.finish_private_index(obj, destination, '0' * 64)
    assert not destination.exists()


def test_schedule_change_after_lock_excludes_copy_without_rewriting_original(runner):
    original = [{'gameId': 'synthetic', 'forecastEligible': True, 'enrollmentEligible': True,
                 'scheduledStartUtc': '2026-09-19T20:05:00Z', 'researchLockUtc': '2026-09-19T19:50:00Z'}]
    universe = {'later': {'canonicalGameId': 'synthetic', 'scheduledStartUtc': '2026-09-20T20:05:00Z',
                          'firstSeenBySealerUtc': '2026-09-19T19:55:00Z'}}
    revised = runner.apply_schedule_dispositions(original, universe)
    assert original[0]['forecastEligible'] is True
    assert revised[0]['forecastEligible'] is False
    assert revised[0]['originalForecastEligible'] is True


def test_relative_evidence_pointer_and_ledger_locator_verify_original_bytes(tmp_path):
    consumer, runtime = tmp_path / 'consumer', tmp_path / 'runtime'
    consumer.mkdir()
    evidence = consumer / 'evidence.json'
    evidence.write_bytes(storage.encode({'rows': {'one/two': {'value': 4}}}))
    ref = {**storage.file_ref(evidence), 'path': 'evidence.json', 'locator': '/rows/one~1two'}
    ledger = consumer / 'attempt-ledger.jsonl'
    ledger.write_bytes(_ledger_bytes([{'kind': 'SEAL_ATTEMPT'}]))
    records, _ = storage.load_ledger(ledger)
    refs = storage.RetainedRefs(consumer, runtime, records)
    assert refs(ref) == {'value': 4}
    relative_line = {**records[0][1], 'path': 'attempt-ledger.jsonl'}
    assert refs(relative_line)['kind'] == 'SEAL_ATTEMPT'
    with pytest.raises(ValueError, match='LEDGER_LINE_REFERENCE_MISMATCH'):
        refs({**relative_line, 'sha256': '0' * 64})
    with pytest.raises(ValueError, match='PHYSICAL_REFERENCE_MISMATCH'):
        refs({**ref, 'sha256': '0' * 64})


def test_reference_scope_escape_is_rejected(tmp_path):
    consumer = tmp_path / 'consumer'
    consumer.mkdir()
    outside = tmp_path / 'outside.json'
    outside.write_bytes(b'{}')
    refs = storage.RetainedRefs(consumer, tmp_path / 'runtime')
    with pytest.raises(ValueError, match='REFERENCE_OUTSIDE_READ_SCOPE'):
        refs({**storage.file_ref(outside), 'path': '../outside.json'})


def test_interrupted_immutable_write_has_no_final_name_and_never_replaces_existing(tmp_path, monkeypatch):
    target = tmp_path / 'immutable.json'
    def interruption(_handle):
        raise OSError('synthetic interruption before final rename')
    monkeypatch.setattr(storage.os, 'fsync', interruption)
    with pytest.raises(OSError, match='interruption'):
        storage.write_once(target, b'{"complete":true}\n')
    assert not target.exists()
    assert list(tmp_path.glob('*.pending'))
    existing = tmp_path / 'existing.json'
    existing.write_bytes(b'original')
    with pytest.raises(ValueError, match='IMMUTABLE_REPLACEMENT_ATTEMPT'):
        storage.write_once(existing, b'replacement')
    assert existing.read_bytes() == b'original'


def test_schema_frozen_nullable_refs_and_numeric_clock_constraints():
    schema = json.loads((Path(__file__).resolve().parents[1] /
        'docs/mlb-v18-market-prospective-v1/PACKET_SCHEMA.json').read_text())
    assert not storage.schema_errors(None, schema['properties']['forecast'], schema)
    assert not storage.schema_errors(None, schema['properties']['anchor']['properties']['atUtc'], schema)
    assert storage.schema_errors('2026-09-19T19:50:00', schema['properties']['sealedAtUtc'], schema)
    assert storage.schema_errors('not-a-sha', schema['$defs']['sha'], schema)
    assert storage.schema_errors(True, schema['$defs']['ref']['properties']['bytes'], schema)
    leg = schema['$defs']['leg']['properties']
    assert storage.schema_errors(1.0, leg['decimal'], schema)
    assert storage.schema_errors(float('nan'), leg['decimal'], schema)
    assert not storage.schema_errors(2.0, leg['decimal'], schema)
    assert storage.schema_errors({'unexpected': True}, schema)


def test_outcome_guard_is_recursive_and_allows_only_pregame_score_populations(runner):
    runner.no_outcomes({'forecast': {'scorePopulationRef': {'path': 'synthetic'}, 'pHome': .6}})
    for value in ({'Winner': 'HOME'}, {'rows': [{'home_score': 5}]}, {'market': {'settlement_result': 'WIN'}}):
        with pytest.raises(ValueError, match='OUTCOME_FIELD_IN_PREGAME_EXPORT'):
            runner.no_outcomes(value)


def _sealed_fixture(tmp_path, monkeypatch, runner, *, sgo=False, completed='2026-09-19T19:51:05Z', seal_kind='SEALED'):
    packet, protocol, audit, verify_memory, _, _ = _fixture()
    consumer, runtime = tmp_path / 'consumer', tmp_path / 'runtime'
    consumer.mkdir()
    key = 'synthetic_game_revision_1'
    packet['episodeKey'] = key
    packet['protocolSha256'] = storage.PROTOCOL_SHA
    protocol['protocolSha256'] = storage.PROTOCOL_SHA
    protocol.pop('_admissionContext')
    if sgo:
        pair = packet['market']['candidates'][0]
        pair['providerKey'] = 'SPORTSGAMEODDS'
        pair['conventions']['extraInnings'] = 'INCLUDED_PER_PROVIDER_FULL_GAME_PERIOD_AS_ENFORCED_BY_THE_SGO_PARSER'
        pair['conventions']['pitcherActionRule'] = 'NOT_RETAINED_UNKNOWN'
        pair['legSkewSeconds'] = None
        for side in ('home', 'away'):
            leg = pair[side]
            leg['clockMeaning'] = "pair's OLDER provider side update applied to both legs (per-side stamps not retained)"
            leg['availableByIsReceipt'] = False
            for field in ('bookKey', 'providerKey', 'marketId', 'snapshotId', 'period', 'conventions'):
                leg.pop(field)
        pair['eligible'] = True
        packet['market']['status'] = 'FRESH_PAIRED'

    # Materialize the existing entirely synthetic in-memory references into
    # independent files. Relative paths deliberately model the consumer export.
    references = {}
    def materialize(value):
        if isinstance(value, dict) and {'path', 'sha256', 'bytes'} <= value.keys():
            identity = value['path']
            if identity not in references:
                original = verify_memory(value)
                body = materialize(original)
                destination = consumer / ('support-' + value['sha256'] + '.json')
                destination.write_bytes(storage.encode(body))
                references[identity] = {**storage.file_ref(destination), 'path': destination.name}
            return deepcopy(references[identity])
        if isinstance(value, dict):
            return {k: materialize(v) for k, v in value.items()}
        if isinstance(value, list):
            return [materialize(v) for v in value]
        return value
    original_q = verify_memory(protocol['quarantineLedgerAtFreeze'])
    original_phase = verify_memory(packet['game']['phaseEvidenceRef'])
    original_decisions = verify_memory(packet['sourceRefs'][0])
    original_candidates = verify_memory(packet['anchor']['candidateDecisionsRef'])
    original_selection = verify_memory(packet['selection']['consumerExportRef'])
    packet, audit, protocol = materialize(packet), materialize(audit), materialize(protocol)

    quarantine = runtime / 'server/artifacts/governance/mlb-final-oot-quarantine-v1.json'
    quarantine.parent.mkdir(parents=True)
    quarantine.write_bytes(storage.encode(original_q))
    qref = storage.file_ref(quarantine)
    protocol['quarantineLedgerAtFreeze'] = qref
    packet['game']['quarantineIdentityGate']['ledgerSha256'] = qref['sha256']
    # Raw phase file is identity-only synthetic metadata and is hashed without
    # parsing by the real RetainedRefs phase branch.
    phase_path = tmp_path / 'ai-sports-predictor/data/raw/mlb_stats_api/2026/09/19/synthetic.json'
    phase_path.parent.mkdir(parents=True)
    phase_path.write_bytes(storage.encode(original_phase))
    phase_metadata = {**storage.file_ref(phase_path), **original_phase}
    packet['game']['phaseEvidenceRef'] = storage.file_ref(phase_path)
    evidence = {**original_decisions, 'mode': 'PROSPECTIVE_SEAL', 'episodeKey': key,
        'protocolSha256': storage.PROTOCOL_SHA,
        'files': {'phaseEvidence': phase_metadata},
        'notes': {'candidateDecisions': original_candidates, 'selectionExport': original_selection}}
    evidence_bytes = storage.encode(evidence)
    evidence_name = key + '.evidence-' + storage.sha(evidence_bytes)[:16] + '.json'
    evidence_path = consumer / evidence_name
    evidence_path.write_bytes(evidence_bytes)
    eref = {**storage.file_ref(evidence_path), 'path': evidence_name}
    packet['sourceRefs'] = [eref]
    packet['anchor']['candidateDecisionsRef'] = {**eref, 'locator': '/notes/candidateDecisions'}
    packet['selection']['consumerExportRef'] = {**eref, 'locator': '/notes/selectionExport'}
    universe_row = {'kind': 'UNIVERSE_FIRST_SEEN', 'episodeKey': key,
        'canonicalGameId': packet['game']['canonicalGameId'],
        'scheduledStartUtc': packet['game']['scheduledStartUtc'],
        'researchLockUtc': packet['anchor']['researchLockUtc'],
        'sealDeadlineUtc': packet['anchor']['sealDeadlineUtc'], 'firstSeenBySealerUtc': packet['game']['firstSeenAtUtc']}
    attempt = {'kind': 'SEAL_ATTEMPT', 'episodeKey': key}
    ledger_path = consumer / 'attempt-ledger.jsonl'
    ledger_path.write_bytes(_ledger_bytes([universe_row, attempt]))
    first_records, _ = storage.load_ledger(ledger_path)
    packet['attemptLedgerRef'] = {**first_records[1][1], 'path': ledger_path.name}
    packet_bytes = storage.encode(packet)
    packet_path = consumer / (key + '.json')
    packet_path.write_bytes(packet_bytes)
    seal = {'kind': seal_kind, 'episodeKey': key, 'packetSha256': storage.sha(packet_bytes),
        'packetBytes': len(packet_bytes), 'evidenceFile': evidence_name,
        'evidenceSha256': storage.sha(evidence_bytes), 'writtenAtUtc': completed,
        'sealedAtUtc': packet['sealedAtUtc'], 'sealDeadlineUtc': packet['anchor']['sealDeadlineUtc']}
    ledger_path.write_bytes(_ledger_bytes([universe_row, attempt, seal]))
    ledger_records, _ = storage.load_ledger(ledger_path)
    seal, seal_ref = ledger_records[-1]
    (consumer / (key + '.sha256')).write_text(seal['packetSha256'] + '  ' + key + '.json\n' +
        seal['evidenceSha256'] + '  ' + evidence_name + '\n', encoding='ascii')
    refs = storage.RetainedRefs(consumer, runtime, ledger_records)
    monkeypatch.setattr(runner, 'audit_producer', lambda *_: deepcopy(audit))
    monkeypatch.setattr(runner, 'publication_candidates', lambda *_: [])
    schema = json.loads((Path(__file__).resolve().parents[1] /
        'docs/mlb-v18-market-prospective-v1/PACKET_SCHEMA.json').read_text())
    binding = {'readyAtUtc': '2026-09-19T03:00:00Z', 'authorityExpiresAtUtc': '2026-10-01T00:00:00Z'}
    args = (seal, seal_ref, {key: universe_row}, refs, protocol, schema, binding,
            datetime(2026, 9, 20, tzinfo=timezone.utc), runtime)
    return args, packet_bytes, evidence_bytes


def test_process_seal_preserves_original_bytes_and_uses_later_real_validation_clock(tmp_path, monkeypatch, runner):
    args, packet_bytes, evidence_bytes = _sealed_fixture(tmp_path, monkeypatch, runner)
    packet, evidence, result, retained_packet, retained_evidence = runner.process_seal(*args)
    assert retained_packet == packet_bytes and retained_evidence == evidence_bytes
    assert result['forecastEligible'] and result['priceEvaluable'] and result['enrollmentEligible']
    assert result['originalSealedAtUtc'] == '2026-09-19T19:51:00Z'
    assert result['sealCompletedAtUtc'] == '2026-09-19T19:51:05Z'
    assert result['validatedAtUtc'] == '2026-09-20T00:00:00+00:00'
    assert result['packetSha256'] == storage.sha(packet_bytes)
    assert result['originalEvidenceRef']['sha256'] == storage.sha(evidence_bytes)


def test_process_seal_late_completed_write_is_excluded_even_with_timely_build_start(tmp_path, monkeypatch, runner):
    args, _, _ = _sealed_fixture(tmp_path, monkeypatch, runner, completed='2026-09-19T20:01:00Z')
    result = runner.process_seal(*args)[2]
    assert not result['enrollmentEligible'] and not result['forecastEligible']
    assert 'LATE_OR_BACKDATED_PACKET_SEAL' in result['reasons']


def test_process_seal_missing_completed_sealed_ledger_state_cannot_enroll(tmp_path, monkeypatch, runner):
    args, _, _ = _sealed_fixture(tmp_path, monkeypatch, runner, seal_kind='SEAL_ATTEMPT')
    result = runner.process_seal(*args)[2]
    assert not result['enrollmentEligible']
    assert 'COMPLETED_SEAL_LEDGER_BINDING_MISMATCH' in result['reasons']


def test_process_seal_bad_completed_ledger_reference_cannot_enroll(tmp_path, monkeypatch, runner):
    args, _, _ = _sealed_fixture(tmp_path, monkeypatch, runner)
    altered = list(args)
    altered[1] = {**args[1], 'sha256': '0' * 64}
    result = runner.process_seal(*altered)[2]
    assert not result['enrollmentEligible']
    assert 'COMPLETED_SEAL_LEDGER_REFERENCE_VERIFICATION_FAILED' in result['reasons']


def test_process_seal_current_sgo_shape_is_unpriced_and_keeps_legitimate_forecast(tmp_path, monkeypatch, runner):
    args, _, _ = _sealed_fixture(tmp_path, monkeypatch, runner, sgo=True)
    result = runner.process_seal(*args)[2]
    assert result['forecastEligible'] and result['enrollmentEligible']
    assert not result['priceEvaluable'] and result['marketStatus'] == 'UNPRICED'
    assert 'PITCHER_ACTION_CONVENTION_UNPROVEN' in result['reasons']
    assert 'HOME_INDIVIDUAL_QUOTE_CLOCK_UNPROVEN' in result['reasons']


def test_process_seal_detects_packet_replacement_before_producer_audit(tmp_path, monkeypatch, runner):
    args, _, _ = _sealed_fixture(tmp_path, monkeypatch, runner)
    seal, _, _, refs, *_ = args
    (refs.consumer / (seal['episodeKey'] + '.json')).write_bytes(b'{}')
    def forbidden(*_):
        raise AssertionError('Bad packet reached producer audit')
    monkeypatch.setattr(runner, 'audit_producer', forbidden)
    with pytest.raises(ValueError, match='SEALED_PACKET_HASH_MISMATCH'):
        runner.process_seal(*args)
