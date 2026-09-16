"""Deterministically verify an NFL Week 2 eligibility batch and packages."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_nfl_m1.week2_paper_eligibility import (
    BATCH_SCHEMA,
    canonical_json_bytes,
    physical,
    verify_package,
)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("batch_receipt", type=Path)
    args = parser.parse_args()
    raw = args.batch_receipt.read_bytes()
    batch = json.loads(raw)
    if raw != canonical_json_bytes(batch):
        raise SystemExit("batch receipt is not canonical UTF-8 JSON")
    if batch.get("schemaVersion") != BATCH_SCHEMA or batch.get("gameCount") != 16:
        raise SystemExit("batch scope differs")
    addresses = []
    for row in batch["packages"]:
        verified = verify_package(Path(row["exchangeDirectory"]))
        if verified["address"] != row["supplementAddress"]:
            raise SystemExit("package row address differs")
        if verified["manifest"] != row["manifest"] or verified["supplement"] != row["supplement"]:
            raise SystemExit("package row physical binding differs")
        addresses.append(verified["address"])
    if len(addresses) != 16 or len(set(addresses)) != 16:
        raise SystemExit("package cardinality differs")
    print(json.dumps({
        "status": "VERIFIED",
        "batch": physical(args.batch_receipt),
        "batchSha256": hashlib.sha256(raw).hexdigest(),
        "gameCount": 16,
        "supplementAddresses": addresses,
    }, indent=2))
