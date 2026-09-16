MLB pregame comparison: 2026-09-12. Verdict: insufficient assessment evidence.

Existing frozen studies: 0 scored and 3 pending. Candidate-minus-baseline losses below zero favor the candidate; signed run error is predicted minus observed.

| Existing study | Status / prerequisite | Δ log loss | Δ Brier |
|---|---|---:|---:|
| 2026-09-11 COL-DET duration (824227) | PROVENANCE_BEARING_FINAL_REQUIRED | — | — |
| 2026-09-12 NYM-NYY transition (823496) | PROVENANCE_BEARING_FINAL_REQUIRED | — | — |
| 2026-09-12 KC-BOS transition (824712) | PERSISTED_FINAL_NOT_AVAILABLE | — | — |

COL–DET is the September 11 game 824227. NYM–NYY lacks retained candidate distributions, so candidate CRPS, intervals and joint scores remain unavailable. Missing starter BF or transition sequences does not prevent eligible whole-game scoring. [Exact final requirements and scoring evidence](<C:/Users/james/asp-model-studio/outputs/mlb-v18-three-arm-pregame-comparison-v1/scoring/objects/sha256/56db3b1ad642ad7b1a8f4894c43394aad1b29ee025198cf0dbdc9a5f4fda30ad/scoring-findings.json>).

Future cohort: **6 declared; 5 locally frozen; 5 games / 10 candidate forecasts exchange-published; 0 imports confirmed**. Supported games: survival 0, transition 5, common 0. Fallback arms: 5; blocked/pending games: 1. Stopping boundary: 2026-09-13T01:25:00+00:00.

Cells show home-win probability / mean total runs. Changes are candidate minus baseline in percentage points / runs: **forecast changes, not accuracy gains**. F = exact baseline fallback; pending cells have no frozen comparison.

| Game / MLBAM | V18 base | Survival | Transition | Δ survival | Δ transition |
|---|---:|---:|---:|---:|---:|
| HOU–TB / 822927 | 55.36% / 8.622 | 55.36% / 8.622 F | 55.38% / 8.606 | +0.00 / +0.000 | +0.02 / -0.016 |
| CIN–MIL / 823737 | 63.46% / 8.205 | 63.46% / 8.205 F | 63.80% / 8.164 | +0.00 / +0.000 | +0.34 / -0.041 |
| PHI–ATL / 824870 | 48.50% / 8.738 | 48.50% / 8.738 F | 48.08% / 8.710 | +0.00 / +0.000 | -0.42 / -0.028 |
| CWS–STL / 823009 | 46.02% / 8.323 | 46.02% / 8.323 F | 46.32% / 8.208 | +0.00 / +0.000 | +0.30 / -0.116 |
| TEX–AZ / 825035 | 55.52% / 9.613 | 55.52% / 9.613 F | 55.72% / 9.581 | +0.00 / +0.000 | +0.20 / -0.032 |
| 824955 | Awaiting confirmed away lineup and its source timestamp | — | — | — | — |

Fallback prerequisites: Certified pre-cutoff starter-history mappings are unresolved for AWAY pitcher 641835, HOME pitcher 641816; Certified pre-cutoff starter-history mappings are unresolved for AWAY pitcher 656794, HOME pitcher 681517; Certified pre-cutoff starter-history mappings are unresolved for AWAY pitcher 663567, HOME pitcher 693855; Certified pre-cutoff starter-history mappings are unresolved for AWAY pitcher 663903, HOME pitcher 675660; Certified pre-cutoff starter-history mappings are unresolved for AWAY pitcher 677958, HOME pitcher 694297.

[Survival history evidence](<C:/Users/james/asp-model-studio/outputs/mlb-v18-three-arm-pregame-comparison-v1/survival-support-gap.json>): the registry covers only pilot pitchers 664285/690279 through 2026-09-10. It lacks the required current-starter coverage; repairing identity mappings alone is insufficient.

