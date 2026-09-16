"""Sensitivity follow-up to the already declared fixed probability bands.

Selected after the full band scan, not independent confirmation. No fitting or
new prediction. Uses the same physically gated Development readers as primary.
"""
from __future__ import annotations
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import diagnose_mlb_v18_pa_v1 as d


def main():
    df,p,q,y,obs,ll,llq,b,bq,protocol,accounting = d.load_data()
    bands = [("DOUBLE",.05,.10), ("SINGLE",.20,.30), ("HOME_RUN",.05,.10), ("BIP_OUT",.30,.40), ("BIP_OUT",.60,.80)]
    rows, sensitivity, bootstrap = [], [], {}
    windows = {"all":np.ones(len(df),bool), "early_folds1_3":(df.foldNumber<=3).to_numpy(), **{f"fold{k}":(df.foldNumber==k).to_numpy() for k in range(1,6)}}
    def record(mask, j):
        f = df.loc[mask, ["canonicalGameId","game_date","week","batterCanonicalPlayerId","pitcherCanonicalPlayerId","homeTeamId","awayTeamId"]]
        bc=p[mask,j]-obs[mask,j]
        qc=q[mask,j]-obs[mask,j]
        vals=np.column_stack([ll[mask]-llq[mask],bc,qc,bc**2-qc**2])
        stats=d.clustered(vals,f.canonicalGameId)
        return {"pa_count":len(f),"games":f.canonicalGameId.nunique(),"dates":f.game_date.nunique(),"weeks":f.week.nunique(),"batters":f.batterCanonicalPlayerId.nunique(),"pitchers":f.pitcherCanonicalPlayerId.nunique(),"players":pd.concat([f.batterCanonicalPlayerId,f.pitcherCanonicalPlayerId]).nunique(),"teams":pd.concat([f.homeTeamId,f.awayTeamId]).dropna().nunique(),"team_identity_missing_pa":int(f.homeTeamId.isna().sum()),"first_date":f.game_date.min(),"last_date":f.game_date.max(),"observed_events":int(obs[mask,j].sum()),"v18_predicted":p[mask,j].mean(),"v14_predicted":q[mask,j].mean(),"observed":obs[mask,j].mean(),"v18_bias":bc.mean(),"v14_bias":qc.mean(),"v18_bias_ci_lower":stats[1,1],"v18_bias_ci_upper":stats[1,2],"v18_binary_class_brier":np.mean(bc**2),"v14_binary_class_brier":np.mean(qc**2),"class_brier_difference":np.mean(bc**2-qc**2),"class_brier_difference_ci_lower":stats[3,1],"class_brier_difference_ci_upper":stats[3,2],"v18_pa_log_loss":ll[mask].mean(),"v14_pa_log_loss":llq[mask].mean(),"delta_pa_log_loss":vals[:,0].mean(),"delta_pa_log_loss_ci_lower":stats[0,1],"delta_pa_log_loss_ci_upper":stats[0,2]}
    for c,lo,hi in bands:
        j=d.CLASSES.index(c)
        label=f"{c} [{lo},{hi})"
        mask=(p[:,j]>=lo)&(p[:,j]<hi)
        for win,w in windows.items():
            m=mask&w
            if m.any():
                rows.append({"band":label,"window":win,**record(m,j),"timing_status":d.TIMING_STATUS,"selection_status":"FOLLOW_UP_TO_PREDECLARED_BAND_SCAN_NOT_INDEPENDENT_CONFIRMATION"})
        bootstrap[label]={"columns":["delta_pa_log_loss","v18_class_bias","v14_class_bias"],"game":d.bootstrap_ratio(np.column_stack([ll[mask]-llq[mask],p[mask,j]-obs[mask,j],q[mask,j]-obs[mask,j]]),df.loc[mask,["canonicalGameId","game_date","season"]],"game"),"four_week":d.bootstrap_ratio(np.column_stack([ll[mask]-llq[mask],p[mask,j]-obs[mask,j],q[mask,j]-obs[mask,j]]),df.loc[mask,["canonicalGameId","game_date","season"]],"four_week")}
        variants=[("none",None,mask)]
        for col in ["batterCanonicalPlayerId","pitcherCanonicalPlayerId","game_date"]:
            dominant=df.loc[mask,col].value_counts().index[0]
            variants.append(("drop_dominant_"+col,str(dominant),mask&(df[col]!=dominant).to_numpy()))
        teams=pd.concat([df.loc[mask,"homeTeamId"],df.loc[mask,"awayTeamId"]]).dropna().value_counts()
        dominant=teams.index[0]
        variants.append(("known_teams_drop_dominant_team",str(dominant),mask&df.homeTeamId.notna().to_numpy()&(df.homeTeamId!=dominant).to_numpy()&(df.awayTeamId!=dominant).to_numpy()))
        variants.append(("existing_conservative_timing_keys_ESTIMATOR_STILL_UNCERTAIN",None,mask&df.candidateConservativeRowEligibility.eq(True).to_numpy()))
        for name,value,m in variants:
            if m.any():
                sensitivity.append({"band":label,"sensitivity":name,"removed_identity":value,**record(m,j)})
    pd.DataFrame(rows).to_csv(d.OUT/"calibration-leads.csv",index=False)
    pd.DataFrame(sensitivity).to_csv(d.OUT/"calibration-lead-sensitivities.csv",index=False)
    d.dump("calibration-lead-bootstrap.json",bootstrap)
    d.dump("calibration-lead-input-manifest.json",{"references":d.REFS,"physicalReads":d.READS,"protocol":protocol,"selection":"Five already-declared bands chosen for sensitivity after primary band scan; not independent confirmation","fitting":False,"inference":False,"ootPayloadReads":0})
    print(pd.DataFrame(rows).query("window == 'all'")[["band","pa_count","games","v18_predicted","v14_predicted","observed","v18_bias","v14_bias"]].to_string(index=False),flush=True)


if __name__ == "__main__":
    main()
