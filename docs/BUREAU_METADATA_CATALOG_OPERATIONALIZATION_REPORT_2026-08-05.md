# ATLAS Bureau Metadata Catalog Operationalization Closeout Report

Date: 2026-08-05  
Repository: `<repository-root>`  
Scope: Bureau Metadata Catalog operationalization closeout only  
Document state: **FINAL - AUTOMATED CLOSEOUT COMPLETE**  
Current verdict: **READY FOR CONTROLLED CATALOG INTEGRATION**

All required automated closeout gates passed from the unchanged frozen source state. The final integrated production-authentication soak, complete hermetic regression matrix, expanded source-safety scan, final protected-authority comparison, isolated-process shutdown, and repository checks are recorded below. Historical interrupted or supporting runs remain documented as history and are not substituted for the final integrated result.

This report is aggregate-only. It omits complete licensed descriptions, complete special-value definitions, unrestricted record dumps, browser profiles, credentials, secrets, and physical restricted-storage paths. Synthetic acceptance identifiers and approved opaque HELOC lineage identifiers are included only where required to establish the acceptance boundary.

## Executive closeout status

| Gate | Status | Evidence or blocker |
| --- | --- | --- |
| Existing catalog implementation preserved | Completed | Foundation, durable installer, exact registry, entitlement, bounded API, crosswalk governance, and admin surface remain present |
| Repository safety snapshot | Completed | Branch/HEAD, ten-entry Git history, patch, manifests, authority baselines, listener inventory, and migration evidence preserved externally |
| Repository-owned Vite removal | Passed | Listener PID `86880` and its repository-owned command tree stopped; port `5174` closed |
| Live backend isolation | Passed | PID `89928` remained running and untouched |
| Isolated authority map | Passed | 21 mutable authorities resolved canonically, were non-reparse, mutually distinct, and did not overlap the repository or a live authority |
| Production-build authentication readiness | Passed | Prerequisite run `production-auth-29bc67f62a70441cad85568724a6ce39` |
| Integrated production-authentication soak | Passed | Final run `production-auth-f7c4f1d2fe374aec8586e1e8ed85d038`; 1,800.031-second timed soak |
| Full hermetic regression matrix | Passed | Every required manifest and compilation/build check completed without failure |
| Expanded source-safety scan | Passed | Zero findings across tracked text, candidate documentation/tests, fingerprints, OCR, and images |
| Final post-regression semantic comparison | Passed | Zero authoritative changes and zero supplementary changes |

## 1. Initial repository state

The closeout safety snapshot recorded:

| Item | Captured value |
| --- | --- |
| Branch | `codex/phase2a-canonical-lineage` |
| HEAD | `938c5b1e2d5b4f81f2b35acc11a048a9b8a04d62` |
| Upstream | `origin/codex/phase2a-canonical-lineage` |
| Git index | Empty |
| Modified tracked paths | 62 |
| Untracked file paths | 54; the short-status view collapsed these into 37 entries |
| Conflict or deletion detected | None in the captured manifests |
| Pre-existing path removed by this closeout | None detected |

The working tree was already substantially dirty. Existing changes were treated as James's work and preserved. The external safety directory contains, by safe filename, `branch-head.txt`, `git-log-10.txt`, `working-tree.patch`, `tracked-change-manifest.txt`, `untracked-file-manifest.txt`, `task-file-classification.csv`, a sanitized catalog aggregate, HELOC identity and partition snapshots, logical database baselines, audit baselines, a protected-authority manifest, migration evidence, and listener/process evidence.

No Git staging or history operation was performed. Final verification found 64 modified tracked paths, 68 untracked paths, zero staged paths, and zero deleted paths; the two never-stage vendor inputs remained untracked and present.

## 2. Prior runtime-isolation failure

The preceding acceptance attempt stopped under the protected-authority invariant because 12 generic `access.denied` rows were appended to a live audit authority. This was a real runtime-isolation failure even though the denials were correct security behavior.

The investigation found no change to the HELOC project, dataset, dataset version, Analysis Partition, target contract, predictor authorization, catalog authority, entitlement, user, role, session, feature manifest, evidence record, MDD record, or other governed workflow state. All 32 previously compared HELOC logical fields remained unchanged.

The incomplete workload from that attempt reached 811.985 seconds, 12,177 requests, 1,098 crosswalk previews, 393 decision writes, and 13 restart/reload cycles with no unexpected workload failure. It is retained only as forensic history. Its elapsed time and operations are not credited to the required fresh soak.

## 3. Exact HMR root cause and audit explanation

The live audit rows were caused by a shared hot-reload path:

1. `AdminConsole.tsx` and `ModelingApp.tsx` were saved.
2. The already-running Vite development server detected those changes.
3. A connected live browser tab hot-reloaded automatically.
4. Before the browser had restored its authenticated application context, it called protected live-backend endpoints.
5. The live backend correctly rejected the unauthenticated requests and appended the denials to its audit authority.

The backend authorization and audit controls therefore behaved as designed. The defect was environmental coupling: mutable development source, a live HMR server, an open live browser, and the live backend were part of the same acceptance path. The closeout does not allowlist those audit rows and does not weaken authentication, authorization, or audit behavior to avoid them.

## 4. Runtime-isolation correction and authorized Vite stop

James explicitly authorized stopping only the repository-owned Vite process tree serving port `5174`. Ownership was checked from the listener, executable, absolute repository module path, sanitized command, and served source before termination. The process working directory was checked operationally but was not independently persisted in the sanitized evidence; the absolute module path is the durable ownership evidence.

| Evidence field | Result |
| --- | --- |
| Listener PID | `86880` |
| Executable | Node.js runtime |
| Sanitized command | `node <repository>\node_modules\vite\bin\vite.js --mode modeling --host 127.0.0.1 --port 5174 --strictPort` |
| Repository ownership | Confirmed for `<repository-root>` |
| Repository-owned process IDs stopped | `86880`, `90856`, `69936`, `86292` |
| Unrelated Node/browser/Python/editor processes stopped | None |
| Port `5174` after stop | No listener |
| Live backend PID | `89928` |
| Live backend action | None; it remained running and healthy on port `8001` |

