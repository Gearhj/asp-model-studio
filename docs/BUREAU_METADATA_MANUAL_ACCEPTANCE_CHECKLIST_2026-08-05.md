# ATLAS Bureau Metadata Catalog Manual Acceptance Checklist

Date: 2026-08-05  
Scope: restricted catalog operationalization baseline plus controlled Data Acquisition integration addendum  
Evidence policy: aggregate metadata and synthetic catalog content only

Evidence-status convention:

- `VERIFIED (automated)` records a completed, machine-checked closeout result.
- An unchecked checkbox remains a genuinely manual acceptance step; automated coverage does not silently check it on the reviewer's behalf.
- A closeout gate is treated as complete only when an explicit final result is recorded.

Historical operationalization closeout status: `READY FOR CONTROLLED CATALOG INTEGRATION`. That earlier phase's 30-minute production-authentication soak, frozen-source hermetic regression, source-safety scan, and protected-authority comparison were verified. They do not validate the subsequently implemented Data Acquisition integration and do not check or waive any manual item below.

Controlled-integration status: **PENDING FROZEN-SOURCE CLOSEOUT**. Sections 1–12 preserve the completed pre-integration operationalization baseline. Section 13 is the new Data Acquisition integration checklist. The historical `READY FOR CONTROLLED CATALOG INTEGRATION` verdict must not be misread as acceptance of the newly implemented integration.

## 1. Purpose and acceptance boundary

Use this checklist to manually verify the provider-neutral Bureau Metadata Catalog service, its administration surface, its entitlement boundaries, and its exact-version restart behavior.

This is not acceptance for live Data Acquisition integration. Passing this checklist authorizes only a later, separately approved controlled-integration phase.

The acceptance operator must stop before any action that would:

- place catalog definitions in Data Acquisition or another Predictive Modeling page;
- change a live project, dataset identity, target contract, predictor authorization, Special-Value Review, Analysis Partition, feature manifest, validation design, workflow completion state, evidence record, or MDD record;
- open or use the sealed final holdout;
- start training, Evaluation, Interpretation, promotion, Scoring, Model Implementation, or Monitoring;
- apply or modify migration 0028 in a live authority;
- start, restart, terminate, reconfigure, or redirect the live backend on port 8001;
- restart the normal Vite development frontend on port 5174; the only live-process exception was the separately authorized, already completed stop of the verified repository-owned Vite process tree documented in Section 10;
- expose a restricted physical path, source filename, complete description collection, or complete special-value collection;
- use real vendor definitions in a screenshot, trace, snapshot, test fixture, or report.

## 2. Acceptance environment

Sections 2 through 9 retain the operator-facing manual checks. Section 10 separately records what the final automated production-authentication run proved; it does not convert visual, keyboard, lifecycle, or reviewer-judgment checks into automatic passes.

### 2.1 Required isolation

- [ ] Use isolated frontend and backend processes on explicitly non-live ports.
- [ ] Use isolated catalog, registry, security, audit, persistence, project, checkpoint, and evidence roots.
- [ ] Use only synthetic catalog definitions for browser and mutating acceptance.
- [ ] Confirm no isolated root overlaps Git, a repository worktree, frontend assets, build output, audit output, uploaded-file staging, Windows Temp when testing durable installation, or a protected live authority.
- [ ] Confirm the production durable-root validator rejects Windows Temp even though a tightly bounded test-only override may host synthetic process acceptance there.
- [ ] Confirm the test-only authentication fixture cannot be enabled through the production application entrypoint.
- [ ] Record isolated process identifiers without recording credentials, cookies, tokens, environment-variable values, or physical restricted paths.

### 2.2 Synthetic acceptance identities

Prepare separate synthetic principals for each case:

| Principal | ATLAS role | Catalog entitlement | Project access | Expected boundary |
| --- | --- | --- | --- | --- |
| Catalog administrator | Administrator | Exact-version administrative grant | As needed for synthetic project tests | May perform authorized catalog administration only |
| Entitled catalog reader | User | Exact-version read grant | None required for catalog-only lookup | May use only granted bounded catalog operations |
| Project user without entitlement | User | None | Synthetic project access | Cannot retrieve restricted catalog definitions |
| Entitled reader without project access | User | Exact-version read grant | None | Cannot inspect a project schema or project crosswalk |
| Unauthenticated principal | None | None | None | Rejected before any catalog metadata is returned |

