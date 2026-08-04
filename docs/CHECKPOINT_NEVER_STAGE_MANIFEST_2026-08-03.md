# ATLAS controlled-checkpoint never-stage manifest

Date: 2026-08-03  
Status: protective manifest; no file was deleted, restored, staged, or otherwise changed

## Rule

The paths below are runtime authority, Dataset Library authority, evidence/MDD authority, failed acceptance evidence, or generated output. Preserve them locally for recovery and audit review, but do not include them in a source checkpoint. Several are already tracked, so `.gitignore` alone cannot protect them. Use only exact positive staging manifests and verify `git diff --cached --name-only` before every commit.

## Current working-tree paths — never stage

### Dataset Library and recovery authority (3)

```text
server/artifacts/datasets/.dataset-library-recovery-journal.json
server/artifacts/datasets/project_links.json
server/artifacts/datasets/registry.json
```

Reason: durable registry, project-link, and recovery-journal authority. These are live mutable state, not source fixtures.

### Governed feature/VIF runtime authority (13)

```text
server/artifacts/feature_manifests/atlas-mrzpau4t/ds_heloc_train_6bdb184b_05905/v_1785186305905_6bdb184b/current.json
server/artifacts/feature_manifests/atlas-mrzpau4t/ds_heloc_train_6bdb184b_05905/v_1785186305905_6bdb184b/versions/fm-8e2dc2933912d428.json
server/artifacts/feature_manifests/project_0a83ccd568574d76a00d78d4e7faf694/ds_canonical-identity-asset_ce674dc0/v_1785637519443_ce674dc0/current.json
server/artifacts/feature_manifests/project_0a83ccd568574d76a00d78d4e7faf694/ds_canonical-identity-asset_ce674dc0/v_1785637519443_ce674dc0/versions/fm-4a9d11396e91ecb1.json
server/artifacts/feature_manifests/project_24ba61e0992f469191a8c0abcfb5ef71/ds_canonical-identity-asset_ce674dc0_15244/v_1785637415244_ce674dc0/current.json
server/artifacts/feature_manifests/project_24ba61e0992f469191a8c0abcfb5ef71/ds_canonical-identity-asset_ce674dc0_15244/v_1785637415244_ce674dc0/versions/fm-fc35727e4b6cc142.json
server/artifacts/feature_manifests/project_29e3e43b1f3a4caca5963fd314704ae4/ds_canonical-identity-asset_ce674dc0_63154/v_1785636963154_ce674dc0/current.json
server/artifacts/feature_manifests/project_29e3e43b1f3a4caca5963fd314704ae4/ds_canonical-identity-asset_ce674dc0_63154/v_1785636963154_ce674dc0/versions/fm-d74420124fe3f763.json
server/artifacts/feature_manifests/project_861431d88e354dfaa114cabbe941f29c/ds_canonical-identity-asset_ce674dc0_78124/v_1785636878124_ce674dc0/current.json
server/artifacts/feature_manifests/project_861431d88e354dfaa114cabbe941f29c/ds_canonical-identity-asset_ce674dc0_78124/v_1785636878124_ce674dc0/versions/fm-f35c231dbbd0df41.json
server/artifacts/feature_manifests/project_fe803b2403e240a28756e652046743f8/ds_canonical-identity-asset_ce674dc0/v_1785637339908_ce674dc0/current.json
server/artifacts/feature_manifests/project_fe803b2403e240a28756e652046743f8/ds_canonical-identity-asset_ce674dc0/v_1785637339908_ce674dc0/versions/fm-5d08552f505e47a4.json
server/artifacts/vif_resolution_plans/atlas-mrzpau4t/ds_heloc_train_6bdb184b_05905/v_1785186305905_6bdb184b/plans/vif-plan-50b8ce1a6786b7ad.json
```

Reason: live governed feature-manifest and VIF-plan records. Preserve for exact project recovery; do not treat test-project-looking records as reusable source fixtures.

### Evidence, EDA documentation, and MDD authority (12)

```text
server/artifacts/eda_documentation/1af2077e8d97253bc3c7510c8766ca7d02b3c0592a0228f7ebe6b76e7e4fff9e.json
server/artifacts/evidence/evidence_registry.json
server/artifacts/evidence/items/eda-evidence-atlas-mrzpau4t-eda-19c43c06.json
server/artifacts/evidence/items/eda-evidence-atlas-mrzpau4t-eda-7fd351ce.json
server/artifacts/evidence/items/eda-evidence-atlas-mrzpau4t-eda-b8c03464.json
server/artifacts/evidence/items/eda-evidence-atlas-mrzpau4t-eda-d95e8ff4.json
server/artifacts/evidence/items/ev-governed-feature-manifest-7a80399a072f0da4.json
server/artifacts/evidence/items/ev-governed-outlier-treatment-and-special-val-6f54f85fc59d909d.json
server/artifacts/evidence/items/ev-missing-value-validation-no-treatment-requ-56830e6baf0a8852.json
server/artifacts/evidence/items/ev-target-intel-af288f22039b46c69429.json
server/artifacts/model_documentation/doc-atlas-mrzpau4t-1785363288.json
server/artifacts/model_documentation/document_index.json
```

