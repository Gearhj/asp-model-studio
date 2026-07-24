# ADR: ATLAS Data Asset Lifecycle

Status: Accepted (this stage). Extends `docs/DATASET_LIBRARY.md` (the v1 storage/access reference) with the
end-to-end lifecycle contract: what happens to a dataset from upload through registration, versioning,
linking, transformation, scoring, and deletion.

## Why this exists

The Predictive Modeling browser audits uploaded real development data into project workspace state and
never saw it in the Dataset Library, because nothing ever called dataset registration. That gap is not a bug
in isolation — the architecture already distinguishes "project workspace upload" from "registered Library
asset" — but the distinction was never surfaced to the user, and the concrete registration action for an
already-uploaded workspace dataset did not exist (`POST /datasets/register` only ever created an empty
metadata shell with zero versions; the only paths that attached real data to a Library asset were the
Library's own direct-upload endpoint and the Step10 scored-output registration). This ADR defines the
contract and this stage implements the missing registration path.

## Asset classes

### 1. Project workspace upload
A CSV loaded via Data Acquisition into `DATASTORE` (`server/core/dataset_store.py`), scoped to
`(owner_user_id, project_id)`. Lives only in server memory plus the debounced JSON checkpoint
(`server/core/session_checkpoint.py`, Stage 6.1 lifecycle). **Not visible in the Dataset Library.** Deleted
when the project is deleted (`discard_modeling_scopes`), unless explicitly registered first. Cannot be
reused by another project — there is no cross-project reference to a DATASTORE scope.

### 2. Registered Dataset Library asset
A durable record in `server/artifacts/datasets/registry.json`, `datasetId`-keyed, owned by a user
(`ownerUserId`), with an `access` grant list (owner/editor/viewer/auditor) and one or more versions on disk
under `server/artifacts/datasets/<datasetId>/versions/<versionId>/`. Survives project deletion. May be
linked to multiple projects via `project_links.json`. This stage adds the action that creates one of these
from the *current project's workspace upload* (previously only reachable via a separate direct-to-Library
upload or a scored-output registration).

### 3. Project-owned registered dataset — resolved: not a separate category
The audit asked whether ATLAS needs a distinct "project-owned but Library-visible" class. It does not: a
registered asset already carries its own `ownerUserId` independent of any project, and `linkedProjects` is
a many-to-many join, not ownership. Introducing a second ownership concept would create exactly the kind of
lifecycle ambiguity this stage exists to remove. Decision: **one asset-ownership model** (the registering
user owns the asset; projects link to it). Deleting the project that happened to register an asset never
deletes or transfers the asset — ownership was never project-scoped to begin with, so there is nothing to
transfer.

### 4. Dataset version
Immutable once created: `versionId`, `rowCount`, `columnCount`, `createdAt`, `createdBy`, content `hash`
(sha256), and `schema.json`/`profile.json`/`preview.json`/`lineage.json` artifacts. `lineage.json` records
`sourceType`, `datasetRole`, `registeredBy`, `registeredAt`, and a `sourceInfo` bag (this stage populates it
with the originating project id, upload filename, and target column for workspace-registered datasets — see
Phase 6 below). Versions are never mutated in place; a new upload to an existing dataset creates a new
version via `POST /datasets/{id}/versions`.

### 5. Transformed / feature-engineered dataset
Outlier treatment, missing-value handling, encoding, scaling, and feature materialization all mutate
`DATASTORE.processed_df` in place (project workspace state) and are **never** silently promoted to the
Library. A user who wants a governed, versioned copy of a transformed dataset must explicitly register it
via the same Data Acquisition registration action, using whatever `DATASTORE` currently holds — no new
mechanism was needed for this since registration always operates on the current workspace state, transformed
or not, at whatever step the user chooses to register. (No new server-side change was required for this
class; it was already correct once the registration path exists.)

### 6. Scored dataset
Registered via the existing `POST /scoring/register-scored-dataset` (`server/scoring/scoring_router.py`),
which already records model name, task, dataset type (TEST/OOT/train), column roles, and row scope in
`sourceInfo`. This stage fixes a missing authorization check on that endpoint (below) but leaves its data
contract unchanged since it already matched Phase 3 item 6's requirements.

