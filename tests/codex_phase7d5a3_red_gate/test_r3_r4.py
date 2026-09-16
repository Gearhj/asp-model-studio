"""Codex Phase 7D.5A.3 red gate for the unresolved Repair 3/4 defects.

The runtime seam is established before any application import.  Every fixture is
synthetic and lives under pytest's externally supplied temporary root.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


# Fail-safe import ordering: production modules must never resolve the shared
# development runtime while this red gate is collected or executed.
_configured_runtime = os.environ.get("ASP_MODEL_STUDIO_RUNTIME_ROOT")
if _configured_runtime:
    _isolated_runtime = Path(_configured_runtime).resolve()
else:
    _isolated_runtime = Path(tempfile.mkdtemp(prefix="codex-7d5a3-r3-r4-")) / "runtime"
os.environ["ASP_MODEL_STUDIO_RUNTIME_ROOT"] = str(_isolated_runtime)
os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import json  # noqa: E402  (the runtime seam intentionally precedes imports)
import uuid  # noqa: E402
from collections.abc import Callable  # noqa: E402
from typing import Any  # noqa: E402

import pytest  # noqa: E402

from server.sports_cockpit import gen3_authority as A  # noqa: E402
from server.sports_cockpit import router as COCKPIT_ROUTER  # noqa: E402
from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes  # noqa: E402
from server.sports_modeling import silver_publish as SP  # noqa: E402
from tests import _silver_fixture as F  # noqa: E402
from tests._hermetic_gen3 import build_hermetic_gen3  # noqa: E402


JsonMutation = Callable[[dict[str, Any]], None]
PublicationMutation = Callable[[dict[str, Any]], str]


def _publish(tmp_path: Path) -> dict[str, Any]:
    return F.publish_silver_hermetic(tmp_path)


def _set(key: str, value: Any) -> JsonMutation:
    def mutate(payload: dict[str, Any]) -> None:
        payload[key] = value

    return mutate


def _add_marker(payload: dict[str, Any]) -> None:
    payload["codexRedGateMutation"] = True


def _rewrite_json_child(
    publication: dict[str, Any], child_name: str, mutate: JsonMutation
) -> None:
    object_dir = Path(publication["object_dir"])
    child_path = object_dir / child_name
    child = json.loads(child_path.read_bytes())
    mutate(child)
    child_path.write_bytes(canonical_json_bytes(child))


def _finish_coordinated_readdress(
    publication: dict[str, Any],
    changed_children: tuple[str, ...] = (),
    mutate_manifest: JsonMutation | None = None,
) -> str:
    """Rebuild the outer inventory/address after coordinated child changes."""
    object_dir = Path(publication["object_dir"])

    manifest_path = object_dir / "publication-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for child_name in changed_children:
        child_bytes = (object_dir / child_name).read_bytes()
        manifest["children"][child_name]["sha256"] = sha256_bytes(child_bytes)
        manifest["children"][child_name]["bytes"] = len(child_bytes)
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    manifest_body = {key: value for key, value in manifest.items() if key != "manifestSha256"}
    new_manifest_sha = sha256_bytes(canonical_json_bytes(manifest_body))
    manifest["manifestSha256"] = new_manifest_sha
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    object_dir.rename(object_dir.parent / new_manifest_sha)
    return new_manifest_sha


def _one_child_mutation(child_name: str, mutate: JsonMutation) -> PublicationMutation:
    def apply(publication: dict[str, Any]) -> str:
        _rewrite_json_child(publication, child_name, mutate)
        return _finish_coordinated_readdress(publication, (child_name,))

    return apply


def _mutate_feature_set_family_and_output(publication: dict[str, Any]) -> str:
    forged_output_sha = "f" * 64

    def mutate_feature_set(feature_set: dict[str, Any]) -> None:
        feature_set["payload"]["orderedOptionalFamilyIds"] = ["FORGED_FAMILY"]
        feature_set["payload"]["datasetContentSha256"] = forged_output_sha

    _rewrite_json_child(publication, "feature-set-v2-contract.json", mutate_feature_set)

    receipt_path = Path(publication["object_dir"]) / "transformation-receipt.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["featureSetBindsOutputLogicalSha256"] = forged_output_sha
    receipt_body = {key: value for key, value in receipt.items() if key != "receiptSha256"}
    receipt["receiptSha256"] = sha256_bytes(canonical_json_bytes(receipt_body))
    receipt_path.write_bytes(canonical_json_bytes(receipt))

    return _finish_coordinated_readdress(
        publication,
        ("feature-set-v2-contract.json", "transformation-receipt.json"),
        lambda manifest: manifest.update(
            {"transformReceiptSha256": receipt["receiptSha256"]}
        ),
    )


def _mutate_publication_manifest_contract(publication: dict[str, Any]) -> str:
    return _finish_coordinated_readdress(
        publication,
        mutate_manifest=_set(
            "manifestContract", "FORGED_SILVER_PUBLICATION_MANIFEST_CONTRACT"
        ),
    )


def test_r3_baseline_is_an_exact_verified_non_self_referential_14_child_object(tmp_path: Path) -> None:
    publication = _publish(tmp_path)
    object_dir = Path(publication["object_dir"])
    manifest = json.loads((object_dir / "publication-manifest.json").read_bytes())

    assert len(SP.REQUIRED_SILVER_CHILDREN) == 14
    assert {path.name for path in object_dir.iterdir()} == set(SP.REQUIRED_SILVER_CHILDREN)
    assert set(manifest["children"]) == set(SP.REQUIRED_SILVER_CHILDREN) - {"publication-manifest.json"}
    assert "publication-manifest.json" not in manifest["children"]
    SP.verify_silver(publication["silver_root"], publication["manifest_sha"])


_R3_COORDINATED_MUTATIONS: tuple[tuple[str, PublicationMutation], ...] = (
    (
        "feature-family-body-stale-self-sha",
        _one_child_mutation(
            "feature-family-contract.json", _set("id", "FORGED_FAMILY_ID")
        ),
    ),
    (
        "semantic-body-stale-self-sha",
        _one_child_mutation("prior-pa-semantic-contract.json", _add_marker),
    ),
    ("temporal-contract-readdressed", _one_child_mutation("temporal-contract.json", _add_marker)),
    ("population-contract-readdressed", _one_child_mutation("population-contract.json", _add_marker)),
    (
        "knowledge-time-contract-readdressed",
        _one_child_mutation("knowledge-time-contract.json", _add_marker),
    ),
    (
        "source-manifest-dataset-relationship",
        _one_child_mutation(
            "source-publication-manifest.json", _set("datasetVersionId", "FORGED_SOURCE")
        ),
    ),
    (
        "source-manifest-logical-relationship",
        _one_child_mutation(
            "source-publication-manifest.json", _set("logicalSha256", "1" * 64)
        ),
    ),
    (
        "source-manifest-row-count-relationship",
        _one_child_mutation(
            "source-publication-manifest.json", _set("rowCount", 999_999)
        ),
    ),
    (
        "source-manifest-season-relationship",
        _one_child_mutation(
            "source-publication-manifest.json", _set("seasons", [2025])
        ),
    ),
    (
        "value-digest-relational-metadata",
        _one_child_mutation(
            "value-digest.json", _set("featureIds", ["FORGED_FEATURE"])
        ),
    ),
    (
        "semantic-to-transformation-receipt",
        _one_child_mutation(
            "prior-pa-semantic-contract.json",
            lambda semantic: semantic["payload"].update(
                {"featureFamilyId": "FORGED_SEMANTIC_FAMILY"}
            ),
        ),
    ),
    (
        "family-to-semantic-members",
        _one_child_mutation(
            "feature-family-contract.json",
            lambda family: family["payload"].update(
                {"orderedFeatureIds": ["FORGED_MEMBER_A", "FORGED_MEMBER_B"]}
            ),
        ),
    ),
    ("feature-set-to-family-and-output", _mutate_feature_set_family_and_output),
    ("publication-manifest-contract-identity", _mutate_publication_manifest_contract),
)


@pytest.mark.parametrize(
    ("case_id", "mutate_publication"),
    _R3_COORDINATED_MUTATIONS,
    ids=[case[0] for case in _R3_COORDINATED_MUTATIONS],
)
def test_coordinated_readdressed_contract_tampering_is_rejected(
    tmp_path: Path, case_id: str, mutate_publication: PublicationMutation
) -> None:
    publication = _publish(tmp_path)
    assert case_id
    readdressed_manifest_sha = mutate_publication(publication)

    with pytest.raises(SP.SilverPublishError, match=".+"):
        SP.verify_silver(publication["silver_root"], readdressed_manifest_sha)


@pytest.fixture(scope="module")
def quarantined_lifecycle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Create valid evidence, then quarantine its dataset in the canonical registry."""
    root = tmp_path_factory.mktemp("r4-quarantined-lifecycle")
    monkeypatch = pytest.MonkeyPatch()
    build_hermetic_gen3(root, monkeypatch)

    project_id = "codex-r4-" + uuid.uuid4().hex[:10]
    entry = next(item for item in A.catalog() if item["generation"] == "GEN3")
    dataset_id = entry["datasetVersionId"]
    binding = A.create_binding(actor="codex-red@asp", project_id=project_id, dataset_version_id=dataset_id)
    authority = A.issue_run_authority(
        actor="codex-red@asp",
        project_id=project_id,
        binding_id=binding["bindingId"],
        model_family="governed_logistic",
        hyperparameters={},
        feature_set="base",
    )
    execution = A.execute(
        actor="codex-red@asp", project_id=project_id, run_authority_id=authority["runAuthorityId"]
    )
    run_id = execution["experimentRunId"]
    A.activate_candidate(actor="codex-red@asp", project_id=project_id, run_id=run_id)
    pending_authority = A.issue_run_authority(
        actor="codex-red@asp",
        project_id=project_id,
        binding_id=binding["bindingId"],
        model_family="governed_logistic",
        hyperparameters={},
        seed=20260820,
        feature_set="base",
    )

    registry = json.loads(A.ASP_REGISTRY.read_bytes())
    canonical_entry = next(item for item in registry["datasets"] if item["datasetVersionId"] == dataset_id)
    canonical_entry.update(
        {
            "status": "QUARANTINED",
            "quarantine": "QUARANTINED",
            "selectable": False,
            "modelEligible": False,
            "approvedForTraining": False,
        }
    )
    A.ASP_REGISTRY.write_bytes(canonical_json_bytes(registry))

    yield {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "binding": binding,
        "run_id": run_id,
        "pending_authority": pending_authority,
    }
    monkeypatch.undo()


