# ATLAS Bureau Metadata Data Acquisition Integration Report

Date: 2026-08-05  
Scope: controlled, exact-version Bureau Metadata Catalog integration into Data Acquisition and the bounded downstream semantic handoff  
Status while this report was prepared: **PENDING FROZEN-SOURCE CLOSEOUT**

This report records the implemented contracts that are visible in the current working tree. It does not turn an unexecuted closeout gate into a pass. The only permitted final `READY` verdict requires the broad frozen-source regression, isolated production-browser acceptance, uninterrupted 30-minute soak, performance measurements, protected-authority comparison, and final port/process verification to be completed by the closeout owner.

## 1. Sources reconciled

The current repository was reconciled with these six historical authorities:

1. `BUREAU_METADATA_CATALOG_FOUNDATION_REPORT_2026-08-04.md`
2. `BUREAU_METADATA_CATALOG_OPERATIONALIZATION_REPORT_2026-08-05.md`
3. `BUREAU_METADATA_ENTITLEMENT_AND_CROSSWALK_CONTRACT_2026-08-05.md`
4. `BUREAU_METADATA_MANUAL_ACCEPTANCE_CHECKLIST_2026-08-05.md`
5. `DATA_ACQUISITION_FINAL_ACCEPTANCE_REPAIR_2026-08-04.md`
6. `DATA_ACQUISITION_INFORMATION_ARCHITECTURE_REPORT_2026-08-03.md`

The repository is authoritative where implementation has advanced beyond those reports. The foundation and operationalization results remain historical evidence; they do not substitute for this integration phase's pending closeout gates.

## 2. Initial repository and process boundary

The integration was performed in an already dirty working tree containing substantial pre-existing product, test, documentation, runtime-artifact, and restricted-source work. No attempt was made in this documentation task to reclassify unrelated changes or to rewrite historical results.

Required runtime boundary for final closeout:

- normal Vite/HMR port `5174` must remain closed;
- the live backend on port `8001` must remain running and untouched;
- browser acceptance must use an isolated production build and isolated backend on non-live ports;
- every mutable test authority must be isolated before application imports;
- any isolated-browser contact with the live backend, or live-browser contact with the isolated backend, is a stop condition.

Process verification for the final frozen source is **PENDING**. This report does not claim that the final listener inventory or closeout checks have run.

## 3. Current catalog architecture

The implementation reuses the established provider-neutral catalog stack:

- restricted catalog installation and checksum verification;
- exact catalog registry identity and lifecycle;
- backend project authorization plus catalog entitlement;
- bounded catalog list, health, search, exact attribute, availability, and special-value reads;
- exact dataset-version catalog-binding revisions;
- immutable governed crosswalk revisions;
- bounded semantic annotations for accepted exact or alias mappings;
- bounded Evidence Center and MDD projections that store identities, counts, checksums, and limitations rather than a proprietary catalog dump.

The browser never becomes catalog, entitlement, binding, crosswalk, or treatment authority. It receives bounded projections and sends explicit analyst intent.

## 4. Before-and-after Data Acquisition flow

Historical Data Acquisition flow:

```text
Dataset registration
  -> bureau detection
  -> observed Special-Value Review
  -> predictor authorization
  -> Analysis Partition readiness
  -> Data Acquisition completion
  -> canonical EDA handoff
```

Current controlled flow:

```text
Exact registered dataset version
  -> bureau detection or explicit metadata review
  -> exact entitled catalog selection
  -> nonmutating binding preview
  -> explicit binding confirmation and bounded evidence/MDD record
  -> server-rebuilt field crosswalk candidates
  -> explicit analyst mapping decisions
  -> exact crosswalk revision pinned by a new binding revision
  -> bounded consistency reconciliation
  -> bounded semantic annotations
  -> table-first observed Special-Value Review
  -> predictor authorization
  -> unchanged Analysis Partition contract
  -> exact canonical EDA handoff
```

The Bureau Metadata Binding panel appears only for detected bureau context, an existing binding, or explicit user review. It is located immediately before the existing table-first `BureauReviewPanel`. A non-bureau or unbound workflow remains usable without catalog semantics.

## 5. Dataset-version catalog-binding contract

The binding scope is tenant, project, `dataset_id`, and `dataset_version_id`; display names are not substitutes. The bound identity pins activation revision, schema checksum, target contract, predictor authorization, exact catalog version/key/checksum, status, actor, server timestamp, evidence, and optional crosswalk ID/revision.

Confirmation is a two-step contract:

