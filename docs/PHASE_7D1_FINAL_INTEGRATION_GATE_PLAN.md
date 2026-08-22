# Phase 7D.1 — Final Advanced-Data Integration Gate — PLAN (Gate 0 read-only inventory)

**Branch:** `phase7d1-final-integration-gate` · **Starting HEAD:** `962a40b19d6a0ee22782a0ec1fff577b25948098`
**Main:** `924db29` (untouched) · **Push:** none.

## HEAD reconciliation (read-only, before any change)

The prompt's *expected* starting HEAD was `a188ab8`. The **actual** resolved HEAD is `962a40b`
("Major commit", authored by Gearhj on 2026-08-21 21:09). That commit is **benign**: `git show 962a40b
--name-status` shows it adds **only** the six preserved audit/acceptance report markdown files
(`GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`, `docs/PHASE_7A2_/7A5_/7C_/7D_/7_CORE_CODEX_*REPORT.md`, 2,747
insertions, **no code, no Bronze data**). `962a40b` is **not** on `main`. The new phase branch is created
from `962a40b`, which preserves those reports as committed history rather than rewriting anything.

## Preconditions (all satisfied)

- Tracked worktree clean (`git status --short` empty).
- Bronze acquisition finished; **no** acquire/governed process running (`ps -W` inspected).
- Bronze manifest present; **SHA matches** the expected
  `fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a`.
- Canonical registry present: `ASP_DATASET_REGISTRY_V3`, migrationId `c2918bde…`, **9 datasets**
  (2 selectable research + 2 restricted sealed + 5 archived lineage) — the Gate-1 expected shape.
- Real Gen-2 v1 + Gen-3 v2 objects published under `.runtime/…/sports-modeling/…` → governed hermetic
  tests can run against real objects.

## Current-state inventory (what already exists from 7C/7D, and where it is)

