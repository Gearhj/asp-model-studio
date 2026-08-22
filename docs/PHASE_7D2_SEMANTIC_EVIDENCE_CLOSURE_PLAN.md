# Phase 7D.2 — Semantic Feature Authority, Immutable Evidence Closure & Final 2025 Retirement — PLAN (Gate 0)

**Branch:** `phase7d2-semantic-evidence-closure` · **Starting HEAD:** `4c5c4ca` (matches expected).
**Main:** `924db29` (untouched) · **Push:** none.

## Gate 0 preconditions (all satisfied, read-only)

- Tracked worktree clean; only preserved audit reports are (committed) — no stray untracked.
- No acquisition / model / test process running.
- Bronze manifest SHA matches `fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a`.
- Canonical registry resolves normally; `catalog()` opens **0 objects** (no sealed open during inventory).

## Carry-forward from Phase 7D.1 (do not reopen)

Fail-closed canonical registry + locked deterministic migration; `VERIFIED_RESEARCH_OBJECT_V1` + complete
verification on every governed read (no cache); strict control-plus-one-family ablation; TOCTOU-safe estimator
reload + recompute; strict logistic/HGB schemas; interprocess execution lock; binding no-op + CAS; retired
2025-based E1/E2 decision; Phase 7B research entry point. 90/90 governed tests green at `4c5c4ca`.

## Remaining-blocker inventory → disposition

Format: **REMAINING GATE · CURRENT IMPL · ROOT CAUSE · TARGET CONTROL · FILES · NEGATIVE TESTS · ACCEPTANCE**.

### Gate 1/2/3 — semantic feature authority + families/sets + leakage validator — **CLOSED this session**
- **Current impl (pre-7D.2):** feature-set contract was V1 (ordered names + count only); a feature was
  "authorized" merely because its name was in the ordered list. No per-feature semantics, no leakage validator.
- **Root cause:** the feature-set carried names, not declared derivation / knowledge-time / leakage semantics.
- **Control:** `MLB_FEATURE_SEMANTIC_CONTRACT_V1` (per-feature derivation/lineage/knowledge-time/as-of/leakage),
  `MLB_FEATURE_FAMILY_CONTRACT_V1`, `MLB_FEATURE_SET_CONTRACT_V2`; a fail-closed **structural** leakage
  validator (declared lineage/derivation/as-of; never statistical). Bound the semantic feature-set identity
  into the run authority + evidence, reconstructed + forgery-checked in `_validate_authority`.
- **Files:** `server/sports_modeling/feature_semantics.py` (new); `server/sports_cockpit/gen3_authority.py`.
- **Negative tests:** `tests/sports_modeling_feature_semantics_test.py` — 17-case rejection matrix + all-22
  valid + families + set V2 + safe-synthetic proof.
- **Acceptance:** target/proxy/post-PA/future/ID/missing-lineage rejected; safe historical feature accepted.

### Gate 4 — safe synthetic advanced-feature proof — **CLOSED this session**
- **Control:** `prior_pa_count → log1p_prior_pa_count`, family `RELIABILITY_SAMPLE_SIZE_TEST`, knowledge-time
  `HISTORICAL_AS_OF_CUTOFF`; proven target-permutation & future-event invariant; enters an advanced feature set
  exactly once at the exact ordered position; feature-set + preprocessor fingerprints change.

### Gate 5 — immutable validated model-request receipt — **CLOSED this session**
- **Current impl:** the request (family/hyper/seed/feature-set) was self-attested inside the run authority
  (though already reconstructed field-by-field at validate).
- **Control:** `MODEL_REQUEST_RECEIPT_V1` — server-issued, content-addressed, create-once; bound into the
  authority; reconstructed from the current binding/contracts/feature-set/semantic identity/request/code+env
  in `_validate_authority`. The client cannot supply the authoritative receipt sha.
- **Files:** `gen3_authority.py`. **Negative tests:** matrix D (receipt/family/seed/feature-set/hyperparameter
  forgery rejected). **Acceptance:** a forged self-consistent authority field does not reconstruct.

