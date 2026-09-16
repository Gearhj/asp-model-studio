"""One focused fold-5 follow-up; no fits, inference, calibration, or bootstrap.

Run: .venv/Scripts/python.exe scripts/followup_mlb_v18_doubles_v1.py
The source has one mixed-Development row group: column chunks are decoded but
only fold-5 predictions enter calculations. Earlier folds use saved summaries.
No original diagnostic file is written by this script.
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name]="1"
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import numpy as np
import pandas as pd
import pyarrow.compute as pc
import pyarrow.parquet as pq
from server.sports_current_statcast.mlb_regime_baseline import AuthorizedByteReader,footer_metadata
from server.sports_current_statcast.mlb_starter_duration_quarantine import final_oot_eligible_key_mask

PARENT=ROOT/"outputs/mlb-v18-empirical-diagnosis-v1"
OUT=ROOT/"outputs/mlb-v18-doubles-followup-v1"
CACHE=ROOT/"outputs/mlb-regime-hybrid-ensemble-v1/baseline-cache"
OOF=ROOT/".runtime/asp-model-studio/stage3-model-laboratory/objects/oof/sha256/b79a80398ef32a13589a8bb66f5e4e9c698b600195de5369886f7fc07f0dc215.parquet"
CLASSES=["STRIKEOUT","WALK_HBP_CI","HOME_RUN","SINGLE","DOUBLE","TRIPLE","BIP_OUT","OTHER_REACH"]
PCOLS=["probability_"+c for c in CLASSES]
READS=[]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_columns(path,columns,purpose,fold5=False):
    path=Path(path)
    meta,footer=footer_metadata(path)
    ranges=[(0,4),(footer,path.stat().st_size)]
    for g in range(meta.num_row_groups):
        group=meta.row_group(g)
        for k in range(group.num_columns):
            col=group.column(k)
            if col.path_in_schema in columns:
                offsets=[col.data_page_offset]
                if col.has_dictionary_page: offsets.append(col.dictionary_page_offset)
                start=min(offsets)
                ranges.append((start,start+col.total_compressed_size))
    with AuthorizedByteReader(path,ranges) as reader:
        table=pq.ParquetFile(reader,pre_buffer=False).read(columns=columns,use_threads=False)
        if fold5: table=table.filter(pc.equal(table["foldNumber"],5))
        result=table.to_pandas()
    READS.append({"path":str(path),"columns":columns,"purpose":purpose,"rowsReturned":len(result),"fold5SelectedBeforeCalculations":fold5,"physicalColumnAllowlist":True})
    return result


def native(value):
    if isinstance(value,dict): return {str(k):native(v) for k,v in value.items()}
    if isinstance(value,(list,tuple,np.ndarray)): return [native(v) for v in value]
    if isinstance(value,(np.integer,)): return int(value)
    if isinstance(value,(np.bool_,)): return bool(value)
    if isinstance(value,(np.floating,float)): return float(value) if np.isfinite(value) else None
    return value


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    protocol={"scope":"FOLD5_ONLY_FOCUSED_DOUBLES_FOLLOWUP","band":[.05,.10],"adjacentBands":[[.025,.05],[.10,.20]],
              "contexts":{"batter_slg":["<0.4","0.4–0.5",">=0.5","missing"],"pitcher_hr_per_bfp":["<0.025",">=0.025","missing"],"matchup_platoon_advantage":["0","1","missing"]},
              "contextInterpretation":"Raw saved pre-PA SLG, pitcher HR allowance proxy (not XBH allowance), and platoon indicator. No interaction search.",
              "otherLeads":{"SINGLE":[.20,.30],"HOME_RUN":[.05,.10]},"support":"Descriptive; flag cells below1000 PAs or100 games as sparse. No new hypothesis testing/bootstrap.",
              "earlierFolds":"Existing summaries only","rawTreatedInspection":"Only three selected context dimensions inside the doubles band, against declared saved transformations; no new features.",
              "noInterventionSelectedInAdvance":True}
    declaration=OUT/"scope.json"
    if declaration.exists():
        assert json.loads(declaration.read_text(encoding="utf-8"))==protocol
    else: declaration.write_text(json.dumps(protocol,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    parent_manifest_sha=sha(PARENT/"artifact-manifest.json")
    lineage=json.loads((PARENT/"lineage/pa-lineage.json").read_text(encoding="utf-8"))
    fold=lineage["folds"][4]
    assert fold["estimator"]["sha256"]=="44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b"
    # Reuse the existing verified identity ledger; select columns, not PA scores.
    games=pd.read_csv(PARENT/"pa/game-pa-ledger.csv",usecols=["canonicalGameId","game_date","foldNumber"])
    keys=read_columns(OOF,["canonicalPaId","canonicalGameId","foldNumber"],"IDENTITY_BEFORE_OUTCOMES")
    assert keys.canonicalPaId.is_unique
    assert all(final_oot_eligible_key_mask(keys.canonicalGameId))
    gated=keys.merge(games,on=["canonicalGameId","foldNumber"],how="left",validate="many_to_one")
    assert gated.game_date.notna().all() and gated.game_date.between("2023-03-30","2026-08-13").all()
    selected_keys=gated[gated.foldNumber==5].copy()
    assert len(selected_keys)==101264
    df=read_columns(OOF,["canonicalPaId","canonicalGameId","foldNumber","observedClassIndex",*PCOLS],"GATED_DEVELOPMENT_COLUMN_CHUNKS_FOLD5_CALCULATIONS_ONLY",fold5=True)
    df=df.merge(selected_keys[["canonicalPaId","game_date"]],on="canonicalPaId",validate="one_to_one",sort=False)
    raw_keys=read_columns(CACHE/"raw-development.parquet",["canonicalPaId","canonicalGameId","game_date","foldNumber"],"CONTEXT_IDENTITY_ONLY",fold5=True)
    assert all(final_oot_eligible_key_mask(raw_keys.canonicalGameId)) and raw_keys.game_date.between("2026-05-02","2026-08-13").all()
    columns=["canonicalPaId","foldNumber","batter_slg","pitcher_hr_per_bfp","matchup_platoon_advantage","batter_prior_missing","pitcher_prior_missing","batter_prior_pa_count","pitcher_prior_bf_count"]
    raw=read_columns(CACHE/"raw-development.parquet",columns,"THREE_RAW_CONTEXTS_PLUS_SAVED_EXPOSURE_METADATA",fold5=True)
    assert raw.canonicalPaId.is_unique and set(raw.canonicalPaId)==set(raw_keys.canonicalPaId)
    raw=raw.drop(columns="foldNumber")
    raw["context_available"]=True
    df=df.merge(raw,on="canonicalPaId",how="left",validate="one_to_one",sort=False)
    p=df[PCOLS].to_numpy(dtype=float)
    y=df.observedClassIndex.to_numpy(dtype=int)
    obs=np.eye(8)[y]
    assert p.shape==(101264,8) and np.isfinite(p).all() and (p>=0).all()
    assert np.max(np.abs(p.sum(axis=1)-1))<1e-12
    primary=(p[:,4]>=.05)&(p[:,4]<.10)
    available=df.context_available.eq(True).to_numpy()
    prior=pd.read_csv(PARENT/"pa/calibration-leads.csv")
    prior_double=prior[(prior.band=="DOUBLE [0.05,0.1)")&(prior.window=="fold5")].iloc[0]
    assert primary.sum()==14375 and obs[primary,4].sum()==652
    assert abs(p[primary,4].mean()-prior_double.v18_predicted)<1e-12
    rows=[]
    def row(kind,population,outcome,mask,dimension="",level=""):
        j=CLASSES.index(outcome)
        n=int(mask.sum()); f=df.loc[mask,["canonicalGameId","game_date"]]
        result={"section":kind,"population":population,"dimension":dimension,"level":level,"outcome":outcome,"PAs":n,"games":int(f.canonicalGameId.nunique()),"dates":int(f.game_date.nunique()),"predicted_count":float(p[mask,j].sum()) if n else None,"observed_count":int(obs[mask,j].sum()) if n else None,"predicted_pct":float(100*p[mask,j].mean()) if n else None,"observed_pct":float(100*obs[mask,j].mean()) if n else None,"bias_pp":float(100*(p[mask,j]-obs[mask,j]).mean()) if n else None,"context_missing_PAs":int((mask&~available).sum()),"support":"SPARSE_OR_ABSENT" if n<1000 or f.canonicalGameId.nunique()<100 else "DESCRIPTIVE_SUPPORTED"}
        rows.append(result)
        return result
    balance={}
    for label,lo,hi in [("DOUBLE 2.5–5%",.025,.05),("DOUBLE 5–10%",.05,.10),("DOUBLE 10–20%",.10,.20)]:
        m=(p[:,4]>=lo)&(p[:,4]<hi)
        if m.any():
            balance[label]=[row("outcome_balance",label,c,m) for c in CLASSES]
            assert abs(p[m].sum()-m.sum())<1e-8 and obs[m].sum()==m.sum()
            assert abs(sum(v["predicted_count"]-v["observed_count"] for v in balance[label]))<1e-8
        else:
            balance[label]=[row("adjacent_coverage",label,"DOUBLE",m)]
    dimensions={
        "batter_slg":[("<0.4",df.batter_slg<.4),("0.4–0.5",df.batter_slg.between(.4,.5,inclusive="left")),(">=0.5",df.batter_slg>=.5),("missing",df.batter_slg.isna())],
        "pitcher_hr_per_bfp":[("<0.025",df.pitcher_hr_per_bfp<.025),(">=0.025",df.pitcher_hr_per_bfp>=.025),("missing",df.pitcher_hr_per_bfp.isna())],
        "matchup_platoon_advantage":[("0",df.matchup_platoon_advantage==0),("1",df.matchup_platoon_advantage==1),("missing",df.matchup_platoon_advantage.isna())],
    }
    context_results=[]
    for dimension,levels in dimensions.items():
        masks=[]
        for level,m in levels:
            mask=primary&available&m.to_numpy()
            masks.append(mask)
            context_results.append(row("context","DOUBLE 5–10%","DOUBLE",mask,dimension,level))
        assert sum(int(m.sum()) for m in masks)==int((primary&available).sum())
    row("context_coverage","DOUBLE 5–10%","DOUBLE",primary&~available,"cache","unavailable")
    overlaps={}
    leads={"SINGLE 20–30%":(3,.20,.30),"HOME_RUN 5–10%":(2,.05,.10)}
    for label,(j,lo,hi) in leads.items():
        m=(p[:,j]>=lo)&(p[:,j]<hi)
        overlaps[label]={"lead_PAs":int(m.sum()),"overlap_PAs":int((m&primary).sum()),"share_of_double_band":float((m&primary).sum()/primary.sum()),"share_of_lead":float((m&primary).sum()/m.sum()) if m.any() else None}
        row("other_lead",label,CLASSES[j],m)
        row("overlap",label+" inside DOUBLE band",CLASSES[j],m&primary)
        row("overlap",label+" outside DOUBLE band",CLASSES[j],m&~primary)
        row("overlap_double",label+" inside DOUBLE band","DOUBLE",m&primary)
    singles=(p[:,3]>=.20)&(p[:,3]<.30)
    homers=(p[:,2]>=.05)&(p[:,2]<.10)
    overlaps["triple_overlap_PAs"]=int((primary&singles&homers).sum())
    # Narrow inspection of the three existing treated inputs, after the result
    # identifies the recorded context groups. No transform/inference is executed.
    tp=CACHE/"validation-fold-5-treated.parquet"
    tk=read_columns(tp,["canonicalPaId","canonicalGameId","game_date","foldNumber"],"TREATED_KEYS_BEFORE_CONTEXT")
    assert all(final_oot_eligible_key_mask(tk.canonicalGameId)) and tk.game_date.between("2026-05-02","2026-08-13").all()
    treated_cols=["canonicalPaId","batter_slg","pitcher_hr_per_bfp","matchup_platoon_advantage","pitcher_hr_per_bfp__prior_v1__posterior_mean","pitcher_hr_per_bfp__prior_v1__history_state"]
    treated=read_columns(tp,treated_cols,"THREE_TREATED_CONTEXTS_AND_DECLARED_PRIOR_METADATA").set_index("canonicalPaId",verify_integrity=True)
    f=df.loc[primary&available].copy()
    t=treated.reindex(f.canonicalPaId)
    assert t.index.is_unique and len(t)==len(f)
    treatment={}
    for col in dimensions:
        a=pd.to_numeric(f[col],errors="coerce").to_numpy(dtype=float)
        b=pd.to_numeric(t[col],errors="coerce").to_numpy(dtype=float)
        both=np.isfinite(a)&np.isfinite(b)
        treatment[col]={"rows":len(f),"raw_missing":int(np.isnan(a).sum()),"treated_missing":int(np.isnan(b).sum()),"finite_raw_treated_changed":int((np.abs(a[both]-b[both])>1e-12).sum()),"raw_range":[float(np.nanmin(a)),float(np.nanmax(a))],"treated_range":[float(np.nanmin(b)),float(np.nanmax(b))],"mean_finite_treated_minus_raw":float(np.mean(b[both]-a[both]))}
    treatment["exposure_metadata"]={"batter_prior_missing_count":int((f.batter_prior_missing==1).sum()),"pitcher_prior_missing_count":int((f.pitcher_prior_missing==1).sum()),"pitcher_prior_states":t.pitcher_hr_per_bfp__prior_v1__history_state.value_counts(dropna=False).to_dict(),"posterior_hr_range":[float(t.pitcher_hr_per_bfp__prior_v1__posterior_mean.min()),float(t.pitcher_hr_per_bfp__prior_v1__posterior_mean.max())]}
    result=pd.DataFrame(rows)
    result.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    earlier=prior[(prior.band=="DOUBLE [0.05,0.1)")&prior.window.isin(["fold1","fold2","fold3","fold4"])][["window","pa_count","v18_predicted","observed","v18_bias"]].to_dict("records")
    stats={"createdAtUtc":datetime.now(timezone.utc).isoformat(),"branch":"codex/mlb-starter-duration-source-intake-v1","head":"9ca94e9c0135cde7d2b852560d59a43fa45a5c17","parentManifestSha256":parent_manifest_sha,"fold5":fold,"scope":protocol,"full_fold5_PAs":len(df),"double_band_PAs":int(primary.sum()),"double_band_context_PAs":int((primary&available).sum()),"double_band_context_missing_PAs":int((primary&~available).sum()),"all_fold5_double_bias_pp":float(100*(p[:,4]-obs[:,4]).mean()),"outcome_balance":balance,"context_results":context_results,"overlaps":overlaps,"raw_treated_inspection":treatment,"earlier_fold_summaries_reused":earlier,"previous_fold5_v14_double_rate":float(prior_double.v14_predicted),"physicalReads":READS,"verification":{"fold5_and_primary_counts_match_prior":True,"all_eight_probability_and_observed_totals_reconciled_once":True,"three_context_partitions_reconcile":True,"quarantine_before_outcome_access":True,"original_manifest_unchanged":sha(PARENT/"artifact-manifest.json")==parent_manifest_sha},"limitations":{"FinalOotPayloadRead":False,"remainingSealedOotKeys":13837,"all_training_chronology_uncertified":True,"bootstrapRuns":0,"modelFits":0,"modelInference":0,"only_fold5_predictions_analysed":True,"single_row_group_requires_decoding_development_column_chunks":True}}
    plot(balance)
    stats["outputs"]=[{"path":str(OUT/n),"sha256":sha(OUT/n)} for n in ["scope.json","results.csv","outcome-balance.png"]]
    stats["script"]={"path":str(Path(__file__).resolve()),"sha256":sha(__file__)}
    (OUT/"manifest.json").write_text(json.dumps(native(stats),indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    print(result.to_string(index=False),flush=True)
    print("OVERLAPS "+json.dumps(native(overlaps)),flush=True)
    print("TREATMENT "+json.dumps(native(treatment)),flush=True)
    render_note()


def plot(balance):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(10,4.8),constrained_layout=True)
    x=np.arange(8)
    for label,offset,color in [("DOUBLE 2.5–5%",-.18,"#7b94aa"),("DOUBLE 5–10%",.18,"#b34a31")]:
        data=balance[label]
        if len(data)==8: ax.bar(x+offset,[r["bias_pp"] for r in data],width=.36,label=label,color=color)
    ax.axhline(0,color="#333",linewidth=.8)
    ax.set_xticks(x,["K","BB/HBP/CI","HR","1B","2B","3B","BIP out","Other reach"])
    ax.set_ylabel("Predicted minus observed (percentage points)")
    ax.set_title("Fold 5: eight-outcome balance in adjacent doubles bands\nHistorical timing uncertain; aggregate balance does not prescribe redistribution")
    ax.spines[["top","right"]].set_visible(False)
    ax.legend(frameon=False)
    fig.savefig(OUT/"outcome-balance.png",dpi=150,facecolor="white")
    plt.close(fig)


def render_note():
    """Finish the small successor without rereading predictions or rescoring."""
    mp=OUT/"manifest.json"
    m=json.loads(mp.read_text(encoding="utf-8"))
    note="""# Frozen fold-5 doubles follow-up

