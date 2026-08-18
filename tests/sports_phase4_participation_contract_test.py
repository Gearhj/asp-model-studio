from __future__ import annotations

import copy
import math
import unittest

from server.sports_phase4.dynamic_contract import (
    HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION,
    dynamic_state_contract_payload,
    dynamic_state_contract_sha,
    dynamic_history_index_schema_sha,
    dynamic_state_schema_sha,
)
from server.sports_phase4.dynamic_state import FrozenDynamicPolicy
from server.sports_phase4.participation_contract import (
    BULLPEN_DECISION_ENUM,
    BULLPEN_FEATURES,
    DYNAMIC_CONTRACT_SHA,
    DYNAMIC_LOGICAL_URI_PREFIX,
    LINEUP_DECISION_ENUM,
    LINEUP_FEATURES,
    STARTER_DECISION_ENUM,
    STARTER_FEATURES,
    BullpenDecisionEvidence,
    LineupDecisionEvidence,
    ParticipationContractError,
    StarterDecisionEvidence,
    bullpen_decision,
    contract_set_payload,
    lineup_decision,
    starter_decision,
    validate_dynamic_descriptor,
)


def _dynamic_descriptor() -> dict[str, object]:
    artifact_sha = "2" * 64
    history_sha = "3" * 64
    authorities = dynamic_state_contract_payload()["authorityBindings"]
    return {
        "contractName": "MLB_DYNAMIC_PLAYER_STATE_V1",
        "contractSha": dynamic_state_contract_sha(),
        "schemaSha": dynamic_state_schema_sha(),
        "contentSha": "1" * 64,
        "artifactSha": artifact_sha,
        "artifactBytes": 100,
        "logicalUri": (
            f"{DYNAMIC_LOGICAL_URI_PREFIX}objects/sha256/22/{artifact_sha}/state.parquet"
        ),
        "parent": copy.deepcopy(authorities["dataset"]),
        "identityBridge": copy.deepcopy(authorities["identityBridge"]),
        "phase3": copy.deepcopy(authorities["phase3"]),
        "selectedPolicy": FrozenDynamicPolicy.create(
            half_life_days=30,
            prior_ess=50,
        ).public(),
        "historyIndex": {
            "schemaVersion": HISTORY_INDEX_DESCRIPTOR_SCHEMA_VERSION,
            "contractName": "MLB_DYNAMIC_PLAYER_STATE_V1",
            "contractSha": dynamic_state_contract_sha(),
            "schemaSha": dynamic_history_index_schema_sha(),
            "contentSha": "4" * 64,
            "artifactId": f"sports-phase4-artifact:dynamic_history_index:sha256:{history_sha}",
            "artifactSha": history_sha,
            "artifactBytes": 100,
            "logicalUri": (
                f"{DYNAMIC_LOGICAL_URI_PREFIX}objects/sha256/33/{history_sha}/history.parquet"
            ),
            "mediaType": "application/vnd.apache.parquet",
            "rowCount": 1,
            "sourceRowCount": 1,
            "resolvedReferenceCount": 2,
            "sourcePartitionIds": ["fixture-history-partition"],
            "authorityBindings": {
                "dataset": copy.deepcopy(authorities["dataset"]),
                "identityBridge": copy.deepcopy(authorities["identityBridge"]),
            },
        },
        "dynamicComponentId": (
            "sports-phase4-component:dynamic-player-state:sha256:" + "5" * 64
        ),
    }


