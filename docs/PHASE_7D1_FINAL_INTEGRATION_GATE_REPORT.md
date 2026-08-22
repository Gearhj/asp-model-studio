# Phase 7D.1 — Final Advanced-Data Integration Gate — REPORT

**Branch:** `phase7d1-final-integration-gate` · **Starting HEAD:** `962a40b` · **Ending HEAD:** `23552e0`
**Main:** `924db29` (untouched) · **Push status:** none · **History rewrite:** none.

## Terminal verdict

**PHASE_7D1_BLOCKED.**

This session closed a large, coherent, **fully-tested** tranche of the fail-closed integration controls
(canonical-registry authority, verified object access, strict ablation identity, immutable/TOCTOU-safe
estimator reload, interprocess execution bounds, binding CAS, strict request schemas, 2025-script retirement,
the Phase 7B research entry point, and the incremental-signal test repair) — **90/90 governed tests green on
the stable committed tree**. It does **not** yet close the remaining *architectural* blockers required for a
Codex-clean Phase 7B gate: the per-feature **semantic feature contracts + leakage validator + safe synthetic
propagation** (Gates 6–9), the **V2 content-addressed run-evidence bundle + immutable run receipt + evidence
registry + request receipt** (Gates 15/16/20 and the registry-anchor half of 14), the **untracked-content /
lockfile code-environment closure** (Gate 22), the **full A–H negative matrices** (Gate 26), and **live +
frontend acceptance** (Gates 27/28). Those remain and are enumerated precisely below so the next session (or
Codex) has an exact map. No claim of readiness is made while they are open.

## What is closed and proven this session (tested)

New hermetic suite `tests/sports_cockpit_phase7d1_integration_test.py` (43 fast + 3 heavy = 46) plus the
repaired `tests/sports_phase4_incremental_signal_study_test.py` (21), all green; the pre-existing gen-3
authority / sealed-access / acl / flow / acquisition suites remain green (re-run: **90 passed** in the final
batch). Every governed test was run on a **stable, non-mutating tracked tree** — I confirmed mid-run editing
correctly trips the Gate-22 code/environment drift guard (a feature, not a defect).

| Gate | Control | Status | Evidence |
|---|---|---|---|
| 0 | Read-only blocker inventory + plan | ✅ | `docs/PHASE_7D1_FINAL_INTEGRATION_GATE_PLAN.md` |
| 1 | Canonical registry is the sole resolver; fail closed; no sidecar fallback | ✅ | 6 negative tests (missing/malformed/schema/dup-id/dup-address/sealed-selectable) |
| 2 | Deterministic, byte-idempotent, interprocess-locked migration + append-only audit | ✅ | 3 tests (idempotent no-op, no volatile fields, concurrent agree) |
| 3 | `VERIFIED_RESEARCH_OBJECT_V1` handle; `research_object_path` retired; engine reads verified object | ✅ | 2 tests + engine wired |
| 4 | Complete object verification before any read; outside-root opens = 0 | ✅ (strengthened) | `_verify_object` (7C/7D) now always-run + reached via the handle; sealed-access opens=0 |
| 5 | Verification cache retired; full receipt recomputed every read | ✅ | 1 test (cache empty after read) |
| 10 | `decide_feature_value` retired; env self-grant removed | ✅ | incremental-signal tests |
| 11 | Phase 7B approved research entry point (research-only) | ✅ | 2 tests + live CLI |
| 12 | Hidden ordinary champion-2025 metric read removed | ⚠️ partial | dead `final2025` read removed; see REMAINING |
| 13 | Strict control-plus-one-family ablation identity | ✅ | accept + 7 rejections |
| 18 | TOCTOU-safe estimator reload + independent recompute | ✅ | 3 tests (class, byte-substitution, bit-for-bit) |
| 21 | Strict family-specific request schemas (uniform 422) | ✅ | logistic + HGB rejection matrix; idempotent re-validation |
| 23 | Interprocess, same-thread-reentrant execution/ablation lock | ✅ | 2 tests (held→BUSY, reentrancy, cross-thread exclusion) |
| 24 | Binding same-version no-op; new revision needs reason/CAS | ✅ | 3 tests |
| 25 | Incremental-signal decision tests updated to assert retirement | ✅ | 21/21 |
| 17 | Evidence path/tamper containment (fixed child names, contained) | ✅ (pre-existing) | `_open_verified_evidence` |
| 19 | Activation reconstructs + re-verifies the full parent chain | ✅ (pre-existing) | `_verify_run_chain` / `get_active_candidate` |

