"""Report the single frozen NBA close-score comparison; never fit or simulate.

This entry point requires the completed six-season run receipt before opening
score tables. It joins the candidate to the retained paired baseline, checks
the original cohort and invariant metrics, and applies the declared weekly
paired bootstrap. All seasons are reused Category A research evidence.
"""
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

from server.sports_nba_gen1.authority import json_bytes, reference, verified_bytes

DEFAULT = ROOT / 'outputs/nba-gen1-close-score-v1/completed'
EXPECTED_COHORT_SHA = 'ad88cc9387186757be06c55111bcfb160ab87022565fbe2ef85a832ff2e4f58f'
BOOTSTRAP_METRICS = ['energy', 'home_crps', 'away_crps', 'margin_crps',
                     'home_mae', 'away_mae', 'margin_mae']
PROPER_METRICS = BOOTSTRAP_METRICS + ['total_crps', 'total_mae', 'log_loss', 'binary_brier']
LEVELS = (50, 80, 90)
VARIABLES = ('home', 'away', 'total', 'margin')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    raw = value.encode('utf-8') if isinstance(value, str) else json_bytes(value)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists() or path.read_bytes() == raw, 'Refusing to replace evidence: ' + str(path))
    path.write_bytes(raw)
    return reference(path)


def paired_uncertainty(baseline, candidate):
    """Exact paired-game differences, resampling whole ISO calendar weeks."""
    require(len(baseline) > 0 and baseline.index.equals(candidate.index), 'Matched nonempty cohort required')
    require(baseline.game_date.equals(candidate.game_date), 'Paired game dates changed')
    difference = candidate[BOOTSTRAP_METRICS].to_numpy(float) - baseline[BOOTSTRAP_METRICS].to_numpy(float)
    require(np.isfinite(difference).all(), 'Nonfinite scoring difference')
    labels = pd.to_datetime(baseline.game_date).dt.strftime('%G-%V')
    weeks, indices = np.unique(labels, return_inverse=True)
    sums = np.zeros((len(weeks), len(BOOTSTRAP_METRICS)), dtype=float)
    counts = np.zeros(len(weeks), dtype=np.int64)
    np.add.at(sums, indices, difference)
    np.add.at(counts, indices, 1)
    selected = np.random.default_rng(731201).integers(len(weeks), size=(2000, len(weeks)))
    sampled = sums[selected].sum(axis=1) / counts[selected].sum(axis=1)[:, None]
    return {'direction': 'close_score minus saved paired baseline; negative improves proper scores/errors',
            'games': len(baseline), 'calendarWeeks': len(weeks), 'replicates': 2000, 'seed': 731201,
            'qualification': 'Observed games are assessment units. Week blocks approximate dependence; these are reused historical comparisons, not untouched confirmation. Simulation precision is not model uncertainty.',
            'metrics': {metric: {'difference': float(difference[:, i].mean()),
                                 'interval95': np.quantile(sampled[:, i], [.025, .975]).tolist()}
                        for i, metric in enumerate(BOOTSTRAP_METRICS)}}


