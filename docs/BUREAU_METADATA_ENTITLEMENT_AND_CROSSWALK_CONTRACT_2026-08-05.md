# ATLAS Bureau Metadata Entitlement and Crosswalk Contract

Date: 2026-08-05  
Scope: restricted Bureau Metadata Catalog operationalization  
Status: implementation contract for the current closeout source

## 1. Purpose and boundary

This document defines the authorization, entitlement, cache-isolation, and governed crosswalk rules implemented by the Bureau Metadata Catalog phase. It is deliberately provider-neutral and contains no complete catalog, proprietary descriptions, unrestricted special-value collection, or physical restricted-storage location.

The catalog is a restricted metadata authority. An ATLAS role, project permission, or visible frontend route is never by itself a catalog license grant. Catalog access is decided by the backend against an exact principal, tenant, catalog version, checksum, and operation. Project-scoped crosswalk work adds an independent project and dataset-lineage check.

This phase does not integrate catalog decisions into Data Acquisition or any other Predictive Modeling workflow page. A preview or governed decision records evidence and review state only; it does not change a dataset, target contract, predictor authorization, feature set, treatment, partition, or workflow completion state.

## 2. Authoritative identities

### 2.1 Catalog identity

One catalog version is identified by all of the following:

- provider;
- product;
- edition;
- source or dictionary version;
- exact normalized catalog SHA-256 checksum; and
- durable `catalog_version_id`.

The service performs exact lookup only. It does not select a first, latest, neighboring, or similarly named catalog version. A catalog version must be active and integrity-verified before ordinary restricted content reads are authorized; bounded inventory and administrative integrity revalidation may expose lifecycle status without serving definitions. License metadata must also allow the requested content operation.

### 2.2 Project and dataset identity

The production HTTP candidate-preview contract is pinned to:

- `project_id`;
- `dataset_id`;
- `dataset_version_id`;
- exact schema checksum;
- exact catalog key and checksum; and
- caller-supplied target and deterministic target-source field exclusions.

The preview route verifies the exact durable project-to-dataset link and registered schema. It does not currently accept or persist a dataset activation revision, target-contract ID, or predictor-authorization ID. Its target exclusions are bounded request inputs, not substitutes for those governed identifiers.

The separately composed governed-crosswalk contract carries the fuller lineage: project, dataset, dataset version, positive activation revision, target-contract identity, predictor-authorization identity, exact schema checksum, exact catalog key and checksum, and source candidate-crosswalk identity. Any mismatch between supplied and current lineage fails closed for current-state operations. There is no browser-state, checkpoint, first-version, or latest-version fallback.

## 3. Principal classes and effective permissions

| Principal class | Required authorities | Permitted behavior | Explicitly prohibited behavior |
| --- | --- | --- | --- |
| Catalog administrator | Authenticated ATLAS administrator role plus an active, unexpired entitlement for the exact catalog version; mutating administrative operations require the backend administrative gate | View entitled inventory; validate exact-version integrity; inspect bounded definitions; grant or revoke bounded entitlements; retire an exact version using revision-aware state | Administration by role alone; access to an unentitled version; bulk export; path disclosure; implicit version selection; project or dataset mutation |
| Entitled catalog reader | Authenticated principal, exact tenant match, active unexpired entitlement, exact catalog version and checksum, and the requested operation in the grant | Use only the granted bounded catalog-only operations, such as health, exact lookup, bounded search, attribute-specific special-value lookup, or candidate analysis | Administration; use of operations absent from the grant; reuse of another principal's or tenant's grant; unrestricted enumeration or export |
| Project user without catalog entitlement | Authenticated principal with project access but no matching catalog grant | Use ordinary project capabilities outside this restricted catalog contract | Retrieve restricted definitions, special values, catalog identity, or crosswalk candidates merely because project access exists |
| Unauthorized or unauthenticated user | None | No restricted catalog operation | Any catalog content, catalog administration, project schema disclosure, or crosswalk evidence; responses use the established safe authentication or authorization convention |
| Entitled reader without project access | Exact catalog entitlement but no permission for the requested project | Catalog-only operations expressly present in the grant | Project schema resolution, project crosswalk preview, governed crosswalk reads, or governed decision writes |

