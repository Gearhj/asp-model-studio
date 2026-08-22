# ASP Model Studio Phase 7D — Independent Codex Acquisition-Readiness Gate

## Gate result

`PHASE_7D_REPAIRS_REQUIRED_BEFORE_PHASE_7B`

| Decision | Result |
|---|---|
| Phase 7B local acquisition | **NO-GO** |
| Scientist testing | **NO-GO** |
| Private beta | **NO-GO** |

The Phase 7D happy path is materially better than Phase 7C: the live catalog has the intended two research and two sealed entries, normal catalog listing opens no Parquet, canonical synthetic execution and ablation remain on 2024, path containment rejected the tested Windows escape forms, an HGB estimator reproduced its persisted validation probabilities bit-for-bit, and the focused Phase 7D suite passes 7/7.

Those controls are not yet sufficient for the narrow Phase 7B gate. A missing canonical registry silently restores mutable sidecars as execution authority; the approved research-path helper can bypass the object receipt verifier; the advanced-feature contract admits a direct target proxy; feature-family ablation does not require a strict control-plus-family challenger; ordinary tracked scripts can still open, score, and use 2025; and mutable run JSON can be altered and activated despite valid evidence bytes. Each defect can corrupt or misidentify a 2024 feature-family experiment, admit sealed influence, or activate fabricated evidence.

Landing source files into a separate, quarantined 2019–2024 staging area could be done manually without using these services or scripts. That limited activity is not an acceptance of the requested Phase 7B pipeline, which also includes derived state, advanced-view registration, governed ablation, and activation.

## 1. Repository and audit boundary

| Item | Independently observed value |
|---|---|
| Repository | `C:\Users\james\asp-model-studio` |
| Branch | `phase7d-acquisition-gate-hardening` |
| Full HEAD | `1aa274ad943a70689ca0c52e41a75958240c3144` |
| `main` reference | `924db29511f93909f9d785855bfa056775443690` |
| Merge base with `main` | `924db29511f93909f9d785855bfa056775443690` |
| Phase 7C comparison point | `93f1634e27ed32f713edd6cf43035d56baf546fa` |
| Phase 7D commits | `6237ad4`, `5919999`, `dc95ff6`, `3187808`, `1aa274a` |
| Tracked Phase 7D delta | 10 files, +1,053 / -200 |
| Raw/runtime/governed data committed in delta | None |
| Evidence of a Phase 7D external-data download | None found in Git; filesystem history cannot independently prove that no prior local download occurred |
| External data downloaded by this audit | No |
| Real sealed 2025 data opened or scored | **No** |
| D3/C4 retrained or changed | No |
| Candidate promoted | No |
| Source or tests modified | No |
| Commit or push | No |
| File created by this audit | `docs/PHASE_7D_CODEX_ACQUISITION_READINESS_REPORT.md` only |
| Final worktree | Tracked clean; six untracked audit reports including this report |
| Governed science state | Unchanged |

The five pre-existing untracked audit reports were preserved:

- `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`
- `docs/PHASE_7A2_CODEX_ACCEPTANCE_REPORT.md`
- `docs/PHASE_7A5_CODEX_FINAL_ACCEPTANCE_REPORT.md`
- `docs/PHASE_7C_CODEX_FINAL_ACCEPTANCE_REPORT.md`
- `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md`

The Phase 7D delta adds two documents and one test and modifies the cockpit engine, authority service, router, Gen-3 contracts, one Phase-4 decision service, and two cockpit UI files. It adds no Parquet, CSV, raw baseball data, registry, or runtime artifact. `git diff --check` was clean before this report was created.

## 2. Diagnostic and test record

All behavioral probes used disposable synthetic objects, registries, projects, and evidence directories. Temporary artifacts were removed. Two additional probe starts were denied before fixture creation because their selected temp roots were inaccessible; their empty roots were subsequently removed and they produced no behavioral evidence. Metadata-only inspection of the real registry did not open its research or sealed Parquet objects.

