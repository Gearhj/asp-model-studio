"""Receipts and decisions for the temporary NFL -> MLB heartbeat handoff.

All scheduler mutations use the Codex automation tool, never SQLite/file edits.
This helper snapshots only the two named tasks and NFL archive metadata; it
never opens NFL source payloads, MLB OOT or live game outcomes.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_mlb_starter_duration_paired import OUTPUT, published_pairs, read, reference, resume, save, score
from server.sports_current_statcast.mlb_v18_unattended import atomic_state

TASKS = Path('C:/Users/james/.codex/automations')
DATABASE = Path('C:/Users/james/.codex/sqlite/codex-dev.db')
NFL = 'archive-nfl-forward-evidence'
MLB = 'mlb-starter-pair-readiness'
MONITOR = OUTPUT / 'monitoring'
CURRENT = MONITOR / 'current.json'
DECLARATION = OUTPUT / 'objects/sha256/b3f6debf668aba1cafbe308489255772a593e9d03532d5b3097f101af32bd19b/declaration.json'
NFL_CURSOR = ROOT / 'outputs/nfl-forward-vintages-v1/CURRENT.json'


def now():
    return datetime.now(timezone.utc)


def scheduler_snapshot():
    result = {}
    with sqlite3.connect(DATABASE.as_uri() + '?mode=ro', uri=True) as db:
        db.execute('PRAGMA query_only=ON')
        db.row_factory = sqlite3.Row
        for task in (NFL, MLB):
            config_path = TASKS / task / 'automation.toml'
            raw = config_path.read_bytes()
            row = db.execute('SELECT * FROM automations WHERE id=?', (task,)).fetchone()
            if row is None:
                raise ValueError('EXISTING_TASK_REQUIRED:' + task)
            config = tomllib.loads(raw.decode())
            if row['status'] != config['status']:
                raise ValueError('SCHEDULER_AND_CONFIG_STATE_DISAGREE:' + task)
            result[task] = {'config': config, 'originalConfigUtf8': raw.decode(),
                            'configRef': reference(config_path), 'schedulerRow': dict(row),
                            'runs': [dict(r) for r in db.execute(
                                'SELECT * FROM automation_runs WHERE automation_id=?', (task,))]}
    return result


def state():
    return json.loads(CURRENT.read_bytes())


def original():
    return read(state()['prepared'])


def frozen_pairs_unchanged(prepared):
    current = {p['commonPairId']: ptr for p, ptr in published_pairs(OUTPUT)}
    for key, pointer in prepared['frozenPairs'].items():
        if current.get(key) != pointer:
            raise ValueError('FROZEN_PUBLISHED_PAIR_CHANGED:' + key)


def event(label, body):
    prior = state() if CURRENT.exists() else {}
    obj = save('monitor-event.json', {'schemaVersion': 'MLB_PAIR_TEMPORARY_HEARTBEAT_HANDOFF_V1',
        'event': label, 'observedAtUtc': now().isoformat(), 'previous': prior.get('latest'), **body}, MONITOR)
    atomic_state(CURRENT, {**prior, 'latest': obj})
    return obj


def prepare():
    if CURRENT.exists():
        return {'status': 'EXISTING_HANDOFF_REUSED', 'prepared': state()['prepared']}
    scheduler = scheduler_snapshot()
    if scheduler[NFL]['config']['status'] != 'ACTIVE' or scheduler[MLB]['config']['status'] != 'PAUSED':
        raise ValueError('EXPECTED_NFL_ACTIVE_MLB_PAUSED')
    cursor = json.loads(NFL_CURSOR.read_bytes())
    metadata = [cursor['manifest']] + [r['vintage'] for r in cursor['families'].values() if r.get('vintage')]
    metadata_copies = []
    for ref in metadata:
        path = Path(ref['path'])
        if not path.resolve().is_relative_to(NFL_CURSOR.parent.resolve()) or path.name not in ('manifest.json', 'vintage.json'):
            raise ValueError('ONLY_NFL_ARCHIVE_METADATA_MAY_BE_SNAPSHOTTED')
        actual = reference(path)
        if actual['sha256'] != ref['sha256'] or actual['bytes'] != ref['byteCount']:
            raise ValueError('NFL_ARCHIVE_METADATA_REFERENCE_MISMATCH')
        metadata_copies.append({'originalRef': actual, 'originalUtf8': path.read_text(encoding='utf-8')})
    obj = event('PREPARED_BEFORE_ANY_TASK_CHANGE', {
        'reason': 'JAMES_AUTHORIZED_TEMPORARY_MLB_PROSPECTIVE_READINESS_AND_FINAL_MEASUREMENT',
        'scheduler': scheduler, 'nflArchiveCursorRef': reference(NFL_CURSOR),
        'nflArchiveCursorOriginalUtf8': NFL_CURSOR.read_bytes().decode(),
        'nflArchiveMetadata': metadata_copies,
        'cursorMeaning': 'NFL CURRENT families are the archive heads; scheduler has last/next_run_at and target thread, no separate cursor column',
        'frozenPairs': {p['commonPairId']: ptr for p, ptr in published_pairs(OUTPUT)},
        'declaration': reference(DECLARATION),
        'restorationRule': 'ALL_CURRENT_PUBLISHED_PAIRS_SCORED_OR_24H_FROM_NFL_PAUSE_WHICHEVER_FIRST',
        'availabilityLimit': 'Local heartbeat requires computer awake and Codex running; overdue restoration is first action on next wake',
        'fitsAllowed': False, 'newProviderRequestsAllowed': False})
    atomic_state(CURRENT, {**state(), 'prepared': obj})
    return {'status': 'PREPARED', 'prepared': obj,
            'nflPriorNextRunAt': scheduler[NFL]['schedulerRow']['next_run_at']}


def same_nfl_configuration(before, after, *, restoring=False):
    ignored = {'status', 'updated_at'}
    if {k:v for k,v in before['config'].items() if k not in ignored} != {
            k:v for k,v in after['config'].items() if k not in ignored}:
        raise ValueError('NFL_CONFIGURATION_CHANGED_BEYOND_AUTHORIZED_STATE')
    if not restoring and before['schedulerRow']['last_run_at'] != after['schedulerRow']['last_run_at']:
        raise ValueError('NFL_LAST_RUN_CURSOR_CHANGED_DURING_SWITCH')
    if not restoring and before['runs'] != after['runs']:
        raise ValueError('NFL_RUN_HISTORY_CHANGED_DURING_SWITCH')


def record_transition(label):
    prepared = original()
    pair_check_error = None
    try:
        frozen_pairs_unchanged(prepared)
    except Exception as error:
        if label != 'NFL_RESTORED':
            raise
        # MLB diagnostic failures must not prevent verifying the hard-limit
        # NFL restoration. They remain visible and require notification.
        pair_check_error = type(error).__name__
    scheduler = scheduler_snapshot()
    same_nfl_configuration(prepared['scheduler'][NFL], scheduler[NFL], restoring=label == 'NFL_RESTORED')
    archive_unchanged = reference(NFL_CURSOR) == prepared['nflArchiveCursorRef']
    if label != 'NFL_RESTORED' and not archive_unchanged:
        raise ValueError('NFL_ARCHIVE_CURSOR_CHANGED_DURING_SWITCH')
    expected = {'NFL_PAUSED': ('PAUSED', 'PAUSED'),
                'MLB_ACTIVATED': ('PAUSED', 'ACTIVE'), 'NFL_RESTORED': ('ACTIVE', 'PAUSED')}[label]
    if tuple(scheduler[x]['config']['status'] for x in (NFL, MLB)) != expected:
        raise ValueError('TASK_TRANSITION_NOT_ACTUALLY_OBSERVED')
    details = {'scheduler': scheduler, 'prepared': state()['prepared'], 'nflArchiveCursorUnchanged': archive_unchanged,
               'priorNextRunAtPreservedInPreparedReceipt': prepared['scheduler'][NFL]['schedulerRow']['next_run_at'],
               'actualNextRunAtAfterTransition': scheduler[NFL]['schedulerRow']['next_run_at'],
               'frozenPairsUnchanged': None if pair_check_error else True,
               'frozenPairVerificationError': pair_check_error,
               'stateVerifiedFromConfigAndScheduler': True}
    if label == 'NFL_PAUSED':
        paused = datetime.fromtimestamp(scheduler[NFL]['config']['updated_at']/1000, timezone.utc)
        details.update(pausedAtUtc=paused.isoformat(), restoreNoLaterThanUtc=(paused+timedelta(hours=24)).isoformat(),
                       reason='TEMPORARY_MLB_READINESS_FINAL_SCORING_AUTHORIZED_BY_JAMES')
    receipt = event(label, details)
    updates = {label.lower(): receipt}
    if label == 'NFL_PAUSED':
        updates['restoreNoLaterThanUtc'] = details['restoreNoLaterThanUtc']
    atomic_state(CURRENT, {**state(), **updates})
    return {'receipt': receipt, 'nflStatus': expected[0], 'mlbStatus': expected[1],
            'restoreNoLaterThanUtc': state().get('restoreNoLaterThanUtc')}


def restoration_arguments():
    c = original()['scheduler'][NFL]['config']
    args = {'mode': 'update', 'id': NFL, 'kind': c['kind'], 'name': c['name'],
            'prompt': c['prompt'], 'rrule': c['rrule'], 'status': c['status'],
            'targetThreadId': c['target_thread_id'], 'destination': 'thread'}
    row = original()['scheduler'][NFL]['schedulerRow']
    args['notificationPolicy'] = row.get('notification_policy')
    return args


def mlb_pause_arguments():
    c = tomllib.loads((TASKS / MLB / 'automation.toml').read_text(encoding='utf-8'))
    return {'mode': 'update', 'id': MLB, 'kind': c['kind'], 'name': c['name'],
            'prompt': c['prompt'], 'rrule': c['rrule'], 'status': 'PAUSED',
            'targetThreadId': c['target_thread_id'], 'destination': 'thread'}


def restoration_reason(published, scored, deadline, as_of):
    if not 0 <= scored <= published:
        raise ValueError('INVALID_PAIR_SCORE_ACCOUNTING')
    if deadline is not None and as_of >= deadline:
        return '24_HOUR_LIMIT'
    return 'ALL_CURRENT_PAIRS_SCORED' if published > 0 and scored == published else None


def readiness_counts(rows, declaration, published_game_ids, scored, as_of):
    closed = {g['gameId'] for g in declaration['games'] if as_of >= datetime.fromisoformat(g['deadlineUtc'])}
    published = set(published_game_ids)
    return {'gamesAccountedFor': len(rows), 'expired': len(closed - published),
            'pending': sum(r['status'] == 'PENDING_INPUTS' and r['gameId'] not in closed | published for r in rows),
            'pairsPublished': len(published), 'awaitingFinals': len(published)-scored, 'scored': scored}


def decision():
    s = state()
    if s.get('nfl_restored'):
        return {'action': 'NFL_ALREADY_RESTORED', 'receipt': s['nfl_restored'],
                'archiveExecutionVerified': bool(s.get('nfl_archive_resumed'))}
    limit = datetime.fromisoformat(s['restoreNoLaterThanUtc']) if s.get('restoreNoLaterThanUtc') else None
    if limit is not None and now() >= limit:
        # The temporary MLB task must not hold NFL archiving hostage to a
        # missing/corrupt readiness, pair or scoring artifact after expiry.
        return {'action': 'RESTORE_NFL_NOW', 'restorationReason': '24_HOUR_LIMIT',
                'restoreNoLaterThanUtc': s['restoreNoLaterThanUtc'],
                'counts': None, 'countStatus': 'NOT_REQUIRED_BEFORE_HARD_LIMIT_RESTORATION',
                'mlbPauseArguments': mlb_pause_arguments(),
                'nflRestorationArguments': restoration_arguments()}
    frozen_pairs_unchanged(original())
    pairs = published_pairs(OUTPUT)
    scored = []
    for pair, pointer in pairs:
        path = OUTPUT / 'scores-by-pair' / (pair['commonPairId'] + '.json')
        if path.exists():
            result = read(json.loads(path.read_bytes()))
            if result.get('pair') != pointer['pair'] or result.get('gameId') != pair['gameId']:
                raise ValueError('SCORE_DOES_NOT_MATCH_SAVED_PAIR')
            scored.append(pair['commonPairId'])
    reason = restoration_reason(len(pairs), len(scored), limit, now())
    restore = reason is not None
    needs_restore = restore and not s.get('nfl_restored')
    readiness = json.loads((OUTPUT/'readiness-state.json').read_bytes())
    rows = list(readiness.get('games', {}).values())
    return {'action': 'NFL_ALREADY_RESTORED' if s.get('nfl_restored') else 'RESTORE_NFL_NOW' if restore else 'CONTINUE_MLB',
            'restorationReason': reason,
            'restoreNoLaterThanUtc': s.get('restoreNoLaterThanUtc'),
            'counts': readiness_counts(rows, read(original()['declaration']),
                                      [p['gameId'] for p, _ in pairs], len(scored), now()),
            'countDefinitions': 'Expired means unpublished deadline closed; pending excludes closed/published games. Readiness reflects last completed tick, not a fresh evidence claim.',
            'readinessLastTickAt': readiness.get('lastTickAt'),
            'mlbPauseArguments': mlb_pause_arguments() if needs_restore else None,
            'nflRestorationArguments': restoration_arguments() if needs_restore else None}


def tick():
    check = decision()
    if check['action'] != 'CONTINUE_MLB':
        return check
    errors = []
    try:
        result = resume(original()['declaration'])
    except Exception as error:
        result = {'status': 'READINESS_CHECK_FAILED', 'errorType': type(error).__name__}
        errors.append(result)
    # Scoring must not starve behind the production simulation lock/failure.
    try:
        scoring = result.get('scoring') or score(OUTPUT)
    except Exception as error:
        scoring = {'status': 'FINAL_SCORING_CHECK_FAILED', 'errorType': type(error).__name__}
        errors.append(scoring)
    receipt = event('MLB_READINESS_SCORING_CHECK', {'resume': result, 'scoring': scoring,
                    'failures': errors})
    return {'receipt': receipt, 'readinessStatus': result.get('status', 'CHECK_COMPLETED'),
            'failures': errors, **decision()}


def verify_restored_archive():
    if not state().get('nfl_restored'):
        raise ValueError('NFL_RESTORATION_MUST_BE_VERIFIED_FIRST')
    if state().get('nfl_archive_resumed'):
        return {'status': 'EXACT_RESTORED_ARCHIVE_RUN_REUSED', 'receipt': state()['nfl_archive_resumed']}
    # This is the original authorized archive, once after the scheduled switch;
    # no replacement collector, provider call, model or old-evidence overwrite.
    from server.sports_nfl_m1.forward_vintages import capture_forward_vintages
    result = capture_forward_vintages()
    for ref in original()['nflArchiveMetadata']:
        if reference(ref['originalRef']['path']) != ref['originalRef']:
            raise ValueError('ORIGINAL_NFL_ARCHIVE_METADATA_CHANGED')
    receipt = event('NFL_ARCHIVE_RESUMED_VERIFIED', {'result': result,
                    'scheduler': scheduler_snapshot(), 'originalArchiveMetadataUnchanged': True})
    atomic_state(CURRENT, {**state(), 'nfl_archive_resumed': receipt})
    return {'status': 'NFL_ARCHIVE_RESUMED_VERIFIED', 'receipt': receipt}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'paused', 'activated', 'decision', 'tick', 'restore-arguments', 'restored', 'verify-restored-archive'])
    cmd = parser.parse_args().command
    actions = {'prepare': prepare, 'paused': lambda: record_transition('NFL_PAUSED'),
               'activated': lambda: record_transition('MLB_ACTIVATED'), 'decision': decision, 'tick': tick,
               'restore-arguments': restoration_arguments, 'restored': lambda: record_transition('NFL_RESTORED'),
               'verify-restored-archive': verify_restored_archive}
    print(json.dumps(actions[cmd](), indent=2, default=str))