Frontend route visibility is only a usability gate. The backend independently authenticates every route and enforces roles and entitlements. A non-admin route denial must not make a catalog request or change active project or dataset state.

## 4. Entitlement contract

### 4.1 Grant identity

An entitlement binds exactly:

- `principal_id`;
- `tenant_id`, including an exact distinction between a tenant value and no tenant;
- `catalog_version_id`;
- the catalog checksum current at grant time;
- a non-empty bounded set of operations;
- active or revoked status;
- optional timezone-aware expiry; and
- grant/revocation actors and timestamps.

Supported operation grants are:

- `catalog_health`;
- `manifest_read`;
- `attribute_lookup`;
- `special_value_lookup`;
- `value_classification`; and
- `crosswalk_candidate`.

An unsupported, empty, expired, revoked, cross-tenant, cross-principal, wrong-version, wrong-checksum, or wrong-operation grant is denied. The safe denial does not disclose whether the requested restricted object exists.

### 4.2 Enforcement order

For ordinary catalog-only access, the backend:

1. resolves the authenticated principal and tenant;
2. resolves the requested exact catalog version;
3. verifies an active entitlement for the exact principal, tenant, version, checksum, and operation;
4. verifies active lifecycle and integrity state;
5. accesses the exact checksum-qualified cache or stored artifact; and
6. enforces the catalog license operation gate.

For project-scoped crosswalk preview, project authorization and the exact durable project-to-dataset link are resolved before catalog candidate access. The supplied schema checksum must match the registered dataset version. Only then may the exact catalog entitlement be evaluated and the bounded preview be built.

For governed crosswalk operations, the service enforces, in order:

1. the access context names the same exact project;
2. the project authorization provider grants `view` or `edit` as required;
3. an exact `crosswalk_candidate` catalog entitlement is valid for the same principal, tenant, key, and checksum;
4. the supplied lineage matches the current lineage for current-state operations; and
5. the requested repository read or append uses the exact governance identity and revision.

Project denial occurs before catalog entitlement or governed-repository access. Catalog denial occurs before repository access. This order prevents a caller from learning project schema, catalog content, or governance history through a failed cross-boundary request.

### 4.3 Administrative authority

Catalog administration requires both the ATLAS `admin` role and exact catalog entitlement. The administration inventory is entitlement-filtered. Integrity validation, retirement, entitlement grant, and entitlement revoke are backend-authorized independently; client-side role checks do not replace those gates.

Retirement changes only the exact selected registry version. The registry and HTTP request contract support caller-supplied `expected_revision`; stale supplied revisions fail with a conflict. The current administration client does not yet send that value, so the server substitutes the exact version's current revision. The UI therefore does not demonstrate a stale-revision conflict. Retirement does not delete the restricted catalog bytes or rewrite prior crosswalk lineage.

## 5. Bounded API and disclosure contract

The operational surface provides bounded version listing, health, search, exact attribute lookup, attribute-specific special-value lookup, availability metadata, integrity validation, entitlement administration, and project-scoped crosswalk preview.

The surface does not provide:

- full-catalog export or download;
- unrestricted empty-query enumeration;
- unrestricted special-value export;
- physical storage paths;
- a browser-readable catalog artifact;
- a provider-global special-value meaning table;
- similar-code or latest-version fallback; or
- client-side authorization as an authority.

Search has bounded query length, offset, page size, and server-side deadline. Exact attribute lookup either returns the exact normalized code or a safe not-found response. Special-value definitions remain scoped to the exact attribute and exact catalog version.

## 6. Cache isolation

The loaded-catalog cache is a small, thread-safe LRU keyed by the complete catalog key and exact checksum. It stores only an already checksum-verified catalog snapshot; it does not store or confer a user's grant.

