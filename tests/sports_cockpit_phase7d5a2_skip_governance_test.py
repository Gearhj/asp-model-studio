"""Phase 7D.5A.2 (Repair 8) — the COLLECTION-AWARE skip-governance analyzer must fail closed on every tampered gate.

Each mandatory case builds a synthetic (collected, junit, policy) triple and runs the REAL analyzer CLI, asserting it
exits non-zero. A baseline valid triple must pass.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GOV = REPO / "scripts" / "phase7d5a_skip_governance.py"

CRIT = "tests/sports_cockpit_phase7d5a2_chronology_test.py::test_ok"       # matches a critical file pattern
VIEW = "tests/sports_cockpit_data_preview_test.py::test_view"             # allowed skip
BASE_NODES = [CRIT, VIEW]
VIEW_REASON = "D3 feature view not materialized"


def _digest(nodes):
    import hashlib
    return hashlib.sha256("\n".join(sorted(nodes)).encode()).hexdigest()


def _policy(nodes=BASE_NODES):
    return {"schemaVersion": "PHASE_7D5A2_GATE_POLICY_V1", "policyVersion": 1, "selection": "sel",
            "collectionDigest": _digest(nodes), "expectedCollected": sorted(nodes),
            "criticalPatterns": ["sports_cockpit_phase7d5a2_chronology_test"],
            "allowedSkips": {VIEW: {"reason": VIEW_REASON, "reasonCode": "REAL_D3_GEN2_VIEW"}}}


def _junit(cases):
    # cases: list of (nodeid, status, reason)
    tcs = []
    for nodeid, status, reason in cases:
        f, name = nodeid.split("::", 1)
        inner = ""
        if status == "skipped":
            inner = f'<skipped message="{reason}"/>'
        elif status == "failed":
            inner = "<failure/>"
        tcs.append(f'<testcase file="{f}" name="{name}">{inner}</testcase>')
    return '<?xml version="1.0"?><testsuites><testsuite name="p">' + "".join(tcs) + "</testsuite></testsuites>"


def _run(tmp, *, collected, junit_cases, policy):
    (tmp / "collected.txt").write_text("\n".join(collected))
    (tmp / "junit.xml").write_text(_junit(junit_cases))
    (tmp / "policy.json").write_text(json.dumps(policy))
    r = subprocess.run([sys.executable, str(GOV), "--collected", str(tmp / "collected.txt"),
                        "--junit", str(tmp / "junit.xml"), "--out", str(tmp / "manifest.json"),
                        "--policy", str(tmp / "policy.json")], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def test_baseline_valid_triple_passes(tmp_path):
    rc, out = _run(tmp_path, collected=BASE_NODES,
                   junit_cases=[(CRIT, "passed", ""), (VIEW, "skipped", VIEW_REASON)], policy=_policy())
    assert rc == 0, out


def test_omitting_a_critical_test_from_collection_fails(tmp_path):
    rc, out = _run(tmp_path, collected=[VIEW],                       # critical node dropped from collection
                   junit_cases=[(VIEW, "skipped", VIEW_REASON)], policy=_policy())
    assert rc != 0 and ("NOT COLLECTED" in out or "MISSING" in out)


def test_skipping_a_critical_test_fails(tmp_path):
    rc, out = _run(tmp_path, collected=BASE_NODES,
                   junit_cases=[(CRIT, "skipped", "whatever"), (VIEW, "skipped", VIEW_REASON)], policy=_policy())
    assert rc != 0 and "CRITICAL NODE SKIPPED" in out


def test_critical_test_not_passing_fails(tmp_path):
    rc, out = _run(tmp_path, collected=BASE_NODES,
                   junit_cases=[(CRIT, "failed", ""), (VIEW, "skipped", VIEW_REASON)], policy=_policy())
    assert rc != 0 and "not passed" in out


def test_unknown_skipped_node_fails(tmp_path):
    extra = "tests/sports_other_test.py::test_x"
    nodes = BASE_NODES + [extra]
    pol = _policy(nodes)
    rc, out = _run(tmp_path, collected=nodes,
                   junit_cases=[(CRIT, "passed", ""), (VIEW, "skipped", VIEW_REASON), (extra, "skipped", "mystery reason")],
                   policy=pol)
    assert rc != 0 and "UNKNOWN SKIP" in out


def test_changed_skip_reason_fails(tmp_path):
    rc, out = _run(tmp_path, collected=BASE_NODES,
                   junit_cases=[(CRIT, "passed", ""), (VIEW, "skipped", "some DIFFERENT reason text")], policy=_policy())
    assert rc != 0 and ("REASON CHANGED" in out or "UNKNOWN SKIP" in out or "CATEGORY CHANGED" in out)


def test_changed_skip_category_fails(tmp_path):
    pol = _policy()
    pol["allowedSkips"][VIEW]["reasonCode"] = "SOME_OTHER_CODE"       # policy code no longer matches the reason
    rc, out = _run(tmp_path, collected=BASE_NODES,
                   junit_cases=[(CRIT, "passed", ""), (VIEW, "skipped", VIEW_REASON)], policy=pol)
    assert rc != 0 and "CATEGORY CHANGED" in out


def test_removed_expected_allowed_skip_node_fails(tmp_path):
    # the policy expects VIEW to be collected; a collection that drops it fails (expected node missing)
    rc, out = _run(tmp_path, collected=[CRIT], junit_cases=[(CRIT, "passed", "")], policy=_policy())
    assert rc != 0 and "MISSING FROM COLLECTION" in out


def test_unexpected_collected_test_fails(tmp_path):
    nodes = BASE_NODES + ["tests/sports_brand_new_test.py::test_y"]
    rc, out = _run(tmp_path, collected=nodes,
                   junit_cases=[(CRIT, "passed", ""), (VIEW, "skipped", VIEW_REASON),
                                ("tests/sports_brand_new_test.py::test_y", "passed", "")], policy=_policy())
    assert rc != 0 and "UNEXPECTED NODE APPEARED" in out


def test_subset_collection_cannot_claim_full_gate(tmp_path):
    # running a SUBSET (fewer collected than the policy's full expected set) fails on the missing expected nodes,
    # so a subset run can never emit a passing full-gate governance result
    rc, out = _run(tmp_path, collected=[CRIT], junit_cases=[(CRIT, "passed", "")], policy=_policy())
    assert rc != 0 and "MISSING FROM COLLECTION" in out
