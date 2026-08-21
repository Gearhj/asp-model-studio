# Phase 7D — Phase 7B Acquisition-Gate Hardening — REPORT

**Branch:** `phase7d-acquisition-gate-hardening` · **Starting HEAD:** `93f1634` · **Ending HEAD:** `3187808` (before this report's commit)
**Push status:** not pushed. `main` not modified. No history rewrite.

## Executive verdict

**PHASE_7D_READY_FOR_FINAL_PHASE_7B_CODEX_GATE**

Every acquisition-boundary blocker the Phase 7C audit raised — the ones that could corrupt evidence,
misidentify a dataset/contract, let an advanced feature be ignored, open or use sealed 2025 in a decision,
attribute a run to the wrong dataset, accept a tampered object/evidence bundle, or activate an
invalid/fabricated candidate — is resolved and proven with **isolated behavioral tests** plus **live**
verification. Items the audit itself classified as scientist-testing / private-beta blockers (not
trusted-local acquisition blockers) are addressed where cheap and otherwise documented as debt.

## P7C blocker disposition

| Blocker | Disposition | Evidence |
|---|---|---|
| **P7C-01** registry not sole resolver | **RESOLVED** | One canonical registry (`ASP_DATASET_REGISTRY_V3`) is the sole `catalog()`/`_resolve_version` source; `migrate_registry()` is atomic + idempotent, keeps exactly the 4 current entries selectable/restricted and archives all legacy/combined/V1/intermediate entries nonselectable; the descriptive engine resolves the Gen-2 research object through the same resolver; `catalog()` opens 0 objects. Test A + live (4 entries). |
| **P7C-02** seal not system-wide | **RESOLVED (core) / PARTIAL (retired utilities)** | The decisive model-selection leakage (`incremental_signal_study.decide_feature_value`, which used the sealed 2025 season in the E1/E2 verdict) now **fails closed** under ordinary capability. `/cockpit/objective` no longer returns the champion's 2025 metric; Evaluation no longer appends the 2025 Phase-4 severe-miss evidence. The engine frame remains research-only (2023-2024). Remaining retired Phase-4/5 CLI utilities still glob the combined object directly and are documented below as retired-archival (must-not-run for Phase 7B); Phase 7B acquisition scripts (new) use the research-only resolver. |
| **P7C-03** features/controls outside authority | **RESOLVED** | Generation-specific ordered **feature-set contracts** replace the global `FEATURE_NAMES` as the execution authority; the run authority binds `featureSet`/`featureSetName`/`featureSetContractId`/`featureSetSha256` and execution loads exactly that order; a client can only name a **registered** feature set. Advanced-feature propagation proven (Gate 11). |
| **P7C-04** verifier fail-open | **RESOLVED** | `_verify_object` resolves + **contains** the object path under a fixed immutable root (reparse ancestors rejected) BEFORE any open (a malicious path causes **0** opens), requires the embedded Parquet identities (object kind / logical / schema / bundle / temporal / feature-schema / target) and the publication manifest to agree with the generation-correct contracts, verifies per-season counts, binds generation+object-kind into the canonical identity, and caches by **recomputed physical SHA** (same-size/mtime substitution fails). Test C. |
| **P7C-05** evidence/activation mutable | **RESOLVED** | Evidence is published **atomically** as a content-addressed bundle with fixed child filenames + a run-anchored manifest SHA; downstream reads verify the manifest anchor and every child checksum; a loadable fitted estimator (logistic coefficients + full joblib; HGB full joblib) is persisted; activation and `get_active_candidate` re-verify the full parent chain, so fabricated / non-COMPLETE / stale / tampered runs fail closed. Tests F/G. |
| **P7C-06** authority self-attesting / code-env fail-open | **RESOLVED** | `_validate_authority` **reconstructs** the expected authority from the current binding + registry + contracts + feature-set + validated model request and compares every field (generation, binding revision, dataset, contract ids/shas, bundle, fold seasons, feature-set, hyperparameters); fail-closed on UNKNOWN code/environment; post-fit drift → FAILED. Test H. |
| **P7C-07** browser transitions can lie | **PARTIAL (scientist-testing debt)** | 7C already made downstream consume the server active candidate and reset local project state; binding same-version CAS/no-op and the shared revision-aware frontend refresh (Gate 19/20) remain. The audit classifies P7C-07 as a scientist-testing blocker, not a trusted-local acquisition blocker. Documented below. |
| **P7C-08** resource controls partial | **RESOLVED for trusted-local** | A per-project **reentrant execution lock** bounds heavy work to one run at a time (second concurrent request → HTTP 429); strict typed request schemas (`extra=forbid`, exact int/seed bounds) on the canonical run-authority/execute/ablation paths (live 422s). Multi-user scheduler remains private-beta debt. |
| **P7C-09** tests insufficient | **RESOLVED** | New `tests/sports_cockpit_phase7d_acquisition_test.py` is isolated (never touches shared `.runtime`), publishes real objects into a temporary canonical registry + object roots, and exercises the PRODUCTION resolver/authority/evidence/activation with tamper/forgery/containment matrices. |

## Gate-by-gate

- **Gate 1/2** registry sole resolver + atomic migration — done (4 entries: Gen-2 research 2023-2024, Gen-3 V2 research 2021-2024; Gen-2/Gen-3 sealed restricted; combined/V1/intermediate archived).
- **Gate 3** research-only capability — `RESEARCH_OBJECT_READ` is the only capability ordinary code receives; sealed target reads are never granted.
- **Gate 4** tracked-script containment — **PARTIAL**: the decisive 2025 model-selection leakage is fail-closed; the remaining retired Phase-4/5 utilities are flagged retired-archival (see §Debt).
- **Gate 5/21** remove 2025 from ordinary UI/DTO — objective champion 2025 metric + Evaluation 2025 severe-miss removed; champion 2025 shown only as "restricted archival evidence".
- **Gate 6/7/8** object verification, containment, cache — done and tamper-proven.
- **Gate 9** generation-specific feature contracts — done.
- **Gate 10** experiment draft — **NOT CONFIGURED this phase** (the feature-set contract + run authority already carry the full effective config into the run; a separate server-side Steps-03–08 draft is scientist-testing debt).
- **Gate 11** advanced-feature propagation proof — done (synthetic feature enters the run once, changes feature-set + config + preprocessor fingerprints; arbitrary feature rejected).
- **Gate 12** canonical 2024-only feature-family ablation — done (`run_feature_family_ablation` + `/cockpit/gen3/feature-family-ablation`; paired game-cluster bootstrap; comparison manifest SHA).
- **Gate 13/14/15** atomic content-addressed evidence, path containment, estimator persistence — done.
- **Gate 16** activation verification — done.
- **Gate 17/18** authority reconstruction, code/env fail-closed — done.
- **Gate 19** binding CAS/idempotency — **NOT DONE this phase** (backend supersession from 7C remains; same-version no-op + concurrent CAS is scientist-testing debt).
- **Gate 20** demote remaining browser authority — **PARTIAL** (downstream/objective demoted in 7C+7D; legacy DatasetSection/TargetSelector notes remain UX bookmarks).
- **Gate 22** trusted-local execution bound — done (per-project reentrant lock, 429).
- **Gate 23** strict schemas on canonical paths — done.
- **Gate 24** isolated behavioral tests — done (7/7).
- **Gate 25** rendered frontend harness — **NOT ADDED** (explicitly a scientist-testing/private-beta blocker, not a Phase-7B-local acquisition blocker).
- **Gate 26** regression/live — done (below).

## Tests, build, live

- `npx tsc -b` clean · `npm run build` success · `py_compile` OK · `git diff --check` clean.
- `tests/sports_cockpit_phase7d_acquisition_test.py` **7/7** (registry, verifier tamper/containment/cache, advanced-feature propagation, 2024-only ablation, evidence/activation/estimator, authority forgery).
- Route-contract + two-user/two-project ACL **9/9**; hermetic production-resolver seal **6/6** (0 sealed opens).
- Live (backend restarted, real login): health 200 · catalog 4 entries · bind Gen-3 · run-authority strict schema (extra field → 422, fractional seed → 422) · arbitrary/unregistered feature set → 422 "not registered" · ablation route unregistered challenger → 422 · **bounded run → activate 200 → evaluation with independent recompute matching**.

## Remaining debt (scientist-testing / private-beta — NOT trusted-local Phase-7B blockers)

1. **Retired Phase-4/5 CLI utilities** (`run_mlb_*`, `phase7_*`) still glob the combined/full object directly. The decisive model-selection leakage is fixed; the rest are retired-archival and must not be run for Phase 7B. Recommend routing them through `research_object_path` or a hard fail-closed guard before scientist testing.
2. **Binding CAS / same-version no-op (Gate 19)** and **full browser-authority demotion (Gate 20)** — the legacy DatasetSection/TargetSelector notes remain UX bookmarks; no scientific stage derives authority from them.
3. **Server experiment draft (Gate 10)** for Steps 03–08.
4. **Rendered frontend harness (Gate 25)** and **generated TS types**.
5. **Multi-user execution scheduler / durable QUEUED-RUNNING attempt lifecycle** (P7C-08 beyond trusted-local).

---

### Final handoff

STARTING HEAD `93f1634` · ENDING HEAD `3187808` (+ this report commit) · BRANCH `phase7d-acquisition-gate-hardening` · WORKTREE clean (tracked) · PUSH none

**REGISTRY** — sole resolver = yes (`ASP_DATASET_REGISTRY_V3`) · active selectable research entries = 2 (Gen-2 2023-2024, Gen-3 V2 2021-2024) · restricted sealed entries = 2 · archived legacy entries = 5 (combined, Gen-3 V1×2, intermediate×2) · sidecars authoritative = no (publisher inputs only)

**SEAL** — ordinary sealed opens = 0 · ordinary target reads = 0 · ordinary predictions/metrics = 0 · ordinary payload exposure = none (objective/Evaluation 2025 removed) · tracked Phase 7B script sealed access = 0 (E1/E2 leakage fail-closed; retired utilities flagged) · archived combined-object ordinary access = 0 (unresolvable via registry)

**OBJECT VERIFIER** — path contained before open = yes (0 outside-root opens) · physical/logical/schema(nullability)/embedded metadata/bundle+contracts/generation+object-kind/season+rows+features = all verified · cache substitution rejected = yes

**FEATURE AUTHORITY** — Gen-2 feature contract = generation-specific base · Gen-3 feature contract = generation-specific base · global fixed list removed as authority = yes · advanced synthetic feature enters run = yes · client arbitrary feature rejected = yes (live 422) · experiment draft server-backed = feature-set + run authority carry the effective config (separate draft = debt)

**FEATURE ABLATION** — canonical service = yes · 2024 only = yes · control/challenger run ids + feature-family SHA + paired game-cluster uncertainty + comparison manifest SHA = yes · 2025 usage = 0

**RUN EVIDENCE** — atomic/content-addressed = yes · manifest anchored to run = yes · child traversal blocked = yes (fixed filenames) · coordinated tamper blocked = yes · logistic estimator = yes · HGB estimator = yes (full joblib) · predictions/targets/diagnostics/full receipt = yes

**ACTIVATION** — COMPLETE required = yes · active binding required = yes · authority + evidence verified = yes · fabricated/non-COMPLETE runs rejected = yes · active read re-verifies = yes

**AUTHORITY / DRIFT** — reconstructed from binding+registry = yes · unknown code/env rejected = yes · final post-fit check = yes · self-attested field forgery rejected = yes

**BINDING** — same-version no-op = NOT this phase (debt) · CAS = backend supersession only (debt) · old binding superseded = yes

**TRUSTED-LOCAL RESOURCE BOUND** — heavy runs per project = 1 (reentrant lock, 429) · strict canonical schemas = yes

TESTS TSC=pass BUILD=pass PY_COMPILE=pass DIFF_CHECK=pass LIVE=pass

PHASE 7B LOCAL ACQUISITION READY = **yes** · SCIENTIST TESTING READY = no (Gate 19/20/25 debt) · PRIVATE BETA READY = no

external downloads = 0 · advanced real features added = 0 · D3 changed = no · D3 retrained = no · champion promoted = no · 2021/2022/2023 dev preserved = yes · 2024 validation preserved = yes · 2025 fit = no · 2025 score = no · 2025 payload exposure = no · 2026 touched = no · security weakened = no · pushes = 0 · main modified = no