- [ ] Use different principals for administrator, entitled reader, unentitled project user, and unauthenticated cases.
- [ ] Use at least two tenants or organizations for contamination checks where the environment supports them.
- [ ] Use at least two synthetic exact catalog versions so a fallback would be detectable.
- [ ] Record the expected exact `catalog_version_id` and full checksum in restricted acceptance evidence only.

## 3. Role and entitlement acceptance

### 3.1 Catalog administrator

- [ ] Open the administration catalog surface as an entitled administrator.
- [ ] Confirm the inventory contains only versions entitled to that administrator or organization.
- [ ] Validate one exact version and confirm the response identifies the same `catalog_version_id` and checksum.
- [ ] Grant a narrowly scoped read entitlement to a synthetic reader.
- [ ] Confirm the grant records only the requested operations and exact catalog version.
- [ ] Revoke that entitlement.
- [ ] Confirm the revoked reader is denied immediately and remains denied after restart.
- [ ] Confirm privileged offline installation is restricted to the approved operator path; there is no production registration HTTP endpoint.
- [ ] Confirm validation, retirement, grant, and revoke HTTP requests are each independently authorized by the backend.

### 3.2 Non-admin with a catalog entitlement

- [ ] Attempt to open the administration catalog surface as an entitled non-admin.
- [ ] Confirm the backend returns the established safe authorization response.
- [ ] Confirm no catalog version metadata, validation control, retirement control, grant control, or revoke control is rendered.
- [ ] Confirm client-side route visibility is not used as the authorization decision.
- [ ] Confirm the same principal can use only the bounded lookup operations present in the entitlement.

### 3.3 Project user without a catalog entitlement

- [ ] Give the principal access to a synthetic project but no catalog entitlement.
- [ ] Attempt exact attribute lookup, special-value lookup, and project crosswalk preview.
- [ ] Confirm every restricted operation is denied by the backend.
- [ ] Confirm project access alone does not disclose provider/product/version metadata beyond the existing safe authorization convention.

### 3.4 Catalog entitlement without project access

- [ ] Give the principal an exact-version catalog entitlement but no access to the synthetic project.
- [ ] Confirm ordinary catalog-only operations allowed by the entitlement succeed.
- [ ] Attempt the project-scoped crosswalk preview.
- [ ] Confirm project authorization fails before project schema or crosswalk evidence is returned.

### 3.5 Cross-tenant, cross-user, and cross-project isolation

- [ ] Repeat one cached exact lookup as two users in different tenants.
- [ ] Confirm the second user cannot reuse the first user's entitlement.
- [ ] Confirm a project-A user cannot retrieve project-B crosswalk candidates or decisions.
- [ ] Confirm a catalog version for one provider/product/version is never substituted for another version with an overlapping attribute code.
- [ ] Confirm audit records contain bounded identifiers and outcome metadata, not full descriptions or special-value definitions.

## 4. Exact-version registration and integrity

### 4.1 Inventory identity

- [ ] Select one synthetic registered catalog version by exact `catalog_version_id`.
- [ ] Confirm provider, product, edition, source version, record count, special-value count, checksum prefix, integrity status, installation status, entitlement status, creator, and creation time are present where authorized.
- [ ] Confirm the full physical path, bulk-file reference, unrestricted source filename, and complete catalog are absent.
- [ ] Confirm deterministic ordering and bounded inventory pagination.
- [ ] Confirm an unknown version returns the safe exact-resource response and does not select a first, latest, current, or neighboring version.

### 4.2 Integrity validation

- [ ] Invoke validation for the selected exact version.
- [ ] Confirm the validator evicts or bypasses cached content and recomputes integrity from exact stored bytes.
- [ ] Confirm the returned checksum, record count, and special-value count match the registry identity.
- [ ] Confirm successful validation records `verified` only after all checks complete.
- [ ] In an isolated disposable copy, alter one synthetic catalog byte.
- [ ] Confirm validation fails closed, marks or reports the exact version as failed according to contract, and returns no altered definition.
- [ ] Restore only by creating a new disposable fixture or by the documented isolated repair path; never repair live authority bytes during acceptance.
- [ ] Confirm a checksum mismatch cannot remain served from cache.

