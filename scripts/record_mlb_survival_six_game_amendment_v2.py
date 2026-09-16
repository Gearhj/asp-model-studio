"""Record the user's exact six-source grant and append quarantine before intake."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_silver.canonical_ids import canonical_game_id
from server.sports_current_statcast.mlb_starter_duration_quarantine import (
    LEDGER, LEDGER_ARCHIVE, ORIGINAL_LEDGER_SHA, SIX_ALLOWED, SIX_USER_GRANT_SHA,
    SIX_AUTHORITY_POINTER, AUTHORITY_POINTER, PURPOSE, load_exception_authority,
    final_oot_eligible_key_mask)
from server.sports_current_statcast.mlb_v18_unattended import atomic_state, single_owner

OUT = ROOT / 'outputs/mlb-v18-position-and-survival-verification-v1'
GRANT = Path(r'C:\Users\james\.codex\attachments\ecb2a77a-b8ab-459b-bef6-d157bad76b9f\pasted-text.txt')


def ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def retain(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('IMMUTABLE_AMENDMENT_DESTINATION_CONFLICT')
    else:
        path.write_bytes(raw)
    return ref(path)


def record():
    grant = ref(GRANT)
    if grant['sha256'] != SIX_USER_GRANT_SHA:
        raise ValueError('EXACT_USER_SOURCE_AMENDMENT_CHANGED')
    with single_owner(AUTHORITY_POINTER.parent / 'intake.lock') as owned:
        if not owned:
            return {'status': 'DEFERRED_EXISTING_INTAKE_OWNER'}
        if SIX_AUTHORITY_POINTER.exists():
            authority = load_exception_authority(json.loads(SIX_AUTHORITY_POINTER.read_bytes()))
            return {'status': 'ALREADY_RECORDED_NO_SOURCE_ACCESS', 'authority': authority['authorityRef'],
                    'quarantine': authority['currentQuarantineRef']}
        before = LEDGER.read_bytes()
        if hashlib.sha256(before).hexdigest() != ORIGINAL_LEDGER_SHA:
            raise ValueError('ORIGINAL_THREE_GAME_QUARANTINE_PREDECESSOR_REQUIRED')
        old = json.loads(before)
        predecessor = retain(LEDGER_ARCHIVE / ORIGINAL_LEDGER_SHA / 'quarantine.json', before)
        stamp = datetime.now(timezone.utc).isoformat()
        added = [{'mlbamGamePk': pk, 'canonicalGameId': canonical_game_id(pk), 'gameDate': day,
                  'authorizedPitcherMlbamId': pid,
                  'pitcherName': 'Gabriel Hughes' if pid == '687312' else 'Jackson Jobe',
                  'reason': 'PROSPECTIVE_FEATURE_CONSTRUCTION'}
                 for pid, pk, day in sorted(SIX_ALLOWED, key=lambda v: (v[2], v[1]))]
        ledger = {**old, 'schemaVersion': 'MLB_FINAL_OOT_PERMANENT_GAME_QUARANTINE_V2',
                  'recordedAt': stamp, 'authority': 'James exact six-game source amendment ecb2a77a, preserving the original three exclusions',
                  'predecessor': predecessor, 'userAuthorization': grant, 'games': old['games'] + added,
                  'identityAccountingNote': 'Original three-game receipt remains historical. New nine-game observation counts have not been evaluated or inferred; source permission grants no OOT evaluation.'}
        # This atomic ledger change precedes every new source request or payload read.
        atomic_state(LEDGER, ledger)
        quarantine = ref(LEDGER)
        old_authority = json.loads(AUTHORITY_POINTER.read_bytes())
        amendment = {'schemaVersion': 'MLB_STARTER_SURVIVAL_EXACT_SIX_SOURCE_AMENDMENT_V2',
                     'declaredAt': stamp, 'purpose': PURPOSE, 'userAuthorizationRef': grant,
                     'predecessorAuthority': old_authority, 'quarantineRef': quarantine,
                     'allowedTuples': [{'pitcherMlbamId': pid, 'gamePk': pk, 'gameDate': day}
                                      for pid, pk, day in sorted(SIX_ALLOWED, key=lambda v: (v[2], v[1]))],
                     'maxNewRequests': 6, 'maxNewOriginalBytes': 50331648, 'sourceCostUsdCeiling': 0,
                     'cumulativeRequestCeiling': 200, 'cumulativeOriginalPayloadByteCeiling': 524288000,
                     'evaluationAllowed': False, 'modelFitAllowed': False, 'sealedEvaluationFilesMayBeRead': False,
                     'remainingProtectedSourceGamesAuthorized': False, 'prospectiveForecastOnly': True,
                     'requiredSourceFields': ['starter and source identity', 'BF and outs', 'ordered PA attribution',
                                              'relevant runner/substitution/non-PA events', 'completion/resumption/correction lineage'],
                     'rawScoreUse': 'Inseparable scores only as quarantined source reconciliation; no performance inspection.',
                     'originalPilotAuthorityPointerChanged': False}
        raw = (json.dumps(amendment, sort_keys=True, indent=2) + '\n').encode()
        digest = hashlib.sha256(raw).hexdigest()
        descriptor = retain(AUTHORITY_POINTER.parent / 'objects/sha256' / (digest + '.source-amendment.json'), raw)
        atomic_state(SIX_AUTHORITY_POINTER, descriptor)
        verified = load_exception_authority(descriptor)
        keys = [str(g['mlbamGamePk']) for g in ledger['games']]
        if any(final_oot_eligible_key_mask(keys)) or len(keys) != 9:
            raise ValueError('NINE_ENTIRE_GAMES_NOT_QUARANTINED')
        receipt = {'schemaVersion': 'MLB_SIX_SOURCE_AMENDMENT_RECORDED_V2', 'recordedAtUtc': stamp,
                   'status': 'RECORDED_BEFORE_SOURCE_ACCESS', 'userAuthorization': grant,
                   'authority': descriptor, 'quarantine': verified['currentQuarantineRef'],
                   'previousQuarantine': predecessor, 'wholeGamesPermanentlyExcluded': 9,
                   'originalThreePreserved': ledger['games'][:3] == old['games'],
                   'oldPilotAuthorityStillValid': load_exception_authority()['authorityRef'] == old_authority,
                   'sourceRequests': 0, 'sourcePayloadReads': 0, 'sealedEvaluationReads': 0}
        raw = (json.dumps(receipt, indent=2) + '\n').encode()
        descriptor = retain(OUT / 'governance/sha256' / hashlib.sha256(raw).hexdigest() / 'amendment-receipt.json', raw)
        atomic_state(OUT / 'governance/current.json', descriptor)
        return receipt


if __name__ == '__main__':
    print(json.dumps(record(), indent=2))
