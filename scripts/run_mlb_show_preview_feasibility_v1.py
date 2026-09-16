"""One locked team-only comparison, or a fail-closed current-input check."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import joblib
import numpy as np
from server.sports_shared import mlb_show_preview_team as m
from server.sports_shared.show_preview import canonical, digest, immutable, physical

OUT = ROOT / "outputs/mlb-show-preview-feasibility-v1"
DESIGN_SHA = "0e96d068e13fd3a697b6a8179d679fba2aca1ff953ed65362f7c03b793d555f2"


def assess(out):
    started = time.perf_counter()
    design = (out / "FROZEN_DESIGN.json").read_bytes()
    if digest(design) != DESIGN_SHA:
        raise ValueError("frozen design differs")
    if (out / "ASSESSMENT.json").exists():
        assessment = json.loads((out / "ASSESSMENT.json").read_bytes())
        for ref in assessment["artifacts"]:
            if physical(ref["path"]) != ref:
                raise ValueError("retained artifact changed")
        print("REUSED", digest((out / "ASSESSMENT.json").read_bytes()))
        return
    rows, excluded, sources = m.retained_population(
        Path(r"C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1"),
        Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1"),
        out / "historical-identity-inspection.json")
    targets = [r for r in rows if r["season"] >= 2021]
    x, audits = m.feature_matrix(rows, targets)
    immutable(out / "population.json", canonical(rows))
    immutable(out / "feature-audit.json", canonical({"features": m.FEATURES, "audits": audits, "values": x.tolist()}))
    immutable(out / "source-index.json", canonical({"sourceFiles": sources, "excluded": excluded,
              "seasons": dict(Counter(r["season"] for r in rows)), "protectedSeasonsOpened": [],
              "researchAdmission": "User-authorized bounded derived team-only research; raw Bronze/Silver governance flags unchanged",
              "dataAttribution": "The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at www.retrosheet.org.",
              "sourceVintageQualification": "Historical final scores acquired August 21, 2026. No historical source publication/revision timestamps are inferred. No revised box statistics used. Completion dates control suspended-game eligibility. This is reconstructed research, not certified historical preview performance."}))
    seasons = np.array([r["season"] for r in targets])
    reports, predictions, uncertainty = {}, [], {}
    artifacts = [physical(out / n) for n in ("population.json", "feature-audit.json", "source-index.json", "FROZEN_DESIGN.json")]
    for year in (2022, 2023, 2024):
        train, test = seasons < year, seasons == year
        training = [r for r, mask in zip(targets, train) if mask]
        testing = [r for r, mask in zip(targets, test) if mask]
        model = m.fit(x[train], training)
        estimates = m.predict(model, x[test])
        if not np.isfinite(estimates).all() or np.any(estimates[:, 1:] <= 0):
            raise ValueError("invalid expected scores")
        baseline_values = np.mean([[float(r["home_score"] > r["away_score"]), r["away_score"], r["home_score"]] for r in training], axis=0)
        baseline = np.tile(baseline_values, (len(testing), 1))
        cm, cs = m.metrics(testing, estimates)
        bm, bs = m.metrics(testing, baseline)
        uncertainty[str(year)] = m.paired_week_uncertainty(testing, cs-bs)
        reports[str(year)] = {"role": "reused Validation" if year == 2024 else "season-forward Development diagnostic",
                              "trainingSeasons": sorted(set(r["season"] for r in training)),
                              "candidate": cm, "benchmark": bm, "missingStarterCount": len(testing), "missingLineupCount": len(testing)}
        supports = [a["currentSeasonSupport"] for a, mask in zip(audits, test) if mask]
        for name, mask in (("earlySupport", np.array([min(s) <= 20 for s in supports])),
                           ("laterSupport", np.array([min(s) > 20 for s in supports]))):
            subset = [r for r, take in zip(testing, mask) if take]
            reports[str(year)][name] = {"candidate": m.metrics(subset, estimates[mask])[0], "benchmark": m.metrics(subset, baseline[mask])[0]}
        for r, b, c in zip(testing, baseline, estimates):
            predictions.append({"gameId": r["id"], "date": r["date"], "season": year,
                "actual": {"away": r["away_score"], "home": r["home_score"]},
                "benchmark": dict(zip(("pHome", "expectedAway", "expectedHome"), b.tolist())),
                "candidate": dict(zip(("pHome", "expectedAway", "expectedHome"), c.tolist()))})
        model_path = out / f"model-trained-through-{year-1}.joblib"
        joblib.dump({"configuration": m.CONFIG, "features": m.FEATURES, "models": model,
                     "trainingTargetIds": [r["id"] for r in training], "designSha256": DESIGN_SHA}, model_path)
        artifacts.append(physical(model_path))
    immutable(out / "predictions.json", canonical(predictions))
    artifacts.append(physical(out / "predictions.json"))
    val = reports["2024"]
    delta = uncertainty["2024"]["candidateMinusBenchmark"]
    gate = {
        "minimumValidationGames": val["candidate"]["n"] >= 2000,
        "logLossReductionAtLeast0.005": delta["logLoss"]["mean"] <= -.005,
        "pairedWeek95UpperBelowZero": delta["logLoss"]["upper95"] < 0,
        "brierNotWorse": delta["binaryBrier"]["mean"] <= 0,
        "totalMAENoMoreThan0.1Worse": delta["totalMAE"]["mean"] <= .1,
        "bothDevelopmentSeasonsImprove": all(reports[str(y)]["candidate"]["logLoss"] < reports[str(y)]["benchmark"]["logLoss"] for y in (2022, 2023)),
        "finitePositiveExpectedScores": True,
    }
    passed = all(gate.values())
    decision = {"configuration": m.CONFIG, "numericalGate": gate, "numericalGatePassed": passed,
                "historicalPublicationTimingCertified": False, "currentInputsCertified": False,
                "admittedForPublication": False,
                "decision": "IMPLEMENTED_AWAITING_CERTIFIED_CURRENT_INPUTS" if passed else "REJECTED_BY_FROZEN_NUMERICAL_GATE",
                "noFurtherCandidateSearch": True, "sourceVintageQualificationRetained": True}
    immutable(out / "CANDIDATE_SELECTION.json", canonical(decision))
    assessment = {"schema": "MLB_SHOW_PREVIEW_ASSESSMENT_V1", "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "designSha256": DESIGN_SHA, "configuration": m.CONFIG,
        "status": decision["decision"], "reports": reports, "pairedUncertainty": uncertainty,
        "selection": decision, "targetSeasons": [2021, 2022, 2023, 2024], "historySeasons": [2019, 2020],
        "metricConventions": {"logLoss": "natural log binary home-win", "brier": "mean((pHome-homeWin)^2), range 0..1", "tie": "0; historical tied/no-decision games excluded", "pointScores": "independent Poisson conditional means, no joint distribution"},
        "matchedV18Comparison": "Unavailable without mixing 2026 inspected outcomes, uncertified target-day participants or unmatched horizons; not performed",
        "currentSeasonOutcomeSelectionAccess": False, "elapsedSeconds": time.perf_counter()-started, "artifacts": artifacts}
    immutable(out / "ASSESSMENT.json", canonical(assessment))
    print(json.dumps({"selection": decision, "reports": {y: {k:v for k,v in r.items() if k in ('candidate','benchmark')} for y,r in reports.items()}, "seconds": assessment["elapsedSeconds"]}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["assess", "check-current", "produce"])
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--inputs", type=Path)
    p.add_argument("--exchange", type=Path, default=Path(r"C:\Users\james\asp-model-exchange"))
    args = p.parse_args()
    if args.mode == "assess":
        assess(args.out)
    else:
        if not args.inputs:
            raise SystemExit("CURRENT_TEAM_HISTORY_AND_SCHEDULE_REQUIRED: no acquisition performed")
        now = datetime.now(timezone.utc)
        m.require_current_inputs(json.loads(args.inputs.read_bytes()), now)
        if args.mode == "produce":
            from server.sports_shared.show_preview import consumer_validator, publish
            context = json.loads((ROOT / "outputs/multisport-show-preview-producer-v1/context/context.json").read_bytes())
            pin = context["consumer_validator"]
            validator = consumer_validator(ROOT / "outputs/multisport-show-preview-producer-v1/context/consumer-contract.py", pin["sha256"])
            source = m.point_source(args.inputs, args.out / "model-trained-through-2023.joblib",
                                    args.out / "ASSESSMENT.json", args.out, now)
            result = publish([m.preview_source(source)], args.exchange, validator)
            raw = canonical(result)
            immutable(args.out / "publications" / (digest(raw)+".json"), raw)
            print(json.dumps(result))
        else:
            print("INPUTS_VERIFIED_NO_FORECAST_OR_PUBLICATION")
