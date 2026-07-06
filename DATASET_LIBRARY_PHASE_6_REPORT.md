# DATASET LIBRARY PHASE 6 REPORT

## Summary

Implemented ATLAS Dataset Library / local Data Warehouse v1 as a backend-backed dataset registry with compact file artifacts, local user access controls, frontend library pages, Data Acquisition reuse, project dataset links, and system diagnostics.

The implementation preserves the existing predictive and experimental workflows. It does not move or rename `ds-workflow-starter`.

## Backend Implementation

Added:

- `server/datasets/dataset_registry.py`
- `server/datasets/dataset_router.py`
- `server/datasets/__init__.py`

New backend artifact storage:

- `server/artifacts/datasets/registry.json`
- `server/artifacts/datasets/users.json`
- `server/artifacts/datasets/project_links.json`
- `server/artifacts/datasets/<datasetId>/versions/<versionId>/`

Stored per-version artifacts:

- metadata
- schema
- profile
- preview
- lineage
- compact CSV sample
- original filename metadata only; full raw upload files are not copied into the registry

The Dataset Library avoids browser `localStorage` for dataset payloads.

## API Endpoints Added

- `GET /api/users/current`
- `GET /api/users`
- `POST /api/users/switch-dev-user`
- `GET /api/datasets`
- `GET /api/datasets/{dataset_id}`
- `POST /api/datasets/upload`
- `POST /api/datasets/register`
- `GET /api/datasets/{dataset_id}/versions`
- `POST /api/datasets/{dataset_id}/versions`
- `GET /api/datasets/{dataset_id}/versions/{version_id}`
- `GET /api/datasets/{dataset_id}/profile`
- `GET /api/datasets/{dataset_id}/versions/{version_id}/profile`
- `GET /api/datasets/{dataset_id}/versions/{version_id}/preview`
- `POST /api/datasets/{dataset_id}/share`
- `POST /api/datasets/{dataset_id}/archive`
- `POST /api/projects/{project_id}/datasets/link`
- `GET /api/projects/{project_id}/datasets`
- `DELETE /api/projects/{project_id}/datasets/{dataset_id}`
- `GET /api/system/diagnostics`

## Frontend Implementation

Added:

- `src/lib/datasetLibrary.ts`
- `src/steps/DatasetLibrary.tsx`
- `src/steps/DatasetDetail.tsx`
- `src/steps/RegisterDataset.tsx`
- `src/steps/SystemDiagnostics.tsx`

Updated:

- `src/apps/ModelingApp.tsx`
- `src/components/Sidebar.tsx`
- `src/steps/Step01_DataAcquisition.tsx`
- `src/steps/ProjectOverview.tsx`
- `src/steps/ProjectUtilityPages.tsx`
- `src/lib/localDataset.ts`
- `src/lib/modelDevelopmentDocument.ts`
- `src/lib/governanceReport.ts`

## Data Acquisition Integration

The Existing Dataset source now:

- loads backend Dataset Library records,
- allows selecting a dataset and version,
- loads preview rows into Data Acquisition,
- lets the user select target/features,
- saves a compact local modeling view,
- links the selected dataset version to the current project.

## Project and Documentation Integration

Project Overview now includes linked Dataset Library assets.

Model Development Document and Governance Report now include:

- Dataset Library ID
- Dataset Library version
- Dataset Library name
- Dataset Library role

## Security and Storage Controls

Implemented:

- backend owner/grant/admin access checks,
- local development user switch,
- compact profile/preview/sample artifacts,
- no raw dataset persistence in browser localStorage,
- diagnostics page for storage and registry health.

Hosted deployment still requires authenticated identity, tenant/project boundaries, audit logging, malware scanning, and hardened authorization.

## Tests Run

- `npm run test:dataset-library` passed.
- `npm run test:data-acquisition` passed.
- `npm run test:regression` passed.
- `npm run test:persistence` passed.
- `.\\.venv\\Scripts\\python.exe -m py_compile server\\datasets\\dataset_registry.py server\\datasets\\dataset_router.py server\\main.py` passed.
- `npm run build:modeling` passed.

## Known Limitations

- Dataset upload v1 supports CSV/TXT only.
- SQL/cloud data sources can be metadata-only records for now.
- Dataset Library preview loads compact preview rows into the browser workflow; full backend project-dataset execution over a registered full dataset is future work.
- The local user switch is development-only and must be replaced before hosted deployment.
