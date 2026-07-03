# Security and Data Handling

ATLAS is currently optimized for local development. The following controls are required before hosted deployment.

## Local Development Controls

- Keep `.env.local`, `.runtime`, and local secrets out of exports.
- Keep raw customer data out of git.
- Avoid persisting raw datasets to browser `localStorage`.
- Use compact summaries for browser project persistence.
- Validate imported project files before loading.

## File Uploads

File upload controls now enforce:

- Frontend browser-preview limit: 25 MB, 250,000 rows, and 500 columns.
- Backend CSV endpoint limit: configurable by `ATLAS_MAX_UPLOAD_BYTES`, `ATLAS_MAX_UPLOAD_ROWS`, and `ATLAS_MAX_UPLOAD_COLUMNS`.
- Allowed backend extensions: `.csv` and `.txt`.
- Friendly user-facing errors for unsupported types, oversized files, empty files, and excessive row/column counts.

Hosted deployments should add MIME sniffing, malware scanning, upload quarantine, and governed object storage.

## Project Imports

Imported `.atlas` or JSON project files are validated before registry insertion:

- JSON must parse into an object or exported project array.
- Project name and supported project type are required.
- Workflow IDs are validated and reset to a known workflow if needed.
- Invalid current-step references are reset to the first step with a warning.
- Corrupted imports fail gracefully and do not overwrite the active project.

## Report HTML

Generated HTML reports sanitize user-supplied text before rendering. ATLAS removes unsafe tags, JavaScript URLs, and inline event handlers while preserving generated report tables and styling. Reports should avoid raw object dumps and should separate executive summaries from audit appendices.

## CORS

The backend supports explicit local Vite development origins and optional comma-separated `ATLAS_CORS_ORIGINS`. Wildcard CORS is not used by default. Hosted deployments must provide environment-specific origins only.

## Local Data Controls

The Settings page includes local cache clearing for the current project. This removes project-scoped workflow-node evidence and compact browser artifacts. It does not delete exported project files, backend datasets, or external governed data stores.

## Production Readiness

Before hosting:

- Add authentication and authorization.
- Add server-side project persistence.
- Add audit logging with retention controls.
- Add file scanning and upload quarantine if real customer data is used.
- Add HTTPS-only deployment.
- Add secrets management.
