# ATLAS Runtime-Isolation Database Forensics — 2026-08-04

## Scope and forensic conclusion

This report covers Phase A only: read-only forensic reconciliation of the two
runtime databases whose protected hashes changed during the checkpoint-blocker
remediation run.

**Forensic conclusion:** the available evidence strongly supports mirrored,
anonymous authentication-denial audit writes as the logical activity associated
with the database changes. The exact requesting process is unresolved. A true
row-level before/after comparison is impossible because no verified pre-change
database copy was preserved; only pre-change file metadata and SHA-256 manifests
exist. No cleanup is supported.

This conclusion is deliberately narrower than a final hermetic-harness verdict.
It does not validate test isolation and does not authorize restoration,
deletion, or migration.

## 1. Evidence sources

Primary prior-run evidence:

- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-remediation-20260804T125205Z\protected-authority-hashes-before.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-remediation-20260804T125205Z\protected-authority-hashes-stop-after.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-remediation-20260804T125205Z\protected-authority-drift-stop.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-remediation-20260804T125205Z\runtime-isolation-stop.txt`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233441\protected-authority-hashes-before.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233441\protected-authority-hashes-after.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233441\database-metadata-before.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233441\service-listeners-before.txt`
- `C:\Users\james\AppData\Local\Temp\atlas-checkpoint-readiness-20260803-233441\service-processes-before.csv`
- `docs/CHECKPOINT_BLOCKER_REMEDIATION_REPORT_2026-08-04.md`
- `docs/CHECKPOINT_READINESS_REPORT_2026-08-03.md`

Current forensic-safety evidence:

- `C:\Users\james\AppData\Local\Temp\atlas-runtime-isolation-20260804-123957\forensic-copy-verification.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-runtime-isolation-20260804-123957\database-file-metadata.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-runtime-isolation-20260804-123957\database-no-write-check-after-cli-incident.csv`
- `C:\Users\james\AppData\Local\Temp\atlas-runtime-isolation-20260804-123957\forensic-scenario-failure-live-shm.txt`
- `C:\Users\james\AppData\Local\Temp\atlas-runtime-isolation-20260804-123957\service-listener-inventory.csv`

All database queries reported below used verified external copies with a
read-only immutable SQLite URI. No ATLAS application module was imported for
this analysis.

## 2. Before/after snapshot verification

### Pre-change evidence

The five relevant prior evidence roots were searched for exact database names
and for database candidates matching the recorded before/after file sizes:

1. `atlas-checkpoint-readiness-20260803-233349`
2. `atlas-checkpoint-migration-audit-20260803-234921-b7f09a73`
3. `atlas-checkpoint-readiness-20260803-233441`
4. `atlas-checkpoint-backend-validation-20260804-000112`
5. `atlas-checkpoint-remediation-20260804T125205Z`

No copy with the pre-change SHA-256 of either live database was found. Three
files named `atlas_security.db` under the earlier readiness source harness were
isolated synthetic test databases, not live snapshots; their sizes and lineage
did not match the protected database.

The only verified pre-change evidence is therefore:

| Database | Pre-change bytes | Pre-change last-write UTC | Pre-change SHA-256 |
|---|---:|---|---|
| Security | 6,012,928 | `2026-08-04T03:21:22.4441084Z` | `A1D061E0011866C13288ED23632E4F5E81FF08A4EFA2C00D7F98C6BEB2D52CF7` |
| Persistence | 27,291,648 | `2026-08-04T03:21:22.4614050Z` | `F19EF9BBC13EF72791E5BAC2DA2162F10DF51B7AF116B17C084CBF44BC62CFDC` |

These manifest values prove byte drift but cannot identify row additions,
updates, deletions, or changed columns.

### Verified post-change copies

| Database | Verified copy | Bytes | Source/copy SHA-256 match |
|---|---|---:|---|
| Persistence | `forensic-copies\persistence-post-20260804T150539Z.db` | 27,291,648 | `56D03587C1FB5802F4FD7D4B23F82E9EB3319E8E08CD5F6209448EB852BC5B0A` |
| Security | `forensic-copies\security-post-20260804T150539Z.db` | 6,029,312 | `2DD09B81A1E74FE75AA66DA7904129FB74D05DC18B4C2BF54D88C115EA74ED4C` |

