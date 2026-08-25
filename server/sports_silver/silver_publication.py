"""Governed, immutable, QUARANTINED Silver-table publication (Phase 7B1, Sections 14, 30, 31).

Integrates WITH the accepted Phase 7D.5A publication model (immutable content-addressed object + immutable,
complete-byte-addressed registration record + minimal locator index + fail-closed quarantine) rather than replacing it,
and reuses the accepted content-addressing primitives. It does NOT modify the frozen ``silver_publish`` module.

Every published object is QUARANTINED / NOT_MODEL_ELIGIBLE / NOT_APPROVED_FOR_TRAINING / NOT_SELECTABLE and binds full
lineage: the governed Bronze manifest identity, contributing source-partition identities, the normalization CODE
identity, the schema/contract identity, the identity-bridge version, row-count evidence, and season evidence. An
independent auditor can answer: which exact Bronze bytes + which normalization implementation + which identity mappings
produced this object, and can it be reconstructed and verified.
"""
from __future__ import annotations

import inspect
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_cockpit.interprocess_lock import interprocess_lock
from ..sports_cockpit.path_containment import ContainmentError, contained_no_reparse
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from . import bronze_authority as BA
from . import canonical_ids as CID
from . import contracts as CT

SILVER_TABLE_OBJECT = "MLB_SILVER_TABLE_OBJECT_V1"
SILVER_TABLE_RECEIPT = "MLB_SILVER_TABLE_TRANSFORM_RECEIPT_V1"
SILVER_TABLE_MANIFEST = "MLB_SILVER_TABLE_PUBLICATION_MANIFEST_V1"
SILVER_TABLE_REGISTRATION = "MLB_SILVER_TABLE_REGISTRATION_RECORD_V1"
SILVER_TABLE_REGISTRY = "MLB_SILVER_TABLE_REGISTRY_V1"
IDENTITY_BRIDGE_VERSION = "1.0.0"
_HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")

REQUIRED_CHILDREN = ("object.parquet", "table-contract.json", "transformation-receipt.json", "publication-manifest.json")


class SilverTablePublishError(RuntimeError):
    """A governed Silver-table publication/verification precondition failed (fail-closed)."""


class SilverTableNotModelEligibleError(RuntimeError):
    """A quarantined Phase 7B1 Silver table was offered to a model-eligible path (fail-closed)."""


def assert_not_model_eligible(dataset_version_id: str) -> None:
    """The QUARANTINE BARRIER (Section 31): a Phase 7B1 Silver-table dataset (``silver-table:...``) is never
    model-eligible. Any model-binding / run-authority / training / scoring / activation path that resolves such a
    dataset MUST call this and fail closed BEFORE model execution."""
    if str(dataset_version_id).startswith("silver-table:"):
        raise SilverTableNotModelEligibleError(
            f"SILVER_QUARANTINED: {dataset_version_id} is a QUARANTINED Phase 7B1 Silver object; model binding / "
            "run authority / training / scoring / activation / comparison is not authorized")


# --------------------------------------------------------------------------- deterministic serialization
def _rows_to_table(rows: Sequence[Mapping[str, Any]], field_order: Sequence[str]) -> pa.Table:
    cols = {k: [_json_scalar(r.get(k)) for r in rows] for k in field_order}
    return pa.table({k: pa.array(cols[k], type=pa.string()) for k in field_order})