def summary(baseline, candidate):
    require(baseline.index.equals(candidate.index) and len(baseline) > 0, 'Summary requires matched games')
    observed = abs(baseline.actual_home - baseline.actual_away)
    arms = {}
    for name, frame in (('baseline', baseline), ('close_score', candidate)):
        intervals = {variable: {str(level): {
            'coverage': float(frame[f'{variable}_{level}_coverage'].mean()),
            'width': float(frame[f'{variable}_{level}_width'].mean())}
            for level in LEVELS} for variable in VARIABLES}
        arms[name] = {'metrics': {metric: float(frame[metric].mean()) for metric in PROPER_METRICS},
                      'intervals': intervals,
                      'onePointProbability': float(frame.one_point_probability.mean()),
                      'homeWinMcseMean': float(frame.home_win_mcse.mean())}
    bins = []
    for k in range(1, 9):
        base_p = float(candidate[f'baseline_abs_margin_{k}_probability'].mean())
        changed_p = float(candidate[f'abs_margin_{k}_probability'].mean())
        actual_p = float((observed == k).mean())
        bins.append({'absoluteMargin': k, 'baselineProbability': base_p,
                     'candidateProbability': changed_p, 'observedFrequency': actual_p,
                     'baselineMinusObserved': base_p - actual_p,
                     'candidateMinusObserved': changed_p - actual_p})
    parity = {}
    for name, margins in (('odd', (1, 3, 5, 7)), ('even', (2, 4, 6, 8)), ('all_close', tuple(range(1, 9)))):
        selected = [bins[k-1] for k in margins]
        bp = sum(item['baselineProbability'] for item in selected)
        cp = sum(item['candidateProbability'] for item in selected)
        op = sum(item['observedFrequency'] for item in selected)
        parity[name] = {'absoluteMargins': list(margins), 'baselineProbability': bp,
                        'candidateProbability': cp, 'observedFrequency': op,
                        'candidateMinusObserved': cp - op,
                        'probabilityChange': cp - bp,
                        'qualification': 'Within-parity transport preserves this close mass; it cannot repair a wrong aggregate close-frequency or parity mixture.'}
    team_tails = {}
    for variable in ('home', 'away'):
        team_tails[variable] = {}
        for quantile in (.01, .05, .95, .99):
            threshold_column = f'{variable}_q{quantile:g}'
            outside_column = f'{variable}_outside{quantile:g}'
            values = {name: {'meanThreshold': float(frame[threshold_column].mean()),
                             'outsideFrequency': float(frame[outside_column].mean())}
                      for name, frame in (('baseline', baseline), ('candidate', candidate))}
            team_tails[variable][f'{quantile:g}'] = {
                'quantile': quantile,
                'outsideDefinition': 'actual score strictly below threshold' if quantile < .5 else 'actual score strictly above threshold',
                **values,
                'candidateMinusBaseline': {key: values['candidate'][key] - values['baseline'][key]
                                            for key in ('meanThreshold', 'outsideFrequency')}}
    return {'games': len(baseline), 'configurations': arms,
            'differences': {metric: float((candidate[metric] - baseline[metric]).mean()) for metric in PROPER_METRICS},
            'actualOnePointFrequency': float((observed == 1).mean()),
            'bins': bins, 'residualCloseMassGaps': parity, 'teamScoreTailDiagnostics': team_tails,
            'supportedGames': int(candidate.correction_supported.sum()),
            'fallbackGames': int((~candidate.correction_supported.astype(bool)).sum())}


def _bound_inputs(root):
    """Check completion, physical bindings and code before outcome table reads."""
    require((root / 'run-receipt.json').is_file(), 'Frozen six-season run is not complete; score access refused')
    method = json.loads((root / 'method-freeze.json').read_bytes())
    run = json.loads((root / 'run-receipt.json').read_bytes())
    require(method['schema'] == 'NBA_GEN1_CLOSE_SCORE_METHOD_FREEZE_V1', 'Wrong frozen method')
    require(method['cohort']['eligibleGames'] == 7009 and method['cohort']['eligibleIdentitySha256'] == EXPECTED_COHORT_SHA,
            'Original 7009-game cohort binding changed')
    require(run['games'] == 7009 and run['candidateDraws'] == 7009 * method['drawCount'], 'Incomplete draw population')
    require(run['originalBaselineIndexAndBoundArtifactsUnchanged'] is True and run['originalCohortExact'] is True,
            'Original baseline preservation was not verified')
    for bound in method['code'] + [method['parent'], method['parentMethod'], method['parentCohort'], method['developmentDiagnosis']]:
        verified_bytes(bound)
    base = Path(method['parent']['path']).parent
    original_index = json.loads(verified_bytes(method['parent']))
    for bound in original_index['artifacts'] + original_index['code']:
        verified_bytes(bound)
    cohort = json.loads(verified_bytes(method['parentCohort']))
    expected_ids = [item['game_id'] for item in cohort['eligible']]
    require(hashlib.sha256('\n'.join(expected_ids).encode()).hexdigest() == EXPECTED_COHORT_SHA,
            'Cohort identity bytes changed')
    receipts = []
    for year in range(2021, 2027):
        receipt_path = root / 'assessment' / str(year) / 'receipt.json'
        require(receipt_path.is_file(), 'Missing completed assessment season ' + str(year))
        receipt = json.loads(receipt_path.read_bytes())
        require(receipt['frozenMethod'] == reference(root / 'method-freeze.json'), 'Season used a different method')
        require(receipt['allRetainedCountDigestsVerified'] is True, 'Candidate count accounting incomplete')
        for bound in receipt['artifacts']:
            verified_bytes(bound)
        require(receipt['games'] == method['cohort']['seasons'][str(year)], 'Season cohort changed')
        receipts.append(reference(receipt_path))
    require(sum(json.loads(verified_bytes(r))['games'] for r in receipts) == 7009, 'Season coverage incomplete')
    for name in ('kernel-artifacts.json', 'frozen-development-kernel.json'):
        require((root / name).is_file(), 'Missing retained component: ' + name)
    mechanism_path = root / 'development-mechanism.json'
    require(mechanism_path.is_file(), 'Missing bound Development mechanism receipt')
    mechanism = json.loads(mechanism_path.read_bytes())
    require(mechanism['schema'] == 'NBA_CLOSE_SCORE_DEVELOPMENT_MECHANISM_V1' and mechanism['games'] == 3338,
            'Different Development mechanism population')
    for bound in mechanism['boundOriginalSupportEffects']:
        verified_bytes(bound)
    return method, run, base, expected_ids, receipts


