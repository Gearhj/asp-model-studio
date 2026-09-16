"""Phase 7C Gate 1 — physically separate the Gen-2 research frame from the sealed 2025 season.

The legacy Gen-2 path loaded ONE combined 2023-2025 object (`mlb-pa-feature-view-v1.parquet`) and sliced it
in memory, so ordinary scientist routes physically opened the sealed 2025 rows. This publisher reads that
combined object ONCE under an explicit administrative build authority and emits TWO physically-separated,
immutable, content-addressed objects under Gen-2 contracts:

    A. MLB_GEN2_RESEARCH_2023_2024   (2023 development + 2024 validation; NO 2025)
    B. MLB_GEN2_SEALED_2025          (2025 only; restricted, non-selectable)

It NEVER fits a model, scores, predicts, computes metrics, or exposes target values. The one administrative
read of the sealed 2025 rows is recorded in an immutable migration-audit record. The old combined object is
retained as archived lineage and removed from every ordinary catalog resolver (see gen3_authority.catalog).

Output root (gitignored): .runtime/asp-model-studio/sports-modeling/mlb-pa-gen2-v1/
Idempotent + conflict-safe (publish_object reuses an identical object and rejects divergent conflict).
"""
from __future__ import annotations

import glob
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling import gen3_contracts as C
from server.sports_modeling.gen3_publish import publish_object, Gen3PublishError

RUNTIME = REPO / ".runtime" / "asp-model-studio"
AUTHORITY_ROOT = RUNTIME / "sports-modeling" / "mlb-pa-gen2-v1"
COMBINED_GLOB = str(RUNTIME / "sports-modeling" / "mlb-pa-v1" / "objects" / "sha256" / "**"
                    / "mlb-pa-feature-view-v1.parquet")
RESEARCH_SEASONS = [2023, 2024]
SEALED_SEASONS = [2025]


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def _resolve_combined() -> Path:
    matches = sorted(glob.glob(COMBINED_GLOB, recursive=True))
    if not matches:
        raise SystemExit("combined Gen-2 feature view not materialized; cannot publish Gen-2 objects")
    return Path(matches[0])


