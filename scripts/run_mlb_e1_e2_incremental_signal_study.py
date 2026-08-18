"""run-mlb-e1-e2-incremental-signal-study — Phase 4E controlled feature ablation.

Trains D3 vs D3+E1 vs D3+E1+E2 under an identical 549,479-PA population, identical
fold-local preprocessing, and the identical fixed D3 regularization (C=0.05 multinomial
l2 logistic). It performs NO grid search, NO algorithm tournament, NO hyperparameter or
class-weight tuning, NO label-based feature selection, NO calibration search, and trains
no E6/archetype features. 2025 is a frozen rolling-origin evaluation, never a selection
fold. Branch A reproduces the frozen D3 log loss (2024=1.476588, 2025=1.474100) as a
correctness anchor before any E1/E2 verdict is emitted.

Inputs are read only from already-registered governed authorities:
  * the local D3 PA feature view + dynamic-state materializations (frozen),
  * the local E1/E2 content-addressed feature parquets (SHA-verified), and
  * the registered FD1 identity-bridge alias parquet (retrosheet <-> canonical uuid).
No provider calls, no network, no new data acquisition. Idempotent: an identical set of
authorities + code revision reuses the completed study artifact.
"""

from __future__ import annotations

import argparse
import datetime
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from server.sports_modeling.metrics import PA_CLASS_ORDER, encode_labels  # noqa: E402
from server.sports_modeling.training import TrainingArrays  # noqa: E402
from server.sports_phase4.dynamic_contract import STATE_VALUE_COLUMNS  # noqa: E402
from server.sports_phase4 import incremental_signal_study as study  # noqa: E402

RUNTIME_ROOT = REPOSITORY_ROOT / ".runtime" / "asp-model-studio"
OUTPUT_ROOT = RUNTIME_ROOT / "sports-phase4" / "e1-e2-incremental-signal-study"
CONTRACT_PATH = REPOSITORY_ROOT / "docs" / "contracts" / "MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_V1.md"
DEFAULT_EXCHANGE_ROOT = Path(r"C:/Users/james/asp-model-exchange")
FV_SHA = "42884747dfb610564bf0c85ab30f6c16d09b2a01982ddbc4e9ccb485f2ddb53f"
STATE_SHA = "6117988df812bb35dc0fdafd7f8b78d0c0a62a8454e598e4271f2da148bf3b03"
BRIDGE_MANIFEST_SHA = "1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49"
_STARTED = time.monotonic()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _hb(stage: str, evidence: Mapping[str, Any]) -> None:
    print(f"[e1e2-study] {int(time.monotonic() - _STARTED):>5}s | {stage} | "
          + " ".join(f"{k}={v}" for k, v in evidence.items()), flush=True)


def _progress(stage: str, evidence: Mapping[str, Any]) -> None:
    _hb(stage, evidence)


def _resolve_object(sha: str, filename: str) -> Path:
    hits = glob.glob(str(RUNTIME_ROOT / "**" / "objects" / "sha256" / sha[:2] / sha / filename), recursive=True)
    if not hits:
        raise RuntimeError(f"could not resolve local object {filename} sha256:{sha[:16]}")
    return Path(hits[0])


def _resolve_feature_family(subdir: str) -> tuple[Path, dict[str, Any]]:
    pointer = OUTPUT_ROOT.parent / subdir / "latest.audit.json"
    record = json.loads(pointer.read_text(encoding="utf-8"))
    audit = record["audit"]
    art = audit["featureArtifact"]
    path = OUTPUT_ROOT.parent / subdir / Path(art["logicalUri"].split("/")[-1])
    observed = hashlib.sha256(path.read_bytes()).hexdigest()
    if observed != art["sha256"]:
        raise RuntimeError(f"{subdir} feature parquet SHA mismatch: {observed} != {art['sha256']}")
    return path, audit


