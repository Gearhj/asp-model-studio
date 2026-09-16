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


def _unregistered_rows_2023() -> list[dict[str, Any]]:
    """Valid 2023 science deliberately absent from the canonical issuer fixture."""
    rows = _rows(2023)
    # This is a scientific-value distinction, not cosmetic row/key vocabulary:
    # identifiers are normalized away by the joint contract, while a changed
    # model feature is preserved in the normalized operation.
    rows[0][FEATURE_NAMES[0]] = 0.91
    return rows


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


def _runner_issuer_fixture(signature: str) -> dict[str, Any]:
    configured = os.environ.get("CODEX_PHASE7D5A7_ISSUER_REGISTRY", "").strip()
    if not configured:
        pytest.fail(f"{signature} the runner-owned canonical issuer fixture is not configured")
    path = Path(configured).resolve()
    if not path.is_file():
        pytest.fail(f"{signature} canonical issuer fixture is missing: {path}")
    return _read_json(path)


def _source_authority_evidence(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceLogicalSha256": result["parts"]["entry"]["logicalSha256"],
        "sourcePhysicalSha256": result["receipt"]["physicalSha256"],
        "sourceSchemaSha256": result["receipt"]["schemaSha256"],
        "sourceReceiptSha256": result["parts"]["entry"]["receiptSha256"],
        "sourceManifestSha256": result["parts"]["entry"]["manifestSha256"],
        "rowCount": int(result["receipt"]["rowCount"]),
        "seasons": sorted(int(value) for value in result["receipt"]["seasons"]),
    }


def _fixture_issuer_record(fixture: dict[str, Any], issuer_sha: str, signature: str) -> dict[str, Any]:
    matches = [
        record for record in fixture.get("issuerRecords", [])
        if record.get("issuerRecordSha256") == issuer_sha
    ]
    assert len(matches) == 1, f"{signature} fixture does not contain issuer record {issuer_sha!r} exactly once"
    record = matches[0]
    body = {key: value for key, value in record.items() if key != "issuerRecordSha256"}
    assert sha256_bytes(canonical_json_bytes(body)) == issuer_sha, (
        f"{signature} runner issuer record is not content-addressed"
    )
    return record


def _attach_runner_issuer(
    result: dict[str, Any],
    *,
    control_id: str | None = None,
    signature: str,
) -> dict[str, Any]:
    """Persist a runner-owned issuer precondition without making an authority decision."""
    fixture = _runner_issuer_fixture(signature)
    actual = _source_authority_evidence(result)
    if control_id is not None:
        # The ID selects the auditor-authored negative witness, never production
        # authority; every source relationship is reconstructed and compared below.
        controls = [
            item for item in fixture.get("unauthorizedIssuanceControls", [])
            if item.get("controlId") == control_id
        ]
        assert len(controls) == 1, f"{signature} fixture lacks unique control {control_id!r}"
        authority = controls[0]
        assert authority.get("expectedStageB") == "REJECT_UNAUTHORIZED_SEASON"
        assert authority.get("lookupPermitted") is False
        issuer_sha = str(authority["issuerRecordSha256"])
        record = _fixture_issuer_record(fixture, issuer_sha, signature)
    else:
        scientific_keys = (
            "sourceLogicalSha256",
            "sourcePhysicalSha256",
            "sourceSchemaSha256",
            "rowCount",
            "seasons",
        )
        records = [
            record for record in fixture.get("issuerRecords", [])
            if all(record.get(key) == actual[key] for key in scientific_keys)
        ]
        assert len(records) == 1, (
            f"{signature} reconstructed source relationships do not identify exactly one issuer record"
        )
        record = records[0]
        issuer_sha = str(record["issuerRecordSha256"])
        authority = record
        # Trace metadata is audited only after authority has been selected from
        # reconstructed science; it is never an input to the lookup.
        traces = [
            item for item in fixture.get("nonAuthoritativeTraceMetadata", [])
            if item.get("issuerRecordSha256") == issuer_sha
        ]
        assert traces and all(item.get("lookupPermitted") is False for item in traces)
    authority_keys = [
        "sourceLogicalSha256",
        "sourcePhysicalSha256",
        "sourceSchemaSha256",
        "rowCount",
        "seasons",
    ]
    if control_id is not None:
        authority_keys.extend(("sourceReceiptSha256", "sourceManifestSha256"))
    for key in authority_keys:
        value = actual[key]
        expected = authority.get(key, record.get(key))
        assert expected == value, (
            f"{signature} staged source does not match runner issuer authority at {key}: "
            f"expected {expected!r}, got {value!r}"
        )

    issuer_dir = Path(result["source_root"]) / "issuer-records" / "sha256" / issuer_sha
    issuer_dir.mkdir(parents=True, exist_ok=False)
    issuer_dir.joinpath("issuer-record.json").write_bytes(canonical_json_bytes(record))
    result["parts"]["entry"]["issuerRecordSha256"] = issuer_sha
    _write_json(result["parts"]["registry_path"], result["parts"]["registry"])
    return record