def load_matched(root):
    method, run, base, expected_ids, receipts = _bound_inputs(root)
    original, changed, effects = [], [], []
    for year in range(2021, 2027):
        old = pd.read_parquet(base / 'assessment' / str(year) / 'scores.parquet')
        original.append(old[old.configuration == 'paired'])
        changed.append(pd.read_parquet(root / 'assessment' / str(year) / 'scores.parquet'))
        effects.append(pd.read_parquet(root / 'assessment' / str(year) / 'transformations.parquet'))
    baseline = pd.concat(original, ignore_index=True).sort_values(['game_date', 'game_id']).set_index('game_id', drop=False)
    candidate = pd.concat(changed, ignore_index=True).sort_values(['game_date', 'game_id']).set_index('game_id', drop=False)
    effects = pd.concat(effects, ignore_index=True).set_index('game_id', drop=False).loc[expected_ids]
    for name, frame in (('baseline', baseline), ('candidate', candidate), ('effects', effects)):
        require(frame.index.is_unique and list(frame.index) == expected_ids, name + ' differs from exact frozen cohort/order')
    require((candidate.configuration == 'close_score').all(), 'Unexpected candidate configuration')
    require((baseline.draw_count == method['drawCount']).all() and (candidate.draw_count == method['drawCount']).all(),
            'Original denominator changed')
    identity_columns = ['game_date', 'game_index', 'season_end', 'home_team_code', 'away_team_code',
                        'actual_home', 'actual_away', 'model_sha256', 'bank_id', 'donors', 'latest_donor_date',
                        'ridge_expected_home', 'ridge_expected_away', 'either_season_opener', 'both_ordinary_rest_supported']
    for column in identity_columns:
        require(baseline[column].equals(candidate[column]), 'Matched identity/input/final changed: ' + column)
    invariant_columns = ['draw_count', 'home_win_probability', 'away_win_probability', 'tie_probability',
                         'log_loss', 'binary_brier', 'correct_pick', 'home_win_mcse']
    invariant_columns += sorted(column for column in baseline.columns if column.startswith('total_'))
    for column in invariant_columns:
        require(baseline[column].equals(candidate[column]), 'Per-game invariant changed: ' + column)
    for flag in ('all_draw_totals_preserved', 'all_draw_winners_preserved', 'outer_pairs_preserved'):
        require(effects[flag].eq(True).all(), 'Draw-level invariant absent: ' + flag)
    require(np.array_equal(baseline.one_point_probability, candidate.baseline_abs_margin_1_probability), 'Baseline one-point binding changed')
    require(np.array_equal(candidate.one_point_probability, candidate.abs_margin_1_probability), 'Candidate one-point mass does not reconcile')
    require(candidate.correction_supported.equals(effects.correction_supported), 'Support disposition differs between artifacts')
    require(((effects.calibration_games == 0) | (effects.calibration_latest_date < effects.game_date)).all(), 'Kernel chronology is not strictly earlier')
    return method, run, baseline, candidate, effects, receipts, invariant_columns


