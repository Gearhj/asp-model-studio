"""Governed point-in-time sufficient statistics beside frozen Current Gold.

The companion publication is evidence only.  It never projects the Gold target,
never exposes FINAL_OOT feature payloads, and contains no estimator, model fit,
score, policy adoption, feature-set registration, or promotion path.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from ..persistence.db import Database, decode_row, json_dumps, now_iso
from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_gold.features import (
    aggregate_pitch_history,
    build_advanced_features_with_sufficient_statistics,
    prepare_pa_history,
)
from ..sports_gold.silver_inputs import read_verified_columns, resolve_current_silver
from ..sports_modeling.feature_view import _metric, _prior_lookup
from .gold import (
    CURRENT_GOLD_DATASET_ID,
    _current_paths,
    _load_current_manifest,
    _load_dim_player,
    _load_player_priors,
    verify_current_gold,
)
from .pipeline import (
    DEVELOPMENT_END,
    EVIDENCE_END,
    FINAL_OOT_START,
    CurrentStatcastPipelineError,
    _load_json,
    _sha_file,
)


CURRENT_SUFFICIENT_STATS_CONTRACT = "MLB_CURRENT_STATCAST_SUFFICIENT_STATS_V1"
CURRENT_SUFFICIENT_STATS_DATASET_ID = (
    "gold-table:gold_mlb_current_pa_sufficient_stats_v1"
)
FINAL_OOT_SEALED = "FINAL_OOT_SEALED"
DEVELOPMENT_MATERIALIZED = "DEVELOPMENT_MATERIALIZED"
UNMATERIALIZED = "UNMATERIALIZED"
HISTORY_CUTOFF = (
    "annual: season <= Y-1 (eligible_from_season <= Y); rolling: "
    "source.gameDate < target.gameDate; same-date games excluded"
)

DEFAULT_CURRENT_SILVER_ROOT = Path(
    r"C:\Users\james\asp-data-staging\mlb-current-statcast-silver-v1"
)
DEFAULT_EXISTING_SILVER_ROOT = Path(
    r"C:\Users\james\asp-data-staging\mlb-silver-v1"
)
DEFAULT_CURRENT_GOLD_ROOT = Path(
    r"C:\Users\james\asp-data-staging\mlb-current-statcast-gold-v1"
)
DEFAULT_EXCHANGE_ROOT = Path(r"C:\Users\james\asp-model-exchange")

GOLD_KEY_COLUMNS = ("canonicalPaId", "datasetRole")
DEVELOPMENT_CONTEXT_COLUMNS = ("game_date", "season")
COMPANION_IDENTITY_COLUMNS = (
    "canonicalPaId",
    *DEVELOPMENT_CONTEXT_COLUMNS,
    "datasetRole",
)
_GOLD_DEVELOPMENT_COLUMNS = (
    *GOLD_KEY_COLUMNS,
    *DEVELOPMENT_CONTEXT_COLUMNS,
    "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId",
    "batter_prior_missing",
    "pitcher_prior_missing",
    "batter_last100_insufficient",
    "batter_last100_whiff_missing",
    "pitcher_last250_insufficient",
    "pitcher_last250_whiff_missing",
    "pitcher_last250_velocity_missing",
    "pitcher_whip",
    "pitcher_gs_per_g",
    "batter_slg",
    "batter_obp",
    "batter_avg",
    "pitcher_last250_avg_fastball_velocity",
    "pitcher_last250_whiff_rate",
    "pitcher_last250_offspeed_usage",
    "pitcher_last250_fastball_usage",
    "pitcher_last250_breaking_usage",
    "batter_last100_whiff_rate",
    "batter_last100_contact_rate",
)

ANNUAL_BATTING_FIELDS: tuple[tuple[str, str], ...] = (
    ("batter_prior_ab", "AB"),
    ("batter_prior_h", "H"),
    ("batter_prior_2b", "2B"),
    ("batter_prior_3b", "3B"),
    ("batter_prior_hr", "HR"),
    ("batter_prior_bb", "BB"),
    ("batter_prior_hbp", "HBP"),
    ("batter_prior_sf", "SF"),
    ("batter_prior_sh", "SH"),
    ("batter_prior_so", "SO"),
)
ANNUAL_PITCHING_FIELDS: tuple[tuple[str, str], ...] = (
    ("pitcher_prior_ipouts", "IPouts"),
    ("pitcher_prior_h", "H"),
    ("pitcher_prior_bb", "BB"),
    ("pitcher_prior_hbp", "HBP"),
    ("pitcher_prior_bfp", "BFP"),
    ("pitcher_prior_g", "G"),
    ("pitcher_prior_gs", "GS"),
)
ELIGIBLE_SEASON_COLUMNS = (
    "batter_prior_eligible_from_season",
    "pitcher_prior_eligible_from_season",
)
ROLLING_INTEGER_COLUMNS = (
    "pitcher_last250_pitch_count",
    "pitcher_last250_swing_count",
    "pitcher_last250_whiff_count",
    "pitcher_last250_fastball_count",
    "pitcher_last250_breaking_count",
    "pitcher_last250_offspeed_count",
    "pitcher_last250_other_or_unclassified_pitch_count",
    "pitcher_last250_fastball_velocity_count",
    "batter_last100_swing_count",
    "batter_last100_whiff_count",
)
FLOAT_COLUMNS = (
    "pitcher_last250_fastball_velocity_sum",
    "pitcher_last250_fastball_velocity_sumsq",
)
INTEGER_COUNT_COLUMNS = tuple(
    [name for name, _ in ANNUAL_BATTING_FIELDS]
    + [name for name, _ in ANNUAL_PITCHING_FIELDS]
    + list(ROLLING_INTEGER_COLUMNS)
)
SUFFICIENT_STATISTIC_COLUMNS = (
    *INTEGER_COUNT_COLUMNS,
    *ELIGIBLE_SEASON_COLUMNS,
    *FLOAT_COLUMNS,
)
ROW_STATE_COLUMNS = ("materialization_status", "materialization_reason")

_HISTORY_PA_COLUMNS = (
    "canonicalPaId",
    "canonicalGameId",
    "gameDate",
    "mlbamGamePk",
    "atBatNumber",
    "season",
    "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId",
    "paEvent",
    "stand",
    "pThrows",
)

_SOURCE_RIGHTS_EXPECTED: dict[str, dict[str, Any]] = {
    "CHADWICK_PERSONS_REGISTER": {
        "registrationId": "sports-dataset-1b58d5d1def2c9b7",
        "status": "USED",
        "allowedUses": [
            "INTERNAL_DERIVED_ANALYTICS",
            "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
            "READ_ONLY_REGISTRATION",
        ],
        "prohibitedUses": [
            "PUBLIC_BULK_DOWNLOAD",
            "PUBLIC_RAW_REDISTRIBUTION",
            "RAW_DATA_RESALE",
            "UNREVIEWED_COMMERCIAL_REDISTRIBUTION",
        ],
        "attribution": (
            "Contains information from the Chadwick Baseball Bureau Persons Register, "
            "which is made available under the ODC Attribution License."
        ),
        "controls": {
            "attribution_required_if_used": True,
            "no_endorsement": True,
            "public_redistribution_authorized_by_package": False,
            "raw_redistribution_authorized_by_package": False,
            "separate_rights_review_required": False,
            "transformation_disclosure_required_if_used": True,
            "unreviewed_commercial_redistribution_authorized_by_package": False,
        },
    },
    "MLB_STATCAST": {
        "registrationId": "sports-dataset-current-statcast-03ca6dab30e760b2",
        "status": "GOVERNED_LOCAL_RESEARCH_ONLY",
        "allowedUses": [
            "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
            "READ_ONLY_REGISTRATION",
        ],
        "prohibitedUses": [
            "PUBLIC_RAW_REDISTRIBUTION",
            "RAW_DATA_RESALE",
            "UNREVIEWED_COMMERCIAL_REDISTRIBUTION",
        ],
        "attribution": (
            "MLB Advanced Media / Baseball Savant Statcast evidence; preserve source attribution."
        ),
        "controls": {
            "commercialRights": "UNCLEAR_REQUIRES_REVIEW",
            "rawRedistribution": "PROHIBITED",
        },
    },
    "SABR_LAHMAN_MODERN_MLB": {
        "registrationId": "sports-dataset-1b58d5d1def2c9b7",
        "status": "USED_MODERN_MLB_ONLY",
        "allowedUses": [
            "INTERNAL_DERIVED_ANALYTICS",
            "LOCAL_PRIVATE_MODEL_DEVELOPMENT",
            "READ_ONLY_REGISTRATION",
        ],
        "prohibitedUses": [
            "PUBLIC_BULK_DOWNLOAD",
            "PUBLIC_RAW_REDISTRIBUTION",
            "RAW_DATA_RESALE",
            "UNREVIEWED_COMMERCIAL_REDISTRIBUTION",
        ],
        "attribution": (
            "Includes data from the SABR Lahman Baseball Database 1871–2025, created "
            "by Sean Lahman and published by SABR, under CC BY-SA 3.0. ASP "
            "transformations are identified separately."
        ),
        "controls": {
            "attribution_required_if_used": True,
            "no_endorsement": True,
            "public_redistribution_authorized_by_package": False,
            "raw_redistribution_authorized_by_package": False,
            "separate_rights_review_required": False,
            "transformation_disclosure_required_if_used": True,
            "unreviewed_commercial_redistribution_authorized_by_package": False,
        },
    },
}

_RIGHTS_CONTRACT = {
    "effectiveStatus": "GOVERNED_LOCAL_RESEARCH_ONLY",
    "allowedUses": ["LOCAL_PRIVATE_MODEL_DEVELOPMENT", "READ_ONLY_REGISTRATION"],
    "prohibitedUses": [
        "PUBLIC_BULK_DOWNLOAD",
        "PUBLIC_RAW_REDISTRIBUTION",
        "RAW_DATA_RESALE",
        "UNREVIEWED_COMMERCIAL_REDISTRIBUTION",
    ],
    "attributionRequired": True,
    "commercialRights": "UNCLEAR_REQUIRES_REVIEW",
    "combinationRule": "INTERSECTION_MOST_RESTRICTIVE_APPLICABLE_SOURCE_AUTHORITY",
    "sourceAuthorities": [
        {
            "rightsControlId": rights_id,
            "status": authority["status"],
            "allowedUses": authority["allowedUses"],
            "prohibitedUses": authority["prohibitedUses"],
            "attribution": authority["attribution"],
            "controls": authority["controls"],
        }
        for rights_id, authority in _SOURCE_RIGHTS_EXPECTED.items()
    ],
}

_GOLD_UPSTREAM_KEYS = (
    "existingGoldV1",
    "existingSilverPa",
    "existingSilverPitch",
    "currentSilverManifestSha256",
    "playerIdentity",
    "playerPrior",
)


def sufficient_statistics_schema() -> pa.Schema:
    fields = [
        pa.field("canonicalPaId", pa.string(), nullable=False),
        pa.field("game_date", pa.date32(), nullable=True),
        pa.field("season", pa.int16(), nullable=True),
        pa.field("datasetRole", pa.string(), nullable=False),
        pa.field("materialization_status", pa.string(), nullable=False),
        pa.field("materialization_reason", pa.string(), nullable=True),
    ]
    fields.extend(pa.field(name, pa.int64(), nullable=True) for name in INTEGER_COUNT_COLUMNS)
    fields.extend(pa.field(name, pa.int16(), nullable=True) for name in ELIGIBLE_SEASON_COLUMNS)
    fields.extend(pa.field(name, pa.float64(), nullable=True) for name in FLOAT_COLUMNS)
    return pa.schema(fields)


def _physical_schema_contract(schema: pa.Schema | None = None) -> list[dict[str, Any]]:
    resolved = schema or sufficient_statistics_schema()
    return [
        {"name": field.name, "physicalType": str(field.type), "nullable": field.nullable}
        for field in resolved
    ]


def _gold_manifest_path(root: Path, manifest_sha256: str) -> Path:
    return Path(root) / "publications" / "sha256" / manifest_sha256 / "manifest.json"


def _gold_locator_manifest_sha(
    root: Path,
    requested_manifest_sha256: str | None,
) -> str:
    """Resolve one current Gold identity without opening a Parquet payload."""

    locator_path = Path(root) / "current.json"
    locator = _load_json(locator_path)
    locator_sha = str(locator.get("manifestSha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", locator_sha):
        raise CurrentStatcastPipelineError("Current Gold locator lacks an exact manifest SHA")
    requested = str(requested_manifest_sha256 or locator_sha)
    if requested != locator_sha:
        raise CurrentStatcastPipelineError(
            "requested Current Gold manifest differs from the authenticated current locator"
        )
    expected_relative = (
        Path("publications") / "sha256" / locator_sha / "manifest.json"
    ).as_posix()
    if locator.get("datasetId") != CURRENT_GOLD_DATASET_ID:
        raise CurrentStatcastPipelineError("Current Gold locator dataset identity differs")
    if str(locator.get("manifestRelativePath") or "") != expected_relative:
        raise CurrentStatcastPipelineError("Current Gold locator manifest path differs")
    return locator_sha


def _gold_snapshot(root: Path, manifest: Mapping[str, Any], manifest_sha256: str) -> dict[str, Any]:
    current = Path(root) / "current.json"
    manifest_path = _gold_manifest_path(root, manifest_sha256)
    return {
        "currentSha256": _sha_file(current),
        "manifestPath": manifest_path.relative_to(root).as_posix(),
        "manifestSha256": _sha_file(manifest_path),
        "partitionSha256": {
            str(item["relativePath"]): _sha_file(Path(root) / str(item["relativePath"]))
            for item in manifest.get("partitions", [])
        },
    }


def _assert_gold_snapshot(root: Path, snapshot: Mapping[str, Any]) -> None:
    if _sha_file(Path(root) / "current.json") != snapshot["currentSha256"]:
        raise CurrentStatcastPipelineError("frozen Current Gold locator changed")
    manifest_path = Path(root) / str(snapshot["manifestPath"])
    if _sha_file(manifest_path) != snapshot["manifestSha256"]:
        raise CurrentStatcastPipelineError("frozen Current Gold manifest changed")
    for relative, expected in dict(snapshot["partitionSha256"]).items():
        if _sha_file(Path(root) / relative) != expected:
            raise CurrentStatcastPipelineError("frozen Current Gold object changed")


def _load_gold_without_target(
    root: Path,
    manifest_sha256: str | None,
) -> tuple[dict[str, Any], str, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    authenticated_sha = _gold_locator_manifest_sha(root, manifest_sha256)
    verified = verify_current_gold(root, authenticated_sha, metadata_only=True)
    manifest_sha = str(verified["manifestSha256"])
    manifest_path = _gold_manifest_path(root, manifest_sha)
    manifest = _load_json(manifest_path)
    if _sha_file(manifest_path) != manifest_sha:
        raise CurrentStatcastPipelineError("Current Gold manifest failed content verification")
    if manifest.get("datasetId") != CURRENT_GOLD_DATASET_ID:
        raise CurrentStatcastPipelineError("Current Gold manifest dataset identity differs")
    snapshot = _gold_snapshot(root, manifest, manifest_sha)
    key_tables: list[pa.Table] = []
    development_tables: list[pa.Table] = []
    for partition in manifest.get("partitions", []):
        object_path = Path(root) / str(partition["relativePath"])
        key_tables.append(pq.read_table(object_path, columns=list(GOLD_KEY_COLUMNS)))
        development_tables.append(
            pq.read_table(
                object_path,
                columns=list(_GOLD_DEVELOPMENT_COLUMNS),
                filters=[("datasetRole", "=", "DEVELOPMENT_SELECTION")],
            )
        )
    if not key_tables:
        raise CurrentStatcastPipelineError("Current Gold has no verified partitions")
    keys = pa.concat_tables(key_tables, promote_options="none").to_pandas()
    development = pa.concat_tables(
        development_tables, promote_options="none"
    ).to_pandas()
    if len(keys) != int(manifest["rowCount"]):
        raise CurrentStatcastPipelineError("Current Gold key projection row count differs")
    if keys["canonicalPaId"].isna().any() or keys["canonicalPaId"].duplicated().any():
        raise CurrentStatcastPipelineError("Current Gold key projection is not one-to-one")
    roles = set(keys["datasetRole"].astype(str))
    if roles != {"DEVELOPMENT_SELECTION", "FINAL_OOT"}:
        raise CurrentStatcastPipelineError(f"Current Gold role authority differs: {sorted(roles)}")
    if len(development) != int((keys["datasetRole"] == "DEVELOPMENT_SELECTION").sum()):
        raise CurrentStatcastPipelineError("development-only Gold projection does not reconcile")
    if (
        development["canonicalPaId"].isna().any()
        or development["canonicalPaId"].duplicated().any()
        or not development["datasetRole"].eq("DEVELOPMENT_SELECTION").all()
        or set(development["canonicalPaId"].astype(str))
        != set(
            keys.loc[
                keys["datasetRole"].eq("DEVELOPMENT_SELECTION"), "canonicalPaId"
            ].astype(str)
        )
    ):
        raise CurrentStatcastPipelineError(
            "development-only Gold identity projection does not reconcile"
        )
    development_dates = pd.to_datetime(development["game_date"], errors="raise")
    development_seasons = pd.to_numeric(development["season"], errors="raise")
    if (
        development_dates.isna().any()
        or development_seasons.isna().any()
        or not (development_dates.dt.year.to_numpy() == development_seasons.to_numpy()).all()
        or development_dates.max() > pd.Timestamp(DEVELOPMENT_END)
    ):
        raise CurrentStatcastPipelineError(
            "development-only Gold date/season authority differs"
        )
    return manifest, manifest_sha, keys, development, snapshot


def _declared_gold_upstream_authorities(
    gold_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    declared = gold_manifest.get("sourceAuthorities")
    if not isinstance(declared, Mapping):
        raise CurrentStatcastPipelineError("Current Gold lacks upstream authority bindings")
    if set(declared) != set(_GOLD_UPSTREAM_KEYS):
        raise CurrentStatcastPipelineError(
            "Current Gold upstream authority set differs from the exact Wave 1 contract"
        )
    current_silver_sha = str(declared.get("currentSilverManifestSha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", current_silver_sha):
        raise CurrentStatcastPipelineError(
            "Current Gold current-Silver authority is not an exact manifest SHA"
        )
    return dict(declared)


def _bind_gold_upstream_authorities(
    gold_manifest: Mapping[str, Any],
    *,
    silver_authority: Mapping[str, Any],
    identity_authority: Mapping[str, Any],
    prior_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Fail closed unless every directly reloaded authority matches Gold exactly."""

    declared = _declared_gold_upstream_authorities(gold_manifest)
    resolved = {
        "existingSilverPa": silver_authority.get("existingSilverPa"),
        "existingSilverPitch": silver_authority.get("existingSilverPitch"),
        "currentSilverManifestSha256": silver_authority.get(
            "currentSilverManifestSha256"
        ),
        "playerIdentity": identity_authority,
        "playerPrior": prior_authority,
    }
    for key, value in resolved.items():
        if canonical_json_bytes(value) != canonical_json_bytes(declared.get(key)):
            raise CurrentStatcastPipelineError(
                f"reloaded upstream authority differs from Current Gold: {key}"
            )
    authority_sha = sha256_bytes(canonical_json_bytes(declared))
    return {
        "authorities": declared,
        "sha256": authority_sha,
        "verifiedExact": True,
        "verification": {
            "existingGoldV1": "AUTHENTICATED_VIA_CURRENT_GOLD_MANIFEST_AND_PARTITIONS",
            "existingSilverPa": "DIRECT_EXACT_MATCH",
            "existingSilverPitch": "DIRECT_EXACT_MATCH",
            "currentSilverManifestSha256": "DIRECT_EXACT_MATCH",
            "playerIdentity": "DIRECT_EXACT_MATCH",
            "playerPrior": "DIRECT_EXACT_MATCH",
        },
    }


