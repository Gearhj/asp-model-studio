"""Phase 7D.5A.2 (Repair 8) — COLLECTION-AWARE, policy-driven, fail-closed skip governance for the isolated gate.

The prior analyzer only evaluated tests that appeared as skipped in JUnit — a critical test silently dropped from
COLLECTION would go unnoticed — and classified reasons with broad substrings. This version enforces an EXACT,
versioned gate policy (``scripts/phase7d5a_gate_policy.json``):

  * runs ``pytest --collect-only`` first and compares the EXACT collected node set + a collection digest against the
    policy — an expected node that disappears, an unexpected node that appears, or a critical node that is not
    collected fails the gate;
  * every CRITICAL node must be collected, must not be skipped, and must PASS;
  * every skipped node must be an explicitly-listed allowed skip whose EXACT normalized reason code AND reason match
    the policy — an unknown node, a changed reason, or a changed category fails the gate.

The policy is NEVER regenerated automatically; ``--write-policy`` records it as a deliberate, reviewed action.

Usage:
    python scripts/phase7d5a_skip_governance.py --collected <collected.txt> --junit <gate-junit.xml>
                                                --out <skip-manifest.json> [--policy <policy.json>] [--write-policy]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

POLICY_SCHEMA = "PHASE_7D5A2_GATE_POLICY_V1"
EXPECTED_POLICY_VERSION = 1
DEFAULT_POLICY = Path(__file__).with_name("phase7d5a_gate_policy.json")

# CRITICAL Phase-7D.5A/.2 ingress-safety test files: any of their nodes must be collected, not skipped, and pass.
CRITICAL_FILE_PATTERNS = (
    "sports_cockpit_phase7d5a2_chronology_test",
    "sports_cockpit_phase7d5a2_source_authority_test",
    "sports_cockpit_phase7d5a2_silver_integrity_test",
    "sports_cockpit_phase7d5a2_quarantine_test",
    "sports_cockpit_phase7d5a2_isolation_guard_test",
    "sports_cockpit_phase7d5a2_skip_governance_test",
    "sports_cockpit_phase7d5a_silver_test",
    "sports_cockpit_phase7d5a_silver_concurrency_test",
    "sports_cockpit_phase7d5a_reparse_test",
    "sports_cockpit_phase7d5a_champion2024_test",
    "sports_cockpit_phase7d5a_cleanup_test",
    "sports_cockpit_phase7d5a_isolation_test",
    "sports_cockpit_phase7d5a1_season_roles_test",
    "sports_modeling_feature_semantics_test",
)

# Exact normalized reason -> reason code (for the ALLOWED, non-critical skips). Exact-substring, ordered.
REASON_CODES = (
    ("D3 feature view not materialized", "REAL_D3_GEN2_VIEW"),
    ("feature view not materialized", "REAL_D3_GEN2_VIEW"),
    ("feature view / play_transition", "REAL_D3_GEN2_VIEW"),
    ("Gen-3 v2 authority not published", "REAL_PUBLISHED_AUTHORITY"),
    ("Gen-3 feature view not materialized", "REAL_GEN3_V1_VIEW"),
    ("reconciliation not run", "REAL_RECONCILIATION_ARTIFACT"),
    ("governed-logistic reconciliation", "REAL_RECONCILIATION_ARTIFACT"),
    ("REAL production development", "REAL_RECONCILIATION_ARTIFACT"),
    ("synthetic seed", "REAL_DATA_ONLY_UNDER_SYNTHETIC_SEED"),
    ("ablation record not present", "HISTORICAL_PHASE5_SIMULATION"),
    ("governed D3 runtime artifacts not present", "HISTORICAL_PHASE5_SIMULATION"),
    ("play_transition", "HISTORICAL_PHASE5_SIMULATION"),
    ("simulation", "HISTORICAL_PHASE5_SIMULATION"),
    ("monte", "HISTORICAL_PHASE5_SIMULATION"),
    ("starter", "HISTORICAL_PHASE5_SIMULATION"),
    ("participation ablation", "HISTORICAL_PHASE5_SIMULATION"),
    ("ASP_MODEL_EXCHANGE_ROOT is required", "REAL_MODEL_EXCHANGE_GOLDEN_CORPUS"),
    ("external FD1 play_transition corpus is out of bounds", "ISOLATED_EXTERNAL_CORPUS"),
    ("shared .runtime governed boundary", "LEGACY_SHARED_RUNTIME_BOUNDARY"),
    ("browser tooling", "OPTIONAL_LIVE_BROWSER_TOOLING"),
    ("playwright", "OPTIONAL_LIVE_BROWSER_TOOLING"),
    ("chromium", "OPTIONAL_LIVE_BROWSER_TOOLING"),
    ("live server", "OPTIONAL_LIVE_SERVER_TOOLING"),
    ("reparse-point creation not permitted", "OS_CAPABILITY_NON_WINDOWS"),
    ("symlink", "OS_CAPABILITY_NON_WINDOWS"),
)


def reason_code(reason: str) -> str | None:
    low = (reason or "").lower()
    for needle, code in REASON_CODES:
        if needle.lower() in low:
            return code
    return None


def is_critical(nodeid: str) -> bool:
    return any(p in nodeid for p in CRITICAL_FILE_PATTERNS)


def _norm_node(nodeid: str) -> str:
    return nodeid.replace("\\", "/").strip()


def parse_collected(path: Path) -> list[str]:
    nodes = []
    # utf-8-sig strips a UTF-8 BOM (PowerShell Set-Content -Encoding utf8 writes one); also lstrip any residual BOM
    # per line so the FIRST collected node is never silently dropped by a leading ﻿.
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip().lstrip("﻿")
        if "::" in s and (s.startswith("tests/") or s.startswith("tests\\") or s.startswith("tests.")):
            nodes.append(_norm_node(s))
    return sorted(set(nodes))


def parse_junit(path: Path) -> dict[str, dict]:
    root = ET.parse(path).getroot()
    out = {}
    for tc in root.iter("testcase"):
        file_attr = tc.get("file", "")
        name = tc.get("name", "")
        nodeid = _norm_node(f"{file_attr}::{name}" if file_attr else f"{tc.get('classname','')}::{name}")
        status = "passed"
        reason = ""
        if tc.find("skipped") is not None:
            status = "skipped"
            reason = (tc.find("skipped").get("message") or tc.find("skipped").text or "").strip()
        elif tc.find("failure") is not None:
            status = "failed"
        elif tc.find("error") is not None:
            status = "error"
        out[nodeid] = {"status": status, "reason": reason}
    return out


def collection_digest(nodes) -> str:
    return hashlib.sha256("\n".join(sorted(nodes)).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collected", required=True, type=Path)
    ap.add_argument("--junit", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--selection", default="")
    ap.add_argument("--write-policy", action="store_true")
    args = ap.parse_args()

    if not args.collected.is_file() or not args.junit.is_file():
        print("SKIP-GOV FAIL: collected/junit input missing", file=sys.stderr)
        return 3
    collected = parse_collected(args.collected)
    junit = parse_junit(args.junit)
    skipped = {n: v["reason"] for n, v in junit.items() if v["status"] == "skipped"}

    if args.write_policy:
        allowed = {}
        for n, reason in sorted(skipped.items()):
            if is_critical(n):
                continue
            rc = reason_code(reason) or "UNCLASSIFIED"
            allowed[n] = {"reason": reason, "reasonCode": rc, "category": rc}
        policy = {"schemaVersion": POLICY_SCHEMA, "policyVersion": 1, "selection": args.selection,
                  "collectionDigest": collection_digest(collected), "expectedCollected": collected,
                  "criticalPatterns": list(CRITICAL_FILE_PATTERNS), "allowedSkips": allowed}
        args.policy.write_text(json.dumps(policy, indent=2), encoding="utf-8")
        print(f"SKIP-GOV: wrote policy v1 ({len(collected)} collected, {len(allowed)} allowed skips) -> {args.policy}")

    if not args.policy.is_file():
        print(f"SKIP-GOV FAIL: gate policy not found: {args.policy}", file=sys.stderr)
        return 3
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    exp = set(policy["expectedCollected"])
    allowed = policy["allowedSkips"]

    fails: list[str] = []
    # (0) immutable policy-metadata authority (R8): schema version, policy version, selection, critical authority
    if policy.get("schemaVersion") != POLICY_SCHEMA:
        fails.append(f"policy schemaVersion invalid: {policy.get('schemaVersion')!r}")
    if policy.get("policyVersion") != EXPECTED_POLICY_VERSION:
        fails.append(f"policy policyVersion invalid: {policy.get('policyVersion')!r} (expected {EXPECTED_POLICY_VERSION})")
    if args.selection and policy.get("selection") != args.selection:
        fails.append(f"policy selection {policy.get('selection')!r} != gate selection {args.selection!r}")
    if not policy.get("criticalPatterns"):
        fails.append("policy critical authority is erased/empty")
    for n in collected:               # every analyzer-critical collected node must be covered by a policy pattern
        if is_critical(n) and not any(pat in n for pat in policy.get("criticalPatterns", [])):
            fails.append(f"policy critical authority does not cover collected critical node: {n}")
    # (1) exact collection parity
    missing = sorted(exp - set(collected))
    extra = sorted(set(collected) - exp)
    for m in missing:
        fails.append(f"EXPECTED NODE MISSING FROM COLLECTION: {m}")
    for x in extra:
        fails.append(f"UNEXPECTED NODE APPEARED IN COLLECTION (needs reviewed policy update): {x}")
    # (1b) EXACT collection<->junit parity: every collected node must be executed, and vice versa
    junit_nodes = set(junit)
    for n in sorted(set(collected) - junit_nodes):
        fails.append(f"COLLECTED NODE MISSING FROM JUNIT (never executed): {n}")
    for n in sorted(junit_nodes - set(collected)):
        fails.append(f"JUNIT NODE NOT IN COLLECTION (unexpected execution): {n}")
    # (1c) EXACT allowed-skip <-> actual-skip equality: an expected skip that unexpectedly passes fails closed
    for n in sorted(set(allowed) - set(skipped)):
        fails.append(f"EXPECTED ALLOWED SKIP DID NOT SKIP (passed or executed): {n}")
    # (2) collection digest
    if collection_digest(collected) != policy["collectionDigest"]:
        fails.append("COLLECTION DIGEST MISMATCH")
    # (3) every critical pattern must be collected at least once (collected namespace); and every critical node in
    # the junit must have PASSED (junit namespace). parse_collected yields file-path ids and parse_junit yields
    # classname ids, so each check stays within its own namespace (is_critical matches the file substring in both).
    for pat in policy["criticalPatterns"]:
        if not any(pat in n for n in collected):
            fails.append(f"CRITICAL FILE NOT COLLECTED: {pat}")
        if not any(pat in n for n in junit):
            fails.append(f"CRITICAL FILE NOT EXECUTED (absent from junit): {pat}")
    for n, v in junit.items():
        if is_critical(n) and v["status"] != "passed":
            fails.append(f"CRITICAL NODE not passed (status={v['status']}): {n}")
    # (4) skips: exact allowed-skip match (reason + code)
    grouped: dict[str, list[str]] = {}
    for n, reason in sorted(skipped.items()):
        if is_critical(n):
            fails.append(f"CRITICAL NODE SKIPPED: {n} ({reason})")
            continue
        pol = allowed.get(n)
        code = reason_code(reason)
        if pol is None:
            fails.append(f"UNKNOWN SKIP (not in policy): {n} ({reason})")
        else:
            if pol.get("reason") != reason:
                fails.append(f"SKIP REASON CHANGED for {n}: policy={pol.get('reason')!r} actual={reason!r}")
            if pol.get("reasonCode") != code:
                fails.append(f"SKIP REASON-CODE CHANGED for {n}: policy={pol.get('reasonCode')} actual={code}")
            if "category" in pol and pol.get("category") != code:
                fails.append(f"SKIP CATEGORY (independently governed) CHANGED for {n}: policy={pol.get('category')} actual={code}")
        grouped.setdefault(code or "UNCLASSIFIED", []).append(n)

    manifest = {"schema": "PHASE_7D5A2_SKIP_MANIFEST_V1", "collectedCount": len(collected),
                "collectionDigest": collection_digest(collected), "totalSkipped": len(skipped),
                "categories": {k: {"count": len(v), "nodes": sorted(v)} for k, v in sorted(grouped.items())},
                "violations": fails}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    if fails and not args.write_policy:
        print(f"SKIP-GOV FAIL: {len(fails)} governance violation(s):", file=sys.stderr)
        for f in fails[:60]:
            print("    " + f, file=sys.stderr)
        return 1
    print(f"SKIP-GOV: collected={len(collected)} skipped={len(skipped)} "
          f"categories={ {k: len(v) for k, v in grouped.items()} } manifest={args.out}")
    print("SKIP-GOV PASS: exact collection, no critical skip/omission, no unknown/changed skip." if not fails
          else "SKIP-GOV: policy written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
