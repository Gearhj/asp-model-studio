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
import re
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


_PY_EXT_RE = re.compile(r"\.py(?=::|$)")


def _canon_parity(nodeid: str) -> str:
    """Namespace-neutral parity key. pytest emits COLLECTED ids in the file-path namespace
    (``tests/foo_test.py::Cls::m``) but junit ids in the dotted-classname namespace
    (``tests.foo_test.Cls::m``); both collapse to ``tests.foo_test.Cls.m`` here so collection<->junit parity can be
    compared across the two namespaces (the real corpus junit carries a dotted classname and no file= attr).

    D8 (no-file fallback) — the trailing parametrization ``[...]`` is kept BYTE-VERBATIM and is never slash->dot
    normalized: ``[param/a]`` and ``[param.a]`` are DISTINCT identities and must not collapse to one key even when the
    junit omits ``file=``. Only the module/class/function segment is namespace-folded; a distinct-but-colliding
    identity there is still caught by the raw-duplicate and PRECISE-identity checks."""
    head, param = _split_param(nodeid.replace("\\", "/").strip())
    head = _PY_EXT_RE.sub("", head)
    return head.replace("/", ".").replace("::", ".") + param


def _split_param(node: str) -> tuple[str, str]:
    """Separate the trailing ``[...]`` parametrization verbatim so its interior (which may contain ``/``, ``.`` or
    ``::``) is NEVER transformed or split. Returns ``(head, param)`` where ``param`` includes the brackets or ``''``."""
    s = node.strip()
    if s.endswith("]"):
        lb = s.rfind("[")
        if lb != -1:
            return s[:lb], s[lb:]
    return s, ""


def _module_components(file_path: str) -> tuple[str, ...]:
    """Non-lossy module identity: split ONLY on the path separator (a dotted filename such as ``a.b_test.py`` stays a
    single component and is never confused with the directory ``a/b_test.py``); drop a single trailing ``.py``."""
    comps = [c for c in _norm_node(file_path).split("/") if c != ""]
    if comps and comps[-1].endswith(".py"):
        comps[-1] = comps[-1][:-3]
    return tuple(comps)


def _collected_identity(nodeid: str) -> tuple:
    """PRECISE, non-lossy structured identity of a COLLECTED node id (file-path namespace):
    ``(module_components, class_chain, test_name_with_param)``. The exact repo-relative file path, class path,
    test name, and complete parametrization id are all preserved distinctly."""
    head, param = _split_param(_norm_node(nodeid))
    parts = head.split("::")
    module = _module_components(parts[0])
    rest = parts[1:]
    if rest:
        klass = tuple(rest[:-1])
        name = rest[-1] + param
    else:
        klass = ()
        name = param
    return (module, klass, name)


def _junit_identity(file_attr: str, classname: str, name: str) -> tuple:
    """PRECISE, non-lossy structured identity of a JUnit testcase that carries a ``file`` attribute. The class chain
    is recovered as the dotted classname suffix beyond the file-derived module path; a classname inconsistent with
    the file is preserved in full so it can never spuriously match a differently-classed collected node."""
    module = _module_components(file_attr)
    module_dotted = ".".join(module)
    cn = (classname or "").strip()
    if not cn or cn == module_dotted:
        klass: tuple = ()
    elif cn.startswith(module_dotted + "."):
        klass = tuple(cn[len(module_dotted) + 1:].split("."))
    else:
        klass = ("\x00classname", *tuple(cn.split(".")))
    return (module, klass, _norm_node(name))


def parse_collected(path: Path) -> list[str]:
    """Raw collected node ids in file order, PRESERVING multiplicity (no set/dict dedup): duplicate raw collected
    identities are a fail-closed defect, so they must survive to the analyzer, not be silently collapsed here."""
    nodes = []
    # utf-8-sig strips a UTF-8 BOM (PowerShell Set-Content -Encoding utf8 writes one); also lstrip any residual BOM
    # per line so the FIRST collected node is never silently dropped by a leading ﻿.
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        s = line.strip().lstrip("﻿")
        if "::" in s and (s.startswith("tests/") or s.startswith("tests\\") or s.startswith("tests.")):
            nodes.append(_norm_node(s))
    return nodes


