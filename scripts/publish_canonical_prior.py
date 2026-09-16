"""Publish the user's exact Wave 2 objects; operational SQLite stays read-only."""
from pathlib import Path
import contextlib
import datetime
import hashlib
import json
import os
import sqlite3
import sys

WORK = Path(r'C:\Users\james\worktrees\asp-model-studio-tenant-workflow-repair-v1')
PRIMARY = Path(r'C:\Users\james\asp-model-studio')
SOURCE = PRIMARY / '.tmp/asp-player-prior-wave2/.runtime/asp-model-studio/stage3-player-prior-authorities-v2'
DEST = PRIMARY / '.runtime/asp-model-studio/stage3-player-prior-authorities-v2'
DB = PRIMARY / '.runtime/asp-model-studio/persistence/asp_model_studio.db'
GOLD = Path(r'C:\Users\james\asp-data-staging\mlb-current-statcast-gold-v1')
REPORTS = WORK / 'docs/repair-evidence'
PROJECT = 'asp-mtlozhdx'
AUTHORITY = 'MLB_PLAYER_STATE_PRIOR_AUTHORITY_V2:sha256:9d9cfaf34f87be67f7d3ab2b8b024d83a6fc5e8abe0dde8de7be0866f1b8366e'
FINAL = 'MLB_PLAYER_STATE_FITTED_PRIOR_V2:FINAL_DEVELOPMENT:sha256:5ae0f9f560f83935e1f89440657ac4080afc33ac3318c3c2c8e50656a9eee526'
GOLD_SHA = '67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758'
COMPANION_SHA = '98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33'
sys.path.insert(0, str(WORK))
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['ASP_MLB_PLAYER_PRIOR_V2_ROOT'] = str(SOURCE)
os.environ.pop('ASP_REQUIRE_ISOLATED_RUNTIME', None)
violations = []
blocked_dependency_probes = []

def path_of(value):
    return Path(os.fsdecode(value)).resolve()

def allowed_write(path):
    return path.is_relative_to(DEST) or path.is_relative_to(REPORTS)

def guard(event, args):
    if event == 'subprocess.Popen' and args[1] == 'lscpu':
        blocked_dependency_probes.append('numpy optional CPU probe: lscpu; not executed')
        raise OSError('CPU probing is disabled during publication')
    if event in {'socket.connect', 'socket.getaddrinfo', 'subprocess.Popen', 'os.system'}:
        violations.append(event)
        raise RuntimeError('Network and child processes are forbidden during publication')
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        path = path_of(args[0])
        if 'ai-sports-predictor' in path.parts:
            raise RuntimeError('Excluded repository access forbidden')
        if path.suffix.lower() in {'.parquet', '.pq', '.arrow', '.feather', '.pkl', '.pickle', '.joblib', '.npy', '.npz'}:
            violations.append('row_or_model_file_open')
            raise RuntimeError('Row/model files are forbidden')
        mode, flags = args[1], args[2]
        writing = (isinstance(mode, str) and any(c in mode for c in 'wax+')) or bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC))
        if writing and not allowed_write(path):
            violations.append('write_outside_publication_or_receipt')
            raise RuntimeError('Write outside exact publication/receipt roots forbidden')
    if event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.rename', 'os.link'}:
        for value in args[:2] if event in {'os.rename', 'os.link'} else args[:1]:
            if isinstance(value, (str, bytes, os.PathLike)) and not allowed_write(path_of(value)):
                violations.append('filesystem_mutation_outside_publication_or_receipt')
                raise RuntimeError('Filesystem mutation outside approved roots forbidden')
    if event == 'sqlite3.connect' and not str(args[0]).endswith('?mode=ro'):
        violations.append('non_read_only_database_connect')
        raise RuntimeError('Only explicit read-only database connections permitted')

sys.addaudithook(guard)

def digest(data):
    return hashlib.sha256(data).hexdigest()

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')

