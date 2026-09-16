"""Fixed whole-game assessment, reliability, uncertainty and selection gates."""
from __future__ import annotations

import numpy as np
import pandas as pd

SCORE_COLUMNS = ('energy', 'logLoss', 'binaryBrier', 'homeCRPS', 'awayCRPS', 'totalCRPS', 'marginCRPS',
                 'homeMAE', 'awayMAE', 'totalMAE', 'marginMAE')


def flatten_score(scored):
    row = {'energy': scored['jointEnergyScore'], 'logLoss': scored['winnerLogLoss'],
        'binaryBrier': scored['binaryBrier'], 'pHome': scored['homeWinProbability'],
        'yHome': scored['actualHomeWin']}
    for name, marginal in scored['marginals'].items():
        row[name+'CRPS'] = marginal['crps']
        row[name+'MAE'] = marginal['absoluteError']
        for level, interval in marginal['centralPredictionIntervals'].items():
            row[name+'Coverage'+level] = float(interval['covered'])
            row[name+'Width'+level] = interval['width']
        row[name+'Below01'] = float(marginal['observed'] < marginal['quantiles']['0.01'])
        row[name+'Above99'] = float(marginal['observed'] > marginal['quantiles']['0.99'])
    return row


def reliability(frame):
    rows = []
    for i in range(10):
        mask = (frame.pHome >= i/10) & ((frame.pHome < (i+1)/10) if i < 9 else (frame.pHome <= 1))
        selected = frame[mask]
        rows.append({'lowerInclusive': i/10, 'upper': (i+1)/10, 'upperInclusive': i == 9,
            'games': len(selected), 'meanPredicted': float(selected.pHome.mean()) if len(selected) else None,
            'observedHomeWinRate': float(selected.yHome.mean()) if len(selected) else None})
    return rows


def summary(frame):
    if not len(frame):
        return {'games': 0, 'metrics': None, 'reliability': []}
    numeric = [k for k in frame if k in SCORE_COLUMNS or 'Coverage' in k or 'Width' in k or 'Below01' in k or 'Above99' in k]
    return {'games': len(frame), 'metrics': {k: float(frame[k].mean()) for k in numeric}, 'reliability': reliability(frame)}


def paired_interval(base, challenger, metric, seed=20260913, repeats=1000):
    if list(base.game_id) != list(challenger.game_id):
        raise ValueError('Same game identities and order required for paired assessment')
    differences = challenger[metric].to_numpy(float) - base[metric].to_numpy(float)
    # Calendar-week clusters retain all observed games, never treat simulation draws as observations.
    dates = pd.to_datetime(base.scheduled_tipoff_utc, utc=True)
    block_ids = dates.dt.strftime('%G-%V').to_numpy()
    groups = [np.flatnonzero(block_ids == b) for b in sorted(set(block_ids))]
    result = {'meanDifference': float(differences.mean()), 'games': len(differences), 'calendarWeekBlocks': len(groups),
        'resamples': repeats, 'unit': 'calendar-week blocks of paired observed games'}
    if len(groups) < 8:
        return {**result, 'lower95': None, 'upper95': None, 'status': 'INSUFFICIENT_OBSERVED_BLOCKS'}
    rng = np.random.default_rng(seed)
    sums = np.array([differences[g].sum() for g in groups])
    counts = np.array([len(g) for g in groups])
    selected = rng.integers(0, len(groups), size=(repeats, len(groups)))
    means = sums[selected].sum(axis=1)/counts[selected].sum(axis=1)
    low, high = np.quantile(means, [.025, .975])
    return {**result, 'lower95': float(low), 'upper95': float(high), 'status': 'PAIRED_BLOCK_INTERVAL'}


def add_groups(ledger, feature_rows, pace_cutpoints):
    f = feature_rows.set_index('game_id').loc[ledger.game_id]
    out = ledger.copy()
    support = np.minimum(f.home_season_games_played, f.away_season_games_played).to_numpy()
    out['supportBand'] = np.where(support < 10, 'EARLY_LT10', np.where(support < 30, '10_TO29', '30_PLUS'))
    out['backToBack'] = np.where((f.home_back_to_back + f.away_back_to_back).to_numpy() > 0, 'EITHER_TEAM', 'NEITHER')
    rest = np.minimum(f.home_rest_days, f.away_rest_days).to_numpy()
    out['restBand'] = np.where(~np.isfinite(rest), 'UNKNOWN', np.where(rest == 0, 'ZERO_REST_DAYS', np.where(rest <= 1, 'ONE_REST_DAY', 'TWO_PLUS')))
    pace = ((f.home_pace + f.away_pace)/2).to_numpy()
    out['paceBand'] = np.where(pace < pace_cutpoints[0], 'SLOW', np.where(pace <= pace_cutpoints[1], 'MIDDLE', 'FAST'))
    density = np.maximum(f.home_games_last_7_days, f.away_games_last_7_days).to_numpy()
    out['densityBand'] = np.where(density >= 4, 'FOUR_PLUS_PRIOR_7D', 'FEWER_THAN_FOUR')
    return out


def grouped_report(frame):
    return {'overall': summary(frame), 'by': {key: {str(value): summary(group) for value, group in frame.groupby(key, sort=True)}
        for key in ('season', 'supportBand', 'backToBack', 'restBand', 'paceBand', 'densityBand')},
        'subgroupsExploratory': True, 'causality': 'Feature association and localized forecast errors are not causal effects or specialist authorization.'}


def advancement_gate(base, candidate, declaration):
    gate = declaration['gate']
    a, b = summary(base)['metrics'], summary(candidate)['metrics']
    interval = paired_interval(base, candidate, 'energy')
    checks = {'energyEffect': b['energy'] <= a['energy']*(1-gate['minimumRelativeEnergyImprovement']),
        'pairedEnergy': interval['upper95'] is not None and interval['upper95'] < 0,
        'logLoss': b['logLoss'] <= a['logLoss']+gate['maximumLogLossDeterioration'],
        'brier': b['binaryBrier'] <= a['binaryBrier']+gate['maximumBrierDeterioration']}
    for name in ('home', 'away', 'total', 'margin'):
        checks[name+'Crps'] = b[name+'CRPS'] <= a[name+'CRPS']*(1+gate['maximumMarginalCrpsRelativeDeterioration'])
        for level in ('0.5', '0.8', '0.9'):
            checks[name+'Coverage'+level] = abs(b[name+'Coverage'+level]-float(level)) <= abs(a[name+'Coverage'+level]-float(level))+gate['maximumAbsoluteCoverageDeterioration']
            width = a[name+'Width'+level]
            ratio = b[name+'Width'+level]/width if width else 0.
            checks[name+'Width'+level] = gate['minimumWidthRatio'] <= ratio <= gate['maximumWidthRatio']
    mid = len(base)//2
    checks['firstHalf'] = float(candidate.energy.iloc[:mid].mean()) <= float(base.energy.iloc[:mid].mean())
    checks['secondHalf'] = float(candidate.energy.iloc[mid:].mean()) <= float(base.energy.iloc[mid:].mean())
    return {'advance': all(checks.values()), 'checks': checks, 'energyInterval': interval,
        'metricDifferences': {k: b[k]-a[k] for k in SCORE_COLUMNS},
        'pairedIntervals': {k: paired_interval(base, candidate, k) for k in SCORE_COLUMNS if k != 'energy'}}
