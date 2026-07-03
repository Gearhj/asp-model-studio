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
.\.venv\Scripts\Activate.ps1
uvicorn server.main:app --reload --port 8001
```

Backend health check:

`http://127.0.0.1:8001/api/health`

Interactive API docs:

`http://127.0.0.1:8001/docs`

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