The doubles excess remains unexplained by the supported contexts. The next experiment I recommend is a fixed prospective eight-outcome calibration check of unchanged fold 5 because the error spans those contexts, and neither its cause nor a safe probability redistribution is established.

**Measured failure.** On 14,375 PAs/1,240 game IDs, V18 expected **802.42 doubles versus 652 observed** (5.582% versus 4.536%; **+1.046 percentage points**). Excess expected counts are K +11.86, BB/HBP/CI +6.13, singles +33.59 and doubles +150.42; deficits are HR −20.47, triples −20.00, BIP_OUT −143.00 and OTHER_REACH −18.54. This arithmetic balance does not identify a safe redistribution. [results.csv](results.csv) contains all eight predicted/observed counts and rates, adjacent bands, contexts and overlaps.

The adjacent 2.5–5% band has 86,652 PAs: **4.093% predicted versus 4.013% observed** (+0.080 pp). Its BIP_OUT bias reverses direction (+0.244 pp). The 10–20% band has only 12 PAs/9 games, insufficient for inference. Existing earlier-fold high-band biases are +1.136/+0.825/+0.662/+0.964 pp; V14 also overpredicts on these fold-5 rows (5.249%). Whole-population bias is +0.217 pp in fold 5 versus +0.144 pp pooled.

