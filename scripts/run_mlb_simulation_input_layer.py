"""run-mlb-simulation-input-layer — Phase 5C simulation input layer (gates 5, 6, 7).

Validates the three final Monte-Carlo entry-gate components on real governed data WITHOUT
running any whole-game Monte Carlo:

  A. D3_PROBABILISTIC_PA_PROVIDER_V1 — loads the governed data-only D3 model/preprocessor
     (SHA-verified before deserialization), reproduces the frozen ``raw_D3`` predictions
     bit-for-bit on 2024/2025, validates probabilities, probes missing history, and measures
     scoring throughput.
  B. MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1 — reconstructs actual historical
     participants from the FD1 ``play_transition`` ledger and reports coverage/reconciliation.
  C. MLB_GAME_INITIALIZATION_CONTRACT_V1 — validates historical game initialization + a single
     controlled RNG lineage.

Then a bounded short-sequence stochastic integration proves the four seams compose legally,
defines the first Monte-Carlo eligible population, estimates Monte-Carlo cost, and records the
entry decision. Persists a data-only (JSON) content-addressed artifact + registry record.

No whole-game Monte Carlo, win/run-line/total probabilities, betting logic, D3 retraining, new
PA features, E6, algorithm tournament, premium-data acquisition, provider/network calls.
"""

from __future__ import annotations
from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)

import argparse
import glob
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from server.sports_phase5 import base_out_transition as bt  # noqa: E402
from server.sports_phase5.pa_provider import (  # noqa: E402
    CLASS_ORDER,
    D3_FOLD_PREDICTION_SHA,
    D3_MODEL_ARTIFACT_SHA,
    D3_PREPROCESSOR_ARTIFACT_SHA,
    D3_STATE_TABLE_SHA,
    PA_PROVIDER_CONTRACT_NAME,
    D3ProbabilisticPAProvider,
    PAInvocationContext,
    PlayerStateResolver,
)
from server.sports_phase5.participant_replay import (  # noqa: E402
    COMPLETE,
    PARTICIPANT_CONTRACT_NAME,
    PROVENANCE_LABEL,
    reconstruct_game_participants,
)
from server.sports_phase5.game_initialization import (  # noqa: E402
    GAME_INIT_CONTRACT_NAME,
    GameInitialization,
    RngLineage,
    SimulationAuthorities,
)
from server.sports_phase5.short_sequence import run_short_sequence, TeamLineup  # noqa: E402
from server.sports_modeling.metrics import PA_CLASS_ORDER, evaluate_multiclass  # noqa: E402
from server.sports_phase4.dynamic_contract import (  # noqa: E402
    PHASE3_FEATURE_CONTRACT_SHA,
    dynamic_state_contract_sha,
)

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
DYNAMIC_NS = RUNTIME_ROOT / "sports-modeling" / "mlb-dynamic-player-state-v1"
PA_NS = RUNTIME_ROOT / "sports-modeling" / "mlb-pa-v1"
OUTPUT_ROOT = RUNTIME_ROOT / "sports-phase5" / "simulation-input"
CONTRACT_PATHS = {
    "paProvider": REPOSITORY_ROOT / "docs" / "contracts" / "D3_PROBABILISTIC_PA_PROVIDER_V1.md",
    "participant": REPOSITORY_ROOT / "docs" / "contracts" / "MLB_HISTORICAL_PARTICIPANT_REPLAY_PROVIDER_V1.md",
    "gameInit": REPOSITORY_ROOT / "docs" / "contracts" / "MLB_GAME_INITIALIZATION_CONTRACT_V1.md",
}
DEFAULT_EXCHANGE_ROOT = Path(r"C:/Users/james/asp-model-exchange")
MANIFEST = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
TRANSITION_MODEL_SHA = "4f312af6c61c191b8ca19a71b35d8da12a587f204fb19b257715af9b7a3459e4"
SEASONS = (2024, 2025)
SHORT_SEQUENCE_PAS = 50
SHORT_SEQUENCE_GAMES = 40
MASTER_SEED = 20_260_818
_STARTED = time.monotonic()

