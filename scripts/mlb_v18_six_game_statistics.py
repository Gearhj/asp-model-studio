"""Fixed descriptive statistics for the predeclared six-game study, no fitting."""
from __future__ import annotations

import math
import numpy as np
import pandas as pd

SEED = 20260919
RESAMPLES = 2000


def interval_by_date(frame, statistic):
    """Resample games by whole local-date blocks, never simulation draws."""
    dates = sorted(frame.game_date.unique())
    point = float(statistic(frame)) if len(frame) else float('nan')
    if len(dates) < 2:
        return {'estimate': point, 'lower95': None, 'upper95': None,
                'date_blocks': len(dates), 'valid_resamples': 0}
    groups = [frame[frame.game_date.eq(d)] for d in dates]
    rng = np.random.default_rng(SEED)
    values = []
    for indexes in rng.integers(0, len(groups), (RESAMPLES, len(groups))):
        sample = pd.concat([groups[i] for i in indexes], ignore_index=True)
        value = float(statistic(sample))
        if np.isfinite(value):
            values.append(value)
    lo, hi = np.quantile(values, [.025, .975]) if values else (None, None)
    return {'estimate': point, 'lower95': lo, 'upper95': hi,
            'date_blocks': len(dates), 'valid_resamples': len(values)}


def wilson(wins, n):
    if not n:
        return (None, None)
    z = 1.959963984540054
    p = wins/n
    c = (p+z*z/(2*n))/(1+z*z/n)
    h = z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return c-h, c+h


def add_losses(frame):
    f = frame.copy()
    h, a = f.actual_home, f.actual_away
    for arm in ['v18', 'team6', 'team6_blend', 'h2h6', 'h2h6_blend']:
        eh, ea = f[arm+'_home']-h, f[arm+'_away']-a
        f[arm+'_team_mae'] = (eh.abs()+ea.abs())/2
        f[arm+'_team_mse'] = (eh*eh+ea*ea)/2
        f[arm+'_team_bias'] = (eh+ea)/2
        f[arm+'_margin_mae'] = (eh-ea).abs()
        f[arm+'_margin_mse'] = (eh-ea)**2
        f[arm+'_margin_bias'] = eh-ea
        f[arm+'_total_mae'] = (eh+ea).abs()
        f[arm+'_total_mse'] = (eh+ea)**2
        f[arm+'_total_bias'] = eh+ea
    decisive = h.notna() & a.notna() & h.ne(a)
    y = h.gt(a).astype(float)
    p = f.p_home_win
    f['v18_brier'] = ((p-y)**2).where(decisive)
    # Guard only floating point log evaluation; original probabilities retained.
    f['v18_log_loss'] = (-(y*np.log(p.clip(1e-15,1-1e-15))+(1-y)*np.log((1-p).clip(1e-15,1-1e-15)))).where(decisive)
    return f


def comparisons(f):
    rows = []
    scored = f[f.actual_home.notna() & f.actual_away.notna()]
    for ref in ['team6', 'h2h6']:
        available = scored[scored[ref+'_home'].notna() & scored[ref+'_away'].notna()]
        cohorts = {
            'AVAILABLE_SUPPORT': available,
            'COMPLETE_SIX': available[available[ref+'_complete_six']],
            'BOTH_REFERENCES_COMPLETE_SIX': available[available.team6_complete_six & available.h2h6_complete_six]
        }
        for support, pop in cohorts.items():
            for selection, sub in [('ALL',pop),('SELECTED',pop[pop.selected]),('NONSELECTED',pop[~pop.selected])]:
                if not len(sub):
                    continue
                for arm in ['v18',ref,ref+'_blend']:
                    r = {'reference':ref,'support_population':support,'selection':selection,'arm':arm,'games':len(sub),'date_blocks':sub.game_date.nunique()}
                    for dim in ['team','margin','total']:
                        r[dim+'_mae'] = sub[arm+'_'+dim+'_mae'].mean()
                        r[dim+'_rmse'] = math.sqrt(sub[arm+'_'+dim+'_mse'].mean())
                        r[dim+'_bias'] = sub[arm+'_'+dim+'_bias'].mean()
                        # Date-block aggregate is algebraically identical to rebuilding every sampled frame.
                        tmp = sub[['game_date',arm+'_'+dim+'_mae']].copy()
                        delta = sub[arm+'_'+dim+'_mae']-sub['v18_'+dim+'_mae']
                        ci = paired_interval(sub.game_date.to_numpy(),delta.to_numpy())
                        r[dim+'_mae_delta_vs_v18'] = ci['estimate']
                        r[dim+'_delta_lower95'] = ci['lower95']
                        r[dim+'_delta_upper95'] = ci['upper95']
                        r['valid_resamples'] = ci['valid_resamples']
                    rows.append(r)
    return pd.DataFrame(rows)