**Contexts and overlap.** Context exists for 13,346 high-band PAs; 1,029 are unjoined. Bias remains positive across nonmissing raw batter SLG groups (+1.086–1.443 pp), pitcher HR/BF groups (+1.123–1.190 pp) and both platoon states (+1.079/+1.112 pp). Missing SLG is the exception (−0.291 pp; 589 PAs). No specialist population emerges. Pitcher HR/BF is an explicit proxy: no saved pitcher doubles/XBH allowance field exists.

High-single and high-HR leads overlap the doubles band on 682 and 1,620 PAs; only 24 occupy all three. Most lie outside it, where singles still predict **21.842% versus 18.770%** (1,529 PAs) and HR **5.988% versus 5.015%** (5,105 PAs). These post-scan findings suggest a broader calibration pattern; they do not identify a bad matchup.

The targeted raw/treated check matched saved rules: SLG becomes its Wave2 posterior; valid raw pitcher HR rates and platoon flags remain unchanged. Missing inputs match saved exposure states. No concrete mapping, treatment or exposure defect was found. Training chronology remains uncertified.

**Next observation.** The intervention layer is evidence capture and frozen-output assessment; no particular correction or candidate comparison is justified yet. Before outcomes, freeze a future cohort of timestamped, actual pre-PA eight-class predictions from this exact fold-5 estimator, retaining PA/game IDs, input/preprocessor identities and the three contexts. Include all eligible PAs through the first complete game-day reaching **5,000 PAs in the 5–10% doubles band, at least 400 games and four active calendar weeks**. Exclude quarantined games before outcome access. Archive adjacent bands and overlapping leads; stopping must not depend on errors.

