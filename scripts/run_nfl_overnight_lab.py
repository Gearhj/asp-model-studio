"""Run the frozen Development-only NFL overnight model laboratory."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from server.sports_nfl_m1.overnight_lab import LabConfig, run_overnight_lab
from server.sports_nfl_m1.lab_registration import DEFAULT_DATABASE_PATH, register_overnight_lab


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--external-root", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--draws", type=int, default=2_000)
    parser.add_argument("--tuning-draws", type=int, default=1_000)
    parser.add_argument("--bootstrap-resamples", type=int, default=1_000)
    parser.add_argument("--database-path", type=Path, default=DEFAULT_DATABASE_PATH)
    parser.add_argument("--skip-workflow-registration", action="store_true")
    arguments = parser.parse_args()
    defaults = LabConfig()
    result = run_overnight_lab(LabConfig(
        external_root=arguments.external_root or defaults.external_root,
        output_root=arguments.output_root or defaults.output_root,
        draws=arguments.draws,
        tuning_draws=arguments.tuning_draws,
        bootstrap_resamples=arguments.bootstrap_resamples,
    ))
    registration = None if arguments.skip_workflow_registration else register_overnight_lab(
        result,
        manifest_sha256=result["manifestSha256"],
        handoff_path=result["handoffPath"],
        handoff_sha256=result["handoffSha256"],
        database_path=arguments.database_path,
    )
    print(json.dumps({
        "handoffPath": result["handoffPath"],
        "handoffSha256": result["handoffSha256"],
        "manifestSha256": result["manifestSha256"],
        "developmentSelectedPipeline": result["developmentSelectedPipeline"],
        "finalOotAccessed": result["finalOotAccessed"],
        "workflowRegistration": registration,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
