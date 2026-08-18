# Phase 4 Milestone B — Operator Runbook

**Audience:** the operator (Codex) who will perform the actual analytical runs.
**Scope:** ASP Model Studio only. No provider calls, no sibling repositories.
**Status at writing:** engineering-ready; **no Milestone B results exist yet.**

This runbook is deliberately operational. It tells you exactly what to run, in what
order, and what "done" looks like. It does **not** make modeling decisions.

---

## 0. What Milestone B produces

One governed run fits and registers **three** components as one combined Phase 4
study that extends the frozen Phase 3 / D3 (`DYNAMIC_STATE_RESEARCH_CHALLENGER`)
lineage:

- Lineup projection — `MLB_LINEUP_PROJECTION_V1`
- Starter duration — `MLB_STARTER_DURATION_V1`
- Bullpen usage — `MLB_BULLPEN_USAGE_V1`

> **Catcher influence readiness (`MLB_CATCHER_INFLUENCE_READINESS_V1`) is now built
> as a separate DATA-AVAILABILITY AUDIT** (`server/sports_phase4/catcher_readiness.py`,
> contract `docs/contracts/MLB_CATCHER_INFLUENCE_READINESS_V1.md`). It is **not** a
> predictive model and is **not a prerequisite** for the lineup/starter/bullpen run
> below — run it independently whenever you want the catcher/battery evidence audit.
> Until it is executed, the Catcher section under Participation & Usage shows an
> honest `NOT_RUN`, and the predictive catcher graph nodes stay `NOT_CONFIGURED`.

The run is a **single supervised command** (not per-component) by design: the study
payload (`build_phase4_study_payload`) requires all three components together, and
the worker asserts the component set is exactly
`{LINEUP_PROJECTION, STARTER_DURATION, BULLPEN_USAGE}`. Do **not** try to split it
without a deliberate registry redesign.

---

## 1. Preconditions (must all be true before running)

- An **active Milestone A Phase 4 study** (D3) is registered in the isolated DB.
- The **dataset validation cache is fully warmed** (0 misses) at
  `.runtime/asp-model-studio/sports-modeling/dataset-validation/validation-cache.json`.
- The **identity bridge** is validated.
- `ASP_MODEL_EXCHANGE_ROOT` points at the approved exchange package (read-only).
- The isolated DB exists at
  `.runtime/asp-model-studio/persistence/asp_model_studio.db` (single-link regular file).
- Governed runtime roots (the CLI enforces these exactly):
  - dynamic input: `.runtime/asp-model-studio/sports-modeling`
  - participation output: `.runtime/asp-model-studio/sports-phase4`

The CLI **fails closed** if any path differs from the approved boundary, if the
validation cache has any miss, or if `--bootstrap-resamples != 500`.

Environment (recommended): set `ASP_MODEL_EXCHANGE_ROOT` and `ATLAS_SQLITE_PATH`
(pointing at the isolated DB above) in `.env.local` so you can omit the flags.

---

## 2. Runtime expectations

- Estimated duration: **≈15–35 minutes** (`estimatedSecondsLower/Upper` = 900/2100).
- Heartbeat: every **30 s** (component, stage, elapsed, rows, throughput, ETA, memory).
- Supervision watchdog: 8 h overall, **90 s silence kill**, 8 GiB RSS, per-component
  stage limits (lineup/starter 90 min, bullpen 120 min).
- Artifacts: ≤200 MB under the ignored `sports-phase4` runtime root. SQLite stores
  metadata + logical references only.
- Resume: feature/final checkpoints are content-addressed and atomic. There is **no
  mid-training skip-resume** — if you interrupt during fitting, a rerun re-fits from
  the start (the run is short and watchdog-bounded, so this is acceptable).

---

## 3. Run sequence

All commands from the repo root, using the project venv
(`.venv/Scripts/python.exe`). None of these call a provider or a sibling repo.

### Step 1 — Runtime estimate (safe; no training)
```
.venv/Scripts/python.exe scripts/run_mlb_participation_usage.py --estimate-only
```
Expect JSON with `estimatedSecondsLower/Upper` and `liveRunStarted: false`.

### Step 2 — Preflight (validates authorities; no fitting)
```
.venv/Scripts/python.exe scripts/run_mlb_participation_usage.py \
  --exchange-root "%ASP_MODEL_EXCHANGE_ROOT%" \
  --database ".runtime/asp-model-studio/persistence/asp_model_studio.db" \
  --preflight-only
```
Expect a `PREFLIGHT_COMPLETE` heartbeat and exit 0. A non-zero exit here means a
precondition in §1 is not met — fix that, do not proceed.

