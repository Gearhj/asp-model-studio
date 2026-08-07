# ATLAS Bureau Metadata Catalog Foundation Report

Date: 2026-08-04  
Validation completed: 2026-08-05  
Repository: `C:\Users\james\ds-workflow-starter`  
Scope: provider-neutral restricted catalog foundation, complete Experian Premier v1.2 reconciliation, and HELOC candidate-crosswalk readiness  
Status: **COMPLETE WITH DOCUMENTED TEST-HARNESS LIMITATIONS — READY FOR MANUAL REVIEW; NOT STAGED**

This report is aggregate-only. It intentionally omits the complete licensed dictionary, long source excerpts, complete special-value definitions, and row-level crosswalk evidence. Those materials remain in an access-restricted Windows Temp root outside Git.

## 1. Repository and safety baseline

| Item | Baseline |
| --- | --- |
| Branch | `codex/phase2a-canonical-lineage` |
| HEAD | `938c5b1e2d5b4f81f2b35acc11a048a9b8a04d62` |
| Upstream | `origin/codex/phase2a-canonical-lineage`, ahead 0 / behind 0 |
| Git index | Empty |
| Baseline tracked changes | 53 paths, all retained |
| Baseline untracked files | 8 paths, all retained |
| Missing pre-existing paths | 0 of 68 checked paths |
| External safety evidence | `C:\Users\james\AppData\Local\Temp\atlas-bureau-catalog-20260804-231240` |

The safety directory contains the branch/HEAD record, binary Git patch, tracked and untracked manifests, source fingerprints, protected-authority baseline, logical-authority baseline, and intended phase files. It contains no raw dataset, browser profile, credential, cookie, token, environment-variable value, or sealed-holdout membership.

The working tree was already substantially dirty before this phase. Those changes were treated as James's work and preserved. No Git index or history operation was performed.

## 2. Current ATLAS bureau-metadata flow

The existing live flow remains:

`exact dataset schema and active version -> name/pattern and observed-value bureau detection -> observed special-value profiles -> feature-level Special-Value Treatment Review -> durable review/evidence -> downstream EDA and preparation interpretation`

The current flow already protects exact project/dataset/version lineage and keeps bureau specials separate from true nulls and ordinary outliers. It still relies on a mixture of attribute-name patterns, observed-value patterns, browser-imported/local metadata descriptions, locally maintained labels, and generic treatment wording. It does not yet bind live Data Acquisition, EDA, Outliers, Missing Values, or Feature Engineering decisions to an exact licensed catalog version, attribute definition, ordinary range, per-attribute special definition, or cross-bureau availability record.

That integration was deliberately not changed in this phase. The new package is an offline/read-only foundation. Existing production consumers and workflow pages remain unchanged.

## 3. Sources and canonical authority

| Role | Filename | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| Canonical dictionary | `Experian_Premier_Credit_Bureau.pdf` | 2,720,424 | `856FE14F1C9078C30DAA996DFD7CB5A85B272DBAA2736F20268A5E4D6FB25B7E` |
| Machine-readable staging | `credit_bureau_premier.csv` | 226,533 | `B421FD5B551490570395F5F650ED0889A11195DEF67E4AA8FDA566C2552CE456` |

The PDF is canonical whenever the two sources disagree. Both fingerprints matched the start-of-phase baseline at closeout. Deterministic PDF text/table extraction was sufficient for all 202 pages; zero pages lacked text and OCR was not used.

The source attachments were already present as untracked files at repository root when the phase began. The build did not copy them into a tracked location and never staged them. Because the task prohibited moving, deleting, or discarding existing files, those two pre-existing untracked attachments remain a manual never-stage item.

## 4. Canonical provider-neutral contracts

The foundation defines immutable typed contracts for:

- `BureauCatalogManifest`
- `BureauAttributeDefinition`
- `BureauSpecialValueDefinition`
- `BureauCatalogValidationFinding`
- `BureauAttributeMatchCandidate`
- `BureauDatasetCrosswalk`
- `BureauCatalogLicenseMetadata`
- exact catalog identity, access grants, structured attribute resolution, and observed-value classification

