"""Interactive resolver for immutable Wave 2 prior fit bundles."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from . import stage3_player_prior_authority_v2 as prior_v2
from .stage3_player_prior_artifact_store_v2 import (
    DEFAULT_AUTHORITY_ROOT,
    PriorArtifactStoreV2Error,
    load_artifact,
    load_current_bundle,
)


def resolve_project_fit_bundle(
    *,
    project_authority: Any,
    v1_authority_manifest: Mapping[str, Any],
    sufficient_statistics_authority: Mapping[str, Any] | None,
    treatment_specification_key: str,
    treatment_source_sha256: str,
    compiler_version: str,
    compiler_sha256: str,
    root: Path = DEFAULT_AUTHORITY_ROOT,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Verify the current bundle against lightweight live authorities.

    Expensive companion/Gold key reconciliation and OOT footer inspection are
    sealed into the stored definition by the fitting command.  Interactive
    requests still authenticate the registration and every object through the
    Wave 1 resolver before this function is called.
    """

    public = prior_v2._public_authority(project_authority)
    try:
        bundle = load_current_bundle(str(public.get("projectId") or ""), root=root)
    except PriorArtifactStoreV2Error as exc:
        raise prior_v2.PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    if bundle is None:
        return None
    reference = bundle.get("definition") or {}
    try:
        definition = load_artifact(
            str(reference.get("artifactSha256") or ""), root=root
        )
    except PriorArtifactStoreV2Error as exc:
        raise prior_v2.PlayerPriorAuthorityV2Error(exc.code, str(exc)) from exc
    definition = prior_v2._validate_definition(definition)
    companion = sufficient_statistics_authority or {}
    expected = {
        "projectAuthority": public,
        "goldManifestSha256": public.get("goldManifestSha"),
        "v1AuthorityId": v1_authority_manifest.get("authorityId"),
        "v1AuthorityChecksum": v1_authority_manifest.get("authorityChecksum"),
        "companionManifestSha256": companion.get("manifestSha256"),
        "companionBindingAuthorityId": companion.get("authorityId"),
        "treatmentSpecificationKey": treatment_specification_key,
        "treatmentSourceSha256": treatment_source_sha256,
        "compilerVersion": compiler_version,
        "compilerSha256": compiler_sha256,
    }
    stored = {
        "projectAuthority": definition.get("projectAuthority"),
        "goldManifestSha256": (definition.get("gold") or {}).get("manifestSha256"),
        "v1AuthorityId": (definition.get("wave1PriorAuthority") or {}).get("authorityId"),
        "v1AuthorityChecksum": (definition.get("wave1PriorAuthority") or {}).get("authorityChecksum"),
        "companionManifestSha256": (definition.get("companionAuthority") or {}).get("manifestSha256"),
        "companionBindingAuthorityId": (definition.get("companionAuthority") or {}).get("bindingAuthorityId"),
        "treatmentSpecificationKey": (definition.get("treatmentSpecificationSource") or {}).get("key"),
        "treatmentSourceSha256": (definition.get("treatmentSpecificationSource") or {}).get("sourceContentSha256"),
        "compilerVersion": (definition.get("treatmentSpecificationSource") or {}).get("compilerVersion"),
        "compilerSha256": (definition.get("treatmentSpecificationSource") or {}).get("compilerSha256"),
    }
    if not sufficient_statistics_authority:
        raise prior_v2.PlayerPriorAuthorityV2Error(
            "PRIOR_V2_COMPANION_NO_LONGER_VALID",
            "A Wave 2 pointer exists but its companion registration no longer authenticates.",
        )
    if stored != expected:
        raise prior_v2.PlayerPriorAuthorityV2Error(
            "PRIOR_V2_LIVE_AUTHORITY_MISMATCH",
            "The current Wave 2 fit bundle is stale for the live project/compiler authority.",
        )
    verified = prior_v2._validate_bundle(
        bundle, expected_definition=definition, root=root
    )
    return verified, definition


__all__ = ["resolve_project_fit_bundle"]