The copies reside under
`C:\Users\james\AppData\Local\Temp\atlas-runtime-isolation-20260804-123957`.
Source and copy sizes and hashes match in `forensic-copy-verification.csv`.
After all immutable queries, both copy hashes remained identical and no SQLite
sidecar was created beside either copy.

## 3. SQLite and schema metadata

| Property | Persistence post copy | Security post copy |
|---|---:|---:|
| Header | SQLite format 3 | SQLite format 3 |
| SQLite library/header version | 3.45.3 / 3,045,003 | 3.45.3 / 3,045,003 |
| Page size | 4,096 | 4,096 |
| Page count | 6,663 | 1,472 |
| Freelist pages | 2,169 | 0 |
| Header read/write version | 2 / 2 (WAL-format header) | 1 / 1 (rollback-format header) |
| Change counter / version-valid-for | 4,197 / 4,197 | 184,373 / 184,373 |
| Schema cookie / schema format | 313 / 4 | 5 / 4 |
| `user_version` / `application_id` | 0 / 0 | 0 / 0 |
| Tables | 77 | 5 |
| Non-internal schema objects | 223 | 5 |
| Named non-internal indexes | 123 | 0 |
| Triggers | 23 | 0 |
| Views | 0 | 0 |
| Integrity check | `ok` | `ok` |
| Foreign-key findings | 312 | 67 |
| Post-only canonical schema SHA-256 | `359D9A15A104DF07B0F7B9DA4E1B755FF35B68DA935AAF4DA8B93E2B46B45652` | `9F87C7AE48229533DC2B1DDCE57A2E216E9B81828126237ED29FC613CC03C16D` |

The persistence object counts and foreign-key finding count exactly match the
2026-08-03 readiness report. The security table count and foreign-key finding
count also match that report. Persistence migration history contains 27 rows,
from `0001_initial.sql` through `0027_special_value_reviews.sql`; no `0028`
history row exists.

This is evidence against a schema or migration-history change. It is not a
definition-level before/after proof because no pre-change schema image or
canonical schema hash exists.

The standalone immutable persistence copy has no WAL sidecar. Its header bytes,
not the standalone-copy `PRAGMA journal_mode` response, are the relevant
evidence that the copied main file was in WAL format.

## 4. Post-only canonical table inventory

Canonical row hashing used ordered schema columns, explicit type prefixes,
normalized nulls, stable integer/real formatting, byte lengths plus hexadecimal
encoding for text/BLOB values, primary-key row order (or `rowid` where no key
existed), UTF-8 encoding, and SHA-256 over LF-separated records. Raw values,
BLOBs, credential material, and regulated payloads were never printed.

These hashes describe the post-change copies only. They cannot be labeled
unchanged or changed without pre-change table hashes.

### Persistence nonempty tables

