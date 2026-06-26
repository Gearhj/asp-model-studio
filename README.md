
# DS Workflow Starter

A schema-driven, modular React + TypeScript app (Vite) for teaching a Binary Fraud Classification workflow.

## Quickstart
1) Install Node.js LTS (18+).
2) Unzip this folder.
3) Start the modeling backend when using the modeling tool:
```bash
uvicorn server.main:app --reload --port 8001
```
4) Start the scheduling tool:
```bash
npm install
npm run dev:scheduling
```
Open http://127.0.0.1:5173

5) Start the modeling tool in a separate terminal:
```bash
npm run dev:modeling
```
Open http://127.0.0.1:5174

## Stack
- Vite + React + TypeScript
- Tailwind CSS
- Zustand (state) + localStorage
- (Optional) XState later for strict gating