1. Preview validates exact lineage, catalog checksum, entitlement, and expected revision without persistence or workflow mutation.
2. Confirm requires the exact preview checksum, optimistic expected revision, and analyst rationale. It creates or revises the binding and persists bounded Evidence Center and MDD references before reporting success.

Identical retries are idempotent. First/latest catalog fallback, browser-cached selection, display-name substitution, cross-tenant lookup, and unentitled versions fail closed.

## 6. Nine-state crosswalk model

The implementation preserves the established persisted state names:

| Persisted state | Meaning | Can provide provider-authoritative semantics? |
| --- | --- | --- |
| `exact_verified` | Exact provider code was explicitly reviewed and supported by exact catalog evidence | Yes, after analyst confirmation |
| `approved_alias` | An institutional alias was explicitly approved with alias evidence | Yes, after analyst confirmation |
| `transformed_or_derived` | Field is transformed or derived and carries transformation lineage | No raw-provider equivalence |
| `probable_review_required` | Candidate exists but requires analyst review | No |
| `ambiguous_review_required` | Multiple candidates remain plausible | No |
| `recoding_evidence_required` | Candidate requires durable recoding/lineage evidence | No |
| `unresolved` | No supported mapping exists | No |
| `out_of_catalog` | Analyst recorded that the field is outside the selected catalog | No |
| `rejected` | Analyst rejected the candidate | No |

All server-generated initial candidates remain review-required or unresolved. Exact-name evidence may produce a candidate, but it does not auto-confirm authority. Generic HELOC-style names are not assigned provider meanings without explicit evidence.

## 7. Crosswalk decision, binding-link, and partial-state behavior

The server rebuilds candidate evidence from the exact current binding, exact catalog checksum, and verified predictor authorization. Target, deterministic target-source fields, and excluded predictors do not enter the candidate inventory.

Every decision request uses the exact current crosswalk revision and binding revision. A successful decision:

1. appends immutable crosswalk governance;
2. appends a binding revision that pins the exact governance ID/revision;
3. persists bounded evidence and MDD records;
4. returns explicit false mutation flags.

If governance persists but binding append fails, the API returns `partial_metadata_state: true`, `governance_persisted: true`, and `binding_linked: false`. If binding succeeds but Evidence/MDD persistence fails, it returns a partial state with `binding_linked: true` and `documentation_persisted: false`. The exact retry endpoint completes the missing operation idempotently. A partial response is never reported as success.

## 8. Special-Value table integration and exact UI wording

The catalog enriches rather than replaces the table-first Special-Value Treatment Review. Observed counts, population burden, event-rate behavior, treatment selection, rationale, and review state remain separate from catalog semantics.

Current source labels are exactly:

- `Provider catalog definition`
- `Analyst-approved crosswalk`
- `Dataset-observed behavior`
- `ATLAS heuristic detection`
- `Unverified candidate`

Current unresolved-field wording is exactly:

> No authoritative catalog mapping is available for this field. ATLAS will continue to show observed special-value behavior, but it will not assign a provider definition without approved mapping evidence.

Current no-entitlement heading is exactly:

> No entitled bureau catalog version is available.

Its supporting text states that ATLAS has not created an authoritative mapping and that the existing Special-Value Review remains separate and unchanged.

The binding panel also states:

> Binding metadata does not choose special-value treatments or change downstream workflow state.

No catalog decision silently selects, applies, confirms, or materializes a special-value treatment.

## 9. Consistency reconciliation

The exact-bound consistency endpoint compares accepted exact/alias mappings with backend-authoritative structural summaries. It does not read raw rows, browser preview data, or the final holdout.

Result states are:

- `consistent`
- `consistent_with_observed_unused_codes`
- `review_required`
- `contradictory`
- `metadata_unavailable`
- `mapping_unresolved`

Checks cover compatible datatype family, field length when comparable, ordinary range, defined/observed special codes, and bounded metadata availability. Contradictions block metadata-derived recommendations. Provider-defined but unobserved special codes are not treated as contradictions. Unresolved and review-required mappings cannot expose provider-authoritative definitions.

## 10. API contracts

All paths below are under `/api` and require backend authentication. Project routes additionally require exact project access and catalog entitlement.

### Catalog reads and administration

- `GET /bureau-catalogs`
- `GET /bureau-catalogs/{catalog_version_id}/health`
- `GET /bureau-catalogs/{catalog_version_id}/attributes`
- `GET /bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}`
- `GET /bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}/special-values`
- `GET /bureau-catalogs/{catalog_version_id}/attributes/{attribute_code}/availability`
- existing `/admin/bureau-catalogs...` routes remain administrator-only

