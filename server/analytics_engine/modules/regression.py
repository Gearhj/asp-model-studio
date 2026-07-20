from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy import stats
from sklearn.metrics import explained_variance_score, mean_absolute_error, mean_squared_error, median_absolute_error, r2_score

from ..errors import InsufficientDataError
from ..result_builder import chart, result, table


def _vif(frame: pd.DataFrame, columns: list[str]) -> list[Dict[str, Any]]:
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce").dropna()
    rows = []
    if numeric.shape[0] < 5 or numeric.shape[1] < 2: return rows
    for column in numeric.columns:
        y = numeric[column].to_numpy(); X = numeric.drop(columns=[column]).to_numpy(); X = np.c_[np.ones(len(X)), X]
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None); fitted = X @ beta; r_squared = r2_score(y, fitted); rows.append({"feature":str(column), "vif":float(1 / max(1-r_squared, 1e-12)), "r_squared":float(r_squared)})
        except np.linalg.LinAlgError: rows.append({"feature":str(column), "vif":None, "r_squared":None})
    return rows


def compute_regression_diagnostics(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    actual, predicted = parameters.get("target_column"), parameters.get("prediction_column")
    work = pd.DataFrame({"actual":pd.to_numeric(frame[actual],errors="coerce"), "predicted":pd.to_numeric(frame[predicted],errors="coerce")}).dropna()
    if len(work) < 5: raise InsufficientDataError("Regression diagnostics require at least five non-missing actual and predicted values.")
    residual = work.actual - work.predicted; mse = mean_squared_error(work.actual, work.predicted); nonzero = work.actual != 0
    metrics = {"observation_count":int(len(work)), "mae":mean_absolute_error(work.actual,work.predicted), "mse":mse, "rmse":float(np.sqrt(mse)), "r_squared":r2_score(work.actual,work.predicted), "mape":float(np.mean(np.abs(residual[nonzero] / work.actual[nonzero])) * 100) if nonzero.any() else None, "smape":float(np.mean(2*np.abs(residual)/(np.abs(work.actual)+np.abs(work.predicted)).replace(0,np.nan))*100), "median_absolute_error":median_absolute_error(work.actual,work.predicted), "mean_residual":float(residual.mean()), "residual_standard_deviation":float(residual.std(ddof=1)), "explained_variance":explained_variance_score(work.actual,work.predicted), "maximum_absolute_error":float(residual.abs().max())}
    quantiles = pd.qcut(work.predicted.rank(method="first"), min(10,len(work)), labels=False, duplicates="drop")
    bands = pd.DataFrame({"prediction_band":quantiles,"absolute_error":residual.abs(),"residual":residual}).groupby("prediction_band",observed=True).agg(count=("absolute_error","size"),mean_absolute_error=("absolute_error","mean"),mean_residual=("residual","mean")).reset_index().to_dict("records")
    qq = stats.probplot(residual, dist="norm"); qq_rows = [{"theoretical_quantile":float(a),"sample_quantile":float(b)} for a,b in zip(qq[0][0],qq[0][1])]
    feature_columns = [str(x) for x in parameters.get("feature_columns") or [] if str(x) in frame.columns]
    vif = _vif(frame,feature_columns)
    warnings = []
    if abs(metrics["mean_residual"]) > .1 * max(float(work.actual.std()),1e-9): warnings.append("Residual bias is material relative to target variation.")
    if vif and max(float(row["vif"] or 0) for row in vif) > 10: warnings.append("At least one feature has VIF above 10 and may be multicollinear.")
    charts = [chart("actual_vs_predicted","scatter","Actual versus predicted",work.assign(residual=residual).to_dict("records"),x_field="actual",x_label="Actual",y_fields=[{"field":"predicted","label":"Predicted"}]), chart("residuals_vs_fitted","scatter","Residuals versus fitted",work.assign(residual=residual).to_dict("records"),x_field="predicted",x_label="Predicted",y_fields=[{"field":"residual","label":"Residual"}],reference_lines=[{"y":0,"label":"Zero residual"}]), chart("qq_plot","qq_plot","Residual Q-Q plot",qq_rows,x_field="theoretical_quantile",x_label="Theoretical quantile",y_fields=[{"field":"sample_quantile","label":"Sample quantile"}])]
    return result("regression_diagnostics",context,parameters,statistics=metrics,tables=[table("residual_summary","Residual summary",[{"minimum":float(residual.min()),"q1":float(residual.quantile(.25)),"median":float(residual.median()),"q3":float(residual.quantile(.75)),"maximum":float(residual.max())}]),table("prediction_band_error","Error by prediction band",bands),table("vif","Variance inflation factors",vif)],charts=charts,warnings=warnings)
