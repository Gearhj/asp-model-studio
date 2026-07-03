# Release Checklist

## Build and Test

- Run `npm run build`.
- Run `npm run build:modeling`.
- Run `npm run test:experimental-design`.
- Start the backend and confirm `/api/health`.
- Smoke test `/dashboard`, `/step00`, `/step01`, `/step02`, and `/workflow/experimental-design/1`.

## Project Boundary

- Confirm ATLAS build does not require Greatest Guitarist entry files.
- Confirm ATLAS backend does not mount STELA routes.
- Confirm standalone project folders contain their own README and package metadata.
- Keep the original `ds-workflow-starter` folder until separated builds are verified.

## Persistence

- Confirm project save works.
- Confirm Recent Projects are listed.
- Confirm no raw datasets or full simulation arrays are written to localStorage.
- Confirm quota errors are displayed inline.

## Documentation

- Generate executive report.
- Generate full audit package.
- Confirm tables render as professional HTML, not raw Markdown.
- Confirm Decision Journal is readable as an audit timeline.

## Security

- Confirm shareable exports exclude `.runtime`, `.env.local`, `.venv`, `node_modules`, `dist`, and logs.
- Confirm upload limits are enforced before hosted deployment.
- Confirm imported project schema validation runs before loading.