The normal development frontend was not restarted. Production acceptance used a static, non-HMR build on port `15184` and an isolated backend on port `18127`. Final closeout verification confirmed that both isolated ports and port `5174` were closed while the live backend PID `89928` remained untouched.

Sanitized evidence: `vite-stop-evidence.json`.

## 5. True isolated authority map

The isolated acceptance map uses one closeout UUID and a separate canonical root for each mutable authority. Every entry was classified `isolated`, resolved to a distinct canonical path, and was verified not to be a reparse point. Physical paths are intentionally omitted here.

| Authority | Isolation result |
| --- | --- |
| Persistence database | Distinct |
| Security database | Distinct |
| Audit authority | Distinct |
| Catalog registry | Distinct |
| Restricted catalog | Distinct |
| Catalog installation journal | Distinct |
| Project registry | Distinct |
| Dataset registry | Distinct |
| Project links | Distinct |
| Dataset Library | Distinct |
| Workflow checkpoint | Distinct |
| Evidence registry | Distinct |
| Documentation registry | Distinct |
| Feature manifests | Distinct |
| Model registry | Distinct |
| Temporary files | Distinct |
| Browser profile | Distinct |
| Browser downloads | Distinct |
| Test output | Distinct |
| Logs | Distinct |
| Frontend build | Distinct |

The harness strips inherited ATLAS, Vite, temporary-directory, and sensitive environment settings before pinning every required authority to a run-specific child. It rejects repository overlap, live-authority overlap, case aliases, symlinks, junctions, relative escape, missing mapped authorities, and live development ports. Durable restricted-catalog installation remains outside Windows Temp; synthetic test authorities remain bounded to the explicitly isolated test map.

Sanitized evidence: `isolated-authority-map.json`.

## 6. Production-build authentication readiness acceptance

The prerequisite production-authentication readiness acceptance is run `production-auth-29bc67f62a70441cad85568724a6ce39`. The final integrated production-authentication soak is reported separately in Section 22.

### 6.1 Build and transport

| Measure | Result |
| --- | --- |
| Build mode | Modeling production bundle served by a plain static server |
| Output files | 138 |
| Build checksum | `98adfbbf4a3fa3e350ac7079aad436f0d60292195a010d73270aa7836d12bdae` |
| Vite HMR markers | Absent |
| Browser mode | Headed persistent Chromium with an isolated synthetic profile |
| Fetch/XHR requests | 89 |
| Requests to isolated backend | 89 |
| Unexpected fetch/XHR requests | 0 |
| WebSocket requests | 0 |
| Live-port contacts | 0 |
| Guard-blocked requests | 0 |

### 6.2 Authentication, role, entitlement, and project isolation

| Scenario | Result |
| --- | --- |
| Initial load waits for authentication readiness | Passed |
| Authenticated reload restores user context | Passed |
| Authenticated reload restores entitlement context | Passed |
| Authenticated reloads | 20 of 20 passed |
| Synthetic users/providers/projects | 5 / 2 / 2 |
| Unauthenticated access | HTTP 401; no catalog request and no restricted detail |
| Non-admin administration route | UI role gate; no catalog request and no version metadata |
| Admin without exact entitlement | HTTP 403; nonleaking denial |
| Project A own-identity retrievals | 6 of 6 passed |
| Project A attempts against project B | 6 of 6 denied without content leak |
| Project B own-identity retrievals | 6 of 6 passed |
| Project B attempts against project A | 6 of 6 denied without content leak |
| Cross-user/project/provider contamination | 0 / 0 / 0 |
| Foreign project identity in browser storage | None detected |

The strict soak-compatible frontend evidence contains 21 bounded fields and checksum `fa16dd79de766ed44d2a265f871589de257de655bfc7e38b54bef7404a344d4f`. It reports 20 attempts, 20 successes, two projects, two providers, five users, no authentication failures, no unexpected failures, no live authority access, and no live-port contact.

### 6.3 Isolated audit result

The run appended 51 rows only to the isolated audit authority: 37 success outcomes and 14 expected denials. Of those, 24 were project-authorization rows, split into 12 successes and 12 nonleaking denials. The bounded schema and physical-path absence checks passed. The live audit authorities were not opened by the acceptance harness.

### 6.4 Sanitized screenshots

The definitive set contains synthetic content only:

- `production-auth-admin-initial.png`
- `production-auth-admin-reload.png`
- `production-auth-unauthenticated-denial.png`
- `production-auth-role-denial.png`
- `production-auth-entitlement-denial.png`
- `production-auth-project-alpha-isolation.png`
- `production-auth-project-beta-isolation.png`

This final set supersedes an earlier diagnostic unauthenticated screenshot that contained a prefilled local account identifier. That earlier image is not accepted closeout evidence and must not be used in reports or acceptance packages.

Primary evidence: `production-auth-acceptance-summary.json` and `frontend-authenticated-reload-evidence.json` beneath the opaque final run directory.

## 7. Protected-authority verification model

The closeout replaced whole-database-hash-only reasoning with a layered comparator implemented in `scripts/protected_authority_snapshot.py`.

### 7.1 Immutable file authorities

The protected manifest identifies 396 immutable file authorities. For these files, exact size and SHA-256 remain authoritative. The inventory covers curated dataset registries and links, workflow checkpoints, evidence and documentation records, feature manifests, model-registry artifacts, and other protected authorities selected for this closeout.

### 7.2 Critical SQLite authorities

Five SQLite profiles are captured read-only:

- primary ATLAS database, global scope;
- primary ATLAS database, exact HELOC scope;
- security database, global safe projection;
- live bureau catalog registry; and
- optional live bureau crosswalk-governance database.

The capture opens SQLite read-only and records allowlisted logical projections rather than unrestricted row content. The comparison covers, where present, primary-key identity digests, row counts, status values, revision statistics, checksum statistics, timestamp ranges, foreign-key schema, and protected relationship digests for users, sessions, project access, project and dataset identities, active selection, target/predictor contracts, Special-Value Review, Analysis Partition, feature manifests, validation/training/candidate records, evidence/MDD references, catalog versions, entitlements, and governed crosswalk decisions.

