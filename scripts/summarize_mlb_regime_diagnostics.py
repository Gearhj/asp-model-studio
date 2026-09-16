"""Immutable post-fit diagnostics of the completed, safe Development study.

No model, gate, cluster, temperature or policy is fitted or selected here.
The existing metrics helper's calibration regressions describe supplied
probabilities only and never become a forecast artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '4'

import joblib
import numpy as np
import pandas as pd
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from server.sports_current_statcast.mlb_regime_baseline import sha_file
from server.sports_current_statcast.mlb_regime_metrics import predictive_metrics, paired_uncertainty, metric_contributions
from server.sports_current_statcast.mlb_regime_models import temperature_transform
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER

OUTPUT = ROOT / 'outputs/mlb-regime-hybrid-ensemble-v1'
RUN = OUTPUT / 'runs/mlb-regime-hybrid-20260910-v1'
RESULT_SHA = '740632fd33bef4c729633b16ef1a17637f6c08bca3435c7a1dabefa9832e699b'
BASELINE_SHA = '0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9'
DOMAINS = ('BATTER', 'PITCHER', 'TEAM_REST_TRAVEL', 'MATCHUP_CONTEXT')
MODELS = ('RESIDUAL_SPECIALISTS', 'SOFT_MIXTURE_OF_EXPERTS', 'RF_RESIDUAL_ENSEMBLE')
COLD_FLAGS = {'batter_no_prior': 'batter_prior_missing', 'pitcher_no_prior': 'pitcher_prior_missing',
              'batter_low_rolling_history': 'batter_last100_insufficient',
              'pitcher_low_rolling_history': 'pitcher_last250_insufficient'}


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def verified(path, digest, size=None):
    path = Path(path)
    # No arbitrary/raw input paths: all inputs belong to the already safe study.
    if not path.resolve().is_relative_to(OUTPUT.resolve()):
        raise ValueError('Input is outside the safe study output directory')
    if sha_file(path) != digest or (size is not None and path.stat().st_size != size):
        raise ValueError(f'Immutable input checksum/size mismatch: {path}')
    return path


def reference(path):
    return {'path': str(path.resolve()), 'sha256': sha_file(path), 'byteCount': path.stat().st_size}


def emit(event, **payload):
    print(json.dumps(clean({'event': event, **payload}), sort_keys=True), flush=True)


def weighted_residual_uncertainty(frame, residual, weights):
    """Descriptive fixed-membership weighted mean, with game and week resampling."""
    use = weights > 0
    if not use.any():
        return {'status': 'NO_SUPPORTED_OBSERVATIONS'}
    sample = frame.loc[use, ['canonicalGameId', 'game_date']].copy()
    sample['w'] = weights[use]
    sample['wr'] = weights[use] * residual[use]
    estimate = float(sample.wr.sum() / sample.w.sum())
    rng_game, rng_week = [np.random.default_rng(s) for s in np.random.SeedSequence(20260910).spawn(2)]

    def resample(stats, rng, week=False):
        groups = len(stats)
        if groups < 2:
            return {'status': 'INSUFFICIENT_GROUPS', 'groups': groups}
        draws = []
        for start in range(0, 1000, 32):
            count = min(32, 1000 - start)
            if week:
                starts = rng.integers(0, groups - 4 + 1, size=(count, int(np.ceil(groups / 4))))
                index = (starts[:, :, None] + np.arange(4)).reshape(count, -1)[:, :groups]
            else:
                index = rng.integers(0, groups, size=(count, groups))
            sums = stats[index].sum(axis=1)
            draws.extend((sums[sums[:, 0] > 0, 1] / sums[sums[:, 0] > 0, 0]).tolist())
        return {'status': 'AVAILABLE', 'estimate': estimate, 'lower': float(np.quantile(draws, .025)),
                'upper': float(np.quantile(draws, .975)), 'confidenceLevel': .95,
                'intervalType': 'PERCENTILE', 'replicates': len(draws), 'groups': groups}

    game = sample.groupby('canonicalGameId', sort=False)[['w', 'wr']].sum().to_numpy()
    dates = pd.to_datetime(sample.game_date)
    weeks = dates - pd.to_timedelta(dates.dt.dayofweek, unit='D')
    codes = ((weeks - weeks.min()).dt.days // 7).to_numpy()
    n_weeks = int(codes.max()) + 1
    observed_weeks = int(np.unique(codes).size)
    week_stats = np.column_stack([np.bincount(codes, weights=sample.w, minlength=n_weeks),
                                  np.bincount(codes, weights=sample.wr, minlength=n_weeks)])
    week_ci = (resample(week_stats, rng_week, week=True) if n_weeks >= 8 and observed_weeks >= 8
               else {'status': 'INSUFFICIENT_TEMPORAL_BLOCKS'})
    week_ci.update({'method': 'NONCIRCULAR_FOUR_CALENDAR_WEEK_MOVING_BLOCK', 'calendarWeeks': n_weeks,
                    'observedWeeks': observed_weeks, 'minimumWeeks': 8, 'emptyWeeksRetained': True,
                    'limitedBlockWarning': 'FEWER_THAN_FIVE_NONOVERLAPPING_FULL_BLOCKS' if n_weeks // 4 < 5 else None})
    return {'status': 'DESCRIPTIVE_FIXED_MEMBERSHIP', 'direction': 'OBSERVED_MINUS_RAW_V18_PREDICTED',
            'estimate': estimate, 'gameClusterBootstrap': resample(game, rng_game),
            'calendarWeekBlockBootstrap': week_ci,
            'limitation': 'No cluster/selection/model uncertainty is refitted; intervals are not simultaneous or confirmatory.'}


def summarize_support(frame, domain, component):
    membership = frame[f'{domain}_membership_{component}'].to_numpy()
    support = frame[f'{domain}_support'].to_numpy()
    weights = membership * support
    hard = frame[f'{domain}_label'].eq(component).to_numpy() & (support > 0)
    return hard, weights, {'observations': len(frame), 'hardInsidePAs': int(hard.sum()),
            'hardInsideGames': int(frame.loc[hard, 'canonicalGameId'].nunique()),
            'positiveWeightPAs': int((weights > 0).sum()),
            'positiveWeightGames': int(frame.loc[weights > 0, 'canonicalGameId'].nunique()),
            'weightAtLeastPointOnePAs': int((weights >= .1).sum()),
            'weightAtLeastPointOneGames': int(frame.loc[weights >= .1, 'canonicalGameId'].nunique()),
            'effectivePAs': float(weights.sum() ** 2 / max(np.square(weights).sum(), 1e-30)),
            'weightSum': float(weights.sum()), 'hardInsideMeanSupport': float(support[hard].mean()) if hard.any() else None,
            'zeroDomainSupportPAs': int((support <= 0).sum())}


def all_cluster_profiles(atlas, base_raw, residual_raw, base_calibrated, residual_calibrated, ensemble_calibrated):
    y = atlas.observedClassIndex.to_numpy(dtype=int)
    contributions = {name: metric_contributions(y, p) for name, p in
                     [('V18', base_calibrated), ('RESIDUAL_SPECIALISTS', residual_calibrated),
                      ('RF_RESIDUAL_ENSEMBLE', ensemble_calibrated)]}
    raw_change = np.max(np.abs(residual_raw - base_raw), axis=1)
    profiles = []
    for domain in DOMAINS:
        components = sorted(int(c.rsplit('_', 1)[1]) for c in atlas.columns if c.startswith(domain + '_membership_'))
        for component in components:
            take, _, support = summarize_support(atlas, domain, component)
            profiles.append({'clusterId': f'{domain}_{component}', 'domain': domain, **support,
                'globalLogLoss': float(contributions['V18']['logLoss'][take].mean()) if take.any() else None,
                'specialistLogLoss': float(contributions['RESIDUAL_SPECIALISTS']['logLoss'][take].mean()) if take.any() else None,
                'selectedEnsembleLogLoss': float(contributions['RF_RESIDUAL_ENSEMBLE']['logLoss'][take].mean()) if take.any() else None,
                'globalBrier': float(contributions['V18']['brier'][take].mean()) if take.any() else None,
                'specialistBrier': float(contributions['RESIDUAL_SPECIALISTS']['brier'][take].mean()) if take.any() else None,
                'selectedEnsembleBrier': float(contributions['RF_RESIDUAL_ENSEMBLE']['brier'][take].mean()) if take.any() else None,
                'meanAdjustment': float(raw_change[take].mean()) if take.any() else None,
                'maximumAdjustment': float(raw_change[take].max()) if take.any() else None,
                'influencedObservations': int((raw_change[take] > 1e-12).sum()),
                'comparisonModel': 'RESIDUAL_SPECIALISTS',
                'scoreMode': 'SAVED_FOLD4_CALIBRATED',
                'adjustmentDefinition': 'Per-PA maximum absolute class probability change of RAW residual system versus RAW V18; mean/max over hard supported regime.'})
    return profiles


def extend_existing(digest):
    """Add eight requested profile rows without rerunning the diagnostic regressions/CIs."""
    old_path = verified(OUTPUT / 'diagnostics/sha256' / digest / 'postfit-diagnostics.json', digest)
    payload = json.loads(old_path.read_text())
    refs = {Path(r['path']).name: r for r in payload['evidence']}

    def load_path(name):
        row = refs[name]
        return verified(row['path'], row['sha256'], row['byteCount'])

    atlas = pd.read_parquet(load_path('error-atlas-fold-5.parquet'))
    frame = pd.read_parquet(load_path('validation-fold-5-treated.parquet'))
    frame = frame.set_index('canonicalPaId', verify_integrity=True).loc[atlas.canonicalPaId].reset_index()
    if not np.array_equal(frame.canonicalGameId, atlas.canonicalGameId) or not np.array_equal(frame.observedClassIndex, atlas.observedClassIndex):
        raise ValueError('Exact profile PA/game/target mismatch')
    system = joblib.load(load_path('fitted-research-system.joblib'))
    p = atlas[['v18_' + c for c in PA_CLASS_ORDER]].to_numpy()
    residual_raw = system['specialists'].predict(system['clusters'].transform(frame), p)
    residual_calibrated = atlas[['RESIDUAL_SPECIALISTS_' + c for c in PA_CLASS_ORDER]].to_numpy()
    if not np.array_equal(temperature_transform(residual_raw, system['temperatures']['RESIDUAL_SPECIALISTS']), residual_calibrated):
        raise ValueError('Frozen residual profile reconstruction is not bitwise exact')
    payload['allEightResidualProfiles'] = all_cluster_profiles(atlas, p, residual_raw,
        temperature_transform(p, system['temperatures']['V18']), residual_calibrated,
        atlas[['RF_RESIDUAL_ENSEMBLE_' + c for c in PA_CLASS_ORDER]].to_numpy())
    payload['profileExtensionPredecessor'] = reference(old_path)
    payload['implementation'] = reference(Path(__file__))
    raw = canonical_json_bytes(clean(payload))
    new_digest = hashlib.sha256(raw).hexdigest()
    directory = OUTPUT / 'diagnostics/sha256' / new_digest
    directory.mkdir(parents=True, exist_ok=True)
    content = (old_path.parent / 'README.md').read_text().replace(digest, new_digest)
    content += '\nAll eight residual-system profiles now distinguish actual specialist log loss from selected ensemble log loss and report raw residual-system mean/max adjustment. The predecessor is preserved; no diagnostic regressions or bootstrap campaign was repeated.\n'
    for name, data in {'postfit-diagnostics.json': raw, 'README.md': content.encode('utf-8')}.items():
        path = directory / name
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError('Immutable profile extension conflict')
        else:
            with path.open('xb') as handle:
                handle.write(data)
    emit('POSTFIT_PROFILE_EXTENSION_PUBLISHED', artifacts=[reference(directory / name) for name in ('postfit-diagnostics.json', 'README.md')])


def add_integration_aliases(digest):
    """Pure JSON successor: expose existing values under final publisher keys."""
    old_path = verified(OUTPUT / 'diagnostics/sha256' / digest / 'postfit-diagnostics.json', digest)
    payload = json.loads(old_path.read_text())
    payload['clusterProfileCorrections'] = {row['clusterId']: {key: row[key] for key in
        ('specialistLogLoss', 'meanAdjustment', 'maximumAdjustment')} for row in payload['allEightResidualProfiles']}
    payload['ensembleComposition'] = payload['ensembleContribution']
    payload['integrationAliasPredecessor'] = reference(old_path)
    payload['implementation'] = reference(Path(__file__))
    if len(payload['clusterProfileCorrections']) != 8:
        raise ValueError('Final publisher requires all eight frozen cluster profiles')
    raw = canonical_json_bytes(clean(payload))
    new_digest = hashlib.sha256(raw).hexdigest()
    directory = OUTPUT / 'diagnostics/sha256' / new_digest
    directory.mkdir(parents=True, exist_ok=True)
    readme = (old_path.parent / 'README.md').read_text().replace(digest, new_digest)
    readme += '\nIntegration aliases expose the same computed values as clusterProfileCorrections and ensembleComposition. This immutable successor reads only its predecessor JSON; no statistical calculation is repeated.\n'
    for name, content in {'postfit-diagnostics.json': raw, 'README.md': readme.encode('utf-8')}.items():
        path = directory / name
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError('Immutable integration alias conflict')
        else:
            with path.open('xb') as handle:
                handle.write(content)
    emit('POSTFIT_INTEGRATION_ALIASES_PUBLISHED', artifacts=[reference(directory / name) for name in ('postfit-diagnostics.json', 'README.md')])


def main():
    result_path = verified(RUN / 'study-result.json', RESULT_SHA)
    result = json.loads(result_path.read_text())
    if result['status'] != 'COMPLETED' or result['selectedArchitecture'] != 'RF_RESIDUAL_ENSEMBLE':
        raise ValueError('Unexpected completed study selection')
    refs = {Path(row['path']).name: row for row in result['artifacts']}
    evidence = [reference(result_path)]

    def run_file(name):
        ref = refs[name]
        path = verified(ref['path'], ref['sha256'], ref['byteCount'])
        evidence.append(reference(path))
        return path

    baseline_path = verified(OUTPUT / f'baseline-cache/baseline-reproduction-{BASELINE_SHA}.json', BASELINE_SHA)
    baseline = json.loads(baseline_path.read_text())
    evidence.append(reference(baseline_path))
    if baseline['finalOotPayloadBytesRead'] or any(row['rawPredictionBitwiseMismatchCount'] for row in baseline['folds']):
        raise ValueError('Safe baseline parity gate not passed')

    def cache(key, columns=None):
        ref = baseline['artifacts'][key]
        path = verified(ref['path'], ref['sha256'], ref['bytes'])
        evidence.append(reference(path))
        return pd.read_parquet(path, columns=columns)

    atlases = [pd.read_parquet(run_file(f'error-atlas-fold-{fold}.parquet')) for fold in range(1, 6)]
    all_ids = pd.concat([a[['canonicalPaId', 'canonicalGameId', 'game_date', 'foldNumber']] for a in atlases])
    if all_ids.canonicalPaId.duplicated().any() or all_ids.game_date.astype(str).max() > '2026-08-06':
        raise ValueError('Safe Development atlas identity/date restriction failed')
    system = joblib.load(run_file('fitted-research-system.joblib'))
    if list(system['targetOrder']) != list(PA_CLASS_ORDER):
        raise ValueError('Class order mismatch')
    registry = json.loads(run_file('failure-regime-registry.json').read_text())['selected']
    cluster_spec = json.loads(run_file('cluster-specification.json').read_text())
    final = atlases[-1]
    frame = cache('validationFold5').set_index('canonicalPaId', verify_integrity=True).loc[final.canonicalPaId].reset_index()
    if not np.array_equal(frame.observedClassIndex, final.observedClassIndex) or not np.array_equal(frame.canonicalGameId, final.canonicalGameId):
        raise ValueError('Exact PA/game/target reconstruction mismatch')
    oof = cache('matchedOof', ['canonicalPaId', 'canonicalGameId', 'observedClassIndex'] +
                ['rf_probability_' + c for c in PA_CLASS_ORDER])
    oof = oof.set_index('canonicalPaId', verify_integrity=True).loc[final.canonicalPaId]
    if not np.array_equal(oof.canonicalGameId, final.canonicalGameId) or not np.array_equal(oof.observedClassIndex, final.observedClassIndex):
        raise ValueError('RF exact PA/game/target mismatch')
    y = final.observedClassIndex.to_numpy(dtype=int)
    p = final[['v18_' + c for c in PA_CLASS_ORDER]].to_numpy()
    rf = oof[['rf_probability_' + c for c in PA_CLASS_ORDER]].to_numpy()
    domains = system['clusters'].transform(frame)
    domain_checks = {}
    for domain, values in domains.items():
        original = final[[f'{domain}_membership_{k}' for k in range(values['membership'].shape[1])]].to_numpy()
        if not np.array_equal(original, values['membership']) or not np.array_equal(final[domain + '_support'], values['support']):
            raise ValueError('Saved cluster assignments did not reproduce exactly')
        domain_checks[domain] = {'membershipBitwiseEqual': True, 'supportBitwiseEqual': True}
    z = system['basis'].transform(domains, frame)
    experts = system['specialists']
    expert_support = experts.weights(domains)
    branches = experts.branches(p)
    raw = {'RESIDUAL_SPECIALISTS': experts.predict(domains, p),
           'SOFT_MIXTURE_OF_EXPERTS': system['gate'].predict(z, expert_support, branches, p)}
    raw['RF_RESIDUAL_ENSEMBLE'] = system['ensemble'].predict(np.stack([p, rf, raw['RESIDUAL_SPECIALISTS']], axis=1))
    predictions = {'V18': temperature_transform(p, system['temperatures']['V18'])}
    reproduction = {}
    for name in MODELS:
        predictions[name] = temperature_transform(raw[name], system['temperatures'][name])
        saved = final[[name + '_' + c for c in PA_CLASS_ORDER]].to_numpy()
        maximum = float(np.max(np.abs(saved - predictions[name])))
        reproduction[name] = {'bitwiseEqual': bool(np.array_equal(saved, predictions[name])), 'maximumAbsoluteDifference': maximum}
        if maximum > 1e-12:
            raise ValueError('Post-fit branch reconstruction disagrees with saved atlas')
    emit('FROZEN_ARTIFACT_RECONSTRUCTION_VERIFIED', branches=reproduction)
    logits = np.column_stack([np.ones(len(z)), z]) @ system['gate'].coefficients
    logits += np.where(expert_support > 0, np.log(np.maximum(expert_support, 1e-30)), -np.inf)
    gate_weights = softmax(np.column_stack([np.zeros(len(z)), logits]), axis=1)[:, 1:] * .25
    specialist_weights = expert_support / np.maximum(1., expert_support.sum(axis=1, keepdims=True)) * .5
    metric_cache = {}

    def metrics(mask, name):
        key = (hashlib.sha256(np.packbits(mask).tobytes()).hexdigest(), name)
        if key not in metric_cache:
            metric_cache[key] = predictive_metrics(y[mask], predictions[name][mask]) if mask.any() else None
        return metric_cache[key]

    def comparison(mask, name):
        base, candidate = metrics(mask, 'V18'), metrics(mask, name)
        return {'observations': int(mask.sum()), 'games': int(final.loc[mask, 'canonicalGameId'].nunique()),
                'baselineModel': 'V18', 'comparisonModel': name, 'outputMode': 'SAVED_FOLD4_CALIBRATED',
                'baseline': base, 'candidate': candidate,
                'deltaLogLoss': candidate['logLoss'] - base['logLoss'] if base else None,
                'deltaBrier': candidate['brier'] - base['brier'] if base else None}

    support_rows, residual_rows = [], []
    for fold, atlas in enumerate(atlases, 1):
        for domain in DOMAINS:
            width = domains[domain]['membership'].shape[1]
            for component in range(width):
                _, weights, support = summarize_support(atlas, domain, component)
                support_rows.append({'fold': fold, 'clusterId': f'{domain}_{component}', **support})
        for rule in registry:
            hard, weights, support = summarize_support(atlas, rule['domain'], rule['component'])
            label = PA_CLASS_ORDER[rule['classIndex']]
            residual = atlas['calibrationResidual_' + label].to_numpy()
            residual_rows.append({'fold': fold, 'clusterId': rule['clusterId'], 'className': label,
                'startDate': str(atlas.game_date.min()), 'endDate': str(atlas.game_date.max()),
                'evidenceRole': {1: 'DISCOVERY', 2: 'DISCOVERY', 3: 'CORRECTION_FIT', 4: 'GATE_CALIBRATION_SELECTION', 5: 'LATER_DEVELOPMENT_EVALUATION'}[fold],
                'hardInsideObservedMinusPredicted': float(residual[hard].mean()) if hard.any() else None,
                'hardInsideObservedRate': float(atlas.loc[hard, 'observedClassIndex'].eq(rule['classIndex']).mean()) if hard.any() else None,
                'hardInsidePredictedRate': float(atlas.loc[hard, 'v18_' + label].mean()) if hard.any() else None,
                'support': support, 'softMembershipWeightedBias': weighted_residual_uncertainty(atlas, residual, weights)})
        emit('FOLD_RESIDUAL_DIAGNOSTICS_COMPLETED', fold=fold)
    specialist_rows = []
    for expert_index, rule in enumerate(registry):
        if experts.experts[expert_index]['clusterId'] != rule['clusterId']:
            raise ValueError('Frozen expert and discovery registry order differ')
        inside, _, support = summarize_support(final, rule['domain'], rule['component'])
        scopes = []
        for scope, take in [('INSIDE', inside), ('OUTSIDE', ~inside)]:
            scopes.append({'scope': scope, 'models': [comparison(take, name) for name in MODELS[:2]],
                'meanFrozenExpertResidualSystemWeight': float(specialist_weights[take, expert_index].mean()) if take.any() else None,
                'meanFrozenExpertSoftGateWeight': float(gate_weights[take, expert_index].mean()) if take.any() else None})
        specialist_rows.append({'clusterId': rule['clusterId'], 'chosenFailureClass': PA_CLASS_ORDER[rule['classIndex']],
            'support': support, 'frozenExpert': clean(experts.experts[expert_index]), 'scopes': scopes,
            'interpretation': 'Two complete frozen specialist architectures evaluated inside/outside this qualified regime; not the selected RF ensemble and not an individual-expert ablation.'})
        emit('QUALIFIED_SPECIALIST_DIAGNOSTICS_COMPLETED', clusterId=rule['clusterId'])
    subgroup_rows = []
    subgroups = []
    for domain in DOMAINS:
        for component in range(domains[domain]['membership'].shape[1]):
            take, _, support = summarize_support(final, domain, component)
            subgroups.append((f'{domain}_{component}', 'TRAINING_DEFINED_REGIME', take, support))
    for name, field in COLD_FLAGS.items():
        subgroups.append((name, 'PREFIT_COLD_START_FLAG', final[field].eq(1).to_numpy(), {'field': field, 'requiredValue': 1}))
    for name, kind, take, support in subgroups:
        row = {'subgroup': name, 'kind': kind, 'support': support, **comparison(take, 'RF_RESIDUAL_ENSEMBLE')}
        if take.any():
            ci = paired_uncertainty(final.loc[take, ['canonicalGameId', 'game_date']], y[take], predictions['V18'][take],
                predictions['RF_RESIDUAL_ENSEMBLE'][take], seed=20260910, replicates=1000)
            ci.pop('repeatedIdentitySensitivity', None)
            ci['scope'] = 'GAME_AND_TEMPORAL_SENSITIVITIES_ONLY_NO_JOINT_PLAYER_TEAM_DEPENDENCE_GUARANTEE'
            row['pairedUncertainty'] = ci
        else:
            row['pairedUncertainty'] = {'status': 'EMPTY_SUBGROUP'}
        subgroup_rows.append(row)
        emit('SELECTED_ENSEMBLE_SUBGROUP_COMPLETED', subgroup=name, observations=int(take.sum()))
    weights = system['ensemble'].weights
    additive = {'RF': weights[1] * (rf - p), 'QUALIFIED_RESIDUAL_SYSTEM': weights[2] * (raw['RESIDUAL_SPECIALISTS'] - p)}
    pre_cap = p + sum(additive.values())
    ensemble_details = {'branchOrder': ['V18', 'RF', 'QUALIFIED_RESIDUAL_SYSTEM'], 'savedWeights': weights,
        'fitReceipt': system['ensemble'].fit_receipt, 'savedTemperatures': system['temperatures'],
        'perBranchPreCapDescriptiveMovement': {name: {'meanAbsoluteClassMovement': np.abs(delta).mean(axis=0),
            'meanSignedClassMovement': delta.mean(axis=0), 'meanRowMaximumAbsoluteMovement': float(np.abs(delta).max(axis=1).mean())}
            for name, delta in additive.items()},
        'capOrSimplexModifiedPAs': int((np.max(np.abs(pre_cap - raw['RF_RESIDUAL_ENSEMBLE']), axis=1) > 1e-12).sum()),
        'interpretation': 'Saved weights are convex mixture coefficients before the existing cap/simplex and saved temperature. They are not causal or additive performance attribution. No ablation, reconfiguration, weight optimization or reselection was performed. A nonzero residual weight does not establish that standalone specialists improve prediction.'}
    payload = {'schemaVersion': 'MLB_REGIME_POSTFIT_DIAGNOSTICS_V1', 'predecessor': reference(result_path),
        'status': 'COMPLETED_EXPLORATORY_DEVELOPMENT_DIAGNOSTICS', 'selectedArchitectureUnchanged': system['selected'],
        'classOrder': list(PA_CLASS_ORDER), 'cohort': result['cohort'], 'evidence': evidence,
        'definitions': {'inside': 'Frozen hard cluster label equals component AND domain support > 0; outside is its exact complement.',
            'softResidualWeight': 'Frozen membership probability times frozen domain support; effective N = sum(w)^2 / sum(w^2).',
            'residualDirection': 'Observed class indicator minus RAW rolling V18 probability; positive means underprediction.',
            'metricDeltaDirection': 'Candidate minus matched calibrated V18; negative log loss/Brier is lower error.',
            'calibration': 'predictive_metrics diagnostic-only regressions and reliability bins; no forecast calibration fitted.',
            'intervals': 'Exploratory 95% percentile intervals; not simultaneous or new formal selection/promotion tests.'},
        'clusterReconstruction': domain_checks, 'branchReconstruction': reproduction,
        'clusterFoldSupport': support_rows, 'chosenClassFiveFoldResidualBias': residual_rows,
        'qualifiedSpecialistLaterEvaluation': specialist_rows, 'selectedEnsembleSubgroups': subgroup_rows,
        'allEightResidualProfiles': all_cluster_profiles(final, p, raw['RESIDUAL_SPECIALISTS'], predictions['V18'],
            predictions['RESIDUAL_SPECIALISTS'], predictions['RF_RESIDUAL_ENSEMBLE']),
        'ensembleContribution': ensemble_details, 'trainingClusterProfiles': cluster_spec.get('profiles', []),
        'authority': {'status': 'RESEARCH_SHADOW', 'promotionStatus': 'NOT_PROMOTED', 'wageringAuthority': False,
            'executionAllowedInAISP': False, 'modelFits': 0, 'calibratorFits': 0, 'providerCalls': 0,
            'finalOotPayloadBytesRead': 0, 'AispReads': 0, 'AispWrites': 0},
        'limitations': ['The original registered OOF population has 501539 PAs; only 494432 safe PAs are used and 7107 remain excluded.',
            'Fold 5 ends 2026-08-06; no sealed 2026-08-14 through 2026-08-27 payload is opened.',
            'Fold 5 is later Development evidence, not independent OOT; earlier folds include discovery/fitting/selection roles.',
            'Subgroups overlap across domains and cold-start flags; counts must not be summed as disjoint populations.',
            'Multiple subgroup intervals are descriptive, with no multiplicity-adjusted superiority claims.',
            'Game and week resampling do not establish joint long-lived player/team dependence control.',
            'Soft gates can influence observations outside the corresponding hard cluster; outside is not an untouched control.']}
    payload['implementation'] = reference(Path(__file__))
    payload['clusterProfileCorrections'] = {row['clusterId']: {key: row[key] for key in
        ('specialistLogLoss', 'meanAdjustment', 'maximumAdjustment')} for row in payload['allEightResidualProfiles']}
    payload['ensembleComposition'] = payload['ensembleContribution']
    raw_json = canonical_json_bytes(clean(payload))
    digest = hashlib.sha256(raw_json).hexdigest()
    directory = OUTPUT / 'diagnostics/sha256' / digest
    lines = ['# Completed-study diagnostics supplement', '',
        'Post-fit descriptive evidence only. No model, calibrator, cluster, gate, ensemble weight or policy was fitted or reselected.', '',
        f'- Predecessor: `{RESULT_SHA}`.', f'- Primary JSON SHA-256: `{digest}`.',
        '- 494,432 safe Development PAs across five folds; 94,157 PAs / 1,248 games in later evaluation.',
        '- Four qualified specialists all target raw V18 BIP_OUT underprediction; the JSON reports actual five-fold signed bias and uncertainty.',
        '- Each qualified regime includes separate RESIDUAL_SPECIALISTS and SOFT_MIXTURE_OF_EXPERTS inside/outside calibrated comparisons.',
        '- Selected-ensemble metrics and paired game/week intervals cover all eight frozen regimes and four predeclared cold-start flags.',
        '- Inside means frozen hard label plus positive support; soft memberships may also influence outside rows.',
        f'- Saved ensemble weights [V18, RF, residual system]: {np.asarray(weights).tolist()}. These are not causal performance attributions.',
        '- All three calibrated branches reproduce the saved atlas within 1e-12; exact differences are in the JSON.',
        '- Calibration regressions are descriptive diagnostics only; no calibrator artifact or forecast probability was changed.',
        '- All intervals are exploratory, not simultaneous tests or promotion authority. Original artifacts remain unchanged.', '']
    files = {'postfit-diagnostics.json': raw_json, 'README.md': '\n'.join(lines).encode('utf-8')}
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = directory / name
        if path.exists():
            if path.read_bytes() != content:
                raise ValueError('Immutable diagnostics output conflict')
        else:
            with path.open('xb') as handle:
                handle.write(content)
    emit('POSTFIT_DIAGNOSTICS_PUBLISHED', artifacts=[reference(directory / name) for name in files],
         qualifiedSpecialists=len(specialist_rows), residualRows=len(residual_rows), subgroups=len(subgroup_rows))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--extend-existing', help='Add requested eight-cluster profile summary to this existing diagnostics SHA, without repeating calibration diagnostics or CIs.')
    parser.add_argument('--add-integration-aliases', help='Publish a pure-JSON immutable successor exposing existing final publisher aliases.')
    arguments = parser.parse_args()
    if arguments.extend_existing and arguments.add_integration_aliases:
        raise ValueError('Choose one bounded successor action')
    with threadpool_limits(limits=4):
        if arguments.add_integration_aliases:
            add_integration_aliases(arguments.add_integration_aliases)
        elif arguments.extend_existing:
            extend_existing(arguments.extend_existing)
        else:
            main()
