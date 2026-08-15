# ASP Model Studio Fork Provenance

## Fork identity

- Source repository: `C:\Users\james\ds-workflow-starter`
- Source branch: `codex/phase2a-canonical-lineage`
- Source HEAD: `e13ac139ec1d684935f50272f2c9cd3ef693ad9d`
- Source status fingerprint: `53feb055ccaaf181aa76c222d02cae02de05093a76920c7bfbbe3bacc9564d6c`
- Source index fingerprint: `4ed8f33a26ece67b4b1b19066b6001134ddbc1a717186aedcf65934d773f926a`
- Source manifest SHA-256: `fb2f949cb6b376c37495b4b6de92e82fc1a76fdde2a25415e012676695d37b01`
- Fork baseline time: `2026-08-15T21:28:53.5733879Z`
- Target repository: `C:\Users\james\asp-model-studio`
- Fork-snapshot commit: `17a6cbe541f481cd3d30a34711bc36ef0a8ae153`
- Snapshot commit message: `baseline: capture ATLAS working tree for ASP Model Studio fork`

The snapshot commit has the source HEAD as its direct parent and preserves the safe, meaningful ATLAS working-tree changes. The target was created by a local `git clone --no-hardlinks`, has its own `.git` directory and object database, has no object-store alternates or worktree link, and has no remote.

## Included untracked work

The snapshot includes 17 Git-visible untracked files: one implementation report, six application source modules, and ten test files. The exact paths, sizes, and SHA-256 values are retained in `docs/fork-evidence/included-untracked-inventory.json`.

The included paths are:

- `ATLAS_ANALYTICAL_SCOPE_AND_PREPROCESSING_INTEGRITY_REPAIR_REPORT.md`
- `server/core/population_contract.py`
- `server/preprocessing/execution_contract.py`
- `server/preprocessing/preprocessing_contract.py`
- `server/scoring_runs/treatment_replay.py`
- `src/lib/predictiveWorkflowCompletionEvidence.ts`
- `src/lib/vifSimulatorSelection.ts`
- `tests/analytical_scope_preprocessing_integrity_test.py`
- `tests/e2e/analytical-scope-preprocessing-integrity-isolated.spec.ts`
- `tests/eda_population_contract_test.py`
- `tests/exact_registry_scoring_contract_test.py`
- `tests/external_scoring_treatment_replay_test.py`
- `tests/interpretationModelSelection.test.mjs`
- `tests/predictiveWorkflowLateCompletion.test.mjs`
- `tests/predictive_workflow_late_completion_reconciliation_test.py`
- `tests/preprocessing_v2_contract_test.py`
- `tests/vifSimulatorSelectionState.test.mjs`

Four of these paths received an additional review because they were not named in a nearby implementation report. Direct import and test references established that they are meaningful application source and regression coverage, so they were included rather than omitted.

## Excluded content

Sixteen Git-visible untracked files under `server/artifacts` were excluded as generated evidence, feature manifests, and VIF plans. Sixteen modified tracked runtime/test-output files were reset to the inherited source-HEAD version in the target; the tracked deletion of `test-results/e2e/artifacts/.last-run.json` was preserved as expressly required by the fork snapshot.

Ignored source-local content was not copied, including `.env.local`, `.venv`, `node_modules`, `dist`, `.tmp`, `.runtime`, caches, logs, SQLite files and sidecars, Python bytecode, test output, and local editor configuration. The exact Git-visible exclusion inventory is retained in `docs/fork-evidence/excluded-untracked-inventory.json`. Twenty inaccessible pytest cache directories were classified by name as generated runtime caches and were not traversed or copied.

## Authority and separation

Financial-services ATLAS remains authoritative at `C:\Users\james\ds-workflow-starter` and was not modified by this fork. ASP Model Studio now evolves independently from the fork-snapshot commit.

AI Sports Predictor remains a separate product and was not accessed. Future communication between AI Sports Predictor and ASP Model Studio must use immutable dataset manifests, governed model bundles, and forward-evidence contracts. The repositories must never share mutable databases, artifact roots, credentials, dependency directories, process state, or Git object storage.

This fork does not introduce sports modeling, data integration, training, deployment, live forecasts, UI redesign, or broad rebranding.
