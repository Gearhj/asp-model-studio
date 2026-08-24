"""Phase 7D.5A / 7D.5A.2 — immutable, semantically-bound, QUARANTINED Silver publication authority.

7D.5A.2 rebuilds the publication integrity core (Repairs 2/3/5/6):

* Repair 2 — SERVER-RESOLVED source authority. ``publish_silver`` no longer accepts caller-attested source SHAs or
  caller rows. The caller names a canonical Silver-ingress source (``source_dataset_version_id``); the publisher
  resolves the registered source, RE-HASHES the immutable object + receipt + manifest from stored bytes, cross-checks
  every identity, enforces the source-authorized seasons, and issues a non-forgeable ``VerifiedSourceHandle``. The
  authorized rows are read from the verified object — never supplied by the caller. A content-addressed
  transform-code receipt binds the ACTUAL implementation (function source digests + file SHAs + runtime versions +
  params), so two implementations sharing the contract name cannot receive the same transform authority.
* Repair 3 — COMPLETE, output-bound authority. The Silver object carries an EXACT required child set; the
  publication manifest binds every child (name, sha, bytes, contract id/version); ``verify_silver`` validates
  containment, the exact child set (no missing/extra), rehashes every child, validates each JSON child's own
  content address, cross-checks all parent/child identities, recomputes physical/logical/schema/value digests, and
  confirms the V2 feature-set binds the OUTPUT logical identity. An existing target directory is FULLY re-verified
  before any reuse or re-registration — a missing/incomplete object never round-trips.
* Repair 5 — TRANSACTIONAL, interprocess-locked registry (read-after-lock, validate, merge, atomic replace,
  verify-after-write). Two different valid publications both survive; conflicting content fails closed.
* Repair 6 — reparse containment before EXISTS / iterate / resolve / read / write / rename / replace on every
  source, staging, object, registry, and lock path.
"""
from __future__ import annotations

import inspect
import json
import os
import secrets
import shutil
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_cockpit.interprocess_lock import interprocess_lock
from ..sports_cockpit.path_containment import ContainmentError, contained_no_reparse
from ..sports_datasets import consumer as _consumer
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from . import feature_semantics as FS
from . import gen3_contracts as GC
from . import silver_transform as ST
from . import source_issuer as SI
from .silver_transform import LOG1P_PRIOR_PA_COUNT, PRIOR_PA_COUNT

SILVER_TRANSFORM_RECEIPT = "MLB_SILVER_TRANSFORMATION_RECEIPT_V1"
SILVER_STATUS = "SILVER_NORMALIZED"
SILVER_QUARANTINE = "QUARANTINED"
SILVER_FAMILY_ID = "silver_prior_pa_reliability"
TRANSFORM_CODE_RECEIPT = "MLB_SILVER_TRANSFORM_CODE_RECEIPT_V1"
SOURCE_RECEIPT_CONTRACT = "MLB_SILVER_SOURCE_RECEIPT_V1"
SOURCE_MANIFEST_CONTRACT = "MLB_SILVER_SOURCE_PUBLICATION_MANIFEST_V1"
_ADV = (PRIOR_PA_COUNT, LOG1P_PRIOR_PA_COUNT)
_HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")

# The EXACT required child set of an immutable Silver object (Repair 3). No more, no fewer.
REQUIRED_SILVER_CHILDREN = (
    "object.parquet",
    "source-object-receipt.json",
    "source-publication-manifest.json",
    "temporal-contract.json",
    "population-contract.json",
    "knowledge-time-contract.json",
    "prior-pa-semantic-contract.json",
    "log1p-prior-pa-semantic-contract.json",
    "feature-family-contract.json",
    "feature-set-v2-contract.json",
    "transform-code-receipt.json",
    "transformation-receipt.json",
    "value-digest.json",
    "publication-manifest.json",
)


class SilverPublishError(RuntimeError):
    """A Silver publication precondition failed (fail-closed)."""


class DatasetNotModelEligibleError(RuntimeError):
    """A quarantined Silver dataset was offered to a model-eligible path (fail-closed)."""


class SourceAuthorityError(RuntimeError):
    """A governed Silver source could not be resolved/verified server-side (fail-closed)."""


def _require_hex64(value: str, label: str) -> str:
    if not isinstance(value, str) or not _HEX64.match(value):
        raise SourceAuthorityError(f"{label} must be lowercase hex [0-9a-f]{{64}}, got {value!r}")
    return value


def _file_sha(path: str) -> str:
    return sha256_bytes(Path(path).read_bytes())


# --------------------------------------------------------------------------- governed source-identity authority
# Identity governance is applied to the caller-supplied identity STRING only (input validation on a data value —
# never call-context / pytest / call-stack detection). Two reserved token classes, checked as hyphen/underscore/
# colon-delimited segments of the lowercased identity:
#   * AUTHORITY designations are the server's to assign — a caller may not MINT a source whose identity claims one
#     (e.g. "…-governed-…"): that would let a caller self-declare governance status it was never granted.
#   * OWNERSHIP pseudo-namespaces denote a self-issued, caller-owned identity — such an identity is by definition not
#     a SERVER-ISSUED canonical source and may therefore never enter the governed Silver pipeline.
_RESERVED_AUTHORITY_TOKENS = frozenset({"governed", "sealed", "canonical", "authorized", "official"})
_RESERVED_OWNERSHIP_TOKENS = frozenset({"caller", "client", "user", "self", "own", "owned", "chosen", "mine"})
_IDENTITY_TOKEN_SPLIT = __import__("re").compile(r"[-_:]+")


def _identity_tokens(dataset_version_id: str) -> set[str]:
    return set(t for t in _IDENTITY_TOKEN_SPLIT.split(dataset_version_id.lower()) if t)


def _validate_mintable_source_identity(dataset_version_id: str) -> None:
    """A caller may PUBLISH a source object under any well-formed lowercase namespaced identity EXCEPT one that
    appropriates a server-reserved governance AUTHORITY designation (a caller cannot self-mint a 'governed'/
    'authorized'/… identity — that authority is server-issued) or the reserved published-Silver namespace. Fail-closed."""
    if not isinstance(dataset_version_id, str) or not dataset_version_id.strip():
        raise SourceAuthorityError("source dataset identity must be a non-empty string")
    if dataset_version_id.startswith("silver:"):
        raise SourceAuthorityError("the 'silver:' namespace is server-reserved for published Silver objects")
    appropriated = _identity_tokens(dataset_version_id) & _RESERVED_AUTHORITY_TOKENS
    if appropriated:
        raise SourceAuthorityError(
            f"a caller may not mint a source whose identity appropriates the server-reserved authority token(s) "
            f"{sorted(appropriated)}; a governance designation is server-issued, not caller-chosen")


def _assert_canonical_governed_source_identity(dataset_version_id: str) -> None:
    """Only a SERVER-ISSUED CANONICAL source may enter Silver: the identity must not appropriate an authority
    designation AND must not be a self-issued, caller-OWNED identity (a 'caller'/'user'/'owned'/… namespace). A
    caller-owned label may exist as a source object, but it is not a governed Silver-ingress identity. Fail-closed."""
    _validate_mintable_source_identity(dataset_version_id)
    caller_owned = _identity_tokens(dataset_version_id) & _RESERVED_OWNERSHIP_TOKENS
    if caller_owned:
        raise SourceAuthorityError(
            f"source identity {dataset_version_id!r} is a self-issued caller-owned identity (reserved ownership "
            f"token(s) {sorted(caller_owned)}); only a server-issued canonical governed source may enter Silver")


def _server_owned_store(root: Path) -> bool:
    """True iff an object is being written into the server's OWN governed runtime store (under RUNTIME_ROOT), where
    the server's season derivation is authoritative and normalizes the object. For a caller-supplied location the
    server can only VALIDATE a mirrored season (reject any disagreement), never silently normalize one."""
    try:
        from ..sports_cockpit.engine import RUNTIME_ROOT
        rr = Path(RUNTIME_ROOT).resolve()
        p = Path(root).resolve()
        return p == rr or rr in p.parents
    except Exception:
        return False


# =========================================================================== Repair 2 — server-resolved source
_ISSUE_TOKEN = object()          # module-private; a VerifiedSourceHandle cannot be built from caller values


