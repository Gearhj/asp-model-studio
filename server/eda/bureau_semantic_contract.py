"""Authenticated Bureau metadata lineage guard for Data Acquisition -> EDA.

EDA never queries raw provider catalog rows and never treats browser metadata
as authority.  This boundary resolves the exact current dataset-version
annotation set using the authenticated principal, compares the complete
bounded identity, and fails before any analytical service can materialize a
development target.  A genuinely absent or unentitled optional annotation set
remains non-blocking only when the client explicitly reports ``unavailable``.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from fastapi import HTTPException

from .analytical_contract import EDAAnalyticalContractError


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_TO_SET_FIELD = {
    "bureau_semantic_annotation_set_id": "annotation_set_id",
    "bureau_semantic_annotation_set_checksum": "annotation_set_checksum",
    "bureau_metadata_schema_checksum": "schema_checksum",
    "bureau_metadata_binding_id": "binding_id",
    "bureau_metadata_binding_revision": "binding_revision",
    "bureau_metadata_binding_revision_checksum": "binding_revision_checksum",
    "bureau_metadata_crosswalk_id": "crosswalk_id",
    "bureau_metadata_crosswalk_revision": "crosswalk_revision",
    "bureau_metadata_crosswalk_revision_checksum": "crosswalk_revision_checksum",
    "bureau_metadata_catalog_version_id": "catalog_version_id",
    "bureau_metadata_catalog_checksum": "catalog_checksum",
}
_NONMUTATION_FIELDS = (
    "dataset_mutated",
    "target_contract_mutated",
    "treatment_mutated",
    "predictor_authorization_mutated",
    "analysis_partition_mutated",
    "feature_manifest_mutated",
)
_PROVIDER_AUTHORITATIVE_MAPPING_STATES = {
    "exact_verified",
    "approved_alias",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _same(left: object, right: object) -> bool:
    if isinstance(left, int) or isinstance(right, int):
        return str(left) == str(right)
    return _text(left) == _text(right)


def _contract_error(
    message: str,
    *,
    code: str = "bureau_semantic_annotation_stale",
) -> EDAAnalyticalContractError:
    return EDAAnalyticalContractError(
        message,
        code=code,
        recovery=(
            "Reload Data Acquisition and reopen EDA from the current exact "
            "dataset-version metadata handoff."
        ),
        stale_artifacts=["bureau_semantic_annotations", "predictor_eda"],
    )


def _resolve_exact(
    request: Any,
    user: Mapping[str, Any],
) -> Mapping[str, Any]:
    # Lazy import keeps the EDA analytical module independent from catalog
    # startup and avoids loading restricted provider content for ordinary
    # datasets that do not assert a Bureau metadata state.
    from ..bureau_metadata.crosswalk_router import (
        resolve_exact_semantic_handoff_for_user,
    )

    return resolve_exact_semantic_handoff_for_user(
        project_id=_text(request.project_id),
        dataset_id=_text(request.dataset_id),
        dataset_version_id=_text(request.dataset_version_id),
        user=user,
    )


def validate_bureau_semantic_handoff(
    request: Any,
    user: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate an optional compare-only semantic identity before EDA work.

    Returns a bounded audit projection.  It contains counts and exact
    identifiers only; catalog definitions and annotation rows never cross into
    the analytical service.
    """

    state = getattr(request, "bureau_semantic_annotation_state", None)
    if state is None:
        return {}
    try:
        envelope = _resolve_exact(request, user)
    except HTTPException as exc:
        if state == "unavailable" and int(exc.status_code) in {403, 404}:
            return {
                "state": "unavailable",
                "authoritative": False,
                "server_resolution": (
                    "not_entitled" if int(exc.status_code) == 403 else "not_bound"
                ),
                "annotations_included": False,
                "provider_catalog_rows_included": False,
                "unresolved_mappings_authoritative": False,
                "final_holdout_accessed": False,
            }
        raise _contract_error(
            "The asserted Bureau semantic metadata is unavailable or no longer current.",
            code=(
                "bureau_semantic_annotation_access_unavailable"
                if int(exc.status_code) == 403
                else "bureau_semantic_annotation_stale"
            ),
        ) from exc

    if state == "unavailable":
        raise _contract_error(
            "The request reported Bureau semantic metadata as unavailable, but an exact current entitled annotation set exists.",
            code="bureau_semantic_annotation_false_unavailable",
        )
    if not isinstance(envelope, Mapping) or envelope.get("ok") is not True:
        raise _contract_error(
            "The exact Bureau semantic annotation authority returned an invalid envelope."
        )
    annotation_set = envelope.get("annotation_set")
    annotations = envelope.get("annotations")
    if not isinstance(annotation_set, Mapping) or not isinstance(
        annotations, list
    ):
        raise _contract_error(
            "The exact Bureau semantic annotation authority is incomplete."
        )
    if len(annotations) > 250:
        raise _contract_error(
            "The exact Bureau semantic annotation authority exceeded its bounded inventory."
        )
    expected_scope = {
        "project_id": request.project_id,
        "dataset_id": request.dataset_id,
        "dataset_version_id": request.dataset_version_id,
    }
    mismatches = [
        field
        for field, expected in expected_scope.items()
        if not _same(annotation_set.get(field), expected)
    ]
    mismatches.extend(
        request_field
        for request_field, set_field in _REQUEST_TO_SET_FIELD.items()
        if not _same(
            annotation_set.get(set_field),
            getattr(request, request_field, None),
        )
    )
    if mismatches:
        raise _contract_error(
            "The EDA Bureau semantic assertion does not match the exact current backend annotation set: "
            + ", ".join(sorted(set(mismatches)))
            + "."
        )
    checksum_fields = (
        "annotation_set_checksum",
        "schema_checksum",
        "binding_revision_checksum",
        "crosswalk_revision_checksum",
        "catalog_checksum",
    )
    if any(
        not _SHA256.fullmatch(_text(annotation_set.get(field)).casefold())
        for field in checksum_fields
    ):
        raise _contract_error(
            "The exact Bureau semantic annotation authority contains an invalid checksum."
        )
    if any(annotation_set.get(field) is not False for field in _NONMUTATION_FIELDS):
        raise _contract_error(
            "The exact Bureau semantic annotation authority did not prove non-mutation of governed workflow state."
        )

    authoritative_count = 0
    non_authoritative_count = 0
    for raw in annotations:
        if not isinstance(raw, Mapping):
            raise _contract_error(
                "The bounded Bureau semantic annotation inventory is invalid."
            )
        mapping_state = _text(raw.get("mapping_state"))
        provider_authoritative = raw.get("provider_authoritative") is True
        if (
            mapping_state not in _PROVIDER_AUTHORITATIVE_MAPPING_STATES
            and provider_authoritative
        ):
            raise _contract_error(
                "An unresolved or review-required catalog mapping was incorrectly marked provider-authoritative."
            )
        if raw.get("final_holdout_accessed") is True:
            raise _contract_error(
                "The Bureau semantic handoff reported prohibited final-holdout access."
            )
        if provider_authoritative:
            authoritative_count += 1
        else:
            non_authoritative_count += 1

    return {
        "state": "available",
        "authoritative": True,
        "annotation_set_id": annotation_set.get("annotation_set_id"),
        "annotation_set_checksum": annotation_set.get(
            "annotation_set_checksum"
        ),
        "binding_revision": annotation_set.get("binding_revision"),
        "crosswalk_revision": annotation_set.get("crosswalk_revision"),
        "authoritative_annotation_count": authoritative_count,
        "non_authoritative_annotation_count": non_authoritative_count,
        "annotations_included": False,
        "provider_catalog_rows_included": False,
        "unresolved_mappings_authoritative": False,
        "final_holdout_accessed": False,
    }


__all__ = ["validate_bureau_semantic_handoff"]