| Concern | Symbol / location | State found |
|---|---|---|
| Canonical registry resolver | `_canonical_registry()` [gen3_authority.py:280] | **Fallback present** — if registry file absent, derives from sidecars read-only. Gate 1 requires fail-closed. |
| Registry migration | `migrate_registry()` [gen3_authority.py:244] | Atomic write; **not byte-idempotent** (fresh `migrationId`+timestamp every run); **no interprocess lock / CAS**. |
| Research object resolver | `research_object_path()` [gen3_authority.py:307] | Returns a **bare `Path`**; only `_reject_sealed_target_read` + containment, **not** full `_verify_object`. Consumed by `engine.py:_feature_view_path` [engine.py:176]. |
| Object verification | `_verify_object()` [gen3_authority.py:364] | Strong (physical/logical/schema/embedded/bundle/season/counts/features). **But** verification cache returns early [line 386-388] before re-checking schema/counts/bundle → Gate 5 violation. |
| Verification cache | `_VERIFIED_OBJECT_CACHE` [gen3_authority.py:359] | Keyed by (path, physical, logical, gen, kind); early-return skips full receipt recheck. |
| Feature-set contract | `feature_set_contract()` [gen3_contracts.py:212] | `MLB_FEATURE_SET_CONTRACT_V1` (ordered names + count only). **No** per-feature semantic contract, **no** family contract, **no** V2 binding. |
| Feature-family ablation | `run_feature_family_ablation()` [gen3_authority.py:1088] | Computes `added` set + paired game-cluster bootstrap. **Does not enforce** strict control-prefix identity (no reorder/removal/substitution/one-family checks). Comparison persisted as replaceable `{sha}.json` under `ablations/` (Gate 14 wants content-addressed evidence). |
| Run evidence bundle | `_write_evidence_bundle()` [gen3_authority.py:789] | `MODEL_RUN_EVIDENCE_BUNDLE_V1`, atomic, fixed child names, fitted estimator persisted. **Not** content-addressed under `evidence/sha256/<manifest-sha>/`; run JSON at `runs/<id>.json` is the mutable scientific record (Gate 15/16 want V2 + immutable receipt anchor). |
| Estimator reload | `load_fitted_estimator()` [gen3_authority.py:888] | Verifies checksum in `_open_verified_evidence`, then `joblib.load(path)` **re-reads file** → TOCTOU (Gate 18 wants read-once → verify bytes → deserialize from memory). |
| Activation | `activate_candidate` / `get_active_candidate` / `_verify_run_chain` [gen3_authority.py:1200-1256] | Full parent-chain re-verification present and strong. |
| Model request authority | `issue_run_authority` [gen3_authority.py:672] | Request is **self-attested inside** the authority; no separate server-issued immutable request receipt (Gate 20). |
| Hyperparameter validation | `_validate_hyperparameters` [gen3_authority.py:603] | Bounds-checked, but not family-specific strict Pydantic; router DTOs `RunAuthorityRequest`/`AblationRequest` [router.py:226-251] use `extra="forbid"` + `StrictInt` but pass `hyperparameters: dict[str,Any]` through unchecked (Gate 21). |
| Code/env identity | `_code_identity` / `_env_sha` [gen3_authority.py:115-131] | Binds HEAD + `git diff HEAD` + `git status --porcelain` (untracked **names**, not content) + lib versions. Gate 22 wants untracked **content**, lockfiles, explicit audit-report/Bronze exclusion, drift check inside the publish critical section (drift check exists [line 999-1009]). |
| Execution lock | `_project_exec_lock` → `_threading.RLock` [gen3_authority.py:80-92] | **In-memory only.** Gate 23 requires an **interprocess** lock. |
| Binding CAS | `create_binding` [gen3_authority.py:477] | `expected_revision` CAS + supersession present. **No same-version no-op** — every call bumps revision (Gate 24). |
| 2025-capable script | `incremental_signal_study.decide_feature_value` [incremental_signal_study.py:477] | Fail-closed for ordinary use **but** grants itself via a **user-settable env var** `ASP_ARCHIVAL_AUDIT_CAPABILITY` (Gate 10/25 forbid). Module also trains a 2025 fold (`train_2025`). |
| Incremental-signal tests | `tests/sports_phase4_incremental_signal_study_test.py` | **5 tests fail** (they call `decide_feature_value` directly: lines 161,172,180,189,200) since the 7D guard makes it raise. Gate 25: update to assert retirement. |
| Ordinary 2025 UI reads | removed in 7C commit `dc95ff6` | Verify no residual internal 2025 metric/target read (Gate 12). |

---

## Blocker-by-blocker disposition (Codex 9 families → gates)

Format: **CODEX FINDING · ROOT CAUSE · TARGET CONTROL · FILES · NEGATIVE TEST · ACCEPTANCE**.

### B1 — Mutable registry fallback (Gate 1, 2)
- **Finding:** `_canonical_registry()` reconstructs an executable catalog from publisher sidecars when the
  registry file is missing; migration is not byte-idempotent and has no interprocess lock/CAS.
- **Root cause:** convenience fallback + non-deterministic migration id/timestamp.
- **Control:** `_canonical_registry()` **fails closed** (missing/malformed/schema-invalid/inconsistent →
  `AuthorityError`); sidecars are *migration input only*, reachable exclusively via the explicit
  `migrate_registry()` admin command guarded by an interprocess lock; migration id is **deterministic** over
  the (before,after) content so an exact rerun is a byte-for-byte no-op.
- **Files:** `server/sports_cockpit/gen3_authority.py`.
- **Negative test:** missing registry → fail closed; malformed registry → fail closed; forged sidecar cannot
  serve as fallback; repeat migration = byte no-op (same file bytes); two concurrent migrations → one wins.
- **Acceptance:** ordinary catalog/binding/population/execution never reads a sidecar; rerun no-op proven.

### B2 — Incomplete / bypassable object verification (Gate 3, 4, 5)
- **Finding:** `research_object_path()` hands out a bare path (descriptive engine bypasses full receipt);
  verification cache returns early before rechecking schema/counts/bundle/features.