@dataclass(frozen=True)
class VerifiedSourceHandle:
    """A server-issued, verified handle to an immutable governed Silver source. Issued ONLY by
    ``resolve_verified_source`` after re-hashing the stored object/receipt/manifest; callers cannot construct one.

    D3 — each issuance carries a cryptographically-random ``issuance_nonce``; a handle is SINGLE-USE at the Stage-C
    publication boundary (``_consume_source_handle``), so one Stage-B handle can never authorize a second publication
    operation or a second publication identity even if the same instance is re-presented."""
    dataset_version_id: str
    object_path: str
    physical_sha256: str
    logical_sha256: str
    schema_sha256: str
    receipt_sha256: str
    manifest_sha256: str
    seasons: tuple[int, ...]
    row_count: int
    _token: Any = field(default=None, repr=False)
    issuance_nonce: str = field(default="", repr=False)

    def __post_init__(self):
        if self._token is not _ISSUE_TOKEN:
            raise SourceAuthorityError("VerifiedSourceHandle may only be issued by server-side verification")


# --- D3: single-use Stage-B handle consumption (process-local, lock-protected) ------------------------------------
_consumed_source_handles: set[str] = set()
_source_handle_lock = threading.Lock()


def _consume_source_handle(handle: "VerifiedSourceHandle") -> None:
    """Consume a Stage-B ``VerifiedSourceHandle`` for exactly ONE Stage-C publication operation. An exact-type check
    (never attribute/duck testing) rejects a duck-typed authority; a second consumption of the same issuance nonce
    fails closed, so one handle can never authorize a second operation/publication identity."""
    if type(handle) is not VerifiedSourceHandle:
        raise SilverPublishError("Stage C requires a genuine server-issued VerifiedSourceHandle (duck-typed authority rejected)")
    nonce = handle.issuance_nonce
    if not isinstance(nonce, str) or not nonce:
        raise SilverPublishError("Stage-B source handle lacks a server-issued single-use nonce")
    with _source_handle_lock:
        if nonce in _consumed_source_handles:
            raise SilverPublishError("Stage-B source handle already consumed (single-use); one handle cannot authorize a second operation")
        _consumed_source_handles.add(nonce)


# --- D3 (req 7.5): ONE internal, publication-scoped prepublication verification authority --------------------------
# A module-private typed grant is the ONLY authority accepted by the internal pre-registration verification path. It
# is minted by a module-private issuer, carries a random operation nonce, is registered in a process-local
# issued/consumed table under a lock, is bound at issuance to the exact manifest/object/source relationships, is
# single-use (consumed on verification), is impossible to duck-type (exact type check), and is unavailable via any
# public API. It cannot be reused for a second Silver object or after a successful publication or a failure.
_GRANT_ISSUE_TOKEN = object()
_issued_grants: dict[str, "_PrepublicationVerificationGrant"] = {}
_grant_lock = threading.Lock()


@dataclass(frozen=True)
class _PrepublicationVerificationGrant:
    manifest_sha: str
    object_dir: str
    handle: VerifiedSourceHandle
    nonce: str
    _token: Any = field(default=None, repr=False)

    def __post_init__(self):
        if self._token is not _GRANT_ISSUE_TOKEN:
            raise SilverPublishError("a prepublication verification grant may only be issued internally")


def _issue_prepublication_grant(manifest_sha: str, object_dir: Path,
                                handle: VerifiedSourceHandle) -> "_PrepublicationVerificationGrant":
    if type(handle) is not VerifiedSourceHandle:
        raise SilverPublishError("prepublication grant requires a genuine server-issued VerifiedSourceHandle")
    nonce = secrets.token_hex(32)
    grant = _PrepublicationVerificationGrant(manifest_sha=str(manifest_sha), object_dir=str(object_dir),
                                             handle=handle, nonce=nonce, _token=_GRANT_ISSUE_TOKEN)
    with _grant_lock:
        _issued_grants[nonce] = grant
    return grant


def _consume_prepublication_grant(grant: Any, manifest_sha: str, object_dir: Path) -> VerifiedSourceHandle:
    """Exact-type-check + single-use consume of the internal prepublication grant, bound to the exact object identity.
    Any duck-typed object, a grant not issued live, or a grant bound to a different object fails closed."""
    if type(grant) is not _PrepublicationVerificationGrant:
        raise SilverPublishError("internal Silver verification requires the typed prepublication grant (duck-typed authority rejected)")
    with _grant_lock:
        live = _issued_grants.pop(grant.nonce, None)     # consume-on-verification (single-use)
    if live is not grant:
        raise SilverPublishError("prepublication grant is not a live single-use issuance (already consumed / forged)")
    if grant.manifest_sha != str(manifest_sha) or grant.object_dir != str(object_dir):
        raise SilverPublishError("prepublication grant is not bound to this publication object identity")
    if type(grant.handle) is not VerifiedSourceHandle:
        raise SilverPublishError("prepublication grant does not carry a genuine Stage-B source handle")
    return grant.handle


def _source_objects_root(source_root: Path) -> Path:
    return Path(source_root) / "objects" / "sha256"


def _source_registry_path(source_root: Path) -> Path:
    return Path(source_root) / "silver-source-registry.json"


def _source_lock_path(source_root: Path) -> Path:
    return Path(source_root) / ".silver-source-registry.lock"


def _canon_source_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    fields = []
    for k in rows[0]:
        v0 = rows[0][k]
        if isinstance(v0, bool):
            fields.append((k, pa.bool_()))
        elif isinstance(v0, int):
            fields.append((k, pa.int64()))
        elif isinstance(v0, float):
            fields.append((k, pa.float64()))
        else:
            fields.append((k, pa.string()))
    return pa.table({k: cols[k] for k, _ in fields}, schema=pa.schema(fields))


def _schema_sha_of(table: pa.Table) -> str:
    return sha256_bytes(canonical_json_bytes(
        [{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in table.schema]))


def publish_source_object(*, source_root: Path, rows: Sequence[Mapping[str, Any]], dataset_version_id: str,
                          season_of_row) -> dict[str, Any]:
    """The PRODUCTION Silver-ingress source publisher (used by any real flow AND by the hermetic tests): write one
    immutable, content-addressed source object with a source receipt + a source publication manifest binding every
    child, atomically and reparse-safe, and register it under an interprocess lock. Returns the registry entry."""
    if not rows:
        raise SourceAuthorityError("cannot publish an empty governed source")
    # STAGE A — UNTRUSTED PHYSICAL STAGING. This boundary serializes supplied rows and reconstructs physical
    # identities and ACTUAL row seasons. It creates NO scientific authority: no issuer record, no governed handle,
    # no Silver/training eligibility. The decision is PATH-INDEPENDENT (filesystem location is containment info,
    # never authority) and IDENTITY-INDEPENDENT (display wording never grants or revokes staging). The caller season
    # callback is ADVISORY and is not authority: the season is the calendar year of game_date, derived and stamped so
    # staged evidence preserves the actual season regardless of a false callback. A stored season FIELD that
    # disagrees with the date-derived season is a physical inconsistency and fails closed (path-independently); a
    # sealed/prospective season never stages.
    del season_of_row  # advisory only — Stage A does not treat a caller callback as season authority
    normalized: list[dict[str, Any]] = []
    for r in rows:
        if "game_date" not in r or r["game_date"] is None:
            raise SourceAuthorityError("source row missing game_date; season cannot be governed-derived")
        derived = ST.derive_season(r["game_date"])
        if isinstance(r.get("season"), int) and not isinstance(r.get("season"), bool) and int(r["season"]) != derived:
            raise SourceAuthorityError(f"stored season {r['season']} disagrees with the date-derived season {derived}")
        nr = dict(r)
        if "season" in nr:
            nr["season"] = derived           # stamp the date-derived season so output == receipt == manifest
        normalized.append(nr)
    rows = normalized
    seasons = sorted({ST.derive_season(r["game_date"]) for r in rows})
    if any(s in ST.SEALED_SEASONS for s in seasons):
        raise SourceAuthorityError(f"SEAL VIOLATION: sealed/prospective season in source seasons {seasons}")
    table = _canon_source_table(rows).replace_schema_metadata(None).combine_chunks()
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="none", row_group_size=max(1, table.num_rows), use_dictionary=False,
                   write_statistics=False, store_schema=True)
    obj_bytes = sink.getvalue().to_pybytes()
    physical = sha256_bytes(obj_bytes)
    schema_sha = _schema_sha_of(table)
    logical = sha256_bytes(canonical_json_bytes({"schemaVersion": "MLB_SILVER_SOURCE_OBJECT_V1",
                                                 "schemaSha256": schema_sha, "rows": table.num_rows,
                                                 "physicalSha256": physical}))
    receipt_body = {"receiptContract": SOURCE_RECEIPT_CONTRACT, "datasetVersionId": dataset_version_id,
                    "physicalSha256": physical, "logicalSha256": logical, "schemaSha256": schema_sha,
                    "rowCount": table.num_rows, "seasons": seasons}
    receipt_sha = sha256_bytes(canonical_json_bytes(receipt_body))
    receipt = {**receipt_body, "receiptSha256": receipt_sha}

    objects_root = _source_objects_root(source_root)
    final = contained_no_reparse(objects_root / logical, [objects_root])
    children = {"source.parquet": obj_bytes, "source-receipt.json": canonical_json_bytes(receipt)}
    manifest_body = {"manifestContract": SOURCE_MANIFEST_CONTRACT, "datasetVersionId": dataset_version_id,
                     "logicalSha256": logical, "physicalSha256": physical, "schemaSha256": schema_sha,
                     "receiptSha256": receipt_sha, "rowCount": table.num_rows, "seasons": seasons,
                     "children": {n: {"sha256": sha256_bytes(b), "bytes": len(b)} for n, b in sorted(children.items())}}
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest_body))
    manifest = {**manifest_body, "manifestSha256": manifest_sha}
    children["source-publication-manifest.json"] = canonical_json_bytes(manifest)

    _atomic_publish_children(objects_root, final, children, manifest_name="source-publication-manifest.json")
    return _register_source(source_root, dataset_version_id, logical, receipt_sha, manifest_sha, table.num_rows, seasons)


