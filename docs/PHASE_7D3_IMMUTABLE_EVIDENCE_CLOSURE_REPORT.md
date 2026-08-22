# Phase 7D.3 — Immutable Model-Run Evidence, Run Receipt Registry, Activation Reconstruction — REPORT

**Branch:** `phase7d3-immutable-evidence-closure` · **Starting HEAD:** `254a924` · **Ending HEAD:** `50bc1bb`
(+ this docs commit) · **Main:** `924db29` (untouched) · **Push:** none · **History rewrite:** none.

## Terminal verdict

**PHASE_7D3_READY_FOR_FINAL_CODEX_PHASE7B_GATE.**

The tight evidence-V2 delta this phase was scoped to close is genuinely, completely closed and independently
reproduced: every completed run is now ONE immutable content-addressed `MODEL_RUN_EVIDENCE_BUNDLE_V2`; each run
has one immutable `MODEL_RUN_RECEIPT_V1`; run id resolves only to a create-once receipt SHA in a canonical
evidence registry; mutable run JSON is no longer scientific authority; Logistic + HGB reload and reproduce
predictions bit-for-bit; activation reconstructs the full immutable parent chain and active-candidate reads
re-verify it; all evidence/activation/registry tamper matrices are committed and green; and the current-HEAD
Gen-3 A2 Logistic run is reproduced **exactly** from the V2 evidence. **180 governed tests pass**; no 2025
access occurs. See the honest **Live acceptance** note below for the one item performed in-process rather than
over authenticated HTTP.

## Phase 7D.2 carry-forward (not reopened)

Canonical registry + locked migration; `VERIFIED_RESEARCH_OBJECT_V1` + full verification per read (no cache);
semantic feature/family/set contracts + structural leakage validator + safe synthetic proof; immutable
`MODEL_REQUEST_RECEIPT_V1`; strict Logistic/HGB schemas; interprocess execution lock; binding no-op/CAS;
untracked scientific-content hashing; legacy 2025 model-execution retirement. All still green in this phase's
regression (180 tests).

## What was built (Gate-by-gate)

- **Gate 1–3 (V2 bundle + manifest + atomic publication):** `MODEL_RUN_EVIDENCE_BUNDLE_V2` — one content-
  addressed bundle at `evidence-v2/objects/sha256/<manifest-sha>/` with a fixed mandatory **29-child** set
  (run-authority, model-request/object/binding receipts, target/population/temporal/preprocessing/
  knowledge-time contracts, feature-semantic/family/set contracts, effective-features, model-metadata,
  classes, validation row-ids/target/probabilities, aggregate/per-class/confusion/reliability, feature/runtime/
  code-env evidence, preprocessor + model artifacts, child-sha-inventory, bundle-manifest). Publication:
  staging → per-child self-verify → canonical manifest → manifest SHA → **atomic `os.replace`**; never
  overwrites, reuses only byte-identical, rejects divergent/extra/missing children; the manifest SHA is the
  content address (never stored inside the manifest).
- **Gate 4 (run receipt):** `MODEL_RUN_RECEIPT_V1`, content-addressed at `evidence-v2/receipts/sha256/<sha>/`,
  SHA over canonical content **excluding only its own `receiptSha256`**.
- **Gate 5/18 (evidence registry):** create-once, interprocess-locked `runId → receiptSha` index (no scientific
  field stored); same run+same receipt idempotent, same run+different receipt conflict, missing/corrupt fail
  closed; 6-thread concurrency test green.
- **Gate 6 (attempt lifecycle):** the run JSON is an operational attempt record carrying only pointers
  (`runReceiptSha256`, `bundleManifestSha256`, `status`); only a COMPLETE run gets a bundle/receipt/registry
  entry/activation eligibility; drift → `FAILED_STALE_AUTHORITY`, no COMPLETE evidence.
- **Gate 7/8 (containment + canonical verifier):** `verify_model_run_receipt` — registry → receipt (SHA re-
  verified) → content-addressed bundle → exact child set → every child SHA → child-name allowlist + parent
  containment + symlink rejection → receipt/manifest cross-check → COMPLETE → no sealed year. Mutable run JSON
  is never trusted.
- **Gate 9 (reload):** `load_fitted_estimator_v2` / `verify_estimator_reload_v2` — read-once → verify bytes →
  deserialize from memory → class check; Logistic + HGB reproduce persisted probabilities **bit-for-bit**.
