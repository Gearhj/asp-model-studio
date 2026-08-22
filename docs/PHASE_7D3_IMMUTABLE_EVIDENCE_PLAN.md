# Phase 7D.3 — Immutable Model-Run Evidence, Run Receipt Registry, Activation Reconstruction — PLAN (Gate 0)

**Branch:** `phase7d3-immutable-evidence-closure` · **Starting HEAD:** `254a924` (matches expected).
**Main:** `924db29` (untouched) · **Push:** none.

## Gate 0 preconditions (all satisfied, read-only)

- Tracked worktree clean; no acquisition / governed run / test process active.
- Bronze manifest SHA matches `fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a`.
- Canonical registry resolves; `catalog()` opens **0 objects** (no sealed open during inventory).

## Carry-forward from Phase 7D.2 (not reopened — no regression demonstrated)

Mandatory fail-closed canonical registry + locked migration; `VERIFIED_RESEARCH_OBJECT_V1` + full object
verification per governed read (no cache); semantic feature/family/set contracts + structural leakage
validator + safe synthetic proof; immutable `MODEL_REQUEST_RECEIPT_V1` + request reconstruction; strict
Logistic/HGB schemas; interprocess execution lock; binding no-op/CAS; untracked scientific-content hashing;
formal retirement of legacy 2025 model execution. 120 governed tests green at `254a924`.

## V1 evidence inventory → V2 disposition

Format: **CURRENT V1 ELEMENT · SCIENTIFIC AUTHORITY TODAY · V2 REPLACEMENT · MIGRATION/LINEAGE · NEGATIVE
TEST · ACCEPTANCE**.

1. **Run-attempt record** `runs/<run-id>.json` (`MODEL_EXPERIMENT_RUN_EVIDENCE_V1`).
   - *Authority today:* the run JSON was the scientific record (metrics, model family, feature set, status).
   - *V2:* the run JSON becomes an **operational attempt record only**, carrying pointers
     (`runReceiptSha256`, `bundleManifestSha256`, `status`). Scientific truth is the content-addressed bundle.
   - *Lineage:* V1 bundle + run JSON retained (backward-compatible reload); never trusted for science.
   - *Negative test:* tampering a run-JSON scientific field does not affect activation/evaluation (they read
     the verified bundle). *Acceptance:* every displayed scientific field derives from the V2 bundle.

2. **V1 evidence dir** `evidence/<run-id>/` (fixed children, atomic, tamper-checked, estimator persisted).
   - *V2:* `MODEL_RUN_EVIDENCE_BUNDLE_V2` — ONE content-addressed bundle at
     `evidence-v2/objects/sha256/<manifest-sha>/` with a fixed mandatory 29-child set (authority, request/
     object/binding receipts, all contracts + feature semantic/family/set contracts, effective features,
     preprocessor + fitted estimator artifacts, classes, validation row-ids/target/probabilities, aggregate/
     per-class/confusion/reliability, feature/runtime/code-env evidence, child-sha inventory, manifest).
   - *Negative test:* Gate 13 A/B/C/D (atomic publication, child tamper, manifest/receipt/index/coordinated
     tamper, path/name guards). *Acceptance:* any tamper fails closed; content-address never overwritten.

3. **Run-ID lookup** (previously implicit via `runs/<id>.json`).
   - *V2:* canonical evidence registry `evidence-v2/registry.json` — create-once, interprocess-locked
     `runId → receiptSha`; no scientific field stored. *Negative test:* Gate 18 (idempotent / conflict /
     concurrency / missing / corrupt). *Acceptance:* same run+same receipt idempotent; same run+different
     receipt conflicts.

4. **Model/preprocessor persistence + reload** (`load_fitted_estimator`, `verify_estimator_reload`).
   - *V2:* `load_fitted_estimator_v2` / `verify_estimator_reload_v2` read from the verified V2 bundle
     (read-once → verify bytes → deserialize from memory → class check). *Acceptance:* Logistic + HGB reload
     reproduce persisted probabilities bit-for-bit.

5. **Candidate activation** (`ACTIVE_CANDIDATE_REVIEW_V1`, `_verify_run_chain`).
   - *V2:* `activate_candidate` reconstructs the full immutable parent chain via `verify_model_run_receipt`
     and writes `ACTIVE_CANDIDATE_REVIEW_V2` (immutable references only). `get_active_candidate` re-verifies
     on every read; a changed binding → STALE (no active candidate). *Negative test:* Gate 14 status matrix.
   - *Acceptance:* only a COMPLETE, receipt+bundle-verified, current-binding run activates; fabricated/
     tampered/stale/cross-project rejected.

6. **Evaluation / Calibration evidence load** (`active_candidate_evaluation` on V1 diagnostics + run JSON).
   - *V2:* consume the verified V2 bundle only (metrics/per-class/confusion/reliability) + independent
     recompute from persisted predictions/target. *Acceptance:* stored == recomputed; no mutable run JSON.

7. **Run-authority / request / object / binding receipts** — already immutable (7D.1/7D.2); in V2 they are
   bundle children + manifest identities, cross-checked by `verify_model_run_receipt`.

## Missing delta THIS PHASE closes (only this)

Content-addressing the COMPLETE run as one scientific object; a create-once immutable run receipt; a canonical
evidence-registry anchor; removing mutable run JSON as scientific source of truth; activation + downstream
resolving only through the immutable receipt; the V2 tamper + activation-status + registry-concurrency
matrices; a current-HEAD A2 Logistic reproduction and a bounded HGB proof through the V2 path; live acceptance.

Terminal verdict is READY only if every item above is genuinely closed with passing tests + the real A2
reproduction; otherwise `PHASE_7D3_BLOCKED`.
</content>
