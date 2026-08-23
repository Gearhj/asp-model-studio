"""Shared hermetic Silver fixtures (Phase 7D.5A.2). The hermetic tests FIRST publish a synthetic governed source
through the REAL production source publisher (``publish_source_object``), then reference it by its canonical identity
— never by caller-attested SHAs or caller rows."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from server.sports_modeling import silver_publish as SP
from server.sports_modeling.feature_contract import FEATURE_NAMES

SRC_ID = "mlb-silver-source-hermetic-v1"


def source_rows(*, seasons=(2023, 2024), batters=("b1", "b2"), per=3, season_override=None, seed=0):
    """Deterministic, strict-typed-chronology source rows (one game per batter per season, sequential at-bats)."""
    out = []
    for s in seasons:
        for b in batters:
            for ab in range(per):
                r = {"plate_appearance_id": f"pa-{s}-{b}-{ab}", "game_id": f"g-{s}-{b}", "game_date": f"{s}-04-01",
                     "at_bat_number": ab, "batter_canonical_player_uuid": b, "season": s}
                for i, f in enumerate(FEATURE_NAMES):
                    r[f] = float((s + ab + i + seed) % 7) / 10.0
                out.append(r)
    if season_override is not None:
        out[0]["season"] = season_override
    return out


def publish_source(source_root: Path, *, rows=None, dataset_version_id: str = SRC_ID) -> dict[str, Any]:
    return SP.publish_source_object(source_root=source_root, rows=(rows if rows is not None else source_rows()),
                                    dataset_version_id=dataset_version_id, season_of_row=lambda r: r["season"])


def publish_silver_hermetic(base: Path, *, rows=None, dataset_version_id: str = SRC_ID, **kw) -> dict[str, Any]:
    """Publish a synthetic governed source, then a Silver object referencing it by canonical identity."""
    source_root = base / "src"
    silver_root = base / "silver"
    publish_source(source_root, rows=rows, dataset_version_id=dataset_version_id)
    entry = SP.publish_silver(silver_root=silver_root, source_root=source_root,
                              source_dataset_version_id=dataset_version_id, base_feature_ids=list(FEATURE_NAMES),
                              season_of_row=lambda r: r["season"], **kw)
    return {"entry": entry, "silver_root": silver_root, "source_root": source_root,
            "manifest_sha": entry["manifestSha256"], "object_dir": silver_root / "objects" / "sha256" / entry["manifestSha256"]}
