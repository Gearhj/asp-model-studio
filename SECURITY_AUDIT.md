# ATLAS Security Audit

Audit date: 2026-07-03  
Scope: local ATLAS workspace security review. No secrets are reproduced in this document.

## Executive Summary

ATLAS is currently suitable for local development and demonstration with sensitive data handled carefully by the user. It is not yet hardened for a hosted multi-user environment. The highest-priority issues are browser storage of dataset samples and governance text, permissive CORS, unrestricted upload size, pickle-based runtime checkpointing, and report rendering that permits existing HTML content.

## Threat Models

### Current Local-Only Threat Model

Assumption: one trusted user runs the frontend and backend on localhost.

Main risks:

- Sensitive data is cached in browser storage or backend runtime checkpoint files.
- Exported reports, notebooks, and model bundles can contain regulated model information.
- Local project state can be lost or corrupted if browser storage is cleared or quota is exceeded.
- Imported project JSON can carry unexpected content.

### Future Hosted Threat Model

Assumption: multiple users, browser clients, uploaded data, governance artifacts, and model outputs are handled by a hosted service.

Additional requirements:

- Authentication and authorization.
- Tenant/project-level access control.
- Server-side persistence with encryption at rest.
- Strict CORS.
- File size/type validation and malware scanning.
- HTML sanitization for any rendered user content.
- Audit log integrity.
- Secure model artifact storage and access controls.
- Secrets management outside repo and client bundle.

## Findings

| Severity | Area | Finding | Evidence | Recommendation |
|---|---|---|---|---|
| High | Browser storage | Dataset samples are saved to `sessionStorage` under `modeling-tool-dataset`, capped at 5,000 rows. This can contain customer data. | `src/lib/localDataset.ts` | Keep only metadata and safe previews in browser. Use backend or IndexedDB with explicit clear controls for larger or sensitive data. Add a visible "Clear local data" control. |
| High | Backend persistence | Backend checkpoint uses pickle and stores raw/processed data, splits, model artifacts, and final model in `.runtime/workflow_checkpoint.pkl`. | `server/core/session_checkpoint.py` | Treat `.runtime` as sensitive local state. Exclude from zips. For production, replace pickle checkpoint with controlled artifact storage and authenticated access. |
| High | CORS | Backend allows local origins and `"*"` while `allow_credentials=True`. | `server/main.py` | Remove wildcard before any hosted deployment. Use explicit origins by environment. |
| High | Upload security | `/api/data/upload_csv` reads the whole file into memory with no size limit and no MIME/extension allowlist enforcement. | `server/main.py` | Add max file size, allowed types, row/column limits, parse timeouts, and clear user-facing errors. |
| Medium | Report rendering | `ReportSectionContent` renders generated HTML using `dangerouslySetInnerHTML`; `renderReportContentHtml` allows content already shaped like HTML to pass through. | `src/components/ReportSectionContent.tsx`, `src/lib/reportFormatting.ts` | Sanitize HTML with a strict allowlist before rendering or exporting. Keep Markdown-to-table conversion but escape raw user HTML by default. |
| Medium | Project imports | Open Project imports JSON from local files and validates shape lightly. | `src/steps/ProjectUtilityPages.tsx`, `src/lib/localProjects.ts` | Add schema validation, versioning, size limits, and reject unknown executable/script fields. |
| Medium | Experiment storage | Experiment tracking stores feature importance, compacted curves, metadata, and notes in `localStorage`. | `src/lib/experimentTracking.ts` | Continue compacting arrays. Add quota-safe writes and project-scoped cleanup. |
| Medium | Decision Journal | Decision journal stores up to 1,000 entries in `localStorage`. Entries may include user rationale and governance text. | `src/lib/decisionJournal.ts` | Add export/clear/archive controls and summarize old entries for model documents. |
| Medium | Secrets | `.env.local` exists locally and is ignored. `.env.modeling` and `.env.scheduling` are checked config files with mode flags. | `.gitignore`, `.env.modeling`, `.env.scheduling` | Keep `.env.local` unshared. If LLM/API keys are added later, keep them server-side only. |
| Low | Dependency review | No dependency vulnerability audit was run in this pass. | `package-lock.json`, `requirements.txt` | Run `npm audit` and Python dependency scanning before release. |
| Low | Generated exports | Notebook, HTML, Markdown, DOC-compatible HTML, CSV, and PKL exports are available. | `src/steps/*Export*`, `server/evaluation/eval_router.py` | Add warning labels for regulated data and strip raw row data unless explicitly requested. |

