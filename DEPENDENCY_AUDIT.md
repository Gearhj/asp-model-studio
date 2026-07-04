# ATLAS Dependency Audit

Date: 2026-07-03

## Summary

`npm audit --json` was run in `C:\Users\james\ds-workflow-starter`.

Result: no npm vulnerabilities were reported.

| Area | Result |
|---|---:|
| Info | 0 |
| Low | 0 |
| Moderate | 0 |
| High | 0 |
| Critical | 0 |
| Total | 0 |
| Production dependencies | 55 |
| Development dependencies | 216 |
| Total package tree | 270 |

No `npm audit fix` was run because there were no npm vulnerabilities to remediate.

## Frontend Dependency Notes

The production build still reports two freshness warnings:

- `baseline-browser-mapping` data is over two months old.
- Browserslist / `caniuse-lite` data is eight months old.

These are compatibility-data freshness warnings, not security vulnerabilities. They should be updated during a controlled dependency refresh, but they do not block a local release candidate.

The build also reports a large chunk warning. Phase 5 added a low-risk route split for the Experimental Design workflow, reducing the main JavaScript chunk from about 1,083 KB to about 805 KB and moving the Experimental Design workflow into its own about 280 KB chunk. Further reduction requires additional page-level extraction or chart/report utility splitting.

## Python Dependency Situation

Two Python dependency files exist:

| File | Purpose | Notes |
|---|---|---|
| `requirements.txt` | Broad/root environment for the full ATLAS local stack | Includes FastAPI, data science libraries, XAI, profiling, document handling, database connectors, MLflow, security/auth, and dev tooling. |
| `server/requirements.txt` | Narrow FastAPI modeling backend | Smaller set focused on API, pandas/numpy, scikit-learn, tree/boosting models, and plotting. |

The files intentionally do not match today:

- Root `requirements.txt` pins newer FastAPI/Pydantic/Uvicorn than `server/requirements.txt`.
- Root includes broader optional packages such as SHAP, LIME, ELI5, Great Expectations, MLflow, document-generation libraries, and database connectors.
- Server requirements are lighter and better suited for backend-only installation.

## Recommended Backend Dependency Plan

For a future hosted deployment, split Python dependencies into explicit files:

| Proposed file | Contents |
|---|---|
| `requirements-server.txt` | Minimal FastAPI modeling/scoring backend dependencies. |
| `requirements-analytics.txt` | Optional SHAP, LIME, EDA profiling, advanced charting, and notebook/export dependencies. |
| `requirements-dev.txt` | Test, formatting, linting, and local-only developer tools. |
| `requirements-all.txt` | Convenience aggregate for local workstations. |

Do not consolidate the current files blindly. The server path should stay deployable without requiring heavy optional packages unless a feature endpoint needs them.

## Security Posture Observed

Implemented safeguards observed in the current codebase:

- Frontend browser-preview upload caps: 25 MB, 250,000 rows, 500 columns.
- Backend upload caps: configurable byte, row, and column limits.
- Local-only CORS defaults are explicit localhost origins, not wildcard origins.
- Report HTML is sanitized before rendering/export.
- Project import validation rejects invalid import structures.
- Local secrets, `.runtime`, `.venv`, logs, build output, and generated caches are excluded from shareable exports through `.gitignore`.
- Decision Journal local persistence is capped to avoid unbounded storage growth.
- Project persistence now has compact and thin fallback writes for quota safety.

## Safe Fixes Applied

No dependency version changes were applied because `npm audit` reported zero vulnerabilities.

Low-risk build-warning mitigation applied:

- Experimental Design route is lazy-loaded from the modeling app shell.

## Remaining Non-Blocking Items

- Run `npx update-browserslist-db@latest` during a scheduled dependency-refresh pass with network access.
- Consider updating `baseline-browser-mapping` during the same refresh.
- Continue page-level Experimental Design extraction to reduce the main bundle further.
- Add a Python vulnerability scanner such as `pip-audit` to the developer toolchain before hosted deployment.