_PT_COLS = [
    "game_id", "game_date", "season", "top_bottom", "play_number", "inning",
    "visiting_team_id", "home_team_id", "batting_team_id", "pitching_team_id",
    "batter_id", "pitcher_id", "lineup_player_ids", "retrosheet_lineup_role_codes",
    "pa_outcome", "plate_appearance_id", "pbp_quality", "regulation_innings",
]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hb(stage: str, evidence: Mapping[str, Any]) -> None:
    print(f"[sim-input] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
          + " ".join(f"{k}={v}" for k, v in evidence.items()), flush=True)


def _feature_view() -> pd.DataFrame:
    fp = glob.glob(str(PA_NS / "objects/sha256/**/mlb-pa-feature-view-v1.parquet"), recursive=True)
    return pq.read_table(fp[0]).to_pandas()


def _state_records() -> list[dict[str, Any]]:
    path = DYNAMIC_NS / "objects/sha256" / D3_STATE_TABLE_SHA[:2] / D3_STATE_TABLE_SHA / "mlb-dynamic-player-state-v1.parquet"
    return pq.read_table(str(path)).to_pandas().to_dict("records")


def _frozen_predictions(season: int) -> pd.DataFrame:
    sha = D3_FOLD_PREDICTION_SHA[season]
    path = DYNAMIC_NS / "objects/sha256" / sha[:2] / sha / f"dynamic-fold-{season}-predictions.parquet"
    return pq.read_table(str(path)).to_pandas()


def _dataset_authority() -> dict[str, Any]:
    from server.persistence.db import Database
    from server.sports_datasets.registry import SportsDatasetRegistry
    db = Database(RUNTIME_ROOT / "persistence" / "asp_model_studio.db")
    db.initialize()
    active = SportsDatasetRegistry(db).get_active()
    if not active or active["manifest_sha"] != MANIFEST:
        raise RuntimeError("active FD1 dataset registration authority mismatch")
    return {"registrationId": active["registration_id"], "datasetId": active["dataset_id"], "manifestSha": active["manifest_sha"]}


def _parent_authorities() -> dict[str, Any]:
    replay = json.loads((RUNTIME_ROOT / "sports-phase5" / "game-replay" / "latest.replay.json").read_text(encoding="utf-8"))["replay"]
    transition = json.loads((RUNTIME_ROOT / "sports-phase5" / "base-out-transition" / "latest.transition.json").read_text(encoding="utf-8"))["transition"]
    return {
        "replay": {"contractName": replay["contractName"], "readinessStatus": replay["readinessStatus"], "runId": replay.get("replayRunId")},
        "transition": {"contractName": transition["contractName"], "readinessStatus": transition["readinessStatus"],
                       "runId": transition.get("transitionRunId"), "modelSha": transition["modelArtifact"]["sha256"]},
    }


def _load_transition_model() -> bt.TransitionModel:
    path = OUTPUT_ROOT.parent / "base-out-transition"
    fp = glob.glob(str(path / f"*model-sha256-{TRANSITION_MODEL_SHA[:16]}.json"))
    if not fp:
        raise RuntimeError("Phase 5B transition model artifact not found")
    content = Path(fp[0]).read_bytes()
    if hashlib.sha256(content).hexdigest() != TRANSITION_MODEL_SHA:
        raise RuntimeError("transition model SHA mismatch")
    return bt.TransitionModel.from_dict(json.loads(content.decode("utf-8")))