## 5. Bounded API acceptance

Run each request with an exact entitled version and record method, route template, status, returned count, and correlation identifier. Do not record restricted response text.

| Operation | Expected manual check |
| --- | --- |
| Catalog-version listing | Bounded offset/limit, deterministic order, entitled versions only |
| Catalog health | Exact version and checksum-aware status |
| Attribute search | Non-empty bounded query, maximum query length, bounded page size, deterministic results |
| Exact attribute lookup | One exact case-normalized code, no similar-code fallback |
| Special-value lookup | Attribute-specific definitions only, bounded and paginated |
| Availability lookup | Exact-version bureau/version availability only |
| Integrity validation | Administrator and exact-version entitlement required |
| Entitlement grant/revoke | Administrator required; bounded operations; durable status |
| Crosswalk preview | Project authorization plus catalog entitlement; candidate-only and read-only |

- [ ] Confirm an empty search is rejected rather than becoming an unbounded catalog listing.
- [ ] Confirm a search query over the maximum length is rejected.
- [ ] Confirm a page size over the maximum is rejected.
- [ ] Confirm a page offset over the maximum is rejected.
- [ ] Confirm each page contains no more than the requested limit and accurately signals whether another page exists.
- [ ] Confirm exact attribute lookup returns one record or a safe not-found result.
- [ ] Confirm special values remain scoped to the exact attribute; no global sentinel dictionary exists.
- [ ] Confirm availability, leveling, and archive metadata remain pinned to the selected catalog version.
- [ ] Confirm no bulk catalog export, download, stream, full-catalog route, or unrestricted copy-all operation exists.

## 6. Administration UI acceptance

### 6.1 Authorized view

- [ ] Open the administration-only catalog route as the entitled synthetic administrator.
- [ ] Confirm the page is explicitly labeled as restricted administration.
- [ ] Confirm the current project and user context are not cleared or changed.
- [ ] Confirm the installed-version list identifies exact versions and never labels one as an implicit latest fallback.
- [ ] Confirm health and lifecycle states are legible at desktop and narrow responsive widths.
- [ ] Confirm search requires a query and displays a bounded page count or range.
- [ ] Confirm Previous and Next controls enforce page boundaries.
- [ ] Confirm exact lookup requires a complete attribute code.
- [ ] Confirm failed search and exact lookup states preserve the current user and selected exact version.
- [ ] Confirm loading, empty, authorization-denial, unavailable, and integrity-conflict states are understandable.
- [ ] Confirm keyboard focus indicators are visible and all actions are reachable without a pointer.

### 6.2 Retirement confirmation

- [ ] Select one disposable synthetic catalog version by exact ID.
- [ ] Select **Retire version**.
- [ ] Confirm no retirement request is sent at the first click.
- [ ] Confirm the page presents a distinct **Confirm catalog retirement** step.
- [ ] Confirm keyboard focus moves to **Confirm retirement**.
- [ ] Select **Cancel** and confirm no state changes.
- [ ] Repeat, select **Confirm retirement**, and record the exact version. Note that the current client does not submit `expected_revision`; the server uses the exact version's current revision.
- [ ] Confirm only that exact version becomes retired.
- [ ] Confirm retirement does not delete catalog bytes or rewrite prior governed lineage.
- [ ] Confirm the retired version is not implicitly selected for new use.
- [ ] Exercise the API/repository stale-`expected_revision` case and confirm it fails with a conflict instead of overwriting current state. Record that this is not currently demonstrable through the administration client.

### 6.3 Unauthorized view

- [ ] Open the same route as a non-admin.
- [ ] Confirm the UI presents the safe administrative-access denial.
- [ ] Confirm version IDs, checksums, search results, exact records, validation actions, retirement actions, and entitlement controls are absent.
- [ ] Confirm manually entering the API route remains denied.

## 7. Governed crosswalk acceptance

- [ ] Use a synthetic project, exact dataset version, exact schema checksum, and exact catalog version.
- [ ] Confirm both project authorization and catalog entitlement are required.
- [ ] Confirm preview results are bounded, reproducible, candidate-only, and not persisted.
- [ ] Confirm the dataset, predictor authorization, feature set, target contract, and workflow state remain unchanged.
- [ ] Confirm a fuzzy or semantically similar name never becomes an authoritative mapping.
- [ ] Confirm the supported mapping states are exactly:
  - `exact_verified`
  - `approved_alias`
  - `transformed_or_derived`
  - `probable_review_required`
  - `ambiguous_review_required`
  - `recoding_evidence_required`
  - `unresolved`
  - `out_of_catalog`
  - `rejected`
