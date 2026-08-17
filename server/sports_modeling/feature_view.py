from __future__ import annotations

import hashlib
import json
import math
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_datasets.consumer import (
    ManifestValidationError,
    SportsDatasetManifestConsumer,
    ValidatedPackage,
    _validate_resolved_child,
    canonical_json_bytes,
    filesystem_identity,
    sha256_bytes,
    validate_package_relative_uri,
)
from ..sports_identity_bridges.consumer import (
    IdentityBridgeValidationError,
    MlbFd1IdentityBridgeAdapter,
    ValidatedIdentityBridge,
)
from .feature_contract import (
    BATTER_FEATURES,
    BRIDGE_ALIAS_AUTHORITY_SHA,
    BRIDGE_DIMENSION_AUTHORITY_SHA,
    BRIDGE_MANIFEST_SHA,
    EXPECTED_SEASON_ROWS,
    EXPECTED_TOTAL_ROWS,
    FEATURE_CONTRACT_NAME,
    FEATURE_CONTRACT_VERSION,
    FEATURE_NAMES,
    PARENT_MANIFEST_SHA,
    PARENT_PARTITION_AUTHORITY_SHA,
    PITCHER_FEATURES,
    TARGET_SEASONS,
    feature_contract_payload,
    feature_contract_sha,
    feature_schema_sha,
    feature_schema_spec,
)
from .metrics import PA_CLASS_ORDER


FEATURE_VIEW_CONTENT_SCHEMA_VERSION = "MLB_PA_FEATURE_VIEW_CONTENT_V1"
DEFAULT_BATCH_SIZE = 65_536
EXPECTED_PRIOR_COVERAGE: Mapping[tuple[int, str], tuple[int, int]] = {
    (2023, "BATTER"): (169_005, 15_099),
    (2023, "PITCHER"): (159_568, 24_536),
    (2024, "BATTER"): (170_594, 11_855),
    (2024, "PITCHER"): (160_914, 21_535),
    (2025, "BATTER"): (167_720, 15_206),
    (2025, "PITCHER"): (164_678, 18_248),
}

_PA_COLUMNS = (
    "plate_appearance_id",
    "game_id",
    "game_date",
    "season",
    "population_category",
    "strict_population",
    "canonical_identity_resolved",
    "visiting_team_id",
    "home_team_id",
    "batting_team_id",
    "batter_id",
    "pitcher_id",
    "outcome",
    "inning",
    "top_bottom",
    "outs_before",
    "base_mask_before",
    "visiting_score_before",
    "home_score_before",
    "timing_risk_label",
    "target_only_not_pregame_feature",
    "strict_same_game_pregame_eligible",
    "enhanced_research_eligible",
)
_PRIOR_COLUMNS = (
    "canonical_player_id",
    "identity_resolution_status",
    "season",
    "domain",
    "eligible_from_season",
    "same_season_predictor_eligible",
    "metrics_json",
)


class FeatureViewIntegrityError(RuntimeError):
    """Fail-closed error for a feature view that differs from its frozen contract."""


@dataclass(frozen=True)
class BuiltFeatureView:
    table: pa.Table
    contract: dict[str, Any]
    contract_sha: str
    schema_spec: dict[str, Any]
    schema_sha: str
    content_sha: str
    parquet_bytes: bytes
    season_rows: dict[int, int]
    prior_coverage: tuple[dict[str, Any], ...]
    source_partition_ids: tuple[str, ...]

    @property
    def row_count(self) -> int:
        return self.table.num_rows

    @property
    def feature_names(self) -> tuple[str, ...]:
        return FEATURE_NAMES