- **Root cause:** read boundary is a path, not a verified handle; cache optimized on physical SHA alone.
- **Control:** introduce `VERIFIED_RESEARCH_OBJECT_V1` (path + full receipt: registry identity, receipt SHAs,
  generation, kind, bundle, contracts, rows, per-season, season roles, target-class order, ordered feature
  identities, capability, verification state). All governed consumers use it. **Remove the cross-request
  verification cache** (this trusted-local phase): recompute physical SHA + complete receipt before every
  governed read; never early-return.
- **Files:** `gen3_authority.py`, `engine.py`.
- **Negative test:** same-size/mtime byte substitution; forged schema/bundle/generation/object-kind/season
  counts/feature order/target-class order — **all fail**; outside-root object opens = 0.
- **Acceptance:** every governed consumer receives a verified handle; no bare-path scientific read remains.

### B3 — Target-leaky advanced-feature authority (Gate 6, 7, 8, 9)
- **Finding:** a feature is authorized merely because its column name is in the ordered set; no per-feature
  semantic derivation/knowledge-time/leakage classification; the 7D advanced-feature fixture was
  target-derived.
- **Root cause:** feature-set contract carries names, not semantics; no leakage validator.
- **Control:** `MLB_FEATURE_SEMANTIC_CONTRACT_V1` (per-feature: id/name/dtype/family/source receipts+columns/
  derivation expr+code digest/grain/knowledge-time class/as-of rule/lookback/leakage class/prohibited
  fields/identifier class/target-relationship/SHA); `MLB_FEATURE_FAMILY_CONTRACT_V1`;
  `MLB_FEATURE_SET_CONTRACT_V2` binding the exact final ordered feature ids + family ids + SHAs; a
  **fail-closed leakage validator** run before dataset publication / feature-set registration / run-authority
  / ablation. Safe synthetic fixture = `prior_pa_count` → `log1p_prior_pa_count`
  (`HISTORICAL_AS_OF_CUTOFF`, strictly earlier than target, family `RELIABILITY_SAMPLE_SIZE_TEST`).
- **Files:** `gen3_contracts.py` (+ new `feature_semantics.py`), `gen3_authority.py`, tests.
- **Negative test:** target column / encoded target / target proxy / post-PA / future / ID-derived / missing
  derivation / unknown leakage class **rejected**; safe historical feature **accepted**; target permutation
  does not change the feature; feature-set SHA + effective-config SHA differ; base excludes / advanced
  includes exactly once at the exact position.
- **Acceptance:** direct leakage is structurally impossible; the safe synthetic feature enters canonical
  training and is echoed in run evidence.

### B4 — Invalid feature-family ablation identity (Gate 13, 14)
- **Finding:** ablation does not prove challenger = control-prefix + exactly one declared family; comparison
  is a replaceable JSON.
- **Root cause:** identity computed as a set-difference, not a strict prefix/one-family assertion; evidence
  not content-addressed.
- **Control:** enforce challenger[:len(control)] == control exactly (no removal/reorder/substitution/dup),
  added == one family contract exactly, family non-empty, same binding/target/population/folds/preprocessing/
  model/hyperparameters/seed/code+env/validation-rows; publish comparison as content-addressed immutable
  evidence anchored in the evidence registry.
- **Files:** `gen3_authority.py`.
- **Negative test:** one-feature challenger / empty family / multiple families / reordered control / removed
  base / substituted feature / undeclared column **rejected**; strict control+one-family **accepted**.
- **Acceptance:** 2024-only comparison with paired game-cluster bootstrap; immutable comparison receipt.

### B5 — Mutable / tamperable run and activation records (Gate 15, 16, 17, 18, 19)
- **Finding:** run JSON is the mutable scientific record; estimator reload re-reads the file post-verify.
- **Root cause:** no content-addressed bundle V2 + immutable run receipt anchor; TOCTOU on reload.
- **Control:** `MODEL_RUN_EVIDENCE_BUNDLE_V2` (one content-addressed bundle under `evidence/sha256/<sha>/`);
  immutable run receipt registered in a canonical evidence registry; run-id→receipt-SHA append-only lookup;
  displayed scientific fields reconstructed from the verified bundle; **read-once → verify bytes →
  deserialize from memory** for estimator reload.