def parse_junit(path: Path) -> list[dict]:
    """Ordered JUnit testcase records, PRESERVING multiplicity (no dict-assignment dedup): each record keeps the exact
    raw identity components (file attr, classname, name) so duplicate raw JUnit identities and lossy-alias collisions
    are detectable before any normalization."""
    root = ET.parse(path).getroot()
    out: list[dict] = []
    for tc in root.iter("testcase"):
        file_attr = _norm_node(tc.get("file", ""))
        classname = tc.get("classname", "")
        name = tc.get("name", "")
        nodeid = _norm_node(f"{file_attr}::{name}" if file_attr else f"{classname}::{name}")
        status = "passed"
        reason = ""
        if tc.find("skipped") is not None:
            status = "skipped"
            reason = (tc.find("skipped").get("message") or tc.find("skipped").text or "").strip()
        elif tc.find("failure") is not None:
            status = "failed"
        elif tc.find("error") is not None:
            status = "error"
        out.append({"file": file_attr, "classname": classname, "name": name, "nodeid": nodeid,
                    "rawIdentity": f"{file_attr}\x1f{classname}\x1f{name}", "status": status, "reason": reason})
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
    collected_raw = parse_collected(args.collected)          # RAW, multiplicity-preserving (D8 9.1)
    collected = sorted(set(collected_raw))                   # de-duped view for the existing set/digest logic
    junit_records = parse_junit(args.junit)                  # RAW records, multiplicity-preserving (D8 9.1)
    junit = {rec["nodeid"]: {"status": rec["status"], "reason": rec["reason"]} for rec in junit_records}
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
    # (1a) RAW multiplicity authority (D8 9.1): count raw identities BEFORE any normalization/dedup. A duplicate raw
    # collected node id, or a duplicate raw JUnit testcase identity, is a fail-closed cardinality defect — a plain
    # ``set()``/dict-assignment would silently erase it and mask a missing or double-counted result.
    seen_c: dict[str, int] = {}
    for n in collected_raw:
        seen_c[n] = seen_c.get(n, 0) + 1
    for n in sorted(k for k, c in seen_c.items() if c > 1):
        fails.append(f"DUPLICATE COLLECTED NODE IDENTITY (multiplicity/cardinality != 1): {n} (x{seen_c[n]})")
    seen_j: dict[str, int] = {}
    for rec in junit_records:
        seen_j[rec["rawIdentity"]] = seen_j.get(rec["rawIdentity"], 0) + 1
    for raw in sorted(k for k, c in seen_j.items() if c > 1):
        who = raw.replace("\x1f", "::")
        fails.append(f"DUPLICATE JUNIT TESTCASE IDENTITY (multiplicity/cardinality != 1): {who} (x{seen_j[raw]})")
    # (1b) EXACT collection<->junit parity (namespace-neutral): every collected node must be executed, and vice
    # versa. collected ids are file-path-namespaced and junit ids are dotted-classname-namespaced, so parity is
    # compared on the canonical key (see _canon_parity) rather than on the raw, non-comparable strings.
    # D8 — the canonical key MUST be INJECTIVE: two distinct raw node ids collapsing to one key would let a plain
    # dict silently overwrite and hide a missing/duplicate execution result. Build multimaps (never overwrite),
    # treat any key that maps >1 distinct raw id on EITHER side as a FATAL collision, then compare the one-to-one
    # keyed sets. Every collected node must map to exactly one execution result and vice versa.
    col_mm: dict[str, list[str]] = {}
    for n in collected:
        col_mm.setdefault(_canon_parity(n), []).append(n)
    jun_mm: dict[str, list[str]] = {}
    for n in junit:
        jun_mm.setdefault(_canon_parity(n), []).append(n)
    for key, raws in sorted(col_mm.items()):
        distinct = sorted(set(raws))
        if len(distinct) > 1:
            fails.append(f"CANONICAL KEY COLLISION (collection not injective / not one-to-one): {distinct}")
    for key, raws in sorted(jun_mm.items()):
        distinct = sorted(set(raws))
        if len(distinct) > 1:
            fails.append(f"CANONICAL KEY COLLISION (junit not injective / not one-to-one): {distinct}")
    for k in sorted(set(col_mm) - set(jun_mm)):
        fails.append(f"COLLECTED NODE MISSING FROM JUNIT (never executed): {col_mm[k][0]}")
    for k in sorted(set(jun_mm) - set(col_mm)):
        fails.append(f"JUNIT NODE NOT IN COLLECTION (unexpected execution): {jun_mm[k][0]}")
    # (1b-precise) NON-LOSSY IDENTITY parity. When JUnit carries file= attributes (the exact repo-relative slashed
    # path is known on BOTH sides), reconcile the precise structured identity — module components (split on the path
    # separator only, so ``a.b_test.py`` never aliases the directory ``a/b_test.py``), class chain, and the verbatim
    # test name+parametrization (its ``/`` and ``.`` are never rewritten). A collected and a JUnit identity that only
    # collapse to one lossy key but differ structurally are an alias/mismatch, not one-to-one — fail closed; and each
    # precise identity must have cardinality exactly one on both sides before any set-equality is trusted.
    if any(rec["file"] for rec in junit_records):
        col_struct: dict[tuple, list[str]] = {}
        for n in collected:
            col_struct.setdefault(_collected_identity(n), []).append(n)
        jun_struct: dict[tuple, list[str]] = {}
        for rec in junit_records:
            ident = _junit_identity(rec["file"], rec["classname"], rec["name"]) if rec["file"] \
                else _collected_identity(rec["nodeid"])
            jun_struct.setdefault(ident, []).append(rec["rawIdentity"])
        for ident, raws in sorted(col_struct.items(), key=lambda kv: str(kv[0])):
            if len(set(raws)) > 1:
                fails.append(f"PRECISE COLLECTED IDENTITY CARDINALITY != 1 (multiplicity / not one-to-one): {sorted(set(raws))}")
        for ident, raws in sorted(jun_struct.items(), key=lambda kv: str(kv[0])):
            if len(set(raws)) > 1:
                who = sorted(r.replace("\x1f", "::") for r in set(raws))
                fails.append(f"PRECISE JUNIT IDENTITY CARDINALITY != 1 (multiplicity / not one-to-one): {who}")
        for ident in sorted(set(col_struct) - set(jun_struct), key=str):
            fails.append(f"PRECISE COLLECTED IDENTITY MISSING FROM JUNIT (alias/mismatch, identity not one-to-one): {col_struct[ident][0]}")
        for ident in sorted(set(jun_struct) - set(col_struct), key=str):
            who = jun_struct[ident][0].replace("\x1f", "::")
            fails.append(f"PRECISE JUNIT IDENTITY NOT IN COLLECTION (alias/mismatch, identity not one-to-one): {who}")
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
                fails.append(f"SKIP CATEGORY CHANGED (reason-code) for {n}: policy={pol.get('reasonCode')} actual={code}")
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
