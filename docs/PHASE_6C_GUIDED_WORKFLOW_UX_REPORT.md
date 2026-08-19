# Phase 6C — Fool-Proof Guided Workflow & UX Orchestration

## 1. Executive Verdict

**Status: `GUIDED_WORKFLOW_READY`.** The MLB sports project is now a guided, fool-proof workflow.
At every screen the user knows where they are, what to do, and what happens next — without
documentation, source knowledge, Claude, or trial-and-error navigation. **No analytical
functionality was removed**; this is pure orchestration and UX over the existing Phase 4/5/6
science. All 20 sidebar modules, the PA Modeling Cockpit, Simulation Studio, Model Laboratory,
Data Warehouse, governance, security, and registry evidence are preserved.

## 2. Original User Failure

The first-time walkthrough stalled: after creating a project the user landed on a passive Project
Overview showing 12 "NOT CONFIGURED" stages; the dataset said "workspace available, not bound"
with no binding action; Data Warehouse showed evidence but no project-binding action; the MLB
Workflow page showed 12 identical spec cards with no primary action. The user could not determine
where to begin.

## 3. Root Cause

Three defects: (a) **no canonical entry point** — creation routed to a passive dashboard instead
of into the workflow; (b) **no per-project workflow state or resolver** — stages showed a blanket
"NOT CONFIGURED" with no notion of READY vs BLOCKED, no blocking prerequisite, and no next action;
(c) **the workflow page was a specification, not an orchestrator** — 12 equal-weight cards with
scope/prerequisites but zero primary actions, and Stage 1 (the forecast contract) had no
configuration surface anywhere.

## 4. Workflow Architecture

New module `src/sports/workflow/`:
- **`workflowState.ts`** — the orchestration brain. Persists a per-project **forecast contract**
  and **dataset binding** (localStorage; no data copy, no duplicate registration, no governance
  change), and a single `resolveStages()` that computes each of the 12 stages' status
  (`COMPLETE`/`CURRENT`/`READY`/`BLOCKED`/`STALE`), blocking prerequisite, evidence, and primary
  action from local artifacts + governed evidence. `firstActionableStage()` and
  `completionSummary()` power Continue Work everywhere.
- **`GuidedWorkflow.tsx`** — the persistent shell: context header, 12-stage stepper, one focused
  stage workspace, Back/Continue footer.
- **`ForecastContractPanel.tsx`** — Stage 1 inline configuration.
- **`DatasetBindingPanel.tsx`** — Stage 2 inline dataset binding.
- **`WorkflowReturnBar.tsx`** — return breadcrumb for any deep-linked module.

## 5. Guided vs Workspace vs Evidence Views

Made explicit: the **guided workflow** (`/workflows/mlb`) is the sequential path; **workspace
modules** (Data Warehouse, PA Cockpit, Model Lab, Simulation Studio…) are reusable tools opened
from stages with a return breadcrumb; **evidence views** are read-only status. Advanced users
still reach every module directly from the sidebar — the guided path is the default, not a prison.

## 6. Project Creation

Creating an MLB project now routes directly to `/workflows/mlb?step=1` (the guided workflow at
Step 1) instead of the passive overview. Metadata entered at creation (sport, league, period,
lifecycle, target, secondary targets, purpose, description) is preserved and prefills Stage 1.

## 7. Project Overview

Now a status dashboard with a **dominant Continue Work action** ("Start Step 1" for a new project,
"Continue Step N" for a returning one) that routes via the canonical resolver. Completion reads
"X of 12 complete · Y ready · Z blocked" (not just a percent). Each stage card shows status, the
blocking prerequisite when blocked, and a primary action ("Complete Step N" / the action label /
"Review").

## 8. Guided MLB Workflow