def _alias_map(exchange_root: Path) -> dict[str, str]:
    pattern = str(exchange_root / "identity-bridges" / "mlb-fd1" / f"manifest-sha256-{BRIDGE_MANIFEST_SHA}" / "**" / "player-identity-aliases.parquet")
    hits = glob.glob(pattern, recursive=True)
    if not hits:
        raise RuntimeError("registered identity-bridge alias parquet not found under exchange root")
    al = pq.read_table(hits[0], columns=["canonical_player_uuid", "namespace", "source_player_id"]).to_pandas()
    rs = al[al["namespace"] == "RETROSHEET"].copy()
    rs["rid"] = "retrosheet:player:" + rs["source_player_id"].astype(str)
    if rs["rid"].duplicated().any() or rs["canonical_player_uuid"].duplicated().any():
        raise RuntimeError("retrosheet alias map is not 1:1")
    return dict(zip(rs["rid"], rs["canonical_player_uuid"]))


def _build_aligned_frame(exchange_root: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    fv_path = _resolve_object(FV_SHA, "mlb-pa-feature-view-v1.parquet")
    st_path = _resolve_object(STATE_SHA, "mlb-dynamic-player-state-v1.parquet")
    fv = pq.read_table(fv_path).to_pandas()
    st = pq.read_table(st_path).to_pandas()
    _hb("LOADED_D3_INPUTS", {"paRows": len(fv), "stateRows": len(st)})

    # --- D3 state features (context + batter_b + pitcher_b), one-to-one join ---
    def state_cols(role: str) -> pd.DataFrame:
        sub = st[(st["role"] == role) & (st["state_kind"] == "B_CUMULATIVE")]
        ren = {name: f"{role.lower()}_b_{name}" for name in STATE_VALUE_COLUMNS}
        return sub[["game_date", "season", "canonical_player_uuid", *STATE_VALUE_COLUMNS]].rename(
            columns={"canonical_player_uuid": f"{role.lower()}_state_uuid", **ren}
        )

    before = len(fv)
    fv = fv.merge(state_cols("BATTER"), left_on=["game_date", "season", "batter_canonical_player_uuid"],
                  right_on=["game_date", "season", "batter_state_uuid"], how="left")
    fv = fv.merge(state_cols("PITCHER"), left_on=["game_date", "season", "pitcher_canonical_player_uuid"],
                  right_on=["game_date", "season", "pitcher_state_uuid"], how="left")
    if len(fv) != before:
        raise RuntimeError(f"D3 state join changed row count {before} -> {len(fv)}")
    non_dse = [f"{r}_b_{n}" for r in ("batter", "pitcher") for n in STATE_VALUE_COLUMNS if n != "days_since_evidence"]
    state_join_misses = int(fv[non_dse].isna().any(axis=1).sum())
    if state_join_misses:
        raise RuntimeError(f"D3 state join left {state_join_misses} unmatched target rows")
    _hb("JOINED_D3_STATE", {"rows": len(fv), "joinMisses": 0})

    # --- Attach E1 / E2 via the registered identity bridge (per player/date) ---
    rs2uuid = _alias_map(exchange_root)
    e1_path, e1_audit = _resolve_feature_family("pitch-sequence-features")
    e2_path, e2_audit = _resolve_feature_family("process-interactions")
    e1 = pq.read_table(e1_path).to_pandas()
    e2 = pq.read_table(e2_path).to_pandas()
    e1["b_uuid"] = e1["batter_id"].map(rs2uuid)
    e1["p_uuid"] = e1["pitcher_id"].map(rs2uuid)
    e2["b_uuid"] = e2["batter_id"].map(rs2uuid)
    e2["p_uuid"] = e2["pitcher_id"].map(rs2uuid)
    if e1[["b_uuid", "p_uuid"]].isna().any().any() or e2[["b_uuid", "p_uuid"]].isna().any().any():
        raise RuntimeError("E1/E2 retrosheet ids did not fully resolve to canonical uuids")

    e1_batter = [c for c in e1.columns if c.startswith("batter_") and c != "batter_id"]
    e1_pitcher = [c for c in e1.columns if c.startswith("pitcher_") and c != "pitcher_id"]
    e2_features = [c for c in e2.columns if c not in ("batter_id", "pitcher_id", "season", "_ord", "b_uuid", "p_uuid")]

    # Join-success markers -- E1/E2 feature VALUES may be legitimately NaN for
    # missing-history players, so join coverage is measured by the marker, not a value.
    batter_lookup = e1.drop_duplicates(["b_uuid", "_ord"])[["b_uuid", "_ord", *e1_batter]].assign(_e1b_hit=1)
    pitcher_lookup = e1.drop_duplicates(["p_uuid", "_ord"])[["p_uuid", "_ord", *e1_pitcher]].assign(_e1p_hit=1)
    e2_lookup = e2.drop_duplicates(["b_uuid", "p_uuid", "_ord"])[["b_uuid", "p_uuid", "_ord", *e2_features]].assign(_e2_hit=1)

    fv["_ord"] = pd.to_datetime(fv["game_date"]).map(
        lambda t: datetime.date(t.year, t.month, t.day).toordinal()
    ).astype("int64")

    before = len(fv)
    fv = fv.merge(batter_lookup, left_on=["batter_canonical_player_uuid", "_ord"], right_on=["b_uuid", "_ord"], how="left")
    fv = fv.merge(pitcher_lookup, left_on=["pitcher_canonical_player_uuid", "_ord"], right_on=["p_uuid", "_ord"], how="left")
    fv = fv.merge(e2_lookup, left_on=["batter_canonical_player_uuid", "pitcher_canonical_player_uuid", "_ord"],
                  right_on=["b_uuid", "p_uuid", "_ord"], how="left", suffixes=("", "_e2"))
    if len(fv) != before:
        raise RuntimeError(f"E1/E2 attach changed row count {before} -> {len(fv)} (fan-out)")

    e1_match = int(((fv["_e1b_hit"] == 1) & (fv["_e1p_hit"] == 1)).sum())
    e2_match = int((fv["_e2_hit"] == 1).sum())
    _hb("ATTACHED_E1_E2", {"rows": len(fv), "e1Match": e1_match, "e2Match": e2_match})

    lineage = {
        "population": {
            "paFeatureViewSha256": FV_SHA,
            "rowCount": int(len(fv)),
            "seasons": {str(int(s)): int((fv["season"] == s).sum()) for s in sorted(fv["season"].unique())},
        },
        "d3StateSha256": STATE_SHA,
        "e1": {
            "materializationId": e1_audit["materializationId"],
            "featureSha256": e1_audit["featureArtifact"]["sha256"],
            "numericFeatureCount": len(e1_batter) + len(e1_pitcher),
            "matchRate": e1_match / len(fv),
        },
        "e2": {
            "materializationId": e2_audit["materializationId"],
            "featureSha256": e2_audit["featureArtifact"]["sha256"],
            "featureCount": len(e2_features),
            "matchRate": e2_match / len(fv),
        },
        "e1Features": e1_batter + e1_pitcher,
        "e2Features": e2_features,
        "e1E2AttachMethod": "IDENTITY_BRIDGE_RETROSHEET_TO_UUID_PER_PLAYER_DATE_LOOKUP_NO_FANOUT",
    }
    return fv, lineage


def _arrays(fv: pd.DataFrame, lineage: Mapping[str, Any]) -> TrainingArrays:
    feature_cols = list(study.D3_FEATURES) + list(lineage["e1Features"]) + list(lineage["e2Features"])
    feature_values = {name: fv[name].to_numpy(dtype=np.float64) for name in feature_cols}
    labels = fv["outcome"].to_numpy(dtype=object)
    return TrainingArrays(
        feature_values=feature_values,
        labels=labels,
        encoded_labels=encode_labels(labels),
        seasons=fv["season"].to_numpy(dtype=np.int64),
        game_dates=fv["game_date"].to_numpy(dtype=object),
        game_ids=fv["game_id"].to_numpy(dtype=object),
        plate_appearance_ids=fv["plate_appearance_id"].to_numpy(dtype=object),
    )


def _dataset_authority() -> dict[str, Any]:
    from server.persistence.db import Database
    from server.sports_datasets.registry import SportsDatasetRegistry
    db_path = RUNTIME_ROOT / "persistence" / "asp_model_studio.db"
    db = Database(db_path)
    db.initialize()
    active = SportsDatasetRegistry(db).get_active()
    if not active:
        raise RuntimeError("no active FD1 dataset registration")
    return {
        "registrationId": active["registration_id"],
        "datasetId": active["dataset_id"],
        "manifestSha": active["manifest_sha"],
    }


def _run(args: argparse.Namespace) -> int:
    exchange_root = Path(args.exchange_root or os.getenv("ASP_MODEL_EXCHANGE_ROOT", "") or DEFAULT_EXCHANGE_ROOT)
    if not exchange_root.exists():
        print(f"exchange root not found: {exchange_root}", file=sys.stderr)
        return 2
    dataset_authority = _dataset_authority()
    code_revision = os.getenv("ASP_MODEL_STUDIO_CODE_REVISION", "").strip() or "worktree:e1-e2-incremental-signal-study"
    contract_sha = hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() if CONTRACT_PATH.exists() else ""

    e1_path, e1_audit = _resolve_feature_family("pitch-sequence-features")
    e2_path, e2_audit = _resolve_feature_family("process-interactions")
    run_id = "e1-e2-incremental-signal-study-" + _sha({
        "contractName": study.STUDY_CONTRACT_NAME, "contractSha": contract_sha,
        "paFeatureViewSha": FV_SHA, "stateSha": STATE_SHA,
        "e1": e1_audit["featureArtifact"]["sha256"], "e2": e2_audit["featureArtifact"]["sha256"],
        "C": study.FIXED_C, "seed": study.BOOTSTRAP_SEED, "resamples": args.resamples,
        "codeRevision": code_revision,
    })[:16]
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    completed = OUTPUT_ROOT / f"{run_id}.study.json"

    if args.status:
        print(json.dumps({"runId": run_id, "completed": completed.exists()}))
        return 0
    if completed.exists() and not args.force:
        record = json.loads(completed.read_text(encoding="utf-8"))
        _hb("REUSED_COMPLETED_STUDY", {"runId": run_id})
        _emit(record["study"], reused=True)
        return 0
    if args.preflight_only:
        _hb("PREFLIGHT_COMPLETE", {"runId": run_id, "e1": e1_audit["materializationId"], "e2": e2_audit["materializationId"]})
        return 0

    fv, lineage = _build_aligned_frame(exchange_root)
    arrays = _arrays(fv, lineage)
    labels_by_season = {s: arrays.labels[arrays.seasons == s] for s in (2024, 2025)}
    game_ids_by_season = {s: arrays.game_ids[arrays.seasons == s] for s in (2024, 2025)}

    branches: dict[str, study.BranchFolds] = {}
    for branch_id in ("A", "B", "C"):
        names = study.branch_feature_names(branch_id, lineage["e1Features"], lineage["e2Features"])
        branches[branch_id] = study.train_branch(arrays, branch_id, names, progress=_progress)
        m = branches[branch_id].metrics
        _hb("BRANCH_COMPLETE", {"branch": branch_id, "features": len(names),
                                "logLoss2024": round(m[2024]["logLoss"], 6), "logLoss2025": round(m[2025]["logLoss"], 6),
                                "nIter2024": branches[branch_id].n_iter[2024], "nIter2025": branches[branch_id].n_iter[2025]})

    anchor = study.verify_branch_a_anchor(branches["A"])
    if not anchor["reproducedBothFolds"]:
        raise RuntimeError(f"Branch A did NOT reproduce frozen D3 log loss: {anchor}")
    _hb("ANCHOR_VERIFIED", {"reproduced": anchor["reproducedBothFolds"]})

    incremental = study.incremental_table(branches, labels_by_season)
    classwise = study.classwise_table(branches, labels_by_season)
    strikeout = study.focused_class_analysis("STRIKEOUT", branches, labels_by_season)
    walk = study.focused_class_analysis("WALK_HBP_CI", branches, labels_by_season)
    rare = {name: study.focused_class_analysis(name, branches, labels_by_season)
            for name in ("HOME_RUN", "DOUBLE", "TRIPLE", "OTHER_REACH")}
    catastrophic = study.catastrophic_analysis(branches, labels_by_season)
    bootstrap = study.bootstrap_comparisons(branches, labels_by_season, game_ids_by_season,
                                            n_resamples=args.resamples, progress=_progress)
    decision = study.decide_feature_value(incremental, bootstrap, strikeout)
    next_step = study.next_step_path(decision)

    study_payload = {
        "schemaVersion": study.STUDY_SCHEMA_VERSION,
        "contractName": study.STUDY_CONTRACT_NAME,
        "contractSha": contract_sha,
        "studyId": run_id,
        "datasetAuthority": dataset_authority,
        "researchOnly": True,
        "promotedModel": False,
        "changesChampionStatus": False,
        "modelPolicy": {
            "estimator": "sklearn.linear_model.LogisticRegression",
            "multiclass": "TRUE_MULTINOMIAL", "penalty": "l2", "solver": "lbfgs",
            "C": study.FIXED_C, "gridSearch": False, "classWeight": None,
            "preprocessing": "FOLD_LOCAL_MEAN_IMPUTE_STANDARDIZE_FIXED_ONE_HOT",
            "tuning": "NONE_FIXED_D3_POLICY",
        },
        "temporalProtocol": {
            "developmentSeason": 2023, "selectionSeason": 2024, "frozenFinalSeason": 2025,
            "note": "Fixed policy: no selection performed; 2025 is rolling-origin evaluation only.",
        },
        "population": lineage["population"],
        "lineage": lineage,
        "branchFeatureCounts": {b: len(branches[b].feature_names) for b in ("A", "B", "C")},
        "branchRuntimeSeconds": {b: branches[b].runtime_seconds for b in ("A", "B", "C")},
        "branchConvergence": {b: {"nIter2024": branches[b].n_iter[2024], "nIter2025": branches[b].n_iter[2025]} for b in ("A", "B", "C")},
        "branchMetrics": {b: {str(s): branches[b].metrics[s] for s in (2024, 2025)} for b in ("A", "B", "C")},
        "anchor": anchor,
        "incrementalTable": incremental,
        "classwise": classwise,
        "strikeout": strikeout,
        "walkHbpCi": walk,
        "rareOutcomes": rare,
        "catastrophic": catastrophic,
        "bootstrap": bootstrap,
        "decision": decision,
        "nextStep": next_step,
        "limitations": [
            "Feature ablation only under one fixed model family and fixed C=0.05; no algorithm or hyperparameter search was performed.",
            "Raw model outputs are used for the feature-value verdict; no temperature scaling or calibration search was applied.",
            "E1/E2 attach to the D3 population via the registered identity bridge as a pure per-(player,date) lookup; feature values are identical to a direct E1/E2 materialization on this population.",
            "Predictive value and materialization readiness are separate; this study does not change any feature-family readiness status.",
        ],
    }
    audit_sha = _sha(study_payload)
    record = {
        "schemaVersion": "MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_ARTIFACT_V1",
        "studyId": run_id, "studySha": audit_sha, "codeRevision": code_revision,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "study": study_payload,
    }
    for pointer in (completed, OUTPUT_ROOT / "latest.study.json"):
        tmp = pointer.with_suffix(".tmp")
        tmp.write_bytes(_canonical(record))
        os.replace(tmp, pointer)
    _hb("REGISTERED_STUDY_ARTIFACT", {"studySha": audit_sha[:16], "runId": run_id})
    _emit(study_payload, reused=False)
    return 0


def _emit(study_payload: Mapping[str, Any], *, reused: bool) -> None:
    d = study_payload["decision"]
    ns = study_payload["nextStep"]
    print("COMPLETED" + (" (reused)" if reused else "")
          + f" e1={d['e1']['decision']} e2={d['e2']['decision']} path={ns['recommendedPath']}"
          + f" anchorReproduced={study_payload['anchor']['reproducedBothFolds']}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4E controlled E1/E2 incremental-signal feature-ablation study.")
    parser.add_argument("--exchange-root", default=os.getenv("ASP_MODEL_EXCHANGE_ROOT", ""))
    parser.add_argument("--resamples", type=int, default=study.BOOTSTRAP_RESAMPLES)
    parser.add_argument("--estimate-only", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.estimate_only:
        print(json.dumps({
            "schemaVersion": "MLB_E1_E2_INCREMENTAL_SIGNAL_STUDY_ESTIMATE_V1", "estimateOnly": True,
            "estimatedSecondsLower": 300, "estimatedSecondsUpper": 1800,
            "assumptions": ["reuses frozen D3 inputs + E1/E2 parquets", "6 fixed-C logistic fits", "500-replicate whole-game bootstrap", "no grid search, no tuning"],
        }, sort_keys=True))
        return 0
    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