- **Gate 10 (activation reconstruction):** accepts only project id, run id, optional expected binding revision;
  everything scientific is reconstructed from immutable evidence; writes `ACTIVE_CANDIDATE_REVIEW_V2` (immutable
  refs only).
- **Gate 11 (active-candidate V2):** `get_active_candidate` re-verifies the full chain every read; a changed
  binding → STALE (no active candidate); no mutable metrics returned.
- **Gate 12 (downstream V2):** `active_candidate_evaluation` consumes the verified bundle only (metrics/
  per-class/confusion/reliability) + independent recompute; no mutable run JSON, no browser result, no 2025.
- **Gate 17 (code/env):** the post-fit code/environment drift check + V2 publication run inside one critical
  section on the already-verified identity; the audit reports remain the only non-scientific exclusions.

## Negative matrices (committed, green — `tests/sports_cockpit_phase7d3_test.py`)

- **Atomic publication (13-A):** complete publish; missing child; extra child; destination reuse (idempotent)
  vs divergent conflict.
- **Child tamper (13-B):** model / preprocessor / predictions / target-row-ids / metrics / diagnostics /
  feature-contracts / request-receipt / object-receipt / code-env — all fail closed.
- **Manifest / receipt / index tamper (13-C):** manifest tamper (content-address break); receipt tamper (SHA
  break); registry-index remap to a mismatched receipt (receipt.runId re-check); coordinated child+manifest;
  wrong run id / project / binding in receipt.
- **Path / name (13-D):** child-name allowlist + `_V2_SAFE_NAME` + parent-containment + symlink rejection.
- **Activation status (14):** COMPLETE accepted; fabricated / not-registered (QUEUED/RUNNING/FAILED-equivalent)
  / missing-bundle / tampered-child / stale-revision / cross-project rejected; active read re-verifies.
- **Registry concurrency (18):** idempotent / conflict / 6-thread concurrent / missing / corrupt.

## Gate 15 — current-HEAD A2 Logistic V2 run (independently reproduced)

- runId `2ac3380a14dc49599b5b22d33818f6ac` · receiptSha256 `190e6211589432b8174977b96bc902ced3b5bf572fa918339d2ed1bf12fd5f49`
  · bundleManifestSha256 `05a4b5e5e33e932ec916f8c269624b773020046b7993e7956b3dce3a3304c5b5`.
- developmentRows **547,835** · validationRows **182,449** · preprocessorSha256 `49623488530bba3e…` ·
  modelSha256 `ed736d47d218d5b1…` · predictionSha256 `320868d9ae1b0fbf…`.
- storedLogLoss **1.4827332596445002** · independent recompute from V2 evidence **1.4827332596445002** (brier
  0.70614, ece 0.003113, top1 0.452422, macroF1 0.086408) · governed reference **1.4827332596445002** ·
  **diff = 0.0** (≤ 1e-6 **accepted**) · reload bit-for-bit · activated as `ACTIVE_CANDIDATE_REVIEW_V2`.

## Gate 16 — bounded HGB V2 proof

- runId `83cc6be594294a0ab4886d2d430a1e3f` · HGB reload **bit-for-bit** (maxAbsDiff 0.0) · activated · no 2025
  payload in the evaluation.

## Live acceptance (Gate 19) — honest status

- **Over HTTP (in-process app):** `GET /api/health` = **200**; protected routes correctly enforce auth
  (**401** without a valid session) — the live HTTP layer is up and secure on the new code.
- **Full pipeline (in-process, real Gen-3):** bind → issue → run → `verify_model_run_receipt` → independent
  recompute → activate → `active_candidate_evaluation` succeeds through V2, with the A2 value reproduced
  **exactly**. This is the identical code path the routes wrap.
