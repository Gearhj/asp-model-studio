# Phase 6C.2 — Unified MLB Project Workspace

## 1. Executive Verdict

**Status: `UNIFIED_PROJECT_WORKSPACE_READY`.** The 12-stage MLB workflow is now a **continuous
project workspace**, not a traffic controller. Steps 4–11 render the real analytical content
**inside the workflow shell** — the user never has to leave the MLB project to review player state,
participation, develop PA models, simulate, evaluate, or inspect the model graph. The embedded
content reuses the exact same components as the standalone modules (no duplication, no iframes),
and the standalone sidebar routes remain fully available for expert use.

## 2. The Structural Defect

Phase 6C/6C.1 fixed navigation and evidence honesty, but Steps 4–11 still routed the user **out**
to standalone pages (`/player-team-state`, `/participation-usage`, `/pa-modeling-cockpit`, …) with a
"Return to MLB Workflow" breadcrumb. The workflow acted as a dispatcher rather than a workspace.

## 3. Unified Architecture (reuse, not duplicate)

The minimal reuse boundary: the analytical bodies of the standalone modules were extracted so a
single implementation serves both contexts.
- `Phase4Surfaces.tsx`: `PlayerTeamStatePage` / `ParticipationUsagePage` now wrap exported
  `PlayerTeamStateBody` / `ParticipationUsageBody`. The standalone pages keep their hero; the bodies
  render context-free.
- `PaModelingCockpit` gained an `embedded` prop that suppresses its standalone hero (the workflow
  shell provides project identity/progress).
- `GuidedStageContent.tsx` composes each guided step's workspace from the already-exported section
  components (`GameReplaySection`, `BaseOutTransitionSection`, `WholeGameMonteCarloSection`,
  `Phase4ModelLaboratorySection`, `Phase4EvaluationSection`, `Phase4GraphSection`,
  `StarterIdentitySection`, `ParticipationAblationSection`, `CatcherInfluenceReadinessSection`, …).

No `<iframe>`, no duplicated analytical logic, no parallel science path.

## 4. Continuous Shell

`GuidedWorkflow` keeps a stable shell across all 12 steps: project title, program progress
(complete / ready / available / blocked), a **collapsible** 12-stage navigator, the current stage
header, and Previous/Continue. Only the central analytical workspace changes as the user moves
through steps. The navigator can collapse to a thin numbered rail so the embedded cockpit /
simulation content gets full width on laptop screens.

## 5. Step-by-Step

- **Steps 1–3** — unchanged inline (forecast contract, dataset binding, identity/leakage evidence);
  auto-advance preserved; no interstitials.
- **Step 4 — Hitter & Pitcher State** — embeds `PlayerTeamStateBody` beneath an **adopted
  player-state baseline** summary (bounded Y−1 batter/pitcher prior coverage per season). Optional /
  advanced research (dynamic state, E1, E2, severe-miss) renders with honest status and does **not**
  make the page look empty or block progress. Primary: **Accept Player-State Baseline & Continue**.
- **Step 5 — Participation & Usage** — embeds `ParticipationUsageBody` (lineup / starter-duration /
  bullpen component statuses, plus starter-identity, participation-ablation, and catcher-readiness
  evidence). Honest per-component status; no blank page.
- **Step 6 — Plate-Appearance Models** — embeds the **full Phase 6A/6B PA Modeling Cockpit**
  (`<PaModelingCockpit embedded />`) with its own 15-stage navigation (Objective → … → Registry;
  **Outliers before Missing Values** preserved). The user develops PA models **without leaving the
  MLB project**. The nested 15-stage model workflow stays distinct from the 12-stage program
  workflow (no 27-step flattening).
- **Step 7 — Game Simulation** — embeds replay, base-out transition, simulation input, and
  whole-game Monte Carlo sections.
- **Step 8 — Candidate Model Laboratory** — embeds the Phase 4 component candidate ledger.
- **Steps 9–10 — Temporal Validation / Calibration** — embed the Phase 4 evaluation/reliability
  evidence.