Catalog identity is the exact tuple `provider + product + edition + dictionary_version`, additionally pinned to one normalized catalog SHA-256. Attribute and special codes remain strings. Attribute definitions retain description, unit, field length, ordinary-domain expression and parsed bounds, numeric type, versions, cross-bureau availability, leveling/archive indicators, parser notes, source locator/checksum, extraction method/confidence, reconciliation/review state, timestamps, and record checksum.

Special definitions retain their exact attribute code and value code, source meaning, reviewable semantic family/confidence, source page/sequence, explicit bureau-special/null/parse/outlier flags, treatment-review state, optional policy reference, definition ID, and checksum. No dictionary wording silently approves a treatment.

| Contract | Canonical identity and principal fields |
| --- | --- |
| Catalog manifest | Exact provider/product/edition/dictionary version, normalized catalog checksum, restricted file descriptors, source fingerprints, counts, validation state, license envelope, builder provenance |
| Attribute definition | Exact catalog identity/checksum, sequence, string attribute code, description, units, field length, valid-value expression, ordinary bounds, numeric type, versions, bureau availability, leveling/archive indicators, source references, review state, record checksum |
| Special-value definition | Exact catalog identity/checksum, string attribute/value code, source meaning, semantic family/confidence, source references, mutually distinct value-class flags, review/policy state, definition checksum |
| Validation finding | Finding category/severity, source-safe location, canonical/secondary comparison state, selection basis, resolution state |
| Match candidate | Dataset field, candidate catalog code, candidate-only status, confidence, evidence categories, ambiguity, analyst-confirmation and recoding requirements |
| Dataset crosswalk | Exact project/dataset/version/catalog checksum, schema checksum, candidate mappings, approval state, mutation/non-access assertions, crosswalk checksum |
| License metadata | Classification, policy identity/version, allowed operations, redistribution state, export/API/tenant/demo controls, legal-review flag |

## 5. Ingestion architecture

The implementation separates responsibilities across:

- explicit external-path inspection and hashing;
- deterministic CSV staging parsing;
- deterministic PDF table/text extraction with no OCR fallback unless configured;
- normalization of identifiers, values, ranges, JSON, and checksums;
- PDF-authoritative reconciliation;
- immutable atomic external publication;
- strict descriptor/checksum validation and bounded exact loading;
- entitlement-checked lookup/classification/crosswalk operations; and
- candidate-only dataset crosswalk construction.

The builder writes only to an explicit absolute external root that cannot overlap or alias the repository. Publication uses a unique staging directory and an atomic final rename. A failed validation or injected publication failure cannot leave a final catalog snapshot.

## 6. Reconciliation rules

1. Match the canonical PDF record to CSV staging by exact attribute code; use source sequence only as a conflict-detecting fallback.
2. Preserve PDF and CSV values, selected value, selection basis, status, and severity for every reconciled field.
3. Select the PDF value when both sources disagree and a canonical PDF value exists.
4. Treat missing canonical PDF content as unresolved/error rather than silently selecting CSV.
5. Preserve multiline descriptions and special definitions.
6. Parse ranges from canonical PDF text; keep large sentinel codes as strings.
7. Detect spreadsheet date conversion generically.
8. Reject duplicate codes, duplicate normalized per-attribute special codes, malformed domains, unsafe paths, descriptor/hash mismatches, and contradictory identity.
9. Sort definitions and findings deterministically.
10. Validate the complete staged snapshot before atomic publication.

## 7. Complete PDF-versus-CSV reconciliation