def _arrow_schema(*, metadata: Mapping[bytes, bytes] | None = None) -> pa.Schema:
    fields = [
        pa.field("plate_appearance_id", pa.string(), nullable=False),
        pa.field("game_id", pa.string(), nullable=False),
        pa.field("game_date", pa.string(), nullable=False),
        pa.field("season", pa.int16(), nullable=False),
        pa.field("outcome", pa.string(), nullable=False),
        pa.field("batter_canonical_player_uuid", pa.string(), nullable=False),
        pa.field("pitcher_canonical_player_uuid", pa.string(), nullable=False),
        pa.field("batter_prior_season", pa.int16(), nullable=True),
        pa.field("batter_prior_eligible_from_season", pa.int16(), nullable=True),
        pa.field("pitcher_prior_season", pa.int16(), nullable=True),
        pa.field("pitcher_prior_eligible_from_season", pa.int16(), nullable=True),
        pa.field("context_inning", pa.int16(), nullable=False),
        pa.field("context_top_bottom", pa.int8(), nullable=False),
        pa.field("context_outs_before", pa.int8(), nullable=False),
        pa.field("context_base_mask_before", pa.int8(), nullable=False),
        pa.field("context_batting_score_diff_before", pa.int16(), nullable=False),
    ]
    for name in BATTER_FEATURES + PITCHER_FEATURES:
        fields.append(
            pa.field(
                name,
                pa.bool_() if name.endswith("_missing") else pa.float64(),
                nullable=not name.endswith("_missing"),
            )
        )
    return pa.schema(fields, metadata=metadata)


