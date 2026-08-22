# Phase 7D.4 — Production Semantic Authority & Canonical Parent-Chain Verification — PLAN (Gate 0)

**Branch:** `phase7d4-production-semantic-chain-closure` · **Starting HEAD (local):** `fe9fd79`.
**Remote note:** `origin/phase7d3-immutable-evidence-closure` = `50bc1bb` (informational; not touched, not authority).
**Main:** `924db29` (untouched) · **Push:** none.

## Gate 0 preconditions (satisfied, read-only)

Local HEAD `fe9fd79` (matches expected); tracked tree clean (only the preserved
`docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md` untracked — never staged/edited); main `924db29`; no
governed/acquisition process; Bronze manifest SHA matches
`fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a`; registry resolves, `catalog()` opens 0
objects. Codex report read in full.

## Blocker map (B1–B10 → root cause · current files · required change · negative test · success)

### B1 — advanced semantic authority not connected to production (Gate 1/2)
- **Root cause:** `_resolve_feature_set` returns a bare `MLB_FEATURE_SET_CONTRACT_V1` for a non-base registered
  set; `_semantic_feature_identity` returns null for non-base; the V2 bundle writes empty semantic/family/set
  children for non-base; leakage classification is not enum-validated.
- **Files:** `gen3_authority.py` (`_resolve_feature_set` ~832, `_semantic_feature_identity` ~877,
  `_build_v2_content_children` ~1267, `_verify_object` feature check ~611), `feature_semantics.py`.
- **Change:** require `MLB_FEATURE_SEMANTIC_CONTRACT_V1`/`_FAMILY_CONTRACT_V1`/`_SET_CONTRACT_V2` for every
  non-base set (a non-base set with no semantic authority is rejected, not silently V1); strict closed leakage
  enum in the validator. **Test:** unknown leakage class rejected; a non-base set without semantic authority
  rejected. **Success:** no non-base set can bind/request/execute/publish/activate without complete V2 semantics.

### B2 — safe advanced-feature proof stops at a test helper (Gate 3/13)
- **Root cause:** `prior_pa_count`/`log1p_prior_pa_count` is proven only as a unit helper, not through the real
  publisher→registry→verifier→binding→request→run→evidence→activation→evaluation chain.
- **Change:** a hermetic advanced research dataset published through the actual production code with semantic
  contracts, run end-to-end; plus production-path negative tests (target-proxy/post-event/future/ID/unknown-
  leakage/unregistered/reordered rejected). **Success:** the safe feature traverses the full production chain
  and every leaky variant fails closed.

### B3 — immutable request receipt not mandatory / coordinated forgery accepted (Gate 5)
- **Root cause:** `_validate_authority` reconstructs a receipt from the *mutable* authority fields and recomputes
  self-attested hashes instead of loading the persisted immutable `MODEL_REQUEST_RECEIPT_V1` by SHA and
  comparing; the bundle writer substitutes a one-field placeholder when the receipt file is missing.
- **Files:** `gen3_authority.py` (`_validate_authority` ~1000-1029, placeholder ~1264-1266,
  `_model_request_receipt`/issue ~930-945).
- **Change:** load the persisted receipt by `modelRequestReceiptSha256`, verify its bytes/SHA, reconstruct the
  expected receipt from current project/binding/registry/object/contracts/feature-set/strict-request/code-env,
  compare **every** field; remove the placeholder → fail closed. **Test:** a fully-rehashed forged authority
  (seed/family/hyper/feature-set/binding-revision all changed with dependent hashes recomputed) is rejected
  because the immutable issued receipt does not match. **Success:** the receipt is the sole request authority.

### B4 — activation verifies bytes but not the full scientific parent chain (Gate 6/7/8)
- **Root cause:** `verify_model_run_receipt` compares a limited receipt/manifest field set + child hashes;
  `_verify_run_chain` exists but is unused; activation/active reads use the narrow verifier and never reconstruct
  authority/object/contracts/request/code-env from current canonical authority.
- **Change:** one canonical `verify_canonical_model_run_chain(project_id, run_id, expected_binding_revision,
  require_current_binding)` that reconstructs every immutable parent from the canonical registry / current
  binding / current contracts / request receipt / verified object / code-environment and **relationally**
  cross-checks the bundled children (feature-set order == effective-features order; request feature-set SHA ==
  authority feature-set SHA; class order == target contract; dev/val seasons == temporal/population; object
  receipt == canonical registry object; model family/hyper == request receipt; code/env == accepted snapshot).
  Route `activate_candidate`, `get_active_candidate`, evaluation, registry, and V2 comparison through it.
  **Test:** a fully coordinated forged chain (new self-consistent bundle+receipt+registry mapping) rejected
  because it disagrees with the current canonical binding/contracts/request/object/code-env. **Success:** the
  primary acceptance invariant holds.

