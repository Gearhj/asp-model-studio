# Historical prepared-patch review — superseded

The user subsequently approved both exact patches, which are now applied and committed as `b5af4211b446f1a470b71cbda4bd6724f50346b9`. The following text records the earlier pre-approval state, not the current result. See [SECURITY_COMPLETION_REPORT.md](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/security-completion/SECURITY_COMPLETION_REPORT.md>) for passing standard checks and the additional concurrency blocker.

# Prepared tenant-authorization repair

Status: prepared and statically checked; **not applied or verified after repair**. Automatic approval review rejected the narrow apply operation twice because it treated the prior backup-only request as authoritative instead of the latest repair attachment. No workaround application or source mirror was used.

The latest repair mandate is `C:\Users\james\.codex\attachments\cce76256-1fac-4ca0-98fb-d44abccb3be6\pasted-text.txt`. The destination is exclusively `C:\Users\james\worktrees\asp-model-studio-tenant-workflow-repair-v1`, branch `codex/model-studio-tenant-workflow-repair-v1`, initially `bff19a8a657bc96dea0469fad481acdcb4234386`.

## Evidence and reproduction

The audit was read at `C:\Users\james\worktrees\asp-model-studio-fable51-audit`, exact HEAD `3a70c98b485a6e9450782ad6d296add0ea7f49d6`; its changes relative to Wave 2 are additions under `docs/` only.

- F-001: authenticated nonowner can self-grant legacy `owner` (mapped to project `admin`) when a project has no explicit permission rows. Exact Wave 2 HTTP reproduction returned 200 for User A granting themselves ownership-equivalent access to User B's project, followed by 200 reading that project.
- F-004: foreign authenticated user can read `/projects/{project_id}/access`; exact Wave 2 reproduction returned 200.
- Connected causes reproduced: guessed-ID orphan grants; POST with an existing project ID overwrites its owner; an editor can replace the canonical owner through the PUT body; membership details leak through the parallel sharing-status endpoint; audit storage failure leaves a committed grant.

`tenant-security-before-final.json` records 29 checks: 13 pass, 16 fail on the exact starting base. Several later failures are consequences of the earlier disposable takeovers, and are labelled by probe. Both ordinary users initially own two projects; one independent administrator is also present. The disposable database integrity check returns `ok`.

All SQLite connections were checked to remain under the unique disposable runtime root. The probe used Model Studio's own Python, disabled external socket connections, required an isolated sports runtime root, and generated temporary authentication material in memory. It performed zero operational database writes, provider calls, science-object reads, authoritative fits or final-OOT opens.

## Concrete changes

The six-file patch is `tenant-security.patch`:

1. `server/security/security_store.py`: removes public self-owner bootstrap; validates canonical ACL administration before target synchronization; requires authenticated user context for ACL listing; treats repeated identical grants as nonmutating.
2. `server/security/security_router.py`: supplies the authenticated actor to ACL listing; documents the general grant's lack of bootstrap exceptions.
3. `server/sharing/sharing_service.py`: requires canonical project owner or workspace administrator for project ACL administration; keeps unknown and foreign ACL errors identical; provides only a private creation bootstrap; validates supported principals and product permission levels; makes duplicate grants idempotent; prevents downgrading or revoking owner-of-record; returns only the member's effective access to ordinary members; wraps project ACL, collaborator, notification and attributable audit writes in one SQLite transaction.
4. `server/persistence/persistence_router.py`: project creation takes owner/creator/updater from authentication; existing IDs cannot be overwritten by POST; PUT preserves owner and creator and rejects attempted replacement; new project creation calls the private bootstrap only after the owner record exists.
5. `server/persistence/repositories/project_repository.py`: adds insert-only project creation, preventing a racing upsert from replacing another creator's project.
6. `src/steps/NewProject.tsx`: awaits durable server creation for every workflow type and removes the browser's public self-grant call.

The separate `tenant-security-tests.patch` adds `tests/tenant_project_access_repair_test.py`. It launches a fresh isolated subprocess for a 30-probe two-user/two-project matrix: self-grant, modern/legacy unauthorized invite/revoke/ACL reads, member elevation and owner spoofing, server creator bootstrap, owner/admin permissions, duplicate idempotence, immediate revocation, unknown/foreign nondisclosure, membership enumeration suppression, audit-failure rollback, attributable allowed audit events and simultaneous users. Synthetic credentials are generated in memory, never stored as fixtures or printed.

## Requirement review

| Phase A requirement | Prepared implementation |
|---|---|
| Nonadministrators cannot grant foreign project access | Canonical owner/workspace-admin gate in the underlying service, before ACL writes |
| Creator membership through server bootstrap | Private creation-only hook validates the persisted owner |
| Bootstrap cannot act as general grant | No HTTP bootstrap route or bypass flag; public grant always authorizes existing owner |
| Acting user is authenticated | Router dependency plus forced creation/update provenance |
| Members cannot self-elevate | Generic grants and owner changes both blocked |
| Owner grants product roles only | Validated against existing `PERMISSION_LEVELS`; legacy aliases remain mapped |
| Workspace administration works | Explicit authenticated `admin` role accepted on existing projects |
| Duplicate membership idempotent | Same target/permission/expiry returns existing grant before mutation |
| Revocation immediate | Existing active-permission lookup reads current database status on each request |
| Allowed ACL changes attributable | ACL and persistence audit share one transaction; audit failure rolls back grant |
| Denied ACL mutations unchanged | Denial occurs before domain writes; tests snapshot project, permission, collaborator, sharing-event, notification and audit tables |
| Nonmembers receive no sensitive detail | Same ACL status/payload for unknown and foreign IDs; no membership enumeration before authorization |

The unchanged-state assertion concerns authorization-domain tables. Existing authentication activity updates in security sessions and persistence users are not falsely represented as a byte-for-byte unchanged authentication database. ACL denial itself adds no audit or membership mutations.

## Product-role interpretation

The existing product exposes `view`, `comment`, `edit`, `validate`, `approve`, `export`, and `admin`; an owner may grant those existing levels. Legacy `owner` remains the existing alias for project `admin`, preserving authorized project operations, but does not transfer canonical ownership or let that member administer the ACL. Canonical owners and workspace administrators alone can administer project membership. Ordinary members can retrieve their own effective access through sharing status; membership lists, owner ID, grant events and share links are withheld. No new product role was invented.

## Remaining verification

Both patches pass `git apply --check`; all reconstructed Python files and the focused test parse with `ast.parse`. No after-repair behavioral pass is claimed. After specific approval resolves the reviewer block, apply only the two prepared patches in the isolated repair worktree, run the focused test and independent before/after probe, then existing security and relevant frontend suites. The source/apply checks must be rerun if concurrent edits change patch context.

The two patches were not committed or pushed. The protected primary and Wave 2 checkouts and their runtime artifacts were not modified by this subtask.
