"""Inspect bounded paired replay outputs; reuse mature outcomes only after identity gate."""
from __future__ import annotations
import itertools,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
SOURCE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(SOURCE))
from scripts.run_mlb_v18_instrumented_replay import OUT,PRIOR,TABLE,guard,ref,read_ref,write,now
from scripts.run_mlb_v18_distribution_diagnosis import crps,energy

METRICS=['log_loss','brier','margin_crps','total_crps','energy_score','team_mae','margin_mae','total_mae']

def scores(home,away,actual_home,actual_away):
    h=np.asarray(home);a=np.asarray(away);y=int(actual_home>actual_away);p=np.mean(h>a)
    assert 0<p<1 and not np.any(h==a)
    return {'p_home':float(p),'log_loss':float(-np.log(p if y else 1-p)),'brier':float((p-y)**2),
      'margin_crps':crps(h-a,actual_home-actual_away),'total_crps':crps(h+a,actual_home+actual_away),
      'energy_score':energy(np.column_stack([h,a]),np.array([actual_home,actual_away])),
      'team_mae':float((abs(h.mean()-actual_home)+abs(a.mean()-actual_away))/2),
      'margin_mae':float(abs((h-a).mean()-(actual_home-actual_away))),
      'total_mae':float(abs((h+a).mean()-(actual_home+actual_away))),
      'home_mean':float(h.mean()),'away_mean':float(a.mean()),
      'home_bias':float(h.mean()-actual_home),'away_bias':float(a.mean()-actual_away),
      'margin_var':float(np.var(h-a)),'total_var':float(np.var(h+a)),
      'home_away_covariance':float(np.mean((h-h.mean())*(a-a.mean())))}

def covariance(x):
    return float(np.mean((x[:,0]-x[:,0].mean())*(x[:,1]-x[:,1].mean())))

def block_intervals(d):
    dates=sorted(d.local_game_date.unique());indices=[d.index[d.local_game_date.eq(date)].tolist() for date in dates]
    values=[]
    # Enumerate all four-date bootstrap resamples: no random draws from simulator.
    for choices in itertools.product(range(len(dates)),repeat=len(dates)):
        ix=sum([indices[i] for i in choices],[])
        values.append(d.loc[ix,[m+'_delta' for m in METRICS]].mean().to_numpy())
    values=np.asarray(values)
    return {m:{'meanPairedEffect':float(d[m+'_delta'].mean()),'dateBlockPercentile95':np.quantile(values[:,i],[.025,.975]).tolist(),
      'improvedGames':int((d[m+'_delta']<-1e-12).sum()),'worseGames':int((d[m+'_delta']>1e-12).sum()),
      'unchangedGames':int((d[m+'_delta'].abs()<=1e-12).sum())} for i,m in enumerate(METRICS)}