def transformation_summary(effects, candidate):
    details = [json.loads(value) for value in effects.effects_json]
    for item in details:
        for flag in ('totalsPerDrawExact', 'winnerPerDrawExact', 'outerMarginsExact', 'inputUnmodified', 'noDrawDropped'):
            require(item[flag] is True, 'Incomplete transport verification: ' + flag)
        require(item['drawCount'] == 10000 and item['retainedDrawCount'] == 10000, 'Transport lost draw mass')
    n = len(effects)
    changed_draws = int(effects.changed_draw_count.sum())
    fallback = ~candidate.correction_supported.astype(bool)
    require((effects.loc[fallback, 'changed_draw_count'] == 0).all(), 'Fallback changed baseline pairs')
    return {'games': n, 'supportedGames': int((~fallback).sum()), 'exactBaselineFallbackGames': int(fallback.sum()),
            'affectedGames': int((effects.changed_draw_count > 0).sum()), 'retainedDraws': n * 10000,
            'changedDraws': changed_draws, 'changedDrawFraction': changed_draws / (n * 10000),
            'homeMeanChange': float(effects.home_mean_change.mean()),
            'awayMeanChange': float(effects.away_mean_change.mean()),
            'meanAbsoluteHomeMeanChange': float(effects.home_mean_change.abs().mean()),
            'maximumAbsoluteHomeMeanChange': float(effects.home_mean_change.abs().max()),
            'maximumAbsoluteAwayMeanChange': float(effects.away_mean_change.abs().max()),
            'maximumAbsoluteIndividualTeamScoreChange': int(effects.max_absolute_team_score_change.max()),
            'nonnegativeSupportFallbackDraws': sum(item['nonnegativeSupportFallbackDrawCount'] for item in details),
            'unseenSourceBinIdentityDraws': sum(item['unseenSourceBinIdentityDrawCount'] for item in details),
            'populationOrder': 'Lexicographic retained HOME/AWAY cell plus replica, not original simulation order',
            'uncertainty': 'Reported sample MCSE describes numerical sampling precision only; no bound on input/model error.'}


