"""Focused optional Bureau Metadata Catalog handoff tests for EDA."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.eda import eda_router
from server.eda.analytical_contract import EDAAnalyticalContractError
from server.eda.bureau_semantic_contract import (
    validate_bureau_semantic_handoff,
)
from server.eda.workspace_service import (
    EDAWorkspaceService,
    _bureau_semantic_request_identity,
    _bureau_semantic_response_lineage,
)
from server.eda.workspace_types import EDAWorkspaceRequest


PROJECT_ID = "project-bureau-eda"
DATASET_ID = "dataset-bureau-eda"
VERSION_ID = "version-bureau-eda"
SCHEMA_CHECKSUM = "1" * 64
ANNOTATION_CHECKSUM = "2" * 64
BINDING_CHECKSUM = "3" * 64
CROSSWALK_CHECKSUM = "4" * 64
CATALOG_CHECKSUM = "5" * 64


def _semantic_fields(*, crosswalk_revision: int = 3) -> dict[str, object]:
    return {
        "bureau_semantic_annotation_state": "available",
        "bureau_semantic_annotation_set_id": "bsas-exact-current",
        "bureau_semantic_annotation_set_checksum": ANNOTATION_CHECKSUM,
        "bureau_metadata_schema_checksum": SCHEMA_CHECKSUM,
        "bureau_metadata_binding_id": "binding-exact-current",
        "bureau_metadata_binding_revision": 7,
        "bureau_metadata_binding_revision_checksum": BINDING_CHECKSUM,
        "bureau_metadata_crosswalk_id": "crosswalk-exact-current",
        "bureau_metadata_crosswalk_revision": crosswalk_revision,
        "bureau_metadata_crosswalk_revision_checksum": CROSSWALK_CHECKSUM,
        "bureau_metadata_catalog_version_id": "catalog-version-exact",
        "bureau_metadata_catalog_checksum": CATALOG_CHECKSUM,
    }


def _request(
    *,
    crosswalk_revision: int = 3,
    **overrides: object,
) -> EDAWorkspaceRequest:
    values: dict[str, object] = {
        "project_id": PROJECT_ID,
        "dataset_id": DATASET_ID,
        "dataset_version_id": VERSION_ID,
        "analysis_partition_id": "partition-current",
        "analysis_partition_revision": 11,
        **_semantic_fields(crosswalk_revision=crosswalk_revision),
    }
    values.update(overrides)
    return EDAWorkspaceRequest(**values)


def _envelope(
    *,
    crosswalk_revision: int = 3,
    unresolved_provider_authoritative: bool = False,
) -> dict[str, object]:
    return {
        "ok": True,
        "annotation_set": {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "annotation_set_id": "bsas-exact-current",
            "annotation_set_checksum": ANNOTATION_CHECKSUM,
            "schema_checksum": SCHEMA_CHECKSUM,
            "binding_id": "binding-exact-current",
            "binding_revision": 7,
            "binding_revision_checksum": BINDING_CHECKSUM,
            "crosswalk_id": "crosswalk-exact-current",
            "crosswalk_revision": crosswalk_revision,
            "crosswalk_revision_checksum": CROSSWALK_CHECKSUM,
            "catalog_version_id": "catalog-version-exact",
            "catalog_checksum": CATALOG_CHECKSUM,
            "dataset_mutated": False,
            "target_contract_mutated": False,
            "treatment_mutated": False,
            "predictor_authorization_mutated": False,
            "analysis_partition_mutated": False,
            "feature_manifest_mutated": False,
        },
        "annotations": [
            {
                "dataset_field": "ExternalRiskEstimate",
                "mapping_state": "exact_verified",
                "provider_authoritative": True,
                "final_holdout_accessed": False,
            },
            {
                "dataset_field": "GenericInquiryField",
                "mapping_state": "unresolved",
                "provider_authoritative": unresolved_provider_authoritative,
                "final_holdout_accessed": False,
            },
        ],
    }


class EDABureauSemanticHandoffTest(unittest.TestCase):
    def test_exact_da_and_eda_revisions_match_and_rows_do_not_propagate(self) -> None:
        request = _request()
        with patch(
            "server.bureau_metadata.crosswalk_router.resolve_exact_semantic_handoff_for_user",
            return_value=_envelope(),
        ) as resolver:
            result = validate_bureau_semantic_handoff(
                request,
                {"userId": "bureau-eda-user"},
            )

        resolver.assert_called_once_with(
            project_id=PROJECT_ID,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            user={"userId": "bureau-eda-user"},
        )
        self.assertEqual(result["binding_revision"], 7)
        self.assertEqual(result["crosswalk_revision"], 3)
        self.assertEqual(result["authoritative_annotation_count"], 1)
        self.assertEqual(result["non_authoritative_annotation_count"], 1)
        self.assertFalse(result["annotations_included"])
        self.assertFalse(result["provider_catalog_rows_included"])
        self.assertFalse(result["unresolved_mappings_authoritative"])
        self.assertFalse(result["final_holdout_accessed"])
        self.assertEqual(request.analysis_partition_revision, 11)

    def test_stale_crosswalk_revision_fails_before_eda(self) -> None:
        request = _request()
        with patch(
            "server.eda.bureau_semantic_contract._resolve_exact",
            return_value=_envelope(crosswalk_revision=4),
        ), self.assertRaises(EDAAnalyticalContractError) as raised:
            validate_bureau_semantic_handoff(
                request,
                {"userId": "bureau-eda-user"},
            )
        self.assertEqual(
            raised.exception.code,
            "bureau_semantic_annotation_stale",
        )

    def test_unresolved_mapping_can_never_be_provider_authoritative(self) -> None:
        with patch(
            "server.eda.bureau_semantic_contract._resolve_exact",
            return_value=_envelope(unresolved_provider_authoritative=True),
        ), self.assertRaises(EDAAnalyticalContractError) as raised:
            validate_bureau_semantic_handoff(
                _request(),
                {"userId": "bureau-eda-user"},
            )
        self.assertIn("unresolved", str(raised.exception).casefold())

    def test_optional_unavailable_is_nonblocking_for_absent_unentitled_or_unavailable_service(
        self,
    ) -> None:
        request = EDAWorkspaceRequest(
            project_id=PROJECT_ID,
            dataset_id=DATASET_ID,
            dataset_version_id=VERSION_ID,
            bureau_semantic_annotation_state="unavailable",
        )
        for status, expected in (
            (403, "not_entitled"),
            (404, "not_bound"),
            (500, "service_unavailable"),
            (503, "service_unavailable"),
        ):
            with self.subTest(status=status), patch(
                "server.eda.bureau_semantic_contract._resolve_exact",
                side_effect=HTTPException(status_code=status),
            ):
                result = validate_bureau_semantic_handoff(
                    request,
                    {"userId": "bureau-eda-user"},
                )
            self.assertEqual(result["server_resolution"], expected)
            self.assertFalse(result["authoritative"])

        with patch(
            "server.eda.bureau_semantic_contract._resolve_exact",
            return_value=_envelope(),
        ), self.assertRaises(EDAAnalyticalContractError) as raised:
            validate_bureau_semantic_handoff(
                request,
                {"userId": "bureau-eda-user"},
            )
        self.assertEqual(
            raised.exception.code,
            "bureau_semantic_annotation_false_unavailable",
        )

    def test_available_identity_is_all_or_none(self) -> None:
        with self.assertRaises(ValidationError):
            EDAWorkspaceRequest(
                project_id=PROJECT_ID,
                dataset_id=DATASET_ID,
                dataset_version_id=VERSION_ID,
                bureau_semantic_annotation_state="available",
                bureau_semantic_annotation_set_id="incomplete",
            )
        with self.assertRaises(ValidationError):
            EDAWorkspaceRequest(
                project_id=PROJECT_ID,
                bureau_semantic_annotation_state="unavailable",
                bureau_metadata_binding_id="contradictory",
            )

    def test_cache_and_response_lineage_change_with_crosswalk_revision(self) -> None:
        service = EDAWorkspaceService()
        request_three = _request()
        request_four = _request(crosswalk_revision=4)
        contract_three = {
            "analysis_partition_id": "partition-current",
            "analysis_partition_revision": 11,
            "bureau_semantic_identity": _bureau_semantic_request_identity(
                request_three
            ),
        }
        contract_four = {
            **contract_three,
            "bureau_semantic_identity": _bureau_semantic_request_identity(
                request_four
            ),
        }
        frame = pd.DataFrame({"risk": [1, 2], "bad_flag": [0, 1]})
        authorization = {
            "manifest_version": "predictor-auth",
            "authorized_predictors": ["risk"],
        }
        key_three = service._key(
            "overview",
            request_three,
            frame,
            "bad_flag",
            authorization,
            "fingerprint",
            contract_three,
        )
        key_four = service._key(
            "overview",
            request_four,
            frame,
            "bad_flag",
            authorization,
            "fingerprint",
            contract_four,
        )
        self.assertNotEqual(key_three, key_four)
        lineage = _bureau_semantic_response_lineage(contract_three)
        self.assertEqual(
            lineage["bureau_metadata_crosswalk_revision"],
            3,
        )
        nested = lineage["bureau_semantic_annotations"]
        self.assertFalse(nested["annotations_included"])
        self.assertFalse(nested["analysis_partition_mutated"])
        self.assertFalse(nested["feature_manifest_mutated"])
        self.assertFalse(nested["final_holdout_accessed"])

        downstream = service._canonical_nested_response_lineage(
            {
                "contract_version": "eda-contract-test",
                "artifact_id": "eda-artifact-test",
                "artifact_hash": "eda-artifact-hash-test",
                "project_id": PROJECT_ID,
                "dataset_id": DATASET_ID,
                "dataset_version_id": VERSION_ID,
                "activation_revision": 1,
                "target": "bad_flag",
                "target_contract_id": "target-contract-test",
                "problem_type": "classification",
                "positive_value": 1,
                "negative_value": 0,
                "predictor_authorization_id": "predictor-auth-test",
                "analysis_partition_id": "partition-current",
                "analysis_partition_revision": 11,
                "analysis_partition_artifact_hash": "partition-artifact",
                "analysis_partition_assignment_hash": "partition-assignment",
                "special_value_review_id": "special-review",
                "special_value_review_revision": 2,
                "rows_used": 80,
                "population_rows": 100,
                "rows_excluded": 20,
                "exclusion_reasons": ["sealed_final_holdout_excluded"],
                "analysis_population_id": "development-population",
                "split_id": "partition-current",
                "bureau_semantic_identity": (
                    _bureau_semantic_request_identity(request_three)
                ),
            },
            analysis_source="eda.test.narrow_downstream",
        )
        self.assertEqual(
            downstream["bureau_metadata_binding_revision"],
            7,
        )
        self.assertEqual(
            downstream["bureau_metadata_crosswalk_revision"],
            3,
        )
        self.assertNotIn("annotations", downstream)
        self.assertFalse(downstream["final_holdout_accessed"])

    def test_http_guard_rejects_stale_metadata_before_service_calculation(self) -> None:
        app = FastAPI()
        app.include_router(eda_router.router, prefix="/api/eda")
        app.dependency_overrides[eda_router.require_user] = lambda: {
            "userId": "bureau-eda-user"
        }
        payload = _request().model_dump(mode="json")
        with patch.object(
            eda_router,
            "authorize_modeling_scope",
            return_value=PROJECT_ID,
        ), patch(
            "server.eda.bureau_semantic_contract._resolve_exact",
            return_value=_envelope(crosswalk_revision=4),
        ), patch.object(
            eda_router.eda_workspace_service,
            "section",
        ) as section:
            response = TestClient(
                app,
                raise_server_exceptions=False,
            ).post("/api/eda/workspace/overview", json=payload)

        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(
            response.json()["detail"]["code"],
            "bureau_semantic_annotation_stale",
        )
        section.assert_not_called()

    def test_saved_downstream_plan_cannot_cross_semantic_revision(self) -> None:
        current = _request()
        stale = _request(crosswalk_revision=4)
        contract = {
            "project_id": PROJECT_ID,
            "dataset_id": DATASET_ID,
            "dataset_version_id": VERSION_ID,
            "activation_revision": 1,
            "target_contract_id": "target-contract",
            "target": "bad_flag",
            "positive_value": 1,
            "negative_value": 0,
            "predictor_authorization_id": "predictor-auth",
            "analysis_partition_id": "partition-current",
            "analysis_partition_revision": 11,
            "special_value_review_id": "special-review",
            "special_value_review_revision": 2,
            "bureau_semantic_identity": _bureau_semantic_request_identity(
                current
            ),
        }
        plan_inputs = {
            **contract,
            "bureau_semantic_identity": None,
            **stale.model_dump(mode="json"),
        }
        plan_inputs.update(
            {
                "activation_revision": 1,
                "target_contract_id": "target-contract",
                "target": "bad_flag",
                "positive_value": 1,
                "negative_value": 0,
                "predictor_authorization_id": "predictor-auth",
                "analysis_partition_id": "partition-current",
                "analysis_partition_revision": 11,
                "special_value_review_id": "special-review",
                "special_value_review_revision": 2,
            }
        )
        with self.assertRaises(EDAAnalyticalContractError) as raised:
            EDAWorkspaceService._require_current_vif_plan_lineage(
                {"inputs": plan_inputs},
                contract,
            )
        self.assertEqual(
            raised.exception.code,
            "vif_resolution_plan_stale",
        )
        self.assertIn("bureau_semantic_identity", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
