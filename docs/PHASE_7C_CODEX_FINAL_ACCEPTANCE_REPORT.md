# ASP Model Studio Phase 7C — Final Independent Codex Acceptance Report

Audit date: 2026-08-21  
Repository: `C:\Users\james\asp-model-studio`  
Branch: `phase7c-canonical-authority-cutover`  
Committed HEAD: `93f1634e27ed32f713edd6cf43035d56baf546fa`  
Main reference: `924db29511f93909f9d785855bfa056775443690`

## Primary verdict

**PHASE_7C_HARDENING_REQUIRED_BEFORE_PHASE_7B**

Phase 7C contains a real and valuable canonical-server cutover: Gen-2 and Gen-3 research data are physically separated from 2025, Gen-3 is republished under the V2 bundle, the project-scoped execution routes enforce ACL checks, nine legacy execution endpoints return 410, Evaluation and Calibration can resolve an active run, and the saved A2 2024 predictions independently reproduce the reported metrics exactly.

It is not yet safe to accept Phase 7C for Phase 7B. Four acceptance-boundary failures remain:

1. The advertised immutable registry is neither the sole resolver nor current. Production resolution trusts two mutable `registration.json` sidecars, while the external registry has nine entries, including selectable legacy combined/V1 objects.
2. Physical 2025 isolation is only true inside the new Model Lab service. Ordinary cockpit payloads still expose 2025 evidence, and tracked local research utilities still open combined/full objects, score 2025, and in at least one case use 2025 in a feature-value decision.
3. The canonical authority cannot execute Phase 7B feature work: it hard-codes the same global 22-feature list for both generations, while Steps 03–08 save controls that never enter a run authority.
4. Run evidence and activation are mutable/self-attesting in critical places. Coordinated manifest-and-child tampering is accepted downstream, fabricated non-complete runs can be activated, and HGB runs do not persist a fitted estimator.

These are bounded, repairable hardening items rather than grounds to discard the Phase 7C work. They do, however, directly threaten exact dataset identity, physical sealing, canonical experiment identity, and reproducibility—the explicit Phase 7B gate.

## Final readiness decisions

| Readiness boundary | Decision | Reason |
|---|---|---|
| Phase 7B local acquisition and controlled 2024 experiments | **NO-GO** | Registry/object authority is not canonical, tracked research tools can consume 2025, and advanced features cannot enter the governed run contract. |
| Scientist testing | **NO-GO** | Multiple browser/data authorities, stale result state, decorative experiment controls, project-switch races, and visible 2025 evidence remain. |
| Private beta | **NO-GO** | Add strict schemas, bounded scheduling, complete state transitions, full lifecycle tests, and rendered UI verification after the Phase 7B blockers. |
| Paid pilot | **NO-GO** | Evidence immutability, reproducible estimator artifacts, product capability completeness, and operational controls are insufficient. |
| Production | **NO-GO** | The authority, seal, evidence, security, and operational gaps are release-blocking. |

## 1. Audit scope, safety, and repository state

This was an independent read-only/adversarial audit except for creation of this report. No application source or test was changed. No commit, push, dependency download, promotion, registry write, D3/C4 mutation, or model fit was performed.

- Worktree before this report: four pre-existing untracked reports only; `.pytest_cache` was unreadable and untouched.
- Preserved untracked files:
  - `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md` — SHA-256 `2072fcb956dd35f12ec9fd3fdff99dcd892aa66d83f8dc397b19c4fc886dc3a9`
  - `docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md` — `4d01057823bdd5142fc3c9be4aeca6eaf865d37aef76ee4813210c27dbb11e86`
  - `docs/PHASE_7A5_CODEX_FINAL_ACCEPTANCE_REPORT.md` — `180f3f2792a26156d981e453e5b591c7f60fa06de048b5a152e5c922a929d069`
  - `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md` — `00adbfe2a25581ba855ec9487560f63208cc2b9449edd70ad210b11a1bf9f80d`
- Phase 7C commits after `7eb8de5`: `6b0a312`, `51f10a7`, `b89e30e`, `e75eec9`, `93f1634`.
- Tracked delta: 14 files, 1,132 insertions and 469 deletions.
- Runtime/raw files committed in the Phase 7C delta: **0**.
- `git diff --check`: **pass**.
- Files created by this audit: `docs/PHASE_7C_CODEX_FINAL_ACCEPTANCE_REPORT.md` only.
- Real models executed by this audit: **0**.
- Real sealed-2025 object bytes or target rows touched by this audit: **no**.
- Research objects read: the current Gen-2 and Gen-3 research Parquets only, for receipt verification. Persisted A2 artifacts contained 2024 validation data only.

The Phase 7C plan and handoff report were traced to source and receipts; their conclusions were not treated as proof. Several system-wide claims in `docs/PHASE_7C_CANONICAL_AUTHORITY_CUTOVER_REPORT.md:14-30,61-71,132-139,163-165,179-193,202-220` are disproved below.