### 7.3 Audit authorities

Audit tables are compared independently as append-only authorities. The snapshot records total rows, maximum identifiers and timestamps, action and result counts, actor classification, project/entity binding counts, and bounded digests. A new live audit row remains an isolation failure; there is no blanket allowlist for `access.denied`.

### 7.4 Supplementary whole-file evidence

Whole SQLite file size and SHA-256 remain supplementary forensic evidence. They are not the sole semantic verdict because append-only audit activity, SQLite journaling, and storage representation can change bytes without changing protected business authority. Conversely, a matching whole-file hash does not replace logical integrity checks.

### 7.5 Comparator correction

The first comparison revision incorrectly treated a consistently absent optional crosswalk database as a change. The comparator was corrected so a stable absent optional authority is a baseline warning, while appearance, disappearance, required absence, logical digest change, audit growth, or relationship regression still fails. Focused hermetic verification passed 15 of 15 tests in run `atlas-hrt-20260805-190948-959b445561`.

## 8. Intermediate live-authority comparison

The semantic snapshot taken after the final `29bc...` production-auth run was compared with the frozen pre-auth snapshot.

| Comparison field | Result |
| --- | --- |
| Comparison mode | `logical_and_audit_authoritative` |
| Authoritative changes | 0 |
| Supplementary changes | 0 |
| Comparison passed | Yes |
| Main `audit_log` rows | 18,358 before and after |
| Security `audit_events` rows | 20,618 before and after |
| Maximum live audit timestamp | Unchanged |
| Whole SQLite hash used as sole authority | No |

Two stable baseline warnings remain:

1. Fourteen pre-existing unmatched `project_access_to_user` relationship rows in the security projection.
2. The optional live bureau crosswalk-governance database is absent.

Neither warning was created by isolated acceptance. Session-to-user integrity remained 357 of 357 matched. The final post-soak and post-regression comparison independently returned zero authoritative changes, zero supplementary changes, and no live audit additions; see Section 27.

Evidence: `live-protected-before.json`, `live-protected-after-project-auth.json`, and `live-protected-compare-project-auth.json`.

## 9. Restricted-storage architecture

`RestrictedCatalogInstaller` provides the durable installation boundary:

- requires an explicit absolute external restricted root;
- rejects the repository, worktrees, build/public/test output, Windows Temp for durable installation, configured live authorities, aliases, links, junctions, relative escape, and overlapping roots;
- inspects the Windows ACL and can fail closed when broad access is detected;
- validates the exact source manifest, expected checksum, attribute count, and special-value count before copying;
- copies to a unique staging location, rejects linked components, reloads and verifies the copied exact snapshot, writes a restricted installation envelope, and publishes atomically;
- removes only its own failed staging location and never moves or deletes the source;
- treats an identical existing installation as an idempotent exact revalidation;
- rejects a conflicting snapshot for the same logical version; and
- returns an opaque restricted reference rather than a filesystem path.

The installed catalog remains checksum-pinned and exact-version-only. The verified aggregate identity is:

| Measure | Value |
| --- | --- |
| Normalized catalog checksum | `0234e10f34c04430e445e51cfa3fb7dcf7c0dbada38af31f27a369e8b05599f8` |
| Attribute definitions | 1,718 |
| Attribute-scoped special-value definitions | 4,630 |
| Validation status | `passed_with_warnings` |
| First/latest fallback used | No |
| Full-catalog export used | No |

The physical restricted root and complete catalog content are intentionally not reproduced in this report.

## 10. Catalog registry architecture

`CatalogRegistry` is a self-versioned SQLite authority separate from the restricted catalog bytes. The closeout added support for a separately configured registry root and rejects any overlap between registry and restricted-content roots.

The registry provides:

- immutable exact catalog identity;
- uniqueness for exact provider/product/edition/release and normalized checksum;
- source and normalized checksums, aggregate counts, installation/integrity/lifecycle status, and registry revision;
- exact retrieval only, with no first/latest/current fallback;
- bounded deterministic version and entitlement inventories;
- exact principal/tenant/version operation grants with optional expiry;
- transactional grant, revoke, validation-state, and optimistic retirement updates;
- immutable identity triggers for protected catalog fields; and
- append-only access-audit triggers that reject update and delete.

The intermediate live semantic snapshot showed one installed, verified, active catalog version, one active entitlement pinned to the same checksum, one valid entitlement-to-version relationship, and five pre-existing bounded catalog-audit rows. These live records were unchanged by production-auth acceptance.

## 11. Entitlement model

Authorization is backend enforced and additive:

| Principal class | Required checks | Result boundary |
| --- | --- | --- |
| Catalog administrator | Authenticated ATLAS user, `admin` role, and exact catalog entitlement for the requested administrative version | May use only the implemented bounded administrative operation |
| Entitled catalog reader | Authenticated principal/tenant plus active exact-version grant containing the requested operation | May use only granted bounded read operations |
| Project user without catalog entitlement | Exact project access but no exact catalog grant | Catalog metadata denied without leaking whether the version exists |
| Unauthorized user | No valid authenticated context | HTTP 401 before restricted metadata is returned |

Entitlements are pinned to principal, optional tenant, exact `catalog_version_id`, exact catalog checksum, sorted operation set, status, and optional expiry. Retirement or failed integrity prevents ordinary reads. Grant and revoke are durable. Client-side route visibility is convenience only; it is not the authorization decision.

Project crosswalk preview requires both exact project authorization and exact catalog entitlement. The project resolver verifies the requested project, dataset, version, and durable link and does not select browser, checkpoint, first, or latest state. Safe denials do not disclose project schema, catalog definitions, or candidate mappings.

Catalog content caching is exact identity/checksum scoped. Authorization is evaluated before catalog access, and the final production-auth run proved no user, project, or provider content crossed contexts. Integrity validation clears the cache before reading exact stored bytes; failure clears it again and marks the exact registry version failed.

## 12. Bounded API contracts