Primary measure: mean P(double) minus observed double rate in that band, with a prespecified **95% game-cluster confidence interval**. A lower bound above zero establishes prospective recurrence and permits deciding whether to develop a correction; it does not determine redistribution. An interval including zero is inconclusive: stop without fitting. A nonpositive upper bound rejects recurrence of the excess. Other-class balances and the adjacent band test whether the historical compensation pattern persists.

No fitting data are selected. Historical folds are diagnosis only; any later candidate needs separate development data and subsequent untouched prospective assessment. Four weeks cannot establish long-term robustness.

No corrected Claude export was found; whole-game metrics were not updated. Final OOT remains sealed and quarantine preceded outcome access. Original artifacts, publication and paired-study/NFL tasks are preserved, including the September 12 20:52:51.349Z restoration deadline or published-pair completion if earlier.

Reproduce from `C:\\Users\\james\\asp-model-studio`: `.\\.venv\\Scripts\\python.exe scripts/followup_mlb_v18_doubles_v1.py`. Branch `codex/mlb-starter-duration-source-intake-v1`, HEAD `9ca94e9c0135cde7d2b852560d59a43fa45a5c17`. [One plot](outcome-balance.png) · [Scope, lineage and reconciliation](manifest.json). Original diagnostic artifacts are preserved. The OOF source has one compressed Development row group, so its selected column chunks are decoded; only the 101,264 fold-5 rows enter calculations, with earlier folds reused solely as summaries.
"""
    p=OUT/"decision.md"
    p.write_text(note,encoding="utf-8")
    m["decisionNote"]={"path":str(p),"sha256":sha(p)}
    m["script"]={"path":str(Path(__file__).resolve()),"sha256":sha(__file__)}
    m["correctedExportCheck"]={"result":"NO_NEW_CORRECTED_EXPORT_FOUND_IN_BOUNDED_LOCAL_METADATA_CHECK","identifiedSource":"outputs/market-intelligence-rff-v1/source/sha256/df6ded6fa0356ff12c6e1d33dcb816cff12660c4f627b733a9336e04caefaa27","noOutcomeOrDatabaseReadDuringCheck":True,"wholeGameMetricsUpdated":False}
    m["mappingReviewSources"]=[".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/21f13e822fcfc204bcbc769f171e4e57379b56c58d7bf330ceb3cc9a0f877df5.json",".runtime/asp-model-studio/stage3-model-laboratory/objects/corrected-preprocessing/sha256/5ede17e4bd63ad1bb0aa372b71bbefe1aa7be70f03eadbe95fc6d2d7823ffe9b.json"]
    mp.write_text(json.dumps(m,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    print("Finished decision.md; no additional prediction read or calculation.",flush=True)


if __name__=="__main__":
    if "--render-only" in sys.argv: render_note()
    else: main()
