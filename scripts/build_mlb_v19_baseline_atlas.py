"""Descriptive frozen-V18 atlas on the already-separated Development cohort.

No candidate predictions are read and no selection rule is changed. Earlier-fold
eligibility is replayed with the same pure function used before candidate fits.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from reproduce_mlb_v19_baseline import BASE, BASE_SHA, load_safe_cache
from run_mlb_v19_study import GAME_PATH, GAME_SHA, join_teams
from server.sports_current_statcast.mlb_v19_evaluation import (
    _metrics, discover_persistent_regimes, evaluate_predictions, regime_masks,
)
from server.sports_current_statcast.mlb_regime_metrics import metric_contributions
from server.sports_datasets.consumer import canonical_json_bytes

DEST = ROOT / "outputs/mlb-v19-current-state-specialists-v1/baseline-atlas"


def reference(path):
    raw = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def store(name, data):
    raw = canonical_json_bytes(data)
    sha = hashlib.sha256(raw).hexdigest()
    path = DEST / "sha256" / sha / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        assert path.read_bytes() == raw, "Immutable baseline atlas conflict"
    else:
        with path.open("xb") as stream:
            stream.write(raw)
    return reference(path)


def weighting(frame, contributions, mask):
    n = int(mask.sum())
    if not n:
        return {"observations": 0, "games": 0, "paWeightedLogLoss": None,
                "paWeightedBrier": None, "equalGameWeightedLogLoss": None, "equalGameWeightedBrier": None}
    values = pd.DataFrame({"game": frame.loc[mask, "canonicalGameId"].to_numpy(),
                           "logLoss": contributions["logLoss"][mask], "brier": contributions["brier"][mask]})
    means = values.groupby("game", sort=False)[["logLoss", "brier"]].mean()
    return {"observations": n, "games": len(means), "paWeightedLogLoss": float(values.logLoss.mean()),
            "paWeightedBrier": float(values.brier.mean()), "equalGameWeightedLogLoss": float(means.logLoss.mean()),
            "equalGameWeightedBrier": float(means.brier.mean())}


def build():
    meta, raw, oof = load_safe_cache()
    raw = join_teams(raw).reset_index(drop=True)
    frame = raw.set_index("canonicalPaId", drop=False).loc[oof.canonicalPaId].reset_index(drop=True)
    assert len(frame) == 494432 and frame.canonicalGameId.nunique() == 6570
    assert np.array_equal(frame.observedClassIndex, oof.observedClassIndex)
    assert np.array_equal(frame.canonicalGameId, oof.canonicalGameId)
    assert frame.game_date.astype(str).max() <= "2026-08-06"
    p = oof[["probability_" + name for name in meta["targetOrder"]]].to_numpy()
    y = frame.observedClassIndex.to_numpy(dtype=int)
    with threadpool_limits(limits=1):
        evaluation = evaluate_predictions(frame, {"V18": p})
        contributions = metric_contributions(y, p)
        masks, registry = regime_masks(frame)
        eligibility = [discover_persistent_regimes(frame, p, before_fold=n) for n in (3, 4, 5)]
        fold_rows = []
        all_rows = np.ones(len(frame), dtype=bool)
        scope_weighting = [{"scope": "ALL", **weighting(frame, contributions, all_rows)}]
        for fold in range(1, 6):
            take = frame.foldNumber.eq(fold).to_numpy()
            detailed = _metrics(y, p, contributions, take)
            fold_rows.append({"foldNumber": fold, "firstDate": str(frame.loc[take, "game_date"].min()),
                              "lastDate": str(frame.loc[take, "game_date"].max()),
                              "games": int(frame.loc[take, "canonicalGameId"].nunique()), **detailed})
            scope_weighting.append({"scope": "FOLD_" + str(fold), **weighting(frame, contributions, take)})
        regime_rows = []
        for name, mask in masks.items():
            scope_weighting.append({"scope": name, **weighting(frame, contributions, mask)})
            local_folds = []
            for fold in range(1, 6):
                take = frame.foldNumber.eq(fold).to_numpy()
                inside, outside = take & mask, take & ~mask
                metrics = weighting(frame, contributions, inside)
                residual = contributions["calibrationResidual"][inside].mean(axis=0).tolist() if inside.any() else None
                excess = float(contributions["logLoss"][inside].mean() - contributions["logLoss"][outside].mean()) if inside.any() and outside.any() else None
                local_folds.append({"foldNumber": fold, **metrics, "logLossExcessVsComplement": excess,
                                    "observedMinusPredictedClassRates": residual})
            regime_rows.append({"name": name, "folds": local_folds,
                                "eligibilitySnapshots": [{"beforeFold": row["beforeFold"], "selected": name in row["selected"],
                                    **{key: item[key] for key in ("eligible", "reason", "stableExcessLoss", "stableBiasClasses", "months", "teams")}}
                                    for row in eligibility for item in row["regimes"] if item["name"] == name],
                                "allFoldReviewRole": "DESCRIPTIVE_ONLY_NEVER_CHANGES_PRIOR_FOLD_ELIGIBILITY"})
        exposure_rows = []
        # Fixed bins are descriptive counts, not discovered specialist gates.
        for feature in ("batter_prior_pa_count", "pitcher_prior_bf_count"):
            exposure = pd.to_numeric(frame[feature], errors="coerce").to_numpy(dtype=float)
            groups = [("ZERO_RECORDED_OBSERVATIONS", exposure == 0), ("1_TO_24", (exposure > 0) & (exposure < 25)),
                      ("25_TO_99", (exposure >= 25) & (exposure < 100)), ("100_TO_249", (exposure >= 100) & (exposure < 250)),
                      ("250_TO_999", (exposure >= 250) & (exposure < 1000)), ("1000_PLUS", exposure >= 1000),
                      ("UNKNOWN", ~np.isfinite(exposure))]
            assert sum(int(mask.sum()) for _, mask in groups) == len(frame)
            exposure_rows.extend({"feature": feature, "bin": name, **weighting(frame, contributions, mask)} for name, mask in groups)
    atlas = {"schemaVersion": "MLB_V19_FROZEN_V18_BASELINE_FAILURE_ATLAS_V1", "baselineReceipt": reference(BASE),
             "baselineIdentity": BASE_SHA, "rawDevelopment": meta["artifacts"]["rawDevelopment"],
             "matchedOof": meta["artifacts"]["matchedOof"], "gameMap": {"path": str(GAME_PATH), "sha256": GAME_SHA},
             "classOrder": meta["targetOrder"], "observations": len(frame), "games": int(frame.canonicalGameId.nunique()),
             "predictionDefinition": "EXACT_STORED_FROZEN_V18_RAW_PROBABILITIES_NO_NEW_CALIBRATION",
             "comparability": "Equal chronological calibration is reported separately with final candidate evaluation; this atlas does not compare raw V18 against calibrated challengers.",
             "evaluation": evaluation, "foldCalibrationAndConfusion": fold_rows,
             "regimeFoldPersistence": regime_rows, "pastFoldEligibility": eligibility,
             "weighting": scope_weighting, "exposureBins": exposure_rows,
             "weightingDefinitions": {"primary": "One equal weight per observed PA; player/game exposure contributes through its actual PA count. No arbitrary repeat weighting by prior sample size.",
                                      "equalGame": "Mean PA loss within each game, then equal weight per included game; for a regime, only its observed PAs within that game are averaged.",
                                      "confusion": "Observed class rows, maximum-probability predicted class columns; this is a hard-label diagnostic, not probabilistic calibration.",
                                      "calibration": "Per-class predicted minus observed mean rate, one-vs-rest Brier and fixed10bin reliability/ECE. Intervals in the matched challenger evaluation are descriptive Development intervals, not an independent trial."},
             "gameLevelEvidence": {"status": "NO_MATCHED_HISTORICAL_PREGAME_INPUT_VINTAGES", "diagnosticGames": 20,
                                   "diagnosticDates": ["2026-05-02", "2026-05-03"], "permittedUse": "ORACLE_MECHANICS_SENSITIVITY_NONPREGAME",
                                   "simulationsRunForAtlas": 0,
                                   "notEstablished": ["Pregame winner calibration", "Pregame score/margin/total forecast error", "Pregame tails/interval coverage", "Market superiority"]},
             "regimeRegistry": registry, "candidatePredictionsRead": 0, "fits": 0, "providerCalls": 0,
             "finalOotPayloadReads": 0, "aispWrites": 0, "operationalDeploymentActions": 0,
             "decisionRuleChanged": False, "producer": reference(Path(__file__).resolve())}
    artifact = store("baseline-failure-atlas.json", atlas)
    manifest = store("manifest.json", {"schemaVersion": "MLB_V19_BASELINE_ATLAS_MANIFEST_V1", "artifact": artifact,
                                      "baselineReceipt": reference(BASE), "observations": len(frame), "games": 6570,
                                      "candidatePredictionsRead": 0, "modelFits": 0, "finalOotPayloadReads": 0})
    overall = next(row for row in evaluation["metrics"] if row["dimension"] == "overall")
    return {"manifest": manifest, "atlas": artifact, "overall": {k: overall[k] for k in ("observations", "games", "logLoss", "brier")},
            "folds": [{k: r[k] for k in ("foldNumber", "observations", "games", "logLoss", "brier")} for r in fold_rows],
            "eligibleEarlierFolds": [{"beforeFold": r["beforeFold"], "selected": r["selected"]} for r in eligibility],
            "regimes": [{"name": r["name"], "eligibility": r["eligibilitySnapshots"]} for r in regime_rows]}


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
