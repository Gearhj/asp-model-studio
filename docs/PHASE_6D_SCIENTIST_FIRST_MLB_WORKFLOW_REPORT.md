# Phase 6D — Scientist-First MLB Workflow Consolidation

## 1. Executive Verdict

**Status: `SCIENTIST_FIRST_WORKFLOW_READY`.** The MLB program workflow is consolidated from **12
stages to 9**, each a real scientist activity or governed decision. Data Evidence and Identity/
Leakage are merged into one **Data Evidence & Quality** stage; **PA Model Development** is now
Stage 3 — reachable immediately after reviewing the data, with no mandatory player-state or
participation page in between. Player-state research (Y-1 priors, dynamic state, E1, E2, handedness)
is relocated into the cockpit's **Feature Engineering** as feature families; severe-miss forensics
into the cockpit's **Evaluation**. **No science changed, no evidence deleted, no modules removed,
zero backend changes.**

## 2. Why the 12-Stage Workflow Was Wrong

Top-level stages were internal research components, not scientist decisions. Identity/Leakage is
data governance (belongs with the dataset). Hitter & Pitcher State had no required decision — its
research belongs where the scientist chooses features. Severe-miss forensics is model diagnostics.
Participation matters for whole-game forecasting, not PA-model development. The workflow read like a
guided tour of every artifact rather than a modeling environment.

## 3. Scientist-First Design Principle

Top-level program stages must correspond to a real scientist activity (configure / inspect / select
/ compare / analyze / validate / decide / export). Internal research components are relocated to the
moment they inform a decision — evidence, not architecture.

## 4. New 9-Stage Program Workflow

| # | Stage | Scientist does |
|---|---|---|
| 1 | Project & Forecast Objective | **CONFIGURE** the target, temporal policy, evidence mode |
| 2 | Data Evidence & Quality | **REVIEW & DECIDE** — see the data + identity/leakage; accept it for modeling |
| 3 | PA Model Development | **ANALYZE / BUILD** — the embedded 15-stage PA Modeling Cockpit |
| 4 | Participation & Game Context | **REVIEW & DECIDE** the lineup/starter/bullpen components for simulation |
| 5 | Game Simulation | **ANALYZE** whole-game score distributions |
| 6 | Candidate Comparison | **COMPARE** forecasting-system candidates & ensembles |
| 7 | Validation & Calibration | **VALIDATE** 2024/2025 performance, reliability, subgroups |
| 8 | Champion Decision | **DECIDE** the governed component graph + terminal decision |
| 9 | Export / Deployment | **EXPORT** the approved bundle (gated) |

The 15-stage PA Modeling Cockpit is nested inside Stage 3 and is **not** counted as program stages
(Outliers-before-Missing preserved).

## 5. Old-to-New Stage Mapping

| Old (12) | New (9) |
|---|---|
| 1 Objective | 1 Objective |
| 2 Data Evidence | 2 Data Evidence & Quality |
| 3 Identity, Coverage & Leakage | **2** (merged) |
| 4 Hitter & Pitcher State | **relocated → cockpit Feature Engineering** (not a program stage) |
| 5 Participation | 4 |
| 6 Plate-Appearance Models | 3 |
| 7 Base-Out Simulation | 5 |
| 8 Candidate Model Lab | 6 |
| 9 Temporal Validation | 7 |
| 10 Calibration & Reliability | 7 (merged) |
| 11 Model Graph & Decision | 8 |
| 12 Export | 9 |

`LEGACY_STEP_TO_STAGE` implements this for old `?step=N` bookmarks; adoption records migrate via
`LEGACY_ADOPTION_MAP` (old 3→2, 6→3, 5→4, 7→5, 8→6, 9/10→7, 11→8, 12→9; old 4 dropped).

## 6. Data Evidence + Quality Consolidation

Stage 2 is one workspace: the Phase 6C.5 real dataset preview (rows/columns/seasons/target/
missingness/schema/roles/25-row preview/season+sample+search controls) **plus** an inline
`DataQualitySummary` — identity mapping / unresolved / ambiguous (from `identityBridge.joinAudit`),
point-in-time / leakage gate (`noNamesOrFuzzyMatching`), Y-1 prior coverage per season (`featureAudit
.perSeasonRows`), known limitations, and a "Is this dataset suitable for modeling?" chip strip.
Technical identity-bridge hashes/authority live under a "Technical authority & lineage" disclosure.
Completing Stage 2 (Accept Data & Continue) leads directly to Stage 3 — no separate Identity stage.

## 7. Player-State Research Relocation

`PlayerStateFeatureFamilies` in cockpit **06 Feature Engineering**: **Y-1 priors** appear as
toggleable base families (Prior-season batter state, Prior-season pitcher state, Missing-history
indicators — Include/Exclude in a challenger). **Dynamic recent-form state, E1, E2, Handedness/
platoon** appear as advanced research families with honest status (RESEARCH ONLY / NOT CONFIGURED)
and one-line prior-research findings + "View evidence ↗". A "APPLIES TO NEW CHALLENGER" badge makes
clear selections never mutate the immutable D3 champion.

## 8. E1/E2 Feature-Family Integration

E1 → "Marginal positive predictive value." E2 → "Negative aggregate incremental value; K/BB
subclasses improved." Both are feature families guided by their registered ablation evidence, not
program stages or standalone walls.

## 9. Severe-Miss Diagnostic Relocation