Authorization is deliberately evaluated before every loader or cache access. Revocation and expiry therefore take effect on the next call even when the requested catalog bytes are already cached. A principal cannot reuse another principal's or tenant's authorization through a shared cache entry.

The operational-service instance cache is keyed by the canonical restricted-catalog authority and canonical registry authority together. A root change clears the prior service cache, and explicitly separate authorities must be disjoint. It does not select a service by project, user, first version, or latest version.

Integrity validation clears the loaded-catalog cache and revalidates exact stored bytes. A failed validation clears the cache and marks the exact registry version failed, preventing stale verified bytes from continuing to serve. Version retirement also clears loaded catalog entries.

Crosswalk decisions are not held in a browser cache or browser storage. The administration client uses authenticated requests and does not persist catalog versions, entitlements, or project IDs in `localStorage` or `sessionStorage`.

## 7. Candidate preview versus governed decision

These are distinct contracts:

1. **Candidate preview** is bounded, reproducible, non-authoritative, and non-persistent. Even an exact dictionary-code match or an approved institutional alias remains a candidate requiring governed review. A preview returns `candidate_only`, `persisted: false`, `dataset_mutated: false`, and `governed_feature_set_changed: false`.
2. **Governed decision** is an append-only review record pinned to exact lineage and bounded external evidence references. It may reach a terminal confirmed lifecycle only when every field has an evidence-complete terminal state. Confirmation still does not apply the decision to a dataset or predictor contract.

Semantic similarity may produce only a probable or ambiguous candidate. It can never produce an authoritative mapping. Target fields and deterministic target-source fields are excluded from predictor mapping candidates. Negative or institutionally recoded values receive no vendor meaning without durable source-to-model recoding evidence.

## 8. Nine-state mapping governance model

`Confirmable` below means eligible to be part of an evidence-complete terminal crosswalk. It does not mean that the catalog service changed a dataset or approved a predictor.

| State | Meaning and minimum contract | Confirmable |
| --- | --- | --- |
| `exact_verified` | One exact-code source candidate, exact catalog definition and exact-match evidence, explicit analyst-review evidence, reviewer, rationale, and candidate attribute code | Yes |
| `approved_alias` | A versioned institution-approved alias candidate, exact alias-authority ID and alias evidence reference pinned to the source candidate, analyst-review evidence, reviewer, rationale, and candidate code | Yes |
| `transformed_or_derived` | A derived field with named source attribute codes present in source evidence; documented transformation reference or rule; type, units, source system, timing, special-value handling, value-range reconciliation, special-value reconciliation, bounded concerns, analyst-review evidence, reviewer, and rationale | Yes |
| `probable_review_required` | A single semantic candidate supported by semantic-analysis evidence; it remains non-authoritative and cannot claim analyst confirmation | No |
| `ambiguous_review_required` | At least two possible catalog codes supported by ambiguity-analysis evidence; no candidate is selected authoritatively and analyst confirmation remains false | No |
| `recoding_evidence_required` | A candidate affected by unresolved transformation or recoding concerns, with recoding-observation evidence and bounded concerns; source meanings remain unassigned pending durable evidence | No |
| `unresolved` | No governed resolution, supported by an unresolved-assessment evidence reference; analyst confirmation remains false | No |
| `out_of_catalog` | Evidence-complete terminal determination that the field has no supported catalog candidate; no candidate code is allowed; requires out-of-catalog and analyst-review evidence, reviewer, and rationale | Yes |
| `rejected` | Evidence-complete terminal rejection preserved for audit; requires analyst-review evidence, reviewer, and bounded rationale | Yes |

There is intentionally no generic `approved` state. Each terminal outcome communicates why it is terminal and which evidence must support it.

Every decision requires at least one bounded evidence reference. Evidence references contain identity, kind, external authority ID, checksum, creator, and timestamp; the full evidence content remains in its own authority system. Evidence IDs must be unique within a decision.

