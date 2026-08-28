"""Project-scoped Stage 2 review of the existing current Gold publication.

This module is deliberately read-only.  It resolves the exact project dataset
activation, identifies the one Gold publication derived from that immutable
source authority, verifies its content-addressed objects, and profiles the
already-published matrix.  It never acquires data, rebuilds a table, or imports
an estimator.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from ..persistence.db import Database
from ..persistence.sports_forecast_contract import SportsForecastContractStore
from ..sports_datasets.consumer import canonical_json_bytes
from ..sports_datasets.registry import SportsDatasetRegistry
from ..sports_gold.contracts import (
    BATTER_HISTORY_FEATURES,
    GOLD_CLASS_ORDER,
    GOLD_FEATURES,
    MATCHUP_FEATURES,
    PITCHER_HISTORY_FEATURES,
)
from ..sports_modeling.feature_contract import BATTER_FEATURES, PITCHER_FEATURES
from .gold import CURRENT_GOLD_CONTRACT, CURRENT_GOLD_DATASET_ID
from .incremental import CurrentStatcastSyncConfig


REVIEW_SCHEMA_VERSION = "SPORTS_STAGE2_CURRENT_GOLD_REVIEW_V1"
CURRENT_SOURCE_DATASET_ID = "asp.mlb.statcast.current-pa.v1"
REQUIRED_SEASONS = (2023, 2024, 2025, 2026)
SIMULATION_STATE_FIELDS = (
    "context_inning",
    "context_top_bottom",
    "context_outs_before",
    "context_base_mask_before",
    "context_batting_score_diff_before",
)
IDENTIFIER_FIELDS = (
    "canonicalPaId",
    "plate_appearance_id",
    "batterCanonicalPlayerId",
    "pitcherCanonicalPlayerId",
)
GROUPING_FIELDS = ("canonicalGameId", "game_id")
TIME_FIELDS = ("game_date", "season")
MISSINGNESS_INDICATORS = (
    "batter_prior_missing",
    "pitcher_prior_missing",
    "batter_last100_insufficient",
    "batter_last100_whiff_missing",
    "pitcher_last250_insufficient",
    "pitcher_last250_whiff_missing",
    "pitcher_last250_velocity_missing",
    "matchup_batter_hand_missing",
    "matchup_pitcher_hand_missing",
)
REASON_CATEGORIES = (
    "NO_PRIOR_HISTORY",
    "INSUFFICIENT_HISTORY",
    "SOURCE_MISSING",
    "IDENTITY_FAILURE",
    "COMPUTATION_FAILURE",
)
EXPECTED_GOLD_HISTORY_CUTOFF = "source.gameDate < target.gameDate; same-date games excluded"
EXPECTED_SOURCE_HISTORY_CUTOFF = "source.gameDate < target.gameDate; same-date history excluded"
EXPECTED_SOURCE_COVERAGE = ("2023-03-30", "2026-08-27", 702_326)
EXPECTED_GOLD_COVERAGE = ("2023-03-30", "2026-08-27", 697_729)
EXPECTED_DEVELOPMENT = ("2023-03-30", "2026-08-13", 683_662)
EXPECTED_FINAL_OOT = ("2026-08-14", "2026-08-27", 14_067)


class CurrentGoldStage2ReviewError(RuntimeError):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        self.code = code
        self.status_code = status_code
        super().__init__(message)

    def public_detail(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_AUTHORITY_UNAVAILABLE",
            "The linked current Gold authority could not be read.",
            status_code=503,
        ) from exc
    if not isinstance(value, dict):
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_AUTHORITY_INVALID",
            "The linked current Gold authority is malformed.",
        )
    return value


def _gold_root() -> Path:
    configured = os.getenv("ASP_MODEL_STUDIO_CURRENT_GOLD_ROOT", "").strip()
    candidate = Path(configured) if configured else CurrentStatcastSyncConfig().current_gold_root
    return candidate.expanduser().resolve(strict=False)


def _existing_silver_root() -> Path:
    configured = os.getenv("ASP_MODEL_STUDIO_EXISTING_SILVER_ROOT", "").strip()
    candidate = Path(configured) if configured else CurrentStatcastSyncConfig().existing_silver_root
    return candidate.expanduser().resolve(strict=False)


def _column_role(name: str) -> str:
    if name in IDENTIFIER_FIELDS:
        return "IDENTIFIER"
    if name in GROUPING_FIELDS:
        return "GROUPING"
    if name in TIME_FIELDS:
        return "TIME"
    if name == "outcome":
        return "TARGET"
    if name in SIMULATION_STATE_FIELDS:
        return "SIMULATION_GENERATED_STATE"
    if name in MISSINGNESS_INDICATORS:
        return "MISSINGNESS_INDICATOR"
    if name in GOLD_FEATURES:
        return "PREGAME_FEATURE"
    if name == "datasetRole":
        return "RESEARCH_ONLY"
    return "EXCLUDED"


def _indicator_for(feature: str) -> str | None:
    if feature in MISSINGNESS_INDICATORS:
        return feature
    if feature in BATTER_FEATURES:
        return "batter_prior_missing"
    if feature in PITCHER_FEATURES:
        return "pitcher_prior_missing"
    if feature.startswith("batter_last100_"):
        if feature in {"batter_last100_contact_rate", "batter_last100_whiff_rate"}:
            return "batter_last100_whiff_missing"
        return "batter_last100_insufficient"
    if feature.startswith("pitcher_last250_"):
        if feature == "pitcher_last250_whiff_rate":
            return "pitcher_last250_whiff_missing"
        if feature == "pitcher_last250_avg_fastball_velocity":
            return "pitcher_last250_velocity_missing"
        return "pitcher_last250_insufficient"
    if feature.startswith("matchup_batter_"):
        return "matchup_batter_hand_missing"
    if feature.startswith("matchup_pitcher_"):
        return "matchup_pitcher_hand_missing"
    if feature == "matchup_platoon_advantage":
        return "matchup_batter_hand_missing|matchup_pitcher_hand_missing"
    return None


def _player_field(feature: str) -> str | None:
    if feature.startswith("batter_") or feature.startswith("matchup_batter_"):
        return "batterCanonicalPlayerId"
    if feature.startswith("pitcher_") or feature.startswith("matchup_pitcher_"):
        return "pitcherCanonicalPlayerId"
    return None


def _indicator_mask(frame: pd.DataFrame, indicator: str | None) -> pd.Series:
    if not indicator:
        return pd.Series(False, index=frame.index)
    names = indicator.split("|")
    result = pd.Series(False, index=frame.index)
    for name in names:
        if name in frame:
            numeric = pd.to_numeric(frame[name], errors="coerce").fillna(0.0)
            result |= numeric.ne(0.0)
    return result


def _reason_masks(feature: str, frame: pd.DataFrame, affected: pd.Series) -> dict[str, pd.Series]:
    empty = pd.Series(False, index=frame.index)
    result = {name: empty.copy() for name in REASON_CATEGORIES}
    remaining = affected.copy()

    if feature.startswith("batter_"):
        prior_count = pd.to_numeric(frame.get("batter_prior_pa_count", 0), errors="coerce").fillna(0.0)
        no_prior = remaining & (
            prior_count.eq(0.0)
            | _indicator_mask(frame, "batter_prior_missing")
        )
        result["NO_PRIOR_HISTORY"] |= no_prior
        remaining &= ~no_prior
        if feature.startswith("batter_last100_"):
            short = pd.to_numeric(frame.get("batter_last100_pa_count", 0), errors="coerce").fillna(0.0).lt(100.0)
            insufficient = remaining & short
            result["INSUFFICIENT_HISTORY"] |= insufficient
            remaining &= ~insufficient
            source = remaining & _indicator_mask(frame, "batter_last100_whiff_missing")
            result["SOURCE_MISSING"] |= source
            remaining &= ~source
    elif feature.startswith("pitcher_"):
        prior_count = pd.to_numeric(frame.get("pitcher_prior_bf_count", 0), errors="coerce").fillna(0.0)
        no_prior = remaining & (
            prior_count.eq(0.0)
            | _indicator_mask(frame, "pitcher_prior_missing")
        )
        result["NO_PRIOR_HISTORY"] |= no_prior
        remaining &= ~no_prior
        if feature.startswith("pitcher_last250_"):
            short = pd.to_numeric(frame.get("pitcher_last250_bf_count", 0), errors="coerce").fillna(0.0).lt(250.0)
            insufficient = remaining & short
            result["INSUFFICIENT_HISTORY"] |= insufficient
            remaining &= ~insufficient
            source_indicator = (
                "pitcher_last250_velocity_missing"
                if feature in {"pitcher_last250_avg_fastball_velocity", "pitcher_last250_velocity_missing"}
                else "pitcher_last250_whiff_missing"
            )
            source = remaining & _indicator_mask(frame, source_indicator)
            result["SOURCE_MISSING"] |= source
            remaining &= ~source
    elif feature.startswith("matchup_"):
        source = remaining & _indicator_mask(frame, _indicator_for(feature))
        result["SOURCE_MISSING"] |= source
        remaining &= ~source

    result["COMPUTATION_FAILURE"] |= remaining
    return result


def _rate(numerator: int, denominator: int) -> float:
    return float(numerator / denominator) if denominator else 0.0


def _find_bound_gold(
    root: Path,
    *,
    source_publication_sha: str,
    explicit_gold: Mapping[str, Any] | None,
) -> tuple[str, Path, dict[str, Any]]:
    publications_root = root / "publications" / "sha256"
    explicit_sha = str((explicit_gold or {}).get("manifestSha256") or "")
    candidates: list[tuple[str, Path, dict[str, Any]]] = []
    if publications_root.is_dir():
        for directory in sorted(publications_root.iterdir(), key=lambda item: item.name):
            if not directory.is_dir() or len(directory.name) != 64:
                continue
            path = directory / "manifest.json"
            if not path.is_file():
                continue
            manifest = _load_json(path)
            if (
                manifest.get("datasetId") == CURRENT_GOLD_DATASET_ID
                and (manifest.get("sourceAuthorities") or {}).get("currentSilverManifestSha256")
                    == source_publication_sha
            ):
                candidates.append((directory.name, path, manifest))

    if explicit_sha:
        candidates = [item for item in candidates if item[0] == explicit_sha]
    if len(candidates) != 1:
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_BINDING_NOT_UNIQUE",
            "The project-linked source authority does not resolve to exactly one current Gold publication.",
        )
    manifest_sha, path, manifest = candidates[0]
    if _sha256_file(path) != manifest_sha:
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_MANIFEST_HASH_MISMATCH",
            "The linked current Gold manifest differs from its complete-byte address.",
        )
    return manifest_sha, path, manifest


def _verify_player_identity(
    gold_manifest: Mapping[str, Any],
    observed_players: set[str],
) -> dict[str, Any]:
    authority = ((gold_manifest.get("sourceAuthorities") or {}).get("playerIdentity") or {})
    expected_manifest = str(authority.get("publicationManifestSha256") or "")
    expected_registration = str(authority.get("registrationSha256") or "")
    try:
        root = _existing_silver_root()
        registry = _load_json(root / "silver-table-registry.json")
        logical = ((registry.get("logicalObjects") or {}).get("dim_player") or {})
        expected_dataset_version = f"silver-table:dim_player:sha256:{expected_manifest}"
        if (
            logical.get("currentRegistrationSha256") != expected_registration
            or logical.get("currentDatasetVersionId") != expected_dataset_version
        ):
            raise CurrentGoldStage2ReviewError(
                "PLAYER_IDENTITY_AUTHORITY_MISMATCH",
                "The current Gold player identity authority differs from the verified Silver dimension.",
            )
        registration_path = root / "silver-table-registrations" / "objects" / "sha256" / f"{expected_registration}.json"
        if _sha256_file(registration_path) != expected_registration:
            raise CurrentGoldStage2ReviewError(
                "PLAYER_IDENTITY_AUTHORITY_MISMATCH",
                "The immutable player registration differs from its complete-byte address.",
            )
        registration = _load_json(registration_path)
        if (
            registration.get("datasetVersionId") != expected_dataset_version
            or registration.get("publicationManifestSha256") != expected_manifest
            or registration.get("tableName") != "dim_player"
            or registration.get("quarantine") != "QUARANTINED"
            or registration.get("selectable") is not False
            or registration.get("modelEligible") is not False
            or registration.get("approvedForTraining") is not False
        ):
            raise CurrentGoldStage2ReviewError(
                "PLAYER_IDENTITY_AUTHORITY_MISMATCH",
                "The immutable player registration contract does not match current Gold.",
            )
        object_dir = root / "objects" / "sha256" / expected_manifest
        manifest = _load_json(object_dir / "publication-manifest.json")
        addressed = hashlib.sha256(canonical_json_bytes({
            key: value for key, value in manifest.items() if key != "manifestSha256"
        })).hexdigest()
        expected_children = {"publication-manifest.json", "object.parquet", "table-contract.json", "transformation-receipt.json"}
        if (
            addressed != expected_manifest
            or {item.name for item in object_dir.iterdir()} != expected_children
            or manifest.get("outputPhysicalSha256") != registration.get("outputPhysicalSha256")
        ):
            raise CurrentGoldStage2ReviewError(
                "PLAYER_IDENTITY_AUTHORITY_MISMATCH",
                "The immutable player publication manifest is not self-consistent.",
            )
        for child_name in ("object.parquet", "table-contract.json", "transformation-receipt.json"):
            child = (manifest.get("children") or {}).get(child_name) or {}
            child_path = object_dir / child_name
            if (
                not child_path.is_file()
                or _sha256_file(child_path) != child.get("sha256")
                or child_path.stat().st_size != int(child.get("bytes") or -1)
            ):
                raise CurrentGoldStage2ReviewError(
                    "PLAYER_IDENTITY_AUTHORITY_MISMATCH",
                    f"The immutable player publication child {child_name} differs from its manifest.",
                )
        table = pq.read_table(
            object_dir / "object.parquet",
            columns=["canonicalPlayerId", "chadwickKeyUuid", "resolutionStatus"],
        )
        if table.num_rows != int(registration.get("rowCount") or -1):
            raise CurrentGoldStage2ReviewError(
                "PLAYER_IDENTITY_AUTHORITY_MISMATCH",
                "The immutable player dimension row count does not reconcile.",
            )
    except CurrentGoldStage2ReviewError:
        raise
    except Exception as exc:
        raise CurrentGoldStage2ReviewError(
            "PLAYER_IDENTITY_AUTHORITY_UNAVAILABLE",
            "The exact player identity authority could not be verified.",
            status_code=503,
        ) from exc

    exact: dict[str, str] = {}
    ambiguous: set[str] = set()
    for row in table.to_pylist():
        canonical = str(row.get("canonicalPlayerId") or "")
        chadwick = str(row.get("chadwickKeyUuid") or "")
        if row.get("resolutionStatus") != "MATCHED_EXACT" or not canonical or not chadwick:
            continue
        prior = exact.get(canonical)
        if prior is not None and prior != chadwick:
            ambiguous.add(canonical)
        else:
            exact[canonical] = chadwick
    unresolved = observed_players - set(exact)
    return {
        "authorityManifestSha256": expected_manifest,
        "authorityRegistrationSha256": expected_registration,
        "observedPlayerCount": len(observed_players),
        "matchedExactPlayerCount": len(observed_players - unresolved - ambiguous),
        "unresolvedPlayerIdentities": len(unresolved),
        "ambiguousPlayerIdentities": len(ambiguous & observed_players),
    }


@lru_cache(maxsize=8)
def _profile_gold(root_text: str, manifest_sha: str) -> dict[str, Any]:
    root = Path(root_text)
    manifest_path = root / "publications" / "sha256" / manifest_sha / "manifest.json"
    manifest = _load_json(manifest_path)
    feature_names = tuple(str(item) for item in manifest.get("featureNames") or [])
    if feature_names != tuple(GOLD_FEATURES):
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_FEATURE_CONTRACT_MISMATCH",
            "The current Gold ordered predictor contract is not the exact Gold-48 contract.",
        )

    paths: list[Path] = []
    declared_rows = 0
    physical_schema = None
    for partition in manifest.get("partitions") or []:
        path = root / str(partition.get("relativePath") or "")
        parquet = pq.ParquetFile(path) if path.is_file() else None
        if (
            not path.is_file()
            or _sha256_file(path) != partition.get("sha256")
            or parquet is None
            or parquet.metadata.num_rows != int(partition.get("rowCount") or -1)
        ):
            raise CurrentGoldStage2ReviewError(
                "CURRENT_GOLD_PARTITION_MISMATCH",
                "A current Gold partition differs from its immutable manifest.",
            )
        paths.append(path)
        declared_rows += int(partition["rowCount"])
        if physical_schema is None:
            physical_schema = parquet.schema_arrow
        elif not parquet.schema_arrow.equals(physical_schema):
            raise CurrentGoldStage2ReviewError(
                "CURRENT_GOLD_COLUMN_CONTRACT_MISMATCH",
                "Current Gold partitions do not share one exact physical schema.",
            )
    if not paths or declared_rows != int(manifest.get("rowCount") or -1):
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_ROW_COUNT_MISMATCH",
            "The current Gold row count does not reconcile with its partitions.",
        )

    assert physical_schema is not None
    columns = list(physical_schema.names)
    expected_columns = {
        *IDENTIFIER_FIELDS,
        *GROUPING_FIELDS,
        *TIME_FIELDS,
        "outcome",
        "datasetRole",
        *GOLD_FEATURES,
    }
    if set(columns) != expected_columns:
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_COLUMN_CONTRACT_MISMATCH",
            "The current Gold physical columns differ from the exact review contract.",
        )

    temporal = manifest.get("temporalContract") or {}
    dev_start, dev_end = [str(value) for value in temporal.get("developmentSelection") or ("", "")]
    oot_start, oot_end = [str(value) for value in temporal.get("finalOot") or ("", "")]
    totals = {"overall": 0, "development": 0, "finalOot": 0}
    season_rows: Counter[int] = Counter()
    month_rows: Counter[str] = Counter()
    target_counts = {
        "overall": Counter(),
        "development": Counter(),
        "finalOot": Counter(),
    }
    null_counts: dict[str, Counter[str]] = {
        name: Counter(overall=0, development=0, finalOot=0) for name in GOLD_FEATURES
    }
    seasonal_missing: dict[str, Counter[int]] = {name: Counter() for name in GOLD_FEATURES}
    monthly_missing: dict[str, Counter[str]] = {name: Counter() for name in GOLD_FEATURES}
    indicator_counts: Counter[str] = Counter()
    affected_counts: Counter[str] = Counter()
    affected_players: dict[str, set[str]] = {name: set() for name in GOLD_FEATURES}
    reason_counts: dict[str, Counter[str]] = {name: Counter() for name in GOLD_FEATURES}
    computation_failures: Counter[str] = Counter()
    seen_canonical_pa: set[str] = set()
    seen_public_pa: set[str] = set()
    duplicate_canonical_pa = 0
    duplicate_public_pa = 0
    alias_pa_mismatches = 0
    alias_game_mismatches = 0
    null_identity_rows = 0
    null_game_identity_rows = 0
    observed_players: set[str] = set()
    observed_game_pairs: set[tuple[str, str]] = set()
    split_overlap_rows = 0
    unclassified_temporal_rows = 0
    observed_min_date = ""
    observed_max_date = ""

    scan_columns = [
        "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id",
        "game_date", "season", "outcome", "datasetRole",
        "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", *GOLD_FEATURES,
    ]
    for path in paths:
        parquet = pq.ParquetFile(path)
        for batch in parquet.iter_batches(batch_size=65_536, columns=scan_columns, use_threads=False):
            frame = batch.to_pandas()
            size = len(frame)
            totals["overall"] += size
            dates = frame["game_date"].astype(str)
            development = dates.between(dev_start, dev_end, inclusive="both")
            final_oot = dates.between(oot_start, oot_end, inclusive="both")
            split_overlap_rows += int((development & final_oot).sum())
            unclassified_temporal_rows += int((~(development | final_oot)).sum())
            batch_min = str(dates.min())
            batch_max = str(dates.max())
            observed_min_date = min(observed_min_date, batch_min) if observed_min_date else batch_min
            observed_max_date = max(observed_max_date, batch_max) if observed_max_date else batch_max
            totals["development"] += int(development.sum())
            totals["finalOot"] += int(final_oot.sum())
            seasons = pd.to_numeric(frame["season"], errors="coerce").astype("Int64")
            months = dates.str.slice(0, 7)
            for season, count in seasons.value_counts(dropna=False).items():
                if not pd.isna(season):
                    season_rows[int(season)] += int(count)
            for month, count in months.value_counts().items():
                month_rows[str(month)] += int(count)

            for scope, mask in (
                ("overall", pd.Series(True, index=frame.index)),
                ("development", development),
                ("finalOot", final_oot),
            ):
                counts = frame.loc[mask, "outcome"].value_counts(dropna=False)
                for outcome, count in counts.items():
                    key = "<NULL>" if pd.isna(outcome) else str(outcome)
                    target_counts[scope][key] += int(count)

            identity_cols = [
                "canonicalPaId", "plate_appearance_id", "canonicalGameId", "game_id",
                "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
            ]
            identity_missing = frame[identity_cols].isna() | frame[identity_cols].astype(str).apply(lambda col: col.str.strip().eq(""))
            null_identity_rows += int(identity_missing.any(axis=1).sum())
            game_missing = identity_missing[["canonicalGameId", "game_id"]].any(axis=1)
            null_game_identity_rows += int(game_missing.sum())
            alias_pa_mismatches += int(frame["canonicalPaId"].astype(str).ne(frame["plate_appearance_id"].astype(str)).sum())
            alias_game_mismatches += int(frame["canonicalGameId"].astype(str).ne(frame["game_id"].astype(str)).sum())
            observed_game_pairs.update(zip(frame.loc[~game_missing, "canonicalGameId"].astype(str), frame.loc[~game_missing, "game_id"].astype(str)))
            for value in frame["canonicalPaId"].astype(str):
                if value in seen_canonical_pa:
                    duplicate_canonical_pa += 1
                else:
                    seen_canonical_pa.add(value)
            for value in frame["plate_appearance_id"].astype(str):
                if value in seen_public_pa:
                    duplicate_public_pa += 1
                else:
                    seen_public_pa.add(value)
            observed_players.update(frame["batterCanonicalPlayerId"].dropna().astype(str))
            observed_players.update(frame["pitcherCanonicalPlayerId"].dropna().astype(str))

            feature_frame = frame.loc[:, list(GOLD_FEATURES)]
            missing_frame = feature_frame.isna()
            numeric_frame = feature_frame.apply(pd.to_numeric, errors="coerce")
            finite_matrix = np.isfinite(numeric_frame.to_numpy(dtype=float, na_value=np.nan))
            nonfinite_frame = feature_frame.notna() & pd.DataFrame(
                ~finite_matrix,
                index=feature_frame.index,
                columns=feature_frame.columns,
            )
            season_missing = missing_frame.groupby(seasons, dropna=True).sum()
            month_missing = missing_frame.groupby(months, dropna=True).sum()
            for season, row in season_missing.iterrows():
                for feature, count in row.items():
                    seasonal_missing[str(feature)][int(season)] += int(count)
            for month, row in month_missing.iterrows():
                for feature, count in row.items():
                    monthly_missing[str(feature)][str(month)] += int(count)

            for feature in GOLD_FEATURES:
                missing = missing_frame[feature]
                nonfinite = nonfinite_frame[feature]
                computation_failures[feature] += int(nonfinite.sum())
                null_counts[feature]["overall"] += int(missing.sum())
                null_counts[feature]["development"] += int((missing & development).sum())
                null_counts[feature]["finalOot"] += int((missing & final_oot).sum())

                indicator = _indicator_for(feature)
                indicated = _indicator_mask(frame, indicator)
                indicator_counts[feature] += int(indicated.sum())
                affected = missing | indicated | nonfinite
                affected_counts[feature] += int(affected.sum())
                player_field = _player_field(feature)
                if player_field:
                    affected_players[feature].update(frame.loc[affected, player_field].dropna().astype(str))
                for reason, mask in _reason_masks(feature, frame, affected).items():
                    reason_counts[feature][reason] += int(mask.sum())

    identity = _verify_player_identity(manifest, observed_players)
    diagnostics = []
    for feature in GOLD_FEATURES:
        reasons = [
            {"category": category, "rows": int(reason_counts[feature][category])}
            for category in REASON_CATEGORIES
            if reason_counts[feature][category]
        ]
        primary_reason = max(reasons, key=lambda item: item["rows"])["category"] if reasons else None
        diagnostics.append({
            "feature": feature,
            "order": list(GOLD_FEATURES).index(feature) + 1,
            "classification": _column_role(feature),
            "missingRows": int(null_counts[feature]["overall"]),
            "overallMissingPct": _rate(null_counts[feature]["overall"], totals["overall"]),
            "developmentMissingPct": _rate(null_counts[feature]["development"], totals["development"]),
            "finalOotMissingPct": _rate(null_counts[feature]["finalOot"], totals["finalOot"]),
            "indicatorField": _indicator_for(feature),
            "indicatorRows": int(indicator_counts[feature]),
            "indicatorPrevalence": _rate(indicator_counts[feature], totals["overall"]),
            "affectedRows": int(affected_counts[feature]),
            "affectedPlayerCount": len(affected_players[feature]),
            "primaryReasonCategory": primary_reason,
            "reasonCounts": reasons,
            "computationFailureRows": int(computation_failures[feature]),
            "bySeason": [
                {
                    "season": int(season),
                    "missingRows": int(missing_rows),
                    "rows": int(season_rows[season]),
                    "missingPct": _rate(missing_rows, season_rows[season]),
                }
                for season, missing_rows in sorted(seasonal_missing[feature].items())
            ],
            "byMonth": [
                {
                    "month": month,
                    "missingRows": int(missing_rows),
                    "rows": int(month_rows[month]),
                    "missingPct": _rate(missing_rows, month_rows[month]),
                }
                for month, missing_rows in sorted(monthly_missing[feature].items())
            ],
        })

    schema = physical_schema
    columns_payload = []
    feature_order = {name: index + 1 for index, name in enumerate(GOLD_FEATURES)}
    for field in schema:
        columns_payload.append({
            "name": field.name,
            "dtype": str(field.type),
            "nullable": field.nullable,
            "classification": _column_role(field.name),
            "predictorOrder": feature_order.get(field.name),
        })

    canonical_game_targets: dict[str, set[str]] = defaultdict(set)
    public_game_targets: dict[str, set[str]] = defaultdict(set)
    for canonical_game_id, public_game_id in observed_game_pairs:
        canonical_game_targets[canonical_game_id].add(public_game_id)
        public_game_targets[public_game_id].add(canonical_game_id)
    ambiguous_game_identities = sum(
        1 for values in canonical_game_targets.values() if len(values) != 1
    ) + sum(
        1 for values in public_game_targets.values() if len(values) != 1
    )
    observed_target_classes = sorted(target_counts["overall"])
    unexpected_target_rows = sum(
        count for outcome, count in target_counts["overall"].items()
        if outcome not in GOLD_CLASS_ORDER
    )

    return {
        "rowCount": totals["overall"],
        "developmentRows": totals["development"],
        "finalOotRows": totals["finalOot"],
        "rowsBySeason": {str(key): int(value) for key, value in sorted(season_rows.items())},
        "rowsByMonth": {key: int(value) for key, value in sorted(month_rows.items())},
        "targetCounts": {
            scope: [
                {"class": outcome, "rows": int(target_counts[scope][outcome])}
                for outcome in GOLD_CLASS_ORDER
            ]
            for scope in ("overall", "development", "finalOot")
        },
        "observedTargetClasses": observed_target_classes,
        "unexpectedTargetRows": int(unexpected_target_rows),
        "targetRowsReconciled": int(sum(target_counts["overall"].values())) == totals["overall"],
        "columns": columns_payload,
        "missingness": diagnostics,
        "identity": {
            **identity,
            "duplicateCanonicalPaIdentities": duplicate_canonical_pa,
            "duplicatePlateAppearanceIdentities": duplicate_public_pa,
            "unresolvedGameIdentities": null_game_identity_rows,
            "ambiguousGameIdentities": ambiguous_game_identities,
            "nullIdentityRows": null_identity_rows,
            "paAliasValueDifferences": alias_pa_mismatches,
            "gameAliasValueDifferences": alias_game_mismatches,
        },
        "computationFailureRows": int(sum(computation_failures.values())),
        "temporalReconciliation": {
            "observedStartDate": observed_min_date,
            "observedEndDate": observed_max_date,
            "splitOverlapRows": split_overlap_rows,
            "unclassifiedRows": unclassified_temporal_rows,
            "developmentPlusFinalOotRows": totals["development"] + totals["finalOot"],
        },
    }


def _preview_rows(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    season: int | None,
    limit: int,
    sample: str,
) -> dict[str, Any]:
    limit = min(max(int(limit), 1), 50)
    selected_partitions = [
        item for item in (manifest.get("partitions") or [])
        if season is None or int(item.get("season") or 0) == int(season)
    ]
    if not selected_partitions:
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_PREVIEW_SCOPE_EMPTY",
            "No current Gold rows exist for the requested season.",
            status_code=404,
        )
    preview_columns = [
        "game_date", "season", "game_id", "plate_appearance_id", "outcome",
        "context_inning", "context_top_bottom", "context_outs_before",
        "context_base_mask_before", "context_batting_score_diff_before",
        "batter_avg", "pitcher_era9", "batter_last100_strikeout_rate",
        "pitcher_last250_strikeout_rate", "datasetRole",
    ]
    frames: list[pd.DataFrame] = []
    for partition in selected_partitions:
        path = root / str(partition["relativePath"])
        if sample == "random":
            frames.append(pq.read_table(path, columns=preview_columns).to_pandas())
        else:
            frames.append(pq.ParquetFile(path).read_row_group(0, columns=preview_columns).slice(0, limit).to_pandas())
            if sum(len(item) for item in frames) >= limit:
                break
    frame = pd.concat(frames, ignore_index=True)
    if sample == "random" and len(frame) > limit:
        frame = frame.sample(limit, random_state=20260828)
    else:
        frame = frame.head(limit)
    rows = frame.to_dict(orient="records")
    for row in rows:
        for key, value in tuple(row.items()):
            if value is None or (not isinstance(value, (list, dict, tuple)) and bool(pd.isna(value))):
                row[key] = None
            elif isinstance(value, (np.integer,)):
                row[key] = int(value)
            elif isinstance(value, (float, np.floating)):
                row[key] = float(value) if math.isfinite(float(value)) else None
            elif isinstance(value, np.bool_):
                row[key] = bool(value)
    return {
        "season": season,
        "sample": "random" if sample == "random" else "head",
        "limit": limit,
        "columns": preview_columns,
        "rows": rows,
    }


def current_gold_stage2_review(
    database: Database,
    project_id: str,
    *,
    season: int | None = None,
    limit: int = 25,
    sample: str = "head",
) -> dict[str, Any]:
    """Return the exact project-linked current-Gold Stage 2 review."""

    if season is not None and season not in REQUIRED_SEASONS:
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_PREVIEW_SEASON_INVALID",
            "Stage 2 season scope is limited to the linked 2023–2026 Gold authority.",
            status_code=422,
        )
    if sample not in {"head", "random"}:
        raise CurrentGoldStage2ReviewError(
            "CURRENT_GOLD_PREVIEW_SAMPLE_INVALID",
            "Stage 2 preview sample must be head or random.",
            status_code=422,
        )
    linkage = SportsForecastContractStore(database).get_evidence_dataset(project_id)
    registration = SportsDatasetRegistry(database).get(str(linkage["registrationId"]))
    if not registration:
        raise CurrentGoldStage2ReviewError(
            "PROJECT_DATASET_REGISTRATION_MISSING",
            "The project-linked sports registration is unavailable.",
        )
    exact_link = (
        registration.get("dataset_id") == linkage.get("datasetId") == CURRENT_SOURCE_DATASET_ID
        and registration.get("dataset_version_id") == linkage.get("datasetVersionId")
        and registration.get("manifest_sha") == linkage.get("manifestSha")
        and registration.get("validation_status") == "VALID"
    )
    if not exact_link:
        raise CurrentGoldStage2ReviewError(
            "PROJECT_DATASET_AUTHORITY_MISMATCH",
            "The project dataset activation does not match its exact registered authority.",
        )
    metadata = registration.get("metadata_json") or {}
    manifest_metadata = metadata.get("manifestMetadata") or {}
    source_publication_sha = str(manifest_metadata.get("publicationManifestSha256") or "")
    if len(source_publication_sha) != 64:
        raise CurrentGoldStage2ReviewError(
            "PROJECT_DATASET_SOURCE_AUTHORITY_MISSING",
            "The project-linked registration does not identify its immutable Silver publication.",
        )

    root = _gold_root()
    gold_sha, _gold_path, gold_manifest = _find_bound_gold(
        root,
        source_publication_sha=source_publication_sha,
        explicit_gold=metadata.get("goldPublication") if isinstance(metadata, Mapping) else None,
    )
    # `_profile_gold` performs complete-byte manifest/partition verification,
    # exact schema checks, and row reconciliation while producing the review.
    # Avoid reading the same 697k-row publication twice on a cold Stage 2 load.
    profile = _profile_gold(str(root), gold_sha)

    feature_names = [str(item) for item in gold_manifest.get("featureNames") or []]
    temporal = gold_manifest.get("temporalContract") or {}
    source_temporal = manifest_metadata.get("temporalContract") or {}
    class_order = [str(item) for item in manifest_metadata.get("targetClassOrder") or []]
    seasons = sorted(int(key) for key in profile["rowsBySeason"])
    identity = profile["identity"]
    source_coverage = linkage["coverage"]
    source_coverage_exact = (
        source_coverage.get("earliestDate"),
        source_coverage.get("latestDate"),
        int(source_coverage.get("rowCount") or -1),
    ) == EXPECTED_SOURCE_COVERAGE
    gold_coverage_exact = (
        str((gold_manifest.get("dateCoverage") or {}).get("earliestDate") or ""),
        str((gold_manifest.get("dateCoverage") or {}).get("latestDate") or ""),
        profile["rowCount"],
    ) == EXPECTED_GOLD_COVERAGE
    temporal_reconciliation = profile["temporalReconciliation"]
    temporal_exact = (
        tuple(temporal.get("developmentSelection") or ()) == EXPECTED_DEVELOPMENT[:2]
        and profile["developmentRows"] == EXPECTED_DEVELOPMENT[2]
        and tuple(temporal.get("finalOot") or ()) == EXPECTED_FINAL_OOT[:2]
        and profile["finalOotRows"] == EXPECTED_FINAL_OOT[2]
        and tuple(temporal.get("eligibleEvidence") or ()) == EXPECTED_GOLD_COVERAGE[:2]
        and temporal_reconciliation["observedStartDate"] == EXPECTED_GOLD_COVERAGE[0]
        and temporal_reconciliation["observedEndDate"] == EXPECTED_GOLD_COVERAGE[1]
        and temporal_reconciliation["splitOverlapRows"] == 0
        and temporal_reconciliation["unclassifiedRows"] == 0
        and temporal_reconciliation["developmentPlusFinalOotRows"] == profile["rowCount"]
    )
    target_exact = (
        class_order == list(GOLD_CLASS_ORDER)
        and set(profile["observedTargetClasses"]) == set(GOLD_CLASS_ORDER)
        and profile["unexpectedTargetRows"] == 0
        and profile["targetRowsReconciled"]
    )
    model_free = (
        gold_manifest.get("status") == "RESEARCH_ONLY_COMPLETE"
        and int(gold_manifest.get("modelsFitted") or 0) == 0
        and gold_manifest.get("modelPromoted") is False
    )
    pit_pass = (
        temporal.get("historyCutoff") == EXPECTED_GOLD_HISTORY_CUTOFF
        and source_temporal.get("featureCutoffRule") == EXPECTED_SOURCE_HISTORY_CUTOFF
        and feature_names == list(GOLD_FEATURES)
        and source_coverage_exact
        and gold_coverage_exact
        and temporal_exact
    )
    leakage_pass = (
        target_exact
        and "outcome" not in feature_names
        and all(_column_role(name) in {"PREGAME_FEATURE", "SIMULATION_GENERATED_STATE", "MISSINGNESS_INDICATOR"} for name in feature_names)
        and all(_column_role(name) == "SIMULATION_GENERATED_STATE" for name in SIMULATION_STATE_FIELDS)
        and identity["duplicateCanonicalPaIdentities"] == 0
        and identity["duplicatePlateAppearanceIdentities"] == 0
        and identity["unresolvedPlayerIdentities"] == 0
        and identity["ambiguousPlayerIdentities"] == 0
        and identity["unresolvedGameIdentities"] == 0
        and identity["ambiguousGameIdentities"] == 0
        and profile["computationFailureRows"] == 0
        and model_free
    )

    checks = [
        {"code": "PROJECT_SOURCE_IDENTITY", "status": "PASS" if exact_link else "FAIL", "blocking": True, "detail": "Project activation matches registration, version, and manifest."},
        {"code": "SOURCE_COVERAGE", "status": "PASS" if source_coverage_exact else "FAIL", "blocking": True, "detail": f"Registered source coverage is {source_coverage.get('earliestDate')} through {source_coverage.get('latestDate')} with {int(source_coverage.get('rowCount') or 0):,} accepted PAs."},
        {"code": "GOLD_SOURCE_BINDING", "status": "PASS", "blocking": True, "detail": "Exactly one verified Gold publication binds the registered Silver publication SHA."},
        {"code": "GOLD_ROW_RECONCILIATION", "status": "PASS" if gold_coverage_exact and profile["rowCount"] == int(gold_manifest.get("rowCount") or -1) else "FAIL", "blocking": True, "detail": f"{profile['rowCount']:,} materialized rows reconcile to immutable partitions and exact coverage."},
        {"code": "GOLD_FEATURE_CONTRACT", "status": "PASS" if feature_names == list(GOLD_FEATURES) and gold_manifest.get("featureCount") == 48 else "FAIL", "blocking": True, "detail": "Exact ordered Gold-48 predictor contract."},
        {"code": "REQUIRED_SEASONS", "status": "PASS" if seasons == list(REQUIRED_SEASONS) else "FAIL", "blocking": True, "detail": f"Materialized seasons: {', '.join(str(item) for item in seasons)}."},
        {"code": "TEMPORAL_SPLIT_RECONCILIATION", "status": "PASS" if temporal_exact else "FAIL", "blocking": True, "detail": f"Development {EXPECTED_DEVELOPMENT[0]}–{EXPECTED_DEVELOPMENT[1]} ({profile['developmentRows']:,}) plus final OOT {EXPECTED_FINAL_OOT[0]}–{EXPECTED_FINAL_OOT[1]} ({profile['finalOotRows']:,}) exactly reconciles."},
        {"code": "FINAL_OOT_PRESENT", "status": "PASS" if temporal_exact and profile["finalOotRows"] == EXPECTED_FINAL_OOT[2] else "FAIL", "blocking": True, "detail": f"{profile['finalOotRows']:,} untouched final-OOT rows."},
        {"code": "TARGET_TAXONOMY", "status": "PASS" if target_exact else "FAIL", "blocking": True, "detail": "Observed targets exactly reconcile to the governed eight-class PA taxonomy."},
        {"code": "PA_IDENTITY_UNIQUENESS", "status": "PASS" if identity["duplicateCanonicalPaIdentities"] == 0 and identity["duplicatePlateAppearanceIdentities"] == 0 else "FAIL", "blocking": True, "detail": "Zero duplicate canonical or public PA identities."},
        {"code": "PLAYER_GAME_IDENTITY", "status": "PASS" if identity["unresolvedPlayerIdentities"] == 0 and identity["ambiguousPlayerIdentities"] == 0 and identity["unresolvedGameIdentities"] == 0 and identity["ambiguousGameIdentities"] == 0 else "FAIL", "blocking": True, "detail": "Zero unresolved or ambiguous included player/game identities."},
        {"code": "MODEL_FREE_PUBLICATION", "status": "PASS" if model_free else "FAIL", "blocking": True, "detail": "Research-only Gold evidence has zero fitted models and no promotion."},
        {"code": "POINT_IN_TIME_REVIEW", "status": "PASS" if pit_pass else "REVIEW", "blocking": True, "detail": "Every historical aggregate uses source.gameDate < target.gameDate; same-date rows are excluded." if pit_pass else "The exact prior-day cutoff evidence is unresolved."},
        {"code": "LEAKAGE_GATE", "status": "PASS_WITH_CONDITIONS" if leakage_pass else "REVIEW", "blocking": True, "detail": "Predictors exclude target/future fields. Five conditional PA-state predictors must be generated by the simulator at forecast time." if leakage_pass else "One or more leakage-contract invariants remain unresolved."},
    ]
    blockers = [item["detail"] for item in checks if item["blocking"] and item["status"] not in {"PASS", "PASS_WITH_CONDITIONS"}]
    review_identity = {
        "projectId": project_id,
        "registrationId": linkage["registrationId"],
        "datasetVersionId": linkage["datasetVersionId"],
        "sourceManifestSha": linkage["manifestSha"],
        "goldManifestSha": gold_sha,
        "checks": [{"code": item["code"], "status": item["status"]} for item in checks],
    }
    review_digest = hashlib.sha256(canonical_json_bytes(review_identity)).hexdigest()
    preview = _preview_rows(root, gold_manifest, season=season, limit=limit, sample=sample)

    return {
        "schemaVersion": REVIEW_SCHEMA_VERSION,
        "projectId": project_id,
        "sourceAuthority": {
            "registrationId": linkage["registrationId"],
            "datasetId": linkage["datasetId"],
            "datasetVersionId": linkage["datasetVersionId"],
            "manifestSha": linkage["manifestSha"],
            "activationRevision": linkage["activationRevision"],
            "rowCount": linkage["coverage"]["rowCount"],
            "dateCoverage": {
                "earliestDate": linkage["coverage"]["earliestDate"],
                "latestDate": linkage["coverage"]["latestDate"],
            },
            "silverPublicationManifestSha": source_publication_sha,
        },
        "goldAuthority": {
            "datasetId": CURRENT_GOLD_DATASET_ID,
            "manifestSha": gold_sha,
            "manifestContract": gold_manifest.get("manifestContract"),
            "manifestVersion": gold_manifest.get("manifestVersion"),
            "status": gold_manifest.get("status"),
            "modelsFitted": gold_manifest.get("modelsFitted"),
            "modelPromoted": gold_manifest.get("modelPromoted"),
            "rowCount": profile["rowCount"],
            "featureCount": len(feature_names),
            "dateCoverage": gold_manifest.get("dateCoverage"),
            "rowsBySeason": profile["rowsBySeason"],
            "sourceSilverManifestSha": source_publication_sha,
            "verified": True,
        },
        "matrix": {
            "grain": "PLATE_APPEARANCE",
            "totalColumns": len(profile["columns"]),
            "predictorCount": len(feature_names),
            "orderedPredictors": feature_names,
            "seasons": seasons,
            "development": {
                "startDate": (temporal.get("developmentSelection") or [None, None])[0],
                "endDate": (temporal.get("developmentSelection") or [None, None])[1],
                "rows": profile["developmentRows"],
            },
            "finalOot": {
                "startDate": (temporal.get("finalOot") or [None, None])[0],
                "endDate": (temporal.get("finalOot") or [None, None])[1],
                "rows": profile["finalOotRows"],
            },
            "columns": profile["columns"],
        },
        "targetTaxonomy": {
            "column": "outcome",
            "classOrder": class_order,
            "distributions": profile["targetCounts"],
        },
        "identity": identity,
        "missingness": {
            "reasonCategories": list(REASON_CATEGORIES),
            "predictors": profile["missingness"],
            "note": "Indicator prevalence is reported separately from physical nulls; a complete indicator column does not prove its underlying feature is complete.",
        },
        "pointInTimeReview": next(item for item in checks if item["code"] == "POINT_IN_TIME_REVIEW"),
        "leakageGate": next(item for item in checks if item["code"] == "LEAKAGE_GATE"),
        "modelingTreatment": {
            "coldStartRows": "RETAIN",
            "imputation": "TRAINING_FOLD_ONLY_OR_HIERARCHICAL_LEAGUE_PRIORS",
            "missingFlags": "RETAIN",
            "globalImputation": "PROHIBITED",
            "validationOrOotPreprocessing": "PROHIBITED",
            "simulationStateForecastRule": "SUPPLY_FROM_SIMULATOR_NEVER_FUTURE_ACTUAL_GAME_STATE",
        },
        "checks": checks,
        "acceptance": {"allowed": not blockers, "blockers": blockers},
        "reviewDigest": review_digest,
        "preview": preview,
    }


__all__ = [
    "CurrentGoldStage2ReviewError",
    "REVIEW_SCHEMA_VERSION",
    "current_gold_stage2_review",
]