| Table | Rows | Post-only canonical SHA-256 |
|---|---:|---|
| `active_modeling_dataset_versions` | 1 | `D4722F7BE8238D2ABBD83AF20E1A698BFFC57A46B7F52BDE74708E4E271F3B8E` |
| `analysis_partition_events` | 5 | `0BB64F12764202682448533C17397BBE706E79AF4638DB9D40640EC388A0DB5A` |
| `analysis_partitions` | 1 | `E9E8CCCFA47105A7EDAFD551FAAAE8BAC66BCE911EFF9E7ABA0A60AD620F9BEC` |
| `audit_log` | 18,044 | `C294FCBD25DC475D5F3269F38C37699E04832A39BD7821787A0E00DF689998FA` |
| `dataset_library_maintenance_events` | 2 | `4958BFB036EA04A8A44FEFECB9456A738DACBC857D3FC850D97D936A8D5A4B11` |
| `decision_journal` | 786 | `B49D7E5C9FEB45455C559F0C0777438EE69AFA3527AE10BCFE5D7030156397F0` |
| `documentation_packages` | 1 | `1F3B466CCF1850EFFACDA665C01D52602684F172532B9988CD25AA1560C97441` |
| `evidence_artifacts` | 219 | `70DA052C81589AA41C0C00C2022BAA0172F7AE82A349512ECFFB44E4E1F5AAD9` |
| `mdd_content_blocks` | 1 | `D58C3B947E7D875D3A739EBBB5326ECADED44D185DADA8AD24325BE08D6C9AF7` |
| `mdd_document_versions` | 1 | `DCD3D08A6C373F92EC1A327E8548CF7CDB0A15048B2B57B53644648F1ED3D757` |
| `mdd_documents` | 1 | `639B5AB9B8AE8ED6C060832486D6F11536A2EA53FA192A63DD7B8F66ADB7107B` |
| `mdd_evidence_links` | 1 | `7EC0A6386D27B387F1D4C074A5D9C87846D43A1745D82E017223D76703751B27` |
| `mdd_sections` | 1 | `AD88522CCC0DAE19C58916C08E24E6B5745C9F23A4FAD5773EF452055D5AB973` |
| `model_versions` | 1 | `D5925BAD3867E4EE5911FDB7A00BE80CBD277B431F5C416FA67ACCC692BF99C5` |
| `models` | 1 | `DFD50DF1F4EFE141BF8623DB29EA3178BD27E0AA4D3B152A9C93289FC86091EA` |
| `notifications` | 1 | `475329AB0B6FE253796BD1E718D313ED29BA640AE00270D21E1BE0C93C812A98` |
| `predictor_authorization_manifests` | 1 | `575E4283F721F2E3AC7BC055164ED42B30C988006E949400C2E8E8D03ECA843E` |
| `project_collaborators` | 121 | `E6AF47E9E456308D94875405B9F4FD2356440EDFBEED2F9878069781213CE884` |
| `project_dataset_activation_events` | 2 | `4F8FA150DF9A70CC99D6C667BC729471EBCCD9A7106D6E851640EB6BBE28F5FE` |
| `project_dataset_links` | 1 | `4AE4E8820C231E47D88D03CBAA6AD220A89E3397BE8BDC66831EE5DE09FBA724` |
| `projects` | 132 | `A36B34118247EA5540E72BFABFF4604E365EF7E477CFD408606899D06F5A97EA` |
| `resource_permissions` | 180 | `DA7E07935021AF71E972C2D15EDDFF5F8BF367AF40340C134545F4FFCB897188` |
| `schema_migrations` | 27 | `D3603544731C37BEBC368AB127A0FAAC9DFAC72995377D4B5C981EFE2A51F9B1` |
| `scoring_runs` | 18 | `E6555FA5219EDCC6D9CDBE49C78FFD668FD6455B266030FCFDF1F0AE87DA2BF2` |
| `sharing_events` | 1 | `CDFC5FBE40A88BB62808A8375FE092AC09FAFB5E0F77EDE774D5F69D349F5B1B` |
| `special_value_review_events` | 1 | `CD8FD58B58A1825F0A47B0CBF156BE38A44D93F056F3C61F3265B4AC41A45211` |
| `special_value_reviews` | 1 | `983B368D06BCB2F6B2D047543BDE510F4B36AABE4FE210D09497CBF4DF1A915A` |
| `target_findings` | 13 | `4404BD9D9717C9EDA8B803545A2E67DDE01B548BD9B95253469EB07F8484A617` |
| `users` | 249 | `AB42B41E3C9708C15A1C04FC4655EA968BC86825B7CF9E79F037D0CC902EA48D` |
| `workflow_state` | 120 | `EEF4A2C6887C682743241CB961C2B41BE56C0EFC68AB46D680637820B00FCB3F` |

The other 47 persistence tables are empty and have the canonical empty-input
SHA-256 `E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855`.

### Security tables