- **Step 11 — Model Graph & Decision** — embeds the research graph + registry sections.
- **Step 12 — Export** — inline export gate with the exact missing prerequisite.

## 6. Expert Escape (optional)

Each embedded workspace offers a subordinate **"Open full <module> ↗"** link (adds
`?from=mlb-workflow&step=N`, so the Return-to-MLB-Workflow breadcrumb appears there). Normal guided
usage **never requires** the return breadcrumb — it exists only for a deliberate expert detour.

## 7. Program vs Model Workflow

Preserved: the **12-stage MLB program workflow** and the nested **15-stage PA model-development
workflow** (inside Step 6) remain distinct concepts, not merged.

## 8. Project-Evidence Semantics

Unchanged from Phase 6C.1 and correct: existing workspace evidence shows **Available / Adopt &
Continue**, never auto-COMPLETE; completion progresses only as the project adopts each stage. Step 6
adopts via **Adopt Current PA Champion & Continue**.

## 9. Step 5 Evidence Reconciliation

The standalone "Components recorded 0/3 · NOT CONFIGURED" reflects what the backend assembles into
`phase4.components` for the active study; this UX pass **surfaces the truth inline and adds the
registered Phase 5 starter-identity / participation-ablation / catcher-readiness evidence** rather
than a bare empty page. No research was re-run and no availability was fabricated (§19 honored).

## 10. Preserved Functionality

All 20 sidebar modules and standalone routes (`/player-team-state`, `/participation-usage`,
`/pa-modeling-cockpit`, `/simulation-studio`, `/model-laboratory`, `/model-graph`,
`/registry-deployment`, …) are intact and unchanged. The standalone Player & Team State and
Participation & Usage pages render the same content via the shared bodies (zero regression). No
Phase 4/5/6 science, governance, security, or registry evidence changed. The owner's project,
Strict-Pregame contract, and temporal policy (2021–2023 / 2024 / 2025 frozen / 2026) are preserved.

## 11. Browser Acceptance

Owner-deferred (headless/authenticated environment; auth not weakened). The continuous-shell journey
(Steps 1→6 without leaving the workflow, Step 6 opening the embedded cockpit) is covered by tests.
`tsc` + production build clean.

## 12. Tests

`tests/sportsGuidedWorkflow.test.mjs` — **20 passing** (14 from 6C/6C.1 + 6 new): guided steps 4–11
embed content in-shell; Step 6 embeds the PA cockpit (reuse, `embedded` prop, hero suppressed);
Steps 4/5 reuse the shared `*Body` components; standalone pages and routes preserved; optional
expert escape (no iframe); Step 4 shows adopted baseline + honest optional research. Phase 6A/6B
`paModelingCockpit.test.mjs` — **14 passing** (unchanged). tsc + build clean; no backend changes.

## 13. Known Limitations

- The double-nav on Step 6/7 (workflow rail + cockpit nav) is dense on ≤1024px; the collapsible
  workflow navigator mitigates it. Mobile collapses the navigator but the embedded cockpit remains a
  desktop-oriented workspace.
- Contract / binding / adoptions remain client-side localStorage references (documented Phase 6C
  limitation; backend-governed registration is the next increment).
- Step 5/downstream evidence depth depends on what the backend assembles into the active study; this
  pass surfaces it honestly and does not re-run research.

## 14. Exact Next Step

**Return to scientist modeling.** The unified workspace is ready: open the current project, walk
Steps 1→6, and develop PA-model experiments inside Step 6. Engineering-wise, the remaining item is
promoting contract/binding/adoptions to governed backend registrations.

### Confirmations
Phase 5 science changed = 0 · D3 changed = no · model retraining = 0 · Monte Carlo = 0 ·
new baseball research = 0 · provider/network calls = 0 · security weakened = no · auth weakened = no
· dataset governance weakened = no · iframes used = 0 · duplicate cockpit built = 0 · PA Cockpit /
Data Warehouse / Player & Team State / Participation / Simulation Studio / Model Laboratory removed =
0 · AISP accessed = no · financial ATLAS accessed = no · ds-workflow-starter accessed = no ·
pushes = 0 · remote changes = 0.