## Codex blocker-by-blocker disposition

1. **Target-leaky advanced-feature authority (6/7/8/9)** — **REMAINING.** The structural half is done: Gate 13
   enforces exact control-prefix-plus-one-contiguous-family identity, and every predictor must be a
   *registered* feature-set (the client never submits raw columns). Not done: `MLB_FEATURE_SEMANTIC_CONTRACT_V1`
   (per-feature derivation / knowledge-time class / as-of rule / leakage class / source receipts),
   `MLB_FEATURE_FAMILY_CONTRACT_V1`, `MLB_FEATURE_SET_CONTRACT_V2`, the fail-closed **leakage validator**, and
   the **safe synthetic `prior_pa_count → log1p_prior_pa_count`** propagation battery. The feature-set contract
   is still V1 (ordered names + count).
2. **Mutable registry fallback (1)** — **CLOSED + tested.**
3. **Registry migration (2)** — **CLOSED + tested** (deterministic id, byte-idempotent no-op, interprocess lock).
4. **Incomplete/bypassable object verification (3/4/5)** — **CLOSED.** All governed consumers use the verified
   handle; the descriptive engine no longer reads a bare path; the warm cache is gone so the full receipt runs
   every time.
5. **Invalid feature-family ablation identity (13/14)** — **CLOSED (structural) + tested.** The 2024-only paired
   comparison (with paired game-cluster bootstrap) is held under one ablation lock and written as immutable
   content-addressed evidence (`ablations/sha256/<sha>.json`, no overwrite). Not done: anchoring the comparison
   in a canonical **evidence registry** (with Gate 15/16) and a formal family-contract membership proof.
6. **Mutable/tamperable run + activation records (15/16/17/18/19)** — **PARTIAL.** Done: TOCTOU-safe estimator
   reload + independent recompute (18); evidence tamper containment (17, pre-existing); activation chain
   re-verification (19, pre-existing). **REMAINING:** `MODEL_RUN_EVIDENCE_BUNDLE_V2` as one content-addressed
   bundle under `evidence/sha256/<manifest-sha>/`; an **immutable run receipt** registered transactionally in a
   canonical evidence registry with an append-only run-id→receipt-sha lookup; reconstruct all displayed
   scientific fields from the verified bundle rather than the mutable run JSON.
7. **Self-attested requests + incomplete code/env identity (20/21/22)** — **PARTIAL.** Done: strict
   family-specific request schemas (21). Strong pre-existing authority **reconstruction** already rejects
   fields that merely self-hash (17-style), and the drift check runs inside the publish critical section.
   **REMAINING:** a separate server-issued **immutable request receipt** bound into the authority (20); binding
   **untracked scientific/config/lock-file CONTENT** + Node/Python lockfiles into the code/environment identity,
   explicitly excluding only the named audit reports + the external Bronze root (22).
8. **Partial request validation + concurrency (21/23/24)** — **CLOSED + tested.** Interprocess heavy-work lock
   (23); binding same-version no-op + CAS + supersession (24); strict schemas → uniform 422 (21).