| Measure | Result |
| --- | ---: |
| PDF pages processed | 202 |
| Pages without extractable text | 0 |
| CSV rows processed | 1,718 |
| PDF attribute records | 1,718 |
| Reconciled attributes | 1,718 |
| Unique PDF codes | 1,718 |
| Unique CSV codes | 1,718 |
| Exact code matches | 1,718 |
| PDF-only attributes | 0 |
| CSV-only attributes | 0 |
| Duplicate PDF codes | 0 |
| Duplicate CSV codes | 0 |
| Sequence gaps | 0 |
| Invalid ranges | 0 |
| Date-conversion detections | 5 |
| Normalized formatting differences | 1,525 |
| Core substantive conflicts | 410 |
| Unresolved conflicts | 0 |
| Unit conflicts | 350 |
| Length conflicts | 0 |
| Version conflicts | 0 |
| Attributes with no documented special values | 119 |
| Attributes with one or more documented special values | 1,599 |
| Attributes with multiple documented special values | 1,427 |
| Special-value definitions | 4,630 |
| Attributes with canonical PDF provenance | 1,718 of 1,718 |
| Source-page coverage | 202 of 202 pages |
| Cross-bureau availability populated | 169 attributes |
| Leveling metadata populated | 83 attributes |
| Archive metadata populated | 188 attributes |

The 410 core conflicts comprise 55 description, 350 unit, and 5 valid-range disagreements; field length had zero conflicts. Each disagreement remains in the restricted reconciliation artifact with both source values, the PDF-selected value, and explicit canonical-selection basis. The final catalog reports `passed_with_warnings`, not a false exact-match status.

The final builder counter reports 1,525 normalized formatting differences. An earlier exploratory comparison reported 1,551 because it used a broader aggregation across four raw core fields; the definitive builder result is the contract value and the exploratory number is retained only as diagnostic history.

## 8. Verified spreadsheet date-conversion cases

All five mandatory candidates were checked against the canonical PDF:

| Attribute | CSV staging value | Canonical PDF value | PDF page | Result |
| --- | --- | --- | ---: | --- |
| `ALL6310` | `9-Jan` | `1-9` | 23 | PDF range selected; conversion damage recorded |
| `ALL6320` | `9-Jan` | `1-9` | 23 | PDF range selected; conversion damage recorded |
| `BCC8337` | `13-Jan` | `1-13` | 81 | PDF range selected; conversion damage recorded |
| `BCC8338` | `25-Jan` | `1-25` | 81 | PDF range selected; conversion damage recorded |
| `MTF6326` | `3-Jan` | `1-3` | 153 | PDF range selected; conversion damage recorded |

These are verification results, not hardcoded corrections. Detection is generic and the canonical value is selected from the PDF record.

## 9. Value-classification contract

An exact observed value resolves to one and only one of:

- `ordinary_valid`
- `bureau_special`
- `true_null`
- `parse_failure`
- `unexpected_invalid`

Ordinary-outlier status is separate and can only be true for an ordinary valid value. Lookup is always attribute-specific: `provider + product + edition + version + checksum + attribute_code + observed_value`. A documented special outside the ordinary range remains a bureau special; an undocumented out-of-range value is unexpected. The same code may have different meanings on different attributes. No global special-code meaning was introduced.

The live analytical pages do not yet consume this classifier. Later integration must exclude exact bureau specials from ordinary histograms, density estimates, quantiles, boxplots, correlations, VIF, and outlier calculations while preserving independently versioned institution treatment policy.

## 10. Restricted artifact format and access

Each exact snapshot contains:

- `catalog_manifest.json`
- `attribute_definitions.jsonl`
- `special_value_definitions.jsonl`
- `reconciliation_findings.jsonl`
- `lookup_index.json`
- `catalog_validation_summary.json`
- `catalog_build_log.json`

The loader requires an exact provider/product/edition/version and exact expected checksum. It rejects first/latest fallback, corrupt/missing/partial files, unsafe paths and links, descriptor mismatches, excessive size, schema violations, contradictory identity, duplicate normalized codes, invalid domains, and restrictive-license tampering. Its LRU cache is bounded and thread-safe.

The service defaults to deny-all entitlement. Every allowed operation requires an exact principal/catalog/checksum/operation grant before cache or artifact access. No router, browser UI, public static artifact, full-catalog endpoint, or download/export method was added.

## 11. Licensing safeguards

The first catalog is marked as a platform safety classification, not a legal conclusion:

| Control | Value |
| --- | --- |
| Classification | `restricted_vendor_metadata` |
| Redistribution | `prohibited` |
| Source export | false |
| Full-catalog API | false |
| Tenant sharing | false |
| Public demo | false |
| Legal review required | true |
| Restricted export | true |

The restrictive governance envelope is integrity-bound to the exact catalog checksum and revalidated on load and service use. Altering these fields without producing a different caller-pinned checksum fails closed.

The Windows Temp root has inheritance disabled and explicit access only for the current Windows user, Administrators, and SYSTEM.

## 12. HELOC candidate-crosswalk readiness

The analysis used the exact persisted schema document only. It did not load observations, preview rows, assignments, or final-holdout data. A strict allowlisted schema contract rejects unknown/nested payloads rather than treating constant booleans as proof of non-access.

| Aggregate coverage category | Count |
| --- | --- |
| Exact matches | 0 |
| Approved aliases | 0 |
| Probable matches | 0 |
| Ambiguous matches | 0 |
| Unresolved fields | 1 |
| Fields requiring recoding evidence | 23 |

Negative HELOC values were not assigned Premier meanings. Without durable source-to-modeling recode evidence, affected fields remain `unresolved_recoding`. Similar names do not become mappings, ambiguity does not become approval, and the current predictor authorization is unchanged.

## 13. Long-run acceptance matrix

Definitive restricted root: `C:\Users\james\AppData\Local\Temp\atlas-bureau-restricted-20260804-235210\outputs\acceptance-definitive-pinned-20260805-070600`

| Workload | Result |
| --- | --- |
| Clean complete catalog builds | 3 of 3 passed from distinct clean directories |
| Deterministic normalized checksums | Identical across all three builds |
| Deterministic artifact hashes | Identical for all seven restricted artifacts across all three builds |
| Complete exact reloads | 100 of 100 passed |
| Exact-code lookups | 100,000 of 100,000 passed |
| Observed-value classifications | 100,000 of 100,000 passed |
| Concurrent read workers | 8 of 8; 1,024 operations; all exact identity |
| Corrupt manifest rejection | Passed |
| Corrupt data rejection | Passed |
| Exact version/checksum mismatch rejection | Both passed |
| Missing-file rejection | Passed |
| Partial-publication rejection | Passed |
| Safe failure/retry | Injected failure rejected; no final snapshot published; staging cleanup verified; retry passed with exact checksum |
| First/latest fallback used | No |
| Full-catalog export used | No |

Final catalog checksum: `0234e10f34c04430e445e51cfa3fb7dcf7c0dbada38af31f27a369e8b05599f8`

The definitive artifact was built, accepted, and persistently recorded under the repository-pinned Pydantic 2.7.4 environment. A separate two-runtime synthetic audit under Pydantic 2.7.4 and 2.13.4 produced identical hashes after the repair. An additional direct diagnostic loaded the definitive artifact successfully under 2.13.4 with the same checksum, 1,718 attributes, and 4,630 special definitions; that direct diagnostic was not persisted in `acceptance-summary.json` and is therefore not counted as persisted acceptance evidence. Acceptance exposed and repaired a real cross-version risk: `frozenset` serialization order for allowed operations differed by Pydantic release. The governance payload and written manifest now sort that field explicitly before hashing. Earlier acceptance roots are preserved as diagnostic evidence and are not definitive.

## 14. Performance and artifact sizes

| Measurement | Result |
| --- | --- |
| Three-build total / mean / p95 | 400,244.5104 ms / 133,414.8368 ms / 149,957.2759 ms |
| 100 reload total / mean / p95 / maximum | 502,271.5764 ms / 5,022.715764 ms / 5,511.4847 ms / 7,514.7550 ms |
| Exact lookup workload wall total / sampled-operation mean / p95 / maximum | 6,493.1382 ms / 64.064789 µs / 106.9 µs / 1,510.899980 µs |
| Classification workload wall total / sampled-operation mean / p95 / maximum | 7,829.1683 ms / 77.009501 µs / 126.4 µs / 920.999970 µs |
| Eight-reader workload | 1,024 exact operations in 75,941.5403 ms |
| Representative uncached reload peak Python allocation | 134,787,969 bytes peak; 69,213,818 bytes current; 14,992.6992 ms |
| Safe-retry elapsed | 115,924.3075 ms |
| Complete acceptance elapsed | 1,242,151.6772 ms |
| Artifact bytes per build | 15,930,542 bytes |

