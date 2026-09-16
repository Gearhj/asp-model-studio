"""Stage or publish the additive formal assessment through the existing exchange."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.assess_mlb_existing_prospective_finals_v1 import OUT, immutable, raw_json, read, ref, save, verify

EXCHANGE = Path('C:/Users/james/asp-model-exchange/mlb-v18-ensemble-research-v1/closeout-explanations-v1/packages/sha256')
PREVIOUS_SHA = 'dc279581869935ce817fda246c3920001faf20114046b160c717944a74a8fb4b'


def stage():
    staging_path = OUT/'staged-publication.json'
    if staging_path.exists():
        staged = json.loads(staging_path.read_bytes())
        for bound in staged['files']:
            verify(bound)
        return staged
    result_ref = json.loads((OUT/'assessment.json').read_bytes())
    report = read(result_ref)
    sources = {'formal-assessment.json': Path(result_ref['path']), 'RESULTS.md': OUT/'RESULTS.md',
        'governed-finals.json': OUT/'governed-finals.json', 'identity-before-outcomes.json': OUT/'identity-before-outcomes.json'}
    for bound in report['scoringReceipts']:
        verify(bound)
        sources[Path(bound['path']).name] = Path(bound['path'])
    index = {'schemaVersion': 'MLB_RESEARCH_CLOSEOUT_EXPLANATION_HANDOFF_V1',
        'createdAtUtc': datetime.now(timezone.utc).isoformat(),
        'artifactKind': 'ADDITIVE_FORMAL_ASSESSMENT_NOT_FORECAST',
        'previousQualifiedPackage': {'path': str(EXCHANGE/PREVIOUS_SHA/'index.json'), 'sha256': PREVIOUS_SHA},
        'qualificationResolved': 'Only missing governed September 13 revisions; earlier qualified consumer observations remain unchanged.',
        'files': [{'relativePath': name, 'sha256': ref(p)['sha256'], 'bytes': ref(p)['bytes'], 'originalSource': ref(p)} for name, p in sources.items()],
        'coverage': {'governedStudyGamesScored': 2, 'researchInterventions': 3, 'fallbacks': 0,
            'gamePks': ['824225', '823734'], 'originalBaselineDrawsPerGame': 5000, 'scoreLimitedRetainedDraws': 4722},
        'readerContract': 'Verify exact physical bytes without normalization. Join exact forecastId, canonical game UUID, MLBAM gamePk and sourceOutcomeId/sourceRevision; never nearest/latest forecast. All arms of a game share one final identity. This does not import or replace a forecast.',
        'originalForecastPublicationClocksPreserved': True,
        'exportPublicationClock': 'Separate publication receipt; this assessment did not exist at the original forecast publication.',
        'authority': {'activatesModel': False, 'promotionAllowed': False, 'wageringAuthority': False, 'changesPolicy': False},
        'newHandoffConsumerAcknowledgement': None}
    index_raw = raw_json(index)
    sha = hashlib.sha256(index_raw).hexdigest()
    stage_dir, delivered = OUT/'package/sha256'/sha, EXCHANGE/sha
    immutable(stage_dir/'index.json', index_raw)
    for name, p in sources.items():
        immutable(stage_dir/name, p.read_bytes())
    handoff = f'''# Claude handoff: formal September 13 research assessments

Index: `{delivered/'index.json'}`
Physical SHA-256: `{sha}`; {len(index_raw)} bytes. Verify physical checksums and byte counts before importing; no newline normalization.

This additive assessment closes the missing-governed-revision qualification in package `{PREVIOUS_SHA}`. Preserve that package and its historical consumer reports. Its September 12 explanation joins and protected-inspection note are unchanged. No forecast is regenerated, revised or promoted by this handoff.

Use `formal-assessment.json` rows, their exact `forecastId`, `gamePk`, and `finalIdentity.gameId/sourceOutcomeId/sourceRevision`. Read each row's `scoringReceipt` for original ordered population identity, scoring functions and uncertainty. The same revision is used for all arms of each game. `RESULTS.md` contains the concise numerical table. A derivative's current creation/publication time must not replace original input, freeze, deadline or consumer import clocks.

- COL–DET 824225, canonical `8b923997-fc79-483d-9444-78f088e65c52`: COL 1–DET 8, governed outcome `cd779bf5-e277-4d9c-a631-6eb3e422a0f1`, revision 1. Baseline `mlb-v18-daily-80ff0089388dd199fbeb14b70ff9465d76ea14abcc7a1be1100e3237f0f3826a`. Survival and transition each applied and imported before the original 15:55Z cutoff; one supported game with two interventions. Every arm retains 5,000 original draws.
- CIN–MIL 823734, canonical `3c7a6820-7c95-4e91-87fa-6acb89c013d7`: CIN 4–MIL 3, governed outcome `105dc37c-8fbe-4dbf-abf4-a81bfddb2194`, revision 1. Baseline `mlb-v18-daily-05f86403fb40fc60600d479b94821a46e17b91471afbf6c8ac3c48e18ceeaeaa` retains all 5,000 draws; the distinct score-limited configuration retains 4,722 original indexed draws. Excluded 278 (5.56%); limits remain 5 per played half-inning and 14 per team/game. Candidate import preceded 17:55Z.

Probabilities are fractions 0–1. MLB Brier is binary `(pHome-yHome)^2`, admitted after exact zero-tie checks. Candidate-minus-baseline negative loss, Brier, CRPS, energy or absolute error favors the candidate. Do not halve an already binary score. Home margin means home minus away. Joint energy retains the original home/away pairing. Unequal-N score-limited scores use their actual denominators; no equal-N pairing was invented. MCSE is simulation precision, not predictive-improvement uncertainty.

All arms selected the eventual winner; no picks changed. Survival has a small realized winner-score gain and mixed distribution results. Transition slightly worsens winner scores and has mixed distribution results. CIN score limits improve winner and every reported run-distribution score on this single game, but both configurations already picked CIN. This does not establish recurring improvement or offered-price profitability. No arm advances; archetype B/C remain rejected.

Starter/relief allocation assessment is unavailable: original baseline exposure counters and final-bound actual pitcher evidence are missing. Candidate summaries cannot establish allocation improvement; no counter or actual duration was invented. Whole-game scoring is complete. Use these observations in plain-language disclosures without asserting managerial causes or actual-PA calibration.

Reproduce/verify from retained evidence: `.venv/Scripts/python.exe -B scripts/assess_mlb_existing_prospective_finals_v1.py`.
No source requests, simulations, fitting, new monitor or AISP writes occurred. Existing candidate imports are previously confirmed; acknowledgement of this new formal-assessment package is not yet evidenced.
'''
    immutable(stage_dir/'CLAUDE_HANDOFF.md', handoff.encode())
    staged = {'schemaVersion': 'MLB_ADDITIVE_HANDOFF_STAGING_V1', 'createdAtUtc': datetime.now(timezone.utc).isoformat(),
        'stageDirectory': str(stage_dir), 'destinationDirectory': str(delivered), 'index': ref(stage_dir/'index.json'),
        'handoff': ref(stage_dir/'CLAUDE_HANDOFF.md'), 'files': [ref(p) for p in sorted(stage_dir.iterdir())]}
    immutable(staging_path, raw_json(staged))
    return staged


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    staged = stage()
    if not args.publish:
        print(json.dumps(staged, indent=2))
        return
    receipt_pointer = OUT/'publication-receipt.json'
    if receipt_pointer.exists():
        bound = json.loads(receipt_pointer.read_bytes())
        receipt = read(bound)
        for delivered in receipt['files']:
            verify(delivered)
        print(json.dumps({'status': 'EXISTING_PUBLICATION_VERIFIED', 'receipt': bound}, indent=2))
        return
    target = Path(staged['destinationDirectory']).resolve()
    assert target.parent == EXCHANGE.resolve() and target.name == staged['index']['sha256']
    started = datetime.now(timezone.utc).isoformat()
    delivered = [immutable(target/Path(b['path']).name, verify(b)) for b in staged['files']]
    receipt = {'schemaVersion': 'MLB_ADDITIVE_FORMAL_ASSESSMENT_PUBLICATION_V1', 'status': 'PUBLISHED',
        'publicationStartedAtUtc': started, 'publishedAtUtc': datetime.now(timezone.utc).isoformat(),
        'index': ref(target/'index.json'), 'handoff': ref(target/'CLAUDE_HANDOFF.md'), 'files': delivered,
        'fileCount': len(delivered), 'bytes': sum(b['bytes'] for b in delivered),
        'sourceStaging': ref(OUT/'staged-publication.json'), 'consumerAcknowledged': False,
        'forecastsCreatedOrChanged': 0, 'newSimulations': 0, 'providerRequests': 0, 'promotionAllowed': False}
    bound = save('publication-receipt.json', receipt)
    immutable(receipt_pointer, raw_json(bound))
    print(json.dumps({'status': 'PUBLISHED', 'index': receipt['index'], 'handoff': receipt['handoff'],
        'receipt': bound, 'fileCount': len(delivered)}, indent=2))


if __name__ == '__main__':
    main()
