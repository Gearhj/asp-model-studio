from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd
from scipy import stats

from ..errors import InsufficientDataError
from ..result_builder import chart, result, table


def compute_experiment_diagnostics(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    treatment, outcome = parameters.get("treatment_column"), parameters.get("outcome_column")
    work=pd.DataFrame({"treatment":frame[treatment].astype(str),"outcome":pd.to_numeric(frame[outcome],errors="coerce")}).dropna()
    groups=[(name,group.outcome.to_numpy()) for name,group in work.groupby("treatment")]
    if len(groups)<2 or min(len(values) for _,values in groups)<2: raise InsufficientDataError("Experiment diagnostics require at least two treatment groups with two valid observations each.")
    group_rows=[{"group":name,"count":int(len(values)),"mean":float(np.mean(values)),"standard_deviation":float(np.std(values,ddof=1))} for name,values in groups]
    control_name=parameters.get("control_value") or groups[0][0]; control=next(values for name,values in groups if name==control_name); effects=[]
    for name,values in groups:
        if name==control_name: continue
        difference=float(np.mean(values)-np.mean(control)); test=stats.ttest_ind(values,control,equal_var=False); pooled=np.sqrt((np.var(values,ddof=1)+np.var(control,ddof=1))/2); effects.append({"treatment":name,"control":control_name,"absolute_effect":difference,"standardized_effect":difference/max(pooled,1e-12),"p_value":float(test.pvalue),"confidence_interval_low":difference-1.96*np.sqrt(np.var(values,ddof=1)/len(values)+np.var(control,ddof=1)/len(control)),"confidence_interval_high":difference+1.96*np.sqrt(np.var(values,ddof=1)/len(values)+np.var(control,ddof=1)/len(control))})
    anova=stats.f_oneway(*[values for _,values in groups]) if len(groups)>2 else None
    stats_summary={"observation_count":int(len(work)),"group_count":len(groups),"anova_f":float(anova.statistic) if anova else None,"anova_p_value":float(anova.pvalue) if anova else None}
    return result("experiment_diagnostics",context,parameters,statistics=stats_summary,tables=[table("group_summary","Treatment group summary",group_rows),table("effect_estimates","Treatment effect estimates",effects)],charts=[chart("group_means","bar","Outcome by treatment",group_rows,x_field="group",x_label="Treatment",y_fields=[{"field":"mean","label":"Mean outcome"}])])


def compute_anova(frame: pd.DataFrame, context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    return compute_experiment_diagnostics(frame,context,parameters) | {"analysis_type":"anova"}


def compute_power_analysis(context: Dict[str, Any], parameters: Dict[str, Any]) -> Dict[str, Any]:
    effect=float(parameters.get("effect_size") or 0); alpha=float(parameters.get("alpha") or .05); power=float(parameters.get("power") or .8)
    if effect<=0: raise InsufficientDataError("Power analysis requires a positive anticipated standardized effect size.")
    z_alpha=stats.norm.ppf(1-alpha/2); z_power=stats.norm.ppf(power); required=int(np.ceil(2*((z_alpha+z_power)/effect)**2))
    return result("power_analysis",context,parameters,statistics={"effect_size":effect,"alpha":alpha,"target_power":power,"required_sample_per_group":required,"required_total_sample":required*2},tables=[table("power_summary","Power analysis",[{"effect_size":effect,"alpha":alpha,"power":power,"sample_per_group":required,"total_sample":required*2}])])