| Table | Rows | Post-only canonical SHA-256 |
|---|---:|---|
| `audit_events` | 20,304 | `2CBCA92B33F1632D40D8AD9AB6B9DB97717781219EF89237A37E271EA8628CE7` |
| `credentials` | 267 | `A007812238AB9986371B1E6720C582021B9E845E0518EABAF8459E2FED362B95` |
| `project_access` | 27 | `71E5AC7BA2DC6C03E890F6900CDB718AFABF90EFF37215C6690176679D4C0218` |
| `sessions` | 353 | `5EA304B3825A8EE0C0D2A5ADF12CCD3B77C5EFC4D4710C6482726534764720BF` |
| `users` | 200 | `BBF95387302B25468A27A4369323606EB77673D6E768B933EF82D2C32D190645` |

## 5. Safe changed-record evidence

The remediation baseline was captured at `2026-08-04T12:52:49Z`. A post-only
scan of every timestamp-like, created, updated, granted, login, expiry,
revocation, and last-seen column found exactly one activity class through the
last database write:

| Post-baseline table | Rows | First timestamp UTC | Last timestamp UTC | Safe classification |
|---|---:|---|---|---|
| `security.audit_events` | 42 | `2026-08-04T14:23:35.235787Z` | `2026-08-04T15:05:39.375941Z` | anonymous `access.denied`, resource `auth`, outcome `denied` |
| `persistence.audit_log` | 42 | `2026-08-04T14:23:35.235787Z` | `2026-08-04T15:05:39.375941Z` | mirrored anonymous `access.denied`, entity `auth` |

All 42 rows in each database have no named actor. The two exact audit-ID sets
and timestamps match one-for-one. The canonical SHA-256 of the 42-row security
subset is
`E291603614E08DE41AEBFEDA46AB9859B5EC7382302EE2B81BB2D99A9B1BB6D3`;
the corresponding persistence subset is
`D657F9E451FAFB41B0D79A71648A3D072AEA4277F0C6FEDF4EAED562DAA3EBF1`.
The differing hashes reflect the two stores' different audit schemas, not an ID
or timestamp mismatch.

In the narrow `15:00:00Z`–`15:10:00Z` window, both tables contain 12 of those
mirrored records. The final record has safe identity
`audit_236817f11ae54514b5bbb4395e038aab` and timestamp
`2026-08-04T15:05:39.375941Z`. No project, dataset, model, session, or named
actor is attached to it.

No other table had a temporal value after the baseline and on or before
`2026-08-04T15:05:40Z`. In particular, no post-baseline timestamp was found in
security users, credentials, sessions, or project access, or in persistence
projects, workflow state, dataset authority, target/predictor authority,
Analysis Partitions, evidence, MDD, feature/model authority, training,
Evaluation, holdout exposure, or Scoring metadata.

This supports identifying the 42 pairs as post-baseline additions. It does not
prove that no undated field changed, or that no row was deleted, because no
pre-change database exists for comparison. Consequently, before-row hashes,
updated-column lists, and definitive added/updated/deleted inventories cannot
be produced.

## 6. Timeline and attribution

| UTC | Evidence | Attribution level |
|---|---|---|
| `2026-08-04T12:52:49Z` | Remediation protected hash baseline completed. | Confirmed |
| `2026-08-04T14:23:35.235787Z` | First of 42 mirrored anonymous authentication denials. | Confirmed |
| `2026-08-04T15:00:26Z`–`15:01:10Z` | Nine mirrored anonymous denials. | Confirmed |
| `2026-08-04T15:05:38.280470Z`–`15:05:39.375941Z` | Final three mirrored anonymous denials. | Confirmed |
| `2026-08-04T15:05:39.3819386Z` | Security database last-write, approximately 6 ms after the final audit record. | Confirmed |
| `2026-08-04T15:05:39.3950004Z` | Persistence database last-write, approximately 19 ms after the final audit record. | Confirmed |
| `2026-08-04T15:29:10Z` | Drift stop evidence captured; listeners 5174/8001 absent. | Confirmed |