## 2. Acceptance snapshot

### Gen-2

- Research object: `mlb-pa-gen2-research:sha256:50ce1def3315f5e4d9c5bd1ba9cb72490f33d20303720eb814f4eff1742eaf58`
- Research seasons/rows: 2023–2024; 366,553 total (184,104 / 182,449)
- Research physical SHA: `e8e836e387973fd48d88eb7c077a5ff7f2c38392d1be361ae3ce0cd467094402`
- Research schema SHA: `c4890268b2047cc90d08adc7909b9acefd1b235e8520a4dd34fdc4d4fb3e11e6`
- Sealed object metadata: `a04852d56cdeb42298d1d72c531c369c4c9ef142658b18c2ecb51b9a3fc7f5a4`; 2025; 182,926 rows; restricted/nonselectable
- Contract bundle: `ce5cd20c284351c768c4572b9ef1fc249de2f404c742c41359cc7c218e6a9bf5`; generation-correct Gen-2 identities
- Current research bytes verified: **yes**
- Verifier complete/fail-closed under adversarial metadata/path/cache cases: **no**
- Canonical Model Lab sealed opens observed: **0**
- System-wide ordinary combined/2025 access eliminated: **no**

### Gen-3 V2

- Research object: `mlb-pa-gen3-research:sha256:b4bc7a0ebb593e919b6eecfa1b10815314e4a917877571c03d05e531bf36bdea`
- Research seasons/rows: 2021–2024; 730,284 total (181,752 / 181,979 / 184,104 / 182,449)
- Research physical SHA: `c52bb432b6f1fcbc53203437ea8e7969a885932a510ee4f5e9713366f81cf4e7`
- Research schema SHA: `c4890268b2047cc90d08adc7909b9acefd1b235e8520a4dd34fdc4d4fb3e11e6`
- Sealed object metadata: `4c33b9e57a6b8ffc00cd3ac803c31b31b75e0cf38cde6fbcd17027f669a06d20`; 2025; 182,926 rows; restricted/nonselectable
- V2 bundle: `86a60f6caefc74b14f8068d684541dd8d03ed66004cf95632374e10f1fd65ffa`
- Knowledge time: `MLB_GEN3_KNOWLEDGE_TIME_CONTRACT_V2:sha256:6ab2d6e5efd162a82d2a78275e7062af67685fbe62e8cadbf76d9a7a4bd91d8d`, honestly labelled `CONDITIONAL_PRE_TERMINAL_PA_STATE`
- V1 lineage: distinct old research `05c91a…`, sealed `878a31…`, bundle `f68770…`, KT V1 `0a6909…`
- Quarantine: 139 structural convention anomalies, ledger `fec36f1b…`
- Current research bytes verified: **yes**
- Canonical Model Lab sealed opens observed: **0**
- System-wide ordinary combined/2025 access eliminated: **no**

The sealed-object values above were verified from registration/manifests only. Sealed Parquet bytes were deliberately not opened.

## 3. Prioritized findings register

### P7C-01 — P0 / blocks Phase 7B — the registry is not the sole resolver

`catalog()` builds four entries from fixed `registration.json` files and `_resolve_version()` loops that synthesized catalog (`server/sports_cockpit/gen3_authority.py:125-220`). `ASP_REGISTRY` is written only by the admin helper and is never read by a consumer (`:202-211`). The descriptive engine separately trusts the Gen-2 sidecar and checks only file existence before reading (`server/sports_cockpit/engine.py:167-215`).

The actual external registry has nine entries and no trustworthy canonical-four invariant. It still contains selectable legacy combined Gen-2 `74b9c24…`, selectable Gen-3 V1 `05c91a…`, an intermediate Gen-3 `13bf9d…`, and the current entries. The sidecars themselves are fixed, overwriteable `write_text` targets (`scripts/phase7a_build_gen3.py:110-135`; `scripts/phase7c_publish_gen2.py:100-148`). The Gen-2 publisher does not refresh the external registry.

Impact: exact version/contract identity depends on mutable files outside the claimed sole registry; the descriptive and modeling planes have different resolvers. This directly blocks acquisition provenance and controlled experiments.

Minimal repair: make one immutable/content-addressed registry the only catalog and object resolver; atomically register both generations in one transaction; mark all old combined/V1/intermediate entries archived and nonselectable; treat sidecars as publisher inputs, not executable authority.

### P7C-02 — P0 / blocks Phase 7B — the physical 2025 seal is path-local, not system-wide

The canonical server path correctly opens the two research objects and no sealed object. The broader system does not satisfy the claimed zero-access ledger:

- `/cockpit/objective` returns `frozen2025` from registered/fallback champion evidence (`server/sports_cockpit/engine.py:149-153,259-325`). The cockpit fetches Objective on every mount (`src/sports/cockpit/PaModelingCockpit.tsx:41-45`), Step 01 renders “2025 frozen final” (`cockpitSteps1.tsx:107-110`), and Model Lab fetches the same payload (`cockpitSteps2.tsx:45-56`).
- Evaluation appends Phase-4 severe-miss evidence (`cockpitSteps2.tsx:468-478,525-526`) that renders 2025 tail-loss share, confusion pairs, over-index, and official D3 log loss (`src/sports/Phase4Surfaces.tsx:547-590`).
- Tracked executable utilities still open the archived combined Gen-2 or full Gen-3 object and process 2025: `run_mlb_e1_e2_incremental_signal_study.py`, `run_mlb_simulation_input_layer.py`, `run_mlb_projected_participation_ablation.py`, `run_mlb_starter_identity.py`, `run_mlb_whole_game_monte_carlo.py`, `run_mlb_severe_miss_forensics.py`, `run_mlb_dynamic_player_state.py`, `run_mlb_pa_baseline.py`, `phase7_ablation.py`, `phase7_build_gen3.py`, `run_mlb_pitch_sequence_features.py`, `run_mlb_process_interactions.py`, `run_mlb_base_out_transition.py`, and `run_mlb_game_replay.py`.
- Most decisively, `server/sports_phase4/incremental_signal_study.py:477-520` requires both 2024 and 2025 relative-gain/bootstrap results for the E1/E2 predictive-value and next-step decision. This is model-selection leakage, not archival display.
- Several utilities still use `glob(...)[0]`, reintroducing first-match resolution.

No such tool was executed by this audit. Their tracked, ordinary executability is enough to disprove “system-wide sealed” and to make Phase 7B advanced-feature research unsafe by default.

Minimal repair: enforce a single research-only object capability in all current scripts/services; require an explicit audited administrative sealed-data capability; remove 2025 from all feature-value/readiness decisions and ordinary UI DTOs; quarantine or hard-retire combined/full objects and old utilities.

### P7C-03 — P0 / blocks Phase 7B — scientist controls and future features are outside run authority

Steps 03–08 receive no `projectId`, call binding-free fixed-Gen2 endpoints, and save feature/outlier/missing/segmentation/temporal choices (`PaModelingCockpit.tsx:26-31`; `cockpitSteps1.tsx:520-619,851-1048,1393-1423,1626-1659,1867-1943`; `router.py:52-141,313-374`). Canonical issue/execute accepts project, binding, family, and a narrowly validated HGB map; it fixes preprocessing and `FEATURE_NAMES` (`gen3_authority.py:474-553`).

The same global 22-feature list is used for Gen-2 and Gen-3 catalog counts, verification, authority fingerprints, and object loading (`gen3_authority.py:151,180,296-301,474-483,520-553`). A Phase 7B generation-specific advanced/pregame feature contract would be ignored; changing the global list would break Gen-2.

Local `dataset.selected` / `target.confirmed` notes still gate Objective and present themselves as authority (`cockpitSteps1.tsx:42-80,212-354`), while their target analysis remains fixed Gen-2. A scientist can therefore see Gen-3 as bound while profiling/configuring Gen-2 and then run the fixed base-22 authority.

Minimal repair: derive ordered feature columns and preprocessing from the bound registered contract; bind the complete effective experiment configuration into the authority; make all functional pages project/binding aware; remove or unambiguously demote the legacy selectors and decorative controls.

### P7C-04 — P1 / blocks Phase 7B — object verification is incomplete and can read outside the authority root

The shared physical/logical/schema digest implementation is a genuine improvement (`server/sports_modeling/gen3_publish.py:35-57,86-125`). Current research objects pass it. Adversarial behavior remains fail-open:

- A malicious sidecar SHA produced a path outside `GEN3_ROOT`; `_verify_object` opened the outside synthetic Parquet before its logical check rejected it. `_object_path` and `_verify_object` do not resolve/contain the registered path (`gen3_authority.py:133-186,236-269`).
- Missing critical embedded metadata and forged embedded schema, temporal, feature-schema, and target IDs were accepted 5/5. The verifier conditionally checks only logical SHA, bundle, and object kind (`:272-286`) and does not authenticate the publication manifest.
- Publisher/logic does not bind generation and object kind into the logical digest itself; those rely on incompletely checked external/embedded fields.
- The verification cache is keyed by resolved path, size, mtime, and expected logical SHA. A same-size/same-mtime content substitution was accepted from the warm cache.

Minimal repair: resolve and contain every object under a fixed registered root before any open; reject symlink/junction/reparse ancestors; require every embedded identity and publication manifest; bind generation/object kind into the canonical digest; remove the cache or key it by recomputed physical SHA.

### P7C-05 — P1 / blocks Phase 7B — evidence and activation are not immutable or fully authenticated

The saved A2 files are complete enough to recompute 2024 metrics and all current hashes match. The general mechanism is weaker:

- Evidence directories use `mkdir(exist_ok=True)` and unconditional writes; the run-collision check occurs only after evidence writes (`gen3_authority.py:556-595,747-750`).
- Downstream readers verify children against hashes inside the mutable manifest but never hash the manifest and compare it to `run.evidenceBundleSha256` (`:598-632,839-866`). A coordinated diagnostics+manifest substitution and a predictions+target+manifest substitution were both accepted; the latter returned a forged log loss of `2.079441541679836` while the run-bound manifest SHA remained different.
- Manifest-controlled filenames are not resolved/contained beneath the evidence directory; a hermetic manifest traversal read a synthetic file outside the bundle root.
- Activation checks only that `run.bindingId` equals the current pointer (`:805-822`). Hermetic probes activated fabricated `FAILED_STALE_AUTHORITY`, `RUNNING`, and `COMPLETE` records without authority or evidence files (3/3 accepted).
- `get_active_candidate` compares only run-authority ID and dataset-content SHA (`:825-836`); it does not verify status, binding revision, evidence manifest, result fingerprint, current authority, or current code/environment.
- HGB `model.json` stores hyperparameters/classes/iteration count, not fitted trees (`:685-697`). It is not a persisted estimator and cannot score without refitting. The currently active HGB run `ce8ca6…` has this limitation.

Minimal repair: publish run JSON and all evidence as one atomic append-only content-addressed bundle; anchor and verify the manifest from the run on every read; verify all children, run authority, object receipt, binding revision, status, and fingerprints before activation/serving; require `COMPLETE`; persist a loadable fitted estimator for every advertised family.

### P7C-06 — P1 / blocks Phase 7B — run authority remains partly self-attesting

`_validate_authority` compares contract SHAs and a recomputed effective-config hash, but hermetic forgery accepted mismatched binding revision, dataset version versus binding, generation versus binding/object, bundle SHA, six contract IDs, and fold seasons after the self-attested hash was recomputed (`gen3_authority.py:507-543`). It does not compare the full authority to the current binding/registry record.

`_code_identity()` hashes tracked diff bytes plus untracked path names, not untracked contents or ignored executable/config/lockfile contents, and returns `UNKNOWN` on Git failure (`:102-111`). Authority issue and validation both accepted `UNKNOWN/UNKNOWN`. Tracked changes are correctly checked before fit and again after fit, but an environment change after the post-fit check was published as `COMPLETE` with authority environment A and evidence environment B (`:706-744`). Documentation/untracked report names can invalidate work while material untracked content edits can escape detection.

Minimal repair: reconstruct authority solely from the active binding plus immutable registry and compare every field; fail closed on unknown code/environment; hash the actual relevant source/config/lockfile closure; snapshot one environment identity and echo it; make the final drift check immediately precede an atomic publication.

### P7C-07 — P1 / blocks scientist testing — binding/project browser transitions can lie

Backend project state uses opaque project keys and current binding supersession, but UI coordination is incomplete:

- Same-version selection remains clickable, sends no `expectedRevision`, always creates a new revision, and silently invalidates the candidate (`Gen3CatalogSection.tsx:175-207,229-238`; `gen3_authority.py:313-351`). A concurrent CAS probe produced two same-revision successes and two ACTIVE records.
- `Gen3PopulationPanel` reloads only on `projectId`, not binding ID, so a new binding can display beside old population (`Gen3CatalogSection.tsx:112-121,229-238`).
- Active-candidate and Autopilot requests can resolve after project change; persistence leaves a debounced save alive across project switches (`cockpitSteps2.tsx:343-356,438-445`; `cockpitPersistence.ts:82-129`).
- Persisted `labSuite`, `lastResult`, and `lastSim` remain. `lastResult` still drives the header and Model Lab completion, and old candidates can render `frozen` metrics (`PaModelingCockpit.tsx:44,79,99`; `cockpitSteps2.tsx:64-80,288-315`).

Minimal repair: shared server binding context keyed by project+revision; idempotent same-version bind with mandatory CAS; cancel stale requests/timers; version and migrate browser snapshots; derive stage completion and active experiment only from server runs/candidate.

### P7C-08 — P2 / nonblocking for trusted single-developer acquisition, blocks multi-user testing

Resource controls are partial. HGB finite/range checks and the eight-candidate suite cap work (`gen3_authority.py:440-461,755-784`). Requests remain raw dictionaries: unknown fields/hyperparameters are ignored, fractional integers are truncated, malformed mappings can raise an uncaught `AttributeError`, seed handling occurs outside the guarded validator, and logistic silently ignores submitted hyperparameters. Two suites can enter execution concurrently; there is no per-user/project scheduler or durable QUEUED/RUNNING attempt.

This does not by itself block one trusted developer from acquiring data. It blocks scientist/private-beta concurrency and operational safety. Add strict typed schemas (`extra=forbid`), exact integer/seed bounds, uniform error mapping, idempotency, a bounded scheduler, and durable attempt lifecycle.

