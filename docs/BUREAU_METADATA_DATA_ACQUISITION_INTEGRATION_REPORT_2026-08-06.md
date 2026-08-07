# Bureau Metadata Data Acquisition Integration Report — 2026-08-06

**Final verdict:** **READY FOR MANUAL DATA ACQUISITION ACCEPTANCE**

This report records the completed controlled Bureau Metadata Catalog integration into Data Acquisition and the bounded canonical metadata handoff. The broad regression, security, storage isolation, TypeScript/production build, headed production-browser acceptance, uninterrupted soak, ten listener restarts, isolated-service teardown, strict source/artifact scans, protected-authority comparison, live HELOC comparison, migration check, compilation, live-port reconciliation, and Git closeout all passed.

Evidence used here includes current source inspection, the preserved 2026-08-05 integration report, the controlled-suite manifest, hermetic run `atlas-hrt-20260806-145610-ed37849c17`, and final integrated run `production-auth-a9e0d4b45eb8428d88f5102c3949f953`. Its exact summary is `C:\Users\james\AppData\Local\ATLAS\catalog-closeout-17f09fa69f51415997414ef1c1930d90\test-output-2512ef019a4244c3a03a34ffb2b920a9\production-auth-a9e0d4b45eb8428d88f5102c3949f953\integrated-catalog-closeout-summary.json`. The exact soak child summary is `C:\Users\james\AppData\Local\ATLAS\catalog-closeout-17f09fa69f51415997414ef1c1930d90\test-output-2512ef019a4244c3a03a34ffb2b920a9\catalog-soak-5abef5305747905dde4887f8\catalog-soak-20260806-174439-2d225e9b-summary.json`.

## 1. Initial repository and process state

- Workspace: `C:\Users\james\ds-workflow-starter`.
- The prior report `docs/BUREAU_METADATA_DATA_ACQUISITION_INTEGRATION_REPORT_2026-08-05.md` was preserved. This dated report is a new artifact.
- This report-preparation subtask did not invoke Git, stage files, create a commit, push, reset, restore, clean, amend, stash, delete, or discard repository content.
- No live project, governed dataset, catalog authority, service, process, or port was mutated or controlled while preparing this report.
- Broad `HERMETIC_REGRESSION` evidence completed with 97 suites passed and 0 failed.
- Final integrated run `production-auth-a9e0d4b45eb8428d88f5102c3949f953` completed with `passed: true` from `2026-08-06T17:41:48.767915Z` through `2026-08-06T18:19:29.735201Z`, 2260.953 seconds total.
- The run used 21 mapped, disjoint synthetic authority children; `live_project_accessed`, `sealed_holdout_accessed`, `training_started`, and `source_or_git_mutated_by_run` were all `false`.
- A transient closeout observation found PID 89928 alive as the same uvicorn process while no port-8001 `LISTEN` socket was visible. The PID never exited; without agent action, its listener returned on port 8001 with the same process identity and start time. The run made zero live-port contacts and performed no live-service manipulation.
- Final protected comparison passed with zero authoritative and zero supplementary changes. The exact HELOC identity and revision-1 Analysis Partition matched baseline.
- Final Git closeout recorded branch `codex/phase2a-canonical-lineage` at `938c5b1e2d5b4f81f2b35acc11a048a9b8a04d62`, an empty index, no tracked deletions, and `git diff --check` exit 0.
- Final source snapshot covered 998 files with aggregate SHA-256 `460ca50076225341c071ba5cb1b68df2d9fdf011120dbf6b42432acd02d0d4c0`.

## 2. Exact current catalog architecture

The implemented architecture separates restricted provider material from bounded application projections:

1. Source readers and parsers ingest provider PDF/CSV material only into the controlled builder/validation path.
2. Normalization and validation produce a deterministic catalog version, catalog key, checksum, lifecycle state, attribute records, ordinary-range references, and special-value definitions.
3. Restricted storage, the catalog registry, and the installation journal remain server-side authorities. The browser never becomes a catalog authority.
4. The operational catalog service enforces access context, lifecycle, checksum, entitlement, bounded search, bounded detail, availability, and mapped-field batch reads.
5. Exact dataset-version binding persists immutable revisions connecting project, dataset, dataset version, schema checksum, catalog version/key/checksum, actor, reason, evidence, and confirmation lineage.
6. Governed crosswalk revisions persist analyst decisions in the existing nine-state model. Candidate generation is not authoritative.
7. Consistency, semantic-annotation, Evidence Center, MDD, and EDA projections are bounded, checksummed handoffs. They do not copy the complete restricted catalog.

Application routers are mounted under `/api` in `server/main.py`. Non-admin catalog reads remain authenticated and entitled; administrative catalog inventory, validation, retirement, entitlement grant, and entitlement revoke routes remain administrator-only.

## 3. Existing nine-state crosswalk model

`server/bureau_metadata/crosswalk_governance.py` defines exactly these states:

| State | Governed meaning |
| --- | --- |
| `exact_verified` | Analyst-verified exact provider attribute mapping. |
| `approved_alias` | Analyst-approved alias for a provider attribute. |
| `transformed_or_derived` | Dataset field is transformed or derived and is not represented as a direct provider field. |
| `probable_review_required` | Heuristic evidence suggests a candidate, but analyst review is required. |
| `ambiguous_review_required` | More than one plausible candidate or insufficient disambiguation requires review. |
| `recoding_evidence_required` | A recoding claim requires evidence before authoritative promotion. |
| `unresolved` | No approved authoritative mapping is available. |
| `out_of_catalog` | The field is governed as outside the selected catalog. |
| `rejected` | A proposed candidate was explicitly rejected. |

Only `exact_verified` and `approved_alias` may carry provider-authoritative semantics into the canonical downstream envelope. A probable, ambiguous, unresolved, transformed, out-of-catalog, rejected, or recoding-evidence-required state is not silently promoted.

