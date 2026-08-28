"""Publish the exact 48-feature current Gold evidence without fitting a model."""
from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ..sports_datasets.constants import MANIFEST_SHA as FD1_MANIFEST_SHA
from ..sports_datasets.consumer import (
    SportsDatasetManifestConsumer,
    canonical_json_bytes,
    semantic_manifest_sha,
    sha256_bytes,
)
from ..sports_gold.contracts import GOLD_FEATURES
from ..sports_gold.features import (
    aggregate_pitch_history,
    assemble_gold_frame,
    build_advanced_features,
    feature_quality_report,
    prepare_pa_history,
)
from ..sports_gold.publication import verify_gold
from ..sports_gold.silver_inputs import read_verified_columns, resolve_current_silver
from ..sports_modeling.feature_contract import BATTER_FEATURES, FEATURE_NAMES, PITCHER_FEATURES
from ..sports_modeling.feature_view import _batting_features, _pitching_features, _prior_lookup
from ..sports_silver import silver_publication as silver_publish
from .pipeline import (
    DEVELOPMENT_END,
    ELIGIBLE_START,
    EVIDENCE_END,
    FINAL_OOT_START,
    CurrentStatcastPipelineError,
    _load_json,
    _sha_file,
    _write_json_atomic,
    verify_current_silver,
)


CURRENT_GOLD_CONTRACT = "MLB_CURRENT_STATCAST_GOLD_FEATURE_VIEW_V1"
CURRENT_GOLD_DATASET_ID = "gold-table:gold_mlb_current_pa_v1"


def _whole_number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if math.isfinite(number) and number.is_integer() else None


def _current_paths(silver_root: Path, manifest: Mapping[str, Any], family: str) -> tuple[Path, ...]:
    paths: list[Path] = []
    for receipt in manifest.get("partitions", []):
        item = (receipt.get("objects") or {}).get(family)
        if not isinstance(item, Mapping):
            raise CurrentStatcastPipelineError(f"current Silver receipt lacks {family}")
        path = Path(silver_root) / str(item.get("relativePath") or "")
        if not path.is_file() or _sha_file(path) != item.get("sha256"):
            raise CurrentStatcastPipelineError(f"current Silver {family} object failed verification")
        if int(item.get("rowCount") or 0):
            paths.append(path)
    return tuple(paths)


def _load_current_manifest(silver_root: Path) -> tuple[dict[str, Any], str]:
    verified = verify_current_silver(silver_root)
    manifest = _load_json(Path(verified["manifestPath"]))
    return manifest, str(verified["manifestSha256"])


def _load_dim_player(existing_silver_root: Path) -> tuple[dict[str, str], dict[str, Any]]:
    root = Path(existing_silver_root)
    logical = silver_publish.logical_index(root)
    item = logical["dim_player"]
    registration_sha = str(item["currentRegistrationSha256"])
    registration = silver_publish._load_registration(root, registration_sha)
    manifest_sha = str(registration["publicationManifestSha256"])
    silver_publish.verify_silver_table(root, manifest_sha)
    path = root / "objects" / "sha256" / manifest_sha / "object.parquet"
    table = pq.read_table(path, columns=["canonicalPlayerId", "chadwickKeyUuid", "resolutionStatus"])
    mapping: dict[str, str] = {}
    for row in table.to_pylist():
        if row["resolutionStatus"] != "MATCHED_EXACT":
            continue
        canonical = str(row["canonicalPlayerId"])
        chadwick = str(row["chadwickKeyUuid"])
        if canonical in mapping and mapping[canonical] != chadwick:
            raise CurrentStatcastPipelineError(f"ambiguous canonical player identity: {canonical}")
        mapping[canonical] = chadwick
    return mapping, {
        "registrationSha256": registration_sha,
        "publicationManifestSha256": manifest_sha,
        "mappedPlayerCount": len(mapping),
    }