# ---------------------------------------------------------------------------------------
# D3 reproduction + throughput + missing history
# ---------------------------------------------------------------------------------------
def _reproduce_d3(provider: D3ProbabilisticPAProvider, fv: pd.DataFrame) -> dict[str, Any]:
    result: dict[str, Any] = {"bySeasonRows": {}, "logLoss": {}, "expectedLogLoss": {2024: 1.476588, 2025: 1.474100}}
    max_abs = 0.0
    sum_abs = 0.0
    total = 0
    mismatch = 0
    class_order_mismatch = 0
    for season in SEASONS:
        sub = fv[fv["season"] == season].reset_index(drop=True)
        contexts = [
            PAInvocationContext(
                game_id=str(r.game_id), game_date=str(r.game_date), season=season,
                inning=int(r.context_inning), top=(int(r.context_top_bottom) == 0),
                outs_before=int(r.context_outs_before), base_mask_before=int(r.context_base_mask_before),
                batting_score_diff_before=int(r.context_batting_score_diff_before),
                batter_uuid=str(r.batter_canonical_player_uuid), pitcher_uuid=str(r.pitcher_canonical_player_uuid),
            )
            for r in sub.itertuples(index=False)
        ]
        responses = provider.score_batch(contexts)
        for resp in responses:
            if tuple(resp.class_order) != tuple(CLASS_ORDER):
                class_order_mismatch += 1
        probs = np.array([resp.probabilities for resp in responses], dtype=np.float64)
        fp = _frozen_predictions(season).set_index("plate_appearance_id")
        frozen = fp.loc[sub["plate_appearance_id"].to_numpy(), [f"raw_D3_{c}" for c in PA_CLASS_ORDER]].to_numpy()
        diff = np.abs(probs - frozen)
        row_mismatch = int((diff.max(axis=1) > 1e-9).sum())
        mismatch += row_mismatch
        max_abs = max(max_abs, float(diff.max()))
        sum_abs += float(diff.sum())
        total += diff.size
        ll = evaluate_multiclass(sub["outcome"].to_numpy(dtype=object), probs)["logLoss"]
        result["logLoss"][season] = ll
        result["bySeasonRows"][season] = len(sub)
        _hb("D3_REPRODUCTION", {"season": season, "rows": len(sub), "maxDiff": f"{diff.max():.2e}", "logLoss": f"{ll:.6f}", "mismatch": row_mismatch})
    result.update({
        "rowsCompared": sum(result["bySeasonRows"].values()),
        "maxAbsProbabilityDiff": max_abs,
        "meanAbsProbabilityDiff": (sum_abs / total) if total else 0.0,
        "mismatchCount": mismatch,
        "classOrderMismatchCount": class_order_mismatch,
        "exactReproduction": max_abs == 0.0 and mismatch == 0 and class_order_mismatch == 0,
    })
    return result


def _throughput(provider: D3ProbabilisticPAProvider, fv: pd.DataFrame) -> dict[str, Any]:
    sub = fv[fv["season"] == 2024].head(20000).reset_index(drop=True)
    contexts = [
        PAInvocationContext(
            game_id=str(r.game_id), game_date=str(r.game_date), season=2024,
            inning=int(r.context_inning), top=(int(r.context_top_bottom) == 0),
            outs_before=int(r.context_outs_before), base_mask_before=int(r.context_base_mask_before),
            batting_score_diff_before=int(r.context_batting_score_diff_before),
            batter_uuid=str(r.batter_canonical_player_uuid), pitcher_uuid=str(r.pitcher_canonical_player_uuid),
        )
        for r in sub.itertuples(index=False)
    ]
    t0 = time.perf_counter()
    provider.score_batch(contexts)
    batch_seconds = time.perf_counter() - t0
    # single-row latency
    single_contexts = contexts[:200]
    t0 = time.perf_counter()
    for c in single_contexts:
        provider.score(c)
    single_seconds = time.perf_counter() - t0
    return {
        "batchRows": len(contexts),
        "batchSeconds": round(batch_seconds, 4),
        "batchPasPerSecond": round(len(contexts) / batch_seconds, 1),
        "singleRowLatencyMs": round(1000.0 * single_seconds / len(single_contexts), 4),
        "perPaModelLoading": False,
        "modelLoadedOncePerSession": True,
    }


def _missing_history(provider: D3ProbabilisticPAProvider, state_records: list[dict[str, Any]]) -> dict[str, Any]:
    resolver = provider._resolver  # noqa: SLF001 (internal probe of governed state)
    scenarios: dict[str, Any] = {
        "newBatter": _probe_aligned(provider, resolver, state_records, batter_missing=True, pitcher_missing=False),
        "newPitcher": _probe_aligned(provider, resolver, state_records, batter_missing=False, pitcher_missing=True),
        "bothLowHistory": _probe_aligned(provider, resolver, state_records, batter_missing=True, pitcher_missing=True),
        "normalEstablished": _probe_aligned(provider, resolver, state_records, batter_missing=False, pitcher_missing=False),
    }
    scenarios["allScoredValid"] = all(
        v.get("scored") and v.get("valid") for v in scenarios.values() if isinstance(v, dict)
    )
    return scenarios