| Diagnostic | Result | Safety / interpretation |
|---|---|---|
| `.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp <disposable-root> tests/sports_cockpit_phase7d_acquisition_test.py` | **7 passed** in an isolated writable temp root | Synthetic only; zero real sealed opens. The first default-temp attempt failed during pytest setup because that Windows temp root was inaccessible; no test body ran. |
| `tests/sports_phase4_incremental_signal_study_test.py` | **8 passed, 5 failed** | Synthetic regression suite. All five decision tests now fail at the new environment-string guard; the surrounding tests were not updated. |
| `tests/gen3ScientistFlow.test.mjs` | **5 passed, 1 failed** with `--test-isolation=none` | The default `node --test` attempt first failed with sandbox spawn `EPERM`. The isolated-mode failure is a stale comment-string expectation and illustrates that this is source-text checking, not an end-to-end browser proof. |
| Canonical catalog metadata check | 4 returned; 2 selectable; 2 restricted; object opens 0 | The persisted V3 registry has 9 entries total: 4 current and 5 archived. |
| Registry fallback probe | Missing registry used sidecars; forged sidecar became bindable | Fails the sole-authority and fail-closed claims. |
| Registry migration probe | Second migration not byte-identical; migration ID changed | Two concurrent migrations both succeeded with different IDs. |
| Containment matrix | 8/8 escape variants rejected; outside open count 0 | Covered outside absolute, traversal, backslashes, encoded traversal, drive, UNC, and mixed separators. A reparse ancestor was unavailable in the test environment. |
| Receipt/cache matrix | Warm forged receipt accepted; missing publication manifest accepted; wrong content-address hardlink accepted; an object with unknown target classes passed object verification | Physical byte hash is recomputed, but the full receipt is not an invariant. Later execution label encoding rejects unknown classes. |
| Advanced-feature proof | Registered synthetic column entered the matrix once | The column was an explicit target proxy, so this proves wiring while disproving leakage safety. |
| Invalid ablation probe | A 1-feature challenger was accepted against a 22-feature control | The service does not enforce control plus one declared family. |
| Estimator reproduction | Persisted HGB + reconstructed persisted preprocessor reproduced probabilities bit-for-bit; max absolute difference 0 | Positive evidence for estimator bytes and preprocessing state on the synthetic fixture. |
| Run tamper / activation | Changed stored LL to `-999` and family to `fabricated_family`; activation accepted both | The mutable run record is not authenticated by the evidence bundle. |
| Coordinated evidence tamper | Child + manifest + mutable run anchor replacement accepted | The downstream anchor is mutable and therefore not an immutable parent receipt. |
| Code identity probe | Untracked scientific-file content change was not detected when its path stayed constant | Untracked names/status are bound; contents are not. |
| Request strictness matrix | Extra top-level field, fractional/huge seed rejected; arbitrary/unknown nested hyperparameters accepted or ignored; fractional HGB integer truncated | Canonical DTO strictness is partial. |

No test or diagnostic opened or scored real sealed 2025 data. No governed registry, dataset, evidence, D3, or C4 artifact was written.

The registry/cache/ablation/evidence/request matrices above were one-off read-only audit probes executed with `.venv\Scripts\python.exe -B` against disposable roots and production service functions. Their input cases and exact observed outputs are retained in this table, but the inline probe bodies were not added to the repository and are not claimed as committed regression tests. Each failing case should be converted into a hermetic test before the repair gate is accepted.

## 3. Prioritized acceptance findings

### P0 — Advanced-feature authority admits direct target leakage

The new feature-set contract contains generation, name, ordered feature names, and count, but not feature dtype, derivation, source receipt, point-in-time/as-of rule, prohibited inputs, knowledge-time class, or a feature-family digest (`server/sports_modeling/gen3_contracts.py:212-222`). The underlying Gen-3 feature schema and knowledge-time definitions still describe only the base feature set (`server/sports_modeling/gen3_contracts.py:50-59,72-88`). `_resolve_feature_set` accepts a unique string list from registry metadata (`server/sports_cockpit/gen3_authority.py:627-641`), while object verification continues to require only the global base `FEATURE_NAMES` (`server/sports_cockpit/gen3_authority.py:453-466`).

The acceptance fixture defines `outcome` from class index `ci`, then constructs `synthetic_signal = float(ci) + noise`, registers that column as advanced, and successfully trains it (`tests/sports_cockpit_phase7d_acquisition_test.py:37-45,76-85,147-161`). That is an overt target proxy. The test proves a registered column propagates through the pipeline, but it also proves production will accept a leakage feature.

Impact: a Phase 7B feature can appear governed while directly encoding the terminal target or future information. Its resulting 2024 gain would be invalid.

Required repair: publish a versioned per-feature contract containing dtype/nullability, derivation identity and code digest, source receipts, temporal/as-of rule, leakage classification, allowed target relationship, and declared family membership. Bind it into dataset logical identity, registry, object metadata, run authority, evidence, and result DTO. Add negative tests for target, post-terminal, future-season, ID-derived, and reordered features.

### P1 — The V3 registry is not the sole fail-closed authority

When the canonical registry is missing, `_canonical_registry` reconstructs a catalog from mutable generation sidecars (`server/sports_cockpit/gen3_authority.py:280-286`). A hermetic forged sidecar became bindable and caused an object open. Sidecars are therefore still potential execution authority.

`migrate_registry` always assigns a new migration UUID and timestamp and rewrites the file (`server/sports_cockpit/gen3_authority.py:244-268`). Repeating the same migration changed both bytes and migration ID. Two simultaneous migrations both succeeded with distinct IDs. There is no idempotent no-op, interprocess lock, or compare-and-swap conflict result.

Positive control: with the real V3 registry present, catalog returned exactly four current records—two selectable research and two restricted sealed—and logged zero object opens. Five additional records are archived. That correct present state does not remove the fallback and migration failure modes.

Impact: deletion, partial deployment, or concurrent migration can silently substitute mutable publisher sidecars, select the wrong object, or create divergent registry authority.

Required repair: fail closed on absent/invalid V3 registry; treat sidecars only as explicit migration inputs; validate registry schema, unique IDs, exact content addresses and four-current-entry invariants; use an interprocess migration lock and compare-and-swap; make an already-canonical migration byte-for-byte idempotent.

