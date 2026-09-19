"""Assemble the inspected-cohort report and supplementary uncertainty tables."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from run_mlb_v18_distribution_diagnosis import OUTPUT,CONFIG,summary,dump,now,ref

d=pd.read_csv(OUTPUT/'game_results.csv');s=json.loads((OUTPUT/'SUMMARY.json').read_text())
rows=[]
for day in sorted(d.local_game_date.unique()):
    a=summary(d[d.local_game_date!=day])
    rows.append({'omitted_date':day,**{k:a[k] for k in ['n','margin_center_slope','margin_centered_error_variance_ratio','total_centered_error_variance_ratio','residual_home_away_correlation']}})
pd.DataFrame(rows).to_csv(OUTPUT/'leave_one_date_out.csv',index=False)

# Wager uncertainty is diagnostic: resample whole dates, preserving original
# stakes, prices, result labels and the seven cases; no new probabilities/EV.
rng=np.random.default_rng(CONFIG['seed']);dates=d.local_game_date.unique()
g=d[d.selected].copy();g['model_underdog']=g.selected_probability<.5
g['selected_won']=g.wager_result.eq('WIN').astype(float)
group_masks={'ALL':pd.Series(True,index=g.index),'MODEL_FAVORITE':~g.model_underdog,'MODEL_UNDERDOG':g.model_underdog,'SEVEN_MAPPING_CASES':g.uncertainty_defect_selection}
stats={n:[] for n in group_masks}
for _ in range(3000):
    chosen=rng.choice(dates,len(dates),replace=True)
    for name,mask in group_masks.items():
        source=g[mask];sample=pd.concat([source[source.local_game_date==day] for day in chosen])
        if len(sample):stats[name].append([float((sample.selected_won-sample.selected_probability).mean()),float(sample.profit_actual.sum()/sample.stake.sum())])
uncertainty=[]
for name,v in stats.items():
    actual=g[group_masks[name]];a=np.array(v)
    uncertainty.append({'group':name,'n':len(actual),'dates':actual.local_game_date.nunique(),'win_minus_predicted_probability':float((actual.selected_won-actual.selected_probability).mean()),'gap_lower95':float(np.quantile(a[:,0],.025)),'gap_upper95':float(np.quantile(a[:,0],.975)),'realized_roi':float(actual.profit_actual.sum()/actual.stake.sum()),'roi_lower95':float(np.quantile(a[:,1],.025)),'roi_upper95':float(np.quantile(a[:,1],.975)),'nonemptyReplicates':len(v)})
pd.DataFrame(uncertainty).to_csv(OUTPUT/'original_wager_uncertainty.csv',index=False)

report='''# V18 score-distribution diagnosis

**The retained evidence does not establish general underdog overvaluation, and it does not support globally overdispersed margins. Compressed expected margins remain a plausible but uncertain symptom. The clearest follow-up signal is the difference between margin and total dispersion and their implied home/away dependence. No correction is selected.**

This is an exploratory diagnosis of **90 already-inspected games on eight dates, September 10–17**, using each exact original 5,000-draw paired population. There are **31 selected and 59 nonselected forecasts**. The seven uncertainty-mapping selections remain in the historical record. Fifteen September 18 forecasts without finals at the previous study's retained cutoff remain outside this mature cohort; no newly available outcomes were added. Legacy models, the sealed August cohort and whole-game exclusions remain separate. This is not fresh holdout evidence or a promotion result.

## What the scores show

Errors below are **forecast minus actual**, in runs; CRPS and energy score are proper distribution scores, lower is better. Their absolute values alone are not a proof of adequate calibration.

| Target | Mean bias | MAE | RMSE | CRPS |
|---|---:|---:|---:|---:|
| Home runs | −0.577 | 2.464 | 3.362 | 1.759 |
| Away runs | −0.097 | 2.285 | 2.987 | 1.589 |
| Home−away margin | −0.480 | 3.576 | 4.858 | 2.586 |
| Total runs | −0.674 | 3.169 | 4.104 | 2.282 |

Predicted home/away averages were 4.345/4.448, versus actual 4.922/4.544. Home underprediction is concentrated in nonselected games (−0.995 runs; selected +0.218). Overall home-bias 95% date-block interval is [−1.252, +0.187]; total-bias interval [−1.516, +0.142]. This does not justify an additive home or total adjustment.

### Compression versus excess spread

* **Center compression:** the descriptive regression of actual home margin on original predicted margin has slope **2.05**, with 95% date-block interval **[0.57, 3.37]**. A slope above one is compatible with compression; the interval includes one. Leaving out one date produces slopes 1.61–2.62, showing a recurring direction within this inspected sample, not independent confirmation. Forecast margin SD is only 0.819 runs, so estimating the slope is inherently noisy. A narrow range of predicted means compared with realized outcomes is expected and is not, by itself, evidence of compression.
* **Margin spread:** centered realized error variance divided by mean simulated variance is **1.33 [0.82, 1.78]**. Ratios below one would support excess spread; this point estimate goes the other way. Simulated margin SD is 4.196 runs versus margin RMSE 4.858. Every leave-one-date ratio exceeds one (1.15–1.44). Broadly shrinking simulated margins is unsupported.
* **Total spread:** the corresponding ratio is **0.90 [0.56, 1.23]**. The selected subset is more concentrated (0.62), while margin variation is not similarly small (1.17). These are different targets and populations; a single global variance correction would conflate them.
* **Joint dependence:** average simulated home/away covariance is **+0.144 runs²**, while the centered realized error covariance is **−1.746 runs²**. The latter's date-block interval is [−3.190, −0.194]; realized residual correlation is −0.177 [−0.347, −0.023], versus average simulated correlation +0.016. This is compatible with the margin/total contrast because Var(H−A)=Var(H)+Var(A)−2Cov(H,A). However, cross-game residual covariance also includes misspecified conditional means, schedule mix and outcome noise; it is not a directly observed within-game covariance parameter and must not be copied into a simulator.

![Scoring centers](01_scoring_centers.png)

## Distribution shape and discrete calibration

Integer intervals contain more than their nominal continuous probability. Compare observed coverage with the **actual retained model mass**, not simply the label.

| Target / central interval | Actual model mass | Observed coverage | 95% date-block interval |
|---|---:|---:|---:|
| Margin 50% | 58.3% | 57.8% | 49.4–66.2% |
| Margin 80% | 83.4% | 80.0% | 72.2–87.5% |
| Margin 95% | 96.1% | 93.3% | 88.0–98.1% |
| Total 50% | 58.1% | 66.7% | 57.1–75.8% |
| Total 80% | 84.5% | 88.9% | 83.3–93.7% |
| Total 95% | 96.3% | 96.7% | 92.6–100.0% |

The discrete PIT histogram fractionally spreads each outcome over its empirical CDF jump. It avoids treating discrete midranks as uniform or choosing a favorable random jitter. Margin ranks do not show the strong central excess expected from broadly excessive margin spread. Total ranks have more central mass, consistent with the coverage results, but the overall variance interval includes one.

Joint energy score is **2.679 [2.267, 3.096]**. An empirical highest-mass joint-score region containing 90.4% of model mass covers 80/90 outcomes (88.9%). These are joint diagnostics, not independent home/away draws. Original paired arrays remain unchanged.

![Distribution shape](02_distribution_shape.png)

## Winner probabilities and the original selections

All 90 original probabilities exactly reconcile to the retained paired draws. That establishes numerical translation consistency, not real-world probability calibration. Eight forecasts favor a different side by win frequency than by score mean; distribution asymmetry can produce this without a coding error. No win probability was inferred from score means.

| Population | Games | Log loss | Brier | Joint energy |
|---|---:|---:|---:|---:|
| All | 90 | 0.6758 | 0.2414 | 2.679 |
| Selected | 31 | 0.6761 | 0.2415 | 2.510 |
| Nonselected | 59 | 0.6757 | 0.2414 | 2.768 |
| Seven mapping cases (included above) | 7 | 0.6731 | 0.2398 | 2.837 |

Overall log-loss interval is [0.6420, 0.7153], Brier [0.2251, 0.2608]. Selected/nonselected log-loss intervals overlap substantially: [0.6259, 0.7224] and [0.6366, 0.7272]. The sample does not establish worse winner scoring among selected forecasts.

Model favorites won **51/90 = 56.67%**, against mean predicted **56.71%**. The paired win-minus-probability gap is −0.04 percentage points [−10.04, +7.97]. Underdogs have the complementary result. This aggregate equality can conceal conditional errors. Favorite-probability groups are 19/40 wins versus 52.7% predicted, 15/24 versus 56.7%, and 17/26 versus 62.8%. Home-probability bins contain only 8–23 games and are visibly irregular. An unapplied logistic calibration diagnostic gives intercept 0.17 [−0.18, 0.47] and slope 1.09 [−0.31, 2.76]; it does not establish overconfidence or underconfidence.

| Original selected side | W–L | Mean model p | Mean decimal odds | Stake | Actual profit | Recorded raw / controlling expected profit |
|---|---:|---:|---:|---:|---:|---:|
| All | 13–18 | 49.9% | 2.307 | $70.18 | −$10.02 | +$9.11 / +$5.83 |
| Model favorite | 7–8 | 56.1% | 2.016 | $31.80 | −$4.41 | +$4.16 / +$2.85 |
| Model underdog | 6–10 | 44.1% | 2.579 | $38.38 | −$5.61 | +$4.95 / +$2.98 |
| Seven mapping cases (included above) | 5–2 | 55.1% | 1.977 | $10.62 | +$3.00 | +$0.56 / +$0.15 |

These are model-defined favorites/underdogs, not bookmaker favorite labels. Both selected groups fell below their recorded mean probability. Six wins among 16 selected underdogs is insufficient to diagnose systematic overvaluation; `original_wager_uncertainty.csv` retains date-block probability-gap and ROI intervals. Recorded expected profit is the historical forecast-dependent expectation, not demonstrated true EV. The seven cases are neither removed nor relabeled, and their positive profit does not excuse the historical field mismatch. A loss alone does not make a decision bad.

Mean finite-draw MC standard error is **0.00698 probability units (0.70 percentage points)**. It measures numerical sampling precision conditional on the model, not uncertainty about model validity, inputs, calibration or wagering returns. No market-relative edge claim is made here; adequate quote evidence remains a separate requirement.

![Probability and dispersion](03_probability_and_dispersion.png)

## What the engine evidence can and cannot explain

Original simulations retain innings and PA counts. Predicted extras average **9.70%**. Of the model probability that either team exceeds 14 runs, **97.60% occurs in regulation and 2.40% in extras**. Thus extreme draws are predominantly a regulation phenomenon in this cohort. The model assigns a mean 1.02% probability to that event; it occurred twice in 90 inspected outcomes. This small count cannot establish tail calibration, and an extreme individual draw is distinct from an extreme forecast mean.

The inspected implementation uses a default BF23 starter-removal policy with inning, BF, runs and times-through-order effects; selected inputs lack individualized workload history. Relief uses an anonymous average of staff PA templates, not named availability and fatigue. Lineup order advances modulo nine across innings. The empirical transition hierarchy, inning switches and extras runner are implemented, but only one representative event trace is retained per forecast. Context limits on inning/score difference do not clip final simulated scores.

These are known representation limits, **not newly established implementation defects**. The retained scores cannot separate PA-probability error from run-transition, starter-exposure, bullpen or game-ending error. Per-draw component responsibility and certified actual participant/inning attribution are insufficient for causal isolation. The full source-bound explanation is in `MECHANICS.md`; prediction-only strata are in `retained_mechanics_diagnostics.csv`. No realized participant was substituted into a pregame input.

## One next experiment

**Recommend a prospective replication of the joint home/away dependence symptom, with unchanged V18 and instrumented regulation-to-final summaries.** Hypothesis: conditional home/away dependence is misrepresented enough to produce broader realized margin errors without comparably broad total errors; the apparent center compression may instead reflect conditional-mean error. This directly tests the strongest joint symptom before selecting a component patch.

Freeze one analysis before enrollment. Retain each original paired score, regulation-end score, innings/PA counts and per-draw starter/relief run exposure; preserve exact pregame inputs and model identity. Join genuinely admitted finals and inning totals with disclosed availability clocks. Use every eligible forecast, retain selection labels, and compare the covariance mismatch, centered margin/total variance ratios and center slope with date-block uncertainty. Energy score, margin/total CRPS and winner scores remain guardrails; no recalibration, clipping or weight search is part of this replication. Missing participant attribution remains missing.

Aim for **at least 200 games across 20 regular-season dates**, with no postseason pooling and no promotion conclusion from a smaller sample. The remaining 2026 collection period cannot supply 20 new dates before the existing expiry. A sufficiently sized clean evaluation therefore requires a separately authorized 2027 regular-season cohort; any smaller permitted remainder-of-2026 replication would be explicitly inconclusive. Required instrumentation, source permission and future collection authorization must be established before starting. This is a recommendation, not an activated study or extension of current budgets. Do not substitute these 90 inspected games as its test set.

This differs from the completed six-game blend and score-filter studies: no recent-score reference or truncation is used. It also does not repeat the small conditional-transition challenger: no transition change is selected from these results. The experiment register's data and validation gates remain in force.

## Reproducibility and limitations

`game_results.csv` joins by game, original forecast and position identity and retains exact population/outcome references, clocks, probabilities, original wager fields and mapping-case flags. `group_summary.csv`, `calibration_bins.csv`, `discrete_pit.csv`, `leave_one_date_out.csv` and both wager tables expose every aggregation. `SOURCE_INDEX.json`, the mechanics receipts and delivery receipt bind physical sources and implementation. Original reconstruction checks are reused; no six-game study was rerun.

The main intervals use 3,000 resamples of whole dates, not 450,000 simulation draws. Logistic intervals use 1,000 diagnostic fits with convergence/score-gradient validation. Eight dates and repeated teams across dates give weak uncertainty resolution; the intervals are descriptive, not multiple-testing-adjusted confirmatory evidence. Conditional covariance is not identifiable from one outcome per game, and outcomes have already been inspected. Subgroups have even less support. No production model, policy, calibration, publisher or frozen assessment schedule changed.
'''
(OUTPUT/'REPORT.md').write_text(report,encoding='utf-8')
notebook={'cells':[{'cell_type':'markdown','metadata':{},'source':['# V18 retained-distribution diagnosis\n','Exploratory, 90 previously inspected games. This notebook reads only derived outputs; it does not acquire outcomes or rerun simulations.']},{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':['from pathlib import Path\n','import pandas as pd, json\n',f'root = Path({str(OUTPUT)!r})\n',"summary = pd.read_csv(root / 'group_summary.csv')\n","summary[['group','n','margin_crps','total_crps','log_loss','brier','energy_score']]\n"]},{'cell_type':'code','execution_count':None,'metadata':{},'outputs':[],'source':["games = pd.read_csv(root / 'game_results.csv')\n","assert len(games) == games.game_id.nunique() == 90\n","assert games.selected.sum() == 31\n","assert games.uncertainty_defect_selection.sum() == 7\n","pd.read_csv(root / 'original_wager_groups.csv')\n"]}], 'metadata':{'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'}},'nbformat':4,'nbformat_minor':5}
dump(OUTPUT/'inspect_results.ipynb',notebook)
dump(OUTPUT/'REPORT_BUILD_RECEIPT.json',{'builtAtUtc':now(),'source':ref(__file__),'inputSummary':ref(OUTPUT/'SUMMARY.json'),'mainConfigurationUnchanged':True,'supplementarySensitivity':'Leave-one-date-out and descriptive original-wager date-block intervals; no candidate selection or model changes','intermediateReportingFixes':['Normalized historical HOME/AWAY labels before computing selected-side diagnostics; asserted all 31 WIN/LOSS labels','Verified prior delivered CSV hash before loading outcomes','Required logistic convergence or independently small gradient','Used absolute original mean margin for declared magnitude bins, retaining all eight mean/probability-side disagreements'],'numericalUnitChecksPassed':4,'allThreePlotsVisuallyReviewed':True})
print(OUTPUT/'REPORT.md')