### Gate 11 — code/environment content closure — **CLOSED this session**
- **Current impl:** `_code_identity` bound the tracked diff + untracked NAMES (not content).
- **Control:** bind untracked **content** (via `ls-files --others --exclude-standard`), excluding only the named
  audit Markdown reports; `.runtime` + external Bronze root are git-ignored so never listed.
- **Files:** `gen3_authority.py`. **Negative tests:** matrix E (untracked-content change detected; audit report
  excluded; unknown Git/env rejected). **Acceptance:** an untracked scientific/config change trips the drift guard.

### Gate 12 — formal retirement of the legacy 2025 modeling path — **CLOSED this session**
- **Current impl:** `champion_baseline` / `run_experiment` / `run_ablation` / `run_autopilot` /
  `_fit_and_evaluate` fit/scored a frozen 2025 fold; `CHAMPION_REFERENCE_FALLBACK` carried a 2025 constant.
  No route reached them, but direct-import tests did, and three pre-existing champion tests failed on the
  seal-emptied 2025 fold.
- **Control:** those functions raise `LegacyModelingRetiredError` (a `CockpitError`) before any data open,
  pointing to the canonical gen3 path; `fit_cockpit_model` is retained (2023-only simulator fit); the 2025
  constant removed; the simulator uses the governed champion C constant directly.
- **Files:** `modeling.py`, `engine.py`, `simulation.py`, `tests/sports_cockpit_test.py`, `phase6b/6f/6g/6h`.
- **Negative tests:** matrix F (all legacy execs retired before open; champion reference 2024-only; canonical
  research path 2024-only). **Acceptance:** no ordinary 2025 target/metric read; champion unchanged.

### Gate 6/7/8/9/10 — immutable run-evidence bundle V2 + run receipt + evidence registry + activation reconstruction — **REMAINING**
- **Current impl (from 7D.1):** `MODEL_RUN_EVIDENCE_BUNDLE_V1` is atomic, fixed-child-named, tamper-checked,
  persists the fitted estimator (logistic coeffs + HGB joblib); reload is TOCTOU-safe with bit-for-bit
  recompute (Gate 9 substantially met); activation re-verifies the full parent chain
  (`_verify_run_chain` → `_validate_authority` → verified object + evidence). The run JSON at `runs/<id>.json`
  is still the record and the bundle is at `evidence/<id>/`, NOT content-addressed under
  `evidence/sha256/<manifest-sha>/`; there is no separate immutable run receipt in a canonical evidence
  registry, and activation does not yet route reconstruction *through* an immutable run receipt.
- **Root cause:** 7D.1 delivered atomicity + tamper containment + chain re-verification but not the V2
  content-addressed bundle + run-receipt/evidence-registry indirection.
- **Target control:** `MODEL_RUN_EVIDENCE_BUNDLE_V2` (one content-addressed bundle with all Gate-6 children),
  `MODEL_RUN_RECEIPT_V1` registered transactionally in a canonical evidence registry with an append-only
  run-id→receipt-sha lookup, and activation that reconstructs run→receipt→bundle→authority→request-receipt→
  object→binding→registry.
- **Acceptance:** coordinated bundle+manifest+lookup tamper rejected; displayed scientific fields
  reconstructed from the verified bundle only.

### Gate 13 — complete Codex negative matrices — **PARTIAL**
- **Closed:** matrix A (feature leakage), D (request/authority forgery), E (drift), F (sealed legacy); much of
  B/C already covered by the 7D.1 gen3-authority + phase7d1-integration suites.
- **Remaining:** the V2-evidence tamper matrix (B) and the full activation-status matrix (C) as dedicated
  7D.2 tests (blocked on Gate 6/7/8/10).

### Gate 14 — live/API acceptance — **NOT performed** (backend restart + live checks).

## Execution plan & honest scope

Tranches, each individually tested against the real objects on a stable tree: (1) semantic authority (1-4) +
binding; (2) code/env closure (11); (3) legacy retirement (12); (4) request receipt (5). The large evidence-V2
core (6/7/8/10) is an interconnected rework of the execute/activation record and is documented as the remaining
centerpiece rather than rushed late in the budget. Terminal verdict is READY only if every A-K item is
genuinely closed; otherwise `PHASE_7D2_BLOCKED` with a precise per-gate disposition.
</content>