def _load_player_priors(exchange_root: Path) -> tuple[pa.Table, dict[str, Any]]:
    package = (
        Path(exchange_root)
        / "datasets"
        / "mlb-fd1"
        / f"sha256-{FD1_MANIFEST_SHA}"
    )
    manifest_path = package / "sports-dataset-manifest.json"
    manifest = _load_json(manifest_path)
    SportsDatasetManifestConsumer.validate_manifest_contract(manifest)
    if semantic_manifest_sha(manifest) != FD1_MANIFEST_SHA:
        raise CurrentStatcastPipelineError("FD1 manifest SHA differs before player-prior read")
    paths: list[Path] = []
    lineage: list[dict[str, Any]] = []
    for partition in manifest.get("partitions", []):
        if partition.get("family") != "player_prior":
            continue
        season = int(partition["season"])
        if season > 2025:
            raise CurrentStatcastPipelineError("FD1 player_prior unexpectedly extends beyond 2025")
        path = package / str(partition["package_relative_uri"])
        expected = str(partition["file_sha256"])
        if not path.is_file() or _sha_file(path) != expected:
            raise CurrentStatcastPipelineError(f"FD1 player_prior partition SHA differs: {partition['partition_id']}")
        paths.append(path)
        lineage.append({
            "partitionId": partition["partition_id"],
            "season": season,
            "fileSha256": expected,
            "rowCount": int(partition["row_count"]),
        })
    if not paths:
        raise CurrentStatcastPipelineError("FD1 player_prior partitions are missing")
    columns = [
        "canonical_player_id", "identity_resolution_status", "season", "domain",
        "eligible_from_season", "same_season_predictor_eligible", "metrics_json",
    ]
    table = ds.dataset([str(path) for path in paths], format="parquet").to_table(columns=columns)
    return table, {
        "datasetManifestSha256": FD1_MANIFEST_SHA,
        "family": "player_prior",
        "rowCount": table.num_rows,
        "partitions": lineage,
    }


