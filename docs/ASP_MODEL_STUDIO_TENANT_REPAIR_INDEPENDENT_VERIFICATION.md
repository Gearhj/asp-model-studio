# ASP Model Studio tenant-isolation / Wave 2 / Stage 3 repair — independent verification

Narrow, audit-only verification of the completed Codex repair
`codex/model-studio-tenant-workflow-repair-v1` @ `9f02e6835f578b13d0429d0a7442b3634048f8f2`.
No application source was modified; nothing was integrated, merged, or pushed. All
dynamic and concurrency testing used disposable SQLite databases, synthetic
users/projects, and temporary runtime roots. The authoritative database and
canonical runtime objects were opened read-only only for snapshots.

**Verdict: `ASP_MODEL_STUDIO_REPAIR_INDEPENDENTLY_VERIFIED_GO_FOR_INTEGRATION`.**

## 1. Lineage and scope

All four commit hashes match expected exactly (repair `9f02e683`, wave2 `bff19a8`,
main `924db29`, audit `3a70c98`). The repair is a **linear 8-commit descendant** of
the Wave 2 base; the primary checkout (`codex/mlb-governed-prior-engine-v1` @
`33cd85f`) is a clean earlier point on the **same line** (0 divergent commits).

The 8-commit delta touches only the six declared repair areas: project membership
and ACL security, project write atomicity, Stage 3 route scope, Wave 2 canonical
publication, downstream project binding, and tests/evidence. The 242k insertions
are almost entirely committed evidence documentation (`docs/tenant-stage3-repair-v1`,
`docs/repair-evidence`); application source changes are ~2–3k lines. **Wave 2 prior
estimator math is unchanged** (no prior_estimators/sufficient-statistics/estimator
files in the diff); **no runtime object, receipt, or manifest was rewritten**; no
deletions or renames. `main` and every original worktree are unchanged.

## 2. Original defects — independently reproduced on the Wave 2 base

- **F-001 (project takeover)**: On the base, project creation writes no owner ACL
  row, so the `first_owner_claim` bootstrap accepted any self-grant. User A called
  `grant_project_access` on User B's project and **gained admin** (A's view →
  `allowed, permission=admin`, A now in the ACL). Reproduced.
- **F-004 (ACL disclosure)**: Base `list_project_access(project_id)` takes no user
  and performs no authorization — it returns ACL rows to any caller and
  distinguishes an existing project from an unknown one. Reproduced.
- **Atomic create/update race**: With a synchronization barrier (Events, not
  sleeps), A cleared `_authorize_project(allow_missing=True)` while the project was
  absent, B created and committed it, and A's `upsert` overwrote it — final DB
  state `created_by=B, updated_by=A, name="A-HIJACKED"`. **Takeover reproduced.**

## 3. Repaired behaviour — independently verified on the repair HEAD

| Check | Result |
| --- | --- |
| F-001 foreign self-grant | **403** "Project access administration is not available."; no membership, no role change; A cannot view |
| F-004 foreign ACL read | **403**; unknown project also **403** (nondisclosure consistent); non-owner describe_access returns only the caller's own permission |
| Atomic race, 25 concurrent rounds | **0 takeovers**; A denied (403/409) in all 13 rounds where B won the create; 0 names hijacked |
| Same-ID creation, 10 rounds | exactly one winner each; one owner membership each; loser update denied 10/10; no duplicates |
| Audit rollback | injected audit-persistence failure → whole transaction rolls back (no project row, no ACL rows) |
| Legitimate owner/admin/viewer | owner reads own ACL and grants; granted viewer can view but not edit (403) |

The fix moves authorization **inside** a `BEGIN IMMEDIATE` ACL transaction; owner
and creator are forced to the caller and cannot be set via payload; `update_locked`
carries an owner/created_by identity guard in its WHERE clause; `create` is a plain
INSERT (409 on conflict); the mutation audit commits in the same transaction.

