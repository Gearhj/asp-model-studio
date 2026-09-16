"""End-to-end Phase 7B2 Gold build and fixed research experiment orchestration."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

import joblib
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from ..sports_datasets.consumer import canonical_json_bytes, sha256_bytes
from ..sports_modeling.feature_contract import FEATURE_NAMES
from .contracts import (
    BASE_FEATURE_SPECIFICATION,
    BATTER_HISTORY_FEATURES,
    FEATURE_SPECIFICATION,
    GOLD_FEATURES,
    GOLD_GOVERNANCE,
    MATCHUP_FEATURES,
    PITCHER_HISTORY_FEATURES,
    CONTACT_QUALITY_LIMITATION,
)
from .features import (
    aggregate_pitch_history,
    assemble_gold_frame,
    build_advanced_features,
    feature_quality_report,
    prepare_pa_history,
)
from .models import run_fixed_experiment_suite
from .pa_bridge import PaBridgeResult, bridge_plate_appearances
from .publication import implementation_identity, publish_gold, verify_gold
from .silver_inputs import read_verified_columns, resolve_current_silver, verified_gen3_research


TARGET_COLUMNS = (
    "plate_appearance_id", "game_id", "game_date", "season", "outcome",
    "batter_canonical_player_uuid", "pitcher_canonical_player_uuid", *FEATURE_NAMES,
)
PA_COLUMNS = (
    "canonicalPaId", "canonicalGameId", "mlbamGamePk", "atBatNumber",
    "batterCanonicalPlayerId", "pitcherCanonicalPlayerId", "season", "gameDate",
    "inning", "inningTopBot", "stand", "pThrows", "paEvent",
)
PITCH_COLUMNS = ("canonicalPaId", "pitchType", "releaseSpeed", "pitchResultType")

_EXPECTED_BRIDGE = {
    "counts": {
        "targetRows": 730_284,
        "matchedRows": 716_813,
        "excludedRows": 13_471,
        "naturallyUniqueRows": 716_263,
        "occurrenceResolvedRows": 550,
        "postOrdinalAmbiguousRows": 0,
        "duplicateOutputRows": 0,
        "duplicateOutputPlateAppearanceIds": 0,
        "duplicateOutputCanonicalPaIds": 0,
    },
    "development": {
        "targetRows": 547_835,
        "matchedRows": 536_102,
        "excludedRows": 11_733,
        "occurrenceResolvedRows": 418,
        "postOrdinalAmbiguousRows": 0,
    },
    "validation": {
        "targetRows": 182_449,
        "matchedRows": 180_711,
        "excludedRows": 1_738,
        "occurrenceResolvedRows": 132,
        "postOrdinalAmbiguousRows": 0,
    },
}


class GoldPipelineError(RuntimeError):
    """The fixed Gold build or experiment could not complete honestly."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / f".tmp-{uuid.uuid4().hex}.json"
    temp.write_bytes(canonical_json_bytes(_json_safe(value)))
    os.replace(temp, path)


def _connection_report(bridge: PaBridgeResult) -> dict[str, Any]:
    report = dict(bridge.report)
    reasons = report.get("exclusionReasonCounts", {})
    split_rows: dict[str, Any] = {}
    for key, source in (("development", report["splits"]["development"]), ("validation", report["splits"]["validation"])):
        subset = bridge.exclusions[bridge.exclusions["split"].eq(key.upper())]
        details = subset["reasonDetail"].fillna("").astype(str) if not subset.empty else pd.Series(dtype=str)
        split_rows[key] = {
            "governedTargetRows": int(source["targetRows"]),
            "exactSilverPaMatches": int(source["matchedRows"]),
            "unmatchedTargetRows": int(source["excludedRows"]),
            "ambiguousMatches": int(source["postOrdinalAmbiguousRows"]),
            "duplicateTargetIdentities": 0,
            "duplicateSilverIdentities": 0,
            "rowsWithUnresolvedBatterIdentity": int(details.str.contains("BATTER", regex=False).sum()),
            "rowsWithUnresolvedPitcherIdentity": int(details.str.contains("PITCHER", regex=False).sum()),
            "rowsWithUnresolvedGameIdentity": int(subset["reasonCode"].eq("GAME_IDENTITY_UNMAPPED").sum()) if not subset.empty else 0,
            "occurrenceResolvedRows": int(source["occurrenceResolvedRows"]),
        }
    report.update({
        "datasetName": "gold_mlb_pa_v1",
        "splitReconciliation": split_rows,
        "allRowsReconciled": int(report["counts"]["matchedRows"] + report["counts"]["excludedRows"])
        == int(report["counts"]["targetRows"]),
        "exclusionReasonCounts": dict(reasons),
    })
    return report


