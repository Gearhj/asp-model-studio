"""Executable Phase 7D.5A.9 protected-set boundary authority."""
from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from tests.codex_phase7d5a7_contract.test_contract import (
    _canonical_sha,
    _file_sha,
    _load,
    _validate_json_schema,
)


REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CONTRACT_PATH = REPO / "tests/codex_phase7d5a7_contract/acceptance_contract.json"
REPORT_PATH = HERE / "acceptance_boundary_report.json"
SCHEMA_PATH = HERE / "acceptance_boundary_report_schema.json"
HISTORICAL_REPORT_PATH = REPO / "tests/codex_phase7d5a7_contract/satisfiability_report.json"
HISTORICAL_SCHEMA_PATH = REPO / "tests/codex_phase7d5a7_contract/satisfiability_report_schema.json"
ORIGINAL_MANIFEST_PATH = REPO / "tests/codex_phase7d5a3_red_gate/acceptance_manifest.json"
DELTA_MANIFEST_PATH = REPO / "tests/codex_phase7d5a5_delta_red_gate/acceptance_manifest.json"

EDITABLE_PATHS = {
    "tests/_isolated_data_guard.py",
    "tests/conftest.py",
    "scripts/phase7d5a_skip_governance.py",
}
TARGET_BY_PATH = {
    "tests/_isolated_data_guard.py": "D7_ISOLATED_DATA_GUARD",
    "tests/conftest.py": "D7_PYTEST_CAPABILITY_INSTALLER",
    "scripts/phase7d5a_skip_governance.py": "D8_COLLECTION_JUNIT_ANALYZER",
}
FINDING_TARGETS = {
    "R7_DATA_HERMETIC_GATE": {
        "D7_ISOLATED_DATA_GUARD", "D7_PYTEST_CAPABILITY_INSTALLER",
    },
    "D7_SESSION_BOUND_TEMP_AUTHORITY": {
        "D7_ISOLATED_DATA_GUARD", "D7_PYTEST_CAPABILITY_INSTALLER",
    },
    "R8_COLLECTION_AND_SKIP_GOVERNANCE": {"D8_COLLECTION_JUNIT_ANALYZER"},
    "D8_INJECTIVE_COLLECTION_RESULT_PARITY": {"D8_COLLECTION_JUNIT_ANALYZER"},
}


def _manifests() -> dict[str, dict[str, Any]]:
    return {
        "original": _load(ORIGINAL_MANIFEST_PATH),
        "delta": _load(DELTA_MANIFEST_PATH),
    }


def _immutable_paths(contract: dict[str, Any]) -> set[str]:
    return (
        {item["path"] for item in contract["immutableAcceptanceInputs"]}
        | {item["path"] for item in contract["protectedTestDigests"]}
        | {item["path"] for item in contract["protectedRunnerDigests"]}
    )