def _json_scalar(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return canonical_json_bytes(v).decode("utf-8")
    return str(v)


def _object_bytes(table: pa.Table) -> bytes:
    sink = pa.BufferOutputStream()
    pq.write_table(table.replace_schema_metadata(None).combine_chunks(), sink, compression="none",
                   row_group_size=max(1, table.num_rows), use_dictionary=False, write_statistics=False,
                   store_schema=True)
    return sink.getvalue().to_pybytes()


def _value_digest(rows: Sequence[Mapping[str, Any]], field_order: Sequence[str], natural_key: Sequence[str]) -> str:
    """Content identity invariant to row ORDER: sort rows by natural key, then hash each row's canonical field values
    INCREMENTALLY (bounded memory, no giant intermediate JSON — Section 17)."""
    import hashlib
    def key(r):
        return tuple("" if r.get(k) is None else str(r.get(k)) for k in natural_key)
    h = hashlib.sha256()
    h.update(canonical_json_bytes(["MLB_SILVER_TABLE_VALUE_DIGEST_V1", list(field_order)]))
    for r in sorted(rows, key=key):
        h.update(canonical_json_bytes([_json_scalar(r.get(f)) for f in field_order]))
    return h.hexdigest()


# --------------------------------------------------------------------------- code identity
def _normalization_code_digest(code_modules: Sequence[Any]) -> dict[str, Any]:
    files = {}
    for mod in code_modules:
        try:
            files[Path(mod.__file__).name] = sha256_bytes(Path(mod.__file__).read_bytes())
        except Exception:
            files[getattr(mod, "__name__", str(mod))] = "UNAVAILABLE"
    impl = sha256_bytes(canonical_json_bytes(files))
    return {"implementationDigest": impl, "fileShas": files,
            "runtime": {"python": sys.version.split()[0], "pyarrow": pa.__version__}}


def _silver_tables_root(silver_root: Path) -> Path:
    return Path(silver_root) / "objects" / "sha256"


def _registrations_root(silver_root: Path) -> Path:
    return Path(silver_root) / "silver-table-registrations" / "objects" / "sha256"


def _registry_path(silver_root: Path) -> Path:
    return Path(silver_root) / "silver-table-registry.json"


def _lock_path(silver_root: Path) -> Path:
    return Path(silver_root) / ".silver-table-registry.lock"


# --------------------------------------------------------------------------- publish
def publish_silver_table(*, silver_root: Path, contract: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
                         bronze_manifest: Mapping[str, Any], source_partition_ids: Sequence[str],
                         code_modules: Sequence[Any], field_order: Sequence[str]) -> dict[str, Any]:
    """Publish ONE normalized Silver table as an immutable, content-addressed, QUARANTINED object with full lineage,
    then register it (interprocess-locked) through an immutable complete-byte-addressed registration record. Idempotent:
    re-publishing identical content converges to the same object address and reuses the object."""
    silver_root = Path(silver_root)
    contained_no_reparse(_silver_tables_root(silver_root), [silver_root])       # D6 containment first
    contained_no_reparse(_registrations_root(silver_root), [silver_root])
    name = contract["tableName"]
    seasons = sorted(int(s) for s in contract.get("seasons", []))
    if any(s in (2025, 2026) for s in seasons):
        raise SilverTablePublishError(f"SEAL VIOLATION: {name} declares a sealed season {seasons}")
    natural_key = list(contract.get("naturalKey", []))

    table = _rows_to_table(rows, field_order)
    obj_bytes = _object_bytes(table)
    physical = sha256_bytes(obj_bytes)
    schema_sha = sha256_bytes(canonical_json_bytes([{"name": f.name, "type": str(f.type)} for f in table.schema]))
    value_digest = _value_digest(rows, field_order, natural_key or field_order)
    contract_bytes = canonical_json_bytes(dict(contract))
    contract_sha = sha256_bytes(contract_bytes)
    code = _normalization_code_digest(code_modules)

    receipt_body = {
        "receiptContract": SILVER_TABLE_RECEIPT, "tableName": name, "schemaVersion": contract["schemaVersion"],
        "bronzeManifestSha256": BA.EXPECTED_BRONZE_MANIFEST_SHA256, "bronzeManifestContract": BA.BRONZE_MANIFEST_CONTRACT,
        "sourcePartitionIds": sorted(source_partition_ids), "sourcePartitionCount": len(set(source_partition_ids)),
        "identityBridgeVersion": IDENTITY_BRIDGE_VERSION,
        "normalizationCode": code, "tableContractSha256": contract_sha,
        "outputPhysicalSha256": physical, "outputSchemaSha256": schema_sha, "valueDigestSha256": value_digest,
        "rowCount": table.num_rows, "seasons": seasons, "fieldOrder": list(field_order),
        **CT.QUARANTINE_STATE,
    }
    receipt_bytes = canonical_json_bytes(receipt_body)
    receipt_sha = sha256_bytes(receipt_bytes)

    children = {"object.parquet": obj_bytes, "table-contract.json": contract_bytes,
                "transformation-receipt.json": receipt_bytes}
    manifest_body = {
        "manifestContract": SILVER_TABLE_MANIFEST, "tableName": name, **CT.QUARANTINE_STATE,
        "transformReceiptSha256": receipt_sha, "outputPhysicalSha256": physical, "valueDigestSha256": value_digest,
        "rowCount": table.num_rows, "seasons": seasons, "tableContractSha256": contract_sha,
        "children": {n: {"sha256": sha256_bytes(b), "bytes": len(b)} for n, b in sorted(children.items())},
    }
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest_body))
    children["publication-manifest.json"] = canonical_json_bytes({**manifest_body, "manifestSha256": manifest_sha})
    if set(children) != set(REQUIRED_CHILDREN):
        raise SilverTablePublishError(f"assembled child set != required set for {name}")

    objects_root = _silver_tables_root(silver_root)
    final = contained_no_reparse(objects_root / manifest_sha, [objects_root])
    if not final.exists():
        _atomic_publish_children(objects_root, final, children)

    # immutable registration record — complete-byte-addressed (no embedded self-hash)
    dsid = f"silver-table:{name}:sha256:{manifest_sha}"
    reg_body = {
        "recordContract": SILVER_TABLE_REGISTRATION, "recordVersion": "1.0.0", "datasetVersionId": dsid,
        "tableName": name, "publicationManifestSha256": manifest_sha, "transformReceiptSha256": receipt_sha,
        "outputPhysicalSha256": physical, "valueDigestSha256": value_digest, "tableContractSha256": contract_sha,
        "bronzeManifestSha256": BA.EXPECTED_BRONZE_MANIFEST_SHA256, "rowCount": table.num_rows, "seasons": seasons,
        **CT.QUARANTINE_STATE,
    }
    reg_bytes = canonical_json_bytes(reg_body)
    registration_sha = sha256_bytes(reg_bytes)
    _write_addressed(_registrations_root(silver_root), registration_sha, reg_bytes, silver_root)
    _locked_put(silver_root, dsid, {"registrationSha256": registration_sha})

    # publish-time verification (independent of the mutable index) proves COMPLETE before returning
    verify_silver_table(silver_root, manifest_sha)
    return {"datasetVersionId": dsid, "tableName": name, "manifestSha256": manifest_sha, "receiptSha256": receipt_sha,
            "registrationSha256": registration_sha, "outputPhysicalSha256": physical, "valueDigestSha256": value_digest,
            "rowCount": table.num_rows, "seasons": seasons, **CT.QUARANTINE_STATE}