def _strict_metrics_json(raw: Any) -> dict[str, int | float | None]:
    if not isinstance(raw, str):
        raise FeatureViewIntegrityError("player_prior metrics_json must be a string")

    def duplicate_guard(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise FeatureViewIntegrityError(f"duplicate player-prior metric key: {key}")
            output[key] = value
        return output

    def reject_constant(value: str) -> None:
        raise FeatureViewIntegrityError(f"non-finite player-prior metric: {value}")

    try:
        parsed = json.loads(
            raw,
            object_pairs_hook=duplicate_guard,
            parse_constant=reject_constant,
        )
    except FeatureViewIntegrityError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise FeatureViewIntegrityError("invalid player_prior metrics_json") from exc
    if not isinstance(parsed, dict):
        raise FeatureViewIntegrityError("player_prior metrics_json root must be an object")
    for key, value in parsed.items():
        if value is None:
            continue
        if (
            not isinstance(key, str)
            or not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or float(value) < 0.0
        ):
            raise FeatureViewIntegrityError("player_prior metrics must be finite non-negative numbers")
    return parsed


def _metric(metrics: Mapping[str, int | float | None], name: str) -> float:
    value = metrics.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise FeatureViewIntegrityError(f"player_prior metric is missing or nonnumeric: {name}")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0.0:
        raise FeatureViewIntegrityError(f"player_prior metric is invalid: {name}")
    return parsed


def _safe_divide(numerator: float, denominator: float) -> float | None:
    if denominator <= 0.0:
        return None
    value = numerator / denominator
    if not math.isfinite(value):
        raise FeatureViewIntegrityError("derived prior rate is non-finite")
    return value


def _batting_features(metrics: Mapping[str, int | float | None]) -> dict[str, float | None]:
    ab = _metric(metrics, "AB")
    bb = _metric(metrics, "BB")
    hbp = _metric(metrics, "HBP")
    sf = _metric(metrics, "SF")
    sh = _metric(metrics, "SH")
    hits = _metric(metrics, "H")
    doubles = _metric(metrics, "2B")
    triples = _metric(metrics, "3B")
    home_runs = _metric(metrics, "HR")
    strikeouts = _metric(metrics, "SO")
    plate_appearances = ab + bb + hbp + sf + sh
    return {
        "batter_log1p_pa": math.log1p(plate_appearances),
        "batter_avg": _safe_divide(hits, ab),
        "batter_obp": _safe_divide(hits + bb + hbp, ab + bb + hbp + sf),
        "batter_slg": _safe_divide(hits + doubles + 2.0 * triples + 3.0 * home_runs, ab),
        "batter_so_per_pa": _safe_divide(strikeouts, plate_appearances),
        "batter_bb_hbp_per_pa": _safe_divide(bb + hbp, plate_appearances),
        "batter_hr_per_pa": _safe_divide(home_runs, plate_appearances),
    }


def _pitching_features(metrics: Mapping[str, int | float | None]) -> dict[str, float | None]:
    bfp = _metric(metrics, "BFP")
    ip_outs = _metric(metrics, "IPouts")
    bb = _metric(metrics, "BB")
    hits = _metric(metrics, "H")
    return {
        "pitcher_log1p_bfp": math.log1p(bfp),
        "pitcher_era9": _safe_divide(27.0 * _metric(metrics, "ER"), ip_outs),
        "pitcher_whip": _safe_divide(3.0 * (bb + hits), ip_outs),
        "pitcher_so_per_bfp": _safe_divide(_metric(metrics, "SO"), bfp),
        "pitcher_bb_per_bfp": _safe_divide(bb, bfp),
        "pitcher_hr_per_bfp": _safe_divide(_metric(metrics, "HR"), bfp),
        "pitcher_hbp_per_bfp": _safe_divide(_metric(metrics, "HBP"), bfp),
        "pitcher_gs_per_g": _safe_divide(_metric(metrics, "GS"), _metric(metrics, "G")),
    }


def _require_columns(table: pa.Table, expected: Sequence[str], *, label: str) -> None:
    missing = [name for name in expected if name not in table.column_names]
    if missing:
        raise FeatureViewIntegrityError(f"{label} is missing required columns: {missing}")


def _prior_lookup(
    table: pa.Table,
    *,
    dimension_uuids: frozenset[str],
    target_seasons: Sequence[int],
) -> dict[tuple[int, str, str], tuple[int, int, dict[str, int | float | None]]]:
    _require_columns(table, _PRIOR_COLUMNS, label="player_prior")
    values = table.select(_PRIOR_COLUMNS).to_pydict()
    source_rows: dict[
        tuple[str, str, int], tuple[int, dict[str, int | float | None]]
    ] = {}
    for index in range(table.num_rows):
        canonical = values["canonical_player_id"][index]
        domain = values["domain"][index]
        season = values["season"][index]
        eligible_from = values["eligible_from_season"][index]
        if (
            not isinstance(canonical, str)
            or canonical not in dimension_uuids
            or values["identity_resolution_status"][index] != "EXACT"
        ):
            raise FeatureViewIntegrityError("player_prior canonical identity is not exact in the bridge dimension")
        if domain not in {"BATTING", "PITCHING"}:
            continue
        if (
            not isinstance(season, int)
            or not isinstance(eligible_from, int)
            or eligible_from <= season
            or values["same_season_predictor_eligible"][index] is not False
        ):
            raise FeatureViewIntegrityError("player_prior temporal eligibility is invalid")
        key = (canonical, domain, season)
        if key in source_rows:
            raise FeatureViewIntegrityError("duplicate player_prior canonical/domain/season row")
        source_rows[key] = (eligible_from, _strict_metrics_json(values["metrics_json"][index]))

    lookup: dict[
        tuple[int, str, str], tuple[int, int, dict[str, int | float | None]]
    ] = {}
    by_player_domain: dict[
        tuple[str, str], list[tuple[int, int, dict[str, int | float | None]]]
    ] = {}
    for (canonical, domain, season), (eligible, metrics) in source_rows.items():
        by_player_domain.setdefault((canonical, domain), []).append((season, eligible, metrics))
    for rows in by_player_domain.values():
        rows.sort(key=lambda row: (row[0], row[1]))
    for target in target_seasons:
        for (canonical, domain), rows in by_player_domain.items():
            eligible_rows = [row for row in rows if row[0] <= target - 1 and row[1] <= target]
            if eligible_rows:
                lookup[(target, canonical, domain)] = eligible_rows[-1]
    return lookup


def _logical_content_sha(table: pa.Table, *, contract_sha: str, schema_sha: str) -> str:
    digest = hashlib.sha256()
    digest.update(
        canonical_json_bytes(
            {
                "schemaVersion": FEATURE_VIEW_CONTENT_SCHEMA_VERSION,
                "contractSha256": contract_sha,
                "schemaSha256": schema_sha,
                "rowCount": table.num_rows,
            }
        )
    )
    combined = table.combine_chunks()
    for batch in combined.to_batches(max_chunksize=DEFAULT_BATCH_SIZE):
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, combined.schema.remove_metadata()) as writer:
            writer.write_batch(batch)
        digest.update(sink.getvalue().to_pybytes())
    return digest.hexdigest()


def _parquet_bytes(
    table: pa.Table,
    *,
    code_revision: str,
    content_sha: str,
    contract_sha: str,
    schema_sha: str,
) -> bytes:
    metadata = {
        b"artifactSchemaVersion": FEATURE_VIEW_CONTENT_SCHEMA_VERSION.encode("utf-8"),
        b"codeRevision": code_revision.encode("utf-8"),
        b"contentSha256": content_sha.encode("ascii"),
        b"contractSha256": contract_sha.encode("ascii"),
        b"schemaSha256": schema_sha.encode("ascii"),
    }
    materialized = table.cast(_arrow_schema(metadata=metadata))
    sink = pa.BufferOutputStream()
    pq.write_table(
        materialized,
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=DEFAULT_BATCH_SIZE,
    )
    return sink.getvalue().to_pybytes()


