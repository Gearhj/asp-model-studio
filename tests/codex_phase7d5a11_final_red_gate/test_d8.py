"""D8 final-red gate: result parity must preserve identity and multiplicity."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


_PREFIX = "D8_DUPLICATE_AND_ALIAS_SAFE_RESULT_PARITY:"
_HARNESS = "PHASE7D5A11_D8_HARNESS_ERROR:"
_REPO = Path(__file__).resolve().parents[2]
_ANALYZER = _REPO / "scripts" / "phase7d5a_skip_governance.py"
_POLICY_SCHEMA = "PHASE_7D5A2_GATE_POLICY_V1"
_POLICY_VERSION = 1
_SELECTION = "phase7d5a11-final-d8-parity"


def _node_signature(name: str) -> str:
    return f"{_PREFIX}{name}:"


def _collection_digest(nodes: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(nodes)).encode("utf-8")).hexdigest()


def _assert_external_audit_root(root: Path) -> Path:
    resolved = root.resolve()
    try:
        resolved.relative_to(_REPO)
    except ValueError:
        return resolved
    raise AssertionError(f"{_HARNESS} synthetic analyzer evidence root is inside the repository: {resolved}")


def _junit_case(
    nodeid: str,
    *,
    classname: str | None = None,
) -> dict[str, str]:
    file_name, name = nodeid.split("::", 1)
    return {
        "file": file_name,
        "classname": classname or file_name.removesuffix(".py").replace("/", "."),
        "name": name,
    }


def _write_junit(path: Path, cases: list[dict[str, str]]) -> None:
    suite = ET.Element("testsuite", tests=str(len(cases)))
    for case in cases:
        ET.SubElement(suite, "testcase", **case)
    ET.ElementTree(suite).write(path, encoding="utf-8", xml_declaration=True)


def _run_analyzer(
    root: Path,
    *,
    collected_lines: list[str],
    junit_cases: list[dict[str, str]],
    critical_pattern: str,
) -> tuple[subprocess.CompletedProcess[str], dict]:
    root = _assert_external_audit_root(root)
    root.mkdir(parents=True, exist_ok=True)
    collected_path = root / "collected.txt"
    junit_path = root / "junit.xml"
    policy_path = root / "policy.json"
    output_path = root / "result.json"

    # Preserve exact line multiplicity. The policy describes the unique collected
    # inventory because multiplicity is independently required to be fail-closed.
    collected_path.write_text("\n".join(collected_lines) + "\n", encoding="utf-8")
    _write_junit(junit_path, junit_cases)
    expected_collected = sorted(set(collected_lines))
    policy = {
        "schemaVersion": _POLICY_SCHEMA,
        "policyVersion": _POLICY_VERSION,
        "selection": _SELECTION,
        "collectionDigest": _collection_digest(expected_collected),
        "expectedCollected": expected_collected,
        "criticalPatterns": [critical_pattern],
        "allowedSkips": {},
    }
    policy_path.write_text(json.dumps(policy, indent=2), encoding="utf-8")

    result = subprocess.run(
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
    manifest = json.loads(output_path.read_text(encoding="utf-8")) if output_path.is_file() else {}
    return result, manifest


def _assert_identity_rejected(
    result: subprocess.CompletedProcess[str],
    manifest: dict,
    scenario: str,
    node_signature: str,
    diagnostic_tokens: tuple[str, ...],
) -> None:
    assert result.returncode != 0, (
        f"{node_signature} analyzer false-passed {scenario}; identity or multiplicity was erased before parity\n"
        f"manifest={manifest}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    diagnostic = (result.stdout + result.stderr + json.dumps(manifest)).lower()
    assert any(token in diagnostic for token in diagnostic_tokens), (
        f"{_HARNESS} analyzer rejected {scenario} for an unrelated reason: {diagnostic}"
    )


def test_exact_duplicate_junit_testcases_are_fatal(tmp_path: Path) -> None:
    node = "tests/final_identity_test.py::test_exact_duplicate[param-a]"
    case = _junit_case(node)
    result, manifest = _run_analyzer(
        tmp_path / "duplicate-junit",
        collected_lines=[node],
        junit_cases=[case, dict(case)],
        critical_pattern="test_exact_duplicate",
    )
    _assert_identity_rejected(
        result,
        manifest,
        "two byte-identical JUnit testcase identities",
        _node_signature("test_exact_duplicate_junit_testcases_are_fatal"),
        ("duplicate", "cardinality", "multiplicity", "identity"),
    )


def test_parameter_slash_and_dot_alias_is_not_treated_as_same_identity(tmp_path: Path) -> None:
    collected = "tests/delta.parity_test.py::test_collision[param/a]"
    junit = "tests/delta/parity_test.py::test_collision[param.a]"
    result, manifest = _run_analyzer(
        tmp_path / "slash-dot-alias",
        collected_lines=[collected],
        junit_cases=[_junit_case(junit)],
        critical_pattern="test_collision",
    )
    _assert_identity_rejected(
        result,
        manifest,
        "a slash/dot file and parameter alias across parity sides",
        _node_signature("test_parameter_slash_and_dot_alias_is_not_treated_as_same_identity"),
        ("parity", "mismatch", "missing", "unexpected", "alias", "identity", "collision"),
    )


def test_file_and_class_identity_cannot_be_erased_by_canonicalization(tmp_path: Path) -> None:
    collected = "tests/identity.probe_test.py::test_file_class_alias[param-a]"
    junit = "tests/identity/probe_test.py::test_file_class_alias[param-a]"
    result, manifest = _run_analyzer(
        tmp_path / "file-class-erasure",
        collected_lines=[collected],
        junit_cases=[
            _junit_case(
                junit,
                classname="tests.identity.probe_test.TestDifferentClass",
            )
        ],
        critical_pattern="test_file_class_alias",
    )
    _assert_identity_rejected(
        result,
        manifest,
        "different file and class identities erased by namespace canonicalization",
        _node_signature("test_file_and_class_identity_cannot_be_erased_by_canonicalization"),
        ("parity", "mismatch", "missing", "unexpected", "alias", "identity", "collision"),
    )


def test_duplicate_collected_node_identity_is_fatal(tmp_path: Path) -> None:
    node = "tests/final_identity_test.py::test_duplicate_collection[param-a]"
    result, manifest = _run_analyzer(
        tmp_path / "duplicate-collection",
        collected_lines=[node, node],
        junit_cases=[_junit_case(node)],
        critical_pattern="test_duplicate_collection",
    )
    _assert_identity_rejected(
        result,
        manifest,
        "two identical collected node identities",
        _node_signature("test_duplicate_collected_node_identity_is_fatal"),
        ("duplicate", "digest", "cardinality", "multiplicity", "identity"),
    )


def test_parity_rejects_nonunit_cardinality_before_set_comparison(tmp_path: Path) -> None:
    node = "tests/final_identity_test.py::test_nonunit_cardinality[param-a]"
    case = _junit_case(node)
    result, manifest = _run_analyzer(
        tmp_path / "nonunit-cardinality",
        collected_lines=[node, node],
        junit_cases=[case, dict(case)],
        critical_pattern="test_nonunit_cardinality",
    )
    _assert_identity_rejected(
        result,
        manifest,
        "equal canonical-key sets whose collection and JUnit cardinalities are both two",
        _node_signature("test_parity_rejects_nonunit_cardinality_before_set_comparison"),
        ("duplicate", "cardinality", "multiplicity", "identity", "one-to-one"),
    )


def test_valid_one_to_one_identity_mapping_still_passes(tmp_path: Path) -> None:
    node = "tests/final_identity_test.py::test_one_to_one[param-a]"
    result, manifest = _run_analyzer(
        tmp_path / "valid-one-to-one",
        collected_lines=[node],
        junit_cases=[_junit_case(node)],
        critical_pattern="test_one_to_one",
    )
    assert result.returncode == 0, (
        f"{_HARNESS} valid one-to-one identity mapping was rejected\n"
        f"manifest={manifest}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert manifest.get("violations") == [], f"{_HARNESS} valid control emitted violations: {manifest}"
    assert "SKIP-GOV PASS" in result.stdout, f"{_HARNESS} valid control did not reach analyzer PASS: {result.stdout}"