All routes are mounted under `/api`, require the existing authenticated dependency, and return safe structured errors. No bulk catalog endpoint, browser-accessible storage path, file download, full-catalog stream, or unrestricted copy-all route exists.

| Method and route | Contract |
| --- | --- |
| `GET /bureau-catalogs` | Entitled exact versions only; deterministic bounded page, maximum 100 |
| `GET /bureau-catalogs/{version}/health` | Exact version/checksum health with entitlement |
| `GET /bureau-catalogs/{version}/attributes` | Non-empty query up to 128 characters; offset up to 100,000; page up to 50 |
| `GET /bureau-catalogs/{version}/attributes/{code}` | One exact normalized attribute or safe not found; no similar-code fallback |
| `GET /bureau-catalogs/{version}/attributes/{code}/special-values` | Attribute-specific special values only; page up to 100 |
| `GET /bureau-catalogs/{version}/attributes/{code}/availability` | Exact-version range, availability, leveling, and archive metadata |
| `POST /projects/{project}/bureau-catalogs/{version}/crosswalk-preview` | Exact project/dataset/version plus catalog entitlement; at most 250 schema fields and 2,000 candidate mappings; candidate-only and nonmutating |
| `GET /admin/bureau-catalogs` | Administrator role and entitled version inventory |
| `POST /admin/bureau-catalogs/{version}/validate` | Administrator plus exact entitlement; cache-evicting checksum/count validation |
| `POST /admin/bureau-catalogs/{version}/retire` | Administrator plus exact entitlement; optimistic registry revision; no deletion |
| `POST /admin/bureau-catalogs/{version}/entitlements` | Administrator plus exact entitlement; bounded supported operations |
| `POST /admin/bureau-catalog-entitlements/{id}/revoke` | Administrator plus exact entitlement for the referenced version |
| Admin attribute search and exact lookup aliases | Same backend entitlement and bounds as ordinary exact reads |

The router maps denial to safe HTTP 403, exact absence to 404, identity/integrity conflict to 409, invalid bounds to 400, search deadline to 504, and service unavailability to 503. A production-auth defect in which one entitlement denial escaped as an uncaught domain exception was corrected at the router boundary; the backend denial and bounded audit were preserved.

## 13. Crosswalk-state model

Crosswalk governance supports exactly nine states:

1. `exact_verified`
2. `approved_alias`
3. `transformed_or_derived`
4. `probable_review_required`
5. `ambiguous_review_required`
6. `recoding_evidence_required`
7. `unresolved`
8. `out_of_catalog`
9. `rejected`

Every decision requires bounded evidence. Confirmable states require explicit analyst confirmation, reviewer identity, rationale, and matching analyst-review evidence. Probable, ambiguous, recoding-required, and unresolved states remain review-required and prevent a lifecycle state of `confirmed`.

`SQLiteGovernedCrosswalkRepository` stores immutable revisions and a separately updated head. Each append uses `BEGIN IMMEDIATE`, compares `expected_revision`, requires exactly current revision plus one, verifies the previous revision checksum, and preserves immutable project/dataset/version/catalog/source lineage. Update and delete triggers protect revision history. Exact revision and exact current retrieval never fall back to another governance record.

The stored contract includes literal `dataset_mutated: false` and `predictor_authorization_mutated: false` invariants. Acceptance or confirmation records governance evidence only; it does not rewrite a dataset, target contract, predictor authorization, feature set, or workflow completion state.

## 14. Alias governance

Name similarity never creates an authoritative mapping. `approved_alias` requires:

- one exact candidate attribute code;
- an alias-authority identifier;
- an exact institutional alias reference;
- matching `institutional_alias` evidence from that authority;
- explicit analyst confirmation;
- reviewer identity matching analyst-review evidence; and
- a bounded rationale.

Alias references are rejected for every other mapping state. Probable semantic similarity remains `probable_review_required`; multiple plausible codes remain `ambiguous_review_required` with at least two alternatives. Neither can be silently upgraded by the preview service, cache, browser, or repository.

## 15. Transformation and recoding governance

`transformed_or_derived` requires at least one source attribute, a transformation rule or exact evidence reference, transformation-lineage evidence, reviewer evidence, and all of the following operational fields:

- data type;
- units;
- source system;
- timing;
- special-value handling;
- value-range reconciliation; and
- special-value reconciliation.

At least one bounded transformation or recoding concern is also required. `recoding_evidence_required` similarly requires explicit recoding evidence and bounded concerns and cannot be confirmed. The repository preserves the evidence/checksum chain across revisions rather than mutating source fields or applying a transformation.

## 16. Special-value safeguards

Special meanings are always keyed by exact catalog identity, attribute code, and value code. There is no global sentinel dictionary. The same value may have different meanings for different attributes, products, providers, editions, or versions.

Observed values resolve to exactly one of `ordinary_valid`, `bureau_special`, `true_null`, `parse_failure`, or `unexpected_invalid`; ordinary-outlier status is orthogonal and applies only to ordinary valid values. A documented special outside the ordinary domain remains a bureau special. An undocumented out-of-range value remains unexpected.

Catalog definitions never approve an institution's treatment automatically. A modeling recode requires separate governed evidence. The current Data Acquisition, EDA, Outliers, Missing Values, and Feature Engineering pages were not changed to consume this catalog in this closeout.

## 17. HELOC read-only diagnostic

The diagnostic is schema-only and exact identity-bound. It reads an allowlisted registered profile schema and a caller-supplied matching schema document. It rejects row, observation, preview, sample, and holdout keys; it does not open dataset data, development positions, holdout positions, or target values.

| Identity | Exact value |
| --- | --- |
| Project | `atlas-mrzpau4t` |
| Dataset | `ds_heloc_train_6bdb184b_05905` |
| Dataset version | `v_1785186305905_6bdb184b` |
| Analysis Partition | `analysis-partition-688c2184b4e9b8181946-r1` |
| Partition revision | 1 |
| Development / sealed final holdout | 5,020 / 1,255 |

Aggregate diagnostic outcome:

| State | Count |
| --- | ---: |
| Exact verified | 0 |
| Approved alias | 0 |
| Probable | 0 |
| Ambiguous | 0 |
| Unresolved fields | 1 |
| Fields requiring recoding evidence | 23 |

