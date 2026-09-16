Three-arm pregame driver
=======================

`scripts/run_mlb_v18_three_arm_pregame_v1.py` declares one fixed remaining slate,
reads compatible ordinary V18 forecast objects, and freezes local research
populations. It does not collect sources, read game outcomes, publish, import,
fit models or create a scheduler.

The declaration pins six remaining September 12 identities from the retained
20:42 UTC scheduled-slate receipt, before outcomes. It pins the unchanged PA
artifact and treatment, the existing baseline transition, HGB survival `f64f82…`,
hierarchical transition `8c91d6…`, 5,000 draws, seed 20260907, and execution code.
Every game stops 15 minutes before its original scheduled start. No game can be
added, no baseline can be replaced after the first numerical attempt, and no
expired opportunity can be backfilled.

Run from the Studio repository:

```powershell
.venv/Scripts/python.exe scripts/run_mlb_v18_three_arm_pregame_v1.py plan
.venv/Scripts/python.exe scripts/run_mlb_v18_three_arm_pregame_v1.py run --max-games 1 --wall-seconds 600
```

The root workflow owns declaration creation and actual runs. The driver holds
the existing nonblocking ordinary-producer lock; a busy publisher yields a
deferred receipt without simulation. It reuses the exact baseline draw arrays.
`V18_SURVIVAL_ONLY` changes only the removal hook, and
`V18_TRANSITION_ONLY` changes only the transition model. Each unsupported arm
retains the identical baseline arrays and its concrete fallback reason. Only
games with both arms applied support a direct survival-versus-transition
comparison. Fallback coverage is never a component trial.

`current.json` points to an immutable status object. Its `records[].result`
references completed immutable game receipts. Each receipt retains the original
forecast ID and object digest, baseline/manifest/source/feature/execution refs,
source cutoff, execution and freeze clocks, component disposition, and a paired
NPZ with `<arm>_homeRuns`, `<arm>_awayRuns`, `<arm>_innings`, and
`<arm>_paCounts`. Existing component BF/outs arrays are retained when present;
baseline exposure values are not invented. All authority flags remain false.

`focused-checks.json` records seven pure boundary checks and authentication of
the four ordinary baselines available at review time. It loaded no models and
ran no simulations. Actual integration is verified by the first authorized
pregame run; publication and consumer confirmation require separate receipts.