- **NOT performed this session:** the full **authenticated** HTTP bind→run→activate→evaluate flow and any
  browser E2E. The dev-header auth path requires a genuine loopback client (TestClient's host is not loopback),
  and the running `:8101` backend serves pre-7D.3 code — restarting it was declined to avoid disrupting the
  developer's live session. No browser-E2E claim is made.

## Final handoff

**STARTING HEAD** `254a924` · **ENDING HEAD** `50bc1bb` (+ docs) · **BRANCH** `phase7d3-immutable-evidence-closure`
· **WORKTREE** clean (tracked) · **PUSH** none · **MAIN** unmodified. **COMMITS:** `57226fb` V2 bundle/receipt/
registry/activation · `50bc1bb` V2 tamper/activation/registry matrices · (+ this docs commit).

**BRONZE** — staging root `C:\Users\james\asp-data-staging\mlb-advanced-bronze-v1` · manifest SHA
`fe3d5fb7949861949591a601f5b30c03a5f3eef9c4e80b889995026569b20e4a` (verified) · modified = no.

**V2 BUNDLE** — contract `MODEL_RUN_EVIDENCE_BUNDLE_V2` · mandatory children = 29 (fixed allowlist) · manifest
SHA = sha256 of canonical manifest bytes (content address) · path `evidence-v2/objects/sha256/<sha>/` · atomic
publication = staging + os.replace · conflict handling = reuse-if-identical / reject-divergent / never
overwrite · partial-publication = staging cleaned, no COMPLETE receipt.

**RUN RECEIPT** — contract `MODEL_RUN_RECEIPT_V1` · path `evidence-v2/receipts/sha256/<sha>/receipt.json` · SHA
rule = canonical content excluding `receiptSha256` · create-once = yes · registry `MODEL_RUN_EVIDENCE_REGISTRY_V1`
· run-ID lookup = `runId → receiptSha` · index scientific fields = none.

**EVIDENCE VERIFICATION** — receipt/bundle/child-set/child-SHAs/contracts/request/object/code-env all verified;
tamper matrix = green (13-A/B/C/D).

**ESTIMATORS** — Logistic persisted + reload + probability reproduction = yes (bit-for-bit) · HGB persisted +
reload + probability reproduction = yes (bit-for-bit).

**ACTIVATION** — COMPLETE required = yes · current binding required = yes · receipt/bundle/request/object/
feature-set/code-env required = yes · fabricated/noncomplete/stale/cross-project rejected = yes · active read
re-verifies = yes.

**CURRENT-HEAD A2** — see Gate 15: diff = 0.0, accepted. **HGB PROOF** — see Gate 16: reload bit-for-bit,
accepted.

**CODE/ENVIRONMENT** — issuance/pre-fit/post-fit/final-publication checks = yes · stale-run outcome =
`FAILED_STALE_AUTHORITY`, no COMPLETE evidence.

**2025** — object opens = 0 · target reads = 0 · predictions = 0 · metrics = 0 · payload exposure = 0.

**NEGATIVE MATRICES** — atomic publication / child tamper / manifest-receipt tamper / coordinated tamper / path
traversal / activation statuses / cross-project / binding stale / registry concurrency = all committed + green.

**TESTS** = 180 governed pass · **TSC** = pass · **BUILD** = not run (no frontend changed) · **PY_COMPILE** =
pass · **DIFF_CHECK** = clean · **LIVE STATUS** = health 200 + auth-enforced over HTTP; full pipeline exact in
process; authenticated-HTTP full flow + browser E2E not performed (see Live acceptance).

**READINESS** — PHASE 7B SILVER NORMALIZATION READY = the evidence/receipt/activation authority is complete;
Silver builders + advanced feature registration remain the next phase's work (explicitly out of scope here) ·
SCIENTIST TESTING READY = yes (backend paths hardened + exact A2 reproduction) · PRIVATE BETA READY = pending
the authenticated-HTTP live pass + frontend E2E.

**Invariants confirmed:** external downloads = 0 · Bronze joins = 0 · advanced real features = 0 · models
promoted = 0 · D3 changed = no · D3 retrained = no · 2021/2022/2023 development preserved = yes · 2024 validation
preserved = yes · 2025 fit = no · 2025 score = no · 2025 target/metric exposure = no · 2026 touched = no · raw
data committed = 0 · security weakened = no · pushes = 0 · main modified = no.

## Remaining (non-blocking) debt

- Full **authenticated HTTP** live acceptance (bind→run→activate→evaluate over the real server) + browser E2E of
  Evaluation/Calibration reading the V2 bundle — a thin wrapper over the already-proven pipeline.
- The V1 evidence bundle + run JSON are retained for backward compatibility; a later cleanup can remove them
  once no consumer references them.
</content>
