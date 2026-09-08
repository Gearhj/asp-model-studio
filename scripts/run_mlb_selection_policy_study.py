"""Run the bounded MLB selection-policy study from immutable local artifacts."""

from __future__ import annotations

import argparse
from pathlib import Path

from server.sports_current_statcast.mlb_selection_policy_study import write_study


DEFAULT_COHORT = Path(
    "outputs/mlb-gen1-bet-readiness-cohort/sha256/"
    "cd44ef70d6d4a5f3258cfad2cd6222accc5a39431d131184cf7b851ecced5785"
)
DEFAULT_V18_HANDOFF = Path(
    "outputs/mlb-v18-daily-slate/handoffs/sha256/"
    "3bbada26170778ca0d26ace39dc86fffbccfb3a82924872fd6dc1a1adef6014a/aisp-handoff.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--v18-handoff", type=Path, default=DEFAULT_V18_HANDOFF)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/mlb-selection-policy-study"))
    parser.add_argument(
        "--aisp-audit",
        type=Path,
        default=Path("C:/Users/james/ai-sports-predictor/outputs/mlb-policy-availability-audit/audit.json"),
    )
    args = parser.parse_args()
    target = write_study(
        args.cohort / "records.jsonl.gz",
        args.cohort / "cohort.json",
        args.v18_handoff,
        args.output_root,
        aisp_audit_path=args.aisp_audit,
    )
    print(target)


if __name__ == "__main__":
    main()