### Step 3 — Governed run (fits + registers all three components)
```
.venv/Scripts/python.exe scripts/run_mlb_participation_usage.py \
  --exchange-root "%ASP_MODEL_EXCHANGE_ROOT%" \
  --database ".runtime/asp-model-studio/persistence/asp_model_studio.db" \
  --bootstrap-resamples 500
```
- Watch the 30 s heartbeats. Do not kill on apparent silence < 90 s; the watchdog
  handles genuine stalls.
- **Success line:**
  `COMPLETED run_id=... decisions={...} artifacts=N study_id=... graph_id=...`
- **Failure line:** `FAILED <ErrorType>: <message>` (exit 1) or
  `FAILED SUPERVISION <reason>` (watchdog). These are honest terminal states — read
  the reason; do not retry blindly.

Per-component terminal decisions will each be one of:
`{LINEUP|STARTER_DURATION|BULLPEN_USAGE}_{RESEARCH_COMPONENT|RESEARCH_BASELINE|REJECTED|BLOCKED}`.
A `*_BLOCKED` decision is a legitimate, registered outcome (e.g. insufficient
candidate coverage) — not a crash. Do not fabricate a non-blocked result.

### Step 4 — Registry finalization (verify, don't re-run)
The successful run already registers the combined study. Confirm it is the active
study (e.g. the `study_id`/`graph_id` printed match what the active-study projection
returns). Do not insert or edit registry rows by hand.

### Step 5 — Frontend verification
```
node tests/sportsProductConversion.test.mjs        # sports contract (expect 15/15)
node node_modules/typescript/bin/tsc --noEmit -p tsconfig.json   # expect exit 0
npm run build                                       # production build once
```
Then, if a local authenticated session is available, smoke-check these surfaces for
honest states (no fabricated numbers, no console errors, no horizontal overflow):
Project Overview · Player & Team State · Participation & Usage · Model Laboratory ·
Evaluation & Calibration · Model Graph. If no authenticated session is available,
rely on the frontend contract test and skip manual protected-page QA (do not weaken
authentication).

### Step 6 — Focused backend re-check
```
.venv/Scripts/python.exe -m pytest \
  tests/sports_phase4_participation_contract_test.py \
  tests/sports_phase4_participation_features_test.py \
  tests/sports_phase4_participation_cli_test.py \
  tests/sports_phase4_participation_training_runner_test.py -q
```
(22 passed at readiness time.) Do not loop full-platform suites.

### Step 7 — Commit 2
Only after coherent component decisions are registered and the frontend renders them
honestly. `git diff --check`; stage the Milestone B work plus the readiness docs;
commit. (This readiness pass left everything **unstaged** for you.)

---

## 4. If something is off

Errors are already differentiated — surface the exact terminal reason, do not
collapse to a generic failure:

- Precondition/authority problem → non-zero exit at preflight (Step 2). Fix §1.
- `*_BLOCKED` component decision → registered, honest; investigate coverage, do not
  fake a result.
- Watchdog `FAILED SUPERVISION silence/overall/rss` → the run stalled or exceeded a
  bound; inspect the last heartbeat's stage, do not immediately re-run.
- Frontend shows `NOT_RUN`/`NOT_CONFIGURED` after a successful run → check the study
  registered as **active** and that `/api/sports/datasets/active` returns `phase4`.

---

## 4b. Catcher influence readiness audit (separate, not blocking)

`MLB_CATCHER_INFLUENCE_READINESS_V1` is a **data-availability audit**, independent
of §3. What is **built and tested now**:

- `server/sports_phase4/catcher_readiness.py` — pure, schema-agnostic algorithms
  (starting-catcher reconstruction, catcher-at-PA assignment with substitution/
  ambiguity handling, strict prior-only battery & catcher-batter sample-size
  distributions, fallback-level mapping, readiness decision, free-feature/premium-gap
  inventories, registry-ready payload builder).
- `tests/sports_phase4_catcher_readiness_test.py` — 23 hermetic tests (all pass).
- Frontend Catcher section (honest `NOT_RUN`) and predictive-catcher graph nodes
  (`NOT_CONFIGURED`).

