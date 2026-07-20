# ATLAS Registry and Management Dashboard Report

## Scope

Implemented the ATLAS Registry and Management Command Center portfolio layer from real SQLite persistence in `C:\Users\james\ds-workflow-starter`. The implementation does not use mocked portfolio assets. It derives registry state from persisted projects, workflow state, evidence artifacts, run records, documentation packages, export artifacts, decision journal records, and audit records.

## Backend

New registry API routes are mounted under `/api`:

- `GET /api/registry/assets`
- `GET /api/registry/assets/{project_id}`
- `GET /api/registry/summary`
- `GET /api/registry/actions`
- `GET /api/registry/activity`
- `GET /api/registry/owners`

The registry service computes:

- Asset class and workflow classification.
- Evidence readiness from the shared evidence status contract.
- Documentation readiness from persisted package and section records.
- Validation status and validation score from workflow and run records.
- Recommendation, implementation, and monitoring status from decision and evidence records.
- Explainable lifecycle status with matched rule and reason trail.
- Open governance actions only when the persisted record requires action.
- Portfolio activity and owner rollups.

Verified real persisted project:

- Project ID: `atlas-mrlgel4o`
- Name: `Cash Logistics Transportation QA`
- Asset type: `Optimization Study`
- Template: `Transportation / Logistics`
- Lifecycle: `Implementation Planned`
- Evidence: `Ready`, 100 percent
- Documentation: `Complete`, 100 percent
- Validation: `Complete`, score 100
- Recommendation: `Recommended`
- Implementation: `Plan complete`
- Monitoring: `Plan complete`
- Open actions: 0

## Frontend

Added:

- `/management-dashboard`
- `/registry`
- `/registry/:projectId`

Updated:

- Sidebar now has a consolidated `MANAGEMENT` group with Management Dashboard, Model / Decision Registry, Model Evidence Center, and Audit Log.
- Project Overview now shows an Enterprise Analytical Asset registry status panel and links to the canonical persisted registry asset.
- Registry detail page includes lifecycle derivation, evidence readiness, documentation readiness, latest analytical runs, recommendation and implementation state, export artifacts, open actions, and audit trail.

The Project Overview integration supports compact browser-restored projects by resolving the canonical persisted registry asset by project name when the active browser project ID differs from the SQLite project ID.

## Visual and Responsive QA

Manual browser QA was performed against:

- `http://127.0.0.1:5174/management-dashboard`
- `http://127.0.0.1:5174/registry`
- `http://127.0.0.1:5174/registry/atlas-mrlgel4o`
- `http://127.0.0.1:5174/project-overview`

Confirmed:

- Dashboard loads the real `Cash Logistics Transportation QA` portfolio asset.
- Registry table shows the persisted SQLite asset with lifecycle, evidence, documentation, validation, recommendation, implementation, and activity.
- Registry detail page shows persisted timeline, runs, exports, decisions, documentation, and audit records.
- Project Overview shows the registry status panel and links to `/registry/atlas-mrlgel4o`.
- Dashboard, registry list, and registry detail have no mobile horizontal overflow at a 390 pixel mobile viewport.
- Registry detail switches timeline, run records, and export artifacts to mobile-friendly stacked cards.
- New registry visible copy does not use em dashes.

## Validation

Automated checks run:

- `npx tsc -b`
- `npm run build`
- `npm run test:registry-dashboard`
- `npm run test:project-types`
- `npm run test:workflow-navigation-state`
- `npm run test:open-project`
- `npm run test:persistence`
- `npm run test:regression`
- `npm run test:dataset-library`
- `npm run test:model-documentation`
- `npm run test:evidence-graph`
- `npm run test:credit-risk-studio`
- `npm run test:optimization`
- `npm run test:user-management`

Latest final checks after the responsive detail-page adjustment:

- `npx tsc -b`: passed
- `npm run test:registry-dashboard`: passed, 10 frontend checks and 6 backend checks
- `npm run build`: passed

Build warnings remain the existing Vite bundle-size and browser-data currency warnings. They do not block the registry implementation.

## Files Added or Updated

Backend:

- `server/registry/__init__.py`
- `server/registry/router.py`
- `server/registry/schemas.py`
- `server/registry/registry_service.py`
- `server/main.py`
- `shared/evidence_status_contract.json`
- `src/lib/persistedEvidenceStatus.ts`

Frontend:

- `src/lib/registryApi.ts`
- `src/lib/serverPersistence.ts`
- `src/components/registry/RegistryPrimitives.tsx`
- `src/steps/ManagementDashboard.tsx`
- `src/steps/RegistryPage.tsx`
- `src/steps/RegistryAssetDetail.tsx`
- `src/components/Sidebar.tsx`
- `src/apps/ModelingApp.tsx`
- `src/steps/ProjectOverview.tsx`

Tests:

- `tests/registry_backend_test.py`
- `tests/registryDashboard.test.mjs`
- `package.json`

Report:

- `ATLAS_REGISTRY_MANAGEMENT_DASHBOARD_REPORT.md`

## Notes

The registry is intentionally source-of-truth based on SQLite persistence. Browser project snapshots can still be compact and may omit large artifacts, but the registry surfaces remain driven by persisted backend records when the backend is available.