## 4. Before-and-after Data Acquisition flow

**Before the controlled integration**

Registered dataset/version → bureau detection → dataset-observed Special-Value Review → predictor authorization → Analysis Partition readiness → Data Acquisition completion → canonical EDA handoff.

**After the controlled integration**

Exact registered dataset/version → bureau detection or explicit review → explicit entitled catalog selection → nonmutating binding preview → explicit checksum/evidence confirmation → server-built crosswalk candidates → analyst governance decisions → immutable crosswalk revision → new exact binding revision pinning that crosswalk → consistency checks → bounded semantic annotations → table-first Special-Value Review → unchanged predictor authorization and Analysis Partition → canonical EDA handoff.

The integration adds metadata and governance lineage. It does not replace the existing observed-special-value flow or authorize dataset/treatment/partition mutation.

## 5. Dataset-version catalog-binding contract

- Scope is the exact tuple `project_id + dataset_id + dataset_version_id`, plus the dataset schema checksum and the explicitly selected catalog version/key/checksum.
- Inventory and an absent binding are different states. The client must not choose “first,” “latest,” or another implicit catalog fallback.
- Preview is server-authoritative and nonmutating. It returns bounded counts and a preview checksum.
- Confirmation requires explicit selection, evidence, preview checksum, and optimistic revision. Repeating the same valid confirmation is deterministic and idempotent.
- History is immutable and bounded to at most 100 returned revisions.
- A later crosswalk link creates a new binding revision; it does not rewrite prior lineage.
- Binding metadata does not choose or apply a special-value treatment and does not change downstream workflow state.
- Confirmation is not reported as wholly successful until its bounded Evidence Center and MDD projections persist. A governance revision that persists before a binding or documentation failure is returned as a visible partial metadata state, not a false rollback claim.

## 6. Crosswalk governance behavior

The server builds bounded candidates from the exact dataset schema and exact entitled catalog identity. Analysts explicitly choose one of the nine governance states and provide the evidence required for an authoritative decision. The server validates dataset identity, catalog identity, checksums, decision shape, candidate limits, and optimistic revision before appending an immutable crosswalk revision.

Key fail-closed behavior:

- heuristics and unverified candidates remain visibly non-authoritative;
- generic HELOC-style names are not automatically assigned Experian definitions;
- accepted provider semantics require `exact_verified` or `approved_alias`;
- stale binding/crosswalk/checksum lineage is rejected;
- contradictory metadata does not become a treatment recommendation;
- persisted governance followed by binding-link or documentation failure is disclosed as `partial_metadata_state: true` with exact persistence/link status.

The crosswalk router bounds a request to 250 fields, 1,000 candidates, and 100 returned history revisions.

## 7. Special-Value table integration

The compact binding and crosswalk experience is placed in Data Acquisition immediately before the existing Special-Value Review. The existing review remains table-first:

- each dataset field remains the primary row;
- dataset-observed special-value behavior remains available even with no entitlement or no authoritative mapping;
- provider definitions and approved crosswalk evidence are supplemental metadata, not treatment instructions;
- row expansion exposes code-level metadata without replacing inline treatment controls;
- catalog metadata never silently selects, applies, or changes a treatment;
- true nulls and ordinary outliers remain separate from provider special values.

## 8. Exact wording for authoritative, heuristic, and unresolved metadata

The production UI uses these exact provenance labels:

- “Provider catalog definition”
- “Analyst-approved crosswalk”
- “Dataset-observed behavior”
- “ATLAS heuristic detection”
- “Unverified candidate”

The unresolved message is:

> No authoritative catalog mapping is available for this field. ATLAS will continue to show observed special-value behavior, but it will not assign a provider definition without approved mapping evidence.

The no-entitlement heading is:

> No entitled bureau catalog version is available.

The binding disclaimer is:

> Bind this exact Dataset Library version to one explicitly selected, entitled, checksum-verified bureau catalog version. Binding metadata does not choose special-value treatments or change downstream workflow state.

## 9. Consistency-check behavior

`server/bureau_metadata/catalog_consistency.py` returns exactly these overall states:

- `consistent`
- `consistent_with_observed_unused_codes`
- `review_required`
- `contradictory`
- `metadata_unavailable`
- `mapping_unresolved`

Checks compare approved mapping state, datatype, field length, ordinary-range boundaries, observed values, provider special definitions, and lineage availability. `consistent` and `consistent_with_observed_unused_codes` can support a bounded informational recommendation. `review_required` requires analyst action. `contradictory`, `metadata_unavailable`, and `mapping_unresolved` fail closed for provider-driven recommendation while preserving dataset-observed review.

## 10. API contracts

All paths below are application paths under `/api`.

**Entitled catalog query plane**

- `GET /api/bureau-catalogs`
- `GET /api/bureau-catalogs/{catalog_version_id}/health`
- `GET /api/bureau-catalogs/{catalog_version_id}/attributes`
- `GET /api/bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}`
- `GET /api/bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}/special-values`
- `GET /api/bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}/availability`
- `POST /api/projects/{project_id}/bureau-catalogs/{catalog_version_id}/crosswalk-preview`

**Exact dataset-version binding**

- `GET /api/projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}/bureau-metadata/binding`
- `POST .../bureau-metadata/binding/preview`
- `POST .../bureau-metadata/binding/confirm`
- `GET .../bureau-metadata/binding/history?limit=...`

**Governed crosswalk and semantic handoff**

- `GET .../bureau-metadata/crosswalk/preview`
- `GET .../bureau-metadata/crosswalk/current`
- `GET .../bureau-metadata/crosswalk/history?limit=...`
- `POST .../bureau-metadata/crosswalk/decisions`
- `POST .../bureau-metadata/crosswalk/binding-link`
- `GET .../bureau-metadata/crosswalk/semantic-annotations`
- canonical alias: `GET .../bureau-metadata/annotations`
- `GET .../bureau-metadata/crosswalk/consistency`

