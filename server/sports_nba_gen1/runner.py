"""Gated season-forward NBA research execution. No production registration.

Every numerical phase requires a verified real source index. Unit fixtures are
not an alternate admission mode. Selection and OOT are separate invocations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from .authority import (RESEARCH_FLAGS, immutable_json, json_bytes, latest_final_rows, load_seasons, numerical_source_bindings,
                        reference, require, verified_bytes)
from .assessment import (SCORE_COLUMNS, add_groups, advancement_gate, flatten_score, grouped_report,
                         paired_interval, summary)
from .distribution import game_seed, score_forecast, simulate, summarize
from .features import FEATURE_COLUMNS, build_features, feature_contract
from .models import fit_model


def artifact(root, name, raw):
    sha = hashlib.sha256(raw).hexdigest()
    path = Path(root)/'objects/sha256'/sha/name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == raw, 'Immutable artifact conflict')
    else:
        path.write_bytes(raw)
    return reference(path)


def frame_artifact(root, name, frame):
    stream = io.BytesIO()
    frame.to_parquet(stream, index=False)
    return artifact(root, name, stream.getvalue())


def model_artifact(root, name, model):
    stream = io.BytesIO()
    joblib.dump(model, stream, compress=3)
    return artifact(root, name, stream.getvalue())


def get_frame(bound):
    return pd.read_parquet(io.BytesIO(verified_bytes(bound)))


def load_pointer(root, name):
    pointer = Path(root)/(name+'.json')
    require(pointer.exists(), 'Required earlier phase missing: '+name)
    bound = json.loads(pointer.read_bytes())
    return json.loads(verified_bytes(bound)), bound


def finish(root, name, value):
    bound = immutable_json(root, name+'.json', value)
    path = Path(root)/(name+'.json')
    try:
        with path.open('xb') as stream:
            stream.write(json_bytes(bound))
    except FileExistsError:
        require(False, 'Completed phase is immutable; use its retained receipt')
    return bound


def context(root):
    plan, plan_ref = load_pointer(root, 'declaration')
    require(plan['outcomesOpened'] is False and plan['scope'] == 'NBA_REGULAR_SEASON_FULL_GAME_INCLUDING_OVERTIME', 'Wrong population declaration')
    current = numerical_source_bindings()
    require(set(current) == set(plan['numericalSources']), 'Numerical implementation inventory changed after registration')
    for key, bound in plan['numericalSources'].items():
        verified_bytes(bound)
        require(current[key]['sha256'] == bound['sha256'], 'Numerical implementation changed after registration')
    require(plan['featureContract']['sha256'] == feature_contract()['sha256'], 'Feature contract changed after registration')
    index = json.loads(verified_bytes(plan['sourceIndex']))
    return plan, plan_ref, index


def features(games):
    targets = latest_final_rows(games).sort_values(['scheduled_tipoff_utc', 'game_id'])
    frame, audit = build_features(games[games.status == 'FINAL'], targets)
    supported = (frame.home_history_supported == 1) & (frame.away_history_supported == 1)
    dispositions = frame.loc[~supported, ['game_id', 'season', 'home_history_supported', 'away_history_supported']].copy()
    dispositions['reason'] = 'INSUFFICIENT_CURRENT_OR_PRIOR_SEASON_TEAM_HISTORY'
    return frame[supported].reset_index(drop=True), targets, audit, dispositions


def labels_before(games, cutoff, target_season):
    admitted = games[(pd.to_datetime(games.source_available_at_utc, utc=True) < pd.Timestamp(cutoff)) & (games.season < target_season)]
    return latest_final_rows(admitted)


def fitting_rows(games, feature_frame, cutoff, target_season, minimum):
    labels = labels_before(games, cutoff, target_season)
    labels = labels[labels.game_id.isin(feature_frame.game_id)]
    x = feature_frame.set_index('game_id').loc[labels.game_id].reset_index()
    require(len(labels) >= minimum, 'Insufficient earlier eligible training games')
    require((labels.season < target_season).all(), 'Target season entered model training')
    return x, labels


def ot_training(periods, labels, cutoff):
    keys = set(zip(labels.game_id, labels.source_revision))
    chosen = periods.loc[np.array([tuple(x) in keys for x in periods[['game_id', 'source_revision']].itertuples(index=False, name=None)], dtype=bool)]
    return chosen[pd.to_datetime(chosen.source_available_at_utc, utc=True) < pd.Timestamp(cutoff)].copy()


def residual_frame(targets, predicted, cutoff, family):
    result = targets[['game_id', 'season', 'scheduled_tipoff_utc', 'source_available_at_utc', 'source_revision']].copy()
    result['predicted_home'] = predicted[:, 0]
    result['predicted_away'] = predicted[:, 1]
    result['residual_home'] = targets.home_score.to_numpy()-predicted[:, 0]
    result['residual_away'] = targets.away_score.to_numpy()-predicted[:, 1]
    result['point_training_cutoff_utc'] = str(cutoff)
    result['family'] = family
    result['residual_kind'] = 'SEASON_FORWARD_OUT_OF_FOLD'
    return result


def evaluate(root, name, targets, predicted, donors, overtime, plan, feature_frame, pace_cutpoints):
    rows, homes, aways, diagnostics = [], [], [], []
    require(len(overtime) >= plan['minimumOvertimePeriods'], 'Insufficient authenticated earlier OT periods; tie treatment unsupported')
    overtime_pairs = overtime[['home_points', 'away_points']].to_numpy()
    for (_, target), point in zip(targets.iterrows(), predicted):
        eligible = donors[(donors.season < target.season) &
            (pd.to_datetime(donors.source_available_at_utc, utc=True) < pd.Timestamp(target.scheduled_tipoff_utc))]
        require(len(eligible) >= plan['minimumResidualDonors'], 'Insufficient chronological paired residual donors')
        require(set(eligible.residual_kind) == {'SEASON_FORWARD_OUT_OF_FOLD'}, 'In-sample residuals are forbidden')
        seed = game_seed(str(target.game_id), 'NBA_GEN1_COMMON_RANDOM_V1', plan['seed'])
        simulation = simulate(float(point[0]), float(point[1]), eligible[['residual_home', 'residual_away']].to_numpy(),
            seed=seed, draws=plan['draws'], overtime_evidence=overtime_pairs)
        h, a = simulation['home_runs'], simulation['away_runs']
        score = score_forecast(h, a, int(target.home_score), int(target.away_score))
        q = summarize(h, a, include_distributions=False)
        rows.append({'game_id': target.game_id, 'season': int(target.season), 'scheduled_tipoff_utc': str(target.scheduled_tipoff_utc),
            'pointHome': float(point[0]), 'pointAway': float(point[1]), 'expectedHome': q['expectedHomeScore'],
            'expectedAway': q['expectedAwayScore'], 'expectedTotal': q['expectedTotal'], 'expectedMargin': q['expectedHomeMargin'],
            'actualHome': int(target.home_score), 'actualAway': int(target.away_score), 'residualDonors': len(eligible),
            'homeWinMcse': q['homeWinMonteCarloStandardError'], **flatten_score(score)})
        homes.append(h)
        aways.append(a)
        diagnostics.append({'game_id': target.game_id, 'seed': seed, 'overtimeDonors': len(overtime), **simulation['diagnostics']})
    ledger = add_groups(pd.DataFrame(rows), feature_frame, pace_cutpoints)
    stream = io.BytesIO()
    np.savez_compressed(stream, game_ids=ledger.game_id.to_numpy(dtype=str), home=np.stack(homes), away=np.stack(aways))
    result = {'ledger': frame_artifact(root, name+'-ledger.parquet', ledger),
        'population': artifact(root, name+'-paired-draws.npz', stream.getvalue()),
        'diagnostics': immutable_json(root, name+'-simulation-diagnostics.json', diagnostics),
        'scores': grouped_report(ledger), 'originalDrawsPerGame': plan['draws'],
        'simulationMeaning': 'Final-score paired residual population plus explicit empirical OT tie resolution; no independent sampling of team errors.'}
    return result, ledger


def point_permutation_diagnostics(model, x, y, seed):
    """One fixed shuffle per feature on earlier Development holdout predictions.

    This describes associations measured by point squared error, not causality,
    not energy importance, and not an additional configuration-selection gate.
    """
    truth = y[['home_score', 'away_score']].to_numpy(float)
    baseline = float(np.mean((model.predict(x)-truth)**2))
    rng = np.random.default_rng(seed)
    rows = []
    for column in FEATURE_COLUMNS:
        altered = x.copy()
        altered[column] = altered[column].to_numpy()[rng.permutation(len(altered))]
        error = float(np.mean((model.predict(altered)-truth)**2))
        rows.append({'feature': column, 'increaseInMeanTeamSquaredError': error-baseline})
    return {'kind': 'EXPLORATORY_DEVELOPMENT_HOLDOUT_POINT_PERMUTATION', 'games': len(x), 'seed': seed,
        'permutationsPerFeature': 1, 'baselineMeanTeamSquaredError': baseline,
        'interpretation': 'Associational sensitivity with correlated features; not causal effect, probability-score importance or independent assessment.',
        'rows': sorted(rows, key=lambda r: r['increaseInMeanTeamSquaredError'], reverse=True)}


def development(root):
    plan, plan_ref, index = context(root)
    require(not (Path(root)/'development.json').exists(), 'Development already frozen')
    games, overtime = load_seasons(index, plan['roles']['development'])
    x, targets, audit, dispositions = features(games)
    require(len(x) > 0, 'No supported real feature rows')
    pace_cutpoints = np.quantile((x.home_pace+x.away_pace)/2, [1/3, 2/3]).tolist()
    settings, entries = {}, []
    for family, configurations in plan['screen'].items():
        trials = []
        for number, parameters in enumerate(configurations):
            residuals, scored_ledgers, folds = [], [], []
            for season in plan['roles']['development'][1:]:
                target_x = x[x.season == season].sort_values(['scheduled_tipoff_utc', 'game_id'])
                require(len(target_x) > 0, 'No supported target season')
                target = targets.set_index('game_id').loc[target_x.game_id].reset_index()
                cutoff = pd.to_datetime(target.scheduled_tipoff_utc, utc=True).min()-pd.Timedelta(nanoseconds=1)
                train_x, train_y = fitting_rows(games, x, cutoff, season, plan['minimumTrainingGames'])
                model = fit_model(family, parameters, train_x, train_y)
                predicted = model.predict(target_x)
                model_ref = model_artifact(root, f'{family}-{number}-through-{season-1}.joblib', model)
                fold = {'season': season, 'trainingCutoff': str(cutoff), 'trainingGames': len(train_y), 'model': model_ref}
                if residuals:
                    donors = pd.concat(residuals, ignore_index=True)
                    ot = ot_training(overtime, train_y, cutoff)
                    result, ledger = evaluate(root, f'dev-{family}-{number}-{season}', target, predicted, donors, ot, plan, x, pace_cutpoints)
                    fold['assessment'] = result
                    scored_ledgers.append(ledger)
                residuals.append(residual_frame(target, predicted, cutoff, family))
                folds.append(fold)
            require(scored_ledgers, 'Development requires at least three chronological seasons')
            scored = pd.concat(scored_ledgers, ignore_index=True)
            bank = pd.concat(residuals, ignore_index=True)
            trial = {'family': family, 'parameters': parameters, 'folds': folds, 'scores': summary(scored),
                'scoredGameIds': scored.game_id.tolist(),
                'residuals': frame_artifact(root, f'{family}-{number}-oof-residuals.parquet', bank)}
            trials.append(trial)
            entries.append(trial)
        require(all(t['scoredGameIds'] == trials[0]['scoredGameIds'] for t in trials), 'Hyperparameter trials must use the same chronological games')
        settings[family] = min(trials, key=lambda t: t['scores']['metrics']['energy'])
    selected_hgb = settings['hgb']
    last_fold = selected_hgb['folds'][-1]
    hgb = joblib.load(io.BytesIO(verified_bytes(last_fold['model'])))
    holdout_x = x[x.season == last_fold['season']].sort_values(['scheduled_tipoff_utc', 'game_id'])
    holdout_y = targets.set_index('game_id').loc[holdout_x.game_id].reset_index()
    importance = immutable_json(root, 'development-hgb-permutation.json',
        point_permutation_diagnostics(hgb, holdout_x, holdout_y, plan['seed']))
    record = {'schemaVersion': 'NBA_GEN1_DEVELOPMENT_FREEZE_V1', 'frozenAtUtc': datetime.now(timezone.utc).isoformat(),
        'declaration': plan_ref, 'selectedSettings': settings, 'allTrials': entries, 'paceCutpoints': pace_cutpoints,
        'features': frame_artifact(root, 'development-features.parquet', x),
        'featureAudit': immutable_json(root, 'development-feature-audit.json', audit),
        'hgbAssociationalImportance': importance,
        'unsupported': frame_artifact(root, 'development-unsupported.parquet', dispositions),
        'validationOpened': False, 'ootOpened': False, **RESEARCH_FLAGS}
    return finish(root, 'development', record)


def season_assessment(root, phase):
    plan, plan_ref, index = context(root)
    development_result, dev_ref = load_pointer(root, 'development')
    require(phase in ('validation', 'oot'), 'Unknown assessment role')
    require(not (Path(root)/(phase+'.json')).exists(), 'Completed assessment is immutable')
    if phase == 'oot':
        selected, selection_ref = load_pointer(root, 'selection')
        require(selected['ootOpened'] is False and selected['lockedFamily'], 'Selection must be locked before OOT')
        # A failed/interrupted one-time opening remains an explicit incident, not a silent retry.
        access_path = Path(root)/'oot-access.json'
        try:
            with access_path.open('xb') as stream:
                stream.write(json_bytes({'schemaVersion': 'NBA_GEN1_OOT_ACCESS_V1', 'selection': selection_ref,
                    'accessAuthorizedAtUtc': datetime.now(timezone.utc).isoformat(), 'role': plan['roles']['oot'], **RESEARCH_FLAGS}))
        except FileExistsError:
            require(False, 'OOT was already opened; use retained evidence, do not rerun silently')
    seasons = plan['roles']['development'] + plan['roles']['validation'] + (plan['roles']['oot'] if phase == 'oot' else [])
    games, overtime = load_seasons(index, seasons)
    x, targets, audit, dispositions = features(games)
    season = plan['roles'][phase][0]
    target_x = x[x.season == season].sort_values(['scheduled_tipoff_utc', 'game_id'])
    target = targets.set_index('game_id').loc[target_x.game_id].reset_index()
    require(len(target) >= 400, 'Assessment season lacks a usable common population; pilot declaration required')
    cutoff = pd.to_datetime(target.scheduled_tipoff_utc, utc=True).min()-pd.Timedelta(nanoseconds=1)
    train_x, train_y = fitting_rows(games, x, cutoff, season, plan['minimumTrainingGames'])
    ot = ot_training(overtime, train_y, cutoff)
    artifacts, ledgers = {}, {}
    for family in plan['selectionOrder']:
        setting = development_result['selectedSettings'][family]
        model = fit_model(family, setting['parameters'], train_x, train_y)
        predicted = model.predict(target_x)
        donors = get_frame(setting['residuals'])
        if phase == 'oot':
            validation_result, _ = load_pointer(root, 'validation')
            donors = pd.concat([donors, get_frame(validation_result['arms'][family]['outOfFoldResiduals'])], ignore_index=True)
        result, ledger = evaluate(root, phase+'-'+family, target, predicted, donors, ot, plan, x, development_result['paceCutpoints'])
        result.update(model=model_artifact(root, phase+'-'+family+'.joblib', model),
            preprocessing='Serialized inside the bound point-model artifact; fit only on earlier eligible training rows.',
            trainingCutoffUtc=str(cutoff), trainingGames=len(train_y),
            outOfFoldResiduals=frame_artifact(root, phase+'-'+family+'-residuals.parquet', residual_frame(target, predicted, cutoff, family)),
            residualBank=frame_artifact(root, phase+'-'+family+'-donors.parquet', donors),
            overtimeEvidence=frame_artifact(root, phase+'-'+family+'-ot-donors.parquet', ot),
            modelExplanation=model.diagnostic_coefficients)
        artifacts[family], ledgers[family] = result, ledger
    require(all(list(f.game_id) == list(ledgers['league'].game_id) for f in ledgers.values()), 'All candidates must share the same whole-game cohort')
    chosen, gates = 'league', []
    if phase == 'validation':
        for family in plan['selectionOrder'][1:]:
            result = advancement_gate(ledgers[chosen], ledgers[family], plan)
            gates.append({'reference': chosen, 'candidate': family, **result})
            if result['advance']:
                chosen = family
    else:
        chosen = selected['lockedFamily']
    record = {'schemaVersion': 'NBA_GEN1_SEASON_ASSESSMENT_V1', 'role': phase, 'createdAtUtc': datetime.now(timezone.utc).isoformat(),
        'declaration': plan_ref, 'developmentFreeze': dev_ref, 'season': season, 'arms': artifacts,
        'lockedFamily': chosen, 'selectionGates': gates, 'calibration': 'DISABLED', 'blend': 'DISABLED',
        'commonGames': len(target), 'featureAudit': immutable_json(root, phase+'-feature-audit.json', audit),
        'features': frame_artifact(root, phase+'-features.parquet', x),
        'unsupported': frame_artifact(root, phase+'-unsupported.parquet', dispositions[dispositions.season == season]),
        'pairedVsLeague': {f: {metric: paired_interval(ledgers['league'], ledgers[f], metric) for metric in SCORE_COLUMNS} for f in plan['selectionOrder'][1:]},
        'ootUsedForSelection': False, 'authority': RESEARCH_FLAGS}
    bound = finish(root, phase, record)
    if phase == 'validation':
        finish(root, 'selection', {'schemaVersion': 'NBA_GEN1_LOCKED_SELECTION_V1', 'frozenAtUtc': datetime.now(timezone.utc).isoformat(),
            'lockedFamily': chosen, 'parameters': development_result['selectedSettings'][chosen]['parameters'],
            'validation': bound, 'declaration': plan_ref, 'ootOpened': False, 'calibrationEnabled': False,
            'blendEnabled': False, 'selectedBy': 'Joint energy effect and whole-game paired gate, stability and proper-score/distribution guardrails; simplest passing configuration.', **RESEARCH_FLAGS})
    render_report(root, record)
    return bound


def refit(root):
    plan, plan_ref, index = context(root)
    selection, selection_ref = load_pointer(root, 'selection')
    oot, oot_ref = load_pointer(root, 'oot')
    require(not (Path(root)/'refit.json').exists(), 'Refit already retained')
    games, overtime = load_seasons(index, sum(plan['roles'].values(), []))
    x, _, audit, dispositions = features(games)
    cutoff = datetime.now(timezone.utc).isoformat()
    season = max(sum(plan['roles'].values(), []))+1
    train_x, labels = fitting_rows(games, x, cutoff, season, plan['minimumTrainingGames'])
    family = selection['lockedFamily']
    model = fit_model(family, selection['parameters'], train_x, labels)
    donors = pd.concat([get_frame(oot['arms'][family]['residualBank']), get_frame(oot['arms'][family]['outOfFoldResiduals'])], ignore_index=True)
    donors = donors[pd.to_datetime(donors.source_available_at_utc, utc=True) < pd.Timestamp(cutoff)]
    ot = ot_training(overtime, labels, cutoff)
    require((pd.to_datetime(donors.point_training_cutoff_utc, utc=True) < pd.to_datetime(donors.scheduled_tipoff_utc, utc=True)).all(), 'Residual model training did not precede donor season')
    model_ref = model_artifact(root, 'nba-gen1-refit.joblib', model)
    residual_ref = frame_artifact(root, 'refit-chronological-residuals.parquet', donors)
    _, dev_ref = load_pointer(root, 'development')
    _, validation_ref = load_pointer(root, 'validation')
    configuration_id = 'nba-gen1-'+family+'-'+selection_ref['sha256']
    residual_receipt = immutable_json(root, 'refit-residual-receipt.json', {
        'schemaVersion': 'NBA_GEN1_CHRONOLOGICAL_RESIDUAL_RECEIPT_V1',
        'residualType': 'CHRONOLOGICAL_OUT_OF_FOLD_ACTUAL_MINUS_PREDICTED', 'population': residual_ref,
        'sourceIndexSha256': plan['sourceIndex']['sha256'], 'modelConfigurationIdentity': configuration_id,
        'allTrainingBeforeDonorTipoff': True, 'allFeatureHistoryBeforeDonorTipoff': True,
        'foldEvidence': [dev_ref, validation_ref, oot_ref]})
    return finish(root, 'refit', {'schemaVersion': 'NBA_GEN1_POST_OOT_RESEARCH_REFIT_V1',
        'createdAtUtc': datetime.now(timezone.utc).isoformat(), 'sourceCutoffUtc': cutoff, 'selection': selection_ref,
        'originalOotAssessment': oot_ref, 'declaration': plan_ref, 'family': family, 'parameters': selection['parameters'],
        'model': model_ref, 'featureContract': feature_contract(),
        'featureContractArtifact': immutable_json(root, 'fitted-feature-contract.json', feature_contract()),
        'modelConfigurationIdentity': configuration_id, 'modelTrainingIdentitySha256': model.training_identity_sha256,
        'residualReceipt': residual_receipt,
        'trainingFeatures': frame_artifact(root, 'refit-training-features.parquet', train_x),
        'featureAudit': immutable_json(root, 'refit-feature-audit.json', audit),
        'residuals': residual_ref,
        'overtimeEvidence': frame_artifact(root, 'refit-ot-donors.parquet', ot),
        'completeThroughSeason': season-1, 'futureForecastPublished': False, **RESEARCH_FLAGS})


def render_report(root, result):
    lines = [f"NBA Gen 1 {result['role']} — season {result['season']}", '',
        f"Common observed games: {result['commonGames']}. Locked family: {result['lockedFamily']}. NBA remains research-only and unfunded.", '',
        '| Model | Energy | Log loss | Binary Brier | Home/away CRPS | Total/margin CRPS | Home/away MAE | Total/margin MAE |',
        '|---|---:|---:|---:|---|---|---|---|']
    for family, arm in result['arms'].items():
        m = arm['scores']['overall']['metrics']
        pair = lambda a,b: f'{m[a]:.5f}/{m[b]:.5f}'
        lines.append(f"| {family} | {m['energy']:.6f} | {m['logLoss']:.6f} | {m['binaryBrier']:.6f} | {pair('homeCRPS','awayCRPS')} | {pair('totalCRPS','marginCRPS')} | {pair('homeMAE','awayMAE')} | {pair('totalMAE','marginMAE')} |")
    lines += ['', 'All detailed season, early-support, rest, back-to-back, pace and density results, reliability bins, 50/80/90% interval coverage and 1/99% tail exceedances are retained in the bound JSON assessment. These groups localize error and do not authorize specialists.',
        'Paired uncertainty resamples calendar-week clusters of observed games. Simulation MCSE is numerical precision only. Calibration and blending were disabled before results.',
        'Opponent-adjusted team box histories omit injuries, expected starters, lineups, player strength, referees, travel and sportsbook information. Source revisions enter a target only after authenticated availability; missing snapshots never receive invented clocks.',
        'The empirical overtime resolution rule applies to ties in a full-game residual population; its activation and changes to means/win probabilities are retained per game. It is not claimed to be a possession-level overtime model.']
    artifact(root, result['role']+'-RESULTS.md', ('\n'.join(lines)+'\n').encode())
