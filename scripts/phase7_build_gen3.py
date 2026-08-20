"""Phase 7 — materialize the Gen-3 2021-2025 PA feature view from the ALREADY-REGISTERED FD1 package.

No download. Constructs the validated FD1 package + identity bridge exactly as the governed registration
scripts do, reuses the frozen partition reader + Gen-3 builder (identical base-feature math to Gen-2),
and writes a content-addressed parquet under the gitignored runtime root. Prints a full reconciliation
(season rows, prior eligibility/blindness). Idempotent: re-running overwrites the same output.

Usage:  .venv/Scripts/python.exe scripts/phase7_build_gen3.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_datasets.access import approved_package_root
from server.sports_datasets.consumer import SportsDatasetManifestConsumer
from server.sports_identity_bridges.consumer import (
    SportsIdentityBridgeV1Consumer,
    approved_bridge_root,
)
from server.sports_modeling.feature_view import _PA_COLUMNS, _PRIOR_COLUMNS, _read_registered_partitions
from server.sports_modeling.feature_view_gen3 import GEN3_TARGET_SEASONS, build_gen3_feature_table

RUNTIME = REPO / ".runtime" / "asp-model-studio" / "sports-modeling"
OUT_DIR = RUNTIME / "mlb-pa-gen3-v1"
OUT_PARQUET = OUT_DIR / "mlb-pa-gen3-feature-view-v1.parquet"
CACHE = RUNTIME / "dataset-validation" / "validation-cache.json"


def _exchange_root() -> Path:
    root = os.getenv("ASP_MODEL_EXCHANGE_ROOT", "").strip()
    if not root:
        env_local = REPO / ".env.local"
        if env_local.is_file():
            for line in env_local.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("ASP_MODEL_EXCHANGE_ROOT"):
                    root = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not root:
        raise SystemExit("ASP_MODEL_EXCHANGE_ROOT is not configured (env or .env.local)")
    return Path(root)


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main() -> int:
    exchange_root = _exchange_root()
    _log("validating FD1 package …")
    parent = SportsDatasetManifestConsumer(
        approved_package_root(exchange_root), cache_path=CACHE, progress=None
    ).validate()
    _log("validating identity bridge …")
    bridge = SportsIdentityBridgeV1Consumer(approved_bridge_root(exchange_root), progress=None).validate()

    pa_partitions = [
        p for p in parent.partitions
        if p.get("family") == "plate_appearance" and p.get("season") in GEN3_TARGET_SEASONS
    ]
    prior_partitions = [
        p for p in parent.partitions
        if p.get("family") == "player_prior"
        and isinstance(p.get("season"), int)
        and int(p["season"]) <= max(GEN3_TARGET_SEASONS) - 1
    ]
    _log(f"reading {len(pa_partitions)} PA partitions + {len(prior_partitions)} prior partitions …")
    pa_tables = _read_registered_partitions(parent, pa_partitions, columns=_PA_COLUMNS)
    prior_tables = _read_registered_partitions(parent, prior_partitions, columns=_PRIOR_COLUMNS)
    prior_table = pa.concat_tables(prior_tables, promote_options="none")

    _log("building Gen-3 feature table (2021-2025) …")
    t0 = time.time()
    table, recon = build_gen3_feature_table(
        pa_tables, prior_table,
        retrosheet_aliases=bridge.retrosheet_aliases,
        dimension_uuids=bridge.dimension_uuids,
        seasons=GEN3_TARGET_SEASONS,
    )
    recon["buildSeconds"] = round(time.time() - t0, 1)
    recon["partitionAuthoritySha"] = parent.partition_authority_sha
    recon["bridgeManifest"] = bridge.manifest.get("bridge_manifest_id")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, OUT_PARQUET, compression="zstd", compression_level=9)
    content_sha = hashlib.sha256(OUT_PARQUET.read_bytes()).hexdigest()
    recon["outputParquet"] = str(OUT_PARQUET.relative_to(REPO))
    recon["outputSha256"] = content_sha
    (OUT_DIR / "gen3-reconciliation.json").write_text(json.dumps(recon, indent=2), encoding="utf-8")

    _log("RECONCILIATION")
    print(json.dumps(recon, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
