# ATLAS Repository Inventory

Audit date: 2026-07-03  
Workspace audited: `C:\Users\james\ds-workflow-starter`  
Scope: inventory only. No files were moved or deleted.

## Executive Summary

The current workspace is a mixed development folder containing ATLAS, an older Data Science Workflow Tracker / STELA dashboard, and the Greatest Guitarist web app. They share one Vite package and one root `package.json`. ATLAS is the active modeling product, but the repository root still carries legacy names, older starter documentation, multiple app entry points, generated runtime folders, and unrelated project code.

The safest path is a copy-first migration into a clean project structure, not an in-place move. ATLAS should become its own project folder after the audit artifacts are reviewed.

## Current Root

`C:\Users\james\ds-workflow-starter`

Important top-level folders:

| Path | Classification | Notes |
|---|---|---|
| `src` | Mixed source | Contains ATLAS, STELA/tracker app, and Greatest Guitarist source. |
| `server` | ATLAS backend plus STELA router | FastAPI backend used by predictive modeling and STELA endpoints. |
| `tests` | ATLAS tests | Currently has `experimentalDesign.test.mjs`. |
| `public` | Shared static assets | Includes favicon and guitar image assets. |
| `scripts` | Mixed scripts | Includes Greatest Guitarist Wikidata script. |
| `.venv` | Generated Python environment | Should never be included in shared zip. |
| `node_modules` | Generated Node dependencies | Should never be included in shared zip. |
| `dist` | Generated build output | Can be regenerated. |
| `.runtime` | Runtime checkpoint data | Contains backend checkpoint artifacts. Treat as local runtime state. |
| `.tmp` | Temporary working data | Not source. |
| `catboost_info` | Generated model training output | Not source. |
| `media` | Needs review | Likely assets or generated media. Confirm before migration. |

Important top-level files:

| File | Classification | Notes |
|---|---|---|
| `package.json` | Active package manifest | Single real Node/Vite package root. |
| `package-lock.json` | Active dependency lock | Keep with package. |
| `vite.config.ts` | Active Vite config | Builds both `index.html` and `guitarist.html`. |
| `index.html` | Main app entry | Loads `src/main.tsx`. |
| `guitarist.html` | Greatest Guitarist entry | Loads `src/guitarist-main.tsx`. |
| `requirements.txt` | Python dependency file | Larger than `server/requirements.txt`; contains production, docs, ML, and optional dependencies. |
| `server/requirements.txt` | Backend dependency file | Smaller backend-focused set. Conflicts with root versions. |
| `README.md` | Outdated starter documentation | Still says DS Workflow Starter and binary fraud workflow. |
| `Startup Instructions.txt` | Local instructions plus package cleanup notes | Useful but should be rewritten for ATLAS. |
| `.env.modeling` | Mode config | Contains `VITE_APP_TARGET=modeling`, `VITE_API_BASE=/api`. |
| `.env.scheduling` | Mode config | Contains `VITE_APP_TARGET=scheduling`. |
| `.env.local` | Local environment | Present locally and ignored by `.gitignore`; do not share. |
| `guitarist.html` | Unrelated app entry | Belongs with Greatest Guitarist project if split. |

## Package Roots

Only one active application package root was found outside generated folders:

| Package root | Purpose |
|---|---|
| `C:\Users\james\ds-workflow-starter\package.json` | Vite/React package for ATLAS, STELA/tracker, and Greatest Guitarist. |

Package files inside `.venv` are Jupyter/labextension dependencies and are not app roots. `node_modules`, `.venv`, `dist`, and `.tmp` were excluded from source inventory.

## Active App Entry Points

| Entry | Path | Purpose |
|---|---|---|
| Main app | `index.html` -> `src/main.tsx` -> `src/App.tsx` | Selects app by `VITE_APP_TARGET`. |
| ATLAS modeling | `src/apps/ModelingApp.tsx` | Loaded when `VITE_APP_TARGET=modeling`. |
| STELA / workflow tracker | `src/apps/StelaDashboardApp.tsx` | Loaded by default scheduling mode. |
| Greatest Guitarist | `guitarist.html` -> `src/guitarist-main.tsx` -> `src/GuitaristApp.tsx` | Separate local website bundled into the same Vite config. |
| Backend API | `server/main.py` | FastAPI app on port 8001. |

## ATLAS Source Inventory

### Frontend

Core ATLAS files and folders:

| Path | Purpose |
|---|---|
| `src/apps/ModelingApp.tsx` | ATLAS route shell, header, sidebar, Atlas Guide layout. |
| `src/components/Sidebar.tsx` | ATLAS navigation. |
| `src/components/CopilotCard.tsx` | Atlas Guide recommendation panel. |
| `src/components/BrandLogo.tsx` | ATLAS branding component. |
| `src/config/brand.ts` | Central brand constants. |
| `src/config/workflows.ts` | Predictive and project-type workflow definitions. |
| `src/state/useWorkflowStore.ts` | Persistent workflow store and project snapshot bridge. |
| `src/lib/localProjects.ts` | Browser Recent Projects registry and legacy migration. |
| `src/lib/projectContext.ts` | Project context model and defaults. |
| `src/lib/localDataset.ts` | Browser/session dataset cache. |
| `src/lib/decisionJournal.ts` | Audit trail model and exports. |
| `src/lib/experimentTracking.ts` | Lightweight experiment records. |
| `src/lib/governanceReport.ts` | Governance report generator. |
| `src/lib/modelDevelopmentDocument.ts` | Model development document generator. |
| `src/lib/notebookExport.ts` | Notebook and Python export generator. |
| `src/lib/experimentalDesign.ts` | Experimental Design analysis object and DOE helpers. |
| `src/steps/Step00_ProjectContext.tsx` through `src/steps/Step13_ModelMonitoring.tsx` | Predictive modeling workflow pages. |
| `src/steps/WorkflowPlaceholderStep.tsx` | Multi-project workflow page renderer, including Experimental Design pages. |
| `src/steps/ProjectUtilityPages.tsx` | Open project, settings, export utilities. |
| `src/steps/NewProject.tsx` | New project creation. |
| `src/assets/branding` | ATLAS branding assets. |