No negative HELOC value was assigned a vendor meaning without durable recoding evidence. No mapping became authoritative, no predictor authorization changed, and no sealed-holdout data was accessed.

## 18. Administration surface

The application exposes `/admin/bureau-catalogs` through an authenticated administrator route. A non-admin sees a safe denial and the client makes no catalog request. The backend independently enforces role and entitlement.

The administration surface provides:

- an explicit restricted-administration identity;
- server-filtered entitled exact-version inventory;
- integrity, installation, entitlement, validation, and lifecycle status;
- exact checksum prefix and aggregate counts;
- bounded query-required attribute search with deterministic pagination;
- exact single-attribute lookup;
- explicit integrity validation;
- two-step retirement with focus moved to the confirm action;
- cancel without mutation; and
- loading, empty, denial, unavailable, and conflict states.

There is no export, download, copy-all, unrestricted browse, or physical-path action. Retirement prevents new use of the exact version but does not delete catalog bytes or rewrite prior governed lineage. Entitlement grant/revoke exists at the backend contract; it is not presented as an unrestricted bulk administration tool.

## 19. Hermetic TypeScript packaging repair

The foundation report documented four older Node source-contract suites that failed before assertions because their isolated source mirrors omitted the runtime `typescript` package. The hermetic launcher now copies only the allowlisted TypeScript runtime package into each applicable child mirror.

The Node pre-import guard verifies:

- `HERMETIC_REGRESSION` mode;
- child source and authority roots;
- child-local `node_modules` and cache roots;
- exact TypeScript resolution beneath the copied child package;
- no TypeScript resolution from the live repository;
- no repository/live/browser authority overlap; and
- rejection of live ports `5174` and `8001`.

The child uses `node --import` to run the guard before the test module. Tests confirm the copied package is not a symlink, the live dependency file hash and timestamp remain unchanged, failure in one child does not contaminate another, and unsafe pre-import configuration fails before application import or authority write.

This repair closes the previously identified packaging mechanism. The complete frontend matrix passed from the final unchanged frozen source state in run `atlas-hrt-20260805-235532-5c2b87adde`; see Section 23.

## 20. Files changed by the catalog operationalization work

The repository has overlapping pre-existing work. The following is the exact catalog-related implementation and closeout surface identified for review; this is not a staging instruction and does not assign ownership to unrelated dirty-tree changes.

### Production and operational source

- `server/bureau_metadata/__init__.py`
- `server/bureau_metadata/types.py`
- `server/bureau_metadata/source_reader.py`
- `server/bureau_metadata/pdf_parser.py`
- `server/bureau_metadata/csv_parser.py`
- `server/bureau_metadata/normalizer.py`
- `server/bureau_metadata/catalog_builder.py`
- `server/bureau_metadata/catalog_store.py`
- `server/bureau_metadata/catalog_service.py`
- `server/bureau_metadata/validation.py`
- `server/bureau_metadata/crosswalk.py`
- `server/bureau_metadata/restricted_storage.py`
- `server/bureau_metadata/catalog_registry.py`
- `server/bureau_metadata/operational_service.py`
- `server/bureau_metadata/catalog_router.py`
- `server/bureau_metadata/crosswalk_governance.py`
- `server/bureau_metadata/crosswalk_governance_repository.py`
- `server/bureau_metadata/crosswalk_governance_service.py`
- `server/main.py`
- `src/lib/bureauCatalogAdmin.ts`
- `src/steps/BureauCatalogAdmin.tsx`
- `src/steps/AdminConsole.tsx`
- `src/apps/ModelingApp.tsx`

### Commands and closeout infrastructure

- `scripts/build_bureau_metadata_catalog.py`
- `scripts/validate_bureau_metadata_catalog.py`
- `scripts/build_bureau_metadata_crosswalk.py`
- `scripts/install_bureau_metadata_catalog.py`
- `scripts/run_bureau_metadata_schema_crosswalk_diagnostic.py`
- `scripts/run_bureau_metadata_isolated_acceptance.py`
- `scripts/run_bureau_metadata_operational_soak.py`
- `scripts/run_bureau_metadata_production_auth_acceptance.py`
- `scripts/protected_authority_snapshot.py`
- `scripts/hermetic_node_guard.mjs`
- `scripts/hermetic_node_preload.mjs`
- `scripts/hermetic_test_authority.py`
- `scripts/hermetic_test_bootstrap.py`
- `scripts/run_hermetic_tests.py`

### Documentation

- `docs/BUREAU_METADATA_CATALOG_FOUNDATION_REPORT_2026-08-04.md`
- `docs/BUREAU_METADATA_MANUAL_ACCEPTANCE_CHECKLIST_2026-08-05.md`
- `docs/BUREAU_METADATA_ENTITLEMENT_AND_CROSSWALK_CONTRACT_2026-08-05.md`
- `docs/BUREAU_METADATA_CATALOG_OPERATIONALIZATION_REPORT_2026-08-05.md`

The two user-supplied raw source files remain untracked, unchanged never-stage inputs. They were not copied into a tracked source, test, documentation, screenshot, frontend, or build artifact.

## 21. Tests added or updated and completed focused evidence

Catalog-specific tests and fixtures include:

- `tests/bureau_metadata_ingestion_test.py`
- `tests/bureau_metadata_core_test.py`
- `tests/bureau_metadata_acceptance_harness_test.py`
- `tests/bureau_metadata_crosswalk_test.py`
- `tests/bureau_metadata_crosswalk_cli_test.py`
- `tests/bureau_metadata_crosswalk_governance_test.py`
- `tests/bureau_metadata_crosswalk_sqlite_repository_test.py`
- `tests/bureau_metadata_catalog_router_test.py`
- `tests/bureau_metadata_registry_root_test.py`
- `tests/bureau_metadata_schema_crosswalk_diagnostic_test.py`
- `tests/bureau_metadata_operational_soak_test.py`
- `tests/bureau_metadata_source_safety_scan_test.py`
- `tests/protected_authority_snapshot_test.py`
- `tests/bureauCatalogAdmin.test.mjs`
- `tests/bureauCatalogAdmin.isolated.acceptance.mjs`
- `tests/bureauCatalogAdmin.productionAuth.acceptance.mjs`
- `tests/bureauCatalogAdmin.isolated.entry.tsx`
- `tests/bureauCatalogAdmin.isolated.entry.html`
- `tests/bureau_metadata_isolated_runtime_app.py`
- `tests/bureau_metadata_isolated_static_server.py`
- `tests/hermetic_node_guard.test.mjs`
- `tests/hermetic_test_harness_test.py`