### P1 — Research object loading can bypass the full receipt verifier

`research_object_path` checks catalog status/capability and path containment but returns a path without calling `_verify_object` (`server/sports_cockpit/gen3_authority.py:307-315`). The descriptive engine then reads that Parquet and calculates a hash after use (`server/sports_cockpit/engine.py:176-216`). A synthetic registry with a forged expected physical receipt still yielded an approved research path.

The cold verifier recomputes physical bytes and checks several receipt fields, but important conditions remain incomplete or bypassable (`server/sports_cockpit/gen3_authority.py:364-466`):

- the publication manifest is optional (`server/sports_cockpit/gen3_authority.py:425-432`);
- exact content-addressed path identity is not enforced, so a hardlink at the wrong logical address was accepted;
- target class domain/order was not enforced by the object verifier (later execution label encoding rejects unknown classes);
- ordered advanced feature identity is not an object invariant;
- the cache key covers path, physical SHA, logical SHA, generation, and object kind, then returns before rechecking schema, counts, bundle/contracts, seasons, and features;
- a warm-cache call accepted forged expectations for those omitted receipt fields.

Actual same-size/same-mtime byte substitution is rejected because the physical SHA is recomputed. The failure is expectation substitution and incomplete receipt closure, not reliance on size/mtime alone.

Impact: a governed consumer can read before receipt validation or accept an object whose registry expectations, target domain, feature order, publication manifest, or content address are wrong.

Required repair: make every governed research open return a verified immutable object handle/receipt, not a bare path. Require and hash the publication manifest; verify exact logical-address path, publisher-compatible schema including nullability, every embedded contract, class order, row and per-season counts, and exact ordered registered feature set. Recompute the full receipt on each execution, or cache only by a digest of the entire canonical registry receipt plus physical bytes.

### P1 — Feature-family comparison does not establish a feature-family ablation

`MODEL_FEATURE_FAMILY_ABLATION_V1` resolves two registered name lists, calculates `challenger - control`, and runs them (`server/sports_cockpit/gen3_authority.py:1102-1118`). It does not require:

- challenger ordered prefix equals the entire control;
- no control feature is removed or reordered;
- exactly one declared feature family is added;
- the added columns share a governed derivation/family identity;
- control and challenger feature contracts are immutable children of the same dataset publication.

A synthetic challenger containing only one feature was accepted against the 22-feature control. The reported “family added” set was empty, yet both runs and the comparison completed. Therefore a delta may reflect removing or replacing the control rather than adding a feature family.

The implemented metric difference is `challenger - control`; negative favors the challenger (`server/sports_cockpit/gen3_authority.py:1129-1138`). The paired game-cluster percentile interval is correctly computed on 2024 log-loss differences (`server/sports_cockpit/gen3_authority.py:1139-1153`), but no paired interval is supplied for Brier, ECE, top-1, macro-F1, or class-level changes. The comparison JSON is replaceable and lacks a verified retrieval/parent-anchor chain (`server/sports_cockpit/gen3_authority.py:1172-1174`).

There is also no frontend caller for `/cockpit/gen3/feature-family-ablation`; the Feature Engineering surface says canonical ablation is not configured (`src/sports/cockpit/cockpitSteps1.tsx:1608-1624`). The legacy Model Lab suite is hard-disabled (`src/sports/cockpit/cockpitSteps2.tsx:56-63,145-146`), Autopilot is the only canonical execution caller (`src/sports/cockpit/cockpitSteps2.tsx:334-395`), and tuning remains unwired (`src/sports/cockpit/cockpitSteps2.tsx:400-415`). This UI gap is not the reason the server-side Phase 7B gate fails, but it independently blocks scientist use.

Impact: the central Phase 7B decision can label a non-comparable model pair as an advanced-family gain.

Required repair: bind a declared immutable family contract; enforce `challenger == control + exactly that ordered family`; require identical dataset, target, folds, preprocessing, family, effective hyperparameters, seed, and authority fingerprints; sign or content-address the comparison and both run parents; state delta direction; preserve row/game pairing; add strict removal/reorder/substitution negative tests.

### P1 — Evidence bytes do not authenticate the mutable run and activation record

Evidence children are staged and atomically renamed, and the synthetic HGB estimator is genuinely loadable. The complete scientific record is not one atomic content-addressed object (`server/sports_cockpit/gen3_authority.py:789-875`):

- the evidence directory is addressed by random run ID, not its content digest;
- the COMPLETE run JSON is a later, separate, ordinary writable file;
- the run JSON is the mutable anchor used to select the expected manifest SHA;
- the manifest need not prove the exact schema, run ID, or exact mandatory child set;
- downstream checks do not bind all run fields, metrics, fingerprints, receipt, and feature-set identity back to mandatory evidence children.

