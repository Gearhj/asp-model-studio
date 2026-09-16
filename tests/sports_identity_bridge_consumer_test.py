from __future__ import annotations

import copy
import json
import os
import unittest
import uuid
from pathlib import Path
from typing import Any

from server.sports_identity_bridges import (
    MLBFD1IdentityAdapter,
    IdentityBridgeValidationError,
    SportsIdentityBridgeV1Consumer,
)
from server.sports_identity_bridges.constants import (
    ALIAS_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    DIMENSION_AUTHORITY_SHA,
    EXPECTED_JOIN_REFERENCES,
    EXPECTED_JOIN_VALIDATION,
    EXPECTED_Y_MINUS_1,
)
from server.sports_identity_bridges.consumer import (
    MlbFd1IdentityBridgeAdapter,
    _scan_json_security,
    approved_bridge_root,
    semantic_bridge_manifest_sha,
)
from server.sports_datasets.consumer import ManifestValidationError, load_strict_json
from tests.sports_dataset_test_fixture import golden_corpus_available, golden_package


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = REPOSITORY_ROOT / ".tmp"


def _scratch(name: str) -> Path:
    path = SCRATCH_ROOT / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _contains_physical_path(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in {"path", "physicalpath", "packageroot"}
            or _contains_physical_path(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_physical_path(item) for item in value)
    if isinstance(value, str):
        folded = value.casefold()
        return (
            bool(len(value) >= 3 and value[1:3] in {":\\", ":/"})
            or value.startswith(("/", "\\\\", "file:"))
            or ".runtime" in folded
        )
    return False


class IdentityBridgeStrictUnitTests(unittest.TestCase):
    def test_duplicate_keys_and_invalid_utf8_are_rejected(self) -> None:
        root = _scratch("identity-bridge-strict-json")
        duplicate = root / "duplicate.json"
        duplicate.write_text('{"bridge":1,"bridge":2}', encoding="utf-8")
        with self.assertRaises(ManifestValidationError) as raised:
            load_strict_json(duplicate, logical_uri="duplicate.json")
        self.assertEqual(raised.exception.code, "DUPLICATE_JSON_KEY")

        invalid = root / "invalid.json"
        invalid.write_bytes(b'{"bridge":"\xff"}')
        with self.assertRaises(ManifestValidationError) as raised:
            load_strict_json(invalid, logical_uri="invalid.json")
        self.assertEqual(raised.exception.code, "INVALID_UTF8")

    def test_runtime_physical_and_credential_fields_are_rejected(self) -> None:
        for value in (
            {"logical_uri": "C:/private/bridge.json"},
            {"logical_uri": "file:///private/bridge.json"},
            {"logical_uri": "/private/bridge.json"},
            {"credential": "not-a-real-secret"},
        ):
            with self.subTest(value=value), self.assertRaises(IdentityBridgeValidationError):
                _scan_json_security(value)

    def test_retrosheet_resolution_is_exact_and_has_no_fallback(self) -> None:
        targets = {"retrosheet:player:heuec001": frozenset({"uuid-authority"})}
        self.assertEqual(
            MLBFD1IdentityAdapter._resolve_exact(
                "retrosheet:player:heuec001",
                alias_targets=targets,
            ),
            ("RESOLVED", "uuid-authority"),
        )
        for inferred in ("heuec001", "RETROSHEET:PLAYER:HEUEC001", " heuec001 "):
            with self.subTest(inferred=inferred):
                self.assertEqual(
                    MLBFD1IdentityAdapter._resolve_exact(inferred, alias_targets=targets),
                    ("UNRESOLVED", None),
                )


@unittest.skipUnless(
    golden_corpus_available(),
    "ASP_MODEL_EXCHANGE_ROOT is required for golden identity-bridge tests",
)
class GoldenIdentityBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        exchange_root = Path(os.environ["ASP_MODEL_EXCHANGE_ROOT"])
        cls.bridge_root = approved_bridge_root(exchange_root)
        cls.bridge = SportsIdentityBridgeV1Consumer(cls.bridge_root).validate()
        cls.parent, _parent_root, _cache_path = golden_package()
        cls.progress: list[dict[str, Any]] = []
        cls.audit = MLBFD1IdentityAdapter(
            cls.bridge,
            cls.parent,
            progress=lambda item: cls.progress.append(dict(item)),
        ).build_join_audit()

    def test_exact_golden_bridge_validates_through_public_consumer(self) -> None:
        self.assertEqual(self.bridge.manifest["bridge_manifest_sha256"], BRIDGE_MANIFEST_SHA)
        self.assertEqual(semantic_bridge_manifest_sha(self.bridge.manifest), BRIDGE_MANIFEST_SHA)
        self.assertEqual(len(self.bridge.aliases), 13_460)
        self.assertEqual(len(self.bridge.dimensions), 2_692)
        self.assertEqual(self.bridge.alias_rows, self.bridge.aliases)
        self.assertEqual(self.bridge.dimension_rows, self.bridge.dimensions)

    def test_frozen_row_authorities_reconcile(self) -> None:
        self.assertEqual(
            self.bridge.manifest["totals"]["alias_authority_sha256"],
            ALIAS_AUTHORITY_SHA,
        )
        self.assertEqual(
            self.bridge.manifest["totals"]["dimension_authority_sha256"],
            DIMENSION_AUTHORITY_SHA,
        )

    def test_manifest_extra_key_and_semantic_change_are_rejected(self) -> None:
        extra = copy.deepcopy(self.bridge.manifest)
        extra["unexpected"] = True
        with self.assertRaises(IdentityBridgeValidationError) as raised:
            MlbFd1IdentityBridgeAdapter.validate_manifest_contract(extra)
        self.assertEqual(raised.exception.code, "BRIDGE_MANIFEST_FIELDS_MISMATCH")

        changed = copy.deepcopy(self.bridge.manifest)
        changed["evidence_cutoff"] = "2026-08-16"
        with self.assertRaises(IdentityBridgeValidationError):
            MlbFd1IdentityBridgeAdapter.validate_manifest_contract(changed)

    def test_rights_and_one_player_zero_impact_are_fail_closed(self) -> None:
        rights = copy.deepcopy(self.bridge.source_rights)
        rights["package_controls"]["raw_redistribution_authorized"] = True
        with self.assertRaises(IdentityBridgeValidationError) as raised:
            MlbFd1IdentityBridgeAdapter._validate_source_rights(rights)
        self.assertEqual(raised.exception.code, "RIGHTS_CONTROL_MISMATCH")

        changed = copy.deepcopy(self.bridge.manifest)
        changed["coverage_evidence"]["downstream_impacted_rows"] = 1
        with self.assertRaises(IdentityBridgeValidationError) as raised:
            MlbFd1IdentityBridgeAdapter._validate_one_player_limitation(changed)
        self.assertEqual(raised.exception.code, "ONE_PLAYER_LIMITATION_MISMATCH")

    def test_exact_join_audit_matches_all_frozen_authorities(self) -> None:
        self.assertEqual(self.audit["status"], "PASS")
        self.assertEqual(self.audit["totalReferences"], EXPECTED_JOIN_REFERENCES)
        self.assertEqual(self.audit["resolvedReferences"], EXPECTED_JOIN_REFERENCES)
        self.assertEqual(self.audit["mappingRate"], 1.0)
        self.assertEqual(self.audit["unresolvedReferences"], 0)
        self.assertEqual(self.audit["ambiguousReferences"], 0)
        self.assertEqual(self.audit["multiplyMappedReferences"], 0)
        self.assertEqual(len(self.audit["joins"]), len(EXPECTED_JOIN_VALIDATION))
        for item in self.audit["joins"]:
            references, unique_sources, unique_players = EXPECTED_JOIN_VALIDATION[
                item["joinContractId"]
            ]
            self.assertEqual(item["referenceCount"], references)
            self.assertEqual(item["uniqueSourceIds"], unique_sources)
            self.assertEqual(item["uniqueCanonicalPlayers"], unique_players)

    def test_y_minus_one_counts_and_primary_pa_counts_are_exact(self) -> None:
        self.assertEqual(len(self.audit["yMinus1Coverage"]), len(EXPECTED_Y_MINUS_1))
        for item in self.audit["yMinus1Coverage"]:
            expected = EXPECTED_Y_MINUS_1[(item["targetSeason"], item["role"])]
            self.assertEqual(
                (
                    item["referenceRows"],
                    item["rowsWithEligiblePrior"],
                    item["legitimateMissingPriorRows"],
                    item["maximumEligiblePriorSeason"],
                ),
                expected,
            )

    def test_join_audit_is_public_safe_and_emits_completion_progress(self) -> None:
        self.assertFalse(_contains_physical_path(self.audit))
        self.assertTrue(self.audit["noNamesOrFuzzyMatching"])
        self.assertEqual(self.progress[-1]["stage"], "JOIN_AUDIT_PASS")
        self.assertEqual(self.progress[-1]["errors"], 0)


if __name__ == "__main__":
    unittest.main()
