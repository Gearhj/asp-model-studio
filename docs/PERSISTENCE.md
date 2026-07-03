# Persistence

ATLAS uses local browser persistence for project metadata, workflow decisions, and compact analysis summaries.

## Persisted Data

Recommended persisted fields:

- Project metadata
- Model ID and project context
- Workflow step status
- User selections and final decisions
- Decision journal rationale
- Experiment summaries
- Compact chart-ready aggregates
- Final model metadata and export references

## Data That Should Not Be Persisted in localStorage

Do not store:

- Raw datasets
- Full uploaded files
- Full Monte Carlo iteration arrays
- Full SHAP arrays
- Full scoring output rows
- Large chart payloads
- Long unbounded clickstream logs

Use compact summaries in localStorage. Use IndexedDB or backend-managed artifacts for large objects.

## Recent Projects

Recent Projects should be the primary launcher. Each project should have:

- Stable project ID
- Project name
- Workflow type
- Model ID when applicable
- Created timestamp
- Last modified timestamp
- Progress metadata
- Current workflow stage

## Quota-Safe Writes

Persistence writes should catch quota errors and show inline UI feedback. The application should not use browser alerts for save errors.

## Export Boundary

Shareable exports should exclude runtime caches, local secrets, raw temporary data, and generated build artifacts.