Behavioral proof: after a valid synthetic HGB run, changing only the run JSON model family and log loss to fabricated values still passed `activate_candidate`; `get_active_candidate` returned `fabricated_family` and `-999`. Evaluation detected a metric mismatch but did not reject the candidate. A coordinated child + manifest + mutable run-anchor replacement was also accepted. `_verify_run_chain` checks status, project, binding/revision, authority config hash, and the expected manifest reference, but does not reconstruct and compare the complete run record (`server/sports_cockpit/gen3_authority.py:1206-1233`). Result authority also omits feature-set name, ID, SHA, and ordered list (`server/sports_cockpit/gen3_authority.py:1016-1039`).

The internal joblib estimator is not a user-upload path, and its checksum is checked before load. The checksum and `joblib.load` are separate file opens, leaving a local TOCTOU window (`server/sports_cockpit/gen3_authority.py:888-898`). Logistic uses the common persistence path in source, but only HGB persistence/recompute was behaviorally proven in this audit.

Impact: a trusted-local filesystem change, interrupted publication, or coordinated replacement can fabricate the selected family/metrics or misattribute an advanced feature run while leaving individually plausible estimator bytes.

Required repair: publish one immutable, content-addressed run bundle containing the authority, exact request, object receipt, feature contract, preprocessor, model, predictions, targets/row IDs, diagnostics, metrics, and canonical manifest. Commit its receipt transactionally and never overwrite. Activation must reconstruct every displayed/run field from verified children and fresh canonical authority; a mutable index may point to a digest but may not define its content.

### P1 — The tracked script estate is not physically sealed for Phase 7B

The canonical catalog and synthetic canonical run/ablation path did not open sealed objects. That is a path-local pass, not a system-wide Phase 7B seal. No tracked script calls `research_object_path`; only the cockpit engine does (`server/sports_cockpit/engine.py:183`). No canonical Phase 7B acquisition script was added in this delta.

The strongest counterexample is `scripts/run_mlb_e1_e2_incremental_signal_study.py`: it opens combined feature/state/E1/E2 inputs, constructs 2025 labels, trains/scores 2024 and 2025, and bootstraps both before calling the new guard (`scripts/run_mlb_e1_e2_incremental_signal_study.py:73-137,263-289`). The guard is a self-grantable process environment string, `ASP_ARCHIVAL_AUDIT_CAPABILITY=SEALED_TARGET_DATA_READ` (`server/sports_phase4/incremental_signal_study.py:477-495`). It is neither a server-issued capability nor an audited administrative action. Ordinary invocation therefore reads and scores 2025 before failing; setting the string allows the 2025-based decision to finish.

Ordinary authenticated cockpit objective loading also still globs an archival experiment-metrics JSON and reads `aggregateMetrics.final2025` internally (`server/sports_cockpit/engine.py:254-290`). Exact frozen metrics remain in a source fallback (`server/sports_cockpit/engine.py:149-153`). Phase 7D removed the current objective DTO field and severe-miss panel, which is positive, but it did not establish zero ordinary 2025 metric reads. Population DTO/UI still exposes sealed-season aggregate counts; these are structural metadata, not sealed target rows or model metrics. Separately, the persisted legacy `LabCandidate.frozen` field can be restored from browser storage and rendered as `2025 frozen LL` (`src/sports/cockpit/cockpitApi.ts:191-202`, `src/sports/cockpit/cockpitPersistence.ts:88-99`, `src/sports/cockpit/cockpitSteps2.tsx:307-314`).

Impact: Phase 7B data-value work can accidentally run on an archived combined object or use 2025 in a feature/readiness decision despite the canonical API being sealed.

Required repair: provide tracked Phase 7B entry points that resolve only verified research objects through the V3 registry; move every capability check before path resolution/open; hard-disable or physically separate archived combined scripts and objects from ordinary research; replace forgeable environment strings with an unavailable-by-default audited administrative capability; add repository-wide open instrumentation tests.

### P1 — Request, code/environment, and resource authority remain partial

Top-level run/execute/ablation models forbid unknown fields and strictly constrain seed/bootstrap. Nested hyperparameters remain `dict[str, Any]` (`server/sports_cockpit/router.py:226-251`). Logistic silently ignores supplied hyperparameters; HGB ignores unknown keys and converts finite fractional integers with `int()` (`server/sports_cockpit/gen3_authority.py:603-623`). Bind, run-suite, and activation still accept raw dictionaries (`server/sports_cockpit/router.py:196-202,268-274,300-303`).

Run authority reconstructs project, binding, registry, and several contract identities, but validates model family, effective hyperparameters, seed, and feature-set name using values from the authority being checked and then recomputes a self-consistent hash (`server/sports_cockpit/gen3_authority.py:710-766`). There is no independent immutable request receipt against which those values are compared.

Unknown Git/environment identity fails closed, which is positive. `_code_identity` binds the tracked clean tree through HEAD and hashes tracked diffs, but it binds only untracked names/status—not their contents (`server/sports_cockpit/gen3_authority.py:115-130`). The demonstrated closure gap is therefore untracked scientific/config content; tracked repository lockfiles are covered by HEAD/diff. The post-fit drift check occurs before evidence publication, while a later unchecked environment digest is written into COMPLETE evidence (`server/sports_cockpit/gen3_authority.py:999-1039`).