### P7C-09 — P1 / acceptance evidence is insufficient

The new sealed-access test directly calls service methods, uses real developer runtime registrations/objects, and instruments only `G3A._record_open`; it does not exercise authenticated HTTP, the external registry, all analytical/UI routes, direct PyArrow/script opens, or archived combined objects (`tests/sports_cockpit_gen3_sealed_access_test.py:1-116`). Several other authority tests call `register_gen3()` against shared runtime and execute real research models. Existing frontend tests are source-string assertions, not rendered behavior.

Safe Node source tests produced 44/50 passes: `gen3FrontendConsolidation` 7/7, `gen3ScientistFlow` 5/6, `cockpit6g2` 12/12, `cockpitNavAndPopulation` 9/9, and `paModelingCockpit` 11/16. Six failures are stale assertions, mostly for deliberately retired Simulation/Eligibility/Ablation paths. Batch `node --test` could not spawn in the sandbox; files were run one at a time. One selected pytest attempt executed no tests because the host pytest temp root was inaccessible; a separate safely isolated ACL/path subset passed 3/3 (two deselected).

Minimal repair: isolated temporary registries and objects; authenticated two-user/two-project HTTP lifecycle; full production resolver/open instrumentation; object/evidence/authority tamper matrices; in-flight drift/concurrency tests; independent metrics; rendered project/binding transition tests. Tests must never mutate shared `.runtime`.

## 4. Gate-by-gate result

| Gate | Result | Independent conclusion |
|---|---|---|
| Repository/report audit | PASS | Exact branch/HEAD resolved; clean tracked tree; report claims traced. |
| Gen-2 physical split | PARTIAL | Current objects/receipts are correct; combined object remains executable through registry/scripts. |
| Gen-3 V2 split | PASS for current canonical objects | V2 bundle and KT V2 match; V1 remains distinct lineage. System-wide consumers are not sealed. |
| Registry sole resolver | FAIL | Mutable sidecars drive execution; external registry is stale and unused. |
| Digest equivalence/tamper | FAIL | Current hashes reproduce, but path, embedded identity, manifest, and cache tamper cases fail closedness. |
| One data/target authority | FAIL | Server binding coexists with local notes and fixed Gen-2 analytical routes. |
| Binding/project transitions | FAIL | Backend supersession is present; same-version/CAS and frontend refresh/race behavior are unsafe. |
| Project ACL/path | PARTIAL | Project ACL and opaque project storage pass; dataset object-path containment fails. |
| Production-resolver 2025 seal | FAIL | Canonical service path passes; system-wide UI, scripts, and stale registry do not. |
| Legacy endpoint retirement | PASS for HTTP execution | Nine routes return 410; live UI execution uses canonical run service. Dead source and CLI paths remain. |
| Strict requests/resources | PARTIAL | Family/range/candidate bounds exist; schemas, seed, malformed input, concurrency, and scheduler remain. |
| Run evidence bundle | PARTIAL | A2 bundle is rich and currently hash-consistent; publication/consumption/activation are mutable and HGB estimator is absent. |
| Code/environment drift | PARTIAL | Pre-fit and post-fit tracked drift fail closed; UNKNOWN, untracked/ignored content, and final environment race fail. |
| Active candidate/downstream | PARTIAL/FAIL | Evaluation/Calibration use active evidence, but activation is forgeable and Evaluation adds 2025 Phase-4 evidence. |
| A2 evidence | PASS, qualified | Exact persisted 2024 metric reproduction; run is science-code-equivalent to HEAD, not literal current-HEAD identity. |
| Population truthfulness | PARTIAL | Binding panel uses exact registered counts/KT; other pages and hardcoded copy can show a different authority. |
| Autopilot/tuning/aids | PARTIAL | Autopilot uses authorized runs; tuning/simulation/ablation are honest blocks; stale/dead suite evidence remains. |
| Test quality | FAIL acceptance threshold | Important behavior is untested or tested against shared runtime; current source suite is red. |

## 5. Authority, caller, and downstream inventory

### Canonical execution

- One live frontend execution service: **yes** — manual Model Lab issues `/cockpit/gen3/run-authority` then `/cockpit/gen3/execute`; Autopilot uses `/cockpit/gen3/run-suite`.
- Project authentication: **yes** — the full cockpit router is mounted with `require_user` (`server/main.py:463,500`).
- Project ACL: **yes on all Gen3 project routes** — each project route calls `authorize_modeling_scope` (`router.py:194-282`; `core/modeling_scope.py:56-106`).
- Two-user/two-project hermetic HTTP matrix: 24/24 owner requests allowed; 24/24 cross-project requests denied.
- Scientist-reachable binding-free HTTP execution callers: **0 live callers**.
- Dead frontend literal: `/cockpit/experiment/run` remains behind a constant early return and disabled button (`cockpitSteps2.tsx:63-74,147-148`). Delete it.