Focused development evidence currently available:

| Focused check | Result |
| --- | --- |
| Catalog registry/operational focused group | 30 passed |
| Router/crosswalk focused group | 34 passed |
| Operational-soak harness focused tests | 11 passed |
| Protected semantic snapshot/comparator hermetic suite | 15 passed in 0.95 seconds |
| Production-build headed authentication acceptance | Passed; detailed in Section 6 |

These focused results established that the closeout harnesses and repaired contracts were executable. The complete final matrix subsequently passed and is reported in Section 23.

## 22. Fresh 30-minute soak results

**Status: PASSED.**

Final integrated run `production-auth-f7c4f1d2fe374aec8586e1e8ed85d038` completed from the unchanged source freeze of 956 files with aggregate SHA-256 `6415bdd48d462a74a61631b6dc991c4ecb160060ab212626dcef3876ef17d366`. The same source-freeze checksum was verified after the run. The isolated production build contained 138 files, contained no HMR markers, and had checksum `6516eb36f4749d451888576615dbe5d48cb0408535fda80aa8178acadad7364c`. The bounded integrated evidence checksum is `bfa704743967529bf22e21362c95a1ae549769ded517ba97c897acdb4ba8b084`.

| Required measure | Minimum | Final observed result |
| --- | ---: | --- |
| Uninterrupted timed soak | 1,800 seconds | 1,800.031 seconds |
| Parent acceptance window | Covers the timed soak and runtime recovery | 2,024.75 seconds |
| Total integrated run time | Complete isolated run | 2,238.266 seconds |
| Total requests / successful requests | Sustained workload | 13,379 / 13,042 |
| Expected authorization denials | Correct nonleaking denials | 254 |
| Concurrent synthetic users | 25 | 25 |
| Isolated projects | 10 | 10 |
| Synthetic catalog versions | 3 | 3 |
| Bounded lookup/search operations | 10,000 | 11,110 |
| Crosswalk previews | 1,000 | 1,290 |
| Crosswalk decision writes | 250 | 623 |
| Actual isolated backend listener restart cycles | 10 | 10; 11 unique isolated backend PIDs |
| Authenticated frontend reloads | Required during the integrated run | 60 of 60 passed |
| Latency | Bounded observation | p50 381.3138 ms; p95 704.0152 ms; maximum 3,061.4139 ms |
| Unexpected failures/timeouts | 0 / 0 | 0 / 0 |
| Cross-user/project/provider contamination | 0 / 0 / 0 | 0 / 0 / 0 |
| Entitlement inconsistencies | 0 | 0 |
| Duplicate revisions | 0 | 0 |
| Unexpected checksum/restart-recovery failures | 0 / 0 | 0 / 0 |
| Expected tamper checksum failures | 3 | 3 detected correctly |
| Temporary-root/transient-root leaks | 0 / 0 | 0 / 0 |
| Live frontend/backend contacts | 0 / 0 | 0 / 0 |
| Cache occupancy | Bounded | 3 of 4 entries |
| RSS/file-handle deltas | Best-effort platform metrics | Unavailable on this Windows process; reported as unavailable, not zero |
| Live-authority changes | 0 | Final semantic comparison: 0 authoritative and 0 supplementary changes |

The integrated run had zero unexpected failures, timeouts, contamination, duplicate revisions, entitlement inconsistency, unexpected checksum failures, restart-recovery failures, leaks, or live contacts. The three checksum failures were deliberate tamper cases and were detected as expected. RSS and file-handle deltas are the one unavailable runtime metric; no zero value is inferred. Historical interrupted and supporting soak runs remain recorded above as forensic history and are not credited toward this final result.

## 23. Full regression results

**Status: PASSED from one unchanged frozen source state.**

The final source freeze contained 956 files with aggregate SHA-256 `6415bdd48d462a74a61631b6dc991c4ecb160060ab212626dcef3876ef17d366`. Its checksum was unchanged after the complete regression cycle. Every manifest ran sequentially through the validated hermetic runner; no green wrapper contained a failed or skipped required child.

The completed matrix included:

- Bureau Metadata ingestion, core, parser, restricted-storage, registry, entitlement, router, crosswalk, governance, repository, diagnostic, soak, and source-safety suites;
- administration frontend tests and production-auth structural acceptance;
- all four formerly incomplete frontend suites under the repaired TypeScript packaging contract;
- hermetic harness and Node pre-import guard tests;
- Data Acquisition, canonical dataset identity, Project Context, project-scoped route, EDA, preparation, predictor authorization, and Special-Value Review regressions;
- security gate;
- storage-isolation scanner and guard;
- TypeScript compilation;
- production build into an external isolated output root;
- Python compilation into an external cache; and
- `git diff --check` and final empty-index verification.