Administrative `/api/admin/bureau-catalogs...` routes remain administrator-only. Catalog version pages are capped at 50, attribute pages at 50, special-value pages at 100, search text at 128 characters, and search offset at 100,000. Mapped results, history, annotations, and consistency responses are bounded; no route exports raw dataset rows or the complete provider catalog.

Expected safe failure classes are authorization `403`, unavailable exact resource `404`, stale/conflicting lineage `409`, request validation `400/422`, and operational unavailability `503`. Error payloads must not disclose restricted definitions, physical restricted paths, credentials, or another tenant’s identity.

## 11. Entitlement and tenant-isolation behavior

Project access and catalog entitlement are independent server-side checks; neither implies the other. Durable and cached identity includes the required tenant, principal, project, and catalog-version dimensions. Revocation makes current restricted semantics unavailable without erasing immutable binding/crosswalk history. Client visibility is presentation, never authorization.

The hermetic security and isolation suites passed as recorded in Sections 20 and 21. The final headed-browser phases exercised six synthetic users, two providers, five project scenarios, authenticated and role/entitlement denials, and multi-user/multi-project/provider separation. Across all three phases, cross-user, cross-project, and cross-provider contamination were zero. The soak recorded 254 expected authorization denials, three entitlement-revoke integration events, and zero inconsistent entitlement results. The final protected comparison recorded zero authoritative and supplementary live changes.

## 12. Evidence and MDD mapping

`record_binding_evidence_and_documentation` stores a bounded projection of exact dataset/catalog lineage, binding and crosswalk revision references, entitlement verification, mapping-state counts, special-value separation rules, treatment-policy limitations, actor, and server timestamp.

The projection records that:

- true nulls and ordinary outliers remain separate from provider special values;
- metadata informed review but did not select or apply a treatment;
- dataset, target contract, treatment, predictor authorization, Analysis Partition, and feature manifest were not mutated by the metadata operation;
- the proprietary provider catalog was not embedded.

Binding confirmation and successful crosswalk decision/link completion do not report full success until their bounded Evidence Center and MDD projections persist. Repeated exact confirmation is deterministic and idempotent.

## 13. Downstream metadata handoff

The canonical semantic envelope pins project, dataset, version, schema checksum, exact catalog version/key/checksum, binding ID/revision/checksum, crosswalk ID/revision/checksum, and annotation-set checksum. Only analyst-confirmed `exact_verified` and `approved_alias` decisions may include provider-authoritative description, datatype, units, range, or special-code definitions.

The server performs one bounded exact entitled batch read for accepted mapped attributes rather than per-cell or per-row catalog calls. Unresolved, stale, contradictory, or unentitled metadata is not promoted. EDA validates the exact annotation identity and nonmutation contract: optional absence is nonblocking, while stale or contradictory metadata fails closed. The handoff does not change row scope, development membership, target intelligence, predictor authorization, feature manifest, Analysis Partition, or holdout isolation.

## 14. Performance design and measurements

Implemented controls include deterministic ordering, checksum/revision lineage, bounded server-side search, one bounded mapped-attribute batch read, bounded descriptions/special definitions, and no full-catalog browser, Evidence Center, or MDD payload.

| Required final metric | 2026-08-06 measured result |
| --- | --- |
| Aggregate isolated request latency | 13,386 samples; p50 371.65635 ms; p95 644.2625 ms; maximum 5835.8083 ms |
| Data Acquisition integration activity | 975 events: 812 HTTP 200, 6 HTTP 401, 42 HTTP 403, 109 HTTP 404, 3 HTTP 409, and 3 HTTP 422 |
| Mapped semantic batch activity | 106 `semantic_batch` events; bounded mapped-read design remained in force |
| Catalog search/lookup activity | 3 integrated `catalog_search_or_lookup` events; soak switched exact catalog versions 875 times |
| Crosswalk activity | 1,291 soak previews, 641 timed probes, 625 decision writes, 84 expected concurrency conflicts, and 71 concurrent alias reviews |
| Cache behavior | 0 final entries against a limit of 4; within limit; tamper cache eviction, detection, and recovery passed |
| Bounded operations | 11,112; 13,386 total requests; 13,048 successful; 0 timeouts; 0 unexpected failures |
| Memory and handle observations | Unavailable: RSS and handle before/after/delta are `null` and were explicitly reported unavailable, not zero |
| Per-route catalog-summary latency | **NOT SEPARATELY EMITTED BY THE FINAL SUMMARY** |
| Per-route mapped-field latency | **NOT SEPARATELY EMITTED BY THE FINAL SUMMARY** |
| Catalog-search and crosswalk-preview p50/p95 by operation | **NOT SEPARATELY EMITTED; aggregate p50/p95 above** |
| Response payload sizes and SQL query counts | **NOT SEPARATELY EMITTED** |

The isolated production run also recorded 168 independent writer instances, 800 exact-identity negative checks, zero duplicate revisions, zero leaked temporary entries, and zero leaked transient roots. Suite child durations in Sections 18–21 remain test-runner durations, not endpoint latency.

## 15. Exact production files changed

Final Git closeout captured the exact branch, HEAD, index state, status counts, and clean diff check recorded in Section 29. Because the dirty tree also contains unrelated pre-existing work, the exact controlled integration production surface identified by source and test contracts is listed here without attributing every dirty path to this phase:

**Backend**

