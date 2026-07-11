from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import HTTPException

from ..datasets.dataset_registry import latest_version_id, require_dataset, version_dir
from ..evidence.evidence_store import upsert_evidence
from .leakage_guard import validate_predictors
from .woe_iv_engine import get_analysis, get_project_analysis


SCORECARD_ROOT = Path(__file__).resolve().parents[1] / "artifacts" / "credit_risk" / "scorecards"
MODELS_ROOT = SCORECARD_ROOT / "models"
REGISTRY_PATH = SCORECARD_ROOT / "scorecard_registry.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_store() -> None:
    MODELS_ROOT.mkdir(parents=True, exist_ok=True)
    if not REGISTRY_PATH.exists():
        write_json(REGISTRY_PATH, {"models": []})


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def read_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def model_path(model_id: str) -> Path:
    return MODELS_ROOT / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', model_id)}.json"


def load_registry() -> List[Dict[str, Any]]:
    ensure_store()
    payload = read_json(REGISTRY_PATH, {"models": []})
    return payload.get("models", []) if isinstance(payload, dict) else []


def save_registry(rows: List[Dict[str, Any]]) -> None:
    write_json(REGISTRY_PATH, {"models": sorted(rows, key=lambda row: str(row.get("updatedAt") or ""), reverse=True)})


def compact_model(model: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "modelId": model.get("modelId"),
        "projectId": model.get("projectId"),
        "datasetId": model.get("datasetId"),
        "datasetVersionId": model.get("datasetVersionId"),
        "targetColumn": model.get("targetColumn"),
        "eventValue": model.get("eventValue"),
        "modelType": model.get("modelType"),
        "champion": bool(model.get("champion")),
        "auc": model.get("metrics", {}).get("auc"),
        "ks": model.get("metrics", {}).get("ks"),
        "gini": model.get("metrics", {}).get("gini"),
        "pdo": model.get("pdoSettings", {}).get("pdo"),
        "baseScore": model.get("pdoSettings", {}).get("baseScore"),
        "baseOdds": model.get("pdoSettings", {}).get("baseOdds"),
        "selectedCutoff": model.get("selectedCutoff"),
        "status": "Complete" if model.get("metrics", {}).get("auc") is not None else "Needs Review",
        "createdAt": model.get("createdAt"),
        "updatedAt": model.get("updatedAt"),
    }


def save_scorecard_model(model: Dict[str, Any]) -> Dict[str, Any]:
    ensure_store()
    timestamp = now_iso()
    model["updatedAt"] = timestamp
    model["createdAt"] = model.get("createdAt") or timestamp
    write_json(model_path(str(model["modelId"])), model)
    registry = [row for row in load_registry() if row.get("modelId") != model.get("modelId")]
    registry.append(compact_model(model))
    save_registry(registry)
    return model


def get_scorecard_model(model_id: str) -> Optional[Dict[str, Any]]:
    found = read_json(model_path(model_id), None)
    return found if isinstance(found, dict) else None


def get_project_scorecard(project_id: str) -> Optional[Dict[str, Any]]:
    match = next((row for row in load_registry() if row.get("projectId") == project_id), None)
    return get_scorecard_model(str(match.get("modelId"))) if match else None


def load_dataset_frame(dataset_id: str, version_id: Optional[str]) -> tuple[Dict[str, Any], str, pd.DataFrame]:
    dataset = require_dataset(dataset_id)
    resolved_version = version_id or latest_version_id(dataset)
    if not resolved_version:
        raise HTTPException(status_code=400, detail="Dataset has no version available for scorecard training.")
    full_path = version_dir(dataset_id, resolved_version) / "data_full.csv"
    if not full_path.exists():
        raise HTTPException(status_code=409, detail="Full dataset artifact is required for governed scorecard training. Re-register the dataset so ATLAS can materialize data_full.csv; sample artifacts are not valid for reporting.")
    df = pd.read_csv(full_path)
    if df.empty:
        raise HTTPException(status_code=400, detail="Dataset full artifact has no rows.")
    return dataset, resolved_version, df


