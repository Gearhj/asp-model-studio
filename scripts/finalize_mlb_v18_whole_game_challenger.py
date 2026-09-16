"""Build the bounded V18 whole-game Development bundle and AISP handoff."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import joblib
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from server.persistence.db import Database
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_phase5 import base_out_transition as bt
from server.sports_phase5.whole_game_monte_carlo import GameContribs, simulate_game
from server.sports_phase5.game_initialization import RngLineage
from server.sports_current_statcast import stage3_eda as eda
from server.sports_current_statcast.mlb_v18_game_baseline import (
    FD1_LOGICAL_PREFIX, FD1_REGISTRATION_ID, load_registered_fd1_transitions,
)
from server.sports_current_statcast.mlb_v18_whole_game_challenger import (
    V18StateProbabilityProvider, chronological_temperature_study,
    compose_raw_template, simulate_prospective_game, verify_template_all_folds,
)
from server.sports_current_statcast import stage3_model_laboratory as lab
from server.sports_current_statcast.stage3_model_laboratory import resolve_model_lab_authority


COMPARISON = ROOT / "outputs/mlb-corrected-treatment/corrected-hgb-recovery-1-comparison-12bfbc8c4a17a7ef45ec102ef3cb7ca8a9e03b395d0941eed51c98ec3bdf699d.json"
OOF = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory/objects/oof/sha256/b79a80398ef32a13589a8bb66f5e4e9c698b600195de5369886f7fc07f0dc215.parquet"
SNAPSHOT = ROOT / ".runtime/asp-model-studio/v18-whole-game-challenger/aisp-pregame-snapshot.json"
BASELINE_BUNDLE = ROOT / "outputs/mlb-v18-pa-game-baseline/sha256/5d0525475d26c63b275f2534badf668173b2a149c885327ad1dbcc4a6c5533ee"
OUTPUT = ROOT / "outputs/mlb-v18-whole-game-challenger"
RUNTIME = ROOT / ".runtime/asp-model-studio/stage3-model-laboratory"
DB = ROOT / ".runtime/asp-model-studio/persistence/asp_model_studio.db"
EXCHANGE = Path(r"C:\Users\james\asp-model-exchange")
DIM_PLAYER = Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1\objects\sha256\ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf\object.parquet")
MASTER_SEED = 20260907


def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def json_bytes(value: object) -> bytes:
    return canonical_json_bytes(value)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def json_safe(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if pd.isna(value) if not isinstance(value, (dict, list, tuple)) else False:
        return None
    return value


def file_record(path: Path, base: Path) -> dict:
    raw = path.read_bytes()
    return {"relativePath": path.relative_to(base).as_posix(), "bytes": len(raw), "sha256": sha_bytes(raw)}


def load_pipelines(comparison: dict) -> tuple[list[object], list[dict]]:
    pipelines, records = [], []
    for row in comparison["treatmentExecution"]["fittedFoldArtifacts"]:
        reference = row["localResearchArtifact"]["model"]
        path = RUNTIME / reference["relativePath"]
        if sha_bytes(path.read_bytes()) != reference["sha256"]:
            raise RuntimeError("saved V18 model checksum differs")
        pipeline = joblib.load(path)
        if len(pipeline.ordered_features) != 246 or len(pipeline.preprocessor.ordered_features) != 273:
            raise RuntimeError("saved V18 pipeline feature contract differs")
        pipelines.append(pipeline)
        records.append({"foldNumber": row["foldNumber"], **reference, "reloadVerified": True})
    return pipelines, records


def identity_map(mlbam_ids: list[str]) -> tuple[dict[str, str], dict]:
    table = pq.read_table(
        DIM_PLAYER,
        columns=["canonicalPlayerId", "mlbamId", "resolutionStatus"],
        filters=[("mlbamId", "in", mlbam_ids)],
    ).to_pandas().drop_duplicates()
    exact = table[table["resolutionStatus"] == "MATCHED_EXACT"]
    mapping = dict(zip(exact["mlbamId"].astype(str), exact["canonicalPlayerId"].astype(str)))
    return mapping, {
        "source": "GOVERNED_DIM_PLAYER_EXACT_MLBAM_CROSSWALK",
        "artifactSha256": "ab06c88e7d4fa6e78b397c8a4dfbbc2c8a21a51c03f50fd78ee49de232fb0aaf",
        "requested": len(set(mlbam_ids)), "resolved": len(mapping),
    }


def latest_rows(frame: pd.DataFrame, source_order: tuple[str, ...], players: list[str], role: str) -> dict[str, dict]:
    identity = "batterCanonicalPlayerId" if role == "BATTER" else "pitcherCanonicalPlayerId"
    frame = frame[
        frame[identity].astype(str).isin(players)
        & frame["game_date"].astype(str).between("2026-04-01", "2026-08-13")
    ].copy()
    if frame.empty:
        return {}
    frame.sort_values(["game_date", "canonicalPaId"], inplace=True, kind="stable")
    return {
        str(key): row.loc[list(source_order)].to_dict()
        for key, row in frame.groupby(identity, sort=False).tail(1).set_index(identity, drop=False).iterrows()
    }


def cold_batter(frame: pd.DataFrame, source_order: tuple[str, ...]) -> dict:
    recent = frame[frame["game_date"].astype(str).between("2026-07-01", "2026-08-13")]
    valid = recent[recent["batter_prior_missing"].fillna(False).astype(bool)]
    if valid.empty:
        raise RuntimeError("governed Development cold-start exemplar is unavailable")
    return valid.iloc[-1].loc[list(source_order)].to_dict()


def bullpen_rows(authority, development: pd.DataFrame, source_order: tuple[str, ...], team: str, starter_id: str) -> list[dict]:
    identities = eda._scan(
        authority, ["canonicalPaId"],
        {"startDate": "2026-07-15", "endDate": "2026-08-13", "fieldingTeam": [team]},
    )
    selected_ids = set(identities["canonicalPaId"].astype(str))
    frame = development[development["canonicalPaId"].astype(str).isin(selected_ids)].copy()
    frame = frame[frame["pitcherCanonicalPlayerId"].astype(str) != starter_id].copy()
    frame.sort_values(["game_date", "canonicalPaId"], inplace=True, kind="stable")
    latest = frame.groupby("pitcherCanonicalPlayerId", sort=False).tail(1).tail(8)
    if latest.empty:
        raise RuntimeError(f"Development team bullpen distribution unavailable for {team}")
    return [row.loc[list(source_order)].to_dict() for _, row in latest.iterrows()]


def distribution(values: np.ndarray) -> list[dict]:
    counts = Counter(int(v) for v in values)
    total = len(values)
    return [{"value": key, "probability": count / total} for key, count in sorted(counts.items())]


def compact_simulation(result: dict) -> dict:
    return {
        key: json_safe(value) for key, value in result.items()
        if key not in {"awayRuns", "homeRuns", "innings", "paCounts"}
    } | {
        "awayRunDistribution": distribution(result["awayRuns"]),
        "homeRunDistribution": distribution(result["homeRuns"]),
        "totalRunDistribution": distribution(result["awayRuns"] + result["homeRuns"]),
        "runDifferentialDistribution": distribution(result["homeRuns"] - result["awayRuns"]),
    }


def actual_scores_2024(game_ids: list[str]) -> dict[str, tuple[int, int]]:
    connection = sqlite3.connect(DB)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            "select logical_uri from sports_dataset_partitions where registration_id=? "
            "and family='play_transition' and season=2024 order by month",
            (FD1_REGISTRATION_ID,),
        ).fetchall()
    finally:
        connection.close()
    frames = []
    for row in rows:
        relative = PurePosixPath(str(row["logical_uri"])[len(FD1_LOGICAL_PREFIX):])
        path = EXCHANGE.joinpath(*relative.parts)
        table = pq.read_table(path, columns=["game_id", "play_number", "visiting_score_after", "home_score_after"])
        frames.append(table.to_pandas())
    frame = pd.concat(frames, ignore_index=True)
    frame = frame[frame["game_id"].astype(str).isin(game_ids)].sort_values(["game_id", "play_number"])
    return {
        str(game): (int(row["visiting_score_after"]), int(row["home_score_after"]))
        for game, row in frame.groupby("game_id").tail(1).set_index("game_id").iterrows()
    }


def oracle_evaluation(authority, development, oof, transition_model) -> dict:
    """Small oracle mechanics check using immutable fold-1 OOF PA probabilities.

    Realized game-local PA context is intentionally averaged to one eight-class vector per
    game.  This is fast, leakage-labeled mechanics evidence, never a prospective forecast.
    """
    frame = development[
        development["game_date"].astype(str).between("2024-04-01", "2024-04-07")
    ][["canonicalPaId", "canonicalGameId", "game_date", "context_inning"]].copy()
    game_ids = eda._scan(
        authority, ["canonicalGameId", "game_id"],
        {"startDate": "2024-04-01", "endDate": "2024-04-07"},
    ).drop_duplicates("canonicalGameId")
    frame = frame.merge(game_ids, on="canonicalGameId", how="inner", validate="many_to_one")
    probability_columns = [f"probability_{name}" for name in PA_CLASS_ORDER]
    fold_oof = oof[oof["foldNumber"] == 1][["canonicalPaId", *probability_columns]]
    frame = frame.merge(fold_oof, on="canonicalPaId", how="inner", validate="one_to_one")
    games = []
    for canonical_game_id, game in frame.groupby("canonicalGameId", sort=True):
        if len(game) < 50:
            continue
        games.append((str(canonical_game_id), str(game.iloc[0]["game_id"]), game))
        if len(games) == 10:
            break
    actual = actual_scores_2024([row[1] for row in games])
    records, null_records = [], []
    # Fold-1 null is estimated only from its registered earlier training window.
    training = development[development["game_date"].astype(str).between("2023-03-30", "2023-10-01")]
    counts = training["outcome"].value_counts()
    null_p = np.array([counts.get(name, 0) + 1 for name in PA_CLASS_ORDER], dtype=float)
    null_p /= null_p.sum()
    zeros = np.zeros((130, 8), dtype=float)
    contribs = GameContribs(zeros, zeros, zeros, zeros, 9)
    from server.sports_phase5.whole_game_monte_carlo import FastTransitionSampler
    sampler = FastTransitionSampler(transition_model)
    for canonical_game_id, game_id, game in games:
        if game_id not in actual:
            continue
        game_p = game.loc[:, probability_columns].to_numpy(dtype=float).mean(axis=0)
        game_p /= game_p.sum()
        sim = simulate_game(
            game_id=f"oracle:{canonical_game_id}", contribs=contribs, fold=None,
            transition_sampler=sampler,
            rng_lineage=RngLineage(MASTER_SEED, f"oracle:{canonical_game_id}"),
            n_sims=5000, fixed_probs=game_p, check_legality=True,
        )
        null = simulate_game(
            game_id=f"null:{game_id}", contribs=contribs, fold=None,
            transition_sampler=sampler, rng_lineage=RngLineage(MASTER_SEED, f"null:{game_id}"),
            n_sims=5000, fixed_probs=null_p,
        )
        actual_away, actual_home = actual[game_id]
        records.append({
            "gameId": game_id, "canonicalGameId": canonical_game_id,
            "actualAway": actual_away, "actualHome": actual_home,
            "actualExtraInnings": bool(game["context_inning"].max() > 9),
            "pHome": float(sim.home_win.mean()), "meanAway": float(sim.away_runs.mean()),
            "meanHome": float(sim.home_runs.mean()), "meanTotal": float((sim.away_runs + sim.home_runs).mean()),
            "meanDiff": float((sim.home_runs - sim.away_runs).mean()),
            "oneRunRate": float((np.abs(sim.home_runs - sim.away_runs) == 1).mean()),
            "extraInningRate": float((sim.innings > 9).mean()), "nontermination": sim.nonterminated,
            "illegal": sim.illegal_states,
        })
        null_records.append({"gameId": game_id, "pHome": float(null.home_win.mean())})

    def metrics(rows):
        p = np.clip(np.array([r["pHome"] for r in rows]), 1e-9, 1 - 1e-9)
        y = np.array([r["actualHome"] > r["actualAway"] for r in records], dtype=float)
        return {"homeWinLogLoss": float(-(y*np.log(p)+(1-y)*np.log(1-p)).mean()),
                "homeWinBrier": float(np.square(p-y).mean())}
    metric = metrics(records)
    actual_total = np.array([r["actualAway"] + r["actualHome"] for r in records])
    actual_diff = np.array([r["actualHome"] - r["actualAway"] for r in records])
    metric.update({
        "awayRunsMae": float(np.mean([abs(r["meanAway"]-r["actualAway"]) for r in records])),
        "homeRunsMae": float(np.mean([abs(r["meanHome"]-r["actualHome"]) for r in records])),
        "totalRunsMae": float(np.mean([abs(r["meanTotal"]-v) for r, v in zip(records, actual_total)])),
        "runDifferentialMae": float(np.mean([abs(r["meanDiff"]-v) for r, v in zip(records, actual_diff)])),
        "meanPredictedTotal": float(np.mean([r["meanTotal"] for r in records])),
        "meanActualTotal": float(actual_total.mean()),
        "predictedOneRunRate": float(np.mean([r["oneRunRate"] for r in records])),
        "actualOneRunRate": float(np.mean(np.abs(actual_diff) == 1)),
        "predictedExtraInningRate": float(np.mean([r["extraInningRate"] for r in records])),
        "actualExtraInningRate": float(np.mean([r["actualExtraInnings"] for r in records])),
        "terminationFailures": int(sum(r["nontermination"] for r in records)),
        "illegalStates": int(sum(r["illegal"] for r in records)),
        "homeWinCalibration": {"meanPredicted": float(np.mean([r["pHome"] for r in records])), "observed": float(np.mean([r["actualHome"] > r["actualAway"] for r in records]))},
    })
    return {
        "track": "ORACLE_MECHANICS_DIAGNOSTIC_NONDEPLOYABLE",
        "fold": 1, "games": len(records), "simulationsPerGame": 5000,
        "metrics": metric, "null": metrics(null_records), "gamesEvidence": records,
        "participantSemantics": "REALIZED_GAME_LOCAL_FOLD1_OOF_PA_PROBABILITIES_AVERAGED_ORACLE_ONLY",
        "limitation": "The game-local vector uses realized PA contexts and participation; it tests the transition/game mechanics and is not a deployable pregame forecast.",
        "finalOotRowsRead": 0,
    }


def main() -> int:
    started = time.perf_counter()
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    if snapshot.get("outcomesRead") is not False or snapshot.get("aispRowsModified") != 0:
        raise RuntimeError("AISP snapshot boundary differs")
    pipelines, model_records = load_pipelines(comparison)
    source_order = tuple(pipelines[0].ordered_features)
    if any(tuple(model.ordered_features) != source_order for model in pipelines):
        raise RuntimeError("saved fold raw feature orders differ")
    authority = resolve_model_lab_authority(Database(DB), "asp-mtlozhdx")
    if authority.split["finalOot"].get("locked") is not True:
        raise RuntimeError("Final OOT seal is not active")
    corrected_set = next(
        (
            item for item in authority.feature_sets
            if (item.get("transformationContracts") or {}).get("semanticTreatmentVersion")
            == "MLB_SEMANTIC_TREATMENT_V1"
            and len(item.get("orderedFeatures") or []) == 273
        ),
        None,
    )
    if corrected_set is None:
        raise RuntimeError("the split-bound corrected 273-input V18 feature set is unavailable")
    registered_sources = tuple(corrected_set["transformationContracts"]["sourceOrderedFeatures"])
    if source_order[:len(registered_sources)] != registered_sources:
        raise RuntimeError("saved model raw feature prefix differs from the registered V18 source contract")
    development = lab._fold_frame(
        authority,
        corrected_set["orderedFeatures"],
        include_oof_identity=True,
        include_target=True,
    )
    source_identity = development.attrs.get("correctedSourceIdentity") or {}
    if (
        source_identity.get("treatmentSpecificationId")
        != "stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638"
        or source_identity.get("treatmentManifestChecksum")
        != "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3"
        or len(development) != 683_662
    ):
        raise RuntimeError("authenticated V18 Development authority differs from the accepted contract")
    if any(name not in development.columns for name in source_order):
        raise RuntimeError("authenticated V18 Development frame does not supply the saved model inputs")

    oof = pq.read_table(OOF).to_pandas()
    calibration, _ = chronological_temperature_study(oof)
    if calibration["decision"] != "RETAIN_RAW_V18":
        raise RuntimeError("this bundle expects evidence-based raw V18 selection")

    mlbam = [str(entry["mlbam"]) for side in snapshot["sides"] for entry in side["lineup"]]
    mlbam += [str(side["starter"]["mlbamId"]) for side in snapshot["sides"]]
    crosswalk, crosswalk_evidence = identity_map(mlbam)
    batter_ids = [crosswalk.get(str(entry["mlbam"])) for side in snapshot["sides"] for entry in side["lineup"]]
    starter_by_side = {
        side["side"]: crosswalk.get(str(side["starter"]["mlbamId"]))
        for side in snapshot["sides"]
    }
    if set(starter_by_side) != {"AWAY", "HOME"} or any(value is None for value in starter_by_side.values()):
        raise RuntimeError("a prospective starter has no governed Model Studio identity")
    batter_evidence = latest_rows(development, source_order, [x for x in batter_ids if x], "BATTER")
    pitcher_evidence = latest_rows(development, source_order, list(starter_by_side.values()), "PITCHER")
    fallback = cold_batter(development, source_order)
    sides = sorted(snapshot["sides"], key=lambda row: row["side"] == "HOME")
    away_side, home_side = sides[0], sides[1]
    cursor = 0
    side_batters, cold_fallbacks = {}, []
    for side in (away_side, home_side):
        rows = []
        for entry in side["lineup"]:
            canonical = crosswalk.get(str(entry["mlbam"]))
            if canonical and canonical in batter_evidence:
                rows.append(batter_evidence[canonical])
            else:
                rows.append(dict(fallback))
                cold_fallbacks.append({"side": side["side"], "slot": entry["batting_order"], "mlbamId": str(entry["mlbam"]), "reason": "NO_DEVELOPMENT_PA_USES_GOVERNED_COLD_START_EXEMPLAR"})
            cursor += 1
        side_batters[side["side"]] = rows
    away_starter_id, home_starter_id = starter_by_side["AWAY"], starter_by_side["HOME"]
    if away_starter_id not in pitcher_evidence or home_starter_id not in pitcher_evidence:
        raise RuntimeError("a prospective starter lacks Development feature evidence")
    away_bullpen = bullpen_rows(authority.eda_authority, development, source_order, away_side["team"]["abbreviation"], away_starter_id)
    home_bullpen = bullpen_rows(authority.eda_authority, development, source_order, home_side["team"]["abbreviation"], home_starter_id)

    fixture = verify_template_all_folds(pipelines, side_batters["AWAY"][0], pitcher_evidence[home_starter_id])
    raw_templates = []
    for side, batters, opposing in (("AWAY", side_batters["AWAY"], pitcher_evidence[home_starter_id]), ("HOME", side_batters["HOME"], pitcher_evidence[away_starter_id])):
        for slot, batter in enumerate(batters, 1):
            row = compose_raw_template(source_order=source_order, batter_row=batter, pitcher_row=opposing,
                state={"context_inning": 1, "context_top_bottom": 0 if side == "AWAY" else 1,
                       "context_outs_before": 0, "context_base_mask_before": 0,
                       "context_batting_score_diff_before": 0})
            row.insert(0, "templateSide", side); row.insert(1, "templateSlot", slot)
            raw_templates.append(row)
    raw_template_frame = pd.concat(raw_templates, ignore_index=True)
    treated = pipelines[4].preprocessor.transform_frame(raw_template_frame.loc[:, source_order])

    transition_eval = json.loads((BASELINE_BUNDLE / "transition-evaluation.json").read_text(encoding="utf-8"))
    fold4 = next(row for row in transition_eval["folds"] if row["foldNumber"] == 4)
    transition_path = BASELINE_BUNDLE / fold4["transitionArtifact"]["relativePath"]
    if sha_bytes(transition_path.read_bytes()) != fold4["transitionArtifact"]["sha256"]:
        raise RuntimeError("transition artifact checksum differs")
    transition = bt.TransitionModel.from_dict(json.loads(transition_path.read_text(encoding="utf-8")))
    provider = V18StateProbabilityProvider(
        pipeline=pipelines[4], away_batters=side_batters["AWAY"], home_batters=side_batters["HOME"],
        away_starter=pitcher_evidence[away_starter_id], home_starter=pitcher_evidence[home_starter_id],
        away_bullpen=away_bullpen, home_bullpen=home_bullpen, temperature=None,
    )
    convergence = []
    simulations = {}
    simulation_runtimes = {}
    for count in (5000, 10000):
        print(json.dumps({"stage": "PROSPECTIVE_SIMULATION", "simulations": count}), flush=True)
        simulation_started = time.perf_counter()
        simulations[count] = simulate_prospective_game(
            game_id=snapshot["game"]["game_id"], provider=provider, transition_model=transition,
            n_sims=count, master_seed=MASTER_SEED, regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=1,
        )
        simulation_runtimes[count] = time.perf_counter() - simulation_started
    delta_p = abs(simulations[5000]["homeWinProbability"] - simulations[10000]["homeWinProbability"])
    delta_total = abs(simulations[5000]["meanTotalRuns"] - simulations[10000]["meanTotalRuns"])
    selected_count = 5000 if delta_p <= 0.01 and delta_total <= 0.15 else 20000
    if selected_count == 20000:
        print(json.dumps({"stage": "PROSPECTIVE_SIMULATION", "simulations": 20000}), flush=True)
        simulation_started = time.perf_counter()
        simulations[20000] = simulate_prospective_game(
            game_id=snapshot["game"]["game_id"], provider=provider, transition_model=transition,
            n_sims=20000, master_seed=MASTER_SEED, regulation=int(snapshot["game"].get("scheduled_innings") or 9), trace_count=1,
        )
        simulation_runtimes[20000] = time.perf_counter() - simulation_started
    convergence = {"countsEvaluated": sorted(simulations), "delta5000To10000": {"homeWinProbability": delta_p, "meanTotalRuns": delta_total},
                   "thresholds": {"homeWinProbability": 0.01, "meanTotalRuns": 0.15}, "selectedCount": selected_count,
                   "runtimeSecondsByCount": {str(key): value for key, value in simulation_runtimes.items()}}
    selected = simulations[selected_count]
    replay_a = simulate_prospective_game(game_id="replay-fixture", provider=provider, transition_model=transition, n_sims=256, master_seed=MASTER_SEED, trace_count=1)
    replay_b = simulate_prospective_game(game_id="replay-fixture", provider=provider, transition_model=transition, n_sims=256, master_seed=MASTER_SEED, trace_count=1)
    replay_equal = all(np.array_equal(replay_a[name], replay_b[name]) for name in ("awayRuns", "homeRuns", "innings", "paCounts")) and replay_a["traces"] == replay_b["traces"]
    if not replay_equal or selected["nonterminationCount"] or selected["illegalStateCount"]:
        raise RuntimeError("simulation integrity checks failed")

    fold1_transition_path = BASELINE_BUNDLE / next(row for row in transition_eval["folds"] if row["foldNumber"] == 1)["transitionArtifact"]["relativePath"]
    print(json.dumps({"stage": "ORACLE_MECHANICS_DIAGNOSTIC", "games": 10, "simulationsPerGame": 5000}), flush=True)
    oracle_started = time.perf_counter()
    oracle = oracle_evaluation(
        authority.eda_authority,
        development,
        oof,
        bt.TransitionModel.from_dict(json.loads(fold1_transition_path.read_text(encoding="utf-8"))),
    )
    oracle["runtimeSeconds"] = time.perf_counter() - oracle_started

    staging = ROOT / ".runtime/asp-model-studio/v18-whole-game-challenger" / f"build-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    write_json(staging / "calibration.json", calibration)
    write_json(staging / "aisp-pregame-snapshot.json", snapshot)
    raw_template_frame.to_parquet(staging / "prospective-raw-246.parquet", index=False)
    treated.to_parquet(staging / "prospective-treated-273.parquet", index=False)
    write_json(staging / "template-verification.json", {"folds": fixture, "coldStartFallbacks": cold_fallbacks,
        "rawRows": len(raw_template_frame), "rawInputs": 246, "treatedInputs": 273,
        "sourceMaximumDate": "2026-08-13", "finalOotFeatureRowsRead": 0})
    prospective = compact_simulation(selected) | {
        "track": "PROSPECTIVE_RESEARCH_SHADOW", "capturedAt": snapshot["capturedAt"],
        "scheduledStart": snapshot["game"]["starts_at"], "lineupModes": [s["lineupAuthority"]["status"] for s in snapshot["sides"]],
        "paFold": 5, "transitionFold": 4, "calibration": "RAW_V18_SELECTED",
        "convergence": convergence, "deterministicReplayVerified": replay_equal,
    }
    write_json(staging / "prospective-forecast.json", prospective)
    write_json(staging / "oracle-mechanics-evaluation.json", oracle)
    inventory = {
        "scheduleStartVenue": {"status": "USED", "source": "AISP persisted game/game-state authority", "asOf": snapshot["capturedAt"]},
        "lineups": {"status": "USED_PROJECTED", "source": "AISP most recent prior complete confirmed lineup", "asOf": snapshot["capturedAt"]},
        "startersAndHands": {"status": "USED_PROBABLE", "source": "AISP MLB_STATS_API observations", "asOf": snapshot["capturedAt"]},
        "roster": {"status": "AVAILABLE_NOT_NEEDED_AFTER_LINEUP_SELECTION", "count": snapshot["inventoryCounts"]["roster_observations"]},
        "playerTalent": {"status": "USED_V18_DEVELOPMENT_CARRY_FORWARD", "maximumDate": "2026-08-13"},
        "parkWeather": {"status": "OBSERVED_BUT_V18_HAS_NO_DIRECT_EXECUTABLE_BINDING", "weather": snapshot.get("weather")},
        "bullpen": {"status": "MODEL_STUDIO_TEAM_STAFF_DISTRIBUTION_BASELINE", "AispAvailability": "UNAVAILABLE", "awayMembers": len(away_bullpen), "homeMembers": len(home_bullpen)},
        "recentWorkload": {"status": "UNAVAILABLE_NOT_FABRICATED"},
    }
    write_json(staging / "authority-inventory.json", inventory)
    handoff = {
        "schemaVersion": "AISP_MLB_V18_RESEARCH_SHADOW_HANDOFF_V1",
        "registrationState": "READY_FOR_AISP_AGENT_REGISTRATION_NOT_REGISTERED",
        "sport": "MLB", "season": 2026, "status": "RESEARCH_SHADOW", "promotionStatus": "NOT_PROMOTED",
        "executionAllowed": False, "wageringAuthority": False, "marketDataRequired": False,
        "forecastFile": "prospective-forecast.json", "pregameEvidenceFile": "aisp-pregame-snapshot.json",
        "paModelFile": "executable/v18-pa-fold5.joblib",
        "transitionModelFile": "executable/transition-fold4.json",
        "implementationFile": "executable/implementation/mlb_v18_whole_game_challenger.py",
        "requiredConsumerChecks": ["bundle checksum", "game identity", "capture before start", "researchShadowOnly", "executionAllowed=false", "zero illegal and nontermination counts"],
        "registrationInstruction": "AISP agent should add a narrow MLB V18 shadow-import contract/adapter, copy this immutable bundle by checksum, create a distinct research-shadow forecast track, and must not mutate Gen1 forecasts, experiments, positions, or promotion state.",
    }
    write_json(staging / "aisp-handoff.json", handoff)
    executable = staging / "executable"
    executable.mkdir()
    selected_model_path = RUNTIME / model_records[4]["relativePath"]
    shutil.copy2(selected_model_path, executable / "v18-pa-fold5.joblib")
    shutil.copy2(transition_path, executable / "transition-fold4.json")
    implementation = executable / "implementation"
    implementation.mkdir()
    shutil.copy2(ROOT / "server/sports_current_statcast/mlb_v18_whole_game_challenger.py", implementation / "mlb_v18_whole_game_challenger.py")
    shutil.copy2(ROOT / "server/sports_phase5/base_out_transition.py", implementation / "base_out_transition.py")
    shutil.copy2(ROOT / "server/sports_phase5/whole_game_monte_carlo.py", implementation / "whole_game_monte_carlo.py")
    artifacts = [file_record(path, staging) for path in sorted(staging.iterdir()) if path.is_file()]
    executable_artifacts = [
        file_record(path, staging) for path in sorted(executable.rglob("*")) if path.is_file()
    ]
    artifacts.extend(executable_artifacts)
    manifest_body = {
        "schemaVersion": "MLB_V18_WHOLE_GAME_CHALLENGER_BUNDLE_V1",
        "verdict": "V18_WHOLE_GAME_CHALLENGER_BUNDLED_FOR_AISP_RESEARCH_SHADOW",
        "branch": "codex/mlb-governed-prior-engine-v1", "acceptedCommits": ["a24d3145e70db3690cb2b251c2f626b2b8360c19", "a372855d3e8c2780e54fd829de36dd2e033a1049"],
        "paModels": model_records, "selectedPaFold": 5,
        "calibrationDecision": calibration["decision"], "transition": {"selectedFold": 4, "sha256": fold4["transitionArtifact"]["sha256"]},
        "featureContract": {"rawInputs": 246, "treatedInputs": 273, "treatmentSpecificationId": "stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638", "manifestSha256": "4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3"},
        "simulation": {"count": selected_count, "masterSeed": MASTER_SEED, "policy": "TRANSPARENT_STARTER_HOOK_PLUS_PREGAME_TEAM_STAFF_DISTRIBUTION"},
        "executionPayload": executable_artifacts,
        "executionRuntimeSecondsBeforeManifest": time.perf_counter() - started,
        "evidenceTracks": {"oracleGames": oracle["games"], "prospectiveGames": 1, "mixed": False},
        "identityCrosswalk": crosswalk_evidence, "limitations": [
            "projected lineups are carried from the most recent prior complete lineup",
            "no bench or substitution model; batting order remains fixed",
            "no AISP bullpen workload observations; Development team staff distribution is used",
            "V18 contextual features are carried forward from Development evidence through 2026-08-13",
            "prospective PA uses saved fold 5 and transition uses latest available fitted fold 4; no full-Development refit",
            "oracle evaluation averages realized game-local fold-1 OOF PA probabilities and is not a deployable pregame estimate",
        ],
        "finalOot": {"locked": True, "featurePayloadRowsRead": 0, "targetsRead": 0, "scored": False},
        "aisp": {"modified": False, "registration": "HANDOFF_READY"},
        "artifacts": artifacts,
    }
    bundle_sha = sha_bytes(json_bytes(manifest_body))
    manifest = {**manifest_body, "bundleId": f"mlb-v18-whole-game-{bundle_sha[:24]}", "bundleSha256": bundle_sha}
    write_json(staging / "manifest.json", manifest)
    target = OUTPUT / "sha256" / bundle_sha
    if target.exists():
        shutil.rmtree(staging)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        staging.replace(target)
    reloaded = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    if sha_bytes(json_bytes({k: v for k, v in reloaded.items() if k not in {"bundleId", "bundleSha256"}})) != bundle_sha:
        raise RuntimeError("bundle reload checksum failed")
    latest = OUTPUT / "latest.json"
    write_json(latest, {"bundleId": manifest["bundleId"], "bundleSha256": bundle_sha, "relativePath": target.relative_to(ROOT).as_posix()})
    print(json.dumps({"verdict": manifest["verdict"], "bundleId": manifest["bundleId"], "bundleSha256": bundle_sha,
                      "path": str(target), "calibration": calibration["decision"], "prospectiveGames": 1,
                      "oracleGames": oracle["games"], "simulations": selected_count,
                      "runtimeSeconds": time.perf_counter()-started}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