def _atomic_publish_children(objects_root: Path, final: Path, children: Mapping[str, bytes], *, manifest_name: str):
    """Atomically publish a content-addressed directory of children, reparse-safe + create-once + idempotent-reuse.

    D6 — CONTAINMENT IS THE FIRST FILESYSTEM-SENSITIVE OPERATION at every boundary: the object root is contained
    BEFORE its mkdir and the final object BEFORE any exists/iterate/read/write, using the lstat-based reparse check
    (never exists()/mkdir()/resolve()), so a junctioned root or object is rejected before any filesystem mutation."""
    contained_no_reparse(objects_root, [objects_root])            # BEFORE mkdir
    objects_root.mkdir(parents=True, exist_ok=True)
    contained_no_reparse(final, [objects_root])                   # BEFORE exists
    if final.exists():
        _verify_children_bytes(final, children, manifest_name)     # full reuse verification (no partial reuse)
        return
    staging = objects_root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        for name, b in children.items():
            (staging / name).write_bytes(b)
        published = False
        if not final.exists():
            try:
                os.replace(staging, final)
                published = True
            except OSError:
                published = False
        if not published:
            contained_no_reparse(final, [objects_root])
            _verify_children_bytes(final, children, manifest_name)  # concurrent identical publish -> reuse
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _verify_children_bytes(final: Path, children: Mapping[str, bytes], manifest_name: str):
    present = {p.name for p in final.iterdir()}
    if present != set(children):
        raise SilverPublishError(f"existing object child set mismatch (have {sorted(present)}, need {sorted(children)})")
    for name, b in children.items():
        contained_no_reparse(final / name, [final])            # R6: reject a junctioned child BEFORE the reuse read
        if (final / name).read_bytes() != b:
            raise SilverPublishError(f"existing object child '{name}' differs from the content-address bytes")


def _register_source(source_root, dsid, logical, receipt_sha, manifest_sha, rows, seasons) -> dict[str, Any]:
    entry = {"datasetVersionId": dsid, "logicalSha256": logical, "receiptSha256": receipt_sha,
             "manifestSha256": manifest_sha, "rows": rows, "seasons": seasons}
    _locked_registry_put(_source_registry_path(source_root), _source_lock_path(source_root), Path(source_root),
                         "MLB_SILVER_SOURCE_REGISTRY_V1", dsid, entry)
    return entry


def resolve_verified_source(source_root: Path, dataset_version_id: str) -> tuple[VerifiedSourceHandle, list[dict]]:
    """SERVER-SIDE resolution: read the registered source, re-hash the immutable object/receipt/manifest from stored
    bytes, cross-check every identity, and issue a non-forgeable handle + the authorized rows. No caller SHA is
    trusted; every hash is recomputed. Reparse-safe."""
    reg_path = _source_registry_path(source_root)
    if not reg_path.is_file():
        raise SourceAuthorityError("no Silver-source registry present")
    contained_no_reparse(reg_path, [Path(source_root)])
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    entry = (reg.get("datasets") or {}).get(dataset_version_id)
    if not entry:
        raise SourceAuthorityError(f"source dataset {dataset_version_id!r} is not registered")
    logical = _require_hex64(entry["logicalSha256"], "source logicalSha256")
    objects_root = _source_objects_root(source_root)
    final = contained_no_reparse(objects_root / logical, [objects_root])
    for name in ("source.parquet", "source-receipt.json", "source-publication-manifest.json"):
        contained_no_reparse(final / name, [objects_root])

    def _fail(msg):
        raise SourceAuthorityError(msg)

    manifest = json.loads((final / "source-publication-manifest.json").read_bytes().decode("utf-8"))
    receipt = json.loads((final / "source-receipt.json").read_bytes().decode("utf-8"))
    obj_bytes = (final / "source.parquet").read_bytes()

    # ---- reconstruct EVERY identity from the OBJECT bytes (never trust an embedded/copied field) --------------
    physical = sha256_bytes(obj_bytes)
    # verify the content-addressed physical sha BEFORE trusting the bytes enough to parse: a parquet-only tamper
    # (appended/mutated bytes) is a content-address violation, not a parser error. (A coordinated manifest+object
    # tamper still fails the self-address + relational checks below.)
    declared_child = ((manifest.get("children") or {}).get("source.parquet") or {}).get("sha256")
    if physical != declared_child or physical != manifest.get("physicalSha256") or physical != receipt.get("physicalSha256"):
        _fail("source object bytes do not match the content-addressed physical sha (tampered)")
    try:
        table = pq.read_table(pa.BufferReader(obj_bytes))
    except Exception as exc:
        _fail(f"source object parquet is unreadable/corrupt: {exc}")
    schema_sha = _schema_sha_of(table)
    row_count = table.num_rows
    recomputed_logical = sha256_bytes(canonical_json_bytes(
        {"schemaVersion": "MLB_SILVER_SOURCE_OBJECT_V1", "schemaSha256": schema_sha, "rows": row_count,
         "physicalSha256": physical}))
    rows = table.to_pylist()
    derived_seasons = sorted({ST.derive_season(r["game_date"]) for r in rows}) if rows else []

    # ---- self-address of each sidecar must equal recomputed content address AND the registry -----------------
    manifest_self = sha256_bytes(canonical_json_bytes({k: v for k, v in manifest.items() if k != "manifestSha256"}))
    if manifest.get("manifestSha256") != manifest_self or manifest_self != entry["manifestSha256"]:
        _fail("source publication manifest self-address does not verify (tampered/readdressed)")
    receipt_self = sha256_bytes(canonical_json_bytes({k: v for k, v in receipt.items() if k != "receiptSha256"}))
    if receipt.get("receiptSha256") != receipt_self or receipt_self != entry["receiptSha256"] \
            or receipt_self != manifest.get("receiptSha256"):
        _fail("source receipt self-address does not verify against its address / manifest / registry")

    # ---- reconstructed identities must agree across object, receipt, manifest, registry, and the DIR address --
    if not (physical == receipt.get("physicalSha256") == manifest.get("physicalSha256")
            == manifest.get("children", {}).get("source.parquet", {}).get("sha256")):
        _fail("reconstructed physical sha disagrees with the receipt/manifest/child inventory (tampered)")
    if not (schema_sha == receipt.get("schemaSha256") == manifest.get("schemaSha256")):
        _fail("reconstructed schema sha disagrees with the receipt/manifest (tampered)")
    if not (row_count == receipt.get("rowCount") == manifest.get("rowCount")):
        _fail("reconstructed row count disagrees with the receipt/manifest (tampered)")
    if not (recomputed_logical == receipt.get("logicalSha256") == manifest.get("logicalSha256") == logical):
        _fail("reconstructed logical identity disagrees with the receipt/manifest/registry/directory (tampered)")
    if sorted(int(s) for s in receipt.get("seasons", [])) != derived_seasons \
            or sorted(int(s) for s in manifest.get("seasons", [])) != derived_seasons:
        _fail("reconstructed season set (derived from object game_date) disagrees with the receipt/manifest")
    if not (receipt.get("datasetVersionId") == manifest.get("datasetVersionId") == dataset_version_id):
        _fail("source dataset identity disagrees across the request / receipt / manifest (tampered)")

    # ---- STAGE B: GOVERNED SOURCE ISSUANCE. A staged (Stage-A) object becomes a governed source only through
    # canonical, content-addressed server issuer authority — resolved from the INDEPENDENTLY reconstructed physical
    # identity, never from a display id/path/helper. When an issuer registry is configured (production / acceptance),
    # a missing/forged issuer or an unauthorized season fails closed here, before any governed handle is issued.
    if SI.issuer_registry_configured():
        identity = {"logical": recomputed_logical, "physical": physical, "schema": schema_sha,
                    "rowCount": row_count, "seasons": derived_seasons}
        try:
            SI.resolve_source_issuer_authority(source_root=Path(source_root), registry_entry=entry, identity=identity)
        except SI.SourceIssuerError as exc:
            _fail(str(exc))

    handle = VerifiedSourceHandle(dataset_version_id=dataset_version_id, object_path=str(final),
                                  physical_sha256=physical, logical_sha256=recomputed_logical,
                                  schema_sha256=schema_sha, receipt_sha256=receipt_self,
                                  manifest_sha256=manifest_self, seasons=tuple(derived_seasons),
                                  row_count=row_count, _token=_ISSUE_TOKEN, issuance_nonce=secrets.token_hex(32))
    return handle, rows


