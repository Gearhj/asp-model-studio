# Persistent Scoring Runs and Analytical Result History -- Architecture

## 1. Current-state inventory (Phase A)

Before this phase, every scoring-related object was ephemeral except the fitted model's small metadata summary:

| Object | Lived in | Survives refresh? | Survives restart? | Survives project deletion? |
|---|---|---|---|---|
| Scored row-level output (predictions/probabilities/residuals) | HTTP response body only (`eval_service.score_dataset`'s `scored_rows`) | No | No | N/A -- never persisted |
| TRAIN/TEST/OOT scoring results | `Step10_Scoring.tsx` React `useState` (`testResult`/`trainResult`/`ootResult`) | No | No | N/A |
| Metrics/PSI/VSI for a scoring run | Recomputed inline on every `/score/*` call, never cached | No | No | N/A |
| TEST-split scoring reference (for PSI) | `RESULTS.scoring_reference` (in-memory, `(user,project)`-scoped) | Yes (same process) | No | Cleared by `discard_modeling_scopes` |
| Fitted model object | `RESULTS.final_model` (in-memory only) | Yes (same process) | No -- `session_checkpoint.py` explicitly nulls it on restore | Cleared on project deletion |
| Scoring exports | None -- no export/download endpoint exists | -- | -- | -- |
| Scored-output-as-Dataset-Library-asset | `data_full.csv` under the Dataset Library, via explicit "Register" action only | Yes | Yes | Yes (assets survive, unlinked) |
| Evidence for a scoring action | Not captured anywhere (evidence auto-capture only covers Dataset Library entries) | -- | -- | -- |

The one durable path that already existed -- "Register scored dataset" -- produces a Dataset Library snapshot, not a governed *scoring execution* record: it has no model identity, no metrics, no PSI/VSI, and no lineage back to the run that produced it. This is the gap Phase 1 closes.

## 2. Core principle

```
Scoring execution (TRAIN/TEST/OOT/external/monitoring)
  -> durable ScoringRun row (SQLite, metadata + bounded summaries)
  -> governed Parquet artifact (row-level predictions, immutable, write-once)
  -> retrievable by id from any surface: Step10 history panel, Visual
     Intelligence Lab (via URL), Evidence, future Model Monitoring
```

A ScoringRun is created the moment `/score/upload` or `/score/development-split` succeeds -- additively, alongside the existing (unchanged) synchronous response. Existing callers that ignore the new `scoringRunId` response field see no behavior change at all.

## 3. Domain model

`server/analytics/query_contract.py` (Enterprise Analytical Data Plane, prior phase) had already reserved `SourceType.SCORING_SESSION`, `Partition`, and `scoringRunId` in its contract -- this phase is the intended consumer of those fields, not a new parallel contract.

`scoring_runs` table (`server/persistence/migrations/0011_scoring_runs.sql`): scoring_run_id (PK), project_id (`ON DELETE SET NULL` -- see &sect;6), user_id, dataset_id/dataset_version_id/dataset_identity, partition, model_id/model_version/feature_manifest_version, problem_type, target, status, created_at/completed_at/started_by, execution_engine, query_version, row_count, prediction_column/probability_column/residual_column, output_artifact_id/path/format, metrics_json/diagnostics_json/psi_json/vsi_json, evidence_links_json/documentation_links_json, lineage_json, retention_policy, archived_at, checksum, error_message, updated_at. Every field from the brief's minimum-field list is present; `evidenceLinks`/`documentationLinks` are populated via the evidence side-effect (&sect;7) rather than a separate join table, matching this codebase's existing `..._json` column convention (`server/persistence/db.py`'s `decode_row`).

`modelId`/`modelVersion` are synthesized (`metadata.model_key` and the training-run timestamp respectively) because **no durable Model registry exists in this codebase today** (confirmed in the Phase A inventory -- `RESULTS.final_model` is a pure in-memory object, never persisted). This is disclosed as a known limitation, not hidden: a future durable Model entity would let `modelVersion` become a real foreign key instead of a timestamp string.

## 4. Storage split (Phase C/D)

Metadata, bounded metrics/diagnostic summaries, and artifact *references* live in SQLite (`ScoringRunRepository`, following the exact repository/migration pattern already used by every other persistence domain in this codebase -- `server/persistence/repositories/*.py`). The full row-level scored table is written **once**, at creation time, to a governed per-run Parquet file (`server/scoring_runs/scoring_run_artifacts.py`, `ARTIFACT_ROOT/{scoringRunId}/predictions.parquet`, path-traversal-checked exactly like the Dataset Library's `ARTIFACT_ROOT`) -- never re-derived, never mutated. A ScoringRun's Parquet artifact and its SQLite row are therefore both immutable once created, which is also why (&sect;9) it is safe to mark scoring-session queries cacheable in the Enterprise Analytical Data Plane's result cache.

CSV export is available on demand by reading the Parquet artifact back (`read_scoring_run_rows`) rather than keeping a second on-disk copy -- "CSV export optional," not automatic.

A **Scoring Run** is distinct from a **Scored Dataset** (Phase D): the pre-existing `/api/scoring/register-scored-dataset` endpoint (untouched by this phase) still produces a separate, optional Dataset Library asset. A ScoringRun's `summary` endpoint reports `registrationStatus: "not_registered"` today because no code path links the two yet -- a reasonable Phase 2 item (let registration reference the originating `scoringRunId`) rather than something this phase silently pretends is already wired.

## 5. Scoring History API (Phase E)

`server/scoring_runs/scoring_runs_router.py`, mounted at `/api/scoring-runs*` (deliberately distinct from the pre-existing, unrelated `/api/scoring/register-scored-dataset`): list (filterable by project/dataset/model/partition/status/problemType/date range/archived), get, metrics, diagnostics, summary, lineage, rows (bounded), cancel, archive, compare. Every entry point re-authorizes via `authorize_modeling_scope` (`server/scoring_runs/scoring_run_service.py`) -- no new authorization mechanism, no client-supplied ownership.

## 6. TRAIN/TEST/OOT history (Phase F)

Because `upsert()` is keyed by a fresh `scoring_run_id` generated on every scoring action (never reused across calls), scoring the same partition twice produces two independent rows -- verified directly (`tests/scoring_runs_test.py::test_history_preserves_multiple_train_runs_without_overwriting`, two TRAIN runs coexist). The `compare` endpoint returns metrics/PSI side by side for any 2-10 run ids the caller is authorized to read.

## 7. Evidence integration (Phase H)

Every successful `create_scoring_run()` call also writes one SQLite `evidence_artifacts` row (`server/persistence/repositories/evidence_repository.py`, the same table the existing `GET/POST /api/projects/{id}/evidence` endpoints already serve) with `sourceRef = scoringRunId` and a metrics-summary `payload_json`. This is best-effort and wrapped so an evidence-write failure can never fail the scoring action itself.

## 8. Project lifecycle (Phase I)

`scoring_runs.project_id` uses `ON DELETE SET NULL`, not `CASCADE` -- a ScoringRun is a durable governance artifact, matching the Dataset Library's existing "assets survive project deletion, unlinked" precedent (not "assets vanish"). `persistence_router.py`'s `delete_project` calls `archive_scoring_runs_for_project(project_id)` **before** deleting the project row (ordering matters: `SET NULL` fires the instant the project row is gone, so archiving must see a still-valid `project_id`). Archived runs are excluded from the default `list()` view but remain fully readable by id -- verified end-to-end (`ScoringRunProjectDeletionTests`).

## 9. Visual Intelligence integration (Phase G)

`server/analytics/artifact_resolver.py` gained a `SourceType.SCORING_SESSION` branch: resolves `request.scoringRunId` to its governed Parquet path via the SQLite row, rejects a scoring run that does not belong to the request's own `projectId` (no cross-project leakage even if the caller has access to both projects), and returns a `ResolvedSource` exactly like the `REGISTERED` branch -- meaning the existing query planner and DuckDB engine handle it identically, with zero planner changes required (`resolved.file_path is not None` was already the pushdown-eligibility test). Scoring-session sources are also marked cacheable in `query_service.py`, alongside `REGISTERED`, since both are immutable/write-once.

On the client, `VisualIntelligenceContext.tsx` resolves its base reference from a `scoringRunId` URL query parameter when present (`GET /api/scoring-runs/{id}`), falling back to the pre-existing live-workspace resolution otherwise. Because the id lives in the URL rather than React state, a hard refresh reloads the identical run -- verified end-to-end in Playwright (`tests/e2e/scoring-runs.spec.ts`). `dataAccessLayer.ts` gained `fetchScoringRunRows`/`fetchScoringRunEvaluationRows`, used by `DistributionExplorer`, `ClassificationDecisionExplorer`, and `RegressionDiagnosticExplorer` whenever `baseReference.sourceType === "scoring-session"` -- a small, additive branch in each explorer's existing data-fetch effect, not a rewrite of any explorer's rendering logic.

## 10. Known limitations (disclosed, not hidden)

- No durable Model registry exists yet; `modelVersion` is a training-timestamp string, not a real foreign key.
- A ScoringRun and a registered Scored Dataset are not yet cross-linked (`registrationStatus` is always `"not_registered"`).
- Cancellation is structurally supported (status transitions, a `cancel` endpoint) but not functionally meaningful today, because `/score/upload` and `/score/development-split` remain synchronous, unchanged from before this phase -- a ScoringRun is always created already in a terminal state. A future async scoring pipeline would give `cancel` real teeth.
- `Partition` values beyond TRAIN/TEST/OOT ("external-validation", "monitoring") are storable as free text in `scoring_runs.partition` but not yet enumerated in the Enterprise Analytical Data Plane's `Partition` enum -- extending that enum is a small, isolated Phase 2 change once a concrete monitoring/external-validation scoring flow exists.
- Dataset/model *deletion* lifecycle rules were not exercised because neither a Dataset Library hard-delete nor a Model deletion endpoint exists in this codebase today (confirmed in Phase A) -- there is nothing to test yet.