def test_r4_baseline_eligible_entry_remains_allowed() -> None:
    A.assert_canonical_eligibility(
        {
            "datasetVersionId": "ordinary-research",
            "status": "RESEARCH_READY",
            "generation": "GEN3",
            "selectable": True,
            "modelEligible": True,
            "approvedForTraining": True,
        }
    )


def test_not_approved_for_training_is_never_selectable() -> None:
    entry = {
        "datasetVersionId": "ordinary-not-approved",
        "status": "RESEARCH_READY",
        "generation": "GEN3",
        "selectable": True,
        "modelEligible": True,
        "approvedForTraining": False,
    }
    with pytest.raises(A.AuthorityError, match="approved|eligible"):
        A.assert_canonical_eligibility(entry)


def test_r4_listing_discloses_quarantine_only_as_nonselectable(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    entry = next(
        item for item in A.catalog() if item["datasetVersionId"] == quarantined_lifecycle["dataset_id"]
    )
    assert entry["status"] == "QUARANTINED"
    assert entry["selectable"] is False
    with pytest.raises(A.AuthorityError):
        A.assert_canonical_eligibility(entry)


def test_r4_binding_rejects_quarantined_dataset(quarantined_lifecycle: dict[str, Any]) -> None:
    with pytest.raises(A.AuthorityError):
        A.create_binding(
            actor="codex-red@asp",
            project_id=quarantined_lifecycle["project_id"] + "-new",
            dataset_version_id=quarantined_lifecycle["dataset_id"],
        )


def test_r4_run_authority_rejects_quarantined_dataset(quarantined_lifecycle: dict[str, Any]) -> None:
    with pytest.raises(A.AuthorityError):
        A.issue_run_authority(
            actor="codex-red@asp",
            project_id=quarantined_lifecycle["project_id"],
            binding_id=quarantined_lifecycle["binding"]["bindingId"],
            model_family="governed_logistic",
        )


def test_r4_execution_rejects_preissued_authority_after_quarantine(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A.execute(
            actor="codex-red@asp",
            project_id=quarantined_lifecycle["project_id"],
            run_authority_id=quarantined_lifecycle["pending_authority"]["runAuthorityId"],
        )


def test_post_quarantine_model_reload_is_rejected(quarantined_lifecycle: dict[str, Any]) -> None:
    with pytest.raises(A.AuthorityError):
        A.load_fitted_estimator_v2(
            project_id=quarantined_lifecycle["project_id"], run_id=quarantined_lifecycle["run_id"]
        )


def test_post_quarantine_v2_recompute_is_rejected(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A.recompute_validation_logloss_v2(
            project_id=quarantined_lifecycle["project_id"], run_id=quarantined_lifecycle["run_id"]
        )


def test_post_quarantine_v1_recompute_is_rejected(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A.recompute_validation_logloss(
            project_id=quarantined_lifecycle["project_id"], run_id=quarantined_lifecycle["run_id"]
        )


def test_direct_run_id_cannot_bypass_quarantine(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A.verify_model_run_receipt(
            project_id=quarantined_lifecycle["project_id"],
            run_id=quarantined_lifecycle["run_id"],
        )


def test_direct_artifact_reference_cannot_bypass_quarantine(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        verified = A.verify_model_run_receipt(
            project_id=quarantined_lifecycle["project_id"],
            run_id=quarantined_lifecycle["run_id"],
        )
        A._v2_child_bytes(verified["bundleDir"], verified["manifest"], "model.artifact")


def test_r4_activation_rejects_quarantined_parent(quarantined_lifecycle: dict[str, Any]) -> None:
    with pytest.raises(A.AuthorityError):
        A.activate_candidate(
            actor="codex-red@asp",
            project_id=quarantined_lifecycle["project_id"],
            run_id=quarantined_lifecycle["run_id"],
        )


def test_r4_active_model_read_rejects_quarantined_parent(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A.get_active_candidate(project_id=quarantined_lifecycle["project_id"])


def test_r4_active_evaluation_rejects_quarantined_parent(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A.active_candidate_evaluation(project_id=quarantined_lifecycle["project_id"])


def test_r4_comparison_initiation_rejects_quarantined_parent(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A.run_feature_family_ablation(
            actor="codex-red@asp",
            project_id=quarantined_lifecycle["project_id"],
            binding_id=quarantined_lifecycle["binding"]["bindingId"],
            challenger_feature_set="advanced",
            bootstrap_iterations=100,
        )


def test_r4_comparison_arm_read_rejects_quarantined_parent(
    quarantined_lifecycle: dict[str, Any],
) -> None:
    with pytest.raises(A.AuthorityError):
        A._v2_validation_evidence(
            quarantined_lifecycle["project_id"], quarantined_lifecycle["run_id"]
        )


def test_r4_export_boundary_is_absent() -> None:
    assert not any(
        "export" in name.lower() and callable(getattr(A, name))
        for name in dir(A)
    )
    assert not any("export" in route.path.lower() for route in COCKPIT_ROUTER.router.routes)