- [ ] Confirm approved aliases require reviewer, rationale, actor, timestamp, exact dataset version, exact catalog version, and evidence.
- [ ] Confirm transformed or derived mappings require source attributes, transformation rule, type, units, source system, timing, special-value handling, reviewer, and evidence.
- [ ] Confirm recoded special values require a documented raw-to-modeling recoding chain.
- [ ] Confirm probable and ambiguous candidates remain non-authoritative.
- [ ] Confirm rejected mappings remain historically visible.
- [ ] Confirm optimistic concurrency rejects competing stale revisions.
- [ ] Confirm no vendor special-value meaning is applied before an exact or approved governed mapping exists.
- [ ] Confirm target fields and deterministic target-source fields remain excluded from predictor mapping.
- [ ] Confirm no holdout rows or holdout targets are opened or accessed.

## 8. Restart and durable recovery

Use only the isolated backend process.

- [ ] Record the isolated listener PID before restart.
- [ ] Record one active exact version ID, checksum, integrity status, entitlement ID/status, and one retired disposable version.
- [ ] Stop the isolated backend and confirm the old listener is closed.
- [ ] Start a new isolated backend process from the same source and isolated authority.
- [ ] Confirm the new listener PID differs from the old PID.
- [ ] Confirm isolated health returns HTTP 200.
- [ ] Retrieve the active catalog by the exact recorded `catalog_version_id`.
- [ ] Confirm the full checksum, record count, special-value count, and integrity state match the pre-restart authority.
- [ ] Confirm the entitled reader still has only the recorded operations.
- [ ] Confirm the revoked reader remains denied.
- [ ] Confirm the retired version remains retired and is not selected for new use.
- [ ] Confirm a non-admin remains denied after restart.
- [ ] Confirm recovery did not use first-version, latest-version, browser-storage, checkpoint, or anonymous-scope fallback.
- [ ] Confirm the live backend listener PID did not change and the intentionally stopped normal Vite listener was not restarted.

## 9. Synthetic screenshot and DOM guidance

Screenshots and traces must use synthetic catalogs only.

- [ ] Use visibly synthetic provider, product, edition, attribute codes, descriptions, ranges, and special values.
- [ ] Capture the authorized admin surface with exact-version identity, integrity state, bounded search, and exact lookup visible.
- [ ] If capturing retirement, stop at the confirmation view or use a disposable synthetic version.
- [ ] Capture the non-admin denial only if it contains no version metadata.
- [ ] Inspect the DOM and screenshot text for physical paths, environment-variable values, source filenames, bulk references, credentials, cookies, tokens, and real vendor descriptions.
- [ ] Store only the sanitized screenshot artifact, not a browser profile or authenticated trace.
- [ ] Do not attach unrestricted network response bodies.

Accepted sanitized screenshots from prerequisite production-authentication run `production-auth-29bc67f62a70441cad85568724a6ce39`:

1. `production-auth-admin-initial.png`
2. `production-auth-admin-reload.png`
3. `production-auth-unauthenticated-denial.png`
4. `production-auth-role-denial.png`
5. `production-auth-entitlement-denial.png`
6. `production-auth-project-alpha-isolation.png`
7. `production-auth-project-beta-isolation.png`

All seven screenshots contain synthetic content only. The acceptance asserted that restricted details were absent. Only the sanitized screenshots and bounded summaries are retained as acceptance evidence; browser profiles, authentication material, unrestricted traces, and response bodies are not checklist artifacts.

## 10. Automated closeout evidence and final release gates

### 10.1 Prerequisite production-authentication run — `VERIFIED (automated)`

Run ID: `production-auth-29bc67f62a70441cad85568724a6ce39`

This run used a non-HMR production build served by an isolated static frontend on port 15184 and an isolated backend on port 18127. Its isolated authorities covered persistence, security, audit, catalog registry and restricted catalog storage, installation journal, project and dataset registries, project links, Dataset Library, workflow checkpoints, evidence, documentation, feature manifests, model registry, temporary files, browser state and downloads, test output, logs, and frontend build output.