def markdown(result, reproduce_command=None):
    groups, decision = result['groups'], result['decision']
    mechanism = result['developmentMechanism']['means']
    text = ['# NBA Gen 1: one close-score support comparison', '',
            f"**{decision['verdict']}**. {decision['recommendation']} {decision['evidenceQualification']}", '',
            'The same 7,009 previously inspected games and 10,000 retained pairs per game are compared. '
            'Negative candidate-minus-baseline proper-score/error differences are better. '
            'This is Category A finalized historical reconstruction, not a new OOT or prospective result. '
            'The saved paired baseline was unpublished research; the published point/Elo forecast has drawCount=0 and remains unchanged.', '',
            f"Development already had excess one-point mass before tie projection: rounded simulations assigned {mechanism['rounded__one_point_fraction']:.2%}, versus {groups['development']['actualOnePointFrequency']:.2%} observed; projecting {mechanism['rounded__tie_fraction']:.2%} rounded ties to adjacent untied scores raised final one-point mass to {mechanism['final__one_point_fraction']:.2%}.", '',
            '| Cohort | Games | Arm | Energy | Margin CRPS | Home CRPS | Away CRPS | One-point predicted / actual |',
            '|---|---:|---|---:|---:|---:|---:|---:|']
    for key, label in (('all', 'All'), ('development', 'Development 2021–23'), ('reused_2024_2026', 'Reused 2024–26')):
        group = groups[key]
        for arm, arm_label in (('baseline', 'Saved paired'), ('close_score', 'Close-score')):
            value = group['configurations'][arm]
            metric = value['metrics']
            text.append(f"| {label} | {group['games']:,} | {arm_label} | {metric['energy']:.5f} | {metric['margin_crps']:.5f} | {metric['home_crps']:.5f} | {metric['away_crps']:.5f} | {value['onePointProbability']:.2%} / {group['actualOnePointFrequency']:.2%} |")
    text += ['', '| Season ending | Games | Δ energy | Δ margin CRPS | One-point baseline → candidate / actual |',
             '|---|---:|---:|---:|---:|']
    for season in range(2021, 2027):
        group = groups[f'season_{season}']
        a, b = group['configurations']['baseline'], group['configurations']['close_score']
        text.append(f"| {season} | {group['games']:,} | {group['differences']['energy']:+.5f} | {group['differences']['margin_crps']:+.5f} | {a['onePointProbability']:.2%} → {b['onePointProbability']:.2%} / {group['actualOnePointFrequency']:.2%} |")
    text += ['', 'Paired 95% intervals use 2,000 ISO-calendar-week bootstrap resamples (seed 731201).']
    for key, label in (('all', 'All'), ('development', 'Development'), ('reused_2024_2026', 'Reused 2024–26')):
        uncertainty = result['pairedUncertainty'][key]['metrics']
        details = []
        for metric, title in (('energy', 'energy'), ('margin_crps', 'margin CRPS')):
            value = uncertainty[metric]
            details.append(f"Δ {title} {value['difference']:+.5f} [{value['interval95'][0]:+.5f}, {value['interval95'][1]:+.5f}]")
        text.append(f"{label}: {'; '.join(details)}.")
    text += ['', 'Reused 2024–26 interval coverage, with average width in points in parentheses:', '',
             '| Distribution | 50% baseline → candidate | 80% baseline → candidate | 90% baseline → candidate |',
             '|---|---:|---:|---:|']
    reused = groups['reused_2024_2026']
    for variable in VARIABLES:
        cells = []
        for level in LEVELS:
            a = reused['configurations']['baseline']['intervals'][variable][str(level)]
            b = reused['configurations']['close_score']['intervals'][variable][str(level)]
            cells.append(f"{a['coverage']:.1%} ({a['width']:.2f}) → {b['coverage']:.1%} ({b['width']:.2f})")
        text.append(f"| {variable.title()} | " + ' | '.join(cells) + ' |')
    effect = result['transformations']
    gaps = reused['residualCloseMassGaps']
    worst_tail = max(((variable, quantile, value) for variable, tails in reused['teamScoreTailDiagnostics'].items()
                      for quantile, value in tails.items()),
                     key=lambda item: abs(item[2]['candidateMinusBaseline']['outsideFrequency']))
    tail_variable, tail_quantile, tail_value = worst_tail
    text += ['',
             f"The component ran on {effect['supportedGames']:,} games; {effect['exactBaselineFallbackGames']:,} retained the exact baseline because calibration prerequisites were unmet. "
             f"It changed {effect['changedDraws']:,}/{effect['retainedDraws']:,} pairs ({effect['changedDrawFraction']:.2%}) across {effect['affectedGames']:,} games. "
             f"Mean absolute game-level home-mean change was {effect['meanAbsoluteHomeMeanChange']:.4f} points; maximum {effect['maximumAbsoluteHomeMeanChange']:.4f}. "
             f"Maximum individual team-score change was {effect['maximumAbsoluteIndividualTeamScoreChange']} points. "
             f"Draw-level nonnegative-support fallbacks: {effect['nonnegativeSupportFallbackDraws']:,}.", '',
             'Every draw total and winner, all pairs with absolute margin above 8, and the full denominator were preserved. '
             'Consequently winner probabilities, picks, log loss, Brier, every total score/quantile/coverage and total tail mass remain exactly unchanged per game. '
             'This component cannot improve winner predictions or totals. Original paired count hashes and artifacts remain unchanged.', '',
             'A preserved first execution stopped on floating-point summation-order roundoff in total MCSE; the successor verifies identical draw totals and total mass, checks recomputed summaries within 1e-12, and carries the original numerical total summaries unchanged, with the frozen kernel, radius and decision gate preserved.', '',
             f"Across retained home/away 1%, 5%, 95% and 99% quantile checks, the largest absolute change in reused 2024–26 outside frequency was {100 * abs(tail_value['candidateMinusBaseline']['outsideFrequency']):.3f} percentage points "
             f"({tail_variable}, quantile {tail_quantile}; {tail_value['baseline']['outsideFrequency']:.3%} → {tail_value['candidate']['outsideFrequency']:.3%}); all threshold means and outside-frequency changes are retained in JSON.", '',
             f"Residual reused close-mass gaps remain: odd margins 1/3/5/7 {gaps['odd']['candidateProbability']:.2%} predicted versus {gaps['odd']['observedFrequency']:.2%} observed; "
             f"even margins 2/4/6/8 {gaps['even']['candidateProbability']:.2%} versus {gaps['even']['observedFrequency']:.2%}; "
             f"all margins 1–8 {gaps['all_close']['candidateProbability']:.2%} versus {gaps['all_close']['observedFrequency']:.2%}. "
             'Conditional transport preserves these masses, so their discrepancies remain uncorrected.', '',
             'Radius 8 was chosen at the first observed-versus-simulated close-margin cumulative crossing in Development, before later-season comparison. '
             'Development kernels use strictly earlier dates, at least 200 calibration games and at least 20 observed close finishes per parity; insufficient support gives exact fallback. '
             'The post-2023 kernel uses all 3,338 eligible Development games only. '
             'Underlying source history spans 2019–2026; assessment targets span 2021–2026. '
             'This does not repair missing historical revision clocks, certify unrecorded pregame information, or establish prospective calibration. '
             'No point model, original residual sampler, winner model, total tail, provider collection, forecast publication or authority was changed.', '',
             'The JSON assessment retains all frozen-group proper scores, home/away/margin paired uncertainty, interval widths, absolute-margin bins 1–8 and source bindings. '
             'Games are the assessment units. Simulation MCSE is numerical precision, not a bound on model error.']
    if reproduce_command:
        text += ['', 'Read-only reproduction:', '', '```powershell', reproduce_command, '```']
    return '\n'.join(text) + '\n'


