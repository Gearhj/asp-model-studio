"""Run the bounded NFL M1 chronological score-distribution benchmark."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from server.sports_nfl_m1.benchmark import BenchmarkConfig, run_benchmark


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--foundation-root",
        type=Path,
        default=Path(r"C:\Users\james\asp-data-staging\nfl\foundation-v1"),
    )
    parser.add_argument(
        "--external-root",
        type=Path,
        default=Path(r"C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1"),
    )
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "nfl_m1",
    )
    parser.add_argument("--oof-draws", type=int, default=2_000)
    parser.add_argument("--oot-draws", type=int, default=10_000)
    parser.add_argument("--bootstrap-resamples", type=int, default=2_000)
    parser.add_argument("--seed", type=int, default=731_001)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def progress(message: str) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        print(f"[{stamp}] {message}", flush=True)

    try:
        summary = run_benchmark(
            BenchmarkConfig(
                foundation_root=args.foundation_root,
                external_root=args.external_root,
                docs_root=args.docs_root,
                seed=args.seed,
                oof_draws=args.oof_draws,
                oot_draws=args.oot_draws,
                bootstrap_resamples=args.bootstrap_resamples,
            ),
            progress=progress,
        )
    except Exception as exc:
        print(
            f"ASP_NFL_M1_MODELING_BENCHMARK_BLOCKED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        raise
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))
    print("ASP_NFL_M1_MODELING_BENCHMARK_COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