| Automated gate | Verified result |
| --- | --- |
| Production build | Passed; 138 files, HMR markers absent |
| Initial authentication readiness | The first protected route waited for resolved authentication before issuing project or catalog work |
| Headed browser execution | Passed |
| Authenticated reload recovery | 20 of 20 reloads restored the expected user and entitlement |
| Synthetic identity coverage | 5 users, 2 providers, and 2 projects |
| Project-A and project-B own-identity checks | 12 successful exact own-project retrievals |
| Cross-project authorization | 12 backend denials with zero cross-project content leaks |
| Cross-user, cross-project, and cross-provider contamination | Zero detected |
| Unauthenticated behavior | HTTP 401 before any catalog request or metadata disclosure |
| Non-admin administration route | Role gate denied access without issuing a catalog request |
| Administrator lacking the exact entitlement | HTTP 403 |
| Fetch/XHR network guard | 89 of 89 requests reached only the isolated backend |
| Live-port or unexpected network contact | Zero live-port contacts, zero unexpected fetch/XHR requests, zero WebSockets, and zero blocked requests |
| Restricted-detail exposure | None detected |
| Isolated audit evidence | Bounded, path-free audit schema verified for success and expected-denial outcomes |
| Live authorities opened by the run | No |
| Live services touched by the run | No |
| Source or Git mutated by the run | No |

The strict authenticated-reload evidence was independently validated as soak-compatible. It records two synthetic project bindings and zero user, project, or provider contamination without exposing credentials, browser state, or restricted catalog text.

### 10.2 Authorized normal-frontend shutdown — `VERIFIED (automated)`

Before termination, listener ownership was checked using the PID, executable, command line, and working directory. Only the repository-owned Vite development process tree serving port 5174 was stopped.

| Shutdown evidence | Verified result |
| --- | --- |
| Stopped listener PID | `86880` |
| Sanitized process command | Repository-owned `vite --host 127.0.0.1 --port 5174` development command |
| Repository ownership | Verified before stop from listener, executable, command line, and working directory |
| Port 5174 after stop | No listener |
| Normal Vite restart | Not performed; port 5174 remains intentionally unavailable for this closeout |
| Live backend on port 8001 | PID `89928` remained running, healthy, and untouched |
| Unrelated processes | No unrelated Node, browser, Python, editor, or user process was stopped |

### 10.3 Final automated gates — `VERIFIED (automated)`

All required automated gates passed from the unchanged 956-file source freeze with aggregate SHA-256 `6415bdd48d462a74a61631b6dc991c4ecb160060ab212626dcef3876ef17d366`. The manual items in Sections 2 through 9 and Section 12 remain unchecked.