### Exact binding

- `GET /projects/{project_id}/datasets/{dataset_id}/versions/{dataset_version_id}/bureau-metadata/binding`
- `POST .../bureau-metadata/binding/preview`
- `POST .../bureau-metadata/binding/confirm`
- `GET .../bureau-metadata/binding/history?limit=...`

### Governed crosswalk and semantic handoff

- `GET .../bureau-metadata/crosswalk/preview`
- `GET .../bureau-metadata/crosswalk/current`
- `GET .../bureau-metadata/crosswalk/history?limit=...`
- `POST .../bureau-metadata/crosswalk/decisions`
- `POST .../bureau-metadata/crosswalk/binding-link`
- `GET .../bureau-metadata/crosswalk/semantic-annotations`
- canonical alias: `GET .../bureau-metadata/annotations`
- `GET .../bureau-metadata/crosswalk/consistency`

Histories, search results, mapped-field reads, annotations, and consistency results are bounded. No route exports the complete provider catalog or raw dataset rows.

Safe failure classes are structured as authorization `403`, unavailable exact resource `404`, stale/conflicting lineage `409` (or exact preview precondition failure where applicable), request validation `400/422`, and operational unavailability `503`. Error bodies do not disclose restricted descriptions, catalog counts through differential errors, physical restricted paths, credentials, or another tenant's identity.

## 11. Entitlement and tenant isolation

Project access and catalog entitlement are independent requirements. Neither implies the other. Cache and durable identities include tenant/principal/project/catalog-version dimensions as required by the underlying service. Revocation makes current restricted semantics unavailable without erasing immutable binding/crosswalk history. Client-side control visibility is presentation only, never authorization.

Final security and cross-tenant browser acceptance are **PENDING**.

## 12. Evidence and MDD contract

`record_binding_evidence_and_documentation` stores a bounded projection containing exact dataset and catalog lineage, binding/crosswalk revision references, entitlement verification, mapping-state counts, special-value separation rules, treatment-policy limitations, actor, and server timestamp.

It explicitly records that:

- true nulls and ordinary outliers remain separate from provider special values;
- metadata informed treatment but did not select or apply it;
- dataset, target contract, treatment, predictor authorization, Analysis Partition, and feature manifest were not mutated;
- the proprietary provider catalog was not embedded.

Binding confirmation and successful crosswalk decision/link completion do not report success until the bounded Evidence Center and MDD projections persist. Repeated exact confirmation is deterministic and idempotent.

## 13. Canonical downstream handoff

The canonical semantic envelope pins project, dataset, version, schema checksum, exact catalog version/key/checksum, binding ID/revision/checksum, crosswalk ID/revision/checksum, and annotation-set checksum. Only analyst-confirmed `exact_verified` and `approved_alias` decisions may include provider-authoritative description, datatype, units, range, and special-code definitions.

The implementation performs one bounded exact entitled batch read for accepted mapped attributes, avoiding per-cell or per-row catalog requests. Unresolved, stale, contradictory, or unentitled metadata is not promoted to authoritative analytical input.

EDA validates the exact annotation identity and nonmutation contract. Optional absence remains nonblocking; stale or contradictory metadata fails closed. The handoff does not change EDA row scope, development membership, target intelligence, predictor authorization, feature manifest, Analysis Partition, or holdout isolation.

## 14. Performance design and measurements

Implemented design controls include bounded server-side catalog search, bounded mapped-attribute batch retrieval, deterministic ordering, catalog-checksum and crosswalk-revision lineage, bounded descriptions and special definitions, and no full-catalog browser state or Evidence/MDD payload.

Final measured results are **PENDING**:

| Required metric | Final frozen-source result |
| --- | --- |
| Data Acquisition catalog summary latency | **PENDING** |
| Mapped-field batch latency | **PENDING** |
| Catalog search p50 / p95 | **PENDING** |
| Crosswalk preview p50 / p95 | **PENDING** |
| Payload sizes | **PENDING** |
| Query counts / N+1 check | **PENDING** |
| Cache hit behavior | **PENDING** |
| Memory / handle observations | **PENDING; do not report unavailable values as zero** |

## 15. Current controlled-integration files

The current integration-specific production set observed while preparing this report is:

### Backend