9. **Insufficient negative tests (25/26)** — **PARTIAL.** Done: the 5 incremental-signal decision tests repaired
   to assert retirement (25); new matrices for registry (A), verified handle + cache, strict ablation identity
   (D), estimator reload (E-subset), interprocess lock + binding CAS (G/H-subset), strict schemas, and the
   research entry point. **REMAINING:** the full object-tamper matrix (B) beyond what `_verify_object` +
   sealed-access already prove, the evidence coordinated-tamper matrix (E) beyond reload, the activation-forgery
   matrix (F), and the authority-drift matrix (G) as *dedicated* 7D.1 tests (several are already exercised by
   the pre-existing gen-3 authority suite).
10. **2025-capable scripts (10/11/12)** — **MOSTLY CLOSED.** `decide_feature_value` hard-retired with the env
    self-grant removed (10); Phase 7B research entry point added (11); the hidden ordinary `final2025` read
    removed (12). **REMAINING (12):** the legacy `server/sports_cockpit/modeling.py` `champion_baseline` /
    `evaluate_and_compare` machinery still *computes* a `frozen2025` fold and `CHAMPION_REFERENCE_FALLBACK`
    still carries a hardcoded 2025 metric constant. This path is **already defanged by the 7C physical seal**
    (the ordinary `load_frame()` is 2023-2024 only, so the 2025 fold is empty and the legacy `sports_cockpit_test`
    champion/tournament tests fail on 0 samples — a pre-existing condition, not introduced here), but the code
    should be formally retired/research-restricted for a clean Gate 12.
11. **Incremental-signal tests (25)** — **CLOSED + tested.**
12. **Negative test matrices (26)** — **PARTIAL** (see 9).

## Final handoff

**STARTING HEAD** `962a40b` · **ENDING HEAD** `23552e0` · **BRANCH** `phase7d1-final-integration-gate` ·
**WORKTREE** clean (tracked) · **PUSH** none · **MAIN** unmodified.
**COMMITS (6):** `ff24e5d` fail-closed registry/verified access · `a6fc135` retire sealed-2025 incremental
decision · `278991f` integration negative matrices · `1fc1c25` Gate 0 plan · `1e161f4` strict schemas +
champion-2025 read removal · `23552e0` Phase 7B research entry point + tests.

**BRONZE** — staging root `C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1` · manifest SHA
`fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a` (verified match) · **Bronze modified = no.**

**REGISTRY** — missing → fail closed = yes · sidecar fallback = none · migration idempotent = yes
(byte-for-byte no-op) · concurrent migration = single agreed end-state · sole resolver = yes.

**VERIFIED OBJECT** — bare-path governed consumers = 0 (engine uses the verified handle) · outside-root opens =
0 · publication manifest verified = yes · physical/logical/schema verified = yes · target class order verified =
yes · ordered features verified = yes · warm-cache substitution = cache retired (recomputed every read).

**FEATURE AUTHORITY** — semantic contract = **NOT YET** · knowledge-time (dataset-level) = yes (V2) ·
per-feature derivation identity = **NOT YET** · source receipts (per feature) = **NOT YET** · leakage validator
= **NOT YET** · safe synthetic feature = **NOT YET** · feature set bound to run = yes (feature-set SHA in
authority/evidence).

**SCRIPTS / 2025** — Phase 7B-approved entry point = `scripts/phase7b_research.py` · self-grant capability
removed = yes · sealed opens (ordinary) = 0 · 2025 target/metric ordinary reads = removed from the objective;
legacy modeling.py frozen2025 machinery remains (seal-defanged) = **REMAINING**.

**ABLATION** — strict control+one family = yes · removal/reorder/substitution/empty/one-feature rejected = yes ·
control + challenger run receipts = yes · 2024 only = yes · paired game-cluster bootstrap = yes · immutable
content-addressed comparison = yes · evidence-registry anchor = **REMAINING** · 2025 usage = none.

**RUN EVIDENCE** — bundle V1 atomic + fixed child names + fitted estimator = yes · bundle **V2** content-
addressed = **REMAINING** · immutable run receipt / registry anchor = **REMAINING** · logistic + HGB estimator
reload (TOCTOU-safe) = yes · independent prediction recompute (bit-for-bit) = yes.

