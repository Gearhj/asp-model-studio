"""Separate-process worker for the Phase 7D.5A (Workstream I) Silver publication concurrency battery.

Runnable as ``python -m tests._silver_worker <silver_root> <seed>``: builds a DETERMINISTIC hermetic source from
``seed`` (so the SAME seed yields byte-identical content across processes) and publishes it through the production
Silver publisher. Prints ``OK <manifest_sha>`` or ``ERR <message>``.
"""
from __future__ import annotations

import sys
from pathlib import Path

from server.sports_modeling import silver_publish as SP
from server.sports_modeling.feature_contract import FEATURE_NAMES


def _rows(seed: int):
    rows = []
    for s in (2021, 2022, 2023, 2024):
        for b in ("b1", "b2", "b3"):
            for g in range(2):
                for ab in range(3):
                    r = {"plate_appearance_id": f"pa-{s}-{b}-{g}-{ab}", "game_id": f"{s}-{b}-g{g}",
                         "game_date": f"{s}-04-{1 + g:02d}", "at_bat_number": ab,
                         "batter_canonical_player_uuid": b, "season": s}
                    for i, f in enumerate(FEATURE_NAMES):
                        r[f] = float((s + g + ab + i + seed) % 7) / 10.0     # deterministic in (seed, position)
                    rows.append(r)
    return rows


def main() -> int:
    silver_root = Path(sys.argv[1])
    seed = int(sys.argv[2])
    try:
        entry = SP.publish_silver(
            silver_root=silver_root, source_object_id="concurrency-src", source_receipt_sha="s" * 64,
            source_manifest_sha="m" * 64, source_physical_sha="p" * 64, source_logical_sha="l" * 64,
            source_schema_sha="c" * 64, source_rows=_rows(seed), base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda r: r["season"])
        print("OK " + entry["manifestSha256"], flush=True)
    except Exception as exc:                      # noqa: BLE001 — report any failure to the parent
        print("ERR " + type(exc).__name__ + ": " + str(exc)[:120], flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
