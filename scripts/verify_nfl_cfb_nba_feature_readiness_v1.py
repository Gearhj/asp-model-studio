"""Focused integrity checks for the multisport feature-readiness artifact."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "nfl-cfb-nba-feature-readiness-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    design = json.loads((DOC / "STUDY_DESIGN.json").read_text(encoding="utf-8"))
    assert design["status"] == "FROZEN_BEFORE_NEW_TARGET_ACCESS"
    assert design["calendarCutoffExclusiveUtc"] == "2026-01-01T00:00:00Z"
    bound = json.loads((DOC / "BOUND_INPUT_RECEIPT.json").read_text(encoding="utf-8"))
    for sport in ("NFL", "CFB", "NBA"):
        assert bound["files"][sport]["sha256"] == design["inputs"][sport]["sha256"]
        assert bound["files"][sport]["rows"] == design["inputs"][sport]["rows"]
    results = json.loads((DOC / "EXPERIMENT_RESULTS.json").read_text(encoding="utf-8"))
    assert all(not item["passesFrozenGate"] for sport in results.values() for item in sport["pooledReusedLater"])
    quality = json.loads((DOC / "DATA_QUALITY_SCORECARDS.json").read_text(encoding="utf-8"))
    assert all(quality[s]["duplicateGameIds"] == 0 and quality[s]["missingTargetRows"] == 0 for s in quality)
    assert all(quality[s]["impossibleValueCount"] == 0 for s in quality)
    figures = json.loads((DOC / "FIGURE_INDEX.json").read_text(encoding="utf-8"))["figures"]
    assert len(figures) == 30 and all((ROOT / p).is_file() for p in figures)
    activity = json.loads((DOC / "EXTERNAL_ACTIVITY.json").read_text(encoding="utf-8"))
    assert all(activity[k] == 0 for k in ("networkRequests", "providerRequests", "sportsbookRequests", "aispWrites", "exchangeWrites", "productionOwnerChanges", "sealedOrFinalOotReads"))
    index = json.loads((DOC / "artifact-index.json").read_text(encoding="utf-8"))
    for item in index["files"]:
        path = ROOT / item["path"]
        assert path.stat().st_size == item["bytes"]
        assert sha(path) == item["sha256"]
    print(json.dumps({"status": "verified", "boundSports": 3, "figures": len(figures), "indexedFiles": len(index["files"]), "passingBlocks": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