- `server/bureau_metadata/catalog_binding.py`
- `server/bureau_metadata/catalog_binding_repository.py`
- `server/bureau_metadata/catalog_binding_service.py`
- `server/bureau_metadata/catalog_binding_router.py`
- `server/bureau_metadata/catalog_documentation.py`
- `server/bureau_metadata/catalog_consistency.py`
- `server/bureau_metadata/crosswalk_governance.py`
- `server/bureau_metadata/crosswalk_governance_repository.py`
- `server/bureau_metadata/crosswalk_governance_service.py`
- `server/bureau_metadata/crosswalk_router.py`
- `server/bureau_metadata/catalog_router.py`
- `server/bureau_metadata/operational_service.py`
- `server/bureau_metadata/semantic_annotation.py`
- `server/eda/bureau_semantic_contract.py`
- `server/eda/eda_router.py`
- `server/eda/workspace_service.py`
- `server/eda/workspace_types.py`
- `server/eda/analytical_contract.py`
- `server/main.py`

**Frontend**

- `src/components/BureauMetadataBindingPanel.tsx`
- `src/components/BureauMetadataCrosswalkWorkspace.tsx`
- `src/components/BureauReviewPanel.tsx`
- `src/lib/bureauMetadata.ts`
- `src/lib/bureauSemanticAnnotations.ts`
- `src/lib/dataAcquisitionEdaHandoff.ts`
- `src/steps/Step01_DataAcquisition.tsx`
- `src/steps/Step02_EDA.tsx`

This is a source-scope inventory, not permission to stage every path. Final Git classification must replace this caveat before the report can be treated as final.

## 16. Exact migrations added

No migration was added for the controlled Bureau Metadata integration; existing durable authorities are reused. In the hermetic 97-suite run:

- `migration-atomicity`: `tests/persistence_migration_atomicity_test.py` — 14 passed, 18 warnings in 25.81 seconds; child duration 27.442795 seconds.
- All child summaries reported zero isolated migrations.

Final migration proof passed: `0028_project_deletion_append_only_cascade.sql` retained SHA-256 `2256c1afd0ee4b8667dcadca4422950b29144a7745b48394e83d1c2b72f672c8`, and `live_applied_count` remained 0.

## 17. Exact tests added and updated

The final Git classification is recorded in Section 29. Because the working tree intentionally contains unrelated pre-existing work, this section identifies the exact controlled integration test and harness inventory rather than attributing unrelated repository entries to this phase:

**Backend and cross-phase tests**

- `tests/bureau_metadata_ingestion_test.py`
- `tests/bureau_metadata_core_test.py`
- `tests/bureau_metadata_registry_root_test.py`
- `tests/bureau_metadata_catalog_router_test.py`
- `tests/bureau_metadata_catalog_binding_test.py`
- `tests/bureau_metadata_catalog_binding_router_test.py`
- `tests/bureau_metadata_catalog_documentation_test.py`
- `tests/bureau_metadata_mapped_batch_test.py`
- `tests/bureau_metadata_crosswalk_test.py`
- `tests/bureau_metadata_crosswalk_governance_test.py`
- `tests/bureau_metadata_crosswalk_sqlite_repository_test.py`
- `tests/bureau_metadata_crosswalk_router_test.py`
- `tests/bureau_metadata_crosswalk_cli_test.py`
- `tests/bureau_detection_exact_binding_test.py`
- `tests/special_value_review_contract_test.py`
- `tests/eda_bureau_semantic_handoff_test.py`

**Frontend source-contract tests**

- `tests/bureauCatalogAdmin.test.mjs`
- `tests/bureauDetectionExactBinding.test.mjs`
- `tests/bureauMetadataBindingPanel.test.mjs`
- `tests/bureauMetadataCrosswalkWorkspace.test.mjs`
- `tests/bureauSemanticAnnotationsFrontend.test.mjs`
- `tests/bureauSemanticDownstreamPresentation.test.mjs`
- `tests/bureauMetadataIntegrationAcceptanceHarness.test.mjs`

**Controlled closeout and safety tests**

- `tests/bureau_metadata_acceptance_harness_test.py`
- `tests/bureau_metadata_source_safety_scan_test.py`
- `tests/restricted_catalog_source_safety_test.py`
- `tests/bureau_metadata_schema_crosswalk_diagnostic_test.py`
- `tests/bureau_metadata_integrated_closeout_test.py`
- `tests/bureau_metadata_reverse_isolation_guard_test.py`
- `tests/bureau_metadata_operational_soak_test.py`
- `tests/bureau_metadata_isolated_services_launcher_test.py`
- `tests/bureau_metadata_browser_reload_evidence_test.py`
- `tests/isolated_loopback_ports_test.py`
- `tests/bureauMetadataIntegration.production.acceptance.mjs`
- `tests/bureauMetadataIntegration.isolated.entry.tsx`
- `tests/bureauMetadataIntegration.isolated.entry.html`
- `tests/bureauMetadataIntegration.vite.config.ts`
- `tests/bureau_metadata_integration_runtime_app.py`
- `tests/bureau_metadata_integrated_runtime_app.py`
- `tests/bureau_metadata_isolated_runtime_app.py`

## 18. Focused test results

These exact relevant-suite results come from `atlas-hrt-20260806-145610-ed37849c17`:

| Suite | Target | Exact result | Child duration |
| --- | --- | --- | ---: |
| `bureau-ingestion` | `tests/bureau_metadata_ingestion_test.py` | 9 passed | 3.789332 s |
| `bureau-core` | `tests/bureau_metadata_core_test.py` | 8 passed | 2.432314 s |
| `bureau-registry-root` | `tests/bureau_metadata_registry_root_test.py` | 6 passed | 2.012038 s |
| `bureau-catalog-router` | `tests/bureau_metadata_catalog_router_test.py` | 18 passed | 6.292698 s |
| `bureau-catalog-binding` | `tests/bureau_metadata_catalog_binding_test.py` | 17 passed | 2.205931 s |
| `bureau-catalog-binding-router` | `tests/bureau_metadata_catalog_binding_router_test.py` | 15 passed | 6.186371 s |
| `bureau-catalog-documentation` | `tests/bureau_metadata_catalog_documentation_test.py` | 3 passed | 2.004845 s |
| `bureau-mapped-batch` | `tests/bureau_metadata_mapped_batch_test.py` | 2 passed | 1.975354 s |
| `bureau-crosswalk` | `tests/bureau_metadata_crosswalk_test.py` | 10 passed | 1.890651 s |
| `bureau-crosswalk-governance` | `tests/bureau_metadata_crosswalk_governance_test.py` | 39 passed | 1.925442 s |
| `bureau-crosswalk-sqlite` | `tests/bureau_metadata_crosswalk_sqlite_repository_test.py` | 5 passed | 2.024486 s |
| `bureau-crosswalk-router` | `tests/bureau_metadata_crosswalk_router_test.py` | 12 passed | 6.656905 s |
| `bureau-crosswalk-cli` | `tests/bureau_metadata_crosswalk_cli_test.py` | 5 passed | 2.227394 s |
| `bureau-exact-binding` | `tests/bureau_detection_exact_binding_test.py` | 14 passed | 8.861127 s |
| `bureau-acceptance-harness` | `tests/bureau_metadata_acceptance_harness_test.py` | 6 passed | 8.380480 s |
| `bureau-schema-crosswalk-diagnostic` | `tests/bureau_metadata_schema_crosswalk_diagnostic_test.py` | 7 passed | 6.212176 s |
| `bureau-integrated-closeout` | `tests/bureau_metadata_integrated_closeout_test.py` | 10 passed | 2.463334 s |
| `bureau-reverse-isolation-guard` | `tests/bureau_metadata_reverse_isolation_guard_test.py` | 5 passed | 2.932396 s |
| `bureau-operational-soak-contract` | `tests/bureau_metadata_operational_soak_test.py` | 11 passed | 29.649843 s |
| `bureau-isolated-services-launcher` | `tests/bureau_metadata_isolated_services_launcher_test.py` | 7 passed | 1.405178 s |
| `bureau-browser-reload-evidence` | `tests/bureau_metadata_browser_reload_evidence_test.py` | 11 passed | 2.408757 s |
| `isolated-loopback-ports` | `tests/isolated_loopback_ports_test.py` | 4 passed | 2.370652 s |
| `special-value-review` | `tests/special_value_review_contract_test.py` | 7 passed | 4.044174 s |
| `eda-bureau-semantic-handoff` | `tests/eda_bureau_semantic_handoff_test.py` | 8 passed, 2 subtests passed, 13 warnings | 17.301767 s |
| `bureau-admin-ui` | `tests/bureauCatalogAdmin.test.mjs` | 11/11 Node tests passed | 0.308352 s |
| `bureau-exact-binding-ui` | `tests/bureauDetectionExactBinding.test.mjs` | 7/7 Node tests passed | 1.477866 s |
| `bureau-binding-panel-ui` | `tests/bureauMetadataBindingPanel.test.mjs` | 7/7 Node tests passed | 1.025530 s |
| `bureau-crosswalk-workspace-ui` | `tests/bureauMetadataCrosswalkWorkspace.test.mjs` | 7/7 Node tests passed | 0.992929 s |
| `bureau-semantic-annotations-ui` | `tests/bureauSemanticAnnotationsFrontend.test.mjs` | 7/7 Node tests passed | 1.014295 s |
| `bureau-semantic-downstream-presentation-ui` | `tests/bureauSemanticDownstreamPresentation.test.mjs` | 4/4 Node tests passed | 1.037017 s |
| `bureau-browser-acceptance-contract-ui` | `tests/bureauMetadataIntegrationAcceptanceHarness.test.mjs` | 4/4 Node tests passed | 0.370035 s |

The browser and soak rows above validate contracts and harness behavior only; they are not actual browser acceptance or an uninterrupted 30-minute soak.

## 19. Broad regression results

| Field | Exact result |
| --- | --- |
| Run ID | `atlas-hrt-20260806-145610-ed37849c17` |
| Mode | `HERMETIC_REGRESSION` |
| Start | `2026-08-06T15:01:52.303459+00:00` |
| Finish | `2026-08-06T16:00:53.403537+00:00` |
| Wall time | 3541.100078 seconds (59:01.100078) |
| Sum of child durations | 1245.111726 seconds (20:45.111726) |
| Suite result | **97 passed, 0 failed** |
| Python pytest targets | 56 suites; 589 passed; 56 subtests passed; 147 warnings; 0 failures/skips |
| Node targets | 39 suites; 34 numeric suites reported 343/343 tests passed, 0 failed/skipped/cancelled/todo; 5 static command suites passed |
| Other targets | Security gate and storage-isolation scanner both passed |
| Evidence preserved | `true` |
| Run-level cross-child isolation field | `status: not-run`, `child_count: 0` |

This is strong broad hermetic regression evidence. That specific 97-suite run did not execute a production build, real browser, or uninterrupted 30-minute acceptance soak; those were subsequently executed by the separate final integrated run documented in Sections 22–24. The final live HELOC and protected-authority comparisons passed as documented in Sections 26–27.

## 20. Security results

`security-release-gate` ran `scripts/run_security_tests.py` and passed in a child duration of 254.812425 seconds:

- 7 behavioral suites;
- 62 behavioral tests;
- 1 structural suite;
- 30 structural assertions;
- 0 gate failures.

The output retained non-failing ResourceWarning and Pydantic deprecation diagnostics. Browser entitlement transitions and live-authority invariance were subsequently verified by the final integrated and protected-comparison evidence.

## 21. Storage-isolation results