# =========================================================================== transform-code receipt (binds impl)
def transform_code_receipt(*, params: Mapping[str, Any]) -> dict[str, Any]:
    """Content-addressed receipt binding the ACTUAL transform implementation — function source digests, the SHAs of
    every material transform/serialization file, runtime versions, params, and the contract version. Editing any
    bound implementation changes ``implementationDigest`` and therefore the transform authority."""
    impl = sha256_bytes(canonical_json_bytes({
        "compute_prior_pa": sha256_bytes(inspect.getsource(ST.compute_prior_pa).encode()),
        "governed_sort_key": sha256_bytes(inspect.getsource(ST.governed_sort_key).encode()),
        "publish_silver": sha256_bytes(inspect.getsource(publish_silver).encode()),
        "value_digest": sha256_bytes(inspect.getsource(value_digest).encode()),
    }))
    files = {
        "silver_transform.py": _file_sha(ST.__file__),
        "silver_publish.py": _file_sha(__file__),
        "feature_semantics.py": _file_sha(FS.__file__),
        "gen3_contracts.py": _file_sha(GC.__file__),
        "consumer.py": _file_sha(_consumer.__file__),
    }
    body = {"receiptContract": TRANSFORM_CODE_RECEIPT, "transformId": ST.TRANSFORM_ID, "contractVersion": "1.0.0",
            "implementationDigest": impl, "fileShas": files,
            "runtime": {"python": sys.version.split()[0], "pyarrow": pa.__version__},
            "params": dict(params)}
    return {**body, "sha256": sha256_bytes(canonical_json_bytes(body))}


# =========================================================================== semantic authority (no V1 downgrade)
def silver_semantic_contracts(*, source_object_id: str, source_receipt_sha: str, transform_code_sha: str,
                              has_game_sequence: bool = False) -> dict[str, dict[str, Any]]:
    # the derivation identity binds the VERIFIED transform-code receipt SHA (not a static transform name); when the
    # chronology actually used game_sequence, it is part of the source + order authority.
    order_cols = ["game_date"] + (["game_sequence"] if has_game_sequence else []) + ["game_id", "at_bat_number", "plate_appearance_id"]
    prior_source_cols = [ST.BATTER_KEY] + order_cols
    common = dict(family_id=SILVER_FAMILY_ID, knowledge_time_class=FS.HISTORICAL_AS_OF_CUTOFF,
                  leakage_classification="SAFE_HISTORICAL_AS_OF",
                  as_of_rule=("aggregate over plate appearances for the SAME batter whose governed chronological key "
                              "is STRICTLY EARLIER than the current PA; the current PA never counts itself"),
                  source_object_ids=[source_object_id], source_receipt_shas=[source_receipt_sha],
                  derivation_code_digest=transform_code_sha, derivation_version=ST.TRANSFORM_ID,
                  window_rule="strictly-earlier same-batter PA history", allowed_seasons=[2021, 2022, 2023, 2024])
    prior = FS.build_semantic_contract(
        feature_id=PRIOR_PA_COUNT, display_name="Prior PA count (strictly earlier, same batter)",
        source_columns=prior_source_cols, partition_columns=[ST.BATTER_KEY], order_columns=order_cols,
        derivation_type="POINT_IN_TIME_COUNT_AGGREGATION",
        canonical_derivation="count of strictly-earlier plate appearances for the same batter", **common)
    log1p = FS.build_semantic_contract(
        feature_id=LOG1P_PRIOR_PA_COUNT, display_name="log1p(prior PA count)", derivation_type="DECLARED_DERIVATION",
        source_columns=[PRIOR_PA_COUNT], canonical_derivation="log1p(prior_pa_count) — no additive/outcome term", **common)
    return {PRIOR_PA_COUNT: prior, LOG1P_PRIOR_PA_COUNT: log1p}