### Retired endpoints

Behavioral no-data diagnostic confirmed 410 for nine endpoints with zero catalog object opens:

`champion`, `experiment/run`, `experiments`, `experiments/{id}`, `autopilot`, `simulate`, `eligibility`, `provider/verify`, and `feature/ablation` (`router.py:160-178,289-310,377-381`).

### Functional pages

| Surface | Authority result |
|---|---|
| Data Warehouse | Server catalog cards, but sourced from mutable sidecars; Gen2 sealed styling is also weaker than Gen3. |
| Data & Population | Canonical selector/panel exists and exact counts are truthful; legacy dataset/target surfaces and stale sibling refresh remain. |
| Objective | FAIL: browser notes gate “authority”; endpoint returns 2025 champion metrics. |
| Target | FAIL: local confirmation plus fixed Gen-2 target analysis. |
| Profile / Outliers / Missing / Feature Engineering / Segmentation / Temporal Split | Fixed Gen-2 research tools; not bound to project dataset or executable run config. |
| Model Laboratory | Canonical manual execution works; dead legacy suite and stale browser leaderboard remain. |
| Autopilot | Uses canonical authorized suite and immutable run IDs; no scheduler and project-request race remain. |
| Tuning | Honestly unavailable. |
| Evaluation | Active-run 2024 evidence works; appended global 2025 severe-miss evidence is a conflicting authority. |
| Calibration | Same active run; honestly raw and calibrator not configured. |
| Simulation | Honestly `NOT CONFIGURED`; legacy route returns 410. |
| Feature Ablation | Honestly `NOT CONFIGURED`; legacy route returns 410. |
| Champion/Challenger | Active challenger and disabled promotion; champion 2025 is still exposed elsewhere. |
| Registry/Evidence | Active-run based; manifest is not anchored/fully verified by the consumer. |

## 6. Security and transition results

