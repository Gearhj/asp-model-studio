# ASP Model Studio

Sports Forecasting, Simulation & Model Intelligence

ASP Model Studio is a local, authenticated workbench for developing sports forecasting systems: immutable data evidence, player and team state, event and drive models, simulation, experiments, temporal validation, calibration, model graphs, documentation, and governed model-bundle export.

Phase 1 provides active MLB forecasting and an NFL workflow foundation. College Football, NBA & WNBA, NHL, MMA, and Boxing are presented only as planned sports. Dataset-manifest and model-bundle connections are intentionally honest empty states until later phases.

## Local Quickstart

From this repository root, validate the isolated configuration:

```powershell
.\scripts\start-asp-model-studio.ps1
```

Start the target-local backend and frontend:

```powershell
.\scripts\start-asp-model-studio.ps1 -Start
```

Open [http://127.0.0.1:5274](http://127.0.0.1:5274). The backend listens on `127.0.0.1:8101`. Authentication remains enabled and public registration remains disabled; use a target-local administrator account stored only in the ignored ASP Model Studio runtime.

The launcher keeps application state beneath `.runtime\asp-model-studio` and refuses the protected ports used by adjacent products. Do not point the studio at another repository's databases, artifacts, credentials, or services.

## Focused Verification

```powershell
npx tsc -b --pretty false
npm run test:sports-product
npm run build:modeling
```

## Phase 1 Contracts

- Sports dataset registration: `SPORTS_DATASET_MANIFEST_V1` (connection planned)
- Sports model export: `SPORTS_MODEL_BUNDLE_V1` (no bundle exists until a graph is approved)
- External ASP warehouse: remains external and read-only; no connection is made in Phase 1

Generic authentication, project isolation, dataset identity, analytics, SQL, visualization, documentation, experiment, validation, registry, monitoring, and evidence-lineage machinery remains in place for sports-native development.

## Documentation

The `docs` directory includes inherited platform documentation. Some historical workflow and architecture documents describe the source fork and are retained as provenance; they are not the Phase 1 product surface or local launch instructions.