def _scientific_conflicts(records: list[dict[str, Any]]) -> list[set[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = json.dumps(
            {
                "scientificStage": record["scientificStage"],
                "operation": record["operation"],
                "authoritativePreconditions": record["authoritativePreconditions"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        grouped[key].append(record)
    return [
        {item["requirementId"] for item in group}
        for group in grouped.values()
        if len({item["expectedResult"] for item in group}) > 1
    ]


def _mutability_conflicts(contract: dict[str, Any]) -> set[str]:
    editable = {item["path"] for item in contract["editableImplementationTargets"]}
    return editable & _immutable_paths(contract)


def test_v2_report_schema_hashes_and_exact_counts() -> None:
    contract = _load(CONTRACT_PATH)
    report = _load(REPORT_PATH)
    schema = _load(SCHEMA_PATH)
    _validate_json_schema(report, schema, schema)

    assert contract["schemaVersion"] == "CODEX_PHASE7D5A9_ACCEPTANCE_CONTRACT_V2"
    assert contract["contractVersion"] == 2
    assert report["contractSha256"] == _canonical_sha(contract)
    assert contract["boundarySatisfiabilitySchema"] == {
        "relativePath": "tests/codex_phase7d5a9_contract/acceptance_boundary_report_schema.json",
        "fileSha256": _file_sha(SCHEMA_PATH),
        "schemaVersion": "CODEX_PHASE7D5A9_ACCEPTANCE_BOUNDARY_REPORT_V2",
    }
    assert report["historicalScientificReportSha256"] == _file_sha(HISTORICAL_REPORT_PATH)
    assert report["coverage"] == {
        "protectedFindingCount": 9,
        "protectedNodeCount": 86,
        "requirementCount": 86,
        "editableTargetCount": 3,
        "immutableInputCount": 11,
        "protectedTestDigestCount": 9,
        "protectedRunnerCount": 3,
        "nodeCoverageExact": True,
        "targetCoverageExact": True,
        "classificationDisjoint": True,
    }
    assert len({item["requirementId"] for item in report["requirements"]}) == 86
    assert len({item["immutableTestOwner"] for item in report["requirements"]}) == 86
    assert len({item["path"] for item in report["fileClassifications"]}) == len(
        report["fileClassifications"]
    )


def test_exact_three_editable_targets_are_disjoint_from_all_immutable_bytes() -> None:
    contract = _load(CONTRACT_PATH)
    targets = {item["path"]: item for item in contract["editableImplementationTargets"]}
    assert set(targets) == EDITABLE_PATHS
    assert {path: item["targetId"] for path, item in targets.items()} == TARGET_BY_PATH
    assert _mutability_conflicts(contract) == set()

    transitive = {item["path"] for item in contract["protectedAuthorities"]["transitiveInputs"]}
    assert not (EDITABLE_PATHS & transitive)
    assert "scripts/run_phase7d5a_isolated_gate.ps1" not in EDITABLE_PATHS
    assert {item["path"] for item in contract["protectedRunnerDigests"]} == {
        "scripts/run_phase7d5a3_codex_red_gate.ps1",
        "scripts/run_phase7d5a5_codex_delta_red_gate.ps1",
        "scripts/run_phase7d5a_isolated_gate.ps1",
    }
    for item in targets.values():
        assert item["byteIdentityEnforced"] is False
        assert len(item["previouslyProtectedSha256"]) == 64
        assert item["allowedChangeScope"]
        assert "NO_TEST_SPECIFIC_BRANCHING" in item["prohibitions"]
        assert item["immutableGoverningNodeIds"]


def test_all_immutable_input_test_and_runner_digests_match_exact_bytes() -> None:
    contract = _load(CONTRACT_PATH)
    manifests = _manifests()
    for item in contract["immutableAcceptanceInputs"]:
        assert _file_sha(REPO / item["path"]) == item["sha256"]
    for item in contract["protectedRunnerDigests"]:
        assert _file_sha(REPO / item["path"]) == item["sha256"]
    for item in contract["protectedTestDigests"]:
        manifest = manifests[item["owner"]]
        finding = next(
            value for value in manifest["findings"] if value["findingId"] == item["findingId"]
        )
        assert _file_sha(REPO / item["path"]) == item["fileSha256"]
        assert _canonical_sha(finding) == item["findingSha256"]
        assert _canonical_sha(finding["pytestNodeIds"]) == item["nodeListSha256"]
        assert len(finding["pytestNodeIds"]) == item["expectedNodeCount"]


def test_every_protected_node_has_one_exact_requirement_and_target_binding() -> None:
    contract = _load(CONTRACT_PATH)
    report = _load(REPORT_PATH)
    manifests = _manifests()
    expected: dict[str, str] = {}
    for protected in contract["protectedTestDigests"]:
        finding = next(
            item
            for item in manifests[protected["owner"]]["findings"]
            if item["findingId"] == protected["findingId"]
        )
        for node in finding["pytestNodeIds"]:
            assert node not in expected
            expected[node] = protected["findingId"]

    records = {item["immutableTestOwner"]: item for item in report["requirements"]}
    assert set(records) == set(expected)
    for node, finding_id in expected.items():
        record = records[node]
        assert record["findingId"] == finding_id
        assert record["implementationTarget"]
        assert record["mutabilityClassification"] == "IMMUTABLE_ACCEPTANCE_REQUIREMENT"
        assert set(record["implementationTargetIds"]) == FINDING_TARGETS.get(finding_id, set())

    nodes_by_finding: dict[str, set[str]] = defaultdict(set)
    for node, finding_id in expected.items():
        nodes_by_finding[finding_id].add(node)
    for target in contract["editableImplementationTargets"]:
        governed = set().union(*(nodes_by_finding[item] for item in target["findingIds"]))
        assert set(target["immutableGoverningNodeIds"]) == governed


def test_scientific_contract_and_historical_d1_d2_report_are_unchanged() -> None:
    contract = _load(CONTRACT_PATH)
    scientific = contract["immutableScientificRequirements"]
    for field, key in (
        ("stageDefinitionsSha256", "stageDefinitions"),
        ("stateTransitionMatrixSha256", "stateTransitionMatrix"),
        ("normalizationPolicySha256", "normalizationPolicy"),
        ("nodeOwnershipSha256", "nodeOwnership"),
        ("reconciledNodeIdsSha256", "reconciledNodeIds"),
        ("postconditionCatalogSha256", "postconditionCatalog"),
    ):
        assert scientific[field] == _canonical_sha(contract[key])

    historical = contract["historicalScientificReport"]
    assert historical["reportFileSha256"] == _file_sha(HISTORICAL_REPORT_PATH)
    assert historical["schemaFileSha256"] == _file_sha(HISTORICAL_SCHEMA_PATH)
    old_report = _load(HISTORICAL_REPORT_PATH)
    assert old_report["contractSha256"] == historical["boundContractCanonicalSha256"]
    assert len(old_report["after"]["requirements"]) == 101
    assert old_report["after"]["conflictGroups"] == []
    assert old_report["summary"]["afterConflictCount"] == 0
    assert contract["baseAuthorities"]["currentProductionBaseline"]["originalPackage"]["passed"] == 83
    assert contract["baseAuthorities"]["currentProductionBaseline"]["deltaPackage"]["passed"] == 16
    assert contract["builderConstraints"]["requiredCurrentRedFindings"] == ["D3", "D7", "D8"]


def test_scientific_and_mutability_contradiction_algorithms_fail_closed() -> None:
    contract = _load(CONTRACT_PATH)
    report = _load(REPORT_PATH)
    assert _scientific_conflicts(report["requirements"]) == []
    assert _mutability_conflicts(contract) == set()
    assert report["scientificConflictGroups"] == []
    assert report["mutabilityConflictGroups"] == []

    opposite = deepcopy(report["requirements"][0])
    opposite["requirementId"] = "PHASE7D5A9-SYNTHETIC-99"
    opposite["expectedResult"] = "OPPOSITE_FOR_SYNTHETIC_TEST"
    assert _scientific_conflicts([report["requirements"][0], opposite]) == [
        {report["requirements"][0]["requirementId"], opposite["requirementId"]}
    ]

    conflicted = deepcopy(contract)
    conflicted["immutableAcceptanceInputs"].append(
        {"role": "SYNTHETIC_CONTRADICTION", "path": "tests/_isolated_data_guard.py", "sha256": "0" * 64}
    )
    assert _mutability_conflicts(conflicted) == {"tests/_isolated_data_guard.py"}


def test_file_classification_report_exactly_projects_contract_boundary() -> None:
    contract = _load(CONTRACT_PATH)
    report = _load(REPORT_PATH)
    by_path = {item["path"]: item for item in report["fileClassifications"]}
    immutable = _immutable_paths(contract)
    assert immutable.isdisjoint(EDITABLE_PATHS)
    assert set(by_path) == immutable | EDITABLE_PATHS
    for path in immutable:
        assert by_path[path]["classification"].startswith("IMMUTABLE_")
        assert by_path[path]["byteIdentityEnforced"] is True
        assert by_path[path]["targetId"] is None
    for path in EDITABLE_PATHS:
        assert by_path[path]["classification"] == "EDITABLE_IMPLEMENTATION_TARGET"
        assert by_path[path]["byteIdentityEnforced"] is False
        assert by_path[path]["targetId"] == TARGET_BY_PATH[path]
    assert {
        key: set(value) for key, value in contract["findingToImplementationTargetMap"].items()
    } == FINDING_TARGETS