def _load_development_history(
    *,
    current_silver_root: Path,
    existing_silver_root: Path,
    current_silver_manifest_sha256: str | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    current_manifest, current_manifest_sha = _load_current_manifest(
        current_silver_root, current_silver_manifest_sha256
    )
    current_pa_paths = _current_paths(current_silver_root, current_manifest, "plate_appearance")
    current_pitch_paths = _current_paths(current_silver_root, current_manifest, "pitch")
    if not current_pa_paths or not current_pitch_paths:
        raise CurrentStatcastPipelineError("current Silver contains no accepted PA/pitch facts")
    old_pa = resolve_current_silver(existing_silver_root, "fact_statcast_plate_appearance")
    old_pitch = resolve_current_silver(existing_silver_root, "fact_statcast_pitch")
    old_pa_table = read_verified_columns(
        old_pa, list(_HISTORY_PA_COLUMNS), seasons=(2019, 2020, 2021, 2022, 2023, 2024)
    )
    current_pa_table = ds.dataset(
        [str(path) for path in current_pa_paths], format="parquet"
    ).to_table(
        columns=list(_HISTORY_PA_COLUMNS),
        filter=ds.field("gameDate") <= pa.scalar(DEVELOPMENT_END),
    )
    current_pa_table = current_pa_table.cast(old_pa_table.schema, safe=True)
    pa_history = pa.concat_tables(
        [old_pa_table, current_pa_table], promote_options="none"
    )
    pitch_aggregates = aggregate_pitch_history(
        (*old_pitch.child_paths, *current_pitch_paths),
        maximum_game_date=DEVELOPMENT_END,
    )
    history = prepare_pa_history(
        pa_history,
        pitch_aggregates,
        allowed_seasons=(2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026),
    )
    if history["gameDate"].max() > pd.Timestamp(DEVELOPMENT_END):
        raise CurrentStatcastPipelineError("FINAL_OOT PA history became accessible")
    return history, {
        "currentSilverManifestSha256": current_manifest_sha,
        "existingSilverPa": old_pa.identity(),
        "existingSilverPitch": old_pitch.identity(),
        "developmentPaRowsRead": int(len(history)),
        "maximumPaHistoryDateRead": history["gameDate"].max().date().isoformat(),
        "finalOotPaRowsRead": 0,
        "finalOotPitchRowsRead": 0,
    }


def _exact_nonnegative_integer(metrics: Mapping[str, Any], name: str) -> int:
    value = _metric(metrics, name)
    if value < 0 or not float(value).is_integer():
        raise CurrentStatcastPipelineError(
            f"player_prior sufficient statistic is not an exact non-negative integer: {name}"
        )
    return int(value)


def _annual_sufficient_statistics(
    development: pd.DataFrame,
    *,
    canonical_to_chadwick: Mapping[str, str],
    player_priors: pa.Table,
) -> pd.DataFrame:
    target_seasons = tuple(sorted(int(value) for value in development["season"].unique()))
    dimension = frozenset(str(value) for value in player_priors["canonical_player_id"].to_pylist())
    lookup = _prior_lookup(
        player_priors,
        dimension_uuids=dimension,
        target_seasons=target_seasons,
    )
    rows: list[dict[str, Any]] = []
    for source in development.to_dict(orient="records"):
        season = int(source["season"])
        row: dict[str, Any] = {}
        for side, identity_column, domain, fields, eligible_column in (
            (
                "batter",
                "batterCanonicalPlayerId",
                "BATTING",
                ANNUAL_BATTING_FIELDS,
                "batter_prior_eligible_from_season",
            ),
            (
                "pitcher",
                "pitcherCanonicalPlayerId",
                "PITCHING",
                ANNUAL_PITCHING_FIELDS,
                "pitcher_prior_eligible_from_season",
            ),
        ):
            canonical = str(source[identity_column])
            chadwick = canonical_to_chadwick.get(canonical)
            if not chadwick:
                raise CurrentStatcastPipelineError(
                    f"development {side} lacks exact Chadwick identity: {canonical}"
                )
            prior = lookup.get((season, chadwick, domain))
            if prior is None:
                row.update({output: None for output, _ in fields})
                row[eligible_column] = None
                continue
            prior_season, eligible_from, metrics = prior
            if prior_season > season - 1 or eligible_from > season:
                raise CurrentStatcastPipelineError("annual sufficient statistic crossed its Y-1 cutoff")
            row.update(
                {
                    output: _exact_nonnegative_integer(metrics, metric)
                    for output, metric in fields
                }
            )
            row[eligible_column] = int(eligible_from)
        rows.append(row)
    return pd.DataFrame(rows, index=development.index)


def _assert_annual_missingness_parity(
    development: pd.DataFrame,
    annual: pd.DataFrame,
) -> None:
    """Prove Gold missing flags and annual component nullness are identical."""

    for side, missing_column, fields, eligible_column in (
        (
            "batter",
            "batter_prior_missing",
            ANNUAL_BATTING_FIELDS,
            "batter_prior_eligible_from_season",
        ),
        (
            "pitcher",
            "pitcher_prior_missing",
            ANNUAL_PITCHING_FIELDS,
            "pitcher_prior_eligible_from_season",
        ),
    ):
        missing = pd.to_numeric(development[missing_column], errors="coerce")
        if missing.isna().any() or not missing.isin([0.0, 1.0]).all():
            raise CurrentStatcastPipelineError(
                f"Current Gold {side} prior-missing flag is not exact"
            )
        columns = [*[name for name, _metric_name in fields], eligible_column]
        nulls = annual[columns].isna()
        if not nulls.all(axis=1).equals(nulls.any(axis=1)):
            raise CurrentStatcastPipelineError(
                f"{side} annual sufficient statistics are partially materialized"
            )
        if not nulls.all(axis=1).equals(missing.eq(1.0)):
            raise CurrentStatcastPipelineError(
                f"{side} annual sufficient-statistic nullness differs from Gold missingness"
            )


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> np.ndarray:
    n = pd.to_numeric(numerator, errors="coerce").to_numpy(dtype=np.float64)
    d = pd.to_numeric(denominator, errors="coerce").to_numpy(dtype=np.float64)
    result = np.full(len(n), np.nan, dtype=np.float64)
    valid = np.isfinite(n) & np.isfinite(d) & (d > 0.0)
    result[valid] = n[valid] / d[valid]
    return result


def _assert_rate_equivalent(
    name: str,
    actual: pd.Series,
    expected: np.ndarray,
) -> float:
    observed = pd.to_numeric(actual, errors="coerce").to_numpy(dtype=np.float64)
    observed_finite = np.isfinite(observed)
    expected_finite = np.isfinite(expected)
    if not np.array_equal(observed_finite, expected_finite):
        raise CurrentStatcastPipelineError(f"{name} NULL parity differs from Current Gold")
    if not bool(expected_finite.any()):
        return 0.0
    error = np.abs(observed[expected_finite] - expected[expected_finite])
    maximum = float(error.max(initial=0.0))
    if maximum > 1e-6:
        raise CurrentStatcastPipelineError(
            f"{name} sufficient-statistic reconstruction differs by {maximum}"
        )
    return maximum


def _equivalence_report(
    development_gold: pd.DataFrame,
    payload: pd.DataFrame,
    recomputed_rolling_rates: pd.DataFrame,
) -> dict[str, Any]:
    frame = pd.concat(
        [development_gold.reset_index(drop=True), payload.reset_index(drop=True)], axis=1
    )
    ab = frame["batter_prior_ab"]
    hits = frame["batter_prior_h"]
    bb = frame["batter_prior_bb"]
    hbp = frame["batter_prior_hbp"]
    sf = frame["batter_prior_sf"]
    doubles = frame["batter_prior_2b"]
    triples = frame["batter_prior_3b"]
    home_runs = frame["batter_prior_hr"]
    ipouts = frame["pitcher_prior_ipouts"]
    pitcher_hits = frame["pitcher_prior_h"]
    pitcher_bb = frame["pitcher_prior_bb"]
    games = frame["pitcher_prior_g"]
    starts = frame["pitcher_prior_gs"]
    pitcher_swings = frame["pitcher_last250_swing_count"]
    pitcher_whiffs = frame["pitcher_last250_whiff_count"]
    pitches = frame["pitcher_last250_pitch_count"]
    batter_swings = frame["batter_last100_swing_count"]
    batter_whiffs = frame["batter_last100_whiff_count"]
    formulas = {
        "pitcher_whip": _safe_ratio(3 * (pitcher_bb + pitcher_hits), ipouts),
        "pitcher_gs_per_g": _safe_ratio(starts, games),
        "batter_avg": _safe_ratio(hits, ab),
        "batter_obp": _safe_ratio(hits + bb + hbp, ab + bb + hbp + sf),
        "batter_slg": _safe_ratio(
            hits + doubles + 2 * triples + 3 * home_runs, ab
        ),
        "pitcher_last250_whiff_rate": _safe_ratio(pitcher_whiffs, pitcher_swings),
        "pitcher_last250_fastball_usage": _safe_ratio(
            frame["pitcher_last250_fastball_count"], pitches
        ),
        "pitcher_last250_breaking_usage": _safe_ratio(
            frame["pitcher_last250_breaking_count"], pitches
        ),
        "pitcher_last250_offspeed_usage": _safe_ratio(
            frame["pitcher_last250_offspeed_count"], pitches
        ),
        "pitcher_last250_avg_fastball_velocity": _safe_ratio(
            frame["pitcher_last250_fastball_velocity_sum"],
            frame["pitcher_last250_fastball_velocity_count"],
        ),
        "batter_last100_whiff_rate": _safe_ratio(batter_whiffs, batter_swings),
        "batter_last100_contact_rate": _safe_ratio(
            batter_swings - batter_whiffs, batter_swings
        ),
    }
    errors = {
        name: _assert_rate_equivalent(name, frame[name], expected)
        for name, expected in formulas.items()
    }
    for name in (
        "pitcher_last250_whiff_rate",
        "pitcher_last250_fastball_usage",
        "pitcher_last250_breaking_usage",
        "pitcher_last250_offspeed_usage",
        "pitcher_last250_avg_fastball_velocity",
        "batter_last100_whiff_rate",
        "batter_last100_contact_rate",
    ):
        errors[f"samePass:{name}"] = _assert_rate_equivalent(
            f"same-pass {name}", frame[name], recomputed_rolling_rates[name].to_numpy()
        )
    return {
        "validatedDevelopmentRows": int(len(frame)),
        "validatedFeatureCount": len(formulas),
        "perFeatureMaximumAbsoluteError": errors,
        "maximumAbsoluteReconstructionError": max(errors.values(), default=0.0),
        "tolerance": 1e-6,
        "pitcherEra9Reconstructed": False,
        "retiredQaFeaturesReconstructed": [
            "batter_obp",
            "batter_last100_contact_rate",
        ],
    }


def _validate_payload_frame(frame: pd.DataFrame) -> pd.DataFrame:
    expected = {
        *GOLD_KEY_COLUMNS,
        *DEVELOPMENT_CONTEXT_COLUMNS,
        *ROW_STATE_COLUMNS,
        *SUFFICIENT_STATISTIC_COLUMNS,
    }
    if set(frame.columns) != expected:
        missing = sorted(expected - set(frame.columns))
        extra = sorted(set(frame.columns) - expected)
        raise CurrentStatcastPipelineError(
            f"sufficient-statistic schema differs; missing={missing}, extra={extra}"
        )
    output = frame.copy()
    if output["canonicalPaId"].isna().any() or output["canonicalPaId"].duplicated().any():
        raise CurrentStatcastPipelineError("companion canonicalPaId is null or duplicated")
    development = output["datasetRole"].eq("DEVELOPMENT_SELECTION")
    final_oot = output["datasetRole"].eq("FINAL_OOT")
    if not (development | final_oot).all():
        raise CurrentStatcastPipelineError("companion contains an unauthorized datasetRole")
    dates = pd.to_datetime(output["game_date"], errors="coerce")
    seasons = pd.to_numeric(output["season"], errors="coerce")
    if (
        dates.loc[development].isna().any()
        or seasons.loc[development].isna().any()
        or not (
            dates.loc[development].dt.year.to_numpy()
            == seasons.loc[development].to_numpy()
        ).all()
        or dates.loc[final_oot].notna().any()
        or seasons.loc[final_oot].notna().any()
    ):
        raise CurrentStatcastPipelineError(
            "development date/season or sealed FINAL_OOT context differs"
        )
    output["game_date"] = dates.dt.date.where(dates.notna(), None)
    output["season"] = seasons.astype("Int16")
    if not output.loc[development, "materialization_status"].eq(DEVELOPMENT_MATERIALIZED).all():
        raise CurrentStatcastPipelineError("development sufficient statistics are not materialized")
    if output.loc[development, "materialization_reason"].notna().any():
        raise CurrentStatcastPipelineError("development materialization reason must be NULL")
    if not output.loc[final_oot, "materialization_status"].eq(UNMATERIALIZED).all():
        raise CurrentStatcastPipelineError("FINAL_OOT rows are not explicitly unmaterialized")
    if not output.loc[final_oot, "materialization_reason"].eq(FINAL_OOT_SEALED).all():
        raise CurrentStatcastPipelineError("FINAL_OOT rows lack the sealing reason")
    oot_allowed_non_null = {
        "canonicalPaId",
        "datasetRole",
        "materialization_status",
        "materialization_reason",
    }
    oot_forbidden = [
        name for name in output.columns if name not in oot_allowed_non_null
    ]
    if output.loc[final_oot, oot_forbidden].notna().any(axis=None):
        raise CurrentStatcastPipelineError(
            "FINAL_OOT row carries fields beyond immutable identity and sealing state"
        )

    for name in INTEGER_COUNT_COLUMNS:
        numeric = pd.to_numeric(output[name], errors="coerce")
        finite = numeric.notna()
        if bool((numeric[finite] < 0).any()) or bool(
            ((numeric[finite] - np.rint(numeric[finite])).abs() > 0.0).any()
        ):
            raise CurrentStatcastPipelineError(f"{name} is not an exact non-negative integer")
        output[name] = numeric.astype("Int64")
    for name in ELIGIBLE_SEASON_COLUMNS:
        numeric = pd.to_numeric(output[name], errors="coerce")
        finite = numeric.notna()
        if bool(((numeric[finite] - np.rint(numeric[finite])).abs() > 0.0).any()):
            raise CurrentStatcastPipelineError(f"{name} is not an exact integer season")
        output[name] = numeric.astype("Int16")
    for name in FLOAT_COLUMNS:
        numeric = pd.to_numeric(output[name], errors="coerce").astype("Float64")
        finite = numeric.dropna().astype(float)
        if bool((~np.isfinite(finite)).any()) or bool((finite < 0.0).any()):
            raise CurrentStatcastPipelineError(f"{name} is not finite and non-negative")
        output[name] = numeric
    if output.loc[final_oot, list(SUFFICIENT_STATISTIC_COLUMNS)].notna().any(axis=None):
        raise CurrentStatcastPipelineError("FINAL_OOT statistic payload became accessible")
    if output.loc[development, list(ROLLING_INTEGER_COLUMNS) + list(FLOAT_COLUMNS)].isna().any(axis=None):
        raise CurrentStatcastPipelineError("development rolling statistic is unexpectedly NULL")

    dev = output.loc[development]
    pitch_total = (
        dev["pitcher_last250_fastball_count"]
        + dev["pitcher_last250_breaking_count"]
        + dev["pitcher_last250_offspeed_count"]
        + dev["pitcher_last250_other_or_unclassified_pitch_count"]
    )
    if not pitch_total.equals(dev["pitcher_last250_pitch_count"]):
        raise CurrentStatcastPipelineError("full pitch-composition invariant failed")
    relations = (
        ("pitcher_last250_whiff_count", "pitcher_last250_swing_count"),
        ("pitcher_last250_swing_count", "pitcher_last250_pitch_count"),
        ("pitcher_last250_fastball_velocity_count", "pitcher_last250_fastball_count"),
        ("batter_last100_whiff_count", "batter_last100_swing_count"),
        ("pitcher_prior_gs", "pitcher_prior_g"),
        ("batter_prior_h", "batter_prior_ab"),
    )
    for lower, upper in relations:
        comparable = dev[[lower, upper]].dropna()
        if bool((comparable[lower] > comparable[upper]).any()):
            raise CurrentStatcastPipelineError(f"sufficient-statistic relation failed: {lower} <= {upper}")
    hit_parts = dev[
        ["batter_prior_2b", "batter_prior_3b", "batter_prior_hr", "batter_prior_h"]
    ].dropna()
    if bool(
        (
            hit_parts["batter_prior_2b"]
            + hit_parts["batter_prior_3b"]
            + hit_parts["batter_prior_hr"]
            > hit_parts["batter_prior_h"]
        ).any()
    ):
        raise CurrentStatcastPipelineError("batting extra-base hit components exceed hits")
    velocity = dev[
        [
            "pitcher_last250_fastball_velocity_count",
            "pitcher_last250_fastball_velocity_sum",
            "pitcher_last250_fastball_velocity_sumsq",
        ]
    ].astype(float)
    zero_velocity = velocity["pitcher_last250_fastball_velocity_count"].eq(0.0)
    if bool(
        (
            velocity.loc[zero_velocity, "pitcher_last250_fastball_velocity_sum"].ne(0.0)
            | velocity.loc[zero_velocity, "pitcher_last250_fastball_velocity_sumsq"].ne(0.0)
        ).any()
    ):
        raise CurrentStatcastPipelineError("zero velocity exposure has nonzero moments")
    positive = velocity["pitcher_last250_fastball_velocity_count"].gt(0.0)
    centered = (
        velocity.loc[positive, "pitcher_last250_fastball_velocity_sumsq"]
        - velocity.loc[positive, "pitcher_last250_fastball_velocity_sum"].pow(2)
        / velocity.loc[positive, "pitcher_last250_fastball_velocity_count"]
    )
    if bool((centered < -1e-7).any()):
        raise CurrentStatcastPipelineError("velocity moments imply negative centered sum of squares")
    return output


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    table = pa.Table.from_pandas(
        frame,
        schema=sufficient_statistics_schema(),
        preserve_index=False,
        safe=True,
    )
    sink = pa.BufferOutputStream()
    pq.write_table(
        table,
        sink,
        compression="zstd",
        compression_level=9,
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=65_536,
    )
    return sink.getvalue().to_pybytes()


def _write_object(root: Path, data: bytes) -> tuple[str, Path]:
    sha = sha256_bytes(data)
    path = Path(root) / "objects" / "sha256" / f"{sha}.parquet"
    if path.exists():
        if _sha_file(path) != sha:
            raise CurrentStatcastPipelineError("companion content-addressed object was modified")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
        temporary.write_bytes(data)
        os.replace(temporary, path)
    return sha, path


def _write_json_atomic_if_changed(path: Path, payload: Mapping[str, Any]) -> bool:
    """Atomically publish mutable locators while making exact reuse write-free."""

    body = canonical_json_bytes(payload)
    if path.is_file() and path.read_bytes() == body:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(body)
    os.replace(temporary, path)
    return True


def _development_counts(frame: pd.DataFrame) -> tuple[dict[str, int], dict[str, int]]:
    development = frame.loc[frame["datasetRole"].eq("DEVELOPMENT_SELECTION")]
    non_null = {
        name: int(development[name].notna().sum()) for name in SUFFICIENT_STATISTIC_COLUMNS
    }
    zero = {
        name: int(pd.to_numeric(development[name], errors="coerce").eq(0).sum())
        for name in SUFFICIENT_STATISTIC_COLUMNS
    }
    return non_null, zero


def build_current_sufficient_stats(
    *,
    current_silver_root: Path = DEFAULT_CURRENT_SILVER_ROOT,
    existing_silver_root: Path = DEFAULT_EXISTING_SILVER_ROOT,
    current_gold_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
    exchange_root: Path = DEFAULT_EXCHANGE_ROOT,
    output_root: Path | None = None,
    current_silver_manifest_sha256: str | None = None,
    current_gold_manifest_sha256: str | None = None,
    publish_current: bool = True,
) -> dict[str, Any]:
    """Build the sealed companion publication with zero target or OOT payload reads."""

    output = Path(output_root or current_gold_root).resolve()
    gold_root = Path(current_gold_root).resolve()
    (
        gold_manifest,
        gold_manifest_sha,
        gold_keys,
        development_gold,
        gold_snapshot,
    ) = _load_gold_without_target(gold_root, current_gold_manifest_sha256)
    declared_upstream = _declared_gold_upstream_authorities(gold_manifest)
    gold_current_silver_sha = str(
        declared_upstream["currentSilverManifestSha256"]
    )
    if (
        current_silver_manifest_sha256 is not None
        and str(current_silver_manifest_sha256) != gold_current_silver_sha
    ):
        raise CurrentStatcastPipelineError(
            "requested Current Silver manifest differs from Current Gold authority"
        )
    history, silver_authority = _load_development_history(
        current_silver_root=Path(current_silver_root),
        existing_silver_root=Path(existing_silver_root),
        current_silver_manifest_sha256=gold_current_silver_sha,
    )
    development_gold = development_gold.reset_index(drop=True)
    target_keys = development_gold[["canonicalPaId"]].copy()
    recomputed_rates, rolling = build_advanced_features_with_sufficient_statistics(
        history, target_keys
    )
    canonical_to_chadwick, identity_authority = _load_dim_player(
        Path(existing_silver_root)
    )
    player_priors, prior_authority = _load_player_priors(Path(exchange_root))
    upstream_authority = _bind_gold_upstream_authorities(
        gold_manifest,
        silver_authority=silver_authority,
        identity_authority=identity_authority,
        prior_authority=prior_authority,
    )
    annual = _annual_sufficient_statistics(
        development_gold,
        canonical_to_chadwick=canonical_to_chadwick,
        player_priors=player_priors,
    )
    _assert_annual_missingness_parity(development_gold, annual)
    development_payload = pd.concat(
        [annual.reset_index(drop=True), rolling.reset_index(drop=True)], axis=1
    ).reindex(columns=list(SUFFICIENT_STATISTIC_COLUMNS))
    equivalence = _equivalence_report(
        development_gold,
        development_payload,
        recomputed_rates.reset_index(drop=True),
    )
    development_payload.insert(
        0, "canonicalPaId", development_gold["canonicalPaId"].astype(str).to_numpy()
    )
    development_payload.insert(
        1,
        "game_date",
        pd.to_datetime(development_gold["game_date"], errors="raise").dt.date.to_numpy(),
    )
    development_payload.insert(
        2,
        "season",
        pd.to_numeric(development_gold["season"], errors="raise").to_numpy(),
    )
    combined = gold_keys.merge(
        development_payload,
        on="canonicalPaId",
        how="left",
        validate="one_to_one",
        sort=False,
    )
    is_development = combined["datasetRole"].eq("DEVELOPMENT_SELECTION")
    combined["materialization_status"] = np.where(
        is_development, DEVELOPMENT_MATERIALIZED, UNMATERIALIZED
    )
    combined["materialization_reason"] = np.where(
        is_development, None, FINAL_OOT_SEALED
    )
    combined = combined[
        [
            *COMPANION_IDENTITY_COLUMNS,
            *ROW_STATE_COLUMNS,
            *SUFFICIENT_STATISTIC_COLUMNS,
        ]
    ]
    combined = _validate_payload_frame(combined)
    development_rows = combined.loc[is_development].sort_values(
        ["season", "game_date", "canonicalPaId"], kind="mergesort"
    ).reset_index(drop=True)
    final_oot_rows = combined.loc[~is_development].sort_values(
        ["canonicalPaId"], kind="mergesort"
    ).reset_index(drop=True)
    combined = pd.concat(
        [development_rows, final_oot_rows], ignore_index=True
    ).reindex(columns=combined.columns)

    output.mkdir(parents=True, exist_ok=True)
    partitions: list[dict[str, Any]] = []
    for season in sorted(int(value) for value in development_rows["season"].unique()):
        partition_frame = development_rows.loc[
            development_rows["season"].eq(season)
        ].copy()
        data = _parquet_bytes(partition_frame)
        object_sha, object_path = _write_object(output, data)
        partitions.append(
            {
                "partitionRole": "DEVELOPMENT_SELECTION",
                "season": season,
                "rowCount": int(len(partition_frame)),
                "developmentRowCount": int(
                    partition_frame["datasetRole"].eq("DEVELOPMENT_SELECTION").sum()
                ),
                "finalOotKeyRowCount": int(
                    partition_frame["datasetRole"].eq("FINAL_OOT").sum()
                ),
                "minimumDate": min(partition_frame["game_date"]).isoformat(),
                "maximumDate": max(partition_frame["game_date"]).isoformat(),
                "sha256": object_sha,
                "byteCount": len(data),
                "relativePath": object_path.relative_to(output).as_posix(),
            }
        )
    if final_oot_rows.empty:
        raise CurrentStatcastPipelineError("Current Gold FINAL_OOT identity partition is empty")
    oot_data = _parquet_bytes(final_oot_rows)
    oot_object_sha, oot_object_path = _write_object(output, oot_data)
    partitions.append(
        {
            "partitionRole": FINAL_OOT_SEALED,
            "season": 2026,
            "rowSeasonMaterialized": False,
            "rowDateMaterialized": False,
            "rowCount": int(len(final_oot_rows)),
            "developmentRowCount": 0,
            "finalOotKeyRowCount": int(len(final_oot_rows)),
            "minimumDate": FINAL_OOT_START,
            "maximumDate": EVIDENCE_END,
            "sha256": oot_object_sha,
            "byteCount": len(oot_data),
            "relativePath": oot_object_path.relative_to(output).as_posix(),
        }
    )
    non_null_counts, zero_counts = _development_counts(combined)
    physical_schema = _physical_schema_contract()
    physical_schema_sha = sha256_bytes(canonical_json_bytes({"fields": physical_schema}))
    validation_evidence = {
        "equivalence": equivalence,
        "compositionInvariant": "PASS_FULL_FOUR_CELL_COMPOSITION",
        "integerDtypes": "PASS_EXACT_PHYSICAL_INT64_AND_INT16",
        "velocityDtypes": "PASS_FLOAT64_NO_ROUNDING_OR_TRUNCATION",
        "annualPointInTime": "LATEST_ELIGIBLE_SEASON_LE_Y_MINUS_1",
        "annualMissingnessParity": "PASS_EXACT_GOLD_PRIOR_MISSING_FLAGS",
        "rollingPointInTime": "STRICT_SOURCE_GAME_DATE_LT_TARGET_GAME_DATE",
        "goldTargetColumnsRead": [],
        "goldOutcomeRowsRead": 0,
        "finalOotPayloadRowsRead": 0,
        "finalOotStatisticRowsComputed": 0,
        "finalOotRowsTransformed": 0,
        "finalOotKeyRowsCarried": int(
            combined["datasetRole"].eq("FINAL_OOT").sum()
        ),
    }
    validation_sha = sha256_bytes(canonical_json_bytes(validation_evidence))
    manifest = {
        "manifestContract": CURRENT_SUFFICIENT_STATS_CONTRACT,
        "manifestVersion": 1,
        "datasetId": CURRENT_SUFFICIENT_STATS_DATASET_ID,
        "status": "COMPANION_EVIDENCE_COMPLETE_NONSELECTABLE",
        "workspaceActivationEligible": False,
        "modelEligible": False,
        "modelsFitted": 0,
        "modelsScored": 0,
        "modelsCalibrated": 0,
        "modelsPromoted": 0,
        "featureSetsRegistered": 0,
        "policiesAdopted": 0,
        "targetColumns": [],
        "rowCount": int(len(combined)),
        "rowsBySeason": {
            str(int(key)): int(value)
            for key, value in development_rows.groupby("season", sort=True).size().items()
        },
        "developmentRowCount": int(is_development.sum()),
        "finalOotKeyRowCount": int((~is_development).sum()),
        "historyCutoff": HISTORY_CUTOFF,
        "sourceAuthorities": {
            "currentGold": {
                "datasetId": gold_manifest["datasetId"],
                "manifestSha256": gold_manifest_sha,
                "featureCount": gold_manifest["featureCount"],
                "keyProjection": list(GOLD_KEY_COLUMNS),
                "developmentProjection": list(_GOLD_DEVELOPMENT_COLUMNS),
                "targetProjection": [],
            },
            "currentSilver": silver_authority,
            "playerIdentity": identity_authority,
            "playerPrior": prior_authority,
            "goldDeclaredUpstream": upstream_authority,
        },
        "physicalSchema": {
            "fields": physical_schema,
            "sha256": physical_schema_sha,
        },
        "sufficientStatisticColumns": list(SUFFICIENT_STATISTIC_COLUMNS),
        "developmentNonNullCounts": non_null_counts,
        "developmentZeroCounts": zero_counts,
        "validationEvidence": validation_evidence,
        "validationEvidenceSha256": validation_sha,
        "rights": _RIGHTS_CONTRACT,
        "finalOot": {
            "startDate": FINAL_OOT_START,
            "endDate": EVIDENCE_END,
            "keyOnly": True,
            "payloadStatus": UNMATERIALIZED,
            "reason": FINAL_OOT_SEALED,
            "rowDateMaterialized": False,
            "rowSeasonMaterialized": False,
            "allowedNonNullRowFields": [
                "canonicalPaId",
                "datasetRole",
                "materialization_status",
                "materialization_reason",
            ],
            "payloadColumnsNull": [
                *DEVELOPMENT_CONTEXT_COLUMNS,
                *SUFFICIENT_STATISTIC_COLUMNS,
            ],
        },
        "partitions": partitions,
        "limitations": [
            "Evidence publication only; Wave 2 estimators are not implemented here.",
            "FINAL_OOT rows carry immutable identity and partition metadata only.",
            "Commercial use or distribution requires explicit rights review.",
        ],
    }
    body = canonical_json_bytes(manifest)
    manifest_sha = sha256_bytes(body)
    manifest_path = (
        output
        / "sufficient-statistics"
        / "publications"
        / "sha256"
        / manifest_sha
        / "manifest.json"
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    if manifest_path.exists():
        if manifest_path.read_bytes() != body:
            raise CurrentStatcastPipelineError(
                "companion content-addressed manifest differs"
            )
    else:
        temporary = manifest_path.with_name(
            f".{manifest_path.name}.tmp-{uuid.uuid4().hex}"
        )
        temporary.write_bytes(body)
        os.replace(temporary, manifest_path)
    _assert_gold_snapshot(gold_root, gold_snapshot)
    if publish_current:
        _write_json_atomic_if_changed(
            output / "current-sufficient-stats.json",
            {
                "datasetId": CURRENT_SUFFICIENT_STATS_DATASET_ID,
                "manifestSha256": manifest_sha,
                "manifestRelativePath": manifest_path.relative_to(output).as_posix(),
            },
        )
    return {
        **manifest,
        "manifestSha256": manifest_sha,
        "manifestPath": str(manifest_path),
        "objectSha256": [item["sha256"] for item in partitions],
        "verified": True,
        "goldImmutability": {
            "verified": True,
            "currentSha256": gold_snapshot["currentSha256"],
            "manifestSha256": gold_snapshot["manifestSha256"],
            "partitionCount": len(gold_snapshot["partitionSha256"]),
        },
    }


def verify_current_sufficient_stats(
    output_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
    manifest_sha256: str | None = None,
    *,
    current_gold_root: Path | None = None,
) -> dict[str, Any]:
    root = Path(output_root).resolve()
    if manifest_sha256 is None:
        locator = _load_json(root / "current-sufficient-stats.json")
        manifest_sha = str(locator.get("manifestSha256") or "")
        expected_relative = (
            Path("sufficient-statistics")
            / "publications"
            / "sha256"
            / manifest_sha
            / "manifest.json"
        ).as_posix()
        if (
            locator.get("datasetId") != CURRENT_SUFFICIENT_STATS_DATASET_ID
            or str(locator.get("manifestRelativePath") or "") != expected_relative
        ):
            raise CurrentStatcastPipelineError("companion current locator differs")
        manifest_path = root / expected_relative
    else:
        manifest_sha = str(manifest_sha256)
        manifest_path = (
            root
            / "sufficient-statistics"
            / "publications"
            / "sha256"
            / manifest_sha
            / "manifest.json"
        )
    if (
        not re.fullmatch(r"[0-9a-f]{64}", manifest_sha)
        or not manifest_path.is_file()
        or _sha_file(manifest_path) != manifest_sha
    ):
        raise CurrentStatcastPipelineError(
            "companion manifest is not content-addressed"
        )
    manifest = _load_json(manifest_path)
    if (
        manifest.get("manifestContract") != CURRENT_SUFFICIENT_STATS_CONTRACT
        or manifest.get("datasetId") != CURRENT_SUFFICIENT_STATS_DATASET_ID
        or manifest.get("targetColumns") != []
        or manifest.get("workspaceActivationEligible") is not False
        or manifest.get("modelEligible") is not False
        or manifest.get("modelsFitted") != 0
        or manifest.get("modelsScored") != 0
        or manifest.get("modelsCalibrated") != 0
        or manifest.get("modelsPromoted") != 0
        or manifest.get("featureSetsRegistered") != 0
        or manifest.get("policiesAdopted") != 0
    ):
        raise CurrentStatcastPipelineError("companion manifest contract differs")
    physical_schema = manifest.get("physicalSchema") or {}
    expected_fields = _physical_schema_contract()
    expected_schema_sha = sha256_bytes(
        canonical_json_bytes({"fields": expected_fields})
    )
    if (
        physical_schema.get("fields") != expected_fields
        or physical_schema.get("sha256") != expected_schema_sha
    ):
        raise CurrentStatcastPipelineError("companion physical dtype manifest differs")
    validation_evidence = manifest.get("validationEvidence") or {}
    if manifest.get("validationEvidenceSha256") != sha256_bytes(
        canonical_json_bytes(validation_evidence)
    ):
        raise CurrentStatcastPipelineError("companion validation evidence checksum differs")
    required_validation = {
        "compositionInvariant": "PASS_FULL_FOUR_CELL_COMPOSITION",
        "integerDtypes": "PASS_EXACT_PHYSICAL_INT64_AND_INT16",
        "velocityDtypes": "PASS_FLOAT64_NO_ROUNDING_OR_TRUNCATION",
        "annualPointInTime": "LATEST_ELIGIBLE_SEASON_LE_Y_MINUS_1",
        "annualMissingnessParity": "PASS_EXACT_GOLD_PRIOR_MISSING_FLAGS",
        "rollingPointInTime": "STRICT_SOURCE_GAME_DATE_LT_TARGET_GAME_DATE",
        "goldTargetColumnsRead": [],
        "goldOutcomeRowsRead": 0,
        "finalOotPayloadRowsRead": 0,
        "finalOotStatisticRowsComputed": 0,
        "finalOotRowsTransformed": 0,
    }
    if any(validation_evidence.get(key) != value for key, value in required_validation.items()):
        raise CurrentStatcastPipelineError("companion sealed validation evidence differs")
    if manifest.get("rights") != _RIGHTS_CONTRACT:
        raise CurrentStatcastPipelineError("companion effective rights contract differs")
    final_oot_contract = manifest.get("finalOot") or {}
    if (
        final_oot_contract.get("keyOnly") is not True
        or final_oot_contract.get("payloadStatus") != UNMATERIALIZED
        or final_oot_contract.get("reason") != FINAL_OOT_SEALED
        or final_oot_contract.get("rowDateMaterialized") is not False
        or final_oot_contract.get("rowSeasonMaterialized") is not False
        or final_oot_contract.get("allowedNonNullRowFields")
        != [
            "canonicalPaId",
            "datasetRole",
            "materialization_status",
            "materialization_reason",
        ]
        or final_oot_contract.get("payloadColumnsNull")
        != [*DEVELOPMENT_CONTEXT_COLUMNS, *SUFFICIENT_STATISTIC_COLUMNS]
    ):
        raise CurrentStatcastPipelineError("companion FINAL_OOT contract differs")
    tables: list[pa.Table] = []
    object_shas: list[str] = []
    partition_identities: set[tuple[str, int]] = set()
    sealed_partition_count = 0
    for partition in manifest.get("partitions", []):
        season = int(partition["season"])
        partition_role = str(partition.get("partitionRole") or "")
        identity = (partition_role, season)
        if identity in partition_identities:
            raise CurrentStatcastPipelineError("companion partition identity is duplicated")
        partition_identities.add(identity)
        object_path = root / str(partition.get("relativePath") or "")
        expected_sha = str(partition.get("sha256") or "")
        if not object_path.is_file() or _sha_file(object_path) != expected_sha:
            raise CurrentStatcastPipelineError("companion partition SHA differs")
        table = pq.read_table(object_path)
        if table.schema.remove_metadata() != sufficient_statistics_schema():
            raise CurrentStatcastPipelineError("companion partition physical dtype differs")
        if table.num_rows != int(partition["rowCount"]):
            raise CurrentStatcastPipelineError("companion partition row count differs")
        partition_roles = table["datasetRole"].to_pylist()
        if partition_roles.count("DEVELOPMENT_SELECTION") != int(
            partition["developmentRowCount"]
        ) or partition_roles.count("FINAL_OOT") != int(
            partition["finalOotKeyRowCount"]
        ):
            raise CurrentStatcastPipelineError("companion partition role counts differ")
        partition_dates = table["game_date"].to_pylist()
        partition_row_seasons = table["season"].to_pylist()
        if partition_role == "DEVELOPMENT_SELECTION":
            if (
                set(partition_roles) != {"DEVELOPMENT_SELECTION"}
                or any(value is None for value in partition_dates)
                or set(partition_row_seasons) != {season}
                or min(partition_dates).isoformat() != partition["minimumDate"]
                or max(partition_dates).isoformat() != partition["maximumDate"]
            ):
                raise CurrentStatcastPipelineError(
                    "companion development partition context differs"
                )
        elif partition_role == FINAL_OOT_SEALED:
            sealed_partition_count += 1
            if (
                set(partition_roles) != {"FINAL_OOT"}
                or any(value is not None for value in partition_dates)
                or any(value is not None for value in partition_row_seasons)
                or partition.get("rowDateMaterialized") is not False
                or partition.get("rowSeasonMaterialized") is not False
                or partition.get("minimumDate") != FINAL_OOT_START
                or partition.get("maximumDate") != EVIDENCE_END
            ):
                raise CurrentStatcastPipelineError(
                    "companion sealed FINAL_OOT partition context differs"
                )
        else:
            raise CurrentStatcastPipelineError("companion partition role differs")
        tables.append(table)
        object_shas.append(expected_sha)
    if not tables:
        raise CurrentStatcastPipelineError("companion publication has no partitions")
    if sealed_partition_count != 1:
        raise CurrentStatcastPipelineError(
            "companion requires exactly one sealed FINAL_OOT key partition"
        )
    frame = pa.concat_tables(tables, promote_options="none").to_pandas()
    _validate_payload_frame(frame)
    if len(frame) != int(manifest["rowCount"]):
        raise CurrentStatcastPipelineError("companion publication row count differs")
    roles = frame["datasetRole"].astype(str)
    if int(roles.eq("DEVELOPMENT_SELECTION").sum()) != int(
        manifest["developmentRowCount"]
    ) or int(roles.eq("FINAL_OOT").sum()) != int(manifest["finalOotKeyRowCount"]):
        raise CurrentStatcastPipelineError("companion publication role counts differ")
    actual_rows_by_season = {
        str(int(key)): int(value)
        for key, value in frame.loc[
            roles.eq("DEVELOPMENT_SELECTION")
        ].groupby("season", sort=True).size().items()
    }
    if actual_rows_by_season != manifest.get("rowsBySeason"):
        raise CurrentStatcastPipelineError("companion season row counts differ")
    non_null_counts, zero_counts = _development_counts(frame)
    if (
        non_null_counts != manifest.get("developmentNonNullCounts")
        or zero_counts != manifest.get("developmentZeroCounts")
    ):
        raise CurrentStatcastPipelineError("companion development field counts differ")
    if validation_evidence.get("finalOotKeyRowsCarried") != int(
        roles.eq("FINAL_OOT").sum()
    ):
        raise CurrentStatcastPipelineError("companion FINAL_OOT key count evidence differs")
    gold_root = Path(current_gold_root or output_root)
    gold_identity = (manifest.get("sourceAuthorities") or {}).get("currentGold") or {}
    gold_manifest_sha = str(gold_identity.get("manifestSha256") or "")
    _gold_locator_manifest_sha(gold_root, gold_manifest_sha)
    verified_gold = verify_current_gold(
        gold_root,
        gold_manifest_sha,
        metadata_only=True,
    )
    if verified_gold["rowCount"] != len(frame):
        raise CurrentStatcastPipelineError("companion and frozen Gold grains differ")
    gold_manifest = _load_json(_gold_manifest_path(gold_root, gold_manifest_sha))
    gold_key_tables = [
        pq.read_table(
            gold_root / str(partition["relativePath"]),
            columns=list(GOLD_KEY_COLUMNS),
        )
        for partition in gold_manifest.get("partitions", [])
    ]
    if not gold_key_tables:
        raise CurrentStatcastPipelineError("authenticated Current Gold has no key projection")
    gold_keys = pa.concat_tables(
        gold_key_tables, promote_options="none"
    ).to_pandas()
    companion_keys = frame[list(GOLD_KEY_COLUMNS)].copy()
    for key_frame in (gold_keys, companion_keys):
        key_frame["canonicalPaId"] = key_frame["canonicalPaId"].astype(str)
        key_frame["datasetRole"] = key_frame["datasetRole"].astype(str)
        key_frame.sort_values(
            ["datasetRole", "canonicalPaId"],
            kind="mergesort",
            inplace=True,
        )
        key_frame.reset_index(drop=True, inplace=True)
    if not companion_keys.equals(gold_keys):
        raise CurrentStatcastPipelineError(
            "companion one-to-one key identity differs from authenticated Current Gold"
        )
    gold_development_tables = [
        pq.read_table(
            gold_root / str(partition["relativePath"]),
            columns=[*GOLD_KEY_COLUMNS, *DEVELOPMENT_CONTEXT_COLUMNS],
            filters=[("datasetRole", "=", "DEVELOPMENT_SELECTION")],
        )
        for partition in gold_manifest.get("partitions", [])
    ]
    gold_development = pa.concat_tables(
        gold_development_tables, promote_options="none"
    ).to_pandas()
    companion_development = frame.loc[
        roles.eq("DEVELOPMENT_SELECTION"),
        [*GOLD_KEY_COLUMNS, *DEVELOPMENT_CONTEXT_COLUMNS],
    ].copy()
    for development_frame in (gold_development, companion_development):
        development_frame["canonicalPaId"] = development_frame[
            "canonicalPaId"
        ].astype(str)
        development_frame["datasetRole"] = development_frame[
            "datasetRole"
        ].astype(str)
        development_frame["game_date"] = pd.to_datetime(
            development_frame["game_date"], errors="raise"
        ).dt.date
        development_frame["season"] = pd.to_numeric(
            development_frame["season"], errors="raise"
        ).astype(np.int64)
        development_frame.sort_values(
            ["season", "game_date", "canonicalPaId"],
            kind="mergesort",
            inplace=True,
        )
        development_frame.reset_index(drop=True, inplace=True)
    if not companion_development.equals(gold_development):
        raise CurrentStatcastPipelineError(
            "companion development date/season identity differs from authenticated Current Gold"
        )
    companion_sources = manifest.get("sourceAuthorities") or {}
    gold_upstream = companion_sources.get("goldDeclaredUpstream") or {}
    declared_gold_upstream = _declared_gold_upstream_authorities(gold_manifest)
    resolved_current_silver = companion_sources.get("currentSilver") or {}
    if (
        gold_upstream.get("authorities") != declared_gold_upstream
        or gold_upstream.get("sha256")
        != sha256_bytes(canonical_json_bytes(declared_gold_upstream))
        or gold_upstream.get("verifiedExact") is not True
        or resolved_current_silver.get("existingSilverPa")
        != declared_gold_upstream["existingSilverPa"]
        or resolved_current_silver.get("existingSilverPitch")
        != declared_gold_upstream["existingSilverPitch"]
        or resolved_current_silver.get("currentSilverManifestSha256")
        != declared_gold_upstream["currentSilverManifestSha256"]
        or companion_sources.get("playerIdentity")
        != declared_gold_upstream["playerIdentity"]
        or companion_sources.get("playerPrior")
        != declared_gold_upstream["playerPrior"]
    ):
        raise CurrentStatcastPipelineError(
            "companion upstream bindings differ from authenticated Current Gold"
        )
    binding_authority = _expected_binding_authority(
        manifest,
        manifest_sha=manifest_sha,
        object_shas=object_shas,
        gold_manifest_sha=gold_manifest_sha,
    )
    return {
        "datasetId": CURRENT_SUFFICIENT_STATS_DATASET_ID,
        "manifestSha256": manifest_sha,
        "manifestPath": str(manifest_path),
        "rowCount": len(frame),
        "developmentRowCount": int(
            frame["datasetRole"].eq("DEVELOPMENT_SELECTION").sum()
        ),
        "finalOotKeyRowCount": int(frame["datasetRole"].eq("FINAL_OOT").sum()),
        "objectSha256": object_shas,
        "physicalSchema": manifest["physicalSchema"],
        "sourceGoldManifestSha256": str(gold_identity["manifestSha256"]),
        "validationEvidence": manifest["validationEvidence"],
        "rights": manifest["rights"],
        "bindingAuthority": binding_authority,
        "verified": True,
    }


def _registration_ids(manifest_sha256: str) -> dict[str, str]:
    suffix = manifest_sha256[:16]
    return {
        "registrationId": f"sports-dataset-sufficient-stats-{suffix}",
        "datasetVersionId": f"{CURRENT_SUFFICIENT_STATS_DATASET_ID}:sha256:{manifest_sha256}",
        "manifestId": f"{CURRENT_SUFFICIENT_STATS_CONTRACT}:sha256:{manifest_sha256}",
        "packageId": f"mlb-current-sufficient-stats-sha256-{manifest_sha256}",
    }


def _authenticate_companion_object_metadata(
    root: Path,
    manifest: Mapping[str, Any],
) -> list[str]:
    """Authenticate objects and Parquet footers without loading any row payload."""

    resolved_root = Path(root).resolve()
    object_shas: list[str] = []
    rows = 0
    for partition in manifest.get("partitions", []):
        relative = str(partition.get("relativePath") or "")
        object_path = (resolved_root / relative).resolve()
        if not object_path.is_relative_to(resolved_root):
            raise CurrentStatcastPipelineError("companion object path escapes its publication root")
        expected_sha = str(partition.get("sha256") or "")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", expected_sha)
            or not object_path.is_file()
            or _sha_file(object_path) != expected_sha
        ):
            raise CurrentStatcastPipelineError("companion partition SHA differs")
        parquet = pq.ParquetFile(object_path)
        if parquet.schema_arrow.remove_metadata() != sufficient_statistics_schema():
            raise CurrentStatcastPipelineError("companion partition physical dtype differs")
        row_count = int(parquet.metadata.num_rows)
        if row_count != int(partition["rowCount"]):
            raise CurrentStatcastPipelineError("companion partition metadata row count differs")
        rows += row_count
        object_shas.append(expected_sha)
    if not object_shas or rows != int(manifest.get("rowCount") or -1):
        raise CurrentStatcastPipelineError("companion object metadata does not reconcile")
    return object_shas


def _binding_authority_checksum_is_valid(authority: Mapping[str, Any]) -> bool:
    unsigned = {
        key: value
        for key, value in authority.items()
        if key not in {"authorityChecksum", "authorityId"}
    }
    checksum = sha256_bytes(canonical_json_bytes(unsigned))
    return (
        authority.get("authorityChecksum") == checksum
        and authority.get("authorityId")
        == f"MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:{checksum}"
    )


def _expected_binding_authority(
    manifest: Mapping[str, Any],
    *,
    manifest_sha: str,
    object_shas: Sequence[str],
    gold_manifest_sha: str,
) -> dict[str, Any]:
    """Reconstruct the complete signed binding from authenticated authorities."""

    gold_upstream = (manifest.get("sourceAuthorities") or {}).get(
        "goldDeclaredUpstream"
    )
    if not isinstance(gold_upstream, Mapping):
        raise CurrentStatcastPipelineError(
            "companion manifest lacks its Gold upstream binding authority"
        )
    upstream_authorities = gold_upstream.get("authorities")
    if not isinstance(upstream_authorities, Mapping):
        raise CurrentStatcastPipelineError(
            "companion manifest lacks exact Gold upstream authorities"
        )
    unsigned = {
        "schemaVersion": "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1",
        "datasetId": CURRENT_SUFFICIENT_STATS_DATASET_ID,
        "manifestContract": CURRENT_SUFFICIENT_STATS_CONTRACT,
        "manifestSha256": manifest_sha,
        "objectSha256": list(object_shas),
        "sourceGoldManifestSha256": gold_manifest_sha,
        "sourceGoldUpstreamAuthoritiesSha256": str(gold_upstream["sha256"]),
        "sourceCurrentSilverManifestSha256": str(
            upstream_authorities["currentSilverManifestSha256"]
        ),
        "physicalSchemaSha256": str(manifest["physicalSchema"]["sha256"]),
        "validationEvidenceSha256": str(manifest["validationEvidenceSha256"]),
        "requiredColumns": list(SUFFICIENT_STATISTIC_COLUMNS),
        "verified": True,
        "integerValidation": True,
        "equivalenceValidation": True,
        "finalOotSealed": True,
        "rightsStatus": str(manifest["rights"]["effectiveStatus"]),
    }
    checksum = sha256_bytes(canonical_json_bytes(unsigned))
    return {
        **unsigned,
        "authorityChecksum": checksum,
        "authorityId": (
            "MLB_SUFFICIENT_STATISTICS_BINDING_AUTHORITY_V1:sha256:"
            f"{checksum}"
        ),
    }


def _source_rights_rows(connection: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rights_id, authority in _SOURCE_RIGHTS_EXPECTED.items():
        row = connection.execute(
            """
            SELECT * FROM sports_dataset_rights
            WHERE registration_id = ? AND rights_control_id = ?
            """,
            (authority["registrationId"], rights_id),
        ).fetchone()
        if row is None:
            raise CurrentStatcastPipelineError(
                f"required source rights registration is missing: {rights_id}"
            )
        source = dict(row)
        try:
            allowed = json.loads(source["allowed_uses_json"])
            prohibited = json.loads(source["prohibited_uses_json"])
            controls = json.loads(source["controls_json"])
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CurrentStatcastPipelineError(
                f"source rights JSON is invalid: {rights_id}"
            ) from exc
        if (
            source.get("status") != authority["status"]
            or allowed != authority["allowedUses"]
            or prohibited != authority["prohibitedUses"]
            or source.get("attribution") != authority["attribution"]
            or not str(source.get("attribution") or "").strip()
            or controls != authority["controls"]
        ):
            raise CurrentStatcastPipelineError(
                f"source rights authority differs: {rights_id}"
            )
        rows.append(source)
    allowed_sets = [set(json.loads(row["allowed_uses_json"])) for row in rows]
    prohibited = sorted(
        set().union(*(set(json.loads(row["prohibited_uses_json"])) for row in rows))
    )
    allowed = sorted(set.intersection(*allowed_sets))
    if allowed != sorted(_RIGHTS_CONTRACT["allowedUses"]) or prohibited != sorted(
        _RIGHTS_CONTRACT["prohibitedUses"]
    ):
        raise CurrentStatcastPipelineError(
            "source rights do not reconcile to the governed effective intersection"
        )
    return rows


_RIGHTS_CHILD_CONTENT_COLUMNS = (
    "rights_control_id",
    "display_name",
    "source_name",
    "status",
    "allowed_uses_json",
    "prohibited_uses_json",
    "attribution",
    "controls_json",
    "metadata_json",
)

_REGISTRATION_LIMITATIONS = (
    (
        "SUFFICIENT_STATS_COMPANION_NO_ACTIVATION",
        "MODELING",
        "Companion evidence is nonselectable and cannot be activated as a modeling dataset.",
    ),
    (
        "SUFFICIENT_STATS_WAVE2_ENGINE_REQUIRED",
        "MODELING",
        "Validated component bindings remain nonexecutable until their Wave 2 estimators exist.",
    ),
    (
        "SUFFICIENT_STATS_COMMERCIAL_RIGHTS_REVIEW_REQUIRED",
        "RIGHTS",
        "Commercial use or distribution requires explicit review of all source authorities.",
    ),
)

_REGISTRATION_CHILD_COLUMNS: dict[str, tuple[str, ...]] = {
    "sports_dataset_partitions": (
        "partition_id",
        "registration_id",
        "family",
        "season",
        "month",
        "logical_uri",
        "row_count",
        "byte_count",
        "minimum_date",
        "maximum_date",
        "schema_id",
        "physical_schema_fingerprint",
        "file_sha",
        "source_key",
        "source_version_id",
        "original_source_logical_identity",
        "checkpoint_lineage_id",
        "governance_checksum",
        "target_eligibility_json",
        "temporal_classification_json",
        "rights_ids_json",
        "physical_schema_json",
    ),
    "sports_dataset_schemas": (
        "registration_id",
        "family",
        "logical_schema_version",
        "compatible_partition_count",
        "physical_variant_count",
        "fields_json",
        "physical_variants_json",
    ),
    "sports_dataset_rights": ("registration_id", *_RIGHTS_CHILD_CONTENT_COLUMNS),
    "sports_dataset_limitations": (
        "registration_id",
        "limitation_id",
        "scope",
        "description",
    ),
}

_REGISTRATION_CHILD_KEYS: dict[str, tuple[str, ...]] = {
    "sports_dataset_partitions": ("partition_id",),
    "sports_dataset_schemas": ("registration_id", "family"),
    "sports_dataset_rights": ("registration_id", "rights_control_id"),
    "sports_dataset_limitations": ("registration_id", "limitation_id"),
}


def _expected_registration_children(
    manifest: Mapping[str, Any],
    *,
    manifest_sha: str,
    identifiers: Mapping[str, str],
    logical_root: str,
    source_rights: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return every immutable child row implied by a companion manifest."""

    registration_id = identifiers["registrationId"]
    rights_ids = [row["rights_control_id"] for row in source_rights]
    schema_fields = manifest["physicalSchema"]["fields"]
    schema_id = f"{CURRENT_SUFFICIENT_STATS_CONTRACT}:schema:v1"
    partition_rows: list[dict[str, Any]] = []
    for partition in manifest["partitions"]:
        season = int(partition["season"])
        partition_role = str(partition["partitionRole"])
        role_token = partition_role.casefold().replace("_", "-")
        partition_rows.append(
            {
                "partition_id": (
                    "mlb-current-sufficient-stats-"
                    f"{season}-{role_token}-{manifest_sha[:16]}"
                ),
                "registration_id": registration_id,
                "family": "sufficient_statistics",
                "season": season,
                "month": None,
                "logical_uri": (
                    f"{logical_root}/role={role_token}/season={season}/"
                    f"object=sha256-{partition['sha256']}.parquet"
                ),
                "row_count": int(partition["rowCount"]),
                "byte_count": int(partition["byteCount"]),
                "minimum_date": partition["minimumDate"],
                "maximum_date": partition["maximumDate"],
                "schema_id": schema_id,
                "physical_schema_fingerprint": manifest["physicalSchema"]["sha256"],
                "file_sha": partition["sha256"],
                "source_key": CURRENT_SUFFICIENT_STATS_CONTRACT,
                "source_version_id": identifiers["datasetVersionId"],
                "original_source_logical_identity": manifest["sourceAuthorities"][
                    "currentGold"
                ]["manifestSha256"],
                "checkpoint_lineage_id": None,
                "governance_checksum": manifest["validationEvidenceSha256"],
                "target_eligibility_json": json_dumps(
                    {
                        "partitionRole": partition_role,
                        "development": (
                            "MATERIALIZED"
                            if partition_role == "DEVELOPMENT_SELECTION"
                            else "NOT_APPLICABLE"
                        ),
                        "finalOot": (
                            "KEY_ONLY_FINAL_OOT_SEALED"
                            if partition_role == FINAL_OOT_SEALED
                            else "NOT_APPLICABLE"
                        ),
                    }
                ),
                "temporal_classification_json": json_dumps(
                    {
                        "historyCutoff": HISTORY_CUTOFF,
                        "partitionMetadataSeason": season,
                        "partitionRole": partition_role,
                        "rowDateMaterialized": partition.get(
                            "rowDateMaterialized", True
                        ),
                        "rowSeasonMaterialized": partition.get(
                            "rowSeasonMaterialized", True
                        ),
                    }
                ),
                "rights_ids_json": json_dumps(rights_ids),
                "physical_schema_json": json_dumps(schema_fields),
            }
        )

    return {
        "sports_dataset_partitions": partition_rows,
        "sports_dataset_schemas": [
            {
                "registration_id": registration_id,
                "family": "sufficient_statistics",
                "logical_schema_version": CURRENT_SUFFICIENT_STATS_CONTRACT,
                "compatible_partition_count": len(manifest["partitions"]),
                "physical_variant_count": 1,
                "fields_json": json_dumps(schema_fields),
                "physical_variants_json": json_dumps(
                    [
                        {
                            "sha256": manifest["physicalSchema"]["sha256"],
                            "partitionCount": len(manifest["partitions"]),
                        }
                    ]
                ),
            }
        ],
        "sports_dataset_rights": [
            {
                "registration_id": registration_id,
                **{
                    column: source[column]
                    for column in _RIGHTS_CHILD_CONTENT_COLUMNS
                },
            }
            for source in source_rights
        ],
        "sports_dataset_limitations": [
            {
                "registration_id": registration_id,
                "limitation_id": limitation_id,
                "scope": scope,
                "description": description,
            }
            for limitation_id, scope, description in _REGISTRATION_LIMITATIONS
        ],
    }


def _registration_child_mismatch(
    connection: Any,
    expected: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str | None:
    """Return the first child table whose exact persisted content differs."""

    for table, expected_rows in expected.items():
        columns = _REGISTRATION_CHILD_COLUMNS[table]
        key_columns = _REGISTRATION_CHILD_KEYS[table]
        registration_id = expected_rows[0]["registration_id"]
        actual_rows = [
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM {table} WHERE registration_id = ?",
                (registration_id,),
            ).fetchall()
        ]

        def indexed(
            rows: Sequence[Mapping[str, Any]],
        ) -> dict[tuple[Any, ...], tuple[Any, ...]]:
            return {
                tuple(row.get(column) for column in key_columns): tuple(
                    row.get(column) for column in columns
                )
                for row in rows
            }

        if len(actual_rows) != len(expected_rows) or indexed(actual_rows) != indexed(
            expected_rows
        ):
            return table
    return None


def _expected_registration_content(
    manifest: Mapping[str, Any],
    *,
    manifest_sha: str,
    identifiers: Mapping[str, str],
    logical_root: str,
    binding_authority: Mapping[str, Any],
    decoded_json: bool,
) -> dict[str, Any]:
    """Return all registrar-owned immutable registration fields."""

    totals = {
        "rows": manifest["rowCount"],
        "bytes": sum(int(item["byteCount"]) for item in manifest["partitions"]),
    }
    seasons = sorted(int(value) for value in manifest["rowsBySeason"])
    evidence_coverage = {
        "developmentRows": manifest["developmentRowCount"],
        "finalOotKeyRows": manifest["finalOotKeyRowCount"],
        "finalOotPayloadRows": 0,
    }
    metadata = {
        "authorityState": "COMPANION_ONLY",
        "workspaceActivationEligible": False,
        "modelEligible": False,
        "bindingAuthority": dict(binding_authority),
        "effectiveRights": manifest["rights"],
        "modelsFitted": 0,
        "modelsScored": 0,
        "modelsPromoted": 0,
        "featureSetsRegistered": 0,
        "policiesAdopted": 0,
        "finalOotPayloadRowsRead": 0,
        "targetRowsRead": 0,
    }
    return {
        "registration_id": identifiers["registrationId"],
        "dataset_id": CURRENT_SUFFICIENT_STATS_DATASET_ID,
        "dataset_version_id": identifiers["datasetVersionId"],
        "manifest_id": identifiers["manifestId"],
        "manifest_sha": manifest_sha,
        "package_id": identifiers["packageId"],
        "sport": "BASEBALL",
        "league": "MLB",
        "evidence_cutoff": DEVELOPMENT_END,
        "published_at": f"{EVIDENCE_END}T23:59:59Z",
        "logical_package_root": logical_root,
        "validation_status": "VALID",
        "rights_status": "GOVERNED_LOCAL_RESEARCH_ONLY",
        "limitation_count": len(_REGISTRATION_LIMITATIONS),
        "active": 0,
        "totals_json": totals if decoded_json else json_dumps(totals),
        "seasons_json": seasons if decoded_json else json_dumps(seasons),
        "evidence_coverage_json": (
            evidence_coverage if decoded_json else json_dumps(evidence_coverage)
        ),
        "metadata_json": metadata if decoded_json else json_dumps(metadata),
    }


def register_current_sufficient_stats(
    database: Database,
    *,
    output_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
    manifest_sha256: str | None = None,
    current_gold_root: Path | None = None,
    registered_by: str,
) -> dict[str, Any]:
    """Register one immutable non-activatable companion and its source rights."""

    verified = verify_current_sufficient_stats(
        output_root,
        manifest_sha256,
        current_gold_root=current_gold_root,
    )
    manifest = _load_json(Path(verified["manifestPath"]))
    manifest_sha = str(verified["manifestSha256"])
    identifiers = _registration_ids(manifest_sha)
    registered_at = now_iso()
    logical_root = (
        "asp://sports-datasets/mlb-current-sufficient-stats/v1/sha256/"
        f"{manifest_sha}"
    )
    limitations = _REGISTRATION_LIMITATIONS
    expected_registration = _expected_registration_content(
        manifest,
        manifest_sha=manifest_sha,
        identifiers=identifiers,
        logical_root=logical_root,
        binding_authority=verified["bindingAuthority"],
        decoded_json=False,
    )
    totals_json = expected_registration["totals_json"]
    seasons_json = expected_registration["seasons_json"]
    evidence_coverage_json = expected_registration["evidence_coverage_json"]
    metadata_json = expected_registration["metadata_json"]
    with database.transaction() as connection:
        source_rights = _source_rights_rows(connection)
        expected_children = _expected_registration_children(
            manifest,
            manifest_sha=manifest_sha,
            identifiers=identifiers,
            logical_root=logical_root,
            source_rights=source_rights,
        )
        existing = connection.execute(
            "SELECT * FROM sports_dataset_registrations WHERE manifest_sha = ?",
            (manifest_sha,),
        ).fetchone()
        if existing is not None:
            existing_row = dict(existing)
            if any(
                existing_row.get(key) != value
                for key, value in expected_registration.items()
            ):
                raise CurrentStatcastPipelineError(
                    "existing companion registration conflicts with immutable identity"
                )
            child_mismatch = _registration_child_mismatch(
                connection, expected_children
            )
            if child_mismatch is not None:
                raise CurrentStatcastPipelineError(
                    "existing companion registration child content conflicts: "
                    f"{child_mismatch}"
                )
            return {
                **identifiers,
                "manifestSha256": manifest_sha,
                "registrationDisposition": "REUSED",
                "writes": 0,
                "active": False,
                "rightsRowCount": len(source_rights),
            }

        connection.execute(
            """
            INSERT INTO sports_dataset_registrations (
              registration_id, dataset_id, dataset_version_id, manifest_id, manifest_sha,
              package_id, sport, league, evidence_cutoff, published_at, logical_package_root,
              validation_status, registered_at, last_validated_at, registered_by, rights_status,
              limitation_count, active, totals_json, seasons_json, evidence_coverage_json, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, 'BASEBALL', 'MLB', ?, ?, ?, 'VALID', ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                identifiers["registrationId"],
                CURRENT_SUFFICIENT_STATS_DATASET_ID,
                identifiers["datasetVersionId"],
                identifiers["manifestId"],
                manifest_sha,
                identifiers["packageId"],
                DEVELOPMENT_END,
                f"{EVIDENCE_END}T23:59:59Z",
                logical_root,
                registered_at,
                registered_at,
                registered_by,
                "GOVERNED_LOCAL_RESEARCH_ONLY",
                len(limitations),
                totals_json,
                seasons_json,
                evidence_coverage_json,
                metadata_json,
            ),
        )
        rights_ids = [row["rights_control_id"] for row in source_rights]
        schema_fields = manifest["physicalSchema"]["fields"]
        for partition in manifest["partitions"]:
            season = int(partition["season"])
            partition_role = str(partition["partitionRole"])
            role_token = partition_role.casefold().replace("_", "-")
            partition_id = (
                "mlb-current-sufficient-stats-"
                f"{season}-{role_token}-{manifest_sha[:16]}"
            )
            connection.execute(
                """
                INSERT INTO sports_dataset_partitions (
                  partition_id, registration_id, family, season, month, logical_uri,
                  row_count, byte_count, minimum_date, maximum_date, schema_id,
                  physical_schema_fingerprint, file_sha, source_key, source_version_id,
                  original_source_logical_identity, checkpoint_lineage_id, governance_checksum,
                  target_eligibility_json, temporal_classification_json, rights_ids_json,
                  physical_schema_json
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    partition_id,
                    identifiers["registrationId"],
                    "sufficient_statistics",
                    season,
                    (
                        f"{logical_root}/role={role_token}/season={season}/"
                        f"object=sha256-{partition['sha256']}.parquet"
                    ),
                    int(partition["rowCount"]),
                    int(partition["byteCount"]),
                    partition["minimumDate"],
                    partition["maximumDate"],
                    f"{CURRENT_SUFFICIENT_STATS_CONTRACT}:schema:v1",
                    manifest["physicalSchema"]["sha256"],
                    partition["sha256"],
                    CURRENT_SUFFICIENT_STATS_CONTRACT,
                    identifiers["datasetVersionId"],
                    manifest["sourceAuthorities"]["currentGold"]["manifestSha256"],
                    None,
                    manifest["validationEvidenceSha256"],
                    json_dumps(
                        {
                            "partitionRole": partition_role,
                            "development": (
                                "MATERIALIZED"
                                if partition_role == "DEVELOPMENT_SELECTION"
                                else "NOT_APPLICABLE"
                            ),
                            "finalOot": (
                                "KEY_ONLY_FINAL_OOT_SEALED"
                                if partition_role == FINAL_OOT_SEALED
                                else "NOT_APPLICABLE"
                            ),
                        }
                    ),
                    json_dumps(
                        {
                            "historyCutoff": HISTORY_CUTOFF,
                            "partitionMetadataSeason": season,
                            "partitionRole": partition_role,
                            "rowDateMaterialized": partition.get(
                                "rowDateMaterialized", True
                            ),
                            "rowSeasonMaterialized": partition.get(
                                "rowSeasonMaterialized", True
                            ),
                        }
                    ),
                    json_dumps(rights_ids),
                    json_dumps(schema_fields),
                ),
            )
        connection.execute(
            """
            INSERT INTO sports_dataset_schemas (
              registration_id, family, logical_schema_version, compatible_partition_count,
              physical_variant_count, fields_json, physical_variants_json
            ) VALUES (?, 'sufficient_statistics', ?, ?, 1, ?, ?)
            """,
            (
                identifiers["registrationId"],
                CURRENT_SUFFICIENT_STATS_CONTRACT,
                len(manifest["partitions"]),
                json_dumps(schema_fields),
                json_dumps(
                    [
                        {
                            "sha256": manifest["physicalSchema"]["sha256"],
                            "partitionCount": len(manifest["partitions"]),
                        }
                    ]
                ),
            ),
        )
        for source in source_rights:
            connection.execute(
                """
                INSERT INTO sports_dataset_rights (
                  registration_id, rights_control_id, display_name, source_name, status,
                  allowed_uses_json, prohibited_uses_json, attribution, controls_json,
                  metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifiers["registrationId"],
                    source["rights_control_id"],
                    source["display_name"],
                    source["source_name"],
                    source["status"],
                    source["allowed_uses_json"],
                    source["prohibited_uses_json"],
                    source["attribution"],
                    source["controls_json"],
                    source["metadata_json"],
                ),
            )
        for limitation_id, scope, description in limitations:
            connection.execute(
                """
                INSERT INTO sports_dataset_limitations (
                  registration_id, limitation_id, scope, description
                ) VALUES (?, ?, ?, ?)
                """,
                (identifiers["registrationId"], limitation_id, scope, description),
            )
    return {
        **identifiers,
        "manifestSha256": manifest_sha,
        "registrationDisposition": "CREATED",
        "writes": 1 + len(manifest["partitions"]) + 1 + len(source_rights) + len(limitations),
        "active": False,
        "rightsRowCount": len(source_rights),
    }


def registered_sufficient_statistics_authority(
    database: Database,
    *,
    expected_gold_manifest_sha256: str,
    output_root: Path = DEFAULT_CURRENT_GOLD_ROOT,
) -> dict[str, Any] | None:
    locator_path = Path(output_root) / "current-sufficient-stats.json"
    if not locator_path.is_file():
        return None
    locator = _load_json(locator_path)
    manifest_sha = str(locator.get("manifestSha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha):
        return None
    expected_relative = (
        Path("sufficient-statistics")
        / "publications"
        / "sha256"
        / manifest_sha
        / "manifest.json"
    ).as_posix()
    if (
        locator.get("datasetId") != CURRENT_SUFFICIENT_STATS_DATASET_ID
        or str(locator.get("manifestRelativePath") or "") != expected_relative
    ):
        return None
    manifest_path = Path(output_root) / expected_relative
    if not manifest_path.is_file() or _sha_file(manifest_path) != manifest_sha:
        return None
    manifest = _load_json(manifest_path)
    if (
        manifest.get("rights") != _RIGHTS_CONTRACT
        or ((manifest.get("sourceAuthorities") or {}).get("currentGold") or {}).get(
            "manifestSha256"
        )
        != expected_gold_manifest_sha256
    ):
        return None
    try:
        object_shas = _authenticate_companion_object_metadata(
            Path(output_root), manifest
        )
    except (CurrentStatcastPipelineError, OSError, ValueError, pa.ArrowException):
        return None
    with database.connection() as connection:
        row = connection.execute(
            """
            SELECT * FROM sports_dataset_registrations
            WHERE dataset_id = ? AND manifest_sha = ? AND validation_status = 'VALID'
            """,
            (CURRENT_SUFFICIENT_STATS_DATASET_ID, manifest_sha),
        ).fetchone()
        if row is None:
            return None
        registration = decode_row(row) or {}
        metadata = registration.get("metadata_json") or {}
        authority = metadata.get("bindingAuthority")
        if not isinstance(authority, Mapping):
            return None
        try:
            source_rights = _source_rights_rows(connection)
            identifiers = _registration_ids(manifest_sha)
            logical_root = (
                "asp://sports-datasets/mlb-current-sufficient-stats/v1/sha256/"
                f"{manifest_sha}"
            )
            expected_binding = _expected_binding_authority(
                manifest,
                manifest_sha=manifest_sha,
                object_shas=object_shas,
                gold_manifest_sha=expected_gold_manifest_sha256,
            )
            expected_registration = _expected_registration_content(
                manifest,
                manifest_sha=manifest_sha,
                identifiers=identifiers,
                logical_root=logical_root,
                binding_authority=expected_binding,
                decoded_json=True,
            )
            expected_children = _expected_registration_children(
                manifest,
                manifest_sha=manifest_sha,
                identifiers=identifiers,
                logical_root=logical_root,
                source_rights=source_rights,
            )
            child_mismatch = _registration_child_mismatch(
                connection, expected_children
            )
        except (CurrentStatcastPipelineError, KeyError, TypeError, ValueError):
            return None
    if (
        any(
            registration.get(key) != value
            for key, value in expected_registration.items()
        )
        or child_mismatch is not None
    ):
        return None
    resolved = dict(authority)
    if resolved != expected_binding or not _binding_authority_checksum_is_valid(resolved):
        return None
    return expected_binding


__all__ = [
    "CURRENT_SUFFICIENT_STATS_CONTRACT",
    "CURRENT_SUFFICIENT_STATS_DATASET_ID",
    "DEFAULT_CURRENT_GOLD_ROOT",
    "FINAL_OOT_SEALED",
    "INTEGER_COUNT_COLUMNS",
    "SUFFICIENT_STATISTIC_COLUMNS",
    "build_current_sufficient_stats",
    "register_current_sufficient_stats",
    "registered_sufficient_statistics_authority",
    "sufficient_statistics_schema",
    "verify_current_sufficient_stats",
]