**ACTIVATION** — COMPLETE required = yes · run + authority + object + evidence re-verified = yes · stale/
cross-project/non-complete rejected = yes · active read re-verifies = yes (pre-existing chain).

**REQUEST / DRIFT** — strict logistic schema = yes · strict HGB schema = yes · self-attested forgery rejected =
yes (reconstruction) · immutable request receipt = **REMAINING** · unknown Git/env rejected = yes · untracked
CONTENT / lockfiles bound = **REMAINING** · final publication drift check = yes (in the publish section).

**RESOURCE / BINDING** — interprocess lock = yes · concurrent run/ablation → 429/BUSY = yes · full ablation
lock = yes · same-version binding no-op = yes · CAS = yes · binding-change abort mid-run = yes (pre-existing).

**TESTS** — new + repaired 7D.1 suites and gen-3 authority/sealed/acl/flow/acquisition = **90 passed** (stable
committed tree). **PY_COMPILE** = pass · **DIFF_CHECK** = clean · **TSC** = run (no frontend changed) ·
**BUILD** = not run (no frontend changed) · **LIVE (Gate 28)** = not performed · **FRONTEND (Gate 27)** = not
performed.

**READINESS** — PHASE 7B SILVER NORMALIZATION READY = **no** (feature-semantic authority + leakage validator +
V2 evidence outstanding) · SCIENTIST TESTING READY = partial (backend paths hardened; no live/browser pass) ·
PRIVATE BETA READY = no.

**Invariants confirmed:** external downloads = 0 · Bronze joins = 0 · advanced real features = 0 · models
promoted = 0 · D3 changed = no · D3 retrained = no · 2021/2022/2023 development preserved = yes · 2024
validation preserved = yes · 2025 fit = no · 2025 score = no · 2025 target/metric exposure = removed from the
ordinary objective (legacy modeling.py path seal-defanged, flagged) · 2026 touched = no · raw data committed =
0 · security weakened = no · pushes = 0 · main modified = no.

## Precise remaining work (for the next session / Codex)

1. **Gates 6–9** — build `MLB_FEATURE_SEMANTIC_CONTRACT_V1` (+ family V1, feature-set V2), a fail-closed
   leakage validator over them, and the `prior_pa_count → log1p_prior_pa_count` safe-synthetic propagation
   battery (target-permutation invariance; base excludes / advanced includes once at the exact index; rejects
   target/post-PA/future/ID-derived/undeclared features).
2. **Gates 14/15/16/20** — `MODEL_RUN_EVIDENCE_BUNDLE_V2` (one content-addressed bundle under
   `evidence/sha256/<sha>/`), an immutable run receipt + canonical evidence registry (append-only
   run-id→receipt-sha), reconstruct displayed fields from the verified bundle, and a server-issued immutable
   request receipt bound into the authority; anchor the ablation comparison in the same registry.
3. **Gate 22** — bind untracked scientific/config/lock-file CONTENT + Node/Python lockfiles into the code/env
   identity, excluding only the named audit reports + the external Bronze root.
4. **Gate 12 (finish)** — formally retire/research-restrict `modeling.py` `champion_baseline` /
   `evaluate_and_compare` frozen2025 machinery and drop the 2025 constant from `CHAMPION_REFERENCE_FALLBACK`;
   update/retire the three stale `sports_cockpit_test` champion/tournament tests accordingly.
5. **Gate 26** — complete the object-tamper (B), coordinated evidence-tamper (E), activation-forgery (F), and
   authority-drift (G) matrices as dedicated 7D.1 behavioral tests.
6. **Gates 27/28** — live safe acceptance (restart backend; health/login/catalog/bind/authorize/execute/
   activate/evaluate/ablation/429/retired-script/rejected-2025) and the minimum frontend authority checks.
</content>
