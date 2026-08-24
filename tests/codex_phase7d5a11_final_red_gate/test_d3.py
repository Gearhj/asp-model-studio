"""Phase 7D.5A.11 D3 final-red tests for Silver verification authority.

Every filesystem object in this module is synthetic and lives below pytest's
disposable temporary root.  The tests deliberately use the production source
publisher, Silver publisher, Stage-B resolver, and Silver verifier; there is no
test-local verification implementation.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling import silver_publish as SP
from server.sports_modeling.feature_contract import FEATURE_NAMES
from tests import _silver_fixture as F


SIG = "D3_REGISTRY_AND_PREPUBLICATION_HANDLE_AUTHORITY:"
HARNESS = "PHASE7D5A11_D3_HARNESS_ERROR:"
REPO = Path(__file__).resolve().parents[2]
_CANONICAL_ISSUER = (
    REPO
    / "tests"
    / "codex_phase7d5a7_contract"
    / "canonical_synthetic_issuer_registry.json"
)
_EXPECTED_REJECTIONS = (
    SP.SilverPublishError,
    SP.SourceAuthorityError,
    TypeError,
    PermissionError,
)


@pytest.fixture
def publication(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Create one real, valid publication using only synthetic source rows."""
    _install_canonical_issuer(tmp_path, monkeypatch)
    return F.publish_silver_hermetic(tmp_path / "publication")