def _assert_expected_bridge(report: Mapping[str, Any]) -> None:
    """Lock the measured full-corpus connection before feature construction."""

    for key, expected in _EXPECTED_BRIDGE["counts"].items():
        actual = int(report["counts"].get(key, -1))
        if actual != expected:
            raise GoldPipelineError(f"Gold PA bridge {key} differs: {actual} != {expected}")
    for split in ("development", "validation"):
        observed = report["splits"][split]
        for key, expected in _EXPECTED_BRIDGE[split].items():
            actual = int(observed.get(key, -1))
            if actual != expected:
                raise GoldPipelineError(
                    f"Gold PA bridge {split}.{key} differs: {actual} != {expected}"
                )


def _exclusion_bytes(exclusions: pd.DataFrame) -> bytes:
    ordered = exclusions.sort_values(
        ["season", "game_id", "plate_appearance_id", "reasonCode"], kind="mergesort", na_position="last"
    ).reset_index(drop=True)
    table = pa.Table.from_pandas(ordered, preserve_index=False)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, compression="zstd", compression_level=9, use_dictionary=False)
    return sink.getvalue().to_pybytes()


def build_gold_v1(*, silver_root: Path, gold_root: Path) -> dict[str, Any]:
    """Build the full matched 2021--2024 Gold view from verified authorities."""

    started = time.perf_counter()
    target_handle = verified_gen3_research()
    if target_handle.rows != 730_284:
        raise GoldPipelineError(f"governed target row count differs: {target_handle.rows}")
    target_table = pq.read_table(target_handle.path, columns=list(TARGET_COLUMNS))
    target = target_table.to_pandas()
    observed = {int(key): int(value) for key, value in target.groupby("season").size().items()}
    expected = {2021: 181_752, 2022: 181_979, 2023: 184_104, 2024: 182_449}
    if observed != expected:
        raise GoldPipelineError(f"governed target season rows differ: {observed}")

    names = (
        "bridge_game_identity", "dim_player", "fact_statcast_plate_appearance", "fact_statcast_pitch",
    )
    handles = {name: resolve_current_silver(Path(silver_root), name) for name in names}
    games = read_verified_columns(
        handles["bridge_game_identity"],
        ["canonicalGameId", "retrosheetGameId", "resolutionStatus"],
    ).to_pandas()
    players = read_verified_columns(
        handles["dim_player"], ["canonicalPlayerId", "chadwickKeyUuid", "resolutionStatus"]
    ).to_pandas()
    pa_table = read_verified_columns(
        handles["fact_statcast_plate_appearance"], PA_COLUMNS, seasons=(2019, 2020, 2021, 2022, 2023, 2024)
    )
    pa_frame = pa_table.to_pandas()
    modeling_pa = pa_frame[pd.to_numeric(pa_frame["season"], errors="raise").isin([2021, 2022, 2023, 2024])]
    bridge = bridge_plate_appearances(target, modeling_pa, games, players)
    connection = _connection_report(bridge)
    if not connection["allRowsReconciled"] or bridge.matched.empty:
        raise GoldPipelineError("Silver-to-target PA bridge did not reconcile")
    _assert_expected_bridge(bridge.report)

    mapping_columns = [
        "plate_appearance_id", "canonicalPaId", "canonicalGameId",
        "batterCanonicalPlayerId", "pitcherCanonicalPlayerId",
    ]
    matched = target.merge(
        bridge.matched[mapping_columns], on="plate_appearance_id", how="inner", validate="one_to_one"
    )
    if len(matched) != len(bridge.matched):
        raise GoldPipelineError("bridge mapping did not rejoin governed target one-to-one")
    silver_dates = pa_frame.loc[:, ["canonicalPaId", "gameDate"]].copy()
    if silver_dates["canonicalPaId"].duplicated().any():
        raise GoldPipelineError("Silver PA date authority contains duplicate canonical PA IDs")
    silver_dates = silver_dates.rename(columns={"gameDate": "_silverGameDate"})
    matched = matched.merge(silver_dates, on="canonicalPaId", how="left", validate="one_to_one")
    target_dates = pd.to_datetime(matched["game_date"], format="%Y-%m-%d", errors="raise")
    silver_target_dates = pd.to_datetime(
        matched["_silverGameDate"], format="%Y-%m-%d", errors="raise"
    )
    date_mismatch = ~target_dates.eq(silver_target_dates)
    if bool(date_mismatch.any()):
        raise GoldPipelineError(
            f"target/Silver game-date authority differs for {int(date_mismatch.sum())} matched PAs"
        )
    matched = matched.drop(columns=["_silverGameDate"])
    connection["crossSourceDateAgreement"] = {
        "rowsCompared": int(len(matched)),
        "mismatchRows": 0,
    }

    pitch_aggregates = aggregate_pitch_history(handles["fact_statcast_pitch"].child_paths)
    history = prepare_pa_history(pa_frame, pitch_aggregates)
    advanced = build_advanced_features(history, matched)
    gold_frame = assemble_gold_frame(matched, advanced)
    quality = feature_quality_report(gold_frame)

    exclusion_data = _exclusion_bytes(bridge.exclusions)
    connection["exclusionLedger"] = {
        "contract": "MLB_GOLD_PA_BRIDGE_EXCLUSION_LEDGER_V1",
        "rows": len(bridge.exclusions),
        "sha256": hashlib.sha256(exclusion_data).hexdigest(),
    }
    source_inputs = {
        "governedGen3Target": target_handle.identity(),
        "currentSilver": {name: handle.identity() for name, handle in sorted(handles.items())},
        "silverQuarantineUnchanged": True,
    }
    code_paths = [
        Path(__file__), Path(__file__).with_name("contracts.py"), Path(__file__).with_name("features.py"),
        Path(__file__).with_name("pa_bridge.py"), Path(__file__).with_name("publication.py"),
        Path(__file__).with_name("silver_inputs.py"), Path(__file__).with_name("models.py"),
        Path(__file__).resolve().parents[2] / "scripts" / "phase7b_research.py",
    ]
    implementation = implementation_identity(code_paths)
    table = pa.Table.from_pandas(gold_frame, preserve_index=False)
    published = publish_gold(
        Path(gold_root), table, source_inputs=source_inputs, connection_report=connection,
        feature_quality=quality, implementation=implementation,
    )
    object_sha = published["logicalContentSha256"]
    evidence_root = Path(gold_root) / "evidence" / object_sha
    evidence_root.mkdir(parents=True, exist_ok=True)
    (evidence_root / "bridge-exclusions.parquet").write_bytes(exclusion_data)
    _atomic_json(evidence_root / "connection-report.json", connection)
    _atomic_json(evidence_root / "feature-specification.json", {
        "schemaVersion": "MLB_GOLD_V1_FEATURE_SPECIFICATION_V1",
        "featureOrder": list(GOLD_FEATURES),
        "baseFeatures": {name: dict(BASE_FEATURE_SPECIFICATION[name]) for name in FEATURE_NAMES},
        "advancedFeatures": {name: dict(FEATURE_SPECIFICATION[name]) for name in FEATURE_SPECIFICATION},
        "limitations": [dict(CONTACT_QUALITY_LIMITATION)],
    })
    summary = {
        "schemaVersion": "MLB_GOLD_V1_BUILD_RESULT_V1",
        "status": "COMPLETE",
        "dataset": published,
        "connection": connection,
        "quality": quality,
        "sourceInputs": source_inputs,
        "implementationIdentity": implementation,
        "elapsedSeconds": float(time.perf_counter() - started),
        **GOLD_GOVERNANCE,
    }
    _atomic_json(evidence_root / "build-result.json", summary)
    return summary