- `storage-isolation-scanner` ran `scripts/check_test_storage_isolation.py`: passed; 123 Python test sources inspected; child duration 35.538816 seconds.
- `storage-isolation-guard` ran `tests/test_storage_isolation_guard_test.py`: 24 passed in 64.28 seconds; child duration 67.124915 seconds.
- `migration-atomicity` ran `tests/persistence_migration_atomicity_test.py`: 14 passed, 18 warnings in 25.81 seconds; child duration 27.442795 seconds.

These are passing storage-safety gates. The run summary’s separate run-level `cross_child_isolation` field was `not-run`, so it is not mislabeled as a pass. Dedicated integrated isolation and the protected-live-authority comparison subsequently passed as recorded in Sections 24, 26, and 28.

## 22. Production build and compilation results

The final integrated run built the isolated production frontend before starting its services. `npm run build:modeling` expands to `tsc -b && vite build --mode modeling`, so the successful command is evidence for both TypeScript compilation and the isolated Vite production build.

| Gate | Result |
| --- | --- |
| TypeScript compilation | **PASSED** as the `tsc -b` stage of `npm run build:modeling` |
| Isolated non-HMR production build | **PASSED** with the multi-entry `tests/bureauMetadataIntegration.vite.config.ts` and external output root |
| Production output | 146 files; SHA-256 `27f1f2f1699dc30146a1f16fadd5c4ae0d1272a0ec92afcdfb0b2b7acfaf9062` |
| HMR/development marker scan | **PASSED**; `/@vite/client`, `@react-refresh`, `import.meta.hot`, and `__vite_ping` absent |
| Final Python compilation | **PASSED**; `compileall server scripts tests` exit 0 |
| Final whitespace/diff validation | **PASSED**; `git diff --check` exit 0 |

The progress evidence recorded `production_frontend_built` at run elapsed 100.969 seconds. That elapsed value includes prior run setup and is not represented as a standalone build benchmark.

## 23. Browser acceptance results

**Actual isolated headed production-browser acceptance: PASSED.**

Run `production-auth-a9e0d4b45eb8428d88f5102c3949f953` executed three headed-browser phases against the isolated non-HMR frontend on port 53609 and isolated backend on port 53608:

| Phase | Authenticated reloads | Result |
| --- | ---: | --- |
| Initial | 26/26 | Passed |
| Timed operational window | 60/60 | Passed |
| Final post-soak | 26/26 | Passed |
| **Total** | **112/112** | **Passed** |

Every phase covered synthetic scenarios `A_exact`, `B_mixed_contradiction`, `C_no_entitlement`, `D_non_bureau`, and `E_multi_user`; six synthetic users; two synthetic providers; five synthetic projects; exact canonical EDA handoff; zero cross-user/project/provider contamination; no holdout access; and no training.

The combined browser network guard recorded 963 fetch/XHR requests, all 963 to the isolated backend, with zero unexpected fetch/XHR requests, WebSockets, blocked requests, or live-port contacts.

The integrated summary evidence checksum is `2999c6aeeaa2dcbb6f6cb369e1bcc5c73f73536ce8bfbb125a1e163faae3681`. The 48-event progress journal has SHA-256 `304dded84a518bab4081fea483b438d75ee00a12c3bb7dbf036d8423011c7a76`, and combined authenticated-reload evidence has checksum `08b78cdb366c58f251117f90e576e93712c3ca71a2b4509759f448443a88c3a4`.

Read-only evidence enumeration confirmed 57 PNG files totaling 5,014,249 bytes: 19 captures in each of the initial, timed-window, and final phases. Each phase contained seven authentication/authorization/isolation captures and these 12 integration captures:

- `bureau-metadata-compact-binding-summary.png`
- `bureau-metadata-entitled-catalog-selection.png`
- `bureau-metadata-crosswalk-table-all-states.png`
- `bureau-metadata-crosswalk-exact-state.png`
- `bureau-metadata-crosswalk-unresolved-state.png`
- `bureau-metadata-visible-contradiction.png`
- `bureau-metadata-table-first-special-review.png`
- `bureau-metadata-expanded-code-level-metadata.png`
- `bureau-metadata-project-c-no-entitlement.png`
- `bureau-metadata-project-d-non-bureau.png`
- `bureau-metadata-canonical-eda-handoff.png`
- `bureau-metadata-api-only-multi-user-isolation.png`

The evidence is stored beneath `C:\Users\james\AppData\Local\ATLAS\catalog-closeout-17f09fa69f51415997414ef1c1930d90\test-output-2512ef019a4244c3a03a34ffb2b920a9\production-auth-a9e0d4b45eb8428d88f5102c3949f953`. The run summary classifies it as synthetic-only with `contains_vendor_content: false`. Independent final artifact-content scanning passed as recorded in Section 25.

## 24. Thirty-minute soak results

**Actual uninterrupted 30-minute isolated soak: PASSED.**

The integrated run’s uninterrupted operational window used the same run ID and lasted 2029.64 seconds (33:49.640) against a configured 1800-second minimum. Its soak child `catalog-soak-20260806-174439-2d225e9b` recorded 1802.968 timed-soak seconds (30:02.968) and 2027.781 total elapsed seconds.

