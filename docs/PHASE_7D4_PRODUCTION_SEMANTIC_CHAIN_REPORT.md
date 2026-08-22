# Phase 7D.4 — Production Semantic Authority & Canonical Parent-Chain Verification — REPORT

**Branch:** `phase7d4-production-semantic-chain-closure` · **Starting HEAD (local):** `fe9fd79` ·
**Ending HEAD:** `5a6db06` (+ this docs commit) · **Main:** `924db29` (untouched) · **Push:** none ·
**Remote:** `origin/phase7d3-immutable-evidence-closure` = `50bc1bb` (never touched).

## Terminal verdict

**PHASE_7D4_BLOCKED.**

The scientific-authority **core** the Codex gate flagged as the true Silver blockers is closed and tested:
the coordinated self-attested forgery is now rejected, the immutable request receipt is mandatory, activation
reconstructs the full canonical parent chain, the publication manifest is mandatory, the final-publication
drift race is closed, the leakage classification is a strict closed enum, non-base feature sets require
complete V2 semantic authority, and every named 2025-capable script exits before any open. The accepted A2
Logistic evidence still reproduces **exactly** (diff 0.0) through the repaired verifier. It is **not** READY:
the full production advanced-feature run through a hermetic publisher (B2/Gate 3/13), the V2-only feature-family
comparison (B6/Gate 10), the backend/frontend DTO alignment (B9/Gate 9), and the true-interprocess (Gate 14),
authenticated-HTTP-scratch-server (Gate 16), and isolated-root full-inventory (Gate 15) test batteries remain.
Those are documented precisely below.

## Blocker disposition (B1–B10)

- **B1 — advanced semantic authority in production** — **PARTIAL (guard closed).** A non-base feature set now
  REQUIRES a complete `MLB_FEATURE_SET_CONTRACT_V2` registration (per-feature semantic contract for every
  advanced feature + the exact base prefix); a bare ordered name-list is refused and every declared advanced
  feature is leakage-validated (`_resolve_feature_set`). **Remaining:** a *registered* real/hermetic advanced
  dataset exercising this path end-to-end is part of B2/Gate 3 (deferred).
- **B2 — safe feature through the real production chain** — **PARTIAL.** The strict closed **leakage enum** is
  in production (SAFE_PREGAME / SAFE_HISTORICAL_AS_OF / SAFE_CONDITIONAL_PRE_PA + the *_PROHIBITED classes;
  unknown/blank/prohibited rejected). **Remaining (Gate 3/13):** publishing a hermetic advanced research
  dataset through the *actual* publisher/registry and running `prior_pa_count → log1p_prior_pa_count` through
  registration → binding → request → run → V2 evidence → activation → evaluation.
- **B3 — immutable model-request receipt is mandatory** — **CLOSED + tested.** `_validate_authority` loads the
  persisted `MODEL_REQUEST_RECEIPT_V1` by sha (no reconstruction-substitute), verifies its content address, and
  requires an exact reconstruction from current authority; the bundle writer no longer substitutes a
  placeholder. A missing receipt fails closed; a coordinated authority rewrite whose receipt file was not also
  forged fails at load.
- **B4 — canonical parent-chain verifier** — **CLOSED + tested (crown jewel).**
  `verify_canonical_model_run_chain` reconstructs every immutable parent from the current canonical authority
  and relationally cross-checks the bundled children; `activate_candidate` / `get_active_candidate` /
  Evaluation route through it. A self-consistent forged bundle+receipt+registry that the narrow receipt verifier
  ACCEPTS is REJECTED by the chain (contract sha disagreement); superseded binding → STALE/rejected.
- **B5 — verified-object publication manifest** — **CLOSED.** The publication manifest is mandatory (no
  fail-open "if exists"); the exact target class order is proven from the target contract + object; the receipt
  carries `targetClassOrder` + `orderedFeatures`. The real Gen-2/Gen-3 objects carry manifests and still verify.
- **B6 — V2-only feature-family comparison** — **REMAINING (Gate 10).** The ablation comparison still resolves
  V1/mutable evidence; migrating both arms through `verify_canonical_model_run_chain` + content-addressing the
  comparison receipt is not yet done.
- **B7 — final drift transaction** — **CLOSED + tested.** A final code/environment recompute runs inside the
  publication critical section (under the exec lock) immediately before COMPLETE; injected late drift →
  `FAILED_STALE_AUTHORITY`, no COMPLETE bundle/receipt/registry entry/activation.
- **B8 — retire 2025-capable scripts** — **CLOSED + tested.** The 7 named scripts call `retire_2025()` as the
  first statement of `main()`, exiting (code 2) before any path resolution/glob/open; subprocess tests prove it.
  **Note:** other tracked `run_mlb_*` scripts (catcher_readiness, dynamic_player_state, game_replay, pa_baseline,
  participation_usage, pitch_sequence_features, process_interactions, severe_miss_forensics) were not all
  guarded this session — a documented residual.
- **B9 — backend/frontend evidence DTOs** — **REMAINING (Gate 9).** Strict versioned Pydantic response models
  (`ACTIVE_CANDIDATE_RESPONSE_V2` / `MODEL_EVALUATION_RESPONSE_V2` / `MODEL_CALIBRATION_RESPONSE_V2` /
  `MODEL_REGISTRY_EVIDENCE_RESPONSE_V2`) + matching TS types + the `cockpitSteps2.tsx` fixes are not yet done.
  (Backend Evaluation now fails closed on a recompute mismatch instead of a boolean, one half of the gate.)