Reason: append-only/current evidence, documentation, and MDD authority. These can contain project-specific decisions and are not product source.

### Browser/audit evidence requiring human review (15)

```text
audit-output/analysis-partition-p0-acceptance-2026-08-01/acceptance-failure.png
audit-output/analysis-partition-p0-acceptance-2026-08-01/acceptance-result.json
audit-output/live-workflow-p0-acceptance-2026-08-02/acceptance-pre.json
audit-output/live-workflow-p0-acceptance-2026-08-02/acceptance-pre-failure.png
audit-output/project-context-p0-acceptance-2026-08-02/01-project-scoped-route.png
audit-output/project-context-p0-acceptance-2026-08-02/02-authoritative-project-hydration.png
audit-output/project-context-p0-acceptance-2026-08-02/03-data-acquisition-identity.png
audit-output/project-context-p0-acceptance-2026-08-02/04-analysis-partition-current.png
audit-output/project-context-p0-acceptance-2026-08-02/07-eda-http-500.png
audit-output/project-context-p0-acceptance-2026-08-02/08-workflow-type-contradiction.png
audit-output/project-context-p0-acceptance-2026-08-02/09-stable-heloc-project-context.png
audit-output/project-context-p0-acceptance-2026-08-02/10-data-acquisition-exact-identity.png
audit-output/project-context-p0-acceptance-2026-08-02/12-eda-acceptance-failure.png
audit-output/project-context-p0-acceptance-2026-08-02/acceptance-failure.png
audit-output/project-context-p0-acceptance-2026-08-02/acceptance-result.json
```

Reason: these are prior acceptance evidence, including failed-result records (`ok: false`). James may retain selected sanitized evidence outside a source commit after review; default disposition is never-stage.

### Generated Playwright output (3)

```text
test-results/e2e/artifacts/.last-run.json
test-results/e2e/html-report/index.html
test-results/e2e/results.json
```

Reason: reproducible runner output, not reusable test source.

Current exact never-stage count: **46**.

## Protective never-stage patterns

These patterns apply whether or not they were dirty in the protected baseline:

| Pattern | Reason |
|---|---|
| `.runtime/**` | workflow checkpoint and mutable runtime state |
| `server/data/**` | live SQLite persistence and related runtime files |
| `server/artifacts/security/**` | security database and authentication authority |
| `server/artifacts/datasets/**` | Dataset Library registry, links, versions, and recovery state |
| `server/artifacts/analysis_partitions/**` | governed partition metadata and assignment artifacts |
| `server/artifacts/evidence/**` | evidence registry and evidence items |
| `server/artifacts/model_documentation/**` | MDD runtime records |
| `server/artifacts/eda_documentation/**` | live EDA documentation authority |
| `server/artifacts/feature_manifests/**` | governed feature-manifest authority |
| `server/artifacts/vif_resolution_plans/**` | governed recommendation-plan authority |
| `server/artifacts/model_registry/**` | registered model artifacts and checksums |
| `server/artifacts/scoring_runs/**` | scoring-run artifacts; scoring was outside this audit |
| `server/artifacts/training/**`, `server/artifacts/candidates/**`, `server/artifacts/evaluation/**` | training/candidate/evaluation runtime artifacts |
| `audit-output/**` | browser screenshots and acceptance evidence unless explicitly sanitized/approved |
| `test-results/**` | Playwright and test-run output |
| `.tmp/**` | repository-local pseudo-temporary state |
| `dist/**` | generated frontend build output |
| `tsconfig.tsbuildinfo` | generated TypeScript incremental state |
| `.pytest_cache/**`, `pytest-cache-files-*/**` | pytest cache and cache-file artifacts |
| `__pycache__/**`, `*.pyc` | Python bytecode/cache |
| `node_modules/**` | installed dependencies |
| `*.log` | runtime/test/service logs |
| browser profiles, cookies, session exports, authentication traces | secrets/session material; never source-controlled |
| external Windows Temp harnesses/profiles/logs | audit isolation material outside the repository |
| temporary acceptance scripts | one-off harness material, not reusable source |

## Required pre-commit check

For any later approved slice:

```powershell
git diff --cached --name-only
git diff --cached --check
```

Compare the staged list byte-for-byte with the approved positive manifest and confirm that no path or pattern from this document is present. Do not attempt cleanup, restore, or deletion as part of that review.