- Owner/cross-project service/HTTP behavior: **pass** for tested Gen3 routes.
- Same user, two project state roots: opaque, distinct SHA-derived keys.
- Windows-shaped project IDs tested: `..\..`, `..\`, encoded/mixed separators, drive absolute, UNC, slash absolute, reserved/trailing forms. Eight variants produced zero project-state escapes.
- Dataset object path: **fail** — a malicious sidecar caused one outside-root synthetic Parquet open before rejection.
- Binding supersession: stale binding cannot issue/execute, and candidate pointer invalidation exists.
- Same-version/CAS: **fail** — two concurrent binds can succeed at the same revision and leave two ACTIVE records.
- Object verification cache: **fail** under same-size/same-mtime substitution.
- Authority forgery: **fail** for material ID/binding/generation/fold mismatches when the self-attested config hash is recomputed.
- Pre-fit tracked drift: **pass**.
- Post-fit tracked drift: **pass** (one failed record, zero evidence directories in the hermetic probe).
- Git identity unavailable: **fail** (`UNKNOWN/UNKNOWN` can be issued and validated).
- Environment change after final check: **fail** (mismatched environment identities published COMPLETE).
- Resource bounds: **partial** — 12/12 invalid HGB numeric cases and a nine-candidate suite were rejected, but fractional integers truncate, logistic unknown/nonfinite values are ignored, malformed mappings escape as `AttributeError`, huge seeds are accepted, and two concurrent suites both entered execution (peak concurrency two).

## 7. A2 independent evidence audit

Run under review: `781b6bc15d8f4101a8f3e8a07558cae3`  
Run authority: `852eb093e1084af3868329404ff15fc1`  
Binding: `2b358cf8eee9403a91dac4d51b9dcf5b`, revision 4  
Dataset: Gen-3 V2 `b4bc7a0e…`  
Development: 2021–2023, 547,835 rows  
Validation: 2024, 182,449 rows  
Estimator: multinomial logistic, L2, LBFGS, C=0.05, max_iter=2000, tol=1e-7, n_iter=673

Persisted evidence:

| Artifact | SHA-256 / result |
|---|---|
| Evidence manifest | `8229d1fd51b46433c046bc2ae54aafe0334b1c5502bd151e4ded0c9e698acc3e` |
| Predictions | `320868d9ae1b0fbf27f2a19144d52a555dffea5b1ec3a34cb9fd68dd0cfb555d` |
| Validation target/row IDs | `6cb9dd8bec18427679403871f45e6b755795b7bb4721bcb3b659c2c18564f46a` |
| Diagnostics | `dc866ddfd28d925518412cd48efc11b9d5ab2a9da04c62481e7097dcd65f137d` |
| Model coefficients/intercept | `7ef21cfd4b4092156538f032fb673de8e357375f3dfa0db7e6cde9b4e404d169` |
| Preprocessor | `49623488530bba3e1d6e9baba29a6d41e0d2902c946f8220f7f4acfc4c9aad98` |

Independent recomputation used only persisted 2024 target/prediction artifacts, not project metric helpers and not a reconciliation JSON:

| Metric | Stored | Independent | Difference |
|---|---:|---:|---:|
| Log loss | 1.4827332596445002 | 1.4827332596445002 | 0 |
| Summed multiclass Brier | 0.7061395390730664 | 0.7061395390730664 | 0 |
| Top-label ECE (10 equal-width bins) | 0.003112544507234644 | 0.003112544507234644 | 0 |
| Top-1 accuracy | 0.45242232075812966 | 0.45242232075812966 | 0 |
| Macro F1 | 0.08640780054871053 | 0.08640780054871054 | rounding only |

The predictions are finite with shape 182,449 × 8 and maximum row-sum error `4.44e-16`. Class order is:

`STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH`.

A2 run revision is `e75eec9f8df8999cd3a6ec0e19ae44f80584ea6d`, while current HEAD is `93f1634…`. The only committed difference is the Phase 7C handoff report; all server/scripts/src/tests modeling code is byte-identical. Therefore A2 is accepted as exact evidence for the current scientific code, but the handoff phrase “current-HEAD cryptographic reproduction” is literally overstated. The currently active candidate is the older HGB run `ce8ca6b28284491e95a187de3908e6d7`, not this A2 logistic run.

Specific A2 evidence accepted: **yes**. General evidence immutability/activation mechanism accepted: **no**.

## 8. Evidence-bundle checklist

| Required evidence | A2 state | Platform conclusion |
|---|---|---|
| Run authority/object receipt/binding/contracts | Present in run JSON | Not mutually bound into an immutable bundle; consumer does not reverify all parents. |
| Effective ordered features | Present | Hard-coded global list, not generation-contract derived. |
| Preprocessor | Full state present | Current hash matches. |
| Estimator | Full logistic coefficients present | HGB stores no fitted trees; family-wide claim fails. |
| Class order | Present and exact | Pass. |
| Validation row IDs/target/probabilities | Present | 182,449 2024 rows; current hashes pass. |
| Aggregate/per-class/confusion/reliability | Present | Independent aggregate and diagnostics checks pass. |
| Coefficients/importance | Logistic coefficients present | HGB has neither fitted estimator nor feature importance. |
| Convergence/warnings/runtime | Present for A2 | Run lifecycle still lacks durable queued/running/crash attempt. |
| Code/environment | Present | Coverage/fail-closed behavior incomplete. |
| Manifest SHA | Run records it and current bytes match | Downstream does not anchor manifest bytes to it. |

## 9. Phase 7C §25 debt classification

| Item | Phase 7B | Scientist testing | Private beta | Production | Minimum next action |
|---|---|---|---|---|---|
| A. Legacy DatasetSection/TargetSelector bookmarks | **Blocks** because they can misidentify controlled experiments | Blocks | Blocks | Blocks | Remove/demote; bind Objective/Target to server authority. |
| B. Full `extra=forbid` schemas | Nonblocking for one trusted developer | Strongly recommended | Blocks | Blocks | Typed bodies, exact numeric types, uniform 4xx mapping. |
| C. Per-user/project scheduler | Nonblocking for serial local work | Blocks concurrent cohort | Blocks | Blocks | Bounded queue/semaphore, quotas, cancellation/idempotency. |
| D. QUEUED/RUNNING attempts | Nonblocking for bounded serial acquisition | Blocks reliable multi-run testing | Blocks | Blocks | Durable attempt before fit; terminal failure classes. |
| E. Authoritative Simulation not configured | Nonblocking while explicitly unavailable | Nonblocking if out of test scope | Blocks any beta claiming simulation | Blocks capability claim | Keep blocked or implement active-run-bound 2024 simulation. |
| F. Canonical feature ablation not configured | **Blocks controlled Phase 7B data-value experiments** | Blocks feature-science workflow | Blocks | Blocks | 2024-only, active-binding/run-authority ablation with uncertainty. |
| G. Generated TypeScript API types | Nonblocking debt | Nonblocking alone | Recommended | Blocks robust schema governance | Generate from strict server schemas. |
| H. Dedicated two-user/two-project lifecycle test | Nonblocking for trusted local acquisition | Blocks acceptance confidence | Blocks | Blocks | Authenticated HTTP lifecycle using temporary stores/registry. |
| I. Rendered frontend harness | Nonblocking for backend acquisition | Blocks | Blocks | Blocks UI release | Rendered project/binding transition and stale-state tests. |

Additional unlisted Phase 7B blockers: sole immutable registry, system-wide sealed-data capability, generation-specific feature authority, object verifier containment/metadata/cache, evidence manifest anchoring, activation checks, and fitted HGB persistence.

## 10. Minimum hardening sequence

1. **Registry/object boundary:** install one immutable registry resolver; retire stale selectable entries; contain paths; authenticate complete embedded/manifests; eliminate unsafe cache trust.
2. **Seal boundary:** remove 2025 metrics/forensics from ordinary workflow; force every tracked script through research-only resolution; administrative capability-gate all sealed reads; remove 2025 from selection/readiness logic.
3. **Scientific authority:** derive target/population/temporal/features/preprocessing from the active binding; make Phase 7B feature contracts executable; remove fixed Gen-2 and browser-note authority conflicts.
4. **Evidence boundary:** atomically/content-address the complete run bundle; anchor manifest to run; verify before activation/read; require COMPLETE/current binding/authority; persist full estimators.
5. **Transition and drift:** idempotent/CAS binding; shared revision-aware frontend state; cancel stale requests/saves; fail closed on unknown Git/env and bind relevant untracked/config contents.
6. **Operational proof:** strict schemas, bounded scheduler, attempt lifecycle, isolated tamper/HTTP/resolver tests, independent metrics, and rendered UI transitions.

## 11. Required final summary

**GEN-2**

- research object = `50ce1def3315f5e4d9c5bd1ba9cb72490f33d20303720eb814f4eff1742eaf58`
- research seasons = 2023, 2024
- sealed object = `a04852d56cdeb42298d1d72c531c369c4c9ef142658b18c2ecb51b9a3fc7f5a4` (metadata only; not opened)
- contracts correct = yes for current registration
- object verified = current research bytes yes; verifier hardening incomplete
- ordinary sealed opens = canonical service 0; system-wide guarantee failed

**GEN-3 V2**

- research object = `b4bc7a0ebb593e919b6eecfa1b10815314e4a917877571c03d05e531bf36bdea`
- research seasons = 2021, 2022, 2023, 2024
- sealed object = `4c33b9e57a6b8ffc00cd3ac803c31b31b75e0cf38cde6fbcd17027f669a06d20` (metadata only; not opened)
- V2 bundle = `86a60f6caefc74b14f8068d684541dd8d03ed66004cf95632374e10f1fd65ffa`
- object verified = current research bytes yes; verifier hardening incomplete
- ordinary sealed opens = canonical service 0; system-wide guarantee failed

**AUTHORITY**

- one active dataset = backend execution yes; product-wide no
- one target = no
- one run service = yes for live UI execution
- one active candidate = one pointer, but activation verification fails
- browser authority remaining = yes
- legacy execution callers = zero live binding-free HTTP callers; dead frontend code plus multiple tracked direct CLI callers remain

**RUN EVIDENCE**

- model persisted = A2 logistic yes; HGB no
- preprocessor persisted = yes
- predictions persisted = yes
- targets/row IDs persisted = yes
- diagnostics persisted = yes
- independent metric recompute = exact
- full manifest verified = current A2 bytes manually yes; product consumption no

**DOWNSTREAM**

- Evaluation = active candidate evidence plus conflicting 2025 Phase-4 evidence; fail
- Calibration = same active run, honestly raw/unconfigured; pass with activation caveat
- Simulation = honestly NOT CONFIGURED
- Feature Ablation = honestly NOT CONFIGURED; blocks Phase 7B controlled feature-value work
- Champion = read-only/disabled promotion; 2025 champion evidence leaks through Objective
- Registry = active-run driven but evidence chain not fully authenticated

**2025**

- sealed opens by audit = 0
- sealed target reads by audit = 0
- sealed predictions by audit = 0
- new metrics computed by audit = 0
- ordinary payload exposure = yes, pre-existing metrics/forensics
- archived combined object opens by audit = 0; tracked ordinary executable paths remain

**SECURITY**

- two-user = owner/cross-user matrix passes
- two-project = isolated project roots and ACL matrix pass
- cross-project denial = 24/24 denied; owners 24/24 allowed
- traversal = project-state pass; dataset-object containment fail
- code drift = tracked pre/post-fit pass; UNKNOWN/untracked/final-env gaps fail
- resource bounds = partial; family limits/candidate cap pass, strict schemas/scheduler/concurrency fail

**A2**

- run ID = `781b6bc15d8f4101a8f3e8a07558cae3`
- development rows = 547,835
- validation rows = 182,449
- stored LL = 1.4827332596445002
- independent LL = 1.4827332596445002
- difference = 0 (3.56e-10 versus rounded governed reference 1.48273326)
- accepted = yes for the specific current-science-code evidence; not proof that the general authority/evidence system is immutable

**DEBT CLASSIFICATION** = §25 contains real nonblocking items, but A/F plus the unlisted registry, seal, feature-authority, verifier, and evidence issues block Phase 7B.  
**PHASE 7B DECISION** = **NO-GO**  
**SCIENTIST TESTING DECISION** = **NO-GO**  
**PRIVATE BETA DECISION** = **NO-GO**  
**PAID PILOT DECISION** = **NO-GO**  
**PRODUCTION DECISION** = **NO-GO**  
**PRIMARY VERDICT** = **PHASE_7C_HARDENING_REQUIRED_BEFORE_PHASE_7B**