## Storage Inventory

| Key or mechanism | Storage | Data class | Risk |
|---|---|---|---|
| `ds-workflow-store` | `sessionStorage` via Zustand | Active workflow state | Lost on browser/session clearing; not project registry. |
| `modeling-tool-dataset` | `sessionStorage` | Up to 5,000 dataset rows, headers, target | Sensitive data exposure in browser profile. |
| `atlas-local-projects` | `localStorage` | Recent Projects registry and snapshots | Browser-only persistence; quota risk. |
| `atlas-workflow-node-state:{projectId}:{stepId}` | `localStorage` | Experimental workflow evidence, metrics, compact simulation summaries | Can become large; currently compacted in several places. |
| `modeling-tool-decision-journal` | `localStorage` | Audit trail | Long history, possible sensitive rationale. |
| `modeling-tool-mlflow-lite-experiments` | `localStorage` | Experiment summaries | Must remain compact. |
| `.runtime/workflow_checkpoint.pkl` | Local filesystem | Raw data, splits, artifacts, final model | Sensitive and pickle-based. |

## File Upload and Data Access Review

Current frontend supports CSV and JSON parsing locally. The UI also documents SQL, cloud, existing dataset, and Python loader paths, but those appear to be governed metadata flows rather than live enterprise connectors.

Required hardening:

1. Enforce file size limit before frontend parse and backend upload.
2. Enforce row and column limits with user warnings.
3. Validate file type and parsing mode.
4. Avoid saving raw rows into browser storage by default.
5. Add import schema validation for `.atlas` and `.json` project files.
6. Add explicit local data clearing.

## XSS and HTML Injection Review

One direct `dangerouslySetInnerHTML` usage was found:

| Path | Use |
|---|---|
| `src/components/ReportSectionContent.tsx` | Renders generated report section HTML. |

This is acceptable only if all report content is generated from escaped, trusted builders. Current report utilities escape most table and paragraph values, but `renderReportContentHtml` also allows existing HTML content through when it appears to contain HTML. That is useful for professional report formatting, but it should be replaced by strict sanitization before hosted use.

Recommended fix:

- Add a sanitizer such as DOMPurify for frontend rendering.
- Restrict allowed tags to report-safe tags: `table`, `thead`, `tbody`, `tr`, `th`, `td`, `section`, `p`, `h1`-`h3`, `ul`, `li`, `div`, `span`, `strong`, `br`.
- Reject `script`, event handlers, inline JavaScript URLs, and external iframes.

## Dependency and Supply Chain

Observed dependencies include Vite, React, D3, Zustand, React Router, FastAPI, pandas, scikit-learn, XGBoost, LightGBM, CatBoost, SHAP, Great Expectations, MLflow, and document libraries.

Dependency concerns:

- Root `requirements.txt` and `server/requirements.txt` specify different versions for core packages such as FastAPI, Pydantic, pandas, and scikit-learn.
- Heavy optional packages increase install size and vulnerability surface.
- No lockfile equivalent for Python is currently present.

Recommended commands before any release:

```powershell
npm audit --audit-level=high
pip-audit -r requirements.txt
pip-audit -r server\requirements.txt
```

If `pip-audit` is not installed, install it only in a controlled dev environment.

## Export Security

| Export | Current risk | Recommendation |
|---|---|---|
| Governance report HTML/Markdown/DOC | Can include project context, decisions, SQL text, and model metrics. | Add sensitivity banner and optional redaction mode. |
| Notebook export | Can include generated code and decision notes. | Keep raw data paths as placeholders; never embed row-level data by default. |
| Experiment CSV | Contains model metrics and notes. | Safe for governance, but mark internal. |
| Decision journal CSV/Markdown | Can include all user rationales. | Provide filtered executive export and full audit export separately. |
| Model PKL bundle | Contains executable Python pickle artifact. | Treat as controlled model artifact, not a casual download. |

## Security Readiness

| Environment | Readiness |
|---|---|
| Local trusted demo | Acceptable with caution about sensitive data. |
| Internal single-user desktop | Acceptable if `.runtime`, `.venv`, local exports, and browser data are controlled. |
| Internal shared server | Not ready without auth, storage redesign, CORS hardening, upload controls, and HTML sanitization. |
| External hosted app | Not ready. |

