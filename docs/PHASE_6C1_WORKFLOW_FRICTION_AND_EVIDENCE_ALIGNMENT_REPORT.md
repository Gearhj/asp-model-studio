# Phase 6C.1 — Guided Workflow Friction + Project-Evidence Alignment Repair

## 1. Executive Verdict

**Status: `WORKFLOW_EVIDENCE_ALIGNED`.** The live-walkthrough defects are fixed. Steps 1 and 2
auto-advance (no dead interstitials), Step 3 reviews identity/leakage evidence inline (and the
broken Studio-Home route is gone), and — the central repair — the workflow now distinguishes
**workspace evidence available** from **project-adopted evidence** from **project-stage complete**.
A fresh project no longer jumps to ~75%; it reports honest completion (1 → 2 → 3 as stages are
adopted). No science changed, no functionality removed.

## 2. Live Walkthrough Defects

1. "Save & Register Forecast Contract" → a dead Step-1-complete interstitial ("Continue to
   Baseball Data Evidence"). 2. "Use This Registered Dataset" → a dead Step-2-complete
   interstitial. 3. Step 3 "Review Identity & Leakage Evidence" **routed to Studio Home** (broken).
   4. Completion **jumped to ~75%** after only two steps. 5. Step 4 shown COMPLETE while Player &
   Team State says `MLB_DYNAMIC_PLAYER_STATE_V1` not registered / E1 / E2 not materialized
   (contradiction). 6. The UI conflated "workspace evidence exists" with "this project adopted it".

## 3. Root Cause

The Phase 6C resolver marked stages 3–11 **COMPLETE from global workspace evidence** the moment the
dataset was bound (identity bridge + PA candidates + calibration + graph all exist for the FD1
research), producing the ~75% jump. Step 4 used a coarse `paBaseline.candidates` proxy for
completion, but the destination page checks `study.components.dynamicState` (absent) — hence the
contradiction. And the Step 3 primary action had `kind: "inline"` with no route, so
`DeepLinkStage`'s `route || "/dashboard"` fallback sent it to Studio Home.

## 4. Completion Interstitial Removal

`ForecastContractPanel.save()` now `saveContract()` then calls `onSaved()` immediately;
`DatasetBindingPanel.doBind()` `saveBinding()` then `onBound()` immediately. `GuidedWorkflow`'s
`onCompleted(next, from)` sets `?step=next&done=from`, auto-advancing to the next step and showing a
brief "✓ Step N complete — advanced to Step N+1" banner. The interstitial screens are removed. The
stepper turns the finished step green, and **Previous** still returns to any completed stage for
review.

## 5. Step 3 Inline Evidence

Step 3 renders identity/coverage/leakage **inline** — no need to leave the workflow: **Player
identity** (exact mapping rate, unresolved, ambiguous from `identityBridge.joinAudit`), **Leakage
review** (exact-join-only / point-in-time from `identityBridge.noNamesOrFuzzyMatching` +
`featureAudit.joinEvidence`), **Prior coverage by season** (batter/pitcher Y−1 join rates from
`featureAudit.perSeasonRows`), **Known limitations** (dataset limitations), and technical authority
under a disclosure. Primary action: **Adopt Evidence & Continue**; secondary: **Inspect Full
Evidence in Data Warehouse**.

## 6. Broken Route Repair

The Studio-Home misroute is eliminated: Step 3's secondary routes to `/data-warehouse?from=
mlb-workflow&step=3`, and the generic module route now uses `focus.action.route` (Step 3 → Data
Warehouse is defined in the action map). A test asserts **no stage routes to `/dashboard`**.

## 7. Workspace vs Project Evidence

New explicit semantics in `workflowState.ts`: `EvidenceState` ∈ {`NO_EVIDENCE`,
`WORKSPACE_EVIDENCE_AVAILABLE`, `PROJECT_EVIDENCE_ADOPTED`, `PROJECT_STAGE_COMPLETE`, `BLOCKED`}.
Existing workspace evidence makes a stage show **"Existing workspace evidence available" / READY**
with an **Adopt Evidence & Continue** action — never COMPLETE. Per-project adoptions are stored in
localStorage (`adoptStage`), consistent with the Phase 6C contract/binding approach (no data copy,
no duplicate registration, no governance change).

## 8. Completion Semantics

A stage is COMPLETE only when the project has adopted it (Step 1 = contract saved, Step 2 = binding,
Steps 3–11 = adoption), enforced through a linear prerequisite chain; Step 12 export stays gated.
**Fresh project after Step 1 → 1 complete; after Step 2 → 2 complete; after adopting Step 3 → 3
complete.** No 75% jump. `completionSummary` now reports complete / ready / **available** / blocked.

## 9. Step 4 State Alignment

Root cause = coarse proxy + workspace-vs-project conflation. Step 4 is now **never COMPLETE from
workspace evidence**; it shows "Existing workspace evidence available: bounded Y−1 prior player
state (used by the PA baseline)" and honestly notes "dynamic player state & E1/E2 features are
optional further research (not yet registered)". Primary action: **Adopt Evidence & Continue** (or
**Open Player & Team State** to inspect/extend). The Player & Team State page's existing honest
"dynamic state not registered / E1 / E2 NOT_RUN" display is now **consistent** with the workflow,
which no longer claims completion.

## 10. Steps 5–11 Status Audit

Same class fixed for all: no stage is COMPLETE without project adoption. Each stage's
`evidenceAvailable` reflects the specific registered artifact (participation components, PA
candidates, whole-game MC, calibration.final2025, calibration, graph nodes); when present the stage
is READY/AVAILABLE with an adopt action, otherwise NOT_CONFIGURED with an "Open module to
configure" action — never a false COMPLETE.

## 11. Deep-Link Audit

Validated action routes (test-enforced): Step 3 → Data Warehouse, Step 4 → Player & Team State,
Step 5 → Participation & Usage, Step 6 → PA Modeling Cockpit, Step 7 → Simulation Studio, Step 8 →
Candidate Model Laboratory, Step 9/10 → Evaluation & Calibration, Step 11 → Model Graph, Step 12 →
Registry (gated). All deep-links carry `?from=mlb-workflow&step=N` and show the Return-to-MLB-
Workflow breadcrumb. No `/dashboard` misroutes.

## 12. Browser Acceptance

Owner-deferred (headless/authenticated environment; auth not weakened). The exact live journey is
covered by tests: Step 1 save → step 2; Step 2 bind → step 3; fresh project ≠ 75%; Step 4 not
falsely complete; Step 3 secondary → Data Warehouse (not home). `tsc` + production build clean.

## 13. Tests

`tests/sportsGuidedWorkflow.test.mjs` — **14 passing**: fresh state; post-contract; **bound +
workspace evidence but no adoption → only 2 complete (not ~9)**; available-vs-adopted transitions;
binding-without-evidence honesty; **Step 4 never complete from workspace evidence**; no-Studio-Home
routing; completion counts 1→2→3; strict-pregame preserved; auto-advance wiring; Step 3 inline
evidence; available/adopted/complete distinction; routing/redirect/return-bar; sidebar preserved.
Phase 6A/6B `paModelingCockpit.test.mjs` — **14 passing** (unchanged).

## 14. Preserved Functionality

All 20 sidebar modules, PA Modeling Cockpit, Data Warehouse, Player & Team State, Participation &
Usage, Simulation Studio, Model Laboratory, Model Graph, Registry, governance, security, and
registry evidence are intact. No Phase 4/5/6 science changed. The owner's project, target,
temporal policy (2021–2023 / 2024 / 2025 frozen / 2026), and **Strict Pregame** contract choice are
preserved (read verbatim from the stored contract).

## 15. Remaining Limitations

Contract, binding, and adoptions remain client-side localStorage references to the immutable
governed dataset (not yet backend-registered artifacts). The upstream-change → downstream-STALE
confirmation flow is defined in the model (`STALE` state, `resetAdoption`) but its explicit
invalidation UI is a documented next increment. Browser walkthrough owner-deferred.

## 16. Exact Next Step

Promote the forecast contract + binding + stage adoptions to governed backend registrations so
stage completion is server-authoritative, and wire the upstream-change → downstream-STALE
invalidation flow (re-review required when target/population/dataset/split changes).

### Confirmations
Phase 5 science changed = 0 · D3 changed = no · model retraining = 0 · Monte Carlo = 0 ·
provider/network calls = 0 · security weakened = no · auth weakened = no · dataset governance
weakened = no · PA Modeling Cockpit removed = 0 · Data Warehouse removed = 0 · Player & Team State
removed = 0 · Participation removed = 0 · Simulation Studio removed = 0 · Model Laboratory removed =
0 · AISP accessed = no · financial ATLAS accessed = no · ds-workflow-starter accessed = no ·
pushes = 0 · remote changes = 0.
