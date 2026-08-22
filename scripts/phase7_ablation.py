"""Phase 7 — training-volume ablation (Gate 15A) on the Gen-3 base-22 feature view.

Answers the PRIMARY question: does adding 2021/2022 development rows improve 2024 validation?

  A0: development = {2023}            (current Gen-2 baseline)
  A1: development = {2022, 2023}
  A2: development = {2021, 2022, 2023}

Same target, same 22 base features, same fold-local preprocessing (median impute fit on development
only + fixed-category one-hot for the 3 categorical context features), same model families
(multinomial logistic + HistGradientBoosting). Selection metric = 2024 validation only. The 2025
secondary out-of-time season is NEVER scored unless --run-secondary-oot-2025 is passed. 2026 untouched.

Also verifies Gen-3 base-feature PARITY with the frozen Gen-2 view on the overlapping 2023-2025 rows.
Non-destructive: fits nothing into the registry; D3/C4 untouched.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from server.sports_cockpit import engine as E
from server.sports_modeling.metrics import PA_CLASS_ORDER, encode_labels, evaluate_multiclass
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from scripts._retired_2025_guard import retire_2025  # Phase 7D.4 Gate 12 (B8)

GEN3 = REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v1/mlb-pa-gen3-feature-view-v1.parquet"
OUT = REPO / ".runtime/asp-model-studio/sports-modeling/mlb-pa-gen3-v1/phase7-ablation.json"
NUMERIC = [
    "context_inning", "context_batting_score_diff_before",
    "batter_log1p_pa", "batter_avg", "batter_obp", "batter_slg", "batter_so_per_pa",
    "batter_bb_hbp_per_pa", "batter_hr_per_pa", "batter_prior_missing",
    "pitcher_log1p_bfp", "pitcher_era9", "pitcher_whip", "pitcher_so_per_bfp", "pitcher_bb_per_bfp",
    "pitcher_hr_per_bfp", "pitcher_hbp_per_bfp", "pitcher_gs_per_g", "pitcher_prior_missing",
]
CATEG = {"context_top_bottom": [0, 1], "context_outs_before": [0, 1, 2], "context_base_mask_before": list(range(8))}
KEY_CLASSES = ["STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "BIP_OUT"]


def _design(frame: pd.DataFrame, fills: dict) -> np.ndarray:
    cols = []
    for c in NUMERIC:
        v = frame[c].astype("float64").to_numpy()
        v = np.where(np.isfinite(v), v, fills[c])
        cols.append(v.reshape(-1, 1))
    for c, cats in CATEG.items():
        vals = frame[c].to_numpy()
        for cat in cats:
            cols.append((vals == cat).astype("float64").reshape(-1, 1))
    return np.hstack(cols)


def _fit_fills(dev: pd.DataFrame) -> dict:
    fills = {}
    for c in NUMERIC:
        v = dev[c].astype("float64").to_numpy()
        v = v[np.isfinite(v)]
        fills[c] = float(np.median(v)) if v.size else 0.0
    return fills


def _class_conditional_logloss(y_enc: np.ndarray, proba: np.ndarray) -> dict:
    eps = 1e-15
    out = {}
    for i, cls in enumerate(PA_CLASS_ORDER):
        mask = y_enc == i
        if mask.sum() == 0:
            out[cls] = None
            continue
        p = np.clip(proba[mask, i], eps, 1)
        out[cls] = round(float(np.mean(-np.log(p))), 5)
    return out


def _evaluate(dev: pd.DataFrame, val: pd.DataFrame, family: str) -> dict:
    fills = _fit_fills(dev)
    Xd, Xv = _design(dev, fills), _design(val, fills)
    yd = encode_labels(dev["outcome"].to_numpy())
    if family == "logistic":
        est = LogisticRegression(C=1.0, max_iter=2000, solver="lbfgs")
    else:
        est = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.1, random_state=20260819)
    t0 = time.time()
    est.fit(Xd, yd)
    fit_s = round(time.time() - t0, 1)
    # align proba to 8 classes
    proba = np.zeros((len(val), len(PA_CLASS_ORDER)))
    proba[:, est.classes_] = est.predict_proba(Xv)
    yv = encode_labels(val["outcome"].to_numpy())
    m = evaluate_multiclass(val["outcome"].to_numpy(), proba)
    return {
        "family": family, "devRows": int(len(dev)), "valRows": int(len(val)), "fitSeconds": fit_s,
        "logLoss": round(m["logLoss"], 6), "brier": round(m["brierScore"], 6),
        "ece": round(m["topLabelEce"], 6), "top1": round(m["top1Accuracy"], 6),
        "macroF1": round(m["macroF1"], 6),
        "classLogLoss": {k: v for k, v in _class_conditional_logloss(yv, proba).items() if k in KEY_CLASSES},
    }


def main() -> int:
    retire_2025("server.sports_cockpit.gen3_authority.run_feature_family_ablation (canonical 2024-only research)")
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-secondary-oot-2025", action="store_true", help="score the sealed 2025 OOT season")
    args = ap.parse_args()
    if not GEN3.is_file():
        raise SystemExit("Gen-3 feature view not materialized; run scripts/phase7_build_gen3.py first")

    g3 = pd.read_parquet(GEN3)
    # --- PARITY: Gen-3 2023-2025 must equal the frozen Gen-2 view on the 22 features (vectorized merge) ---
    gen2 = E.load_frame()
    base_feats = list(E.ALL_FEATURES)
    parity = {}
    if "plate_appearance_id" in gen2.columns:
        cols = ["plate_appearance_id"] + [f for f in base_feats if f in gen2.columns and f in g3.columns]
        left = g3[g3["season"].isin([2023, 2024, 2025])][cols]
        merged = left.merge(gen2[cols], on="plate_appearance_id", suffixes=("_g3", "_g2"), how="inner")
        mism = 0
        for f in cols[1:]:
            a = merged[f + "_g3"].to_numpy(dtype="float64")
            b = merged[f + "_g2"].to_numpy(dtype="float64")
            both_nan = np.isnan(a) & np.isnan(b)
            mism += int(np.sum(~(np.isclose(a, b, equal_nan=True) | both_nan)))
        parity = {"comparedRows": int(len(merged)), "featureMismatches": mism, "identical": mism == 0}
        print(f"[{time.strftime('%H:%M:%S')}] parity: {parity}", flush=True)
    else:
        parity = {"note": "gen2 frame lacks plate_appearance_id; parity via prior-coverage match in build"}

    val = g3[g3["season"] == 2024]
    branches = {"A0": [2023], "A1": [2022, 2023], "A2": [2021, 2022, 2023]}
    results = {}
    for name, dev_seasons in branches.items():
        dev = g3[g3["season"].isin(dev_seasons)]
        results[name] = {"developmentSeasons": dev_seasons, "developmentRows": int(len(dev)),
                         "priorBlind2021": bool(2021 in dev_seasons)}
        for fam in ("logistic", "hist_gradient_boosting"):
            print(f"[{time.strftime('%H:%M:%S')}] {name} {fam} dev={dev_seasons} rows={len(dev)}", flush=True)
            results[name][fam] = _evaluate(dev, val, fam)
            r = results[name][fam]
            print(f"    val logLoss={r['logLoss']} top1={r['top1']} macroF1={r['macroF1']} fit={r['fitSeconds']}s", flush=True)

    payload = {"parity": parity, "validationSeason": 2024, "branches": results,
               "selectionRule": "2024 validation log loss only; 2025 sealed; 2026 untouched",
               "secondaryOot2025": None}

    if args.run_secondary_oot_2025:
        print("[gated] scoring 2025 secondary OOT (NOT used for selection) …", flush=True)
        oot = g3[g3["season"] == 2025]
        payload["secondaryOot2025"] = {
            name: {fam: _evaluate(g3[g3["season"].isin(branches[name])], oot, fam)["logLoss"]
                   for fam in ("logistic",)}
            for name in branches
        }

    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