def build_feature_view_from_tables(
    plate_appearance_tables: Sequence[pa.Table],
    player_prior_table: pa.Table,
    *,
    retrosheet_aliases: Mapping[str, str],
    dimension_uuids: frozenset[str],
    code_revision: str,
    expected_season_rows: Mapping[int, int] | None = None,
    expected_prior_coverage: Mapping[tuple[int, str], tuple[int, int]] | None = None,
    source_partition_ids: Sequence[str] = (),
    progress: Any | None = None,
) -> BuiltFeatureView:
    """Pure table-level builder used by both the governed runner and fixtures."""

    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ValueError("code_revision must be a non-empty explicit revision descriptor")
    if not plate_appearance_tables:
        raise FeatureViewIntegrityError("at least one plate_appearance table is required")
    for table in plate_appearance_tables:
        if not isinstance(table, pa.Table):
            raise TypeError("plate_appearance_tables must contain pyarrow Tables")
        _require_columns(table, _PA_COLUMNS, label="plate_appearance")
    if not isinstance(player_prior_table, pa.Table):
        raise TypeError("player_prior_table must be a pyarrow Table")
    if not isinstance(dimension_uuids, frozenset) or not dimension_uuids:
        raise FeatureViewIntegrityError("a non-empty exact bridge dimension is required")
    if not retrosheet_aliases:
        raise FeatureViewIntegrityError("a non-empty exact RETROSHEET alias map is required")

    pa_table = pa.concat_tables(
        [table.select(_PA_COLUMNS) for table in plate_appearance_tables],
        promote_options="none",
    )
    observed_seasons = sorted({int(value) for value in pa_table["season"].to_pylist()})
    target_seasons = tuple(expected_season_rows) if expected_season_rows is not None else tuple(observed_seasons)
    if not target_seasons or any(season not in TARGET_SEASONS for season in target_seasons):
        raise FeatureViewIntegrityError("feature view seasons must be a non-empty subset of 2023-2025")
    prior_lookup = _prior_lookup(
        player_prior_table,
        dimension_uuids=dimension_uuids,
        target_seasons=target_seasons,
    )

    values = pa_table.to_pydict()
    output: dict[str, list[Any]] = {field.name: [] for field in _arrow_schema()}
    seen_pa_ids: set[str] = set()
    season_counts: Counter[int] = Counter()
    coverage = {
        (season, role): {
            "targetSeason": season,
            "role": role,
            "referenceRows": 0,
            "rowsWithEligiblePrior": 0,
            "legitimateMissingPriorRows": 0,
            "unresolvedIdentityRows": 0,
            "ambiguousIdentityRows": 0,
            "multiplyMappedIdentityRows": 0,
        }
        for season in target_seasons
        for role in ("BATTER", "PITCHER")
    }
    started = time.monotonic()
    last_emit = started
    for index in range(pa_table.num_rows):
        season = values["season"][index]
        pa_id = values["plate_appearance_id"][index]
        game_id = values["game_id"][index]
        game_date = values["game_date"][index]
        outcome = values["outcome"][index]
        if not isinstance(season, int) or season not in target_seasons:
            raise FeatureViewIntegrityError("plate_appearance season is outside the governed view")
        if (
            not isinstance(pa_id, str)
            or not pa_id
            or pa_id in seen_pa_ids
            or not isinstance(game_id, str)
            or not game_id
            or not isinstance(game_date, str)
            or not game_date.startswith(f"{season:04d}-")
        ):
            raise FeatureViewIntegrityError("plate_appearance lineage keys are null, duplicated, or invalid")
        seen_pa_ids.add(pa_id)
        if outcome not in PA_CLASS_ORDER:
            raise FeatureViewIntegrityError("plate_appearance outcome is outside the frozen class order")
        if (
            values["population_category"][index] != "GEN2_PRIMARY_2023_2025"
            or values["strict_population"][index] != "GEN2_STRICT_DEPLOYABLE_RECONSTRUCTION"
            or values["canonical_identity_resolved"][index] is not False
            or values["timing_risk_label"][index] != "RETROSPECTIVE_EVENT_OUTCOME_TIMING_RISK"
            or values["target_only_not_pregame_feature"][index] is not True
            or values["strict_same_game_pregame_eligible"][index] is not False
            or values["enhanced_research_eligible"][index] is not True
        ):
            raise FeatureViewIntegrityError("plate_appearance population or timing evidence differs")

        inning = values["inning"][index]
        top_bottom = values["top_bottom"][index]
        outs_before = values["outs_before"][index]
        base_mask = values["base_mask_before"][index]
        visiting_score = values["visiting_score_before"][index]
        home_score = values["home_score_before"][index]
        if (
            not isinstance(inning, int)
            or inning < 1
            or inning > 14
            or top_bottom not in (0, 1)
            or outs_before not in (0, 1, 2)
            or not isinstance(base_mask, int)
            or base_mask < 0
            or base_mask > 7
            or not isinstance(visiting_score, int)
            or visiting_score < 0
            or not isinstance(home_score, int)
            or home_score < 0
        ):
            raise FeatureViewIntegrityError("pre-terminal plate-appearance state is null or out of range")
        expected_batting_team = (
            values["visiting_team_id"][index]
            if top_bottom == 0
            else values["home_team_id"][index]
        )
        if values["batting_team_id"][index] != expected_batting_team:
            raise FeatureViewIntegrityError("top_bottom convention conflicts with batting_team_id")
        score_difference = (
            visiting_score - home_score if top_bottom == 0 else home_score - visiting_score
        )

        batter_key = values["batter_id"][index]
        pitcher_key = values["pitcher_id"][index]
        batter_uuid = retrosheet_aliases.get(batter_key)
        pitcher_uuid = retrosheet_aliases.get(pitcher_key)
        if (
            not isinstance(batter_key, str)
            or not isinstance(pitcher_key, str)
            or batter_uuid not in dimension_uuids
            or pitcher_uuid not in dimension_uuids
        ):
            raise FeatureViewIntegrityError("plate_appearance identity did not resolve exactly through the bridge")

        batter_prior = prior_lookup.get((season, batter_uuid, "BATTING"))
        pitcher_prior = prior_lookup.get((season, pitcher_uuid, "PITCHING"))
        for role, prior in (("BATTER", batter_prior), ("PITCHER", pitcher_prior)):
            item = coverage[(season, role)]
            item["referenceRows"] += 1
            if prior is None:
                item["legitimateMissingPriorRows"] += 1
            else:
                item["rowsWithEligiblePrior"] += 1
        batter_values = _batting_features(batter_prior[2]) if batter_prior else {}
        pitcher_values = _pitching_features(pitcher_prior[2]) if pitcher_prior else {}

        row = {
            "plate_appearance_id": pa_id,
            "game_id": game_id,
            "game_date": game_date,
            "season": season,
            "outcome": outcome,
            "batter_canonical_player_uuid": batter_uuid,
            "pitcher_canonical_player_uuid": pitcher_uuid,
            "batter_prior_season": batter_prior[0] if batter_prior else None,
            "batter_prior_eligible_from_season": batter_prior[1] if batter_prior else None,
            "pitcher_prior_season": pitcher_prior[0] if pitcher_prior else None,
            "pitcher_prior_eligible_from_season": pitcher_prior[1] if pitcher_prior else None,
            "context_inning": inning,
            "context_top_bottom": top_bottom,
            "context_outs_before": outs_before,
            "context_base_mask_before": base_mask,
            "context_batting_score_diff_before": score_difference,
            **{name: batter_values.get(name) for name in BATTER_FEATURES if not name.endswith("_missing")},
            "batter_prior_missing": batter_prior is None,
            **{name: pitcher_values.get(name) for name in PITCHER_FEATURES if not name.endswith("_missing")},
            "pitcher_prior_missing": pitcher_prior is None,
        }
        for name in output:
            output[name].append(row[name])
        season_counts[season] += 1
        now = time.monotonic()
        if progress is not None and (
            index == 0
            or (index + 1) % 50_000 == 0
            or index + 1 == pa_table.num_rows
            or now - last_emit >= 30.0
        ):
            elapsed = max(now - started, 1e-9)
            progress(
                {
                    "stage": "MATERIALIZING_MLB_PA_FEATURE_VIEW_V1",
                    "rowsProcessed": index + 1,
                    "rowsTotal": pa_table.num_rows,
                    "currentSeason": season,
                    "rowsPerSecond": round((index + 1) / elapsed, 2),
                    "elapsedSeconds": round(elapsed, 2),
                }
            )
            last_emit = now

    if expected_season_rows is not None:
        expected = {int(key): int(value) for key, value in expected_season_rows.items()}
        if dict(sorted(season_counts.items())) != dict(sorted(expected.items())):
            raise FeatureViewIntegrityError(
                f"feature-view season row counts differ: observed={dict(season_counts)} expected={expected}"
            )
    coverage_rows = tuple(coverage[key] for key in sorted(coverage))
    if expected_prior_coverage is not None:
        if set(expected_prior_coverage) != set(coverage):
            raise FeatureViewIntegrityError("eligible-prior coverage keys differ from the frozen authority")
        for key, item in coverage.items():
            expected_eligible, expected_missing = expected_prior_coverage[key]
            if (
                item["rowsWithEligiblePrior"] != expected_eligible
                or item["legitimateMissingPriorRows"] != expected_missing
                or item["referenceRows"] != expected_eligible + expected_missing
                or item["unresolvedIdentityRows"] != 0
                or item["ambiguousIdentityRows"] != 0
                or item["multiplyMappedIdentityRows"] != 0
            ):
                raise FeatureViewIntegrityError(
                    f"eligible-prior coverage differs for target={key[0]} role={key[1]}"
                )
    table = pa.Table.from_pydict(output, schema=_arrow_schema()).sort_by(
        [
            ("season", "ascending"),
            ("game_date", "ascending"),
            ("game_id", "ascending"),
            ("plate_appearance_id", "ascending"),
        ]
    )
    contract = feature_contract_payload()
    contract_digest = feature_contract_sha(contract)
    schema_spec = feature_schema_spec()
    schema_digest = feature_schema_sha()
    content_digest = _logical_content_sha(
        table,
        contract_sha=contract_digest,
        schema_sha=schema_digest,
    )
    parquet = _parquet_bytes(
        table,
        code_revision=code_revision,
        content_sha=content_digest,
        contract_sha=contract_digest,
        schema_sha=schema_digest,
    )
    return BuiltFeatureView(
        table=table,
        contract=contract,
        contract_sha=contract_digest,
        schema_spec=schema_spec,
        schema_sha=schema_digest,
        content_sha=content_digest,
        parquet_bytes=parquet,
        season_rows=dict(sorted(season_counts.items())),
        prior_coverage=coverage_rows,
        source_partition_ids=tuple(sorted(str(value) for value in source_partition_ids)),
    )