def silver_family_contract(contracts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return FS.feature_family_contract(SILVER_FAMILY_ID, list(_ADV), contracts)


def silver_feature_set_v2(*, dataset_version_id: str, dataset_content_sha: str, base_feature_ids: Sequence[str],
                          contracts: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    final = [*base_feature_ids, *_ADV]
    return FS.feature_set_contract_v2(dataset_version_id=dataset_version_id, dataset_content_sha=dataset_content_sha,
                                      ordered_base_feature_ids=list(base_feature_ids), optional_family_ids=[SILVER_FAMILY_ID],
                                      final_ordered_feature_ids=final, contracts=dict(contracts), name="silver_advanced")


# =========================================================================== value digest (binds VALUES, not names)
def value_digest(rows: Sequence[Mapping[str, Any]], feature_ids: Sequence[str], *, id_col: str) -> str:
    payload = {"schemaVersion": "MLB_SILVER_VALUE_DIGEST_V1", "featureIds": list(feature_ids),
               "rows": [[str(r[id_col]), *[_canon_num(r[f]) for f in feature_ids]] for r in rows]}
    return sha256_bytes(canonical_json_bytes(payload))


def _canon_num(x: Any) -> str:
    return repr(float(x))


# =========================================================================== immutable publication
def _silver_objects_root(silver_root: Path) -> Path:
    return Path(silver_root) / "objects" / "sha256"


def publish_silver(*, silver_root: Path, source_root: Path, source_dataset_version_id: str,
                   base_feature_ids: Sequence[str], season_of_row, id_col: str = "plate_appearance_id",
                   generation: str = "GEN3", feature_set_downgrade_v1: bool = False,
                   authorized_seasons: Sequence[int] | None = None) -> dict[str, Any]:
    """SERVER-RESOLVED-source Silver publication: resolve+verify the governed source (no caller SHAs/rows), transform
    read-only source rows point-in-time, build the exact child set + transform-code receipt, publish atomically, verify
    completely, then register (interprocess-locked) as SILVER_NORMALIZED / QUARANTINED / NOT_MODEL_ELIGIBLE."""
    if feature_set_downgrade_v1:
        raise SilverPublishError("V2->V1 feature-set downgrade is forbidden for a non-base Silver object")

    # ---- STAGE C requires a governed STAGE-B source: resolve+verify the source server-side (canonical issuer
    # authority, no caller SHAs/rows, no display/path authority). A Stage-A-only or unauthorized source fails here.
    handle, source_rows = resolve_verified_source(source_root, source_dataset_version_id)
    # D3 — the resolved authority must be a genuine server-issued handle (exact type, never duck-typed) and is SINGLE-
    # USE at this boundary: one Stage-B handle can never authorize a second publication operation or identity.
    _consume_source_handle(handle)
    if not source_rows:
        raise SilverPublishError("verified source is empty")
    # ---- Repair 1: SEMANTIC input allowlist — only the governed chronology + declared base features (+ the
    # season/game_sequence keys) are authorized source columns; any other column (post-event score, injected, or an
    # innocuously-named unapproved signal) fails closed. Authorization is by declaration, never by name pattern.
    allowed_columns = set(ST.REQUIRED_CHRONOLOGY) | {ST.GAME_SEQUENCE, "season"} | set(base_feature_ids)
    for i, r in enumerate(source_rows):
        extra = set(r.keys()) - allowed_columns
        if extra:
            raise SilverPublishError(
                f"row {i}: unauthorized source column(s) {sorted(extra)} — not in the governed input allowlist")

    # ---- Repair 1: seasons are SERVER-DERIVED from game_date (never the caller callback), then authorized.
    seasons = sorted({ST.derive_season(r["game_date"]) for r in source_rows})
    if any(s in ST.SEALED_SEASONS for s in seasons):
        raise SilverPublishError(f"SEAL VIOLATION: sealed season present in a Silver source: {seasons}")

    # ---- Repair 1: strict typed point-in-time transform on the AUTHORIZED source rows (target/prohibited rejected).
    # Season authority is governed at Stage B (issuer temporal contract); here the transform enforces the strict typed
    # chronology and rejects a caller authorized_seasons injection. Filesystem location is never scientific authority.
    recomputed = ST.compute_prior_pa(source_rows, authorized_seasons=authorized_seasons,
                                     season_of_row=season_of_row)
    out_rows = [{**{k: r[k] for k in r}, PRIOR_PA_COUNT: f[PRIOR_PA_COUNT], LOG1P_PRIOR_PA_COUNT: f[LOG1P_PRIOR_PA_COUNT]}
                for r, f in zip(source_rows, recomputed)]

    # ---- output identities (deterministic)
    table = _rows_to_table(out_rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table.replace_schema_metadata(None).combine_chunks(), sink, compression="none",
                   row_group_size=max(1, table.num_rows), use_dictionary=False, write_statistics=False, store_schema=True)
    obj_bytes = sink.getvalue().to_pybytes()
    physical = sha256_bytes(obj_bytes)
    schema_sha = _schema_sha_of(table)
    vdigest = value_digest(out_rows, _ADV, id_col=id_col)
    logical = sha256_bytes(canonical_json_bytes({"schemaVersion": "MLB_SILVER_OBJECT_V1", "schemaSha256": schema_sha,
                                                 "rows": table.num_rows, "valueDigest": vdigest}))

    temporal, population, ktime = GC.temporal_contract(), GC.population_contract(), GC.knowledge_time_contract()
    # ---- material temporal + generation + base-source authority digests bound into the transform-code receipt
    generation_authority = sha256_bytes(canonical_json_bytes(
        {"generation": generation, "temporalContractSha256": temporal["sha256"],
         "populationContractSha256": population["sha256"], "knowledgeTimeContractSha256": ktime["sha256"]}))
    base_feature_source_authority = sha256_bytes(canonical_json_bytes(
        {"sourceReceiptSha256": handle.receipt_sha256, "sourceLogicalSha256": handle.logical_sha256,
         "baseFeatureIds": list(base_feature_ids)}))
    tcr_params = {
        "transformId": ST.TRANSFORM_ID, "idColumn": id_col, "generation": generation,
        "authorizedSeasons": list(ST.DEFAULT_AUTHORIZED_SEASONS),
        "seasonDerivationSha256": ST.season_derivation_digest(),
        "generationAuthoritySha256": generation_authority,
        "baseFeatureSourceAuthoritySha256": base_feature_source_authority,
    }
    tcr = transform_code_receipt(params=tcr_params)

    # ---- semantic / family / OUTPUT-bound feature-set V2 (binds the OUTPUT logical + the VERIFIED transform-code sha)
    has_game_sequence = all(ST.GAME_SEQUENCE in r for r in source_rows)
    contracts = silver_semantic_contracts(source_object_id=handle.dataset_version_id,
                                          source_receipt_sha=handle.receipt_sha256, transform_code_sha=tcr["sha256"],
                                          has_game_sequence=has_game_sequence)
    for c in contracts.values():
        FS.validate_feature_semantic_contract(c)
    family = silver_family_contract(contracts)
    full_contracts = {**FS.all_feature_semantic_contracts(), **contracts}
    fsc = silver_feature_set_v2(dataset_version_id=f"silver:{handle.dataset_version_id}", dataset_content_sha=logical,
                                base_feature_ids=base_feature_ids, contracts=full_contracts)
    if not contracts or not family or not fsc:
        raise SilverPublishError("refusing to publish Silver with empty semantic/family/set children")

    receipt_body = {
        "receiptContract": SILVER_TRANSFORM_RECEIPT, "receiptVersion": "1.0.0", "transformId": ST.TRANSFORM_ID,
        "generation": generation, "sourceDatasetVersionId": handle.dataset_version_id,
        "sourceManifestSha256": handle.manifest_sha256, "sourceReceiptSha256": handle.receipt_sha256,
        "sourcePhysicalSha256": handle.physical_sha256, "sourceLogicalSha256": handle.logical_sha256,
        "sourceSchemaSha256": handle.schema_sha256, "governedChronologicalKey": ST.governed_sort_key(),
        "temporalContractSha256": temporal["sha256"], "populationContractSha256": population["sha256"],
        "knowledgeTimeContractSha256": ktime["sha256"], "transformCodeReceiptSha256": tcr["sha256"],
        "semanticContractShas": {k: contracts[k]["sha256"] for k in _ADV},
        "featureFamilySha256": family["sha256"], "featureFamilyId": family["id"],
        "featureSetV2Sha256": fsc["sha256"], "featureSetV2Id": fsc["id"],
        "featureSetBindsOutputLogicalSha256": logical,
        "orderedOutputFeatures": list(fsc["payload"]["exactFinalOrderedFeatureIds"]),
        "producedAdvancedFeatures": list(_ADV), "rowIdentityColumn": id_col, "valueDigestSha256": vdigest,
        "outputPhysicalSha256": physical, "outputLogicalSha256": logical, "outputSchemaSha256": schema_sha,
        "rowCount": table.num_rows, "perSeasonRows": {str(s): sum(1 for r in source_rows if ST.derive_season(r["game_date"]) == s) for s in seasons},
        # the transformation receipt MIRRORS the material temporal/generation authority bound in the code receipt
        "authorizedSeasons": list(ST.DEFAULT_AUTHORIZED_SEASONS), "seasonDerivationSha256": ST.season_derivation_digest(),
        "generationAuthoritySha256": generation_authority, "baseFeatureSourceAuthoritySha256": base_feature_source_authority,
    }
    receipt_sha = sha256_bytes(canonical_json_bytes(receipt_body))
    receipt = {**receipt_body, "receiptSha256": receipt_sha}

    # ---- exact child set (bytes) ----------------------------------------------------------------------------
    children: dict[str, bytes] = {
        "object.parquet": obj_bytes,
        "source-object-receipt.json": _read_source_child(handle, "source-receipt.json"),
        "source-publication-manifest.json": _read_source_child(handle, "source-publication-manifest.json"),
        "temporal-contract.json": canonical_json_bytes(temporal),
        "population-contract.json": canonical_json_bytes(population),
        "knowledge-time-contract.json": canonical_json_bytes(ktime),
        "prior-pa-semantic-contract.json": canonical_json_bytes(contracts[PRIOR_PA_COUNT]),
        "log1p-prior-pa-semantic-contract.json": canonical_json_bytes(contracts[LOG1P_PRIOR_PA_COUNT]),
        "feature-family-contract.json": canonical_json_bytes(family),
        "feature-set-v2-contract.json": canonical_json_bytes(fsc),
        "transform-code-receipt.json": canonical_json_bytes(tcr),
        "transformation-receipt.json": canonical_json_bytes(receipt),
        "value-digest.json": canonical_json_bytes({"valueDigestSha256": vdigest, "featureIds": list(_ADV),
                                                    "rowIdentityColumn": id_col, "rowCount": table.num_rows}),
    }
    manifest_body = {
        "manifestContract": "MLB_SILVER_PUBLICATION_MANIFEST_V1", "status": SILVER_STATUS, "quarantine": SILVER_QUARANTINE,
        "modelEligible": False, "approvedForTraining": False, "selectable": False,
        "transformReceiptSha256": receipt_sha, "transformCodeReceiptSha256": tcr["sha256"],
        "sourceDatasetVersionId": handle.dataset_version_id, "outputPhysicalSha256": physical,
        "outputLogicalSha256": logical, "outputSchemaSha256": schema_sha, "valueDigestSha256": vdigest,
        "rowCount": table.num_rows, "seasons": seasons, "orderedOutputFeatures": receipt_body["orderedOutputFeatures"],
        # `children` here holds every child EXCEPT publication-manifest.json (added after the manifest is built)
        "children": {n: {"sha256": sha256_bytes(b), "bytes": len(b),
                         "contract": _child_contract_id(n, receipt, fsc, family, tcr)}
                     for n, b in sorted(children.items())},
    }
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest_body))
    manifest = {**manifest_body, "manifestSha256": manifest_sha}
    children["publication-manifest.json"] = canonical_json_bytes(manifest)

    if set(children) != set(REQUIRED_SILVER_CHILDREN):
        raise SilverPublishError(f"assembled child set != required set (have {sorted(children)})")

    # ---- publish atomically (content-addressed by the publication-manifest sha), reparse-safe + reuse-guarded ---
    objects_root = _silver_objects_root(silver_root)
    final = contained_no_reparse(objects_root / manifest_sha, [objects_root])
    if not final.exists():
        _atomic_publish_children(objects_root, final, children, manifest_name="publication-manifest.json")
    # pre-registry (Stage C internal): verify the just-published object against the Stage-B governed handle through the
    # typed, single-use, publication-scoped prepublication grant — NEVER the public interface or the candidate registry.
    grant = _issue_prepublication_grant(manifest_sha, final, handle)
    _verify_silver_prepublication(silver_root, manifest_sha, grant)
    return _register(silver_root, handle.dataset_version_id, manifest_sha, receipt_sha, table.num_rows, seasons,
                     source_root=Path(source_root))