def report(root, reproduce_command=None):
    root = Path(root).resolve()
    output_names = ('assessment.json', 'results-compact.json', 'REPORT.md')
    if any((root / name).exists() for name in output_names):
        require(all((root / name).is_file() for name in output_names), 'Partial immutable report exists; preserve it before recovery')
        existing = json.loads((root / 'assessment.json').read_bytes())
        verified_bytes(existing['reportCode'])
        for bound in existing['inputs']:
            verified_bytes(bound)
        for bound in existing['reportArtifacts']:
            verified_bytes(bound)
        return {'reusedImmutableReport': True, 'decision': existing['decision'],
                'artifacts': [reference(root / name) for name in output_names]}
    method, run, baseline, candidate, effects, receipts, invariant_columns = load_matched(root)
    masks = {'all': np.ones(len(baseline), dtype=bool),
             'development': baseline.season_end <= 2023, 'reused_2024_2026': baseline.season_end >= 2024,
             'ordinary_rest': baseline.both_ordinary_rest_supported.astype(bool),
             'unavailable_rest': ~baseline.both_ordinary_rest_supported.astype(bool),
             'season_openers': baseline.either_season_opener.astype(bool)}
    masks.update({f'season_{year}': baseline.season_end == year for year in range(2021, 2027)})
    groups = {key: summary(baseline.loc[mask], candidate.loc[mask]) for key, mask in masks.items() if np.any(mask)}
    uncertainty = {key: paired_uncertainty(baseline.loc[masks[key]], candidate.loc[masks[key]])
                   for key in ('all', 'development', 'reused_2024_2026')}
    group = groups['reused_2024_2026']
    actual = group['actualOnePointFrequency']
    base_error = abs(group['configurations']['baseline']['onePointProbability'] - actual)
    changed_error = abs(group['configurations']['close_score']['onePointProbability'] - actual)
    checks = {'onePointAbsoluteFrequencyErrorDecreased': changed_error < base_error,
              'energyDidNotWorsen': group['differences']['energy'] <= 0,
              'marginCrpsDidNotWorsen': group['differences']['margin_crps'] <= 0,
              'supportMassTotalsWinnerInvariants': True}
    passed = all(checks.values())
    crossing_zero = [metric for metric in ('energy', 'margin_crps')
                     if uncertainty['reused_2024_2026']['metrics'][metric]['interval95'][0] <= 0
                     <= uncertainty['reused_2024_2026']['metrics'][metric]['interval95'][1]]
    evidence_qualification = (
        'The reused 95% interval includes zero for ' + ', '.join(crossing_zero) +
        '; passing a directional point-estimate gate does not establish a stable or meaningful predictive gain.'
        if crossing_zero else
        'The directional point-estimate gate and this one reused comparison do not establish a stable or meaningful prospective gain.')
    decision = {'verdict': 'SUPPORTED_FURTHER_RESEARCH' if passed else 'NEEDS_CORRECTION_RETAIN_BASELINE',
                'gate': 'Frozen descriptive reused2024-2026 rule; no requirement that bootstrap intervals exclude zero',
                'checks': checks, 'baselineOnePointAbsoluteFrequencyError': base_error,
                'candidateOnePointAbsoluteFrequencyError': changed_error,
                'promotion': False, 'evidenceQualification': evidence_qualification,
                'reusedPrimaryOrMarginIntervalsIncludingZero': crossing_zero,
                'recommendation': ('Leave the published point/Elo forecast unchanged and keep this corrected joint distribution research-only; no new future study or consumer handoff is opened.'
                                   if passed else 'Preserve the existing paired distribution as a research reference and leave the published point/Elo forecast unchanged; this correction did not pass its declared descriptive gate and should not advance.')}
    result = {'schema': 'NBA_GEN1_CLOSE_SCORE_MATCHED_ASSESSMENT_V1',
              'createdAtUtc': datetime.now(timezone.utc).isoformat(),
              'method': reference(root / 'method-freeze.json'), 'reportCode': reference(Path(__file__)),
              'inputs': [reference(root / name) for name in ('method-freeze.json', 'development-diagnosis.json', 'development-mechanism.json',
                         'kernel-artifacts.json', 'frozen-development-kernel.json', 'run-receipt.json')] + receipts,
              'cohort': method['cohort'], 'groups': groups, 'pairedUncertainty': uncertainty,
              'developmentMechanism': json.loads((root / 'development-mechanism.json').read_bytes()),
              'transformations': transformation_summary(effects, candidate), 'decision': decision,
              'invariants': {'checkedPerGameColumns': invariant_columns, 'allExact': True,
                             'drawLevelTotalsWinnersOuterPairsVerifiedByBoundRunner': True,
                             'retainedCountDigestsVerifiedByBoundRunner': True,
                             'originalBaselineUnchanged': run['originalBaselineIndexAndBoundArtifactsUnchanged']},
              'scope': 'One Development-selected radius8 parity transport; same7009 reused Category A games. No model refit, new provider data, original forecast changes, prospective claim, integration or promotion.'}
    compact = {'schema': 'NBA_GEN1_CLOSE_SCORE_COMPACT_RESULTS_V1', 'createdAtUtc': result['createdAtUtc'],
               'method': result['method'], 'direction': 'candidate minus baseline; lower proper scores/errors improve',
               'decision': decision, 'rows': [{'group': key, 'games': group['games'],
                    'baseline': group['configurations']['baseline']['metrics'],
                    'candidate': group['configurations']['close_score']['metrics'], 'difference': group['differences'],
                    'onePointBaseline': group['configurations']['baseline']['onePointProbability'],
                    'onePointCandidate': group['configurations']['close_score']['onePointProbability'],
                    'onePointObserved': group['actualOnePointFrequency']}
                    for key, group in groups.items() if key in ('all', 'development', 'reused_2024_2026') or key.startswith('season_')]}
    compact_ref = save(root / 'results-compact.json', compact)
    report_ref = save(root / 'REPORT.md', markdown(result, reproduce_command))
    result['reportArtifacts'] = [compact_ref, report_ref]
    assessment_ref = save(root / 'assessment.json', result)
    return {'decision': decision, 'artifacts': [assessment_ref, compact_ref, report_ref]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=DEFAULT)
    parser.add_argument('--reproduce-command', help='Already verified read-only replay command, documented without executing it')
    args = parser.parse_args()
    print(json.dumps(report(args.root, args.reproduce_command), indent=2))
