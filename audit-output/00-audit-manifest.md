# 00 — ATLAS Enterprise Validation Audit: Manifest

**Audit date:** 2026-07-26
**Audit type:** Independent, read-only validation and diagnostic audit. **Not** a remediation assignment.
**Governing documents:** `AGENTS.md`, `ATLAS_CURRENT_STATE_HANDOFF.md`, `ATLAS_CODEX_ULTRA_VALIDATION_AUDIT_PROMPT.md`, `README-FIRST.md` (audit pack, read in full before analysis began).

---

## 1. Audit-pack location discrepancy (recorded per instruction "resolve discrepancies in favour of the actual repository")

The four audit-pack documents were **not present in the working repository**. Verified by filesystem search, `git ls-files`, and `git log --all --diff-filter=A`: none of `README-FIRST.md`, `AGENTS.md`, `ATLAS_CURRENT_STATE_HANDOFF.md`, or `ATLAS_CODEX_ULTRA_VALIDATION_AUDIT_PROMPT.md` has ever been tracked in this repository.

They were located in a prepared audit snapshot directory (`atlas-audit-snapshot-2026-07-26`, alongside a second copy in the system temp directory). `README-FIRST.md` explains this: the files are ChatGPT-generated artifacts that were downloaded into the snapshot rather than written into the project. All four were read completely from the snapshot before any analysis began.

## 2. Which tree was audited, and why

`README-FIRST.md` instructs that the audit be run against the **snapshot**, not the live folder, for one stated reason: *"Do not let Codex and Claude Code write to the same working tree."* That hazard does not apply to this run — there is exactly one agent, it is the agent that previously edited the live tree, and it has stopped editing. The bootstrap instruction (item 5) also requires that **the actual repository be treated as authoritative**.

**Decision: the live repository was audited; deliverables are written to `audit-output/` inside it.**

This decision was made safe by verifying the two trees are equivalent for all audited source:

| Comparison | Result |
| --- | --- |
| `HEAD` (live vs snapshot) | identical — `4e21fdd` on `master` |
| `diff -rq src/` | **no differences** |
| `diff -rq tests/` | no differences except a `__pycache__` directory |
| `tests/e2e/data-acquisition-ui-load.spec.ts` | present in both |

**Consequence:** conclusions drawn here apply equally to the snapshot. Where the handoff document and the repository disagree, the repository wins and the divergence is labelled in the relevant deliverable.

## 3. Repository identity and working-tree state

| Item | Value |
| --- | --- |
| Branch | `master` |
| HEAD | `4e21fdd57e6c0318b34a60b579679f279cbedd5f` — *"Backend updates"* |
| Previous commits | `9af9e09` *Total backend redesign. Completely hardened.* · `ef7e45d` · `a988cb4` · `17cdc0a` |
| Working tree | **dirty — 23 entries.** Preserved byte-for-byte; nothing staged, committed, reset, cleaned, checked out, stashed, or reverted during this audit. |

### Working-tree summary (all 23 entries)

**Modified — product source (3 files, +111 / −15):**
- `src/steps/Step01_DataAcquisition.tsx` (+55/−…)
- `src/lib/dataAcquisitionLifecycle.ts`
- `tests/dataAcquisitionStatus.test.mjs`

**Modified — runtime/application state written by the app itself, not by hand:**
- `server/artifacts/datasets/project_links.json`
- `server/artifacts/datasets/registry.json`
- `server/artifacts/evidence/evidence_registry.json`
- `test-results/e2e/artifacts/.last-run.json`

**Untracked — new test + application-generated evidence + test output:**
- `tests/e2e/data-acquisition-ui-load.spec.ts` *(the new UI-driven walkthrough)*
- 5 × `server/artifacts/evidence/items/ev-predictive-modeling-project-context-*.json`
- 4 × `test-results/e2e/screenshots/2026-07-26T*/` run directories
- 1 × `test-results/e2e/artifacts/data-acquisition-ui-load-*-chromium/`

**Deleted (5) — prior Playwright attachments superseded by later runs:**
- 4 PNG attachments + 1 diagnostics JSON under `test-results/e2e/artifacts/data-acquisition-status-*-chromium/attachments/`

> **Observation for the record (P3, hygiene):** the working tree shows that *running the test suite mutates tracked, committed files* — `registry.json`, `project_links.json`, and `evidence_registry.json` are live application state that is under version control. This is noted as a finding in the persistence and testing lanes rather than treated as an artefact of this audit.