def _read_source_child(handle: VerifiedSourceHandle, name: str) -> bytes:
    src = Path(handle.object_path)
    contained_no_reparse(src / name, [src.parent])
    return (src / name).read_bytes()


def _child_contract_id(name: str, receipt, fsc, family, tcr) -> str | None:
    return {"transformation-receipt.json": receipt["receiptContract"],
            "feature-set-v2-contract.json": fsc["id"], "feature-family-contract.json": family["id"],
            "transform-code-receipt.json": tcr["receiptContract"]}.get(name)


def _rows_to_table(rows: Sequence[Mapping[str, Any]]) -> pa.Table:
    cols = {k: [r[k] for r in rows] for k in rows[0]}
    fields = []
    for k in rows[0]:
        v0 = rows[0][k]
        if isinstance(v0, bool):
            fields.append((k, pa.bool_()))
        elif isinstance(v0, float):
            fields.append((k, pa.float64()))
        elif isinstance(v0, int):
            fields.append((k, pa.int64()))
        else:
            fields.append((k, pa.string()))
    return pa.table({k: cols[k] for k, _ in fields}, schema=pa.schema(fields))


def _per_season(rows, season_of_row) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        s = str(int(season_of_row(r)))
        out[s] = out.get(s, 0) + 1
    return out


# =========================================================================== Repair 5 — locked registry
def _silver_registry_path(silver_root: Path) -> Path:
    return Path(silver_root) / "silver-registry.json"


def _silver_lock_path(silver_root: Path) -> Path:
    return Path(silver_root) / ".silver-registry.lock"


def _locked_registry_put(reg_path: Path, lock_path: Path, root: Path, schema_version: str, key: str,
                         entry: Mapping[str, Any]) -> None:
    """Transactional interprocess-locked registry upsert (Repair 5): lock, re-read, validate, detect conflicting
    same-key content, merge (never drop unrelated entries), atomic replace, re-read + verify before unlock. Reparse-
    safe on the registry, its parent, and the lock path."""
    root = Path(root)
    reg_path, lock_path = Path(reg_path), Path(lock_path)
    # D6 — containment is the FIRST filesystem-sensitive operation: the registry parent is contained BEFORE its
    # mkdir; the registry path and the lock path (hence the lock parent) are contained BEFORE any exists/read and
    # BEFORE the lock file is created. All checks use the lstat-based reparse walk (never exists()/mkdir()/read()).
    contained_no_reparse(reg_path.parent, [root])                 # BEFORE mkdir
    reg_path.parent.mkdir(parents=True, exist_ok=True)
    contained_no_reparse(reg_path, [root])                        # BEFORE exists/read AND before lock creation
    contained_no_reparse(lock_path, [root])                       # BEFORE lock creation (contains the lock parent)
    with interprocess_lock(lock_path, blocking=True, timeout=60.0, stale_after=600.0):
        contained_no_reparse(reg_path, [root])                   # TOCTOU recheck under the lock
        if reg_path.is_file():
            reg = json.loads(reg_path.read_text(encoding="utf-8"))     # re-read UNDER the lock
            if not isinstance(reg.get("datasets"), dict):
                raise SilverPublishError("existing registry is structurally invalid")
        else:
            reg = {"schemaVersion": schema_version, "datasets": {}}
        existing = reg["datasets"].get(key)
        if existing is not None and existing != dict(entry):
            raise SilverPublishError(f"registry conflict: key {key!r} already holds divergent content")
        reg["datasets"][key] = dict(entry)                            # merge; unrelated entries preserved
        reg["schemaVersion"] = schema_version
        # D3 — content-address the registry body so a later out-of-band edit of any entry field (e.g. a redirected
        # sourceRoot, a forged datasetVersionId, a moved entry key, a mutated schemaVersion) is tamper-evident.
        reg.pop("registrySha256", None)
        reg["registrySha256"] = sha256_bytes(canonical_json_bytes(reg))
        tmp = reg_path.parent / f".tmp-{uuid.uuid4().hex}"
        contained_no_reparse(tmp, [root])
        with open(tmp, "wb") as fh:
            fh.write(canonical_json_bytes(reg))
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp, reg_path)
        committed = json.loads(reg_path.read_text(encoding="utf-8"))  # verify-after-write UNDER the lock
        if committed["datasets"].get(key) != dict(entry):
            raise SilverPublishError("registry commit verification failed")


def _register(silver_root: Path, source_object_id: str, manifest_sha: str, receipt_sha: str, rows: int,
              seasons: list[int], source_root: Path | None = None) -> dict[str, Any]:
    dsid = f"silver:{source_object_id}:sha256:{manifest_sha}"
    entry = {"datasetVersionId": dsid, "status": SILVER_STATUS, "quarantine": SILVER_QUARANTINE, "modelEligible": False,
             "approvedForTraining": False, "selectable": False, "manifestSha256": manifest_sha,
             "transformReceiptSha256": receipt_sha, "rows": rows, "seasons": seasons, "sourceObjectId": source_object_id}
    if source_root is not None:
        # D3 — the trusted registration records WHERE the canonical Stage-A/B source lives so public verification can
        # re-resolve it INDEPENDENTLY of the candidate bundle. This is a location, never scientific authority.
        entry["sourceRoot"] = str(Path(source_root).resolve())
    _locked_registry_put(_silver_registry_path(silver_root), _silver_lock_path(silver_root), Path(silver_root),
                         "MLB_SILVER_REGISTRY_V1", dsid, entry)
    return entry


def _authenticate_silver_registry(silver_root: Path) -> dict[str, Any]:
    """D3 (7.1/7.3) — AUTHENTICATE the trusted Silver registry BEFORE any entry or source is trusted: containment on
    the registry path; strict schema; recompute + verify the registry's content-address SELF-IDENTITY; and, for every
    entry, require the registry KEY to bind the entry identity EXACTLY —
    ``key == datasetVersionId == silver:{sourceObjectId}:sha256:{manifestSha256}`` — and reject duplicate manifest
    identities. Returns the authenticated ``datasets`` mapping. Fail-closed on ANY deviation; trusts no field merely
    because it is present in the JSON."""
    reg_path = _silver_registry_path(silver_root)
    contained_no_reparse(reg_path, [Path(silver_root)])
    if not reg_path.is_file():
        raise SilverPublishError("no trusted Silver registry present for canonical verification (unregistered candidate)")
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SilverPublishError(f"trusted Silver registry is unreadable: {exc}")
    if not isinstance(reg, dict):
        raise SilverPublishError("trusted Silver registry is malformed")
    if reg.get("schemaVersion") != "MLB_SILVER_REGISTRY_V1":
        raise SilverPublishError(f"trusted Silver registry schema is invalid/forged: {reg.get('schemaVersion')!r}")
    self_addr = sha256_bytes(canonical_json_bytes({k: v for k, v in reg.items() if k != "registrySha256"}))
    if reg.get("registrySha256") != self_addr:
        raise SilverPublishError("trusted Silver registry is not canonically self-addressed (tampered)")
    datasets = reg.get("datasets")
    if not isinstance(datasets, dict):
        raise SilverPublishError("trusted Silver registry datasets are structurally invalid")
    seen_manifests: set[str] = set()
    for key, entry in datasets.items():
        if not isinstance(entry, dict):
            raise SilverPublishError("trusted Silver registry entry is structurally invalid")
        dsid, sobj, msha = entry.get("datasetVersionId"), entry.get("sourceObjectId"), entry.get("manifestSha256")
        if dsid != key:
            raise SilverPublishError(f"registry key {key!r} does not equal its entry datasetVersionId {dsid!r} (tampered)")
        if not sobj or not isinstance(msha, str) or not _HEX64.match(msha):
            raise SilverPublishError("registry entry lacks a bound sourceObjectId / manifest identity (tampered)")
        if key != f"silver:{sobj}:sha256:{msha}":
            raise SilverPublishError("registry key does not bind the source object id + manifest identity exactly (tampered)")
        if msha in seen_manifests:
            raise SilverPublishError("registry contains duplicate manifest identities (tampered)")
        seen_manifests.add(msha)
    return datasets


def _authenticated_lookup(datasets: Mapping[str, Any], manifest_sha: str) -> dict[str, Any] | None:
    """Return the AUTHENTICATED registry entry whose object address is ``manifest_sha`` (or None). A re-addressed
    candidate whose object dir was renamed to a fresh sha is NOT registered, so it has no governed authority."""
    for entry in datasets.values():
        if isinstance(entry, dict) and entry.get("manifestSha256") == manifest_sha:
            return entry
    return None


