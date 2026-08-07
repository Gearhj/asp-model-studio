from __future__ import annotations

import copy
import unittest

from server.bureau_metadata.crosswalk import (
    CatalogSelectionError,
    build_crosswalk_candidates,
    build_dataset_crosswalk,
)


CATALOG_A = {
    "provider": "Synthetic Provider A",
    "product": "Attributes One",
    "edition": "US",
    "dictionary_version": "v1",
}

CATALOG_B = {
    "provider": "Synthetic Provider B",
    "product": "Attributes Two",
    "edition": "CA",
    "dictionary_version": "2026.1",
}
CATALOG_A_CHECKSUM = "a" * 64
CATALOG_B_CHECKSUM = "b" * 64


def attribute(
    code: str,
    description: str,
    *,
    units: str = "count",
    minimum: str = "0",
    maximum: str = "99",
    catalog: dict[str, str] = CATALOG_A,
) -> dict[str, object]:
    return {
        **catalog,
        "attribute_code": code,
        "description": description,
        "units": units,
        "ordinary_valid_min": minimum,
        "ordinary_valid_max": maximum,
    }


ATTRIBUTES = [
    attribute(
        "A100",
        "Revolving balance amount",
        units="currency",
        maximum="100000",
    ),
    attribute("B200", "Recent inquiry count"),
    attribute("B201", "Recent inquiry count alternative"),
]