def _assert_temporal_issuer_precondition(record: dict[str, Any], signature: str) -> None:
    """Separate the R1 temporal boundary from R2's missing-issuer boundary."""
    fixture = _runner_issuer_fixture(signature)
    temporal = (fixture.get("contracts") or {}).get("temporal") or {}
    authorized = sorted(int(value) for value in temporal.get("authorizedSeasons", []))
    assert authorized == [2021, 2022, 2023, 2024] and 2019 not in authorized, (
        f"{signature} canonical temporal authority is not the required 2021-2024 contract: {authorized}"
    )
    assert record.get("temporalContractSha256") == temporal.get("sha256"), (
        f"{signature} issuer record is not bound to the canonical temporal contract"
    )


def _attempt_source_stage(
    source_root: Path,
    rows: list[dict[str, Any]],
    *,
    dataset_id: str = _SOURCE_ID,
    season_of_row: Callable[[dict[str, Any]], int] | None = None,
) -> dict[str, Any]:
    try:
        entry = _publish_source(
            source_root,
            [dict(row) for row in rows],
            dataset_id=dataset_id,
            season_of_row=season_of_row,
        )
    except _REJECTION_ERRORS as exc:
        return {"accepted": False, "error": exc, "source_root": source_root}
    parts = _source_parts(source_root, dataset_id)
    receipt = _read_json(parts["receipt_path"])
    manifest = _read_json(parts["manifest_path"])
    actual = sorted(
        set(
            int(value)
            for value in pq.read_table(parts["object_dir"] / "source.parquet", columns=["season"])
            .column("season")
            .to_pylist()
        )
    )
    return {
        "accepted": True,
        "entry": entry,
        "parts": parts,
        "receipt": receipt,
        "manifest": manifest,
        "actual": actual,
        "source_root": source_root,
    }


def _assert_truthful_unissued_source(result: dict[str, Any], expected_seasons: list[int]) -> None:
    assert result["accepted"]
    assert result["actual"] == expected_seasons
    assert sorted(int(value) for value in result["receipt"]["seasons"]) == expected_seasons
    assert sorted(int(value) for value in result["manifest"]["seasons"]) == expected_seasons
    assert "issuerRecordSha256" not in result["entry"]
    assert "issuerRecordSha256" not in result["parts"]["entry"]
    assert not (Path(result["source_root"]) / "issuer-records").exists()


