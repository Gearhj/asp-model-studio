"""Materialize the study's safe game/team lookup and twenty score diagnostics."""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_regime_game_sources import load_development_game_context


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def main() -> None:
    source = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache/matched-oof.parquet"
    oof = pd.read_parquet(source, columns=["canonicalPaId", "canonicalGameId", "game_id", "game_date", "foldNumber"])
    if len(oof) != 494432 or oof.canonicalPaId.duplicated().any():
        raise RuntimeError("reproduced common OOF inventory differs")
    selected = oof.loc[oof.foldNumber.eq(5), ["canonicalGameId", "game_date"]].drop_duplicates().sort_values(
        ["game_date", "canonicalGameId"], kind="stable"
    ).head(20)
    context, evidence = load_development_game_context(oof, score_game_ids=selected.canonicalGameId.tolist())
    game_ids = oof[["canonicalGameId", "game_id"]].drop_duplicates()
    context = context.merge(game_ids, on="canonicalGameId", how="left", validate="one_to_one")
    context = context.sort_values(["game_date", "canonicalGameId"], kind="stable").reset_index(drop=True)
    evidence.update({
        "matchedOofSource": str(source), "matchedOofSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "matchedOofRows": len(oof), "selectedScoreGames": selected.canonicalGameId.tolist(),
        "selectedScoreGamePolicy": "FIRST_20_FOLD5_DATE_CANONICAL_ID_WITHOUT_OUTCOMES",
        "gamesBySeason": {str(key): int(value) for key, value in context.groupby(context.game_date.str[:4]).size().items()},
        "distinctCanonicalTeams": len(set(context.homeTeamId) | set(context.awayTeamId)),
        "teamIdsUsedAsPredictors": False, "purpose": "DEPENDENCE_BLOCKS_AND_EVALUATION_ONLY",
    })
    buffer = io.BytesIO()
    context.to_parquet(buffer, index=False, compression="zstd")
    payloads = {"game-context.parquet": buffer.getvalue(), "source-evidence.json": canonical(evidence)}
    manifest = {"schemaVersion": "MLB_REGIME_GAME_CONTEXT_MANIFEST_V1", "games": len(context),
                "scoreDiagnosticGames": evidence["scoreDiagnosticGames"], "finalOotRowsRead": 0,
                "artifacts": {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
                              for name, data in payloads.items()}}
    manifest_bytes = canonical(manifest)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    directory = ROOT / "outputs/mlb-regime-hybrid-ensemble-v1/game-context/sha256" / digest
    directory.mkdir(parents=True, exist_ok=True)
    for name, data in {**payloads, "manifest.json": manifest_bytes}.items():
        target = directory / name
        if target.exists():
            if target.read_bytes() != data:
                raise RuntimeError(f"immutable game-context artifact differs: {name}")
        else:
            target.write_bytes(data)
    restored = pd.read_parquet(directory / "game-context.parquet")
    pd.testing.assert_frame_equal(restored, context)
    print(json.dumps({"path": str(directory), "manifestSha256": digest,
                      "games": len(context), "scoreDiagnosticGames": evidence["scoreDiagnosticGames"],
                      "distinctCanonicalTeams": evidence["distinctCanonicalTeams"],
                      "gamesBySeason": evidence["gamesBySeason"], "artifacts": manifest["artifacts"]}, indent=2))


if __name__ == "__main__":
    main()
