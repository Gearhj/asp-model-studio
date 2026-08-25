"""Governed Bronze source authority (Phase 7B1).

Bronze is IMMUTABLE source evidence: this module never writes, moves, repairs, or downloads Bronze. It verifies the
governed manifest, inventories partitions read-only, and produces before/after immutability evidence so normalization
can be proven not to have mutated a single Bronze byte.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes

BRONZE_MANIFEST_CONTRACT = "MLB_ADVANCED_BRONZE_SOURCE_MANIFEST_V1"
EXPECTED_BRONZE_MANIFEST_SHA256 = "fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a"
DEFAULT_BRONZE_ROOT = Path(r"C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1")

# Expected governed coverage (the manifest + actual source are controlling; a disagreement is fail-closed, never a
# silent expectation update).
EXPECTED_COVERAGE = {
    "statcast": {"partitions": 2196, "rows": 3929155, "seasons": [2019, 2020, 2021, 2022, 2023, 2024]},
    "chadwick": {"partitions": 16, "rows": 518743},
    "retrosheet": {"partitions": 12},
}
_ALLOWED_SEASONS = (2019, 2020, 2021, 2022, 2023, 2024)
_SEALED_SEASONS = (2025, 2026)


class BronzeAuthorityError(RuntimeError):
    """The governed Bronze authority could not be verified (fail-closed)."""


@dataclass(frozen=True)
class BronzePartition:
    partition_id: str
    source: str
    year: int | None
    relative_path: str
    row_count: int | None
    file_sha256: str | None
    status: str
    natural_keys: Any
    column_names: Sequence[str]

    def absolute_path(self, root: Path) -> Path:
        return (Path(root) / self.relative_path).resolve()


def _manifest_path(root: Path) -> Path:
    return Path(root) / "manifests" / "bronze-manifest.json"


def verify_bronze_manifest(root: Path = DEFAULT_BRONZE_ROOT) -> dict[str, Any]:
    """Verify the governed Bronze manifest BEFORE any row is opened: it exists, its complete file bytes hash to the
    expected content address, its contract is the governed contract, and it is not model-eligible / not registered.
    Returns the parsed manifest. Fail-closed on any disagreement (never a silent expectation update)."""
    root = Path(root)
    if not root.is_dir():
        raise BronzeAuthorityError(f"Bronze root does not exist: {root}")
    mp = _manifest_path(root)
    if not mp.is_file():
        raise BronzeAuthorityError(f"Bronze manifest is missing: {mp}")
    raw = mp.read_bytes()
    actual_sha = sha256_bytes(raw)
    if actual_sha != EXPECTED_BRONZE_MANIFEST_SHA256:
        raise BronzeAuthorityError(
            f"Bronze manifest SHA-256 mismatch: expected {EXPECTED_BRONZE_MANIFEST_SHA256}, got {actual_sha}")
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("manifestContract") != BRONZE_MANIFEST_CONTRACT:
        raise BronzeAuthorityError(f"Bronze manifest contract is not {BRONZE_MANIFEST_CONTRACT}")
    if manifest.get("modelEligible") is True or manifest.get("registeredInAsp") is True:
        raise BronzeAuthorityError("Bronze manifest must remain NOT model-eligible / NOT registered")
    return manifest


def partitions(manifest: Mapping[str, Any], *, source: str | None = None) -> list[BronzePartition]:
    """Return the governed Bronze partitions (optionally for one source), as immutable records."""
    out: list[BronzePartition] = []
    for p in manifest.get("partitions", []):
        if source is not None and p.get("source") != source:
            continue
        out.append(BronzePartition(
            partition_id=str(p.get("partitionId")), source=str(p.get("source")),
            year=(int(p["year"]) if p.get("year") is not None else None),
            relative_path=str(p.get("relativePath")), row_count=p.get("rowCount"),
            file_sha256=p.get("fileSha256"), status=str(p.get("status")),
            natural_keys=p.get("naturalKeys"), column_names=tuple(p.get("columnNames") or ())))
    return out


def assert_expected_coverage(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Confirm the ACTUAL governed coverage equals the expected governed coverage. Fail-closed on any disagreement:
    partition counts, Statcast pitch total + per-season, Chadwick rows, and that only seasons 2019-2024 are present
    (no sealed 2025 / 2026). Returns the observed coverage summary."""
    parts = partitions(manifest)
    by_source: dict[str, list[BronzePartition]] = {}
    for p in parts:
        by_source.setdefault(p.source, []).append(p)

    observed: dict[str, Any] = {}
    # statcast
    sc = by_source.get("statcast", [])
    sc_rows = sum(int(p.row_count or 0) for p in sc)
    sc_seasons = sorted({p.year for p in sc if p.year is not None})
    sc_by_year = {}
    for p in sc:
        sc_by_year[str(p.year)] = sc_by_year.get(str(p.year), 0) + int(p.row_count or 0)
    observed["statcast"] = {"partitions": len(sc), "rows": sc_rows, "seasons": sc_seasons, "rowsByYear": sc_by_year}
    if len(sc) != EXPECTED_COVERAGE["statcast"]["partitions"]:
        raise BronzeAuthorityError(f"Statcast partition count {len(sc)} != {EXPECTED_COVERAGE['statcast']['partitions']}")
    if sc_rows != EXPECTED_COVERAGE["statcast"]["rows"]:
        raise BronzeAuthorityError(f"Statcast pitch total {sc_rows} != {EXPECTED_COVERAGE['statcast']['rows']}")
    if sc_seasons != EXPECTED_COVERAGE["statcast"]["seasons"]:
        raise BronzeAuthorityError(f"Statcast seasons {sc_seasons} != {EXPECTED_COVERAGE['statcast']['seasons']}")

    # chadwick
    cw = by_source.get("chadwick", [])
    cw_rows = sum(int(p.row_count or 0) for p in cw)
    observed["chadwick"] = {"partitions": len(cw), "rows": cw_rows}
    if len(cw) != EXPECTED_COVERAGE["chadwick"]["partitions"]:
        raise BronzeAuthorityError(f"Chadwick partition count {len(cw)} != {EXPECTED_COVERAGE['chadwick']['partitions']}")
    if cw_rows != EXPECTED_COVERAGE["chadwick"]["rows"]:
        raise BronzeAuthorityError(f"Chadwick rows {cw_rows} != {EXPECTED_COVERAGE['chadwick']['rows']}")

    # retrosheet
    rs = by_source.get("retrosheet", [])
    observed["retrosheet"] = {"partitions": len(rs)}
    if len(rs) != EXPECTED_COVERAGE["retrosheet"]["partitions"]:
        raise BronzeAuthorityError(f"Retrosheet partition count {len(rs)} != {EXPECTED_COVERAGE['retrosheet']['partitions']}")

    # season seal: no partition may carry a sealed season
    for p in parts:
        if p.year is not None and int(p.year) in _SEALED_SEASONS:
            raise BronzeAuthorityError(f"SEAL VIOLATION: Bronze partition {p.partition_id} carries sealed season {p.year}")
        if p.year is not None and int(p.year) not in _ALLOWED_SEASONS:
            raise BronzeAuthorityError(f"Bronze partition {p.partition_id} carries out-of-scope season {p.year}")

    observed["lahmanStatus"] = sorted({p.status for p in by_source.get("lahman", [])})
    return observed


