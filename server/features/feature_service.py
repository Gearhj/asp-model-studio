from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
import time
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from ..core.dataset_store import DATASTORE
from ..core.session_checkpoint import save_checkpoint
from .feature_types import FeatureDefinitionInput, FeatureManifestUpdateRequest


_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SPLIT_FIELD = re.compile(r"(^|_)(split|fold|partition|sample_role)($|_)", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_hash(payload: dict[str, Any]) -> str:
    stable = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return f"fm-{hashlib.sha256(stable.encode('utf-8')).hexdigest()[:16]}"


def _existing_manifest() -> dict[str, Any]:
    manifest = DATASTORE.meta.get("feature_manifest")
    return manifest if isinstance(manifest, dict) else {}


def _base_columns() -> list[str]:
    df = DATASTORE.get_base_df()
    if df is None:
        return []
    prior_materialized = set(DATASTORE.meta.get("materialized_feature_names") or [])
    return [str(column) for column in df.columns if str(column) not in prior_materialized]


def _original_feature_rows() -> list[dict[str, Any]]:
    df = DATASTORE.get_base_df()
    if df is None:
        return []
    selected = set(DATASTORE.get_selected_columns())
    target = str(DATASTORE.target or "")
    prior_materialized = set(DATASTORE.meta.get("materialized_feature_names") or [])
    existing = {row.get("feature_name"): row for row in _existing_manifest().get("features", []) if isinstance(row, dict)}
    rows: list[dict[str, Any]] = []
    for column in df.columns:
        name = str(column)
        if name == target or name in prior_materialized:
            continue
        prior = existing.get(name, {})
        eligible = not _SPLIT_FIELD.search(name)
        rows.append({
            "feature_name": name,
            "display_name": prior.get("display_name") or name,
            "feature_id": prior.get("feature_id") or f"original-{hashlib.sha1(name.encode('utf-8')).hexdigest()[:12]}",
            "origin": "original",
            "source_features": [name],
            "transformation_type": "source_column",
            "formula_or_rule": name,
            "output_datatype": str(df[column].dtype),
            "creation_status": "available",
            "materialization_status": "source",
            "pipeline_status": "not_applicable",
            "eligibility_status": "eligible" if eligible else "excluded",
            "leakage_status": "reviewed" if eligible else "locked",
            "selected": bool(eligible and (not selected or name in selected)),
            "exclusion_reason": "" if eligible else "Split or fold metadata cannot be used as a predictor.",
            "created_at": prior.get("created_at") or _now(),
            "created_by": prior.get("created_by") or "Data Acquisition",
            "transformation_version": "source-v1",
            "dataset_version": str(DATASTORE.meta.get("dataset_version") or "in-memory"),
            "profile_scope": "full_dataset",
            "summary_statistics": prior.get("summary_statistics") or {},
            "evidence_reference": prior.get("evidence_reference"),
            "config": {},
            "user_rationale": prior.get("user_rationale") or "",
        })
    return rows


def _normalize_engineered(item: FeatureDefinitionInput, df_columns: set[str], existing_names: set[str]) -> dict[str, Any]:
    name = item.feature_name.strip()
    if not _VALID_NAME.fullmatch(name):
        raise ValueError(f"Feature name '{name}' must start with a letter or underscore and contain only letters, numbers, or underscores.")
    if name in existing_names or name in df_columns:
        raise ValueError(f"Feature name '{name}' already exists.")
    target = str(DATASTORE.target or "")
    if name == target or target in item.source_features:
        raise ValueError(f"Feature '{name}' cannot use the target column.")
    if any(_SPLIT_FIELD.search(source) for source in item.source_features):
        raise ValueError(f"Feature '{name}' cannot use split or fold metadata.")
    missing_sources = [source for source in item.source_features if source not in df_columns and source not in existing_names]
    if missing_sources:
        raise ValueError(f"Feature '{name}' references unavailable source columns: {', '.join(missing_sources)}.")
    if name in item.source_features:
        raise ValueError(f"Feature '{name}' cannot depend on itself.")
    row = item.model_dump()
    row.update({
        "feature_id": item.feature_id or f"feature-{uuid4().hex}",
        "display_name": item.display_name or name,
        "creation_status": "planned",
        "materialization_status": "not_materialized",
        "pipeline_status": "not_applicable",
        "eligibility_status": "eligible",
        "leakage_status": "reviewed",
        "created_at": _now(),
        "created_by": "Current ATLAS user",
        "transformation_version": "1",
        "dataset_version": str(DATASTORE.meta.get("dataset_version") or "in-memory"),
        "profile_scope": "not_profiled",
        "summary_statistics": {},
        "evidence_reference": None,
    })
    return row


def get_manifest() -> dict[str, Any]:
    existing = _existing_manifest()
    originals = _original_feature_rows()
    engineered = [row for row in existing.get("features", []) if isinstance(row, dict) and row.get("origin") != "original"]
    payload = {
        "dataset_version": str(DATASTORE.meta.get("dataset_version") or existing.get("dataset_version") or "in-memory"),
        "features": originals + engineered,
        "pipeline_steps": existing.get("pipeline_steps", []),
    }
    version = existing.get("manifest_version") or _manifest_hash(payload)
    manifest = {
        "ok": True,
        "manifest_version": version,
        "dataset_version": payload["dataset_version"],
        "features": payload["features"],
        "pipeline_steps": payload["pipeline_steps"],
        "created_at": existing.get("created_at") or _now(),
        "updated_at": existing.get("updated_at") or _now(),
        "split_status": DATASTORE.meta.get("split_status") or "not_created",
    }
    DATASTORE.meta["feature_manifest"] = manifest
    return manifest


def update_manifest(request: FeatureManifestUpdateRequest) -> dict[str, Any]:
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    prior = get_manifest()
    prior_by_id = {row.get("feature_id"): row for row in prior["features"] if row.get("origin") != "original"}
    originals = _original_feature_rows()
    requested_originals = {
        item.feature_name: item
        for item in request.features
        if item.origin == "original"
    }
    for original in originals:
        requested = requested_originals.get(original["feature_name"])
        if requested and original["eligibility_status"] == "eligible":
            original["selected"] = bool(requested.selected)
            original["exclusion_reason"] = requested.exclusion_reason if not requested.selected else ""
    df_columns = set(_base_columns())
    engineered: list[dict[str, Any]] = []
    names: set[str] = set()
    for item in request.features:
        if item.origin == "original":
            continue
        row = _normalize_engineered(item, df_columns, names)
        previous = prior_by_id.get(row["feature_id"])
        if previous and previous.get("feature_name") == row["feature_name"]:
            for key in ("created_at", "materialization_status", "creation_status", "summary_statistics", "profile_scope"):
                row[key] = previous.get(key, row.get(key))
        names.add(row["feature_name"])
        engineered.append(row)
    pipeline_steps = []
    for index, step in enumerate(request.pipeline_steps):
        pipeline_steps.append({
            **step.model_dump(),
            "step_id": step.step_id or f"pipeline-{index + 1}-{uuid4().hex[:8]}",
            "fit_scope": "training_only",
            "status": "configured" if step.enabled else "disabled",
        })
    payload = {
        "dataset_version": request.dataset_version or str(DATASTORE.meta.get("dataset_version") or "in-memory"),
        "features": originals + engineered,
        "pipeline_steps": pipeline_steps,
    }
    version = _manifest_hash(payload)
    changed = version != prior.get("manifest_version")
    manifest = {
        "ok": True,
        "manifest_version": version,
        "dataset_version": payload["dataset_version"],
        "features": payload["features"],
        "pipeline_steps": pipeline_steps,
        "created_at": prior.get("created_at") or _now(),
        "updated_at": _now(),
        "split_status": "stale" if changed and DATASTORE.X_train is not None else prior.get("split_status", "not_created"),
    }
    DATASTORE.meta["feature_manifest"] = manifest
    DATASTORE.meta["selected_columns"] = [
        row["feature_name"]
        for row in manifest["features"]
        if row.get("selected") and row.get("eligibility_status") == "eligible"
    ]
    if changed:
        DATASTORE.meta["split_status"] = "stale" if DATASTORE.X_train is not None else "not_created"
        DATASTORE.reset_splits()
    save_checkpoint()
    return manifest


def _apply_feature(frame: pd.DataFrame, feature: dict[str, Any]) -> pd.Series:
    origin = feature["origin"]
    sources = feature.get("source_features") or []
    config = feature.get("config") or {}
    if origin == "interaction":
        if len(sources) != 2:
            raise ValueError("Interaction features require exactly two source variables.")
        return pd.to_numeric(frame[sources[0]], errors="coerce") * pd.to_numeric(frame[sources[1]], errors="coerce")
    if origin == "polynomial":
        if len(sources) != 1:
            raise ValueError("Polynomial features require one source variable.")
        degree = int(config.get("degree") or 2)
        if degree not in {2, 3}:
            raise ValueError("Polynomial degree must be 2 or 3.")
        return pd.to_numeric(frame[sources[0]], errors="coerce") ** degree
    if origin == "numeric_bin":
        if len(sources) != 1:
            raise ValueError("Numeric bins require one source variable.")
        cut_points = sorted(float(value) for value in config.get("cut_points", []))
        if not cut_points:
            raise ValueError("Numeric bins require at least one cut point.")
        labels = [str(value) for value in config.get("labels", [])]
        if labels and len(labels) != len(cut_points) + 1:
            raise ValueError("Numeric-bin labels must contain one more value than cut points.")
        output = pd.cut(pd.to_numeric(frame[sources[0]], errors="coerce"), bins=[-np.inf, *cut_points, np.inf], labels=labels or None, include_lowest=True)
        if config.get("missing_label"):
            output = output.astype("object").where(output.notna(), str(config["missing_label"]))
        return output
    if origin == "categorical_rule":
        if len(sources) != 1:
            raise ValueError("Categorical rules require one source variable.")
        source = frame[sources[0]]
        output = pd.Series(str(config.get("else_label") or "Other"), index=frame.index, dtype="object")
        for rule in config.get("rules", []):
            op = str(rule.get("op") or "equals")
            value = rule.get("value")
            if op == "equals":
                mask = source.astype(str) == str(value)
            elif op == "contains":
                mask = source.astype(str).str.contains(str(value), case=False, na=False)
            elif op == "greater_than":
                mask = pd.to_numeric(source, errors="coerce") > float(value)
            elif op == "less_than":
                mask = pd.to_numeric(source, errors="coerce") < float(value)
            elif op == "is_missing":
                mask = source.isna()
            else:
                raise ValueError(f"Unsupported categorical rule operator '{op}'.")
            output.loc[mask] = str(rule.get("then_label") or "Matched")
        return output
    if origin == "arithmetic":
        if len(sources) != 2:
            raise ValueError("Arithmetic features require exactly two source variables.")
        left = pd.to_numeric(frame[sources[0]], errors="coerce")
        right = pd.to_numeric(frame[sources[1]], errors="coerce")
        operation = str(config.get("operation") or "add")
        if operation == "add":
            return left + right
        if operation == "subtract":
            return left - right
        if operation == "multiply":
            return left * right
        if operation == "divide":
            return left / right.replace(0, np.nan)
        raise ValueError(f"Unsupported arithmetic operation '{operation}'.")
    if origin == "date-derived":
        if len(sources) != 1:
            raise ValueError("Date-derived features require one source variable.")
        parsed = pd.to_datetime(frame[sources[0]], errors="coerce")
        component = str(config.get("component") or "year")
        if component == "year":
            return parsed.dt.year
        if component == "month":
            return parsed.dt.month
        if component == "day_of_week":
            return parsed.dt.dayofweek
        if component == "quarter":
            return parsed.dt.quarter
        raise ValueError(f"Unsupported date component '{component}'.")
    raise ValueError(f"Feature origin '{origin}' is not a deterministic materialization type.")


def preview_features(features: list[FeatureDefinitionInput], limit: int) -> dict[str, Any]:
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    frame = df.head(limit).copy()
    outputs: list[str] = []
    for item in features:
        if item.origin == "original":
            continue
        normalized = _normalize_engineered(item, set(frame.columns), set(outputs))
        frame[normalized["feature_name"]] = _apply_feature(frame, normalized)
        outputs.append(normalized["feature_name"])
    columns = [*dict.fromkeys(source for item in features for source in item.source_features if source in frame.columns), *outputs]
    rows = frame[columns].replace({np.nan: None}).to_dict(orient="records") if columns else []
    return {
        "ok": True,
        "scope": "rendered_sample",
        "registered_row_count": int(len(df)),
        "preview_row_count": int(len(frame)),
        "columns": columns,
        "created_features": outputs,
        "rows": rows,
    }


def materialize_manifest(expected_version: str = "") -> dict[str, Any]:
    started = time.perf_counter()
    manifest = get_manifest()
    if expected_version and expected_version != manifest["manifest_version"]:
        raise ValueError("The feature plan changed. Refresh the manifest before materializing features.")
    df = DATASTORE.get_base_df()
    if df is None or df.empty:
        raise ValueError("No full backend dataset is loaded.")
    prior_materialized = set(DATASTORE.meta.get("materialized_feature_names") or [])
    frame = df.drop(columns=[column for column in prior_materialized if column in df.columns], errors="ignore").copy()
    materialized: list[str] = []
    failures: list[dict[str, str]] = []
    for feature in manifest["features"]:
        if feature.get("origin") == "original":
            continue
        try:
            frame[feature["feature_name"]] = _apply_feature(frame, feature)
            feature["creation_status"] = "created"
            feature["materialization_status"] = "materialized"
            feature["profile_scope"] = "full_dataset"
            values = frame[feature["feature_name"]]
            numeric = pd.to_numeric(values, errors="coerce").dropna()
            feature["summary_statistics"] = {
                "row_count": int(len(values)),
                "missing_count": int(values.isna().sum()),
                "distinct_count": int(values.nunique(dropna=True)),
                "mean": float(numeric.mean()) if len(numeric) else None,
                "minimum": float(numeric.min()) if len(numeric) else None,
                "maximum": float(numeric.max()) if len(numeric) else None,
            }
            materialized.append(feature["feature_name"])
        except Exception as exc:
            feature["creation_status"] = "failed"
            feature["materialization_status"] = "failed"
            failures.append({"feature": feature["feature_name"], "error": str(exc)})
    if failures:
        raise ValueError("Feature materialization failed: " + "; ".join(f"{row['feature']}: {row['error']}" for row in failures))
    DATASTORE.set_processed(frame)
    DATASTORE.meta["processed_stage"] = "feature_engineering"
    DATASTORE.meta["materialized_feature_names"] = materialized
    selected = [feature["feature_name"] for feature in manifest["features"] if feature.get("selected") and feature.get("eligibility_status") == "eligible"]
    DATASTORE.meta["selected_columns"] = selected
    DATASTORE.meta["split_status"] = "not_created"
    manifest["updated_at"] = _now()
    manifest["features"] = manifest["features"]
    manifest["split_status"] = "not_created"
    DATASTORE.meta["feature_manifest"] = manifest
    save_checkpoint()
    return {
        "ok": True,
        "manifest_version": manifest["manifest_version"],
        "dataset_version": manifest["dataset_version"],
        "row_count": int(len(frame)),
        "original_feature_count": sum(1 for row in manifest["features"] if row.get("origin") == "original"),
        "engineered_feature_count": len(materialized),
        "materialized_features": materialized,
        "selected_features": selected,
        "duration_ms": int((time.perf_counter() - started) * 1000),
    }


def delete_feature(feature_id: str) -> dict[str, Any]:
    manifest = get_manifest()
    target = next((row for row in manifest["features"] if row.get("feature_id") == feature_id), None)
    if not target:
        raise ValueError("Feature was not found in the current manifest.")
    if target.get("origin") == "original":
        raise ValueError("Source features cannot be deleted. Deselect them in the governed predictor review instead.")
    remaining = [row for row in manifest["features"] if row.get("feature_id") != feature_id and row.get("origin") != "original"]
    request = FeatureManifestUpdateRequest(features=[FeatureDefinitionInput(**row) for row in remaining], pipeline_steps=manifest.get("pipeline_steps", []), dataset_version=manifest.get("dataset_version", ""))
    return update_manifest(request)
