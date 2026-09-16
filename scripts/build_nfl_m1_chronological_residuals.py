"""Reuse certified M1 point predictions as paired chronological residual evidence.

This research reader never fits a score model and never opens season 2025 or
2026 outcomes.  Separate physical season filters keep the declared assessment
scores unopened until a fitted sampler configuration has been frozen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

SOURCE_ROOT = Path(r"C:\Users\james\asp-data-staging\nfl\m1-modeling-benchmark-v1")
SOURCE_LEDGER = SOURCE_ROOT / "predictions/five-fold-oof-point-predictions.parquet"
SOURCE_SELECTION = SOURCE_ROOT / "selection/oof-selection-receipt.json"
POINT_LEDGER_SHA256 = "ba8a695675c9222746cc1d6a31608604c7a5e50083574cd6717f1dd34c199a1b"
SOURCE_CANDIDATE = "xgboost-fixed-research-challenger"
SOURCE_RECENCY = "ALL_AVAILABLE_HISTORY"
CONTRACT = "NFL_M1_CHRONOLOGICAL_PAIRED_RESIDUAL_EVIDENCE_V1"
PHASE_SEASONS = {"development": (2020, 2021, 2022), "assessment": (2023, 2024)}
COUNTS = {2020: 269, 2021: 285, 2022: 284, 2023: 285, 2024: 285}
METADATA_COLUMNS = (
    "canonical_game_id", "game_date", "season", "game_type", "week", "fold_id",
    "candidate_id", "family", "feature_tier", "recency_strategy", "training_rows",
    "training_start_season", "training_end_season",
)
SCORE_COLUMNS = (
    "actual_home_points", "actual_away_points",
    "predicted_home_points", "predicted_away_points",
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def reference(path: Path) -> dict[str, Any]:
    path = Path(path).resolve()
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "byteCount": len(data)}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_bytes())
    if not isinstance(value, dict):
        raise ValueError("OBJECT_REQUIRED")
    return value


def _clock(value: str) -> datetime:
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("EXPLICIT_TIMEZONE_REQUIRED")
    return result.astimezone(timezone.utc)


def _source_receipt() -> dict[str, Any]:
    source = reference(SOURCE_LEDGER)
    selection = _json(SOURCE_SELECTION)
    if source["sha256"] != POINT_LEDGER_SHA256 or selection.get("pointOofLedgerSha256") != POINT_LEDGER_SHA256:
        raise ValueError("CERTIFIED_OOF_LEDGER_HASH_DIFFERS")
    selected = selection["familySelections"]["XGBOOST"]
    if selected["candidate_id"] != SOURCE_CANDIDATE or selected["recency_strategy"] != SOURCE_RECENCY:
        raise ValueError("FROZEN_XGBOOST_CONFIGURATION_DIFFERS")
    if selection["developmentValidationSeasons"] != list(COUNTS):
        raise ValueError("REGISTERED_DEVELOPMENT_SEASONS_DIFFER")
    return {
        "pointPredictionSource": source, "selectionReceipt": reference(SOURCE_SELECTION),
        "selectionIdentity": selection["selectionSha256"],
        "foundationManifestSha256": selection["foundationManifestSha256"],
        "gameGoldManifestSha256": selection["gameGoldManifestSha256"],
        "pointModelConfiguration": selected,
    }


def _filters(seasons: tuple[int, ...]) -> list[tuple[str, str, Any]]:
    if not seasons or not set(seasons).issubset(COUNTS):
        raise ValueError("ONLY_DECLARED_DEVELOPMENT_SEASONS_PERMITTED")
    return [("candidate_id", "=", SOURCE_CANDIDATE),
            ("recency_strategy", "=", SOURCE_RECENCY), ("season", "in", list(seasons)),
            ("season", "<", 2025)]


def validate_chronology(frame: pd.DataFrame, seasons: tuple[int, ...]) -> None:
    if frame.canonical_game_id.duplicated().any():
        raise ValueError("DUPLICATE_CHRONOLOGICAL_GAME")
    observed = {int(k): int(v) for k, v in frame.groupby("season").size().items()}
    if observed != {season: COUNTS[season] for season in seasons}:
        raise ValueError("CERTIFIED_COHORT_COUNTS_DIFFER")
    if not frame.training_end_season.eq(frame.season - 1).all():
        raise ValueError("SCORE_MODEL_NOT_TRAINED_BEFORE_PREDICTION_SEASON")
    if not frame.training_start_season.eq(1999).all():
        raise ValueError("DECLARED_ALL_HISTORY_TRAINING_START_DIFFERS")
    if not frame.canonical_game_id.str[:4].astype(int).eq(frame.season).all():
        raise ValueError("GAME_ID_SEASON_DIFFERS")
    if not frame.family.eq("XGBOOST").all() or not frame.feature_tier.eq("LONG_HISTORY_CORE").all():
        raise ValueError("FROZEN_MODEL_FAMILY_OR_FEATURE_TIER_DIFFERS")
    dates = pd.to_datetime(frame.game_date, errors="raise")
    if dates.isna().any():
        raise ValueError("MISSING_GAME_DATE")


def metadata_inventory() -> dict[str, Any]:
    """Inspect all Development membership/fit lineage without outcome columns."""
    sources = _source_receipt()
    seasons = tuple(COUNTS)
    frame = pq.read_table(SOURCE_LEDGER, columns=list(METADATA_COLUMNS), filters=_filters(seasons)).to_pandas()
    validate_chronology(frame, seasons)
    return {"contract": CONTRACT, "createdAtUtc": utc(), **sources,
            "metadataOnly": True, "outcomesRead": False,
            "seasons": [{"season": s, "games": COUNTS[s],
                         "trainingStartSeason": 1999, "trainingEndSeason": s - 1}
                        for s in seasons],
            "sealedSeasonsExcludedBeforeOutcomeAccess": [2025], "opening2026Excluded": True,
            "historicalPredictions": "FROZEN_FOLD_LOCAL_OUT_OF_SAMPLE_POINT_PREDICTIONS",
            "historicalVintageLimitation": "Reconstructed Gold uses retained source revisions, not archived game-cutoff acquisitions; Development years previously informed M1 research."}


def materialize_target_metadata(output_dir: Path) -> dict[str, Any]:
    """Save exact target identities for context construction without scores."""
    retained_path = Path(output_dir) / "metadata-preflight.json"
    if retained_path.exists():
        retained = _json(retained_path)
        for ref in [retained["targetIdentities"], retained["pointPredictionSource"],
                    *retained["productionPreservationReferences"]]:
            if reference(Path(ref["path"])) != ref:
                raise ValueError("RETAINED_PREFLIGHT_PHYSICAL_BYTES_DIFFER")
        return retained
    inventory = metadata_inventory()
    frame = pq.read_table(SOURCE_LEDGER, columns=list(METADATA_COLUMNS),
                          filters=_filters(tuple(COUNTS))).to_pandas()
    frame = frame.sort_values(["game_date", "canonical_game_id"], kind="stable").reset_index(drop=True)
    path = Path(output_dir) / "target-identities.parquet"
    _write_new(path, frame.to_parquet(index=False, engine="pyarrow", compression="zstd"))
    artifact_root = SOURCE_ROOT / "research-artifact/objects/sha256/ab9c066052b288f3f6162d8f8558e673988fb52172c72fe00aa855aa800a45e9"
    manifest_ref = reference(artifact_root / "manifest.json")
    binary_ref = reference(artifact_root / "model.joblib")
    if manifest_ref["sha256"] != artifact_root.name or binary_ref["sha256"] != "7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd":
        raise ValueError("ACTIVE_FROZEN_MODEL_PHYSICAL_IDENTITY_DIFFERS")
    result = {**inventory, "targetIdentities": reference(path), "rowCount": len(frame),
              "productionPreservationReferences": [manifest_ref, binary_ref],
              "productionModelLoaded": False}
    _write_new(Path(output_dir) / "metadata-preflight.json",
               (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return result


def _write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"IMMUTABLE_OUTPUT_ALREADY_EXISTS:{path}")
        return
    with path.open("xb") as stream:
        stream.write(data)


def build_residual_evidence(
    declaration_path: Path, output_dir: Path, *, phase: str,
    fitted_config_path: Path | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Materialize one predeclared phase; retain raw aligned residual pairs.

    The sampler must center the eligible pooled donor bank once for both arms.
    This table deliberately does not center per-season or candidate residuals.
    """
    if phase not in PHASE_SEASONS:
        raise ValueError("UNKNOWN_RESIDUAL_PHASE")
    declaration = _json(declaration_path)
    declaration_ref = reference(declaration_path)
    if declaration.get("allowedPointLedgerSha256") != POINT_LEDGER_SHA256:
        raise ValueError("DECLARATION_POINT_SOURCE_BINDING_REQUIRED")
    if declaration.get("donorSeasons") != list(PHASE_SEASONS["development"]) or declaration.get("assessmentSeasons") != list(PHASE_SEASONS["assessment"]):
        raise ValueError("DECLARATION_TEMPORAL_PHASES_DIFFER")
    declaration_clock = _clock(declaration["recordedAtUtc"])
    if declaration_clock > datetime.now(timezone.utc):
        raise ValueError("DECLARATION_CLOCK_IS_IN_FUTURE")
    fitted_ref = None
    if phase == "assessment":
        if fitted_config_path is None:
            raise ValueError("FROZEN_SAMPLER_CONFIGURATION_REQUIRED_BEFORE_ASSESSMENT")
        fitted = _json(fitted_config_path)
        if fitted.get("declarationSha256") != declaration_ref["sha256"]:
            raise ValueError("FITTED_CONFIGURATION_DECLARATION_BINDING_DIFFERS")
        fitted_clock = _clock(fitted.get("frozenAtUtc") or fitted.get("createdAtUtc") or fitted.get("fittedAtUtc"))
        if not declaration_clock <= fitted_clock <= datetime.now(timezone.utc):
            raise ValueError("FITTED_CONFIGURATION_CLOCK_NOT_AFTER_DECLARATION")
        fitted_ref = reference(fitted_config_path)
    sources = _source_receipt()
    seasons = PHASE_SEASONS[phase]
    output_dir = Path(output_dir)
    receipt_path = output_dir / f"{phase}-residuals-receipt.json"
    if receipt_path.exists():
        retained = _json(receipt_path)
        if retained["declaration"] != declaration_ref or retained["fittedSamplerConfiguration"] != fitted_ref:
            raise ValueError("RETAINED_RESIDUAL_BINDING_DIFFERS")
        if retained["pointPredictionSource"] != sources["pointPredictionSource"]:
            raise ValueError("RETAINED_SOURCE_BINDING_DIFFERS")
        if reference(Path(retained["data"]["path"])) != retained["data"]:
            raise ValueError("RETAINED_RESIDUAL_DATA_BYTES_DIFFER")
        frame = pd.read_parquet(retained["data"]["path"])
        validate_chronology(frame, seasons)
        return frame, retained
    # Identity/chronology before score columns: no outcome from a sealed or
    # undeclared season can enter this phase's read request.
    metadata = pq.read_table(SOURCE_LEDGER, columns=list(METADATA_COLUMNS), filters=_filters(seasons)).to_pandas()
    validate_chronology(metadata, seasons)
    outcome_opened_at = utc()
    frame = pq.read_table(SOURCE_LEDGER, columns=[*METADATA_COLUMNS, *SCORE_COLUMNS], filters=_filters(seasons)).to_pandas()
    validate_chronology(frame, seasons)
    frame = frame.sort_values(["game_date", "canonical_game_id"], kind="stable").reset_index(drop=True)
    values = frame[list(SCORE_COLUMNS)].to_numpy(float)
    if not np.isfinite(values).all() or (values < 0).any():
        raise ValueError("INVALID_POINT_FORECAST_OR_ACTUAL_SCORE")
    for side in ("home", "away"):
        frame[f"raw_{side}_residual"] = frame[f"actual_{side}_points"] - frame[f"predicted_{side}_points"]
    data_path = output_dir / f"{phase}-residuals.parquet"
    parquet_bytes = frame.to_parquet(index=False, engine="pyarrow", compression="zstd")
    _write_new(data_path, parquet_bytes)
    receipt = {
        "contract": CONTRACT, "createdAtUtc": utc(), "phase": phase,
        "declaration": declaration_ref, "fittedSamplerConfiguration": fitted_ref, **sources,
        "data": reference(data_path), "rowCount": len(frame), "seasons": list(seasons),
        "outcomeColumnsOpenedAtUtc": outcome_opened_at,
        "physicalReadFilter": _filters(seasons), "chronologyCheckedBeforeOutcomeAccess": True,
        "sealed2025OutcomesOpened": False, "opening2026OutcomesOpened": False,
        "scoreModelFittingPerformed": False, "productionArtifactWrites": False,
        "residualDefinition": "actual_home_points-predicted_home_points, actual_away_points-predicted_away_points; complete same-game oriented pair; not yet centered",
        "requiredSamplerCentering": "Center the fixed 2020-2022 pooled donor residuals once; reuse the same centered pairs in both arms and both assessment seasons; do not recenter candidate weights or add assessment residuals",
        "evidenceClass": "CHRONOLOGICAL_RESEARCH_REUSE_OF_CERTIFIED_POINT_OOF",
        "historicalVintageLimitation": "Point features were reconstructed Gold with retained source revisions; no archived acquisition-vintage guarantee. Development years previously informed M1 research. This is not untouched external confirmation.",
    }
    _write_new(output_dir / f"{phase}-residuals-receipt.json",
               (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8"))
    return frame, receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--declaration", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--phase", choices=tuple(PHASE_SEASONS), default="development")
    parser.add_argument("--fitted-config", type=Path)
    args = parser.parse_args()
    if args.metadata_only:
        result = metadata_inventory()
    else:
        if args.declaration is None or args.output_dir is None:
            parser.error("--declaration and --output-dir are required")
        _, result = build_residual_evidence(args.declaration, args.output_dir,
                                          phase=args.phase, fitted_config_path=args.fitted_config)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