| Closeout gate | Verified result | Acceptance consequence |
| --- | --- | --- |
| Integrated production-authentication soak | Run `production-auth-f7c4f1d2fe374aec8586e1e8ed85d038` passed: 1,800.031-second timed soak, 2,024.75-second parent window, 2,238.266-second total run; 13,379 requests, 13,042 successes, and 254 expected denials | Sustained isolated runtime, authentication, entitlement, restart, and reload requirements verified |
| Workload and isolation | 11,110 bounded operations, 1,290 previews, 623 writes; 25 users, 10 projects, 3 versions; 10 actual isolated backend restarts, 11 unique PIDs, and 60 of 60 authenticated reloads | Zero unexpected failures, timeouts, contamination, duplicate revisions, entitlement inconsistencies, unexpected checksum/restart-recovery failures, leaks, or live contacts |
| Integrated performance and integrity | p50 381.3138 ms, p95 704.0152 ms, maximum 3,061.4139 ms; 3 expected tamper checksum failures detected; cache occupancy 3 of 4 | Required performance and integrity gates passed; RSS and file-handle deltas were unavailable and are not reported as zero |
| Isolated production build | 138 files; checksum `6516eb36f4749d451888576615dbe5d48cb0408535fda80aa8178acadad7364c`; no HMR; bounded evidence checksum `bfa704743967529bf22e21362c95a1ae549769ded517ba97c897acdb4ba8b084` | Browser acceptance used only the isolated frontend/backend pair |
| Catalog regression | `atlas-hrt-20260805-235516-a26176946f`: 14 of 14 suites and 148 of 148 tests, zero failures | Catalog implementation gates verified |
| Cross-phase regression | `atlas-hrt-20260805-235519-0922951dac`: 12 of 12 suites, 83 tests and 15 subtests, zero failures, 36 warnings | Relevant workflow contracts verified |
| Frontend regression | `atlas-hrt-20260805-235532-5c2b87adde`: 18 of 18 suites, 210 tests plus 2 legacy checks, zero failures, 2 expected warnings | Administration and cross-phase frontend contracts verified |
| Hermetic harness/Node guard | `atlas-hrt-20260805-235523-453681edc3`: 5 of 5 suites; 18 Python, 14 Node, and 15 semantic tests; 8 subtests; 2 probes; 1 intentional skip | Hermetic launcher and pre-import guards verified |
| Security gate | `atlas-hrt-20260806-000857-c6be774714`: 62 tests plus 30 structural assertions, zero failures, 6 warnings | Authentication, authorization, and source-contract gates verified |
| Storage scanner and guard | Scanner `atlas-hrt-20260806-000539-164dcdfa98` inspected 113 sources with zero findings; guard `atlas-hrt-20260806-000711-38a941108a` passed 24 of 24 tests | Storage isolation verified |
| Compilation/build/repository checks | TypeScript, isolated production build, Python compilation, and `git diff --check` passed; Git index empty | Final frozen-source toolchain gates verified |
| Expanded source-safety scan | Zero findings across 2,120 tracked paths, 1,697 text files, 311 candidate documentation/test files, 78,558 fingerprints, 244 of 244 OCR images, and zero image matches | No tracked proprietary corpus or unsafe exposure detected |
| Final layered protected-authority comparison | Passed with 0 authoritative and 0 supplementary changes across 396 immutable and 5 SQLite authorities; audit counts remained 18,358 and 20,618 | Live protected state remained unchanged |
| Final closeout verdict | `READY FOR CONTROLLED CATALOG INTEGRATION` | A separately authorized controlled-integration phase may begin; this checklist does not begin it |

The exact HELOC identity, Analysis Partition revision 1, and development/final-holdout counts 5,020 / 1,255 remained unchanged. The sealed holdout was not accessed. Migration `0028` remained unapplied and unchanged at SHA-256 `2256c1afd0ee4b8667dcadca4422950b29144a7745b48394e83d1c2b72f672c8`. Live backend PID `89928` remained untouched; ports `5174`, `15184`, and `18127` were closed at final verification. Final Git classification was 64 modified tracked paths, 68 untracked paths, zero staged paths, and zero deleted paths; the vendor PDF/CSV remained untracked and present.

## 11. Failure capture and stop rules

Stop the affected scenario immediately if any of these conditions occurs:

- expected checksum or aggregate counts differ;
- a storage root resolves inside a prohibited location;
- an exact-version request selects a different version;
- a non-entitled principal retrieves restricted metadata;
- cache content crosses user, tenant, project, provider, product, or version boundaries;
- a catalog or crosswalk response exposes a physical path or bulk reference;
- a fuzzy, probable, ambiguous, or recoding-required mapping becomes authoritative without required evidence;
- a live protected authority changes;
- a request accesses the sealed final holdout;
- migration execution would apply migration 0028 live;
- real vendor content appears in a screenshot, trace, fixture, report, frontend asset, or Git-controlled output.

Capture only the following sanitized failure evidence:

| Field | Safe value to record |
| --- | --- |
| Scenario and checklist step | Human-readable step name |
| Operation | Method and route template or service operation |
| Actor | Synthetic or opaque principal ID |
| Catalog identity | Safe catalog ID and exact version ID |
| Project/dataset identity | Synthetic or already approved opaque IDs only |
| HTTP status | Numeric status |
| Safe structured error | Error code and generic message only |
| Correlation ID | Opaque server-generated ID |
| State changed | Yes, no, or unknown |
| Restricted content exposed | Yes or no; do not reproduce it |
| Protected authority changed | Yes, no, or unverifiable |
| Backend PID | Isolated PID only |

- [ ] Do not print the restricted record involved.
- [ ] Do not silently repair, restore, delete, or overwrite a failed authority.
- [ ] Preserve sanitized evidence and report the exact failed boundary.
- [ ] Continue an independent scenario only when the failure cannot invalidate it.

