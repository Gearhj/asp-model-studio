# ASP Model Studio

Sports Forecasting, Simulation & Model Intelligence

ASP Model Studio is a local, authenticated workbench for developing sports forecasting systems: immutable data evidence, player and team state, event and drive models, simulation, experiments, temporal validation, calibration, model graphs, documentation, and governed model-bundle export.

Phase 1 provides active MLB forecasting and an NFL workflow foundation. Phase 2 adds metadata-only registration and bounded read-only analytics for the approved immutable MLB FD1 exchange. College Football, NBA & WNBA, NHL, MMA, and Boxing remain planned sports.

The first plate-appearance feature contract is documented but intentionally blocked: the finalized exchange does not include the package-bound identity bridge required to join Retrosheet plate appearances to canonical Y−1 player priors. No model, predictions, simulation evidence, or export bundle is claimed.

## Local Quickstart

From this repository root, validate the isolated configuration:

```powershell
.\scripts\start-asp-model-studio.ps1
```

Start the target-local backend and frontend:

```powershell
.\scripts\start-asp-model-studio.ps1 -Start
```

To enable the approved immutable exchange, configure the backend-only root in ignored `.env.local` (never in a `VITE_` variable):

```text
ASP_MODEL_EXCHANGE_ROOT=<administrator-controlled neutral exchange root>
```

The browser can request registration of the fixed approved adapter, but it cannot submit or choose a physical filesystem path. Registered partitions are displayed only through `asp-model-exchange://` logical URIs.

Open [http://127.0.0.1:5274](http://127.0.0.1:5274). The backend listens on `127.0.0.1:8101`. Authentication remains enabled and public registration remains disabled; use a target-local administrator account stored only in the ignored ASP Model Studio runtime.

The launcher keeps application state beneath `.runtime\asp-model-studio` and refuses the protected ports used by adjacent products. Do not point the studio at another repository's databases, artifacts, credentials, or services.

## Focused Verification

```powershell
npx tsc -b --pretty false
npm run test:sports-product
npm run build:modeling
```

## Sports Data Contracts

- Consumer adapter: `SPORTS_DATASET_CONSUMER_ADAPTER_V1`
- Sports dataset registration: `SPORTS_DATASET_MANIFEST_V1`
- Plate-appearance feature view: `MLB_PA_FEATURE_VIEW_V1` (`BLOCKED`, not materialized)
- Sports model export: `SPORTS_MODEL_BUNDLE_V1` (no bundle exists until a graph is approved)
- Neutral MLB exchange: external, immutable, and read-only; no data rows are copied into SQLite

Generic authentication, project isolation, dataset identity, analytics, SQL, visualization, documentation, experiment, validation, registry, monitoring, and evidence-lineage machinery remains in place for sports-native development.

## Documentation

The `docs` directory includes inherited platform documentation. Some historical workflow and architecture documents describe the source fork and are retained as provenance; they are not the Phase 1 product surface or local launch instructions.
