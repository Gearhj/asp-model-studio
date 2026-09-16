"""Summarize fixed retrospective V18 sidecars; never run models or acquire data."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_modeling.metrics import PA_CLASS_ORDER
from server.sports_current_statcast.mlb_starter_duration_quarantine import LEDGER, final_oot_eligible_key_mask
from server.sports_silver.canonical_ids import canonical_game_id

OUT = ROOT / 'outputs/mlb-v18-population-diagnostics-v1'
CASES = ('824630', '823496', '824870')
SIDES = ('AWAY', 'HOME')
OBSERVED_SHA = '873027ff0eea7c5306ee7a54d394986359bce929aa6ab64d0f4c02d3db0d3363'
ALIASES = {f'BASE_OCCUPANCY_{k}_CONTINUING': f'BASE_OCCUPANCY_{k}' for k in ('INCREASE', 'DECREASE', 'UNCHANGED')}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ref(path):
    p = Path(path).resolve(); b = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(b).hexdigest(), 'bytes': len(b)}


def verified_bytes(reference):
    p = Path(reference['path']).resolve(); b = p.read_bytes()
    require(hashlib.sha256(b).hexdigest() == reference['sha256'] and len(b) == reference['bytes'], 'Reference checksum/length mismatch: ' + str(p))
    return b


def verified_json(reference):
    return json.loads(verified_bytes(reference))


def guard(case):
    require(all(final_oot_eligible_key_mask([case['gameId'], case['sourceGameId'], canonical_game_id(int(case['sourceGameId']))])), 'Whole-game quarantine failed')


def distribution(values, actual=None):
    """Inclusive empirical tails over saved draws; no inferential test or smoothing."""
    values = np.asarray(values, dtype=np.float64)
    require(values.ndim == 1 and np.isfinite(values).all(), 'Distribution must be a finite vector')
    if not len(values):
        return {'draws': 0, 'actual': actual, 'mean': None, 'p05': None, 'p50': None, 'p95': None,
            'inclusiveLowerTail': None, 'inclusiveUpperTail': None}
    p05, p50, p95 = np.quantile(values, [.05, .5, .95], method='linear')
    return {'draws': len(values), 'actual': actual, 'mean': float(values.mean()),
        'p05': float(p05), 'p50': float(p50), 'p95': float(p95),
        'inclusiveLowerTail': None if actual is None else float(np.mean(values <= actual)),
        'inclusiveUpperTail': None if actual is None else float(np.mean(values >= actual))}


def rates(numerators, denominators, actual_numerator, actual_denominator):
    numerators = np.asarray(numerators, dtype=np.float64); denominators = np.asarray(denominators, dtype=np.float64)
    require(numerators.shape == denominators.shape and numerators.ndim == 1, 'Rate vectors differ')
    mask = denominators > 0
    actual = actual_numerator / actual_denominator if actual_denominator else None
    return {'perDrawRatioDistribution': distribution(numerators[mask] / denominators[mask], actual),
        'ratioOfSums': float(numerators.sum() / denominators.sum()) if denominators.sum() else None,
        'undefinedZeroDenominatorDraws': int((~mask).sum()),
        'definition': 'Per-draw ratios are summarized before averaging; ratioOfSums is separately exposure-weighted and generally differs.'}


def load_population(sidecar, enriched_population, enriched_counters):
    require(sidecar['classification'] == 'RETROSPECTIVE_REPRODUCTION_AFTER_OBSERVED_RESULTS', 'Only retrospective declared cases may be compared')
    require(not sidecar['newForecastCreated'] and not sidecar['originalForecastModified'], 'Forecast authority changed')
    require(sidecar['invariance']['mismatchedDraws'] == 0 and sidecar['invariance']['maximumAbsoluteDrawDifference'] == 0, 'Draw invariance failed')
    require(all(sidecar['invariance']['drawArraysExact'].values()), 'A draw array failed invariance')
    require(all(sidecar['invariance']['summaryScalarsExact'].values()) and sidecar['invariance']['representativeTraceExact'], 'Scalar/representative-trace invariance failed')
    counters = sidecar['counters']; require(counters['simulationCount'] == 5000 and counters['accounting']['allPassed'], 'Counter accounting not passed')
    require(all(counters['accounting']['checks'].values()), 'Counter check failed')
    require(counters['definitions']['teamOrder'] == list(SIDES) and counters['definitions']['paClassOrder'] == list(PA_CLASS_ORDER), 'Array order mismatch')
    raw = verified_bytes(sidecar['population'])
    with np.load(io.BytesIO(raw), allow_pickle=False) as z:
        require(set(z.files) == set(counters['arrays']), 'Array inventory differs from saved metadata')
        parent_arrays = {name: z[name].copy() for name in z.files}
    added = {'automatic_runner_placements', 'runners_after_last_transition', 'walkoff_runner_remnants', 'censored_runner_remnants'}
    for name, value in counters.items():
        if name not in ('arrays', 'definitions'):
            require(enriched_counters.get(name) == value, 'Enrichment changed original counter metadata: ' + name)
    require({k: v for k, v in enriched_counters['definitions'].items() if k != 'boundaries'} == counters['definitions'], 'Enrichment changed original definitions')
    boundary = enriched_counters['boundaryDerivation']
    require(boundary['allPassed'] and all(boundary['checks'].values()), 'Boundary checks did not pass')
    require(boundary['extraRandomDraws'] == boundary['simulationReruns'] == 0, 'Boundary enrichment was not passive')
    raw_enriched = verified_bytes(enriched_population)
    with np.load(io.BytesIO(raw_enriched), allow_pickle=False) as z:
        require(set(z.files) == set(parent_arrays) | added == set(enriched_counters['arrays']), 'Enriched array inventory differs')
        arrays = {name: z[name].copy() for name in z.files}
    for name, values in parent_arrays.items():
        require(enriched_counters['arrays'][name] == counters['arrays'][name] and np.array_equal(arrays[name], values), 'Enrichment changed parent array: ' + name)
    definitions = enriched_counters['definitions']
    for name, values in arrays.items():
        spec = enriched_counters['arrays'][name]
        require(list(values.shape) == spec['shape'] and str(values.dtype) == spec['dtype'], 'Array shape/dtype mismatch: ' + name)
        require(values.shape[0] == 5000 and np.isfinite(values).all(), 'Array length/nonfinite values: ' + name)
    needed = ('completed_pa', 'runs', 'outs_recorded', 'outcome_counts', 'outcome_runs', 'probability_sums',
        'starter_bf_by_inning', 'anonymous_relief_bf_by_inning', 'starter_outs_by_inning', 'anonymous_relief_outs_by_inning',
        'runs_while_starter_active', 'runs_while_anonymous_relief_active', 'starter_removal_inning', 'starter_removal_reason',
        'transition_counts', 'runners_lob_third_out', 'half_innings_started', 'half_innings_completed', 'terminal_reason',
        'non_pa_event_count', 'pa_counts', 'away_runs', 'home_runs', 'innings')
    require(all(name in arrays for name in needed), 'Required diagnostic array missing')
    completed = arrays['completed_pa']; require(completed.ndim == 3 and completed.shape[1] == 2, 'Team/inning axes differ')
    require(np.array_equal(arrays['outcome_counts'].sum(axis=-1), completed), 'Class count/PA reconciliation failed')
    require(np.allclose(arrays['probability_sums'].sum(axis=-1), completed, rtol=0, atol=1e-8), 'Probability mass/PA reconciliation failed')
    require(np.array_equal(completed.sum(axis=(1, 2)), arrays['pa_counts']), 'Total PA mismatch')
    require(np.array_equal(arrays['runs'].sum(axis=2), np.stack([arrays['away_runs'], arrays['home_runs']], axis=1)), 'Run orientation mismatch')
    require(np.array_equal(arrays['starter_bf_by_inning'] + arrays['anonymous_relief_bf_by_inning'], completed[:, ::-1]), 'Pitcher BF orientation mismatch')
    require(np.array_equal(arrays['starter_outs_by_inning'] + arrays['anonymous_relief_outs_by_inning'], arrays['outs_recorded'][:, ::-1]), 'Pitcher outs orientation mismatch')
    return arrays, definitions


def compare_game(case, observed, sidecar, arrays, definitions):
    n = arrays['completed_pa'].shape[2]
    categories = definitions['transitionCategoryOrder']
    require(len(categories) == arrays['transition_counts'].shape[3] and len(set(categories)) == len(categories), 'Transition category shape mismatch')
    rows = {}
    for t, side in enumerate(SIDES):
        actual = observed['perTeam'][side]; pa = arrays['completed_pa'][:, t].sum(axis=1)
        require(np.all(pa > 0), 'Zero full-game batting PA')
        class_counts = arrays['outcome_counts'][:, t].sum(axis=1)
        class_mass = arrays['probability_sums'][:, t].sum(axis=1)
        class_runs = arrays['outcome_runs'][:, t].sum(axis=1)
        observed_events = [e for e in observed['observedPlayBoundaries'] if e['battingSide'] == side]
        by_class = {}
        for c, name in enumerate(PA_CLASS_ORDER):
            actual_count = actual['outcome_counts'][name]
            actual_class_runs = sum(e['runs'] for e in observed_events if e['paClass'] == name)
            by_class[name] = {'actualCount': actual_count, 'actualRate': actual_count / actual['completed_pa'],
                'sampledCount': distribution(class_counts[:, c], actual_count),
                'probabilitySum': distribution(class_mass[:, c]),
                'sampledCountPerPA': rates(class_counts[:, c], pa, actual_count, actual['completed_pa']),
                'probabilitySumPerPA': rates(class_mass[:, c], pa, actual_count, actual['completed_pa']),
                'runsOnClassTransitions': distribution(class_runs[:, c], actual_class_runs),
                'runsOnClassTransitionsMeaning': 'Aggregate runs across the whole play carrying this terminal class, including within-PA runner activity; not proof that the terminal PA class alone caused those runs.'}
        run = arrays['runs'][:, t]
        modeled_removal = arrays['starter_removal_reason'][:, t] == 1
        removal_inning = arrays['starter_removal_inning'][:, t]
        require(np.all(removal_inning[~modeled_removal] == -1), 'Censored removal coordinates must be -1')
        actual_removal = actual['starterRemoval']['inning']
        metrics = {'completedPA': distribution(pa, actual['completed_pa']),
            'starterBF': distribution(arrays['starter_bf_by_inning'][:, t].sum(axis=1), actual['starter_bf']),
            'anonymousReliefBF': distribution(arrays['anonymous_relief_bf_by_inning'][:, t].sum(axis=1), actual['relief_bf']),
            'starterOuts': distribution(arrays['starter_outs_by_inning'][:, t].sum(axis=1), actual['starter_outs']),
            'anonymousReliefOuts': distribution(arrays['anonymous_relief_outs_by_inning'][:, t].sum(axis=1), actual['relief_outs']),
            'runs': distribution(run.sum(axis=1), actual['runs'] + actual['non_pa_runs']),
            'maximumInningRuns': distribution(run.max(axis=1), actual['maximumInningRuns']),
            'lateRuns7Plus': distribution(run[:, 6:].sum(axis=1), actual['lateRuns7Plus']),
            'thirdOutLOB': distribution(arrays['runners_lob_third_out'][:, t].sum(axis=1), actual['thirdOutConservationLOB']),
            'outsOnCompletedPAs': distribution(arrays['outs_recorded'][:, t].sum(axis=1), actual['outs_recorded'])}
        aggregate_classes = {
            'hits': ('SINGLE', 'DOUBLE', 'TRIPLE', 'HOME_RUN'),
            'extraBaseHits': ('DOUBLE', 'TRIPLE', 'HOME_RUN'),
            'reachClassPA': ('WALK_HBP_CI', 'SINGLE', 'DOUBLE', 'TRIPLE', 'HOME_RUN', 'OTHER_REACH'),
        }
        for name, members in aggregate_classes.items():
            counts = class_counts[:, [PA_CLASS_ORDER.index(c) for c in members]].sum(axis=1)
            actual_count = sum(actual['outcome_counts'][c] for c in members)
            metrics[name] = {**distribution(counts, actual_count),
                'classes': list(members), 'actualRate': actual_count / actual['completed_pa'],
                'perPA': rates(counts, pa, actual_count, actual['completed_pa']),
                'definition': 'Count of completed PAs in the listed fixed classes. Reach-class PA is not a baserunner count: a fielders-choice class can include an out.'}
        active_runs = {}
        for role, key in [('STARTER', 'runs_while_starter_active'), ('RELIEF', 'runs_while_anonymous_relief_active')]:
            labels = [e for e in observed['observedPlayBoundaries'] if e['pitchingSide'] == side and e['pitcherRole'] == role]
            active_runs[role] = distribution(arrays[key][:, t].sum(axis=1), sum(e['runs'] for e in labels))
        transition = {}
        for c, name in enumerate(categories):
            observed_name = ALIASES.get(name, name)
            require(observed_name in actual['transitionCounts'], 'Observed transition definition unavailable: ' + name)
            transition[name] = distribution(arrays['transition_counts'][:, t, :, c].sum(axis=1), actual['transitionCounts'][observed_name])
        metrics['multipleOutPAProxy'] = transition['MULTIOUT_PA_PROXY']
        innings = []
        for i in range(n):
            observed_inning = next((r for r in observed['perTeamInning'] if r['teamSide'] == side and r['inning'] == i + 1), None)
            present = observed_inning is not None
            innings.append({'inning': i + 1, 'observedInningRepresented': present,
                'completedPA': distribution(arrays['completed_pa'][:, t, i], observed_inning['completed_pa'] if present else 0),
                'runs': distribution(run[:, i], observed_inning['runs'] + observed_inning['non_pa_runs'] if present else 0),
                'starterBF': distribution(arrays['starter_bf_by_inning'][:, t, i], observed_inning['starter_bf'] if present else 0),
                'anonymousReliefBF': distribution(arrays['anonymous_relief_bf_by_inning'][:, t, i], observed_inning['relief_bf'] if present else 0)})
        rows[side] = {'team': observed['awayTeam'] if side == 'AWAY' else observed['homeTeam'], 'metrics': metrics,
            'classes': by_class, 'transitionCounts': transition, 'byInning': innings,
            'removalInningGivenModeledRemoval': distribution(removal_inning[modeled_removal], actual_removal),
            'removalReasonCounts': {str(k): int(np.sum(arrays['starter_removal_reason'][:, t] == int(k))) for k in definitions['starterRemovalReasons']},
            'removalCensoredDraws': int((~modeled_removal).sum()), 'observedRemoval': actual['starterRemoval'],
            'runsWhilePitcherRoleActive': active_runs,
            'observedNonPA': {'records': actual['non_pa_records'], 'outs': actual['non_pa_outs'], 'runs': actual['non_pa_runs'], 'endingInningLOB': actual['nonPAEndingInningLOB']},
            'officialGIDP': actual['officialGIDP'], 'officialLineScoreLOB': actual['officialLineScoreLOB'],
            'officialLOBIsNotWalkoffConservationTarget': True}
    # Boundary counters are sealed by the separate passive postprocessor. This
    # reader consumes them; it never invokes enrichment or simulation itself.
    walkoff = arrays['terminal_reason'] == 1
    censored = arrays['terminal_reason'] == 4
    boundary = {}
    for t, side in enumerate(SIDES):
        boundary[side] = {
            'automaticRunnerPlacements': distribution(arrays['automatic_runner_placements'][:, t].sum(axis=1), 0),
            'walkoffRunnerRemnantsGivenWalkoff': distribution(arrays['walkoff_runner_remnants'][walkoff, t]),
            'censoredRunnerRemnantsGivenTruncation': distribution(arrays['censored_runner_remnants'][censored, t])}
    return {'sourceGameId': case['sourceGameId'], 'gameId': case['gameId'], 'matchup': observed['awayTeam'] + '–' + observed['homeTeam'],
        'classification': sidecar['classification'], 'originalForecastId': sidecar['baselineForecastId'], 'simulationCount': 5000,
        'teamOrder': list(SIDES), 'teams': rows,
        'totalPA': distribution(arrays['pa_counts'], observed['completedPA']),
        'totalRuns': distribution(arrays['away_runs'] + arrays['home_runs'], sum(observed['perTeam'][s]['runs'] + observed['perTeam'][s]['non_pa_runs'] for s in SIDES)),
        'boundaries': {'byBattingTeam': boundary, 'walkoffDraws': int(walkoff.sum()), 'walkoffRate': float(walkoff.mean()),
            'censoredDraws': int(censored.sum()), 'definitions': definitions['boundaries'],
            'actualWalkoffRemnant': None, 'actualQualification': 'All three observed cases end conventionally in regulation; actual automatic placements0, with no observed walkoff/censor remnant comparison.'},
        'nonPARepresentation': definitions['nonPAEventCount'], 'observedSourceQualification': observed['comparability'],
        'baseStateValidation': observed['baseStateValidation'], 'observedSource': observed['source'],
        'originalClocks': {k: sidecar[k] for k in ('originalSourceCutoff', 'originalCaptureUtc', 'originalForecastCreatedAtUtc', 'scheduledStartUtc')},
        'retrospectiveCaptureClocks': {k: sidecar[k] for k in ('executionStartedAtUtc', 'createdAtUtc')},
        'invariance': sidecar['invariance']}


def markdown(result):
    def cell(v):
        return f"{v['actual']:g} / {v['mean']:.2f} [{v['p05']:g}–{v['p95']:g}]"
    def pair(row, key):
        return '<br>'.join(s[0] + ': ' + cell(row['teams'][s]['metrics'][key]) for s in SIDES)
    lines = [f"The three declared cases are selected retrospective explanations, with unchanged original forecasts. This report contains {len(result['rows'])} of 3 completed captures. Cells show **observed / simulated mean [5th–95th percentile]**; event-mix cells show **observed / simulated mean**. A/H denotes away/home, and BB+ includes walks, HBP and catcher interference.", '',
        '| Game | Total PA | Runs A/H | Hits, HR and BB+ A/H | Starter BF A/H | Relief BF A/H | Maximum inning runs A/H |',
        '|---|---|---|---|---|---|---|']
    for row in result['rows']:
        mix = []
        for side in SIDES:
            classes = row['teams'][side]['classes']
            hr = classes['HOME_RUN']['sampledCount']; walk = classes['WALK_HBP_CI']['sampledCount']
            hits = row['teams'][side]['metrics']['hits']
            mix.append(f"{side[0]} hits {hits['actual']:g} / {hits['mean']:.2f}; HR {hr['actual']:g} / {hr['mean']:.2f}; BB+ {walk['actual']:g} / {walk['mean']:.2f}")
        lines.append('| ' + ' | '.join([row['matchup'] + ' ' + row['sourceGameId'], cell(row['totalPA']), pair(row, 'runs'), '<br>'.join(mix),
            pair(row, 'starterBF'), pair(row, 'anonymousReliefBF'), pair(row, 'maximumInningRuns')]) + ' |')
    if result['missingCases']:
        lines += ['', 'Partial result from the fixed three-case declaration; pending completed enrichments: ' + ', '.join(result['missingCases']) + '.']
    lines += ['', 'The JSON retains all eight sampled class counts, probability-sum distributions, observed rates, per-draw simulated rates, pitching exposure and outs, conditional removal innings, inning scoring, transition counts and inclusive empirical tails.', '',
        'Probability sums describe evolving simulated situations. They are not predictions captured before actual PAs. Mean per-draw class/PA ratios and exposure-weighted ratios of totals are reported separately. The JSON also reports three fixed aggregates: hits, extra-base hits and reach-class PAs, with the same PA denominators. Reach-class PA is not a baserunner count; fielders choices can include an out. Inclusive tails include ties and are descriptive, not p-values or calibration tests.', '',
        'Starter and relief BF/outs use the pitching-team axis. Runs while a role is active include inherited runners and differ from official pitcher responsibility. Multiple-out PAs are a net-outs proxy, not the grounded-double-play statistic. Third-out LOB excludes unfinished walkoff halves; walkoff remnants are reported separately.', '',
        'Observed classes use the existing event mapping and V2’s explicit record type. V2 index and game physical hashes verify exactly without normalization; V1’s transport qualification remains historical. V2 “bases before” flags are still empty and were rejected; preceding saved end states and half-inning resets pass runner conservation and official LOB checks. The full slate contains 1,176 play records but 1,173 completed PAs; this subset has 224 records and 223 completed PAs. Runner activity within completed PAs remains separately retained: class-run and transition measures use whole-play boundaries, not terminal-class-only causation.', '',
        'No fitting, forecast change or intervention choice is made here. Historical training/feature chronology remains uncertified. The detailed JSON preserves original cutoffs and source references.', '',
        'Reproduce: `.venv/Scripts/python.exe scripts/summarize_mlb_v18_population_diagnostics_v1.py' + (' --partial' if result['partial'] else '') + '`.']
    return '\n'.join(lines) + '\n'


def immutable(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_bytes() == data, 'Existing immutable result differs')
    else:
        with path.open('xb') as f: f.write(data)
    return ref(path)


def summarize(*, partial=False, output_root=OUT):
    output_root = Path(output_root).resolve()
    declaration_path = OUT / 'declaration.json'; declaration_ref = ref(declaration_path)
    declaration = verified_json(declaration_ref)
    require(declaration['schemaVersion'] == 'MLB_V18_PASSIVE_POPULATION_DIAGNOSTIC_DECLARATION_V1', 'Declaration schema mismatch')
    cases = {c['sourceGameId']: c for c in declaration['cases']}
    require(set(cases) == set(CASES) and declaration['simulationsPerRun'] == 5000, 'Fixed three-game declaration differs')
    for case in cases.values(): guard(case)
    observed_ref = ref(OUT / 'observed-v2/observed.json')
    require(observed_ref['sha256'] == OBSERVED_SHA, 'Pinned observed summary changed')
    observed = verified_json(observed_ref)
    require(observed['schemaVersion'] == 'MLB_V18_THREE_GAME_OBSERVED_POPULATION_DIAGNOSTICS_V2', 'Corrected observed schema differs')
    require(observed['PA_CLASS_ORDER'] == list(PA_CLASS_ORDER) and observed['teamOrder'] == list(SIDES), 'Observed ordering differs')
    obs = {o['sourceGameId']: o for o in observed['rows']}; require(set(obs) == set(CASES), 'Observed cases differ')
    pointers = {pk: OUT / 'retrospective' / pk / 'current.json' for pk in CASES}
    enriched_pointers = {pk: OUT / 'retrospective' / pk / 'enriched.json' for pk in CASES}
    missing = [pk for pk in CASES if not pointers[pk].exists() or not enriched_pointers[pk].exists()]
    require(partial or not missing, 'Missing declared completed enrichments: ' + ', '.join(missing) + '; use --partial to summarize available cases')
    rows = []; inputs = {}
    for pk in CASES:
        if pk in missing: continue
        guard(cases[pk]); pointer_ref = ref(pointers[pk]); sidecar_ref = verified_json(pointer_ref); sidecar = verified_json(sidecar_ref)
        require(sidecar['sourceGameId'] == pk and sidecar['gameId'] == cases[pk]['gameId'] == obs[pk]['gameId'], 'Game identity mismatch')
        require(sidecar['baselineObjectSha256'] == cases[pk]['objectSha256'] and sidecar['baselineForecastId'] == cases[pk]['forecastId'], 'Original forecast identity mismatch')
        require(sidecar['declaration'] == declaration_ref, 'Sidecar declaration mismatch')
        enriched_pointer_ref = ref(enriched_pointers[pk]); completion_ref = verified_json(enriched_pointer_ref)
        completion = verified_json(completion_ref)
        require(completion['parentSidecar'] == sidecar_ref, 'Completion receipt does not bind the exact parent sidecar')
        require(not completion['eligibleProspectiveCapture'], 'Prospective completion cannot enter retrospective comparison')
        enriched_sidecar = verified_json(completion['enrichedSidecar'])
        require(enriched_sidecar['counters'] == completion['counters'], 'Enriched sidecar counter metadata differs from completion receipt')
        require(enriched_sidecar['gameId'] == sidecar['gameId'] and enriched_sidecar['sourceGameId'] == pk, 'Enriched sidecar game identity differs')
        verified_bytes(completion['boundaryHelper'])
        arrays, definitions = load_population(sidecar, completion['enrichedPopulation'], completion['counters'])
        rows.append(compare_game(cases[pk], obs[pk], sidecar, arrays, definitions))
        inputs[pk] = {'pointer': pointer_ref, 'sidecar': sidecar_ref, 'population': sidecar['population'],
            'enrichedPointer': enriched_pointer_ref, 'completionReceipt': completion_ref,
            'enrichedSidecar': completion['enrichedSidecar'], 'enrichedPopulation': completion['enrichedPopulation'],
            'boundaryHelper': completion['boundaryHelper'], 'sourceArchives': completion['sourceArchives'],
            'completionStatus': completion['status'], 'artifactsCompletedAtUtc': completion['artifactsCompletedAtUtc'],
            'completedAtUtc': completion['completedAtUtc'], 'collector': sidecar['collector'],
            'accounting': sidecar['counters']['accounting'], 'boundaryAccounting': completion['counters']['boundaryDerivation']}
    result = {'schemaVersion': 'MLB_V18_FIXED_POPULATION_DIAGNOSTIC_COMPARISON_V1', 'partial': bool(missing),
        'requestedPartialMode': bool(partial), 'fixedCases': list(CASES), 'availableCases': [r['sourceGameId'] for r in rows], 'missingCases': missing,
        'selection': declaration['selection'], 'status': 'COMPLETE' if not missing else 'PARTIAL', 'rows': rows,
        'sources': {'declaration': declaration_ref, 'observed': observed_ref, 'quarantineAtRead': ref(LEDGER), 'sidecars': inputs, 'summarizer': ref(__file__)},
        'definitions': {'quantiles': 'numpy.quantile method=linear at0.05,0.50,0.95; each distribution reports its draw count.',
            'inclusiveTails': 'Mean(draw<=actual) and mean(draw>=actual); ties enter both. Descriptive selected-case locations, not p-values, calibration or independent validation.',
            'ratioDistinction': 'sampledCountPerPA/perDrawRatioDistribution.mean is mean(count/PA); ratioOfSums is sum(count)/sum(PA). No substitution between them.',
            'probabilitySums': 'Summed frozen model probabilities on evolving simulated exposures; never actual-PA conditional forecasts.',
            'axes': 'Team AWAY/HOME for batting metrics; starter/relief BF/outs and active-role runs are pitching-team metrics.',
            'removalCensoring': 'Quantiles/tails condition on reason1 modeled removal; reason2/3 draws remain counted as censored, not inning-1.',
            'observedTransport': 'V2 index and selected game physical hashes verify exactly without normalization. V1 normalized-LF/canonical-JSON qualifications are retained only in predecessor lineage.',
            'observedRunAttribution': 'V2 recordType distinguishes a completed PA from an inning-ending baserunning out. Within-PA runner activity stays in its whole-play net boundary; runs-on-class and transition counters do not isolate terminal-class-only causation.',
            'chronology': 'Inherited fitted-model training and feature chronology limitations remain; this reproduction cannot repair them.'},
        'interventionSelected': False, 'fits': 0, 'modelRuns': 0, 'providerRequests': 0, 'newOutcomeReads': 0, 'originalArtifactsModified': False}
    encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    digest = hashlib.sha256(encoded).hexdigest(); destination = output_root / 'summary/objects/sha256' / digest
    report = immutable(destination / 'comparison.json', encoded)
    md = immutable(destination / 'comparison.md', markdown(result).encode())
    pointer = {'comparison': report, 'markdown': md, 'status': result['status'], 'availableCases': result['availableCases'], 'missingCases': missing}
    p = output_root / 'summary/current.json'; p.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(pointer, indent=2) + '\n').encode()
    if not p.exists() or p.read_bytes() != data:
        temporary = p.with_suffix('.tmp'); temporary.write_bytes(data); temporary.replace(p)
    return pointer


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--partial', action='store_true', help='Summarize only declared cases with completed enrichment receipts; list missing cases')
    parser.add_argument('--output-root', type=Path, default=OUT, help='Result root; input pointers always come from the fixed study root')
    args = parser.parse_args()
    print(json.dumps(summarize(partial=args.partial, output_root=args.output_root), indent=2))
