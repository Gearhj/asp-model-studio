# ATLAS Artifact Storage Strategy

ATLAS intentionally separates small governed workflow state from large analytical artifacts. This prevents browser quota failures and makes project restore behavior predictable.

## Storage Responsibilities

| Artifact Type | Primary Store | Persist Full Payload? | Restore Status |
|---|---|---:|---|
| Project metadata, model ID, workflow progress, selected options, and final decisions | `localStorage` registry | Yes | Fully restored |
| Compact workflow-node evidence and governance summaries | Project-scoped `localStorage` keys | Yes, compacted | Fully restored |
| Browser dataset preview and small sampled rows | `sessionStorage` during active session, compact snapshot in project export | Preview only | Restored with dataset reload required |
| Raw datasets, scoring files, and row-level outputs | Backend filesystem or governed data platform | No | Restored with dataset reload required |
| Fitted model binaries, `.pkl`, `.jar`, SHAP arrays, full RFE paths | Backend artifact store | No | Restored with model rerun required |
| Monte Carlo iteration-level results | Not persisted in `localStorage` | No | Restored with simulation summary only |
| Monte Carlo seed, assumptions, summary metrics, and chart aggregates | Project-scoped `localStorage` | Yes, compacted | Restored with simulation summary only |
| Corrupted or invalid import references | Rejected at import validation | No | Artifact missing |

## Restore Status Definitions

- **Fully restored**: the project can reopen with workflow state, choices, summaries, and compact evidence intact.
- **Restored with dataset reload required**: ATLAS restored decisions and metadata, but raw data must be reloaded before rerunning analysis.
- **Restored with model rerun required**: the model record exists, but fitted artifacts or diagnostics must be regenerated.
- **Restored with simulation summary only**: Monte Carlo decisions and summary metrics are available, but iteration-level simulation traces were intentionally discarded.
- **Artifact missing**: ATLAS detected an invalid, corrupted, or unavailable reference and surfaces a warning instead of failing silently.

## Current Implementation

- Recent Projects are stored in `atlas-local-projects`.
- Workflow-node evidence is stored under `atlas-workflow-node-state:{projectId}:{stepId}`.
- Project snapshots use compact persistence through `src/lib/projectPersistence.ts`.
- Restore semantics are documented in `src/lib/artifactStorage.ts`.
- Large arrays are compacted before browser persistence.

## Future Backend Registry

When ATLAS is hosted, large artifacts should move to a backend registry with immutable artifact IDs, checksums, schema versions, and retention policy metadata. Browser project snapshots should store references and restore statuses, not full payloads.
