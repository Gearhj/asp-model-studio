"""Phase 7D.5A.5 delta-red acceptance tests for D1 and D2.

Every decision is made by the production Silver publisher/resolver at the
audited baseline.  Fixtures contain only small synthetic rows under the
runner-supplied external audit root.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# Establish every mutable root before importing production modules.  A focused
# invocation must supply the same explicit external seam as the delta runner.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_configured_root = os.environ.get("CODEX_PHASE7D5A5_AUDIT_ROOT", "").strip()
if not _configured_root:
    raise RuntimeError("CODEX_PHASE7D5A5_AUDIT_ROOT must name an external disposable root")
_AUDIT_ROOT = Path(_configured_root).resolve()
if _AUDIT_ROOT == _REPO_ROOT or _REPO_ROOT in _AUDIT_ROOT.parents:
    raise RuntimeError("the Phase 7D.5A.5 audit root must be outside the repository")
_RUNTIME_ROOT = (_AUDIT_ROOT / "runtime").resolve()
os.environ["ASP_MODEL_STUDIO_RUNTIME_ROOT"] = str(_RUNTIME_ROOT)
os.environ["ASP_REQUIRE_ISOLATED_RUNTIME"] = "1"
os.environ["ASP_MODEL_EXCHANGE_ROOT"] = str((_AUDIT_ROOT / "model-exchange-disabled").resolve())
os.environ["TEMP"] = str((_AUDIT_ROOT / "temp").resolve())
os.environ["TMP"] = str((_AUDIT_ROOT / "temp").resolve())
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import pyarrow.parquet as pq  # noqa: E402
import pytest  # noqa: E402

from server.sports_datasets.consumer import canonical_json_bytes, sha256_bytes  # noqa: E402
from server.sports_modeling import silver_publish as SP  # noqa: E402
from server.sports_modeling import silver_transform as ST  # noqa: E402
from server.sports_modeling.feature_contract import FEATURE_NAMES  # noqa: E402
from tests import _silver_fixture as F  # noqa: E402


_PRODUCTION_REJECTIONS = (
    SP.SourceAuthorityError,
    SP.SilverPublishError,
    ST.SilverTransformError,
)
# This display alias is explicitly present in the runner-owned canonical
# synthetic issuer registry.  Using it for D1 lets the test distinguish a
# temporal-policy rejection from the independent D2 missing-issuer rejection.
_D1_SOURCE_ID = "codex-r1-r2-synthetic-source-v1"
_D1_SIG = "D1_PATH_INDEPENDENT_SEASON_AUTHORITY:"
_D2_SIG = "D2_CRYPTOGRAPHIC_ISSUER_AUTHORITY:"
_NEUTRAL_IDS = (
    "mlb-history-v17",
    "mlb-source-2024",
    "statcast-curated-a",
    "pa-history-release-1",
)


def _canonical_issuer_rows(season: int) -> list[dict[str, Any]]:
    """Exact two-row shape used by the canonical original-base issuer controls."""
    rows: list[dict[str, Any]] = []
    for at_bat in (1, 2):
        row: dict[str, Any] = {
            "plate_appearance_id": f"pa-{season}-{at_bat}",
            "game_id": f"game-{season}",
            "game_date": f"{season}-04-01",
            "at_bat_number": at_bat,
            "batter_canonical_player_uuid": "batter-1",
            "season": season,
        }
        for index, feature in enumerate(FEATURE_NAMES):
            row[feature] = float((at_bat + index) % 7) / 10.0
        rows.append(row)
    return rows


def _rows_2019() -> list[dict[str, Any]]:
    return _canonical_issuer_rows(2019)


def _rows_2023() -> list[dict[str, Any]]:
    return F.source_rows(seasons=(2023,), batters=("b1",), per=2)


def _canonical_issuer_rows_2023() -> list[dict[str, Any]]:
    """Rows bound by the original-base record in the canonical issuer fixture."""
    return _canonical_issuer_rows(2023)


def _runtime_case(tmp_path: Path, label: str) -> Path:
    return _RUNTIME_ROOT / "phase7d5a5-d1" / f"{tmp_path.name}-{label}"


def _silver_outputs_exist(silver_root: Path) -> bool:
    registry = silver_root / "silver-registry.json"
    objects_root = silver_root / "objects" / "sha256"
    return registry.exists() or (objects_root.is_dir() and any(objects_root.iterdir()))


def _attempt_silver(
    base: Path,
    *,
    dataset_id: str,
    rows: list[dict[str, Any]],
    callback_season: int,
    authorized_seasons: list[int] | None = None,
    issuer_control_id: str,
) -> dict[str, Any]:
    """Run explicit A/B/C boundaries with a runner-owned issuer precondition."""
    source_root = base / "source"
    silver_root = base / "silver"
    staged = _attempt_source_stage(
        source_root,
        dataset_id=dataset_id,
        rows=rows,
        callback_season=callback_season,
    )
    if not staged["accepted"]:
        return {**staged, "silver_root": silver_root, "rejectionStage": "STAGE_A"}
    _assert_truthful_unissued_stage_a(staged, sorted({int(row["season"]) for row in rows}))
    issuer_record = _attach_runner_issuer(
        staged,
        control_id=issuer_control_id,
        signature=_D1_SIG,
    )
    try:
        SP.resolve_verified_source(source_root, dataset_id)
    except SP.SourceAuthorityError as exc:
        return {
            **staged,
            "accepted": False,
            "error": exc,
            "silver_root": silver_root,
            "issuer_record": issuer_record,
            "rejectionStage": "STAGE_B",
        }
    try:
        entry = SP.publish_silver(
            silver_root=silver_root,
            source_root=source_root,
            source_dataset_version_id=dataset_id,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda _row: callback_season,
            authorized_seasons=authorized_seasons,
        )
        verified = SP.verify_silver(silver_root, entry["manifestSha256"])
    except _PRODUCTION_REJECTIONS as exc:
        return {
            **staged,
            "accepted": False,
            "error": exc,
            "source_root": source_root,
            "silver_root": silver_root,
            "issuer_record": issuer_record,
            "rejectionStage": "STAGE_C",
        }
    return {
        **staged,
        "accepted": True,
        "entry": entry,
        "verified": verified,
        "source_root": source_root,
        "silver_root": silver_root,
        "issuer_record": issuer_record,
        "rejectionStage": None,
    }


def _publish_neutral_source(source_root: Path, dataset_id: str) -> dict[str, Any]:
    return SP.publish_source_object(
        source_root=source_root,
        rows=_rows_2023(),
        dataset_version_id=dataset_id,
        season_of_row=lambda row: row["season"],
    )


def _source_registry(source_root: Path) -> tuple[Path, dict[str, Any]]:
    path = source_root / "silver-source-registry.json"
    return path, json.loads(path.read_bytes())


def _runner_issuer_fixture(signature: str) -> tuple[Path, dict[str, Any]]:
    configured = os.environ.get("CODEX_PHASE7D5A7_ISSUER_REGISTRY", "").strip()
    if not configured:
        pytest.fail(f"{signature} the runner-owned canonical issuer fixture is not configured")
    path = Path(configured).resolve()
    if not path.is_file():
        pytest.fail(f"{signature} canonical issuer fixture is missing: {path}")
    return path, json.loads(path.read_bytes())


def _source_authority_evidence(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "sourceLogicalSha256": result["registry_entry"]["logicalSha256"],
        "sourcePhysicalSha256": result["receipt"]["physicalSha256"],
        "sourceSchemaSha256": result["receipt"]["schemaSha256"],
        "sourceReceiptSha256": result["registry_entry"]["receiptSha256"],
        "sourceManifestSha256": result["registry_entry"]["manifestSha256"],
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
    """Persist an immutable runner-owned precondition; production still decides Stage B/C."""
    _, fixture = _runner_issuer_fixture(signature)
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
    result["registry_entry"]["issuerRecordSha256"] = issuer_sha
    result["registry_path"].write_bytes(canonical_json_bytes(result["registry"]))
    return record


def _assert_temporal_issuer_precondition(record: dict[str, Any], signature: str) -> None:
    """Prove D1 has issuer authority and is not merely a D2 missing-issuer case."""
    _, fixture = _runner_issuer_fixture(signature)
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
    *,
    dataset_id: str,
    rows: list[dict[str, Any]],
    callback_season: int,
) -> dict[str, Any]:
    """Exercise Stage A only and expose its physical evidence without granting authority."""
    try:
        entry = SP.publish_source_object(
            source_root=source_root,
            rows=[dict(row) for row in rows],
            dataset_version_id=dataset_id,
            season_of_row=lambda _row: callback_season,
        )
    except _PRODUCTION_REJECTIONS as exc:
        return {"accepted": False, "error": exc, "source_root": source_root}

    registry_path, registry = _source_registry(source_root)
    registry_entry = registry["datasets"][dataset_id]
    object_dir = source_root / "objects" / "sha256" / registry_entry["logicalSha256"]
    receipt = json.loads((object_dir / "source-receipt.json").read_bytes())
    manifest = json.loads((object_dir / "source-publication-manifest.json").read_bytes())
    physical_seasons = sorted(
        set(
            int(value)
            for value in pq.read_table(object_dir / "source.parquet", columns=["season"])
            .column("season")
            .to_pylist()
        )
    )
    return {
        "accepted": True,
        "entry": entry,
        "registry": registry,
        "registry_entry": registry_entry,
        "registry_path": registry_path,
        "object_dir": object_dir,
        "receipt": receipt,
        "manifest": manifest,
        "physical_seasons": physical_seasons,
        "source_root": source_root,
    }


def _assert_truthful_unissued_stage_a(result: dict[str, Any], expected_seasons: list[int]) -> None:
    assert result["accepted"], f"Stage-A staging unexpectedly rejected: {result.get('error')!r}"
    assert result["physical_seasons"] == expected_seasons
    assert sorted(int(value) for value in result["receipt"]["seasons"]) == expected_seasons
    assert sorted(int(value) for value in result["manifest"]["seasons"]) == expected_seasons
    assert "issuerRecordSha256" not in result["entry"]
    assert "issuerRecordSha256" not in result["registry_entry"]
    assert not (Path(result["source_root"]) / "issuer-records").exists()


def _require_missing_issuer_rejected(source_root: Path, dataset_id: str) -> None:
    try:
        SP.resolve_verified_source(source_root, dataset_id)
    except SP.SourceAuthorityError as exc:
        reason = str(exc).lower()
        assert "issuer" in reason or "canonical upstream" in reason or "governed authority" in reason, (
            f"{_D2_SIG} Stage B rejected for the wrong boundary instead of missing issuer authority: {exc}"
        )
        return
    pytest.fail(f"{_D2_SIG} Stage B accepted an issuer-less Stage-A object")


def _require_temporal_authority_rejected(
    source_root: Path,
    dataset_id: str,
    label: str,
    issuer_record: dict[str, Any],
) -> None:
    _assert_temporal_issuer_precondition(issuer_record, _D1_SIG)
    try:
        SP.resolve_verified_source(source_root, dataset_id)
    except SP.SourceAuthorityError as exc:
        reason = str(exc).lower()
        temporal = ("2019" in reason) and any(
            token in reason for token in ("season", "temporal", "authorized", "2021-2024")
        )
        assert temporal, (
            f"{_D1_SIG} Stage B rejected {label} for a non-temporal reason; "
            f"the 2019 authority boundary was not exercised: {exc}"
        )
        return
    pytest.fail(f"{_D1_SIG} Stage B authorized truthful 2019 staging at {label} placement")


def _assert_temporal_stage_b_result(result: dict[str, Any], label: str) -> None:
    assert not result["accepted"] and result.get("rejectionStage") == "STAGE_B", (
        f"{_D1_SIG} {label} must reject at Stage B under the temporal contract, got "
        f"{result.get('rejectionStage')}: {result.get('error')!r}"
    )
    record = result["issuer_record"]
    _assert_temporal_issuer_precondition(record, _D1_SIG)
    reason = str(result["error"]).lower()
    assert "2019" in reason and any(
        token in reason for token in ("season", "temporal", "authorized", "2021-2024")
    ), f"{_D1_SIG} {label} rejected for a non-temporal reason: {result['error']}"


def _assert_false_callback_or_temporal_result(result: dict[str, Any], label: str) -> None:
    if result.get("rejectionStage") == "STAGE_A":
        reason = str(result.get("error", "")).lower()
        assert any(token in reason for token in ("callback", "derivation", "season", "disagree")), (
            f"{_D1_SIG} {label} Stage A rejected for a non-scientific reason: {result.get('error')!r}"
        )
        return
    _assert_temporal_stage_b_result(result, label)


def _require_silver_rejected(
    *,
    silver_root: Path,
    source_root: Path,
    dataset_id: str,
    callback_season: int,
    signature: str,
) -> None:
    try:
        SP.publish_silver(
            silver_root=silver_root,
            source_root=source_root,
            source_dataset_version_id=dataset_id,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda _row: callback_season,
        )
    except _PRODUCTION_REJECTIONS:
        return
    pytest.fail(f"{signature} Stage C accepted a source without governed issuer authority")


def _require_valid_2023_issuer_control(base: Path, signature: str) -> None:
    """Prove that the same explicit fixture attachment accepts canonical 2023."""
    result = _attempt_source_stage(
        base / "source",
        dataset_id=_D1_SOURCE_ID,
        rows=_canonical_issuer_rows_2023(),
        callback_season=2023,
    )
    _assert_truthful_unissued_stage_a(result, [2023])
    record = _attach_runner_issuer(
        result,
        signature=signature,
    )
    try:
        handle, _ = SP.resolve_verified_source(result["source_root"], _D1_SOURCE_ID)
        entry = SP.publish_silver(
            silver_root=base / "silver",
            source_root=result["source_root"],
            source_dataset_version_id=_D1_SOURCE_ID,
            base_feature_ids=list(FEATURE_NAMES),
            season_of_row=lambda row: row["season"],
        )
        SP.verify_silver(base / "silver", entry["manifestSha256"])
    except _PRODUCTION_REJECTIONS as exc:
        pytest.fail(f"{signature} valid runner-issued 2023 control was rejected: {exc}")
    assert handle.logical_sha256 == record["sourceLogicalSha256"]
    assert handle.physical_sha256 == record["sourcePhysicalSha256"]
    assert handle.schema_sha256 == record["sourceSchemaSha256"]
    assert handle.row_count == record["rowCount"] and list(handle.seasons) == record["seasons"]


# =========================================================================== D1
def test_runtime_root_placement_does_not_disable_season_authority(tmp_path: Path) -> None:
    base = _runtime_case(tmp_path, "placement")
    result = _attempt_silver(
        base,
        dataset_id=_D1_SOURCE_ID,
        rows=_rows_2019(),
        callback_season=2024,
        authorized_seasons=[2024],
        issuer_control_id="original-base-2019-under-2021-2024-v1",
    )

    _assert_false_callback_or_temporal_result(result, "inside-runtime placement")
    assert not _silver_outputs_exist(base / "silver")


def test_identical_source_has_identical_season_decision_inside_and_outside_runtime_root(
    tmp_path: Path,
) -> None:
    rows = _rows_2019()
    inside = _attempt_silver(
        _runtime_case(tmp_path, "inside"),
        dataset_id=_D1_SOURCE_ID,
        rows=rows,
        callback_season=2024,
        authorized_seasons=[2024],
        issuer_control_id="original-base-2019-under-2021-2024-v1",
    )
    outside = _attempt_silver(
        tmp_path / "outside",
        dataset_id=_D1_SOURCE_ID,
        rows=rows,
        callback_season=2024,
        authorized_seasons=[2024],
        issuer_control_id="original-base-2019-under-2021-2024-v1",
    )

    assert inside.get("rejectionStage") == outside.get("rejectionStage"), (
        f"{_D1_SIG} path placement changed the scientific rejection stage: "
        f"inside={inside.get('rejectionStage')}, outside={outside.get('rejectionStage')}"
    )
    _assert_false_callback_or_temporal_result(inside, "inside-runtime placement")
    _assert_false_callback_or_temporal_result(outside, "outside-runtime placement")


def test_runtime_root_source_cannot_publish_2019_as_authorized(tmp_path: Path) -> None:
    base = _runtime_case(tmp_path, "unauthorized-2019")
    result = _attempt_silver(
        base,
        dataset_id=_D1_SOURCE_ID,
        rows=_rows_2019(),
        callback_season=2019,
        authorized_seasons=[2024],
        issuer_control_id="original-base-2019-under-2021-2024-v1",
    )

    _assert_temporal_stage_b_result(result, "server-owned 2019 source")
    assert not _silver_outputs_exist(base / "silver"), (
        f"{_D1_SIG} an unauthorized season left a Silver object or registry entry"
    )


def test_runtime_root_source_callback_cannot_relabel_2019_as_2024(tmp_path: Path) -> None:
    rows = _rows_2019()
    _require_valid_2023_issuer_control(
        tmp_path / "valid-2023-control",
        _D1_SIG,
    )
    inside = _attempt_source_stage(
        _runtime_case(tmp_path, "false-callback-inside") / "source",
        dataset_id=_D1_SOURCE_ID,
        rows=rows,
        callback_season=2024,
    )
    outside = _attempt_source_stage(
        tmp_path / "false-callback-outside" / "source",
        dataset_id=_D1_SOURCE_ID,
        rows=rows,
        callback_season=2024,
    )

    assert inside["accepted"] == outside["accepted"], (
        f"{_D1_SIG} Stage-A placement changed the false-callback decision: "
        f"inside={inside['accepted']}, outside={outside['accepted']}"
    )
    if inside["accepted"]:
        _assert_truthful_unissued_stage_a(inside, [2019])
        _assert_truthful_unissued_stage_a(outside, [2019])

    for label, source_result in (("inside", inside), ("outside", outside)):
        if source_result["accepted"]:
            issuer_record = _attach_runner_issuer(
                source_result,
                control_id="original-base-2019-under-2021-2024-v1",
                signature=_D1_SIG,
            )
            _require_temporal_authority_rejected(
                source_result["source_root"],
                _D1_SOURCE_ID,
                label,
                issuer_record,
            )
            _require_silver_rejected(
                silver_root=tmp_path / f"false-callback-{label}-silver",
                source_root=source_result["source_root"],
                dataset_id=_D1_SOURCE_ID,
                callback_season=2024,
                signature=_D1_SIG,
            )


def test_output_receipt_manifest_and_source_seasons_must_all_agree(tmp_path: Path) -> None:
    base = _runtime_case(tmp_path, "all-season-evidence")
    result = _attempt_silver(
        base,
        dataset_id=_D1_SOURCE_ID,
        rows=_rows_2019(),
        callback_season=2019,
        authorized_seasons=[2024],
        issuer_control_id="original-base-2019-under-2021-2024-v1",
    )
    _assert_temporal_stage_b_result(result, "all-season-evidence source")
    if result["accepted"]:
        verified = result["verified"]
        object_dir = Path(verified["objectDir"])
        output_seasons = sorted(
            set(pq.read_table(object_dir / "object.parquet", columns=["season"])["season"].to_pylist())
        )
        transform_seasons = sorted(int(value) for value in verified["receipt"]["perSeasonRows"])
        manifest_seasons = sorted(int(value) for value in verified["manifest"]["seasons"])
        source_receipt = json.loads((object_dir / "source-object-receipt.json").read_bytes())
        source_manifest = json.loads((object_dir / "source-publication-manifest.json").read_bytes())
        pytest.fail(
            f"{_D1_SIG} unauthorized 2019 publication exists; internal agreement cannot confer authority: "
            f"output={output_seasons}, transform={transform_seasons}, outer={manifest_seasons}, "
            f"sourceReceipt={source_receipt.get('seasons')}, sourceManifest={source_manifest.get('seasons')}"
        )

    assert not _silver_outputs_exist(base / "silver")


# =========================================================================== D2
def test_neutral_looking_identifier_cannot_mint_source_authority(tmp_path: Path) -> None:
    dataset_id = "mlb-history-v17"
    source = _attempt_source_stage(
        tmp_path / "neutral-mint" / "source",
        dataset_id="mlb-history-v17",
        rows=_rows_2023(),
        callback_season=2023,
    )
    _assert_truthful_unissued_stage_a(source, [2023])
    _require_missing_issuer_rejected(source["source_root"], dataset_id)
    _require_silver_rejected(
        silver_root=tmp_path / "neutral-mint" / "silver",
        source_root=source["source_root"],
        dataset_id=dataset_id,
        callback_season=2023,
        signature=_D2_SIG,
    )


def test_identifier_vocabulary_does_not_determine_issuer_authority(tmp_path: Path) -> None:
    stage_a_decisions: dict[str, bool] = {}
    for index, dataset_id in enumerate(_NEUTRAL_IDS):
        result = _attempt_source_stage(
            tmp_path / f"neutral-{index}" / "source",
            dataset_id=dataset_id,
            rows=_rows_2023(),
            callback_season=2023,
        )
        stage_a_decisions[dataset_id] = bool(result["accepted"])
        if result["accepted"]:
            _assert_truthful_unissued_stage_a(result, [2023])

    assert all(stage_a_decisions.values()), (
        f"{_D2_SIG} display vocabulary changed Stage-A physical staging: {stage_a_decisions}"
    )
    for index, dataset_id in enumerate(_NEUTRAL_IDS):
        source_root = tmp_path / f"neutral-{index}" / "source"
        _require_missing_issuer_rejected(source_root, dataset_id)
        _require_silver_rejected(
            silver_root=tmp_path / f"neutral-{index}" / "silver",
            source_root=source_root,
            dataset_id=dataset_id,
            callback_season=2023,
            signature=_D2_SIG,
        )


def test_source_requires_persisted_server_issuer_record(tmp_path: Path) -> None:
    source_root = tmp_path / "issuer-required"
    try:
        entry = _publish_neutral_source(source_root, "mlb-history-v17")
    except SP.SourceAuthorityError as exc:
        pytest.fail(f"{_D2_SIG} Stage A rejected a neutral physical label before issuer verification: {exc}")

    assert "issuerRecordSha256" not in entry, (
        f"{_D2_SIG} physical staging improperly minted server issuer authority"
    )
    assert not (source_root / "issuer-records").exists()
    _require_missing_issuer_rejected(source_root, "mlb-history-v17")
    _require_silver_rejected(
        silver_root=tmp_path / "issuer-required-silver",
        source_root=source_root,
        dataset_id="mlb-history-v17",
        callback_season=2023,
        signature=_D2_SIG,
    )


def test_forged_issuer_record_reference_is_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "forged-reference"
    dataset_id = "mlb-source-2024"
    try:
        _publish_neutral_source(source_root, dataset_id)
    except SP.SourceAuthorityError as exc:
        pytest.fail(f"{_D2_SIG} Stage A rejected a neutral physical label before forged-reference verification: {exc}")
    registry_path, registry = _source_registry(source_root)
    registry["datasets"][dataset_id]["issuerRecordSha256"] = "0" * 64
    registry_path.write_bytes(canonical_json_bytes(registry))

    try:
        SP.resolve_verified_source(source_root, dataset_id)
    except SP.SourceAuthorityError:
        return
    pytest.fail(f"{_D2_SIG} forged issuer-record reference was accepted")


def test_issuer_record_body_is_rehashed_and_relationally_verified(tmp_path: Path) -> None:
    source_root = tmp_path / "forged-body"
    dataset_id = "statcast-curated-a"
    try:
        _publish_neutral_source(source_root, dataset_id)
    except SP.SourceAuthorityError as exc:
        pytest.fail(f"{_D2_SIG} Stage A rejected a neutral physical label before forged-body verification: {exc}")

    claimed_sha = "1" * 64
    issuer_dir = source_root / "issuer-records" / "sha256" / claimed_sha
    issuer_dir.mkdir(parents=True)
    issuer_dir.joinpath("issuer-record.json").write_bytes(
        canonical_json_bytes(
            {
                "issuerRecordContract": "MLB_SILVER_SOURCE_ISSUER_V1",
                "datasetVersionId": "different-parent",
                "issuerRecordSha256": claimed_sha,
            }
        )
    )
    registry_path, registry = _source_registry(source_root)
    registry["datasets"][dataset_id]["issuerRecordSha256"] = claimed_sha
    registry_path.write_bytes(canonical_json_bytes(registry))

    try:
        SP.resolve_verified_source(source_root, dataset_id)
    except SP.SourceAuthorityError:
        return
    pytest.fail(f"{_D2_SIG} forged issuer-record body was accepted")


def test_source_authority_survives_renaming_only_when_issuer_record_is_unchanged(
    tmp_path: Path,
) -> None:
    # First prove that two issuer-less, nonreserved display labels have the same
    # physical-staging and governed-rejection behavior.  Reserved namespace
    # validation is not itself scientific authority and is deliberately not
    # constrained by this half of the node.
    stage_a: dict[str, dict[str, Any]] = {}
    for index, dataset_id in enumerate(("mlb-history-v17", "mlb-display-history-v17")):
        result = _attempt_source_stage(
            tmp_path / f"rename-{index}",
            dataset_id=dataset_id,
            rows=_rows_2023(),
            callback_season=2023,
        )
        stage_a[dataset_id] = result

    assert all(result["accepted"] for result in stage_a.values()), (
        f"{_D2_SIG} display vocabulary changed neutral Stage-A staging: "
        f"{ {name: value['accepted'] for name, value in stage_a.items()} }"
    )
    logical_addresses = set()
    for dataset_id, result in stage_a.items():
        _assert_truthful_unissued_stage_a(result, [2023])
        logical_addresses.add(result["registry_entry"]["logicalSha256"])
        _require_missing_issuer_rejected(result["source_root"], dataset_id)
        _require_silver_rejected(
            silver_root=tmp_path / f"silver-{dataset_id}",
            source_root=result["source_root"],
            dataset_id=dataset_id,
            callback_season=2023,
            signature=_D2_SIG,
        )
    assert len(logical_addresses) == 1, (
        f"{_D2_SIG} changing a display alias changed the physical/logical identity"
    )

    # The positive same-issuer rename is an abstract Stage-B/C transition in the
    # joint contract: display aliases are trace-only and excluded from lookup.
    # This production node therefore neither prescribes a new display-id API nor
    # turns reserved/official-looking Stage-A labels into scientific authority.
    _, fixture = _runner_issuer_fixture(_D2_SIG)
    traces = [
        item for item in fixture.get("nonAuthoritativeTraceMetadata", [])
        if item.get("canonicalSourceKey") == "original-base-v1"
    ]
    assert len(traces) == 1 and traces[0].get("lookupPermitted") is False
    assert len(set(traces[0].get("displayAliases", []))) >= 2