The registered Phase 4F `SevereMissForensicsSection` now renders in cockpit **11 Evaluation** (as
error analysis — where the model fails), shown even before a challenger run. It is no longer in
Player State or a program stage.

## 10. Calibration Relocation

Calibration lives in cockpit **12 Calibration** (Phase 6A reliability curves) and program Stage 7
(Validation & Calibration) via the Phase 4 evaluation evidence — not buried in Player State.

## 11. Participation & Game Context

Program Stage 4 reuses `ParticipationUsageBody` (lineup / starter-duration / bullpen component status
+ starter-identity / ablation / catcher readiness) — framed as preparation for whole-game
forecasting, with adopt-and-continue, not a mandatory report before modeling.

## 12–16. Simulation / Candidates / Validation / Decision / Export

Stage 5 reuses the Phase 5 replay / base-out transition / simulation-input / whole-game Monte Carlo
sections; Stage 6 the Phase 4 candidate ledger; Stage 7 the Phase 4 evaluation/calibration evidence;
Stage 8 the model graph + registry; Stage 9 the gated export. All reuse existing components (no
duplication, no iframes).

## 17. Current Project Migration

For **MLB Plate Appearance Modeling – Gen 2**, the legacy adoption `[3]` (identity) migrates to
`[2]`, yielding **Stage 1 COMPLETE, Stage 2 COMPLETE, Stage 3 (PA Model Development) CURRENT**,
Stages 4–9 pending. Contract, binding, target, temporal policy, and Strict-Pregame choice are
preserved; the legacy adoption key is never destroyed. Completion recalculates against **9** (no
obsolete /12 denominator).

## 18. Backward-Compatible Routing

Canonical route is `/workflows/mlb?stage=N` (1–9). Old `?step=N` bookmarks map forward via
`LEGACY_STEP_TO_STAGE`; the return breadcrumb accepts either. No redirect loops.

## 19. Browser Acceptance

The live local stack is running with these changes (vite dev HMR picks up the saved files, backend
unchanged), so reloading the app renders the 9-stage workflow. Interactive click-through is
owner-deferred (no in-session browser automation; auth not weakened). The journey is covered by the
9-stage resolver + wiring tests: fresh → Stage 1; after data acceptance → Stage 3 (PA modeling)
directly; migration; data+identity merge; relocation of player-state and severe-miss.

## 20. Tests

`tests/sportsGuidedWorkflow.test.mjs` — **15**: 9 canonical stages in order; fresh/after-contract/
after-data states; **PA Model Development is Stage 3 reachable right after data**; data+identity
merge; **adoption migration 12→9**; legacy step→stage mapping; routing; 9-stage completion; player-
state relocation into Feature Engineering; severe-miss relocation into Evaluation; standalone modules
preserved. `paModelingCockpit.test.mjs` — **16**. Backend `route-contract` + `data-preview` — **10**.
TypeScript clean; production build clean.

## 21. Preserved Scientific Evidence

Nothing deleted. D3, D0–D4, E1, E2, Phase 4F severe-miss, Phase 5 replay/base-out/Monte Carlo,
participation ablation, starter identity, frozen 2025 metrics — all unchanged (evidence moved in the
UI only; **zero backend changes**). All standalone expert modules retained.

## 22. Known Limitations

- Interactive browser walkthrough owner-deferred.
- Contract/binding/adoptions remain client-side localStorage (documented Phase 6C limitation).
- Participation/simulation/candidate stages reuse existing Phase 4/5 evidence sections; deeper
  project-scoped participation configuration is future work.

## 23. Exact Next Scientist Action

Open **MLB Plate Appearance Modeling – Gen 2 → Stage 3 — PA Model Development → 03 Data Profile**,
and begin the first Gen-2 experiment by examining Information Value, Mutual Information, target
distribution, feature distributions, missingness, outliers, and temporal stability **before**
selecting the first challenger feature set. (Do not launch that experiment yet — this phase was the
consolidation.)

### Information Architecture
```
MLB PROGRAM
 1 Project & Forecast Objective
 2 Data Evidence & Quality        (dataset preview + identity/coverage/leakage quality)
 3 PA Model Development
     01 Objective · 02 Data & Population · 03 Data Profile · 04 Outliers · 05 Missing Values
     06 Feature Engineering (incl. player-state feature families: Y-1 priors, dynamic, E1, E2, platoon)
     07 Player Segmentation · 08 Temporal Split · 09 Model Laboratory · 10 Hyperparameter Tuning
     11 Evaluation (incl. severe-miss error analysis) · 12 Calibration · 13 Simulation Impact
     14 Champion / Challenger · 15 Registry & Evidence
 4 Participation & Game Context
 5 Game Simulation
 6 Candidate Comparison
 7 Validation & Calibration
 8 Champion Decision
 9 Export / Deployment
```

### Confirmations
program stages before = 12 · program stages after = 9 · scientific evidence deleted = 0 · modeling
functionality removed = 0 · PA cockpit / Data Warehouse / Player & Team State / Participation /
Simulation Studio / Model Laboratory / Evaluation / Model Graph functionality removed = 0 · D3
changed = no · Phase 4 science changed = no · Phase 5 science changed = no · model retraining = 0 ·
new feature research = 0 · Monte Carlo = 0 · provider/network calls = 0 · auth weakened = no ·
security weakened = no · dataset governance weakened = no · current project recreated = no ·
duplicate dataset registration = no · old artifacts re-run = no · backend changed = no · pushes = 0 ·
remote changes = 0 · main modified = no.