## 9. Lifecycle and state-transition rules

- Candidate registration creates revision 1 in `draft` lifecycle only and uses expected revision 0.
- A later revision preserves the exact governed field inventory. Fields cannot be silently added or removed.
- A non-confirming revision enters `review_required`.
- A confirming revision enters `confirmed` only when every decision is in an evidence-complete terminal state.
- Review-required states cannot set `analyst_confirmed`.
- Terminal states require explicit reviewer identity and rationale; reviewer identity must match the creator of analyst-review evidence.
- The audit actor must match the authenticated principal.
- Source candidate mappings must remain exact-catalog, candidate-only, unapproved, and nonmutating.
- The source crosswalk and every later revision must retain the same exact project, dataset, schema, target, predictor-authorization, catalog, and source-crosswalk identity.

The explicit `history()` operation remains project-authorized and catalog-entitled and may inspect an exact old lineage after it is no longer current, provided every returned record matches the supplied lineage. Exact-revision and current-state operations require current lineage. This permits bounded audit without a first/latest lineage fallback.

## 10. Optimistic concurrency and immutable history

The repository uses atomic compare-and-append semantics:

- the caller supplies `expected_revision`;
- that value must equal the exact current head revision;
- the appended revision must be current revision plus one;
- revision 1 has no previous checksum;
- every later revision pins the exact previous revision checksum; and
- lineage, source crosswalk identity, and source crosswalk checksum are immutable across revisions.

The durable repository performs this sequence in one immediate database transaction. Competing writers using the same expected revision can produce at most one successful next revision; stale writers receive a conflict and no partial record remains.

Revision rows are protected by database triggers against update and delete. The head is updated only after the revision append passes validation. Each stored revision is checksum-verified on read, and history reads verify sequential revision numbers and the complete checksum chain. Exact revision lookup never falls back to another revision. Rejected decisions remain visible in immutable history after later reconsideration.

The repository is independently self-versioned under the restricted metadata authority and does not use or apply the ATLAS application migration numbered 0028.

## 11. Audit behavior

### 11.1 Catalog access audit

Catalog operations write bounded audit events with an opaque audit ID, actor, action, result status, correlation ID, server timestamp, and only the applicable bounded catalog-version, attribute, project, or safe-detail identifiers. The catalog access-audit table is append-only; database triggers reject update and delete.

Successful operations and safe denied-or-failed outcomes are distinguishable. Authorization responses use generic messages and must not reproduce restricted definitions or internal exception content. An unauthenticated request is rejected by the authentication dependency before catalog service access and receives no catalog data.

The router's secondary audit helper is best effort: an audit-write failure does not replace the primary HTTP result or cause raw restricted/error content to be emitted. Operational isolation therefore treats audit availability and unexpected live audit appends as separately monitored authorities.

### 11.2 Governed revision audit

Every governed revision embeds immutable audit metadata:

- authenticated actor ID;
- request ID;
- timezone-aware occurrence timestamp;
- bounded reason; and
- at most 16 sorted, unique, flat labels.

Arbitrary nested audit payloads are not accepted. Label keys associated with credentials, authorization headers, cookies, passwords, secrets, tokens, API keys, or connection strings are prohibited. The actor ID must equal the authenticated principal. Evidence content is referenced by checksum rather than copied into audit metadata.

## 12. No-mutation guarantees

The crosswalk contract contains no dataset writer, target-contract writer, predictor-authorization writer, feature-manifest writer, workflow-completion writer, or modeling-job launcher.

The following invariants are encoded in the immutable models and checked by the governance service:

- source candidates remain `candidate_only: true`;
- candidate mappings remain `approved_mapping: false`;
- preview persistence remains false;
- `dataset_mutated` remains false;
- `governed_feature_set_changed` remains false for preview;
- `predictor_authorization_mutated` remains false for governed revisions; and
- target and deterministic target-source fields never enter predictor approval.