The heavy-run bound is one in-process `RLock` per project and a suite cap of eight; a competing run receives 429 while the lock is held. There is no interprocess/durable exclusion, canonical timeout, or cancellation lifecycle. A whole suite does not retain one lock across all candidates, so two suites can interleave or partially fail.

Impact: malformed requests can be silently normalized, request fields can remain self-attested, a final drift race can produce COMPLETE evidence, and multi-worker or interleaved suite execution can misstate a controlled comparison.

Required repair: family-specific strict nested DTOs with finite/range/integer validation; immutable server-issued request receipt; final transactional code/environment check covering relevant untracked scientific/config contents as well as the tracked tree; interprocess per-project run/ablation lock; bounded timeout/cancellation and all-or-nothing suite semantics.

### P2 for trusted-local work, P1 for scientist use — Binding and browser authority debt

Binding creation is an unlocked read-modify-write operation. Same-version binding is not a no-op, compare-and-swap is not transactional, and binding does not share the heavy-run lock (`server/sports_cockpit/gen3_authority.py:477-516`). This debt alone would not block one rigorously serialized developer who pins and rechecks one revision, but it blocks scientist testing. A binding change during ablation must be a hard atomic failure, not merely two point-in-time checks.

The cockpit still contains browser-local Dataset/Target notes and binding-free fixed-Gen2 descriptive controls. They do not define the canonical server run or feature-family authority, so they are nonblocking for a future server/CLI-only Phase 7B path. They can still mark workflow stages complete, display stale population/lab state, and mislead a scientist about what executed; therefore they block scientist testing. The Gen-2 sealed catalog card also receives research styling because the UI recognizes only `GEN3_SEALED` as sealed (`src/sports/cockpit/Gen3CatalogSection.tsx:175-201`).

## 4. Canonical registry and script boundary

### Current registry state

The metadata-only V3 inspection found:

- 9 stored records;
- 4 current/nonarchived records;
- 2 selectable research records;
- 2 restricted sealed records;
- 5 archived records;
- normal catalog object opens: 0.

The registry file SHA-256 was `C6C45CEF59D951E62FA138FAD1B4B001039F4947153E311BD2391440B0F423DD`. The generation-specific base feature-set SHA-256 values were Gen-2 `64713c4a3e309e3787d3eefcb2edf2d93ac98326d6cfd3fdf5057a94367167da` and Gen-3 `cc56f155afae85d49d9f4f6ff30e66af43b0d375824b6effa5c3c99bed0acd51`. Both selectable real records currently had `featureSets={}`; Phase 7D has not published an actual advanced feature-set authority.

The four current roles are Gen-2 research (2023–2024), Gen-2 sealed (2025), Gen-3 V2 research (2021–2024), and Gen-3 V2 sealed (2025). The present records are correct, but missing-registry sidecar fallback means archived/noncanonical authority is not structurally impossible.

### Tracked baseball-script classification

Under the requested A/B/C/D definitions, there are currently no proven Class A scripts, no genuinely hard-retired Class B scripts, and no script with an unforgeable administrative sealed capability that qualifies for Class C. The 21 relevant entry points are therefore Class D pending explicit hardening.

- **A — Phase 7B approved:** canonical V3 registry plus verified research-only capability.
- **B — Retired archival:** hard fail-closed under ordinary invocation.
- **C — Administrative sealed:** explicit, audited sealed capability required and unavailable to Phase 7B research.
- **D — Unsafe/unclassified:** does not satisfy A, B, or C.

