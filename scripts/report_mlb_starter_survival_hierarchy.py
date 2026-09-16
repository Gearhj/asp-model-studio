"""Report saved research predictions only: no training, source access or publication."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = ROOT / "outputs/mlb-starter-survival-hierarchical-pa-v1"
RESULT = BASE / "duration-study/objects/sha256/af2e6aca3f83a2e4312b555502b2cf598d0939941f7473c03226318d30f6ff84/duration-results.json"
PA = BASE / "pa-eligibility/sha256/37e3fcb056899420d0000be6f0f61f9567d1ccccb05fe0da7033d6a3c4554531/eligibility-review.json"
GAMES = BASE / "game-eligibility/sha256/fa2d011e2dafeda0170dcda26b64f457d8bf6a157ce2a48ae91e5728273855dd/game-eligibility.json"
CORRECTION = BASE / "duration-data/excluded-start-null-metadata-correction.json"
REF = "EMPIRICAL_POOLED_CAL"
SELECTED = "HGB_PREGAME_CAL"
LABELS = {REF: "Pooled empirical", SELECTED: "Pregame HGB", "LOGISTIC_CONDITIONAL_CAL": "Observed-state logistic"}


def descriptor(path):
    path = Path(path)
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def checked(ref):
    path = Path(ref["path"]).resolve()
    if not path.is_relative_to(BASE):
        raise ValueError("Reporter accepts only this isolated research output")
    actual = descriptor(path)
    if any(actual[k] != ref[k] for k in ("sha256", "bytes")):
        raise ValueError(f"Artifact mismatch: {path}")
    return path


def addressed_json(path):
    ref = descriptor(path)
    if ref["sha256"] != path.parent.name:
        raise ValueError("Addressed JSON mismatch")
    return json.loads(path.read_text(encoding="utf-8"))


def save(name, data):
    digest = hashlib.sha256(data).hexdigest()
    path = BASE / "report/sha256" / digest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError("Immutable report collision")
    else:
        with path.open("xb") as handle:
            handle.write(data)
    return descriptor(path)


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def figure(name, fig):
    stream = io.BytesIO()
    fig.savefig(stream, format="png", dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return save(name, stream.getvalue())


def main():
    result, pa, games = [addressed_json(p) for p in (RESULT, PA, GAMES)]
    cohort = json.loads(checked(result["cohort"]).read_text(encoding="utf-8"))
    for ref in cohort["code"] + [cohort["declaration"]]:
        actual = descriptor(ref["path"])
        if any(actual[k] != ref[k] for k in ("sha256", "bytes")):
            raise ValueError("Executed model/declaration source changed")
    checked(cohort["dataManifest"])
    checked(cohort["risk"])
    checked(cohort["starts"])
    checked(result["preTestSelectionReceipt"])
    reloads = []
    for item in result["models"]:
        model = joblib.load(checked(item["artifact"]))
        inputs = pd.read_parquet(checked(item["fixture"]))
        expected = pd.read_parquet(checked(item["expected"])).to_numpy()
        actual = model.predict_proba(inputs)
        if not np.array_equal(actual, expected):
            raise ValueError("Saved inference reload mismatch")
        reloads.append({"model": item["model"], "rows": len(inputs), "probabilities": actual.size,
                        "mismatches": int(np.count_nonzero(actual != expected)), "fits": 0})
    frames = {key: pd.read_parquet(checked(ref)) for key, ref in result["predictionArtifacts"].items()}
    duration, risk = frames["durationPredictions"], frames["riskPredictions"]
    reference_ids = set(duration.loc[duration.model == REF, "startId"])
    if any(set(g.startId) != reference_ids for _, g in duration.groupby("model")):
        raise ValueError("Reporting cohort mismatch")
    monthly = []
    duration["month"] = duration.gameDate.str[:7]
    for (model, month), frame in duration.groupby(["model", "month"]):
        monthly.append({"model": model, "month": month, "starts": len(frame), "games": frame.gameId.nunique(),
                        **{k: float(frame[k].mean()) for k in ["bfCappedMeanAbsoluteError", "bfCrpsThrough100", "bfNll", "coverage90", "bfCappedMeanBias"]}})
    # Descriptive calibration at observed opportunities, not independent-row inference.
    calibration = []
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.plot([0, 0.4], [0, 0.4], "--", color="#777777", linewidth=1)
    for model in LABELS:
        frame = risk.loc[(risk.model == model) & (risk.endpoint != "GAME_END")].copy()
        frame["predicted"] = frame.REMOVAL / (frame.REMOVAL + frame.CONTINUE)
        frame["observed"] = frame.endpoint.eq("REMOVAL")
        frame["bin"] = pd.cut(frame.predicted, [0, .01, .025, .05, .075, .1, .15, .2, .3, .5, 1], include_lowest=True)
        grouped = frame.groupby("bin", observed=True).agg(predicted=("predicted", "mean"), observed=("observed", "mean"), rows=("observed", "size"))
        for _, row in grouped.iterrows():
            calibration.append({"model": model, "predicted": float(row.predicted), "observed": float(row.observed), "rows": int(row.rows)})
        shown = grouped[grouped.rows >= 100]
        ax.plot(shown.predicted, shown.observed, marker="o", label=LABELS[model])
    ax.set(title="Removal calibration at supported observed opportunities", xlabel="Mean predicted removal probability", ylabel="Observed removal frequency", xlim=(0, .4), ylim=(0, .4))
    ax.legend(frameon=False)
    fig.text(.02, -.01, "50,227 non-game-end boundaries; bins with ≥100 rows shown. Descriptive; rows are not independent games.", fontsize=8)
    figures = [figure("removal-calibration.png", fig)]
    fig, ax = plt.subplots(figsize=(7.5, 4.6))
    realized = duration[duration.model == REF].realizedBf.astype(int)
    hist = realized.value_counts(normalize=True).sort_index()
    ax.bar(hist.index, hist.values, width=.85, color="#c6cbd3", label="Observed completed stint")
    for item in result["durationDistributionArtifacts"]:
        law = pd.read_parquet(checked(item["artifact"]))
        if item["model"] in (REF, SELECTED):
            mean_law = law.groupby("bf").probability.mean()
            ax.plot(mean_law.index, mean_law.values, linewidth=2, label=LABELS[item["model"]])
    ax.set(title="Pregame reduced-state BF distributions", xlabel="Batters faced (not pitching outs or decimal innings)", ylabel="Probability mass", xlim=(0, 50))
    ax.legend(frameon=False)
    fig.text(.02, -.01, "2,302 held-out starts. Plot displays BF ≤50; stored laws extend to100 with explicit unresolved tail.", fontsize=8)
    figures.append(figure("pregame-bf-distributions.png", fig))
    ci = [row for row in result["pairedIntervals"] if row["candidate"] == SELECTED and row["metric"] in ("bfCappedMeanAbsoluteError", "bfCrpsThrough100")]
    fig, ax = plt.subplots(figsize=(7.5, 3))
    for i, row in enumerate(ci):
        point, (low, high) = row["differenceCandidateMinusReference"], row["ci95"]
        ax.errorbar(point, i, xerr=[[point-low], [high-point]], fmt="o", color="#2369aa", capsize=5)
    ax.axvline(0, color="#777777", linestyle="--")
    ax.set(yticks=range(len(ci)), yticklabels=["BF expected-duration MAE", "BF CRPS through100"], xlabel="Pregame HGB minus pooled empirical (lower is better)", title="Paired starter-duration error changes — not game scores")
    fig.text(.02, -.05, "95% descriptive intervals:500 paired whole-game bootstrap samples;1,162 games/2,302 starts.", fontsize=8)
    figures.append(figure("paired-duration-errors.png", fig))
    comparison = {
        "schemaVersion": "MLB_STARTER_SURVIVAL_HIERARCHY_COMPARISON_V1",
        "status": "COMPONENT_ONLY_GAME_VALIDATION_BLOCKED",
        "sourceResult": descriptor(RESULT), "declaration": cohort["declaration"], "cohort": result["cohort"],
        "excludedMetadataCorrection": descriptor(CORRECTION), "paEligibility": descriptor(PA), "gameEligibility": descriptor(GAMES),
        "durationMetrics": result["metrics"], "currentHookConditionalDiagnostics": result["currentMechanismComparison"],
        "pairedIntervals": result["pairedIntervals"], "subgroups": result["subgroups"], "monthlyDescriptiveStability": monthly,
        "calibrationBins": calibration, "fittedBundles": result["models"], "reloadVerification": reloads,
        "selectedEarlier": result["selectedDeployableCandidate"], "preTestSelectionReceipt": result["preTestSelectionReceipt"],
        "paComparison": [{"arm": arm, "comparisonPAs": 0, "eightClassLogLoss": None, "brier": None, "rootLoss": None, "outBranchLoss": None, "nonOutBranchLoss": None,
                          "status": "BLOCKED_SHARED_FEATURE_HISTORY_CHRONOLOGY"} for arm in ["A_FROZEN_V18", "B_BINARY_FREQUENCY_CONTROL", "C_LEARNED_HIERARCHY"]],
        "gameComparison": {"accountedScheduleRows": games["scheduledGames"], "eligibleFourArmGames": 0, "simulationDraws": 0,
                           "gameErrorMetrics": None, "firstFiveMetrics": None, "winnerMetrics": None,
                           "reason": "Shared PA chronology, eligible common pregame input authority and supported reliever integration are not established",
                           "scheduleCompletenessLimitation": games["scheduleCompletenessLimitation"]},
        "unavailablePlots": {"paRootVersusBranchLoss": "No eligible real PA comparison", "pairedGameError": "No eligible four-arm game comparison"},
        "figures": figures, "scoreSupport": result["durationScoreSupport"],
        "accounting": {"realHazardEstimatorFitsStarted": 3, "realHazardEstimatorFitsCompleted": 3, "empiricalFrequencyFits": 1, "temperatureFits": 3,
                       "syntheticPAHeadFits": 3, "realPAFits": 0, "v18Fits": 0, "fullGameSimulations": 0, "studyRuntimeSeconds": result["runtimeSeconds"],
                       "reporterFits": 0, "providerCalls": 0, "costUsd": 0, "finalOotReads": 0, "aispWrites": 0},
        "authority": {"researchOnly": True, "promoted": False, "wageringAuthority": False, "existingV18AndDecisionPolicyUnchanged": True},
        "nextAction": "Authenticate shared completion-ordered rolling/context histories and freeze one timing-valid matched PA cohort before the B/C comparison and gated game pilot",
        "reporter": descriptor(Path(__file__)),
    }
    output = save("comparison.json", json_bytes(comparison))
    print(json.dumps({"comparison": output, "figures": figures, "reloads": reloads, "monthly": [r for r in monthly if r["model"] in (REF, SELECTED)]}, indent=2))


if __name__ == "__main__":
    main()
