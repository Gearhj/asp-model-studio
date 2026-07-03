# ATLAS Migration Plan

Audit date: 2026-07-03  
Purpose: safe folder restructure plan. This plan intentionally does not move or delete files yet.

## Migration Goals

1. Move ATLAS into a clean, professional project folder.
2. Preserve Greatest Guitarist and Data Science Workflow Tracker/STELA as separate projects.
3. Remove generated dependency/runtime folders from shared zips.
4. Preserve working ATLAS behavior.
5. Make future development easier by separating frontend, backend, docs, tests, and unrelated apps.

## Non-Negotiables

- Do not delete the original `C:\Users\james\ds-workflow-starter` until the migrated projects are verified.
- Use copy-first migration.
- Do not move browser localStorage/sessionStorage data; export important projects first.
- Do not copy `.venv`, `node_modules`, `dist`, `.tmp`, `.runtime`, `catboost_info`, logs, or local secrets into shareable folders.
- Keep unrelated projects intact.

## Proposed Target Layout

```text
C:\Users\james\Projects\
  ATLAS\
    atlas-app\
      frontend\
        index.html
        package.json
        package-lock.json
        vite.config.ts
        tsconfig*.json
        postcss.config.js
        tailwind.config.js
        src\
        public\
      backend\
        server\
        requirements.txt
      tests\
      docs\
      scripts\
      README.md
  Greatest-Guitarist\
    guitarist-app\
      package.json
      index.html
      src\
      public\
      scripts\
  Data-Science-Workflow-Tracker\
    tracker-app\
      package.json
      index.html
      src\
      server\
      docs\
  Archive\
    ds-workflow-starter-original-snapshot\
    old-prototypes\
    unknown-files-review\
```

Alternative: keep ATLAS as one full-stack root with `src` and `server` at the top. This is less clean than frontend/backend split but lower effort.

## Phase 0: Preserve Current State

1. Confirm current Git status.
2. Create a branch for migration work.
3. Export any important browser projects from ATLAS Open Project.
4. Export key governance docs if needed.
5. Copy the entire current folder to a timestamped backup location, excluding generated dependency folders if space is an issue.

Recommended commands after approval:

```powershell
cd C:\Users\james\ds-workflow-starter
git status
git checkout -b codex/atlas-restructure-audit
```

## Phase 1: Create Clean ATLAS Copy

Create:

```text
C:\Users\james\Projects\ATLAS\atlas-app
```

Copy ATLAS source first, excluding generated folders:

- Include: `src`, `server`, `tests`, `public`, `package.json`, `package-lock.json`, Vite/TS/Tailwind configs, `.env.modeling`, documentation.
- Exclude: `node_modules`, `.venv`, `dist`, `.tmp`, `.runtime`, `catboost_info`, logs, `.env.local`.

Important: at first, copy more source than less. Do not try to surgically remove STELA/guitarist during the first copy unless build boundaries are already verified.

## Phase 2: Split Unrelated Projects

### Greatest Guitarist

Move or copy these into `C:\Users\james\Projects\Greatest-Guitarist\guitarist-app`:

- `guitarist.html`
- `src/guitarist-main.tsx`
- `src/GuitaristApp.tsx`
- `src/guitarist.css`
- `src/data/guitarists.ts`
- `src/data/sourceRankings.ts`
- `src/data/supplementalGuitarists.ts`
- `src/data/wikidataGuitarists.ts`
- `scripts/fetch-wikidata-guitarists.mjs`
- `public/assets/guitar-fretboard.png`
- shared build config as needed

Then give it its own package and Vite config.

### Data Science Workflow Tracker / STELA

Move or copy these into `C:\Users\james\Projects\Data-Science-Workflow-Tracker\tracker-app`:

- `src/App.tsx` tracker code, or a cleaned tracker entry.
- `src/apps/StelaDashboardApp.tsx`
- `src/lib/stelaApi.ts`
- `server/stela_router.py`
- `.env.scheduling`
- any STELA-specific public assets and docs.

This split needs extra care because `src/App.tsx` currently selects between ATLAS and STELA by `VITE_APP_TARGET`.

## Phase 3: Rename and Normalize ATLAS Package

In ATLAS copy:

1. Rename package from `ds-workflow-starter` to `atlas`.
2. Update README to ATLAS.
3. Remove `guitarist.html` from ATLAS Vite rollup inputs after guitarist split.
4. Remove scheduling/STELA mode from ATLAS if tracker split is complete.
5. Keep `npm run dev:modeling` or rename to `npm run dev`.
6. Consolidate Python requirements.

Recommended ATLAS scripts:

```json
{
  "dev": "vite --mode modeling --host 127.0.0.1 --port 5174 --strictPort",
  "build": "tsc -b && vite build --mode modeling",
  "preview": "vite preview --host 127.0.0.1 --port 4174",
  "test:experimental-design": "node tests/experimentalDesign.test.mjs"
}
```

## Phase 4: Backend Cleanup

1. Move FastAPI code into `backend/server` or keep as `server` at ATLAS root.
2. Decide one requirements file.
3. Exclude `.runtime` from committed/shared source.
4. Add a documented command:

```powershell
uvicorn server.main:app --reload --host 127.0.0.1 --port 8001
```

5. Remove STELA router from ATLAS backend only after tracker backend has its own route.

## Phase 5: Verification

Run in the migrated ATLAS folder:

```powershell
npm install
npm run build
npm run test:experimental-design
python -m py_compile server\evaluation\eval_service.py
```

Manual smoke tests:

1. Start backend on `127.0.0.1:8001`.
2. Start ATLAS frontend on `127.0.0.1:5174`.
3. Create a Predictive Modeling project.
4. Upload classification dataset and train selected models.
5. Confirm Evaluation and Interpretation load.
6. Create an Experimental Design project.
7. Enter factors and levels.
8. Confirm treatment matrix, Sample Size, Monte Carlo, Run Plan, Optimization, and Documentation.
9. Export governance report and notebook.
10. Reopen project from Recent Projects.

## Phase 6: Archive Original

Only after ATLAS, Greatest Guitarist, and tracker are verified:

1. Keep original `ds-workflow-starter` as an archive for at least one release cycle.
2. Do not delete until user confirms all projects open and build from new locations.
3. If disk space is needed, remove only generated folders from the archive copy:
   - `node_modules`
   - `.venv`
   - `dist`
   - `.tmp`
   - `.runtime`
   - `catboost_info`
   - logs

## Rollback Plan

If migration breaks:

1. Stop using migrated folder.
2. Return to `C:\Users\james\ds-workflow-starter`.
3. Start backend and frontend using existing commands.
4. Re-export any browser projects from the original app.
5. Reattempt migration with a smaller copy scope.

## Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Breaking shared imports when splitting apps | First copy full source, then remove unrelated code incrementally with build verification after each removal. |
| Losing browser projects | Export important projects before migration; do not rely on localStorage moving across domains/ports/folders. |
| Missing assets | Keep public/assets in first copy; remove only after visual verification. |
| Python dependency mismatch | Consolidate requirements after verifying backend starts. |
| Reports or notebook exports fail after path changes | Test all export routes before archiving original. |
| STELA/tracker accidentally deleted | Put it into its own project folder before ATLAS cleanup. |

## Recommended Immediate Next Step

Review these audit documents first. After approval, begin Phase 0 and Phase 1 only. Do not split unrelated apps until the clean ATLAS copy builds and runs.

