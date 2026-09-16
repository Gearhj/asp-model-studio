"""Offline metadata-only prospective support checks; no model/source execution.

Compatibility must be attested by the owning frozen-model verifier. This module
does not infer feature completeness from a non-null row or an artifact's shape.
The optional CLI reads only historical JSON receipts/manifests/pregame metadata.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _digest(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None


def assess_game_support(record: Mapping[str, Any], *, execution_time: str,
                        required_models: Sequence[str] = ('V18', 'RF')) -> dict[str, Any]:
    """Assess explicit metadata, preserving prior skips and original timestamps."""
    now = _utc(execution_time)
    if now is None:
        raise ValueError('A timezone-aware actual execution time is required')
    reasons: list[str] = []
    kickoff = _utc(record.get('scheduledStartUtc'))
    captured = _utc(record.get('capturedAtUtc'))
    cutoff = _utc(record.get('evidenceCutoffUtc'))
    if kickoff is None:
        reasons.append('MISSING_OR_INVALID_KICKOFF')
    elif now >= kickoff:
        reasons.append('EXECUTION_AT_OR_AFTER_KICKOFF')
    if captured is None:
        reasons.append('MISSING_OR_INVALID_CAPTURE_TIMESTAMP')
    elif captured > now:
        reasons.append('CAPTURE_AFTER_EXECUTION')
    if kickoff and captured and captured >= kickoff:
        reasons.append('CAPTURE_AT_OR_AFTER_KICKOFF')
    if cutoff is None:
        reasons.append('MISSING_OR_INVALID_EVIDENCE_CUTOFF')
    else:
        if cutoff > now or (captured and cutoff > captured):
            reasons.append('EVIDENCE_AFTER_CAPTURE_OR_EXECUTION')
        if kickoff and cutoff >= kickoff:
            reasons.append('EVIDENCE_AT_OR_AFTER_KICKOFF')
    identifiers = [record.get(k) for k in ('canonicalEventId', 'canonicalHomeTeamId', 'canonicalAwayTeamId', 'sourceEventId')]
    if any(not isinstance(v, str) or not v.strip() for v in identifiers) or record.get('identityStatus') != 'VERIFIED_EXACT':
        reasons.append('EVENT_TEAM_IDENTITY_NOT_VERIFIED')
    if record.get('canonicalHomeTeamId') and record.get('canonicalHomeTeamId') == record.get('canonicalAwayTeamId'):
        reasons.append('HOME_AWAY_IDENTITY_COLLISION')
    if record.get('eventStatus') not in ('SCHEDULED', 'PREGAME', 'PRE_GAME'):
        reasons.append('EVENT_NOT_PREGAME')
    if record.get('originalStatus') == 'SKIPPED':
        reasons.append('ORIGINAL_SKIP_RETAINED')
    per_model = {}
    compatibility = record.get('inputCompatibility') or {}
    for model in required_models:
        data = compatibility.get(model) or {}
        model_reasons = []
        if data.get('status') != 'VERIFIED_COMPATIBLE' or data.get('completeForFrozenModel') is not True:
            model_reasons.append('FROZEN_INPUT_COMPATIBILITY_NOT_VERIFIED')
        if data.get('canonicalEventId') != record.get('canonicalEventId') or not record.get('canonicalEventId'):
            model_reasons.append('INPUT_EVENT_IDENTITY_NOT_VERIFIED')
        for field in ('modelSha256', 'inputArtifactSha256', 'orderedSchemaSha256', 'compatibilityReceiptSha256'):
            if not _digest(data.get(field)):
                model_reasons.append('MISSING_OR_INVALID_' + field.upper())
        if data.get('currentEventContextVerified') is not True:
            model_reasons.append('CURRENT_EVENT_CONTEXT_NOT_VERIFIED')
        observed = _utc(data.get('sourceObservedAtUtc'))
        available = _utc(data.get('sourceAvailableAsOfUtc'))
        if observed is None or available is None:
            model_reasons.append('EXACT_INPUT_SOURCE_TIMESTAMPS_NOT_VERIFIED')
        elif (observed > available or available > now or not captured or available > captured
              or not cutoff or available > cutoff):
            model_reasons.append('INPUT_SOURCE_TIMING_NOT_POINT_IN_TIME')
        if kickoff and ((observed and observed >= kickoff) or (available and available >= kickoff)):
            model_reasons.append('INPUT_SOURCE_AT_OR_AFTER_KICKOFF')
        per_model[model] = {'supported': not model_reasons, 'reportedStatus': data.get('status', 'UNAVAILABLE'),
                            'reasons': model_reasons, 'metadata': dict(data)}
        reasons.extend(model + ':' + reason for reason in model_reasons)
    supported = not reasons
    status = ('EXPIRED_NONPROSPECTIVE' if kickoff and now >= kickoff else
              'SUPPORTED_PREGAME_METADATA' if supported else 'WITHHELD_UNSUPPORTED')
    return {'canonicalEventId': record.get('canonicalEventId'), 'sourceEventId': record.get('sourceEventId'),
            'canonicalHomeTeamId': record.get('canonicalHomeTeamId'), 'canonicalAwayTeamId': record.get('canonicalAwayTeamId'),
            'scheduledStartUtc': kickoff.isoformat() if kickoff else record.get('scheduledStartUtc'),
            'capturedAtUtc': record.get('capturedAtUtc'), 'evidenceCutoffUtc': record.get('evidenceCutoffUtc'),
            'status': status, 'supported': supported, 'reasons': reasons, 'models': per_model,
            'originalStatus': record.get('originalStatus'), 'originalSkipReason': record.get('originalSkipReason'),
            'sourceReferences': list(record.get('sourceReferences') or []),
            'sourceEvidence': record.get('sourceEvidence'), 'historicalObjectSha256': record.get('historicalObjectSha256')}


def account_games(records: Sequence[Mapping[str, Any]], *, execution_time: str,
                  next_slate_known: bool = False, required_models: Sequence[str] = ('V18', 'RF')) -> dict[str, Any]:
    ids = [r.get('canonicalEventId') for r in records if r.get('canonicalEventId')]
    if len(ids) != len(set(ids)):
        raise ValueError('One accounting row per canonical event is required')
    games = [assess_game_support(row, execution_time=execution_time, required_models=required_models) for row in records]
    if not next_slate_known and any(row['supported'] for row in games):
        raise ValueError('Supported current games cannot be reported with an unknown next-slate scope')
    return {'schemaVersion': 'MLB_V18_RF_PROSPECTIVE_SUPPORT_ACCOUNTING_V1', 'asOfUtc': _utc(execution_time).isoformat(),
            'scope': 'NEXT_SLATE_KNOWN' if next_slate_known else 'NEXT_SLATE_UNKNOWN_HISTORICAL_INVENTORY_ONLY',
            'nextSlate': {'identityStatus': 'ESTABLISHED' if next_slate_known else 'NOT_ESTABLISHED_FROM_LOCAL_EVIDENCE',
                          'scheduledGameCount': len(games) if next_slate_known else None,
                          'supportedGameCount': sum(r['supported'] for r in games),
                          'withheldGameCount': sum(not r['supported'] for r in games) if next_slate_known else None},
            'inspectedRecordCount': len(games), 'expiredNonprospectiveCount': sum(r['status'] == 'EXPIRED_NONPROSPECTIVE' for r in games),
            'originalPublishedCount': sum(r['originalStatus'] == 'PUBLISHED' for r in games),
            'originalSkipCount': sum(r['originalStatus'] == 'SKIPPED' for r in games),
            'reasonCounts': dict(Counter(reason for row in games for reason in row['reasons'])), 'games': games,
            'authority': {'status': 'RESEARCH_SHADOW', 'promotionStatus': 'NOT_PROMOTED', 'wageringAuthority': False,
                          'executionAllowedInAISP': False},
            'limitations': ['Metadata support is not authorization to execute, publish, promote, or wager.',
                'Original capture time cannot authorize retrospective execution after first pitch.',
                'Unknown next-slate scope is not evidence that no games are scheduled.',
                'Date-only historical source bounds cannot be replaced with invented exact timestamps.']}


def _read_metadata(path: Path, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or resolved.name not in ('slate-result.json', 'manifest.json', 'pregame-evidence.json'):
        raise ValueError('Only bounded historical receipt/manifest/pregame JSON metadata may be opened')
    raw = resolved.read_bytes()
    return json.loads(raw), {'path': str(resolved), 'sha256': hashlib.sha256(raw).hexdigest(), 'byteCount': len(raw)}


def write_historical_accounting(receipt_path: Path, output_path: Path, *, execution_time: str) -> dict[str, Any]:
    """Read only September 8 metadata; never open execution inputs or parquet."""
    daily_root = Path(__file__).resolve().parents[2] / 'outputs/mlb-v18-daily-slate'
    receipt, receipt_ref = _read_metadata(receipt_path, daily_root)
    if receipt.get('slateDate') != '2026-09-08' or len(receipt.get('games', [])) != 15:
        raise ValueError('The bounded historical receipt must describe all 15 September 8 records')
    records, evidence = [], [receipt_ref]
    for original in receipt['games']:
        row = {'canonicalEventId': original['gameId'], 'sourceEventId': None, 'canonicalHomeTeamId': None,
               'canonicalAwayTeamId': None, 'identityStatus': 'NOT_RECORDED_IN_SKIP_RECEIPT', 'eventStatus': None,
               'scheduledStartUtc': original['scheduledStart'], 'capturedAtUtc': original.get('capturedAt'),
               'evidenceCutoffUtc': None, 'originalStatus': original['status'], 'originalSkipReason': original.get('reason'),
               'historicalObjectSha256': original.get('objectSha256'), 'sourceReferences': [receipt_ref],
               'sourceEvidence': {'historicalTemplateDateWindow': ['2026-04-01', '2026-08-13'],
                   'historicalBullpenTemplateDateWindow': ['2026-07-15', '2026-08-13'],
                   'exactModelSourceAvailableAsOfUtc': None,
                   'currentEventContext': 'NOT_VERIFIED_FOR_A_NEW_EVENT', 'publicationTimestampIsNotEvidenceRefresh': True},
               'inputCompatibility': {'V18': {'status': 'HISTORICAL_REPLAY_ONLY_NOT_CURRENT_EVENT_VERIFIED',
                   'completeForFrozenModel': False}, 'RF': {'status': 'PROSPECTIVE_COMPANION_INPUTS_NOT_VERIFIED',
                   'completeForFrozenModel': False}}}
        if original['status'] == 'PUBLISHED':
            directory = daily_root / original['artifactPath']
            manifest, manifest_ref = _read_metadata(directory / 'manifest.json', daily_root)
            snapshot, snapshot_ref = _read_metadata(directory / 'pregame-evidence.json', daily_root)
            expected = next(a for a in manifest['artifacts'] if a['relativePath'] == 'pregame-evidence.json')
            if (manifest['objectSha256'] != original['objectSha256'] or manifest['gameId'] != original['gameId']
                or snapshot_ref['sha256'] != expected['sha256'] or snapshot_ref['byteCount'] != expected['bytes']
                or snapshot['game']['game_id'] != original['gameId']):
                raise ValueError('Historical snapshot/manifest identity or checksum differs')
            sides = {side['side']: side for side in snapshot['sides']}
            row.update({'sourceEventId': snapshot['game'].get('source_game_id'),
                'canonicalHomeTeamId': sides['HOME']['team']['uuid'], 'canonicalAwayTeamId': sides['AWAY']['team']['uuid'],
                'identityStatus': 'VERIFIED_EXACT', 'eventStatus': snapshot['game']['status'],
                'sourceReferences': [receipt_ref, manifest_ref, snapshot_ref]})
            row['sourceEvidence']['participantEvidence'] = {side: {'teamAbbreviation': data['team']['abbreviation'],
                'starterAvailableAsOfUtc': data['starter'].get('availableAsOf'),
                'starterObservedAtUtc': data['starter'].get('observedAt'),
                'lineupAvailableAsOfUtc': data['lineupAuthority'].get('availableAsOf'),
                'lineupObservedAtUtc': data['lineupAuthority'].get('observedAt'),
                'lineupStatus': data['lineupAuthority'].get('status')} for side, data in sides.items()}
            evidence.extend([manifest_ref, snapshot_ref])
        records.append(row)
    result = account_games(records, execution_time=execution_time)
    result['sourceReferences'] = evidence
    result['activity'] = {'modelFits': 0, 'modelExecutions': 0, 'providerCalls': 0, 'aispReads': 0, 'aispWrites': 0,
                          'finalOotPayloadBytesRead': 0, 'parquetPayloadReads': 0, 'newForecasts': 0}
    raw = json.dumps(result, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if output_path.read_bytes() != raw:
            raise ValueError('Existing accounting receipt is immutable; use a new output identity')
    else:
        with output_path.open('xb') as handle:
            handle.write(raw)
    return {'path': str(output_path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest(), 'byteCount': len(raw),
            'expiredRecords': result['expiredNonprospectiveCount'], 'originalSkips': result['originalSkipCount'],
            'nextSlate': result['nextSlate']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical-receipt', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(write_historical_accounting(args.historical_receipt, args.output,
        execution_time=datetime.now(timezone.utc).isoformat()), sort_keys=True))