def is_quarantined_silver(silver_root: Path, dataset_version_id: str) -> bool:
    p = _silver_registry_path(silver_root)
    if not p.is_file():
        return str(dataset_version_id).startswith("silver:")
    reg = json.loads(p.read_text(encoding="utf-8"))
    e = (reg.get("datasets") or {}).get(dataset_version_id)
    if e is None:
        return str(dataset_version_id).startswith("silver:")
    return bool(not e.get("modelEligible") or e.get("quarantine") == SILVER_QUARANTINE)


def assert_model_eligible(silver_root: Path, dataset_version_id: str) -> None:
    if str(dataset_version_id).startswith("silver:") or is_quarantined_silver(silver_root, dataset_version_id):
        raise DatasetNotModelEligibleError(
            f"DATASET_NOT_MODEL_ELIGIBLE: {dataset_version_id} is a QUARANTINED Silver dataset; model training / "
            "binding / activation / comparison is not authorized (SILVER_QUARANTINED)")


# =========================================================================== Repair 3 — complete verification
def verify_silver(silver_root: Path, manifest_sha: str) -> dict[str, Any]:
    """PUBLIC Silver verification (D3 7.4 — no caller-supplied expected authority). The canonical source authority is
    established INDEPENDENTLY of the candidate bundle: AUTHENTICATE the trusted Silver registry first (strict schema +
    content-address self-identity + exact key/manifest binding), require the candidate's object address to be present
    in that authenticated registry, then RE-RESOLVE the canonical Stage-A/B source from the registered source location
    (so a re-addressed candidate, a tampered/redirected registry, or one whose canonical source registry/issuer has
    diverged is rejected). Candidate-declared source fields are never the source of truth — they must EXACTLY equal the
    reconstructed canonical handle. A caller may NOT inject expected authority: the pre-registration Stage-C path uses a
    private, typed, single-use grant (``_verify_silver_prepublication``), never this public entry point."""
    datasets = _authenticate_silver_registry(silver_root)
    reg_entry = _authenticated_lookup(datasets, manifest_sha)
    if reg_entry is None:
        raise SilverPublishError("no canonical Silver registration for this candidate object (re-addressed / unregistered)")
    src_root = reg_entry.get("sourceRoot")
    if not src_root:
        raise SilverPublishError("canonical Silver registration lacks a source location for independent reload")
    try:
        src_root_path = contained_no_reparse(Path(src_root), [Path(src_root)])   # containment BEFORE source-root access
        canonical, _ = resolve_verified_source(src_root_path, reg_entry.get("sourceObjectId"))
    except (SourceAuthorityError, ContainmentError) as exc:
        raise SilverPublishError(f"canonical source re-resolution failed during Silver verification: {exc}")
    return _verify_silver_core(silver_root, manifest_sha, canonical=canonical)


def _verify_silver_prepublication(silver_root: Path, manifest_sha: str,
                                  grant: "_PrepublicationVerificationGrant") -> dict[str, Any]:
    """INTERNAL pre-registration verification (Stage C). The ONLY accepted authority is the typed, single-use,
    publication-scoped prepublication grant, consumed here and bound to the exact object identity. Unavailable to any
    public caller; impossible to duck-type."""
    root = _silver_objects_root(silver_root)
    final = contained_no_reparse(root / manifest_sha, [root])
    canonical = _consume_prepublication_grant(grant, manifest_sha, final)
    return _verify_silver_core(silver_root, manifest_sha, canonical=canonical)