def _base_target_frame(
    current_pa: pd.DataFrame,
    *,
    canonical_to_chadwick: Mapping[str, str],
    player_prior_table: pa.Table,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dimension = frozenset(str(value) for value in player_prior_table["canonical_player_id"].to_pylist())
    lookup = _prior_lookup(
        player_prior_table,
        dimension_uuids=dimension,
        target_seasons=(2025, 2026),
    )
    rows: list[dict[str, Any]] = []
    coverage: Counter[tuple[int, str, str]] = Counter()
    seen: set[str] = set()
    for source in current_pa.to_dict(orient="records"):
        season = int(source["season"])
        game_date = str(source["gameDate"])
        pa_id = str(source["canonicalPaId"])
        if season not in (2025, 2026) or not game_date.startswith(f"{season}-") or pa_id in seen:
            raise CurrentStatcastPipelineError("current Gold target lineage is invalid or duplicated")
        seen.add(pa_id)
        inning = _whole_number(source.get("inning"))
        outs = _whole_number(source.get("outsBeforePa"))
        top_bottom_raw = str(source.get("inningTopBot") or "").casefold()
        top_bottom = 0 if top_bottom_raw == "top" else 1 if top_bottom_raw == "bot" else None
        base_mask = (
            int(bool(source.get("onFirstOccupiedBeforePa")))
            + 2 * int(bool(source.get("onSecondOccupiedBeforePa")))
            + 4 * int(bool(source.get("onThirdOccupiedBeforePa")))
        )
        bat_score = _whole_number(source.get("batScoreBeforePa"))
        field_score = _whole_number(source.get("fieldScoreBeforePa"))
        if (
            inning is None or inning < 1
            or top_bottom not in (0, 1)
            or outs not in (0, 1, 2)
            or bat_score is None or bat_score < 0
            or field_score is None or field_score < 0
        ):
            raise CurrentStatcastPipelineError(f"current PA lacks exact pre-PA context: {pa_id}")
        batter_canonical = str(source["batterCanonicalPlayerId"])
        pitcher_canonical = str(source["pitcherCanonicalPlayerId"])
        batter_uuid = canonical_to_chadwick.get(batter_canonical)
        pitcher_uuid = canonical_to_chadwick.get(pitcher_canonical)
        if not batter_uuid or not pitcher_uuid:
            raise CurrentStatcastPipelineError(f"current PA lacks exact Chadwick identity: {pa_id}")
        batter_prior = lookup.get((season, batter_uuid, "BATTING"))
        pitcher_prior = lookup.get((season, pitcher_uuid, "PITCHING"))
        coverage[(season, "BATTER", "eligible" if batter_prior else "missing")] += 1
        coverage[(season, "PITCHER", "eligible" if pitcher_prior else "missing")] += 1
        batter_values = _batting_features(batter_prior[2]) if batter_prior else {}
        pitcher_values = _pitching_features(pitcher_prior[2]) if pitcher_prior else {}
        row = {
            "canonicalPaId": pa_id,
            "plate_appearance_id": pa_id,
            "canonicalGameId": str(source["canonicalGameId"]),
            "game_id": str(source["canonicalGameId"]),
            "game_date": game_date,
            "season": season,
            "outcome": str(source["outcome"]),
            "batterCanonicalPlayerId": batter_canonical,
            "pitcherCanonicalPlayerId": pitcher_canonical,
            "context_inning": inning,
            "context_top_bottom": top_bottom,
            "context_outs_before": outs,
            "context_base_mask_before": base_mask,
            "context_batting_score_diff_before": int(bat_score) - int(field_score),
            **{name: batter_values.get(name) for name in BATTER_FEATURES if not name.endswith("_missing")},
            "batter_prior_missing": batter_prior is None,
            **{name: pitcher_values.get(name) for name in PITCHER_FEATURES if not name.endswith("_missing")},
            "pitcher_prior_missing": pitcher_prior is None,
        }
        rows.append(row)
    frame = pd.DataFrame(rows)
    if list(FEATURE_NAMES) != list(GOLD_FEATURES[:22]):
        raise CurrentStatcastPipelineError("accepted Base-22 order differs from Gold contract")
    report: dict[str, Any] = {}
    for season in (2025, 2026):
        report[str(season)] = {
            role.lower(): {
                "eligiblePriorRows": int(coverage[(season, role, "eligible")]),
                "legitimateMissingPriorRows": int(coverage[(season, role, "missing")]),
            }
            for role in ("BATTER", "PITCHER")
        }
    return frame, report


def _parquet_bytes(frame: pd.DataFrame, schema: pa.Schema) -> bytes:
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False, safe=True)
    sink = pa.BufferOutputStream()
    pq.write_table(
        table, sink, compression="zstd", compression_level=9, use_dictionary=False,
        write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


def _write_object(root: Path, data: bytes) -> tuple[str, Path]:
    sha = sha256_bytes(data)
    path = Path(root) / "objects" / "sha256" / f"{sha}.parquet"
    if path.exists():
        if _sha_file(path) != sha:
            raise CurrentStatcastPipelineError("current Gold content-addressed object was modified")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        temp.write_bytes(data)
        os.replace(temp, path)
    return sha, path


def build_current_gold(
    *,
    current_silver_root: Path,
    existing_silver_root: Path,
    existing_gold_root: Path,
    exchange_root: Path,
    output_root: Path,
) -> dict[str, Any]:
    """Build the combined 2023--2026 Gold-48 evidence, with zero model fits."""

    current_manifest, current_manifest_sha = _load_current_manifest(Path(current_silver_root))
    current_pa_paths = _current_paths(Path(current_silver_root), current_manifest, "plate_appearance")
    current_pitch_paths = _current_paths(Path(current_silver_root), current_manifest, "pitch")
    if not current_pa_paths or not current_pitch_paths:
        raise CurrentStatcastPipelineError("current Silver contains no accepted PA/pitch facts")
    current_pa_table = ds.dataset([str(path) for path in current_pa_paths], format="parquet").to_table()
    current_pa = current_pa_table.to_pandas()

    old_pa_handle = resolve_current_silver(Path(existing_silver_root), "fact_statcast_plate_appearance")
    old_pitch_handle = resolve_current_silver(Path(existing_silver_root), "fact_statcast_pitch")
    old_pa_table = read_verified_columns(
        old_pa_handle,
        [
            "canonicalPaId", "canonicalGameId", "gameDate", "mlbamGamePk", "atBatNumber", "season",
            "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "paEvent", "stand", "pThrows",
        ],
        seasons=(2019, 2020, 2021, 2022, 2023, 2024),
    )
    current_history = current_pa_table.select(old_pa_table.column_names).cast(
        old_pa_table.schema,
        safe=True,
    )
    history_pa_table = pa.concat_tables(
        [old_pa_table, current_history],
        promote_options="none",
    )
    pitch_aggregates = aggregate_pitch_history((*old_pitch_handle.child_paths, *current_pitch_paths))
    history = prepare_pa_history(
        history_pa_table,
        pitch_aggregates,
        allowed_seasons=(2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026),
    )

    canonical_to_chadwick, identity_authority = _load_dim_player(Path(existing_silver_root))
    player_priors, prior_authority = _load_player_priors(Path(exchange_root))
    base, prior_coverage = _base_target_frame(
        current_pa,
        canonical_to_chadwick=canonical_to_chadwick,
        player_prior_table=player_priors,
    )
    advanced = build_advanced_features(history, base)
    new_gold = assemble_gold_frame(base, advanced)

    old_verified = verify_gold(Path(existing_gold_root))
    old_table = pq.read_table(old_verified["path"])
    old_gold = old_table.to_pandas()
    old_gold = old_gold[old_gold["season"].isin([2023, 2024])].copy()
    combined = pd.concat([old_gold, new_gold], ignore_index=True, sort=False)
    combined["datasetRole"] = combined["game_date"].map(
        lambda value: "FINAL_OOT" if FINAL_OOT_START <= str(value) <= EVIDENCE_END else "DEVELOPMENT_SELECTION"
    )
    combined = combined.sort_values(
        ["season", "game_date", "game_id", "plate_appearance_id"], kind="mergesort"
    ).reset_index(drop=True)
    if combined["canonicalPaId"].duplicated().any() or combined["plate_appearance_id"].duplicated().any():
        raise CurrentStatcastPipelineError("combined current Gold has duplicate PA identities")
    if tuple(GOLD_FEATURES) != tuple(old_verified["featureNames"]):
        raise CurrentStatcastPipelineError("exact Gold-48 feature order differs")
    if not combined["outcome"].isin([
        "STRIKEOUT", "WALK_HBP_CI", "HOME_RUN", "SINGLE", "DOUBLE", "TRIPLE", "BIP_OUT", "OTHER_REACH"
    ]).all():
        raise CurrentStatcastPipelineError("combined current Gold target is outside the governed class order")
    for name in GOLD_FEATURES:
        numeric = pd.to_numeric(combined[name], errors="coerce")
        finite = numeric.dropna().map(math.isfinite).all()
        if not finite:
            raise CurrentStatcastPipelineError(f"Gold feature contains non-finite values: {name}")

    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    # The frozen Gold V1 Arrow metadata names its old logical content and code
    # revision.  Reuse the physical field contract, never that stale identity.
    schema = old_table.schema.remove_metadata()
    partitions: list[dict[str, Any]] = []
    for season in (2023, 2024, 2025, 2026):
        frame = combined[combined["season"] == season].copy()
        data = _parquet_bytes(frame, schema)
        sha, path = _write_object(output, data)
        partitions.append({
            "season": season,
            "rowCount": len(frame),
            "minimumDate": str(frame["game_date"].min()),
            "maximumDate": str(frame["game_date"].max()),
            "sha256": sha,
            "byteCount": len(data),
            "relativePath": path.relative_to(output).as_posix(),
        })
    quality = feature_quality_report(combined)
    feature_availability = [
        {
            "order": index + 1,
            "feature": name,
            "status": (
                "AVAILABLE_WITH_SOURCE_CHANGE" if index < 5
                else "AVAILABLE_UNCHANGED" if index < 22 or index >= 42
                else "DERIVABLE_POINT_IN_TIME"
            ),
        }
        for index, name in enumerate(GOLD_FEATURES)
    ]
    manifest = {
        "manifestContract": CURRENT_GOLD_CONTRACT,
        "manifestVersion": 1,
        "datasetId": CURRENT_GOLD_DATASET_ID,
        "status": "RESEARCH_ONLY_COMPLETE",
        "modelsFitted": 0,
        "modelPromoted": False,
        "featureCount": 48,
        "featureNames": list(GOLD_FEATURES),
        "featureAvailability": feature_availability,
        "dateCoverage": {"earliestDate": ELIGIBLE_START, "latestDate": EVIDENCE_END},
        "temporalContract": {
            "eligibleEvidence": [ELIGIBLE_START, EVIDENCE_END],
            "developmentSelection": [ELIGIBLE_START, DEVELOPMENT_END],
            "finalOot": [FINAL_OOT_START, EVIDENCE_END],
            "historyCutoff": "source.gameDate < target.gameDate; same-date games excluded",
        },
        "sourceAuthorities": {
            "existingGoldV1": {
                "datasetVersionId": old_verified["datasetVersionId"],
                "logicalContentSha256": old_verified["logicalContentSha256"],
                "reusedSeasons": [2023, 2024],
            },
            "existingSilverPa": old_pa_handle.identity(),
            "existingSilverPitch": old_pitch_handle.identity(),
            "currentSilverManifestSha256": current_manifest_sha,
            "playerIdentity": identity_authority,
            "playerPrior": prior_authority,
        },
        "priorCoverage": prior_coverage,
        "partitions": partitions,
        "rowCount": len(combined),
        "rowsBySeason": {str(int(key)): int(value) for key, value in combined.groupby("season").size().items()},
        "quality": quality,
        "limitations": [
            "2026 rolling histories include regular-season Statcast only; 2025 postseason was not authorized for acquisition.",
            "This is evidence publication only. No model was fitted, scored, calibrated, selected, or promoted.",
        ],
    }
    body = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(body)
    path = output / "publications" / "sha256" / manifest_sha / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != body:
        raise CurrentStatcastPipelineError("current Gold content-addressed manifest differs")
    path.write_bytes(body)
    _write_json_atomic(output / "current.json", {
        "datasetId": CURRENT_GOLD_DATASET_ID,
        "manifestSha256": manifest_sha,
        "manifestRelativePath": path.relative_to(output).as_posix(),
    })
    return {**manifest, "manifestSha256": manifest_sha, "manifestPath": str(path)}


def verify_current_gold(output_root: Path) -> dict[str, Any]:
    root = Path(output_root).resolve()
    locator = _load_json(root / "current.json")
    manifest_sha = str(locator.get("manifestSha256") or "")
    path = root / "publications" / "sha256" / manifest_sha / "manifest.json"
    if not path.is_file() or _sha_file(path) != manifest_sha:
        raise CurrentStatcastPipelineError("current Gold manifest is not content-addressed")
    manifest = _load_json(path)
    if manifest.get("featureNames") != list(GOLD_FEATURES) or manifest.get("featureCount") != 48:
        raise CurrentStatcastPipelineError("current Gold feature order differs")
    rows = 0
    dates: list[str] = []
    for partition in manifest.get("partitions", []):
        object_path = root / str(partition["relativePath"])
        if not object_path.is_file() or _sha_file(object_path) != partition["sha256"]:
            raise CurrentStatcastPipelineError("current Gold partition SHA differs")
        table = pq.read_table(object_path)
        if table.num_rows != int(partition["rowCount"]):
            raise CurrentStatcastPipelineError("current Gold partition row count differs")
        rows += table.num_rows
        dates.extend([str(partition["minimumDate"]), str(partition["maximumDate"])])
    if rows != int(manifest["rowCount"]) or min(dates) != ELIGIBLE_START or max(dates) != EVIDENCE_END:
        raise CurrentStatcastPipelineError("current Gold coverage does not reconcile")
    return {
        "datasetId": manifest["datasetId"],
        "manifestSha256": manifest_sha,
        "rowCount": rows,
        "featureCount": 48,
        "dateCoverage": manifest["dateCoverage"],
        "verified": True,
    }


__all__ = ["build_current_gold", "verify_current_gold"]
