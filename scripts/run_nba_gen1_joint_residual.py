"""Freeze, assess and reproduce one pooled paired-residual NBA research baseline."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from server.sports_nba_gen1.authority import reference, verified_bytes, json_bytes
from server.sports_nba_gen1.joint_residual import (
    ENGINE, BENCHMARK, DRAW_COUNT, MIN_DONORS, MASTER_SEED,
    eligible_bank, simulate_pair, joint_counts, totals_query, stage_summary)
from server.sports_nba_gen1.joint_residual_scoring import energy_score
from server.sports_nfl_m1.metrics import empirical_crps

DEFAULT = ROOT/'outputs/nba-gen1-joint-residual-v1'
MAIN_METRICS = ['energy', 'total_crps', 'margin_crps', 'log_loss', 'binary_brier',
                'total_mae', 'margin_mae']
INTERVALS = (.50, .80, .90)


def now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    raw = json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError(f'Refusing to replace evidence: {path}')
    path.write_bytes(raw)
    return reference(path)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def code_bindings():
    return [reference(p) for p in [Path(__file__),
            ROOT/'server/sports_nba_gen1/joint_residual.py',
            ROOT/'server/sports_nba_gen1/joint_residual_scoring.py',
            ROOT/'server/sports_nfl_m1/metrics.py']]


def freeze(root):
    path = root/'method-freeze.json'
    if path.exists():
        return json.loads(path.read_bytes())
    provenance = json.loads((root/'residual-provenance.json').read_bytes())
    verified_bytes(provenance['residuals'])
    rows = pd.read_parquet(root/'residuals.parquet').sort_values(['game_date', 'game_id'])
    dates = rows.game_date.to_numpy()
    earlier = np.searchsorted(dates, dates, side='left')
    eligible = rows[earlier >= MIN_DONORS]
    dev = rows[rows.season_end <= 2023]
    low, high = np.quantile(dev.actual_home_score+dev.actual_away_score, [.05, .95], method='inverted_cdf')
    demonstration = eligible[eligible.season_end == 2026].iloc[0]
    value = {'schema': 'NBA_GEN1_JOINT_RESIDUAL_METHOD_FREEZE_V1', 'frozenAtUtc': now(),
        'engine': ENGINE, 'benchmark': BENCHMARK, 'researchOnly': True, 'publicationAuthorized': False,
        'drawCountPerGamePerArm': DRAW_COUNT, 'masterSeed': MASTER_SEED,
        'seedPolicy': 'First 8 SHA256 bytes big-endian of ENGINE|MASTER_SEED|game_id|stream; NumPy PCG64. Independent fixed streams for donors, benchmark permutation and each arm support tie-breaking.',
        'residualBank': 'All eligible corrected Ridge OOF HOME/AWAY pairs with donor date strictly before target date, expanding daily; minimum 200. Center each bank column once using earlier donors. No scale, window, regime or outcome-driven selection.',
        'benchmarkDefinition': 'Same Ridge expectations and same sampled marginal residual values; seeded permutation of sampled AWAY vector removes pairing in expectation. Same support projection and 10000 draws. No fitted marginal correction.',
        'supportTreatment': 'Nearest nonnegative integer coordinate rounding floor(max(x,0)+0.5). For ties choose closest valid +/-1 single-coordinate neighbor to original latent pair, seeded uniform only among equal squared-distance minimizers. No overtime append, rejected draws, upper-tail cap or donor omission.',
        'developmentRationale': 'No negative latent draws in 33.38M Development samples. About 2.63% rounding ties need explicit final-score support. Minimum-distance repair is bounded, symmetric and requires no new fitted parameters. Development already identifies excessive one-point mass; this limitation is frozen and will be reported, not optimized away.',
        'primaryMetric': 'Exact empirical joint Euclidean energy V-statistic, N-squared denominator; lower is better.',
        'scoring': {'crps': 'Exact empirical marginal V-statistic', 'winner': 'Final HOME>AWAY fractions; no ties; log floor 1e-12; Brier=(pHome-actualHomeWin)^2',
                    'intervals': 'Central equal-tail 50/80/90%; inverted_cdf quantiles; inclusive endpoints; width upper-minus-lower',
                    'uncertainty': 'Paired ISO calendar-week block bootstrap, 2000 resamples, seed731201; observed games are units. Simulation MCSE is numerical precision only.'},
        'groups': ['overall', 'Development 2021-2023', 'reused 2024-2026', 'season', 'either team season opener', 'ordinary rest both supported / unavailable rest', 'actual low/high total by frozen Development 5/95 quantiles'],
        'tailThresholds': {'developmentGames': len(dev), 'lowTotalInclusive': int(low), 'highTotalInclusive': int(high),
                           'futureCalibrationQueries': 'Actual below forecast 1/5 percentiles and above95/99 percentiles, strictly outside discrete thresholds'},
        'cohort': {'availableOOFGames': len(rows), 'eligibleGames': len(eligible), 'unsupportedGames': int((earlier < MIN_DONORS).sum()),
                   'eligibleIdentitySha256': digest('\n'.join(eligible.game_id).encode()),
                   'seasons': {str(y): len(f) for y, f in eligible.groupby('season_end')},
                   'qualification': 'All seasons previously inspected; Category A finalized historical reconstruction, not untouched OOT or certified historical information availability. Same-date exclusion does not reconstruct unobserved publication/revision clocks.'},
        'demonstration': {'gameId': demonstration.game_id, 'selection': 'Earliest eligible 2025-26 game by date then canonical identity, chosen before proper-score assessment', 'illustrativeLines': [225, 225.5]},
        'populationRetention': 'Lossless sparse joint frequency table: game_index, HOME score, AWAY score, count. Sum counts=10000 for each game/arm. Full paired distribution and tails retained; original sample order reproducible from seeds and verified by ordered int64 draw SHA256. No marginal recombination used to reconstruct the paired arm.',
        'provenance': reference(root/'residual-provenance.json'), 'residuals': reference(root/'residuals.parquet'),
        'developmentSupport': reference(root/'development-support-audit.json'), 'code': code_bindings(),
        'decisionRule': 'One descriptive matched comparison. Report paired energy improvement/uncertainty plus marginal, interval and close-game limitations; no promotion, repeated tuning or fresh-holdout claim. A proper-score advantage alone does not certify exact push or close-margin probabilities.'}
    save(path, value)
    save(root/'cohort-games.json', {'eligible': eligible[['game_id','game_date','season_end']].to_dict('records'),
         'unsupported': rows[earlier < MIN_DONORS][['game_id','game_date','season_end']].assign(earlier_donors=earlier[earlier < MIN_DONORS]).to_dict('records')})
    return value


def score(draws, home, away):
    h, a = draws.T
    total, margin = h+a, h-a
    p = float((h > a).mean())
    y = int(home > away)
    out = {'draw_count': len(h), 'home_win_probability': p, 'away_win_probability': 1-p,
           'tie_probability': 0., 'log_loss': float(-np.log(max(p if y else 1-p, 1e-12))),
           'binary_brier': (p-y)**2, 'energy': energy_score(h, a, home, away),
           'correct_pick': None if p == .5 else int((p > .5) == bool(y)),
           'home_win_mcse': float(np.sqrt(p*(1-p)/len(h))),
           'one_point_probability': float((abs(margin) == 1).mean())}
    for name, sample, observed in [('home',h,home), ('away',a,away), ('total',total,home+away), ('margin',margin,home-away)]:
        out[name+'_mean'] = float(sample.mean())
        out[name+'_mean_mcse'] = float(sample.std(ddof=1)/np.sqrt(len(sample)))
        out[name+'_crps'] = float(empirical_crps(sample, observed))
        out[name+'_mae'] = abs(float(sample.mean())-observed)
        for level in INTERVALS:
            lower, upper = np.quantile(sample, [(1-level)/2, (1+level)/2], method='inverted_cdf')
            prefix = f'{name}_{int(level*100)}'
            out[prefix+'_lower'], out[prefix+'_upper'] = int(lower), int(upper)
            out[prefix+'_coverage'] = int(lower <= observed <= upper)
            out[prefix+'_width'] = int(upper-lower)
        for q in (.01, .05, .95, .99):
            quantile = float(np.quantile(sample,q,method='inverted_cdf'))
            out[f'{name}_q{q:g}'] = quantile
            out[f'{name}_outside{q:g}'] = int(observed < quantile if q < .5 else observed > quantile)
    return out


def run(root):
    declaration = json.loads((root/'method-freeze.json').read_bytes())
    repair_path = root/'execution-code-repair.json'
    bindings = declaration['code']
    if repair_path.exists():
        repair = json.loads(repair_path.read_bytes())
        verified_bytes(repair['originalMethod'])
        verified_bytes(repair['originalRunner'])
        bindings = [repair['repairedRunner'] if item['path'] == str(Path(__file__).resolve()) else item for item in bindings]
    for item in bindings + [declaration['residuals'], declaration['provenance'], declaration['developmentSupport']]:
        verified_bytes(item)
    rows = pd.read_parquet(root/'residuals.parquet').sort_values(['game_date','game_id']).reset_index(drop=True)
    cohort = json.loads((root/'cohort-games.json').read_bytes())
    eligible_ids = {r['game_id'] for r in cohort['eligible']}
    target = rows[rows.game_id.isin(eligible_ids)].copy()
    target['game_index'] = np.arange(len(target),dtype=np.int32)
    if digest('\n'.join(target.game_id).encode()) != declaration['cohort']['eligibleIdentitySha256']:
        raise AssertionError('Declared cohort changed')
    tail = declaration['tailThresholds']
    bank_cache, bank_records = {}, []
    for year, year_rows in target.groupby('season_end'):
        folder = root/'assessment'/str(year)
        receipt_path = folder/'receipt.json'
        if receipt_path.exists():
            for item in json.loads(receipt_path.read_bytes())['artifacts']:
                verified_bytes(item)
            continue
        folder.mkdir(parents=True,exist_ok=True)
        if not (folder/'execution-start.json').exists():
            save(folder/'execution-start.json', {'startedAtUtc': now(), 'method': reference(root/'method-freeze.json'), 'games': len(year_rows)})
        score_rows, support_rows, manifests = [], [], []
        buffers = {'paired': [], 'benchmark': []}
        writers = {}
        def flush(name):
            if not buffers[name]:
                return
            frame = pd.concat(buffers[name],ignore_index=True)
            table = pa.Table.from_pandas(frame,preserve_index=False)
            if name not in writers:
                writers[name] = pq.ParquetWriter(folder/(name+'-joint-counts.parquet'),table.schema,compression='zstd',compression_level=9)
            writers[name].write_table(table)
            buffers[name].clear()
        for position, (_, game) in enumerate(year_rows.iterrows()):
            if game.game_date not in bank_cache:
                bank = eligible_bank(rows, game.game_date, game.game_id)
                values = bank[['residual_home','residual_away']].to_numpy(float)
                bank_id = digest(('\n'.join(bank.game_id)).encode()+values.astype('<f8').tobytes())
                bank_cache[game.game_date] = (values, bank_id, str(bank.game_date.max()))
                bank_records.append({'target_date': game.game_date, 'bank_id': bank_id, 'donors': len(bank),
                    'latest_donor_date': str(bank.game_date.max()), 'home_center': float(values[:,0].mean()),
                    'away_center': float(values[:,1].mean()), 'residual_correlation': float(np.corrcoef(values.T)[0,1])})
            values, bank_id, latest = bank_cache[game.game_date]
            assert latest < game.game_date and game.training_last_date < game.game_date
            populations, offset = simulate_pair([game.expected_home_score,game.expected_away_score], values, game.game_id)
            meta = {'game_id': game.game_id, 'game_index': int(game.game_index), 'game_date': game.game_date, 'season_end': int(year),
                    'home_team_code': game.home_team_code, 'away_team_code': game.away_team_code,
                    'actual_home': int(game.actual_home_score), 'actual_away': int(game.actual_away_score),
                    'ridge_expected_home': float(game.expected_home_score), 'ridge_expected_away': float(game.expected_away_score),
                    'elo_home_win_probability': float(game.p_home_win_elo),
                    'both_ordinary_rest_supported': bool(game.both_ordinary_rest_supported),
                    'either_season_opener': bool(game.either_season_opener), 'early_season': bool(game.early_season),
                    'model_sha256': game.model_artifact_sha256, 'bank_id': bank_id, 'donors': len(values), 'latest_donor_date': latest}
            for name, population in populations.items():
                draws = population['draws']
                scored = score(draws,game.actual_home_score,game.actual_away_score)
                score_rows.append({**meta,'configuration':name,**scored,
                    'total_low_probability': float((draws.sum(axis=1) <= tail['lowTotalInclusive']).mean()),
                    'total_high_probability': float((draws.sum(axis=1) >= tail['highTotalInclusive']).mean())})
                stages = stage_summary(population['stages'],tail['lowTotalInclusive'],tail['highTotalInclusive'])
                flat = {f'{stage}__{k}': v for stage, vals in stages.items() if isinstance(vals,dict) for k,v in vals.items()}
                support_rows.append({'game_id':game.game_id,'configuration':name,**flat,
                    'winner_order_reversal_fraction':stages['winner_order_reversal_fraction']})
                pairs, counts = joint_counts(draws)
                # Lossless full joint population, not separate marginals or representative paths.
                if pairs.max() > np.iinfo(np.int32).max:
                    raise ValueError('Score exceeds storage integer range')
                weighted_mean = (pairs*counts[:,None]).sum(axis=0)/DRAW_COUNT
                assert np.array_equal(weighted_mean,draws.mean(axis=0)) and counts.sum() == DRAW_COUNT
                frame = pd.DataFrame({'game_index':np.full(len(pairs),game.game_index,dtype=np.int32),
                    'home_score':pairs[:,0].astype(np.int32),'away_score':pairs[:,1].astype(np.int32),'count':counts.astype(np.int32)})
                buffers[name].append(frame)
                manifests.append({**meta,'configuration':name,'draw_count':DRAW_COUNT,'joint_cells':len(pairs),
                    'ordered_draws_int64_le_sha256':digest(draws.astype('<i8').tobytes()),
                    'joint_counts_int64_le_sha256':digest(np.column_stack((pairs,counts)).astype('<i8').tobytes()),
                    'home_center':float(offset[0]),'away_center':float(offset[1])})
                if game.game_id == declaration['demonstration']['gameId'] and name == 'paired':
                    save(root/'totals-demonstration.json',{'schema':'NBA_GEN1_JOINT_TOTALS_RESEARCH_EXAMPLE_V1',
                        'createdAtUtc':now(),'evidence':'REUSED_HISTORICAL_ASSESSMENT_NOT_ORIGINAL_PREGAME_FORECAST',
                        'engine':ENGINE,**meta,'drawCount':DRAW_COUNT,
                        'jointDerivedHomeWinProbability':scored['home_win_probability'],
                        'eloHomeWinProbabilitySeparateOutput':float(game.p_home_win_elo),
                        'jointExpectedHome':scored['home_mean'],'jointExpectedAway':scored['away_mean'],
                        'central80TotalInterval':[scored['total_80_lower'],scored['total_80_upper']],
                        'queries':[totals_query(draws,line) for line in declaration['demonstration']['illustrativeLines']],
                        'integerTotalFrequency':[{'total':int(t),'count':int(c),'probability':float(c/DRAW_COUNT)} for t,c in zip(*np.unique(draws.sum(axis=1),return_counts=True))],
                        'settlement':'Full final scores including overtime; no additional OT appended.',
                        'priceSemantics':'No recorded market prices. Expected net return=pWin*(decimalOdds-1)-pLoss. Fair decimal odds=1+pLoss/pWin when pWin>0.'})
            if (position+1) % 100 == 0:
                for name in buffers:
                    flush(name)
            if (position+1) % 300 == 0:
                print(f'{year}: {position+1}/{len(year_rows)} games',flush=True)
        for name in buffers:
            flush(name)
            writers[name].close()
        pd.DataFrame(score_rows).to_parquet(folder/'scores.parquet',index=False,compression='zstd')
        pd.DataFrame(support_rows).to_parquet(folder/'support-effects.parquet',index=False,compression='zstd')
        pd.DataFrame(manifests).to_parquet(folder/'populations.parquet',index=False,compression='zstd')
        pd.DataFrame([r for r in bank_records if r['target_date'] in set(year_rows.game_date)]).to_parquet(folder/'donor-banks.parquet',index=False)
        save(receipt_path,{'schema':'NBA_GEN1_JOINT_RESIDUAL_SEASON_ASSESSMENT_V1','completedAtUtc':now(),
            'method':reference(root/'method-freeze.json'),'games':len(year_rows),'configurations':2,'drawsPerConfigurationPerGame':DRAW_COUNT,
            'artifacts':[reference(folder/n) for n in ['paired-joint-counts.parquet','benchmark-joint-counts.parquet','scores.parquet','support-effects.parquet','populations.parquet','donor-banks.parquet']],
            'checks':{'chronology':True,'fullCountReconciliation':True,'jointMeansReconcileExactly':True,'negativeOrTiedFinalDraws':0}})
        print(f'{year}: complete',flush=True)
    return {'assessmentComplete':True,'games':len(target)}


def paired_uncertainty(scores):
    a = scores[scores.configuration=='benchmark'].set_index('game_id').sort_index()
    b = scores[scores.configuration=='paired'].set_index('game_id').sort_index()
    if not a.index.equals(b.index) or not a.game_date.equals(b.game_date):
        raise AssertionError('Matched cohort required')
    metrics = MAIN_METRICS + [f'{v}_{int(q*100)}_coverage' for v in ('total','margin') for q in INTERVALS]
    diff = b[metrics].to_numpy()-a[metrics].to_numpy()
    labels = pd.to_datetime(a.game_date).dt.strftime('%G-%V')
    weeks,index = np.unique(labels,return_inverse=True)
    sums,counts = np.zeros((len(weeks),len(metrics))),np.zeros(len(weeks),int)
    np.add.at(sums,index,diff)
    np.add.at(counts,index,1)
    selected = np.random.default_rng(731201).integers(len(weeks),size=(2000,len(weeks)))
    sampled = sums[selected].sum(axis=1)/counts[selected].sum(axis=1)[:,None]
    return {'direction':'paired-minus-benchmark; negative improves proper scores/errors; coverage interpreted against nominal',
        'games':len(a),'calendarWeeks':len(weeks),'replicates':2000,'seed':731201,
        'metrics':{m:{'difference':float(diff[:,i].mean()),'interval95':np.quantile(sampled[:,i],[.025,.975]).tolist()} for i,m in enumerate(metrics)}}


def summarize(frame):
    metrics = MAIN_METRICS + ['home_crps','away_crps','home_mae','away_mae','one_point_probability','home_win_mcse']
    metrics += [f'{v}_{int(q*100)}_{suffix}' for v in ('home','away','total','margin') for q in INTERVALS for suffix in ('coverage','width')]
    metrics += [f'{v}_outside{q:g}' for v in ('home','away','total','margin') for q in (.01,.05,.95,.99)]
    return {'games':len(frame),**{m:float(frame[m].mean()) for m in metrics},
        'actual_one_point_frequency':float((abs(frame.actual_home-frame.actual_away)==1).mean()),
        'model_implied_low_total_frequency':float(frame.total_low_probability.mean()),
        'model_implied_high_total_frequency':float(frame.total_high_probability.mean())}


def report(root):
    declaration = json.loads((root/'method-freeze.json').read_bytes())
    receipts = sorted((root/'assessment').glob('*/receipt.json'))
    for receipt in receipts:
        for bound in json.loads(receipt.read_bytes())['artifacts']:
            verified_bytes(bound)
    scores = pd.concat([pd.read_parquet(p.parent/'scores.parquet') for p in receipts],ignore_index=True)
    effects = pd.concat([pd.read_parquet(p.parent/'support-effects.parquet') for p in receipts],ignore_index=True)
    if scores.game_id.nunique()!=declaration['cohort']['eligibleGames'] or len(scores)!=2*scores.game_id.nunique():
        raise AssertionError('Incomplete matched assessment')
    masks = {'all':np.ones(len(scores),bool),'development':scores.season_end<=2023,'reused_2024_2026':scores.season_end>=2024,
        'season_openers':scores.either_season_opener,'other_games':~scores.either_season_opener,
        'ordinary_rest':scores.both_ordinary_rest_supported,'unavailable_rest':~scores.both_ordinary_rest_supported,
        'low_total':scores.actual_home+scores.actual_away<=declaration['tailThresholds']['lowTotalInclusive'],
        'high_total':scores.actual_home+scores.actual_away>=declaration['tailThresholds']['highTotalInclusive']}
    masks.update({f'season_{y}':scores.season_end==y for y in sorted(scores.season_end.unique())})
    groups = {name:{arm:summarize(f) for arm,f in scores[mask].groupby('configuration')} for name,mask in masks.items()}
    paired = scores[scores.configuration=='paired'].copy()
    jointpick = np.sign(paired.home_win_probability-.5)
    elopick = np.sign(paired.elo_home_win_probability-.5)
    differences = paired.assign(joint_minus_elo_probability=paired.home_win_probability-paired.elo_home_win_probability,
                                picks_disagree=(jointpick != elopick)&(jointpick!=0)&(elopick!=0))
    differences.to_parquet(root/'joint-versus-elo.parquet',index=False,compression='zstd')
    transformations = {}
    for arm, f in effects.groupby('configuration'):
        vals = {'games':len(f),'average_by_stage':{stage:{c.split('__',1)[1]:float(f[c].mean()) for c in f.columns if c.startswith(stage+'__')} for stage in ('latent','floored','rounded','final')},
                'winner_order_reversal_fraction':float(f.winner_order_reversal_fraction.mean())}
        vals['final_minus_latent'] = {key:{'mean_game_change':float((f['final__'+key]-f['latent__'+key]).mean()),
                    'maximum_absolute_game_change':float((f['final__'+key]-f['latent__'+key]).abs().max())}
                    for key in vals['average_by_stage']['latent']}
        transformations[arm] = vals
    calibration = []
    bins = np.minimum((paired.home_win_probability*10).astype(int),9)
    for group, f in paired.groupby(bins):
        calibration.append({'probabilityBand':[int(group)/10,(int(group)+1)/10],'games':len(f),
                'predictedHomeWin':float(f.home_win_probability.mean()),'observedHomeWin':float((f.actual_home>f.actual_away).mean())})
    result = {'schema':'NBA_GEN1_JOINT_RESIDUAL_MATCHED_ASSESSMENT_V1','createdAtUtc':now(),
        'method':reference(root/'method-freeze.json'),'groups':groups,'pairedUncertainty':paired_uncertainty(scores),
        'pairedUncertaintyReused2024_2026':paired_uncertainty(scores[scores.season_end>=2024]),
        'supportTransformations':transformations,'homeWinReliability':calibration,
        'jointVersusSeparateElo':{'games':len(paired),'picksDisagree':int(differences.picks_disagree.sum()),
            'jointHasNoUniquePick':int((jointpick==0).sum()),'meanAbsoluteProbabilityDifference':float(differences.joint_minus_elo_probability.abs().mean()),
            'maximumAbsoluteProbabilityDifference':float(differences.joint_minus_elo_probability.abs().max()),
            'eloLogLoss':float((-np.log(np.where(paired.actual_home>paired.actual_away,paired.elo_home_win_probability,1-paired.elo_home_win_probability).clip(1e-12,1))).mean()),
            'eloBinaryBrier':float(((paired.elo_home_win_probability-(paired.actual_home>paired.actual_away).astype(int))**2).mean())},
        'actualTailFrequencies':{'low':float((paired.actual_home+paired.actual_away<=declaration['tailThresholds']['lowTotalInclusive']).mean()),
                                'high':float((paired.actual_home+paired.actual_away>=declaration['tailThresholds']['highTotalInclusive']).mean())},
        'scope':'One matched historical comparison; every season reused; no refitting, calibration, acquisition, prospective publication, consumer integration or promotion.'}
    save(root/'assessment.json',result)
    flat = [{'group':group,'configuration':arm,**v} for group,arms in groups.items() for arm,v in arms.items()]
    pd.DataFrame(flat).to_csv(root/'results-table.csv',index=False)
    return {k:result[k] for k in ('pairedUncertainty','jointVersusSeparateElo')}


def reproduce(root):
    declaration=json.loads((root/'method-freeze.json').read_bytes())
    rows=pd.read_parquet(root/'residuals.parquet').sort_values(['game_date','game_id'])
    checks=[]
    # One first game from each chronological season plus the declared totals example.
    for receipt in sorted((root/'assessment').glob('*/receipt.json')):
        meta=pd.read_parquet(receipt.parent/'populations.parquet')
        game_id=meta.iloc[0].game_id
        game=rows[rows.game_id==game_id].iloc[0]
        bank=eligible_bank(rows,game.game_date,game_id)
        generated,_=simulate_pair([game.expected_home_score,game.expected_away_score],bank[['residual_home','residual_away']].to_numpy(),game_id)
        for arm,pop in generated.items():
            bound=meta[(meta.game_id==game_id)&(meta.configuration==arm)].iloc[0]
            assert digest(pop['draws'].astype('<i8').tobytes())==bound.ordered_draws_int64_le_sha256
            pairs,counts=joint_counts(pop['draws'])
            assert digest(np.column_stack((pairs,counts)).astype('<i8').tobytes())==bound.joint_counts_int64_le_sha256
            retained=pd.read_parquet(receipt.parent/(arm+'-joint-counts.parquet'),filters=[('game_index','=',int(bound.game_index))])
            assert np.array_equal(retained[['home_score','away_score','count']].to_numpy(),np.column_stack((pairs,counts)))
            saved=pd.read_parquet(receipt.parent/'scores.parquet')
            saved=saved[(saved.game_id==game_id)&(saved.configuration==arm)].iloc[0]
            rescored=score(pop['draws'],game.actual_home_score,game.actual_away_score)
            for m in MAIN_METRICS:
                assert rescored[m]==saved[m]
            checks.append({'gameId':game_id,'configuration':arm,'orderedDrawsExact':True,'retainedCountsExact':True,'scoresExact':True})
    return save(root/'reproduction-verification.json',{'createdAtUtc':now(),'method':reference(root/'method-freeze.json'),'checks':checks,
        'fullPopulationAccounting':'Every game reconciled counts, paired means and score support during assessment; targeted replay checks one game per season for both arms.'})


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['freeze','run','report','verify'])
    parser.add_argument('--root',type=Path,default=DEFAULT)
    args=parser.parse_args()
    functions={'freeze':freeze,'run':run,'report':report,'verify':reproduce}
    print(json.dumps(functions[args.action](args.root),indent=2,allow_nan=False))