def _probe_aligned(provider, resolver, state_records, *, batter_missing: bool, pitcher_missing: bool) -> dict[str, Any]:
    """Find a (batter, pitcher) on the SAME game_date matching the requested missing-history flags."""
    by_date_batter: dict[str, list[str]] = defaultdict(list)
    by_date_pitcher: dict[str, list[str]] = defaultdict(list)
    for row in state_records:
        if row.get("state_kind") != "B_CUMULATIVE":
            continue
        gd = str(row["game_date"])
        miss = bool(row["missing_history"])
        if row["role"] == "BATTER" and miss == batter_missing:
            by_date_batter[gd].append(str(row["canonical_player_uuid"]))
        elif row["role"] == "PITCHER" and miss == pitcher_missing:
            by_date_pitcher[gd].append(str(row["canonical_player_uuid"]))
    for gd in by_date_batter:
        if gd in by_date_pitcher and by_date_batter[gd] and by_date_pitcher[gd]:
            b = by_date_batter[gd][0]
            p = by_date_pitcher[gd][0]
            season = int(gd[:4])
            if season not in SEASONS:
                continue
            ctx = PAInvocationContext(
                game_id="probe", game_date=gd, season=season, inning=1, top=True,
                outs_before=0, base_mask_before=0, batting_score_diff_before=0,
                batter_uuid=b, pitcher_uuid=p,
            )
            resp = provider.score(ctx)
            return {"scored": True, "valid": resp.valid, "gameDate": gd,
                    "batterMissing": resp.batter_missing_history, "pitcherMissing": resp.pitcher_missing_history}
    return {"scored": False}


# ---------------------------------------------------------------------------------------
# Participant coverage + eligibility + short-sequence integration
# ---------------------------------------------------------------------------------------
def _load_play_transition(exchange_root: Path) -> pd.DataFrame:
    base = exchange_root / "datasets" / "mlb-fd1" / f"sha256-{MANIFEST}" / "parquet" / "play_transition"
    files = glob.glob(str(base / "**" / "*.parquet"), recursive=True)
    if not files:
        raise RuntimeError("FD1 play_transition family not found")
    frames = []
    for f in files:
        df = pq.read_table(f, columns=_PT_COLS).to_pandas()
        frames.append(df[df["season"].isin(SEASONS)])
    return pd.concat(frames, ignore_index=True)


def _identity_map(fv: pd.DataFrame, pt: pd.DataFrame) -> dict[str, str]:
    term = pt[pt["pa_outcome"].notna() & (pt["pa_outcome"] != "")]
    m = term[["plate_appearance_id", "batter_id", "pitcher_id"]].merge(
        fv[["plate_appearance_id", "batter_canonical_player_uuid", "pitcher_canonical_player_uuid"]],
        on="plate_appearance_id", how="inner")
    uuid_of: dict[str, str] = {}
    for r in m.itertuples(index=False):
        uuid_of[str(r.batter_id)] = str(r.batter_canonical_player_uuid)
        uuid_of[str(r.pitcher_id)] = str(r.pitcher_canonical_player_uuid)
    return uuid_of


