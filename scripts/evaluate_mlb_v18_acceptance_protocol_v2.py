"""Evaluate records under the immutable MLB V18 prospective protocol V2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_v18_acceptance_protocol_v2 import write_evaluation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    path = write_evaluation(payload, args.output_root)
    result = json.loads((path / "evaluation.json").read_text(encoding="utf-8")) if (path / "evaluation.json").exists() else json.loads((path / "result.json").read_text(encoding="utf-8"))
    print(json.dumps({"path": str(path), "evidenceState": result["evidenceState"],
                      "formalInference": result["formalInference"]["status"],
                      "resultSha256": result["resultSha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