def _experiment_markdown(payload: Mapping[str, Any]) -> str:
    rows = [
        "# Phase 7B2 Gold V1 fixed-model experiment",
        "",
        f"Gold dataset: `{payload['goldDatasetVersionId']}`",
        "",
        "| Rank | Model | Status | Features | 2024 log loss | Brier | ECE | Accuracy | Macro-F1 |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in payload["leaderboard"]:
        def show(key: str) -> str:
            value = item.get(key)
            return "—" if value is None else f"{float(value):.9f}"
        rows.append(
            f"| {item.get('rank') or '—'} | {item['label']} | {item['status']} | {item['feature_count']} | "
            f"{show('logLoss')} | {show('brierScore')} | {show('topLabelEce')} | "
            f"{show('top1Accuracy')} | {show('macroF1')} |"
        )
    rows.extend([
        "", "No model was promoted. Gold remains research-only and not champion-eligible.", "",
    ])
    return "\n".join(rows)


def run_gold_experiment(*, gold_root: Path, include_xgboost: bool = True) -> dict[str, Any]:
    """Run and persist the fixed suite without registering or promoting a model."""

    started = time.perf_counter()
    verified = verify_gold(Path(gold_root))
    frame = pq.read_table(verified["path"]).to_pandas()
    result = run_fixed_experiment_suite(
        frame,
        base_features=FEATURE_NAMES,
        batter_features=BATTER_HISTORY_FEATURES,
        pitcher_features=PITCHER_HISTORY_FEATURES,
        matchup_features=MATCHUP_FEATURES,
        include_xgboost=include_xgboost,
    )
    request = {
        "schemaVersion": "MLB_GOLD_FIXED_EXPERIMENT_REQUEST_V1",
        "goldDatasetVersionId": verified["datasetVersionId"],
        "goldLogicalContentSha256": verified["logicalContentSha256"],
        "includeXgboost": bool(include_xgboost),
        "developmentSeasons": [2021, 2022, 2023],
        "validationSeason": 2024,
        "featureOrder": list(GOLD_FEATURES),
        "promotionRequested": False,
    }
    experiment_sha = sha256_bytes(canonical_json_bytes(request))
    final = Path(gold_root) / "experiments" / "sha256" / experiment_sha
    staging = final.parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    model_inventory: dict[str, Any] = {}
    try:
        models_dir = staging / "models"
        models_dir.mkdir()
        for model_id, artifact in sorted(result.models.items()):
            path = models_dir / f"{model_id}.joblib"
            joblib.dump(artifact, path, compress=3)
            data = path.read_bytes()
            model_inventory[model_id] = {"file": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        payload = {
            "schemaVersion": "MLB_GOLD_FIXED_EXPERIMENT_RESULT_V1",
            **request,
            "experimentSha256": experiment_sha,
            "developmentRows": result.development_rows,
            "validationRows": result.validation_rows,
            "classOrder": list(result.class_order),
            "leaderboard": result.leaderboard,
            "featureFamilyComparisons": result.ablations,
            "failures": result.failures,
            "modelArtifacts": model_inventory,
            "elapsedSeconds": float(time.perf_counter() - started),
            "status": "RESEARCH_ONLY_COMPLETE",
            "promotionPerformed": False,
            "championChanged": False,
        }
        (staging / "leaderboard.json").write_bytes(canonical_json_bytes(_json_safe(payload)))
        (staging / "experiment-report.md").write_text(_experiment_markdown(payload), encoding="utf-8", newline="\n")
        (staging / "manifest.json").write_bytes(canonical_json_bytes({
            "experimentSha256": experiment_sha,
            "request": request,
            "leaderboardSha256": hashlib.sha256((staging / "leaderboard.json").read_bytes()).hexdigest(),
            "modelArtifacts": model_inventory,
            "status": "RESEARCH_ONLY",
            "promotionEligible": False,
            "championEligible": False,
        }))
        final.parent.mkdir(parents=True, exist_ok=True)
        if not final.exists():
            os.replace(staging, final)
        else:
            import shutil
            shutil.rmtree(staging)
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging, ignore_errors=True)
    return json.loads((final / "leaderboard.json").read_text(encoding="utf-8"))


__all__ = ["GoldPipelineError", "build_gold_v1", "run_gold_experiment"]
