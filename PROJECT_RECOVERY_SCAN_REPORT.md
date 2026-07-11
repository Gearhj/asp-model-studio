# PROJECT_RECOVERY_SCAN_REPORT

Generated: 2026-07-07

## Summary

Phase 10H adds a deeper recovery path for ATLAS projects that do not appear in Recent Projects. The Open Project page can now scan browser projects, backend project registry metadata, Dataset Library links, and server artifact evidence before the user chooses which candidates to recover.

## Recovery Sources Added

- Browser Recent Projects registry.
- Legacy browser project snapshots and workflow-node state through the existing migration utilities.
- Backend project registry at `server/artifacts/projects/project_registry.json`.
- Dataset Library registry and `project_links.json`.
- Dataset artifact names under `server/artifacts/datasets`.

## Predictive Modeling Evidence Found

The current artifact folder contains recoverable Predictive Modeling evidence:

| Project / Shell | Evidence | Target | Recovery Status |
|---|---|---|---|
| Home Prices Regression Test Model | `REG_TRAIN`, `REG_TEST`, `REG_OOT`, Home Prices scored train/test/OOT outputs, Dataset Library project links | `MedHouseVal` | Partially reconstructable as a dataset-linked predictive shell |
| Recovered Classification Predictive Model | `CLASS_TRAIN`, `CLASS_TEST`, `CLASS_OOT` artifact folders and Dataset Library records | `Class` | Partially reconstructable as a dataset-linked predictive shell |
| Browser Recent Projects | Any currently registered local project snapshot | depends on snapshot | Complete if the browser snapshot is present |

## Critical Recovery Answer

The original regression and classification projects are not guaranteed to be fully recoverable unless their full browser snapshot is still present. However, the data and scored-output evidence for the Home Prices Regression Test Model and classification/fraud workflow are still present in server artifacts and Dataset Library metadata.

That means ATLAS can reconstruct usable Predictive Modeling project shells with project identity, task, target, and linked datasets. Page-level modeling choices, final champion state, and some UI selections may need review if the full browser snapshot is not available.

## Open Project UX Added

- Deep Recovery Scan panel.
- Scan Browser Storage.
- Scan Server Artifacts.
- Scan Dataset Links.
- Recover Selected Projects.
- Export Recovery Report.
- Card View / Detailed View toggle.
- Search by project name, target, dataset, or type.
- Filters for Predictive Modeling, Experimental Design, Regression, Classification, Recovered, and Incomplete.

## Dataset Library Detailed View Added

- Card View / Detailed View toggle.
- Detailed columns for dataset name, type, rows, columns, versions, owner, created, updated, linked projects, latest version, source type, status, and actions.
- Filters for training, test, OOT, scored outputs, regression, classification, uploaded, metadata-only, linked to current project, and unlinked.
- Actions for Open, Open in Analytics, Open in Chart Studio, Open in Model Diagnostics for scored output, Link to Project, Delete, and Export Metadata.

## Known Limitations

- Dataset-linked shells are intentionally not auto-imported. The user must select candidates to recover.
- Full project recovery depends on whether the original browser snapshot still exists.
- The backend project registry currently stores durable metadata, not full workflow snapshots.
- Dataset delete archives records for governance preservation rather than physically deleting artifact files.