class ParticipationContractTest(unittest.TestCase):
    def test_contract_names_features_and_enums_are_exact(self) -> None:
        payload = contract_set_payload()["contracts"]
        self.assertEqual(payload["lineup"]["contractName"], "MLB_LINEUP_PROJECTION_V1")
        self.assertEqual(payload["starter"]["contractName"], "MLB_STARTER_DURATION_V1")
        self.assertEqual(payload["bullpen"]["contractName"], "MLB_BULLPEN_USAGE_V1")
        self.assertEqual(tuple(payload["lineup"]["featureNames"]), LINEUP_FEATURES)
        self.assertEqual(tuple(payload["starter"]["featureNames"]), STARTER_FEATURES)
        self.assertEqual(tuple(payload["bullpen"]["featureNames"]), BULLPEN_FEATURES)
        self.assertEqual(tuple(payload["lineup"]["decisionPolicy"]["enum"]), LINEUP_DECISION_ENUM)
        self.assertEqual(tuple(payload["starter"]["decisionPolicy"]["enum"]), STARTER_DECISION_ENUM)
        self.assertEqual(tuple(payload["bullpen"]["decisionPolicy"]["enum"]), BULLPEN_DECISION_ENUM)
        for features in (LINEUP_FEATURES, STARTER_FEATURES, BULLPEN_FEATURES):
            self.assertFalse(any("_id" in name or "uuid" in name for name in features))

    def test_dynamic_contract_sha_is_shared_and_tamper_fails(self) -> None:
        self.assertEqual(DYNAMIC_CONTRACT_SHA, dynamic_state_contract_sha())
        valid = _dynamic_descriptor()
        self.assertEqual(validate_dynamic_descriptor(valid)["contractSha"], DYNAMIC_CONTRACT_SHA)
        for path in ("contractSha", "schemaSha"):
            tampered = copy.deepcopy(valid)
            tampered[path] = "f" * 64
            with self.assertRaises(ParticipationContractError):
                validate_dynamic_descriptor(tampered)
        tampered = copy.deepcopy(valid)
        tampered["phase3"]["featureContractSha"] = "f" * 64  # type: ignore[index]
        with self.assertRaises(ParticipationContractError):
            validate_dynamic_descriptor(tampered)

    def test_lineup_decision_uses_both_folds_and_coverage(self) -> None:
        component = lineup_decision(LineupDecisionEvidence(0.01, 0.02, 0.95, 0.96))
        self.assertEqual(component["decision"], "LINEUP_RESEARCH_COMPONENT")
        baseline = lineup_decision(LineupDecisionEvidence(0.01, -0.01, 0.99, 0.99))
        self.assertEqual(baseline["decision"], "LINEUP_RESEARCH_BASELINE")
        blocked = lineup_decision(
            LineupDecisionEvidence(0.01, 0.02, 1.0, 1.0, "fixture integrity")
        )
        self.assertEqual(blocked["decision"], "LINEUP_BLOCKED")

    def test_starter_decision_requires_s0_and_s1_all_metrics_both_folds(self) -> None:
        values = [0.1] * 8
        component = starter_decision(StarterDecisionEvidence(*values))
        self.assertEqual(component["decision"], "STARTER_DURATION_RESEARCH_COMPONENT")
        values[3] = 0.0
        baseline = starter_decision(StarterDecisionEvidence(*values))
        self.assertEqual(baseline["decision"], "STARTER_DURATION_RESEARCH_BASELINE")

    def test_bullpen_gate_uses_raw_logloss_brier_calibration_and_coverage(self) -> None:
        component = bullpen_decision(
            BullpenDecisionEvidence(0.01, 0.02, 0.0, -1e-10, 0.95, 0.96, True, True)
        )
        self.assertEqual(component["decision"], "BULLPEN_USAGE_RESEARCH_COMPONENT")
        baseline = bullpen_decision(
            BullpenDecisionEvidence(0.01, 0.02, -2e-10, 0.0, 1.0, 1.0, True, True)
        )
        self.assertEqual(baseline["decision"], "BULLPEN_USAGE_RESEARCH_BASELINE")
        with self.assertRaises(ParticipationContractError):
            bullpen_decision(
                BullpenDecisionEvidence(math.nan, 0.02, 0.0, 0.0, 1.0, 1.0, True, True)
            )


if __name__ == "__main__":
    unittest.main()
