"""Repair 8 red gate: mutate inputs to the actual committed skip analyzer."""
from __future__ import annotations

import copy

from ._helpers import collection_digest, run_governance


CRIT_ONE = "tests/sports_cockpit_phase7d5a2_chronology_test.py::test_one"
CRIT_TWO = "tests/sports_cockpit_phase7d5a2_chronology_test.py::test_two"
VIEW = "tests/sports_cockpit_data_preview_test.py::test_view"
EXTRA = "tests/sports_cockpit_data_preview_test.py::test_junit_only_extra"
VIEW_REASON = "D3 feature view not materialized"
SELECTION = "tests/sports_*_test.py"


def _policy(nodes=None):
    nodes = list(nodes or [CRIT_ONE, VIEW])
    return {
        "schemaVersion": "PHASE_7D5A2_GATE_POLICY_V1",
        "policyVersion": 1,
        "selection": SELECTION,
        "collectionDigest": collection_digest(nodes),
        "expectedCollected": sorted(nodes),
        "criticalPatterns": ["sports_cockpit_phase7d5a2_chronology_test"],
        "allowedSkips": {
            VIEW: {
                "reason": VIEW_REASON,
                "reasonCode": "REAL_D3_GEN2_VIEW",
                "category": "REAL_D3_GEN2_VIEW",
            }
        },
    }


def _assert_rejected(result):
    assert result.returncode != 0, "analyzer false-pass:\n" + result.stdout + result.stderr


def test_policy_rejects_allowed_skip_that_unexpectedly_passes(tmp_path):
    result = run_governance(
        tmp_path,
        collected=[CRIT_ONE, VIEW],
        junit_cases=[(CRIT_ONE, "passed", ""), (VIEW, "passed", "")],
        policy=_policy(),
        selection=SELECTION,
    )
    _assert_rejected(result)


def test_policy_rejects_wrong_schema_version_or_selection(tmp_path):
    mutations = [
        ("schemaVersion", "PHASE_7D5A2_GATE_POLICY_BOGUS"),
        ("policyVersion", 999),
        ("selection", "tests/one_file_only.py"),
    ]
    false_passes: list[str] = []
    for index, (field, value) in enumerate(mutations):
        policy = _policy()
        policy[field] = value
        result = run_governance(
            tmp_path / str(index),
            collected=[CRIT_ONE, VIEW],
            junit_cases=[(CRIT_ONE, "passed", ""), (VIEW, "skipped", VIEW_REASON)],
            policy=policy,
            selection=SELECTION,
        )
        if result.returncode == 0:
            false_passes.append(field)
    assert not false_passes, f"analyzer accepted invalid policy metadata: {false_passes}"


def test_policy_rejects_collected_node_missing_from_junit(tmp_path):
    nodes = [CRIT_ONE, CRIT_TWO, VIEW]
    result = run_governance(
        tmp_path,
        collected=nodes,
        junit_cases=[(CRIT_ONE, "passed", ""), (VIEW, "skipped", VIEW_REASON)],
        policy=_policy(nodes),
        selection=SELECTION,
    )
    _assert_rejected(result)


def test_policy_rejects_erased_critical_authority(tmp_path):
    policy = _policy()
    policy["criticalPatterns"] = []
    result = run_governance(
        tmp_path,
        collected=[CRIT_ONE, VIEW],
        junit_cases=[(CRIT_ONE, "passed", ""), (VIEW, "skipped", VIEW_REASON)],
        policy=policy,
        selection=SELECTION,
    )
    _assert_rejected(result)


def test_policy_requires_exact_collection_junit_parity(tmp_path):
    result = run_governance(
        tmp_path,
        collected=[CRIT_ONE, VIEW],
        junit_cases=[
            (CRIT_ONE, "passed", ""),
            (VIEW, "skipped", VIEW_REASON),
            (EXTRA, "passed", ""),
        ],
        policy=_policy(),
        selection=SELECTION,
    )
    _assert_rejected(result)


def test_policy_requires_exact_allowed_actual_skip_equality(tmp_path):
    result = run_governance(
        tmp_path,
        collected=[CRIT_ONE, VIEW],
        junit_cases=[(CRIT_ONE, "passed", ""), (VIEW, "passed", "")],
        policy=_policy(),
        selection=SELECTION,
    )
    _assert_rejected(result)


def test_policy_rejects_changed_skip_reason(tmp_path):
    result = run_governance(
        tmp_path,
        collected=[CRIT_ONE, VIEW],
        junit_cases=[(CRIT_ONE, "passed", ""), (VIEW, "skipped", "feature view / play_transition")],
        policy=_policy(),
        selection=SELECTION,
    )
    _assert_rejected(result)


def test_policy_rejects_changed_skip_category(tmp_path):
    policy = copy.deepcopy(_policy())
    policy["allowedSkips"][VIEW]["category"] = "WRONG_CATEGORY"
    result = run_governance(
        tmp_path,
        collected=[CRIT_ONE, VIEW],
        junit_cases=[(CRIT_ONE, "passed", ""), (VIEW, "skipped", VIEW_REASON)],
        policy=policy,
        selection=SELECTION,
    )
    _assert_rejected(result)