- **B10 — strongest tests** — **PARTIAL.** Committed: coordinated-forgery, leakage-enum, non-base-semantic,
  script-retirement, missing-receipt, final-drift, superseded-binding. **Remaining:** true **interprocess**
  (subprocess) registry/evidence concurrency (Gate 14) and the authenticated-HTTP scratch-server flow (Gate 16).

## Gate 17 — A2 / HGB regression through the repaired verifier

- **A2 Logistic (new run under 7D.4 code):** runId `1399aa0769ad42a39210979e43300860` · dev 2021-2023 /
  **547,835** · val 2024 / **182,449** · stored = independent recompute = governed reference =
  **1.4827332596445002** · **diff 0.0** (accepted ≤1e-6) · reload bit-for-bit · verified through
  `verify_canonical_model_run_chain` · activated `ACTIVE_CANDIDATE_REVIEW_V2` · eval recompute matches.
- **HGB:** bit-for-bit reload through the V2 path (module fixture + accepted 7D.3 evidence).

## Final handoff

**COMMITS (this branch, on top of `fe9fd79`):** `b0bb679` production semantic authority + canonical chain +
mandatory receipt + manifest + final drift · `c07a5fb` retire 2025-capable scripts · `5a6db06` production
semantic / coordinated-forgery / drift / script-retirement tests · (+ this docs commit). **WORKTREE:** clean
(tracked; the preserved Codex report + the plan/report docs untracked by design). **PUSH:** none. **MAIN:**
unmodified. **REMOTE ACTIONS:** 0.

**BRONZE** — manifest SHA `fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a` (verified) ·
modified = no · registered = no · model eligible = no.

**SEMANTIC PRODUCTION AUTHORITY** — non-base features require V2 semantics = yes (guard) · unknown leakage
classes rejected = yes · target proxy / post-event / future / ID-derived rejected = yes (contract validator) ·
publication binds semantic identities = yes (bundle children + authority) · verified object proves feature
order = yes (`orderedFeatures`) · verified object proves class order = yes (`targetClassOrder`).

**MODEL REQUEST** — receipt mandatory = yes · fallback removed = yes · receipt bytes verified = yes · canonical
reconstruction = yes · fully rehashed forgery rejected = yes (missing/mismatched receipt fails closed).

**CANONICAL PARENT CHAIN** — registry / binding / object / contracts / feature set / request / authority /
receipt / bundle / code-environment / activation / active read / Evaluation = reconstructed + cross-checked by
`verify_canonical_model_run_chain`. Calibration/Registry: backend paths use the same chain; DTO/TS alignment
(B9) remains.

**V2 COMPARISON** — REMAINING (still V1/mutable; B6/Gate 10).

**FINAL DRIFT** — publication critical section = yes · final code/env recompute = yes · late-drift test = yes ·
COMPLETE evidence on drift = 0.

**2025 SCRIPT ESTATE** — 7 named scripts hard-retired before open (subprocess-proven, exit 2); self-grant
capability = none; other `run_mlb_*` scripts = residual (documented). `final2025` ordinary parsing = the
champion-reference fallback constant was removed in 7D.2; a legacy metrics-JSON read path may remain in helpers
(to audit under Gate 12 completion).

**TESTS** — Phase 7D.4 suite: **15 passed**. Full governed regression (7D.1/7D.2/7D.3/7D.4 + feature-semantics +
gen3 authority/sealed/acl/flow + incremental): **195 passed, 0 failed** (16m29s) on the committed tree. **TSC** =
pass · **BUILD** = not run (no frontend changed) · **PY_COMPILE** = pass · **DIFF_CHECK** = clean.
**LIVE/HTTP** = authenticated scratch-server flow (Gate 16) not performed; browser E2E = no.

**READINESS** — PHASE 7B SILVER NORMALIZATION READY = no (B2 production advanced path + B6 + B9 remain) · 2024
FEATURE-FAMILY EXPERIMENTS READY = no (B6 V2-only comparison remains) · SCIENTIST TESTING READY = no (B9 DTO
alignment) · PRIVATE BETA READY = no.

**Invariants:** external downloads = 0 · Bronze joins = 0 · real advanced features = 0 · models promoted = 0 ·
D3 changed = no · D3 retrained = no · 2021/2022/2023 development preserved = yes · 2024 validation preserved =
yes · 2025 fit = no · 2025 score = no · 2025 payload exposure = no · 2026 touched = no · raw data committed = 0 ·
security weakened = no · remote actions = 0 · pushes = 0 · main modified = no.

## Remaining work for the next session / re-audit

1. **B2/Gate 3/13** — publish a hermetic advanced research dataset through the actual publisher with an
   `MLB_FEATURE_SET_CONTRACT_V2` registration, and run `log1p_prior_pa_count` through the full production chain +
   the production-path leaky-variant rejections.
2. **B6/Gate 10** — migrate feature-family comparison to resolve both arms through
   `verify_canonical_model_run_chain` and content-address the comparison receipt (V1/mutable evidence retired).
3. **B9/Gate 9** — strict versioned Pydantic evaluation/candidate/calibration/registry response models + matching
   TS types + `cockpitSteps2.tsx` fixes + a frontend contract test.
4. **Gate 14 / Gate 16** — true interprocess (subprocess) concurrency tests and an authenticated-HTTP flow on a
   fresh scratch loopback server.
5. **Gate 12 (finish)** — guard the remaining `run_mlb_*` scripts and remove any residual archival `final2025`
   parsing from ordinary helpers.
6. **Gate 15** — retrofit the governed suites to isolated temporary registry/object/state/evidence roots.
</content>