Registering, revising, confirming, rejecting, or leaving a crosswalk decision under review changes only the separately governed crosswalk evidence history. A later integration phase must explicitly translate an accepted proposal through the appropriate dataset and predictor-authorization authorities; this phase cannot do so implicitly.

## 13. Failure behavior

The contract fails closed for:

- missing authentication;
- absent project permission;
- missing, expired, revoked, or mismatched entitlement;
- cross-tenant or cross-principal use;
- retired or integrity-failed catalog versions;
- stale project, dataset, authorization, schema, or catalog lineage;
- source candidates that are not candidate-only and nonmutating;
- evidence-incomplete decisions;
- unsupported alias, transformation, or recoding claims;
- a changed governed field inventory;
- stale optimistic revision;
- broken checksum chain; and
- exact-resource absence.

Safe HTTP errors distinguish authentication/authorization, exact-resource absence, state conflict, invalid bounded request, timeout, and service unavailability without disclosing restricted content.

## 14. Current limitations and deferred integration

1. The production HTTP surface currently exposes candidate preview, not the full governed-decision lifecycle. `GovernedCrosswalkService` and the append-only repositories are implemented and tested composition components; exposing them through production routes or UI requires a separately approved integration phase.
2. No catalog binding, crosswalk state, alias, or special-value treatment is integrated into Data Acquisition or another workflow page.
3. Ordinary catalog-only operations are entitlement-scoped rather than project-scoped by design. Project membership is additionally required only for project schema, preview, and governed crosswalk operations.
4. The entitlement row is a durable current grant record that can be re-granted or revoked; it is not itself an immutable revision ledger. Administrative HTTP entitlement actions are represented in the append-only access audit. Immutable decision history applies to governed crosswalk revisions.
5. The institutional alias authority, project authorization provider, and current-lineage authority remain injected authorities. A production composition must bind them to the approved durable ATLAS authorities and preserve the same fail-closed order.
6. Semantic scoring is candidate-generation assistance only. It cannot approve mappings, resolve ambiguity, assign special-value meanings, or authorize predictors.
7. The catalog cache is content-addressed rather than principal-addressed. Its safety depends on the enforced per-call authorization-before-cache rule; any future cache path must preserve that order.
8. Catalog router auditing is intentionally bounded and best effort. Operational monitoring must detect audit-authority unavailability, while acceptance isolation requires zero writes to live audit authorities.
9. No bulk export, unrestricted catalog browser, full special-value dump, or physical storage disclosure is part of this contract.
10. This phase does not access modeling rows or the sealed final holdout and provides no authority to train, evaluate, interpret, promote, or score a model.
11. The current production HTTP preview does not bind activation-revision, target-contract, or predictor-authorization identifiers; that fuller identity exists in the governed-crosswalk composition and remains deferred from the HTTP/UI lifecycle.
12. The administration client does not currently submit `expected_revision` when retiring a version. Optimistic concurrency is implemented at the registry/API boundary and tested there, but stale-revision retirement remains an API-only acceptance case and a documented UI limitation.

## 15. Contract invariants for future integration

Any later controlled integration must preserve all of these conditions:

- backend authentication, role, project, and entitlement enforcement;
- exact catalog version and checksum binding;
- authorization before cache or artifact access;
- exact current lineage for current-state reads and writes;
- bounded, candidate-only preview;
- the nine-state governance model with state-specific evidence;
- atomic optimistic concurrency and checksum-chained immutable history;
- bounded, secret-safe audit metadata;
- no fuzzy or semantic candidate becoming authoritative automatically;
- provider- and attribute-specific special-value meanings;
- no automatic dataset, target, predictor-authorization, feature-set, or workflow mutation; and
- no first/latest, browser-storage, checkpoint, or anonymous-scope fallback.

Controlled catalog integration must be separately authorized and accepted. Until then, the catalog remains an administration and governed-evidence capability outside the Predictive Modeling workflow.
