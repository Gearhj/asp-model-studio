"""Publish immutable reports over the completed bounded MLB study; never fit models."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server.sports_datasets.consumer import canonical_json_bytes
from server.sports_current_statcast.mlb_regime_study_registration import (
    checked_artifact, read_result, register_study,
)

OUTPUT = ROOT / 'outputs/mlb-regime-hybrid-ensemble-v1'
RUN = OUTPUT / 'runs/mlb-regime-hybrid-20260910-v1'
SOURCE_SHA = '740632fd33bef4c729633b16ef1a17637f6c08bca3435c7a1dabefa9832e699b'
FORWARD = OUTPUT / 'forward-contract/sha256/9505a1a0ed1ce633997d2a27520c079014f47a297c0c9374f7cd3df7504c8d96'


def ref(path: Path, label: str | None = None, category: str = 'Research evidence') -> dict:
    raw = path.read_bytes()
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(raw).hexdigest(), byteCount=len(raw),
                label=label or path.name, category=category)


def put(path: Path, raw: bytes) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError(f'Immutable publication conflict: {path}')
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return ref(path)


def document(name: str, raw: bytes) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    return put(OUTPUT / 'documents/sha256' / digest / name, raw)


def json_document(name: str, value: object) -> dict:
    return document(name, canonical_json_bytes(value))


def prepare(diagnostics_path: Path) -> dict:
    original_ref = ref(RUN / 'study-result.json')
    if original_ref['sha256'] != SOURCE_SHA:
        raise ValueError('Original completed research result differs')
    original = read_result(original_ref)
    for artifact in original['artifacts']:
        checked_artifact(artifact)
    diagnostics_path = diagnostics_path.resolve()
    if not diagnostics_path.is_relative_to(OUTPUT / 'diagnostics/sha256'):
        raise ValueError('Expected immutable post-fit diagnostics under this study')
    diagnostics_ref = ref(diagnostics_path)
    diagnostics = json.loads(diagnostics_path.read_text(encoding='utf-8'))
    source_ref = ref(FORWARD / 'source-evidence.json')
    if source_ref['sha256'] != FORWARD.name:
        raise ValueError('Forward evidence identity differs')
    evidence = json.loads((FORWARD / 'source-evidence.json').read_text(encoding='utf-8'))
    result = copy.deepcopy(original)
    result['publicationRevision'] = 'REPORTING_AND_POSTFIT_DIAGNOSTICS_V1'
    result['predecessor'] = original_ref
    result['diagnostics'] = diagnostics_ref
    result['sourceEvidence'] = source_ref
    result['reportingDefinitions'] = {
        'clusterSpecialistError': 'STANDALONE_RESIDUAL_SPECIALISTS_CALIBRATED_MATCHED_HARD_CLUSTER',
        'selectedEnsembleError': 'RF_RESIDUAL_ENSEMBLE_CALIBRATED_MATCHED_HARD_CLUSTER',
        'originalFieldCorrection': 'Predecessor specialistLogLoss held the selected ensemble. Original preserved; successor distinguishes both.',
        'stability': 'TRAINING_PREFIX_ARI_CONDITIONAL_ON_OUTER_2023_SEMANTIC_PREPROCESSOR',
        'intervalAuthority': 'EXPLORATORY_DEVELOPMENT_NOT_INDEPENDENT_PROMOTION_INFERENCE',
    }
    # The diagnostics writer supplies one verified, explicitly named record per profile.
    profile_updates = {row['clusterId']: row for row in diagnostics['allEightResidualProfiles']}
    if set(profile_updates) != {row['clusterId'] for row in original['clusterProfiles']}:
        raise ValueError('Standalone specialist profile coverage differs')
    for row in result['clusterProfiles']:
        row['selectedEnsembleLogLoss'] = row['specialistLogLoss']
        row['selectedEnsembleMeanAdjustment'] = row['meanAdjustment']
        row.update(profile_updates[row['clusterId']])
        row['comparisonModel'] = 'RESIDUAL_SPECIALISTS'
        row['recommendation'] = 'Review only. No specialist promotion.'
    result['selection']['frozenEnsembleComposition'] = diagnostics['ensembleContribution']
    result['selection']['conclusion'] = 'Small V18/RF diversification gain; zero residual-specialist weight. Retain V18 authority.'
    result['currentShadow'] = {
        'status': 'FORWARD_CONTRACT_ONLY_NO_SUPPORTED_NEXT_SLATE_INPUTS', 'forecasts': 0,
        'retrospectiveForecastsProduced': 0, 'lastExistingLocalSlate': '2026-09-08',
        'existingPublishedForecastsPreserved': 13, 'existingSkipsPreserved': 2,
        'requiredLink': 'Exact frozen RF preprocessing reconstruction and timestamped pre-kickoff next-slate inputs',
        'sourceEvidence': source_ref,
    }
    result['limitations'] = [
        'Ensemble gain is 89.2% V18 / 10.8% existing RF diversification; fitted residual specialist weight is zero.',
        'Standalone cluster, interaction, residual and mixture-of-experts candidates worsen final total log loss.',
        'Exact baseline parity covers 494,432 matched PAs; 7,107 registered OOF PAs/94 games are excluded to keep the mixed physical OOT row group unread.',
        'Fold 5 is later Development used historically in V18 research, not independent Final OOT.',
        'Fifteen evaluation weeks contain only three nonoverlapping complete four-week blocks; intervals are descriptive Development evidence.',
        'Cluster ARI is conditional training-prefix stability, not a full end-to-end or multi-season stability guarantee.',
        'Player clusters primarily reflect exposure and uncertainty. Team rest/travel is not bullpen availability; matchup clusters are calendar dominated.',
        'Class calibration is mixed; WALK_HBP_CI Brier and some marginal biases worsen; rare-class slopes remain imperfect.',
        'Cold-history flags do not identify rookies, promotions, trades, role changes or absence; fixed semantic priors were not causally ablated.',
        'Bullpen-workload and temperature missingness flags are 1 on every safe OOF PA. Missing-family error impact cannot be estimated without governed comparison evidence.',
        'Game results are twenty-game oracle mechanics sensitivity, not prospective pregame forecasting skill.',
        'No historical valid time-matched two-sided market cohort was established; no market-relative or wagering-edge claim.',
        'No current forecast is published: saved September 8 templates are past; future inputs and complete RF frozen-preprocessor reproduction are unavailable.',
        'Large governed observation caches and OOF atlas payloads remain local, checksum-referenced, and are not stored in Git.',
    ]
    starts = [json.loads(line) for line in (RUN/'events.jsonl').read_text().splitlines()]
    result['executionAccounting'] = {
        'clustering': result['modelFitReceipts']['clustering'],
        'correctionFitStarts': sum(r['event']=='CORRECTION_FIT_STARTED' and not r['name'].startswith('TEMPERATURE_') for r in starts),
        'correctionFitCompletions': sum(r['event']=='CORRECTION_FIT_COMPLETED' and not r['name'].startswith('TEMPERATURE_') for r in starts),
        'forecastTemperatureFitStarts': sum(r['event']=='CORRECTION_FIT_STARTED' and r['name'].startswith('TEMPERATURE_') for r in starts),
        'forecastTemperatureFitCompletions': sum(r['event']=='CORRECTION_FIT_COMPLETED' and r['name'].startswith('TEMPERATURE_') for r in starts),
        'globalPredictiveEstimatorFits': 0,
        'failureEvents': [r for r in starts if 'FAILED' in r['event']],
        'studyExecutionSeconds': (datetime.fromisoformat(result['completedAtUtc'])-datetime.fromisoformat(result['startedAtUtc'])).total_seconds(),
        'runtimeScope': 'Main bounded study only; excludes baseline reproduction, diagnostics, reporting and UI build.',
        'diagnosticRegressionScope': 'Evaluation calibration intercept/slope regressions do not update forecast calibrators or candidate selection.',
        'python': sys.version, 'platform': platform.platform(),
    }
    extras = [original_ref, diagnostics_ref, source_ref, ref(FORWARD/'forward-contract.md'), ref(RUN/'events.jsonl')]
    for name in ('MLB_REGIME_HYBRID_STUDY_REPORT_V1.md','MLB_REGIME_HYBRID_MODEL_CARD_V1.md'):
        extras.append(document(name, (ROOT/'docs'/name).read_bytes()))
    extras.append(json_document('candidate-comparison-matrix.json', result['leaderboard']))
    extras.append(json_document('fold-regime-calibration-evidence.json', {
        'foldMetrics': result['foldMetrics'], 'calibration': result['calibration'],
        'regimeMetrics': result['regimeMetrics'], 'regimeComparisonModel': result['diagnosticChallenger'],
        'diagnosticsSupplement': diagnostics_ref, 'coldStart': result['coldStart'],
        'uncertaintyIntervals': result['uncertaintyIntervals'], 'removalSensitivity': result['removalSensitivity'],
    }))
    extras.append(json_document('gating-ensemble-contract.json', {
        'selection': result['selection'], 'modelFitReceipts': result['modelFitReceipts'],
        'eligibility': result['specialistEligibility'], 'authority': result['authority'],
        'fittedInputRequirements': ['EXACT_V18_RAW_PROBABILITIES','EXACT_FROZEN_RF_RAW_PROBABILITIES',
                                    '273_ORDERED_V18_SEMANTIC_FEATURES','ORIGINAL_CLASS_AND_EVENT_IDENTITIES'],
        'capScope': '0.03 per class, before chronological temperature scaling',
        'currentExecutable': False,
    }))
    baseline_path = OUTPUT/'baseline-cache/baseline-reproduction-0abcf4e521c2a59c7c8cd04450e1d57a0c790f306dc571d7866b3650553a3af9.json'
    extras.append(ref(baseline_path))
    for key, item in result['baselineParity']['artifacts'].items():
        extras.append({'path':item['path'],'sha256':item['sha256'],'byteCount':item['bytes'],
                       'label':key, 'category':'Local governed Development cache'})
    result['artifacts'].extend(extras)
    # Source metadata is not interpreted as new authority or instructions.
    result['sourceEvidenceSchema'] = evidence.get('schemaVersion', evidence.get('contract'))
    return json_document('review-result.json', result)


def publish(prepared_path: Path, workbook_path: Path) -> dict:
    result = read_result(ref(prepared_path))
    workbook_path = workbook_path.resolve()
    if not workbook_path.is_relative_to(OUTPUT) or workbook_path.suffix != '.xlsx':
        raise ValueError('Expected the reviewed workbook under this study output')
    workbook_ref = document(workbook_path.name, workbook_path.read_bytes())
    result['artifacts'].append(workbook_ref)
    result['verification'] = {
        'focusedPytestCasesPassed': 8,
        'scope': ['physical seal/baseline 2','simulator orientation/reproduction 2',
                  'metric/interval diagnostics 1','authenticated research registration 1','seal/capped-global-fallback 2'],
        'baselineBitwiseMismatchCount': 0, 'fittedBranchReloadMismatchCount': 0,
        'frontendBuilds': 1, 'frontendBuildStatus': 'PASSED',
        'workbook': 'Formula deltas checked and both sheets rendered/reviewed; no native Excel interaction performed.',
        'fullRepositorySuiteRun': False,
    }
    raw = canonical_json_bytes(result)
    digest = hashlib.sha256(raw).hexdigest()
    result_ref = put(OUTPUT/'publications/sha256'/digest/'study-result.json', raw)
    verified = read_result(result_ref)
    for artifact in verified['artifacts']:
        checked_artifact(artifact)
    if (OUTPUT/'latest.json').exists():
        prior = json.loads((OUTPUT/'latest.json').read_text())
        if prior['result'] != result_ref:
            raise ValueError('A different study publication owns latest; no pointer changed')
        checked_artifact(prior['manifest'])
        print(json.dumps({'status':'NO_OP','pointer':prior},indent=2))
        return prior
    code_paths = sorted([*ROOT.glob('server/sports_current_statcast/mlb_regime_*.py'),
                         *ROOT.glob('scripts/*mlb_regime*.py'),ROOT/'scripts/mlb-regime-workbook/build.mjs',
                         ROOT/'src/sports/MlbRegimeStudy.tsx',ROOT/'src/sports/ForecastWorkflow.tsx',
                         ROOT/'server/sports_shared/router.py',ROOT/'docs/MLB_REGIME_HYBRID_STUDY_PROTOCOL_V1.md'])
    manifest = {'schemaVersion':'MLB_REGIME_RESEARCH_PUBLICATION_MANIFEST_V1',
        'studyId':result['studyId'], 'researchCompletedAtUtc':result['completedAtUtc'],
        'publicationCreatedAtUtc':datetime.now(timezone.utc).isoformat(),
        'result':result_ref,'files':result['artifacts'], 'codeReferences':[ref(path) for path in code_paths],
        'authority':result['authority'],'forecastCount':0,'officialForecastsChanged':0,
        'predecessor':result['predecessor'],'recommendedAction':'RETAIN_V18_PRESERVE_NONEXECUTING_RESEARCH_ENSEMBLE',
        'localPayloadBackupRequired':True}
    manifest_ref = json_document('publication-manifest.json', manifest)
    receipt = register_study(result_ref)
    repeated = register_study(result_ref)
    if repeated['status'] != 'NO_OP':
        raise ValueError('Registration must be idempotent')
    receipt_ref = json_document('registration-receipt.json', {'first':receipt,'repeated':repeated,'result':result_ref})
    pointer = {'result': result_ref, 'manifest':manifest_ref, 'registration':receipt_ref}
    # This task owns this previously absent discovery pointer. Do not replace other publications.
    put(OUTPUT/'latest.json',canonical_json_bytes(pointer))
    print(json.dumps(pointer, indent=2))
    return pointer


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['prepare','publish'])
    parser.add_argument('--diagnostics', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--workbook', type=Path)
    args = parser.parse_args()
    if args.mode == 'prepare':
        print(json.dumps(prepare(args.diagnostics),indent=2))
    else:
        publish(args.prepared,args.workbook)
