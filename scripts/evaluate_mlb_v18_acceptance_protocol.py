"""Evaluate exported AISP V18 research-shadow records under the frozen protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_v18_acceptance_protocol import write_evaluation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Immutable AISP record export JSON")
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/mlb-v18-acceptance-evaluations")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    target = write_evaluation(payload, args.output_root)
    result = json.loads((target / "evaluation.json").read_text(encoding="utf-8"))
    print(json.dumps({
        "evidenceState": result["evidenceState"], "pairedGames": result["metrics"]["pairedGames"],
        "resultSha256": result["resultSha256"], "path": str(target),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