| Invocation | Files/tests/subtests/assertions | Pass/fail/skip/warnings | Runtime | Result |
| --- | --- | --- | --- | --- |
| Bureau Metadata backend group, `atlas-hrt-20260805-235516-a26176946f` | 14 of 14 suites; 148 of 148 tests | 0 failures | 507.887372 s wall | Passed |
| Relevant backend cross-phase group, `atlas-hrt-20260805-235519-0922951dac` | 12 of 12 suites; 83 tests and 15 subtests | 0 failures; 36 warnings | 697.266957 s wall | Passed |
| Frontend/admin/cross-phase group, `atlas-hrt-20260805-235532-5c2b87adde` | 18 of 18 suites; 210 tests plus 2 legacy check scripts | 0 failures; 2 expected recovery-index warnings | 536.981882 s wall | Passed |
| Hermetic harness/Node guard, `atlas-hrt-20260805-235523-453681edc3` | 5 of 5 suites; 18 Python, 14 Node, and 15 semantic tests; 8 subtests; 2 probes | 0 failures; 1 intentional skip | 285.471880 s wall | Passed |
| Security gate, `atlas-hrt-20260806-000857-c6be774714` | 62 tests plus 30 structural assertions | 0 failures; 6 warnings | 323.344320 s wall | Passed |
| Storage-isolation scanner, `atlas-hrt-20260806-000539-164dcdfa98` | 1 of 1 suite; 113 Python test sources inspected | 0 findings | 80.255168 s wall | Passed |
| Storage-isolation guard, `atlas-hrt-20260806-000711-38a941108a` | 1 of 1 suite; 24 of 24 tests | 0 failures | 148.740584 s wall | Passed |
| TypeScript | Project compilation | 0 failures | Recorded in final gate evidence | Passed |
| Isolated production build | 138 files; checksum `6516eb36f4749d451888576615dbe5d48cb0408535fda80aa8178acadad7364c`; no HMR | 0 failures | Recorded in integrated run | Passed |
| Python compilation | Production Python sources | 0 failures | Recorded in final gate evidence | Passed |
| Git whitespace/index checks | `git diff --check`; index inspection | 0 whitespace failures; 0 staged paths | Recorded in final gate evidence | Passed |

All hermetic evidence remained in its opaque run root outside the repository. No manifest contacted a live service or live authority, and no required child failed or was omitted.

## 24. Security results

Completed production-build evidence establishes:

- protected calls waited for authentication readiness;
- unauthenticated access returned 401 without a catalog request;
- non-admin UI access was denied before a catalog request;
- missing exact entitlement returned a safe 403;
- project access alone did not authorize catalog access;
- cross-project requests were denied without leaking foreign identity;
- no restricted definition, checksum, version, storage path, or project schema leaked in a denial;
- denials remained audited in the isolated authority; and
- backend security was not suppressed or weakened.

The complete security gate passed hermetically in run `atlas-hrt-20260806-000857-c6be774714`: 62 tests and 30 structural assertions passed with zero failures and six warnings. The run did not contact live authentication, security, project, or audit authorities.

## 25. Storage-isolation results

Completed closeout evidence establishes:

- 21 mapped mutable authorities were canonical, distinct, non-reparse, and non-overlapping;
- catalog registry and restricted catalog roots were separated;
- all production-auth browser traffic stayed on the isolated origin pair;
- no isolated browser contacted ports `5174` or `8001`;
- no live browser contact with the isolated backend was observed;
- no isolated authority was resolved beneath the repository or a live root;
- final production-auth used an isolated browser profile, downloads, logs, temp, output, and build root; and
- the post-auth semantic comparator found no live mutation.

The full storage-isolation scanner passed in run `atlas-hrt-20260806-000539-164dcdfa98`, inspecting 113 Python test sources with zero findings. The storage-isolation guard passed 24 of 24 tests in run `atlas-hrt-20260806-000711-38a941108a`. Final runtime evidence recorded zero live contacts, overlaps, temporary-root leaks, transient-root leaks, and live audit additions. The isolated frontend and backend ports `15184` and `18127` were closed after the run; port `5174` remained closed and live backend PID `89928` remained untouched.

## 26. Source-safety scan

The prior foundation source-safety suite passed 8 of 8 checks, and the definitive production-auth summary reports synthetic content only, no vendor content, no live authority access, and no source/Git mutation. The raw source inputs remain untracked never-stage files. No unrestricted bulk export or frontend catalog asset exists.

The final expanded source scan passed with zero findings. It covered:

- raw PDF/CSV or normalized catalog artifacts tracked by Git;
- raw vendor descriptions in tests, documentation, screenshots, or frontend assets;
- restricted physical paths in frontend payloads;
- hardcoded user-profile paths;
- unrestricted export, download, stream, or copy-all behavior;
- catalog access without backend entitlement;
- fuzzy similarity producing authoritative mapping;
- global provider-special meanings;
- first/latest/current catalog fallback;
- client-side authorization as authority; and
- live HELOC identifiers embedded in production decision logic.

The strict scan inventoried 2,120 tracked paths, 1,697 tracked text files, 311 candidate documentation/test files, and 78,558 normalized fingerprints. OCR completed for 244 of 244 eligible images and produced zero image matches. The two raw vendor source inputs remained present, untracked, and excluded from tracked source, documentation, tests, screenshots, frontend assets, and build output.

## 27. Live authority, repository classification, and remaining limitations

### 27.1 Protected HELOC state after the final regression comparison

| Authority | Verified state |
| --- | --- |
| Project/dataset/version | Exact IDs in Section 17 unchanged |
| Active revision | 1, active |
| Analysis Partition | Exact ID in Section 17, revision 1 |
| Development/final-holdout counts | 5,020 / 1,255 |
| Holdout status | Sealed; isolation verified |
| Durable project link | Active and unchanged |
| Predictor authorization/target contract | Unchanged |
| Assignment/artifact/population checksums | Unchanged in the final semantic comparison |
| Live catalog version/entitlement/audit | Unchanged |
| Main `audit_log` rows | 18,358 before and after |
| Security `audit_events` rows | 20,618 before and after |
| Protected-authority inventory | 396 immutable file authorities and 5 read-only SQLite profiles |
| Final semantic comparison | Passed; 0 authoritative and 0 supplementary changes |
| Migration `0028` | SHA-256 `2256c1afd0ee4b8667dcadca4422950b29144a7745b48394e83d1c2b72f672c8`; applied live count 0 |

### 27.2 Repository classification

The safety baseline classifies existing production source, test infrastructure, tests, documentation, protected runtime authorities, and never-stage vendor inputs separately. Final classification recorded 64 modified tracked paths, 68 untracked paths, zero staged paths, and zero deleted paths. The raw vendor PDF and CSV remained untracked and present. `git diff --check` passed and the Git index remained empty.