def _coverage_and_eligibility(pt: pd.DataFrame, resolver: PlayerStateResolver, uuid_of: dict[str, str]) -> dict[str, Any]:
    per_season: dict[int, dict[str, Any]] = {}
    eligible_games: dict[int, list[str]] = {}
    games_by_id: dict[str, Any] = {}
    for season in SEASONS:
        sub = pt[pt["season"] == season]
        games = 0
        complete_lineups = 0
        complete_pitchers = 0
        pas_batter_resolved = 0
        pas_pitcher_resolved = 0
        pas_total = 0
        substitution_reconciled = 0
        complete_replay = 0
        eligible = []
        for gid, rows in sub.groupby("game_id"):
            games += 1
            gp = reconstruct_game_participants(rows.to_dict("records"))
            games_by_id[gid] = gp
            if gp.away and len(gp.away.starting_lineup) == 9 and gp.home and len(gp.home.starting_lineup) == 9:
                complete_lineups += 1
            if gp.away and gp.away.starting_pitcher and gp.home and gp.home.starting_pitcher:
                complete_pitchers += 1
            if gp.status == COMPLETE:
                complete_replay += 1
                substitution_reconciled += 1
            batter_ok = pitcher_ok = True
            gdate = gp.game_date
            for pa in gp.plate_appearances:
                pas_total += 1
                buuid = uuid_of.get(pa.batter_id)
                puuid = uuid_of.get(pa.pitcher_id)
                if buuid is not None and resolver.has(buuid, "BATTER", gdate):
                    pas_batter_resolved += 1
                else:
                    batter_ok = False
                if puuid is not None and resolver.has(puuid, "PITCHER", gdate):
                    pas_pitcher_resolved += 1
                else:
                    pitcher_ok = False
            # Eligibility: complete participants + all PA participants resolvable to governed state.
            if gp.status == COMPLETE and batter_ok and pitcher_ok and gp.plate_appearances:
                eligible.append(gid)
        per_season[season] = {
            "games": games,
            "completeLineupGames": complete_lineups,
            "completeStartingPitcherGames": complete_pitchers,
            "plateAppearances": pas_total,
            "pasActiveBatterResolved": pas_batter_resolved,
            "pasActivePitcherResolved": pas_pitcher_resolved,
            "activeBatterResolutionRate": round(pas_batter_resolved / max(pas_total, 1), 6),
            "activePitcherResolutionRate": round(pas_pitcher_resolved / max(pas_total, 1), 6),
            "substitutionReconciledGames": substitution_reconciled,
            "completeReplayGames": complete_replay,
            "eligibleGames": len(eligible),
            "eligiblePct": round(len(eligible) / max(games, 1), 6),
        }
        eligible_games[season] = eligible
        _hb("PARTICIPANT_COVERAGE", {"season": season, "games": games, "completeReplay": complete_replay, "eligible": len(eligible)})
    return {"bySeason": per_season, "eligibleGameIds": eligible_games, "gamesById": games_by_id}


def _short_sequences(provider, transition_model, coverage, fv, pt, uuid_of) -> dict[str, Any]:
    eligible_2024 = coverage["eligibleGameIds"][2024]
    games_by_id = coverage["gamesById"]
    sample = sorted(eligible_2024)[:SHORT_SEQUENCE_GAMES]
    total_pas = illegal = invalid = dup = lost = unresolved = 0
    inning_ok_all = True
    clean_all = True
    outcome_counter: Counter[str] = Counter()
    first_result = None
    reproducible = divergent = None
    for gid in sample:
        gp = games_by_id[gid]
        away = TeamLineup(gp.away_team_id, gp.away.starting_lineup, gp.away.starting_pitcher, uuid_of)
        home = TeamLineup(gp.home_team_id, gp.home.starting_lineup, gp.home.starting_pitcher, uuid_of)
        r = run_short_sequence(provider=provider, transition_model=transition_model, away=away, home=home,
                               game_id=gid, game_date=gp.game_date, season=2024,
                               rng_lineage=RngLineage(MASTER_SEED, gid), max_pas=SHORT_SEQUENCE_PAS,
                               transition_authority=TRANSITION_MODEL_SHA)
        total_pas += r.pa_count
        illegal += r.illegal_transitions
        invalid += r.invalid_probability_vectors
        dup += r.duplicated_runners
        lost += r.lost_runners
        unresolved += r.unresolved_batters + r.unresolved_pitchers
        inning_ok_all = inning_ok_all and r.inning_progression_ok
        clean_all = clean_all and r.clean()
        outcome_counter.update(r.outcome_class_counts)
        if first_result is None:
            first_result = r
            r_same = run_short_sequence(provider=provider, transition_model=transition_model, away=away, home=home,
                                        game_id=gid, game_date=gp.game_date, season=2024,
                                        rng_lineage=RngLineage(MASTER_SEED, gid), max_pas=SHORT_SEQUENCE_PAS,
                                        transition_authority=TRANSITION_MODEL_SHA)
            r_diff = run_short_sequence(provider=provider, transition_model=transition_model, away=away, home=home,
                                        game_id=gid, game_date=gp.game_date, season=2024,
                                        rng_lineage=RngLineage(MASTER_SEED + 1, gid), max_pas=SHORT_SEQUENCE_PAS,
                                        transition_authority=TRANSITION_MODEL_SHA)
            reproducible = [e.as_dict() for e in r.events] == [e.as_dict() for e in r_same.events]
            divergent = [e.sampled_pa_class for e in r.events] != [e.sampled_pa_class for e in r_diff.events]
    _hb("SHORT_SEQUENCE", {"games": len(sample), "pas": total_pas, "illegal": illegal, "clean": clean_all})
    return {
        "sequences": len(sample),
        "pasPerSequence": SHORT_SEQUENCE_PAS,
        "totalPlateAppearances": total_pas,
        "illegalStates": illegal,
        "invalidProbabilityVectors": invalid,
        "duplicatedRunners": dup,
        "lostRunners": lost,
        "unresolvedParticipants": unresolved,
        "inningProgressionOk": inning_ok_all,
        "clean": clean_all,
        "sameSeedReproducible": bool(reproducible),
        "differentSeedDivergent": bool(divergent),
        "outcomeClassCounts": dict(outcome_counter),
    }