class ReadOnlyDatabase:
    path = DB
    def connect(self):
        connection = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA query_only=ON')
        return connection
    @contextlib.contextmanager
    def connection(self):
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

def protected_snapshot(database):
    with database.connection() as connection:
        connection.execute('BEGIN')
        names = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        protected = {'projects', 'project_collaborators', 'resource_permissions', 'sports_dataset_registrations', 'sports_dataset_partitions', 'project_dataset_links', 'active_modeling_dataset_versions', 'project_dataset_activation_events', 'run_records', 'candidate_selection_decisions', 'models', 'model_versions', 'export_artifacts', 'holdout_exposures', 'sports_dataset_query_audit', 'workflow_state', 'schema_migrations'}
        counts = {}
        for table in sorted(names):
            if table in protected or table.startswith('stage3_'):
                rows = [tuple(row) for row in connection.execute('SELECT * FROM "' + table + '"')]
                counts[table] = {'rows': len(rows), 'sha256': digest(b'\n'.join(sorted(canonical(row) for row in rows)))}
        integrity = [row[0] for row in connection.execute('PRAGMA integrity_check')]
        assert integrity == ['ok'], 'Primary SQLite integrity failed'
    return {'tables': counts, 'databaseIntegrity': integrity}

def source_inventory():
    inventory = []
    for path in sorted(SOURCE.rglob('*')):
        if path.is_file():
            assert path.suffix == '.json', 'Unexpected non-JSON prior-store file'
            raw = path.read_bytes()
            inventory.append({'path': str(path), 'bytes': len(raw), 'sha256': digest(raw)})
    return inventory

def parent_manifests():
    records = []
    for root, expected in ((GOLD, GOLD_SHA), (GOLD / 'sufficient-statistics', COMPANION_SHA)):
        path = root / 'publications/sha256' / expected / 'manifest.json'
        raw = path.read_bytes()
        assert digest(raw) == expected, 'Parent manifest checksum mismatch'
        records.append({'path': str(path), 'bytes': len(raw), 'sha256': expected})
    return records

