"""Publish existing prior evidence without changing its scientific identity.

The Wave 2 definition fingerprints its original artifact-store implementation.
Deployment path selection and publication safety therefore live outside that
immutable scientific implementation. This module never fits or opens row data.
"""
from __future__ import annotations

import hashlib
import json
import os
import contextlib
from pathlib import Path
import re
import uuid
from typing import Any, Mapping

from ..sports_datasets.consumer import canonical_json_bytes
from .stage3_player_prior_artifact_store_v2 import PriorArtifactStoreV2Error, load_artifact


def runtime_prior_root() -> Path:
    runtime = os.environ.get('ASP_MODEL_STUDIO_RUNTIME_ROOT')
    configured = os.environ.get('ASP_MLB_PLAYER_PRIOR_V2_ROOT')
    isolated = os.environ.get('ASP_REQUIRE_ISOLATED_RUNTIME', '').lower() in ('1', 'true', 'yes')
    if runtime and not Path(runtime).expanduser().is_absolute():
        raise PriorArtifactStoreV2Error('PRIOR_V2_RUNTIME_ROOT_INVALID', 'Runtime root must be absolute.')
    if isolated and not runtime:
        raise PriorArtifactStoreV2Error('PRIOR_V2_RUNTIME_ROOT_INVALID', 'Isolated execution requires an explicit runtime root.')
    default = Path(__file__).resolve().parents[2] / '.runtime' / 'asp-model-studio'
    base = Path(runtime).expanduser().resolve() if runtime else default
    if isolated and base == default.resolve():
        raise PriorArtifactStoreV2Error('PRIOR_V2_RUNTIME_ROOT_INVALID', 'Isolated execution cannot use the operational default runtime.')
    if configured:
        value = Path(configured).expanduser()
        if not value.is_absolute():
            raise PriorArtifactStoreV2Error('PRIOR_V2_RUNTIME_ROOT_INVALID', 'Prior root must be absolute.')
        result = value.resolve()
        if isolated and not result.is_relative_to(base):
            raise PriorArtifactStoreV2Error('PRIOR_V2_RUNTIME_ROOT_INVALID', 'Isolated prior root escaped its runtime.')
        return result
    return (base / 'stage3-player-prior-authorities-v2').resolve()


def _project(value: str) -> str:
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value or ''):
        raise PriorArtifactStoreV2Error('PRIOR_V2_PROJECT_ID_INVALID', 'A safe project identity is required.')
    return value


def _contained(root: Path, relative: Path) -> Path:
    target = root / relative
    if not target.resolve().is_relative_to(root.resolve()):
        raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_PATH_INVALID', 'An object path escaped its governed root.')
    current = target
    while current != root:
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_PATH_INVALID', 'Linked object paths are not publication authority.')
        current = current.parent
    return target