## 4. Known audit baseline limitation (recorded, not treated as a platform-wide failure)

`tests/e2e/data-acquisition-ui-load.spec.ts` is **currently red**. `test-results/e2e/artifacts/.last-run.json` records `"status": "failed"` with one failed test.

Per the master prompt and the handoff, this is scoped as follows:

- **Already proven in the real browser** (screenshots 001–004 captured under `test-results/e2e/screenshots/2026-07-26T22-06-40-552Z/`): UI selection of the exact Dataset and Dataset Version; the visible Load command; the real load action; all seven loading milestones; `Version Loaded`; and the 170,884 / 52 / 29 reconciliation.
- **Unresolved:** the final predictor-semantics assertion block, and the fifth screenshot (`ui-05-variable-summary-high-iv-and-counts`) was never captured.
- **Audit treatment:** recorded as a *known localized unfinished acceptance item*. It is **not** scored as a P0, is **not** taken as evidence that the architecture is broken, and is **not** remediated here.

## 5. Environment and hardware context (for benchmark interpretation)

| Item | Value |
| --- | --- |
| OS | Windows 10 Pro 19045 |
| CPU | Intel Core i7-4790 @ 3.60 GHz — 4 physical cores / 8 logical |
| RAM | 34,244,681,728 bytes (≈ 31.9 GiB) |
| Free disk (C:) | ≈ 631 GiB free of ≈ 953 GiB |
| Node | v24.3.0 |
| npm | 11.6.4 |
| Python | 3.12.6 (repository virtualenv) |
| Frontend | Vite dev server, `http://127.0.0.1:5174` |
| Backend | FastAPI / uvicorn, port `8001` |
| Required env | `ATLAS_CODE_SANDBOX_COMMAND=default` for Python execution |

> This is a **2014-era 4-core desktop CPU**. Every measured throughput number in `04-scalability-and-performance.md` must be read against this hardware; it materially understates what modern server silicon would deliver, and that adjustment is stated explicitly wherever a projection is made.

**Safe-benchmark limits applied** (per `AGENTS.md` §"Safe test and benchmark limits"): peak audit memory kept well below 50% of available RAM; generated temporary data kept far below the 20 GB ceiling; every dynamic probe timeout-bounded; live registered artifacts read-only.

## 6. Repository scale (measured)

| Metric | Count |
| --- | --- |
| Backend Python files (excl. `__pycache__`) | 224 |
| Backend Python LOC | 44,770 |
| Frontend TypeScript/TSX files | 286 |
| Frontend LOC | 97,237 |
| **Total audited application LOC** | **≈ 142,000** |
| Backend router modules (`*router*.py`) | 39 |
| Playwright specs (`tests/e2e/*.spec.ts`) | 23 |
| Node unit tests (`tests/*.test.mjs`) | 54 |
| Backend top-level domain packages | 35 |

Backend domain packages: `admin`, `analytics`, `analytics_engine`, `charts`, `code_execution`, `core`, `credit_risk`, `data`, `datasets`, `eda`, `evaluation`, `evidence`, `experimentation`, `features`, `model_diagnostics`, `model_documentation`, `model_registry`, `monitoring`, `notebooks`, `notifications`, `optimization`, `persistence`, `preprocessing`, `projects`, `registry`, `scoring`, `scoring_runs`, `security`, `sharing`, `splitting`, `sql_studio`, `training`, `validation`.

## 7. Benchmark subject (authoritative figures, per handoff §3)

| Property | Value |
| --- | --- |
| Project | `Credit Card Transaction Fraud Model - TEST` (Model ID `00001`) |
| Dataset | `CLASS_TRAIN` — `ds_class_train_982c7a7d_35930` |
| Version | `v_1784989835930_982c7a7d` |
| Schema | `Time`, `V1`–`V28`, `Amount`, `Class` |
| Population | 170,884 rows × 31 columns |
| Target | `Class`; `1` = event, `0` = non-event |
| Events / non-events | 360 / 170,524 |
| Event rate | `360 / 170884` = 0.002106692259… ≈ 0.2107% (≈ 473.7 non-events per event) |
| Duplicate rows | 52 |
| Columns with missing values | 29 |
| Selected predictors | 30 |