class BureauMetadataCrosswalkTest(unittest.TestCase):
    def test_exact_code_match_remains_a_candidate_requiring_confirmation(self) -> None:
        candidates = build_crosswalk_candidates(
            {"field_name": "A100", "observed_min": "0", "observed_max": "5000"},
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
        )

        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        self.assertEqual("exact_dictionary_code_match", candidate["match_status"])
        self.assertEqual("A100", candidate["candidate_attribute_code"])
        self.assertTrue(candidate["candidate_only"])
        self.assertFalse(candidate["approved_mapping"])
        self.assertTrue(candidate["required_analyst_confirmation"])

    def test_institution_approved_alias_is_not_auto_approved_as_a_dataset_mapping(self) -> None:
        aliases = [
            {
                **CATALOG_A,
                "dataset_field": "LocalBalance",
                "attribute_code": "A100",
                "approval_status": "approved",
                "evidence_id": "synthetic-alias-policy-1",
            }
        ]
        candidates = build_crosswalk_candidates(
            {"field_name": "LocalBalance"},
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
            aliases=aliases,
        )

        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        self.assertEqual("approved_institutional_alias", candidate["match_status"])
        self.assertEqual("synthetic-alias-policy-1", candidate["institutional_alias_reference"])
        self.assertFalse(candidate["approved_mapping"])
        self.assertTrue(candidate["required_analyst_confirmation"])

    def test_unapproved_or_unversioned_alias_is_not_used(self) -> None:
        aliases = [
            {
                **CATALOG_A,
                "dataset_field": "OpaqueLocalField",
                "attribute_code": "A100",
                "approval_status": "draft",
                "evidence_id": "draft-only",
            },
            {
                "dataset_field": "OpaqueLocalField",
                "attribute_code": "B200",
                "approval_status": "approved",
                "evidence_id": "missing-catalog-version",
            },
        ]
        candidates = build_crosswalk_candidates(
            {"field_name": "OpaqueLocalField"},
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
            aliases=aliases,
        )

        self.assertEqual("no_supported_match", candidates[0]["match_status"])
        self.assertIsNone(candidates[0]["candidate_attribute_code"])

    def test_negative_modeling_codes_remain_unresolved_without_durable_recode_evidence(self) -> None:
        candidates = build_crosswalk_candidates(
            {
                "field_name": "B200",
                "observed_special_values": ["-7", "-8"],
            },
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
        )

        candidate = candidates[0]
        self.assertEqual("unresolved_recoding", candidate["match_status"])
        self.assertEqual("B200", candidate["candidate_attribute_code"])
        self.assertEqual(
            "withheld_pending_durable_recode_evidence",
            candidate["special_value_evidence"]["source_meaning_assignment"],
        )
        self.assertTrue(candidate["transformation_or_recoding_concerns"])
        self.assertNotIn("meaning", " ".join(candidate["special_value_evidence"]["observed_values"]))

    def test_durable_recode_evidence_removes_the_unresolved_status_but_assigns_no_meaning(self) -> None:
        candidates = build_crosswalk_candidates(
            {
                "field_name": "B200",
                "observed_special_values": ["-7"],
                "durable_recode_evidence": {
                    "evidence_id": "synthetic-transform-1",
                    "source_to_model": {"source-special-a": "-7"},
                },
            },
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
        )

        candidate = candidates[0]
        self.assertEqual("exact_dictionary_code_match", candidate["match_status"])
        self.assertEqual(
            "not_assigned_by_crosswalk",
            candidate["special_value_evidence"]["source_meaning_assignment"],
        )

    def test_target_and_deterministic_target_source_are_never_mapping_candidates(self) -> None:
        target = build_crosswalk_candidates(
            {"field_name": "outcome"},
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
            target_field="outcome",
            target_source_fields=("source_outcome",),
        )[0]
        target_source = build_crosswalk_candidates(
            {"field_name": "source_outcome"},
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
            target_field="outcome",
            target_source_fields=("source_outcome",),
        )[0]

        self.assertEqual("target", target["match_status"])
        self.assertEqual("deterministic_target_source", target_source["match_status"])
        for candidate in (target, target_source):
            self.assertIsNone(candidate["candidate_attribute_code"])
            self.assertFalse(candidate["approved_mapping"])
            self.assertFalse(candidate["required_analyst_confirmation"])

    def test_equivalent_semantic_matches_stay_ambiguous(self) -> None:
        candidates = build_crosswalk_candidates(
            {
                "field_name": "RecentInquiryCount",
                "description": "Recent inquiry count",
                "units": "count",
                "observed_min": "0",
                "observed_max": "20",
            },
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
        )

        self.assertEqual(["B200", "B201"], [row["candidate_attribute_code"] for row in candidates])
        self.assertTrue(all(row["match_status"] == "multiple_possible_matches" for row in candidates))
        self.assertTrue(all(row["ambiguity"] == ["B200", "B201"] for row in candidates))
        self.assertTrue(all(not row["approved_mapping"] for row in candidates))

    def test_catalog_selection_is_provider_neutral_and_has_no_version_fallback(self) -> None:
        provider_b_attribute = attribute(
            "Z900",
            "Synthetic alternate provider measure",
            catalog=CATALOG_B,
        )
        all_attributes = [*ATTRIBUTES, provider_b_attribute]

        provider_b = build_crosswalk_candidates(
            {"field_name": "Z900"},
            all_attributes,
            catalog_key={
                "provider": CATALOG_B["provider"],
                "product": CATALOG_B["product"],
                "edition": CATALOG_B["edition"],
                "version": CATALOG_B["dictionary_version"],
            },
            catalog_checksum=CATALOG_B_CHECKSUM,
        )[0]
        self.assertEqual("Synthetic Provider B", provider_b["provider"])
        self.assertEqual("Z900", provider_b["candidate_attribute_code"])

        with self.assertRaisesRegex(CatalogSelectionError, "fallback is prohibited"):
            build_crosswalk_candidates(
                {"field_name": "Z900"},
                all_attributes,
                catalog_key={**CATALOG_B, "dictionary_version": "missing-version"},
                catalog_checksum=CATALOG_B_CHECKSUM,
            )

    def test_dataset_crosswalk_is_deterministic_candidate_only_and_nonmutating(self) -> None:
        fields = [
            {"field_name": "A100"},
            {"field_name": "outcome"},
            {"field_name": "local_note", "non_catalog_field": True},
        ]
        original_fields = copy.deepcopy(fields)
        original_attributes = copy.deepcopy(ATTRIBUTES)

        first = build_dataset_crosswalk(
            fields,
            ATTRIBUTES,
            catalog_key=CATALOG_A,
            catalog_checksum=CATALOG_A_CHECKSUM,
            target_field="outcome",
        )
        second = build_dataset_crosswalk(
            copy.deepcopy(fields),
            copy.deepcopy(ATTRIBUTES),
            catalog_key=copy.deepcopy(CATALOG_A),
            catalog_checksum=CATALOG_A_CHECKSUM,
            target_field="outcome",
        )

        self.assertEqual(first, second)
        self.assertEqual(fields, original_fields)
        self.assertEqual(ATTRIBUTES, original_attributes)
        self.assertEqual("candidate_only", first["crosswalk_status"])
        self.assertEqual(CATALOG_A_CHECKSUM, first["catalog_checksum"])
        self.assertEqual([], first["approved_mappings"])
        self.assertFalse(first["governed_feature_set_changed"])
        self.assertFalse(first["dataset_mutated"])
        self.assertTrue(all(row["candidate_only"] for row in first["mappings"]))
        self.assertTrue(all(not row["approved_mapping"] for row in first["mappings"]))
        self.assertTrue(
            all(
                row["catalog_checksum"] == CATALOG_A_CHECKSUM
                for row in first["mappings"]
            )
        )

    def test_exact_catalog_checksum_is_required_and_propagated(self) -> None:
        with self.assertRaisesRegex(TypeError, "catalog_checksum"):
            build_crosswalk_candidates(  # type: ignore[call-arg]
                {"field_name": "A100"},
                ATTRIBUTES,
                catalog_key=CATALOG_A,
            )
        with self.assertRaisesRegex(
            ValueError,
            "exact lowercase catalog checksum",
        ):
            build_dataset_crosswalk(
                [{"field_name": "A100"}],
                ATTRIBUTES,
                catalog_key=CATALOG_A,
                catalog_checksum="not-an-exact-checksum",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