def _atomic_publish_children(objects_root: Path, final: Path, children: Mapping[str, bytes]) -> None:
    objects_root.mkdir(parents=True, exist_ok=True)
    if final.exists():
        return
    staging = objects_root / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    try:
        for n, b in children.items():
            (staging / n).write_bytes(b)
        if not final.exists():
            try:
                os.replace(staging, final)
            except OSError:
                pass
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging, ignore_errors=True)


def _write_addressed(root: Path, sha: str, data: bytes, silver_root: Path) -> None:
    contained_no_reparse(root, [Path(silver_root)])
    root.mkdir(parents=True, exist_ok=True)
    final = contained_no_reparse(root / f"{sha}.json", [root])
    if final.exists():
        if final.read_bytes() != data:
            raise SilverTablePublishError("existing registration record differs from its content address (tampered)")
        return
    tmp = root / f".tmp-{uuid.uuid4().hex}.json"
    try:
        tmp.write_bytes(data)
        try:
            os.replace(tmp, final)
        except OSError:
            if not (final.exists() and final.read_bytes() == data):
                raise
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _locked_put(silver_root: Path, key: str, entry: Mapping[str, Any]) -> None:
    reg_path, lock_path = _registry_path(silver_root), _lock_path(silver_root)
    contained_no_reparse(reg_path, [Path(silver_root)])
    contained_no_reparse(lock_path, [Path(silver_root)])
    with interprocess_lock(lock_path, blocking=True, timeout=60.0, stale_after=600.0):
        reg = {"schemaVersion": SILVER_TABLE_REGISTRY, "datasets": {}}
        if reg_path.is_file():
            import json
            reg = json.loads(reg_path.read_text(encoding="utf-8"))
        existing = reg["datasets"].get(key)
        if existing is not None and existing != dict(entry):
            raise SilverTablePublishError(f"registry conflict: key {key!r} already holds divergent content")
        reg["datasets"][key] = dict(entry)
        reg["schemaVersion"] = SILVER_TABLE_REGISTRY
        tmp = reg_path.parent / f".tmp-{uuid.uuid4().hex}"
        tmp.write_bytes(canonical_json_bytes(reg))
        os.replace(tmp, reg_path)


# --------------------------------------------------------------------------- verify
def _load_registration(silver_root: Path, registration_sha: str) -> dict[str, Any]:
    import json
    if not _HEX64.match(registration_sha):
        raise SilverTablePublishError("bad registration sha")
    root = _registrations_root(silver_root)
    path = contained_no_reparse(root / f"{registration_sha}.json", [root])
    if not path.is_file():
        raise SilverTablePublishError("immutable registration record missing (unregistered/tampered)")
    raw = path.read_bytes()
    if sha256_bytes(raw) != registration_sha:
        raise SilverTablePublishError("registration record not content-addressed at its filename (tampered)")
    rec = json.loads(raw.decode("utf-8"))
    if rec.get("recordContract") != SILVER_TABLE_REGISTRATION or "registrationSha256" in rec:
        raise SilverTablePublishError("registration record contract forged / embeds self-hash")
    return rec