def _safe_partition_path(parent: ValidatedPackage, partition: Mapping[str, Any]) -> Path:
    uri = validate_package_relative_uri(partition.get("package_relative_uri"))
    root = parent.package_root.resolve(strict=True)
    candidate = root.joinpath(*PurePosixPath(uri).parts)
    return _validate_resolved_child(root, candidate, logical_uri=uri)


def _read_registered_partitions(
    parent: ValidatedPackage,
    partitions: Sequence[Mapping[str, Any]],
    *,
    columns: Sequence[str],
    progress: Any | None = None,
) -> list[pa.Table]:
    output: list[pa.Table] = []
    ordered = sorted(
        partitions,
        key=lambda value: (
            int(value.get("season", 0)),
            int(value.get("month", 0)),
            str(value.get("package_relative_uri", "")),
        ),
    )
    started = time.monotonic()
    rows_read = 0
    for index, partition in enumerate(ordered):
        path = _safe_partition_path(parent, partition)
        try:
            table = pq.read_table(path, columns=list(columns), use_threads=False)
        except Exception as exc:
            raise FeatureViewIntegrityError(
                f"registered {partition.get('family')} partition could not be read"
            ) from exc
        if table.num_rows != partition.get("row_count"):
            raise FeatureViewIntegrityError("registered partition row count changed after validation")
        output.append(table)
        rows_read += table.num_rows
        if progress is not None:
            progress(
                {
                    "stage": f"READING_{str(partition.get('family', '')).upper()}_PARTITIONS",
                    "partitionsProcessed": index + 1,
                    "partitionsTotal": len(ordered),
                    "rowsProcessed": rows_read,
                    "elapsedSeconds": round(time.monotonic() - started, 2),
                }
            )
    return output


