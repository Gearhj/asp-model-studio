"""Assemble completed bounded V19 evidence; never fit or publish a forecast."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
from run_mlb_v19_study import OUT, VARIANTS, ref, write_json
from server.sports_datasets.consumer import canonical_json_bytes
from register_mlb_v19_study import VERDICTS, verify_manifest
from compare_mlb_v19_game_mechanics import completed_meta_authority

START_BRANCH = 'codex/mlb-v18-current-state-pipeline-v1'
START_HEAD = '9b6253fa7c59ebf5d19a3c1fb1b220efd7fc14f4'
STUDY_BRANCH = 'codex/mlb-v19-current-state-specialists-v1'
DECLARATION_HEAD = '5be3c6e868b4decbc90efd19e61f8efa6910e98e'
QUALITY = OUT / 'feature-quality/sha256'


def load(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def immutable_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode('utf8')
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('Preserve existing report; successor identity required: ' + str(path))
    else:
        with path.open('xb') as handle:
            handle.write(data)
    return ref(path)


def validate_final_disposition(candidate, verdict, candidates, executable, readiness, game_comparison):
    """Reject contradictory completion claims; never choose a candidate here."""
    selected = candidates[candidate]
    passed = selected.get('passesDevelopmentResearchRule') is True
    if (executable.get('schemaVersion') != 'MLB_V19_EXECUTABLE_RESEARCH_PACKAGE_V1'
            or executable.get('inputAuthority', {}).get('selectedBranch') != candidate
            or executable.get('inputAuthority', {}).get('selectedCandidateDecision') != selected
            or executable.get('finalOotPayloadBytesRead') != 0):
        raise ValueError('Executable package does not match the evaluated candidate and sealed Development authority')
    replays = executable.get('fullStackReproduction', [])
    if (not replays or any(r.get('observations') != 32 or r.get('mismatchCount') != 0 for r in replays)
            or not any(r.get('branch') == candidate and r.get('scale') == 'calibrated' for r in replays)):
        raise ValueError('The selected complete executable must have exact full-stack calibrated reload evidence')
    if (readiness.get('schemaVersion') != 'MLB_V19_COMPOUND_OPERATIONAL_READINESS_V1'
            or readiness.get('selectedBranch') != candidate or readiness.get('passesDevelopmentRule') is not passed
            or type(readiness.get('prospectiveReady')) is not bool
            or type(readiness.get('verifiedSupportedCurrentGames')) is not int
            or readiness['verifiedSupportedCurrentGames'] < 0
            or readiness.get('wageringAuthority') is not False
            or readiness.get('executionAllowedInAISP') is not False
            or readiness.get('finalOotPayloadBytesRead') != 0):
        raise ValueError('Operational readiness must state the same candidate, Development result, current support and research-only authority')
    ready = readiness['prospectiveReady'] is True and readiness['verifiedSupportedCurrentGames'] > 0
    if verdict == 'MLB_V19_SPECIALIST_CHALLENGER_READY_FOR_PROSPECTIVE_SHADOW':
        if candidate != 'SPECIALIST_MIXTURE' or not passed or not ready:
            raise ValueError('Specialist-ready verdict requires the passing specialist and verified supported current games')
    elif verdict == 'MLB_V19_GLOBAL_CHALLENGER_ONLY':
        if candidate == 'SPECIALIST_MIXTURE' or not passed:
            raise ValueError('Global-only verdict requires a passing global branch or global ensemble')
        # This verdict preserves a global research challenger; it is deliberately
        # not an assertion that its current source bridge is operational.
    elif verdict == 'MLB_V18_RETAINED_AFTER_SPECIALIST_STUDY':
        if any(row.get('passesDevelopmentResearchRule') is True for row in candidates.values()):
            raise ValueError('A passing research candidate requires an explicit global/ready/blocked disposition, not a no-improvement verdict')
    elif verdict == 'MLB_V19_STUDY_BLOCKED_ON_EVIDENCE':
        if not passed or ready or not readiness.get('blockers'):
            raise ValueError('An evidence-blocked completed study requires a passing but unsupported candidate and specific blockers')
    if (game_comparison.get('schemaVersion') != 'MLB_V19_ORACLE_GAME_COMPARISON_V1'
            or game_comparison.get('evidenceTrack') != 'ORACLE_MECHANICS_SENSITIVITY_NONPREGAME'
            or game_comparison.get('candidate') != candidate
            or game_comparison.get('probabilityScale') != 'calibrated'
            or game_comparison.get('completedGames') != 20 or game_comparison.get('simulationsPerGame') != 500
            or game_comparison.get('simulatorCalls') != 40
            or game_comparison.get('populationHashMismatches') != 0 or game_comparison.get('populationReloadMismatches') != 0):
        raise ValueError('Expected the complete exact twenty-game, 500-draw calibrated oracle comparison for this candidate')
    if not passed and game_comparison.get('selectionDisposition') != 'REJECTED_DIAGNOSTIC_ONLY':
        raise ValueError('A failing candidate game comparison must remain an explicitly rejected diagnostic')
    return {'candidate': candidate, 'candidatePassesDevelopmentRule': passed,
            'prospectiveReady': readiness['prospectiveReady'],
            'verifiedSupportedCurrentGames': readiness['verifiedSupportedCurrentGames'],
            'verdictEvidenceConsistent': True}


def main(args):
    # Require the completed global/meta evaluation before making a final report.
    meta_package, _, _ = completed_meta_authority()
    if meta_package['matchedRows'] != 494432 or meta_package['matchedGames'] != 6570:
        raise ValueError('Matched Development population differs')
    decision = load(OUT / 'evaluation/development-decision.json')
    calibrated = load(OUT / 'evaluation/calibrated-evaluation.json')
    raw = load(OUT / 'evaluation/raw-evaluation.json')
    candidates = {r['model']: r for r in decision['candidates']}
    if args.candidate not in candidates:
        raise ValueError('Candidate must be an evaluated frozen branch')
    if args.verdict not in VERDICTS:
        raise ValueError('Unrecognized user verdict')
    required = [args.cluster_report, args.executable_package, args.operational_readiness, args.game_comparison,
                OUT / 'review/MLB_V19_Research_Review.xlsx']
    for path in required:
        if not path.resolve().is_relative_to(OUT.resolve()) or not path.is_file():
            raise ValueError('Required completed V19 deliverable missing')
    executable = load(args.executable_package)
    readiness = load(args.operational_readiness)
    game_comparison = load(args.game_comparison)
    disposition = validate_final_disposition(args.candidate, args.verdict, candidates, executable, readiness, game_comparison)
    # Authenticate the package's readiness child, not an unrelated free-standing
    # JSON claiming that a different branch happens to be operational.
    readiness_ref = ref(args.operational_readiness)
    if readiness_ref not in executable.get('artifacts', []):
        raise ValueError('Operational-readiness receipt is not a checksum-linked child of this executable package')
    events_path = OUT / 'fit-events.jsonl'
    events = [json.loads(line) for line in events_path.read_text().splitlines() if line]
    global_starts = [e for e in events if e['event'] == 'FIT_STARTED' and e.get('fit') in VARIANTS]
    global_completions = [e for e in events if e['event'] == 'FIT_COMPLETED' and e.get('fit') in VARIANTS]
    if len(global_starts) != 20 or len(global_completions) != 20:
        raise ValueError('Twenty actual global fits and completions required; scheduled slots are not fits')
    expected = {(fold, name) for fold in range(1, 6) for name in VARIANTS}
    if {(e['fold'], e['fit']) for e in global_completions} != expected:
        raise ValueError('Global completion identity differs')
    matrix, cluster_estimators = [], 0
    for fold in range(1, 6):
        folder = OUT / f'folds/fold-{fold}'
        prefit = load(folder / 'prefit-native-missing-v2.json')
        complete = load(folder / 'complete.json')
        if complete['globalFitsCompleted'] != 4:
            raise ValueError('Incomplete global fold')
        for report in load(folder / 'clusters.json')['domains']:
            if report.get('centersOriginalUnits'):
                cluster_estimators += 1 + int(report.get('subprefixStabilityARI') is not None)
        for name in VARIANTS:
            verification = load(folder / (name + '-verified.json'))
            fit = next(e for e in global_completions if (e['fold'], e['fit']) == (fold, name))
            matrix.append({'model': name, 'fold': fold, 'trainingRows': prefit['trainRows'],
                'validationRows': prefit['validationRows'], 'split': prefit['fold'],
                'featureCountAfterEncoding': verification['featureCount'],
                'seed': 20260911 + fold, 'nativeWorkers': 4, 'fitSeconds': fit['seconds'],
                'orderedFeatureAndModelAuthority': ref(folder / (name + '-verified.json')),
                'prefitAuthority': ref(folder / 'prefit-native-missing-v2.json')})
    reports = OUT / 'reports'
    matrix_ref = write_json(reports / 'candidate-matrix.json', {
        'schemaVersion': 'MLB_V19_COMPLETED_CANDIDATE_MATRIX_V1', 'globalFits': matrix,
        'baseline': 'V18_FROZEN_FIVE_FOLD_EXACT_REPLAY_NO_REFIT',
        'globalArchitectures': {
            'SEMANTIC_HGB': 'Frozen V18 HGB parameters plus 44 semantic means/exposure inputs',
            'SEMANTIC_EXTRA_TREES': {'n_estimators': 240, 'max_depth': 20, 'min_samples_leaf': 50,
                'max_features': .7, 'bootstrap': False, 'historicalMissingRFReplacement': False},
            'REGIME_HGB': 'SEMANTIC_HGB plus 12 fixed pregame indicators',
            'REGIME_CLUSTER_HGB': 'REGIME_HGB plus training-only fixed three-cluster domain features'},
        'derivedModels': ['GLOBAL_ENSEMBLE', 'SPECIALIST_MIXTURE'],
        'chronologicalMetaAuthority': ref(OUT / 'evaluation/meta-study-package.json'),
        'declaration': ref(ROOT / 'docs/MLB_V19_STUDY_DECLARATION_V1.md')})
    accounting_ref = write_json(reports / 'fit-accounting.json', {
        'scheduledGlobalFitSlots': 20, 'actualGlobalEstimatorStarts': len(global_starts),
        'actualGlobalEstimatorCompletions': len(global_completions),
        'failedFitEvents': [e for e in events if e['event'] == 'FIT_FAILED'],
        'preflightFailures': [e for e in events if e['event'] == 'PREFLIGHT_FAILURE_RECORDED'],
        'completedFitEventsByFamily': dict(Counter(e['fit'] for e in events if e['event'] == 'FIT_COMPLETED')),
        'semanticDomainOptimizerFits': 20, 'clusterEstimatorFitCalls': cluster_estimators,
        'actualMetaFits': meta_package['actualMetaFits'], 'syntheticNativeNaNCompatibilityFits': 2,
        'syntheticCompatibilityTreesPerFit': 2, 'baselineEstimatorFits': 0,
        'globalFitSeconds': sum(e['seconds'] for e in global_completions),
        'globalFitStartUtc': min(e['atUtc'] for e in global_starts),
        'globalFitLastCompletionUtc': max(e['atUtc'] for e in global_completions),
        'events': ref(events_path), 'providerCalls': 0, 'providerCostUsd': 0,
        'finalOotPayloadBytesRead': 0, 'aispWrites': 0,
        'pinnedV18DeploymentChanged': False, 'originalNFLNBAWorkPreserved': True})
    calibration_ref = write_json(reports / 'calibration-uncertainty.json', {
        'scope': 'REUSED_DEVELOPMENT_DESCRIPTIVE_NOT_INDEPENDENT_CONFIRMATION',
        'rawEvaluation': ref(OUT / 'evaluation/raw-evaluation.json'),
        'calibratedEvaluation': ref(OUT / 'evaluation/calibrated-evaluation.json'),
        'perClassCalibration': 'Eight-class observed/predicted rates, one-vs-rest Brier and ten-bin reliability/ECE',
        'calibrationFitRule': 'Separate bounded scalar temperatures using final15percent dates of earlier OOF folds only; fold1 identity',
        'intervalRule': '500 paired resamples at game and four-week calendar-block levels; same matched IDs',
        'multipleDevelopmentReuse': True, 'finalOotRecommendation': 'REMAIN_SEALED',
        'semanticUncertainty': 'Four training-prior posterior-dispersion fields excluded from mean inputs; no claim of fitted game-variance improvement',
        'hyperpriorClarification': 'Entity counts strictly precede query date. League/hand population priors use the entire outer training prefix. The concentration/decay objective is training-prefix empirical Bayes with pre-date entity counts, not fully prequential population-prior fitting.',
        'declarationPreserved': 'The original declaration wording is retained; this precise qualification supersedes its unqualified prequential-loss phrase.',
        'removalSensitivityDefinition': 'Strongest is lowest mean per-PA log-loss delta among supported groups, not greatest total contribution.',
        'gamePerformanceLimitation': 'Realized-participant oracle simulation cannot establish historical pregame winner/score calibration.'})
    selected = candidates[args.candidate]
    overall = lambda evaluation: [r for r in evaluation['metrics'] if r['dimension'] == 'overall']
    regimes = [r for r in calibrated['metrics'] if r['model'] in ('V18', args.candidate) and r['dimension'] == 'regime'
               and ('EARLY' in r['group'] or 'MISSING' in r['group'] or 'EXPOSURE' in r['group'] or 'OBSERVATION' in r['group'])]
    recommendation_ref = write_json(reports / 'recommendation.json', {
        'verdict': args.verdict, 'retainedOfficialModel': 'V18', 'preservedCandidate': args.candidate,
        'candidatePassesDevelopmentRule': selected['passesDevelopmentResearchRule'],
        'dispositionVerification': disposition,
        'decision': ref(OUT / 'evaluation/development-decision.json'),
        'rawOverall': overall(raw), 'calibratedOverall': overall(calibrated),
        'candidatePairedIntervals': calibrated['pairedIntervals'][args.candidate],
        'earlyAndColdStart': regimes, 'nextAction': args.next_action,
        'prospectiveReadiness': ref(args.operational_readiness),
        'finalOotRecommendation': 'REMAIN_SEALED', 'wageringAuthority': False,
        'executionAllowedInAISP': False, 'promotionStatus': 'NOT_PROMOTED'})
    text = ['# MLB V19 bounded study result', '', f'Verdict: `{args.verdict}`.', '',
        f'V18 remains retained. Preserved research branch: `{args.candidate}`. '
        f'Development-rule pass: {selected["passesDevelopmentResearchRule"]}.', '',
        '## Matched plate-appearance performance', '',
        '494,432 PAs from 6,570 games. All five V18 baseline artifacts reproduced exactly. '
        'The 7,107 additional registered OOF observations remain excluded to protect the physical seal and incomplete boundary date.', '',
        '| Model | Raw log loss | Raw Brier | Calibrated log loss | Calibrated Brier |',
        '| --- | ---: | ---: | ---: | ---: |']
    raw_index = {r['model']: r for r in overall(raw)}
    for row in overall(calibrated):
        old = raw_index[row['model']]
        text.append(f'| {row["model"]} | {old["logLoss"]:.9f} | {old["brier"]:.9f} | {row["logLoss"]:.9f} | {row["brier"]:.9f} |')
    text += ['', '## Interpretation and limits', '',
        'The machine-readable evaluations retain fold, early-season, limited-exposure, annual-prior-missing, '
        'month, team, cluster, routed and complement results with exact sample sizes. '
        'The declaration was committed before fitting. Paired game and four-week intervals are descriptive '
        'because these Development periods have been studied before.', '',
        'Current source work derives workload/rest and source-age evidence from seven already captured days '
        '(September 3–9), preserving receipts and clocks. It is forward-archive evidence, not historically '
        'point-in-time-certified training data. No lift is attributed to these new captures.', '',
        'New numerical features are 44 training-fitted batter/pitcher/team class-prior and exposure inputs. '
        'Four posterior-dispersion quantities are outside the mean model. No generic median/mode was added. '
        'Source absence is not career absence. The per-field specification also records unsupported treatment families.', '',
        'The prior objective uses full-training-prefix league/hand priors with strictly pre-date entity counts. '
        'It is not a fully prequential hyperprior fit. Separate chronological validation remains untouched.', '',
        'Historical lineup/participant publication vintages are unavailable. The 20-game simulation is only '
        'oracle mechanics sensitivity, not pregame winner/score forecast skill. No market result from the earlier '
        '40-game study is reused as confirmation.', '',
        '## Authority and next action', '', args.next_action, '',
        'Final OOT remains sealed. No AISP changes, promotion, position creation or wagering authority. '
        'Pinned V18 publication, NFL and NBA work are unchanged.', '']
    report_ref = immutable_text(reports / 'MLB_V19_STUDY_REPORT.md', '\n'.join(text))
    deliverables = {
        'feature_quality_audit': ref(QUALITY / '18171d5414989a12ebfba8ed1916112ac047ef78f62c7a793b65d1d4923aabc0/feature-quality.json'),
        'ranked_source_gaps': ref(QUALITY / '2c75cb8a47d1f4d39b5495987cbc65232207294dbd8a811f424b6e6158a0321a/ranked-source-gaps.json'),
        'cold_start_specification': ref(QUALITY / '8e88e564a2e12e754f8c723d39a1864ef9bb4589b57c14134fe55063d2a98f25/cold-start-specification.json'),
        'failure_atlas': ref(OUT / 'baseline-atlas/sha256/d1b27325f5c2d0ac2ef048e282578cca12b5e09cb95827145a428fc594312b73/baseline-failure-atlas.json'),
        'cluster_analysis': ref(args.cluster_report), 'candidate_matrix': matrix_ref,
        'matched_evaluation': ref(OUT / 'evaluation/meta-study-package.json'),
        'calibration_uncertainty': calibration_ref, 'executable_package': ref(args.executable_package),
        'game_simulation_comparison': ref(args.game_comparison), 'operational_readiness': ref(args.operational_readiness),
        'review_workbook': ref(OUT / 'review/MLB_V19_Research_Review.xlsx'), 'recommendation': recommendation_ref}
    # Snapshot after all writers finish. Publishing a checksum manifest does not
    # register or authorize any candidate to execute in the production importer.
    files = [ref(p) for p in sorted(OUT.rglob('*')) if p.is_file()
             and p.relative_to(OUT).parts[0] not in ('publication', 'registration')
             and p.suffix not in ('.png', '.pyc')]
    stamp_path = reports / 'completion-clock.json'
    if not stamp_path.exists():
        write_json(stamp_path, {'completedAtUtc': datetime.now(timezone.utc).isoformat()})
        files.append(ref(stamp_path))
    manifest = {'schemaVersion': 'MLB_V19_STUDY_PUBLICATION_MANIFEST_V1', 'projectId': 'asp-mtlozhdx',
        'studyId': 'MLB_V19_CURRENT_STATE_SPECIALISTS_V1', 'status': 'COMPLETED', 'verdict': args.verdict,
        'startedAtUtc': min(e['atUtc'] for e in events), 'completedAtUtc': load(stamp_path)['completedAtUtc'],
        'startingBranch': START_BRANCH, 'startingCommit': START_HEAD, 'researchBranch': STUDY_BRANCH,
        'predeclaredProtocolCommit': DECLARATION_HEAD, 'deliverables': deliverables,
        'authority': {'status': 'RESEARCH_SHADOW', 'promotionStatus': 'NOT_PROMOTED',
            'wageringAuthority': False, 'executionAllowedInAISP': False, 'finalOotAccessed': False},
        'files': sorted(files, key=lambda r: r['path']), 'fitAccounting': accounting_ref,
        'humanReport': report_ref, 'sourceCode': [ref(p) for p in sorted(ROOT.glob('scripts/*mlb_v19*')) if p.is_file()]
            + [ref(p) for p in sorted((ROOT / 'server/sports_current_statcast').glob('mlb_v19*.py'))]}
    digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    manifest_path = OUT / 'publication/sha256' / digest / 'study-manifest.json'
    published = write_json(manifest_path, manifest)
    _, _, verification = verify_manifest(manifest_path)
    print(json.dumps({'manifest': published, 'verification': verification}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--verdict', required=True, choices=sorted(VERDICTS))
    parser.add_argument('--cluster-report', type=Path, required=True)
    parser.add_argument('--executable-package', type=Path, required=True)
    parser.add_argument('--operational-readiness', type=Path, required=True)
    parser.add_argument('--game-comparison', type=Path, required=True)
    parser.add_argument('--next-action', required=True)
    main(parser.parse_args())
