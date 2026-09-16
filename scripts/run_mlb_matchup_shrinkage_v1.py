"""Staged research only: diagnose -> select -> assess; verify for byte replay."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_shared import mlb_matchup_shrinkage as m

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["diagnose", "select", "assess", "verify"])
    ap.add_argument("--output", type=Path, default=ROOT/"outputs/mlb-matchup-starter-shrinkage-v1")
    args = ap.parse_args()
    if args.action == "diagnose":
        r = m.development_diagnosis(args.output)
        print(json.dumps({k:r[k] for k in ("maximumTeamMean", "maximumTotalMean", "thresholds")}))
    elif args.action == "select":
        r = m.select_development(args.output)
        print(json.dumps({"selected": r["selectedH2h"]["config"], "metrics": r["selectedH2h"]["metrics"], "candidates":len(r["allCandidatesIncludingNegative"])}))
    elif args.action == "assess":
        r = m.assess(args.output)
        print(json.dumps({"decision":r["decision"], "gate":r["gate"], "support":r["support"], "metrics":{k:v["metrics"] for k,v in r["comparisons"].items()}}))
    else:
        m.checked_design(args.output)
        # Deterministic recomputation must match immutable evidence byte-for-byte.
        m.development_diagnosis(args.output)
        m.select_development(args.output)
        m.assess(args.output)
        preserved = json.loads((args.output/"PRESERVATION_BEFORE.json").read_bytes())
        for ref in preserved["files"]:
            if m.physical(ref["path"]) != ref:
                raise ValueError("Original artifact changed: " + ref["path"])
        print(json.dumps({"verified":True, "deterministicReplay":True, "preservedFiles":len(preserved["files"]), "assessment":m.physical(args.output/"ASSESSMENT.json")}))