| Scripts | Class | Reason |
|---|---|---|
| `register_mlb_dataset.py`, `register_mlb_identity_bridge.py` | D — unclassified administrative metadata | They are not canonical Phase 7B research entry points and do not establish the V3 verified-object/capability boundary (`scripts/register_mlb_dataset.py:58-95`; `scripts/register_mlb_identity_bridge.py:92-147`). |
| `phase7a_build_gen3.py`, `phase7c_publish_gen2.py`, `phase7_build_gen3.py` | D — publisher/legacy | They read or materialize 2025; no unforgeable administrative capability is required. The legacy builder writes a combined 2021–2025 object (`scripts/phase7a_build_gen3.py:33-68,102-135`; `scripts/phase7c_publish_gen2.py:57-64,87-148`; `scripts/phase7_build_gen3.py:78-99`). |
| `phase7a_governed_ablation.py` | D — research but noncanonical | It is 2021–2024, but resolves a mutable registration sidecar directly, uses the fixed base list, and writes legacy evidence (`scripts/phase7a_governed_ablation.py:45-57,148-180`). |
| `run_mlb_pitch_sequence_features.py`, `run_mlb_process_interactions.py`, `run_mlb_catcher_readiness.py`, `run_mlb_game_replay.py` | D — acquisition/readiness | They inspect or materialize 2025 events/predictors and can influence acquisition/readiness decisions; none uses the canonical verified research resolver (`scripts/run_mlb_pitch_sequence_features.py:119-164`; `scripts/run_mlb_process_interactions.py:123-155`; `scripts/run_mlb_catcher_readiness.py:161-202`; `scripts/run_mlb_game_replay.py:39,78-81,197-238`). |
| `phase7_ablation.py`, `run_mlb_pa_baseline.py`, `run_mlb_dynamic_player_state.py`, `run_mlb_participation_usage.py`, `run_mlb_e1_e2_incremental_signal_study.py`, `run_mlb_base_out_transition.py`, `run_mlb_projected_participation_ablation.py`, `run_mlb_severe_miss_forensics.py`, `run_mlb_simulation_input_layer.py`, `run_mlb_starter_identity.py`, `run_mlb_whole_game_monte_carlo.py` | D — unsafe executable legacy research | These remain invocable and read, score, or use 2025. Several select an object with `glob(...)[0]` (`scripts/phase7_ablation.py:109-162`; `scripts/run_mlb_pa_baseline.py:279`; `scripts/run_mlb_dynamic_player_state.py:271-365`; `scripts/run_mlb_participation_usage.py:330-423`; `scripts/run_mlb_e1_e2_incremental_signal_study.py:73-137,263-317`; `scripts/run_mlb_base_out_transition.py:43,82-85,284-325`; `scripts/run_mlb_projected_participation_ablation.py:60,109-142,347-353`; `scripts/run_mlb_severe_miss_forensics.py:118-181,261-289,422-446`; `scripts/run_mlb_simulation_input_layer.py:86,114-183,451-476,538-642`; `scripts/run_mlb_starter_identity.py:59,242-273,281-372`; `scripts/run_mlb_whole_game_monte_carlo.py:58,125-127,552-563,591-677`). The E1/E2 guard is late and self-grantable. |

Administrative acquisition/publishing is allowed to touch 2025 only with a real, audited capability and a purpose-specific isolated process. That enforcement is absent, so the files cannot be upgraded to Class C merely by documentation.

## 5. Acceptance-area determinations

### Registry

- Sole resolver: **No**. Mutable sidecar fallback remains.
- Exactly two selectable research and two restricted sealed current entries: **Yes, in the present V3 registry**.
- Archived entries nonselectable in the present registry: **Yes**.
- Archived/sidecar entries structurally nonexecutable: **No**.
- Catalog zero-object-open behavior: **Pass for the normal V3 catalog**.
- Migration atomic/idempotent/conflict behavior: **Fail**.

### Research-only capability and seal

- Canonical research API rejects sealed catalog entries before opening: **Pass in synthetic fixtures**.
- Ordinary scripts can obtain or self-assert sealed authority: **Fail**.
- Canonical run and canonical feature ablation use 2024 only: **Pass**.
- System-wide ordinary 2025 target/prediction/metric influence equals zero: **Fail**.
- Archived combined-object ordinary reachability: **Fail**.

### Path and object receipt

- Outside-root containment before open: **Pass for 8/8 tested Windows variants; outside open count 0**.
- Symlink/reparse ancestor: **Not exercised; unavailable in the fixture environment**.
- Physical SHA: **Pass; recomputed**.
- Same-size/same-mtime byte substitution: **Rejected**.
- Full registry expectation/cache substitution: **Fail**.
- Logical/schema/nullability/metadata/contracts/counts: **Partial cold-path checks, not a complete invariant**.
- Publication manifest: **Fail; optional**.
- Exact content-addressed path: **Fail**.
- Target class order: **Fail**.
- Ordered registered advanced features: **Fail**.

### Feature authority and propagation

- Generation-specific base feature-set ID: **Pass**; Gen-2 and Gen-3 base identities are distinct.
- Exact base feature-set SHA-256 identities: Gen-2 `64713c4a3e309e3787d3eefcb2edf2d93ac98326d6cfd3fdf5057a94367167da`; Gen-3 `cc56f155afae85d49d9f4f6ff30e66af43b0d375824b6effa5c3c99bed0acd51`.
- Actual selectable advanced sets: **None**; both current research records have `featureSets={}`.
- Old global list removed as object authority: **Fail**.
- Registered synthetic feature enters once in the requested order: **Pass as wiring**.
- Synthetic feature establishes scientific point-in-time safety: **Fail; it is a target proxy**.
- Client can name an unregistered feature set: **Rejected**.
- Registry/sidecar operator can authorize an arbitrary existing column without semantic feature validation: **Yes; blocker**.
- Result/evaluation echoes exact advanced feature-set identity: **Fail**.

### Ablation

- Both canonical arms use 2024 validation only: **Pass**.
- Same binding/target/population/fold/family/request intended: **Mostly bound by the service**.
- Challenger is proven to equal control plus one family: **Fail**.
- Feature-family identity is immutable and derivation-bound: **Fail**.
- Paired game-cluster uncertainty: **Pass for log loss only**.
- Comparison manifest immutable and parent-anchored: **Fail**.
- 2025 used by canonical ablation: **No in the synthetic proof**.

### Evidence and estimator persistence

