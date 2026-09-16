"""Complete only the missing 2023 team identities for the safe V19 cohort."""
from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_regime_game_sources import load_development_game_context

RAW = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/raw-development.parquet"
RAW_SHA = "d5fdb7bcbe058f34334483a21b14e83129d19c1727d20eddb469c18668ff3b82"
OLD = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/game-context/sha256/90dc14c30b5c0b0279730ce716af13e6d3fd23527c36289c3778e8286ee77c02/game-context.parquet"
OLD_SHA = "1c694e7b8bf185e6fd7366461295290c15a406fb8f527d725e4fbb6d08313adf"
OUTPUT = ROOT / "outputs/mlb-v19-current-state-specialists-v1/game-context/sha256"
FIELDS = ["canonicalGameId", "game_date", "homeTeamId", "awayTeamId", "homeTeamSourceCode", "homeTeamAbbrev",
          "homeTeamRetrosheetCode", "awayTeamSourceCode", "awayTeamAbbrev", "awayTeamRetrosheetCode", "game_id"]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    if sha(RAW) != RAW_SHA or sha(OLD) != OLD_SHA:
        raise ValueError("Physically Development-only source cache checksum differs")
    identities = pd.read_parquet(RAW, columns=["canonicalGameId", "game_date", "game_id"]).drop_duplicates()
    if identities.canonicalGameId.duplicated().any() or not identities.game_date.astype(str).between("2023-03-30", "2026-08-06").all():
        raise ValueError("Safe Development game identity/date differs")
    # Existing final-score diagnostic columns are not materialized or exported.
    existing = pd.read_parquet(OLD, columns=FIELDS)
    missing = identities[~identities.canonicalGameId.isin(existing.canonicalGameId)].copy()
    if len(missing) != 2406 or not missing.game_date.astype(str).str.startswith("2023-").all():
        raise ValueError("Only the previously missing initial 2023 training games may be resolved")
    added, source_evidence = load_development_game_context(missing, score_game_ids=())
    added = added.drop(columns=["actualAway", "actualHome", "scoreAuthority"]).merge(
        missing[["canonicalGameId", "game_id"]], on="canonicalGameId", validate="one_to_one")
    context = pd.concat([existing[FIELDS], added[FIELDS]], ignore_index=True)
    context = context.sort_values(["game_date", "canonicalGameId"], kind="stable").reset_index(drop=True)
    if len(context) != 8976 or context.canonicalGameId.duplicated().any() or context.isna().any().any():
        raise ValueError("Completed all-Development game/team mapping differs")
    if context.homeTeamId.eq(context.awayTeamId).any():
        raise ValueError("Game home/away orientation is invalid")
    check = identities.merge(context, on=["canonicalGameId", "game_date", "game_id"], how="left", validate="one_to_one")
    if check.homeTeamId.isna().any() or len(check) != len(identities):
        raise ValueError("A raw training/validation game lost its exact canonical/source identity")
    evidence = {"schemaVersion": "MLB_V19_ALL_DEVELOPMENT_GAME_CONTEXT_V1",
                "rawDevelopment": {"path": str(RAW), "sha256": RAW_SHA},
                "existingOofContext": {"path": str(OLD), "sha256": OLD_SHA, "games": len(existing)},
                "addedInitialTrainingGames": len(added), "addedSourceEvidence": source_evidence,
                "columnsMaterializedAndExported": FIELDS, "outcomeColumnsExported": [],
                "sourceCalls": 0, "finalOotRowsRead": 0,
                "uses": ["OUTCOME_FREE_CANONICAL_TEAM_MAPPING", "PAST_GAME_ONLY_TEAM_HISTORY_AGGREGATION", "PAIRED_DEPENDENCE_DIAGNOSTICS"],
                "pregameParticipantVintagesEstablished": False}
    buffer = io.BytesIO()
    context.to_parquet(buffer, index=False, compression="zstd")
    payloads = {"game-context.parquet": buffer.getvalue(), "source-evidence.json": canonical_json_bytes(evidence)}
    manifest = {"schemaVersion": "MLB_V19_GAME_CONTEXT_MANIFEST_V1", "games": len(context),
                "addedTrainingGames": len(added), "sourceCalls": 0, "finalOotRowsRead": 0,
                "artifacts": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in payloads.items()}}
    content = canonical_json_bytes(manifest)
    digest = hashlib.sha256(content).hexdigest()
    directory = OUTPUT / digest
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in {**payloads, "manifest.json": content}.items():
        path = directory / name
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("Immutable V19 game mapping conflict")
        else:
            with path.open("xb") as stream:
                stream.write(data)
    pd.testing.assert_frame_equal(pd.read_parquet(directory / "game-context.parquet"), context)
    print(json.dumps({"path": str(directory), "manifestSha256": digest, **manifest}, indent=2))


if __name__ == "__main__":
    main()
