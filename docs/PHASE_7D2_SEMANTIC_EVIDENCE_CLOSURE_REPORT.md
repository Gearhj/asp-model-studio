# Phase 7D.2 — Semantic Feature Authority, Immutable Evidence Closure & Final 2025 Retirement — REPORT

**Branch:** `phase7d2-semantic-evidence-closure` · **Starting HEAD:** `4c5c4ca` · **Ending HEAD:** `4d2621d`
**Main:** `924db29` (untouched) · **Push:** none · **History rewrite:** none.

## Terminal verdict

**PHASE_7D2_BLOCKED.**

This session **closed and tested** the semantic-feature "A/B/C" acquisition blockers (semantic per-feature
contracts, family/feature-set V2, the fail-closed structural leakage validator, and the point-in-time-safe
synthetic-feature proof), the **immutable validated model-request receipt**, the **code/environment content
closure**, and the **formal retirement of the legacy 2025 modeling path** — 120 governed tests green on the
stable committed tree. It does **not** close the interconnected **immutable run-evidence closure** centerpiece
(Gates 6/7/8/10: one content-addressed `MODEL_RUN_EVIDENCE_BUNDLE_V2`, an immutable `MODEL_RUN_RECEIPT_V1` in a
canonical evidence registry, and activation reconstructed *through* that receipt), nor the full V2-evidence
tamper / activation-status negative matrices (Gate 13-B/C) that depend on it, nor live acceptance (Gate 14).
Those remain and are documented precisely below. No READY claim is made while they are open.

## Closed this session (tested)

| Gate | Control | Evidence |
|---|---|---|
| 1 | `MLB_FEATURE_SEMANTIC_CONTRACT_V1` — per-feature derivation/lineage/knowledge-time/as-of/leakage for all 22 base features | `feature_semantics.py`; 28 tests |
| 2 | `MLB_FEATURE_FAMILY_CONTRACT_V1` (3 families) + `MLB_FEATURE_SET_CONTRACT_V2`; semantic identity bound into run authority + evidence, forgery-checked | `feature_semantics.py`, `gen3_authority.py` |
| 3 | Fail-closed **structural** leakage validator (declared lineage/derivation/as-of; never statistical) | matrix A: 17-case rejection |
| 4 | Safe synthetic `prior_pa_count → log1p_prior_pa_count` (`HISTORICAL_AS_OF_CUTOFF`, `RELIABILITY_SAMPLE_SIZE_TEST`) | target-permutation & future-event invariance; exact-position inclusion; fingerprints change |
| 5 | Immutable server-issued `MODEL_REQUEST_RECEIPT_V1` (content-addressed, create-once); reconstructed + forgery-checked in `_validate_authority` | matrix D: receipt/family/seed/feature-set/hyperparameter forgery rejected |
| 9 | Logistic + HGB estimator persistence; TOCTOU-safe reload; bit-for-bit recompute | from 7D.1, re-validated (3 reload tests) |
| 11 | Code/env identity binds untracked **content** + lockfiles, excluding only the named audit reports | matrix E: untracked-content change detected; audit report excluded; unknown Git/env rejected |
| 12 | Legacy `champion_baseline`/`run_experiment`/`run_ablation`/`run_autopilot`/`_fit_and_evaluate` retired before any data open; `fit_cockpit_model` retained (2023-only); 2025 constant removed | matrix F; 3 champion tests + phase6 tests rewritten |

## Codex block-by-block disposition

- **A. semantic feature contracts** — CLOSED (Gate 1).
- **B. leakage validation** — CLOSED (Gate 3).
- **C. safe advanced-feature propagation** — CLOSED (Gate 4).
- **D. one atomic content-addressed `MODEL_RUN_EVIDENCE_BUNDLE_V2`** — **REMAINING.** The 7D.1 V1 bundle is
  atomic, fixed-child-named, tamper-checked, and persists the fitted estimator, but is at `evidence/<run-id>/`,
  not content-addressed at `evidence/sha256/<manifest-sha>/`, and lacks the full Gate-6 child set
  (run-authority, model-request-receipt, verified-object-receipt, binding-receipt, feature/family/set
  contracts as bundle children).
- **E. immutable run receipt + evidence registry anchor** — **REMAINING.** `MODEL_RUN_RECEIPT_V1` +
  transactional canonical evidence registry + append-only run-id→receipt-sha lookup are not yet built; the run
  JSON at `runs/<id>.json` is still the record (though `_verify_run_chain` re-verifies the full parent chain
  including the object + evidence + reconstructed authority + request receipt).
- **F. immutable validated model-request receipt** — CLOSED (Gate 5).
- **G. complete candidate-activation reconstruction** — **PARTIAL.** Activation already re-verifies
  run→authority→object→evidence→binding→registry on every read (7D.1 `_verify_run_chain`); it does not yet
  route *through* an immutable run receipt (blocked on E).
- **H. code/environment closure** — CLOSED (Gate 11).
- **I. legacy 2025 modeling retirement** — CLOSED (Gate 12).
- **J. committed negative matrices** — **PARTIAL.** A/D/E/F committed; B (V2-evidence tamper) and the full C
  (activation-status) matrices are blocked on D/E and remain.
- **K. live/API acceptance** — **NOT performed** (Gate 14).

## Final handoff

**STARTING HEAD** `4c5c4ca` · **ENDING HEAD** `4d2621d` · **BRANCH** `phase7d2-semantic-evidence-closure` ·
**WORKTREE** clean (tracked; plan/report docs untracked by design) · **PUSH** none · **MAIN** unmodified.
**COMMITS (5):** `5b446c0` semantic feature authority · `f2bac44` code-env content closure · `d2e06d4` legacy
frozen-2025 retirement · `4d2621d` immutable model-request receipt · (+ this docs commit).