### B5 — verified-object fail-open metadata cases (Gate 4)
- **Root cause:** publication-manifest verification is conditional on the file existing; exact target-class
  values/order and advanced ordered feature identity are not proven from the object before the handle reports
  hard-coded values.
- **Files:** `gen3_authority.py` `_verify_object` (~583-624).
- **Change:** publication manifest is **mandatory**; target class domain+order and the exact ordered feature
  identity are proven from the object/contract. **Test:** missing manifest → fail closed; forged class order /
  feature order → fail closed. **Success:** no fail-open metadata path.

### B6 — feature-family comparison uses legacy/mutable evidence (Gate 10)
- **Root cause:** `_validation_evidence`/ablation resolve V1/mutable run fields, not V2 receipts+bundles.
- **Change:** `MODEL_FEATURE_FAMILY_COMPARISON_V2` resolves both arms only through the canonical verifier;
  enforce control + exactly one registered family; content-address the comparison receipt. **Success:** V1/
  mutable comparison retired.

### B7 — code/environment drift race before COMPLETE publication (Gate 11)
- **Root cause:** no final equality assertion inside the publication critical section immediately before the
  COMPLETE commit.
- **Change:** recompute code/env inside the publication critical section (under the exec lock), compare to
  issuance/pre-fit/post-fit and every code-env child; publish COMPLETE only if all exactly equal, else
  `FAILED_STALE_AUTHORITY` with no COMPLETE artifacts. **Test:** injected late drift between post-fit and
  publication → no COMPLETE bundle/receipt/registry/activation.

### B8 — tracked 2025-capable scripts (Gate 12)
- **Files:** `scripts/run_mlb_e1_e2_incremental_signal_study.py`, `scripts/phase7_ablation.py`,
  `run_mlb_base_out_transition.py`, `run_mlb_projected_participation_ablation.py`,
  `run_mlb_simulation_input_layer.py`, `run_mlb_starter_identity.py`, `run_mlb_whole_game_monte_carlo.py`, + any
  found in the inventory.
- **Change:** hard-retire (exit before path resolution / glob / parquet open / label / fit / metric) with a
  message naming the canonical replacement; no self-grantable env capability; remove ordinary `final2025`
  parsing. **Test:** subprocess proofs — exit first; research/sealed/archived opens = 0; target reads = 0.

### B9 — backend/frontend evidence DTOs incompatible (Gate 9)
- **Files:** `router.py`, `src/sports/cockpit/cockpitSteps2.tsx` (~450-458, 477-518, 550-575, 655-681).
- **Change:** strict versioned Pydantic `ACTIVE_CANDIDATE_RESPONSE_V2` / `MODEL_EVALUATION_RESPONSE_V2` /
  `MODEL_CALIBRATION_RESPONSE_V2` / `MODEL_REGISTRY_EVIDENCE_RESPONSE_V2` + matching TS types; Evaluation fails
  closed on any recomputed-vs-stored mismatch (not a boolean). **Test:** frontend response/type contract tests.

### B10 — strongest tests missing (Gate 13/14/16)
- **Change:** coordinated semantic-forgery, true **interprocess** (subprocess) registry/evidence concurrency,
  authenticated HTTP on a fresh scratch loopback server, and the production-path safe-feature run — all as
  committed tests. **Success:** each proven, not merely collected.

## Execution plan & honest scope

This closes ten interconnected production-integration blockers — realistically a multi-session effort. This
session prioritizes the **scientific-authority core** Codex flagged as the true Silver blockers, landed with
real coordinated-forgery tests and validated against the real objects:

- **Tranche 1 (this session, tested):** B3 (mandatory immutable request receipt + coordinated-forgery
  rejection), B4 (one canonical parent-chain verifier; activation/active-reads/evaluation route through it),
  B5 (publication manifest mandatory + exact class/feature order), B7 (final-publication drift transaction),
  B2-enum (strict closed leakage enum), B1-guard (reject non-base sets lacking complete V2 semantic authority),
  B8 (retire 2025-capable scripts before open).
- **Deferred (documented precisely):** B2 full production safe-feature run through a hermetic advanced
  publisher (Gate 3/13), B6 V2-only comparison rework (Gate 10), B9 DTO/TS alignment (Gate 9), the interprocess
  + authenticated-HTTP-scratch-server test batteries (Gate 14/16), and the isolated-root full-inventory retrofit
  (Gate 15).

Terminal verdict is `PHASE_7D4_READY_FOR_FINAL_CODEX_SILVER_GATE` only if every B1–B10 item is genuinely
closed with passing tests; otherwise `PHASE_7D4_BLOCKED` with a precise per-blocker disposition.
</content>