def main():
    from server.sports_current_statcast.stage3_model_laboratory import persisted_project_workflow_state
    from server.sports_current_statcast.stage3_prior_publication_v2 import authenticate_existing_bundle, publish_existing_bundle
    database = ReadOnlyDatabase()
    before = protected_snapshot(database)
    inventory = source_inventory()
    parents = parent_manifests()
    state = persisted_project_workflow_state(database, PROJECT)
    assert state['priorAuthority']['status'] == 'AUTHENTICATED'
    assert state['authority']['goldManifestSha'] == GOLD_SHA
    assert state['treatment']['status'] == 'DRAFT' and state['treatment']['canAdopt'] is False
    pointer = json.loads((SOURCE / 'projects' / PROJECT / 'current.json').read_bytes())
    parent = json.loads((SOURCE / pointer['manifestRelativePath']).read_bytes())
    definition = json.loads((SOURCE / 'objects/sha256' / parent['definition']['artifactSha256'] / 'manifest.json').read_bytes())
    project_authority = {key: state['authority'].get(key) for key in definition['projectAuthority']}
    options = {'source_root': SOURCE, 'project_id': PROJECT, 'expected_authority_id': AUTHORITY, 'expected_final_fitted_id': FINAL, 'expected_project_authority': project_authority, 'expected_companion_sha256': COMPANION_SHA}
    authenticated = authenticate_existing_bundle(**options)
    assert len(authenticated['objects']) == 9 and len(authenticated['bundle']['foldAuthorities']) == 5
    report = {'capturedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sourceRoot': str(SOURCE), 'destinationRoot': str(DEST), 'canonicalExistedBefore': DEST.exists(), 'sourceInventoryBefore': inventory, 'parentManifests': parents, 'projectAuthority': project_authority, 'authorityId': AUTHORITY, 'definition': authenticated['bundle']['definition'], 'foldContract': authenticated['bundle']['foldContract'], 'outputContractChecksum': definition['outputContractsChecksum'], 'rights': definition.get('rights'), 'sourceObjectClosure': [{key:value for key,value in obj.items() if key != 'content'} for obj in authenticated['objects']], 'protectedBefore': before, 'blockedDependencyProbes': blocked_dependency_probes}
    if '--publish' not in sys.argv:
        report['status'] = 'AUTHENTICATED_PREFLIGHT_ONLY'
        name = 'canonical-publication-preflight.json'
    else:
        publication = publish_existing_bundle(destination_root=DEST, **options)
        replay = publish_existing_bundle(destination_root=DEST, **options)
        assert replay['objectsCreated'] == 0 and replay['objectsReused'] == 9 and replay['pointerCreated'] is False
        os.environ['ASP_MLB_PLAYER_PRIOR_V2_ROOT'] = str(DEST)
        canonical_state = persisted_project_workflow_state(database, PROJECT)
        assert canonical_state['priorAuthority']['status'] == 'AUTHENTICATED'
        counts = canonical_state['priorAuthority']['v1']
        assert [counts[key] for key in ('readyV1FeatureCount', 'readyV2FeatureCount', 'retiredFeatureCount', 'blockedFeatureCount')] == [11, 10, 3, 0]
        assert canonical_state['treatment']['status'] == 'DRAFT' and canonical_state['treatment']['canAdopt'] is False
        after = protected_snapshot(database)
        assert before == after, 'Protected operational evidence changed during publication'
        assert source_inventory() == inventory, 'Source prior store changed'
        assert parent_manifests() == parents, 'Parent manifest changed'
        assert not violations, 'Publication guard recorded a prohibited attempt'
        report.update({'status': 'CANONICAL_OBJECTS_INDEPENDENTLY_AUTHENTICATED', 'publication': publication, 'idempotentReplay': replay, 'protectedAfter': after, 'sourceInventoryUnchanged': True, 'parentManifestsUnchanged': True, 'resolverVerification': {'codeRoot': str(WORK), 'metadataDatabase': str(DB), 'priorRoot': str(DEST), 'registeredProjectId': PROJECT, 'status': canonical_state['priorAuthority']['status'], 'v1Features': 11, 'v2Features': 10, 'retiredFields': 3, 'missingPriorEvidenceBlockers': 0, 'foldAuthorities': len(canonical_state['priorAuthority']['wave2']['foldAuthorities']), 'finalDevelopmentAuthority': FINAL, 'treatment': canonical_state['treatment'], 'population': canonical_state['population'], 'primaryCheckoutContainsV2Resolver': (PRIMARY / 'server/sports_current_statcast/stage3_player_prior_resolution_v2.py').exists(), 'operationalProcessUpdated': False}, 'finalOotOpens': 0, 'finalOotTargetReads': 0, 'targetColumnsRead': [], 'currentGoldMutations': 0, 'predictiveFits': 0, 'tuningRuns': 0, 'scoringRuns': 0, 'calibrations': 0, 'promotions': 0, 'championMutations': 0, 'featureSetRegistrations': 0, 'treatmentPolicyAdoptions': 0, 'providerCalls': 0, 'guardViolations': violations, 'registrationEventRequired': False, 'registrationEventReason': 'Existing exact project dataset registration and immutable specification authenticate the same existing prior identity; only content objects and its locator need publication.'})
        name = 'canonical-publication-receipt.json'
    target = REPORTS / name
    if target.exists():
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = target.with_name(target.stem + '-' + stamp + target.suffix)
    with target.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({'status': report['status'], 'receipt': str(target), 'closureObjects': 9, 'allSourceFilesPreserved': len(inventory), 'canonicalObjectsCreated': report.get('publication', {}).get('objectsCreated'), 'replayObjectsCreated': report.get('idempotentReplay', {}).get('objectsCreated'), 'prohibitedActivityAttempts': violations}))

if __name__ == '__main__':
    main()