def train_scorecard(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        from sklearn.metrics import log_loss, roc_auc_score
        from sklearn.model_selection import train_test_split
    except Exception as exc:
        raise HTTPException(status_code=501, detail=f"Logistic scorecard training requires sklearn in the local backend environment. {exc}")

    dataset, resolved_version, df = load_dataset_frame(str(payload.get("datasetId")), payload.get("datasetVersionId"))
    target = str(payload.get("targetColumn") or "")
    if target not in df.columns:
        raise HTTPException(status_code=400, detail=f"Target column {target!r} was not found in the dataset.")
    event_value = payload.get("eventValue")
    y = df[target].astype(str).str.strip().eq(str(event_value)).astype(int)
    if y.nunique() < 2:
        raise HTTPException(status_code=400, detail="Target has one class only. Scorecard training requires both good and bad outcomes.")

    woe_analysis = get_analysis(str(payload.get("woeAnalysisId"))) if payload.get("woeAnalysisId") else get_project_analysis(str(payload.get("projectId")))
    requested_selected = [str(item) for item in payload.get("selectedVariables") or []]
    selected = validate_predictors(
        requested_selected,
        target=target,
        dataset_meta=dataset,
        columns=df.columns,
        explicit=bool(requested_selected),
    )
    train_raw = bool(payload.get("trainRawBaseline"))
    warnings: List[str] = []
    if not selected and woe_analysis:
        selected = [
            row.get("variable")
            for row in woe_analysis.get("variableSummaries") or []
            if 0.02 <= float(row.get("iv") or 0) < 0.50 and row.get("status") != "error"
        ][:20]
    selected = validate_predictors(selected, target=target, dataset_meta=dataset, columns=df.columns, explicit=False)
    if not selected:
        raise HTTPException(status_code=400, detail="No usable scorecard variables were selected.")

    if woe_analysis and not train_raw:
        X, transform_summary, selected = transform_with_woe(df, selected, woe_analysis)
        model_label = payload.get("modelType") or "Logistic Scorecard"
    elif train_raw:
        X = raw_design_matrix(df, selected)
        transform_summary = {
            "mode": "raw_logistic_baseline",
            "rows": int(len(X)),
            "variables": list(X.columns),
            "missingWoeAssignments": 0,
            "unseenCategories": 0,
            "variablesExcluded": [item for item in selected if item not in X.columns],
            "warning": "Raw logistic baseline is not scorecard-ready until WOE bins are approved.",
        }
        selected = list(X.columns)
        warnings.append("Raw logistic baseline trained without WOE bins. Not scorecard-ready.")
        model_label = "Raw Logistic Baseline"
    else:
        raise HTTPException(status_code=400, detail="Run WOE / IV analysis first or enable raw logistic baseline.")

    split_column = next((column for column in df.columns if str(column).lower() == "atlas_split"), None)
    split_source = "random"
    if split_column is not None:
        split_values = df[split_column].astype(str).str.strip().str.lower()
        train_mask = split_values.isin({"train", "training", "development", "dev"})
        val_mask = split_values.isin({"test", "validation", "val"})
        if train_mask.any() and val_mask.any():
            X_train, X_val, y_train, y_val = X.loc[train_mask], X.loc[val_mask], y.loc[train_mask], y.loc[val_mask]
            split_source = "atlas_split"
        else:
            split_column = None
    if split_column is None:
        split = max(0.5, min(float(payload.get("trainValidationSplit") or 0.7), 0.9))
        try:
            X_train, X_val, y_train, y_val = train_test_split(X, y, train_size=split, random_state=42, stratify=y)
        except Exception:
            X_train, X_val, y_train, y_val = train_test_split(X, y, train_size=split, random_state=42)
    penalty = "l2" if str(payload.get("modelType") or "").lower().startswith("regularized") or payload.get("regularization") else None
    kwargs = {
        "max_iter": 1000,
        "solver": "liblinear",
        "class_weight": "balanced" if payload.get("classWeight") == "balanced" else None,
        "C": max(float(payload.get("regularizationC") or 1.0), 0.0001),
    }
    if penalty:
        kwargs["penalty"] = "l2"
    model = LogisticRegression(**kwargs)
    model.fit(X_train, y_train)
    val_pd = model.predict_proba(X_val)[:, 1]
    all_pd = model.predict_proba(X)[:, 1]
    coefficients = [{"variable": col, "coefficient": round(float(coef), 8)} for col, coef in zip(X.columns, model.coef_[0])]
    pdo = float(payload.get("pdo") or 20)
    base_score = float(payload.get("baseScore") or 600)
    base_odds = parse_base_odds(payload.get("baseOdds") or "50:1")
    factor = pdo / math.log(2)
    offset = base_score - factor * math.log(max(base_odds, 1e-12))
    log_odds = model.intercept_[0] + (X.to_numpy() @ model.coef_[0])
    score = offset + factor * log_odds
    min_score = payload.get("minScore")
    max_score = payload.get("maxScore")
    if min_score is not None:
        score = np.maximum(score, float(min_score))
    if max_score is not None:
        score = np.minimum(score, float(max_score))
    auc = safe_auc(y_val, val_pd, roc_auc_score)
    ks_table = build_ks_table(score, y, all_pd)
    lift_table = build_lift_table(score, y, all_pd)
    metrics = {
        "auc": auc,
        "ks": max((row["ks"] for row in ks_table), default=0),
        "gini": round((2 * auc - 1), 6) if auc is not None else None,
        "logLoss": safe_log_loss(y_val, val_pd, log_loss),
        "eventRate": round(float(y.mean()), 6),
        "validationRows": int(len(X_val)),
        "trainRows": int(len(X_train)),
    }
    scorecard_points = build_scorecard_points(woe_analysis, selected, coefficients, factor, model.intercept_[0])
    score_distribution = build_score_distribution(score, y, all_pd)
    cutoff_table = build_cutoff_table(score, y, payload)
    selected_cutoff = cutoff_table[0]["scoreCutoff"] if cutoff_table else None
    model_id = scorecard_model_id(payload, resolved_version, selected)
    result = {
        "modelId": model_id,
        "projectId": payload.get("projectId"),
        "datasetId": dataset.get("datasetId"),
        "datasetName": dataset.get("name"),
        "datasetVersionId": resolved_version,
        "targetColumn": target,
        "eventValue": event_value,
        "modelType": model_label,
        "woeAnalysisId": woe_analysis.get("analysisId") if woe_analysis else None,
        "selectedVariables": selected,
        "splitSource": split_source,
        "transformSummary": transform_summary,
        "coefficients": coefficients,
        "intercept": round(float(model.intercept_[0]), 8),
        "pdoSettings": {
            "pdo": pdo,
            "baseScore": base_score,
            "baseOdds": payload.get("baseOdds") or "50:1",
            "scoreDirection": payload.get("scoreDirection") or "Higher score = lower risk",
            "factor": round(factor, 6),
            "offset": round(offset, 6),
            "minScore": min_score,
            "maxScore": max_score,
        },
        "metrics": metrics,
        "scorecardPoints": scorecard_points,
        "scoreDistribution": score_distribution,
        "liftTable": lift_table,
        "ksTable": ks_table,
        "cutoffTable": cutoff_table,
        "selectedCutoff": selected_cutoff,
        "generatedCode": generate_scorecard_code({**payload, "selectedVariables": selected}),
        "warnings": warnings,
    }
    return save_scorecard_model(result)


def transform_with_woe(df: pd.DataFrame, selected: List[str], analysis: Dict[str, Any]) -> tuple[pd.DataFrame, Dict[str, Any], List[str]]:
    summaries = {row.get("variable"): row for row in analysis.get("variableSummaries") or []}
    output: Dict[str, pd.Series] = {}
    missing_assignments = 0
    unseen = 0
    excluded = []
    for variable in selected:
        summary = summaries.get(variable)
        if not summary or not summary.get("bins"):
            excluded.append(variable)
            continue
        values = []
        for raw in df[variable]:
            woe, status = lookup_woe(raw, summary.get("bins") or [])
            if status == "missing":
                missing_assignments += 1
            if status == "unseen":
                unseen += 1
            values.append(woe)
        output[f"woe_{variable}"] = pd.Series(values, index=df.index).fillna(0)
    if not output:
        raise HTTPException(status_code=400, detail="Selected variables did not have usable WOE bins.")
    return pd.DataFrame(output), {
        "mode": "woe",
        "rows": int(len(df)),
        "variables": list(output.keys()),
        "missingWoeAssignments": int(missing_assignments),
        "unseenCategories": int(unseen),
        "variablesExcluded": excluded,
    }, [name.replace("woe_", "", 1) for name in output.keys()]


def lookup_woe(raw: Any, bins: List[Dict[str, Any]]) -> tuple[float, str]:
    if pd.isna(raw):
        missing = next((item for item in bins if item.get("isMissingBin")), None)
        return float(missing.get("woe") or 0) if missing else 0.0, "missing"
    numeric = pd.to_numeric(pd.Series([raw]), errors="coerce").iloc[0]
    for bin_row in bins:
        if bin_row.get("isMissingBin"):
            continue
        if bin_row.get("categoryValues") and str(raw) in [str(item) for item in bin_row.get("categoryValues") or []]:
            return float(bin_row.get("woe") or 0), "matched"
        lower = bin_row.get("lowerBound")
        upper = bin_row.get("upperBound")
        if pd.notna(numeric) and lower is not None and upper is not None and float(lower) <= float(numeric) <= float(upper):
            return float(bin_row.get("woe") or 0), "matched"
    return 0.0, "unseen"


def raw_design_matrix(df: pd.DataFrame, selected: List[str]) -> pd.DataFrame:
    raw = df[[col for col in selected if col in df.columns]].copy()
    for col in raw.columns:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    return raw.fillna(raw.median(numeric_only=True)).fillna(0)


def build_scorecard_points(analysis: Optional[Dict[str, Any]], selected: List[str], coefficients: List[Dict[str, Any]], factor: float, intercept: float) -> List[Dict[str, Any]]:
    coef_map = {item["variable"].replace("woe_", "", 1): float(item["coefficient"]) for item in coefficients}
    rows = [{"variable": "Base", "bin": "Intercept", "woe": 0, "coefficient": round(intercept, 8), "rawContribution": round(intercept, 8), "points": round(factor * intercept, 2), "reasonCodeLabel": "Base score contribution"}]
    summaries = {row.get("variable"): row for row in (analysis or {}).get("variableSummaries") or []}
    for variable in selected:
        clean = variable.replace("woe_", "", 1)
        coef = coef_map.get(clean, coef_map.get(variable, 0.0))
        bins = summaries.get(clean, {}).get("bins") or [{"label": "Raw variable", "woe": 0}]
        for bin_row in bins:
            woe = float(bin_row.get("woe") or 0)
            contribution = coef * woe
            rows.append({
                "variable": clean,
                "bin": bin_row.get("label"),
                "woe": round(woe, 6),
                "coefficient": round(coef, 8),
                "rawContribution": round(contribution, 8),
                "points": round(factor * contribution, 2),
                "reasonCodeLabel": f"{clean}: {bin_row.get('label')}",
            })
    return rows


def build_lift_table(score: Any, y: pd.Series, pd_values: Any) -> List[Dict[str, Any]]:
    df = pd.DataFrame({"score": score, "event": y.to_numpy(), "pd": pd_values})
    df["decile"] = pd.qcut(df["score"].rank(method="first", ascending=False), q=10, labels=False, duplicates="drop") + 1
    total_accounts = len(df)
    total_events = max(int(df["event"].sum()), 1)
    total_non_events = max(total_accounts - total_events, 1)
    rows = []
    cum_accounts = cum_events = cum_non_events = 0
    for decile, group in df.groupby("decile"):
        accounts = int(len(group))
        events = int(group["event"].sum())
        non_events = accounts - events
        cum_accounts += accounts
        cum_events += events
        cum_non_events += non_events
        event_rate = events / max(accounts, 1)
        rows.append({
            "decile": int(decile),
            "accounts": accounts,
            "accountPct": round(accounts / max(total_accounts, 1), 6),
            "minScore": round(float(group["score"].min()), 2),
            "maxScore": round(float(group["score"].max()), 2),
            "avgScore": round(float(group["score"].mean()), 2),
            "expectedEvents": round(float(group["pd"].sum()), 2),
            "actualEvents": events,
            "actualEventRate": round(event_rate, 6),
            "cumulativeAccountPct": round(cum_accounts / max(total_accounts, 1), 6),
            "cumulativeEventPct": round(cum_events / total_events, 6),
            "cumulativeNonEventPct": round(cum_non_events / total_non_events, 6),
            "lift": round(event_rate / max(float(df["event"].mean()), 1e-12), 4),
        })
    return rows


def build_ks_table(score: Any, y: pd.Series, pd_values: Any) -> List[Dict[str, Any]]:
    rows = build_lift_table(score, y, pd_values)
    return [{**row, "ks": round(abs(row["cumulativeEventPct"] - row["cumulativeNonEventPct"]), 6)} for row in rows]


def build_score_distribution(score: Any, y: pd.Series, pd_values: Any) -> List[Dict[str, Any]]:
    df = pd.DataFrame({"score": score, "event": y.to_numpy(), "pd": pd_values})
    df["scoreBand"] = pd.cut(df["score"], bins=10, duplicates="drop").astype(str)
    rows = []
    for band, group in df.groupby("scoreBand", observed=False):
        rows.append({"scoreBand": str(band), "accounts": int(len(group)), "eventRate": round(float(group["event"].mean()), 6), "avgPd": round(float(group["pd"].mean()), 6)})
    return rows


def build_cutoff_table(score: Any, y: pd.Series, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    avg_balance = float(payload.get("averageBalance") or 0)
    lgd = float(payload.get("lossGivenDefault") or 0)
    revenue = float(payload.get("revenuePerBookedAccount") or 0)
    max_bad = payload.get("maximumBadRate")
    rows = []
    for cutoff in sorted(set(pd.Series(score).quantile([0.1, 0.25, 0.5, 0.75, 0.9]).round(0).astype(int))):
        approved = pd.Series(score) >= cutoff
        approval_rate = float(approved.mean())
        bad_rate = float(y[approved].mean()) if approved.any() else 0.0
        approved_count = int(approved.sum())
        declined_count = int((~approved).sum())
        expected_loss = approved_count * bad_rate * avg_balance * lgd if avg_balance and lgd else None
        expected_profit = approved_count * revenue - (expected_loss or 0) if revenue else None
        recommendation = "Candidate"
        if max_bad is not None and bad_rate > float(max_bad):
            recommendation = "Bad-rate limit exceeded"
        rows.append({
            "scoreCutoff": int(cutoff),
            "approvalRate": round(approval_rate, 6),
            "badRate": round(bad_rate, 6),
            "expectedLoss": round(expected_loss, 2) if expected_loss is not None else None,
            "expectedProfit": round(expected_profit, 2) if expected_profit is not None else None,
            "populationApproved": approved_count,
            "populationDeclined": declined_count,
            "recommendation": recommendation,
        })
    return rows


def create_scorecard_evidence(model_id: str, technique: str = "scorecard_modeling", label: str = "Scorecard Model Evidence") -> Dict[str, Any]:
    model = get_scorecard_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Scorecard model not found.")
    metrics = model.get("metrics") or {}
    top_vars = model.get("selectedVariables", [])[:10]
    item = {
        "projectId": model.get("projectId"),
        "source": "Credit Risk Studio",
        "evidenceType": "credit_risk",
        "title": label,
        "summary": f"Credit risk scorecard evidence for {model.get('modelType')} with AUC {metrics.get('auc')} and KS {metrics.get('ks')}.",
        "financialDomain": "credit_risk",
        "financialTechnique": technique,
        "supportsSections": [
            "Model Training Strategy",
            "Model Performance",
            "Model Interpretation",
            "Scoring and External Validation",
            "Implementation Plan",
            "Monitoring Plan",
            "Fair Lending and Governance Considerations",
            "Appendices",
        ],
        "metadata": {
            "modelId": model.get("modelId"),
            "targetEvent": model.get("targetColumn"),
            "pdo": model.get("pdoSettings", {}).get("pdo"),
            "baseScore": model.get("pdoSettings", {}).get("baseScore"),
            "baseOdds": model.get("pdoSettings", {}).get("baseOdds"),
            "auc": metrics.get("auc"),
            "ks": metrics.get("ks"),
            "gini": metrics.get("gini"),
            "topVariables": top_vars,
            "selectedCutoff": model.get("selectedCutoff"),
        },
        "payload": {"metrics": metrics, "topVariables": top_vars, "selectedCutoff": model.get("selectedCutoff")},
        "status": "ready",
        "importance": "high",
    }
    evidence = upsert_evidence(item)
    model["evidenceIds"] = sorted(set((model.get("evidenceIds") or []) + [evidence.get("evidenceId")]))
    save_scorecard_model(model)
    return evidence


def export_scorecard_excel(model_id: str) -> bytes:
    model = get_scorecard_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Scorecard model not found.")
    try:
        from openpyxl import Workbook
    except Exception:
        return json.dumps(model, indent=2, default=str).encode("utf-8")
    wb = Workbook()
    sheet_map = {
        "Model Summary": list(model.items()),
        "Performance Metrics": list((model.get("metrics") or {}).items()),
        "Detailed Lift Table": model.get("liftTable") or [],
        "KS Table": model.get("ksTable") or [],
        "Score Distribution": model.get("scoreDistribution") or [],
        "Scorecard Points": model.get("scorecardPoints") or [],
        "WOE Variables": [{"variable": item} for item in model.get("selectedVariables") or []],
        "Cutoff Strategy": model.get("cutoffTable") or [],
        "Evidence Mapping": [{"evidenceId": item} for item in model.get("evidenceIds") or []],
        "Generated Code": [{"language": key, "code": value} for key, value in (model.get("generatedCode") or {}).items()],
    }
    ws = wb.active
    ws.title = "Model Summary"
    write_sheet(ws, sheet_map["Model Summary"])
    for name, rows in list(sheet_map.items())[1:]:
        write_sheet(wb.create_sheet(name), rows)
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def write_sheet(ws: Any, rows: Any) -> None:
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        headers = list(rows[0].keys())
        ws.append(headers)
        for row in rows:
            ws.append([row.get(header) for header in headers])
    elif isinstance(rows, list):
        for key, value in rows:
            if key not in {"generatedCode", "scorecardPoints", "liftTable", "ksTable", "scoreDistribution", "cutoffTable"}:
                ws.append([key, json.dumps(value, default=str) if isinstance(value, (dict, list)) else value])
    else:
        ws.append(["Value", json.dumps(rows, default=str)])


def register_scorecard_model(model_id: str, champion: bool = True) -> Dict[str, Any]:
    model = get_scorecard_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Scorecard model not found.")
    model["champion"] = bool(champion)
    return save_scorecard_model(model)


def generate_scorecard_code(settings: Dict[str, Any]) -> Dict[str, str]:
    target = settings.get("targetColumn") or "bad_event"
    event = settings.get("eventValue", 1)
    variables = settings.get("selectedVariables") or ["woe_var1", "woe_var2", "woe_var3"]
    pdo = settings.get("pdo") or 20
    base_score = settings.get("baseScore") or 600
    base_odds = settings.get("baseOdds") or "50:1"
    return {
        "python": f"""import numpy as np\nfrom sklearn.linear_model import LogisticRegression\nfrom sklearn.metrics import roc_auc_score\n\nX = woe_train[{variables!r}]\ny = (woe_train[{target!r}].astype(str) == {str(event)!r}).astype(int)\nmodel = LogisticRegression(max_iter=1000, solver='liblinear')\nmodel.fit(X, y)\npd = model.predict_proba(X)[:, 1]\nauc = roc_auc_score(y, pd)\nfactor = {pdo} / np.log(2)\nbase_odds = {parse_base_odds(base_odds)!r}\noffset = {base_score} - factor * np.log(base_odds)\nscore = offset + factor * (model.intercept_[0] + X.to_numpy() @ model.coef_[0])\nprint('AUC', auc)\n""",
        "sql": f"""-- ATLAS scorecard scoring skeleton\nselect *,\n       1.0 / (1.0 + exp(-(intercept + beta1 * woe_var1))) as predicted_pd,\n       offset + factor * (intercept + beta1 * woe_var1) as score\nfrom woe_scored_input;\n""",
        "r": f"""model <- glm(I(as.character({target}) == '{event}') ~ { ' + '.join(variables) }, data=woe_train, family=binomial())\nwoe_train$predicted_pd <- predict(model, type='response')\nfactor <- {pdo} / log(2)\nbase_odds <- {parse_base_odds(base_odds)}\noffset <- {base_score} - factor * log(base_odds)\nwoe_train$score <- offset + factor * predict(model, type='link')\n""",
        "sas": f"""proc logistic data=work.woe_train descending;\n  model {target} = {' '.join(variables)};\n  output out=work.scored p=predicted_pd xbeta=log_odds;\nrun;\n\ndata work.scored;\n  set work.scored;\n  factor = {pdo} / log(2);\n  base_odds = {parse_base_odds(base_odds)};\n  offset = {base_score} - factor * log(base_odds);\n  score = offset + factor * log_odds;\nrun;\n""",
    }


def scorecard_model_id(payload: Dict[str, Any], version_id: str, variables: List[str]) -> str:
    basis = json.dumps({"projectId": payload.get("projectId"), "datasetId": payload.get("datasetId"), "version": version_id, "target": payload.get("targetColumn"), "variables": variables, "modelType": payload.get("modelType")}, sort_keys=True, default=str)
    return "scorecard-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:14]


def parse_base_odds(value: Any) -> float:
    match = re.search(r"([0-9.]+)", str(value))
    return float(match.group(1)) if match else float(value or 1)


def is_excluded_field(name: str) -> bool:
    return bool(re.search(r"(^id$|_id$|target|score|prediction|predicted|probability|pd$|race|gender|sex|ethnic)", name, re.I))


def safe_auc(y: Any, pred: Any, fn: Any) -> Optional[float]:
    try:
        return round(float(fn(y, pred)), 6)
    except Exception:
        return None


def safe_log_loss(y: Any, pred: Any, fn: Any) -> Optional[float]:
    try:
        return round(float(fn(y, pred)), 6)
    except Exception:
        return None
