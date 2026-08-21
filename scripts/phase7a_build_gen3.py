"""Phase 7A — build + immutably publish the Gen-3 authority (Gates 1-5).

No download. Rebuilds the Gen-3 feature table from the already-registered FD1 package (now including
legitimate innings 15-16), validates the canonical contracts, and publishes TWO physically-separated
immutable content-addressed objects — a research view (2021-2024) and a sealed 2025 object — plus a
content-addressed row-level quarantine ledger and a registration record. Idempotent + conflict-safe.

Output root (gitignored): .runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v2/
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pyarrow as pa
import pyarrow.compute as pc

from server.sports_datasets.access import approved_package_root
from server.sports_datasets.consumer import SportsDatasetManifestConsumer, canonical_json_bytes, sha256_bytes
from server.sports_identity_bridges.consumer import SportsIdentityBridgeV1Consumer, approved_bridge_root
from server.sports_modeling.feature_view import _PA_COLUMNS, _PRIOR_COLUMNS, _read_registered_partitions
from server.sports_modeling.feature_view_gen3 import GEN3_TARGET_SEASONS, build_gen3_feature_table
from server.sports_modeling import gen3_contracts as C
from server.sports_modeling.gen3_publish import publish_object, Gen3PublishError

AUTHORITY_ROOT = REPO / ".runtime" / "asp-model-studio" / "sports-modeling" / "mlb-pa-gen3-v2"
CACHE = REPO / ".runtime" / "asp-model-studio" / "sports-modeling" / "dataset-validation" / "validation-cache.json"
RESEARCH_SEASONS = [2021, 2022, 2023, 2024]
SEALED_SEASONS = [2025]


def _exchange_root() -> Path:
    import os
    root = os.getenv("ASP_MODEL_EXCHANGE_ROOT", "").strip()
    if not root and (REPO / ".env.local").is_file():
        for line in (REPO / ".env.local").read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ASP_MODEL_EXCHANGE_ROOT"):
                root = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if not root:
        raise SystemExit("ASP_MODEL_EXCHANGE_ROOT not configured")
    return Path(root)


def _log(m: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main() -> int:
    exchange = _exchange_root()
    _log("validating FD1 package + bridge …")
    parent = SportsDatasetManifestConsumer(approved_package_root(exchange), cache_path=CACHE, progress=None).validate()
    bridge = SportsIdentityBridgeV1Consumer(approved_bridge_root(exchange), progress=None).validate()

    pa_partitions = [p for p in parent.partitions if p.get("family") == "plate_appearance" and p.get("season") in GEN3_TARGET_SEASONS]
    prior_partitions = [p for p in parent.partitions if p.get("family") == "player_prior" and isinstance(p.get("season"), int) and int(p["season"]) <= max(GEN3_TARGET_SEASONS) - 1]
    source_partition_ids = sorted(str(p["partition_id"]) for p in [*pa_partitions, *prior_partitions])
    _log(f"reading {len(pa_partitions)} PA + {len(prior_partitions)} prior partitions …")
    pa_tables = _read_registered_partitions(parent, pa_partitions, columns=_PA_COLUMNS)
    prior_tables = _read_registered_partitions(parent, prior_partitions, columns=_PRIOR_COLUMNS)
    prior_table = pa.concat_tables(prior_tables, promote_options="none")

    _log("building Gen-3 feature table (2021-2025, incl. innings 15-16) …")
    table, recon = build_gen3_feature_table(pa_tables, prior_table,
                                            retrosheet_aliases=bridge.retrosheet_aliases,
                                            dimension_uuids=bridge.dimension_uuids, seasons=GEN3_TARGET_SEASONS)

    # Validate contracts before publication.
    contracts = C.all_contracts()
    bundle_sha = C.contract_bundle_sha()
    _log(f"contract bundle sha256={bundle_sha}")

    AUTHORITY_ROOT.mkdir(parents=True, exist_ok=True)
    # Content-addressed quarantine ledger (immutable child).
    ledger = recon["quarantineLedger"]
    ledger_bytes = canonical_json_bytes({"schemaVersion": "MLB_GEN3_QUARANTINE_LEDGER_V1", "records": ledger})
    ledger_sha = sha256_bytes(ledger_bytes)
    ledger_dir = AUTHORITY_ROOT / "objects" / "sha256" / ledger_sha
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "quarantine-ledger.json").write_bytes(ledger_bytes)

    prov = {
        "datasetId": C.PARENT_DATASET_ID,
        "partitionAuthoritySha256": parent.partition_authority_sha,
        "bridgeManifestId": bridge.manifest.get("bridge_manifest_id"),
        "sourcePartitionIds": source_partition_ids,
        "quarantineLedgerSha256": ledger_sha,
        "quarantineCounts": recon["quarantined"],
        "seasonRows": recon["seasonRows"],
    }

    def season_subset(seasons: list[int]) -> pa.Table:
        mask = pc.is_in(table["season"], value_set=pa.array(seasons, pa.int16()))
        return table.filter(mask)

    published = {}
    for kind, seasons in (("research", RESEARCH_SEASONS), ("sealed-2025", SEALED_SEASONS)):
        sub = season_subset(seasons)
        _log(f"publishing {kind} object ({sub.num_rows} rows, seasons {seasons}) …")
        m = publish_object(AUTHORITY_ROOT, sub, object_kind=kind, contracts=contracts,
                           contract_bundle_sha=bundle_sha,
                           provenance_extra={**prov, "seasons": seasons})
        published[kind] = m

    registration = {
        "schemaVersion": "MLB_GEN3_REGISTRATION_V1",
        "registrationId": f"mlb-pa-gen3-research:sha256:{published['research']['logicalContentSha256']}",
        "contractBundleSha256": bundle_sha,
        "contracts": {k: v["id"] for k, v in contracts.items()},
        "research": {"logicalContentSha256": published["research"]["logicalContentSha256"],
                     "physicalParquetSha256": published["research"]["physicalParquetSha256"],
                     "schemaSha256": published["research"]["schemaSha256"],
                     "rows": published["research"]["rowCount"], "seasons": RESEARCH_SEASONS,
                     "seasonRows": {str(s): int(recon["seasonRows"].get(str(s), recon["seasonRows"].get(s, 0))) for s in RESEARCH_SEASONS}},
        "sealed2025": {"logicalContentSha256": published["sealed-2025"]["logicalContentSha256"],
                       "physicalParquetSha256": published["sealed-2025"]["physicalParquetSha256"],
                       "schemaSha256": published["sealed-2025"]["schemaSha256"],
                       "rows": published["sealed-2025"]["rowCount"], "seasons": SEALED_SEASONS,
                       "seasonRows": {str(s): int(recon["seasonRows"].get(str(s), recon["seasonRows"].get(s, 0))) for s in SEALED_SEASONS},
                       "note": "structural registration only; target values not loaded by default development"},
        "perSeasonRows": {str(s): int(v) for s, v in recon["seasonRows"].items()},
        "developmentSeasons": [2021, 2022, 2023], "validationSeason": 2024, "sealedSeasons": [2025],
        "quarantineLedgerSha256": ledger_sha,
        "quarantineTotal": recon["quarantinedTotal"],
        "createdAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (AUTHORITY_ROOT / "registration.json").write_text(json.dumps(registration, indent=2), encoding="utf-8")
    # Explicit registry write (A2-06/Gate 6): registration is a build/admin action, never a UI side effect.
    from server.sports_cockpit import gen3_authority as _G3A
    _G3A.register_gen3()
    _log("REGISTRATION")
    print(json.dumps(registration, indent=2))
    print(json.dumps({"quarantined": recon["quarantined"], "seasonRows": recon["seasonRows"],
                      "ledgerRecords": len(ledger)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Gen3PublishError as exc:
        print(f"PUBLISH ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
