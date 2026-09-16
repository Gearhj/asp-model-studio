# Frozen V18 three-arm pregame comparison

Import precomputed research forecasts only. The unchanged ordinary V18 baseline remains the enabled default. Calibration is disabled; execution, activation and wagering authority are false.

This package contains two separately identified candidates sharing each game's exact original baseline: V18_SURVIVAL_ONLY uses the existing V1 BASE/DURATION contract; V18_TRANSITION_ONLY uses V2 BASE/TRANSITION. The V2 consumer extension is still required. No consumer import or display is confirmed by this package.

| Configuration | Source game | Canonical game | Exact forecast ID | Exact baseline forecast ID |
|---|---|---|---|---|
| V18_SURVIVAL_ONLY | 824225 | 8b923997-fc79-483d-9444-78f088e65c52 | mlb-v18-survival-e2be2661fa1f72156096dd3b16087e5cc98ccd329bf299a89653de06851edac1 | mlb-v18-daily-80ff0089388dd199fbeb14b70ff9465d76ea14abcc7a1be1100e3237f0f3826a |
| V18_TRANSITION_ONLY | 824225 | 8b923997-fc79-483d-9444-78f088e65c52 | mlb-v18-transition-e2be2661fa1f72156096dd3b16087e5cc98ccd329bf299a89653de06851edac1 | mlb-v18-daily-80ff0089388dd199fbeb14b70ff9465d76ea14abcc7a1be1100e3237f0f3826a |

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
& '..\.venv\Scripts\python.exe' -c $candidateImport 'C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1\survival-starter-coverage-v1\packages\sha256\eed95fe30e7c70cf0d88a8f4e8d4a82fc89e1f27e864b5bc088cef6dafb926ad\V18_SURVIVAL_ONLY\aisp-handoff.json'
```

For TRANSITION, first extend the existing consumer to accept HANDOFF_V2 plus TRANSITION only under V2, retain the V1 child forecast/object schemas and existing baseline/clock/idempotency checks, and persist the actual handoff version in bundle.contract_version. Then run the same command with this exact handoff:

```powershell
& '..\.venv\Scripts\python.exe' -c $candidateImport 'C:\Users\james\asp-model-exchange\mlb-v18-ensemble-research-v1\survival-starter-coverage-v1\packages\sha256\eed95fe30e7c70cf0d88a8f4e8d4a82fc89e1f27e864b5bc088cef6dafb926ad\V18_TRANSITION_ONLY\aisp-handoff.json'
```

Current candidate_comparison selects one latest candidate and the latest baseline. Add a configuration selector and bind the displayed baseline by the candidate's stored baselineForecastId so both separate comparisons remain inspectable. An old imported ensemble replay does not establish support for these candidates.

The original three assessment studies remain separate. COL–DET824227 and NYM–NYY823496 require a provenance-bearing FINAL revision; KC–BOS824712 requires a persisted eligible final. The governed game_final_outcomes record must include FINAL status, revision/source and required clocks. Core score columns cannot replace that record. Do not infer unavailable starter BF or transition sequences.

Scoring command: `.\.venv\Scripts\python.exe scripts/score_mlb_frozen_component_pairs_v1.py` in Model Studio. The original paired identities and scoring rules stay fixed; no new Monte Carlo run is needed to score them.

After import, return exact forecast IDs, imported/already-present/rejected counts, bundle contract version and consumer receipt path. Report display confirmation separately. A few observed games establish integration and measurement, not predictive superiority.