**BRONZE** — staging root `C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1` · manifest SHA
`fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a` (verified) · **modified = no.**

**FEATURE SEMANTICS** — semantic contract = `MLB_FEATURE_SEMANTIC_CONTRACT_V1` (22 features) · feature families
= 3 (`MLB_FEATURE_FAMILY_CONTRACT_V1`) · feature sets = `MLB_FEATURE_SET_CONTRACT_V2` · knowledge-time classes =
CONDITIONAL_PRE_PA_STATE + HISTORICAL_AS_OF_CUTOFF (7-class taxonomy defined) · source receipts = yes
(partition + bridge authority SHAs) · derivation identities = yes · leakage validator = fail-closed structural ·
safe synthetic feature = yes (`log1p_prior_pa_count`) · target-proxy rejection = yes · future/post-event/ID
rejection = yes.

**MODEL REQUEST** — receipt contract = `MODEL_REQUEST_RECEIPT_V1` · strict Logistic + HGB request = yes (7D.1
schemas) · receipt SHA = server-issued content-addressed · client cannot self-attest = yes (reconstructed at
validate).

**RUN EVIDENCE** — bundle V1 atomic/fixed-children/estimator = yes · **bundle V2 content-addressed = REMAINING**
· run receipt / evidence registry / manifest anchor = **REMAINING** · coordinated tamper rejected = V1 tamper
rejected (7D.1); V2 coordinated matrix REMAINING · Logistic + HGB reload/recompute = yes (bit-for-bit).

**ACTIVATION** — COMPLETE required = yes · bundle/object/authority/request re-verified = yes · fabricated/
non-complete/tampered/stale/cross-project rejected = yes (7D.1) · active read re-verifies = yes · reconstruct
THROUGH an immutable run receipt = **REMAINING** (blocked on evidence registry).

**CODE / ENVIRONMENT** — unknown rejected = yes · untracked scientific content bound = yes · config/lockfiles
bound = yes (untracked by content; tracked via HEAD+diff) · pre-fit / post-fit / final-publication checks = yes
(7D.1 publish critical section).

**LEGACY 2025** — legacy model execution retired = yes (raise before data open) · legacy route status =
`LegacyModelingRetiredError` (CockpitError) · frozen DTO fields removed = yes (no frozen2025 in champion ref/
fallback) · 2025 object opens = 0 · 2025 target reads = 0 · 2025 predictions = 0 · 2025 metrics = 0 · champion
changed = no.

**NEGATIVE MATRICES** — feature leakage (A) = committed · request/authority (D) = committed · drift (E) =
committed · sealed legacy (F) = committed · evidence tamper (B) = REMAINING · activation-status (C) = REMAINING.

**TESTS** — 120 governed tests green on the committed tree (28 feature-semantics + phase7d2 + phase7d1
integration incl. 3 reload + gen3 authority/sealed/acl/flow + rewritten cockpit/phase6). A big-batch run showed
3 transient fixture *errors* (module hgb_run) that do NOT reproduce in isolation or in-file (a code/worktree
drift artifact from concurrent doc writes, not a defect — the prompt's own caveat). **PY_COMPILE** = pass ·
**DIFF_CHECK** = clean · **TSC** = run (no frontend changed) · **BUILD** = not run (no frontend changed) ·
**LIVE (Gate 14)** = not performed.

**READINESS** — PHASE 7B SILVER NORMALIZATION READY = **no** (immutable evidence V2 + run receipt/registry +
activation-through-receipt outstanding) · SCIENTIST TESTING READY = partial (semantic authority + request
receipt + retirement hardened; no live pass) · PRIVATE BETA READY = no.

**Invariants confirmed:** external downloads = 0 · Bronze joins = 0 · advanced REAL features = 0 (the synthetic
feature is a hermetic test fixture, never added to Gen-3) · models promoted = 0 · D3 changed = no · D3 retrained
= no · 2021/2022/2023 development preserved = yes · 2024 validation preserved = yes · 2025 fit = no · 2025 score
= no · 2025 payload exposure = no · 2026 touched = no · raw data committed = 0 · security weakened = no · pushes
= 0 · main modified = no.

## Precise remaining work (for the next session / Codex)

1. **Gates 6/7/8** — `MODEL_RUN_EVIDENCE_BUNDLE_V2`: one content-addressed bundle under
   `evidence/sha256/<manifest-sha>/` carrying the full Gate-6 child set (run-authority, model-request-receipt,
   verified-object-receipt, binding-receipt, feature/family/feature-set contracts, effective features,
   preprocessor + fitted estimator, classes, validation ids/target/probabilities, metrics/confusion/reliability,
   coefficients/importances, convergence, runtime, code-env receipt, child-sha inventory, canonical manifest);
   an immutable `MODEL_RUN_RECEIPT_V1` registered transactionally in a canonical evidence registry with an
   append-only run-id→receipt-sha lookup; fixed child names + traversal/tamper containment.
2. **Gate 10** — activation reconstructs run→receipt→bundle→authority→request-receipt→object→binding→registry,
   and reconstructs all displayed scientific fields from the verified bundle rather than the mutable run JSON.
3. **Gate 13-B/C** — the coordinated V2-evidence tamper matrix (single-child / manifest / run-anchor / run-lookup
   / traversal / missing-child / retry-collision) and the full activation-status matrix.
4. **Gate 14** — live safe acceptance (restart backend; health/login/registry/safe-feature-contract/target-proxy-
   rejection/safe-synthetic-feature-set/request-receipt/bounded-run/activation/independent-recompute/tampered-
   activation-rejected/legacy-410/2025-rejected) + the minimum frontend authority checks.
</content>
