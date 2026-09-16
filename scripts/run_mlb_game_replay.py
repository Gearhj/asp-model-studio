"""run-mlb-game-replay — Phase 5 deterministic historical MLB game-replay engine.

Consumes only the governed FD1 ``play_transition`` ledger and reconstructs game state
through deterministic base-out / half-inning / scoring rules, validating the engine's
tracked state against the source at every play. Runs a diverse 75-game sample first
(25 x 2023/2024/2025, including extra-inning, high/low-scoring, walk-off, and
multi-reliever games), and expands to the full 2023-2025 population only if the sample is
structurally sound. Persists a content-addressed replay summary in ignored runtime storage.

Mechanical only: no probabilistic simulation, no Monte Carlo, no win/run-line/total
probabilities, no betting edge, no provider/network calls, no new data acquisition.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import pyarrow.parquet as pq  # noqa: E402

from server.sports_phase5 import game_replay as gr  # noqa: E402

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
OUTPUT_ROOT = RUNTIME_ROOT / "sports-phase5" / "game-replay"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_GAME_REPLAY_ENGINE_V1.md"
DEFAULT_EXCHANGE_ROOT = Path(r"C:/Users/james/asp-model-exchange")
DATASET_MANIFEST_SHA = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
PRIMARY_SEASONS = (2023, 2024, 2025)
SAMPLE_PER_SEASON = 25
_COLS = [
    "game_id", "season", "play_number", "plate_appearance_id", "inning", "top_bottom",
    "outs_before", "base_mask_before", "outs_after", "base_mask_after",
    "visiting_score_before", "home_score_before", "visiting_score_after", "home_score_after",
    "runs_scored", "batter_id", "pitcher_id", "pa_outcome", "event_text",
    "regulation_innings", "pbp_quality", "automatic_runner_placement_before", "automatic_runner_base",
]
_STARTED = time.monotonic()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hb(stage: str, evidence: Mapping[str, Any]) -> None:
    print(f"[replay] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
          + " ".join(f"{k}={v}" for k, v in evidence.items()), flush=True)


def _dataset_authority() -> dict[str, Any]:
    from server.persistence.db import Database
    from server.sports_datasets.registry import SportsDatasetRegistry
    db = Database(RUNTIME_ROOT / "persistence" / "asp_model_studio.db")
    db.initialize()
    active = SportsDatasetRegistry(db).get_active()
    if not active or active["manifest_sha"] != DATASET_MANIFEST_SHA:
        raise RuntimeError("active FD1 dataset registration authority mismatch")
    return {"registrationId": active["registration_id"], "datasetId": active["dataset_id"], "manifestSha": active["manifest_sha"]}


def _load_play_transition(exchange_root: Path):
    import pandas as pd
    base = exchange_root / "datasets" / "mlb-fd1" / f"sha256-{DATASET_MANIFEST_SHA}" / "parquet" / "play_transition"
    files = glob.glob(str(base / "**" / "*.parquet"), recursive=True)
    if not files:
        raise RuntimeError("FD1 play_transition family not found")
    df = pd.concat([pq.read_table(f, columns=_COLS).to_pandas() for f in files], ignore_index=True)
    return df[df["season"].isin(PRIMARY_SEASONS)].copy()


def _game_events(df, game_id: str) -> list[gr.ReplayEvent]:
    rows = df[df["game_id"] == game_id].sort_values("play_number")
    return [gr.event_from_row(r) for r in rows.to_dict("records")]


def _diverse_sample(df) -> list[str]:
    """Deterministic diverse per-season sample: extra-inning, high/low-scoring, walk-off,
    multi-reliever, and evenly-strided ordinary games. No cherry-picking of easy games."""

    import pandas as pd
    game_meta = df.sort_values("play_number").groupby("game_id").agg(
        season=("season", "first"),
        plays=("play_number", "size"),
        max_inning=("inning", "max"),
        final_away=("visiting_score_after", "last"),
        final_home=("home_score_after", "last"),
        last_top=("top_bottom", "last"),
        pitchers=("pitcher_id", "nunique"),
    ).reset_index()
    game_meta["total_runs"] = game_meta["final_away"] + game_meta["final_home"]
    game_meta["walkoff"] = (game_meta["last_top"] == 0) & (game_meta["final_home"] > game_meta["final_away"]) & (game_meta["max_inning"] >= game_meta["max_inning"])
    selected: list[str] = []
    for season in PRIMARY_SEASONS:
        pool = game_meta[game_meta["season"] == season].sort_values("game_id").reset_index(drop=True)
        picks: list[str] = []
        # 5 extra-inning, 4 high-scoring, 4 low-scoring, 4 walk-off, 3 multi-reliever, rest strided
        def take(frame, n):
            ids = [g for g in frame["game_id"].tolist() if g not in picks][:n]
            picks.extend(ids)
        take(pool[pool["max_inning"] > 9].sort_values("max_inning", ascending=False), 5)
        take(pool.sort_values("total_runs", ascending=False), 4)
        take(pool.sort_values("total_runs", ascending=True), 4)
        take(pool[(pool["last_top"] == 0) & (pool["final_home"] > pool["final_away"])].sort_values("game_id"), 4)
        take(pool.sort_values("pitchers", ascending=False), 3)
        # even stride across remaining ordinary games for coverage
        remaining = [g for g in pool["game_id"].tolist() if g not in picks]
        if remaining:
            stride = max(1, len(remaining) // max(1, SAMPLE_PER_SEASON - len(picks)))
            take(pd.DataFrame({"game_id": remaining[::stride]}), SAMPLE_PER_SEASON - len(picks))
        selected.extend(picks[:SAMPLE_PER_SEASON])
    return selected


def _forensics(results: list[gr.GameReplayResult]) -> list[dict[str, Any]]:
    from collections import Counter
    causes: Counter[tuple[str, str | None]] = Counter()
    for r in results:
        for m in r.mismatches:
            causes[(m.category, m.pa_outcome)] += 1
    return [{"category": cat, "paOutcome": outcome, "count": n}
            for (cat, outcome), n in causes.most_common(20)]


def _run(args: argparse.Namespace) -> int:
    exchange_root = Path(args.exchange_root or os.getenv("ASP_MODEL_EXCHANGE_ROOT", "") or DEFAULT_EXCHANGE_ROOT)
    if not exchange_root.exists():
        print(f"exchange root not found: {exchange_root}", file=sys.stderr)
        return 2
    dataset_authority = _dataset_authority()
    code_revision = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip() or "worktree:phase5-game-replay"
    contract_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() if CONTRACT_PATH.exists() else ""
    run_id = "game-replay-" + _sha({"contract": gr.REPLAY_CONTRACT_NAME, "contractSha": contract_sha,
                                    "manifest": DATASET_MANIFEST_SHA, "code": code_revision, "full": args.full})[:16]
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    completed = OUTPUT_ROOT / f"{run_id}.replay.json"
    if args.status:
        print(json.dumps({"runId": run_id, "completed": completed.exists()}))
        return 0
    if completed.exists() and not args.force:
        _hb("REUSED_COMPLETED_REPLAY", {"runId": run_id})
        print("COMPLETED (reused)")
        return 0

    _hb("LOADING_PLAY_TRANSITION", {})
    df = _load_play_transition(exchange_root)
    _hb("LOADED", {"plays": len(df), "games": int(df["game_id"].nunique())})

    sample_ids = _diverse_sample(df)
    _hb("SAMPLE_SELECTED", {"games": len(sample_ids)})
    sample_results = [gr.replay_game(_game_events(df, gid)) for gid in sample_ids]
    sample_metrics = gr.aggregate(sample_results)
    _hb("SAMPLE_REPLAYED", {"exactRate": round(sample_metrics["exactReplayRate"], 4),
                            "finalScoreExact": round(sample_metrics["finalScoreExactRate"], 4),
                            "mismatches": sample_metrics["totalMismatches"]})

    sample_sound = (sample_metrics["finalScoreExactRate"] >= 0.98 and sample_metrics["zeroContinuityRate"] >= 0.98)
    full_metrics = None
    full_results: list[gr.GameReplayResult] = []
    if args.full and sample_sound:
        all_ids = sorted(df["game_id"].unique().tolist())
        _hb("FULL_REPLAY_STARTED", {"games": len(all_ids)})
        # group once for speed
        grouped = {gid: [gr.event_from_row(r) for r in grp.sort_values("play_number").to_dict("records")]
                   for gid, grp in df.groupby("game_id")}
        last = time.monotonic()
        for i, gid in enumerate(all_ids, 1):
            full_results.append(gr.replay_game(grouped[gid]))
            if time.monotonic() - last >= 30.0:
                _hb("FULL_REPLAY_PROGRESS", {"done": i, "total": len(all_ids)})
                last = time.monotonic()
        full_metrics = gr.aggregate(full_results)
        _hb("FULL_REPLAYED", {"exactRate": round(full_metrics["exactReplayRate"], 4),
                              "finalScoreExact": round(full_metrics["finalScoreExactRate"], 4)})

    reference = full_metrics or sample_metrics
    readiness = _readiness(reference, sample_sound)
    forensic_results = full_results or sample_results
    payload = {
        "schemaVersion": gr.REPLAY_SCHEMA_VERSION,
        "contractName": gr.REPLAY_CONTRACT_NAME,
        "replayRunId": run_id,
        "contractSha": contract_sha,
        "datasetAuthority": dataset_authority,
        "sourceFamily": "play_transition",
        "sourceSchemas": {"play_transition": _COLS},
        "seasons": list(PRIMARY_SEASONS),
        "researchOnly": True,
        "probabilisticSimulation": False,
        "sample": {"gameIds": sample_ids, "sound": sample_sound, "metrics": sample_metrics},
        "full": {"executed": full_metrics is not None, "metrics": full_metrics},
        "mismatchForensics": _forensics(forensic_results),
        "sampleGameResults": [r.public() for r in sample_results],
        "readinessStatus": readiness,
        "limitations": [
            "Deterministic replay validator only; no probabilistic simulation, Monte Carlo, or betting logic.",
            "Runner destinations come from the governed play_transition after-state (actual advancement), never inferred rules.",
            "READY means the mechanics are trustworthy enough to begin probabilistic simulation; it does NOT mean a forecasting simulator exists.",
        ],
    }
    audit_sha = _sha(payload)
    record = {"schemaVersion": "MLB_GAME_REPLAY_RUNTIME_ARTIFACT_V1", "replayRunId": run_id, "replaySha": audit_sha,
              "codeRevision": code_revision, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "replay": payload}
    for pointer in (completed, OUTPUT_ROOT / "latest.replay.json"):
        tmp = pointer.with_suffix(".tmp")
        tmp.write_bytes(_canonical(record))
        os.replace(tmp, pointer)
    _hb("REGISTERED_REPLAY_ARTIFACT", {"replaySha": audit_sha[:16], "runId": run_id, "readiness": readiness})
    print(f"COMPLETED readiness={readiness} sampleExact={sample_metrics['exactReplayRate']:.4f} "
          f"fullExecuted={full_metrics is not None}")
    return 0


def _readiness(metrics: Mapping[str, Any], sample_sound: bool) -> str:
    if not sample_sound:
        return "GAME_REPLAY_ENGINE_BLOCKED"
    if metrics["finalScoreExactRate"] >= 0.999 and metrics["exactReplayRate"] >= 0.99 and metrics["zeroContinuityRate"] >= 0.999:
        return "GAME_REPLAY_ENGINE_READY"
    return "GAME_REPLAY_ENGINE_PARTIALLY_READY"


def main(argv: list[str] | None = None) -> int:
    from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)
    retire_2025()   # locates+opens sealed-2025 play rows on ordinary run -> exit before any data open
    parser = argparse.ArgumentParser(description="Phase 5 deterministic MLB game-replay engine.")
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--full", action="store_true", help="expand to full 2023-2025 replay if the sample is sound")
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.estimate_only:
        print(json.dumps({"estimateOnly": True, "estimatedSecondsLower": 5, "estimatedSecondsUpper": 120}, sort_keys=True))
        return 0
    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001
        import traceback; traceback.print_exc()
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
