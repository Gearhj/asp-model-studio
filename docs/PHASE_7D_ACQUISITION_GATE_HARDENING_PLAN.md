# Phase 7D — Phase 7B Acquisition-Gate Hardening — PLAN (Gate 0)

**Branch:** `phase7d-acquisition-gate-hardening` · **Starting HEAD:** `93f1634`
**Worktree at entry:** clean; untracked = 5 preserved audit/Codex reports only.

Purpose: make it safe for ONE trusted local developer to begin Phase 7B (acquire Statcast/Retrosheet/
Chadwick/Lahman, build 2019–2020 prior history, construct advanced point-in-time feature families, register
immutable advanced feature views, run controlled 2024-only feature-family experiments). This is NOT a
scientist-testing / private-beta / production gate.

Preserved accepted evidence (never rebuilt to rename): Gen-2 research `50ce1def` (2023-2024, 366,553) /
sealed `a04852d5` (2025); Gen-3 V2 research `b4bc7a0e` (2021-2024, 730,284) / sealed `4c33b9e5` (2025);
V2 bundle `86a60f6c`; A2 logistic evidence (LL 1.4827332596445002, independently recomputed, diff 0).

## Blocker inventory (from the Phase 7C Codex audit, verified locations)

| Blocker | Current implementation | Target | Files | Test | Acceptance |
|---|---|---|---|---|---|
| **P7C-01** registry not sole resolver | `catalog()` builds from `registration.json` sidecars; `_resolve_version` loops that; `ASP_REGISTRY` written, never read; engine trusts Gen-2 sidecar (existence-only). External registry has 9 stale selectable entries (combined `74b9c24`, V1 `05c91a`, intermediate `13bf9d`). | ONE canonical immutable registry is the sole catalog+execution resolver; atomic migration archives all legacy/V1/intermediate/combined as nonselectable; sidecars are publisher inputs only; catalog opens 0 objects. | `gen3_authority.py`, `engine.py` | registry sole-resolver + archived-entries + zero-open test | 4 selectable/restricted entries; sidecars cannot drive execution |
| **P7C-02** 2025 not system-wide sealed | `/cockpit/objective` returns `frozen2025`; Evaluation appends 2025 Phase-4 severe-miss; **`incremental_signal_study.py:477-520` uses 2025 in E1/E2 decision (leakage)**; 14 tracked scripts open combined/full + 2025; `glob()[0]` first-match. | Central research-only capability; ordinary routes/scripts research-only; remove 2025 from objective/Evaluation DTOs; the E1/E2 study refuses 2025 under ordinary capability; scripts fail-closed or archival. | `engine.py`, `router.py`, `incremental_signal_study.py`, MLB scripts, `cockpitSteps1/2.tsx`, `Phase4Surfaces.tsx` | research-only capability + script-containment + no-2025-DTO test | 0 ordinary sealed/combined opens; 0 2025 payload |
| **P7C-03** features/controls outside authority | Global 22-feature `FEATURE_NAMES` for both generations; Steps 03-08 save to browser, no `projectId`; notes gate Objective. | Generation-specific ordered feature-set contract resolved per dataset version; server experiment draft; Objective/Target derive from binding. | `gen3_contracts.py`, `gen3_authority.py`, `router.py`, `cockpitSteps1.tsx` | feature-authority + draft + advanced-feature-propagation | feature-set SHA in authority; client arbitrary feature rejected |
| **P7C-04** verifier fail-open | `_verify_object` opens outside-root sidecar path before rejecting; forged embedded IDs accepted 5/5; no manifest auth; gen/kind not in identity; cache same-size/mtime substitution accepted. | Resolve+contain under fixed root before open; reject reparse ancestors; verify embedded identities + publication manifest; bind gen/objectKind into canonical identity; recompute physical SHA (drop weak cache). | `gen3_authority.py`, `gen3_publish.py` | verifier tamper/containment/cache matrix | outside-root rejected before open; all tamper classes fail closed |
| **P7C-05** evidence/activation mutable | `mkdir(exist_ok=True)`+unconditional writes; downstream never anchors manifest to `run.evidenceBundleSha256`; manifest filenames uncontained; activation checks only `bindingId`; fabricated runs activated 3/3; HGB persists no estimator. | Atomic content-addressed bundle; run receipt anchors manifest SHA; contained child ids; activation verifies status/binding/authority/receipt/all children/fingerprints; persist fitted HGB estimator. | `gen3_authority.py` | evidence-tamper + activation-forgery + estimator-load matrix | fabricated/tampered/noncomplete rejected; HGB estimator loads |
| **P7C-06** authority self-attesting + code/env fail-open | `_validate_authority` accepts forged binding-revision/dataset/generation/bundle/contract/fold after hash recompute; `_code_identity` hashes untracked NAMES not contents; `UNKNOWN` accepted. | Reconstruct authority from binding+registry, compare every field; fail-closed on UNKNOWN; hash relevant untracked/config/lockfile contents; final drift check immediately before atomic COMPLETE. | `gen3_authority.py` | authority-forgery + UNKNOWN-env + drift matrix | material forgery + UNKNOWN rejected |
| **P7C-07** binding transitions lie | Same-version bind always new revision; no CAS; concurrent binds → two ACTIVE; panels reload on projectId not revision; lastResult/lastSim persist. | Same-version idempotent no-op; CAS; concurrent → one success; revision-driven refresh; demote browser authority. | `gen3_authority.py`, `Gen3CatalogSection.tsx`, `cockpitSteps1/2.tsx` | CAS + idempotency + concurrent-bind test | one success; same-version no-op |
| **P7C-08** resources partial (P2) | raw dict requests; two suites concurrent. | Trusted-local: serial/bounded per project + strict schemas on canonical paths (multi-user scheduler = documented debt). | `gen3_authority.py`, `router.py` | bounded-serial + strict-schema test | 2nd concurrent → 409/429 |
| **P7C-09** tests insufficient | service-method calls on shared `.runtime`; source-string frontend tests. | Isolated temp registry/objects/state; behavioral tamper/HTTP/resolver/metrics tests. | `tests/*` | the Gate-24 matrix | isolated behavioral acceptance passes |

## Execution order
1. Registry sole resolver + atomic migration (Gate 1/2) + research-only capability (Gate 3) + object-path containment/verification/cache (Gate 6/7/8).
2. System-wide 2025 removal (Gate 4/5/21): E1/E2 study leakage, tracked-script containment, objective/Evaluation DTOs.
3. Generation-specific feature contracts (Gate 9) + experiment draft (Gate 10) + advanced-feature propagation proof (Gate 11).
4. Canonical 2024-only feature-family ablation (Gate 12).
5. Atomic content-addressed evidence (Gate 13/14) + HGB estimator (Gate 15) + activation verification (Gate 16) + authority reconstruction (Gate 17) + code/env fail-closed (Gate 18).
6. Binding CAS (Gate 19) + browser demotion (Gate 20) + trusted-local bound (Gate 22) + strict schemas (Gate 23).
7. Isolated behavioral tests (Gate 24/25) + regression/live (Gate 26) + report (Gate 27) + commits (Gate 28).

Items that cannot be fully and safely completed within the acquisition budget are marked NOT CONFIGURED /
documented debt (scientist-testing/private-beta blockers), never left as an unsafe path.
