"""Immutable Phase 7D.5A.3 red acceptance nodes for audit findings R1 and R2.

These tests deliberately exercise the production Silver transform/publisher at the
5ec6c9b baseline.  They use synthetic rows and pytest-owned disposable directories
only.  They are expected to FAIL on that baseline because production currently
accepts the unsafe operation asserted inside each ``pytest.raises`` block or emits
relationships that fail the explicit equality assertions.

This file is acceptance authority, not an alternative implementation.  In
particular, the small re-addressing helper only creates adversarial fixture bytes;
all acceptance decisions are made by the real production resolver/verifier.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

# Establish the mutable-root seam BEFORE importing production modules.  The gate
# runner supplies an explicit external root; the fallback remains outside the repo
# for focused local collection and never resolves to the shared .runtime.
_REPO = Path(__file__).resolve().parents[2]
_RUNTIME = Path(
    os.environ.get(
        "ASP_MODEL_STUDIO_RUNTIME_ROOT",
        str(Path(tempfile.gettempdir()) / f"asp-phase7d5a3-r1-r2-{os.getpid()}"),
    )
).resolve()
if _RUNTIME == _REPO or _REPO in _RUNTIME.parents:
    raise RuntimeError("R1/R2 red gate requires an external disposable runtime root")
if _RUNTIME == (_REPO / ".runtime").resolve() or (_REPO / ".runtime").resolve() in _RUNTIME.parents:
    raise RuntimeError("R1/R2 red gate refuses the shared repository .runtime")
os.environ["ASP_MODEL_STUDIO_RUNTIME_ROOT"] = str(_RUNTIME)
os.environ.setdefault("ASP_MODEL_EXCHANGE_ROOT", str(_RUNTIME / "model-exchange-disabled"))
os.environ.setdefault("TEMP", str(_RUNTIME / "tmp"))
os.environ.setdefault("TMP", str(_RUNTIME / "tmp"))

import pyarrow.parquet as pq
import pytest

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from server.sports_modeling import silver_publish as SP
from server.sports_modeling import silver_transform as ST
from server.sports_modeling.feature_contract import FEATURE_NAMES


_SOURCE_ID = "codex-r1-r2-synthetic-source-v1"
_REJECTION_ERRORS = (SP.SourceAuthorityError, SP.SilverPublishError, ST.SilverTransformError)


def _row(season: int, at_bat: int, pa_id: str, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "plate_appearance_id": pa_id,
        "game_id": f"game-{season}",
        "game_date": f"{season}-04-01",
        "at_bat_number": at_bat,
        "batter_canonical_player_uuid": "batter-1",
        "season": season,
    }
    for index, feature in enumerate(FEATURE_NAMES):
        row[feature] = float((at_bat + index) % 7) / 10.0
    row.update(extra)
    return row


def _rows(season: int = 2023, **first_row_extra: Any) -> list[dict[str, Any]]:
    return [
        _row(season, 1, f"pa-{season}-1", **first_row_extra),
        _row(season, 2, f"pa-{season}-2"),
    ]


def _publish_source(
    root: Path,
    rows: list[dict[str, Any]],
    *,
    dataset_id: str = _SOURCE_ID,
    season_of_row: Callable[[dict[str, Any]], int] | None = None,
) -> dict[str, Any]:
    callback = season_of_row or (lambda row: row["season"])
    return SP.publish_source_object(
        source_root=root,
        rows=rows,
        dataset_version_id=dataset_id,
        season_of_row=callback,
    )


def _publish_silver(
    base: Path,
    rows: list[dict[str, Any]],
    *,
    dataset_id: str = _SOURCE_ID,
    source_season_of_row: Callable[[dict[str, Any]], int] | None = None,
    silver_season_of_row: Callable[[dict[str, Any]], int] | None = None,
    authorized_seasons: list[int] | None = None,
) -> dict[str, Any]:
    source_root = base / "source"
    silver_root = base / "silver"
    _publish_source(
        source_root,
        rows,
        dataset_id=dataset_id,
        season_of_row=source_season_of_row,
    )
    callback = silver_season_of_row or (lambda row: row["season"])
    entry = SP.publish_silver(
        silver_root=silver_root,
        source_root=source_root,
        source_dataset_version_id=dataset_id,
        base_feature_ids=list(FEATURE_NAMES),
        season_of_row=callback,
        authorized_seasons=authorized_seasons,
    )
    verified = SP.verify_silver(silver_root, entry["manifestSha256"])
    return {
        "entry": entry,
        "verified": verified,
        "source_root": source_root,
        "silver_root": silver_root,
        "object_dir": Path(verified["objectDir"]),
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> bytes:
    encoded = canonical_json_bytes(value)
    path.write_bytes(encoded)
    return encoded


def _source_parts(source_root: Path, dataset_id: str = _SOURCE_ID) -> dict[str, Any]:
    registry_path = source_root / "silver-source-registry.json"
    registry = _read_json(registry_path)
    entry = registry["datasets"][dataset_id]
    object_dir = source_root / "objects" / "sha256" / entry["logicalSha256"]
    return {
        "registry_path": registry_path,
        "registry": registry,
        "entry": entry,
        "object_dir": object_dir,
        "receipt_path": object_dir / "source-receipt.json",
        "manifest_path": object_dir / "source-publication-manifest.json",
    }


def _readdress_source_sidecars(parts: dict[str, Any], receipt: dict[str, Any], manifest: dict[str, Any]) -> None:
    """Rebuild fixture-side outer addresses after a coordinated relational mutation.

    This deliberately does not decide validity.  The production
    ``resolve_verified_source`` call in the test is the only verifier.
    """
    receipt_body = {key: value for key, value in receipt.items() if key != "receiptSha256"}
    receipt["receiptSha256"] = sha256_bytes(canonical_json_bytes(receipt_body))
    receipt_bytes = _write_json(parts["receipt_path"], receipt)

    manifest["receiptSha256"] = receipt["receiptSha256"]
    manifest["children"]["source-receipt.json"] = {
        "sha256": sha256_bytes(receipt_bytes),
        "bytes": len(receipt_bytes),
    }
    manifest_body = {key: value for key, value in manifest.items() if key != "manifestSha256"}
    manifest["manifestSha256"] = sha256_bytes(canonical_json_bytes(manifest_body))
    _write_json(parts["manifest_path"], manifest)

    parts["entry"]["receiptSha256"] = receipt["receiptSha256"]
    parts["entry"]["manifestSha256"] = manifest["manifestSha256"]
    _write_json(parts["registry_path"], parts["registry"])


def _apply_relationship_mutation(source_root: Path, mutation: str) -> None:
    parts = _source_parts(source_root)
    receipt = _read_json(parts["receipt_path"])
    manifest = _read_json(parts["manifest_path"])

    if mutation == "dataset-id":
        receipt["datasetVersionId"] = "different-dataset-id"
    elif mutation == "logical-sha":
        receipt["logicalSha256"] = "0" * 64
    elif mutation == "schema-sha":
        manifest["schemaSha256"] = "1" * 64
    elif mutation == "row-count":
        manifest["rowCount"] = int(manifest["rowCount"]) + 1
    elif mutation == "season-set":
        manifest["seasons"] = [1901]
    elif mutation == "object-directory-address":
        new_address = "f" * 64
        new_dir = source_root / "objects" / "sha256" / new_address
        shutil.copytree(parts["object_dir"], new_dir)
        parts["entry"]["logicalSha256"] = new_address
        _write_json(parts["registry_path"], parts["registry"])
        return
    else:  # pragma: no cover - test-author error, not an acceptance branch
        raise AssertionError(f"unknown source relationship mutation: {mutation}")

    _readdress_source_sidecars(parts, receipt, manifest)


def _child(publication: dict[str, Any], name: str) -> dict[str, Any]:
    return _read_json(publication["object_dir"] / name)


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


# =========================================================================== R1: season and column authority
def test_rejects_caller_authorized_2019(tmp_path: Path) -> None:
    rows = _rows(2019)
    source_root = tmp_path / "source"
    _publish_source(source_root, rows)

    with pytest.raises(_REJECTION_ERRORS):
        SP.publish_silver(
            silver_root=tmp_path / "silver",
            source_root=source_root,
            source_dataset_version_id=_SOURCE_ID,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
            authorized_seasons=[2019],
        )


def test_rejects_false_season_derivation_callback(tmp_path: Path) -> None:
    real_2019_rows = _rows(2019)
    with pytest.raises(_REJECTION_ERRORS):
        _publish_silver(
            tmp_path,
            real_2019_rows,
            source_season_of_row=lambda _row: 2024,
            silver_season_of_row=lambda _row: 2024,
        )


def test_rejects_row_and_receipt_season_disagreement(tmp_path: Path) -> None:
    # Put the synthetic object beneath the package conftest's explicitly allowed
    # disposable runtime so the assertion tests season relationships, not the
    # external-data guard's path policy.
    isolated_base = _RUNTIME / "r1-r2-season-agreement" / tmp_path.name
    publication = _publish_silver(
        isolated_base,
        _rows(2019),
        source_season_of_row=lambda _row: 2024,
        silver_season_of_row=lambda _row: 2024,
    )
    actual = sorted(
        set(
            pq.read_table(publication["object_dir"] / "object.parquet", columns=["season"])
            .column("season")
            .to_pylist()
        )
    )
    receipt_seasons = sorted(int(value) for value in publication["verified"]["receipt"]["perSeasonRows"])
    manifest_seasons = sorted(int(value) for value in publication["verified"]["manifest"]["seasons"])
    assert actual == receipt_seasons == manifest_seasons, (
        "production accepted a false season derivation: output rows, transformation receipt, and publication "
        "manifest do not describe the same seasons"
    )


def test_rejects_post_home_score(tmp_path: Path) -> None:
    del tmp_path  # isolation fixture is intentionally present even though the pure transform needs no files
    with pytest.raises(ST.SilverTransformError):
        ST.compute_prior_pa(
            _rows(2023, post_home_score=9),
            season_of_row=lambda row: row["season"],
        )


def test_rejects_unapproved_source_column_even_when_not_named_outcome(tmp_path: Path) -> None:
    rows = _rows(2023)
    for row in rows:
        row["auditor_unapproved_post_event_signal"] = 123.0
    with pytest.raises(_REJECTION_ERRORS):
        _publish_silver(tmp_path, rows)


# =========================================================================== R2: source and transform authority
def test_rejects_source_manifest_embedded_sha_mismatch(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    _publish_source(source_root, _rows())
    parts = _source_parts(source_root)
    manifest = _read_json(parts["manifest_path"])
    manifest["manifestSha256"] = "0" * 64
    _write_json(parts["manifest_path"], manifest)

    with pytest.raises(SP.SourceAuthorityError):
        SP.resolve_verified_source(source_root, _SOURCE_ID)


@pytest.mark.parametrize(
    "mutation",
    [
        "dataset-id",
        "logical-sha",
        "schema-sha",
        "row-count",
        "season-set",
        "object-directory-address",
    ],
    ids=[
        "dataset-id",
        "logical-sha",
        "schema-sha",
        "row-count",
        "season-set",
        "object-directory-address",
    ],
)
def test_reconstructs_all_source_relationships(tmp_path: Path, mutation: str) -> None:
    source_root = tmp_path / "source"
    _publish_source(source_root, _rows())
    _apply_relationship_mutation(source_root, mutation)

    with pytest.raises(SP.SourceAuthorityError):
        SP.resolve_verified_source(source_root, _SOURCE_ID)


def test_caller_rows_cannot_mint_governed_source(tmp_path: Path) -> None:
    with pytest.raises(SP.SourceAuthorityError):
        SP.publish_source_object(
            source_root=tmp_path / "caller-chosen-source-root",
            rows=_rows(),
            dataset_version_id="caller-chosen-governed-id",
            season_of_row=lambda row: row["season"],
        )


def test_caller_season_callback_cannot_mint_governed_source(tmp_path: Path) -> None:
    with pytest.raises(SP.SourceAuthorityError):
        SP.publish_source_object(
            source_root=tmp_path / "source",
            rows=_rows(2019),
            dataset_version_id=_SOURCE_ID,
            season_of_row=lambda _row: 2024,
        )


def test_silver_requires_server_issued_source_authority(tmp_path: Path) -> None:
    # The baseline accepts any caller-chosen source root/id after the same caller
    # minted it.  A corrected path must resolve a server-owned canonical identity,
    # not accept this self-issued authority chain.
    source_root = tmp_path / "caller-owned-source-root"
    _publish_source(source_root, _rows(), dataset_id="caller-owned-source-id")
    with pytest.raises(SP.SourceAuthorityError):
        SP.publish_silver(
            silver_root=tmp_path / "silver",
            source_root=source_root,
            source_dataset_version_id="caller-owned-source-id",
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
        )


def test_semantics_bind_actual_transform_receipt(tmp_path: Path) -> None:
    publication = _publish_silver(tmp_path, _rows())
    transform_code_receipt = _child(publication, "transform-code-receipt.json")
    semantic_children = [
        _child(publication, "prior-pa-semantic-contract.json"),
        _child(publication, "log1p-prior-pa-semantic-contract.json"),
    ]
    assert all(
        child["payload"]["derivationCodeDigest"] == transform_code_receipt["sha256"]
        for child in semantic_children
    ), "semantic derivation identity is a static transform name, not the verified transform-code receipt SHA"


def test_semantics_bind_game_sequence_when_used(tmp_path: Path) -> None:
    rows = [_row(2023, 1, "doubleheader-pa-1", game_sequence=1), _row(2023, 1, "doubleheader-pa-2", game_sequence=2)]
    rows[0]["game_id"] = "doubleheader-game-a"
    rows[1]["game_id"] = "doubleheader-game-b"
    publication = _publish_silver(tmp_path, rows)
    semantic = _child(publication, "prior-pa-semantic-contract.json")["payload"]
    assert "game_sequence" in semantic["sourceColumns"] and "game_sequence" in semantic["orderColumns"], (
        "production used game_sequence to order the values but omitted it from the semantic source/order authority"
    )


def test_family_lineage_is_derived_from_verified_members(tmp_path: Path) -> None:
    publication = _publish_silver(tmp_path, _rows())
    members = [
        _child(publication, "prior-pa-semantic-contract.json"),
        _child(publication, "log1p-prior-pa-semantic-contract.json"),
    ]
    expected_receipts = sorted(
        {sha for member in members for sha in member["payload"]["sourceReceiptShas"]}
    )
    family = _child(publication, "feature-family-contract.json")["payload"]
    assert sorted(family["sourceReceiptShas"]) == expected_receipts, (
        "family source lineage was taken from hardcoded base receipts rather than its verified semantic members"
    )


def test_tcr_binds_all_material_temporal_and_generation_parameters(tmp_path: Path) -> None:
    publication = _publish_silver(tmp_path, _rows())
    tcr = _child(publication, "transform-code-receipt.json")
    transformation = _child(publication, "transformation-receipt.json")
    params = tcr["params"]
    required = {
        "authorizedSeasons",
        "seasonDerivationSha256",
        "generationAuthoritySha256",
        "baseFeatureSourceAuthoritySha256",
    }
    assert required <= set(params), f"transform-code receipt omits material authority: {sorted(required - set(params))}"
    assert params["authorizedSeasons"] == list(ST.DEFAULT_AUTHORIZED_SEASONS)
    for key in (
        "seasonDerivationSha256",
        "generationAuthoritySha256",
        "baseFeatureSourceAuthoritySha256",
    ):
        assert _is_hex64(params[key]), f"{key} must be a content address"
        assert transformation.get(key) == params[key], f"transformation receipt does not mirror {key}"
    assert transformation.get("authorizedSeasons") == params["authorizedSeasons"]