The dominant bottlenecks are deterministic PDF extraction/publication and full checksum-validating cold reload. A cold reload intentionally rereads and validates every descriptor, artifact, record, license envelope, and normalized checksum. Cached exact lookup and classification are two orders of magnitude faster and were measured independently. No threshold was invented after observing results.

## 15. Synthetic tests

The test fixtures use synthetic providers, codes, descriptions, ranges, and meanings. They do not include the licensed dictionary. Coverage includes:

- exact code/sequence reconciliation and multiline preservation;
- unique codes, string codes, large sentinel round-trip, ranges, and spreadsheet-date detection;
- attribute-specific meaning and no global semantics;
- null/special/outlier separation and unexpected-value behavior;
- exact version/checksum/provider/product fail-closed behavior;
- corruption, unknown structured resolution, no full export, deterministic/concurrent reads;
- candidate-only crosswalks, ambiguity, negative recode protection, target/source roles, and second-provider loading;
- external-root isolation and source/log redaction;
- nonnumeric special codes, normalized-code collision rejection, and no failed publication;
- strict schema-only crosswalk input and entitlement denial; and
- source scans for identity, route/export, fallback, global meanings, vendor files/artifacts, paths, and secret leakage.

## 16. Regression and static validation

All commands ran from `C:\Users\james\ds-workflow-starter`. Hermetic commands used fresh Windows Temp authorities and preserved their evidence.

| Gate | Command/result |
| --- | --- |
| Focused bureau foundation | 6 suites; 46 passed; 0 failed/errors/skips/warnings; run `atlas-hrt-20260805-070303-5e7c8e01af`; harness 142.427391 s |
| Existing backend bureau/DA/EDA/preparation/canonical regressions | 12 of 12 suites passed; 114 tests + 29 subtests; 36 warnings; run `atlas-hrt-20260805-073043-a6e57da895`; 552.1 s wall |
| Relevant frontend structural regressions | 3 suites passed / 4 suites failed before assertions; 21 tests executed in the passing suites; failures were `ERR_MODULE_NOT_FOUND` because hermetic mirrors omit runtime package `typescript`; run `atlas-hrt-20260805-074018-5c9b1ea9c2` |
| Security gate | Passed; 7 behavioral suites / 62 tests + 1 structural suite / 30 assertions; run `atlas-hrt-20260805-074317-f96a5353ce`; 248.401535 s child |
| Storage-isolation scanner and guard | Passed; 104 Python test sources scanned + 24 guard tests; run `atlas-hrt-20260805-074820-fc96031496` |
| TypeScript | `npx tsc -b --pretty false`; passed; 42.4 s |
| Production build | Passed; 3,441 modules; 137 files / 83,101,525 bytes in external Temp; 76.4 s wall |
| Python compilation | Passed; 441 `.pyc` files in external Temp cache |
| Source safety scan | 8 of 8 passed inside the focused 46-test run |
| `git diff --check` | Passed; line-ending notices only; Git index empty |

Nonblocking diagnostics were preserved rather than hidden: the backend group emitted 36 existing warnings; the security gate emitted AnyIO unclosed-memory-stream `ResourceWarning`s and Pydantic V2 `.dict()` deprecation warnings; the production build emitted stale browser-data, mixed static/dynamic import, and large-chunk warnings. None changed a gate exit code.

Exact hermetic commands:

