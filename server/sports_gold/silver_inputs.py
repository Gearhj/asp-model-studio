"""Verified, read-only inputs for the Phase 7B2 Gold V1 experiment.

This module deliberately has no publication or mutation API.  It resolves the
single current registration from the existing Silver logical index, invokes the
existing Silver verifier, and returns the exact immutable children that were
verified.  The only permitted modeling seasons are 2021--2024; Silver history
from 2019--2020 may be read solely to calculate prior-day histories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ..sports_cockpit import gen3_authority as G3
from ..sports_silver import silver_publication as SP


ALLOWED_SILVER_SEASONS = (2019, 2020, 2021, 2022, 2023, 2024)
MODELING_SEASONS = (2021, 2022, 2023, 2024)
FORBIDDEN_SEASONS = (2025, 2026)


class GoldInputError(RuntimeError):
    """A governed input could not be resolved or violated the season boundary."""


@dataclass(frozen=True)
class VerifiedSilverHandle:
    table_name: str
    dataset_version_id: str
    registration_sha256: str
    manifest_sha256: str
    partitioned: bool
    seasons: tuple[int, ...]
    row_count: int
    object_dir: Path
    child_paths: tuple[Path, ...]
    value_digest_sha256: str | None

    def identity(self) -> dict[str, object]:
        return {
            "tableName": self.table_name,
            "datasetVersionId": self.dataset_version_id,
            "registrationSha256": self.registration_sha256,
            "manifestSha256": self.manifest_sha256,
            "partitioned": self.partitioned,
            "rowCount": self.row_count,
            "seasons": list(self.seasons),
            "valueDigestSha256": self.value_digest_sha256,
        }


@dataclass(frozen=True)
class VerifiedGen3Handle:
    dataset_version_id: str
    path: Path
    rows: int
    seasons: tuple[int, ...]
    logical_content_sha256: str
    contract_bundle_sha256: str

    def identity(self) -> dict[str, object]:
        return {
            "datasetVersionId": self.dataset_version_id,
            "rows": self.rows,
            "seasons": list(self.seasons),
            "logicalContentSha256": self.logical_content_sha256,
            "contractBundleSha256": self.contract_bundle_sha256,
        }


def _strict_seasons(values: Iterable[object], *, allowed: Sequence[int]) -> tuple[int, ...]:
    try:
        seasons = tuple(sorted({int(value) for value in values}))
    except (TypeError, ValueError) as exc:
        raise GoldInputError("input seasons are not strict integers") from exc
    if not seasons or any(season not in allowed for season in seasons):
        raise GoldInputError(f"input season boundary violated: {seasons}")
    if any(season in FORBIDDEN_SEASONS for season in seasons):
        raise GoldInputError("2025/2026 input is physically prohibited")
    return seasons


def verified_gen3_research() -> VerifiedGen3Handle:
    """Resolve the canonical, physically separated 2021--2024 target/base object."""

    raw = G3.verified_research_object("GEN3")
    seasons = _strict_seasons(raw.get("seasons") or (), allowed=MODELING_SEASONS)
    if seasons != MODELING_SEASONS:
        raise GoldInputError(f"Gen3 research seasons differ: {seasons}")
    if raw.get("capability") != "RESEARCH_OBJECT_READ" or raw.get("verificationState") != "VERIFIED":
        raise GoldInputError("Gen3 research object is not fully verified")
    path = Path(raw["path"])
    if not path.is_file():
        raise GoldInputError("verified Gen3 research parquet is missing")
    return VerifiedGen3Handle(
        dataset_version_id=str(raw["datasetVersionId"]),
        path=path,
        rows=int(raw["rows"]),
        seasons=seasons,
        logical_content_sha256=str(raw["logicalContentSha256"]),
        contract_bundle_sha256=str(raw["contractBundleSha256"]),
    )


def resolve_current_silver(silver_root: Path, table_name: str) -> VerifiedSilverHandle:
    """Resolve and independently verify exactly one current Silver logical object."""

    root = Path(silver_root)
    logical = SP.logical_index(root)
    if table_name not in logical:
        raise GoldInputError(f"current Silver logical object missing: {table_name}")
    item = logical[table_name]
    current_sha = str(item.get("currentRegistrationSha256", ""))
    current_id = str(item.get("currentDatasetVersionId", ""))
    record = SP._load_registration(root, current_sha)
    if record.get("datasetVersionId") != current_id or record.get("tableName") != table_name:
        raise GoldInputError(f"current Silver registration mismatch: {table_name}")
    if any(record.get(flag) is not expected for flag, expected in (
        ("selectable", False), ("modelEligible", False), ("approvedForTraining", False)
    )) or record.get("quarantine") != "QUARANTINED":
        raise GoldInputError(f"Silver quarantine differs: {table_name}")
    seasons = _strict_seasons(record.get("seasons") or (), allowed=ALLOWED_SILVER_SEASONS)
    manifest_sha = str(record["publicationManifestSha256"])
    partitioned = bool(record.get("partitioned"))
    if partitioned:
        verified = SP.verify_partitioned_silver_table(root, manifest_sha)
        object_dir = SP._partitioned_root(root) / manifest_sha
        manifest = json.loads((object_dir / "manifest.json").read_text(encoding="utf-8"))
        children = tuple(
            object_dir / "children" / f"{child['childSha256']}.parquet"
            for child in manifest["children"]
        )
    else:
        verified = SP.verify_silver_table(root, manifest_sha)
        object_dir = SP._silver_tables_root(root) / manifest_sha
        children = (object_dir / "object.parquet",)
    if verified.get("tableName") != table_name:
        raise GoldInputError(f"verified Silver table identity mismatch: {table_name}")
    return VerifiedSilverHandle(
        table_name=table_name,
        dataset_version_id=current_id,
        registration_sha256=current_sha,
        manifest_sha256=manifest_sha,
        partitioned=partitioned,
        seasons=seasons,
        row_count=int(record["rowCount"]),
        object_dir=object_dir,
        child_paths=children,
        value_digest_sha256=record.get("valueDigestSha256"),
    )


def read_verified_columns(
    handle: VerifiedSilverHandle,
    columns: Sequence[str],
    *,
    seasons: Sequence[int] | None = None,
) -> pa.Table:
    """Read selected columns from an already verified handle with a strict season filter."""

    wanted = tuple(int(value) for value in (seasons or handle.seasons))
    if not wanted or any(value not in ALLOWED_SILVER_SEASONS for value in wanted):
        raise GoldInputError(f"read season boundary violated: {wanted}")
    if any(value in FORBIDDEN_SEASONS for value in wanted):
        raise GoldInputError("2025/2026 rejected before any table open")
    if handle.partitioned:
        dataset = ds.dataset([str(path) for path in handle.child_paths], format="parquet")
        schema_names = set(dataset.schema.names)
        missing = sorted(set(columns) - schema_names)
        if missing:
            raise GoldInputError(f"{handle.table_name} columns missing: {missing}")
        season_type = dataset.schema.field("season").type if "season" in schema_names else None
        if season_type is None:
            if set(wanted) != set(handle.seasons):
                raise GoldInputError(f"{handle.table_name} has no season column for bounded read")
            return dataset.to_table(columns=list(columns))
        values: list[object] = list(wanted) if pa.types.is_integer(season_type) else [str(v) for v in wanted]
        return dataset.to_table(columns=list(columns), filter=ds.field("season").isin(values))
    table = pq.read_table(handle.child_paths[0], columns=list(columns))
    if "season" in table.column_names:
        raw = table["season"].to_pylist()
        mask = pa.array([int(value) in wanted for value in raw], type=pa.bool_())
        table = table.filter(mask)
    elif set(wanted) != set(handle.seasons):
        raise GoldInputError(f"{handle.table_name} has no season column for bounded read")
    return table


__all__ = [
    "ALLOWED_SILVER_SEASONS",
    "FORBIDDEN_SEASONS",
    "GoldInputError",
    "MODELING_SEASONS",
    "VerifiedGen3Handle",
    "VerifiedSilverHandle",
    "read_verified_columns",
    "resolve_current_silver",
    "verified_gen3_research",
]