def _require_stage_b_and_c_rejected(
    *,
    source_root: Path,
    silver_root: Path,
    dataset_id: str,
    season_of_row: Callable[[dict[str, Any]], int],
    signature: str,
    stage_b_reason: str,
    issuer_record: dict[str, Any] | None = None,
) -> None:
    try:
        SP.resolve_verified_source(source_root, dataset_id)
    except SP.SourceAuthorityError as exc:
        reason = str(exc).lower()
        if stage_b_reason == "UNAUTHORIZED_SEASON":
            assert issuer_record is not None, f"{signature} temporal rejection lacks an issuer precondition"
            _assert_temporal_issuer_precondition(issuer_record, signature)
            matched = ("2019" in reason) and any(
                token in reason for token in ("season", "temporal", "authorized", "2021-2024")
            )
        elif stage_b_reason == "MISSING_ISSUER":
            matched = (
                "issuer" in reason
                or "canonical upstream" in reason
                or "governed authority" in reason
            )
        else:  # pragma: no cover - auditor-authored call contract
            raise AssertionError(f"unknown Stage-B reason: {stage_b_reason}")
        assert matched, (
            f"{signature} Stage B rejected at the wrong boundary; expected {stage_b_reason}, got: {exc}"
        )
    else:
        pytest.fail(f"{signature} Stage B accepted an object that must reject for {stage_b_reason}")

    try:
        SP.publish_silver(
            silver_root=silver_root,
            source_root=source_root,
            source_dataset_version_id=dataset_id,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=season_of_row,
        )
    except _REJECTION_ERRORS:
        return
    pytest.fail(f"{signature} Stage C accepted a Stage-A object without governed issuer authority")


