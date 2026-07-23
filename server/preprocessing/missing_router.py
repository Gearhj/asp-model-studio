from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.dataset_store import DATASTORE
from ..core.json_safety import json_safe
from ..core.modeling_scope import authorize_modeling_scope
from ..core.session_checkpoint import save_checkpoint
from ..security.security_store import require_user
from .outlier_service import outlier_service


router = APIRouter()
MISSING_STRINGS = {"", "na", "n/a", "null", "none", "nan", "missing"}


class MissingRule(BaseModel):
    strategy: str = "None"
    constantValue: Optional[Any] = None


class MissingApplyRequest(BaseModel):
    project_id: str
    config: Dict[str, MissingRule] = Field(default_factory=dict)
    event_value: Any = None
    problem_type: str | None = None


def _normalize_missing(df: pd.DataFrame) -> pd.DataFrame:
    work = df.copy()
    for col in work.columns:
        if pd.api.types.is_object_dtype(work[col]) or pd.api.types.is_string_dtype(work[col]):
            text = work[col].astype("string")
            work.loc[text.str.strip().str.lower().isin(MISSING_STRINGS), col] = np.nan
    return work


def _feature_columns(df: pd.DataFrame) -> List[str]:
    return [str(col) for col in df.columns if not DATASTORE.target or str(col) != str(DATASTORE.target)]