```powershell
& .\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --mode HERMETIC_REGRESSION --temp-parent 'C:\Users\james\AppData\Local\Temp' --suite tests\bureau_metadata_ingestion_test.py --suite tests\bureau_metadata_core_test.py --suite tests\bureau_metadata_acceptance_harness_test.py --suite tests\bureau_metadata_crosswalk_test.py --suite tests\bureau_metadata_crosswalk_cli_test.py --suite tests\bureau_metadata_source_safety_scan_test.py

& .\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --mode HERMETIC_REGRESSION --temp-parent 'C:\Users\james\AppData\Local\Temp' --suite tests\bureau_detection_exact_binding_test.py --suite tests\canonical_dataset_identity_test.py --suite tests\data_acquisition_reproducibility_context_test.py --suite tests\data_acquisition_validation_simplification_test.py --suite tests\eda_governed_analytical_contract_test.py --suite tests\feature_engineering_acceptance_repair_test.py --suite tests\missing_table_first_backend_test.py --suite tests\predictor_authorization_contract_test.py --suite tests\preparation_table_first_backend_contract_test.py --suite tests\security_containment_test.py --suite tests\special_value_review_contract_test.py --suite tests\test_storage_isolation_guard_test.py

& .\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --mode HERMETIC_REGRESSION --temp-parent 'C:\Users\james\AppData\Local\Temp' --suite tests\bureauDetectionExactBinding.test.mjs --suite tests\canonicalDatasetIdentity.test.mjs --suite tests\dataAcquisitionLifecycle.test.mjs --suite tests\dataAcquisitionValidationSimplification.test.mjs --suite tests\edaCanonicalIdentity.test.mjs --suite tests\featureBuilderValidation.test.mjs --suite tests\preparationTableFirstContract.test.mjs

& .\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --mode HERMETIC_REGRESSION --temp-parent 'C:\Users\james\AppData\Local\Temp' --suite scripts\run_security_tests.py

& .\.venv\Scripts\python.exe scripts\run_hermetic_tests.py --mode HERMETIC_REGRESSION --temp-parent 'C:\Users\james\AppData\Local\Temp' --suite scripts\check_test_storage_isolation.py --suite tests\test_storage_isolation_guard_test.py
```

Static/build commands:

```powershell
npx tsc -b --pretty false
npm run build -- --outDir 'C:\Users\james\AppData\Local\Temp\atlas-bureau-build-20260805-075100'
$env:PYTHONPYCACHEPREFIX='C:\Users\james\AppData\Local\Temp\atlas-bureau-pycache-20260805-075300'; & .\.venv\Scripts\python.exe -m compileall -q server scripts tests
git diff --check
git diff --cached --name-only
```

Known pre-existing harness limitation, reproduced and classified precisely: four legacy Node source-contract tests import `typescript` at runtime, while hermetic child mirrors intentionally omit `node_modules`. Those children fail before assertion import with `ERR_MODULE_NOT_FOUND`; they are neither product assertion failures nor reported as passes. The three dependency-free structural suites, TypeScript compilation, and production build passed from the same frozen source.

## 17. Protected-authority comparison

Nine of nine protected files with comparable baseline hashes match in both length and SHA-256, including persistence, Dataset Library registry and links, workflow checkpoint, evidence registry, MDD index/document, feature-manifest authority, and migration `0028`. There were zero missing paths and zero mismatches.

An independent immutable/query-only comparison selected 35 allowlisted metadata fields only; 35 of 35 matched across active identity, durable project link, migration level, and Analysis Partition. Cardinality remained exactly one active selection, one durable link, and one current partition. Exact activation, target/predictor contracts, partition revision/seed/stratification, aggregate population metadata, and artifact/assignment/population fingerprints all matched baseline. The query did not select observations, row assignments, event-count payloads, development positions, or holdout membership.

Migration `0028` matched its baseline length and SHA-256, had zero applied migration rows, and remained unchanged and unapplied. The security database baseline was hash-unavailable because of a sharing lock. Per scope it was not accessed or unlocked at closeout; it therefore remains **unverifiable**, not reported as matched.

## 18. Future ATLAS integration contract

The next phase should integrate only reviewed, exact-version metadata and must preserve current authority:

- **Data Acquisition:** recognize exact attributes; show description, unit, range, observed special meanings, version/provenance, cross-bureau metadata, and analyst confirmation in the existing table-first review.
- **EDA:** use readable labels/tooltips and split ordinary versus special distributions with provenance-aware findings.
- **Outliers:** exclude exact per-attribute bureau specials from ordinary outlier calculations.
- **Missing Values:** distinguish true nulls from documented exceptional codes.
- **Feature Engineering:** prevent unreviewed special codes from unsupported arithmetic/binning; offer governed indicators and recodes.
- **Interpretation:** use reviewed descriptions and reason-code context.
- **Evidence/MDD:** persist exact provider/product/version/code/definition/range/observed specials/treatment/rationale/source checksum/reviewer/timestamp.

Integration must remain backend-authoritative, exact-version, tenant-entitled, project-scoped, candidate/review based, and fail closed. It must not use browser authorization, first/latest selection, silent aliases, or automatic treatment approval.

## 19. Files changed by this phase

Production foundation:

- `requirements.txt`
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

Offline commands:

- `scripts/build_bureau_metadata_catalog.py`
- `scripts/validate_bureau_metadata_catalog.py`
- `scripts/build_bureau_metadata_crosswalk.py`

Synthetic tests:

- `tests/bureau_metadata_ingestion_test.py`
- `tests/bureau_metadata_core_test.py`
- `tests/bureau_metadata_crosswalk_test.py`
- `tests/bureau_metadata_crosswalk_cli_test.py`
- `tests/bureau_metadata_acceptance_harness_test.py`
- `tests/bureau_metadata_source_safety_scan_test.py`

Documentation:

- `docs/BUREAU_METADATA_CATALOG_FOUNDATION_REPORT_2026-08-04.md`

No existing workflow page, live preprocessing consumer, router, migration, authority database, or governed project artifact was modified by this phase.

## 20. External restricted outputs

The definitive directory contains the complete normalized attribute catalog, complete special-value catalog, complete reconciliation findings, manifests, lookup index, validation/build logs, performance results, integrity-test evidence, and detailed HELOC candidate crosswalk:

`C:\Users\james\AppData\Local\Temp\atlas-bureau-restricted-20260804-235210\outputs\acceptance-definitive-pinned-20260805-070600`

The directory contents must never be staged or copied into docs, audit output, screenshots, browser traces, fixtures, public assets, or frontend bundles. The path itself is documented here only so James can locate the restricted deliverables.

## 21. Remaining limitations

1. Live ATLAS pages still use the pre-existing detection/review metadata path; the new catalog is intentionally not integrated.
2. The 23 HELOC predictor mappings remain unresolved pending durable institutional recoding/source evidence and analyst review.
3. The first source's PDF column layout is supplied by a configurable parser contract; broader provider onboarding still needs an explicit reviewed layout profile per source.
4. The complete source output is restricted vendor metadata and requires organizational licensing/legal review before broader access.
5. The live security database checksum could not be obtained because another process held a sharing lock at both checkpoints. The separately allowlisted 35 non-security project, dataset, and partition metadata fields were unchanged; security-database contents remain unverifiable.
6. Legacy hermetic Node source mirrors do not package the `typescript` dependency for four relevant older tests; those failures occur before assertions and remain a test-infrastructure limitation, not a claimed pass.
7. The two user-supplied source attachments remain pre-existing untracked files at repository root because this task prohibited moving/deleting them.
8. Full uncached integrity reload averages about 5.0 seconds because every restricted artifact and record is rehashed and revalidated; later integration should retain the bounded exact cache and avoid cold loading per value.
9. `allowed_operations` is the only unordered field in the current checksum-bound models and is explicitly sorted. Any future set/frozenset field must receive the same canonicalization before it can join catalog identity.

## 22. Recommended next implementation phase