def _install_canonical_issuer(root: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Install the committed synthetic issuer under the disposable test root."""
    target = root / "issuer-authority" / "canonical-issuer-registry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_CANONICAL_ISSUER.read_bytes())
    monkeypatch.setenv(SP.SI.ISSUER_REGISTRY_ENV, str(target))
    return target


def _read_json(path: Path) -> dict:
    return json.loads(path.read_bytes().decode("utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value))


def _silver_registry(publication: dict[str, object]) -> Path:
    return Path(publication["silver_root"]) / "silver-registry.json"


def _unregistered_object_clone(
    publication: dict[str, object], root: Path, label: str
) -> Path:
    """Copy only the immutable object, intentionally omitting the registry."""
    silver_root = root / label
    target = (
        silver_root
        / "objects"
        / "sha256"
        / str(publication["manifest_sha"])
    )
    target.parent.mkdir(parents=True, exist_ok=False)
    shutil.copytree(Path(publication["object_dir"]), target)
    assert not (silver_root / "silver-registry.json").exists()
    return silver_root


def _node_signature(name: str) -> str:
    return f"{SIG}{name}:"


def _assert_verification_rejected(
    operation: Callable[[], object], detail: str, node_signature: str
) -> None:
    """Require an authority rejection while allowing setup failures to escape."""
    try:
        operation()
    except _EXPECTED_REJECTIONS:
        return
    pytest.fail(f"{node_signature} verifier accepted {detail}")


def _candidate_derived_expected_source(publication: dict[str, object]) -> SimpleNamespace:
    receipt = _read_json(
        Path(publication["object_dir"]) / "transformation-receipt.json"
    )
    # These are exclusively candidate-declared fields.  This object was not
    # issued by Stage B and deliberately has no production capability token.
    return SimpleNamespace(
        dataset_version_id=receipt["sourceDatasetVersionId"],
        object_path=str(Path(publication["object_dir"])),
        physical_sha256=receipt["sourcePhysicalSha256"],
        logical_sha256=receipt["sourceLogicalSha256"],
        schema_sha256=receipt["sourceSchemaSha256"],
        receipt_sha256=receipt["sourceReceiptSha256"],
        manifest_sha256=receipt["sourceManifestSha256"],
        seasons=tuple(),
        row_count=receipt["rowCount"],
    )


def test_silver_registry_schema_and_identity_are_verified_before_lookup(
    publication: dict[str, object], monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_path = _silver_registry(publication)
    registry = _read_json(registry_path)
    original_bytes = registry_path.read_bytes()

    # Each relationship is an independent acceptance obligation. Keeping the
    # mutations separate prevents a schema-only repair from masking an
    # unauthenticated registry identity (or vice versa).
    class EntryTrustedBeforeRegistryAuthentication(Exception):
        pass

    def source_trust_sentinel(*_args: object, **_kwargs: object):
        raise EntryTrustedBeforeRegistryAuthentication

    def mutate_identity(value: dict) -> None:
        key, entry = next(iter(value["datasets"].items()))
        entry["datasetVersionId"] = f"{key}:forged-identity"

    monkeypatch.setattr(SP, "resolve_verified_source", source_trust_sentinel)
    problems: list[str] = []
    for label, mutate in (
        ("schema", lambda value: value.__setitem__("schemaVersion", "FORGED_SILVER_REGISTRY_SCHEMA")),
        ("identity", mutate_identity),
    ):
        registry_path.write_bytes(original_bytes)
        mutated = _read_json(registry_path)
        mutate(mutated)
        _write_json(registry_path, mutated)
        try:
            SP.verify_silver(
                Path(publication["silver_root"]), str(publication["manifest_sha"])
            )
        except EntryTrustedBeforeRegistryAuthentication:
            problems.append(f"{label} mutation trusted an entry/source before registry authentication")
        except _EXPECTED_REJECTIONS:
            pass
        else:
            problems.append(f"{label} mutation was accepted")
    assert problems == [], (
        f"{_node_signature('test_silver_registry_schema_and_identity_are_verified_before_lookup')} "
        + "; ".join(problems)
    )


def test_registry_source_root_redirect_to_byte_identical_clone_is_rejected(
    publication: dict[str, object], tmp_path: Path
) -> None:
    canonical_source = Path(publication["source_root"])
    redirected_source = tmp_path / "byte-identical-source-clone"
    shutil.copytree(canonical_source, redirected_source)

    registry_path = _silver_registry(publication)
    registry = _read_json(registry_path)
    entry = next(iter(registry["datasets"].values()))
    entry["sourceRoot"] = str(redirected_source.resolve())
    _write_json(registry_path, registry)

    _assert_verification_rejected(
        lambda: SP.verify_silver(
            Path(publication["silver_root"]), str(publication["manifest_sha"])
        ),
        "a registry sourceRoot redirected to a byte-identical clone",
        _node_signature("test_registry_source_root_redirect_to_byte_identical_clone_is_rejected"),
    )


def test_registry_entry_key_and_manifest_identity_must_agree(
    publication: dict[str, object],
) -> None:
    registry_path = _silver_registry(publication)
    registry = _read_json(registry_path)
    key, entry = next(iter(registry["datasets"].items()))
    del registry["datasets"][key]
    registry["datasets"][f"{key}:wrong-entry-key"] = entry
    _write_json(registry_path, registry)

    _assert_verification_rejected(
        lambda: SP.verify_silver(
            Path(publication["silver_root"]), str(publication["manifest_sha"])
        ),
        "a manifest-addressed entry stored under a divergent registry key",
        _node_signature("test_registry_entry_key_and_manifest_identity_must_agree"),
    )


def test_public_verify_rejects_candidate_derived_duck_typed_expected_source(
    publication: dict[str, object], tmp_path: Path
) -> None:
    unregistered_root = _unregistered_object_clone(
        publication, tmp_path, "duck-typed-unregistered"
    )
    candidate_authority = _candidate_derived_expected_source(publication)
    assert not isinstance(candidate_authority, SP.VerifiedSourceHandle)

    _assert_verification_rejected(
        lambda: SP.verify_silver(
            unregistered_root,
            str(publication["manifest_sha"]),
            _expected_source=candidate_authority,
        ),
        "an unregistered object using candidate-derived duck-typed authority",
        _node_signature("test_public_verify_rejects_candidate_derived_duck_typed_expected_source"),
    )


def test_public_verify_rejects_unregistered_object_even_with_genuine_source_handle(
    publication: dict[str, object], tmp_path: Path
) -> None:
    handle, _ = SP.resolve_verified_source(
        Path(publication["source_root"]), F.SRC_ID
    )
    assert isinstance(handle, SP.VerifiedSourceHandle)
    unregistered_root = _unregistered_object_clone(
        publication, tmp_path, "genuine-handle-unregistered"
    )

    _assert_verification_rejected(
        lambda: SP.verify_silver(
            unregistered_root,
            str(publication["manifest_sha"]),
            _expected_source=handle,
        ),
        "an unregistered object using a genuine but unscoped Stage-B handle",
        _node_signature("test_public_verify_rejects_unregistered_object_even_with_genuine_source_handle"),
    )


def test_prepublication_handle_is_typed_scoped_and_single_operation_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_canonical_issuer(tmp_path, monkeypatch)
    source_root = tmp_path / "scoped-source"
    F.publish_source(source_root)

    # This spy delegates to the real issuer resolver.  It proves the scenario
    # reaches source_issuer.py; it does not supply or replace issuer authority.
    original_issuer_resolve = SP.SI.resolve_source_issuer_authority
    issuer_results: list[object] = []

    def observe_issuer(*args: object, **kwargs: object):
        result = original_issuer_resolve(*args, **kwargs)
        issuer_results.append(result)
        return result

    monkeypatch.setattr(SP.SI, "resolve_source_issuer_authority", observe_issuer)

    original_resolve = SP.resolve_verified_source
    original_verify = SP.verify_silver
    issued: list[tuple[object, list[dict]]] = []

    def rejected(operation: Callable[[], object]) -> bool:
        try:
            operation()
        except _EXPECTED_REJECTIONS:
            return True
        return False

    def capture_resolve(*args: object, **kwargs: object):
        handle, rows = original_resolve(*args, **kwargs)
        issued.append((handle, rows))
        return handle, rows

    def publish(label: str, generation: str) -> dict[str, object]:
        silver_root = tmp_path / label
        entry = SP.publish_silver(
            silver_root=silver_root,
            source_root=source_root,
            source_dataset_version_id=F.SRC_ID,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
            generation=generation,
        )
        return {
            "silver_root": silver_root,
            "manifest_sha": entry["manifestSha256"],
            "object_dir": silver_root
            / "objects"
            / "sha256"
            / entry["manifestSha256"],
        }

    # Positive control: the legitimate publisher resolves Stage B and exercises
    # its real pre-registration Stage-C path.
    monkeypatch.setattr(SP, "resolve_verified_source", capture_resolve)
    first = publish("first-publication", "GEN3")
    monkeypatch.setattr(SP, "resolve_verified_source", original_resolve)
    assert len(issued) == 1 and issuer_results
    handle, rows = issued[0]
    assert isinstance(handle, SP.VerifiedSourceHandle)

    # Public verification must reject an UNUSED genuine Stage-B handle.  This
    # check is independent of whether another handle was consumed internally.
    fresh_public_handle, _ = original_resolve(source_root, F.SRC_ID)
    public_rejected = rejected(
        lambda: original_verify(
            Path(first["silver_root"]),
            str(first["manifest_sha"]),
            _expected_source=fresh_public_handle,
        )
    )

    # Candidate fields cannot construct the genuine production handle type.
    candidate = SimpleNamespace(
        dataset_version_id=handle.dataset_version_id,
        object_path=handle.object_path,
        physical_sha256=handle.physical_sha256,
        logical_sha256=handle.logical_sha256,
        schema_sha256=handle.schema_sha256,
        receipt_sha256=handle.receipt_sha256,
        manifest_sha256=handle.manifest_sha256,
        seasons=handle.seasons,
        row_count=handle.row_count,
    )
    with pytest.raises((SP.SourceAuthorityError, TypeError)):
        SP.VerifiedSourceHandle(
            dataset_version_id=candidate.dataset_version_id,
            object_path=candidate.object_path,
            physical_sha256=candidate.physical_sha256,
            logical_sha256=candidate.logical_sha256,
            schema_sha256=candidate.schema_sha256,
            receipt_sha256=candidate.receipt_sha256,
            manifest_sha256=candidate.manifest_sha256,
            seasons=candidate.seasons,
            row_count=candidate.row_count,
        )

    # Submit the duck type to the legitimate publisher boundary.  A repaired
    # Stage C must reject it before registration, regardless of the private seam
    # name used by the implementation.
    duck_root = tmp_path / "duck-prepublication"
    monkeypatch.setattr(SP, "resolve_verified_source", lambda *_a, **_k: (candidate, rows))
    duck_rejected = rejected(
        lambda: SP.publish_silver(
            silver_root=duck_root,
            source_root=source_root,
            source_dataset_version_id=F.SRC_ID,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
            generation="GEN3-DUCK-WITNESS",
        )
    )

    # Reuse the exact already-consumed handle in a second operation against the
    # same publication identity, then against a distinct identity. Both must
    # fail: scope alone is insufficient without single-operation consumption.
    monkeypatch.setattr(SP, "resolve_verified_source", lambda *_a, **_k: (handle, rows))
    same_reuse_rejected = rejected(
        lambda: SP.publish_silver(
            silver_root=Path(first["silver_root"]),
            source_root=source_root,
            source_dataset_version_id=F.SRC_ID,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
            generation="GEN3",
        )
    )

    # Reuse for a distinct publication identity exercises publication binding.
    reuse_root = tmp_path / "reused-prepublication"
    monkeypatch.setattr(SP, "resolve_verified_source", lambda *_a, **_k: (handle, rows))
    reuse_rejected = rejected(
        lambda: SP.publish_silver(
            silver_root=reuse_root,
            source_root=source_root,
            source_dataset_version_id=F.SRC_ID,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
            generation="GEN3-REUSE-WITNESS",
        )
    )
    monkeypatch.setattr(SP, "resolve_verified_source", original_resolve)

    problems: list[str] = []
    if not public_rejected:
        problems.append("the public verifier accepted an unused genuine Stage-B handle")
    if not duck_rejected:
        problems.append("Stage C accepted candidate-constructible duck-typed authority")
    if not same_reuse_rejected:
        problems.append("one Stage-B handle authorized a second operation")
    if not reuse_rejected:
        problems.append("one Stage-B handle authorized a second publication identity")
    if (duck_root / "silver-registry.json").exists() and duck_rejected:
        problems.append("the rejected duck-typed attempt still registered Silver authority")
    if (reuse_root / "silver-registry.json").exists() and reuse_rejected:
        problems.append("the rejected reused-handle attempt still registered Silver authority")
    assert problems == [], (
        f"{_node_signature('test_prepublication_handle_is_typed_scoped_and_single_operation_only')} "
        f"{'; '.join(problems)}"
    )