No stage, commit, push, reset, restore, clean, amend, rebase, merge, cherry-pick, stash, delete, or discard operation was performed by this closeout. The final report preserves the initial dirty-tree history rather than presenting the repository as if this work began from a clean state.

### 27.3 Remaining nonblocking limitations

1. RSS and file-handle deltas were unavailable on the Windows runtime and are reported as unavailable, not zero. All required functional, isolation, latency, restart, and contamination gates still passed.
2. Fourteen project-access relationship orphans predate this closeout. They were stable through the final comparison and are not silently repaired here.
3. The optional live crosswalk-governance database is absent. Stable absence is a warning, not permission to create or migrate it in this task.
4. HELOC mappings remain non-authoritative pending institutional alias/recode evidence and analyst governance.
5. The complete licensed catalog remains restricted and requires organizational licensing/legal review before broader access.
6. Data Acquisition and downstream Predictive Modeling integration were intentionally not started.
7. Migration `0028` remains unchanged and unapplied live.
8. The normal ATLAS frontend on port `5174` remains intentionally stopped and must not be restarted by this closeout.

## 28. Final verdict and completion confirmations

### 28.1 Final automated closeout verdict

**READY FOR CONTROLLED CATALOG INTEGRATION**

Every required automated gate passed from the same unchanged 956-file frozen source state. This verdict authorizes only a separately approved controlled catalog-integration phase. It does not itself integrate definitions into Data Acquisition or any Predictive Modeling workflow, and it does not mark the manual reviewer checkboxes as complete.

### 28.2 Final confirmations

| Confirmation | Final result |
| --- | --- |
| Prior implementation preserved | Yes |
| Real source catalog moved or deleted | No |
| Raw vendor PDF/CSV present and untracked | Yes |
| Raw vendor catalog added to Git | No; zero staged paths |
| Proprietary catalog added to frontend assets | No |
| Bulk export created | No |
| Frozen production source changed during final gates | No; 956-file SHA-256 remained `6415bdd48d462a74a61631b6dc991c4ecb160060ab212626dcef3876ef17d366` |
| Live HELOC identity changed | No; the exact project, dataset, and dataset-version identity in Section 17 remained unchanged |
| Live Analysis Partition changed | No; revision 1 and development/final-holdout counts 5,020 / 1,255 remained unchanged |
| Sealed holdout accessed | No |
| Training occurred | No |
| Evaluation occurred | No |
| Interpretation occurred | No |
| Promotion occurred | No |
| Scoring occurred | No |
| Data Acquisition integration started | No |
| Migration `0028` changed or applied live | No / no; SHA-256 `2256c1afd0ee4b8667dcadca4422950b29144a7745b48394e83d1c2b72f672c8`, applied count 0 |
| Live authorization controls weakened | No |
| Live audit rows added by final integrated acceptance | No; counts remained 18,358 and 20,618 |
| Final protected-authority comparison | Passed; 0 authoritative and 0 supplementary changes across 396 immutable and 5 SQLite authorities |
| Isolated browser contacted live backend | No |
| Live browser contacted isolated backend | No |
| Isolated acceptance processes remained running | No; ports `15184` and `18127` were closed |
| Normal Vite frontend restarted | No; port `5174` remains intentionally unavailable |
| Live backend restarted, terminated, redirected, or reconfigured | No; PID `89928` remained untouched |
| Git index | Empty at final verification |
| Final working-tree classification | 64 modified tracked, 68 untracked, 0 staged, 0 deleted |
| Git/history/destructive operations | None: no stage, commit, push, reset, restore, clean, amend, rebase, merge, cherry-pick, stash, delete, or discard |
| Credentials, tokens, cookies, secrets, environment values, or restricted paths reproduced | No |

## Sanitized evidence index

| Evidence | Safe reference |
| --- | --- |
| Repository/safety state | `branch-head.txt`, `status-short.txt`, tracked/untracked manifests, `working-tree.patch` |
| Vite ownership and stop | `vite-stop-evidence.json` |
| Isolated authority map | `isolated-authority-map.json` |
| Catalog aggregate | `catalog-aggregate-sanitized.json` |
| HELOC identity/link/partition | `heloc-active-identity.json`, `heloc-project-link.json`, `heloc-analysis-partition.json` |
| Migration 0028 | `migration-0028-baseline.json` |
| Protected baseline | `protected-authority-manifest.json`, `live-protected-before.json` |
| Prerequisite production authentication | Run `production-auth-29bc67f62a70441cad85568724a6ce39` |
| Auth summary/reload evidence | `production-auth-acceptance-summary.json`, `frontend-authenticated-reload-evidence.json` |
| Post-auth semantic snapshot | `live-protected-after-project-auth.json` |
| Post-auth semantic comparison | `live-protected-compare-project-auth.json` |
| Corrected comparator focused test | Run `atlas-hrt-20260805-190948-959b445561`; 15 passed |
| Final integrated soak | Run `production-auth-f7c4f1d2fe374aec8586e1e8ed85d038`; bounded evidence SHA-256 `bfa704743967529bf22e21362c95a1ae549769ded517ba97c897acdb4ba8b084` |
| Frozen source | 956-file aggregate SHA-256 `6415bdd48d462a74a61631b6dc991c4ecb160060ab212626dcef3876ef17d366`, unchanged |
| Isolated production build | 138 files; SHA-256 `6516eb36f4749d451888576615dbe5d48cb0408535fda80aa8178acadad7364c`; no HMR |
| Catalog regression | Run `atlas-hrt-20260805-235516-a26176946f` |
| Cross-phase regression | Run `atlas-hrt-20260805-235519-0922951dac` |
| Hermetic harness/Node guard | Run `atlas-hrt-20260805-235523-453681edc3` |
| Frontend regression | Run `atlas-hrt-20260805-235532-5c2b87adde` |
| Storage scanner | Run `atlas-hrt-20260806-000539-164dcdfa98` |
| Storage guard | Run `atlas-hrt-20260806-000711-38a941108a` |
| Security gate | Run `atlas-hrt-20260806-000857-c6be774714` |
| Final semantic comparison | Passed; 0 authoritative and 0 supplementary changes |
