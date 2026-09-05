from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from server.sports_current_statcast import stage3_prior_publication_v2 as publication
from server.sports_current_statcast import stage3_player_prior_authority_v2 as science
from server.sports_current_statcast.stage3_player_prior_artifact_store_v2 import (
    PriorArtifactStoreV2Error, publish_current_bundle,
)
from tests.sports_stage3_player_prior_authority_v2_test import _chronological_bundle_fixture


@pytest.fixture
def existing(tmp_path, monkeypatch):
    source = tmp_path / 'existing-science'
    fixture = _chronological_bundle_fixture(monkeypatch, source)
    bundle = fixture['bundle']
    project = fixture['definition']['projectAuthority']['projectId']
    publish_current_bundle(project, bundle, root=source)
    args = dict(source_root=source, destination_root=tmp_path / 'canonical', project_id=project,
                expected_authority_id=bundle['authorityId'],
                expected_final_fitted_id=bundle['finalDevelopmentAuthority']['fittedId'],
                expected_project_authority=fixture['definition']['projectAuthority'],
                expected_companion_sha256=fixture['definition']['companionAuthority']['manifestSha256'])
    fixture['publication'] = args
    # From this boundary onward even a synthetic refit or row-data open is an error.
    def prohibited(*args, **kwargs):
        raise AssertionError('Publication attempted a fit or row-data read')
    monkeypatch.setattr(science, 'fit_fold_authority', prohibited)
    monkeypatch.setattr(science, 'load_authenticated_development_companion', prohibited)
    monkeypatch.setattr(science.pq, 'ParquetFile', prohibited)
    monkeypatch.setattr(science.pq, 'read_table', prohibited)
    return fixture


def test_absolute_runtime_root_does_not_depend_on_cwd(tmp_path, monkeypatch):
    monkeypatch.delenv('ASP_REQUIRE_ISOLATED_RUNTIME', raising=False)
    monkeypatch.delenv('ASP_MLB_PLAYER_PRIOR_V2_ROOT', raising=False)
    monkeypatch.delenv('ASP_MODEL_STUDIO_RUNTIME_ROOT', raising=False)
    before = publication.runtime_prior_root()
    monkeypatch.chdir(tmp_path)
    assert publication.runtime_prior_root() == before
    assert before.is_absolute()


def test_runtime_override_is_resolved_at_request_time(tmp_path, monkeypatch):
    monkeypatch.delenv('ASP_MLB_PLAYER_PRIOR_V2_ROOT', raising=False)
    monkeypatch.setenv('ASP_MODEL_STUDIO_RUNTIME_ROOT', str(tmp_path / 'a'))
    assert publication.runtime_prior_root() == tmp_path / 'a/stage3-player-prior-authorities-v2'
    monkeypatch.setenv('ASP_MODEL_STUDIO_RUNTIME_ROOT', str(tmp_path / 'b'))
    assert publication.runtime_prior_root() == tmp_path / 'b/stage3-player-prior-authorities-v2'


@pytest.mark.parametrize('setting', ['relative-runtime', 'relative-prior', 'isolated-missing', 'isolated-escape'])
def test_runtime_overrides_fail_closed(tmp_path, monkeypatch, setting):
    monkeypatch.delenv('ASP_MLB_PLAYER_PRIOR_V2_ROOT', raising=False)
    monkeypatch.delenv('ASP_MODEL_STUDIO_RUNTIME_ROOT', raising=False)
    monkeypatch.delenv('ASP_REQUIRE_ISOLATED_RUNTIME', raising=False)
    if setting == 'relative-runtime':
        monkeypatch.setenv('ASP_MODEL_STUDIO_RUNTIME_ROOT', 'relative')
    elif setting == 'relative-prior':
        monkeypatch.setenv('ASP_MLB_PLAYER_PRIOR_V2_ROOT', 'relative')
    else:
        monkeypatch.setenv('ASP_REQUIRE_ISOLATED_RUNTIME', '1')
        if setting == 'isolated-escape':
            monkeypatch.setenv('ASP_MODEL_STUDIO_RUNTIME_ROOT', str(tmp_path / 'allowed'))
            monkeypatch.setenv('ASP_MLB_PLAYER_PRIOR_V2_ROOT', str(tmp_path / 'outside'))
    with pytest.raises(PriorArtifactStoreV2Error):
        publication.runtime_prior_root()


