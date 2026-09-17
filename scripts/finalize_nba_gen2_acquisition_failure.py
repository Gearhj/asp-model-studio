"""Write the immutable partial NBA Gen2 intake receipt without network I/O."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pandas as pd


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    files = list((root / "raw" / "sha256").glob("*/team_box_2019.parquet"))
    if len(files) != 1:
        raise RuntimeError(f"expected one retained response, found {len(files)}")
    path = files[0]
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if path.parent.name != sha:
        raise RuntimeError("content-address mismatch")
    frame = pd.read_parquet(path)
    schema = [(str(c), str(frame[c].dtype)) for c in frame.columns]
    receipt = {
        "schemaVersion": "NBA_GEN2_TEAM_BOX_ACQUISITION_FAILURE_V1",
        "recordedAtUtc": datetime.now(timezone.utc).isoformat(),
        "status": "STOPPED_FAIL_CLOSED",
        "classification": "CATEGORY_A_RECONSTRUCTED_HISTORICAL_EVIDENCE",
        "provider": "SportsDataverse/hoopR-nba-data",
        "underlyingSource": "ESPN",
        "license": "CC BY 4.0",
        "nbaComRequests": 0,
        "successfulHttpRequests": 1,
        "responseBytes": len(raw),
        "costUsd": 0,
        "request": {
            "asset": "team_box_2019.parquet",
            "seasonLabel": "2018-19",
            "url": "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_nba_team_boxscores/team_box_2019.parquet",
            "httpStatus": 200,
            "responseHeaders": None,
            "responseHeaderQualification": "Original fail-closed path did not persist headers; no duplicate request was made.",
            "retrievedAtUtcApproximation": datetime.fromtimestamp(path.stat().st_ctime, timezone.utc).isoformat(),
            "path": str(path),
            "sha256": sha,
            "bytes": len(raw),
            "rows": int(len(frame)),
            "games": int(frame.game_id.nunique()),
            "schemaFingerprint": hashlib.sha256(encoded(schema)).hexdigest(),
        },
        "integrityObserved": {
            "teamRows": int(len(frame)),
            "distinctGames": int(frame.game_id.nunique()),
            "rowsPerGameCounts": {str(k): int(v) for k, v in frame.groupby("game_id").size().value_counts().items()},
            "homeAwayCounts": {str(k): int(v) for k, v in frame.team_home_away.value_counts().items()},
            "seasonTypeCounts": {str(k): int(v) for k, v in frame.season_type.value_counts().items()},
        },
        "stopReasons": [
            "No explicit minutes or overtime-period field exists in the team-box export.",
            "The initial schema map expected total_rebounds/team_score aliases that were not declared before the request.",
            "Automatic approval review enforced the requested stop-on-schema-instability rule before further requests."
        ],
        "remainingPlan": "Use matching licensed schedule exports to reconcile status_period and derive 240+25*OT team minutes, then continue remaining boxes only after renewed approval.",
    }
    raw_receipt = encoded(receipt)
    physical = hashlib.sha256(raw_receipt).hexdigest()
    target = root / "receipts" / "sha256" / physical / "acquisition-failure.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw_receipt:
        raise RuntimeError("immutable receipt collision")
    target.write_bytes(raw_receipt)
    pointer = {"path": str(target), "sha256": physical, "bytes": len(raw_receipt)}
    (root / "acquisition-failure-current.json").write_bytes(encoded(pointer))
    print(json.dumps(pointer, indent=2))


if __name__ == "__main__":
    main()
