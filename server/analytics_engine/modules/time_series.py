from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy import stats

from ..errors import InsufficientDataError, InvalidTimestampError
from ..result_builder import chart, result, table


def _acf(values: np.ndarray, lag: int) -> float | None:
    if len(values) <= lag + 2: return None
    return float(np.corrcoef(values[:-lag], values[lag:])[0, 1]) if np.std(values[:-lag]) and np.std(values[lag:]) else None


def _pacf(values: np.ndarray, lag: int) -> float | None:
    if lag < 1 or len(values) <= lag + 5:
        return None
    y = values[lag:]
    design = np.column_stack([values[lag - offset:-offset] for offset in range(1, lag + 1)])
    try:
        coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
        return float(coefficients[-1])
    except np.linalg.LinAlgError:
        return None


def compute_time_series_profile(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    timestamp_column, target_column = parameters.get("timestamp_column") or parameters.get("date_column"), parameters.get("target_column")
    entity_columns = [str(c) for c in parameters.get("entity_columns") or parameters.get("entity_grain") or []]
    if not timestamp_column or timestamp_column not in frame.columns: raise InvalidTimestampError("Time-series profile requires a mapped timestamp column.")
    if not target_column or target_column not in frame.columns: raise InsufficientDataError("Time-series profile requires a mapped target value column.")
    work = frame[[timestamp_column,target_column,*[c for c in entity_columns if c in frame.columns]]].copy(); work["__time"] = pd.to_datetime(work[timestamp_column],errors="coerce"); work["__value"] = pd.to_numeric(work[target_column],errors="coerce"); work = work.dropna(subset=["__time","__value"]).sort_values("__time")
    if len(work) < 5: raise InsufficientDataError("Time-series profile requires at least five valid timestamp and target observations.")
    aggregation = str(parameters.get("aggregation") or "sum").lower(); aggregate = work.groupby("__time",as_index=False)["__value"].agg("mean" if aggregation == "mean" else "sum").sort_values("__time")
    inferred = pd.infer_freq(aggregate["__time"]) if len(aggregate) >= 3 else None; diffs = aggregate["__time"].diff().dropna(); median_delta = diffs.median() if not diffs.empty else None
    values = aggregate["__value"]
    window = max(3,min(int(parameters.get("rolling_window") or 7),max(3,len(aggregate)//2))); aggregate["rolling_mean"] = values.rolling(window, min_periods=2).mean(); aggregate["rolling_std"] = values.rolling(window,min_periods=2).std(); aggregate["z"]=(values-values.rolling(window,min_periods=2).mean())/values.rolling(window,min_periods=2).std(); aggregate["anomaly"] = aggregate["z"].abs() > float(parameters.get("anomaly_threshold") or 3.0)
    slope = float(np.polyfit(np.arange(len(aggregate)),values,1)[0]) if len(aggregate)>1 else 0.0; acf_rows=[{"lag":lag,"acf":_acf(values.to_numpy(),lag),"pacf":_pacf(values.to_numpy(),lag)} for lag in [1,7,14,30] if _acf(values.to_numpy(),lag) is not None]
    entity_summary=[]
    if entity_columns:
        grouped=work.groupby(entity_columns,dropna=False)
        for keys, group in grouped:
            key_values=keys if isinstance(keys,tuple) else (keys,); entity_summary.append({"entity":" | ".join(map(str,key_values)),"observation_count":int(len(group)),"start":group["__time"].min(),"end":group["__time"].max(),"volatility":float(group["__value"].std(ddof=1)) if len(group)>1 else 0.0})
    expected_periods=None; missing_periods=None
    if median_delta is not None and median_delta > pd.Timedelta(0): expected_periods=int((aggregate.__time.max()-aggregate.__time.min())/median_delta)+1; missing_periods=max(0,expected_periods-len(aggregate))
    warnings=[]
    if len(aggregate)<14: warnings.append("History is short; weekly and monthly seasonality diagnostics are not reliable.")
    if len(aggregate)<60: warnings.append("Fewer than two monthly cycles are available; monthly seasonality should be treated as exploratory.")
    warnings.append("ADF and KPSS stationarity tests are not available in this runtime. Inspect trend, autocorrelation, and differencing guidance before model selection.")
    diagnostics={"observation_count":int(len(aggregate)),"date_range_start":aggregate["__time"].min(),"date_range_end":aggregate["__time"].max(),"mean_target":float(values.mean()),"median_target":float(values.median()),"standard_deviation":float(values.std(ddof=1)),"coefficient_of_variation":float(values.std(ddof=1)/max(abs(values.mean()),1e-12)),"trend_direction":"increasing" if slope>0 else "decreasing" if slope<0 else "flat","trend_slope":slope,"frequency":inferred or (str(median_delta) if median_delta is not None else "unknown"),"missing_period_count":missing_periods,"duplicate_timestamp_count":int(work.duplicated(subset=["__time",*entity_columns]).sum()),"entity_count":int(len(entity_summary)) if entity_columns else 1,"anomaly_count":int(aggregate["anomaly"].sum())}
    top_anomalies=aggregate.loc[aggregate["anomaly"],["__time","__value","z"]].rename(columns={"__time":"timestamp","__value":"value","z":"z_score"}).sort_values("z_score",key=lambda series:series.abs(),ascending=False).head(25).to_dict("records")
    raw_rows=aggregate.rename(columns={"__time":"timestamp","__value":"actual"})[["timestamp","actual","rolling_mean","rolling_std","anomaly"]].to_dict("records")
    charts=[chart("series","line","Actual values and rolling mean",raw_rows,x_field="timestamp",x_label="Period",y_fields=[{"field":"actual","label":"Actual target"},{"field":"rolling_mean","label":"Rolling mean"}],annotations=[{"field":"anomaly","label":"Anomaly candidate"}]),chart("acf","acf","Autocorrelation",acf_rows,x_field="lag",x_label="Lag",y_fields=[{"field":"acf","label":"Autocorrelation"}]),chart("pacf","pacf","Partial autocorrelation",[row for row in acf_rows if row["pacf"] is not None],x_field="lag",x_label="Lag",y_fields=[{"field":"pacf","label":"Partial autocorrelation"}])]
    return result("time_series_profile",context,parameters,statistics=diagnostics,tables=[table("diagnostic_summary","Time-series diagnostic summary",[diagnostics]),table("autocorrelation","Autocorrelation diagnostics",acf_rows),table("anomalies","Top anomalous periods",top_anomalies),table("entity_summary","Entity series summary",entity_summary)],charts=charts,warnings=warnings)