**Standing interpretation rule applied throughout this audit** (`AGENTS.md` §9): `V1`–`V28` are PCA-transformed components. **A high Information Value is not by itself evidence of leakage.** No finding in this audit treats strong IV alone as a leakage signal, a progression blocker, or grounds for automatic exclusion.

## 8. Audit operating model

**Main agent (this agent)** — the only agent permitted to write, and only under `audit-output/`.

**Seven independent read-only lanes**, each run as a separate subagent with no write tools and an explicit prohibition on file creation, shell redirection, mutating git commands, package installation, server start/stop, migrations, and live exploitation:

| Lane | Scope |
| --- | --- |
| 1 | Architecture and request-flow mapping |
| 2 | Security and multi-user isolation (static review only — no live exploitation) |
| 3 | Data-plane and scalability |
| 4 | Persistence, jobs, and failure recovery |
| 5 | Model lifecycle, reproducibility, evidence, MDD, validation, monitoring |
| 6 | Frontend workflow, UX, accessibility, browser performance |
| 7 | Testing, CI, dependencies, deployment, observability, disaster recovery |

Lane reports are evidence, not conclusions. Every material lane claim is re-checked by the main agent against the code before it enters the findings register, and any claim that could not be independently confirmed is carried into `12-open-questions.md` rather than asserted.

## 9. Evidence classification standard

Every conclusion in every deliverable is labelled as exactly one of:

- **OBSERVED FACT** — directly read in the repository, with `file:line`.
- **VERIFIED TEST RESULT** — produced by a command run during this audit, or by a named existing test.
- **INFERENCE** — reasoned from observed facts; the reasoning is shown.
- **UNVERIFIED ASSUMPTION** — stated as such, with the exact evidence or test that would settle it.

## 10. Audit restrictions honoured

| Restriction | Status |
| --- | --- |
| No production source edited | Honoured — writes confined to `audit-output/` |
| No commit / stage / push / merge / rebase / stash / reset / restore / clean | Honoured — no mutating git command run |
| No schema change, no migration run against live state | Honoured |
| No package install or upgrade | Honoured |
| No registered dataset, model, scoring, evidence, documentation, validation, monitoring or audit record altered | Honoured |
| Writes only under `audit-output/` | Honoured |
| Disposable resources for any dynamic test | Honoured |
| No secrets, credentials, or sensitive data in deliverables | Honoured |
| No destructive or exploitative requests; no external systems contacted | Honoured — security lane is static code review only |
| No recommendation to abandon or rebuild ATLAS | Honoured |
| No fixes implemented | Honoured |

## 11. Commands used (representative; all read-only)

```
git log --oneline -5
git rev-parse --abbrev-ref HEAD ; git rev-parse HEAD
git status --porcelain
git diff --stat -- src tests
git ls-files ; git log --all --diff-filter=A --name-only -- <audit-pack globs>
diff -rq <live>/src <snapshot>/src ; diff -rq <live>/tests <snapshot>/tests
node --version ; npm --version ; ./.venv/Scripts/python.exe --version
wmic cpu get ... ; wmic ComputerSystem get TotalPhysicalMemory ; wmic logicaldisk ...
find server -name '*.py' ... | wc -l   (and equivalents for src, routers, tests)
```

Dynamic verification performed later in the audit is logged, with its exact commands and raw results, in `04-scalability-and-performance.md` and `03-security-and-isolation.md`.

## 12. Deliverables

| File | Contents |
| --- | --- |
| `00-audit-manifest.md` | this document |
| `01-executive-verdict.md` | verdict, strengths, risks, readiness scoring |
| `02-system-architecture.md` | component map, request flows, sources of truth, Mermaid diagrams |
| `03-security-and-isolation.md` | threat model, authorization matrix, security findings |
| `04-scalability-and-performance.md` | measured benchmarks, envelopes, capacity model |
| `05-persistence-jobs-and-recovery.md` | persistence inventory, source-of-truth map, failure behaviour |
| `06-model-lifecycle-governance-and-mdd.md` | lineage, reproducibility, evidence, MDD, validation, monitoring |
| `07-frontend-ux-and-accessibility.md` | workflow integrity, status truthfulness, accessibility |
| `08-testing-deployment-and-operations.md` | test inventory, dependencies, deployment, observability, DR |
| `09-findings-register.csv` | full findings register |
| `10-prioritized-roadmap.md` | phased remediation roadmap |
| `11-validation-harness-plan.md` | automated suite specification |
| `12-open-questions.md` | everything that could not be verified, and how to settle it |