| Measure | Exact result |
| --- | ---: |
| Actual isolated backend listener restarts | 10 |
| Unique listener PIDs observed | 11; uniqueness verified |
| Restart recovery failures | 0 |
| Listener port closed before each restart | 10/10 |
| Exact catalog/crosswalk/checksum/entitlement recovery | 10/10 |
| Additional soak service reload cycles / child processes | 20 / 20 |
| Timed-window authenticated reloads | 60/60 |
| Total soak requests / successful requests | 13,386 / 13,048 |
| Unexpected failures / timeouts | 0 / 0 |
| Expected authorization denials | 254 |
| Expected concurrency conflicts | 84 |
| Crosswalk previews / decision writes | 1,291 / 625 |
| Timed crosswalk probes | 641 |
| Exact-identity negative checks | 800 |
| Catalog-version switches | 875 |
| Bounded operations | 11,112 |
| Expected tamper checksum failures | 4; unexpected checksum failures 0 |
| Cross-user/project/provider/tenant contamination | 0 / 0 / 0 / 0 |
| Inconsistent entitlement results / duplicate revisions | 0 / 0 |
| Temporary-entry / transient-root leaks | 0 / 0 |
| Live ports contacted / live project accessed / live service manipulated | false / false / false |
| Sealed holdout accessed | false |

The final summary reports `failures: []`, functional integrity true, configured and release thresholds met, tamper detection/cache eviction/recovery passed, and `passed: true`. RSS and handle measurements were unavailable and remain `null`; they are not reported as zero.

## 25. Source-safety scan results

Two source-safety suites passed in the broad run:

- `bureau-source-safety` — `tests/bureau_metadata_source_safety_scan_test.py`: 8 passed in 2.34 seconds; child duration 3.588342 seconds.
- `restricted-source-safety` — `tests/restricted_catalog_source_safety_test.py`: 12 passed in 0.64 seconds; child duration 1.743568 seconds.

These code/package tests support the prohibitions on raw provider sources in application paths, full catalogs in browser/MDD/evidence constants, physical restricted paths in APIs, implicit first/latest fallback, browser-authoritative entitlement, client-side authorization filtering, holdout reads, automatic treatment, and fabricated generic-name mappings.

Final strict scan `strict-source-scan-integrated-final-20260806.json` passed:

- scanner: `restricted-catalog-source-safety`;
- root label: `git-index`;
- inventory: 2,120 entries;
- screenshot OCR inventory: 244 entries;
- findings: 0;
- result: `passed: true`.

The integrated run was independently audited for its final screenshots: 57/57 expected PNGs were present and zero restricted-content leak hits were found. This agrees with the run’s `synthetic_integrated_catalog_closeout` classification and `contains_vendor_content: false` result.

## 26. Protected-authority before-and-after comparison

**PASSED — zero authoritative changes and zero supplementary changes.**

`live-protected-compare-integrated-final-20260806.json` used `logical_and_audit_authoritative` comparison and recorded:

- `passed: true`;
- `authoritative_change_count: 0`;
- `supplementary_change_count: 0`;
- no authoritative or supplementary change records.

Two baseline warnings were preserved rather than hidden: 14 pre-existing `project_access_to_user` relationship orphans in the global security authority, and an unavailable optional live crosswalk SQLite authority. They existed in the baseline, produced no before/after change, and did not invalidate the logical/audit-authoritative result. Whole-file SQLite hashing was supplementary, not the authoritative comparison mode.

The final integrated run also used 21 unique, disjoint mapped synthetic authority children; reported `live_authorities_opened: false`, `live_project_accessed: false`, and `sealed_holdout_accessed: false`; and recorded authority-map checksum `f94be838f525be4d49363233440e502c2275689998e958632ad9cf16d2b137a0`.

## 27. Live HELOC identity and partition comparison

**PASSED — exact identity and revision-1 Analysis Partition matched baseline.**

| Identity field | Final unchanged value |
| --- | --- |
| Project | `atlas-mrzpau4t` |
| Dataset | `ds_heloc_train_6bdb184b_05905` |
| Dataset version | `v_1785186305905_6bdb184b` |
| Dataset activation revision/status | 1 / `active` |
| Analysis Partition | `analysis-partition-688c2184b4e9b8181946-r1` |
| Partition revision/status | 1 / `current` |
| Target | `bad_flag` |
| Target contract | `target-contract-9a0bbd69645b7e5e0b4c` |
| Predictor authorization | `predictor-auth-491392549aa93a6ad258` |
| Population / development / holdout | 6,275 / 5,020 / 1,255 |
| Holdout state | `sealed` / isolation `verified` |
| Assignment hash | `ed04b51eef3ebfccc846ff742203978ae0463ee871807c6045595b68106bb6c5` |
| Artifact hash | `688c2184b4e9b8181946766e2577c1f1a53f9c88de2adf81a1d3affbc8dcd5fa` |
| Population fingerprint | `0d81ad64bb8ac0b0314abb28a05b94c74e6dc97138ff05ddbb864440d081875a` |

The protected comparison recorded no changes. The integrated run opened no live project/authority, accessed no sealed holdout, and started no training.

## 28. Port and process closeout

The final integrated run used dynamically selected non-live ports 53608 (backend) and 53609 (static frontend). Progress event `isolated_runtime_torn_down` records `isolated_ports_closed: true`, ten restart cycles, and no failure. The summary separately records zero live-backend and live-frontend contacts, no live-service manipulation, and no non-orchestrated client contact.

| Required check | Result |
| --- | --- |
| Isolated backend port 53608 closed after teardown | **PASSED** |
| Isolated static-frontend port 53609 closed after teardown | **PASSED** |
| Ten isolated listener restart cycles and recovery | **PASSED; 10/10, 11 unique listener PIDs** |
| Acceptance network contact with ports 8001/5174 | **PASSED; zero contacts** |
| Run manipulated a live service | **PASSED; `false`** |
| Isolated build contains Vite/HMR markers | **PASSED; none found** |
| Port `5174` final listener count | **PASSED; 0** |
| Normal Vite/HMR listener | **PASSED; none on 5174** |
| Orchestrated isolated acceptance services remain | **PASSED; torn down and isolated ports closed** |
| Live backend process identity | **PASSED; PID 89928, same uvicorn process and start time** |
| Port `8001` final listener | **PASSED; PID 89928 owns the listener** |

