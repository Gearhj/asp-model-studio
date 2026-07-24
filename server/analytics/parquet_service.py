"""Enterprise Analytical Data Plane -- governed Parquet materialization for
registered Dataset Library versions.

Explicit migration behavior only (stop condition #8: do not automatically
convert all CSV files to Parquet). A version's CSV remains the artifact of
record; materialize_parquet_for_version() is called on demand (via the
analytics_queries_router endpoint below, itself invoked from a UI action or a
governed background job -- neither auto-fires on every registration in this
phase) and adds an ADDITIONAL analyticalParquetPath field to the existing
version metadata, never replacing or deleting the CSV, and never touching
datasetId/versionId/schema/target/rowCount/lineage, which remain exactly as
they were.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict

import pyarrow as pa
import pyarrow.csv as pa_csv
import pyarrow.parquet as pa_parquet

from ..datasets.dataset_registry import ARTIFACT_ROOT, load_registry, now_iso, require_dataset, save_registry


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def materialize_parquet_for_version(dataset_id: str, version_id: str) -> Dict[str, Any]:
    """Reads the version's existing data_full.csv via Arrow's streaming CSV reader
    (does not require the whole file to fit in a single pandas DataFrame first),
    writes a sibling data_full.parquet, and records the new path + checksum +
    row/column counts in the version's registry metadata. Idempotent -- calling
    again re-materializes and updates the checksum, it does not error if a
    Parquet file already exists."""
    dataset = require_dataset(dataset_id, write=True)
    version = next((v for v in dataset.get("versions", []) if v.get("versionId") == version_id), None)
    if not version:
        raise ValueError(f"Version not found: {version_id}")

    csv_relative = version.get("fullDataPath")
    if not csv_relative:
        raise ValueError("This version has no CSV artifact to materialize from.")
    csv_path = (ARTIFACT_ROOT / csv_relative).resolve()
    if ARTIFACT_ROOT.resolve() not in csv_path.parents or not csv_path.exists():
        raise ValueError("Source CSV artifact is unavailable or outside the artifact root.")

    parquet_path = csv_path.with_suffix(".parquet")
    table = pa_csv.read_csv(csv_path)
    pa_parquet.write_table(table, parquet_path, compression="snappy")

    checksum = _sha256_of_file(csv_path)
    parquet_relative = str(parquet_path.relative_to(ARTIFACT_ROOT))

    registry = load_registry()
    for entry in registry.get("datasets", []):
        if entry.get("datasetId") != dataset_id:
            continue
        for v in entry.get("versions", []):
            if v.get("versionId") != version_id:
                continue
            v["analyticalParquetPath"] = parquet_relative
            v["analyticalFormat"] = "parquet"
            v["sourceChecksumSha256"] = checksum
            v["parquetRowCount"] = table.num_rows
            v["parquetColumnCount"] = table.num_columns
            v["parquetMaterializedAt"] = now_iso()
        entry["updatedAt"] = now_iso()
    save_registry(registry)

    return {
        "datasetId": dataset_id, "versionId": version_id, "parquetPath": parquet_relative,
        "rowCount": table.num_rows, "columnCount": table.num_columns, "checksum": checksum,
        "sizeBytes": parquet_path.stat().st_size,
    }