def test_manifest_last_source_equality_and_idempotent_replay(existing):
    args = existing['publication']
    before = {p.relative_to(args['source_root']): p.read_bytes() for p in args['source_root'].rglob('*.json')}
    receipt = publication.publish_existing_bundle(**args)
    assert receipt['objectsCreated'] == 9
    assert receipt['objectsReused'] == 0
    assert receipt['pointerCreated']
    assert receipt['publicationOrder'][-1] == f"projects/{args['project_id']}/current.json"
    pointer = json.loads((args['source_root'] / receipt['publicationOrder'][-1]).read_bytes())
    assert receipt['publicationOrder'][-2] == pointer['manifestRelativePath']
    assert receipt['targetColumnsRead'] == []
    assert receipt['finalOotRowsRead'] == receipt['finalOotOpens'] == receipt['predictiveFits'] == 0
    assert receipt['scienceIdentitiesCreated'] == 0
    for path, content in before.items():
        assert (args['source_root'] / path).read_bytes() == content
        assert (args['destination_root'] / path).read_bytes() == content
    replay = publication.publish_existing_bundle(**args)
    assert replay['objectsCreated'] == 0
    assert replay['objectsReused'] == 9
    assert replay['publicationOrder'] == []
    assert replay['pointerCreated'] is False


@pytest.mark.parametrize('kind', ['object', 'pointer'])
def test_collisions_reject_before_any_publication(existing, kind):
    args = existing['publication']
    if kind == 'object':
        relative = Path('objects/sha256') / existing['childReceipts'][0]['sha256'] / 'manifest.json'
    else:
        relative = Path('projects') / args['project_id'] / 'current.json'
    collision = args['destination_root'] / relative
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b'conflicting-existing-bytes')
    before = {p.relative_to(args['destination_root']): p.read_bytes() for p in args['destination_root'].rglob('*') if p.is_file()}
    with pytest.raises(PriorArtifactStoreV2Error):
        publication.publish_existing_bundle(**args)
    after = {p.relative_to(args['destination_root']): p.read_bytes() for p in args['destination_root'].rglob('*') if p.is_file()}
    assert after == before


def test_missing_child_rejects_without_creating_destination(existing):
    args = existing['publication']
    path = args['source_root'] / 'objects/sha256' / existing['childReceipts'][0]['sha256'] / 'manifest.json'
    path.unlink()
    with pytest.raises((PriorArtifactStoreV2Error, science.PlayerPriorAuthorityV2Error)):
        publication.publish_existing_bundle(**args)
    assert not args['destination_root'].exists()


@pytest.mark.parametrize('tamper', ['prior-parameters', 'feature-order', 'parent-manifest', 'fold-membership', 'output-contract', 'project-identity', 'file-path', 'adjacent-manifest'])
def test_tampering_rejected_on_disposable_objects(existing, tamper):
    args = existing['publication']
    source = args['source_root']
    if tamper in ('file-path', 'adjacent-manifest'):
        path = source / 'projects' / args['project_id'] / 'current.json'
        value = json.loads(path.read_bytes())
        if tamper == 'file-path':
            value['manifestRelativePath'] = '../manifest.json'
        else:
            (source / 'projects' / args['project_id'] / 'manifest.json').write_bytes(b'{}')
            value['manifestRelativePath'] = 'projects/' + args['project_id'] + '/manifest.json'
    elif tamper == 'prior-parameters':
        path = source / 'objects/sha256' / existing['childReceipts'][0]['sha256'] / 'manifest.json'
        value = json.loads(path.read_bytes())
        value['parameters'] = {'tampered': True}
    elif tamper == 'fold-membership':
        path = source / 'objects/sha256' / existing['contractReceipt']['sha256'] / 'manifest.json'
        value = json.loads(path.read_bytes())
        value['folds'][0]['trainingMembershipChecksum'] = '0' * 64
    else:
        path = source / 'objects/sha256' / existing['definitionReceipt']['sha256'] / 'manifest.json'
        value = json.loads(path.read_bytes())
        if tamper == 'project-identity':
            value['projectAuthority']['projectId'] = 'other-project'
        elif tamper == 'parent-manifest':
            value['gold']['manifestSha256'] = '0' * 64
        elif tamper == 'feature-order':
            value['bindings'] = list(reversed(value.get('bindings', []))) + [{'invalid': True}]
        else:
            value['outputContracts'] = {'tampered': True}
    path.write_bytes(publication.canonical_json_bytes(value))
    with pytest.raises((PriorArtifactStoreV2Error, science.PlayerPriorAuthorityV2Error)):
        publication.publish_existing_bundle(**args)
    assert not args['destination_root'].exists()


