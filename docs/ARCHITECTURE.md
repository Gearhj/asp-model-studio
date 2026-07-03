# Architecture

ATLAS is organized as a React/Vite frontend with a FastAPI backend.

## Frontend Runtime

- Entry point: `src/main.tsx`
- ATLAS app boundary: `src/AtlasApp.tsx`
- Main application shell: `src/apps/ModelingApp.tsx`
- Branding: `src/config/brand.ts`, `src/components/BrandLogo.tsx`
- Workflow state: `src/state`
- Predictive modeling pages: `src/steps`
- Experimental design workflow: `src/workflows/experimental-design`

The ATLAS runtime now imports `AtlasApp`, which renders the regulated model development workbench only. Legacy STELA and Greatest Guitarist source files are preserved in the original repository but are not part of the ATLAS entry path.

## Backend Runtime

- API factory: `server/main.py`
- Dataset store: `server/core/dataset_store.py`
- Session checkpointing: `server/core/session_checkpoint.py`
- Metadata endpoints: `server/core/metadata_router.py`
- EDA endpoints: `server/eda/eda_router.py`
- Preprocessing endpoints: `server/preprocessing`
- Training endpoints: `server/training/trainer_router.py`
- Evaluation endpoints: `server/evaluation/eval_router.py`

The ATLAS backend no longer mounts the STELA router. STELA is preserved as a separate project asset.

## Build Boundary

Vite builds `index.html` only for ATLAS. The former Greatest Guitarist `guitarist.html` entry is preserved for the standalone guitarist app, but is no longer bundled into the ATLAS build.

## Separation Strategy

The original workspace remains the controlled source and backup. Clean copies are synchronized into:

- `C:\Users\james\Projects\ATLAS\atlas-app`
- `C:\Users\james\Projects\Greatest-Guitarist\guitarist-app`
- `C:\Users\james\Projects\Data-Science-Workflow-Tracker\tracker-app`