The one-to-one mirrored audit IDs, identical timestamps and classifications,
and millisecond file-write alignment make the ATLAS mirrored audit-write path a
**strongly supported** explanation for the logical writes. The persistence WAL
header also makes a WAL checkpoint or merge into the main file possible during
the final write/lifecycle window.

The exact originating request or process is **unresolved**. The preserved
process inventory proves that the prior backend and frontend listeners existed
earlier, while the stop inventory proves that they were absent later. It does
not contain a contemporaneous request log, PID-bound audit record, test run ID,
or shutdown trace for `15:05:39Z`. Mere process existence is not treated as
attribution, and the records are not labeled test-generated.

Attribution thresholds used here:

- **Confirmed:** directly represented in a verified manifest or immutable
  database record.
- **Strongly supported:** multiple independent records align exactly, with no
  contradicting evidence, but process identity is absent.
- **Possible:** technically consistent but not linked by direct evidence.
- **Unresolved:** evidence cannot identify the responsible actor/process.

## 7. HELOC logical-state result

The verified post copy retains the exact expected logical authority:

| Field | Post-change value |
|---|---|
| Project | `atlas-mrzpau4t` |
| Dataset | `ds_heloc_train_6bdb184b_05905` |
| Dataset version | `v_1785186305905_6bdb184b` |
| Analysis Partition | `analysis-partition-688c2184b4e9b8181946-r1` |
| Revision | 1 |
| Population / development / sealed holdout counts | 6,275 / 5,020 / 1,255 |
| Development / holdout shares | 0.8 / 0.2 |
| Seed | 42 |
| Stratification | target / `bad_flag` |
| Partition status | current |
| Holdout status | sealed / verified |
| Assignment checksum | `ed04b51eef3ebfccc846ff742203978ae0463ee871807c6045595b68106bb6c5` |
| Artifact checksum | `688c2184b4e9b8181946766e2577c1f1a53f9c88de2adf81a1d3affbc8dcd5fa` |
| Dataset activation | active, revision 1 |
| Project-dataset link | active |

The partition and activation timestamps predate the remediation baseline. The
post copy contains zero post-baseline HELOC candidate decisions, Evaluation
packages, holdout exposures, Scoring runs, or run records. No assignment JSON,
row membership, target values, raw dataset rows, evidence payload, MDD narrative,
or model binary was read or emitted.

## 8. Expected versus unexpected activity

- The records are structurally expected security/audit activity: anonymous
  requests were denied and logged in both configured audit stores.
- Their occurrence during a supposedly hermetic remediation run is unexpected
  and demonstrates that some request path still reached live audit authorities.
- The evidence does not establish whether the requests came from a test,
  diagnostic probe, browser, service lifecycle, or another process.
- No current HELOC workflow authority was contradicted by the post-state
  metadata.
- No evidence indicates migration `0028`, a training job, Evaluation,
  Interpretation, promotion, or Scoring occurred during the window.
- No evidence indicates a security credential, user, project-access, or session
  record acquired a post-baseline timestamp. Without the pre database, a
  categorical claim that no undated security-sensitive field changed would be
  too strong.

## 9. Cleanup disposition

No cleanup is proven safe and none is proposed for execution.

Although the 42 mirrored records are anonymous denial audits, they have no
recognizable test run ID, no PID/request lineage, and no source-test identifier.
They are also audit evidence of a real isolation failure. They therefore do not
meet the required standard for proven synthetic cleanup: exact lineage, exact
source test/run, and demonstrated absence of legitimate references. Do not
delete, reverse, repair, or restore them.

## 10. Read-only SQLite sidecar incident

An initial ordinary SQLite CLI `-readonly` open against the live persistence
path refreshed `server\data\atlas_local.db-shm`. The scenario stopped
immediately. The main persistence and security database sizes, timestamps, and
SHA-256 hashes remained unchanged; no database-record write was observed. The
coordination file was 32,768 bytes and had last-write time
`2026-08-04T16:42:43.2269098Z`.