@contextlib.contextmanager
def _pin_directory(path: Path):
    """On Windows deny directory rename/deletion while its child is published."""
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_PATH_INVALID', 'Publication directory is a link.')
    if os.name != 'nt':
        raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_PLATFORM_UNSUPPORTED', 'Atomic canonical publication requires the supported Windows directory-pinning implementation.')
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    # Attribute-only access does not participate in Windows sharing enforcement.
    handle = create(str(path), 0x80000000, 0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_DIRECTORY_UNAVAILABLE', 'Cannot pin publication directory.')
    try:
        class AttributeTag(ctypes.Structure):
            _fields_ = [('attributes', wintypes.DWORD), ('tag', wintypes.DWORD)]
        info = AttributeTag()
        query = kernel.GetFileInformationByHandleEx
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        query.restype = wintypes.BOOL
        if not query(handle, 9, ctypes.byref(info), ctypes.sizeof(info)) or info.attributes & 0x400:
            raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_PATH_INVALID', 'Cannot authenticate an ordinary publication directory.')
        yield
    finally:
        close(handle)


@contextlib.contextmanager
def _pinned_parent(path: Path):
    """Pin each ancestor before creating/entering its child; never follow junctions."""
    absolute = Path(os.path.abspath(path))
    parts = list(reversed([absolute, *absolute.parents]))
    with contextlib.ExitStack() as pins:
        for directory in parts:
            if not directory.exists():
                directory.mkdir()
            pins.enter_context(_pin_directory(directory))
        yield


def _write_pinned(path: Path, content: bytes) -> bool:
    with _pinned_parent(path.parent):
        if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
            raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_PATH_INVALID', 'Publication target is a link.')
        return _create_exact(path, content)


def _create_exact(path: Path, content: bytes) -> bool:
    """Atomically create, never replace: a racing different writer fails closed."""
    if path.exists():
        if path.read_bytes() != content:
            raise PriorArtifactStoreV2Error('PRIOR_V2_CONTENT_ADDRESS_CONFLICT', 'Destination bytes conflict with the approved object.')
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != content:
                raise PriorArtifactStoreV2Error('PRIOR_V2_CONTENT_ADDRESS_CONFLICT', 'Destination changed during publication.')
            return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


def authenticate_existing_bundle(
    *, source_root: Path, project_id: str, expected_authority_id: str,
    expected_final_fitted_id: str, expected_project_authority: Mapping[str, Any],
    expected_companion_sha256: str,
) -> dict[str, Any]:
    from . import stage3_player_prior_authority_v2 as science
    source_input = Path(os.path.abspath(source_root))
    _contained(Path(source_input.anchor), source_input.relative_to(source_input.anchor))
    source = source_input.resolve()
    project = _project(project_id)
    pointer = _contained(source, Path('projects') / project / 'current.json')
    if not pointer.is_file():
        raise PriorArtifactStoreV2Error('PRIOR_V2_ARTIFACT_MISSING', 'Approved source pointer is missing.')
    pointer_bytes = pointer.read_bytes()
    pointer_value = json.loads(pointer_bytes)
    pointer_sha = str(pointer_value.get('authoritySha256') or '')
    if not re.fullmatch(r'[0-9a-f]{64}', pointer_sha):
        raise PriorArtifactStoreV2Error('PRIOR_V2_CURRENT_POINTER_INVALID', 'Pointer content address is invalid.')
    _contained(source, Path('objects/sha256') / pointer_sha / 'manifest.json')
    expected_relative = (Path('objects/sha256') / pointer_sha / 'manifest.json').as_posix()
    if (canonical_json_bytes(pointer_value) != pointer_bytes
        or pointer_value.get('schemaVersion') != 'MLB_PLAYER_STATE_PRIOR_V2_CURRENT_POINTER_V1'
        or pointer_value.get('projectId') != project
        or pointer_value.get('manifestRelativePath') != expected_relative):
        raise PriorArtifactStoreV2Error('PRIOR_V2_CURRENT_POINTER_INVALID', 'Pointer snapshot contract differs.')
    bundle = load_artifact(pointer_sha, root=source)
    if bundle is None or bundle.get('authorityId') != expected_authority_id:
        raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_AUTHORITY_MISMATCH', 'Source authority differs from the approved identity.')
    references = [bundle.get('definition') or {}, bundle.get('foldContract') or {},
                  *(bundle.get('foldAuthorities') or []), bundle.get('finalDevelopmentAuthority') or {}]
    for reference in references:
        checksum = str(reference.get('artifactSha256') or '')
        if not re.fullmatch(r'[0-9a-f]{64}', checksum):
            raise PriorArtifactStoreV2Error('PRIOR_V2_ARTIFACT_SHA_INVALID', 'A referenced object address is malformed.')
        _contained(source, Path('objects/sha256') / checksum / 'manifest.json')
    definition_ref = bundle.get('definition') or {}
    definition = load_artifact(str(definition_ref.get('artifactSha256') or ''), root=source)
    verified = science._validate_bundle(bundle, expected_definition=definition, root=source)
    if (definition.get('projectAuthority') != dict(expected_project_authority)
        or definition.get('projectAuthority', {}).get('projectId') != project
        or verified.get('finalDevelopmentAuthority', {}).get('fittedId') != expected_final_fitted_id
        or definition.get('companionAuthority', {}).get('manifestSha256') != expected_companion_sha256):
        raise PriorArtifactStoreV2Error('PRIOR_V2_PUBLICATION_AUTHORITY_MISMATCH', 'Project, parent, or final-development authority differs.')
    references = [pointer_sha, verified['definition']['artifactSha256'], verified['foldContract']['artifactSha256'],
                  *[item['artifactSha256'] for item in verified['foldAuthorities']], verified['finalDevelopmentAuthority']['artifactSha256']]
    objects = []
    for checksum in sorted(set(references)):
        relative = Path('objects/sha256') / checksum / 'manifest.json'
        path = _contained(source, relative)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != checksum or canonical_json_bytes(json.loads(raw)) != raw:
            raise PriorArtifactStoreV2Error('PRIOR_V2_ARTIFACT_CHECKSUM_MISMATCH', 'A referenced object failed its content address.')
        objects.append({'relativePath': relative.as_posix(), 'sha256': checksum, 'byteCount': len(raw), 'content': raw})
    root_relative = pointer_value['manifestRelativePath']
    if root_relative not in {obj['relativePath'] for obj in objects}:
        raise PriorArtifactStoreV2Error('PRIOR_V2_ARTIFACT_MISSING', 'Approved parent object is missing.')
    # Authenticate every fitted child's sealed counters without opening any Gold/companion partition.
    children = [*verified['foldAuthorities'], verified['finalDevelopmentAuthority']]
    for child in children:
        value = load_artifact(child['artifactSha256'], root=source)
        evidence = value.get('fitEvidence') or {}
        if evidence.get('targetColumnsRead') != [] or evidence.get('finalOotRowsRead') != 0:
            raise PriorArtifactStoreV2Error('PRIOR_V2_PROHIBITED_ACTIVITY_RECORDED', 'A fitted child lacks sealed zero-read evidence.')
    return {'sourceRoot': source, 'projectId': project, 'bundle': verified, 'definition': definition,
            'objects': objects, 'pointerRelativePath': pointer.relative_to(source), 'pointerBytes': pointer_bytes,
            'bundleRelativePath': root_relative}


def publish_existing_bundle(*, destination_root: Path, **authentication: Any) -> dict[str, Any]:
    """Authenticate everything first, publish immutable children then parent then locator."""
    validated = authenticate_existing_bundle(**authentication)
    destination_input = Path(os.path.abspath(Path(destination_root).expanduser()))
    _contained(Path(destination_input.anchor), destination_input.relative_to(destination_input.anchor))
    destination = destination_input.resolve()
    source = validated['sourceRoot']
    objects = sorted(validated['objects'], key=lambda item: (item['relativePath'] == validated['bundleRelativePath'], item['relativePath']))
    prepared = [(item, _contained(destination, Path(item['relativePath']))) for item in objects]
    pointer = _contained(destination, validated['pointerRelativePath'])
    for item, target in prepared:
        if target.exists() and target.read_bytes() != item['content']:
            raise PriorArtifactStoreV2Error('PRIOR_V2_CONTENT_ADDRESS_CONFLICT', 'Preflight rejected a destination collision.')
    if pointer.exists() and pointer.read_bytes() != validated['pointerBytes']:
        raise PriorArtifactStoreV2Error('PRIOR_V2_POINTER_CONFLICT', 'Destination already names a different prior authority.')
    if (source / validated['pointerRelativePath']).read_bytes() != validated['pointerBytes']:
        raise PriorArtifactStoreV2Error('PRIOR_V2_SOURCE_CHANGED', 'Source pointer changed during authentication.')
    results = []
    order = []
    for item, target in prepared:
        _contained(destination, Path(item['relativePath']))
        if item['relativePath'] == validated['bundleRelativePath'] and (source / validated['pointerRelativePath']).read_bytes() != validated['pointerBytes']:
            raise PriorArtifactStoreV2Error('PRIOR_V2_SOURCE_CHANGED', 'Source pointer changed before parent publication.')
        created = _write_pinned(target, item['content'])
        if hashlib.sha256(target.read_bytes()).hexdigest() != item['sha256']:
            raise PriorArtifactStoreV2Error('PRIOR_V2_ARTIFACT_CHECKSUM_MISMATCH', 'Destination verification failed.')
        results.append({k:v for k,v in item.items() if k != 'content'} | {'sourcePath': str(source / item['relativePath']), 'destinationPath': str(target), 'created': created})
        if created:
            order.append(item['relativePath'])
    if (source / validated['pointerRelativePath']).read_bytes() != validated['pointerBytes']:
        raise PriorArtifactStoreV2Error('PRIOR_V2_SOURCE_CHANGED', 'Source pointer changed before locator publication.')
    _contained(destination, validated['pointerRelativePath'])
    pointer_created = _write_pinned(pointer, validated['pointerBytes'])
    if pointer_created:
        order.append(validated['pointerRelativePath'].as_posix())
    # Full post-publication validation is independent of the source paths.
    authenticate_existing_bundle(source_root=destination, **{k:v for k,v in authentication.items() if k != 'source_root'})
    for item in objects:
        if (source / item['relativePath']).read_bytes() != item['content']:
            raise PriorArtifactStoreV2Error('PRIOR_V2_SOURCE_CHANGED', 'Source changed during publication.')
    if (source / validated['pointerRelativePath']).read_bytes() != validated['pointerBytes']:
        raise PriorArtifactStoreV2Error('PRIOR_V2_SOURCE_CHANGED', 'Source pointer changed during publication.')
    return {'schemaVersion': 'MLB_PRIOR_CANONICAL_PUBLICATION_V1', 'projectId': validated['projectId'],
            'sourceRoot': str(source), 'destinationRoot': str(destination), 'objects': results,
            'objectsCreated': sum(item['created'] for item in results), 'objectsReused': sum(not item['created'] for item in results),
            'pointerCreated': pointer_created, 'pointerPath': str(pointer), 'pointerSha256': hashlib.sha256(validated['pointerBytes']).hexdigest(),
            'publicationOrder': order, 'authorityId': validated['bundle']['authorityId'],
            'finalDevelopmentAuthority': validated['bundle']['finalDevelopmentAuthority'],
            'foldAuthorities': validated['bundle']['foldAuthorities'], 'definition': validated['bundle']['definition'],
            'foldContract': validated['bundle']['foldContract'], 'targetColumnsRead': [], 'finalOotRowsRead': 0,
            'finalOotOpens': 0, 'predictiveFits': 0, 'scienceIdentitiesCreated': 0, 'registrationEventsAppended': 0}
