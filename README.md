# ATLAS

Enterprise AI Model Development Platform

ATLAS is a local-first regulated AI/ML model development workbench for consumer lending model development. It supports guided and power-user workflows across data acquisition, EDA, preprocessing, model training, evaluation, interpretation, scoring, governance documentation, and experimental design.

## Local Quickstart

Install frontend dependencies:

```powershell
npm install
```

Start the FastAPI backend:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn server.main:app --reload --port 8001
```

Start ATLAS:

```powershell
npm run dev
```

Open [http://127.0.0.1:5174](http://127.0.0.1:5174).

## Verification

```powershell
npm run build
npm run build:modeling
npm run test:experimental-design
```

## Project Separation

This folder is the source workspace for ATLAS. The Phase 2 clean copy is synchronized to:

`C:\Users\james\Projects\ATLAS\atlas-app`

Related projects are preserved separately:

- Greatest Guitarist: `C:\Users\james\Projects\Greatest-Guitarist\guitarist-app`
- Data Science Workflow Tracker / STELA: `C:\Users\james\Projects\Data-Science-Workflow-Tracker\tracker-app`

The original `C:\Users\james\ds-workflow-starter` folder remains the git-tracked working backup until all separated builds are fully verified.

## Documentation

- [Local Development](docs/LOCAL_DEVELOPMENT.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Persistence](docs/PERSISTENCE.md)
- [Security and Data Handling](docs/SECURITY_AND_DATA_HANDLING.md)
- [Release Checklist](docs/RELEASE_CHECKLIST.md)
- [Predictive Modeling Workflow](docs/workflows/predictive-modeling.md)
- [Experimental Design Workflow](docs/workflows/experimental-design.md)