After James reviews licensing, catalog provenance, and the candidate crosswalk, implement a separate governed integration phase. Start with an entitlement-backed exact catalog binding and reviewed institutional alias/recode authority, then update Data Acquisition's existing table-first Special-Value Review. Do not integrate EDA/preparation behavior until exact-version binding, review evidence, and fail-closed no-fallback tests are green.

## 23. Proposed commit slices

No files were staged or committed. Recommended selective slices after manual review:

1. **Provider-neutral contracts and exact storage/service** — `requirements.txt`, `server/bureau_metadata/{types,normalizer,source_reader,catalog_store,catalog_service,validation,__init__}.py`.
2. **Deterministic ingestion and external build** — parsers, builder, build/validation CLI, ingestion/core/acceptance tests.
3. **Candidate-only crosswalk** — crosswalk module/CLI and crosswalk tests.
4. **Safety scans and aggregate report** — source-safety test and this report.

Before staging, re-check each slice against the dirty-tree classification and never-stage list.

## 24. Files and paths that must never be staged

- `Experian_Premier_Credit_Bureau.pdf`
- `credit_bureau_premier.csv`
- every directory under `C:\Users\james\AppData\Local\Temp\atlas-bureau-restricted-20260804-235210`
- safety patches/manifests under `C:\Users\james\AppData\Local\Temp\atlas-bureau-catalog-20260804-231240`
- raw datasets, Dataset Library artifacts, live databases, security state, checkpoints, evidence items, MDD artifacts, feature manifests, model artifacts, browser profiles/traces, `.env*`, `.runtime`, `.tmp`, and caches
- the complete normalized dictionary, special definitions, reconciliation records, detailed crosswalk, or any derivative containing restricted source content

## 25. Manual review checklist for James

- [ ] Verify the two source fingerprints against the provided files.
- [ ] Review the five date-conversion decisions and selected PDF pages.
- [ ] Review aggregate conflict categories and a restricted sample of reconciliation findings.
- [ ] Confirm licensing/redistribution policy and intended catalog administrators.
- [ ] Review the 23 unresolved HELOC recoding candidates; do not approve by name similarity alone.
- [ ] Provide or reject durable institutional alias/recode evidence.
- [ ] Review the exact entitlement boundary and tenant policy before any live integration.
- [ ] Confirm the external restricted root ACL and retention policy.
- [ ] Inspect the proposed commit slices and never-stage list before selective staging.
- [ ] Keep the live workflow unchanged until a separately scoped integration acceptance is approved.

## 26. Final confirmations

| Confirmation | Result |
| --- | --- |
| Both source files processed | Yes; exact source fingerprints matched baseline |
| PDF extraction sufficient / OCR used | Yes / no OCR; 202 of 202 pages processed, zero pages without text |
| Actual attribute count verified | Yes; 1,718 PDF records, 1,718 CSV rows, 1,718 unique reconciled codes |
| Every attribute has PDF provenance | Yes; 1,718 of 1,718 |
| Five date candidates verified | Yes; all five verified against canonical PDF pages and reconciled |
| Special values attribute-specific | Yes; 4,630 definitions keyed by exact catalog + attribute + value |
| Global special-code semantics introduced | No |
| Full catalog remains outside Git | Yes; definitive restricted Temp root only |
| Unrestricted full-catalog API created | No |
| Live HELOC state changed | No change detected in the comparable non-security authorities and allowlisted metadata; security-database contents remain unverifiable |
| Sealed holdout accessed | No |
| Analysis Partition revised/replaced | No |
| Predictor authorization changed | No |
| Special-Value Review decision changed | No |
| Evidence record changed | No |
| MDD record changed | No |
| Training occurred | No |
| Evaluation occurred | No |
| Interpretation occurred | No |
| Promotion occurred | No |
| Scoring occurred | No |
| Migration `0028` changed/applied | No / no; exact file matched and applied-row count remained zero |
| Protected authorities | 9 of 9 comparable files and 35 of 35 logical fields matched; security DB hash unavailable and not accessed |
| Git index | Empty |
| Git/history/destructive operations | None: no stage, commit, push, reset, restore, clean, amend, rebase, merge, stash, delete, or discard |