`/workflows/mlb` is now the canonical guided workflow. The persistent header shows project name,
"Step X of 12 · status", the current stage title and purpose, and overall completion. A left
12-stage stepper shows real per-stage status with color and a status dot; the current stage
dominates. A Back/Continue footer disables Continue until the stage is complete and states why.
The old technical specification is preserved at `/workflows/mlb-spec` and inside each stage under
"Advanced · technical specification" (progressive disclosure) — nothing was dumbed down.

## 9. Step 1 — Forecast Contract

Fully configurable inline: forecast target, lifecycle, temporal policy, evidence mode (Enhanced /
Strict), research purpose, notes — **prefilled from project creation**. "Save & Register Forecast
Contract" registers a versioned contract, shows "✓ Step 1 complete · v1", and offers "Continue to
Baseball Data Evidence →". Completion unlocks Step 2 via the resolver.

## 10. Step 2 — Dataset Binding

Detects the already-registered governed FD1 dataset and presents it (seasons, games, plate
appearances, rights, VALID). "Use This Registered Dataset" binds it to the project (a local
reference — no data copy, no duplicate registration, immutable authority untouched); "Inspect in
Data Warehouse" is the secondary action. Success shows authority, coverage, and rights, then
"Continue to Identity, Coverage & Leakage →". Honest empty state (no dataset → open Data
Warehouse) and error state (service unreadable ≠ "no evidence", with Retry).

## 11. Step 3 — Identity/Coverage

Once bound, surfaces the registered identity/leakage evidence (identity bridge, point-in-time
review) with a "Review Identity & Leakage Evidence" action and an "Inspect full identity evidence
in Data Warehouse" secondary. Completion derives automatically from the governed evidence.

## 12. Steps 4–12 Orchestration

Each has one clear primary action routing to real existing functionality with preserved context
(`?from=mlb-workflow&step=N`): Step 4 → Player & Team State; Step 5 → Participation & Usage;
Step 6 → **PA Modeling Cockpit**; Step 7 → Simulation Studio; Step 8 → Candidate Model Laboratory;
Step 9/10 → Evaluation & Calibration; Step 11 → Model Graph & Decision; Step 12 → Registry (export
gated). Completion for 3–11 derives from registered evidence; Step 12 export stays disabled with a
clear "requires Step 11" explanation. No invented actions.

## 13. PA Modeling Cockpit Integration

The 12 program stages and the 15 cockpit model-development steps are nested, not duplicated. Step 6
opens the cockpit with `?from=mlb-workflow&step=6`, and the global return bar renders
"MLB Workflow › Step 6 › PA Modeling Cockpit · Return to MLB Workflow" above it — one component
serves every deep-linked module.

## 14. Temporal Policy

Stage 1 proposes the owner's intended policy — **Development 2021–2023 · Validation 2024 · Frozen
2025 · Prospective 2026** — reviewable/changeable before registering. A horizontal timeline renders
each season colored by role, with **2025 visually distinct (rose, ringed)** and a badge "2025
FROZEN — not used for model selection". The full 2021–2025 registered evidence is available (not
restricted to 2023–2025). Phase 6A/6B frozen-evaluation protection is unchanged (the cockpit still
fits on 2023 and never selects on 2025).

## 15. Human-Readable Evidence

Data Warehouse population composition now leads with human-readable summaries (population name, row
count, % of rows, permitted uses, prohibitions) and moves the raw serialized predicate under a
"View technical query" disclosure. Evidence bullets across the workflow read as conclusions first;
technical authority (manifest SHA, registration id) is secondary.

## 16. Blocking / Status Semantics

Five explicit states: COMPLETE (green), CURRENT/READY (cyan/blue), BLOCKED (muted), STALE (amber).
A stage is BLOCKED only when a real prerequisite is incomplete, and it names the exact blocking
step. Clicking a blocked stage shows "This stage requires Step N — …" and a "Go to Step N" button —
never a dead end. Completion derives from evidence, never from page visits.

## 17. Back / Next / Resume

A canonical `firstActionableStage()` resolver powers Continue Work on Project Overview and the
workflow's initial focus, so returning users resume exactly where they left off ("Welcome back …
Next: Step N"). The guided footer provides Previous / Continue with Continue gated on completion.
The 12-stage stepper allows jumping to any stage; completed stages are revisitable ("Review").

