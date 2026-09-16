"""Phase 7A Gate 6 — GOVERNED baseline equivalence + physically-blinded A0/A1/A2.

Reads ONLY the immutable Gen-3 research object (2021-2024). The sealed 2025 object is never opened; there
is NO CLI flag to score it. Uses the exact governed Gen-2 pipeline: FoldPreprocessor (fold-training-only
mean imputation + standardization), one-hot categorical context, multinomial lbfgs logistic with C
selected over the frozen C_GRID via a chronological development-only inner split, fail-closed on
non-convergence, effective hyperparameters + n_iter captured. HGB uses NO random early stopping
(deterministic). A paired whole-game bootstrap on 2024 quantifies uncertainty.

Reproduction gate: governed A0 (dev=2023) must reproduce the registered raw Gen-2 2024 logistic log loss
(~1.484255) within a predeclared tolerance; otherwise the gate FAILS and A1/A2 are not interpreted as
volume effects. Persists immutable prediction/metric/bootstrap evidence bound to the research object SHA
+ contract bundle SHA + code revision.
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import pyarrow.parquet as pq
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression

from server.sports_modeling.feature_contract import C_GRID, FEATURE_NAMES
from server.sports_modeling.training import FoldPreprocessor, DEFAULT_MAX_ITER, DEFAULT_TOLERANCE, chronological_date_atomic_split
from server.sports_modeling.metrics import PA_CLASS_ORDER, encode_labels, evaluate_multiclass
from server.sports_modeling import gen3_contracts as C
from server.sports_modeling.gen3_publish import _code_revision, _dependency_versions

AUTHORITY = REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v2"
GOVERNED_GEN2_RAW_2024_LOGLOSS = 1.484255   # registered raw C4 comparator (Codex-verified)
REPRODUCTION_TOLERANCE = 1.0e-3             # predeclared
VAL_SEASON = 2024


def _research_object() -> Path:
    reg = json.loads((AUTHORITY / "registration.json").read_text())
    sha = reg["research"]["logicalContentSha256"]
    return AUTHORITY / "objects" / "sha256" / sha / "research.parquet", sha, reg["contractBundleSha256"]


def _load_research():
    path, sha, bundle = _research_object()
    table = pq.read_table(path)
    seasons = np.asarray(table["season"].to_pylist(), dtype=np.int64)
    present = sorted(set(int(s) for s in seasons))
    if 2025 in present or 2026 in present:
        raise SystemExit("SEALED SEASON PRESENT IN RESEARCH FRAME — blinding violation")
    fv = {name: np.asarray(table[name].to_pylist(), dtype=np.float64) for name in FEATURE_NAMES}
    labels = np.asarray(table["outcome"].to_pylist(), dtype=object)
    game_dates = np.asarray(table["game_date"].to_pylist(), dtype=object)
    game_ids = np.asarray(table["game_id"].to_pylist(), dtype=object)
    return dict(fv=fv, labels=labels, encoded=encode_labels(labels), seasons=seasons,
                game_dates=game_dates, game_ids=game_ids, present=present, sha=sha, bundle=bundle)


def _fit_governed_logistic(fv, encoded, train_mask, c_value):
    pre = FoldPreprocessor.fit(fv, FEATURE_NAMES, train_mask)
    X = pre.transform(fv, train_mask)
    y = encoded[train_mask]
    if np.unique(y).size != len(PA_CLASS_ORDER):
        raise SystemExit("every class must occur in each training fold")
    est = LogisticRegression(C=float(c_value), penalty="l2", solver="lbfgs",
                             max_iter=DEFAULT_MAX_ITER, tol=DEFAULT_TOLERANCE, fit_intercept=True,
                             class_weight=None, random_state=None)
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always", ConvergenceWarning)
        est.fit(X, y)
    n_iter = int(np.max(est.n_iter_))
    converged = not (any(issubclass(w.category, ConvergenceWarning) for w in observed) or n_iter >= DEFAULT_MAX_ITER)
    if not converged:
        raise SystemExit(f"GATE 6 FAIL-CLOSED: logistic did not converge (n_iter={n_iter}/{DEFAULT_MAX_ITER})")
    return pre, est, n_iter


def _governed_logistic_branch(data, dev_seasons):
    fv, encoded, seasons, dates = data["fv"], data["encoded"], data["seasons"], data["game_dates"]
    dev_mask = np.isin(seasons, dev_seasons)
    val_mask = seasons == VAL_SEASON
    # C selection via chronological development-only inner split (governed policy).
    inner_train, inner_val, split_ev = chronological_date_atomic_split(dates, dev_mask, training_fraction=0.8)
    tuning = []
    for c in C_GRID:
        pre, est, n_iter = _fit_governed_logistic(fv, encoded, inner_train, c)
        proba = est.predict_proba(pre.transform(fv, inner_val))
        m = evaluate_multiclass(data["labels"][inner_val], proba)
        tuning.append({"C": float(c), "logLoss": m["logLoss"], "brier": m["brierScore"], "nIter": n_iter})
    winner = min(tuning, key=lambda t: (t["logLoss"], t["brier"], t["C"]))
    pre, est, n_iter = _fit_governed_logistic(fv, encoded, dev_mask, winner["C"])
    proba = est.predict_proba(pre.transform(fv, val_mask))
    m = evaluate_multiclass(data["labels"][val_mask], proba)
    return {
        "family": "governed_logistic", "devSeasons": list(dev_seasons), "devRows": int(dev_mask.sum()),
        "selectedC": winner["C"], "nIter": n_iter, "converged": True, "maxIter": DEFAULT_MAX_ITER,
        "tol": DEFAULT_TOLERANCE, "tuning": tuning, "innerSplit": split_ev,
        "logLoss": round(m["logLoss"], 8), "brier": round(m["brierScore"], 8),
        "ece": round(m["topLabelEce"], 8), "top1": round(m["top1Accuracy"], 8), "macroF1": round(m["macroF1"], 8),
    }, proba


def _governed_hgb_branch(data, dev_seasons):
    fv, encoded, seasons = data["fv"], data["encoded"], data["seasons"]
    dev_mask = np.isin(seasons, dev_seasons); val_mask = seasons == VAL_SEASON
    pre = FoldPreprocessor.fit(fv, FEATURE_NAMES, dev_mask)
    est = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, early_stopping=False,
                                         random_state=20260819)  # deterministic, no random inner split
    est.fit(pre.transform(fv, dev_mask), encoded[dev_mask])
    proba = np.zeros((int(val_mask.sum()), len(PA_CLASS_ORDER)))
    proba[:, est.classes_] = est.predict_proba(pre.transform(fv, val_mask))
    m = evaluate_multiclass(data["labels"][val_mask], proba)
    return {"family": "governed_hgb", "devSeasons": list(dev_seasons), "devRows": int(dev_mask.sum()),
            "earlyStopping": False, "nIter": int(est.n_iter_), "maxIter": 200,
            "logLoss": round(m["logLoss"], 8), "brier": round(m["brierScore"], 8),
            "top1": round(m["top1Accuracy"], 8), "macroF1": round(m["macroF1"], 8)}


def _paired_game_bootstrap(data, proba_a, proba_b, n=2000, seed=20260819):
    """PA-weighted mean logloss delta (a-b) over 2024 games resampled with replacement (paired)."""
    seasons = data["seasons"]; val_mask = seasons == VAL_SEASON
    enc = data["encoded"][val_mask]; games = data["game_ids"][val_mask]
    eps = 1e-15
    ll_a = -np.log(np.clip(proba_a[np.arange(len(enc)), enc], eps, 1))
    ll_b = -np.log(np.clip(proba_b[np.arange(len(enc)), enc], eps, 1))
    diff = ll_a - ll_b
    uniq_games = np.unique(games)
    idx_by_game = {g: np.flatnonzero(games == g) for g in uniq_games}
    rng = np.random.default_rng(seed)
    deltas = np.empty(n)
    observed = float(diff.mean())
    for i in range(n):
        sampled = rng.choice(uniq_games, size=len(uniq_games), replace=True)
        rows = np.concatenate([idx_by_game[g] for g in sampled])
        deltas[i] = float(diff[rows].mean())
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    return {"observedDelta": round(observed, 9), "ci95": [round(float(lo), 9), round(float(hi), 9)],
            "pLeftBetter": round(float(np.mean(deltas < 0)), 4), "replicates": n}


def main() -> int:
    from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)
    # Reads the research object via a BARE runtime path (bypasses the canonical verified_research_object
    # resolver); superseded by the server-authorized canonical 2024-only feature-family comparison.
    retire_2025("server.sports_cockpit.gen3_authority.run_feature_family_ablation (canonical 2024-only research)")
    data = _load_research()
    print(f"[research] seasons present={data['present']} (2025 absent: {2025 not in data['present']})", flush=True)
    branches = {"A0": [2023], "A1": [2022, 2023], "A2": [2021, 2022, 2023]}
    logistic, hgb, probas = {}, {}, {}
    for name, dev in branches.items():
        print(f"[{time.strftime('%H:%M:%S')}] {name} governed logistic dev={dev} …", flush=True)
        logistic[name], probas[name] = _governed_logistic_branch(data, dev)
        print(f"    C={logistic[name]['selectedC']} logLoss={logistic[name]['logLoss']} nIter={logistic[name]['nIter']}", flush=True)
        hgb[name] = _governed_hgb_branch(data, dev)

    a0 = logistic["A0"]["logLoss"]
    repro_diff = abs(a0 - GOVERNED_GEN2_RAW_2024_LOGLOSS)
    repro_pass = repro_diff <= REPRODUCTION_TOLERANCE

    bootstrap = {
        "A1_minus_A0": _paired_game_bootstrap(data, probas["A1"], probas["A0"]),
        "A2_minus_A0": _paired_game_bootstrap(data, probas["A2"], probas["A0"]),
        "A2_minus_A1": _paired_game_bootstrap(data, probas["A2"], probas["A1"]),
    }
    rev, dirty = _code_revision()
    payload = {
        "schemaVersion": "MLB_GEN3_GOVERNED_ABLATION_V1",
        "researchObjectSha256": data["sha"], "contractBundleSha256": data["bundle"],
        "preprocessingContract": C.preprocessing_contract()["id"],
        "codeRevision": rev, "dirtyTree": dirty, "environment": _dependency_versions(),
        "reproductionGate": {"target": GOVERNED_GEN2_RAW_2024_LOGLOSS, "governedA0": a0,
                             "difference": round(repro_diff, 8), "tolerance": REPRODUCTION_TOLERANCE,
                             "pass": bool(repro_pass)},
        "logistic": logistic, "hgb": hgb, "pairedGameBootstrap2024": bootstrap,
        "validationSeason": VAL_SEASON, "sealedSeasonLoaded": False, "seasonsPresent": data["present"],
    }
    (AUTHORITY / "governed-ablation.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"reproductionGate": payload["reproductionGate"],
                      "logistic": {k: {"C": v["selectedC"], "logLoss": v["logLoss"], "nIter": v["nIter"]} for k, v in logistic.items()},
                      "hgb": {k: {"logLoss": v["logLoss"], "nIter": v["nIter"]} for k, v in hgb.items()},
                      "bootstrap": bootstrap}, indent=2))
    if not repro_pass:
        print("GATE 6: REPRODUCTION FAILED — A1/A2 not interpretable as pure volume effects", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