- Child staging and atomic rename: **Pass**.
- Whole COMPLETE run is one content-addressed atomic bundle: **Fail**.
- Manifest anchored to immutable receipt: **Fail; anchor is mutable run JSON**.
- Independent child tamper blocked: **Generally detected against the current manifest**.
- Coordinated child + manifest + anchor tamper blocked: **Fail**.
- Fixed child path traversal: **Blocked by fixed-name containment**.
- Retry/no-overwrite conflict for the entire record: **Not established**.
- HGB fitted estimator persisted and loadable: **Pass**.
- HGB validation probabilities reproducible from estimator/preprocessor: **Pass, bit-for-bit on synthetic fixture**.
- Logistic persistence: **Common source path present; not behaviorally reproduced in this audit**.
- Safe deserialization boundary: **Internal artifacts only, but checksum/load TOCTOU remains**.

### Activation

- COMPLETE required: **Pass**.
- Current active binding/revision required: **Pass**.
- Separate authority and evidence checked: **Pass, but incompletely bound**.
- QUEUED/RUNNING/FAILED/stale binding intended rejection: **Present in status/revision checks**.
- Fabricated/tampered COMPLETE record rejected: **Fail**.
- `get_active_candidate` re-verifies: **Yes, but it repeats the same incomplete chain**.
- Displayed metrics/family reconstructed from evidence rather than run JSON: **Fail**.

### Authority, drift, and binding

- Project/binding/registry/contracts reconstructed: **Partial pass**.
- Model request independently authenticated: **Fail; request fields remain self-attested**.
- Unknown Git/environment rejected: **Pass**.
- Tracked dirty diff bound: **Pass**.
- Relevant untracked scientific/config contents bound: **Fail**; tracked repository files are bound through HEAD/diff.
- One final checked code/environment identity committed atomically with COMPLETE: **Fail**.
- Same-version bind no-op: **Fail**.
- Binding compare-and-swap atomic under concurrency: **Fail**.
- Binding debt alone blocks a rigorously serialized local run: **No**.
- Binding debt blocks scientist testing: **Yes**.

### Resource and request bounds

- One heavy run per project: **One per process**.
- Concurrent single run while lock held: **429**.
- One atomic suite/ablation across processes: **Fail/not established**.
- Candidates per `run_authorized_suite` request: **8 maximum**; there is no persistent/project-wide candidate-count cap across successive suites.
- Timeout/cancellation: **Absent**.
- Strict top-level execute/ablation DTO: **Pass**.
- Strict nested family-specific hyperparameters and all canonical routes: **Fail**.

### Project/path security and Python

- Production cockpit authentication: **Present globally** (`server/main.py:463,500`).
- Gen-3 project-scope authorization: **Present on canonical routes**.
- Fresh two-user/two-project HTTP matrix in the Phase 7D 7-test suite: **Absent**; source review found no deliberate removal, but this audit does not misstate it as behaviorally re-proven.
- Project/object traversal matrix: **Pass, 8/8; zero outside opens**.
- Exact content-address/hardlink identity: **Fail**.
- Python execution default: **Disabled** (`server/python_execution.py:111`).

### Browser authority debt

Browser-local DatasetSection/TargetSelector notes do not alter canonical binding, target, feature-set authority, run authority, server feature-family ablation, or verified active-candidate endpoint. Therefore that browser debt is **nonblocking by itself for a future CLI/server-only Phase 7B path**. It still creates contradictory stage completion and evidence presentation and therefore **blocks scientist testing and private beta**.

## 6. Acceptance-suite quality

The 7/7 suite is a meaningful synthetic happy-path test: it uses temporary roots, the production authority service, real synthetic Parquet, actual authority issuance/execution/evidence publication/activation, open instrumentation, an HGB estimator type check, and basic tamper/authority negatives. It does not touch shared governed data or real sealed 2025.

It is insufficient for the claimed final gate because it does not cover:

- missing-registry fail-closed behavior or forged sidecars;
- migration idempotency, conflict, and concurrency;
- complete receipt/cache expectation forgery;
- missing/forged publication manifest;
- exact content-address/hardlink identity;
- target class order and advanced ordered feature identity;
- target/future/post-terminal leakage features;
- challenger removal, reordering, substitution, or empty added family;
- coordinated run + manifest + child tamper;
- fabricated COMPLETE run fields/metrics;
- exact mandatory evidence-child set and interrupted publication;
- logistic estimator reload/recompute;
- self-consistent request-authority forgery;
- final post-fit/pre-COMPLETE environment race;
- multi-process execution/migration/binding exclusion;
- strict nested hyperparameter matrices;
- full current two-user/two-project HTTP behavior;
- system-wide tracked-script open instrumentation;
- actual scientist UI transitions.

Most importantly, its advanced feature is generated from the target class. Passing that fixture is evidence against, not for, a safe scientific feature boundary.

## 7. Minimum repair gate before Phase 7B

