"""Immutable Bronze manifest + checkpoint + columnar source-native inspection. Pure stdlib + pyarrow (used
ONLY as a generic CSV/columnar reader for inspection — never to resolve or open an ASP dataset object)."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from . import BRONZE_MANIFEST_CONTRACT
from .safety import contained_path


def canonical_json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def inspect_csv(path: Path, *, natural_keys: list[str] | None = None, date_col: str | None = None) -> dict:
    """Columnar inspection of a CSV: row/column counts, ordered column names, a schema fingerprint, date
    coverage, and natural-key duplicate count — computed with pyarrow (no row-wise Python loop)."""
    import pyarrow as pa
    import pyarrow.csv as pacsv
    import pyarrow.compute as pc

    try:
        table = pacsv.read_csv(path, read_options=pacsv.ReadOptions(block_size=1 << 24))
    except pa.lib.ArrowInvalid:
        # header-only response (e.g. a Statcast off-day) — no data rows; read the header for column names.
        raw = path.read_bytes().lstrip(b"\xef\xbb\xbf").splitlines()
        header = raw[0].decode("utf-8", "replace") if raw else ""
        cols0 = [c.strip().strip('"') for c in header.split(",")] if header else []
        return {"rowCount": 0, "columnCount": len(cols0), "columnNames": cols0,
                "schemaFingerprint": sha256_bytes(canonical_json_bytes(cols0)), "headerOnly": True}
    cols = list(table.column_names)
    info: dict[str, Any] = {
        "rowCount": int(table.num_rows), "columnCount": len(cols), "columnNames": cols,
        "schemaFingerprint": sha256_bytes(canonical_json_bytes([{"name": f.name, "type": str(f.type)} for f in table.schema])),
    }
    if date_col and date_col in cols:
        col = table.column(date_col)
        try:
            info["minDate"] = str(pc.min(col).as_py())
            info["maxDate"] = str(pc.max(col).as_py())
        except Exception:
            info["minDate"] = info["maxDate"] = None
    if natural_keys and all(k in cols for k in natural_keys) and table.num_rows:
        # duplicate natural keys = rows - distinct(key tuples), all columnar
        key_tbl = table.select(natural_keys)
        combined = None
        for name in natural_keys:
            c = pc.cast(key_tbl.column(name), pa.string())
            combined = c if combined is None else pc.binary_join_element_wise(combined, c, "\x1f")
        distinct = pc.count_distinct(combined).as_py()
        info["naturalKeyDuplicateCount"] = int(table.num_rows) - int(distinct)
        info["naturalKeys"] = list(natural_keys)
    return info


class BronzeManifest:
    """Accumulates immutable per-partition records for one Bronze staging root and writes the canonical
    manifest + its sha256. This is a Bronze acquisition manifest ONLY — not an ASP dataset registration."""

    LABELS = ["QUARANTINED BRONZE SOURCE EVIDENCE", "NOT REGISTERED", "NOT MODEL-ELIGIBLE",
              "NOT FEATURE-ELIGIBLE", "NOT APPROVED FOR TRAINING"]

    def __init__(self, staging_root: Path):
        self.root = Path(staging_root)
        self.path = self.root / "manifests" / "bronze-manifest.json"
        self.partitions: list[dict] = []
        if self.path.is_file():
            prior = json.loads(self.path.read_text(encoding="utf-8"))
            self.partitions = prior.get("partitions", [])

    def _index(self, partition_id: str) -> int:
        for i, p in enumerate(self.partitions):
            if p.get("partitionId") == partition_id:
                return i
        return -1

    def upsert(self, record: dict) -> None:
        record = {**record, "recordedAtUtc": utc_now()}
        i = self._index(record["partitionId"])
        if i >= 0:
            self.partitions[i] = record
        else:
            self.partitions.append(record)

    def has_valid(self, partition_id: str, expected_sha: str | None = None) -> bool:
        i = self._index(partition_id)
        if i < 0:
            return False
        rec = self.partitions[i]
        if rec.get("status") not in ("COMPLETE", "COMPLETE_EMPTY"):
            return False
        rel = rec.get("relativePath")
        if not rel:
            return False
        fp = contained_path(self.root, *Path(rel).parts)
        if not fp.is_file():
            return False
        recorded_sha = rec.get("fileSha256")
        authoritative_sha = expected_sha or recorded_sha
        if not authoritative_sha or recorded_sha != authoritative_sha:
            return False
        digest = hashlib.sha256()
        with fp.open("rb") as source:
            for block in iter(lambda: source.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != authoritative_sha:
            return False
        return True

    def write(self) -> str:
        payload = {
            "manifestContract": BRONZE_MANIFEST_CONTRACT, "manifestVersion": 1,
            "labels": self.LABELS, "registeredInAsp": False, "modelEligible": False,
            "stagingRoot": str(self.root), "updatedAtUtc": utc_now(),
            "partitionCount": len(self.partitions),
            "partitions": sorted(self.partitions, key=lambda p: p.get("partitionId", "")),
        }
        body = canonical_json_bytes(payload)
        sha = sha256_bytes(body)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_bytes(body)
        tmp.replace(self.path)
        (self.path.parent / "bronze-manifest.sha256").write_text(sha + "  bronze-manifest.json\n", encoding="utf-8")
        return sha