def main():
    identities=guard();design=json.loads((OUT/'DESIGN.json').read_bytes())
    # Only the original mature rows after identity-only quarantine. No new finals.
    original=pd.read_csv(TABLE).set_index('source_game_id')
    if not original.index.is_unique:raise ValueError('AMBIGUOUS_ORIGINAL_GAME_JOIN')
    rows=[];mechanics=[];regimes=[];bindings=[]
    for case in design['cases']:
        pk=int(case['source_game_id']);folder=OUT/'games'/str(pk)
        replay=json.loads((folder/'REPLAY.json').read_bytes());run=json.loads((folder/'COMPARISON_RUN.json').read_bytes())
        if replay['case']!=case or run['case']!=case:raise ValueError('CASE_IDENTITY_DIFFERS')
        inv=replay['invariance']
        if not all(inv['arrays'].values()) or not all(inv['scalars'].values()) or not inv['trace']:raise ValueError('INVARIANCE_RECEIPT_FAILED')
        if not run['rngEquivalent'] or not run['allWinnersAndPaAndInningsUnchanged'] or run['baselineInput']!=replay['input']:raise ValueError('CANDIDATE_BINDING_FAILED')
        x=read_ref(replay['input'])['population'];candidate=read_ref(run['candidate'])
        if ref(replay['diagnostics']['path'])!=replay['diagnostics']:raise ValueError('DIAGNOSTICS_CHANGED')
        with np.load(replay['diagnostics']['path'],allow_pickle=False) as file:arrays={k:file[k] for k in file.files}
        source=original.loc[pk];h=np.asarray(x['homeRuns']);a=np.asarray(x['awayRuns']);ch=np.asarray(candidate['homeRuns']);ca=np.asarray(candidate['awayRuns'])
        for field in ['game_id','forecast_object_sha256','local_game_date','selected','uncertainty_defect_selection']:
            if source[field]!=case[field]:raise ValueError('ORIGINAL_JOIN_IDENTITY_DIFFERS:'+field)
        if not np.array_equal(arrays['joint_final_scores'],np.column_stack([a,h])):raise ValueError('DIAGNOSTIC_PAIRING_DIFFERS')
        if not np.array_equal(h>a,ch>ca) or any(not np.array_equal(x[k],candidate[k]) for k in ['awayRuns','innings','paCounts']):raise ValueError('CANDIDATE_PATH_OR_WINNER_CHANGED')
        if not np.array_equal(candidate['terminalCreditSensitivity']['rawHomeRuns'],h) or not np.array_equal(candidate['terminalCreditSensitivity']['rawAwayRuns'],a):raise ValueError('RAW_CANDIDATE_TRAJECTORY_DIFFERS')
        excess=arrays['walkoff_nonhr_excess_credit']
        if not np.array_equal(h-ch,excess) or not np.array_equal(a,ca):raise ValueError('CANDIDATE_NOT_EXACT_TERMINAL_MECHANISM')
        base=scores(h,a,source.actual_home,source.actual_away);changed=scores(ch,ca,source.actual_home,source.actual_away)
        row={**case,'forecast_identity':source.forecast_identity,'position_id':source.position_id if pd.notna(source.position_id) else '',
          'actual_home':source.actual_home,'actual_away':source.actual_away,'outcome_authority':source.outcome_authority,
          'outcome_source_revision':source.outcome_source_revision,'outcome_source_sha256':source.outcome_source_sha256,
          'odds_american':source.odds_american,'stake':source.stake,'wager_result':source.wager_result,'profit_actual':source.profit_actual,
          'changed_draw_count':int((excess>0).sum()),'changed_draw_rate':float((excess>0).mean()),'mean_terminal_excess_credit':float(excess.mean())}
        for m in base:row[m+'_v18']=base[m];row[m+'_sensitivity']=changed[m];row[m+'_delta']=changed[m]-base[m]
        rows.append(row)
        mech={**case,'draws':len(h),'p_skipped_bottom_ninth':float(arrays['skipped_bottom_ninth'].mean()),
          'p_walkoff':float(arrays['walkoff'].mean()),'p_extra_innings':float(arrays['extras_observed'].mean()),
          'p_nonhr_walkoff_excess':float((excess>0).mean()),'excess_credit_per_game':float(excess.mean()),
          'mean_first8_covariance':covariance(arrays['runs'][:,:,:8].sum(axis=2)),
          'regulation_covariance':covariance(arrays['joint_regulation_scores']),
          'final_covariance':covariance(arrays['joint_final_scores']),
          'sensitivity_covariance':covariance(np.column_stack([ca,ch])),
          'ambiguous_third_out_run_events':int(arrays['third_out_scoring_events_by_batting_team'].sum())}
        early=arrays['runs'][:,:,:8].sum(axis=2);late=arrays['joint_final_scores']-early
        mech['ninth_and_extras_covariance']=covariance(late)
        mech['away_early_home_late_covariance']=covariance(np.column_stack([early[:,0],late[:,1]]))
        mech['away_late_home_early_covariance']=covariance(np.column_stack([late[:,0],early[:,1]]))
        phase_sum=sum(mech[k] for k in ['mean_first8_covariance','ninth_and_extras_covariance','away_early_home_late_covariance','away_late_home_early_covariance'])
        if abs(phase_sum-mech['final_covariance'])>1e-9:raise ValueError('PHASE_COVARIANCE_DECOMPOSITION_FAILED')
        for j,side in enumerate(['away','home']):
            for key in ['joint_regulation_scores','joint_final_scores','joint_extra_inning_runs','team_completed_pa','team_batting_half_opportunities','starter_final_bf','starter_outs_total','relief_bf_total','relief_outs_total','starter_runs_while_active_total','relief_runs_while_active_total']:
                mech[side+'_'+key+'_mean']=float(arrays[key][:,j].mean())
            mech[side+'_starter_duration_innings_equivalent']=float(arrays['starter_outs_total'][:,j].mean()/3)
            mech[side+'_unknown_named_relief_identity']=True
            mech[side+'_official_inherited_runner_responsibility']=None
        mechanics.append(mech)
        labels=np.where(arrays['extras_observed'],'EXTRA_INNINGS',np.where(arrays['skipped_bottom_ninth'],'SKIPPED_BOTTOM_NINTH',np.where(arrays['walkoff'],'REGULATION_WALKOFF','OTHER_REGULATION')))
        final=arrays['joint_final_scores'];grand=final.mean(axis=0);within=between=0.
        for label in sorted(set(labels)):
            mask=labels==label;pair=final[mask];weight=float(mask.mean());means=pair.mean(axis=0)
            wc=weight*covariance(pair);bc=weight*(means[0]-grand[0])*(means[1]-grand[1]);within+=wc;between+=bc
            regimes.append({'source_game_id':pk,'regime':label,'draws':int(mask.sum()),'probability':weight,
              'away_mean':float(means[0]),'home_mean':float(means[1]),'within_covariance_contribution':wc,'between_covariance_contribution':bc})
        if abs(within+between-mech['final_covariance'])>1e-9:raise ValueError('COVARIANCE_DECOMPOSITION_FAILED')
        bindings.extend([ref(folder/'REPLAY.json'),ref(folder/'COMPARISON_RUN.json')])
    d=pd.DataFrame(rows);m=pd.DataFrame(mechanics);g=pd.DataFrame(regimes)
    d.to_csv(OUT/'game_results.csv',index=False);m.to_csv(OUT/'mechanics_game_summary.csv',index=False);g.to_csv(OUT/'ending_regime_decomposition.csv',index=False)
    intervals=block_intervals(d)
    comp=[]
    for metric in METRICS:
        comp.append({'metric':metric,'unchanged_V18':float(d[metric+'_v18'].mean()),'terminal_credit_sensitivity':float(d[metric+'_sensitivity'].mean()),**intervals[metric]})
    pd.DataFrame(comp).to_csv(OUT/'comparison.csv',index=False)
    # Preserve all90 original rows and all7 mapping cases with explicit replay-subset membership.
    full=original.reset_index();full['instrumented_replay_case']=full.source_game_id.isin(d.source_game_id)
    full.to_csv(OUT/'mature_cohort_index.csv',index=False)
    summary={'computedAtUtc':now(),'classification':design['classification'],'games':len(d),'dates':d.local_game_date.nunique(),
      'selected':int(d.selected.sum()),'uncertaintyMappingReplayCases':int(d.uncertainty_defect_selection.sum()),
      'fullMatureGames':len(full),'fullUncertaintyMappingCases':int(full.uncertainty_defect_selection.sum()),
      'simulatedPairs':int(len(d)*5000),'allReplaysExactlyOriginal':True,'allCandidateWinnersAndRngUnchanged':True,
      'changedDraws':int(d.changed_draw_count.sum()),'meanChangedDrawRate':float(d.changed_draw_rate.mean()),
      'meanTerminalCreditRemoved':float(d.mean_terminal_excess_credit.mean()),'comparison':comp,
      'meanMechanics':m.select_dtypes(include=['number']).drop(columns=['source_game_id'],errors='ignore').mean().to_dict(),
      'prior90GameDiagnosis':ref(PRIOR/'SUMMARY.json'),'sameRetainedOutcomeCohort':ref(TABLE),'replayReceipts':bindings,
      'uncertaintyCaution':'Four date blocks, six deliberately stratified games; descriptive intervals only, not independent confirmation or a promotion test.'}
    write(OUT/'SUMMARY.json',summary)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    labels=[f'{r.away_team} @ {r.home_team}\n{str(r.source_game_id)}' for r in d.itertuples()]
    fig,axs=plt.subplots(1,2,figsize=(13,5.6),layout='constrained');x=np.arange(len(m))
    for label,col,color in [('Skipped bottom ninth','p_skipped_bottom_ninth','#355c9a'),('Walk-off','p_walkoff','#c97135'),('Extra innings','p_extra_innings','#3b8c74')]:axs[0].plot(x,m[col]*100,'o-',label=label,color=color)
    axs[0].set(xticks=x,xticklabels=labels,ylabel='Simulated games (%)',title='Legitimate ending mechanics affect batting exposure');axs[0].tick_params(axis='x',labelrotation=35);axs[0].legend(fontsize=8)
    for label,col,color in [('First eight innings','mean_first8_covariance','#9aa9bd'),('Regulation ending','regulation_covariance','#355c9a'),('Final scores','final_covariance','#c97135')]:axs[1].plot(x,m[col],'o-',label=label,color=color)
    axs[1].axhline(0,color='grey',lw=.7);axs[1].set(xticks=x,xticklabels=labels,ylabel='Within-forecast home/away covariance (runs²)',title='Game-state summaries, not a causal decomposition');axs[1].tick_params(axis='x',labelrotation=35);axs[1].legend(fontsize=8)
    fig.suptitle('Unchanged V18: 6 inspected games × 5,000 original paired paths',fontsize=14);fig.savefig(OUT/'01_game_ending_mechanics.png',dpi=170);plt.close(fig)
    fig,axs=plt.subplots(1,2,figsize=(12,5.5),layout='constrained')
    axs[0].barh(labels,d.changed_draw_rate*100,color='#355c9a');axs[0].set(xlabel='Paths with non-HR terminal excess credit (%)',title='One localized terminal-credit sensitivity')
    metrics=['margin_crps','total_crps','energy_score'];titles=['Margin CRPS','Total CRPS','Joint energy score']
    for i,metric in enumerate(metrics):
        means=intervals[metric]['meanPairedEffect'];lo,hi=intervals[metric]['dateBlockPercentile95']
        axs[1].errorbar(means,i,xerr=[[max(0,means-lo)],[max(0,hi-means)]],fmt='o',capsize=4,color='#c97135')
    axs[1].axvline(0,color='grey',lw=1);axs[1].set(yticks=range(3),yticklabels=titles,xlabel='Sensitivity − V18; negative favors sensitivity',title='Paired effects; 95% whole-date intervals')
    fig.suptitle('Winner probabilities and RNG paths unchanged; four dates are not fresh validation',fontsize=12);fig.savefig(OUT/'02_controlled_experiment.png',dpi=170);plt.close(fig)
    lines=['# V18 instrumented replay and one controlled terminal-credit experiment','',
      f'Completed {summary["computedAtUtc"]}. Private development analysis of already inspected games; no production, acquisition or frozen-assessment changes.','',
      '## Finding','',
      f'V18 retains a localized terminal-score representation weakness: in these {len(d)} cases, {summary["changedDraws"]:,} of {summary["simulatedPairs"]:,} original paths ({summary["meanChangedDrawRate"]:.2%}) credited non-home-run walk-off runs beyond the run needed to win. The average excess was {summary["meanTerminalCreditRemoved"]:.4f} runs per forecast. This experiment changed only that event-derived scoring credit, preserved every HOME_RUN in full, and retained all original sampled transitions and scores alongside the experimental credit. It did not impose a generic score cap or rearrange paired team scores.','',
      '**Every winner, random-number stream, PA count and inning count stayed unchanged. This mechanism cannot explain underdog probability overvaluation.** Its score-distribution effects are below; none are independent validation.','',
      'The eight-class event representation lacks over-fence versus inside-park home runs, exact runner advances/touches, appeals/awards and force-versus-time-play attribution. Accordingly, this is a precisely specified terminal-credit sensitivity, not a certified implementation of every official scoring rule. A third-out transition with positive runs is flagged as ambiguous, not automatically illegal.','',
      '## Scope and invariance','',
      'The unchanged 90-game September 10–17 cohort remains the historical record: 31 selected, 59 nonselected and all seven uncertainty-mapping selections. No August payload was opened. Identity-only quarantine checks passed before outcome loading. The six replay cases were fixed at signed predicted-margin quartile positions within nonselected, ordinary-selected and uncertainty-mapping-selected strata. Their outcomes were already inspected; selection used only forecast and selection metadata. This is a purposive development case study, not a new holdout or population-weighted estimate.','',
      'All six 5,000-draw replays matched the exact original home/away arrays, innings, PA counts, numeric summaries and representative trace. Counter-enabled/disabled checks retain all three RNG stream seeds, calls, value counts and final states. Existing EXP-027 counters, historical replay authority and exact one-row preprocessing semantics were reused. No fitting, provider call, calibration or weight/threshold search occurred.','',
      '## Same-game comparison','',
      'Lower scores/errors are better. Effects are sensitivity minus unchanged V18. Intervals enumerate whole-date bootstrap resamples; only four dates and six selected cases make them descriptive. Simulation draws are not the uncertainty unit.','',
      '| Metric | V18 | Terminal credit | Paired effect | 95% date-block interval |','|---|---:|---:|---:|---:|']
    for c in comp:
        lo,hi=c['dateBlockPercentile95'];lines.append(f'| {c["metric"]} | {c["unchanged_V18"]:.6f} | {c["terminal_credit_sensitivity"]:.6f} | {c["meanPairedEffect"]:+.6f} | [{lo:+.6f}, {hi:+.6f}] |')
    lines += ['', 'Winner probabilities come from the coherent original paired population; they were not inferred from changed means. Identical winner events make log loss and Brier identical by construction. The original wagers, selection labels, odds, stakes and results are retained in the joined table without recalculating decisions or expected profit.','',
      '## Mechanics and the margin/total contrast','',
      f'Across these forecast populations, skipped bottom ninths occurred in {m.p_skipped_bottom_ninth.mean():.1%} of paths, walk-offs in {m.p_walkoff.mean():.1%}, and extra innings in {m.p_extra_innings.mean():.1%}. Walk-offs and extra innings can overlap. Home teams averaged {m.home_team_completed_pa_mean.mean():.2f} completed PAs versus {m.away_team_completed_pa_mean.mean():.2f} for away teams. These legitimate game-ending mechanics change batting opportunities; equalizing them would change the game being modeled.','',
      f'Mean within-forecast home/away covariance was {m.mean_first8_covariance.mean():+.4f} runs² through eight innings, {m.regulation_covariance.mean():+.4f} at regulation ending, and {m.final_covariance.mean():+.4f} at the final. The late-game stage materially changes model dependence. The exact early/late covariance identity and ending-regime table are retained, but these are observed path decompositions, not causal interventions: ninth-inning scoring, game-ending selection and extras all contribute. They do not establish why actual forecast residuals differed.','',
      'The completed 90-game diagnosis is reused unchanged: centered error variance divided by simulated variance was 1.327 for margin and 0.901 for total, with wide date-block intervals. The descriptive margin-center slope was 2.05 with an interval spanning 1; model-wide overdispersion or compressed relative strength was not established. Its negative cross-game residual covariance is not a directly identified within-game covariance setting. This replay does not force that residual covariance into the simulator.','',
      'The terminal-credit experiment isolates one representation effect. Its exact zero effect on winners rules it out as a remedy for the probability question. Determining whether expected relative strength is wrong still requires probabilities matched to real PA states and supported actual usage, rather than simulated exposure sums alone. No claim that legitimate endings or one localized accounting weakness primarily caused the mature-cohort residual contrast is supported.','',
      '## What the evidence can and cannot attribute','',
      'Draw-level and game-level tables retain regulation/final scores, both teams’ PA and half-inning opportunities, skipped ninths, walk-offs, extras, starter BF/outs/hook coordinates and anonymous relief BF/outs. Pitcher-side exposures are distinguished from batting-side scores. No observed hook is encoded as -1 rather than an invented removal. Runs while a pitcher state is active include inherited runners and are not official pitcher responsibility.','',
      'The original starter hook is an unfitted monotone policy using a default expected 23 BF, inning, runs and times through the order; the default is not a fixed 23-BF removal. Relief uses the original team/staff mixture rather than a named simulated reliever sequence. The counters expose these assumptions but do not prove that they caused a particular loss. Missing actual-PA probability capture, reliever selection/availability and inherited-runner attribution prevent a complete PA-to-game causal audit.','',
      '## Decision','',
      'Retain this bounded experiment as a localized mechanism finding. It establishes an inspectable terminal-credit sensitivity and its numerical effects, not a production improvement or a cure for apparent underdog overvaluation. Keep V18 unchanged. Before promoting a terminal-credit correction, establish the missing scoring-event semantics on permitted development examples; before choosing a strength or dispersion intervention, obtain the missing actual-state PA/usage evidence. A 2027 replication was not required for this development work. No second candidate or broader algorithm search was started.','',
      '## Files','',
      '- `game_results.csv`: exact forecast/outcome join, original selection/wager fields and paired scores.','- `mature_cohort_index.csv`: all original 90 cases, all seven mapping cases, and explicit replay membership.','- `mechanics_game_summary.csv` and `ending_regime_decomposition.csv`: joint path and exposure summaries.','- `games/<MLBAM>/draw_summaries.csv.gz`, `diagnostics.npz`, and `candidate_population.json`: inspectable paired draws, original counters, experimental scores and raw terminal events.','- `DESIGN.json`, `SOURCE_ARCHIVE.json`, per-game receipts and `SUMMARY.json`: frozen scope, exact identities, clocks and invariance.','',
      '![Ending mechanics](01_game_ending_mechanics.png)','', '![Controlled comparison](02_controlled_experiment.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'games':len(d),'changedDraws':summary['changedDraws'],'comparison':comp},indent=2),flush=True)

if __name__=='__main__':main()