def main() -> int:
    from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)
    retire_2025()   # one-time migration reads sealed-2025 rows to split; separation already done -> exit
    combined = _resolve_combined()
    combined_physical = hashlib.sha256(combined.read_bytes()).hexdigest()
    _log(f"administrative source read: {combined.name} (physical sha256={combined_physical[:16]}…)")

    # ADMINISTRATIVE build authority: this is the single sanctioned read of the combined object, including
    # its sealed 2025 rows. No model is fit; no score/prediction/metric is computed; no target is exposed.
    table = pq.read_table(combined)
    seasons_present = sorted(set(int(s) for s in table["season"].to_pylist()))
    _log(f"combined object rows={table.num_rows} seasons={seasons_present}")

    contracts = C.gen2_contracts()
    bundle_sha = C.contract_bundle_sha_for("GEN2")
    _log(f"Gen-2 contract bundle sha256={bundle_sha}")

    AUTHORITY_ROOT.mkdir(parents=True, exist_ok=True)

    def subset(seasons: list[int]) -> pa.Table:
        mask = pc.is_in(table["season"], value_set=pa.array(seasons, table.schema.field("season").type))
        return table.filter(mask)

    prov_common = {
        "datasetId": C.PARENT_DATASET_ID,
        "sourceObject": "mlb-pa-feature-view-v1.parquet",
        "sourcePhysicalSha256": combined_physical,
        "administrativeBuildAuthority": "phase7c_publish_gen2",
    }

    published = {}
    season_rows = {}
    for kind, seasons in (("gen2-research", RESEARCH_SEASONS), ("gen2-sealed-2025", SEALED_SEASONS)):
        sub = subset(seasons)
        season_rows[kind] = {int(s): int(pc.sum(pc.cast(pc.equal(sub["season"], s), pa.int64())).as_py() or 0) for s in seasons}
        _log(f"publishing {kind}: {sub.num_rows} rows, seasons {seasons} …")
        m = publish_object(AUTHORITY_ROOT, sub, object_kind=kind, contracts=contracts,
                           contract_bundle_sha=bundle_sha,
                           provenance_extra={**prov_common, "seasons": seasons})
        published[kind] = m

    # Per-season registered row counts (registered receipts — never fabricated by equal division).
    per_season_counts = {int(s): int(pc.sum(pc.cast(pc.equal(table["season"], s), pa.int64())).as_py() or 0)
                         for s in seasons_present}

    registration = {
        "schemaVersion": "MLB_GEN2_REGISTRATION_V1",
        "registrationId": f"mlb-pa-gen2-research:sha256:{published['gen2-research']['logicalContentSha256']}",
        "generation": "GEN2",
        "contractBundleSha256": bundle_sha,
        "contracts": {k: v["id"] for k, v in contracts.items()},
        "research": {
            "logicalContentSha256": published["gen2-research"]["logicalContentSha256"],
            "physicalParquetSha256": published["gen2-research"]["physicalParquetSha256"],
            "schemaSha256": published["gen2-research"]["schemaSha256"],
            "rows": published["gen2-research"]["rowCount"], "seasons": RESEARCH_SEASONS,
            "seasonRows": season_rows["gen2-research"],
        },
        "sealed2025": {
            "logicalContentSha256": published["gen2-sealed-2025"]["logicalContentSha256"],
            "physicalParquetSha256": published["gen2-sealed-2025"]["physicalParquetSha256"],
            "schemaSha256": published["gen2-sealed-2025"]["schemaSha256"],
            "rows": published["gen2-sealed-2025"]["rowCount"], "seasons": SEALED_SEASONS,
            "note": "structural registration only; target values not loaded by ordinary development",
        },
        "perSeasonRows": per_season_counts,
        "developmentSeasons": [2023], "validationSeason": 2024, "sealedSeasons": [2025],
        "sourceLineage": {"combinedObject": str(combined), "combinedPhysicalSha256": combined_physical,
                          "status": "ARCHIVED_LINEAGE — retained immutable; removed from ordinary resolvers"},
        "createdAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (AUTHORITY_ROOT / "registration.json").write_text(json.dumps(registration, indent=2), encoding="utf-8")

    # Immutable migration-audit record of the administrative sealed access.
    audit = {
        "schemaVersion": "MLB_GEN2_SEAL_MIGRATION_AUDIT_V1",
        "action": "PHYSICAL_SEPARATION_OF_GEN2_RESEARCH_FROM_SEALED_2025",
        "administrativeBuildAuthority": "scripts/phase7c_publish_gen2.py",
        "sourceCombinedObject": str(combined),
        "sourceCombinedPhysicalSha256": combined_physical,
        "sealedSeasonsAdministrativelyRead": SEALED_SEASONS,
        "modelFit": False, "scored": False, "predictionsComputed": False, "metricsComputed": False,
        "targetValuesExposed": False,
        "researchObject": published["gen2-research"]["logicalContentSha256"],
        "sealedObject": published["gen2-sealed-2025"]["logicalContentSha256"],
        "createdAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    audit_bytes = canonical_json_bytes(audit)
    audit_sha = sha256_bytes(audit_bytes)
    audit_dir = AUTHORITY_ROOT / "objects" / "sha256" / audit_sha
    audit_dir.mkdir(parents=True, exist_ok=True)
    (audit_dir / "seal-migration-audit.json").write_bytes(audit_bytes)
    registration["sealMigrationAuditSha256"] = audit_sha
    (AUTHORITY_ROOT / "registration.json").write_text(json.dumps(registration, indent=2), encoding="utf-8")

    _log("GEN2 REGISTRATION")
    print(json.dumps(registration, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Gen3PublishError as exc:
        print(f"PUBLISH ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