def _is_numeric_like(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    non_missing = series.dropna()
    return bool(len(non_missing) and pd.to_numeric(non_missing, errors="coerce").notna().mean() >= 0.8)


def _display_dtype(series: pd.Series) -> str:
    return "float64" if _is_numeric_like(series) else str(series.dtype)


def _event_value(target: pd.Series, requested: Any) -> Any:
    if requested is not None and str(requested) != "":
        return requested
    return next((value for value in target.dropna().unique() if str(value) == "1"), None)


def _config_payload(config: Dict[str, MissingRule]) -> dict[str, dict[str, Any]]:
    return {key: value.dict() for key, value in sorted(config.items())}


def _config_signature(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _pre_missing_df() -> pd.DataFrame:
    if DATASTORE.meta.get("processed_stage") == "outliers" and DATASTORE.processed_df is not None:
        current = DATASTORE.get_active_df()
        if current is not None and not current.empty:
            return current

    source = DATASTORE.get_raw_active_df()
    if source is None or source.empty:
        raise HTTPException(status_code=400, detail="No full registered dataset is loaded.")
    prior = DATASTORE.meta.get("outlier_application")
    if isinstance(prior, dict) and isinstance(prior.get("config"), dict):
        try:
            source, _ = outlier_service.apply(
                source,
                config=prior["config"],
                global_method=str(prior.get("global_method") or "IQR_1_5"),
                target=DATASTORE.target,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"The saved outlier treatment could not be reconstructed: {exc}") from exc
    return source


def _informative_missingness(
    feature: pd.Series,
    target: pd.Series | None,
    problem_type: str,
    event_value: Any,
) -> dict[str, Any]:
    missing = feature.isna()
    if target is None or not missing.any() or not (~missing).any():
        return {"informative": False, "missing_target_metric": None, "present_target_metric": None, "difference": None}
    if problem_type == "regression":
        numeric_target = pd.to_numeric(target, errors="coerce")
        missing_mean = numeric_target[missing].mean()
        present_mean = numeric_target[~missing].mean()
        scale = numeric_target.std(ddof=0)
        if pd.isna(missing_mean) or pd.isna(present_mean):
            return {"informative": False, "missing_target_metric": None, "present_target_metric": None, "difference": None}
        difference = float(missing_mean - present_mean)
        standardized = abs(difference) / float(scale) if pd.notna(scale) and float(scale) > 0 else 0.0
        return {
            "informative": standardized >= 0.1,
            "missing_target_metric": float(missing_mean),
            "present_target_metric": float(present_mean),
            "difference": difference,
            "standardized_difference": standardized,
        }

    if event_value is None:
        return {"informative": False, "missing_target_metric": None, "present_target_metric": None, "difference": None}
    valid = target.notna()
    event = target.astype(str) == str(event_value)
    missing_rate = float(event[missing & valid].mean()) if int((missing & valid).sum()) else None
    present_rate = float(event[(~missing) & valid].mean()) if int(((~missing) & valid).sum()) else None
    difference = missing_rate - present_rate if missing_rate is not None and present_rate is not None else None
    return {
        "informative": bool(difference is not None and abs(difference) >= 0.02),
        "missing_target_metric": missing_rate,
        "present_target_metric": present_rate,
        "difference": difference,
    }


@router.get("/summary")
def missing_summary(
    project_id: str = Query(...),
    event_value: Any = Query(default=None),
    problem_type: str | None = Query(default=None),
    user: Dict[str, Any] = Depends(require_user),
) -> Dict[str, Any]:
    authorize_modeling_scope(user, project_id, "view")
    work = _normalize_missing(_pre_missing_df())
    target = DATASTORE.target if DATASTORE.target in work.columns else None
    y = work[target] if target else None
    resolved_problem = problem_type if problem_type in {"classification", "regression"} else "classification"
    resolved_event = _event_value(y, event_value) if y is not None and resolved_problem == "classification" else None
    event_rate = None
    if y is not None and resolved_event is not None:
        valid = y.notna()
        event_rate = float((y[valid].astype(str) == str(resolved_event)).mean()) if int(valid.sum()) else None

    stats: Dict[str, Any] = {}
    columns: List[Dict[str, Any]] = []
    total = int(len(work))
    for col in _feature_columns(work):
        missing = int(work[col].isna().sum())
        relationship = _informative_missingness(work[col], y, resolved_problem, resolved_event)
        stats[col] = {
            "missing": missing,
            "missingPct": float((missing / total) * 100) if total else 0.0,
            "total": total,
            **relationship,
        }
        columns.append({"name": col, "dtype": _display_dtype(work[col]), "role": "feature"})
    return json_safe({
        "ok": True,
        "scope": "full_dataset",
        "rows": total,
        "columns": columns,
        "stats": stats,
        "target": target,
        "problem_type": resolved_problem,
        "event_value": resolved_event,
        "event_rate": event_rate,
        "rare_event": bool(event_rate is not None and event_rate < 0.05),
        "source_stage": "outlier_treated" if DATASTORE.meta.get("outlier_application") else "registered_dataset",
        "dataset_version": DATASTORE.meta.get("dataset_version") or "unversioned",
        "application": DATASTORE.meta.get("missing_application"),
    })


@router.post("/apply")
def apply_missing_values(request: MissingApplyRequest, user: Dict[str, Any] = Depends(require_user)) -> Dict[str, Any]:
    authorize_modeling_scope(user, request.project_id, "edit")
    work = _normalize_missing(_pre_missing_df())
    before = int(work.isna().sum().sum())
    features = set(_feature_columns(work))
    dropped_rows = 0
    applied: List[Dict[str, Any]] = []

    for col, rule in request.config.items():
        if col not in work.columns or col not in features:
            continue
        strategy = str(rule.strategy or "None").strip().lower()
        if strategy == "none":
            continue
        missing_before = int(work[col].isna().sum())
        if missing_before == 0:
            continue
        if strategy == "drop row":
            row_count = int(len(work))
            work = work.loc[~work[col].isna()].copy()
            removed = row_count - int(len(work))
            dropped_rows += removed
            applied.append({"feature": col, "strategy": rule.strategy, "filled": 0, "dropped_rows": removed})
            continue

        series = work[col]
        numeric = _is_numeric_like(series)
        if numeric:
            series = pd.to_numeric(series, errors="coerce")
            work[col] = series
        fill_value: Any = None
        if strategy == "mean" and numeric:
            fill_value = series.mean()
        elif strategy == "median" and numeric:
            fill_value = series.median()
        elif strategy in {"mode", "mean", "median"}:
            mode = series.dropna().mode()
            fill_value = mode.iloc[0] if len(mode) else ""
        elif strategy == "constant":
            fill_value = rule.constantValue if rule.constantValue is not None else ""
            if numeric:
                fill_value = pd.to_numeric(pd.Series([fill_value]), errors="coerce").iloc[0]
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported missing-value strategy '{rule.strategy}' for {col}.")
        if pd.isna(fill_value):
            raise HTTPException(status_code=400, detail=f"The selected strategy for {col} did not produce a valid fill value.")
        work[col] = series.fillna(fill_value)
        applied.append({"feature": col, "strategy": rule.strategy, "filled": missing_before, "value": str(fill_value)})

    payload = _config_payload(request.config)
    application = {
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": DATASTORE.meta.get("dataset_version") or "unversioned",
        "config": payload,
        "config_signature": _config_signature(payload),
        "source_stage": "outlier_treated" if DATASTORE.meta.get("outlier_application") else "registered_dataset",
        "rows_before": int(len(_pre_missing_df())),
        "rows_after": int(len(work)),
        "missing_before": before,
        "missing_after": int(work.isna().sum().sum()),
        "dropped_rows": int(dropped_rows),
        "treatments": applied,
    }
    DATASTORE.set_processed(work)
    DATASTORE.meta["processed_stage"] = "missing_values"
    DATASTORE.meta["missing_config"] = payload
    DATASTORE.meta["missing_application"] = application
    DATASTORE.meta["split_status"] = "stale"
    manifest = DATASTORE.meta.get("feature_manifest")
    if isinstance(manifest, dict):
        manifest["split_status"] = "stale"
    if not save_checkpoint():
        raise HTTPException(status_code=500, detail="Missing-value treatments were applied, but ATLAS could not persist the workflow checkpoint.")
    return json_safe({"ok": True, "scope": "full_dataset", "application": application})