def paired_interval(dates, values):
    ok = np.isfinite(values)
    values, dates = values[ok], dates[ok]
    if not len(values):
        return {'estimate':None,'lower95':None,'upper95':None,'date_blocks':0,'valid_resamples':0}
    unique = sorted(set(dates))
    point = float(values.mean())
    if len(unique)<2:
        return {'estimate':point,'lower95':None,'upper95':None,'date_blocks':len(unique),'valid_resamples':0}
    totals=np.array([values[dates==d].sum() for d in unique])
    counts=np.array([(dates==d).sum() for d in unique])
    indexes=np.random.default_rng(SEED).integers(0,len(unique),(RESAMPLES,len(unique)))
    draws=totals[indexes].sum(axis=1)/counts[indexes].sum(axis=1)
    lo,hi=np.quantile(draws,[.025,.975])
    return {'estimate':point,'lower95':float(lo),'upper95':float(hi),'date_blocks':len(unique),'valid_resamples':len(draws)}


def group_difference(sub, variable, group_col):
    """UNUSUAL minus ORDINARY, block bootstrap preserving both group membership."""
    sub=sub[sub[group_col].isin(['UNUSUAL','ORDINARY']) & sub[variable].notna()]
    unique=sorted(sub.game_date.unique())
    if not len(sub) or sub[group_col].nunique()<2:
        return {'estimate':None,'lower95':None,'upper95':None,'date_blocks':len(unique),'valid_resamples':0}
    unusual=sub[group_col].eq('UNUSUAL')
    point=float(sub.loc[unusual,variable].mean()-sub.loc[~unusual,variable].mean())
    sums=np.zeros((len(unique),2));counts=np.zeros_like(sums)
    for i,d in enumerate(unique):
        for j,label in enumerate(['UNUSUAL','ORDINARY']):
            x=sub.loc[sub.game_date.eq(d)&sub[group_col].eq(label),variable]
            sums[i,j]=x.sum();counts[i,j]=len(x)
    if len(unique)<2:
        return {'estimate':point,'lower95':None,'upper95':None,'date_blocks':len(unique),'valid_resamples':0}
    ix=np.random.default_rng(SEED).integers(0,len(unique),(RESAMPLES,len(unique)))
    den=counts[ix].sum(axis=1);num=sums[ix].sum(axis=1)
    valid=(den>0).all(axis=1)
    draw=num[valid,0]/den[valid,0]-num[valid,1]/den[valid,1]
    lo,hi=np.quantile(draw,[.025,.975]) if len(draw) else (None,None)
    return {'estimate':point,'lower95':lo,'upper95':hi,'date_blocks':len(unique),'valid_resamples':int(valid.sum())}


def outlier_tables(f):
    rows=[];diffs=[]
    scored=f[f.actual_home.notna() & f.actual_away.notna()]
    for ref in ['team6','h2h6']:
        for support,pop in [('AVAILABLE_SUPPORT',scored),('COMPLETE_SIX',scored[scored[ref+'_complete_six']])]:
            for selection,sub in [('ALL',pop),('SELECTED',pop[pop.selected]),('NONSELECTED',pop[~pop.selected])]:
                for label,g in sub.groupby(ref+'_outlier'):
                    r={'reference':ref,'support_population':support,'selection':selection,'outlier_group':label,'games':len(g),'date_blocks':g.game_date.nunique()}
                    for k in ['v18_team_mae','v18_margin_mae','v18_total_mae','v18_brier','v18_log_loss']:
                        r[k]=g[k].mean()
                    r['mean_deviation_max_team_runs']=g[ref+'_max_abs_team_deviation'].mean()
                    r['uncertainty_defect_games']=int(g.uncertainty_defect_selection.sum())
                    rows.append(r)
                for metric in ['v18_team_mae','v18_margin_mae','v18_total_mae','v18_brier','v18_log_loss']:
                    ci=group_difference(sub,metric,ref+'_outlier')
                    diffs.append({'reference':ref,'support_population':support,'selection':selection,'metric':metric,**ci})
    wagers=f[f.selected].copy()
    wagers['loss_indicator']=wagers.wager_result.eq('LOSS').astype(float).where(wagers.wager_result.isin(['WIN','LOSS']))
    wrows=[]
    for ref in ['team6','h2h6']:
        for support,pop in [('AVAILABLE_SUPPORT',wagers),('COMPLETE_SIX',wagers[wagers[ref+'_complete_six']])]:
            for label,g in pop.groupby(ref+'_outlier'):
                won=int(g.wager_result.eq('WIN').sum());lost=int(g.wager_result.eq('LOSS').sum())
                lo,hi=wilson(won,won+lost)
                wrows.append({'reference':ref,'support_population':support,'outlier_group':label,'positions':len(g),'wins':won,'losses':lost,'other':len(g)-won-lost,'win_rate':won/(won+lost) if won+lost else None,'win_rate_lower95':lo,'win_rate_upper95':hi,'stake':g.stake.sum(),'actual_profit':g.profit_actual.sum(),'recorded_expected_profit_raw':g.expected_profit_raw.sum(),'recorded_expected_profit_controlling':g.expected_profit_controlling.sum(),'mean_decimal_odds':g.odds_decimal.mean(),'median_american_odds':g.odds_american.median(),'min_american_odds':g.odds_american.min(),'max_american_odds':g.odds_american.max(),'uncertainty_defect_positions':int(g.uncertainty_defect_selection.sum()),'roi':g.profit_actual.sum()/g.stake.sum() if g.stake.sum() else None})
            for metric in ['loss_indicator','profit_actual']:
                diffs.append({'reference':ref,'support_population':support,'selection':'SELECTED_WAGERS','metric':metric,**group_difference(pop,metric,ref+'_outlier')})
    return pd.DataFrame(rows),pd.DataFrame(diffs),pd.DataFrame(wrows)


