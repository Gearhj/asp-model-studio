# ATLAS Phase 7 User Management, Authentication, Authorization, and Security Controls

## Summary

Phase 7 adds the first governance-ready local authentication foundation for ATLAS. The implementation replaces visible development user switching with sign-in/sign-out, server-side sessions, SQLite-backed users, role-based access checks, dataset/project ACL APIs, audit events, and security diagnostics.

This is a local-development security foundation. It is not SSO, MFA, tenant isolation, FedRAMP, or production hosted security.

## Files Changed

- `server/main.py`
- `server/security/__init__.py`
- `server/security/security_store.py`
- `server/security/security_router.py`
- `server/datasets/dataset_registry.py`
- `server/datasets/dataset_router.py`
- `src/apps/ModelingApp.tsx`
- `src/components/Sidebar.tsx`
- `src/lib/auth.ts`
- `src/lib/datasetLibrary.ts`
- `src/steps/AuthPages.tsx`
- `src/steps/DatasetDetail.tsx`
- `src/steps/DatasetLibrary.tsx`
- `src/steps/NewProject.tsx`
- `src/steps/ProjectUtilityPages.tsx`
- `tests/userManagement.test.mjs`
- `package.json`

## Authentication Design

- Users are stored in SQLite at `server/artifacts/security/atlas_security.db`.
- The backend seeds a local admin:
  - Email: `admin@atlas.local`
  - Local development password: `AtlasLocalDev123!`
- Added auth endpoints:
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `POST /api/auth/logout`
  - `GET /api/auth/me`
  - `POST /api/auth/change-password`
  - password reset stubs
- Frontend routes:
  - `/login`
  - `/register`
  - `/account`
  - `/admin/users`
  - `/audit`

## Password Hashing Design

The local environment did not include `argon2`, `bcrypt`, or `passlib`, so Phase 7 uses salted PBKDF2-HMAC-SHA256 with per-user random salt and high iteration count.

Security Diagnostics intentionally marks this as a warning and recommends argon2id or bcrypt before hosted deployment.

No plaintext passwords are stored.

## Session Design

- Sessions are server-side records in SQLite.
- Browser receives an `atlas_session` cookie.
- Cookie settings:
  - `HttpOnly`
  - `SameSite=Lax`
  - `Secure` when not local development
- Logout revokes the active session.
- Session expiry and last-seen timestamps are tracked.

## RBAC Design

Global roles added:

- `admin`
- `data_steward`
- `model_owner`
- `model_manager`
- `data_scientist`
- `auditor`
- `viewer`

Admin-only user management supports:

- create user
- change role
- disable user
- enable user
- unlock user

## Dataset ACL Integration

- Dataset endpoints require authenticated users.
- Dataset upload/register assigns `ownerUserId` from the authenticated backend user.
- Dataset list filters to owner, shared access, or admin.
- Dataset detail requires read access.
- Dataset versioning and archive require write-level access.
- Dataset detail now includes a sharing panel for owner/admin ACL grants.
- Dataset ACL API:
  - `GET /api/datasets/{dataset_id}/access`
  - `POST /api/datasets/{dataset_id}/access/grant`
  - `POST /api/datasets/{dataset_id}/access/revoke`

## Project ACL Integration

- New Project now attempts to claim owner access for the signed-in user.
- Project dataset linking checks project access and dataset access.
- Project ACL API:
  - `GET /api/projects/{project_id}/access`
  - `POST /api/projects/{project_id}/access/grant`
  - `POST /api/projects/{project_id}/access/revoke`
- Existing browser-only projects can still be opened through the local project registry.

## Audit Logging

Audit events are written for key auth, user, dataset, project, diagnostics, and denied-access actions.

Added audit page:

- `/audit`

Added audit endpoints:

- `GET /api/audit/events`
- `GET /api/audit/events/resource/{resource_type}/{resource_id}`

Audit access is limited to admin/auditor/model-manager roles in this pass.

## Security Diagnostics

System Diagnostics now includes Security checks from the backend security store, including:

- auth enabled
- current user loaded
- user DB reachable
- admin user exists
- session secret configuration
- password hashing configuration
- dataset ACL enforcement availability
- project ACL enforcement availability
- audit logging writable
- hosted Python execution warning

## Migration Notes

- Existing Dataset Library records are preserved.
- Dataset registry cleanup preserves owner grants and normalizes ACL entries.
- A seeded `local-user` admin exists to avoid orphaning legacy local records.
- New projects now attempt a first owner grant immediately after creation.

## Tests Run

- `npm run test:user-management` - passed
- `npm run test:dataset-library` - passed
- `npm run test:data-acquisition` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- Python compile check for security/dataset/main modules - passed
- `npm run build:modeling` - passed
- `npm run build` - passed

Manual backend smoke:

- `GET /api/health` - passed
- `POST /api/auth/login` with seeded admin - passed
- `GET /api/auth/me` with session cookie - passed
- `POST /api/auth/logout` - passed

## Known Limitations

- PBKDF2 is used only because argon2/bcrypt are not installed locally. Hosted deployment should switch to argon2id or bcrypt.
- No MFA, SSO, SAML, OIDC, tenant isolation, or production account recovery yet.
- The user directory is available to authenticated users for dataset sharing convenience; a hosted version should restrict or search-scope that directory.
- Browser Recent Projects are still browser-local records. Project ACL exists in the backend, but full server-owned project registry migration is future work.
- Security diagnostics are practical local checks, not a certification claim.

## Clean-Copy Sync

Synced 19 Phase 7 source, test, and report files to `C:\Users\james\Projects\ATLAS\atlas-app`.

Clean-copy verification:

- `npm run test:user-management` - passed
- `npm run build:modeling` - passed
