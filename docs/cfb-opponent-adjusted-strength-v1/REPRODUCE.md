# Reproduce the bounded CFB strength study

Run from `C:\Users\james\asp-model-studio-source-cfb-strength` with the existing private Python environment. No acquisition script, production model, publisher, scheduler or AISP process is invoked.

The original study output is `C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1`. Its `DESIGN.json`, `DESIGN.md`, `DESIGN_CLARIFICATION_001.json` and implementation/source bindings precede comparison results. `ENVIRONMENT.json` records exact library versions. The admitted source remains at the location/hash in DESIGN.json and is private reconstructed historical evidence.

Synthetic verification:

```powershell
Set-Location C:\Users\james\asp-model-studio-source-cfb-strength
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -m pytest tests/test_cfb_opponent_strength.py tests/test_cfb_strength_study_chronology.py -q
```

For a deterministic replay, create a **new** output directory and copy the frozen design/configuration receipts into it. Preserve the original output and its selection receipt:

```powershell
$cfbOriginal = 'C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1'
$cfbReplay = 'C:\Users\james\asp-model-studio\outputs\cfb-opponent-adjusted-strength-v1-replay'
New-Item -ItemType Directory -Path $cfbReplay -ErrorAction Stop
foreach ($cfbName in @('DESIGN.json','DESIGN.md','DESIGN_CLARIFICATION_001.json','DESIGN_CLARIFICATION.md','IMPLEMENTATION_BINDING.json','ENVIRONMENT.json')) {
    Copy-Item -LiteralPath (Join-Path $cfbOriginal $cfbName) -Destination (Join-Path $cfbReplay $cfbName)
}
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B scripts/run_cfb_strength_study_v1.py --stage development --output $cfbReplay
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B scripts/run_cfb_strength_study_v1.py --stage assessment --output $cfbReplay
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B scripts/summarize_cfb_strength_study_v1.py --output $cfbReplay
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B scripts/render_cfb_strength_study_v1.py --output $cfbReplay
& C:\Users\james\asp-model-studio\.venv\Scripts\python.exe -B scripts/verify_cfb_strength_study_v1.py --output $cfbReplay
```

The Development stage rejects an output directory with an existing frozen selection. Assessment rejects a directory without one. Source reads materialize only seasons <=2022 for Development and <=2025 after selection. Here **2026 means season 2026**, which is excluded from features, fitting, tuning and scoring. The season-2025 source includes 11 nonprimary postseason context rows scheduled in January 2026; those rows were materialized by the season-filtered assessment preparation. They are not primary evaluation games and occur after its final target, November 30, 2025. No primary evaluation game occurs in calendar 2026. A season cutoff must not be described as excluding every calendar-2026 source byte. Full-object physical hashes are integrity checks, not model input reads.

The source design path and physical hashes refer to the executed worktree. Replays require those bound bytes; a checkout that changes line endings needs an explicit source-binding reconciliation, not a silently edited receipt. Replay timestamps and filesystem paths will differ; numerical predictions/scores should match with the recorded environment.

Artifacts:

- `models/strength-*.joblib`: per-UTC-date strength fits, eligible history IDs, support counts, prior precision/weight and offense/defense estimates. `features/*.parquet` retains corresponding target features.
- `models/fold-<season>-<arm>.joblib`: independently fitted preprocessing, Ridge pairs and earlier-origin margin calibration. These are research fits, not loaded production artifacts.
- `models/fold-<season>-receipt.json`: selected origin penalty and exact baseline point-prediction reconciliation.
- `FROZEN_SELECTION.json`: Development-only final penalty and A/B choice, written before later source materialization.
- `COMMON_POPULATION_PREDICTIONS.parquet`: all common point OOF games/arms, including residual warmup. `COMMON_POPULATION_SCORES.parquet`: common distribution games/arms with per-game errors, probabilities and proper scores.
- `COMPARISON.csv`, `PAIRED_EFFECTS.json`, `DECISION.json`: aggregate results, paired week-block uncertainty and literal frozen-gate decisions.
- `figures/`: scientific PNG/SVG figures; figure/source bindings accompany them. `VERIFICATION.json` records independent checks and their sampled scope.

Numerical result reports, the new standalone `EXPERIMENT_REGISTER_ENTRY.json`, fitted artifacts, predictions and plots remain in the private output directory. The original immutable experiment register is preserved. Only source code, frozen research design and reproduction instructions belong in the reviewed source workflow; this source permission does not authorize redistribution of the retained data or numerical result package.

Paired donor populations are reconstructible from each arm's earlier-season OOF prediction rows and their stored donor identity hashes. Full simulation populations are not duplicated for every historical game: the unchanged fixed-seed sampler deterministically reconstructs each 10,000-draw population. Uncertainty resamples actual calendar-week game blocks, never simulation draws.

The independent verifier replayed 18 baseline/A/B distributions across 2018, 2023 and 2025. CRPS, winner scores and energy with the frozen numerical precision reconciled within `7.1e-15`. Its separate float64 energy calculation differed by at most `9.2e-7`: the retained sampler computes the energy pair-distance term with `numpy.hypot` on int16 score differences, yielding a float32 reduction. The verifier records both calculations and a conservative floating-point reduction bound. This is an inherited precision qualification; no saved metric, model, selection threshold or advancement gate was changed.

Point-model fits and calibration exclude target-season outcomes. The chronological team-strength state legitimately uses only **earlier eligible results within the target season**, behind the common final-status/finite-score/48-hour reconstruction gate. This distinction is necessary for the dynamic challenger and is not historical completion-time certification.
