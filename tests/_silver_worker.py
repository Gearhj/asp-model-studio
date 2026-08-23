"""Separate-process worker for the Phase 7D.5A.2 (Repair 5) transactional Silver-registry battery.

``python -m tests._silver_worker <base_dir> <seed>``: publishes a governed source + a Silver object into the SHARED
``<base_dir>/silver`` + ``<base_dir>/src`` roots. With DISTINCT seeds two workers produce two different immutable
objects that must BOTH survive in the one interprocess-locked registry; with the SAME seed they converge idempotently.
Prints ``OK <manifest_sha>`` or ``ERR <message>``.
"""
from __future__ import annotations

import sys
from pathlib import Path

from server.sports_modeling import silver_publish as SP
from server.sports_modeling.feature_contract import FEATURE_NAMES
from tests._silver_fixture import source_rows


def main() -> int:
    base = Path(sys.argv[1])
    seed = int(sys.argv[2])
    src_id = f"mlb-silver-source-seed{seed}"
    try:
        SP.publish_source_object(source_root=base / "src", rows=source_rows(seed=seed), dataset_version_id=src_id,
                                 season_of_row=lambda r: r["season"])
        entry = SP.publish_silver(silver_root=base / "silver", source_root=base / "src",
                                  source_dataset_version_id=src_id, base_feature_ids=list(FEATURE_NAMES),
                                  season_of_row=lambda r: r["season"])
        print("OK " + entry["manifestSha256"], flush=True)
    except Exception as exc:  # noqa: BLE001
        print("ERR " + type(exc).__name__ + ": " + str(exc)[:140], flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