A transient read-only socket observation found no port-8001 `LISTEN` entry while PID 89928 remained alive. The PID never exited, and the listener returned under the same PID and process start time without agent action. Final OS-level evidence therefore reconciles the transient observation: the live backend was not stopped, restarted, contacted, redirected, or reconfigured by the run.

## 29. Repository working-tree classification

Final read-only Git classification:

| Field | Result |
| --- | --- |
| Branch | `codex/phase2a-canonical-lineage` |
| HEAD | `938c5b1e2d5b4f81f2b35acc11a048a9b8a04d62` |
| Working-tree status entries | 163 |
| Staged/index entries | 0 |
| Tracked deletions | 0 |
| Untracked entries | 112 |
| `git diff --check` | exit 0 |
| Source/Git mutation by integrated run | `false` |
| Final source snapshot | 998 files |
| Source aggregate SHA-256 | `460ca50076225341c071ba5cb1b68df2d9fdf011120dbf6b42432acd02d0d4c0` |

The working tree remains intentionally dirty with reviewed and unrelated pre-existing work; the empty index proves nothing was staged. Nothing was committed, pushed, reset, restored, cleaned, amended, stashed, deleted, or discarded by this closeout.

## 30. Files safe for a future commit slice

All closeout gates have passed, but staging still requires James’s explicit authorization and a deliberate review of the dirty tree. Candidate review slices are:

1. exact binding, crosswalk governance, consistency, bounded semantic, Evidence/MDD backend contracts and their focused Python tests;
2. Data Acquisition binding/crosswalk UI, provenance presentation, table-first Special-Value integration, clients, and focused Node tests;
3. bounded EDA handoff validation and focused cross-phase tests;
4. isolated acceptance/safety harnesses and sanitized documentation, including this report after placeholders are replaced.

Section 15 and Section 17 are candidate scope inventories only. Nothing in this report authorizes staging or committing every listed path.

## 31. Files that must never be staged

Do not stage:

- `Experian_Premier_Credit_Bureau.pdf`;
- `credit_bureau_premier.csv`;
- installed restricted catalog data, registry payloads containing restricted content, installation journals, or physical restricted-storage paths;
- raw datasets, holdout membership, live project links, live workflow checkpoints, evidence registries, or live database/WAL/SHM/journal files;
- credentials, tokens, cookies, browser profiles, downloads, connection strings, environment dumps, or screenshots containing real provider definitions;
- unrestricted catalog exports, complete catalog fixtures, caches, logs, runtime/test-output roots, build output, temporary acceptance profiles, or external hermetic run roots;
- unrelated dirty-tree content not deliberately reviewed for the selected slice.

## 32. Remaining limitations

- The isolated headed-browser acceptance, 112 authenticated reloads, ten listener restarts, uninterrupted 30-minute soak, TypeScript/production build, and isolated-service teardown passed.
- Per-route catalog-summary/mapped-batch/search/crosswalk latency, response payload size, and SQL query-count measurements were not separately emitted; only aggregate latency and bounded operation/event counts are available. The observed aggregate latency was not evaluated against a separate release SLA.
- RSS and handle observations were unavailable and correctly recorded as `null`, not zero.
- The protected comparison retained two non-changing baseline warnings: 14 pre-existing security relationship orphans and an unavailable optional live crosswalk SQLite authority.
- The broad runner’s run-level `cross_child_isolation` check recorded `not-run`; the dedicated storage scanner/guard, 21-root integrated isolation, network guard, service teardown, and protected-authority comparison all passed.
- Generic HELOC-style fields correctly remain unresolved without approved mapping evidence; this is governance behavior, not a missing automatic-mapping feature.
- The crosswalk revision adapter reuses an internal source-identity validator because the governance service has no separate public revision-validation method; that remains bounded technical debt.
- The working tree remains intentionally dirty with 163 status entries, including 112 untracked entries. The index is empty; any future commit slice still requires deliberate review and James’s authorization.

Final closeout explicitly confirms:

- no fabricated authoritative HELOC mapping was created;
- no catalog-driven treatment was silently selected or applied;
- no dataset value was mutated;
- no predictor was removed;
- no feature manifest changed;
- the live Analysis Partition remained `analysis-partition-688c2184b4e9b8181946-r1`, revision 1;
- no Training, Evaluation, Interpretation, promotion, or Scoring occurred;
- migration `0028` retained checksum `2256c1afd0ee4b8667dcadca4422950b29144a7745b48394e83d1c2b72f672c8` and remained unapplied live;
- port 5174 had zero listeners;
- the live backend listener on port 8001 remained PID 89928 with the same process identity/start time and received no acceptance traffic or manipulation;
- isolated ports 53608 and 53609 were closed;
- the Git index remained empty;
- nothing was staged, committed, pushed, reset, restored, cleaned, amended, stashed, deleted, or discarded.

All required release gates are green. The selected permitted verdict is **READY FOR MANUAL DATA ACQUISITION ACCEPTANCE**.

## 33. Manual checklist for James

After automated closeout is complete and James later starts the normal frontend himself:

1. Start the normal frontend manually.
2. Open the HELOC Data Acquisition page.
3. Confirm the exact dataset and version remain current.
4. Confirm the current Analysis Partition remains revision 1.
5. Confirm the Bureau Metadata section is visible and compact.
6. Confirm ATLAS does not fabricate Experian mappings for generic HELOC names.
7. Confirm observed special-value treatments remain available.
8. Confirm catalog mapping status and evidence are understandable.
9. Confirm the Special-Value Review remains table-first.
10. Confirm EDA receives the exact dataset/version/target/partition identity.
11. Confirm no new partition, treatment, or catalog-binding revision was created merely by viewing the pages.

**Final verdict: READY FOR MANUAL DATA ACQUISITION ACCEPTANCE.**
