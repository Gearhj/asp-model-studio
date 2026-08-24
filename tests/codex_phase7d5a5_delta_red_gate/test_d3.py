"""D3 delta-red tests for independent outer Silver relationship authority."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling import silver_publish as SP
from tests import _silver_fixture as F


SIG = "D3_OUTER_RELATIONAL_RECONSTRUCTION:"
JsonMutation = Callable[[dict[str, Any]], None]


def _valid_publication(root: Path) -> dict[str, Any]:
    return F.publish_silver_hermetic(root / "valid")


def _copy_candidate(publication: dict[str, Any], root: Path, label: str) -> dict[str, Any]:
    silver_root = root / f"candidate-{label}"
    shutil.copytree(Path(publication["silver_root"]), silver_root)
    manifest_sha = publication["manifest_sha"]
    return {
        **publication,
        "silver_root": silver_root,
        "object_dir": silver_root / "objects" / "sha256" / manifest_sha,
        "manifest_sha": manifest_sha,
    }


def _readdress(
    candidate: dict[str, Any],
    *,
    changed_children: tuple[str, ...] = (),
    mutate_manifest: JsonMutation | None = None,
) -> str:
    object_dir = Path(candidate["object_dir"])
    manifest_path = object_dir / "publication-manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for name in changed_children:
        child_bytes = (object_dir / name).read_bytes()
        manifest["children"][name]["sha256"] = sha256_bytes(child_bytes)
        manifest["children"][name]["bytes"] = len(child_bytes)
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    body = {key: value for key, value in manifest.items() if key != "manifestSha256"}
    new_sha = sha256_bytes(canonical_json_bytes(body))
    manifest["manifestSha256"] = new_sha
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    object_dir.rename(object_dir.parent / new_sha)
    candidate["object_dir"] = object_dir.parent / new_sha
    candidate["manifest_sha"] = new_sha
    return new_sha


def _expect_rejected(candidate: dict[str, Any], detail: str) -> None:
    try:
        SP.verify_silver(candidate["silver_root"], candidate["manifest_sha"])
    except SP.SilverPublishError:
        return
    pytest.fail(f"{SIG} verifier accepted {detail}")


def _mutate_outer(candidate: dict[str, Any], **changes: Any) -> None:
    _readdress(candidate, mutate_manifest=lambda manifest: manifest.update(changes))


def _coordinate_new_parent(candidate: dict[str, Any], forged_parent: str) -> None:
    """Re-address every copied child needed to make a forged parent internally coherent."""
    object_dir = Path(candidate["object_dir"])

    source_receipt_path = object_dir / "source-object-receipt.json"
    source_receipt = json.loads(source_receipt_path.read_bytes())
    source_receipt["datasetVersionId"] = forged_parent
    source_receipt_body = {
        key: value for key, value in source_receipt.items() if key != "receiptSha256"
    }
    source_receipt["receiptSha256"] = sha256_bytes(canonical_json_bytes(source_receipt_body))
    source_receipt_path.write_bytes(canonical_json_bytes(source_receipt))

    source_manifest_path = object_dir / "source-publication-manifest.json"
    source_manifest = json.loads(source_manifest_path.read_bytes())
    source_manifest["datasetVersionId"] = forged_parent
    source_manifest["receiptSha256"] = source_receipt["receiptSha256"]
    source_receipt_bytes = source_receipt_path.read_bytes()
    source_manifest["children"]["source-receipt.json"]["sha256"] = sha256_bytes(
        source_receipt_bytes
    )
    source_manifest["children"]["source-receipt.json"]["bytes"] = len(source_receipt_bytes)
    source_manifest_body = {
        key: value for key, value in source_manifest.items() if key != "manifestSha256"
    }
    source_manifest["manifestSha256"] = sha256_bytes(canonical_json_bytes(source_manifest_body))
    source_manifest_path.write_bytes(canonical_json_bytes(source_manifest))

    tcr = json.loads((object_dir / "transform-code-receipt.json").read_bytes())
    transform_path = object_dir / "transformation-receipt.json"
    transform = json.loads(transform_path.read_bytes())
    contracts = SP.silver_semantic_contracts(
        source_object_id=forged_parent,
        source_receipt_sha=source_receipt["receiptSha256"],
        transform_code_sha=tcr["sha256"],
        has_game_sequence=False,
    )
    family = SP.silver_family_contract(contracts)
    base_ids = list(transform["orderedOutputFeatures"])[: -len(SP._ADV)]
    feature_set = SP.silver_feature_set_v2(
        dataset_version_id=f"silver:{forged_parent}",
        dataset_content_sha=transform["outputLogicalSha256"],
        base_feature_ids=base_ids,
        contracts={**SP.FS.all_feature_semantic_contracts(), **contracts},
    )
    for feature, child_name in (
        (SP.PRIOR_PA_COUNT, "prior-pa-semantic-contract.json"),
        (SP.LOG1P_PRIOR_PA_COUNT, "log1p-prior-pa-semantic-contract.json"),
    ):
        (object_dir / child_name).write_bytes(canonical_json_bytes(contracts[feature]))
    (object_dir / "feature-family-contract.json").write_bytes(canonical_json_bytes(family))
    (object_dir / "feature-set-v2-contract.json").write_bytes(canonical_json_bytes(feature_set))

    transform.update(
        {
            "sourceDatasetVersionId": forged_parent,
            "sourceReceiptSha256": source_receipt["receiptSha256"],
            "sourceManifestSha256": source_manifest["manifestSha256"],
            "semanticContractShas": {name: contracts[name]["sha256"] for name in SP._ADV},
            "featureFamilySha256": family["sha256"],
            "featureFamilyId": family["id"],
            "featureSetV2Sha256": feature_set["sha256"],
            "featureSetV2Id": feature_set["id"],
        }
    )
    transform_body = {key: value for key, value in transform.items() if key != "receiptSha256"}
    transform["receiptSha256"] = sha256_bytes(canonical_json_bytes(transform_body))
    transform_path.write_bytes(canonical_json_bytes(transform))

    changed = (
        "source-object-receipt.json",
        "source-publication-manifest.json",
        "prior-pa-semantic-contract.json",
        "log1p-prior-pa-semantic-contract.json",
        "feature-family-contract.json",
        "feature-set-v2-contract.json",
        "transformation-receipt.json",
    )
    _readdress(
        candidate,
        changed_children=changed,
        mutate_manifest=lambda manifest: manifest.update(
            {
                "sourceDatasetVersionId": forged_parent,
                "transformReceiptSha256": transform["receiptSha256"],
            }
        ),
    )


def test_readdressed_outer_seasons_cannot_redefine_canonical_authority(tmp_path: Path) -> None:
    candidate = _copy_candidate(_valid_publication(tmp_path), tmp_path, "seasons")
    _mutate_outer(candidate, seasons=[1901])
    _expect_rejected(candidate, "a re-addressed outer season set [1901]")


def test_readdressed_outer_source_dataset_id_cannot_redefine_canonical_authority(
    tmp_path: Path,
) -> None:
    candidate = _copy_candidate(_valid_publication(tmp_path), tmp_path, "source-id")
    _mutate_outer(candidate, sourceDatasetVersionId="mlb-history-v99")
    _expect_rejected(candidate, "a re-addressed outer sourceDatasetVersionId")


def test_expected_outer_relationships_do_not_come_from_candidate_bundle(tmp_path: Path) -> None:
    candidate = _copy_candidate(_valid_publication(tmp_path), tmp_path, "row-count")
    _mutate_outer(candidate, rowCount=999_999)
    _expect_rejected(candidate, "a candidate-supplied outer row count")


def test_canonical_source_is_reloaded_independently_during_verification(tmp_path: Path) -> None:
    publication = _valid_publication(tmp_path)
    registry_path = Path(publication["source_root"]) / "silver-source-registry.json"
    registry = json.loads(registry_path.read_bytes())
    registry["datasets"][F.SRC_ID]["manifestSha256"] = "0" * 64
    registry_path.write_bytes(canonical_json_bytes(registry))
    try:
        SP.verify_silver(publication["silver_root"], publication["manifest_sha"])
    except SP.SilverPublishError:
        return
    pytest.fail(f"{SIG} verifier accepted a bundle after canonical source authority diverged")


def test_outer_manifest_and_transformation_receipt_cannot_coordinate_a_new_parent(
    tmp_path: Path,
) -> None:
    candidate = _copy_candidate(_valid_publication(tmp_path), tmp_path, "coordinated-parent")
    _coordinate_new_parent(candidate, "mlb-history-v99")
    _expect_rejected(candidate, "a coordinated new scientific parent")
