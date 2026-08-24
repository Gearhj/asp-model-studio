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
_D1_SOURCE_ID = "mlb-season-scope-v1"
_D1_SIG = "D1_PATH_INDEPENDENT_SEASON_AUTHORITY:"
_D2_SIG = "D2_CRYPTOGRAPHIC_ISSUER_AUTHORITY:"
_NEUTRAL_IDS = (
    "mlb-history-v17",
    "mlb-source-2024",
    "statcast-curated-a",
    "pa-history-release-1",
)


def _rows_2019() -> list[dict[str, Any]]:
    return F.source_rows(seasons=(2019,), batters=("b1",), per=2)


def _rows_2023() -> list[dict[str, Any]]:
    return F.source_rows(seasons=(2023,), batters=("b1",), per=2)


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
) -> dict[str, Any]:
    """Run the real source and Silver publication boundaries, preserving rejection."""
    source_root = base / "source"
    silver_root = base / "silver"
    try:
        SP.publish_source_object(
            source_root=source_root,
            rows=[dict(row) for row in rows],
            dataset_version_id=dataset_id,
            season_of_row=lambda _row: callback_season,
        )
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
            "accepted": False,
            "error": exc,
            "source_root": source_root,
            "silver_root": silver_root,
        }
    return {
        "accepted": True,
        "entry": entry,
        "verified": verified,
        "source_root": source_root,
        "silver_root": silver_root,
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


# =========================================================================== D1
def test_runtime_root_placement_does_not_disable_season_authority(tmp_path: Path) -> None:
    base = _runtime_case(tmp_path, "placement")
    result = _attempt_silver(
        base,
        dataset_id=_D1_SOURCE_ID,
        rows=_rows_2019(),
        callback_season=2024,
        authorized_seasons=[2024],
    )

    assert not result["accepted"], (
        f"{_D1_SIG} production accepted 2019 solely when the caller-selected source/Silver roots were beneath "
        "the isolated RUNTIME_ROOT"
    )
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
    )
    outside = _attempt_silver(
        tmp_path / "outside",
        dataset_id=_D1_SOURCE_ID,
        rows=rows,
        callback_season=2024,
        authorized_seasons=[2024],
    )

    assert inside["accepted"] == outside["accepted"], (
        f"{_D1_SIG} identical scientific rows/callback/list received different decisions: "
        f"inside accepted={inside['accepted']}, outside accepted={outside['accepted']}"
    )
    assert not inside["accepted"] and not outside["accepted"], (
        f"{_D1_SIG} both placements must reject the unauthorized season"
    )


def test_runtime_root_source_cannot_publish_2019_as_authorized(tmp_path: Path) -> None:
    base = _runtime_case(tmp_path, "unauthorized-2019")
    result = _attempt_silver(
        base,
        dataset_id=_D1_SOURCE_ID,
        rows=_rows_2019(),
        callback_season=2024,
        authorized_seasons=[2024],
    )

    assert not result["accepted"], (
        f"{_D1_SIG} the server-owned 2021-2024 season set did not reject 2019"
    )
    assert not _silver_outputs_exist(base / "silver"), (
        f"{_D1_SIG} an unauthorized season left a Silver object or registry entry"
    )


def test_runtime_root_source_callback_cannot_relabel_2019_as_2024(tmp_path: Path) -> None:
    source_root = _runtime_case(tmp_path, "false-callback") / "source"
    try:
        SP.publish_source_object(
            source_root=source_root,
            rows=_rows_2019(),
            dataset_version_id=_D1_SOURCE_ID,
            season_of_row=lambda _row: 2024,
        )
    except _PRODUCTION_REJECTIONS:
        return
    pytest.fail(f"{_D1_SIG} runtime-root placement caused the false 2024 callback to be ignored")


def test_output_receipt_manifest_and_source_seasons_must_all_agree(tmp_path: Path) -> None:
    base = _runtime_case(tmp_path, "all-season-evidence")
    result = _attempt_silver(
        base,
        dataset_id=_D1_SOURCE_ID,
        rows=_rows_2019(),
        callback_season=2024,
        authorized_seasons=[2024],
    )
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
    result = _attempt_silver(
        tmp_path / "neutral-mint",
        dataset_id="mlb-history-v17",
        rows=_rows_2023(),
        callback_season=2023,
    )
    assert not result["accepted"], (
        f"{_D2_SIG} a neutral caller-created identifier minted governed Silver authority without a server issuer record"
    )


def test_identifier_vocabulary_does_not_determine_issuer_authority(tmp_path: Path) -> None:
    accepted: list[str] = []
    for index, dataset_id in enumerate(_NEUTRAL_IDS):
        result = _attempt_silver(
            tmp_path / f"neutral-{index}",
            dataset_id=dataset_id,
            rows=_rows_2023(),
            callback_season=2023,
        )
        if result["accepted"]:
            accepted.append(dataset_id)

    assert accepted == [], (
        f"{_D2_SIG} identifier vocabulary substituted for issuer authority; caller-minted neutral IDs accepted: "
        f"{accepted}"
    )


def test_source_requires_persisted_server_issuer_record(tmp_path: Path) -> None:
    source_root = tmp_path / "issuer-required"
    try:
        entry = _publish_neutral_source(source_root, "mlb-history-v17")
    except SP.SourceAuthorityError:
        return  # Correct: an issuer-less publication was rejected at the production boundary.

    issuer_sha = entry.get("issuerRecordSha256")
    assert isinstance(issuer_sha, str) and len(issuer_sha) == 64, (
        f"{_D2_SIG} production registered a source without a persisted cryptographic server issuer identity"
    )
    issuer_path = source_root / "issuer-records" / "sha256" / issuer_sha / "issuer-record.json"
    assert issuer_path.is_file(), (
        f"{_D2_SIG} the claimed issuer record is not persisted at its content address"
    )
    issuer = json.loads(issuer_path.read_bytes())
    body = {key: value for key, value in issuer.items() if key != "issuerRecordSha256"}
    assert issuer.get("issuerRecordSha256") == sha256_bytes(canonical_json_bytes(body)) == issuer_sha, (
        f"{_D2_SIG} persisted issuer record is not self-addressed"
    )


def test_forged_issuer_record_reference_is_rejected(tmp_path: Path) -> None:
    source_root = tmp_path / "forged-reference"
    dataset_id = "mlb-source-2024"
    try:
        _publish_neutral_source(source_root, dataset_id)
    except SP.SourceAuthorityError:
        return
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
    except SP.SourceAuthorityError:
        return

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
    decisions: dict[str, bool] = {}
    for index, dataset_id in enumerate(("mlb-history-v17", "mlb-official-history-v17")):
        try:
            _publish_neutral_source(tmp_path / f"rename-{index}", dataset_id)
        except SP.SourceAuthorityError:
            decisions[dataset_id] = False
        else:
            decisions[dataset_id] = True

    assert len(set(decisions.values())) == 1, (
        f"{_D2_SIG} renaming the same issuer-less scientific source changed authority solely because one display identifier "
        f"contained a reserved vocabulary token: {decisions}"
    )
    assert not any(decisions.values()), (
        f"{_D2_SIG} an unchanged absence of issuer authority must reject both names"
    )
