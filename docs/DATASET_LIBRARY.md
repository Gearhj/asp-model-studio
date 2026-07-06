# ATLAS Dataset Library v1

The ATLAS Dataset Library is a local, backend-backed dataset registry for governed model-development assets.

## Storage Location

Dataset artifacts are stored under:

```text
server/artifacts/datasets/
```

The registry uses:

```text
server/artifacts/datasets/registry.json
server/artifacts/datasets/users.json
server/artifacts/datasets/project_links.json
```

Each dataset version stores compact governance artifacts:

```text
dataset_<id>/versions/version_<id>/
  metadata.json
  schema.json
  profile.json
  preview.json
  lineage.json
  data_sample.csv
```

ATLAS intentionally does not store raw datasets, full profiling payloads, or large chart objects in browser `localStorage`.

## User and Access Model

Local development uses a simple `users.json` model:

- `admin`: can view and edit all datasets.
- dataset owner: can view, edit, share, and archive owned datasets.
- `editor`: can view and update granted datasets.
- `viewer`: can view granted datasets.

The Settings page includes a local development user switch. Hosted deployment must replace this with authenticated identity and server-side authorization.

## Data Acquisition Integration

The Data Acquisition page now supports `Existing Dataset`.

The user can:

1. choose a registered Dataset Library asset,
2. choose the latest version,
3. load the preview into the modeling workflow,
4. select target/features,
5. persist the selected dataset view,
6. link the dataset version to the current ATLAS project.

## Project Links

Project-dataset links are stored in `project_links.json` and exposed on Project Overview.

The link captures:

- `projectId`
- `datasetId`
- `versionId`
- `datasetRole`
- link timestamp
- linked user

## Diagnostics

System Diagnostics is available at:

```text
/system/diagnostics
```

It verifies:

- artifact root availability,
- registry readability,
- local user configuration,
- project-dataset links,
- access-control configuration.

## Current Limitations

- v1 supports CSV/TXT uploads for profiled data registration.
- SQL/cloud data sources can be registered as metadata-only assets.
- Full data warehouse querying, SSO, cloud sync, row-level entitlements, and hosted auth are out of scope for v1.
- Large simulation arrays and raw datasets are not persisted in browser storage.