## 18. Data Warehouse Cleanup

Population composition made human-readable with progressive disclosure (see §15). All detailed
warehouse evidence — season coverage, family volume, temporal folds, identity bridge, source
rights, known limitations — is preserved.

## 19. Browser Acceptance

Owner-deferred (headless/authenticated environment; auth was not weakened to force automation, per
§79). The exact acceptance journeys (§75–78) are covered by the resolver + wiring tests: fresh
project → Step 1 CURRENT / 2–12 BLOCKED; after contract → Step 2 CURRENT; after binding+evidence →
downstream COMPLETE; blocked-stage redirect; new-project redirect; Continue Work; return context.
`tsc` and production build are clean.

## 20. Accessibility

Semantic `<ol>`/`<nav>`/`<button>`/`<details>` with visible focus states (retained from the design
system), action-labeled buttons ("Configure Forecast Contract", "Open PA Modeling Cockpit",
"Review Calibration & Reliability" — never bare "Open"), and disabled controls that always state
their reason. Responsive: the stepper and stage workspace stack on laptop/mobile; the header and
primary action remain visible; wide content collapses under disclosures.

## 21. Tests

- `tests/sportsGuidedWorkflow.test.mjs` — **12 passing**: resolver state transitions (fresh,
  post-contract, post-binding, binding-without-evidence honesty), action map, completion summary,
  and static wiring (guided route, spec preserved, new-project redirect, Continue Work, return bar,
  no-regression sidebar/cockpit inventory).
- Phase 6A/6B `tests/paModelingCockpit.test.mjs` — **14 passing** (unchanged).
- TypeScript clean; production build clean.

## 22. Preserved Functionality

All 20 sidebar modules retained (Data Warehouse, Player & Team State, Participation & Usage, Model
Laboratory, PA Modeling Cockpit, Simulation Studio, Evaluation & Calibration, Model Graph, Registry
& Deployment, Forward Monitoring, Research Tools, Analytics Workbench, SQL Lab, Visualization
Studio, Model Documentation, Data Sources & Rights, Users & Settings, Studio Home, Sports Projects,
Sports Workflows). No Phase 4/5/6 science, governance, security, or registry evidence changed.

## 23. Known Limitations

- Browser walkthrough owner-deferred (auth environment).
- Per-project workflow state (contract + binding) is client-side localStorage; it references the
  immutable governed dataset but is not itself a backend-registered artifact. A future phase can
  promote the forecast contract to a governed backend registration.
- "STALE / requires review" upstream-change semantics are defined in the resolver but the explicit
  invalidation-on-contract-change confirmation flow (§52) is a documented next increment.
- NFL remains the technical-spec workflow (foundation only).

## 24. Exact Next Step

Promote the forecast contract + dataset binding to governed backend registrations (so stage
completion is server-authoritative), and implement the upstream-change → downstream-STALE
confirmation flow. Then the guided flow is fully governed end to end.

### Canonical journey
CREATE PROJECT → FORECAST CONTRACT → DATA EVIDENCE → IDENTITY & LEAKAGE → PLAYER STATE →
PARTICIPATION → PA MODELING → SIMULATION → CANDIDATE LAB → TEMPORAL VALIDATION → CALIBRATION →
MODEL DECISION → EXPORT.

### Confirmations
existing analytical functionality removed = 0 · Phase 5 science changed = 0 · D3 changed = no ·
PA cockpit functionality removed = 0 · Data Warehouse functionality removed = 0 (population display
made human-readable, nothing removed) · Simulation Studio removed = 0 · Model Laboratory removed =
0 · security weakened = no · auth weakened = no · dataset governance weakened = no · provider/
network calls = 0 · AISP accessed = no · financial ATLAS accessed = no · ds-workflow-starter
accessed = no · pushes = 0 · remote changes = 0.
