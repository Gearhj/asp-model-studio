"""Build the descriptive Gen 1 bet-readiness cohort from a read-only AISP export."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.sports_current_statcast.mlb_bet_readiness_cohort import write_cohort


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=ROOT / "outputs/mlb-gen1-bet-readiness-cohort")
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    path = write_cohort(payload, args.output_root)
    cohort = json.loads((path / "cohort.json").read_text(encoding="utf-8"))
    latest = {"cohortSha256": cohort["cohortSha256"],
              "relativePath": path.resolve().relative_to(ROOT).as_posix(),
              "sourceExportSha256": cohort["sourceExportSha256"]}
    (args.output_root / "latest.json").write_text(
        json.dumps(latest, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    print(json.dumps({"path": str(path), "cohortSha256": cohort["cohortSha256"],
                      "decisions": cohort["funnel"]["decisionEvaluations"],
                      "events": cohort["funnel"]["distinctEvents"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
