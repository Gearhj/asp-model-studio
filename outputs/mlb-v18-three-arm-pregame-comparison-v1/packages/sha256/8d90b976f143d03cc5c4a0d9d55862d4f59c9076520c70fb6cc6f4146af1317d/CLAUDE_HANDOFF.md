# Frozen V18 three-arm pregame comparison

Import precomputed research forecasts only. The unchanged ordinary V18 baseline remains the enabled default. Calibration is disabled; execution, activation and wagering authority are false.

This package contains two separately identified candidates sharing each game's exact original baseline: V18_SURVIVAL_ONLY uses the existing V1 BASE/DURATION contract; V18_TRANSITION_ONLY uses V2 BASE/TRANSITION. The V2 consumer extension is still required. No consumer import or display is confirmed by this package.

| Configuration | Source game | Canonical game | Exact forecast ID | Exact baseline forecast ID |
|---|---|---|---|---|
| V18_SURVIVAL_ONLY | 824870 | 896b29fb-fb83-47ce-a15a-a16d44e6eda1 | mlb-v18-survival-42b4ad65cc24ed31b5d5aeb37fc9b30d491568f3943571059f66c3b8189f377b | mlb-v18-daily-5af32a236f9ee77727237540f4b89a9184ba7dbc8ce632e3e535e2104e5c81c0 |
| V18_SURVIVAL_ONLY | 823009 | fa05b07a-6934-4bb6-b2f9-17fd061d5548 | mlb-v18-survival-53d12ce777066cf905b69a9bd21b691aad256cf15531ad988ecaa4ef2281939a | mlb-v18-daily-b0e596435f2a629f77076b50b5352ac1ab528cf8c2ef7f2ea756868f41f5a412 |
| V18_SURVIVAL_ONLY | 822927 | e45caaf3-91b4-43c9-b316-2624eee29705 | mlb-v18-survival-716d3d7425aa5300baf80a41a47afefb07058bdc7a0fa5608c03060a6bdb0d3f | mlb-v18-daily-f017c7477ed01a04f618ec93f159d5a4cd0fb4c83dd782b70b632bb84c1191cf |
| V18_SURVIVAL_ONLY | 823737 | 4611976b-ed57-4648-951d-f2f86bfc636a | mlb-v18-survival-bb92168f8d64fb87f86065aac2e9c47263bd580c5d72f3aa5614aeaa3857a691 | mlb-v18-daily-ee6bea843eac4933181dc5b33719c9f8edf78fe7dd89752ec5824fa6073e665a |
| V18_TRANSITION_ONLY | 824870 | 896b29fb-fb83-47ce-a15a-a16d44e6eda1 | mlb-v18-transition-42b4ad65cc24ed31b5d5aeb37fc9b30d491568f3943571059f66c3b8189f377b | mlb-v18-daily-5af32a236f9ee77727237540f4b89a9184ba7dbc8ce632e3e535e2104e5c81c0 |
| V18_TRANSITION_ONLY | 823009 | fa05b07a-6934-4bb6-b2f9-17fd061d5548 | mlb-v18-transition-53d12ce777066cf905b69a9bd21b691aad256cf15531ad988ecaa4ef2281939a | mlb-v18-daily-b0e596435f2a629f77076b50b5352ac1ab528cf8c2ef7f2ea756868f41f5a412 |
| V18_TRANSITION_ONLY | 822927 | e45caaf3-91b4-43c9-b316-2624eee29705 | mlb-v18-transition-716d3d7425aa5300baf80a41a47afefb07058bdc7a0fa5608c03060a6bdb0d3f | mlb-v18-daily-f017c7477ed01a04f618ec93f159d5a4cd0fb4c83dd782b70b632bb84c1191cf |
| V18_TRANSITION_ONLY | 823737 | 4611976b-ed57-4648-951d-f2f86bfc636a | mlb-v18-transition-bb92168f8d64fb87f86065aac2e9c47263bd580c5d72f3aa5614aeaa3857a691 | mlb-v18-daily-ee6bea843eac4933181dc5b33719c9f8edf78fe7dd89752ec5824fa6073e665a |

Each object preserves source cutoff, original capturedAt/freeze, scheduled start, policy cutoff, component status, seed 20260907, 5,000 paired draws and exact configuration/component identities. The publication receipt separately records first actual exchange publication time. Fallback forecasts reuse exact baseline draws and do not count as component trials.

Import the named ordinary V18 baseline IDs first if absent. Use the existing Windows-owned ordinary V18 handoff and server/scripts/mlb_v18_daily_slate.py import --handoff <immutable ordinary handoff> --receipt <consumer-owned receipt path>. Do not substitute a newer baseline forecast for the named ID.

Run the survival import from PowerShell after the package has actually been exported:

```powershell
Set-Location 'C:\Users\james\ai-sports-predictor\server'
$candidateImport = @'
import sys,json
from pathlib import Path
from dataclasses import asdict
from app.db.session import SessionLocal
from app.shadow_import.mlb_ensemble_candidate import verify_package,register_package
verified = verify_package(Path(sys.argv[1]))
if verified.rejected or not verified.forecasts:
    raise ValueError('Package rejected or empty: '+repr(verified.rejected))
with SessionLocal() as session:
    receipt = register_package(session, verified)
    session.commit()
    print(json.dumps(asdict(receipt), default=str))
'@
& '..\.venv\Scripts\python.exe' -c $candidateImport 'C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1\three-arm-pregame-comparison-v1\packages\sha256\8d90b976f143d03cc5c4a0d9d55862d4f59c9076520c70fb6cc6f4146af1317d\V18_SURVIVAL_ONLY\aisp-handoff.json'
```

For TRANSITION, first extend the existing consumer to accept HANDOFF_V2 plus TRANSITION only under V2, retain the V1 child forecast/object schemas and existing baseline/clock/idempotency checks, and persist the actual handoff version in bundle.contract_version. Then run the same command with this exact handoff:

```powershell
& '..\.venv\Scripts\python.exe' -c $candidateImport 'C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1\three-arm-pregame-comparison-v1\packages\sha256\8d90b976f143d03cc5c4a0d9d55862d4f59c9076520c70fb6cc6f4146af1317d\V18_TRANSITION_ONLY\aisp-handoff.json'
```

Current candidate_comparison selects one latest candidate and the latest baseline. Add a configuration selector and bind the displayed baseline by the candidate's stored baselineForecastId so both separate comparisons remain inspectable. An old imported ensemble replay does not establish support for these candidates.

The original three assessment studies remain separate. COL–DET824227 and NYM–NYY823496 require a provenance-bearing FINAL revision; KC–BOS824712 requires a persisted eligible final. The governed game_final_outcomes record must include FINAL status, revision/source and required clocks. Core score columns cannot replace that record. Do not infer unavailable starter BF or transition sequences.

Scoring command: `.\.venv\Scripts\python.exe scripts/score_mlb_frozen_component_pairs_v1.py` in Model Studio. The original paired identities and scoring rules stay fixed; no new Monte Carlo run is needed to score them.

Pinned existing-pair scoring receipt SHA-256: `56db3b1ad642ad7b1a8f4894c43394aad1b29ee025198cf0dbdc9a5f4fda30ad`; copied as `existing-pair-scoring-findings.json`.

After import, return exact forecast IDs, imported/already-present/rejected counts, bundle contract version and consumer receipt path. Report display confirmation separately. A few observed games establish integration and measurement, not predictive superiority.