### 7. Export file
Out of scope for change this stage — ATLAS's export endpoints (diagnostics CSV/PDF, evidence exports)
already produce standalone files without registering them as Library assets, which matches the desired
contract. No code changes were needed for this class.

## Deletion and retention rules (Phase 7) — as implemented this stage

| Scenario | Rule | Status before this stage | Status after |
|---|---|---|---|
| Delete project with only a workspace upload | Workspace state (`DATASTORE`/`RESULTS` scope) deleted via `discard_modeling_scopes`; no Library asset ever existed | Correct (Stage 6.1) | Unchanged |
| Delete project linked to a shared Library asset | Remove the project's link only; asset and other projects' links survive | **Defect**: link was never removed — `persistence_router.delete_project` never called dataset-link cleanup, leaving `project_links.json` entries pointing at a project that no longer exists | **Fixed**: `delete_project` now calls `unlink_project_dataset_links(project_id)` for every dataset linked to the deleted project |
| Delete the project that originally registered an asset | Asset is never cascade-deleted; ownership stays with the registering *user*, not the project, so there is nothing to reassign | Correct by construction (ownership was already user-scoped) | Unchanged, now explicitly documented (this ADR) |
| Delete a Library asset | Requires an explicit Library action (`POST /datasets/{id}/archive`); archived assets are excluded from listings and from `require_dataset`, so they become unreachable from new links while remaining on disk for existing lineage/version history | Exists (archive-only, no hard delete) | Unchanged — archive-only is the correct conservative default; a hard-delete-with-dependency-review action is a documented future gap (see Governance Gaps in the final report), not built this stage |
| Delete a registered scored asset | Same archive path as any other asset; removing it does not touch the source dataset or model artifacts (no reverse foreign key exists from model → scored asset) | Correct by construction | Unchanged |
| User deletion | No user-deletion endpoint exists anywhere in the product (confirmed in Stage 6.1's audit). Documented required future policy: ownership should transfer to an admin or a "deleted user" placeholder rather than leaving `ownerUserId` dangling; shared datasets must not silently disappear from other users' authorized project views | N/A | Documented only — no administration system built this stage, per the brief's explicit exclusion |

## Authorization gaps found and fixed

Two confirmed defects, both "any authenticated user can act on a project they don't own" holes:

1. `POST /scoring/register-scored-dataset` called `link_project()` directly with a client-supplied
   `projectId` and no check that the caller can edit that project — fixed by adding
   `authorize_modeling_scope(user, projectId, "edit")` before linking.
2. `DELETE /projects/{project_id}/datasets/{dataset_id}` (unlink) had no authorization check at all — any
   authenticated user could sever another user's project-dataset link by ID — fixed by adding
   `user_can_access_project(project_id, write=True)`.

`GET /projects/{project_id}/datasets` was left unauthenticated-by-project (any authenticated user can query
any project's link list) because the underlying data is already filtered per-dataset by
`user_can_access()` inside `project_dataset_links()` — a caller without dataset access learns only that
*some* dataset is linked, never its contents, name, or schema. Tightened to require at least project-view
access, since project ID enumeration of link counts is still an unnecessary leak.

## Frontend contract (Phase 4)

Data Acquisition gained a **Dataset Persistence** section directly under Target Setup (no separate
"How to Choose" accordion, per the brief) with two inline choices:

- **Project Workspace Only** (default) — "Use this dataset only in the current project. It will not appear
  in the Dataset Library unless you register it later."
- **Register in Dataset Library** — "Create a governed, versioned data asset that authorized projects can
  reuse." Selecting this reveals name/description/tags fields (owner, source, and target are inferred, not
  re-asked), a duplicate-check that surfaces existing likely-matching assets as a reviewable suggestion
  (never an automatic substitution), and a "Register Development Dataset" button. On success the page shows
  the new `datasetId`/`versionId`, a link to open it in the Dataset Library, and confirms the current project
  is now linked.

Default is Project Workspace Only, matching the brief's stated default and the existing product convention
that nothing is promoted to a shared registry without an explicit action.