def _require_valid_2023_issuer_control(base: Path, signature: str) -> None:
    """Prove the same runner issuer mechanism accepts its valid 2023 control."""
    result = _attempt_source_stage(
        base / "source",
        _rows(2023),
        season_of_row=lambda row: row["season"],
    )
    _assert_truthful_unissued_source(result, [2023])
    record = _attach_runner_issuer(
        result,
        signature=signature,
    )
    try:
        handle, _ = SP.resolve_verified_source(result["source_root"], _SOURCE_ID)
        entry = SP.publish_silver(
            silver_root=base / "silver",
            source_root=result["source_root"],
            source_dataset_version_id=_SOURCE_ID,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
        )
        SP.verify_silver(base / "silver", entry["manifestSha256"])
    except _REJECTION_ERRORS as exc:
        pytest.fail(f"{signature} valid runner-issued 2023 control was rejected: {exc}")
    assert handle.logical_sha256 == record["sourceLogicalSha256"]
    assert handle.physical_sha256 == record["sourcePhysicalSha256"]
    assert handle.schema_sha256 == record["sourceSchemaSha256"]
    assert handle.row_count == record["rowCount"] and list(handle.seasons) == record["seasons"]


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
    # Stage A is physical staging, not governed issuance.  A real 2019 row may be
    # represented, but its date-derived season must remain 2019 and staging must
    # not mint an issuer record merely because the path is below RUNTIME_ROOT.
    _require_valid_2023_issuer_control(
        tmp_path / "valid-2023-control",
        "R1_STAGE_BOUNDARY_RECONCILIATION:",
    )
    isolated_base = _RUNTIME / "r1-r2-season-agreement" / tmp_path.name
    inside = _attempt_source_stage(
        isolated_base / "source",
        _rows(2019),
        season_of_row=lambda _row: 2024,
    )
    outside = _attempt_source_stage(
        tmp_path / "outside-source",
        _rows(2019),
        season_of_row=lambda _row: 2024,
    )
    assert inside["accepted"] == outside["accepted"], (
        "R1_STAGE_BOUNDARY_RECONCILIATION: identical false-callback Stage-A inputs received different decisions "
        f"inside/outside RUNTIME_ROOT: {inside['accepted']} vs {outside['accepted']}"
    )
    if not inside["accepted"]:
        return
    for label, result in (("inside", inside), ("outside", outside)):
        _assert_truthful_unissued_source(result, [2019])
        issuer_record = _attach_runner_issuer(
            result,
            control_id="original-base-2019-under-2021-2024-v1",
            signature="R1_STAGE_BOUNDARY_RECONCILIATION:",
        )
        _require_stage_b_and_c_rejected(
            source_root=result["source_root"],
            silver_root=tmp_path / f"silver-{label}",
            dataset_id=_SOURCE_ID,
            season_of_row=lambda _row: 2024,
            signature="R1_STAGE_BOUNDARY_RECONCILIATION:",
            stage_b_reason="UNAUTHORIZED_SEASON",
            issuer_record=issuer_record,
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
    source_root = tmp_path / "caller-chosen-source-root"
    # The display label is deliberately neutral. Reserved-namespace validation
    # is not the authority decision under test; the missing issuer is.
    dataset_id = "synthetic-source-label-v1"
    try:
        entry = SP.publish_source_object(
            source_root=source_root,
            rows=_unregistered_rows_2023(),
            dataset_version_id=dataset_id,
            season_of_row=lambda row: row["season"],
        )
    except SP.SourceAuthorityError as exc:
        pytest.fail(
            "R2_STAGE_BOUNDARY_RECONCILIATION: Stage-A physical staging was rejected solely by caller-chosen "
            f"identifier vocabulary: {exc}"
        )
    assert "issuerRecordSha256" not in entry
    _require_stage_b_and_c_rejected(
        source_root=source_root,
        silver_root=tmp_path / "silver",
        dataset_id=dataset_id,
        season_of_row=lambda row: row["season"],
        signature="R2_STAGE_BOUNDARY_RECONCILIATION:",
        stage_b_reason="MISSING_ISSUER",
    )


def test_caller_season_callback_cannot_mint_governed_source(tmp_path: Path) -> None:
    rows = _rows(2019)
    _require_valid_2023_issuer_control(
        tmp_path / "valid-2023-control",
        "R2_STAGE_BOUNDARY_RECONCILIATION:",
    )
    outside = _attempt_source_stage(
        tmp_path / "source",
        rows,
        season_of_row=lambda _row: 2024,
    )
    inside = _attempt_source_stage(
        _RUNTIME / "r1-r2-source-callback" / tmp_path.name,
        rows,
        season_of_row=lambda _row: 2024,
    )
    assert outside["accepted"] == inside["accepted"], (
        "R2_STAGE_BOUNDARY_RECONCILIATION: path placement changed the Stage-A callback decision"
    )
    if not outside["accepted"]:
        return
    for label, result in (("outside", outside), ("inside", inside)):
        _assert_truthful_unissued_source(result, [2019])
        issuer_record = _attach_runner_issuer(
            result,
            control_id="original-base-2019-under-2021-2024-v1",
            signature="R2_STAGE_BOUNDARY_RECONCILIATION:",
        )
        _require_stage_b_and_c_rejected(
            source_root=result["source_root"],
            silver_root=tmp_path / f"silver-{label}",
            dataset_id=_SOURCE_ID,
            season_of_row=lambda _row: 2024,
            signature="R2_STAGE_BOUNDARY_RECONCILIATION:",
            stage_b_reason="UNAUTHORIZED_SEASON",
            issuer_record=issuer_record,
        )


def test_silver_requires_server_issued_source_authority(tmp_path: Path) -> None:
    # The baseline accepts any caller-chosen source root/id after the same caller
    # minted it.  A corrected path must resolve a server-owned canonical identity,
    # not accept this self-issued authority chain.
    source_root = tmp_path / "caller-owned-source-root"
    dataset_id = "caller-owned-source-id"
    entry = _publish_source(source_root, _unregistered_rows_2023(), dataset_id=dataset_id)
    assert "issuerRecordSha256" not in entry
    _require_stage_b_and_c_rejected(
        source_root=source_root,
        silver_root=tmp_path / "silver",
        dataset_id=dataset_id,
        season_of_row=lambda row: row["season"],
        signature="R2_STAGE_BOUNDARY_RECONCILIATION:",
        stage_b_reason="MISSING_ISSUER",
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
