"""One bounded, checkpointed Development-only MLB forecast-correction study."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ[name] = '4'

import joblib
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits

from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_current_statcast.mlb_regime_baseline import sha_file, load_oof, OOF_SHA
from server.sports_current_statcast.mlb_regime_clusters import fit_clusters
from server.sports_current_statcast.mlb_regime_models import (
    MembershipBasis, OffsetCorrection, ResidualExperts, SoftGate, ConvexEnsemble,
    discover_failures, fit_temperature, temperature_transform,
)
from server.sports_current_statcast.mlb_regime_metrics import predictive_metrics, metric_contributions, paired_uncertainty
from server.sports_current_statcast.mlb_regime_simulation import load_accepted_transition, compare_paired_game_mechanics

OUTPUT = ROOT / 'outputs/mlb-regime-hybrid-ensemble-v1'
BASELINE_PATH = OUTPUT / 'baseline-cache/baseline-reproduction-0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9.json'
GAME_DIR = OUTPUT / 'game-context/sha256/90dc14c30b5c0b0279730ce716af13e6d3fd23527c36289c3778e8286ee77c02'
PROB_COLS = ['probability_' + c for c in PA_CLASS_ORDER]
MODEL_NAMES = ['V18', 'GLOBAL_CLASS_OFFSET_CONTROL', 'MEMBERSHIP_OFFSET', 'INTERACTION_OFFSET',
               'RESIDUAL_SPECIALISTS', 'SOFT_MIXTURE_OF_EXPERTS', 'RF_RESIDUAL_ENSEMBLE']


def utc():
    return datetime.now(timezone.utc).isoformat()


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


def write_json(path, value):
    raw = canonical_json_bytes(clean(value))
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError(f'Immutable artifact conflict: {path}')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as handle:
            handle.write(raw)
    return reference(path)


def reference(path, label=None, category='Research evidence'):
    return {'path': str(path.resolve()), 'sha256': sha_file(path), 'byteCount': path.stat().st_size,
            'label': label or path.name, 'category': category}


def subset_domains(domains, mask):
    return {name: {k: v[mask] for k, v in data.items()} for name, data in domains.items()}


def quick_metrics(y, probabilities):
    c = metric_contributions(y, probabilities)
    return {'logLoss': float(c['logLoss'].mean()), 'brier': float(c['brier'].mean()), 'entropy': float(c['entropy'].mean())}


def main(run_dir):
    started = utc()
    run_dir.mkdir(parents=True, exist_ok=False)
    events = run_dir / 'events.jsonl'
    def emit(event, **payload):
        row = clean({'event': event, 'utc': utc(), **payload})
        with events.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, sort_keys=True) + '\n')
        print(json.dumps(row), flush=True)
    def fitted(name, function):
        emit('CORRECTION_FIT_STARTED', name=name)
        clock = time.monotonic()
        try:
            value = function()
        except Exception as exc:
            emit('CORRECTION_FIT_FAILED', name=name, error=repr(exc))
            raise
        emit('CORRECTION_FIT_COMPLETED', name=name, seconds=time.monotonic()-clock)
        return value
    try:
        baseline = json.loads(BASELINE_PATH.read_text())
        if sha_file(BASELINE_PATH) != '0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9':
            raise ValueError('Baseline parity receipt bytes differ')
        if any(f['rawPredictionBitwiseMismatchCount'] for f in baseline['folds']) or baseline['finalOotPayloadBytesRead']:
            raise ValueError('Baseline gate not passed')
        def cache(key):
            ref = baseline['artifacts'][key]
            path = Path(ref['path'])
            if sha_file(path) != ref['sha256'] or path.stat().st_size != ref['bytes']:
                raise ValueError('Cached Development artifact differs')
            return pd.read_parquet(path)
        train = cache('trainingFold1')
        frame = pd.concat([cache(f'validationFold{n}') for n in range(1, 6)], ignore_index=True)
        oof = cache('matchedOof').set_index('canonicalPaId', verify_integrity=True).loc[frame.canonicalPaId].reset_index()
        if not np.array_equal(frame.canonicalGameId, oof.canonicalGameId) or not np.array_equal(frame.observedClassIndex, oof.observedClassIndex):
            raise ValueError('Exact evaluation PA/game/target alignment differs')
        if frame.game_date.astype(str).max() > '2026-08-06' or train.game_date.astype(str).max() != '2023-10-01':
            raise ValueError('Unauthorized chronological input date')
        if frame.groupby('canonicalGameId').foldNumber.nunique().max() != 1:
            raise ValueError('Game split across folds')
        game_path = GAME_DIR / 'game-context.parquet'
        if sha_file(game_path) != '1c694e7b8bf185e6fd7366461295290c15a406fb8f527d725e4fbb6d08313adf':
            raise ValueError('Game identity map differs')
        games = pd.read_parquet(game_path)
        frame = frame.merge(games.drop(columns=['game_date']), on='canonicalGameId', how='left', validate='many_to_one', sort=False)
        if frame.homeTeamId.isna().any() or not np.array_equal(frame.canonicalPaId, oof.canonicalPaId):
            raise ValueError('Game-team join changed or lost observations')
        frame['battingTeamId'] = np.where(frame.context_top_bottom == 1, frame.homeTeamId, frame.awayTeamId)
        frame['fieldingTeamId'] = np.where(frame.context_top_bottom == 1, frame.awayTeamId, frame.homeTeamId)
        y = frame.observedClassIndex.to_numpy(dtype=int)
        p = oof[PROB_COLS].to_numpy()
        rf = oof[['rf_' + c for c in PROB_COLS]].to_numpy()
        masks = {'discovery': frame.foldNumber.le(2).to_numpy(), 'specialist_fit': frame.foldNumber.eq(3).to_numpy(),
                 'evaluation': frame.foldNumber.eq(5).to_numpy()}
        days = sorted(frame.loc[frame.foldNumber.eq(4), 'game_date'].astype(str).unique())
        a, b = len(days)//2, len(days)*3//4
        for name, dates in [('gate_fit', days[:a]), ('calibration_fit', days[a:b]), ('selection', days[b:])]:
            masks[name] = frame.foldNumber.eq(4).to_numpy() & frame.game_date.astype(str).isin(dates).to_numpy()
        phase_rows = []
        for name, mask in masks.items():
            sample = frame[mask]
            phase_rows.append({'phase': name, 'observations': len(sample), 'games': sample.canonicalGameId.nunique(),
                               'start': str(sample.game_date.min()), 'end': str(sample.game_date.max())})
        ordered = ['discovery', 'specialist_fit', 'gate_fit', 'calibration_fit', 'selection', 'evaluation']
        for left, right in zip(ordered, ordered[1:]):
            if frame.loc[masks[left], 'game_date'].max() >= frame.loc[masks[right], 'game_date'].min():
                raise ValueError('Chronological model roles overlap')
        contract = {'schemaVersion': 'MLB_REGIME_PREFIT_EXECUTION_V1', 'startedAtUtc': started,
                    'targetOrder': list(PA_CLASS_ORDER), 'baseline': reference(BASELINE_PATH), 'phases': phase_rows,
                    'protocol': reference(ROOT/'docs/MLB_REGIME_HYBRID_STUDY_PROTOCOL_V1.md'),
                    'code': [reference(ROOT/name) for name in ['scripts/run_mlb_regime_hybrid_study.py',
                      'server/sports_current_statcast/mlb_regime_models.py', 'server/sports_current_statcast/mlb_regime_clusters.py',
                      'server/sports_current_statcast/mlb_regime_metrics.py']],
                    'seed': 20260910, 'nativeWorkers': 4, 'globalEstimatorFitsAuthorized': 0, 'finalOotAccessed': False}
        write_json(run_dir/'prefit-contract.json', contract)
        emit('PREFIT_CONTRACT_FROZEN', phases=phase_rows)
        with threadpool_limits(limits=4):
            clusters, cluster_meta = fit_clusters(train, emit=emit)
            domains = clusters.transform(frame)
        joblib.dump(clusters, run_dir/'clusters.joblib', compress=3)
        write_json(run_dir/'cluster-specification.json', cluster_meta)
        del train
        discovery = masks['discovery']
        registry, eligible = discover_failures(frame[discovery], y[discovery], p[discovery], subset_domains(domains, discovery))
        write_json(run_dir/'failure-regime-registry.json', {'rules': registry, 'selected': eligible,
                    'status': 'DISCOVERY_ONLY_FROZEN_BEFORE_SPECIALIST_FITS'})
        emit('FAILURE_REGIMES_FROZEN', qualified=len(eligible), clusters=[e['clusterId'] for e in eligible])
        fit = masks['specialist_fit']
        basis = MembershipBasis().fit(subset_domains(domains, fit), frame[fit])
        z = basis.transform(domains, frame)
        zi = basis.transform(domains, frame, interactions=True)
        with threadpool_limits(limits=4):
            control = fitted('GLOBAL_CLASS_OFFSET_CONTROL', lambda: OffsetCorrection.fit(np.ones((fit.sum(), 1)), y[fit], p[fit]))
            membership = fitted('MEMBERSHIP_OFFSET', lambda: OffsetCorrection.fit(z[fit], y[fit], p[fit]))
            interaction = fitted('INTERACTION_OFFSET', lambda: OffsetCorrection.fit(zi[fit], y[fit], p[fit]))
            specialists = fitted('RESIDUAL_SPECIALISTS', lambda: ResidualExperts.fit(eligible, subset_domains(domains, fit), y[fit], p[fit]))
            gate_mask = masks['gate_fit']
            gate = fitted('SOFT_MIXTURE_OF_EXPERTS', lambda: SoftGate.fit(z[gate_mask], specialists.weights(subset_domains(domains, gate_mask)),
                specialists.branches(p[gate_mask]), y[gate_mask], p[gate_mask]))
            raw = {'V18': p, 'GLOBAL_CLASS_OFFSET_CONTROL': control.predict(np.ones((len(p), 1)), p),
                   'MEMBERSHIP_OFFSET': membership.predict(z, p), 'INTERACTION_OFFSET': interaction.predict(zi, p),
                   'RESIDUAL_SPECIALISTS': specialists.predict(domains, p),
                   'SOFT_MIXTURE_OF_EXPERTS': gate.predict(z, specialists.weights(domains), specialists.branches(p), p)}
            ensemble = fitted('RF_RESIDUAL_ENSEMBLE', lambda: ConvexEnsemble.fit(np.stack(
                [p[gate_mask], rf[gate_mask], raw['RESIDUAL_SPECIALISTS'][gate_mask]], axis=1), y[gate_mask]))
            raw['RF_RESIDUAL_ENSEMBLE'] = ensemble.predict(np.stack([p, rf, raw['RESIDUAL_SPECIALISTS']], axis=1))
            temperatures, temperature_receipts, calibrated = {}, {}, {}
            cal = masks['calibration_fit']
            for name in MODEL_NAMES:
                temperature, receipt = fitted('TEMPERATURE_'+name, lambda name=name: fit_temperature(y[cal], raw[name][cal]))
                temperatures[name], temperature_receipts[name] = temperature, receipt
                calibrated[name] = temperature_transform(raw[name], temperature)
        selection = masks['selection']
        selection_scores = {name: quick_metrics(y[selection], probabilities[selection]) for name, probabilities in calibrated.items()}
        candidates = [name for name in MODEL_NAMES[2:] if selection_scores[name]['brier'] <= selection_scores['V18']['brier']]
        selected = min(['V18', *candidates], key=lambda name: (selection_scores[name]['logLoss'], name))
        selection_receipt = {'selected': selected, 'basis': 'FOLD4_LAST_SEGMENT_ONLY_CALIBRATED_LL_WITH_NONWORSE_BRIER', 'scores': selection_scores,
                             'temperatures': temperatures, 'temperatureFitReceipts': temperature_receipts}
        write_json(run_dir/'selection-frozen-before-evaluation.json', selection_receipt)
        emit('CANDIDATE_FROZEN_BEFORE_FINAL_DEVELOPMENT_EVALUATION', selected=selected)
        fitted_bundle = {'clusters': clusters, 'basis': basis, 'control': control, 'membership': membership, 'interaction': interaction,
                         'specialists': specialists, 'gate': gate, 'ensemble': ensemble, 'temperatures': temperatures,
                         'selected': selected, 'targetOrder': list(PA_CLASS_ORDER), 'forecastInput': 'EXACT_V18_PROBABILITIES_AND_273_SEMANTIC_FEATURES'}
        joblib.dump(fitted_bundle, run_dir/'fitted-research-system.joblib', compress=3)
        # Reload and reproduce all evaluation correction branches, not just serialize.
        reloaded = joblib.load(run_dir/'fitted-research-system.joblib')
        ev = masks['evaluation']
        rd = reloaded['clusters'].transform(frame[ev])
        rz = reloaded['basis'].transform(rd, frame[ev])
        rzi = reloaded['basis'].transform(rd, frame[ev], interactions=True)
        sp = reloaded['specialists']
        check = {'V18': p[ev], 'GLOBAL_CLASS_OFFSET_CONTROL': reloaded['control'].predict(np.ones((ev.sum(), 1)), p[ev]),
                 'MEMBERSHIP_OFFSET': reloaded['membership'].predict(rz, p[ev]), 'INTERACTION_OFFSET': reloaded['interaction'].predict(rzi, p[ev]),
                 'RESIDUAL_SPECIALISTS': sp.predict(rd, p[ev]), 'SOFT_MIXTURE_OF_EXPERTS': reloaded['gate'].predict(rz, sp.weights(rd), sp.branches(p[ev]), p[ev])}
        check['RF_RESIDUAL_ENSEMBLE'] = reloaded['ensemble'].predict(np.stack([p[ev], rf[ev], check['RESIDUAL_SPECIALISTS']], axis=1))
        reload_checks = {name: {'maximumAbsoluteDifference': float(np.max(np.abs(check[name]-raw[name][ev]))),
                              'bitwiseEqual': bool(np.array_equal(check[name], raw[name][ev]))} for name in MODEL_NAMES}
        if any(row['maximumAbsoluteDifference'] > 1e-12 for row in reload_checks.values()):
            raise ValueError('Fitted research artifact reload failed')
        write_json(run_dir/'artifact-reload-verification.json', reload_checks)
        emit('ARTIFACT_RELOAD_VERIFIED', results=reload_checks)
        leaderboard, calibration = [], []
        for phase in ('selection', 'evaluation'):
            mask = masks[phase]
            for mode, predictions in [('RAW', raw), ('CALIBRATED', calibrated)]:
                base_metrics = quick_metrics(y[mask], predictions['V18'][mask])
                for name in MODEL_NAMES:
                    metrics = predictive_metrics(y[mask], predictions[name][mask])
                    leaderboard.append({'model': name, 'phase': phase.upper()+'_'+mode, 'observations': int(mask.sum()),
                        'games': int(frame.loc[mask, 'canonicalGameId'].nunique()), **{key: metrics[key] for key in ('logLoss','brier','entropy')},
                        'deltaLogLoss': metrics['logLoss']-base_metrics['logLoss'], 'deltaBrier': metrics['brier']-base_metrics['brier'],
                        'temperature': temperatures[name] if mode == 'CALIBRATED' else 1.})
                    calibration.append({'model': name, 'phase': phase.upper()+'_'+mode, **metrics})
            emit('PHASE_METRICS_COMPLETED', phase=phase)
        final_frame = frame[ev].reset_index(drop=True)
        intervals = {}
        for name in MODEL_NAMES[1:]:
            intervals[name] = paired_uncertainty(final_frame, y[ev], calibrated['V18'][ev], calibrated[name][ev], seed=20260910, replicates=1000)
            emit('PAIRED_INTERVAL_COMPLETED', model=name)
        diagnostic_name = selected if selected != 'V18' else min(MODEL_NAMES[2:], key=lambda name: selection_scores[name]['logLoss'])
        # A nonselected diagnostic is never substituted for the selected recommendation.
        profiles, regime_metrics, influence = [], [], []
        base_c = metric_contributions(y[ev], calibrated['V18'][ev])
        challenger_c = metric_contributions(y[ev], calibrated[diagnostic_name][ev])
        adjustment = np.max(np.abs(raw[diagnostic_name][ev] - p[ev]), axis=1)
        for domain, data in domains.items():
            labels = data['labels'][ev]
            for k in range(data['membership'].shape[1]):
                take = (labels == k) & (data['support'][ev] > 0)
                if not take.any():
                    continue
                cluster_id = f'{domain}_{k}'
                meta = next((row for row in cluster_meta.get('profiles', []) if row.get('clusterId') == cluster_id), {})
                weights = data['membership'][ev, k] * data['support'][ev]
                profile = {'clusterId': cluster_id, 'domain': domain, 'features': clusters.features[domain],
                    'interpretation': meta.get('interpretation', 'Training-defined '+domain.lower().replace('_',' ')+' archetype '+str(k)),
                    'populationPAs': int(take.sum()), 'games': int(final_frame.loc[take,'canonicalGameId'].nunique()),
                    'seasons': sorted(frame.loc[data['labels'] == k, 'season'].unique().tolist()),
                    'stabilityARI': meta.get('stabilityAri'), 'effectivePAs': float(weights.sum()**2 / max((weights*weights).sum(), 1e-30)),
                    'globalLogLoss': float(base_c['logLoss'][take].mean()), 'specialistLogLoss': float(challenger_c['logLoss'][take].mean()),
                    'meanAdjustment': float(adjustment[take].mean()), 'maximumAdjustment': float(adjustment[take].max()),
                    'recommendation': 'LATER_DEVELOPMENT_DIAGNOSTIC_NOT_PROMOTED', 'comparisonModel': diagnostic_name, 'trainingProfile': meta}
                profiles.append(profile)
                for inside, subset in [('INSIDE', take), ('OUTSIDE', ~take)]:
                    if subset.any():
                        regime_metrics.append({'clusterId': cluster_id, 'scope': inside, 'observations': int(subset.sum()),
                            'baseline': quick_metrics(y[ev][subset], calibrated['V18'][ev][subset]),
                            'challenger': quick_metrics(y[ev][subset], calibrated[diagnostic_name][ev][subset])})
        for name in MODEL_NAMES[1:]:
            change = np.max(np.abs(raw[name][ev]-p[ev]), axis=1)
            influence.append({'model': name, 'observations': int(ev.sum()), 'influencedObservations': int((change > 1e-12).sum()),
                              'influenceFraction': float((change > 1e-12).mean()), 'meanMaximumClassAdjustment': float(change.mean()),
                              'maximumClassAdjustment': float(change.max())})
        cold = {}
        for name, mask in {'batter_no_prior': final_frame.batter_prior_missing.eq(1), 'pitcher_no_prior': final_frame.pitcher_prior_missing.eq(1),
            'batter_low_rolling_history': final_frame.batter_last100_insufficient.eq(1), 'pitcher_low_rolling_history': final_frame.pitcher_last250_insufficient.eq(1)}.items():
            mask = mask.to_numpy()
            cold[name] = {'observations': int(mask.sum()), 'games': int(final_frame.loc[mask,'canonicalGameId'].nunique()),
                'baseline': quick_metrics(y[ev][mask], calibrated['V18'][ev][mask]) if mask.any() else None,
                'challenger': quick_metrics(y[ev][mask], calibrated[diagnostic_name][ev][mask]) if mask.any() else None}
        removal, month_metrics = [], []
        delta = challenger_c['logLoss'] - base_c['logLoss']
        for field, values in [('month', final_frame.game_date.astype(str).str[:7]), ('battingTeamId', final_frame.battingTeamId)]:
            grouped = pd.DataFrame({'group': values, 'delta': delta}).groupby('group').delta.agg(['sum','mean','size'])
            strongest = str(grouped['sum'].idxmin())
            keep = np.asarray(values.astype(str) != strongest)
            removal.append({'removedCategory': field, 'removed': strongest, 'remainingPAs': int(keep.sum()),
                            'deltaLogLoss': float(delta[keep].mean()), 'scope': 'EXPLORATORY_REMOVAL_SENSITIVITY'})
            if field == 'month':
                month_metrics = [{'month': str(idx), 'deltaLogLoss': float(row['mean']), 'observations': int(row['size'])} for idx,row in grouped.iterrows()]
        if profiles:
            strongest_profile = min(profiles, key=lambda row: (row['specialistLogLoss']-row['globalLogLoss'])*row['populationPAs'])
            domain, k = strongest_profile['domain'], int(strongest_profile['clusterId'].rsplit('_',1)[1])
            keep = domains[domain]['labels'][ev] != k
            removal.append({'removedCategory': 'cluster', 'removed': strongest_profile['clusterId'], 'remainingPAs': int(keep.sum()),
                            'deltaLogLoss': float(delta[keep].mean()), 'scope':'EXPLORATORY_REMOVAL_SENSITIVITY'})
        fold_metrics = []
        for n in range(1,6):
            mask = frame.foldNumber.eq(n).to_numpy()
            fold_metrics.append({'fold': n, 'observations': int(mask.sum()), 'baseline': quick_metrics(y[mask], p[mask]),
                                 'candidateEvidenceRole': next(row['phase'] for row in phase_rows if str(frame.loc[mask,'game_date'].min()) >= row['start'] and str(frame.loc[mask,'game_date'].min()) <= row['end'])})
        tables = []
        for n in range(1,6):
            mask = frame.foldNumber.eq(n).to_numpy()
            atlas = frame.loc[mask, ['canonicalPaId','canonicalGameId','game_date','season','foldNumber','observedClassIndex',
                'batterCanonicalPlayerId','pitcherCanonicalPlayerId','battingTeamId','fieldingTeamId',
                'batter_prior_missing','pitcher_prior_missing','batter_last100_insufficient','pitcher_last250_insufficient']].copy()
            contributions = metric_contributions(y[mask], p[mask])
            for col in ('logLoss','brier','entropy','maximumProbability'):
                atlas[col] = contributions[col]
            for c, label in enumerate(PA_CLASS_ORDER):
                atlas['v18_'+label] = p[mask,c]
                atlas['calibrationResidual_'+label] = contributions['calibrationResidual'][:,c]
            for domain, data in domains.items():
                atlas[domain+'_label'] = data['labels'][mask]
                atlas[domain+'_support'] = data['support'][mask]
                for k in range(data['membership'].shape[1]):
                    atlas[f'{domain}_membership_{k}'] = data['membership'][mask,k]
            if n == 5:
                for name in MODEL_NAMES[1:]:
                    for c,label in enumerate(PA_CLASS_ORDER):
                        atlas[name+'_'+label] = calibrated[name][mask,c]
            path = run_dir/f'error-atlas-fold-{n}.parquet'
            atlas.to_parquet(path, index=False, compression='zstd')
            tables.append(reference(path, f'Fold {n} error atlas and cluster assignments', 'Machine-readable evidence'))
        original_oof = load_oof(OOF_SHA, 'histogram_gradient_boosting')
        excluded = original_oof[~original_oof.canonicalPaId.isin(frame.canonicalPaId)][['canonicalPaId','canonicalGameId','foldNumber']].copy()
        excluded['reason'] = 'MIXED_SEALED_ROW_GROUP_OR_INCOMPLETE_BOUNDARY_DATE'
        excluded.to_parquet(run_dir/'excluded-development-ids.parquet', index=False, compression='zstd')
        transition, transition_ref = load_accepted_transition(ROOT)
        simulation = compare_paired_game_mechanics(final_frame, p[ev], raw[diagnostic_name][ev], transition_model=transition,
            transition_training_end=transition_ref['trainingEnd'], transition_model_sha256=transition_ref['sha256'],
            n_sims=500, maximum_games=20, game_truth=games.dropna(subset=['actualAway','actualHome']))
        write_json(run_dir/'simulation-comparison.json', simulation)
        eval_scores = {name: quick_metrics(y[ev], calibrated[name][ev]) for name in MODEL_NAMES}
        verdict = 'NO_DEMONSTRATED_IMPROVEMENT_RETAIN_V18'
        if selected != 'V18':
            ci = intervals[selected]
            upper_game = ci['gameClusterBootstrap'].get('intervals',{}).get('logLoss',{}).get('upper', float('inf'))
            upper_week = ci['calendarWeekBlockBootstrap'].get('intervals',{}).get('logLoss',{}).get('upper', float('inf'))
            wins = sum(row['deltaLogLoss'] < 0 for row in month_metrics)
            if (eval_scores[selected]['logLoss'] < eval_scores['V18']['logLoss'] and eval_scores[selected]['brier'] <= eval_scores['V18']['brier']
                    and upper_game < 0 and upper_week < 0 and wins > len(month_metrics)/2):
                verdict = 'RESEARCH_CHALLENGER_REQUIRES_PROSPECTIVE_EVIDENCE'
        result = {'contract':'MLB_REGIME_HYBRID_STUDY_V1', 'studyId':run_dir.name, 'projectId':'asp-mtlozhdx', 'status':'COMPLETED',
            'startedAtUtc':started, 'completedAtUtc':utc(), 'verdict':verdict, 'selectedArchitecture':selected, 'diagnosticChallenger':diagnostic_name,
            'authority':{'status':'RESEARCH_SHADOW','promotionStatus':'NOT_PROMOTED','wageringAuthority':False,'executionAllowedInAISP':False,
                'finalOotAccessed':False,'classOrder':list(PA_CLASS_ORDER),'finalOot':['2026-08-14','2026-08-27'],
                'treatmentManifestSha256':baseline['treatmentManifestSha256'], 'globalModel':'V18_ACCEPTED_FROZEN_FOLD_MODELS',
                'sourceUseRestrictions':['LOCAL_PRIVATE_MODEL_DEVELOPMENT','GOVERNED_LOCAL_RESEARCH_ONLY','ATTRIBUTION_REQUIRED','COMMERCIAL_RIGHTS_REVIEW_REQUIRED']},
            'cohort':{'eligibleDevelopmentPAs':baseline['eligibleRawRows'],'oofPAs':len(frame),'oofGames':frame.canonicalGameId.nunique(),
                'seasons':sorted(frame.season.unique().tolist()),'excludedOofPAs':len(excluded),'registeredOofPAs':501539,'phases':phase_rows},
            'baselineParity':baseline, 'clusterProfiles':profiles, 'stability':[{'domain':name, **data} for name,data in cluster_meta['domains'].items()],
            'failureRegimes':[r for r in registry if r['eligible']], 'specialistEligibility':eligible,
            'leaderboard':leaderboard,'influence':influence,'calibration':calibration,'uncertaintyIntervals':intervals,
            'regimeMetrics':regime_metrics,'coldStart':cold,'removalSensitivity':removal,'monthlyEvaluation':month_metrics,
            'foldMetrics':fold_metrics,'gameSimulation':simulation,'artifactReload':reload_checks,
            'selection':selection_receipt,'modelFitReceipts':{'control':control.fit_receipt,'membership':membership.fit_receipt,
                'interaction':interaction.fit_receipt,'gate':gate.fit_receipt,'ensemble':ensemble.fit_receipt,
                'residualExperts':clean(specialists.experts),'clustering':cluster_meta.get('fitAccounting')},
            'limitations':[], 'currentShadow':{'status':'NOT_PUBLISHED_PENDING_SUPPORTED_CURRENT_PREGAME_INPUT_AUTHORITY','forecasts':0},
            'artifacts':tables}
        for filename in ['prefit-contract.json','cluster-specification.json','failure-regime-registry.json','selection-frozen-before-evaluation.json',
                         'fitted-research-system.joblib','clusters.joblib','artifact-reload-verification.json','simulation-comparison.json','excluded-development-ids.parquet']:
            result['artifacts'].append(reference(run_dir/filename))
        write_json(run_dir/'study-result.json', result)
        emit('STUDY_COMPLETE', verdict=verdict, selected=selected, result=reference(run_dir/'study-result.json'))
    except Exception as exc:
        emit('STUDY_FAILED', error=repr(exc))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    if not args.run_id.replace('-','').replace('_','').isalnum():
        raise ValueError('A simple unique run identity is required')
    with threadpool_limits(limits=4):
        main(OUTPUT/'runs'/args.run_id)