**The adapter is wired and the audit has been EXECUTED** against the real FD1 dataset
(2026-08-18). Command (no provider calls, no model fitting):

```
# estimate / preflight / status / run (idempotent) / force-recompute
.venv/Scripts/python.exe scripts/run_mlb_catcher_readiness.py --estimate-only
.venv/Scripts/python.exe scripts/run_mlb_catcher_readiness.py --preflight-only
.venv/Scripts/python.exe scripts/run_mlb_catcher_readiness.py --status
.venv/Scripts/python.exe scripts/run_mlb_catcher_readiness.py            # reuses completed artifact
.venv/Scripts/python.exe scripts/run_mlb_catcher_readiness.py --force    # recompute
```
Requires `ASP_MODEL_EXCHANGE_ROOT` and the isolated DB (`ATLAS_SQLITE_PATH` →
`.runtime/asp-model-studio/persistence/asp_model_studio.db`).

**Real result:** `CATCHER_INFLUENCE_PARTIALLY_READY` in **26 s** — starting-catcher
reconstruction ≈100 %, PA-level catcher assignment ≈87 % (the ~13 % ambiguity is
structural: multi-catcher team-games with no substitution-timing family), dense
pitcher-catcher battery history (2024 median 102 prior PAs; 50.6 % ≥100), sparse
catcher-batter history (2024 median 9). Content-addressed evidence is written to
`.runtime/asp-model-studio/sports-phase4/catcher-readiness/` and surfaced to the
frontend via `/api/sports/datasets/active → phase4.catcherReadiness`.

**Idempotency:** an identical authority + code revision **reuses** the completed
artifact (`REUSED_COMPLETED_AUDIT`); use `--force` to recompute.

**Relationship to Codex's Milestone B training:** the catcher readiness audit is a
**separate, non-blocking** data audit — it does **not** gate the lineup/starter/
bullpen analytical run (§3). It fits no model; the future
`MLB_CATCHER_AND_BATTERY_EFFECT_V1` study (design only, `M0→M5`) is where any catcher
effect would be estimated.

---

## 4c. E1 pitch-sequence process feature materialization (separate, not blocking)

`MLB_PITCH_SEQUENCE_PROCESS_FEATURES_V1` is a leakage-safe **feature materialization**
(no model), preparation for the next PA-modeling wave. It does **not** gate the
Milestone B participation run.

```
.venv/Scripts/python.exe scripts/run_mlb_pitch_sequence_features.py --estimate-only
.venv/Scripts/python.exe scripts/run_mlb_pitch_sequence_features.py --preflight-only
.venv/Scripts/python.exe scripts/run_mlb_pitch_sequence_features.py --status
.venv/Scripts/python.exe scripts/run_mlb_pitch_sequence_features.py            # reuses completed
.venv/Scripts/python.exe scripts/run_mlb_pitch_sequence_features.py --force    # recompute
```
**Executed result:** `PITCH_SEQUENCE_FEATURES_READY` in **26 s** — 100 % parser
success, 50 leakage-safe batter/pitcher process features (cumulative + trailing-30d)
over **568,935** target PAs (2023–2025); content-addressed Parquet under
`.runtime/asp-model-studio/sports-phase4/pitch-sequence-features/` (not committed);
surfaced via `phase4.pitchSequenceFeatures`. **Idempotent** (`--force` recomputes).
E1 is preparation for a future E2 interaction materialization and a separate governed
model experiment — **no model is trained here and no predictive improvement is
claimed**.

**E2 (batter × pitcher process interactions) is now available** — a bounded
leakage-safe transform of E1 (`scripts/run_mlb_process_interactions.py`,
`--estimate-only`/`--preflight-only`/`--status`/`--force`). Executed:
`PROCESS_INTERACTIONS_READY` in 4 s, 25 features over the same 568,935 E1 rows
(row-count preserved), SHA-verified parent E1, content-addressed Parquet in ignored
runtime storage, surfaced via `phase4.processInteractions`. Idempotent (`--force`
recomputes). E2 is **not** a prerequisite for the Milestone B participation run; it is
input for the next PA-model experiment (where any predictive value would be tested).

---

## 5. Guardrails (do not violate)

No provider/network calls · no sibling repos (`ai-sports-predictor`,
`ds-workflow-starter`, financial ATLAS) · do not alter Milestone A / D3 results ·
do not change modeling methodology · do not build the catcher model, archetypes, or
the simulator in this run · keep `--bootstrap-resamples 500`.