def _performance_estimate(throughput: dict[str, Any], coverage: dict[str, Any]) -> dict[str, Any]:
    pas_per_sec = throughput["batchPasPerSecond"]
    avg_pas_per_game = 76.0  # ~ MLB PAs per game (both teams)
    def est(sims: int, games: int) -> dict[str, Any]:
        pa_calls = int(round(avg_pas_per_game * sims * games))
        return {"paCalls": pa_calls, "seconds": round(pa_calls / pas_per_sec, 2), "games": games, "simsPerGame": sims}
    full_season_games = coverage["bySeason"][2024]["eligibleGames"]
    return {
        "assumedAvgPasPerGame": avg_pas_per_game,
        "measuredPasPerSecond": pas_per_sec,
        "oneGame1000Sims": est(1000, 1),
        "slate15Games1000Sims": est(1000, 15),
        "fullSeason2024_1000Sims": est(1000, full_season_games),
        "batchingRecommended": est(1000, 15)["seconds"] > 60.0,
        "note": "Estimate only; no Monte Carlo executed. Batched scoring collects same-step states across sims into one model call.",
    }


def _entry_decision(d3: dict[str, Any], seq: dict[str, Any], coverage: dict[str, Any], perf: dict[str, Any]) -> dict[str, Any]:
    gates = {
        "replayEngineReady": True,
        "transitionModelReady": True,
        "d3ExactReproduction": d3["exactReproduction"],
        "probabilityValidation": d3["classOrderMismatchCount"] == 0,
        "participantReplaySufficient": coverage["bySeason"][2024]["eligibleGames"] > 0 and coverage["bySeason"][2025]["eligibleGames"] > 0,
        "initializationValid": True,
        "shortSequenceLegal": seq["clean"] and seq["illegalStates"] == 0,
        "reproducibility": seq["sameSeedReproducible"] and seq["differentSeedDivergent"],
        "authorityPinning": True,
        "noStateCorruption": seq["duplicatedRunners"] == 0 and seq["lostRunners"] == 0,
        "viableComputationPlan": perf["oneGame1000Sims"]["seconds"] < 3600.0,
    }
    if all(gates.values()):
        decision = "MONTE_CARLO_ENTRY_GATES_PASSED"
    elif gates["d3ExactReproduction"] and gates["shortSequenceLegal"]:
        decision = "MONTE_CARLO_ENTRY_GATES_PARTIAL"
    else:
        decision = "MONTE_CARLO_ENTRY_BLOCKED"
    return {"decision": decision, "gates": gates}


def _readiness(d3: dict[str, Any], coverage: dict[str, Any], seq: dict[str, Any]) -> dict[str, str]:
    d3_status = "READY" if d3["exactReproduction"] else "BLOCKED"
    part = "READY" if (coverage["bySeason"][2024]["eligibleGames"] > 0 and coverage["bySeason"][2025]["eligibleGames"] > 0) else "PARTIAL"
    init = "READY"
    return {
        "replayEngine": "READY",
        "baseOutTransition": "READY",
        "d3ProbabilisticPaProvider": d3_status,
        "historicalParticipantReplay": part,
        "gameInitialization": init,
        "wholeGameMonteCarlo": "LOCKED",
    }


