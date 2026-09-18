"""Post-selection descriptive diagnostics; no fitting or candidate selection."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from sports_cfb_gen1.strength_study import binding, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path(
        r"C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1"))
    out = parser.parse_args().output
    point_path = out / "COMMON_POPULATION_PREDICTIONS.parquet"
    score_path = out / "COMMON_POPULATION_SCORES.parquet"
    points, scores = pd.read_parquet(point_path), pd.read_parquet(score_path)
    result = {"schema": "CFB_STRENGTH_DESCRIPTIVE_DIAGNOSTICS_V1",
              "postSelectionDescriptiveOnly": True,
              "sources": [binding(point_path), binding(score_path)],
              "script": binding(__file__), "periods": {}}
    for period, years in (("development", range(2017, 2023)),
                          ("reused_validation", (2023, 2024)), ("reused_2025", (2025,))):
        p = points.loc[points.season.isin(years)]
        s = scores.loc[scores.season.isin(years)]
        base = p.loc[p.arm.eq("baseline")].set_index("game_id").sort_index()
        candidate = p.loc[p.arm.eq("B")].set_index("game_id").loc[base.index]
        sb = s.loc[s.arm.eq("baseline")].set_index("game_id").loc[base.index]
        sc = s.loc[s.arm.eq("B")].set_index("game_id").loc[base.index]
        row = {"games": len(base), "forecastChanges": {},
               "fractionGamesWithLowerEnergy": float((sc.jointEnergyScore < sb.jointEnergyScore).mean()),
               "pointWinnerSignChanges": int((np.sign(base.pred_margin) != np.sign(candidate.pred_margin)).sum())}
        for label in ("home", "away", "margin", "total"):
            delta = candidate[f"pred_{label}"] - base[f"pred_{label}"]
            absolute = delta.abs()
            row["forecastChanges"][label] = {
                "meanSignedChange": float(delta.mean()), "meanAbsoluteChange": float(absolute.mean()),
                "medianAbsoluteChange": float(absolute.median()), "p90AbsoluteChange": float(absolute.quantile(.9))}
        prob_delta = sc.jointHomeWinProbability - sb.jointHomeWinProbability
        row["jointHomeWinProbabilityChange"] = {
            "medianAbsoluteChange": float(prob_delta.abs().median()),
            "p90AbsoluteChange": float(prob_delta.abs().quantile(.9)),
            "atLeastFivePercentagePoints": int((prob_delta.abs() >= .05).sum())}
        row["supportCounts"] = {
            "lowSupport": int(candidate.low_support.sum()),
            "zeroCurrentPrimarySupportEitherTeam": int(candidate.opener.sum()),
            "zeroPriorPrimarySupportEitherTeam": int(candidate.zero_prior_support.sum())}
        row["coverage90"] = {label: {"baseline": float(sb[f"{label}Coverage90"].mean()),
                                     "B": float(sc[f"{label}Coverage90"].mean()),
                                     "baselineWidth": float(sb[f"{label}Width90"].mean()),
                                     "BWidth": float(sc[f"{label}Width90"].mean())}
                             for label in ("home", "away", "margin", "total")}
        result["periods"][period] = row
    write_json(out / "DESCRIPTIVE_DIAGNOSTICS.json", result)
    print(result["periods"]["reused_validation"])


if __name__ == "__main__":
    main()