1. Make the V3 registry mandatory and fail closed; remove sidecars from ordinary resolution; make migration locked, conflict-aware, and byte-idempotent.
2. Route every research consumer through a full verified-object receipt; require publication manifest, exact content address, class order, per-season counts, and registered ordered feature schema on every governed open.
3. Publish advanced per-feature derivation/provenance/knowledge-time/leakage contracts and bind them into dataset, registry, object, authority, evidence, and result identities.
4. Enforce a strict immutable `control + one declared family` ablation contract and parent-anchor the comparison.
5. Replace mutable run/evidence trust with one append-only content-addressed bundle and reconstruct activation/displayed results from it.
6. Add tracked Phase 7B research entry points using the verified V3 research resolver; hard-disable or administratively isolate all combined/2025 scripts before any open; remove forgeable environment-string authority.
7. Authenticate the effective model request; close relevant untracked scientific/config identity; perform one final transactional drift check; add interprocess run/ablation locking and strict nested request schemas.
8. Extend hermetic tests with the negative matrices above, including a scientifically valid point-in-time synthetic feature and explicit target-proxy rejection.

## 8. Required final field summary

### REGISTRY

```text
sole resolver = no
selectable research entries = 2 current
restricted sealed entries = 2 current
archived entries = 5
catalog object opens = 0 with the present V3 registry
sidecars authoritative = yes when the V3 registry is absent; blocker
```

### SEAL

```text
ordinary sealed opens = 0 in the canonical synthetic path; not enforced system-wide
target reads = 0 canonical; ordinary tracked scripts can still read 2025
predictions = 0 canonical; ordinary tracked scripts can still score 2025
metrics = 0 canonical ablation; objective still reads archival final2025 internally
payload exposure = current objective metric field removed; sealed counts are metadata, while legacy persisted frozen metric presentation remains possible
archived combined opens = 0 in the canonical fixture; executable legacy scripts can still open them
Phase 7B-approved script seal = fail; no tracked Class A entry point
```

### OBJECT VERIFIER

```text
path contained before open = yes for 8/8 tested escape variants
physical SHA = yes, recomputed
logical SHA = cold-path check present; full receipt bypass remains
schema/nullability = cold-path check present; warm expectation substitution remains
embedded metadata = partial, not complete feature/target identity
publication manifest = optional; fail
bundle/contracts = cold-path checks present; warm cache bypass and bare-path consumer remain
generation/object kind = checked, but exact content address is not
seasons/rows/features = partial; object verification does not enforce target class order or advanced ordered features, though execution label encoding rejects unknown classes
cache substitution = byte substitution rejected; forged expectation substitution accepted
```

### FEATURE AUTHORITY

```text
generation-specific = yes for named feature-set identity; semantic contract incomplete
global fixed list authority = yes for object completeness; not fully removed
synthetic advanced feature proof = wiring pass, scientific leakage fail
client arbitrary feature = unregistered name rejected; arbitrary registry column lacks semantic validation
```

### ABLATION

```text
2024-only = yes on the canonical service
control/challenger authority = incomplete; strict superset/equality constraints absent
feature-family identity = no governed derivation/family identity
uncertainty = paired game-cluster interval for log loss only
2025 usage = none in canonical synthetic ablation; unsafe legacy studies remain
```

### EVIDENCE

```text
atomic/content-addressed = atomic child publication only; full run chain no
manifest anchored = to mutable run JSON, not an immutable external receipt
tamper blocked = independent mismatch generally yes; coordinated replacement no
child traversal blocked = yes for fixed child names
logistic persisted = common source path, not behaviorally reproven
HGB persisted = yes
independent recompute possible = yes for synthetic HGB, bit-for-bit; logistic untested
```

### ACTIVATION

```text
COMPLETE required = yes
active binding required = yes
authority verified = partial
evidence verified = partial and mutable-anchor dependent
fabricated/noncomplete rejected = noncomplete yes; fabricated/tampered COMPLETE no
active read reverifies = yes, but repeats the incomplete chain
```

### AUTHORITY / DRIFT

```text
reconstructed = project/binding/registry/contracts partial pass; model request not independently anchored
self-attested forgery rejected = no
unknown Git/env rejected = yes
untracked/config closure = tracked tree yes through HEAD/diff; relevant untracked contents no
final drift check = no transactional final check
```

### RESOURCE BOUND

```text
heavy runs/project = one per process
concurrent suite result = suites can interleave/partially 429; no durable all-suite lock
strict schemas = partial; nested hyperparameters and several routes remain permissive
```

### SECURITY

```text
two-user = production authentication and project authorization present; not behaviorally rerun by the Phase 7D 7-test file
two-project = project-scope calls present; full current matrix absent from the Phase 7D suite
cross-project = source enforcement retained; not claimed as freshly behaviorally re-proven here
traversal = 8/8 tested path variants rejected; zero outside opens
Python default = disabled
```

```text
REMAINING DEBT = blocking registry fallback/migration, incomplete verified-open boundary, target-leaky feature contract, invalid ablation identity, mutable evidence/run activation, executable 2025 scripts, partial request/drift/resource authority; browser and binding debt additionally block scientist use
PHASE 7B DECISION = NO-GO
SCIENTIST TESTING DECISION = NO-GO
PRIVATE BETA DECISION = NO-GO
PRIMARY VERDICT = PHASE_7D_REPAIRS_REQUIRED_BEFORE_PHASE_7B
```