- `server/bureau_metadata/catalog_binding.py`
- `server/bureau_metadata/catalog_binding_repository.py`
- `server/bureau_metadata/catalog_binding_service.py`
- `server/bureau_metadata/catalog_binding_router.py`
- `server/bureau_metadata/catalog_documentation.py`
- `server/bureau_metadata/catalog_consistency.py`
- `server/bureau_metadata/crosswalk_router.py`
- `server/bureau_metadata/operational_service.py`
- `server/bureau_metadata/semantic_annotation.py`
- `server/eda/bureau_semantic_contract.py`
- `server/eda/eda_router.py`
- `server/eda/workspace_service.py`
- `server/eda/workspace_types.py`
- `server/eda/analytical_contract.py`
- `server/main.py`

### Frontend

- `src/components/BureauMetadataBindingPanel.tsx`
- `src/components/BureauMetadataCrosswalkWorkspace.tsx`
- `src/components/BureauReviewPanel.tsx`
- `src/lib/bureauMetadata.ts`
- `src/lib/bureauSemanticAnnotations.ts`
- `src/lib/dataAcquisitionEdaHandoff.ts`
- `src/steps/Step01_DataAcquisition.tsx`
- `src/steps/Step02_EDA.tsx`

### Focused integration tests and harness assets

- `tests/bureauMetadataBindingPanel.test.mjs`
- `tests/bureauMetadataCrosswalkWorkspace.test.mjs`
- `tests/bureauSemanticAnnotationsFrontend.test.mjs`
- `tests/bureau_metadata_catalog_binding_test.py`
- `tests/bureau_metadata_catalog_binding_router_test.py`
- `tests/bureau_metadata_catalog_documentation_test.py`
- `tests/bureau_metadata_crosswalk_router_test.py`
- `tests/bureau_metadata_mapped_batch_test.py`
- `tests/eda_bureau_semantic_handoff_test.py`
- `tests/bureauMetadataIntegration.production.acceptance.mjs`
- `tests/bureauMetadataIntegration.isolated.entry.tsx`
- `tests/bureauMetadataIntegration.isolated.entry.html`
- `tests/bureauMetadataIntegration.vite.config.ts`
- `tests/bureau_metadata_integration_runtime_app.py`

The repository contains additional foundation, operationalization, and unrelated dirty-tree files. This list is not permission to stage every dirty path.

## 16. Migrations

No database migration was added for this controlled integration. Existing durable authorities were reused. Migration `0028` is outside this phase and must remain unchanged and unapplied live. Final checksum verification is **PENDING**.

## 17. Focused validation already observed

The following bounded results were actually observed during implementation and may be cited without converting broader gates to green:

- crosswalk router, source-safety, catalog documentation, crosswalk governance, and mapped-batch group: **58 passed**;
- hermetic `HERMETIC_REGRESSION` crosswalk-router run `atlas-hrt-20260806-031636-db1c1b3709`: **7 passed**;
- scoped Python compilation for crosswalk/semantic/operational modules: passed;
- scoped `git diff --check`: passed.

These are focused results, not the final broad regression.

## 18. Frozen-source closeout placeholders

The closeout owner must replace each placeholder with exact command, counts, runtime, evidence root, and result from one frozen source state.

| Gate | Status |
| --- | --- |
| Complete backend regression | **PENDING** |
| Complete frontend regression | **PENDING** |
| Cross-phase DA, EDA, Outliers, Missing Values, Feature Engineering, Analysis Partition, MDD, Evidence, routing, identity suites | **PENDING** |
| Security gate | **PENDING** |
| Storage-isolation scanner and guard | **PENDING** |
| TypeScript compilation | **PENDING** |
| Production build | **PENDING** |
| Python compilation | **PENDING** |
| Final `git diff --check` | **PENDING** |
| Isolated production-browser acceptance and sanitized screenshots | **PENDING** |
| Uninterrupted 30-minute authenticated soak | **PENDING** |
| Performance and payload measurements | **PENDING** |
| Source/package safety scan | **PENDING** |
| Layered protected-authority comparison | **PENDING** |
| Live HELOC identity/partition comparison | **PENDING** |
| Isolated service shutdown and port closure | **PENDING** |
| Port `5174` remains closed | **PENDING FINAL CHECK** |
| Live backend `8001` remains untouched | **PENDING FINAL CHECK** |

## 19. Production-browser acceptance still required

Acceptance must cover synthetic exact-match, mixed-state, no-entitlement, non-bureau, and multi-user/multi-project fixtures. It must prove no route reload or scroll reset; visibly separate provider definitions, approved crosswalk evidence, observed behavior, heuristics, and candidates; preserve table-first treatments; reject fabricated generic-name mappings; verify exact EDA identity; and make no holdout request or downstream workflow action.

