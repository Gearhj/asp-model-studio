"""D8 delta-red gate: collection/JUnit parity keys must be injective."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts import phase7d5a_skip_governance as GOV


_PREFIX = "D8_INJECTIVE_COLLECTION_RESULT_PARITY:"
_REPO = Path(__file__).resolve().parents[2]
_ANALYZER = _REPO / "scripts" / "phase7d5a_skip_governance.py"
_SELECTION = "phase7d5a5-delta-collision"
_COLLISION_A = "tests/delta.parity_test.py::test_collision"
_COLLISION_B = "tests/delta/parity_test.py::test_collision"


def _write_junit(path: Path, nodeids: list[str]) -> None:
    suite = ET.Element("testsuite", tests=str(len(nodeids)))
    for nodeid in nodeids:
        file_name, name = nodeid.split("::", 1)
        ET.SubElement(
            suite,
            "testcase",
            file=file_name,
            classname=file_name.removesuffix(".py").replace("/", "."),
            name=name,
        )
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _run_analyzer(root: Path, *, collected: list[str], junit: list[str]) -> subprocess.CompletedProcess[str]:
    root.mkdir(parents=True, exist_ok=True)
    collected_path = root / "collected.txt"
    junit_path = root / "junit.xml"
    policy_path = root / "policy.json"
    output_path = root / "result.json"
    collected_path.write_text("\n".join(collected) + "\n", encoding="utf-8")
    _write_junit(junit_path, junit)
    policy = {
        "schemaVersion": GOV.POLICY_SCHEMA,
        "policyVersion": GOV.EXPECTED_POLICY_VERSION,
        "selection": _SELECTION,
        "collectionDigest": GOV.collection_digest(collected),
        "expectedCollected": sorted(collected),
        "criticalPatterns": ["test_collision"],
        "allowedSkips": {},
    }
    policy_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(_ANALYZER),
            "--collected",
            str(collected_path),
            "--junit",
            str(junit_path),
            "--out",
            str(output_path),
            "--policy",
            str(policy_path),
            "--selection",
            _SELECTION,
        ],
        cwd=_REPO,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _assert_collision_rejected(result: subprocess.CompletedProcess[str], scenario: str) -> None:
    assert result.returncode != 0, (
        f"{_PREFIX} analyzer false-passed {scenario}; a dictionary overwrite hid a distinct node\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    diagnostic = (result.stdout + result.stderr).lower()
    assert "collision" in diagnostic or "one-to-one" in diagnostic or "inject" in diagnostic, (
        f"{_PREFIX} analyzer failed for an unrelated reason in {scenario}: {diagnostic}"
    )


def test_distinct_collection_ids_cannot_share_one_canonical_key(tmp_path: Path) -> None:
    result = _run_analyzer(
        tmp_path / "distinct-collected",
        collected=[_COLLISION_A, _COLLISION_B],
        junit=[_COLLISION_B],
    )
    _assert_collision_rejected(result, "two distinct collected IDs sharing one canonical key")


def test_canonical_key_collision_is_fatal(tmp_path: Path) -> None:
    result = _run_analyzer(
        tmp_path / "canonical-fatal",
        collected=[_COLLISION_A, _COLLISION_B],
        junit=[_COLLISION_A, _COLLISION_B],
    )
    _assert_collision_rejected(result, "canonical-key collision on both sides")


def test_junit_missing_one_of_two_colliding_nodes_is_fatal(tmp_path: Path) -> None:
    result = _run_analyzer(
        tmp_path / "junit-missing",
        collected=[_COLLISION_A, _COLLISION_B],
        junit=[_COLLISION_A],
    )
    _assert_collision_rejected(result, "JUnit missing one of two colliding collected nodes")


def test_collection_to_junit_mapping_is_one_to_one(tmp_path: Path) -> None:
    result = _run_analyzer(
        tmp_path / "collection-to-junit",
        collected=[_COLLISION_A, _COLLISION_B],
        junit=[_COLLISION_B],
    )
    _assert_collision_rejected(result, "two collection nodes mapping to one JUnit result")


def test_junit_to_collection_mapping_is_one_to_one(tmp_path: Path) -> None:
    result = _run_analyzer(
        tmp_path / "junit-to-collection",
        collected=[_COLLISION_A],
        junit=[_COLLISION_A, _COLLISION_B],
    )
    _assert_collision_rejected(result, "two JUnit results mapping to one collected node")


def test_duplicate_canonical_result_key_is_fatal(tmp_path: Path) -> None:
    result = _run_analyzer(
        tmp_path / "duplicate-result-key",
        collected=[_COLLISION_A, _COLLISION_B],
        junit=[_COLLISION_A, _COLLISION_B],
    )
    _assert_collision_rejected(result, "duplicate canonical JUnit result key")
