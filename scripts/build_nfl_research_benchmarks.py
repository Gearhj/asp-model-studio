"""Build read-only matched Development comparisons, optionally new candidate OOF."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from server.sports_nfl_m1.research_benchmarks import DEFAULT_OUTPUT, evaluate

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    sources = parser.add_mutually_exclusive_group()
    sources.add_argument("--candidates", type=Path, help="JSON map of model ID to saved compatible OOF parquet; calibrated IDs end in _CALIBRATED")
    sources.add_argument("--semantic-current", type=Path, help="Completed semantic CURRENT.json; include all new raw and calibrated OOF, not duplicated baseline entries")
    args = parser.parse_args()
    candidates = None if args.candidates is None else {k: Path(v) for k, v in json.loads(args.candidates.read_text()).items()}
    if args.semantic_current:
        pointer = json.loads(args.semantic_current.read_text())
        payload = Path(pointer["resultPath"]).read_bytes()
        if pointer.get("status") != "COMPLETED" or hashlib.sha256(payload).hexdigest() != pointer["resultSha256"]:
            raise ValueError("completed semantic result identity required")
        result = json.loads(payload)
        candidates = {row["pipelineId"] + "_" + kind: Path(row["oofPath"]) for row in result["results"]
                      if row["status"].startswith("COMPLETED") for kind in ("RAW", "CALIBRATED")}
    print(json.dumps(evaluate(args.output, candidates), indent=2))