def verify_silver_table(silver_root: Path, manifest_sha: str) -> dict[str, Any]:
    """Independent verification against the immutable authority: authenticate the minimal index, load the immutable
    registration record (complete-byte address), then re-verify the object children (exact set, per-child hashes,
    manifest self-address, receipt binding, recomputed physical + order-invariant value digest) and confirm the object
    stays QUARANTINED / NOT model-eligible. Fail-closed on any deviation."""
    import json
    silver_root = Path(silver_root)
    reg_path = _registry_path(silver_root)
    contained_no_reparse(reg_path, [silver_root])
    if not reg_path.is_file():
        raise SilverTablePublishError("no Silver table registry present (unregistered)")
    reg = json.loads(reg_path.read_text(encoding="utf-8"))
    if reg.get("schemaVersion") != SILVER_TABLE_REGISTRY:
        raise SilverTablePublishError("silver table registry schema forged")
    matches = [(k, e) for k, e in (reg.get("datasets") or {}).items()
               if isinstance(e, dict) and set(e.keys()) == {"registrationSha256"}
               and k.rsplit(":sha256:", 1)[-1] == manifest_sha]
    if len(matches) != 1:
        raise SilverTablePublishError("no unique registration for this object (re-addressed/unregistered/ambiguous)")
    index_key, entry = matches[0]
    record = _load_registration(silver_root, entry["registrationSha256"])
    if record.get("datasetVersionId") != index_key or record.get("publicationManifestSha256") != manifest_sha:
        raise SilverTablePublishError("registration record identity mismatch (tampered index)")

    root = _silver_tables_root(silver_root)
    final = contained_no_reparse(root / manifest_sha, [root])
    present = {p.name for p in final.iterdir()}
    if present != set(REQUIRED_CHILDREN):
        raise SilverTablePublishError(f"child set invalid: {sorted(present)}")
    manifest = json.loads((final / "publication-manifest.json").read_bytes().decode("utf-8"))
    if sha256_bytes(canonical_json_bytes({k: v for k, v in manifest.items() if k != "manifestSha256"})) != manifest_sha:
        raise SilverTablePublishError("publication manifest sha != content address (tampered)")
    inv = manifest["children"]
    for n in REQUIRED_CHILDREN:
        if n == "publication-manifest.json":
            continue
        b = (final / n).read_bytes()
        if sha256_bytes(b) != inv[n]["sha256"] or len(b) != inv[n]["bytes"]:
            raise SilverTablePublishError(f"child {n} differs from manifest inventory (tampered)")
    receipt = json.loads((final / "transformation-receipt.json").read_bytes().decode("utf-8"))
    if receipt.get("receiptContract") != SILVER_TABLE_RECEIPT:
        raise SilverTablePublishError("transformation receipt contract forged")
    if sha256_bytes(canonical_json_bytes(receipt)) != manifest["transformReceiptSha256"]:
        raise SilverTablePublishError("transformation receipt sha != manifest binding (tampered)")
    obj = (final / "object.parquet").read_bytes()
    if sha256_bytes(obj) != receipt["outputPhysicalSha256"] or receipt["outputPhysicalSha256"] != manifest["outputPhysicalSha256"]:
        raise SilverTablePublishError("object bytes differ from receipt/manifest (tampered)")
    if receipt.get("bronzeManifestSha256") != BA.EXPECTED_BRONZE_MANIFEST_SHA256:
        raise SilverTablePublishError("object is not bound to the governed Bronze manifest (lineage broken)")
    # order-invariant value digest recompute from the object bytes
    table = pq.read_table(pa.BufferReader(obj))
    field_order = list(receipt["fieldOrder"])
    rows = [{k: table.column(k)[i].as_py() for k in field_order} for i in range(table.num_rows)]
    contract = json.loads((final / "table-contract.json").read_bytes().decode("utf-8"))
    nk = contract.get("naturalKey") or field_order
    if _value_digest(rows, field_order, nk) != receipt["valueDigestSha256"]:
        raise SilverTablePublishError("recomputed order-invariant value digest != receipt (tampered)")
    if manifest.get("modelEligible") or manifest.get("approvedForTraining") or manifest.get("selectable") \
            or manifest.get("quarantine") != "QUARANTINED":
        raise SilverTablePublishError("Silver object must remain QUARANTINED / NOT model-eligible")
    return {"tableName": manifest["tableName"], "manifestSha256": manifest_sha, "rowCount": table.num_rows,
            "seasons": receipt["seasons"], "valueDigestSha256": receipt["valueDigestSha256"],
            "quarantine": manifest["quarantine"], "modelEligible": manifest["modelEligible"]}