### Backend

| Path | Purpose |
|---|---|
| `server/main.py` | FastAPI app factory, CORS, upload endpoint, router registration. |
| `server/core/dataset_store.py` | In-memory raw/processed/split dataset store. |
| `server/core/result_store.py` | In-memory model results and artifacts. |
| `server/core/session_checkpoint.py` | Pickle checkpoint to `.runtime/workflow_checkpoint.pkl`. |
| `server/core/metadata_router.py` | Dataset sample and metadata endpoints. |
| `server/eda/*` | EDA services and image endpoints. |
| `server/preprocessing/*` | Missing and outlier services. |
| `server/splitting/*` | Train/test split and balancing. |
| `server/training/*` | Model availability and training. |
| `server/evaluation/*` | Evaluation, RFE, interpretation, scoring, model export. |
| `server/stela_router.py` | STELA dashboard API, not core ATLAS modeling. |

## Unrelated or Separate Projects

### Greatest Guitarist

These files should be preserved but separated from ATLAS:

| Path | Notes |
|---|---|
| `guitarist.html` | Standalone entry point. |
| `src/guitarist-main.tsx` | Standalone React bootstrap. |
| `src/GuitaristApp.tsx` | Main guitarist app. |
| `src/guitarist.css` | Guitarist styling. |
| `src/data/guitarists.ts` | Curated guitarist dataset. |
| `src/data/sourceRankings.ts` | Ranking source data. |
| `src/data/supplementalGuitarists.ts` | Supplemental guitarist records. |
| `src/data/wikidataGuitarists.ts` | Generated or imported guitarist records. |
| `scripts/fetch-wikidata-guitarists.mjs` | Data acquisition script. |
| `public/assets/guitar-fretboard.png` | Guitarist visual asset. |

### Data Science Workflow Tracker / STELA

These files appear to belong to a separate tracker/dashboard line:

| Path | Notes |
|---|---|
| `src/App.tsx` | Contains legacy `ModelFlow` scheduling/tracker code and mode switch to ATLAS. |
| `src/apps/StelaDashboardApp.tsx` | STELA dashboard app. |
| `src/lib/stelaApi.ts` | STELA API client. |
| `server/stela_router.py` | STELA backend router. |
| `.env.scheduling` | Vite target for scheduling/tracker. |

This project should not be deleted. It should be copied into its own folder if still needed.

## Duplicates, Deprecated Files, and Review Items

| Path | Issue | Recommendation |
|---|---|---|
| `src/state/stepOrder.tx` | Suspicious extension/duplicate next to `stepOrder.ts`. | Inspect and archive if unused after grep/build verification. |
| `src/steps/Step07_Eval.tsx` | Appears obsolete; active route uses `Step08_Evaluation.tsx`. | Confirm no imports. Archive if unused. |
| `README.md` | Outdated product name and workflow description. | Replace after restructure. |
| `Startup Instructions.txt` | Useful but outdated; includes package uninstall notes. | Convert to `docs/LOCAL_DEVELOPMENT.md`. |
| `requirements.txt` and `server/requirements.txt` | Version conflicts between root and server dependency files. | Consolidate into one backend dependency strategy. |
| `.runtime` | Runtime checkpoint data, not source. | Exclude from migration unless explicitly preserving local session state. |
| `server/static` | Generated/static backend output. | Review before copying to clean source folder. |
| `media` | Unknown role. | Manually inspect before move. |
| `*.log` files | Generated logs. | Do not migrate as source. |

## Recommended Target Structure

Do not execute until `MIGRATION_PLAN.md` is reviewed.

```text
C:\Users\james\Projects\
  ATLAS\
    atlas-app\
      frontend\
      backend\
      docs\
      tests\
      scripts\
      runtime\
  Greatest-Guitarist\
    guitarist-app\
  Data-Science-Workflow-Tracker\
    tracker-app\
  Archive\
    ds-workflow-starter-original-snapshot\
    old-prototypes\
    unknown-files-review\
```

## Immediate Inventory Conclusions

1. ATLAS should not be restructured in place until the user approves a copy-first migration.
2. Greatest Guitarist and the tracker/STELA app are separate projects and should be preserved.
3. The current Vite package is overloaded with three app identities.
4. Local browser storage and backend `.runtime` checkpoint state are not portable project files.
5. Generated folders can be omitted from shared zips: `node_modules`, `.venv`, `dist`, `.tmp`, `.runtime`, `catboost_info`, logs.