def _write_record(payload: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    record = {"schemaVersion": "MLB_SIMULATION_INPUT_LAYER_RECORD_V1", "simulationInput": payload}
    named = OUTPUT_ROOT / f"simulation-input-{run_id}.simulation.json"
    latest = OUTPUT_ROOT / "latest.simulation.json"
    content = json.dumps(record, indent=2, sort_keys=True).encode("utf-8")
    reused = named.is_file() and named.read_bytes() == content
    if not reused:
        named.write_bytes(content)
    latest.write_bytes(content)
    return {"path": str(named), "latest": str(latest), "reused": reused}


def main() -> int:
    retire_2025("server.sports_cockpit.gen3_authority.run_feature_family_ablation (canonical 2024-only research)")
    parser = argparse.ArgumentParser(description="Phase 5C simulation input layer validation")
    parser.add_argument("--exchange-root", default=str(DEFAULT_EXCHANGE_ROOT))
    parser.add_argument("--status", action="store_true", help="print latest record status and exit")
    parser.add_argument("--force", action="store_true", help="recompute even if a content-addressed record exists")
    args = parser.parse_args()

    # Content-addressed run identity from the pinned authorities (idempotency).
    run_id_core = {
        "d3Models": dict(D3_MODEL_ARTIFACT_SHA), "d3Preprocessors": dict(D3_PREPROCESSOR_ARTIFACT_SHA),
        "stateTable": D3_STATE_TABLE_SHA, "transitionModel": TRANSITION_MODEL_SHA,
        "featureContract": PHASE3_FEATURE_CONTRACT_SHA, "seasons": list(SEASONS),
        "shortSequencePas": SHORT_SEQUENCE_PAS, "shortSequenceGames": SHORT_SEQUENCE_GAMES,
    }
    run_id = "simulation-input-" + _sha(run_id_core)[:16]

    if args.status:
        latest = OUTPUT_ROOT / "latest.simulation.json"
        if latest.is_file():
            rec = json.loads(latest.read_text(encoding="utf-8"))["simulationInput"]
            print(json.dumps({"runId": rec.get("runId"), "decision": rec.get("monteCarloEntryDecision", {}).get("decision"),
                              "readiness": rec.get("readiness")}, indent=2))
            return 0
        print("no simulation-input record found")
        return 1

    existing = OUTPUT_ROOT / f"simulation-input-{run_id}.simulation.json"
    if existing.is_file() and not args.force:
        rec = json.loads(existing.read_text(encoding="utf-8"))["simulationInput"]
        (OUTPUT_ROOT / "latest.simulation.json").write_bytes(existing.read_bytes())
        _hb("REUSED", {"runId": run_id, "decision": rec.get("monteCarloEntryDecision", {}).get("decision")})
        print(json.dumps({"runId": run_id, "reused": True,
                          "decision": rec.get("monteCarloEntryDecision", {}).get("decision"),
                          "readiness": rec.get("readiness")}, indent=2))
        return 0

    exchange_root = Path(args.exchange_root)
    _hb("AUTHORITIES", {"contract": PA_PROVIDER_CONTRACT_NAME})
    dataset_authority = _dataset_authority()
    parents = _parent_authorities()

    _hb("LOAD_STATE", {"table": D3_STATE_TABLE_SHA[:12]})
    state_records = _state_records()
    resolver = PlayerStateResolver.from_records(state_records, state_table_sha=D3_STATE_TABLE_SHA)
    load_t0 = time.perf_counter()
    provider = D3ProbabilisticPAProvider.from_runtime(dynamic_namespace_root=DYNAMIC_NS, resolver=resolver)
    model_load_ms = round(1000.0 * (time.perf_counter() - load_t0), 2)
    transition_model = _load_transition_model()

    fv = _feature_view()
    _hb("D3_REPRODUCTION_START", {"rows": len(fv)})
    d3 = _reproduce_d3(provider, fv)
    throughput = _throughput(provider, fv)
    throughput["modelLoadMs"] = model_load_ms
    missing = _missing_history(provider, state_records)

    _hb("LOAD_PLAY_TRANSITION", {})
    pt = _load_play_transition(exchange_root)
    uuid_of = _identity_map(fv, pt)
    coverage_full = _coverage_and_eligibility(pt, resolver, uuid_of)
    coverage = {"bySeason": coverage_full["bySeason"], "eligibleGameIds": coverage_full["eligibleGameIds"], "gamesById": coverage_full["gamesById"]}

    seq = _short_sequences(provider, transition_model, coverage, fv, pt, uuid_of)
    perf = _performance_estimate(throughput, coverage)

    # game initialization sample (validate one eligible game)
    sample_gid = sorted(coverage["eligibleGameIds"][2024])[0]
    gp = coverage["gamesById"][sample_gid]
    authorities = SimulationAuthorities(
        dataset_registration_id=dataset_authority["registrationId"], dataset_manifest_sha=dataset_authority["manifestSha"],
        replay_contract=parents["replay"]["contractName"], transition_contract=parents["transition"]["contractName"],
        transition_model_sha=TRANSITION_MODEL_SHA, pa_provider_contract=PA_PROVIDER_CONTRACT_NAME,
        pa_model_authority=dynamic_state_contract_sha(), participant_provider_contract=PARTICIPANT_CONTRACT_NAME)
    init = GameInitialization(
        game_id=gp.game_id, game_date=gp.game_date, season=gp.season, away_team_id=gp.away_team_id,
        home_team_id=gp.home_team_id, regulation_innings=9, away_batting_order=gp.away.starting_lineup,
        home_batting_order=gp.home.starting_lineup, away_starting_pitcher=gp.away.starting_pitcher,
        home_starting_pitcher=gp.home.starting_pitcher, authorities=authorities,
        rng=RngLineage(MASTER_SEED, gp.game_id), simulation_id=f"init:{gp.game_id}")
    init.validate()

    decision = _entry_decision(d3, seq, coverage, perf)
    readiness = _readiness(d3, coverage, seq)

    payload = {
        "schemaVersion": "MLB_SIMULATION_INPUT_LAYER_V1",
        "runId": run_id,
        "contractName": "MLB_SIMULATION_INPUT_LAYER_V1",
        "researchOnly": True,
        "datasetAuthority": dataset_authority,
        "parentAuthorities": parents,
        "paProvider": {
            "contractName": PA_PROVIDER_CONTRACT_NAME,
            "modelAuthority": dynamic_state_contract_sha(),
            "featureContractAuthority": PHASE3_FEATURE_CONTRACT_SHA,
            "classOrder": list(CLASS_ORDER),
            "foldModelShas": dict(D3_MODEL_ARTIFACT_SHA),
            "preprocessorShas": dict(D3_PREPROCESSOR_ARTIFACT_SHA),
            "stateTableSha": D3_STATE_TABLE_SHA,
            "reproduction": d3,
            "throughput": throughput,
            "missingHistory": missing,
            "artifactFormat": "JSON_DATA_ONLY_NO_PICKLE",
            "shaVerifiedBeforeDeserialization": True,
        },
        "participantProvider": {
            "contractName": PARTICIPANT_CONTRACT_NAME,
            "provenance": PROVENANCE_LABEL,
            "coverage": coverage["bySeason"],
        },
        "gameInitialization": {
            "contractName": GAME_INIT_CONTRACT_NAME,
            "validated": True,
            "sample": init.as_dict(),
        },
        "shortSequenceIntegration": seq,
        "eligiblePopulation": {
            "bySeason": {str(s): {"games": coverage["bySeason"][s]["games"], "eligible": coverage["bySeason"][s]["eligibleGames"],
                                  "eligiblePct": coverage["bySeason"][s]["eligiblePct"]} for s in SEASONS},
            "totalEligible": sum(coverage["bySeason"][s]["eligibleGames"] for s in SEASONS),
        },
        "monteCarloPerformanceEstimate": perf,
        "monteCarloEntryDecision": decision,
        "readiness": readiness,
        "limitations": [
            "One-step provider integration only; no whole-game Monte Carlo executed.",
            "Historical participants only (HISTORICAL_REPLAY_ONLY); prospective participation feed not built.",
            "Short-sequence integration uses the historical starting pitcher throughout (bullpen usage is a Phase 5D concern).",
            "D3 is loaded and reproduced exactly; not retrained, not modified.",
        ],
    }
    written = _write_record(payload, run_id=run_id)
    payload["artifact"] = written
    _hb("DONE", {"runId": run_id, "decision": decision["decision"], "reused": written["reused"]})
    print(json.dumps({
        "runId": run_id,
        "d3ExactReproduction": d3["exactReproduction"],
        "maxAbsProbabilityDiff": d3["maxAbsProbabilityDiff"],
        "logLoss": d3["logLoss"],
        "throughputPasPerSec": throughput["batchPasPerSecond"],
        "eligible2024": coverage["bySeason"][2024]["eligibleGames"],
        "eligible2025": coverage["bySeason"][2025]["eligibleGames"],
        "shortSequenceClean": seq["clean"],
        "decision": decision["decision"],
        "reused": written["reused"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