## 12. Closeout and explicit stop

- [ ] Confirm every screenshot contains synthetic content only.
- [ ] Confirm no complete vendor description or special-value collection entered Git-controlled output.
- [ ] Confirm no bulk export or browser-accessible physical path was created.
- [ ] Confirm the source catalog was not moved or deleted.
- [ ] Confirm the live HELOC authorities and Analysis Partition are unchanged.
- [ ] Confirm the sealed holdout was not accessed.
- [ ] Confirm no training, Evaluation, Interpretation, promotion, Scoring, Model Implementation, or Monitoring occurred.
- [ ] Confirm migration 0028 was unchanged and unapplied live.
- [ ] Confirm live security controls were not weakened.
- [ ] Confirm isolated processes are stopped and their ports are closed.
- [ ] Confirm the live backend PID did not change and the normal Vite frontend remained intentionally stopped after its authorized closeout shutdown.
- [ ] Confirm the uninterrupted 30-minute operational soak completed successfully; automated evidence status is `VERIFIED (automated)`.
- [ ] Confirm the complete hermetic regression and security/storage/build gate completed successfully; automated evidence status is `VERIFIED (automated)`.
- [ ] Confirm the final layered protected-authority comparison completed with no authoritative change; automated evidence status is `VERIFIED (automated)`.
- [ ] Confirm no catalog definition was integrated into Data Acquisition or any Predictive Modeling workflow page.
- [ ] Stop. Do not begin controlled catalog integration without a separate explicit authorization.

The final two Section 12 items are retained as historical operationalization-boundary checks. Controlled integration was subsequently authorized; use Section 13 for the current product acceptance and do not re-check those historical stop items as if integration had not occurred.

## 13. Controlled Data Acquisition integration addendum

Status: **PENDING FROZEN-SOURCE CLOSEOUT AND MANUAL REVIEW**

### 13.1 Automated prerequisites — closeout owner

- [ ] Record the exact frozen-source hash/manifest used by every final gate.
- [ ] Run the complete required backend and frontend regression exclusively through approved hermetic/isolated paths.
- [ ] Run security and storage-isolation gates and record exact counts and runtimes.
- [ ] Run TypeScript compilation, production build, Python compilation, and final `git diff --check`.
- [ ] Complete isolated production-browser acceptance with synthetic catalog content only.
- [ ] Complete a new uninterrupted integration-specific soak of at least 30 minutes; do not reuse prior operationalization soak time.
- [ ] Record summary/batch/search/crosswalk latency, payload, query-count, and cache measurements; do not report unavailable memory or handle values as zero.
- [ ] Complete the layered protected-authority comparison, including live audit row counts.
- [ ] Confirm the live HELOC project, exact dataset/version, target, and Analysis Partition revision/membership/checksums are unchanged.
- [ ] Stop isolated services and verify every isolated port is closed.
- [ ] Confirm port `5174` remains closed and the live backend on `8001` was untouched.
- [ ] Confirm migration `0028` remained unchanged and unapplied live.
- [ ] Confirm the Git index is empty and no prohibited Git operation occurred.

### 13.2 Exact binding and entitlement

- [ ] Open an isolated synthetic Data Acquisition project with an exact active Dataset Library version.
- [ ] Confirm `Bureau Metadata Binding` is compact and appears for bureau context or explicit review without duplicating the page.
- [ ] Confirm the selector lists only explicitly entitled exact catalog versions.
- [ ] Confirm no first/latest, display-name, cached-browser, cross-project, or cross-tenant fallback occurs.
- [ ] Confirm `Preview exact binding` is nonmutating and shows exact integrity, entitlement, and version context.
- [ ] Confirm `Confirm exact binding` requires an analyst rationale and exact optimistic revision.
- [ ] Confirm an identical retry is idempotent and a stale revision produces a safe structured conflict.
- [ ] Confirm a user without entitlement sees no restricted description, special-code definition, catalog count leakage, or physical storage path.

### 13.3 Governed crosswalk

