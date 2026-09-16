"""Reconcile retained transition populations; no simulation or outcome reload."""
from __future__ import annotations
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.build_mlb_v18_transition_shrinkage_v1 import _freeze_forecast_identities, ref, put
from server.sports_datasets.consumer import canonical_json_bytes

OUT = ROOT / "outputs/mlb-v18-transition-shrinkage-v1"


def verify() -> dict:
    current = json.loads((OUT / "current.json").read_text())
    protocol = json.loads((OUT / "protocol.json").read_text())
    eligible = _freeze_forecast_identities(protocol["gameComparison"]["eligibleForecastObjectSha256"])
    for key in ("result", "population", "component", "manifest"):
        reference = current[key]
        actual = ref(Path(reference["path"]))
        if any(actual[k] != reference[k] for k in ("sha256", "bytes")):
            raise ValueError("Retained research artifact differs")
    result = json.loads(Path(current["result"]["path"]).read_text())
    rows = result["gameResults"]
    if len(rows) != 16 or {r["gameId"] for r in rows} != set(eligible):
        raise ValueError("Retained result and frozen eligible cohort differ")
    measures = {key: [] for key in ("home", "away", "total", "margin", "homeWin")}
    with np.load(current["population"]["path"], allow_pickle=False) as arrays:
        for index, row in enumerate(rows):
            bh, ba, ch, ca = [arrays[f"game_{index:02d}_{arm}_{field}"]
                             for arm, field in (("baseline", "homeRuns"), ("baseline", "awayRuns"),
                                                ("change", "homeRuns"), ("change", "awayRuns"))]
            if any(v.shape != (5000,) for v in (bh, ba, ch, ca)):
                raise ValueError("Retained paired population size differs")
            values = {"home": ch-bh, "away": ca-ba, "total": (ch+ca)-(bh+ba),
                      "margin": (ch-ca)-(bh-ba),
                      "homeWin": (ch > ca).astype(float)-(bh > ba).astype(float)}
            for key, value in values.items():
                measures[key].append(value)
    corrected = {}
    for key, games in measures.items():
        mean = float(np.mean([g.mean() for g in games]))
        if not np.isclose(mean, result["pairedDrawMeanChange"][key]["mean"], atol=1e-12, rtol=0):
            raise ValueError("Retained paired means differ")
        corrected[key] = {
            "mean": mean,
            "pairedMonteCarloStandardError": math.sqrt(sum(float(g.var(ddof=1))/len(g) for g in games))/len(games),
        }
    receipt = {
        "schemaVersion": "MLB_V18_TRANSITION_DELIVERY_VERIFICATION_V1",
        "verifiedAtUtc": datetime.now(timezone.utc).isoformat(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "trackedDirtyFilesPreserved": subprocess.check_output(["git", "diff", "--name-only"], cwd=ROOT, text=True).splitlines(),
        "result": current["result"], "population": current["population"],
        "cohort": {"included": 16, "pilotExcludedFrom17PublishedHistoricalGames": 1,
                   "permanentQuarantineKeys": ["823343", "824235", "822693"],
                   "quarantinedGamesPresent": 0, "sealedWindowGamesPresent": 0,
                   "historicalFallbackGames": 0,
                   "sourceEvidenceClasses": dict(Counter(r["truth"]["cohort"] for r in rows))},
        "simulationsPerGamePerConfiguration": 5000,
        "newSimulations": 0, "newOutcomeSourceReads": 0,
        "pairedDrawMeanChange": corrected,
        "mcMethod": "Independent game seeds; sqrt(sum_g(sample_variance(paired_difference_g)/5000))/16. Conditional finite-simulation error only, not uncertainty about predictive improvement.",
        "legacyQualifications": [
            "Original 16-game scores and arrays are preserved. No re-fit, re-selection or re-simulation occurred.",
            "The original build decoded the upstream-protected export before its local pilot check. The successor code gates exact forecast identity, game quarantine and sealed dates before decoding any selected outcome payload; it does not retroactively change that execution order.",
            "A focused revision-bound reconciliation found 16 matching original outcomes and zero saved-truth mismatches; no pilot outcome entered the fixed comparison.",
            "Transition reconstruction uses its own 2023-2025 fit counts and is descriptive only. Frozen PA training chronology remains uncertified.",
            "The original NYM-NYY prospective receipt retained summary means only; its missing candidate draws are not reconstructed or represented as retained prospective distributions.",
            "The protocol names component selection metrics but its historical game-level section cannot supply them; no acceptance gate was passed and no replacement gate is selected after scores.",
        ],
        "candidateAuthority": False, "verdict": "INSUFFICIENT_EVIDENCE",
    }
    raw = canonical_json_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    path = OUT / f"delivery-verification/sha256/{digest}/verification.json"
    put(path, raw)
    pointer = ref(path)
    (OUT / "delivery-verification-current.json").write_bytes(canonical_json_bytes(pointer))
    return pointer


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