def test_correctly_hashed_bundle_for_wrong_project_is_rejected(existing):
    args = copy.deepcopy(existing['publication'])
    args['expected_project_authority']['projectId'] = 'foreign-project'
    with pytest.raises(PriorArtifactStoreV2Error, match='Project'):
        publication.publish_existing_bundle(**args)
    assert not args['destination_root'].exists()


def test_atomic_create_never_overwrites_racing_writer(tmp_path, monkeypatch):
    target = tmp_path / 'manifest.json'
    original_link = publication.os.link
    def racing_link(source, destination):
        Path(destination).write_bytes(b'other-writer')
        original_link(source, destination)
    monkeypatch.setattr(publication.os, 'link', racing_link)
    with pytest.raises(PriorArtifactStoreV2Error):
        publication._create_exact(target, b'approved')
    assert target.read_bytes() == b'other-writer'
    assert not list(tmp_path.glob('.manifest.json.*.tmp'))


def test_isolated_runtime_cannot_be_operational_default(monkeypatch):
    default = Path(publication.__file__).resolve().parents[2] / '.runtime/asp-model-studio'
    monkeypatch.setenv('ASP_REQUIRE_ISOLATED_RUNTIME', '1')
    monkeypatch.setenv('ASP_MODEL_STUDIO_RUNTIME_ROOT', str(default))
    monkeypatch.delenv('ASP_MLB_PLAYER_PRIOR_V2_ROOT', raising=False)
    with pytest.raises(PriorArtifactStoreV2Error):
        publication.runtime_prior_root()


def test_unrelated_objects_are_not_published(existing):
    args = existing['publication']
    unrelated = args['source_root'] / 'objects/sha256' / ('e' * 64) / 'manifest.json'
    unrelated.parent.mkdir(parents=True)
    unrelated.write_bytes(b'not an authority and not a valid object')
    receipt = publication.publish_existing_bundle(**args)
    assert receipt['objectsCreated'] == 9
    assert not (args['destination_root'] / unrelated.relative_to(args['source_root'])).exists()


def test_source_pointer_change_before_publication_is_rejected(existing, monkeypatch):
    args = existing['publication']
    original = science._validate_bundle
    pointer = args['source_root'] / 'projects' / args['project_id'] / 'current.json'
    def change_pointer(*values, **keywords):
        result = original(*values, **keywords)
        raw = json.loads(pointer.read_bytes())
        raw['authoritySha256'] = 'f' * 64
        pointer.write_bytes(publication.canonical_json_bytes(raw))
        return result
    monkeypatch.setattr(science, '_validate_bundle', change_pointer)
    with pytest.raises(PriorArtifactStoreV2Error, match='Source pointer changed'):
        publication.publish_existing_bundle(**args)
    assert not args['destination_root'].exists()


def test_directory_cannot_be_swapped_while_child_is_written(tmp_path, monkeypatch):
    directory = tmp_path / 'canonical'
    directory.mkdir()
    target = directory / 'manifest.json'
    original = publication._create_exact
    def attempt_swap(path, content):
        with pytest.raises(OSError):
            directory.rename(tmp_path / 'moved')
        return original(path, content)
    monkeypatch.setattr(publication, '_create_exact', attempt_swap)
    assert publication._write_pinned(target, b'approved')
    assert target.read_bytes() == b'approved'
    assert not (tmp_path / 'moved').exists()
