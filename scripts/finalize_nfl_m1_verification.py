"""Record completed NFL M1 test evidence without rerunning the benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.sports_nfl_m1.benchmark import finalize_benchmark_verification


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tests-passed", type=int, required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            r"C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1\benchmark-summary.json"
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPOSITORY_ROOT
        / "docs"
        / "ASP_NFL_M1_MODELING_BENCHMARK_REPORT.md",
    )
    args = parser.parse_args(argv)
    result = finalize_benchmark_verification(
        args.summary,
        args.report,
        tests_passed=args.tests_passed,
        test_command=args.test_command,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