def _bridge_authorities_match(manifest: Mapping[str, Any]) -> bool:
    parent_binding = manifest.get("parent_binding")
    totals = manifest.get("totals")
    return (
        manifest.get("bridge_manifest_sha256") == BRIDGE_MANIFEST_SHA
        and isinstance(parent_binding, Mapping)
        and parent_binding.get("parent_dataset_manifest_sha256") == PARENT_MANIFEST_SHA
        and parent_binding.get("parent_partition_authority_sha256")
        == PARENT_PARTITION_AUTHORITY_SHA
        and isinstance(totals, Mapping)
        and totals.get("alias_authority_sha256") == BRIDGE_ALIAS_AUTHORITY_SHA
        and totals.get("dimension_authority_sha256") == BRIDGE_DIMENSION_AUTHORITY_SHA
    )


def _validate_bindings(
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
) -> None:
    if not isinstance(parent, ValidatedPackage):
        raise TypeError("parent must be an already validated MLB FD1 package")
    if not isinstance(identity_bridge, ValidatedIdentityBridge):
        raise TypeError("identity_bridge must be an already validated MLB FD1 bridge")
    SportsDatasetManifestConsumer.validate_manifest_contract(parent.manifest)
    MlbFd1IdentityBridgeAdapter.validate_manifest_contract(identity_bridge.manifest)
    if (
        parent.manifest.get("manifest_sha256") != PARENT_MANIFEST_SHA
        or parent.partition_authority_sha != PARENT_PARTITION_AUTHORITY_SHA
    ):
        raise FeatureViewIntegrityError("parent dataset authority differs from the frozen contract")
    if not _bridge_authorities_match(identity_bridge.manifest):
        raise FeatureViewIntegrityError("identity bridge authority differs from the frozen contract")
    if filesystem_identity(parent.package_root) != parent.root_identity:
        raise FeatureViewIntegrityError("validated parent package root identity changed")
    if filesystem_identity(identity_bridge.package_root) != identity_bridge.root_identity:
        raise FeatureViewIntegrityError("validated identity bridge root identity changed")


