"""Append-only assessment of one declared NBA ordinary-rest correction."""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .authority import reference, verified_bytes
from .recent_study import now, save, predict, assess, pair_interval, summarize
from .rest_support import fit_rest_model, feature_contract


def code_bindings():
    here = Path(__file__).parent
    return {n: reference(here/n) for n in ("rest_support.py", "rest_study.py", "recent_study.py",
            "recent_features.py", "historical_features.py", "recent_models.py", "models.py")}


def fit_bound(train, folder):
    path = folder/'ridge_a100_rest.joblib'
    if path.exists():
        raise ValueError("Refusing to replace a fitted correction")
    model = fit_rest_model(train, train)
    folder.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path, compress=3)
    bound = {"config": {"id": "ridge_a100_rest", "family": "ridge", "params": {"alpha": 100.0}},
             "artifact": reference(path), "trainingGames": len(train),
             "trainingGameIds": list(model.training_game_ids),
             "trainingIdentitySha256": model.training_identity_sha256,
             "trainingLastDate": str(train.game_date.max()),
             "trainingHomeWinFraction": float((train.home_score > train.away_score).mean()),
             "featureContract": feature_contract(), "restSupport": model.rest_support,
             "coefficients": model.diagnostic_coefficients,
             "rawTrainingFeaturesSha256": model.raw_training_feature_values_sha256,
             "treatedTrainingFeaturesSha256": model.training_feature_values_sha256,
             "trainingTargetsSha256": model.training_target_values_sha256,
             "numericalModules": code_bindings(), "futurePublicationEligible": False}
    return model, bound


def grouped_results(ledger, audit):
    original = ledger[ledger.model_id == 'ridge_a100']
    failures = set(original.loc[(original.expected_home_score < 0) | (original.expected_away_score < 0), 'game_id'])
    ordinary = set(audit.loc[audit.both_ordinary_supported, 'game_id'])
    groups = {'all': set(original.game_id), 'original_negative_games': failures,
              'both_ordinary_rest_supported': ordinary,
              'other_rest_unavailable': set(original.game_id) - ordinary - failures}
    out = {}
    for name, ids in groups.items():
        sample = ledger[ledger.game_id.isin(ids)]
        out[name] = {model: {**summarize(frame),
                            'minimumExpectedTeamScore': float(frame[['expected_home_score', 'expected_away_score']].min().min()),
                            'negativeTeamExpectations': int((frame[['expected_home_score', 'expected_away_score']] < 0).sum().sum())}
                     for model, frame in sample.groupby('model_id')}
    return out


def run(root, stage):
    root = Path(root)
    prior = root.parent/'nba-gen1-recent-v1'
    declaration = json.loads((root/'declaration.json').read_bytes())
    if declaration['configuration'] != 'NBA_GEN1_ELO_WIN_RIDGE_A100_ORDINARY_REST_V1':
        raise ValueError('Fixed remedy declaration required')
    if stage not in ('development', 'reused-diagnostics'):
        raise ValueError('Use dedicated 2026 source admission before new assessment')
    folder = root/stage
    receipt = folder/'receipt.json'
    if receipt.exists():
        existing = json.loads(receipt.read_bytes())
        for bound in existing['artifacts'].values():
            verified_bytes(bound)
        return existing
    folder.mkdir(parents=True, exist_ok=True)
    feature_path = prior/('development' if stage == 'development' else 'holdout')/'features.parquet'
    source_stages = ['development'] if stage == 'development' else ['validation', 'holdout']
    ledger_paths = [prior/s/'predictions-and-paired-residuals.parquet' for s in source_stages]
    save(folder/'execution-start.json', {'createdAtUtc': now(), 'declaration': reference(root/'declaration.json'),
         'features': reference(feature_path), 'originalPredictions': [reference(p) for p in ledger_paths],
         'numericalModules': code_bindings(), 'evidence': 'Reused historical Development/diagnostic outcomes; not new untouched confirmation'})
    features = pd.read_parquet(feature_path)
    originals = pd.concat([pd.read_parquet(p) for p in ledger_paths], ignore_index=True)
    originals = originals[originals.model_id.isin(['ridge_a100', 'elo'])].copy()
    years = [2021, 2022, 2023] if stage == 'development' else [2024, 2025]
    all_predictions, all_audits, models = [originals], [], {}
    for year in years:
        train = features[(features.season_end < year) & features.target_eligible].copy()
        target = features[(features.season_end == year) & features.target_eligible].copy()
        model, bound = fit_bound(train, folder/'models'/str(year))
        candidate = predict(bound, target)
        original = originals[(originals.model_id == 'ridge_a100') & (originals.season_end == year)]
        if set(candidate.game_id) != set(original.game_id):
            raise ValueError('Correction must preserve the exact original assessment games')
        a = candidate.set_index('game_id').sort_index()
        b = original.set_index('game_id').sort_index()
        if not np.array_equal(a.p_home_win.to_numpy(), b.p_home_win.to_numpy()):
            raise ValueError('Elo probability changed')
        audit = model.support_audit(target)
        audit['season_end'] = year
        all_predictions.append(candidate)
        all_audits.append(audit)
        models[str(year)] = bound
    ledger = pd.concat(all_predictions, ignore_index=True)
    audits = pd.concat(all_audits, ignore_index=True)
    ledger.to_parquet(folder/'predictions.parquet', index=False)
    audits.to_parquet(folder/'rest-input-audit.parquet', index=False)
    result = assess(ledger)
    result.update(pairedCorrectionVersusOriginal=pair_interval(ledger, 'ridge_a100_rest', 'ridge_a100'),
                  supportGroups=grouped_results(ledger, audits),
                  status='DEVELOPMENT_REUSED_FOR_REMEDY' if stage == 'development' else 'REUSED_2024_2025_DIAGNOSTIC_EVIDENCE_NOT_UNTOUCHED',
                  thresholds={y: b['restSupport']['maximumDays'] for y,b in models.items()},
                  noScoreClipping=True)
    save(folder/'assessment.json', result)
    save(folder/'models.json', models)
    result_receipt = {'schema': 'nba-gen1-rest-remedy-assessment-receipt-v1', 'createdAtUtc': now(),
                      'stage': stage, 'declaration': reference(root/'declaration.json'),
                      'distinctAssessmentGames': int(ledger.game_id.nunique()),
                      'artifacts': {n: reference(folder/n) for n in ('predictions.parquet', 'rest-input-audit.parquet', 'assessment.json', 'models.json')},
                      'numericalModules': code_bindings(), 'originalArtifactsReplaced': False}
    save(receipt, result_receipt)
    return result_receipt