Absent-baseline dispositions use the [saved ordinary tick](<C:/Users/james/asp-model-studio/outputs/mlb-v18-unattended-v1/objects/sha256/48405ef57470e0e3fd74009b39dd1e6e6ca606f3bf55c713d303a17776457453/tick.json>) completed 2026-09-12T22:05:52.740045+00:00.

The unchanged V18 PA estimator, preprocessing and default authority remain fixed. Survival and transition are separate interventions; calibration stays disabled. Only common supported games can compare the two interventions directly. The fitted model's inherited training chronology remains uncertified. No superiority claim follows from these integrations or from 5,000 Monte Carlo draws per game.

Claude handoff (EXCHANGE_PUBLISHED):

- [V18_SURVIVAL_ONLY](<C:/Users/james/asp-model-exchange/mlb-v18-ensemble-research-v1/three-arm-pregame-comparison-v1/packages/sha256/150b2002fba9d12fa84f7855ffb6e67e94f86300f342e1d841d6525648ebeb5b/V18_SURVIVAL_ONLY/aisp-handoff.json>) — SHA256 `5fb9787f18f1e4252a69ae7adc7707e17144a89705118c2f463fffe5777c1ab1`.
- [V18_TRANSITION_ONLY](<C:/Users/james/asp-model-exchange/mlb-v18-ensemble-research-v1/three-arm-pregame-comparison-v1/packages/sha256/150b2002fba9d12fa84f7855ffb6e67e94f86300f342e1d841d6525648ebeb5b/V18_TRANSITION_ONLY/aisp-handoff.json>) — SHA256 `ab928e3ea4cfad47d515eb3dc3169bc8dc3a70bb0cff89427998fd733deb30a2`.

[Exact import command and consumer prerequisites](<C:/Users/james/asp-model-studio/outputs/mlb-v18-three-arm-pregame-comparison-v1/packages/sha256/150b2002fba9d12fa84f7855ffb6e67e94f86300f342e1d841d6525648ebeb5b/CLAUDE_HANDOFF.md>). V1 survival import verification and V2 TRANSITION support are distinct from actual imports. Confirm imports/display separately; the existing consumer must retain exact baseline identity and configuration selection.

[Consumer verification](<C:/Users/james/asp-model-studio/outputs/mlb-v18-three-arm-pregame-comparison-v1/consumer-final-checks-v3.json>): survival V1 and exact stored baseline binding passed. The current consumer refuses the V2 TRANSITION envelope.

NFL restoration: scheduler ACTIVE. Original deadline 2026-09-12T20:52:51.349Z; [actual restoration](<C:/Users/james/asp-model-studio/outputs/mlb-starter-duration-paired-research-v1/monitoring/objects/sha256/a125c31da1b1e5121f7bf7361b79fc051a7d728982444652f58eef9d5b05550a/monitor-event.json>) at 2026-09-12T20:55:30.619329Z and [actual archive run](<C:/Users/james/asp-model-studio/outputs/mlb-starter-duration-paired-research-v1/monitoring/objects/sha256/a8c7857585402721cc13861a5ca5e7717de6764fb70161a6637169aeb3871842/monitor-event.json>) at 2026-09-12T20:55:41.182294Z. Both preceded this task's 20:56 UTC start.

Run in Model Studio:
```powershell
.venv/Scripts/python.exe scripts/score_mlb_frozen_component_pairs_v1.py
.venv/Scripts/python.exe scripts/run_mlb_v18_three_arm_pregame_v1.py plan
.venv/Scripts/python.exe scripts/run_mlb_v18_three_arm_pregame_v1.py run --max-games 1 --wall-seconds 1200
.venv/Scripts/python.exe scripts/package_mlb_v18_three_arm_pregame_comparison_v1.py --export
.venv/Scripts/python.exe scripts/report_mlb_v18_three_arm_comparison_v1.py
```

Use the bounded run only for still-eligible declared games; preserve original deadlines and existing locks. Task commit: 915e03608506ec0b59d9adf1d500f1cd257453f7.