def build_mlb_pa_feature_view_v1(
    parent: ValidatedPackage,
    identity_bridge: ValidatedIdentityBridge,
    *,
    code_revision: str,
    progress: Any | None = None,
) -> BuiltFeatureView:
    """Read only the registered parent partitions needed by the frozen view."""

    _validate_bindings(parent, identity_bridge)
    pa_partitions = [
        item
        for item in parent.partitions
        if item.get("family") == "plate_appearance"
        and item.get("season") in TARGET_SEASONS
    ]
    prior_partitions = [
        item
        for item in parent.partitions
        if item.get("family") == "player_prior"
        and isinstance(item.get("season"), int)
        and int(item["season"]) <= max(TARGET_SEASONS) - 1
    ]
    if not pa_partitions or not prior_partitions:
        raise FeatureViewIntegrityError("registered PA or player-prior partitions are missing")
    pa_tables = _read_registered_partitions(
        parent, pa_partitions, columns=_PA_COLUMNS, progress=progress
    )
    prior_tables = _read_registered_partitions(
        parent, prior_partitions, columns=_PRIOR_COLUMNS, progress=progress
    )
    prior_table = pa.concat_tables(prior_tables, promote_options="none")
    source_partition_ids = [
        str(item["partition_id"]) for item in [*pa_partitions, *prior_partitions]
    ]
    built = build_feature_view_from_tables(
        pa_tables,
        prior_table,
        retrosheet_aliases=identity_bridge.retrosheet_aliases,
        dimension_uuids=identity_bridge.dimension_uuids,
        code_revision=code_revision,
        expected_season_rows=EXPECTED_SEASON_ROWS,
        expected_prior_coverage=EXPECTED_PRIOR_COVERAGE,
        source_partition_ids=source_partition_ids,
        progress=progress,
    )
    if built.row_count != EXPECTED_TOTAL_ROWS:
        raise FeatureViewIntegrityError("feature-view total row count differs")
    return built


__all__ = [
    "BuiltFeatureView",
    "DEFAULT_BATCH_SIZE",
    "EXPECTED_PRIOR_COVERAGE",
    "FEATURE_VIEW_CONTENT_SCHEMA_VERSION",
    "FeatureViewIntegrityError",
    "build_feature_view_from_tables",
    "build_mlb_pa_feature_view_v1",
]