def charts(f, comparison, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False,'axes.labelcolor':'#25303d','text.color':'#25303d'})
    colors={'SELECTED_WIN':'#246494','SELECTED_LOSS':'#c27827','NONSELECTED':'#7e8791'}
    fig,axes=plt.subplots(1,2,figsize=(12,4.8),layout='constrained')
    for ax,ref,title in zip(axes,['team6','h2h6'],['Team last six games: full support','H2H available slots: 1-6 meetings']):
        sub=f[f.actual_home.notna() & f[ref+'_max_abs_team_deviation'].notna()]
        for label,mask,marker in [('NONSELECTED',~sub.selected,'o'),('SELECTED_WIN',sub.selected & sub.wager_result.eq('WIN'),'^'),('SELECTED_LOSS',sub.selected & sub.wager_result.eq('LOSS'),'x')]:
            g=sub[mask]
            ax.scatter(g[ref+'_max_abs_team_deviation'],g.v18_team_mae,c=colors[label],marker=marker,s=38,alpha=.75,label=label.replace('_',' ').title()+f' (n={len(g)})')
        ax.axvline(2,color='#25303d',ls='--',lw=1)
        ax.set_title(title+f' | n={len(sub)}')
        ax.set_xlabel('Largest team-mean deviation from reference (runs)')
        ax.set_ylabel('Original V18 mean per-team absolute error (runs)')
        ax.set_xlim(left=0);ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.15)
        ax.legend(fontsize=8,loc='upper right')
    fig.suptitle('Pregame score deviation and later score error',fontweight='bold',fontsize=15)
    fig.supxlabel('Fixed dashed line: 2-run unusual-mean threshold. Team history: 90/90 complete; H2H: only 3/66 complete six-meeting histories.',fontsize=9)
    fig.savefig(output/'01_deviation_and_score_error.png',dpi=170)
    plt.close(fig)
    fig,axes=plt.subplots(1,3,figsize=(12,4.8),layout='constrained')
    c=comparison[(comparison.selection=='ALL') & (comparison.support_population=='AVAILABLE_SUPPORT') & (comparison.arm!='v18')].copy()
    labels=[]
    for _,r in c.iterrows():
        labels.append(('Team last6' if r.reference=='team6' else 'H2H 1-6 slots')+(' 50/50 blend' if r.arm.endswith('blend') else ' alone')+f' (n={r.games})')
    for ax,metric,title in zip(axes,['team','margin','total'],['Per-team MAE','Margin MAE','Total MAE']):
        for i,(_,r) in enumerate(c.iterrows()):
            x=r[metric+'_mae_delta_vs_v18'];lo=r[metric+'_delta_lower95'];hi=r[metric+'_delta_upper95']
            color='#246494' if r.arm.endswith('blend') else '#c27827'
            ax.plot([lo,hi],[i,i],color=color,lw=2)
            ax.plot(x,i,'o' if r.arm.endswith('blend') else 's',color=color,ms=6)
        ax.axvline(0,color='#25303d',ls='--',lw=1)
        ax.set_title(title);ax.set_yticks(range(len(labels)),labels if metric=='team' else [])
        ax.invert_yaxis();ax.set_xlabel('Change versus V18 (runs)');ax.grid(axis='x',alpha=.15)
    fig.suptitle('Fixed six-game score blends: paired changes in error',fontsize=15,fontweight='bold')
    fig.supxlabel('Lower is better. 95% date-block intervals; same games within each comparison. H2H has complete six-meeting support in only 3/66 games.',fontsize=9)
    fig.savefig(output/'02_score_blend_comparison.png',dpi=170)
    plt.close(fig)
