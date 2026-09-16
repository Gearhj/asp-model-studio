#!/usr/bin/env python
"""Phase 7B APPROVED research entry point (Phase 7D.1 Gate 11).

The ONLY approved route for the next (Silver) research phase for one trusted local developer. It may:
  - resolve the canonical V3 registry (fail-closed; NO sidecar fallback);
  - obtain a fully VERIFIED research object handle (no bare path, no first-glob selection);
  - inspect registered research metadata;
  - invoke the Phase 7B2 Gold V1 builder and fixed research experiment through
    explicit research-only interfaces;
  - invoke the canonical 2024-only feature-family ablation.

It REFUSES, structurally: sealed / archived / combined objects, sidecar fallback, and any 2025/2026 access
(a sealed generation cannot even be named). Gold V1 reads only verified current Silver and the physically
separated Gen3 2021--2024 research object; it never normalizes Bronze or changes Silver quarantine.

Usage:
    python -m scripts.phase7b_research --inspect --generation GEN3
    python -m scripts.phase7b_research --build-gold-v1
    python -m scripts.phase7b_research --run-gold-v1
    python -m scripts.phase7b_research --gold-v1-all
    python -m scripts.phase7b_research --binary-hierarchical
    python -m scripts.phase7b_research --hierarchical-robustness
    python -m scripts.phase7b_research --recent-state-ensemble
    python -m scripts.phase7b_research --recent-data-walk-forward
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Only research generations are namable — sealed generations (GEN2_SEALED/GEN3_SEALED) are not an option.
_RESEARCH_GENERATIONS = ("GEN2", "GEN3")
_FORBIDDEN_SEASONS = (2025, 2026)


def _research_summary(generation: str) -> dict:
    from server.sports_cockpit import (
        gen3_authority as A,
    )  # imported lazily so --help needs no runtime

    if generation not in _RESEARCH_GENERATIONS:
        raise SystemExit(
            f"REFUSED: {generation!r} is not a selectable research generation"
        )
    handle = A.verified_research_object(
        generation
    )  # canonical registry + COMPLETE verification, fail-closed
    seasons = [int(s) for s in (handle.get("seasons") or [])]
    if any(s in _FORBIDDEN_SEASONS for s in seasons):
        raise SystemExit(
            "REFUSED: a sealed/prohibited season is present in the resolved research object"
        )
    if (
        handle.get("capability") != "RESEARCH_OBJECT_READ"
        or handle.get("verificationState") != "VERIFIED"
    ):
        raise SystemExit(
            "REFUSED: object did not resolve under the research-only verified capability"
        )
    return {
        "entryPoint": "PHASE_7B_RESEARCH_V1",
        "generation": handle["generation"],
        "datasetVersionId": handle["datasetVersionId"],
        "capability": handle["capability"],
        "verificationState": handle["verificationState"],
        "objectKind": handle["objectKind"],
        "rows": handle["rows"],
        "seasons": seasons,
        "developmentSeasons": handle["developmentSeasons"],
        "validationSeason": handle["validationSeason"],
        "sealedSeasons": handle["sealedSeasons"],
        "featureCount": handle["featureCount"],
        "logicalContentSha256": handle["logicalContentSha256"],
        "contractBundleSha256": handle["contractBundleSha256"],
        "contracts": handle["contracts"],
        "note": "research-only; Bronze normalization and feature creation are NOT enabled in this phase",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Phase 7B approved research entry point (research-only)"
    )
    ap.add_argument("--generation", choices=list(_RESEARCH_GENERATIONS), default="GEN3")
    actions = ap.add_mutually_exclusive_group(required=True)
    actions.add_argument(
        "--inspect",
        action="store_true",
        help="print the verified research object summary",
    )
    actions.add_argument(
        "--build-gold-v1", action="store_true", help="build the immutable Gold V1 table"
    )
    actions.add_argument(
        "--run-gold-v1",
        action="store_true",
        help="run the fixed suite on an existing Gold V1 table",
    )
    actions.add_argument(
        "--gold-v1-all",
        action="store_true",
        help="build Gold V1, then run the fixed suite",
    )
    actions.add_argument(
        "--binary-hierarchical",
        action="store_true",
        help="run the fixed BATTER_RETIRED binary/hierarchical experiment on existing Gold V1",
    )
    actions.add_argument(
        "--hierarchical-robustness",
        action="store_true",
        help="run the development-selected Phase 7B3 hierarchical robustness study",
    )
    actions.add_argument(
        "--recent-state-ensemble",
        action="store_true",
        help="run the fixed Phase 7B4 recent-state, matchup, and ensemble study",
    )
    actions.add_argument(
        "--recent-data-walk-forward",
        action="store_true",
        help="run the final-14-day Phase 7B5 daily walk-forward study",
    )
    ap.add_argument(
        "--silver-root",
        type=Path,
        default=Path(r"C:\Users\james\asp-data-staging\mlb-silver-v1"),
        help="existing Phase 7B1 Silver root",
    )
    ap.add_argument(
        "--gold-root",
        type=Path,
        default=Path(r"C:\Users\james\asp-data-staging\mlb-gold-v1"),
        help="external Gold V1 artifact root (never committed)",
    )
    ap.add_argument(
        "--no-xgboost",
        action="store_true",
        help="skip the optional installed XGBoost candidate",
    )
    args = ap.parse_args(argv)
    if (
        args.binary_hierarchical
        or args.hierarchical_robustness
        or args.recent_state_ensemble
        or args.recent_data_walk_forward
    ) and args.no_xgboost:
        ap.error(
            "--no-xgboost applies to --run-gold-v1/--gold-v1-all, not the fixed persisted hierarchy sources"
        )
    if args.inspect:
        payload = _research_summary(args.generation)
    else:
        if args.generation != "GEN3":
            ap.error(
                "Gold V1 is bound to the verified GEN3 2021--2024 target/base object"
            )
        from server.sports_gold.pipeline import (
            _json_safe,
            build_gold_v1,
            run_gold_experiment,
        )

        payload: dict = {"entryPoint": "PHASE_7B2_GOLD_V1_RESEARCH_V1"}
        if args.build_gold_v1 or args.gold_v1_all:
            built = build_gold_v1(
                silver_root=args.silver_root, gold_root=args.gold_root
            )
            payload["build"] = {
                "status": built["status"],
                "dataset": built["dataset"],
                "connection": built["connection"],
                "quality": built["quality"],
            }
        if args.run_gold_v1 or args.gold_v1_all:
            payload["experiment"] = run_gold_experiment(
                gold_root=args.gold_root, include_xgboost=not args.no_xgboost
            )
        if args.binary_hierarchical:
            from server.sports_gold.binary_hierarchical import (
                run_binary_hierarchical_experiment,
            )

            payload["binaryHierarchical"] = run_binary_hierarchical_experiment(
                gold_root=args.gold_root,
                progress=lambda message: print(
                    f"[binary-hierarchical] {message}", file=sys.stderr
                ),
            )
        if args.hierarchical_robustness:
            from server.sports_gold.hierarchical_robustness import (
                run_hierarchical_robustness_study,
            )

            payload["entryPoint"] = "PHASE_7B3_HIERARCHICAL_ROBUSTNESS_RESEARCH_V1"
            payload["hierarchicalRobustness"] = run_hierarchical_robustness_study(
                gold_root=args.gold_root,
                progress=lambda message: print(
                    f"[hierarchical-robustness] {message}", file=sys.stderr
                ),
            )
        if args.recent_state_ensemble:
            from server.sports_gold.recent_state_study import (
                run_recent_state_matchup_ensemble_study,
            )

            payload["entryPoint"] = (
                "PHASE_7B4_RECENT_STATE_MATCHUP_ENSEMBLE_RESEARCH_V1"
            )
            payload["recentStateEnsemble"] = run_recent_state_matchup_ensemble_study(
                gold_root=args.gold_root,
                progress=lambda message: print(
                    f"[recent-state-ensemble] {message}", file=sys.stderr
                ),
            )
        if args.recent_data_walk_forward:
            from server.sports_gold.recent_data_walk_forward import (
                run_recent_data_walk_forward_study,
            )

            payload["entryPoint"] = "PHASE_7B5_RECENT_DATA_WALK_FORWARD_RESEARCH_V1"
            payload["recentDataWalkForward"] = run_recent_data_walk_forward_study(
                gold_root=args.gold_root,
                silver_root=args.silver_root,
                progress=lambda message: print(
                    f"[recent-data-walk-forward] {message}", file=sys.stderr
                ),
            )
    if not args.inspect:
        payload = _json_safe(payload)
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
