from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from ..errors import InsufficientDataError
from ..result_builder import result, table


def compute_segment_diagnostics(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    segment, outcome = parameters.get("segment_column"), parameters.get("outcome_column")
    if not segment or not outcome or segment not in frame or outcome not in frame: raise InsufficientDataError("Segment diagnostics require explicitly mapped segment and outcome columns.")
    work=pd.DataFrame({"segment":frame[segment].astype(str),"outcome":pd.to_numeric(frame[outcome],errors="coerce")}).dropna(); rows=work.groupby("segment",observed=True).outcome.agg(["count","mean"]).reset_index().rename(columns={"mean":"outcome_rate"}).to_dict("records")
    return result("segment_diagnostics",context,parameters,statistics={"segment_count":len(rows)},tables=[table("segment_performance","Segment performance",rows)])


def compute_fairness_diagnostics(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    if not parameters.get("protected_group_column"): return result("fairness_diagnostics",context,parameters,status="not_applicable",warnings=["Fairness diagnostics are not applicable until an authorized protected-group column is explicitly configured."])
    return compute_segment_diagnostics(frame,context,{"segment_column":parameters["protected_group_column"],"outcome_column":parameters.get("outcome_column")}) | {"analysis_type":"fairness_diagnostics"}
