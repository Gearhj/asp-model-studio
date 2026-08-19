# Phase 6C.3 — Decision-Driven Workflow

## 1. Problem

Navigation was coherent after 6C.2, but several stages gave the scientist **nothing to do**.
Step 4 (Hitter & Pitcher State) showed an adopted Y−1 baseline plus a wall of `NOT_RUN` optional
research; Step 5 (Participation & Usage) surfaced empty component cards. Neither had a required
modeling decision, yet both were mandatory active stops — the owner correctly asked "why are these
workflow steps if there's nothing to select or decide?" The workflow was displaying architecture
instead of guiding decisions.

## 2. Governing Rule Applied

If a stage has no decision, no configuration, no analysis to review, and no required evidence to
approve, it is **not a required active stop**. Such stages are now **AUTO_SATISFIED** foundation
checks that complete automatically and are skipped by Continue — the scientist is moved to the PA
Modeling Cockpit fast.

## 3. Stage Classification (current project, evidence-derived)

| Step | Stage | Decision class |
|---|---|---|
| 1 | Forecast Contract | **CONFIGURE** |
| 2 | Baseball Data Evidence | **REVIEW_AND_DECIDE** |
| 3 | Identity, Coverage & Leakage | **REVIEW_AND_DECIDE** |
| 4 | Hitter & Pitcher State | **AUTO_SATISFIED** (optional customization available) |
| 5 | Lineup, Starter & Bullpen Usage | **AUTO_SATISFIED** (optional customization available) |
| 6 | Plate-Appearance Models | **ANALYZE** (embedded cockpit — the real work) |
| 7 | Base-Out Game Simulation | ANALYZE |
| 8 | Candidate Model Laboratory | ANALYZE |
| 9 | Temporal Validation | REVIEW_AND_DECIDE |
| 10 | Calibration & Reliability | REVIEW_AND_DECIDE |
| 11 | Model Graph & Decision | REVIEW_AND_DECIDE (DECIDE) |
| 12 | Export MLB Bundle | **TERMINAL** (gated) |

Blocked stages report `BLOCKED` with the exact prerequisite. The classification derives from the
project's actual evidence, not from architecture.

## 4. Step 4 Resolution — Player State

The bounded Y−1 batter/pitcher prior state the PA baseline already uses **is sufficient** for PA
modeling, so Step 4 is **AUTO_SATISFIED**. The stage now leads with a compact **"Player-state
foundation ready"** summary (per-season Y−1 coverage), then a compact **optional/advanced research**
block (Dynamic state / E1 / E2 / handedness → *Enabled* or *Not enabled*), with the full analytical
body collapsed under **"Explore advanced player-state research."** Large empty `NOT_RUN` panels no
longer dominate the primary path. Secondary: **Customize (Player & Team State) ↗**.

## 5. Step 5 Dependency Resolution — Participation

Traced dependency: lineup / starter-identity / starter-duration / bullpen components are
prerequisites for **full-game simulation (Step 7)**, **not** for training or evaluating the PA
classifier. Minimum participation evidence required for **PA modeling = none**, so Step 5 is
**AUTO_SATISFIED** with a **"Participation foundation sufficient for PA modeling"** summary, compact
component rows (existing research / simulation dependency), and the full participation body under
**"Customize participation & usage."** PA modeling is never blocked on these components. (No research
was re-run; the surface reflects registered evidence honestly.)

## 6. Foundation Checkpoint

Reaching Step 6 shows a compact **Model foundation complete** checkpoint: ✓ forecast contract ✓
registered MLB evidence ✓ identity/leakage checks ✓ player-state baseline ✓ PA-modeling
participation prerequisites — with **Customize player state / Customize participation** buttons and
**"Foundation ready — begin plate-appearance model development below."**

## 7. Adaptive Navigation

Completing a stage re-resolves and advances to the **first stage that still needs work**
(`advanceFrom` → `firstActionableStage`), and the footer **Continue** uses `nextActionable`, so
**adopting Step 3 jumps straight to Step 6**, skipping auto-satisfied Steps 4 & 5. Those stages
render in the navigator as **"Foundation ready"** (green), not as pages the user must visit.
Manual access remains: clicking Step 4 or 5 opens them for review/customization — they simply aren't
mandatory stops.

## 8. Step 6 Entry

Above the embedded cockpit, a concise project-context strip loads automatically (target, development
2021–2023, validation 2024, frozen 2025, champion D3 C4, evidence mode) with **"Begin model
development"** — the scientist does not reconfigure any of it. The full Phase 6A/6B 15-stage cockpit
(Objective → … → Registry, **Outliers before Missing Values** preserved) is exposed directly with
minimal program chrome.

## 9. Browser Acceptance

Owner-deferred (headless/authenticated environment; auth not weakened). The happy path — Step 1 →
Step 2 → Step 3 → (Steps 4 & 5 auto-satisfied and skipped) → **Step 6 PA Modeling Cockpit** — is
covered by tests. **Happy-path click count from project start to modeling: 3 decisions** (Save
contract → Use dataset → Adopt identity), then the cockpit. For the owner's existing project
(contract + binding + identity already present), Continue Work lands **directly on Step 6**.

## 10. Tests

`tests/sportsGuidedWorkflow.test.mjs` — **26 passing** (6 new/updated for decision-driven behavior):
Step 3 adoption auto-satisfies Steps 4 & 5 → Step 6 next; `nextActionable` skips auto-satisfied
stages; decision classes (CONFIGURE / REVIEW_AND_DECIDE / AUTO_SATISFIED / ANALYZE / TERMINAL); Step
6 blocked until bind + identity exist; completion counts 1 → 2 → foundation(5); auto-satisfied
compact rendering (no empty NOT_RUN panels); foundation checkpoint + Step 6 project context;
"Foundation ready" navigator labels. Phase 6A/6B `paModelingCockpit.test.mjs` — **14 passing**
(unchanged). tsc + production build clean; **zero backend changes**.

## 11. Remaining Limitations

- Contract / binding / adoptions remain client-side localStorage references (documented Phase 6C
  limitation; backend-governed registration is the next increment).
- Auto-satisfaction rules are scoped to the current PA project (Steps 4 & 5). Downstream stages
  (7–11) remain review/analyze stages after modeling and are not auto-satisfied.
- Browser walkthrough owner-deferred.

## 12. Exact Next Modeling Action

**Open the current project and go straight to Step 6 — Plate-Appearance Models.** Develop a
challenger in the embedded cockpit (e.g., a calendar-feature ablation or an XGBoost/LightGBM
challenger against D3), evaluate on 2024/2025, and run the bounded simulation impact — all inside
the MLB project shell. The remaining engineering item is promoting contract/binding/adoptions to
governed backend registrations.

### Confirmations
new modeling = 0 · model retraining = 0 · Monte Carlo = 0 · Phase 5 science changed = 0 · D3 changed
= no · provider/network calls = 0 · security weakened = no · auth weakened = no · existing modules
removed = 0 · pushes = 0 · remote changes = 0.
