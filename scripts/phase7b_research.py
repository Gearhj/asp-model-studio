#!/usr/bin/env python
"""Phase 7B APPROVED research entry point (Phase 7D.1 Gate 11).

The ONLY approved route for the next (Silver) research phase for one trusted local developer. It may:
  - resolve the canonical V3 registry (fail-closed; NO sidecar fallback);
  - obtain a fully VERIFIED research object handle (no bare path, no first-glob selection);
  - inspect registered research metadata;
  - later invoke Silver/Gold builders through explicit research-only interfaces;
  - invoke the canonical 2024-only feature-family ablation.

It REFUSES, structurally: sealed / archived / combined objects, sidecar fallback, and any 2025/2026 access
(a sealed generation cannot even be named). It does NOT normalize Bronze or create features in this phase.

Usage:
    python -m scripts.phase7b_research --inspect --generation GEN3
"""
from __future__ import annotations

import argparse
import json
import sys

# Only research generations are namable — sealed generations (GEN2_SEALED/GEN3_SEALED) are not an option.
_RESEARCH_GENERATIONS = ("GEN2", "GEN3")
_FORBIDDEN_SEASONS = (2025, 2026)


def _research_summary(generation: str) -> dict:
    from server.sports_cockpit import gen3_authority as A  # imported lazily so --help needs no runtime

    if generation not in _RESEARCH_GENERATIONS:
        raise SystemExit(f"REFUSED: {generation!r} is not a selectable research generation")
    handle = A.verified_research_object(generation)  # canonical registry + COMPLETE verification, fail-closed
    seasons = [int(s) for s in (handle.get("seasons") or [])]
    if any(s in _FORBIDDEN_SEASONS for s in seasons):
        raise SystemExit("REFUSED: a sealed/prohibited season is present in the resolved research object")
    if handle.get("capability") != "RESEARCH_OBJECT_READ" or handle.get("verificationState") != "VERIFIED":
        raise SystemExit("REFUSED: object did not resolve under the research-only verified capability")
    return {
        "entryPoint": "PHASE_7B_RESEARCH_V1", "generation": handle["generation"],
        "datasetVersionId": handle["datasetVersionId"], "capability": handle["capability"],
        "verificationState": handle["verificationState"], "objectKind": handle["objectKind"],
        "rows": handle["rows"], "seasons": seasons, "developmentSeasons": handle["developmentSeasons"],
        "validationSeason": handle["validationSeason"], "sealedSeasons": handle["sealedSeasons"],
        "featureCount": handle["featureCount"], "logicalContentSha256": handle["logicalContentSha256"],
        "contractBundleSha256": handle["contractBundleSha256"], "contracts": handle["contracts"],
        "note": "research-only; Bronze normalization and feature creation are NOT enabled in this phase",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 7B approved research entry point (research-only)")
    ap.add_argument("--generation", choices=list(_RESEARCH_GENERATIONS), default="GEN3")
    ap.add_argument("--inspect", action="store_true", help="print the verified research object summary")
    args = ap.parse_args(argv)
    if not args.inspect:
        ap.error("this phase supports only --inspect (no Bronze normalization / feature creation)")
    json.dump(_research_summary(args.generation), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
