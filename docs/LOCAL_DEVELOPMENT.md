# Local Development

## Frontend

ATLAS runs on Vite in modeling mode.

```powershell
npm install
npm run dev
```

Default URL:

`http://127.0.0.1:5174`

## Backend

The FastAPI backend serves dataset, EDA, preprocessing, training, evaluation, and scoring endpoints.

```powershell
Set-Location "C:\Users\james\ds-workflow-starter"
$env:ATLAS_LOCAL_DEV = "true"
$env:ATLAS_DEV_MODE = "true"
$env:ATLAS_HOSTED_MODE = "false"
.\.venv\Scripts\python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload
```

Do not run `uvicorn main:app` from inside `server`; the backend uses package-relative imports and must be loaded as `server.main` from the repository root.

Backend health check:

`http://127.0.0.1:8000/api/health`

Interactive API docs:

`http://127.0.0.1:8000/docs`

## Common Commands

```powershell
npm run build
npm run build:modeling
npm run test:experimental-design
```

## Notes

- Do not commit `.venv`, `node_modules`, `dist`, `.runtime`, `.tmp`, or local logs.
- Large raw datasets and simulation arrays should not be persisted to browser `localStorage`.
- The old scheduling/STELA application has been separated from the ATLAS runtime and should be launched from its own project folder.