def inventory(manifest: Mapping[str, Any], root: Path) -> dict[str, Any]:
    """Read-only content-integrity inventory over the actual Bronze files, computed from the manifest's per-partition
    ``fileSha256`` (path length / size / declared sha only — a deterministic identity that proves before==after)."""
    root = Path(root)
    files: list[dict[str, Any]] = []
    for p in partitions(manifest):
        if not p.relative_path or p.relative_path == "None" or p.status == "FAILED":
            continue                                    # non-landed (e.g. deferred Lahman) — no file to inventory
        ap = p.absolute_path(root)
        files.append({"partitionId": p.partition_id, "source": p.source, "relativePath": p.relative_path,
                      "declaredSha256": p.file_sha256, "exists": ap.is_file(),
                      "sizeBytes": (ap.stat().st_size if ap.is_file() else None)})
    digest = sha256_bytes(canonical_json_bytes(
        [[f["relativePath"], f["declaredSha256"], f["sizeBytes"], f["exists"]] for f in files]))
    return {"schemaVersion": "PHASE_7B1_BRONZE_INVENTORY_V1", "root": str(root), "fileCount": len(files),
            "inventoryDigest": digest, "files": files}


def read_partition_frame(partition: BronzePartition, root: Path):
    """Read ONE Bronze partition read-only into an Arrow table (never modifies Bronze). CSV partitions are read with
    pyarrow; the caller is responsible for streaming/batching at the corpus level."""
    import pyarrow.csv as pacsv
    ap = partition.absolute_path(root)
    if not ap.is_file():
        raise BronzeAuthorityError(f"Bronze partition file missing: {ap}")
    return pacsv.read_csv(str(ap))


def iter_source_frames(manifest: Mapping[str, Any], root: Path, source: str,
                       *, only_nonempty: bool = True, partition_filter=None) -> Iterator[tuple[BronzePartition, Any]]:
    """Stream (partition, arrow_table) for a source in deterministic partition order, one partition at a time (bounded
    memory). ``partition_filter`` (callable(BronzePartition)->bool) is applied to the partition METADATA BEFORE the file
    is opened, so a bounded slice never reads partitions it will discard. Empty Statcast off-day partitions
    (status COMPLETE_EMPTY) are skipped when ``only_nonempty``."""
    for p in sorted(partitions(manifest, source=source), key=lambda x: x.relative_path):
        if only_nonempty and (p.status == "COMPLETE_EMPTY" or (p.row_count is not None and int(p.row_count) == 0)):
            continue
        if p.status not in ("COMPLETE", "COMPLETE_EMPTY"):
            continue
        if partition_filter is not None and not partition_filter(p):
            continue
        yield p, read_partition_frame(p, root)
