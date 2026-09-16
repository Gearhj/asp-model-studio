"""Executable authority for the Phase 7D.5A.7 acceptance contract.

The package validates auditor artifacts only. It does not implement, wrap,
patch, or simulate the production Silver publisher.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest


REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "acceptance_contract.json"
REPORT_PATH = HERE / "satisfiability_report.json"
REPORT_SCHEMA_PATH = HERE / "satisfiability_report_schema.json"
ISSUER_PATH = HERE / "canonical_synthetic_issuer_registry.json"
ORIGINAL_MANIFEST_PATH = REPO / "tests/codex_phase7d5a3_red_gate/acceptance_manifest.json"
DELTA_MANIFEST_PATH = REPO / "tests/codex_phase7d5a5_delta_red_gate/acceptance_manifest.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _resolve_schema_ref(root: dict[str, Any], ref: str) -> dict[str, Any]:
    assert ref.startswith("#/")
    value: Any = root
    for component in ref[2:].split("/"):
        value = value[component.replace("~1", "/").replace("~0", "~")]
    assert isinstance(value, dict)
    return value


def _json_type_matches(value: Any, expected: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }[expected]


def _validate_json_schema(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> None:
    if "$ref" in schema:
        _validate_json_schema(value, _resolve_schema_ref(root, schema["$ref"]), root, path)
        return
    if "oneOf" in schema:
        matches = 0
        for option in schema["oneOf"]:
            try:
                _validate_json_schema(value, option, root, path)
            except AssertionError:
                continue
            matches += 1
        assert matches == 1, f"{path}: expected exactly one schema branch, got {matches}"
        return
    if "const" in schema:
        assert value == schema["const"], f"{path}: expected constant {schema['const']!r}"
    if "enum" in schema:
        assert value in schema["enum"], f"{path}: value {value!r} not in enum"
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        assert any(_json_type_matches(value, item) for item in types), f"{path}: wrong JSON type"
    if isinstance(value, dict):
        required = set(schema.get("required", []))
        assert required <= set(value), f"{path}: missing keys {sorted(required - set(value))}"
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(properties), f"{path}: extra keys {sorted(set(value) - set(properties))}"
        if "minProperties" in schema:
            assert len(value) >= schema["minProperties"]
        for key, item in value.items():
            if key in properties:
                _validate_json_schema(item, properties[key], root, f"{path}.{key}")
    if isinstance(value, list):
        if "minItems" in schema:
            assert len(value) >= schema["minItems"]
        if "maxItems" in schema:
            assert len(value) <= schema["maxItems"]
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            assert len(encoded) == len(set(encoded)), f"{path}: duplicate array items"
        if "items" in schema:
            for index, item in enumerate(value):
                _validate_json_schema(item, schema["items"], root, f"{path}[{index}]")
    if isinstance(value, str):
        if "minLength" in schema:
            assert len(value) >= schema["minLength"]
        if "pattern" in schema:
            assert re.fullmatch(schema["pattern"], value), f"{path}: pattern mismatch"
    if isinstance(value, int) and not isinstance(value, bool) and "minimum" in schema:
        assert value >= schema["minimum"]


_FORBIDDEN_AUTHORITY_KEYS = {
    "datasetversionid", "displayid", "displayalias", "path", "pathplacement",
    "runtimeroot", "helper", "helpername", "callstack", "pytest", "testfilename",
    "testname", "nodeid",
}


def _authority_key_tokens(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            found.add(re.sub(r"[^a-z0-9]", "", key.lower()))
            found.update(_authority_key_tokens(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_authority_key_tokens(item))
    return found


def _assert_no_forbidden_authority_dimensions(record: dict[str, Any]) -> None:
    authoritative = {
        "scientificStage": record["scientificStage"],
        "normalizedOperation": record["normalizedOperation"],
        "authoritativePreconditions": record["authoritativePreconditions"],
    }
    found = _authority_key_tokens(authoritative)
    assert not (_FORBIDDEN_AUTHORITY_KEYS & found), sorted(_FORBIDDEN_AUTHORITY_KEYS & found)


def _requirement_key(record: dict[str, Any]) -> str:
    _assert_no_forbidden_authority_dimensions(record)
    return _canonical_sha(
        {
            "scientificStage": record["scientificStage"],
            "normalizedOperation": record["normalizedOperation"],
            "authoritativePreconditions": record["authoritativePreconditions"],
        }
    )


def _result_is_compatible(
    group: list[dict[str, Any]], result: str, postcondition_catalog: dict[str, dict[str, str]]
) -> bool:
    if result == "REJECT":
        stage_sets = [set(item["resultContract"]["allowedRejectionStages"]) for item in group]
        if not set.intersection(*stage_sets):
            return False
    dimensions: dict[str, set[str]] = defaultdict(set)
    for item in group:
        tokens = item["resultContract"]["postconditionsByResult"][result]
        local_dimensions: dict[str, set[str]] = defaultdict(set)
        for token in tokens:
            definition = postcondition_catalog[token]
            local_dimensions[definition["dimension"]].add(definition["value"])
        if any(len(values) > 1 for values in local_dimensions.values()):
            return False
        for dimension, values in local_dimensions.items():
            dimensions[dimension].update(values)
    return all(len(values) == 1 for values in dimensions.values())


def _conflicts(
    records: list[dict[str, Any]], postcondition_catalog: dict[str, dict[str, str]]
) -> list[set[str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[_requirement_key(record)].append(record)
    conflicts: list[set[str]] = []
    for group in grouped.values():
        common = set(group[0]["resultContract"]["allowedResults"])
        for item in group[1:]:
            common &= set(item["resultContract"]["allowedResults"])
        if not any(_result_is_compatible(group, result, postcondition_catalog) for result in common):
            conflicts.append({item["requirementId"] for item in group})
    return conflicts


def test_contract_schema_policy_and_stage_boundaries_are_exact() -> None:
    contract = _load(CONTRACT_PATH)
    assert set(contract) == {
        "schemaVersion", "contractVersion", "policyVersion", "contractId",
        "baseAuthorities", "stageDefinitions", "stateTransitionMatrix",
        "normalizationPolicy", "nodeOwnership", "reconciledNodeIds",
        "protectedAuthorities", "issuerFixture", "builderConstraints",
        "satisfiabilitySchema", "postconditionCatalog",
        "immutableAcceptanceInputs", "editableImplementationTargets",
        "immutableScientificRequirements", "findingToImplementationTargetMap",
        "protectedTestDigests", "protectedRunnerDigests",
        "historicalScientificReport", "boundarySatisfiabilitySchema",
    }
    assert contract["schemaVersion"] == "CODEX_PHASE7D5A9_ACCEPTANCE_CONTRACT_V2"
    assert contract["contractVersion"] == 2
    assert set(contract["stageDefinitions"]) == {
        "STAGE_A_PHYSICAL_STAGING", "STAGE_B_GOVERNED_ISSUANCE",
        "STAGE_C_SILVER_PUBLICATION",
    }
    assert contract["stageDefinitions"]["STAGE_A_PHYSICAL_STAGING"]["authorityCreated"] == []
    assert contract["stageDefinitions"]["STAGE_C_SILVER_PUBLICATION"]["modelEligibilityCreated"] is False
    interpretation = contract["baseAuthorities"]["section7Section11Interpretation"]
    assert "explicit narrow exception" in interpretation and "Section 11" in interpretation
    assert contract["builderConstraints"]["productionChangesAllowed"] is False
    assert contract["builderConstraints"]["alternateProductionImplementationAllowed"] is False
    assert contract["builderConstraints"]["d3d6d7d8AcceptanceBehaviorChangesAllowed"] is False
    assert contract["builderConstraints"]["mappedImplementationChangesAllowed"] is True
    assert contract["satisfiabilitySchema"]["fileSha256"] == _file_sha(REPORT_SCHEMA_PATH)
    scientific = contract["immutableScientificRequirements"]
    for key, contract_key in (
        ("stageDefinitionsSha256", "stageDefinitions"),
        ("stateTransitionMatrixSha256", "stateTransitionMatrix"),
        ("normalizationPolicySha256", "normalizationPolicy"),
        ("nodeOwnershipSha256", "nodeOwnership"),
        ("reconciledNodeIdsSha256", "reconciledNodeIds"),
        ("postconditionCatalogSha256", "postconditionCatalog"),
    ):
        assert scientific[key] == _canonical_sha(contract[contract_key])


def test_state_transition_matrix_is_complete_and_monotonic() -> None:
    matrix = _load(CONTRACT_PATH)["stateTransitionMatrix"]
    assert len(matrix) == 6
    assert [row["input"] for row in matrix] == [
        "valid 2023-2024 rows without issuer",
        "valid 2023-2024 rows with valid issuer",
        "2019 rows under 2021-2024 contract",
        "callback relabels actual 2019 as 2024",
        "neutral caller display ID without issuer",
        "renamed valid source with same issuer",
    ]
    assert all(set(row) == {"input", "stageA", "stageB", "stageC"} for row in matrix)
    assert matrix[0]["stageB"] == "REJECT_MISSING_ISSUER" and matrix[0]["stageC"] == "REJECT"
    assert matrix[1]["stageB"] == "ACCEPT_AFTER_CANONICAL_RECONSTRUCTION"
    assert matrix[2]["stageB"] == "REJECT_UNAUTHORIZED_SEASON"
    assert matrix[3]["stageC"] == "REJECT"
    assert matrix[4]["stageB"] == "REJECT_MISSING_ISSUER"
    assert matrix[5]["stageB"] == "ACCEPT_IF_CANONICAL_RELATIONSHIPS_AGREE"


def test_issuer_fixture_is_content_addressed_and_never_lexical_authority() -> None:
    fixture = _load(ISSUER_PATH)
    assert fixture["schemaVersion"] == "CODEX_PHASE7D5A7_CANONICAL_SYNTHETIC_ISSUER_REGISTRY_V2"
    assert fixture["registrySha256"] == _canonical_sha(_without(fixture, "registrySha256"))
    assert "displayAliases" not in fixture

    declaration = fixture["authorityDeclaration"]
    assert declaration["issuerAuthorityRootSha256"] == _canonical_sha(
        _without(declaration, "issuerAuthorityRootSha256")
    )
    for scientific_contract in fixture["contracts"].values():
        assert scientific_contract["sha256"] == _canonical_sha(_without(scientific_contract, "sha256"))

    upstream = {
        item["upstreamRegistrationSha256"]: item
        for item in fixture["canonicalUpstreamRegistrations"]
    }
    assert len(upstream) == 4
    for address, item in upstream.items():
        assert address == _canonical_sha(_without(item, "upstreamRegistrationSha256"))

    records = {item["issuerRecordSha256"]: item for item in fixture["issuerRecords"]}
    assert len(records) == 4
    forbidden_lexical = {
        "datasetVersionId", "displayId", "displayAlias", "displayAliases",
        "alias", "canonicalSourceKey", "path", "runtimeRoot", "helper", "pytest",
    }
    for address, record in records.items():
        assert address == _canonical_sha(_without(record, "issuerRecordSha256"))
        assert record["issuerAuthorityRootSha256"] == declaration["issuerAuthorityRootSha256"]
        assert record["canonicalUpstreamRegistrationSha256"] in upstream
        assert record["temporalContractSha256"] == fixture["contracts"]["temporal"]["sha256"]
        assert forbidden_lexical.isdisjoint(record)

    policy = fixture["lookupPolicy"]
    assert policy["requiredStartingRelationship"] == "PERSISTED_ISSUER_RECORD_SHA256"
    assert policy["displayTextMayGrantOrRevokeAuthority"] is False
    assert policy["traceMetadataLookupPermitted"] is False
    assert {"datasetVersionId", "displayId", "displayAlias", "path", "runtimeRoot"} <= set(
        policy["forbiddenLookupFields"]
    )
    assert not ({"datasetVersionId", "displayId", "displayAlias"} & set(policy["permittedLookupFields"]))

    traces = fixture["nonAuthoritativeTraceMetadata"]
    assert all(item["lookupPermitted"] is False for item in traces)
    base_trace = next(item for item in traces if item["canonicalSourceKey"] == "original-base-v1")
    assert len(base_trace["displayAliases"]) >= 2
    assert len(set(base_trace["displayAliases"])) == len(base_trace["displayAliases"])
    assert base_trace["issuerRecordSha256"] in records
    assert records[base_trace["issuerRecordSha256"]]["sourceLogicalSha256"] == base_trace["sourceLogicalSha256"]

    control = fixture["unauthorizedIssuanceControls"]
    assert len(control) == 1
    control = control[0]
    assert control["lookupPermitted"] is False
    assert control["expectedStageB"] == "REJECT_UNAUTHORIZED_SEASON"
    assert control["rowCount"] == 2 and control["seasons"] == [2019]
    assert control["issuerRecordSha256"] in records
    record = records[control["issuerRecordSha256"]]
    assert record["sourceLogicalSha256"] == control["sourceLogicalSha256"]
    assert record["sourcePhysicalSha256"] == control["sourcePhysicalSha256"]
    assert record["sourceSchemaSha256"] == control["sourceSchemaSha256"]
    assert control["issuerAuthorityRootSha256"] == declaration["issuerAuthorityRootSha256"]
    assert control["temporalContractSha256"] == fixture["contracts"]["temporal"]["sha256"]

    contract = _load(CONTRACT_PATH)
    assert contract["issuerFixture"]["registrySha256"] == fixture["registrySha256"]
    assert contract["issuerFixture"]["traceMetadataAuthorityBearing"] is False


def test_node_ownership_exactly_covers_original_and_delta_d1_d2() -> None:
    contract = _load(CONTRACT_PATH)
    original = _load(ORIGINAL_MANIFEST_PATH)
    delta = _load(DELTA_MANIFEST_PATH)
    original_expected = {
        finding["findingId"]: finding["pytestNodeIds"]
        for finding in original["findings"]
        if finding["findingId"] in {"R1_SEASON_AND_COLUMN_AUTHORITY", "R2_SOURCE_AND_TRANSFORM_AUTHORITY"}
    }
    delta_expected = {
        finding["findingId"]: finding["pytestNodeIds"]
        for finding in delta["findings"]
        if finding["findingId"] in {"D1_PATH_INDEPENDENT_SEASON_AUTHORITY", "D2_CRYPTOGRAPHIC_ISSUER_AUTHORITY"}
    }
    ownership = contract["nodeOwnership"]
    assert ownership["originalR1"] == original_expected["R1_SEASON_AND_COLUMN_AUTHORITY"]
    assert ownership["originalR2"] == original_expected["R2_SOURCE_AND_TRANSFORM_AUTHORITY"]
    assert ownership["deltaD1"] == delta_expected["D1_PATH_INDEPENDENT_SEASON_AUTHORITY"]
    assert ownership["deltaD2"] == delta_expected["D2_CRYPTOGRAPHIC_ISSUER_AUTHORITY"]
    all_nodes = [node for values in ownership.values() for node in values]
    assert len(all_nodes) == len(set(all_nodes)) == 30


def test_satisfiability_report_schema_is_strict_and_atomic_coverage_is_exact() -> None:
    contract = _load(CONTRACT_PATH)
    report = _load(REPORT_PATH)
    schema = _load(REPORT_SCHEMA_PATH)
    _validate_json_schema(report, schema, schema)
    historical = contract["historicalScientificReport"]
    assert report["contractSha256"] == historical["boundContractCanonicalSha256"]
    assert _file_sha(REPORT_PATH) == historical["reportFileSha256"]
    assert _file_sha(REPORT_SCHEMA_PATH) == historical["schemaFileSha256"]
    assert report["normalizationPolicySha256"] == _canonical_sha(contract["normalizationPolicy"])
    assert report["requirementSchemaSha256"] == _file_sha(REPORT_SCHEMA_PATH)

    records = report["after"]["requirements"]
    assert len(records) == report["coverage"]["requirementCountAfter"] == 101
    assert len({record["requirementId"] for record in records}) == len(records)
    by_id = {record["requirementId"]: record for record in records}
    for requirement_id in {
        "AFTER-DELTA-D1-01-C",
        "AFTER-DELTA-D1-02-C",
        "AFTER-DELTA-D1-03-C",
        "AFTER-DELTA-D1-05-C",
    }:
        record = by_id[requirement_id]
        assert record["invocationCondition"] == "ONLY_ON_FORBIDDEN_PRIOR_ACCEPTANCE"
        assert record["resultContract"] == {
            "allowedResults": ["NOT_REACHED"],
            "allowedRejectionStages": [],
            "postconditionsByResult": {
                "NOT_REACHED": [
                    "PUBLICATION_NOT_REACHED",
                    "SILVER_OBJECT_ABSENT",
                    "SILVER_REGISTRY_ENTRY_ABSENT",
                ]
            },
        }
    assert "AFTER-DELTA-D1-04-V" not in by_id
    assert "AFTER-DELTA-D1-04-CTRL-V" in by_id
    expected_nodes = {node for values in contract["nodeOwnership"].values() for node in values}
    assert {record["nodeId"] for record in records} == expected_nodes

    operation_stage = {
        "PUBLISH_SOURCE_OBJECT": "STAGE_A_PHYSICAL_STAGING",
        "RESOLVE_VERIFIED_SOURCE": "STAGE_B_GOVERNED_ISSUANCE",
        "PUBLISH_SILVER": "STAGE_C_SILVER_PUBLICATION",
        "VERIFY_SILVER": "STAGE_C_SILVER_PUBLICATION",
        "COMPUTE_PRIOR_PA": "STAGE_C_SILVER_PUBLICATION",
    }
    callable_by_operation = {
        "PUBLISH_SOURCE_OBJECT": "server.sports_modeling.silver_publish.publish_source_object",
        "RESOLVE_VERIFIED_SOURCE": "server.sports_modeling.silver_publish.resolve_verified_source",
        "PUBLISH_SILVER": "server.sports_modeling.silver_publish.publish_silver",
        "VERIFY_SILVER": "server.sports_modeling.silver_publish.verify_silver",
        "COMPUTE_PRIOR_PA": "server.sports_modeling.silver_transform.compute_prior_pa",
    }
    catalog = contract["postconditionCatalog"]
    schema_tokens = set(schema["$defs"]["postcondition"]["enum"])
    assert set(catalog) == schema_tokens
    allowed_result_shapes = {
        ("ACCEPT",), ("REJECT",), ("NOT_REACHED",), ("ACCEPT", "REJECT"),
    }
    for record in report["before"]["requirements"] + records:
        operation = record["normalizedOperation"]
        assert record["scientificStage"] == operation_stage[operation["operationKind"]]
        assert operation["productionCallable"] == callable_by_operation[operation["operationKind"]]
        result_contract = record["resultContract"]
        assert tuple(result_contract["allowedResults"]) in allowed_result_shapes
        assert set(result_contract["postconditionsByResult"]) == set(result_contract["allowedResults"])
        if "REJECT" in result_contract["allowedResults"]:
            assert result_contract["allowedRejectionStages"]
        else:
            assert result_contract["allowedRejectionStages"] == []
        _assert_no_forbidden_authority_dimensions(record)

    actual = defaultdict(set)
    for record in records:
        actual[record["nodeId"]].add(
            (record["scientificStage"], record["normalizedOperation"]["operationKind"])
        )
    ownership = contract["nodeOwnership"]
    expected: dict[str, set[tuple[str, str]]] = {}
    expected[ownership["originalR1"][0]] = {( "STAGE_A_PHYSICAL_STAGING", "PUBLISH_SOURCE_OBJECT"), ("STAGE_B_GOVERNED_ISSUANCE", "RESOLVE_VERIFIED_SOURCE"), ("STAGE_C_SILVER_PUBLICATION", "PUBLISH_SILVER")}
    expected[ownership["originalR1"][1]] = expected[ownership["originalR1"][0]] | {("STAGE_C_SILVER_PUBLICATION", "VERIFY_SILVER")}
    expected[ownership["originalR1"][2]] = set(expected[ownership["originalR1"][0]]) | {("STAGE_C_SILVER_PUBLICATION", "VERIFY_SILVER")}
    expected[ownership["originalR1"][3]] = {("STAGE_C_SILVER_PUBLICATION", "COMPUTE_PRIOR_PA")}
    expected[ownership["originalR1"][4]] = expected[ownership["originalR1"][1]]
    for node in ownership["originalR2"][:7]:
        expected[node] = {("STAGE_A_PHYSICAL_STAGING", "PUBLISH_SOURCE_OBJECT"), ("STAGE_B_GOVERNED_ISSUANCE", "RESOLVE_VERIFIED_SOURCE")}
    for node in ownership["originalR2"][7:10]:
        expected[node] = {("STAGE_A_PHYSICAL_STAGING", "PUBLISH_SOURCE_OBJECT"), ("STAGE_B_GOVERNED_ISSUANCE", "RESOLVE_VERIFIED_SOURCE"), ("STAGE_C_SILVER_PUBLICATION", "PUBLISH_SILVER")}
    expected[ownership["originalR2"][8]].add(("STAGE_C_SILVER_PUBLICATION", "VERIFY_SILVER"))
    for node in ownership["originalR2"][10:]:
        expected[node] = {("STAGE_A_PHYSICAL_STAGING", "PUBLISH_SOURCE_OBJECT"), ("STAGE_B_GOVERNED_ISSUANCE", "RESOLVE_VERIFIED_SOURCE"), ("STAGE_C_SILVER_PUBLICATION", "PUBLISH_SILVER"), ("STAGE_C_SILVER_PUBLICATION", "VERIFY_SILVER")}
    for node in ownership["deltaD1"]:
        expected[node] = {("STAGE_A_PHYSICAL_STAGING", "PUBLISH_SOURCE_OBJECT"), ("STAGE_B_GOVERNED_ISSUANCE", "RESOLVE_VERIFIED_SOURCE"), ("STAGE_C_SILVER_PUBLICATION", "PUBLISH_SILVER"), ("STAGE_C_SILVER_PUBLICATION", "VERIFY_SILVER")}
    for index, node in enumerate(ownership["deltaD2"]):
        expected[node] = {("STAGE_A_PHYSICAL_STAGING", "PUBLISH_SOURCE_OBJECT"), ("STAGE_B_GOVERNED_ISSUANCE", "RESOLVE_VERIFIED_SOURCE")}
        if index in {0, 1, 2, 5}:
            expected[node].add(("STAGE_C_SILVER_PUBLICATION", "PUBLISH_SILVER"))
    assert dict(actual) == expected

    controls = [record for record in records if "-CTRL-" in record["requirementId"]]
    assert len(controls) == 12
    control_nodes = {
        ownership["originalR1"][2], ownership["originalR2"][8], ownership["deltaD1"][3],
    }
    assert {record["nodeId"] for record in controls} == control_nodes
    assert all(
        sum(record["nodeId"] == node for record in controls) == 4
        for node in control_nodes
    )
    assert {
        record["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"]
        for record in controls
    } == {"3de56d5007b2e09814f7440dc875d2eac03acb1fadcba942cd455c3a3fd63326"}

    nested_forbidden = deepcopy(records[0])
    nested_forbidden["authoritativePreconditions"]["nested"] = {"displayId": "forbidden"}
    with pytest.raises(AssertionError):
        _assert_no_forbidden_authority_dimensions(nested_forbidden)


def test_before_contract_reproduces_exactly_two_original_suite_conflicts() -> None:
    contract = _load(CONTRACT_PATH)
    before = _load(REPORT_PATH)["before"]
    calculated = {frozenset(group) for group in _conflicts(before["requirements"], contract["postconditionCatalog"])}
    declared = {frozenset(item["requirementIds"]) for item in before["conflictGroups"]}
    assert calculated == declared
    assert len(calculated) == 2
    assert {item["conflictId"] for item in before["conflictGroups"]} == {
        "D1_ORIGINAL_STAGE_A_FALSE_CALLBACK", "D2_ORIGINAL_STAGE_A_CALLER_ROWS",
    }
    assert all(record["suiteOwner"] == "original" for record in before["requirements"])
    d1 = [item for item in before["requirements"] if item["requirementId"].startswith("BEFORE-D1")]
    d2 = [item for item in before["requirements"] if item["requirementId"].startswith("BEFORE-D2")]
    assert len({_requirement_key(item) for item in d1}) == 1
    assert len({_requirement_key(item) for item in d2}) == 1
    assert {item["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"] for item in d1} == {
        "7eb846f0476ecb050d5951f4888e5785c9533ce4680caf4c2cecbd1b694b93cd"
    }
    assert {item["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"] for item in d2} == {
        "3de56d5007b2e09814f7440dc875d2eac03acb1fadcba942cd455c3a3fd63326"
    }


def test_reconciled_contract_has_zero_normalized_outcome_or_postcondition_conflicts() -> None:
    contract = _load(CONTRACT_PATH)
    report = _load(REPORT_PATH)
    assert _conflicts(report["after"]["requirements"], contract["postconditionCatalog"]) == []
    assert report["after"]["conflictGroups"] == []
    assert report["summary"]["beforeConflictCount"] == 2
    assert report["summary"]["afterConflictCount"] == 0
    assert set(report["summary"]["remainingCurrentProductionRedFindings"]) == {"D1", "D2"}

    base = report["after"]["requirements"][0]
    opposite = deepcopy(base)
    opposite["requirementId"] = "AFTER-SYNTHETIC-CONTRADICTION"
    opposite["resultContract"] = {
        "allowedResults": ["REJECT"],
        "allowedRejectionStages": [base["scientificStage"]],
        "postconditionsByResult": {"REJECT": ["PHYSICAL_OBJECT_ABSENT"]},
    }
    assert _conflicts([base, opposite], contract["postconditionCatalog"]) == [
        {base["requirementId"], opposite["requirementId"]}
    ]

    same_result_bad_post = deepcopy(base)
    same_result_bad_post["requirementId"] = "AFTER-SYNTHETIC-POSTCONDITION-CONTRADICTION"
    same_result_bad_post["resultContract"] = {
        "allowedResults": ["ACCEPT"],
        "allowedRejectionStages": [],
        "postconditionsByResult": {"ACCEPT": ["PHYSICAL_OBJECT_ABSENT"]},
    }
    assert _conflicts([base, same_result_bad_post], contract["postconditionCatalog"]) == [
        {base["requirementId"], same_result_bad_post["requirementId"]}
    ]


def test_normalization_ignores_only_cosmetics_and_preserves_exact_scientific_rows() -> None:
    records = _load(REPORT_PATH)["after"]["requirements"]
    base = next(item for item in records if item["requirementId"] == "AFTER-DELTA-D2-01-A")
    original_key = _requirement_key(base)
    cosmetic = deepcopy(base)
    cosmetic["cosmeticContext"] = {
        "displayIdClass": "RENAMED_PAIR", "pathClass": "MULTIPLE_EXTERNAL",
        "helperClass": "DIRECT", "witnessCount": 99,
    }
    assert _requirement_key(cosmetic) == original_key

    for field, value in (
        ("normalizedRowsSha256", "0" * 64),
        ("orderedColumnsSha256", "1" * 64),
    ):
        changed = deepcopy(base)
        changed["normalizedOperation"]["rowEvidence"][field] = value
        assert _requirement_key(changed) != original_key
    changed = deepcopy(base)
    changed["normalizedOperation"]["callbackOutputs"] = [2024, 2024]
    assert _requirement_key(changed) != original_key
    changed = deepcopy(base)
    changed["authoritativePreconditions"]["issuerRecordState"] = "VALID_PERSISTED_SERVER_ISSUER"
    assert _requirement_key(changed) != original_key

    original_2019 = next(item for item in records if item["requirementId"] == "AFTER-ORIGINAL-R1-03-A")
    delta_2019 = next(item for item in records if item["requirementId"] == "AFTER-DELTA-D1-04-A")
    assert original_2019["normalizedOperation"]["rowEvidence"] == delta_2019["normalizedOperation"]["rowEvidence"]
    assert _requirement_key(original_2019) == _requirement_key(delta_2019)

    original_2023 = next(item for item in records if item["requirementId"] == "AFTER-ORIGINAL-R2-11-A")
    unregistered_2023 = next(item for item in records if item["requirementId"] == "AFTER-ORIGINAL-R2-08-A")
    delta_2023 = next(item for item in records if item["requirementId"] == "AFTER-DELTA-D2-01-A")
    assert unregistered_2023["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"] == (
        "0538ca4d2789979dfde1eed44cc07caec08b2c83688bcc5487d1b2fa2ce3627e"
    )
    assert original_2023["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"] != unregistered_2023["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"]
    assert original_2023["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"] != delta_2023["normalizedOperation"]["rowEvidence"]["normalizedRowsSha256"]


def test_d3_d6_d7_d8_and_transitive_inputs_are_byte_identical() -> None:
    contract = _load(CONTRACT_PATH)
    protected = contract["protectedAuthorities"]
    manifests = {"original": _load(ORIGINAL_MANIFEST_PATH), "delta": _load(DELTA_MANIFEST_PATH)}
    assert _file_sha(REPO / protected["sharedHelper"]["path"]) == protected["sharedHelper"]["sha256"]
    for item in protected["transitiveInputs"]:
        assert _file_sha(REPO / item["path"]) == item["sha256"]

    id_map = {
        "R3": "R3_RELATIONAL_SILVER_VERIFICATION",
        "R4": "R4_CANONICAL_QUARANTINE_BOUNDARY",
        "R6": "R6_COMPLETE_REPARSE_CONTAINMENT",
        "R7": "R7_DATA_HERMETIC_GATE",
        "R8": "R8_COLLECTION_AND_SKIP_GOVERNANCE",
        "D3": "D3_OUTER_RELATIONAL_RECONSTRUCTION",
        "D6": "D6_PRE_IO_CONTAINMENT_ORDER",
        "D7": "D7_SESSION_BOUND_TEMP_AUTHORITY",
        "D8": "D8_INJECTIVE_COLLECTION_RESULT_PARITY",
    }
    for owner in ("original", "delta"):
        findings = {item["findingId"]: item for item in manifests[owner]["findings"]}
        for short_id, authority in protected[owner].items():
            finding = findings[id_map[short_id]]
            assert _file_sha(REPO / authority["path"]) == authority["fileSha256"]
            assert _canonical_sha(finding) == authority["findingSha256"]
            assert _canonical_sha(finding["pytestNodeIds"]) == authority["nodeListSha256"]
            assert len(finding["pytestNodeIds"]) == authority["expectedNodeCount"]


def test_contract_package_contains_no_alternate_production_path() -> None:
    package_files = sorted(HERE.glob("*.py"))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in package_files)
    assert ("from " + "server.") not in combined
    assert ("import " + "server.") not in combined
    assert ("def " + "publish_") not in combined
    assert ("monkey" + "patch") not in combined