- [ ] Confirm initial server-generated candidates are review-required or unresolved; none is automatically authoritative.
- [ ] Verify all nine states render: exact verified, approved alias, transformed/derived, probable review required, ambiguous review required, recoding evidence required, unresolved, out of catalog, and rejected.
- [ ] Confirm exact and alias authority requires explicit analyst confirmation and supporting evidence.
- [ ] Confirm generic HELOC-style fields remain unresolved without defensible lineage or recoding evidence.
- [ ] Confirm target, deterministic target-source fields, excluded predictors, and derived fields cannot masquerade as raw provider attributes.
- [ ] Confirm decision save appends immutable crosswalk history and pins the exact crosswalk ID/revision in a new binding revision.
- [ ] Confirm governance-persisted/binding-failed and binding-persisted/documentation-failed cases return explicit partial metadata state rather than success.
- [ ] Confirm `binding-link` retry closes the exact partial state idempotently.
- [ ] Confirm no crosswalk action changes dataset values, target contract, predictor authorization, Analysis Partition, feature manifest, or treatment.

### 13.4 Table-first Special-Value Review

- [ ] Confirm the existing Special-Value Review remains table-first; the old Variable Navigator is not reintroduced.
- [ ] Confirm observed counts, burden, event behavior, treatment selection, rationale, and review status remain usable with no catalog mapping.
- [ ] Expand a mapped row and confirm these sources are visually distinct: `Provider catalog definition`, `Analyst-approved crosswalk`, `Dataset-observed behavior`, `ATLAS heuristic`, and `Unverified candidate`.
- [ ] Confirm an unresolved row says: `No authoritative catalog mapping is available for this field. Observed behavior remains available without assigning a provider meaning.`
- [ ] Confirm true nulls, provider special values, ordinary values, outliers, and parse failures remain distinct.
- [ ] Confirm catalog metadata never silently selects, applies, confirms, or materializes a treatment.
- [ ] Confirm selecting mappings or expanding rows does not reload the route, lose scroll position, or reset target/predictor/partition state.

### 13.5 Consistency and downstream handoff

- [ ] Confirm consistency results distinguish consistent, unused provider codes, review required, contradictory, metadata unavailable, and mapping unresolved states.
- [ ] Confirm contradictory datatype/range/code evidence blocks metadata-derived recommendations.
- [ ] Confirm provider-defined but unobserved codes are described as unused, not fabricated as observed.
- [ ] Confirm the canonical annotation identity pins exact dataset version, schema, catalog, binding, crosswalk, and checksums.
- [ ] Confirm only analyst-confirmed exact/alias decisions expose provider-authoritative definitions.
- [ ] Confirm EDA accepts the same exact current annotation identity, treats optional absence as nonblocking, and rejects stale/contradictory metadata.
- [ ] Confirm Outliers, Missing Values, and Feature Engineering do not query or embed the full catalog and do not treat unresolved/unentitled metadata as authority.
- [ ] Confirm no holdout request occurs and no Analysis Partition revision is created.

### 13.6 Evidence, MDD, and manual live review for James

- [ ] Confirm successful binding/crosswalk completion records bounded Evidence Center and MDD references before the UI reports success.
- [ ] Confirm evidence includes exact identities, checksums, revisions, actor, timestamp, bounded counts, and treatment limitations without embedding the complete provider catalog.
- [ ] After automated closeout, James starts the normal frontend manually; automation must not restart port `5174`.
- [ ] Open the HELOC Data Acquisition page and confirm the exact dataset/version and Analysis Partition revision 1 remain current.
- [ ] Confirm generic HELOC names were not assigned fabricated provider mappings.
- [ ] Confirm observed special-value treatments remain available and table-first.
- [ ] Confirm viewing the page alone creates no binding, crosswalk, treatment, predictor, feature-manifest, or partition revision.
- [ ] Navigate to EDA and confirm exact dataset/version/target/partition identity plus bounded metadata identity.
- [ ] Stop before training, Evaluation, Interpretation, promotion, Scoring, Implementation, or Monitoring.

Controlled-integration reviewer: ____________________  
Review date/time: ____________________  
Result: `PASS` / `FAIL` / `BLOCKED`  
Sanitized evidence reference: ____________________  
Notes: ____________________

Manual reviewer: ____________________  
Review date/time: ____________________  
Result: `PASS` / `FAIL` / `BLOCKED`  
Sanitized evidence reference: ____________________  
Notes: ____________________