def _verify_silver_core(silver_root: Path, manifest_sha: str, *, canonical: "VerifiedSourceHandle") -> dict[str, Any]:
    """Fully re-verify a published Silver object against an ALREADY-established canonical source authority: containment
    before iterate/open; EXACT child set (no missing/extra); rehash every child; every JSON child validates its own
    content address where it carries one; all parent/child identities cross-checked; physical/logical/schema/value
    digests recomputed; the V2 feature-set binds the OUTPUT logical identity; status is quarantined + model-ineligible;
    every candidate-declared source relationship must EXACTLY equal ``canonical``. Fail-closed on any deviation."""
    root = _silver_objects_root(silver_root)
    final = contained_no_reparse(root / manifest_sha, [root])
    # exact child set BEFORE opening anything of substance
    present = {p.name for p in final.iterdir()}
    if present != set(REQUIRED_SILVER_CHILDREN):
        missing = set(REQUIRED_SILVER_CHILDREN) - present
        extra = present - set(REQUIRED_SILVER_CHILDREN)
        raise SilverPublishError(f"Silver child set invalid (missing={sorted(missing)}, extra={sorted(extra)})")
    for name in REQUIRED_SILVER_CHILDREN:
        contained_no_reparse(final / name, [root])

    def _load(name):
        return json.loads((final / name).read_bytes().decode("utf-8"))

    manifest = _load("publication-manifest.json")
    if sha256_bytes(canonical_json_bytes({k: v for k, v in manifest.items() if k != "manifestSha256"})) != manifest_sha:
        raise SilverPublishError("Silver publication manifest sha does not match its content address (tampered)")
    # rehash every child against the manifest inventory
    inv = manifest["children"]
    for name in REQUIRED_SILVER_CHILDREN:
        if name == "publication-manifest.json":
            continue
        b = (final / name).read_bytes()
        if name not in inv:
            raise SilverPublishError(f"child '{name}' not inventoried in the publication manifest")
        if sha256_bytes(b) != inv[name]["sha256"] or len(b) != inv[name]["bytes"]:
            raise SilverPublishError(f"child '{name}' bytes/sha differ from the manifest inventory (tampered)")

    receipt = _load("transformation-receipt.json")
    if sha256_bytes(canonical_json_bytes({k: v for k, v in receipt.items() if k != "receiptSha256"})) != receipt.get("receiptSha256") \
            or receipt["receiptSha256"] != manifest["transformReceiptSha256"]:
        raise SilverPublishError("Silver transformation receipt sha does not verify")
    tcr = _load("transform-code-receipt.json")
    if sha256_bytes(canonical_json_bytes({k: v for k, v in tcr.items() if k != "sha256"})) != tcr.get("sha256") \
            or tcr["sha256"] != receipt["transformCodeReceiptSha256"] or tcr["sha256"] != manifest["transformCodeReceiptSha256"]:
        raise SilverPublishError("Silver transform-code receipt sha does not verify")
    fsc = _load("feature-set-v2-contract.json")
    if fsc["sha256"] != receipt["featureSetV2Sha256"]:
        raise SilverPublishError("feature-set V2 sha mismatch vs receipt")
    if fsc["payload"].get("datasetContentSha256") not in (receipt["outputLogicalSha256"], receipt.get("featureSetBindsOutputLogicalSha256")):
        raise SilverPublishError("feature-set V2 does not bind the OUTPUT logical identity")
    family = _load("feature-family-contract.json")
    if family["sha256"] != receipt["featureFamilySha256"]:
        raise SilverPublishError("feature-family sha mismatch vs receipt")
    for feat, child in ((PRIOR_PA_COUNT, "prior-pa-semantic-contract.json"), (LOG1P_PRIOR_PA_COUNT, "log1p-prior-pa-semantic-contract.json")):
        sc = _load(child)
        if sc["sha256"] != receipt["semanticContractShas"][feat]:
            raise SilverPublishError(f"semantic contract sha mismatch for {feat}")
    # family membership: the family's ordered member contract SHAs must be exactly the two advanced semantic SHAs
    if list(family["payload"].get("orderedFeatureContractShas", [])) != [receipt["semanticContractShas"][f] for f in _ADV]:
        raise SilverPublishError("family membership mismatch")

    obj_bytes = (final / "object.parquet").read_bytes()
    if sha256_bytes(obj_bytes) != receipt["outputPhysicalSha256"]:
        raise SilverPublishError("Silver object bytes differ from the receipt (tampered)")
    table = pq.read_table(pa.BufferReader(obj_bytes))
    if _schema_sha_of(table) != receipt["outputSchemaSha256"]:
        raise SilverPublishError("Silver object schema differs from the receipt (tampered)")
    rows = table.to_pylist()
    id_col = receipt["rowIdentityColumn"]
    if value_digest(rows, receipt["producedAdvancedFeatures"], id_col=id_col) != receipt["valueDigestSha256"]:
        raise SilverPublishError("Silver value digest recomputed from the published object does not verify (tampered)")
    recomputed_logical = sha256_bytes(canonical_json_bytes({"schemaVersion": "MLB_SILVER_OBJECT_V1",
                                                            "schemaSha256": receipt["outputSchemaSha256"],
                                                            "rows": table.num_rows, "valueDigest": receipt["valueDigestSha256"]}))
    if recomputed_logical != receipt["outputLogicalSha256"]:
        raise SilverPublishError("Silver output logical identity recompute mismatch (tampered)")

    # ---- D3: the CANONICAL source authority was established INDEPENDENTLY of this candidate bundle (by the public
    # verifier, from the authenticated registry; or by the internal prepublication grant). Every candidate-declared
    # source relationship must equal it EXACTLY. A re-addressed candidate is not registered; a candidate whose
    # canonical source registry/issuer has diverged fails to re-resolve; a coordinated new parent never matches.
    if type(canonical) is not VerifiedSourceHandle:
        raise SilverPublishError("internal error: canonical source authority is not a genuine server-issued handle")
    if not (receipt.get("sourceDatasetVersionId") == canonical.dataset_version_id
            and receipt.get("sourceLogicalSha256") == canonical.logical_sha256
            and receipt.get("sourcePhysicalSha256") == canonical.physical_sha256
            and receipt.get("sourceSchemaSha256") == canonical.schema_sha256
            and receipt.get("sourceReceiptSha256") == canonical.receipt_sha256
            and receipt.get("sourceManifestSha256") == canonical.manifest_sha256):
        raise SilverPublishError("candidate Silver source authority diverges from the reconstructed canonical source")
    if manifest.get("sourceDatasetVersionId") != canonical.dataset_version_id:
        raise SilverPublishError("candidate publication-manifest source identity diverges from canonical (tampered)")
    if sorted(int(s) for s in manifest.get("seasons", [])) != sorted(int(s) for s in receipt.get("perSeasonRows", {})):
        raise SilverPublishError("candidate publication-manifest seasons diverge from the transformation receipt (tampered)")
    if not (manifest.get("rowCount") == receipt.get("rowCount") == table.num_rows):
        raise SilverPublishError("candidate publication-manifest row count diverges from the canonical output (tampered)")

    # ---- R3: RECONSTRUCT every silver-authored contract from CANONICAL AUTHORITY and require an EXACT byte match.
    # A coordinated re-addressing (recomputing the outer inventory + manifest hashes and renaming the object dir)
    # keeps the bundle internally consistent, so internal-consistency checks pass — but a reconstructed authority
    # never matches a forged relationship. Every acceptance decision below is made against reconstructed truth.
    def _cb(name):
        return (final / name).read_bytes()

    for name, canon in (("temporal-contract.json", GC.temporal_contract()),
                        ("population-contract.json", GC.population_contract()),
                        ("knowledge-time-contract.json", GC.knowledge_time_contract())):
        if _cb(name) != canonical_json_bytes(canon) or canon["sha256"] != receipt[{
                "temporal-contract.json": "temporalContractSha256", "population-contract.json": "populationContractSha256",
                "knowledge-time-contract.json": "knowledgeTimeContractSha256"}[name]]:
            raise SilverPublishError(f"{name} does not reconstruct to the canonical governed contract (tampered)")

    expected_tcr = transform_code_receipt(params=tcr["params"])
    if _cb("transform-code-receipt.json") != canonical_json_bytes(tcr) \
            or tcr.get("implementationDigest") != expected_tcr["implementationDigest"] \
            or tcr.get("fileShas") != expected_tcr["fileShas"]:
        raise SilverPublishError("transform-code receipt does not reconstruct to the actual implementation (tampered)")

    has_gs = ST.GAME_SEQUENCE in table.schema.names
    rebuilt = silver_semantic_contracts(source_object_id=receipt["sourceDatasetVersionId"],
                                        source_receipt_sha=receipt["sourceReceiptSha256"],
                                        transform_code_sha=tcr["sha256"], has_game_sequence=has_gs)
    for feat, name in ((PRIOR_PA_COUNT, "prior-pa-semantic-contract.json"),
                       (LOG1P_PRIOR_PA_COUNT, "log1p-prior-pa-semantic-contract.json")):
        if _cb(name) != canonical_json_bytes(rebuilt[feat]) or rebuilt[feat]["sha256"] != receipt["semanticContractShas"][feat]:
            raise SilverPublishError(f"{name} does not reconstruct from the verified source/transform authority (tampered)")

    rebuilt_family = silver_family_contract(rebuilt)
    if _cb("feature-family-contract.json") != canonical_json_bytes(rebuilt_family) \
            or rebuilt_family["sha256"] != receipt["featureFamilySha256"]:
        raise SilverPublishError("feature-family contract does not reconstruct from its verified members (tampered)")

    base_ids = list(receipt["orderedOutputFeatures"])[:-len(_ADV)]
    full = {**FS.all_feature_semantic_contracts(), **rebuilt}
    rebuilt_fsc = silver_feature_set_v2(dataset_version_id=f"silver:{receipt['sourceDatasetVersionId']}",
                                        dataset_content_sha=receipt["outputLogicalSha256"], base_feature_ids=base_ids,
                                        contracts=full)
    if _cb("feature-set-v2-contract.json") != canonical_json_bytes(rebuilt_fsc) \
            or rebuilt_fsc["sha256"] != receipt["featureSetV2Sha256"] \
            or receipt.get("featureSetBindsOutputLogicalSha256") != receipt["outputLogicalSha256"]:
        raise SilverPublishError("feature-set V2 does not reconstruct (family/output/source authority) (tampered)")

    vd = json.loads(_cb("value-digest.json").decode("utf-8"))
    if list(vd.get("featureIds", [])) != list(_ADV) or vd.get("valueDigestSha256") != receipt["valueDigestSha256"] \
            or vd.get("rowCount") != table.num_rows or vd.get("rowIdentityColumn") != id_col:
        raise SilverPublishError("value-digest relational metadata does not reconstruct from the object (tampered)")

    # source-object receipt/manifest COPIES: self-address + relational agreement with the transformation receipt
    src_receipt = json.loads(_cb("source-object-receipt.json").decode("utf-8"))
    src_manifest = json.loads(_cb("source-publication-manifest.json").decode("utf-8"))
    src_r_self = sha256_bytes(canonical_json_bytes({k: v for k, v in src_receipt.items() if k != "receiptSha256"}))
    src_m_self = sha256_bytes(canonical_json_bytes({k: v for k, v in src_manifest.items() if k != "manifestSha256"}))
    if src_receipt.get("receiptSha256") != src_r_self or src_r_self != receipt["sourceReceiptSha256"]:
        raise SilverPublishError("source receipt copy self-address / receipt binding mismatch (tampered)")
    if src_manifest.get("manifestSha256") != src_m_self or src_m_self != receipt["sourceManifestSha256"]:
        raise SilverPublishError("source manifest copy self-address / receipt binding mismatch (tampered)")
    if not (src_receipt.get("datasetVersionId") == src_manifest.get("datasetVersionId") == receipt["sourceDatasetVersionId"]):
        raise SilverPublishError("source dataset relationship mismatch (tampered)")
    if not (src_receipt.get("logicalSha256") == src_manifest.get("logicalSha256") == receipt["sourceLogicalSha256"]):
        raise SilverPublishError("source logical relationship mismatch (tampered)")
    if not (src_receipt.get("physicalSha256") == src_manifest.get("physicalSha256") == receipt["sourcePhysicalSha256"]):
        raise SilverPublishError("source physical relationship mismatch (tampered)")
    if not (src_receipt.get("schemaSha256") == src_manifest.get("schemaSha256") == receipt["sourceSchemaSha256"]):
        raise SilverPublishError("source schema relationship mismatch (tampered)")
    if src_receipt.get("rowCount") != src_manifest.get("rowCount"):
        raise SilverPublishError("source row-count relationship mismatch (tampered)")
    if sorted(src_receipt.get("seasons", [])) != sorted(src_manifest.get("seasons", [])):
        raise SilverPublishError("source season relationship mismatch (tampered)")

    if manifest.get("manifestContract") != "MLB_SILVER_PUBLICATION_MANIFEST_V1":
        raise SilverPublishError("publication manifest contract identity is forged (tampered)")

    if manifest.get("modelEligible") or manifest.get("approvedForTraining") or manifest.get("selectable"):
        raise SilverPublishError("Silver manifest must remain quarantined / model-ineligible / not selectable")
    if manifest.get("status") != SILVER_STATUS or manifest.get("quarantine") != SILVER_QUARANTINE:
        raise SilverPublishError("Silver manifest must be SILVER_NORMALIZED / QUARANTINED")
    return {"manifest": manifest, "receipt": receipt, "valueDigestSha256": receipt["valueDigestSha256"], "objectDir": final}