This proves that ordinary `-readonly` is not a sufficient no-filesystem-write
control for a live WAL database. Every subsequent forensic query used the
verified external copies with `mode=ro&immutable=1`. No sidecar appeared beside
those copies, and their hashes remained unchanged. The live sidecar was not
deleted, restored, or otherwise manipulated.

## 11. Operational output incident

During a broad static source search, command output exposed a source-defined
local-development password-default literal from
`server/security/security_store.py`. It was not read from an environment
variable, live credential record, session, cookie, or authentication payload,
and it is intentionally not repeated here. Nevertheless, printing any password
literal violated the task's no-password-output constraint. No live
authentication/session data was read. This incident is an operational
limitation separate from the database-forensic conclusions.

## 12. Unresolved limitations

1. No verified pre-change database copy exists, so row-level before/after proof,
   before-row hashes, deleted-row detection, and changed-column attribution are
   unavailable.
2. Pre-change table counts and canonical table/schema hashes were not captured.
3. The database records do not contain a request ID, process ID, test run ID, or
   endpoint path sufficient to identify the originating process.
4. WAL/SHM sidecars were not preserved at the original drift timestamp.
5. Post-only timestamp scans cannot exclude an undated update or deletion.
6. The earlier manifest hashed main database files, not a transactionally
   consistent snapshot including WAL state.
7. The source-literal output incident means the broader run cannot honestly
   claim that no password-like value was printed.

## 13. Safety confirmations

- No live database was queried after the SQLite sidecar incident.
- No database record was inserted, updated, deleted, repaired, restored, or
  migrated by this forensic analysis.
- Migration `0028` was not applied or edited.
- No service was started, stopped, killed, or restarted by this analysis.
- No model training, Evaluation, Interpretation, promotion, or Scoring occurred.
- No sealed-holdout rows, positions, memberships, assignment JSON, or values were
  accessed.
- No raw dataset row, evidence payload, MDD narrative, model binary, password
  hash, token, cookie, session body, authentication header, API key, connection
  string, or environment-variable value was printed by the database queries.
- The Git index was not touched. Nothing was staged, committed, pushed, reset,
  restored, checked out, cleaned, amended, rebased, merged, cherry-picked,
  stashed, deleted, or discarded.
- No cleanup action was performed or authorized.

## 14. Post-harness live-authority addendum (18:02 UTC)

Later read-only checks established that both live database main files advanced
again to approximately `2026-08-04T17:25:47Z`, after the verified 15:05
forensic copies. The current main-file hashes therefore differ from the copies
used for the table-level analysis above. No listener was present on ports 5174
or 8001 during the final checks, and no ATLAS service was stopped or otherwise
changed by this phase. The process that advanced or continued to hold the live
authorities remains unresolved.

The final fail-closed preflight found:

- no `-wal`, `-shm`, or `-journal` sidecar for either database;
- a stable persistence main-file SHA-256 across two reads,
  `F80E5AA452ECEEACA08FD92A335F4EB0FBC8B4481829F48B8DA7D93F3B42517C`,
  and zero raw-byte occurrences of the hermetic canary prefix;
- zero canary occurrences in 645 safe JSON artifacts (one under `.runtime` and
  644 under `server/artifacts`), with zero read, enumeration, or stability
  failures; and
- a continuing Windows sharing violation on the live security database when a
  strict non-writer read handle was requested.

The security sharing lock was not weakened or bypassed. No new snapshot was
created and no current live database was opened with SQLite. Consequently, the
verified 15:05 copy continues to prove the historical HELOC state described in
Section 7, but it cannot prove the current live logical state, and the final
security-database canary count is unavailable. This is a blocking forensic
evidence limitation even though every hermetic child manifest resolved its
authorities outside the repository and the available live canary scans were
clean.

The earlier source-output incident recurred once during a provider-inventory
read: a source-defined local-development password-default literal was emitted
by command output. It was not obtained from an environment variable, database,
credential record, cookie, session, or authentication request and is not
repeated in this report. The run therefore cannot truthfully confirm that no
password-like literal was printed.
