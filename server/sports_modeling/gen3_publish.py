"""Immutable, atomic, content-addressed Gen-3 publication (Phase 7A Gates 3-5).

Replaces Phase-7's fixed-path direct overwrite. Each object (research view 2021-2024, sealed 2025) is
staged on the destination filesystem, validated, fsynced, hashed, and atomically published under
``objects/sha256/<logical-content-sha>/``. Re-runs reuse an identical existing object and REJECT any
divergent conflict. Symlinks/reparse points and path escapes are rejected. A complete provenance
manifest (Gate 4) binds every parent/contract/code/environment identity, and critical identities are
embedded into the Parquet metadata as well.

Physical blinding (Gate 5): research and sealed seasons are published as SEPARATE immutable objects, so
the default research loader can open the research object without the sealed 2025 bytes being resident.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes

GEN3_PUBLISH_SCHEMA_VERSION = "MLB_GEN3_PUBLICATION_V1"
_BATCH = 65_536


class Gen3PublishError(RuntimeError):
    """Raised on any immutability/atomicity/tamper violation during publication."""


def logical_content_sha(table: pa.Table, *, contract_bundle_sha: str, schema_sha: str) -> str:
    """Order-sensitive, metadata-free, ROUND-TRIP-STABLE logical digest (Phase 7C Gate 5).

    The digest binds (schemaVersion, contract bundle, schema, row count) and the table's values. It is
    computed over a canonical, deterministic Parquet serialization of the metadata-stripped, chunk-combined
    table (no dictionary encoding, no statistics, single row group). Unlike the previous Arrow-IPC batch
    hash, this representation is a fixed point under a Parquet write->read round-trip, so the publisher's
    content-address and the consumer's verification digest are identical for the SAME published object.
    The canonical serialization is defined w.r.t. the pinned Arrow/Parquet writer version recorded in the
    object receipt/environment identity."""
    digest = hashlib.sha256()
    digest.update(canonical_json_bytes({
        "schemaVersion": GEN3_PUBLISH_SCHEMA_VERSION,
        "contractBundleSha256": contract_bundle_sha,
        "schemaSha256": schema_sha,
        "rowCount": table.num_rows,
    }))
    canonical = table.replace_schema_metadata(None).combine_chunks()
    sink = pa.BufferOutputStream()
    pq.write_table(canonical, sink, compression="none", row_group_size=max(1, canonical.num_rows),
                   use_dictionary=False, write_statistics=False, store_schema=True)
    digest.update(sink.getvalue().to_pybytes())
    return digest.hexdigest()


def _code_revision() -> tuple[str, bool]:
    try:
        rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).resolve().parents[2]).decode().strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=Path(__file__).resolve().parents[2]).decode().strip())
        return rev, dirty
    except Exception:
        return "UNKNOWN", True


def _dependency_versions() -> dict[str, str]:
    import numpy, pandas, sklearn
    return {"python": sys.version.split()[0], "pyarrow": pa.__version__, "numpy": numpy.__version__,
            "pandas": pandas.__version__, "sklearn": sklearn.__version__}


def _reject_links(path: Path, root: Path) -> None:
    """Reject symlink/junction/reparse anywhere between root and path."""
    cur = path
    while True:
        if cur.is_symlink():
            raise Gen3PublishError(f"link/reparse point rejected in publication path: {cur}")
        if cur == root or cur.parent == cur:
            break
        cur = cur.parent


def _schema_sha(table: pa.Table) -> str:
    return sha256_bytes(canonical_json_bytes([{ "name": f.name, "type": str(f.type), "nullable": f.nullable}
                                              for f in table.schema]))


def publish_object(
    objects_root: Path,
    table: pa.Table,
    *,
    object_kind: str,
    contracts: Mapping[str, Any],
    contract_bundle_sha: str,
    provenance_extra: Mapping[str, Any],
) -> dict[str, Any]:
    """Publish one immutable content-addressed object; return its manifest. Idempotent + conflict-safe."""
    objects_root = objects_root.resolve()
    schema_sha = _schema_sha(table)
    content_sha = logical_content_sha(table, contract_bundle_sha=contract_bundle_sha, schema_sha=schema_sha)
    rev, dirty = _code_revision()
    object_dir = (objects_root / "objects" / "sha256" / content_sha).resolve()
    if objects_root not in object_dir.parents:
        raise Gen3PublishError("resolved object path escapes the objects root")

    # Embed critical identities into Parquet metadata (Gate 4) in addition to the external manifest.
    meta = {
        b"artifactSchemaVersion": GEN3_PUBLISH_SCHEMA_VERSION.encode(),
        b"objectKind": object_kind.encode(),
        b"logicalContentSha256": content_sha.encode(),
        b"schemaSha256": schema_sha.encode(),
        b"contractBundleSha256": contract_bundle_sha.encode(),
        b"temporalContractId": contracts["temporal"]["id"].encode(),
        b"featureSchemaId": contracts["featureSchema"]["id"].encode(),
        b"targetContractId": contracts["target"]["id"].encode(),
        b"codeRevision": rev.encode(),
    }
    materialized = table.replace_schema_metadata({**(table.schema.metadata or {}), **meta})

    manifest = {
        "schemaVersion": GEN3_PUBLISH_SCHEMA_VERSION,
        "objectKind": object_kind,
        "createdAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "buildRunId": uuid.uuid4().hex,
        "rowCount": table.num_rows,
        "logicalContentSha256": content_sha,
        "schemaSha256": schema_sha,
        "contractBundleSha256": contract_bundle_sha,
        "contracts": {k: v["id"] for k, v in contracts.items()},
        "codeRevision": rev,
        "dirtyTree": dirty,
        "environment": _dependency_versions(),
        "platform": platform.platform(),
        **dict(provenance_extra),
    }

    # Idempotent reuse / conflict rejection.
    parquet_path = object_dir / f"{object_kind}.parquet"
    if object_dir.exists():
        _reject_links(object_dir, objects_root)
        if parquet_path.is_symlink() or not parquet_path.is_file():
            raise Gen3PublishError(f"existing object is incomplete or a link: {object_dir}")
        # Tamper rejection: the existing object's LOGICAL content must still hash to its content-address.
        # An unreadable/corrupt file is itself a tamper condition.
        try:
            existing_table = pq.read_table(parquet_path)
            existing_logical = logical_content_sha(
                existing_table.replace_schema_metadata(None),
                contract_bundle_sha=contract_bundle_sha, schema_sha=_schema_sha(existing_table),
            )
        except Gen3PublishError:
            raise
        except Exception as exc:
            raise Gen3PublishError(f"immutable object unreadable/tampered: {object_dir}") from exc
        if existing_logical != content_sha:
            raise Gen3PublishError(f"immutable object tampered: {object_dir} logical sha diverged")
        manifest["physicalParquetSha256"] = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
        manifest["reused"] = True
        return manifest

    # Stage on the destination filesystem, validate, fsync, atomic publish.
    staging = (objects_root / "objects" / "sha256" / f".staging-{uuid.uuid4().hex}").resolve()
    staging.mkdir(parents=True, exist_ok=False)
    try:
        stage_parquet = staging / f"{object_kind}.parquet"
        pq.write_table(materialized, stage_parquet, compression="zstd", compression_level=9)
        try:  # best-effort durability flush; an RDWR handle is required for fsync on Windows
            fd = os.open(str(stage_parquet), os.O_RDWR)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        physical_sha = hashlib.sha256(stage_parquet.read_bytes()).hexdigest()
        manifest["physicalParquetSha256"] = physical_sha
        manifest["reused"] = False
        (staging / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        # Re-check no concurrent publisher created the target, then atomically move.
        if object_dir.exists():
            shutil.rmtree(staging, ignore_errors=True)
            return publish_object(objects_root, table, object_kind=object_kind, contracts=contracts,
                                  contract_bundle_sha=contract_bundle_sha, provenance_extra=provenance_extra)
        os.replace(staging, object_dir)  # atomic dir publish (target must not exist)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return manifest