- **Files:** `gen3_authority.py`.
- **Negative test:** single-child tamper / manifest tamper / coordinated tamper / run-anchor replacement /
  child traversal / partial publish / retry collision **fail**; logistic + HGB reload; independent
  prediction recompute bit-for-bit.
- **Acceptance:** activation reconstructs the full parent chain from immutable evidence only.

### B6 — Tracked scripts capable of opening/using 2025 (Gate 10, 11, 12)
- **Finding:** `decide_feature_value` self-grants via a user-settable env var and consumes the 2025 fold in a
  selection decision.
- **Root cause:** env-string "capability"; no approved Phase-7B research entry point.
- **Control:** **remove** the env self-grant; hard-retire `decide_feature_value` for ordinary use (raise,
  point to the 2024-only ablation); document a *separate, unavailable* administrative sealed service (not
  implemented here). Add `scripts/phase7b_research.py` (canonical registry + verified handle only; refuses
  sealed/archived/combined/sidecar/2025/2026). Confirm no ordinary internal 2025 metric/target read.
- **Files:** `incremental_signal_study.py`, new `scripts/phase7b_research.py`, tests.
- **Negative test:** ordinary `decide_feature_value` raises before any 2025 open; env var grants nothing;
  approved entry point opens research only; retired path exits before object open; 2025 read count = 0.
- **Acceptance:** no user-settable string authorizes sealed access anywhere.

### B7 — Self-attested requests + incomplete code/env identity (Gate 20, 21, 22)
- **Control:** server-issued immutable request receipt bound into run authority (reconstructed, not trusted);
  family-specific strict Pydantic request schemas (logistic + HGB, `extra=forbid`, strict ints, finite
  ranges, uniform 422); code/env closure binds untracked **content** + lockfiles, explicitly excluding only
  the named audit reports + external Bronze root, with the final drift check inside the publish critical
  section.
- **Files:** `gen3_authority.py`, `server/sports_cockpit/modeling.py`, `router.py`.
- **Negative test:** self-consistent forged authority fields fail; unknown Git/env fail; untracked content
  change detected; strict-schema invalids (NaN/Inf/fractional int/huge seed/unknown field) → 422.

### B8 — Partial request validation + concurrency (Gate 22-lock, 23, 24)
- **Control:** interprocess project+operation lock (bounded Windows lockfile: exclusive create, owner PID,
  timestamp, stale handling, timeout, finally-release); one heavy run and one full ablation per project;
  concurrent second request → 429; binding same-version no-op + CAS + supersession-abort during a run.
- **Files:** `gen3_authority.py` (+ small lock helper).
- **Negative test:** concurrent run/ablation → 429; same-version bind no-op; CAS conflict → one wins;
  binding change mid-run → hard fail (no COMPLETE evidence).

### B9 — Insufficient negative behavioral tests (Gate 25, 26)
- **Control:** update the 5 incremental-signal tests to assert retirement; add hermetic negative matrices
  A–H (registry / object / features / ablation / evidence / activation / authority-drift / seal-scripts).
- **Files:** `tests/…`.
- **Acceptance:** every Codex probe is a committed passing behavioral test; temp roots only; no shared
  `.runtime` mutation; no real sealed open.

---

## Execution plan & honest scope

This is a 31-gate, security-critical hardening pass on a large existing authority platform. To keep every
claim verifiable, gates are landed in coherent, individually-tested tranches against the **real** published
objects, and the terminal verdict is only `PHASE_7D1_READY_FOR_FINAL_CODEX_PHASE7B_GATE` when a gate is
genuinely closed with passing tests; otherwise `PHASE_7D1_BLOCKED` with a precise per-gate disposition. The
report (`docs/PHASE_7D1_FINAL_INTEGRATION_GATE_REPORT.md`) records the exact state of each gate at closeout.

Tranche order (highest fail-closed value first): B1 → B2 → B6/B9(tests) → B8 → B5(18) → B4 → then the
larger authority-surface gates B3, B5(15/16), B7. Live acceptance (Gate 28), regression (Gate 29), report
(Gate 30), commits (Gate 31) follow a stable tracked tree.
</content>
</invoke>
