"""Phase 7D.5A.1 (Workstream 2) — fail-closed skip governance for the isolated governed gate.

Parses a pytest JUnit XML, classifies EVERY skipped test against an explicit policy, and fails closed when:
  * a Phase-7D.5A CRITICAL ingress-safety test is skipped (never permitted — a missing synthetic fixture is not
    permission to skip a safety behavior);
  * a skip reason does not match any allowed, explicitly-justified category (unknown/unclassified);
  * a NEW skip node appears that is not in the committed baseline allowlist (an unexpected skip-set change).
It emits a machine-readable skip manifest (grouped by category, with counts and node lists) to the log dir.

Usage:
    python scripts/phase7d5a_skip_governance.py --junit <gate-junit.xml> --out <skip-manifest.json>
                                                [--baseline scripts/phase7d5a_skip_baseline.json]
                                                [--write-baseline]

Exit code 0 = governance passed; non-zero = a governance violation (the gate must fail).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# ---- CRITICAL Phase-7D.5A ingress-safety test files: ANY skip of a test in these files is a violation. ------
CRITICAL_FILE_PATTERNS = (
    "sports_cockpit_phase7d5a_silver_test",
    "sports_cockpit_phase7d5a_silver_concurrency_test",
    "sports_cockpit_phase7d5a_reparse_test",
    "sports_cockpit_phase7d5a_champion2024_test",
    "sports_cockpit_phase7d5a_cleanup_test",
    "sports_cockpit_phase7d5a_isolation_test",
    "sports_cockpit_phase7d5a1_season_roles_test",
    "sports_modeling_feature_semantics_test",
)

# ---- Allowed, explicitly-justified NON-CRITICAL skip categories: reason-substring -> category label. --------
# Each is an out-of-scope requirement that cannot be satisfied by small hermetic data without copying the
# shared runtime (forbidden), and whose equivalent critical behavior is covered hermetically elsewhere.
ALLOWED_CATEGORIES = (
    ("D3 feature view not materialized", "real_d3_gen2_view"),
    ("feature view not materialized", "real_d3_gen2_view"),
    ("feature view / play_transition", "real_d3_gen2_view"),
    ("Gen-3 v2 authority not published", "real_published_authority"),
    ("Gen-3 feature view not materialized", "real_gen3_v1_view"),
    ("reconciliation not run", "real_reconciliation_artifact"),
    ("governed-logistic reconciliation", "real_reconciliation_artifact"),
    ("REAL production development", "real_reconciliation_artifact"),
    ("synthetic seed", "real_data_only_under_synthetic_seed"),
    ("play_transition", "historical_phase5_simulation"),
    ("simulation", "historical_phase5_simulation"),
    ("monte", "historical_phase5_simulation"),
    ("starter", "historical_phase5_simulation"),
    ("participation ablation", "historical_phase5_simulation"),
    ("ablation record not present", "historical_phase5_simulation"),
    ("governed d3 runtime artifacts not present", "historical_phase5_simulation"),
    # Gold / model-exchange governance layer: the golden-package, identity-bridge, and registered data-access
    # tests require ASP_MODEL_EXCHANGE_ROOT pointing at the real golden exchange corpus (a large pre-existing
    # artifact, out of scope for the Silver-ingress gate and NOT a Silver-ingress safety behavior).
    ("asp_model_exchange_root is required", "real_model_exchange_golden_corpus"),
    ("browser tooling", "optional_live_browser_tooling"),
    ("node", "optional_live_browser_tooling"),
    ("playwright", "optional_live_browser_tooling"),
    ("chromium", "optional_live_browser_tooling"),
    ("live server", "optional_live_server_tooling"),
    ("uvicorn", "optional_live_server_tooling"),
    ("reparse-point creation not permitted", "os_capability_non_windows"),
    ("symlink", "os_capability_non_windows"),
)


def _classify(reason: str) -> str | None:
    low = (reason or "").lower()
    for needle, category in ALLOWED_CATEGORIES:
        if needle.lower() in low:
            return category
    return None


def _is_critical(nodeid: str) -> bool:
    return any(pat in nodeid for pat in CRITICAL_FILE_PATTERNS)


def _parse_junit(path: Path) -> list[dict]:
    root = ET.parse(path).getroot()
    skips = []
    for tc in root.iter("testcase"):
        sk = tc.find("skipped")
        if sk is None:
            continue
        classname = tc.get("classname", "") or ""
        name = tc.get("name", "") or ""
        file_attr = tc.get("file", "")
        nodeid = f"{file_attr}::{name}" if file_attr else f"{classname}::{name}"
        reason = (sk.get("message") or sk.text or "").strip()
        skips.append({"nodeid": nodeid, "classname": classname, "name": name, "reason": reason})
    return skips


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--junit", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--baseline", type=Path, default=Path(__file__).with_name("phase7d5a_skip_baseline.json"))
    ap.add_argument("--write-baseline", action="store_true",
                    help="record the current skip node set as the baseline (policy update; run intentionally)")
    args = ap.parse_args()

    if not args.junit.is_file():
        print(f"SKIP-GOV FAIL: junit xml not found: {args.junit}", file=sys.stderr)
        return 3
    skips = _parse_junit(args.junit)

    critical_violations, unknown_violations, grouped = [], [], {}
    for s in skips:
        if _is_critical(s["nodeid"]):
            critical_violations.append(s)
            continue
        cat = _classify(s["reason"])
        if cat is None:
            unknown_violations.append(s)
            cat = "UNCLASSIFIED"
        grouped.setdefault(cat, []).append(s["nodeid"])

    current_nodes = sorted(s["nodeid"] for s in skips)
    if args.write_baseline:
        args.baseline.write_text(json.dumps({"skipNodes": current_nodes}, indent=2), encoding="utf-8")
        print(f"SKIP-GOV: wrote baseline ({len(current_nodes)} nodes) to {args.baseline}")

    baseline_nodes, new_unexpected = [], []
    if args.baseline.is_file():
        baseline_nodes = json.loads(args.baseline.read_text(encoding="utf-8")).get("skipNodes", [])
        baseline_set = set(baseline_nodes)
        new_unexpected = [n for n in current_nodes if n not in baseline_set]

    manifest = {
        "schema": "PHASE_7D5A_SKIP_MANIFEST_V1",
        "totalSkipped": len(skips),
        "categories": {k: {"count": len(v), "nodes": sorted(v)} for k, v in sorted(grouped.items())},
        "criticalViolations": critical_violations,
        "unknownSkipReasons": unknown_violations,
        "newUnexpectedVsBaseline": new_unexpected,
        "baselineNodeCount": len(baseline_nodes),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    ok = True
    if critical_violations:
        ok = False
        print(f"SKIP-GOV FAIL: {len(critical_violations)} CRITICAL ingress-safety test(s) skipped:", file=sys.stderr)
        for s in critical_violations:
            print(f"    CRITICAL SKIP  {s['nodeid']}  ({s['reason']})", file=sys.stderr)
    if unknown_violations:
        ok = False
        print(f"SKIP-GOV FAIL: {len(unknown_violations)} skip(s) with unclassified reason:", file=sys.stderr)
        for s in unknown_violations:
            print(f"    UNKNOWN SKIP   {s['nodeid']}  ({s['reason']})", file=sys.stderr)
    if new_unexpected and not args.write_baseline:
        ok = False
        print(f"SKIP-GOV FAIL: {len(new_unexpected)} NEW skip(s) not in the committed baseline "
              f"(a skip-set change requires an explicit --write-baseline policy update):", file=sys.stderr)
        for n in new_unexpected:
            print(f"    NEW SKIP       {n}", file=sys.stderr)

    print(f"SKIP-GOV: total_skipped={len(skips)} categories={ {k: len(v) for k, v in grouped.items()} } "
          f"manifest={args.out}")
    if ok:
        print("SKIP-GOV PASS: no critical skips, no unknown reasons, no unexpected skip-set change.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