Screenshot paths and browser results: **PENDING**.

## 20. Thirty-minute soak still required

The new integration soak must start at zero and run uninterrupted for at least 30 minutes against only isolated production services and synthetic authorities. It must include authenticated reloads, backend restarts, binding/crosswalk reads and writes, bounded search and batch reads, optimistic conflicts, entitlement grant/revoke transitions, multi-user isolation, EDA handoff retrieval, cancellation/retry, and malformed/contradictory requests.

Soak run ID, elapsed time, request counts, restart counts, failure/isolation results, and memory/handle observations: **PENDING**.

## 21. Protected-authority and live-state comparison

The final layered comparison must verify critical logical records, immutable hashes, and append-only audit counts before and after the frozen-source run. It must separately confirm the approved live project/dataset/version identity and Analysis Partition revision/membership/checksums are unchanged, migration `0028` is unchanged and unapplied live, no live audit row was added, and no sealed-holdout access occurred.

Final comparison: **PENDING**. No protected-authority conclusion is invented here.

## 22. Safe future commit slice

After every pending gate is green and James explicitly authorizes staging, the safest review sequence is:

1. exact binding, crosswalk, bounded semantic, consistency, Evidence/MDD backend contracts and focused Python tests;
2. Data Acquisition binding/crosswalk UI, table-first semantic presentation, client contracts, and focused frontend tests;
3. narrow EDA handoff validation and focused cross-phase tests;
4. isolated acceptance harness and sanitized documentation.

Each slice must be reviewed against the actual final dirty tree. Do not use this outline as authorization to stage or commit.

## 23. Never-stage content

The following must never enter a normal source commit:

- `Experian_Premier_Credit_Bureau.pdf`
- `credit_bureau_premier.csv`
- installed restricted catalog data, registry payloads containing restricted content, installation journals, or physical restricted-storage paths;
- raw datasets, holdout membership, browser profiles, cookies, credentials, tokens, connection strings, environment dumps, screenshots containing real provider definitions, or unrestricted catalog exports;
- live database files, WAL/SHM/journal files, live project links, workflow checkpoints, evidence registries, runtime artifacts, test-output roots, logs, caches, build output, or temporary acceptance profiles;
- any unrelated dirty-tree artifact not deliberately reviewed for the selected slice.

## 24. Remaining limitations

- Final broad regression and frozen-source closeout have not yet been recorded in this report.
- Production-browser UX and no-leak acceptance remain pending.
- The new integration-specific 30-minute soak remains pending.
- Final latency, payload, query-count, cache, memory, and handle measurements remain pending.
- Final protected-authority and port/process comparisons remain pending.
- Generic HELOC-style fields correctly remain unresolved without approved mapping evidence; this is a governance outcome, not a missing automatic mapping feature.
- The crosswalk revision adapter currently reuses an internal source-identity validator because the governance service has no separate public revision-validation method; this is bounded technical debt, not permission to weaken validation.

## 25. Manual checklist for James

After automated closeout is complete and James later starts the normal frontend himself:

1. Open the HELOC Data Acquisition page.
2. Confirm the exact dataset and dataset version remain current.
3. Confirm the current Analysis Partition remains revision 1.
4. Confirm the Bureau Metadata Binding section is compact and understandable.
5. Confirm generic HELOC names were not assigned fabricated provider mappings.
6. Confirm observed special-value treatments remain available without a catalog mapping.
7. Confirm binding, crosswalk, mapping evidence, and consistency states are understandable.
8. Confirm Special-Value Review remains table-first and inline treatments remain usable.
9. Confirm provider definitions, approved crosswalk evidence, observed behavior, heuristics, and unverified candidates are visibly distinct.
10. Confirm EDA receives the exact dataset/version/target/partition and bounded metadata identity.
11. Confirm viewing pages alone creates no new partition, treatment, predictor, feature-manifest, binding, or crosswalk revision.

## 26. Interim verdict

**PENDING FROZEN-SOURCE CLOSEOUT — DO NOT ISSUE A READY VERDICT YET.**

The implementation contracts and focused crosswalk evidence are documented, but the required broad regression, isolated browser acceptance, uninterrupted 30-minute soak, performance results, protected-authority comparison, and final port/process closeout are still pending. The closeout owner must select the final permitted verdict only after those results are recorded truthfully.