## 4. Stage 3 route authorization (F-006)

Every **active project-bearing** Stage 3 route is project-scoped:
`server/persistence/persistence_router.py` 73/73 path routes guarded; the cockpit
router has 38 active guarded routes + **9 retired routes returning HTTP 410**. The
legacy `/cockpit/*` reader routes now require `require_legacy_research_project`
(which chains `require_project_view` and an authenticated Gen-2 binding). The scope
primitive `authorize_modeling_scope` enforces owner→allow, foreign→403, anon→403,
viewer-edit→403, missing→404, blank→400. The 14 other flagged routes
(credit-risk/validation/bureau-metadata/analytics-engine/registry) are pre-existing
legacy routes untouched by the repair — not Stage 3, not a regression. The repair's
real-httpx route-authorization suite passes (215 checks).

## 5. Wave 2 canonical publication

The resolver default changed from the cwd-relative `DEFAULT_AUTHORITY_ROOT` (the
disposable worktree, the F-002 defect) to `runtime_prior_root()` (governed runtime
root). The canonical root in the primary `.runtime` resolves the `asp-mtlozhdx`
pointer to fit bundle `bac2d184`, whose `authorityId` **is** the expected
`9d9cfaf3` — self-contained (9 content-addressed objects), **without referencing the
disposable worktree**. All expected authorities match: authority `9d9cfaf3`, final
`5ae0f9f5`, Gold `67de02ce`, companion `98673b65`, 5 folds + fold contract
`cd720585`, development 683,662 rows, final-OOT 14,067 rows
`KEY_ONLY_UNMATERIALIZED_LOCKED_UNOPENED` with `payloadRowsRead=0`. On a disposable
copy, every tamper (object manifest, bundle fold/Gold checksum, pointer repoint) is
**detected / fails closed**.

## 6. Downstream project binding (F-003)

The base hard-coded the pilot `asp-mtddc6pw` / `EXPECTED_PROJECT_ID` in the
executable-artifact, game-scoring, and model-lab modules (7 occurrences). The repair
server source contains **zero** hard-coded pilot occurrences; downstream resolves
the active project's authorities. Combined with the verified project scoping, pilot
candidates/receipts/finalist/champion cannot leak into the challenger's views. The
prior-publication, downstream-workflow, project-model-laboratory, and
candidate-evaluation suites pass (72 tests).

## 7. Protected scientific boundaries

Zero authoritative fits, tuning runs, scores, calibrations, promotions, champion
changes, policy adoptions, feature-set registrations, Gold/companion mutations,
final-OOT opens, or provider calls were performed. The science authority SHAs all
match expected and are unchanged; final-OOT payloadRowsRead is 0. See the
protected-state and OOT-access receipts.

## 8. Tests

446 repair tests pass as-committed on the repair HEAD (374 tenant/Stage-3 +
72 Wave-2/downstream), plus the independent service and concurrency harnesses
above. No test was modified. The frontend `.mjs` contract tests and a live
3-viewport browser session were **not** run because the isolated verification
worktree was not provisioned with a built frontend; the frontend project-binding is
covered at the source layer and by the real-httpx route-authorization suite. This
does not affect any GO-gate criterion.

## 9. Integration

A clean, non-destructive **fast-forward** onto `main`, the primary branch, or wave2
is possible (linear, zero divergence). See
`ASP_MODEL_STUDIO_REPAIR_INTEGRATION_RUNBOOK.md`.

## 10. Verdict

All GO-gate criteria are independently satisfied: the atomic race is closed;
foreign membership and ACL access are closed; all active project-bearing Stage 3
routes are scoped; the Wave 2 authority resolves canonically; the challenger shows
no pilot evidence; and no scientific authority or OOT evidence was altered.

**`ASP_MODEL_STUDIO_REPAIR_INDEPENDENTLY_VERIFIED_GO_FOR_INTEGRATION`.**
